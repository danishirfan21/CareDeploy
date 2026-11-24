"""Transactional scheduling operations. Every function takes an open AsyncSession; the caller
owns the transaction boundary (commit/rollback), so a failure never leaves partial state."""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Appointment, AppointmentEvent, Patient, Proposal
from app.scheduling import engine
from app.scheduling.auth import AuthContext, hash_token, new_secret, require_patient
from app.scheduling.engine import Slot, TypeInfo
from app.scheduling.errors import (
    AppointmentModified,
    Forbidden,
    InvalidInput,
    InvalidStateTransition,
    NotFound,
    PolicyViolation,
    ProposalAlreadyUsed,
    ProposalExpired,
    ProposalMismatch,
    ProposalNotConfirmed,
    SlotUnavailable,
)
from app.scheduling.published import PublishedConfig
from app.schemas.scheduling import (
    AppointmentEventRead,
    AppointmentRead,
    AvailabilityResponse,
    ProposalCreate,
    ProposalRead,
    SlotRead,
)

EXCLUSION_VIOLATION = "23P01"


def canonical_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sqlstate(exc: DBAPIError) -> str | None:
    orig: Any = exc.orig
    return getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )


def appointment_read(a: Appointment) -> AppointmentRead:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(a.timezone)
    return AppointmentRead(
        id=a.id,
        clinic_id=a.clinic_id,
        patient_id=a.patient_id,
        appointment_type_id=a.appointment_type_id,
        type_name=a.type_name,
        duration_minutes=a.duration_minutes,
        timezone=a.timezone,
        start_at=a.start_at,
        end_at=a.end_at,
        start_local=a.start_at.astimezone(tz).isoformat(),
        end_local=a.end_at.astimezone(tz).isoformat(),
        status=a.status,  # type: ignore[arg-type]
        config_version=a.config_version,
        reschedule_count=a.reschedule_count,
        row_version=a.row_version,
        cancelled_at=a.cancelled_at,
        cancellation_reason=a.cancellation_reason,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


# ---- reads -------------------------------------------------------------------------------
def _type(cfg: PublishedConfig, type_id: uuid.UUID) -> TypeInfo:
    info = cfg.types.get(type_id)
    if info is None:
        raise NotFound("Appointment type not found for this clinic.")
    return info


async def busy_slots(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exclude: uuid.UUID | None = None,
) -> list[Slot]:
    """Scheduled appointments overlapping [start, end). Uses the exclusion constraint's index."""
    rng = func.tstzrange(Appointment.start_at, Appointment.end_at, "[)")
    query = select(Appointment.start_at, Appointment.end_at).where(
        Appointment.clinic_id == clinic_id,
        Appointment.status == "scheduled",
        rng.op("&&")(func.tstzrange(start, end, "[)")),
    )
    if exclude is not None:
        query = query.where(Appointment.id != exclude)
    return [Slot(s, e) for s, e in (await session.execute(query)).all()]


async def get_availability(
    session: AsyncSession,
    cfg: PublishedConfig,
    type_id: uuid.UUID,
    date_from: date,
    date_to: date,
    limit: int,
    now: datetime,
) -> AvailabilityResponse:
    info = _type(cfg, type_id)
    if date_to < date_from:
        raise InvalidInput("date_to must not be before date_from.")
    if (date_to - date_from).days + 1 > engine.MAX_RANGE_DAYS:
        raise InvalidInput(f"Date range may span at most {engine.MAX_RANGE_DAYS} days.")
    rules = cfg.rules
    slots: list[Slot] = []
    truncated = False
    if not info.requires_human_escalation:
        lo = engine.local_to_utc(date_from, datetime.min.time(), rules.tz)
        hi = engine.local_to_utc(date_to + timedelta(days=1), datetime.min.time(), rules.tz)
        busy = await busy_slots(session, cfg.clinic_id, lo, hi)
        slots, truncated = engine.list_slots(
            rules, info.duration_minutes, date_from, date_to, now, busy, limit
        )
    tz = rules.tz
    return AvailabilityResponse(
        clinic_id=cfg.clinic_id,
        appointment_type_id=type_id,
        timezone=rules.timezone_name,
        config_version=rules.version,
        date_from=date_from,
        date_to=date_to,
        requires_human_escalation=info.requires_human_escalation,
        truncated=truncated,
        slots=[
            SlotRead(
                start_at=s.start,
                end_at=s.end,
                start_local=s.start.astimezone(tz).isoformat(),
                end_local=s.end.astimezone(tz).isoformat(),
            )
            for s in slots
        ],
    )


async def get_patient(
    session: AsyncSession, clinic_id: uuid.UUID, patient_id: uuid.UUID
) -> Patient:
    patient = await session.scalar(
        select(Patient).where(Patient.clinic_id == clinic_id, Patient.id == patient_id)
    )
    if patient is None:
        raise NotFound("Patient not found.")
    return patient


async def list_patient_appointments(
    session: AsyncSession, ctx: AuthContext, patient_id: uuid.UUID, include_cancelled: bool
) -> list[AppointmentRead]:
    require_patient(ctx, patient_id)
    query = select(Appointment).where(
        Appointment.clinic_id == ctx.clinic_id, Appointment.patient_id == patient_id
    )
    if not include_cancelled:
        query = query.where(Appointment.status != "cancelled")
    rows = await session.scalars(query.order_by(Appointment.start_at).limit(200))
    return [appointment_read(a) for a in rows]


async def get_appointment(
    session: AsyncSession,
    ctx: AuthContext,
    appointment_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Appointment:
    query = select(Appointment).where(
        Appointment.clinic_id == ctx.clinic_id, Appointment.id == appointment_id
    )
    if lock:
        query = query.with_for_update()
    appt = await session.scalar(query)
    if appt is None:
        raise NotFound("Appointment not found.")
    if appt.patient_id != ctx.patient_id:
        raise Forbidden("This authorization does not apply to this appointment.")
    return appt


async def appointment_events(
    session: AsyncSession, ctx: AuthContext, appointment_id: uuid.UUID
) -> list[AppointmentEventRead]:
    await get_appointment(session, ctx, appointment_id)
    rows = await session.scalars(
        select(AppointmentEvent)
        .where(
            AppointmentEvent.clinic_id == ctx.clinic_id,
            AppointmentEvent.appointment_id == appointment_id,
        )
        .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
    )
    return [
        AppointmentEventRead(
            id=e.id,
            appointment_id=e.appointment_id,
            operation_id=e.operation_id,
            event_type=e.event_type,
            from_status=e.from_status,
            to_status=e.to_status,
            config_version=e.config_version,
            details=e.details,
            created_at=e.created_at,
        )
        for e in rows
    ]


# ---- rule checks (shared by proposals' dry run and by execution) ------------------------
async def plan_book(
    session: AsyncSession,
    cfg: PublishedConfig,
    type_id: uuid.UUID,
    start: datetime,
    now: datetime,
) -> TypeInfo:
    info = _type(cfg, type_id)
    if info.requires_human_escalation:
        raise PolicyViolation(
            "human_escalation_required",
            f"'{info.name}' must be arranged by clinic staff, not scheduled automatically.",
        )
    engine.check_slot(cfg.rules, info.duration_minutes, start, now)
    end = start + timedelta(minutes=info.duration_minutes)
    if await busy_slots(session, cfg.clinic_id, start, end):
        raise SlotUnavailable("That time is no longer available.")
    return info


def plan_cancel(cfg: PublishedConfig, appt: Appointment, now: datetime) -> None:
    if appt.status != "scheduled":
        raise InvalidStateTransition(f"The appointment is already {appt.status}.")
    if appt.start_at <= now:
        raise PolicyViolation("appointment_in_past", "The appointment has already started.")
    window = cfg.rules.policy.cancellation_window_hours
    if appt.start_at < now + timedelta(hours=window):
        raise PolicyViolation(
            "cancellation_window",
            f"Appointments must be cancelled at least {window} hours in advance.",
            cancellation_window_hours=window,
        )


async def plan_reschedule(
    session: AsyncSession,
    cfg: PublishedConfig,
    appt: Appointment,
    new_start: datetime,
    now: datetime,
) -> None:
    if appt.status != "scheduled":
        raise InvalidStateTransition(f"The appointment is already {appt.status}.")
    if appt.start_at <= now:
        raise PolicyViolation("appointment_in_past", "The appointment has already started.")
    policy = cfg.rules.policy
    if appt.start_at < now + timedelta(hours=policy.reschedule_window_hours):
        raise PolicyViolation(
            "reschedule_window",
            f"Appointments must be rescheduled at least {policy.reschedule_window_hours} "
            "hours in advance.",
            reschedule_window_hours=policy.reschedule_window_hours,
        )
    if appt.reschedule_count >= policy.max_reschedules:
        raise PolicyViolation(
            "max_reschedules",
            f"This appointment has already been rescheduled {appt.reschedule_count} time(s); "
            f"the limit is {policy.max_reschedules}.",
            max_reschedules=policy.max_reschedules,
        )
    if new_start == appt.start_at:
        raise PolicyViolation("no_change", "The new time is the same as the current time.")
    engine.check_slot(cfg.rules, appt.duration_minutes, new_start, now)
    end = new_start + timedelta(minutes=appt.duration_minutes)
    if await busy_slots(session, cfg.clinic_id, new_start, end, exclude=appt.id):
        raise SlotUnavailable("That time is no longer available.")


# ---- proposals --------------------------------------------------------------------------
def bound_details(action: str, **kw: Any) -> dict[str, Any]:
    """The exact target a confirmation authorizes. Hashed; any change invalidates it."""
    if action == "book":
        return {
            "action": "book",
            "appointment_type_id": str(kw["appointment_type_id"]),
            "start_at": iso_utc(kw["start_at"]),
        }
    if action == "reschedule":
        return {
            "action": "reschedule",
            "appointment_id": str(kw["appointment_id"]),
            "new_start_at": iso_utc(kw["new_start_at"]),
        }
    return {
        "action": "cancel",
        "appointment_id": str(kw["appointment_id"]),
        "reason": (kw.get("reason") or "").strip(),
    }


def _effective_status(p: Proposal, now: datetime) -> str:
    if p.status in ("pending", "confirmed") and p.expires_at <= now:
        return "expired"
    return p.status


def proposal_read(
    p: Proposal, now: datetime, summary: str, token: str | None = None
) -> ProposalRead:
    return ProposalRead(
        id=p.id,
        clinic_id=p.clinic_id,
        patient_id=p.patient_id,
        action=p.action,  # type: ignore[arg-type]
        status=_effective_status(p, now),  # type: ignore[arg-type]
        summary=summary,
        details=p.payload["bound"],
        expires_at=p.expires_at,
        confirmation_token=token,
    )


def _local_text(cfg: PublishedConfig, instant: datetime) -> str:
    return instant.astimezone(cfg.rules.tz).strftime("%A, %B %d at %I:%M %p %Z").replace(" 0", " ")


async def create_proposal(
    session: AsyncSession,
    cfg: PublishedConfig,
    ctx: AuthContext,
    body: ProposalCreate,
    now: datetime,
) -> ProposalRead:
    extra: dict[str, Any] = {}
    if body.action == "book":
        if body.appointment_type_id is None or body.start_at is None or body.appointment_id:
            raise InvalidInput("A booking proposal needs appointment_type_id and start_at only.")
        info = await plan_book(session, cfg, body.appointment_type_id, body.start_at, now)
        bound = bound_details("book", appointment_type_id=info.id, start_at=body.start_at)
        summary = f"Book {info.name} ({info.duration_minutes} min) on " + _local_text(
            cfg, body.start_at
        )
    else:
        if body.appointment_id is None or body.appointment_type_id is not None:
            raise InvalidInput("This proposal needs appointment_id and no appointment_type_id.")
        appt = await get_appointment(session, ctx, body.appointment_id)
        extra["appointment_row_version"] = appt.row_version
        if body.action == "reschedule":
            if body.start_at is None:
                raise InvalidInput("A reschedule proposal needs start_at (the new time).")
            await plan_reschedule(session, cfg, appt, body.start_at, now)
            bound = bound_details("reschedule", appointment_id=appt.id, new_start_at=body.start_at)
            summary = (
                f"Move {appt.type_name} from {_local_text(cfg, appt.start_at)} "
                f"to {_local_text(cfg, body.start_at)}"
            )
        else:
            if body.start_at is not None:
                raise InvalidInput("A cancel proposal does not take start_at.")
            plan_cancel(cfg, appt, now)
            bound = bound_details("cancel", appointment_id=appt.id, reason=body.reason)
            summary = f"Cancel {appt.type_name} on {_local_text(cfg, appt.start_at)}"

    token = new_secret()
    proposal = Proposal(
        clinic_id=ctx.clinic_id,
        patient_id=ctx.patient_id,
        action=body.action,
        payload={"bound": bound, "summary": summary, **extra},
        payload_hash=canonical_hash(bound),
        token_hash=hash_token(token),
        status="pending",
        expires_at=now + timedelta(minutes=get_settings().proposal_ttl_minutes),
    )
    session.add(proposal)
    await session.flush()
    return proposal_read(proposal, now, summary, token)


async def _load_proposal(
    session: AsyncSession, ctx: AuthContext, proposal_id: uuid.UUID, *, lock: bool
) -> Proposal:
    query = select(Proposal).where(Proposal.clinic_id == ctx.clinic_id, Proposal.id == proposal_id)
    if lock:
        query = query.with_for_update()
    proposal = await session.scalar(query)
    if proposal is None:
        raise NotFound("Proposal not found.")
    if proposal.patient_id != ctx.patient_id:
        raise Forbidden("This authorization does not apply to this proposal.")
    return proposal


async def read_proposal(
    session: AsyncSession, ctx: AuthContext, proposal_id: uuid.UUID, now: datetime
) -> ProposalRead:
    p = await _load_proposal(session, ctx, proposal_id, lock=False)
    return proposal_read(p, now, p.payload["summary"])


async def confirm_proposal(
    session: AsyncSession, ctx: AuthContext, proposal_id: uuid.UUID, token: str, now: datetime
) -> ProposalRead:
    p = await _load_proposal(session, ctx, proposal_id, lock=True)
    state = _effective_status(p, now)
    if state == "expired":
        raise ProposalExpired("The proposal has expired. Create a new one.")
    if state == "executed":
        raise ProposalAlreadyUsed("The proposal has already been used.")
    if state == "rejected":
        raise ProposalNotConfirmed("The proposal was rejected.")
    if p.token_hash != hash_token(token):
        raise Forbidden("The confirmation token does not match this proposal.")
    if p.status == "pending":
        p.status = "confirmed"
        p.confirmed_at = now
        await session.flush()
    return proposal_read(p, now, p.payload["summary"])


async def reject_proposal(
    session: AsyncSession, ctx: AuthContext, proposal_id: uuid.UUID, now: datetime
) -> ProposalRead:
    p = await _load_proposal(session, ctx, proposal_id, lock=True)
    state = _effective_status(p, now)
    if state == "executed":
        raise ProposalAlreadyUsed("The proposal has already been used.")
    if state in ("pending", "confirmed"):
        p.status = "rejected"
        await session.flush()
    return proposal_read(p, now, p.payload["summary"])


async def consume_proposal(
    session: AsyncSession,
    ctx: AuthContext,
    proposal_id: uuid.UUID,
    bound: dict[str, Any],
    operation_id: uuid.UUID,
    now: datetime,
) -> Proposal:
    """One-time use: the proposal must be confirmed, unexpired, owned by this patient, and the
    request must match the confirmed details exactly. Marked executed in the caller's tx."""
    p = await _load_proposal(session, ctx, proposal_id, lock=True)
    state = _effective_status(p, now)
    if state == "expired":
        raise ProposalExpired("The proposal has expired. Create a new one.")
    if state == "executed":
        raise ProposalAlreadyUsed("The proposal has already been used.")
    if state != "confirmed":
        raise ProposalNotConfirmed("The proposal has not been confirmed.")
    if p.action != bound["action"] or p.payload_hash != canonical_hash(bound):
        raise ProposalMismatch("The request does not match the confirmed proposal.")
    p.status = "executed"
    p.executed_at = now
    p.executed_operation_id = operation_id
    await session.flush()
    return p


# ---- state-changing operations ----------------------------------------------------------
def _event(
    appt: Appointment,
    operation_id: uuid.UUID,
    event_type: str,
    from_status: str | None,
    cfg: PublishedConfig,
    details: dict[str, Any],
) -> AppointmentEvent:
    return AppointmentEvent(
        clinic_id=appt.clinic_id,
        appointment_id=appt.id,
        operation_id=operation_id,
        event_type=event_type,
        from_status=from_status,
        to_status=appt.status,
        config_version=cfg.rules.version,
        details=details,
    )


async def book(
    session: AsyncSession,
    cfg: PublishedConfig,
    ctx: AuthContext,
    type_id: uuid.UUID,
    start: datetime,
    operation_id: uuid.UUID,
    now: datetime,
) -> Appointment:
    info = await plan_book(session, cfg, type_id, start, now)
    appt = Appointment(
        clinic_id=ctx.clinic_id,
        patient_id=ctx.patient_id,
        appointment_type_id=info.id,
        type_name=info.name,
        duration_minutes=info.duration_minutes,
        timezone=cfg.rules.timezone_name,
        start_at=start,
        end_at=start + timedelta(minutes=info.duration_minutes),
        status="scheduled",
        config_version=cfg.rules.version,
    )
    session.add(appt)
    await _flush_or_conflict(session)
    session.add(
        _event(
            appt,
            operation_id,
            "booked",
            None,
            cfg,
            {"start_at": iso_utc(appt.start_at), "end_at": iso_utc(appt.end_at)},
        )
    )
    await session.flush()
    await session.refresh(appt)
    return appt


async def reschedule(
    session: AsyncSession,
    cfg: PublishedConfig,
    ctx: AuthContext,
    appointment_id: uuid.UUID,
    new_start: datetime,
    expected_row_version: int,
    operation_id: uuid.UUID,
    now: datetime,
) -> Appointment:
    appt = await get_appointment(session, ctx, appointment_id, lock=True)
    if appt.row_version != expected_row_version:
        raise AppointmentModified("The appointment was changed after this was proposed.")
    await plan_reschedule(session, cfg, appt, new_start, now)
    before = {"start_at": iso_utc(appt.start_at), "end_at": iso_utc(appt.end_at)}
    appt.start_at = new_start
    appt.end_at = new_start + timedelta(minutes=appt.duration_minutes)
    appt.reschedule_count += 1
    appt.row_version += 1
    appt.updated_at = now
    await _flush_or_conflict(session)
    session.add(
        _event(
            appt,
            operation_id,
            "rescheduled",
            "scheduled",
            cfg,
            {
                "from": before,
                "to": {"start_at": iso_utc(appt.start_at), "end_at": iso_utc(appt.end_at)},
            },
        )
    )
    await session.flush()
    await session.refresh(appt)
    return appt


async def cancel(
    session: AsyncSession,
    cfg: PublishedConfig,
    ctx: AuthContext,
    appointment_id: uuid.UUID,
    reason: str | None,
    expected_row_version: int,
    operation_id: uuid.UUID,
    now: datetime,
) -> Appointment:
    appt = await get_appointment(session, ctx, appointment_id, lock=True)
    if appt.row_version != expected_row_version:
        raise AppointmentModified("The appointment was changed after this was proposed.")
    plan_cancel(cfg, appt, now)
    if not engine.check_transition(appt.status, "cancelled"):
        raise InvalidStateTransition(f"Cannot cancel an appointment that is {appt.status}.")
    appt.status = "cancelled"
    appt.cancelled_at = now
    appt.cancellation_reason = (reason or "").strip() or None
    appt.row_version += 1
    appt.updated_at = now
    await session.flush()
    session.add(_event(appt, operation_id, "cancelled", "scheduled", cfg, {"reason": reason or ""}))
    await session.flush()
    await session.refresh(appt)
    return appt


async def _flush_or_conflict(session: AsyncSession) -> None:
    """Translate the database's exclusion-constraint rejection into a booking conflict."""
    try:
        async with session.begin_nested():
            await session.flush()
    except DBAPIError as exc:
        if sqlstate(exc) == EXCLUSION_VIOLATION:
            raise SlotUnavailable("That time is no longer available.") from None
        raise
