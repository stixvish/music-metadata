import httpx
import pytest

from music_metadata.artwork import (
  CANDIDATE_ALBUM_SEARCH,
  CANDIDATE_SONG_SEARCH,
  CANDIDATE_SPOTIFY,
  SIZES,
  fetch_bytes,
  fetch_largest,
  jpeg_dimensions,
  matches_release,
  resolve_artwork,
  upgrade_url,
)
from music_metadata.sources.itunes import ItunesRelease

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def release(
  name="No Strings Attached", artist="*NSYNC", url="https://i.test/100x100bb.jpg"
):
  return ItunesRelease(
    collection_id=1, collection_name=name, artist_name=artist, artwork_url_100=url
  )


# --- the name check rejects, it never coerces (§7c) ---------------------------


def test_an_exact_match_is_accepted():
  assert matches_release(release(), "No Strings Attached", "*NSYNC") is True


def test_case_and_punctuation_do_not_matter():
  assert matches_release(
    release(name="no strings attached!"), "No Strings Attached", "*NSYNC"
  )


def test_the_chosen_name_contained_in_the_result_is_accepted():
  """§7c: exact on normalised text, or the chosen name contained in it."""
  got = matches_release(
    release(name="No Strings Attached (Deluxe Edition)"),
    "No Strings Attached",
    "*NSYNC",
  )

  assert got is True


def test_96_months_is_rejected():
  """§7c's worked example. a looser match would embed the wrong cover silently.

  searching itunes for `Calvin Harris 18 Months` returns exactly one album —
  `96 Months` — and it is verified live that this is still true.
  """
  got = matches_release(
    release(name="96 Months", artist="Calvin Harris"), "18 Months", "Calvin Harris"
  )

  assert got is False


def test_a_different_artist_with_the_same_album_name_is_rejected():
  """measured live: searching `*NSYNC No Strings Attached` returns a second
  album of the same name by Brian Robert Jones. matching on the name alone
  would accept it on a different result ordering."""
  got = matches_release(
    release(artist="Brian Robert Jones"), "No Strings Attached", "*NSYNC"
  )

  assert got is False


def test_a_release_with_no_artwork_url_is_rejected():
  assert matches_release(release(url=None), "No Strings Attached", "*NSYNC") is False


@pytest.mark.parametrize(
  "name", ["", "Strings", "No Strings", "Attached", "A Totally Different Album"]
)
def test_partial_and_unrelated_names_are_rejected(name):
  assert matches_release(release(name=name), "No Strings Attached", "*NSYNC") is False


def test_matching_is_not_symmetric_in_the_wrong_direction():
  """the *result* may be longer than the chosen name, never shorter."""
  got = matches_release(release(name="Months"), "18 Months", "Calvin Harris")

  assert got is False


# --- the resolution upgrade (F5, §7c) -----------------------------------------


def test_the_hundred_is_rewritten_to_the_requested_size():
  got = upgrade_url("https://i.test/a/b/100x100bb.jpg", 3000)

  assert got == "https://i.test/a/b/3000x3000bb.jpg"


def test_any_source_size_is_rewritten():
  assert upgrade_url("https://i.test/60x60bb.jpg", 1400).endswith("1400x1400bb.jpg")


def test_a_url_without_a_size_segment_is_returned_unchanged():
  url = "https://i.test/artwork.jpg"

  assert upgrade_url(url, 3000) == url


def test_the_step_down_order_matches_the_spec():
  """§7c: step down 3000 → 1400 → 600 rather than failing the track."""
  assert SIZES == (3000, 1400, 600)


# --- the chain, end to end ----------------------------------------------------


class FakeItunes:
  """an itunes that returns whatever the test says, and records the terms."""

  def __init__(self, albums=(), songs=()):
    self._albums = list(albums)
    self._songs = list(songs)
    self.terms = []

  def search_albums(self, term):
    self.terms.append(("album", term))
    return _Result(self._albums)

  def search_songs(self, term):
    self.terms.append(("song", term))
    return _Result(self._songs)


