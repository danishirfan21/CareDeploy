# Verification debt

Everything that has been built but **not** verified against the real thing. Nothing here is recorded as passed. An item moves to *Verified* only when the method below has been executed and the result recorded in `implementation-status.md`.

Statuses: **Open** (not attempted), **Blocked** (cannot be attempted without a missing dependency or approval), **Partial** (some evidence exists), **Verified**.

| ID | Item | Risk if wrong | Verification method | Status | Dependencies | Target |
| --- | --- | --- | --- | --- | --- | --- |
| VD-01 | LiveKit connectivity: worker registers and joins a room, browser and worker see each other | No call can start. The whole voice path is unproven end to end. | Run a LiveKit server (cloud project or self-hosted), start `voice_agent.worker`, start a call from the Playground, confirm the worker claims the session and the room has two participants. | Blocked | LiveKit URL, API key and secret; decision to run | Next live-verification pass |
| VD-02 | Browser microphone capture over the real transport | The caller cannot be heard, or permission handling fails on real browsers. | Real call in Chromium with a physical microphone; check permission prompt, mute, device change, denied permission. | Blocked | VD-01 | Next live-verification pass |
| VD-03 | Speech-to-text accuracy and endpointing | Mishearings (dates, names, "yes") create wrong proposals or false confirmations. | Spoken test calls with varied accents and noise; compare finalized transcript with what was said, especially confirmations. | Blocked | VD-01, speech provider credentials, spend approval | Next live-verification pass |
| VD-04 | LLM tool selection and phrasing | The model may skip a required step, confirm early, or invent availability. Mode A scripts these steps and cannot see this. | Mode B (LLM conversation evaluation) with a simulated caller; then live calls. | Blocked | Model credentials and explicit spend approval; a Mode B provider implementation (none exists yet) | Next live-verification pass |
| VD-05 | Text-to-speech output | Unintelligible, clipped or mispronounced speech (times, dates). | Listen to real calls; check dates and times read aloud. | Blocked | VD-01, TTS provider credentials | Next live-verification pass |
| VD-06 | Barge-in and turn-taking | The agent talks over the caller or ignores interruptions. | Interrupt the agent mid-sentence on a real call; observe the transcript and tool activity. | Blocked | VD-01 to VD-05 | Next live-verification pass |
| VD-07 | Real voice booking, reschedule and cancel | The tested HTTP and tool path may not match what a live call produces. | One real call each against the sample clinic; confirm the appointment rows, operation ledger and call record agree. | Blocked | VD-01 to VD-06 | Next live-verification pass |
| VD-08 | Live multi-clinic behavior | A call may use the wrong clinic's configuration under a real room and token flow. | Two concurrent calls to two sample clinics; check each call's instructions, tools and results belong to its clinic. | Blocked | VD-01 to VD-06 | Next live-verification pass |
| VD-09 | PostgreSQL concurrency response (M2 intermittent 503) | A rare 503 `dependency_unavailable` can appear under heavy concurrent booking. It is retry-safe, but the cause is unproven. | Repeat `test_many_concurrent_bookings_never_overlap` many times with SQLSTATE capture (see `implementation-status.md`), then confirm whether the database raised a deadlock, serialization failure or other error. | Partial | None | M4 follow-up |
| VD-10 | Remote GitHub Actions | The workflow has never run, so CI is untested. It may fail on a clean runner (services, paths, Playwright browsers, voice service). | Push to a remote and run the workflow; fix findings. | Open | A remote repository and a decision to push | When a remote exists |
| VD-11 | Docker Compose | Compose files have never been run (Docker is not installed on the development machine). | `docker compose up` on a machine with Docker; check API, web and Postgres 17. | Open | Docker | When Docker is available |
| VD-12 | Emergency guidance in agent instructions | The shared instructions mention symptoms and the escalation tool but do not tell the agent to direct a caller with a possible emergency to emergency services. EVAL-020 checks the hand-off and that nothing is scheduled, not the guidance. | Product and clinical review of the wording, a change to the shared instructions, then Mode B and live calls. | Open | Product decision | Before any real use |
| VD-13 | Real-audio evaluation runner (Mode C) | There is no automated end-to-end audio evaluation. | Design and build a runner that places real audio calls against the worker, with approved spend. | Open | VD-01 to VD-06 | After live verification |

## What is verified today

Workflow simulation (Mode A) of twenty scenarios against the real tool layer, the real scheduling API and PostgreSQL. See `implementation-status.md` for the executed commands and counts.

## How to retire an item

1. Run the method exactly as written, with the dependencies approved.
2. Record the date, what was run, and the observed result in `implementation-status.md`.
3. Change the status here. Do not delete rows; a verified item stays as a record.
