import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app import __version__
from app.api import clinics, health, scheduling, voice
from app.config import get_settings
from app.scheduling.errors import DependencyUnavailable, SchedulingError

logger = logging.getLogger("caredeploy")
_SCHEDULING_PATH = re.compile(
    r"^/api/clinics/[^/]+/(patients|availability|scheduling|appointments|proposals|operations)"
)


def _error_response(err: SchedulingError) -> JSONResponse:
    return JSONResponse(err.body(), status_code=err.status_code, headers=err.headers)


def create_app() -> FastAPI:
    app = FastAPI(title="CareDeploy API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(clinics.router, prefix="/api")
    app.include_router(scheduling.router, prefix="/api")
    app.include_router(voice.router, prefix="/api")

    @app.exception_handler(SchedulingError)
    async def _scheduling_error(request: Request, exc: SchedulingError) -> JSONResponse:
        logger.info("scheduling.rejected code=%s path=%s", exc.code, request.url.path)
        return _error_response(exc)

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        # Never leak database details to clients.
        logger.error("database error path=%s type=%s", request.url.path, type(exc.orig).__name__)
        return _error_response(
            DependencyUnavailable(
                "A dependency is temporarily unavailable.", headers={"Retry-After": "1"}
            )
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        if not _SCHEDULING_PATH.match(request.url.path):
            from fastapi.exception_handlers import request_validation_exception_handler

            return await request_validation_exception_handler(request, exc)
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_input",
                    "message": "Invalid request.",
                    "details": {"errors": errors},
                }
            },
            status_code=422,
        )

    return app


app = create_app()
