"""Session event recording with stable ids, ordering and redaction.

Events are reported to the backend over the authenticated worker channel (not through the
browser). Every event has a stable ``event_id`` and a monotonically increasing ``seq`` so the
backend can deduplicate retries and the UI can order and merge without duplicates.

Redaction happens here first (the backend scrubs again): date of birth, phone digits, bearer and
confirmation tokens are never recorded.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger("voice_agent.events")

FORBIDDEN = {
    "date_of_birth",
    "dob",
    "phone",
    "phone_last4",
    "token",
    "access_token",
    "confirmation_token",
    "authorization",
    "authorization_token",
    "api_key",
    "secret",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if k.lower() not in FORBIDDEN}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Reporter(Protocol):
    async def send_events(self, events: list[dict[str, Any]]) -> None: ...
    async def send_state(self, state: dict[str, Any]) -> None: ...


class EventRecorder:
    """Assigns seq/ids and ships events in order. A failed flush keeps the batch and retries, so
    ordering and completeness survive a flaky backend; ``flush`` at shutdown drains the queue."""

    def __init__(
        self,
        reporter: Reporter,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        batch_size: int = 50,
    ) -> None:
        self._reporter = reporter
        self._clock = clock
        self._seq = 0
        self._seen: set[str] = set()
        self._queue: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._batch = batch_size
        self.sent: list[dict[str, Any]] = []
        self.failures = 0

    def record(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Queue an event. Returns None if ``event_id`` was already recorded (dedupe)."""
        eid = event_id or f"{kind}:{self._seq}"
        if eid in self._seen:
            return None
        self._seen.add(eid)
        event = {
            "event_id": eid,
            "seq": self._seq,
            "kind": kind,
            "occurred_at": (occurred_at or self._clock()).isoformat(),
            "payload": redact(payload),
        }
        self._seq += 1
        self._queue.append(event)
        return event

    @property
    def pending(self) -> int:
        return len(self._queue)

    async def flush(self) -> bool:
        async with self._lock:
            while self._queue:
                batch = self._queue[: self._batch]
                try:
                    await self._reporter.send_events(batch)
                except Exception as e:  # noqa: BLE001 - reporting must never crash the call
                    self.failures += 1
                    log.warning("event flush failed (%s); will retry", type(e).__name__)
                    return False
                del self._queue[: len(batch)]
                self.sent.extend(batch)
        return True

    async def push_state(self, state: dict[str, Any]) -> None:
        try:
            await self._reporter.send_state(redact(state))
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            log.warning("state push failed (%s)", type(e).__name__)
