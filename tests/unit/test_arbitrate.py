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
from music_metadata.credit import FLAG_CREDIT_DISAGREEMENT
from music_metadata.probe import ProbedFile
from music_metadata.release import ReleaseCandidate
from music_metadata.sources.musicbrainz import Credit, Work


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
  got = arbitrate(
    probed(name="A, B & C - Track.aiff"), [cand(track_artists=("A", "B", "C"))]
  )

  assert got.tags.artist == "A, B & C"


def test_the_filename_outranks_spotify_for_artist():
  """§6 ranks the filename second, above spotify — it is the operator's own
  curation, and it agreed with musicbrainz on every case where both existed."""
  got = arbitrate(
    probed(name="*NSYNC - Bye Bye Bye.aiff"), [cand(track_artists=("N Sync",))]
  )

  assert got.tags.artist == "*NSYNC"


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


# --- musicbrainz: credit, and the writing credits (§6, §7d, F52) -------------


def test_musicbrainz_decides_the_credit_when_it_has_the_recording():
  got = arbitrate(
    probed(name="Calvin Harris - Sweet Nothing (ft. Florence Welch).aiff"),
    [
      cand(
        track_name="Sweet Nothing", track_artists=("Calvin Harris", "Florence Welch")
      )
    ],
    musicbrainz=Credit(main=("Calvin Harris",), featured=("Florence Welch",)),
  )

  assert got.tags.artist == "Calvin Harris"
  assert got.tags.title == "Sweet Nothing (ft. Florence Welch)"
  assert got.provenance["artist"] == "musicbrainz"


def test_a_credit_disagreement_is_flagged():
  """G6: disagreements are queued for review, never auto-resolved."""
  got = arbitrate(
    probed(name="Someone Else - Track.aiff"),
    [cand(track_name="Track")],
    musicbrainz=Credit(main=("The Real Artist",), featured=()),
  )

  assert FLAG_CREDIT_DISAGREEMENT in got.flags


def test_composer_and_lyricist_are_written_when_musicbrainz_names_them():
  """F52: measured 10/10 on indian repertoire, where §7a scopes the rule."""
  got = arbitrate(
    probed(name="Arijit Singh - Channa Mereya.aiff", isrc="INS171602370"),
    [cand(track_name="Channa Mereya", track_artists=("Arijit Singh",))],
    work=Work(composers=("Pritam",), lyricists=("Amitabh Bhattacharya",), writers=()),
  )

  assert got.tags.composer == "Pritam"
  assert got.tags.lyricist == "Amitabh Bhattacharya"
  assert got.provenance["composer"] == "musicbrainz"


def test_a_bare_writer_is_not_promoted_to_composer():
  """F52: `writer` records that someone wrote it, not which role they held.

  promoting it would assert a role musicbrainz deliberately left unstated, and
  §7f's rule applies — a wrong value gets trusted.
  """
  got = arbitrate(
    probed(),
    [cand()],
    work=Work(composers=(), lyricists=(), writers=("Calvin Harris", "Kid Harpoon")),
  )

  assert got.tags.composer is None
  assert got.tags.lyricist is None


def test_several_composers_use_the_house_separator():
  got = arbitrate(
    probed(),
    [cand()],
    work=Work(composers=("A", "B", "C"), lyricists=(), writers=()),
  )

  assert got.tags.composer == "A, B & C"


def test_indian_scope_refuses_spotifys_artist_list():
  """§7a / F29: spotify inverts roles on bollywood, promoting music directors.

  an indian track with no musicbrainz and no filename credit is flagged rather
  than given a list that names the wrong people.
  """
  got = arbitrate(
    probed(name="Untitled.aiff", isrc="INS181801821"),
    [cand(track_artists=("Some Music Director", "A Singer"))],
  )

  assert got.tags.artist is None
  assert "no-performer-credit" in got.flags


def test_western_repertoire_still_uses_spotify_as_a_fallback():
  """applying the indian rule globally would strip real main artists."""
  got = arbitrate(
    probed(name="Untitled.aiff", isrc="USJI10000001"),
    [cand(track_artists=("Metro Boomin",))],
  )

  assert got.tags.artist == "Metro Boomin"


def test_the_losing_reading_reaches_the_review_queue():
  got = arbitrate(
    probed(name="A Boogie Wit da Hoodie - Chanelly (ft. Don Q).aiff"),
    [cand(track_name="Chanelly", track_artists=("A Boogie Wit da Hoodie",))],
    musicbrainz=Credit(main=("A Boogie Wit da Hoodie",), featured=()),
  )

  assert "Don Q" in got.alternatives[FLAG_CREDIT_DISAGREEMENT]
