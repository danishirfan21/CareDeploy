"""Call history and call detail read models (M5). Every query is scoped to one clinic."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.store import latest_views
from app.models import (
    CallEvent,
    CallSession,
    Clinic,
    ConfigVersion,
    Deployment,
    EvalRun,
    Operation,
)
from app.ops import classify as cl
from app.ops.pricing import RateTable, estimate
from app.ops.redact import safe
from app.schemas.clinic import ClinicConfig
from app.schemas.ops import (
    AgentAction,
    CallDetail,
    CallList,
    CallListItem,
    DeploymentRef,
    EvaluationRef,
    OperationRef,
    TranscriptTurnOut,
)

TOOL_LABELS = {
    "get_clinic_information": "Clinic information",
    "get_appointment_availability": "Availability check",
    "verify_patient": "Caller verification",
    "get_patient_appointments": "Appointment lookup",
    "propose_booking": "Booking proposal",
    "propose_reschedule": "Reschedule proposal",
    "propose_cancellation": "Cancellation proposal",
    "withdraw_pending_proposal": "Withdraw proposal",
    "confirm_operation": "Confirm change",
    "get_operation_status": "Operation status check",
    "request_human_escalation": "Hand-off to staff",
}


def zone_of(clinic: Clinic) -> ZoneInfo:
    try:
        return ZoneInfo(clinic.timezone or "UTC")
    except Exception:  # noqa: BLE001 - an unknown zone name falls back to UTC, never a 500
        return ZoneInfo("UTC")


def local_range(zone: ZoneInfo, start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive local dates -> [start, end) instants in UTC. The end is the start of the next
    local day, so a call at 23:59 local time belongs to its own day whatever the UTC offset."""
    lo = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return lo, hi


# ------------------------------------------------------------------------ classification -----
async def ledger_for(db: AsyncSession, cs: CallSession) -> list[Operation]:
    ids: list[uuid.UUID] = []
    for raw in cs.operation_ids or []:
        try:
            ids.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not ids:
        return []
    rows = (
        await db.scalars(
            select(Operation)
            .where(Operation.clinic_id == cs.clinic_id, Operation.id.in_(ids))
            .order_by(Operation.created_at)
        )
    ).all()
    return list(rows)


async def classify_session(db: AsyncSession, cs: CallSession, now: datetime | None = None) -> None:
    """Set the verified classification from the call record and the operations ledger. Does not
    commit. Safe to repeat: a finished call is reclassified from the same evidence."""
    ops = await ledger_for(db, cs)
    result = cl.classify(
        status=cs.status,
        outcome=cs.outcome,
        escalation_reason=cs.escalation_reason,
        error=cs.error,
        transport_lost=bool((cs.metrics or {}).get("transport_lost")),
        ops=[cl.LedgerOp(str(o.id), o.operation_type, o.status) for o in ops],
    )
    cs.outcome_class = result.outcome_class
    cs.task_type = result.task_type
    cs.classified_at = now or datetime.now(UTC)


async def classify_pending(db: AsyncSession, clinic_id: uuid.UUID) -> int:
    """Lazy backfill for finished calls that predate classification (older M3 records)."""
    rows = (
        await db.scalars(
            select(CallSession)
            .where(
                CallSession.clinic_id == clinic_id,
                CallSession.outcome_class.is_(None),
                CallSession.status.in_(tuple(cl.TERMINAL_STATUSES)),
            )
            .limit(500)
        )
    ).all()
    for cs in rows:
        await classify_session(db, cs)
    if rows:
        await db.commit()
    return len(rows)


def _label(outcome_class: str | None) -> str:
    return cl.CLASS_LABELS.get(outcome_class or "", "In progress")


