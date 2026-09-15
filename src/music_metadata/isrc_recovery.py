"""recovering an ISRC from a link the operator pasted (SPEC.md F19, F62).

this exists because of one measured asymmetry: **the domain in a youtube link
means nothing and the video id means everything.**

```text
music.youtube.com/watch?v=fxHjlCBHuzA   -> USJI10000001
      youtube.com/watch?v=fxHjlCBHuzA   -> USJI10000001   same id, same answer
music.youtube.com/watch?v=Eo-KmOd3i7s   -> nothing
      youtube.com/watch?v=Eo-KmOd3i7s   -> nothing        same id, same answer
```

`fxHjlCBHuzA` is the *track* — an auto-generated "art track" that maps to a
release. `Eo-KmOd3i7s` is the *official video*, a separate upload that maps to
no release at all. both are "the song on youtube" to a human, and the pages look
identical, so **the operator cannot be expected to tell them apart**.

so when a video is pasted, this does not report a failure. it takes the title
musicfetch read off the video, searches youtube music for the track, and
resolves that instead — which is what the operator meant.

**nothing is returned without the duration agreeing with the file** (G10). the
recovery path is a search, and a search can land on the wrong recording; the
`(Official Video)` upload of a song is also frequently a different length from
the release. the check is what makes the convenience safe.
"""

from __future__ import annotations

import enum
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from music_metadata.dedup import DURATION_TOLERANCE_S
from music_metadata.sources.base import SourceError
from music_metadata.sources.musicfetch import Musicfetch

# a youtube id is 11 characters; the search also returns channel and playlist
# ids, which are longer and are not things we can resolve.
_ID_LENGTH = 11

# how many search results to try before giving up. the right track is the first
# result in every measured case; this is headroom, not an expectation.
_MAX_CANDIDATES = 4

# noise in a video title that hurts a music search.
_TITLE_NOISE = (
  "(official video)",
  "(official music video)",
  "(official audio)",
  "(lyric video)",
  "(official lyric video)",
  "(visualizer)",
  "[official video]",
  "[official audio]",
)


class Status(enum.StrEnum):
  """what happened, in terms the operator can act on."""

  OK = "ok"
  RECOVERED = "recovered-from-video"
  VIDEO_UNRESOLVED = "video-unresolved"
  DURATION_MISMATCH = "duration-mismatch"
  NOT_FOUND = "not-found"
  ERROR = "error"


@dataclass(frozen=True, slots=True)
class Recovery:
  """one pasted link, and what became of it."""

  status: Status
  isrc: str | None = None
  name: str | None = None
  artists: tuple[str, ...] = ()
  duration_s: float | None = None
  note: str = ""

  @property
  def usable(self) -> bool:
    """Whether this ISRC may be written to the map."""
    return self.isrc is not None and self.status in (Status.OK, Status.RECOVERED)

  @property
  def who(self) -> str:
    """The artists as one string."""
    return ", ".join(self.artists)


def clean_title(title: str) -> str:
  """Strip the marketing suffixes a video upload carries.

  Args:
    title: the video's title.

  Returns:
    A string better suited to a music search.
  """
  out = title
  lowered = out.lower()
  for noise in _TITLE_NOISE:
    index = lowered.find(noise)
    if index != -1:
      out = out[:index] + out[index + len(noise) :]
      lowered = out.lower()
  return " ".join(out.split())


def search_youtube_music(query: str) -> list[str]:
  """Return youtube music video ids matching a query, best first.

  Args:
    query: what to search for.

  Returns:
    Track ids. Empty when yt-dlp is unavailable or the search fails — the
    caller degrades to reporting an unresolved video, never crashes.
  """
  # resolved rather than named, so PATH cannot decide which binary this is.
  yt_dlp = shutil.which("yt-dlp")
  if yt_dlp is None:
    return []
  try:
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
      [
        yt_dlp,
        "--flat-playlist",
        "--playlist-end",
        str(_MAX_CANDIDATES),
        "--print",
        "%(id)s",
        f"https://music.youtube.com/search?q={query}",
      ],
      capture_output=True,
      text=True,
      timeout=90,
      check=False,
    )
  except (OSError, subprocess.SubprocessError):
    return []
  return [
    line.strip()
    for line in completed.stdout.splitlines()
    if len(line.strip()) == _ID_LENGTH
  ]


