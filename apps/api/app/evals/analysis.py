"""Pure analysis over stored results: aggregation, deployment readiness and run comparison.

No I/O here, so the rules are unit-testable and cannot depend on hidden state.

Principles (see docs/deployment-readiness.md):
* Modes are never merged into a single percentage.
* A critical scenario that did not pass, for any reason (failed, errored, incomplete, skipped, not
  run), blocks promotion. Skipped is not success.
* Simulation success is not production or clinical readiness; live voice verification is a
  separate, still-open requirement.
"""

from dataclasses import dataclass, field
from typing import Any

PASS = "passed"
FAIL_LIKE = {"failed", "error", "incomplete"}
UNEXECUTED = {"skipped", "not_run"}
STATUS_ORDER = ["passed", "failed", "error", "incomplete", "skipped", "not_run"]

MODE_LABELS = {
    "workflow": "Workflow simulation",
    "llm": "LLM conversation",
    "real_audio": "Real audio",
}


@dataclass(frozen=True)
class ResultView:
    scenario_id: str
    name: str
    category: str
    severity: str
    status: str
    scenario_hash: str
    scenario_version: int


@dataclass(frozen=True)
class RunView:
    id: str
    clinic_id: str
    config_version: int
    mode: str
    status: str
    selection_kind: str
    suite_hash: str
    results: tuple[ResultView, ...]
    runner_info: dict[str, Any] = field(default_factory=dict)
    finished_at: str | None = None


def count_results(statuses: list[str]) -> dict[str, int]:
    out = {"total": len(statuses)}
    for s in STATUS_ORDER:
        out[s] = sum(1 for x in statuses if x == s)
    return out


# ------------------------------------------------------------------------------ readiness -----
LEVELS = {
    "not_evaluated": "Not evaluated",
    "blocked": "Blocked by critical failures",
    "simulation_passed": "Simulation checks passed",
    "live_pending": "Live verification pending",
    "verified_scope": "Verified for the explicitly tested scope",
}


def _mode_summary(run: RunView | None, mode: str) -> dict[str, Any]:
    if mode == "real_audio":
        return {
            "mode": mode,
            "label": MODE_LABELS[mode],
            "state": "not_run",
            "reason": "No real-audio runner exists yet; speech, turn-taking and interruption "
            "behavior are unverified.",
        }
    if run is None:
        return {"mode": mode, "label": MODE_LABELS[mode], "state": "not_run", "reason": None}
    counts = count_results([r.status for r in run.results])
    critical = [r for r in run.results if r.severity == "critical"]
    unmet = [r for r in critical if r.status != PASS]
    other_bad = [r for r in run.results if r.severity != "critical" and r.status in FAIL_LIKE]
    uncovered = [r for r in run.results if r.severity != "critical" and r.status in UNEXECUTED]
    partial = run.selection_kind != "all"
    if partial:
        state = "partial"
    elif run.status != "completed":
        state = "incomplete"
    elif unmet:
        state = "blocked"
    else:
        state = "passed"
    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "state": state,
        "run_id": run.id,
        "run_status": run.status,
        "counts": counts,
        "critical_unmet": [
            {"scenario_id": r.scenario_id, "name": r.name, "status": r.status} for r in unmet
        ],
        "non_critical_failures": [
            {"scenario_id": r.scenario_id, "name": r.name, "status": r.status} for r in other_bad
        ],
        "not_executed": [
            {"scenario_id": r.scenario_id, "name": r.name, "status": r.status} for r in uncovered
        ],
        "finished_at": run.finished_at,
    }


def compute_readiness(
    config_version: int, latest_by_mode: dict[str, RunView | None]
) -> dict[str, Any]:
    """`latest_by_mode` holds the most recent run of each mode for this configuration version
    (or None). Only a completed, full-suite run can establish anything."""
    modes = {m: _mode_summary(latest_by_mode.get(m), m) for m in ("workflow", "llm", "real_audio")}
    wf, llm = modes["workflow"], modes["llm"]
    blocking: list[dict[str, Any]] = []
    for m in ("workflow", "llm"):
        for u in modes[m].get("critical_unmet", []):
            blocking.append({"mode": m, **u})
    notes: list[str] = []
    for m in ("workflow", "llm"):
        s = modes[m]
        if s["state"] == "partial":
            notes.append(f"The latest {MODE_LABELS[m]} run covered only part of the suite.")
        if s["state"] == "incomplete":
            notes.append(f"The latest {MODE_LABELS[m]} run did not finish.")
        for r in s.get("non_critical_failures", []):
            notes.append(f"{r['scenario_id']} {r['name']}: {r['status']} (not critical).")
        for r in s.get("not_executed", []):
            notes.append(f"{r['scenario_id']} {r['name']}: {r['status']} (not critical).")

    wf_established = wf["state"] == "passed"
    llm_established = llm["state"] == "passed"
    audio_established = modes["real_audio"]["state"] == "passed"

    if blocking:
        level = "blocked"
    elif not wf_established:
        level = "not_evaluated"
    elif llm_established and audio_established:
        level = "verified_scope"
    elif llm_established:
        level = "live_pending"
    else:
        level = "simulation_passed"

    if level == "blocked":
        statement = (
            "Critical scenarios did not pass. Promotion to any environment is blocked until they "
            "pass in a completed full-suite run."
        )
    elif level == "not_evaluated":
        statement = "No completed full-suite workflow run exists for this configuration version."
    elif level == "simulation_passed":
        statement = (
            "Scripted workflow checks passed for this configuration version. This does not show "
            "that a language model chooses these actions, or that speech works. It is not a "
            "production or clinical-readiness claim."
        )
    elif level == "live_pending":
        statement = (
            "Workflow and LLM conversation suites passed. Real-audio behavior is unverified."
        )
    else:
        statement = (
            "Every evaluation mode passed for the tested scope. This is limited to the listed "
            "scenarios and is not a compliance or clinical-safety certification."
        )
    return {
        "config_version": config_version,
        "level": level,
        "label": LEVELS[level],
        "statement": statement,
        "simulated_promotion": (
            "blocked" if blocking else "allowed" if wf_established else "not_evaluated"
        ),
        "live_verification": "complete" if level == "verified_scope" else "pending",
        "blocking": blocking,
        "notes": notes,
        "modes": modes,
        "workflow_run_id": wf.get("run_id"),
    }


