import pytest

from music_metadata.dedup import DuplicateClass, TrackFile
from music_metadata.verify import (
  REQUIRED_FIELDS,
  Report,
  duplicate_report,
  gate_g1_identity,
  gate_g2_completeness,
  gate_g3_beatport_classes,
  gate_g4_non_destruction,
  gate_g5_artwork,
  gate_g6_credit,
  gate_g9_no_contamination,
  gate_g10_isrc_trust,
  gate_g11_no_duplicates,
)


def f(path, md5="aaa", isrc="A"):
  return TrackFile(path=path, audio_md5=md5, duration_s=200.0, isrc=isrc)


# --- gates with a real threshold ---------------------------------------------


def test_g1_passes_at_the_measured_baseline():
  """§8: measured baseline 20/20."""
  assert gate_g1_identity(with_isrc=1439, resolved=1439).passed is True


def test_g1_fails_below_ninety_five_percent():
  assert gate_g1_identity(with_isrc=1000, resolved=940).passed is False


def test_g1_reports_the_rate_not_just_a_verdict():
  got = gate_g1_identity(with_isrc=1000, resolved=940)

  assert got.measured == "94.0%"
  assert "940 of 1000" in got.detail


def test_g2_requires_all_eight_fields():
  assert len(REQUIRED_FIELDS) == 8


def test_g2_passes_at_ninety_eight_percent():
  assert gate_g2_completeness(complete=980, total=1000).passed is True


def test_g2_fails_below_it():
  assert gate_g2_completeness(complete=970, total=1000).passed is False


def test_g6_uses_the_measured_threshold_not_the_original():
  """F53: 88%, derived from the measured 90.5%. the 95% came from 30 tracks."""
  assert gate_g6_credit(agree=323, disagree=34).passed is True
  assert gate_g6_credit(agree=850, disagree=150).passed is False


def test_g6_reports_the_queue_depth():
  got = gate_g6_credit(agree=323, disagree=34)

  assert "34 queued" in got.detail


# --- gates with no tolerance --------------------------------------------------


def test_g4_passes_only_on_an_identical_checksum():
  assert gate_g4_non_destruction("abc123", "abc123").passed is True


def test_g4_fails_loudly_when_the_source_changed():
  got = gate_g4_non_destruction("abc123", "def456")

  assert got.passed is False
  assert got.measured == "MUTATED"


def test_g9_has_no_tolerance():
  """adopting beatport's ISRC is a correctness failure, not a near-miss."""
  assert gate_g9_no_contamination(0).passed is True
  assert gate_g9_no_contamination(1).passed is False


def test_g11_fails_when_output_files_share_audio():
  got = gate_g11_no_duplicates([f("a.aiff"), f("b.aiff")])

  assert got.passed is False
  assert got.measured == "1"


def test_g11_passes_on_distinct_audio():
  assert gate_g11_no_duplicates([f("a.aiff", md5="x"), f("b.aiff", md5="y")]).passed


# --- gates that report rather than judge --------------------------------------


def test_g3_reports_the_class_fractions_without_a_threshold():
  """§8: zero beatport results is a normal outcome, not a failure."""
  got = gate_g3_beatport_classes(same=10, different=3, no_match=1481)

  assert got.passed is True
  assert got.measured == "10/3/1481"


def test_g3_passes_even_with_no_matches_at_all():
  assert gate_g3_beatport_classes(0, 0, 1494).passed is True


def test_g5_reports_coverage_rather_than_demanding_it():
  """§7c: a track with no verifying candidate keeps what it has."""
  got = gate_g5_artwork(verified=1400, flagged=94)

  assert got.passed is True
  assert "94 kept existing art" in got.detail


def test_g10_reports_how_many_isrcs_were_stripped():
  got = gate_g10_isrc_trust(trusted=1430, stripped=9)

  assert got.passed is True
  assert got.measured == "9 stripped"


# --- the duplicate report -----------------------------------------------------


def test_duplicates_are_reported_and_split_by_policy():
  files = [
    f("a.aiff", md5="same", isrc="X"),
    f("a (2).aiff", md5="same", isrc="X"),
    f("b.aiff", md5="one", isrc="Y"),
    f("c.aiff", md5="two", isrc="Y"),
  ]

  duplicates, gate = duplicate_report(files)

  assert len(duplicates) == 2
  assert "1 auto-resolvable" in gate.detail
  assert "1 need review" in gate.detail


def test_the_duplicate_report_never_fails_the_run():
  """on the source library this is a report; §9 forbids mutating it."""
  files = [f("a.aiff", md5="s", isrc="X"), f("b.aiff", md5="s", isrc="X")]

  assert duplicate_report(files)[1].passed is True


def test_class_b_is_not_counted_as_auto_resolvable():
  files = [f("a.aiff", md5="one", isrc="Y"), f("b.aiff", md5="two", isrc="Y")]

  duplicates, _ = duplicate_report(files)

  assert duplicates[0].kind is DuplicateClass.SAME_ISRC_DIFFERENT_AUDIO
  assert duplicates[0].auto_resolvable is False


# --- the report ---------------------------------------------------------------


def test_a_report_passes_only_when_every_gate_does():
  report = Report(
    gates=[gate_g9_no_contamination(0), gate_g4_non_destruction("a", "a")]
  )

  assert report.passed is True


def test_a_report_names_its_failures():
  report = Report(
    gates=[gate_g9_no_contamination(3), gate_g4_non_destruction("a", "a")]
  )

  assert report.passed is False
  assert [g.name for g in report.failures] == ["G9 no cross-recording contamination"]


def test_a_gate_renders_one_readable_line():
  line = str(gate_g1_identity(with_isrc=100, resolved=100))

  assert line.startswith("PASS")
  assert "G1 identity" in line
  assert "100.0%" in line


def test_a_failing_gate_renders_as_fail():
  assert str(gate_g9_no_contamination(2)).startswith("FAIL")


@pytest.mark.parametrize(
  "gate",
  [
    gate_g1_identity(0, 0),
    gate_g2_completeness(0, 0),
    gate_g6_credit(0, 0),
    gate_g5_artwork(0, 0),
    gate_g10_isrc_trust(0, 0),
  ],
)
def test_an_empty_population_does_not_divide_by_zero(gate):
  assert gate.measured is not None