def _url_for(video_id: str) -> str:
  """Build a youtube music url for an id.

  Args:
    video_id: the 11-character id.

  Returns:
    The url.
  """
  return f"https://music.youtube.com/watch?v={video_id}"


def recover(
  url: str,
  client: Musicfetch,
  local_duration_s: float | None = None,
  search: Callable[[str], Sequence[str]] = search_youtube_music,
  tolerance_s: float = DURATION_TOLERANCE_S,
) -> Recovery:
  """Resolve a pasted link to an ISRC, recovering from a video link if needed.

  Args:
    url: what the operator pasted.
    client: the musicfetch client.
    local_duration_s: the file's own duration, when known. Without it no
      duration check is possible and the result is returned unverified.
    search: injectable youtube music search, so tests need no network.
    tolerance_s: the permitted duration difference (G10).

  Returns:
    What was found, and whether it may be used.
  """
  try:
    match = client.isrc_for_url(url)
  except SourceError as exc:
    return Recovery(status=Status.ERROR, note=str(exc))

  if match.isrc:
    return _verified(match.isrc, match, local_duration_s, tolerance_s, Status.OK)

  if not match.looks_like_a_video:
    return Recovery(
      status=Status.NOT_FOUND,
      note="musicfetch could not place this link.",
    )

  # the operator pasted the video. find the track they meant.
  title = clean_title(match.name or "")
  if not title:
    return Recovery(
      status=Status.VIDEO_UNRESOLVED,
      note="this is a video upload, and it carries no title to search by.",
    )

  for video_id in list(search(title))[:_MAX_CANDIDATES]:
    try:
      candidate = client.isrc_for_url(_url_for(video_id))
    except SourceError:
      continue
    if not candidate.isrc:
      continue
    found = _verified(
      candidate.isrc, candidate, local_duration_s, tolerance_s, Status.RECOVERED
    )
    if found.usable:
      return found
  return Recovery(
    status=Status.VIDEO_UNRESOLVED,
    name=match.name,
    note=(
      f"this is a video upload, not a track — no release is behind it. "
      f"searching youtube music for {title!r} found no matching track either; "
      f"open the song in youtube music and paste that link instead."
    ),
  )


def _verified(
  isrc: str,
  match: object,
  local_duration_s: float | None,
  tolerance_s: float,
  status: Status,
) -> Recovery:
  """Apply G10's duration check to a candidate ISRC.

  Args:
    isrc: the recovered ISRC.
    match: the musicfetch result it came from.
    local_duration_s: the file's duration, when known.
    tolerance_s: the permitted difference.
    status: the status to report on success.

  Returns:
    The recovery, with `DURATION_MISMATCH` when the lengths disagree.
  """
  name = getattr(match, "name", None)
  artists = getattr(match, "artists", ())
  theirs = getattr(match, "duration_s", None)
  note = ""
  if status is Status.RECOVERED:
    note = "recovered from a video link by searching youtube music."

  if local_duration_s and theirs:
    delta = abs(theirs - local_duration_s)
    if delta > tolerance_s:
      return Recovery(
        status=Status.DURATION_MISMATCH,
        isrc=isrc,
        name=name,
        artists=artists,
        duration_s=theirs,
        note=(
          f"{isrc} is {theirs:.0f}s but this file is {local_duration_s:.0f}s "
          f"— {delta:.0f}s apart, so it is a different recording (G10)."
        ),
      )
  return Recovery(
    status=status,
    isrc=isrc,
    name=name,
    artists=artists,
    duration_s=theirs,
    note=note,
  )
