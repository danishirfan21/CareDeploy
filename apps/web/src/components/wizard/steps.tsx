"use client";

import { Field, inputCls } from "@/components/ui";
import {
  CAPABILITIES,
  INTENTS,
  type AppointmentTypeEntry,
  type Capability,
  type ClinicConfig,
  type Intent,
} from "@/lib/api/types";
import { TIMEZONES, WEEKDAYS, humanize } from "@/lib/format";
import type { StepErrors } from "./validation";

interface StepProps {
  config: ClinicConfig;
  onChange: (next: ClinicConfig) => void;
  errors: StepErrors;
}

function Err({ msg }: { msg?: string }) {
  return msg ? (
    <p role="alert" className="mt-1 text-xs text-red-600">
      {msg}
    </p>
  ) : null;
}

function toggle<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

export function DetailsStep({ config, onChange, errors }: StepProps) {
  const d = config.details;
  const set = (patch: Partial<typeof d>) =>
    onChange({ ...config, details: { ...d, ...patch } });
  return (
    <div className="space-y-4">
      <Field label="Clinic name" error={errors.name}>
        <input
          className={inputCls}
          value={d.name}
          onChange={(e) => set({ name: e.target.value })}
        />
      </Field>
      <Field label="Specialty" error={errors.specialty}>
        <input
          className={inputCls}
          value={d.specialty}
          onChange={(e) => set({ specialty: e.target.value })}
        />
      </Field>
      <Field label="Location" error={errors.location} hint="City and state">
        <input
          className={inputCls}
          value={d.location}
          onChange={(e) => set({ location: e.target.value })}
        />
      </Field>
      <Field label="Time zone" error={errors.timezone}>
        <select
          className={inputCls}
          value={d.timezone}
          onChange={(e) => set({ timezone: e.target.value })}
        >
          {TIMEZONES.map((tz) => (
            <option key={tz}>{tz}</option>
          ))}
        </select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Phone">
          <input
            className={inputCls}
            value={d.phone}
            onChange={(e) => set({ phone: e.target.value })}
          />
        </Field>
        <Field label="Email" error={errors.email}>
          <input
            className={inputCls}
            value={d.email}
            onChange={(e) => set({ email: e.target.value })}
          />
        </Field>
      </div>
    </div>
  );
}

