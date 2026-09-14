"""hit the real spotify API and assert §7b's verification table still holds.

marked `live`: excluded from every ordinary run (SPEC.md §12). run it with
`uv run pytest -m live`.

CLAUDE.md: a citation more than a few weeks old is a hypothesis, not a fact.
this test is how §7b's table stops being a hypothesis.
"""

import pytest

from music_metadata.config import MissingCredentialError, load_env, require
from music_metadata.release import choose_release, earliest_release_date
from music_metadata.sources.spotify import Spotify

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def spotify():
  load_env()
  try:
    client = Spotify(require("SPOTIFY_CLIENT_ID"), require("SPOTIFY_CLIENT_SECRET"))
  except MissingCredentialError as exc:
    pytest.skip(str(exc))
  yield client
  client.close()


# SPEC.md §7b, "verified against every case probed for this spec".
TABLE = [
  ("USUM72214489", "Demons Protected By Angels", 4, 19),
  ("INS181801821", "Stree", 2, 4),
  ("INS181700238", "Badrinath Ki Dulhania", 2, 5),
  ("USJI10000001", "No Strings Attached", 1, 12),
  ("USUG12509635", "ODYSSEY", 7, 19),
  ("GBARL1201392", "18 Months", 10, 15),
  ("SGB502383473", "Desperado", 1, 1),
  ("GBARL2501127", "Blessings - The Remixes (Part 2)", 4, 6),
]


@pytest.mark.parametrize(("isrc", "album", "track_number", "total_tracks"), TABLE)
def test_section_7b_table(spotify, isrc, album, track_number, total_tracks):
  chosen = choose_release(spotify.search_isrc(isrc).candidates)

  assert chosen is not None, f"{isrc} returned no releases"
  assert chosen.album_name == album
  assert (chosen.track_number, chosen.total_tracks) == (track_number, total_tracks)


def test_the_date_comes_from_a_different_release_than_the_album(spotify):
  """F33 and §5a, on the spec's own worked example.

  the chosen album is No Strings Attached (2000-03-21); the date written is
  2000-01-17, from the single. both facts are true and both are kept.
  """
  result = spotify.search_isrc("USJI10000001")
  chosen = choose_release(result.candidates)

  assert chosen is not None
  assert chosen.album_name == "No Strings Attached"
  assert earliest_release_date(result.candidates) == "2000-01-17"
  assert chosen.release_date != "2000-01-17"


def test_pagination_reaches_past_the_first_page(spotify):
  """measured 2026-09-14: this ISRC returns 34 releases, not the 10 §5a saw."""
  result = spotify.search_isrc("USJI10000001")

  assert len(result.candidates) > 10


def test_every_page_is_kept_for_the_cache(spotify):
  """SPEC.md §9a: a parsing fix is replayed offline against stored payloads."""
  raw = spotify.search_isrc("USJI10000001").raw

  assert raw["query"] == "isrc:USJI10000001"
  assert len(raw["pages"]) > 1
