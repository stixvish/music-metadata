import pytest

from music_metadata.dedup import (
  DuplicateClass,
  TrackFile,
  find_cross_format_duplicates,
  find_duplicates,
  find_identical_audio,
  isrc_describes_file,
  preference_key,
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


# --- class D: the same recording arriving in two formats ---------------------
# measured on the operator's library: a beatport .wav and a youtube-derived
# .aiff of the same track share a sample-exact duration (192.229365s) but
# **neither** an audio hash nor an ISRC — the wav carries no ISRC at all. so
# class D is matched on duration plus title, and is never automatic.


def test_the_measured_cross_format_pair_is_found():
  """the real files this class exists for."""
  files = [
    f(
      "/m/beatport/jUdAh, XXXTENTACION, Rio Santana, Andrez Babii"
      " - I don_t even speak spanish lol (Original Mix).wav",
      md5="db00b698",
      duration=192.229365,
      isrc=None,
    ),
    f(
      "/m/library/XXXTENTACION - I don't even speak spanish lol"
      " (ft. Rio Santana, Judah & Andrez Babii).aiff",
      md5="bae5aa52",
      duration=192.229365,
      isrc="USUG11800451",
    ),
  ]
  groups = find_cross_format_duplicates(files)

  assert len(groups) == 1
  assert groups[0].kind is DuplicateClass.PROBABLE_CROSS_FORMAT
  assert not groups[0].auto_resolvable, "class D is never automatic"


def test_the_wav_is_the_suggested_keep():
  """a store master outranks a youtube rip; the operator still confirms."""
  wav = f("/m/beatport/artist - song.wav", md5="a", duration=192.229365, isrc=None)
  aiff = f("/m/library/artist - song.aiff", md5="b", duration=192.229365, isrc="X")
  groups = find_cross_format_duplicates([aiff, wav])

  assert groups[0].suggested_keep.path.endswith(".wav")


def test_the_same_duration_with_unrelated_titles_is_not_a_duplicate():
  """measured: 22 exact-duration collisions in 1,494 files, mostly unrelated.

  youtube-sourced files land on round durations, so `159.000000` collides
  readily. the title check is what makes the duration signal usable.
  """
  files = [
    f("/m/library/Fixupboy - Problems.aiff", md5="a", duration=159.0, isrc="A"),
    f("/m/library/NAV - Good For It.aiff", md5="b", duration=159.0, isrc="B"),
  ]

  assert find_cross_format_duplicates(files) == []


def test_a_different_duration_is_never_a_cross_format_duplicate():
  """an extended mix is a different recording, however alike the titles read."""
  files = [
    f("/m/beatport/artist - song (Extended).wav", md5="a", duration=300.0, isrc=None),
    f("/m/library/artist - song.aiff", md5="b", duration=192.0, isrc="X"),
  ]

  assert find_cross_format_duplicates(files) == []


def test_byte_identical_files_are_class_a_not_class_d():
  """class A already covers them, and it is the automatic one."""
  files = [
    f("/m/library/song.aiff", md5="same", duration=192.0, isrc="X"),
    f("/m/library/song (2).aiff", md5="same", duration=192.0, isrc="X"),
  ]

  assert find_cross_format_duplicates(files) == []


# --- which copy survives -----------------------------------------------------


def test_the_redownload_suffix_loses_to_the_original():
  """`CHICA 305 (2).aiff` sorts *ahead* of `CHICA 305.aiff` (space < dot).

  so taking the first by path would systematically keep every re-download and
  drop every original — the opposite of what the operator wants.
  """
  group = find_identical_audio(
    [
      f("/m/library/John Summit & Feid - CHICA 305 (2).aiff", md5="same"),
      f("/m/library/John Summit & Feid - CHICA 305.aiff", md5="same"),
    ]
  )[0]

  assert group.keep.path.endswith("CHICA 305.aiff")
  assert group.quarantine[0].path.endswith("(2).aiff")


def test_a_store_master_outranks_a_youtube_rip():
  assert preference_key("/m/beatport/x.wav") < preference_key("/m/library/x.aiff")


def test_wav_outranks_aiff_within_one_folder():
  assert preference_key("/m/library/x.wav") < preference_key("/m/library/x.aiff")


def test_a_bare_number_in_a_title_is_not_a_redownload_suffix():
  """`(2)` only counts at the very end, after a space."""
  assert preference_key("/m/library/Song (2) Live.aiff")[2] == 0
  assert preference_key("/m/library/Song (2).aiff")[2] == 1
