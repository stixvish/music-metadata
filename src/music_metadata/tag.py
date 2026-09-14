"""the ID3-on-AIFF writer (SPEC.md §7d).

two rules govern everything here.

**nothing outside §7d's table is written.** the field set is closed; an empty
`TOPE` is noise, and rekordbox shows the column whether or not it holds a value.

**frames we do not own are preserved.** serato keeps beatgrids and cue points in
`GEOB` frames in the same tag we write, and rekordbox writes its own. a rewrite
that drops them destroys the operator's work in a different application — which
`CLAUDE.md` lists as a working agreement, not a nicety. so this module deletes
*only* the frames it manages and leaves every other frame untouched.

mutagen is used because it is the only library that writes AIFF ID3 chunks
correctly (§12).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from mutagen.aiff import AIFF
from mutagen.id3 import (
  APIC,
  ID3,
  TALB,
  TBPM,
  TCOM,
  TCON,
  TDRC,
  TDRL,
  TEXT,
  TIT2,
  TIT3,
  TKEY,
  TOPE,
  TPE1,
  TPE2,
  TPE4,
  TPOS,
  TPUB,
  TRCK,
  TSRC,
)

# the front cover, per the ID3 picture-type table.
_APIC_FRONT_COVER = 3


@dataclass(frozen=True, slots=True)
class Tags:
  """every field this project writes, and nothing else (§7d)."""

  title: str | None = None
  artist: str | None = None
  album: str | None = None
  album_artist: str | None = None
  date: str | None = None
  track_number: int | None = None
  track_count: int | None = None
  disc_number: int | None = None
  disc_count: int | None = None
  genre: str | None = None
  label: str | None = None
  isrc: str | None = None
  mix_name: str | None = None
  remixer: str | None = None
  original_artist: str | None = None
  composer: str | None = None
  lyricist: str | None = None
  bpm: int | None = None
  key: str | None = None
  artwork: bytes | None = None
  artwork_mime: str | None = None


# field -> frame class, for the plain text frames. `TDRL` is written from the
# same date as `TDRC` so both carry the recording's earliest release (F33).
_TEXT_FRAMES = (
  ("title", TIT2),
  ("artist", TPE1),
  ("album", TALB),
  ("album_artist", TPE2),
  ("genre", TCON),
  ("label", TPUB),
  ("isrc", TSRC),
  ("mix_name", TIT3),
  ("remixer", TPE4),
  ("original_artist", TOPE),
  ("composer", TCOM),
  ("lyricist", TEXT),
  ("key", TKEY),
)

# every frame this module owns. these are cleared before a write; anything else
# in the tag belongs to another tool and is left alone.
_OWNED = (
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
)


def _number_of_total(number: int | None, total: int | None) -> str | None:
  """Render `TRCK`/`TPOS` as `n/total`, or bare when there is no total.

  Args:
    number: the track or disc number.
    total: the count on the release, if known.

  Returns:
    The frame text, or None when there is no number.
  """
  if number is None:
    return None
  return f"{number}/{total}" if total else str(number)


class TagError(RuntimeError):
  """raised when a file cannot be tagged."""


def _open(path: Path) -> tuple[AIFF, ID3]:
  """Open an AIFF, giving it an ID3 chunk if it has none.

  The `AIFF` wrapper is used rather than `ID3` directly because ID3 on AIFF
  lives inside an IFF chunk: saving a bare `ID3` writes a raw ID3 stream and
  loses the container.

  Args:
    path: the AIFF file.

  Returns:
    The open file and its tag.

  Raises:
    TagError: if the file will not accept an ID3 chunk.
  """
  audio = AIFF(path)
  if audio.tags is None:
    audio.add_tags()
  id3 = audio.tags
  if id3 is None:
    msg = f"could not add an ID3 chunk to {path}"
    raise TagError(msg)
  return audio, id3


def write_tags(path: Path, tags: Tags) -> None:
  """Write `tags` to the file, preserving every frame this module does not own.

  Args:
    path: the AIFF file to tag.
    tags: the values to write. Fields left None are not written, and any stale
      value this module previously wrote for them is cleared.
  """
  audio, id3 = _open(path)

  # clear only our own frames. a blanket delete would take serato's GEOB
  # beatgrids and rekordbox's frames with it.
  for name in _OWNED:
    id3.delall(name)

  for field, frame in _TEXT_FRAMES:
    value = getattr(tags, field)
    if value:
      id3.add(frame(encoding=3, text=[str(value)]))

  if tags.date:
    id3.add(TDRC(encoding=3, text=[tags.date]))
    id3.add(TDRL(encoding=3, text=[tags.date]))

  track = _number_of_total(tags.track_number, tags.track_count)
  if track:
    id3.add(TRCK(encoding=3, text=[track]))

  disc = _number_of_total(tags.disc_number, tags.disc_count)
  if disc:
    id3.add(TPOS(encoding=3, text=[disc]))

  if tags.bpm is not None:
    id3.add(TBPM(encoding=3, text=[str(tags.bpm)]))

  if tags.artwork:
    id3.add(
      APIC(
        encoding=3,
        mime=tags.artwork_mime or "image/jpeg",
        type=_APIC_FRONT_COVER,
        desc="Cover (front)",
        data=tags.artwork,
      )
    )

  audio.save()


def _text(id3: ID3, frame: str) -> str | None:
  """Read one text frame.

  Args:
    id3: the tag.
    frame: the frame name.

  Returns:
    The first text value, or None if the frame is absent.
  """
  if frame not in id3:
    return None
  values = id3[frame].text
  return str(values[0]) if values else None


def _split_number(value: str | None) -> tuple[int | None, int | None]:
  """Parse `n/total` into its parts.

  Args:
    value: the frame text.

  Returns:
    The number and the total, either of which may be None.
  """
  if not value:
    return (None, None)
  number, _, total = value.partition("/")
  try:
    return (int(number), int(total) if total else None)
  except ValueError:
    return (None, None)


def read_tags(path: Path) -> Tags:
  """Read back the fields this module writes.

  Args:
    path: the AIFF file.

  Returns:
    The tags found. Frames owned by other tools are not reported.
  """
  id3 = AIFF(path).tags
  if id3 is None:
    return Tags()

  track_number, track_count = _split_number(_text(id3, "TRCK"))
  disc_number, disc_count = _split_number(_text(id3, "TPOS"))

  bpm_text = _text(id3, "TBPM")
  try:
    bpm = int(bpm_text) if bpm_text else None
  except ValueError:
    bpm = None

  pictures = id3.getall("APIC")
  tags = Tags(
    date=_text(id3, "TDRC"),
    track_number=track_number,
    track_count=track_count,
    disc_number=disc_number,
    disc_count=disc_count,
    bpm=bpm,
    artwork=pictures[0].data if pictures else None,
    artwork_mime=pictures[0].mime if pictures else None,
  )
  return replace(tags, **{f: _text(id3, c.__name__) for f, c in _TEXT_FRAMES})
