"""A tiny in-memory per-day run counter.

Bounds worst-case daily API spend when the app is exposed on a public URL: once
`max_runs_per_day` research runs have happened on a given UTC day, further runs
are refused until the next day.

Caveats (acceptable for a small test deployment):
  - State lives in this process only. A restart / redeploy resets the count, and
    multiple worker processes each keep their own counter.
  - The *guaranteed* spending cap is the Anthropic Console monthly spend limit;
    this counter is a lighter, best-effort backstop on top of that.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone


class DailyRunLimiter:
    """Thread-safe counter of successful runs, keyed by UTC date."""

    def __init__(self, max_per_day: int) -> None:
        self.max_per_day = max_per_day
        self._lock = threading.Lock()
        self._date: str = ""
        self._count: int = 0

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_over(self) -> None:
        """Reset the counter when the UTC day changes. Caller holds the lock."""
        today = self._today()
        if today != self._date:
            self._date = today
            self._count = 0

    def try_acquire(self) -> bool:
        """Reserve one run for today. Returns False if today's cap is reached."""
        with self._lock:
            self._roll_over()
            if self._count >= self.max_per_day:
                return False
            self._count += 1
            return True

    def release(self) -> None:
        """Give back a reservation (e.g. when the run failed and wasn't billed)."""
        with self._lock:
            self._roll_over()
            if self._count > 0:
                self._count -= 1

    @property
    def remaining(self) -> int:
        with self._lock:
            self._roll_over()
            return max(0, self.max_per_day - self._count)
