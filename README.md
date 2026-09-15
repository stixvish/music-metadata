# music-metadata

1,494 AIFF files in `~/Music/library` carry tags of unknown provenance. this
resolves them from the one field that is trustworthy — the ISRC, present on
96.3% of them — through free APIs, and writes a **tagged copy**. the source tree
is never modified.

the operator is a DJ, which biases two fields above the rest: **genre**
(beatport's sub-genre, not "Dance") and **artwork** (large, square, from a
verified master).

- `SPEC.md` — what we are building, and why each decision went the way it did
- `CLAUDE.md` — how we work: style, tooling, commits
- `tasks/plan.md` — the build order · `tasks/todo.md` — the task list

## status

**milestone 5 of 6 — the gates.** `verify` now asserts G1–G11 over an output
tree and reports each one as a **measured number against its target**, not a
pass/fail bit. duplicates are classified by §11a's three policies, and the diff
screen gates `apply` behind an explicit confirmation.

| thing             | state                                                  |
| ----------------- | ------------------------------------------------------ |
| `probe`           | 1,494 files, 1,439 with ISRC — reproduces the baseline |
| `resolve`         | spotify · musicbrainz · itunes · discogs · beatport    |
| `diff` / `apply`  | tagged copies to an output tree; source untouched      |
| **`verify`**      | **G1–G11, each a measured number against its target**  |
| **duplicates**    | §11a's three classes; only class A is automatic        |
| **artwork**       | verified chain, at each album's master (up to 3000²)   |
| **genre / label** | beatport → discogs → itunes                            |
| **BPM / key**     | beatport only, key in camelot — needs a cookie         |
| review queue      | flagged tracks in the browser, grouped by gate         |
| **acquisition**   | **not built** — tier 0 is M6                           |

what is populated today: title, artist, album, album artist, release date, year,
track number, disc number, mix name, remixer, original artist, ISRC, genre,
label, artwork, and — where musicbrainz names the role — composer and
lyricist. everything else is
deliberately left empty rather than guessed: §7e's position on BPM, applied
generally.

**on BPM and key.** beatport is the only source in this stack that has them, so
coverage is zero until a session cookie exists — and honestly zero rather than
computed. §7e is explicit: rekordbox recomputes both during its own analysis and
prefers its own values, so a guessed tag buys nothing and gets trusted anyway.
key is written in **camelot** (`2A`, not `Eb Minor`), which is what rekordbox and
serato display and what harmonic mixing actually uses.

**enabling beatport.** export beatport.com cookies from chrome in Netscape
format; `uv run python tools/bp_cookies.py path` prints where they go and
`check` verifies they still mint a token. the session lasts about a month. with
no cookie, `resolve` says so and carries on.

**on artwork.** the danger is identity, not resolution: an image returned for a
track is the cover of whichever release the matcher landed on, and that is a
compilation often enough to matter. every candidate is verified against the
chosen release before its bytes are used, and the name check **rejects rather
than coerces** — searching itunes for `Calvin Harris 18 Months` returns `96
Months`, a different record, and a fuzzy match would embed its cover silently.

apple serves each album's own master, which varies: 3000² for some, 1425² for
others. the tag records what actually came back, not what was requested.

**on artist credit.** musicbrainz decides _who_ performed; the filename decides
_which of them is featured_. F53 measured why: on 13 of 398 featured tracks
musicbrainz joins the feature with `&` and it disappears, while the operator
typed `(ft. …)` deliberately. where the two name genuinely different people —
34 tracks — nothing is auto-resolved; they go to the review queue.

**on composer and lyricist.** F52 measured that musicbrainz records explicit
`composer` and `lyricist` roles for indian repertoire (10/10 works sampled) and
the role-less `writer` relation for western ones (34 of 34). a bare `writer` is
**not** promoted into `TCOM` — it says someone wrote the work, not which role
they held, and a wrong value gets trusted where a missing one does not.

## prerequisites

```sh
brew install uv ffmpeg taplo
npm install -g prettier markdownlint-cli2
```

`ffprobe` and `ffmpeg` come with the `ffmpeg` formula.

## install

```sh
uv sync
cp .env.example .env    # then add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
```

