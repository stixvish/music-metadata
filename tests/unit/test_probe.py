import shutil
import subprocess

import pytest

from music_metadata.probe import ProbeError, probe_file, probe_tree

pytestmark = pytest.mark.skipif(
  not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
  reason="ffmpeg/ffprobe not installed",
)


def make_aiff(path, seconds=1.0, **tags):
  """Write a real AIFF with real ID3 tags, so the probe is tested end to end."""
  cmd = [
    "ffmpeg",
    "-v",
    "error",
    "-y",
    "-f",
    "lavfi",
    "-i",
    f"sine=frequency=440:duration={seconds}",
    "-c:a",
    "pcm_s16be",
    "-ar",
    "44100",
    "-write_id3v2",
    "1",
  ]
  for k, v in tags.items():
    cmd += ["-metadata", f"{k}={v}"]
  cmd.append(str(path))
  subprocess.run(cmd, check=True, capture_output=True)
  return path


@pytest.fixture
def track(tmp_path):
  return make_aiff(
    tmp_path / "*NSYNC - Bye Bye Bye.aiff",
    seconds=2.0,
    title="Bye Bye Bye",
    artist="*NSYNC",
    TSRC="USJI10000001",
  )


def test_reads_the_isrc_from_the_tag(track):
  assert probe_file(track).isrc == "USJI10000001"


def test_reads_the_duration(track):
  assert probe_file(track).duration_s == pytest.approx(2.0, abs=0.05)


def test_audio_md5_is_of_the_decoded_audio_not_the_container(tmp_path):
  """F44: identity is the decoded audio, so container differences must not show.

  the same PCM in two containers has to hash the same, or the dedup in §11a is
  hashing the wrong thing.
  """
  aiff = make_aiff(tmp_path / "a.aiff", seconds=1.0, title="x")
  wav = tmp_path / "a.wav"
  subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-c:a", "pcm_s16le", str(wav)],
    check=True,
    capture_output=True,
  )

  assert probe_file(aiff).audio_md5 == probe_file(wav).audio_md5


def test_audio_md5_matches_ffmpeg_directly(track):
  out = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", str(track), "-map", "0:a", "-f", "md5", "-"],
    check=True,
    capture_output=True,
    text=True,
  ).stdout.strip()

  assert probe_file(track).audio_md5 == out.removeprefix("MD5=")


def test_different_audio_hashes_differently(tmp_path):
  a = make_aiff(tmp_path / "a.aiff", seconds=1.0)
  b = make_aiff(tmp_path / "b.aiff", seconds=2.0)

  assert probe_file(a).audio_md5 != probe_file(b).audio_md5


def test_retagging_does_not_change_the_audio_md5(tmp_path):
  """the whole point of hashing decoded audio: tags are not identity."""
  a = make_aiff(tmp_path / "a.aiff", seconds=1.0, title="one")
  b = make_aiff(tmp_path / "b.aiff", seconds=1.0, title="completely different")

  assert probe_file(a).audio_md5 == probe_file(b).audio_md5


def test_a_file_with_no_isrc_reports_none(tmp_path):
  f = make_aiff(tmp_path / "no-isrc.aiff", title="untagged")

  assert probe_file(f).isrc is None


def test_tags_are_carried_through(track):
  tags = probe_file(track).tags

  assert tags["title"] == "Bye Bye Bye"
  assert tags["artist"] == "*NSYNC"


def test_missing_file_raises(tmp_path):
  with pytest.raises(ProbeError):
    probe_file(tmp_path / "nope.aiff")


def test_a_non_audio_file_raises(tmp_path):
  junk = tmp_path / "junk.aiff"
  junk.write_text("this is not audio")

  with pytest.raises(ProbeError):
    probe_file(junk)


def test_probe_tree_finds_every_aiff_sorted(tmp_path):
  make_aiff(tmp_path / "b.aiff")
  make_aiff(tmp_path / "a.aiff")
  (tmp_path / "notes.txt").write_text("ignored")

  assert [p.path.name for p in probe_tree(tmp_path)] == ["a.aiff", "b.aiff"]


def test_probe_tree_is_case_insensitive_about_the_suffix(tmp_path):
  make_aiff(tmp_path / "upper.AIFF")

  assert [p.path.name for p in probe_tree(tmp_path)] == ["upper.AIFF"]


def test_probe_tree_reports_an_empty_directory_as_empty(tmp_path):
  assert list(probe_tree(tmp_path)) == []
