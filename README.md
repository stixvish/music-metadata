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

**milestone 1 of 6 — the resolve spine.** one track goes end to end: probed from
disk, resolved against spotify by ISRC, arbitrated through §7's precedence
table, and written as a tagged copy. verified on the real library.

| thing               | state                                                        |
| ------------------- | ------------------------------------------------------------ |
| `probe`             | 1,494 files, 1,439 with ISRC — reproduces the baseline       |
| `resolve`           | spotify ISRC search, paginated, cached in sqlite             |
| `diff` / `apply`    | tagged copies to an output tree; source untouched            |
| `map`               | `library.toml` with the §9c view flags                       |
| web ui              | library screen, resolve as a background job with progress    |
| **artwork**         | **not built** — the §7c chain lands in M3                    |
| **genre, BPM, key** | **not built** — beatport is M4                               |
| **artist credit**   | **not built** — musicbrainz is M2; artists come from spotify |
| **acquisition**     | **not built** — tier 0 is M6                                 |

what M1 actually populates: title, artist, album, album artist, release date,
year, track number, disc number, mix name, remixer, original artist and ISRC.
everything else is deliberately left empty rather than guessed — §7e's position
on BPM, applied generally.

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

# 2. resolve identities into the sidecar. rate-limited to 20 req/min.
uv run music-metadata resolve --limit 20

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

## the web ui

the ui is the primary interface (`SPEC.md` §14). it binds loopback only.

```sh
uv run music-metadata serve
```

then open <http://127.0.0.1:8765>. the library screen lists every probed track
and can start a resolve as a background job, with progress polled — a full
resolve is over an hour and cannot be held open in an HTTP request.

the review, acquire and diff screens are stubs until the data that justifies
them exists.

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
uv run pytest -q           # 243 tests, no network
uv run pytest -q -m live   # hits the real spotify api
uv run pytest -q -m slow   # probes all 1,494 files against the measured baseline
```

the pure modules — `release`, `naming`, `output` — are held at 100% coverage
with a 90% floor. they carry the decisions the spec argued hardest about.
