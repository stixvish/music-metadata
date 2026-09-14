"""a token bucket, because every source here has a ceiling worth respecting.

F8 measured the practical limit at 20 req/min. §9a's promise — that a re-run
costs no API calls — only matters because the first run is slow: 1,494 tracks
at 20/min is over an hour, and burning quota on a careless re-run is expensive.

the bucket is shared per source, not per call site, so the whole process stays
under one ceiling.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

_SECONDS_PER_MINUTE = 60.0


class TokenBucket:
  """allows a burst up to the per-minute rate, then paces to it."""

  def __init__(
    self,
    per_minute: int,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
  ) -> None:
    """Build a bucket.

    Args:
      per_minute: sustained requests per minute. Also the burst capacity.
      now: monotonic clock, injectable so tests need not wait a real minute.
      sleep: blocking sleep, injectable for the same reason.

    Raises:
      ValueError: if `per_minute` is not positive.
    """
    if per_minute <= 0:
      msg = f"per_minute must be positive, got {per_minute}"
      raise ValueError(msg)
    self.per_minute = per_minute
    self._interval = _SECONDS_PER_MINUTE / per_minute
    self._now = now
    self._sleep = sleep
    self._lock = threading.Lock()
    # capacity is the per-minute rate: idling does not buy unbounded credit,
    # or a resumed run would slam the api with an hour's saved-up burst.
    self._tokens = float(per_minute)
    self._last = now()

  def take(self) -> None:
    """Consume one token, blocking until one is available."""
    with self._lock:
      self._refill()
      if self._tokens < 1.0:
        wait = (1.0 - self._tokens) * self._interval
        self._sleep(wait)
        self._refill()
      self._tokens -= 1.0

  def _refill(self) -> None:
    """Add the tokens earned since the last check, capped at capacity."""
    current = self._now()
    earned = (current - self._last) / self._interval
    self._last = current
    self._tokens = min(float(self.per_minute), self._tokens + earned)
