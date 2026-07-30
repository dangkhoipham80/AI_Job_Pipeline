"""Polite jittered rate limiting between requests (PLAN §5.1: 2–5s + jitter)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable


class RateLimiter:
    """Sleep a jittered delay in ``[low, high]`` seconds before each request.

    ``sleep`` and ``rng`` are injectable so tests run instantly and
    deterministically. A non-positive ``high`` disables waiting entirely.
    """

    def __init__(
        self,
        low: float = 2.0,
        high: float = 5.0,
        *,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.low = low
        self.high = high
        self._sleep = sleep
        self._rng = rng or random.Random()

    def wait(self) -> float:
        """Block for a random delay; returns the seconds waited (0 if disabled)."""
        if self.high <= 0:
            return 0.0
        delay = self._rng.uniform(self.low, self.high)
        self._sleep(delay)
        return delay
