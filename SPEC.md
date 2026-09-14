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

**F17 — those ISRCs came from spotify, and they check out.** the operator
confirms the library's ISRCs were originally taken from spotify, which explains
why they identify the **streaming** release rather than the beatport one (F22). comparing each resolved ISRC's musicfetch
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

**F21 — every remix carries its own ISRC.** confirmed against the 10 `Blessings`
variants in the library: 10 distinct ISRCs → **10 distinct musicfetch results**,
each naming its own remixer. remix identity is therefore *free* — it falls out of
the ISRC and needs no fuzzy title matching.

```
GBARL2500591  Blessings                      (original)
GBARL2501117  Blessings - CamrinWatsin Remix
GBARL2501127  Blessings - Odd Mob Remix
…             10 of 10 distinct
```

**F22 — beatport supports exact ISRC lookup, but the streaming and beatport
releases carry *different* ISRCs.** `/v4/catalog/tracks/?isrc={ISRC}` does work
and returns `count: 1` on an exact hit. but matching the library against beatport
this way returns **0 of 9** for the `Blessings` remixes, while matching on
artist + mix name returns **9 of 9**:

| remix | library ISRC | beatport ISRC |
|---|---|---|
| CamrinWatsin | `GBARL2501117` | `GBARL2501120` |
| Malugi | `GBARL2501118` | `GBARL2501121` |
| Airwolf Paradise | `GBARL2501119` | `GBARL2501122` |
| HUGEL, Adam Trigger & Casa Mata | `GBARL2501124` | `GBARL2501129` |
| MistaJam | `GBARL2501125` | `GBARL2501130` |
| Will Clarke | `GBARL2501126` | `GBARL2501131` |
| Odd Mob | `GBARL2501127` | `GBARL2501132` |
| Schak | `GBARL2501128` | `GBARL2501133` |
| COASTR. | `GBARL2501139` | `GBARL2501140` |

**ISRC-only matching is therefore wrong for precisely the tracks that matter
most** — dance remixes, where beatport is the only source with a useful genre.
an earlier revision of this spec made ISRC the sole beatport key; that was a
mistake and is corrected here.

**F23 — the two releases are different recordings, not duplicate registrations.**
measured durations settle it:

| remix | library | beatport | delta |
|---|---|---|---|
| Airwolf Paradise | 203s | 289s | +86s |
| CamrinWatsin | 226s | 336s | +110s |
| COASTR. | 223s | 330s | +107s |
| Malugi | 161s | 241s | +80s |
| MistaJam | 166s | 303s | +137s |
| Odd Mob | 189s | 272s | +83s |
| HUGEL, Adam Trigger & Casa Mata | 158s | 293s | +135s |

the library holds the **short streaming edits**; beatport holds the **extended
versions**. the separate ISRCs are correct — these are genuinely different
recordings of the same work.

**this splits beatport's fields into two classes:**

- **work-level, safe to copy across the edit boundary:** `genre`, `sub_genre`,
  `label`, `remixers`, and the mix identity. a remix's genre does not change
  between its radio edit and its extended version.
- **recording-level, must NOT be copied when durations disagree:** `bpm`, `key`,
  `length`, `catalog_number`, `isrc`. writing beatport's 330s extended-mix BPM
  onto a 223s radio edit is a silent factual error.

**gate G3 is rewritten accordingly** — duration decides which class transfers,
rather than accepting or rejecting the whole record.

a related catch: the one no-ISRC `Blessings` file in the library is **330s**,
exactly matching beatport's `Extended Mix` (`GBARL2500592`, 330s). duration alone
identifies it. the same trick is worth trying across the 55 no-ISRC files (§10).

**F23a — in dance music the extended mix is the primary release.** the radio
edit is the derived, shortened version, not the other way round. beatport's
catalogue reflects this: it stocks the extended and remix versions and generally
not the radio cut. two consequences:

- `Extended` is **not** a variant marker to be de-prioritised; for a DJ library
  it is the preferred version.
- **the library currently holds the wrong versions.** all nine `Blessings`
  remixes are streaming edits 80-137 seconds shorter than the beatport release.
  nothing in the tagging pipeline can fix that — it is an **acquisition**
  concern, recorded as OQ-8.

**F24 — beatport's data model already encodes the remixer rule.**
`mix_name` and `remixers` are separate fields, and `remixers` is empty exactly
where it should be:

```
Blessings / "Extended Mix"      remixers: []              ← not a remix
Blessings / "Max Styler Remix"  remixers: ["Max Styler"]  ← a remix
```

but `remixers` is **sparsely populated**: across 15 `Blessings` tracks only
`Cassian` and `Max Styler` carried it; the other thirteen — including every
remix in the library — returned an empty array despite an unambiguous
`mix_name`. **`mix_name` is reliable, `remixers` is not.** the remixer is
therefore parsed from `mix_name` (§7a) and beatport's `remixers` is used only to
confirm it.

beatport's `bpm` is not always trustworthy either: `Odd Mob Remix` is reported
at **67 bpm**, a half-time detection error on a 130-ish track.

**F25 — the library's existing tag convention is already close to the target.**
a remix in the library today carries:

```
title         Blessings [Odd Mob Remix]
TPE4          Odd Mob              ← remixer
TIT3          Odd Mob Remix        ← mix name
artist        Calvin Harris, Clementine Douglas & Odd Mob
album_artist  Calvin Harris & Clementine Douglas
```

and the original carries **no `TPE4`/`TIT3` at all** — correct. apple and spotify
instead use a `" - {X} Remix"` suffix on `name`, so their titles must be parsed
into title + mix name before writing (§7a).

**F26 — the `(From "…")` suffix is a *compilation* artefact, and spotify's ISRC
search exposes every release a recording appears on.**
`GET /v1/search?q=isrc:{ISRC}&type=track` returns one entry per release. for
`INS181700238` (Arijit Singh — Roke Na Ruke Naina) it returns **ten**:

```
[single     ] 2017-02-14 trk 2/5   Badrinath Ki Dulhania      | Roke Na Ruke Naina
[compilation] 2017-06-07 trk 5/20  Love Forever With Arijit…  | Roke Na Ruke Naina (From "Badrinath Ki Dulhania")
[compilation] 2018-02-06 trk 2/20  Arijit Singh: Love Songs   | Roke Na Ruke Naina (From "Badrinath Ki Dulhania")
…  nine compilations, every one suffixed
```

**the movie soundtrack release carries the clean title; only the compilations
add the `(From "…")` context** — they need it because the album gives no other
clue. so the suffix is not a bollywood convention to strip, it is a signal that
the *wrong release* was chosen. picking the right release removes it for free.

**F27 — release preference: `album` > `single` > `compilation`, earliest first.**
"earliest non-compilation" was the obvious rule and it is **wrong**: for
`USJI10000001` (\*NSYNC — Bye Bye Bye) the earliest non-compilation is a
**1-track single**, which would set `track 1/1` and discard the album entirely.
the album release is the better attribution:

```
[single     ] 2000-01-17 trk 1/1   Bye Bye Bye           ← earliest, but 1/1
[album      ] 2000-03-21 trk 1/12  No Strings Attached   ← correct
[compilation] 2005-10-25 …         Greatest Hits         ← plus 7 more
```

the type-ordered rule is correct on all four probes:

| ISRC | chosen release | why |
|---|---|---|
| `USJI10000001` | `No Strings Attached` (album, 1/12) | album beats the 1/1 single |
| `USUG12509635` | `ODYSSEY` (album, 7/19) | album beats same-day single |
| `INS181700238` | `Badrinath Ki Dulhania` (single, 2/5) | no album exists; soundtrack wins, clean title |
| `GBARL2501127` | `Blessings — The Remixes (Part 2)` (single, 4/6) | only release |

this single policy fixes **album, album artist, track number, disc number and
title cleanliness across the whole library** — it is not a bollywood special
case. it also explains the earlier itunes edition ambiguity (standard / deluxe /
instrumental): those are release-selection failures, not identity failures.

**two traps recorded.** spotify's `tracks.total` reads **0** on `isrc:` searches
while `items` is fully populated — count `items`, never trust `total`. and
`limit=50` returns `400 Invalid limit` on this endpoint (10 works); the error
body parses as valid JSON with no `tracks` key, so a naive parser reports "no
results" instead of an error. **every API helper must check for an `error` key
before reading results.**

