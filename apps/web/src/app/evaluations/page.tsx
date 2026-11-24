"use client";

import { useState } from "react";
import { ClinicSelector } from "@/components/clinic-selector";
import { Icon } from "@/components/icons";
import { PageHeader, primaryBtn } from "@/components/ui";
import { EmptyState, StatusIndicator } from "@/components/primitives";

export default function Evaluations() {
  const [clinicId, setClinicId] = useState("");
  return (
    <>
      <PageHeader
        title="Evaluations"
        subtitle="Check an agent against automated scenarios before deployment."
        action={
          <button
            type="button"
            className={primaryBtn}
            disabled
            aria-describedby="eval-unavailable-note"
          >
            <Icon name="play" className="h-4 w-4" /> Run evaluation
          </button>
        }
      />
      <div className="mb-6 max-w-sm">
        <ClinicSelector
          label="Clinic and published version"
          value={clinicId}
          onChange={setClinicId}
        />
      </div>

      <section aria-label="Evaluation results">
        <EmptyState
          testId="unavailable"
          icon={<Icon name="evaluations" />}
          title="No evaluation runs"
        >
          <span id="eval-unavailable-note">
            Not available yet. Automated scenario runs are planned for milestone
            M4, so there are no scenarios, scores or reports to show.
          </span>
        </EmptyState>
        <p className="mt-4 text-center">
          <StatusIndicator tone="neutral">Readiness unknown</StatusIndicator>
        </p>
      </section>
    </>
  );
}
