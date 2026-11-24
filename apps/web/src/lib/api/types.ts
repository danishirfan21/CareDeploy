// Mirrors apps/api/app/schemas/*.py. Keep in sync when contracts change.
export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
}

export interface DbHealthResponse {
  status: "ok" | "unavailable";
  database: boolean;
}

export const INTENTS = [
  "book_appointment",
  "cancel_appointment",
  "reschedule_appointment",
  "clinic_information",
  "speak_to_human",
] as const;
export type Intent = (typeof INTENTS)[number];

export const CAPABILITIES = [
  "check_availability",
  "book_appointment",
  "cancel_appointment",
  "reschedule_appointment",
  "escalate_to_human",
] as const;
export type Capability = (typeof CAPABILITIES)[number];

export const INTENT_REQUIRES_CAPABILITY: Partial<Record<Intent, Capability>> = {
  book_appointment: "book_appointment",
  cancel_appointment: "cancel_appointment",
  reschedule_appointment: "reschedule_appointment",
  speak_to_human: "escalate_to_human",
};

export interface ClinicDetails {
  name: string;
  specialty: string;
  location: string;
  timezone: string;
  phone: string;
  email: string;
}

export interface Clinic extends ClinicDetails {
  id: string;
  created_at: string;
  updated_at: string;
  latest_version: number | null;
}

export interface OperatingHoursEntry {
  weekday: number; // 0 = Monday
  opens: string; // HH:MM
  closes: string;
}

export interface AppointmentTypeEntry {
  /** Stable identity assigned by the server; omit for new types. */
  id?: string | null;
  name: string;
  duration_minutes: number;
  requires_human_escalation: boolean;
  constraints: string;
}

export interface SchedulingPolicy {
  min_notice_hours: number;
  max_advance_days: number;
  same_day_booking: boolean;
  cancellation_window_hours: number;
  cancellation_notes: string;
  reschedule_window_hours: number;
  max_reschedules: number;
}

export interface AgentBehavior {
  agent_name: string;
  greeting: string;
  supported_intents: Intent[];
  escalation_instructions: string;
  allowed_capabilities: Capability[];
}

export interface ClinicConfig {
  details: ClinicDetails;
  hours: OperatingHoursEntry[];
  appointment_types: AppointmentTypeEntry[];
  policy: SchedulingPolicy;
  agent: AgentBehavior;
}

export interface ConfigResponse {
  clinic_id: string;
  config: ClinicConfig;
  latest_version: number | null;
  has_unpublished_changes: boolean;
}

export interface ValidationIssue {
  severity: "error" | "warning";
  section: "details" | "hours" | "services" | "policy" | "agent";
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
}

export interface ConfigVersionSummary {
  version: number;
  published_at: string;
}

export interface ConfigVersion extends ConfigVersionSummary {
  clinic_id: string;
  config: ClinicConfig;
}

// ---- Voice sessions (M3) ----

export type CallStatus =
  "created" | "active" | "completed" | "failed" | "abandoned";

export type CallOutcomeKind =
  | "appointment_booked"
  | "appointment_rescheduled"
  | "appointment_cancelled"
  | "information_provided"
  | "escalated"
  | "no_action"
  | "failed";

export interface VoiceSessionCreated {
  call_session_id: string;
  clinic_id: string;
  clinic_name: string;
  agent_name: string;
  config_version: number;
  room_name: string;
  livekit_url: string;
  token: string;
  token_expires_at: string;
  created_at: string;
  dev_actor: string;
}

export interface LiveState {
  transport?: string;
  conversation?: string;
  operation?: string;
  activity?: string;
  interim_user?: string;
  agent_name?: string;
  pending_confirmation?: boolean;
  verified_patient?: string | null;
  ended?: boolean;
}

export interface VoiceSession {
  call_session_id: string;
  clinic_id: string;
  clinic_name: string;
  agent_name: string;
  config_version: number;
  status: CallStatus;
  outcome: CallOutcomeKind | null;
  summary: string | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  ended_by: string | null;
  escalation_reason: string | null;
  error: string | null;
  operation_ids: string[];
  metrics: Record<string, unknown>;
  live_state: LiveState;
  dev_actor: string;
}

