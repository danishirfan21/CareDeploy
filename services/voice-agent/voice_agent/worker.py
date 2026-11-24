"""LiveKit Agents worker: the only module that touches LiveKit types.

Run (after ``livekit-agents`` is installed and the environment is set):

    python -m voice_agent.worker dev      # development, auto-reload
    python -m voice_agent.worker start    # production-style

Flow per call: the browser receives a token that explicitly dispatches this worker
(`agent_name`) into one room; the job metadata carries only the call-session id. The worker then
*claims* the session from the backend over the authenticated channel and receives the frozen
configuration there. Nothing in room or job metadata is trusted for clinic identity.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    cli,
    function_tool,
)

from voice_agent.backend import BackendClient, BackendError
from voice_agent.events import EventRecorder
from voice_agent.instructions import build_instructions
from voice_agent.providers import ProviderNotConfigured, build_pipeline
from voice_agent.runtime import CallRuntime
from voice_agent.scheduling_client import SchedulingClient
from voice_agent.settings import WorkerSettings
from voice_agent.states import StateTracker, Transport
from voice_agent.tool_schemas import exposed_tool_schemas
from voice_agent.tools import Toolbox

log = logging.getLogger("voice_agent.worker")
SETTINGS = WorkerSettings.from_env()
server = AgentServer()


def _make_tool(box: Toolbox, schema: dict[str, Any]) -> Any:
    name = schema["name"]

    async def handler(raw_arguments: dict[str, object], context: RunContext[Any]) -> str:
        result = await box.call(name, dict(raw_arguments))
        return json.dumps(result.for_llm(), default=str)

    return function_tool(handler, raw_schema=schema)


def _usage(session: AgentSession[Any]) -> dict[str, Any]:
    try:
        return {"models": [m.model_dump(mode="json") for m in session.usage.model_usage]}
    except Exception:  # noqa: BLE001 - usage is best effort and must never block shutdown
        return {}


def _ts(created_at: float | None) -> datetime | None:
    return datetime.fromtimestamp(created_at, UTC) if created_at else None


@server.rtc_session(agent_name=SETTINGS.agent_name)
async def entrypoint(ctx: JobContext) -> None:
    try:
        session_id = uuid.UUID(ctx.job.metadata)
    except ValueError:
        log.error("job metadata is not a call-session id; refusing the job")
        ctx.shutdown("invalid job metadata")
        return

    http = httpx.AsyncClient(
        base_url=SETTINGS.api_base_url, timeout=SETTINGS.request_timeout_seconds
    )
    backend = BackendClient(http, session_id, SETTINGS.worker_secret)
    try:
        call = await backend.claim(ctx.job.room.name)
    except BackendError as e:
        log.error("claim refused: %s", e)
        await http.aclose()
        ctx.shutdown(f"claim refused: {e.code}")
        return

    recorder = EventRecorder(backend)
    tracker = StateTracker()
    box = Toolbox(call, SchedulingClient(http, call.clinic_id), recorder, tracker)
    runtime = CallRuntime(call, box, recorder, tracker)
    await runtime.start()
    session: AgentSession[Any] | None = None
    finished = asyncio.Event()

    async def finish(error: str | None = None, lost: bool = False) -> None:
        if finished.is_set():
            return
        finished.set()
        usage = _usage(session) if session else {}
        report = await runtime.finish(provider_usage=usage, error=error, transport_lost=lost)
        with contextlib.suppress(Exception):
            await backend.complete(report)
        await http.aclose()

    ctx.add_shutdown_callback(finish)

    try:
        pipeline = build_pipeline(SETTINGS)
    except ProviderNotConfigured as e:
        runtime.on_pipeline_error("provider", str(e), recoverable=False)
        await finish(error="provider_not_configured: " + ", ".join(e.missing))
        ctx.shutdown("provider not configured")
        return

    runtime.rec.record(
        "system",
        {
            "event": "call_started",
            "config_version": call.config_version,
            "clinic": call.config.details.name,
            "pipeline": pipeline.description,
        },
    )
    await ctx.connect()
    runtime.on_transport(Transport.CONNECTED)

    room = ctx.room
    room.on("reconnecting", lambda: runtime.on_transport(Transport.RECONNECTING))
    room.on("reconnected", lambda: runtime.on_transport(Transport.CONNECTED))

    def operator_left(participant: Any) -> None:
        # The browser hung up (or lost its connection for good): end the call.
        runtime.rec.record("system", {"event": "operator_disconnected"})
        asyncio.create_task(_shutdown("operator left"))

    async def _shutdown(reason: str) -> None:
        if session:
            await session.aclose()
        ctx.shutdown(reason)

    room.on("participant_disconnected", operator_left)

    session = AgentSession(stt=pipeline.stt, llm=pipeline.llm, tts=pipeline.tts, vad=pipeline.vad)
    agent = Agent(
        instructions=build_instructions(call, datetime.now(UTC)),
        tools=[_make_tool(box, s) for s in exposed_tool_schemas(call)],
    )

    @session.on("agent_state_changed")
    def _agent_state(ev: Any) -> None:
        runtime.on_agent_state(str(ev.new_state))

    @session.on("user_state_changed")
    def _user_state(ev: Any) -> None:
        runtime.on_user_state(str(ev.old_state), str(ev.new_state))

    @session.on("user_input_transcribed")
    def _user_text(ev: Any) -> None:
        if not ev.is_final:
            runtime.on_user_interim(ev.transcript)

    @session.on("conversation_item_added")
    def _item(ev: Any) -> None:
        item = ev.item
        if getattr(item, "type", "") != "message":
            return
        text = item.text_content or ""
        if item.role == "user":
            runtime.on_user_final(item.id, text, _ts(getattr(item, "created_at", None)))
        elif item.role == "assistant":
            runtime.on_agent_final(
                item.id, text, bool(item.interrupted), _ts(getattr(item, "created_at", None))
            )

    @session.on("error")
    def _error(ev: Any) -> None:
        err = ev.error
        runtime.on_pipeline_error(
            str(ev.source.__class__.__name__),
            str(getattr(err, "message", err)),
            bool(getattr(err, "recoverable", True)),
        )

    @session.on("close")
    def _close(ev: Any) -> None:
        asyncio.create_task(finish(error=str(ev.error) if ev.error else None))

    await session.start(agent=agent, room=room)
    await session.say(call.config.agent.greeting, allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(server)
