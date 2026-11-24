"""Deployments (M5): server-side readiness, atomic promotion, rollback, audit and voice pinning."""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.models import Deployment, DeploymentEvent
from app.models.evals import EvalRun
from tests.test_evals_runner import run_eval
from tests.world import World

SECRET = "test-worker-secret"


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


async def clear_deployments() -> None:
    """The sample fixtures start every clinic with a seed deployment. Tests that exercise
    promotion start from "never deployed". TRUNCATE is not subject to the row triggers."""
    async with get_sessionmaker()() as s:
        await s.execute(text("TRUNCATE deployment_events, deployments CASCADE"))
        await s.commit()


def url(world: World, tail: str = "", name: str = "Northstar Family Medicine") -> str:
    return f"/api/clinics/{world.clinics[name].id}/deployment{tail}"


async def promote(world: World, version: int = 1, expected: int | None = None, **extra: Any) -> Any:
    body = {"config_version": version, "expected_active_version": expected, **extra}
    return await world.client.post(url(world, "/promote"), json=body)


@pytest.fixture
async def evaluated(world: World) -> World:
    await clear_deployments()
    await run_eval(world, "all")
    return world


async def test_fresh_clinic_has_no_active_deployment(world: World) -> None:
    await clear_deployments()
    state = (await world.client.get(url(world))).json()
    assert state["active"] is None and state["environment_label"] == "Simulated Live"
    assert state["latest_published_version"] == 1
    assert (await world.client.get(url(world, "/history"))).json() == []


async def test_promotion_is_blocked_without_evidence(world: World) -> None:
    await clear_deployments()
    r = await promote(world)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "deployment_blocked"
    ids = {c["id"] for c in r.json()["detail"]["checks"]}
    assert "required_coverage" in ids
    a = (await world.client.get(url(world, "/readiness"), params={"config_version": 1})).json()
    assert a["eligible"] is False and a["decision"] == "blocked"
    assert "Real voice verification" in a["live_verification_message"]
    assert (await world.client.get(url(world))).json()["active"] is None


async def test_client_cannot_force_or_supply_readiness(world: World) -> None:
    await clear_deployments()
    for extra in ({"force": True}, {"ready": True}, {"readiness": {"level": "ready"}}):
        r = await promote(world, **extra)
        assert r.status_code == 422, extra
    assert (await world.client.get(url(world))).json()["active"] is None


async def test_unknown_and_foreign_versions_are_not_found(world: World) -> None:
    await clear_deployments()
    assert (await promote(world, 99)).status_code == 404
    assert (
        await world.client.post(
            f"/api/clinics/{uuid.uuid4()}/deployment/promote", json={"config_version": 1}
        )
    ).status_code == 404


async def test_promote_after_full_pass_then_replay_and_conflicts(evaluated: World) -> None:
    w = evaluated
    a = (await w.client.get(url(w, "/readiness"), params={"config_version": 1})).json()
    assert a["eligible"] is True, a["checks"]
    r = await promote(w, 1, None, idempotency_key="promote-key-0001")
    assert r.status_code == 201, r.text
    dep = r.json()
    assert dep["status"] == "active" and dep["environment_label"] == "Simulated Live"
    assert dep["action"] == "promote"

    # Same key, same request: the original result, nothing new written.
    again = await promote(w, 1, None, idempotency_key="promote-key-0001")
    assert again.status_code == 200 and again.json()["id"] == dep["id"]
    # Same key, different request: refused.
    clash = await promote(w, 1, 1, idempotency_key="promote-key-0001")
    assert clash.status_code == 409 and clash.json()["detail"]["code"] == "idempotency_conflict"
    # Stale caller (thinks nothing is active, but version 1 is): compare-and-swap rejects.
    stale = await promote(w, 1, None)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "concurrent_modification"
    # Promoting the active version again changes nothing.
    noop = await promote(w, 1, 1)
    assert noop.status_code == 409 and noop.json()["detail"]["code"] == "already_active"

    hist = (await w.client.get(url(w, "/history"))).json()
    assert len(hist) == 1 and hist[0]["kind"] == "promoted" and hist[0]["from_version"] is None
    detail = (await w.client.get(url(w, f"/events/{hist[0]['id']}"))).json()
    assert detail["readiness"]["assessment"]["eligible"] is True
    # Another clinic cannot read it.
    other = url(w, f"/events/{hist[0]['id']}", "Lakeside Dermatology")
    assert (await w.client.get(other)).status_code == 404


