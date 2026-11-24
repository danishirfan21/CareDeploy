"""Isolated fixtures for evaluation scenarios.

Isolation mechanism: **a database per scenario**, cloned from a migrated template database that is
created for the run and dropped at its end. Published configurations and appointment history are
immutable by design (database triggers), so a scenario's clinic cannot be deleted afterwards;
dropping the whole scenario database is the only honest cleanup, and it cannot touch ordinary
clinics because those live in a different database. Only databases this module created (names
matching `EVAL_DB_NAME`) are ever dropped.
"""

import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import psycopg
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url

from alembic import command
from app.config import get_settings
from app.db import session as db_session
from app.evals.schema import PatientFixture, Scenario
from app.models import Clinic, ConfigVersion, Patient
from app.scheduling.runtime import Faults
from app.schemas.clinic import ClinicConfig
from app.seed import LAKESIDE
from app.services import clinics as svc
from app.testdb import API_ROOT

EVAL_DB_NAME = re.compile(r"^[a-z0-9_]{1,40}_ev[0-9a-f]{12}(_t|_s\d{2,3})$")


class FixtureError(Exception):
    """The scenario could not be set up. Reported as an *error*, never as a pass or a failure of
    the agent."""


# --------------------------------------------------------------------------- databases --------
def _sync_url(name: str) -> str:
    return (
        make_url(get_settings().database_url)
        .set(drivername="postgresql", database=name)
        .render_as_string(False)
    )


def _async_url(name: str) -> str:
    return make_url(get_settings().database_url).set(database=name).render_as_string(False)


def _admin_conn() -> psycopg.Connection[Any]:
    return psycopg.connect(_sync_url("postgres"), autocommit=True)


def _guard(name: str) -> str:
    if not EVAL_DB_NAME.match(name):
        raise FixtureError(f"refusing to manage database '{name}': not an evaluation database")
    return name


async def _repoint(url: str | None) -> None:
    """Point the process-wide app engine at `url` (or back to the environment default)."""
    if db_session._engine is not None:
        await db_session._engine.dispose()
    db_session._engine = None
    db_session._sessionmaker = None
    if url is None:
        os.environ.pop("CAREDEPLOY_EVAL_SAVED_URL", None)
    get_settings.cache_clear()


class RunDatabases:
    """Template database for a run plus one disposable database per scenario."""

    def __init__(self) -> None:
        self.main_name = make_url(get_settings().database_url).database or ""
        self.tag = uuid.uuid4().hex[:12]
        base = re.sub(r"[^a-z0-9_]", "", self.main_name.lower())[:30] or "caredeploy"
        self._base = f"{base}_ev{self.tag}"
        self.template = _guard(f"{self._base}_t")
        self._saved_url = os.environ.get("DATABASE_URL")
        self._current: str | None = None
        self.created: list[str] = []

    def create_template(self) -> None:
        with _admin_conn() as conn:
            conn.execute(f'CREATE DATABASE "{self.template}"')
        self.created.append(self.template)
        self._migrate(self.template)

    def _migrate(self, name: str) -> None:
        saved = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = _async_url(name)
        get_settings.cache_clear()
        try:
            cfg = Config(str(API_ROOT / "alembic.ini"))
            cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
            command.upgrade(cfg, "head")
        finally:
            if saved is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = saved
            get_settings.cache_clear()

    def scenario_db(self, index: int) -> str:
        name = _guard(f"{self._base}_s{index:02d}")
        with _admin_conn() as conn:
            # Nothing of ours should still be attached to the template (a pooled connection from
            # the migration run can linger); a template must have no sessions to be copied.
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (self.template,),
            )
            conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{self.template}"')
        self.created.append(name)
        return name

    async def use(self, name: str) -> None:
        _guard(name)
        os.environ["DATABASE_URL"] = _async_url(name)
        await _repoint(os.environ["DATABASE_URL"])
        self._current = name

    async def restore(self) -> None:
        if self._saved_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self._saved_url
        await _repoint(None)
        self._current = None

    def drop(self, name: str) -> bool:
        _guard(name)
        try:
            with _admin_conn() as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except psycopg.Error:
            return False
        if name in self.created:
            self.created.remove(name)
        return True

    def drop_all(self) -> list[str]:
        """Drop everything this run created; returns names that could not be dropped."""
        return [n for n in list(self.created) if not self.drop(n)]