`.env` is git-ignored. **the library path needs no musicfetch token at all**
(`SPEC.md` F36/F37) — only tier 0 acquisition will, in M6.

## using it

```sh
# 1. local tag survey. no network. ~2.5 minutes for 1,494 files.
uv run music-metadata probe

# 2. resolve identities into the sidecar. spotify at 20 req/min,
#    musicbrainz at 1 req/s.
uv run music-metadata resolve --limit 20

# ...or skip tier 3 deliberately. the pipeline completes either way.
uv run music-metadata resolve --limit 20 --no-beatport

# 3. see what would change, and which source supplied each field.
uv run music-metadata diff --limit 5

# 4. write tagged copies. the source tree is never touched.
uv run music-metadata apply --out ~/Music/tagged --map library.toml

# 5. scan the map (SPEC.md §9c).
uv run music-metadata map --missing beatport
uv run music-metadata map --no-isrc
```

a real `diff`, from the worked example in `SPEC.md` §5a:

```text
*NSYNC - Bye Bye Bye.aiff
  album      'No Strings Attached (special UK edition)' -> 'No Strings Attached'  [spotify]
  date       '2000' -> '2000-01-17'  [spotify]
  track_count '' -> '12'  [spotify]
  flags: no-artwork
```

the date is **not** the chosen album's date. it is the earliest across all 34
releases the ISRC appears on (F33) — the single preceded the album by two
months, and both facts are kept.

## what gets scanned, and what comes out

The pipeline reads from several folders and writes one output tree:

```text
~/Music/library     ~/Music/beatport     ~/Music/soundcloud
        \                  |                     /
         \                 v                    /
                    ~/Music/tagged
```

`_Serato_`, `rekordbox` and `PioneerDJ` are **never scanned** — they are
another tool's data. Override with `--library A B C`.

Output filenames are rebuilt from the resolved tags and **lowercased**:

```text
XXXTENTACION - I don't even speak spanish lol (ft. …).aiff
  -> xxxtentacion - i don't even speak spanish lol (ft. …).aiff
```

macOS is case-insensitive, so lowercasing means a later fix to an artist's
capitalisation never renames the file — and never costs a relink in Rekordbox
for a track already imported. The extension is carried through unchanged; audio
is copied, never transcoded.

## duplicate handling

Three byte-identical pairs exist in the library. `apply` writes **one** copy of
each and reports the other, so G11 ("no two output files share an audio md5")
holds. The source tree is never touched.

A fourth kind is harder: the same recording acquired twice in different
formats — a Beatport `.wav` and a YouTube-derived `.aiff`. Their audio hashes
differ (one has been through a lossy step) and the store copy often has no
ISRC, so both of the usual tests miss it. These are matched on duration plus
title and **always go to the review queue** — never auto-removed, because the
duration signal alone produces false positives.

## filling in missing ISRCs

55 files carry no ISRC tag, and the ISRC is the key every other field hangs off.
The `isrc` screen in the web UI takes a YouTube link per track, reads the ISRC
from it (F19), checks it against the file's own length, and writes it to
`library.toml`:

```bash
uv run music-metadata serve      # then open /isrc
```

**A link to the official video works too.** The video and the track are separate
uploads with different ids — indistinguishable in a browser — and only the track
maps to a release. Paste the video and the track is looked up and used instead.

Nothing is written unless the duration agrees within 5s, so a mispasted link is
refused rather than tagged. The same thing from the CLI:

```bash
uv run python tools/yt_isrc.py look "https://www.youtube.com/watch?v=liZm1im2erU"
uv run python tools/yt_isrc.py fill pairs.txt    # <filename><TAB><url> per line
```

Hand-edits to `library.toml` outrank every source and survive every regenerate —
and a hand-typed ISRC is resolved _with_, not merely written, so the whole
pipeline runs against it.

## resuming a run

`resolve` caches every source's raw response separately, so a pass that stops
part-way costs nothing to resume — re-running it skips what is already cached
and picks up where it left off.

It stops on purpose in one case. Spotify enforces a **quota** as well as a rate
limit, and they are different problems: the rate limit is a rolling 30-second
window that slowing down fixes, while the quota is a budget for the whole
developer account that slowing down does nothing for. A quota 429 says so in
its body (`"reason": "QUOTA_EXCEEDED"`) and asks for hours — measured at
43,868s, 12.2h.

