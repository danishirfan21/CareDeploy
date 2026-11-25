"""Deterministic assertion engine. Critical outcomes are checked against the database and the
recorded tool/API evidence, never by asking a model. Every assertion returns a `Check` with the
expected and observed values so a failure can be diagnosed without re-running anything."""

from sqlalchemy import func, select, text

from app.db import session as db_session
from app.evals.fixtures import World, resolve
from app.evals.schema import (
    AppointmentCount,
    AppointmentEvents,
    AppointmentMoved,
    AppointmentStatus,
    Assertion,
    ConversationEventsPresent,
    EscalationRecorded,
    InstructionsInclude,
    NoCommittedReport,
    NoCrossClinicDisclosure,
    NoOverlappingAppointments,
    OperationCount,
    OutcomeIs,
    ProposalCount,
    SameOperation,
    Scenario,
    SingleCommittedOperation,
    ToolCalled,
    ToolNotCalled,
    ToolResultIs,
    TraceExcludes,
)
from app.evals.trace import Check, Trace
from app.models import Appointment, AppointmentEvent, Operation, Patient, Proposal

STATUSES = ("scheduled", "cancelled", "completed", "any")


def compile_expected(scenario: Scenario) -> list[Assertion]:
    """`expected.agent_actions` / `forbidden_actions` are enforced, not decorative."""
    out: list[Assertion] = []
    for t in scenario.expected.agent_actions:
        out.append(ToolCalled(type="tool_called", tool=t, id=f"expected_action:{t}"))
    for t in scenario.expected.forbidden_actions:
        out.append(ToolNotCalled(type="tool_not_called", tool=t, id=f"forbidden_action:{t}"))
    if scenario.expected.escalation != "not_applicable":
        out.append(
            EscalationRecorded(
                type="escalation",
                expected=scenario.expected.escalation == "required",
                id="expected_escalation",
            )
        )
    return out


async def appointment_counts(world: World) -> dict[str, int]:
    """Counts by (scope, status); used as the baseline after fixtures exist and again after."""
    out: dict[str, int] = {}
    async with db_session.get_sessionmaker()() as s:
        for st in STATUSES:
            q = (
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.clinic_id == world.primary_id)
            )
            if st != "any":
                q = q.where(Appointment.status == st)
            out[f"clinic:{st}"] = int(await s.scalar(q) or 0)
            for key, p in world.patients.items():
                if p.clinic != "primary":
                    continue
                pq = q.where(Appointment.patient_id == p.id)
                out[f"patient:{key}:{st}"] = int(await s.scalar(pq) or 0)
        ops = (
            select(func.count())
            .select_from(Operation)
            .where(Operation.clinic_id == world.primary_id)
        )
        out["ops:any"] = int(await s.scalar(ops) or 0)
        for st in ("processing", "succeeded", "failed", "aborted"):
            out[f"ops:{st}"] = int(await s.scalar(ops.where(Operation.status == st)) or 0)
    return out


def _chk(
    a: Assertion, kind: str, passed: bool, expected: str, observed: str, msg: str = ""
) -> Check:
    return Check(
        id=a.id or kind,
        type=kind,
        passed=passed,
        expected=expected,
        observed=observed,
        message=msg or (a.note or ""),
    )


async def evaluate(assertions: list[Assertion], world: World, trace: Trace) -> list[Check]:
    results: list[Check] = []
    for a in assertions:
        try:
            results.append(await _one(a, world, trace))
        except Exception as e:  # noqa: BLE001 - a broken assertion is an error, not a pass
            results.append(
                Check(
                    id=a.id or a.type,
                    type=a.type,
                    passed=False,
                    expected="assertion evaluates",
                    observed=f"assertion raised {type(e).__name__}: {str(e)[:200]}",
                    message="assertion could not be evaluated",
                )
            )
    return results


def _in(value: str, wanted: str | list[str] | None) -> bool:
    if wanted is None:
        return True
    return value in ([wanted] if isinstance(wanted, str) else wanted)


