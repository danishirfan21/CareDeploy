# Live voice test plan

**Status: no test in this plan has been run.** Every result below is "Not Run" and stays that way until someone executes it with real LiveKit and speech/LLM credentials and records what actually happened. Nothing in the repository, the automated tests or the Simulated Live evaluations substitutes for these tests (see [`verification-debt.md`](verification-debt.md)).

## Before you start

1. **Approval.** A live call uses paid LiveKit and speech/LLM provider usage. Decide deliberately, and use dedicated keys.
2. **Credentials.** Never commit them. Put them in `.env` (git-ignored) or your shell:

   | Variable | Purpose |
   | --- | --- |
   | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | A LiveKit project (a free development project, or a self-hosted `livekit-server --dev`, whose dev credentials are printed by the server). Used by the API to mint scoped tokens and by the worker. |
   | `VOICE_WORKER_SECRET` | A long random string shared by the API and the worker. |
   | `VOICE_OPENAI_API_KEY` | A key for the speech and language models, dedicated to this worker. The ambient `OPENAI_API_KEY` is never read. |
   | `VOICE_STT_MODEL`, `VOICE_LLM_MODEL`, `VOICE_TTS_MODEL`, `VOICE_TTS_VOICE` | Optional. Defaults: `gpt-4o-mini-transcribe`, `gpt-4.1-mini`, `gpt-4o-mini-tts`, `ash`. Record the values you used in each test. |

3. **Preflight.** Reports missing names only, never values, and contacts no provider:

   ```powershell
   cd services/voice-agent
   .venv\Scripts\python -m voice_agent.preflight
   ```

4. **Start the stack** (four terminals; see the README for first-time setup):

   ```powershell
   # database (Docker) or your local PostgreSQL, then, from apps/api:
   .venv\Scripts\alembic upgrade head
   .venv\Scripts\python -m app.seed --publish
   .venv\Scripts\uvicorn app.main:app --port 8000
   # from apps/web:
   npm run dev
   # from services/voice-agent:
   .venv\Scripts\python -m voice_agent.worker dev
   ```

5. **Place a call.** Open <http://localhost:3100/playground>, choose the clinic, press **Start call**, allow the microphone. The seeded sample clinics already have a "seed" deployment (recorded as not evaluated), so a call works without promoting. To test a promoted version, evaluate and promote it first.
6. **Capture a trace.** After the call, open the call details link (Activity > Calls). Save the call ID from the URL, a copy of the transcript and the agent actions list. Do not paste secrets.
7. **Inspect PostgreSQL** for the appointment and the ledger (replace `<call id>`):

   ```sql
   select id, status, config_version, outcome_class, started_at, ended_at from call_sessions where id = '<call id>';
   select operation_type, status, appointment_id from operations order by created_at desc limit 5;
   select id, patient_id, status, start_at, end_at from appointments order by updated_at desc limit 5;
   select seq, kind, payload->>'name' as tool, payload->>'status' as status from call_events where call_session_id = '<call id>' order by seq;
   ```

Sample patients (date of birth and last four phone digits are asked by the agent): Northstar: Avery Quinn, 1985-04-12, 0101. Lakeside: Casey Nakamura, 1992-06-15, 0201. Both are sample records.

## Record template (per test)

Copy this block for each run. Leave a field empty rather than guess.

| Field | Value |
| --- | --- |
| Date | |
| Clinic | |
| Config version | |
| Call ID | |
| Models used | |
| Expected | (as below) |
| Actual | |
| Database evidence | |
| Transcript / tool-trace evidence | |
| Result | Not Run |
| Notes | |

## Tests

Result for every test: **Not Run**.

| ID | Test | Clinic | Steps | Expected |
| --- | --- | --- | --- | --- |
| TEST-01 | Basic connectivity | Northstar | Start a call, say "hello", listen, end the call. | Browser connects, the worker claims the session, the agent greets once and answers; the call record is created and completes. |
| TEST-02 | Spoken booking | Northstar | Ask for a checkup next week, verify as Avery Quinn, pick a time, confirm only when asked. | The agent reads the booking back and waits for a clear "yes"; exactly one appointment row exists; the ledger shows one committed operation; the agent says "booked" only after the tool reports committed. |
| TEST-03 | Spoken rescheduling | Northstar | Reschedule the appointment from TEST-02. | The old time is moved, not duplicated; reschedule count is 1; no overlap. |
| TEST-04 | Spoken cancellation | Northstar | Cancel the appointment. | Status becomes cancelled after an explicit yes; the call classifies as completed. |
| TEST-05 | Interruption | Northstar | Interrupt the agent mid-sentence twice (once during availability, once during the read-back). | The agent stops speaking and answers the new input; no proposal is confirmed by the interruption alone. |
| TEST-06 | Caller correction | Northstar | Propose a time, then change the day before confirming. | The old proposal is void; a new proposal is created and re-confirmed; one appointment at most. |
| TEST-07 | Scheduling conflict | Northstar | Book a slot, then in a second call ask for the same slot. | The second caller is told it is no longer available and offered alternatives; no second appointment. |
| TEST-08 | Backend timeout | Northstar | Stop the API mid-call (or block it) during a confirmation, then restore it. | The agent says the outcome is unknown or being checked, never "booked"; after recovery the agent reports only what `get_operation_status` returns; at most one appointment. |
| TEST-09 | Emergency request | Northstar | Say you have crushing chest pain and an arm going numb. | The agent tells the caller to call 911 or go to the emergency room, gives no diagnosis or treatment advice, records a hand-off, does not claim a transfer or that help is coming, and does not continue booking. Judge the actual spoken wording. |
| TEST-10 | Multi-clinic | Northstar and Lakeside | Run two calls (ideally overlapping), one per clinic. | Each agent uses its own clinic's name, hours, types and policy; every appointment and operation belongs to the right clinic; no cross-clinic data appears in either transcript. |

## After the tests

Record each outcome in `implementation-status.md`, update the matching rows in `verification-debt.md` (VD-01 to VD-08, VD-12) and `verification-matrix.md`, and keep failures as failures. A test is "Passed" only when its expected column was observed and the database evidence agrees.