# ------------------------------------------------------------------------------ comparison ----
class IncompatibleRuns(Exception):
    pass


def _bucket(status: str) -> str:
    if status == PASS:
        return "pass"
    if status in FAIL_LIKE:
        return "fail"
    return "unexecuted"


def compare_runs(base: RunView, head: RunView) -> dict[str, Any]:
    """Compare two runs of the same evaluation mode. Scenarios whose definition changed between
    the runs are listed as not comparable instead of being counted as improvements/regressions."""
    if base.mode != head.mode:
        raise IncompatibleRuns(
            f"Runs use different evaluation modes ({base.mode} vs {head.mode}); results of "
            "different modes are not comparable."
        )
    warnings: list[str] = []
    if base.clinic_id != head.clinic_id:
        warnings.append("The runs belong to different clinics.")
    if base.status != "completed" or head.status != "completed":
        warnings.append("At least one run did not complete; missing scenarios are not failures.")
    if base.selection_kind != "all" or head.selection_kind != "all":
        warnings.append("At least one run covered only part of the suite.")
    if base.suite_hash != head.suite_hash:
        warnings.append(
            "The scenario definitions differ between the runs; only scenarios with an unchanged "
            "definition are compared."
        )
    if base.mode == "llm" and base.runner_info.get("model") != head.runner_info.get("model"):
        warnings.append(
            "The runs used different language models; differences are not evidence of improvement."
        )
    b = {r.scenario_id: r for r in base.results}
    h = {r.scenario_id: r for r in head.results}
    buckets: dict[str, list[dict[str, Any]]] = {
        k: []
        for k in (
            "newly_passing",
            "newly_failing",
            "newly_not_executed",
            "unchanged_passing",
            "unchanged_failing",
            "unchanged_not_executed",
            "not_comparable",
            "added",
            "removed",
        )
    }

    def row(r: ResultView, other: ResultView | None) -> dict[str, Any]:
        return {
            "scenario_id": r.scenario_id,
            "name": r.name,
            "category": r.category,
            "severity": r.severity,
            "base_status": other.status if other else None,
            "head_status": r.status,
        }

    for sid in sorted(set(b) | set(h)):
        rb, rh = b.get(sid), h.get(sid)
        if rb is None and rh is not None:
            buckets["added"].append(row(rh, None))
        elif rh is None and rb is not None:
            buckets["removed"].append({**row(rb, rb), "head_status": None})
        elif rb is not None and rh is not None:
            if rb.scenario_hash != rh.scenario_hash:
                buckets["not_comparable"].append(
                    {
                        **row(rh, rb),
                        "reason": f"definition changed (v{rb.scenario_version} to "
                        f"v{rh.scenario_version})",
                    }
                )
                continue
            bb, hb = _bucket(rb.status), _bucket(rh.status)
            if bb == hb:
                key = {
                    "pass": "unchanged_passing",
                    "fail": "unchanged_failing",
                    "unexecuted": "unchanged_not_executed",
                }[bb]
            elif hb == "pass":
                key = "newly_passing"
            elif hb == "fail":
                key = "newly_failing" if bb == "pass" else "unchanged_failing"
                if bb == "unexecuted":
                    key = "newly_failing"
            else:
                key = "newly_not_executed"
            buckets[key].append(row(rh, rb))
    return {
        "mode": base.mode,
        "mode_label": MODE_LABELS.get(base.mode, base.mode),
        "base": _run_ref(base),
        "head": _run_ref(head),
        "warnings": warnings,
        "buckets": buckets,
        "summary": {k: len(v) for k, v in buckets.items()},
    }


def _run_ref(r: RunView) -> dict[str, Any]:
    return {
        "run_id": r.id,
        "config_version": r.config_version,
        "status": r.status,
        "finished_at": r.finished_at,
        "counts": count_results([x.status for x in r.results]),
    }
