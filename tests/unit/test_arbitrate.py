import dataclasses
from pathlib import Path

from music_metadata.arbitrate import (
  FILE_TAG,
  FILENAME,
  FLAG_NO_ISRC,
  FLAG_NO_RELEASE,
  MANUAL,
  SPOTIFY,
  arbitrate,
  year_of,
)
from music_metadata.probe import ProbedFile
from music_metadata.release import ReleaseCandidate


def probed(name="*NSYNC - Bye Bye Bye.aiff", isrc="USJI10000001", duration=200.4):
  return ProbedFile(
    path=Path(name),
    audio_md5="8ab13f549542ec73ee5d8da7c62dd6a4",
    duration_s=duration,
    isrc=isrc,
    tags={},
  )


def cand(
  album="No Strings Attached",
  album_type="album",
  total_tracks=12,
  release_date="2000-03-21",
  track_number=1,
  track_name="Bye Bye Bye",
  track_artists=("*NSYNC",),
  album_artists=("*NSYNC",),
):
  return ReleaseCandidate(
    album_name=album,
    album_type=album_type,
    album_artists=album_artists,
    total_tracks=total_tracks,
    release_date=release_date,
    track_number=track_number,
    disc_number=1,
    track_name=track_name,
    track_artists=track_artists,
    duration_ms=200_400,
    album_id="alb",
    track_id="trk",
  )


SINGLE = cand(
  album="Bye Bye Bye", album_type="single", total_tracks=1, release_date="2000-01-17"
)


# --- the §5a worked example --------------------------------------------------


def test_the_worked_example_from_section_5a():
  got = arbitrate(probed(), [cand(), SINGLE])

  assert got.tags.title == "Bye Bye Bye"
  assert got.tags.album == "No Strings Attached"
  assert got.tags.album_artist == "*NSYNC"
  assert (got.tags.track_number, got.tags.track_count) == (1, 12)
  assert got.tags.disc_number == 1


def test_the_date_is_the_earliest_not_the_chosen_release():
  """F33: these come from different rows of the same response."""
  got = arbitrate(probed(), [cand(), SINGLE])

  assert got.tags.date == "2000-01-17"
  assert year_of(got) == "2000"


def test_the_isrc_is_the_file_s_own():
  """§7: the file's own tag is the first source for ISRC."""
  got = arbitrate(probed(), [cand()])

  assert got.tags.isrc == "USJI10000001"
  assert got.provenance["isrc"] == FILE_TAG


# --- provenance is a requirement, not diagnostics ----------------------------


def test_every_written_field_names_a_source():
  """§4: every tagged field traces to a named source, recorded per track."""
  got = arbitrate(probed(), [cand(), SINGLE])

  written = {
    f.name
    for f in dataclasses.fields(got.tags)
    if getattr(got.tags, f.name) is not None
    and f.name not in {"artwork", "artwork_mime", "track_count"}
  }
  assert written <= set(got.provenance) | {"year"}


def test_album_fields_are_attributed_to_spotify():
  got = arbitrate(probed(), [cand()])

  assert got.provenance["album"] == SPOTIFY
  assert got.provenance["track_number"] == SPOTIFY


# --- §7a shape ---------------------------------------------------------------


def test_a_dash_suffix_becomes_the_mix_not_part_of_the_title():
  got = arbitrate(
    probed(name="Calvin Harris - Blessings.aiff", isrc="GBARL2501127"),
    [cand(track_name="Blessings - Odd Mob Remix", track_artists=("Calvin Harris",))],
  )

  assert got.tags.title == "Blessings [Odd Mob Remix]"
  assert got.tags.mix_name == "Odd Mob Remix"


def test_a_remix_sets_the_remixer_and_original_artist():
  """§7d: TOPE is meaningful only on remixes."""
  got = arbitrate(
    probed(name="Calvin Harris - Blessings.aiff"),
    [cand(track_name="Blessings - Odd Mob Remix", track_artists=("Calvin Harris",))],
  )

  assert got.tags.remixer == "Odd Mob"
  assert got.tags.original_artist == "Calvin Harris"


