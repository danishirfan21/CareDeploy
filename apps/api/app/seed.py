"""Seed two sample clinics. Idempotent: existing clinics (by name) are left untouched.

Usage: python -m app.seed [--publish]

--publish also publishes each seeded clinic's configuration (required before scheduling works).
Sample patients are always seeded.
"""

import asyncio
import sys
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_engine
from app.models import Clinic, Patient
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


# Sample patients. Verification (simulated): date of birth + last 4 digits of phone.
PATIENTS: dict[str, list[tuple[str, date, str, str]]] = {
    "Northstar Family Medicine": [
        ("Avery Quinn", date(1985, 4, 12), "(512) 555-0101", "avery.quinn@example.test"),
        ("Jordan Ellis", date(1990, 9, 30), "(512) 555-0102", "jordan.ellis@example.test"),
        ("Morgan Reyes", date(1978, 1, 22), "(512) 555-0103", "morgan.reyes@example.test"),
    ],
    "Lakeside Dermatology": [
        ("Casey Nakamura", date(1992, 6, 15), "(303) 555-0201", "casey.nakamura@example.test"),
        ("Riley Okafor", date(1988, 11, 3), "(303) 555-0202", "riley.okafor@example.test"),
        ("Sam Whitfield", date(1975, 2, 8), "(303) 555-0203", "sam.whitfield@example.test"),
    ],
}


async def seed_patients(session: AsyncSession) -> int:
    added = 0
    for clinic_name, people in PATIENTS.items():
        clinic_id = await session.scalar(select(Clinic.id).where(Clinic.name == clinic_name))
        if clinic_id is None:
            continue
        for name, dob, phone, email in people:
            exists = await session.scalar(
                select(Patient.id).where(Patient.clinic_id == clinic_id, Patient.full_name == name)
            )
            if exists is None:
                session.add(
                    Patient(
                        clinic_id=clinic_id,
                        full_name=name,
                        date_of_birth=dob,
                        phone=phone,
                        email=email,
                    )
                )
                added += 1
    await session.flush()
    return added


async def publish_seeded(session: AsyncSession) -> list[str]:
    published: list[str] = []
    for config in (NORTHSTAR, LAKESIDE):
        clinic = await session.scalar(select(Clinic).where(Clinic.name == config.details.name))
        if clinic is None:
            continue
        try:
            await svc.publish(session, clinic)
            published.append(config.details.name)
        except svc.ConfigNotChangedError:
            pass
    return published


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
    await seed_patients(session)
    await session.commit()
    return created


async def main() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = get_engine()
    async with async_sessionmaker(engine)() as session:
        created = await seed(session)
        published: list[str] = []
        if "--publish" in sys.argv:
            published = await publish_seeded(session)
            await session.commit()
    await engine.dispose()
    print(f"Seeded: {', '.join(created) if created else 'nothing (already present)'}")
    if "--publish" in sys.argv:
        print(f"Published: {', '.join(published) if published else 'nothing (already published)'}")


if __name__ == "__main__":
    asyncio.run(main())
