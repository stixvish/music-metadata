"""tier 3 — beatport, for genre, BPM and key (SPEC.md §5, G3, F14, F22, F23).

**this tier is isolated on purpose.** §5 names it the component most likely to
break and the one nothing else depends on: if auth fails, it returns nothing,
genre falls back to discogs and then itunes, and the pipeline still completes.
every failure path here is a `None`, never an exception.

**matching is two-step, because ISRC alone does not work.** F22 measured
`?isrc=` succeeding on originals and failing on **all nine** `Blessings`
remixes — beatport and the streaming services issue different ISRCs for the same
remix. so ISRC is a fast path, and a search on artist + name + mix name is the
real one.

**and a match is not permission to copy everything.** F23 found the same work
released as two genuinely different recordings. G3 therefore splits by duration:

```text
within ±5s   the recording is the same     -> all fields transfer
outside ±5s  same work, different edit     -> genre, sub_genre, label and
                                              remixer only. bpm, key, length
                                              and beatport's ISRC are DISCARDED
```

taking beatport's ISRC for a longer recording would label the file as a track it
is not — a correctness failure, not a metadata improvement. G9 asserts it never
happens.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from music_metadata.camelot import to_camelot
from music_metadata.naming import normalise_mix
from music_metadata.sources.base import Source, SourceError
from music_metadata.sources.bp_auth import TokenProvider
from music_metadata.sources.ratelimit import TokenBucket

if TYPE_CHECKING:
  from music_metadata.store import JsonValue

_API = "https://api.beatport.com"

# F8: 20 req/min is the practical ceiling across this stack.
_RATE_PER_MINUTE = 20

# G3: the tolerance that separates "the same recording" from "a different edit".
DURATION_TOLERANCE_S = 5.0

# OQ-8: a beatport match materially longer than the file is a re-acquisition
# candidate, reported by `verify` and never substituted.
MATERIALLY_LONGER_S = 15.0

MATCHED_BY_ISRC = "isrc"
MATCHED_BY_SEARCH = "search"

# the two field classes G3 defines.
CLASS_SAME_RECORDING = "same-recording"
CLASS_DIFFERENT_EDIT = "different-edit"
CLASS_NO_MATCH = "no-match"


@dataclass(frozen=True, slots=True)
class BeatportTrack:
  """one beatport listing."""

  track_id: int
  name: str
  mix_name: str | None
  artists: tuple[str, ...]
  remixers: tuple[str, ...]
  genre: str | None
  sub_genre: str | None
  label: str | None
  bpm: int | None
  key: str | None
  length_ms: int | None
  isrc: str | None
  url: str | None = None

  @property
  def camelot_key(self) -> str | None:
    """The key in camelot notation (§7f), or None if unparseable."""
    return to_camelot(self.key)

  @property
  def best_genre(self) -> str | None:
    """`sub_genre` where it exists, else `genre`.

    F13 measured `sub_genre` populated on 1 of 17 — the operator's decision is
    to take it wherever it exists and fall back to `genre` otherwise.
    """
    return self.sub_genre or self.genre


@dataclass(frozen=True, slots=True)
class Match:
  """a beatport listing and how much of it may be used."""

  track: BeatportTrack
  matched_by: str
  field_class: str
  delta_s: float | None = None

  @property
  def transfers_everything(self) -> bool:
    """Whether bpm, key and length may be taken (G3)."""
    return self.field_class == CLASS_SAME_RECORDING

  @property
  def materially_longer(self) -> bool:
    """Whether this is an OQ-8 re-acquisition candidate."""
    return self.delta_s is not None and self.delta_s > MATERIALLY_LONGER_S


def classify(local_duration_s: float, track: BeatportTrack) -> tuple[str, float | None]:
  """Decide which fields a match may transfer (G3).

  Args:
    local_duration_s: the file's own duration.
    track: the beatport listing.

  Returns:
    The field class, and the absolute difference in seconds (None when
    beatport reports no length, in which case nothing may be assumed).
  """
  if track.length_ms is None or local_duration_s <= 0:
    # no duration to compare: treat as a different edit rather than assume
    # sameness, because assuming sameness is what writes a wrong BPM.
    return (CLASS_DIFFERENT_EDIT, None)
  delta = abs(track.length_ms / 1000.0 - local_duration_s)
  if delta <= DURATION_TOLERANCE_S:
    return (CLASS_SAME_RECORDING, delta)
  return (CLASS_DIFFERENT_EDIT, delta)


class Beatport:
  """beatport's v4 catalog API, behind a pluggable token provider."""

  def __init__(
    self,
    tokens: TokenProvider,
    bucket: TokenBucket | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
  ) -> None:
    """Build the adapter.

    Args:
      tokens: supplies bearer tokens; may supply none.
      bucket: shared rate limiter; one is made at 20/min if omitted.
      transport: injectable transport, so tests need no network.
      sleep: injectable sleep, for backoff.
    """
    self._tokens = tokens
    self._source = Source(
      name="beatport",
      base_url=_API,
      bucket=bucket or TokenBucket(_RATE_PER_MINUTE),
      transport=transport,
      sleep=sleep,
    )

  def close(self) -> None:
    """Close the connection pool."""
    self._source.close()

  def _get(self, path: str, params: dict[str, str]) -> JsonValue | None:
    """Make an authenticated request, or return None if that is impossible.

    Args:
      path: the API path.
      params: query parameters.

    Returns:
      The decoded body, or None when there is no token or the call fails.
      **Never raises**: §5 requires that this tier failing cannot stop a run.
    """
    token = self._tokens.get()
    if token is None:
      return None
    self._source.set_header("Authorization", f"Bearer {token}")
    try:
      return self._source.get_json(path, params=params)
    except SourceError:
      return None

  def by_isrc(self, isrc: str) -> tuple[BeatportTrack | None, JsonValue]:
    """Look a track up by ISRC — the fast path.

    F22: this succeeds on originals and fails on remixes, because beatport and
    the streaming services issue different ISRCs for the same remix. A miss is
    expected, not exceptional.

    Args:
      isrc: the recording's ISRC.

    Returns:
      The first listing (None on a miss) and the raw payload for the cache.
    """
    raw = self._get("/v4/catalog/tracks/", {"isrc": isrc})
    tracks = tracks_from_raw(raw)
    return (tracks[0] if tracks else None, raw)

  def search(
    self, artist: str, name: str, mix_name: str | None = None
  ) -> tuple[list[BeatportTrack], JsonValue]:
    """Search by artist, track name and mix name — the real path (F22, G3).

    Args:
      artist: the track's main artist.
      name: the bare track name, without features or mix.
      mix_name: the mix name, when there is one.

    Returns:
      Every listing beatport returned (possibly empty) and the raw payload.
    """
    term = " ".join(part for part in (artist, name, mix_name) if part)
    raw = self._get(
      "/v4/catalog/search/", {"q": term, "type": "tracks", "per_page": "20"}
    )
    return (tracks_from_raw(raw), raw)

  def find(
    self,
    isrc: str | None,
    artist: str,
    name: str,
    mix_name: str | None,
    local_duration_s: float,
  ) -> tuple[Match | None, JsonValue]:
    """Find the best listing for a track and decide what it may contribute.

    Args:
      isrc: the file's own ISRC, tried as a fast path.
      artist: the track's main artist.
      name: the bare track name.
      mix_name: the mix name, when there is one.
      local_duration_s: the file's duration, for G3's split.

    Returns:
      The match and its field class (None on a miss), plus the raw payload the
      match came from — §9a stores what the API said, not a re-serialised
      parse of it. **Zero results is a normal outcome**: most of this library
      is not on beatport at all.
    """
    if isrc:
      hit, raw = self.by_isrc(isrc)
      if hit is not None:
        field_class, delta = classify(local_duration_s, hit)
        return (Match(hit, MATCHED_BY_ISRC, field_class, delta), raw)

    candidates, raw = self.search(artist, name, mix_name)
    accepted = _accept(candidates, artist, mix_name)
    if accepted is None:
      return (None, raw)
    field_class, delta = classify(local_duration_s, accepted)
    return (Match(accepted, MATCHED_BY_SEARCH, field_class, delta), raw)


