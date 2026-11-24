# Authorization and confirmation (M2)

> **Verification here is simulated.** Matching a date of birth and the last four digits
> of a phone number is *not* identity proofing and must not be used for real patients.
> It exists so the backend can enforce a server-issued, expiring, patient-bound authorization,
> which is the mechanism a real verification step would plug into.

## Server-issued authorization

1. `POST /patients/{id}/verify` with `{date_of_birth, phone_last4}`. The server compares in
   constant time. Clients can never assert "verified": request models forbid extra fields, and no
   endpoint accepts such a flag.
2. On success the server returns a random bearer token (stored only as a SHA-256 hash) bound to
   one clinic and one patient, valid for `AUTHORIZATION_TTL_MINUTES` (default 15).
3. Failures increment a counter; after `VERIFICATION_MAX_ATTEMPTS` (5) the patient is locked for
   `VERIFICATION_LOCKOUT_MINUTES` (10) and gets `429 verification_locked` even for correct input.

Every patient-scoped endpoint requires `Authorization: Bearer ...`:

| Situation | Result |
| --- | --- |
| Missing/unknown token | 401 `authentication_required` |
| Expired or revoked token | 401 `authorization_expired` |
| Token from another clinic | 403 `forbidden` |
| Token for another patient in the same clinic | 403 `forbidden` |

Clinic scoping is repeated in every query and, for appointments, by composite foreign keys.

## Confirmation: propose -> confirm -> execute

Booking, rescheduling and cancelling require an explicit, server-tracked confirmation.

1. `POST /proposals` `{action, ...details}` runs a **dry run of every rule** and stores the exact
   details plus a human-readable summary. The response includes a one-time
   `confirmation_token` (stored hashed; later reads never return it). Lifetime
   `PROPOSAL_TTL_MINUTES` (default 5).
2. `POST /proposals/{id}/confirm` with the token moves `pending -> confirmed`. A wrong token or a
   different patient is refused; an expired proposal returns 410 `operation_expired`. Confirming
   an already-confirmed proposal is idempotent. `POST /proposals/{id}/reject` ends it.
3. The execution request (`book`, `reschedule`, `cancel`) names the `proposal_id` **and repeats
   the details**; the server hashes them and compares with the confirmed details. Any difference
   is `409 proposal_mismatch`. A pending/rejected proposal gives `409 proposal_not_confirmed`.
4. Execution consumes the proposal (`executed`) in the same transaction as the effect, so a proposal
   can be used once: replays with a *new* idempotency key get `409 proposal_already_used`; replays
   with the *same* key return the stored outcome (see idempotency.md).
5. Reschedule/cancel proposals capture the appointment `row_version`; if it changed, execution
   fails with `409 appointment_modified` and nothing is applied.

State is recorded in `operation_proposals` (`pending, confirmed, executed, rejected`; "expired" is
derived from `expires_at`).

## What this does not provide

No real identity proofing, no MFA, no session management beyond the bearer token, no admin/staff
roles, no rate limiting beyond the per-patient lockout, and no audit of *read* access. Clinic
configuration endpoints (M1) remain unauthenticated, as before.
