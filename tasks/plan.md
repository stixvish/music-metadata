# implementation plan

**status:** approved 2026-09-14 · not started
**see also:** `SPEC.md` (what we are building) · `CLAUDE.md` (how we work) ·
`tasks/todo.md` (the task list this plan generates)

## context

`SPEC.md` is complete: phase 0 research is done, 50 findings are probed live and
cited, and every open question except OQ-5 (beatport official credentials) is
decided. there is no implementation yet — the repo holds the spec, `CLAUDE.md`,
two working scripts in `tools/`, and measured baselines in `cache/`.

the problem the code has to solve: 1,494 AIFF files in `~/Music/library` carry
tags of unknown provenance. 1,439 of them (96.3%) carry an ISRC, which is the
key that unlocks every other field. the build turns that spec into a pipeline
that resolves those ISRCs through free APIs, arbitrates the results by a written
precedence table, and writes a tagged **copy** — the source tree is never
touched.

**three decisions taken when this plan was approved:**

- **greenfield.** every module here is written against `SPEC.md`. no code is
  ported in from elsewhere.
- **the web ui is scaffolded from the first slice**, not bolted on at the end.
  §14 makes it the primary interface; no command ships CLI-only.
- **v1 is the existing library.** tier 0 acquisition (§10, §10a, §11b, gates
  G7/G8) is milestone 6, after the library is tagged.

## spec issues to resolve before coding

three contradictions found while reading. `CLAUDE.md` says to surface these
rather than paper over them.

1. **§7c's artwork chain contradicts F37.** §7c lists candidate A as
   musicfetch's `appleMusic.id`. F37 is the later operator decision and removes
   **musicfetch from tier 1 entirely**, replacing candidate A with a second
   itunes query: `entity=song` on the track name, filtered on `collectionName`.
   F37 records that this reproduces musicfetch's results byte for byte on 4/4
   probes.

   **the consequence is a good one: v1 needs no musicfetch at all.** no
   `sources/musicfetch.py`, no token, no $100/month plan — F36 says so
   explicitly. musicfetch returns only in milestone 6, where `/url` is genuinely
   unique. this plan builds the F37 chain and treats §7c as stale.

2. **`.env` holds `MUSICMATCH_TOKEN`; the spec says musicfetch throughout.**
   either the key is misnamed or it is for a different service. since v1 no
   longer needs it this blocks nothing, but resolve it before milestone 6.

3. **stale "needs a decision" text.** §6 says OQ-4 "needs a decision" and §7a
   says OQ-7 "needs confirmation", but §13 marks both decided. §13 and §7a's
   tables are authoritative: title shape is `{Name} (ft. {Features}) [{Mix}]`;
   separator is comma throughout with `&` before the last. a docs commit should
   delete the stale sentences.

**also: three formatters in `CLAUDE.md`'s check gate are not installed** —
`taplo`, `djlint`, `prettier`. task 0.1 installs them; the gate cannot run today.

## dependency graph

```
        ┌─────────────────────────────────────────────┐
        │ M0  scaffold · store.py · output.py · web   │
        └───────────────────┬─────────────────────────┘
                            │
      ┌─────────────────────┼──────────────────┐
      ▼                     ▼                  ▼
  probe.py            ratelimit.py         web/jobs.py
  (ffprobe,           + sources/base.py    (progress)
   md5, duration)           │
      │                     ▼
      │              sources/spotify.py ──────► release.py  (§7b, pure)
      │                     │                        │
      │                     │        ┌───────────────┤
      │                     ▼        ▼               ▼
      │              musicbrainz.py  itunes.py   naming.py (§7a, pure)
      │                     │        │               │
      │                     ▼        ▼               │
      │                credit.py  artwork.py         │
      │                  (§6)      (§7c/F37)         │
      │                     │        │               │
      │              discogs.py      │               │
      │              beatport.py ─► camelot.py       │
      │                     │        │               │
      └─────────────────────┴────────┴───────────────┘
                            ▼
                     arbitrate.py (§7, pure)
                            ▼
          library_map.py (§9b)  ──►  tag.py (§7d)  ──►  verify.py (§8)
```

