"""beatport cookie helper: export a session from chrome and verify it works.

F11: the session cookie lasts about a month and `/api/auth/session` re-mints a
fresh 10-minute token on every call. a copied *token* is useless — it dies long
before a full pass finishes — so what has to be exported is the **cookie**.

the cookie is `httpOnly`, so page JavaScript cannot read it, and chrome's cookie
store is encrypted with a key held in the macOS keychain. `yt-dlp` already
decrypts that store for the youtube path, so `export` reuses it rather than
reimplementing keychain access.

**only beatport.com cookies are written.** the browser's jar holds sessions for
every site you are logged into; writing all of them to disk would turn one
credential into dozens. the file is written `0600`.

usage:
  bp_cookies.py export [--browser chrome]   extract beatport cookies from chrome
  bp_cookies.py check                       mint a token and report
  bp_cookies.py path                        print where the file belongs
"""

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402 — needs the path above

from music_metadata.sources.bp_auth import (  # noqa: E402
  BROWSER_USER_AGENT,
  COOKIE_FILE,
  CookieSessionProvider,
  load_netscape_cookies,
)

# a harmless public page. yt-dlp needs *a* url to run, but `--simulate` means
# nothing is downloaded; we only want the side effect of it writing the jar.
_PROBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# the cookie F11 identifies as the session. its absence means the export
# captured a logged-out browser.
_SESSION_COOKIE = "__Secure-next-auth.session-token"

_DOMAIN_SUFFIX = "beatport.com"


def _extract_jar(browser: str, destination: Path) -> bool:
  """Have yt-dlp decrypt chrome's cookie store into a Netscape file.

  Args:
    browser: the browser spec yt-dlp understands, such as `chrome`.
    destination: where to write the full jar.

  Returns:
    True when a jar was written.
  """
  yt_dlp = shutil.which("yt-dlp")
  if yt_dlp is None:
    print("FAIL  yt-dlp is not installed; it is what decrypts chrome's cookies")
    return False
  subprocess.run(
    [
      yt_dlp,
      "--cookies-from-browser",
      browser,
      "--cookies",
      str(destination),
      "--skip-download",
      "--simulate",
      "--quiet",
      "--no-warnings",
      _PROBE_URL,
    ],
    capture_output=True,
    text=True,
    check=False,
  )
  return destination.is_file()


def _filter_to_beatport(source: Path, destination: Path) -> int:
  """Copy only beatport.com cookies, dropping every other site's session.

  Args:
    source: the full browser jar.
    destination: where to write the filtered jar.

  Returns:
    How many cookies were kept.
  """
  kept = [
    "# Netscape HTTP Cookie File",
    "# beatport.com only, exported by bp_cookies.py",
  ]
  for line in source.read_text().splitlines():
    if line.startswith("#") or not line.strip():
      continue
    fields = line.split("\t")
    if len(fields) >= 7 and fields[0].lstrip(".").endswith(_DOMAIN_SUFFIX):
      kept.append(line)

  destination.parent.mkdir(parents=True, exist_ok=True)
  destination.write_text("\n".join(kept) + "\n")
  # the file is a credential; nobody else on the machine needs to read it.
  destination.chmod(0o600)
  return len(kept) - 2


def cmd_export(args):
  with tempfile.TemporaryDirectory() as tmp:
    full = Path(tmp) / "jar.txt"
    if not _extract_jar(args.browser, full):
      print(f"FAIL  could not read cookies from {args.browser}")
      print("      is the browser installed, and have you logged into beatport?")
      return 1

    count = _filter_to_beatport(full, COOKIE_FILE)

  if count == 0:
    print(f"FAIL  no {_DOMAIN_SUFFIX} cookies found in {args.browser}")
    print("      log in at https://www.beatport.com and run this again")
    return 1

  jar = load_netscape_cookies(COOKIE_FILE)
  print(f"wrote {count} {_DOMAIN_SUFFIX} cookies to {COOKIE_FILE} (0600)")
  if _SESSION_COOKIE not in jar:
    print(f"WARN  {_SESSION_COOKIE} is missing — the browser may be logged out")
  print()
  return cmd_check(args)


def cmd_check(_args):
  if not COOKIE_FILE.is_file():
    print(f"FAIL  no cookie file at {COOKIE_FILE}")
    print("      run `bp_cookies.py export` to create one")
    return 1

  jar = load_netscape_cookies(COOKIE_FILE)
  mode = oct(COOKIE_FILE.stat().st_mode & 0o777)
  print(f"cookie file  {COOKIE_FILE}  ({len(jar)} cookies, mode {mode})")
  print(f"session      {'present' if _SESSION_COOKIE in jar else 'MISSING'}")

  token = CookieSessionProvider().get()
  if token is None:
    print()
    print("FAIL  could not mint a bearer token.")
    print("      the session has probably expired — re-run `export`.")
    return 1

  print(f"token        minted, {len(token)} chars")

  # **minting a token is not evidence the token works**, and reporting it as
  # success is how a whole pass came back empty. a stale exported cookie mints
  # a token missing the `openid` scope; the catalog API answers every request
  # with 401, and the pipeline reports each one as "not on beatport". so the
  # check asks the API the pipeline actually uses.
  probe = httpx.get(
    "https://api.beatport.com/v4/catalog/tracks/",
    params={"isrc": "USQX92100617"},
    headers={"Authorization": f"Bearer {token}", "User-Agent": BROWSER_USER_AGENT},
    timeout=30.0,
  )
  if probe.status_code == httpx.codes.UNAUTHORIZED:
    scope = _scope_of(token)
    print(f"scope        {scope!r}")
    print()
    print("FAIL  the catalog API rejected the token.")
    if "openid" not in scope:
      print("      it is missing the `openid` scope, which means the exported")
      print("      cookie is stale — the session token rotated since the export.")
    print("      log in at https://www.beatport.com and re-run `export`.")
    return 1
  if probe.status_code != httpx.codes.OK:
    print()
    print(f"FAIL  the catalog API answered HTTP {probe.status_code}.")
    return 1

  print(f"scope        {_scope_of(token)!r}")
  print()
  print("OK    the catalog API accepted it and returned a track.")
  print("      beatport will contribute genre, BPM and key on the next resolve.")
  return 0


def _scope_of(token: str) -> str:
  """Read the scope claim out of a JWT without verifying it.

  Args:
    token: the bearer token.

  Returns:
    The scope string, or "" when it cannot be read.
  """
  try:
    segment = token.split(".")[1]
    padded = segment + "=" * (-len(segment) % 4)
    return str(json.loads(base64.urlsafe_b64decode(padded)).get("scope", ""))
  except (IndexError, ValueError):
    return ""


def cmd_path(_args):
  print(COOKIE_FILE)
  return 0


def main():
  ap = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
  )
  sub = ap.add_subparsers(dest="cmd", required=True)

  export = sub.add_parser("export", help="extract beatport cookies from a browser")
  export.add_argument(
    "--browser",
    default="chrome",
    help="browser spec yt-dlp understands: chrome, chrome:Profile 1, firefox, safari",
  )
  export.set_defaults(func=cmd_export)

  sub.add_parser("check", help="mint a token and report").set_defaults(func=cmd_check)
  sub.add_parser("path", help="print the cookie file path").set_defaults(func=cmd_path)

  args = ap.parse_args()
  raise SystemExit(args.func(args))


if __name__ == "__main__":
  main()
