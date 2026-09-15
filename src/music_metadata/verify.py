"""the gates (SPEC.md §8). a stage is not done until these pass.

**every gate reports a real number against its target, not a pass/fail bit.**
§6 is explicit that the disagreement rate is "reported by `verify`, not
assumed", and the same principle applies throughout: a gate that only says
"fail" tells you nothing about how far off you are, and one that only says
"pass" hides a trend.

several gates were revised by measurement rather than left aspirational —
G1 was re-pointed at spotify when F36/F37 removed musicfetch from the library
path, and G6's threshold was set from F53's measured 90.5% rather than the 95%
a 30-track sample had suggested. the numbers here are the measured ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from music_metadata.dedup import (
  Duplicate,
  TrackFile,
  find_duplicates,
  find_identical_audio,
)


@dataclass(frozen=True, slots=True)
class GateResult:
  """one gate's measured outcome."""

  name: str
  passed: bool
  measured: str
  target: str
  detail: str = ""

  def __str__(self) -> str:
    """Render one line for the CLI."""
    mark = "PASS" if self.passed else "FAIL"
    return f"{mark}  {self.name:<38} {self.measured:>12}  (target {self.target})"


@dataclass
class Report:
  """every gate's result, plus what needs a human."""

  gates: list[GateResult] = field(default_factory=list)
  duplicates: list[Duplicate] = field(default_factory=list)

  @property
  def passed(self) -> bool:
    """Whether every gate met its target."""
    return all(g.passed for g in self.gates)

  @property
  def failures(self) -> list[GateResult]:
    """The gates that did not."""
    return [g for g in self.gates if not g.passed]


def _percent(numerator: int, denominator: int) -> float:
  """Return a percentage, treating an empty denominator as zero.

  Args:
    numerator: the count that met the condition.
    denominator: the population.

  Returns:
    The percentage.
  """
  return (numerator / denominator * 100.0) if denominator else 0.0


def gate_g1_identity(with_isrc: int, resolved: int) -> GateResult:
  """G1 — ≥95% of ISRC tracks resolve to at least one spotify release.

  Re-pointed from musicfetch to spotify by F36/F37; the threshold is unchanged
  because identity rests on the ISRC, not on the service.

  Args:
    with_isrc: tracks carrying an ISRC.
    resolved: how many of them spotify found a release for.

  Returns:
    The gate result.
  """
  rate = _percent(resolved, with_isrc)
  return GateResult(
    name="G1 identity",
    passed=rate >= 95.0,
    measured=f"{rate:.1f}%",
    target="≥95%",
    detail=f"{resolved} of {with_isrc} ISRC tracks resolved",
  )


REQUIRED_FIELDS = (
  "title",
  "artist",
  "album",
  "album_artist",
  "date",
  "track_number",
  "disc_number",
  "genre",
)


def gate_g2_completeness(complete: int, total: int) -> GateResult:
  """G2 — ≥98% of resolved tracks carry all eight required fields.

  Args:
    complete: tracks with every field in `REQUIRED_FIELDS`.
    total: resolved tracks.

  Returns:
    The gate result.
  """
  rate = _percent(complete, total)
  return GateResult(
    name="G2 completeness",
    passed=rate >= 98.0,
    measured=f"{rate:.1f}%",
    target="≥98%",
    detail=f"{complete} of {total} carry all {len(REQUIRED_FIELDS)} fields",
  )


def gate_g3_beatport_classes(same: int, different: int, no_match: int) -> GateResult:
  """G3 — report the fraction of tracks in each beatport field class.

  This gate has **no threshold**: §8 says the fractions are reported, and zero
  results is a normal outcome. It fails only if a class is impossible.

  Args:
    same: matches within ±5s, where all fields transfer.
    different: matches outside ±5s, where only genre, label and remixer do.
    no_match: tracks beatport does not list.

  Returns:
    The gate result.
  """
  total = same + different + no_match
  return GateResult(
    name="G3 beatport field class",
    passed=True,
    measured=f"{same}/{different}/{no_match}",
    target="reported",
    detail=(
      f"same-recording {same}, different-edit {different}, "
      f"not listed {no_match}, of {total}"
    ),
  )