export interface CallEvent {
  event_id: string;
  seq: number;
  kind: "transcript" | "tool" | "state" | "operation" | "error" | "system";
  occurred_at: string;
  payload: Record<string, unknown>;
}

// ---- Evaluations (M4) ----

export type EvalMode = "workflow" | "llm" | "real_audio";
export type EvalSelection =
  | { kind: "all"; value?: null }
  | { kind: "category" | "scenario"; value: string };

export type EvalRunStatus =
  "queued" | "running" | "completed" | "incomplete" | "cancelled" | "error";
export type EvalResultStatus =
  "passed" | "failed" | "error" | "incomplete" | "skipped" | "not_run";

export interface EvalModeInfo {
  mode: EvalMode;
  label: string;
  available: boolean;
  reason: string | null;
}

export interface EvalScenarioInfo {
  id: string;
  version: number;
  name: string;
  description: string;
  category: string;
  severity: string;
  modes: string[];
  behavior: string;
  not_evaluated_in_workflow: string[];
}

export interface EvalCatalog {
  scenarios: EvalScenarioInfo[];
  categories: { id: string; label: string }[];
  modes: EvalModeInfo[];
  suite_hash: string;
}

export type EvalCounts = Partial<Record<EvalResultStatus | "total", number>>;

export interface EvalRunSummary {
  id: string;
  clinic_id: string;
  mode: EvalMode;
  mode_label: string;
  status: EvalRunStatus;
  config_version: number;
  config_hash: string;
  selection: { kind: string; value: string | null; total?: number };
  rerun_of: string | null;
  counts: EvalCounts;
  total: number;
  current_scenario: string | null;
  error: string | null;
  requested_by: string;
  suite_hash: string;
  runner_version: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested: boolean;
}

export interface EvalResultSummary {
  scenario_id: string;
  scenario_version: number;
  name: string;
  category: string;
  severity: string;
  status: EvalResultStatus;
  failure: string | null;
  duration_ms: number;
  not_evaluated: string[];
}

export interface EvalCategoryGroup {
  category: string;
  label: string;
  counts: EvalCounts;
  results: EvalResultSummary[];
}

export interface EvalRunDetail extends EvalRunSummary {
  categories: EvalCategoryGroup[];
}

export interface EvalAssertion {
  id: string;
  type: string;
  passed: boolean;
  expected: string;
  observed: string;
  message: string;
  source: string;
}

export interface EvalEvent {
  seq: number;
  kind: string;
  actor: string;
  occurred_at: string | null;
  payload: Record<string, unknown>;
}

export interface EvalResultDetail extends EvalResultSummary {
  run_id: string;
  scenario_hash: string;
  mode: string;
  expected: Record<string, unknown>;
  observed: Record<string, unknown>;
  assertions: EvalAssertion[];
  events: EvalEvent[];
  started_at: string | null;
  finished_at: string | null;
}

export type EvalReadinessLevel =
  | "not_evaluated"
  | "blocked"
  | "simulation_passed"
  | "live_pending"
  | "verified_scope";

export interface EvalModeReadiness {
  mode: EvalMode;
  label: string;
  state: "not_run" | "partial" | "incomplete" | "blocked" | "passed";
  reason?: string | null;
  run_id?: string;
  counts?: EvalCounts;
  critical_unmet?: { scenario_id: string; name: string; status: string }[];
}

export interface EvalReadiness {
  config_version: number;
  level: EvalReadinessLevel;
  label: string;
  statement: string;
  simulated_promotion: string;
  live_verification: "pending" | "complete";
  blocking: {
    mode: string;
    scenario_id: string;
    name: string;
    status: string;
  }[];
  notes: string[];
  modes: Record<EvalMode, EvalModeReadiness>;
}

// ---------------------------------------------------------------- Operations (M5) ----------
export type OutcomeClass =
  | "completed"
  | "escalated"
  | "failed"
  | "abandoned"
  | "interrupted"
  | "unknown";

