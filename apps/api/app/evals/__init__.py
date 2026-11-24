"""Conversation evaluation engine (M4).

The engine drives the *same* tool layer the M3 voice worker uses (`voice_agent.tools.Toolbox`,
`CallRuntime`, `SchedulingClient`, `build_instructions`, `exposed_tool_schemas`) against the real M2
scheduling API. `services/voice-agent` is a sibling package in this monorepo; when it is not
installed we put it on `sys.path` so evaluation works from a plain checkout.
"""

import sys
from pathlib import Path

RUNNER_VERSION = "1.0.0"
REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIO_DIR = REPO_ROOT / "evals" / "scenarios"


def _ensure_voice_agent_importable() -> None:
    try:
        import voice_agent  # noqa: F401
    except ModuleNotFoundError:
        sys.path.insert(0, str(REPO_ROOT / "services" / "voice-agent"))


_ensure_voice_agent_importable()
