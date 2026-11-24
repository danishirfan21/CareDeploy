import { Icon } from "@/components/icons";
import { Card, StatusIndicator } from "@/components/primitives";
import type {
  EvaluationGroupData,
  EvaluationResultData,
  EvaluationSummaryData,
} from "./types";

export function EvaluationSummary({
  summary,
}: {
  summary: EvaluationSummaryData;
}) {
  const failed = summary.total - summary.passed;
  const pct = summary.total
    ? Math.round((summary.passed / summary.total) * 100)
    : 0;
  return (
    <Card className="p-6">
      <div data-testid="evaluation-summary">
        <p className="flex flex-wrap items-center gap-3 text-2xl font-medium tracking-tight">
          {summary.passed} of {summary.total} scenarios passed
          <StatusIndicator tone="neutral" dot={false}>
            {pct}%
          </StatusIndicator>
        </p>
        <p className="mt-2 text-sm text-muted">
          {failed === 0
            ? "All scenarios passed."
            : `${failed} scenario${failed > 1 ? "s" : ""} ${failed > 1 ? "need" : "needs"} attention.`}
          {summary.runTimeSeconds !== undefined &&
            ` Run time ${summary.runTimeSeconds}s.`}
        </p>
      </div>
    </Card>
  );
}

export function EvaluationResult({ result }: { result: EvaluationResultData }) {
  const failed = result.status === "fail";
  return (
    <li className="py-2">
      <div className="flex items-center gap-3 text-sm">
        <span
          aria-hidden
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${failed ? "bg-danger" : "bg-accent"}`}
        />
        <span className="min-w-0 flex-1">{result.name}</span>
        {result.critical && failed && (
          <StatusIndicator tone="danger" dot={false}>
            CRITICAL
          </StatusIndicator>
        )}
        <span className="font-mono text-[11px] tracking-[0.04em] text-muted">
          {failed ? "FAIL" : "PASS"}
          {result.durationMs !== undefined &&
            ` · ${(result.durationMs / 1000).toFixed(1)}s`}
        </span>
      </div>
      {failed && (result.expected || result.observed) && (
        <div className="mt-3 rounded-xl bg-surface-low p-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg bg-surface p-3">
              <p className="font-mono text-[11px] uppercase tracking-[0.04em] text-muted">
                Expected
              </p>
              <p className="mt-1 text-sm">{result.expected}</p>
            </div>
            <div className="rounded-lg bg-surface p-3">
              <p className="font-mono text-[11px] uppercase tracking-[0.04em] text-danger">
                Observed
              </p>
              <p className="mt-1 text-sm">{result.observed}</p>
            </div>
          </div>
          {result.technical && (
            <details className="mt-3">
              <summary className="cursor-pointer font-mono text-[11px] tracking-[0.04em] text-muted">
                Technical details
              </summary>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-xs">
                {result.technical}
              </pre>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

/** Collapsible scenario group; groups with failures start expanded. */
export function EvaluationGroup({ group }: { group: EvaluationGroupData }) {
  const passed = group.results.filter((r) => r.status === "pass").length;
  const failed = group.results.length - passed;
  return (
    <Card>
      <details open={failed > 0} className="group">
        <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 px-5 py-3">
          <span className={failed ? "text-danger" : "text-accent"}>
            <Icon name={failed ? "alertCircle" : "checkCircle"} />
          </span>
          <span className="flex-1 text-lg font-medium">{group.name}</span>
          <span
            className={`font-mono text-[11px] tracking-[0.04em] ${failed ? "text-danger" : "text-muted"}`}
          >
            {passed} of {group.results.length} passed
            {failed > 0 && ` (${failed} failed)`}
          </span>
          <Icon
            name="chevronDown"
            className="h-5 w-5 text-muted transition-transform group-open:rotate-180"
          />
        </summary>
        <ul className="divide-y divide-line px-5 pb-3">
          {group.results.map((r) => (
            <EvaluationResult key={r.id} result={r} />
          ))}
        </ul>
      </details>
    </Card>
  );
}