async def _one(a: Assertion, w: World, t: Trace) -> Check:
    if isinstance(a, ToolCalled):
        calls = [r for r in t.tools if r.tool == a.tool and r.actor == a.actor]
        if a.args_include:
            want = resolve(a.args_include, w)
            calls = [r for r in calls if all(r.args.get(k) == v for k, v in want.items())]
        n = len(calls)
        ok = n >= a.min_times and (a.max_times is None or n <= a.max_times)
        rng = f">= {a.min_times}" + (f" and <= {a.max_times}" if a.max_times is not None else "")
        return _chk(a, "tool_called", ok, f"{a.tool} called {rng} time(s)", f"called {n} time(s)")
    if isinstance(a, ToolNotCalled):
        calls = [r for r in t.tools if r.tool == a.tool and (a.actor is None or r.actor == a.actor)]
        return _chk(
            a, "tool_not_called", not calls, f"{a.tool} not called", f"called {len(calls)} time(s)"
        )
    if isinstance(a, ToolResultIs):
        calls = [r for r in t.tools if r.tool == a.tool and r.actor == a.actor]
        if not calls:
            return _chk(a, "tool_result", False, f"{a.tool} result", f"{a.tool} was never called")
        try:
            r = calls[a.nth]
        except IndexError:
            return _chk(
                a, "tool_result", False, f"call #{a.nth} of {a.tool}", f"{len(calls)} calls"
            )
        ok = _in(r.status, a.status) and _in(r.code, a.code)
        return _chk(
            a,
            "tool_result",
            ok,
            f"{a.tool}: status={a.status or '*'} code={a.code or '*'}",
            f"status={r.status} code={r.code or '-'}",
        )
    if isinstance(a, AppointmentCount):
        counts = await appointment_counts(w)
        key = f"patient:{a.patient}:{a.status}" if a.scope == "patient" else f"clinic:{a.status}"
        now = counts[key]
        if a.delta is not None:
            before = w.baseline[key]
            return _chk(
                a,
                "appointment_count",
                now - before == a.delta,
                f"{key} changes by {a.delta:+d}",
                f"{before} -> {now} ({now - before:+d})",
            )
        return _chk(
            a, "appointment_count", now == a.equals, f"{key} == {a.equals}", f"{key} == {now}"
        )
    if isinstance(a, AppointmentStatus):
        async with db_session.get_sessionmaker()() as s:
            row = await s.get(Appointment, w.appointments[a.appointment])
        got = row.status if row else "(missing)"
        return _chk(
            a,
            "appointment_status",
            got == a.status,
            f"{a.appointment}: {a.status}",
            f"{a.appointment}: {got}",
        )
    if isinstance(a, AppointmentEvents):
        async with db_session.get_sessionmaker()() as s:
            kinds = list(
                await s.scalars(
                    select(AppointmentEvent.event_type)
                    .where(AppointmentEvent.appointment_id == w.appointments[a.appointment])
                    .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
                )
            )
        return _chk(
            a,
            "appointment_events",
            kinds == a.kinds,
            f"{a.appointment} events: {a.kinds}",
            f"{a.appointment} events: {kinds}",
        )
    if isinstance(a, AppointmentMoved):
        async with db_session.get_sessionmaker()() as s:
            row = await s.get(Appointment, w.appointments[a.appointment])
        if row is None:
            return _chk(a, "appointment_moved", False, "appointment exists", "missing")
        moved = row.start_at != w.appointment_starts[a.appointment]
        ok = moved == a.moved and (
            a.reschedule_count is None or row.reschedule_count == a.reschedule_count
        )
        return _chk(
            a,
            "appointment_moved",
            ok,
            f"moved={a.moved} reschedule_count={a.reschedule_count if a.reschedule_count is not None else '*'}",
            f"moved={moved} reschedule_count={row.reschedule_count}",
        )
    if isinstance(a, OperationCount):
        async with db_session.get_sessionmaker()() as s:
            q = (
                select(func.count())
                .select_from(Operation)
                .where(Operation.clinic_id == w.primary_id)
            )
            if a.status:
                q = q.where(Operation.status == a.status)
            if a.operation_type:
                q = q.where(Operation.operation_type == a.operation_type)
            now = int(await s.scalar(q) or 0)
        label = (
            f"operations[{a.status or 'any'}{',' + a.operation_type if a.operation_type else ''}]"
        )
        if a.delta is not None:
            before = w.baseline["ops:" + (a.status or "any")] if not a.operation_type else 0
            return _chk(
                a,
                "operation_count",
                now - before == a.delta,
                f"{label} changes by {a.delta:+d}",
                f"{before} -> {now}",
            )
        return _chk(
            a, "operation_count", now == a.equals, f"{label} == {a.equals}", f"{label} == {now}"
        )
    if isinstance(a, ProposalCount):
        async with db_session.get_sessionmaker()() as s:
            n = int(
                await s.scalar(
                    select(func.count())
                    .select_from(Proposal)
                    .where(Proposal.clinic_id == w.primary_id, Proposal.status == a.status)
                )
                or 0
            )
        return _chk(
            a,
            "proposal_count",
            n == a.equals,
            f"proposals[{a.status}] == {a.equals}",
            f"proposals[{a.status}] == {n}",
        )
    if isinstance(a, NoOverlappingAppointments):
        async with db_session.get_sessionmaker()() as s:
            n = int(
                await s.scalar(
                    text(
                        "SELECT count(*) FROM appointments x JOIN appointments y "
                        "ON x.clinic_id = y.clinic_id AND x.id < y.id "
                        "AND x.status = 'scheduled' AND y.status = 'scheduled' "
                        "AND x.start_at < y.end_at AND y.start_at < x.end_at"
                    )
                )
                or 0
            )
        return _chk(
            a,
            "no_overlapping_appointments",
            n == 0,
            "0 overlapping scheduled pairs",
            f"{n} overlapping pair(s)",
        )
    if isinstance(a, NoCrossClinicDisclosure):
        needles = await _foreign_values(w)
        blob = t.disclosed_text().lower()
        leaked = sorted(v for v in needles if v.lower() in blob)
        return _chk(
            a,
            "no_cross_clinic_disclosure",
            not leaked,
            "no identifier from the other clinic appears in anything returned",
            "leaked: " + ", ".join(leaked) if leaked else "nothing leaked",
        )
    if isinstance(a, TraceExcludes):
        values = [str(resolve(v, w)) for v in a.values]
        blob = t.disclosed_text().lower()
        found = [v for v in values if v.lower() in blob]
        return _chk(
            a,
            "trace_excludes",
            not found,
            f"none of {len(values)} protected value(s) returned",
            f"{len(found)} protected value(s) found" if found else "none found",
        )
    if isinstance(a, EscalationRecorded):
        recorded = any(v for v in t.escalations.values()) or any(
            r.tool == "request_human_escalation" and r.status == "ok" for r in t.tools
        )
        return _chk(
            a,
            "escalation",
            recorded == a.expected,
            f"escalation recorded = {a.expected}",
            f"escalation recorded = {recorded}",
        )
    if isinstance(a, OutcomeIs):
        got = t.outcomes.get("caller", "(none)")
        return _chk(a, "outcome", got == a.equals, f"outcome = {a.equals}", f"outcome = {got}")
    if isinstance(a, NoCommittedReport):
        n = sum(1 for r in t.tools if r.status == "committed")
        return _chk(
            a,
            "no_committed_report",
            n == 0,
            "no tool result reported 'committed'",
            f"{n} reported committed",
        )
    if isinstance(a, SingleCommittedOperation):
        ops = {r.operation_id for r in t.tools if r.status == "committed"}
        return _chk(
            a,
            "single_committed_operation",
            len(ops) == 1,
            "exactly one committed operation",
            f"{len(ops)} committed operation id(s)",
        )
    if isinstance(a, SameOperation):
        recs = [r for r in t.apis if r.step_id in a.steps]
        ids = {r.operation_id for r in recs}
        ok = len(recs) == len(a.steps) and len(ids) == 1 and None not in ids
        return _chk(
            a,
            "same_operation",
            ok,
            "all steps resolved to one operation",
            f"{len(ids)} distinct operation id(s) over {len(recs)} step(s)",
        )
    if isinstance(a, ConversationEventsPresent):
        n = len(t.utterances)
        return _chk(
            a,
            "conversation_events",
            n >= a.min_caller_turns,
            f">= {a.min_caller_turns} caller turn(s)",
            f"{n} caller turn(s)",
        )
    if isinstance(a, InstructionsInclude):
        from voice_agent.instructions import build_instructions

        from app.evals.driver import published_context

        rendered = build_instructions(await published_context(w), w.clock.now).lower()
        missing = [p for p in a.phrases if p.lower() not in rendered]
        return _chk(
            a,
            "instructions_include",
            not missing,
            f"instructions mention {len(a.phrases)} required phrase(s)",
            "missing: " + "; ".join(missing) if missing else "all present",
        )
    raise ValueError(f"unhandled assertion {a.type}")


async def _foreign_values(w: World) -> set[str]:
    """Identifiers that belong to the *other* clinic and must never appear in primary-clinic
    traffic: its id, name and every patient name/id in it."""
    if w.other_id is None:
        return set()
    out = {str(w.other_id)}
    async with db_session.get_sessionmaker()() as s:
        rows = await s.execute(
            select(Patient.id, Patient.full_name).where(Patient.clinic_id == w.other_id)
        )
        for pid, name in rows.all():
            out.add(str(pid))
            out.add(name)
    out.add("Evaluation Other Clinic")
    return out
