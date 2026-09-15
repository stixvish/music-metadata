import pytest

from music_metadata.credit import (
  FLAG_CREDIT_DISAGREEMENT,
  FROM_FILENAME,
  FROM_FILENAME_BOUNDARY,
  FROM_MUSICBRAINZ,
  credit_from_filename,
  in_indian_scope,
  render_credit,
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


def test_a_band_name_containing_an_ampersand_is_not_a_disagreement():
  """`Tegan & Sara` is one act. splitting it produces two names no source
  will match, and that is a parser artefact, not a real disagreement.

  measured: this class appeared in the G6 sample at 87.5% agreement.
  """
  got = resolve_credit(
    "David Guetta - Every Chance We Get We Run (ft. Tegan & Sara)",
    musicbrainz=Credit(main=("David Guetta",), featured=("Tegan & Sara",)),
  )

  assert got.agrees is True


def test_a_genuinely_different_name_is_still_a_disagreement():
  """the joined-form comparison must not swallow real differences."""
  got = resolve_credit(
    "A Boogie Wit da Hoodie - Need a Best Friend (ft. Lil Quee & Quango Rondo)",
    musicbrainz=Credit(
      main=("A Boogie Wit da Hoodie",), featured=("Lil Quee", "Quango Quango")
    ),
  )

  assert got.agrees is False


# --- F53: the filename decides the boundary, musicbrainz decides the people --


def test_the_filename_wins_when_musicbrainz_flattened_the_feature():
  """F53, 13 measured cases: musicbrainz joins with `&` and the feature is lost.

  `Blxst - Risk Taker (ft. Offset)` — musicbrainz credits both as main. the
  operator typed the boundary deliberately, so it stands.
  """
  got = resolve_credit(
    "Blxst - Risk Taker (ft. Offset)",
    musicbrainz=Credit(main=("Blxst", "Offset"), featured=()),
  )

  assert got.main == ("Blxst",)
  assert got.featured == ("Offset",)
  assert got.source == FROM_FILENAME_BOUNDARY
  assert got.flags == ()


def test_a_boundary_correction_is_not_a_disagreement():
  got = resolve_credit(
    "All Time Low - Monsters (ft. blackbear)",
    musicbrainz=Credit(main=("All Time Low", "blackbear"), featured=()),
  )

  assert got.agrees is True


def test_different_personnel_is_still_flagged():
  """F53, 8 measured cases: `Quango Rondo` vs `Quango Quango` is a real
  disagreement and must not be auto-resolved by a boundary rule."""
  got = resolve_credit(
    "A Boogie Wit da Hoodie - Need a Best Friend (ft. Lil Quee & Quango Rondo)",
    musicbrainz=Credit(
      main=("A Boogie Wit da Hoodie",), featured=("Lil Quee", "Quango Quango")
    ),
  )

  assert FLAG_CREDIT_DISAGREEMENT in got.flags
  assert got.source == FROM_MUSICBRAINZ


def test_musicbrainz_still_decides_personnel_on_a_real_disagreement():
  """19 measured cases where musicbrainz is missing an artist entirely stay
  flagged: the operator decides those, not a rule."""
  got = resolve_credit(
    "A Boogie Wit da Hoodie - Chanelly (ft. Don Q)",
    musicbrainz=Credit(main=("A Boogie Wit da Hoodie",), featured=()),
  )

  assert got.agrees is False
  assert got.main == ("A Boogie Wit da Hoodie",)


def test_extra_musicbrainz_artists_are_a_real_disagreement():
  """7 measured cases where musicbrainz names co-producers the filename omits."""
  got = resolve_credit(
    "David Guetta - Sound of Letting Go (ft. Chris Willis)",
    musicbrainz=Credit(main=("David Guetta", "Tocadisco"), featured=("Chris Willis",)),
  )

  assert FLAG_CREDIT_DISAGREEMENT in got.flags


def test_a_disagreement_carries_the_losing_reading():
  """the queue is undecidable without both sides: these two share a TPE1 and
  differ only in who is featured."""
  got = resolve_credit(
    "A Boogie Wit da Hoodie - Chanelly (ft. Don Q)",
    musicbrainz=Credit(main=("A Boogie Wit da Hoodie",), featured=()),
  )

  assert got.alternative is not None
  assert got.alternative.featured == ("Don Q",)


def test_agreement_carries_no_alternative():
  got = resolve_credit(
    "Calvin Harris - Sweet Nothing (ft. Florence Welch)",
    musicbrainz=Credit(main=("Calvin Harris",), featured=("Florence Welch",)),
  )

  assert got.alternative is None


def test_render_credit_puts_features_in_the_parenthetical():
  assert render_credit(("A", "B"), ("C",)) == "A, B (ft. C)"
  assert render_credit(("A",), ()) == "A"
