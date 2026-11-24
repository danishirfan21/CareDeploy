import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentConfig,
    AppointmentType,
    Clinic,
    ConfigVersion,
    OperatingHours,
    SchedulingPolicy,
)
from app.schemas.clinic import (
    INTENT_REQUIRES_CAPABILITY,
    AgentBehavior,
    AppointmentTypeEntry,
    ClinicConfig,
    ClinicDetails,
    ClinicRead,
    OperatingHoursEntry,
    SchedulingPolicyConfig,
    ValidationIssue,
    ValidationResult,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ConfigNotChangedError(Exception):
    """Publishing would duplicate the latest published version."""


class UnknownAppointmentTypeError(ValueError):
    """The draft references an appointment-type id that does not belong to this clinic."""


class ConfigInvalidError(Exception):
    def __init__(self, result: ValidationResult) -> None:
        super().__init__("Configuration is not valid for publishing")
        self.result = result


async def get_clinic(session: AsyncSession, clinic_id: uuid.UUID) -> Clinic | None:
    return await session.get(Clinic, clinic_id)


def details_of(clinic: Clinic) -> ClinicDetails:
    return ClinicDetails(
        name=clinic.name,
        specialty=clinic.specialty,
        location=clinic.location,
        timezone=clinic.timezone,
        phone=clinic.phone,
        email=clinic.email,
    )


def clinic_read(clinic: Clinic, latest_version: int | None) -> ClinicRead:
    return ClinicRead(
        **details_of(clinic).model_dump(),
        id=clinic.id,
        created_at=clinic.created_at,
        updated_at=clinic.updated_at,
        latest_version=latest_version,
    )


async def latest_versions(session: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(ConfigVersion.clinic_id, func.max(ConfigVersion.version)).group_by(
            ConfigVersion.clinic_id
        )
    )
    return {cid: v for cid, v in rows.all()}


async def latest_version(session: AsyncSession, clinic_id: uuid.UUID) -> ConfigVersion | None:
    return await session.scalar(
        select(ConfigVersion)
        .where(ConfigVersion.clinic_id == clinic_id)
        .order_by(ConfigVersion.version.desc())
        .limit(1)
    )


async def build_config(session: AsyncSession, clinic: Clinic) -> ClinicConfig:
    hours = (
        await session.scalars(
            select(OperatingHours)
            .where(OperatingHours.clinic_id == clinic.id)
            .order_by(OperatingHours.weekday)
        )
    ).all()
    types = (
        await session.scalars(
            select(AppointmentType)
            .where(AppointmentType.clinic_id == clinic.id, AppointmentType.archived_at.is_(None))
            .order_by(AppointmentType.position)
        )
    ).all()
    policy = await session.scalar(
        select(SchedulingPolicy).where(SchedulingPolicy.clinic_id == clinic.id)
    )
    agent = await session.scalar(select(AgentConfig).where(AgentConfig.clinic_id == clinic.id))
    return ClinicConfig(
        details=details_of(clinic),
        hours=[
            OperatingHoursEntry(weekday=h.weekday, opens=h.opens, closes=h.closes) for h in hours
        ],
        appointment_types=[
            AppointmentTypeEntry(
                id=t.id,
                name=t.name,
                duration_minutes=t.duration_minutes,
                requires_human_escalation=t.requires_human_escalation,
                constraints=t.constraints,
            )
            for t in types
        ],
        policy=SchedulingPolicyConfig.model_validate(policy, from_attributes=True)
        if policy
        else SchedulingPolicyConfig(),
        agent=AgentBehavior(
            agent_name=agent.agent_name,
            greeting=agent.greeting,
            supported_intents=agent.supported_intents,  # type: ignore[arg-type]
            escalation_instructions=agent.escalation_instructions,
            allowed_capabilities=agent.allowed_capabilities,  # type: ignore[arg-type]
        )
        if agent
        else AgentBehavior(),
    )


async def save_config(session: AsyncSession, clinic: Clinic, config: ClinicConfig) -> None:
    """Replace the clinic's draft configuration. Every row is scoped to `clinic.id`."""
    d = config.details
    clinic.name, clinic.specialty, clinic.location = d.name, d.specialty, d.location
    clinic.timezone, clinic.phone, clinic.email = d.timezone, d.phone, d.email

    await session.execute(delete(OperatingHours).where(OperatingHours.clinic_id == clinic.id))
    await session.flush()
    session.add_all(
        OperatingHours(clinic_id=clinic.id, weekday=h.weekday, opens=h.opens, closes=h.closes)
        for h in config.hours
    )
    await _save_types(session, clinic, config)

    policy = await session.scalar(
        select(SchedulingPolicy).where(SchedulingPolicy.clinic_id == clinic.id)
    )
    if policy is None:
        policy = SchedulingPolicy(clinic_id=clinic.id, **config.policy.model_dump())
        session.add(policy)
    else:
        for k, v in config.policy.model_dump().items():
            setattr(policy, k, v)

    agent = await session.scalar(select(AgentConfig).where(AgentConfig.clinic_id == clinic.id))
    if agent is None:
        session.add(AgentConfig(clinic_id=clinic.id, **config.agent.model_dump()))
    else:
        for k, v in config.agent.model_dump().items():
            setattr(agent, k, v)
    await session.flush()


async def _save_types(session: AsyncSession, clinic: Clinic, config: ClinicConfig) -> None:
    """Upsert by stable id. Types removed from the draft are archived, never deleted, so
    published versions and appointments keep a valid reference."""
    existing = {
        t.id: t
        for t in (
            await session.scalars(
                select(AppointmentType).where(AppointmentType.clinic_id == clinic.id)
            )
        ).all()
    }
    keep: set[uuid.UUID] = set()
    for entry in config.appointment_types:
        if entry.id is not None and entry.id not in existing:
            raise UnknownAppointmentTypeError(f"Unknown appointment type id {entry.id}")
        if entry.id is not None:
            keep.add(entry.id)

    # Archive removed types first (frees their names), then rename/update, then insert.
    now = datetime.now(UTC)
    for tid, row in existing.items():
        if tid not in keep and row.archived_at is None:
            row.archived_at = now
    await session.flush()
    # Park retained rows on unique placeholder names so renames/swaps cannot collide mid-flush.
    retained = [existing[i] for i in keep]
    for row in retained:
        row.archived_at = None
        row.name = f"~{row.id}"
    await session.flush()
    fields = {"name", "duration_minutes", "requires_human_escalation", "constraints"}
    for pos, entry in enumerate(config.appointment_types):
        data = entry.model_dump(include=fields)
        if entry.id is not None:
            row = existing[entry.id]
            for k, v in data.items():
                setattr(row, k, v)
            row.position = pos
        else:
            session.add(AppointmentType(clinic_id=clinic.id, position=pos, **data))
    await session.flush()


def _strip_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = {**snapshot}
    out["appointment_types"] = [
        {k: v for k, v in t.items() if k != "id"} for t in snapshot.get("appointment_types", [])
    ]
    return out


def snapshot_has_type_ids(snapshot: dict[str, Any]) -> bool:
    types = snapshot.get("appointment_types", [])
    return all(t.get("id") for t in types)


def same_content(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Compare configurations ignoring appointment-type ids (M1 snapshots predate them)."""
    return _strip_ids(a) == _strip_ids(b)


def snapshot_of(config: ClinicConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")


def validate_config(config: ClinicConfig) -> ValidationResult:
    """Publish-readiness checks. Structural checks already ran in the Pydantic models."""
    issues: list[ValidationIssue] = []

    def err(section: str, msg: str) -> None:
        issues.append(ValidationIssue(severity="error", section=section, message=msg))  # type: ignore[arg-type]

    def warn(section: str, msg: str) -> None:
        issues.append(ValidationIssue(severity="warning", section=section, message=msg))  # type: ignore[arg-type]

    if not config.details.phone and not config.details.email:
        warn("details", "No phone or email: the agent has no contact details to share.")

    if not config.hours:
        err("hours", "Select at least one operating day.")
    longest = (
        max(
            ((h.closes.hour * 60 + h.closes.minute) - (h.opens.hour * 60 + h.opens.minute))
            for h in config.hours
        )
        if config.hours
        else 0
    )

    if not config.appointment_types:
        err("services", "Add at least one appointment type.")
    for t in config.appointment_types:
        if config.hours and t.duration_minutes > longest:
            err(
                "services",
                f"'{t.name}' ({t.duration_minutes} min) is longer than any operating day.",
            )

    p, a = config.policy, config.agent
    if p.max_reschedules == 0 and "reschedule_appointment" in a.supported_intents:
        err("policy", "Rescheduling is a supported intent but the policy allows 0 reschedules.")
    if not p.same_day_booking and p.min_notice_hours == 0:
        warn("policy", "Same-day booking is off, so a minimum notice of 0 hours has no effect.")

    if not a.agent_name.strip():
        err("agent", "Give the agent a name.")
    if not a.greeting.strip():
        err("agent", "Write a greeting.")
    if not a.supported_intents:
        err("agent", "Select at least one supported intent.")
    if not a.allowed_capabilities:
        err("agent", "Select at least one allowed capability.")
    for intent in a.supported_intents:
        needed = INTENT_REQUIRES_CAPABILITY.get(intent)
        if needed and needed not in a.allowed_capabilities:
            err("agent", f"Intent '{intent}' needs the '{needed}' capability.")
    if any(t.requires_human_escalation for t in config.appointment_types):
        if not a.escalation_instructions.strip():
            err(
                "agent",
                "Some appointment types need human escalation: add escalation instructions.",
            )
        if "escalate_to_human" not in a.allowed_capabilities:
            err("agent", "Some appointment types need human escalation: allow 'escalate_to_human'.")

    return ValidationResult(valid=not any(i.severity == "error" for i in issues), issues=issues)


async def has_unpublished_changes(config: ClinicConfig, latest: ConfigVersion | None) -> bool:
    return latest is None or not same_content(latest.snapshot, snapshot_of(config))


async def publish(session: AsyncSession, clinic: Clinic) -> ConfigVersion:
    # Serialise concurrent publishes for this clinic.
    await session.execute(select(Clinic.id).where(Clinic.id == clinic.id).with_for_update())
    config = await build_config(session, clinic)
    result = validate_config(config)
    if not result.valid:
        raise ConfigInvalidError(result)
    latest = await latest_version(session, clinic.id)
    snapshot = snapshot_of(config)
    if (
        latest is not None
        and same_content(latest.snapshot, snapshot)
        and snapshot_has_type_ids(latest.snapshot)
    ):
        raise ConfigNotChangedError
    version = ConfigVersion(
        clinic_id=clinic.id, version=(latest.version if latest else 0) + 1, snapshot=snapshot
    )
    session.add(version)
    await session.flush()
    await session.refresh(version)
    return version
