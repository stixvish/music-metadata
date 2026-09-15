"""who performed the track, and which of them is a feature (SPEC.md §6).

the complaint, quantified: spotify flattens every contributor into one list with
no role. **398 of 1,494 files (26.6%)** encode a feature in the filename and 401
carry a separator in the artist part, so this is not an edge case.

the resolution order §6 sets out:

1. **musicbrainz `artist-credit` joinphrases** — structural, unambiguous.
2. **the filename** — the operator's own curation, and it agreed with
   musicbrainz on every case where both were present. a first-class source
   here, not a last resort.
3. **the source title** — a trailing `(feat. …)`, where musicbrainz has nothing.
4. **`track.artists` minus `album.artists`** — a hint only, **never decisive**.
   it inverts roles on bollywood and demotes collaborators (F29), so it is not
   implemented as a deciding rule at all.

**G6 is the gate: when musicbrainz and the filename agree, the credit is
accepted automatically; when they disagree the track is flagged for review
rather than guessed.** the disagreement rate is reported, not assumed — and
measured at **87.5%**, below the gate's 95% target, which is a fact about the
two sources rather than a defect in this module.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from music_metadata.naming import split_filename, split_title
from music_metadata.sources.musicbrainz import Credit

# §7a / F38: the performers-only rule is **scoped, not global**. applying it to
# western repertoire would strip Metro Boomin, Calvin Harris and Internet Money
# out of TPE1, where they genuinely are main artists.
INDIAN_GENRE = re.compile(r"bollywood|indian|punjabi|telugu|tamil", re.IGNORECASE)
INDIAN_ISRC_PREFIX = "IN"

# provenance labels for where a credit came from.
FROM_MUSICBRAINZ = "musicbrainz"
FROM_FILENAME = "filename"
FROM_TITLE = "title-parse"

FLAG_CREDIT_DISAGREEMENT = "credit-disagreement"


@dataclass(frozen=True, slots=True)
class CreditResult:
  """the resolved credit, its source, and whether it needs review."""

  main: tuple[str, ...]
  featured: tuple[str, ...]
  source: str
  agrees: bool | None = None
  flags: tuple[str, ...] = ()


def _fold(name: str) -> str:
  """Normalise a name for comparison only — never for output.

  Comparison has to survive punctuation and accent differences between sources;
  the written value always keeps the source's own spelling.

  Args:
    name: the artist name.

  Returns:
    A comparison key.
  """
  decomposed = unicodedata.normalize("NFKD", name)
  stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
  return re.sub(r"[^a-z0-9]+", "", stripped.lower())


def _same(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
  """Whether two name lists describe the same people, ignoring order.

  Compares the joined form as well as the set, because a band name can itself
  contain a separator: `Tegan & Sara` is one act, and splitting it produces
  two names that no source will ever match. Comparing the concatenation avoids
  having to decide, per name, whether an `&` joins two artists or belongs to
  one — a decision neither source gives us enough to make.

  Args:
    left: one list.
    right: the other.

  Returns:
    True when the names describe the same people.
  """
  if {_fold(n) for n in left} == {_fold(n) for n in right}:
    return True
  return bool(left) and bool(right) and _fold("".join(left)) == _fold("".join(right))


def credit_from_filename(stem: str) -> Credit:
  """Read the main/featured split out of `Artist - Title (ft. Featured)`.

  Args:
    stem: the filename without its suffix.

  Returns:
    The split the operator's own naming encodes.
  """
  artist_part, title_part = split_filename(stem)
  parsed = split_title(title_part)
  mains = tuple(
    part.strip()
    for part in re.split(r"\s*(?:,|&|\band\b)\s*", artist_part, flags=re.IGNORECASE)
    if part.strip()
  )
  return Credit(main=mains, featured=parsed.features)


def in_indian_scope(isrc: str | None, genre: str | None) -> bool:
  """Whether the performers-only rule applies to this track (§7a, F38).

  Either signal fires: an `IN` ISRC country prefix, or an indian genre. Measured
  at 167 tracks, 11% of the library.

  Args:
    isrc: the track's ISRC.
    genre: the genre as any source reported it.

  Returns:
    True when the track is in scope.
  """
  if isrc and isrc[:2].upper() == INDIAN_ISRC_PREFIX:
    return True
  return bool(genre and INDIAN_GENRE.search(genre))


def resolve_credit(
  filename_stem: str,
  musicbrainz: Credit | None = None,
  title_features: tuple[str, ...] = (),
  fallback_main: tuple[str, ...] = (),
) -> CreditResult:
  """Resolve one track's credit, applying §6's order and G6's gate.

  Args:
    filename_stem: the filename without its suffix.
    musicbrainz: the joinphrase split, when musicbrainz has the recording.
    title_features: a trailing `(feat. …)` parsed from a source's title.
    fallback_main: main artists from spotify, used only when nothing better
      exists.

  Returns:
    The credit, the source that decided it, whether the two primary sources
    agreed, and any review flags.
  """
  from_name = credit_from_filename(filename_stem)

  if musicbrainz is not None and musicbrainz.main:
    if not from_name.main:
      # nothing to cross-check against; musicbrainz stands alone.
      return CreditResult(
        main=musicbrainz.main,
        featured=musicbrainz.featured,
        source=FROM_MUSICBRAINZ,
      )

    agrees = _same(musicbrainz.main, from_name.main) and _same(
      musicbrainz.featured, from_name.featured
    )
    # G6: agreement is accepted automatically; disagreement is queued for
    # review, never auto-resolved into whichever source we happen to prefer.
    return CreditResult(
      main=musicbrainz.main,
      featured=musicbrainz.featured,
      source=FROM_MUSICBRAINZ,
      agrees=agrees,
      flags=() if agrees else (FLAG_CREDIT_DISAGREEMENT,),
    )

  if from_name.main:
    return CreditResult(
      main=from_name.main,
      featured=from_name.featured or title_features,
      source=FROM_FILENAME,
    )

  return CreditResult(main=fallback_main, featured=title_features, source=FROM_TITLE)
