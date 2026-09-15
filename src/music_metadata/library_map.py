"""`library.toml` — one map, generated and editable (SPEC.md §9b).

one entry per audio file, keyed by decoded-audio md5 (F44). it is the map, the
override file and the worklist at once; an earlier draft split those into three
artefacts, which meant the operator had to know which one to open.

**an empty field is an invitation.** `beatport = ""` is the worklist entry: find
the listing, paste the URL, re-run.

**the resolver never overwrites what it did not write.** the sidecar keeps the
last value it generated per `(md5, field)`:

```text
file value == last generated  ->  ours to refresh
file value != last generated  ->  the operator edited it; preserve verbatim
```

no marker to remember and no ceremony — editing a line *is* the act of asserting
it, and clearing a line hands the field back to the resolver.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from music_metadata.store import Store

# the fields the map carries, in the order §9b prints them. title, artist and
# album are written for legibility and are not read back as resolver input;
# `isrc` and the service URLs are.
FIELDS = ("file", "title", "artist", "album", "isrc", "spotify", "itunes", "beatport")

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


def merge(
  audio_md5: str,
  resolved: dict[str, str],
  on_disk: dict[str, str],
  generated: dict[str, str],
) -> Entry:
  """Apply §9b's merge rule to one entry.

  Args:
    audio_md5: the track's decoded-audio md5.
    resolved: what the resolver produced this run.
    on_disk: what the file currently holds for this track.
    generated: what the resolver wrote for this track last run.

  Returns:
    The merged entry, naming which fields the operator asserted by hand.
  """
  values: dict[str, str] = {}
  manual: set[str] = set()

  for name in FIELDS:
    current = on_disk.get(name, "")
    last = generated.get(name, "")
    fresh = resolved.get(name, "")

    # a value that differs from what we generated was typed by the operator.
    # an empty one is not an edit: clearing a line hands the field back.
    if current and current != last:
      values[name] = current
      manual.add(name)
    else:
      values[name] = fresh

  return Entry(audio_md5=audio_md5, values=values, manual=frozenset(manual))


def write(path: Path, entries: list[Entry], store: Store) -> None:
  """Write the map and record what was generated, for the next run's merge.

  Only resolver-generated values are recorded. A hand-edited value is not ours
  and must not become the baseline we later compare against, or the operator's
  next edit would look like our own output.

  Args:
    path: the `library.toml` file.
    entries: the merged rows.
    store: the sidecar, which remembers what we generated.
  """
  path.write_text(render(entries))
  for entry in entries:
    store.put_generated(
      entry.audio_md5,
      {k: v for k, v in entry.values.items() if k not in entry.manual},
    )


def set_isrc(path: Path, audio_md5: str, isrc: str) -> bool:
  """Write one entry's `isrc` in place, leaving the rest of the file untouched.

  **The whole file is not regenerated.** §9b's merge already preserves
  hand-edits, but rewriting only the one line means every other edit, every
  comment and the file's exact shape survive a lookup that touched one track —
  which matters when the operator is working down a list of 55.

  Args:
    path: the map file.
    audio_md5: which entry to change.
    isrc: the value to set.

  Returns:
    True when the file was changed. False when there is no such entry, or it
    already said this.
  """
  if not path.is_file():
    return False
  text = path.read_text()
  heading = f'["{audio_md5}"]'
  start = text.find(heading)
  if start == -1:
    return False
  end = text.find('\n["', start + 1)
  stop = end if end != -1 else len(text)

  out = []
  changed = False
  for line in text[start:stop].splitlines(keepends=True):
    if line.lstrip().startswith("isrc"):
      newline = "\n" if line.endswith("\n") else ""
      # the trailing `# not found` comment goes with the value; it is no
      # longer true, and leaving it would read as a contradiction.
      replacement = f'isrc     = "{isrc}"{newline}'
      if line == replacement:
        return False
      out.append(replacement)
      changed = True
    else:
      out.append(line)
  if not changed:
    return False
  path.write_text(text[:start] + "".join(out) + text[stop:])
  return True
