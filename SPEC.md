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

**F11 — beatport auth: a month-long cookie mints 10-minute tokens.**
captured live from a logged-in session. `www.beatport.com/api/auth/session`
returns a nextauth session containing a bearer token:

```
token.accessToken      1156 chars
token.tokenType        bearer
token.expiresIn        599 seconds          ← ~10 minutes
scope                  user:dj openid app:prostore
session.expires        2026-10-14           ← ~1 month
```

**this corrects the earlier "grab a token by hand" plan.** a copied token dies
in 10 minutes and a full pass takes ~72 (F8), so a manual token cannot cover
even one run. but the *session cookie* lasts a month and the endpoint re-mints a
fresh token on every call — verified by repeated calls across the capture.

the session cookie is **httpOnly**, so it is not readable from page JavaScript
(`document.cookie` shows only consent and analytics cookies). it must be
exported from chrome's cookie store, the same way `youtube-cookies.txt` already
is, and lives in `~/.config/musicpipeline/beatport-cookies.txt` — never the repo.

**the auth design is therefore:** export the cookie once per month → call
`/api/auth/session` to mint a bearer token → re-mint every ~8 minutes during a
run. no `authorization_code` implementation, no runtime client_id discovery,
no swagger-ui scraping. this is simpler *and* more durable than the
`beets-beatport4` flow.

**F12 — beatport returns the ISRC, so matches verify exactly.**
`/v4/catalog/tracks/{id}/` includes an `isrc` field. comparing it to the ISRC we
sent musicfetch turns F9's fuzzy-match worry into a cheap exact check:

```
17 beatport ids from the musicfetch sample
16/17 ISRC exact match
 1/17 mismatch — "MEDUZA & Khalid - Weekend"
```

the ~6% mismatch rate is real, and it is **detectable rather than silent**. G3
is rewritten accordingly: compare ISRCs, and on mismatch discard the beatport
record and fall back to apple. no artist/title/duration heuristics needed.

**F13 — `sub_genre` is almost always null; `genre` is the field that matters.**

```
sub_genre populated:  1 of 17  (6%)  — only "Mainstage" → "Big Room"
```

**this corrects the original premise.** the plan assumed beatport sub-genres
would supply a fine taxonomy; measured, they are absent for all but genuine
electronic releases. beatport's top-level `genre` is still clearly better than
apple's for DJ use:

| beatport | apple, same tracks |
|---|---|
| `Hip-Hop` (7) · `Pop` (4) · `Dance / Pop` (2) · `Trap / Future Bass` (2) · `Mainstage` (1) · `R&B` (1) | `Hip-Hop/Rap` · `Pop` · `Dance` · `R&B/Soul` |

`Mainstage` and `Trap / Future Bass` are distinctions apple collapses into
`Dance`. so beatport stays the primary genre source — reading `sub_genre` when
present and `genre` otherwise, rather than depending on `sub_genre`.

**F14 — beatport supplies BPM and key for 100% of matches.**
`bpm` and `key` were populated on **17 of 17** records (e.g. `125` / `Eb Minor`).
these were not in the original field list and are the two fields a DJ library
most wants. they are added to §7 as first-class outputs.

`mix_name` is also populated and carries real signal — observed values include
`Original Mix`, `Clean`, `Intro`, `feat. NAV`, and
`Tall Boys 100-130 Transition`. it is the most likely explanation for the F12
mismatch and is the key to OQ-3 (remix identity).

**F15 — the official API is the same API; only token acquisition differs.**
read from the partner portal and `api.beatport.com/v4/docs/` while logged in
(2026-09-14). three grant flows exist — `authorization_code`, `password`, and
`client_credentials` — and **all three require a client id and secret issued by
beatport**:

```
client_id={client_id provided}
redirect_uri={redirect_uri shared with us, can not be different}
"if you do not have authentication credentials please reach out to your
 account manager to receive them"
```

`account.beatport.com/o/applications/` redirects to plain account settings —
**there is no self-service app registration.** credentials require a business
relationship, and that is a request the operator must make, not a technical step.

**the official token is materially better when it exists:**

| | web-session token (F11) | official OAuth token |
|---|---|---|
| TTL | `expires_in: 599` (~10 min) | `expires_in: 36000` (**10 hours**) |
| refresh | re-mint from cookie | `refresh_token` |
| credential | month-long httpOnly cookie | client id + secret |
| approval | none | account manager |

a 10-hour token covers a full 72-minute pass outright.

**but note what this does *not* change.** the token captured in F11 is a valid
bearer for `api.beatport.com` — it already returned `/v4/catalog/tracks/{id}/`
successfully across 17 records. **we are not working around the official API; we
are already calling it.** the endpoints, the fields, the ISRC verification and
the genre data in F12–F14 are all the official API's, obtained with a token the
official identity service issued. only the *acquisition* differs.

**design consequence: the token provider is pluggable, the rest of tier 3 is
not.** two implementations against one interface:

```
TokenProvider.get() -> bearer
  ├── CookieSessionProvider   works today, no approval  (F11)
  └── OAuthClientProvider     drop-in once credentials arrive (F15)
```

