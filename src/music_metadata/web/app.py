"""the web ui — fastapi + jinja2 + htmx (SPEC.md §14).

this is the primary interface, not a wrapper over the CLI. both are front doors
to the same sqlite store (§9a); neither is authoritative.

local-first: binds localhost, no auth, no multi-user. it reads and writes the
operator's own library on the operator's own machine.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from music_metadata.store import Store

_HERE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))

# the screens §14 specifies. library is built; the rest are stubs until the
# data that justifies them exists — a review queue with nothing to review is
# not worth building twice.
_PLACEHOLDERS = {
  "review": "the review queue fills once the gates have something to flag (M2).",
  "acquire": "tier 0 acquisition lands after the library is tagged (M6).",
  "diff": "diff and apply land with the tag writer (M1).",
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
