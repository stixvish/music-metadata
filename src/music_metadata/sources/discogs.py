"""tier 2 — discogs, for label and a genre fallback (SPEC.md OQ-10, F46, F47).

it supplies two things nothing free above it does: the **label** (§7 precedence,
below beatport) and `styles`, a deeper taxonomy than itunes' `primaryGenreName`
(F47). it is **not** a BPM or key source — it has neither field at all (§7e).

**two calls, and the second is not optional.** the search endpoint returns a
flat `label` array that merges the actual labels with pressing plants,
publishers and studios — measured on `18 Months`, it contained `Sony DADC`,
`EMI Music Publishing` and `Westlake Studios` alongside the real labels. the
release endpoint separates `labels` (`entity_type: Label`) from `companies`
(copyright, distribution), which is the distinction F46 needs.

because it costs two calls, §7 runs it **only when beatport has no listing**.
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

_API = "https://api.discogs.com"

# measured 2026-09-14 from the `x-discogs-ratelimit` response header on an
# authenticated request: 60 per minute. not documented in the spec.
_RATE_PER_MINUTE = 60

# discogs requires an identifying User-Agent, as musicbrainz does.
USER_AGENT = "music-metadata/0.1.0 +https://github.com/stixvish/music-metadata"

# an `entity_type_name` of "Label" is the real label; everything else in the
# release's company list is a plant, publisher, distributor or studio.
_LABEL_ENTITY = "label"


@dataclass(frozen=True, slots=True)
class DiscogsRelease:
  """what discogs says about one release."""

  release_id: int
  title: str
  labels: tuple[str, ...] = ()
  styles: tuple[str, ...] = ()
  genres: tuple[str, ...] = ()
  catalog_number: str | None = None

  @property
  def label(self) -> str | None:
    """The first real label, which is what `TPUB` takes."""
    return self.labels[0] if self.labels else None

  @property
  def style(self) -> str | None:
    """The first style — F47's genre fallback, deeper than itunes' genre."""
    return self.styles[0] if self.styles else None


class Discogs:
  """the discogs database API."""

  def __init__(
    self,
    token: str,
    bucket: TokenBucket | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
  ) -> None:
    """Build the adapter.

    Args:
      token: a discogs personal access token.
      bucket: shared rate limiter; one is made at 60/min if omitted.
      transport: injectable transport, so tests need no network.
      sleep: injectable sleep, for backoff.
    """
    self._source = Source(
      name="discogs",
      base_url=_API,
      bucket=bucket or TokenBucket(_RATE_PER_MINUTE),
      headers={
        "User-Agent": USER_AGENT,
        "Authorization": f"Discogs token={token}",
      },
      transport=transport,
      sleep=sleep,
    )

  def close(self) -> None:
    """Close the connection pool."""
    self._source.close()

  def search_release_id(self, artist: str, album: str) -> tuple[int | None, JsonValue]:
    """Find the release id for an artist and album.

    Args:
      artist: the album artist.
      album: the album name.

    Returns:
      The first result's id (None when there is no match) and the raw payload.
    """
    raw = self._source.get_json(
      "/database/search",
      params={"q": f"{artist} {album}".strip(), "type": "release", "per_page": "5"},
    )
    return (_first_release_id(raw), raw)

  def release(self, release_id: int) -> tuple[DiscogsRelease | None, JsonValue]:
    """Fetch one release's labels, styles and catalog number.

    Args:
      release_id: the discogs release id.

    Returns:
      The parsed release (None when discogs has none) and the raw payload.
    """
    raw = self._source.get_json(f"/releases/{release_id}")
    return (release_from_raw(raw), raw)


def _strings(value: JsonValue) -> tuple[str, ...]:
  """Coerce a JSON array to a tuple of non-empty strings.

  Args:
    value: the raw array.

  Returns:
    The strings, in order.
  """
  if not isinstance(value, list):
    return ()
  return tuple(v for v in value if isinstance(v, str) and v)


def _first_release_id(raw: JsonValue) -> int | None:
  """Pull the first release id out of a search payload.

  Args:
    raw: the search response.

  Returns:
    The id, or None.
  """
  if not isinstance(raw, dict):
    return None
  results = raw.get("results")
  if not isinstance(results, list):
    return None
  for entry in results:
    if not isinstance(entry, dict):
      continue
    release_id = entry.get("id")
    if isinstance(release_id, int) and not isinstance(release_id, bool):
      return release_id
  return None


def release_from_raw(raw: JsonValue) -> DiscogsRelease | None:
  """Parse a stored release payload, with no network call (§9a).

  Only entries whose `entity_type_name` is `Label` become labels. The rest of
  the company list is copyright holders, distributors and studios, and letting
  those reach `TPUB` is exactly what F46 warns against.

  Args:
    raw: the release payload.

  Returns:
    The release, or None when the payload holds none.
  """
  if not isinstance(raw, dict):
    return None
  release_id = raw.get("id")
  if not isinstance(release_id, int) or isinstance(release_id, bool):
    return None

  labels: list[str] = []
  catalog: str | None = None
  entries = raw.get("labels")
  if isinstance(entries, list):
    for entry in entries:
      if not isinstance(entry, dict):
        continue
      kind = str(entry.get("entity_type_name", "")).strip().lower()
      name = entry.get("name")
      if kind and kind != _LABEL_ENTITY:
        continue
      if isinstance(name, str) and name:
        labels.append(name)
        catno = entry.get("catno")
        if catalog is None and isinstance(catno, str) and catno:
          catalog = catno

  return DiscogsRelease(
    release_id=release_id,
    title=str(raw.get("title", "")),
    labels=tuple(labels),
    styles=_strings(raw.get("styles")),
    genres=_strings(raw.get("genres")),
    catalog_number=catalog,
  )
