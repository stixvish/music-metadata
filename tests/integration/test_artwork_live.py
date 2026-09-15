"""hit the real itunes API and assert §7c's measured table still holds.

marked `live`: excluded from every ordinary run (SPEC.md §12).

CLAUDE.md: a citation more than a few weeks old is a hypothesis, not a fact.
this is how §7c's byte sizes stop being a hypothesis.
"""

import pytest

from music_metadata.artwork import (
  CANDIDATE_ALBUM_SEARCH,
  CANDIDATE_SONG_SEARCH,
  matches_release,
  resolve_artwork,
)
from music_metadata.sources.itunes import Itunes

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def itunes():
  client = Itunes()
  yield client
  client.close()


# SPEC.md §7c: "measured on four tracks, 4/4 produced 3000×3000".
TABLE = [
  ("No Strings Attached", "*NSYNC", "Bye Bye Bye", CANDIDATE_ALBUM_SEARCH, 2256),
  ("Stree", "Sachin-Jigar", "Kamariya", CANDIDATE_ALBUM_SEARCH, 1755),
  ("18 Months", "Calvin Harris", "Sweet Nothing", CANDIDATE_SONG_SEARCH, 2162),
  ("ODYSSEY", "ILLENIUM", "Don't Want Your Love", CANDIDATE_ALBUM_SEARCH, 2919),
]


@pytest.mark.parametrize(("album", "artist", "track", "candidate", "kb"), TABLE)
def test_section_7c_table(itunes, album, artist, track, candidate, kb):
  art = resolve_artwork(itunes, album, artist, track)

  assert art is not None, f"no candidate verified for {album}"
  assert art.width == 3000
  assert art.candidate == candidate
  # the spec records the byte size; allow a little drift if apple re-encodes.
  assert abs(len(art.data) // 1024 - kb) < 200


def test_album_search_still_cannot_find_18_months(itunes):
  """F37's premise. if this ever starts passing, candidate B is dead weight."""
  results = itunes.search_albums("Calvin Harris 18 Months").releases

  assert not any(matches_release(r, "18 Months", "Calvin Harris") for r in results), (
    "album search now finds 18 Months; re-check whether song search is still needed"
  )


def test_album_search_returns_96_months_instead(itunes):
  """the specific wrong record §7c names. a fuzzy match would embed its cover."""
  names = [
    r.collection_name for r in itunes.search_albums("Calvin Harris 18 Months").releases
  ]

  assert "96 Months" in names


def test_over_asking_returns_the_master_rather_than_erroring(itunes):
  """measured: apple caps at each album's own master, which varies per album.

  `No Strings Attached` serves 3600² for any request above it; `18 Months`
  serves 3000². over-asking never errors, so 3000 is OQ-1's storage decision
  rather than a technical ceiling — and it is safe, because every album
  measured serves at least 3000.
  """
  from music_metadata.artwork import fetch_bytes, upgrade_url

  release = itunes.search_albums("*NSYNC No Strings Attached").releases[0]
  at_3000 = fetch_bytes(upgrade_url(release.artwork_url_100, 3000))
  at_4500 = fetch_bytes(upgrade_url(release.artwork_url_100, 4500))

  assert at_3000 is not None
  assert at_4500 is not None, "over-asking must not fail"
  assert len(at_4500) >= len(at_3000)
