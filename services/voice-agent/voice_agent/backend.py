"""Authenticated worker channel to the CareDeploy backend."""

import uuid
from typing import Any

import httpx

from voice_agent.contracts import CallContext


class BackendError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code = status, code


class BackendClient:
    """Speaks only to ``/api/voice/worker/...``; the worker secret is attached to every call."""

    def __init__(self, http: httpx.AsyncClient, session_id: uuid.UUID, secret: str) -> None:
        self._http = http
        self._base = f"/api/voice/worker/sessions/{session_id}"
        self._headers = {"X-Voice-Worker-Secret": secret}

    async def _call(self, method: str, path: str, json: Any = None) -> Any:
        resp = await self._http.request(
            method, f"{self._base}{path}", json=json, headers=self._headers
        )
        if resp.is_success:
            return resp.json()
        detail: Any = {}
        try:
            detail = resp.json().get("detail", {})
        except ValueError:
            pass
        if isinstance(detail, dict):
            raise BackendError(
                resp.status_code, str(detail.get("code", "")), str(detail.get("message", ""))
            )
        raise BackendError(resp.status_code, "", str(detail))

    async def claim(self, room_name: str) -> CallContext:
        return CallContext.model_validate(
            await self._call("POST", "/claim", {"room_name": room_name})
        )

    async def send_events(self, events: list[dict[str, Any]]) -> None:
        await self._call("POST", "/events", {"events": events})

    async def send_state(self, state: dict[str, Any]) -> None:
        await self._call("PUT", "/state", {"state": state})

    async def complete(self, body: dict[str, Any]) -> dict[str, Any]:
        out = await self._call("POST", "/complete", body)
        return dict(out)
