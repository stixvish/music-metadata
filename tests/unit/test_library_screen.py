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
  client.store.put_file("Dua Lipa - Levitating.aiff", "m1", 203.0, "GBAHT2000123")
  client.store.put_file("*NSYNC - Bye Bye Bye.aiff", "m2", 200.4, "USJI10000001")
  client.store.put_file("A$AP Rocky - Problems.aiff", "m3", 190.0, None)
  client.store.put_raw("USJI10000001", "spotify", {"tracks": {"items": []}})
  client.store.put_review("m1", "credit-disagreement", "Dua Lipa - Levitating.aiff")


# --- §14: filterable ---------------------------------------------------------


def test_the_library_lists_every_track(client):
  seed(client)

  body = client.get("/").text

  assert "3 of 3 tracks" in body


def test_filtering_narrows_by_name(client):
  seed(client)

  body = client.get("/rows", params={"q": "levitating"}).text

  assert "Levitating" in body
  assert "Bye Bye Bye" not in body


def test_filtering_is_case_insensitive(client):
  seed(client)

  assert "Levitating" in client.get("/rows", params={"q": "LEVITATING"}).text


def test_filtering_matches_an_isrc(client):
  """the ISRC is the key everything hangs off; it has to be searchable."""
  seed(client)

  body = client.get("/rows", params={"q": "USJI10000001"}).text

  assert "Bye Bye Bye" in body
  assert "Levitating" not in body


def test_a_filter_matching_nothing_says_so(client):
  seed(client)

  assert "no tracks match that filter" in client.get("/rows", params={"q": "zzz"}).text


def test_an_empty_library_says_what_to_run(client):
  assert "music-metadata probe" in client.get("/").text


# --- §14: resolution state ---------------------------------------------------


def test_a_resolved_track_is_marked_resolved(client):
  seed(client)

  body = client.get("/rows", params={"state": "resolved"}).text

  assert "Bye Bye Bye" in body
  assert "Problems" not in body


def test_a_flagged_track_outranks_resolved(client):
  """a track with an open review flag is a decision, not a finished one."""
  seed(client)

  body = client.get("/rows", params={"state": "flagged"}).text

  assert "Levitating" in body


def test_a_track_with_no_isrc_has_its_own_state(client):
  seed(client)

  body = client.get("/rows", params={"state": "no-isrc"}).text

  assert "Problems" in body
  assert "Bye Bye Bye" not in body


def test_state_is_not_conveyed_by_colour_alone(client):
  """every state carries a glyph, so it survives greyscale and colour blindness."""
  seed(client)

  body = client.get("/rows").text

  assert 'aria-hidden="true"' in body
  assert any(g in body for g in ("●", "▲", "○"))


# --- §14: sortable -----------------------------------------------------------


def test_sorting_by_artist_reorders(client):
  seed(client)

  body = client.get("/rows", params={"sort": "artist"}).text

  assert body.index("*NSYNC") < body.index("Dua Lipa")


def test_an_unknown_sort_key_falls_back_rather_than_erroring(client):
  seed(client)

  assert client.get("/rows", params={"sort": "; DROP TABLE files"}).status_code == 200


def test_the_sorted_column_is_announced(client):
  seed(client)

  assert 'aria-sort="ascending"' in client.get("/rows", params={"sort": "file"}).text


# --- accessibility -----------------------------------------------------------


def test_there_is_a_skip_link(client):
  assert 'class="skip"' in client.get("/").text


def test_the_current_screen_is_marked_for_screen_readers(client):
  assert 'aria-current="page"' in client.get("/").text


def test_the_review_screen_marks_itself_current(client):
  body = client.get("/review").text

  assert 'href="/review"' in body
  assert 'aria-current="page"' in body


def test_table_headers_declare_scope(client):
  seed(client)

  assert 'scope="col"' in client.get("/rows").text


def test_the_row_count_is_a_live_region(client):
  seed(client)

  assert 'aria-live="polite"' in client.get("/rows").text


# --- not rendering 1,494 rows ------------------------------------------------


def test_the_table_is_capped(client):
  """1,494 <tr> is slow to parse and impossible to scan; the filter reaches
  the rest."""
  from music_metadata.web.app import _PAGE

  for i in range(_PAGE + 20):
    client.store.put_file(f"Artist - Track {i:04d}.aiff", f"m{i}", 200.0, f"X{i:011d}")

  body = client.get("/rows").text

  assert body.count("<tr>") - 1 == _PAGE
  assert "narrow the filter" in body
