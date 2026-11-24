import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _clinic_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("clinics.id", ondelete="RESTRICT"), index=True)


class OperatingHours(Base):
    __tablename__ = "operating_hours"
    __table_args__ = (
        UniqueConstraint("clinic_id", "weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("opens < closes", name="opens_before_closes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = _clinic_fk()
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    opens: Mapped[time] = mapped_column(Time)
    closes: Mapped[time] = mapped_column(Time)


class AppointmentType(Base):
    __tablename__ = "appointment_types"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_appointment_types_clinic_id_id"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        # Names are unique among *active* types; archived types keep their identity for history.
        Index(
            "uq_appointment_types_active_name",
            "clinic_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = _clinic_fk()
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(100))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    requires_human_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    constraints: Mapped[str] = mapped_column(Text, default="")
    # Types are never hard-deleted: removing one from the draft archives it, so published
    # versions and appointments keep a valid, stable reference.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SchedulingPolicy(Base):
    __tablename__ = "scheduling_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"), unique=True
    )
    min_notice_hours: Mapped[int] = mapped_column(Integer)
    max_advance_days: Mapped[int] = mapped_column(Integer)
    same_day_booking: Mapped[bool] = mapped_column(Boolean)
    cancellation_window_hours: Mapped[int] = mapped_column(Integer)
    cancellation_notes: Mapped[str] = mapped_column(Text, default="")
    reschedule_window_hours: Mapped[int] = mapped_column(Integer)
    max_reschedules: Mapped[int] = mapped_column(Integer)


class AgentConfig(Base):
    """Draft agent behavior for a clinic (one row per clinic)."""

    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"), unique=True
    )
    agent_name: Mapped[str] = mapped_column(String(80), default="")
    greeting: Mapped[str] = mapped_column(Text, default="")
    supported_intents: Mapped[list[str]] = mapped_column(JSONB, default=list)
    escalation_instructions: Mapped[str] = mapped_column(Text, default="")
    allowed_capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list)


class ConfigVersion(Base):
    """Immutable published snapshot. UPDATE/DELETE are rejected by a database trigger."""

    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("clinic_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = _clinic_fk()
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
