"""Exposure guard and a few security properties (M6). Not an authentication test: CareDeploy has
no user authentication, and this file says so rather than implying otherwise."""

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.main import check_exposure


def test_development_defaults_start() -> None:
    check_exposure(Settings())


def test_production_refuses_without_acknowledgement() -> None:
    with pytest.raises(RuntimeError, match="no user authentication"):
        check_exposure(Settings(app_env="production"))
    check_exposure(Settings(app_env="production", allow_unauthenticated_admin=True))


def test_wildcard_cors_is_refused() -> None:
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        check_exposure(Settings(cors_origins="*"))


async def test_cors_only_allows_configured_origin(client: AsyncClient) -> None:
    ok = await client.options(
        "/api/health",
        headers={"Origin": "http://localhost:3100", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3100"
    bad = await client.options(
        "/api/health",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


async def test_worker_channel_and_health_never_leak_secrets(client: AsyncClient) -> None:
    r = await client.get("/api/health")
    text = r.text.lower()
    for word in ("secret", "password", "api_key", "token"):
        assert word not in text
    # Without the worker secret the worker channel is closed.
    denied = await client.post("/api/voice/worker/sessions/x/claim", json={"room_name": "x"})
    assert denied.status_code in (401, 422, 503)
