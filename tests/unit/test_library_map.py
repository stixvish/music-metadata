import pytest

from music_metadata.library_map import (
  Entry,
  MapError,
  merge,
  read,
  render,
  write,
)
from music_metadata.store import Store

MD5 = "446fd65a7c0be5bd83448b5a04bb7035"


@pytest.fixture
def store(tmp_path):
  with Store.open(tmp_path / "sidecar.sqlite") as s:
    yield s


def entry(**values):
  base = {
    "file": "Calvin Harris - Blessings.aiff",
    "title": "Blessings",
    "artist": "Calvin Harris",
    "album": "Blessings",
    "isrc": "GBARL2501127",
    "spotify": "https://open.spotify.com/track/1Z2",
    "itunes": "",
    "beatport": "",
  }
  base.update(values)
  return Entry(audio_md5=MD5, values=base)


# --- rendering ---------------------------------------------------------------


def test_the_entry_is_keyed_by_audio_md5(tmp_path):
  """F44: an ISRC is not a unique key for a file; the decoded audio is."""
  assert f'["{MD5}"]' in render([entry()])


def test_every_field_is_written_even_when_empty():
  """§9b: an empty field is an invitation, so it has to be visible."""
  out = render([entry()])

  assert 'beatport = ""' in out
  assert "# not found" in out


def test_the_rendered_map_is_valid_toml(tmp_path):
  path = tmp_path / "library.toml"
  path.write_text(render([entry()]))

  assert read(path)[MD5]["isrc"] == "GBARL2501127"


def test_quotes_in_a_value_do_not_break_the_file(tmp_path):
  path = tmp_path / "library.toml"
  path.write_text(render([entry(title='Kamariya (From "Stree")')]))

  assert read(path)[MD5]["title"] == 'Kamariya (From "Stree")'


def test_a_missing_map_reads_as_empty(tmp_path):
  """§9b: it is safe to delete."""
  assert read(tmp_path / "nope.toml") == {}


# --- §9b's merge rule --------------------------------------------------------


def test_a_value_we_generated_is_ours_to_refresh():
  merged = merge(
    MD5,
    resolved={"album": "The Real Album"},
    on_disk={"album": "Old Album"},
    generated={"album": "Old Album"},
  )

  assert merged.values["album"] == "The Real Album"
  assert "album" not in merged.manual


def test_a_value_the_operator_changed_is_preserved():
  merged = merge(
    MD5,
    resolved={"album": "The Real Album"},
    on_disk={"album": "What I Say It Is"},
    generated={"album": "Old Album"},
  )

  assert merged.values["album"] == "What I Say It Is"
  assert "album" in merged.manual


def test_clearing_a_line_hands_the_field_back():
  """§9b: deleting a line's value reverts that field to resolver control."""
  merged = merge(
    MD5,
    resolved={"beatport": "https://beatport.com/track/x/1"},
    on_disk={"beatport": ""},
    generated={"beatport": "https://beatport.com/track/old/9"},
  )

  assert merged.values["beatport"] == "https://beatport.com/track/x/1"
  assert "beatport" not in merged.manual


def test_a_pasted_url_into_an_empty_field_is_an_edit():
  """§9b: `beatport = ""` is the worklist entry — paste the URL, re-run."""
  merged = merge(
    MD5,
    resolved={"beatport": ""},
    on_disk={"beatport": "https://beatport.com/track/blessings/20819013"},
    generated={"beatport": ""},
  )

  assert merged.values["beatport"] == "https://beatport.com/track/blessings/20819013"
  assert "beatport" in merged.manual


def test_a_first_run_has_nothing_to_preserve():
  merged = merge(MD5, resolved={"album": "A"}, on_disk={}, generated={})

  assert merged.values["album"] == "A"
  assert merged.manual == frozenset()


# --- the round trip that the rule actually has to survive --------------------


def test_a_hand_edit_survives_a_regenerate(tmp_path, store):
  path = tmp_path / "library.toml"

  write(path, [merge(MD5, {"album": "Generated"}, {}, {})], store)
  on_disk = read(path)[MD5]
  on_disk["album"] = "Operator Says This"
  path.write_text(render([Entry(MD5, on_disk)]))

  second = merge(MD5, {"album": "Generated"}, read(path)[MD5], store.get_generated(MD5))
  write(path, [second], store)

  assert read(path)[MD5]["album"] == "Operator Says This"


