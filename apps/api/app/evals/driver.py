"""Workflow driver: executes a scenario's scripted steps through the production M3 call stack.

Shared with the voice worker (imported, not copied): `Toolbox` (tool validation, capability gating,
proposal/confirmation discipline, idempotent execution and reconciliation), `SchedulingClient`,
`CallRuntime` (transcript/state events), `EventRecorder`, `StateTracker`, `CallContext`.

Substituted: the audio pipeline and the language model. In a workflow scenario the *scenario file*
chooses each tool call, so this mode proves tool, authorization, business-rule and database
behavior, never that a model would pick those calls.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from voice_agent.contracts import CallContext
from voice_agent.events import EventRecorder
from voice_agent.runtime import CallRuntime
from voice_agent.scheduling_client import SchedulingClient
from voice_agent.states import Conversation, StateTracker, Transport
from voice_agent.tools import Toolbox

from app.db import session as db_session
from app.evals.fixtures import FixtureError, World, resolve, verify_token
from app.evals.schema import (
    ApiStep,
    ClearFaultsStep,
    Expect,
    InjectStep,
    ParallelStep,
    SayStep,
    Scenario,
    Step,
    ToolStep,
)
from app.evals.trace import MAX_TRACE_EVENTS, ApiRecord, Check, ToolRecord, Trace, clip
from app.models import ConfigVersion


class MemoryReporter:
    """Receives the events the worker would send to the backend. Nothing is persisted from here
    except through the evaluation store, and only after redaction (done by the recorder)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.states: list[dict[str, Any]] = []

    async def send_events(self, events: list[dict[str, Any]]) -> None:
        self.events.extend(events)

    async def send_state(self, state: dict[str, Any]) -> None:
        self.states.append(state)


class Actor:
    def __init__(
        self, name: str, ctx: CallContext, box: Toolbox, runtime: CallRuntime, rep: MemoryReporter
    ) -> None:
        self.name, self.ctx, self.box, self.runtime, self.reporter = name, ctx, box, runtime, rep
        self.utterances = 0


async def published_context(world: World, call_session_id: uuid.UUID | None = None) -> CallContext:
    """The frozen context a worker would receive from the claim endpoint."""
    async with db_session.get_sessionmaker()() as session:
        cv = await session.scalar(
            select(ConfigVersion)
            .where(ConfigVersion.clinic_id == world.primary_id)
            .order_by(ConfigVersion.version.desc())
            .limit(1)
        )
    if cv is None:
        raise FixtureError("the fixture clinic has no published version")
    return CallContext.model_validate(
        {
            "call_session_id": str(call_session_id or uuid.uuid4()),
            "clinic_id": str(world.primary_id),
            "config_version": cv.version,
            "room_name": f"eval-{uuid.uuid4().hex[:8]}",
            "created_at": world.clock.now.isoformat(),
            "config": cv.snapshot,
        }
    )


async def make_actor(name: str, world: World) -> Actor:
    ctx = await published_context(world)
    reporter = MemoryReporter()
    rec = EventRecorder(reporter, clock=world.clock)
    tracker = StateTracker()
    tracker.set_transport(Transport.CONNECTED)
    tracker.set_conversation(Conversation.READY)
    sched = SchedulingClient(world.http, ctx.clinic_id)

    async def nosleep(_: float) -> None:
        return None

    box = Toolbox(ctx, sched, rec, tracker, clock=world.clock, sleep=nosleep)
    runtime = CallRuntime(ctx, box, rec, tracker, clock=world.clock)
    return Actor(name, ctx, box, runtime, reporter)


def _match(actual: str, wanted: str | list[str] | None) -> bool:
    if wanted is None:
        return True
    return actual in ([wanted] if isinstance(wanted, str) else wanted)


