# Implementation status

## M4 - Conversation evaluation engine (2026-11-24): COMPLETE for workflow simulation; LLM and real-audio modes NOT RUN

Twenty version-controlled scenarios (`evals/scenarios/`) drive the real voice-agent `Toolbox`, `SchedulingClient`, `build_instructions` and the real M2 scheduling API on PostgreSQL. Only Mode A (workflow simulation) exists as a runnable mode. Mode B (LLM conversation) is shown as Not run: no provider is implemented, and it needs `EVAL_LLM_API_KEY` plus `EVAL_LLM_APPROVED=true`; nothing was billed. Mode C (real audio) has no runner. Live voice verification from M3 is still outstanding (see `verification-debt.md`). Pass rates of different modes are never combined.

### Verified (actually executed)
- Backend: ruff, ruff format and strict mypy clean (70 files). pytest: 174 tests (97 + 28 earlier, plus 49 new: 21 unit, 10 runner, 17 API/worker, 1 migration), all passing. The full run took 17-24 minutes; one clean full run had two failures from a scratch-database check that saw another database's leftover (fixed by scoping the check) and the two tests then passed alone. The test-file edits after the last full run are the leftover-check scope and two `type: ignore` comments; neither was followed by a second complete 174-test run.
- Mutation tests show evaluation really drives shared code: weakening the toolbox confirmation rule turns EVAL-016 red; weakening the scheduling engine turns the integrity scenarios red.
- Voice service: 9 tests, ruff and mypy clean.
- Frontend: eslint, tsc, prettier and `next build` pass. Playwright: 39 tests, 38 passed in the full run, plus the one failing spec (a stale M3-era assertion in `navigation.spec.ts`) fixed and rerun with all 6 passing. `evaluations.spec.ts` runs the real worker against the published sandbox clinic, covering the empty state, unavailable modes, a category run with inspection and rerun, cancellation, the Activity tab and mobile overflow.
- Migration `0005_evaluations` is additive and reversible (checked by `test_migrations.py`); 0001-0004 are untouched.

### Not verified
- Mode B and Mode C were never run. Real LiveKit, STT, TTS, barge-in and live booking remain open (`verification-debt.md`, VD-01 to VD-08).
- GitHub Actions and Docker Compose have never run.
- Emergency guidance in the shared agent instructions is a documented gap (VD-12), not changed here.

### Investigations
- **M2 concurrency 503:** SQLSTATE logging (exception class and code only, no data) was added to the scheduling infrastructure-failure path. The cause is still unproven; no repeated-run reproduction was done in this milestone (VD-09, Partial).
- **Backend suite duration:** the pre-M4 suite was about 9 minutes. The M4 tests dominate the increase because every scenario clones a database from a per-run template that must be migrated first (full suite about 130 s, single scenario about 100 s under load). No refactor was made; running the suite alongside Playwright or mypy roughly doubles it.
- A stopped Playwright run left one scratch evaluation database; it was removed by name pattern. Do not run two pytest sessions against the same test database at once.

### Limitations
Single operator, no authentication. Passing Mode A says nothing about model behavior, speech, clinical safety or compliance. Not HIPAA compliant.

## M3 - Real-time voice agent (2026-11-24): PARTIALLY COMPLETE, live voice verification blocked

No LiveKit or speech-provider credentials were available, and spending the ambient OpenAI key was not approved, so a real call was never made. Everything around the audio path is built and tested.

### Verified (actually executed)
- Backend: ruff, ruff format, strict mypy clean. pytest: 97 earlier tests plus 28 new (11 voice session API tests, 17 tool-layer integration tests against the real M2 API and PostgreSQL, including dropped request, dropped response and backend-down recovery with exactly one appointment, clinic isolation and capability gating).
- Voice service: 9 unit tests (state machines, instruction building for two configurations, no clinic-name branching, event dedupe and redaction), ruff and mypy clean. `voice_agent.worker` imports with livekit-agents 1.8.13.
- Frontend: eslint, tsc, prettier, `next build` pass. Playwright: 33 passed. New `voice.spec.ts` (7 tests) uses a controlled no-audio transport and drives the real worker channel: full call with transcript, interim text, tool activity, confirmation state, end, outcome and call details; not-configured state; microphone denied; connection failure; mid-call connection loss; mute and keyboard; mobile overflow.
- Order dependency removed: the scheduling console spec now uses a pre-published `Sandbox Family Clinic` (`--sandbox` seed for e2e only) and is renamed `scheduling-dev.spec.ts`.
- Migration `0004_voice_sessions` (additive; `call_sessions`, `call_events`).

### Not verified
- Real LiveKit join, audio, STT/LLM/TTS, barge-in and latency. `worker.py` and `providers.py` are written against the SDK but have never run against a server.
- `livekit-client` adapter has never connected to a real room.
- GitHub Actions and Docker Compose still never run (voice service is not yet in the workflow).

### Intermittent M2 concurrency failure: investigated
`test_many_concurrent_bookings_never_overlap` failed once in about 50 repeated runs. The failing response body was the 503 `dependency_unavailable` message ("Nothing was changed; retry with the same key"), not a 201/409. Probable cause (not proven; the SQLSTATE was not captured): concurrent inserts racing on the exclusion constraint can make PostgreSQL abort one transaction with a deadlock or serialization error, which M2 maps to a retryable 503 rather than `slot_unavailable`. This is safe (nothing changes and a retry with the same key works) but the test asserts only 201/409. M2 logic was not changed; left open.

### Limitations
Browser microphone only, no telephony. Simulated verification; not HIPAA compliant. Escalation records a request, it does not transfer. Browser follows the call by polling. Activity has no call list yet.

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
