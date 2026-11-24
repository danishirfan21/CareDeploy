"use client";

import { useMemo, useState } from "react";
import { ClinicSelector } from "@/components/clinic-selector";
import { Icon } from "@/components/icons";
import { PageHeader } from "@/components/ui";
import { EmptyState, StatusIndicator } from "@/components/primitives";
import { CallControls } from "@/components/voice/call-controls";
import { CallResult } from "@/components/voice/call-result";
import {
  ConversationTranscript,
  ToolChain,
} from "@/components/voice/conversation";
import { api } from "@/lib/api/client";
import { useFetch } from "@/lib/use-fetch";
import { foldEvents } from "@/lib/voice/fold";
import { useCall, type TransportState } from "@/lib/voice/use-call";

const TRANSPORT_LABEL: Record<TransportState, string> = {
  connecting: "Connecting",
  connected: "Connected",
  reconnecting: "Reconnecting",
  disconnected: "Disconnected",
};

const PHASE_HEADLINE: Record<string, string> = {
  waiting_for_verification: "Verifying the caller",
  awaiting_confirmation: "Waiting for the caller to confirm",
  executing_tool: "Working on it",
  recovering: "Recovering from a problem",
  escalated: "Hand-off to staff requested",
  thinking: "Thinking",
  speaking: "Agent speaking",
  listening: "Listening",
  ready: "Ready",
};

export default function Playground() {
  const [clinicId, setClinicId] = useState("");
  const call = useCall();
  const clinics = useFetch("clinics", () => api.listClinics());
  const clinic = clinics.data?.find((c) => c.id === clinicId);
  const { turns, tools } = useMemo(
    () => foldEvents(call.events),
    [call.events],
  );
  const live = call.snapshot?.live_state;
  const inCall = !["idle", "ended"].includes(call.phase);
  const published = !!clinic?.latest_version;
  const stage = live?.conversation ? PHASE_HEADLINE[live.conversation] : null;

  return (
    <>
      <PageHeader
        title="Playground"
        subtitle="Talk to a clinic's voice agent using its published configuration."
        action={
          inCall || call.phase === "ended" ? (
            <StatusIndicator
              tone={
                call.transportState === "connected"
                  ? "success"
                  : call.transportState === "reconnecting"
                    ? "warning"
                    : "neutral"
              }
            >
              <span data-testid="transport-status">
                {call.phase === "ended"
                  ? "Call ended"
                  : TRANSPORT_LABEL[call.transportState]}
              </span>
            </StatusIndicator>
          ) : (
            <StatusIndicator tone="neutral">Not in a call</StatusIndicator>
          )
        }
      />

      <div className="mb-6 grid max-w-xl gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
        {inCall ? (
          <div>
            <p className="mb-1 text-sm font-medium">Clinic</p>
            <p className="text-sm" data-testid="call-clinic">
              {call.created?.clinic_name ?? clinic?.name}
            </p>
          </div>
        ) : (
          <ClinicSelector
            value={clinicId}
            onChange={(id) => {
              setClinicId(id);
              if (call.phase === "ended") call.reset();
            }}
          />
        )}
        <p
          className="font-mono text-[11px] tracking-[0.04em] text-muted"
          data-testid="agent-version"
        >
          {call.created
            ? `${call.created.agent_name || "Agent"} · config v${call.created.config_version}`
            : clinic?.latest_version
              ? `Will use published v${clinic.latest_version}`
              : clinicId
                ? "No published version"
                : ""}
        </p>
      </div>

      {call.problem && (
        <div
          role="alert"
          data-testid="call-problem"
          className="mb-6 rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          <p className="font-medium">{call.problem.title}</p>
          <p className="mt-1">{call.problem.detail}</p>
          {call.problem.missing && (
            <ul className="mt-2 list-disc pl-5 font-mono text-xs">
              {call.problem.missing.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <section aria-label="Conversation" className="space-y-6">
        {call.phase === "idle" && !call.problem && (
          <EmptyState
            testId="idle-state"
            icon={<Icon name="phone" />}
            title={
              clinicId ? "Ready to start a call" : "Choose a clinic to begin"
            }
          >
            {clinicId && !published
              ? "This clinic has no published configuration yet, so it cannot take a call."
              : "The call uses a microphone and a live voice agent. Transcripts and tool activity appear here as the call goes."}
          </EmptyState>
        )}

        {(call.phase === "starting" || call.phase === "connecting") && (
          <p
            role="status"
            data-testid="connecting"
            className="text-sm text-muted"
          >
            {call.phase === "starting"
              ? "Starting the call…"
              : "Connecting. Waiting for the voice agent to join…"}
          </p>
        )}

        {inCall && stage && call.phase === "active" && (
          <p
            role="status"
            aria-live="polite"
            data-testid="call-stage"
            className="font-mono text-[11px] uppercase tracking-[0.04em] text-primary"
          >
            {stage}
            {live?.verified_patient
              ? ` · verified: ${live.verified_patient}`
              : ""}
          </p>
        )}

        {live?.pending_confirmation && call.phase === "active" && (
          <div
            data-testid="confirmation-pending"
            className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900"
          >
            The agent is waiting for the caller to say yes before changing
            anything.
          </div>
        )}

        {(turns.length > 0 || live?.interim_user) && (
          <ConversationTranscript turns={turns} />
        )}
        {live?.interim_user && call.phase === "active" && (
          <p
            data-testid="interim"
            aria-label="Caller is speaking"
            className="text-sm italic text-muted"
          >
            {live.interim_user}…
          </p>
        )}
        {tools.length > 0 && <ToolChain tools={tools} />}

        <CallControls
          phase={
            call.phase === "idle" && !published ? "unavailable" : call.phase
          }
          muted={call.muted}
          onStart={() => void call.start(clinicId)}
          onEnd={() => void call.end()}
          onToggleMute={() => void call.toggleMute()}
        />
        {call.phase === "idle" && clinicId === "" && (
          <p className="text-center text-xs text-muted">
            Select a clinic to enable Start call.
          </p>
        )}

        {call.phase === "ending" && (
          <p role="status" className="text-center text-sm text-muted">
            Ending the call…
          </p>
        )}

        {call.phase === "ended" && call.snapshot && (
          <CallResult
            session={call.snapshot}
            detailsHref={`/activity/calls/${call.snapshot.call_session_id}?clinic=${call.snapshot.clinic_id}`}
          />
        )}
      </section>
    </>
  );
}
