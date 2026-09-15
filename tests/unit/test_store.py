import json

import pytest

from music_metadata.store import SOURCE_VERSION, Store


@pytest.fixture
def store(tmp_path):
  with Store.open(tmp_path / "sidecar.sqlite") as s:
    yield s


def test_schema_creates_every_table_in_spec_9a(store):
  got = {
    r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type='table'")
  }
  assert {
    "files",
    "recordings",
    "service_ids",
    "fingerprints",
    "artwork",
    "jobs",
  } <= got


def test_two_files_may_share_an_isrc(store):
  """SPEC.md §11a classes B and C: same ISRC, different files, both kept.

  the measured library has 6 such ISRCs (cache/dupisrc.txt). a unique
  constraint here would refuse to ingest them, and §11a cannot classify a
  duplicate it never stored.
  """
  store.put_file(path="a.aiff", audio_md5="aaa", duration_s=180.0, isrc="USUM72009629")
  store.put_file(path="b.aiff", audio_md5="bbb", duration_s=240.0, isrc="USUM72009629")

  assert len(store.files_by_isrc("USUM72009629")) == 2


def test_two_files_may_share_an_audio_md5(store):
  """SPEC.md §11a class A: byte-identical audio at two paths, both kept.

  measured: 3 such md5s (cache/dupaudio.txt). class A is resolved by policy —
  keep one, quarantine the other — not by a constraint that blocks the insert.
  """
  store.put_file(path="x.aiff", audio_md5="dup", duration_s=200.0, isrc="A")
  store.put_file(path="x (2).aiff", audio_md5="dup", duration_s=200.0, isrc="B")

  assert len(store.files_by_md5("dup")) == 2


def test_path_is_the_file_identity(store):
  store.put_file(path="a.aiff", audio_md5="aaa", duration_s=180.0, isrc="X")
  store.put_file(path="a.aiff", audio_md5="zzz", duration_s=999.0, isrc="Y")

  rows = store.query("SELECT * FROM files")
  assert len(rows) == 1
  assert rows[0]["audio_md5"] == "zzz"


def test_raw_payloads_round_trip(store):
  """SPEC.md §9a: raw responses are stored, not just parsed fields."""
  payload = {"tracks": {"items": [{"id": "62bOmKYxYg7dhrC6gH9vFn"}]}}
  store.put_raw("USJI10000001", "spotify", payload)

  assert store.get_raw("USJI10000001", "spotify") == payload


def test_raw_payloads_are_stored_per_service(store):
  store.put_raw("USJI10000001", "spotify", {"a": 1})
  store.put_raw("USJI10000001", "musicbrainz", {"b": 2})

  assert store.get_raw("USJI10000001", "spotify") == {"a": 1}
  assert store.get_raw("USJI10000001", "musicbrainz") == {"b": 2}


def test_missing_raw_payload_is_none(store):
  assert store.get_raw("NOPE00000000", "spotify") is None


def test_recording_records_the_source_version(store):
  """SPEC.md §9a: source_version is what makes re-resolution safe."""
  store.put_raw("USJI10000001", "spotify", {"a": 1})

  row = store.query(
    "SELECT source_version FROM recordings WHERE isrc = ?", ("USJI10000001",)
  )
  assert row[0]["source_version"] == SOURCE_VERSION


def test_stale_recordings_are_findable(store):
  store.put_raw("OLD000000001", "spotify", {"a": 1})
  store.execute(
    "UPDATE recordings SET source_version = 0 WHERE isrc = ?", ("OLD000000001",)
  )
  store.put_raw("NEW000000001", "spotify", {"a": 1})

  assert store.isrcs_below_source_version() == ["OLD000000001"]


def test_job_progress_can_be_written_and_polled(store):
  """SPEC.md §14: a 72-minute resolve cannot block an http request."""
  job_id = store.create_job("resolve")

  assert store.get_job(job_id)["state"] == "pending"

  store.update_job(job_id, state="running", progress=0.5)
  job = store.get_job(job_id)
  assert job["state"] == "running"
  assert job["progress"] == pytest.approx(0.5)

  store.update_job(job_id, state="done", progress=1.0)
  assert store.get_job(job_id)["state"] == "done"


