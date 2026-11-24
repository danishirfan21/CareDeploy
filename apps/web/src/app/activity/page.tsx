"use client";

import { useState } from "react";
import { ClinicSelector } from "@/components/clinic-selector";
import {
  CategoryGroupCard,
  RunHistory,
  RunPill,
  countsText,
} from "@/components/evaluations/evaluation-parts";
import { Icon } from "@/components/icons";
import { EmptyState } from "@/components/primitives";
import { Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useFetch } from "@/lib/use-fetch";

type Tab = "calls" | "evaluations";

/** Persisted evaluation runs for one clinic. Read-only: runs are started on the Evaluations page. */
function EvaluationActivity({
  clinicId,
  onClinic,
  onCount,
}: {
  clinicId: string;
  onClinic: (id: string) => void;
  onCount: (n: number) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const runs = useFetch(`activity-runs-${clinicId}`, async () => {
    const list = clinicId ? await api.listEvalRuns(clinicId, 50) : [];
    onCount(list.length);
    return list;
  });
  const run = useFetch(`activity-run-${clinicId}-${openId}`, () =>
    clinicId && openId
      ? api.getEvalRun(clinicId, openId)
      : Promise.resolve(null),
  );
  return (
    <div className="space-y-4">
      <div className="max-w-sm">
        <ClinicSelector
          label="Clinic"
          value={clinicId}
          onChange={(id) => {
            setOpenId(null);
            onClinic(id);
          }}
        />
      </div>
      {!clinicId && (
        <EmptyState
          testId="unavailable"
          icon={<Icon name="activity" />}
          title="Choose a clinic"
        >
          Select a clinic to see its evaluation runs.
        </EmptyState>
      )}
      {runs.error && (
        <Notice tone="error">Could not load runs: {runs.error}</Notice>
      )}
      {clinicId && !runs.loading && !runs.error && !runs.data?.length && (
        <EmptyState
          testId="unavailable"
          icon={<Icon name="activity" />}
          title="No evaluation runs yet"
        >
          Run your first evaluation to check this agent&apos;s scheduling
          behavior.
        </EmptyState>
      )}
      {runs.data && runs.data.length > 0 && (
        <RunHistory runs={runs.data} activeId={openId} onOpen={setOpenId} />
      )}
      {run.error && (
        <Notice tone="error">Could not load the run: {run.error}</Notice>
      )}
      {run.data && (
        <section
          aria-label="Evaluation run detail"
          data-testid="activity-detail"
          className="space-y-3"
        >
          <p className="flex flex-wrap items-center gap-3 text-sm">
            <RunPill status={run.data.status} />
            {run.data.mode_label} · version {run.data.config_version} ·{" "}
            {countsText(run.data.counts)}
          </p>
          {run.data.error && <Notice tone="error">{run.data.error}</Notice>}
          {run.data.categories.map((g) => (
            <CategoryGroupCard
              key={g.category}
              group={g}
              selectedId={null}
              onSelect={() => undefined}
            />
          ))}
        </section>
      )}
    </div>
  );
}

export default function Activity() {
  const [tab, setTab] = useState<Tab>("calls");
  const [clinicId, setClinicId] = useState("");
  const [evalCount, setEvalCount] = useState(0);
  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: "calls", label: "Calls", count: 0 },
    { id: "evaluations", label: "Evaluations", count: evalCount },
  ];
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
        {tabs.map((t) => (
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
              {t.count}
            </span>
          </button>
        ))}
      </div>
      <div role="tabpanel" id="activity-panel" aria-labelledby={`tab-${tab}`}>
        {tab === "calls" ? (
          <EmptyState
            testId="unavailable"
            icon={<Icon name="activity" />}
            title="No calls yet"
          >
            Call history appears here once calls are made from the Playground.
          </EmptyState>
        ) : (
          <EvaluationActivity
            clinicId={clinicId}
            onClinic={setClinicId}
            onCount={setEvalCount}
          />
        )}
      </div>
    </>
  );
}