export interface CallListItem {
  id: string;
  clinic_id: string;
  clinic_name: string;
  started_at: string;
  status: string;
  outcome_class: OutcomeClass | null;
  outcome_label: string;
  task_type: string | null;
  task_label: string | null;
  duration_seconds: number | null;
  config_version: number;
}

export interface CallList {
  items: CallListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TranscriptTurnOut {
  event_id: string;
  seq: number;
  speaker: "caller" | "agent";
  text: string;
  interrupted: boolean;
  occurred_at: string;
}

export interface OperationRef {
  id: string;
  operation_type: string;
  status: string;
  appointment_id: string | null;
}

export interface AgentAction {
  call_id: string;
  name: string;
  label: string;
  status: string;
  succeeded: boolean;
  code: string | null;
  message: string | null;
  error_category: string | null;
  error_category_label: string | null;
  operation_id: string | null;
  operation: OperationRef | null;
  latency_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
  args: Record<string, unknown> | null;
}

export interface DeploymentRef {
  id: string;
  action: string;
  config_version: number;
  activated_at: string;
  status: string;
}

export interface EvaluationRef {
  run_id: string;
  status: string;
  finished_at: string | null;
}

export interface CallDetail {
  id: string;
  clinic_id: string;
  clinic_name: string;
  agent_name: string | null;
  config_version: number;
  status: string;
  agent_reported_outcome: string | null;
  outcome_class: OutcomeClass | null;
  outcome_label: string;
  outcome_reason: string | null;
  task_type: string | null;
  task_label: string | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  ended_by: string | null;
  escalation_reason: string | null;
  error: string | null;
  summary: string | null;
  operations: OperationRef[];
  deployment: DeploymentRef | null;
  evaluation: EvaluationRef | null;
  transcript: TranscriptTurnOut[];
  actions: AgentAction[];
  technical: Record<string, unknown>;
}

export interface MetricRate {
  numerator: number;
  denominator: number;
  value: number | null;
  low_sample: boolean;
  definition: string;
}

export interface CostSummary {
  estimate: true;
  currency: string;
  available: boolean;
  calls_with_cost: number;
  calls_without_cost: number;
  total: string | null;
  per_call: string | null;
  per_completed_task: string | null;
  completed_with_cost: number;
  reason: string | null;
  note: string;
}

export interface CallMetrics {
  clinic_id: string;
  timezone: string;
  from_date: string;
  to_date: string;
  total_calls: number;
  in_progress: number;
  classified_calls: number;
  by_outcome: Record<string, number>;
  completion: MetricRate;
  escalation: MetricRate;
  failure: MetricRate;
  average_duration_seconds: number | null;
  calls_with_duration: number;
  average_duration_completed_seconds: number | null;
  tools: {
    finished: number;
    succeeded: number;
    failed: number;
    uncertain: number;
    failure_rate: MetricRate;
  };
  cost: CostSummary;
  notes: string[];
}

export interface DeploymentRead {
  id: string;
  clinic_id: string;
  config_version: number;
  environment: string;
  environment_label: string;
  status: "active" | "superseded";
  action: "seed" | "promote" | "rollback";
  activated_at: string;
  deactivated_at: string | null;
  actor: string;
  readiness_level: string;
  restored_from_id: string | null;
}

export interface DeploymentState {
  clinic_id: string;
  environment: string;
  environment_label: string;
  active: DeploymentRead | null;
  latest_published_version: number | null;
  note: string;
}

export interface DeploymentEvent {
  id: string;
  deployment_id: string;
  kind: "seeded" | "promoted" | "rolled_back";
  from_version: number | null;
  to_version: number;
  actor: string;
  occurred_at: string;
  summary: string;
}

export interface DeploymentCheck {
  id: string;
  passed: boolean;
  message: string;
}

export interface DeploymentAssessment {
  clinic_id: string;
  config_version: number;
  action: "promote" | "rollback" | "none";
  eligible: boolean;
  decision: "allowed" | "blocked";
  headline: string;
  live_verification: string;
  live_verification_message: string;
  checks: DeploymentCheck[];
  active_version: number | null;
  evaluated_run_id: string | null;
}