def test_job_records_an_error(store):
  job_id = store.create_job("acquire")
  store.update_job(job_id, state="failed", error="cookies rotated mid-batch")

  assert store.get_job(job_id)["error"] == "cookies rotated mid-batch"


def test_service_id_is_recorded_with_how_it_matched(store):
  store.put_service_id(
    isrc="GBARL2501127",
    service="beatport",
    service_id="20819013",
    url="https://beatport.com/track/blessings/20819013",
    matched_by="search",
    verified=True,
  )

  row = store.query("SELECT * FROM service_ids")[0]
  assert row["matched_by"] == "search"
  assert row["verified"] == 1


def test_artwork_row_records_provenance(store):
  store.put_artwork(
    isrc="USJI10000001",
    source_release="No Strings Attached",
    candidate="itunes-album-search",
    url_template="https://.../{w}x{w}bb.jpg",
    width=3000,
    sha256="deadbeef",
    local_path="artwork/USJI10000001.jpg",
  )

  row = store.query("SELECT * FROM artwork")[0]
  assert row["source_release"] == "No Strings Attached"
  assert row["candidate"] == "itunes-album-search"
  assert row["width"] == 3000


def test_fingerprint_round_trips(store):
  store.put_fingerprint(isrc="USJI10000001", chromaprint="AQADtMk...", duration_s=200.0)

  row = store.query("SELECT * FROM fingerprints")[0]
  assert row["chromaprint"] == "AQADtMk..."


def test_reopening_keeps_the_data(tmp_path):
  path = tmp_path / "sidecar.sqlite"
  with Store.open(path) as s:
    s.put_raw("USJI10000001", "spotify", {"a": 1})
  with Store.open(path) as s:
    assert s.get_raw("USJI10000001", "spotify") == {"a": 1}


def test_raw_payload_is_stored_as_json_text(store):
  store.put_raw("USJI10000001", "spotify", {"a": 1})

  raw = store.query("SELECT raw_spotify FROM recordings")[0]["raw_spotify"]
  assert json.loads(raw) == {"a": 1}


def test_unknown_service_is_rejected(store):
  with pytest.raises(ValueError, match="unknown service"):
    store.put_raw("USJI10000001", "napster", {"a": 1})


def test_artwork_counts_per_candidate_tier(store):
  """G5: `verify` reports the count **per candidate tier**, not one total.

  F37 replaced a candidate outright; knowing which tier carries the load is
  what makes a future change to the chain decidable.
  """
  for isrc, candidate in [
    ("A", "itunes-album-search"),
    ("B", "itunes-album-search"),
    ("C", "itunes-song-search"),
  ]:
    store.put_artwork(isrc, "Album", candidate, "url", 3000, "sha", "path")

  assert store.artwork_by_candidate() == {
    "itunes-album-search": 2,
    "itunes-song-search": 1,
  }


def test_artwork_with_no_candidate_is_not_counted(store):
  store.put_artwork("A", "Album", None, "url", 3000, "sha", "path")

  assert store.artwork_by_candidate() == {}


def test_the_database_is_in_wal_mode(store):
  """§14: the ui must be browsable while a resolve writes for hours.

  the default `delete` journal gives a writer an exclusive lock and readers
  SQLITE_BUSY; WAL lets them run concurrently.
  """
  mode = store.query("PRAGMA journal_mode")[0][0]

  assert mode.lower() == "wal"


def test_a_reader_is_not_blocked_by_an_open_writer(tmp_path):
  path = tmp_path / "sidecar.sqlite"
  with Store.open(path) as writer:
    writer.put_file(path="a.aiff", audio_md5="x", duration_s=1.0, isrc="A")
    with Store.open(path) as reader:
      assert len(reader.query("SELECT * FROM files")) == 1
