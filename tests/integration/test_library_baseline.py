"""probe the real library and assert it reproduces the measured baseline.

CLAUDE.md: local facts get measured, not recalled. `cache/*.tsv` holds what
`ffprobe` actually reported for all 1,494 files, so the probe is correct exactly
when it reproduces those rows — this is an oracle, not a spot check.

marked `slow`: it decodes every file, which takes minutes.
"""

import pathlib

import pytest

from music_metadata.probe import probe_tree

LIBRARY = pathlib.Path.home() / "Music/library"
CACHE = pathlib.Path(__file__).parents[2] / "cache"

pytestmark = [
  pytest.mark.slow,
  pytest.mark.skipif(
    not (LIBRARY.is_dir() and (CACHE / "audiomd5.tsv").is_file()),
    reason="the real library or its measured baseline is not present",
  ),
]


def _baseline():
  md5 = {}
  for line in (CACHE / "audiomd5.tsv").read_text().splitlines():
    if line.strip():
      digest, name = line.split("\t", 1)
      md5[name] = digest
  isrc = {}
  for line in (CACHE / "isrc.tsv").read_text().splitlines():
    if line.strip():
      value, name = line.split("\t", 1)
      # the baseline writes the literal NONE where a file carries no ISRC.
      isrc[name] = None if value == "NONE" else value
  return md5, isrc


@pytest.fixture(scope="module")
def probed():
  return list(probe_tree(LIBRARY))


def test_probes_every_file_in_the_baseline(probed):
  expected_md5, _ = _baseline()

  assert len(probed) == len(expected_md5) == 1494


def test_every_audio_md5_matches_the_baseline(probed):
  expected_md5, _ = _baseline()

  wrong = [p.path.name for p in probed if p.audio_md5 != expected_md5[p.path.name]]

  assert wrong == []


def test_every_isrc_matches_the_baseline(probed):
  _, expected_isrc = _baseline()

  wrong = [p.path.name for p in probed if p.isrc != expected_isrc[p.path.name]]

  assert wrong == []


def test_isrc_coverage_matches_spec_section_2(probed):
  """SPEC.md §2: 1,494 files, 1,439 carry an ISRC (96.3%), 55 do not."""
  with_isrc = sum(1 for p in probed if p.isrc)

  assert with_isrc == 1439
  assert len(probed) - with_isrc == 55
