"use client";

import Link from "next/link";
import { useState } from "react";
import { ClinicSelector } from "@/components/clinic-selector";
import { Icon } from "@/components/icons";
import {
  Card,
  EmptyState,
  StatusIndicator,
  type Tone,
} from "@/components/primitives";
import { Notice, inputCls, secondaryBtn } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { CallMetrics, MetricRate, OutcomeClass } from "@/lib/api/types";
import { useFetch } from "@/lib/use-fetch";

const PAGE = 15;

export const OUTCOME_TONE: Record<OutcomeClass, Tone> = {
  completed: "success",
  escalated: "info",
  failed: "danger",
  abandoned: "neutral",
  interrupted: "warning",
  unknown: "warning",
};

export function OutcomePill({
  cls,
  label,
}: {
  cls: OutcomeClass | null;
  label: string;
}) {
  return (
    <StatusIndicator tone={cls ? OUTCOME_TONE[cls] : "neutral"}>
      {label}
    </StatusIndicator>
  );
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "Unavailable";
  const s = Math.round(seconds);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function pct(r: MetricRate): string {
  return r.value === null ? "Unavailable" : `${Math.round(r.value * 100)}%`;
}

function Metric({
  label,
  value,
  note,
  testId,
}: {
  label: string;
  value: string;
  note: string;
  testId: string;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="text-2xl font-medium" data-testid={testId}>
        {value}
      </p>
      <p className="text-xs text-muted">{note}</p>
    </div>
  );
}

function rateNote(r: MetricRate): string {
  const base = `${r.numerator} of ${r.denominator} finished calls`;
  return r.low_sample ? `${base} · small sample` : base;
}

function MetricsSummary({ m }: { m: CallMetrics }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="Call metrics" className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric
          testId="metric-completion"
          label="Completed"
          value={pct(m.completion)}
          note={rateNote(m.completion)}
        />
        <Metric
          testId="metric-escalation"
          label="Escalated"
          value={pct(m.escalation)}
          note={rateNote(m.escalation)}
        />
        <Metric
          testId="metric-duration"
          label="Average duration"
          value={formatDuration(m.average_duration_seconds)}
          note={`${m.calls_with_duration} calls with a recorded duration`}
        />
      </div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="text-sm text-primary underline"
        data-testid="metrics-toggle"
      >
        {open ? "Hide details" : "Show details"}
      </button>
      {open && (
        <Card className="space-y-4 p-4 text-sm">
          <div data-testid="metrics-details" className="space-y-4">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
              {Object.entries(m.by_outcome).map(([k, n]) => (
                <div key={k} className="flex justify-between">
                  <dt className="capitalize text-muted">{k}</dt>
                  <dd className="font-mono">{n}</dd>
                </div>
              ))}
              <div className="flex justify-between">
                <dt className="text-muted">In progress</dt>
                <dd className="font-mono">{m.in_progress}</dd>
              </div>
            </dl>
            <p>
              Tool calls: {m.tools.finished} finished, {m.tools.succeeded}{" "}
              succeeded, {m.tools.failed} failed, {m.tools.uncertain} uncertain.
            </p>
            <p data-testid="cost-line">
              {m.cost.available ? (
                <>
                  Estimated cost: {m.cost.total} {m.cost.currency} across{" "}
                  {m.cost.calls_with_cost} calls (estimate, not billing).
                </>
              ) : (
                (m.cost.reason ?? "Cost unavailable.")
              )}
            </p>
            <p className="text-xs text-muted">
              Rates use finished calls only. Range {m.from_date} to {m.to_date}{" "}
              ({m.timezone}).
            </p>
            {m.notes.map((n) => (
              <p key={n} className="text-xs text-muted">
                {n}
              </p>
            ))}
          </div>
        </Card>
      )}
    </section>
  );
}

const OUTCOMES = [
  ["", "All outcomes"],
  ["completed", "Completed"],
  ["escalated", "Escalated"],
  ["failed", "Failed"],
  ["abandoned", "Abandoned"],
  ["interrupted", "Interrupted"],
  ["unknown", "Unknown"],
  ["in_progress", "In progress"],
] as const;