**pure modules — no network, no I/O, tested exhaustively:** `release.py`,
`naming.py`, `credit.py`, `camelot.py`, `arbitrate.py`. these hold every decision
the spec argued hardest about, and they are the cheapest to get right. `mypy`
runs `disallow_untyped_defs` on them and coverage is gated at 90%.

**`cache/` is a ready-made oracle.** `audiomd5.tsv` and `isrc.tsv` hold all 1,494
measured rows; `dupaudio.txt` and `dupisrc.txt` hold the known duplicates;
`dursample.tsv` holds durations. `probe.py` is correct when it reproduces them
exactly. the probe tables in §5a, §7b and §7c become fixtures.

## milestones

each milestone is one branch, one pr, squash-merged (`CLAUDE.md`). checkpoints
are human review gates — stop, show numbers, wait.

### M0 — foundation and ui scaffold

`pyproject.toml` per `CLAUDE.md` verbatim (2-space ruff, 88 cols, the full
`select` list including `ANN`/`S`/`T20`, mypy strict on `src/`), `uv` project,
`lefthook.yml` running the seven checks in order, prettier and djlint config.

`src/music_metadata/output.py` — the single output module. `T20` bans `print` in
`src/` precisely so the web ui can capture the same messages; every module writes
through this from the first line of code, not retrofitted.

`store.py` and `schema.sql` — the six tables of §9a (`files`, `recordings`,
`service_ids`, `fingerprints`, `artwork`, `jobs`) with the unique indexes on
`audio_md5` and `isrc` that §11a's dedup depends on. **raw response columns from
day one** — §9a calls storing raw payloads the load-bearing decision, and
retrofitting it means re-fetching 1,494 tracks.

`web/app.py` (fastapi), `web/jobs.py`, `templates/base.html`, `static/`, htmx and
alpine from a CDN. binds localhost, no auth. four routes stubbed, library screen
rendering an empty table.

### M1 — the spine: one track, resolved, tagged, visible

the thinnest complete path. no second source until this works end to end. tasks
1.1–1.10 in `tasks/todo.md`.

> **checkpoint 1.** 20 tracks resolved, diffed, applied to an output tree. **G4
> asserted by checksum** — every source byte unchanged. show the diff for
> `*NSYNC - Bye Bye Bye` and confirm it matches §5a's worked example.

### M2 — identity and credit

`sources/musicbrainz.py` (1 req/s; **`currently busy` is a retry, not a miss** —
F30), `credit.py` implementing §6's joinphrase split, the filename parser as a
**first-class** source (§6 ranks it second, above spotify and itunes), and G6
cross-validation: agree → accept, disagree → **flag, never guess**.

the indian-scope performers-only rule (§7a, F38) — `ISRC[:2] == "IN"` or a genre
match, 167 tracks. **scoped, never global**; applying it to western repertoire
would strip Metro Boomin and Calvin Harris out of `TPE1`. composer and lyricist
(`TCOM`/`TEXT`) are written wherever musicbrainz supplies them, globally (§7d).

**review queue screen** — the flags now exist, so the screen that justifies the
ui (§14) gets built here, grouped by gate.

> **checkpoint 2.** G6 measured across the 418 featured tracks — target ≥95%
> agreement. report the real disagreement rate; §6 says it is reported, not
> assumed. review a sample of disagreements in the browser.

### M3 — completeness: itunes, artwork, discogs

`sources/itunes.py` (lookup plus both search entities). `artwork.py` — **the F37
chain, not §7c's**: `entity=album` → `entity=song` filtered on `collectionName` →
spotify's ~640px image → none, keep existing and flag. upgrade `artworkUrl100`
to 3000², stepping 3000 → 1400 → 600 on failure.

**the name check rejects, it never coerces.** searching `Calvin Harris 18 Months`
returns `96 Months`, a different record. no fuzzy ratio, no "closest wins": a
loose match embeds the wrong cover with no signal that anything went wrong.

`sources/discogs.py` — label (F46) and a `styles[0]` genre fallback (F47), two
calls, **only when beatport has no listing**.