# --------------------------------------------------------------------------------- list -------
def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def list_calls(
    db: AsyncSession,
    clinic: Clinic,
    *,
    outcome: str | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
    limit: int,
    offset: int,
) -> CallList:
    await classify_pending(db, clinic.id)
    conds: list[Any] = [CallSession.clinic_id == clinic.id]
    if outcome == "in_progress":
        conds.append(CallSession.status.in_(("created", "active")))
    elif outcome:
        conds.append(CallSession.outcome_class == outcome)
    zone = zone_of(clinic)
    if date_from:
        conds.append(CallSession.created_at >= local_range(zone, date_from, date_from)[0])
    if date_to:
        conds.append(CallSession.created_at < local_range(zone, date_to, date_to)[1])
    if q and q.strip():
        pattern = _like(q.strip())
        conds.append(
            or_(
                cast(CallSession.id, String).ilike(pattern, escape="\\"),
                cast(CallSession.operation_ids, String).ilike(pattern, escape="\\"),
                CallSession.summary.ilike(pattern, escape="\\"),
                CallSession.task_type.ilike(pattern, escape="\\"),
            )
        )
    total = int(await db.scalar(select(func.count()).select_from(CallSession).where(*conds)) or 0)
    rows = (
        await db.scalars(
            select(CallSession)
            .where(*conds)
            .order_by(CallSession.created_at.desc(), CallSession.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        CallListItem(
            id=r.id,
            clinic_id=r.clinic_id,
            clinic_name=clinic.name,
            started_at=r.started_at or r.created_at,
            status=r.status,
            outcome_class=r.outcome_class,  # type: ignore[arg-type]
            outcome_label=_label(r.outcome_class),
            task_type=r.task_type,
            task_label=cl.TASK_LABELS.get(r.task_type or ""),
            duration_seconds=r.duration_seconds,
            config_version=r.config_version,
        )
        for r in rows
    ]
    return CallList(items=items, total=total, limit=limit, offset=offset)


# ------------------------------------------------------------------------------- detail ------
def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def call_detail(
    db: AsyncSession, clinic: Clinic, session_id: uuid.UUID, rates: RateTable
) -> CallDetail | None:
    cs = await db.get(CallSession, session_id)
    if cs is None or cs.clinic_id != clinic.id:
        return None  # another clinic's call is indistinguishable from a missing one
    if cs.outcome_class is None and cs.status in cl.TERMINAL_STATUSES:
        await classify_session(db, cs)
        await db.commit()
    events = (
        await db.scalars(
            select(CallEvent)
            .where(CallEvent.call_session_id == cs.id)
            .order_by(CallEvent.seq, CallEvent.occurred_at)
        )
    ).all()
    ledger = {str(o.id): o for o in await ledger_for(db, cs)}
    ops_out = [
        OperationRef(
            id=str(o.id),
            operation_type=o.operation_type,
            status=o.status,
            appointment_id=str(o.appointment_id) if o.appointment_id else None,
        )
        for o in ledger.values()
    ]

    turns: list[TranscriptTurnOut] = []
    tools: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for e in events:
        p = e.payload or {}
        if e.kind == "transcript" and p.get("final", True):
            text = str(p.get("text") or "").strip()
            interrupted = p.get("interrupted") is True
            if not text and not interrupted:
                continue
            turns.append(
                TranscriptTurnOut(
                    event_id=e.event_id,
                    seq=e.seq,
                    speaker="agent" if p.get("speaker") == "agent" else "caller",
                    text=text or "(interrupted)",
                    interrupted=interrupted,
                    occurred_at=_aware(e.occurred_at),
                )
            )
        elif e.kind == "tool":
            call_id = str(p.get("call_id") or e.event_id)
            entry = tools.setdefault(call_id, {"name": str(p.get("name") or "")})
            if p.get("phase") == "started":
                entry["started_at"] = _aware(e.occurred_at)
                entry["args"] = safe(p.get("args") or {})
            elif p.get("phase") == "finished":
                entry["finished_at"] = _aware(e.occurred_at)
                entry.update(
                    status=str(p.get("status") or ""),
                    code=p.get("code"),
                    message=p.get("message"),
                    operation_id=p.get("operation_id"),
                    latency_ms=p.get("latency_ms"),
                )
        elif e.kind == "error":
            errors.append({"at": _aware(e.occurred_at).isoformat(), **safe(p)})

    actions: list[AgentAction] = []
    for call_id, t in tools.items():
        status = t.get("status") or "running"
        category = cl.error_category(status, t.get("code")) if t.get("status") else None
        op_id = t.get("operation_id")
        op = ledger.get(str(op_id)) if op_id else None
        actions.append(
            AgentAction(
                call_id=call_id,
                name=t["name"],
                label=TOOL_LABELS.get(t["name"], t["name"].replace("_", " ")),
                status=status,
                succeeded=status in cl.OK_STATUSES,
                code=t.get("code"),
                message=str(t["message"])[:300] if t.get("message") else None,
                error_category=category,
                error_category_label=cl.CATEGORY_LABELS.get(category) if category else None,
                operation_id=str(op_id) if op_id else None,
                operation=OperationRef(
                    id=str(op.id),
                    operation_type=op.operation_type,
                    status=op.status,
                    appointment_id=str(op.appointment_id) if op.appointment_id else None,
                )
                if op
                else None,
                latency_ms=t.get("latency_ms"),
                started_at=t.get("started_at"),
                finished_at=t.get("finished_at"),
                args=t.get("args"),
            )
        )

    cv = await db.scalar(
        select(ConfigVersion).where(
            ConfigVersion.clinic_id == clinic.id, ConfigVersion.version == cs.config_version
        )
    )
    agent_name = ClinicConfig.model_validate(cv.snapshot).agent.agent_name if cv else None

    deployment: DeploymentRef | None = None
    if cs.deployment_id:
        d = await db.get(Deployment, cs.deployment_id)
        if d and d.clinic_id == clinic.id:
            deployment = DeploymentRef(
                id=d.id,
                action=d.action,
                config_version=d.config_version,
                activated_at=_aware(d.activated_at),
                status=d.status,
            )
    evaluation: EvaluationRef | None = None
    latest = (await latest_views(db, clinic.id, cs.config_version)).get("workflow")
    if latest is not None:
        run = await db.get(EvalRun, uuid.UUID(latest.id))
        if run:
            evaluation = EvaluationRef(
                run_id=run.id,
                status=run.status,
                finished_at=run.finished_at and _aware(run.finished_at),
            )

    cost = estimate(cs.provider_usage or {}, cs.started_at or cs.created_at, rates)
    classification = cl.classify(
        status=cs.status,
        outcome=cs.outcome,
        escalation_reason=cs.escalation_reason,
        error=cs.error,
        transport_lost=bool((cs.metrics or {}).get("transport_lost")),
        ops=[cl.LedgerOp(str(o.id), o.operation_type, o.status) for o in ledger.values()],
    )
    technical: dict[str, Any] = {
        "metrics": safe(cs.metrics or {}),
        "provider_usage": safe(cs.provider_usage or {}),
        "cost_estimate": cost,
        "errors": errors,
        "event_count": len(events),
        "first_event_at": _aware(events[0].occurred_at).isoformat() if events else None,
        "last_event_at": _aware(events[-1].occurred_at).isoformat() if events else None,
        "room_name": cs.room_name,
    }
    return CallDetail(
        id=cs.id,
        clinic_id=cs.clinic_id,
        clinic_name=clinic.name,
        agent_name=agent_name,
        config_version=cs.config_version,
        status=cs.status,
        agent_reported_outcome=cs.outcome,
        outcome_class=cs.outcome_class,  # type: ignore[arg-type]
        outcome_label=_label(cs.outcome_class),
        outcome_reason=classification.reason if cs.outcome_class else None,
        task_type=cs.task_type,
        task_label=cl.TASK_LABELS.get(cs.task_type or ""),
        created_at=_aware(cs.created_at),
        started_at=cs.started_at and _aware(cs.started_at),
        ended_at=cs.ended_at and _aware(cs.ended_at),
        duration_seconds=cs.duration_seconds,
        ended_by=cs.ended_by,
        escalation_reason=cs.escalation_reason,
        error=cs.error,
        summary=cs.summary,
        operations=ops_out,
        deployment=deployment,
        evaluation=evaluation,
        transcript=turns,
        actions=actions,
        technical=technical,
    )
