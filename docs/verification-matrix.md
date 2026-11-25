# Verification matrix

What has actually been verified, by what, and what has not. Statuses are **Passed**, **Failed**, **Blocked** (cannot run here) and **Not Run**. A blocked or unrun item is never upgraded by inference: passing simulated tests does not verify live speech.

Date of last update: 2026-11-25. Evidence references are test files or documents in this repository.

| Category | Status | Evidence | Notes |
| --- | --- | --- | --- |
| Backend logic (scheduling, policy, idempotency, tenancy) | Passed | `apps/api/tests/` (full suite recorded in `implementation-status.md`) | Includes contention test for the VD-09 deadlock fix. |
| Database (migrations, constraints, append-only history) | Passed | `tests/test_migrations.py`, `tests/test_lifecycle.py` | Local PostgreSQL 17 only; hosted databases not tested. |
| Frontend (lint, types, format, build, component behavior) | Passed | `npm run lint/typecheck/format:check/build` | Results in `implementation-status.md`. |
| Browser end to end (Playwright) | Passed | `apps/web/e2e/` | Chromium on one machine; not run in CI. |
| Scheduling under concurrency | Passed | `tests/test_scheduling_reliability.py` | A regression guard, not a proof of no other rare failure. |
| Evaluations (20 scenarios, mutation tests) | Passed | `tests/test_evals_runner.py`, `evals/scenarios/` | Workflow simulation only. No model-driven (Mode B) run. Cancellation-window policy has no scenario. |
| Deployment controls (readiness, promote, rollback, history) | Passed | `tests/test_deployments.py`, `tests/test_lifecycle.py` | Promotion moves an internal pointer; nothing is deployed externally. |
| Voice transport (token, session, worker channel, events) | Passed | `tests/test_voice_sessions.py`, `services/voice-agent/tests/` | No audio, no LiveKit server. |
| Speech recognition | Not Run | `live-voice-test-plan.md` TEST-02 | Needs credentials. |
| Speech synthesis | Not Run | `live-voice-test-plan.md` TEST-03 | Needs credentials. |
| Agent reasoning (real LLM) | Not Run | `live-voice-test-plan.md` TEST-04..06 | Instructions are unit-tested for content only. |
| Interruption (barge-in) | Not Run | `live-voice-test-plan.md` TEST-07 | Synthetic playback would not verify acoustic barge-in. |
| Multi-clinic voice | Not Run | `live-voice-test-plan.md` TEST-08 | Multi-clinic scheduling and config isolation are tested without voice. |
| Emergency guidance (VD-12) | Partial | `services/voice-agent/tests/test_instructions.py`, EVAL-020 | Instruction content and tool restrictions verified; the model's behavior is not. |
| CI | Not Run | `.github/workflows/ci.yml` | Written and reviewed; never run on GitHub. |
| Docker Compose | Not Run | `docker-compose.yml` | Statically reviewed; Docker is unavailable on the development machine. |
| Clean setup on a fresh machine | Not Run | `README.md` | Commands follow the same steps used locally; not replayed on a clean host. |