# --------------------------------------------------------------------------- doubles -----------
class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class ScriptedFaults(Faults):
    """Raise a prepared exception the first N times a named point in the scheduling engine is
    reached. This is the same hook the M2 reliability tests use."""

    def __init__(self) -> None:
        self.plan: dict[str, list[BaseException]] = {}
        self.hits: list[str] = []

    def fail_at(self, point: str, exc: BaseException, times: int = 1) -> None:
        self.plan[point] = [exc] * times

    def clear(self) -> None:
        self.plan.clear()

    async def hit(self, point: str) -> None:
        self.hits.append(point)
        queue = self.plan.get(point)
        if queue:
            raise queue.pop(0)


class LossyTransport(httpx.AsyncBaseTransport):
    """Forwards to the app, but can lose a request (never delivered) or a response (delivered,
    answer lost) for matching POSTs, which is how a real network loses them."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.drop_request = 0
        self.drop_response = 0
        self.down = False
        self.match = "/appointments"
        self.calls: list[str] = []

    def clear(self) -> None:
        self.drop_request = self.drop_response = 0
        self.down = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hit = request.method == "POST" and self.match in request.url.path
        self.calls.append(f"{request.method} {request.url.path}")
        if self.down and (hit or "/operations" in request.url.path):
            raise httpx.ConnectTimeout("backend unreachable", request=request)
        if hit and self.drop_request > 0:
            self.drop_request -= 1
            raise httpx.ConnectTimeout("request lost", request=request)
        resp = await self.inner.handle_async_request(request)
        if hit and self.drop_response > 0:
            self.drop_response -= 1
            await resp.aread()
            raise httpx.ReadTimeout("response lost", request=request)
        return resp


# --------------------------------------------------------------------------- source config -----
@dataclass(frozen=True)
class SourceConfig:
    """The exact published version under evaluation, read once from the results database."""

    clinic_id: uuid.UUID
    version: int
    config: ClinicConfig
    content_hash: str


@dataclass
class PatientRef:
    key: str
    id: uuid.UUID
    name: str
    dob: str
    last4: str
    clinic: str  # "primary" | "other"


@dataclass
class World:
    app: Any
    http: AsyncClient
    transport: LossyTransport
    faults: ScriptedFaults
    clock: FixedClock
    primary_id: uuid.UUID
    other_id: uuid.UUID | None
    config: ClinicConfig
    version: int
    patients: dict[str, PatientRef] = field(default_factory=dict)
    appointments: dict[str, uuid.UUID] = field(default_factory=dict)
    appointment_starts: dict[str, datetime] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    baseline: dict[str, int] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)

    def clinic_id(self, which: str) -> uuid.UUID:
        if which == "other":
            if self.other_id is None:
                raise FixtureError("scenario uses the other clinic but did not declare it")
            return self.other_id
        return self.primary_id

    async def close(self) -> None:
        await self.http.aclose()


# --------------------------------------------------------------------------- variables ---------
_VAR = re.compile(r"\$\{([a-zA-Z0-9_.]+)\}")


def resolve(value: Any, world: World) -> Any:
    """Substitute ${...} variables in strings, recursively. Unknown variables are a fixture
    error: a silent literal would let a scenario test the wrong thing."""
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if name in world.variables:
                return world.variables[name]
            parts = name.split(".")
            if parts[0] == "patient" and len(parts) == 3 and parts[1] in world.patients:
                p = world.patients[parts[1]]
                found = {"name": p.name, "dob": p.dob, "last4": p.last4, "id": str(p.id)}.get(
                    parts[2]
                )
                if found is not None:
                    return found
            if parts[0] == "appt" and len(parts) == 3 and parts[1] in world.appointments:
                if parts[2] == "id":
                    return str(world.appointments[parts[1]])
                if parts[2] == "start":
                    return world.appointment_starts[parts[1]].isoformat().replace("+00:00", "Z")
            raise FixtureError(f"unresolved variable ${{{name}}}")

        return _VAR.sub(sub, value)
    if isinstance(value, list):
        return [resolve(v, world) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, world) for k, v in value.items()}
    return value


def _utc_iso(local: datetime) -> str:
    return local.astimezone(UTC).isoformat().replace("+00:00", "Z")


def compute_variables(config: ClinicConfig, now: datetime) -> dict[str, str]:
    """Dates derived from the configuration under test and the scenario's fixed clock, so one
    scenario file works for any configuration that has the needed hours and appointment types."""
    tz = ZoneInfo(config.details.timezone)
    local_now = now.astimezone(tz)
    hours = {h.weekday: (h.opens, h.closes) for h in config.hours}
    out: dict[str, str] = {"today": local_now.date().isoformat()}
    std = next((t for t in config.appointment_types if not t.requires_human_escalation), None)
    esc = next((t for t in config.appointment_types if t.requires_human_escalation), None)
    if std:
        out["standard_type"] = std.name
    if esc:
        out["escalation_type"] = esc.name

    def at(d: date, hhmm: str | time, plus_minutes: int = 0) -> datetime:
        if isinstance(hhmm, time):
            h, m = hhmm.hour, hhmm.minute
        else:
            h, m = (int(x) for x in hhmm.split(":")[:2])
        return datetime.combine(d, time(h, m), tzinfo=tz) + timedelta(minutes=plus_minutes)

    opens_seen: list[date] = []
    closed: date | None = None
    for i in range(2, 40):
        d = local_now.date() + timedelta(days=i)
        if d.weekday() in hours:
            if len(opens_seen) < 3:
                opens_seen.append(d)
        elif closed is None:
            closed = d
    for n, d in enumerate(opens_seen, start=1):
        out["open_date" if n == 1 else f"open_date_{n}"] = d.isoformat()
    if opens_seen:
        d1 = opens_seen[0]
        o, c = hours[d1.weekday()]
        out["slot_first"] = _utc_iso(at(d1, o, 0))
        out["slot_a"] = _utc_iso(at(d1, o, 60))
        out["slot_b"] = _utc_iso(at(d1, o, 120))
        out["slot_c"] = _utc_iso(at(d1, o, 180))
        out["after_hours_start"] = _utc_iso(at(d1, c, 60))
        out["before_hours_start"] = _utc_iso(at(d1, o, -180))
        if len(opens_seen) > 1:
            d2 = opens_seen[1]
            o2, _c2 = hours[d2.weekday()]
            out["slot_next_day"] = _utc_iso(at(d2, o2, 60))
    if closed:
        out["closed_date"] = closed.isoformat()
        out["closed_day_start"] = _utc_iso(at(closed, "10:00"))
    return out


# --------------------------------------------------------------------------- building ---------
def _strip_ids(config: ClinicConfig) -> ClinicConfig:
    copy = config.model_copy(deep=True)
    for t in copy.appointment_types:
        t.id = None
    return copy


async def _create_clinic(
    config: ClinicConfig, version: int, patients: list[PatientFixture]
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """Create a clinic whose *published version number and content* equal the source's. The
    version row is written directly (not via `publish`) so the number is preserved; the snapshot
    is produced by the production `build_config`/`snapshot_of` code."""
    async with db_session.get_sessionmaker()() as session:
        clinic = Clinic(**config.details.model_dump())
        session.add(clinic)
        await session.flush()
        await svc.save_config(session, clinic, _strip_ids(config))
        built = await svc.build_config(session, clinic)
        verdict = svc.validate_config(built)
        if not verdict.valid:
            raise FixtureError(
                "the selected configuration does not validate: "
                + "; ".join(i.message for i in verdict.issues if i.severity == "error")
            )
        session.add(
            ConfigVersion(clinic_id=clinic.id, version=version, snapshot=svc.snapshot_of(built))
        )
        ids: dict[str, uuid.UUID] = {}
        for p in patients:
            row = Patient(
                clinic_id=clinic.id,
                full_name=p.name,
                date_of_birth=date.fromisoformat(p.dob),
                phone=p.phone,
                email="",
            )
            session.add(row)
            await session.flush()
            ids[p.key] = row.id
        await session.commit()
        return clinic.id, ids


async def build_world(scenario: Scenario, source: SourceConfig) -> World:
    """Create the scenario's clinics, patients and appointments in the *current* database."""
    from app.main import create_app
    from app.scheduling.runtime import get_clock, get_faults

    now = datetime.fromisoformat(scenario.clock.replace("Z", "+00:00"))
    clock = FixedClock(now)
    faults = ScriptedFaults()
    app = create_app()
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_faults] = lambda: faults
    transport = LossyTransport(ASGITransport(app=app))
    http = AsyncClient(transport=transport, base_url="http://eval.local", timeout=30)

    fx = scenario.fixtures
    primary_patients = [p for p in fx.patients if p.clinic == "primary"]
    other_patients = [p for p in fx.patients if p.clinic == "other"]
    primary_id, primary_ids = await _create_clinic(source.config, source.version, primary_patients)
    other_id: uuid.UUID | None = None
    other_ids: dict[str, uuid.UUID] = {}
    if fx.other_clinic:
        other_cfg = LAKESIDE.model_copy(deep=True)
        other_cfg.details.name = "Evaluation Other Clinic"
        other_id, other_ids = await _create_clinic(other_cfg, 1, other_patients)

    world = World(
        app=app,
        http=http,
        transport=transport,
        faults=faults,
        clock=clock,
        primary_id=primary_id,
        other_id=other_id,
        config=source.config,
        version=source.version,
        variables=compute_variables(source.config, now),
    )
    for tname in ("standard_type", "escalation_type"):
        if tname in world.variables:
            world.variables[tname + "_id"] = str(
                await _type_id(world, "primary", world.variables[tname])
            )
    for p in fx.patients:
        pid = (other_ids if p.clinic == "other" else primary_ids)[p.key]
        world.patients[p.key] = PatientRef(p.key, pid, p.name, p.dob, p.last4, p.clinic)

    for a in fx.appointments:
        start_text = str(resolve(a.start, world))
        type_name = str(resolve(a.type, world))
        patient = world.patients[a.patient]
        type_id = await _type_id(world, patient.clinic, type_name)
        token = await verify_token(world, patient)
        h = {"Authorization": f"Bearer {token}"}
        base = f"/api/clinics/{world.clinic_id(patient.clinic)}"
        pr = await http.post(
            f"{base}/proposals",
            json={"action": "book", "appointment_type_id": str(type_id), "start_at": start_text},
            headers=h,
        )
        if pr.status_code != 201:
            raise FixtureError(f"fixture appointment '{a.key}' was rejected: {pr.text[:200]}")
        pj = pr.json()
        c = await http.post(
            f"{base}/proposals/{pj['id']}/confirm",
            json={"confirmation_token": pj["confirmation_token"]},
            headers=h,
        )
        if c.status_code != 200:
            raise FixtureError(f"fixture appointment '{a.key}' not confirmable: {c.text[:200]}")
        r = await http.post(
            f"{base}/appointments",
            json={
                "proposal_id": pj["id"],
                "appointment_type_id": str(type_id),
                "start_at": start_text,
            },
            headers={**h, "Idempotency-Key": f"fixture-{a.key}-{uuid.uuid4().hex[:8]}"},
        )
        if r.status_code not in (200, 201):
            raise FixtureError(f"fixture appointment '{a.key}' not booked: {r.text[:200]}")
        booked = r.json()
        booked = booked.get("appointment", booked)
        world.appointments[a.key] = uuid.UUID(booked["id"])
        world.appointment_starts[a.key] = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
    world.tokens.clear()  # scenario steps verify for themselves
    transport.calls.clear()
    return world


