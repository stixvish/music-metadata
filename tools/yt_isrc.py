"""recover ISRCs from youtube links, and optionally write them into the map.

F19: musicfetch's `/url` turns a youtube link into a fully resolved recording —
8 of 8 on the staging ids, with no fingerprint, no text search and no edition
ambiguity. this is the cheapest way to fill in the 55 files that carry no ISRC
tag (§2), and the only thing musicfetch is used for (F36).

**use the youtube *music* link, not the video link.** measured 2026-09-15:

    Eo-KmOd3i7s  "*NSYNC - Bye Bye Bye (Official Video)"  -> nothing
    fxHjlCBHuzA  "Bye Bye Bye" by *NSYNC                  -> USJI10000001

an official-video upload is a different entity from the track and resolves to
no release. this tool says so explicitly rather than reporting a failure.

usage:
  yt_isrc.py look URL [URL ...]        print what each url resolves to
  yt_isrc.py fill PAIRS [--map M]      write ISRCs into library.toml

`fill` reads lines of `<file-or-md5><TAB><url>`, so the worklist in
`tasks/no-isrc.md` can be pasted in with a url appended to each line. `-` reads
stdin. recovered ISRCs are written to `overrides.toml`; `library.toml` is only
read, to resolve a filename to its md5.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_metadata import library_map  # noqa: E402 — needs the path above
from music_metadata.config import DEFAULT_SIDECAR, load_env, require  # noqa: E402
from music_metadata.isrc_recovery import Recovery, recover  # noqa: E402
from music_metadata.sources.musicfetch import Musicfetch  # noqa: E402
from music_metadata.store import Store  # noqa: E402


def _client() -> Musicfetch:
  """Build a client from the operator's token.

  Returns:
    The client.
  """
  load_env()
  return Musicfetch(require("MUSICMATCH_TOKEN"))


def _describe(url: str, found: Recovery) -> str:
  """Render one lookup for a human.

  Args:
    url: what was looked up.
    found: what came back.

  Returns:
    A single line.
  """
  if found.usable:
    suffix = f"  [{found.note}]" if found.note else ""
    return f"{found.isrc}  {found.who or '?'} — {found.name}{suffix}"
  return f"no isrc — {found.note}  {url}"


def cmd_look(args: argparse.Namespace) -> int:
  client = _client()
  failures = 0
  try:
    for url in args.url:
      found = recover(url, client)
      print(_describe(url, found))
      failures += 0 if found.usable else 1
  finally:
    client.close()
  return 1 if failures else 0


def _pairs(source: str) -> list[tuple[str, str]]:
  """Read `<key><TAB><url>` lines.

  Args:
    source: a file path, or `-` for stdin.

  Returns:
    Key and url for each usable line. Blank lines and `#` comments are skipped.
  """
  text = sys.stdin.read() if source == "-" else Path(source).read_text()
  out = []
  for line in text.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
      continue
    key, _, url = line.partition("\t")
    if not url:
      key, _, url = line.rpartition(" ")
    if key.strip() and url.strip():
      out.append((key.strip(), url.strip()))
  return out


def cmd_fill(args: argparse.Namespace) -> int:
  rows = library_map.read(args.map)
  if not rows:
    print(f"FAIL  no map at {args.map} — run `music-metadata map --regenerate`")
    return 1

  # the worklist names files; the map is keyed by md5. accept either.
  by_file = {v.get("file", ""): md5 for md5, v in rows.items()}
  # **a recovered ISRC is checked against the file, not trusted on sight.**
  # G10's rule does not care where an ISRC came from: one whose recording is a
  # different length is not this file's ISRC, and pasting the wrong link is the
  # easiest mistake to make when working through 55 of them by hand.
  with Store.open(args.sidecar) as store:
    local = {
      r["audio_md5"]: r["duration_s"]
      for r in store.query("SELECT audio_md5, duration_s FROM files")
    }
  client = _client()
  written = skipped = 0
  try:
    for key, url in _pairs(args.pairs):
      md5 = key if key in rows else by_file.get(key)
      if md5 is None:
        print(f"SKIP  no entry for {key!r}")
        skipped += 1
        continue
      found = recover(url, client, local.get(md5))
      if not found.usable or not found.isrc:
        print(f"SKIP  {key}: {found.note}")
        skipped += 1
        continue
      library_map.set_override(args.overrides, md5, "file", rows[md5].get("file", ""))
      if not library_map.set_override(args.overrides, md5, "isrc", found.isrc):
        print(f"SKIP  {key}: already {rows[md5].get('isrc', '')!r}")
        skipped += 1
        continue
      written += 1
      note = f"  [{found.note}]" if found.note else ""
      print(f"OK    {key}  ->  {found.isrc}{note}")
  finally:
    client.close()

  print(f"\n{written} written to {args.map}, {skipped} skipped")
  return 0


def main() -> None:
  ap = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
  )
  sub = ap.add_subparsers(dest="cmd", required=True)

  look = sub.add_parser("look", help="print what each url resolves to")
  look.add_argument("url", nargs="+")
  look.set_defaults(func=cmd_look)

  fill = sub.add_parser("fill", help="write recovered ISRCs into library.toml")
  fill.add_argument("pairs", help="file of `<file-or-md5><TAB><url>` lines, or -")
  fill.add_argument("--map", type=Path, default=Path("library.toml"))
  fill.add_argument("--overrides", type=Path, default=Path("overrides.toml"))
  fill.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
  fill.set_defaults(func=cmd_fill)

  args = ap.parse_args()
  raise SystemExit(args.func(args))


if __name__ == "__main__":
  main()