def _fold(text: str) -> str:
  """Normalise a name for comparison only.

  Args:
    text: the raw name.

  Returns:
    A comparison key.
  """
  return re.sub(r"[^a-z0-9]+", "", text.lower())


def _accept(
  candidates: list[BeatportTrack], artist: str, mix_name: str | None
) -> BeatportTrack | None:
  """Pick the search result that is actually this track (G3).

  G3: "a candidate is accepted when artist and normalised mix name agree."
  Accepting on name alone would take a different artist's cover, and accepting
  across mix names would take the extended cut's BPM for a radio edit.

  Args:
    candidates: what the search returned.
    artist: the expected main artist.
    mix_name: the expected mix name, if any.

  Returns:
    The accepted listing, or None when none agrees.
  """
  want_artist = _fold(artist)
  want_mix = _fold(normalise_mix(mix_name) or "")
  for candidate in candidates:
    artists = {_fold(a) for a in candidate.artists}
    if want_artist and not any(want_artist in a or a in want_artist for a in artists):
      continue
    got_mix = _fold(normalise_mix(candidate.mix_name) or "")
    if got_mix != want_mix:
      continue
    return candidate
  return None


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


def _names(value: JsonValue) -> tuple[str, ...]:
  """Pull `name` out of a beatport artist or remixer array.

  Args:
    value: the raw array.

  Returns:
    The names, in order.
  """
  if not isinstance(value, list):
    return ()
  out: list[str] = []
  for entry in value:
    if isinstance(entry, dict):
      name = entry.get("name")
      if isinstance(name, str) and name:
        out.append(name)
  return tuple(out)


