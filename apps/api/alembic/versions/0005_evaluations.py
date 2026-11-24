"""evaluation runs, scenario results and traces (additive)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

RUN_STATUSES = "'queued','running','completed','cancelled','error','incomplete'"
RESULT_STATUSES = "'passed','failed','error','skipped','not_run','incomplete'"
MODES = "'workflow','llm','real_audio'"
NOW = sa.func.now()
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "clinic_id", sa.Uuid(), sa.ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "config_version_id",
            sa.Uuid(),
            sa.ForeignKey("config_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("selection", JSONB(), nullable=False, server_default="{}"),
        sa.Column("rerun_of", sa.Uuid(), sa.ForeignKey("eval_runs.id")),
        sa.Column("suite_hash", sa.String(64), nullable=False),
        sa.Column("runner_version", sa.String(20), nullable=False),
        sa.Column("runner_info", JSONB(), nullable=False, server_default="{}"),
        sa.Column("counts", JSONB(), nullable=False, server_default="{}"),
        sa.Column("readiness", JSONB()),
        sa.Column("current_scenario", sa.String(20)),
        sa.Column("error", sa.Text()),
        sa.Column("requested_by", sa.String(80), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="ck_eval_runs_status"),
        sa.CheckConstraint(f"mode IN ({MODES})", name="ck_eval_runs_mode"),
    )
    op.create_index("ix_eval_runs_clinic_created", "eval_runs", ["clinic_id", "created_at"])

    op.create_table(
        "eval_scenario_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("eval_runs.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("scenario_id", sa.String(20), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("scenario_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected", JSONB(), nullable=False, server_default="{}"),
        sa.Column("observed", JSONB(), nullable=False, server_default="{}"),
        sa.Column("assertions", JSONB(), nullable=False, server_default="[]"),
        sa.Column("failure", sa.Text()),
        sa.Column("not_evaluated", JSONB(), nullable=False, server_default="[]"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"status IN ({RESULT_STATUSES})", name="ck_eval_results_status"),
        sa.UniqueConstraint("run_id", "scenario_id", name="uq_eval_results_run_scenario"),
    )
    op.create_index("ix_eval_scenario_results_run_id", "eval_scenario_results", ["run_id"])

    op.create_table(
        "eval_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "result_id",
            sa.Uuid(),
            sa.ForeignKey("eval_scenario_results.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(30), nullable=False, server_default="caller"),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("result_id", "seq", name="uq_eval_events_result_seq"),
    )
    op.create_index("ix_eval_events_result_id", "eval_events", ["result_id"])

    # Finished runs, results and traces are immutable: a report must not change after the fact.
    op.execute(
        """
        CREATE FUNCTION eval_run_immutable() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'eval_runs rows cannot be deleted';
          END IF;
          IF OLD.status IN ('completed','cancelled','error','incomplete') THEN
            RAISE EXCEPTION 'finished evaluation runs are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER eval_runs_immutable BEFORE UPDATE OR DELETE ON eval_runs
        FOR EACH ROW EXECUTE FUNCTION eval_run_immutable()
        """
    )
    op.execute(
        """
        CREATE FUNCTION eval_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("eval_scenario_results", "eval_events"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION eval_append_only()
            """
        )


def downgrade() -> None:
    for table in ("eval_events", "eval_scenario_results"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS eval_append_only()")
    op.execute("DROP TRIGGER IF EXISTS eval_runs_immutable ON eval_runs")
    op.execute("DROP FUNCTION IF EXISTS eval_run_immutable()")
    op.drop_table("eval_events")
    op.drop_table("eval_scenario_results")
    op.drop_table("eval_runs")
