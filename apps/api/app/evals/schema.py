"""Scenario specification (strict). A scenario is data: fixtures, scripted steps, assertions.

Everything is validated before anything executes; unknown keys are rejected so a typo cannot
silently turn into a check that never runs.
"""

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal[
    "appointment_workflows",
    "conversation_handling",
    "scheduling_integrity",
    "authorization_safety",
    "failure_escalation",
]
CATEGORY_LABELS: dict[str, str] = {
    "appointment_workflows": "Appointment workflows",
    "conversation_handling": "Conversation handling",
    "scheduling_integrity": "Scheduling integrity",
    "authorization_safety": "Authorization and safety",
    "failure_escalation": "Failure and escalation",
}
Severity = Literal["critical", "high", "medium", "low"]
EvalMode = Literal["workflow", "llm", "real_audio"]
SCENARIO_ID = re.compile(r"^EVAL-\d{3}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- requirements -----
class Requires(Strict):
    """What the selected clinic configuration must provide. Unmet requirements make the scenario
    *skipped* (never passed): the readiness gate treats a skipped critical scenario as unmet."""

    capabilities: list[str] = Field(default_factory=list)
    standard_type: bool = False  # at least one appointment type the agent may book itself
    escalation_type: bool = False  # at least one type that requires human escalation
    intents: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- fixtures ---------
class PatientFixture(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,20}$")
    name: str
    dob: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    phone: str = Field(pattern=r"^\(\d{3}\) \d{3}-\d{4}$")
    clinic: Literal["primary", "other"] = "primary"

    @property
    def last4(self) -> str:
        return self.phone[-4:]


class AppointmentFixture(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,20}$")
    patient: str
    type: str = "${standard_type}"
    start: str  # may be a ${...} variable such as ${in_hours_start}


class Fixtures(Strict):
    patients: list[PatientFixture] = Field(default_factory=list)
    appointments: list[AppointmentFixture] = Field(default_factory=list)
    other_clinic: bool = False  # a second, unrelated clinic with its own patients

    @model_validator(mode="after")
    def _refs(self) -> "Fixtures":
        keys = [p.key for p in self.patients]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate patient keys")
        for a in self.appointments:
            if a.patient not in keys:
                raise ValueError(f"appointment '{a.key}' references unknown patient '{a.patient}'")
        if any(p.clinic == "other" for p in self.patients) and not self.other_clinic:
            raise ValueError("patients in the other clinic need fixtures.other_clinic = true")
        return self


# --------------------------------------------------------------------------- steps ------------
class Expect(Strict):
    """Per-step expectation. Each populated field becomes its own assertion result."""

    status: str | list[str] | None = None  # tool status, or HTTP status for api steps
    code: str | list[str] | None = None
    ok: bool | None = None
    replay: bool | None = None  # api steps: was the response an idempotent replay?


class SayStep(Strict):
    kind: Literal["say"]
    text: str = Field(min_length=1)
    actor: str = "caller"


class ToolStep(Strict):
    kind: Literal["tool"]
    id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,30}$")
    actor: str = "caller"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    expect: Expect | None = None


class ApiStep(Strict):
    """A raw call to the M2 scheduling API as a *non-agent* client. It exists to prove the backend
    itself refuses things the tool layer would never attempt (so a buggy or manipulated agent is
    still contained)."""

    kind: Literal["api"]
    id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,30}$")
    method: Literal["GET", "POST"]
    path: str = Field(pattern=r"^/[a-zA-Z0-9_/${}.\-]*$")
    clinic: Literal["primary", "other"] = "primary"
    as_patient: str | None = None  # fixture patient key whose verified token to send
    body: dict[str, Any] | None = None
    idempotency_key: str | None = None
    capture: dict[str, str] = Field(default_factory=dict)  # variable -> dotted JSON path
    expect: Expect | None = None


class FaultSpec(Strict):
    type: Literal["scheduling_fault", "drop_response", "drop_request", "backend_down"]
    point: Literal["after_claim", "in_work", "before_commit", "after_commit"] | None = None
    error: Literal["timeout", "unavailable"] = "timeout"
    match: str = "/appointments"
    times: int = Field(default=1, ge=1, le=5)


class InjectStep(Strict):
    kind: Literal["inject"]
    fault: FaultSpec


class ClearFaultsStep(Strict):
    kind: Literal["clear_faults"]


class ParallelStep(Strict):
    kind: Literal["parallel"]
    branches: list[list["Step"]] = Field(min_length=2, max_length=4)


Step = Annotated[
    SayStep | ToolStep | ApiStep | InjectStep | ClearFaultsStep | ParallelStep,
    Field(discriminator="kind"),
]
ParallelStep.model_rebuild()


# --------------------------------------------------------------------------- assertions --------
class A(Strict):
    id: str | None = None  # optional label shown in the report
    note: str | None = None


class ToolCalled(A):
    type: Literal["tool_called"]
    tool: str
    actor: str = "caller"
    min_times: int = Field(default=1, ge=1)
    max_times: int | None = None
    args_include: dict[str, Any] | None = None


