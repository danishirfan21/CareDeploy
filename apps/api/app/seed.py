"""Seed two fictional clinics. Idempotent: existing clinics (by name) are left untouched.

Usage: python -m app.seed
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_engine
from app.models import Clinic
from app.schemas.clinic import (
    AgentBehavior,
    AppointmentTypeEntry,
    ClinicConfig,
    ClinicDetails,
    OperatingHoursEntry,
    SchedulingPolicyConfig,
)
from app.services import clinics as svc


def _hours(days: range, opens: str, closes: str) -> list[OperatingHoursEntry]:
    return [OperatingHoursEntry(weekday=d, opens=opens, closes=closes) for d in days]  # type: ignore[arg-type]


NORTHSTAR = ClinicConfig(
    details=ClinicDetails(
        name="Northstar Family Medicine",
        specialty="Primary care",
        location="Austin, Texas",
        timezone="America/Chicago",
        phone="(512) 555-0142",
        email="frontdesk@northstar.example",
    ),
    hours=_hours(range(0, 5), "09:00", "17:00"),
    appointment_types=[
        AppointmentTypeEntry(name="Annual physical", duration_minutes=30),
        AppointmentTypeEntry(name="Sick visit", duration_minutes=30),
        AppointmentTypeEntry(
            name="Follow-up visit",
            duration_minutes=30,
            constraints="Existing patients only.",
        ),
    ],
    policy=SchedulingPolicyConfig(
        min_notice_hours=4,
        max_advance_days=60,
        same_day_booking=True,
        cancellation_window_hours=24,
        cancellation_notes="Cancellations inside 24 hours are noted on the patient record.",
        reschedule_window_hours=12,
        max_reschedules=2,
    ),
    agent=AgentBehavior(
        agent_name="Nora",
        greeting="Thank you for calling Northstar Family Medicine. This is Nora. "
        "How can I help you today?",
        supported_intents=[
            "book_appointment",
            "cancel_appointment",
            "reschedule_appointment",
            "clinic_information",
            "speak_to_human",
        ],
        escalation_instructions="Transfer to the front desk for billing questions, "
        "medication refills, or any symptom that sounds urgent.",
        allowed_capabilities=[
            "check_availability",
            "book_appointment",
            "cancel_appointment",
            "reschedule_appointment",
            "escalate_to_human",
        ],
    ),
)

LAKESIDE = ClinicConfig(
    details=ClinicDetails(
        name="Lakeside Dermatology",
        specialty="Dermatology",
        location="Denver, Colorado",
        timezone="America/Denver",
        phone="(303) 555-0187",
        email="appointments@lakeside.example",
    ),
    hours=_hours(range(1, 6), "10:00", "18:00"),
    appointment_types=[
        AppointmentTypeEntry(name="Skin check", duration_minutes=20),
        AppointmentTypeEntry(name="Acne follow-up", duration_minutes=15),
        AppointmentTypeEntry(
            name="Full-body skin exam",
            duration_minutes=45,
            constraints="New patients should arrive 15 minutes early.",
        ),
        AppointmentTypeEntry(
            name="Mohs surgery consultation",
            duration_minutes=60,
            requires_human_escalation=True,
            constraints="Scheduled by clinical staff only.",
        ),
        AppointmentTypeEntry(
            name="Cosmetic laser procedure",
            duration_minutes=60,
            requires_human_escalation=True,
            constraints="Requires a prior consultation.",
        ),
    ],
    policy=SchedulingPolicyConfig(
        min_notice_hours=24,
        max_advance_days=90,
        same_day_booking=False,
        cancellation_window_hours=48,
        cancellation_notes="Procedure appointments require 72 hours notice via staff.",
        reschedule_window_hours=48,
        max_reschedules=1,
    ),
    agent=AgentBehavior(
        agent_name="Skye",
        greeting="Hello, you've reached Lakeside Dermatology. I'm Skye, "
        "the virtual scheduling assistant.",
        supported_intents=[
            "book_appointment",
            "cancel_appointment",
            "reschedule_appointment",
            "speak_to_human",
        ],
        escalation_instructions="Procedures (Mohs surgery, cosmetic laser) are never booked by "
        "the agent. Collect the caller's name and number and hand off to clinical staff. "
        "Hand off immediately if the caller reports a rapidly changing or bleeding lesion.",
        allowed_capabilities=[
            "check_availability",
            "book_appointment",
            "cancel_appointment",
            "reschedule_appointment",
            "escalate_to_human",
        ],
    ),
)


async def seed(session: AsyncSession) -> list[str]:
    created: list[str] = []
    for config in (NORTHSTAR, LAKESIDE):
        exists = await session.scalar(select(Clinic.id).where(Clinic.name == config.details.name))
        if exists:
            continue
        clinic = Clinic(**config.details.model_dump())
        session.add(clinic)
        await session.flush()
        await svc.save_config(session, clinic, config)
        created.append(config.details.name)
    await session.commit()
    return created


async def main() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = get_engine()
    async with async_sessionmaker(engine)() as session:
        created = await seed(session)
    await engine.dispose()
    print(f"Seeded: {', '.join(created) if created else 'nothing (already present)'}")


if __name__ == "__main__":
    asyncio.run(main())
