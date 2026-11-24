import { Icon } from "@/components/icons";
import { Card, StatusIndicator, type Tone } from "@/components/primitives";
import {
  CallOutcome,
  ConversationTranscript,
  ToolChain,
} from "@/components/voice/conversation";
import type {
  CallOutcomeData,
  ToolExecution,
  TranscriptTurn,
} from "@/components/voice/types";

export interface ActivityItem {
  id: string;
  title: string;
  subtitle: string;
  /** Pre-formatted timestamp text. */
  when: string;
  statusLabel: string;
  tone: Tone;
  duration?: string;
}

export function ActivityList({
  items,
  selectedId,
  onSelect,
  label,
}: {
  items: ActivityItem[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
  label: string;
}) {
  return (
    <ul aria-label={label} className="space-y-2">
      {items.map((i) => (
        <li key={i.id}>
          <button
            type="button"
            onClick={() => onSelect(i.id)}
            aria-current={i.id === selectedId ? "true" : undefined}
            className={`flex w-full items-center gap-4 rounded-2xl border bg-surface px-4 py-4 text-left ${
              i.id === selectedId ? "border-accent" : "border-line"
            }`}
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate text-lg font-medium">
                {i.title}
              </span>
              <span className="block truncate text-sm text-muted">
                {i.subtitle} ·{" "}
                <span className="font-mono text-xs">{i.when}</span>
              </span>
            </span>
            <span className="flex flex-col items-end gap-1">
              <StatusIndicator tone={i.tone}>{i.statusLabel}</StatusIndicator>
              {i.duration && (
                <span className="font-mono text-xs text-muted">
                  {i.duration}
                </span>
              )}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export interface CallDetailData {
  title: string;
  outcome?: CallOutcomeData;
  turns: TranscriptTurn[];
  tools: ToolExecution[];
  technical?: string;
}

/** Detail panel for one call; technical diagnostics are collapsed by default. */
export function ActivityDetail({ detail }: { detail: CallDetailData }) {
  return (
    <Card className="p-5 md:p-6">
      <div data-testid="activity-detail" className="space-y-6">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.04em] text-primary">
            Inspection focus
          </p>
          <h2 className="text-xl font-medium">{detail.title}</h2>
        </div>
        {detail.outcome && <CallOutcome outcome={detail.outcome} />}
        <section>
          <h3 className="mb-3 font-mono text-[11px] uppercase tracking-[0.04em] text-muted">
            Conversation transcript
          </h3>
          <ConversationTranscript turns={detail.turns} />
        </section>
        {detail.tools.length > 0 && (
          <section>
            <h3 className="mb-3 font-mono text-[11px] uppercase tracking-[0.04em] text-muted">
              Executed tool chain
            </h3>
            <ToolChain tools={detail.tools} />
          </section>
        )}
        {detail.technical && (
          <details className="rounded-xl bg-surface-low px-4 py-3">
            <summary className="flex cursor-pointer items-center gap-2 font-mono text-[11px] tracking-[0.04em] text-muted">
              <Icon name="chevronDown" className="h-4 w-4" /> Technical
              diagnostics
            </summary>
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-xs">
              {detail.technical}
            </pre>
          </details>
        )}
      </div>
    </Card>
  );
}
