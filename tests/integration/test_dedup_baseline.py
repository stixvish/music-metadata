"""classify the real library's duplicates and assert F39's measured counts.

marked `slow`: it reads the whole measured baseline, not the audio.
"""

import pathlib

import pytest

from music_metadata.dedup import (
  DuplicateClass,
  TrackFile,
  find_duplicates,
  find_identical_audio,
)

CACHE = pathlib.Path(__file__).parents[2] / "cache"

pytestmark = [
  pytest.mark.slow,
  pytest.mark.skipif(
    not (CACHE / "audiomd5.tsv").is_file(), reason="measured baseline not present"
  ),
]


@pytest.fixture(scope="module")
def library():
  md5 = {}
  for line in (CACHE / "audiomd5.tsv").read_text().splitlines():
    if line.strip():
      digest, name = line.split("\t", 1)
      md5[name] = digest
  isrc = {}
  for line in (CACHE / "isrc.tsv").read_text().splitlines():
    if line.strip():
      value, name = line.split("\t", 1)
      isrc[name] = None if value == "NONE" else value
  return [
    TrackFile(path=n, audio_md5=md5[n], duration_s=0.0, isrc=isrc.get(n)) for n in md5
  ]


def test_the_baseline_is_the_whole_library(library):
  assert len(library) == 1494


def test_f39s_six_duplicate_isrcs_are_found(library):
  """F39: the library has 6 duplicate ISRCs in three distinct classes."""
  assert len(find_duplicates(library)) == 6


def test_they_split_three_and_three(library):
  kinds = [d.kind for d in find_duplicates(library)]

  assert kinds.count(DuplicateClass.IDENTICAL) == 3
  assert kinds.count(DuplicateClass.SAME_ISRC_DIFFERENT_AUDIO) == 3


def test_only_the_identical_ones_are_auto_resolvable(library):
  """§11a: class B is never auto-deleted."""
  auto = [d for d in find_duplicates(library) if d.auto_resolvable]

  assert len(auto) == 3


def test_the_three_shared_audio_groups_match_the_baseline(library):
  """G11, against `cache/dupaudio.txt`."""
  expected = {
    line.strip()
    for line in (CACHE / "dupaudio.txt").read_text().splitlines()
    if line.strip()
  }
  found = {d.files[0].audio_md5 for d in find_identical_audio(library)}

  assert found == expected


def test_a_class_b_pair_can_be_two_unrelated_songs(library):
  """F39's worst case: `INS181600966` carries two different recordings.

  this is why class B is never auto-resolved — "keep one" would delete a track
  that has nothing to do with the one kept.
  """
  groups = {
    d.files[0].isrc: d
    for d in find_duplicates(library)
    if d.kind is DuplicateClass.SAME_ISRC_DIFFERENT_AUDIO
  }

  # both files claim this ISRC; they are not the same song.
  assert "INS181600966" in groups
  names = {f.path for f in groups["INS181600966"].files}
  assert len(names) == 2
