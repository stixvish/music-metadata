"""tier 2 — musicbrainz, queried directly by ISRC (SPEC.md §5a step 2).

musicbrainz is here for one thing nothing else in the stack does: it carries an
explicit `joinphrase` per artist-credit element, so the main/featured boundary
is **machine-readable rather than inferred** (§6). spotify flattens every
contributor into one list with no role, and itunes is inconsistent about whether
a feature lives in the title or the artist name.

two operational facts, both measured live on 2026-09-14 rather than recalled:

- **a `User-Agent` is mandatory.** the API answers `HTTP 403` without one. it is
  not optional politeness.
- **`currently busy` is `HTTP 503`, and it is a retry, not a miss** (F30). the
  first request of this probe got one. treating it as a miss silently drops
  artist credits for tracks musicbrainz actually has.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from music_metadata.sources.base import Source
from music_metadata.sources.ratelimit import TokenBucket

if TYPE_CHECKING:
  from music_metadata.store import JsonValue

_API = "https://musicbrainz.org"

# musicbrainz asks for one request per second and enforces it. 60/min is the
# same ceiling expressed in the bucket's units.
_RATE_PER_MINUTE = 60

# the API returns 403 with no User-Agent (measured). the contact form is what
# their docs ask for so they can reach the operator of a misbehaving client.
USER_AGENT = "music-metadata/0.1.0 ( https://github.com/stixvish/music-metadata )"

# §6: everything before the element whose joinphrase says "feat" is a main
# artist; everything from that element's successor on is featured.
_FEATURE_JOIN = re.compile(r"\b(feat|ft|featuring|with)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Credit:
  """the main/featured split musicbrainz makes machine-readable."""

  main: tuple[str, ...]
  featured: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Recording:
  """what one musicbrainz recording says about a track."""

  mbid: str
  title: str
  credit: Credit
  work_id: str | None
  length_ms: int | None
  first_release_date: str | None


@dataclass(frozen=True, slots=True)
class Work:
  """the writing credits on a recording's work.

  measured on a 12-track sample: **every credit came back as `writer`**, with no
  `composer` and no `lyricist` at all. the three are kept separate here so the
  caller decides what a bare `writer` means rather than this module guessing.
  """

  composers: tuple[str, ...]
  lyricists: tuple[str, ...]
  writers: tuple[str, ...]


def split_credit(artist_credit: JsonValue) -> Credit:
  """Split a musicbrainz `artist-credit` array into main and featured artists.

  §6's rule, applied literally: the element whose `joinphrase` names a feature
  is the **boundary**. It and everything before it are main artists; everything
  after is featured. No string parsing of a title and no guessing.

  Args:
    artist_credit: the raw `artist-credit` array.

  Returns:
    The split. Both halves are empty when the array is unusable.
  """
  if not isinstance(artist_credit, list):
    return Credit((), ())

  names: list[str] = []
  joins: list[str] = []
  for element in artist_credit:
    if not isinstance(element, dict):
      continue
    name = element.get("name")
    if not name:
      artist = element.get("artist")
      name = artist.get("name") if isinstance(artist, dict) else None
    if not name:
      continue
    names.append(str(name))
    joins.append(str(element.get("joinphrase") or ""))

  boundary = next(
    (i for i, join in enumerate(joins) if _FEATURE_JOIN.search(join)), None
  )
  if boundary is None:
    return Credit(tuple(names), ())
  return Credit(tuple(names[: boundary + 1]), tuple(names[boundary + 1 :]))


class MusicBrainz:
  """musicbrainz's web service, by ISRC."""

  def __init__(
    self,
    bucket: TokenBucket | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
  ) -> None:
    """Build the adapter.

    Args:
      bucket: shared rate limiter; one is made at 1 req/s if omitted.
      transport: injectable transport, so tests need no network.
      sleep: injectable sleep, for backoff.
    """
    self._source = Source(
      name="musicbrainz",
      base_url=_API,
      bucket=bucket or TokenBucket(_RATE_PER_MINUTE),
      headers={"User-Agent": USER_AGENT},
      transport=transport,
      sleep=sleep,
    )

  def close(self) -> None:
    """Close the connection pool."""
    self._source.close()

  def recording_for_isrc(self, isrc: str) -> tuple[Recording | None, JsonValue]:
    """Look up the recording an ISRC identifies.

    Args:
      isrc: the recording's ISRC.

    Returns:
      The parsed recording (None when musicbrainz has none) and the raw payload
      for the cache. A miss is a normal outcome — F31: a musicbrainz miss does
      not mean a bad ISRC.
    """
    raw = self._source.get_json(
      f"/ws/2/isrc/{isrc}",
      params={"inc": "artist-credits+work-rels", "fmt": "json"},
    )
    if not isinstance(raw, dict):
      return (None, raw)

    recordings = raw.get("recordings")
    if not isinstance(recordings, list) or not recordings:
      return (None, raw)

    first = recordings[0]
    if not isinstance(first, dict):
      return (None, raw)

    return (
      Recording(
        mbid=str(first.get("id", "")),
        title=str(first.get("title", "")),
        credit=split_credit(first.get("artist-credit")),
        work_id=_work_id(first.get("relations")),
        length_ms=_maybe_int(first.get("length")),
        first_release_date=_maybe_str(first.get("first-release-date")),
      ),
      raw,
    )

  def work(self, work_id: str) -> tuple[Work, JsonValue]:
    """Look up a work's writing credits.

    Args:
      work_id: the work's MBID.

    Returns:
      The credits and the raw payload for the cache.
    """
    raw = self._source.get_json(
      f"/ws/2/work/{work_id}", params={"inc": "artist-rels", "fmt": "json"}
    )
    if not isinstance(raw, dict):
      return (Work((), (), ()), raw)

    buckets: dict[str, list[str]] = {"composer": [], "lyricist": [], "writer": []}
    relations = raw.get("relations")
    if isinstance(relations, list):
      for relation in relations:
        if not isinstance(relation, dict):
          continue
        kind = str(relation.get("type", ""))
        artist = relation.get("artist")
        if kind in buckets and isinstance(artist, dict) and artist.get("name"):
          buckets[kind].append(str(artist["name"]))

    return (
      Work(
        composers=tuple(buckets["composer"]),
        lyricists=tuple(buckets["lyricist"]),
        writers=tuple(buckets["writer"]),
      ),
      raw,
    )


def _work_id(relations: JsonValue) -> str | None:
  """Find the work a recording is a performance of.

  Args:
    relations: the recording's `relations` array.

  Returns:
    The work's MBID, or None when the recording links to no work — measured at
    6 of 12 on a real sample, so this is the common case, not an edge one.
  """
  if not isinstance(relations, list):
    return None
  for relation in relations:
    if not isinstance(relation, dict) or relation.get("type") != "performance":
      continue
    work = relation.get("work")
    if isinstance(work, dict) and work.get("id"):
      return str(work["id"])
  return None


def _maybe_int(value: JsonValue) -> int | None:
  """Coerce a JSON value to an int when it plausibly is one.

  Args:
    value: the raw field.

  Returns:
    The integer, or None.
  """
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return None
  return int(value)


def _maybe_str(value: JsonValue) -> str | None:
  """Coerce a JSON value to a non-empty string.

  Args:
    value: the raw field.

  Returns:
    The string, or None when absent or empty.
  """
  return str(value) if isinstance(value, str) and value else None
