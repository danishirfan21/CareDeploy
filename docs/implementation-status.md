# Implementation status

## M1 - Multi-clinic management and configuration (2026-11-24)

### Verified (actually executed)
- Backend: `ruff check`, `ruff format --check`, `mypy` (strict) clean; `pytest` 22 passed against a real PostgreSQL database (`caredeploy_test`, recreated per run): CRUD, 404/409/422 codes, config validation rules, operating-hours rules, persistence read back via a separate connection, clinic isolation, version immutability (including the database trigger rejecting UPDATE/DELETE), seed distinctness.
- Migrations: `alembic upgrade head` (0001, 0002) applied to the dev database; additive.
- Frontend: `eslint`, `tsc`, `prettier --check`, `next build` pass.
- Playwright: 13 passed against real API + PostgreSQL (`caredeploy_e2e`, seeded, API :8001, web :3101): sidebar navigation and collapse, unavailable states, both seeded clinics with distinct config, per-step validation, creating a third clinic, five-step wizard, save/reopen/reload persistence, blocked then successful publish, published visibility, duplicate-name rejection, and the M0 health checks.
- Persistence across restart: created a clinic through the API, killed the API process, restarted it, and the clinic was still listed (dev DB on :5433).
- M0 tests still pass (3 backend health tests incl. DB; 2 e2e health tests).

### Not verified / limitations
- **Docker Compose** still never run (Docker not installed). **GitHub Actions** workflow updated for M1 but never run.
- Stitch exports are absent, so the UI makes no claim of visual fidelity to any design.
- "Draft" is the live editable rows; publishing snapshots them into an immutable `config_versions` row. There is no separate draft table or per-field history.
- Appointment-type and operating-hour rows are replaced on every save, so their ids are not stable across saves.
- Publishing does **not** create a live voice agent; the UI says so. Playground (M3) and evaluations (M4) are explicitly unavailable pages.
- No authentication or multi-user concurrency control beyond a row lock during publish.
- Browser coverage is Chromium only; responsive layout was not tested at mobile widths in e2e.
- Test databases: pytest uses `caredeploy_test`, Playwright `caredeploy_e2e`; both are dropped and recreated on each run.

## M0 — Foundation (2026-11-24)

### Verified (actually executed)
- Backend: `ruff`, `mypy` (strict) pass; `pytest` 3 passed, including real DB connectivity.
- `alembic upgrade head` executed against real PostgreSQL 16; `clinics` and `alembic_version` tables confirmed via psql.
- `/api/health/db` returned `{"status":"ok","database":true}` live.
- Frontend: `eslint`, `tsc`, `prettier`, `next build` pass.
- Playwright: 2 passed (frontend -> API health, and database connectivity through the UI).

### Not verified
- **Docker Compose**: Docker is not installed here, so `docker compose up postgres` was never run. The compose file is untested.
- GitHub Actions CI is unrun (not pushed).
- Verification used a dedicated local cluster (`D:\CareDeploy\.pgdata`, port 5433, Postgres 16 binaries from `D:\Postgresql`), not Compose's Postgres 17.

### Notes
- Web dev port is 3100 because 3000 is occupied by another local app.
- Stitch exports absent; see `design/README.md`.
- Next.js scaffold enabled `cacheComponents` in `next.config.ts` by default; left as generated.
