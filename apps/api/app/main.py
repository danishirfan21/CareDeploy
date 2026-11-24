from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import clinics, health
from app.config import get_settings


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
    return app


app = create_app()
