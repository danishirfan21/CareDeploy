# Implementation status

## M2.5 - Stitch UI integration (2026-11-24)

Frontend only; backend, models and migrations unchanged. See `ui-architecture.md`.

### Verified (actually executed)
- Backend: ruff, ruff format, strict mypy clean; 97 pytest passed (unchanged).
- Frontend: eslint, tsc, prettier check, `next build` pass.
- Playwright: 26 passed, 0 skipped (the 14 earlier tests, updated home/navigation assertions, new tests for
  playground/evaluations/activity unavailable states, component preview, tablet and mobile overflow and
  navigation, mobile wizard, and a screenshot capture spec). The e2e run uses real frontend, API and PostgreSQL.
- Screens rendered in Chromium at 1440, 768 and 390 px and compared by eye with the Stitch `screen.png` files.

### Not verified / limitations
- Visual fidelity is approximate (no pixel diff). Wizard uses labelled inputs, not Stitch chip selectors,
  and lives on its own route. Stitch-only content (fake labels, task composer, sample data) is intentionally absent.
- Mobile virtual keyboard and real touch devices were not tested. Chromium only.
- GitHub Actions and Docker Compose still never run.

## M2 - Scheduling engine and reliability (2026-11-24)

### Verified (actually executed)
- Backend: `ruff check`, `ruff format --check`, `mypy` (strict, 40 source files) clean; `pytest` **97 passed** against real PostgreSQL (`caredeploy_test`): 22 M1/M0 tests unchanged plus 13 pure engine tests (hours, closed days, boundary spanning, past, notice/horizon, half-open overlap, durations, bounded listing, DST spring-forward 2026-03-08 and fall-back 2026-11-01, lifecycle), 44 API integration tests (availability, booking, double booking, idempotent retry and key collision, replayed failures, reschedule success/conflict/policy/authorization, cancel/repeat/policy, audit history, proposals: unconfirmed/wrong token/modified details/replay/expiry/rejection/cross-patient/cross-clinic/stale appointment, verification lockout and token expiry, tenant isolation, draft-vs-published semantics, stable type ids and frozen history, archived types), 16 reliability tests (concurrent bookings -> exactly one winner, concurrent identical retries -> one appointment and one operation, concurrent reschedules and cancel-vs-reschedule, injected faults before commit / in work / after commit, lost-response reconciliation, no leaked DB text, exclusion constraint, composite-FK cross-clinic rejection, check constraints, append-only trigger, per-clinic key uniqueness, snapshot immutability) and 2 migration tests on a scratch database (M1 rows survive 0003, downgrade to 0002 and re-upgrade, `alembic check` finds no model/migration drift).
- Concurrency tests repeated 17 times in a row without failure. One earlier first-run failure of `test_many_concurrent_bookings_never_overlap` (an assertion on response status codes) was **not reproduced** and its cause was not identified; its assertion now prints the offending responses if it recurs.
- Migrations: `alembic upgrade head` through 0003 on the dev database (additive).
- Frontend: `eslint`, `tsc`, `prettier --check` (src, e2e), `next build` pass. Playwright: **14 passed** (13 earlier + a test of the `/dev/scheduling` console: failed then successful verification, availability, propose, confirm, book, cancel).

### Not verified / limitations
- **GitHub Actions has not run for M2.** The workflow is unchanged (its PostgreSQL service user is a superuser, which `CREATE EXTENSION btree_gist` and the migration tests need); it has never run remotely.
- Docker Compose still never run.
- Verification is simulated (DOB + last four phone digits); no real identity proofing, no staff roles, M1 config endpoints remain unauthenticated.
- Single bookable resource per clinic (no providers/rooms). Slot step fixed at 15 minutes. No endpoint marks appointments `completed`. Cancel/reschedule apply the current published policy.
- Concurrency tested in a single API process against real PostgreSQL; no multi-process or load testing. Fault injection is a test seam, not real network failure.
- Clinics published under M1 (before type ids existed) must be republished before they can be scheduled.
- The seeded clinics stay drafts unless `python -m app.seed --publish` is used; the dev-console Playwright spec publishes Northstar and is named so it runs last.


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
- "Draft" is the live editable rows; publishing snapshots them into an immutable `config_versions` row. There is no separate draft table or per-field history.
- (Superseded in M2: appointment types now have stable ids; operating-hour rows are still replaced on save.)
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
