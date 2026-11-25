# Deployments

A deployment selects which **published, immutable** configuration version new voice sessions use. It provisions nothing. The only environment is **Simulated Live**. It is a development concept inside CareDeploy and is not a real healthcare production deployment.

Four different things are kept apart:

| Concept | Meaning |
| --- | --- |
| Draft | The editable configuration. |
| Published version | An immutable numbered snapshot (M1). |
| Evaluated version | A version with workflow evaluation evidence (M4). |
| Active deployment | The version new calls use. One per clinic, set by promote or rollback. |

## Eligibility

Computed on the server for every promote, rollback and readiness request, from the M4 readiness engine. The request bodies accept no `force`, `ready` or readiness field (unknown fields are a 422). A version is eligible only when **all** hold:

1. It is a published version of this clinic (another clinic's version number is a 404).
2. The latest completed full-suite workflow run for that version passed every scenario in the mandatory suite.
3. No critical scenario failed.
4. The evidence was produced by the **current** scenario suite (suite hash matches).
5. The evidence is recent (default 30 days, `DEPLOYMENT_EVIDENCE_MAX_AGE_DAYS`). The 30 days is a demo assumption, not an industry requirement.
6. It is not already the active version.

For rollback the target must also have been deployed before. Rollback uses the same evidence rules, so an unsafe target (never deployed, no fresh evidence, older suite) is rejected.

Passing these checks means the **workflow simulation** passed. Real speech, turn-taking and a language model's tool choices remain unverified, and every assessment says so ("Real voice verification has not been completed"). See `verification-debt.md`.

## Concurrency and idempotency

- Every change takes a row lock on the clinic (`SELECT ... FOR UPDATE`). Changes for one clinic run one after another.
- Inside the lock the caller's `expected_active_version` is compared with the real active version (compare-and-swap). A mismatch is `409 concurrent_modification`, and nothing is written.
- Readiness is recalculated inside the lock, so evidence cannot go stale between the check and the write.
- A partial unique index allows only one `active` deployment per clinic and environment. If code were ever wrong, the database still refuses an ambiguous pointer, and an `IntegrityError` is returned as `409`.
- `idempotency_key` is scoped to the clinic. The same key with the same request returns the original result (`200`). The same key with a different request is `409 idempotency_conflict`. Without a key, promoting the already-active version is `409 already_active` and writes nothing.

## History is never deleted

`deployments` rows are written once. The only permitted change is the active → superseded flag, enforced by a trigger, and deletes are refused. `deployment_events` is append-only (update and delete are refused by a trigger). A rollback is a **new** deployment row (`action = rollback`, `restored_from_id` set) plus a new event. Each event stores the readiness evidence used for the decision.

## API

| Route | Purpose |
| --- | --- |
| `GET /api/clinics/{id}/deployment` | Active deployment and latest published version. |
| `GET /api/clinics/{id}/deployment/history` | Events, newest first. |
| `GET /api/clinics/{id}/deployment/events/{event_id}` | One event with its readiness evidence. |
| `GET /api/clinics/{id}/deployment/readiness?config_version=N&action=promote\|rollback` | Eligibility with each check. |
| `POST /api/clinics/{id}/deployment/promote` | `{config_version, expected_active_version, idempotency_key?}` |
| `POST /api/clinics/{id}/deployment/rollback` | `{target_version, expected_active_version, idempotency_key?}` |

Errors: `404` unknown clinic, version or event; `409` with codes `deployment_blocked`, `rollback_blocked` (includes the failing checks), `already_active`, `concurrent_modification`, `idempotency_conflict`; `422` malformed body.

## Voice runtime

`POST /api/clinics/{id}/voice/sessions` resolves the **active deployment**, never "the latest published version". With none it returns `409 no_active_deployment` with the message "evaluate a published version and promote it". A clinic with no published version at all keeps `409 clinic_not_configured`. The session stores `config_version` and `deployment_id`. The worker claim resolves by the session's stored version, so a call that started before a promotion or rollback keeps its original version.

## Sample data

The seed command and the test fixtures activate the sample clinics with `action = seed`, recorded honestly as "not evaluated". This path exists only in seed code. The API has no route that produces it.

## Limits

- Single operator; the actor is the constant `local-dev-operator`. There is no approval workflow and no authentication (M6).
- One environment. No scheduled or gradual rollout.
- Nothing here deploys to any external system.
