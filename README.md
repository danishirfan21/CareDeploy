# CareDeploy

A multi-clinic deployment platform for AI voice agents in healthcare front-desk workflows. Clinics are configured once, published as immutable versions, and scheduled against a PostgreSQL-backed scheduling engine that the voice agent will call.

## Status

| Milestone | Scope | State |
| --- | --- | --- |
| M0 | Monorepo foundation, health checks, CI | Done |
| M1 | Multi-clinic management, five-step configuration wizard, immutable published versions | Done |
| M2 | Scheduling engine, confirmed and idempotent booking, reliability tests | Done |
| M2.5 | Stitch UI integration (frontend only) | Done |
| M3 | LiveKit voice agent and Playground | Partially complete: built and tested without audio; live voice verification blocked on credentials |
| M4 | Evaluation engine: 20 scenarios, workflow simulation, readiness and regression views | Done for workflow simulation. LLM and real-audio modes are not run (no approved credentials) |
| M5 | Call operations, metrics, cost estimates, Simulated Live deployment pointer with rollback | Built and tested on simulated data. Live audio and real cost rates are not verified |

What has and has not been verified is tracked in [`docs/implementation-status.md`](docs/implementation-status.md). The GitHub Actions workflow and Docker Compose setup have not been run yet.

## Features

- **Clinic configuration:** operating hours, appointment types, scheduling policy and agent behavior, edited as a draft and published as immutable, numbered versions.
- **Scheduling engine:** availability, booking, rescheduling and cancellation in the clinic's time zone, with DST handling and half-open intervals.
- **No double-booking:** enforced by a PostgreSQL exclusion constraint, not only application checks.
- **Safe state changes:** every booking, reschedule or cancel requires a server-issued authorization, a confirmed proposal bound to the exact details, and an idempotency key.
- **Recovery:** retries replay stored outcomes, and uncertain outcomes can be reconciled by operation id or key. A success is never reported before commit.
- **Typed adapter:** a `SchedulingAdapter` interface with one PostgreSQL implementation, used by the voice agent's tools.
- **Voice agent (M3):** a LiveKit worker with a speech-to-text, LLM and text-to-speech pipeline. It schedules only through the M2 API, runs on the clinic's frozen published configuration, and reports transcripts, tool activity and outcomes to the Playground. See [`docs/voice-agent.md`](docs/voice-agent.md).
- **Evaluations (M4):** twenty version-controlled scenarios drive the real voice-agent tools and scheduling API in isolated databases, with deterministic assertions, persisted immutable results, a deployment-readiness view that never merges evidence levels, and regression comparison. See [`docs/evaluations.md`](docs/evaluations.md).

## Architecture

```
apps/web   Next.js 16, React 19, TypeScript, Tailwind
apps/api   FastAPI, async SQLAlchemy 2, Alembic, Pydantic v2
services/voice-agent   LiveKit Agents worker (Python)
PostgreSQL 17 (Docker Compose or local binaries)
```

Routes live under `/api`. Pydantic schemas in `apps/api/app/schemas/` are mirrored by hand in `apps/web/src/lib/api/types.ts`, and all frontend calls go through `apps/web/src/lib/api/client.ts`.

## Quick start

**Prerequisites:** Node 22+, Python 3.12+, Docker with Compose v2 (or local PostgreSQL, see below).

```powershell
copy .env.example .env
docker compose up -d postgres
```

API (from `apps/api`):

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"      # Linux/macOS: .venv/bin/pip
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m app.seed --publish
.venv\Scripts\uvicorn app.main:app --port 8000 --reload
```

Web (from `apps/web`, in a second terminal):

```powershell
npm install
npm run dev
```

The web app runs on <http://localhost:3100> (not 3000, to avoid clashing with other local apps) and the API on <http://localhost:8000>.

To confirm it works, open `/api/health`, `/api/health/db` and the interactive docs at `/docs`, then check that the Clinics page lists Northstar Family Medicine and Lakeside Dermatology.

### Seed data

`python -m app.seed` creates two sample clinics (Northstar Family Medicine and Lakeside Dermatology) and three sample patients each (idempotent). Without `--publish` the clinics stay drafts; with it, both are published so scheduling works. The sample verification credentials (date of birth and last four phone digits) are listed in `apps/api/app/seed.py`.

### Scheduling test console

`/dev/scheduling` is a development-only page that walks through verify, availability, propose, confirm, book and cancel. It is not linked from the navigation and is not a patient portal.

### Voice agent (needs credentials)

Without LiveKit settings the Playground still loads and reports exactly which variables are missing when you press Start call. To run a live call you need a LiveKit project and a speech/LLM provider key (paid usage), set as described in [`services/voice-agent/README.md`](services/voice-agent/README.md), then start the worker with `python -m voice_agent.worker dev`. Everything else (API, tool layer, UI) is tested without them.

### Without Docker (Windows)

```powershell
$b = "D:\Postgresql\bin"   # your PostgreSQL bin directory
"caredeploy" | Set-Content $env:TEMP\pw.txt
& "$b\initdb.exe" -D .pgdata -U caredeploy --pwfile=$env:TEMP\pw.txt --auth=scram-sha-256
Start-Process "$b\pg_ctl.exe" "-D .pgdata -o `"-p 5433`" -l .pgdata\server.log start" -NoNewWindow
$env:PGPASSWORD = "caredeploy"; & "$b\createdb.exe" -h localhost -p 5433 -U caredeploy caredeploy
# .env: DATABASE_URL=postgresql+asyncpg://caredeploy:caredeploy@localhost:5433/caredeploy
```

