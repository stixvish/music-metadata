"""musical key to camelot notation (SPEC.md §7f).

beatport reports keys as `"Eb Minor"`, `"Db Major"`, `"F# Minor"`. rekordbox and
serato both display camelot, and harmonic mixing is done in it, so `TKEY` is
written in camelot — storing `2A` rather than `Eb Minor` means the tag is usable
without mental conversion mid-set.

the wheel is circle-of-fifths ordered: `B` is major, `A` is its relative minor,
so `nA` and `nB` share the same seven notes and mix cleanly. anchors verified
against published charts: 1A = A♭ minor, 1B = B major, 8A = A minor, 8B = C
major ([dj.studio](https://dj.studio/blog/camelot-wheel), checked 2026-09-14).

**an unparseable key returns None and `TKEY` is left empty.** a wrong key is
worse than a missing one: it survives into a set and gets trusted. this mirrors
§7e's position on BPM.
"""

# fmt: off
# the alignment is the wheel: reading down a column walks the circle of fifths.
# one entry per line is what the formatter wants and it destroys that.
# major keys in circle-of-fifths order starting at 8B = C major.
_MAJOR_BY_NUMBER = {
  8: "C",  9: "G",  10: "D",  11: "A",  12: "E",  1: "B",
  2: "F#", 3: "Db", 4:  "Ab", 5:  "Eb", 6:  "Bb", 7: "F",
}
# each number's relative minor (the major's sixth degree).
_MINOR_BY_NUMBER = {
  8: "A",  9: "E",  10: "B",  11: "F#", 12: "Db", 1: "Ab",
  2: "Eb", 3: "Bb", 4:  "F",  5:  "C",  6:  "G",  7: "D",
}

# enharmonic spellings normalised to the ones used above.
_ENHARMONIC = {
  "C#": "Db", "D#": "Eb", "G#": "Ab", "A#": "Bb", "Gb": "F#",
  "Cb": "B",  "B#": "C",  "Fb": "E",  "E#": "F",
}
# fmt: on


def _build() -> dict[tuple[str, str], str]:
  """Build the (root, mode) -> camelot code table.

  Returns:
    Every one of the 24 codes, keyed by root note and mode.
  """
  table: dict[tuple[str, str], str] = {}
  for n, root in _MAJOR_BY_NUMBER.items():
    table[(root, "major")] = f"{n}B"
  for n, root in _MINOR_BY_NUMBER.items():
    table[(root, "minor")] = f"{n}A"
  return table


_TABLE = _build()


def to_camelot(key: str | None) -> str | None:
  """Return the Camelot code for a key string, or None if unparseable.

  Args:
    key: A key such as "Eb Minor", "F# maj", "A minor". Case-insensitive.

  Returns:
    A Camelot code such as "2A", or None when the input cannot be parsed.
    Returning None is deliberate: a wrong key is worse than a missing one.
  """
  if not key:
    return None
  parts = key.strip().replace("-", " ").split()
  if len(parts) < 2:
    return None
  root, mode = parts[0], parts[-1].lower()
  root = root[0].upper() + root[1:].replace("♯", "#").replace("♭", "b")
  root = _ENHARMONIC.get(root, root)
  if mode.startswith("min") or mode == "m":
    mode = "minor"
  elif mode.startswith("maj") or mode == "M":
    mode = "major"
  else:
    return None
  return _TABLE.get((root, mode))
