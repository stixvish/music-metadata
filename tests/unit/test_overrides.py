"""§9b's hand-edits have to be *used*, not merely preserved.

the merge rule keeps an operator's edit in `library.toml`, but keeping it there
changes no tag on its own. these pin the other half: the edit reaching the
resolver, and a hand-typed ISRC reaching it *before* the lookups rather than
after, since the ISRC is the key the lookups are made with.
"""

from pathlib import Path

from music_metadata.cli import _effective, _overrides_for
from music_metadata.probe import ProbedFile


def probed(isrc=None, md5="abc"):
  return ProbedFile(
    path=Path("/m/library/The Killers - Mr. Brightside.aiff"),
    audio_md5=md5,
    duration_s=222.0,
    isrc=isrc,
    tags={},
  )


def test_a_hand_typed_isrc_is_substituted_before_any_lookup():
  """the 55 no-ISRC files are the whole point of this path."""
  out = _effective(probed(isrc=None), {"isrc": "GBAHT0400322"})

  assert out.isrc == "GBAHT0400322"


def test_a_hand_typed_isrc_overrides_the_files_own_tag():
  """§9b: a hand-edited value outranks every source, the file tag included."""
  out = _effective(probed(isrc="WRONG0000001"), {"isrc": "GBAHT0400322"})

  assert out.isrc == "GBAHT0400322"


def test_an_empty_override_leaves_the_file_alone():
  """`isrc = ""` is the generated placeholder, not an assertion of emptiness."""
  assert _effective(probed(isrc="USUG11800451"), {"isrc": ""}).isrc == "USUG11800451"
  assert _effective(probed(isrc="USUG11800451"), {}).isrc == "USUG11800451"


def test_whitespace_around_a_pasted_isrc_is_ignored():
  """it is typed by hand into a toml file; it will have stray spaces."""
  assert _effective(probed(), {"isrc": "  GBAHT0400322 "}).isrc == "GBAHT0400322"


def test_nothing_else_about_the_file_is_changed():
  """the override supplies identity, never local facts."""
  before = probed(isrc=None)
  after = _effective(before, {"isrc": "GBAHT0400322"})

  assert after.audio_md5 == before.audio_md5
  assert after.duration_s == before.duration_s
  assert after.path == before.path


def test_a_missing_map_overrides_nothing(tmp_path):
  """the first run has no map yet, and that is normal."""
  assert _overrides_for(tmp_path / "nope.toml") == {}


def test_only_hand_typed_values_count_as_overrides(tmp_path):
  """**the map holds generated values too, and those are not assertions.**

  reading every value back would make the pipeline treat its own output as
  the operator's choice: a generated artwork url would be re-fetched as
  `operator-supplied`, and a generated album name would pin itself forever.
  §9b's own test decides it — a value differing from what was generated last
  run was typed by hand.
  """
  from music_metadata.store import Store

  md5 = "5154f8a0e01e0dfd0cda86c43eb7ac41"
  path = tmp_path / "library.toml"
  path.write_text(
    f'["{md5}"]\n'
    'file     = "The Killers - Mr. Brightside.aiff"\n'
    'isrc     = "GBAHT0400322"\n'
    'album    = "Hot Fuss"\n'
  )

  with Store.open(tmp_path / "s.sqlite") as store:
    # the album is what we generated; the isrc is not.
    store.put_generated(md5, {"album": "Hot Fuss"})
    loaded = _overrides_for(path, store)

  assert loaded[md5]["isrc"] == "GBAHT0400322"
  assert "album" not in loaded[md5], "a generated value is not an override"


def test_without_a_store_nothing_is_treated_as_an_override(tmp_path):
  """no record of what was generated means no way to tell an edit apart."""
  path = tmp_path / "library.toml"
  path.write_text('["abc"]\nisrc     = "GBAHT0400322"\n')

  assert _overrides_for(path) == {}
