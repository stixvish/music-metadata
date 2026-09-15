"""local tag facts, read with ffprobe. no network (SPEC.md §5a step 0).

identity is the **decoded audio**, not the container and not the tags: F44
measured that an ISRC is not a unique key for a file, so §11a's duplicate
classes turn on an md5 of the decoded PCM. retagging a file must not change it,
and the same PCM in a different container must hash the same.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# ffprobe reports the ID3 frame name directly for ISRC, rather than mapping it
# to a friendly key the way it does for title and artist.
_ISRC_TAG = "TSRC"

_AUDIO_SUFFIXES = {".aiff", ".aif", ".wav"}


class ProbeError(RuntimeError):
  """raised when a file cannot be probed."""


@dataclass(frozen=True, slots=True)
class ProbedFile:
  """what one file says about itself before any network call."""

  path: Path
  audio_md5: str
  duration_s: float
  isrc: str | None
  tags: dict[str, str]


def _binary(name: str) -> str:
  """Resolve a required external binary to an absolute path.

  Resolving rather than relying on PATH lookup at exec time is what keeps the
  subprocess calls below off ruff's S607.

  Args:
    name: the binary to find.

  Returns:
    Its absolute path.

  Raises:
    ProbeError: if the binary is not installed.
  """
  found = shutil.which(name)
  if found is None:
    msg = f"{name} is not installed; it is required to probe audio"
    raise ProbeError(msg)
  return found


def _run(cmd: list[str]) -> str:
  """Run a command and return stdout.

  Args:
    cmd: the argument list. Never a string, so no shell is involved.

  Returns:
    Captured stdout.

  Raises:
    ProbeError: if the command fails.
  """
  proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603 — argument list, absolute binary, no shell
  if proc.returncode != 0:
    msg = f"{Path(cmd[0]).name} failed: {proc.stderr.strip()[:200]}"
    raise ProbeError(msg)
  return proc.stdout


def audio_md5(path: Path) -> str:
  """Return the md5 of the file's decoded audio stream.

  This is the file's identity (F44). It ignores the container and every tag, so
  retagging does not change it and the same PCM in a WAV and an AIFF match.

  Args:
    path: the audio file.

  Returns:
    The md5 hex digest of the decoded stream.

  Raises:
    ProbeError: if the file cannot be decoded.
  """
  out = _run(
    [_binary("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"]
  )
  digest = out.strip().removeprefix("MD5=")
  if not digest:
    msg = f"no audio stream in {path}"
    raise ProbeError(msg)
  return digest


def probe_file(path: Path) -> ProbedFile:
  """Read one file's local facts.

  Args:
    path: the audio file.

  Returns:
    Its decoded-audio md5, duration, ISRC and tags.

  Raises:
    ProbeError: if the file is missing or is not audio.
  """
  if not path.is_file():
    msg = f"no such file: {path}"
    raise ProbeError(msg)

  out = _run(
    [
      _binary("ffprobe"),
      "-v",
      "quiet",
      "-print_format",
      "json",
      "-show_format",
      str(path),
    ]
  )
  try:
    fmt = json.loads(out)["format"]
  except (json.JSONDecodeError, KeyError) as exc:
    msg = f"ffprobe returned nothing usable for {path}"
    raise ProbeError(msg) from exc

  tags = {str(k): str(v) for k, v in fmt.get("tags", {}).items()}
  try:
    duration = float(fmt["duration"])
  except (KeyError, ValueError) as exc:
    msg = f"no duration for {path}"
    raise ProbeError(msg) from exc

  return ProbedFile(
    path=path,
    audio_md5=audio_md5(path),
    duration_s=duration,
    isrc=tags.get(_ISRC_TAG) or None,
    tags=tags,
  )


def probe_tree(*roots: Path) -> Iterator[ProbedFile]:
  """Probe every audio file under each root, in sorted path order.

  Several roots are supported because the operator's tracks arrive from more
  than one place — a store download and a youtube rip of the same recording sit
  in different folders, and §11a cannot compare what it never saw.

  Args:
    *roots: the directories to walk. A root that does not exist is skipped, so
      an optional folder need not be created to be named.

  Yields:
    One `ProbedFile` per audio file found. Each path is yielded once even if
    the roots overlap or repeat.
  """
  seen: set[Path] = set()
  for root in roots:
    if not root.is_dir():
      continue
    for path in sorted(root.rglob("*")):
      resolved = path.resolve()
      if resolved in seen:
        continue
      if path.is_file() and path.suffix.lower() in _AUDIO_SUFFIXES:
        seen.add(resolved)
        yield probe_file(path)
