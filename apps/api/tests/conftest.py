"""Tests run against a real, freshly migrated PostgreSQL database named `<db>_test`.

The development database is never touched.
"""

from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.testdb import reset_database

TEST_DB = "caredeploy_test"


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    reset_database(TEST_DB)  # also points DATABASE_URL at the test DB
    yield


@pytest.fixture(autouse=True)
def _clean_tables(_database: None) -> None:
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(False), autocommit=True) as conn:
        conn.execute(
            "TRUNCATE clinics, operating_hours, appointment_types, scheduling_policies, "
            "agent_configs, config_versions CASCADE"
        )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
