"""the map and the overrides — two files, one shape (SPEC.md §9b).

one entry per audio file, keyed by decoded-audio md5 (F44).

**`library.toml` is generated and `overrides.toml` is yours.** §9b originally
made one file do both jobs, on the reasoning that the operator should not have
to know which artefact to open. that reasoning was wrong, and the way it failed
is worth keeping written down:

- telling an edit from a generated value meant remembering what was generated
  last run, in a third place. when an *algorithm* changed — §7b's edition
  preference — 15 album names moved and every one then read as hand-typed, and
  would have pinned itself forever.
- the file the operator's edits lived in was also the file the pipeline
  rewrote. regenerating it is a normal operation, and a normal operation must
  never be able to destroy work. it did.

so the split is not tidiness. **`library.toml` can be deleted at any moment and
regenerated exactly**; nothing in it is authored. `overrides.toml` holds only
values someone typed, and the pipeline appends to it but never rewrites it.

**an empty field in the map is an invitation.** `beatport = ""` is the worklist
entry: find the listing, paste the URL into `overrides.toml`, re-run.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# the fields the map carries, in the order §9b prints them. title, artist and
# album are written for legibility and are not read back as resolver input;
# `isrc` and the service URLs are.
# `artwork` is last because it is the longest value and the least scanned —
# it holds the cover's source url, and accepts an apple music link when the
# itunes search index does not carry the release (measured on `Checkers`).
FIELDS = (
  "file",
  "title",
  "artist",
  "album",
  "isrc",
  "spotify",
  "itunes",
  "beatport",
  "artwork",
)

# what an empty value means, printed beside it so the file reads as a worklist.
_NOT_FOUND_COMMENT = "        # not found"


class MapError(RuntimeError):
  """raised when the map on disk cannot be read."""


@dataclass(frozen=True, slots=True)
class Entry:
  """one row of the map."""

  audio_md5: str
  values: dict[str, str]
  manual: frozenset[str] = frozenset()


def _escape(value: str) -> str:
  """Escape a value for a TOML basic string.

  Args:
    value: the raw text.

  Returns:
    The escaped text, without surrounding quotes.
  """
  return value.replace("\\", "\\\\").replace('"', '\\"')


def render(entries: list[Entry]) -> str:
  """Render the map as TOML.

  **One table per md5, not per file.** §9b describes the map as "one entry per
  audio file, keyed by decoded-audio md5" — but §11a documents three class-A
  duplicates where two files share one md5, and TOML cannot declare the same
  key twice. the two clauses cannot both hold, and md5 keying is the load-
  bearing one: it is what makes the map stable across a rename (F44).

  a duplicated md5 is therefore one entry, with the other paths named in a
  comment so nothing is hidden. §11a's report is where duplicates are acted on.

  Args:
    entries: the rows, in the order they should appear.

  Returns:
    The file contents.
  """
  out = [
    "# library.toml — the map. one entry per recording, keyed by decoded-audio md5.",
    "# regenerated every run. hand-edited values are preserved verbatim.",
    "",
  ]
  seen: dict[str, Entry] = {}
  ordered: list[Entry] = []
  duplicates: dict[str, list[str]] = {}
  for entry in entries:
    if entry.audio_md5 in seen:
      # same decoded audio at another path — §11a class A.
      duplicates.setdefault(entry.audio_md5, []).append(entry.values.get("file", ""))
      continue
    seen[entry.audio_md5] = entry
    ordered.append(entry)

  for entry in ordered:
    out.append(f'["{entry.audio_md5}"]')
    for other in duplicates.get(entry.audio_md5, []):
      out.append(f"# also at: {other}   (§11a class A duplicate)")
    for name in FIELDS:
      value = entry.values.get(name, "")
      line = f'{name:<8} = "{_escape(value)}"'
      if not value:
        line += _NOT_FOUND_COMMENT
      out.append(line)
    out.append("")
  return "\n".join(out)


def read(path: Path) -> dict[str, dict[str, str]]:
  """Read the map back.

  Args:
    path: the `library.toml` file.

  Returns:
    md5 to field values. Empty when the file does not exist — §9b says the map
    is safe to delete, so a missing file is not an error.
  """
  if not path.is_file():
    return {}
  try:
    with path.open("rb") as handle:
      raw = tomllib.load(handle)
  except tomllib.TOMLDecodeError as exc:
    # **not swallowed into an empty map.** the file carries hand-asserted
    # values (§9b), and treating a malformed one as absent would discard them
    # silently on the next write. §9b says the map is safe to *delete* — that
    # is the operator's call to make, knowing what it costs.
    msg = (
      f"{path} is not valid TOML: {exc}. "
      f"fix the file, or delete it to regenerate (hand-edited values are lost)."
    )
    raise MapError(msg) from exc
  return {
    md5: {k: str(v) for k, v in table.items()}
    for md5, table in raw.items()
    if isinstance(table, dict)
  }


def write(path: Path, entries: list[Entry]) -> None:
  """Write the map.

  **No merge, and no baseline to keep.** The map is generated in full every
  run; nothing in it is authored, so there is nothing to preserve. Assertions
  live in `overrides.toml` and are never written here.

  Args:
    path: the `library.toml` file.
    entries: the rows to write.
  """
  path.write_text(render(entries))


OVERRIDES_HEADER = (
  "# overrides.toml — values you assert by hand.\n"
  "#\n"
  "# the pipeline reads this and never rewrites it. anything here outranks\n"
  "# every source (§9b), including the file's own tags.\n"
  "#\n"
  "# entries are keyed by audio md5; `library.toml` is the index to look them\n"
  "# up in. set only the fields you mean to assert. `file` is ignored and is\n"
  "# here so an entry says what it is.\n"
)


def read_overrides(path: Path) -> dict[str, dict[str, str]]:
  """Read the operator's assertions.

  Args:
    path: the `overrides.toml` file.

  Returns:
    md5 to asserted fields, with empty values and the `file` label dropped. An
    absent file is normal — an operator who has asserted nothing overrides
    nothing.

  Raises:
    MapError: if the file exists but is not valid TOML. A typo has to fail
      loudly: silently ignoring it would discard the operator's work at exactly
      the moment they were most deliberate about it.
  """
  if not path.is_file():
    return {}
  out: dict[str, dict[str, str]] = {}
  for md5, values in read(path).items():
    asserted = {k: v for k, v in values.items() if v and k != "file"}
    if asserted:
      out[md5] = asserted
  return out


def set_override(path: Path, audio_md5: str, field: str, value: str) -> bool:
  """Record one asserted value, creating the file or the entry as needed.

  **Only ever adds or replaces one field.** Every other entry, every other
  field and every comment survives byte-for-byte, because this runs while the
  operator may be part-way through editing the same file.

  Args:
    path: the `overrides.toml` file.
    audio_md5: which track.
    field: which field to assert.
    value: the value.

  Returns:
    True when the file changed.

  Raises:
    MapError: if `field` is not one the map carries.
  """
  if field not in FIELDS:
    msg = f"unknown field {field!r}; expected one of {FIELDS}"
    raise MapError(msg)

  text = path.read_text() if path.is_file() else OVERRIDES_HEADER
  heading = f'["{audio_md5}"]'
  line = f'{field:<8} = "{_escape(value)}"\n'

  start = text.find(heading)
  if start == -1:
    path.write_text(f"{text.rstrip(chr(10))}\n\n{heading}\n{line}")
    return True

  end = text.find('\n["', start + 1)
  stop = end if end != -1 else len(text)
  out: list[str] = []
  replaced = False
  for existing in text[start:stop].splitlines(keepends=True):
    stripped = existing.lstrip()
    if stripped.startswith(f"{field} ") or stripped.startswith(f"{field}="):
      if existing.rstrip("\n") == line.rstrip("\n"):
        return False
      out.append(line)
      replaced = True
    else:
      out.append(existing)
  if not replaced:
    out = ["".join(out).rstrip("\n") + "\n", line]
  path.write_text(text[:start] + "".join(out) + text[stop:])
  return True
