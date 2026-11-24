"""Shared builders for unit tests. Contexts here are small hand-written sample configurations."""

import uuid
from datetime import UTC, datetime
from typing import Any

from voice_agent.contracts import CallContext


def make_ctx(
    name: str = "Sample Clinic A",
    agent: str = "Ada",
    capabilities: list[str] | None = None,
    intents: list[str] | None = None,
    types: list[dict[str, Any]] | None = None,
    greeting: str = "Hello from the sample clinic.",
) -> CallContext:
    return CallContext.model_validate(
        {
            "call_session_id": str(uuid.uuid4()),
            "clinic_id": str(uuid.uuid4()),
            "config_version": 3,
            "room_name": "call-x",
            "created_at": datetime(2026, 3, 2, 15, 0, tzinfo=UTC).isoformat(),
            "config": {
                "details": {
                    "name": name,
                    "specialty": "Family medicine",
                    "location": "1 Sample Way",
                    "timezone": "America/Chicago",
                    "phone": "555-0100",
                },
                "hours": [{"weekday": 0, "opens": "09:00", "closes": "17:00"}],
                "appointment_types": types
                or [
                    {"id": str(uuid.uuid4()), "name": "Checkup", "duration_minutes": 30},
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Procedure",
                        "duration_minutes": 60,
                        "requires_human_escalation": True,
                    },
                ],
                "policy": {
                    "min_notice_hours": 2,
                    "max_advance_days": 60,
                    "same_day_booking": True,
                    "cancellation_window_hours": 24,
                    "cancellation_notes": "",
                    "reschedule_window_hours": 12,
                    "max_reschedules": 2,
                },
                "agent": {
                    "agent_name": agent,
                    "greeting": greeting,
                    "supported_intents": intents
                    if intents is not None
                    else ["book_appointment", "clinic_information", "speak_to_human"],
                    "escalation_instructions": "Send urgent matters to the front desk.",
                    "allowed_capabilities": capabilities
                    if capabilities is not None
                    else ["check_availability", "book_appointment", "escalate_to_human"],
                },
            },
        }
    )