class ToolNotCalled(A):
    type: Literal["tool_not_called"]
    tool: str
    actor: str | None = None  # None: no actor called it


class ToolResultIs(A):
    type: Literal["tool_result"]
    tool: str
    actor: str = "caller"
    nth: int = -1  # -1: the last call of that tool
    status: str | list[str] | None = None
    code: str | list[str] | None = None


class AppointmentCount(A):
    type: Literal["appointment_count"]
    scope: Literal["clinic", "patient"] = "clinic"
    patient: str | None = None
    status: Literal["scheduled", "cancelled", "completed", "any"] = "scheduled"
    delta: int | None = None  # change from the state after fixtures were created
    equals: int | None = None

    @model_validator(mode="after")
    def _one(self) -> "AppointmentCount":
        if (self.delta is None) == (self.equals is None):
            raise ValueError("give exactly one of delta / equals")
        if self.scope == "patient" and not self.patient:
            raise ValueError("scope 'patient' needs a patient key")
        return self


class AppointmentStatus(A):
    type: Literal["appointment_status"]
    appointment: str
    status: Literal["scheduled", "cancelled", "completed"]


class AppointmentEvents(A):
    """The appointment's audit trail holds exactly these event types, in order (a refused change
    must leave no event behind)."""

    type: Literal["appointment_events"]
    appointment: str
    kinds: list[str]


class AppointmentMoved(A):
    type: Literal["appointment_moved"]
    appointment: str
    moved: bool = True
    reschedule_count: int | None = None


class OperationCount(A):
    type: Literal["operation_count"]
    delta: int | None = None
    equals: int | None = None
    status: Literal["processing", "succeeded", "failed", "aborted"] | None = None
    operation_type: str | None = None

    @model_validator(mode="after")
    def _one(self) -> "OperationCount":
        if (self.delta is None) == (self.equals is None):
            raise ValueError("give exactly one of delta / equals")
        return self


class ProposalCount(A):
    type: Literal["proposal_count"]
    status: Literal["pending", "confirmed", "executed", "rejected"]
    equals: int


class NoOverlappingAppointments(A):
    type: Literal["no_overlapping_appointments"]


class NoCrossClinicDisclosure(A):
    type: Literal["no_cross_clinic_disclosure"]


class TraceExcludes(A):
    type: Literal["trace_excludes"]
    values: list[str] = Field(min_length=1)


class EscalationRecorded(A):
    type: Literal["escalation"]
    expected: bool = True


class OutcomeIs(A):
    type: Literal["outcome"]
    equals: Literal[
        "appointment_booked",
        "appointment_rescheduled",
        "appointment_cancelled",
        "information_provided",
        "escalated",
        "no_action",
        "failed",
    ]


class NoCommittedReport(A):
    """No tool result claimed `committed`, i.e. the agent was never told a change succeeded."""

    type: Literal["no_committed_report"]


class SingleCommittedOperation(A):
    """Every committed tool result refers to the same backend operation (idempotent replay)."""

    type: Literal["single_committed_operation"]


class SameOperation(A):
    """Several api steps resolved to one backend operation (idempotent replay)."""

    type: Literal["same_operation"]
    steps: list[str] = Field(min_length=2)


class ConversationEventsPresent(A):
    type: Literal["conversation_events"]
    min_caller_turns: int = Field(default=1, ge=0)


class InstructionsInclude(A):
    """The shared agent instructions (the same text the live agent receives for this published
    configuration) contain each phrase. Binds instruction wording to the evaluation."""

    type: Literal["instructions_include"]
    phrases: list[str] = Field(min_length=1)


Assertion = Annotated[
    ToolCalled
    | ToolNotCalled
    | ToolResultIs
    | AppointmentCount
    | AppointmentStatus
    | AppointmentMoved
    | AppointmentEvents
    | OperationCount
    | ProposalCount
    | NoOverlappingAppointments
    | NoCrossClinicDisclosure
    | TraceExcludes
    | EscalationRecorded
    | OutcomeIs
    | NoCommittedReport
    | SingleCommittedOperation
    | SameOperation
    | ConversationEventsPresent
    | InstructionsInclude,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- blocks -----------
class Expected(Strict):
    """What a reviewer should see happen. `agent_actions` / `forbidden_actions` are enforced:
    they are compiled into tool_called / tool_not_called assertions."""

    behavior: str = Field(min_length=10)
    agent_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    operation_outcome: str = ""
    database_changes: str = ""
    escalation: Literal["required", "forbidden", "not_applicable"] = "not_applicable"


class WorkflowBlock(Strict):
    """Scripted, deterministic run: the *test* chooses every tool call. Establishes tool,
    authorization, business-rule and database behavior; says nothing about language models."""

    steps: list[Step] = Field(min_length=1)
    assertions: list[Assertion] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class LlmBlock(Strict):
    """Scripted caller lines for a real model. Objective assertions run on the real tool trace;
    `criteria` are human-review notes (no model judges safety-critical results)."""

    caller_script: list[str] = Field(min_length=1)
    assertions: list[Assertion] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=120, ge=10, le=600)


