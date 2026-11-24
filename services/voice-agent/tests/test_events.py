from typing import Any

from voice_agent.events import EventRecorder, redact


class Reporter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail = 0

    async def send_events(self, events: list[dict[str, Any]]) -> None:
        if self.fail:
            self.fail -= 1
            raise RuntimeError("backend down")
        self.events.extend(events)

    async def send_state(self, state: dict[str, Any]) -> None:
        pass


def test_redaction_is_recursive() -> None:
    out = redact(
        {
            "a": 1,
            "date_of_birth": "1990-01-01",
            "n": {"phone_last4": "1234", "ok": [{"token": "x", "k": 2}]},
        }
    )
    assert out == {"a": 1, "n": {"ok": [{"k": 2}]}}


async def test_order_and_dedupe() -> None:
    r = Reporter()
    rec = EventRecorder(r)  # type: ignore[arg-type]
    rec.record("transcript", {"text": "hi"}, event_id="item:1")
    rec.record("transcript", {"text": "hi again"}, event_id="item:1")
    rec.record("system", {"event": "x"})
    await rec.flush()
    assert [e["seq"] for e in r.events] == sorted(e["seq"] for e in r.events)
    assert len({e["event_id"] for e in r.events}) == len(r.events) == 2
