"""Evaluation HTTP API: typed contracts, duplicate prevention, tenancy, lifecycle."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.db.session import get_sessionmaker
from app.main import app
from app.models.evals import EvalRun
from tests.test_evals_runner import NORTHSTAR, run_eval
from tests.world import World

LAKESIDE = "Lakeside Dermatology"


@pytest.fixture
def launched() -> Iterator[list[uuid.UUID]]:
    """Replace the worker launcher: runs stay queued, so nothing executes inside API tests."""
    calls: list[uuid.UUID] = []

    async def stub(run_id: uuid.UUID) -> None:
        calls.append(run_id)

    app.state.eval_launcher = stub
    yield calls
    del app.state.eval_launcher


def base(world: World, name: str = NORTHSTAR) -> str:
    return f"/api/clinics/{world.clinics[name].id}/evaluations"


@pytest.mark.asyncio
async def test_catalog_lists_the_twenty_scenarios(client: AsyncClient) -> None:
    r = await client.get("/api/evaluations/scenarios")
    assert r.status_code == 200
    body = r.json()
    assert [s["id"] for s in body["scenarios"]] == [f"EVAL-{i:03d}" for i in range(1, 21)]
    assert len(body["categories"]) == 5
    modes = {m["mode"]: m for m in body["modes"]}
    assert modes["workflow"]["available"] is True
    assert modes["llm"]["available"] is False and modes["llm"]["reason"]
    assert modes["real_audio"]["available"] is False


@pytest.mark.asyncio
async def test_unavailable_modes_are_refused_not_simulated(world: World) -> None:
    for mode in ("llm", "real_audio"):
        r = await world.client.post(f"{base(world)}/runs", json={"mode": mode})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "mode_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"selection": {"kind": "scenario", "value": "../../etc/passwd"}},
        {"selection": {"kind": "scenario", "value": "EVAL-999x"}},
        {"selection": {"kind": "category", "value": "nope"}},
        {"selection": {"kind": "all", "value": "EVAL-001"}},
        {"mode": "workflow", "script": "print(1)"},
        {"mode": "workflow", "path": "evals/scenarios/EVAL-001.json"},
        {"mode": "bogus"},
        {"config_version": 0},
    ],
)
async def test_arbitrary_input_is_rejected(world: World, body: dict[str, Any]) -> None:
    r = await world.client.post(f"{base(world)}/runs", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unknown_scenario_and_version(world: World, launched: list[uuid.UUID]) -> None:
    r = await world.client.post(
        f"{base(world)}/runs", json={"selection": {"kind": "scenario", "value": "EVAL-099"}}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_selection"
    r = await world.client.post(f"{base(world)}/runs", json={"config_version": 99})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "version_not_found"
    assert launched == []


@pytest.mark.asyncio
async def test_duplicate_submission_cancel_and_resubmit(
    world: World, launched: list[uuid.UUID]
) -> None:
    url = f"{base(world)}/runs"
    first = await world.client.post(
        url, json={"selection": {"kind": "scenario", "value": "EVAL-002"}}
    )
    assert first.status_code == 202
    run = first.json()
    assert run["status"] == "queued" and run["mode"] == "workflow" and run["total"] == 1
    assert run["config_version"] == 1 and len(run["config_hash"]) == 64
    assert launched == [uuid.UUID(run["id"])]

    dup = await world.client.post(url, json={})
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "run_in_progress"
    assert len(launched) == 1

    # Another clinic is not blocked by this one's run.
    other = await world.client.post(
        f"{base(world, LAKESIDE)}/runs",
        json={"selection": {"kind": "scenario", "value": "EVAL-002"}},
    )
    assert other.status_code == 202

    cancelled = await world.client.post(f"{url}/{run['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    again = await world.client.post(f"{url}/{run['id']}/cancel")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "run_finished"

    resubmit = await world.client.post(
        url, json={"selection": {"kind": "scenario", "value": "EVAL-002"}}
    )
    assert resubmit.status_code == 202

    listing = (await world.client.get(url)).json()
    assert [r["status"] for r in listing] == ["queued", "cancelled"]


@pytest.mark.asyncio
async def test_runs_are_invisible_across_clinics(world: World, launched: list[uuid.UUID]) -> None:
    run = (
        await world.client.post(
            f"{base(world)}/runs", json={"selection": {"kind": "scenario", "value": "EVAL-002"}}
        )
    ).json()
    foreign = f"{base(world, LAKESIDE)}/runs/{run['id']}"
    assert (await world.client.get(foreign)).status_code == 404
    assert (await world.client.post(f"{foreign}/cancel")).status_code == 404
    assert (await world.client.get(f"{base(world, LAKESIDE)}/runs")).json() == []


@pytest.mark.asyncio
async def test_stale_run_is_abandoned_as_error(world: World, launched: list[uuid.UUID]) -> None:
    run = (
        await world.client.post(
            f"{base(world)}/runs", json={"selection": {"kind": "scenario", "value": "EVAL-002"}}
        )
    ).json()
    async with get_sessionmaker()() as s:
        await s.execute(
            update(EvalRun)
            .where(EvalRun.id == uuid.UUID(run["id"]))
            .values(created_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await s.commit()
    detail = (await world.client.get(f"{base(world)}/runs/{run['id']}")).json()
    assert detail["status"] == "error" and "stopped responding" in detail["error"]
    # ...and the clinic is no longer blocked.
    ok = await world.client.post(
        f"{base(world)}/runs", json={"selection": {"kind": "scenario", "value": "EVAL-002"}}
    )
    assert ok.status_code == 202


@pytest.mark.asyncio
async def test_results_readiness_rerun_and_compare(world: World, launched: list[uuid.UUID]) -> None:
    run_id = await run_eval(world, "category", "appointment_workflows")
    root = base(world)

    detail = (await world.client.get(f"{root}/runs/{run_id}")).json()
    assert detail["status"] == "completed" and detail["counts"]["passed"] == 4
    assert [g["category"] for g in detail["categories"]] == ["appointment_workflows"]
    first = detail["categories"][0]["results"][0]
    assert first["status"] == "passed" and first["not_evaluated"]

    one = (await world.client.get(f"{root}/runs/{run_id}/results/EVAL-001")).json()
    assert one["assertions"] and all(a["passed"] for a in one["assertions"])
    assert one["observed"]["tools"] and one["events"]
    assert one["expected"]["behavior"]
    missing = await world.client.get(f"{root}/runs/{run_id}/results/EVAL-099")
    assert missing.status_code == 404

    # A partial run never establishes readiness, and modes are reported separately.
    ready = (await world.client.get(f"{root}/readiness")).json()
    assert ready["level"] == "not_evaluated"
    assert ready["modes"]["workflow"]["state"] == "partial"
    assert ready["modes"]["llm"]["state"] == "not_run"
    assert ready["modes"]["real_audio"]["state"] == "not_run"
    assert "percent" not in str(ready).lower()

    rerun = await world.client.post(f"{root}/runs/{run_id}/rerun", json={"scenario_id": "EVAL-003"})
    assert rerun.status_code == 202
    assert rerun.json()["rerun_of"] == str(run_id) and rerun.json()["config_version"] == 1
    assert launched[-1] == uuid.UUID(rerun.json()["id"])

    # Compare: a finished run against itself has no regressions.
    cmp = (
        await world.client.get(f"{root}/compare", params={"base": str(run_id), "head": str(run_id)})
    ).json()
    assert cmp["summary"]["unchanged_passing"] == 4 and cmp["summary"]["newly_failing"] == 0
    bad = await world.client.get(
        f"{root}/compare", params={"base": str(run_id), "head": str(uuid.uuid4())}
    )
    assert bad.status_code == 404


@pytest.mark.asyncio
async def test_worker_process_executes_a_queued_run(
    world: World, launched: list[uuid.UUID]
) -> None:
    """The production path: the API queues a run and a separate worker process completes it."""
    import asyncio
    import sys

    from app.testdb import API_ROOT

    created = (
        await world.client.post(
            f"{base(world)}/runs", json={"selection": {"kind": "scenario", "value": "EVAL-002"}}
        )
    ).json()
    # The stub launcher keeps the API from spawning its own worker; start exactly one ourselves
    # so the test can wait for it.
    assert launched == [uuid.UUID(created["id"])]
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.evals.worker",
        created["id"],
        cwd=str(API_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    assert proc.returncode == 0, err.decode()
    assert out.decode().strip().endswith("completed"), (out.decode(), err.decode()[-1500:])
    detail = (await world.client.get(f"{base(world)}/runs/{created['id']}")).json()
    assert detail["status"] == "completed" and detail["counts"]["passed"] == 1


def test_worker_rejects_bad_arguments() -> None:
    from app.evals.worker import main

    assert main(["worker"]) == 2
    assert main(["worker", "not-a-uuid"]) == 2