class Scenario(Strict):
    id: str
    version: int = Field(ge=1)
    name: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=10)
    category: Category
    severity: Severity
    modes: list[EvalMode] = Field(min_length=1)
    clock: str  # fixed UTC "now" so availability and notice rules are reproducible
    requires: Requires = Field(default_factory=Requires)
    fixtures: Fixtures = Field(default_factory=Fixtures)
    actors: list[str] = Field(default_factory=lambda: ["caller"])
    expected: Expected
    workflow: WorkflowBlock | None = None
    llm: LlmBlock | None = None
    not_evaluated_in_workflow: list[str] = Field(default_factory=list)
    isolation: Literal["fresh_clinic_per_scenario"] = "fresh_clinic_per_scenario"
    cleanup: Literal["drop_run_database"] = "drop_run_database"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not SCENARIO_ID.match(v):
            raise ValueError("id must look like EVAL-001")
        return v

    @field_validator("clock")
    @classmethod
    def _clock(cls, v: str) -> str:
        from datetime import datetime

        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("clock must be a timezone-aware ISO timestamp")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "Scenario":
        if "workflow" in self.modes and self.workflow is None:
            raise ValueError("mode 'workflow' needs a workflow block")
        if "llm" in self.modes and self.llm is None:
            raise ValueError("mode 'llm' needs an llm block")
        if self.workflow and "workflow" not in self.modes:
            raise ValueError("workflow block present but 'workflow' not listed in modes")
        if self.llm and "llm" not in self.modes:
            raise ValueError("llm block present but 'llm' not listed in modes")
        if "real_audio" in self.modes:
            raise ValueError(
                "real_audio scenarios cannot be declared yet: the audio runner does not exist"
            )
        if self.workflow and not (self.workflow.assertions or self._has_step_expectations()):
            raise ValueError("a workflow scenario needs at least one assertion or step expectation")
        if self.llm and not self.llm.assertions:
            raise ValueError("an llm scenario needs at least one objective assertion")
        if "caller" not in self.actors:
            raise ValueError("the actor list must include 'caller'")
        patient_keys = {p.key for p in self.fixtures.patients}
        if self.workflow:
            _check_steps(self.workflow.steps, set(self.actors), patient_keys)
            for a in self.workflow.assertions:
                _check_assertion(a, set(self.actors), patient_keys, self.fixtures)
        if self.llm:
            for a in self.llm.assertions:
                _check_assertion(a, set(self.actors), patient_keys, self.fixtures)
        for action in self.expected.agent_actions + self.expected.forbidden_actions:
            if action not in TOOL_NAMES:
                raise ValueError(f"expected action '{action}' is not a known tool")
        if set(self.expected.agent_actions) & set(self.expected.forbidden_actions):
            raise ValueError("a tool cannot be both expected and forbidden")
        return self

    def _has_step_expectations(self) -> bool:
        def walk(steps: list[Any]) -> bool:
            for s in steps:
                if isinstance(s, ParallelStep):
                    if any(walk(b) for b in s.branches):
                        return True
                elif getattr(s, "expect", None) is not None:
                    return True
            return False

        return bool(self.workflow and walk(self.workflow.steps))

    def content_hash(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def requires_workflow(self) -> bool:
        return self.workflow is not None


TOOL_NAMES = {
    "get_clinic_information",
    "get_appointment_availability",
    "verify_patient",
    "get_patient_appointments",
    "propose_booking",
    "propose_reschedule",
    "propose_cancellation",
    "confirm_operation",
    "get_operation_status",
    "withdraw_pending_proposal",
    "request_human_escalation",
}


def _check_steps(steps: list[Any], actors: set[str], patients: set[str]) -> None:
    for s in steps:
        if isinstance(s, ParallelStep):
            for b in s.branches:
                _check_steps(b, actors, patients)
            continue
        if isinstance(s, SayStep | ToolStep) and s.actor not in actors:
            raise ValueError(f"step uses undeclared actor '{s.actor}'")
        if isinstance(s, ToolStep) and s.tool not in TOOL_NAMES:
            raise ValueError(f"unknown tool '{s.tool}'")
        if isinstance(s, ApiStep) and s.as_patient and s.as_patient not in patients:
            raise ValueError(f"api step references unknown patient '{s.as_patient}'")


def _check_assertion(a: Any, actors: set[str], patients: set[str], fx: Fixtures) -> None:
    if isinstance(a, ToolCalled | ToolResultIs) and a.actor not in actors:
        raise ValueError(f"assertion uses undeclared actor '{a.actor}'")
    if isinstance(a, ToolCalled | ToolNotCalled | ToolResultIs) and a.tool not in TOOL_NAMES:
        raise ValueError(f"assertion references unknown tool '{a.tool}'")
    if isinstance(a, AppointmentCount) and a.patient and a.patient not in patients:
        raise ValueError(f"assertion references unknown patient '{a.patient}'")
    if isinstance(
        a, AppointmentStatus | AppointmentMoved | AppointmentEvents
    ) and a.appointment not in {x.key for x in fx.appointments}:
        raise ValueError(f"assertion references unknown appointment '{a.appointment}'")
