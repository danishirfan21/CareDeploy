"""Evaluation runs, scenario results and bounded traces (M4).

Completed runs are immutable: database triggers reject any UPDATE of a finished run and any
UPDATE/DELETE of results and events, so a report cannot drift after the fact. Each run records
the exact configuration version (and a content hash) and each result the exact scenario version
(and hash) it used.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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

RUN_STATUSES = ("queued", "running", "completed", "cancelled", "error", "incomplete")
TERMINAL_RUN_STATUSES = ("completed", "cancelled", "error", "incomplete")
RESULT_STATUSES = ("passed", "failed", "error", "skipped", "not_run", "incomplete")
EVAL_MODES = ("workflow", "llm", "real_audio")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_eval_runs_status"),
        CheckConstraint(_in("mode", EVAL_MODES), name="ck_eval_runs_mode"),
        Index("ix_eval_runs_clinic_created", "clinic_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="RESTRICT"))
    config_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("config_versions.id", ondelete="RESTRICT")
    )
    config_version: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rerun_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("eval_runs.id"))
    suite_hash: Mapped[str] = mapped_column(String(64))
    runner_version: Mapped[str] = mapped_column(String(20))
    runner_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    readiness: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    current_scenario: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(80))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalScenarioResult(Base):
    __tablename__ = "eval_scenario_results"
    __table_args__ = (
        CheckConstraint(_in("status", RESULT_STATUSES), name="ck_eval_results_status"),
        UniqueConstraint("run_id", "scenario_id", name="uq_eval_results_run_scenario"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="RESTRICT"), index=True
    )
    scenario_id: Mapped[str] = mapped_column(String(20))
    scenario_version: Mapped[int] = mapped_column(Integer)
    scenario_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer, default=0)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    observed: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    assertions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    failure: Mapped[str | None] = mapped_column(Text)
    not_evaluated: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalEvent(Base):
    __tablename__ = "eval_events"
    __table_args__ = (UniqueConstraint("result_id", "seq", name="uq_eval_events_result_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_scenario_results.id", ondelete="RESTRICT"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(30), default="caller")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
