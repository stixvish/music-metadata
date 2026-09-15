"""the command line (SPEC.md §12).

the CLI and the web ui are two front doors to one sqlite store (§9a, §14);
neither is authoritative. resolution and tagging are **separate commands**
because the API is slow and rate-limited while tagging is fast and local —
caching resolution means the tag writer can be re-run freely.

nothing here writes to stdout directly: `output.emit` is the single sink, so
the ui can capture exactly what the CLI says.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import fields
from pathlib import Path

from music_metadata import library_map
from music_metadata.arbitrate import Resolved, arbitrate
from music_metadata.artwork import Artwork, resolve_artwork
from music_metadata.config import DEFAULT_SIDECAR, get, load_env, require
from music_metadata.output import Level, emit
from music_metadata.probe import ProbedFile, probe_tree
from music_metadata.release import ReleaseCandidate, choose_release
from music_metadata.sources.base import SourceError
from music_metadata.sources.discogs import Discogs, release_from_raw
from music_metadata.sources.itunes import Itunes, releases_from_raw
from music_metadata.sources.musicbrainz import (
  MusicBrainz,
  Work,
  recording_from_raw,
  work_from_raw,
)
from music_metadata.sources.spotify import Spotify, candidates_from_raw
from music_metadata.store import Store
from music_metadata.tag import Tags, read_tags, write_tags

DEFAULT_LIBRARY = Path.home() / "Music/library"


def _candidates_for(store: Store, probed: ProbedFile) -> list[ReleaseCandidate]:
  """Re-parse the cached spotify payload for one track. No network.

  Args:
    store: the sidecar.
    probed: the file's local facts.

  Returns:
    The release candidates, empty when nothing is cached.
  """
  if not probed.isrc:
    return []
  raw = store.get_raw(probed.isrc, "spotify")
  return candidates_from_raw(raw) if isinstance(raw, dict) else []


def _resolved_for(store: Store, probed: ProbedFile) -> Resolved:
  """Arbitrate one track from whatever is already cached. No network.

  Args:
    store: the sidecar.
    probed: the file's local facts.

  Returns:
    The resolved tags.
  """
  credit = None
  work: Work | None = None
  itunes_release = None
  discogs_release = None
  artwork: Artwork | None = None
  if probed.isrc:
    recording = recording_from_raw(store.get_raw(probed.isrc, "musicbrainz"))
    if recording is not None:
      credit = recording.credit
    raw_work = store.get_raw(probed.isrc, "work")
    if raw_work is not None:
      work = work_from_raw(raw_work)
    itunes_raw = store.get_raw(probed.isrc, "itunes")
    if itunes_raw is not None:
      releases = releases_from_raw(itunes_raw)
      itunes_release = releases[0] if releases else None
    discogs_release = release_from_raw(store.get_raw(probed.isrc, "discogs"))
    artwork = _artwork_from_store(store, probed.isrc)

  return arbitrate(
    probed,
    _candidates_for(store, probed),
    musicbrainz=credit,
    work=work,
    itunes=itunes_release,
    discogs=discogs_release,
    artwork=artwork,
  )


def _artwork_from_store(store: Store, isrc: str) -> Artwork | None:
  """Load the artwork bytes already fetched for a recording.

  §9a: 3-4 GB of covers are fetched once. re-reading them from disk is what
  makes `apply` re-runnable without re-downloading the library's artwork.

  Args:
    store: the sidecar.
    isrc: the recording's ISRC.

  Returns:
    The artwork, or None when none was cached.
  """
  rows = store.query("SELECT * FROM artwork WHERE isrc = ?", (isrc,))
  if not rows or not rows[0]["local_path"]:
    return None
  path = Path(rows[0]["local_path"])
  if not path.is_file():
    return None
  return Artwork(
    data=path.read_bytes(),
    mime="image/jpeg",
    width=int(rows[0]["width"] or 0),
    candidate=rows[0]["source_release"] or "cached",
    source_release=rows[0]["source_release"] or "",
    url=rows[0]["url_template"] or "",
  )


def render_credit_from_tags(resolved: Resolved) -> str:
  """Render the credit the resolver chose, as the review queue shows it.

  Args:
    resolved: the arbitrated result.

  Returns:
    The artist plus any featured artists carried in the title.
  """
  title = resolved.tags.title or ""
  _, _, tail = title.partition("(ft. ")
  featured = tail.partition(")")[0] if tail else ""
  artist = resolved.tags.artist or ""
  return f"{artist} (ft. {featured})" if featured else artist


def _map_row(
  probed: ProbedFile,
  resolved: Resolved,
  chosen: ReleaseCandidate | None,
) -> dict[str, str]:
  """Build one `library.toml` row.

  Args:
    probed: the file's local facts.
    resolved: the arbitrated tags.
    chosen: the release §7b picked, whose track id gives the spotify link.

  Returns:
    The field values for the map. An empty service field is the worklist
    entry §9b describes, not a gap to hide.
  """
  spotify_url = ""
  if chosen is not None and chosen.track_id:
    spotify_url = f"https://open.spotify.com/track/{chosen.track_id}"
  return {
    "file": probed.path.name,
    "title": resolved.tags.title or "",
    "artist": resolved.tags.artist or "",
    "album": resolved.tags.album or "",
    "isrc": probed.isrc or "",
    "spotify": spotify_url,
    "itunes": "",
    "beatport": "",
  }


def cmd_probe(args: argparse.Namespace) -> int:
  """Survey the library's local tag facts. No network.

  Args:
    args: parsed arguments.

  Returns:
    Process exit code.
  """
  with Store.open(args.sidecar) as store:
    total = with_isrc = 0
    for probed in probe_tree(args.library):
      store.put_file(
        path=str(probed.path),
        audio_md5=probed.audio_md5,
        duration_s=probed.duration_s,
        isrc=probed.isrc,
        mtime=probed.path.stat().st_mtime,
      )
      total += 1
      with_isrc += bool(probed.isrc)
      if total % 100 == 0:
        emit(f"probed {total}")

    emit(f"probed {total} files")
    emit(
      f"with ISRC {with_isrc} ({with_isrc / total * 100:.1f}%)" if total else "empty"
    )
    emit(f"without ISRC {total - with_isrc}")
  return 0


def cmd_resolve(args: argparse.Namespace) -> int:
  """Resolve identities through the source tiers into the sidecar.

  Args:
    args: parsed arguments.

  Returns:
    Process exit code.
  """
  load_env()
  with Store.open(args.sidecar) as store:
    rows = store.query(
      "SELECT * FROM files WHERE isrc_from_tag IS NOT NULL ORDER BY path"
    )
    if args.limit:
      rows = rows[: args.limit]
    if not rows:
      emit("nothing to resolve — run `probe` first", level=Level.WARN)
      return 1

    spotify = Spotify(require("SPOTIFY_CLIENT_ID"), require("SPOTIFY_CLIENT_SECRET"))
    musicbrainz = MusicBrainz()
    itunes = Itunes()
    discogs_token = get("DISCOGS_TOKEN")
    discogs = Discogs(discogs_token) if discogs_token else None
    art_dir = args.sidecar.parent / "artwork"
    art_dir.mkdir(parents=True, exist_ok=True)
    fetched = cached = mb_hits = mb_misses = mb_errors = 0
    art_hits = art_misses = 0
    try:
      for index, row in enumerate(rows, start=1):
        isrc = row["isrc_from_tag"]
        cached_already = store.get_raw(isrc, "spotify") is not None
        if cached_already and not args.refetch:
          cached += 1
          continue

        result = spotify.search_isrc(isrc)
        store.put_raw(isrc, "spotify", result.raw)

        # tier 2. a miss here is normal (F31), and so is the service being
        # briefly unavailable — musicbrainz 503s routinely (F30/F52). neither
        # may abort the run: §5's rule that a flaky tier cannot stop the
        # pipeline is not specific to beatport, and losing an hour of resolved
        # identities to one bad minute would be the expensive failure.
        recording = None
        try:
          recording, raw_mb = musicbrainz.recording_for_isrc(isrc)
          store.put_raw(isrc, "musicbrainz", raw_mb)
        except SourceError as exc:
          mb_errors += 1
          emit(f"  musicbrainz unavailable for {isrc}: {exc}", level=Level.WARN)

        if recording is None:
          mb_misses += 1
        else:
          mb_hits += 1
          if recording.work_id:
            try:
              _, raw_work = musicbrainz.work(recording.work_id)
              store.put_raw(isrc, "work", raw_work)
            except SourceError as exc:
              mb_errors += 1
              emit(f"  musicbrainz work failed for {isrc}: {exc}", level=Level.WARN)

        # tiers 2 and 3: itunes for the artwork chain and a genre fallback,
        # discogs for label. both are optional — a failure flags the track
        # rather than stopping the run (§5's rule applied beyond beatport).
        chosen = choose_release(result.candidates)
        if chosen is not None:
          album_artist = ", ".join(chosen.album_artists)
          try:
            # the album search doubles as the genre fallback source (§7), so
            # its payload is cached rather than thrown away after the chain.
            album_hits = itunes.search_albums(
              f"{album_artist} {chosen.album_name}".strip()
            )
            store.put_raw(isrc, "itunes", album_hits.raw)
            art = resolve_artwork(
              itunes, chosen.album_name, album_artist, chosen.track_name
            )
          except SourceError as exc:
            art = None
            emit(f"  itunes unavailable for {isrc}: {exc}", level=Level.WARN)

          if art is None:
            art_misses += 1
          else:
            art_hits += 1
            destination = art_dir / f"{isrc}.jpg"
            destination.write_bytes(art.data)
            store.put_artwork(
              isrc=isrc,
              source_release=art.source_release,
              url_template=art.url,
              width=art.width,
              sha256=art.sha256,
              local_path=str(destination),
            )

          if discogs is not None:
            try:
              release_id, raw_search = discogs.search_release_id(
                album_artist, chosen.album_name
              )
              if release_id is not None:
                _, raw_release = discogs.release(release_id)
                store.put_raw(isrc, "discogs", raw_release)
            except SourceError as exc:
              emit(f"  discogs unavailable for {isrc}: {exc}", level=Level.WARN)

        fetched += 1
        credited = "credit" if recording else "no-credit"
        emit(
          f"[{index}/{len(rows)}] {isrc} — "
          f"{len(result.candidates)} releases, {credited}"
        )
    finally:
      spotify.close()
      musicbrainz.close()
      itunes.close()
      if discogs is not None:
        discogs.close()

    emit(f"resolved {fetched} fetched, {cached} already cached")
    emit(f"musicbrainz {mb_hits} found, {mb_misses} missing, {mb_errors} unavailable")
    emit(f"artwork {art_hits} verified, {art_misses} unverified (G5)")
  return 0


def _changes(current: Tags, proposed: Tags) -> list[tuple[str, str, str]]:
  """List the fields that would change.

  Args:
    current: what the file carries now.
    proposed: what the resolver would write.

  Returns:
    Field, old value, new value — for fields that actually differ.
  """
  out = []
  for spec in fields(Tags):
    if spec.name in {"artwork", "artwork_mime"}:
      continue
    old = getattr(current, spec.name)
    new = getattr(proposed, spec.name)
    if new is not None and old != new:
      out.append((spec.name, str(old or ""), str(new)))
  return out


def cmd_diff(args: argparse.Namespace) -> int:
  """Show the proposed change set, old to new. Writes nothing.

  Args:
    args: parsed arguments.

  Returns:
    Process exit code.
  """
  with Store.open(args.sidecar) as store:
    shown = 0
    for probed in probe_tree(args.library):
      if args.limit and shown >= args.limit:
        break
      resolved = _resolved_for(store, probed)
      changes = _changes(read_tags(probed.path), resolved.tags)
      if not changes:
        continue
      shown += 1
      emit(probed.path.name)
      for field_name, old, new in changes:
        source = resolved.provenance.get(field_name, "?")
        emit(f"  {field_name:<16} {old!r} -> {new!r}  [{source}]")
      if resolved.flags:
        emit(f"  flags: {', '.join(resolved.flags)}", level=Level.WARN)
    emit(f"{shown} tracks would change")
  return 0


def cmd_apply(args: argparse.Namespace) -> int:
  """Write tagged copies to the output tree. The source is never touched.

  Args:
    args: parsed arguments.

  Returns:
    Process exit code.
  """
  args.out.mkdir(parents=True, exist_ok=True)
  with Store.open(args.sidecar) as store:
    written = 0
    entries = []
    for probed in probe_tree(args.library):
      if args.limit and written >= args.limit:
        break
      candidates = _candidates_for(store, probed)
      resolved = _resolved_for(store, probed)

      # §8's gates refuse to guess; each refusal becomes a queue entry rather
      # than a line in a log nobody reads (§14).
      store.resolve_review(probed.audio_md5)
      if resolved.flags:
        existing = read_tags(probed.path)
        for flag in resolved.flags:
          # show what the decision is actually between. for a credit
          # disagreement the two sides often share a TPE1 and differ only in
          # who is featured, so a bare artist field shows nothing to decide.
          alternative = resolved.alternatives.get(flag)
          if alternative is not None:
            proposed = render_credit_from_tags(resolved)
            current = alternative
          else:
            proposed = resolved.tags.artist or ""
            current = existing.artist or ""
          store.put_review(
            audio_md5=probed.audio_md5,
            flag=flag,
            file=probed.path.name,
            proposed=proposed,
            current=current,
            source=resolved.provenance.get("artist", ""),
          )

      # §9: emit a fully tagged copy, leave the source untouched.
      destination = args.out / probed.path.name
      shutil.copy2(probed.path, destination)
      write_tags(destination, resolved.tags)
      written += 1

      entries.append(
        library_map.merge(
          probed.audio_md5,
          _map_row(probed, resolved, choose_release(candidates)),
          library_map.read(args.map).get(probed.audio_md5, {}),
          store.get_generated(probed.audio_md5),
        )
      )
      emit(f"wrote {destination.name}")

    library_map.write(args.map, entries, store)
    emit(f"wrote {written} tagged copies to {args.out}")
    emit(f"wrote {args.map}")
    for flag, count in store.review_counts().items():
      emit(f"flagged {count} × {flag}")
  return 0


def cmd_map(args: argparse.Namespace) -> int:
  """Render the map for scanning (§9c). Read-only.

  Args:
    args: parsed arguments.

  Returns:
    Process exit code.
  """
  rows = library_map.read(args.map)
  if not rows:
    emit(f"no map at {args.map} — run `apply` first", level=Level.WARN)
    return 1

  shown = 0
  for md5, values in rows.items():
    if args.missing and values.get(args.missing):
      continue
    if args.no_isrc and values.get("isrc"):
      continue
    shown += 1
    emit(
      "\t".join(
        [
          md5,
          values.get("file", ""),
          values.get("isrc", ""),
          values.get("spotify", ""),
          values.get("itunes", ""),
          values.get("beatport", ""),
        ]
      )
    )
  emit(f"{shown} of {len(rows)} rows")
  return 0


def cmd_serve(args: argparse.Namespace) -> int:
  """Run the web ui (§14).

  Args:
    args: parsed arguments.

  Returns:
    Process exit code.
  """
  from music_metadata.web.app import serve

  emit(f"serving on http://{args.host}:{args.port}")
  serve(args.sidecar, host=args.host, port=args.port)
  return 0


def build_parser() -> argparse.ArgumentParser:
  """Build the argument parser.

  Returns:
    The configured parser.
  """
  parser = argparse.ArgumentParser(prog="music-metadata", description=__doc__)
  parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
  sub = parser.add_subparsers(dest="command", required=True)

  probe = sub.add_parser("probe", help="local tag survey, no network")
  probe.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
  probe.set_defaults(func=cmd_probe)

  resolve = sub.add_parser("resolve", help="resolve identities into the sidecar")
  resolve.add_argument("--limit", type=int, default=0)
  resolve.add_argument("--refetch", action="store_true", help="ignore the cache")
  resolve.set_defaults(func=cmd_resolve)

  diff = sub.add_parser("diff", help="proposed changes, old to new")
  diff.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
  diff.add_argument("--limit", type=int, default=0)
  diff.set_defaults(func=cmd_diff)

  apply_ = sub.add_parser("apply", help="write tagged copies")
  apply_.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
  apply_.add_argument("--out", type=Path, required=True)
  apply_.add_argument("--map", type=Path, default=Path("library.toml"))
  apply_.add_argument("--limit", type=int, default=0)
  apply_.set_defaults(func=cmd_apply)

  map_ = sub.add_parser("map", help="render the map for scanning")
  map_.add_argument("--map", type=Path, default=Path("library.toml"))
  map_.add_argument("--missing", help="only rows where this field is empty")
  map_.add_argument("--no-isrc", action="store_true", help="only rows with no ISRC")
  map_.set_defaults(func=cmd_map)

  serve_ = sub.add_parser("serve", help="run the web ui")
  serve_.add_argument("--host", default="127.0.0.1")
  serve_.add_argument("--port", type=int, default=8765)
  serve_.set_defaults(func=cmd_serve)

  return parser


def main(argv: list[str] | None = None) -> int:
  """Entry point.

  Args:
    argv: arguments, defaulting to `sys.argv[1:]`.

  Returns:
    Process exit code.
  """
  args = build_parser().parse_args(argv)
  result: int = args.func(args)
  return result


if __name__ == "__main__":
  sys.exit(main())
