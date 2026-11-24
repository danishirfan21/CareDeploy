# Call operations

Activity → Calls is the operator's view of finished and in-progress calls for one clinic. Everything on it comes from persisted records (the call session, its events and the scheduling operation ledger). Nothing is inferred from the agent's wording.

## API

All routes are scoped by clinic in the path. A call that belongs to another clinic is reported as `404 call_not_found`, the same as a missing call.

| Route | Purpose |
| --- | --- |
| `GET /api/clinics/{id}/calls` | List. Filters: `outcome`, `date_from`, `date_to`, `q`; pagination: `limit` (1-100), `offset`. Newest first. |
| `GET /api/clinics/{id}/calls/{call_id}` | Detail: summary, transcript, agent actions, technical details. |
| `GET /api/clinics/{id}/call-metrics` | Aggregates for a date range (see `observability.md`). |

Routes avoid the `/operations/` prefix because it belongs to the scheduling ledger.

Search matches only safe metadata: the call id, scheduling operation ids, the stored call summary and the task type. It never searches transcripts or patient details. `%` and `_` are literal characters.

Date filters are inclusive local dates in the **clinic's time zone** and are applied to the call's creation time as `[start of the first day, start of the day after the last day)`. A call at 21:30 local time on 3 March is on 3 March even though it is 4 March in UTC.

## Outcome classification

The agent reports an `outcome` during a call. That is a claim. The classification stored on the call (`outcome_class`, `task_type`) is what the evidence supports. It is computed by the pure function in `app/ops/classify.py` when a call ends, and filled in lazily for older finished calls.

| Class | Meaning |
| --- | --- |
| completed | The supported task reached a verified result. A booking, reschedule or cancellation counts only when the operations ledger holds a `succeeded` operation of that type. An information-only call counts as completed. |
| escalated | The caller was handed to staff. Often correct behavior. It is **not** counted as a failure. |
| failed | The call ended in an error, or the ledger shows the requested change failed or was aborted. |
| abandoned | The caller left, or never joined, before any task finished. |
| interrupted | The connection was lost before the call could end. |
| unknown | The ledger cannot say whether a change committed (an operation is still `processing`), or the agent claimed a change the ledger does not show. Never treated as success. |

A call that has not ended has no class and is shown as "In progress". It is excluded from every rate.

The task type (booking, reschedule, cancellation, information) is shown only when the ledger or the agent-reported result identifies it. Otherwise the UI says "Unavailable".

## Call detail

Summary, Conversation, Agent actions and a collapsed Technical details section. Missing data is shown as "Unavailable"; transcripts are never reconstructed. Agent actions pair each tool's start and finish events and add a deterministic error category (for example "Scheduling conflict" or "Backend unavailable") from the tool status and code. No model produces explanations.

Troubleshooting path: call → failed action → error category → operation id and ledger status → configuration version, deployment and the latest workflow evaluation for that version. Each hop is a link.

## Redaction

Stored event payloads, the call detail and the technical section pass through `app/ops/redact.py`, which removes secrets, tokens, patient identifiers (date of birth, phone) and caps string and list sizes. Audio is never recorded.

## Limits

- One operator, no accounts (`local-dev-operator`).
- The call list is not real time; the page loads on open and when filters change.
- Counts and rates are over the persisted sample data, which is small. Small samples are flagged.
