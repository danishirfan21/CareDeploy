# CareDeploy voice agent

LiveKit Agents worker for the CareDeploy Playground. Design: [`docs/voice-agent.md`](../../docs/voice-agent.md).

## Setup

```powershell
cd services/voice-agent
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Configuration (environment variables, never committed)

| Variable | Used by | Purpose |
| --- | --- | --- |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | worker and API | LiveKit project. |
| `VOICE_WORKER_SECRET` | worker and API | Shared secret for the worker channel. Use a long random value. |
| `CAREDEPLOY_API_URL` | worker | Backend base URL (default `http://localhost:8000`). |
| `VOICE_OPENAI_API_KEY` | worker | Speech and LLM provider key. Deliberately not `OPENAI_API_KEY`. |
| `VOICE_LLM_MODEL`, `VOICE_STT_MODEL`, `VOICE_TTS_MODEL`, `VOICE_TTS_VOICE` | worker | Optional model overrides. |

The backend also needs `LIVEKIT_*` and `VOICE_WORKER_SECRET` to create sessions; without them the Playground reports exactly which variables are missing.

## Run

```powershell
.venv\Scripts\python -m voice_agent.worker dev
```

Starting a worker connects to LiveKit and uses paid provider usage once a call is made. Do this deliberately.

## Manual test (needs credentials)

1. Seed and publish the sample clinics: `python -m app.seed --publish` (from `apps/api`).
2. Start the API, the web app and the worker.
3. Open `/playground`, choose a clinic, press Start call and allow the microphone.
4. Try: "I'd like to book a checkup next week." Verify as Avery Quinn (Northstar), date of birth 1985-04-12, phone ending 0101. Confirm only when asked.
5. End the call and open the call details link.

## Tests

```powershell
.venv\Scripts\python -m pytest tests
```

These run without LiveKit or any credentials. Tool-layer integration tests against PostgreSQL live in `apps/api/tests/test_voice_tools.py`.

## Limitations

Browser microphone only (no telephony). Simulated identity verification. Live audio verification has not been performed. See [`docs/voice-agent.md`](../../docs/voice-agent.md).
