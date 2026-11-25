"""Concurrency, failure injection and database-level guarantees (real PostgreSQL)."""

import asyncio
import uuid
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.session import get_sessionmaker
from tests.world import ScriptedFaults, World, iso, utc

TUE_9 = utc(2026, 3, 3, 15, 0)


def err(r: Any) -> str:
    return str(r.json()["error"]["code"])


async def _confirmed_book(
    world: World, patient: Any, start: Any = TUE_9
) -> tuple[dict[str, Any], str]:
    n = patient.clinic
    tid = str(n.types["Annual physical"])
    pr = await world.propose(
        patient, {"action": "book", "appointment_type_id": tid, "start_at": iso(start)}
    )
    return {"proposal_id": pr.json()["id"], "appointment_type_id": tid, "start_at": iso(start)}, tid


async def _count(sql: str, **params: Any) -> int:
    async with get_sessionmaker()() as s:
        return int(await s.scalar(text(sql), params) or 0)


# ---- concurrency ---------------------------------------------------------------------------------
async def test_concurrent_bookings_for_one_slot_yield_exactly_one(world: World) -> None:
    people = [world.p("Avery"), world.p("Jordan"), world.p("Morgan")]
    for p in people:
        await world.token(p)
    results = await asyncio.gather(*(world.book(p, "Annual physical", TUE_9) for p in people))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409], [r.text for r in results]
    assert all(err(r) == "slot_unavailable" for r in results if r.status_code == 409)
    assert await _count("select count(*) from appointments where status='scheduled'") == 1


async def test_many_concurrent_bookings_never_overlap(world: World) -> None:
    people = [world.p("Avery"), world.p("Jordan"), world.p("Morgan")]
    for p in people:
        await world.token(p)
    starts = [utc(2026, 3, 3, 15, 0), utc(2026, 3, 3, 15, 15), utc(2026, 3, 3, 15, 30)]
    jobs = [world.book(people[i % 3], "Annual physical", starts[i % 3]) for i in range(9)]
    results = await asyncio.gather(*jobs)
    assert all(r.status_code in (201, 409) for r in results), [
        (r.status_code, r.text[:200]) for r in results
    ]
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(
                text(
                    "select start_at, end_at from appointments where status='scheduled' order by start_at"
                )
            )
        ).all()
    for (_, end), (start, _) in zip(rows, rows[1:], strict=False):
        assert end <= start
    assert len(rows) >= 1


async def test_concurrent_identical_retries_create_one_appointment(world: World) -> None:
    a = world.p("Avery")
    body, _ = await _confirmed_book(world, a)
    h = await world.headers(a, "concurrent-key-01")
    url = world.url(a.clinic, "/appointments")
    results = await asyncio.gather(
        *(world.client.post(url, json=body, headers=h) for _ in range(6))
    )
    ok = [r for r in results if r.status_code == 201]
    assert len(ok) >= 1
    assert {r.json()["appointment"]["id"] for r in ok} == {ok[0].json()["appointment"]["id"]}
    for r in results:
        assert r.status_code == 201 or err(r) == "operation_in_progress"
    assert await _count("select count(*) from appointments") == 1
    assert await _count("select count(*) from operations") == 1


async def test_concurrent_reschedules_of_one_appointment_apply_once(world: World) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    d1, d2 = utc(2026, 3, 10, 15, 0), utc(2026, 3, 11, 15, 0)
    results = await asyncio.gather(
        world.reschedule(a, appt["id"], d1), world.reschedule(a, appt["id"], d2)
    )
    # Both proposals captured the same row version; exactly one may win.
    assert sorted(r.status_code for r in results) == [200, 409]
    assert err(next(r for r in results if r.status_code == 409)) == "appointment_modified"
    assert (await world.appointments(a))[0]["reschedule_count"] == 1


