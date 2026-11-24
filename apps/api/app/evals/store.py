"""Persistence for evaluation runs.

The runner owns a *separate* engine pointed at the results database. The application engine
(`app.db.session`) is re-pointed at a scenario database while a scenario executes, so results must
never be written through it.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.evals.analysis import ResultView, RunView
from app.models import ConfigVersion
from app.models.evals import TERMINAL_RUN_STATUSES, EvalEvent, EvalRun, EvalScenarioResult


def now() -> datetime:
    return datetime.now(UTC)


def config_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


def jsonable(value: Any) -> Any:
    """Round-trip through JSON so anything stored is plain, serializable data."""
    return json.loads(json.dumps(value, default=str))


class ResultsStore:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    # ---------------------------------------------------------------- run lifecycle ---------
    async def load_run(self, run_id: uuid.UUID) -> EvalRun:
        async with self.maker() as s:
            run = await s.get(EvalRun, run_id)
        if run is None:
            raise LookupError(f"evaluation run {run_id} not found")
        return run

    async def load_version(self, version_id: uuid.UUID) -> ConfigVersion:
        async with self.maker() as s:
            cv = await s.get(ConfigVersion, version_id)
        if cv is None:
            raise LookupError("configuration version not found")
        return cv

    async def start(self, run_id: uuid.UUID, runner_info: dict[str, Any]) -> bool:
        """queued -> running. False when the run is no longer queued (e.g. cancelled)."""
        async with self.maker() as s:
            res = await s.execute(
                update(EvalRun)
                .where(EvalRun.id == run_id, EvalRun.status == "queued")
                .values(
                    status="running",
                    started_at=now(),
                    heartbeat_at=now(),
                    runner_info=jsonable(runner_info),
                )
            )
            await s.commit()
        return bool(res.rowcount)  # type: ignore[attr-defined]

    async def progress(
        self, run_id: uuid.UUID, current: str | None, counts: dict[str, int]
    ) -> None:
        async with self.maker() as s:
            await s.execute(
                update(EvalRun)
                .where(EvalRun.id == run_id, EvalRun.status == "running")
                .values(current_scenario=current, counts=counts, heartbeat_at=now())
            )
            await s.commit()

    async def heartbeat(self, run_id: uuid.UUID) -> None:
        async with self.maker() as s:
            await s.execute(
                update(EvalRun)
                .where(EvalRun.id == run_id, EvalRun.status == "running")
                .values(heartbeat_at=now())
            )
            await s.commit()

    async def cancel_requested(self, run_id: uuid.UUID) -> bool:
        async with self.maker() as s:
            at = await s.scalar(select(EvalRun.cancel_requested_at).where(EvalRun.id == run_id))
        return at is not None

    async def add_result(
        self, run_id: uuid.UUID, row: dict[str, Any], events: Iterable[dict[str, Any]]
    ) -> None:
        async with self.maker() as s:
            result = EvalScenarioResult(run_id=run_id, **row)
            s.add(result)
            await s.flush()
            for seq, e in enumerate(events):
                occurred = e.get("occurred_at")
                if isinstance(occurred, str):
                    try:
                        occurred = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
                    except ValueError:
                        occurred = None
                s.add(
                    EvalEvent(
                        result_id=result.id,
                        seq=seq,
                        kind=str(e.get("kind", "event"))[:20],
                        actor=str(e.get("actor", "caller"))[:30],
                        occurred_at=occurred if isinstance(occurred, datetime) else None,
                        payload=jsonable(e.get("payload", {})),
                    )
                )
            await s.commit()

    async def finish(
        self,
        run_id: uuid.UUID,
        status: str,
        counts: dict[str, int],
        readiness: dict[str, Any] | None,
        error: str | None = None,
    ) -> None:
        assert status in TERMINAL_RUN_STATUSES
        async with self.maker() as s:
            await s.execute(
                update(EvalRun)
                .where(EvalRun.id == run_id, EvalRun.status.in_(("queued", "running")))
                .values(
                    status=status,
                    counts=counts,
                    readiness=jsonable(readiness) if readiness is not None else None,
                    error=error[:2000] if error else None,
                    current_scenario=None,
                    finished_at=now(),
                )
            )
            await s.commit()

    # ---------------------------------------------------------------- views -------------------
    async def run_view(self, run_id: uuid.UUID) -> RunView:
        async with self.maker() as s:
            return await run_view(s, run_id)

    async def latest_views(self, clinic_id: uuid.UUID, version: int) -> dict[str, RunView | None]:
        async with self.maker() as s:
            return await latest_views(s, clinic_id, version)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def view_of(run: EvalRun, results: Iterable[EvalScenarioResult]) -> RunView:
    return RunView(
        id=str(run.id),
        clinic_id=str(run.clinic_id),
        config_version=run.config_version,
        mode=run.mode,
        status=run.status,
        selection_kind=str((run.selection or {}).get("kind", "all")),
        suite_hash=run.suite_hash,
        results=tuple(
            ResultView(
                scenario_id=r.scenario_id,
                name=r.name,
                category=r.category,
                severity=r.severity,
                status=r.status,
                scenario_hash=r.scenario_hash,
                scenario_version=r.scenario_version,
            )
            for r in sorted(results, key=lambda x: (x.position, x.scenario_id))
        ),
        runner_info=dict(run.runner_info or {}),
        finished_at=_iso(run.finished_at),
    )


async def run_view(session: AsyncSession, run_id: uuid.UUID) -> RunView:
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise LookupError(f"evaluation run {run_id} not found")
    rows = (
        await session.scalars(select(EvalScenarioResult).where(EvalScenarioResult.run_id == run_id))
    ).all()
    return view_of(run, rows)


async def latest_views(
    session: AsyncSession, clinic_id: uuid.UUID, version: int
) -> dict[str, RunView | None]:
    """Newest terminal run per mode for one configuration version. The run being finalized is
    included by the caller after its own status is written, so this reads terminal rows only."""
    out: dict[str, RunView | None] = {}
    for mode in ("workflow", "llm"):
        run = await session.scalar(
            select(EvalRun)
            .where(
                EvalRun.clinic_id == clinic_id,
                EvalRun.config_version == version,
                EvalRun.mode == mode,
                EvalRun.status.in_(TERMINAL_RUN_STATUSES),
                EvalRun.status != "cancelled",
            )
            .order_by(EvalRun.finished_at.desc())
            .limit(1)
        )
        out[mode] = await run_view(session, run.id) if run else None
    return out
