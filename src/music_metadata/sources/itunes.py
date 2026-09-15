"""tier 2 — the free itunes search API (SPEC.md §7c, F4, F37).

it does two jobs: it supplies the track and disc numbers musicfetch never
returned (F4), and it is the **entire** artwork chain after F37 removed
musicfetch from tier 1.

two entities, because one is not enough. `entity=album` finds most releases by
name; where it fails it fails *confidently* — searching `Calvin Harris 18
Months` returns exactly one album, `96 Months`, a different record. `entity=song`
on the track name then finds the right collection. F37 measured the two together
reproducing musicfetch's results byte for byte.

this module reports what itunes said. deciding which result is the **right**
release is §7c's job, in `artwork.py`, and it is a separate concern precisely
because the wrong answer here is silent.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from music_metadata.sources.base import Source
from music_metadata.sources.ratelimit import TokenBucket

if TYPE_CHECKING:
  from music_metadata.store import JsonValue

_API = "https://itunes.apple.com"

# apple documents roughly 20 calls per minute for the search API.
_RATE_PER_MINUTE = 20

# song search has to look past the first few hits: the album we want may be
# several rows down among singles and compilations of the same track.
_SONG_LIMIT = "25"
_ALBUM_LIMIT = "10"


@dataclass(frozen=True, slots=True)
class ItunesRelease:
  """one release as itunes describes it."""

  collection_id: int
  collection_name: str
  artist_name: str
  artwork_url_100: str | None = None
  track_name: str | None = None
  track_number: int | None = None
  track_count: int | None = None
  disc_number: int | None = None
  disc_count: int | None = None
  primary_genre: str | None = None


@dataclass(frozen=True, slots=True)
class ItunesResult:
  """the parsed releases plus the raw payload §9a stores."""

  releases: list[ItunesRelease]
  raw: JsonValue


class Itunes:
  """the itunes search and lookup API. free, no auth."""

  def __init__(
    self,
    bucket: TokenBucket | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
  ) -> None:
    """Build the adapter.

    Args:
      bucket: shared rate limiter; one is made at 20/min if omitted.
      transport: injectable transport, so tests need no network.
      sleep: injectable sleep, for backoff.
    """
    self._source = Source(
      name="itunes",
      base_url=_API,
      bucket=bucket or TokenBucket(_RATE_PER_MINUTE),
      transport=transport,
      sleep=sleep,
    )

  def close(self) -> None:
    """Close the connection pool."""
    self._source.close()

  def search_albums(self, term: str) -> ItunesResult:
    """Search for albums by name.

    Args:
      term: the search text, usually `{album artist} {album}`.

    Returns:
      The releases itunes returned, and the raw payload.
    """
    raw = self._source.get_json(
      "/search", params={"term": term, "entity": "album", "limit": _ALBUM_LIMIT}
    )
    return ItunesResult(releases=releases_from_raw(raw), raw=raw)

  def search_songs(self, term: str) -> ItunesResult:
    """Search for songs, to reach the collection each belongs to.

    This is the path F37 added. `entity=album` cannot find `18 Months`; the
    song search can, because the track name is unambiguous where the album
    name collides.

    Args:
      term: the search text, usually `{artist} {track name}`.

    Returns:
      The releases itunes returned, and the raw payload.
    """
    raw = self._source.get_json(
      "/search", params={"term": term, "entity": "song", "limit": _SONG_LIMIT}
    )
    return ItunesResult(releases=releases_from_raw(raw), raw=raw)

  def lookup(self, collection_id: int) -> ItunesResult:
    """Look a collection up by its apple id.

    Args:
      collection_id: the apple collection id.

    Returns:
      The releases itunes returned, and the raw payload.
    """
    raw = self._source.get_json("/lookup", params={"id": str(collection_id)})
    return ItunesResult(releases=releases_from_raw(raw), raw=raw)


def _int(value: JsonValue) -> int | None:
  """Coerce a JSON value to an int when it plausibly is one.

  Args:
    value: the raw field.

  Returns:
    The integer, or None.
  """
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return None
  return int(value)


def _str(value: JsonValue) -> str | None:
  """Coerce a JSON value to a non-empty string.

  Args:
    value: the raw field.

  Returns:
    The string, or None.
  """
  return str(value) if isinstance(value, str) and value else None


def releases_from_raw(raw: JsonValue) -> list[ItunesRelease]:
  """Parse a stored payload into releases, with no network call (§9a).

  Args:
    raw: a search or lookup payload.

  Returns:
    The releases. A result with no collection is skipped rather than fatal.
  """
  if not isinstance(raw, dict):
    return []
  results = raw.get("results")
  if not isinstance(results, list):
    return []

  out: list[ItunesRelease] = []
  for entry in results:
    if not isinstance(entry, dict):
      continue
    collection_id = _int(entry.get("collectionId"))
    collection_name = _str(entry.get("collectionName"))
    if collection_id is None or collection_name is None:
      continue
    out.append(
      ItunesRelease(
        collection_id=collection_id,
        collection_name=collection_name,
        artist_name=_str(entry.get("artistName")) or "",
        artwork_url_100=_str(entry.get("artworkUrl100")),
        track_name=_str(entry.get("trackName")),
        track_number=_int(entry.get("trackNumber")),
        track_count=_int(entry.get("trackCount")),
        disc_number=_int(entry.get("discNumber")),
        disc_count=_int(entry.get("discCount")),
        primary_genre=_str(entry.get("primaryGenreName")),
      )
    )
  return out
