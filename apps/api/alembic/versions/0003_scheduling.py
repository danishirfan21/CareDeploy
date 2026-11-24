"""scheduling domain: stable appointment types, patients, appointments, operations, proposals

Additive. Existing M1 data stays valid:
- appointment_types gains `archived_at`; its name uniqueness becomes "unique among active types".
- all other objects are new.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NOW = sa.func.now()


def _ts(name: str, nullable: bool = False, default: bool = True) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=NOW if default and not nullable else None,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # --- stable appointment-type identity -------------------------------------------------
    op.add_column("appointment_types", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.drop_constraint(op.f("uq_appointment_types_clinic_id"), "appointment_types", type_="unique")
    op.create_unique_constraint(
        "uq_appointment_types_clinic_id_id", "appointment_types", ["clinic_id", "id"]
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_appointment_types_active_name "
        "ON appointment_types (clinic_id, lower(name)) WHERE archived_at IS NULL"
    )

    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("email", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "verification_method", sa.String(40), nullable=False, server_default="dob_phone_last4"
        ),
        sa.Column("failed_verification_attempts", sa.Integer(), nullable=False, server_default="0"),
        _ts("locked_until", nullable=True),
        _ts("last_verified_at", nullable=True),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], ondelete="RESTRICT", name="fk_patients_clinic_id_clinics"
        ),
        sa.UniqueConstraint("clinic_id", "id", name="uq_patients_clinic_id_id"),
    )
    op.create_index("ix_patients_clinic_id", "patients", ["clinic_id"])

    op.create_table(
        "patient_authorizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        _ts("expires_at", default=False),
        _ts("revoked_at", nullable=True),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_patient_authorizations_patient",
        ),
    )
    op.create_index("ix_patient_authorizations_clinic_id", "patient_authorizations", ["clinic_id"])

    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_type_id", sa.Uuid(), nullable=False),
        sa.Column("type_name", sa.String(100), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        _ts("start_at", default=False),
        _ts("end_at", default=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("reschedule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        _ts("cancelled_at", nullable=True),
        sa.Column("cancellation_reason", sa.String(500)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_appointments_patient",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_type_id"],
            ["appointment_types.clinic_id", "appointment_types.id"],
            ondelete="RESTRICT",
            name="fk_appointments_appointment_type",
        ),
        sa.UniqueConstraint("clinic_id", "id", name="uq_appointments_clinic_id_id"),
        sa.CheckConstraint("end_at > start_at", name="ck_appointments_end_after_start"),
        sa.CheckConstraint(
            "status IN ('scheduled','completed','cancelled')", name="ck_appointments_status"
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="ck_appointments_cancelled_consistent",
        ),
        sa.CheckConstraint("reschedule_count >= 0", name="ck_appointments_reschedules"),
    )
    op.create_index("ix_appointments_clinic_id", "appointments", ["clinic_id"])
    op.create_index(
        "ix_appointments_patient_start", "appointments", ["clinic_id", "patient_id", "start_at"]
    )
    # Concurrency safeguard: one bookable resource per clinic. Two active appointments of the
    # same clinic may not overlap; half-open [start, end) so back-to-back is allowed. Enforced by
    # the database, so concurrent transactions cannot both succeed.
    op.execute(
        """
        ALTER TABLE appointments ADD CONSTRAINT ex_appointments_no_overlap
        EXCLUDE USING gist (clinic_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
        WHERE (status = 'scheduled')
        """
    )

    op.create_table(
        "appointment_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid()),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("config_version", sa.Integer()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointments.clinic_id", "appointments.id"],
            ondelete="RESTRICT",
            name="fk_appointment_events_appointment",
        ),
    )
    op.create_index("ix_appointment_events_clinic_id", "appointment_events", ["clinic_id"])
    op.create_index(
        "ix_appointment_events_appointment_id", "appointment_events", ["appointment_id"]
    )

    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("appointment_id", sa.Uuid()),
        sa.Column("proposal_id", sa.Uuid()),
        sa.Column("outcome", postgresql.JSONB()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("completed_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointments.clinic_id", "appointments.id"],
            ondelete="RESTRICT",
            name="fk_operations_appointment",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_operations_patient",
        ),
        sa.UniqueConstraint("clinic_id", "idempotency_key", name="uq_operations_clinic_id_key"),
        sa.UniqueConstraint("clinic_id", "id", name="uq_operations_clinic_id_id"),
        sa.CheckConstraint(
            "status IN ('processing','succeeded','failed','aborted')", name="ck_operations_status"
        ),
    )
    op.create_index("ix_operations_clinic_id", "operations", ["clinic_id"])

    op.create_table(
        "operation_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        _ts("expires_at", default=False),
        _ts("confirmed_at", nullable=True),
        _ts("executed_at", nullable=True),
        sa.Column("executed_operation_id", sa.Uuid()),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            ondelete="RESTRICT",
            name="fk_operation_proposals_patient",
        ),
        sa.UniqueConstraint("clinic_id", "id", name="uq_operation_proposals_clinic_id_id"),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','executed','rejected')",
            name="ck_operation_proposals_status",
        ),
    )
    op.create_index("ix_operation_proposals_clinic_id", "operation_proposals", ["clinic_id"])

    op.execute(
        """
        CREATE FUNCTION append_only_guard() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% rows are append-only (% blocked)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER appointment_events_append_only
        BEFORE UPDATE OR DELETE ON appointment_events
        FOR EACH ROW EXECUTE FUNCTION append_only_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS appointment_events_append_only ON appointment_events")
    op.execute("DROP FUNCTION IF EXISTS append_only_guard()")
    for table in [
        "operation_proposals",
        "operations",
        "appointment_events",
        "appointments",
        "patient_authorizations",
        "patients",
    ]:
        op.drop_table(table)
    op.execute("DROP INDEX IF EXISTS uq_appointment_types_active_name")
    op.drop_constraint("uq_appointment_types_clinic_id_id", "appointment_types", type_="unique")
    # Restoring plain (clinic, name) uniqueness fails if archived duplicates exist; remove them.
    op.execute("DELETE FROM appointment_types WHERE archived_at IS NOT NULL")
    op.create_unique_constraint(
        op.f("uq_appointment_types_clinic_id"), "appointment_types", ["clinic_id", "name"]
    )
    op.drop_column("appointment_types", "archived_at")
