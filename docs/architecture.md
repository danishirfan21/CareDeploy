# Architecture

- **Frontend** `apps/web`: Next.js (App Router), TypeScript, Tailwind. Talks to the API over HTTP via `src/lib/api/client.ts`.
- **Backend** `apps/api`: FastAPI, async SQLAlchemy 2 (asyncpg). Alembic runs migrations over sync psycopg using the same `DATABASE_URL`.
- **Database**: PostgreSQL 17 (Docker Compose). Constraint naming convention set in `app/db/base.py`.
- **Contracts**: Pydantic schemas are the source of truth; TypeScript types mirrored manually (revisit codegen from OpenAPI when the surface grows).
- **UI direction**: minimal ChatGPT-inspired workspace (Home, Clinics + Wizard, Voice Playground, Evaluations, Activity). Not built yet.
- **Ports**: API 8000, web 3100, Postgres 5432.
