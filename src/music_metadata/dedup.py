"""duplicate classification (SPEC.md §11a, F39, F40, F44).

**three classes, three policies, and only one of them is safely automatic.**

- **A** — same ISRC *and* same audio md5. auto-resolve: byte-identical audio
  cannot lose information.
- **B** — same ISRC, differing md5. **never auto-delete**: these are different
  recordings and one of the ISRCs is wrong.
- **C** — duration disagrees with the ISRC's own recording. strip the ISRC,
  route to tier-0 identity, queue for review.
- **D** — the same recording acquired twice in different formats. **never
  automatic**: matched on duration and title, because neither the audio hash
  nor the ISRC can see it.

the distinction matters because the cost of getting it wrong is asymmetric:
resolving class A wrongly loses nothing, and resolving class B wrongly destroys
a recording the operator cannot get back.

**deletion is always to a quarantine directory, never `rm`** — and §9's rule
that the source tree is never mutated means class A on the *source* library is a
report; only the output tree is de-duplicated.

note the ` (2)` filenames are a symptom, not the test (F39). all three measured
class-A duplicates happen to carry one, but the test is the audio hash — a
re-download under a different name would not.

**class D is the case the hash cannot reach.** measured on the operator's
library: a beatport `.wav` and a youtube-derived `.aiff` of the same track have
the same duration to the microsecond (192.229365s) but different samples — the
youtube copy is lossy-sourced — and the wav carries **no ISRC at all**. so both
of the other tests fail on it, and duration plus title is what is left. that
signal is too weak to act on alone: 22 exact-duration collisions were measured
across 1,494 files, most of them unrelated tracks that happen to share a round
youtube duration. hence review, never auto-resolve.
"""

from __future__ import annotations

import enum
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

# F40 measured the tolerance: beyond this the ISRC does not describe the file.
DURATION_TOLERANCE_S = 5.0


class DuplicateClass(enum.StrEnum):
  """§11a's three classes."""

  IDENTICAL = "A-identical"
  SAME_ISRC_DIFFERENT_AUDIO = "B-same-isrc-different-audio"
  WRONG_ISRC = "C-wrong-isrc"
  PROBABLE_CROSS_FORMAT = "D-probable-cross-format"


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
    identity rather than removing a file, and D rests on a signal measured to
    produce false positives.
    """
    return self.kind is DuplicateClass.IDENTICAL

  @property
  def suggested_keep(self) -> TrackFile:
    """The copy most likely worth keeping. A suggestion, never an action.

    Returns:
      The best-ranked file, or the first by path when nothing separates them.
      Ranking prefers a store-purchased master over a youtube rip and a
      lossless container over one that has been through a lossy step.
    """
    return min(self.files, key=lambda f: preference_key(f.path))

  @property
  def keep(self) -> TrackFile:
    """The file to keep when auto-resolving.

    Ranked rather than merely first-by-path: `CHICA 305 (2).aiff` sorts ahead
    of `CHICA 305.aiff`, so taking the first would systematically keep the
    re-download and drop the original.
    """
    return min(self.files, key=lambda f: preference_key(f.path))

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


# a store download outranks a youtube rip: it is the master, not a re-encode.
# the folder is the signal the operator actually sorts by, and the container is
# a weaker proxy for the same thing.
_STORE_DIRS = ("beatport", "soundcloud")
_LOSSLESS_FIRST = (".wav", ".aiff", ".aif")


# F39: the ` (2)` suffix is a symptom of a re-download, not the test for one.
# it is useless for *finding* duplicates — but once a duplicate is found it is
# a good signal for deciding which copy to keep, because the unsuffixed name is
# the one the operator originally downloaded and the one any playlist refers to.
_REDOWNLOAD_SUFFIX = re.compile(r"\s\(\d+\)$")


def preference_key(path: str) -> tuple[int, int, int, str]:
  """Rank a file by which copy of a duplicate is worth keeping.

  Args:
    path: the file's path.

  Returns:
    A sort key; lower is better. Prefers a store master over a youtube rip, a
    lossless container, and a name with no ` (2)` re-download suffix.
  """
  store, container = _source_rank(path)
  stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  redownload = 1 if _REDOWNLOAD_SUFFIX.search(stem) else 0
  return (store, container, redownload, path)


def _source_rank(path: str) -> tuple[int, int]:
  """Rank a file by how likely it is to be the better copy.

  Args:
    path: the file's path.

  Returns:
    A sort key; lower is better.
  """
  lowered = path.lower()
  from_store = any(f"/{name}/" in lowered for name in _STORE_DIRS)
  suffix = lowered[lowered.rfind(".") :]
  container = (
    _LOSSLESS_FIRST.index(suffix) if suffix in _LOSSLESS_FIRST else len(_LOSSLESS_FIRST)
  )
  return (0 if from_store else 1, container)


# words that say nothing about which recording this is.
_NOISE = frozenset(
  {
    "a",
    "an",
    "the",
    "ft",
    "feat",
    "featuring",
    "with",
    "and",
    "original",
    "mix",
    "edit",
    "version",
    "remix",
    "extended",
    "radio",
  }
)


def _tokens(path: str) -> frozenset[str]:
  """Reduce a filename to the words that identify the recording.

  Args:
    path: the file's path.

  Returns:
    Lowercased word tokens, with punctuation, noise words and the extension
    removed. Apostrophes are dropped rather than split on, so `don_t` from a
    store's sanitised filename and `don't` from ours agree.
  """
  stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
  cleaned = "".join(
    c if c.isalnum() else " " for c in stem.replace("'", "").replace("_", "")
  )
  return frozenset(w for w in cleaned.split() if w and w not in _NOISE)


# measured: the real cross-format pair scores 0.81, and the nearest unrelated
# collision scores 0.0. anywhere in between separates them.
_TITLE_OVERLAP = 0.5


def find_cross_format_duplicates(
  files: list[TrackFile] | tuple[TrackFile, ...],
) -> list[Duplicate]:
  """Group files that look like one recording acquired twice (class D).

  Args:
    files: every probed file.

  Returns:
    One entry per probable pair. **Never auto-resolvable**: the operator
    confirms each in the review queue. Byte-identical files are left out —
    class A already covers them and is the automatic case.
  """
  by_duration: dict[float, list[TrackFile]] = defaultdict(list)
  for entry in files:
    if entry.duration_s > 0:
      by_duration[round(entry.duration_s, 6)].append(entry)

  out: list[Duplicate] = []
  for duration, group in sorted(by_duration.items()):
    if len(group) < 2:
      continue
    # class A's territory; the hash is the stronger test and it already fired.
    if len({f.audio_md5 for f in group}) == 1:
      continue
    for left, right in _pairs(group):
      if left.audio_md5 == right.audio_md5:
        continue
      shared = _tokens(left.path) & _tokens(right.path)
      union = _tokens(left.path) | _tokens(right.path)
      if not union or len(shared) / len(union) < _TITLE_OVERLAP:
        continue
      out.append(
        Duplicate(
          kind=DuplicateClass.PROBABLE_CROSS_FORMAT,
          files=tuple(sorted((left, right), key=lambda f: f.path)),
          reason=(
            f"{duration:.6f}s in both, titles share "
            f"{len(shared)}/{len(union)} words — probably one recording "
            f"acquired twice"
          ),
        )
      )
  return out


def _pairs(
  group: list[TrackFile],
) -> Iterator[tuple[TrackFile, TrackFile]]:
  """Yield every unordered pair in a group.

  Args:
    group: files sharing a duration.

  Yields:
    Each pair once.
  """
  for index, left in enumerate(group):
    for right in group[index + 1 :]:
      yield left, right


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
