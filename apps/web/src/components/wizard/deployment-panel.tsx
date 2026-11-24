"use client";

import { useState } from "react";
import { StatusIndicator } from "@/components/primitives";
import { Notice, primaryBtn, secondaryBtn } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { DeploymentAssessment } from "@/lib/api/types";
import { useFetch } from "@/lib/use-fetch";

const message = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong";

function Checks({ a }: { a: DeploymentAssessment }) {
  const missing = a.checks.filter((c) => !c.passed);
  const met = a.checks.filter((c) => c.passed);
  return (
    <div className="space-y-2" data-testid="deployment-readiness">
      <Notice tone={a.eligible ? "success" : "warning"}>
        <p className="font-medium" data-testid="deployment-headline">
          {a.headline}
        </p>
        {missing.length > 0 && (
          <ul className="mt-1 list-disc pl-5" data-testid="deployment-missing">
            {missing.map((c) => (
              <li key={c.id}>{c.message}</li>
            ))}
          </ul>
        )}
      </Notice>
      {met.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted">
            {met.length} requirement{met.length > 1 ? "s" : ""} met
          </summary>
          <ul className="mt-1 list-disc pl-5 text-muted">
            {met.map((c) => (
              <li key={c.id}>{c.message}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-muted" data-testid="live-verification">
        {a.live_verification_message}
      </p>
    </div>
  );
}

/** Deployment controls for the review step: which published version new voice sessions use.
 *  Eligibility is decided by the server; this panel only displays it and sends the request. */
export function DeploymentPanel({ clinicId }: { clinicId: string }) {
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [target, setTarget] = useState<number | null>(null); // rollback target being confirmed
  const [showHistory, setShowHistory] = useState(false);

  const state = useFetch(`deployment-${clinicId}-${tick}`, () =>
    api.getDeployment(clinicId),
  );
  const history = useFetch(`deployment-history-${clinicId}-${tick}`, () =>
    api.deploymentHistory(clinicId),
  );
  const latest = state.data?.latest_published_version ?? null;
  const active = state.data?.active ?? null;
  const readiness = useFetch(
    `deployment-ready-${clinicId}-${latest}-${tick}`,
    () =>
      latest
        ? api.deploymentReadiness(clinicId, latest)
        : Promise.resolve(null),
  );
  const rollbackCheck = useFetch(
    `deployment-rb-${clinicId}-${target}-${tick}`,
    () =>
      target
        ? api.deploymentReadiness(clinicId, target, "rollback")
        : Promise.resolve(null),
  );

  const previous = Array.from(
    new Set(
      (history.data ?? [])
        .map((e) => e.to_version)
        .filter((v) => v !== active?.config_version),
    ),
  ).sort((a, b) => b - a);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await fn();
      setDone(ok);
      setTarget(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
      setTick((n) => n + 1);
    }
  };

  const key = () => globalThis.crypto.randomUUID();

  return (
    <section
      aria-label="Deployment"
      data-testid="deployment-panel"
      className="space-y-4 rounded-2xl border border-line p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-medium">Deployment</h2>
        <StatusIndicator tone="info" dot={false}>
          {state.data?.environment_label ?? "Simulated Live"}
        </StatusIndicator>
      </div>

      {state.loading && (
        <p className="text-sm text-muted">Loading deployment…</p>
      )}
      {state.error && (
        <Notice tone="error">Could not load deployment: {state.error}</Notice>
      )}

      {state.data && (
        <p className="text-sm" data-testid="deployment-active">
          {active ? (
            <>
              Active: <strong>version {active.config_version}</strong>
              {active.action === "seed" && " (sample seed, not evaluated)"}
              {active.action === "rollback" && " (restored by rollback)"}
            </>
          ) : (
            "No version is active. New voice sessions are refused until one is deployed."
          )}
        </p>
      )}
      <p className="text-xs text-muted">
        Simulated Live selects the version used by new development voice
        sessions. It is not a production healthcare deployment.
      </p>

      {latest === null && state.data && (
        <Notice tone="info">
          Publish a version first, then evaluate and deploy it.
        </Notice>
      )}

      {latest !== null && active?.config_version === latest && (
        <Notice tone="success">
          The latest published version ({latest}) is the active deployment.
        </Notice>
      )}

      {latest !== null && active?.config_version !== latest && (
        <div className="space-y-3">
          <p className="text-sm font-medium">Deploy version {latest}</p>
          {readiness.loading && (
            <p className="text-sm text-muted">Checking readiness…</p>
          )}
          {readiness.error && (
            <Notice tone="error">
              Could not check readiness: {readiness.error}
            </Notice>
          )}
          {readiness.data && <Checks a={readiness.data} />}
          <button
            type="button"
            className={primaryBtn}
            data-testid="promote-button"
            disabled={busy || !readiness.data?.eligible}
            onClick={() =>
              void act(
                () =>
                  api.promote(
                    clinicId,
                    latest,
                    active?.config_version ?? null,
                    key(),
                  ),
                `Version ${latest} is now active in Simulated Live.`,
              )
            }
          >
            {busy ? "Deploying…" : `Deploy version ${latest}`}
          </button>
        </div>
      )}

      {previous.length > 0 && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-sm" htmlFor="rollback-target">
              Roll back to
            </label>
            <select
              id="rollback-target"
              className="min-h-10 rounded-xl border border-line bg-surface px-3 text-sm"
              value={target ?? ""}
              onChange={(e) =>
                setTarget(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">Select a previously deployed version</option>
              {previous.map((v) => (
                <option key={v} value={v}>
                  Version {v}
                </option>
              ))}
            </select>
          </div>
          {target !== null && (
            <div
              role="group"
              aria-label="Confirm rollback"
              data-testid="rollback-confirm-panel"
              className="space-y-2 rounded-xl border border-line bg-surface-low p-3"
            >
              <p className="text-sm">
                Roll back from version {active?.config_version ?? "none"} to
                version {target}? New calls will use version {target}. Existing
                calls and deployment history are not changed; this adds a new
                history entry.
              </p>
              {rollbackCheck.data && <Checks a={rollbackCheck.data} />}
              {rollbackCheck.error && (
                <Notice tone="error">{rollbackCheck.error}</Notice>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  className={primaryBtn}
                  data-testid="rollback-confirm"
                  disabled={busy || !rollbackCheck.data?.eligible}
                  onClick={() =>
                    void act(
                      () =>
                        api.rollback(
                          clinicId,
                          target,
                          active?.config_version ?? null,
                          key(),
                        ),
                      `Rolled back: version ${target} is now active.`,
                    )
                  }
                >
                  Confirm rollback
                </button>
                <button
                  type="button"
                  className={secondaryBtn}
                  onClick={() => setTarget(null)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {done && (
        <Notice tone="success">
          <span data-testid="deployment-done">{done}</span>
        </Notice>
      )}
      {error && (
        <Notice tone="error">
          <span data-testid="deployment-error">{error}</span>
        </Notice>
      )}

      {history.data && history.data.length > 0 && (
        <div>
          <button
            type="button"
            className="text-sm text-primary underline"
            aria-expanded={showHistory}
            onClick={() => setShowHistory(!showHistory)}
          >
            {showHistory ? "Hide history" : `History (${history.data.length})`}
          </button>
          {showHistory && (
            <ul
              className="mt-2 divide-y divide-line text-sm"
              data-testid="deployment-history"
            >
              {history.data.slice(0, 8).map((e) => (
                <li key={e.id} className="py-2">
                  <span>{e.summary}</span>{" "}
                  <span className="font-mono text-xs text-muted">
                    {new Date(e.occurred_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
