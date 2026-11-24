import { WEEKDAYS, formatTime, humanize } from "@/lib/format";
import type { ClinicConfig } from "@/lib/api/types";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-line py-5 first:border-t-0 first:pt-0">
      <h3 className="mb-2 text-sm font-medium text-muted">{title}</h3>
      <div className="text-sm">{children}</div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-4 py-0.5">
      <dt className="w-44 shrink-0 text-muted">{k}</dt>
      <dd className="min-w-0">{v}</dd>
    </div>
  );
}

export function ConfigSummary({ config }: { config: ClinicConfig }) {
  const {
    details: d,
    hours,
    appointment_types: types,
    policy: p,
    agent: a,
  } = config;
  return (
    <div data-testid="config-summary">
      <Section title="Clinic">
        <dl>
          <Row k="Name" v={d.name} />
          <Row k="Specialty" v={d.specialty} />
          <Row k="Location" v={d.location} />
          <Row k="Time zone" v={d.timezone} />
          <Row k="Phone" v={d.phone || "—"} />
          <Row k="Email" v={d.email || "—"} />
        </dl>
      </Section>
      <Section title="Operating hours">
        {hours.length === 0 ? (
          "No operating days"
        ) : (
          <dl>
            {hours.map((h) => (
              <Row
                key={h.weekday}
                k={WEEKDAYS[h.weekday]}
                v={`${formatTime(h.opens)} – ${formatTime(h.closes)}`}
              />
            ))}
          </dl>
        )}
      </Section>
      <Section title="Appointment types">
        {types.length === 0 ? (
          "None"
        ) : (
          <ul className="space-y-1">
            {types.map((t) => (
              <li key={t.name}>
                {t.name} · {t.duration_minutes} min
                {t.requires_human_escalation && (
                  <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
                    Human escalation
                  </span>
                )}
                {t.constraints && (
                  <div className="text-xs text-muted">{t.constraints}</div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Scheduling rules">
        <dl>
          <Row k="Minimum notice" v={`${p.min_notice_hours} hours`} />
          <Row k="Book up to" v={`${p.max_advance_days} days ahead`} />
          <Row
            k="Same-day booking"
            v={p.same_day_booking ? "Allowed" : "Not allowed"}
          />
          <Row
            k="Cancellation window"
            v={`${p.cancellation_window_hours} hours`}
          />
          <Row k="Reschedule window" v={`${p.reschedule_window_hours} hours`} />
          <Row k="Max reschedules" v={p.max_reschedules} />
          {p.cancellation_notes && (
            <Row k="Cancellation notes" v={p.cancellation_notes} />
          )}
        </dl>
      </Section>
      <Section title="Agent behavior">
        <dl>
          <Row k="Agent name" v={a.agent_name || "—"} />
          <Row k="Greeting" v={a.greeting || "—"} />
          <Row
            k="Supported intents"
            v={a.supported_intents.map(humanize).join(", ") || "—"}
          />
          <Row
            k="Allowed capabilities"
            v={a.allowed_capabilities.map(humanize).join(", ") || "—"}
          />
          <Row k="Escalation" v={a.escalation_instructions || "—"} />
        </dl>
      </Section>
    </div>
  );
}
