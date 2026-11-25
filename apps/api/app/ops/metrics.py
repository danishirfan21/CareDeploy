"""Operational metrics (M5): server-side aggregates over persisted call records.

Definitions (also in docs/observability.md):

* The range is inclusive local dates in the clinic's time zone, applied to the call's creation
  time as [start of first day, start of the day after the last day). Nothing is cut at UTC midnight.
* `total_calls` counts every call created in range. `in_progress` calls are excluded from every
  rate. `classified_calls` = total - in_progress is the denominator of the three rates, so
  abandoned, interrupted and unknown calls count against completion and are never assumed good.
* Rates with fewer than MIN_SAMPLE classified calls are returned but flagged `low_sample`.
* Duration averages use only calls that recorded a duration; the count used is returned.
* Tool counts use finished tool events, one per tool call (`call_id`), never the started/finished
  pair twice and never a replayed event twice.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import String, and_, case, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallEvent, CallSession, Clinic
from app.ops.calls import classify_pending, local_range, zone_of
from app.ops.classify import CLASS_LABELS, OK_STATUSES
from app.ops.pricing import RateTable, estimate
from app.schemas.ops import CostSummary, MetricsOut, Rate, ToolStats

MIN_SAMPLE = 10
COST_NOTE = (
    "Estimates from recorded provider usage and the configured rate file. They are not actual "
    "billing and not any organization's real operating costs."
)


def _rate(num: int, den: int, definition: str) -> Rate:
    return Rate(
        numerator=num,
        denominator=den,
        value=round(num / den, 4) if den else None,
        low_sample=den < MIN_SAMPLE,
        definition=definition,
    )


async def compute(
    db: AsyncSession,
    clinic: Clinic,
    start: date,
    end: date,
    rates: RateTable,
    now: datetime,
) -> MetricsOut:
    await classify_pending(db, clinic.id)
    zone = zone_of(clinic)
    lo, hi = local_range(zone, start, end)
    in_range = and_(
        CallSession.clinic_id == clinic.id,
        CallSession.created_at >= lo,
        CallSession.created_at < hi,
    )

    grouped = (
        await db.execute(
            select(CallSession.outcome_class, func.count())
            .where(in_range)
            .group_by(CallSession.outcome_class)
        )
    ).all()
    by_outcome = {k: 0 for k in CLASS_LABELS}
    in_progress = 0
    for key, n in grouped:
        if key is None:
            in_progress += int(n)
        else:
            by_outcome[key] = int(n)
    total = in_progress + sum(by_outcome.values())
    classified = total - in_progress

    dur = (
        await db.execute(
            select(
                func.count(CallSession.duration_seconds),
                func.avg(CallSession.duration_seconds),
                func.count(
                    case((CallSession.outcome_class == "completed", CallSession.duration_seconds))
                ),
                func.avg(
                    case((CallSession.outcome_class == "completed", CallSession.duration_seconds))
                ),
            ).where(in_range, CallSession.outcome_class.is_not(None))
        )
    ).one()
    with_duration, avg_all, completed_with_duration, avg_completed = dur

    # One row per tool call: the `finished` event, distinct by (session, call_id).
    phase = CallEvent.payload["phase"].astext
    status = CallEvent.payload["status"].astext
    # Scoped to the session: ids such as "c1" can repeat across calls and must not collapse.
    call_key = func.concat(
        cast(CallEvent.call_session_id, String),
        ":",
        func.coalesce(CallEvent.payload["call_id"].astext, CallEvent.event_id),
    )
    ok = func.count(distinct(case((status.in_(tuple(OK_STATUSES)), call_key))))
    unc = func.count(distinct(case((status == "uncertain", call_key))))
    done = func.count(distinct(call_key))
    tool_row = (
        await db.execute(
            select(done, ok, unc)
            .select_from(CallEvent)
            .join(CallSession, CallSession.id == CallEvent.call_session_id)
            .where(in_range, CallEvent.kind == "tool", phase == "finished")
        )
    ).one()
    finished, succeeded, uncertain = (int(x) for x in tool_row)
    failed = finished - succeeded - uncertain
    tools = ToolStats(
        finished=finished,
        succeeded=succeeded,
        failed=failed,
        uncertain=uncertain,
        failure_rate=_rate(
            failed,
            finished,
            "tool calls that returned an error or rejection / finished tool calls "
            "(uncertain outcomes are counted separately)",
        ),
    )

    # Cost: only calls that recorded usage can have one.
    usage_rows = (
        await db.execute(
            select(
                CallSession.provider_usage,
                CallSession.started_at,
                CallSession.created_at,
                CallSession.outcome_class,
            ).where(in_range, CallSession.outcome_class.is_not(None))
        )
    ).all()
    dec_total = Decimal(0)
    with_cost = without_cost = completed_with_cost = 0
    completed_cost = Decimal(0)
    reasons: set[str] = set()
    for usage, started, created, klass in usage_rows:
        est = estimate(usage or {}, started or created, rates, now)
        if est["available"]:
            amt = Decimal(est["amount"])
            dec_total += amt
            with_cost += 1
            if klass == "completed":
                completed_with_cost += 1
                completed_cost += amt
        else:
            without_cost += 1
            if est["reason"]:
                reasons.add(est["reason"])
    reason: str | None = None
    if with_cost == 0:
        reason = (
            "Cost unavailable: provider usage data was not recorded."
            if not usage_rows or all(not (u or {}) for u, *_ in usage_rows)
            else sorted(reasons)[0]
        )
    cost = CostSummary(
        currency=rates.currency,
        available=with_cost > 0,
        calls_with_cost=with_cost,
        calls_without_cost=without_cost,
        total=str(dec_total.quantize(Decimal("0.0001"))) if with_cost else None,
        per_call=str((dec_total / with_cost).quantize(Decimal("0.0001"))) if with_cost else None,
        per_completed_task=(
            str((completed_cost / completed_with_cost).quantize(Decimal("0.0001")))
            if completed_with_cost
            else None
        ),
        completed_with_cost=completed_with_cost,
        reason=reason,
        note=COST_NOTE,
    )

    notes: list[str] = []
    if in_progress:
        notes.append(f"{in_progress} call(s) still in progress are excluded from the rates.")
    if classified and classified < MIN_SAMPLE:
        notes.append(f"Only {classified} finished call(s): treat percentages as indicative only.")
    if classified and with_duration < classified:
        notes.append(f"{classified - with_duration} finished call(s) have no recorded duration.")
    if cost.calls_without_cost and cost.available:
        notes.append(f"{cost.calls_without_cost} finished call(s) have no cost estimate.")

    return MetricsOut(
        clinic_id=clinic.id,
        timezone=str(zone),
        from_date=start,
        to_date=end,
        starts_at=lo,
        ends_before=hi,
        total_calls=total,
        in_progress=in_progress,
        classified_calls=classified,
        by_outcome=by_outcome,
        completion=_rate(by_outcome["completed"], classified, "completed / finished calls"),
        escalation=_rate(by_outcome["escalated"], classified, "escalated / finished calls"),
        failure=_rate(by_outcome["failed"], classified, "failed / finished calls"),
        average_duration_seconds=round(float(avg_all), 1) if avg_all is not None else None,
        calls_with_duration=int(with_duration),
        average_duration_completed_seconds=(
            round(float(avg_completed), 1) if avg_completed is not None else None
        ),
        tools=tools,
        cost=cost,
        notes=notes,
    )
