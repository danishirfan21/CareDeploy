"""What a scenario execution leaves behind: the evidence assertions are evaluated against."""

from dataclasses import dataclass, field
from typing import Any

MAX_TRACE_EVENTS = 300
MAX_TEXT = 1500


@dataclass
class ToolRecord:
    n: int
    actor: str
    tool: str
    args: dict[str, Any]
    step_id: str | None
    status: str
    code: str
    ok: bool
    operation_id: str | None
    text: str  # exactly what the model would be shown (JSON), used for disclosure checks


@dataclass
class ApiRecord:
    n: int
    step_id: str | None
    method: str
    path: str
    status: int
    code: str
    text: str
    operation_id: str | None = None
    replay: bool = False


@dataclass
class Check:
    """One evaluated assertion. `source` separates declared assertions from step expectations."""

    id: str
    type: str
    passed: bool
    expected: str
    observed: str
    message: str = ""
    source: str = "assertion"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "passed": self.passed,
            "expected": self.expected,
            "observed": self.observed,
            "message": self.message,
            "source": self.source,
        }


@dataclass
class Trace:
    tools: list[ToolRecord] = field(default_factory=list)
    apis: list[ApiRecord] = field(default_factory=list)
    utterances: list[tuple[str, str]] = field(default_factory=list)
    agent_texts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    outcomes: dict[str, str] = field(default_factory=dict)
    escalations: dict[str, str | None] = field(default_factory=dict)

    def note(self, text: str) -> None:
        self.notes.append(text[:MAX_TEXT])

    def disclosed_text(self) -> str:
        """Everything the system returned to a caller-facing component during the scenario."""
        parts = [t.text for t in self.tools] + [a.text for a in self.apis] + self.agent_texts
        return "\n".join(parts)


def clip(text: str, n: int = MAX_TEXT) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"
