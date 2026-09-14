"""shared HTTP plumbing for every source adapter.

three things every adapter needs and none should reimplement: a **mandatory
timeout** (a request with none can hang the whole resolve), a shared rate
limiter, and retries that distinguish "this is a miss" from "try again".

that distinction is load-bearing. F30 measured musicbrainz answering
`currently busy` under load — a 503 there is a *retry*, not a miss, and treating
it as a miss silently drops artist credits. a 404, by contrast, is a normal
outcome: zero beatport results is expected on most of the library.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
  from music_metadata.sources.ratelimit import TokenBucket
  from music_metadata.store import JsonValue

# generous enough for a slow api, short enough that a hung connection does not
# stall a 1,494-track run indefinitely.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

_RETRYABLE = {429, 500, 502, 503, 504}
_BACKOFF_BASE = 1.0


class SourceError(RuntimeError):
  """raised when a source fails in a way the caller cannot treat as a miss."""


class Source:
  """one external service, rate-limited and retried."""

  def __init__(
    self,
    name: str,
    base_url: str,
    bucket: TokenBucket,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    retries: int = 3,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
  ) -> None:
    """Build an adapter.

    Args:
      name: the service's name, used in error messages.
      base_url: the API root; paths are joined onto it.
      bucket: the shared rate limiter for this service.
      headers: headers sent with every request, such as auth.
      timeout: per-request timeout. There is no way to opt out of one.
      retries: total attempts for a retryable failure.
      transport: injectable transport, so tests need no network.
      sleep: injectable sleep, so backoff is testable.
    """
    self.name = name
    self.bucket = bucket
    self.retries = retries
    self._sleep = sleep
    self._timeout = timeout
    self._client = httpx.Client(
      base_url=base_url,
      headers=headers or {},
      timeout=timeout,
      transport=transport,
    )

  @property
  def timeout(self) -> httpx.Timeout:
    """The per-request timeout this source uses."""
    return self._timeout

  def set_header(self, name: str, value: str) -> None:
    """Set a header sent with every subsequent request.

    Used for bearer tokens that are refreshed during a run.

    Args:
      name: the header name.
      value: the header value.
    """
    self._client.headers[name] = value

  def close(self) -> None:
    """Close the underlying connection pool."""
    self._client.close()

  def get_json(
    self, path: str, params: dict[str, str] | None = None
  ) -> JsonValue | None:
    """GET `path` and decode the JSON body.

    Args:
      path: path joined onto the base URL.
      params: query parameters.

    Returns:
      The decoded body, or None if the service returned 404 — a miss is a
      normal outcome, not an error.

    Raises:
      SourceError: on a non-404 error status, a body that is not JSON, or a
        transport failure that outlived the retries.
    """
    last: str = "no attempt made"
    for attempt in range(1, self.retries + 1):
      self.bucket.take()
      try:
        response = self._client.get(path, params=params)
      except httpx.HTTPError as exc:
        last = f"{type(exc).__name__}: {exc}"
        self._back_off(attempt)
        continue

      if response.status_code == httpx.codes.NOT_FOUND:
        return None
      if response.status_code in _RETRYABLE:
        last = f"HTTP {response.status_code}"
        self._back_off(attempt, response.headers.get("retry-after"))
        continue
      if response.is_error:
        msg = f"{self.name}: HTTP {response.status_code} for {path}"
        raise SourceError(msg)

      try:
        # httpx types .json() as Any; JsonValue is what it actually is.
        return cast("JsonValue", response.json())
      except ValueError as exc:
        msg = f"{self.name}: body was not JSON for {path}"
        raise SourceError(msg) from exc

    msg = f"{self.name}: {last} for {path} after {self.retries} attempts"
    raise SourceError(msg)

  def _back_off(self, attempt: int, retry_after: str | None = None) -> None:
    """Wait before the next attempt, preferring the server's own advice.

    Args:
      attempt: 1-based attempt number, used for exponential backoff.
      retry_after: the `Retry-After` header, when the service sent one.
    """
    if retry_after is not None:
      try:
        self._sleep(float(retry_after))
      except ValueError:
        # a Retry-After can be an HTTP date; fall back to our own schedule.
        self._sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
      return
    self._sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
