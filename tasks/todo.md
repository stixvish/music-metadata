# todo

generated from `tasks/plan.md`. each task names its spec section, its acceptance
criteria, and how to verify it. **a task is not done until its verification
passes** — "looks right" is not evidence.

every milestone is one branch and one pr (`CLAUDE.md`). checkpoints are human
review gates: stop, report real numbers, wait.

**standing rule, every milestone: `README.md` is updated in the same pr.** it
states what exists and runs _today_ — never what is planned. a milestone is not
done until the README matches it. this is the last task in each list below and
it is not optional.

---

## M0 — foundation and ui scaffold

branch `feat/foundation`

- [ ] **0.1 install the missing formatters.** `taplo`, `djlint`, `prettier` and `markdownlint-cli2`
      are in `CLAUDE.md`'s check gate and are not installed on this machine.
      **verify:** all eight checks run and report, even on an empty tree.
- [ ] **0.2 `pyproject.toml` and the `uv` project.** python ≥3.12. runtime deps
      `mutagen`, `httpx`, `pydantic>=2`, `fastapi`, `uvicorn`, `jinja2`; dev deps
      `ruff`, `mypy`, `pytest`, `pytest-cov`. ruff and mypy config copied from
      `CLAUDE.md` verbatim — 2-space indent, 88 cols, the full `select` list
      including `ANN`, `S` and `T20`, `mypy` strict on `src/`.
      **verify:** `uv sync` succeeds · `ruff check .` and `mypy src/` both pass.
- [ ] **0.3 `lefthook.yml`.** the seven checks in `CLAUDE.md`'s stated order, all
      blocking on commit.
      **verify:** a commit with a deliberate format error is rejected.
- [ ] **0.4 `src/music_metadata/output.py`** — the single output module. `T20`
      bans `print` in `src/` so the web ui can capture the same messages (§14).
      **verify:** a unit test captures emitted messages without stdout.
- [ ] **0.5 `store.py` and `schema.sql`** — the six tables of §9a: `files`,
      `recordings`, `service_ids`, `fingerprints`, `artwork`, `jobs`. unique
      indexes on `audio_md5` and on `isrc` (§11a depends on them). **raw response
      columns from day one** — §9a calls this the load-bearing decision, and
      retrofitting it costs a re-fetch of 1,494 tracks. include
      `source_version` on `recordings`.
      **verify:** round-trip test writes and reads a raw payload · the unique
      index rejects a duplicate md5.
- [ ] **0.6 `web/app.py`, `web/jobs.py`, templates and static.** fastapi, jinja2,
      htmx and alpine from a CDN, binding localhost with no auth. four routes
      stubbed (library, review, acquire, diff); library renders an empty table.
      **verify:** `uvicorn` serves the library screen · a `jobs` row can be
      written and polled through `/jobs/{id}` · `djlint` passes on templates.
- [ ] **0.7 create `README.md`.** it does not exist yet. what the project does,
      prerequisites (`uv`, `ffmpeg`, the `.env` keys actually needed), install,
      how to start the web ui, and an explicit "what is not built yet" section.
      **no command is listed that does not work.**
      **verify:** a reader following it from a clean checkout reaches a served
      library screen · `prettier --check` passes on it.

> **acceptance for M0:** the eight-check gate passes clean, `pytest` is green,
> the library screen loads in a browser, and `README.md` describes exactly that
> and nothing more.

---

## M1 — the spine: one track, resolved, tagged, visible

branch `feat/spine`. the thinnest complete path. **no second source until this
works end to end.**

- [ ] **1.1 `probe.py`** — ffprobe over the tree → path, **decoded-audio md5**
      (F44), duration, ISRC, existing tags → the `files` table.
      **verify:** reproduces `cache/audiomd5.tsv` and `cache/isrc.tsv` on all
      1,494 rows exactly, and the counts match §2 (1,494 / 1,439 / 55).
- [ ] **1.2 `sources/ratelimit.py` and `sources/base.py`** — token bucket at
      20 req/min (F8); shared httpx client with **mandatory timeouts** (ruff `S`
      catches a `requests`/`httpx` call without one).
      **verify:** a unit test proves the bucket blocks the 21st call inside a
      minute · no HTTP call anywhere lacks a timeout.
- [ ] **1.3 `sources/spotify.py`** — client-credentials auth,
      `/v1/search?q=isrc:{ISRC}&type=track&limit=10`, pydantic v2 models, **raw
      JSON persisted to `recordings`**.
      **verify:** the 8 ISRCs in §7b's table return their recorded release sets ·
      a second run makes zero API calls.