async def test_concurrent_promotions_leave_one_active(evaluated: World) -> None:
    w = evaluated
    rs = await asyncio.gather(
        *[promote(w, 1, None, idempotency_key=f"concurrent-key-{i}") for i in range(4)]
    )
    codes = sorted(r.status_code for r in rs)
    assert codes.count(201) == 1 and set(codes) <= {201, 409}
    async with get_sessionmaker()() as s:
        active = (await s.scalars(select(Deployment).where(Deployment.status == "active"))).all()
        events = (await s.scalars(select(DeploymentEvent))).all()
    assert len(active) == 1 and len(events) == 1


async def test_critical_failure_blocks(evaluated: World) -> None:
    w = evaluated
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "UPDATE eval_scenario_results SET status='failed', "
                'failure=\'{"summary": "forced"}\'::jsonb '
                "WHERE scenario_id = 'EVAL-001'"
            )
        )
        await s.execute(update(EvalRun).values(counts={"passed": 19, "failed": 1}))
        await s.commit()
    r = await promote(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "deployment_blocked"


async def test_stale_evidence_is_rejected(evaluated: World) -> None:
    w = evaluated
    old = datetime.now(UTC) - timedelta(days=90)
    async with get_sessionmaker()() as s:
        await s.execute(update(EvalRun).values(finished_at=old))
        await s.commit()
    r = await promote(w)
    assert r.status_code == 409
    ids = {c["id"] for c in r.json()["detail"]["checks"]}
    assert "evidence_recent" in ids


async def test_changed_suite_invalidates_evidence(evaluated: World) -> None:
    w = evaluated
    async with get_sessionmaker()() as s:
        await s.execute(update(EvalRun).values(suite_hash="0" * 64))
        await s.commit()
    r = await promote(w)
    assert r.status_code == 409
    assert "evidence_current" in {c["id"] for c in r.json()["detail"]["checks"]}


async def publish_change(w: World, greeting: str) -> int:
    cid = w.north.id
    cfg = (await w.client.get(f"/api/clinics/{cid}/config")).json()["config"]
    cfg["agent"]["greeting"] = greeting
    assert (await w.client.put(f"/api/clinics/{cid}/config", json=cfg)).status_code == 200
    pub = await w.client.post(f"/api/clinics/{cid}/config/publish")
    assert pub.status_code in (200, 201), pub.text
    return int(pub.json()["version"])


async def test_rollback_is_a_new_event_and_unsafe_targets_are_rejected(evaluated: World) -> None:
    w = evaluated
    assert (await promote(w, 1, None)).status_code == 201
    v2 = await publish_change(w, "A different greeting for version two.")
    assert v2 == 2
    # Version 2 has no evidence yet.
    blocked = await promote(w, 2, 1)
    assert blocked.status_code == 409
    # Evaluate version 2 and promote it.
    async with get_sessionmaker()() as s:
        from app.evals.runner import Runner
        from app.evals.service import create_run
        from app.evals.store import ResultsStore

        run = await create_run(
            s, w.north.id, mode="workflow", version=2, kind="all", value=None, requested_by="t"
        )
    store = ResultsStore(get_settings().database_url)
    try:
        await Runner(store, run.id).run()
    finally:
        await store.dispose()
    assert (await promote(w, 2, 1)).status_code == 201

    # Never-deployed target, unknown target and current target are all refused.
    body = {"target_version": 9, "expected_active_version": 2}
    assert (await w.client.post(url(w, "/rollback"), json=body)).status_code == 404
    same = {"target_version": 2, "expected_active_version": 2}
    r = await w.client.post(url(w, "/rollback"), json=same)
    assert r.status_code == 409 and r.json()["detail"]["code"] in (
        "already_active",
        "rollback_blocked",
    )

    ok = await w.client.post(
        url(w, "/rollback"), json={"target_version": 1, "expected_active_version": 2}
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["config_version"] == 1 and ok.json()["action"] == "rollback"
    assert ok.json()["restored_from_id"] is not None

    hist = (await w.client.get(url(w, "/history"))).json()
    assert [h["kind"] for h in hist] == ["rolled_back", "promoted", "promoted"]
    state = (await w.client.get(url(w))).json()
    assert state["active"]["config_version"] == 1

    # History is immutable at the database level.
    async with get_sessionmaker()() as s:
        for stmt in (
            "DELETE FROM deployment_events",
            "UPDATE deployment_events SET actor = 'x'",
            "DELETE FROM deployments",
            "UPDATE deployments SET config_version = 2",
        ):
            with pytest.raises(DBAPIError):
                await s.execute(text(stmt))
            await s.rollback()


async def test_rollback_to_never_deployed_version_is_rejected(evaluated: World) -> None:
    w = evaluated
    assert (await promote(w, 1, None)).status_code == 201
    await publish_change(w, "Another greeting that was never deployed.")
    r = await w.client.post(
        url(w, "/rollback"), json={"target_version": 2, "expected_active_version": 1}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "rollback_blocked"
    ids = {c["id"] for c in r.json()["detail"]["checks"]}
    assert "rollback_target" in ids


async def test_database_rejects_cross_clinic_and_double_active(world: World) -> None:
    await clear_deployments()
    async with get_sessionmaker()() as s:
        now = datetime.now(UTC)
        base: dict[str, Any] = {
            "environment": "simulated_live",
            "action": "seed",
            "activated_at": now,
            "actor": "t",
            "readiness": {},
            "readiness_level": "not_evaluated",
        }
        # Version 7 of the Lakeside clinic does not exist.
        s.add(Deployment(clinic_id=world.lake.id, config_version=7, status="active", **base))
        with pytest.raises(DBAPIError):
            await s.flush()
        await s.rollback()
        s.add(Deployment(clinic_id=world.lake.id, config_version=1, status="active", **base))
        await s.flush()
        s.add(Deployment(clinic_id=world.lake.id, config_version=1, status="active", **base))
        with pytest.raises(DBAPIError):
            await s.flush()
        await s.rollback()


# ------------------------------------------------------------------------- voice runtime ------
async def test_voice_requires_an_active_deployment(voice: None, world: World) -> None:
    await clear_deployments()
    r = await world.client.post(f"/api/clinics/{world.north.id}/voice/sessions")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "no_active_deployment"
    assert "evaluate" in d["message"].lower() and "promote" in d["message"].lower()


async def test_voice_uses_the_active_version_and_pins_it(voice: None, evaluated: World) -> None:
    w = evaluated
    assert (await promote(w, 1, None)).status_code == 201
    s1 = (await w.client.post(f"/api/clinics/{w.north.id}/voice/sessions")).json()
    assert s1["config_version"] == 1

    # A newer published version is NOT used until it is deployed.
    await publish_change(w, "Greeting that is published but not deployed.")
    s2 = (await w.client.post(f"/api/clinics/{w.north.id}/voice/sessions")).json()
    assert s2["config_version"] == 1

    # The session records which deployment it ran under, and the worker keeps its version.
    async with get_sessionmaker()() as s:
        from app.models import CallSession

        cs = await s.get(CallSession, uuid.UUID(s1["call_session_id"]))
        dep = await s.scalar(select(Deployment).where(Deployment.status == "active"))
        assert cs is not None and dep is not None and cs.deployment_id == dep.id
    claim = await w.client.post(
        f"/api/voice/worker/sessions/{s1['call_session_id']}/claim",
        json={"room_name": s1["room_name"]},
        headers={"X-Voice-Worker-Secret": SECRET},
    )
    assert claim.json()["config_version"] == 1


async def test_voice_sessions_started_before_a_rollback_keep_their_version(
    voice: None, world: World
) -> None:
    await clear_deployments()
    from app.deploy.service import seed_activation

    async with get_sessionmaker()() as s:
        await seed_activation(s, world.north.id, 1)
        await s.commit()
    first = (await world.client.post(f"/api/clinics/{world.north.id}/voice/sessions")).json()
    await publish_change(world, "Second version greeting.")
    async with get_sessionmaker()() as s:
        await seed_activation(s, world.north.id, 2)
        await s.commit()
    second = (await world.client.post(f"/api/clinics/{world.north.id}/voice/sessions")).json()
    assert (first["config_version"], second["config_version"]) == (1, 2)
    again = await world.client.get(f"/api/voice/sessions/{first['call_session_id']}")
    assert again.json()["config_version"] == 1


async def test_ending_a_session_classifies_it(
    voice: None, world: World, client: AsyncClient
) -> None:
    s = (await world.client.post(f"/api/clinics/{world.north.id}/voice/sessions")).json()
    r = await world.client.post(
        f"/api/voice/sessions/{s['call_session_id']}/end", json={"reason": "user_ended"}
    )
    assert r.status_code == 200
    detail = (
        await world.client.get(f"/api/clinics/{world.north.id}/calls/{s['call_session_id']}")
    ).json()
    assert detail["outcome_class"] == "abandoned"
    assert detail["deployment"]["config_version"] == 1
