import { Icon } from "@/components/icons";
import { primaryBtn, secondaryBtn } from "@/components/ui";

/** Five-segment progress bar plus the "Step N of 5" label (kept as test id step-indicator). */
export function WizardProgress({
  step,
  titles,
  clinicName,
}: {
  step: number;
  titles: readonly string[];
  clinicName?: string;
}) {
  return (
    <div className="mb-8">
      <div className="mb-3 flex items-center justify-between gap-3 text-sm">
        <span className="truncate font-medium">
          {clinicName ? `${clinicName} · ` : ""}Setup wizard
        </span>
        <span
          className="shrink-0 font-mono text-[11px] tracking-[0.04em] text-accent"
          aria-hidden
        >
          Step {step} of {titles.length}
        </span>
      </div>
      <div className="flex gap-2" aria-hidden>
        {titles.map((_, i) => (
          <div
            key={i}
            className={`h-1.5 flex-1 rounded-full ${i < step ? "bg-accent" : "bg-surface-high"}`}
          />
        ))}
      </div>
      <p
        className="mt-5 text-2xl font-semibold tracking-[-0.02em] md:text-[28px]"
        data-testid="step-indicator"
        aria-live="polite"
      >
        Step {step} of {titles.length}: {titles[step - 1]}
      </p>
    </div>
  );
}

export function WizardNavigation({
  step,
  lastStep,
  busy,
  canPublish,
  onBack,
  onSave,
  onPublish,
}: {
  step: number;
  lastStep: number;
  busy: boolean;
  canPublish: boolean;
  onBack: () => void;
  onSave: () => void;
  onPublish: () => void;
}) {
  return (
    <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
      <button
        type="button"
        className={secondaryBtn}
        onClick={onBack}
        disabled={step === 1 || busy}
      >
        <Icon name="arrowLeft" className="h-4 w-4" /> Back
      </button>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm text-foreground/80 hover:bg-black/5 disabled:opacity-50"
          onClick={onSave}
          disabled={busy}
        >
          {step === lastStep ? "Save draft" : "Save"}
        </button>
        {step < lastStep ? (
          <button type="submit" className={primaryBtn} disabled={busy}>
            Continue <Icon name="arrowRight" className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="button"
            className={primaryBtn}
            onClick={onPublish}
            disabled={busy || !canPublish}
          >
            Publish version
          </button>
        )}
      </div>
    </div>
  );
}
