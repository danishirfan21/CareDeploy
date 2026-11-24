"""Migration 0003 on a scratch database: M1 data survives, and up/down/up round-trips."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.config import get_settings

API_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = "caredeploy_migration_test"


def _admin_url() -> str:
    url = make_url(get_settings().database_url).set(drivername="postgresql", database="postgres")
    return url.render_as_string(False)


def _scratch_url() -> str:
    return (
        make_url(get_settings().database_url)
        .set(database=SCRATCH)
        .render_as_string(hide_password=False)
    )


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": _scratch_url(), "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _sync(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(False)


@pytest.fixture
def scratch() -> str:
    with psycopg.connect(_admin_url(), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{SCRATCH}"')
    return _sync(_scratch_url())


def test_m1_data_survives_upgrade_and_roundtrip_is_clean(scratch: str) -> None:
    r = _alembic("upgrade", "0002")
    assert r.returncode == 0, r.stderr
    clinic, atype = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(scratch, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO clinics (id, name, specialty, location, timezone, phone, email) "
            "VALUES (%s, 'Legacy Clinic', 's', 'l', 'America/Chicago', '555', 'a@b.example')",
            (clinic,),
        )
        conn.execute(
            "INSERT INTO appointment_types (id, clinic_id, name, duration_minutes, position, requires_human_escalation, constraints) "
            "VALUES (%s, %s, 'Checkup', 30, 0, false, '')",
            (atype, clinic),
        )

    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stderr
    with psycopg.connect(scratch) as conn:
        row = conn.execute(
            "SELECT name, archived_at FROM appointment_types WHERE id = %s", (atype,)
        ).fetchone()
        assert row == ("Checkup", None)  # M1 row keeps its id and is active
        tables = {
            t[0]
            for t in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }
        assert {"patients", "appointments", "appointment_events", "operations"} <= tables
        constraint = conn.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = 'ex_appointments_no_overlap'"
        ).fetchone()
        assert constraint is not None

    r = _alembic("downgrade", "0002")
    assert r.returncode == 0, r.stderr
    with psycopg.connect(scratch) as conn:
        assert conn.execute("SELECT count(*) FROM appointment_types").fetchone() == (1,)
        gone = conn.execute("SELECT to_regclass('public.appointments')").fetchone()
        assert gone == (None,)

    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stderr


def test_models_match_migrations(scratch: str) -> None:
    assert _alembic("upgrade", "head").returncode == 0
    r = _alembic("check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_evaluation_migration_is_additive_and_reversible(scratch: str) -> None:
    assert _alembic("upgrade", "0004").returncode == 0
    with psycopg.connect(scratch) as conn:
        assert conn.execute("SELECT to_regclass('public.eval_runs')").fetchone() == (None,)
    assert _alembic("upgrade", "head").returncode == 0
    with psycopg.connect(scratch) as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }
        assert {"eval_runs", "eval_scenario_results", "eval_events"} <= names
        triggers = {
            r[0] for r in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        }
        assert "eval_runs_immutable" in triggers
    r = _alembic("downgrade", "0004")
    assert r.returncode == 0, r.stderr
    with psycopg.connect(scratch) as conn:
        assert conn.execute("SELECT to_regclass('public.eval_runs')").fetchone() == (None,)
        assert conn.execute("SELECT to_regclass('public.appointments')").fetchone() != (None,)
    assert _alembic("upgrade", "head").returncode == 0
