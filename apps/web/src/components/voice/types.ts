/** Data shapes for the voice playground. M3 will populate these from live calls. */
export type Speaker = "caller" | "agent";

export interface TranscriptTurn {
  id: string;
  speaker: Speaker;
  text: string;
  /** Seconds from the start of the call. */
  atSeconds?: number;
  latencyMs?: number;
}

export type ToolStatus = "running" | "succeeded" | "failed";

export interface ToolExecution {
  id: string;
  name: string;
  status: ToolStatus;
  summary: string;
  /** Raw request/response text shown in the collapsed technical details. */
  technical?: string;
}

export type CallPhase =
  "unavailable" | "idle" | "connecting" | "active" | "ended";

export interface CallOutcomeData {
  result: "resolved" | "escalated" | "failed";
  summary: string;
}
