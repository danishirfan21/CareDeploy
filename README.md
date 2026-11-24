# CareDeploy

Monorepo: `apps/web` (Next.js + TypeScript + Tailwind), `apps/api` (FastAPI + SQLAlchemy + Alembic), PostgreSQL via Docker Compose. See `docs/`.

## Prerequisites
Node 22+, Python 3.12+, Docker (Compose v2).

## Setup
```powershell
copy .env.example .env
docker compose up -d postgres

cd apps/api
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"      # Linux/macOS: .venv/bin/pip
.venv\Scripts\alembic upgrade head
.venv\Scripts\uvicorn app.main:app --port 8000 --reload

cd apps/web          # new terminal
npm install
npm run dev          # http://localhost:3100
```
Verify: `http://localhost:8000/api/health`, `/api/health/db`, and the home page shows `API: ok` / `Database: ok`.

Port 3100 is used for the web app to avoid clashing with other local apps on 3000.

## Checks
```powershell
cd apps/api; .venv\Scripts\ruff check .; .venv\Scripts\ruff format --check .; .venv\Scripts\mypy; .venv\Scripts\pytest
cd apps/web; npm run lint; npm run typecheck; npm run format:check; npm run build
cd apps/web; npx playwright install chromium; npm run test:e2e   # needs API + Postgres running
```
`pytest -m "not db"` skips tests that need Postgres.

## API conventions
Routes live under `/api`. Pydantic schemas in `apps/api/app/schemas.py` are mirrored by hand in `apps/web/src/lib/api/types.ts`; all calls go through `apps/web/src/lib/api/client.ts`.

## Design
Stitch exports go in `design/` (see `design/README.md`).
