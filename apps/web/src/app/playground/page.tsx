"use client";

import { useState } from "react";
import { ClinicSelector } from "@/components/clinic-selector";
import { Icon } from "@/components/icons";
import { PageHeader } from "@/components/ui";
import { EmptyState, StatusIndicator } from "@/components/primitives";
import { CallControls } from "@/components/voice/call-controls";

export default function Playground() {
  const [clinicId, setClinicId] = useState("");
  return (
    <>
      <PageHeader
        title="Playground"
        subtitle="Test a clinic's voice agent against its published configuration."
        action={
          <StatusIndicator tone="neutral">Voice testing off</StatusIndicator>
        }
      />
      <div className="mb-6 max-w-sm">
        <ClinicSelector value={clinicId} onChange={setClinicId} />
      </div>

      <section aria-label="Conversation" className="space-y-6">
        <EmptyState
          testId="unavailable"
          icon={<Icon name="phoneOff" />}
          title="Live voice testing is not yet enabled"
        >
          Not available yet. Calls, transcripts and tool activity will appear
          here once voice testing is built (milestone M3). Nothing on this page
          is a real call.
        </EmptyState>
        <CallControls phase="unavailable" />
        <details className="rounded-xl bg-surface-low px-4 py-3">
          <summary className="cursor-pointer font-mono text-[11px] tracking-[0.04em] text-muted">
            Technical details
          </summary>
          <p className="mt-2 text-sm text-muted">
            No call session exists, so there is no latency, tool or audio
            diagnostic data to show.
          </p>
        </details>
      </section>
    </>
  );
}
