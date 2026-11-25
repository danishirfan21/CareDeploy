"""Evaluation engine units that need no database: scenario validation, selection, readiness
levels and regression comparison."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.evals import SCENARIO_DIR, analysis
from app.evals.analysis import IncompatibleRuns, ResultView, RunView
from app.evals.loader import (
    ScenarioError,
    Selection,
    load_directory,
    load_suite,
    parse_scenario,
    select,
    suite_hash,
)
from app.evals.schema import CATEGORY_LABELS


def _raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SCENARIO_DIR / "EVAL-002.json").read_text("utf-8"))
    return data


# ---- the committed suite ---------------------------------------------------------------------
def test_suite_has_the_required_scenarios() -> None:
    suite = load_suite()
    assert [s.id for s in suite] == [f"EVAL-{i:03d}" for i in range(1, 22)]
    assert {s.category for s in suite} == set(CATEGORY_LABELS)
    assert all(s.expected.behavior for s in suite)
    assert all(s.not_evaluated_in_workflow for s in suite)  # honest about what Mode A cannot see


def test_suite_hash_is_stable_and_content_sensitive() -> None:
    suite = load_suite()
    assert suite_hash(suite) == suite_hash(list(reversed(suite)))
    changed = _raw()
    changed["name"] = "Changed"
    other = [s for s in suite if s.id != "EVAL-002"] + [parse_scenario(json.dumps(changed))]
    assert suite_hash(other) != suite_hash(suite)


# ---- strict validation -----------------------------------------------------------------------
def test_unknown_keys_are_rejected() -> None:
    raw = _raw()
    raw["shell"] = "rm -rf /"
    with pytest.raises(ScenarioError) as e:
        parse_scenario(json.dumps(raw))
    assert "shell" in str(e.value)


def test_invalid_json_and_bad_id_are_reported() -> None:
    with pytest.raises(ScenarioError, match="invalid JSON"):
        parse_scenario("{nope")
    raw = _raw()
    raw["id"] = "scenario-2"
    with pytest.raises(ScenarioError):
        parse_scenario(json.dumps(raw))


def test_real_audio_scenarios_cannot_be_declared() -> None:
    raw = _raw()
    raw["modes"] = ["workflow", "real_audio"]
    raw.pop("llm", None)
    with pytest.raises(ScenarioError, match="audio runner"):
        parse_scenario(json.dumps(raw))


def test_mode_blocks_must_match_declared_modes() -> None:
    raw = _raw()
    raw["modes"] = ["llm"]
    with pytest.raises(ScenarioError):
        parse_scenario(json.dumps(raw))


def test_directory_problems_are_all_listed(tmp_path: Path) -> None:
    good = (SCENARIO_DIR / "EVAL-002.json").read_text("utf-8")
    (tmp_path / "EVAL-002.json").write_text(good, "utf-8")
    (tmp_path / "EVAL-003.json").write_text(good, "utf-8")  # duplicate id, wrong file name
    (tmp_path / "EVAL-004.json").write_text("{", "utf-8")
    with pytest.raises(ScenarioError) as e:
        load_directory(tmp_path)
    text = " | ".join(e.value.problems)
    assert "duplicate scenario id EVAL-002" in text
    assert "EVAL-004.json: invalid JSON" in text
    assert "EVAL-003.json: file name must be EVAL-002.json" in text


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match="no scenario files"):
        load_directory(tmp_path)


# ---- selection -------------------------------------------------------------------------------
def test_selection_modes() -> None:
    suite = load_suite()
    assert len(select(suite, Selection("all"))) == 21
    assert [s.id for s in select(suite, Selection("scenario", "EVAL-005"))] == ["EVAL-005"]
    cat = select(suite, Selection("category", "appointment_workflows"))
    assert len(cat) == 4 and {s.category for s in cat} == {"appointment_workflows"}
    for bad in (Selection("scenario", "EVAL-404"), Selection("category", "x"), Selection("what")):
        with pytest.raises(ScenarioError):
            select(suite, bad)


# ---- readiness -------------------------------------------------------------------------------
def _res(sid: str, status: str, severity: str = "critical", h: str = "h") -> ResultView:
    return ResultView(sid, f"name {sid}", "appointment_workflows", severity, status, h, 1)


def _run(
    mode: str = "workflow",
    statuses: dict[str, str] | None = None,
    *,
    kind: str = "all",
    status: str = "completed",
    suite: str = "s1",
    hashes: str = "h",
    severity: str = "critical",
    info: dict[str, Any] | None = None,
) -> RunView:
    statuses = statuses or {f"EVAL-{i:03d}": "passed" for i in range(1, 21)}
    return RunView(
        id=f"run-{mode}",
        clinic_id="c",
        config_version=1,
        mode=mode,
        status=status,
        selection_kind=kind,
        suite_hash=suite,
        results=tuple(_res(k, v, severity, hashes) for k, v in statuses.items()),
        runner_info=info or {},
    )


def test_no_runs_is_not_evaluated() -> None:
    r = analysis.compute_readiness(1, {})
    assert r["level"] == "not_evaluated" and r["live_verification"] == "pending"
    assert {m["state"] for m in r["modes"].values()} == {"not_run"}


def test_full_passing_simulation_is_never_called_ready() -> None:
    r = analysis.compute_readiness(1, {"workflow": _run()})
    assert r["level"] == "simulation_passed"
    assert r["live_verification"] == "pending"
    text = r["statement"].lower()
    assert "does not show" in text and "not a production" in text
    assert r["modes"]["llm"]["state"] == "not_run"


def test_critical_failure_blocks() -> None:
    bad = {**{f"EVAL-{i:03d}": "passed" for i in range(1, 21)}, "EVAL-016": "failed"}
    r = analysis.compute_readiness(1, {"workflow": _run(statuses=bad)})
    assert r["level"] == "blocked" and r["simulated_promotion"] == "blocked"
    assert [b["scenario_id"] for b in r["blocking"]] == ["EVAL-016"]


def test_non_critical_failure_does_not_block_but_is_reported() -> None:
    bad = {**{f"EVAL-{i:03d}": "passed" for i in range(1, 21)}, "EVAL-009": "failed"}
    r = analysis.compute_readiness(1, {"workflow": _run(statuses=bad, severity="high")})
    assert r["level"] != "blocked"
    assert any("EVAL-009" in n for n in r["notes"])


def test_partial_or_incomplete_run_establishes_nothing() -> None:
    one = {"EVAL-001": "passed"}
    partial = analysis.compute_readiness(1, {"workflow": _run(statuses=one, kind="scenario")})
    assert partial["level"] == "not_evaluated"
    assert partial["modes"]["workflow"]["state"] == "partial"
    broken = analysis.compute_readiness(1, {"workflow": _run(status="incomplete")})
    assert broken["level"] == "not_evaluated"
    assert broken["modes"]["workflow"]["state"] == "incomplete"


def test_skipped_is_not_success() -> None:
    ok = {f"EVAL-{i:03d}": "passed" for i in range(1, 21)}
    critical = analysis.compute_readiness(
        1, {"workflow": _run(statuses={**ok, "EVAL-003": "skipped"})}
    )
    assert critical["level"] == "blocked"  # a critical scenario that did not run is unmet
    minor = analysis.compute_readiness(
        1, {"workflow": _run(statuses={**ok, "EVAL-003": "skipped"}, severity="high")}
    )
    assert any("EVAL-003" in n and "skipped" in n for n in minor["notes"])
    assert minor["modes"]["workflow"]["counts"]["skipped"] == 1


def test_modes_are_never_merged_into_one_number() -> None:
    r = analysis.compute_readiness(1, {"workflow": _run(), "llm": _run("llm")})
    assert r["level"] == "live_pending"
    assert set(r["modes"]) == {"workflow", "llm", "real_audio"}
    assert "percent" not in json.dumps(r).lower() and "%" not in json.dumps(r)
    # No real-audio runner exists, so even a supplied run cannot raise the level.
    audio = analysis.compute_readiness(
        1, {"workflow": _run(), "llm": _run("llm"), "real_audio": _run("real_audio")}
    )
    assert audio["level"] == "live_pending" and audio["live_verification"] == "pending"
    assert audio["modes"]["real_audio"]["state"] == "not_run"


def test_count_results() -> None:
    c = analysis.count_results(["passed", "failed", "passed", "error", "not_run"])
    assert c["total"] == 5 and c["passed"] == 2 and c["failed"] == 1 and c["error"] == 1


# ---- comparison ------------------------------------------------------------------------------
def test_compare_buckets_regressions_and_improvements() -> None:
    base = _run(statuses={"EVAL-001": "passed", "EVAL-002": "failed", "EVAL-003": "passed"})
    head = _run(
        statuses={
            "EVAL-001": "failed",
            "EVAL-002": "passed",
            "EVAL-003": "passed",
            "EVAL-004": "passed",
        }
    )
    out = analysis.compare_runs(base, head)
    ids = {k: [r["scenario_id"] for r in v] for k, v in out["buckets"].items()}
    assert ids["newly_failing"] == ["EVAL-001"]
    assert ids["newly_passing"] == ["EVAL-002"]
    assert ids["unchanged_passing"] == ["EVAL-003"]
    assert ids["added"] == ["EVAL-004"]


def test_compare_flags_changed_definitions_instead_of_judging() -> None:
    base = _run(statuses={"EVAL-001": "passed"}, hashes="old")
    head = _run(statuses={"EVAL-001": "failed"}, hashes="new", suite="s2")
    out = analysis.compare_runs(base, head)
    assert out["summary"]["not_comparable"] == 1 and out["summary"]["newly_failing"] == 0
    assert any("scenario definitions differ" in w for w in out["warnings"])


def test_compare_refuses_different_modes() -> None:
    with pytest.raises(IncompatibleRuns):
        analysis.compare_runs(_run("workflow"), _run("llm"))


def test_compare_warns_on_partial_incomplete_and_model_change() -> None:
    out = analysis.compare_runs(
        _run("llm", kind="scenario", info={"model": "a"}),
        _run("llm", status="incomplete", info={"model": "b"}),
    )
    joined = " ".join(out["warnings"])
    assert "part of the suite" in joined and "did not complete" in joined
    assert "different language models" in joined
