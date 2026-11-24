"""Evaluation runner: executes selected scenarios one at a time, each in its own database.

Failure semantics (never "passed" by accident):
* assertion failed            -> scenario `failed`
* setup/driver crashed        -> scenario `error`
* timeout                     -> scenario `incomplete`
* requirement unmet           -> scenario `skipped` (not success)
* mode unavailable/cancelled  -> scenario `not_run`
A run is `incomplete` if any scenario errored or timed out, `cancelled` on request and `error`
if the runner itself crashed.
"""

import asyncio
import dataclasses
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.evals import RUNNER_VERSION
from app.evals.analysis import count_results
from app.evals.assertions import appointment_counts, compile_expected, evaluate
from app.evals.driver import execute_workflow
from app.evals.fixtures import FixtureError, RunDatabases, SourceConfig, World, build_world
from app.evals.llm import availability
from app.evals.loader import Selection, load_suite, select
from app.evals.schema import Scenario
from app.evals.store import ResultsStore, config_hash, jsonable
from app.evals.trace import Check, Trace, clip
from app.schemas.clinic import ClinicConfig

SETUP_TIMEOUT = 90
POLL_SECONDS = 1.0

DatabaseFactory = Callable[[], RunDatabases]


def unmet_requirements(s: Scenario, config: ClinicConfig) -> list[str]:
    out: list[str] = []
    r = s.requires
    have_caps = set(config.agent.allowed_capabilities)
    for c in r.capabilities:
        if c not in have_caps:
            out.append(f"capability '{c}' is not enabled")
    if r.standard_type and not any(
        not t.requires_human_escalation for t in config.appointment_types
    ):
        out.append("no appointment type the agent may book directly")
    if r.escalation_type and not any(t.requires_human_escalation for t in config.appointment_types):
        out.append("no appointment type that requires human escalation")
    have_intents = set(config.agent.supported_intents)
    for i in r.intents:
        if i not in have_intents:
            out.append(f"intent '{i}' is not supported")
    return out


def _trace_json(t: Trace) -> dict[str, Any]:
    out: dict[str, Any] = jsonable(
        {
            "tools": [dataclasses.asdict(x) for x in t.tools],
            "apis": [dataclasses.asdict(x) for x in t.apis],
            "utterances": [{"actor": a, "text": clip(x)} for a, x in t.utterances],
            "agent_texts": [clip(x) for x in t.agent_texts],
            "notes": t.notes,
            "outcomes": t.outcomes,
            "escalations": t.escalations,
        }
    )
    return out


def _expected_json(s: Scenario) -> dict[str, Any]:
    out: dict[str, Any] = jsonable(s.expected.model_dump())
    return out


class Cancelled(Exception):
    pass


