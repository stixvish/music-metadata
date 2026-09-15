"""beatport cookie helper: check whether a session can mint a bearer token.

F11: the session cookie lasts about a month and `/api/auth/session` re-mints a
fresh 10-minute token on every call. a copied *token* is useless — it dies long
before a full pass finishes — so what has to be exported is the **cookie**.

the cookie is `httpOnly`, so page JavaScript cannot read it. export it from
chrome with a Netscape-format cookie extension, the same way
`youtube-cookies.txt` was produced, and save it to the path `path` prints.

usage:
  bp_cookies.py path     print where the cookie file belongs
  bp_cookies.py check    mint a token and report whether it worked
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_metadata.sources.bp_auth import (  # noqa: E402 — needs the path above
  COOKIE_FILE,
  CookieSessionProvider,
  load_netscape_cookies,
)


def cmd_path(_args):
  print(COOKIE_FILE)
  print()
  print("export beatport.com cookies from chrome in Netscape format and save")
  print("them there. the session lasts about a month (F11).")
  return 0


def cmd_check(_args):
  if not COOKIE_FILE.is_file():
    print(f"FAIL  no cookie file at {COOKIE_FILE}")
    print("      run `bp_cookies.py path` for what to do")
    return 1

  jar = load_netscape_cookies(COOKIE_FILE)
  print(f"cookie file  {COOKIE_FILE}")
  print(f"cookies      {len(jar)}")
  session = [name for name in jar if "session" in name.lower()]
  print(f"session-ish  {session or '(none found — is this the right domain?)'}")

  token = CookieSessionProvider().get()
  if token is None:
    print()
    print("FAIL  could not mint a bearer token.")
    print("      the session has probably expired; export the cookies again.")
    return 1

  print()
  print(f"OK    minted a bearer token, {len(token)} chars")
  print("      beatport will contribute genre, BPM and key this run.")
  return 0


def main():
  ap = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
  )
  sub = ap.add_subparsers(dest="cmd", required=True)
  sub.add_parser("path").set_defaults(func=cmd_path)
  sub.add_parser("check").set_defaults(func=cmd_check)
  args = ap.parse_args()
  raise SystemExit(args.func(args))


if __name__ == "__main__":
  main()
