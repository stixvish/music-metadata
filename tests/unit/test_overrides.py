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


def test_assertions_come_from_the_overrides_file(tmp_path):
  """the map is generated and holds no assertions, so it is not consulted."""
  path = tmp_path / "overrides.toml"
  path.write_text('["abc"]\nisrc     = "GBAHT0400322"\n')

  assert _overrides_for(path)["abc"]["isrc"] == "GBAHT0400322"


def test_an_absent_overrides_file_asserts_nothing(tmp_path):
  """the common case: an operator who has asserted nothing."""
  assert _overrides_for(tmp_path / "nope.toml") == {}


def test_a_generated_value_can_no_longer_be_mistaken_for_an_assertion(tmp_path):
  """**this is what the split is for.**

  the map held generated values and typed ones together, and telling them
  apart needed a third record of what was generated. an algorithm change then
  moved 15 generated values and every one read as hand-typed. now a value is
  an assertion because of the file it is in, and nothing else.
  """
  map_path = tmp_path / "library.toml"
  map_path.write_text('["abc"]\nalbum    = "El Dorado (Deluxe)"\n')

  assert _overrides_for(tmp_path / "overrides.toml") == {}
