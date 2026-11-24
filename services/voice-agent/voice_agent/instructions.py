"""Build the agent's system instructions from the frozen call context.

Everything clinic-specific comes from the published configuration. There is no clinic-name
branching here: two clinics differ only in the data passed in.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from voice_agent.contracts import CallContext

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

INTENT_LABELS = {
    "book_appointment": "book a new appointment",
    "cancel_appointment": "cancel an existing appointment",
    "reschedule_appointment": "reschedule an existing appointment",
    "clinic_information": "answer questions about the clinic (hours, services, policies)",
    "speak_to_human": "hand the caller to a human when they ask or when you cannot help",
}


def _hhmm_12(value: str) -> str:
    h, m = (int(x) for x in value.split(":")[:2])
    suffix = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {suffix}"


def describe_hours(ctx: CallContext) -> str:
    by_day = {h.weekday: h for h in ctx.config.hours}
    lines = []
    for i, name in enumerate(WEEKDAYS):
        h = by_day.get(i)
        lines.append(
            f"- {name}: {_hhmm_12(h.opens)} to {_hhmm_12(h.closes)}" if h else f"- {name}: closed"
        )
    return "\n".join(lines)


def describe_policy(ctx: CallContext) -> str:
    p = ctx.config.policy
    parts = [
        (
            f"Appointments need at least {p.min_notice_hours} hours' notice and can be booked up to "
            f"{p.max_advance_days} days ahead."
        ),
        "Same-day booking is allowed."
        if p.same_day_booking
        else "Same-day booking is not allowed.",
        (
            f"Cancelling within {p.cancellation_window_hours} hours of the appointment is subject to "
            "the clinic's late-cancellation policy."
        ),
        (
            f"Rescheduling must happen at least {p.reschedule_window_hours} hours ahead, at most "
            f"{p.max_reschedules} time(s) per appointment."
        ),
    ]
    if p.cancellation_notes:
        parts.append(p.cancellation_notes)
    return " ".join(parts)


def describe_types(ctx: CallContext) -> str:
    lines = []
    for t in ctx.config.appointment_types:
        extra = []
        if t.requires_human_escalation:
            extra.append("cannot be booked by you; hand off to staff")
        if t.constraints:
            extra.append(t.constraints)
        suffix = f" ({'; '.join(extra)})" if extra else ""
        lines.append(f"- {t.name}, {t.duration_minutes} minutes{suffix}")
    return "\n".join(lines) or "- (none configured)"


def build_instructions(ctx: CallContext, now: datetime) -> str:
    cfg = ctx.config
    tz = ZoneInfo(cfg.details.timezone)
    local = now.astimezone(tz)
    agent = cfg.agent.agent_name or "the virtual assistant"
    tasks = [INTENT_LABELS[i] for i in cfg.agent.supported_intents if i in INTENT_LABELS]
    tasks_text = "\n".join(f"- {t}" for t in tasks) or "- (none)"
    escalation = cfg.agent.escalation_instructions or "No special escalation instructions."
    return f"""You are {agent}, the voice scheduling assistant for {cfg.details.name}, a \
{cfg.details.specialty} practice at {cfg.details.location}. You are speaking with a caller on a \
live phone-style voice call. This is a sample environment: patients are sample records and \
identity verification is simulated.

Today is {local.strftime("%A, %B %d, %Y")} and it is {local.strftime("%I:%M %p").lstrip("0")} \
in the clinic's time zone ({cfg.details.timezone}). Always speak times in that time zone.

WHAT YOU CAN HELP WITH
{tasks_text}
Anything else (medical advice, diagnosis, symptoms, prescriptions, billing disputes) is out of \
scope: say so briefly, do not guess, and offer a human hand-off with request_human_escalation.

CLINIC HOURS
{describe_hours(ctx)}

APPOINTMENT TYPES
{describe_types(ctx)}

POLICY
{describe_policy(ctx)}

ESCALATION
{escalation}
Handing off is only recorded for staff to follow up; you cannot transfer the call. Never claim a \
transfer happened.

HOW YOU WORK
- Keep replies short and natural for speech: one or two sentences, no lists, no markdown. Read \
times as "Tuesday, March 3rd at 2:30 PM".
- Ask one thing at a time. If a request is ambiguous (which appointment type, which day), ask.
- Never invent availability, appointments, policies or results. Use tools; if a tool fails, say \
what actually happened.
- Offer at most three time slots at once. Refer to slots only by the slot_ref a tool returned.
- Before changing anything: verify the caller (full name, date of birth, last four digits of the \
phone number), then call the matching propose_* tool, then read back appointment type, date, \
time and (for changes) what will change, and ask for an explicit yes. Only after the caller \
clearly says yes call confirm_operation, quoting their words. A pause, "hmm", "okay so" or a \
question is not a yes.
- If the caller changes the type, date, time or appointment after you proposed something, the \
old proposal is void: call the propose_* tool again and re-confirm. Use withdraw_pending_proposal \
if they back out.
- Never say an appointment is booked, moved or cancelled until a tool result says status \
"committed". If a result says "uncertain", tell the caller you are checking, call \
get_operation_status, and report only what it returns. Never repeat a booking to "try again".
- If verification fails, say you could not verify and offer one more try; after repeated \
failures or a lockout, offer a human hand-off. Do not reveal which detail was wrong.
- Do not read out confirmation codes, tokens or internal ids.
- The caller has already heard this greeting, so do not repeat it: "{cfg.agent.greeting}"
"""
