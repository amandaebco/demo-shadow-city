"""Daily cap on new scenarios, per orchestrator instance (at most two run).

The orchestrator URL is public and every new scenario spends Gemini (and possibly GPU) time.
This is an abuse guard, not exact accounting: the count lives in memory and resets at midnight UTC
or when an instance restarts.
"""

from datetime import datetime, timezone


class DailyQuota:
    def __init__(self, limit: int, clock=lambda: datetime.now(timezone.utc)):
        self._limit = limit
        self._clock = clock
        self._day = None
        self._count = 0

    def try_take(self) -> bool:
        today = self._clock().date()
        if today != self._day:
            self._day, self._count = today, 0
        if self._count >= self._limit:
            return False
        self._count += 1
        return True

    @property
    def limit(self) -> int:
        return self._limit