These credentials are for local development only. The database role must be allowed to create extensions, because migration `0003` enables `btree_gist`.

## Testing

```powershell
# Backend (from apps/api)
.venv\Scripts\ruff check .; .venv\Scripts\ruff format --check .; .venv\Scripts\mypy; .venv\Scripts\pytest

# Frontend (from apps/web)
npm run lint; npm run typecheck; npm run format:check; npm run build

# End to end (from apps/web; needs PostgreSQL running)
npx playwright install chromium; npm run test:e2e
```

Backend tests run against a real PostgreSQL database named `<dev db>_test`, dropped, recreated and migrated on each run. Playwright starts its own API (:8001), web app (:3101) and database `caredeploy_e2e`, so ports 8001 and 3101 must be free. Your development database is never modified by tests.

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | System overview and components |
| [`docs/data-model.md`](docs/data-model.md) | Tables, constraints and migrations |
| [`docs/scheduling.md`](docs/scheduling.md) | Rules, time zones and DST, lifecycle, API, adapter, limitations |
| [`docs/authorization.md`](docs/authorization.md) | Simulated verification and the confirmation flow |
| [`docs/idempotency.md`](docs/idempotency.md) | Retry protocol, failure recovery, client guidance |
| [`docs/ui-architecture.md`](docs/ui-architecture.md) | Stitch integration, components, responsive behavior |
| [`docs/voice-agent.md`](docs/voice-agent.md) | Voice agent design, trust model, verification status |
| [`docs/voice-session-lifecycle.md`](docs/voice-session-lifecycle.md) | Call states, events, failure handling |
| [`docs/voice-tools.md`](docs/voice-tools.md) | Agent tools, result statuses, unknown-outcome recovery |
| [`docs/evaluations.md`](docs/evaluations.md) | Evaluation modes, isolation, runner, API, persistence |
| [`docs/evaluation-scenarios.md`](docs/evaluation-scenarios.md) | The twenty scenarios and what each asserts |
| [`docs/deployment-readiness.md`](docs/deployment-readiness.md) | Readiness levels and how to read them |
| [`docs/operations.md`](docs/operations.md) | Call list and detail, outcome classification |
| [`docs/deployments.md`](docs/deployments.md) | Promote, rollback, eligibility, concurrency, history |
| [`docs/observability.md`](docs/observability.md) | Metric definitions, cost estimates, redaction |
| [`docs/verification-debt.md`](docs/verification-debt.md) | Built but not yet verified live |
| [`docs/implementation-status.md`](docs/implementation-status.md) | What was verified and what was not |
| [`docs/product-spec.md`](docs/product-spec.md) | Product specification |

## Limitations

- Verification is simulated (no real identity proofing, no staff roles), and there is no integration with an external EHR.
- Evaluations: only the deterministic workflow simulation runs. The LLM-conversation and real-audio modes show "Not run" until credentials and spend are approved, so a passing result does not show that a model or speech behaves correctly.
- Voice: browser microphone only (no telephony). Live calls need LiveKit and speech/LLM credentials and incur paid usage; they have not been run. Not HIPAA compliant.
- Deployment is a simulated pointer ("Simulated Live") with one operator and no approvals; it deploys nothing externally. Cost figures are estimates that need a configured rates file; none ship. Not production ready.
- One bookable resource per clinic: no providers or rooms.
- The M1 configuration endpoints are unauthenticated.
- The UI follows the Stitch designs in `design-reference/` (see [`docs/ui-architecture.md`](docs/ui-architecture.md)); fidelity was checked by eye, not by pixel diff. Activity has a Calls tab (persisted calls, filters, details, metrics) and an Evaluations tab.

See [`docs/implementation-status.md`](docs/implementation-status.md) for the full list.