Waiting that out inside the run would park the pass; skipping the track would
be worse, because spotify is fetched first and a skip passes over musicbrainz,
itunes and discogs too. So the pass ends and says when to come back:

```text
error  spotify: rate-limited for 43868s (12.2h) — stopping at track 62 of 1439.
       everything fetched so far is cached; re-run after Tue 11:21 to resume.
```

Re-run the same command after that time. Nothing is lost and nothing is
re-fetched — the request count in that message is how the budget gets measured,
since Spotify does not publish it.

The map is derived from the sidecar, so an interrupted run has not lost it
either:

```bash
uv run music-metadata map --regenerate
```

## verifying a run

```sh
# capture the source tree's checksum first, so G4 can be asserted
BEFORE=$(uv run music-metadata checksum)

uv run music-metadata resolve
uv run music-metadata apply --out ~/Music/tagged
uv run music-metadata verify --out ~/Music/tagged --checksum-before "$BEFORE"
```

every gate prints what it measured beside what it wanted:

```text
PASS  G1 identity                                100.0%  (target ≥95%)
PASS  G4 non-destruction                      unchanged  (target unchanged)
PASS  G9 no cross-recording contamination              0  (target 0)
FAIL  G6 artist-credit agreement                  75.0%  (target ≥88%)
```

**G4 is asserted by checksum, never by inspection.** G9 has no tolerance —
adopting another source's ISRC is a correctness failure, not a near-miss. G3,
G5 and G10 report rather than judge, because zero beatport results and
unverifiable artwork are both normal outcomes.

## duplicates

§11a defines three classes and **only one is safely automatic**:

| class | test                             | policy                                            |
| ----- | -------------------------------- | ------------------------------------------------- |
| A     | same ISRC **and** same audio md5 | auto-resolve — byte-identical audio loses nothing |
| B     | same ISRC, different audio       | **never auto-delete** — one of the ISRCs is wrong |
| C     | duration disagrees with the ISRC | strip the ISRC, queue for review                  |

measured on this library: **3 class A, 3 class B**. one class B pair —
`INS181600966` — carries two entirely different songs, which is exactly why
"keep one" is not allowed to run unattended. deletion is always to a quarantine
directory, never `rm`.

## the web ui

the ui is the primary interface (`SPEC.md` §14). it binds loopback only.

```sh
uv run music-metadata serve
```

then open <http://127.0.0.1:8765>. the library screen lists every probed track
and can start a resolve as a background job, with progress polled — a full
resolve is over an hour and cannot be held open in an HTTP request.

the **review queue** lists every track a gate refused to guess on, grouped by
the gate that raised it — a credit musicbrainz and the filename disagree about
(G6), a track with no verified artwork (G5). §14's argument for the ui is that
these flags are worthless in a log file and valuable in a queue.

the acquire and diff screens are stubs until the data that justifies them
exists.

## where things live

| what           | where                                             |
| -------------- | ------------------------------------------------- |
| sidecar cache  | `~/.local/share/musicpipeline/sidecar.sqlite`     |
| the map        | `library.toml` in the working directory           |
| output tree    | wherever `--out` points; never the source library |
| runtime config | `~/.config/musicpipeline/`                        |

the sidecar stores **raw API responses**, not just parsed fields. a resolver fix
is replayed offline against what was already fetched instead of re-spending a
1,494-track run at 20 req/min.

## development

every check must pass before a commit, in this order:

```sh
uv run ruff format --check .
uv run ruff check .
taplo fmt --check .
uv run djlint src/music_metadata/web/templates --check
prettier --check "**/*.{css,js,json,md}"
markdownlint-cli2
uv run mypy
uv run pytest -q
```

`lefthook install` wires these to `pre-commit`. never silence a check to reach
green — see `CLAUDE.md`.

```sh
uv run pytest -q           # 547 tests, no network
uv run pytest -q -m live   # hits the real spotify api
uv run pytest -q -m slow   # probes all 1,494 files against the measured baseline
```

the pure modules — `release`, `naming`, `credit`, `artwork`, `camelot`,
`output` — are held at 99% coverage with a 90% floor. they carry the decisions
the spec argued hardest about.
