"""Call operations API (M5): clinic-scoped call history, call detail and aggregate metrics.

Every route is scoped by clinic id in the path; a call that belongs to another clinic is reported
as not found. Paths avoid `/operations/` because that prefix belongs to the scheduling ledger."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.models import Clinic
from app.ops import calls, metrics
from app.ops.pricing import load_rates
from app.schemas.ops import CallDetail, CallList, MetricsOut

router = APIRouter(tags=["call operations"])
Db = Annotated[AsyncSession, Depends(get_session)]

OutcomeFilter = Literal[
    "completed", "escalated", "failed", "abandoned", "interrupted", "unknown", "in_progress"
]


async def _clinic(session: AsyncSession, clinic_id: uuid.UUID) -> Clinic:
    clinic = await session.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(404, {"code": "clinic_not_found", "message": "Clinic not found."})
    return clinic


def _check_range(start: date | None, end: date | None) -> None:
    if start and end and start > end:
        raise HTTPException(
            422, {"code": "invalid_range", "message": "The start date is after the end date."}
        )


@router.get("/clinics/{clinic_id}/calls", response_model=CallList)
async def list_calls(
    clinic_id: uuid.UUID,
    session: Db,
    outcome: OutcomeFilter | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> CallList:
    clinic = await _clinic(session, clinic_id)
    _check_range(date_from, date_to)
    out = await calls.list_calls(
        session,
        clinic,
        outcome=outcome,
        date_from=date_from,
        date_to=date_to,
        q=(q or "").strip() or None,
        limit=limit,
        offset=offset,
    )
    await session.commit()
    return out


@router.get("/clinics/{clinic_id}/calls/{session_id}", response_model=CallDetail)
async def get_call(
    clinic_id: uuid.UUID,
    session_id: uuid.UUID,
    session: Db,
    settings: Settings = Depends(get_settings),
) -> CallDetail:
    clinic = await _clinic(session, clinic_id)
    detail = await calls.call_detail(
        session, clinic, session_id, load_rates(settings.cost_rates_file)
    )
    if detail is None:
        raise HTTPException(404, {"code": "call_not_found", "message": "Call not found."})
    return detail


@router.get("/clinics/{clinic_id}/call-metrics", response_model=MetricsOut)
async def call_metrics(
    clinic_id: uuid.UUID,
    session: Db,
    date_from: date | None = None,
    date_to: date | None = None,
    settings: Settings = Depends(get_settings),
) -> MetricsOut:
    clinic = await _clinic(session, clinic_id)
    _check_range(date_from, date_to)
    now = datetime.now(UTC)
    zone = calls.zone_of(clinic)
    today = now.astimezone(zone).date()
    end = date_to or today
    start = date_from or (end - timedelta(days=29))
    if start > end:
        raise HTTPException(
            422, {"code": "invalid_range", "message": "The start date is after the end date."}
        )
    if (end - start).days > 366:
        raise HTTPException(
            422, {"code": "range_too_large", "message": "Choose a range of at most one year."}
        )
    out = await metrics.compute(
        session, clinic, start, end, load_rates(settings.cost_rates_file), now
    )
    await session.commit()
    return out
