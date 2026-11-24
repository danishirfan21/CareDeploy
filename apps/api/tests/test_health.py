from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.session import get_engine
from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_cors_allows_frontend_origin(client: AsyncClient) -> None:
    r = await client.get("/api/health", headers={"Origin": "http://localhost:3100"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3100"


@pytest.mark.db
async def test_database_connectivity(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
    r = await client.get("/api/health/db")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": True}
