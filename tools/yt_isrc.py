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
stdin. nothing is written unless an ISRC was actually recovered.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_metadata import library_map  # noqa: E402 — needs the path above
from music_metadata.config import DEFAULT_SIDECAR, load_env, require  # noqa: E402
from music_metadata.dedup import DURATION_TOLERANCE_S  # noqa: E402
from music_metadata.sources.base import SourceError  # noqa: E402
from music_metadata.sources.musicfetch import Musicfetch, UrlMatch  # noqa: E402
from music_metadata.store import Store  # noqa: E402


def _client() -> Musicfetch:
  """Build a client from the operator's token.

  Returns:
    The client.
  """
  load_env()
  return Musicfetch(require("MUSICMATCH_TOKEN"))


def _describe(url: str, match: UrlMatch) -> str:
  """Render one lookup for a human.

  Args:
    url: what was looked up.
    match: what came back.

  Returns:
    A single line.
  """
  if match.isrc:
    who = ", ".join(match.artists) or "?"
    return f"{match.isrc}  {who} — {match.name}"
  if match.looks_like_a_video:
    return f"no isrc — this looks like a video upload, not a track.  {url}"
  return f"no isrc — musicfetch could not place this url.  {url}"


def cmd_look(args: argparse.Namespace) -> int:
  client = _client()
  failures = 0
  try:
    for url in args.url:
      try:
        match = client.isrc_for_url(url)
      except SourceError as exc:
        print(f"FAIL  {url}: {exc}")
        failures += 1
        continue
      print(_describe(url, match))
      failures += 0 if match.isrc else 1
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
  text = args.map.read_text()
  written = skipped = 0
  try:
    for key, url in _pairs(args.pairs):
      md5 = key if key in rows else by_file.get(key)
      if md5 is None:
        print(f"SKIP  no entry for {key!r}")
        skipped += 1
        continue
      try:
        match = client.isrc_for_url(url)
      except SourceError as exc:
        print(f"FAIL  {key}: {exc}")
        skipped += 1
        continue
      if not match.isrc:
        print(f"SKIP  {key}: {_describe(url, match)}")
        skipped += 1
        continue

      mine = local.get(md5)
      if mine and match.duration_s:
        delta = abs(match.duration_s - mine)
        if delta > DURATION_TOLERANCE_S:
          print(
            f"SKIP  {key}: {match.isrc} is {match.duration_s:.0f}s but the file "
            f"is {mine:.0f}s ({delta:.0f}s apart) — wrong track? (G10)"
          )
          skipped += 1
          continue

      # rewrite the one line in place, so every other hand-edit and every
      # comment in the file survives untouched.
      old = rows[md5].get("isrc", "")
      needle = f'["{md5}"]'
      start = text.index(needle)
      end = text.find('\n["', start + 1)
      block = text[start : end if end != -1 else len(text)]
      updated = _set_isrc(block, match.isrc)
      if updated == block:
        print(f"SKIP  {key}: already {old!r}")
        skipped += 1
        continue
      text = text[:start] + updated + text[end if end != -1 else len(text) :]
      written += 1
      print(f"OK    {key}  ->  {match.isrc}")
  finally:
    client.close()

  if written:
    args.map.write_text(text)
  print(f"\n{written} written to {args.map}, {skipped} skipped")
  return 0


def _set_isrc(block: str, isrc: str) -> str:
  """Replace the `isrc` line inside one map entry.

  Args:
    block: the entry's text, heading included.
    isrc: the value to set.

  Returns:
    The entry with its `isrc` line rewritten, or unchanged if it already said
    this. The trailing `# not found` comment goes with it — it is no longer
    true.
  """
  out = []
  changed = False
  for line in block.splitlines(keepends=True):
    if line.lstrip().startswith("isrc"):
      newline = "\n" if line.endswith("\n") else ""
      replacement = f'isrc     = "{isrc}"{newline}'
      if line == replacement:
        return block
      out.append(replacement)
      changed = True
    else:
      out.append(line)
  return "".join(out) if changed else block


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
  fill.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
  fill.set_defaults(func=cmd_fill)

  args = ap.parse_args()
  raise SystemExit(args.func(args))


if __name__ == "__main__":
  main()
