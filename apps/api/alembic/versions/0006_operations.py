"""deployments, deployment audit events and call classification (additive)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB
OUTCOME_CLASSES = "'completed','escalated','failed','abandoned','interrupted','unknown'"


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "clinic_id", sa.Uuid(), sa.ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
        sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("readiness", JSONB(), nullable=False),
        sa.Column("readiness_level", sa.String(30), nullable=False),
        sa.Column("restored_from_id", sa.Uuid(), sa.ForeignKey("deployments.id")),
        sa.Column("idempotency_key", sa.String(80)),
        sa.Column("request_hash", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # A deployment can only point at a version that belongs to the same clinic.
        sa.ForeignKeyConstraint(
            ["clinic_id", "config_version"],
            ["config_versions.clinic_id", "config_versions.version"],
            ondelete="RESTRICT",
            name="fk_deployments_clinic_version",
        ),
        sa.CheckConstraint("environment IN ('simulated_live')", name="ck_deployments_environment"),
        sa.CheckConstraint("status IN ('active','superseded')", name="ck_deployments_status"),
        sa.CheckConstraint("action IN ('seed','promote','rollback')", name="ck_deployments_action"),
        sa.CheckConstraint(
            "(status = 'active') = (deactivated_at IS NULL)", name="ck_deployments_active_pointer"
        ),
    )
    op.create_index("ix_deployments_clinic_activated", "deployments", ["clinic_id", "activated_at"])
    # The active pointer can never be ambiguous: one active row per clinic and environment.
    op.create_index(
        "uq_deployments_one_active",
        "deployments",
        ["clinic_id", "environment"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_deployments_idempotency",
        "deployments",
        ["clinic_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "deployment_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "clinic_id", sa.Uuid(), sa.ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "deployment_id",
            sa.Uuid(),
            sa.ForeignKey("deployments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("from_version", sa.Integer()),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("readiness", JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('seeded','promoted','rolled_back')", name="ck_deployment_events_kind"
        ),
    )
    op.create_index(
        "ix_deployment_events_clinic_time", "deployment_events", ["clinic_id", "occurred_at"]
    )

    op.add_column("call_sessions", sa.Column("deployment_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_call_sessions_deployment", "call_sessions", "deployments", ["deployment_id"], ["id"]
    )
    op.add_column("call_sessions", sa.Column("outcome_class", sa.String(20)))
    op.add_column("call_sessions", sa.Column("task_type", sa.String(30)))
    op.add_column("call_sessions", sa.Column("classified_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_call_sessions_outcome_class",
        "call_sessions",
        f"outcome_class IS NULL OR outcome_class IN ({OUTCOME_CLASSES})",
    )
    op.create_index(
        "ix_call_sessions_clinic_class", "call_sessions", ["clinic_id", "outcome_class"]
    )

    op.execute(
        """
        CREATE FUNCTION deployments_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'deployments cannot be deleted';
          END IF;
          IF NEW.id IS DISTINCT FROM OLD.id
             OR NEW.clinic_id IS DISTINCT FROM OLD.clinic_id
             OR NEW.config_version IS DISTINCT FROM OLD.config_version
             OR NEW.environment IS DISTINCT FROM OLD.environment
             OR NEW.action IS DISTINCT FROM OLD.action
             OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
             OR NEW.actor IS DISTINCT FROM OLD.actor
             OR NEW.readiness IS DISTINCT FROM OLD.readiness
             OR NEW.restored_from_id IS DISTINCT FROM OLD.restored_from_id THEN
            RAISE EXCEPTION 'only the active flag of a deployment can change';
          END IF;
          IF OLD.status = 'superseded' THEN
            RAISE EXCEPTION 'a superseded deployment is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER deployments_guard BEFORE UPDATE OR DELETE ON deployments
        FOR EACH ROW EXECUTE FUNCTION deployments_guard()
        """
    )
    op.execute(
        """
        CREATE FUNCTION deployment_events_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'deployment_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER deployment_events_append_only BEFORE UPDATE OR DELETE ON deployment_events
        FOR EACH ROW EXECUTE FUNCTION deployment_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS deployment_events_append_only ON deployment_events")
    op.execute("DROP FUNCTION IF EXISTS deployment_events_append_only()")
    op.execute("DROP TRIGGER IF EXISTS deployments_guard ON deployments")
    op.execute("DROP FUNCTION IF EXISTS deployments_guard()")
    op.drop_index("ix_call_sessions_clinic_class", table_name="call_sessions")
    op.drop_constraint("ck_call_sessions_outcome_class", "call_sessions", type_="check")
    op.drop_column("call_sessions", "classified_at")
    op.drop_column("call_sessions", "task_type")
    op.drop_column("call_sessions", "outcome_class")
    op.drop_constraint("fk_call_sessions_deployment", "call_sessions", type_="foreignkey")
    op.drop_column("call_sessions", "deployment_id")
    op.drop_table("deployment_events")
    op.drop_table("deployments")
