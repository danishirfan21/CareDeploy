"use client";

import { useState } from "react";
import { Icon } from "@/components/icons";
import { PageHeader } from "@/components/ui";
import { EmptyState } from "@/components/primitives";

type Tab = "calls" | "evaluations";

const TABS: { id: Tab; label: string }[] = [
  { id: "calls", label: "Calls" },
  { id: "evaluations", label: "Evaluations" },
];

/** No call or evaluation records exist yet (M3/M4 produce them), so both tabs are empty. */
export default function Activity() {
  const [tab, setTab] = useState<Tab>("calls");
  const empty: Record<Tab, { title: string; body: string }> = {
    calls: {
      title: "No calls yet",
      body: "Not available yet. Call history appears here once voice testing exists (milestone M3).",
    },
    evaluations: {
      title: "No evaluation runs yet",
      body: "Not available yet. Evaluation history appears here once evaluations exist (milestone M4).",
    },
  };
  return (
    <>
      <PageHeader
        title="Activity"
        subtitle="Review previous calls and evaluation runs."
      />
      <div
        role="tablist"
        aria-label="Activity type"
        className="mb-6 inline-flex rounded-full bg-surface-low p-1"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="activity-panel"
            onClick={() => setTab(t.id)}
            className={`flex min-h-10 items-center gap-2 rounded-full px-4 text-sm ${
              tab === t.id
                ? "bg-surface font-medium shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            {t.label}
            <span className="rounded-full bg-surface-high/70 px-1.5 font-mono text-[11px]">
              0
            </span>
          </button>
        ))}
      </div>
      <div role="tabpanel" id="activity-panel" aria-labelledby={`tab-${tab}`}>
        <EmptyState
          testId="unavailable"
          icon={<Icon name="activity" />}
          title={empty[tab].title}
        >
          {empty[tab].body}
        </EmptyState>
      </div>
    </>
  );
}
