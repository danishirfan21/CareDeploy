# Idempotency, retries and recovery (M2)

`POST /appointments`, `/appointments/{id}/reschedule` and `/appointments/{id}/cancel` require an
`Idempotency-Key` header (`[A-Za-z0-9._:-]{8,128}`), unique **per clinic**.

## Contract

| Situation | Result |
| --- | --- |
| First request | Executes; response carries `X-Operation-Id` and `Idempotent-Replay: false` |
| Same key, same request (retry) | Stored outcome replayed with the same status/body, `Idempotent-Replay: true`; no new side effects |
| Same key, different request | 409 `idempotency_conflict` |
| Same key while the first attempt is still running | Waits up to `IDEMPOTENCY_WAIT_SECONDS` (3), then 409 `operation_in_progress`; retry later |
| Previously failed with a business error (e.g. slot taken) | The same failure is replayed verbatim |

The *fingerprint* of a request is a SHA-256 of canonical JSON of `{operation, clinic_id, patient_id,
proposal_id, bound details}`; the `operations` table stores it with status
(`processing | succeeded | failed | aborted`), the stored outcome, the resulting appointment, and
timestamps.

## Protocol

1. **Claim** - `INSERT ... ON CONFLICT DO NOTHING` on `(clinic_id, idempotency_key)` in its own
   committed transaction. Exactly one concurrent caller wins; the rest observe the row.
2. **Work** - a second transaction locks the operation row `FOR UPDATE`, checks it is still ours,
   consumes the proposal, applies the change, and writes `succeeded` + the outcome **in the same
   transaction** as the appointment change. The response is built from committed data only; success
   is never reported before commit.
3. **Business failure** (policy, slot taken, mismatch...) - recorded as `failed` with the HTTP
   status and body, replayed on retry.
4. **Infrastructure failure** (database/OS error, timeout) - the work transaction rolls back, the
   operation is marked `aborted` (re-runnable) and the caller gets 503 `dependency_unavailable`.
   Retrying the same request re-executes it. A stale `processing`/`aborted` row can be taken over
   after `OPERATION_LEASE_SECONDS` (30).
5. **Unknown outcome** - if the failure happened around commit and the server cannot tell whether
   the work landed, it first tries to *reconcile* from the database; if that is also impossible it
   returns 503 `outcome_unknown`. It never claims success or failure it cannot prove.

## Client recovery guide

- Timeout / dropped connection / 503: **retry the identical request with the same key** (and the same
  `proposal_id`). That is always safe.
- To check without re-executing: `GET /operations?idempotency_key=...` (or `/operations/{id}` using
  `X-Operation-Id`). `status` is `succeeded`/`failed` (resolved; `outcome` holds the original
  response) or `processing`/`aborted` (not resolved yet, retry).
- Do not invent a new key for a retry of the same intent; do use a new key (and a new proposal) for a
  genuinely new request.

## How it is tested (real PostgreSQL)

Identical retry; key collision; replayed failure; operation lookup scoping; concurrent identical
retries (6 at once -> one appointment, one operation row); concurrent distinct bookings for one slot
(exactly one succeeds); concurrent reschedules and cancel-vs-reschedule races; injected faults at
`after_claim`, `in_work`, `before_commit`, `after_commit` via an overridable `Faults` dependency,
covering rollback, retry after interruption, a lost response after commit (reconciled by key, no
duplicate) and generic 503 bodies that leak no driver or SQL text.

## Limitations

Operation rows are kept indefinitely (no retention job). Fault injection is a test seam; no real
network partitions were simulated. Behaviour under multiple API processes relies on the same row
locks but was only exercised in a single process.
