"""Deployment API (M5): the simulated-live active pointer for a clinic.

Eligibility is computed on the server from the M4 evaluation evidence. The request bodies accept
no readiness, force or override field (`extra="forbid"`)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.deploy import service
from app.deploy.service import DeployError
from app.models import Clinic
from app.schemas.ops import (
    DeploymentAssessment,
    DeploymentEventDetail,
    DeploymentEventRead,
    DeploymentRead,
    DeploymentState,
    PromoteIn,
    RollbackIn,
)

router = APIRouter(tags=["deployments"])
Db = Annotated[AsyncSession, Depends(get_session)]


def _http(e: DeployError) -> HTTPException:
    return HTTPException(e.status, e.detail())


async def _clinic(session: AsyncSession, clinic_id: uuid.UUID) -> Clinic:
    clinic = await session.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(404, {"code": "clinic_not_found", "message": "Clinic not found."})
    return clinic


@router.get("/clinics/{clinic_id}/deployment", response_model=DeploymentState)
async def current(clinic_id: uuid.UUID, session: Db) -> DeploymentState:
    return await service.state(session, await _clinic(session, clinic_id))


@router.get("/clinics/{clinic_id}/deployment/history", response_model=list[DeploymentEventRead])
async def history(
    clinic_id: uuid.UUID, session: Db, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[DeploymentEventRead]:
    await _clinic(session, clinic_id)
    return await service.history(session, clinic_id, limit)


@router.get(
    "/clinics/{clinic_id}/deployment/events/{event_id}", response_model=DeploymentEventDetail
)
async def event(clinic_id: uuid.UUID, event_id: uuid.UUID, session: Db) -> DeploymentEventDetail:
    await _clinic(session, clinic_id)
    detail = await service.event_detail(session, clinic_id, event_id)
    if detail is None:
        raise HTTPException(
            404, {"code": "event_not_found", "message": "Deployment event not found."}
        )
    return detail


@router.get("/clinics/{clinic_id}/deployment/readiness", response_model=DeploymentAssessment)
async def readiness(
    clinic_id: uuid.UUID,
    session: Db,
    config_version: Annotated[int, Query(ge=1)],
    action: Annotated[str, Query(pattern="^(promote|rollback)$")] = "promote",
) -> DeploymentAssessment:
    clinic = await _clinic(session, clinic_id)
    try:
        out = await service.assess(
            session, clinic, config_version, action, get_settings(), datetime.now(UTC)
        )
    except DeployError as e:
        raise _http(e) from e
    await session.commit()  # sweep_stale may have marked dead runs
    return out


@router.post("/clinics/{clinic_id}/deployment/promote", response_model=DeploymentRead)
async def promote(
    clinic_id: uuid.UUID, body: PromoteIn, session: Db, response: Response
) -> DeploymentRead:
    await _clinic(session, clinic_id)
    try:
        dep, _, replay = await service.promote(
            session,
            clinic_id,
            body.config_version,
            body.expected_active_version,
            body.idempotency_key,
            get_settings(),
            datetime.now(UTC),
        )
    except DeployError as e:
        await session.rollback()
        raise _http(e) from e
    response.status_code = 200 if replay else 201
    return service.to_read(dep)


@router.post("/clinics/{clinic_id}/deployment/rollback", response_model=DeploymentRead)
async def rollback(
    clinic_id: uuid.UUID, body: RollbackIn, session: Db, response: Response
) -> DeploymentRead:
    await _clinic(session, clinic_id)
    try:
        dep, _, replay = await service.rollback(
            session,
            clinic_id,
            body.target_version,
            body.expected_active_version,
            body.idempotency_key,
            get_settings(),
            datetime.now(UTC),
        )
    except DeployError as e:
        await session.rollback()
        raise _http(e) from e
    response.status_code = 200 if replay else 201
    return service.to_read(dep)
