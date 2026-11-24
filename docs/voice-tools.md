# Voice tools

The LLM sees only the tools the clinic's configuration allows (`allowed_capabilities`, `supported_intents`). Schemas are generated from the same pydantic models that validate arguments. Every tool returns a result with a `status`; the agent may only describe an outcome that a result states.

| Tool | Purpose | Notes |
| --- | --- | --- |
| `get_clinic_information` | Hours, services, policies, location, contact from the frozen configuration. | Disabled when the clinic lacks the `clinic_information` intent. |
| `get_appointment_availability` | Open slots for an appointment type and date range. | Returns slots as `S1`, `S2`... references. At most three offered at once. |
| `verify_patient` | Simulated verification: name, date of birth, last four phone digits. | Wrong details never say which was wrong; five failures lock the caller out. |
| `get_patient_appointments` | The verified caller's scheduled appointments. | Returned as `A1`, `A2`... references. |
| `propose_booking` / `propose_reschedule` / `propose_cancellation` | Create a server-side proposal. | A new proposal supersedes and rejects the previous one. |
| `withdraw_pending_proposal` | Drop the pending proposal. | Changes nothing in the schedule. |
| `confirm_operation` | Execute the pending proposal. | Requires a final caller turn after the proposal, and `caller_words` must appear in that turn. |
| `get_operation_status` | Report the true state of the last change. | Used after an `uncertain` result. |
| `request_human_escalation` | Record a hand-off request for staff. | Not a transfer. Required for appointment types marked `requires_human_escalation`. |

## Result statuses

`ok`, `needs_input`, `committed`, `rejected`, `uncertain`, `error`. Only `committed` means a change happened. `rejected` means the backend refused it and nothing changed. `uncertain` means the outcome is not yet known.

## Safety rules enforced in code

- The LLM never invents ids: it passes `slot_ref` / `appointment_ref` values that earlier tool results handed out. Unknown refs are refused.
- Changes need verification first, then a proposal, then a caller yes captured in a later turn. Changing the type, time or appointment invalidates the proposal.
- Tool arguments are validated (`extra="forbid"`); invalid input returns a corrective result, never a crash.
- Scheduling goes through the M2 HTTP API only, with the same server-issued confirmation tokens and idempotency keys a human client would use.

## Unknown outcomes

Execution uses a deterministic idempotency key, `voice-{session8}-{proposal_id}`. On timeout, connection loss or a 5xx the tool looks the operation up by key (`GET /operations?idempotency_key=`):

- found `succeeded` -> `committed` (the stored outcome is reused, no second write);
- found `failed` -> `rejected`;
- no record, or `aborted` -> retry once with the **same key**;
- still unknown after bounded attempts -> `uncertain`; the agent says it is checking and calls `get_operation_status`.

Tests inject dropped requests, dropped responses and a backend that is down, and assert exactly one appointment results in every case.
