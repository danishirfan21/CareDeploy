# Architecture

- **Frontend** `apps/web`: Next.js (App Router), TypeScript, Tailwind. Talks to the API over HTTP via `src/lib/api/client.ts`.
- **Backend** `apps/api`: FastAPI, async SQLAlchemy 2 (asyncpg). Alembic runs migrations over sync psycopg using the same `DATABASE_URL`.
- **Database**: PostgreSQL 17 (Docker Compose). Constraint naming convention set in `app/db/base.py`.
- **Contracts**: Pydantic schemas are the source of truth; TypeScript types mirrored manually (revisit codegen from OpenAPI when the surface grows).
- **UI**: Stitch-based workspace (Home, Clinics + Wizard, Playground, Evaluations, Activity). See `ui-architecture.md`.
- **Voice worker** `services/voice-agent`: LiveKit Agents worker (Python). See the M3 section and `voice-agent.md`.
- **Ports**: API 8000, web 3100, Postgres 5432.

## M1 data model
- `clinics`: details (name unique, specialty, location, timezone, contact).
- `operating_hours`, `appointment_types`, `scheduling_policies`, `agent_configs`: the editable **draft**; every row has `clinic_id` (FK, RESTRICT).
- `config_versions`: immutable published snapshots (JSONB) numbered per clinic. A PostgreSQL trigger rejects UPDATE and DELETE, so immutability does not depend on application code.
- Saving a draft (`PUT /api/clinics/{id}/config`) enforces structure (times, durations, uniqueness). `POST .../config/validate` adds publish-readiness rules (cross-field consistency). Publishing re-validates, refuses unchanged drafts (409) and writes the next version.
- Appointment types have stable ids (M2): saves upsert by id and archive removed types instead of deleting them. See `docs/scheduling.md`.

## M2 scheduling engine
- `app/scheduling/`: `engine.py` (pure rules: time zones, DST, slots, overlap, lifecycle), `published.py` (reads the latest published snapshot), `auth.py` (simulated verification, expiring server-issued tokens), `service.py` (availability, proposals, book/reschedule/cancel), `idempotency.py` (claim/work protocol, recovery), `adapter.py` (typed `SchedulingAdapter` Protocol + the single PostgreSQL implementation), `runtime.py` (injectable clock and fault points for tests).
- `app/api/scheduling.py` exposes it under `/api/clinics/{id}/...` with a distinct error envelope.
- Double-booking is prevented by a PostgreSQL exclusion constraint, not by application checks. State changes go through a confirmed proposal and an idempotency key.
- Details: `docs/scheduling.md`, `docs/authorization.md`, `docs/idempotency.md`, `docs/data-model.md`. The voice agent (M3) calls the same HTTP API.

## Frontend
Client-rendered pages calling the API via `src/lib/api/client.ts`. `cacheComponents` is disabled. The UI follows the Stitch exports; see `ui-architecture.md`. `/dev/scheduling` is a development/test console for the scheduling API (not in the navigation, not a patient portal).

## M3 voice agent
- `call_sessions` / `call_events` (migration 0004) record each call: clinic, config version, actor, timestamps, finalized transcript, tool events, operation ids and outcome. No audio.
- `app/api/voice.py`: browser routes create a session and a scoped LiveKit token; worker routes (shared-secret header) claim the session, post events and state, and complete it. The worker receives the frozen published configuration from the claim, never from room metadata.
- `services/voice-agent`: provider boundary, state machines (transport, conversation, operation), tool layer over the M2 HTTP API with idempotent reconciliation, and the only LiveKit-aware module (`worker.py`).
- `apps/web/src/lib/voice`: `VoiceTransport` (LiveKit adapter and a controlled test adapter), call hook, event folding.
- Details: `voice-agent.md`, `voice-session-lifecycle.md`, `voice-tools.md`.

## M4 evaluation engine
- `app/evals/`: strict scenario schema and loader, isolated fixtures (database per scenario cloned from a per-run template), a driver that runs scenarios through the voice-agent `Toolbox`, `SchedulingClient` and the in-process M2 API, a deterministic assertion engine, the runner, and analysis (readiness, regression comparison).
- `app/api/evals.py` and `app/schemas/evals.py`: typed routes under `/api/clinics/{id}/evaluations/...`; runs execute in a separate worker process (`python -m app.evals.worker`).
- Migration `0005_evaluations`: `eval_runs`, `eval_scenario_results`, `eval_events`, immutable once a run is terminal.
- Scenarios are JSON files in `evals/scenarios/`. Details: `evaluations.md`, `evaluation-scenarios.md`, `deployment-readiness.md`, `verification-debt.md`.
