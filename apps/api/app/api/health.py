from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db.session import get_session
from app.schemas import DbHealthResponse, HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get("/db", response_model=DbHealthResponse)
async def health_db(
    response: Response, session: AsyncSession = Depends(get_session)
) -> DbHealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return DbHealthResponse(status="unavailable", database=False)
    return DbHealthResponse(status="ok", database=True)
