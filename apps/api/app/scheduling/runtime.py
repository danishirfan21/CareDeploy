"""Injectable runtime collaborators: the clock and the (test-only) fault hooks."""

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    return system_clock


class Faults:
    """No-op fault hooks. Tests override `get_faults` with a subclass that raises at a point.

    Points: "after_claim", "in_work", "before_commit", "after_commit".
    """

    async def hit(self, point: str) -> None:
        return None


def get_faults() -> Faults:
    return Faults()