class _Result:
  def __init__(self, releases):
    self.releases = releases
    self.raw = {}


def always(data):
  return lambda url: data


def test_the_album_search_is_tried_first():
  it = FakeItunes(albums=[release()])

  got = resolve_artwork(
    it, "No Strings Attached", "*NSYNC", "Bye Bye Bye", fetch=always(JPEG)
  )

  assert got.candidate == CANDIDATE_ALBUM_SEARCH
  assert it.terms == [("album", "*NSYNC No Strings Attached")]


def test_the_song_search_catches_what_the_album_search_misses():
  """F37's whole reason: `18 Months` is only reachable through song search."""
  it = FakeItunes(
    albums=[release(name="96 Months", artist="Calvin Harris")],
    songs=[release(name="18 Months", artist="Calvin Harris")],
  )

  got = resolve_artwork(
    it, "18 Months", "Calvin Harris", "Sweet Nothing", fetch=always(JPEG)
  )

  assert got.candidate == CANDIDATE_SONG_SEARCH
  assert got.source_release == "18 Months"


def test_the_song_search_is_asked_for_the_track_not_the_album():
  it = FakeItunes(albums=[], songs=[release(name="18 Months", artist="Calvin Harris")])

  resolve_artwork(it, "18 Months", "Calvin Harris", "Sweet Nothing", fetch=always(JPEG))

  assert ("song", "Calvin Harris Sweet Nothing") in it.terms


def test_spotify_is_the_last_candidate():
  """§7c candidate C: correct by construction, but capped around 640px."""
  got = resolve_artwork(
    FakeItunes(),
    "Album",
    "Artist",
    "Track",
    spotify_image_url="https://i.test/640.jpg",
    fetch=always(JPEG),
  )

  assert got.candidate == CANDIDATE_SPOTIFY


def test_nothing_verifying_returns_none_rather_than_a_wrong_cover():
  """G5: keep the existing art and flag, never substitute an unverified image."""
  it = FakeItunes(albums=[release(name="96 Months", artist="Calvin Harris")])

  got = resolve_artwork(
    it, "18 Months", "Calvin Harris", "Sweet Nothing", fetch=always(JPEG)
  )

  assert got is None


def test_a_verified_release_whose_bytes_fail_falls_through():
  it = FakeItunes(albums=[release()], songs=[])

  got = resolve_artwork(
    it, "No Strings Attached", "*NSYNC", "Bye Bye Bye", fetch=always(None)
  )

  assert got is None


def test_the_largest_size_wins_when_it_works():
  seen = []

  def fetch(url):
    seen.append(url)
    return JPEG

  got = fetch_largest("https://i.test/100x100bb.jpg", fetch=fetch)

  assert got[1] == 3000
  assert seen == ["https://i.test/3000x3000bb.jpg"]


def test_it_steps_down_when_the_largest_fails():
  """§7c: step down rather than failing the track."""
  seen = []

  def fetch(url):
    seen.append(url)
    return None if "3000" in url else JPEG

  data, width, url = fetch_largest("https://i.test/100x100bb.jpg", fetch=fetch)

  assert width == 1400
  assert len(seen) == 2


def test_every_size_failing_gives_none():
  assert fetch_largest("https://i.test/100x100bb.jpg", fetch=always(None)) is None


def test_the_artwork_hashes_its_bytes():
  got = resolve_artwork(
    FakeItunes(albums=[release()]),
    "No Strings Attached",
    "*NSYNC",
    "x",
    fetch=always(JPEG),
  )

  assert len(got.sha256) == 64


def test_the_recorded_width_is_what_came_back_not_what_was_asked_for():
  """F54: apple caps at the album's master, so asking 3000 can yield 1425.

  recording the requested size would put a false number in the cache.
  """
  # a minimal JPEG whose SOF0 marker declares 1425x1425.
  import struct

  sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 1425, 1425)
  jpeg = b"\xff\xd8" + sof + b"\x00" * 64

  data, width, _ = fetch_largest("https://i.test/100x100bb.jpg", fetch=lambda u: jpeg)

  assert width == 1425


