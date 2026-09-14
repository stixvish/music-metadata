import threading
import time

import pytest

from music_metadata.store import Store
from music_metadata.web.jobs import start


@pytest.fixture
def store(tmp_path):
  with Store.open(tmp_path / "sidecar.sqlite") as s:
    yield s


def wait_for(store, job_id, states, timeout=5.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    row = store.get_job(job_id)
    if row is not None and row["state"] in states:
      return row
    time.sleep(0.01)
  pytest.fail(f"job {job_id} never reached {states}")


def test_a_job_row_exists_before_the_work_starts(store):
  """the browser polls immediately; it must not race a job that is not there."""
  gate = threading.Event()
  job_id = start(store, "resolve", lambda _p: gate.wait(2))

  assert store.get_job(job_id) is not None

  gate.set()
  # let the worker finish before the fixture closes the connection under it.
  wait_for(store, job_id, {"done", "failed"})


def test_a_job_reaches_done(store):
  job_id = start(store, "resolve", lambda _p: None)

  assert wait_for(store, job_id, {"done"})["progress"] == pytest.approx(1.0)


def test_progress_is_recorded_as_it_runs(store):
  seen = []

  def work(progress):
    for i in range(1, 5):
      progress.update(i, 4)
      seen.append(store.get_job(progress.job_id)["progress"])

  job_id = start(store, "resolve", work)
  wait_for(store, job_id, {"done"})

  assert seen == [0.25, 0.5, 0.75, 1.0]


def test_a_failing_job_records_the_error_rather_than_crashing(store):
  def work(_progress):
    msg = "cookies rotated mid-batch"
    raise RuntimeError(msg)

  job_id = start(store, "acquire", work)
  row = wait_for(store, job_id, {"failed"})

  assert "cookies rotated mid-batch" in row["error"]


def test_a_failure_leaves_the_row_behind_to_resume_from(store):
  """§10a: the queue is state, not a runtime list."""
  job_id = start(store, "acquire", lambda _p: (_ for _ in ()).throw(ValueError("x")))
  wait_for(store, job_id, {"failed"})

  assert store.get_job(job_id)["kind"] == "acquire"


def test_zero_total_does_not_divide_by_zero(store):
  job_id = start(store, "resolve", lambda p: p.update(0, 0))

  assert wait_for(store, job_id, {"done"}) is not None
