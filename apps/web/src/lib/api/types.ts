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
