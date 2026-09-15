"""title and artist rendering — one canonical shape (SPEC.md §7a).

```text
{Name} (ft. {Featured artists}) [{Mix name}]
```

the parenthetical carries featured artists only; the bracket carries the mix
name only; either is omitted when it does not apply.

**no source's title string is written verbatim.** apple and spotify render mixes
as a dash suffix — `"Blessings - Odd Mob Remix"` (F25) — and put features
sometimes inside the track name and sometimes folded into the artist name (§6).
this module splits both apart and re-renders.

the one thing it does **not** do is strip `(From "…")`. §7b removes that by
choosing the right release; if it still reaches here, the release choice was
wrong, and quietly deleting it would hide the bug.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# §7a's normalisation table. the library currently holds both `[extended mix]`
# and bare `[extended]`; one spelling wins.
_MIX_ALIASES = {
  "extended mix": "Extended",
  "extended version": "Extended",
  "extended": "Extended",
  "radio edit": "Radio Edit",
  "radio mix": "Radio Edit",
  "radio version": "Radio Edit",
  "original mix": "Original",
  "original version": "Original",
  "original": "Original",
}

# a third-party rework. an extended or radio cut is the original artist
# reworking their own track, which §7a is explicit is *not* a remix.
_REMIX_KINDS = r"Remix|Flip|Bootleg|VIP|Edit|Rework|Refix"
_REMIXER = re.compile(rf"^(?P<who>.+?)\s+(?:{_REMIX_KINDS})$", re.IGNORECASE)

# mixes whose trailing word looks like a remix kind but which name no remixer.
_NOT_A_REMIX = {"radio edit", "extended", "original", "instrumental", "club mix"}

_FEATURE = re.compile(
  r"[(\[]\s*(?:feat|ft|featuring)\.?\s+(?P<who>[^)\]]+)[)\]]",
  re.IGNORECASE,
)
_TRAILING_BRACKET = re.compile(r"\s*\[(?P<inner>[^\]]+)\]\s*$")
_TRAILING_PAREN = re.compile(r"\s*\((?P<inner>[^)]+)\)\s*$")
_DASH_SUFFIX = re.compile(r"^(?P<name>.+?)\s+-\s+(?P<mix>[^-]+)$")

# a parenthetical that is part of the work's own name, not a mix or a feature.
# §7b removes `(From "…")` by choosing the right release; §7a leaves it visible.
#
# a bare number is the other case: `CHICA 305 (2)` is a **filename duplication
# marker**, not a mix. F39 is explicit that the ` (2)` suffix is "a symptom, not
# the test" — reading it as a mix would write `TIT3 = "2"`, which is nonsense,
# and all three of the library's class-A duplicates carry one.
_NOT_A_MIX = re.compile(r"^(from|from the)\b|^\d+$", re.IGNORECASE)

_ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\band\b)\s*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedTitle:
  """a source title split into its three parts."""

  name: str
  features: tuple[str, ...]
  mix: str | None


def join_artists(names: list[str] | tuple[str, ...]) -> str:
  """Join artist names in the house style (§7a, OQ-7).

  Comma between every artist, `&` before the last.

  Args:
    names: the artist names, in credit order.

  Returns:
    One display string; empty when there are no names.
  """
  clean = [n.strip() for n in names if n and n.strip()]
  if not clean:
    return ""
  if len(clean) == 1:
    return clean[0]
  return f"{', '.join(clean[:-1])} & {clean[-1]}"


def normalise_mix(mix: str | None) -> str | None:
  """Fold a mix name onto §7a's canonical spelling.

  Args:
    mix: the mix name as a source rendered it.

  Returns:
    The normalised name, or None when there is no mix. Names outside the
    table — `Odd Mob Remix`, `Continuous Mix`, `Instrumental` — pass through
    unchanged.
  """
  if not mix or not mix.strip():
    return None
  stripped = mix.strip()
  return _MIX_ALIASES.get(stripped.lower(), stripped)


def remixer_from_mix(mix: str | None) -> str | None:
  """Return the third-party remixer named by a mix, if there is one.

  `TPE4` holds a remixer **only** when the track is a remix by someone else.
  `Extended`, `Radio Edit`, `Club Mix`, `Original` and `Instrumental` name no
  remixer, and inventing one would credit the original artist as their own
  remixer.

  Args:
    mix: the normalised mix name.

  Returns:
    The remixer's name, or None.
  """
  if not mix:
    return None
  if mix.strip().lower() in _NOT_A_REMIX:
    return None
  match = _REMIXER.match(mix.strip())
  if match is None:
    return None
  who = match.group("who").strip()
  return who or None


def _split_features(blob: str) -> tuple[str, ...]:
  """Split a feature blob into individual artist names.

  Args:
    blob: the text inside `(feat. …)`.

  Returns:
    The names, in order.
  """
  return tuple(p.strip() for p in _ARTIST_SPLIT.split(blob) if p.strip())


def split_title(raw: str) -> ParsedTitle:
  """Split a source title into name, featured artists and mix name.

  Args:
    raw: the title exactly as spotify or itunes rendered it.

  Returns:
    The three parts. `mix` is normalised per §7a.
  """
  working = raw.strip()

  features: tuple[str, ...] = ()
  match = _FEATURE.search(working)
  if match is not None:
    features = _split_features(match.group("who"))
    # collapse the gap the excised parenthetical leaves behind, or a name like
    # `My Business (ft. Future) (2)` renders with a double space.
    working = re.sub(
      r"\s{2,}", " ", working[: match.start()] + working[match.end() :]
    ).strip()

  mix: str | None = None
  bracket = _TRAILING_BRACKET.search(working)
  if bracket is not None:
    mix = bracket.group("inner").strip()
    working = working[: bracket.start()].strip()
  else:
    paren = _TRAILING_PAREN.search(working)
    if paren is not None and not _NOT_A_MIX.match(paren.group("inner").strip()):
      mix = paren.group("inner").strip()
      working = working[: paren.start()].strip()

  if mix is not None and _NOT_A_MIX.match(mix):
    # a bracketed duplication marker, same as the parenthetical case.
    working = f"{working} [{mix}]".strip()
    mix = None

  if mix is None:
    dash = _DASH_SUFFIX.match(working)
    if dash is not None:
      mix = dash.group("mix").strip()
      working = dash.group("name").strip()

  return ParsedTitle(name=working, features=features, mix=normalise_mix(mix))


def render_title(
  name: str, features: tuple[str, ...] | list[str], mix: str | None
) -> str:
  """Render the canonical title shape (§7a).

  Args:
    name: the bare work name.
    features: featured artists, which go in the parenthetical.
    mix: the mix name, which goes in the bracket.

  Returns:
    `{Name} (ft. {Featured artists}) [{Mix name}]`, omitting whichever parts do
    not apply.
  """
  out = name.strip()
  clean = [f.strip() for f in features if f and f.strip()]
  if clean:
    out += f" (ft. {', '.join(clean)})"
  if mix:
    out += f" [{mix}]"
  return out


def split_filename(stem: str) -> tuple[str, str]:
  """Split `Artist - Title` as the operator's own filenames are shaped.

  §6 ranks the filename **second** for artist credit, above spotify and itunes,
  because it is the operator's own curation — it agreed with musicbrainz on
  every case where both were present. It is a first-class source here, not a
  last resort.

  Args:
    stem: the filename without its suffix.

  Returns:
    The artist part and the title part. When there is no separator the whole
    stem is the title and the artist part is empty.
  """
  artist, sep, title = stem.partition(" - ")
  if not sep:
    return ("", stem.strip())
  return (artist.strip(), title.strip())


# characters that genuinely cannot appear in a macOS filename, plus `:` —
# legal in HFS+ but rendered as `/` by Finder, which is worse than dropping it.
#
# **`*` and `?` are deliberately kept.** they are valid on macOS, and `*NSYNC`
# is the band's actual name: stripping punctuation that belongs to an artist
# would quietly rename them. this is a filesystem safety check, not a style
# preference.
_UNSAFE = re.compile(r'[/\\:<>|"\x00-\x1f]')
_COLLAPSE = re.compile(r"\s+")


def output_filename(title: str, artist: str, suffix: str) -> str:
  """Build the output file's name from the resolved tags.

  **The name is lowercased on purpose.** macOS is case-insensitive, so a later
  correction to an artist's capitalisation would otherwise rename the file —
  and rekordbox tracks files by path, so a rename costs a relink on a track the
  operator has already imported. Lowercasing means casing changes never move
  anything.

  The audio is copied, never transcoded (§9), so the extension is carried
  through unchanged rather than normalised.

  Args:
    title: the resolved title, already rendered to §7a's shape.
    artist: the resolved track artist.
    suffix: the source file's extension, including the dot.

  Returns:
    A filename safe to write into the output directory. Never empty, never a
    path, and never starting with a dot.
  """
  parts = [p for p in (artist.strip(), title.strip()) if p]
  stem = " - ".join(parts) if parts else "untitled"
  stem = _UNSAFE.sub("", stem)
  stem = _COLLAPSE.sub(" ", stem).strip(" .")
  return f"{(stem or 'untitled').lower()}{suffix.lower()}"
