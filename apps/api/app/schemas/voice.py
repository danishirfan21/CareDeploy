"""Voice session API contracts (M3). Mirrored by hand in apps/web/src/lib/api/types.ts and in
services/voice-agent/voice_agent/contracts.py."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.clinic import ClinicConfig

CallStatus = Literal["created", "active", "completed", "failed", "abandoned"]
CallOutcome = Literal[
    "appointment_booked",
    "appointment_rescheduled",
    "appointment_cancelled",
    "information_provided",
    "escalated",
    "no_action",
    "failed",
]
EventKind = Literal["transcript", "tool", "state", "operation", "error", "system"]


class VoiceSessionCreated(BaseModel):
    """Returned to the browser once. `token` is a short-lived LiveKit participant token scoped to
    one room; it carries no API secret and cannot be used for any other room."""

    call_session_id: uuid.UUID
    clinic_id: uuid.UUID
    clinic_name: str
    agent_name: str
    config_version: int
    room_name: str
    livekit_url: str
    token: str
    token_expires_at: datetime
    created_at: datetime
    dev_actor: str


class VoiceSessionRead(BaseModel):
    call_session_id: uuid.UUID
    clinic_id: uuid.UUID
    clinic_name: str
    agent_name: str
    config_version: int
    status: CallStatus
    outcome: CallOutcome | None
    summary: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: float | None
    ended_by: str | None
    escalation_reason: str | None
    error: str | None
    operation_ids: list[str]
    metrics: dict[str, Any]
    provider_usage: dict[str, Any]
    live_state: dict[str, Any]
    dev_actor: str


class CallEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    seq: int = Field(ge=0)
    kind: EventKind
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class CallEventRead(CallEventIn):
    received_at: datetime


class CallEventsIn(BaseModel):
    events: list[CallEventIn] = Field(min_length=1, max_length=100)


class CallEventsAccepted(BaseModel):
    accepted: int
    duplicates: int


class CallEventsOut(BaseModel):
    events: list[CallEventRead]


class WorkerClaim(BaseModel):
    room_name: str = Field(min_length=1, max_length=120)


class WorkerContext(BaseModel):
    """The frozen configuration a call runs with. Resolved from the immutable published version
    recorded on the session, never from a mutable draft or from room metadata."""

    call_session_id: uuid.UUID
    clinic_id: uuid.UUID
    config_version: int
    room_name: str
    created_at: datetime
    config: ClinicConfig


class LiveStateIn(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)


class CallComplete(BaseModel):
    status: Literal["completed", "failed", "abandoned"] = "completed"
    outcome: CallOutcome | None = None
    summary: str | None = Field(default=None, max_length=1000)
    escalation_reason: str | None = Field(default=None, max_length=1000)
    error: str | None = Field(default=None, max_length=1000)
    operation_ids: list[str] = Field(default_factory=list, max_length=50)
    metrics: dict[str, Any] = Field(default_factory=dict)
    provider_usage: dict[str, Any] = Field(default_factory=dict)


class EndRequest(BaseModel):
    reason: Literal["user_ended", "connection_failed", "page_closed", "microphone_denied"] = (
        "user_ended"
    )
