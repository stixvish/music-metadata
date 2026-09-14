# music-metadata

1,494 AIFF files in `~/Music/library` carry tags of unknown provenance. this
resolves them from the one field that is trustworthy — the ISRC, present on
96.3% of them — through free APIs, and writes a **tagged copy**. the source
tree is never modified.

the operator is a DJ, which biases two fields above the rest: **genre**
(beatport's sub-genre, not "Dance") and **artwork** (large, square, from a
verified master).

- `SPEC.md` — what we are building, and why each decision went the way it did
- `CLAUDE.md` — how we work: style, tooling, commits
- `tasks/plan.md` — the build order · `tasks/todo.md` — the task list

## status

**milestone 0 of 6 — foundation.** the project scaffold, the sidecar cache and
the web ui shell exist and are tested. **no metadata is resolved yet**: no
source adapter is written, so there is nothing to probe, resolve, diff or apply.

what works today:

| thing              | state                                                       |
| ------------------ | ----------------------------------------------------------- |
| check gate         | eight checks, all passing                                   |
| `output.py`        | the single message sink the CLI and ui share                |
| `store.py`         | sqlite sidecar — all six tables of `SPEC.md` §9a            |
| web ui             | serves; library screen renders rows; job progress polls     |
| **resolving tags** | **not built** — M1 lands spotify, naming and the tag writer |

what is deliberately **not** built yet: `probe`, `resolve`, `diff`, `apply`,
`verify`, `map`, `acquire`. they are listed in `tasks/todo.md`, not here — this
file records what runs, not what is planned.

## prerequisites

```sh
brew install uv ffmpeg taplo
npm install -g prettier markdownlint-cli2
```

`ffprobe` and `ffmpeg` come with the `ffmpeg` formula. `fpcalc` (chromaprint) is
only needed for §15 fingerprinting and is not used yet.

## install

```sh
uv sync
```

## running the web ui

the ui is the primary interface (`SPEC.md` §14). it binds loopback only.

```sh
uv run python -c "
from pathlib import Path
from music_metadata.web.app import serve
serve(Path.home() / '.local/share/musicpipeline/sidecar.sqlite')
"
```

then open <http://127.0.0.1:8765>. the library screen will say "no tracks yet"
until `probe` exists (M1).

there is no `music-metadata` console command yet — `cli.py` lands in M1 task
1.9, and this file will document it when it does.

## secrets

`.env` holds API credentials and is git-ignored. `.env.example` lists the keys.
spotify and discogs credentials are present; **musicfetch is not needed for the
library path at all** (`SPEC.md` F36/F37) — only for tier 0 acquisition in M6.

no cookie files or tokens are ever committed. runtime config lives in
`~/.config/musicpipeline/`.

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
uv run pytest -q          # 36 tests, no network
uv run pytest -q -m live  # hits real apis; excluded from the default run
```
