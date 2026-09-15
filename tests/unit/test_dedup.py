import pytest

from music_metadata.dedup import (
  DuplicateClass,
  TrackFile,
  find_duplicates,
  find_identical_audio,
  isrc_describes_file,
)


def f(path, md5="aaa", duration=200.0, isrc="USJI10000001"):
  return TrackFile(path=path, audio_md5=md5, duration_s=duration, isrc=isrc)


# --- class A: the only safely automatic one ---------------------------------


def test_same_isrc_and_same_audio_is_class_a():
  """§11a: byte-identical audio cannot lose information."""
  got = find_duplicates([f("a.aiff"), f("a (2).aiff")])

  assert len(got) == 1
  assert got[0].kind is DuplicateClass.IDENTICAL
  assert got[0].auto_resolvable is True


def test_class_a_keeps_one_and_quarantines_the_rest():
  got = find_duplicates([f("b.aiff"), f("a.aiff"), f("c.aiff")])[0]

  assert got.keep.path == "a.aiff"
  assert [x.path for x in got.quarantine] == ["b.aiff", "c.aiff"]


def test_the_numbered_filename_is_a_symptom_not_the_test():
  """F39: a re-download under a different name would not carry ` (2)`."""
  got = find_duplicates([f("track.aiff"), f("completely different name.aiff")])

  assert got[0].kind is DuplicateClass.IDENTICAL


# --- class B: never automatic ------------------------------------------------


def test_same_isrc_but_different_audio_is_class_b():
  """§11a: these are different recordings and one ISRC is wrong."""
  got = find_duplicates([f("a.aiff", md5="aaa"), f("b.aiff", md5="bbb")])

  assert got[0].kind is DuplicateClass.SAME_ISRC_DIFFERENT_AUDIO


def test_class_b_is_never_auto_resolvable():
  """resolving this wrongly destroys a recording that cannot be got back."""
  got = find_duplicates([f("a.aiff", md5="aaa"), f("b.aiff", md5="bbb")])

  assert got[0].auto_resolvable is False


def test_class_b_explains_itself():
  got = find_duplicates([f("a.aiff", md5="aaa"), f("b.aiff", md5="bbb")])

  assert "one of these ISRCs is wrong" in got[0].reason


# --- what is not a duplicate -------------------------------------------------


def test_a_single_file_is_not_a_duplicate():
  assert find_duplicates([f("a.aiff")]) == []


def test_different_isrcs_are_not_duplicates():
  assert find_duplicates([f("a.aiff", isrc="A"), f("b.aiff", isrc="B")]) == []


def test_files_with_no_isrc_are_not_duplicates_of_each_other():
  """F44: an ISRC is not a unique key, and its absence says nothing at all."""
  got = find_duplicates(
    [f("a.aiff", isrc=None, md5="x"), f("b.aiff", isrc=None, md5="y")]
  )

  assert got == []


def test_three_files_on_one_isrc_group_together():
  got = find_duplicates([f("a.aiff"), f("b.aiff"), f("c.aiff")])

  assert len(got) == 1
  assert len(got[0].files) == 3


# --- G11: identical audio regardless of ISRC --------------------------------


def test_identical_audio_under_different_isrcs_is_still_a_duplicate():
  """G11 is stronger than the ISRC grouping: a re-download may carry another."""
  got = find_identical_audio([f("a.aiff", isrc="A"), f("b.aiff", isrc="B")])

  assert len(got) == 1
  assert len(got[0].files) == 2


def test_distinct_audio_is_not_flagged_by_g11():
  assert find_identical_audio([f("a.aiff", md5="x"), f("b.aiff", md5="y")]) == []


def test_g11_covers_files_with_no_isrc():
  got = find_identical_audio([f("a.aiff", isrc=None), f("b.aiff", isrc=None)])

  assert len(got) == 1


# --- G10: does the ISRC describe this file? ---------------------------------


@pytest.mark.parametrize("claimed", [200.0, 202.0, 205.0, 195.0])
def test_a_matching_duration_trusts_the_isrc(claimed):
  assert isrc_describes_file(200.0, claimed) is True


@pytest.mark.parametrize("claimed", [206.0, 300.0, 120.0])
def test_a_diverging_duration_distrusts_the_isrc(claimed):
  """F40: delta > ±5s means the ISRC does not describe this file."""
  assert isrc_describes_file(200.0, claimed) is False


def test_the_boundary_is_inclusive():
  assert isrc_describes_file(200.0, 205.0) is True
  assert isrc_describes_file(200.0, 205.1) is False


def test_nothing_to_compare_is_not_evidence_against_the_isrc():
  """an absent claim is not a reason to strip a good ISRC."""
  assert isrc_describes_file(200.0, None) is True


def test_a_zero_local_duration_does_not_strip_the_isrc():
  assert isrc_describes_file(0.0, 300.0) is True
