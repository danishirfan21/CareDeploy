"""Typed API contracts for the evaluation engine. No field accepts a path, code or scenario body:
clients choose among server-side scenarios by id or category and nothing else."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evals.schema import CATEGORY_LABELS, SCENARIO_ID

EvalModeName = Literal["workflow", "llm", "real_audio"]
SelectionKind = Literal["all", "category", "scenario"]


class SelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: SelectionKind = "all"
    value: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _check(self) -> "SelectionIn":
        if self.kind == "all" and self.value is not None:
            raise ValueError("'all' takes no value")
        if self.kind == "scenario" and not (self.value and SCENARIO_ID.match(self.value)):
            raise ValueError("a scenario selection needs a scenario id such as EVAL-001")
        if self.kind == "category" and self.value not in CATEGORY_LABELS:
            raise ValueError("unknown category")
        return self


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: EvalModeName = "workflow"
    config_version: int | None = Field(default=None, ge=1)  # default: latest published
    selection: SelectionIn = Field(default_factory=SelectionIn)


class RerunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(pattern=SCENARIO_ID.pattern)


class ResultSummary(BaseModel):
    scenario_id: str
    scenario_version: int
    name: str
    category: str
    severity: str
    status: str
    failure: str | None
    duration_ms: int
    not_evaluated: list[str]


class AssertionRead(BaseModel):
    id: str
    type: str
    passed: bool
    expected: str
    observed: str
    message: str = ""
    source: str = "assertion"


class EventRead(BaseModel):
    seq: int
    kind: str
    actor: str
    occurred_at: datetime | None
    payload: dict[str, Any]


class ResultDetail(ResultSummary):
    run_id: uuid.UUID
    scenario_hash: str
    mode: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    assertions: list[AssertionRead]
    events: list[EventRead]
    started_at: datetime | None
    finished_at: datetime | None


class RunSummary(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    mode: str
    mode_label: str
    status: str
    config_version: int
    config_hash: str
    selection: dict[str, Any]
    rerun_of: uuid.UUID | None
    counts: dict[str, int]
    total: int
    current_scenario: str | None
    error: str | None
    requested_by: str
    suite_hash: str
    runner_version: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool


class CategoryGroup(BaseModel):
    category: str
    label: str
    counts: dict[str, int]
    results: list[ResultSummary]


class RunDetail(RunSummary):
    categories: list[CategoryGroup]


class ScenarioInfo(BaseModel):
    id: str
    version: int
    name: str
    description: str
    category: str
    severity: str
    modes: list[str]
    behavior: str
    not_evaluated_in_workflow: list[str]


class ModeInfo(BaseModel):
    mode: str
    label: str
    available: bool
    reason: str | None


class CatalogRead(BaseModel):
    scenarios: list[ScenarioInfo]
    categories: list[dict[str, str]]
    modes: list[ModeInfo]
    suite_hash: str
