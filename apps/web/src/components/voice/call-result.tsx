import Link from "next/link";
import { StatusIndicator } from "@/components/primitives";
import type { CallOutcomeKind, VoiceSession } from "@/lib/api/types";

const OUTCOME: Record<
  CallOutcomeKind,
  { tone: "success" | "warning" | "danger" | "neutral"; label: string }
> = {
  appointment_booked: { tone: "success", label: "Appointment booked" },
  appointment_rescheduled: {
    tone: "success",
    label: "Appointment rescheduled",
  },
  appointment_cancelled: { tone: "success", label: "Appointment cancelled" },
  information_provided: { tone: "neutral", label: "Information provided" },
  escalated: { tone: "warning", label: "Referred to staff" },
  no_action: { tone: "neutral", label: "No action taken" },
  failed: { tone: "danger", label: "Call failed" },
};

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "unknown";
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** After-call outcome: result, plain-language summary and duration; no raw payloads. */
export function CallResult({
  session,
  detailsHref,
}: {
  session: VoiceSession;
  detailsHref?: string;
}) {
  const o = session.outcome ? OUTCOME[session.outcome] : null;
  return (
    <div
      className="rounded-xl bg-surface-low px-4 py-4"
      data-testid="call-outcome"
    >
      <div className="flex flex-wrap items-center gap-3">
        <StatusIndicator tone={o?.tone ?? "neutral"}>
          {o?.label ?? "Outcome pending"}
        </StatusIndicator>
        <span className="font-mono text-[11px] tracking-[0.04em] text-muted">
          Duration {formatDuration(session.duration_seconds)}
        </span>
      </div>
      {session.summary && <p className="mt-2 text-sm">{session.summary}</p>}
      {session.error && (
        <p className="mt-2 text-sm text-danger">{session.error}</p>
      )}
      {detailsHref && (
        <Link
          href={detailsHref}
          className="mt-3 inline-block text-sm font-medium text-primary underline"
        >
          View call details
        </Link>
      )}
    </div>
  );
}
