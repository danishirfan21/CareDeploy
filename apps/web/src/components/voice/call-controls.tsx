import { Icon } from "@/components/icons";
import type { CallPhase } from "./types";

export interface CallControlsProps {
  phase: CallPhase;
  muted?: boolean;
  onStart?: () => void;
  onEnd?: () => void;
  onToggleMute?: () => void;
}

/**
 * Microphone and call controls. In the `unavailable` phase (all of M2.5) no control is
 * actionable; M3 supplies the handlers and the real phase.
 */
export function CallControls({
  phase,
  muted = false,
  onStart,
  onEnd,
  onToggleMute,
}: CallControlsProps) {
  const base =
    "flex h-12 min-w-12 items-center justify-center gap-2 rounded-full px-5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";
  const live =
    phase === "active" ||
    phase === "connecting" ||
    phase === "starting" ||
    phase === "ending";
  const micOn = phase === "active";
  return (
    <div
      role="group"
      aria-label="Call controls"
      data-phase={phase}
      className="flex items-center justify-center gap-3"
    >
      <button
        type="button"
        className={`${base} bg-surface-high/70`}
        aria-pressed={muted}
        aria-label={muted ? "Unmute microphone" : "Mute microphone"}
        disabled={!micOn}
        onClick={onToggleMute}
      >
        <Icon name="mic" />
      </button>
      {live ? (
        <button
          type="button"
          className={`${base} bg-danger text-white`}
          disabled={phase === "ending"}
          onClick={onEnd}
        >
          <Icon name="phoneOff" /> End call
        </button>
      ) : (
        <button
          type="button"
          className={`${base} bg-primary text-white`}
          disabled={phase === "unavailable"}
          onClick={onStart}
        >
          <Icon name="phone" /> Start call
        </button>
      )}
    </div>
  );
}
