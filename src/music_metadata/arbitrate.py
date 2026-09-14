"""apply §7's precedence table and record where every field came from.

`SPEC.md` §4: *every tagged field traces to a named source, recorded per track.*
that is what `provenance` is for — not diagnostics, a requirement.

the table's first line outranks the rest: **a hand-edited value in
`library.toml` (§9b) beats every source.** where the operator has asserted a
value, no source is consulted for that field.

this milestone resolves what spotify alone can supply. the rows musicbrainz,
itunes, beatport and discogs fill are left unset rather than guessed, and the
`sources` argument grows as those adapters land — a field with no source is
written empty, never invented (§7e's position on BPM, applied generally).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Any

from music_metadata.naming import (
  join_artists,
  remixer_from_mix,
  render_title,
  split_filename,
  split_title,
)
from music_metadata.probe import ProbedFile
from music_metadata.release import (
  ReleaseCandidate,
  choose_release,
  earliest_release_date,
)
from music_metadata.tag import Tags

# provenance labels. one string per source so `verify` can count them.
MANUAL = "manual"
SPOTIFY = "spotify"
FILENAME = "filename"
FILE_TAG = "file-tag"
DERIVED = "derived"

# flags raised for the review queue (§14). a flag is never a silent fallback.
FLAG_NO_ISRC = "no-isrc"
FLAG_NO_RELEASE = "no-release"
FLAG_NO_ARTWORK = "no-artwork"


@dataclass(frozen=True, slots=True)
class Resolved:
  """the tags to write, where each came from, and what needs review."""

  tags: Tags
  provenance: dict[str, str] = field(default_factory=dict)
  flags: tuple[str, ...] = ()


def _year_of(date: str | None) -> str | None:
  """Return the year part of a release date.

  Args:
    date: `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.

  Returns:
    The four-digit year, or None.
  """
  if not date:
    return None
  head = date.split("-", 1)[0]
  return head if len(head) == 4 and head.isdigit() else None


def arbitrate(
  probed: ProbedFile,
  candidates: list[ReleaseCandidate] | tuple[ReleaseCandidate, ...] = (),
  overrides: dict[str, str] | None = None,
  prefer_standard_edition: bool = True,
) -> Resolved:
  """Resolve one track's tags from the sources available.

  Args:
    probed: the file's own local facts (§5a step 0).
    candidates: every release spotify returned for the ISRC.
    overrides: hand-edited values from `library.toml`, which outrank every
      source (§7).
    prefer_standard_edition: passed through to §7b's ranking.

  Returns:
    The tags to write, the per-field provenance, and any review flags.
  """
  overrides = overrides or {}
  provenance: dict[str, str] = {}
  flags: list[str] = []

  # the ISRC is the file's own (§7); it is the key everything else hangs off.
  tags = Tags(isrc=probed.isrc)
  if probed.isrc:
    provenance["isrc"] = FILE_TAG
  else:
    flags.append(FLAG_NO_ISRC)

  # the filename is a first-class source for artist credit (§6), not a
  # last resort — it is the operator's own curation.
  name_artist, name_title = split_filename(probed.path.stem)
  parsed_name = split_title(name_title)

  chosen = choose_release(candidates, prefer_standard_edition=prefer_standard_edition)
  if chosen is None:
    flags.append(FLAG_NO_RELEASE)
    # nothing but the file itself is known; fall back to what it is called.
    tags = replace(
      tags,
      title=render_title(parsed_name.name, parsed_name.features, parsed_name.mix),
      artist=name_artist or None,
      mix_name=parsed_name.mix,
      remixer=remixer_from_mix(parsed_name.mix),
    )
    provenance.update(
      {
        k: FILENAME
        for k in ("title", "artist", "mix_name", "remixer")
        if getattr(tags, k)
      }
    )
    return _apply_overrides(Resolved(tags, provenance, tuple(flags)), overrides)

  # no source's title string is written verbatim (§7a): split and re-render.
  parsed = split_title(chosen.track_name)
  features = parsed.features or parsed_name.features
  mix = parsed.mix or parsed_name.mix
  remixer = remixer_from_mix(mix)

  # §7a: `artist` is main artists plus the remixer; `album artist` is main
  # artists only, never the remixer and never a feature.
  main = [a for a in chosen.track_artists if a not in features]
  date = earliest_release_date(candidates)

  tags = replace(
    tags,
    title=render_title(parsed.name, features, mix),
    artist=join_artists(main) or name_artist or None,
    album=chosen.album_name,
    album_artist=join_artists(chosen.album_artists) or None,
    date=date,
    track_number=chosen.track_number or None,
    track_count=chosen.total_tracks or None,
    disc_number=chosen.disc_number or None,
    mix_name=mix,
    remixer=remixer,
    # §7d: TOPE is meaningful only on remixes, and an empty one is noise.
    original_artist=join_artists(main) if remixer else None,
  )

  provenance.update(
    {
      "title": SPOTIFY,
      "artist": SPOTIFY if main else FILENAME,
      "album": SPOTIFY,
      "album_artist": SPOTIFY,
      "track_number": SPOTIFY,
      "track_count": SPOTIFY,
      "disc_number": SPOTIFY,
    }
  )
  if date:
    # F33: the date is the MIN across all releases, not the chosen one's.
    provenance["date"] = SPOTIFY
    provenance["year"] = DERIVED
  if mix:
    provenance["mix_name"] = SPOTIFY if parsed.mix else FILENAME
  if remixer:
    provenance["remixer"] = DERIVED
    provenance["original_artist"] = DERIVED

  # artwork is §7c's chain, which needs itunes; until then it is unresolved
  # and the track is flagged rather than given an unverified image (G5).
  flags.append(FLAG_NO_ARTWORK)

  return _apply_overrides(Resolved(tags, provenance, tuple(flags)), overrides)


def _apply_overrides(resolved: Resolved, overrides: dict[str, str]) -> Resolved:
  """Let hand-edited values win, and mark them as manual.

  Args:
    resolved: what the sources produced.
    overrides: values asserted by the operator in `library.toml`.

  Returns:
    The resolved tags with overrides applied.
  """
  # library.toml is text, but Tags carries ints (track number, BPM) and bytes
  # (artwork). writing a string into an int field would put nonsense in a tag,
  # so a value that cannot be coerced is ignored rather than written.
  # `Any` because the loop below coerces each value to that field's declared
  # type; mypy cannot follow that through a dynamic dict into replace().
  types = {f.name: f.type for f in fields(resolved.tags)}
  usable: dict[str, Any] = {}
  for key, value in overrides.items():
    if not value or key not in types:
      continue
    declared = str(types[key])
    if "bytes" in declared:
      continue
    if "int" in declared:
      try:
        usable[key] = int(value)
      except ValueError:
        continue
    else:
      usable[key] = value

  if not usable:
    return resolved

  provenance = dict(resolved.provenance)
  provenance.update(dict.fromkeys(usable, MANUAL))
  return Resolved(
    tags=replace(resolved.tags, **usable),
    provenance=provenance,
    flags=resolved.flags,
  )


def year_of(resolved: Resolved) -> str | None:
  """Return the year a resolved track should carry.

  Args:
    resolved: the arbitrated result.

  Returns:
    The four-digit year, derived from the release date.
  """
  return _year_of(resolved.tags.date)
