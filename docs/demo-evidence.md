# Demo evidence

Only results that were actually produced, with date, command and limits. No recordings, traces or call logs are included because none exist from a live call. Nothing here is a commercial or accuracy metric.

Machine: one Windows 10 development machine, local PostgreSQL 17 (port 5433). Date: 2026-11-25.

| Evidence | Result | Command | Limits |
| --- | --- | --- | --- |
| Backend tests | 239 passed in 35 min 08 s | `pytest -q` (apps/api) | Sequential, one machine, local PostgreSQL. |
| Voice service tests | 27 passed | `pytest -q` (services/voice-agent) | No audio, no providers. |
| Browser end to end | 45 passed in 6.6 min | `npm run test:e2e` (apps/web) | Chromium only. Includes viewport capture runs. |
| Backend lint and types | ruff check and format clean; strict mypy clean (81 files) | `ruff`, `mypy` | |
| Frontend | eslint, tsc, prettier clean; production build succeeds | `npm run lint/typecheck/format:check/build` | |
| Evaluation workflow simulation | 20 of 20 scenarios passed for each sample clinic in the recorded UI run (before EVAL-021 was added); EVAL-021 has passed in the automated suite but has not been re-run through the UI for both clinics | Evaluations page, "Run evaluation" | Deterministic workflow only; LLM and real-audio modes Not run. |
| Contention fix | 1 failure in 15 runs before; 30 of 30 passes after | see `concurrency-investigation.md` | Probabilistic regression guard. |
| Evaluator can fail | Five mutation tests each break the code and require a red scenario | `tests/test_evals_runner.py` | One known gap: cancellation window (VD-20). |
| Screenshots | `docs/images/` | Playwright against the running dev stack | Development build, sample data. |
| CI | All six jobs passed on GitHub for commit 8111064 after one fixed failure | GitHub Actions | Does not include live voice. |
| Secret scan | No key patterns in tracked files | `git ls-files` + pattern search | Pattern-based, not exhaustive. |

## Not available

Live voice calls, speech accuracy, interruption behavior, model-driven evaluation results, Docker Compose results, and any cost figures. See [`verification-matrix.md`](verification-matrix.md).
