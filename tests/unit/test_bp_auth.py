import httpx

from music_metadata.sources.bp_auth import (
  CookieSessionProvider,
  NullProvider,
  OAuthClientProvider,
  load_netscape_cookies,
)

# F11's measured shape, trimmed.
SESSION = {
  "token": {
    "accessToken": "a" * 1156,
    "tokenType": "bearer",
    "expiresIn": 599,
    "scope": "user:dj openid app:prostore",
  },
  "expires": "2026-10-14T00:00:00.000Z",
}

JAR = (
  "# Netscape HTTP Cookie File\n"
  ".beatport.com\tTRUE\t/\tTRUE\t1791000000\t__Secure-next-auth.session-token\tSECRET\n"
  ".beatport.com\tTRUE\t/\tFALSE\t1791000000\t_ga\tGA1.2.3\n"
)


class FakeClock:
  def __init__(self):
    self.t = 0.0

  def now(self):
    return self.t


def cookie_file(tmp_path, text=JAR):
  p = tmp_path / "beatport-cookies.txt"
  p.write_text(text)
  return p


def provider(tmp_path, handler, **kw):
  clock = FakeClock()
  p = CookieSessionProvider(
    cookie_file=kw.pop("cookie_file", cookie_file(tmp_path)),
    transport=httpx.MockTransport(handler),
    now=clock.now,
  )
  p.clock = clock
  return p


# --- the cookie jar ----------------------------------------------------------


def test_the_session_cookie_is_read(tmp_path):
  jar = load_netscape_cookies(cookie_file(tmp_path))

  assert jar["__Secure-next-auth.session-token"] == "SECRET"
  assert jar["_ga"] == "GA1.2.3"


def test_comments_and_blank_lines_are_ignored(tmp_path):
  jar = load_netscape_cookies(cookie_file(tmp_path, "# a comment\n\n" + JAR))

  assert len(jar) == 2


def test_a_missing_cookie_file_is_empty_not_an_error(tmp_path):
  """§5: tier 3 breaking must not raise. a missing cookie is a normal state."""
  assert load_netscape_cookies(tmp_path / "nope.txt") == {}


def test_a_malformed_line_is_skipped(tmp_path):
  jar = load_netscape_cookies(cookie_file(tmp_path, "not\ta\tcookie\n" + JAR))

  assert len(jar) == 2


# --- minting a token ---------------------------------------------------------


def test_a_token_is_minted_from_the_session(tmp_path):
  got = provider(tmp_path, lambda r: httpx.Response(200, json=SESSION)).get()

  assert got == "a" * 1156


def test_the_cookies_are_sent(tmp_path):
  seen = {}

  def handler(request):
    seen["cookie"] = request.headers.get("cookie", "")
    return httpx.Response(200, json=SESSION)

  provider(tmp_path, handler).get()

  assert "__Secure-next-auth.session-token=SECRET" in seen["cookie"]


def test_the_token_is_reused_until_it_nears_expiry(tmp_path):
  calls = []

  def handler(request):
    calls.append(1)
    return httpx.Response(200, json=SESSION)

  p = provider(tmp_path, handler)
  p.get()
  p.clock.t += 100.0
  p.get()

  assert len(calls) == 1


def test_the_token_is_re_minted_before_it_expires(tmp_path):
  """F11: expiresIn is 599s and a full pass takes over an hour."""
  calls = []

  def handler(request):
    calls.append(1)
    return httpx.Response(200, json=SESSION)

  p = provider(tmp_path, handler)
  p.get()
  p.clock.t += 500.0
  p.get()

  assert len(calls) == 2


# --- every failure is None, never an exception (§5) --------------------------


def test_no_cookie_file_yields_no_token(tmp_path):
  p = provider(
    tmp_path,
    lambda r: httpx.Response(200, json=SESSION),
    cookie_file=tmp_path / "absent.txt",
  )

  assert p.get() is None
  assert p.available is False


def test_an_expired_session_yields_no_token(tmp_path):
  assert provider(tmp_path, lambda r: httpx.Response(401)).get() is None


def test_an_unreachable_beatport_yields_no_token(tmp_path):
  def handler(request):
    raise httpx.ConnectError("boom")

  assert provider(tmp_path, handler).get() is None


def test_a_non_json_body_yields_no_token(tmp_path):
  assert provider(tmp_path, lambda r: httpx.Response(200, text="<html>")).get() is None


def test_a_session_without_a_token_block_yields_none(tmp_path):
  body = {"expires": "2026-10-14T00:00:00.000Z"}

  assert provider(tmp_path, lambda r: httpx.Response(200, json=body)).get() is None


def test_an_empty_access_token_yields_none(tmp_path):
  body = {"token": {"accessToken": "", "expiresIn": 599}}

  assert provider(tmp_path, lambda r: httpx.Response(200, json=body)).get() is None


def test_a_missing_expires_in_still_mints(tmp_path):
  body = {"token": {"accessToken": "tok"}}

  assert provider(tmp_path, lambda r: httpx.Response(200, json=body)).get() == "tok"


# --- the other providers ------------------------------------------------------


def test_the_oauth_provider_is_wired_but_not_yet_usable():
  """OQ-5: F15 measured the official API is the same API; only auth differs."""
  p = OAuthClientProvider(client_id=None, client_secret=None)

  assert p.available is False
  assert p.get() is None


def test_the_oauth_provider_reports_available_once_credentials_exist():
  assert OAuthClientProvider("id", "secret").available is True


def test_the_null_provider_supplies_nothing():
  assert NullProvider().get() is None
  assert NullProvider().available is False