class Driver:
    def __init__(self, scenario: Scenario, world: World, actors: dict[str, Actor]) -> None:
        self.s, self.world, self.actors = scenario, world, actors
        self.trace = Trace()
        self._n = 0
        self._api_n = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ steps -------------
    async def run(self, steps: list[Step]) -> None:
        for step in steps:
            await self._step(step)

    async def _step(self, step: Step) -> None:
        if isinstance(step, SayStep):
            self._say(step)
        elif isinstance(step, ToolStep):
            await self._tool(step)
        elif isinstance(step, ApiStep):
            await self._api(step)
        elif isinstance(step, InjectStep):
            self._inject(step)
        elif isinstance(step, ClearFaultsStep):
            self.world.faults.clear()
            self.world.transport.clear()
            self.trace.note("faults cleared")
        elif isinstance(step, ParallelStep):
            await asyncio.gather(*(self.run(list(branch)) for branch in step.branches))

    def _say(self, step: SayStep) -> None:
        actor = self.actors[step.actor]
        text = str(resolve(step.text, self.world))
        actor.utterances += 1
        actor.runtime.on_user_final(f"{actor.name}-u{actor.utterances}", text, self.world.clock())
        self.trace.utterances.append((actor.name, text))

    async def _tool(self, step: ToolStep) -> None:
        actor = self.actors[step.actor]
        args = resolve(step.args, self.world)
        result = await actor.box.call(step.tool, dict(args))
        text = json.dumps(result.for_llm(), default=str)
        async with self._lock:
            self._n += 1
            rec = ToolRecord(
                self._n,
                actor.name,
                step.tool,
                args,
                step.id,
                result.status,
                result.code,
                result.ok,
                result.operation_id,
                text,
            )
            self.trace.tools.append(rec)
        if step.expect:
            self._check_expect(
                step.id or f"{step.tool}#{rec.n}",
                step.expect,
                result.status,
                result.code,
                result.ok,
            )

    async def _api(self, step: ApiStep) -> None:
        w = self.world
        path = str(resolve(step.path, w))
        base = f"/api/clinics/{w.clinic_id(step.clinic)}"
        headers: dict[str, str] = {}
        if step.as_patient:
            headers["Authorization"] = (
                f"Bearer {await verify_token(w, w.patients[step.as_patient])}"
            )
        if step.idempotency_key:
            headers["Idempotency-Key"] = str(resolve(step.idempotency_key, w))
        body = resolve(step.body, w) if step.body is not None else None
        resp = await w.http.request(step.method, f"{base}{path}", json=body, headers=headers)
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = str(err.get("code", "")) if isinstance(err, dict) else ""
        async with self._lock:
            self._api_n += 1
            self.trace.apis.append(
                ApiRecord(
                    self._api_n,
                    step.id,
                    step.method,
                    f"{base}{path}",
                    resp.status_code,
                    code,
                    clip(resp.text, 800),
                    resp.headers.get("X-Operation-Id"),
                    resp.headers.get("Idempotent-Replay", "").lower() == "true",
                )
            )
        for var, dotted in step.capture.items():
            value: Any = payload
            for part in dotted.split("."):
                if isinstance(value, list) and part.isdigit():
                    value = value[int(part)] if int(part) < len(value) else None
                else:
                    value = value.get(part) if isinstance(value, dict) else None
            if value is None:
                raise FixtureError(f"api step could not capture '{dotted}' from the response")
            self.world.variables[var] = str(value)
        if step.expect:
            self._check_expect(
                step.id or f"api#{self._api_n}",
                step.expect,
                str(resp.status_code),
                code,
                resp.is_success,
                resp.headers.get("Idempotent-Replay", "").lower() == "true",
            )

    def _inject(self, step: InjectStep) -> None:
        f = step.fault
        w = self.world
        if f.type == "scheduling_fault":
            exc: BaseException = (
                TimeoutError("injected timeout")
                if f.error == "timeout"
                else ConnectionError("injected outage")
            )
            w.faults.fail_at(f.point or "before_commit", exc, f.times)
            self.trace.note(f"injected scheduling fault {f.error} at {f.point} x{f.times}")
        elif f.type == "drop_response":
            w.transport.match, w.transport.drop_response = f.match, f.times
            self.trace.note(f"injected lost response on POST *{f.match}* x{f.times}")
        elif f.type == "drop_request":
            w.transport.match, w.transport.drop_request = f.match, f.times
            self.trace.note(f"injected lost request on POST *{f.match}* x{f.times}")
        else:
            w.transport.down = True
            w.transport.match = f.match
            self.trace.note("injected backend outage")

    def _check_expect(
        self,
        label: str,
        expect: Expect,
        status: str,
        code: str,
        ok: bool,
        replay: bool | None = None,
    ) -> None:
        def add(kind: str, passed: bool, want: object, got: object) -> None:
            self.trace.checks.append(
                Check(
                    id=f"step:{label}:{kind}",
                    type="step_expectation",
                    passed=passed,
                    expected=f"{kind} = {want}",
                    observed=f"{kind} = {got}",
                    source="step",
                )
            )

        if expect.status is not None:
            add("status", _match(status, expect.status), expect.status, status)
        if expect.code is not None:
            add("code", _match(code, expect.code), expect.code, code or "(none)")
        if expect.ok is not None:
            add("ok", ok == expect.ok, expect.ok, ok)
        if expect.replay is not None:
            add("replay", replay == expect.replay, expect.replay, replay)

    # ------------------------------------------------------------------ evidence ----------
    async def finish(self) -> None:
        """Flush recorded events, collect outcome/escalation facts and a bounded event trace."""
        for name, actor in self.actors.items():
            await actor.runtime.sync()
            self.trace.outcomes[name] = actor.box.outcome()
            self.trace.escalations[name] = actor.box.escalation_reason
            for e in actor.reporter.events:
                if e["kind"] == "transcript" and e["payload"].get("speaker") == "agent":
                    self.trace.agent_texts.append(str(e["payload"].get("text", "")))
        merged: list[dict[str, Any]] = []
        for name, actor in self.actors.items():
            for e in actor.reporter.events:
                if e["kind"] in ("transcript", "tool", "operation", "error"):
                    merged.append({**e, "actor": name})
        merged.sort(key=lambda e: (e["occurred_at"], e["seq"]))
        self.trace.events = merged[:MAX_TRACE_EVENTS]


async def execute_workflow(scenario: Scenario, world: World) -> Driver:
    assert scenario.workflow is not None
    actors = {name: await make_actor(name, world) for name in scenario.actors}
    driver = Driver(scenario, world, actors)
    started = datetime.now(UTC)
    try:
        await driver.run(list(scenario.workflow.steps))
    finally:
        await driver.finish()
    driver.trace.note(f"workflow finished in {(datetime.now(UTC) - started).total_seconds():.2f}s")
    return driver
