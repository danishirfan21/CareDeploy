# CareDeploy

A multi-clinic deployment platform for AI voice agents in healthcare front-desk workflows. Clinics are configured once, published as immutable versions, and scheduled against a PostgreSQL-backed scheduling engine that the voice agent will call.

> **Demo project.** All clinics and patients are fictional. Patient verification is simulated and there is no integration with any real EHR. Not for use with real patient data.

## Status

| Milestone | Scope | State |
| --- | --- | --- |
| M0 | Monorepo foundation, health checks, CI | Done |
| M1 | Multi-clinic management, five-step configuration wizard, immutable published versions | Done |
| M2 | Scheduling engine, confirmed and idempotent booking, reliability tests | Done |
| M3 | Voice agent and playground | Not started |
| M4 | Evaluations | Not started |

What has and has not been verified is tracked in [`docs/implementation-status.md`](docs/implementation-status.md). The GitHub Actions workflow and Docker Compose setup have not been run yet.

## Features

- **Clinic configuration:** operating hours, appointment types, scheduling policy and agent behavior, edited as a draft and published as immutable, numbered versions.
- **Scheduling engine:** availability, booking, rescheduling and cancellation in the clinic's time zone, with DST handling and half-open intervals.
- **No double-booking:** enforced by a PostgreSQL exclusion constraint, not only application checks.
- **Safe state changes:** every booking, reschedule or cancel requires a server-issued authorization, a confirmed proposal bound to the exact details, and an idempotency key.
- **Recovery:** retries replay stored outcomes, and uncertain outcomes can be reconciled by operation id or key. A success is never reported before commit.
- **Typed adapter:** a `SchedulingAdapter` interface with one PostgreSQL implementation, ready for the voice agent.

## Architecture

```
apps/web   Next.js 16, React 19, TypeScript, Tailwind
apps/api   FastAPI, async SQLAlchemy 2, Alembic, Pydantic v2
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

`python -m app.seed` creates the two fictional clinics and three fictional patients each (idempotent). Without `--publish` the clinics stay drafts; with it, both are published so scheduling works. The demo verification credentials (a fictional date of birth and the last four phone digits) are listed in `apps/api/app/seed.py`.

### Scheduling test console

`/dev/scheduling` is a development-only page that walks through verify, availability, propose, confirm, book and cancel. It is not linked from the navigation and is not a patient portal.

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
| [`docs/implementation-status.md`](docs/implementation-status.md) | What was verified and what was not |
| [`docs/product-spec.md`](docs/product-spec.md) | Product specification |

## Limitations

- Verification is simulated; there is no real identity proofing and no staff roles.
- One bookable resource per clinic: no providers or rooms.
- The M1 configuration endpoints are unauthenticated.
- Design exports from Stitch are not yet in `design/`, so the UI makes no claim of visual fidelity.

See [`docs/implementation-status.md`](docs/implementation-status.md) for the full list.