async def test_cancel_racing_with_reschedule_is_consistent(world: World) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    results = await asyncio.gather(
        world.cancel(a, appt["id"]), world.reschedule(a, appt["id"], utc(2026, 3, 10, 15, 0))
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    row = (await world.appointments(a, include_cancelled=True))[0]
    assert row["status"] in ("cancelled", "scheduled")
    assert (row["status"] == "cancelled") == (row["reschedule_count"] == 0)


# ---- failure injection ---------------------------------------------------------------------------
async def test_failure_before_commit_rolls_back_and_retry_succeeds(
    world: World, faults: ScriptedFaults
) -> None:
    a = world.p("Avery")
    body, _ = await _confirmed_book(world, a)
    h = await world.headers(a, "rollback-key-01")
    url = world.url(a.clinic, "/appointments")
    faults.fail_at("before_commit", ConnectionError("db went away"))
    r = await world.client.post(url, json=body, headers=h)
    assert r.status_code == 503 and err(r) == "dependency_unavailable"
    assert "db went away" not in r.text
    assert await _count("select count(*) from appointments") == 0
    # The proposal was not consumed by the failed attempt: the same request can be retried.
    r2 = await world.client.post(url, json=body, headers=h)
    assert r2.status_code == 201, r2.text
    assert await _count("select count(*) from appointments") == 1
    assert await _count("select count(*) from operations") == 1


async def test_failure_inside_work_never_reports_success(
    world: World, faults: ScriptedFaults
) -> None:
    a = world.p("Avery")
    body, _ = await _confirmed_book(world, a)
    h = await world.headers(a, "inwork-key-0001")
    faults.fail_at("in_work", TimeoutError("slow"))
    r = await world.client.post(world.url(a.clinic, "/appointments"), json=body, headers=h)
    assert r.status_code == 503
    assert await world.appointments(a) == []
    op = await world.client.get(
        world.url(a.clinic, "/operations"), params={"idempotency_key": "inwork-key-0001"}, headers=h
    )
    assert op.json()["status"] == "aborted" and op.json()["resolved"] is False


async def test_lost_response_after_commit_is_reconcilable(
    world: World, faults: ScriptedFaults
) -> None:
    a = world.p("Avery")
    body, _ = await _confirmed_book(world, a)
    h = await world.headers(a, "lost-resp-key-01")
    url = world.url(a.clinic, "/appointments")
    faults.fail_at("after_commit", ConnectionError("response lost"))
    r = await world.client.post(url, json=body, headers=h)
    # Either the caller is told the truth (committed) or told the outcome is unknown; never failure.
    assert r.status_code in (201, 503)
    if r.status_code == 503:
        assert err(r) in ("outcome_unknown", "dependency_unavailable")
    # Reconcile by idempotency key without re-executing.
    op = await world.client.get(
        world.url(a.clinic, "/operations"),
        params={"idempotency_key": "lost-resp-key-01"},
        headers=h,
    )
    assert op.status_code == 200 and op.json()["status"] == "succeeded"
    appt_id = op.json()["appointment_id"]
    assert op.json()["outcome"]["appointment"]["id"] == appt_id
    # Retrying replays the stored outcome; no second appointment.
    r2 = await world.client.post(url, json=body, headers=h)
    assert r2.status_code == 201 and r2.headers["idempotent-replay"] == "true"
    assert r2.json()["appointment"]["id"] == appt_id
    assert await _count("select count(*) from appointments") == 1


async def test_reschedule_failure_leaves_original_intact(
    world: World, faults: ScriptedFaults
) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    faults.fail_at("before_commit", ConnectionError("boom"))
    r = await world.reschedule(a, appt["id"], utc(2026, 3, 10, 15, 0), key="resched-fail-01")
    assert r.status_code == 503
    row = (await world.appointments(a))[0]
    assert row["start_at"] == iso(utc(2026, 3, 9, 15, 0)) and row["reschedule_count"] == 0
    assert (
        await _count(
            "select count(*) from appointment_events where appointment_id=:i", i=appt["id"]
        )
        == 1
    )


async def test_cancel_failure_then_retry(world: World, faults: ScriptedFaults) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", utc(2026, 3, 9, 15, 0))).json()["appointment"]
    pr = await world.propose(a, {"action": "cancel", "appointment_id": appt["id"]})
    url = world.url(a.clinic, f"/appointments/{appt['id']}/cancel")
    h = await world.headers(a, "cancel-retry-0001")
    faults.fail_at("before_commit", ConnectionError("boom"))
    r = await world.client.post(url, json={"proposal_id": pr.json()["id"]}, headers=h)
    assert r.status_code == 503
    assert (await world.appointments(a))[0]["status"] == "scheduled"
    r2 = await world.client.post(url, json={"proposal_id": pr.json()["id"]}, headers=h)
    assert r2.status_code == 200 and r2.json()["appointment"]["status"] == "cancelled"


async def test_unhandled_database_error_is_generic(world: World, faults: ScriptedFaults) -> None:
    a = world.p("Avery")
    body, _ = await _confirmed_book(world, a)
    faults.fail_at("in_work", DBAPIError("SELECT secret FROM t", {}, Exception("password=hunter2")))
    r = await world.client.post(
        world.url(a.clinic, "/appointments"),
        json=body,
        headers=await world.headers(a, "dberr-key-0001"),
    )
    assert r.status_code == 503
    for leak in ("hunter2", "SELECT", "secret"):
        assert leak not in r.text


# ---- database-level guarantees --------------------------------------------------------------------
async def _insert_appt(s: Any, world: World, p: Any, start: str, end: str) -> None:
    await s.execute(
        text(
            """insert into appointments (id, clinic_id, patient_id, appointment_type_id, type_name,
               duration_minutes, timezone, start_at, end_at, status, config_version)
               values (:id, :c, :p, :t, 'x', 30, 'America/Chicago', :s, :e, 'scheduled', 1)"""
        ),
        {
            "id": uuid.uuid4(),
            "c": p.clinic.id,
            "p": p.id,
            "t": p.clinic.types["Annual physical"],
            "s": datetime.fromisoformat(start.replace("Z", "+00:00")),
            "e": datetime.fromisoformat(end.replace("Z", "+00:00")),
        },
    )


async def test_exclusion_constraint_rejects_overlap_but_allows_adjacent_and_cancelled(
    world: World,
) -> None:
    a = world.p("Avery")
    async with get_sessionmaker()() as s:
        await _insert_appt(s, world, a, "2026-04-01T15:00Z", "2026-04-01T15:30Z")
        await _insert_appt(s, world, a, "2026-04-01T15:30Z", "2026-04-01T16:00Z")  # adjacent ok
        await s.commit()
    async with get_sessionmaker()() as s:
        with pytest.raises(IntegrityError):
            await _insert_appt(s, world, a, "2026-04-01T15:15Z", "2026-04-01T15:45Z")
        await s.rollback()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "update appointments set status='cancelled', cancelled_at=now() where start_at='2026-04-01T15:00:00+00'"
            )
        )
        await _insert_appt(s, world, a, "2026-04-01T15:00Z", "2026-04-01T15:30Z")
        await s.commit()


