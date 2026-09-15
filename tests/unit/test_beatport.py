import httpx
import pytest

from music_metadata.sources.beatport import (
  CLASS_DIFFERENT_EDIT,
  CLASS_SAME_RECORDING,
  MATCHED_BY_ISRC,
  MATCHED_BY_SEARCH,
  Beatport,
  BeatportTrack,
  classify,
  tracks_from_raw,
)
from music_metadata.sources.bp_auth import NullProvider
from music_metadata.sources.ratelimit import TokenBucket


class Tokens:
  def __init__(self, token="tok"):
    self.token = token

  def get(self):
    return self.token


def track(**kw):
  base = {
    "track_id": 1,
    "name": "Blessings",
    "mix_name": "Odd Mob Remix",
    "artists": ("Calvin Harris",),
    "remixers": ("Odd Mob",),
    "genre": "House",
    "sub_genre": None,
    "label": "Columbia",
    "bpm": 128,
    "key": "Eb Minor",
    "length_ms": 200_000,
    "isrc": "GBARL2501127",
  }
  base.update(kw)
  return BeatportTrack(**base)


RAW = {
  "results": [
    {
      "id": 20819013,
      "name": "Blessings",
      "mix_name": "Odd Mob Remix",
      "artists": [{"name": "Calvin Harris"}],
      "remixers": [{"name": "Odd Mob"}],
      "genre": {"name": "House"},
      "sub_genre": {"name": "Tech House"},
      "release": {"label": {"name": "Columbia"}},
      "bpm": 128,
      "key": {"name": "Eb Minor"},
      "length_ms": 200_000,
      "isrc": "GBARL2501127",
    }
  ]
}


def make(handler, tokens=None):
  clock = type("C", (), {"t": 0.0, "now": lambda s: s.t, "sleep": lambda s, x: None})()
  return Beatport(
    tokens=tokens or Tokens(),
    bucket=TokenBucket(20, now=clock.now, sleep=clock.sleep),
    transport=httpx.MockTransport(handler),
    sleep=clock.sleep,
  )


# --- G3: the duration split decides what may be copied -----------------------


def test_the_same_duration_transfers_everything():
  got, delta = classify(200.0, track(length_ms=200_000))

  assert got == CLASS_SAME_RECORDING
  assert delta == pytest.approx(0.0)


@pytest.mark.parametrize("delta", [0.0, 2.0, 4.9, 5.0])
def test_within_the_tolerance_is_the_same_recording(delta):
  assert (
    classify(200.0, track(length_ms=int((200.0 + delta) * 1000)))[0]
    == CLASS_SAME_RECORDING
  )


@pytest.mark.parametrize("delta", [5.1, 15.0, 90.0])
def test_outside_the_tolerance_is_a_different_edit(delta):
  """F23: the same work released as two genuinely different recordings."""
  assert (
    classify(200.0, track(length_ms=int((200.0 + delta) * 1000)))[0]
    == CLASS_DIFFERENT_EDIT
  )


def test_a_shorter_beatport_track_is_also_a_different_edit():
  assert classify(400.0, track(length_ms=200_000))[0] == CLASS_DIFFERENT_EDIT


def test_no_beatport_length_is_treated_as_a_different_edit():
  """assuming sameness with nothing to compare is what writes a wrong BPM."""
  got, delta = classify(200.0, track(length_ms=None))

  assert got == CLASS_DIFFERENT_EDIT
  assert delta is None


def test_a_same_recording_match_transfers_everything():
  from music_metadata.sources.beatport import Match

  m = Match(track(), MATCHED_BY_ISRC, CLASS_SAME_RECORDING, 1.0)

  assert m.transfers_everything is True


def test_a_different_edit_match_does_not():
  """G3: bpm, key, length and beatport's isrc are DISCARDED."""
  from music_metadata.sources.beatport import Match

  m = Match(track(), MATCHED_BY_SEARCH, CLASS_DIFFERENT_EDIT, 42.0)

  assert m.transfers_everything is False


def test_a_materially_longer_match_is_an_oq8_candidate():
  """OQ-8: flag, never substitute. the beatport record is a different recording."""
  from music_metadata.sources.beatport import Match

  assert Match(track(), MATCHED_BY_SEARCH, CLASS_DIFFERENT_EDIT, 42.0).materially_longer
  assert not Match(
    track(), MATCHED_BY_SEARCH, CLASS_DIFFERENT_EDIT, 6.0
  ).materially_longer


# --- parsing ------------------------------------------------------------------


def test_a_listing_is_parsed():
  got = tracks_from_raw(RAW)[0]

  assert got.track_id == 20819013
  assert got.artists == ("Calvin Harris",)
  assert got.remixers == ("Odd Mob",)
  assert got.label == "Columbia"
  assert got.bpm == 128


def test_the_sub_genre_wins_where_it_exists():
  """F13: sub_genre was populated on 1 of 17; take it wherever it is."""
  assert tracks_from_raw(RAW)[0].best_genre == "Tech House"


def test_the_genre_is_used_when_there_is_no_sub_genre():
  assert track(genre="House", sub_genre=None).best_genre == "House"


def test_the_key_is_converted_to_camelot():
  """§7f: TKEY is written in camelot, not musical notation."""
  assert tracks_from_raw(RAW)[0].camelot_key == "2A"


