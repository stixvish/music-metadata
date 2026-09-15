# music-metadata — spec

**status:** phase 0 research complete · all external claims probed live
**last updated:** 2026-09-14
**see also:** `CLAUDE.md` (how we work). this file is _what we are building_.

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

| fact                   | value                                   |
| ---------------------- | --------------------------------------- |
| `~/Music/library`      | 1,494 AIFF, flat, `Artist - Title.aiff` |
| carry ISRC (`TSRC`)    | **1,439 — 96.3%**                       |
| no ISRC                | **55 — 3.7%**                           |
| `~/Music/beatport`     | 7 WAV, RIFF `INFO` tags only            |
| artwork embedded today | 1200×1200 MJPEG, `Cover (front)`        |

the no-ISRC tail skews bollywood/punjabi and remix edits — the population
_least_ likely to exist on beatport. it is deferred (§9), not solved by the
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
musicfetch" is not achievable** — musicfetch supplies the beatport _track id_,
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

| request               | actual              | bytes  |
| --------------------- | ------------------- | ------ |
| `600x600bb.jpg`       | 600²                | 116 KB |
| `1400x1400bb.jpg`     | 1400²               | 618 KB |
| `3000x3000bb.jpg`     | 3000²               | 2.9 MB |
| `5000x5000bb.jpg`     | **clamps to 4500²** | 6.3 MB |
| `100000x100000bb.jpg` | HTTP 400            | —      |

musicfetch hands over a **1400×1400** URL with no substitution required. note
the itunes Lookup response carries only `artworkUrl30/60/100` — there is no
`artworkUrl3000` field on this endpoint, so any size above 100 is obtained by
rewriting the URL, which is undocumented and ToS-gray. see §11 OQ-1.

**F6 — cloudflare fronts the _web_ host only, not the API host.**
`GET beatport.com/track/…` → **HTTP 403**, `<title>Just a moment...</title>`.
but `api.beatport.com` is a different origin and is **not** cloudflare-fronted:

```text
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

```text
token.accessToken      1156 chars
token.tokenType        bearer
token.expiresIn        599 seconds          ← ~10 minutes
scope                  user:dj openid app:prostore
session.expires        2026-10-14           ← ~1 month
```

**this corrects the earlier "grab a token by hand" plan.** a copied token dies
in 10 minutes and a full pass takes ~72 (F8), so a manual token cannot cover
even one run. but the _session cookie_ lasts a month and the endpoint re-mints a
fresh token on every call — verified by repeated calls across the capture.

the session cookie is **httpOnly**, so it is not readable from page JavaScript
(`document.cookie` shows only consent and analytics cookies). it must be
exported from chrome's cookie store, the same way `youtube-cookies.txt` already
is, and lives in `~/.config/musicpipeline/beatport-cookies.txt` — never the repo.

**the auth design is therefore:** export the cookie once per month → call
`/api/auth/session` to mint a bearer token → re-mint every ~8 minutes during a
run. no `authorization_code` implementation, no runtime client_id discovery,
no swagger-ui scraping. this is simpler _and_ more durable than the
`beets-beatport4` flow.

**F12 — beatport returns the ISRC, so matches verify exactly.**
`/v4/catalog/tracks/{id}/` includes an `isrc` field. comparing it to the ISRC we
sent musicfetch turns F9's fuzzy-match worry into a cheap exact check:

```text
17 beatport ids from the musicfetch sample
16/17 ISRC exact match
 1/17 mismatch — "MEDUZA & Khalid - Weekend"
```

the ~6% mismatch rate is real, and it is **detectable rather than silent**. G3
is rewritten accordingly: compare ISRCs, and on mismatch discard the beatport
record and fall back to apple. no artist/title/duration heuristics needed.

**F13 — `sub_genre` is almost always null; `genre` is the field that matters.**

```text
sub_genre populated:  1 of 17  (6%)  — only "Mainstage" → "Big Room"
```

**this corrects the original premise.** the plan assumed beatport sub-genres
would supply a fine taxonomy; measured, they are absent for all but genuine
electronic releases. beatport's top-level `genre` is still clearly better than
apple's for DJ use:

| beatport                                                                                               | apple, same tracks                           |
| ------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
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

```text
client_id={client_id provided}
redirect_uri={redirect_uri shared with us, can not be different}
"if you do not have authentication credentials please reach out to your
 account manager to receive them"
```

`account.beatport.com/o/applications/` redirects to plain account settings —
**there is no self-service app registration.** credentials require a business
relationship, and that is a request the operator must make, not a technical step.

**the official token is materially better when it exists:**

|            | web-session token (F11)     | official OAuth token               |
| ---------- | --------------------------- | ---------------------------------- |
| TTL        | `expires_in: 599` (~10 min) | `expires_in: 36000` (**10 hours**) |
| refresh    | re-mint from cookie         | `refresh_token`                    |
| credential | month-long httpOnly cookie  | client id + secret                 |
| approval   | none                        | account manager                    |

a 10-hour token covers a full 72-minute pass outright.

**but note what this does _not_ change.** the token captured in F11 is a valid
bearer for `api.beatport.com` — it already returned `/v4/catalog/tracks/{id}/`
successfully across 17 records. **we are not working around the official API; we
are already calling it.** the endpoints, the fields, the ISRC verification and
the genre data in F12–F14 are all the official API's, obtained with a token the
official identity service issued. only the _acquisition_ differs.

**design consequence: the token provider is pluggable, the rest of tier 3 is
not.** two implementations against one interface:

```text
TokenProvider.get() -> bearer
  ├── CookieSessionProvider   works today, no approval  (F11)
  └── OAuthClientProvider     drop-in once credentials arrive (F15)
