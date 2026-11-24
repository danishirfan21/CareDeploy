"""Simulated deployments (M5).

A deployment selects which immutable published configuration version new voice sessions use. It
is a pointer inside CareDeploy, not infrastructure provisioning. One row per activation; a
rollback is a new row, never an edit of an old one. Database rules (see migration 0006):

* at most one `active` row per clinic and environment (partial unique index),
* the version must belong to the same clinic (composite foreign key),
* only the active flag of a row can change, and a superseded row is immutable,
* `deployment_events` is append-only.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ENVIRONMENT = "simulated_live"
ENVIRONMENT_LABEL = "Simulated Live"


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "config_version"],
            ["config_versions.clinic_id", "config_versions.version"],
            ondelete="RESTRICT",
            name="fk_deployments_clinic_version",
        ),
        CheckConstraint("environment IN ('simulated_live')", name="ck_deployments_environment"),
        CheckConstraint("status IN ('active','superseded')", name="ck_deployments_status"),
        CheckConstraint("action IN ('seed','promote','rollback')", name="ck_deployments_action"),
        CheckConstraint(
            "(status = 'active') = (deactivated_at IS NULL)", name="ck_deployments_active_pointer"
        ),
        Index("ix_deployments_clinic_activated", "clinic_id", "activated_at"),
        Index(
            "uq_deployments_one_active",
            "clinic_id",
            "environment",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_deployments_idempotency",
            "clinic_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="RESTRICT"))
    config_version: Mapped[int] = mapped_column(Integer)
    environment: Mapped[str] = mapped_column(String(30), default=ENVIRONMENT)
    status: Mapped[str] = mapped_column(String(20), default="active")
    action: Mapped[str] = mapped_column(String(20))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(80))
    readiness: Mapped[dict[str, Any]] = mapped_column(JSONB)
    readiness_level: Mapped[str] = mapped_column(String(30))
    restored_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deployments.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeploymentEvent(Base):
    __tablename__ = "deployment_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('seeded','promoted','rolled_back')", name="ck_deployment_events_kind"
        ),
        Index("ix_deployment_events_clinic_time", "clinic_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="RESTRICT"))
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deployments.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(20))
    from_version: Mapped[int | None] = mapped_column(Integer)
    to_version: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(80))
    readiness: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
