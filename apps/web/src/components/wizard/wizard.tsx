"use client";

import Link from "next/link";
import { useState } from "react";
import { ConfigSummary } from "@/components/config-summary";
import {
  ButtonLink,
  Notice,
  PageHeader,
  primaryBtn,
  secondaryBtn,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api/client";
import type {
  ClinicConfig,
  ConfigVersion,
  ValidationResult,
} from "@/lib/api/types";
import { useFetch } from "@/lib/use-fetch";
import { AgentStep, DetailsStep, HoursServicesStep, PolicyStep } from "./steps";
import {
  STEP_TITLES,
  emptyConfig,
  validateStep,
  type StepErrors,
} from "./validation";

/** `clinicId` null = creating a new clinic; the clinic is created when step 1 is continued. */
export function Wizard({ clinicId }: { clinicId: string | null }) {
  const { data, error, loading } = useFetch(`config:${clinicId}`, async () =>
    clinicId ? (await api.getConfig(clinicId)).config : emptyConfig(),
  );
  if (loading)
    return <p className="text-sm text-muted">Loading configuration…</p>;
  if (error || !data)
    return <Notice tone="error">Could not load configuration: {error}</Notice>;
  return <WizardBody initialId={clinicId} initialConfig={data} />;
}

type Banner = { tone: "error" | "success" | "info"; text: string } | null;

function WizardBody({
  initialId,
  initialConfig,
}: {
  initialId: string | null;
  initialConfig: ClinicConfig;
}) {
  const [id, setId] = useState(initialId);
  const [config, setConfig] = useState(initialConfig);
  const [step, setStep] = useState(1);
  const [errors, setErrors] = useState<StepErrors>({});
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [published, setPublished] = useState<ConfigVersion | null>(null);

  const edit = (next: ClinicConfig) => {
    setConfig(next);
    setBanner(null);
    setPublished(null);
  };

  /** Save the whole draft, creating the clinic first if it does not exist yet. */
  async function persist(): Promise<string> {
    let cid = id;
    if (!cid) {
      const created = await api.createClinic(config.details);
      cid = created.id;
      setId(cid);
      window.history.replaceState(null, "", `/clinics/${cid}/configure`);
    }
    await api.saveConfig(cid, config);
    return cid;
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setBanner(null);
    try {
      await action();
    } catch (e) {
      const detail =
        e instanceof ApiError ? (e.body as { detail?: unknown })?.detail : null;
      if (detail && typeof detail === "object" && "issues" in detail) {
        setValidation(detail as ValidationResult);
      }
      setBanner({
        tone: "error",
        text: e instanceof Error ? e.message : "Something went wrong",
      });
    } finally {
      setBusy(false);
    }
  }

  const checkStep = (): boolean => {
    const e = validateStep(step, config);
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const onContinue = () => {
    if (!checkStep()) return;
    void run(async () => {
      if (step === 1 && !id) {
        await persist();
        setBanner({ tone: "success", text: "Clinic created. Draft saved." });
      }
      if (step === 4) {
        const cid = await persist();
        setValidation(await api.validateConfig(cid));
      }
      setStep(step + 1);
    });
  };

  const onBack = () => {
    setErrors({});
    setBanner(null);
    setPublished(null);
    setStep(step - 1);
  };

  const onSave = () => {
    if (step < 5 && !checkStep()) return;
    void run(async () => {
      const cid = await persist();
      if (step === 5) setValidation(await api.validateConfig(cid));
      setBanner({ tone: "success", text: "Draft saved." });
    });
  };

  const onPublish = () =>
    void run(async () => {
      const cid = await persist();
      const version = await api.publishConfig(cid);
      setPublished(version);
      setValidation(await api.validateConfig(cid));
    });

  const blocking =
    validation?.issues.filter((i) => i.severity === "error") ?? [];
  const warnings =
    validation?.issues.filter((i) => i.severity === "warning") ?? [];
  const title =
    id || config.details.name
      ? `Configure ${config.details.name || "clinic"}`
      : "New clinic";

  return (
    <>
      <PageHeader
        title={title}
        subtitle="Configuration draft. Nothing is live until later milestones."
      />

      <div className="mb-8">
        <div className="mb-2 flex gap-1.5" aria-hidden>
          {STEP_TITLES.map((_, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full ${i < step ? "bg-accent" : "bg-gray-200"}`}
            />
          ))}
        </div>
        <p className="text-sm text-muted" data-testid="step-indicator">
          Step {step} of 5 ·{" "}
          <span className="font-medium text-foreground">
            {STEP_TITLES[step - 1]}
          </span>
        </p>
      </div>

      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (step < 5) onContinue();
        }}
      >
        {step === 1 && (
          <DetailsStep config={config} onChange={edit} errors={errors} />
        )}
        {step === 2 && (
          <HoursServicesStep config={config} onChange={edit} errors={errors} />
        )}
        {step === 3 && (
          <PolicyStep config={config} onChange={edit} errors={errors} />
        )}
        {step === 4 && (
          <AgentStep config={config} onChange={edit} errors={errors} />
        )}
        {step === 5 && (
          <div className="space-y-6">
            <div>
              <h2 className="mb-2 font-medium">Validation</h2>
              {validation === null ? (
                <Notice tone="info">
                  Not checked yet. Save the draft to validate.
                </Notice>
              ) : (
                <div className="space-y-2" data-testid="validation-results">
                  {blocking.length === 0 ? (
                    <Notice tone="success">
                      No blocking issues. This configuration can be published.
                    </Notice>
                  ) : (
                    <Notice tone="error">
                      <p className="mb-1 font-medium">
                        {blocking.length} issue{blocking.length > 1 ? "s" : ""}{" "}
                        to fix before publishing
                      </p>
                      <ul className="list-disc pl-5">
                        {blocking.map((i, n) => (
                          <li key={n}>{i.message}</li>
                        ))}
                      </ul>
                    </Notice>
                  )}
                  {warnings.length > 0 && (
                    <Notice tone="warning">
                      <ul className="list-disc pl-5">
                        {warnings.map((i, n) => (
                          <li key={n}>{i.message}</li>
                        ))}
                      </ul>
                    </Notice>
                  )}
                </div>
              )}
            </div>
            <ConfigSummary config={config} />
            <p className="text-xs text-muted">
              Publishing saves an immutable, numbered version of this
              configuration. It does not make a live voice agent available; that
              comes in later milestones.
            </p>
          </div>
        )}

        <div className="mt-6 space-y-3">
          {banner && <Notice tone={banner.tone}>{banner.text}</Notice>}
          {published && (
            <Notice tone="success">
              <p data-testid="published-notice">
                <strong className="font-medium">
                  Version {published.version} published.
                </strong>{" "}
                It is now an immutable snapshot. No live voice agent is
                available yet.
              </p>
              <p className="mt-2">
                <Link
                  href={`/clinics/${published.clinic_id}`}
                  className="font-medium underline"
                >
                  View clinic
                </Link>
              </p>
            </Notice>
          )}
        </div>

        <div className="mt-8 flex items-center justify-between border-t border-line pt-5">
          <button
            type="button"
            className={secondaryBtn}
            onClick={onBack}
            disabled={step === 1 || busy}
          >
            Back
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              className={secondaryBtn}
              onClick={onSave}
              disabled={busy}
            >
              {step === 5 ? "Save draft" : "Save"}
            </button>
            {step < 5 ? (
              <button type="submit" className={primaryBtn} disabled={busy}>
                Continue
              </button>
            ) : (
              <button
                type="button"
                className={primaryBtn}
                onClick={onPublish}
                disabled={busy || validation === null || blocking.length > 0}
              >
                Publish version
              </button>
            )}
          </div>
        </div>
      </form>
      {step === 5 && id && published === null && (
        <p className="mt-4 text-sm">
          <ButtonLink href={`/clinics/${id}`} variant="secondary">
            Back to clinic
          </ButtonLink>
        </p>
      )}
    </>
  );
}
