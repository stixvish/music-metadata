# music-metadata — spec

**status:** phase 0 research complete · all external claims probed live
**last updated:** 2026-09-14
**see also:** `CLAUDE.md` (how we work). this file is *what we are building*.

---

## 1. problem

1,494 AIFF files in `~/Music/library` carry tags of unknown and inconsistent
provenance. they are good enough to play and wrong enough to distrust. the
goal is a library where every field traces to a named source that a label or
distributor actually curated — and where re-running the resolver improves the
whole library for free.

the operator is a DJ. that biases two fields above the rest: **genre** (beatport
sub-genre is the useful taxonomy, not "Dance") and **artwork** (large, square,
from the best available master).

## 2. measured baseline (not estimated)

run `ffprobe` over the tree; these are counts, not guesses.

| fact | value |
|---|---|
| `~/Music/library` | 1,494 AIFF, flat, `Artist - Title.aiff` |
| carry ISRC (`TSRC`) | **1,439 — 96.3%** |
| no ISRC | **55 — 3.7%** |
| `~/Music/beatport` | 7 WAV, RIFF `INFO` tags only |
| artwork embedded today | 1200×1200 MJPEG, `Cover (front)` |

the no-ISRC tail skews bollywood/punjabi and remix edits — the population
*least* likely to exist on beatport. it is deferred (§9), not solved by the
beatport path.

## 3. verified findings (evidence base)

every claim below was probed live on 2026-09-14. uncited external claims are
bugs (`CLAUDE.md`).

**F1 — musicfetch returns links, not per-service metadata.**
probed `api.musicfetch.io/isrc`. each service entry is exactly `{id, link}`:

```json
"beatport":   { "id": "23984398", "link": "https://beatport.com/track/…" }
"appleMusic": { "id": "1851368386", "link": "https://music.apple.com/…" }
```

there is no per-service genre, artwork, or tracklist. **"beatport genre from
musicfetch" is not achievable** — musicfetch supplies the beatport *track id*,
and the genre requires a second fetch. this invalidates the original one-API
design and is the reason §5 has three tiers instead of one.

**F2 — the top-level `genres` array is already apple-shaped.**
observed values across a 20-track sample: `Hip-Hop/Rap` (9), `Pop` (4),
`Dance` (4), `Bollywood`+`Indian` (3), `R&B/Soul`, `House`, `Alternative`,
`Soundtrack`. these are itunes genre strings. **the "fall back to itunes genre"
tier is therefore free** — it arrives in the same response as identity.

**F3 — musicfetch does not return track or disc number.**
the full key set is `type, name, image, duration, isrc, isExplicit, previewUrl,
releaseDate, label, genres, copyright, services, artists, albums`. `totalTracks`
exists on the album; the track's own position does not. two of the eight
requested fields are simply absent.

**F4 — the free itunes Lookup API supplies exactly the missing fields.**
`itunes.apple.com/lookup?id={appleMusic id}` — no auth, no quota — returns
`trackNumber: 7`, `discNumber: 1`, `trackCount: 17`, `discCount: 1`,
`primaryGenreName`, `releaseDate`, `collectionName`. the `appleMusic.id` from
F1 is the join key. this closes F3 at zero cost.

**F5 — artwork: the real ceiling is 4500×4500, reached by URL substitution.**
measured against the `mzstatic` base URL:

| request | actual | bytes |
|---|---|---|
| `600x600bb.jpg` | 600² | 116 KB |
| `1400x1400bb.jpg` | 1400² | 618 KB |
| `3000x3000bb.jpg` | 3000² | 2.9 MB |
| `5000x5000bb.jpg` | **clamps to 4500²** | 6.3 MB |
| `100000x100000bb.jpg` | HTTP 400 | — |

musicfetch hands over a **1400×1400** URL with no substitution required. note
the itunes Lookup response carries only `artworkUrl30/60/100` — there is no
`artworkUrl3000` field on this endpoint, so any size above 100 is obtained by
rewriting the URL, which is undocumented and ToS-gray. see §11 OQ-1.

**F6 — cloudflare fronts the *web* host only, not the API host.**
`GET beatport.com/track/…` → **HTTP 403**, `<title>Just a moment...</title>`.
but `api.beatport.com` is a different origin and is **not** cloudflare-fronted:

```
api.beatport.com/v4/catalog/tracks/23984398/   HTTP 401  server: istio-envoy
api.beatport.com/v4/docs/                      HTTP 200
api.beatport.com/v4/auth/o/token/  (empty POST) HTTP 400
```

401 not 404 means the resource is real and musicfetch's `beatport.id` addresses
it. 400 not 403 means the token endpoint is live and simply wants a body.
`server: istio-envoy` and the absence of any `cf-*` header confirm no cloudflare
in front. **there is no challenge to solve on the path we actually need** — the
cloudflare problem belongs to the HTML site, and we are not using the HTML site.

**F7 — v4 auth works through the operator's own account.**
access is partner-gated with no public client-credentials flow
([oauth-api.beatport.com](https://oauth-api.beatport.com/), checked 2026-09-14).
the maintained [`beets-beatport4`](https://github.com/Samik081/beets-beatport4)
plugin uses the `authorization_code` grant with the `client_id` belonging to
beatport's own swagger-ui frontend, discovered at runtime from
`api.beatport.com/v4/docs/` rather than hardcoded. it exposes **main genre,
sub-genre, or both** — precisely the field this project exists to get right.
tokens do not auto-refresh; expiry means re-authenticating.

the operator holds a paid beatport account. **this is an authenticated JSON API
call as yourself, not scraping** — no HTML parsing, no markup to break, no
challenge to defeat. it is strictly more durable than the HTML path and is the
plan of record.

**F8 — rate limits are gentler in practice than documented.**
published Starter is 6 req/min ([musicfetch.io](https://musicfetch.io/) pricing,
checked 2026-09-14). measured: **20 sequential requests at 1 req/s, all HTTP
200, zero 429s.** the 7-day trial is capped at 5,000 requests — 3.3× the whole
library, so the entire job fits inside the trial. the operator is on the **business plan: 150k requests,
20 req/min**. we **respect the published limit rather than the measured one** —
the limiter is a token bucket at 20/min, not 1/s. a full 1,439-track pass is
then ~72 minutes, and resolution is cached so it is paid once.

**F9 — non-spotify service links are search-derived, not ISRC-verified.**
musicfetch documents that it resolves the ISRC on spotify, then *searches* other
services for matching tracks. the beatport link is therefore a fuzzy match and
may point at a different mix of the same title. **beatport-sourced fields must
be verified before they are trusted** (§7 G3), not written blind.

**F10 — beatport coverage is high but not universal.**
20-track sample: **17/20 (85%) carry a beatport link; 20/20 (100%) carry apple
Music.** all three misses were bollywood. subject to F9.

## 4. goals

- every tagged field traces to a named source, recorded per track.
- genre is beatport's sub-genre where a *verified* beatport match exists, and
  the apple genre otherwise.
- **featured artists are distinguished from main artists** rather than flattened
  into one list (§6).
- artwork is the largest apple master we are willing to embed (§11 OQ-1).
- title, artist, album, album artist, disc number, track number, year, and
  release date are populated for every resolved track.
- the source library is **never mutated**; output is a new tree (§8).
- resolution is idempotent and re-runnable: improving the resolver and re-running
  re-tags everything without re-fetching what is cached.

## 5. architecture — three tiers, because F1 forced it

```
  ISRC (from file tag)
        │
        ▼
  ┌───────────────────────────────────────────────┐
  │ tier 1 · musicfetch /isrc          [PAID]     │
  │ identity · apple genre · artwork url          │
  │ releaseDate · label · album · artists · UPC   │
  │ → appleMusic.id ─┐        → beatport.id ─┐    │
  └──────────────────┼──────────────────────┼────┘
                     ▼                      ▼
  ┌──────────────────────────┐  ┌───────────────────────────┐
  │ tier 2 · itunes Lookup   │  │ tier 3 · beatport v4      │
  │ [FREE, no auth]          │  │ [gated — own account]     │
  │ trackNumber · discNumber │  │ sub-genre · bpm · key      │
  │ trackCount · discCount   │  │ MUST be verified (F9/G3)  │
  └──────────────────────────┘  └───────────────────────────┘
                     └──────────┬───────────┘
                                ▼
                    arbitration (§7) → sidecar → tag writer
```

tier 3 is **optional and isolated behind an adapter**. if beatport auth breaks,
it returns nothing, genre falls back to tier 1, and the pipeline still completes.
this is the single most likely component to break and it is the one nothing else
depends on.

## 6. artist credit — the featured-artist problem

**the complaint, quantified.** spotify (and therefore musicfetch's `artists[]`)
flattens every contributor into one list with no role. measured on real tracks:

| file | musicfetch `artists[]` | correct reading |
|---|---|---|
| `Arizona Zervas - OH MY LORD (ft. 24kGoldn)` | `['Arizona Zervas', '24kGoldn']` | main + **feature**, indistinguishable |
| `Internet Money - Options (ft. 24kGoldn)` | `['Internet Money', '24kGoldn']` | main + **feature**, indistinguishable |

**418 of 1,494 files (28%)** encode a feature in the filename, and 196 more
carry multiple *main* artists. this is not an edge case.

**musicbrainz solves it structurally.** its `artist-credit` array carries an
explicit `joinphrase` per element, so the boundary is machine-readable rather
than inferred:

```
David Guetta - Little Bad Girl (ft. Taio Cruz & Ludacris)
  [('David Guetta', ' feat. '), ('Taio Cruz', ' & '), ('Ludacris', '')]
   ^^^^^^^^^^^^^ main        ^^^ the boundary    ^^^^^^^^^^ features
```

everything before the element whose `joinphrase` matches `/feat\.|ft\.|with/i`
is a **main** artist; everything after is **featured**. no string parsing of a
title, no guessing.

**itunes is not reliable for this** — it is inconsistent about where the feature
lives:

| track | `artistName` | `trackName` |
|---|---|---|
| Dua Lipa - Levitating | `Dua Lipa` | `Levitating (feat. DaBaby)` — in the title |
| Arizona Zervas - OH MY LORD | `Arizona Zervas & 24kGoldn` — flattened | `OH MY LORD` |

both shapes occur, so itunes alone cannot be trusted to separate the roles. it
is still useful as *corroboration* when the feature appears in `trackName`.

**resolution order for artist credit:**

1. **musicbrainz `artist-credit` joinphrases** — structural, unambiguous.
   coverage is not total: 1 of 5 sampled ISRCs returned no recording.
2. **the filename** — `Main - Title (ft. Featured)`. this is the operator's own
   curation and it agreed with musicbrainz on **every case where both were
   present**. it is a first-class source here, not a last resort.
3. **itunes `trackName`** — extract a trailing `(feat. …)` when present.
4. **musicfetch `artists[]`** — order only, roles unknown. last resort.

**cross-validation gate (G6).** when musicbrainz and the filename agree, the
credit is accepted automatically. when they disagree, the track is **flagged for
review rather than guessed**. the disagreement rate is reported by `verify`, not
assumed.

**OQ-4 — tag shape.** the roles are now known; how they are written is a
separate decision:

| option | `artist` | `title` | `album artist` |
|---|---|---|---|
| A — feature in title | `Dua Lipa` | `Levitating (feat. DaBaby)` | `Dua Lipa` |
| B — feature in artist | `Dua Lipa ft. DaBaby` | `Levitating` | `Dua Lipa` |

A keeps artist columns clean and sorts correctly in rekordbox; B surfaces the
feature in the deck display. **needs a decision** (§12).


## 7. field precedence

| field | 1st | 2nd | 3rd |
|---|---|---|---|
| title | musicfetch `name` | itunes `trackName` | filename parse |
| artist | **musicbrainz artist-credit** (§6) | filename parse | itunes `artistName` |
| album | musicfetch `albums[0].name` | itunes `collectionName` | — |
| album artist | **main artists only** (§6) | musicfetch `albums[0].artists` | artist |
| track number | **itunes `trackNumber`** (F3) | — | — |
| disc number | **itunes `discNumber`** (F3) | — | — |
| release date | musicfetch `releaseDate` | itunes `releaseDate` | — |
| year | derived from release date | — | — |
| **genre** | **beatport sub-genre (verified)** | musicfetch `genres[0]` | existing tag |
| artwork | apple master at configured size (F5) | existing embedded art | — |
| label | musicfetch `label` | — | — |
| bpm / key | beatport | — | — |
| ISRC | the file's own tag | musicfetch `isrc` | — |

## 8. gates — a stage is not done until these pass

- **G1 identity.** ≥95% of the 1,439 ISRC tracks resolve to a musicfetch result.
  measured baseline: 20/20.
- **G2 completeness.** ≥98% of resolved tracks carry all eight required fields.
- **G3 beatport agreement.** a beatport match is accepted only if artist and
  normalised title agree and duration is within ±3s. below threshold the match
  is **discarded and genre falls back to tier 1** (F9). agreement rate is
  reported, never assumed.
- **G6 artist-credit agreement.** musicbrainz and the filename agree on the
  main/featured split for ≥95% of the 418 featured tracks. disagreements are
  queued for review, never auto-resolved.
- **G4 non-destruction.** the source tree's bytes are unchanged after any run.
  asserted by checksum, not by inspection.
- **G5 artwork.** every output file embeds art at or above the configured floor.

## 9. write path — new tree, source never touched

the operator's decision: emit a fully tagged copy, leave `~/Music/library`
untouched.

```
resolve  → sidecar (SQLite + per-track JSON), no audio touched
review   → `diff` shows every proposed field change, old → new
apply    → write tagged copies to the output tree
verify   → re-probe the output; assert G1–G5
```

resolution and tagging are **separate commands**. the API is slow and rate-
limited; tagging is fast and local. caching resolution means the tag writer can
be re-run freely while the resolver runs once. AIFF tags are written as ID3;
frames we do not own (serato's `GEOB` beatgrids and cue points) are preserved,
never rewritten.

## 10. non-goals (v1)

- **the 55 no-ISRC files** — deferred. they need text search with a confidence
  gate, and they are 3.7% of the library.
- **the 7 beatport WAVs** — deferred. RIFF `INFO` has no standard slot for album
  artist, disc number, ISRC, or embedded art; tagging them reliably means
  converting to AIFF, which is a separate decision.
- **cloudflare evasion** — F6. if the beatport API path fails, the genre tier
  degrades to apple; we do not build a challenge solver.
- cue points, beatgrids, crates — owned by the DJ apps.
- playlist and crate provenance.

## 11. project structure, commands, testing

```
src/music_metadata/
  cli.py            # entry point
  probe.py          # ffprobe → local tag facts
  sources/
    musicfetch.py   # tier 1 — identity + service ids
    itunes.py       # tier 2 — track/disc number
    musicbrainz.py  # tier 2 — artist-credit roles (§6)
    beatport.py     # tier 3 — genre, pluggable, failure-isolated
    ratelimit.py    # token bucket, 20/min (F8)
  credit.py         # §6 main vs featured split
  arbitrate.py      # §7 precedence
  artwork.py        # fetch + size policy (§11 OQ-1)
  tag.py            # ID3-on-AIFF writer, preserves foreign frames
  store.py          # sidecar cache
tests/{unit,integration}/
```

python ≥3.12 · `uv` · `mutagen` · `httpx` · `pydantic` v2 · `ruff` · `mypy` ·
`pytest`. google style, 2-space indent.

```
music-metadata probe                 # local tag survey, no network
music-metadata resolve [--limit N]   # tiers 1-3 → sidecar
music-metadata diff                  # proposed changes, old → new
music-metadata apply --out DIR       # write tagged copies
music-metadata verify --out DIR      # assert G1-G5
```

**testing.** every source has recorded-fixture unit tests — the probe responses
in this spec become the first fixtures. arbitration is pure and tested without
network. the tag writer is tested round-trip on a copied AIFF, including an
assertion that a synthetic `GEOB` frame survives. one integration test hits the
live APIs, marked and excluded from the default run.

## 12. open questions

- **OQ-1 artwork size.** 1400² is free and needs no URL rewriting; 3000² costs
  ~4.3 GB across the library and relies on undocumented substitution (F5); 4500²
  costs ~9.4 GB. rekordbox and serato display far smaller. **recommendation:
  3000², with 1400² as the no-rewrite fallback.** needs a decision.
- **OQ-2 beatport auth.** confirm the `beets-beatport4` credential flow works
  with the operator's account before tier 3 is scheduled. if it fails, tier 3 is
  cut and genre is apple-only — the pipeline still ships.
- **OQ-4 tag shape for features.** option A (feature in title) or B (feature in
  artist) — see §6. **recommendation: A**, it sorts correctly in rekordbox and
  matches what itunes already does for most releases.
- **OQ-3 remix identity.** does an ISRC on a remix resolve to the remix or the
  original? F9 says beatport matching is fuzzy; the library is full of remixes.
  measure before trusting beatport genre on them.
