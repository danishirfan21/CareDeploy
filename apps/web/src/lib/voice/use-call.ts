"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api/client";
import type {
  CallEvent,
  VoiceSession,
  VoiceSessionCreated,
} from "@/lib/api/types";
import type { CallPhase } from "@/components/voice/types";
import {
  MicrophoneDeniedError,
  createTransport,
  type VoiceTransport,
} from "./transport";

export type TransportState =
  "connecting" | "connected" | "reconnecting" | "disconnected";

export interface CallProblem {
  kind:
    | "not_configured"
    | "clinic_not_ready"
    | "microphone"
    | "connection"
    | "agent_timeout"
    | "connection_lost"
    | "unknown";
  title: string;
  detail: string;
  missing?: string[];
}

const POLL_MS = 700;
const AGENT_JOIN_TIMEOUT_MS = 30_000;
const SETTLE_MS = 6_000;

function describeApiProblem(e: unknown): CallProblem {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: { code?: string; missing?: string[] } })
      ?.detail;
    if (e.status === 503 && d?.code === "voice_not_configured") {
      return {
        kind: "not_configured",
        title: "Voice testing is not configured",
        detail:
          "The backend needs LiveKit credentials before it can start calls. Nothing was started.",
        missing: d.missing,
      };
    }
    if (e.status === 409 && d?.code === "clinic_not_configured") {
      return {
        kind: "clinic_not_ready",
        title: "This clinic has no published configuration",
        detail: "Publish a configuration for this clinic, then try again.",
      };
    }
    return {
      kind: "unknown",
      title: "Could not start the call",
      detail: e.message,
    };
  }
  return {
    kind: "unknown",
    title: "Could not start the call",
    detail: e instanceof Error ? e.message : "Unexpected error",
  };
}

const TERMINAL = new Set(["completed", "failed", "abandoned"]);

