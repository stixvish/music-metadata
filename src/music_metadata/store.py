"""the sidecar cache — sqlite, shared by the CLI and the web ui (SPEC.md §9a).

this is a permanent store keyed by identity, not a scratch file. §4 promises
that improving the resolver re-tags the library for free, and that is only true
if a re-run costs no API calls.

it stores **raw responses**, not just parsed fields. every finding in §3 that
changed the parsing would otherwise have forced a full re-fetch; with the raw
payloads a resolver fix is replayed offline.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

# bump when the parsing logic changes. rows below this are recomputed from
# their stored raw payloads; only rows with no raw payload are re-fetched.
SOURCE_VERSION = 1

# raw payloads are arbitrary JSON, but "arbitrary JSON" is a type, not `Any`.
type JsonValue = (
  str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

# the services whose raw payloads this schema has a column for. a typo would
# otherwise be swallowed by sqlite as an unknown column at write time.
_RAW_COLUMNS = {
  "spotify": "raw_spotify",
  "musicbrainz": "raw_musicbrainz",
  "work": "raw_work",
  "beatport": "raw_beatport",
  "itunes": "raw_itunes",
  "discogs": "raw_discogs",
}

_SCHEMA = Path(__file__).with_name("schema.sql")

# columns added to existing tables after the first release. `CREATE TABLE IF
# NOT EXISTS` silently does nothing to a table that already exists, so a
# sidecar created before a column was added keeps the old shape and every read
# of the new column raises. this list is the migration.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
  ("artwork", "candidate", "TEXT"),
  ("review", "current", "TEXT"),
)


# tables this schema used to create and no longer does. `service_ids` recorded
# how each service link was matched, but nothing ever wrote to it: the only
# search-derived link we actually produce is beatport's, and its `Match` already
# carries `matched_by` inline. dropping is safe **because it was never written
# to** — a table holding real rows would need a migration, not a DROP.
# `map_generated` recorded what the resolver last wrote, so a single file could
# tell a hand-edit from its own output. §9b now keeps the two in separate files,
# which decides it by *which file a value is in* — no history required, and no
# way for an algorithm change to fake an edit.
_DROPPED_TABLES: tuple[str, ...] = ("service_ids", "map_generated")


def _migrate(conn: sqlite3.Connection) -> None:
  """Bring an existing database up to the current schema.

  Args:
    conn: the open connection.
  """
  for table, column, kind in _ADDED_COLUMNS:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if existing and column not in existing:
      conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")  # noqa: S608 — names are literals above
  for table in _DROPPED_TABLES:
    # a fresh database never had it; only an older one needs the drop.
    present = conn.execute(
      "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if present is None:
      continue
    rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 — names are literals above
    # **never drop a table that holds rows.** it was retired because nothing
    # wrote to it; if something did, that is a migration, not a deletion.
    if rows is not None and rows[0] == 0:
      conn.execute(f"DROP TABLE {table}")  # noqa: S608 — names are literals above
  conn.commit()


class Store:
  """the sidecar database."""

  def __init__(self, conn: sqlite3.Connection) -> None:
    """Wrap an open connection.

    Args:
      conn: a connection whose row factory yields mappings.
    """
    self.conn = conn
    # fastapi runs sync route handlers in a threadpool, so the connection is
    # touched from more than one thread. sqlite allows that only with
    # check_same_thread=False, and only one statement at a time — hence the lock.
    self._lock = threading.Lock()

  @classmethod
  @contextmanager
  def open(cls, path: Path | str) -> Iterator[Store]:
    """Open the sidecar at `path`, creating it if needed.

    Args:
      path: the sqlite file. Parent directories are created.

    Yields:
      An open store, closed on exit.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # foreign keys are off by default in sqlite and silently ignore violations.
    conn.execute("PRAGMA foreign_keys = ON")
    # **WAL, so the ui can be browsed while a resolve is writing.** the default
    # `delete` journal gives a writer an exclusive lock and readers get
    # SQLITE_BUSY — which would mean the library screen throwing errors for the
    # hours a full run takes. §14 makes the ui the primary interface; it cannot
    # be unusable exactly when there is something to watch.
    conn.execute("PRAGMA journal_mode = WAL")
    try:
      conn.executescript(_SCHEMA.read_text())
      _migrate(conn)
      yield cls(conn)
    finally:
      # no trailing commit: every write below commits as it goes, so a commit
      # here has no transaction to close and raises when a background job
      # (web/jobs.py) is still writing as the context exits.
      conn.close()

  # --- raw access ------------------------------------------------------------

  def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
    """Run a statement and commit it.

    Args:
      sql: the statement.
      params: bound parameters.
    """
    with self._lock:
      self.conn.execute(sql, params)
      self.conn.commit()

  def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    """Run a query.

    Args:
      sql: the query.
      params: bound parameters.

    Returns:
      Every matching row.
    """
    with self._lock:
      return self.conn.execute(sql, params).fetchall()

  # --- files -----------------------------------------------------------------

  def put_file(
    self,
    path: str,
    audio_md5: str,
    duration_s: float,
    isrc: str | None = None,
    mtime: float | None = None,
  ) -> None:
    """Record one file on disk, replacing any earlier row for the same path.

    Args:
      path: the file's path. This is the file's identity.
      audio_md5: md5 of the decoded audio (F44), not of the container.
      duration_s: duration in seconds.
      isrc: the ISRC carried in the file's own tag, if any.
      mtime: the file's modification time.
    """
    self.execute(
      """INSERT INTO files (path, audio_md5, duration_s, isrc_from_tag, mtime)
         VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(path) DO UPDATE SET
           audio_md5     = excluded.audio_md5,
           duration_s    = excluded.duration_s,
           isrc_from_tag = excluded.isrc_from_tag,
           mtime         = excluded.mtime""",
      (path, audio_md5, duration_s, isrc, mtime),
    )

  def files_by_isrc(self, isrc: str) -> list[sqlite3.Row]:
    """Return every file carrying this ISRC.

    More than one is normal and is what §11a classes B and C describe.

    Args:
      isrc: the ISRC to look up.

    Returns:
      Matching file rows.
    """
    return self.query("SELECT * FROM files WHERE isrc_from_tag = ?", (isrc,))

  def files_by_md5(self, audio_md5: str) -> list[sqlite3.Row]:
    """Return every file with this decoded-audio md5.

    More than one means a §11a class A duplicate.

    Args:
      audio_md5: the md5 to look up.

    Returns:
      Matching file rows.
    """
    return self.query("SELECT * FROM files WHERE audio_md5 = ?", (audio_md5,))

  # --- recordings ------------------------------------------------------------

  def put_raw(self, isrc: str, service: str, payload: JsonValue) -> None:
    """Store one service's raw response for a recording.

    Args:
      isrc: the recording's ISRC.
      service: one of the services this schema has a column for.
      payload: the decoded JSON response, stored verbatim.

    Raises:
      ValueError: if `service` has no raw column.
    """
    column = _RAW_COLUMNS.get(service)
    if column is None:
      msg = f"unknown service {service!r}; expected one of {sorted(_RAW_COLUMNS)}"
      raise ValueError(msg)
    self.execute(
      f"""INSERT INTO recordings (isrc, source_version, {column})
          VALUES (?, ?, ?)
          ON CONFLICT(isrc) DO UPDATE SET
            {column}       = excluded.{column},
            source_version = excluded.source_version,
            fetched_at     = datetime('now')""",  # noqa: S608 — column is from _RAW_COLUMNS, never user input
      (isrc, SOURCE_VERSION, json.dumps(payload)),
    )

  def get_raw(self, isrc: str, service: str) -> JsonValue:
    """Return a stored raw response, or None if it was never fetched.

    Args:
      isrc: the recording's ISRC.
      service: one of the services this schema has a column for.

    Returns:
      The decoded payload, or None.

    Raises:
      ValueError: if `service` has no raw column.
    """
    column = _RAW_COLUMNS.get(service)
    if column is None:
      msg = f"unknown service {service!r}; expected one of {sorted(_RAW_COLUMNS)}"
      raise ValueError(msg)
    rows = self.query(
      f"SELECT {column} AS payload FROM recordings WHERE isrc = ?",  # noqa: S608 — column is from _RAW_COLUMNS
      (isrc,),
    )
    if not rows or rows[0]["payload"] is None:
      return None
    # json.loads is typed as returning Any; JsonValue is what it actually is.
    return cast("JsonValue", json.loads(rows[0]["payload"]))

  def isrcs_below_source_version(self) -> list[str]:
    """Return recordings parsed by an older resolver, oldest first.

    These are recomputed from their stored raw payloads rather than re-fetched.

    Returns:
      The ISRCs needing recomputation.
    """
    rows = self.query(
      "SELECT isrc FROM recordings WHERE source_version < ? ORDER BY isrc",
      (SOURCE_VERSION,),
    )
    return [r["isrc"] for r in rows]

  # --- service ids, artwork, fingerprints ------------------------------------

  def put_artwork(
    self,
    isrc: str,
    source_release: str | None,
    candidate: str | None,
    url_template: str | None,
    width: int | None,
    sha256: str | None,
    local_path: str | None,
  ) -> None:
    """Record the artwork chosen for a recording and where it came from.

    Args:
      isrc: the recording's ISRC.
      source_release: the release §7c verified the artwork against.
      candidate: which step of §7c's chain verified it, for G5's per-tier count.
      url_template: the URL with the size segment left substitutable.
      width: the pixel width actually fetched.
      sha256: hash of the fetched bytes.
      local_path: where the bytes were written.
    """
    self.execute(
      """INSERT INTO artwork
           (isrc, source_release, candidate, url_template, width, sha256, local_path)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(isrc) DO UPDATE SET
           source_release = excluded.source_release,
           candidate      = excluded.candidate,
           url_template   = excluded.url_template,
           width          = excluded.width,
           sha256         = excluded.sha256,
           local_path     = excluded.local_path""",
      (isrc, source_release, candidate, url_template, width, sha256, local_path),
    )

  def put_fingerprint(self, isrc: str, chromaprint: str, duration_s: float) -> None:
    """Store a chromaprint fingerprint for a recording (§15).

    Args:
      isrc: the recording's ISRC.
      chromaprint: the fingerprint as fpcalc returned it.
      duration_s: the duration fpcalc measured.
    """
    self.execute(
      """INSERT INTO fingerprints (isrc, chromaprint, duration_s)
         VALUES (?, ?, ?)
         ON CONFLICT(isrc) DO UPDATE SET
           chromaprint = excluded.chromaprint,
           duration_s  = excluded.duration_s""",
      (isrc, chromaprint, duration_s),
    )

  # --- library.toml provenance (§9b) -----------------------------------------

  # --- the review queue (§14) ------------------------------------------------

  def put_review(
    self,
    audio_md5: str,
    flag: str,
    file: str,
    proposed: str = "",
    current: str = "",
    source: str = "",
  ) -> None:
    """Queue a flagged track for review.

    Args:
      audio_md5: the track's decoded-audio md5.
      flag: the gate that raised it.
      file: the file's name, for the operator to recognise.
      proposed: the value the resolver would write.
      current: the value it would replace. §14 puts the two side by side,
        because a disagreement is not decidable from one of them alone.
      source: which source proposed it.
    """
    self.execute(
      """INSERT INTO review (audio_md5, flag, file, proposed, current, source)
         VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(audio_md5, flag) DO UPDATE SET
           file     = excluded.file,
           proposed = excluded.proposed,
           current  = excluded.current,
           source   = excluded.source""",
      (audio_md5, flag, file, proposed, current, source),
    )

  def resolve_review(self, audio_md5: str, flag: str | None = None) -> None:
    """Clear a track from the review queue.

    Args:
      audio_md5: the track's decoded-audio md5.
      flag: clear only this flag, or every flag on the track when omitted.
    """
    if flag is None:
      self.execute("DELETE FROM review WHERE audio_md5 = ?", (audio_md5,))
    else:
      self.execute(
        "DELETE FROM review WHERE audio_md5 = ? AND flag = ?", (audio_md5, flag)
      )

  def artwork_by_candidate(self) -> dict[str, int]:
    """Return how many covers each step of §7c's chain supplied.

    G5 requires this per-tier count rather than a single total: F37 replaced one
    candidate outright, and knowing which tier is carrying the load is what
    makes a future change to the chain decidable.

    Returns:
      Candidate name to count.
    """
    rows = self.query(
      "SELECT candidate, COUNT(*) AS n FROM artwork "
      "WHERE candidate IS NOT NULL GROUP BY candidate ORDER BY n DESC"
    )
    return {r["candidate"]: int(r["n"]) for r in rows}

  def review_counts(self) -> dict[str, int]:
    """Return how many tracks each gate has flagged.

    Returns:
      Flag to count, which is what `verify` reports rather than assumes.
    """
    rows = self.query(
      "SELECT flag, COUNT(*) AS n FROM review GROUP BY flag ORDER BY flag"
    )
    return {r["flag"]: int(r["n"]) for r in rows}

  # --- the proposed change set (§14) -----------------------------------------

  def put_proposed(
    self,
    audio_md5: str,
    file: str,
    field: str,
    old_value: str,
    new_value: str,
    source: str,
  ) -> None:
    """Record one proposed field change, for the diff screen.

    Args:
      audio_md5: the track's decoded-audio md5.
      file: the file's name.
      field: the tag field.
      old_value: what the file carries now.
      new_value: what the resolver would write.
      source: which source supplied it.
    """
    self.execute(
      """INSERT INTO proposed (audio_md5, file, field, old_value, new_value, source)
         VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(audio_md5, field) DO UPDATE SET
           file      = excluded.file,
           old_value = excluded.old_value,
           new_value = excluded.new_value,
           source    = excluded.source""",
      (audio_md5, file, field, old_value, new_value, source),
    )

  def clear_proposed(self) -> None:
    """Drop the previous change set before recording a new one."""
    self.execute("DELETE FROM proposed")

  # --- jobs ------------------------------------------------------------------

  def create_job(self, kind: str) -> int:
    """Start a background job and return its id.

    Args:
      kind: what the job does, such as "resolve" or "acquire".

    Returns:
      The new job's id.
    """
    with self._lock:
      cur = self.conn.execute("INSERT INTO jobs (kind) VALUES (?)", (kind,))
      self.conn.commit()
      return int(cur.lastrowid or 0)

  def update_job(
    self,
    job_id: int,
    state: str | None = None,
    progress: float | None = None,
    error: str | None = None,
  ) -> None:
    """Update a job's progress. Only the arguments given are changed.

    Args:
      job_id: the job to update.
      state: the new state, such as "running", "done" or "failed".
      progress: fraction complete, 0.0 to 1.0.
      error: the failure message, when the job failed.
    """
    # COALESCE keeps this one static statement instead of assembling SET
    # clauses, so there is no dynamic SQL here at all.
    self.execute(
      """UPDATE jobs SET
           state    = COALESCE(?, state),
           progress = COALESCE(?, progress),
           error    = COALESCE(?, error)
         WHERE id = ?""",
      (state, progress, error, job_id),
    )

  def get_job(self, job_id: int) -> sqlite3.Row | None:
    """Return one job's current row.

    Args:
      job_id: the job to fetch.

    Returns:
      The job row, or None if there is no such job.
    """
    rows = self.query("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return rows[0] if rows else None
