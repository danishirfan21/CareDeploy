"""Scheduling domain tables (M2). Every row is clinic-scoped; parent references are composite
(clinic_id, id) foreign keys so the database itself rejects cross-clinic links."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CLINIC_FK = "clinics.id"

APPOINTMENT_STATUSES = ("scheduled", "completed", "cancelled")
OPERATION_STATUSES = ("processing", "succeeded", "failed", "aborted")
PROPOSAL_STATUSES = ("pending", "confirmed", "executed", "rejected")


class Patient(Base):
    """Synthetic patient. Demo verification only; see docs/authorization.md."""

    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_patients_clinic_id_id"),
        ForeignKeyConstraint(
            ["clinic_id"], [CLINIC_FK], ondelete="RESTRICT", name="fk_patients_clinic_id_clinics"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(40))
    email: Mapped[str] = mapped_column(String(200), default="")
    verification_method: Mapped[str] = mapped_column(String(40), default="dob_phone_last4")
    failed_verification_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PatientAuthorization(Base):
    """Server-issued, expiring authorization. Only the SHA-256 of the token is stored."""

    __tablename__ = "patient_authorizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_patient_authorizations_patient",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_appointments_clinic_id_id"),
        Index("ix_appointments_patient_start", "clinic_id", "patient_id", "start_at"),
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_appointments_patient",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_type_id"],
            ["appointment_types.clinic_id", "appointment_types.id"],
            ondelete="RESTRICT",
            name="fk_appointments_appointment_type",
        ),
        CheckConstraint("end_at > start_at", name="ck_appointments_end_after_start"),
        CheckConstraint(
            "status IN ('scheduled','completed','cancelled')", name="ck_appointments_status"
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="ck_appointments_cancelled_consistent",
        ),
        # The no-overlap exclusion constraint is created in migration 0003 (needs btree_gist).
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column()
    appointment_type_id: Mapped[uuid.UUID] = mapped_column()
    # Frozen at booking time so later configuration edits cannot rewrite history.
    type_name: Mapped[str] = mapped_column(String(100))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    config_version: Mapped[int] = mapped_column(Integer)
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppointmentEvent(Base):
    """Append-only audit trail (UPDATE/DELETE rejected by trigger)."""

    __tablename__ = "appointment_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointments.clinic_id", "appointments.id"],
            ondelete="RESTRICT",
            name="fk_appointment_events_appointment",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(index=True)
    appointment_id: Mapped[uuid.UUID] = mapped_column(index=True)
    operation_id: Mapped[uuid.UUID | None] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    config_version: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint("clinic_id", "idempotency_key", name="uq_operations_clinic_id_key"),
        UniqueConstraint("clinic_id", "id", name="uq_operations_clinic_id_id"),
        CheckConstraint(
            "status IN ('processing','succeeded','failed','aborted')", name="ck_operations_status"
        ),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointments.clinic_id", "appointments.id"],
            ondelete="RESTRICT",
            name="fk_operations_appointment",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_operations_patient",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column()
    operation_type: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    appointment_id: Mapped[uuid.UUID | None] = mapped_column()
    proposal_id: Mapped[uuid.UUID | None] = mapped_column()
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Proposal(Base):
    """A server-issued proposed operation. Confirmation is bound to `payload_hash`."""

    __tablename__ = "operation_proposals"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_operation_proposals_clinic_id_id"),
        CheckConstraint(
            "status IN ('pending','confirmed','executed','rejected')",
            name="ck_operation_proposals_status",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_operation_proposals_patient",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column()
    action: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_operation_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "Appointment",
    "AppointmentEvent",
    "Operation",
    "Patient",
    "PatientAuthorization",
    "Proposal",
]
