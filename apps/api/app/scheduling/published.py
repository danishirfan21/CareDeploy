"""Load the clinic's latest *published* configuration. Drafts never affect scheduling."""

import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Clinic, ConfigVersion
from app.scheduling.engine import ClinicRules, TypeInfo
from app.scheduling.errors import ClinicNotConfigured, NotFound
from app.schemas.clinic import ClinicConfig


@dataclass(frozen=True)
class PublishedConfig:
    clinic_id: uuid.UUID
    rules: ClinicRules
    types: dict[uuid.UUID, TypeInfo]


async def ensure_clinic(session: AsyncSession, clinic_id: uuid.UUID) -> Clinic:
    clinic = await session.get(Clinic, clinic_id)
    if clinic is None:
        raise NotFound("Clinic not found.")
    return clinic


async def load_published(session: AsyncSession, clinic_id: uuid.UUID) -> PublishedConfig:
    await ensure_clinic(session, clinic_id)
    version = await session.scalar(
        select(ConfigVersion)
        .where(ConfigVersion.clinic_id == clinic_id)
        .order_by(ConfigVersion.version.desc())
        .limit(1)
    )
    if version is None:
        raise ClinicNotConfigured("This clinic has no published configuration.")
    config = ClinicConfig.model_validate(version.snapshot)
    if any(t.id is None for t in config.appointment_types):
        raise ClinicNotConfigured(
            "The published version predates stable appointment-type ids; publish a new version."
        )
    rules = ClinicRules(
        version=version.version,
        tz=ZoneInfo(config.details.timezone),
        hours={h.weekday: (h.opens, h.closes) for h in config.hours},
        policy=config.policy,
    )
    types = {
        t.id: TypeInfo(t.id, t.name, t.duration_minutes, t.requires_human_escalation)
        for t in config.appointment_types
        if t.id is not None
    }
    return PublishedConfig(clinic_id, rules, types)