def test_an_extended_mix_sets_no_remixer():
  """§7a: the original artist reworking their own track is not a remixer."""
  got = arbitrate(probed(), [cand(track_name="Blessings - Extended Mix")])

  assert got.tags.mix_name == "Extended"
  assert got.tags.remixer is None
  assert got.tags.original_artist is None


def test_a_feature_moves_into_the_title_parenthetical():
  """OQ-4 option A: the feature lives in the title, not the artist."""
  got = arbitrate(
    probed(name="Dua Lipa - Levitating.aiff"),
    [
      cand(track_name="Levitating (feat. DaBaby)", track_artists=("Dua Lipa", "DaBaby"))
    ],
  )

  assert got.tags.title == "Levitating (ft. DaBaby)"
  assert got.tags.artist == "Dua Lipa"


def test_a_feature_never_reaches_the_album_artist():
  """§6: get it wrong and a feature fragments the album in rekordbox."""
  got = arbitrate(
    probed(),
    [
      cand(
        track_name="Levitating (feat. DaBaby)",
        track_artists=("Dua Lipa", "DaBaby"),
        album_artists=("Dua Lipa",),
      )
    ],
  )

  assert got.tags.album_artist == "Dua Lipa"


def test_multiple_main_artists_use_the_house_separator():
  got = arbitrate(probed(), [cand(track_artists=("A", "B", "C"))])

  assert got.tags.artist == "A, B & C"


# --- the operator's own values outrank every source (§7) ---------------------


def test_a_hand_edited_value_wins():
  got = arbitrate(probed(), [cand()], overrides={"album": "What I Say It Is"})

  assert got.tags.album == "What I Say It Is"
  assert got.provenance["album"] == MANUAL


def test_an_empty_override_does_not_win():
  """§9b: clearing a line returns that field to resolver control."""
  got = arbitrate(probed(), [cand()], overrides={"album": ""})

  assert got.tags.album == "No Strings Attached"
  assert got.provenance["album"] == SPOTIFY


def test_an_unknown_override_key_is_ignored():
  got = arbitrate(probed(), [cand()], overrides={"not_a_field": "x"})

  assert got.tags.album == "No Strings Attached"


# --- degrading honestly ------------------------------------------------------


def test_no_release_falls_back_to_the_filename_and_flags():
  got = arbitrate(probed(name="Arijit Singh - Roke Na Ruke Naina.aiff"), [])

  assert FLAG_NO_RELEASE in got.flags
  assert got.tags.title == "Roke Na Ruke Naina"
  assert got.tags.artist == "Arijit Singh"
  assert got.provenance["artist"] == FILENAME


def test_a_file_with_no_isrc_is_flagged():
  got = arbitrate(probed(isrc=None), [])

  assert FLAG_NO_ISRC in got.flags


def test_a_filename_feature_is_parsed_in_the_fallback():
  got = arbitrate(
    probed(name="Arizona Zervas - OH MY LORD (ft. 24kGoldn).aiff", isrc=None), []
  )

  assert got.tags.title == "OH MY LORD (ft. 24kGoldn)"
  assert got.tags.artist == "Arizona Zervas"


def test_fields_no_source_supplies_are_left_empty_not_invented():
  """§7e's position on BPM, applied generally: a guessed field gets trusted."""
  got = arbitrate(probed(), [cand()])

  assert got.tags.bpm is None
  assert got.tags.key is None
  assert got.tags.genre is None
  assert got.tags.label is None


def test_a_numeric_override_is_coerced():
  """library.toml is text; Tags carries ints. a string in TRCK is nonsense."""
  got = arbitrate(probed(), [cand()], overrides={"track_number": "7"})

  assert got.tags.track_number == 7
  assert isinstance(got.tags.track_number, int)


def test_a_non_numeric_override_of_a_numeric_field_is_ignored():
  got = arbitrate(probed(), [cand()], overrides={"track_number": "seven"})

  assert got.tags.track_number == 1


def test_artwork_cannot_be_overridden_as_text():
  got = arbitrate(probed(), [cand()], overrides={"artwork": "not-bytes"})

  assert got.tags.artwork is None