**F28 — musicbrainz separates performers from composers; spotify cannot.**
in bollywood the composer is credited as an "artist" on spotify, and **position
is not a signal** — the composer appears first on some releases and last on
others:

```
Lat Lag Gayee   spotify artists[]: ['Benny Dayal', 'Shalmali Kholgade', 'Pritam']   ← composer last
Badtameez Dil   spotify artists[]: ['Pritam', 'Benny Dayal', 'Shefali Alvares', …]  ← composer first
Jee Karda       spotify artists[]: ['Sachin-Jigar', 'Divya Kumar']                  ← composers first
```

musicbrainz resolves the roles in **two hops**. the recording gives performers
and a link to the work; the work gives composer and lyricist:

```
/ws/2/isrc/INT101202571?inc=artist-credits+artist-rels+work-rels
   artist-credit : Benny Dayal & Shalmali Kholgade      ← Pritam already excluded
   vocal         : Benny Dayal
   vocal         : Shalmali Kholgade
   performance   : → work fe49ff82-…

/ws/2/work/fe49ff82-…?inc=artist-rels
   composer      : Pritam
   lyricist      : Mayur Puri                            ← not in spotify's list at all
```

**two things fall out.** musicbrainz's `artist-credit` *already* excludes
composers, so it is the correct source for `artist` with no filtering needed —
the same field that solves the featured-artist split in §6. and the work hop
recovers a **lyricist spotify never reported**.

coverage is partial: `Jee Karda` returned a `performance` link but **no `vocal`
relations**, so role typing cannot be relied on universally — `artist-credit`
is the load-bearing field and `vocal` rels are corroboration.

operational notes: musicbrainz asks for **1 request/second** with a real
User-Agent, and returned `"The MusicBrainz web server is currently busy"` on one
of three calls here — **retry with backoff is required, not optional.** at two
hops per track a full pass is ~48 minutes, so work-level lookups are cached and
run as a second pass rather than inline.

