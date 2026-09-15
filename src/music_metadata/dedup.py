"""duplicate classification (SPEC.md §11a, F39, F40, F44).

**three classes, three policies, and only one of them is safely automatic.**

- **A** — same ISRC *and* same audio md5. auto-resolve: byte-identical audio
  cannot lose information.
- **B** — same ISRC, differing md5. **never auto-delete**: these are different
  recordings and one of the ISRCs is wrong.
- **C** — duration disagrees with the ISRC's own recording. strip the ISRC,
  route to tier-0 identity, queue for review.

the distinction matters because the cost of getting it wrong is asymmetric:
resolving class A wrongly loses nothing, and resolving class B wrongly destroys
a recording the operator cannot get back.

**deletion is always to a quarantine directory, never `rm`** — and §9's rule
that the source tree is never mutated means class A on the *source* library is a
report; only the output tree is de-duplicated.

note the ` (2)` filenames are a symptom, not the test (F39). all three measured
class-A duplicates happen to carry one, but the test is the audio hash — a
re-download under a different name would not.
"""

from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass

# F40 measured the tolerance: beyond this the ISRC does not describe the file.
DURATION_TOLERANCE_S = 5.0


class DuplicateClass(enum.StrEnum):
  """§11a's three classes."""

  IDENTICAL = "A-identical"
  SAME_ISRC_DIFFERENT_AUDIO = "B-same-isrc-different-audio"
  WRONG_ISRC = "C-wrong-isrc"


@dataclass(frozen=True, slots=True)
class TrackFile:
  """the local facts a duplicate decision is made from."""

  path: str
  audio_md5: str
  duration_s: float
  isrc: str | None = None


@dataclass(frozen=True, slots=True)
class Duplicate:
  """one group of files that need a decision, and which decision."""

  kind: DuplicateClass
  files: tuple[TrackFile, ...]
  reason: str

  @property
  def auto_resolvable(self) -> bool:
    """Whether policy allows resolving this without a human.

    Only class A. §11a is explicit that B is never auto-deleted and C changes
    identity rather than removing a file.
    """
    return self.kind is DuplicateClass.IDENTICAL

  @property
  def keep(self) -> TrackFile:
    """The file to keep when auto-resolving — the first by path, for stability."""
    return min(self.files, key=lambda f: f.path)

  @property
  def quarantine(self) -> tuple[TrackFile, ...]:
    """The files to move aside. Never deleted outright (§11a)."""
    keeper = self.keep
    return tuple(f for f in self.files if f.path != keeper.path)


def find_duplicates(files: list[TrackFile] | tuple[TrackFile, ...]) -> list[Duplicate]:
  """Group files that share an ISRC into §11a's classes A and B.

  Args:
    files: every probed file.

  Returns:
    One entry per duplicated ISRC, classified. Files with no ISRC are not
    duplicates of each other — F44 is explicit that an ISRC is not a unique key
    for a file, and *absence* of one says nothing at all.
  """
  by_isrc: dict[str, list[TrackFile]] = defaultdict(list)
  for entry in files:
    if entry.isrc:
      by_isrc[entry.isrc].append(entry)

  out: list[Duplicate] = []
  for isrc, group in sorted(by_isrc.items()):
    if len(group) < 2:
      continue
    hashes = {f.audio_md5 for f in group}
    if len(hashes) == 1:
      out.append(
        Duplicate(
          kind=DuplicateClass.IDENTICAL,
          files=tuple(sorted(group, key=lambda f: f.path)),
          reason=f"{isrc}: {len(group)} files, byte-identical audio",
        )
      )
    else:
      out.append(
        Duplicate(
          kind=DuplicateClass.SAME_ISRC_DIFFERENT_AUDIO,
          files=tuple(sorted(group, key=lambda f: f.path)),
          reason=(
            f"{isrc}: {len(group)} files with {len(hashes)} different recordings "
            f"— one of these ISRCs is wrong"
          ),
        )
      )
  return out


def find_identical_audio(
  files: list[TrackFile] | tuple[TrackFile, ...],
) -> list[Duplicate]:
  """Group files with the same decoded audio regardless of ISRC (G11).

  G11 asserts no two output files share an audio md5. That is a stronger check
  than `find_duplicates`, which only looks within an ISRC: a re-download under
  a different name may carry a different ISRC and still be the same recording.

  Args:
    files: every probed file.

  Returns:
    One entry per duplicated audio hash.
  """
  by_hash: dict[str, list[TrackFile]] = defaultdict(list)
  for entry in files:
    by_hash[entry.audio_md5].append(entry)

  return [
    Duplicate(
      kind=DuplicateClass.IDENTICAL,
      files=tuple(sorted(group, key=lambda f: f.path)),
      reason=f"{len(group)} files share decoded audio {digest[:12]}",
    )
    for digest, group in sorted(by_hash.items())
    if len(group) > 1
  ]


def isrc_describes_file(
  local_duration_s: float,
  claimed_duration_s: float | None,
  tolerance_s: float = DURATION_TOLERANCE_S,
) -> bool:
  """Whether a file's ISRC plausibly describes it (G10, F40).

  A delta beyond the tolerance means the ISRC belongs to a different recording.
  §8 is unambiguous about the consequence: the ISRC is stripped, the track goes
  to tier-0 identity, and **no field resolved from an untrusted ISRC is ever
  written**.

  Args:
    local_duration_s: the file's own duration.
    claimed_duration_s: the duration of the recording the ISRC identifies.
    tolerance_s: the permitted difference.

  Returns:
    True when the two agree, and when there is nothing to compare — an absent
    claim is not evidence against the ISRC, so it is not treated as such.
  """
  if claimed_duration_s is None or local_duration_s <= 0:
    return True
  return abs(local_duration_s - claimed_duration_s) <= tolerance_s
