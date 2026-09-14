"""the single place this package writes user-facing messages.

ruff's `T20` bans bare `print` in `src/` so that everything the CLI says can be
captured by the web ui (`SPEC.md` §14). the CLI and the ui are two front doors
to one store, and a message that escapes to stdout is invisible to one of them.

install a sink to capture messages; the default writes to stdout for plain CLI
runs.
"""

import enum
import sys
from dataclasses import dataclass, field
from typing import Protocol


class Level(enum.StrEnum):
  """severity of an emitted message."""

  INFO = "info"
  WARN = "warn"
  ERROR = "error"


@dataclass(frozen=True, slots=True)
class Message:
  """one emitted message and the structured context that came with it."""

  text: str
  level: Level = Level.INFO
  fields: dict[str, str] = field(default_factory=dict)


class Sink(Protocol):
  """anything that can receive emitted messages."""

  def write(self, message: Message) -> None:
    """Accept one message.

    Args:
      message: the message to record or render.
    """
    ...


class StdoutSink:
  """renders messages for a terminal. the default outside the web ui."""

  def write(self, message: Message) -> None:
    """Render one message to stdout.

    Args:
      message: the message to render.
    """
    parts = [f"{message.level.value:<5}", message.text]
    parts += [f"{k}={v}" for k, v in message.fields.items()]
    sys.stdout.write("  ".join(parts) + "\n")


class Recorder:
  """collects messages in memory. used by the web ui and by tests."""

  def __init__(self) -> None:
    """Start with an empty message list."""
    self.messages: list[Message] = []

  def write(self, message: Message) -> None:
    """Append one message.

    Args:
      message: the message to store.
    """
    self.messages.append(message)

  def drain(self) -> list[Message]:
    """Return everything collected so far and clear the buffer.

    Returns:
      The messages recorded since the last drain, oldest first.
    """
    out, self.messages = self.messages, []
    return out


_sink: Sink = StdoutSink()


def get_sink() -> Sink:
  """Return the sink currently receiving messages.

  Returns:
    The installed sink.
  """
  return _sink


def set_sink(sink: Sink) -> None:
  """Install the sink that receives subsequent messages.

  Args:
    sink: the sink to install.
  """
  # the module-level sink is the point of this module: one install site, and
  # every emit in the package routes through it.
  global _sink
  _sink = sink


def emit(text: str, level: Level = Level.INFO, **fields: str) -> None:
  """Emit one message to the installed sink.

  Args:
    text: the human-readable message.
    level: severity; defaults to `Level.INFO`.
    **fields: structured context carried alongside the text, such as the ISRC
      the message concerns.
  """
  _sink.write(Message(text=text, level=level, fields=dict(fields)))
