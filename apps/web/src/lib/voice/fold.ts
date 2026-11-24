import type { CallEvent } from "@/lib/api/types";
import type { ToolExecution, TranscriptTurn } from "@/components/voice/types";

const TOOL_LABEL: Record<string, string> = {
  get_clinic_information: "Looking up clinic information",
  get_appointment_availability: "Checking availability",
  verify_patient: "Verifying the caller",
  get_patient_appointments: "Looking up the caller's appointments",
  propose_booking: "Preparing a booking",
  propose_reschedule: "Preparing a reschedule",
  propose_cancellation: "Preparing a cancellation",
  withdraw_pending_proposal: "Withdrawing the pending change",
  confirm_operation: "Applying the confirmed change",
  get_operation_status: "Checking the result of a change",
  request_human_escalation: "Requesting a hand-off to staff",
};

export function toolLabel(name: string): string {
  return TOOL_LABEL[name] ?? name.replace(/_/g, " ");
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** Fold the ordered event log into what the page shows. Pure, so it is easy to test. */
export function foldEvents(events: CallEvent[]): {
  turns: TranscriptTurn[];
  tools: ToolExecution[];
} {
  const turns: TranscriptTurn[] = [];
  const tools = new Map<string, ToolExecution>();
  const t0 = events.length ? Date.parse(events[0].occurred_at) : 0;
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    const p = e.payload;
    if (e.kind === "transcript") {
      const text = str(p.text).trim();
      if (!text && !p.interrupted) continue;
      turns.push({
        id: e.event_id,
        speaker: p.speaker === "agent" ? "agent" : "caller",
        text: text || "(interrupted)",
        atSeconds: Math.max(0, (Date.parse(e.occurred_at) - t0) / 1000),
        interrupted: p.interrupted === true,
      });
    } else if (e.kind === "tool") {
      const id = str(p.call_id) || e.event_id;
      const name = str(p.name);
      const prior = tools.get(id);
      if (p.phase === "started") {
        tools.set(id, {
          id,
          name,
          status: "running",
          summary: toolLabel(name),
          technical: JSON.stringify(p.args ?? {}, null, 2),
        });
      } else if (p.phase === "finished") {
        const status = str(p.status);
        tools.set(id, {
          id,
          name,
          status:
            status === "ok" ||
            status === "committed" ||
            status === "needs_input"
              ? "succeeded"
              : status === "uncertain"
                ? "uncertain"
                : "failed",
          summary: str(p.message) || toolLabel(name),
          technical: [
            prior?.technical,
            JSON.stringify(
              { status, code: p.code, latency_ms: p.latency_ms },
              null,
              2,
            ),
          ]
            .filter(Boolean)
            .join("\n"),
          resultStatus: status,
        });
      }
    }
  }
  return { turns, tools: [...tools.values()] };
}
