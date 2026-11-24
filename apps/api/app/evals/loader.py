"""Load and validate scenario files. Nothing executes until every selected file is valid."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from app.evals import SCENARIO_DIR
from app.evals.schema import Scenario


class ScenarioError(Exception):
    """One or more scenario files are invalid. `problems` lists file-level messages."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _describe(path: Path, err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        out.append(f"{path.name}: {loc}: {e['msg']}")
    return out


def parse_scenario(text: str, name: str = "scenario.json") -> Scenario:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ScenarioError([f"{name}: invalid JSON ({e.msg} at line {e.lineno})"]) from e
    try:
        return Scenario.model_validate(raw)
    except ValidationError as e:
        raise ScenarioError(_describe(Path(name), e)) from e


def load_directory(directory: Path) -> list[Scenario]:
    files = sorted(directory.glob("*.json"))
    if not files:
        raise ScenarioError([f"no scenario files found in {directory.name}"])
    scenarios: list[Scenario] = []
    problems: list[str] = []
    for f in files:
        try:
            parsed = parse_scenario(f.read_text(encoding="utf-8"), f.name)
        except ScenarioError as e:
            problems.extend(e.problems)
            continue
        scenarios.append(parsed)
        if f.stem != parsed.id:
            problems.append(f"{f.name}: file name must be {parsed.id}.json")
    seen: dict[str, int] = {}
    for s in scenarios:
        seen[s.id] = seen.get(s.id, 0) + 1
    problems.extend(f"duplicate scenario id {i}" for i, n in seen.items() if n > 1)
    if problems:
        raise ScenarioError(problems)
    return sorted(scenarios, key=lambda s: s.id)


@lru_cache(maxsize=1)
def _cached() -> tuple[Scenario, ...]:
    return tuple(load_directory(SCENARIO_DIR))


def load_suite() -> list[Scenario]:
    return list(_cached())


def reload_suite() -> list[Scenario]:
    _cached.cache_clear()
    return load_suite()


@dataclass(frozen=True)
class Selection:
    kind: str  # all | category | scenario
    value: str | None = None


def select(suite: list[Scenario], sel: Selection) -> list[Scenario]:
    if sel.kind == "all":
        return list(suite)
    if sel.kind == "category":
        chosen = [s for s in suite if s.category == sel.value]
    elif sel.kind == "scenario":
        chosen = [s for s in suite if s.id == sel.value]
    else:
        raise ScenarioError([f"unknown selection kind '{sel.kind}'"])
    if not chosen:
        raise ScenarioError([f"selection {sel.kind}={sel.value} matched no scenario"])
    return chosen


def suite_hash(suite: list[Scenario]) -> str:
    """Fingerprint of the exact scenario definitions in use (ids, versions, content)."""
    import hashlib

    parts = sorted(f"{s.id}:{s.version}:{s.content_hash()}" for s in suite)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()
