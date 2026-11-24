"""clinic details, schedules, services, policies, agent drafts, immutable versions

Additive: extends clinics, adds new tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _clinic_fk(table: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "clinic_id",
        sa.Uuid(),
        sa.ForeignKey(
            "clinics.id", ondelete="RESTRICT", name=op.f(f"fk_{table}_clinic_id_clinics")
        ),
        nullable=False,
    )


def upgrade() -> None:
    for col, length in [
        ("specialty", 100),
        ("location", 200),
        ("timezone", 64),
        ("phone", 40),
        ("email", 200),
    ]:
        op.add_column(
            "clinics", sa.Column(col, sa.String(length), nullable=False, server_default="")
        )
    op.add_column(
        "clinics",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_unique_constraint(op.f("uq_clinics_name"), "clinics", ["name"])

    op.create_table(
        "operating_hours",
        sa.Column("id", sa.Uuid(), nullable=False),
        _clinic_fk("operating_hours"),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("opens", sa.Time(), nullable=False),
        sa.Column("closes", sa.Time(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operating_hours")),
        sa.UniqueConstraint("clinic_id", "weekday", name=op.f("uq_operating_hours_clinic_id")),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_operating_hours_weekday_range")
        ),
        sa.CheckConstraint("opens < closes", name=op.f("ck_operating_hours_opens_before_closes")),
    )
    op.create_index(op.f("ix_operating_hours_clinic_id"), "operating_hours", ["clinic_id"])

    op.create_table(
        "appointment_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        _clinic_fk("appointment_types"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("requires_human_escalation", sa.Boolean(), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_types")),
        sa.UniqueConstraint("clinic_id", "name", name=op.f("uq_appointment_types_clinic_id")),
        sa.CheckConstraint(
            "duration_minutes > 0", name=op.f("ck_appointment_types_duration_positive")
        ),
    )
    op.create_index(op.f("ix_appointment_types_clinic_id"), "appointment_types", ["clinic_id"])

    op.create_table(
        "scheduling_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        _clinic_fk("scheduling_policies"),
        sa.Column("min_notice_hours", sa.Integer(), nullable=False),
        sa.Column("max_advance_days", sa.Integer(), nullable=False),
        sa.Column("same_day_booking", sa.Boolean(), nullable=False),
        sa.Column("cancellation_window_hours", sa.Integer(), nullable=False),
        sa.Column("cancellation_notes", sa.Text(), nullable=False),
        sa.Column("reschedule_window_hours", sa.Integer(), nullable=False),
        sa.Column("max_reschedules", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduling_policies")),
        sa.UniqueConstraint("clinic_id", name=op.f("uq_scheduling_policies_clinic_id")),
    )

    op.create_table(
        "agent_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        _clinic_fk("agent_configs"),
        sa.Column("agent_name", sa.String(80), nullable=False),
        sa.Column("greeting", sa.Text(), nullable=False),
        sa.Column("supported_intents", postgresql.JSONB(), nullable=False),
        sa.Column("escalation_instructions", sa.Text(), nullable=False),
        sa.Column("allowed_capabilities", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_configs")),
        sa.UniqueConstraint("clinic_id", name=op.f("uq_agent_configs_clinic_id")),
    )

    op.create_table(
        "config_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        _clinic_fk("config_versions"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_versions")),
        sa.UniqueConstraint("clinic_id", "version", name=op.f("uq_config_versions_clinic_id")),
    )
    op.create_index(op.f("ix_config_versions_clinic_id"), "config_versions", ["clinic_id"])

    op.execute(
        """
        CREATE FUNCTION config_versions_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'config_versions rows are immutable (% blocked)', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER config_versions_no_update_delete
        BEFORE UPDATE OR DELETE ON config_versions
        FOR EACH ROW EXECUTE FUNCTION config_versions_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS config_versions_no_update_delete ON config_versions")
    op.execute("DROP FUNCTION IF EXISTS config_versions_immutable()")
    op.drop_table("config_versions")
    op.drop_table("agent_configs")
    op.drop_table("scheduling_policies")
    op.drop_table("appointment_types")
    op.drop_table("operating_hours")
    op.drop_constraint(op.f("uq_clinics_name"), "clinics", type_="unique")
    op.drop_column("clinics", "updated_at")
    for col in ["email", "phone", "timezone", "location", "specialty"]:
        op.drop_column("clinics", col)
