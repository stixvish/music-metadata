"""the web ui — fastapi + jinja2 + htmx (SPEC.md §14).

this is the primary interface, not a wrapper over the CLI. both are front doors
to the same sqlite store (§9a); neither is authoritative.

local-first: binds localhost, no auth, no multi-user. it reads and writes the
operator's own library on the operator's own machine.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from music_metadata import library_map
from music_metadata.config import get, load_env
from music_metadata.isrc_recovery import Recovery, Status, recover
from music_metadata.release import choose_release
from music_metadata.sources.musicfetch import Musicfetch
from music_metadata.sources.spotify import candidates_from_raw
from music_metadata.store import Store
from music_metadata.web import jobs

_HERE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))

# the screens §14 specifies. library is built; the rest are stubs until the
# data that justifies them exists — a review queue with nothing to review is
# not worth building twice.
_PLACEHOLDERS = {
  "acquire": "tier 0 acquisition lands after the library is tagged (M6).",
}

# how each flag reads as a heading in the queue. §14: the flags are worthless in
# a log file and valuable in a queue, grouped by the gate that raised them.
_GATE_LABELS = {
  "credit-disagreement": "G6 · musicbrainz and the filename disagree on the credit",
  "no-artwork": "G5 · no verified artwork",
  "no-release": "no release found",
  "no-isrc": "G10 · no ISRC",
}


def create_app(store: Store, map_path: Path = Path("library.toml")) -> FastAPI:
  """Build the app around an already-open store.

  Taking the store rather than a path keeps the tests and the CLI on one
  connection and makes the app trivially constructible in a fixture.

  Args:
    store: the sidecar cache backing every screen.
    map_path: `library.toml` (§9b), which the ISRC screen writes to. The same
      file the CLI uses, so an edit made in the browser is an edit the next
      `resolve` picks up.

  Returns:
    The configured application.
  """
  app = FastAPI(title="music-metadata")
  app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

  def _overrides() -> dict[str, dict[str, str]]:
    """Read the map's hand-edited values.

    Returns:
      md5 to asserted fields; empty when no map exists yet.
    """
    return library_map.read(map_path) if map_path.is_file() else {}

  def make_musicfetch() -> Musicfetch | None:
    """Build a musicfetch client, or None when no token is configured.

    §5's rule applied here: a missing credential disables a feature, it does
    not break the app. The screen says what is missing instead.

    Returns:
      The client, or None.
    """
    load_env()
    token = get("MUSICMATCH_TOKEN")
    return Musicfetch(token) if token else None

  def write_isrc(md5: str, isrc: str) -> bool:
    """Record a recovered ISRC in the map.

    Args:
      md5: the file's audio hash.
      isrc: the verified ISRC.

    Returns:
      Whether the map changed.
    """
    return library_map.set_isrc(map_path, md5, isrc)

  @app.get("/", response_class=HTMLResponse)
  def library(
    request: Request, q: str = "", state: str = "all", sort: str = "file"
  ) -> HTMLResponse:
    """§14 screen 1: every track, filterable and sortable by resolution state."""
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="library.html",
      context=_library_context(store, q, state, sort) | {"current": "/"},
    )

  @app.get("/rows", response_class=HTMLResponse)
  def rows(
    request: Request, q: str = "", state: str = "all", sort: str = "file"
  ) -> HTMLResponse:
    """Just the table, for htmx to swap in — no full-page reload to filter."""
    return _TEMPLATES.TemplateResponse(
      request=request, name="rows.html", context=_library_context(store, q, state, sort)
    )

  def _no_isrc_rows() -> list[dict[str, object]]:
    """The files still missing an ISRC, with any hand-edit already applied.

    A file whose ISRC was filled in on an earlier visit drops off the list —
    the map is the source of truth for what is still outstanding, not the tag.

    Returns:
      One row per outstanding file.
    """
    overrides = _overrides()
    rows = []
    for row in store.query(
      "SELECT audio_md5, path, duration_s FROM files "
      "WHERE isrc_from_tag IS NULL ORDER BY path"
    ):
      md5 = row["audio_md5"]
      if (overrides.get(md5, {}).get("isrc") or "").strip():
        continue
      seconds = int(row["duration_s"] or 0)
      rows.append(
        {
          "md5": md5,
          "file": Path(row["path"]).name,
          "duration_s": row["duration_s"],
          "length": f"{seconds // 60}:{seconds % 60:02d}",
          "result": None,
          "url": "",
        }
      )
    return rows

  @app.get("/isrc", response_class=HTMLResponse)
  def isrc(request: Request) -> HTMLResponse:
    """§14: fill in the ISRCs the tags never carried, from youtube links."""
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="isrc.html",
      context={"rows": _no_isrc_rows(), "current": "/isrc"},
    )

  @app.post("/isrc/{md5}", response_class=HTMLResponse)
  def isrc_lookup(request: Request, md5: str, url: str = Form(...)) -> HTMLResponse:
    """Resolve one pasted link and, if it verifies, write it to the map."""
    rows = store.query(
      "SELECT audio_md5, path, duration_s FROM files WHERE audio_md5 = ?", (md5,)
    )
    if not rows:
      raise HTTPException(status_code=404, detail="no such file")
    file = rows[0]
    seconds = int(file["duration_s"] or 0)

    url = url.strip()
    if not url:
      result = Recovery(status=Status.NOT_FOUND, note="paste a link first.")
    else:
      client = make_musicfetch()
      if client is None:
        result = Recovery(
          status=Status.ERROR,
          note="MUSICMATCH_TOKEN is not set; add it to .env (see .env.example).",
        )
      else:
        try:
          result = recover(url, client, file["duration_s"])
        finally:
          client.close()

    if result.usable and result.isrc:
      write_isrc(md5, result.isrc)

    row = {
      "md5": md5,
      "file": Path(file["path"]).name,
      "duration_s": file["duration_s"],
      "length": f"{seconds // 60}:{seconds % 60:02d}",
      "result": result,
      "url": "" if result.usable else url,
    }
    return _TEMPLATES.TemplateResponse(
      request=request, name="isrc_row.html", context={"row": row}
    )

  @app.get("/review", response_class=HTMLResponse)
  def review(request: Request) -> HTMLResponse:
    """The flagged tracks, grouped by the gate that raised them.

    §14: this is the screen that justifies the ui. the gates in §8 deliberately
    refuse to guess, and those refusals are decisions someone has to make.
    """
    groups: dict[str, list[dict[str, str]]] = {}
    for row in store.query("SELECT * FROM review ORDER BY flag, file"):
      label = _GATE_LABELS.get(row["flag"], row["flag"])
      groups.setdefault(label, []).append(
        {
          "md5": row["audio_md5"],
          "file": row["file"],
          "proposed": row["proposed"] or "",
          "current": row["current"] or "",
          "source": row["source"] or "",
        }
      )
    total = sum(len(rows) for rows in groups.values())
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="review.html",
      context={"groups": groups, "total": total, "current": "/review"},
    )

  @app.post("/review/{md5}/accept", response_class=HTMLResponse)
  def accept(request: Request, md5: str) -> HTMLResponse:
    """Accept a flagged value and clear it from the queue."""
    store.resolve_review(md5)
    return _TEMPLATES.TemplateResponse(request=request, name="accepted.html")

  @app.get("/diff", response_class=HTMLResponse)
  def diff(request: Request) -> HTMLResponse:
    """The proposed change set, reviewable before anything is written (§14)."""
    rows = [
      {
        "file": r["file"],
        "field": r["field"],
        "old": r["old_value"] or "",
        "new": r["new_value"] or "",
        "source": r["source"] or "",
      }
      for r in store.query("SELECT * FROM proposed ORDER BY file, field")
    ]
    tracks = len({r["file"] for r in rows})
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="diff.html",
      context={"rows": rows, "total": tracks, "current": "/diff"},
    )

  @app.post("/apply", response_class=HTMLResponse)
  def apply(request: Request, confirm: str = Form(default="")) -> HTMLResponse:
    """Applying is gated behind an explicit confirmation (§14).

    The ui does not write files itself — it records the intent, and `apply` on
    the CLI is what touches disk. one code path writes tags, not two.
    """
    if confirm != "yes":
      return _TEMPLATES.TemplateResponse(
        request=request,
        name="applied.html",
        context={"message": "not confirmed — nothing written", "error": True},
      )
    store.create_job("apply")
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="applied.html",
      context={
        "message": "confirmed. run `music-metadata apply --out DIR` to write.",
        "error": False,
      },
    )

  @app.get("/{screen}", response_class=HTMLResponse)
  def placeholder(request: Request, screen: str) -> HTMLResponse:
    note = _PLACEHOLDERS.get(screen)
    if note is None:
      raise HTTPException(status_code=404, detail=f"no screen {screen!r}")
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="placeholder.html",
      context={"screen": screen, "note": note, "current": f"/{screen}"},
    )

  @app.post("/resolve", response_class=HTMLResponse)
  def start_resolve(request: Request) -> HTMLResponse:
    """Kick off a resolve in the background and return its progress fragment.

    §14: a 72-minute resolve cannot block an http request, so this returns
    immediately with the fragment htmx will poll.
    """
    job_id = jobs.start(store, "resolve", _resolve_body(store))
    row = store.get_job(job_id)
    return _TEMPLATES.TemplateResponse(
      request=request, name="job.html", context={"job": row, "finished": False}
    )

  @app.get("/jobs/{job_id}", response_class=HTMLResponse)
  def job(request: Request, job_id: int) -> HTMLResponse:
    row = store.get_job(job_id)
    if row is None:
      raise HTTPException(status_code=404, detail=f"no job {job_id}")
    # a finished job drops its hx-trigger, which is how htmx knows to stop
    # polling. §14: a 72-minute resolve cannot hold an http request open.
    finished = row["state"] in {"done", "failed"}
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="job.html",
      context={"job": row, "finished": finished},
    )

  return app


# how many rows the table renders at once. 1,494 <tr> elements is slow to
# parse and impossible to scan; the filter is the way to reach the rest.
_PAGE = 300

_STATES = (
  ("all", "all"),
  ("resolved", "resolved"),
  ("flagged", "flagged"),
  ("unresolved", "unresolved"),
  ("no-isrc", "no ISRC"),
)

_COLUMNS = (
  ("file", "file"),
  ("artist", "artist"),
  ("album", "album"),
  ("isrc", "ISRC"),
  ("state", "state"),
  ("duration", "length"),
)

_STATE_GLYPH = {"resolved": "●", "flagged": "▲", "none": "○"}


def _library_context(store: Store, q: str, state: str, sort: str) -> dict[str, object]:
  """Build the library table's rows, filtered and sorted.

  Filtering happens in SQL rather than in the template so a 1,494-row library
  never has to be materialised to show twenty matches.

  Args:
    store: the sidecar.
    q: free-text filter over file, artist, album and ISRC.
    state: one of `_STATES`.
    sort: one of `_COLUMNS`.

  Returns:
    The template context.
  """
  flagged = {
    r["audio_md5"] for r in store.query("SELECT DISTINCT audio_md5 FROM review")
  }
  resolved = {
    r["isrc"] for r in store.query("SELECT isrc FROM recordings WHERE isrc IS NOT NULL")
  }

  total = store.query("SELECT COUNT(*) AS n FROM files")[0]["n"]
  needle = f"%{q.lower()}%"
  rows = store.query(
    "SELECT * FROM files WHERE ? = '' OR lower(path) LIKE ? "
    "OR lower(COALESCE(isrc_from_tag, '')) LIKE ? ORDER BY path",
    (q, needle, needle),
  )

  out: list[dict[str, object]] = []
  for row in rows:
    isrc = row["isrc_from_tag"]
    if isrc is None:
      label, css = "no ISRC", "none"
    elif row["audio_md5"] in flagged:
      label, css = "flagged", "flagged"
    elif isrc in resolved:
      label, css = "resolved", "resolved"
    else:
      label, css = "unresolved", "none"

    if state != "all" and state != ("no-isrc" if isrc is None else label):
      continue

    name = Path(row["path"]).name
    artist, _, rest = name.rpartition(" - ")
    seconds = float(row["duration_s"])
    out.append(
      {
        "file": rest.removesuffix(".aiff") or name,
        "artist": artist,
        "album": "",
        "isrc": isrc or "",
        "state": label,
        "state_class": css,
        "glyph": _STATE_GLYPH.get(css, "○"),
        "duration": f"{int(seconds // 60)}:{int(seconds % 60):02d}",
      }
    )

  key = sort if sort in dict(_COLUMNS) else "file"
  out.sort(key=lambda r: str(r.get(key, "")).lower())

  # album comes from the cached spotify payload, and only for the rows actually
  # rendered — parsing 1,494 payloads to show 300 of them would make every
  # keystroke in the filter box cost a second.
  page = out[:_PAGE]
  for entry in page:
    entry_isrc = entry["isrc"]
    if not entry_isrc:
      continue
    cached = store.get_raw(str(entry_isrc), "spotify")
    chosen = choose_release(candidates_from_raw(cached))
    if chosen is not None:
      entry["album"] = chosen.album_name

  return {
    "rows": page,
    "shown": len(page),
    "total": total,
    "q": q,
    "state": state,
    "sort": key,
    "direction": "ascending",
    "states": _STATES,
    "columns": _COLUMNS,
  }


def _resolve_body(store: Store) -> Callable[[jobs.Progress], None]:
  """Build the resolve job's body.

  Kept out of the route so the route stays a thin adapter and the work is
  testable without an HTTP client.

  Args:
    store: the sidecar.

  Returns:
    A callable the job runner drives.
  """

  def work(progress: jobs.Progress) -> None:
    from music_metadata.config import load_env, require
    from music_metadata.sources.spotify import Spotify

    load_env()
    rows = store.query(
      "SELECT isrc_from_tag FROM files WHERE isrc_from_tag IS NOT NULL ORDER BY path"
    )
    spotify = Spotify(require("SPOTIFY_CLIENT_ID"), require("SPOTIFY_CLIENT_SECRET"))
    try:
      for index, row in enumerate(rows, start=1):
        isrc = row["isrc_from_tag"]
        if store.get_raw(isrc, "spotify") is None:
          store.put_raw(isrc, "spotify", spotify.search_isrc(isrc).raw)
        progress.update(index, len(rows))
    finally:
      spotify.close()

  return work


def serve(sidecar: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
  """Run the ui against a sidecar file until interrupted.

  Binds loopback by default: this reads and writes the operator's own library
  on the operator's own machine, and §14 puts anything else out of scope.

  Args:
    sidecar: path to the sqlite sidecar.
    host: interface to bind.
    port: port to bind.
  """
  import uvicorn

  with Store.open(sidecar) as store:
    uvicorn.run(create_app(store), host=host, port=port, log_level="warning")
