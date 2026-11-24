# Voice session lifecycle

## Call session status

`created` -> `active` -> `completed` | `failed`, or `created` -> `abandoned` | `failed`.

| Event | Result |
| --- | --- |
| Browser `POST /api/clinics/{id}/voice/sessions` | `created`. 503 `voice_not_configured` (lists the missing variables) if LiveKit settings are absent; 409 `clinic_not_configured` if the clinic has no published version; 404 for an unknown clinic. |
| Worker claim | `active`, `started_at` set. One claim per session. |
| Browser end before the worker claimed | `abandoned`, or `failed` with `error=connection_failed`. `microphone_denied` records `abandoned` with that error. |
| Browser end while active | `completed`, `ended_by=browser`. The worker may still add its outcome. |
| Worker complete | Outcome, summary, operation ids, metrics and usage stored; secrets scrubbed. |
| Session not claimed within the token lifetime | `abandoned` on the next claim attempt (`session_expired`). |

## Three separate state models

These are deliberately independent, so a lost audio connection never silently cancels or commits a scheduling change.

- **Transport:** `connecting`, `connected`, `reconnecting`, `disconnected`, `failed`.
- **Conversation:** `connecting`, `ready`, `listening`, `thinking`, `speaking`, `waiting_for_clarification`, `waiting_for_verification`, `awaiting_confirmation`, `executing_tool`, `recovering`, `escalated`, `completed`, `disconnected`. The overlay phases (verification, confirmation, executing, escalated, recovering) are not overwritten by listening/thinking/speaking flips.
- **Operation:** `none`, `availability_shown`, `verified`, `proposed`, `confirmed`, `executing`, `committed`, `rejected`, `unknown`, `invalidated`.

Illegal transitions raise `InvalidTransition` (see `voice_agent/states.py`). A transport disconnect does not touch the operation state: an operation that was executing stays `executing` or becomes `unknown` and is reconciled by its idempotency key.

## Event flow

1. The worker records events locally with a monotonically increasing `seq` and a stable `event_id`, and flushes them in batches with retry.
2. The backend stores them with `UNIQUE(call_session_id, event_id)` and `ON CONFLICT DO NOTHING`, so retries are harmless. Order is by `seq`.
3. Only finalized speech becomes a transcript event. Interim caller text travels in `live_state.interim_user` and is never stored as an event. An interrupted agent turn is stored with the text actually spoken and `interrupted=true`.
4. The browser polls `GET /api/voice/sessions/{id}` (state) and `.../events?after_seq=` (log).

## Failure handling

| Failure | Behavior |
| --- | --- |
| Microphone denied | Call ends, clear message, session `abandoned` (`microphone_denied`). |
| Cannot connect to LiveKit | Session `failed` (`connection_failed`), retry available. |
| No worker picks up within 30 s | Browser ends the call and says the agent did not join. |
| Browser connection lost mid-call | Call is ended and the message says so. Confirmed changes remain in the call details. |
| Worker loses the browser | Worker records `operator_disconnected` and finishes the call. |
| Provider error | Recorded as an `error` event; the conversation moves to `recovering` if recoverable, otherwise the call fails with a reason. |
| Backend unreachable for events | Events stay queued and are retried; the call outcome records `event_flush_failures`. |
| Scheduling timeout or 5xx during a change | Treated as unknown, reconciled with the same idempotency key. See [voice-tools.md](voice-tools.md). |
