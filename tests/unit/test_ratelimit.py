import pytest

from music_metadata.sources.ratelimit import TokenBucket


class FakeClock:
  """a clock the test drives, so a 20/min limit is testable in milliseconds."""

  def __init__(self):
    self.t = 0.0
    self.slept = []

  def now(self):
    return self.t

  def sleep(self, seconds):
    self.slept.append(seconds)
    self.t += seconds


@pytest.fixture
def clock():
  return FakeClock()


def bucket(clock, per_minute=20):
  return TokenBucket(per_minute, now=clock.now, sleep=clock.sleep)


def test_the_first_twenty_calls_do_not_wait(clock):
  """F8: 20 req/min is the ceiling; the burst up to it must be free."""
  b = bucket(clock)

  for _ in range(20):
    b.take()

  assert clock.slept == []


def test_the_twenty_first_call_waits(clock):
  b = bucket(clock)
  for _ in range(20):
    b.take()

  b.take()

  assert clock.slept, "the 21st call inside a minute must block"


def test_it_waits_only_long_enough_for_one_token(clock):
  b = bucket(clock)
  for _ in range(20):
    b.take()

  b.take()

  # one token at 20/min refills every 3 seconds.
  assert clock.slept[0] == pytest.approx(3.0, abs=0.01)


def test_tokens_refill_over_time(clock):
  b = bucket(clock)
  for _ in range(20):
    b.take()

  clock.t += 60.0
  for _ in range(20):
    b.take()

  assert clock.slept == []


def test_a_partial_wait_refills_partially(clock):
  b = bucket(clock)
  for _ in range(20):
    b.take()

  clock.t += 6.0  # two tokens' worth
  b.take()
  b.take()

  assert clock.slept == []


def test_the_bucket_never_exceeds_its_capacity(clock):
  """idling for an hour must not buy an hour's worth of burst."""
  b = bucket(clock)
  clock.t += 3600.0

  for _ in range(20):
    b.take()
  b.take()

  assert clock.slept, "capacity is the per-minute rate, not unbounded credit"


def test_the_rate_is_configurable(clock):
  """musicbrainz is 1 req/s, not 20 req/min (SPEC.md §5a step 2)."""
  b = bucket(clock, per_minute=60)

  for _ in range(60):
    b.take()
  b.take()

  assert clock.slept[0] == pytest.approx(1.0, abs=0.01)


def test_a_non_positive_rate_is_rejected(clock):
  with pytest.raises(ValueError, match="positive"):
    bucket(clock, per_minute=0)
