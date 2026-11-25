# Demo script (about 12 minutes)

A walkthrough for a technical reviewer. Everything shown is real behavior of the running system against sample data, except the live voice step, which is **pending**: it needs LiveKit and speech/LLM credentials that were not used (see [`live-voice-test-plan.md`](live-voice-test-plan.md)). Do not present Simulated Live evidence as proof of live speech.

This is an independent portfolio project. It is not affiliated with any company, and it claims nothing about any company's internal tools.

## Setup (before the call)

```powershell
docker compose up -d postgres        # or your local PostgreSQL
# from apps/api
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m app.seed --publish
.venv\Scripts\uvicorn app.main:app --port 8000
# from apps/web
npm run dev                          # http://localhost:3100
```

## Steps

| # | Show | Say | Evidence on screen |
| --- | --- | --- | --- |
| 1 | **Clinics > Northstar Family Medicine** | Each clinic is configured once: hours, appointment types, policy, agent behavior. No clinic names are hardcoded in code. | Configuration wizard with saved values. |
| 2 | **Published version** | Publishing creates an immutable numbered snapshot. A draft is never what calls use. | Version list; the database refuses edits to a published row. |
| 3 | **Evaluations > Run all (Simulated Live workflow)** | Twenty-one scenarios drive the real voice-agent tool layer and the real scheduling API against isolated PostgreSQL databases. | Scenario results, each with its assertions. |
| 4 | **A failure or block** | Run the evaluation after deliberately weakening a rule (see "Show a failure" below), or open a version with no evidence and try to promote. | A red scenario with the failed assertion, or "Promotion blocked: required coverage". |
| 5 | **Readiness** | Readiness is computed on the server. The browser cannot supply or override it. Passing means the workflow simulation passed, and the page says real voice verification has not been completed. | Readiness checks, evidence level labelled. |
| 6 | **Promote to Simulated Live** | Promotion moves a pointer after re-checking evidence under a row lock. It deploys nothing externally. | Deployment panel and history event with the evidence it used. |
| 7 | **Playground** | The browser starts a session pinned to the active version. The no-audio test transport shows the pipeline; real audio needs credentials. | Session bound to clinic and "config v1". |
| 8 | **Live voice appointment (PENDING)** | This is the step that needs LiveKit and provider credentials. It is documented as TEST-01 to TEST-10 and has not been run. | Say plainly that it is not done. Show the preflight reporting missing variables. |
| 9 | **Activity > Calls > a call** | Every call has a classified outcome (completed, escalated, failed, abandoned, unknown), the operations it caused, and its tool trace. Escalation is not counted as failure; unknown is kept apart. | Call detail with operations checked against the ledger. |
| 10 | **Lakeside Dermatology** | A second clinic has different hours, types and policy, enforced by the same code. | Different configuration; scheduling rejects what the policy forbids. |
| 11 | **Publish a changed version, evaluate, promote** | New sessions use the new version; existing sessions keep theirs. | Two sessions on different versions. |
| 12 | **Rollback** | Rollback is a new history event, never an edit. It needs fresh evidence for the target. | History: promoted, promoted, rolled back. |

## Show a failure (optional, 2 minutes)

Evaluation is only worth trusting if it can fail. The backend test suite proves this by weakening code on purpose and checking that the right scenario turns red (`apps/api/tests/test_evals_runner.py`: disabled confirmation, bypassed hours rule, a tool that claims success without writing, an ignored idempotency key, broken patient and clinic scoping). Run one live:

```powershell
cd apps/api
.venv\Scripts\python -m pytest tests/test_evals_runner.py -k "false_tool_success" -q
```

## If asked

- **Is it production ready?** No. See [`security.md`](security.md) and [`verification-matrix.md`](verification-matrix.md).
- **Does the voice work?** The tool layer, transport lifecycle and UI are tested without audio. Speech recognition, synthesis, interruption and model behavior are unverified.
- **What would you do next?** Run the ten live tests, then Mode B (model-driven) evaluations with approved spend.