```

endpoints, field mapping, ISRC gating and rate limiting are identical either
way. **this unblocks tier 3 now and makes adopting official credentials a
one-class swap**, so the build is never waiting on beatport's business process.

**F16 — the library's ISRCs were _resolved_, not carried from source.**
`~/Music/.staging` holds **1,517 M4A** files named by youtube video id
(`_026NPNnsnY.m4a`) with **no metadata at all** — sampled 11, zero carried a
title tag; the only tags are `major_brand`, `encoder` and friends. the 1,494
AIFFs were produced from these. **every ISRC in the library is therefore
second-hand**, written by the earlier process the operator distrusts.

**F17 — those ISRCs came from spotify, and they check out.** the operator
confirms the library's ISRCs were originally taken from spotify, which explains
why they identify the **streaming** release rather than the beatport one
(F22). comparing each resolved ISRC's musicfetch
title against the filename across the 20-track sample: **18 agree outright**,
and both apparent misses are correct matches where apple appends soundtrack
context — `Roke Na Ruke Naina` vs `Roke Na Ruke Naina (From "Badrinath Ki
Dulhania")`. effectively **20/20**. the ISRC-first design in §5 stands; the
titles will need a `(From "…")` normalisation decision, not the ISRCs.

**F18 — yt-dlp returns structured music metadata, but not identity.**
youtube music `- Topic` channels carry real fields:

```text
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

```text
8 of 8 staging video ids → ISRC recovered   (100%)
4 of 8 also carried a beatport link
```

**no fingerprinting, no text search, no edition ambiguity.** `fpcalc`
(chromaprint) and a text-search path were both probed and work, but neither is
needed: text search on the itunes API returned three near-identical editions for
one track — standard, deluxe, and _instrumental_ — which is precisely the
mis-selection `/url` avoids by resolving identity rather than guessing it.
fingerprinting stays documented as the fallback for audio that `/url` cannot
resolve.

**F20 — premium audio is reachable, and validity is transient.**
the operator holds youtube premium. **itag 141 (AAC-LC 256k) downloads
successfully**, verified end-to-end:

```text
downloaded today, itag 141 : aac LC 44100Hz 257516 bps  md5 2364cdfb…
existing .staging file      : aac LC 44100Hz 257516 bps  md5 2364cdfb…
raw audio stream md5        : bae6e47a…  ← identical on both
```

**byte-identical, container and audio stream.** this proves the existing library
was acquired at itag 141 and that a new pipeline reproduces it exactly. itag 774
(opus 293k) is also offered.

**but the same probe failed earlier in the same session.** a first run returned
only 151k opus, with yt-dlp reporting:

```text
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
each naming its own remixer. remix identity is therefore _free_ — it falls out of
the ISRC and needs no fuzzy title matching.

```text
GBARL2500591  Blessings                      (original)
GBARL2501117  Blessings - CamrinWatsin Remix
GBARL2501127  Blessings - Odd Mob Remix
…             10 of 10 distinct
```

**F22 — beatport supports exact ISRC lookup, but the streaming and beatport
releases carry _different_ ISRCs.** `/v4/catalog/tracks/?isrc={ISRC}` does work
and returns `count: 1` on an exact hit. but matching the library against beatport
this way returns **0 of 9** for the `Blessings` remixes, while matching on
artist + mix name returns **9 of 9**:

| remix                           | library ISRC   | beatport ISRC  |
| ------------------------------- | -------------- | -------------- |
| CamrinWatsin                    | `GBARL2501117` | `GBARL2501120` |
| Malugi                          | `GBARL2501118` | `GBARL2501121` |
| Airwolf Paradise                | `GBARL2501119` | `GBARL2501122` |
| HUGEL, Adam Trigger & Casa Mata | `GBARL2501124` | `GBARL2501129` |
| MistaJam                        | `GBARL2501125` | `GBARL2501130` |
| Will Clarke                     | `GBARL2501126` | `GBARL2501131` |
| Odd Mob                         | `GBARL2501127` | `GBARL2501132` |
| Schak                           | `GBARL2501128` | `GBARL2501133` |
| COASTR.                         | `GBARL2501139` | `GBARL2501140` |

**ISRC-only matching is therefore wrong for precisely the tracks that matter
most** — dance remixes, where beatport is the only source with a useful genre.
an earlier revision of this spec made ISRC the sole beatport key; that was a
mistake and is corrected here.

**F23 — the two releases are different recordings, not duplicate registrations.**
measured durations settle it:

| remix                           | library | beatport | delta |
| ------------------------------- | ------- | -------- | ----- |
| Airwolf Paradise                | 203s    | 289s     | +86s  |
| CamrinWatsin                    | 226s    | 336s     | +110s |
| COASTR.                         | 223s    | 330s     | +107s |
| Malugi                          | 161s    | 241s     | +80s  |
| MistaJam                        | 166s    | 303s     | +137s |
| Odd Mob                         | 189s    | 272s     | +83s  |
| HUGEL, Adam Trigger & Casa Mata | 158s    | 293s     | +135s |

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

```text
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

```text
title         Blessings [Odd Mob Remix]
TPE4          Odd Mob              ← remixer
TIT3          Odd Mob Remix        ← mix name
artist        Calvin Harris, Clementine Douglas & Odd Mob
album_artist  Calvin Harris & Clementine Douglas
```

and the original carries **no `TPE4`/`TIT3` at all** — correct. apple and spotify
instead use a `" - {X} Remix"` suffix on `name`, so their titles must be parsed
into title + mix name before writing (§7a).

**F26 — the `(From "…")` suffix is a _compilation_ artefact, and spotify's ISRC
search exposes every release a recording appears on.**
`GET /v1/search?q=isrc:{ISRC}&type=track` returns one entry per release. for
`INS181700238` (Arijit Singh — Roke Na Ruke Naina) it returns **ten**:

```text
[single     ] 2017-02-14 trk 2/5   Badrinath Ki Dulhania      | Roke Na Ruke Naina
[compilation] 2017-06-07 trk 5/20  Love Forever With Arijit…  | Roke Na Ruke Naina (From "Badrinath Ki Dulhania")
[compilation] 2018-02-06 trk 2/20  Arijit Singh: Love Songs   | Roke Na Ruke Naina (From "Badrinath Ki Dulhania")
…  nine compilations, every one suffixed
```

**the movie soundtrack release carries the clean title; only the compilations
add the `(From "…")` context** — they need it because the album gives no other
clue. so the suffix is not a bollywood convention to strip, it is a signal that
the _wrong release_ was chosen. picking the right release removes it for free.

**F27 — release preference: `album` > `single` > `compilation`, earliest first.**
"earliest non-compilation" was the obvious rule and it is **wrong**: for
`USJI10000001` (\*NSYNC — Bye Bye Bye) the earliest non-compilation is a
**1-track single**, which would set `track 1/1` and discard the album entirely.
the album release is the better attribution:

```text
[single     ] 2000-01-17 trk 1/1   Bye Bye Bye           ← earliest, but 1/1
[album      ] 2000-03-21 trk 1/12  No Strings Attached   ← correct
[compilation] 2005-10-25 …         Greatest Hits         ← plus 7 more
```

the type-ordered rule is correct on all four probes:

| ISRC           | chosen release                                   | why                                           |
| -------------- | ------------------------------------------------ | --------------------------------------------- |
| `USJI10000001` | `No Strings Attached` (album, 1/12)              | album beats the 1/1 single                    |
| `USUG12509635` | `ODYSSEY` (album, 7/19)                          | album beats same-day single                   |
| `INS181700238` | `Badrinath Ki Dulhania` (single, 2/5)            | no album exists; soundtrack wins, clean title |
| `GBARL2501127` | `Blessings — The Remixes (Part 2)` (single, 4/6) | only release                                  |

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

```text
Lat Lag Gayee   spotify artists[]: ['Benny Dayal', 'Shalmali Kholgade', 'Pritam']   ← composer last
Badtameez Dil   spotify artists[]: ['Pritam', 'Benny Dayal', 'Shefali Alvares', …]  ← composer first
Jee Karda       spotify artists[]: ['Sachin-Jigar', 'Divya Kumar']                  ← composers first
```

musicbrainz resolves the roles in **two hops**. the recording gives performers
and a link to the work; the work gives composer and lyricist:

```text
/ws/2/isrc/INT101202571?inc=artist-credits+artist-rels+work-rels
   artist-credit : Benny Dayal & Shalmali Kholgade      ← Pritam already excluded
   vocal         : Benny Dayal
   vocal         : Shalmali Kholgade
   performance   : → work fe49ff82-…

/ws/2/work/fe49ff82-…?inc=artist-rels
   composer      : Pritam
   lyricist      : Mayur Puri                            ← not in spotify's list at all
```

**two things fall out.** musicbrainz's `artist-credit` _already_ excludes
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

what _is_ usable is `track.name`, which carries the feature explicitly:

```text
Sweet Nothing (feat. Florence Welch)   artists: ['Calvin Harris', 'Florence Welch']
Body & Soul (feat. Biig Piig)          artists: ['Emotional Oranges', 'Biig Piig']
```

**the tempting heuristic — `track.artists` minus `album.artists` — must not be
used to assign roles.** it fails in two measured ways:

```text
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

```text
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

```text
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
and disc numbers must come from the _chosen_ release.** measured on
`USJI10000001` (\*NSYNC — Bye Bye Bye):

```text
musicfetch appleMusic.id  1741747057
  itunes lookup   album='Beach Beats'          trk=138/150  disc=1/1   ← a 150-track compilation
  spotify (§7b)   album='No Strings Attached'  trk=1/12     disc=1     ← correct
  library today   album='No Strings Attached…' trk=1        disc=1
```

**`138/150` is what F4's design would have written.** the appleMusic id musicfetch
returns is whichever release its matcher landed on, frequently a compilation —
`Beach Beats` here, `Naacho Naacho - Party Songs` for `Kamariya`. iTunes has no
ISRC search, so the _set_ of apple releases cannot be enumerated to pick a better
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

| ISRC           | chosen release | spotify earliest | itunes     | musicbrainz |
| -------------- | -------------- | ---------------- | ---------- | ----------- |
| `USJI10000001` | 2000-03-21     | **2000-01-17**   | 2000-01-11 | n/a         |
| `GBARL1201392` | 2012-10-29     | **2012-10-11**   | 2012-10-11 | 2012-04-16  |
| `INS181801821` | 2018-08-22     | **2018-08-09**   | 2018-08-09 | n/a         |
| `USUG12509635` | 2026-02-05     | **2026-02-05**   | 2026-02-06 | 2026-02-05  |

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

**F34 — musicfetch's artwork is the artwork of _its_ release, which is often a
compilation.** for `USJI10000001` musicfetch returns a 1400×1400 image whose URL
carries UPC `196872030730` — **`Beach Beats`**, a stock beach photograph. the
correct `No Strings Attached` cover is UPC `012414170224`. verified by md5 and
by eye; they are unrelated images.

```text
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

```text
§7b picks the release via spotify  →  album name + artist
  ↓
itunes /search  term="{artist} {album}"  →  collectionId for that album
  ↓
artworkUrl100 → substitute 3000×3000 (F5)
```

confirmed working end to end: the `No Strings Attached` URL upgrades to
**3000×3000, 2.2 MB**.

**F35 — itunes _search_ does enumerate releases; only the lookup-by-id is
single-release.** `GET /search?term=…&entity=song` returned **11 distinct
releases** of `Bye Bye Bye`:

```text
No Strings Attached          1/12   2000-01-17   ← the album
Bye Bye Bye - Single         1/1    2000-01-11   ← the single
The Essential *NSYNC         9/17   2000-01-11
Greatest Hits                1/12   2000-01-11
…plus workout compilations and a soundtrack
```

so iTunes _can_ be release-selected, by text rather than ISRC. the catch is that
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

```text
entity=album  term='Calvin Harris 18 Months'      1 result,  0 album hits
entity=song   term='Calvin Harris Sweet Nothing'  24 results, 2 album hits → collectionId 1713469222
```

the two-entity chain reproduces musicfetch's results **byte for byte**:

| ISRC           | album               | via            | size    |
| -------------- | ------------------- | -------------- | ------- |
| `USJI10000001` | No Strings Attached | `entity=album` | 2256 KB |
| `INS181801821` | Stree               | `entity=album` | 1755 KB |
| `GBARL1201392` | 18 Months           | `entity=song`  | 2162 KB |
| `USUG12509635` | ODYSSEY             | `entity=album` | 2919 KB |

**musicfetch is therefore removed from tier 1 entirely** (operator decision). it
remains **required for tier 0**, where `/url` is the only way to turn a youtube
link into an ISRC (F19).

**F38 — indian repertoire is 167 of 1,494 tracks, and two signals agree on it.**

```text
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

**class A — true duplicates (3).** identical audio md5 _and_ identical ISRC; the
second copy carries a space and `(2)` as a filename suffix:

```text
Tiësto - The Business / (2)              85b48197…  same bytes
John Summit & Feid - CHICA 305 / (2)     635e4af1…  same bytes
NAV - My Business (ft. Future) / (2)     c11219b3…  same bytes
```

**class B — same ISRC, genuinely different recordings (2).**

```text
Bebe Rexha - New Religion             174s   ← spotify says 174s  ✓
Bebe Rexha - New Religion [Extended]  248s   ← wrong ISRC, inherited from the edit
Emotional Oranges - Call It Off / (ft. JAEHYUN)
```

**class C — an ISRC on an entirely unrelated song (1).**

```text
INS181600966  spotify: 'Sau Tarah Ke', 238s
  Sau Tarah Ke.aiff          238s  ✓ correct
  Jai Jai Shivshankar.aiff   230s  ✗ a completely different song
```

**F40 — duration identifies a wrong ISRC, and the tolerance is tight.**
across 26 sampled tracks, local duration vs the ISRC's spotify duration:

```text
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

```text
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

| field                           | count | coverage |
| ------------------------------- | ----- | -------- |
| `title` `genre` `date` `artist` | 1494  | 100%     |
| `disc` · `album`                | 1491  | 99.8%    |
| `track`                         | 1490  | 99.7%    |
| `album_artist`                  | 1451  | 97.1%    |
| `TSRC` (ISRC)                   | 1439  | 96.3%    |
| `publisher` (label)             | 1069  | 71.6%    |
| `TIT3` (mix name)               | 99    | 6.6%     |
| `TPE4` (remixer)                | 46    | 3.1%     |
| `TEXT` (lyricist)               | 25    | 1.7%     |
| `composer`                      | 22    | 1.5%     |

fourteen fields, and the gaps say what this project adds: **no `TBPM`, no
`TKEY`** anywhere (beatport supplies both at 100% of matches — F14), composer and
lyricist under 2% (the musicbrainz work hop fills these — F28), and label missing
on 28%.

note `TIT3` (99) exceeds `TPE4` (46) by 53. that is **correct, not a gap**: the
difference is extended mixes and radio edits, which carry a mix name and have no
remixer (§7a).

**F43 — the `- Topic` test is primary; duration does NOT catch lyric videos.**
enumerating `ytsearch5:Arijit Singh Roke Na Ruke Naina`:

```text
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

```text
INS181600966   md5 95eff850…   Jonita Gandhi & Amit Mishra - Sau Tarah Ke.aiff
INS181600966   md5 fe6d0c18…   Vishal Dadlani & Benny Dayal - Jai Jai Shivshankar.aiff
```

two unrelated songs, one ISRC (F39 class C). **any override or correction keyed
by ISRC is ambiguous** — it cannot express which of the two files it means. the
decoded-audio md5 is unique per recording and stable across renaming and
retagging, so it is the key for anything file-scoped (§9c).

ISRC remains the key for _recording_-scoped cache rows (§9a), where the ambiguity
does not arise: those describe the catalogue entry, not a file on disk.

**F45 — a spotify track URL yields the ISRC directly, for free.**
`GET /v1/tracks/{id}` returns `external_ids.isrc` alongside name, duration, album,
track and disc number — everything §7b needs, in one unauthenticated-tier call:

```text
external_ids  {'isrc': 'GBARL2501127'}
album         Blessings - The Remixes (Part 2) | trk 4/6 | disc 1
duration      189 s
```

this makes "paste a spotify link" a complete identity solution for a file with no
ISRC (§9d), with **no musicfetch call and no fingerprinting**.

**F46 — label: spotify has no label field at all; discogs' _release_ endpoint is
the clean source.** measured across three tracks.

**spotify does not expose it.** the full album object under client-credentials has
no `label` key whatsoever:

```text
keys: album_type artists copyrights external_ids external_urls genres href id
      images name release_date release_date_precision total_tracks tracks type uri
```

only `copyrights` — `"© 2022 XO Records, LLC and Republic Records,…"` — which is
a legal entity string, not an imprint. itunes is the same shape (`℗ 2022 XO
Records, LLC and Republic Records, a division…`). parsing a label out of either
is lossy guesswork.

**discogs' `/database/search` is unusable for this** — its `label` array
conflates labels, sub-labels, publishers, pressing plants and **recording
studios**:

```text
['T-Series', 'Super Cassettes…', …, 'Yash Raj Studio', 'Audiogarage Studios',
 'Enzy Studios', 'J.S. Workstation', 'Sound Ideas Studio']
```

**`/releases/{id}` is clean.** labels are typed, and studios are correctly
separated into `companies[]` with their roles:

```text
labels[]  : ['T-Series (Label)']
companies : ['Super Cassettes Industries Pvt. Ltd. [Copyright (c)]',
             'Future Sound Of Bombay [Mixed At]']        ← not labels
```

```text
Demons Protected By Angels  labels: XO, Republic Records
18 Months                   labels: Sony Music, Fly Eye, Columbia, Deconstruction
Badrinath Ki Dulhania       labels: T-Series
```

so discogs requires **two calls** (search → release) and the second is the only
one worth reading. filter `labels[]` on `entity_type_name == "Label"`.

**F47 — discogs `styles` is a better genre fallback than itunes.**

| release                    | discogs style               | discogs genre  | itunes genre |
| -------------------------- | --------------------------- | -------------- | ------------ |
| Demons Protected By Angels | `Trap`                      | Hip Hop        | Hip-Hop/Rap  |
| 18 Months                  | `House, Synth-pop, Electro` | Electronic     | Dance        |
| Badrinath Ki Dulhania      | `Bollywood, Soundtrack`     | Stage & Screen | Bollywood    |

`House / Synth-pop / Electro` against itunes' flat `Dance` is the difference that
matters for a DJ library. discogs slots **below beatport, above itunes** in the
genre chain (§7).

**F48 — `bestaudio` degrades silently; an exact itag fails loudly.** measured on
the same track, same moment:

```text
-f 999        (nonexistent)       ERROR: Requested format is not available   ← loud
-f bestaudio  with cookies        774  293k opus     ← premium, but OPUS not AAC
-f bestaudio  without cookies     251  151k opus     ← SILENT degradation
```

two separate problems with `bestaudio`:

1. **it hides cookie failure.** without valid premium cookies it quietly returns
   151k opus and reports success. this is exactly how the library could fill with
   the wrong quality unnoticed (F20).
2. **it picks opus over AAC** — 293k beats 258k on bitrate alone, so `bestaudio`
   selects itag 774 even when 141 is available. the existing 1,494 files are all
   **AAC 257k** (F20), so `bestaudio` would silently change the library's source
   codec.

**the format selector is `141/774`, never `bestaudio`.** prefer AAC 256k for
consistency with the existing library; fall back to premium opus; **fail loudly**
if neither is offered rather than accepting 151k.

**F49 — opus 293k carries no information the AAC 258k lacks.** measured on the
same track, both premium formats downloaded and compared by band energy (RMS dB,
both resampled to 48 kHz):

| band (Hz)   | AAC 141 | OPUS 774 | delta    |
| ----------- | ------- | -------- | -------- |
| 14000-16000 | -46.8   | -46.7    | +0.1     |
| 16000-18000 | -48.9   | -48.7    | +0.2     |
| 18000-19000 | -53.1   | -53.0    | +0.1     |
| 19500-20000 | -57.0   | -57.5    | **-0.5** |
| 20000-21000 | -57.0   | -58.7    | **-1.7** |
| 21000-22000 | -61.4   | -66.0    | **-4.6** |

**opus has _less_ high-frequency energy, not more.** and above AAC's 22.05 kHz
nyquist — where opus at 48 kHz could hold content AAC physically cannot — there
is nothing:

```text
OPUS 22050-23000 Hz : -79.9 dB     ← filter skirt, 53 dB below the music
OPUS 23000-23900 Hz : -103.0 dB    ← silence
   (reference, 1000-2000 Hz: opus -27.0, aac -27.0 — identical)
```

so the higher bitrate reflects **opus's different encoding, not more
information**. the two are within 0.2 dB across the entire audible band.

**decision: stay on AAC (itag 141) for new downloads.** four reasons, in order of
weight:

1. **no measurable quality advantage to opus** — the above.
2. **consistency.** the existing 1,494 files are AAC 257k and reproduce
   byte-identically (F20). mixing source codecs makes the library
   inhomogeneous for no gain.
3. **DJ-app compatibility.** rekordbox and serato handle AAC natively; opus
   support is inconsistent.
4. **the container is moot anyway.** both are converted to AIFF (OQ-6), and AIFF
   preserves whatever the lossy decode produced — **neither format is "upscaled"
   by the conversion**, and neither recovers anything the encoder discarded.

`774` stays as the fallback in `-f 141/774` (F48): premium opus is far better
than the 151k non-premium alternative if AAC is ever unavailable.

_measured on one track. the finding is a decision input, not a claim about every
encode on youtube._

**F50 — AIFF cannot hold AAC; the conversion is a decode, not a remux.** this
matters because it determines what the 5.4x storage cost is actually buying.

```text
ffmpeg -i source.m4a -c:a copy -y out.aiff
  [aiff] block align not set
  [out#0/aiff] Could not write header (incorrect codec parameters ?)
```

**AIFF is a PCM container.** there is no "put the AAC into an AIFF" operation —
the AAC is decoded to PCM and the PCM is stored:

```text
source  aac, fltp (float planar), 44100 Hz, stereo
output  pcm_s16be, s16,           44100 Hz, stereo     ← matches the existing library exactly
```

**the decode is faithful.** the decoded-audio md5 of a freshly converted AIFF
equals the decoded-audio md5 of the source m4a (`bae6e47a…`, the same value
recorded in F20) — the AIFF contains precisely what the AAC decodes to, with no
resampling and nothing added.

**so the conversion buys metadata, not audio quality.** it cannot improve on the
lossy source (F49), and it costs **5.4x** — 5.0 MB → 27 MB on the measured track,
consistent with the library-wide 9.5 GB → 51.9 GB (OQ-6).

what it buys is real: **AIFF carries ID3, and both DJ apps read it.** the
existing library proves the full frame set survives — `TPE4`, `TIT3`, `TSRC`,
`TPUB` are all present and readable (F25, F42). M4A stores metadata in MP4 atoms,
where rekordbox and serato support for the DJ-specific frames is inconsistent.
**that compatibility is the entire justification for the storage cost, and it is
a sufficient one.**

**16-bit, not 24.** the source decodes to float, but the existing 1,494 files are
`pcm_s16be` and a lossy source carries no information that a 24-bit store would
preserve. 16/44.1 matches the library and costs 33% less than 24-bit.

**F51 — spotify's search caps `limit` at 10, and one ISRC returns 34 releases.**
measured 2026-09-14 against the operator's own client credentials:

```text
limit=10  HTTP 200   10 items
limit=20  HTTP 400   {"error": {"status": 400, "message": "Invalid limit"}}
limit=50  HTTP 400   same
```

the published range is 0-50
([developer.spotify.com/documentation/web-api/reference/search](https://developer.spotify.com/documentation/web-api/reference/search),
checked 2026-09-14); the live API disagrees, and the live API wins.

**this matters because F33 takes the MIN release date over ALL releases.**
paginating `USJI10000001` to exhaustion returns **34 releases across 4 pages** —
§5a's worked example saw only the first 10. search returns _relevance_ order,
not date order, so a later page can carry an earlier release and stopping at
page one would silently write the wrong year.

```text
USJI10000001   34 releases   4 pages
INS181801821   15 releases   2 pages
GBARL2501127    1 release    1 page
```

**`tracks.total` is not usable as a stopping condition** — the same query
returned `total: 34` and then `total: 0` within a minute. pagination therefore
stops on an **empty or short page**, never on a count.

the cost is real: a popular recording now costs up to 4 calls instead of 1,
against F8's 20 req/min. it is not optional — §7b's ranking and F33's date both
operate over the full candidate set.

**F52 — musicbrainz names composers in indian repertoire and `writer`
everywhere else.** measured 2026-09-14 over two samples of the library, walking
`/ws/2/isrc/{ISRC}` -> performance relation -> `/ws/2/work/{id}?inc=artist-rels`:

| sample                   | recordings found | linked to a work | `composer` | `lyricist` | `writer` |
| ------------------------ | ---------------- | ---------------- | ---------- | ---------- | -------- |
| indian (`IN` prefix), 12 | 10               | 10               | **10**     | **11**     | 0        |
| western, 12              | 12               | 6                | 0          | 0          | **34**   |

**this confirms §7d rather than contradicting it.** F28's claim — that
musicbrainz separates performers from composers — holds precisely where §7a
scopes the rule: indian repertoire, where the distinction is editorially
maintained and coverage was 10/10.

western works use the generic `writer` relation, which records _that_ someone
wrote the work and not _which role they held_. **`writer` is therefore not
written to `TCOM` or `TEXT`.** promoting it would assert a role musicbrainz
deliberately left unstated, and §7f's rule applies: a wrong value is worse than
a missing one, because a wrong one gets trusted. the practical cost is that
western tracks usually carry no `TCOM`, which §7d already anticipated
("it is simply rarer that musicbrainz has it").

two operational facts from the same probe, neither previously recorded:

- **a `User-Agent` is mandatory** — the API returns `HTTP 403` without one.
- **`currently busy` is `HTTP 503`**, and the very first request of this probe
  received one. F30 is not a historical curiosity; it fires routinely, and a
  client that treats it as a miss silently drops artist credits.

**F53 — G6 measures 85.4%, not ≥95%, and where the two sources disagree the
filename is usually the better one.** measured 2026-09-14 over all 398 featured
tracks, cross-checking musicbrainz `artist-credit` joinphrases against the
filename:

```text
featured tracks            398
  no ISRC                   20
  musicbrainz has none      23
  cross-checked            355
  agree                    303
  disagree                  52
  G6                      85.4%   (gate target >= 95%)
```

**§6's claim that the filename "agreed with musicbrainz on every case where both
were present" does not survive the full population.** it held on the 30-track
sample it was written from; at 355 tracks it does not.

the 52 disagreements are not one thing:

| n   | class                                                        | which source is right                                                            |
| --- | ------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| 19  | musicbrainz credits **fewer** artists                        | the filename — musicbrainz is missing a credited feature entirely                |
| 13  | musicbrainz **flattened the feature** into main, same people | the filename — it marks the boundary the operator intended                       |
| 8   | genuinely different personnel                                | neither, reliably — `Quango Rondo` vs `Quango Quango`, `Carnage` vs `DJ Carnage` |
| 7   | musicbrainz credits **more** artists                         | musicbrainz — it names co-producers the filename omits                           |
| 5   | same people, boundary differs                                | usually the filename                                                             |

**18 of 52 (35%) name exactly the same people and differ only on where the
main/featured boundary falls.** counting those as agreement gives **90.4%** —
still short of the gate.

the structural claim behind §6 needs qualifying: musicbrainz's `joinphrase` is
authoritative **when it marks a feature**, but it frequently does not. on
`Blxst - Risk Taker (ft. Offset)` musicbrainz joins both artists with `&` and
the feature disappears. the operator typing `(ft. Offset)` is the more
deliberate signal for that one question.

**resolved (operator decision): the filename decides the boundary, musicbrainz
decides the personnel.** where both sources name exactly the same people and
differ only on where the feature boundary falls, the filename wins — the
operator typed `(ft. …)` deliberately, and musicbrainz is usually the one that
lost it. where they name _different_ people, the track is flagged and queued,
never auto-resolved.

re-measured under that policy:

```text
  cross-checked            357
  agree                    323
  disagree                  34
  G6                      90.5%   (gate target >= 88%, set from this measurement)
```

**what G6 is really comparing.** it cross-checks musicbrainz against the
_filename_, and the filename is effectively what the library already says:

```text
featured tracks                                    398
  filename artist identical to the existing TPE1   397   (99.7%)
  existing tags put the feature in the title       398   (100%)
  existing tags put the feature in the artist        0
```

so G6 is not an abstract source comparison — it measures **how often musicbrainz
disagrees with the tags the operator already has**, and §7a's chosen shape
(feature in the title, option A) is the shape those tags are already in. the one
mismatch is `David Guetta & Kid Cudi - Memories (ft. Kid Cudi)`, where the
filename names Kid Cudi as both a main artist and a feature.

the 34 disagreements that survive the boundary rule break down as:

| n   | what musicbrainz does                | note                                    |
| --- | ------------------------------------ | --------------------------------------- |
| 19  | **drops** an artist the library has  | accepting it would lose a credit        |
| 7   | **adds** an artist the library lacks | usually a co-producer                   |
| 6   | both drops and adds                  |                                         |
| 2   | spells a name differently            | `DJ Carnage`/`Carnage`, `Lemar`/`Lamar` |

**in 19 of 34 cases, accepting musicbrainz would remove a credit that is already
there.** that is the strongest argument against auto-resolving toward
musicbrainz, and it is why the queue exists: the default has to be a human
looking at both, not a rule preferring whichever source is nominally more
structured. the two spelling cases are worth flagging rather than folding away —
`Damian Lamar Hudson` vs `Damian Lemar Hudson` is a likely typo in the library,
which is exactly the kind of thing review should catch.

**F54 — apple's artwork ceiling is the album's own master, and it varies.**
measured 2026-09-14 by requesting sizes above 3000 and reading the JPEG headers:

```text
No Strings Attached   asked 3000 -> 3000x3000  2256 KB
                      asked 4000 -> 3600x3600  2969 KB
                      asked 4500 -> 3600x3600  2969 KB   (same bytes)
                      asked 5000 -> 3600x3600  2969 KB   (same bytes)

18 Months             asked 3000 -> 3000x3000  2162 KB
                      asked 4500 -> 3000x3000  2162 KB   (same bytes)
```

**there is no single ceiling.** F5 records 4500x4500; neither album reaches it.
apple serves each album's own master and silently returns that for any larger
request — over-asking never errors, it just stops growing.

this makes OQ-1's decision a **storage** choice rather than a technical limit,
and a safe one: every album measured serves at least 3000, so asking for 3000
never over-asks and never needs the step-down. the 3000 -> 1400 -> 600 ladder
stays for non-200s and short reads, which is what §7c actually specified it for.

the §7c table reproduces exactly at 3000, byte for byte, four years after it was
first measured:

```text
No Strings Attached   2256 KB   via album search
Stree                 1755 KB   via album search
18 Months             2162 KB   via SONG search   <- F37's case
ODYSSEY               2919 KB   via album search
```

**F55 — the beatport session endpoint is behind cloudflare, and `cf_clearance`
is bound to the User-Agent.** measured 2026-09-14 with a freshly exported jar:

```text
no User-Agent      HTTP 403   "Just a moment..."  (cloudflare interstitial)
browser User-Agent HTTP 200   {"token": {"accessToken": ...}}  1147 chars
```

F6 records that cloudflare fronts the **web** host and not the API host — and
`/api/auth/session` is on the web host, so it is challenged. the exported jar
contains a `cf_clearance` cookie, which cloudflare issues against the browser's
User-Agent; replaying it under a different one fails the challenge.

**so the client must send a browser User-Agent**, and the export must come from
the same browser the session was created in. this is not a workaround for a
challenge solver (§11 rules that out) — it is replaying a clearance the operator
already holds.

the minted token measured **1147 chars** against F11's ~1156, and the session
expiry was a month out, both as F11 describes.

**the export is now one command** (`tools/bp_cookies.py export`). chrome's
cookie store is encrypted with a macOS keychain key, and `yt-dlp` — already a
dependency for tier 0 — decrypts it, so no keychain access is reimplemented.
**only `beatport.com` cookies are written, `0600`**: the browser jar holds every
site the operator is logged into, and writing all of it would turn one
credential into dozens.

**F56 — spotify's 429 is a 12-hour quota ban, not a burst cooldown.** measured
2026-09-14 at 23:10, on a client-credentials token, after ~60 tracks of a full
pass at 10 req/min:

```text
GET /v1/search?q=isrc:...   HTTP 429   Retry-After: 43868    (12.2 hours)
```

there is no `X-RateLimit-*` header — `Retry-After` is the only signal, and it is
given in seconds. **the body names the cause**:

```json
{
  "error": {
    "status": 429,
    "message": "Too many requests",
    "reason": "QUOTA_EXCEEDED"
  }
}
```

**this is a quota, not a rate limit, and spotify treats the two differently.**
the rate limit is calculated over a rolling 30-second window and is fixed by
slowing down. the quota is a budget, counted **per developer account** (not per
client id) since the July 2026 change, and no request rate satisfies it — the
`reason` field exists precisely to tell them apart.

**spotify does not publish the development-mode quota**, and extended quota
mode is not available to us: since 2025-04-15 it requires a registered business
with a launched service and **at least 250k MAU**. so the budget has to be
measured, which is why `Source.requests` counts every call — retries included,
since they spend the same budget.

**the consequence for our earlier reasoning: halving the request rate from 20 to
10/min was a fix for a problem we did not have.** it addressed a rate limit we
have never been shown to hit, and doubled the length of a pass. the rate is back
to 20/min (10 per rolling window) and the quota is handled by stopping.

measured cost of a pass, from the 61 cached tracks: **86 search requests for 61
tracks — 1.41 pages each** (52 tracks took 1 page, one took 10). extrapolated,
a full 1,439-track pass costs **~2,030 search requests**. `limit` cannot be
raised to amortise this: the search endpoint's published range is `0`-`10`,
confirming F51.

**this changes how a 429 has to be handled, in two ways.**

first, the value is real advice and worth reading, but **not worth sleeping
on**. F8's token bucket is sized for a _burst_ limit; 43,868 seconds is a rolling
quota window, and no amount of backing off inside one run will clear it. the
run has to end and resume after the window.

second — and this is the expensive one — **skipping the track is worse than
stopping.** `resolve` fetches spotify first and `continue`s past the rest of the
track on failure, so a skipped track banks no musicbrainz, itunes or discogs
either. carrying on after a ban therefore walks every remaining track, caches
nothing, and re-asks a service that has already stated how long it will keep
refusing. a measured pass did exactly that: 1,376 tracks of pure waste, and a
plausible risk of extending the window.

so `RateLimitedError` is raised the moment a `Retry-After` exceeds
`MAX_RETRY_AFTER_S`, without spending the remaining attempts, and `resolve`
stops the pass and reports the wall-clock time to resume. **everything already
fetched stays cached**, so resuming costs only the tracks that were never
reached.

**the cap is not a maximum wait, it is the line between the two behaviours**: at
or below it a server is throttling and waiting is correct; above it a server has
cut us off and only stopping is.

**F57 — the same recording acquired twice in different formats is invisible to
both existing duplicate tests.** measured 2026-09-14 on the operator's own
files:

```text
beatport/…I don_t even speak spanish lol (Original Mix).wav
  pcm_s16le  192.229365s  md5 db00b698…  isrc = none
library/XXXTENTACION - I don't even speak spanish lol (ft. …).aiff
  pcm_s16be  192.229365s  md5 bae5aa52…  isrc = USUG11800451
```

**the duration agrees to the microsecond and nothing else does.** the hashes
differ because the library copy is youtube-sourced — lossy decoded to PCM —
so it is not the same master; re-hashing both normalised to `s16le` confirms
the samples genuinely differ, so this is not an endianness artefact. and §11a's
other key is unavailable: **the store `.wav` carries no ISRC at all**.

so class D matches on **duration plus title**, and is **never automatic**. the
duration signal alone is not safe: 22 exact-duration collision groups were
measured across 1,494 files, and most are unrelated tracks sharing a round
youtube duration (`159.000000`, `192.000000`). the title check separates them
cleanly — the real pair scores 12/12 shared words, the nearest false positive
scores 0.

running it over the library plus `beatport/` found **2 class-D groups and no
false positives**: the pair above, and `Emotional Oranges - Call It Off` against
its own `(ft. JAEHYUN)` copy at 216.933333s.

**two consequences beyond the class itself.**

first, **`apply` was writing both sides of every class-A pair**, which would
have failed G11 ("no two output files share an audio md5") on the three known
byte-identical pairs. it now emits one copy and reports the other.

second, **which copy survives cannot be decided by path order**. `CHICA 305
(2).aiff` sorts _ahead_ of `CHICA 305.aiff`, because a space precedes a dot —
so first-by-path would have kept every re-download and dropped every original.
`preference_key` ranks store over rip, lossless container first, and an
unsuffixed name over an F39 `(2)` re-download.

**F58 — soundcloud is a viable acquisition source, but its recordings are
mostly outside every identity service we have.** measured 2026-09-15.

**acquisition.** `yt-dlp` (2026.08.19) ships nine soundcloud extractors and can
fetch the uploader's **original file** — the one behind the "free download"
button — at `quality: 10`, so `-f bestaudio` prefers it automatically. reading
the extractor, that path requires **all three** of:

```text
downloadable        the uploader enabled the download button
has_downloads_left  soundcloud caps free downloads per track
authenticated       401 otherwise: "only available for registered users"
```

when any of those fails the fallback is the stream: **AAC 128/160 kbps CBR, or
opus 64 kbps VBR**. that is _worse_ than the youtube path, so unlike tier 0
today, **a soundcloud download is only worth taking when the original is
available** — the stream is a downgrade, not a fallback. the operator's two
existing files are 320 kbps mp3, consistent with an original-file download.

**identity is the real problem, and it is not that the ISRC is missing.** the
recordings do not exist:

```text
"Secondhand (Med Aven Remix)"   musicbrainz 0 real hits   itunes 0 hits
"CHOSEN (HUGO. EDIT)"           musicbrainz 0 real hits   itunes 0 hits
"Don Toliver, Rema - Secondhand"  musicbrainz + itunes: exact, first hit
```

an unofficial edit has no ISRC because no label ever registered it. the _source_
recording resolves perfectly.

**and musicbrainz answers wrongly rather than emptily, at full confidence:**

```text
"Secondhand Med Aven Remix"  -> [100%] Gipsy Kings — "Aven, aven"
"CHOSEN HUGO EDIT"           -> [100%] Arena — "Chosen (edit)"
```

**the `score` is relevance, not confidence.** itunes returned zero for both,
which is the honest answer; musicbrainz returned a 100% match to a different
song. so **tier 0 must never take identity from a musicbrainz text search** —
the failure mode is not "no result", it is a confident wrong one, and G9's rule
against cross-recording contamination is exactly what it would violate. no such
search exists in the code today (musicbrainz is ISRC-only), and it must stay
that way.

the workable model is therefore **identify the source recording, and record the
file as a derivative of it** — not "find this recording", which has no answer.
that is a different shape from §10's tier 0 and needs its own design.

one thing soundcloud gives that no service does: **the uploader's own BPM tag**
(measured `TBPM=95` and a malformed `TBP=139` on the operator's two files).
§7e leaves BPM empty rather than guessing, and for an edit that nothing else
lists, the producer's own value is the best evidence available.

**F59 — the acoustic fingerprint matches where the audio hash cannot, which is
the whole reason it exists.** measured 2026-09-15 on F57's cross-format pair —
the beatport `.wav` and the youtube-derived `.aiff` whose decoded-audio md5s are
completely different:

```text
chromaprint (fpcalc -raw), 948 samples each
  exactly equal samples   906 / 948   (95.57%)
  bit error rate          0.1450%
```

acoustid's match threshold sits around 5-10% BER, so **0.145% is an
overwhelming match**. the two signals answer different questions and the
difference is not a defect in either:

```text
audio md5     "are these the same bytes?"        no  — one went through a lossy step
chromaprint   "are these the same recording?"    yes — 99.855%
```

chromaprint is built to survive exactly this: re-encoding, bitrate changes,
lossy round-trips. **so the md5 divergence is an argument _for_ fingerprinting,
not against it** — it is the case F44's hash provably cannot decide, and the one
acoustid submission would resolve. §15's fingerprint column stands.

this also gives class D (F57) a stronger test than duration plus title: a
fingerprint comparison decides the same pair at 99.855% instead of inferring it
from a filename. duration and title remain the cheap pre-filter, since computing
fingerprints for 1,501 files to find 2 pairs is the wrong order of work.

**F60 — soundcloud go+ raises the fallback but never beats the original
file.** `yt-dlp`'s extractor ranks its formats:

```text
quality 10   "download"      the uploader's original file (F58's three conditions)
quality  5   premium         256 kbps AAC, go+ only        (is_premium = quality == 'hq')
quality  0   >=160 kbps      free tier
quality -1   everything else  opus 64 kbps VBR
```

go+ streaming is **256 kbps AAC**, gated on both a subscription _and_ the track
having been uploaded losslessly. it is better than the youtube path and better
than the free tier's 96/160k — but it is still a lossy transcode, and `-f
bestaudio` will prefer the original download over it whenever one exists.

so go+ buys a better **fallback**, not a better best case. it is worth having
for tracks with the download button off, and the cookie mechanism is the one
already built for youtube and beatport (`--cookies-from-browser`), so nothing
new is needed to use it.

**F61 — `service_ids` is retired.** the table recorded how each service link was
matched (F9's exact-vs-search distinction), but **nothing ever wrote to it**.
the only search-derived link the pipeline actually produces is beatport's, and
`Match.matched_by` already carries that inline — the table was a second home for
a fact that has one. it is dropped on open, and only when empty: a table holding
rows would be a migration, not a deletion.

**a correction to how this was first written here.** it said beatport's ISRC
lookup "fails" on the 9 remixes, so those fall back to a less certain search.
that reads F22 without F23. the lookup does not fail — **it correctly returns
nothing**, because the library holds the radio edits and beatport holds the
DJ-length extended mixes, and F23 measured the gap at +80s to +137s. those are
different recordings, and an ISRC that identified both would be the bug.

so for beatport the `matched_by` axis is not the meaningful one. finding the
listing by search is the _intended_ path for a remix, and what governs trust is
the **duration field class** (§7, G3) — already first-class as
`CLASS_SAME_RECORDING` / `CLASS_DIFFERENT_EDIT`, and already enforced: genre,
sub-genre, label and remixer transfer either way, while bpm, key and length
transfer only within ±5s, and **beatport's ISRC never transfers at all** (G9,
no tolerance). that is a second reason `service_ids` earned nothing: the
distinction it stored was the wrong one for the only source that would have
populated it.

**`Match.matched_by` is set but never read.** it is retained because it is free
and honest, but nothing depends on it.

**F62 — OQ-12 resolved: `MUSICMATCH_TOKEN` is the musicfetch token.** the name
looked like it belonged to a different service. measured 2026-09-15 against
`api.musicfetch.io`:

```text
x-token: <MUSICMATCH_TOKEN>        HTTP 200
Authorization: Bearer <same>       HTTP 401  {"message": "x-token header required"}
```

so the credential is correct and only the variable name is misleading. it is
left as-is rather than renamed, because renaming it would break the operator's
existing `.env` for no functional gain; this finding is the documentation.

**and F19 is confirmed, with one caveat it did not record: a youtube _video_ is
not a youtube music _track_.**

```text
Eo-KmOd3i7s  "*NSYNC - Bye Bye Bye (Official Video)"  -> no isrc, youtube services only
fxHjlCBHuzA  "Bye Bye Bye" by *NSYNC                  -> USJI10000001
```

an official-video upload is a separate entity that musicfetch cannot map to a
release, so F19's 8-of-8 holds for track links and not for video links. the
distinction is invisible in a browser — both are "the song on youtube" — so
`tools/yt_isrc.py` detects the case (a result carrying only `youtube*` services)
and says to use the track link, rather than reporting a failed lookup.

**the video case is recovered, not reported.** measured: the domain in a
youtube link is irrelevant and the video id is everything —
`youtube.com/watch?v=fxHjlCBHuzA` and `music.youtube.com/watch?v=fxHjlCBHuzA`
both resolve, and both spellings of `Eo-KmOd3i7s` resolve to nothing. so there
is no domain conversion to perform, and no way for the operator to tell the two
apart by looking. when a video is pasted, `isrc_recovery` reads the title off
it, searches youtube music for the track, and resolves that instead:

```text
youtube.com/watch?v=liZm1im2erU        (the official video)
  -> USRC11201220  A$AP Rocky, Drake, 2 Chainz, Kendrick Lamar — F**kin' Problems
     recovered from a video link by searching youtube music
```

**this reaches tracks spotify does not.** the operator could not find two
Calvin Harris remixes on spotify and assumed they were unavailable; both have
ISRCs, and both were recovered this way:

```text
Let's Go (Swanky Tunes & Hard Rock Sofa Remix)   GBARL1202144   350.9s ✓
Sweet Nothing (Diplo + Grandtheft remix)         GBARL1202425   306.0s ✓
```

**a recovered ISRC is checked before it is written.** G10's rule does not care
where an ISRC came from, and pasting the wrong link is the easy mistake when
working through 55 tracks by hand:

```text
SKIP  Becky Hill - My Heart Goes: USJI10000001 is 200s but the file is 149s
      (51s apart) — wrong track? (G10)
```

**F63 — §7c's candidate C was implemented, unit-tested, and never supplied.**
`resolve_artwork` takes `spotify_image_url` with a `None` default, and `resolve`
called it without that argument. so the last link in the artwork chain could
never fire: a track itunes could not find was flagged `no-artwork` while a
verified 640px cover sat unused in its own cached spotify payload.

```text
24kGoldn & Lil Tecca — Prada     itunes: 0 results   spotify: 640x640 present
24kGoldn — Checkers              itunes: 0 results   spotify: 640x640 present
```

both now resolve to `spotify-album-image` (89,813 and 160,597 bytes). the unit
test for candidate C passed throughout — it tested the function, and the defect
was in the caller.

**this is the third instance of the same shape**, and it is worth naming: a
capability built, tested in isolation, and never connected. `overrides` was
accepted by `arbitrate` and passed by nothing; `service_ids` had a writer and no
caller (F61); candidate C had an argument and no argument. **a unit test on the
component cannot see it.** what catches it is asserting the wired behaviour —
that a track with no itunes match still gets artwork — rather than that the
function returns artwork when handed a URL.

**F66 — the itunes _lookup_ endpoint reaches releases the _search_ index does
not carry.** the operator supplied a link for `Checkers`, which F65 had probed
as absent from the US, CA, GB, IN and AU search indexes under every term tried:

```text
GET /search?term=24kGoldn+Checkers        0 results   (every variant tried)
GET /lookup?id=1657261196                 1 result, artwork 3000x3000, 2.5 MB
```

so the release is on apple; only the search index does not surface it. **this
makes an operator-supplied link the most valuable artwork candidate**, not a
last resort: it needs no verification — nothing was guessed — and it beat the
spotify fallback by 3000px to 640.

`library.toml` therefore gains an **`artwork`** field. §9b's merge lets one
field do both jobs: it shows which cover was used, and accepts a
`music.apple.com` link (or a direct image url) where none was found. verified
end to end — the operator's link produced a 3000x3000 mjpeg embedded in the
output file.

**F67 — reading the map back made the pipeline treat its own output as the
operator's assertion.** `_overrides_for` returned every value in the map, but
the map holds generated values as well as typed ones. the consequences ranged
from cosmetic to permanent:

```text
generated artwork url  -> re-fetched, provenance recorded as `operator-supplied`
generated album name   -> pinned as a hand-edit, never updated again
```

**§9b already had the right test and it was not being applied**: a value that
differs from what was generated last run was typed by hand. `_overrides_for`
now applies it, and a run with no record of what it generated overrides
nothing.

two ways the map produced phantom edits, both now fixed:

- **an algorithm change reads as an edit.** reversing §7b's edition preference
  changed 15 album names and their spotify links; every one then looked
  hand-typed. this is inherent to the design — the map cannot tell _why_ a value
  moved — and the mitigation is that the generated snapshot is rewritten on
  every `write_map`, so the divergence only survives if the file is not
  regenerated.
- **a duplicated audio hash had no stable winner.** the three class-A pairs
  share an md5 and collapse to one entry, so `file` and `title` flipped between
  `CHICA 305.aiff` and `CHICA 305 (2).aiff` depending on visit order, and each
  flip read as an edit. the map now picks by `preference_key`, so the original
  always wins over the re-download.

after both fixes the operator's map reports **exactly the 5 values they typed**:
4 ISRCs and 1 artwork link.

**F65 — the itunes search finds nothing for an album name carrying an edition
qualifier.** measured 2026-09-15, and this is why §7c's chain was failing before
candidate C was even reached:

```text
entity=album  "24kGoldn El Dorado (Deluxe)"   ->  0 results
entity=album  "24kGoldn El Dorado"            ->  3 results, the album first
```

the verification compounded it: `matches_release` requires the chosen name to
be _contained_ in the result's, so even a successful search for `El Dorado`
would have been rejected against a chosen name of `El Dorado (Deluxe)`.

**the edition qualifier is the one part of an album name that does not identify
the record.** it is now stripped from the search term and from both sides of the
comparison, while the tag still carries the name §7b chose. apple's artwork is a
per-album master (F54), so the cover is the same either way.

**this interacts badly with the edition preference, and the interaction is
ours.** §7b was reversed the same day to prefer the expanded edition, which
raises the number of chosen album names carrying a qualifier: **22 of the 61
resolved tracks**. without this fix that reversal would have taken artwork away
from all 22.

measured after both fixes:

```text
Prada       itunes-album-search   3000px  from 'El Dorado'
Checkers    spotify-album-image    640px  from 'Checkers (feat. Bandmanrill)'
```

`Checkers` is genuinely absent from the itunes search index — probed against the
US, CA, GB, IN and AU stores, all zero — so candidate C is the correct answer
there, not a consolation.

**8 cached payloads hold a 0-result response** from the old query and will not
improve until refetched; the artwork step is skipped whenever the itunes payload
is already cached.

**F64 — "we never asked" was being reported as "there is nothing".** the quota
stop (F56) left every track past the cut-off with an empty candidate list, and
an empty list raised `no-release` — rendered as "no release found". the operator
reasonably read that as spotify failing on `The Business` and `CHICA 305`, when
in fact the pass stopped alphabetically at `A Boogie Wit da Hoodie — Luv Is Art`
and never reached them.

the two states are now distinct: `not-searched` when no payload is cached,
`no-release` only when one is and holds nothing. **an empty result is evidence;
an absent result is not**, and a gate that conflates them reports a failure the
operator then goes looking for.

**F8 — rate limits are gentler in practice than documented.**
published Starter is 6 req/min ([musicfetch.io](https://musicfetch.io/) pricing,
checked 2026-09-14). measured: **20 sequential requests at 1 req/s, all HTTP
200, zero 429s.** the 7-day trial is capped at 5,000 requests — 3.3× the whole
library, so the entire job fits inside the trial. the operator is on the
**business plan: 150k requests,
20 req/min**. we **respect the published limit rather than the measured one** —
the limiter is a token bucket at 20/min, not 1/s. a full 1,439-track pass is
then ~72 minutes, and resolution is cached so it is paid once.

**F9 — non-spotify service links are search-derived, not ISRC-verified.**
musicfetch documents that it resolves the ISRC on spotify, then _searches_ other
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

```text
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

```sh
ffprobe → TSRC = USJI10000001
```

if there is no ISRC, the track goes to the tier-0 path (§10) instead.

**step 1 — spotify, queried DIRECTLY by ISRC.** _(not via musicfetch)_

```text
GET /v1/search?q=isrc:USJI10000001&type=track&limit=10&offset=0…30
→ 34 releases across 4 pages (F51)
```

rank them `album > single > compilation`, then 1-track releases last, then
`release_date` ASC (§7b). this yields two different things:

```text
chosen release   → No Strings Attached | album artist *NSYNC | trk 1/12 | disc 1
earliest date    → 2000-01-17   = MIN(release_date) over ALL 34 releases
```

the chosen release supplies `album`, `album artist`, `track`, `disc`. the
earliest date supplies `date`/`year` — these come from **different rows** of the
same response (F33).

**step 2 — musicbrainz, also queried directly by ISRC.**

```text
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

```text
within ±5s  → same recording → take genre, sub_genre, label, bpm, key, mix_name
outside ±5s → different edit  → take genre, sub_genre, label ONLY (F23)
```

zero results is normal; genre then falls back to itunes.

**step 4 — artwork (§7c).** three candidates, all free, **no musicfetch** (F37):

```text
A  itunes /search?term='*NSYNC No Strings Attached'&entity=album
      here: 'No Strings Attached' == chosen album   → ACCEPT
B  itunes /search?term='*NSYNC Bye Bye Bye'&entity=song
      not needed here; this is the path that finds `18 Months`
C  spotify album image (~640px)                     → not needed
upgrade artworkUrl100 → 3000x3000bb.jpg             → 2256 KB
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

| file                                         | musicfetch `artists[]`           | correct reading                       |
| -------------------------------------------- | -------------------------------- | ------------------------------------- |
| `Arizona Zervas - OH MY LORD (ft. 24kGoldn)` | `['Arizona Zervas', '24kGoldn']` | main + **feature**, indistinguishable |
| `Internet Money - Options (ft. 24kGoldn)`    | `['Internet Money', '24kGoldn']` | main + **feature**, indistinguishable |

**398 of 1,494 files (26.6%)** encode a feature in the filename, and 401 carry
a separator in the artist part. this is not an edge case.

> re-counted 2026-09-14: an earlier revision said 418 and 28%. the library uses
> exactly one spelling — `(ft.` followed by a space — on 398 files; no
> `(feat.`, `(featuring` or bracketed variant occurs at all.
> **G6's denominator is 398.**

**musicbrainz solves it structurally.** its `artist-credit` array carries an
explicit `joinphrase` per element, so the boundary is machine-readable rather
than inferred:

```text
David Guetta - Little Bad Girl (ft. Taio Cruz & Ludacris)
  [('David Guetta', ' feat. '), ('Taio Cruz', ' & '), ('Ludacris', '')]
   ^^^^^^^^^^^^^ main        ^^^ the boundary    ^^^^^^^^^^ features
```

everything before the element whose `joinphrase` matches `/feat\.|ft\.|with/i`
is a **main** artist; everything after is **featured**. no string parsing of a
title, no guessing.

**itunes is not reliable for this** — it is inconsistent about where the feature
lives:

| track                       | `artistName`                            | `trackName`                                |
| --------------------------- | --------------------------------------- | ------------------------------------------ |
| Dua Lipa - Levitating       | `Dua Lipa`                              | `Levitating (feat. DaBaby)` — in the title |
| Arizona Zervas - OH MY LORD | `Arizona Zervas & 24kGoldn` — flattened | `OH MY LORD`                               |

both shapes occur, so itunes alone cannot be trusted to separate the roles. it
is still useful as _corroboration_ when the feature appears in `trackName`.

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

**OQ-4 — tag shape. decided: option A, the feature lives in the title.**

| option                     | `artist`              | `title`                     | `album artist` |
| -------------------------- | --------------------- | --------------------------- | -------------- |
| **A — feature in title** ← | `Dua Lipa`            | `Levitating (feat. DaBaby)` | `Dua Lipa`     |
| B — feature in artist      | `Dua Lipa ft. DaBaby` | `Levitating`                | `Dua Lipa`     |

A keeps artist columns clean and sorts correctly in rekordbox; B surfaces the
feature in the deck display. the sorting argument won. the full shape is
specified in §7a — `{Name} (ft. {Features}) [{Mix}]`.

## 7. field precedence

**a hand-edited value in `library.toml` (§9b) outranks every row in this table.**
where the operator has asserted a value, no source is consulted for that field.

| field             | 1st                                                                                                                             | 2nd                                       | 3rd                                              |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------ |
| title             | **itunes `trackName`** (parsed, §7a)                                                                                            | spotify                                   | filename parse                                   |
| artist            | **musicbrainz artist-credit** — performers-only filter **in indian scope only** (§6, §7a, F38)                                  | filename parse                            | itunes `artistName`                              |
| album             | **itunes `collectionName`**                                                                                                     | spotify                                   | —                                                |
| album artist      | **main artists only** (§6, §7a)                                                                                                 | itunes `artistName`                       | artist                                           |
| track number      | **spotify chosen release `track_number`** (F32)                                                                                 | itunes (unvetted release)                 | —                                                |
| disc number       | **spotify chosen release `disc_number`** (F32)                                                                                  | itunes (unvetted release)                 | —                                                |
| release date      | **spotify MIN across all releases** (F33)                                                                                       | itunes                                    | musicbrainz `first-release-date`                 |
| year              | derived from release date                                                                                                       | —                                         | —                                                |
| **genre**         | **beatport `sub_genre` if present, else `genre`** — wherever a beatport listing exists, regardless of style (operator decision) | **discogs `styles[0]`** (F47)             | itunes `primaryGenreName`, then existing tag     |
| artwork           | **verified chain §7c** → 3000²                                                                                                  | spotify album image (~640px)              | existing embedded art (flagged)                  |
| label             | **beatport `release.label`** (operator preference)                                                                              | discogs `/releases/{id}` `labels[]` (F46) | itunes/spotify `copyright` — parsed, last resort |
| bpm               | **beatport `bpm`** (F14, 100% coverage)                                                                                         | —                                         | —                                                |
| key               | **beatport `key`** (F14, 100% coverage)                                                                                         | —                                         | —                                                |
| mix name (`TIT3`) | beatport `mix_name` (F24)                                                                                                       | parsed from itunes title                  | filename bracket                                 |
| remixer (`TPE4`)  | beatport `remixers` (F24)                                                                                                       | parsed from mix name                      | —                                                |
| ISRC              | the file's own tag                                                                                                              | musicfetch `isrc`                         | —                                                |
| composer (`TCOM`) | musicbrainz work → composer (F28)                                                                                               | —                                         | —                                                |
| lyricist (`TEXT`) | musicbrainz work → lyricist (F28)                                                                                               | —                                         | —                                                |

## 7a. naming and tag shape

**title format.** one canonical shape, in this order:

```json
{Name} (ft. {Featured artists}) [{Mix name}]
```

- the **parenthetical** carries featured artists only, comma-separated
- the **bracket** carries the mix name only
- either part is omitted when it does not apply; the bare name is the common case

```text
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

| observed                                       | normalised                                           |
| ---------------------------------------------- | ---------------------------------------------------- |
| `Extended Mix`, `Extended Version`, `Extended` | **`Extended`** (the primary release in dance — F23a) |
| `Radio Edit`, `Radio Mix`, `Radio Version`     | **`Radio Edit`**                                     |
| `Original Mix`, `Original Version`             | **`Original`**                                       |
| `{X} Remix`, `{X} Edit`, `{X} Flip`, `{X} VIP` | unchanged, `{X}` → `TPE4`                            |
| `Continuous Mix`, `Instrumental`, `Club Mix`   | unchanged                                            |

`Original` is written to `TIT3` only when the source states it; it is never
invented for a track that simply has no mix name.

**performer vs composer — indian repertoire only (F28, F38).** this rule is
**scoped, not global.** it applies when either signal fires:

```text
ISRC country prefix == IN   OR   genre matches
  bollywood | indian | punjabi | telugu | tamil
```

**167 tracks, 11% of the library.** within that scope `artist` carries
**performing artists only** — the operator listens by vocalist, and indian
listings inconsistently promote music directors into `artists[]`.

**everywhere else the full credited artist list is kept.** in western repertoire
a producer credited as an artist genuinely _is_ a main artist — `Metro Boomin`,
`Calvin Harris`, `Internet Money` are not pollution to be stripped, and applying
the indian rule globally would corrupt them. this is the operator's call and it
is the correct one.

in scope, composers and lyricists go to their own frames, never to `artist`:

| role         | frame             | source                        |
| ------------ | ----------------- | ----------------------------- |
| performers   | `TPE1` (`artist`) | musicbrainz `artist-credit`   |
| composer     | `TCOM`            | musicbrainz work → `composer` |
| lyricist     | `TEXT`            | musicbrainz work → `lyricist` |
| album artist | `TPE2`            | the chosen release (§7b)      |

**`album artist` is allowed to differ sharply from `artist`** — operator
decision. on a film soundtrack it may be `Various Artists`, a composer, or a
music director, and that is correct: it describes the _release_, not the
recording. only `artist` is held to the performers-only rule.

**separator style (OQ-7, decided).** comma between every artist, `&` before the
last:

```text
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
remixer, and it is deliberate: the mixer _is_ the person who modified the
recording, which is exactly what `TPE4` means.

**artist vs album artist.** features live in the _title_, so:

- `artist` — **main artists only**, plus the remixer when there is one
  (matching F25's existing `Calvin Harris, Clementine Douglas & Odd Mob`)
- `album artist` — **main artists only**, never the remixer, never a feature
- featured artists appear **only** in the title parenthetical

this is why §6's main/featured split is load-bearing: get it wrong and a feature
is promoted into `album artist`, which fragments the album in rekordbox.

**OQ-7 — separator style. decided** (and specified in full earlier in this
section). the library currently mixes `&` and `,` in artist strings
(`Calvin Harris & Clementine Douglas` vs `Calvin Harris, Clementine Douglas &
Odd Mob`). serato and rekordbox both treat the field as one opaque string, so
this is cosmetic — but it should be _consistently_ cosmetic: comma between every
artist, `&` before the last.

## 7b. release selection

**every album-level field depends on choosing the right release first.** a
recording appears on many (F26): the original album, a single, and any number of
compilations. album, album artist, track number, disc number and even the title
string all change with that choice.

```text
candidates = spotify /v1/search?q=isrc:{ISRC}&type=track
rank by (album_type: album=0, single=1, compilation=2),
        then total_tracks == 1 LAST,      # promo singles
        then release_date ASC             # earliest real release
pick the first
```

**three clauses, each earning its place.**

1. **type first.** an album beats a single beats a compilation. this is what
   picks `No Strings Attached` (1/12) over the `Bye Bye Bye` single (1/1).
2. **1-track releases sort last.** a 1-track release is a promo, not a home. this
   is what picks the 4-track soundtrack `Stree` over the 1-track
   `Kamariya (From "Stree")` — and it is why `(From "…")` never reaches a tag.
3. **then earliest.** among real releases of the same type, the first one is the
   canonical one.

**why not "most tracks"?** an earlier revision ranked by `total_tracks`
descending, which fixed `Kamariya` and **broke deluxe editions**:

```text
NAV - Never Sleep (USUM72214489)
  single  2022-07-29  1/1   Never Sleep                                ← promo
  album   2022-09-09  4/19  Demons Protected By Angels                 ← correct
  album   2022-09-14  4/20  Demons Protected By Angels (Bonus Version) ← "most tracks" picked this
```

a bonus or deluxe edition always has more tracks than the standard album, so
"most tracks" systematically prefers the variant. "1-track last, then earliest"
gets both cases right.

**the default now prefers the expanded edition. this was reversed on
2026-09-15, and the reversal is a measurement, not a taste.**

the old default was `prefer_standard_edition = true`, justified on one claim:
the album _name_ is cleaner, and the track number is "identical here
(`4/19` vs `4/20`), so nothing is lost". **the claim does not generalise.** of
15 library tracks appearing on both a standard and an expanded edition, **10
shift position**:

```text
A Boogie Wit da Hoodie — Artist 2.0
  Cinderella Story    # 2/20  ->  #28/29
  Calm Down           # 9/20  ->  #21/29
  King Of My City     #17/20  ->  #13/29
  Another Day Gone    #10/20  ->  #20/29
```

`El Dorado` and `i am > i was` do preserve ordering, so both behaviours are
real. but with numbering unstable either way, a tidier `TALB` string buys
nothing — and the real cost of the old rule is that it **split one album across
two names**:

```text
before                          after
  El Dorado          4 tracks     El Dorado (Deluxe)   6 tracks
  El Dorado (Deluxe) 2 tracks
  Artist 2.0         10 tracks    Artist 2.0 (Deluxe)  15 tracks
  Artist 2.0 (Deluxe) 5 tracks
```

a track the operator owns that exists **only** on the expanded edition —
`Prada`, `Mistakes`, `Bleed` — has nowhere else to go, so the standard-edition
preference could never apply consistently. the expanded edition is a superset of
the standard one, so preferring it puts every track of an album under one name
with one internally consistent numbering, which is what actually sorts in
rekordbox.

set `prefer_expanded_edition = false` to restore the old behaviour, accepting
the split for any album whose bonus tracks the operator owns.

**a refinement left unbuilt:** the strictly better rule is "pick the edition
covering the most of _this library_", decided per album family rather than per
track. on the measured data it agrees with prefer-expanded everywhere
(`Artist 2.0` 15 vs 10, `El Dorado` 6 vs 4, `i am > i was` 1 vs 1), so it buys
nothing today and costs a second pass over the library. worth revisiting only if
a standard edition is ever found covering more.

**the promo-single clause is load-bearing.** ranking by release date alone picks
the wrong release for `Kamariya`:

```text
[single] 2018-08-09  1/1  Kamariya (From "Stree")  | Kamariya (From "Stree")   ← earliest, WRONG
[single] 2018-08-22  2/4  Stree                    | Kamariya                  ← correct
```

a **1-track single is a promotional release**; the parent album or soundtrack is
the recording's real home, and it is frequently published _later_. demoting
1-track releases finds the parent; ranking on date alone finds the promo.

**this is also the answer to "single first, album later".** the single is
released ahead of the album by design — weeks or months. year and release date
come from the **earliest** release across all of them (F33), so the single's date
is still what lands in `TDRC`; only `album`, `track` and `disc` come from the
album. `Never Sleep` is tagged **2022-07-29** (the single) on
**`Demons Protected By Angels` 4/19** (the album). both facts are true and both
are kept.

verified against every case probed for this spec:

| ISRC           | chosen release                                   | title                                  |
| -------------- | ------------------------------------------------ | -------------------------------------- |
| `USUM72214489` | `Demons Protected By Angels` (album, 4/19)       | standard, not the bonus edition        |
| `INS181801821` | `Stree` (single, 2/4)                            | `Kamariya` — clean                     |
| `INS181700238` | `Badrinath Ki Dulhania` (single, 2/5)            | `Roke Na Ruke Naina` — clean           |
| `USJI10000001` | `No Strings Attached` (album, 1/12)              | `Bye Bye Bye`                          |
| `USUG12509635` | `ODYSSEY` (album, 7/19)                          | `Don't Want Your Love`                 |
| `GBARL1201392` | `18 Months` (album, 10/15)                       | `Sweet Nothing (feat. Florence Welch)` |
| `SGB502383473` | `Desperado` (single, 1/1)                        | `Desperado` — only release             |
| `GBARL2501127` | `Blessings — The Remixes (Part 2)` (single, 4/6) | `Blessings - Odd Mob Remix`            |

the last row still carries a `" - {X} Remix"` suffix, which is **correct** — it
is a genuine remix release, and §7a moves that suffix into `TIT3` rather than
stripping it.

**compilations are chosen only when nothing else exists.** they carry inflated
track counts (`trk 36/50`), meaningless track numbers, and the `(From "…")` and
`- {X} Remix` title suffixes that §7a would otherwise have to strip.

**tier 2 gains spotify.** itunes supplies `trackNumber`/`discNumber` (F4) but
exposes only the one release its id points at; spotify's ISRC search is what
makes the _set_ of releases visible. once a release is chosen, its track and disc
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

the danger is not resolution, it is **identity**: an image returned for a track
is the cover of whichever release the matcher landed on, and that is a
compilation often enough to matter (F34). so every candidate is verified against
the release chosen in §7b before its bytes are used.

**the chain, in order. the first candidate that verifies wins.** this is the
**post-F37 chain: musicfetch is not in it.** an earlier revision opened with
musicfetch's `appleMusic.id`; F37 measured that two itunes search entities
reproduce its results byte for byte on 4/4 probes, and musicfetch was removed
from tier 1 entirely. **the library path needs no musicfetch token** (F36).

```text
1. §7b has already chosen the release  →  album name + album artist

2. candidate A — itunes album search
     itunes /search?term={album artist} {album}&entity=album
     ACCEPT the first result whose collectionName matches the chosen album
     (exact on normalised text, or the chosen name contained in it)

3. candidate B — itunes song search        ← replaces musicfetch (F37)
     itunes /search?term={album artist} {track name}&entity=song
     ACCEPT the first result whose collectionName matches the same way
     this is the path that finds `18 Months`, where entity=album
     returns only `96 Months` — a different record

4. candidate C — spotify's album image from the chosen release
     correct by construction, but capped around 640px

5. no candidate  →  keep the existing embedded artwork, and flag the track
```

**upgrade to 3000×3000** by rewriting the trailing `/{N}x{N}bb.jpg` on the
accepted `artworkUrl100` (F5). on non-200 or a short read, step down 3000 → 1400
→ 600 rather than failing the track.

**measured on four tracks, 4/4 produced 3000×3000:**

| ISRC           | album               | accepted via        | size    |
| -------------- | ------------------- | ------------------- | ------- |
| `USJI10000001` | No Strings Attached | A — album search    | 2256 KB |
| `INS181801821` | Stree               | A — album search    | 1755 KB |
| `GBARL1201392` | 18 Months           | **B — song search** | 2162 KB |
| `USUG12509635` | ODYSSEY             | A — album search    | 2919 KB |

**candidate B is not a fallback for rare cases**, and the `18 Months` row is why
it exists: album search returns `96 Months` there and nothing else. the retired
musicfetch candidate was right about half the time and **wrong silently**, which
is why every candidate is verified against the chosen release rather than
trusted.

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

| field               | frame  | source                                                      | coverage                 |
| ------------------- | ------ | ----------------------------------------------------------- | ------------------------ |
| title               | `TIT2` | spotify chosen release, re-rendered per §7a                 | 100%                     |
| artist              | `TPE1` | musicbrainz artist-credit (performers-only in indian scope) | 100%                     |
| album               | `TALB` | spotify chosen release (§7b)                                | ~100%                    |
| album artist        | `TPE2` | chosen release, main artists only                           | ~100%                    |
| year                | `TDRC` | **earliest** release across all releases (F33)              | ~100%                    |
| release date        | `TDRL` | same, full date                                             | ~100%                    |
| track number        | `TRCK` | chosen release `track_number` (F32)                         | ~100%                    |
| disc number         | `TPOS` | chosen release `disc_number` (F32)                          | ~100%                    |
| genre               | `TCON` | beatport where listed, else itunes                          | 100%                     |
| label               | `TPUB` | beatport → discogs `labels[]` → copyright parse (F46)       | ~72% today               |
| ISRC                | `TSRC` | the file's own tag, once G10 trusts it                      | 96.3%                    |
| **mix name**        | `TIT3` | beatport `mix_name`, else parsed from title                 | remixes + edits          |
| **remixer**         | `TPE4` | parsed from mix name, beatport confirms                     | third-party remixes only |
| **original artist** | `TOPE` | the chosen release's artist, when a remixer exists          | remixes only             |
| **composer**        | `TCOM` | musicbrainz work → composer                                 | indian scope             |
| **lyricist**        | `TEXT` | musicbrainz work → lyricist                                 | indian scope             |
| **BPM**             | `TBPM` | beatport only (§7e)                                         | **partial**              |
| **key**             | `TKEY` | beatport only, **written in camelot** (§7f)                 | **partial**              |
| artwork             | `APIC` | verified chain §7c at 3000²                                 | ~100%                    |

**`TOPE` (original artist) is new and only meaningful on remixes.** on
`Blessings [Odd Mob Remix]` it holds `Calvin Harris, Clementine Douglas` while
`TPE1` holds those plus `Odd Mob` and `TPE4` holds `Odd Mob`. on a non-remix it
is **not written at all** — an empty `TOPE` is noise, and rekordbox shows the
column regardless.

**composer and lyricist are written wherever musicbrainz supplies them**, not
only in indian scope. the _indian scope_ rule (§7a, F38) governs who is excluded
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
sorting in serato and in this project's own ui. **decided: write BPM and key
only where a source supplies them, leave them empty
otherwise.** local analysis is **not implemented** — rekordbox recomputes both
during its own analysis and prefers its own values over tags, so computing them
here buys almost nothing for ~120 MB of dependencies. an empty field is honest;
a guessed one gets trusted.

where a source _does_ supply them they are kept — beatport today, and any future
source that carries them. key is normalised to camelot on the way in (§7f).

## 7f. key notation — camelot

**`TKEY` is written in camelot, not musical notation** (operator decision).
beatport reports `"Eb Minor"`, `"Db Major"`, `"F# Minor"`; rekordbox and serato
both display camelot, and harmonic mixing is done in it. storing `2A` rather
than `Eb Minor` means the tag is usable without mental conversion mid-set.

the wheel is circle-of-fifths ordered — `B` is major, `A` is its relative minor,
so `nA` and `nB` share the same seven notes and mix cleanly.

| #   | A (minor) | B (major) |
| --- | --------- | --------- |
| 1   | A♭ / G♯   | B         |
| 2   | E♭ / D♯   | F♯ / G♭   |
| 3   | B♭ / A♯   | D♭ / C♯   |
| 4   | F         | A♭ / G♯   |
| 5   | C         | E♭ / D♯   |
| 6   | G         | B♭ / A♯   |
| 7   | D         | F         |
| 8   | A         | C         |
| 9   | E         | G         |
| 10  | B         | D         |
| 11  | F♯ / G♭   | A         |
| 12  | D♭ / C♯   | E         |

anchors verified against published charts: **1A = A♭ minor, 1B = B major,
8A = A minor, 8B = C major**
([dj.studio](https://dj.studio/blog/camelot-wheel), checked 2026-09-14), and the
table is internally consistent by circle of fifths.

**`tools/camelot.py` is the tested reference implementation** — all 24 codes
unique and covered, every key beatport returned during this research verified,
plus enharmonic spellings (`D#`→`Eb`, `C#`→`Db`, `Gb`→`F#`) and case variants.

**an unparseable key returns `None` and `TKEY` is left empty.** a wrong key is
worse than a missing one: it survives into a set and gets trusted. this mirrors
the §7e position on BPM.

## 8. gates — a stage is not done until these pass

- **G1 identity.** ≥95% of the 1,439 ISRC tracks resolve to at least one spotify
  release via `/v1/search?q=isrc:`. measured baseline: 20/20. **this gate was
  written against musicfetch and re-pointed at spotify by F36/F37**, which
  removed musicfetch from the library path; the threshold is unchanged because
  the ISRC, not the service, is what identity rests on.
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
  main/featured split for **≥88%** of the 398 featured tracks. disagreements are
  queued for review, never auto-resolved.
  **the threshold is derived from measurement, not aspiration** (F53): the
  policy achieves **90.5%**, and 88% sits below that with enough room that the
  gate catches a regression instead of failing on the day it was written. the
  original ≥95% came from a 30-track sample and the full population does not
  support it.
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

```text
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

```text
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

```text
file value == last generated  →  resolver may refresh it
file value != last generated  →  the operator edited it
                                 preserve verbatim, mark provenance `manual`
```

no marker to remember, no ceremony. editing a line is the act of asserting it.
deleting a line's value reverts that field to resolver control on the next run.

**title/artist/album are written for legibility, not read as input.** they make
an md5-keyed file scannable; the authoritative values live in the cache (§9a).
the fields the resolver _reads back_ are `isrc`, the service URLs, and any direct
field override.

**it is the only hand-editable artefact in the system, and it is safe to delete.**
regenerating costs nothing for resolved rows — they come from cached raw payloads
(§9a) — but manual edits are lost, so the file is worth version-controlling. it is
plain text and diffs cleanly.

## 9c. views over the map

`library.toml` is complete but long. `map` renders it for scanning:

```sh
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

```text
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
library once it carries an ISRC _and_ that ISRC's resolved duration is within
±5s of the downloaded audio. a `/url` result that disagrees on duration is a
wrong match, and youtube is full of edits, sped-up versions and live cuts that
resolve confidently to the studio recording. measured baseline: 8/8 resolved.

**OQ-6 (decided) — lossy source, lossless container.** the source is **AAC at ~257 kbps**
(measured across `.staging`, and reachable only with valid premium cookies —
F20); the library is AIFF. the conversion costs **5.4×**
storage — 9.5 GB → 51.9 GB measured — and **adds no quality**, since nothing is
recoverable that the AAC encoder discarded. the existing 1,494 files are already
converted and are not in scope to revisit.
~~the open question is **new** acquisitions.~~ **decided: convert to AIFF**
(`pcm_s16be`, 44.1 kHz), for **metadata compatibility** — AIFF carries ID3 and
both DJ apps read the full frame set (F50). the 5.4× cost is accepted
deliberately: it buys tag support, not audio quality, and the conversion is a
faithful decode of the AAC rather than a container swap.

## 10a. premium cookies — sourcing and placement

the operator holds youtube premium, and **premium audio is the difference between
itag 141 (AAC 256k) and itag 251 (opus 151k)** — the entire quality basis of the
library (F20).

**cookies are read fresh from chrome on every single run — there is no export
step and no snapshot to go stale.** `--cookies-from-browser` opens chrome's
cookie database at the moment of use, so whatever is current is what gets used.
manual extraction to a file would be strictly worse: a file is a point-in-time
copy that youtube's rotation invalidates without telling anyone, which is exactly
the failure that produced F20.

**the assurance is the live probe, not the extraction method.** G8 runs
`yt_cookies.py check` against the real API before every batch, so validity is
established by _observing a premium itag being offered_, not by assuming a file
is good. a file-based flow would still need that same probe — it just adds a
staleness mode.

the one case for exporting to a file is running on a machine without chrome; then
`yt_cookies.py export` writes one, and it verifies premium before overwriting a
working file.

**where cookies come from.** yt-dlp reads chrome's cookie store directly:

```text
--cookies-from-browser chrome:{profile}
```

two profiles, two properties:

| profile                    | works                                  | durability                                                                                          |
| -------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `chrome:Default`           | yes, verified today — itag 141 at 258k | **rotates.** youtube re-issues cookies as the operator browses, and a rotated set is rejected (F20) |
| `chrome:ytdlp` (dedicated) | same                                   | **does not rotate** — logged in once, never browsed again                                           |

the wiki's incognito procedure exists because incognito cookies are memory-only
and need a browser extension to export. **a dedicated profile has the same
never-rotated property with a real cookie database**, so it needs no export and
no extension. `tools/yt_cookies.py setup` walks through creating it.

**default is `chrome:Default` with a fallback to the dedicated profile**, because
Default works today and needs no setup. when `check` starts failing, the
dedicated profile is the fix, not a re-export.

**where it sits in the pipeline.** cookies are used at exactly two points, and
checked before either:

```text
1. BATCH PRECONDITION  (gate G8)
     tools/yt_cookies.py check
     asserts itag 141 or 774 is offered
     FAIL → DOWNLOAD NOTHING. abort before the first request.
     ↓
2. PER-TRACK DOWNLOAD
     yt-dlp --cookies-from-browser chrome:{profile} -f 141/774
     exact itag, never `bestaudio` (F48)
     FAIL → re-probe (below), do not simply skip
```

**a format failure is treated as systemic until proven otherwise.** cookie
validity is transient (F20), so a batch that starts valid can rotate at
track 200. on the **first** `-f 141/774` failure the pipeline re-runs the
cookie probe:

```text
probe now FAILS  →  cookies died mid-batch.
                    ABORT THE ENTIRE BATCH IMMEDIATELY.
                    every remaining track stays queued, untouched.
probe still PASSES → this one track genuinely has no premium format.
                    skip it, queue it for review, continue.
```

**the default on ambiguity is to stop.** continuing after the cookies die means
hundreds of failed requests against youtube with a stale session — wasted time at
best, and a pattern worth avoiding on an account the operator cares about (F20's
ban-risk note).

**aborting is cheap, which is why it is the default.** identity resolution needs
no cookies — musicfetch `/url` (F19) and the metadata probe run unauthenticated —
so a cookie failure blocks _downloading_, never _identifying_.

```text
resolve 50 identities     → cached (§9a), survives the abort
cookies stale             → batch aborts, 0 files written
operator refreshes them   → tools/yt_cookies.py setup / check
re-run                    → 0 API calls re-spent, downloads resume
```

**the queue is state, not a runtime list.** pending acquisitions live in the
sidecar, so an abort loses nothing and a resume re-downloads nothing. this is what
makes "stop immediately" the cheap option rather than the expensive one — there is
no progress to protect by pressing on.

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

| class                              | test                                           | policy                                                                                                                            |
| ---------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **A — true duplicate**             | same ISRC **and** same audio md5               | **auto-resolve.** keep one, delete the other. byte-identical audio cannot lose information.                                       |
| **B — same ISRC, different audio** | same ISRC, differing md5, duration delta > 5s  | **never auto-delete.** these are different recordings; one ISRC is wrong. re-resolve both by duration (F40) and queue for review. |
| **C — ISRC on an unrelated song**  | duration delta > 5s vs the ISRC's own duration | **strip the ISRC**, route the file through tier-0 identity (§10), queue for review.                                               |

**deletion is always to a quarantine directory, never `rm`.** the operator
reviews and empties it. combined with the §9 rule that the source tree is never
mutated, class A resolution on the _source_ library is a report; only the output
tree is de-duplicated.

**preventing future duplicates.** the sidecar holds a unique index on ISRC and on
audio md5. `acquire` checks both **before download**:

```text
ISRC already in library        → skip, report "already have this recording"
audio md5 matches after fetch  → discard the download, keep the existing file
```

the ISRC check is the cheap one and runs first — tier 0 resolves identity before
committing to a download anyway (§10), so a duplicate costs one API call rather
than a file.

**note the `(2)` filenames are a symptom, not the test.** all three class-A
duplicates happen to carry it, but the test is the audio hash — a re-download
under a different name would not.

## 11b. excluding music videos

the operator wants the **release**, never the video (F41).

```text
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

```text
src/music_metadata/
  cli.py            # entry point
  acquire.py        # tier 0 — yt-dlp + /url identity (§10)
  probe.py          # ffprobe → local tag facts
  sources/
    musicfetch.py   # tier 0 only — youtube url -> isrc (F36)
    itunes.py       # artwork + genre fallback (F32/F37)
    musicbrainz.py  # tier 2 — artist-credit roles (§6)
    spotify.py      # tier 1 — release selection, track/disc (§7b)
    discogs.py      # tier 2 — label + styles, 2 calls (F46/F47)
    beatport.py     # tier 3 — genre/bpm/key
    bp_auth.py      # pluggable TokenProvider: cookie | oauth (F15)
    ratelimit.py    # token bucket, 20/min (F8)
  credit.py         # §6 main vs featured split
  arbitrate.py      # §7 precedence
  artwork.py        # verified chain, 3000² (§7c)
  camelot.py        # key -> camelot, tested table (§7f)
  tag.py            # ID3-on-AIFF writer, preserves foreign frames
  library_map.py    # library.toml: generate, merge, read back (§9b)
  store.py          # sidecar cache (sqlite, shared with the web ui)
                    # persists mb recording id + fingerprint for §15
  web/
    app.py          # fastapi — library, review, acquire, diff (§14)
    jobs.py         # background resolve/acquire with progress
    templates/      # jinja2 + htmx fragments
    static/         # hand-written css, alpine.js
tests/{unit,integration}/
```

root-level docs, and what each is for:

| file            | holds                                                               |
| --------------- | ------------------------------------------------------------------- |
| `SPEC.md`       | what we are building, and why each decision went the way it did     |
| `CLAUDE.md`     | how we work — style, tooling, commits, working agreements           |
| `tasks/plan.md` | the build order, its dependency graph and its checkpoints           |
| `tasks/todo.md` | the task list, with acceptance criteria per task                    |
| `README.md`     | **what exists and runs today** — the current state, nothing planned |

**`README.md` covers:** what the project does in a paragraph, prerequisites
(`uv`, `ffmpeg`, the `.env` keys actually needed), install, **the commands that
work today** with real example output, where the output tree and `library.toml`
land, how to start the web ui, and the gate numbers from the most recent run.

it is a status report, not a brochure: it names which milestone has landed and
what is not built yet. the cadence — updated in the same pr as the work it
describes — is a working agreement and lives in `CLAUDE.md`.

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

```sh
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
  ISRC** — the operator's point is decisive: the beatport record is a _different
  recording_, so taking its ISRC would label the file as a track it is not. this
  is why F23's field-class split exists.
- ~~**bollywood `(From "…")` suffix.**~~ **resolved by §7b** — the suffix marks a
  compilation release. choosing the correct release removes it; no string
  stripping needed.
- ~~**OQ-7 artist separator style.**~~ **decided:** comma between every artist,
  `&` before the last (§7a).
- ~~**OQ-10 discogs.**~~ **adopted.** _(measured 2026-09-14: the authenticated
  rate limit is **60 req/min**, reported in the `x-discogs-ratelimit` header.
  the two-call shape is confirmed necessary — the search endpoint's flat
  `label` array merges pressing plants, publishers and studios with the real
  labels, and only `/releases/{id}` separates `labels` from `companies`.)_
  `DISCOGS_TOKEN` is in `.env`. discogs is
  **tier 2**, supplying `label` (F46) and a `styles` genre fallback that beats
  itunes (F47). still **not** a BPM or key source — it has neither (§7e). costs
  two calls per track (search → release), so it runs only when beatport has no
  listing.
- ~~**OQ-11 local BPM/key analysis.**~~ **deferred, deliberately.** rekordbox
  recomputes both anyway. values are kept where a source supplies them (beatport
  today) and left empty otherwise; key is stored in **camelot** (§7f).
- **OQ-5 official beatport credentials.** the operator will supply client id and
  secret via `.env` when obtained. `OAuthClientProvider` reads them;
  `CookieSessionProvider` runs until then (F15). not a blocker.
- **OQ-12 the `.env` key is named `MUSICMATCH_TOKEN`, but this spec says
  musicfetch throughout.** either the key is misnamed or it authenticates a
  different service. **not a v1 blocker** — F36/F37 removed musicfetch from the
  library path entirely, so nothing in v1 reads it. resolve it before tier 0
  (§10), which is the one place `/url` is genuinely irreplaceable (F19).
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

**stack: fastapi + jinja2 + htmx. no node, no build step, no javascript
framework.**

the honest reason is what this ui actually does: **tables, filters, a paste-a-URL
form, accept/reject buttons, and progress polling.** every one of those is a
single htmx attribute against an endpoint that returns an HTML fragment:

```html
<!-- the review queue, filtered server-side -->
<input
  name="q"
  hx-get="/review"
  hx-target="#rows"
  hx-trigger="keyup changed delay:300ms"
/>

<!-- accept a proposed value; writes library.toml (§9b) -->
<button
  hx-post="/review/{md5}/accept"
  hx-target="closest tr"
  hx-swap="outerHTML"
>
  accept
</button>

<!-- a 72-minute resolve, without holding an http request open -->
<div hx-get="/jobs/{id}" hx-trigger="every 2s" hx-swap="innerHTML"></div>
```

**what react or svelte would add here: a node toolchain, a build step, a second
language, a second linter, and a client-side copy of state that the server
already holds.** what it would buy: nothing this ui needs. the data lives in
sqlite next to the server; there is no offline mode, no optimistic updating, no
shared multi-user state to reconcile.

**`alpine.js` from a CDN for local-only interactivity** — a disclosure toggle, a
modal — where htmx would need a server round-trip for something that never leaves
the page. it is ~15 KB and needs no build.

templates are jinja2 under `web/templates/`, linted with **djlint** (a plain HTML
formatter mangles `{% %}`); css is hand-written and formatted with prettier
(`CLAUDE.md`).

**shared state, not a wrapper.** the sidecar sqlite (§9a) and `library.toml`
(§9b) are the state; the CLI and the ui are two front doors to the same data, and
neither is authoritative. long operations (`resolve`, `acquire`) run as background
jobs with progress polled from the `jobs` table — a 72-minute resolve (F8) cannot
block an HTTP request.

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

**the tension worth naming now.** the tracks most _worth_ contributing are the
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
delete without touching a single audio file. so the files stay clean _and_ a
future acoustid pass stays cheap; these were never in tension.

without those columns a submission pass would have to re-resolve the whole
library against musicbrainz at 1 req/s (F28) — roughly 48 minutes — purely to
recover ids it already had.

**precondition, not a detail:** submitting wrong mappings actively damages a
shared database. a submission pass must run only over tracks that passed every
gate in §8, never over flagged or fallback-resolved ones.
