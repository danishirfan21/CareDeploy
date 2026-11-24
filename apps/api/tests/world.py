"""Test helpers for scheduling: a frozen clock, scripted faults and a seeded two-clinic world."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx import AsyncClient, Response

from app.scheduling.runtime import Faults
from app.seed import PATIENTS

NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)  # Mon 09:00 America/Chicago, 08:00 America/Denver


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


class FakeClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


class ScriptedFaults(Faults):
    """Raise a prepared exception the first N times a named point is reached."""

    def __init__(self) -> None:
        self.plan: dict[str, list[BaseException]] = {}
        self.hits: list[str] = []

    def fail_at(self, point: str, exc: BaseException, times: int = 1) -> None:
        self.plan[point] = [exc] * times

    async def hit(self, point: str) -> None:
        self.hits.append(point)
        queue = self.plan.get(point)
        if queue:
            raise queue.pop(0)


@dataclass
class ClinicInfo:
    id: uuid.UUID
    name: str
    types: dict[str, uuid.UUID]


@dataclass
class PatientInfo:
    id: uuid.UUID
    clinic: ClinicInfo
    name: str
    dob: date
    last4: str


@dataclass
class World:
    client: AsyncClient
    clock: FakeClock
    clinics: dict[str, ClinicInfo] = field(default_factory=dict)
    patients: dict[str, PatientInfo] = field(default_factory=dict)
    _tokens: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def north(self) -> ClinicInfo:
        return self.clinics["Northstar Family Medicine"]

    @property
    def lake(self) -> ClinicInfo:
        return self.clinics["Lakeside Dermatology"]

    def p(self, first_name: str) -> PatientInfo:
        return self.patients[first_name]

    async def token(self, patient: PatientInfo, *, fresh: bool = False) -> str:
        if fresh or patient.id not in self._tokens:
            r = await self.client.post(
                f"/api/clinics/{patient.clinic.id}/patients/{patient.id}/verify",
                json={"date_of_birth": patient.dob.isoformat(), "phone_last4": patient.last4},
            )
            assert r.status_code == 200, r.text
            self._tokens[patient.id] = r.json()["authorization_token"]
        return self._tokens[patient.id]

    async def headers(self, patient: PatientInfo, key: str | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {await self.token(patient)}"}
        if key:
            h["Idempotency-Key"] = key
        return h

    def url(self, clinic: ClinicInfo, path: str) -> str:
        return f"/api/clinics/{clinic.id}{path}"

    async def propose(
        self, patient: PatientInfo, body: dict[str, Any], *, confirm: bool = True
    ) -> Response:
        """Create (and by default confirm) a proposal. Returns the proposal response, with the
        confirmed proposal's fields merged in when confirmed."""
        h = await self.headers(patient)
        r = await self.client.post(self.url(patient.clinic, "/proposals"), json=body, headers=h)
        if r.status_code != 201 or not confirm:
            return r
        pr = r.json()
        c = await self.client.post(
            self.url(patient.clinic, f"/proposals/{pr['id']}/confirm"),
            json={"confirmation_token": pr["confirmation_token"]},
            headers=h,
        )
        assert c.status_code == 200, c.text
        return r

    async def book(
        self,
        patient: PatientInfo,
        type_name: str,
        start: datetime,
        key: str | None = None,
    ) -> Response:
        type_id = str(patient.clinic.types[type_name])
        pr = await self.propose(
            patient,
            {"action": "book", "appointment_type_id": type_id, "start_at": iso(start)},
        )
        if pr.status_code != 201:
            return pr
        return await self.client.post(
            self.url(patient.clinic, "/appointments"),
            json={
                "proposal_id": pr.json()["id"],
                "appointment_type_id": type_id,
                "start_at": iso(start),
            },
            headers=await self.headers(patient, key or f"key-{uuid.uuid4()}"),
        )

    async def reschedule(
        self, patient: PatientInfo, appointment_id: str, new_start: datetime, key: str | None = None
    ) -> Response:
        pr = await self.propose(
            patient,
            {"action": "reschedule", "appointment_id": appointment_id, "start_at": iso(new_start)},
        )
        if pr.status_code != 201:
            return pr
        return await self.client.post(
            self.url(patient.clinic, f"/appointments/{appointment_id}/reschedule"),
            json={"proposal_id": pr.json()["id"], "new_start_at": iso(new_start)},
            headers=await self.headers(patient, key or f"key-{uuid.uuid4()}"),
        )

    async def cancel(
        self,
        patient: PatientInfo,
        appointment_id: str,
        key: str | None = None,
        reason: str | None = None,
    ) -> Response:
        body: dict[str, Any] = {"action": "cancel", "appointment_id": appointment_id}
        if reason:
            body["reason"] = reason
        pr = await self.propose(patient, body)
        if pr.status_code != 201:
            return pr
        req: dict[str, Any] = {"proposal_id": pr.json()["id"]}
        if reason:
            req["reason"] = reason
        return await self.client.post(
            self.url(patient.clinic, f"/appointments/{appointment_id}/cancel"),
            json=req,
            headers=await self.headers(patient, key or f"key-{uuid.uuid4()}"),
        )

    async def appointments(self, patient: PatientInfo, **params: Any) -> list[dict[str, Any]]:
        r = await self.client.get(
            self.url(patient.clinic, f"/patients/{patient.id}/appointments"),
            params=params,
            headers=await self.headers(patient),
        )
        assert r.status_code == 200, r.text
        return list(r.json())


def patient_creds() -> dict[str, tuple[str, date, str]]:
    out = {}
    for clinic_name, people in PATIENTS.items():
        for name, dob, phone, _email in people:
            out[name.split()[0]] = (clinic_name, dob, phone[-4:])
    return out
