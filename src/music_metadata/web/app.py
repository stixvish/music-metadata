"""the web ui — fastapi + jinja2 + htmx (SPEC.md §14).

this is the primary interface, not a wrapper over the CLI. both are front doors
to the same sqlite store (§9a); neither is authoritative.

local-first: binds localhost, no auth, no multi-user. it reads and writes the
operator's own library on the operator's own machine.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from music_metadata.store import Store
from music_metadata.web import jobs

_HERE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))

# the screens §14 specifies. library is built; the rest are stubs until the
# data that justifies them exists — a review queue with nothing to review is
# not worth building twice.
_PLACEHOLDERS = {
  "acquire": "tier 0 acquisition lands after the library is tagged (M6).",
  "diff": "diff and apply land with the tag writer (M1).",
}

# how each flag reads as a heading in the queue. §14: the flags are worthless in
# a log file and valuable in a queue, grouped by the gate that raised them.
_GATE_LABELS = {
  "credit-disagreement": "G6 · musicbrainz and the filename disagree on the credit",
  "no-artwork": "G5 · no verified artwork",
  "no-release": "no release found",
  "no-isrc": "G10 · no ISRC",
}


def create_app(store: Store) -> FastAPI:
  """Build the app around an already-open store.

  Taking the store rather than a path keeps the tests and the CLI on one
  connection and makes the app trivially constructible in a fixture.

  Args:
    store: the sidecar cache backing every screen.

  Returns:
    The configured application.
  """
  app = FastAPI(title="music-metadata")
  app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

  @app.get("/", response_class=HTMLResponse)
  def library(request: Request) -> HTMLResponse:
    files = store.query("SELECT * FROM files ORDER BY path")
    return _TEMPLATES.TemplateResponse(
      request=request, name="library.html", context={"files": files}
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
      context={"groups": groups, "total": total},
    )

  @app.post("/review/{md5}/accept", response_class=HTMLResponse)
  def accept(request: Request, md5: str) -> HTMLResponse:
    """Accept a flagged value and clear it from the queue."""
    store.resolve_review(md5)
    return _TEMPLATES.TemplateResponse(request=request, name="accepted.html")

  @app.get("/{screen}", response_class=HTMLResponse)
  def placeholder(request: Request, screen: str) -> HTMLResponse:
    note = _PLACEHOLDERS.get(screen)
    if note is None:
      raise HTTPException(status_code=404, detail=f"no screen {screen!r}")
    return _TEMPLATES.TemplateResponse(
      request=request,
      name="placeholder.html",
      context={"screen": screen, "note": note},
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
