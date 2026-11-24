"""The scheduling adapter contract the future voice agent (M3) calls.

`SchedulingAdapter` is the boundary: typed requests/responses, explicit clinic identity,
explicit authorization and explicit operation context. `PostgresSchedulingAdapter` is the only
implementation: it is backed by the CareDeploy PostgreSQL scheduling domain (a *simulated* EHR).

A real external EHR adapter would implement the same Protocol (see docs/scheduling.md); nothing
here claims or provides a real Epic/Cerner/etc. integration.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Operation
from app.scheduling import service
from app.scheduling.auth import AuthContext, authorize, require_patient
from app.scheduling.errors import Forbidden, NotFound
from app.scheduling.idempotency import Outcome, execute
from app.scheduling.published import PublishedConfig, load_published
from app.scheduling.runtime import Clock, Faults
from app.schemas.scheduling import (
    AppointmentEventRead,
    AppointmentRead,
    AvailabilityResponse,
    BookRequest,
    CancelRequest,
    OperationRead,
    OperationResult,
    ProposalCreate,
    ProposalRead,
    RescheduleRequest,
    SchedulableType,
    SchedulingInfo,
)


@dataclass(frozen=True)
class Caller:
    """Who is calling: a clinic and the bearer token of a verified patient."""

    clinic_id: uuid.UUID
    token: str | None


@dataclass(frozen=True)
class OperationContext(Caller):
    """A caller plus the idempotency key for one state-changing request."""

    idempotency_key: str = ""


class SchedulingAdapter(Protocol):
    async def get_availability(
        self,
        clinic_id: uuid.UUID,
        appointment_type_id: uuid.UUID,
        date_from: date,
        date_to: date,
        limit: int = 200,
    ) -> AvailabilityResponse: ...

    async def get_patient_appointments(
        self, caller: Caller, patient_id: uuid.UUID, include_cancelled: bool = False
    ) -> list[AppointmentRead]: ...

    async def propose_operation(self, caller: Caller, body: ProposalCreate) -> ProposalRead: ...

    async def confirm_proposal(
        self, caller: Caller, proposal_id: uuid.UUID, confirmation_token: str
    ) -> ProposalRead: ...

    async def reject_proposal(self, caller: Caller, proposal_id: uuid.UUID) -> ProposalRead: ...

    async def book_appointment(self, ctx: OperationContext, req: BookRequest) -> Outcome: ...

    async def reschedule_appointment(
        self, ctx: OperationContext, appointment_id: uuid.UUID, req: RescheduleRequest
    ) -> Outcome: ...

    async def cancel_appointment(
        self, ctx: OperationContext, appointment_id: uuid.UUID, req: CancelRequest
    ) -> Outcome: ...

    async def get_operation(
        self,
        caller: Caller,
        *,
        operation_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> OperationRead: ...


class PostgresSchedulingAdapter:
    def __init__(self, sm: async_sessionmaker[AsyncSession], clock: Clock, faults: Faults) -> None:
        self._sm = sm
        self._clock = clock
        self._faults = faults

    # ---- helpers ----------------------------------------------------------------------
    async def _auth(self, session: AsyncSession, caller: Caller) -> AuthContext:
        return await authorize(session, caller.clinic_id, caller.token, self._clock())

    async def scheduling_info(self, clinic_id: uuid.UUID) -> SchedulingInfo:
        async with self._sm() as session:
            cfg = await load_published(session, clinic_id)
        return SchedulingInfo(
            clinic_id=clinic_id,
            timezone=cfg.rules.timezone_name,
            config_version=cfg.rules.version,
            appointment_types=[
                SchedulableType(
                    id=t.id,
                    name=t.name,
                    duration_minutes=t.duration_minutes,
                    requires_human_escalation=t.requires_human_escalation,
                )
                for t in cfg.types.values()
            ],
        )

    # ---- reads ------------------------------------------------------------------------
    async def get_availability(
        self,
        clinic_id: uuid.UUID,
        appointment_type_id: uuid.UUID,
        date_from: date,
        date_to: date,
        limit: int = 200,
    ) -> AvailabilityResponse:
        async with self._sm() as session:
            cfg = await load_published(session, clinic_id)
            return await service.get_availability(
                session, cfg, appointment_type_id, date_from, date_to, limit, self._clock()
            )

    async def get_patient_appointments(
        self, caller: Caller, patient_id: uuid.UUID, include_cancelled: bool = False
    ) -> list[AppointmentRead]:
        async with self._sm() as session:
            ctx = await self._auth(session, caller)
            return await service.list_patient_appointments(
                session, ctx, patient_id, include_cancelled
            )

    async def get_appointment_events(
        self, caller: Caller, appointment_id: uuid.UUID
    ) -> list[AppointmentEventRead]:
        async with self._sm() as session:
            ctx = await self._auth(session, caller)
            return await service.appointment_events(session, ctx, appointment_id)

    # ---- confirmation -----------------------------------------------------------------
    async def propose_operation(self, caller: Caller, body: ProposalCreate) -> ProposalRead:
        async with self._sm() as session, session.begin():
            ctx = await self._auth(session, caller)
            cfg = await load_published(session, caller.clinic_id)
            return await service.create_proposal(session, cfg, ctx, body, self._clock())

    async def get_proposal(self, caller: Caller, proposal_id: uuid.UUID) -> ProposalRead:
        async with self._sm() as session:
            ctx = await self._auth(session, caller)
            return await service.read_proposal(session, ctx, proposal_id, self._clock())

    async def confirm_proposal(
        self, caller: Caller, proposal_id: uuid.UUID, confirmation_token: str
    ) -> ProposalRead:
        async with self._sm() as session, session.begin():
            ctx = await self._auth(session, caller)
            return await service.confirm_proposal(
                session, ctx, proposal_id, confirmation_token, self._clock()
            )

    async def reject_proposal(self, caller: Caller, proposal_id: uuid.UUID) -> ProposalRead:
        async with self._sm() as session, session.begin():
            ctx = await self._auth(session, caller)
            return await service.reject_proposal(session, ctx, proposal_id, self._clock())

    # ---- state-changing operations ----------------------------------------------------
    async def _run(
        self,
        ctx: OperationContext,
        operation_type: str,
        proposal_id: uuid.UUID,
        bound: dict[str, Any],
        apply: Any,
    ) -> Outcome:
        now = self._clock()
        async with self._sm() as session:
            auth = await authorize(session, ctx.clinic_id, ctx.token, now)

        async def work(
            session: AsyncSession, op_id: uuid.UUID
        ) -> tuple[dict[str, Any], uuid.UUID, int]:
            cfg: PublishedConfig = await load_published(session, ctx.clinic_id)
            proposal = await service.consume_proposal(session, auth, proposal_id, bound, op_id, now)
            appt = await apply(session, cfg, auth, op_id, proposal.payload)
            result = OperationResult(
                operation_id=op_id,
                operation_type=operation_type,  # type: ignore[arg-type]
                appointment=service.appointment_read(appt),
            )
            return result.model_dump(mode="json"), appt.id, 201 if operation_type == "book" else 200

        return await execute(
            self._sm,
            clinic_id=ctx.clinic_id,
            patient_id=auth.patient_id,
            operation_type=operation_type,
            idempotency_key=ctx.idempotency_key,
            fingerprint=service.canonical_hash(
                {
                    "operation": operation_type,
                    "clinic_id": str(ctx.clinic_id),
                    "patient_id": str(auth.patient_id),
                    "proposal_id": str(proposal_id),
                    "details": bound,
                }
            ),
            proposal_id=proposal_id,
            work=work,
            clock=self._clock,
            faults=self._faults,
        )

    async def book_appointment(self, ctx: OperationContext, req: BookRequest) -> Outcome:
        bound = service.bound_details(
            "book", appointment_type_id=req.appointment_type_id, start_at=req.start_at
        )
        now = self._clock()

        async def apply(
            session: AsyncSession,
            cfg: PublishedConfig,
            auth: AuthContext,
            op_id: uuid.UUID,
            _p: Any,
        ) -> Any:
            return await service.book(
                session, cfg, auth, req.appointment_type_id, req.start_at, op_id, now
            )

        return await self._run(ctx, "book", req.proposal_id, bound, apply)

    async def reschedule_appointment(
        self, ctx: OperationContext, appointment_id: uuid.UUID, req: RescheduleRequest
    ) -> Outcome:
        bound = service.bound_details(
            "reschedule", appointment_id=appointment_id, new_start_at=req.new_start_at
        )
        now = self._clock()

        async def apply(
            session: AsyncSession, cfg: PublishedConfig, auth: AuthContext, op_id: uuid.UUID, p: Any
        ) -> Any:
            return await service.reschedule(
                session,
                cfg,
                auth,
                appointment_id,
                req.new_start_at,
                int(p["appointment_row_version"]),
                op_id,
                now,
            )

        return await self._run(ctx, "reschedule", req.proposal_id, bound, apply)

    async def cancel_appointment(
        self, ctx: OperationContext, appointment_id: uuid.UUID, req: CancelRequest
    ) -> Outcome:
        bound = service.bound_details("cancel", appointment_id=appointment_id, reason=req.reason)
        now = self._clock()

        async def apply(
            session: AsyncSession, cfg: PublishedConfig, auth: AuthContext, op_id: uuid.UUID, p: Any
        ) -> Any:
            return await service.cancel(
                session,
                cfg,
                auth,
                appointment_id,
                req.reason,
                int(p["appointment_row_version"]),
                op_id,
                now,
            )

        return await self._run(ctx, "cancel", req.proposal_id, bound, apply)

    # ---- reconciliation ---------------------------------------------------------------
    async def get_operation(
        self,
        caller: Caller,
        *,
        operation_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> OperationRead:
        async with self._sm() as session:
            ctx = await self._auth(session, caller)
            query = select(Operation).where(Operation.clinic_id == ctx.clinic_id)
            if operation_id is not None:
                query = query.where(Operation.id == operation_id)
            elif idempotency_key:
                query = query.where(Operation.idempotency_key == idempotency_key)
            else:
                raise NotFound("Provide an operation id or an idempotency key.")
            op = await session.scalar(query)
            if op is None:
                raise NotFound("Operation not found.")
            require_patient_or_forbid(ctx, op)
            outcome = op.outcome
            return OperationRead(
                id=op.id,
                clinic_id=op.clinic_id,
                patient_id=op.patient_id,
                operation_type=op.operation_type,
                idempotency_key=op.idempotency_key,
                status=op.status,  # type: ignore[arg-type]
                appointment_id=op.appointment_id,
                proposal_id=op.proposal_id,
                http_status=int(outcome["http_status"]) if outcome else None,
                outcome=outcome["body"] if outcome else None,
                attempts=op.attempts,
                created_at=op.created_at,
                completed_at=op.completed_at,
                resolved=op.status in ("succeeded", "failed"),
            )


def require_patient_or_forbid(ctx: AuthContext, op: Operation) -> None:
    try:
        require_patient(ctx, op.patient_id)
    except Forbidden:
        raise Forbidden("This authorization does not apply to this operation.") from None
