"""Transport-level tests of CallRuntime with scripted pipeline events (no audio, no providers).

Kind of test: transport unit. These prove event ordering, deduplication, redaction, state changes,
failure handling and cleanup for the worker's own code. They do NOT prove speech recognition,
speech synthesis, model behavior or acoustic barge-in: an interruption here is a scripted
`interrupted=True` event, not sound.
"""

from datetime import UTC, datetime
from typing import Any

from tests.helpers import make_ctx
from voice_agent.events import EventRecorder
from voice_agent.runtime import CallRuntime
from voice_agent.states import Conversation, StateTracker, Transport


class FakeReporter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.states: list[dict[str, Any]] = []
        self.fail_flushes = 0

    async def send_events(self, events: list[dict[str, Any]]) -> None:
        if self.fail_flushes:
            self.fail_flushes -= 1
            raise RuntimeError("backend down")
        self.events.extend(events)

    async def send_state(self, state: dict[str, Any]) -> None:
        self.states.append(state)


class _Metrics:
    def as_dict(self) -> dict[str, Any]:
        return {"tool_calls": 0}


class FakeBox:
    """Stands in for the Toolbox: records what the runtime reads, with scripted outcomes."""

    def __init__(self) -> None:
        self.pending = None
        self.patient_name = None
        self.committed: list[dict[str, Any]] = []
        self.escalation_reason: str | None = None
        self.last_unknown = None
        self.operation_ids: list[str] = []
        self.metrics = _Metrics()
        self.user_turns: list[str] = []

    def note_user_turn(self, text: str) -> None:
        self.user_turns.append(text)

    def outcome(self) -> str:
        return "appointment_booked" if self.committed else "no_action"


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def build(box: FakeBox | None = None) -> tuple[CallRuntime, FakeReporter, FakeBox, Clock]:
    reporter = FakeReporter()
    box = box or FakeBox()
    clock = Clock()
    rec = EventRecorder(reporter, clock=lambda: datetime(2026, 3, 2, 15, 0, tzinfo=UTC))
    rt = CallRuntime(
        make_ctx(),
        box,  # type: ignore[arg-type]
        rec,
        StateTracker(),
        monotonic=clock,
    )
    return rt, reporter, box, clock


async def test_scripted_conversation_is_ordered_and_deduplicated() -> None:
    rt, rep, box, _ = build()
    rt.on_transport(Transport.CONNECTING)
    rt.on_transport(Transport.CONNECTED)
    rt.on_user_interim("I would li")  # interim text is live state only
    rt.on_user_final("u1", "I would like a checkup.")
    rt.on_user_final("u1", "I would like a checkup.")  # duplicate delivery
    rt.on_agent_final("a1", "Sure, what day works?", interrupted=False)
    await rt.sync()
    kinds = [e["kind"] for e in rep.events]
    assert [e["seq"] for e in rep.events] == list(range(len(rep.events)))
    assert kinds.count("transcript") == 2
    assert all("I would li" != e["payload"].get("text") for e in rep.events)
    assert box.user_turns == ["I would like a checkup."]
    assert len({e["event_id"] for e in rep.events}) == len(rep.events)


async def test_interrupted_turn_records_only_what_was_spoken() -> None:
    rt, rep, _, _ = build()
    rt.on_transport(Transport.CONNECTED)
    rt.on_agent_final("a1", "We have openings on Mon", interrupted=True)
    await rt.sync()
    spoken = next(e for e in rep.events if e["kind"] == "transcript")["payload"]
    assert spoken["interrupted"] is True and spoken["text"] == "We have openings on Mon"
    assert rt.interruptions == 1


async def test_response_latency_uses_caller_speech_end_to_agent_speech_start() -> None:
    rt, _, _, clock = build()
    rt.on_transport(Transport.CONNECTED)
    rt.on_user_state("listening", "speaking")
    rt.on_user_state("speaking", "listening")
    clock.t += 0.8
    rt.on_agent_state("speaking")
    assert rt.response_latencies_ms == [800]


async def test_recoverable_provider_error_enters_recovering_and_is_recorded() -> None:
    rt, rep, _, _ = build()
    rt.on_transport(Transport.CONNECTED)
    rt.on_pipeline_error("tts", "provider timeout", recoverable=True)
    await rt.sync()
    assert rt.tracker.conversation == Conversation.RECOVERING
    err = next(e for e in rep.events if e["kind"] == "error")["payload"]
    assert err == {"source": "tts", "message": "provider timeout", "recoverable": True}


async def test_unrecoverable_error_ends_failed_without_claiming_success() -> None:
    rt, _, _, _ = build()
    rt.on_transport(Transport.CONNECTED)
    rt.on_pipeline_error("llm", "provider unavailable", recoverable=False)
    result = await rt.finish(error="llm: provider unavailable")
    assert result["status"] == "failed" and result["outcome"] == "failed"
    assert result["operation_ids"] == []
    assert rt.tracker.transport == Transport.FAILED


async def test_connection_that_never_succeeds_reports_failure() -> None:
    rt, _, _, _ = build()
    rt.on_transport(Transport.CONNECTING)
    result = await rt.finish(error="could not connect", transport_lost=True)
    assert result["outcome"] == "failed" and result["metrics"]["transport_lost"] is True


async def test_event_flush_failure_keeps_order_and_loses_nothing() -> None:
    rt, rep, _, _ = build()
    rt.on_transport(Transport.CONNECTED)
    rt.on_user_final("u1", "hello")
    rep.fail_flushes = 2
    await rt.sync()
    await rt.sync()
    assert rep.events == []  # nothing delivered yet, nothing dropped
    rt.on_agent_final("a1", "hi", interrupted=False)
    await rt.sync()
    assert [e["seq"] for e in rep.events] == list(range(len(rep.events)))
    assert [e["payload"].get("text") for e in rep.events if e["kind"] == "transcript"] == [
        "hello",
        "hi",
    ]
    assert rt.rec.failures == 2


async def test_finish_stops_the_pump_and_drains_events() -> None:
    rt, rep, _, _ = build()
    await rt.start()
    rt.on_transport(Transport.CONNECTED)
    rt.on_user_final("u1", "bye")
    result = await rt.finish()
    assert rt._task is not None and rt._task.done()
    assert rt.rec.pending == 0
    assert any(e["payload"].get("text") == "bye" for e in rep.events)
    assert result["status"] == "completed" and result["outcome"] == "no_action"
    assert rt.tracker.transport == Transport.DISCONNECTED


async def test_sensitive_values_never_reach_the_backend_channel() -> None:
    rt, rep, _, _ = build()
    rt.rec.record("tool", {"name": "verify", "date_of_birth": "1990-01-01", "ok": True})
    rt.rec.record("tool", {"name": "x", "args": {"phone_last4": "1234", "k": 1}})
    await rt.sync()
    blob = str(rep.events) + str(rep.states)
    assert "1990-01-01" not in blob and "1234" not in blob


async def test_committed_operation_completes_call_and_reports_ids() -> None:
    box = FakeBox()
    box.committed = [{"operation_id": "op-1"}]
    box.operation_ids = ["op-1"]
    rt, _, _, _ = build(box)
    rt.on_transport(Transport.CONNECTED)
    result = await rt.finish()
    assert result["outcome"] == "appointment_booked"
    assert result["operation_ids"] == ["op-1"]
    assert any(h[0] == "conversation" and h[2].endswith("completed") for h in rt.tracker.history)
