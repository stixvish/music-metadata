"""musicfetch — the one thing no free source does (SPEC.md F19, F36).

F36 removed musicfetch from the library path entirely: F37 showed a second
itunes query reproduces its artwork byte-for-byte, and F32/F34 showed its
release choice and its artwork are often a compilation's. so **nothing in the
v1 resolve path calls this**, and that is deliberate.

what it uniquely does is F19: **turn a youtube URL into an ISRC**, with no
fingerprint, no text search and no edition ambiguity. that is the acquisition
problem (§10), and it is the only reason this module exists.

**a youtube *video* is not a youtube music *track*.** measured 2026-09-15:

```text
Eo-KmOd3i7s  "*NSYNC - Bye Bye Bye (Official Video)"  -> no isrc, youtube only
fxHjlCBHuzA  "Bye Bye Bye" by *NSYNC                  -> USJI10000001
```

the official-video upload is a different entity and musicfetch cannot map it to
a release. a caller that gets no ISRC should be told to try the track link
rather than being told the lookup failed.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from music_metadata.sources.base import DEFAULT_TIMEOUT, Source
from music_metadata.sources.ratelimit import TokenBucket
from music_metadata.store import JsonValue

_BASE_URL = "https://api.musicfetch.io"

# F8: the operator's plan is 20 req/min. the published limit is respected rather
# than the gentler measured one.
_RATE_PER_MINUTE = 20

# **the token is `MUSICMATCH_TOKEN` in `.env`, and that name is not a typo for
# a different service** (OQ-12, resolved 2026-09-15): it authenticates against
# `api.musicfetch.io` and is rejected as `Authorization: Bearer`.
#
#   x-token        HTTP 200
#   Authorization  HTTP 401  {"message": "x-token header required"}
_TOKEN_HEADER = "x-token"  # noqa: S105 — a header name, not a secret


@dataclass(frozen=True, slots=True)
class UrlMatch:
  """what musicfetch made of one url."""

  isrc: str | None
  name: str | None
  artists: tuple[str, ...]
  duration_s: float | None
  raw: JsonValue

  @property
  def looks_like_a_video(self) -> bool:
    """Whether this resolved to youtube alone, with no release behind it.

    An official-video upload maps to no ISRC however well-known the song is.
    Saying so is more useful than reporting a failed lookup.
    """
    if self.isrc is not None:
      return False
    services = _services(self.raw)
    return bool(services) and all(s.startswith("youtube") for s in services)


def _services(raw: JsonValue) -> list[str]:
  """List the services a result carries.

  Args:
    raw: the decoded `result` object.

  Returns:
    Service names, or an empty list if the shape is not what we expect.
  """
  if not isinstance(raw, dict):
    return []
  services = raw.get("services")
  return sorted(services) if isinstance(services, dict) else []


class Musicfetch:
  """resolves a url to a recording (F19)."""

  def __init__(
    self,
    token: str,
    bucket: TokenBucket | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
  ) -> None:
    """Build the client.

    Args:
      token: the `MUSICMATCH_TOKEN` value.
      bucket: injectable rate limiter.
      transport: injectable transport, so tests need no network.
      timeout: request timeout.
    """
    self._source = Source(
      name="musicfetch",
      base_url=_BASE_URL,
      bucket=bucket or TokenBucket(_RATE_PER_MINUTE),
      headers={_TOKEN_HEADER: token},
      timeout=timeout,
      transport=transport,
    )

  def close(self) -> None:
    """Close the connection pool."""
    self._source.close()

  def isrc_for_url(self, url: str) -> UrlMatch:
    """Resolve a youtube (or other service) url to an ISRC.

    Args:
      url: the track url. A `music.youtube.com/watch?v=` link resolves; an
        official-video `youtube.com` link generally does not (see the module
        docstring).

    Returns:
      What musicfetch knows, with `isrc` None when it could not place the url.

    Raises:
      SourceError: if musicfetch is unreachable or rejects the token.
    """
    body = self._source.get_json("/url", params={"url": url})
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict):
      return UrlMatch(isrc=None, name=None, artists=(), duration_s=None, raw=result)

    isrc = result.get("isrc")
    name = result.get("name")
    raw_artists = result.get("artists")
    # the walrus must not be spelled `name` here: in a generator expression it
    # binds in the *enclosing* scope, and would overwrite the track name above.
    artists = tuple(
      who
      for a in (raw_artists if isinstance(raw_artists, list) else [])
      if isinstance(a, dict) and isinstance(who := a.get("name"), str)
    )
    # musicfetch reports milliseconds. G10's principle applies to a recovered
    # ISRC exactly as it does to a tagged one: an ISRC whose recording is a
    # different length is not this file's ISRC.
    millis = result.get("duration")
    return UrlMatch(
      isrc=isrc if isinstance(isrc, str) and isrc else None,
      name=name if isinstance(name, str) else None,
      artists=artists,
      duration_s=millis / 1000.0 if isinstance(millis, (int, float)) else None,
      raw=result,
    )
