"""CallRuntime: turns audio-pipeline notifications into recorded events and state, and builds the
final report. It knows nothing about LiveKit types, so its behaviour is unit-testable without a
media server; ``worker.py`` is the only module that adapts LiveKit events onto these methods.

Timestamps: ``occurred_at`` is the worker's wall clock when the event was handled (or the
pipeline's own ``created_at`` when it supplies one). It is not synchronized with the browser.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from voice_agent.contracts import CallContext
from voice_agent.events import EventRecorder
from voice_agent.states import Conversation, StateTracker, Transport
from voice_agent.tools import Toolbox

log = logging.getLogger("voice_agent.runtime")

# Phases the caller should keep seeing while the audio pipeline flips between
# listening/thinking/speaking underneath them.
STICKY = {
    Conversation.AWAITING_CONFIRMATION,
    Conversation.WAITING_VERIFICATION,
    Conversation.ESCALATED,
    Conversation.RECOVERING,
    Conversation.EXECUTING_TOOL,
}
_AGENT_TO_CONV = {
    "listening": Conversation.LISTENING,
    "thinking": Conversation.THINKING,
    "speaking": Conversation.SPEAKING,
}


class CallRuntime:
    def __init__(
        self,
        ctx: CallContext,
        toolbox: Toolbox,
        recorder: EventRecorder,
        tracker: StateTracker,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ctx, self.box, self.rec, self.tracker = ctx, toolbox, recorder, tracker
        self._mono, self._clock = monotonic, clock
        self.activity = "idle"
        self.interim_user = ""
        self.interruptions = 0
        self.response_latencies_ms: list[int] = []
        self._user_stopped_at: float | None = None
        self._dirty = True
        self._task: asyncio.Task[None] | None = None
        self._started = monotonic()
        self.errors: list[str] = []
        tracker.on_change = self._on_change

    # ------------------------------------------------------------------ plumbing -----------
    def _on_change(self, machine: str, src: str, dst: str) -> None:
        self.rec.record("state", {"machine": machine, "from": src, "to": dst})
        self._dirty = True

    def live_state(self) -> dict[str, Any]:
        return {
            **self.tracker.snapshot(),
            "activity": self.activity,
            "interim_user": self.interim_user,
            "agent_name": self.ctx.config.agent.agent_name,
            "pending_confirmation": bool(self.box.pending and not self.box.pending.confirmed),
            "verified_patient": self.box.patient_name,
        }

    async def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        while True:
            await asyncio.sleep(0.35)
            await self.sync()

    async def sync(self) -> None:
        await self.rec.flush()
        if self._dirty:
            self._dirty = False
            await self.rec.push_state(self.live_state())

    # ------------------------------------------------------------------ transport ----------
    def on_transport(self, state: Transport) -> None:
        self.tracker.set_transport(state)
        self.rec.record("system", {"event": f"transport_{state.value}"})
        if state == Transport.CONNECTED:
            self.tracker.set_conversation(Conversation.READY)
        self._dirty = True

    # ------------------------------------------------------------------ pipeline events ----
    def on_agent_state(self, new: str) -> None:
        self.activity = new
        if new == "speaking" and self._user_stopped_at is not None:
            self.response_latencies_ms.append(round((self._mono() - self._user_stopped_at) * 1000))
            self._user_stopped_at = None
        conv = _AGENT_TO_CONV.get(new)
        if conv and self.tracker.conversation not in STICKY:
            self.tracker.set_conversation(conv)
        elif (
            conv and self.tracker.conversation == Conversation.EXECUTING_TOOL and new != "thinking"
        ):
            pass
        self._dirty = True

    def on_user_state(self, old: str, new: str) -> None:
        if old == "speaking" and new != "speaking":
            self._user_stopped_at = self._mono()
        if new == "speaking":
            self._user_stopped_at = None
        self._dirty = True

    def on_user_interim(self, text: str) -> None:
        """Interim transcripts only update live state; they are never recorded as events."""
        self.interim_user = text
        self._dirty = True

    def on_user_final(self, item_id: str, text: str, at: datetime | None = None) -> None:
        self.interim_user = ""
        if not text.strip():
            return
        recorded = self.rec.record(
            "transcript",
            {"speaker": "caller", "text": text, "final": True},
            event_id=f"item:{item_id}",
            occurred_at=at,
        )
        if recorded is not None:  # a redelivered final transcript must not count as a new turn
            self.box.note_user_turn(text)
        self._dirty = True

    def on_agent_final(
        self, item_id: str, text: str, interrupted: bool, at: datetime | None = None
    ) -> None:
        """``text`` is what was actually spoken. For an interrupted turn the pipeline truncates
        it to the portion played before the caller cut in."""
        if interrupted:
            self.interruptions += 1
        if not text.strip() and not interrupted:
            return
        self.rec.record(
            "transcript",
            {"speaker": "agent", "text": text, "final": True, "interrupted": interrupted},
            event_id=f"item:{item_id}",
            occurred_at=at,
        )
        self._dirty = True

    def on_pipeline_error(self, source: str, message: str, recoverable: bool) -> None:
        self.errors.append(f"{source}: {message}")
        self.rec.record(
            "error", {"source": source, "message": message[:300], "recoverable": recoverable}
        )
        if recoverable:
            self.tracker.set_conversation(Conversation.RECOVERING)
        self._dirty = True

    # ------------------------------------------------------------------ shutdown -----------
    async def finish(
        self,
        *,
        provider_usage: dict[str, Any] | None = None,
        error: str | None = None,
        transport_lost: bool = False,
    ) -> dict[str, Any]:
        """Stop pumping, drain events, and build the completion payload."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self.box.committed or self.box.escalation_reason:
            self.tracker.set_conversation(Conversation.COMPLETED)
        elif self.box.last_unknown:
            self.rec.record(
                "operation",
                {"event": "call_ended_with_unknown_outcome", "key": self.box.last_unknown.key},
            )
        self.tracker.set_transport(
            Transport.FAILED if error else Transport.DISCONNECTED
        ) if self.tracker.transport in (
            Transport.CONNECTED,
            Transport.CONNECTING,
            Transport.RECONNECTING,
        ) else None
        outcome = self.box.outcome()
        if error and not self.box.committed:
            outcome = "failed"
        metrics = {
            **self.box.metrics.as_dict(),
            "interruptions": self.interruptions,
            "response_latency_ms": {
                "count": len(self.response_latencies_ms),
                "values": self.response_latencies_ms[-50:],
                "definition": "end of caller speech to start of agent speech, as observed by "
                "the worker",
            },
            "wall_seconds": round(self._mono() - self._started, 3),
            "event_flush_failures": self.rec.failures,
            "transport_lost": transport_lost,
        }
        unknown = self.box.last_unknown
        summary = _summary(outcome, self.box.committed, unknown is not None)
        await self.rec.push_state({**self.live_state(), "ended": True})
        await self.rec.flush()
        return {
            "status": "failed" if error and outcome == "failed" else "completed",
            "outcome": outcome,
            "summary": summary,
            "escalation_reason": self.box.escalation_reason,
            "error": error or (self.errors[-1] if self.errors and outcome == "failed" else None),
            "operation_ids": self.box.operation_ids,
            "metrics": metrics,
            "provider_usage": provider_usage or {},
        }


def _summary(outcome: str, committed: list[dict[str, Any]], unknown: bool) -> str:
    base = {
        "appointment_booked": "An appointment was booked.",
        "appointment_rescheduled": "An appointment was rescheduled.",
        "appointment_cancelled": "An appointment was cancelled.",
        "information_provided": "Information was provided; no appointment changed.",
        "escalated": "The caller was referred to clinic staff; no appointment changed.",
        "no_action": "No scheduling action was taken.",
        "failed": "The call ended with an error.",
    }[outcome]
    if unknown:
        base += " One change had an unconfirmed outcome when the call ended."
    return base
