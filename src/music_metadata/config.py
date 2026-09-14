"""credentials and paths, read from the environment.

not in `SPEC.md` §12's module list, and deliberately small: every adapter needs
credentials and none should each grow its own way of finding them.

`CLAUDE.md`: no secrets in the repo, ever. `.env` is git-ignored and nothing
here ever writes a credential anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

# the sidecar is data, not config: `~/.config/musicpipeline/` holds the cookie
# jar and runtime settings, and a 3-4 GB cache does not belong beside them.
DEFAULT_SIDECAR = Path.home() / ".local/share/musicpipeline/sidecar.sqlite"
CONFIG_DIR = Path.home() / ".config/musicpipeline"


class MissingCredentialError(RuntimeError):
  """raised when a required credential is not set."""


def load_env(path: Path | None = None) -> None:
  """Load `KEY=value` lines from a `.env` file into the environment.

  Existing environment variables win, so a shell export overrides the file.

  Args:
    path: the file to read. Defaults to `.env` in the working directory.
  """
  path = path or Path(".env")
  if not path.is_file():
    return
  for line in path.read_text().splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
      continue
    key, _, value = stripped.partition("=")
    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def get(name: str, default: str | None = None) -> str | None:
  """Return an environment variable.

  Args:
    name: the variable name.
    default: value to return when it is unset.

  Returns:
    The value, or `default`.
  """
  return os.environ.get(name, default)


def require(name: str) -> str:
  """Return an environment variable, or explain which one is missing.

  Args:
    name: the variable name.

  Returns:
    The value.

  Raises:
    MissingCredentialError: if the variable is unset or empty.
  """
  value = os.environ.get(name)
  if not value:
    msg = f"{name} is not set; add it to .env (see .env.example)"
    raise MissingCredentialError(msg)
  return value
