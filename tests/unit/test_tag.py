import shutil
import subprocess

import pytest
from mutagen.aiff import AIFF
from mutagen.id3 import GEOB, TXXX

from music_metadata.tag import Tags, read_tags, write_tags

pytestmark = pytest.mark.skipif(
  not shutil.which("ffmpeg"), reason="ffmpeg not installed"
)


@pytest.fixture
def aiff(tmp_path):
  path = tmp_path / "track.aiff"
  subprocess.run(
    [
      "ffmpeg",
      "-v",
      "error",
      "-y",
      "-f",
      "lavfi",
      "-i",
      "sine=frequency=440:duration=1",
      "-c:a",
      "pcm_s16be",
      "-ar",
      "44100",
      str(path),
    ],
    check=True,
    capture_output=True,
  )
  return path


FULL = Tags(
  title="Blessings (ft. Clementine Douglas) [Odd Mob Remix]",
  artist="Calvin Harris, Clementine Douglas & Odd Mob",
  album="Blessings - The Remixes (Part 2)",
  album_artist="Calvin Harris & Clementine Douglas",
  date="2025-08-01",
  track_number=4,
  track_count=6,
  disc_number=1,
  disc_count=1,
  genre="House",
  label="Columbia",
  isrc="GBARL2501127",
  mix_name="Odd Mob Remix",
  remixer="Odd Mob",
  original_artist="Calvin Harris, Clementine Douglas",
  composer="C. Harris",
  lyricist="C. Douglas",
  bpm=128,
  key="8A",
)


# --- the non-negotiable: another tool's data survives ------------------------


def test_a_serato_geob_frame_survives_a_rewrite(aiff):
  """CLAUDE.md: never destroy another tool's data.

  serato keeps beatgrids and cue points in GEOB frames. a tag write that drops
  them silently destroys the operator's work in a different application.
  """
  audio = AIFF(aiff)
  audio.add_tags()
  audio.tags.add(
    GEOB(
      encoding=0,
      mime="application/octet-stream",
      desc="Serato Markers2",
      data=b"\x01\x02beatgrid",
    )
  )
  audio.save()

  write_tags(aiff, FULL)

  after = AIFF(aiff).tags
  frames = after.getall("GEOB")
  assert len(frames) == 1
  assert frames[0].desc == "Serato Markers2"
  assert frames[0].data == b"\x01\x02beatgrid"


def test_several_foreign_frames_all_survive(aiff):
  audio = AIFF(aiff)
  audio.add_tags()
  for desc, data in [("Serato Markers2", b"a"), ("Serato BeatGrid", b"b")]:
    audio.tags.add(
      GEOB(encoding=0, mime="application/octet-stream", desc=desc, data=data)
    )
  audio.tags.add(TXXX(encoding=3, desc="SERATO_PLAYCOUNT", text=["12"]))
  audio.save()

  write_tags(aiff, FULL)

  after = AIFF(aiff).tags
  assert {f.desc for f in after.getall("GEOB")} == {
    "Serato Markers2",
    "Serato BeatGrid",
  }
  assert after.getall("TXXX")[0].text == ["12"]


def test_rewriting_twice_does_not_duplicate_foreign_frames(aiff):
  audio = AIFF(aiff)
  audio.add_tags()
  audio.tags.add(
    GEOB(encoding=0, mime="application/octet-stream", desc="Serato Markers2", data=b"a")
  )
  audio.save()

  write_tags(aiff, FULL)
  write_tags(aiff, FULL)

  assert len(AIFF(aiff).tags.getall("GEOB")) == 1


# --- the frames §7d specifies ------------------------------------------------


def test_every_field_round_trips(aiff):
  write_tags(aiff, FULL)

  assert read_tags(aiff) == FULL


@pytest.mark.parametrize(
  ("frame", "expected"),
  [
    ("TIT2", "Blessings (ft. Clementine Douglas) [Odd Mob Remix]"),
    ("TPE1", "Calvin Harris, Clementine Douglas & Odd Mob"),
    ("TALB", "Blessings - The Remixes (Part 2)"),
    ("TPE2", "Calvin Harris & Clementine Douglas"),
    ("TCON", "House"),
    ("TPUB", "Columbia"),
    ("TSRC", "GBARL2501127"),
    ("TIT3", "Odd Mob Remix"),
    ("TPE4", "Odd Mob"),
    ("TOPE", "Calvin Harris, Clementine Douglas"),
    ("TCOM", "C. Harris"),
    ("TEXT", "C. Douglas"),
    ("TBPM", "128"),
    ("TKEY", "8A"),
  ],
)
def test_fields_land_in_the_right_id3_frame(aiff, frame, expected):
  """§7d names the frame for every field; nothing outside that table is written."""
  write_tags(aiff, FULL)

  assert str(AIFF(aiff).tags[frame].text[0]) == expected


