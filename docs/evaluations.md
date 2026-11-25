# Evaluations (M4)

The evaluation engine checks the real scheduling agent against version-controlled scenarios. It is a regression and deployment-gating tool for scheduling behavior. It does not certify clinical safety, compliance or speech quality.

## One agent, three evidence levels

Evaluation never builds a second agent. A scenario drives the same pieces a call uses:

- the voice-agent `Toolbox` (tool contracts, `S#`/`A#` references, confirmation discipline, idempotency keys, reconciliation through the operations ledger),
- the voice-agent `SchedulingClient`, pointed at the real M2 scheduling API running in-process on PostgreSQL,
- `build_instructions` for the clinic's published configuration, and
- the same scheduling engine, authorization and idempotency code.

If someone weakens the shared toolbox or the scheduling engine, evaluation results change. `tests/test_evals_runner.py` proves this by mutating both and requiring the matching scenarios to fail.

The three modes answer different questions and are **never combined into one number**.

| Mode | Question it answers | Needs | Status in this release |
| --- | --- | --- | --- |
| A. Workflow simulation | Do the tools, backend rules, authorization and recovery behave correctly when driven through a fixed script of caller actions? | Local services only. No paid credentials. | Implemented and run |
| B. LLM conversation | Does a language model choose the right tools and say the right things with a simulated caller? | Approved model credentials. | Not run. Shown as "Not run" with the reason. Never billed without approval. |
| C. Real audio | Do speech recognition, turn-taking, interruption and synthesis work end to end? | LiveKit and speech providers. | Not run. No runner exists. |

Mode A scripts the caller. It cannot show that a model *chooses* these actions or that speech works. Each scenario lists what Mode A cannot evaluate (`not_evaluated_in_workflow`) and the UI shows it.

## Scenario files

`evals/scenarios/EVAL-001.json` ... `EVAL-021.json`. The JSON file is the source of truth and is strictly validated before anything runs:

- unknown keys are rejected, ids must match `EVAL-NNN` and the file name, duplicate ids are rejected;
- a scenario must declare at least one objective assertion or step expectation;
- `real_audio` cannot be declared yet (no runner exists), and an `llm` block needs objective assertions;
- loading reports every problem in every file; nothing runs if any selected file is invalid.

A scenario has an id, `version`, category, severity (`critical`, `high`, `medium`), the modes it supports, a fixed clock, requirements on the clinic configuration, fixtures, expected behavior, and a workflow of steps (tool calls, caller utterances, direct API calls, injected faults) plus assertions. The scenario content hash and version are stored with every result, so a result is always tied to the exact definition that produced it. See `evaluation-scenarios.md` for the twenty scenarios.

If the selected configuration cannot support a scenario (for example cancellation is not enabled), the result is `skipped` with the unmet requirement named. A skipped scenario is not a pass.

## Deterministic assertions

Assertions check facts, not impressions: the tools called and their order, tool outcome codes, database rows read through a separate connection, operation outcomes, forbidden actions, disclosure of data the caller must not see, escalation records, and phrases in the generated instructions. A language model never overrides a database fact. (Mode B judgments, when they exist, are recorded separately and cannot turn a failed assertion into a pass.)

## Isolation

Evaluations must never touch the clinics people work in. Immutability triggers on `config_versions` and appointment history rule out cleaning up by deleting rows, so isolation is by database:

1. Each run clones a per-run template database from the application's database schema.
2. Each scenario gets its own database cloned from that template, with a fresh clinic built from the **selected published configuration snapshot**, sample patients and appointments the scenario declares, and a fixed clock.
3. The scenario database is dropped afterwards, including after a crash or timeout. Database names carry a strict pattern and the drop code refuses any other name, so it cannot drop an ordinary database.

Scenarios therefore start from identical state and do not affect each other or the development data. Results are written to the application's own database through a separate connection (`ResultsStore`).

## Running

A run executes in a **separate worker process** (`python -m app.evals.worker <run_id>`), because scenarios re-point the in-process application engine at scenario databases. The API only creates a `queued` run, starts the worker and returns `202`. API handlers never block on scenario execution.

