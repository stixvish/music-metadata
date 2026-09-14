import pytest

from music_metadata.credit import (
  FLAG_CREDIT_DISAGREEMENT,
  FROM_FILENAME,
  FROM_MUSICBRAINZ,
  credit_from_filename,
  in_indian_scope,
  resolve_credit,
)
from music_metadata.sources.musicbrainz import Credit

# --- the filename, §6's second-ranked source --------------------------------


def test_a_feature_in_the_filename_is_read():
  got = credit_from_filename("Arizona Zervas - OH MY LORD (ft. 24kGoldn)")

  assert got.main == ("Arizona Zervas",)
  assert got.featured == ("24kGoldn",)


def test_multiple_main_artists_in_the_filename():
  """196 files carry multiple main artists (§6)."""
  got = credit_from_filename("Calvin Harris, Clementine Douglas & Odd Mob - Blessings")

  assert got.main == ("Calvin Harris", "Clementine Douglas", "Odd Mob")


def test_a_filename_with_no_feature():
  got = credit_from_filename("*NSYNC - Bye Bye Bye")

  assert got.main == ("*NSYNC",)
  assert got.featured == ()


def test_several_features_in_the_filename():
  got = credit_from_filename(
    "A$AP Rocky - Fuckin' Problems (ft. Drake, 2 Chainz & Kendrick Lamar)"
  )

  assert got.featured == ("Drake", "2 Chainz", "Kendrick Lamar")


# --- G6: agree and accept, disagree and flag --------------------------------


def test_agreement_is_accepted_automatically():
  got = resolve_credit(
    "Calvin Harris - Sweet Nothing (ft. Florence Welch)",
    musicbrainz=Credit(main=("Calvin Harris",), featured=("Florence Welch",)),
  )

  assert got.agrees is True
  assert got.flags == ()
  assert got.source == FROM_MUSICBRAINZ


def test_disagreement_is_flagged_rather_than_guessed():
  """§6: when they disagree the track is flagged for review, never auto-resolved."""
  got = resolve_credit(
    "Calvin Harris - Sweet Nothing",
    musicbrainz=Credit(main=("Calvin Harris",), featured=("Florence Welch",)),
  )

  assert got.agrees is False
  assert FLAG_CREDIT_DISAGREEMENT in got.flags


def test_a_disagreement_still_reports_musicbrainz_as_the_value():
  """flagged, not discarded — the reviewer needs something to accept or reject."""
  got = resolve_credit(
    "Someone Else - Track",
    musicbrainz=Credit(main=("The Real Artist",), featured=()),
  )

  assert got.main == ("The Real Artist",)


def test_comparison_ignores_accents_and_punctuation():
  """sources spell the same person differently; that is not a disagreement."""
  got = resolve_credit(
    "Tiesto - Track", musicbrainz=Credit(main=("Tiësto",), featured=())
  )

  assert got.agrees is True


def test_comparison_ignores_order():
  got = resolve_credit(
    "B & A - Track", musicbrainz=Credit(main=("A", "B"), featured=())
  )

  assert got.agrees is True


def test_the_written_value_keeps_the_source_spelling():
  """folding is for comparison only; it must never reach a tag."""
  got = resolve_credit(
    "Tiesto - Track", musicbrainz=Credit(main=("Tiësto",), featured=())
  )

  assert got.main == ("Tiësto",)


# --- §6's fallback order -----------------------------------------------------


def test_the_filename_is_used_when_musicbrainz_has_nothing():
  """F30: a miss falls back to the filename, which §6 ranks above spotify."""
  got = resolve_credit("Arijit Singh - Roke Na Ruke Naina", musicbrainz=None)

  assert got.main == ("Arijit Singh",)
  assert got.source == FROM_FILENAME


def test_a_title_feature_is_used_when_the_filename_has_none():
  got = resolve_credit(
    "Dua Lipa - Levitating", musicbrainz=None, title_features=("DaBaby",)
  )

  assert got.featured == ("DaBaby",)


def test_spotify_is_the_last_resort():
  got = resolve_credit("Untitled", musicbrainz=None, fallback_main=("Some Artist",))

  assert got.main == ("Some Artist",)


def test_musicbrainz_alone_needs_no_cross_check():
  got = resolve_credit("Untitled", musicbrainz=Credit(main=("A",), featured=()))

  assert got.agrees is None
  assert got.flags == ()


# --- §7a / F38: the indian scope is scoped, not global ----------------------


@pytest.mark.parametrize("isrc", ["INS181801821", "INS181700238", "in1234567890"])
def test_an_indian_isrc_prefix_is_in_scope(isrc):
  assert in_indian_scope(isrc, None) is True


@pytest.mark.parametrize(
  "genre", ["Bollywood", "Indian Pop", "punjabi", "Telugu", "Tamil film"]
)
def test_an_indian_genre_is_in_scope(genre):
  assert in_indian_scope("USJI10000001", genre) is True


def test_either_signal_is_enough():
  """F38: 144 by ISRC, 165 by genre, 142 both, 167 either."""
  assert in_indian_scope("INS181801821", "Pop") is True
  assert in_indian_scope("USJI10000001", "Bollywood") is True


def test_western_repertoire_is_out_of_scope():
  """applying the rule globally would strip Metro Boomin out of TPE1."""
  assert in_indian_scope("USJI10000001", "Pop") is False
  assert in_indian_scope("GBARL1201392", "Dance") is False
  assert in_indian_scope(None, None) is False


def test_a_genre_merely_containing_india_still_matches():
  assert in_indian_scope(None, "Indian Classical") is True
