# Investigation: intermittent 503 under concurrent booking (VD-09)

## Symptom

During M2 a rare `503 dependency_unavailable` appeared under concurrent booking. The response is retry-safe by design (the operation is marked `aborted` and the same idempotency key can be retried), but the cause was not known. The error path already logged exception class and SQLSTATE only (no data).

## What was reviewed

- Transaction boundaries in `app/scheduling/idempotency.py`: claim (own transaction), work (one transaction: lock the operation row, consume the proposal, write the appointment and its event, mark the operation succeeded), finish/reconcile (separate transactions).
- The exclusion constraint on `appointments` (no two `scheduled` rows of a clinic may overlap), idempotency ledger, proposal row lock, appointment row lock.
- Error classification: `INFRASTRUCTURE_ERRORS = (DBAPIError, OSError)` all become `503`.

## Reproduction

Controlled and measurable, not assumed:

1. Repeating the existing nine-writer test 25 times (100 concurrent test executions): no 503, no infrastructure warning. The cause was not triggered at that concurrency.
2. A new test, `test_heavy_contention_has_no_infrastructure_failures`, runs 48 concurrent bookings (more writers than pool connections) over three overlapping slots with warning logs captured. It fails on any status other than 201/409 and on any logged infrastructure failure, and prints the diagnostics.
3. Repeating that test 15 times against the unfixed code: **1 failure in 15**. The failing run returned `503` and logged `DBAPIError ... sqlstate=40P01` repeatedly. Other runs of the same test took 9 to 13 seconds instead of about 5, consistent with PostgreSQL waiting out `deadlock_timeout` (default 1 s) before resolving a deadlock.

## Root cause

`40P01` is `deadlock_detected`. Two transactions that insert **overlapping, not identical** time ranges each insert their heap and index entry first and then check the exclusion constraint, which makes each wait for the other's uncommitted row. Neither can proceed, so PostgreSQL aborts one after `deadlock_timeout`. The abort surfaced as a `DBAPIError`, which the idempotency layer correctly mapped to `503 dependency_unavailable`.

It was not a serialization failure (`40001`), a lock timeout (`55P03`), a connection failure (`08xxx`) or an exclusion conflict (`23P01`, which is mapped to `409 slot_unavailable`). Only `40P01` was observed; the other classes are distinguished by SQLSTATE in the log line but were not seen.

## Fix

`lock_schedule()` in `app/scheduling/service.py` takes a transaction-scoped advisory lock keyed on the clinic (`pg_advisory_xact_lock`) at the start of `book` and `reschedule`, before any appointment row is read or written. Writers that add or move a time range within one clinic now queue instead of deadlocking.

Not weakened: the exclusion constraint remains the authoritative backstop; idempotency keys, proposal confirmation, authorization and atomicity are unchanged; the lock is released with the transaction, so a crash cannot leave it held. `cancel` does not take the lock (it frees time, never claims it). Retries still use the same idempotency key.

Trade-off: bookings for **one clinic** are serialized through a short critical section. Other clinics are unaffected. This is appropriate at the scale this project targets and would need revisiting only for very high booking rates per clinic.

## Evidence

- Before: 1 failure in 15 runs of the contention test (`40P01`).
- After: 30 of 30 passes; runtime back to about 5 s per run.
- The scheduling, tool, proposal and appointment tests pass (97 tests). The full suite result is recorded in `implementation-status.md`.

## Remaining uncertainty

- The reproduction proves one concrete deadlock path and removes it. It cannot prove there is no other rare infrastructure failure; any recurrence will log its SQLSTATE and be classified rather than guessed.
- The tests ran against one local PostgreSQL 17 instance on one machine, not a hosted database.
- The failure is probabilistic, so the new test can in principle pass without the fix; it is a regression guard, not a proof.