def _nested_name(value: JsonValue) -> str | None:
  """Pull `name` out of a nested object such as `genre` or `label`.

  Args:
    value: the raw object.

  Returns:
    The name, or None.
  """
  return _str(value.get("name")) if isinstance(value, dict) else None


def _release_label(value: JsonValue) -> str | None:
  """Pull the label name out of a track's nested release object.

  Args:
    value: the raw `release` object.

  Returns:
    The label name, or None.
  """
  if not isinstance(value, dict):
    return None
  return _nested_name(value.get("label"))


def tracks_from_raw(raw: JsonValue) -> list[BeatportTrack]:
  """Parse a stored payload into listings, with no network call (§9a).

  Args:
    raw: a `results`-shaped payload, or a bare list.

  Returns:
    The listings.
  """
  results: JsonValue = raw
  if isinstance(raw, dict):
    results = raw.get("results", raw.get("tracks", []))
  if not isinstance(results, list):
    return []

  out: list[BeatportTrack] = []
  for entry in results:
    if not isinstance(entry, dict):
      continue
    track_id = _int(entry.get("id"))
    name = _str(entry.get("name"))
    if track_id is None or name is None:
      continue
    out.append(
      BeatportTrack(
        track_id=track_id,
        name=name,
        mix_name=_str(entry.get("mix_name")),
        artists=_names(entry.get("artists")),
        remixers=_names(entry.get("remixers")),
        genre=_nested_name(entry.get("genre")),
        sub_genre=_nested_name(entry.get("sub_genre")),
        label=_release_label(entry.get("release")),
        bpm=_int(entry.get("bpm")),
        key=_nested_name(entry.get("key")) or _str(entry.get("key")),
        length_ms=_int(entry.get("length_ms")),
        isrc=_str(entry.get("isrc")),
        url=_str(entry.get("url")),
      )
    )
  return out
