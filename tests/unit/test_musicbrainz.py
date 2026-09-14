import httpx
import pytest

from music_metadata.sources.musicbrainz import (
  USER_AGENT,
  Credit,
  MusicBrainz,
  split_credit,
)
from music_metadata.sources.ratelimit import TokenBucket

# the real payload for GBARL1201392, trimmed. captured live 2026-09-14.
SWEET_NOTHING = {
  "isrc": "GBARL1201392",
  "recordings": [
    {
      "id": "4cf00d80-35b4-49d6-a050-68ca435e694b",
      "title": "Sweet Nothing",
      "length": 212297,
      "first-release-date": "2012-04-16",
      "artist-credit": [
        {"name": "Calvin Harris", "joinphrase": " feat. "},
        {"name": "Florence Welch", "joinphrase": ""},
      ],
      "relations": [
        {"type": "producer", "target-type": "artist"},
        {
          "type": "performance",
          "target-type": "work",
          "work": {"id": "bcb8cfe6-eb41-4197-991f-998c0f953fb5"},
        },
      ],
    }
  ],
}

WORK = {
  "title": "Sweet Nothing",
  "relations": [
    {"type": "writer", "artist": {"name": "Calvin Harris"}},
    {"type": "writer", "artist": {"name": "Kid Harpoon"}},
    {"type": "writer", "artist": {"name": "Florence Welch"}},
  ],
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


def make(handler):
  clock = FakeClock()
  mb = MusicBrainz(
    bucket=TokenBucket(60, now=clock.now, sleep=clock.sleep),
    transport=httpx.MockTransport(handler),
    sleep=clock.sleep,
  )
  mb.clock = clock
  return mb


def default_handler(request):
  if "/work/" in str(request.url):
    return httpx.Response(200, json=WORK)
  return httpx.Response(200, json=SWEET_NOTHING)


# --- §6's joinphrase split, the reason this source exists --------------------


def test_the_joinphrase_marks_the_boundary():
  """§6: `feat.` in a joinphrase splits main from featured, structurally."""
  got = split_credit(SWEET_NOTHING["recordings"][0]["artist-credit"])

  assert got == Credit(main=("Calvin Harris",), featured=("Florence Welch",))


def test_the_david_guetta_case_from_section_6():
  """three artists, two joinphrases, one boundary."""
  got = split_credit(
    [
      {"name": "David Guetta", "joinphrase": " feat. "},
      {"name": "Taio Cruz", "joinphrase": " & "},
      {"name": "Ludacris", "joinphrase": ""},
    ]
  )

  assert got.main == ("David Guetta",)
  assert got.featured == ("Taio Cruz", "Ludacris")


def test_multiple_main_artists_before_the_boundary():
  got = split_credit(
    [
      {"name": "A", "joinphrase": " & "},
      {"name": "B", "joinphrase": " feat. "},
      {"name": "C", "joinphrase": ""},
    ]
  )

  assert got.main == ("A", "B")
  assert got.featured == ("C",)


def test_no_feature_means_everyone_is_main():
  got = split_credit(
    [{"name": "A", "joinphrase": " & "}, {"name": "B", "joinphrase": ""}]
  )

  assert got == Credit(main=("A", "B"), featured=())


@pytest.mark.parametrize(
  "join", [" feat. ", " ft. ", " featuring ", " with ", " FEAT. "]
)
def test_every_feature_spelling_is_a_boundary(join):
  got = split_credit(
    [{"name": "A", "joinphrase": join}, {"name": "B", "joinphrase": ""}]
  )

  assert got.featured == ("B",)


def test_a_name_nested_under_artist_is_still_read():
  got = split_credit([{"artist": {"name": "Arijit Singh"}, "joinphrase": ""}])

  assert got.main == ("Arijit Singh",)


def test_an_unusable_credit_is_empty_not_a_crash():
  assert split_credit(None) == Credit((), ())
  assert split_credit("nonsense") == Credit((), ())


# --- the lookup --------------------------------------------------------------


def test_a_recording_is_parsed():
  rec, _ = make(default_handler).recording_for_isrc("GBARL1201392")

  assert rec is not None
  assert rec.title == "Sweet Nothing"
  assert rec.credit.featured == ("Florence Welch",)
  assert rec.length_ms == 212297
  assert rec.first_release_date == "2012-04-16"


def test_the_work_id_comes_from_the_performance_relation():
  rec, _ = make(default_handler).recording_for_isrc("GBARL1201392")

  assert rec.work_id == "bcb8cfe6-eb41-4197-991f-998c0f953fb5"


def test_a_recording_with_no_work_reports_none():
  """measured: 6 of 12 sampled recordings link to no work at all."""

  def handler(request):
    body = {
      "recordings": [{"id": "x", "title": "y", "artist-credit": [], "relations": []}]
    }
    return httpx.Response(200, json=body)

  rec, _ = make(handler).recording_for_isrc("X")

  assert rec.work_id is None


def test_a_miss_is_none_not_an_error():
  """F31: a musicbrainz miss does not mean a bad ISRC."""

  def handler(request):
    return httpx.Response(200, json={"isrc": "X", "recordings": []})

  rec, raw = make(handler).recording_for_isrc("X")

  assert rec is None
  assert raw == {"isrc": "X", "recordings": []}


def test_a_404_is_a_miss_not_an_error():
  rec, _ = make(lambda r: httpx.Response(404)).recording_for_isrc("X")

  assert rec is None


def test_the_raw_payload_is_returned_for_the_cache():
  _, raw = make(default_handler).recording_for_isrc("GBARL1201392")

  assert raw == SWEET_NOTHING


# --- the two operational facts, measured live --------------------------------


def test_a_user_agent_is_always_sent():
  """measured: musicbrainz answers HTTP 403 with no User-Agent."""
  seen = {}

  def handler(request):
    seen["ua"] = request.headers.get("user-agent")
    return httpx.Response(200, json=SWEET_NOTHING)

  make(handler).recording_for_isrc("X")

  assert seen["ua"] == USER_AGENT
  assert "music-metadata" in seen["ua"]


def test_currently_busy_is_retried_not_treated_as_a_miss():
  """F30: the earlier 'miss' was a server error. this is the whole finding."""
  attempts = []

  def handler(request):
    attempts.append(1)
    if len(attempts) == 1:
      return httpx.Response(
        503, json={"error": "The MusicBrainz web server is currently busy."}
      )
    return httpx.Response(200, json=SWEET_NOTHING)

  rec, _ = make(handler).recording_for_isrc("GBARL1201392")

  assert len(attempts) == 2
  assert rec is not None, "a 503 must not be reported as 'musicbrainz has no recording'"


# --- work credits ------------------------------------------------------------


def test_writers_are_read():
  work, _ = make(default_handler).work("bcb8cfe6")

  assert work.writers == ("Calvin Harris", "Kid Harpoon", "Florence Welch")


def test_composer_and_lyricist_are_kept_separate_from_writer():
  """measured on 12 tracks: 34 `writer`, zero `composer`, zero `lyricist`.

  the three roles stay distinct here so the caller decides what a bare `writer`
  means, rather than this module quietly asserting one.
  """

  def handler(request):
    return httpx.Response(
      200,
      json={
        "relations": [
          {"type": "composer", "artist": {"name": "C"}},
          {"type": "lyricist", "artist": {"name": "L"}},
          {"type": "writer", "artist": {"name": "W"}},
        ]
      },
    )

  work, _ = make(handler).work("x")

  assert work.composers == ("C",)
  assert work.lyricists == ("L",)
  assert work.writers == ("W",)


def test_an_unrelated_relation_is_ignored():
  def handler(request):
    return httpx.Response(
      200, json={"relations": [{"type": "publisher", "artist": {"name": "Sony"}}]}
    )

  work, _ = make(handler).work("x")

  assert work.composers == () and work.lyricists == () and work.writers == ()


def test_persistent_unavailability_raises_rather_than_reporting_a_miss():
  """a run must be able to tell 'musicbrainz has nothing' from 'it is down'.

  reporting a service outage as a miss would silently drop credits for tracks
  musicbrainz actually has, which is exactly F30's failure.
  """
  from music_metadata.sources.base import SourceError

  with pytest.raises(SourceError, match="503"):
    make(lambda r: httpx.Response(503)).recording_for_isrc("X")


def test_it_retries_more_than_the_default_because_503_is_routine():
  attempts = []

  def handler(request):
    attempts.append(1)
    return httpx.Response(503)

  with pytest.raises(Exception, match="503"):
    make(handler).recording_for_isrc("X")

  assert len(attempts) == 5
