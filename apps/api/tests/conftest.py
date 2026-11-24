"""Tests run against a real, freshly migrated PostgreSQL database named `<db>_test`.

The development database is never touched.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.testdb import reset_database

if TYPE_CHECKING:
    from tests.world import FakeClock, ScriptedFaults, World

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
            "agent_configs, config_versions, patients CASCADE"
        )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---- scheduling fixtures (M2) ---------------------------------------------------------------
@pytest.fixture
def clock() -> Iterator["FakeClock"]:
    from app.main import app
    from app.scheduling.runtime import get_clock
    from tests.world import FakeClock

    fake = FakeClock()
    app.dependency_overrides[get_clock] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_clock, None)


@pytest.fixture
def faults() -> Iterator["ScriptedFaults"]:
    from app.main import app
    from app.scheduling.runtime import get_faults
    from tests.world import ScriptedFaults

    scripted = ScriptedFaults()
    app.dependency_overrides[get_faults] = lambda: scripted
    yield scripted
    app.dependency_overrides.pop(get_faults, None)


@pytest.fixture
async def world(client: AsyncClient, clock: "FakeClock") -> "World":
    """Both seeded clinics, published, with their synthetic patients."""
    from sqlalchemy import select

    from app.db.session import get_sessionmaker
    from app.models import Patient
    from app.seed import publish_seeded, seed
    from tests.world import ClinicInfo, PatientInfo, World, patient_creds

    async with get_sessionmaker()() as session:
        await seed(session)
        await publish_seeded(session)
        await session.commit()
        rows = (await session.scalars(select(Patient))).all()
    w = World(client, clock)
    for c in (await client.get("/api/clinics")).json():
        info = (await client.get(f"/api/clinics/{c['id']}/scheduling")).json()
        w.clinics[c["name"]] = ClinicInfo(
            uuid.UUID(c["id"]),
            c["name"],
            {t["name"]: uuid.UUID(t["id"]) for t in info["appointment_types"]},
        )
    creds = patient_creds()
    for row in rows:
        first = row.full_name.split()[0]
        clinic_name, dob, last4 = creds[first]
        w.patients[first] = PatientInfo(row.id, w.clinics[clinic_name], row.full_name, dob, last4)
    return w
