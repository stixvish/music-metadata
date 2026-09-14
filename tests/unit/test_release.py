import pytest

from music_metadata.release import (
  ReleaseCandidate,
  choose_release,
  earliest_release_date,
)


def cand(
  album="Album",
  album_type="album",
  total_tracks=12,
  release_date="2020-01-01",
  track_number=1,
  disc_number=1,
  **kw,
):
  return ReleaseCandidate(
    album_name=album,
    album_type=album_type,
    album_artists=kw.get("album_artists", ("Artist",)),
    total_tracks=total_tracks,
    release_date=release_date,
    track_number=track_number,
    disc_number=disc_number,
    track_name=kw.get("track_name", "Track"),
    track_artists=kw.get("track_artists", ("Artist",)),
    duration_ms=kw.get("duration_ms", 200_000),
    album_id=kw.get("album_id", "alb"),
    track_id=kw.get("track_id", "trk"),
    image_url=kw.get("image_url"),
  )


def test_no_candidates_returns_none():
  assert choose_release([]) is None


def test_a_single_candidate_is_chosen():
  only = cand(album="Desperado", album_type="single", total_tracks=1)

  assert choose_release([only]) is only


# --- clause 1: type ----------------------------------------------------------


def test_album_beats_single():
  """§7b: this is what picks No Strings Attached over the Bye Bye Bye single."""
  album = cand(album="No Strings Attached", album_type="album", total_tracks=12)
  single = cand(album="Bye Bye Bye", album_type="single", total_tracks=2)

  assert choose_release([single, album]) is album


def test_single_beats_compilation():
  single = cand(album="Single", album_type="single", total_tracks=3)
  comp = cand(album="Now 42", album_type="compilation", total_tracks=50)

  assert choose_release([comp, single]) is single


def test_a_compilation_is_chosen_only_when_nothing_else_exists():
  comp = cand(album="Now 42", album_type="compilation", total_tracks=50)

  assert choose_release([comp]) is comp


# --- clause 2: one-track releases sort last ----------------------------------


def test_a_one_track_single_loses_to_a_multi_track_single():
  """§7b Kamariya: the promo is earlier, the soundtrack is correct."""
  promo = cand(
    album='Kamariya (From "Stree")',
    album_type="single",
    total_tracks=1,
    release_date="2018-08-09",
  )
  parent = cand(
    album="Stree",
    album_type="single",
    total_tracks=4,
    track_number=2,
    release_date="2018-08-22",
  )

  assert choose_release([promo, parent]) is parent


def test_the_promo_clause_beats_the_date_clause():
  """ranking on date alone finds the promo; that is the bug §7b fixes."""
  promo = cand(album_type="single", total_tracks=1, release_date="2018-01-01")
  parent = cand(album_type="single", total_tracks=4, release_date="2019-01-01")

  assert choose_release([promo, parent]) is parent


def test_a_one_track_album_also_sorts_last():
  one = cand(album_type="album", total_tracks=1, release_date="2019-01-01")
  many = cand(album_type="album", total_tracks=10, release_date="2020-01-01")

  assert choose_release([one, many]) is many


# --- clause 3: standard edition over deluxe ----------------------------------


def test_the_standard_edition_is_preferred_over_the_bonus_version():
  """§7b NAV: 'most tracks' picked the bonus edition, which was the old bug."""
  standard = cand(
    album="Demons Protected By Angels",
    total_tracks=19,
    track_number=4,
    release_date="2022-09-09",
  )
  bonus = cand(
    album="Demons Protected By Angels (Bonus Version)",
    total_tracks=20,
    track_number=4,
    release_date="2022-09-14",
  )

  assert choose_release([bonus, standard]) is standard


def test_more_tracks_does_not_win():
  """the explicit anti-requirement: ranking by total_tracks broke deluxes."""
  standard = cand(album="Album", total_tracks=19, release_date="2022-09-09")
  bonus = cand(album="Album (Deluxe)", total_tracks=40, release_date="2022-09-09")

  assert choose_release([bonus, standard]) is standard


@pytest.mark.parametrize(
  "name",
  [
    "Album (Deluxe)",
    "Album (Deluxe Edition)",
    "Album (Bonus Version)",
    "Album (Expanded Edition)",
    "Album (Special Edition)",
    "Album (Anniversary Edition)",
    "Album [Deluxe]",
  ],
)
def test_edition_variants_are_recognised(name):
  standard = cand(album="Album", release_date="2022-01-02")
  variant = cand(album=name, release_date="2022-01-01")

  assert choose_release([variant, standard]) is standard


def test_a_deluxe_is_chosen_when_it_is_the_only_release():
  deluxe = cand(album="Album (Deluxe)")

  assert choose_release([deluxe]) is deluxe


def test_the_preference_can_be_switched_off():
  """§7b: set it false to take whichever release the ranking picks."""
  standard = cand(album="Album", release_date="2022-09-09")
  deluxe = cand(album="Album (Deluxe)", release_date="2022-09-01")

  assert choose_release([standard, deluxe], prefer_standard_edition=False) is deluxe


# --- clause 4: earliest ------------------------------------------------------


def test_the_earliest_of_equal_releases_wins():
  later = cand(release_date="2021-06-01")
  earlier = cand(release_date="2020-01-01")

  assert choose_release([later, earlier]) is earlier


def test_partial_dates_sort_before_fuller_ones_in_the_same_year():
  year_only = cand(release_date="2020")
  full = cand(release_date="2020-06-01")

  assert choose_release([full, year_only]) is year_only


# --- F33: the date comes from a different row than the album -----------------


def test_earliest_release_date_spans_every_candidate():
  """F33: year/date is MIN across ALL releases, not the chosen release's date."""
  chosen = cand(album_type="album", release_date="2000-03-21")
  single = cand(album_type="single", total_tracks=1, release_date="2000-01-17")

  assert earliest_release_date([chosen, single]) == "2000-01-17"


def test_the_chosen_album_and_the_earliest_date_can_disagree():
  """§7b NAV: tagged 2022-07-29 (the single) on the album 4/19. Both are true."""
  album = cand(
    album="Demons Protected By Angels", total_tracks=19, release_date="2022-09-09"
  )
  promo = cand(album_type="single", total_tracks=1, release_date="2022-07-29")

  assert choose_release([album, promo]) is album
  assert earliest_release_date([album, promo]) == "2022-07-29"


def test_earliest_release_date_of_nothing_is_none():
  assert earliest_release_date([]) is None


def test_earliest_ignores_unparseable_dates():
  good = cand(release_date="2001-05-05")
  junk = cand(release_date="")

  assert earliest_release_date([junk, good]) == "2001-05-05"


def test_a_non_numeric_date_sorts_last_rather_than_crashing():
  """spotify has sent malformed dates; one must not lose the other releases."""
  junk = cand(release_date="not-a-date")
  good = cand(release_date="2010-01-01")

  assert choose_release([junk, good]) is good
  assert earliest_release_date([junk, good]) == "2010-01-01"
