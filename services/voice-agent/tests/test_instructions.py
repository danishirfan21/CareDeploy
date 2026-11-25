from datetime import UTC, datetime
from pathlib import Path

from tests.helpers import make_ctx
from voice_agent.instructions import build_instructions

NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)


def test_instructions_come_only_from_config() -> None:
    a = build_instructions(make_ctx(name="Sample Clinic A", agent="Ada"), NOW)
    b = build_instructions(
        make_ctx(name="Sample Clinic B", agent="Bo", greeting="Welcome to B."), NOW
    )
    assert "Sample Clinic A" in a and "Ada" in a and "Sample Clinic B" not in a
    assert "Sample Clinic B" in b and "Bo" in b and "Welcome to B." in b
    assert "Monday: 9:00 AM to 5:00 PM" in a and "Tuesday: closed" in a
    assert "Checkup, 30 minutes" in a
    assert "cannot be booked by you" in a
    assert "Send urgent matters to the front desk." in a


def test_date_is_in_clinic_time_zone() -> None:
    text = build_instructions(make_ctx(), NOW)
    assert "Monday, March 02, 2026" in text and "9:00 AM" in text


def test_supported_tasks_follow_configuration() -> None:
    text = build_instructions(make_ctx(intents=["book_appointment"]), NOW)
    assert "book a new appointment" in text
    assert "cancel an existing appointment" not in text


def test_no_clinic_name_branching_in_source() -> None:
    root = Path(__file__).resolve().parents[1] / "voice_agent"
    for path in root.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        for name in ("Northstar", "Lakeside"):
            assert name not in src, f"{name} found in {path.name}"


def _urgent(text: str) -> str:
    start = text.index("URGENT SAFETY")
    return text[start : text.index("ESCALATION", start)]


def test_emergency_guidance_directs_to_emergency_services() -> None:
    # Instruction coverage only. This does not prove what a language model says aloud.
    text = build_instructions(make_ctx(), NOW)
    urgent = _urgent(text)
    assert "911" in urgent and "emergency room" in urgent
    assert "request_human_escalation" in urgent


def test_emergency_guidance_forbids_diagnosis_treatment_and_assumptions() -> None:
    urgent = _urgent(build_instructions(make_ctx(), NOW))
    assert "Do not diagnose" in urgent
    assert "do not give treatment or first-aid instructions" in urgent
    assert "do not assume emergency services have been contacted" in urgent
    assert "Stay administrative" in urgent


def test_emergency_guidance_stops_scheduling_and_avoids_overtriggering() -> None:
    urgent = _urgent(build_instructions(make_ctx(), NOW))
    assert "stop scheduling at once" in urgent
    assert "Do not continue booking, rescheduling or cancelling" in urgent
    assert "Do not treat ordinary questions about appointments or minor concerns" in urgent


def test_no_transfer_or_staff_arrival_is_claimed() -> None:
    text = build_instructions(make_ctx(), NOW)
    assert "you cannot transfer the call" in text
    assert "Never claim a transfer happened or that staff are on their way." in text


def test_emergency_guidance_is_shared_by_every_clinic() -> None:
    a = build_instructions(make_ctx(name="Sample Clinic A"), NOW)
    b = build_instructions(make_ctx(name="Sample Clinic B"), NOW)
    assert _urgent(a) == _urgent(b)
