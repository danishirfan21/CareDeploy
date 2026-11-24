# Implementation status

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
