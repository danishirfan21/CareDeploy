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
Seed the two fictional clinics (idempotent): `cd apps/api; .venv\Scripts\python -m app.seed`.

Verify: `http://localhost:8000/api/health`, `/api/health/db`, API docs at `http://localhost:8000/docs`, and the Clinics page lists Northstar Family Medicine and Lakeside Dermatology.

Port 3100 is used for the web app to avoid clashing with other local apps on 3000.

## Without Docker (Windows, local Postgres binaries)
```powershell
$b="D:\Postgresqlin"   # your Postgres bin dir
"caredeploy" | Set-Content $env:TEMP\pw.txt
& "$b\initdb.exe" -D .pgdata -U caredeploy --pwfile=$env:TEMP\pw.txt --auth=scram-sha-256
Start-Process "$b\pg_ctl.exe" "-D .pgdata -o `"-p 5433`" -l .pgdata\server.log start" -NoNewWindow
$env:PGPASSWORD="caredeploy"; & "$b\createdb.exe" -h localhost -p 5433 -U caredeploy caredeploy
# .env: DATABASE_URL=postgresql+asyncpg://caredeploy:caredeploy@localhost:5433/caredeploy
```

## Checks
```powershell
cd apps/api; .venv\Scripts\ruff check .; .venv\Scripts\ruff format --check .; .venv\Scripts\mypy; .venv\Scripts\pytest
cd apps/web; npm run lint; npm run typecheck; npm run format:check; npm run build
cd apps/web; npx playwright install chromium; npm run test:e2e   # needs API + Postgres running
```
Backend tests run against a real PostgreSQL database named `<dev db>_test` (dropped, recreated and migrated each run). Playwright starts its own API (:8001), web app (:3101) and database `caredeploy_e2e`, so the development database is never modified by tests. Ports 8001/3101 must be free.

## API conventions
Routes live under `/api`. Pydantic schemas in `apps/api/app/schemas.py` are mirrored by hand in `apps/web/src/lib/api/types.ts`; all calls go through `apps/web/src/lib/api/client.ts`.

## Design
Stitch exports go in `design/` (see `design/README.md`).
