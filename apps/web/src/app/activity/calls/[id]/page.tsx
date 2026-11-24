"use client";

import Link from "next/link";
import { use, useMemo } from "react";
import { PageHeader } from "@/components/ui";
import { EmptyState } from "@/components/primitives";
import { CallResult } from "@/components/voice/call-result";
import {
  ConversationTranscript,
  ToolChain,
} from "@/components/voice/conversation";
import { api } from "@/lib/api/client";
import { useFetch } from "@/lib/use-fetch";
import { foldEvents } from "@/lib/voice/fold";

export default function CallDetails({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data, error, loading } = useFetch(`call-${id}`, async () => {
    const [session, events] = await Promise.all([
      api.getVoiceSession(id),
      api.getVoiceEvents(id),
    ]);
    return { session, events: events.events };
  });
  const folded = useMemo(() => foldEvents(data?.events ?? []), [data?.events]);

  return (
    <>
      <PageHeader
        title="Call details"
        subtitle="A finished call: what was said, what the agent did, and the result."
        action={
          <Link href="/playground" className="text-sm text-primary underline">
            Back to Playground
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
          <p className="text-sm text-muted" data-testid="call-meta">
            {data.session.clinic_name} · {data.session.agent_name} · config v
            {data.session.config_version} ·{" "}
            {new Date(data.session.created_at).toLocaleString()}
          </p>
          <CallResult session={data.session} />
          {data.session.operation_ids.length > 0 && (
            <p className="text-sm" data-testid="call-operations">
              Scheduling changes made on this call:{" "}
              <span className="font-mono text-xs">
                {data.session.operation_ids.join(", ")}
              </span>
            </p>
          )}
          <section aria-label="Transcript">
            <h2 className="mb-3 text-base font-medium">Transcript</h2>
            {folded.turns.length ? (
              <ConversationTranscript turns={folded.turns} />
            ) : (
              <p className="text-sm text-muted">No speech was recorded.</p>
            )}
          </section>
          {folded.tools.length > 0 && (
            <section aria-label="Tool activity">
              <h2 className="mb-3 text-base font-medium">Tool activity</h2>
              <ToolChain tools={folded.tools} />
            </section>
          )}
          <p className="text-xs text-muted">
            Audio is not recorded. Patient details are simulated sample records.
          </p>
        </div>
      )}
    </>
  );
}
