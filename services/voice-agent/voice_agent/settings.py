"""Worker configuration, read from the environment (and ``../../.env`` when present).

Credentials are never defaulted. Missing ones are reported by name; the worker then fails the call
visibly instead of substituting anything.
"""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    path = Path(__file__).resolve().parents[2].parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class WorkerSettings:
    api_base_url: str
    worker_secret: str
    agent_name: str
    stt_model: str
    llm_model: str
    tts_model: str
    tts_voice: str
    openai_api_key: str
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "WorkerSettings":
        _load_dotenv()
        e = os.environ.get
        return cls(
            api_base_url=e("CAREDEPLOY_API_URL", "http://localhost:8000"),
            worker_secret=e("VOICE_WORKER_SECRET", ""),
            agent_name=e("VOICE_AGENT_NAME", "caredeploy-voice"),
            stt_model=e("VOICE_STT_MODEL", "gpt-4o-mini-transcribe"),
            llm_model=e("VOICE_LLM_MODEL", "gpt-4.1-mini"),
            tts_model=e("VOICE_TTS_MODEL", "gpt-4o-mini-tts"),
            tts_voice=e("VOICE_TTS_VOICE", "ash"),
            openai_api_key=e("VOICE_OPENAI_API_KEY", ""),
            request_timeout_seconds=float(e("VOICE_SCHEDULING_TIMEOUT_SECONDS", "8")),
        )

    def missing(self) -> list[str]:
        """Names of required variables that are unset. LiveKit's own LIVEKIT_URL/API_KEY/
        API_SECRET are checked too because the worker cannot register without them."""
        need = {
            "VOICE_WORKER_SECRET": self.worker_secret,
            "VOICE_OPENAI_API_KEY": self.openai_api_key,
            "LIVEKIT_URL": os.environ.get("LIVEKIT_URL", ""),
            "LIVEKIT_API_KEY": os.environ.get("LIVEKIT_API_KEY", ""),
            "LIVEKIT_API_SECRET": os.environ.get("LIVEKIT_API_SECRET", ""),
        }
        return [k for k, v in need.items() if not v]