async def _type_id(world: World, clinic: str, type_name: str) -> uuid.UUID:
    r = await world.http.get(f"/api/clinics/{world.clinic_id(clinic)}/scheduling")
    if r.status_code != 200:
        raise FixtureError(f"cannot read scheduling info: {r.text[:200]}")
    for t in r.json()["appointment_types"]:
        if t["name"].lower() == type_name.lower():
            return uuid.UUID(t["id"])
    raise FixtureError(f"appointment type '{type_name}' not found in the configuration")


async def verify_token(world: World, patient: PatientRef) -> str:
    cached = world.tokens.get(patient.key)
    if cached:
        return cached
    r = await world.http.post(
        f"/api/clinics/{world.clinic_id(patient.clinic)}/patients/{patient.id}/verify",
        json={"date_of_birth": patient.dob, "phone_last4": patient.last4},
    )
    if r.status_code != 200:
        raise FixtureError(f"fixture patient '{patient.key}' could not be verified: {r.text[:200]}")
    token = str(r.json()["authorization_token"])
    world.tokens[patient.key] = token
    return token


async def appointment_total(world: World, *, clinic: str = "primary") -> int:
    from sqlalchemy import func

    from app.models import Appointment

    async with db_session.get_sessionmaker()() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.clinic_id == world.clinic_id(clinic))
            )
            or 0
        )


Resolver = Callable[[Any], Any]
