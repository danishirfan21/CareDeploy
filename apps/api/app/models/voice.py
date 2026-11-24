"""Voice call sessions (M3). One row per call; events are reported by the worker and de-duplicated.

No audio is stored. Transcript events hold finalized text only; tool events hold redacted
arguments (never date of birth, phone digits or tokens).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CALL_STATUSES = ("created", "active", "completed", "failed", "abandoned")
CALL_OUTCOMES = (
    "appointment_booked",
    "appointment_rescheduled",
    "appointment_cancelled",
    "information_provided",
    "escalated",
    "no_action",
    "failed",
)
OUTCOME_CLASSES = ("completed", "escalated", "failed", "abandoned", "interrupted", "unknown")
EVENT_KINDS = ("transcript", "tool", "state", "operation", "error", "system")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CallSession(Base):
    __tablename__ = "call_sessions"
    __table_args__ = (
        CheckConstraint(_in("status", CALL_STATUSES), name="ck_call_sessions_status"),
        CheckConstraint(
            "outcome IS NULL OR " + _in("outcome", CALL_OUTCOMES), name="ck_call_sessions_outcome"
        ),
        CheckConstraint(
            "outcome_class IS NULL OR " + _in("outcome_class", OUTCOME_CLASSES),
            name="ck_call_sessions_outcome_class",
        ),
        Index("ix_call_sessions_clinic_created", "clinic_id", "created_at"),
        Index("ix_call_sessions_clinic_class", "clinic_id", "outcome_class"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="RESTRICT"))
    config_version: Mapped[int] = mapped_column(Integer)
    room_name: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="created")
    outcome: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str | None] = mapped_column(Text)
    dev_actor: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    ended_by: Mapped[str | None] = mapped_column(String(20))
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    operation_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    provider_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    live_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    live_state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # M5: the deployment that selected this session's version (null for sessions created before
    # deployments existed) and the verified, domain-level classification (null until the call is
    # over). `outcome` above stays the agent's own report; `outcome_class` is what the ledger shows.
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deployments.id", name="fk_call_sessions_deployment")
    )
    outcome_class: Mapped[str | None] = mapped_column(String(20))
    task_type: Mapped[str | None] = mapped_column(String(30))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallEvent(Base):
    __tablename__ = "call_events"
    __table_args__ = (
        UniqueConstraint("call_session_id", "event_id", name="uq_call_events_session_event"),
        CheckConstraint(_in("kind", EVENT_KINDS), name="ck_call_events_kind"),
        Index("ix_call_events_session_seq", "call_session_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    call_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("call_sessions.id", ondelete="CASCADE")
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="RESTRICT"))
    event_id: Mapped[str] = mapped_column(String(120))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
