"use client";

import { use, useEffect, useState } from "react";
import { ClinicSelector } from "@/components/clinic-selector";
import {
  CategoryGroupCard,
  ReadinessPanel,
  ResultInspector,
  RunHistory,
  RunPill,
  RunProgress,
  countsText,
} from "@/components/evaluations/evaluation-parts";
import { Icon } from "@/components/icons";
import { EmptyState } from "@/components/primitives";
import { Notice, PageHeader, inputCls, primaryBtn } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { EvalMode, EvalRunDetail } from "@/lib/api/types";
import { useFetch } from "@/lib/use-fetch";

const message = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong";

export default function Evaluations({
  searchParams,
}: {
  searchParams: Promise<{ clinic?: string; run?: string }>;
}) {
  // Deep link from a call: /evaluations?clinic=<id>&run=<id>
  const link = use(searchParams);
  const [clinicId, setClinicId] = useState(link.clinic ?? "");
  const [version, setVersion] = useState(""); // "" = latest published
  const [mode, setMode] = useState<EvalMode>("workflow");
  const [scope, setScope] = useState("all"); // "all" or a category id
  const [activeId, setActiveId] = useState<string | null>(link.run ?? null);
  const [run, setRun] = useState<EvalRunDetail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const catalog = useFetch("eval-catalog", () => api.evalCatalog());
  const versions = useFetch(`versions-${clinicId}`, () =>
    clinicId ? api.listVersions(clinicId) : Promise.resolve([]),
  );
  const runs = useFetch(`runs-${clinicId}-${refresh}`, () =>
    clinicId ? api.listEvalRuns(clinicId) : Promise.resolve([]),
  );
  const readiness = useFetch(
    `readiness-${clinicId}-${version}-${refresh}`,
    () =>
      clinicId && versions.data?.length
        ? api.evalReadiness(clinicId, version ? Number(version) : undefined)
        : Promise.resolve(null),
  );

  // The run on screen: the one the user opened, else the most recent persisted run.
  const shownId = activeId ?? runs.data?.[0]?.id ?? null;
  const current = run && run.id === shownId ? run : null;

  useEffect(() => {
    if (!clinicId || !shownId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const d = await api.getEvalRun(clinicId, shownId);
        if (stop) return;
        setRun(d);
        setRunError(null);
        if (d.status === "queued" || d.status === "running") {
          timer = setTimeout(poll, 1000);
        } else {
          setRefresh((n) => n + 1);
        }
      } catch (e) {
        if (!stop) setRunError(message(e));
      }
    };
    void poll();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [clinicId, shownId]);

  const active = current && ["queued", "running"].includes(current.status);
  const modeInfo = catalog.data?.modes.find((m) => m.mode === mode);
  const published = versions.data ?? [];
  const canRun =
    !!clinicId &&
    published.length > 0 &&
    !!modeInfo?.available &&
    !starting &&
    !active;

  const detail = useFetch(`result-${current?.id}-${selected}`, () =>
    current && selected && clinicId
      ? api.getEvalResult(clinicId, current.id, selected)
      : Promise.resolve(null),
  );

  async function start() {
    setStarting(true);
    setActionError(null);
    try {
      const created = await api.startEvalRun(clinicId, {
        mode,
        ...(version ? { config_version: Number(version) } : {}),
        selection:
          scope === "all"
            ? { kind: "all" }
            : { kind: "category", value: scope },
      });
      setSelected(null);
      setActiveId(created.id);
      setRefresh((n) => n + 1);
    } catch (e) {
      setActionError(message(e));
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    if (!current) return;
    setCancelling(true);
    try {
      await api.cancelEvalRun(clinicId, current.id);
      setRefresh((n) => n + 1);
    } catch (e) {
      setActionError(message(e));
    } finally {
      setCancelling(false);
    }
  }

  async function rerun() {
    if (!current || !selected) return;
    setRerunning(true);
    setActionError(null);
    try {
      const created = await api.rerunEvalScenario(
        clinicId,
        current.id,
        selected,
      );
      setSelected(null);
      setActiveId(created.id);
      setRefresh((n) => n + 1);
    } catch (e) {
      setActionError(message(e));
    } finally {
      setRerunning(false);
    }
  }

  const noRuns =
    !!clinicId && !runs.loading && !runs.error && !runs.data?.length;

  return (
    <>
      <PageHeader
        title="Evaluations"
        subtitle="Check an agent against automated scenarios before deployment."
        action={
          <button
            type="button"
            className={primaryBtn}
            disabled={!canRun}
            onClick={() => void start()}
          >
            <Icon name="play" className="h-4 w-4" />{" "}
            {starting ? "Starting…" : "Run evaluation"}
          </button>
        }
      />

      <div className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <ClinicSelector
          label="Clinic"
          value={clinicId}
          onChange={(id) => {
            setClinicId(id);
            setVersion("");
            setActiveId(null);
            setRun(null);
            setSelected(null);
            setActionError(null);
          }}
        />
        <div>
          <label
            className="mb-1 block text-sm font-medium"
            htmlFor="version-select"
          >
            Published version
          </label>
          <select
            id="version-select"
            className={inputCls}
            value={version}
            disabled={!clinicId || published.length === 0}
            onChange={(e) => setVersion(e.target.value)}
          >
            <option value="">
              {published.length
                ? `Latest (v${Math.max(...published.map((v) => v.version))})`
                : "Nothing published"}
            </option>
            {published.map((v) => (
              <option key={v.version} value={v.version}>
                Version {v.version}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label
            className="mb-1 block text-sm font-medium"
            htmlFor="mode-select"
          >
            Evaluation mode
          </label>
          <select
            id="mode-select"
            className={inputCls}
            value={mode}
            onChange={(e) => setMode(e.target.value as EvalMode)}
          >
            {(catalog.data?.modes ?? []).map((m) => (
              <option key={m.mode} value={m.mode}>
                {m.label}
                {m.available ? "" : " (not run)"}
              </option>
            ))}
          </select>
          {modeInfo && !modeInfo.available && (
            <p
              data-testid="mode-unavailable"
              className="mt-1 text-xs text-muted"
            >
              Not run: {modeInfo.reason}
            </p>
          )}
        </div>
        <div>
          <label
            className="mb-1 block text-sm font-medium"
            htmlFor="scope-select"
          >
            Scenarios
          </label>
          <select
            id="scope-select"
            className={inputCls}
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="all">All scenarios</option>
            {(catalog.data?.categories ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-4">
        {catalog.error && (
          <Notice tone="error">
            Could not load scenarios: {catalog.error}
          </Notice>
        )}
        {actionError && <Notice tone="error">{actionError}</Notice>}
        {runError && (
          <Notice tone="error">Could not load the run: {runError}</Notice>
        )}
        {clinicId && !versions.loading && published.length === 0 && (
          <Notice tone="info">
            Publish a configuration before running an evaluation.
          </Notice>
        )}

        {clinicId && readiness.data && (
          <ReadinessPanel readiness={readiness.data} />
        )}
        {readiness.error && (
          <Notice tone="error">
            Could not load readiness: {readiness.error}
          </Notice>
        )}

        {!clinicId && (
          <EmptyState
            testId="select-clinic"
            icon={<Icon name="evaluations" />}
            title="Choose a clinic"
          >
            Select a clinic to run or review evaluations.
          </EmptyState>
        )}

        {noRuns && !active && (
          <EmptyState
            testId="evaluations-empty"
            icon={<Icon name="evaluations" />}
            title="No evaluation runs"
          >
            Run your first evaluation to check this agent&apos;s scheduling
            behavior.
          </EmptyState>
        )}

        {current && active && (
          <RunProgress
            run={current}
            onCancel={() => void cancel()}
            cancelling={cancelling}
          />
        )}

        {current && !active && (
          <section aria-label="Evaluation results" className="space-y-3">
            <div
              data-testid="run-summary"
              className="flex flex-wrap items-center gap-3"
            >
              <RunPill status={current.status} />
              <p className="text-sm">
                {current.mode_label} · version {current.config_version} ·{" "}
                <span data-testid="run-counts">
                  {countsText(current.counts)}
                </span>
              </p>
            </div>
            {current.error && <Notice tone="error">{current.error}</Notice>}
            {current.categories.map((g) => (
              <CategoryGroupCard
                key={g.category}
                group={g}
                selectedId={selected}
                onSelect={setSelected}
              />
            ))}
            {selected && detail.loading && (
              <p className="text-sm text-muted">Loading result…</p>
            )}
            {selected && detail.error && (
              <Notice tone="error">
                Could not load the result: {detail.error}
              </Notice>
            )}
            {selected && detail.data && (
              <ResultInspector
                detail={detail.data}
                onRerun={() => void rerun()}
                rerunning={rerunning}
                canRerun={!active && !!modeInfo?.available}
              />
            )}
          </section>
        )}

        {runs.data && runs.data.length > 0 && (
          <section aria-label="Run history" className="space-y-2">
            <h2 className="text-sm font-medium text-muted">Previous runs</h2>
            <RunHistory
              runs={runs.data}
              activeId={shownId}
              onOpen={(id) => {
                setSelected(null);
                setActiveId(id);
              }}
            />
          </section>
        )}
        {runs.error && (
          <Notice tone="error">Could not load runs: {runs.error}</Notice>
        )}
      </div>
    </>
  );
}
