/** Data shapes for the voice playground. M3 will populate these from live calls. */
export type Speaker = "caller" | "agent";

export interface TranscriptTurn {
  id: string;
  speaker: Speaker;
  text: string;
  /** Seconds from the start of the call. */
  atSeconds?: number;
  latencyMs?: number;
  /** The caller cut the agent off; `text` is only what was actually spoken. */
  interrupted?: boolean;
}

export type ToolStatus = "running" | "succeeded" | "failed" | "uncertain";

export interface ToolExecution {
  id: string;
  name: string;
  status: ToolStatus;
  /** The backend tool result status (committed, rejected, uncertain, ...). */
  resultStatus?: string;
  summary: string;
  /** Raw request/response text shown in the collapsed technical details. */
  technical?: string;
}

export type CallPhase =
  | "unavailable"
  | "idle"
  | "starting"
  | "connecting"
  | "active"
  | "ending"
  | "ended";

export interface CallOutcomeData {
  result: "resolved" | "escalated" | "failed";
  summary: string;
}
