"""The evaluation runner against a real database: isolation, persistence, status semantics."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.evals.runner import Runner
from app.evals.service import create_run
from app.evals.store import ResultsStore
from app.models import Appointment, Clinic
from app.models.evals import EvalEvent, EvalRun, EvalScenarioResult
from tests.world import World

NORTHSTAR = "Northstar Family Medicine"


async def run_eval(world: World, kind: str = "all", value: str | None = None) -> uuid.UUID:
    clinic_id = world.clinics[NORTHSTAR].id
    async with get_sessionmaker()() as s:
        run = await create_run(
            s, clinic_id, mode="workflow", version=None, kind=kind, value=value, requested_by="test"
        )
    store = ResultsStore(get_settings().database_url)
    try:
        await Runner(store, run.id).run()
    finally:
        await store.dispose()
    return run.id


async def results(run_id: uuid.UUID) -> dict[str, EvalScenarioResult]:
    async with get_sessionmaker()() as s:
        rows = (
            await s.scalars(select(EvalScenarioResult).where(EvalScenarioResult.run_id == run_id))
        ).all()
    return {r.scenario_id: r for r in rows}


def summarize(rs: dict[str, EvalScenarioResult]) -> dict[str, Any]:
    return {k: (v.status, v.failure) for k, v in sorted(rs.items())}


@pytest.mark.asyncio
async def test_single_scenario_passes_and_is_isolated(world: World) -> None:
    before = await _ordinary_state()
    run_id = await run_eval(world, "scenario", "EVAL-001")
    rs = await results(run_id)
    assert summarize(rs) == {"EVAL-001": ("passed", None)}
    r = rs["EVAL-001"]
    assert r.assertions and all(a["passed"] for a in r.assertions)
    assert r.observed["tools"], "the real tool trace is persisted"
    async with get_sessionmaker()() as s:
        run = await s.get(EvalRun, run_id)
        events = (await s.scalars(select(EvalEvent).where(EvalEvent.result_id == r.id))).all()
    assert run is not None and run.status == "completed" and run.counts["passed"] == 1
    assert events, "bounded event trace stored"
    # The ordinary clinics are untouched, and no evaluation database is left behind.
    assert await _ordinary_state() == before
    assert await _leftover_databases() == []


async def _ordinary_state() -> tuple[int, int]:
    async with get_sessionmaker()() as s:
        clinics = len((await s.scalars(select(Clinic.id))).all())
        appts = len((await s.scalars(select(Appointment.id))).all())
    return clinics, appts


async def _leftover_databases() -> list[str]:
    async with get_sessionmaker()() as s:
        rows = await s.execute(
            text(
                "SELECT datname FROM pg_database "
                "WHERE datname ~ '_ev[0-9a-f]{12}_' "
                "AND starts_with(datname, current_database() || '_ev')"
            )
        )
    return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_full_suite_passes(world: World) -> None:
    run_id = await run_eval(world)
    rs = await results(run_id)
    assert len(rs) == 20
    assert summarize(rs) == {k: ("passed", None) for k in sorted(rs)}


# ---- the evaluation must be able to FAIL -------------------------------------------------------
@pytest.mark.asyncio
async def test_changing_shared_toolbox_behavior_changes_results(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evaluation drives the real voice-agent Toolbox. Weakening its confirmation discipline must
    turn the confirmation scenario red, otherwise the evaluation would be testing a copy."""
    from voice_agent.tools import ConfirmArgs, Toolbox, ToolResult

    original = Toolbox.confirm_operation

    async def lax(self: Toolbox, a: ConfirmArgs) -> ToolResult:
        self.user_turns.append(a.caller_words)  # pretend the caller said it
        return await original(self, a)

    monkeypatch.setattr(Toolbox, "confirm_operation", lax)
    rs = await results(await run_eval(world, "scenario", "EVAL-016"))
    assert rs["EVAL-016"].status == "failed"
    assert rs["EVAL-016"].failure and "confirmation_not_heard" in rs["EVAL-016"].failure