def test_an_unparseable_key_yields_no_camelot():
  assert track(key="not a key").camelot_key is None


def test_junk_parses_to_nothing():
  assert tracks_from_raw(None) == []
  assert tracks_from_raw({"results": "nonsense"}) == []
  assert tracks_from_raw({"results": [{"no": "id"}]}) == []


# --- §5: this tier failing must not raise ------------------------------------


def test_no_token_means_no_match_not_an_exception():
  """§5: if beatport auth breaks it returns nothing and the run completes."""
  bp = make(lambda r: httpx.Response(200, json=RAW), tokens=NullProvider())

  assert bp.by_isrc("GBARL2501127")[0] is None
  assert bp.search("a", "b")[0] == []
  assert bp.find("X", "a", "b", None, 200.0)[0] is None


def test_a_server_error_means_no_match_not_an_exception():
  bp = make(lambda r: httpx.Response(500))

  assert bp.find("X", "Calvin Harris", "Blessings", None, 200.0)[0] is None


def test_a_404_means_no_match():
  assert make(lambda r: httpx.Response(404)).by_isrc("X")[0] is None


def test_zero_results_is_a_normal_outcome():
  """most of this library is not on beatport at all."""
  bp = make(lambda r: httpx.Response(200, json={"results": []}))

  assert bp.find("X", "a", "b", None, 200.0)[0] is None


# --- F22: ISRC is a fast path, search is the real one ------------------------


def test_the_isrc_fast_path_is_tried_first():
  paths = []

  def handler(request):
    paths.append(request.url.path)
    return httpx.Response(200, json=RAW)

  got, _ = make(handler).find(
    "GBARL2501127", "Calvin Harris", "Blessings", "Odd Mob Remix", 200.0
  )

  assert got.matched_by == MATCHED_BY_ISRC
  assert paths == ["/v4/catalog/tracks/"]


def test_search_is_used_when_the_isrc_misses():
  """F22: ?isrc= failed on all nine Blessings remixes."""
  paths = []

  def handler(request):
    paths.append(request.url.path)
    if request.url.path == "/v4/catalog/tracks/":
      return httpx.Response(200, json={"results": []})
    return httpx.Response(200, json=RAW)

  got, _ = make(handler).find(
    "GBARL2501127", "Calvin Harris", "Blessings", "Odd Mob Remix", 200.0
  )

  assert got.matched_by == MATCHED_BY_SEARCH
  assert paths == ["/v4/catalog/tracks/", "/v4/catalog/search/"]


def test_the_search_term_carries_artist_name_and_mix():
  seen = {}

  def handler(request):
    if request.url.path == "/v4/catalog/tracks/":
      return httpx.Response(200, json={"results": []})
    seen["q"] = request.url.params.get("q")
    return httpx.Response(200, json=RAW)

  make(handler).find(None, "Calvin Harris", "Blessings", "Odd Mob Remix", 200.0)

  assert seen["q"] == "Calvin Harris Blessings Odd Mob Remix"


# --- G3's acceptance rule -----------------------------------------------------


def test_a_different_artist_is_not_accepted():
  """accepting on name alone would take another artist's cover."""
  body = {"results": [{**RAW["results"][0], "artists": [{"name": "Someone Else"}]}]}
  bp = make(lambda r: httpx.Response(200, json=body))

  assert bp.search("Calvin Harris", "Blessings", "Odd Mob Remix")[0] != []
  assert bp.find(None, "Calvin Harris", "Blessings", "Odd Mob Remix", 200.0)[0] is None


def test_a_different_mix_is_not_accepted():
  """taking the extended cut's BPM for a radio edit is exactly the F23 failure."""
  bp = make(lambda r: httpx.Response(200, json=RAW))

  assert bp.find(None, "Calvin Harris", "Blessings", "Extended Mix", 200.0)[0] is None


def test_the_mix_name_comparison_is_normalised():
  """§7a: `Extended Mix` and `Extended` are the same mix."""
  body = {"results": [{**RAW["results"][0], "mix_name": "Extended Mix"}]}
  bp = make(lambda r: httpx.Response(200, json=body))

  assert bp.find(None, "Calvin Harris", "Blessings", "Extended", 200.0)[0] is not None


def test_a_track_with_no_mix_matches_a_listing_with_no_mix():
  body = {"results": [{**RAW["results"][0], "mix_name": None}]}
  bp = make(lambda r: httpx.Response(200, json=body))

  assert bp.find(None, "Calvin Harris", "Blessings", None, 200.0)[0] is not None


def test_the_bearer_token_is_sent():
  seen = {}

  def handler(request):
    seen["auth"] = request.headers.get("authorization")
    return httpx.Response(200, json=RAW)

  make(handler).by_isrc("X")

  assert seen["auth"] == "Bearer tok"


def test_the_raw_payload_is_returned_for_the_cache():
  """§9a stores what the API said, not a re-serialised parse of it."""
  _, raw = make(lambda r: httpx.Response(200, json=RAW)).by_isrc("X")

  assert raw == RAW


def test_a_miss_still_returns_the_payload_it_searched():
  body = {"results": []}
  match, raw = make(lambda r: httpx.Response(200, json=body)).find(
    None, "a", "b", None, 200.0
  )

  assert match is None
  assert raw == body