- Selection: all scenarios, one category, or one scenario. Rerun creates a new linked run for one scenario against the same configuration version.
- Bounded time: each scenario has its own timeout (default and per-scenario limits), and setup has a limit. A timeout is `incomplete`, not `failed` and never `passed`.
- Crashes: an exception inside the runner records `error` with the exception type. Nothing is ever recorded as passed after a crash. A run containing an `error` or `incomplete` result finishes as `incomplete`.
- Cancellation: a queued run is cancelled immediately; a running run stops between scenarios and unstarted scenarios are recorded `not_run`. `not_run` and `skipped` are never counted as success.
- Duplicate prevention: one active run per clinic, enforced under an advisory lock. A second submission returns `409 run_in_progress`.
- Stale runs: a worker that stops heartbeating is detected on the next read and the run is marked `error` ("worker stopped responding"), so a clinic is never blocked forever.

## Persistence

Migration `0005_evaluations` (additive; 0001-0004 are untouched) adds `eval_runs`, `eval_scenario_results` and `eval_events`.

- A run records clinic, configuration version and a hash of the snapshot, mode, selection, runner version, scenario-suite hash, requester, timestamps and counts.
- A result records the scenario id, version and content hash, status, failure message, assertions, expected and observed data, and a bounded trace.
- `eval_events` is append-only (bounded to 300 events per scenario, long text truncated). Secrets and credentials are never recorded.
- Once a run reaches a terminal state, database triggers reject any further UPDATE or DELETE of the run and its results.

## API

All routes are under `/api`. Clients can only choose server-side scenarios by id or category; they cannot submit scenario bodies, code or file paths. Errors use `{"detail": {"code", "message"}}`.

| Route | Purpose |
| --- | --- |
| `GET /evaluations/scenarios` | Scenario catalog, categories and the availability of each mode (with reasons). |
| `GET /clinics/{id}/evaluations/runs` | Persisted runs, newest first. |
| `POST /clinics/{id}/evaluations/runs` | Start a run: `{mode, config_version?, selection}`. `202`; `409 mode_unavailable`, `409 run_in_progress`, `404 version_not_found`. |
| `GET /clinics/{id}/evaluations/runs/{run}` | Progress and results grouped by category with real counts. |
| `GET .../runs/{run}/results/{scenario}` | One result with assertions, expected vs observed, tool events and trace. |
| `POST .../runs/{run}/cancel` | Request cancellation. |
| `POST .../runs/{run}/rerun` | Rerun one scenario as a linked run. |
| `GET /clinics/{id}/evaluations/readiness` | Deployment readiness (see `deployment-readiness.md`). |
| `GET /clinics/{id}/evaluations/compare?base=&head=` | Regression comparison of two runs of the same mode. |

## Regression comparison

Compare two runs of the **same mode** only (`409 incompatible_runs` otherwise). Scenarios are bucketed as newly passing, newly failing, unchanged, newly not executed, added or removed. If a scenario's definition changed between the runs it is listed as **not comparable** instead of being counted as an improvement or a regression, and the comparison warns when the suites differ, a run was partial or incomplete, or (for Mode B) the model differs.

## Running it

The Evaluations page (`/evaluations`) selects a clinic, a published version, a mode and a scenario scope, then shows progress, grouped results, failure inspection and the readiness message. The Activity page lists persisted runs under an Evaluations tab.

Mode B is enabled only when `EVAL_LLM_API_KEY` is set **and** `EVAL_LLM_APPROVED=true`. This release contains no language-model evaluation provider, so even with both set the mode reports that no provider is implemented. It never uses the ambient `OPENAI_API_KEY`.

## Limits

- The sample clinics are sample data. Passing results say nothing about real patients, clinical safety or compliance.
- Single-operator development: the requester is recorded as `local-dev-operator`; there is no authentication.
- One evaluation per clinic at a time; the worker runs scenarios sequentially.
- A passing Mode A run is evidence about backend and tool behavior only. See `verification-debt.md` for everything live that is still unverified.

## M6 review: can the evaluator fail?

Mutation tests in `apps/api/tests/test_evals_runner.py` deliberately break the code under test (a tool reporting success without writing, an ignored idempotency key, broken clinic or patient scoping, an ownership bypass, disabled confirmation, bypassed hours) and require the right scenario to fail. This found one real gap: EVAL-015 did not cover a foreign patient token against a patient's appointment list; a step was added (scenario version bumped, which invalidates older evidence by design). One gap remains open: no scenario covers the cancellation window (VD-20). Evidence age is configurable via `DEPLOYMENT_EVIDENCE_MAX_AGE_DAYS` (default 30, a demo assumption).
