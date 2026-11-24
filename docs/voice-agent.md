# Voice agent (M3)

A LiveKit-based voice agent that takes a call in the browser Playground and schedules through the M2 backend. It is a real-time pipeline (microphone, speech-to-text, LLM with tools, text-to-speech), not a scripted flow.

**Status: partially complete.** Everything outside the audio providers is built and tested. A live call against LiveKit and a speech/LLM provider has **not** been run, because no LiveKit or provider credentials were available in the build environment. See [Verification](#verification).

## Components

```
Browser (apps/web /playground)            Backend (apps/api)                    Worker (services/voice-agent)
  VoiceTransport (LiveKit client)  <---->  LiveKit server  <---->  AgentServer (voice_agent.worker)
  polls events + live state        <----   /api/voice/...  <----   claim / events / state / complete
                                           M2 scheduling API <---- SchedulingClient (tools)
```

| Part | Responsibility |
| --- | --- |
| `apps/api/app/api/voice.py` | Creates call sessions and scoped LiveKit tokens, serves the frozen configuration to the worker, stores events, state and the final outcome. |
| `services/voice-agent/voice_agent/worker.py` | The only module that touches LiveKit types. Claims a session, builds the pipeline, wires pipeline events onto `CallRuntime`. |
| `voice_agent/runtime.py` | LiveKit-agnostic call runtime: transcripts, state, latency, final report. Unit-tested without a media server. |
| `voice_agent/tools.py` | The tool layer. Talks to the M2 HTTP API only; never touches the scheduling database or reimplements its rules. |
| `voice_agent/providers.py` | Provider boundary. One pipeline (OpenAI STT, LLM, TTS plus local Silero VAD) built from settings. Adding a provider means adding a factory here. |
| `apps/web/src/lib/voice/` | `VoiceTransport` interface, the LiveKit adapter, a controlled test adapter, the call hook and event folding. |

## Trust and tenant isolation

- The browser receives only a short-lived (600 s) LiveKit participant token. It is scoped to one room, may publish the microphone only, cannot publish data, and carries no API secret.
- The token explicitly dispatches the named worker (`RoomAgentDispatch`). The dispatch metadata is only the call-session id.
- The worker never trusts room or job metadata for clinic identity. It calls `POST /api/voice/worker/sessions/{id}/claim` with the `X-Voice-Worker-Secret` header and the room name, and receives the clinic id, the config version and the frozen published configuration. A second claim, a wrong room, an unknown id or an expired session is refused.
- The configuration is the immutable published version recorded on the session. Republishing mid-call does not change a call in progress; the next call uses the new version.
- The same runtime serves every clinic. Instructions, hours, appointment types, policy, greeting, allowed intents and capabilities all come from the configuration. There is no clinic-name branching (a unit test scans the source for it).
- Every session records clinic id, config version, a unique call-session id, the local development actor (`local-dev-operator`, a placeholder until real authentication exists) and timestamps.

## Persistence

`call_sessions` and `call_events` (migration `0004`, additive). Stored: finalized transcript turns, tool started/finished events, state changes, operation ids and the outcome, duration and error. Not stored: audio, interim transcripts, secrets, date of birth, phone digits, tokens. Redaction runs in the worker and again in the backend.

## Providers and cost

The worker builds its provider clients from `VOICE_OPENAI_API_KEY`. It deliberately does **not** read the ambient `OPENAI_API_KEY`, so a developer's general key is never spent on calls by accident. With the variable unset the worker fails the call with `provider_not_configured`; it never substitutes generated or canned speech. Running live calls uses paid LiveKit and OpenAI usage and needs your explicit decision.

## Verification

| Layer | How it is verified | Status |
| --- | --- | --- |
| Session API, tokens, worker channel, idempotent events | pytest against real PostgreSQL | Verified |
| Tool layer against the real M2 API (booking, reschedule, cancel, unknown outcomes, isolation, capability gating) | pytest against real PostgreSQL with a fault-injecting transport | Verified |
| State machines, instructions, event recorder, runtime | unit tests, no LiveKit | Verified |
| Playground UI, transcript, tool activity, errors, outcome, call details | Playwright with the controlled transport and a test-driven worker channel | Verified (no audio) |
| LiveKit join, audio in/out, STT/LLM/TTS, barge-in, latency | needs LiveKit and provider credentials | **Not verified** |

The Playwright tests use a transport that carries no audio and play the worker's part through the real worker API. They prove the UI and the persistence pipeline, not speech.

## Limitations

- No telephony: browser microphone only. No claim of phone integration.
- Simulated identity verification (date of birth plus last four phone digits). No real identity proofing; not HIPAA compliant and not intended for real patient data.
- Escalation records a request for staff. It does not transfer the call.
- The browser follows the call by polling (about 0.7 s), so the transcript can lag the audio slightly.
- Latency figures are observed by the worker and are not synchronized with the browser clock.
- Single worker process per call; no load testing.
