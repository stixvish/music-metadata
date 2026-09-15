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

# **the longest we will sit and wait on a `Retry-After`.** below this the
# server is describing a burst limit and waiting is simply correct. above it,
# the server is not throttling us — it has cut us off for a quota window, and
# the only useful response is to stop the run and come back later.
#
# measured 2026-09-14: spotify answered a client-credentials `/v1/search` 429
# with `Retry-After: 43868` — 12.2 hours. that is not a pause, it is a ban, and
# it is why the two cases are handled differently.
MAX_RETRY_AFTER_S = 60.0

# spotify's own word for "this is a budget, not a speed limit" (F56). slowing
# down does not clear it and retrying only spends more of it.
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"


class SourceError(RuntimeError):
  """raised when a source fails in a way the caller cannot treat as a miss.

  carries the HTTP status when there was one, so a caller that swallows
  failures by design can still tell *which* failure it swallowed. a tier that
  is allowed to contribute nothing (§5) must still not be allowed to fail
  silently and systematically.
  """

  def __init__(self, message: str, status: int | None = None) -> None:
    """Build the error.

    Args:
      message: what went wrong.
      status: the HTTP status, when the failure was a response.
    """
    super().__init__(message)
    self.status = status


class RateLimitedError(SourceError):
  """the service has cut us off for a window measured in hours, not seconds.

  spotify distinguishes two things that both surface as a 429, and they are not
  interchangeable: a **rate** limit (too many calls in a rolling 30s window,
  fixed by slowing down) and a **quota** (a budget for the developer account,
  which no amount of slowing down recovers). the body carries
  `"reason": "QUOTA_EXCEEDED"` for the second — see F56.

  **this is not a per-track failure and must not be handled as one.** skipping
  the track and moving to the next one re-asks a service that has already said
  no, for every remaining track, which banks nothing and risks extending the
  window. the caller stops the pass and reports when it can resume.
  """

  def __init__(self, service: str, retry_after: float, reason: str = "") -> None:
    """Build the error.

    Args:
      service: the source that cut us off.
      retry_after: seconds it asked us to wait.
      reason: the service's own classification, when it gives one.
    """
    self.service = service
    self.retry_after = retry_after
    self.reason = reason
    hours = retry_after / 3600.0
    label = "quota exhausted" if reason == QUOTA_EXCEEDED else "rate-limited"
    super().__init__(f"{service}: {label} for {retry_after:.0f}s ({hours:.1f}h)")


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
    self.requests = 0
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
      # **spotify does not publish the development-mode quota** (F56), so the
      # only way to learn our budget is to count what we spent before it said
      # no. retries count too — they come out of the same budget.
      self.requests += 1
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
        advice = response.headers.get("retry-after")
        # a wait we will not sit through is a quota window, not a burst limit.
        # fail immediately rather than spending the remaining attempts asking a
        # service that has already told us how long it will keep saying no.
        requested = _parse_retry_after(advice)
        reason = _error_reason(response)
        if reason == QUOTA_EXCEEDED or (
          requested is not None and requested > MAX_RETRY_AFTER_S
        ):
          raise RateLimitedError(self.name, requested or 0.0, reason)
        self._back_off(attempt, advice)
        continue
      if response.is_error:
        msg = f"{self.name}: HTTP {response.status_code} for {path}"
        raise SourceError(msg, status=response.status_code)

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
    fallback = _BACKOFF_BASE * (2 ** (attempt - 1))
    requested = _parse_retry_after(retry_after)
    if requested is None:
      # absent, or an HTTP date we do not parse; fall back to our own schedule.
      self._sleep(fallback)
      return
    self._sleep(min(requested, MAX_RETRY_AFTER_S))


def _error_reason(response: httpx.Response) -> str:
  """Read the service's own classification of an error, when it gives one.

  Args:
    response: the error response.

  Returns:
    The `error.reason` string, or "" when the body says nothing useful. A body
    that is not JSON is normal for an error page and must not raise here.
  """
  try:
    body = response.json()
  except ValueError:
    return ""
  if not isinstance(body, dict):
    return ""
  error = body.get("error")
  if not isinstance(error, dict):
    return ""
  reason = error.get("reason")
  return reason if isinstance(reason, str) else ""


def _parse_retry_after(value: str | None) -> float | None:
  """Read a `Retry-After` header expressed in seconds.

  Args:
    value: the raw header, when the service sent one.

  Returns:
    The seconds requested, or None when absent or given as an HTTP date.
  """
  if value is None:
    return None
  try:
    return float(value)
  except ValueError:
    return None
