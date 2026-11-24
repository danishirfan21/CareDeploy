# Implementation status

## M1 — Multi-clinic management and configuration (2026-11-24)

### Verified (actually executed)
- Backend: `pytest` 22 passed against a real, isolated PostgreSQL database (`caredeploy_test`): CRUD, config and operating-hours validation, per-clinic isolation, published-version immutability (DB trigger), persistence, seed data. `ruff`, `ruff format --check` and `mypy` (strict) pass.
- Migration `0002` (additive) applied to the dev database; `python -m app.seed` is idempotent (both clinics present).
- Frontend: `eslint`, `tsc`, `prettier --check` and `next build` pass.
- Playwright: 13 passed against an isolated stack (API :8001, web :3101, database `caredeploy_e2e`, seeded each run): M0 health, navigation and sidebar, clinic list, new clinic, five-step wizard (validation, Back keeps state), save and reopen, publish blocked until valid, duplicate names, published-version visibility.

### Not verified / limitations
- UI is functional and intentionally unpolished; the user will supply designs. No fidelity to the Stitch designs is claimed (exports unavailable).
- Publishing creates an immutable configuration version only. No voice agent exists; the UI says so. Playground, Evaluations and Activity are labeled unavailable.
- Appointment type ids are not stable across draft saves (types are replaced on save).
- Docker Compose and GitHub Actions CI remain unrun.
- Playwright specs were written by two sessions working in the same folder; they were reconciled and pass together.

---

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