async def test_cross_clinic_references_are_impossible(world: World) -> None:
    c = world.p("Casey")  # Lakeside patient
    async with get_sessionmaker()() as s:
        with pytest.raises(IntegrityError):
            await s.execute(
                text(
                    """insert into appointments (id, clinic_id, patient_id, appointment_type_id,
                       type_name, duration_minutes, timezone, start_at, end_at, status, config_version)
                       values (:id, :c, :p, :t, 'x', 30, 'America/Chicago', now(), now() + interval '30 min',
                       'scheduled', 1)"""
                ),
                {
                    "id": uuid.uuid4(),
                    "c": world.north.id,  # appointment in Northstar...
                    "p": c.id,  # ...for a Lakeside patient
                    "t": world.north.types["Annual physical"],
                },
            )
        await s.rollback()
    async with get_sessionmaker()() as s:
        with pytest.raises(IntegrityError):
            await s.execute(
                text(
                    """insert into appointments (id, clinic_id, patient_id, appointment_type_id,
                       type_name, duration_minutes, timezone, start_at, end_at, status, config_version)
                       values (:id, :c, :p, :t, 'x', 30, 'America/Chicago', now(), now() + interval '30 min',
                       'scheduled', 1)"""
                ),
                {
                    "id": uuid.uuid4(),
                    "c": world.north.id,
                    "p": world.p("Avery").id,
                    "t": world.lake.types["Skin check"],  # another clinic's appointment type
                },
            )
        await s.rollback()


