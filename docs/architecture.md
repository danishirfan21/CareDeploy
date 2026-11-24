# Architecture

- **Frontend** `apps/web`: Next.js (App Router), TypeScript, Tailwind. Talks to the API over HTTP via `src/lib/api/client.ts`.
- **Backend** `apps/api`: FastAPI, async SQLAlchemy 2 (asyncpg). Alembic runs migrations over sync psycopg using the same `DATABASE_URL`.
- **Database**: PostgreSQL 17 (Docker Compose). Constraint naming convention set in `app/db/base.py`.
- **Contracts**: Pydantic schemas are the source of truth; TypeScript types mirrored manually (revisit codegen from OpenAPI when the surface grows).
- **UI direction**: minimal ChatGPT-inspired workspace (Home, Clinics + Wizard, Voice Playground, Evaluations, Activity). Not built yet.
- **Ports**: API 8000, web 3100, Postgres 5432.

## M1 data model
- `clinics`: details (name unique, specialty, location, timezone, contact).
- `operating_hours`, `appointment_types`, `scheduling_policies`, `agent_configs`: the editable **draft**; every row has `clinic_id` (FK, RESTRICT).
- `config_versions`: immutable published snapshots (JSONB) numbered per clinic. A PostgreSQL trigger rejects UPDATE and DELETE, so immutability does not depend on application code.
- Saving a draft (`PUT /api/clinics/{id}/config`) enforces structure (times, durations, uniqueness). `POST .../config/validate` adds publish-readiness rules (cross-field consistency). Publishing re-validates, refuses unchanged drafts (409) and writes the next version.
- Appointment types are replaced on each draft save (ids are not stable yet).

## Frontend
Client-rendered pages calling the API via `src/lib/api/client.ts`. `cacheComponents` is disabled. The UI is deliberately functional and unpolished until the Stitch screens are provided.