> **checkpoint 3.** G5 reported: count per candidate tier and count flagged,
> against the 4/4-at-3000² baseline in §7c. confirm the ~3-4 GB output estimate.

### M4 — beatport, isolated and optional by construction

`sources/bp_auth.py` — pluggable `TokenProvider`, `CookieSessionProvider` now and
`OAuthClientProvider` behind OQ-5. `sources/beatport.py` — ISRC as a fast path,
then artist + name + mix-name search (F22: ISRC succeeds on originals and fails
on all 9 remixes). `camelot.py` — promoted from `tools/`, already correct and
documented; its 24-code table moves into `tests/`.

**G3's duration split is the whole point:** within ±5s all fields transfer;
outside ±5s **only** `genre`, `sub_genre`, `label` and remixer identity — `bpm`,
`key`, `length` and beatport's `isrc` are discarded. **G9 asserts the written
ISRC always equals the file's own**; adopting beatport's is a correctness
failure, not a metadata improvement.

§5 says tier 3 is the component most likely to break and the one nothing depends
on. *test that claim:* a run with beatport disabled must complete, with genre
falling back to discogs and then itunes.

> **checkpoint 4.** G3 class fractions reported. a beatport-disabled run
> completes green. BPM and key coverage stated honestly per §7e — good for dance,
> near-zero for indian repertoire, and **left empty rather than guessed**.

### M5 — gates, duplicates, and the full run

`verify.py` asserting G1–G11. G10 ISRC trust (local duration against the duration
the ISRC claims; >±5s → strip, flag, queue for tier 0). §11a's three duplicate
classes — **only class A is automatic**, and deletion is always to quarantine,
never `rm`. diff and apply screen with explicit confirmation.

then the real run: 1,494 tracks. at 20 req/min this is hours, not minutes, so it
runs as a background job — which is why §14 requires one.

> **checkpoint 5 — v1.** full library tagged to an output tree. every gate G1–G11
> reported with real numbers against its target. review queue worked through in
> the browser.

### M6 — tier 0 acquisition, post-v1

`acquire.py`, `sources/musicfetch.py`, and `tools/yt_cookies.py` wired in as the
G8 per-run precondition. §11b's `- Topic` test is **necessary, not preferred** —
F43 measured a lyric video at 279s against a 278s release, so duration does not
catch it. G7 admits a download only on ISRC and duration agreement. a cookie
failure mid-batch **aborts the entire batch** (§10a); identity needs no cookies,
so nothing already resolved is lost. this milestone also retires the 55 no-ISRC
files and the 7 beatport WAVs.

## verification

**per task:** `pytest` unit tests against recorded fixtures — every probe
response in §3 becomes a fixture, and `cache/*.tsv` is the oracle for `probe.py`.
pure modules (`release`, `naming`, `credit`, `camelot`, `arbitrate`) are tested
without network at 90% coverage.

**per milestone, before the pr:** `README.md` is updated in the same pr, stating
what exists and runs **today** — never what is planned (`CLAUDE.md`, working
agreements). a README describing unbuilt features is read as a status report and
lies. then the seven checks of `CLAUDE.md` in order —
`ruff format --check .` · `ruff check .` · `taplo fmt --check .` · `djlint` ·
`prettier --check` · `mypy src/` · `pytest -q`. **never silence a check to get to
green**; a `# noqa` or a skip added to make a commit pass is a defect, not a fix.

**end to end, at each checkpoint:**

1. `music-metadata probe` → compare counts to §2's measured baseline
   (1,494 / 1,439 / 55). a mismatch means the probe is wrong, not the baseline.
2. `music-metadata resolve --limit 20` → `diff` → check against §5a's worked
   example, which records what every call actually returned.
3. `apply --out /tmp/out` → `verify --out /tmp/out` → gate numbers.
4. **G4 every time:** checksum `~/Music/library` before and after. the source
   tree is never mutated, and this is asserted rather than inspected.
5. browser: run the same operation from the ui and confirm it reports the same
   result. the CLI and the ui are two front doors to one sqlite store (§14), so a
   divergence there is a bug.

**one live integration test**, marked and excluded from the default run (§12).