@pytest.mark.asyncio
async def test_backend_rule_regression_is_caught(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scheduling-engine regression (hours rule disabled) turns the hours scenario red."""
    from app.scheduling import engine

    monkeypatch.setattr(engine, "check_slot", lambda *a, **k: None)
    rs = await results(await run_eval(world, "scenario", "EVAL-012"))
    assert rs["EVAL-012"].status == "failed"


@pytest.mark.asyncio
async def test_crash_is_error_and_never_passed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("driver exploded")

    monkeypatch.setattr("app.evals.runner.execute_workflow", boom)
    run_id = await run_eval(world, "scenario", "EVAL-001")
    rs = await results(run_id)
    assert rs["EVAL-001"].status == "error" and "driver exploded" in (rs["EVAL-001"].failure or "")
    async with get_sessionmaker()() as s:
        run = await s.get(EvalRun, run_id)
    assert run is not None and run.status == "incomplete"
    assert await _leftover_databases() == []


@pytest.mark.asyncio
async def test_timeout_is_incomplete(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def slow(*a: Any, **k: Any) -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr("app.evals.runner.execute_workflow", slow)
    original = Runner._guarded

    async def quick(self: Runner, coro: Any, timeout: float) -> Any:
        return await original(self, coro, 0.5)

    monkeypatch.setattr(Runner, "_guarded", quick)
    rs = await results(await run_eval(world, "scenario", "EVAL-002"))
    assert rs["EVAL-002"].status == "incomplete", rs["EVAL-002"].failure
    assert "time limit" in (rs["EVAL-002"].failure or "")


@pytest.mark.asyncio
async def test_cancel_before_start_records_not_run(world: World) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import update

    clinic_id = world.clinics[NORTHSTAR].id
    async with get_sessionmaker()() as s:
        run = await create_run(
            s,
            clinic_id,
            mode="workflow",
            version=None,
            kind="category",
            value="appointment_workflows",
            requested_by="test",
        )
        await s.execute(
            update(EvalRun)
            .where(EvalRun.id == run.id)
            .values(cancel_requested_at=datetime.now(UTC))
        )
        await s.commit()
    store = ResultsStore(get_settings().database_url)
    try:
        status = await Runner(store, run.id).run()
    finally:
        await store.dispose()
    assert status == "cancelled"
    rs = await results(run.id)
    assert {r.status for r in rs.values()} == {"not_run"} and len(rs) == 4


def test_unmet_requirements_are_reported() -> None:
    from app.evals.loader import load_suite
    from app.evals.runner import unmet_requirements
    from app.schemas.clinic import ClinicConfig
    from app.seed import NORTHSTAR as CFG

    s = next(x for x in load_suite() if x.id == "EVAL-004")
    assert unmet_requirements(s, CFG) == []
    stripped: ClinicConfig = CFG.model_copy(deep=True)
    stripped.agent.allowed_capabilities = []
    assert unmet_requirements(s, stripped) == ["capability 'cancel_appointment' is not enabled"]


@pytest.mark.asyncio
async def test_llm_mode_is_not_run_without_credentials(world: World) -> None:
    from app.evals.service import EvalError

    async with get_sessionmaker()() as s:
        with pytest.raises(EvalError) as e:
            await create_run(
                s,
                world.clinics[NORTHSTAR].id,
                mode="llm",
                version=None,
                kind="all",
                value=None,
                requested_by="test",
            )
    assert e.value.code == "mode_unavailable"


@pytest.mark.asyncio
async def test_finished_results_are_immutable(world: World) -> None:
    from sqlalchemy.exc import DBAPIError

    run_id = await run_eval(world, "scenario", "EVAL-002")
    async with get_sessionmaker()() as s:
        for stmt in (
            "UPDATE eval_runs SET status = 'running' WHERE id = :i",
            "UPDATE eval_scenario_results SET status = 'passed' WHERE run_id = :i",
            "DELETE FROM eval_scenario_results WHERE run_id = :i",
            "DELETE FROM eval_runs WHERE id = :i",
        ):
            with pytest.raises(DBAPIError):
                await s.execute(text(stmt), {"i": run_id})
            await s.rollback()
