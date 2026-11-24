"""voice call sessions and events (additive)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

STATUSES = "'created','active','completed','failed','abandoned'"
OUTCOMES = (
    "'appointment_booked','appointment_rescheduled','appointment_cancelled',"
    "'information_provided','escalated','no_action','failed'"
)
KINDS = "'transcript','tool','state','operation','error','system'"
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "call_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "clinic_id", sa.Uuid(), sa.ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("room_name", sa.String(120), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="created"),
        sa.Column("outcome", sa.String(40)),
        sa.Column("summary", sa.Text()),
        sa.Column("dev_actor", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("ended_by", sa.String(20)),
        sa.Column("escalation_reason", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("operation_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("provider_usage", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("live_state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("live_state_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_call_sessions_status"),
        sa.CheckConstraint(
            f"outcome IS NULL OR outcome IN ({OUTCOMES})", name="ck_call_sessions_outcome"
        ),
    )
    op.create_index("ix_call_sessions_clinic_created", "call_sessions", ["clinic_id", "created_at"])
    op.create_table(
        "call_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "call_session_id",
            sa.Uuid(),
            sa.ForeignKey("call_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clinic_id", sa.Uuid(), sa.ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("call_session_id", "event_id", name="uq_call_events_session_event"),
        sa.CheckConstraint(f"kind IN ({KINDS})", name="ck_call_events_kind"),
    )
    op.create_index("ix_call_events_session_seq", "call_events", ["call_session_id", "seq"])


def downgrade() -> None:
    op.drop_table("call_events")
    op.drop_table("call_sessions")
