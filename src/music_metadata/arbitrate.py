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

from music_metadata.artwork import Artwork
from music_metadata.credit import (
  FLAG_CREDIT_DISAGREEMENT,
  in_indian_scope,
  render_credit,
  resolve_credit,
)
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
from music_metadata.sources.beatport import Match
from music_metadata.sources.discogs import DiscogsRelease
from music_metadata.sources.itunes import ItunesRelease
from music_metadata.sources.musicbrainz import Credit, Work
from music_metadata.tag import Tags

# provenance labels. one string per source so `verify` can count them.
MANUAL = "manual"
SPOTIFY = "spotify"
FILENAME = "filename"
FILE_TAG = "file-tag"
DERIVED = "derived"
MUSICBRAINZ = "musicbrainz"
ITUNES = "itunes"
DISCOGS = "discogs"
BEATPORT = "beatport"

# flags raised for the review queue (§14). a flag is never a silent fallback.
FLAG_NO_ISRC = "no-isrc"
FLAG_NO_PERFORMER = "no-performer-credit"
FLAG_NO_RELEASE = "no-release"
FLAG_NO_ARTWORK = "no-artwork"
# OQ-8: the beatport listing is materially longer — a re-acquisition candidate,
# never a substitution.
FLAG_SHORTER_THAN_BEATPORT = "shorter-than-beatport"


@dataclass(frozen=True, slots=True)
class Resolved:
  """the tags to write, where each came from, and what needs review."""

  tags: Tags
  provenance: dict[str, str] = field(default_factory=dict)
  flags: tuple[str, ...] = ()
  # what a flagged decision is actually between, keyed by flag. the review
  # queue shows this rather than a bare field value.
  alternatives: dict[str, str] = field(default_factory=dict)


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
  prefer_expanded_edition: bool = True,
  musicbrainz: Credit | None = None,
  work: Work | None = None,
  itunes: ItunesRelease | None = None,
  discogs: DiscogsRelease | None = None,
  artwork: Artwork | None = None,
  beatport: Match | None = None,
) -> Resolved:
  """Resolve one track's tags from the sources available.

  Args:
    probed: the file's own local facts (§5a step 0).
    candidates: every release spotify returned for the ISRC.
    overrides: hand-edited values from `library.toml`, which outrank every
      source (§7).
    prefer_expanded_edition: passed through to §7b's ranking.
    musicbrainz: the joinphrase credit split, when musicbrainz has the
      recording (§6).
    work: the work's writing credits, for `TCOM` and `TEXT` (§7d).
    itunes: the verified itunes release, for the genre fallback (§7).
    discogs: the discogs release, for label and a deeper genre (F46/F47).
    artwork: the artwork §7c's chain verified, if any.
    beatport: the beatport match and its G3 field class, if any.

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

  chosen = choose_release(candidates, prefer_expanded_edition=prefer_expanded_edition)
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

  # §6's resolution order, gated by G6. the filename is a first-class source
  # here, not a last resort.
  # §7a / F38: **in indian scope, spotify's artist list is not usable as a
  # fallback.** F29 measured that it inverts roles there, promoting music
  # directors into `artists[]` — so an indian track with no musicbrainz and no
  # filename credit is flagged rather than given a list that names the wrong
  # people. everywhere else a producer credited as an artist genuinely is one.
  indian = in_indian_scope(probed.isrc, tags.genre)
  spotify_fallback = (
    () if indian else tuple(a for a in chosen.track_artists if a not in features)
  )
  credit = resolve_credit(
    probed.path.stem,
    musicbrainz=musicbrainz,
    title_features=features,
    fallback_main=spotify_fallback,
  )
  if indian and not credit.main:
    flags.append(FLAG_NO_PERFORMER)
  features = credit.featured or features
  flags += list(credit.flags)
  credit_alternative = credit.alternative

  # §7a: `artist` is main artists plus the remixer; `album artist` is main
  # artists only, never the remixer and never a feature.
  main = list(credit.main)
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
      "artist": credit.source,
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

  # §7d: composer and lyricist wherever musicbrainz supplies them. F52 measured
  # that it does so in indian repertoire (10/10) and uses the role-less `writer`
  # relation everywhere else — which is NOT promoted to either frame, because a
  # wrong role gets trusted (§7f's rule, applied to credits).
  if work is not None:
    if work.composers:
      tags = replace(tags, composer=join_artists(list(work.composers)))
      provenance["composer"] = MUSICBRAINZ
    if work.lyricists:
      tags = replace(tags, lyricist=join_artists(list(work.lyricists)))
      provenance["lyricist"] = MUSICBRAINZ

  # §7 precedence for genre: beatport, then discogs `styles[0]` (F47), then
  # itunes `primaryGenreName`. genre transfers in **both** G3 classes — F23 is
  # explicit that a different edit of the same work still shares its genre.
  if beatport is not None and beatport.track.best_genre:
    tags = replace(tags, genre=beatport.track.best_genre)
    provenance["genre"] = BEATPORT
  elif discogs is not None and discogs.style:
    tags = replace(tags, genre=discogs.style)
    provenance["genre"] = DISCOGS
  elif itunes is not None and itunes.primary_genre:
    tags = replace(tags, genre=itunes.primary_genre)
    provenance["genre"] = ITUNES

  # §7 precedence for label: beatport, then discogs `labels[]` (F46). label
  # also transfers in both classes.
  if beatport is not None and beatport.track.label:
    tags = replace(tags, label=beatport.track.label)
    provenance["label"] = BEATPORT
  elif discogs is not None and discogs.label:
    tags = replace(tags, label=discogs.label)
    provenance["label"] = DISCOGS

  if beatport is not None:
    # G3's split. **bpm, key and length transfer ONLY when the durations agree**
    # — outside ±5s this is a different recording, and its tempo is not this
    # file's tempo.
    if beatport.transfers_everything:
      if beatport.track.bpm is not None:
        tags = replace(tags, bpm=beatport.track.bpm)
        provenance["bpm"] = BEATPORT
      # §7f: camelot, and None rather than a guess when unparseable.
      camelot = beatport.track.camelot_key
      if camelot:
        tags = replace(tags, key=camelot)
        provenance["key"] = BEATPORT

    # remixer identity transfers in both classes (G3).
    if beatport.track.remixers and not tags.remixer:
      tags = replace(tags, remixer=join_artists(list(beatport.track.remixers)))
      provenance["remixer"] = BEATPORT

    # OQ-8: flag, never substitute, and never adopt beatport's ISRC (G9).
    if beatport.materially_longer:
      flags.append(FLAG_SHORTER_THAN_BEATPORT)

  # G5: artwork is refetched for every track, but only from a **verified**
  # release. when nothing verifies, the existing embedded art is kept and the
  # track is flagged — never replaced by an unverified image.
  if artwork is not None:
    tags = replace(tags, artwork=artwork.data, artwork_mime=artwork.mime)
    provenance["artwork"] = artwork.candidate
  else:
    flags.append(FLAG_NO_ARTWORK)

  alternatives: dict[str, str] = {}
  if credit_alternative is not None:
    alternatives[FLAG_CREDIT_DISAGREEMENT] = render_credit(
      credit_alternative.main, credit_alternative.featured
    )

  return _apply_overrides(
    Resolved(tags, provenance, tuple(flags), alternatives), overrides
  )


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
    alternatives=resolved.alternatives,
  )


def year_of(resolved: Resolved) -> str | None:
  """Return the year a resolved track should carry.

  Args:
    resolved: the arbitrated result.

  Returns:
    The four-digit year, derived from the release date.
  """
  return _year_of(resolved.tags.date)
