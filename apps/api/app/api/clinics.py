import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Clinic, ConfigVersion
from app.schemas.clinic import (
    ClinicConfig,
    ClinicDetails,
    ClinicRead,
    ClinicUpdate,
    ConfigResponse,
    ConfigVersionRead,
    ConfigVersionSummary,
    ErrorResponse,
    ValidationResult,
)
from app.services import clinics as svc

router = APIRouter(prefix="/clinics", tags=["clinics"])

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Clinic not found"}
}
CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorResponse, "description": "Conflict"}
}
Session = Depends(get_session)


async def _clinic(session: AsyncSession, clinic_id: uuid.UUID) -> Clinic:
    clinic = await svc.get_clinic(session, clinic_id)
    if clinic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinic not found")
    return clinic


def _duplicate_name() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "A clinic with this name already exists")


@router.get("", response_model=list[ClinicRead], summary="List clinics")
async def list_clinics(session: AsyncSession = Session) -> list[ClinicRead]:
    clinics = (await session.scalars(select(Clinic).order_by(Clinic.created_at, Clinic.name))).all()
    versions = await svc.latest_versions(session)
    return [svc.clinic_read(c, versions.get(c.id)) for c in clinics]


@router.post(
    "",
    response_model=ClinicRead,
    status_code=status.HTTP_201_CREATED,
    responses=CONFLICT,
    summary="Create a clinic",
)
async def create_clinic(body: ClinicDetails, session: AsyncSession = Session) -> ClinicRead:
    clinic = Clinic(**body.model_dump())
    session.add(clinic)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_name() from None
    await session.refresh(clinic)
    return svc.clinic_read(clinic, None)


@router.get("/{clinic_id}", response_model=ClinicRead, responses=NOT_FOUND, summary="Get a clinic")
async def get_clinic(clinic_id: uuid.UUID, session: AsyncSession = Session) -> ClinicRead:
    clinic = await _clinic(session, clinic_id)
    latest = await svc.latest_version(session, clinic_id)
    return svc.clinic_read(clinic, latest.version if latest else None)


@router.patch(
    "/{clinic_id}",
    response_model=ClinicRead,
    responses={**NOT_FOUND, **CONFLICT},
    summary="Update clinic details",
)
async def update_clinic(
    clinic_id: uuid.UUID, body: ClinicUpdate, session: AsyncSession = Session
) -> ClinicRead:
    clinic = await _clinic(session, clinic_id)
    merged = {**svc.details_of(clinic).model_dump(), **body.model_dump(exclude_unset=True)}
    try:
        details = ClinicDetails(**merged)  # re-validates timezone, email, required fields
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    for k, v in details.model_dump().items():
        setattr(clinic, k, v)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_name() from None
    await session.refresh(clinic)
    latest = await svc.latest_version(session, clinic_id)
    return svc.clinic_read(clinic, latest.version if latest else None)


@router.get(
    "/{clinic_id}/config",
    response_model=ConfigResponse,
    responses=NOT_FOUND,
    summary="Read the configuration draft",
)
async def read_config(clinic_id: uuid.UUID, session: AsyncSession = Session) -> ConfigResponse:
    clinic = await _clinic(session, clinic_id)
    config = await svc.build_config(session, clinic)
    latest = await svc.latest_version(session, clinic_id)
    return ConfigResponse(
        clinic_id=clinic_id,
        config=config,
        latest_version=latest.version if latest else None,
        has_unpublished_changes=await svc.has_unpublished_changes(config, latest),
    )


@router.put(
    "/{clinic_id}/config",
    response_model=ConfigResponse,
    responses={**NOT_FOUND, **CONFLICT},
    summary="Replace the configuration draft",
)
async def update_config(
    clinic_id: uuid.UUID, body: ClinicConfig, session: AsyncSession = Session
) -> ConfigResponse:
    clinic = await _clinic(session, clinic_id)
    try:
        await svc.save_config(session, clinic, body)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_name() from None
    return await read_config(clinic_id, session)


@router.post(
    "/{clinic_id}/config/validate",
    response_model=ValidationResult,
    responses=NOT_FOUND,
    summary="Validate the saved draft for publishing",
)
async def validate_config(
    clinic_id: uuid.UUID, session: AsyncSession = Session
) -> ValidationResult:
    clinic = await _clinic(session, clinic_id)
    return svc.validate_config(await svc.build_config(session, clinic))


@router.post(
    "/{clinic_id}/config/publish",
    response_model=ConfigVersionRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        **NOT_FOUND,
        **CONFLICT,
        422: {"model": ValidationResult, "description": "Draft is not valid for publishing"},
    },
    summary="Publish the saved draft as a new immutable version",
)
async def publish_config(
    clinic_id: uuid.UUID, session: AsyncSession = Session
) -> ConfigVersionRead:
    clinic = await _clinic(session, clinic_id)
    try:
        version = await svc.publish(session, clinic)
        await session.commit()
    except svc.ConfigInvalidError as e:
        await session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, e.result.model_dump(mode="json")
        ) from None
    except svc.ConfigNotChangedError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No changes since the latest published version"
        ) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Concurrent publish; retry") from None
    return _version_read(version)


def _version_read(v: ConfigVersion) -> ConfigVersionRead:
    return ConfigVersionRead(
        clinic_id=v.clinic_id,
        version=v.version,
        published_at=v.published_at,
        config=ClinicConfig.model_validate(v.snapshot),
    )


@router.get(
    "/{clinic_id}/versions",
    response_model=list[ConfigVersionSummary],
    responses=NOT_FOUND,
    summary="List published versions, newest first",
)
async def list_versions(
    clinic_id: uuid.UUID, session: AsyncSession = Session
) -> list[ConfigVersionSummary]:
    await _clinic(session, clinic_id)
    rows = await session.scalars(
        select(ConfigVersion)
        .where(ConfigVersion.clinic_id == clinic_id)
        .order_by(ConfigVersion.version.desc())
    )
    return [ConfigVersionSummary(version=v.version, published_at=v.published_at) for v in rows]


@router.get(
    "/{clinic_id}/versions/{version}",
    response_model=ConfigVersionRead,
    responses=NOT_FOUND,
    summary="Read one published version",
)
async def read_version(
    clinic_id: uuid.UUID, version: int, session: AsyncSession = Session
) -> ConfigVersionRead:
    await _clinic(session, clinic_id)
    v = await session.scalar(
        select(ConfigVersion).where(
            ConfigVersion.clinic_id == clinic_id, ConfigVersion.version == version
        )
    )
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return _version_read(v)
