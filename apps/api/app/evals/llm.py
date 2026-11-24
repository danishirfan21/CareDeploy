"""Which evaluation modes can run here, and why not.

* workflow: deterministic, local, needs nothing paid. Always available.
* llm: needs a language-model credential AND explicit approval to bill it, AND a provider
  implementation. No provider implementation ships in M4, so it is reported "Not run" even when
  credentials exist. That keeps the state honest instead of silently simulating a model.
* real_audio: needs speech services, a media server and a browser or telephony bridge. Not run.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModeAvailability:
    mode: str
    available: bool
    reason: str | None


def availability() -> dict[str, ModeAvailability]:
    has_key = bool(os.environ.get("EVAL_LLM_API_KEY"))
    approved = os.environ.get("EVAL_LLM_APPROVED", "").lower() in ("1", "true", "yes")
    if not has_key:
        llm_reason = "No language-model credentials are configured for evaluations."
    elif not approved:
        llm_reason = "Billable model calls have not been approved (EVAL_LLM_APPROVED)."
    else:
        llm_reason = "No language-model evaluation provider is implemented in this release."
    return {
        "workflow": ModeAvailability("workflow", True, None),
        "llm": ModeAvailability("llm", False, llm_reason),
        "real_audio": ModeAvailability(
            "real_audio",
            False,
            "Real-audio evaluation needs speech services and a media connection, and is not run "
            "without explicit approval.",
        ),
    }