- [ ] **1.4 `release.py` (§7b)** — pure ranking: `album` > `single` >
      `compilation`, then **1-track releases LAST**, then `release_date` ASC.
      `prefer_standard_edition = true` by default.
      **verify:** all 8 rows of §7b's table · the `NAV - Never Sleep` deluxe case
      picks `4/19` not `4/20` · the `Kamariya` promo case picks `Stree` (2/4),
      not the 1-track `Kamariya (From "Stree")`.
- [ ] **1.5 `naming.py` (§7a)** — render `{Name} (ft. {Features}) [{Mix}]`; the
      mix-normalisation table; the separator style (comma between all, `&` before
      the last). **no source's title string is written verbatim.**
      **verify:** `Extended Mix`/`Extended Version` → `Extended` ·
      `Blessings - Odd Mob Remix` splits into name + `TIT3` · all three separator
      forms from §7a · `Original` is never invented where no source states it.
- [ ] **1.6 `arbitrate.py` (§7)** — the rows reachable from spotify alone, with
      **provenance recorded per field**. a hand-edited `library.toml` value
      outranks every source.
      **verify:** every written field carries a named source · a manual override
      wins and is marked `manual`.
- [ ] **1.7 `tag.py`** — mutagen ID3-on-AIFF, **only the frames in §7d**. `TOPE`
      is not written at all on non-remixes.
      **verify:** round-trip on a **copied** AIFF · **a synthetic `GEOB` frame
      survives the rewrite** (serato's beatgrids live there — `CLAUDE.md`).
- [ ] **1.8 `library_map.py` (§9b)** — generate, merge and read back
      `library.toml`, keyed by audio md5. the merge rule: the resolver never
      overwrites what it did not write.
      **verify:** a hand-edited line survives a regenerate and is marked
      `manual` · clearing a value returns that field to resolver control ·
      `taplo fmt --check` passes on the output.
- [ ] **1.9 `cli.py`** — `probe`, `resolve --limit N`, `diff`, `apply --out DIR`,
      `map` with the §9c view flags.
      **verify:** `music-metadata map --missing beatport` renders TSV · `diff`
      shows old → new per field.
- [ ] **1.10 web — library screen over real rows**, and `resolve` as a background
      job with polled progress.
      **verify:** a 20-track resolve runs from the browser and progress advances
      without holding an HTTP request open.
- [ ] **1.11 update `README.md`.** add `probe`, `resolve --limit N`, `diff`,
      `apply --out DIR` and `map` with **real example output** from the 20-track
      run. record where the output tree and `library.toml` land. state that only
      spotify-derived fields are populated so far.
      **verify:** every command shown is copy-pasteable and works today.

> ### checkpoint 1 — stop and review
>
> 20 tracks resolved, diffed, applied to an output tree.
>
> - **G4 asserted by checksum:** `~/Music/library` is byte-identical before and
>   after. not inspected — asserted.
> - show the full diff for `*NSYNC - Bye Bye Bye` and confirm it matches §5a's
>   worked example: album `No Strings Attached`, track 1/12, date `2000-01-17`
>   (the earliest across all 10 releases, not the chosen release's date).

---

## M2 — identity and credit

branch `feat/credit`

- [ ] **2.1 `sources/musicbrainz.py`** — 1 req/s, `/ws/2/isrc/{ISRC}` with
      `inc=artist-credits+artist-rels+work-rels`, then the work lookup for
      composer and lyricist. **`currently busy` is a retry, not a miss** (F30).
      **verify:** a 503 retries and then succeeds · `Not Found` falls through to
      the title parse and flags the track, rather than erroring.
- [ ] **2.2 `credit.py` (§6)** — the joinphrase split: everything before the
      element whose `joinphrase` matches `/feat\.|ft\.|with/i` is main,
      everything after is featured.
      **verify:** the `David Guetta - Little Bad Girl` case from §6 splits to
      main `David Guetta`, featured `Taio Cruz, Ludacris`.
- [ ] **2.3 filename parser as a first-class source.** §6 ranks it **second**,
      above spotify and itunes, because it is the operator's own curation.
      **verify:** `Main - Title (ft. Featured)` parses on a sample drawn from the
      418 files that encode a feature.
- [ ] **2.4 G6 cross-validation.** musicbrainz and the filename agree → accept
      automatically. disagree → **flag for review, never guess.**
      **verify:** an induced disagreement produces a review row, not a value.
- [ ] **2.5 indian-scope performers-only rule (§7a, F38).** fires on
      `ISRC[:2] == "IN"` **or** a genre match on
      bollywood/indian/punjabi/telugu/tamil. **scoped, never global.**
      **verify:** scope selects ~167 tracks · a western track credited to a
      producer (`Metro Boomin`, `Internet Money`) keeps them in `TPE1` ·
      composers move to `TCOM` only inside scope.
- [ ] **2.6 composer and lyricist globally (§7d).** the indian rule governs who
      is excluded from `TPE1`, not who gets a `TCOM`.
      **verify:** a western track with a musicbrainz work composer gets `TCOM`.
- [ ] **2.7 review queue screen (§14)** — flagged tracks grouped by gate, each
      row showing proposed beside current, the source, and accept/reject/edit.
      writes back to `library.toml`.
      **verify:** accepting a row updates `library.toml` and the row disappears.
- [ ] **2.8 update `README.md`.** artist credit, composer and lyricist now
      populate; document the review queue screen and the indian-scope rule in a
      sentence. record the **measured** G6 agreement rate from checkpoint 2.

> ### checkpoint 2 — stop and review
>
> G6 measured across all 418 featured tracks. target ≥95% agreement, but
> **report the real rate** — §6 says the disagreement rate is reported, not
> assumed. review a sample of the disagreements in the browser.

---

## M3 — completeness: itunes, artwork, discogs

branch `feat/artwork`

- [ ] **3.1 `sources/itunes.py`** — `/lookup` plus search on **both** entities.
      free, no auth.
      **verify:** `trackNumber`, `discNumber`, `trackCount`, `discCount` return
      for the §5a track.
- [ ] **3.2 `artwork.py` — the F37 chain, not §7c's.** `entity=album` →
      `entity=song` filtered on `collectionName` → spotify's ~640px image → none,
      keep existing art and flag. **no musicfetch in v1.**
      **verify:** all four rows of §7c's measured table reach 3000×3000, with
      `18 Months` resolving via `entity=song`.
- [ ] **3.3 resolution upgrade and step-down.** rewrite the trailing
      `/{N}x{N}bb.jpg` on `artworkUrl100` to 3000²; on a non-200 or a short read
      step 3000 → 1400 → 600 rather than failing the track.
      **verify:** a simulated non-200 at 3000 lands at 1400, and the track still
      completes.
- [ ] **3.4 the name check rejects, never coerces.** searching
      `Calvin Harris 18 Months` returns `96 Months` — a different record.
      **verify:** that exact query is **rejected** and the chain moves on. no
      fuzzy ratio, no "closest result wins".
- [ ] **3.5 `sources/discogs.py`** — label (F46, via `/releases/{id}`) and a
      `styles[0]` genre fallback (F47). two calls per track, so it runs **only
      when beatport has no listing**.
      **verify:** two calls, not more · discogs is skipped when beatport matched.
- [ ] **3.6 G5 flags into the review queue.** when no candidate verifies, keep
      the existing embedded art and flag — **never** substitute an unverified
      image.
      **verify:** a track with no verifying candidate keeps its original bytes
      and appears in the queue.
- [ ] **3.7 update `README.md`.** artwork and label now populate. record the
      measured G5 counts per candidate tier and the real output-tree size. note
      that v1 needs **no musicfetch token** (F36/F37).

> ### checkpoint 3 — stop and review
>
> G5 reported: count accepted per candidate tier, count flagged, measured
> against §7c's 4/4-at-3000² baseline. confirm the ~3-4 GB output estimate holds
> at library scale.

---

## M4 — beatport, isolated and optional

branch `feat/beatport`

- [ ] **4.1 `sources/bp_auth.py`** — pluggable `TokenProvider`.
      `CookieSessionProvider` now (F11: a month-long cookie mints 10-minute
      tokens); `OAuthClientProvider` reads `.env` when OQ-5 lands.
      **verify:** a token is minted and refreshed on expiry · a missing cookie
      degrades to "no beatport", never a crash.
- [ ] **4.2 `sources/beatport.py`** — `?isrc=` as a fast path, then artist +
      name + mix-name search. F22: ISRC succeeds on originals and **fails on all 9
      `Blessings` remixes**.
      **verify:** an original resolves by ISRC · a remix resolves by search ·
      zero results is a normal outcome, not an error.
- [ ] **4.3 `camelot.py`** — promote `tools/camelot.py` into `src/`; move its
      24-code table into `tests/`. an unparseable key returns `None` and `TKEY`
      is left empty (§7f).
      **verify:** all 24 codes unique and covered · the four published anchors
      (1A = A♭ minor, 1B = B major, 8A = A minor, 8B = C major) · enharmonics
      and case variants · garbage returns `None`.
- [ ] **4.4 G3 duration split.** within ±5s → all fields transfer. outside ±5s →
      **only** `genre`, `sub_genre`, `label` and remixer identity; `bpm`, `key`,
      `length` and beatport's `isrc` are **discarded**.
      **verify:** a >5s-apart match transfers genre but not bpm.
- [ ] **4.5 G9 no cross-recording contamination.** the written ISRC always equals
      the file's own.
      **verify:** asserted in `verify`, and a test proves beatport's ISRC is
      never adopted.
- [ ] **4.6 prove tier 3 is optional.** §5 claims beatport is the most likely
      component to break and the one nothing depends on. **test the claim.**
      **verify:** a run with beatport disabled completes green, with genre
      falling back to discogs and then itunes.
- [ ] **4.7 update `README.md`.** document beatport setup (cookie provider, and
      that it is **optional** — the pipeline completes without it), the camelot
      `TKEY` notation, and the **honest** BPM/key coverage from checkpoint 4.

> ### checkpoint 4 — stop and review
>
> G3 class fractions reported (same-recording vs different-edit vs no match). a
> beatport-disabled run completes. BPM and key coverage stated **honestly** per
> §7e — good for dance, poor for hip-hop, near-zero for indian repertoire, and
> **left empty rather than guessed**.

---

## M5 — gates, duplicates, and the full run

branch `feat/verify`

- [ ] **5.1 `verify.py` — G1 through G11.** each gate reports a real number
      against its target, not a pass/fail bit.
      **verify:** run against the M1 output tree; every gate produces a count.
- [ ] **5.2 G10 ISRC trust.** compare local duration to the duration the ISRC's
      recording claims (F40). >±5s means the ISRC does not describe this file:
      strip it, route to tier-0 identity, queue for review. **no field resolved
      from an untrusted ISRC is ever written.**
      **verify:** the known class-C case from `cache/dupisrc.txt` is caught.
- [ ] **5.3 duplicates (§11a), three classes and three policies.** class A (same
      ISRC **and** same md5) is the **only** automatic one. **deletion is always
      to a quarantine directory, never `rm`.**
      **verify:** the 6 known duplicates in `cache/dupaudio.txt` and
      `cache/dupisrc.txt` classify into A/B/C correctly · nothing is deleted
      outright.
- [ ] **5.4 G11 no duplicates in the output tree.**
      **verify:** no two output files share an audio md5.
- [ ] **5.5 diff and apply screen**, with apply behind an explicit confirmation.
      **verify:** apply cannot be triggered without confirming.
- [ ] **5.6 the full run — 1,494 tracks.** hours at 20 req/min, so it runs as a
      background job.
      **verify:** the run completes, is resumable, and a re-run costs zero API
      calls (§9a).
- [ ] **5.7 update `README.md` to v1.** the full command set, the **real gate
      numbers G1–G11** from the full run, the duplicate-quarantine behaviour, and
      a clear statement that acquisition (§10) is not built yet.

> ### checkpoint 5 — v1 complete
>
> full library tagged to an output tree. **every gate G1–G11 reported with real
> numbers against its target.** review queue worked through in the browser.
> `~/Music/library` byte-identical to where it started.

---

## M6 — tier 0 acquisition (post-v1)

branch `feat/acquire`. **not in v1 scope** — listed so the sequencing is on the
record.

- [ ] **6.1** resolve the `MUSICMATCH_TOKEN` / musicfetch naming question in
      `.env` (see `tasks/plan.md`, spec issue 2). blocks 6.2.
- [ ] **6.2 `sources/musicfetch.py`** — `/url` → ISRC (F19). this is the one
      thing nothing else in the stack does.
- [ ] **6.3 G8 premium-audio precondition.** `tools/yt_cookies.py check` before
      **every batch**, asserting itag 141 or 774. a per-run precondition, not a
      setup step — validity is transient (F20).
- [ ] **6.4 exact itag, never `bestaudio`** (F48). `bestaudio` degrades
      silently; an exact itag fails loudly.
- [ ] **6.5 abort the entire batch when cookies die mid-run** (§10a). on the
      first format failure, re-probe: probe fails → abort everything, nothing
      written; probe passes → skip this one track and continue.
- [ ] **6.6 §11b `- Topic` test — necessary, not preferred.** F43 measured a
      lyric video at 279s against a 278s release, so **duration does not catch
      it**. `categories` and `media_type` appear on both and must not be used.
- [ ] **6.7 G7 acquisition identity.** admit a download only when it carries an
      ISRC **and** that ISRC's resolved duration is within ±5s.
- [ ] **6.8 ISRC dedup before download** (§11a) — a duplicate costs one API call,
      not a file.
- [ ] **6.9 convert to AIFF** (`pcm_s16be`, 44.1 kHz) per OQ-6 — for tag support,
      not audio quality. the 5.4× storage cost is accepted deliberately.
- [ ] **6.10 retire the deferred tail** — the 55 no-ISRC files and the 7 beatport
      WAVs, using the same machinery (§10, §11).
- [ ] **6.11 update `README.md`.** document `acquire`, the premium-cookie
      prerequisite and its `tools/yt_cookies.py` setup path, the batch-abort
      behaviour, and the fact that acquisition — unlike the library path —
      **does** require a musicfetch token.
