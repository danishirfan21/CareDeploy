"""Shared API contracts. The frontend mirrors these in apps/web/src/lib/api/types.ts."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str = "caredeploy-api"
    version: str


class DbHealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: bool
