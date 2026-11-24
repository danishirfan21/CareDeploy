# Deployment readiness

Readiness answers one narrow question: *what has actually been shown about this published configuration version?* It is computed on read from immutable evaluation results, per clinic and per configuration version, so it cannot drift from the evidence. It is not a score and it is never a percentage.

## Levels

| Level | Meaning |
| --- | --- |
| Not evaluated | No completed full-suite workflow run exists for this version (no run, a partial run, or a run that did not finish). |
| Blocked by critical failures | At least one **critical** scenario failed, errored, did not finish, was skipped or was not run in the latest relevant run. Promotion is blocked until it passes in a completed full-suite run. |
| Simulation checks passed | The latest full workflow run passed every critical scenario. Says nothing about a model choosing these actions or about speech. |
| Live verification pending | Workflow and LLM conversation suites both passed. Real-audio behavior is unverified. |
| Verified for the explicitly tested scope | Every mode passed for the listed scenarios. Not reachable in this release because no real-audio runner exists. |

The message shown beside each level is fixed text. It never says "ready", "safe" or "compliant". The highest level reachable today is *Simulation checks passed*.

## Rules

- Only a **completed, full-suite** run establishes anything. A partial run (one scenario or category), an `incomplete` run, a cancelled run or an errored run is reported as such and leaves the level at *Not evaluated*.
- Critical scenarios gate. A critical scenario that is `failed`, `error`, `incomplete`, `skipped` or `not_run` is unmet. A non-critical failure or skip does not block, but it is listed in the notes so it cannot hide.
- Each mode is reported on its own line (*Workflow simulation*, *LLM conversation*, *Real audio*), with its own counts. `Not run` is shown as `Not run`, with the reason. Results from different modes are never added together or averaged.
- Readiness is per configuration version. Publishing a new version starts at *Not evaluated* again; results for an older version do not carry forward.
- Simulated promotion (`simulated_promotion`) is `blocked`, `allowed` or `not_evaluated`. It describes whether the workflow evidence permits promoting in a simulated environment. `live_verification` stays `pending` until every mode has passed.

## Reading the evidence

1. Open Evaluations, choose the clinic and the published version.
2. Check each mode line: a mode that is `Not run` has no evidence behind it, whatever the other modes show.
3. For a blocked level, the blocking scenarios are listed with their statuses; open one to see expected versus observed, the failed assertions, the tool events and the trace.
4. Compare against an earlier run of the same mode to see what changed. Scenarios whose definitions changed are marked not comparable and are excluded from regression counts.

## What readiness is not

- Not a clinical-safety, privacy or regulatory assessment. The project is not HIPAA compliant.
- Not a statement about live voice behavior while Mode B and Mode C are not run.
- Not an approval workflow. Nothing in the product is gated on it yet; it is information for the person deciding.

Open live-verification items are tracked in `verification-debt.md`.
