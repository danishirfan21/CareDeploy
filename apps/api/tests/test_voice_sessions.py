"""Voice session API (M3): secure creation, frozen config, worker channel, idempotent events.

LiveKit credentials here are test values: tokens are real signed JWTs but no LiveKit server is
contacted. These tests do not exercise audio.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import jwt
import pytest
from httpx import AsyncClient

from app.config import Settings, get_settings
from tests.world import World

SECRET = "test-worker-secret"
LK_KEY = "APItestkey"
LK_SECRET = "test-livekit-secret-that-is-long-enough-123"
WORKER = {"X-Voice-Worker-Secret": SECRET}


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "livekit_url": "wss://example.livekit.test",
        "livekit_api_key": LK_KEY,
        "livekit_api_secret": LK_SECRET,
        "voice_worker_secret": SECRET,
    }
    base.update(over)
    return Settings(**base)


@pytest.fixture
def voice() -> Iterator[None]:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: _settings()
    yield
    app.dependency_overrides.pop(get_settings, None)


async def create(client: AsyncClient, clinic_id: uuid.UUID) -> dict[str, Any]:
    r = await client.post(f"/api/clinics/{clinic_id}/voice/sessions")
    assert r.status_code == 201, r.text
    return dict(r.json())


def ev(seq: int, kind: str = "transcript", **payload: Any) -> dict[str, Any]:
    return {
        "event_id": f"e{seq}",
        "seq": seq,
        "kind": kind,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


async def test_creation_requires_configuration(world: World) -> None:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: _settings(livekit_api_secret="")
    try:
        r = await world.client.post(f"/api/clinics/{world.north.id}/voice/sessions")
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "voice_not_configured"
    assert r.json()["detail"]["missing"] == ["LIVEKIT_API_SECRET"]


async def test_session_binds_clinic_version_and_scoped_token(voice: None, world: World) -> None:
    body = await create(world.client, world.north.id)
    assert body["clinic_name"] == "Northstar Family Medicine"
    assert body["agent_name"] == "Nora"
    assert body["config_version"] == 1
    assert body["dev_actor"] == "local-dev-operator"
    assert body["room_name"] == f"call-{body['call_session_id']}"
    claims = jwt.decode(
        body["token"], LK_SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )
    assert claims["iss"] == LK_KEY
    assert LK_SECRET not in body["token"]
    grants = claims["video"]
    assert grants["room"] == body["room_name"] and grants["roomJoin"] is True
    assert grants.get("roomAdmin") is not True and grants.get("canPublishData") is False
    assert grants["canPublishSources"] == ["microphone"]
    assert claims["exp"] - claims["nbf"] <= 600
    assert body["call_session_id"] in claims["metadata"]
    dispatch = claims["roomConfig"]["agents"][0]
    assert dispatch["agentName"] == "caredeploy-voice"
    assert dispatch["metadata"] == body["call_session_id"]
    assert "livekit_api_secret" not in str(body).lower()


async def test_unpublished_and_unknown_clinic(voice: None, client: AsyncClient) -> None:
    r = await client.post(
        "/api/clinics",
        json={
            "name": "Draft Clinic",
            "specialty": "Test",
            "location": "Nowhere",
            "timezone": "UTC",
        },
    )
    cid = r.json()["id"]
    r = await client.post(f"/api/clinics/{cid}/voice/sessions")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "clinic_not_configured"
    r = await client.post(f"/api/clinics/{uuid.uuid4()}/voice/sessions")
    assert r.status_code == 404


async def test_worker_channel_requires_secret(voice: None, world: World) -> None:
    s = await create(world.client, world.north.id)
    base = f"/api/voice/worker/sessions/{s['call_session_id']}"
    for headers in ({}, {"X-Voice-Worker-Secret": "wrong"}):
        r = await world.client.post(
            f"{base}/claim", json={"room_name": s["room_name"]}, headers=headers
        )
        assert r.status_code == 401
        r = await world.client.post(f"{base}/events", json={"events": [ev(0)]}, headers=headers)
        assert r.status_code == 401
    r = await world.client.post(f"{base}/claim", json={"room_name": "call-other"}, headers=WORKER)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "room_mismatch"


async def test_worker_disabled_without_secret(world: World) -> None:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: _settings(voice_worker_secret="")
    try:
        r = await world.client.post(
            f"/api/voice/worker/sessions/{uuid.uuid4()}/claim",
            json={"room_name": "x"},
            headers=WORKER,
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert r.status_code == 503


async def test_claim_returns_frozen_config_even_after_republish(voice: None, world: World) -> None:
    s = await create(world.client, world.north.id)
    cfg = (await world.client.get(f"/api/clinics/{world.north.id}/config")).json()["config"]
    cfg["agent"]["greeting"] = "A brand new greeting after the call started."
    assert (
        await world.client.put(f"/api/clinics/{world.north.id}/config", json=cfg)
    ).status_code == 200
    pub = await world.client.post(f"/api/clinics/{world.north.id}/config/publish")
    assert pub.status_code in (200, 201), pub.text

    r = await world.client.post(
        f"/api/voice/worker/sessions/{s['call_session_id']}/claim",
        json={"room_name": s["room_name"]},
        headers=WORKER,
    )
    assert r.status_code == 200, r.text
    ctx = r.json()
    assert ctx["config_version"] == 1
    assert "brand new greeting" not in ctx["config"]["agent"]["greeting"]
    assert ctx["config"]["details"]["name"] == "Northstar Family Medicine"
    assert ctx["config"]["appointment_types"][0]["id"]

    # A second claim is refused: one worker per call.
    again = await world.client.post(
        f"/api/voice/worker/sessions/{s['call_session_id']}/claim",
        json={"room_name": s["room_name"]},
        headers=WORKER,
    )
    assert again.status_code == 409

    # New sessions use the newly published version.
    s2 = await create(world.client, world.north.id)
    assert s2["config_version"] == 2


async def test_events_are_idempotent_ordered_and_scrubbed(voice: None, world: World) -> None:
    s = await create(world.client, world.lake.id)
    sid = s["call_session_id"]
    base = f"/api/voice/worker/sessions/{sid}"
    batch = {
        "events": [
            ev(1, speaker="agent", text="Hello"),
            ev(0, "system", message="joined"),
            ev(
                2,
                "tool",
                name="verify_patient",
                args={"patient_id": "p", "date_of_birth": "1990-01-01", "phone_last4": "1234"},
            ),
        ]
    }
    r = await world.client.post(f"{base}/events", json=batch, headers=WORKER)
    assert r.json() == {"accepted": 3, "duplicates": 0}
    r = await world.client.post(f"{base}/events", json=batch, headers=WORKER)
    assert r.json() == {"accepted": 0, "duplicates": 3}

    got = (await world.client.get(f"/api/voice/sessions/{sid}/events")).json()["events"]
    assert [e["seq"] for e in got] == [0, 1, 2]
    assert got[2]["payload"]["args"] == {"patient_id": "p"}
    after = (await world.client.get(f"/api/voice/sessions/{sid}/events?after_seq=1")).json()[
        "events"
    ]
    assert [e["seq"] for e in after] == [2]


async def test_state_complete_and_browser_end(voice: None, world: World) -> None:
    s = await create(world.client, world.north.id)
    sid = s["call_session_id"]
    base = f"/api/voice/worker/sessions/{sid}"
    await world.client.post(f"{base}/claim", json={"room_name": s["room_name"]}, headers=WORKER)
    r = await world.client.put(
        f"{base}/state",
        json={"state": {"conversation": "listening", "interim": "I need"}},
        headers=WORKER,
    )
    assert r.status_code == 200
    read = (await world.client.get(f"/api/voice/sessions/{sid}")).json()
    assert read["status"] == "active" and read["live_state"]["conversation"] == "listening"

    # Browser hangs up first; the worker's findings still land.
    ended = await world.client.post(f"/api/voice/sessions/{sid}/end", json={"reason": "user_ended"})
    assert ended.json()["status"] == "completed" and ended.json()["ended_by"] == "browser"
    done = await world.client.post(
        f"{base}/complete",
        json={
            "outcome": "appointment_booked",
            "summary": "Booked.",
            "operation_ids": ["op-1", "op-1", "op-2"],
            "metrics": {"tool_calls": 4, "token": "must-not-persist"},
        },
        headers=WORKER,
    )
    body = done.json()
    assert body["outcome"] == "appointment_booked" and body["status"] == "completed"
    assert body["operation_ids"] == ["op-1", "op-2"]
    assert body["metrics"] == {"tool_calls": 4}
    assert body["duration_seconds"] is not None and body["duration_seconds"] >= 0


async def test_end_before_worker_joins_is_abandoned(voice: None, world: World) -> None:
    s = await create(world.client, world.north.id)
    r = await world.client.post(
        f"/api/voice/sessions/{s['call_session_id']}/end", json={"reason": "connection_failed"}
    )
    assert r.json()["status"] == "failed" and r.json()["error"] == "connection_failed"
    late = await world.client.post(
        f"/api/voice/worker/sessions/{s['call_session_id']}/claim",
        json={"room_name": s["room_name"]},
        headers=WORKER,
    )
    assert late.status_code == 409


async def test_expired_session_cannot_be_claimed(voice: None, world: World) -> None:
    s = await create(world.client, world.north.id)
    world.clock.advance(minutes=30)
    r = await world.client.post(
        f"/api/voice/worker/sessions/{s['call_session_id']}/claim",
        json={"room_name": s["room_name"]},
        headers=WORKER,
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "session_expired"
    assert (await world.client.get(f"/api/voice/sessions/{s['call_session_id']}")).json()[
        "status"
    ] == "abandoned"


async def test_sessions_are_clinic_isolated(voice: None, world: World) -> None:
    a = await create(world.client, world.north.id)
    b = await create(world.client, world.lake.id)
    assert a["clinic_id"] != b["clinic_id"] and a["room_name"] != b["room_name"]
    claims_a = jwt.decode(
        a["token"], LK_SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )
    assert claims_a["video"]["room"] != b["room_name"]
    r = await world.client.post(
        f"/api/voice/worker/sessions/{b['call_session_id']}/claim",
        json={"room_name": a["room_name"]},
        headers=WORKER,
    )
    assert r.status_code == 403
