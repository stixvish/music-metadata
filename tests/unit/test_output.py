import pytest

from music_metadata.output import Level, Recorder, emit, get_sink, set_sink


@pytest.fixture(autouse=True)
def _restore_sink():
  before = get_sink()
  yield
  set_sink(before)


def test_emit_goes_to_the_installed_sink_not_stdout(capsys):
  rec = Recorder()
  set_sink(rec)

  emit("resolving 20 tracks")

  assert [m.text for m in rec.messages] == ["resolving 20 tracks"]
  # the whole point of the module: the web ui captures what the cli prints,
  # so nothing may escape to stdout behind the sink's back (SPEC.md §14).
  assert capsys.readouterr().out == ""


def test_levels_are_recorded():
  rec = Recorder()
  set_sink(rec)

  emit("starting", level=Level.INFO)
  emit("beatport auth failed, genre falls back", level=Level.WARN)
  emit("cookies dead, batch aborted", level=Level.ERROR)

  assert [m.level for m in rec.messages] == [Level.INFO, Level.WARN, Level.ERROR]


def test_fields_travel_with_the_message():
  rec = Recorder()
  set_sink(rec)

  emit("artwork rejected", isrc="GBARL1201392", candidate="album-search")

  assert rec.messages[0].fields == {
    "isrc": "GBARL1201392",
    "candidate": "album-search",
  }


def test_recorder_can_be_drained():
  rec = Recorder()
  set_sink(rec)

  emit("one")
  drained = rec.drain()
  emit("two")

  assert [m.text for m in drained] == ["one"]
  assert [m.text for m in rec.messages] == ["two"]


def test_default_sink_writes_to_stdout(capsys):
  emit("plain cli run")

  out = capsys.readouterr().out
  assert "plain cli run" in out


def test_default_sink_renders_level_and_fields(capsys):
  emit("no premium itag offered", level=Level.ERROR, itag="251")

  out = capsys.readouterr().out
  assert "error" in out
  assert "no premium itag offered" in out
  assert "itag=251" in out