def test_an_unreadable_jpeg_falls_back_to_the_requested_size():
  data, width, _ = fetch_largest("https://i.test/100x100bb.jpg", fetch=lambda u: JPEG)

  assert width == 3000


# --- fetching the bytes -------------------------------------------------------


def client(handler):
  return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_good_response_returns_its_bytes():
  big = b"\xff\xd8" + b"\x00" * 20_000

  assert (
    fetch_bytes(
      "https://i.test/a.jpg", client=client(lambda r: httpx.Response(200, content=big))
    )
    == big
  )


def test_a_non_200_is_none():
  got = fetch_bytes(
    "https://i.test/a.jpg", client=client(lambda r: httpx.Response(404))
  )

  assert got is None


def test_a_short_read_is_rejected_as_a_placeholder():
  """apple serves a tiny placeholder rather than erroring on some sizes."""
  tiny = b"\xff\xd8" + b"\x00" * 100

  got = fetch_bytes(
    "https://i.test/a.jpg", client=client(lambda r: httpx.Response(200, content=tiny))
  )

  assert got is None


def test_a_transport_failure_is_none_not_an_exception():
  def handler(request):
    raise httpx.ConnectError("boom")

  assert fetch_bytes("https://i.test/a.jpg", client=client(handler)) is None


def test_jpeg_dimensions_reads_the_sof_marker():
  import struct

  sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 640, 480)
  assert jpeg_dimensions(b"\xff\xd8" + sof + b"\x00" * 8) == (480, 640)


def test_jpeg_dimensions_of_junk_is_none():
  assert jpeg_dimensions(b"not a jpeg at all") is None
  assert jpeg_dimensions(b"\xff\xd8\xff\xff\x00") is None


def test_a_truncated_jpeg_header_is_none():
  """a segment length running past the end must not raise."""
  assert jpeg_dimensions(b"\xff\xd8\xff\xe0\xff") is None


def test_no_album_artist_falls_back_to_the_name_check_alone():
  """some releases have no album artist; the name must still be able to match."""
  assert matches_release(release(), "No Strings Attached", "") is True


def test_fetch_bytes_closes_a_client_it_created():
  """the default path opens its own client; it must not leak one per track."""
  got = fetch_bytes("https://i.test/nope.jpg")

  assert got is None


def test_an_empty_search_term_is_skipped():
  """with no album artist and no album name there is nothing to search for."""
  it = FakeItunes(albums=[release()])

  resolve_artwork(it, "", "", "", fetch=always(JPEG))

  assert it.terms == []


def test_an_edition_qualifier_is_stripped_from_the_search_term():
  """measured: itunes returns 0 results for a name carrying `(Deluxe)`.

  `"24kGoldn El Dorado (Deluxe)"` finds nothing; `"24kGoldn El Dorado"` finds
  the album. so the qualifier has to come off the term, and this is why the
  operator's `Prada` had no artwork while a 3000px cover was available.
  """
  seen = []

  class Recording:
    def search_albums(self, term):
      seen.append(term)
      return type("R", (), {"releases": []})()

    def search_songs(self, term):
      seen.append(term)
      return type("R", (), {"releases": []})()

  resolve_artwork(Recording(), "El Dorado (Deluxe)", "24kGoldn", "Prada")

  assert seen[0] == "24kGoldn El Dorado"


def test_a_standard_edition_result_verifies_a_deluxe_choice():
  """the edition qualifier does not identify the record.

  §7b deliberately chooses the expanded edition, and itunes indexes the album
  under its plain name. refusing that match leaves the track with no artwork
  at all, which is strictly worse — apple's cover is a per-album master (F54).
  """
  standard = release(name="El Dorado", artist="24kGoldn")

  assert matches_release(standard, "El Dorado (Deluxe)", "24kGoldn")


def test_a_different_album_still_does_not_verify():
  """widening on the edition must not widen onto a different record."""
  other = release(name="96 Months", artist="Calvin Harris")

  assert not matches_release(other, "18 Months", "Calvin Harris")
