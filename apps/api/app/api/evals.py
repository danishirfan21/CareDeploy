"""Evaluation API (M4). Typed, bounded and read-mostly: clients pick server-side scenarios by id or
category; they cannot submit scenario bodies, code or file paths. Runs execute in a separate worker
process, so none of these handlers blocks on scenario execution."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.evals import analysis
from app.evals.llm import availability
from app.evals.loader import load_suite, suite_hash
from app.evals.schema import CATEGORY_LABELS
from app.evals.service import (
    EvalError,
    Launcher,
    create_run,
    launch,
    request_cancel,
    spawn_worker,
    sweep_stale,
)
from app.evals.store import latest_views, run_view
from app.models import Clinic, ConfigVersion
from app.models.evals import EvalEvent, EvalRun, EvalScenarioResult
from app.schemas.evals import (
    AssertionRead,
    CatalogRead,
    CategoryGroup,
    EventRead,
    ModeInfo,
    RerunCreate,
    ResultDetail,
    ResultSummary,
    RunCreate,
    RunDetail,
    RunSummary,
    ScenarioInfo,
)

router = APIRouter(tags=["evaluations"])
DEV_ACTOR = "local-dev-operator"  # single-operator development limitation (see docs)
Db = Annotated[AsyncSession, Depends(get_session)]


def get_launcher(request: Request) -> Launcher:
    launcher: Launcher | None = getattr(request.app.state, "eval_launcher", None)
    return launcher or spawn_worker


def _http(e: EvalError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message})


async def _clinic(session: AsyncSession, clinic_id: uuid.UUID) -> Clinic:
    clinic = await session.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(404, {"code": "clinic_not_found", "message": "Clinic not found."})
    return clinic


async def _run(session: AsyncSession, clinic_id: uuid.UUID, run_id: uuid.UUID) -> EvalRun:
    run = await session.get(EvalRun, run_id)
    if run is None or run.clinic_id != clinic_id:  # other clinics' runs are indistinguishable
        raise HTTPException(404, {"code": "run_not_found", "message": "Evaluation run not found."})
    return run


def _summary(run: EvalRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        clinic_id=run.clinic_id,
        mode=run.mode,
        mode_label=analysis.MODE_LABELS.get(run.mode, run.mode),
        status=run.status,
        config_version=run.config_version,
        config_hash=run.config_hash,
        selection=run.selection,
        rerun_of=run.rerun_of,
        counts=run.counts or {},
        total=int((run.selection or {}).get("total", 0)),
        current_scenario=run.current_scenario,
        error=run.error,
        requested_by=run.requested_by,
        suite_hash=run.suite_hash,
        runner_version=run.runner_version,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        cancel_requested=run.cancel_requested_at is not None,
    )


def _result_summary(r: EvalScenarioResult) -> ResultSummary:
    return ResultSummary(
        scenario_id=r.scenario_id,
        scenario_version=r.scenario_version,
        name=r.name,
        category=r.category,
        severity=r.severity,
        status=r.status,
        failure=r.failure,
        duration_ms=r.duration_ms,
        not_evaluated=list(r.not_evaluated or []),
    )


# ------------------------------------------------------------------------------- catalog ----
@router.get("/evaluations/scenarios", response_model=CatalogRead, summary="Scenario catalog")
async def catalog() -> CatalogRead:
    suite = load_suite()
    avail = availability()
    return CatalogRead(
        scenarios=[
            ScenarioInfo(
                id=s.id,
                version=s.version,
                name=s.name,
                description=s.description,
                category=s.category,
                severity=s.severity,
                modes=list(s.modes),
                behavior=s.expected.behavior,
                not_evaluated_in_workflow=s.not_evaluated_in_workflow,
            )
            for s in suite
        ],
        categories=[{"id": k, "label": v} for k, v in CATEGORY_LABELS.items()],
        modes=[
            ModeInfo(mode=m, label=analysis.MODE_LABELS[m], available=a.available, reason=a.reason)
            for m, a in avail.items()
        ],
        suite_hash=suite_hash(suite),
    )


# ------------------------------------------------------------------------------- runs -------
@router.get(
    "/clinics/{clinic_id}/evaluations/runs",
    response_model=list[RunSummary],
    summary="List evaluation runs, newest first",
)
async def list_runs(
    clinic_id: uuid.UUID,
    session: Db,
    mode: str | None = Query(default=None, pattern="^(workflow|llm|real_audio)$"),
    config_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
) -> list[RunSummary]:
    await _clinic(session, clinic_id)
    await sweep_stale(session, clinic_id)
    q = select(EvalRun).where(EvalRun.clinic_id == clinic_id)
    if mode:
        q = q.where(EvalRun.mode == mode)
    if config_version:
        q = q.where(EvalRun.config_version == config_version)
    rows = await session.scalars(q.order_by(EvalRun.created_at.desc()).limit(limit))
    return [_summary(r) for r in rows]


@router.post(
    "/clinics/{clinic_id}/evaluations/runs",
    response_model=RunSummary,
    status_code=202,
    summary="Start an evaluation run (executes in a worker process)",
)
async def start_run(
    clinic_id: uuid.UUID,
    body: RunCreate,
    session: Db,
    launcher: Annotated[Launcher, Depends(get_launcher)],
) -> RunSummary:
    await _clinic(session, clinic_id)
    try:
        run = await create_run(
            session,
            clinic_id,
            mode=body.mode,
            version=body.config_version,
            kind=body.selection.kind,
            value=body.selection.value,
            requested_by=DEV_ACTOR,
        )
    except EvalError as e:
        raise _http(e) from None
    await launch(run, launcher, session)
    return _summary(run)


@router.get(
    "/clinics/{clinic_id}/evaluations/runs/{run_id}",
    response_model=RunDetail,
    summary="Run progress and results grouped by category",
)
async def read_run(clinic_id: uuid.UUID, run_id: uuid.UUID, session: Db) -> RunDetail:
    await _clinic(session, clinic_id)
    await sweep_stale(session, clinic_id)
    run = await _run(session, clinic_id, run_id)
    rows = (
        await session.scalars(
            select(EvalScenarioResult)
            .where(EvalScenarioResult.run_id == run.id)
            .order_by(EvalScenarioResult.position)
        )
    ).all()
    groups: list[CategoryGroup] = []
    for cat, label in CATEGORY_LABELS.items():
        items = [r for r in rows if r.category == cat]
        if not items:
            continue
        groups.append(
            CategoryGroup(
                category=cat,
                label=label,
                counts=analysis.count_results([r.status for r in items]),
                results=[_result_summary(r) for r in items],
            )
        )
    return RunDetail(**_summary(run).model_dump(), categories=groups)


@router.get(
    "/clinics/{clinic_id}/evaluations/runs/{run_id}/results/{scenario_id}",
    response_model=ResultDetail,
    summary="One scenario result with assertions, trace and events",
)
async def read_result(
    clinic_id: uuid.UUID, run_id: uuid.UUID, scenario_id: str, session: Db
) -> ResultDetail:
    await _clinic(session, clinic_id)
    run = await _run(session, clinic_id, run_id)
    r = await session.scalar(
        select(EvalScenarioResult).where(
            EvalScenarioResult.run_id == run.id, EvalScenarioResult.scenario_id == scenario_id
        )
    )
    if r is None:
        raise HTTPException(404, {"code": "result_not_found", "message": "Result not found."})
    events = (
        await session.scalars(
            select(EvalEvent).where(EvalEvent.result_id == r.id).order_by(EvalEvent.seq)
        )
    ).all()
    return ResultDetail(
        **_result_summary(r).model_dump(),
        run_id=run.id,
        scenario_hash=r.scenario_hash,
        mode=r.mode,
        expected=r.expected,
        observed=r.observed,
        assertions=[AssertionRead(**a) for a in (r.assertions or [])],
        events=[
            EventRead(
                seq=e.seq, kind=e.kind, actor=e.actor, occurred_at=e.occurred_at, payload=e.payload
            )
            for e in events
        ],
        started_at=r.started_at,
        finished_at=r.finished_at,
    )


@router.post(
    "/clinics/{clinic_id}/evaluations/runs/{run_id}/cancel",
    response_model=RunSummary,
    summary="Request cancellation of a queued or running evaluation",
)
async def cancel_run(clinic_id: uuid.UUID, run_id: uuid.UUID, session: Db) -> RunSummary:
    await _clinic(session, clinic_id)
    run = await _run(session, clinic_id, run_id)
    if run.status not in ("queued", "running"):
        raise HTTPException(409, {"code": "run_finished", "message": "The run already finished."})
    return _summary(await request_cancel(session, run))


@router.post(
    "/clinics/{clinic_id}/evaluations/runs/{run_id}/rerun",
    response_model=RunSummary,
    status_code=202,
    summary="Re-run one scenario of a finished run as a new, linked run",
)
async def rerun(
    clinic_id: uuid.UUID,
    run_id: uuid.UUID,
    body: RerunCreate,
    session: Db,
    launcher: Annotated[Launcher, Depends(get_launcher)],
) -> RunSummary:
    await _clinic(session, clinic_id)
    prior = await _run(session, clinic_id, run_id)
    if prior.status in ("queued", "running"):
        raise HTTPException(409, {"code": "run_active", "message": "The run is still active."})
    # Same configuration version and mode as the original, so the results are comparable.
    try:
        run = await create_run(
            session,
            clinic_id,
            mode=prior.mode,
            version=prior.config_version,
            kind="scenario",
            value=body.scenario_id,
            requested_by=DEV_ACTOR,
            rerun_of=prior.id,
        )
    except EvalError as e:
        raise _http(e) from None
    await launch(run, launcher, session)
    return _summary(run)


# ------------------------------------------------------------------------------- readiness ---
async def _target_version(session: AsyncSession, clinic_id: uuid.UUID, version: int | None) -> int:
    if version is None:
        version = await session.scalar(
            select(func.max(ConfigVersion.version)).where(ConfigVersion.clinic_id == clinic_id)
        )
    if version is None:
        raise HTTPException(
            409, {"code": "not_published", "message": "No published configuration exists."}
        )
    exists = await session.scalar(
        select(ConfigVersion.id).where(
            ConfigVersion.clinic_id == clinic_id, ConfigVersion.version == version
        )
    )
    if exists is None:
        raise HTTPException(404, {"code": "version_not_found", "message": "Version not found."})
    return int(version)


@router.get(
    "/clinics/{clinic_id}/evaluations/readiness",
    summary="Deployment readiness for one published configuration version",
)
async def readiness(
    clinic_id: uuid.UUID, session: Db, config_version: int | None = Query(default=None, ge=1)
) -> dict[str, Any]:
    await _clinic(session, clinic_id)
    await sweep_stale(session, clinic_id)
    version = await _target_version(session, clinic_id, config_version)
    return analysis.compute_readiness(version, await latest_views(session, clinic_id, version))


@router.get(
    "/clinics/{clinic_id}/evaluations/compare",
    summary="Compare two runs of the same mode (regression view)",
)
async def compare(
    clinic_id: uuid.UUID, session: Db, base: uuid.UUID, head: uuid.UUID
) -> dict[str, Any]:
    await _clinic(session, clinic_id)
    await _run(session, clinic_id, base)
    await _run(session, clinic_id, head)
    try:
        return analysis.compare_runs(await run_view(session, base), await run_view(session, head))
    except analysis.IncompatibleRuns as e:
        raise HTTPException(409, {"code": "incompatible_runs", "message": str(e)}) from None
