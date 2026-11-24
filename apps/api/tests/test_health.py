import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.db.session import get_engine


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