endpoints, field mapping, ISRC gating and rate limiting are identical either
way. **this unblocks tier 3 now and makes adopting official credentials a
one-class swap**, so the build is never waiting on beatport's business process.

**F16 — the library's ISRCs were *resolved*, not carried from source.**
`~/Music/.staging` holds **1,517 M4A** files named by youtube video id
(`_026NPNnsnY.m4a`) with **no metadata at all** — sampled 11, zero carried a
title tag; the only tags are `major_brand`, `encoder` and friends. the 1,494
AIFFs were produced from these. **every ISRC in the library is therefore
second-hand**, written by the earlier process the operator distrusts.

**F17 — but those ISRCs check out.** comparing each resolved ISRC's musicfetch
title against the filename across the 20-track sample: **18 agree outright**,
and both apparent misses are correct matches where apple appends soundtrack
context — `Roke Na Ruke Naina` vs `Roke Na Ruke Naina (From "Badrinath Ki
Dulhania")`. effectively **20/20**. the ISRC-first design in §5 stands; the
titles will need a `(From "…")` normalisation decision, not the ISRCs.

**F18 — yt-dlp returns structured music metadata, but not identity.**
youtube music `- Topic` channels carry real fields:

```
track         Silk and Cologne (Spider-Verse Remix)
artists       ['EI8HT', 'Offset']      ← flattened, same defect as spotify (§6)
album         METRO BOOMIN PRESENTS SPIDER-MAN: ACROSS THE SPIDER-VERSE
release_date  20230602
```

there is **no ISRC, no genre, no track or disc number**, and `artists` reproduces
exactly the main/featured flattening §6 exists to fix. useful as corroboration,
insufficient as a source.

**F19 — musicfetch `/url` recovers the ISRC from a youtube URL directly.**
this is the finding that makes acquisition cheap. feeding
`music.youtube.com/watch?v={id}` to `/url` returns a fully resolved track:

```
8 of 8 staging video ids → ISRC recovered   (100%)
4 of 8 also carried a beatport link
```

**no fingerprinting, no text search, no edition ambiguity.** `fpcalc`
(chromaprint) and a text-search path were both probed and work, but neither is
needed: text search on the itunes API returned three near-identical editions for
one track — standard, deluxe, and *instrumental* — which is precisely the
mis-selection `/url` avoids by resolving identity rather than guessing it.
fingerprinting stays documented as the fallback for audio that `/url` cannot
resolve.

**F20 — premium audio is reachable, and validity is transient.**
the operator holds youtube premium. **itag 141 (AAC-LC 256k) downloads
successfully**, verified end-to-end:

```
downloaded today, itag 141 : aac LC 44100Hz 257516 bps  md5 2364cdfb…
existing .staging file      : aac LC 44100Hz 257516 bps  md5 2364cdfb…
raw audio stream md5        : bae6e47a…  ← identical on both
```

**byte-identical, container and audio stream.** this proves the existing library
was acquired at itag 141 and that a new pipeline reproduces it exactly. itag 774
(opus 293k) is also offered.

**but the same probe failed earlier in the same session.** a first run returned
only 151k opus, with yt-dlp reporting:

```
WARNING: [youtube] The provided YouTube account cookies are no longer valid.
They have likely been rotated in the browser as a security measure.
```

youtube rotates account cookies on browser activity, so **cookie validity is a
transient runtime property, not a configuration fact.** expiry timestamps do not
reveal it — the stored `youtube-cookies.txt` showed 50 live cookies, 0 expired,
with `SID`, `SAPISID` and `__Secure-1PSID` all present, and still yielded no
premium format.

two consequences:

- **never run the probe with `--no-warnings`.** the rotation notice is the one
  diagnostic that explains a silent quality drop, and suppressing it cost real
  time here.
- **a profile you browse in will rotate.** a dedicated chrome profile that is
  logged in once and never browsed again holds the same never-rotated property
  as the wiki's incognito procedure
  ([yt-dlp wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)),
  while keeping a real cookie database that can be scripted — incognito cookies
  are in-memory only and need a browser extension to export.

`tools/yt_cookies.py` implements this: `profiles`, `setup`, `check`, `export`.
`check` exits non-zero when no premium itag is offered, and `export` **refuses
to overwrite a working cookie file with one that fails verification.**

the yt-dlp wiki notes that using a personal account for downloads carries a ban
risk. the operator has accepted this.

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
- genre is beatport's, where a **ISRC-verified** beatport match exists (F12),
  and the apple genre otherwise.
- **BPM and key** are populated from beatport wherever a verified match exists
  (F14) — not in the original ask, but free and DJ-critical.
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
| **genre** | **beatport `sub_genre` if present, else `genre`** (F13) | musicfetch `genres[0]` | existing tag |
| artwork | apple master at configured size (F5) | existing embedded art | — |
| label | musicfetch `label` | — | — |
| bpm | **beatport `bpm`** (F14, 100% coverage) | — | — |
| key | **beatport `key`** (F14, 100% coverage) | — | — |
| mix name | beatport `mix_name` | filename bracket | — |
| ISRC | the file's own tag | musicfetch `isrc` | — |

## 8. gates — a stage is not done until these pass

