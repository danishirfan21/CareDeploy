from voice_agent.preflight import check, render

FULL = {
    "LIVEKIT_URL": "wss://lk.test",
    "LIVEKIT_API_KEY": "APIkeyvalue",
    "LIVEKIT_API_SECRET": "supersecretvalue",
    "VOICE_WORKER_SECRET": "workersecretvalue",
    "VOICE_OPENAI_API_KEY": "sk-test-not-real-value",
}


def test_all_set_is_ready_and_values_are_never_rendered() -> None:
    out = render(check(FULL))
    assert "READY for a live voice test." in out
    for v in FULL.values():
        assert v not in out


def test_missing_and_placeholder_are_reported_by_name() -> None:
    env = {**FULL, "LIVEKIT_API_SECRET": "", "VOICE_WORKER_SECRET": "changeme"}
    env.pop("VOICE_OPENAI_API_KEY")
    status = check(env)
    assert status["LIVEKIT_API_SECRET"] == "missing"
    assert status["VOICE_OPENAI_API_KEY"] == "missing"
    assert status["VOICE_WORKER_SECRET"] == "placeholder"
    assert "NOT READY" in render(status)


def test_ambient_openai_key_is_ignored() -> None:
    status = check({**FULL, "OPENAI_API_KEY": "sk-ambient", "VOICE_OPENAI_API_KEY": ""})
    assert status["VOICE_OPENAI_API_KEY"] == "missing"
    assert "OPENAI_API_KEY" not in render(status).replace("VOICE_OPENAI_API_KEY", "")
