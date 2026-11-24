"use client";

import { useState } from "react";
import {
  ActivityDetail,
  ActivityList,
  type ActivityItem,
} from "@/components/activity/activity-parts";
import {
  EvaluationGroup,
  EvaluationSummary,
} from "@/components/evaluations/evaluation-parts";
import { PageHeader } from "@/components/ui";
import { Notice } from "@/components/ui";
import { CallControls } from "@/components/voice/call-controls";
import {
  CallOutcome,
  ConversationTranscript,
  ToolChain,
} from "@/components/voice/conversation";
import type { ToolExecution, TranscriptTurn } from "@/components/voice/types";

/**
 * Development-only preview of the typed UI components with obviously labelled sample data.
 * Not linked from navigation. M3 and M4 replace the sample props with real call and
 * evaluation data.
 */
const TURNS: TranscriptTurn[] = [
  { id: "1", speaker: "caller", text: "Sample caller line.", atSeconds: 4 },
  {
    id: "2",
    speaker: "agent",
    text: "Sample agent reply.",
    atSeconds: 19,
    latencyMs: 380,
  },
];
const TOOLS: ToolExecution[] = [
  {
    id: "t1",
    name: "sample_tool",
    status: "succeeded",
    summary: "Sample tool result.",
    technical: '{"sample": true}',
  },
];
const ITEMS: ActivityItem[] = [
  {
    id: "a1",
    title: "Sample call",
    subtitle: "Sample clinic",
    when: "00:00",
    statusLabel: "Completed",
    tone: "success",
    duration: "1m 14s",
  },
];

export default function UiPreview() {
  const [selected, setSelected] = useState<string | null>("a1");
  return (
    <div className="space-y-10">
      <PageHeader title="UI component preview" />
      <Notice tone="warning">
        Development preview. Everything below is sample data used to exercise
        the components; none of it is real call or evaluation output.
      </Notice>
      <section aria-label="Transcript preview" className="space-y-4">
        <ConversationTranscript turns={TURNS} />
        <ToolChain tools={TOOLS} />
        <CallOutcome
          outcome={{ result: "resolved", summary: "Sample outcome." }}
        />
        <CallControls phase="active" muted={false} />
      </section>
      <section aria-label="Evaluation preview" className="space-y-3">
        <EvaluationSummary summary={{ passed: 1, total: 2 }} />
        <EvaluationGroup
          group={{
            id: "g1",
            name: "Sample group",
            results: [
              { id: "r1", name: "Sample passing scenario", status: "pass" },
              {
                id: "r2",
                name: "Sample failing scenario",
                status: "fail",
                critical: true,
                expected: "Sample expected behaviour.",
                observed: "Sample observed behaviour.",
              },
            ],
          }}
        />
      </section>
      <section aria-label="Activity preview" className="space-y-3">
        <ActivityList
          label="Sample activity"
          items={ITEMS}
          selectedId={selected}
          onSelect={setSelected}
        />
        <ActivityDetail
          detail={{
            title: "Sample call detail",
            outcome: { result: "resolved", summary: "Sample outcome." },
            turns: TURNS,
            tools: TOOLS,
            technical: "sample diagnostics",
          }}
        />
      </section>
    </div>
  );
}
