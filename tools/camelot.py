#!/usr/bin/env python3
"""Convert musical key notation to Camelot notation.

Beatport reports keys as "Eb Minor", "Db Major", "F# Minor". Rekordbox and
Serato both display Camelot, and it is what harmonic mixing actually uses, so
`TKEY` is written in Camelot (SPEC.md §7e).

The wheel is circle-of-fifths ordered: B = major, A = its relative minor, so
nA and nB share the same seven notes. Anchors verified against published
charts: 1A = A-flat minor, 1B = B major, 8A = A minor, 8B = C major.
"""

# major keys in circle-of-fifths order starting at 8B = C major.
_MAJOR_BY_NUMBER = {
  8: "C", 9: "G", 10: "D", 11: "A", 12: "E", 1: "B",
  2: "F#", 3: "Db", 4: "Ab", 5: "Eb", 6: "Bb", 7: "F",
}
# each number's relative minor (the major's sixth degree).
_MINOR_BY_NUMBER = {
  8: "A", 9: "E", 10: "B", 11: "F#", 12: "Db", 1: "Ab",
  2: "Eb", 3: "Bb", 4: "F", 5: "C", 6: "G", 7: "D",
}

# enharmonic spellings normalised to the ones used above.
_ENHARMONIC = {
  "C#": "Db", "D#": "Eb", "G#": "Ab", "A#": "Bb", "Gb": "F#",
  "Cb": "B", "B#": "C", "Fb": "E", "E#": "F",
}


def _build() -> dict[tuple[str, str], str]:
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


if __name__ == "__main__":
  # every key Beatport returned during spec research, plus both anchors
  # and every enharmonic spelling.
  cases = [
    ("Eb Minor", "2A"), ("B Minor", "10A"), ("Ab Minor", "1A"),
    ("Db Major", "3B"), ("D Major", "10B"), ("E Major", "12B"),
    ("C Minor", "5A"), ("B Major", "1B"), ("G Minor", "6A"),
    ("A Minor", "8A"), ("C Major", "8B"),
    ("D# Minor", "2A"), ("G# Minor", "1A"), ("C# Major", "3B"),
    ("Gb Major", "2B"), ("A# Minor", "3A"),
    ("f# minor", "11A"), ("F MAJOR", "7B"), ("Bb maj", "6B"),
    ("", None), ("nonsense", None), ("H Minor", None),
  ]
  bad = 0
  for given, want in cases:
    got = to_camelot(given)
    ok = got == want
    bad += not ok
    print(f"  {'ok ' if ok else 'FAIL'}  {given!r:<14} -> {got!r:<6} (want {want!r})")
  # every code must be unique and all 24 must be covered
  codes = sorted(_TABLE.values())
  print(f"\n  codes: {len(codes)} unique={len(set(codes))==24} covered={set(codes)==set(f'{n}{l}' for n in range(1,13) for l in 'AB')}")
  print("  FAILURES:", bad)
  raise SystemExit(1 if bad else 0)
