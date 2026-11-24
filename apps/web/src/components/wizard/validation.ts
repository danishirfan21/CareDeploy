import type { ClinicConfig } from "@/lib/api/types";

export type StepErrors = Record<string, string>;

export const STEP_TITLES = [
  "Clinic details",
  "Hours and services",
  "Scheduling rules",
  "Agent behavior",
  "Review and deployment",
] as const;

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function intIn(v: number, min: number, max: number): boolean {
  return Number.isInteger(v) && v >= min && v <= max;
}

/** Client-side checks for one step (1-4). The server re-validates everything. */
export function validateStep(step: number, c: ClinicConfig): StepErrors {
  const e: StepErrors = {};
  if (step === 1) {
    const d = c.details;
    if (!d.name.trim()) e.name = "Enter the clinic name.";
    if (!d.specialty.trim()) e.specialty = "Enter the specialty.";
    if (!d.location.trim()) e.location = "Enter the location.";
    if (!d.timezone) e.timezone = "Choose a time zone.";
    if (d.email.trim() && !EMAIL.test(d.email.trim()))
      e.email = "Enter a valid email address.";
  }
  if (step === 2) {
    if (c.hours.length === 0) e.hours = "Select at least one operating day.";
    c.hours.forEach((h) => {
      if (!h.opens || !h.closes || h.opens >= h.closes)
        e[`hours-${h.weekday}`] = "Opening time must be before closing time.";
    });
    if (c.appointment_types.length === 0)
      e.types = "Add at least one appointment type.";
    const seen = new Set<string>();
    c.appointment_types.forEach((t, i) => {
      const name = t.name.trim().toLowerCase();
      if (!name) e[`type-${i}-name`] = "Enter a name.";
      else if (seen.has(name)) e[`type-${i}-name`] = "Names must be unique.";
      seen.add(name);
      if (!intIn(t.duration_minutes, 5, 480))
        e[`type-${i}-duration`] = "Duration must be 5–480 minutes.";
    });
  }
  if (step === 3) {
    const p = c.policy;
    if (!intIn(p.min_notice_hours, 0, 720))
      e.min_notice_hours = "Enter 0–720 hours.";
    if (!intIn(p.max_advance_days, 1, 365))
      e.max_advance_days = "Enter 1–365 days.";
    if (!intIn(p.cancellation_window_hours, 0, 336))
      e.cancellation_window_hours = "Enter 0–336 hours.";
    if (!intIn(p.reschedule_window_hours, 0, 336))
      e.reschedule_window_hours = "Enter 0–336 hours.";
    if (!intIn(p.max_reschedules, 0, 10)) e.max_reschedules = "Enter 0–10.";
  }
  if (step === 4) {
    const a = c.agent;
    if (!a.agent_name.trim()) e.agent_name = "Name the agent.";
    if (!a.greeting.trim()) e.greeting = "Write a greeting.";
    if (a.supported_intents.length === 0)
      e.intents = "Select at least one intent.";
    if (a.allowed_capabilities.length === 0)
      e.capabilities = "Select at least one capability.";
  }
  return e;
}

export function emptyConfig(): ClinicConfig {
  return {
    details: {
      name: "",
      specialty: "",
      location: "",
      timezone: "America/Chicago",
      phone: "",
      email: "",
    },
    hours: [],
    appointment_types: [],
    policy: {
      min_notice_hours: 2,
      max_advance_days: 60,
      same_day_booking: true,
      cancellation_window_hours: 24,
      cancellation_notes: "",
      reschedule_window_hours: 24,
      max_reschedules: 2,
    },
    agent: {
      agent_name: "",
      greeting: "",
      supported_intents: [],
      escalation_instructions: "",
      allowed_capabilities: [],
    },
  };
}
