"""Clinic and configuration API contracts.

Mirrored by hand in apps/web/src/lib/api/types.ts.
"""

import re
import uuid
from datetime import datetime, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator

HHMM = Annotated[time, PlainSerializer(lambda t: t.strftime("%H:%M"), return_type=str)]

Intent = Literal[
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "clinic_information",
    "speak_to_human",
]
Capability = Literal[
    "check_availability",
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "escalate_to_human",
]
INTENT_REQUIRES_CAPABILITY: dict[str, str] = {
    "book_appointment": "book_appointment",
    "cancel_appointment": "cancel_appointment",
    "reschedule_appointment": "reschedule_appointment",
    "speak_to_human": "escalate_to_human",
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClinicDetails(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    specialty: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=64)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=200)

    @field_validator("name", "specialty", "location", "phone", "email", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError) as e:
            raise ValueError(f"Unknown time zone '{v}'") from e
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if v and not _EMAIL.match(v):
            raise ValueError("Invalid email address")
        return v


class ClinicUpdate(BaseModel):
    """PATCH body; omitted fields are unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    specialty: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)


class ClinicRead(ClinicDetails):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    latest_version: int | None = None


class OperatingHoursEntry(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday … 6 = Sunday")
    opens: HHMM
    closes: HHMM

    @model_validator(mode="after")
    def _order(self) -> "OperatingHoursEntry":
        if self.opens >= self.closes:
            raise ValueError("Opening time must be before closing time")
        return self


class AppointmentTypeEntry(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(ge=5, le=480)
    requires_human_escalation: bool = False
    constraints: str = Field(default="", max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class SchedulingPolicyConfig(BaseModel):
    min_notice_hours: int = Field(default=2, ge=0, le=720)
    max_advance_days: int = Field(default=60, ge=1, le=365)
    same_day_booking: bool = True
    cancellation_window_hours: int = Field(default=24, ge=0, le=336)
    cancellation_notes: str = Field(default="", max_length=1000)
    reschedule_window_hours: int = Field(default=24, ge=0, le=336)
    max_reschedules: int = Field(default=2, ge=0, le=10)


class AgentBehavior(BaseModel):
    agent_name: str = Field(default="", max_length=80)
    greeting: str = Field(default="", max_length=500)
    supported_intents: list[Intent] = Field(default_factory=list)
    escalation_instructions: str = Field(default="", max_length=2000)
    allowed_capabilities: list[Capability] = Field(default_factory=list)

    @field_validator("supported_intents", "allowed_capabilities")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("Duplicate entries")
        return v


class ClinicConfig(BaseModel):
    """Everything an editable clinic configuration (draft) or published snapshot contains."""

    details: ClinicDetails
    hours: list[OperatingHoursEntry] = Field(default_factory=list)
    appointment_types: list[AppointmentTypeEntry] = Field(default_factory=list)
    policy: SchedulingPolicyConfig = Field(default_factory=SchedulingPolicyConfig)
    agent: AgentBehavior = Field(default_factory=AgentBehavior)

    @model_validator(mode="after")
    def _unique(self) -> "ClinicConfig":
        days = [h.weekday for h in self.hours]
        if len(set(days)) != len(days):
            raise ValueError("Each weekday may appear only once in operating hours")
        names = [t.name.lower() for t in self.appointment_types]
        if len(set(names)) != len(names):
            raise ValueError("Appointment type names must be unique")
        return self


class ConfigResponse(BaseModel):
    clinic_id: uuid.UUID
    config: ClinicConfig
    latest_version: int | None
    has_unpublished_changes: bool


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    section: Literal["details", "hours", "services", "policy", "agent"]
    message: str


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue]


class ConfigVersionSummary(BaseModel):
    version: int
    published_at: datetime


class ConfigVersionRead(ConfigVersionSummary):
    clinic_id: uuid.UUID
    config: ClinicConfig


class ErrorResponse(BaseModel):
    detail: str