**F29 — spotify exposes no credit roles; the usable signal is the title.**
the credits panel in the spotify app (songwriters, producers, performed by) is
**not in the web API** — `GET /tracks/{id}` returns `artists[]` described only as
"the artists who performed the track", with no role field and no writer or
producer data ([developer.spotify.com, checked 2026-09-14](https://developer.spotify.com/documentation/web-api/reference/get-track)).

what *is* usable is `track.name`, which carries the feature explicitly:

```
Sweet Nothing (feat. Florence Welch)   artists: ['Calvin Harris', 'Florence Welch']
Body & Soul (feat. Biig Piig)          artists: ['Emotional Oranges', 'Biig Piig']
```

**the tempting heuristic — `track.artists` minus `album.artists` — must not be
used to assign roles.** it fails in two measured ways:

```
Lat Lag Gayee   album.artists: ['Pritam']          diff: ['Benny Dayal', 'Shalmali Kholgade']
                                                   ← the COMPOSER is the album artist;
                                                     the diff is the actual vocalists
Lunar           album.artists: ['David Guetta']    diff: ['AFROJACK']
                                                   ← a co-headline collaboration,
                                                     not a feature
```

on bollywood it **inverts** performer and composer; on collaborations it demotes
a co-main artist to a feature. the diff is kept as a weak corroborating hint and
is never decisive.

**F30 — musicbrainz coverage is good, and the earlier "miss" was a server error.**
sampled 30 ISRCs across the library at 1 req/s with retry:

```
resolved   28 / 30   (93%)
not found   2 / 30   — Kamariya (INS181801821), Desperado (SGB502383473)
```

both failures are genuine `"error": "Not Found"`, and both are regional
(indian/singaporean registrants). **`Calvin Harris — Sweet Nothing` resolves
correctly** to `Calvin Harris feat. Florence Welch`; an earlier revision of this
spec recorded it as a coverage gap, which was wrong — it was a transient
`"currently busy"` response mistaken for a miss. **a busy response and a miss
must never be conflated**: the parser distinguishes `error: Not Found` from
`currently busy`, and only the former counts as absent.

**F31 — a musicbrainz miss does not mean a bad ISRC.** both ISRCs musicbrainz
returned `Not Found` for resolve cleanly everywhere else:

```
INS181801821  musicfetch: Kamariya (From "Stree")   spotify: 10 releases
SGB502383473  musicfetch: Desperado / RAGHAV, Tesher  spotify: 1 release
```

so the library's second-hand ISRCs are sound (consistent with F17) and the gap
is **musicbrainz's catalogue**, concentrated in regional repertoire — indian and
singaporean registrants here. the §6 fallback chain covers it: spotify resolved
both, and `Kamariya`'s spotify title carries the `(From "Stree")` suffix that
§7b's release selection then removes.

this also means **`artist` role separation (F28) is unavailable for these
tracks** — no musicbrainz recording means no `vocal` relations and no work hop,
so composer and lyricist cannot be recovered and `artist` falls back to
spotify's flattened list. for bollywood specifically that is the worst case,
since it is exactly where composers pollute `artists[]`. the affected tracks are
**flagged for review rather than silently accepted** (G6).

**F32 — musicfetch's `appleMusic.id` points at an arbitrary release, so track
and disc numbers must come from the *chosen* release.** measured on
`USJI10000001` (\*NSYNC — Bye Bye Bye):

```
musicfetch appleMusic.id  1741747057
  itunes lookup   album='Beach Beats'          trk=138/150  disc=1/1   ← a 150-track compilation
  spotify (§7b)   album='No Strings Attached'  trk=1/12     disc=1     ← correct
  library today   album='No Strings Attached…' trk=1        disc=1
```

**`138/150` is what F4's design would have written.** the appleMusic id musicfetch
returns is whichever release its matcher landed on, frequently a compilation —
`Beach Beats` here, `Naacho Naacho - Party Songs` for `Kamariya`. iTunes has no
ISRC search, so the *set* of apple releases cannot be enumerated to pick a better
one.

**spotify's track object carries both `track_number` and `disc_number`**, on the
release §7b deliberately selected. so track and disc come from spotify, and
**iTunes is demoted** to what it is still uniquely good for:

- **artwork** — the 3000×3000 mzstatic URL (F5)
- **genre fallback** — `primaryGenreName`
- corroboration of title and date

this removes the last dependency on an unvetted release id.

**F33 — release date: the recording's earliest, not the chosen album's.**
these differ, and the difference is large enough to matter:

| ISRC | chosen release | spotify earliest | itunes | musicbrainz |
|---|---|---|---|---|
| `USJI10000001` | 2000-03-21 | **2000-01-17** | 2000-01-11 | n/a |
| `GBARL1201392` | 2012-10-29 | **2012-10-11** | 2012-10-11 | 2012-04-16 |
| `INS181801821` | 2018-08-22 | **2018-08-09** | 2018-08-09 | n/a |
| `USUG12509635` | 2026-02-05 | **2026-02-05** | 2026-02-06 | 2026-02-05 |

per operator decision the tags split:

- **`date` / `year`** — the **minimum release date across every release carrying
  the ISRC**, i.e. when the recording first appeared.
- **`album`, `album artist`, `track`, `disc`** — from the **chosen release**
  (§7b).

spotify is primary for the earliest date because it is the only source that
enumerates every release for an ISRC. the others corroborate but cannot lead:
**iTunes** reports only its one release (and was a day later on the illenium
track — a territory artefact), and **musicbrainz `first-release-date`** was
absent on 2 of 4 and returned **2012-04-16** for a track released in October
2012, six months early. musicbrainz is therefore corroboration only, and a
disagreement greater than 60 days is **flagged, not averaged**.

**F34 — musicfetch's artwork is the artwork of *its* release, which is often a
compilation.** for `USJI10000001` musicfetch returns a 1400×1400 image whose URL
carries UPC `196872030730` — **`Beach Beats`**, a stock beach photograph. the
correct `No Strings Attached` cover is UPC `012414170224`. verified by md5 and
by eye; they are unrelated images.

```
musicfetch image   …/196872030730.jpg   md5 26b1e50c…   Beach Beats (beach photo)
correct album art  …/012414170224.jpg   md5 d8a4f911…   No Strings Attached
currently embedded 1200×1200            md5 69fd3106…   No Strings Attached ✓
```

**the library's existing artwork is already correct.** taking artwork from
musicfetch — as an earlier revision of this spec specified — would have
**actively degraded** the library, swapping real album covers for compilation
stock art at higher resolution. a bigger wrong image is worse than a smaller
right one.

**artwork must come from the release chosen in §7b**, not from the track-level
image. the path:

```
§7b picks the release via spotify  →  album name + artist
  ↓
itunes /search  term="{artist} {album}"  →  collectionId for that album
  ↓
artworkUrl100 → substitute 3000×3000 (F5)
```

confirmed working end to end: the `No Strings Attached` URL upgrades to
**3000×3000, 2.2 MB**.

**F35 — itunes *search* does enumerate releases; only the lookup-by-id is
single-release.** `GET /search?term=…&entity=song` returned **11 distinct
releases** of `Bye Bye Bye`:

```
No Strings Attached          1/12   2000-01-17   ← the album
Bye Bye Bye - Single         1/1    2000-01-11   ← the single
The Essential *NSYNC         9/17   2000-01-11
Greatest Hits                1/12   2000-01-11
…plus workout compilations and a soundtrack
```

so iTunes *can* be release-selected, by text rather than ISRC. the catch is that
text search also returns **different recordings** — a
`Bye Bye Bye (Rock) [feat. Cody Carson]` single and a `Lyle, Lyle, Crocodile`
soundtrack entry appear in the same result set. spotify's `isrc:` search cannot
do that, because it matches the recording exactly.

**therefore spotify selects the release and itunes is asked only to locate that
same album by name** — iTunes is never allowed to choose which release is
canonical.

**F36 — the library path does not need musicfetch, except for artwork
candidate A.** running the full chain with musicfetch removed resolved every
field on three probe tracks — spotify by ISRC, musicbrainz by ISRC, itunes by
album search. the single regression was `GBARL1201392` (`18 Months`), where
itunes album search returns **`96 Months`** and only musicfetch's verified
`appleMusic.id` found the right cover.

so musicfetch's value splits sharply:

- **tier 0 (acquisition): unique and high.** `/url` turns a youtube link into an
  ISRC (F19, 8/8). nothing else in the stack does this.
- **tier 1 (library): narrow.** one of three artwork candidates, right about
  half the time (F34), and the only path to an apple release id when album-name
  search fails.

its `name`, `genres`, `releaseDate`, `label` and `services.beatport` are all
either superseded or demonstrably wrong (F23, F32, F34). **this is worth knowing
before renewing a $100/month plan**: the library backfill could run on the free
tiers alone at the cost of some artwork coverage, while acquisition genuinely
depends on it.

**F37 — itunes alone covers artwork; musicfetch is not needed in tier 1.**
the one case musicfetch uniquely solved (`18 Months`, where
`entity=album` returns `96 Months`) is solved by searching **`entity=song` with
the track name** and filtering on `collectionName`:

```
entity=album  term='Calvin Harris 18 Months'      1 result,  0 album hits
entity=song   term='Calvin Harris Sweet Nothing'  24 results, 2 album hits → collectionId 1713469222
```

the two-entity chain reproduces musicfetch's results **byte for byte**:

| ISRC | album | via | size |
|---|---|---|---|
| `USJI10000001` | No Strings Attached | `entity=album` | 2256 KB |
| `INS181801821` | Stree | `entity=album` | 1755 KB |
| `GBARL1201392` | 18 Months | `entity=song` | 2162 KB |
| `USUG12509635` | ODYSSEY | `entity=album` | 2919 KB |

**musicfetch is therefore removed from tier 1 entirely** (operator decision). it
remains **required for tier 0**, where `/url` is the only way to turn a youtube
link into an ISRC (F19).

**F38 — indian repertoire is 167 of 1,494 tracks, and two signals agree on it.**

```
ISRC country prefix == IN     144
genre matches indian/bollywood/punjabi/telugu/tamil   165
both                          142
either  → scope               167   (11% of the library)
```

the signals overlap on 142, so neither alone is sufficient: **2** IN-prefixed
tracks carry a western genre, and **23** indian-genre tracks carry a non-IN ISRC
— diaspora releases such as `Raghav & Tesher — Desperado` (`SGB502383473`,
singapore). the scope rule is therefore **either** signal, not both.

**F39 — the library has 6 duplicate ISRCs in three distinct classes.** measured
across all 1,494 files by ISRC and by audio-stream md5:

**class A — true duplicates (3).** identical audio md5 *and* identical ISRC; the
second copy carries a ` (2)` filename suffix:
```
Tiësto - The Business / (2)              85b48197…  same bytes
John Summit & Feid - CHICA 305 / (2)     635e4af1…  same bytes
NAV - My Business (ft. Future) / (2)     c11219b3…  same bytes
```

**class B — same ISRC, genuinely different recordings (2).**
```
Bebe Rexha - New Religion             174s   ← spotify says 174s  ✓
Bebe Rexha - New Religion [Extended]  248s   ← wrong ISRC, inherited from the edit
Emotional Oranges - Call It Off / (ft. JAEHYUN)
```

**class C — an ISRC on an entirely unrelated song (1).**
```
INS181600966  spotify: 'Sau Tarah Ke', 238s
  Sau Tarah Ke.aiff          238s  ✓ correct
  Jai Jai Shivshankar.aiff   230s  ✗ a completely different song
```

**F40 — duration identifies a wrong ISRC, and the tolerance is tight.**
across 26 sampled tracks, local duration vs the ISRC's spotify duration:

```
26 of 26 agreed.  max legitimate delta: 2s.  most were exactly 0s.
```

against deltas of **8s** (class C) and **74s** (class B), the separation is
unambiguous. **a ±5s tolerance is well clear of observed noise**, and it is the
same discriminator already used for beatport edits (G3) and acquisition (G7) —
one mechanism, three uses.

this answers "how would we know our ISRC is wrong": **we compare the audio we
have against the duration of the recording the ISRC claims to be.** no
fingerprinting required for the common case.

**F41 — music videos are distinguishable from audio releases by metadata shape.**

```
youtube music '- Topic' upload      official artist-channel video
  uploader  EI8HT - Topic             uploader  Dua Lipa
  track     Silk and Cologne…         track     <absent>
  artist    EI8HT, Offset             artist    <absent>
  album     METRO BOOMIN PRESENTS…    album     <absent>
```

both report `categories: ['Music']` and `media_type: video`, so neither of those
fields helps. the reliable signal is that **youtube music auto-generated `- Topic`
uploads carry `track`/`artist`/`album`, and music videos do not.**

**F42 — complete tag inventory of the current library.** every key present
across all 1,494 files:

| field | count | coverage |
|---|---|---|
| `title` `genre` `date` `artist` | 1494 | 100% |
| `disc` · `album` | 1491 | 99.8% |
| `track` | 1490 | 99.7% |
| `album_artist` | 1451 | 97.1% |
| `TSRC` (ISRC) | 1439 | 96.3% |
| `publisher` (label) | 1069 | 71.6% |
| `TIT3` (mix name) | 99 | 6.6% |
| `TPE4` (remixer) | 46 | 3.1% |
| `TEXT` (lyricist) | 25 | 1.7% |
| `composer` | 22 | 1.5% |

fourteen fields, and the gaps say what this project adds: **no `TBPM`, no
`TKEY`** anywhere (beatport supplies both at 100% of matches — F14), composer and
lyricist under 2% (the musicbrainz work hop fills these — F28), and label missing
on 28%.

note `TIT3` (99) exceeds `TPE4` (46) by 53. that is **correct, not a gap**: the
difference is extended mixes and radio edits, which carry a mix name and have no
remixer (§7a).

**F43 — the `- Topic` test is primary; duration does NOT catch lyric videos.**
enumerating `ytsearch5:Arijit Singh Roke Na Ruke Naina`:

```
279s  Roke Na Ruke Naina Lyrical Video   T-Series
279s  Arijit Singh - … (Lyrics Video)    PluginVibes     ← reupload
279s  Roke Na Ruke Naina                 Arijit Singh
123s  Roke Na Ruke Naina Full Video Song T-Series        ← short video edit
135s  Roke Na Ruke Naina Video Song      T-Series
```

the library's audio release is **278s**. three of those videos are **279s —
inside the ±5s tolerance.** an earlier revision of this spec claimed the duration
gate was a sufficient backstop for music videos because "intro and outro push it
clear"; that is **wrong for lyric videos**, which are the exact audio over a
static image.

so the defences are not interchangeable:

- **metadata test (`- Topic` + `track`/`artist`/`album`) — necessary.** it is the
  only thing that rejects a full-length lyric video. none of the five results
  above is a `- Topic` upload.
- **duration gate — partial.** it catches the 123s and 135s edits and nothing
  else.

none of these five would be admitted, but only because of the metadata test.

**F44 — an ISRC is not a unique key for a file.** measured in this library:

```
INS181600966   md5 95eff850…   Jonita Gandhi & Amit Mishra - Sau Tarah Ke.aiff
INS181600966   md5 fe6d0c18…   Vishal Dadlani & Benny Dayal - Jai Jai Shivshankar.aiff
```

two unrelated songs, one ISRC (F39 class C). **any override or correction keyed
by ISRC is ambiguous** — it cannot express which of the two files it means. the
decoded-audio md5 is unique per recording and stable across renaming and
retagging, so it is the key for anything file-scoped (§9c).

ISRC remains the key for *recording*-scoped cache rows (§9a), where the ambiguity
does not arise: those describe the catalogue entry, not a file on disk.

**F45 — a spotify track URL yields the ISRC directly, for free.**
`GET /v1/tracks/{id}` returns `external_ids.isrc` alongside name, duration, album,
track and disc number — everything §7b needs, in one unauthenticated-tier call:

```
external_ids  {'isrc': 'GBARL2501127'}
album         Blessings - The Remixes (Part 2) | trk 4/6 | disc 1
duration      189 s
```

this makes "paste a spotify link" a complete identity solution for a file with no
ISRC (§9d), with **no musicfetch call and no fingerprinting**.

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
  │ tier 1 · spotify /search?q=isrc:   [FREE]     │
  │ enumerates every release for the recording    │
  │ → chosen release (§7b) · earliest date (F33)  │
  │ → album · album artist · track · disc ───┐    │
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

## 5a. what happens to one track, start to finish

worked on `*NSYNC - Bye Bye Bye.aiff`, with the real values each call returned.

**step 0 — read the file. no network.**
```
ffprobe → TSRC = USJI10000001
```
if there is no ISRC, the track goes to the tier-0 path (§10) instead.

**step 1 — spotify, queried DIRECTLY by ISRC.** *(not via musicfetch)*
```
GET /v1/search?q=isrc:USJI10000001&type=track&limit=10
→ 10 releases
```
rank them `album > single > compilation`, then `total_tracks` DESC, then
`release_date` ASC (§7b). this yields two different things:

```
chosen release   → No Strings Attached | album artist *NSYNC | trk 1/12 | disc 1
earliest date    → 2000-01-17   = MIN(release_date) over ALL 10 releases
```

the chosen release supplies `album`, `album artist`, `track`, `disc`. the
earliest date supplies `date`/`year` — these come from **different rows** of the
same response (F33).

**step 2 — musicbrainz, also queried directly by ISRC.**
```
GET /ws/2/isrc/{ISRC}?inc=artist-credits+artist-rels+work-rels
→ artist-credit joinphrases  → main vs featured split (§6)
→ performance relation       → work id
GET /ws/2/work/{id}?inc=artist-rels
→ composer, lyricist         → TCOM, TEXT
```
on `Not Found`, fall back to the spotify/itunes `(feat. …)` title parse and flag
the track. on `currently busy`, **retry** — that is not a miss (F30).

**step 3 — beatport.** try `?isrc=` first; on zero results search by
artist + name + mix name (F22). compare durations:
```
within ±5s  → same recording → take genre, sub_genre, label, bpm, key, mix_name
outside ±5s → different edit  → take genre, sub_genre, label ONLY (F23)
```
zero results is normal; genre then falls back to itunes.

**step 4 — artwork (§7c).** only now does musicfetch appear, and only as the
first of three candidates:
```
A  musicfetch appleMusic.id → itunes /lookup → collectionName == chosen album?
      here: 'Beach Beats' ≠ 'No Strings Attached'  → REJECT
B  itunes /search?term='*NSYNC No Strings Attached'&entity=album
      here: 'No Strings Attached'  → ACCEPT
C  spotify album image (~640px)                    → not needed
upgrade artworkUrl100 → 3000x3000bb.jpg            → 2256 KB
```

**step 5 — assemble and write to the sidecar.** apply §7 precedence and §7a
naming; **no audio file is touched.** `diff` shows the proposed change, `apply`
writes to the output tree.

**the order that matters:** spotify first, because its release choice is the
input to everything else — the album name drives the artwork search, and the
track/disc numbers come from that release rather than from any id another
service hands over.


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
   measured coverage **28/30 (93%)**, both misses regional (F30).
2. **the filename** — `Main - Title (ft. Featured)`. this is the operator's own
   curation and it agreed with musicbrainz on **every case where both were
   present**. it is a first-class source here, not a last resort.
3. **spotify / itunes `name`** — extract a trailing `(feat. …)` when present.
   this is the designated fallback where musicbrainz has no recording (F29/F30).
4. **`track.artists` minus `album.artists`** — a **hint only, never decisive**;
   it inverts roles on bollywood and demotes collaborators (F29).

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

**a hand-edited value in `library.toml` (§9b) outranks every row in this table.**
where the operator has asserted a value, no source is consulted for that field.

| field | 1st | 2nd | 3rd |
|---|---|---|---|
| title | **itunes `trackName`** (parsed, §7a) | spotify | filename parse |
| artist | **musicbrainz artist-credit** — performers-only filter **in indian scope only** (§6, §7a, F38) | filename parse | itunes `artistName` |
| album | **itunes `collectionName`** | spotify | — |
| album artist | **main artists only** (§6, §7a) | itunes `artistName` | artist |
| track number | **spotify chosen release `track_number`** (F32) | itunes (unvetted release) | — |
| disc number | **spotify chosen release `disc_number`** (F32) | itunes (unvetted release) | — |
| release date | **spotify MIN across all releases** (F33) | itunes | musicbrainz `first-release-date` |
| year | derived from release date | — | — |
| **genre** | **beatport `sub_genre` if present, else `genre`** — wherever a beatport listing exists, regardless of style (operator decision) | itunes `primaryGenreName` | existing tag |
| artwork | **verified chain §7c** → 3000² | spotify album image (~640px) | existing embedded art (flagged) |
| label | beatport `release.label` | itunes | — |
| bpm | **beatport `bpm`** (F14, 100% coverage) | — | — |
| key | **beatport `key`** (F14, 100% coverage) | — | — |
| mix name (`TIT3`) | beatport `mix_name` (F24) | parsed from itunes title | filename bracket |
| remixer (`TPE4`) | beatport `remixers` (F24) | parsed from mix name | — |
| ISRC | the file's own tag | musicfetch `isrc` | — |
| composer (`TCOM`) | musicbrainz work → composer (F28) | — | — |
| lyricist (`TEXT`) | musicbrainz work → lyricist (F28) | — | — |

## 7a. naming and tag shape

**title format.** one canonical shape, in this order:

```
{Name} (ft. {Featured artists}) [{Mix name}]
```

- the **parenthetical** carries featured artists only, comma-separated
- the **bracket** carries the mix name only
- either part is omitted when it does not apply; the bare name is the common case

```
Blessings (ft. Clementine Douglas)
Blessings [Odd Mob Remix]
Blessings (ft. Clementine Douglas) [Extended]
```

**apple and spotify must be parsed, not copied.** they render mixes as a suffix
on `name` — `"Blessings - Odd Mob Remix"` (F25) — and features sometimes inside
`trackName`, sometimes folded into `artistName` (§6). the resolver splits both
apart and re-renders in the shape above. **no source's title string is written
verbatim.**

**remixer (`TPE4`) and mix name (`TIT3`).**

- `TIT3` holds the mix name whenever one exists — `Odd Mob Remix`, `Extended`,
  `Radio Edit`, `Club Mix`.
- `TPE4` holds the remixer **only when the track is a remix by a third party.**
- **an extended mix is not a remix.** `Extended`, `Extended Mix`, `Radio Edit`,
  `Club Mix`, `Original Mix` and `Instrumental` set `TIT3` and leave `TPE4`
  empty — the original artist reworking their own track is not a remixer.
- beatport's `remixers` array decides this directly when a verified match exists
  (F24); otherwise the remixer is the name preceding `Remix`/`Flip`/`Bootleg`/
  `VIP` in the mix name.

**mix-name normalisation.** the library currently holds both `[extended mix]`
(12×) and bare `[extended]`. one spelling wins:

| observed | normalised |
|---|---|
| `Extended Mix`, `Extended Version`, `Extended` | **`Extended`** (the primary release in dance — F23a) |
| `Radio Edit`, `Radio Mix`, `Radio Version` | **`Radio Edit`** |
| `Original Mix`, `Original Version` | **`Original`** |
| `{X} Remix`, `{X} Edit`, `{X} Flip`, `{X} VIP` | unchanged, `{X}` → `TPE4` |
| `Continuous Mix`, `Instrumental`, `Club Mix` | unchanged |

`Original` is written to `TIT3` only when the source states it; it is never
invented for a track that simply has no mix name.


**performer vs composer — indian repertoire only (F28, F38).** this rule is
**scoped, not global.** it applies when either signal fires:

```
ISRC country prefix == IN   OR   genre matches
  bollywood | indian | punjabi | telugu | tamil
```

**167 tracks, 11% of the library.** within that scope `artist` carries
**performing artists only** — the operator listens by vocalist, and indian
listings inconsistently promote music directors into `artists[]`.

**everywhere else the full credited artist list is kept.** in western repertoire
a producer credited as an artist genuinely *is* a main artist — `Metro Boomin`,
`Calvin Harris`, `Internet Money` are not pollution to be stripped, and applying
the indian rule globally would corrupt them. this is the operator's call and it
is the correct one.

in scope, composers and lyricists go to their own frames, never to `artist`:

| role | frame | source |
|---|---|---|
| performers | `TPE1` (`artist`) | musicbrainz `artist-credit` |
| composer | `TCOM` | musicbrainz work → `composer` |
| lyricist | `TEXT` | musicbrainz work → `lyricist` |
| album artist | `TPE2` | the chosen release (§7b) |

**`album artist` is allowed to differ sharply from `artist`** — operator
decision. on a film soundtrack it may be `Various Artists`, a composer, or a
music director, and that is correct: it describes the *release*, not the
recording. only `artist` is held to the performers-only rule.

**separator style (OQ-7, decided).** comma between every artist, `&` before the
last:

```
Benny Dayal, Shalmali Kholgade & Divya Kumar
Arijit Singh                                  (single artist — no separator)
Benny Dayal & Shalmali Kholgade               (two artists — & only)
```

**continuous mixes.** a `[Continuous Mix]` is a DJ mix compilation: the mix is
the album artist's work, the track is not. per operator decision:

- `TPE4` (remixer) — **the album artist**, i.e. the DJ who assembled the mix
- `artist` — **unchanged**, the track's own artist (David Guetta stays David
  Guetta)
- `TIT3` — `Continuous Mix`

this is the one case where `TPE4` is populated without the mix name naming a
remixer, and it is deliberate: the mixer *is* the person who modified the
recording, which is exactly what `TPE4` means.

**artist vs album artist.** features live in the *title*, so:

- `artist` — **main artists only**, plus the remixer when there is one
  (matching F25's existing `Calvin Harris, Clementine Douglas & Odd Mob`)
- `album artist` — **main artists only**, never the remixer, never a feature
- featured artists appear **only** in the title parenthetical

this is why §6's main/featured split is load-bearing: get it wrong and a feature
is promoted into `album artist`, which fragments the album in rekordbox.

**OQ-7 — separator style.** the library currently mixes `&` and `,` in artist
strings (`Calvin Harris & Clementine Douglas` vs `Calvin Harris, Clementine
Douglas & Odd Mob`). serato and rekordbox both treat the field as one opaque
string, so this is cosmetic — but it should be *consistently* cosmetic. proposed:
comma-separate all but the last, `&` before the last. **needs confirmation.**


## 7b. release selection

**every album-level field depends on choosing the right release first.** a
recording appears on many (F26): the original album, a single, and any number of
compilations. album, album artist, track number, disc number and even the title
string all change with that choice.

```
candidates = spotify /v1/search?q=isrc:{ISRC}&type=track
rank by (album_type: album=0, single=1, compilation=2),
        then total_tracks DESC,
        then release_date ASC
pick the first
```

**`total_tracks` descending is load-bearing, not cosmetic.** an earlier revision
ranked by release date alone and picked the wrong release for `Kamariya`:

```
[single] 2018-08-09  1/1  Kamariya (From "Stree")  | Kamariya (From "Stree")   ← earliest, WRONG
[single] 2018-08-22  2/4  Stree                    | Kamariya                  ← correct
```

a **1-track single is a promotional release**; the parent album or soundtrack is
the recording's real home, and it is frequently published *later*. ranking on
track count finds the parent; ranking on date finds the promo.

verified against every case probed for this spec:

| ISRC | chosen release | title |
|---|---|---|
| `INS181801821` | `Stree` (single, 2/4) | `Kamariya` — clean |
| `INS181700238` | `Badrinath Ki Dulhania` (single, 2/5) | `Roke Na Ruke Naina` — clean |
| `USJI10000001` | `No Strings Attached` (album, 1/12) | `Bye Bye Bye` |
| `USUG12509635` | `ODYSSEY` (album, 7/19) | `Don't Want Your Love` |
| `GBARL1201392` | `18 Months` (album, 10/15) | `Sweet Nothing (feat. Florence Welch)` |
| `SGB502383473` | `Desperado` (single, 1/1) | `Desperado` — only release |
| `GBARL2501127` | `Blessings — The Remixes (Part 2)` (single, 4/6) | `Blessings - Odd Mob Remix` |

the last row still carries a `" - {X} Remix"` suffix, which is **correct** — it
is a genuine remix release, and §7a moves that suffix into `TIT3` rather than
stripping it.

**compilations are chosen only when nothing else exists.** they carry inflated
track counts (`trk 36/50`), meaningless track numbers, and the `(From "…")` and
`- {X} Remix` title suffixes that §7a would otherwise have to strip.

**tier 2 gains spotify.** itunes supplies `trackNumber`/`discNumber` (F4) but
exposes only the one release its id points at; spotify's ISRC search is what
makes the *set* of releases visible. once a release is chosen, its track and disc
numbers are read from that release, not from an arbitrary apple id.

**consequences for §7a.** with the right release chosen, `(From "…")` never
appears and the `" - {X} Remix"` suffix appears only on remix releases, where it
is genuine and belongs in `TIT3`. title cleaning becomes a fallback path rather
than the main one.

**OQ-9 (decided) — soundtrack albums.** album artist is left **as the release
states**, including `Various Artists` or a music director. it describes the
release, not the recording. the performers-only rule binds `artist` alone (§7a,
F28).


## 7c. artwork

**all artwork is refetched** (operator decision). existing embedded art is not
trusted or preserved on the assumption it is correct — it is replaced whenever a
**verified** source is found, and kept only when none is.

the danger is not resolution, it is **identity**: musicfetch's track image is the
cover of whichever release its matcher landed on, and that is a compilation often
enough to matter (F34). so every candidate is verified against the release chosen
in §7b before its bytes are used.

**the chain, in order. the first candidate that verifies wins.**

```
1. §7b has already chosen the release  →  album name + album artist

2. candidate A — musicfetch appleMusic.id
     itunes /lookup?id={appleMusic.id}
     ACCEPT only if collectionName matches the chosen album name
     (exact on normalised text, or the chosen name contained in it)

3. candidate B — itunes album search
     itunes /search?term={album artist} {album}&entity=album
     ACCEPT the first result whose collectionName matches the same way

4. candidate C — spotify's album image from the chosen release
     correct by construction, but capped around 640px

5. no candidate  →  keep the existing embedded artwork, and flag the track
```

**upgrade to 3000×3000** by rewriting the trailing `/{N}x{N}bb.jpg` on the
accepted `artworkUrl100` (F5). on non-200 or a short read, step down 3000 → 1400
→ 600 rather than failing the track.

**measured on four tracks, 4/4 produced 3000×3000:**

| ISRC | album | musicfetch id | accepted via | size |
|---|---|---|---|---|
| `USJI10000001` | No Strings Attached | `Beach Beats` ✗ | album search | 2256 KB |
| `INS181801821` | Stree | `Naacho Naacho…` ✗ | album search | 1755 KB |
| `GBARL1201392` | 18 Months | `18 Months` ✓ | appleMusic.id | 2162 KB |
| `USUG12509635` | ODYSSEY | `ODYSSEY` ✓ | appleMusic.id | 2919 KB |

**candidate A is right about half the time and wrong silently**, which is exactly
why the verification step exists rather than trusting the id. candidate B is not
a fallback for rare cases — it carried half this sample.

**the name check must reject, not coerce.** searching iTunes for
`Calvin Harris 18 Months` returns exactly one album: **`96 Months`**, a different
record. the normalised comparison rejects it and the chain moves on. a looser
match — fuzzy ratio, "closest result wins" — would have embedded the wrong cover
with no signal that anything went wrong.

**storage.** 3000² JPEGs run ~1.7-2.9 MB; across 1,494 tracks that is roughly
**3-4 GB** added to the output tree, consistent with OQ-1's estimate.


## 7d. the complete field set

every tag this project writes, its ID3 frame, and where it comes from. **nothing
outside this table is written.**

| field | frame | source | coverage |
|---|---|---|---|
| title | `TIT2` | spotify chosen release, re-rendered per §7a | 100% |
| artist | `TPE1` | musicbrainz artist-credit (performers-only in indian scope) | 100% |
| album | `TALB` | spotify chosen release (§7b) | ~100% |
| album artist | `TPE2` | chosen release, main artists only | ~100% |
| year | `TDRC` | **earliest** release across all releases (F33) | ~100% |
| release date | `TDRL` | same, full date | ~100% |
| track number | `TRCK` | chosen release `track_number` (F32) | ~100% |
| disc number | `TPOS` | chosen release `disc_number` (F32) | ~100% |
| genre | `TCON` | beatport where listed, else itunes | 100% |
| label | `TPUB` | beatport `release.label`, else itunes | ~72% today |
| ISRC | `TSRC` | the file's own tag, once G10 trusts it | 96.3% |
| **mix name** | `TIT3` | beatport `mix_name`, else parsed from title | remixes + edits |
| **remixer** | `TPE4` | parsed from mix name, beatport confirms | third-party remixes only |
| **original artist** | `TOPE` | the chosen release's artist, when a remixer exists | remixes only |
| **composer** | `TCOM` | musicbrainz work → composer | indian scope |
| **lyricist** | `TEXT` | musicbrainz work → lyricist | indian scope |
| **BPM** | `TBPM` | beatport only (§7e) | **partial** |
| **key** | `TKEY` | beatport only (§7e) | **partial** |
| artwork | `APIC` | verified chain §7c at 3000² | ~100% |

**`TOPE` (original artist) is new and only meaningful on remixes.** on
`Blessings [Odd Mob Remix]` it holds `Calvin Harris, Clementine Douglas` while
`TPE1` holds those plus `Odd Mob` and `TPE4` holds `Odd Mob`. on a non-remix it
is **not written at all** — an empty `TOPE` is noise, and rekordbox shows the
column regardless.

**composer and lyricist are written wherever musicbrainz supplies them**, not
only in indian scope. the *indian scope* rule (§7a, F38) governs who is excluded
from `TPE1`, not who gets a `TCOM`. a western track with a known composer gets
one; it is simply rarer that musicbrainz has it and rarer still that it differs
from the artist.

## 7e. BPM and key — the honest coverage problem

**neither exists in the library today** (F42: zero `TBPM`, zero `TKEY` across
1,494 files), and beatport is the only source in this stack that has them.

**beatport gives both at 100% of matches (F14) — but matches are the constraint.**
sampled coverage was 17/20 on mainstream tracks and **0/9 by ISRC** on the
`Blessings` remixes (F22), where a name+mix search was needed. for bollywood,
beatport coverage is effectively nil. so realistic coverage is **good for dance,
poor for hip-hop, near-zero for indian repertoire**.

**discogs does not fill this gap.** it has **no BPM or key fields** at all — the
recommended place for BPM is free-text release notes
([discogs forum, checked 2026-09-14](https://www.discogs.com/forum/thread/412239)).
tools that appear to offer it combine discogs with echonest (**defunct**) or
acousticbrainz (**frozen**). discogs is still worth an API key for **style**
(a deeper taxonomy than itunes genre), **label**, **catalog number** and
**credits** — but not for BPM or key. recorded as OQ-10.

**the only route to full coverage is local analysis**, and nothing for it is
installed today (no `librosa`, `essentia`, `aubio`; only `chromaprint`). that is
a real dependency decision, not a small one — `essentia` is ~120 MB.

**and it may not be worth it.** rekordbox computes its own BPM and key during
analysis and prefers its own values over tags, so a computed `TBPM` mainly buys
sorting in serato and in this project's own ui. **recommendation: write BPM and
key only where beatport supplies them, leave them empty otherwise, and revisit
local analysis once the library is otherwise correct.** an empty field is honest;
a guessed one gets trusted. recorded as OQ-11.


## 8. gates — a stage is not done until these pass

- **G1 identity.** ≥95% of the 1,439 ISRC tracks resolve to a musicfetch result.
  measured baseline: 20/20.
- **G2 completeness.** ≥98% of resolved tracks carry all eight required fields.
- **G3 beatport match and field class.** beatport is searched by **artist +
  name + mix name**, never via musicfetch's link (F23 predecessor), and ISRC is
  tried first only as a fast path — it succeeds on originals and fails on
  remixes (F22). a candidate is accepted when artist and normalised mix name
  agree. then **duration decides which fields transfer** (F23):
  - within ±5s → the recording is the same; **all** fields transfer.
  - outside ±5s → same work, different edit; **only** `genre`, `sub_genre`,
    `label` and remixer identity transfer. `bpm`, `key`, `length` and beatport's
    `isrc` are **discarded**.
  zero results is a normal outcome, not a failure. the fraction of tracks landing
  in each class is reported by `verify`.
- **G10 ISRC trust.** every track's local duration is compared to the duration
  of the recording its ISRC claims (F40). delta > ±5s means **the ISRC does not
  describe this file**: it is stripped, the track goes to tier-0 identity, and it
  is queued for review. no field resolved from an untrusted ISRC is ever written.
- **G11 no duplicates in the output tree.** no two output files share an audio
  md5, and no ISRC appears twice except where G10 has flagged one as wrong.
- **G9 no cross-recording contamination.** when the duration class is "different
  edit", the written ISRC must equal the file's own. adopting beatport's ISRC for
  a longer recording is a correctness failure, not a metadata improvement, and
  `verify` asserts it never happens.
- **G6 artist-credit agreement.** musicbrainz and the filename agree on the
  main/featured split for ≥95% of the 418 featured tracks. disagreements are
  queued for review, never auto-resolved.
- **G4 non-destruction.** the source tree's bytes are unchanged after any run.
  asserted by checksum, not by inspection.
- **G5 artwork — verified identity, always refetched.** every output file
  carries art from a **verified** release (§7c): the artwork's `collectionName`
  must match the §7b-chosen album. artwork is refetched for every track, not
  merely when larger. when **no** candidate verifies, the existing embedded art
  is kept and the track is **flagged** — never replaced by an unverified image.
  `verify` reports the count per candidate tier and the count of flagged tracks.

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

## 9a. the cache — resolve once, re-tag forever

**the sidecar is a permanent cache keyed by identity, not a scratch file.** the
goal in §4 — "improving the resolver re-tags the library for free" — is only true
if a re-run costs no API calls. with a 20 req/min ceiling (F8) and a 5,000-request
trial, a careless re-run is expensive; with the cache it is free.

**store raw responses, not just parsed fields.** this is the load-bearing
decision. every finding in §3 that changed the parsing — release ranking (F27),
the artwork chain (F34), track/disc source (F32) — would have forced a full
re-fetch if only the parsed output had been kept. raw payloads mean a resolver
fix is replayed offline against stored JSON.

**tables.**

```
files       path, audio_md5, duration_s, isrc_from_tag, mtime
            → unique(audio_md5) and unique(isrc) power dedup (§11a)

recordings  isrc PK, fetched_at, source_version
            raw_spotify JSON, raw_musicbrainz JSON, raw_work JSON,
            raw_beatport JSON, raw_itunes JSON
            → the resolved fields are a VIEW over these, recomputable offline

service_ids isrc, service, service_id, url, matched_by, verified
            → the equivalence map (below)

fingerprints isrc, chromaprint, duration_s
            → §15 acoustid, computed lazily and kept forever

artwork     isrc, source_release, url_template, width, sha256, local_path
            → 3-4 GB of covers fetched once

jobs        id, kind, state, progress, started_at, error
            → drives the web ui's progress (§14)
```

**`source_version` is what makes re-resolution safe.** bump it when the parsing
logic changes; rows below the current version are recomputed from their stored
raw payloads, and only rows with **no** raw payload are re-fetched.

**cache invalidation is deliberate and rare.** these are catalogue facts, not
live data — a recording's ISRC, composer and release list do not change. refetch
only on explicit request, or when a field was never successfully resolved.

## 9b. `library.toml` — one map, generated and editable

**every run produces one file: `library.toml`, one entry per audio file, keyed by
decoded-audio md5 (F44).** ~1,494 entries. it is the map, the override file and
the worklist at once — an earlier draft split these into three artefacts, which
meant the operator had to know which one to open.

```toml
["446fd65a7c0be5bd83448b5a04bb7035"]
file     = "Calvin Harris, Clementine Douglas & Odd Mob - Blessings [Odd Mob Remix].aiff"
title    = "Blessings - Odd Mob Remix"
artist   = "Calvin Harris, Clementine Douglas, Odd Mob"
album    = "Blessings - The Remixes (Part 2)"
isrc     = "GBARL2501127"
spotify  = "https://open.spotify.com/track/1Z2HuPvdKhdlIbHst99MnR"
itunes   = "https://music.apple.com/us/album/1829498271"
beatport = ""        # not found

["88a0bc73ae97ee9c7744de964e5abf8e"]
file     = "A$AP Rocky - Fuckin' Problems (ft. Drake, 2 Chainz & Kendrick Lamar).aiff"
isrc     = ""      # none - paste a spotify url below
spotify  = ""
```

**an empty field is an invitation.** `beatport = ""` is the worklist entry: the
operator finds the listing, pastes the URL, re-runs. `isrc = ""` with a pasted
spotify URL is the whole no-ISRC path (§9d). there is no separate file to
consult and no stub to generate.

**merge rule: the resolver never overwrites what it did not write.** the sidecar
keeps the last value it generated per `(md5, field)`. on the next run:

```
file value == last generated  →  resolver may refresh it
file value != last generated  →  the operator edited it
                                 preserve verbatim, mark provenance `manual`
```

no marker to remember, no ceremony. editing a line is the act of asserting it.
deleting a line's value reverts that field to resolver control on the next run.

**title/artist/album are written for legibility, not read as input.** they make
an md5-keyed file scannable; the authoritative values live in the cache (§9a).
the fields the resolver *reads back* are `isrc`, the service URLs, and any direct
field override.

**it is the only hand-editable artefact in the system, and it is safe to delete.**
regenerating costs nothing for resolved rows — they come from cached raw payloads
(§9a) — but manual edits are lost, so the file is worth version-controlling. it is
plain text and diffs cleanly.

## 9c. views over the map

`library.toml` is complete but long. `map` renders it for scanning:

```
music-metadata map                       # TSV: md5, file, isrc, spotify, itunes, beatport
music-metadata map --missing beatport    # only rows where beatport is empty
music-metadata map --no-isrc             # the 55 (§2) — title, artist, duration to search by
music-metadata map --untrusted           # rows G10 flagged on duration
music-metadata map --manual              # everything asserted by hand, for review
```

these are **read-only views**; edits always go back to `library.toml`. the web ui
(§14) renders the same views as tables and writes to the same file.

## 10. acquisition — tier 0, a front-end not a second pipeline

the operator wants to keep adding tracks from youtube music rather than buying
every one on beatport. F19 makes this a small addition rather than a parallel
system:

**input is a playlist or a single track.** `--flat-playlist --dump-json`
enumerates a playlist into `{id, title, duration, channel}` entries without
downloading anything — verified working. each entry then runs the chain below
independently, so a 50-track playlist is 50 identity resolutions and only the
admitted ones become downloads. the **ISRC dedup check (§11a) runs before
download**, so tracks already in the library cost one API call, not a file.

```
playlist url → yt-dlp --flat-playlist → N video ids
single url   → 1 video id
                    │
                    ▼  (per id)
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

**OQ-6 (decided) — lossy source, lossless container.** the source is **AAC at ~257 kbps**
(measured across `.staging`, and reachable only with valid premium cookies —
F20); the library is AIFF. the conversion costs **5.4×**
storage — 9.5 GB → 51.9 GB measured — and **adds no quality**, since nothing is
recoverable that the AAC encoder discarded. the existing 1,494 files are already
converted and are not in scope to revisit. ~~the open question is **new** acquisitions.~~ **decided: convert to AIFF**, for
consistency with the existing 1,494 files and DJ-app behaviour. the 5.4× cost is
accepted deliberately, not by omission.


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

## 11a. duplicates

**three classes, three policies (F39).** the distinction matters: only one class
is safely automatic.

| class | test | policy |
|---|---|---|
| **A — true duplicate** | same ISRC **and** same audio md5 | **auto-resolve.** keep one, delete the other. byte-identical audio cannot lose information. |
| **B — same ISRC, different audio** | same ISRC, differing md5, duration delta > 5s | **never auto-delete.** these are different recordings; one ISRC is wrong. re-resolve both by duration (F40) and queue for review. |
| **C — ISRC on an unrelated song** | duration delta > 5s vs the ISRC's own duration | **strip the ISRC**, route the file through tier-0 identity (§10), queue for review. |

**deletion is always to a quarantine directory, never `rm`.** the operator
reviews and empties it. combined with the §9 rule that the source tree is never
mutated, class A resolution on the *source* library is a report; only the output
tree is de-duplicated.

**preventing future duplicates.** the sidecar holds a unique index on ISRC and on
audio md5. `acquire` checks both **before download**:

```
ISRC already in library        → skip, report "already have this recording"
audio md5 matches after fetch  → discard the download, keep the existing file
```

the ISRC check is the cheap one and runs first — tier 0 resolves identity before
committing to a download anyway (§10), so a duplicate costs one API call rather
than a file.

**note the ` (2)` filenames are a symptom, not the test.** all three class-A
duplicates happen to carry it, but the test is the audio hash — a re-download
under a different name would not.

## 11b. excluding music videos

the operator wants the **release**, never the video (F41).

```
admit   uploader ends with ' - Topic'  AND  track/artist/album present
reject  otherwise  →  retry via music.youtube.com, or refuse with a reason
```

`categories: ['Music']` and `media_type: video` appear on **both** and must not
be used.

**the duration gate is not a sufficient backstop here (F43).** lyric videos carry
the exact audio and land inside ±5s — measured at 279s against a 278s release.
duration only catches truncated video edits. the `- Topic` metadata test is
therefore **necessary**, not merely preferred, and a candidate that fails it is
rejected even when its duration matches perfectly.

**prefer `music.youtube.com` URLs.** given a plain `youtube.com` link, tier 0
resolves the ISRC via musicfetch `/url` (F19) and then re-searches youtube music
for the audio release rather than downloading the page it was handed.


## 12. project structure, commands, testing

```
src/music_metadata/
  cli.py            # entry point
  acquire.py        # tier 0 — yt-dlp + /url identity (§10)
  probe.py          # ffprobe → local tag facts
  sources/
    musicfetch.py   # tier 0 only — youtube url -> isrc (F36)
    itunes.py       # artwork + genre fallback (F32/F37)
    musicbrainz.py  # tier 2 — artist-credit roles (§6)
    spotify.py      # tier 1 — release selection, track/disc (§7b)
    beatport.py     # tier 3 — genre/bpm/key
    bp_auth.py      # pluggable TokenProvider: cookie | oauth (F15)
    ratelimit.py    # token bucket, 20/min (F8)
  credit.py         # §6 main vs featured split
  arbitrate.py      # §7 precedence
  artwork.py        # verified chain, 3000² (§7c)
  tag.py            # ID3-on-AIFF writer, preserves foreign frames
  library_map.py    # library.toml: generate, merge, read back (§9b)
  store.py          # sidecar cache (sqlite, shared with the web ui)
                    # persists mb recording id + fingerprint for §15
  web/
    app.py          # fastapi — library, review, acquire, diff (§14)
    jobs.py         # background resolve/acquire with progress
    static/         # single-page frontend
tests/{unit,integration}/
```

**runtime stack.** python ≥3.12, managed with `uv`. `mutagen` for ID3-on-AIFF
(the only library that writes AIFF ID3 chunks correctly), `httpx` for HTTP with
timeouts and retries, `pydantic` v2 for the source response models, `fastapi` +
`uvicorn` for the ui (§14), `sqlite3` from the stdlib for the sidecar, `yt-dlp`
and `ffmpeg` for tier 0. external binaries: `ffprobe`, `ffmpeg`, `fpcalc`.

python because the three things this project does — tagging (`mutagen`),
youtube acquisition (`yt-dlp`), and audio fingerprinting (`chromaprint`) — all
have their reference implementations there, and two of them are already
installed and working on this machine.

**style, linting and formatting live in `CLAUDE.md`, not here.**

```
music-metadata acquire URL           # tier 0 — download + resolve identity
music-metadata probe                 # local tag survey, no network
music-metadata resolve [--limit N]   # tiers 1-3 → sidecar
music-metadata diff                  # proposed changes, old → new
music-metadata apply --out DIR       # write tagged copies
music-metadata verify --out DIR      # assert G1-G11
```

**testing.** every source has recorded-fixture unit tests — the probe responses
in this spec become the first fixtures. arbitration is pure and tested without
network. the tag writer is tested round-trip on a copied AIFF, including an
assertion that a synthetic `GEOB` frame survives. one integration test hits the
live APIs, marked and excluded from the default run.

## 13. open questions

- ~~**OQ-1 artwork size.**~~ **decided: 3000×3000**, ~3-4 GB measured across the
  library; the 4500² ceiling is not worth the extra storage. steps down
  3000 → 1400 → 600 on failure. **all artwork is refetched** from a verified
  release rather than trusting what is embedded (§7c).
- ~~**OQ-2 beatport auth.**~~ **resolved by live capture** — F11. session-cookie
  → token minting is verified working against the operator's account.
- ~~**OQ-8 the library holds radio edits of dance remixes.**~~ **decided: flag,
  never substitute.** `verify` emits a re-acquisition worklist naming every track
  whose beatport match is **materially longer** (>15s), with both durations and
  the beatport URL. it **never rewrites the file and never adopts beatport's
  ISRC** — the operator's point is decisive: the beatport record is a *different
  recording*, so taking its ISRC would label the file as a track it is not. this
  is why F23's field-class split exists.
- ~~**bollywood `(From "…")` suffix.**~~ **resolved by §7b** — the suffix marks a
  compilation release. choosing the correct release removes it; no string
  stripping needed.
- ~~**OQ-7 artist separator style.**~~ **decided:** comma between every artist,
  `&` before the last (§7a).
- **OQ-10 discogs.** worth an API key for style, label, catalog number and
  credits — **not** for BPM or key, which it does not have (§7e). the operator
  can add `DISCOGS_TOKEN` to `.env`. low priority: it adds depth, not coverage.
- **OQ-11 local BPM/key analysis.** ~120 MB of dependencies for fields rekordbox
  recomputes anyway. **recommendation: defer** — write beatport's values, leave
  the rest empty, revisit when the library is otherwise correct.
- **OQ-5 official beatport credentials.** the operator will supply client id and
  secret via `.env` when obtained. `OAuthClientProvider` reads them;
  `CookieSessionProvider` runs until then (F15). not a blocker.
- ~~**OQ-4 tag shape.**~~ **decided** — fully specified in §7a:
  `{Name} (ft. {Features}) [{Mix}]`, `TPE4` remixer only for third-party remixes,
  `TIT3` mix name always, `Extended Mix` → `Extended`.
- ~~**OQ-3 remix identity.**~~ **resolved by measurement (F21)** — every remix
  carries its own ISRC; 10 of 10 `Blessings` variants resolved distinctly. no
  title matching needed.

## 14. web ui

**the web ui is the primary interface, not a wrapper over a CLI** (operator
decision — the operator does not want to drive this from a terminal). the CLI
remains, as the engine the UI calls and the way anything scriptable runs, but
every routine action must be reachable from the browser.

**it exists because this pipeline generates decisions, not just output.** the
gates in §8 deliberately refuse to guess — flagged artist credits (G6),
unverified artwork (G5), beatport edit mismatches (G3), the re-acquisition
worklist (OQ-8). those flags are worthless in a log file and valuable in a
queue.

**four screens.**

1. **library** — every track, sortable and filterable by artist, album, genre,
   year, and resolution state. this is also where the operator confirms the
   tagging actually looks right at a glance.
2. **review queue** — the flagged tracks, grouped by gate. each row shows the
   proposed value beside the current one, the source that supplied it, and
   accept / reject / edit. **this is the screen that justifies the UI.**
3. **acquire** — paste a youtube or youtube music URL, watch the tier-0 chain
   run (§10), and see the resolved identity before the download is admitted.
   surfaces the G8 premium-audio precondition (F20) as a visible status rather
   than a failed run.
4. **diff / apply** — the proposed change set for a batch, reviewable in the
   browser, with `apply` gated behind an explicit confirmation.

**architecture.** fastapi serving a small single-page frontend; the sidecar
SQLite database (§9) is the shared state between CLI and UI, so neither is
authoritative over the other. long operations (`resolve`, `acquire`) run as
background jobs with progress polled from the job table — a 72-minute resolve
(F8) cannot block an HTTP request.

**local-first.** binds to localhost, no auth, no multi-user. it reads and writes
the operator's own library on the operator's own machine; anything else is out
of scope.

**not in scope for v1:** playback, waveform display, crate or playlist
management, editing audio. rekordbox and serato own those.

## 15. future — contributing fingerprints to acoustid

not v1 scope, recorded so the design does not foreclose it.

once the library is correctly tagged, it becomes a **credible source of
fingerprint → metadata mappings** for the acoustid commons. `fpcalc`
(chromaprint) is already installed and produced a valid fingerprint on the first
try during the F19 probe, and chromaprint is robust to transcoding, so the
AAC-sourced AIFFs are acceptable input.

**what a submission needs** ([acoustid.org/webservice](https://acoustid.org/webservice),
checked 2026-09-14): an application API key plus a user API key. the MusicBrainz
recording id is **optional** — textual metadata (track title and artist, album
title and artist, year, track and disc number) is accepted instead — but the
docs are blunt that a fingerprint with no metadata "is not very useful".

**the tension worth naming now.** the tracks most *worth* contributing are the
ones acoustid and musicbrainz do not already have — and those are largely the
same regional recordings musicbrainz returned `Not Found` for (F30/F31:
`Kamariya`, `Desperado`). for exactly those we have **no MBID to submit**, only
textual metadata. so:

- **~93% of the library** (F30) can be submitted with a recording id — accurate,
  but mostly duplicating mappings that already exist.
- **the ~7% that would genuinely add coverage** can only carry textual metadata,
  unless the operator first creates the musicbrainz recordings themselves. that
  is the higher-value contribution and the larger undertaking.

**the MBID never touches the audio file.** the library carries **no musicbrainz
identifier today** — verified by scanning the raw bytes of a tagged file: zero
occurrences of `UFID`, `TXXX`, `MBID` or the string `MusicBrainz`. the only
identifier present is `TSRC`.

it stays that way. the recording id and any chromaprint fingerprint live **in
the sidecar SQLite, not in ID3** — two columns in a database the operator can
delete without touching a single audio file. so the files stay clean *and* a
future acoustid pass stays cheap; these were never in tension.

without those columns a submission pass would have to re-resolve the whole
library against musicbrainz at 1 req/s (F28) — roughly 48 minutes — purely to
recover ids it already had.

**precondition, not a detail:** submitting wrong mappings actively damages a
shared database. a submission pass must run only over tracks that passed every
gate in §8, never over flagged or fallback-resolved ones.

