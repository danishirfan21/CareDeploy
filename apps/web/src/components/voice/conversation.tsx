import { StatusIndicator } from "@/components/primitives";
import { Icon } from "@/components/icons";
import type {
  CallOutcomeData,
  Speaker,
  ToolExecution,
  TranscriptTurn,
} from "./types";

function clock(s?: number) {
  if (s === undefined) return null;
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

const LABEL: Record<Speaker, string> = { caller: "Caller", agent: "Agent" };

export function ConversationMessage({ turn }: { turn: TranscriptTurn }) {
  const agent = turn.speaker === "agent";
  return (
    <li className={`flex ${agent ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[88%] rounded-2xl px-4 py-3 md:max-w-[80%] ${
          agent ? "border border-line bg-surface" : "bg-surface-low"
        }`}
      >
        <p
          className={`mb-1 flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.04em] ${
            agent ? "text-primary" : "text-muted"
          }`}
        >
          <span>
            {LABEL[turn.speaker]}
            {clock(turn.atSeconds) && ` · ${clock(turn.atSeconds)}`}
          </span>
          {turn.latencyMs !== undefined && (
            <span className="ml-auto normal-case">
              {turn.latencyMs}ms latency
            </span>
          )}
        </p>
        <p className="text-[15px] leading-6">{turn.text}</p>
      </div>
    </li>
  );
}

export function ConversationTranscript({
  turns,
  label = "Conversation transcript",
}: {
  turns: TranscriptTurn[];
  label?: string;
}) {
  return (
    <ol aria-label={label} className="space-y-3" data-testid="transcript">
      {turns.map((t) => (
        <ConversationMessage key={t.id} turn={t} />
      ))}
    </ol>
  );
}

const TOOL_TONE = {
  running: "info",
  succeeded: "success",
  failed: "danger",
} as const;

/** Inline record of one tool execution; technical payload stays collapsed. */
export function ToolActivity({ tool }: { tool: ToolExecution }) {
  return (
    <div className="rounded-xl bg-surface-low px-4 py-3 text-sm">
      <div className="flex items-center gap-2">
        <Icon name="wrench" className="h-4 w-4 text-muted" />
        <span className="font-mono text-[13px]">{tool.name}</span>
        <span className="ml-auto">
          <StatusIndicator tone={TOOL_TONE[tool.status]}>
            {tool.status}
          </StatusIndicator>
        </span>
      </div>
      <p className="mt-1 text-muted">{tool.summary}</p>
      {tool.technical && (
        <details className="mt-2">
          <summary className="cursor-pointer font-mono text-[11px] tracking-[0.04em] text-muted">
            Technical details
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-surface p-3 font-mono text-xs">
            {tool.technical}
          </pre>
        </details>
      )}
    </div>
  );
}

export function ToolChain({ tools }: { tools: ToolExecution[] }) {
  return (
    <ul aria-label="Tool executions" className="space-y-2">
      {tools.map((t) => (
        <li key={t.id}>
          <ToolActivity tool={t} />
        </li>
      ))}
    </ul>
  );
}

const OUTCOME = {
  resolved: { tone: "success", label: "Outcome resolved" },
  escalated: { tone: "warning", label: "Escalated to staff" },
  failed: { tone: "danger", label: "Call failed" },
} as const;

export function CallOutcome({ outcome }: { outcome: CallOutcomeData }) {
  const o = OUTCOME[outcome.result];
  return (
    <div
      className="rounded-xl bg-surface-low px-4 py-3"
      data-testid="call-outcome"
    >
      <StatusIndicator tone={o.tone}>{o.label}</StatusIndicator>
      <p className="mt-2 text-sm">{outcome.summary}</p>
    </div>
  );
}