/** Drives one call: creates the session, joins the room, and follows the backend's event log. */
export function useCall() {
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [created, setCreated] = useState<VoiceSessionCreated | null>(null);
  const [snapshot, setSnapshot] = useState<VoiceSession | null>(null);
  const [events, setEvents] = useState<CallEvent[]>([]);
  const [problem, setProblem] = useState<CallProblem | null>(null);
  const [muted, setMuted] = useState(false);
  const [transportState, setTransportState] =
    useState<TransportState>("connecting");

  const transport = useRef<VoiceTransport | null>(null);
  const unsub = useRef<(() => void) | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionId = useRef<string | null>(null);
  const lastSeq = useRef<number | undefined>(undefined);
  const phaseRef = useRef<CallPhase>("idle");
  const connectedAt = useRef(0);
  const endedAt = useRef(0);
  const polling = useRef(false);
  const problemRef = useRef<CallProblem | null>(null);
  useEffect(() => {
    problemRef.current = problem;
  }, [problem]);

  const go = useCallback((p: CallPhase) => {
    phaseRef.current = p;
    setPhase(p);
  }, []);

  const stopPolling = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  };

  const teardownTransport = useCallback(async () => {
    unsub.current?.();
    unsub.current = null;
    const t = transport.current;
    transport.current = null;
    if (t) await t.disconnect().catch(() => undefined);
  }, []);

  const finishIfSettled = useCallback(
    (s: VoiceSession) => {
      if (!TERMINAL.has(s.status)) return;
      const p = phaseRef.current;
      if (p === "active" || p === "connecting") {
        // The worker ended the call itself (error, hang-up): release our side too.
        endedAt.current = Date.now();
        go("ending");
        void teardownTransport();
        return;
      }
      if (
        p === "ending" &&
        (s.outcome !== null || Date.now() - endedAt.current > SETTLE_MS)
      ) {
        stopPolling();
        go("ended");
      }
    },
    [go, teardownTransport],
  );

  const poll = useCallback(async () => {
    const id = sessionId.current;
    if (!id || polling.current) return;
    polling.current = true;
    try {
      const [s, ev] = await Promise.all([
        api.getVoiceSession(id),
        api.getVoiceEvents(id, lastSeq.current),
      ]);
      setSnapshot(s);
      if (ev.events.length) {
        lastSeq.current = ev.events[ev.events.length - 1].seq;
        setEvents((prev) => [...prev, ...ev.events]);
      }
      if (phaseRef.current === "connecting" && s.status === "active") {
        go("active");
      }
      if (
        phaseRef.current === "connecting" &&
        Date.now() - connectedAt.current > AGENT_JOIN_TIMEOUT_MS
      ) {
        setProblem({
          kind: "agent_timeout",
          title: "The voice agent did not join",
          detail:
            "The call connected, but no voice agent worker picked it up in time. Check that the worker is running.",
        });
        await endInternal("connection_failed");
        return;
      }
      if (phaseRef.current === "ending" && endedAt.current === 0) {
        endedAt.current = Date.now();
      }
      if (TERMINAL.has(s.status)) {
        if (s.status === "failed" && s.error && !problemRef.current) {
          setProblem({
            kind: "unknown",
            title: "The call ended with an error",
            detail: s.error,
          });
        }
        finishIfSettled(s);
      }
    } catch {
      // A missed poll is harmless; the next tick retries.
    } finally {
      polling.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finishIfSettled, go]);

  const startPolling = useCallback(() => {
    stopPolling();
    timer.current = setInterval(() => void poll(), POLL_MS);
    void poll();
  }, [poll]);

  async function endInternal(
    reason:
      "user_ended" | "connection_failed" | "page_closed" | "microphone_denied",
  ) {
    const id = sessionId.current;
    if (!id) return;
    if (phaseRef.current === "ending" || phaseRef.current === "ended") return;
    go("ending");
    endedAt.current = Date.now();
    await teardownTransport();
    setTransportState("disconnected");
    try {
      const s = await api.endVoiceSession(id, reason);
      setSnapshot(s);
      if (s.started_at === null) {
        // The worker never joined: there is nothing more to wait for.
        stopPolling();
        go("idle");
        return;
      }
    } catch {
      // The poll below reports the real state.
    }
    startPolling();
  }

  const start = useCallback(
    async (clinicId: string) => {
      setProblem(null);
      setEvents([]);
      setSnapshot(null);
      setCreated(null);
      setMuted(false);
      lastSeq.current = undefined;
      endedAt.current = 0;
      setTransportState("connecting");
      go("starting");
      let c: VoiceSessionCreated;
      try {
        c = await api.startVoiceSession(clinicId);
      } catch (e) {
        setProblem(describeApiProblem(e));
        go("idle");
        return;
      }
      sessionId.current = c.call_session_id;
      setCreated(c);
      go("connecting");
      connectedAt.current = Date.now();
      const t = await createTransport();
      transport.current = t;
      unsub.current = t.subscribe((ev) => {
        if (ev.type === "connected") setTransportState("connected");
        else if (ev.type === "reconnecting") setTransportState("reconnecting");
        else if (ev.type === "disconnected" || ev.type === "agent_left") {
          setTransportState("disconnected");
          const p = phaseRef.current;
          if (p === "active" || p === "connecting") {
            setProblem({
              kind: "connection_lost",
              title:
                ev.type === "agent_left"
                  ? "The voice agent left the call"
                  : "Connection lost",
              detail:
                "The call was ended. Anything already confirmed is kept in the call details.",
            });
            void endInternal("connection_failed");
          }
        }
      });
      try {
        await t.connect(c.livekit_url, c.token);
      } catch (e) {
        if (e instanceof MicrophoneDeniedError) {
          setProblem({
            kind: "microphone",
            title: "Microphone access is blocked",
            detail:
              "Allow microphone access for this site in your browser, then start the call again.",
          });
          await endInternal("microphone_denied");
        } else {
          setProblem({
            kind: "connection",
            title: "Could not connect to the voice service",
            detail: e instanceof Error ? e.message : "Connection failed.",
          });
          await endInternal("connection_failed");
        }
        return;
      }
      startPolling();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [go, startPolling],
  );

  const end = useCallback(() => endInternal("user_ended"), []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleMute = useCallback(async () => {
    const t = transport.current;
    if (!t) return;
    const next = !muted;
    await t.setMicEnabled(!next).catch(() => undefined);
    setMuted(next);
  }, [muted]);

  const reset = useCallback(() => {
    stopPolling();
    setProblem(null);
    setEvents([]);
    setSnapshot(null);
    setCreated(null);
    sessionId.current = null;
    go("idle");
  }, [go]);

  useEffect(
    () => () => {
      stopPolling();
      if (phaseRef.current === "active" || phaseRef.current === "connecting") {
        void endInternal("page_closed");
      }
      void teardownTransport();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  return {
    phase,
    created,
    snapshot,
    events,
    problem,
    muted,
    transportState,
    start,
    end,
    toggleMute,
    reset,
  };
}