class Runner:
    def __init__(
        self,
        store: ResultsStore,
        run_id: uuid.UUID,
        databases: DatabaseFactory = RunDatabases,
    ) -> None:
        self.store, self.run_id, self._databases = store, run_id, databases
        self.statuses: list[str] = []
        self.position = 0

    # ------------------------------------------------------------------------ public -------
    async def run(self) -> str:
        run = await self.store.load_run(self.run_id)
        started = await self.store.start(
            self.run_id,
            {"runner_version": RUNNER_VERSION, "isolation": "database_per_scenario"},
        )
        if not started:
            return run.status
        dbs: RunDatabases | None = None
        try:
            cv = await self.store.load_version(run.config_version_id)
            config = ClinicConfig.model_validate(cv.snapshot)
            source = SourceConfig(run.clinic_id, cv.version, config, config_hash(cv.snapshot))
            suite = load_suite()
            chosen = select(
                suite, Selection(run.selection.get("kind", "all"), run.selection.get("value"))
            )
            chosen = [s for s in chosen if run.mode in s.modes]
            avail = availability()[run.mode]
            if not avail.available:
                await self._record_all(chosen, "not_run", avail.reason or "Mode unavailable")
                return await self._finish("incomplete", None)
            dbs = self._databases()
            await asyncio.to_thread(dbs.create_template)
            cancelled = False
            for index, scenario in enumerate(chosen):
                if await self.store.cancel_requested(self.run_id):
                    cancelled = True
                    await self._record_all(chosen[index:], "not_run", "Run was cancelled.")
                    break
                await self._one(scenario, source, dbs, index)
            return await self._finish("cancelled" if cancelled else None, None)
        except Exception as e:  # noqa: BLE001 - the run must end in a terminal state
            return await self._finish(
                "error", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
            )
        finally:
            if dbs is not None:
                try:
                    await dbs.restore()
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.to_thread(dbs.drop_all)

    # ------------------------------------------------------------------------ internals -----
    async def _record_all(self, scenarios: list[Scenario], status: str, why: str) -> None:
        for s in scenarios:
            await self._persist(s, status, failure=why, trace=Trace(), checks=[], duration=0)

    async def _persist(
        self,
        s: Scenario,
        status: str,
        *,
        failure: str | None,
        trace: Trace,
        checks: list[Check],
        duration: int,
        started: datetime | None = None,
    ) -> None:
        self.statuses.append(status)
        self.position += 1
        not_eval = list(s.not_evaluated_in_workflow) if status != "not_run" else []
        await self.store.add_result(
            self.run_id,
            {
                "scenario_id": s.id,
                "scenario_version": s.version,
                "scenario_hash": s.content_hash(),
                "name": s.name,
                "category": s.category,
                "severity": s.severity,
                "mode": "workflow",
                "status": status,
                "position": self.position,
                "expected": _expected_json(s),
                "observed": _trace_json(trace),
                "assertions": [c.as_dict() for c in checks],
                "failure": failure,
                "not_evaluated": not_eval,
                "duration_ms": duration,
                "started_at": started,
                "finished_at": datetime.now(UTC),
            },
            trace.events,
        )
        await self.store.progress(self.run_id, None, count_results(self.statuses))

    async def _one(self, s: Scenario, source: SourceConfig, dbs: RunDatabases, index: int) -> None:
        started = datetime.now(UTC)
        await self.store.progress(self.run_id, s.id, count_results(self.statuses))
        unmet = unmet_requirements(s, source.config)
        if unmet:
            await self._persist(
                s,
                "skipped",
                failure="Requirements not met: " + "; ".join(unmet),
                trace=Trace(),
                checks=[],
                duration=0,
                started=started,
            )
            return
        trace = Trace()
        checks: list[Check] = []
        status, failure = "error", None
        name: str | None = None
        world: World | None = None
        try:
            name = await asyncio.to_thread(dbs.scenario_db, index)
            await dbs.use(name)
            world = await asyncio.wait_for(build_world(s, source), SETUP_TIMEOUT)
            world.baseline = await appointment_counts(world)
            assert s.workflow is not None
            try:
                driver = await self._guarded(execute_workflow(s, world), s.workflow.timeout_seconds)
                trace = driver.trace
            except TimeoutError:
                status, failure = (
                    "incomplete",
                    (f"Scenario exceeded its {s.workflow.timeout_seconds}s time limit."),
                )
            except Cancelled:
                status, failure = "incomplete", "Scenario was cancelled while running."
            else:
                checks = list(trace.checks)
                checks += await evaluate(
                    compile_expected(s) + list(s.workflow.assertions), world, trace
                )
                bad = [c for c in checks if not c.passed]
                status = "failed" if bad else "passed"
                if bad:
                    failure = "; ".join(
                        f"{c.id}: expected {c.expected}, observed {c.observed}" for c in bad[:5]
                    )
        except FixtureError as e:
            status, failure = "error", f"Setup failed: {e}"
        except Exception as e:  # noqa: BLE001
            status, failure = "error", f"{type(e).__name__}: {str(e)[:500]}"
        finally:
            if world is not None:
                try:
                    await world.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                await dbs.restore()
            except Exception:  # noqa: BLE001
                pass
            if name is not None:
                await asyncio.to_thread(dbs.drop, name)
        duration = int((datetime.now(UTC) - started).total_seconds() * 1000)
        await self._persist(
            s,
            status,
            failure=failure,
            trace=trace,
            checks=checks,
            duration=duration,
            started=started,
        )

    async def _guarded(self, coro: Any, timeout: float) -> Any:
        """Run with a time limit, polling for a cancel request and refreshing the heartbeat."""
        task = asyncio.ensure_future(coro)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=min(POLL_SECONDS, timeout))
                if done:
                    return task.result()
                if loop.time() >= deadline:
                    raise TimeoutError
                await self.store.heartbeat(self.run_id)
                if await self.store.cancel_requested(self.run_id):
                    raise Cancelled
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001
                    pass

    async def _finish(self, forced: str | None, error: str | None) -> str:
        counts = count_results(self.statuses)
        if forced:
            status = forced
        elif any(x in ("error", "incomplete") for x in self.statuses):
            status = "incomplete"
        else:
            status = "completed"
        # Readiness is derived on read from these immutable results, never stored separately.
        await self.store.finish(self.run_id, status, counts, None, error)
        return status
