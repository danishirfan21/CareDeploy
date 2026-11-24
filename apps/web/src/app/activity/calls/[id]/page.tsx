"use client";

import Link from "next/link";
import { use } from "react";
import { OutcomePill, formatDuration } from "@/components/activity/calls-panel";
import { Card, EmptyState, StatusIndicator } from "@/components/primitives";
import { Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { AgentAction, CallDetail } from "@/lib/api/types";
import { useFetch } from "@/lib/use-fetch";

const UNAVAILABLE = "Unavailable";
const when = (v: string | null) =>
  v ? new Date(v).toLocaleString() : UNAVAILABLE;

function Row({
  label,
  children,
  testId,
}: {
  label: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-4">
      <dt className="w-44 shrink-0 text-sm text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-sm" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

function Summary({ c }: { c: CallDetail }) {
  const base = `/clinics/${c.clinic_id}`;
  return (
    <Card className="p-5">
      <h2 className="mb-1 text-base font-medium">Summary</h2>
      <dl className="divide-y divide-line">
        <Row label="Outcome" testId="call-outcome">
          <OutcomePill cls={c.outcome_class} label={c.outcome_label} />
          {c.outcome_reason && (
            <span className="ml-2 text-muted">{c.outcome_reason}</span>
          )}
        </Row>
        <Row label="Task">{c.task_label ?? UNAVAILABLE}</Row>
        <Row label="Clinic and agent" testId="call-meta">
          {c.clinic_name} · {c.agent_name ?? UNAVAILABLE}
        </Row>
        <Row label="Started">{when(c.started_at ?? c.created_at)}</Row>
        <Row label="Duration">{formatDuration(c.duration_seconds)}</Row>
        <Row label="Agent-reported result">
          {c.agent_reported_outcome ?? UNAVAILABLE}
        </Row>
        {c.escalation_reason && (
          <Row label="Escalation reason">{c.escalation_reason}</Row>
        )}
        {c.error && <Row label="Error">{c.error}</Row>}
        <Row label="Call summary">{c.summary ?? UNAVAILABLE}</Row>
        <Row label="Configuration" testId="call-config">
          <Link href={base} className="text-primary underline">
            Version {c.config_version}
          </Link>
        </Row>
        <Row label="Deployment" testId="call-deployment">
          {c.deployment ? (
            <Link href={`${base}/configure`} className="text-primary underline">
              {c.deployment.action} of version {c.deployment.config_version} (
              {c.deployment.status})
            </Link>
          ) : (
            UNAVAILABLE
          )}
        </Row>
        <Row label="Evaluation" testId="call-evaluation">
          {c.evaluation ? (
            <Link
              href={`/evaluations?clinic=${c.clinic_id}&run=${c.evaluation.run_id}`}
              className="text-primary underline"
            >
              Workflow run ({c.evaluation.status})
            </Link>
          ) : (
            "No workflow evaluation recorded for this version"
          )}
        </Row>
        <Row label="Scheduling changes" testId="call-operations">
          {c.operations.length
            ? c.operations.map((o) => (
                <span key={o.id} className="mr-3 inline-block">
                  <span className="font-mono text-xs">{o.id}</span> (
                  {o.operation_type}, {o.status})
                </span>
              ))
            : "None recorded"}
        </Row>
      </dl>
    </Card>
  );
}

function Conversation({ c }: { c: CallDetail }) {
  return (
    <section aria-label="Conversation">
      <h2 className="mb-3 text-base font-medium">Conversation</h2>
      {c.transcript.length === 0 ? (
        <p className="text-sm text-muted" data-testid="no-transcript">
          No transcript was recorded for this call.
        </p>
      ) : (
        <ol className="space-y-2" data-testid="transcript">
          {c.transcript.map((t) => (
            <li
              key={t.event_id}
              className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
                t.speaker === "agent"
                  ? "bg-surface-low"
                  : "ml-auto bg-accent-soft text-primary"
              }`}
            >
              <span className="mb-0.5 block text-xs text-muted">
                {t.speaker === "agent" ? "Agent" : "Caller"}
                {t.interrupted ? " · interrupted" : ""}
              </span>
              {t.text}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ActionRow({ a, clinicId }: { a: AgentAction; clinicId: string }) {
  return (
    <li className="space-y-1 rounded-2xl border border-line bg-surface px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{a.label}</span>
        <StatusIndicator
          tone={
            a.succeeded
              ? "success"
              : a.status === "running"
                ? "neutral"
                : "danger"
          }
        >
          {a.status}
        </StatusIndicator>
        {a.latency_ms !== null && (
          <span className="font-mono text-xs text-muted">
            {a.latency_ms} ms
          </span>
        )}
      </div>
      {a.message && <p className="text-muted">{a.message}</p>}
      {a.error_category_label && (
        <p data-testid="error-category">
          Error category: <strong>{a.error_category_label}</strong>
          {a.code && <span className="ml-2 font-mono text-xs">{a.code}</span>}
        </p>
      )}
      {a.operation_id && (
        <p className="text-xs" data-testid="action-operation">
          Operation <span className="font-mono">{a.operation_id}</span>
          {a.operation
            ? ` · ${a.operation.operation_type}, ${a.operation.status}`
            : ""}
          {" · "}
          <Link
            href={`/clinics/${clinicId}`}
            className="text-primary underline"
          >
            Clinic configuration
          </Link>
        </p>
      )}
    </li>
  );
}

function Actions({ c }: { c: CallDetail }) {
  return (
    <section aria-label="Agent actions">
      <h2 className="mb-3 text-base font-medium">Agent actions</h2>
      {c.actions.length === 0 ? (
        <p className="text-sm text-muted">
          The agent did not call any tools during this call.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="agent-actions">
          {c.actions.map((a) => (
            <ActionRow key={a.call_id} a={a} clinicId={c.clinic_id} />
          ))}
        </ul>
      )}
    </section>
  );
}

function Technical({ c }: { c: CallDetail }) {
  return (
    <details
      className="rounded-2xl border border-line bg-surface px-4 py-3"
      data-testid="technical-details"
    >
      <summary className="cursor-pointer text-sm font-medium">
        Technical details
      </summary>
      <div className="mt-3 space-y-2 text-sm">
        <p className="font-mono text-xs">Call {c.id}</p>
        <pre className="max-h-96 overflow-auto rounded-xl bg-surface-low p-3 text-xs">
          {JSON.stringify(c.technical, null, 2)}
        </pre>
        <p className="text-xs text-muted">
          Secrets and caller identifiers are redacted. Audio is not recorded.
        </p>
      </div>
    </details>
  );
}

export default function CallDetails({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ clinic?: string }>;
}) {
  const { id } = use(params);
  const { clinic } = use(searchParams);
  const { data, error, loading } = useFetch(
    `call-${id}-${clinic}`,
    async () => {
      // Older links carry no clinic: the voice session record knows it.
      const clinicId = clinic ?? (await api.getVoiceSession(id)).clinic_id;
      return api.getCall(clinicId, id);
    },
  );
  return (
    <>
      <PageHeader
        title="Call details"
        subtitle="What was said, what the agent did, and what the records show."
        action={
          <Link href="/activity" className="text-sm text-primary underline">
            Back to Activity
          </Link>
        }
      />
      {loading && <p className="text-sm text-muted">Loading call…</p>}
      {error && (
        <EmptyState testId="call-not-found" title="Call not found">
          {error}
        </EmptyState>
      )}
      {data && (
        <div className="space-y-6">
          {data.outcome_class === null && (
            <Notice tone="info">
              This call has not ended. The outcome is not final.
            </Notice>
          )}
          <Summary c={data} />
          <Conversation c={data} />
          <Actions c={data} />
          <Technical c={data} />
          <p className="text-xs text-muted">
            Outcomes come from the call record and the scheduling ledger, not
            from the agent&apos;s wording. Patient details are simulated sample
            records.
          </p>
        </div>
      )}
    </>
  );
}
