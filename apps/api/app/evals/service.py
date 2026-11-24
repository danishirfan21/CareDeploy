"""Evaluation run lifecycle on the API side: validation, duplicate prevention, cancellation, stale
run recovery and process launch. Execution itself happens in a separate worker process."""

import asyncio
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.evals import RUNNER_VERSION
from app.evals.llm import availability
from app.evals.loader import (
    ScenarioError,
    Selection,
    load_suite,
    suite_hash,
)
from app.evals.loader import (
    select as select_scenarios,
)
from app.evals.store import config_hash
from app.models import ConfigVersion
from app.models.evals import EvalRun
from app.testdb import API_ROOT

log = logging.getLogger("caredeploy.evals")

STALE_AFTER = timedelta(seconds=90)
QUEUE_STALE_AFTER = timedelta(seconds=60)

Launcher = Callable[[uuid.UUID], Awaitable[None]]


class EvalError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


async def spawn_worker(run_id: uuid.UUID) -> None:
    """Production launcher: a detached worker process, so a long run never blocks API workers."""
    await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.evals.worker",
        str(run_id),
        cwd=str(API_ROOT),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def sweep_stale(session: AsyncSession, clinic_id: uuid.UUID) -> int:
    """A worker that died leaves its run `running`/`queued` forever; mark such runs `error`
    (never `completed`) so the clinic is not blocked and the report is honest."""
    now = datetime.now(UTC)
    res = await session.execute(
        update(EvalRun)
        .where(
            EvalRun.clinic_id == clinic_id,
            EvalRun.status.in_(("queued", "running")),
            ((EvalRun.status == "running") & (EvalRun.heartbeat_at < now - STALE_AFTER))
            | ((EvalRun.status == "queued") & (EvalRun.created_at < now - QUEUE_STALE_AFTER)),
        )
        .values(
            status="error",
            error="The evaluation worker stopped responding; the run was abandoned.",
            finished_at=now,
            current_scenario=None,
        )
    )
    await session.commit()
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


async def create_run(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    *,
    mode: str,
    version: int | None,
    kind: str,
    value: str | None,
    requested_by: str,
    rerun_of: uuid.UUID | None = None,
) -> EvalRun:
    avail = availability()[mode]
    if not avail.available:
        raise EvalError(409, "mode_unavailable", avail.reason or "This mode is not available.")
    suite = load_suite()
    try:
        chosen = [s for s in select_scenarios(suite, Selection(kind, value)) if mode in s.modes]
    except ScenarioError as e:
        raise EvalError(422, "invalid_selection", "; ".join(e.problems)) from None
    if not chosen:
        raise EvalError(
            422, "invalid_selection", "No scenario in that selection supports this mode."
        )

    q = select(ConfigVersion).where(ConfigVersion.clinic_id == clinic_id)
    q = (
        q.where(ConfigVersion.version == version)
        if version
        else q.order_by(ConfigVersion.version.desc()).limit(1)
    )
    cv = await session.scalar(q)
    if cv is None:
        raise EvalError(
            404 if version else 409,
            "version_not_found" if version else "not_published",
            "That configuration version does not exist."
            if version
            else "Publish a configuration before running an evaluation.",
        )

    await sweep_stale(session, clinic_id)
    # Serialize concurrent submissions for one clinic, then check for an active run.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"eval:{clinic_id}"}
    )
    active = await session.scalar(
        select(EvalRun.id).where(
            EvalRun.clinic_id == clinic_id, EvalRun.status.in_(("queued", "running"))
        )
    )
    if active is not None:
        await session.rollback()
        raise EvalError(409, "run_in_progress", "An evaluation is already running for this clinic.")
    run = EvalRun(
        clinic_id=clinic_id,
        config_version_id=cv.id,
        config_version=cv.version,
        config_hash=config_hash(cv.snapshot),
        mode=mode,
        status="queued",
        selection={"kind": kind, "value": value, "total": len(chosen)},
        rerun_of=rerun_of,
        suite_hash=suite_hash(suite),
        runner_version=RUNNER_VERSION,
        runner_info={},
        counts={},
        requested_by=requested_by,
    )
    session.add(run)
    await session.commit()
    return run


async def request_cancel(session: AsyncSession, run: EvalRun) -> EvalRun:
    now = datetime.now(UTC)
    if run.status == "queued":
        await session.execute(
            update(EvalRun)
            .where(EvalRun.id == run.id, EvalRun.status == "queued")
            .values(
                status="cancelled", finished_at=now, cancel_requested_at=now, error="Cancelled."
            )
        )
    elif run.status == "running":
        await session.execute(
            update(EvalRun)
            .where(EvalRun.id == run.id, EvalRun.status == "running")
            .values(cancel_requested_at=now)
        )
    await session.commit()
    await session.refresh(run)
    return run


async def launch(run: EvalRun, launcher: Launcher, session: AsyncSession) -> None:
    try:
        await launcher(run.id)
    except Exception as e:  # noqa: BLE001
        log.error("evaluation worker could not start: %s", type(e).__name__)
        await session.execute(
            update(EvalRun)
            .where(EvalRun.id == run.id, EvalRun.status == "queued")
            .values(
                status="error",
                error="The evaluation worker could not be started.",
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()
        await session.refresh(run)
