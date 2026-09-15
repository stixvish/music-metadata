"""beatport authentication, pluggable by design (SPEC.md F11, F15, OQ-5).

**a copied bearer token dies in ten minutes and a full pass takes over an hour,
so a manual token cannot cover even one run** (F11). the session cookie lasts a
month and `/api/auth/session` re-mints a fresh token on every call, so the
design is: export the cookie once a month, mint a token per run, re-mint before
it expires.

the cookie is `httpOnly` and cannot be read from page JavaScript. it is exported
from chrome's cookie store the same way `youtube-cookies.txt` already is, and
lives in `~/.config/musicpipeline/` — **never the repo**.

**nothing here raises when auth is unavailable.** §5 makes tier 3 the component
most likely to break and the one nothing depends on: a provider that cannot mint
a token returns `None`, beatport returns no match, and genre falls back. an
exception here would take the whole run down with it, which is precisely the
coupling the tier was designed to avoid.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx

from music_metadata.config import CONFIG_DIR

SESSION_URL = "https://www.beatport.com/api/auth/session"

# **a browser User-Agent is mandatory, and this is not cosmetic.** F6 records
# that cloudflare fronts the *web* host, and `/api/auth/session` is on the web
# host. the `cf_clearance` cookie in the exported jar is bound to the
# User-Agent that obtained it, so sending a different one fails the challenge:
#
#   no UA        HTTP 403  "Just a moment..."   (the cloudflare interstitial)
#   browser UA   HTTP 200  {"token": {"accessToken": ...}}
#
# measured 2026-09-14. this is why the export has to come from the same browser
# the session was created in.
BROWSER_USER_AGENT = (
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

COOKIE_FILE = CONFIG_DIR / "beatport-cookies.txt"

# F11 measured `expiresIn` at 599 seconds. re-mint with room to spare rather
# than racing a token that expires mid-request.
_REFRESH_MARGIN_S = 120.0

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class TokenProvider(Protocol):
  """anything that can supply a beatport bearer token."""

  def get(self) -> str | None:
    """Return a valid bearer token, or None when one cannot be minted."""
    ...


def load_netscape_cookies(path: Path) -> dict[str, str]:
  """Read a Netscape-format cookie file into a name/value mapping.

  This is the format `yt-dlp --cookies` writes and chrome extensions export,
  so the beatport jar is produced the same way the youtube one already is.

  Args:
    path: the cookie file.

  Returns:
    Cookie names to values. Empty when the file is missing or unreadable —
    a missing cookie is a normal state, not an error.
  """
  if not path.is_file():
    return {}
  jar: dict[str, str] = {}
  try:
    lines = path.read_text().splitlines()
  except OSError:
    return {}
  for line in lines:
    if not line.strip() or line.startswith("#"):
      continue
    fields = line.split("\t")
    # domain, flag, path, secure, expiry, name, value
    if len(fields) >= 7 and fields[5]:
      jar[fields[5]] = fields[6]
  return jar


class CookieSessionProvider:
  """mints a token from an exported session cookie (F11). works today."""

  def __init__(
    self,
    cookie_file: Path = COOKIE_FILE,
    transport: httpx.BaseTransport | None = None,
    now: Callable[[], float] = time.monotonic,
  ) -> None:
    """Build the provider.

    Args:
      cookie_file: the exported Netscape cookie jar.
      transport: injectable transport, so tests need no network.
      now: injectable monotonic clock, for token expiry.
    """
    self.cookie_file = cookie_file
    self._now = now
    self._transport = transport
    self._token: str | None = None
    self._expires_at = 0.0

  @property
  def available(self) -> bool:
    """Whether a cookie jar exists to try at all."""
    return self.cookie_file.is_file()

  def get(self) -> str | None:
    """Return a bearer token, minting or re-minting as needed.

    Returns:
      The token, or None when no cookie exists, the session has expired, or
      beatport is unreachable. None is a normal outcome, not a failure.
    """
    if self._token is not None and self._now() < self._expires_at:
      return self._token

    cookies = load_netscape_cookies(self.cookie_file)
    if not cookies:
      return None

    client = httpx.Client(
      timeout=_TIMEOUT,
      transport=self._transport,
      cookies=cookies,
      headers={"User-Agent": BROWSER_USER_AGENT},
      follow_redirects=True,
    )
    try:
      response = client.get(SESSION_URL)
    except httpx.HTTPError:
      return None
    finally:
      client.close()

    if response.status_code != httpx.codes.OK:
      return None
    try:
      body = response.json()
    except ValueError:
      return None
    if not isinstance(body, dict):
      return None

    token_block = body.get("token")
    if not isinstance(token_block, dict):
      return None
    access = token_block.get("accessToken")
    if not isinstance(access, str) or not access:
      return None

    expires_in = token_block.get("expiresIn")
    lifetime = float(expires_in) if isinstance(expires_in, (int, float)) else 599.0
    self._token = access
    self._expires_at = self._now() + max(0.0, lifetime - _REFRESH_MARGIN_S)
    return self._token


class OAuthClientProvider:
  """mints a token from official credentials (F15, OQ-5). not yet usable.

  F15 measured that the official API **is the same API**; only the acquisition
  of the token differs. so this slots in beside the cookie provider without
  anything downstream changing — which is the whole point of the protocol.
  """

  def __init__(self, client_id: str | None, client_secret: str | None) -> None:
    """Build the provider.

    Args:
      client_id: beatport application id, when the operator has one.
      client_secret: beatport application secret.
    """
    self.client_id = client_id
    self.client_secret = client_secret

  @property
  def available(self) -> bool:
    """Whether credentials have been supplied at all."""
    return bool(self.client_id and self.client_secret)

  def get(self) -> str | None:
    """Return a bearer token.

    Returns:
      None until OQ-5 is resolved and credentials exist. Returning None rather
      than raising is what lets this be wired in before it works.
    """
    return None


class NullProvider:
  """supplies nothing. the explicit way to run with beatport off."""

  available = False

  def get(self) -> str | None:
    """Return no token.

    Returns:
      Always None.
    """
    return None