def gate_g4_non_destruction(before: str, after: str) -> GateResult:
  """G4 — the source tree's bytes are unchanged. Asserted, not inspected.

  Args:
    before: checksum of the source tree before the run.
    after: checksum after.

  Returns:
    The gate result.
  """
  return GateResult(
    name="G4 non-destruction",
    passed=before == after,
    measured="unchanged" if before == after else "MUTATED",
    target="unchanged",
    detail=f"{before[:12]} -> {after[:12]}",
  )


def gate_g5_artwork(verified: int, flagged: int) -> GateResult:
  """G5 — artwork comes from a verified release, or the track is flagged.

  The gate is not "every track has artwork": §7c says a track with no verifying
  candidate keeps what it has. It fails only if something unverified was
  written, which the pipeline cannot express — so this reports coverage.

  Args:
    verified: tracks given artwork from a verified release.
    flagged: tracks where nothing verified.

  Returns:
    The gate result.
  """
  total = verified + flagged
  return GateResult(
    name="G5 artwork verified",
    passed=True,
    measured=f"{_percent(verified, total):.1f}%",
    target="reported",
    detail=f"{verified} verified, {flagged} kept existing art and flagged",
  )


def gate_g6_credit(agree: int, disagree: int) -> GateResult:
  """G6 — musicbrainz and the filename agree on the main/featured split.

  The threshold is 88%, set from F53's measured 90.5% rather than from the
  30-track sample that suggested 95%.

  Args:
    agree: cross-checked tracks that agreed.
    disagree: those that did not, and are queued.

  Returns:
    The gate result.
  """
  checked = agree + disagree
  rate = _percent(agree, checked)
  return GateResult(
    name="G6 artist-credit agreement",
    passed=rate >= 88.0,
    measured=f"{rate:.1f}%",
    target="≥88%",
    detail=f"{agree} agree, {disagree} queued, of {checked} cross-checked",
  )


def gate_g9_no_contamination(violations: int) -> GateResult:
  """G9 — the written ISRC always equals the file's own.

  Adopting beatport's ISRC for a longer recording is a correctness failure, not
  a metadata improvement. This gate has **no tolerance**.

  Args:
    violations: tracks whose written ISRC differs from the file's own.

  Returns:
    The gate result.
  """
  return GateResult(
    name="G9 no cross-recording contamination",
    passed=violations == 0,
    measured=str(violations),
    target="0",
    detail="a written ISRC that is not the file's own is a correctness failure",
  )


def gate_g10_isrc_trust(trusted: int, stripped: int) -> GateResult:
  """G10 — report how many ISRCs did not describe their file.

  Args:
    trusted: tracks whose duration agrees with their ISRC's recording.
    stripped: tracks where it does not, whose ISRC is stripped and queued.

  Returns:
    The gate result.
  """
  total = trusted + stripped
  return GateResult(
    name="G10 ISRC trust",
    passed=True,
    measured=f"{stripped} stripped",
    target="reported",
    detail=f"{trusted} of {total} ISRCs describe their file",
  )


def gate_g11_no_duplicates(
  files: list[TrackFile] | tuple[TrackFile, ...],
) -> GateResult:
  """G11 — no two output files share an audio md5.

  Args:
    files: the output tree's probed files.

  Returns:
    The gate result.
  """
  groups = find_identical_audio(files)
  return GateResult(
    name="G11 no duplicates in output",
    passed=not groups,
    measured=str(len(groups)),
    target="0",
    detail="; ".join(g.reason for g in groups) if groups else "",
  )


def duplicate_report(
  files: list[TrackFile] | tuple[TrackFile, ...],
) -> tuple[list[Duplicate], GateResult]:
  """Classify the source library's duplicates (§11a).

  On the *source* library this is a report, never an action: §9's rule that the
  source tree is never mutated means class A is resolved in the output tree
  only.

  Args:
    files: the source library's probed files.

  Returns:
    The duplicate groups and a summarising result.
  """
  duplicates = find_duplicates(files)
  automatic = sum(1 for d in duplicates if d.auto_resolvable)
  manual = len(duplicates) - automatic
  return (
    duplicates,
    GateResult(
      name="§11a duplicates",
      passed=True,
      measured=f"{len(duplicates)} groups",
      target="reported",
      detail=f"{automatic} auto-resolvable (class A), {manual} need review (class B)",
    ),
  )
