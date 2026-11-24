"""LLM-facing tool definitions, generated from the same pydantic models that validate calls.

Only tools the clinic's published configuration allows are exposed, so the model cannot even
attempt a capability the clinic has not enabled (the Toolbox enforces it again regardless).
"""

from typing import Any

from voice_agent.contracts import CallContext
from voice_agent.tools import _SPECS, CAPABILITY_FOR_TOOL

DESCRIPTIONS = {
    "get_clinic_information": "Look up the clinic's hours, services, policies, location or contact "
    "details from its published configuration. Use for general questions.",
    "get_appointment_availability": "Find open appointment times for an appointment type from a "
    "start date. Returns slot_ref values to use when proposing a booking or reschedule.",
    "verify_patient": "Verify the caller before any appointment lookup or change. Needs the "
    "caller's full name, date of birth and last four digits of their phone number.",
    "get_patient_appointments": "List the verified caller's upcoming appointments as "
    "appointment_ref values.",
    "propose_booking": "Prepare (not commit) a new appointment in an offered slot. Then read the "
    "details back and ask the caller for an explicit yes.",
    "propose_reschedule": "Prepare (not commit) moving an existing appointment to an offered slot "
    "of the same type. Read back and ask for an explicit yes.",
    "propose_cancellation": "Prepare (not commit) cancelling an existing appointment. Read back "
    "and ask for an explicit yes.",
    "confirm_operation": "Commit the pending proposal. Only after the caller explicitly said yes "
    "AFTER hearing the details; pass their exact words in caller_words.",
    "get_operation_status": "Check what actually happened to a change whose outcome was reported "
    "as uncertain.",
    "withdraw_pending_proposal": "Discard the pending proposal because the caller changed their "
    "mind or wants different details. Nothing is changed.",
    "request_human_escalation": "Record a hand-off request for clinic staff when the caller asks "
    "for a person, the request is out of scope (clinical questions), or the type cannot be booked "
    "by the agent. This does not transfer the call.",
}


def exposed_tool_schemas(ctx: CallContext) -> list[dict[str, Any]]:
    out = []
    for name, (model, _method) in _SPECS.items():
        cap = CAPABILITY_FOR_TOOL.get(name)
        if cap and not ctx.can(cap):
            continue
        if name == "get_clinic_information" and not ctx.supports("clinic_information"):
            continue
        schema = model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        schema.setdefault("properties", {})
        out.append({"name": name, "description": DESCRIPTIONS[name], "parameters": schema})
    return out
