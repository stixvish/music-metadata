import pytest

from music_metadata.library_map import (
  Entry,
  MapError,
  read,
  read_overrides,
  render,
  set_override,
  write,
)

MD5 = "446fd65a7c0be5bd83448b5a04bb7035"


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


# --- the map is generated; the overrides are yours ---------------------------
# §9b used to make one file do both jobs and decide between them by comparing
# against what was generated last run. two measured failures ended that: an
# algorithm change made 15 generated values look hand-typed, and regenerating
# the file destroyed an edit that lived in it.


def test_the_map_is_rewritten_in_full_every_run(tmp_path):
  """nothing in it is authored, so there is nothing to preserve."""
  path = tmp_path / "library.toml"

  write(path, [Entry(MD5, {"album": "First"})])
  write(path, [Entry(MD5, {"album": "Second"})])

  assert read(path)[MD5]["album"] == "Second"


def test_an_assertion_is_read_back_from_the_overrides_file(tmp_path):
  path = tmp_path / "overrides.toml"

  set_override(path, MD5, "isrc", "GBAHT0400322")

  assert read_overrides(path)[MD5]["isrc"] == "GBAHT0400322"


def test_an_absent_overrides_file_asserts_nothing(tmp_path):
  assert read_overrides(tmp_path / "nope.toml") == {}


def test_an_empty_value_is_not_an_assertion(tmp_path):
  """a blank line is the worklist's invitation, not a claim that it is blank."""
  path = tmp_path / "overrides.toml"
  path.write_text(f'["{MD5}"]\nbeatport = ""\n')

  assert read_overrides(path) == {}


def test_the_file_label_is_not_an_assertion(tmp_path):
  """it is there so the entry says what it is, not to override the filename."""
  path = tmp_path / "overrides.toml"
  path.write_text(f'["{MD5}"]\nfile     = "x.aiff"\nisrc     = "GBAHT0400322"\n')

  assert read_overrides(path)[MD5] == {"isrc": "GBAHT0400322"}


def test_setting_a_second_field_keeps_the_first(tmp_path):
  path = tmp_path / "overrides.toml"

  set_override(path, MD5, "isrc", "GBAHT0400322")
  set_override(path, MD5, "beatport", "https://beatport.com/track/x/1")

  loaded = read_overrides(path)[MD5]
  assert loaded["isrc"] == "GBAHT0400322"
  assert loaded["beatport"] == "https://beatport.com/track/x/1"


def test_setting_a_field_leaves_another_entry_alone(tmp_path):
  """**this is the property that was violated.** a write for one track must
  never be able to disturb another's."""
  other = "b" * 32
  path = tmp_path / "overrides.toml"
  set_override(path, other, "beatport", "https://beatport.com/track/keep/9")

  set_override(path, MD5, "isrc", "GBAHT0400322")

  assert read_overrides(path)[other]["beatport"].endswith("/keep/9")


def test_comments_in_the_overrides_file_survive_a_write(tmp_path):
  """the operator annotates their own file; a lookup must not strip it."""
  path = tmp_path / "overrides.toml"
  path.write_text(f'# why this one is odd\n["{MD5}"]\nisrc     = "AAA000000001"\n')

  set_override(path, MD5, "beatport", "https://beatport.com/track/x/1")

  assert "# why this one is odd" in path.read_text()


def test_rewriting_the_same_value_changes_nothing(tmp_path):
  path = tmp_path / "overrides.toml"
  set_override(path, MD5, "isrc", "GBAHT0400322")

  assert not set_override(path, MD5, "isrc", "GBAHT0400322")


def test_an_unknown_field_is_refused(tmp_path):
  with pytest.raises(MapError):
    set_override(tmp_path / "o.toml", MD5, "not_a_field", "x")


def test_malformed_overrides_fail_loudly(tmp_path):
  """silently ignoring a typo discards the operator's work at exactly the
  moment they were most deliberate about it."""
  path = tmp_path / "overrides.toml"
  path.write_text('["' + MD5 + '"]\nisrc = "unterminated\n')

  with pytest.raises(MapError):
    read_overrides(path)


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
