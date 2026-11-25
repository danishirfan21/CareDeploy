# Voice testing: what each kind of test proves

Four kinds of test exist or are planned. A result from one kind never stands in for another.

| Kind | Where | Runs in CI | Proves | Does not prove |
| --- | --- | --- | --- | --- |
| **Transport unit** | `services/voice-agent/tests/` (`test_runtime.py`, `test_events.py`, `test_states.py`) | Yes | Event ordering and deduplication, redaction, state transitions, provider-error handling, connection failure, flush retry, shutdown cleanup, interruption bookkeeping, latency arithmetic | Anything audible |
| **Shared tool integration** | `apps/api/tests/test_voice_tools.py`, `test_voice_sessions.py`, `test_lifecycle.py` | Yes | The real tool layer against the real scheduling API and PostgreSQL; session pinning; worker channel auth and integrity | Speech, model decisions |
| **Genuine LLM** | Not run (needs approved credentials and spend) | No | Would show whether a model follows the instructions (emergency guidance, confirmation, escalation) | Audio |
| **Real audio** | Manual, [`live-voice-test-plan.md`](live-voice-test-plan.md) TEST-01 to TEST-13, all Not Run | No | Would show speech recognition, synthesis, barge-in and latency with a person speaking | Statistical accuracy (small samples) |

## What the transport unit tests script

`CallRuntime` is driven with scripted pipeline events: transcripts (interim and final, including a redelivered final), agent turns (complete and interrupted), user and agent speaking states, recoverable and unrecoverable provider errors, transport states, and a reporter that fails on demand. The real event recorder, state machines and redaction are used; only the reporter and clock are fakes.

An "interruption" in these tests is a scripted `interrupted=True` turn carrying the text spoken so far. Playing a recording over a synthetic caller would exercise voice-activity detection, not human acoustic barge-in, so it is not claimed as verification of it.

## Bug found by this work

A redelivered final caller transcript was recorded once (deduplicated) but still counted as a new caller turn by the tool layer. The runtime now counts a turn only when the event was newly recorded. Latency is also rounded rather than truncated (0.8 s was reported as 799 ms).