async def test_check_constraints_and_append_only_events(world: World) -> None:
    a = world.p("Avery")
    appt = (await world.book(a, "Annual physical", TUE_9)).json()["appointment"]
    async with get_sessionmaker()() as s:
        with pytest.raises(DBAPIError):
            await s.execute(
                text("update appointments set end_at = start_at where id = :i"), {"i": appt["id"]}
            )
        await s.rollback()
        with pytest.raises(DBAPIError):
            await s.execute(
                text("update appointments set status = 'bogus' where id = :i"), {"i": appt["id"]}
            )
        await s.rollback()
        with pytest.raises(DBAPIError):
            await s.execute(text("update appointment_events set event_type = 'x'"))
        await s.rollback()
        with pytest.raises(DBAPIError):
            await s.execute(text("delete from appointment_events"))
        await s.rollback()


async def test_operation_key_unique_per_clinic_not_global(world: World) -> None:
    # Same idempotency key in two clinics are independent operations.
    r1 = await world.book(world.p("Avery"), "Annual physical", TUE_9, key="shared-key-0001")
    r2 = await world.book(
        world.p("Casey"), "Skin check", utc(2026, 3, 4, 17, 0), key="shared-key-0001"
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert (
        await _count("select count(*) from operations where idempotency_key='shared-key-0001'") == 2
    )


async def test_published_snapshots_stay_immutable(world: World) -> None:
    async with get_sessionmaker()() as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("update config_versions set snapshot = '{}'::jsonb"))
        await s.rollback()


async def test_heavy_contention_has_no_infrastructure_failures(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """VD-09: drive far more concurrent writers than the connection pool has connections, over
    overlapping slots, and require every answer to be a business outcome (201/409). Any 503 or
    logged infrastructure failure fails the test and carries its SQLSTATE, so an intermittent
    503 can be classified (deadlock 40P01, serialization 40001, lock timeout 55P03, connection
    08xxx, exclusion 23P01) instead of assumed."""
    caplog.set_level("WARNING", logger="caredeploy.scheduling")
    people = [world.p("Avery"), world.p("Jordan"), world.p("Morgan")]
    for p in people:
        await world.token(p)
    starts = [utc(2026, 3, 3, 15, 0), utc(2026, 3, 3, 15, 15), utc(2026, 3, 3, 15, 30)]
    jobs = [world.book(people[i % 3], "Annual physical", starts[i % 3]) for i in range(48)]
    results = await asyncio.gather(*jobs)
    bad = [(r.status_code, r.text[:160]) for r in results if r.status_code not in (201, 409)]
    infra = [m for m in caplog.messages if "infrastructure failure" in m]
    assert not bad and not infra, {"responses": bad, "diagnostics": infra}
    assert (
        await _count(
            "select count(*) from appointments a join appointments b on a.id < b.id "
            "and a.status='scheduled' and b.status='scheduled' and a.clinic_id=b.clinic_id "
            "and tstzrange(a.start_at, a.end_at) && tstzrange(b.start_at, b.end_at)"
        )
        == 0
    )
