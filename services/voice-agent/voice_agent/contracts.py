"""Typed views of what the backend sends the worker. Mirrors `apps/api/app/schemas/voice.py` and
`schemas/clinic.py` (kept in sync by hand; the integration tests parse real backend responses)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClinicDetails(BaseModel):
    name: str
    specialty: str
    location: str
    timezone: str
    phone: str = ""
    email: str = ""


class HoursEntry(BaseModel):
    weekday: int
    opens: str
    closes: str


class AppointmentTypeInfo(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int
    requires_human_escalation: bool = False
    constraints: str = ""


class PolicyInfo(BaseModel):
    min_notice_hours: int
    max_advance_days: int
    same_day_booking: bool
    cancellation_window_hours: int
    cancellation_notes: str = ""
    reschedule_window_hours: int
    max_reschedules: int


class AgentInfo(BaseModel):
    agent_name: str = ""
    greeting: str = ""
    supported_intents: list[str] = Field(default_factory=list)
    escalation_instructions: str = ""
    allowed_capabilities: list[str] = Field(default_factory=list)


class ClinicConfig(BaseModel):
    details: ClinicDetails
    hours: list[HoursEntry] = Field(default_factory=list)
    appointment_types: list[AppointmentTypeInfo] = Field(default_factory=list)
    policy: PolicyInfo
    agent: AgentInfo


class CallContext(BaseModel):
    """The configuration a call runs with. Frozen: nothing mutates it for the call's lifetime."""

    model_config = ConfigDict(frozen=True)

    call_session_id: uuid.UUID
    clinic_id: uuid.UUID
    config_version: int
    room_name: str
    created_at: datetime
    config: ClinicConfig

    def type_by_id(self, type_id: uuid.UUID) -> AppointmentTypeInfo | None:
        return next((t for t in self.config.appointment_types if t.id == type_id), None)

    def can(self, capability: str) -> bool:
        return capability in self.config.agent.allowed_capabilities

    def supports(self, intent: str) -> bool:
        return intent in self.config.agent.supported_intents