def test_track_and_disc_are_written_as_number_of_total(aiff):
  write_tags(aiff, FULL)
  tags = AIFF(aiff).tags

  assert str(tags["TRCK"].text[0]) == "4/6"
  assert str(tags["TPOS"].text[0]) == "1/1"


def test_a_track_without_a_count_is_written_bare(aiff):
  write_tags(aiff, Tags(title="x", track_number=3))

  assert str(AIFF(aiff).tags["TRCK"].text[0]) == "3"


def test_the_date_lands_in_tdrc(aiff):
  write_tags(aiff, FULL)

  assert str(AIFF(aiff).tags["TDRC"].text[0]) == "2025-08-01"


# --- what must NOT be written ------------------------------------------------


def test_an_empty_field_writes_no_frame(aiff):
  """§7d: an empty TOPE is noise, and rekordbox shows the column regardless."""
  write_tags(aiff, Tags(title="Blessings", artist="Calvin Harris"))

  tags = AIFF(aiff).tags
  assert "TOPE" not in tags
  assert "TPE4" not in tags
  assert "TBPM" not in tags
  assert "TKEY" not in tags


def test_nothing_outside_the_spec_table_is_written(aiff):
  write_tags(aiff, FULL)

  written = {f[:4] for f in AIFF(aiff).tags}
  allowed = {
    "TIT2",
    "TPE1",
    "TALB",
    "TPE2",
    "TDRC",
    "TDRL",
    "TRCK",
    "TPOS",
    "TCON",
    "TPUB",
    "TSRC",
    "TIT3",
    "TPE4",
    "TOPE",
    "TCOM",
    "TEXT",
    "TBPM",
    "TKEY",
    "APIC",
  }
  assert written <= allowed


def test_a_stale_value_is_cleared_when_the_new_value_is_empty(aiff):
  write_tags(aiff, FULL)
  write_tags(aiff, Tags(title="Blessings"))

  assert "TPE4" not in AIFF(aiff).tags


# --- artwork -----------------------------------------------------------------


def test_artwork_is_embedded_as_apic(aiff):
  jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64

  write_tags(aiff, Tags(title="x", artwork=jpeg, artwork_mime="image/jpeg"))

  apic = AIFF(aiff).tags.getall("APIC")
  assert len(apic) == 1
  assert apic[0].data == jpeg
  assert apic[0].mime == "image/jpeg"


def test_artwork_is_marked_as_the_front_cover(aiff):
  write_tags(aiff, Tags(title="x", artwork=b"\xff\xd8\xff", artwork_mime="image/jpeg"))

  assert AIFF(aiff).tags.getall("APIC")[0].type == 3


def test_replacing_artwork_leaves_only_one_image(aiff):
  write_tags(aiff, Tags(title="x", artwork=b"\xff\xd8\x01", artwork_mime="image/jpeg"))
  write_tags(aiff, Tags(title="x", artwork=b"\xff\xd8\x02", artwork_mime="image/jpeg"))

  apic = AIFF(aiff).tags.getall("APIC")
  assert len(apic) == 1
  assert apic[0].data == b"\xff\xd8\x02"


# --- reading -----------------------------------------------------------------


def test_reading_an_untagged_file_gives_empty_tags(aiff):
  assert read_tags(aiff) == Tags()


def test_reading_parses_track_of_total(aiff):
  write_tags(aiff, FULL)
  got = read_tags(aiff)

  assert (got.track_number, got.track_count) == (4, 6)


def test_the_audio_is_not_altered_by_tagging(aiff):
  before = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", str(aiff), "-map", "0:a", "-f", "md5", "-"],
    check=True,
    capture_output=True,
    text=True,
  ).stdout

  write_tags(aiff, FULL)

  after = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", str(aiff), "-map", "0:a", "-f", "md5", "-"],
    check=True,
    capture_output=True,
    text=True,
  ).stdout
  assert before == after
