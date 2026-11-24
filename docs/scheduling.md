# Scheduling (M2)

A PostgreSQL-backed scheduling engine for the sample clinics. It is a **simulated EHR**: nothing
here integrates with, or claims to integrate with, Epic, Cerner or any real system, and all
patients are sample records. The voice agent (M3) is not built; M2 provides the backend it will call.

## Domain assumptions

- **One bookable resource per clinic.** There are no providers, rooms or equipment. Two active
  appointments in the same clinic may never overlap. This is a deliberate simplification, enforced
  by the database (see Concurrency).
- **Published configuration only.** Scheduling reads the *latest published* `config_versions`
  snapshot (hours, time zone, appointment types, policy). Unpublished draft edits never affect
  availability or booking. An unpublished clinic answers `409 clinic_not_configured`.
- **Time:** instants are stored as UTC `timestamptz`; the clinic IANA zone only decides what a
  "day" and "opening hours" mean. API datetimes must carry an offset (naive values are rejected).
- **Intervals are half-open `[start, end)`**; back-to-back appointments are allowed.
- **Slot grid:** starts every 15 minutes (`SLOT_STEP_MINUTES`, a code constant, not configurable),
  anchored at the clinic's opening time that day. Appointment length is the type's duration.

## Time-zone and DST handling

An operating day is converted to a UTC window with the clinic's zone:

- Spring forward (nonexistent local times) - the day's real length shrinks; no slot starts in the
  skipped hour. Tested for America/Chicago 2026-03-08.
- Fall back (ambiguous local times) - both occurrences of the repeated hour are offered as
  distinct instants; a booking request is an unambiguous UTC instant, so there is no guessing.
  Tested for 2026-11-01.
- A slot must start and end inside the same day's operating window (an appointment that would
  cross closing time is rejected, even by one minute).

Policy rules are checked in a fixed order and reported as `policy_violation` with `details.rule`:
`appointment_in_past`, `closed_day`, `outside_operating_hours`, `invalid_slot_start`,
`same_day_not_allowed`, `minimum_notice`, `max_advance`; for existing appointments also
`cancellation_window`, `reschedule_window`, `max_reschedules`; for types needing a human,
`human_escalation_required` (availability returns no slots for them, booking is refused).

## Availability

`GET /api/clinics/{id}/availability?appointment_type_id&date_from[&date_to&limit]` - range capped at
14 days, `limit` (default 200, max 500) with a `truncated` flag. **Slots are informational**:
every booking re-validates all rules and the overlap constraint inside its own transaction.

## Lifecycle

`scheduled -> completed | cancelled`. `cancelled` and `completed` are terminal. Cancelling is soft
(the row stays, with `cancelled_at`, `cancellation_reason`). Repeating a *new* cancel request for an
already-cancelled appointment returns `409 invalid_state_transition`; retrying the *same* request
(same idempotency key) replays the original success. No endpoint marks appointments `completed`
yet (the transition is defined and unit-tested; the trigger would be a future clinic-side workflow).
Every change appends an `appointment_events` row (booked/rescheduled/cancelled, actor patient,
operation id, config version, details). The table is append-only (trigger rejects UPDATE/DELETE).

Reschedule moves the **same** appointment row in place, atomically: on any failure the original is
untouched. Cancel and reschedule apply the *current published* policy windows (not those at booking
time) and use the appointment's frozen duration.

## Stable appointment-type identity and historical facts

M1 replaced appointment-type rows on every save, so ids were unstable. Now:

- `appointment_types.id` is the stable identity. `GET/PUT config` round-trips an optional `id` per
  type; saving upserts by id. Renaming or changing a duration keeps the id. A type removed from the
  config is **archived** (`archived_at`), never deleted; unknown ids are rejected (422).
- Name uniqueness applies only among active types, so a name can be reused after archiving.
- Published snapshots contain the type ids. Legacy M1 snapshots lack them: scheduling reports
  `clinic_not_configured` until the clinic is republished (publish is allowed even if content is
  otherwise unchanged in that case). Existing M1 configs remain valid.