def test_an_unedited_value_still_refreshes_across_runs(tmp_path, store):
  path = tmp_path / "library.toml"

  write(path, [merge(MD5, {"album": "First"}, {}, {})], store)
  second = merge(MD5, {"album": "Second"}, read(path)[MD5], store.get_generated(MD5))
  write(path, [second], store)

  assert read(path)[MD5]["album"] == "Second"


def test_a_hand_edit_is_not_adopted_as_our_own_baseline(tmp_path, store):
  """if an edit became the baseline, the operator's next edit would look like
  our output and be silently overwritten."""
  path = tmp_path / "library.toml"
  write(path, [merge(MD5, {"album": "Generated"}, {}, {})], store)

  edited = read(path)[MD5] | {"album": "Operator Says This"}
  write(
    path, [merge(MD5, {"album": "Generated"}, edited, store.get_generated(MD5))], store
  )

  assert store.get_generated(MD5)["album"] == "Generated"


def test_the_edit_still_holds_on_a_third_run(tmp_path, store):
  path = tmp_path / "library.toml"
  write(path, [merge(MD5, {"album": "Generated"}, {}, {})], store)
  edited = read(path)[MD5] | {"album": "Mine"}
  write(
    path, [merge(MD5, {"album": "Generated"}, edited, store.get_generated(MD5))], store
  )

  third = merge(MD5, {"album": "Generated"}, read(path)[MD5], store.get_generated(MD5))
  write(path, [third], store)

  assert read(path)[MD5]["album"] == "Mine"


# --- §9b vs §11a: two files can share one md5 --------------------------------


def test_duplicated_audio_yields_one_table_not_two(tmp_path):
  """§9b keys the map by md5 and §11a documents 3 class-A duplicates where two
  files share one. TOML cannot declare a key twice, so the map is one entry per
  *recording*, not per file — md5 keying is the load-bearing clause (F44)."""
  a = Entry(MD5, {"file": "CHICA 305.aiff", "isrc": "X"})
  b = Entry(MD5, {"file": "CHICA 305 (2).aiff", "isrc": "X"})

  out = render([a, b])

  assert out.count(f'["{MD5}"]') == 1


def test_the_duplicate_path_is_named_rather_than_hidden(tmp_path):
  a = Entry(MD5, {"file": "CHICA 305.aiff"})
  b = Entry(MD5, {"file": "CHICA 305 (2).aiff"})

  out = render([a, b])

  assert "also at: CHICA 305 (2).aiff" in out
  assert "class A duplicate" in out


def test_a_map_with_duplicates_is_still_valid_toml(tmp_path):
  path = tmp_path / "library.toml"
  path.write_text(
    render(
      [
        Entry(MD5, {"file": "a.aiff", "isrc": "X"}),
        Entry(MD5, {"file": "a (2).aiff", "isrc": "X"}),
        Entry("other", {"file": "b.aiff", "isrc": "Y"}),
      ]
    )
  )

  got = read(path)

  assert len(got) == 2
  assert got[MD5]["file"] == "a.aiff"


def test_the_first_path_by_order_is_the_one_kept(tmp_path):
  out = render(
    [Entry(MD5, {"file": "first.aiff"}), Entry(MD5, {"file": "second.aiff"})]
  )

  assert 'file     = "first.aiff"' in out


def test_a_malformed_map_fails_loudly_rather_than_silently(tmp_path):
  """§9b: the map carries hand-asserted values. treating a broken one as absent
  would discard them on the next write — deleting it is the operator's call."""
  path = tmp_path / "library.toml"
  path.write_text('["dup"]\nfile = "a"\n\n["dup"]\nfile = "b"\n')

  with pytest.raises(MapError, match="not valid TOML"):
    read(path)


def test_the_error_says_what_to_do(tmp_path):
  path = tmp_path / "library.toml"
  path.write_text("this is not toml at all [[[")

  with pytest.raises(MapError, match="delete it to regenerate"):
    read(path)
