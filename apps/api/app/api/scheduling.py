"""Scheduling API (M2). Mounted under /api/clinics/{clinic_id}. Every route is clinic-scoped.

Errors use `{"error": {"code", "message", "details"?}}` (see docs/scheduling.md).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Patient
from app.scheduling import auth as auth_mod
from app.scheduling.adapter import Caller, OperationContext, PostgresSchedulingAdapter
from app.scheduling.errors import InvalidInput
from app.scheduling.idempotency import Outcome
from app.scheduling.published import ensure_clinic
from app.scheduling.runtime import Clock, Faults, get_clock, get_faults
from app.schemas.scheduling import (
    AppointmentEventRead,
    AppointmentRead,
    AvailabilityResponse,
    BookRequest,
    CancelRequest,
    ConfirmRequest,
    OperationRead,
    OperationResult,
    PatientSummary,
    ProposalCreate,
    ProposalRead,
    RescheduleRequest,
    SchedulingInfo,
    VerifyRequest,
    VerifyResponse,
)

router = APIRouter(prefix="/clinics/{clinic_id}", tags=["scheduling"])

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9._:\-]{8,128}$"
ERROR_STATUSES: dict[int | str, dict[str, str]] = {
    code: {"description": "Error"} for code in (401, 403, 404, 409, 410, 422, 429, 503)
}


def get_adapter(
    clock: Clock = Depends(get_clock), faults: Faults = Depends(get_faults)
) -> PostgresSchedulingAdapter:
    return PostgresSchedulingAdapter(get_sessionmaker(), clock, faults)


Adapter = Annotated[PostgresSchedulingAdapter, Depends(get_adapter)]


def _bearer(authorization: Annotated[str | None, Header()] = None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


Token = Annotated[str | None, Depends(_bearer)]
IdemKey = Annotated[str, Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_PATTERN)]


def _respond(outcome: Outcome) -> JSONResponse:
    return JSONResponse(
        outcome.body,
        status_code=outcome.http_status,
        headers={
            "Idempotent-Replay": "true" if outcome.replayed else "false",
            "X-Operation-Id": str(outcome.operation_id),
        },
    )


# ---- patients & verification (simulated) -------------------------------------------------
@router.get("/patients", response_model=list[PatientSummary], summary="Look up synthetic patients")
async def lookup_patients(
    clinic_id: uuid.UUID,
    name: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    phone: Annotated[str | None, Query(min_length=4, max_length=40)] = None,
) -> list[PatientSummary]:
    """Demo directory of fictional patients. Returns id and name only, never other fields."""
    if not name and not phone:
        raise InvalidInput("Provide name or phone.")
    async with get_sessionmaker()() as session:
        await ensure_clinic(session, clinic_id)
        query = select(Patient).where(Patient.clinic_id == clinic_id)
        if name:
            query = query.where(Patient.full_name.ilike(f"%{name}%"))
        if phone:
            query = query.where(Patient.phone.contains(phone))
        rows = await session.scalars(query.order_by(Patient.full_name).limit(10))
        return [PatientSummary(id=p.id, full_name=p.full_name) for p in rows]


@router.post(
    "/patients/{patient_id}/verify",
    response_model=VerifyResponse,
    summary="Verify a synthetic patient (simulated) and receive an expiring authorization",
)
async def verify_patient(
    clinic_id: uuid.UUID,
    patient_id: uuid.UUID,
    body: VerifyRequest,
    clock: Clock = Depends(get_clock),
) -> VerifyResponse:
    return await auth_mod.verify_patient(get_sessionmaker(), clinic_id, patient_id, body, clock())


# ---- availability ---------------------------------------------------------------------------
@router.get("/scheduling", response_model=SchedulingInfo, summary="Published scheduling info")
async def scheduling_info(clinic_id: uuid.UUID, adapter: Adapter) -> SchedulingInfo:
    return await adapter.scheduling_info(clinic_id)


@router.get(
    "/availability",
    response_model=AvailabilityResponse,
    summary="Open slots (informational; revalidated at booking)",
)
async def availability(
    clinic_id: uuid.UUID,
    adapter: Adapter,
    appointment_type_id: uuid.UUID,
    date_from: date,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> AvailabilityResponse:
    return await adapter.get_availability(
        clinic_id, appointment_type_id, date_from, date_to or date_from, limit
    )


# ---- patient appointments & history --------------------------------------------------------
@router.get(
    "/patients/{patient_id}/appointments",
    response_model=list[AppointmentRead],
    summary="List a verified patient's appointments",
)
async def patient_appointments(
    clinic_id: uuid.UUID,
    patient_id: uuid.UUID,
    adapter: Adapter,
    token: Token,
    include_cancelled: bool = False,
) -> list[AppointmentRead]:
    return await adapter.get_patient_appointments(
        Caller(clinic_id, token), patient_id, include_cancelled
    )


@router.get(
    "/appointments/{appointment_id}/events",
    response_model=list[AppointmentEventRead],
    summary="Audit history of an appointment",
)
async def appointment_events(
    clinic_id: uuid.UUID, appointment_id: uuid.UUID, adapter: Adapter, token: Token
) -> list[AppointmentEventRead]:
    return await adapter.get_appointment_events(Caller(clinic_id, token), appointment_id)


# ---- proposals / confirmation ---------------------------------------------------------------
@router.post(
    "/proposals",
    response_model=ProposalRead,
    status_code=201,
    summary="Propose an operation; returns a one-time confirmation token",
)
async def create_proposal(
    clinic_id: uuid.UUID, body: ProposalCreate, adapter: Adapter, token: Token
) -> ProposalRead:
    return await adapter.propose_operation(Caller(clinic_id, token), body)


@router.get("/proposals/{proposal_id}", response_model=ProposalRead)
async def read_proposal(
    clinic_id: uuid.UUID, proposal_id: uuid.UUID, adapter: Adapter, token: Token
) -> ProposalRead:
    return await adapter.get_proposal(Caller(clinic_id, token), proposal_id)


@router.post("/proposals/{proposal_id}/confirm", response_model=ProposalRead)
async def confirm_proposal(
    clinic_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ConfirmRequest,
    adapter: Adapter,
    token: Token,
) -> ProposalRead:
    return await adapter.confirm_proposal(
        Caller(clinic_id, token), proposal_id, body.confirmation_token
    )


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalRead)
async def reject_proposal(
    clinic_id: uuid.UUID, proposal_id: uuid.UUID, adapter: Adapter, token: Token
) -> ProposalRead:
    return await adapter.reject_proposal(Caller(clinic_id, token), proposal_id)


# ---- state-changing operations (idempotent; require a confirmed proposal) ---------------------
@router.post(
    "/appointments",
    response_model=OperationResult,
    status_code=201,
    responses=ERROR_STATUSES,
    summary="Book an appointment",
)
async def book(
    clinic_id: uuid.UUID, body: BookRequest, adapter: Adapter, token: Token, key: IdemKey
) -> JSONResponse:
    return _respond(await adapter.book_appointment(OperationContext(clinic_id, token, key), body))


@router.post(
    "/appointments/{appointment_id}/reschedule",
    response_model=OperationResult,
    responses=ERROR_STATUSES,
    summary="Reschedule an appointment atomically",
)
async def reschedule(
    clinic_id: uuid.UUID,
    appointment_id: uuid.UUID,
    body: RescheduleRequest,
    adapter: Adapter,
    token: Token,
    key: IdemKey,
) -> JSONResponse:
    return _respond(
        await adapter.reschedule_appointment(
            OperationContext(clinic_id, token, key), appointment_id, body
        )
    )


@router.post(
    "/appointments/{appointment_id}/cancel",
    response_model=OperationResult,
    responses=ERROR_STATUSES,
    summary="Cancel an appointment (soft: the row is kept)",
)
async def cancel(
    clinic_id: uuid.UUID,
    appointment_id: uuid.UUID,
    body: CancelRequest,
    adapter: Adapter,
    token: Token,
    key: IdemKey,
) -> JSONResponse:
    return _respond(
        await adapter.cancel_appointment(
            OperationContext(clinic_id, token, key), appointment_id, body
        )
    )


# ---- reconciliation -------------------------------------------------------------------------
@router.get("/operations", response_model=OperationRead, summary="Look up an operation by key")
async def operation_by_key(
    clinic_id: uuid.UUID,
    adapter: Adapter,
    token: Token,
    idempotency_key: Annotated[str, Query(min_length=1, max_length=128)],
) -> OperationRead:
    return await adapter.get_operation(Caller(clinic_id, token), idempotency_key=idempotency_key)


@router.get("/operations/{operation_id}", response_model=OperationRead)
async def operation_by_id(
    clinic_id: uuid.UUID, operation_id: uuid.UUID, adapter: Adapter, token: Token
) -> OperationRead:
    return await adapter.get_operation(Caller(clinic_id, token), operation_id=operation_id)
