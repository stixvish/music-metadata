import httpx
import pytest

from music_metadata.sources.base import Source, SourceError
from music_metadata.sources.ratelimit import TokenBucket


class FakeClock:
  def __init__(self):
    self.t = 0.0
    self.slept = []

  def now(self):
    return self.t

  def sleep(self, seconds):
    self.slept.append(seconds)
    self.t += seconds


def make_source(handler, **kw):
  clock = FakeClock()
  src = Source(
    name="fake",
    base_url="https://api.example.test",
    bucket=TokenBucket(20, now=clock.now, sleep=clock.sleep),
    transport=httpx.MockTransport(handler),
    sleep=clock.sleep,
    **kw,
  )
  src.clock = clock
  return src


def test_get_json_returns_the_decoded_body():
  src = make_source(lambda r: httpx.Response(200, json={"ok": True}))

  assert src.get_json("/thing") == {"ok": True}


def test_the_base_url_is_joined():
  seen = {}

  def handler(request):
    seen["url"] = str(request.url)
    return httpx.Response(200, json={})

  make_source(handler).get_json("/v1/search")

  assert seen["url"] == "https://api.example.test/v1/search"


def test_params_are_sent():
  seen = {}

  def handler(request):
    seen["q"] = request.url.params.get("q")
    return httpx.Response(200, json={})

  make_source(handler).get_json("/search", params={"q": "isrc:USJI10000001"})

  assert seen["q"] == "isrc:USJI10000001"


def test_every_request_carries_a_timeout():
  """ruff's S rules exist for this: a request with no timeout can hang forever."""
  seen = {}

  def handler(request):
    seen["timeout"] = request.extensions.get("timeout")
    return httpx.Response(200, json={})

  make_source(handler).get_json("/x")

  assert seen["timeout"] is not None
  assert seen["timeout"]["read"] is not None


def test_headers_are_sent():
  seen = {}

  def handler(request):
    seen["auth"] = request.headers.get("authorization")
    return httpx.Response(200, json={})

  make_source(handler, headers={"authorization": "Bearer t"}).get_json("/x")

  assert seen["auth"] == "Bearer t"


def test_the_rate_limiter_is_consulted():
  calls = []
  src = make_source(lambda r: httpx.Response(200, json={}))

  for _ in range(21):
    src.get_json("/x")
  calls = src.clock.slept

  assert calls, "the 21st call in a minute must have been paced"


def test_a_404_returns_none_rather_than_raising():
  """a miss is a normal outcome — zero beatport results is not a failure."""
  src = make_source(lambda r: httpx.Response(404))

  assert src.get_json("/missing") is None


def test_a_500_is_retried_then_raises():
  attempts = []

  def handler(request):
    attempts.append(1)
    return httpx.Response(500)

  src = make_source(handler, retries=3)

  with pytest.raises(SourceError, match="500"):
    src.get_json("/x")
  assert len(attempts) == 3


def test_a_500_that_recovers_is_returned():
  attempts = []

  def handler(request):
    attempts.append(1)
    if len(attempts) < 3:
      return httpx.Response(503)
    return httpx.Response(200, json={"recovered": True})

  src = make_source(handler, retries=3)

  assert src.get_json("/x") == {"recovered": True}


def test_a_429_is_retried():
  """musicbrainz answers 'currently busy' under load; that is not a miss (F30)."""
  attempts = []

  def handler(request):
    attempts.append(1)
    if len(attempts) == 1:
      return httpx.Response(429, headers={"retry-after": "2"})
    return httpx.Response(200, json={"ok": 1})

  src = make_source(handler, retries=3)

  assert src.get_json("/x") == {"ok": 1}
  assert src.clock.slept, "a 429 must back off before retrying"


def test_retry_after_is_honoured():
  attempts = []

  def handler(request):
    attempts.append(1)
    if len(attempts) == 1:
      return httpx.Response(429, headers={"retry-after": "7"})
    return httpx.Response(200, json={})

  src = make_source(handler, retries=3)
  src.get_json("/x")

  assert 7.0 in src.clock.slept


def test_a_4xx_that_is_not_404_raises():
  src = make_source(lambda r: httpx.Response(401))

  with pytest.raises(SourceError, match="401"):
    src.get_json("/x")


def test_a_non_json_body_raises():
  src = make_source(lambda r: httpx.Response(200, text="<html>nope</html>"))

  with pytest.raises(SourceError, match="JSON"):
    src.get_json("/x")


def test_a_transport_error_is_retried_then_wrapped():
  attempts = []

  def handler(request):
    attempts.append(1)
    raise httpx.ConnectError("boom")

  src = make_source(handler, retries=2)

  with pytest.raises(SourceError):
    src.get_json("/x")
  assert len(attempts) == 2


def test_an_absurd_retry_after_is_capped():
  """a service asking for an hour parks a 1,494-track run on one track.

  this is the bug that stalled a full pass: the main thread sat in
  `time.sleep` with zero CPU and no open connections, indefinitely.
  """
  from music_metadata.sources.base import MAX_RETRY_AFTER_S

  attempts = []

  def handler(request):
    attempts.append(1)
    if len(attempts) == 1:
      return httpx.Response(429, headers={"retry-after": "86400"})
    return httpx.Response(200, json={})

  src = make_source(handler, retries=3)
  src.get_json("/x")

  assert max(src.clock.slept) <= MAX_RETRY_AFTER_S


def test_a_reasonable_retry_after_is_still_honoured_exactly():
  attempts = []

  def handler(request):
    attempts.append(1)
    if len(attempts) == 1:
      return httpx.Response(429, headers={"retry-after": "7"})
    return httpx.Response(200, json={})

  src = make_source(handler, retries=3)
  src.get_json("/x")

  assert 7.0 in src.clock.slept


def test_the_total_wait_across_retries_is_bounded():
  """every sleep path has a ceiling, so a run can always make progress."""
  from music_metadata.sources.base import MAX_RETRY_AFTER_S

  src = make_source(
    lambda r: httpx.Response(503, headers={"retry-after": "99999"}), retries=5
  )
  with pytest.raises(SourceError):
    src.get_json("/x")

  assert sum(src.clock.slept) <= MAX_RETRY_AFTER_S * 5
