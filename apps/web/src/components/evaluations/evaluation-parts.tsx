import { Icon } from "@/components/icons";
import { Card, StatusIndicator, type Tone } from "@/components/primitives";
import type {
  EvalCategoryGroup,
  EvalCounts,
  EvalModeReadiness,
  EvalReadiness,
  EvalResultDetail,
  EvalResultStatus,
  EvalRunSummary,
} from "@/lib/api/types";

export const RESULT_LABEL: Record<EvalResultStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  error: "Error",
  incomplete: "Incomplete",
  skipped: "Skipped",
  not_run: "Not run",
};

const RESULT_TONE: Record<EvalResultStatus, Tone> = {
  passed: "success",
  failed: "danger",
  error: "danger",
  incomplete: "warning",
  skipped: "neutral",
  not_run: "neutral",
};

const COUNT_ORDER: EvalResultStatus[] = [
  "passed",
  "failed",
  "error",
  "incomplete",
  "skipped",
  "not_run",
];

/** "3 passed · 1 failed": real counts only, zero entries omitted, never a percentage. */
export function countsText(counts: EvalCounts): string {
  const parts = COUNT_ORDER.filter((k) => (counts[k] ?? 0) > 0).map(
    (k) => `${counts[k]} ${RESULT_LABEL[k].toLowerCase()}`,
  );
  return parts.length ? parts.join(" · ") : "nothing run yet";
}

export function ResultPill({ status }: { status: EvalResultStatus }) {
  return (
    <StatusIndicator tone={RESULT_TONE[status]}>
      {RESULT_LABEL[status]}
    </StatusIndicator>
  );
}

const RUN_LABEL: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  incomplete: "Incomplete",
  cancelled: "Cancelled",
  error: "Error",
};
const RUN_TONE: Record<string, Tone> = {
  queued: "info",
  running: "info",
  completed: "success",
  incomplete: "warning",
  cancelled: "neutral",
  error: "danger",
};

export function RunPill({ status }: { status: string }) {
  return (
    <StatusIndicator tone={RUN_TONE[status] ?? "neutral"}>
      {RUN_LABEL[status] ?? status}
    </StatusIndicator>
  );
}

// --------------------------------------------------------------------------- readiness ----
const STATE_TEXT: Record<EvalModeReadiness["state"], string> = {
  not_run: "Not run",
  partial: "Partial run only",
  incomplete: "Did not finish",
  blocked: "Critical scenarios unmet",
  passed: "Passed",
};

/** Deployment readiness. Each evaluation mode is reported on its own line; they are never
 * merged into one score. */
