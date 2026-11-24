"""Scheduling API against real PostgreSQL: availability, booking, reschedule, cancel, proposals,
authorization, tenant isolation and configuration semantics."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text

from app.db.session import get_sessionmaker
from tests.world import FakeClock, World, iso, utc

TUE_9 = utc(2026, 3, 3, 15, 0)  # Tue 09:00 Chicago (CST)
TUE_9_30 = utc(2026, 3, 3, 15, 30)
WED_9 = utc(2026, 3, 4, 15, 0)


def code(r: Any) -> str:
    return str(r.json()["error"]["code"])


# ---- availability -------------------------------------------------------------------------------
async def test_availability_lists_slots_in_clinic_hours(world: World) -> None:
    n = world.north
    r = await world.client.get(
        world.url(n, "/availability"),
        params={
            "appointment_type_id": str(n.types["Annual physical"]),
            "date_from": "2026-03-03",
            "date_to": "2026-03-03",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    starts = [s["start_at"] for s in body["slots"]]
    assert starts[0] == "2026-03-03T15:00:00Z"
    assert starts[-1] == "2026-03-03T22:30:00Z"  # 16:30 CST, ends at 17:00 close
    assert body["timezone"] == "America/Chicago"


async def test_availability_excludes_booked_and_closed_days(world: World) -> None:
    a = world.p("Avery")
    assert (await world.book(a, "Annual physical", TUE_9)).status_code == 201
    r = await world.client.get(
        world.url(world.north, "/availability"),
        params={
            "appointment_type_id": str(world.north.types["Annual physical"]),
            "date_from": "2026-03-03",
        },
    )
    starts = [s["start_at"] for s in r.json()["slots"]]
    assert "2026-03-03T15:00:00Z" not in starts and "2026-03-03T15:15:00Z" not in starts
    assert "2026-03-03T15:30:00Z" in starts  # back-to-back allowed
    sat = await world.client.get(
        world.url(world.north, "/availability"),
        params={
            "appointment_type_id": str(world.north.types["Annual physical"]),
            "date_from": "2026-03-07",
        },
    )
    assert sat.json()["slots"] == []


async def test_availability_is_bounded_and_validated(world: World) -> None:
    n = world.north
    tid = str(n.types["Annual physical"])
    r = await world.client.get(
        world.url(n, "/availability"),
        params={"appointment_type_id": tid, "date_from": "2026-03-03", "date_to": "2026-06-30"},
    )
    assert r.status_code == 422 and code(r) == "invalid_input"
    r = await world.client.get(
        world.url(n, "/availability"),
        params={"appointment_type_id": tid, "date_from": "2026-03-03", "limit": 5},
    )
    assert len(r.json()["slots"]) == 5 and r.json()["truncated"] is True
    r = await world.client.get(
        world.url(n, "/availability"),
        params={"appointment_type_id": str(uuid.uuid4()), "date_from": "2026-03-03"},
    )
    assert r.status_code == 404


async def test_escalation_type_has_no_slots_and_cannot_be_booked(world: World) -> None:
    lake = world.lake
    mohs = str(lake.types["Mohs surgery consultation"])
    r = await world.client.get(
        world.url(lake, "/availability"),
        params={"appointment_type_id": mohs, "date_from": "2026-03-04"},
    )
    assert r.json()["slots"] == [] and r.json()["requires_human_escalation"] is True
    r = await world.book(world.p("Casey"), "Mohs surgery consultation", utc(2026, 3, 4, 17, 0))
    assert (
        r.status_code == 422 and r.json()["error"]["details"]["rule"] == "human_escalation_required"
    )


# ---- booking ------------------------------------------------------------------------------------
async def test_book_success_persists_utc_and_frozen_facts(world: World) -> None:
    a = world.p("Avery")
    r = await world.book(a, "Annual physical", TUE_9, key="book-success-1")
    assert r.status_code == 201, r.text
    appt = r.json()["appointment"]
    assert appt["start_at"] == "2026-03-03T15:00:00Z"
    assert appt["end_at"] == "2026-03-03T15:30:00Z"
    assert appt["status"] == "scheduled"
    assert appt["type_name"] == "Annual physical" and appt["duration_minutes"] == 30
    assert r.headers["idempotent-replay"] == "false"
    listed = await world.appointments(a)
    assert [x["id"] for x in listed] == [appt["id"]]


async def test_book_requires_authorization_and_idempotency_key(world: World) -> None:
    a = world.p("Avery")
    pr = await world.propose(
        a,
        {
            "action": "book",
            "appointment_type_id": str(world.north.types["Annual physical"]),
            "start_at": iso(TUE_9),
        },
    )
    body = {
        "proposal_id": pr.json()["id"],
        "appointment_type_id": str(world.north.types["Annual physical"]),
        "start_at": iso(TUE_9),
    }
    url = world.url(world.north, "/appointments")
    r = await world.client.post(url, json=body, headers={"Idempotency-Key": "no-auth-key-1"})
    assert r.status_code == 401 and code(r) == "authentication_required"
    r = await world.client.post(
        url, json=body, headers={"Authorization": "Bearer nonsense", "Idempotency-Key": "bad-tok-1"}
    )
    assert r.status_code == 401
    r = await world.client.post(url, json=body, headers=await world.headers(a))
    assert r.status_code == 422 and code(r) == "invalid_input"  # missing key


async def test_client_cannot_assert_verified_flag(world: World) -> None:
    a = world.p("Avery")
    r = await world.client.post(
        world.url(world.north, f"/patients/{a.id}/verify"),
        json={"date_of_birth": a.dob.isoformat(), "phone_last4": a.last4, "verified": True},
    )
    assert r.status_code == 422
    r = await world.client.post(
        world.url(world.north, "/proposals"),
        json={"action": "book", "verified": True, "start_at": iso(TUE_9)},
    )
    assert r.status_code in (401, 422)


async def test_book_rejects_bad_type_and_policy_violations(world: World) -> None:
    a = world.p("Avery")
    n = world.north
    pr = await world.propose(
        a,
        {"action": "book", "appointment_type_id": str(uuid.uuid4()), "start_at": iso(TUE_9)},
        confirm=False,
    )
    assert pr.status_code == 404
    for start, rule in [
        (utc(2026, 3, 2, 14, 0), "appointment_in_past"),
        (utc(2026, 3, 7, 16, 0), "closed_day"),
        (utc(2026, 3, 3, 13, 0), "outside_operating_hours"),
        (utc(2026, 3, 3, 22, 45), "outside_operating_hours"),
        (utc(2026, 3, 3, 15, 10), "invalid_slot_start"),
        (utc(2026, 3, 2, 18, 0), "minimum_notice"),
        (utc(2026, 7, 1, 15, 0), "max_advance"),
    ]:
        r = await world.book(a, "Annual physical", start)
        assert r.status_code == 422, (rule, r.text)
        assert r.json()["error"]["details"]["rule"] == rule
    assert await world.appointments(a) == []
    assert n.types


async def test_naive_datetimes_are_rejected(world: World) -> None:
    a = world.p("Avery")
    r = await world.client.post(
        world.url(world.north, "/proposals"),
        json={
            "action": "book",
            "appointment_type_id": str(world.north.types["Annual physical"]),
            "start_at": "2026-03-03T09:00:00",
        },
        headers=await world.headers(a),
    )
    assert r.status_code == 422 and code(r) == "invalid_input"


async def test_double_booking_same_slot_is_rejected(world: World) -> None:
    a, j = world.p("Avery"), world.p("Jordan")
    assert (await world.book(a, "Annual physical", TUE_9)).status_code == 201
    r = await world.book(j, "Sick visit", TUE_9)
    assert r.status_code == 409 and code(r) == "slot_unavailable"
    r = await world.book(j, "Sick visit", utc(2026, 3, 3, 15, 15))  # partial overlap
    assert r.status_code == 409 and code(r) == "slot_unavailable"
    assert (await world.book(j, "Sick visit", TUE_9_30)).status_code == 201  # back-to-back


async def test_different_clinics_can_book_the_same_instant(world: World) -> None:
    assert (
        await world.book(world.p("Avery"), "Annual physical", utc(2026, 3, 4, 17, 0))
    ).status_code == 201
    assert (
        await world.book(world.p("Casey"), "Skin check", utc(2026, 3, 4, 17, 0))
    ).status_code == 201


async def test_lakeside_rules_use_denver_time_and_policy(world: World) -> None:
    c = world.p("Casey")
    # Wed 2026-03-04 10:00 MST = 17:00Z -> valid
    assert (await world.book(c, "Skin check", utc(2026, 3, 4, 17, 0))).status_code == 201
    # 09:30 MST = 16:30Z -> before opening
    r = await world.book(c, "Skin check", utc(2026, 3, 4, 16, 30))
    assert r.json()["error"]["details"]["rule"] == "outside_operating_hours"
    # Monday is closed at Lakeside
    r = await world.book(c, "Skin check", utc(2026, 3, 9, 17, 0))
    assert r.json()["error"]["details"]["rule"] == "closed_day"
    # Same-day not allowed, and 24 h notice
    r = await world.book(c, "Skin check", utc(2026, 3, 2, 21, 0))
    assert r.status_code == 422


# ---- idempotency ----------------------------------------------------------------------------------
async def test_identical_retry_returns_same_outcome(world: World) -> None:
    a = world.p("Avery")
    n = world.north
    pr = await world.propose(
        a,
        {
            "action": "book",
            "appointment_type_id": str(n.types["Annual physical"]),
            "start_at": iso(TUE_9),
        },
    )
    body = {
        "proposal_id": pr.json()["id"],
        "appointment_type_id": str(n.types["Annual physical"]),
        "start_at": iso(TUE_9),
    }
    h = await world.headers(a, "retry-key-0001")
    first = await world.client.post(world.url(n, "/appointments"), json=body, headers=h)
    second = await world.client.post(world.url(n, "/appointments"), json=body, headers=h)
    assert first.status_code == 201 and second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["idempotent-replay"] == "true"
    assert second.headers["x-operation-id"] == first.headers["x-operation-id"]
    assert len(await world.appointments(a)) == 1


async def test_same_key_different_request_conflicts(world: World) -> None:
    a = world.p("Avery")
    assert (await world.book(a, "Annual physical", TUE_9, key="collide-key-01")).status_code == 201
    r = await world.book(a, "Annual physical", WED_9, key="collide-key-01")
    assert r.status_code == 409 and code(r) == "idempotency_conflict"
    assert len(await world.appointments(a)) == 1


async def test_failed_operation_replays_same_failure(world: World) -> None:
    a, j = world.p("Avery"), world.p("Jordan")
    n = world.north
    # Jordan proposes + confirms while the slot is still free...
    pr = (await _proposal(world, j, confirm=True)).json()
    # ...then Avery takes it before Jordan executes.
    assert (await world.book(a, "Annual physical", TUE_9)).status_code == 201
    body = {
        "proposal_id": pr["id"],
        "appointment_type_id": str(n.types["Annual physical"]),
        "start_at": iso(TUE_9),
    }
    h = await world.headers(j, "fail-replay-01")
    first = await world.client.post(world.url(n, "/appointments"), json=body, headers=h)
    assert first.status_code == 409 and code(first) == "slot_unavailable"
    again = await world.client.post(world.url(n, "/appointments"), json=body, headers=h)
    assert again.status_code == 409 and again.json() == first.json()
    assert again.headers["idempotent-replay"] == "true"
    op = await world.client.get(
        world.url(n, "/operations"), params={"idempotency_key": "fail-replay-01"}, headers=h
    )
    assert op.status_code == 200 and op.json()["status"] == "failed"
    assert op.json()["http_status"] == 409 and op.json()["resolved"] is True
    assert await world.appointments(j) == []


async def test_operation_lookup_by_id_and_key_and_scoping(world: World) -> None:
    a, j = world.p("Avery"), world.p("Jordan")
    r = await world.book(a, "Annual physical", TUE_9, key="lookup-key-01")
    op_id = r.headers["x-operation-id"]
    by_id = await world.client.get(
        world.url(world.north, f"/operations/{op_id}"), headers=await world.headers(a)
    )
    assert by_id.status_code == 200 and by_id.json()["status"] == "succeeded"
    assert by_id.json()["appointment_id"] == r.json()["appointment"]["id"]
    other = await world.client.get(
        world.url(world.north, f"/operations/{op_id}"), headers=await world.headers(j)
    )
    assert other.status_code == 403
    missing = await world.client.get(
        world.url(world.north, f"/operations/{uuid.uuid4()}"), headers=await world.headers(a)
    )
    assert missing.status_code == 404


# ---- reschedule -------------------------------------------------------------------------------------
async def test_reschedule_success_frees_old_slot(world: World) -> None:
    a, j = world.p("Avery"), world.p("Jordan")
    appt = (await world.book(a, "Annual physical", TUE_9)).json()["appointment"]
    r = await world.reschedule(a, appt["id"], WED_9)
    assert r.status_code == 200, r.text
    new = r.json()["appointment"]
    assert new["id"] == appt["id"] and new["start_at"] == iso(WED_9)
    assert new["reschedule_count"] == 1
    assert (await world.book(j, "Sick visit", TUE_9)).status_code == 201  # old slot is free


async def test_reschedule_conflict_leaves_original_intact(world: World) -> None:
    a, j = world.p("Avery"), world.p("Jordan")
    appt = (await world.book(a, "Annual physical", TUE_9)).json()["appointment"]
    await world.book(j, "Sick visit", WED_9)
    r = await world.reschedule(a, appt["id"], WED_9)
    assert r.status_code == 409 and code(r) == "slot_unavailable"
    mine = await world.appointments(a)
    assert mine[0]["start_at"] == iso(TUE_9) and mine[0]["reschedule_count"] == 0


async def test_reschedule_policy_limits(world: World) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    # max_reschedules = 2
    for i, d in enumerate((10, 11)):
        r = await world.reschedule(a, appt["id"], utc(2026, 3, d, 15, 0))
        assert r.status_code == 200, (i, r.text)
    r = await world.reschedule(a, appt["id"], utc(2026, 3, 12, 15, 0))
    assert r.status_code == 422 and r.json()["error"]["details"]["rule"] == "max_reschedules"
    # window: within 12h of the appointment
    clock_appt = (await world.book(a, "Sick visit", utc(2026, 3, 16, 15, 0))).json()["appointment"]
    world.clock.now = utc(2026, 3, 16, 10, 0)
    await world.token(a, fresh=True)
    r = await world.reschedule(a, clock_appt["id"], utc(2026, 3, 17, 15, 0))
    assert r.status_code == 422 and r.json()["error"]["details"]["rule"] == "reschedule_window"


async def test_reschedule_auth_and_isolation(world: World) -> None:
    a, j, c = world.p("Avery"), world.p("Jordan"), world.p("Casey")
    appt = (await world.book(a, "Annual physical", TUE_9)).json()["appointment"]
    r = await world.reschedule(j, appt["id"], WED_9)  # another patient, same clinic
    assert r.status_code in (403, 404)
    r = await world.client.post(
        world.url(world.north, "/proposals"),
        json={"action": "reschedule", "appointment_id": appt["id"], "start_at": iso(WED_9)},
        headers=await world.headers(c),  # token from another clinic
    )
    assert r.status_code == 403 and code(r) == "forbidden"
    assert (await world.appointments(a))[0]["start_at"] == iso(TUE_9)


# ---- cancellation -------------------------------------------------------------------------------------
async def test_cancel_is_soft_and_frees_slot(world: World) -> None:
    a, j = world.p("Avery"), world.p("Jordan")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    r = await world.cancel(a, appt["id"], reason="Feeling better")
    assert r.status_code == 200, r.text
    got = r.json()["appointment"]
    assert got["status"] == "cancelled" and got["cancellation_reason"] == "Feeling better"
    assert got["cancelled_at"] is not None
    assert await world.appointments(a) == []
    assert len(await world.appointments(a, include_cancelled=True)) == 1
    assert (await world.book(j, "Sick visit", utc(2026, 3, 9, 15, 0))).status_code == 201


async def test_repeated_cancel_is_a_clear_conflict_and_retry_is_idempotent(world: World) -> None:
    a = world.p("Avery")
    n = world.north
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    pr = await world.propose(a, {"action": "cancel", "appointment_id": appt["id"]})
    url = world.url(n, f"/appointments/{appt['id']}/cancel")
    body = {"proposal_id": pr.json()["id"]}
    h = await world.headers(a, "cancel-key-001")
    first = await world.client.post(url, json=body, headers=h)
    retry = await world.client.post(url, json=body, headers=h)  # lost response -> retry
    assert first.status_code == 200 and retry.status_code == 200
    assert retry.json() == first.json() and retry.headers["idempotent-replay"] == "true"
    # A brand-new cancel request for an already-cancelled appointment is an explicit conflict.
    again = await world.cancel(a, appt["id"], key="cancel-key-002")
    assert again.status_code == 409 and code(again) == "invalid_state_transition"


async def test_cancel_policy_window_and_auth(world: World) -> None:
    a, j = world.p("Avery"), world.p("Jordan")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 3, 15, 0))).json()["appointment"]
    world.clock.advance(minutes=10)  # now < 24h before the appointment
    r = await world.cancel(a, appt["id"])
    assert r.status_code == 422 and r.json()["error"]["details"]["rule"] == "cancellation_window"
    assert (await world.cancel(j, appt["id"])).status_code in (403, 404)
    assert (await world.appointments(a))[0]["status"] == "scheduled"


async def test_audit_history_records_each_change(world: World) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    await world.reschedule(a, appt["id"], utc(2026, 3, 10, 15, 0))
    await world.cancel(a, appt["id"])
    r = await world.client.get(
        world.url(world.north, f"/appointments/{appt['id']}/events"), headers=await world.headers(a)
    )
    assert [e["event_type"] for e in r.json()] == ["booked", "rescheduled", "cancelled"]
    assert all(e["config_version"] >= 1 for e in r.json())


# ---- proposals / confirmation ---------------------------------------------------------------------
async def _proposal(world: World, p: Any, start: datetime = TUE_9, confirm: bool = False) -> Any:
    return await world.propose(
        p,
        {
            "action": "book",
            "appointment_type_id": str(p.clinic.types["Annual physical"]),
            "start_at": iso(start),
        },
        confirm=confirm,
    )


async def test_execution_requires_a_confirmed_proposal(world: World) -> None:
    a = world.p("Avery")
    pr = (await _proposal(world, a)).json()
    body = {
        "proposal_id": pr["id"],
        "appointment_type_id": str(world.north.types["Annual physical"]),
        "start_at": iso(TUE_9),
    }
    r = await world.client.post(
        world.url(world.north, "/appointments"),
        json=body,
        headers=await world.headers(a, "unconfirmed-01"),
    )
    assert r.status_code == 409 and code(r) == "proposal_not_confirmed"
    assert await world.appointments(a) == []


async def test_wrong_confirmation_token_is_rejected(world: World) -> None:
    a = world.p("Avery")
    pr = (await _proposal(world, a)).json()
    r = await world.client.post(
        world.url(world.north, f"/proposals/{pr['id']}/confirm"),
        json={"confirmation_token": "x" * 40},
        headers=await world.headers(a),
    )
    assert r.status_code in (403, 409) and r.status_code != 200


async def test_modified_details_are_rejected(world: World) -> None:
    a = world.p("Avery")
    pr = (await _proposal(world, a, confirm=True)).json()
    r = await world.client.post(
        world.url(world.north, "/appointments"),
        json={
            "proposal_id": pr["id"],
            "appointment_type_id": str(world.north.types["Annual physical"]),
            "start_at": iso(TUE_9_30),
        },
        headers=await world.headers(a, "modified-key-1"),
    )
    assert r.status_code == 409 and code(r) == "proposal_mismatch"
    assert await world.appointments(a) == []


async def test_proposal_replay_is_prevented(world: World) -> None:
    a = world.p("Avery")
    pr = (await _proposal(world, a, confirm=True)).json()
    body = {
        "proposal_id": pr["id"],
        "appointment_type_id": str(world.north.types["Annual physical"]),
        "start_at": iso(TUE_9),
    }
    url = world.url(world.north, "/appointments")
    assert (
        await world.client.post(url, json=body, headers=await world.headers(a, "use-once-key1"))
    ).status_code == 201
    r = await world.client.post(url, json=body, headers=await world.headers(a, "use-once-key2"))
    assert r.status_code == 409 and code(r) == "proposal_already_used"
    assert len(await world.appointments(a)) == 1


async def test_expired_proposal_cannot_be_confirmed_or_used(world: World) -> None:
    a = world.p("Avery")
    pr = (await _proposal(world, a)).json()
    world.clock.advance(minutes=6)
    world.clock.now = world.clock.now  # authorization (15 min) still valid
    r = await world.client.post(
        world.url(world.north, f"/proposals/{pr['id']}/confirm"),
        json={"confirmation_token": pr["confirmation_token"]},
        headers=await world.headers(a),
    )
    assert r.status_code == 410 and code(r) == "operation_expired"


async def test_rejected_proposal_cannot_be_used(world: World) -> None:
    a = world.p("Avery")
    pr = (await _proposal(world, a)).json()
    h = await world.headers(a)
    r = await world.client.post(world.url(world.north, f"/proposals/{pr['id']}/reject"), headers=h)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = await world.client.post(
        world.url(world.north, f"/proposals/{pr['id']}/confirm"),
        json={"confirmation_token": pr["confirmation_token"]},
        headers=h,
    )
    assert r.status_code == 409


async def test_proposal_cannot_be_used_by_another_patient_or_clinic(world: World) -> None:
    a, j, c = world.p("Avery"), world.p("Jordan"), world.p("Casey")
    pr = (await _proposal(world, a, confirm=True)).json()
    body = {
        "proposal_id": pr["id"],
        "appointment_type_id": str(world.north.types["Annual physical"]),
        "start_at": iso(TUE_9),
    }
    url = world.url(world.north, "/appointments")
    r = await world.client.post(url, json=body, headers=await world.headers(j, "steal-key-001"))
    assert r.status_code in (403, 404)
    r = await world.client.post(url, json=body, headers=await world.headers(c, "steal-key-002"))
    assert r.status_code == 403
    r = await world.client.get(
        world.url(world.north, f"/proposals/{pr['id']}"), headers=await world.headers(j)
    )
    assert r.status_code in (403, 404)
    assert await world.appointments(a) == []


async def test_proposal_summary_is_returned_and_confirmation_token_only_once(world: World) -> None:
    a = world.p("Avery")
    pr = (await _proposal(world, a)).json()
    assert pr["confirmation_token"] and pr["status"] == "pending"
    assert pr["details"]["start_at"] == iso(TUE_9) and pr["summary"]
    got = await world.client.get(
        world.url(world.north, f"/proposals/{pr['id']}"), headers=await world.headers(a)
    )
    assert got.json().get("confirmation_token") in (None, "")


async def test_appointment_changed_after_proposal_is_detected(world: World) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    pr = await world.propose(a, {"action": "cancel", "appointment_id": appt["id"]})
    pid = pr.json()["id"]
    # Another change lands in between (reschedule) -> row version differs.
    assert (await world.reschedule(a, appt["id"], utc(2026, 3, 10, 15, 0))).status_code == 200
    r = await world.client.post(
        world.url(world.north, f"/appointments/{appt['id']}/cancel"),
        json={"proposal_id": pid},
        headers=await world.headers(a, "stale-cancel-1"),
    )
    assert r.status_code == 409 and code(r) == "appointment_modified"
    assert (await world.appointments(a))[0]["status"] == "scheduled"


# ---- verification / authorization ---------------------------------------------------------------------
async def test_verification_failure_lockout_and_expiry(world: World) -> None:
    a = world.p("Avery")
    url = world.url(world.north, f"/patients/{a.id}/verify")
    bad = {"date_of_birth": a.dob.isoformat(), "phone_last4": "0000"}
    for _ in range(4):
        r = await world.client.post(url, json=bad)
        assert r.status_code == 403 and code(r) == "verification_failed"
    r = await world.client.post(url, json=bad)
    assert r.status_code in (403, 429)
    r = await world.client.post(
        url, json={"date_of_birth": a.dob.isoformat(), "phone_last4": a.last4}
    )
    assert r.status_code == 429 and code(r) == "verification_locked"
    world.clock.advance(minutes=11)
    r = await world.client.post(
        url, json={"date_of_birth": a.dob.isoformat(), "phone_last4": a.last4}
    )
    assert r.status_code == 200


async def test_authorization_expires(world: World) -> None:
    a = world.p("Avery")
    await world.token(a)
    world.clock.advance(minutes=16)
    r = await world.client.get(
        world.url(world.north, f"/patients/{a.id}/appointments"), headers=await world.headers(a)
    )
    assert r.status_code == 401 and code(r) == "authorization_expired"


async def test_token_is_bound_to_patient_and_clinic(world: World) -> None:
    a, j, c = world.p("Avery"), world.p("Jordan"), world.p("Casey")
    r = await world.client.get(
        world.url(world.north, f"/patients/{j.id}/appointments"), headers=await world.headers(a)
    )
    assert r.status_code == 403
    r = await world.client.get(
        world.url(world.north, f"/patients/{a.id}/appointments"), headers=await world.headers(c)
    )
    assert r.status_code == 403
    r = await world.client.post(
        world.url(world.lake, f"/patients/{a.id}/verify"),
        json={"date_of_birth": a.dob.isoformat(), "phone_last4": a.last4},
    )
    assert r.status_code in (403, 404)  # a Northstar patient does not exist at Lakeside


async def test_patient_lookup_exposes_only_id_and_name(world: World) -> None:
    r = await world.client.get(world.url(world.north, "/patients"), params={"name": "avery"})
    assert r.status_code == 200
    assert set(r.json()[0]) == {"id", "full_name"}
    r = await world.client.get(world.url(world.north, "/patients"), params={"name": "casey"})
    assert r.json() == []  # tenant isolation: Lakeside patient invisible at Northstar


async def test_errors_do_not_leak_internals(world: World) -> None:
    a = world.p("Avery")
    r = await world.client.get(
        world.url(world.north, f"/patients/{a.id}/appointments"),
        headers={"Authorization": "Bearer x"},
    )
    text_ = r.text.lower()
    for leak in ("traceback", "sqlalchemy", "asyncpg", "psycopg", "select "):
        assert leak not in text_


# ---- configuration semantics ----------------------------------------------------------------------------
async def _config(client: AsyncClient, clinic_id: uuid.UUID) -> dict[str, Any]:
    r = await client.get(f"/api/clinics/{clinic_id}/config")
    assert r.status_code == 200, r.text
    return dict(r.json()["config"]) if "config" in r.json() else dict(r.json())


async def test_unpublished_draft_edits_do_not_affect_scheduling(world: World) -> None:
    n = world.north
    cfg = await _config(world.client, n.id)
    cfg["hours"] = [h for h in cfg["hours"] if h["weekday"] != 1]  # drop Tuesday in the draft
    put = await world.client.put(f"/api/clinics/{n.id}/config", json=cfg)
    assert put.status_code == 200, put.text
    r = await world.book(world.p("Avery"), "Annual physical", TUE_9)
    assert r.status_code == 201  # live rules unchanged until published


async def test_type_ids_are_stable_across_edits_and_history_is_frozen(world: World) -> None:
    n = world.north
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", TUE_9)).json()["appointment"]
    cfg = await _config(world.client, n.id)
    for t in cfg["appointment_types"]:
        if t["name"] == "Annual physical":
            assert t["id"] == str(n.types["Annual physical"])
            t["name"] = "Yearly physical"
            t["duration_minutes"] = 60
    put = await world.client.put(f"/api/clinics/{n.id}/config", json=cfg)
    assert put.status_code == 200, put.text
    pub = await world.client.post(f"/api/clinics/{n.id}/config/publish")
    assert pub.status_code in (200, 201), pub.text
    info = (await world.client.get(world.url(n, "/scheduling"))).json()
    ids = {t["name"]: t["id"] for t in info["appointment_types"]}
    assert ids["Yearly physical"] == str(n.types["Annual physical"])  # same identity
    n.types["Yearly physical"] = uuid.UUID(ids["Yearly physical"])
    mine = (await world.appointments(a))[0]
    assert mine["id"] == appt["id"]
    assert mine["type_name"] == "Annual physical" and mine["duration_minutes"] == 30
    assert mine["end_at"] == appt["end_at"]
    # New bookings use the new duration.
    r = await world.book(world.p("Jordan"), "Yearly physical", WED_9)
    assert r.status_code == 201 and r.json()["appointment"]["duration_minutes"] == 60


async def test_removed_type_is_archived_and_unbookable_but_history_survives(world: World) -> None:
    n = world.north
    a = world.p("Avery")
    appt = (await world.book(a, "Sick visit", TUE_9)).json()["appointment"]
    cfg = await _config(world.client, n.id)
    cfg["appointment_types"] = [t for t in cfg["appointment_types"] if t["name"] != "Sick visit"]
    assert (await world.client.put(f"/api/clinics/{n.id}/config", json=cfg)).status_code == 200
    assert (await world.client.post(f"/api/clinics/{n.id}/config/publish")).status_code in (
        200,
        201,
    )
    r = await world.book(world.p("Jordan"), "Sick visit", WED_9)
    assert r.status_code == 404
    assert (await world.appointments(a))[0]["id"] == appt["id"]
    async with get_sessionmaker()() as s:
        n_rows = await s.scalar(
            text(
                "select count(*) from appointment_types where id = :i and archived_at is not null"
            ),
            {"i": n.types["Sick visit"]},
        )
    assert n_rows == 1


async def test_published_policy_change_applies_to_new_bookings(world: World) -> None:
    n = world.north
    cfg = await _config(world.client, n.id)
    cfg["hours"] = [{**h, "closes": "12:00"} for h in cfg["hours"]]
    assert (await world.client.put(f"/api/clinics/{n.id}/config", json=cfg)).status_code == 200
    assert (await world.client.post(f"/api/clinics/{n.id}/config/publish")).status_code in (
        200,
        201,
    )
    r = await world.book(world.p("Avery"), "Annual physical", utc(2026, 3, 3, 19, 0))  # 13:00 CST
    assert (
        r.status_code == 422 and r.json()["error"]["details"]["rule"] == "outside_operating_hours"
    )
    assert (await world.book(world.p("Avery"), "Annual physical", TUE_9)).status_code == 201


async def test_unpublished_clinic_is_not_schedulable(client: AsyncClient) -> None:
    from app.seed import seed

    async with get_sessionmaker()() as session:
        await seed(session)
        await session.commit()
    clinics = (await client.get("/api/clinics")).json()
    r = await client.get(f"/api/clinics/{clinics[0]['id']}/scheduling")
    assert r.status_code == 409 and code(r) == "clinic_not_configured"


async def test_unknown_clinic_is_404(world: World, clock: FakeClock) -> None:
    r = await world.client.get(f"/api/clinics/{uuid.uuid4()}/scheduling")
    assert r.status_code == 404
    assert clock.now == datetime(2026, 3, 2, 15, 0, tzinfo=UTC) + timedelta(0)
