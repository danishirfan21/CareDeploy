"""Provider boundary: one primary pipeline (STT -> LLM -> TTS) built from settings.

The rest of the worker only sees a ``Pipeline``; swapping a provider means adding another factory
here. Nothing is faked: with a key missing, ``build_pipeline`` raises ``ProviderNotConfigured`` and
the worker fails the call with that reason.
"""

from dataclasses import dataclass
from typing import Any

from voice_agent.settings import WorkerSettings


class ProviderNotConfigured(Exception):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("Speech/LLM provider is not configured: " + ", ".join(missing))
        self.missing = missing


@dataclass
class Pipeline:
    stt: Any
    llm: Any
    tts: Any
    vad: Any
    description: dict[str, str]


def build_pipeline(settings: WorkerSettings) -> Pipeline:
    if not settings.openai_api_key:
        raise ProviderNotConfigured(["VOICE_OPENAI_API_KEY"])
    from livekit.plugins import openai, silero

    key = settings.openai_api_key
    return Pipeline(
        stt=openai.STT(model=settings.stt_model, api_key=key),
        llm=openai.LLM(model=settings.llm_model, api_key=key),
        tts=openai.TTS(model=settings.tts_model, voice=settings.tts_voice, api_key=key),
        vad=silero.VAD.load(),
        description={
            "provider": "openai",
            "stt": settings.stt_model,
            "llm": settings.llm_model,
            "tts": settings.tts_model,
            "vad": "silero (local)",
        },
    )
