import httpx

from music_metadata.sources.itunes import Itunes, releases_from_raw
from music_metadata.sources.ratelimit import TokenBucket

# the real shape, trimmed. captured live 2026-09-14.
ALBUM_SEARCH = {
  "resultCount": 3,
  "results": [
    {
      "wrapperType": "collection",
      "collectionType": "Album",
      "collectionId": 303171298,
      "collectionName": "No Strings Attached",
      "artistName": "*NSYNC",
      "trackCount": 12,
      "primaryGenreName": "Pop",
      "artworkUrl100": "https://is1-ssl.mzstatic.com/a/b/100x100bb.jpg",
    },
    {
      # same album name, completely different artist. §7c's identity problem.
      "collectionId": 999,
      "collectionName": "No Strings Attached",
      "artistName": "Brian Robert Jones",
      "artworkUrl100": "https://is1-ssl.mzstatic.com/x/y/100x100bb.jpg",
    },
  ],
}

SONG_SEARCH = {
  "resultCount": 2,
  "results": [
    {
      "wrapperType": "track",
      "kind": "song",
      "collectionId": 1713469222,
      "collectionName": "18 Months",
      "artistName": "Calvin Harris",
      "trackName": "Sweet Nothing (feat. Florence Welch)",
      "trackNumber": 10,
      "trackCount": 15,
      "discNumber": 1,
      "discCount": 1,
      "primaryGenreName": "Dance",
      "artworkUrl100": "https://is1-ssl.mzstatic.com/c/d/100x100bb.jpg",
    }
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
  it = Itunes(
    bucket=TokenBucket(20, now=clock.now, sleep=clock.sleep),
    transport=httpx.MockTransport(handler),
    sleep=clock.sleep,
  )
  it.clock = clock
  return it


# --- album search -------------------------------------------------------------


def test_album_search_parses_results():
  got = make(lambda r: httpx.Response(200, json=ALBUM_SEARCH)).search_albums("x")

  assert got.releases[0].collection_name == "No Strings Attached"
  assert got.releases[0].artist_name == "*NSYNC"
  assert got.releases[0].collection_id == 303171298


def test_album_search_uses_the_album_entity():
  seen = {}

  def handler(request):
    seen["entity"] = request.url.params.get("entity")
    seen["term"] = request.url.params.get("term")
    return httpx.Response(200, json=ALBUM_SEARCH)

  make(handler).search_albums("*NSYNC No Strings Attached")

  assert seen["entity"] == "album"
  assert seen["term"] == "*NSYNC No Strings Attached"


def test_a_same_named_album_by_another_artist_is_still_returned():
  """the adapter reports what itunes said; §7c decides what to accept."""
  got = make(lambda r: httpx.Response(200, json=ALBUM_SEARCH)).search_albums("x")

  assert len(got.releases) == 2
  assert got.releases[1].artist_name == "Brian Robert Jones"


def test_no_results_is_empty_not_an_error():
  body = {"resultCount": 0, "results": []}
  got = make(lambda r: httpx.Response(200, json=body)).search_albums("x")

  assert got.releases == []


# --- song search, the path F37 added -----------------------------------------


def test_song_search_uses_the_song_entity():
  seen = {}

  def handler(request):
    seen["entity"] = request.url.params.get("entity")
    return httpx.Response(200, json=SONG_SEARCH)

  make(handler).search_songs("Calvin Harris Sweet Nothing")

  assert seen["entity"] == "song"


def test_song_search_carries_the_collection_it_belongs_to():
  """F37: this is how `18 Months` is found when album search returns 96 Months."""
  got = make(lambda r: httpx.Response(200, json=SONG_SEARCH)).search_songs("x")

  assert got.releases[0].collection_name == "18 Months"
  assert got.releases[0].collection_id == 1713469222


def test_song_results_carry_track_and_disc_numbers():
  """F4: the free itunes API supplies exactly the fields musicfetch lacked."""
  release = (
    make(lambda r: httpx.Response(200, json=SONG_SEARCH)).search_songs("x").releases[0]
  )

  assert (release.track_number, release.track_count) == (10, 15)
  assert (release.disc_number, release.disc_count) == (1, 1)


def test_the_primary_genre_is_carried():
  """§7 precedence: itunes genre is the fallback below beatport and discogs."""
  release = (
    make(lambda r: httpx.Response(200, json=SONG_SEARCH)).search_songs("x").releases[0]
  )

  assert release.primary_genre == "Dance"


# --- lookup -------------------------------------------------------------------


def test_lookup_queries_by_id():
  seen = {}

  def handler(request):
    seen["id"] = request.url.params.get("id")
    return httpx.Response(200, json=ALBUM_SEARCH)

  make(handler).lookup(303171298)

  assert seen["id"] == "303171298"


def test_lookup_of_an_unknown_id_is_empty():
  body = {"resultCount": 0, "results": []}
  got = make(lambda r: httpx.Response(200, json=body)).lookup(1)

  assert got.releases == []


# --- the cache contract -------------------------------------------------------


def test_the_raw_payload_is_returned():
  """SPEC.md §9a: raw responses are stored, not just parsed fields."""
  got = make(lambda r: httpx.Response(200, json=ALBUM_SEARCH)).search_albums("x")

  assert got.raw == ALBUM_SEARCH


def test_a_stored_payload_re_parses_offline():
  assert releases_from_raw(SONG_SEARCH)[0].collection_name == "18 Months"


def test_re_parsing_junk_is_empty_not_a_crash():
  assert releases_from_raw(None) == []
  assert releases_from_raw({"results": "nonsense"}) == []


def test_a_result_with_no_collection_is_skipped():
  body = {"results": [{"artistName": "x"}, *SONG_SEARCH["results"]]}
  got = make(lambda r: httpx.Response(200, json=body)).search_songs("x")

  assert len(got.releases) == 1