- **G1 identity.** ≥95% of the 1,439 ISRC tracks resolve to a musicfetch result.
  measured baseline: 20/20.
- **G2 completeness.** ≥98% of resolved tracks carry all eight required fields.
- **G3 beatport ISRC agreement.** a beatport record is accepted only when its
  `isrc` equals the ISRC we looked up (F12). on mismatch the record is
  **discarded and genre falls back to tier 1**. measured baseline: 16/17.
  the mismatch rate is reported by `verify`, never assumed.
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

## 10. acquisition — tier 0, a front-end not a second pipeline

the operator wants to keep adding tracks from youtube music rather than buying
every one on beatport. F19 makes this a small addition rather than a parallel
system:

```
yt-dlp  →  audio file + youtube video id
                    │
                    ▼
        musicfetch /url  (F19)  →  ISRC
                    │
                    ▼
        ┌───────────────────────────────┐
        │  §5 tiers 1-3, entirely       │
        │  unchanged                    │
        └───────────────────────────────┘
```

**acquisition ends the moment an ISRC exists.** everything downstream — genre,
artwork, artist credit, track and disc number, BPM and key — is the pipeline
already specified. tier 0 adds one API call and one new failure mode, not a
second architecture.

**it also retires two v1 non-goals.** the same `/url` and fingerprint machinery
resolves the **55 no-ISRC library files** and the **7 beatport WAVs** (§11).
they stay out of v1 by sequencing, not because they need different tooling.

**gate G8 — acquisition audio quality.** before any batch, `acquire` runs the
`tools/yt_cookies.py check` probe and asserts a premium itag (141 or 774) is
offered. if only 130k AAC / 151k opus is available the run **aborts** rather
than downloading (F20). quality degradation must never be silent — and because
validity is transient, this is a **per-run precondition, not a setup step**.

**gate G7 — acquisition identity.** a downloaded track is only admitted to the
library once it carries an ISRC *and* that ISRC's resolved duration is within
±5s of the downloaded audio. a `/url` result that disagrees on duration is a
wrong match, and youtube is full of edits, sped-up versions and live cuts that
resolve confidently to the studio recording. measured baseline: 8/8 resolved.

**OQ-6 — lossy source, lossless container.** the source is **AAC at ~257 kbps**
(measured across `.staging`, and reachable only with valid premium cookies —
F20); the library is AIFF. the conversion costs **5.4×**
storage — 9.5 GB → 51.9 GB measured — and **adds no quality**, since nothing is
recoverable that the AAC encoder discarded. the existing 1,494 files are already
converted and are not in scope to revisit. the open question is **new**
acquisitions: keep AIFF for consistency with the current library and DJ-app
behaviour, or keep M4A and convert only what gets played out. needs a decision.


## 11. non-goals (v1)

- **the 55 no-ISRC files** — deferred by sequencing only. §10 tier 0 resolves
  them with the same machinery; they are 3.7% of the library and can wait.
- **the 7 beatport WAVs** — deferred. RIFF `INFO` has no standard slot for album
  artist, disc number, ISRC, or embedded art; tagging them reliably means
  converting to AIFF, which is a separate decision (see OQ-6).
- **cloudflare evasion** — F6. if the beatport API path fails, the genre tier
  degrades to apple; we do not build a challenge solver.
- cue points, beatgrids, crates — owned by the DJ apps.
- playlist and crate provenance.

## 12. project structure, commands, testing

```
src/music_metadata/
  cli.py            # entry point
  acquire.py        # tier 0 — yt-dlp + /url identity (§10)
  probe.py          # ffprobe → local tag facts
  sources/
    musicfetch.py   # tier 1 — identity + service ids
    itunes.py       # tier 2 — track/disc number
    musicbrainz.py  # tier 2 — artist-credit roles (§6)
    beatport.py     # tier 3 — genre/bpm/key
    bp_auth.py      # pluggable TokenProvider: cookie | oauth (F15)
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
music-metadata acquire URL           # tier 0 — download + resolve identity
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

## 13. open questions

- **OQ-1 artwork size.** 1400² is free and needs no URL rewriting; 3000² costs
  ~4.3 GB across the library and relies on undocumented substitution (F5); 4500²
  costs ~9.4 GB. rekordbox and serato display far smaller. **recommendation:
  3000², with 1400² as the no-rewrite fallback.** needs a decision.
- ~~**OQ-2 beatport auth.**~~ **resolved by live capture** — F11. session-cookie
  → token minting is verified working against the operator's account.
- **OQ-5 official beatport credentials.** worth requesting from an account
  manager — a 10-hour token with refresh beats re-minting every 8 minutes. it is
  a business request, not a blocker: `CookieSessionProvider` ships meanwhile and
  the swap is one class (F15).
- **OQ-4 tag shape for features.** option A (feature in title) or B (feature in
  artist) — see §6. **recommendation: A**, it sorts correctly in rekordbox and
  matches what itunes already does for most releases.
- **OQ-3 remix identity.** does an ISRC on a remix resolve to the remix or the
  original? F9 says beatport matching is fuzzy; the library is full of remixes.
  measure before trusting beatport genre on them.
