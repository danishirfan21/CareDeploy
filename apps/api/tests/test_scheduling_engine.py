"""Pure rule tests: operating hours, time zones, DST, overlap semantics, lifecycle."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.scheduling import engine
from app.scheduling.engine import ClinicRules, Slot
from app.scheduling.errors import PolicyViolation
from app.schemas.clinic import SchedulingPolicyConfig

CHICAGO = ZoneInfo("America/Chicago")
DENVER = ZoneInfo("America/Denver")


def rules(tz: ZoneInfo, hours: dict[int, tuple[str, str]], **policy: object) -> ClinicRules:
    base = {
        "min_notice_hours": 0,
        "max_advance_days": 365,
        "same_day_booking": True,
        "cancellation_window_hours": 0,
        "reschedule_window_hours": 0,
        "max_reschedules": 2,
    }
    return ClinicRules(
        version=1,
        tz=tz,
        hours={d: (time.fromisoformat(o), time.fromisoformat(c)) for d, (o, c) in hours.items()},
        policy=SchedulingPolicyConfig(**{**base, **policy}),  # type: ignore[arg-type]
    )


WEEKDAYS_9_5 = {d: ("09:00", "17:00") for d in range(5)}
NOW = datetime(2026, 2, 20, 12, 0, tzinfo=UTC)  # a Friday


def violation(r: ClinicRules, minutes: int, start: datetime, now: datetime = NOW) -> str | None:
    try:
        engine.check_slot(r, minutes, start, now)
    except PolicyViolation as e:
        return e.rule
    return None


def local(tz: ZoneInfo, y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=tz).astimezone(UTC)


def test_valid_slot_inside_hours() -> None:
    r = rules(CHICAGO, WEEKDAYS_9_5)
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 9, 0)) is None  # Monday
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 16, 30)) is None  # ends exactly at close


def test_closed_day_and_outside_hours() -> None:
    r = rules(CHICAGO, WEEKDAYS_9_5)
    assert violation(r, 30, local(CHICAGO, 2026, 2, 28, 10)) == "closed_day"  # Saturday
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 8, 45)) == "outside_operating_hours"
    # spans the closing boundary: starts inside, ends after close
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 16, 45)) == "outside_operating_hours"
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 17, 0)) == "outside_operating_hours"


def test_slot_must_sit_on_the_grid() -> None:
    r = rules(CHICAGO, WEEKDAYS_9_5)
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 9, 10)) == "invalid_slot_start"


def test_past_and_now_are_rejected() -> None:
    r = rules(CHICAGO, WEEKDAYS_9_5)
    assert violation(r, 30, local(CHICAGO, 2026, 2, 16, 10)) == "appointment_in_past"
    assert violation(r, 30, NOW) == "appointment_in_past"


def test_same_instant_differs_per_clinic_time_zone() -> None:
    chicago = rules(CHICAGO, WEEKDAYS_9_5)
    denver = rules(DENVER, {d: ("10:00", "18:00") for d in range(1, 6)})
    instant = datetime(2026, 3, 3, 15, 0, tzinfo=UTC)  # Tue 09:00 Chicago / 08:00 Denver
    assert violation(chicago, 30, instant, NOW) is None
    assert violation(denver, 30, instant, NOW) == "outside_operating_hours"


def test_policy_notice_same_day_and_horizon() -> None:
    r = rules(CHICAGO, WEEKDAYS_9_5, min_notice_hours=4, max_advance_days=10)
    now = local(CHICAGO, 2026, 2, 23, 9, 0)
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 12, 0), now) == "minimum_notice"
    assert violation(r, 30, local(CHICAGO, 2026, 2, 23, 13, 0), now) is None
    assert violation(r, 30, local(CHICAGO, 2026, 3, 9, 10, 0), now) == "max_advance"
    no_same_day = rules(CHICAGO, WEEKDAYS_9_5, same_day_booking=False)
    assert (
        violation(no_same_day, 30, local(CHICAGO, 2026, 2, 23, 15, 0), now)
        == "same_day_not_allowed"
    )
    assert violation(no_same_day, 30, local(CHICAGO, 2026, 2, 24, 9, 0), now) is None


def test_half_open_overlap_allows_back_to_back() -> None:
    t = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
    a = Slot(t, t + timedelta(minutes=30))
    assert not engine.overlaps(a, Slot(a.end, a.end + timedelta(minutes=30)))
    assert not engine.overlaps(Slot(a.start - timedelta(minutes=30), a.start), a)
    assert engine.overlaps(a, Slot(a.start + timedelta(minutes=15), a.end + timedelta(minutes=15)))
    assert engine.overlaps(a, Slot(a.start, a.end))  # identical


def test_list_slots_respects_busy_and_durations() -> None:
    r = rules(CHICAGO, {0: ("09:00", "10:00")})
    monday = date(2026, 2, 23)
    busy = [Slot(local(CHICAGO, 2026, 2, 23, 9, 0), local(CHICAGO, 2026, 2, 23, 9, 30))]
    slots, truncated = engine.list_slots(r, 30, monday, monday, NOW, busy, 100)
    starts = [s.start.astimezone(CHICAGO).strftime("%H:%M") for s in slots]
    assert starts == ["09:30"]  # back-to-back after the busy slot is allowed; 09:15 overlaps
    assert not truncated
    slots45, _ = engine.list_slots(r, 45, monday, monday, NOW, [], 100)
    assert [s.start.astimezone(CHICAGO).strftime("%H:%M") for s in slots45] == ["09:00", "09:15"]
    assert all(s.end - s.start == timedelta(minutes=45) for s in slots45)


def test_list_slots_is_bounded() -> None:
    r = rules(CHICAGO, WEEKDAYS_9_5)
    first = date(2026, 2, 23)
    slots, truncated = engine.list_slots(r, 15, first, first + timedelta(days=4), NOW, [], 10)
    assert len(slots) == 10 and truncated
    with pytest.raises(ValueError):
        engine.list_slots(r, 15, first, first + timedelta(days=engine.MAX_RANGE_DAYS), NOW, [], 10)


def test_dst_spring_forward_day_is_two_real_hours() -> None:
    # Sunday 2026-03-08: 02:00 CST jumps to 03:00 CDT. Open 01:00-04:00 wall clock = 2 real hours.
    r = rules(CHICAGO, {6: ("01:00", "04:00")})
    day = date(2026, 3, 8)
    window = engine.day_window(r, day)
    assert window is not None
    assert window.end - window.start == timedelta(hours=2)
    slots, _ = engine.list_slots(r, 30, day, day, NOW, [], 100)
    assert len(slots) == 7  # 01:00 CST .. 03:30 CDT, every 15 minutes, 30-minute appointments
    # No offered appointment starts in the nonexistent 02:00-02:59 local hour.
    assert all(s.start.astimezone(CHICAGO).hour != 2 for s in slots)
    assert slots[-1].end.astimezone(CHICAGO).strftime("%H:%M") == "04:00"


def test_dst_fall_back_day_is_four_real_hours_and_ambiguous_time_is_unambiguous() -> None:
    # Sunday 2026-11-01: 02:00 CDT falls back to 01:00 CST, so 01:00-02:00 happens twice.
    r = rules(CHICAGO, {6: ("00:30", "03:30")})
    day = date(2026, 11, 1)
    window = engine.day_window(r, day)
    assert window is not None
    assert window.end - window.start == timedelta(hours=4)
    slots, _ = engine.list_slots(r, 30, day, day, NOW, [], 100)
    assert len(slots) == 15
    ambiguous = [s for s in slots if s.start.astimezone(CHICAGO).strftime("%H:%M") == "01:30"]
    assert len(ambiguous) == 2  # both occurrences, distinguishable by UTC instant / offset
    offsets = {s.start.astimezone(CHICAGO).utcoffset() for s in ambiguous}
    assert offsets == {timedelta(hours=-5), timedelta(hours=-6)}
    # A booking request is an unambiguous instant, so each can be validated on its own.
    for s in ambiguous:
        assert violation(r, 30, s.start) is None


def test_booking_after_the_dst_boundary_uses_the_new_offset() -> None:
    r = rules(CHICAGO, WEEKDAYS_9_5)
    # Monday 2026-03-09 09:00 local is CDT (UTC-5) = 14:00Z; the old CST instant (15:00Z) is 10:00.
    assert violation(r, 30, datetime(2026, 3, 9, 14, 0, tzinfo=UTC)) is None
    assert violation(r, 30, datetime(2026, 3, 9, 13, 45, tzinfo=UTC)) == "outside_operating_hours"


def test_lifecycle_transitions() -> None:
    assert engine.check_transition("scheduled", "cancelled")
    assert engine.check_transition("scheduled", "completed")
    for src in ("cancelled", "completed"):
        for dst in ("scheduled", "cancelled", "completed"):
            assert not engine.check_transition(src, dst)
    assert not engine.check_transition("scheduled", "scheduled")
