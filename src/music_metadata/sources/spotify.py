"""tier 1 — spotify, queried directly by ISRC (SPEC.md §5a step 1).

spotify comes first because its release choice is the input to everything else:
the album name drives the artwork search (§7c), and the track and disc numbers
come from the chosen release rather than from any id another service hands over
(F32).

`/v1/search?q=isrc:` is what makes the *set* of releases visible. itunes exposes
only the one release its id points at, which is why §7b could not be built on it.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from music_metadata.release import ReleaseCandidate
from music_metadata.sources.base import Source, SourceError
from music_metadata.sources.ratelimit import TokenBucket
from music_metadata.store import JsonValue

_API = "https://api.spotify.com"
_TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 — a URL, not a secret

# measured 2026-09-14: the search endpoint rejects any limit above 10 with
# `{"error": {"status": 400, "message": "Invalid limit"}}`, though the published
# range is 0-50. so pages are 10 wide and we paginate.
_SEARCH_LIMIT = "10"

# `USJI10000001` returns 34 releases across 4 pages. F33 takes the MIN date over
# *all* releases and search returns relevance order, not date order — so a later
# page can carry an earlier release and stopping at page 1 would be wrong.
_MAX_PAGES = 10

# refresh a little before expiry so a long run never races the clock.
_TOKEN_MARGIN_S = 30.0


@dataclass(frozen=True, slots=True)
class SpotifyResult:
  """the parsed candidates plus the raw payload §9a stores."""

  candidates: list[ReleaseCandidate]
  raw: JsonValue


class Spotify:
  """spotify's search API, authenticated with client credentials."""

  def __init__(
    self,
    client_id: str,
    client_secret: str,
    bucket: TokenBucket | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
  ) -> None:
    """Build the adapter.

    Args:
      client_id: spotify application id.
      client_secret: spotify application secret.
      bucket: shared rate limiter; one is made at 20/min (F8) if omitted.
      transport: injectable transport, so tests need no network.
      sleep: injectable sleep, for backoff.
      now: injectable monotonic clock, for token expiry.
    """
    self._id = client_id
    self._secret = client_secret
    self._now = now
    self._token: str | None = None
    self._expires_at = 0.0
    self._transport = transport
    self._source = Source(
      name="spotify",
      base_url=_API,
      bucket=bucket or TokenBucket(20),
      transport=transport,
      sleep=sleep,
    )
    self._auth_client = httpx.Client(timeout=self._source.timeout, transport=transport)

  def close(self) -> None:
    """Close both connection pools."""
    self._source.close()
    self._auth_client.close()

  def _bearer(self) -> str:
    """Return a valid access token, fetching or refreshing as needed.

    Returns:
      The bearer token.

    Raises:
      SourceError: if the credentials are rejected.
    """
    if self._token is not None and self._now() < self._expires_at:
      return self._token

    basic = base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()
    try:
      response = self._auth_client.post(
        _TOKEN_URL,
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {basic}"},
      )
    except httpx.HTTPError as exc:
      msg = f"spotify: could not reach the token endpoint: {exc}"
      raise SourceError(msg) from exc

    if response.is_error:
      msg = f"spotify: token request failed with HTTP {response.status_code}"
      raise SourceError(msg)

    body = response.json()
    token = body.get("access_token")
    if not token:
      msg = "spotify: token response carried no access_token"
      raise SourceError(msg)

    self._token = str(token)
    self._expires_at = (
      self._now() + float(body.get("expires_in", 3600)) - _TOKEN_MARGIN_S
    )
    return self._token

  def search_isrc(self, isrc: str) -> SpotifyResult:
    """Find every release carrying this ISRC, across every page.

    `tracks.total` is not trusted: the same query returned 34 and then 0 within
    a minute. Pagination therefore stops on an empty page, not on a count.

    Args:
      isrc: the recording's ISRC.

    Returns:
      The parsed release candidates and every raw page, for the cache. An empty
      candidate list is a normal outcome, not an error.
    """
    self._source.set_header("Authorization", f"Bearer {self._bearer()}")
    query = f"isrc:{isrc}"
    pages: list[JsonValue] = []
    candidates: list[ReleaseCandidate] = []

    for page in range(_MAX_PAGES):
      raw = self._source.get_json(
        "/v1/search",
        params={
          "q": query,
          "type": "track",
          "limit": _SEARCH_LIMIT,
          "offset": str(page * int(_SEARCH_LIMIT)),
        },
      )
      pages.append(raw)
      items = _items(raw)
      if not items:
        break
      candidates += [c for c in (_candidate(i) for i in items) if c is not None]
      if len(items) < int(_SEARCH_LIMIT):
        break

    return SpotifyResult(candidates=candidates, raw={"query": query, "pages": pages})


