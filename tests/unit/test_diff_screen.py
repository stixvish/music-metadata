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


def seed(client):
  client.store.put_proposed(
    audio_md5="abc",
    file="*NSYNC - Bye Bye Bye.aiff",
    field="album",
    old_value="No Strings Attached (special UK edition)",
    new_value="No Strings Attached",
    source="spotify",
  )


def test_an_empty_change_set_says_so(client):
  assert "nothing to apply" in client.get("/diff").text


def test_a_proposed_change_shows_both_values(client):
  seed(client)

  body = client.get("/diff").text

  assert "special UK edition" in body
  assert "spotify" in body


def test_the_track_count_is_tracks_not_fields(client):
  seed(client)
  client.store.put_proposed(
    "abc", "*NSYNC - Bye Bye Bye.aiff", "date", "2000", "2000-01-17", "spotify"
  )

  assert "1 tracks would change" in client.get("/diff").text


def test_applying_without_confirming_writes_nothing(client):
  """§14: apply is gated behind an explicit confirmation."""
  seed(client)

  body = client.post("/apply", data={}).text

  assert "not confirmed" in body


def test_confirming_is_required_to_be_exact(client):
  seed(client)

  assert "not confirmed" in client.post("/apply", data={"confirm": "maybe"}).text


def test_a_confirmed_apply_is_acknowledged(client):
  seed(client)

  body = client.post("/apply", data={"confirm": "yes"}).text

  assert "not confirmed" not in body
  assert "apply" in body


def test_the_ui_does_not_write_files_itself(client):
  """one code path writes tags, not two — the ui records intent only."""
  seed(client)

  body = client.post("/apply", data={"confirm": "yes"}).text

  assert "music-metadata apply" in body


def test_a_confirmed_apply_records_a_job(client):
  seed(client)
  client.post("/apply", data={"confirm": "yes"})

  jobs = client.store.query("SELECT * FROM jobs WHERE kind = 'apply'")
  assert len(jobs) == 1


def test_the_change_set_is_cleared_between_runs(client):
  seed(client)
  client.store.clear_proposed()

  assert "nothing to apply" in client.get("/diff").text
