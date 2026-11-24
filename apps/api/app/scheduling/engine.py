"""Pure scheduling rules. No database access, no clock: `now` is always passed in.

All instants are timezone-aware. A clinic's operating day is converted to a UTC interval once
(`day_window`), and every later comparison is done on UTC instants, so DST shifts change the
*elapsed* length of a day correctly instead of being mishandled by wall-clock arithmetic.

DST rules (documented in docs/scheduling.md):
- A local time that does not exist (spring-forward gap) resolves with the pre-transition offset,
  i.e. it is shifted forward by the gap.
- A local time that occurs twice (fall-back) resolves to its first occurrence.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.scheduling.errors import PolicyViolation
from app.schemas.clinic import SchedulingPolicyConfig

SLOT_STEP_MINUTES: Final = 15
MAX_RANGE_DAYS: Final = 14

ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "scheduled": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


@dataclass(frozen=True)
class TypeInfo:
    id: uuid.UUID
    name: str
    duration_minutes: int
    requires_human_escalation: bool


@dataclass(frozen=True)
class ClinicRules:
    """The scheduling-relevant slice of one *published* configuration version."""

    version: int
    tz: ZoneInfo
    hours: dict[int, tuple[time, time]]
    policy: SchedulingPolicyConfig

    @property
    def timezone_name(self) -> str:
        return self.tz.key


@dataclass(frozen=True)
class Slot:
    start: datetime  # UTC
    end: datetime  # UTC


def local_to_utc(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def day_window(rules: ClinicRules, day: date) -> Slot | None:
    """Operating window of a local calendar day as a UTC interval, or None if closed."""
    hours = rules.hours.get(day.weekday())
    if hours is None:
        return None
    return Slot(local_to_utc(day, hours[0], rules.tz), local_to_utc(day, hours[1], rules.tz))


def local_date(instant: datetime, tz: ZoneInfo) -> date:
    return instant.astimezone(tz).date()


def overlaps(a: Slot, b: Slot) -> bool:
    """Half-open intervals [start, end): back-to-back slots do not overlap."""
    return a.start < b.end and b.start < a.end


def check_slot(rules: ClinicRules, duration_minutes: int, start: datetime, now: datetime) -> None:
    """Raise PolicyViolation unless a new appointment may start at `start` under these rules."""
    if start.tzinfo is None or now.tzinfo is None:
        raise ValueError("naive datetimes are not allowed")
    start = start.astimezone(UTC)
    end = start + timedelta(minutes=duration_minutes)
    policy, tz = rules.policy, rules.tz

    if start <= now:
        raise PolicyViolation("appointment_in_past", "The requested time is in the past.")

    window = day_window(rules, local_date(start, tz))
    if window is None:
        raise PolicyViolation("closed_day", "The clinic is closed on that day.")
    if start < window.start or end > window.end:
        raise PolicyViolation(
            "outside_operating_hours",
            "The appointment must fit entirely within the clinic's operating hours.",
        )
    offset_min = (start - window.start).total_seconds() / 60
    if offset_min % SLOT_STEP_MINUTES != 0:
        raise PolicyViolation(
            "invalid_slot_start",
            f"Appointments start on {SLOT_STEP_MINUTES}-minute boundaries from opening time.",
        )

    today = local_date(now, tz)
    start_day = local_date(start, tz)
    if not policy.same_day_booking and start_day == today:
        raise PolicyViolation("same_day_not_allowed", "Same-day booking is not available.")
    if start < now + timedelta(hours=policy.min_notice_hours):
        raise PolicyViolation(
            "minimum_notice",
            f"Appointments need at least {policy.min_notice_hours} hours' notice.",
            min_notice_hours=policy.min_notice_hours,
        )
    if start_day > today + timedelta(days=policy.max_advance_days):
        raise PolicyViolation(
            "max_advance",
            f"Appointments can be booked at most {policy.max_advance_days} days ahead.",
            max_advance_days=policy.max_advance_days,
        )


def list_slots(
    rules: ClinicRules,
    duration_minutes: int,
    first_day: date,
    last_day: date,
    now: datetime,
    busy: list[Slot],
    limit: int,
) -> tuple[list[Slot], bool]:
    """Open slots for local dates [first_day, last_day]. Returns (slots, truncated)."""
    if last_day < first_day:
        raise ValueError("last_day before first_day")
    if (last_day - first_day).days + 1 > MAX_RANGE_DAYS:
        raise ValueError("range too large")
    step = timedelta(minutes=SLOT_STEP_MINUTES)
    length = timedelta(minutes=duration_minutes)
    out: list[Slot] = []
    day = first_day
    while day <= last_day:
        window = day_window(rules, day)
        if window is not None:
            start = window.start
            while start + length <= window.end:
                cand = Slot(start, start + length)
                try:
                    check_slot(rules, duration_minutes, cand.start, now)
                except PolicyViolation:
                    pass
                else:
                    if not any(overlaps(cand, b) for b in busy):
                        if len(out) >= limit:
                            return out, True
                        out.append(cand)
                start += step
        day += timedelta(days=1)
    return out, False


def check_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())
