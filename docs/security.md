# Security review and posture

CareDeploy is an independent portfolio project run against sample data. It is **not** production software and makes **no HIPAA or other compliance claim**.

> **Do not deploy this system publicly with its admin endpoints exposed.** There is no user authentication, no roles and no approval workflow. Anyone who can reach the API can publish configurations, run evaluations, promote and roll back deployments and start voice sessions.

## What was reviewed (M6)

| Area | Finding | Handling |
| --- | --- | --- |
| Admin endpoints (`/api/clinics`, `/evaluations`, `/deployment`) | Unauthenticated by design (single local operator, actor `local-dev-operator`). | Documented. A startup tripwire (`APP_ENV=production` refuses to start unless `ALLOW_UNAUTHENTICATED_ADMIN=true`). This is a guard against accidents, not access control. |
| Patient-scoped scheduling endpoints | Require a server-issued, expiring token bound to one clinic and one patient; bodies cannot name another patient. Verified by tests and by evaluation scenarios EVAL-013 to EVAL-015, whose guards are mutation-tested. | Unchanged. Verification itself is simulated (date of birth plus last four phone digits). |
| Worker channel (`/api/voice/worker/*`) | Needs `X-Voice-Worker-Secret` (constant-time compare). Disabled with `503` when the secret is unset. | Unchanged. |
| Browser session tokens | Short-lived LiveKit JWT, room-scoped, microphone only, no admin or data grants, no API secret inside. | Unchanged (tested). |
| Deployment mutation | Server-side readiness, row lock, compare-and-swap, idempotency; request bodies accept no `force` or readiness fields. | Unchanged (tested). |
| Evaluation execution | Runs in per-run scratch databases that are dropped afterwards; no provider calls in workflow mode. Anyone with API access can start runs, which cost CPU only. | Documented. |
| Tool authorization | The agent's tools reach the backend only through the scheduling API with the caller's token; confirmation is bound to heard words and a server-side proposal. | Unchanged (mutation-tested). |
| Secrets | `.env*` is git-ignored except `.env.example` (placeholders). Only `VOICE_OPENAI_API_KEY` is read for the voice worker; the ambient `OPENAI_API_KEY` is never read. The preflight (`python -m voice_agent.preflight`) reports names only. | Secret scan before every commit (see verification matrix). |
| Logs | Request bodies are not logged; database errors log exception type and SQLSTATE only; call detail and event payloads are redacted. | Unchanged. |
| Test-only routes | There are no test-only backend routes. The browser transport swap needs `NEXT_PUBLIC_VOICE_TEST_TRANSPORT` at build time. | Documented. |
| `/dev/ui`, `/dev/scheduling` | Web pages for development. | **New:** they return 404 in a production build unless `NEXT_PUBLIC_ENABLE_DEV_PAGES=1` is set at build time. |
| CORS | Explicit origin list from `CORS_ORIGINS`. | **New:** `*` is refused at startup; a test checks that an unlisted origin gets no CORS header. |
| Database credentials | `caredeploy/caredeploy` is a local development default in `.env.example` and CI service containers only. | Change it for anything shared. |
| Debug information | Database errors return a generic `503`; no stack traces or SQL are returned. | Unchanged. |

## What is not provided

User authentication, authorization roles, audit of who did what (the actor is a constant), rate limiting, TLS termination, encryption at rest, retention policy and monitoring. If any of these matter, they have to be added before real use.
