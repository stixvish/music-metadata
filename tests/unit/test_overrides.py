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


def test_edits_are_read_back_keyed_by_md5(tmp_path):
  path = tmp_path / "library.toml"
  path.write_text(
    '["5154f8a0e01e0dfd0cda86c43eb7ac41"]\n'
    'file     = "The Killers - Mr. Brightside.aiff"\n'
    'isrc     = "GBAHT0400322"\n'
  )

  loaded = _overrides_for(path)

  assert loaded["5154f8a0e01e0dfd0cda86c43eb7ac41"]["isrc"] == "GBAHT0400322"