export function HoursServicesStep({ config, onChange, errors }: StepProps) {
  const setHours = (
    weekday: number,
    patch: { opens?: string; closes?: string } | null,
  ) => {
    const rest = config.hours.filter((h) => h.weekday !== weekday);
    const cur = config.hours.find((h) => h.weekday === weekday);
    const next =
      patch === null
        ? rest
        : [
            ...rest,
            { weekday, opens: "09:00", closes: "17:00", ...cur, ...patch },
          ];
    onChange({ ...config, hours: next.sort((a, b) => a.weekday - b.weekday) });
  };
  const setType = (i: number, patch: Partial<AppointmentTypeEntry>) =>
    onChange({
      ...config,
      appointment_types: config.appointment_types.map((t, j) =>
        j === i ? { ...t, ...patch } : t,
      ),
    });

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-1 font-medium">Operating hours</h2>
        <p className="mb-3 text-sm text-muted">
          Select the days the clinic is open. Times are in the clinic&apos;s
          time zone.
        </p>
        <div className="divide-y divide-line rounded-xl border border-line">
          {WEEKDAYS.map((day, wd) => {
            const h = config.hours.find((x) => x.weekday === wd);
            return (
              <div
                key={day}
                className="flex flex-wrap items-center gap-3 px-4 py-2.5"
              >
                <label className="flex w-36 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!h}
                    onChange={(e) => setHours(wd, e.target.checked ? {} : null)}
                  />
                  {day}
                </label>
                {h && (
                  <>
                    <input
                      type="time"
                      aria-label={`${day} opens`}
                      className={`${inputCls} !w-auto`}
                      value={h.opens}
                      onChange={(e) => setHours(wd, { opens: e.target.value })}
                    />
                    <span className="text-muted">to</span>
                    <input
                      type="time"
                      aria-label={`${day} closes`}
                      className={`${inputCls} !w-auto`}
                      value={h.closes}
                      onChange={(e) => setHours(wd, { closes: e.target.value })}
                    />
                    <Err msg={errors[`hours-${wd}`]} />
                  </>
                )}
              </div>
            );
          })}
        </div>
        <Err msg={errors.hours} />
      </section>

      <section>
        <h2 className="mb-1 font-medium">Appointment types</h2>
        <p className="mb-3 text-sm text-muted">
          Types that need a person are escalated instead of booked by the agent.
        </p>
        <div className="space-y-3">
          {config.appointment_types.map((t, i) => (
            <div
              key={i}
              className="space-y-3 rounded-xl border border-line p-4"
            >
              <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
                <div>
                  <input
                    aria-label={`Appointment type ${i + 1} name`}
                    placeholder="Name"
                    className={inputCls}
                    value={t.name}
                    onChange={(e) => setType(i, { name: e.target.value })}
                  />
                  <Err msg={errors[`type-${i}-name`]} />
                </div>
                <div>
                  <input
                    type="number"
                    aria-label={`Appointment type ${i + 1} duration (minutes)`}
                    className={inputCls}
                    value={
                      Number.isNaN(t.duration_minutes) ? "" : t.duration_minutes
                    }
                    onChange={(e) =>
                      setType(i, { duration_minutes: e.target.valueAsNumber })
                    }
                  />
                  <Err msg={errors[`type-${i}-duration`]} />
                </div>
              </div>
              <input
                aria-label={`Appointment type ${i + 1} constraints`}
                placeholder="Constraints (optional)"
                className={inputCls}
                value={t.constraints}
                onChange={(e) => setType(i, { constraints: e.target.value })}
              />
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    aria-label={`Appointment type ${i + 1} requires human escalation`}
                    checked={t.requires_human_escalation}
                    onChange={(e) =>
                      setType(i, {
                        requires_human_escalation: e.target.checked,
                      })
                    }
                  />
                  Requires human escalation
                </label>
                <button
                  type="button"
                  className="text-sm text-muted hover:text-red-600"
                  onClick={() =>
                    onChange({
                      ...config,
                      appointment_types: config.appointment_types.filter(
                        (_, j) => j !== i,
                      ),
                    })
                  }
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
        <Err msg={errors.types} />
        <button
          type="button"
          className="mt-3 text-sm font-medium text-accent hover:underline"
          onClick={() =>
            onChange({
              ...config,
              appointment_types: [
                ...config.appointment_types,
                {
                  name: "",
                  duration_minutes: 30,
                  requires_human_escalation: false,
                  constraints: "",
                },
              ],
            })
          }
        >
          + Add appointment type
        </button>
      </section>
    </div>
  );
}

export function PolicyStep({ config, onChange, errors }: StepProps) {
  const p = config.policy;
  const set = (patch: Partial<typeof p>) =>
    onChange({ ...config, policy: { ...p, ...patch } });
  const num = (key: keyof typeof p, label: string, hint: string) => (
    <Field label={label} hint={hint} error={errors[key]}>
      <input
        type="number"
        className={inputCls}
        value={Number.isNaN(p[key] as number) ? "" : (p[key] as number)}
        onChange={(e) =>
          set({ [key]: e.target.valueAsNumber } as Partial<typeof p>)
        }
      />
    </Field>
  );
  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <h2 className="font-medium">Booking</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {num(
            "min_notice_hours",
            "Minimum notice (hours)",
            "Earliest a visit can be booked",
          )}
          {num(
            "max_advance_days",
            "Book up to (days ahead)",
            "Furthest-out bookable date",
          )}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={p.same_day_booking}
            onChange={(e) => set({ same_day_booking: e.target.checked })}
          />
          Allow same-day booking
        </label>
      </section>
      <section className="space-y-4">
        <h2 className="font-medium">Cancellation and rescheduling</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {num(
            "cancellation_window_hours",
            "Cancellation window (hours)",
            "Notice required",
          )}
          {num(
            "reschedule_window_hours",
            "Reschedule window (hours)",
            "Notice required",
          )}
          {num("max_reschedules", "Max reschedules", "Per appointment")}
        </div>
        <Field
          label="Cancellation notes"
          hint="Appointment-specific rules the agent should state"
        >
          <textarea
            className={inputCls}
            rows={3}
            value={p.cancellation_notes}
            onChange={(e) => set({ cancellation_notes: e.target.value })}
          />
        </Field>
      </section>
      <p className="text-xs text-muted">
        Appointment-specific constraints are set per type in the previous step.
      </p>
    </div>
  );
}

export function AgentStep({ config, onChange, errors }: StepProps) {
  const a = config.agent;
  const set = (patch: Partial<typeof a>) =>
    onChange({ ...config, agent: { ...a, ...patch } });
  return (
    <div className="space-y-5">
      <Field label="Agent name" error={errors.agent_name}>
        <input
          className={inputCls}
          value={a.agent_name}
          onChange={(e) => set({ agent_name: e.target.value })}
        />
      </Field>
      <Field label="Greeting" error={errors.greeting}>
        <textarea
          className={inputCls}
          rows={3}
          value={a.greeting}
          onChange={(e) => set({ greeting: e.target.value })}
        />
      </Field>
      <fieldset>
        <legend className="mb-1 text-sm font-medium">Supported intents</legend>
        <div className="space-y-1.5">
          {INTENTS.map((i) => (
            <label key={i} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                aria-label={`Intent: ${humanize(i)}`}
                checked={a.supported_intents.includes(i)}
                onChange={() =>
                  set({
                    supported_intents: toggle<Intent>(a.supported_intents, i),
                  })
                }
              />
              {humanize(i)}
            </label>
          ))}
        </div>
        <Err msg={errors.intents} />
      </fieldset>
      <fieldset>
        <legend className="mb-1 text-sm font-medium">
          Allowed capabilities
        </legend>
        <div className="space-y-1.5">
          {CAPABILITIES.map((c) => (
            <label key={c} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                aria-label={`Capability: ${humanize(c)}`}
                checked={a.allowed_capabilities.includes(c)}
                onChange={() =>
                  set({
                    allowed_capabilities: toggle<Capability>(
                      a.allowed_capabilities,
                      c,
                    ),
                  })
                }
              />
              {humanize(c)}
            </label>
          ))}
        </div>
        <Err msg={errors.capabilities} />
      </fieldset>
      <Field
        label="Escalation instructions"
        hint="When and how the agent hands off to a person. Required if any appointment type needs human escalation."
      >
        <textarea
          className={inputCls}
          rows={4}
          value={a.escalation_instructions}
          onChange={(e) => set({ escalation_instructions: e.target.value })}
        />
      </Field>
    </div>
  );
}
