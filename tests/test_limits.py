"""Tests for the per-day run cap (`app/limits.py`)."""

from __future__ import annotations

import threading

from app.limits import DailyRunLimiter


class TestTryAcquire:
    def test_allows_up_to_the_cap_then_refuses(self):
        limiter = DailyRunLimiter(max_per_day=3)
        assert [limiter.try_acquire() for _ in range(4)] == [True, True, True, False]

    def test_a_zero_cap_refuses_everything(self):
        assert DailyRunLimiter(max_per_day=0).try_acquire() is False


class TestRelease:
    def test_release_returns_a_slot(self):
        limiter = DailyRunLimiter(max_per_day=1)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False
        limiter.release()
        assert limiter.try_acquire() is True

    def test_release_never_goes_negative(self):
        limiter = DailyRunLimiter(max_per_day=2)
        for _ in range(5):
            limiter.release()
        assert limiter.remaining == 2


class TestRemaining:
    def test_counts_down_and_floors_at_zero(self):
        limiter = DailyRunLimiter(max_per_day=2)
        assert limiter.remaining == 2
        limiter.try_acquire()
        assert limiter.remaining == 1
        limiter.try_acquire()
        assert limiter.remaining == 0
        limiter.try_acquire()
        assert limiter.remaining == 0


class TestDayRollover:
    def test_the_counter_resets_when_the_utc_day_changes(self, monkeypatch):
        limiter = DailyRunLimiter(max_per_day=1)
        monkeypatch.setattr(DailyRunLimiter, "_today", staticmethod(lambda: "2026-01-01"))
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False

        monkeypatch.setattr(DailyRunLimiter, "_today", staticmethod(lambda: "2026-01-02"))
        assert limiter.try_acquire() is True

    def test_today_is_an_iso_date(self):
        today = DailyRunLimiter._today()
        assert len(today) == 10
        assert today.count("-") == 2


class TestThreadSafety:
    def test_concurrent_acquires_never_exceed_the_cap(self):
        """The lock exists to make this true; without it the count can overshoot."""
        limiter = DailyRunLimiter(max_per_day=50)
        granted: list[bool] = []
        lock = threading.Lock()

        def worker():
            got = limiter.try_acquire()
            with lock:
                granted.append(got)

        threads = [threading.Thread(target=worker) for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(granted) == 50
        assert limiter.remaining == 0
