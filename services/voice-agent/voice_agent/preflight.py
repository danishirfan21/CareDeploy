"""Credential preflight for live voice tests: ``python -m voice_agent.preflight``.

Reports which required variables are set or missing. It never prints, logs or returns a value, and
it never contacts LiveKit or OpenAI. ``OPENAI_API_KEY`` is deliberately not read: only
``VOICE_OPENAI_API_KEY`` is ever used, so a general-purpose key is never spent by accident.
"""

import os
import sys
from collections.abc import Mapping

from voice_agent.settings import _load_dotenv

REQUIRED: tuple[tuple[str, str], ...] = (
    ("LIVEKIT_URL", "LiveKit project URL (wss://...)"),
    ("LIVEKIT_API_KEY", "LiveKit API key"),
    ("LIVEKIT_API_SECRET", "LiveKit API secret"),
    ("VOICE_WORKER_SECRET", "secret shared by the API and the worker"),
    ("VOICE_OPENAI_API_KEY", "OpenAI key dedicated to the voice worker"),
)
PLACEHOLDER_HINTS = ("changeme", "your-", "example", "xxxx", "placeholder")


def check(env: Mapping[str, str]) -> dict[str, str]:
    """Maps each required variable to ``set``, ``missing`` or ``placeholder``."""
    out: dict[str, str] = {}
    for name, _ in REQUIRED:
        value = env.get(name, "").strip()
        if not value:
            out[name] = "missing"
        elif any(h in value.lower() for h in PLACEHOLDER_HINTS):
            out[name] = "placeholder"
        else:
            out[name] = "set"
    return out


def render(status: Mapping[str, str]) -> str:
    lines = ["Live voice credential preflight (values are never shown)"]
    for name, purpose in REQUIRED:
        lines.append(f"  {status[name]:<12} {name}  - {purpose}")
    ready = all(v == "set" for v in status.values())
    lines.append(
        "READY for a live voice test." if ready else "NOT READY: live voice tests are blocked."
    )
    lines.append("Nothing was sent to LiveKit or OpenAI.")
    return "\n".join(lines)


def main() -> int:
    _load_dotenv()
    status = check(os.environ)
    print(render(status))
    return 0 if all(v == "set" for v in status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
