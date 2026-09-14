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

  Args:
    entries: the rows, in the order they should appear.

  Returns:
    The file contents.
  """
  out = [
    "# library.toml — the map. one entry per file, keyed by decoded-audio md5.",
    "# regenerated every run. hand-edited values are preserved verbatim.",
    "",
  ]
  for entry in entries:
    out.append(f'["{entry.audio_md5}"]')
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
  with path.open("rb") as handle:
    raw = tomllib.load(handle)
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
