# Implementation status

## M0 — Foundation (2026-11-24)

### Verified (actually executed)
- Backend: `ruff check`, `ruff format --check`, `mypy` (strict) pass; `pytest` 2 passed (health, CORS).
- `alembic upgrade head --sql` generates the expected `clinics` DDL (offline SQL only).
- Frontend: `eslint`, `tsc --noEmit`, `prettier --check`, `next build` pass.
- Playwright: "frontend reaches backend health endpoint" passes (browser -> Next on :3100 -> FastAPI on :8000).

### NOT verified (blocked)
- **Docker is not installed** on this machine, so `docker compose up postgres` was never run.
- **PostgreSQL connectivity and migration execution**: a local PostgreSQL 16 service exists, but requires a password I don't have (I did not guess credentials). Hence:
  - `pytest::test_database_connectivity` FAILS (cannot connect).
  - Playwright "backend reports database connectivity" FAILS.
  - `alembic upgrade head` was not executed against a real database.
  - `/api/health/db` returns 503 `{"status":"unavailable"}` here (correct failure behaviour, observed).
- CI workflow is unrun (not pushed).

### To finish M0 acceptance
Install Docker, `docker compose up -d postgres`, `alembic upgrade head`, `pytest`, `npm run test:e2e` (see README).

### Notes
- Web dev port is 3100 because 3000 is occupied by another local app.
- Stitch exports absent; see `design/README.md`.
- Next.js scaffold enabled `cacheComponents` in `next.config.ts` by default; left as generated.
