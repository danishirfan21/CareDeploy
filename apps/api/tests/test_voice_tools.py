"""Voice tools against the real M2 API and real PostgreSQL.

The only test doubles: an in-memory event reporter, and (for the failure cases) an httpx
transport wrapper that loses a response or a request. No LLM, no audio, no LiveKit server is
involved: this verifies the tool layer's contract with the scheduling backend.
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from voice_agent.backend import BackendClient
from voice_agent.contracts import CallContext
from voice_agent.events import EventRecorder
from voice_agent.scheduling_client import SchedulingClient
from voice_agent.states import Conversation, Operation, StateTracker
from voice_agent.tools import Toolbox

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.models import Appointment
from tests.test_voice_sessions import WORKER, _settings, create
from tests.world import World

DAY = "2026-03-03"


class MemoryReporter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.states: list[dict[str, Any]] = []

    async def send_events(self, events: list[dict[str, Any]]) -> None:
        self.events.extend(events)

    async def send_state(self, state: dict[str, Any]) -> None:
        self.states.append(state)


class LossyTransport(httpx.AsyncBaseTransport):
    """Forwards to the app but can lose a request (never delivered) or a response (delivered,
    answer lost), selected by predicate on the request path/method."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.drop_request = 0
        self.drop_response = 0
        self.down = False
        self.match = "/appointments"
        self.calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hit = request.method == "POST" and self.match in request.url.path
        self.calls.append(f"{request.method} {request.url.path}")
        if self.down and (hit or "/operations" in request.url.path):
            raise httpx.ConnectTimeout("backend unreachable", request=request)
        if hit and self.drop_request > 0:
            self.drop_request -= 1
            raise httpx.ConnectTimeout("request lost", request=request)
        resp = await self.inner.handle_async_request(request)
        if hit and self.drop_response > 0:
            self.drop_response -= 1
            await resp.aread()
            raise httpx.ReadTimeout("response lost", request=request)
        return resp


@dataclass
class Rig:
    box: Toolbox
    rec: EventRecorder
    reporter: MemoryReporter
    tracker: StateTracker
    transport: LossyTransport
    ctx: CallContext
    world: World

    async def say(self, text: str) -> None:
        self.box.note_user_turn(text)

    async def verify(self, first: str = "Avery") -> dict[str, Any]:
        p = self.world.p(first)
        r = await self.box.call(
            "verify_patient",
            {
                "patient_name": p.name,
                "date_of_birth": p.dob.isoformat(),
                "phone_last4": p.last4,
            },
        )
        return r.for_llm()

    async def first_slot(self, type_name: str = "Annual physical", **kw: Any) -> str:
        r = await self.box.call(
            "get_appointment_availability",
            {"appointment_type": type_name, "date_from": DAY, **kw},
        )
        assert r.status == "ok", r
        return str(r.data["slots"][0]["slot_ref"])

    async def count(self, patient_first: str) -> int:
        async with get_sessionmaker()() as s:
            return int(
                await s.scalar(
                    select(func.count())
                    .select_from(Appointment)
                    .where(
                        Appointment.patient_id == self.world.p(patient_first).id,
                        Appointment.status == "scheduled",
                    )
                )
                or 0
            )


@pytest.fixture
def _voice() -> Iterator[None]:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: _settings()
    yield
    app.dependency_overrides.pop(get_settings, None)


async def make_rig(world: World, clinic_name: str = "Northstar Family Medicine") -> Rig:
    clinic = world.clinics[clinic_name]
    created = await create(world.client, clinic.id)
    sid = uuid.UUID(created["call_session_id"])
    # The worker's own HTTP client talks to the real app, through a transport we can break.
    from app.main import app

    transport = LossyTransport(ASGITransport(app=app))
    http = AsyncClient(transport=transport, base_url="http://test")
    backend = BackendClient(http, sid, WORKER["X-Voice-Worker-Secret"])
    ctx = await backend.claim(created["room_name"])
    reporter = MemoryReporter()
    rec = EventRecorder(reporter, clock=lambda: datetime.now(UTC))
    tracker = StateTracker()
    tracker.set_transport(
        __import__("voice_agent.states", fromlist=["Transport"]).Transport.CONNECTED
    )
    tracker.set_conversation(Conversation.READY)
    sched = SchedulingClient(http, ctx.clinic_id)

    async def nosleep(_: float) -> None:
        return None

    box = Toolbox(ctx, sched, rec, tracker, sleep=nosleep)
    return Rig(box, rec, reporter, tracker, transport, ctx, world)


