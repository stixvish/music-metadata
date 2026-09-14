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


def test_an_empty_queue_says_so(client):
  assert "nothing flagged" in client.get("/review").text


def test_a_flagged_track_appears(client):
  client.store.put_review(
    "abc",
    "credit-disagreement",
    "Calvin Harris - Sweet Nothing.aiff",
    proposed="Calvin Harris ft. Florence Welch",
    source="musicbrainz",
  )

  body = client.get("/review").text

  assert "Calvin Harris - Sweet Nothing.aiff" in body
  assert "Florence Welch" in body


def test_flags_are_grouped_by_the_gate_that_raised_them(client):
  """§14: the flags are valuable in a queue, grouped by gate."""
  client.store.put_review("a", "credit-disagreement", "one.aiff")
  client.store.put_review("b", "no-artwork", "two.aiff")

  body = client.get("/review").text

  assert "G6" in body
  assert "G5" in body


def test_the_gate_heading_explains_what_the_flag_means(client):
  client.store.put_review("a", "credit-disagreement", "one.aiff")

  assert "musicbrainz and the filename disagree" in client.get("/review").text


def test_accepting_a_row_clears_it_from_the_queue(client):
  client.store.put_review("abc", "credit-disagreement", "one.aiff")

  response = client.post("/review/abc/accept")

  assert response.status_code == 200
  assert "accepted" in response.text
  assert "nothing flagged" in client.get("/review").text


def test_accept_returns_a_row_fragment_not_a_page(client):
  """htmx swaps this into the existing table."""
  client.store.put_review("abc", "credit-disagreement", "one.aiff")

  body = client.post("/review/abc/accept").text

  assert body.strip().startswith("<tr")
  assert "<html" not in body.lower()


def test_the_same_flag_twice_does_not_duplicate_the_row(client):
  client.store.put_review("abc", "credit-disagreement", "one.aiff", proposed="A")
  client.store.put_review("abc", "credit-disagreement", "one.aiff", proposed="B")

  assert client.store.review_counts() == {"credit-disagreement": 1}
  assert "B" in client.get("/review").text


def test_counts_are_reported_per_gate(client):
  client.store.put_review("a", "credit-disagreement", "one.aiff")
  client.store.put_review("b", "credit-disagreement", "two.aiff")
  client.store.put_review("c", "no-artwork", "three.aiff")

  assert client.store.review_counts() == {"credit-disagreement": 2, "no-artwork": 1}


def test_a_track_can_be_flagged_by_two_different_gates(client):
  client.store.put_review("a", "credit-disagreement", "one.aiff")
  client.store.put_review("a", "no-artwork", "one.aiff")

  assert sum(client.store.review_counts().values()) == 2


def test_clearing_one_flag_leaves_the_other(client):
  client.store.put_review("a", "credit-disagreement", "one.aiff")
  client.store.put_review("a", "no-artwork", "one.aiff")

  client.store.resolve_review("a", "credit-disagreement")

  assert client.store.review_counts() == {"no-artwork": 1}
