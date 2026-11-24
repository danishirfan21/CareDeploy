"""Typed API contracts for call operations, metrics and deployments (M5). Mirrored by hand in
apps/web/src/lib/api/types.ts. Fields that older records may lack are nullable: the UI shows
"Unavailable" rather than a guess."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

OutcomeClass = Literal["completed", "escalated", "failed", "abandoned", "interrupted", "unknown"]


class CallListItem(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    clinic_name: str
    started_at: datetime
    status: str
    outcome_class: OutcomeClass | None
    outcome_label: str
    task_type: str | None
    task_label: str | None
    duration_seconds: float | None
    config_version: int


class CallList(BaseModel):
    items: list[CallListItem]
    total: int
    limit: int
    offset: int


class TranscriptTurnOut(BaseModel):
    event_id: str
    seq: int
    speaker: Literal["caller", "agent"]
    text: str
    interrupted: bool
    occurred_at: datetime


class OperationRef(BaseModel):
    id: str
    operation_type: str
    status: str
    appointment_id: str | None


class AgentAction(BaseModel):
    call_id: str
    name: str
    label: str
    status: str  # ok | committed | needs_input | uncertain | error | rejected | running
    succeeded: bool
    code: str | None
    message: str | None
    error_category: str | None
    error_category_label: str | None
    operation_id: str | None
    operation: OperationRef | None
    latency_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    args: dict[str, Any] | None


class DeploymentRef(BaseModel):
    id: uuid.UUID
    action: str
    config_version: int
    activated_at: datetime
    status: str


class EvaluationRef(BaseModel):
    run_id: uuid.UUID
    status: str
    finished_at: datetime | None


class CallDetail(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    clinic_name: str
    agent_name: str | None
    config_version: int
    status: str
    agent_reported_outcome: str | None
    outcome_class: OutcomeClass | None
    outcome_label: str
    outcome_reason: str | None
    task_type: str | None
    task_label: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: float | None
    ended_by: str | None
    escalation_reason: str | None
    error: str | None
    summary: str | None
    operations: list[OperationRef]
    deployment: DeploymentRef | None
    evaluation: EvaluationRef | None
    transcript: list[TranscriptTurnOut]
    actions: list[AgentAction]
    technical: dict[str, Any]


# --------------------------------------------------------------------------- metrics ----------
class Rate(BaseModel):
    numerator: int
    denominator: int
    value: float | None
    low_sample: bool
    definition: str


class ToolStats(BaseModel):
    finished: int
    succeeded: int
    failed: int
    uncertain: int
    failure_rate: Rate


class CostSummary(BaseModel):
    estimate: Literal[True] = True
    currency: str
    available: bool
    calls_with_cost: int
    calls_without_cost: int
    total: str | None
    per_call: str | None
    per_completed_task: str | None
    completed_with_cost: int
    reason: str | None
    note: str


class MetricsOut(BaseModel):
    clinic_id: uuid.UUID
    timezone: str
    from_date: date
    to_date: date
    starts_at: datetime
    ends_before: datetime
    total_calls: int
    in_progress: int
    classified_calls: int
    by_outcome: dict[str, int]
    completion: Rate
    escalation: Rate
    failure: Rate
    average_duration_seconds: float | None
    calls_with_duration: int
    average_duration_completed_seconds: float | None
    tools: ToolStats
    cost: CostSummary
    notes: list[str]


# ------------------------------------------------------------------------- deployments -------
class PromoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config_version: int = Field(ge=1)
    # Compare-and-swap: the version the caller believes is active now (null = none).
    expected_active_version: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)


class RollbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_version: int = Field(ge=1)
    expected_active_version: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)


class DeploymentRead(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    config_version: int
    environment: str
    environment_label: str
    status: Literal["active", "superseded"]
    action: Literal["seed", "promote", "rollback"]
    activated_at: datetime
    deactivated_at: datetime | None
    actor: str
    readiness_level: str
    restored_from_id: uuid.UUID | None


class DeploymentEventRead(BaseModel):
    id: uuid.UUID
    deployment_id: uuid.UUID
    kind: Literal["seeded", "promoted", "rolled_back"]
    from_version: int | None
    to_version: int
    actor: str
    occurred_at: datetime
    summary: str


class DeploymentEventDetail(DeploymentEventRead):
    readiness: dict[str, Any]
    deployment: DeploymentRead


class DeploymentState(BaseModel):
    clinic_id: uuid.UUID
    environment: str
    environment_label: str
    active: DeploymentRead | None
    latest_published_version: int | None
    note: str


class DeploymentCheck(BaseModel):
    id: str
    passed: bool
    message: str


class DeploymentAssessment(BaseModel):
    clinic_id: uuid.UUID
    config_version: int
    action: Literal["promote", "rollback", "none"]
    eligible: bool
    decision: Literal["allowed", "blocked"]
    headline: str
    live_verification: str
    live_verification_message: str
    checks: list[DeploymentCheck]
    readiness: dict[str, Any]
    active_version: int | None
    evaluated_run_id: str | None