- An appointment stores a foreign key to its type **and** a frozen copy: `type_name`,
  `duration_minutes`, `timezone`, `config_version`. Later edits, renames, archiving or republishing
  never change an existing appointment's name, duration or end time (tested).

## Concurrency

`appointments` has `EXCLUDE USING gist (clinic_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
WHERE (status = 'scheduled')` (needs `btree_gist`, created by migration 0003). Two transactions
racing for overlapping times cannot both commit; the loser gets `409 slot_unavailable`. Application
checks are an optimisation, the constraint is the guarantee. Composite foreign keys
`(clinic_id, id)` make cross-clinic references impossible in the database. Reschedule/cancel use
the appointment `row_version`: if it changed between proposal and execution the request fails with
`409 appointment_modified`.

## API

All under `/api/clinics/{clinic_id}`; scheduling errors use `{"error": {"code", "message", "details?"}}`.

| Method & path | Purpose |
| --- | --- |
| `GET /patients?name\|phone` | Patient lookup (id + name only) |
| `POST /patients/{id}/verify` | Simulated verification; returns expiring bearer token |
| `GET /scheduling` | Published timezone, version, schedulable types |
| `GET /availability` | Open slots |
| `GET /patients/{id}/appointments` | Patient's appointments (`include_cancelled`) |
| `GET /appointments/{id}/events` | Audit trail |
| `POST /proposals`, `GET /proposals/{id}`, `POST /proposals/{id}/confirm`, `POST /proposals/{id}/reject` | Confirmation (see authorization.md) |
| `POST /appointments` | Book (201) |
| `POST /appointments/{id}/reschedule`, `POST /appointments/{id}/cancel` | Change |
| `GET /operations?idempotency_key=` and `GET /operations/{id}` | Reconcile an operation |

Error codes: `invalid_input` 422, `authentication_required` 401, `authorization_expired` 401,
`forbidden` 403, `verification_failed` 403, `verification_locked` 429, `not_found` 404,
`clinic_not_configured` 409, `policy_violation` 422, `slot_unavailable` 409,
`invalid_state_transition` 409, `appointment_modified` 409, `idempotency_conflict` 409,
`operation_in_progress` 409, `operation_expired` 410, `proposal_mismatch` 409,
`proposal_not_confirmed` 409, `proposal_already_used` 409, `dependency_unavailable` 503,
`outcome_unknown` 503. Clients never receive stack traces, SQL or driver messages. M1 endpoints keep
their original `{"detail": ...}` shape.

## Adapter boundary (for M3)

`app/scheduling/adapter.py` defines the `SchedulingAdapter` Protocol: `get_availability`,
`get_patient_appointments`, `propose_operation` / `confirm_proposal` / `reject_proposal`,
`book_appointment`, `reschedule_appointment`, `cancel_appointment`, `get_operation`. Every call takes
an explicit clinic id and a `Caller` (bearer token) or `OperationContext` (+ idempotency key). The
only implementation is `PostgresSchedulingAdapter`; the HTTP routes are thin wrappers over it.

A real EHR adapter would implement the same Protocol: translate availability and booking to the
vendor's API, map the idempotency key to whatever the vendor supports (or keep the `operations`
table locally as the source of truth for retries), and treat "unknown outcome" as first-class. None
of that exists here.

## Local development

`python -m app.seed --publish` seeds and publishes both clinics plus six sample patients. The
development console at `/dev/scheduling` (not linked from navigation; development/test only, not a
patient portal) walks verify -> availability -> propose -> confirm -> book -> cancel.

## Limitations

- Single resource per clinic; no providers, rooms, double-booking by design, waitlists or recurring
  appointments. Slot step is a constant. No `completed` endpoint. No notifications.
- Cancel/reschedule use the *current* published policy, not the policy at booking time.
- Clock comes from the server (`get_clock`); tests substitute a fake clock.
- Concurrency tests run in one process against real PostgreSQL; multi-process behaviour relies on
  the same row locks and the exclusion constraint but was not load-tested.
