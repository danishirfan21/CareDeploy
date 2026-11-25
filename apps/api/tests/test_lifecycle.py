"""End-to-end lifecycle (M6): configuration -> evaluation -> promotion -> voice session -> real
scheduling through the shared backend tool layer -> Activity -> new version -> rollback, with every
claim checked against PostgreSQL.

The voice worker is played by the worker channel of the real API (no audio, no LiveKit, no model).
That proves the pipeline and its integrity rules; it does not prove speech or model behavior.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from tests.test_deployments import clear_deployments, promote, publish_change, url
from tests.world import World, utc

SECRET = "test-worker-secret"
WORKER = {"X-Voice-Worker-Secret": SECRET}
TUE_9 = utc(2026, 3, 3, 15, 0)


@pytest.fixture
def voice() -> Iterator[None]:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(
        livekit_url="wss://example.livekit.test",
        livekit_api_key="APItestkey",
        livekit_api_secret="test-livekit-secret-that-is-long-enough-123",
        voice_worker_secret=SECRET,
    )
    yield
    app.dependency_overrides.pop(get_settings, None)


async def scalar(sql: str, **params: Any) -> Any:
    async with get_sessionmaker()() as s:
        return await s.scalar(text(sql), params)


async def row(sql: str, **params: Any) -> tuple[Any, ...]:
    async with get_sessionmaker()() as s:
        r = (await s.execute(text(sql), params)).one()
        return tuple(r)


async def start_call(w: World, clinic_id: uuid.UUID) -> dict[str, Any]:
    r = await w.client.post(f"/api/clinics/{clinic_id}/voice/sessions")
    assert r.status_code == 201, r.text
    return dict(r.json())


async def claim(w: World, s: dict[str, Any]) -> dict[str, Any]:
    r = await w.client.post(
        f"/api/voice/worker/sessions/{s['call_session_id']}/claim",
        json={"room_name": s["room_name"]},
        headers=WORKER,
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


async def event(w: World, s: dict[str, Any], seq: int, kind: str, **payload: Any) -> None:
    r = await w.client.post(
        f"/api/voice/worker/sessions/{s['call_session_id']}/events",
        json={
            "events": [
                {
                    "event_id": f"life-{s['call_session_id']}-{seq}",
                    "seq": seq,
                    "kind": kind,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "payload": payload,
                }
            ]
        },
        headers=WORKER,
    )
    assert r.status_code == 200, r.text


async def evaluate(w: World, version: int) -> None:
    from app.evals.runner import Runner
    from app.evals.service import create_run
    from app.evals.store import ResultsStore

    async with get_sessionmaker()() as s:
        run = await create_run(
            s,
            w.north.id,
            mode="workflow",
            version=version,
            kind="all",
            value=None,
            requested_by="t",
        )
    store = ResultsStore(get_settings().database_url)
    try:
        await Runner(store, run.id).run()
    finally:
        await store.dispose()


async def test_full_lifecycle(voice: None, world: World) -> None:
    w = world
    await clear_deployments()
    cid = w.north.id

    # 1-3. A published configuration exists, but nothing is deployed: calls are refused and a
    #      newer draft is never treated as deployed.
    refused = await w.client.post(f"/api/clinics/{cid}/voice/sessions")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "no_active_deployment"
    cfg = (await w.client.get(f"/api/clinics/{cid}/config")).json()["config"]
    cfg["agent"]["greeting"] = "Draft greeting that nobody has published."
    assert (await w.client.put(f"/api/clinics/{cid}/config", json=cfg)).status_code == 200
    assert (await w.client.get(url(w))).json()["active"] is None

    # 4. Promotion is blocked without evidence, and the client cannot bypass the failed gate.
    blocked = await promote(w, 1, None)
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "deployment_blocked"
    assert (await promote(w, 1, None, force=True)).status_code == 422
    assert await scalar("select count(*) from deployments") == 0

    # 5-6. Evaluate the published version (workflow simulation) and read readiness.
    await evaluate(w, 1)
    ready = (await w.client.get(url(w, "/readiness"), params={"config_version": 1})).json()
    assert ready["eligible"] is True, ready["checks"]
    assert "Real voice verification" in ready["live_verification_message"]

    # 7. Promote to Simulated Live.
    first = await promote(w, 1, None, idempotency_key="life-promote-1")
    assert first.status_code == 201 and first.json()["environment_label"] == "Simulated Live"

    # 8-9. A voice session is pinned to version 1; the worker receives the frozen configuration,
    #      not the unpublished draft.
    call_a = await start_call(w, cid)
    assert call_a["config_version"] == 1
    ctx_a = await claim(w, call_a)
    assert ctx_a["config_version"] == 1
    assert "Draft greeting" not in ctx_a["config"]["agent"]["greeting"]

    # 10-11. Tools run through the shared backend layer; the worker reports events.
    patient = w.p("Avery")
    booked = await w.book(patient, "Annual physical", TUE_9, key="life-book-1")
    assert booked.status_code == 201, booked.text
    op_id = booked.headers["X-Operation-Id"]
    appt_id = booked.json()["appointment"]["id"]
    await event(
        w, call_a, 0, "transcript", speaker="caller", text="I'd like a physical.", final=True
    )
    await event(
        w,
        call_a,
        1,
        "tool",
        call_id="t1",
        name="confirm_operation",
        phase="finished",
        status="committed",
        message="Booked.",
        operation_id=op_id,
    )
    done = await w.client.post(
        f"/api/voice/worker/sessions/{call_a['call_session_id']}/complete",
        json={
            "outcome": "appointment_booked",
            "summary": "An appointment was booked.",
            "operation_ids": [op_id],
        },
        headers=WORKER,
    )
    assert done.status_code == 200, done.text

    # 12. Activity shows the call; the operation it reports exists in the ledger and the
    #     appointment it points at exists in PostgreSQL for the same clinic.
    detail = (await w.client.get(f"/api/clinics/{cid}/calls/{call_a['call_session_id']}")).json()
    assert detail["config_version"] == 1 and detail["deployment"]["config_version"] == 1
    assert detail["outcome_class"] == "completed"
    assert [o["id"] for o in detail["operations"]] == [op_id]
    assert detail["operations"][0]["appointment_id"] == appt_id
    assert (
        await scalar(
            "select count(*) from appointments where id = :i and clinic_id = :c"
            " and status = 'scheduled'",
            i=uuid.UUID(appt_id),
            c=cid,
        )
        == 1
    )
    # The same call is invisible from the other clinic (tenant boundary).
    other = f"/api/clinics/{w.lake.id}/calls/{call_a['call_session_id']}"
    assert (await w.client.get(other)).status_code == 404

    # 13. A fabricated operation id reported by a worker is not shown as a change.
    call_f = await start_call(w, cid)
    await claim(w, call_f)
    fake = await w.client.post(
        f"/api/voice/worker/sessions/{call_f['call_session_id']}/complete",
        json={
            "outcome": "appointment_booked",
            "summary": "x",
            "operation_ids": [str(uuid.uuid4())],
        },
        headers=WORKER,
    )
    assert fake.status_code == 200
    fdetail = (await w.client.get(f"/api/clinics/{cid}/calls/{call_f['call_session_id']}")).json()
    assert fdetail["operations"] == []

    # 14-17. Publish a changed version. It is not live until evaluated and promoted.
    v2 = await publish_change(w, "Welcome to version two.")
    assert v2 == 2
    still = await start_call(w, cid)
    assert still["config_version"] == 1
    assert (await promote(w, 2, 1)).status_code == 409  # no evidence for v2
    await evaluate(w, 2)
    assert (await promote(w, 2, 1, idempotency_key="life-promote-2")).status_code == 201

    # 18. New sessions use v2; sessions that already existed keep v1 (and their claim stays v1).
    call_b = await start_call(w, cid)
    assert call_b["config_version"] == 2
    assert (await claim(w, call_b))["config_version"] == 2
    again = await w.client.get(f"/api/voice/sessions/{call_a['call_session_id']}")
    assert again.json()["config_version"] == 1
    assert (await claim(w, still))["config_version"] == 1

    # Evidence and call records captured before the rollback, to prove it rewrites neither.
    results_sql = (
        "select md5(string_agg(r.id::text || r.status || r.scenario_hash, ',' order by r.id)),"
        " count(*) from eval_scenario_results r"
    )
    results_before = await row(results_sql)
    calls_before = await row(
        "select md5(string_agg(id::text || config_version::text, ',' order by id)), count(*)"
        " from call_sessions"
    )

    # 19. Roll back: a new event, v1 active again, new sessions on v1.
    rb = await w.client.post(
        url(w, "/rollback"), json={"target_version": 1, "expected_active_version": 2}
    )
    assert rb.status_code == 201 and rb.json()["config_version"] == 1
    assert (await start_call(w, cid))["config_version"] == 1

    # 20. History is complete, ordered and immutable; the published versions never changed.
    hist = (await w.client.get(url(w, "/history"))).json()
    assert [h["kind"] for h in hist] == ["rolled_back", "promoted", "promoted"]
    assert await scalar("select count(*) from deployments where status = 'active'") == 1
    greeting_v1 = await scalar(
        "select snapshot::text from config_versions where clinic_id = :c and version = 1",
        c=cid,
    )
    assert "version two" not in str(greeting_v1) and "Draft greeting" not in str(greeting_v1)
    # Rollback rewrote neither the earlier call records nor the stored evaluation results.
    assert await row(results_sql) == results_before and results_before[1] > 0
    still_calls = await row(
        "select md5(string_agg(id::text || config_version::text, ',' order by id)), count(*)"
        " from call_sessions where id = any(:ids)",
        ids=[uuid.UUID(x) for x in (call_a["call_session_id"], call_b["call_session_id"])],
    )
    assert still_calls[1] == 2 and calls_before[1] >= 2
    assert (await w.client.get(f"/api/clinics/{cid}/calls/{call_b['call_session_id']}")).json()[
        "config_version"
    ] == 2
    # Append-only history: the database refuses edits and deletes.
    async with get_sessionmaker()() as s:
        for stmt in ("DELETE FROM deployment_events", "UPDATE deployments SET config_version = 9"):
            with pytest.raises(DBAPIError):
                await s.execute(text(stmt))
            await s.rollback()
