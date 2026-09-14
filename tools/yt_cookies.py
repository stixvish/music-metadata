#!/usr/bin/env python3
"""youtube cookie helper: set up, export, and verify premium audio access.

youtube rotates account cookies on any open browser tab, which silently
invalidates an exported set (SPEC.md F20). the fix is a session that is never
browsed again. the wiki suggests incognito, but incognito cookies live only in
memory and need a browser extension to export.

a dedicated chrome profile has the same never-rotated property and a real
cookie database, so it can be scripted and verified.

note: using a personal account for downloads carries a ban risk (yt-dlp wiki).

usage:
  yt_cookies.py profiles            list chrome profiles and which are logged in
  yt_cookies.py setup               create the dedicated profile and open it
  yt_cookies.py check [--source S]  probe whether premium audio is offered
  yt_cookies.py export [--source S] write cookies to the config path
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

CHROME_DIR = Path.home() / "Library/Application Support/Google/Chrome"
CONFIG_DIR = Path.home() / ".config/musicpipeline"
COOKIE_FILE = CONFIG_DIR / "youtube-cookies.txt"
PROFILE_NAME = "ytdlp"

# a track known to be published at premium quality; used only as a probe.
PROBE_URL = "https://music.youtube.com/watch?v=_026NPNnsnY"

# premium-only audio itags: 141 = AAC 256k, 774 = opus 256k.
PREMIUM_ITAGS = {"141", "774"}


def run(args, **kw):
  return subprocess.run(args, capture_output=True, text=True, **kw)


def list_profiles():
  """Yield (dir_name, display_name, has_cookie_db) for each chrome profile."""
  if not CHROME_DIR.is_dir():
    return
  for d in sorted(CHROME_DIR.iterdir()):
    if not d.is_dir() or not (d.name == "Default" or d.name.startswith("Profile")):
      continue
    name = "?"
    prefs = d / "Preferences"
    if prefs.is_file():
      try:
        name = json.loads(prefs.read_text()).get("profile", {}).get("name", "?")
      except (json.JSONDecodeError, OSError):
        pass
    yield d.name, name, (d / "Cookies").is_file()


def resolve_source(source):
  """Turn a source string into yt-dlp cookie arguments.

  `file:PATH` or a bare path reads a cookies.txt; anything else is treated as a
  chrome profile directory name.
  """
  if source is None:
    return ["--cookies", str(COOKIE_FILE)] if COOKIE_FILE.is_file() else []
  if source.startswith("file:"):
    return ["--cookies", source[5:]]
  if Path(source).is_file():
    return ["--cookies", source]
  return ["--cookies-from-browser", f"chrome:{source}"]


def probe(cookie_args):
  """Return (formats, warnings) for the probe track.

  warnings are captured deliberately: the cookie-rotation notice arrives on
  stderr and is the single most useful diagnostic (F20). never pass
  --no-warnings here.
  """
  r = run(["yt-dlp", *cookie_args, "-F", "--socket-timeout", "30", PROBE_URL])
  formats = []
  for line in r.stdout.splitlines():
    if "audio only" not in line:
      continue
    itag = line.split(maxsplit=1)[0]
    codec = "opus" if "opus" in line else ("aac" if "mp4a" in line else "?")
    rates = re.findall(r"(\d+)k", line)
    kbps = max((int(x) for x in rates), default=0)
    formats.append({"itag": itag, "codec": codec, "kbps": kbps})
  warnings = [ln for ln in r.stderr.splitlines() if "WARNING" in ln or "ERROR" in ln]
  return formats, warnings


def cmd_profiles(_args):
  rows = list(list_profiles())
  if not rows:
    print("no chrome profiles found at", CHROME_DIR)
    return 1
  print(f"{'dir':<12} {'name':<24} cookies")
  for d, name, ck in rows:
    print(f"{d:<12} {name:<24} {'yes' if ck else 'no'}")
  print()
  ded = [d for d, n, _ in rows if n == PROFILE_NAME or d == PROFILE_NAME]
  if ded:
    print(f"dedicated profile present: {ded[0]}")
  else:
    print(f"no dedicated '{PROFILE_NAME}' profile yet — run: yt_cookies.py setup")
  return 0


def cmd_setup(_args):
  print("your normal profile may work today, but youtube rotates its cookies")
  print("as you browse — `check` will start failing without warning.")
  print("a dedicated profile you never browse in does not rotate.\n")
  print("  1. chrome > profiles > add profile")
  print(f"  2. name it exactly: {PROFILE_NAME}")
  print("  3. in that profile, log in at https://music.youtube.com")
  print("  4. confirm premium is active (avatar > your account)")
  print("  5. close the window and never open that profile again\n")
  print("then verify with:  yt_cookies.py check --source <ProfileDir>")
  print("find <ProfileDir> with:  yt_cookies.py profiles")
  return 0


def cmd_check(args):
  cookie_args = resolve_source(args.source)
  if not cookie_args:
    print("no cookie source: pass --source, or create", COOKIE_FILE)
    return 2
  src = " ".join(cookie_args)
  print(f"probing with: {src}\n")
  formats, warnings = probe(cookie_args)

  rotated = any("no longer valid" in w or "rotated" in w for w in warnings)
  for w in warnings[:4]:
    print("  ", w.strip())
  if warnings:
    print()

  if not formats:
    print("FAIL  no audio formats returned")
    return 1

  best = max(formats, key=lambda f: f["kbps"])
  premium = [f for f in formats if f["itag"] in PREMIUM_ITAGS]
  print(f"{'itag':<6} {'codec':<6} kbps")
  for f in sorted(formats, key=lambda f: f["kbps"]):
    mark = "  <-- premium" if f["itag"] in PREMIUM_ITAGS else ""
    print(f"{f['itag']:<6} {f['codec']:<6} {f['kbps']:<5}{mark}")
  print()

  if premium:
    p = premium[0]
    print(f"PASS  premium audio available: itag {p['itag']} {p['codec']} {p['kbps']}k")
    return 0

  print(f"FAIL  no premium audio. best offered: itag {best['itag']} "
        f"{best['codec']} {best['kbps']}k")
  if rotated:
    print("\ncause: cookies were rotated by youtube (SPEC.md F20).")
  print("\nfix: use a dedicated profile you never browse in —")
  print("  yt_cookies.py setup")
  return 1


def cmd_export(args):
  if not args.source:
    print("export needs --source <ProfileDir>")
    return 2
  CONFIG_DIR.mkdir(parents=True, exist_ok=True)
  tmp = CONFIG_DIR / "youtube-cookies.txt.tmp"
  r = run(["yt-dlp", "--cookies-from-browser", f"chrome:{args.source}",
           "--cookies", str(tmp), "--skip-download", "--simulate",
           "--socket-timeout", "30", PROBE_URL])
  if not tmp.is_file():
    print("FAIL  no cookies written")
    for ln in r.stderr.splitlines()[:5]:
      print("  ", ln.strip())
    return 1
  # only replace a working file once the new one verifies.
  formats, _ = probe(["--cookies", str(tmp)])
  if not any(f["itag"] in PREMIUM_ITAGS for f in formats):
    print(f"FAIL  exported cookies do not grant premium audio; keeping existing "
          f"{COOKIE_FILE.name}")
    tmp.unlink(missing_ok=True)
    return 1
  shutil.move(str(tmp), str(COOKIE_FILE))
  COOKIE_FILE.chmod(0o600)
  print(f"PASS  wrote {COOKIE_FILE} (premium verified)")
  return 0


def main():
  ap = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="cmd", required=True)
  sub.add_parser("profiles").set_defaults(fn=cmd_profiles)
  sub.add_parser("setup").set_defaults(fn=cmd_setup)
  for name, fn in (("check", cmd_check), ("export", cmd_export)):
    p = sub.add_parser(name)
    p.add_argument("--source", help="chrome profile dir, or file:PATH")
    p.set_defaults(fn=fn)
  args = ap.parse_args()
  return args.fn(args)


if __name__ == "__main__":
  sys.exit(main())
