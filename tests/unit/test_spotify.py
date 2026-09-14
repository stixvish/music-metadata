import httpx
import pytest

from music_metadata.sources.base import SourceError
from music_metadata.sources.ratelimit import TokenBucket
from music_metadata.sources.spotify import Spotify

TOKEN_URL = "https://accounts.spotify.com/api/token"

# one track on two releases: the album and the promo single. this is the shape
# every §7b decision is made from.
SEARCH_BODY = {
  "tracks": {
    "items": [
      {
        "id": "trk-album",
        "name": "Bye Bye Bye",
        "duration_ms": 200400,
        "disc_number": 1,
        "track_number": 1,
        "external_ids": {"isrc": "USJI10000001"},
        "artists": [{"name": "*NSYNC"}],
        "album": {
          "id": "alb-album",
          "name": "No Strings Attached",
          "album_type": "album",
          "total_tracks": 12,
          "release_date": "2000-03-21",
          "artists": [{"name": "*NSYNC"}],
          "images": [{"url": "https://i.test/640.jpg", "width": 640}],
        },
      },
      {
        "id": "trk-single",
        "name": "Bye Bye Bye",
        "duration_ms": 200400,
        "disc_number": 1,
        "track_number": 1,
        "external_ids": {"isrc": "USJI10000001"},
        "artists": [{"name": "*NSYNC"}],
        "album": {
          "id": "alb-single",
          "name": "Bye Bye Bye",
          "album_type": "single",
          "total_tracks": 1,
          "release_date": "2000-01-17",
          "artists": [{"name": "*NSYNC"}],
          "images": [],
        },
      },
    ]
  }
}


class FakeClock:
  def __init__(self):
    self.t = 0.0
    self.slept = []

  def now(self):
    return self.t

  def sleep(self, s):
    self.slept.append(s)
    self.t += s


def make_spotify(handler, **kw):
  clock = FakeClock()
  s = Spotify(
    client_id="id",
    client_secret="secret",
    bucket=TokenBucket(20, now=clock.now, sleep=clock.sleep),
    transport=httpx.MockTransport(handler),
    sleep=clock.sleep,
    now=clock.now,
    **kw,
  )
  s.clock = clock
  return s


def default_handler(request):
  if str(request.url).startswith(TOKEN_URL):
    return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
  return httpx.Response(200, json=SEARCH_BODY)


def test_search_returns_one_candidate_per_release():
  got = make_spotify(default_handler).search_isrc("USJI10000001")

  assert len(got.candidates) == 2


def test_candidates_carry_the_album_facts():
  got = make_spotify(default_handler).search_isrc("USJI10000001")
  album = next(c for c in got.candidates if c.album_type == "album")

  assert album.album_name == "No Strings Attached"
  assert album.total_tracks == 12
  assert album.track_number == 1
  assert album.disc_number == 1
  assert album.album_artists == ("*NSYNC",)


def test_the_raw_pages_are_returned_for_the_cache():
  """SPEC.md §9a: raw responses are stored, not just parsed fields."""
  got = make_spotify(default_handler).search_isrc("USJI10000001")

  assert got.raw["query"] == "isrc:USJI10000001"
  assert got.raw["pages"][0] == SEARCH_BODY


def test_a_short_page_ends_pagination():
  """two items is fewer than the page size, so there is no second request."""
  pages = []

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    pages.append(request.url.params.get("offset"))
    return httpx.Response(200, json=SEARCH_BODY)

  make_spotify(handler).search_isrc("USJI10000001")

  assert pages == ["0"]


def test_a_full_page_is_followed_by_another_request():
  """F33 takes the MIN date over ALL releases, and search is relevance-ordered,
  so a later page can carry an earlier release. measured: USJI10000001 returns
  34 releases across 4 pages."""
  offsets = []
  full = {"tracks": {"items": [SEARCH_BODY["tracks"]["items"][0]] * 10}}

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    offset = request.url.params.get("offset")
    offsets.append(offset)
    if offset == "0":
      return httpx.Response(200, json=full)
    return httpx.Response(200, json={"tracks": {"items": []}})

  got = make_spotify(handler).search_isrc("USJI10000001")

  assert offsets == ["0", "10"]
  assert len(got.candidates) == 10


def test_the_page_size_is_ten_because_more_is_rejected():
  """measured 2026-09-14: limit=20 and above return 400 'Invalid limit'."""
  seen = {}

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    seen["limit"] = request.url.params.get("limit")
    return httpx.Response(200, json=SEARCH_BODY)

  make_spotify(handler).search_isrc("A")

  assert seen["limit"] == "10"


def test_the_isrc_is_queried_exactly():
  seen = {}

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    seen["q"] = request.url.params.get("q")
    seen["type"] = request.url.params.get("type")
    return httpx.Response(200, json=SEARCH_BODY)

  make_spotify(handler).search_isrc("USJI10000001")

  assert seen["q"] == "isrc:USJI10000001"
  assert seen["type"] == "track"


def test_the_bearer_token_is_sent():
  seen = {}

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    seen["auth"] = request.headers.get("authorization")
    return httpx.Response(200, json=SEARCH_BODY)

  make_spotify(handler).search_isrc("USJI10000001")

  assert seen["auth"] == "Bearer tok-1"


def test_the_token_is_fetched_once_and_reused():
  tokens = []

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      tokens.append(1)
      return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    return httpx.Response(200, json=SEARCH_BODY)

  s = make_spotify(handler)
  s.search_isrc("A")
  s.search_isrc("B")

  assert len(tokens) == 1


def test_an_expired_token_is_refetched():
  tokens = []

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      tokens.append(1)
      return httpx.Response(200, json={"access_token": "t", "expires_in": 60})
    return httpx.Response(200, json=SEARCH_BODY)

  s = make_spotify(handler)
  s.search_isrc("A")
  s.clock.t += 120.0
  s.search_isrc("B")

  assert len(tokens) == 2


def test_no_results_is_an_empty_list_not_an_error():
  """a recording spotify does not have is a normal outcome."""

  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    return httpx.Response(200, json={"tracks": {"items": []}})

  got = make_spotify(handler).search_isrc("ZZZZZZZZZZZZ")

  assert got.candidates == []


def test_bad_credentials_raise():
  def handler(request):
    return httpx.Response(400, json={"error": "invalid_client"})

  with pytest.raises(SourceError, match="token"):
    make_spotify(handler).search_isrc("A")


def test_items_missing_an_album_are_skipped_not_fatal():
  def handler(request):
    if str(request.url).startswith(TOKEN_URL):
      return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    return httpx.Response(
      200,
      json={
        "tracks": {"items": [{"id": "x", "name": "y"}, *SEARCH_BODY["tracks"]["items"]]}
      },
    )

  got = make_spotify(handler).search_isrc("USJI10000001")

  assert len(got.candidates) == 2


def test_the_album_image_is_carried_for_the_artwork_fallback():
  """§7c candidate C: spotify's own album image, correct by construction."""
  got = make_spotify(default_handler).search_isrc("USJI10000001")
  album = next(c for c in got.candidates if c.album_type == "album")

  assert album.image_url == "https://i.test/640.jpg"


def test_a_release_with_no_image_reports_none():
  got = make_spotify(default_handler).search_isrc("USJI10000001")
  single = next(c for c in got.candidates if c.album_type == "single")

  assert single.image_url is None
