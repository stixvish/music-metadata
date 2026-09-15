import pytest
from fastapi.testclient import TestClient

from music_metadata.store import Store
from music_metadata.web.app import create_app


@pytest.fixture
def client(tmp_path):
  with (
    Store.open(tmp_path / "sidecar.sqlite") as store,
    TestClient(create_app(store)) as c,
  ):
    c.store = store
    yield c


def test_library_screen_renders(client):
  r = client.get("/")

  assert r.status_code == 200
  assert "library" in r.text.lower()


def test_library_screen_is_empty_before_a_probe(client):
  r = client.get("/")

  assert "no tracks yet" in r.text.lower()


def test_library_screen_lists_probed_files(client):
  client.store.put_file(
    path="*NSYNC - Bye Bye Bye.aiff",
    audio_md5="8ab13f549542ec73ee5d8da7c62dd6a4",
    duration_s=200.0,
    isrc="USJI10000001",
  )

  r = client.get("/")

  assert "Bye Bye Bye" in r.text
  assert "USJI10000001" in r.text


@pytest.mark.parametrize("route", ["/", "/review", "/acquire", "/diff"])
def test_all_four_screens_exist(client, route):
  """SPEC.md §14: library, review queue, acquire, diff/apply."""
  assert client.get(route).status_code == 200


def test_the_page_binds_htmx_not_a_build_step(client):
  """SPEC.md §14: htmx and alpine from a CDN, no node toolchain."""
  body = client.get("/").text

  assert "htmx" in body
  assert "<script" in body


def test_job_progress_is_polled_as_a_fragment(client):
  job_id = client.store.create_job("resolve")
  client.store.update_job(job_id, state="running", progress=0.25)

  r = client.get(f"/jobs/{job_id}")

  assert r.status_code == 200
  assert "25" in r.text
  # a fragment, not a whole page: htmx swaps this into an existing div.
  assert "<html" not in r.text.lower()


def test_polling_an_unknown_job_is_404(client):
  assert client.get("/jobs/9999").status_code == 404


def test_a_finished_job_stops_polling(client):
  """htmx keeps polling until the fragment stops asking to be re-fetched."""
  job_id = client.store.create_job("resolve")
  client.store.update_job(job_id, state="done", progress=1.0)

  r = client.get(f"/jobs/{job_id}")

  assert "hx-trigger" not in r.text


def test_a_running_job_keeps_polling(client):
  job_id = client.store.create_job("resolve")
  client.store.update_job(job_id, state="running", progress=0.5)

  r = client.get(f"/jobs/{job_id}")

  assert "hx-trigger" in r.text


def test_a_failed_job_shows_its_error(client):
  job_id = client.store.create_job("acquire")
  client.store.update_job(job_id, state="failed", error="cookies rotated mid-batch")

  r = client.get(f"/jobs/{job_id}")

  assert "cookies rotated mid-batch" in r.text


# --- the isrc screen -----------------------------------------------------------


def test_the_isrc_screen_lists_files_missing_one(client):
  client.store.put_file(
    path="/m/The Killers - Mr. Brightside.aiff",
    audio_md5="aaa",
    duration_s=222.0,
    isrc=None,
  )

  page = client.get("/isrc")

  assert page.status_code == 200
  assert "Mr. Brightside" in page.text


def test_a_file_that_already_has_an_isrc_is_not_listed(client):
  client.store.put_file(
    path="/m/*NSYNC - Bye Bye Bye.aiff",
    audio_md5="bbb",
    duration_s=200.0,
    isrc="USJI10000001",
  )

  assert "Bye Bye Bye" not in client.get("/isrc").text


def test_an_empty_url_is_reported_without_a_network_call(client):
  """the operator hit look-up on a blank box. that is a nudge, not a failure,
  and it must not reach musicfetch."""
  client.store.put_file(path="/m/x.aiff", audio_md5="ccc", duration_s=222.0, isrc=None)

  row = client.post("/isrc/ccc", data={"url": "  "})

  assert row.status_code == 200
  assert "paste a link first" in row.text
  assert "not written" in row.text


def test_a_lookup_for_an_unknown_file_is_a_404(client):
  assert client.post("/isrc/nope", data={"url": "https://x"}).status_code == 404
