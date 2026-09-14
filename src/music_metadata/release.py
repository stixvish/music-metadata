"""choosing which release a recording belongs to (SPEC.md §7b).

every album-level field depends on getting this right. a recording appears on
many releases — the original album, a single, and any number of compilations —
and album, album artist, track number, disc number and even the title string
all change with the choice.

the ranking has four clauses and each earns its place:

1. **type.** album > single > compilation.
2. **one-track releases last.** a 1-track release is a promo, not a home.
   ranking on date alone finds the promo; this clause finds the parent.
3. **standard edition over deluxe.** not for the track number — those usually
   match — but for the album *name*, which lands in `TALB` and sorts.
4. **earliest.** among real releases of the same kind, the first is canonical.

an earlier revision ranked by `total_tracks` descending. it fixed one case and
systematically broke deluxe editions, because a bonus edition always has more
tracks than the standard album. that is why clause 2 counts *one* track rather
than *many*.

the date does **not** come from the chosen release (F33). it is the minimum
across every candidate, because the single precedes the album by design — so
`earliest_release_date` is a separate function over the same list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# album_type ordering: album beats single beats compilation.
_TYPE_RANK = {"album": 0, "single": 1, "compilation": 2}
_UNKNOWN_TYPE_RANK = 3

# a deluxe or bonus edition carries the same recording under a longer album
# name. the name is the only reason to prefer the standard cut.
_EDITION_MARKER = re.compile(
  r"[(\[][^)\]]*\b("
  r"deluxe|bonus|expanded|special|anniversary|collector|"
  r"remaster(ed)?|super|complete|extended\s+edition"
  r")\b[^)\]]*[)\]]",
  re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
  """one release a recording appears on, as spotify describes it."""

  album_name: str
  album_type: str
  album_artists: tuple[str, ...]
  total_tracks: int
  release_date: str
  track_number: int
  disc_number: int
  track_name: str
  track_artists: tuple[str, ...]
  duration_ms: int
  album_id: str
  track_id: str
  image_url: str | None = None

  @property
  def is_edition_variant(self) -> bool:
    """Whether the album name marks this as a deluxe, bonus or expanded cut."""
    return _EDITION_MARKER.search(self.album_name) is not None


def _date_key(release_date: str) -> tuple[int, int, int]:
  """Sort key for a spotify release_date, which may be a year, month or day.

  Args:
    release_date: `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.

  Returns:
    A tuple that sorts chronologically. An unparseable date sorts last.
  """
  parts = release_date.split("-") if release_date else []
  try:
    numbers = [int(p) for p in parts[:3]]
  except ValueError:
    return (9999, 99, 99)
  if not numbers:
    return (9999, 99, 99)
  # a bare year sorts before any dated release in the same year, which is
  # what "earliest known" means when the day is not recorded.
  while len(numbers) < 3:
    numbers.append(0)
  return (numbers[0], numbers[1], numbers[2])


def _rank(
  candidate: ReleaseCandidate, prefer_standard_edition: bool
) -> tuple[int, int, int, tuple[int, int, int]]:
  """Build the sort key for one candidate.

  Args:
    candidate: the release to rank.
    prefer_standard_edition: whether a deluxe cut is demoted.

  Returns:
    The ranking tuple; lower sorts first.
  """
  return (
    _TYPE_RANK.get(candidate.album_type.lower(), _UNKNOWN_TYPE_RANK),
    1 if candidate.total_tracks <= 1 else 0,
    1 if (prefer_standard_edition and candidate.is_edition_variant) else 0,
    _date_key(candidate.release_date),
  )


def choose_release(
  candidates: list[ReleaseCandidate] | tuple[ReleaseCandidate, ...],
  prefer_standard_edition: bool = True,
) -> ReleaseCandidate | None:
  """Pick the release a recording should be attributed to.

  Args:
    candidates: every release the ISRC search returned.
    prefer_standard_edition: demote deluxe and bonus cuts so the cleaner album
      name lands in `TALB`. Set false to take whatever the ranking picks.

  Returns:
    The chosen release, or None if there were no candidates.
  """
  if not candidates:
    return None
  return min(candidates, key=lambda c: _rank(c, prefer_standard_edition))


def earliest_release_date(
  candidates: list[ReleaseCandidate] | tuple[ReleaseCandidate, ...],
) -> str | None:
  """Return the earliest release date across every candidate (F33).

  This is deliberately not the chosen release's date. A single precedes its
  album by design, so `Never Sleep` is tagged 2022-07-29 — the single — while
  its album and track number come from `Demons Protected By Angels`. Both facts
  are true and both are kept.

  Args:
    candidates: every release the ISRC search returned.

  Returns:
    The earliest date string, or None if there is no usable date.
  """
  dated = [c for c in candidates if _date_key(c.release_date) != (9999, 99, 99)]
  if not dated:
    return None
  return min(dated, key=lambda c: _date_key(c.release_date)).release_date
