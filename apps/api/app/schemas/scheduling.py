"""Scheduling API contracts (M2). Strict: unknown fields are rejected on requests."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

AppointmentStatus = Literal["scheduled", "completed", "cancelled"]
Action = Literal["book", "reschedule", "cancel"]
OperationStatus = Literal["processing", "succeeded", "failed", "aborted"]
ProposalStatus = Literal["pending", "confirmed", "executed", "rejected", "expired"]


def _aware_utc(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("Timestamp must include a UTC offset, e.g. 2026-03-02T15:00:00Z")
    return v.astimezone(UTC)


AwareDatetime = Annotated[datetime, AfterValidator(_aware_utc)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- patients & verification -------------------------------------------------------------
class PatientSummary(BaseModel):
    id: uuid.UUID
    full_name: str


class VerifyRequest(Strict):
    date_of_birth: date
    phone_last4: str = Field(pattern=r"^\d{4}$")


class VerifyResponse(BaseModel):
    patient_id: uuid.UUID
    clinic_id: uuid.UUID
    authorization_token: str = Field(description="Bearer token; shown once, expires.")
    expires_at: datetime
    simulated: bool = True


# ---- published scheduling configuration & availability ----------------------------------
class SchedulableType(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int
    requires_human_escalation: bool


class SchedulingInfo(BaseModel):
    clinic_id: uuid.UUID
    timezone: str
    config_version: int
    appointment_types: list[SchedulableType]


class SlotRead(BaseModel):
    start_at: datetime = Field(description="UTC instant")
    end_at: datetime
    start_local: str = Field(description="ISO-8601 with the clinic's UTC offset")
    end_local: str


class AvailabilityResponse(BaseModel):
    clinic_id: uuid.UUID
    appointment_type_id: uuid.UUID
    timezone: str
    config_version: int
    date_from: date
    date_to: date
    requires_human_escalation: bool
    truncated: bool
    slots: list[SlotRead]
    informational: bool = Field(
        default=True, description="Availability is revalidated transactionally when booking."
    )


# ---- appointments -----------------------------------------------------------------------
class AppointmentRead(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    appointment_type_id: uuid.UUID
    type_name: str
    duration_minutes: int
    timezone: str
    start_at: datetime
    end_at: datetime
    start_local: str
    end_local: str
    status: AppointmentStatus
    config_version: int
    reschedule_count: int
    row_version: int
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class AppointmentEventRead(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    operation_id: uuid.UUID | None
    event_type: str
    from_status: str | None
    to_status: str
    config_version: int | None
    details: dict[str, object]
    created_at: datetime


# ---- proposals (confirmation) -----------------------------------------------------------
class ProposalCreate(Strict):
    action: Action
    appointment_type_id: uuid.UUID | None = None
    appointment_id: uuid.UUID | None = None
    start_at: AwareDatetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class ProposalRead(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    action: Action
    status: ProposalStatus
    summary: str
    details: dict[str, object]
    expires_at: datetime
    confirmation_token: str | None = Field(
        default=None, description="Returned once, when the proposal is created."
    )


class ConfirmRequest(Strict):
    confirmation_token: str = Field(min_length=16, max_length=200)


# ---- operations -------------------------------------------------------------------------
class BookRequest(Strict):
    proposal_id: uuid.UUID
    appointment_type_id: uuid.UUID
    start_at: AwareDatetime


class RescheduleRequest(Strict):
    proposal_id: uuid.UUID
    new_start_at: AwareDatetime


class CancelRequest(Strict):
    proposal_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=500)


class OperationResult(BaseModel):
    """Stored and replayed verbatim for idempotent retries."""

    operation_id: uuid.UUID
    operation_type: Literal["book", "reschedule", "cancel"]
    appointment: AppointmentRead


class OperationRead(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    operation_type: str
    idempotency_key: str
    status: OperationStatus
    appointment_id: uuid.UUID | None
    proposal_id: uuid.UUID | None
    http_status: int | None
    outcome: dict[str, object] | None
    attempts: int
    created_at: datetime
    completed_at: datetime | None
    resolved: bool = Field(
        description="True once the outcome is final (succeeded or failed). "
        "'processing' and 'aborted' are not final."
    )