def _names(entries: JsonValue) -> tuple[str, ...]:
  """Pull the `name` out of a spotify artist array.

  Args:
    entries: the raw `artists` array.

  Returns:
    The names in order.
  """
  if not isinstance(entries, list):
    return ()
  out: list[str] = []
  for entry in entries:
    if isinstance(entry, dict) and entry.get("name"):
      out.append(str(entry["name"]))
  return tuple(out)


def candidates_from_raw(raw: JsonValue) -> list[ReleaseCandidate]:
  """Re-parse a stored payload into candidates, with no network call.

  This is what §9a's raw-payload rule buys: a parsing fix is replayed offline
  against what was already fetched, instead of forcing a re-fetch of 1,494
  tracks at 20 req/min.

  Args:
    raw: a payload as `search_isrc` stored it — `{"query": ..., "pages": [...]}`
      — or a single bare search page.

  Returns:
    The release candidates.
  """
  pages: list[JsonValue] = [raw]
  if isinstance(raw, dict):
    stored = raw.get("pages")
    if isinstance(stored, list):
      pages = stored

  out: list[ReleaseCandidate] = []
  for page in pages:
    out += [c for c in (_candidate(i) for i in _items(page)) if c is not None]
  return out


def _items(raw: JsonValue) -> list[JsonValue]:
  """Pull `tracks.items` out of one search page.

  Args:
    raw: the decoded page.

  Returns:
    The items, or an empty list if the page carried none.
  """
  if not isinstance(raw, dict):
    return []
  tracks = raw.get("tracks")
  if not isinstance(tracks, dict):
    return []
  items = tracks.get("items")
  return items if isinstance(items, list) else []


def _int(value: JsonValue) -> int:
  """Coerce a JSON value to an int, treating anything odd as zero.

  Args:
    value: the raw field.

  Returns:
    The integer, or 0 when the field is absent or not a number.
  """
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return 0
  return int(value)


def _candidate(item: JsonValue) -> ReleaseCandidate | None:
  """Turn one search result into a release candidate.

  A malformed item is skipped rather than fatal: one odd row must not lose the
  other releases the recording appears on.

  Args:
    item: one element of `tracks.items`.

  Returns:
    The candidate, or None if the item carries no usable album.
  """
  if not isinstance(item, dict):
    return None
  album = item.get("album")
  if not isinstance(album, dict) or not album.get("name"):
    return None

  images = album.get("images")
  image_url: str | None = None
  if isinstance(images, list) and images and isinstance(images[0], dict):
    url = images[0].get("url")
    image_url = str(url) if url else None

  return ReleaseCandidate(
    album_name=str(album["name"]),
    album_type=str(album.get("album_type", "")),
    album_artists=_names(album.get("artists")),
    total_tracks=_int(album.get("total_tracks")),
    release_date=str(album.get("release_date", "")),
    track_number=_int(item.get("track_number")),
    disc_number=_int(item.get("disc_number")),
    track_name=str(item.get("name", "")),
    track_artists=_names(item.get("artists")),
    duration_ms=_int(item.get("duration_ms")),
    album_id=str(album.get("id", "")),
    track_id=str(item.get("id", "")),
    image_url=image_url,
  )