export function ReadinessPanel({ readiness }: { readiness: EvalReadiness }) {
  const tone: Tone =
    readiness.level === "blocked"
      ? "danger"
      : readiness.level === "not_evaluated"
        ? "neutral"
        : "info";
  return (
    <Card className="p-6">
      <div data-testid="readiness" data-level={readiness.level}>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-medium">
            Deployment readiness · version {readiness.config_version}
          </h2>
          <StatusIndicator tone={tone}>{readiness.label}</StatusIndicator>
        </div>
        <p className="mt-2 text-sm text-muted">{readiness.statement}</p>
        <dl className="mt-4 grid gap-3 md:grid-cols-3">
          {(["workflow", "llm", "real_audio"] as const).map((m) => {
            const s = readiness.modes[m];
            return (
              <div
                key={m}
                data-testid={`mode-${m}`}
                className="rounded-xl bg-surface-low p-3"
              >
                <dt className="font-mono text-[11px] uppercase tracking-[0.04em] text-muted">
                  {s.label}
                </dt>
                <dd className="mt-1 text-sm font-medium">
                  {STATE_TEXT[s.state]}
                </dd>
                {s.counts && s.state !== "not_run" && (
                  <dd className="mt-0.5 text-xs text-muted">
                    {countsText(s.counts)}
                  </dd>
                )}
                {s.reason && (
                  <dd className="mt-0.5 text-xs text-muted">{s.reason}</dd>
                )}
              </div>
            );
          })}
        </dl>
        {readiness.blocking.length > 0 && (
          <ul
            data-testid="readiness-blocking"
            className="mt-4 space-y-1 text-sm text-danger"
          >
            {readiness.blocking.map((b) => (
              <li key={`${b.mode}-${b.scenario_id}`}>
                {b.scenario_id} {b.name}: {b.status} (critical)
              </li>
            ))}
          </ul>
        )}
        {readiness.notes.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
            {readiness.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------- progress ----
export function RunProgress({
  run,
  onCancel,
  cancelling,
}: {
  run: EvalRunSummary;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const done =
    (run.counts.total ?? 0) -
    (run.counts.not_run ?? 0) -
    (run.counts.skipped ?? 0);
  const finished = Math.max(0, Math.min(run.total, done));
  return (
    <Card className="p-6">
      <div data-testid="run-progress">
        <div className="flex flex-wrap items-center gap-3">
          <RunPill status={run.status} />
          <p className="flex-1 text-sm">
            {run.status === "queued"
              ? "Waiting for the evaluation worker to start."
              : `${finished} of ${run.total} scenarios finished.`}
            {run.current_scenario && (
              <>
                {" "}
                Current scenario:{" "}
                <span className="font-mono">{run.current_scenario}</span>
              </>
            )}
          </p>
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling || run.cancel_requested}
            className="min-h-10 rounded-full bg-surface-high/70 px-4 text-sm hover:bg-surface-high disabled:opacity-50"
          >
            {run.cancel_requested ? "Cancelling…" : "Cancel run"}
          </button>
        </div>
        <div
          role="progressbar"
          aria-label="Evaluation progress"
          aria-valuemin={0}
          aria-valuemax={run.total}
          aria-valuenow={finished}
          className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-high/70"
        >
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{
              width: `${run.total ? (finished / run.total) * 100 : 0}%`,
            }}
          />
        </div>
      </div>
    </Card>
  );
}

// ----------------------------------------------------------------------------- results ----
export function CategoryGroupCard({
  group,
  selectedId,
  onSelect,
}: {
  group: EvalCategoryGroup;
  selectedId: string | null;
  onSelect: (scenarioId: string) => void;
}) {
  const bad = group.results.some((r) =>
    ["failed", "error", "incomplete"].includes(r.status),
  );
  return (
    <Card>
      <details open className="group" data-testid={`group-${group.category}`}>
        <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 px-5 py-3">
          <span className={bad ? "text-danger" : "text-accent"}>
            <Icon name={bad ? "alertCircle" : "checkCircle"} />
          </span>
          <span className="flex-1 text-lg font-medium">{group.label}</span>
          <span
            data-testid="group-counts"
            className={`font-mono text-[11px] tracking-[0.04em] ${bad ? "text-danger" : "text-muted"}`}
          >
            {countsText(group.counts)}
          </span>
          <Icon
            name="chevronDown"
            className="h-5 w-5 text-muted transition-transform group-open:rotate-180"
          />
        </summary>
        <ul className="divide-y divide-line px-5 pb-3">
          {group.results.map((r) => (
            <li key={r.scenario_id}>
              <button
                type="button"
                onClick={() => onSelect(r.scenario_id)}
                aria-pressed={selectedId === r.scenario_id}
                data-testid={`result-${r.scenario_id}`}
                className={`flex min-h-12 w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm hover:bg-surface-low ${
                  selectedId === r.scenario_id ? "bg-surface-low" : ""
                }`}
              >
                <span className="font-mono text-[11px] text-muted">
                  {r.scenario_id}
                </span>
                <span className="min-w-0 flex-1">{r.name}</span>
                {r.severity === "critical" && r.status !== "passed" && (
                  <StatusIndicator tone="danger" dot={false}>
                    CRITICAL
                  </StatusIndicator>
                )}
                <ResultPill status={r.status} />
              </button>
            </li>
          ))}
        </ul>
      </details>
    </Card>
  );
}

// -------------------------------------------------------------------------- inspection ----
function asText(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** Failure inspection: expected vs observed, assertions, tool events, trace, raw JSON. */
export function ResultInspector({
  detail,
  onRerun,
  rerunning,
  canRerun,
}: {
  detail: EvalResultDetail;
  onRerun: () => void;
  rerunning: boolean;
  canRerun: boolean;
}) {
  const failedAssertions = detail.assertions.filter((a) => !a.passed);
  const tools = Array.isArray(detail.observed.tools)
    ? (detail.observed.tools as Record<string, unknown>[])
    : [];
  const unsuccessful = detail.status !== "passed";
  return (
    <Card className="p-6">
      <div data-testid="result-inspector" data-scenario={detail.scenario_id}>
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="flex-1 text-lg font-medium">
            <span className="font-mono text-sm text-muted">
              {detail.scenario_id}
            </span>{" "}
            {detail.name}
          </h3>
          <ResultPill status={detail.status} />
          <button
            type="button"
            onClick={onRerun}
            disabled={!canRerun || rerunning}
            className="min-h-10 rounded-full bg-primary px-4 text-sm text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {rerunning ? "Starting…" : "Rerun scenario"}
          </button>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="rounded-lg bg-surface-low p-3">
            <p className="font-mono text-[11px] uppercase tracking-[0.04em] text-muted">
              Expected
            </p>
            <p data-testid="inspector-expected" className="mt-1 text-sm">
              {asText(detail.expected.behavior ?? "")}
            </p>
          </div>
          <div className="rounded-lg bg-surface-low p-3">
            <p
              className={`font-mono text-[11px] uppercase tracking-[0.04em] ${unsuccessful ? "text-danger" : "text-muted"}`}
            >
              Observed
            </p>
            <p data-testid="inspector-observed" className="mt-1 text-sm">
              {detail.failure ??
                (detail.status === "passed"
                  ? "Every assertion held."
                  : "No result was recorded.")}
            </p>
          </div>
        </div>

        {failedAssertions.length > 0 && (
          <section className="mt-5" aria-label="Failed assertions">
            <h4 className="text-sm font-medium">Failed assertions</h4>
            <ul data-testid="failed-assertions" className="mt-2 space-y-2">
              {failedAssertions.map((a) => (
                <li
                  key={a.id}
                  className="rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm"
                >
                  <p className="font-mono text-[11px] text-danger">{a.type}</p>
                  <p className="mt-1">Expected: {a.expected}</p>
                  <p>Observed: {a.observed}</p>
                  {a.message && <p className="text-muted">{a.message}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="mt-5" aria-label="Assertions">
          <h4 className="text-sm font-medium">
            Assertions ({detail.assertions.length - failedAssertions.length} of{" "}
            {detail.assertions.length} held)
          </h4>
          <ul className="mt-2 divide-y divide-line text-sm">
            {detail.assertions.map((a) => (
              <li key={a.id} className="flex items-start gap-2 py-1.5">
                <span
                  className={`mt-0.5 font-mono text-[11px] ${a.passed ? "text-accent" : "text-danger"}`}
                >
                  {a.passed ? "PASS" : "FAIL"}
                </span>
                <span className="flex-1">{a.expected}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="mt-5" aria-label="Tool events">
          <h4 className="text-sm font-medium">Tool events ({tools.length})</h4>
          {tools.length === 0 ? (
            <p className="mt-1 text-sm text-muted">No tool was called.</p>
          ) : (
            <ol data-testid="tool-events" className="mt-2 space-y-1 text-sm">
              {tools.map((t, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[11px] text-muted">
                    {i + 1}
                  </span>
                  <span className="font-mono">{asText(t.tool)}</span>
                  <StatusIndicator
                    tone={t.ok ? "success" : "neutral"}
                    dot={false}
                  >
                    {asText(t.status)}
                  </StatusIndicator>
                </li>
              ))}
            </ol>
          )}
        </section>

        <details className="mt-5" data-testid="trace">
          <summary className="cursor-pointer text-sm font-medium">
            Execution trace ({detail.events.length} events)
          </summary>
          <ol className="mt-2 space-y-1 font-mono text-xs">
            {detail.events.map((e) => (
              <li key={e.seq}>
                <span className="text-muted">{e.seq}</span> {e.actor}{" "}
                <span className="text-muted">{e.kind}</span>
              </li>
            ))}
          </ol>
        </details>

        {detail.not_evaluated.length > 0 && (
          <section className="mt-5" aria-label="Not evaluated in this mode">
            <h4 className="text-sm font-medium">Not evaluated in this mode</h4>
            <ul className="mt-1 list-disc pl-5 text-xs text-muted">
              {detail.not_evaluated.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </section>
        )}

        <details className="mt-5" data-testid="raw-json">
          <summary className="cursor-pointer font-mono text-[11px] tracking-[0.04em] text-muted">
            Raw JSON
          </summary>
          <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {JSON.stringify(detail, null, 2)}
          </pre>
        </details>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------------------ history ----
export function RunHistory({
  runs,
  activeId,
  onOpen,
}: {
  runs: EvalRunSummary[];
  activeId: string | null;
  onOpen: (id: string) => void;
}) {
  return (
    <Card>
      <ul data-testid="run-history" className="divide-y divide-line">
        {runs.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onOpen(r.id)}
              aria-pressed={activeId === r.id}
              className={`flex min-h-12 w-full flex-wrap items-center gap-3 px-5 py-3 text-left text-sm hover:bg-surface-low ${
                activeId === r.id ? "bg-surface-low" : ""
              }`}
            >
              <RunPill status={r.status} />
              <span className="flex-1">
                {r.mode_label} · version {r.config_version} ·{" "}
                {r.selection.kind === "all"
                  ? "all scenarios"
                  : `${r.selection.kind} ${r.selection.value}`}
              </span>
              <span className="font-mono text-[11px] text-muted">
                {countsText(r.counts)}
              </span>
              <time
                dateTime={r.created_at}
                className="font-mono text-[11px] text-muted"
              >
                {new Date(r.created_at).toLocaleString()}
              </time>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
