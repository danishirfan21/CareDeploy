"""Thin typed client over the M2 scheduling API. It adds no scheduling rules: every decision
(availability, policy, conflicts, proposal binding, idempotency) is the backend's.

Responses are classified so callers never mistake a transport failure for a rejection:

* ``ok``          - 2xx.
* ``rejected``    - the backend answered with a definitive 4xx; nothing was changed.
* ``unavailable`` - timeout, connection error, 5xx/503/429 or ``operation_in_progress``. For a
  state-changing call the outcome is *unknown* until reconciled.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

Kind = Literal["ok", "rejected", "unavailable"]


@dataclass
class ApiResult:
    kind: Kind
    status: int | None
    body: Any = None
    code: str = ""
    message: str = ""
    operation_id: str | None = None
    replay: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


_UNKNOWN_CODES = {"operation_in_progress", "outcome_unknown", "dependency_unavailable"}


def classify(resp: httpx.Response) -> ApiResult:
    op_id = resp.headers.get("X-Operation-Id")
    replay = resp.headers.get("Idempotent-Replay", "").lower() == "true"
    try:
        body: Any = resp.json()
    except ValueError:
        body = None
    if resp.is_success:
        return ApiResult("ok", resp.status_code, body, operation_id=op_id, replay=replay)
    err = body.get("error", {}) if isinstance(body, dict) else {}
    code = str(err.get("code") or "")
    msg = str(err.get("message") or "")
    if not code and isinstance(body, dict) and "detail" in body:
        code, msg = "http_error", str(body["detail"])[:200]
    details = err.get("details") if isinstance(err.get("details"), dict) else {}
    uncertain = resp.status_code >= 500 or resp.status_code == 429 or code in _UNKNOWN_CODES
    return ApiResult(
        "unavailable" if uncertain else "rejected",
        resp.status_code,
        body,
        code or f"http_{resp.status_code}",
        msg or f"HTTP {resp.status_code}",
        operation_id=op_id,
        details=details or {},
    )


class SchedulingClient:
    """All calls are scoped to one clinic; the patient bearer token is passed per call."""

    def __init__(self, http: httpx.AsyncClient, clinic_id: uuid.UUID) -> None:
        self._http = http
        self._base = f"/api/clinics/{clinic_id}"

    async def _send(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        key: str | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> ApiResult:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if key:
            headers["Idempotency-Key"] = key
        try:
            resp = await self._http.request(
                method, f"{self._base}{path}", headers=headers, json=json, params=params
            )
        except httpx.TimeoutException:
            return ApiResult("unavailable", None, code="timeout", message="The request timed out.")
        except httpx.TransportError as e:
            return ApiResult("unavailable", None, code="connection_error", message=type(e).__name__)
        return classify(resp)

    async def scheduling_info(self) -> ApiResult:
        return await self._send("GET", "/scheduling")

    async def availability(
        self, type_id: uuid.UUID, date_from: str, date_to: str | None, limit: int
    ) -> ApiResult:
        params: dict[str, Any] = {
            "appointment_type_id": str(type_id),
            "date_from": date_from,
            "limit": limit,
        }
        if date_to:
            params["date_to"] = date_to
        return await self._send("GET", "/availability", params=params)

    async def find_patients(self, name: str) -> ApiResult:
        return await self._send("GET", "/patients", params={"name": name})

    async def verify(self, patient_id: uuid.UUID, dob: str, last4: str) -> ApiResult:
        return await self._send(
            "POST",
            f"/patients/{patient_id}/verify",
            json={"date_of_birth": dob, "phone_last4": last4},
        )

    async def appointments(self, patient_id: uuid.UUID, token: str) -> ApiResult:
        return await self._send("GET", f"/patients/{patient_id}/appointments", token=token)

    async def propose(self, token: str, body: dict[str, Any]) -> ApiResult:
        return await self._send("POST", "/proposals", token=token, json=body)

    async def confirm_proposal(
        self, token: str, proposal_id: uuid.UUID, confirmation_token: str
    ) -> ApiResult:
        return await self._send(
            "POST",
            f"/proposals/{proposal_id}/confirm",
            token=token,
            json={"confirmation_token": confirmation_token},
        )

    async def reject_proposal(self, token: str, proposal_id: uuid.UUID) -> ApiResult:
        return await self._send("POST", f"/proposals/{proposal_id}/reject", token=token)

    async def execute(
        self, token: str, key: str, action: str, body: dict[str, Any], appointment_id: str | None
    ) -> ApiResult:
        path = {
            "book": "/appointments",
            "reschedule": f"/appointments/{appointment_id}/reschedule",
            "cancel": f"/appointments/{appointment_id}/cancel",
        }[action]
        return await self._send("POST", path, token=token, key=key, json=body)

    async def operation_by_key(self, token: str, key: str) -> ApiResult:
        return await self._send("GET", "/operations", token=token, params={"idempotency_key": key})
