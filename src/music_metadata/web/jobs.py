"""background execution for long operations (SPEC.md §14).

a full resolve is over an hour at 20 req/min (F8), which cannot be held open in
an HTTP request. the `jobs` table is the shared state: the worker writes
progress, the browser polls a fragment, and the CLI can read the same row.

the queue is **state, not a runtime list** — the same property §10a relies on so
an aborted acquisition loses nothing. a job that dies leaves its row behind with
the error on it, rather than vanishing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from music_metadata.output import Level, emit
from music_metadata.store import Store


class Progress:
  """the handle a job body uses to report how far along it is."""

  def __init__(self, store: Store, job_id: int) -> None:
    """Bind progress reporting to one job row.

    Args:
      store: the sidecar.
      job_id: the job to report against.
    """
    self.store = store
    self.job_id = job_id

  def update(self, done: int, total: int) -> None:
    """Record fractional progress.

    Args:
      done: units completed.
      total: units in total. Zero is treated as "unknown", not a crash.
    """
    fraction = (done / total) if total else 0.0
    self.store.update_job(self.job_id, progress=min(1.0, max(0.0, fraction)))


def start(store: Store, kind: str, work: Callable[[Progress], None]) -> int:
  """Run `work` on a background thread and return its job id.

  The job row is created before the thread starts, so the caller can poll
  immediately and never races a job that has not appeared yet.

  Args:
    store: the sidecar.
    kind: what the job does, such as "resolve".
    work: the body, which receives a `Progress` to report against.

  Returns:
    The new job's id.
  """
  job_id = store.create_job(kind)

  def run() -> None:
    store.update_job(job_id, state="running")
    try:
      work(Progress(store, job_id))
    except Exception as exc:  # noqa: BLE001 — a job must record any failure, not crash the server
      # §10a's principle: a failure leaves state behind to resume from.
      store.update_job(job_id, state="failed", error=f"{type(exc).__name__}: {exc}")
      emit(f"job {job_id} ({kind}) failed: {exc}", level=Level.ERROR)
      return
    store.update_job(job_id, state="done", progress=1.0)

  thread = threading.Thread(target=run, name=f"job-{job_id}-{kind}", daemon=True)
  thread.start()
  return job_id