# ------------------------------------------------------------------ booking slice -------------
async def test_booking_end_to_end_commits_exactly_one(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    assert rig.ctx.config.agent.agent_name == "Nora"

    slot = await rig.first_slot()
    assert (await rig.verify())["status"] == "ok"
    prop = await rig.box.call(
        "propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot}
    )
    assert prop.status == "ok" and prop.code == "awaiting_caller_confirmation"
    assert rig.tracker.operation == Operation.PROPOSED
    assert rig.tracker.conversation == Conversation.AWAITING_CONFIRMATION
    assert await rig.count("Avery") == 0  # nothing committed before the caller says yes

    await rig.say("Yes, please book that.")
    done = await rig.box.call("confirm_operation", {"caller_words": "yes please book that"})
    assert done.status == "committed" and done.operation_id
    assert rig.tracker.operation == Operation.COMMITTED  # type: ignore[comparison-overlap]  # tool calls mutate the tracker; mypy cannot see it
    assert await rig.count("Avery") == 1
    assert rig.box.outcome() == "appointment_booked"

    again = await rig.box.call("confirm_operation", {"caller_words": "yes please book that"})
    assert again.code == "nothing_to_confirm"
    assert await rig.count("Avery") == 1

    await rig.rec.flush()
    names = [
        (e["payload"].get("name"), e["payload"].get("phase"))
        for e in rig.reporter.events
        if e["kind"] == "tool"
    ]
    assert ("confirm_operation", "finished") in names
    seqs = [e["seq"] for e in rig.reporter.events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


async def test_no_secrets_in_recorded_events(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    await rig.say("yes")
    await rig.box.call("confirm_operation", {"caller_words": "yes"})
    await rig.rec.flush()
    blob = json.dumps(rig.reporter.events)
    p = world.p("Avery")
    assert p.dob.isoformat() not in blob and p.last4 not in blob
    assert "confirmation_token" not in blob and "authorization_token" not in blob


async def test_confirm_requires_a_caller_turn_after_the_proposal(
    _voice: None, world: World
) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.say("book me a physical")  # before the proposal
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    r = await rig.box.call("confirm_operation", {"caller_words": "book me a physical"})
    assert r.code == "confirmation_not_heard"
    await rig.say("hmm let me think")
    r = await rig.box.call("confirm_operation", {"caller_words": "yes"})  # model invented a yes
    assert r.code == "confirmation_not_heard"
    assert await rig.count("Avery") == 0


async def test_changing_the_time_invalidates_the_first_proposal(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    r = await rig.box.call(
        "get_appointment_availability",
        {"appointment_type": "Annual physical", "date_from": DAY, "max_results": 3},
    )
    s1, s2 = r.data["slots"][0]["slot_ref"], r.data["slots"][1]["slot_ref"]
    await rig.verify()
    first = await rig.box.call(
        "propose_booking", {"appointment_type": "Annual physical", "slot_ref": s1}
    )
    first_pending = rig.box.pending
    assert first.ok and first_pending
    await rig.say("actually the second one")
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": s2})
    assert rig.box.pending and rig.box.pending.proposal_id != first_pending.proposal_id
    await rig.say("yes")
    done = await rig.box.call("confirm_operation", {"caller_words": "yes"})
    assert done.status == "committed"
    appts = await world.appointments(world.p("Avery"))
    assert len(appts) == 1
    assert (
        appts[0]["start_at"]
        .replace("Z", "+00:00")
        .startswith(rig.box.slots[s2]["start_at"].replace("Z", "+00:00")[:16])
    )
    # The superseded proposal can no longer be used against the backend.
    assert any(e["payload"].get("event") == "proposal_invalidated" for e in rig.rec._queue)


async def test_withdraw_changes_nothing(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    out = await rig.box.call("withdraw_pending_proposal", {"reason": "changed mind"})
    assert out.ok and rig.box.pending is None
    assert rig.tracker.operation == Operation.INVALIDATED
    assert await rig.count("Avery") == 0
    assert (
        await rig.box.call("confirm_operation", {"caller_words": "yes"})
    ).code == "nothing_to_confirm"


async def test_slot_taken_between_proposal_and_confirmation_is_rejected(
    _voice: None, world: World
) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    # Another caller books the same time first (through the real API).
    start = datetime.fromisoformat(rig.box.slots[slot]["start_at"].replace("Z", "+00:00"))
    taken = await world.book(world.p("Jordan"), "Annual physical", start)
    assert taken.status_code == 201
    await rig.say("yes")
    r = await rig.box.call("confirm_operation", {"caller_words": "yes"})
    assert r.status == "rejected" and r.code == "slot_unavailable"
    assert rig.tracker.operation == Operation.REJECTED
    assert await rig.count("Avery") == 0
    assert rig.box.committed == []


# ------------------------------------------------------------------ reschedule / cancel -------
async def test_reschedule_and_cancel(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    await rig.say("yes")
    assert (await rig.box.call("confirm_operation", {"caller_words": "yes"})).status == "committed"

    listing = await rig.box.call("get_patient_appointments", {})
    ref = listing.data["appointments"][0]["appointment_ref"]
    r = await rig.box.call(
        "get_appointment_availability",
        {"appointment_type": "Annual physical", "date_from": "2026-03-05", "max_results": 2},
    )
    new_slot = r.data["slots"][0]["slot_ref"]
    await rig.box.call("propose_reschedule", {"appointment_ref": ref, "slot_ref": new_slot})
    await rig.say("yes move it")
    moved = await rig.box.call("confirm_operation", {"caller_words": "yes move it"})
    assert moved.status == "committed", moved
    assert rig.box.outcome() == "appointment_rescheduled"
    assert await rig.count("Avery") == 1

    ref = (await rig.box.call("get_patient_appointments", {})).data["appointments"][0][
        "appointment_ref"
    ]
    await rig.box.call(
        "propose_cancellation", {"appointment_ref": ref, "reason": "no longer needed"}
    )
    await rig.say("yes cancel it")
    gone = await rig.box.call("confirm_operation", {"caller_words": "yes cancel it"})
    assert gone.status == "committed"
    assert rig.box.outcome() == "appointment_cancelled"
    assert await rig.count("Avery") == 0


async def test_policy_rejection_is_reported_not_hidden(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    # Same-day slot inside the clinic's minimum-notice window is never offered; ask far ahead.
    r = await rig.box.call(
        "get_appointment_availability",
        {"appointment_type": "Annual physical", "date_from": "2027-12-01"},
    )
    assert r.status == "ok" and r.data["slots"] == []


# ------------------------------------------------------------------ unknown outcomes ----------
async def test_lost_response_is_reconciled_without_double_booking(
    _voice: None, world: World
) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    key = rig.box.pending.key  # type: ignore[union-attr]
    await rig.say("yes")
    rig.transport.drop_response = 1  # the booking commits, the answer never arrives
    r = await rig.box.call("confirm_operation", {"caller_words": "yes"})
    assert r.status == "committed", r
    assert await rig.count("Avery") == 1
    posts = [
        c for c in rig.transport.calls if c == f"POST /api/clinics/{rig.ctx.clinic_id}/appointments"
    ]
    assert len(posts) == 1  # reconciliation found the record; no second booking attempt
    assert key.startswith("voice-")


async def test_request_never_delivered_retries_with_same_key(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    await rig.say("yes")
    rig.transport.drop_request = 1
    r = await rig.box.call("confirm_operation", {"caller_words": "yes"})
    assert r.status == "committed", r
    assert await rig.count("Avery") == 1


async def test_backend_down_is_reported_as_uncertain_then_resolved(
    _voice: None, world: World
) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    await rig.verify()
    await rig.box.call("propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot})
    await rig.say("yes")
    rig.transport.down = True
    r = await rig.box.call("confirm_operation", {"caller_words": "yes"})
    assert r.status == "uncertain" and r.code == "outcome_unknown"
    assert rig.tracker.operation == Operation.UNKNOWN
    assert rig.box.outcome() != "appointment_booked"  # never claimed
    assert await rig.count("Avery") == 0

    rig.transport.down = False
    later = await rig.box.call("get_operation_status", {})
    assert later.status == "committed", later
    assert await rig.count("Avery") == 1
    assert rig.tracker.operation == Operation.COMMITTED  # type: ignore[comparison-overlap]  # tool calls mutate the tracker; mypy cannot see it


# ------------------------------------------------------------------ verification --------------
async def test_unverified_caller_cannot_propose(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    slot = await rig.first_slot()
    r = await rig.box.call(
        "propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot}
    )
    assert r.status == "needs_input" and r.code == "verification_required"
    assert rig.tracker.conversation == Conversation.WAITING_VERIFICATION


async def test_wrong_details_and_lockout(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    p = world.p("Avery")
    bad = {"patient_name": p.name, "date_of_birth": "1970-01-01", "phone_last4": p.last4}
    codes = [(await rig.box.call("verify_patient", bad)).code for _ in range(6)]
    assert codes[:2] == ["verification_failed"] * 2
    assert "verification_locked" in codes
    assert not rig.box.verified
    good = await rig.verify()
    assert good["status"] == "rejected"  # still locked: correct details do not bypass lockout


async def test_invalid_arguments_are_reported_not_raised(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    r = await rig.box.call(
        "verify_patient", {"patient_name": "A", "date_of_birth": "not-a-date", "phone_last4": "12"}
    )
    assert r.status == "needs_input" and r.code == "invalid_arguments"
    r = await rig.box.call(
        "get_appointment_availability",
        {"appointment_type": "Annual physical", "date_from": DAY, "bogus": 1},
    )
    assert r.code == "invalid_arguments"
    assert (await rig.box.call("no_such_tool", {})).code == "unknown_tool"


# ------------------------------------------------------------------ clinics / capabilities ----
async def test_same_runtime_two_clinics_and_isolation(_voice: None, world: World) -> None:
    north = await make_rig(world, "Northstar Family Medicine")
    lake = await make_rig(world, "Lakeside Dermatology")
    assert (
        north.ctx.config.agent.agent_name == "Nora" and lake.ctx.config.agent.agent_name == "Skye"
    )

    assert (await north.box.call("get_clinic_information", {"topic": "hours"})).status == "ok"
    denied = await lake.box.call("get_clinic_information", {"topic": "hours"})
    assert denied.code == "capability_not_enabled"  # Lakeside's published intents omit it

    # Lakeside's agent cannot see Northstar's appointment types, and its patients are its own.
    r = await lake.box.call(
        "get_appointment_availability", {"appointment_type": "Annual physical", "date_from": DAY}
    )
    assert r.code == "appointment_type_unknown"
    north_patient = world.p("Avery")
    r = await lake.box.call(
        "verify_patient",
        {
            "patient_name": north_patient.name,
            "date_of_birth": north_patient.dob.isoformat(),
            "phone_last4": north_patient.last4,
        },
    )
    assert r.status == "rejected" and not lake.box.verified


async def test_procedure_types_require_escalation(_voice: None, world: World) -> None:
    rig = await make_rig(world, "Lakeside Dermatology")
    r = await rig.box.call(
        "get_appointment_availability",
        {"appointment_type": "Mohs surgery consultation", "date_from": DAY},
    )
    assert r.code == "human_escalation_required"
    esc = await rig.box.call(
        "request_human_escalation", {"reason": "Caller wants Mohs consultation"}
    )
    assert esc.ok and esc.data["transfer_performed"] is False
    assert rig.tracker.conversation == Conversation.ESCALATED
    assert rig.box.outcome() == "escalated"
    assert "Mohs" in esc.data["instructions"]


async def test_capability_gate_is_config_driven(_voice: None, world: World) -> None:
    rig = await make_rig(world)
    trimmed_agent = rig.ctx.config.agent.model_copy(
        update={"allowed_capabilities": ["check_availability"], "supported_intents": []}
    )
    ctx = rig.ctx.model_copy(
        update={"config": rig.ctx.config.model_copy(update={"agent": trimmed_agent})}
    )
    rig.box.ctx = ctx
    slot = await rig.first_slot()
    await rig.verify()
    r = await rig.box.call(
        "propose_booking", {"appointment_type": "Annual physical", "slot_ref": slot}
    )
    assert r.code == "capability_not_enabled"
    assert (await rig.box.call("get_clinic_information", {})).code == "capability_not_enabled"