export function CallsPanel({
  clinicId,
  onClinic,
  onCount,
}: {
  clinicId: string;
  onClinic: (id: string) => void;
  onCount: (n: number) => void;
}) {
  const [outcome, setOutcome] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const key = `${clinicId}|${outcome}|${from}|${to}|${q}|${offset}`;
  const list = useFetch(`calls-${key}`, async () => {
    if (!clinicId) return null;
    const res = await api.listCalls(clinicId, {
      outcome,
      date_from: from,
      date_to: to,
      q,
      limit: PAGE,
      offset,
    });
    if (!outcome && !from && !to && !q) onCount(res.total);
    return res;
  });
  const metrics = useFetch(`call-metrics-${clinicId}-${from}-${to}`, () =>
    clinicId ? api.callMetrics(clinicId, from, to) : Promise.resolve(null),
  );
  const reset =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      setOffset(0);
      set(v);
    };
  const data = list.data;
  const filtered = !!(outcome || from || to || q);
  return (
    <div className="space-y-4">
      <div className="max-w-sm">
        <ClinicSelector
          label="Clinic"
          value={clinicId}
          onChange={(id) => {
            setOffset(0);
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
          Select a clinic to see its calls.
        </EmptyState>
      )}
      {clinicId && (
        <>
          {metrics.data && metrics.data.total_calls > 0 && (
            <MetricsSummary m={metrics.data} />
          )}
          <div
            className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
            role="search"
          >
            <label className="text-sm">
              <span className="mb-1 block font-medium">Outcome</span>
              <select
                aria-label="Outcome"
                className={inputCls}
                value={outcome}
                onChange={(e) => reset(setOutcome)(e.target.value)}
              >
                {OUTCOMES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">From</span>
              <input
                type="date"
                aria-label="From date"
                className={inputCls}
                value={from}
                onChange={(e) => reset(setFrom)(e.target.value)}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">To</span>
              <input
                type="date"
                aria-label="To date"
                className={inputCls}
                value={to}
                onChange={(e) => reset(setTo)(e.target.value)}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Search</span>
              <input
                type="search"
                aria-label="Search calls"
                placeholder="Call ID, operation ID, summary"
                className={inputCls}
                value={q}
                onChange={(e) => reset(setQ)(e.target.value)}
              />
            </label>
          </div>
          {list.loading && (
            <p className="text-sm text-muted" data-testid="calls-loading">
              Loading calls…
            </p>
          )}
          {list.error && (
            <Notice tone="error">Could not load calls: {list.error}</Notice>
          )}
          {data && data.total === 0 && (
            <EmptyState
              testId="calls-empty"
              icon={<Icon name="activity" />}
              title={filtered ? "No calls match these filters" : "No calls yet"}
            >
              {filtered
                ? "Try a wider date range or a different outcome."
                : "Calls made from the Playground appear here."}
            </EmptyState>
          )}
          {data && data.total > 0 && (
            <>
              <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
                <table
                  className="w-full text-left text-sm"
                  data-testid="calls-table"
                >
                  <thead className="text-xs text-muted">
                    <tr>
                      <th className="px-4 py-2 font-medium">Started</th>
                      <th className="px-4 py-2 font-medium">Clinic</th>
                      <th className="px-4 py-2 font-medium">Task</th>
                      <th className="px-4 py-2 font-medium">Outcome</th>
                      <th className="px-4 py-2 font-medium">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((c) => (
                      <tr key={c.id} className="border-t border-line">
                        <td className="px-4 py-3">
                          <Link
                            href={`/activity/calls/${c.id}?clinic=${c.clinic_id}`}
                            className="font-mono text-xs text-primary underline"
                            data-testid="call-link"
                          >
                            {new Date(c.started_at).toLocaleString()}
                          </Link>
                        </td>
                        <td className="px-4 py-3">{c.clinic_name}</td>
                        <td className="px-4 py-3">
                          {c.task_label ?? (
                            <span className="text-muted">Unavailable</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <OutcomePill
                            cls={c.outcome_class}
                            label={c.outcome_label}
                          />
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">
                          {formatDuration(c.duration_seconds)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted" data-testid="calls-range">
                  {data.offset + 1}–{Math.min(data.offset + PAGE, data.total)}{" "}
                  of {data.total}
                </span>
                <span className="flex gap-2">
                  <button
                    type="button"
                    className={secondaryBtn}
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - PAGE))}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className={secondaryBtn}
                    disabled={offset + PAGE >= data.total}
                    onClick={() => setOffset(offset + PAGE)}
                  >
                    Next
                  </button>
                </span>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
