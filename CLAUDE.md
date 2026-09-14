# CLAUDE.md

working conventions for this repo. **this file is about *how we work*.
`SPEC.md` is about *what we are building*.** keep them separate — decisions
about the product go in the spec, decisions about process go here.

## verify before you claim

**the model's knowledge base is stale. the web is not.** this project depends
on third-party surfaces that change without notice — musicfetch's response
schema and pricing, beatport's page markup and genre taxonomy, the itunes
search api's artwork sizing, what services musicfetch actually covers.

the rules:

- **every factual claim about an external service gets a lookup first.**
  endpoints, field names, rate limits, pricing tiers, auth headers, supported
  services, html structure. do not answer these from memory — fetch the doc
  page and cite it.
- **cite the url and the date you checked.** in `SPEC.md`, a claim about an
  external api reads `(musicfetch.io/docs/isrc, checked 2026-09-14)`. an
  uncited external claim is a bug.
- **prefer primary sources.** the vendor's own docs over a blog post, a blog
  post over recollection. when the docs are silent — musicfetch does not
  publish rate limits — say "not documented", never guess a number.
- **re-check before you rely on it again.** a citation more than a few weeks
  old is a hypothesis, not a fact. re-fetch when a call starts failing.
- **local facts get measured, not recalled.** file counts, tag coverage,
  formats, what a tag actually contains — run `ffprobe`/`mutagen` and quote
  the output. never estimate what you can count.
- **when a lookup contradicts something already written here or in the spec,
  stop and surface it.** do not silently paper over the difference.

## style

- **all documentation is lowercase.** headings, sentences, prose, pr
  descriptions, commit subjects. sentences need not start with a capital.
  **brand names are lowercased in prose too** — musicfetch, beatport, spotify,
  itunes, musicbrainz, rekordbox, serato.
- **two things keep their case:** acronyms (`ISRC`, `API`, `AIFF`, `BPM`,
  `JSON`, `HTTP`, `UPC`, `DJ`) and anything that is code — identifiers, field
  names, endpoints, file paths. never lowercase `trackNumber` into
  `tracknumber`; it is a real key in a real response.
- **filenames follow convention, not the prose style.** root-level project docs
  are uppercase by convention (`SPEC.md`, `README.md`, `CLAUDE.md`).
- **code follows its language's convention.** python is `snake_case` for
  functions and variables, `PascalCase` for classes — google style, 2-space
  indent. never impose the prose style on identifiers.
- comments explain *why*, never *what*.

## commits, branches, prs

- **conventional commits, short.** `type(scope): subject`, lowercase,
  imperative, **under 70 characters**.
- **no body.** if the why matters it belongs in `SPEC.md`, not a commit
  message. the spec is the record; commits are pointers.
- types: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci`
  `chore` `revert`.
- **commits are small.** one logical change each. a commit that needs "and" in
  its subject is two commits. do not batch unrelated work.
- **never add claude as a co-author.** no `Co-Authored-By`, no
  `Generated with` trailers. these are the user's commits.
- **work on a branch, never commit directly to `main`.**
- **one pr per milestone, never per subtask.** small commits accumulate on the
  branch; the milestone is the unit of review.
- **squash merge.** the branch's commits collapse into one commit on `main`, so
  `main` reads as one entry per milestone. the pr description carries the
  detail: what changed, why, and what was verified.

```
feat(sources): add musicbrainz artist-credit lookup
fix(tag): preserve serato geob frames on rewrite
docs(spec): record beatport api host is not cloudflare-fronted
```


## working agreements

- **measure, do not assume.** if a claim can be tested locally in under an
  hour, test it before writing it into the spec.
- **never destroy another tool's data.** rekordbox and serato write into the
  same tags we do; serato keeps beatgrids and cue points in `GEOB` frames.
  any code that rewrites a tag must preserve frames it does not own.
- **never mutate the library in place without a reversible path.** dry-run
  first, write second.
- **no secrets in the repo, ever.** no cookie files, no tokens. runtime config
  lives in `~/.config/musicpipeline/`.
- push back when an approach has a real problem; do not agree by default.

## git identity

- **never set `user.email` or `user.name` locally in this repo.** the global
  config is already correct: `vishesh
  <64042847+stixvish@users.noreply.github.com>`. a local override shadows it
  silently and the mistake only surfaces at push time.
- the account has **email privacy enabled** (`gh api user` returns
  `"email": null`). pushing a commit authored from a real address is rejected
  with `GH007: your push would publish a private email address`.
- if a commit is ever authored wrongly, fix it **before pushing** — rewriting
  published history is a different and worse problem.

## style, linting, formatting

**this is the only place tooling and style live.** `SPEC.md` describes what we
build and what the code must do; it never specifies indentation, lint rules, or
which formatter runs. if a style rule appears in the spec, it is in the wrong
file.

- **google python style guide**, with one deliberate deviation: **2-space
  indentation**, not 4.
- `snake_case` functions and variables, `PascalCase` classes, `UPPER_SNAKE`
  constants. never impose the lowercase prose style on identifiers.
- **type hints on every public function.** `mypy` runs in strict mode on `src/`.
- docstrings on modules and public functions, google style (`Args:`/`Returns:`).
- comments explain *why*, never *what*.

**ruff is both linter and formatter.** one tool, no black, no isort, no flake8.

```toml
[tool.ruff]
indent-width = 2
line-length  = 88
src          = ["src", "tests"]
target-version = "py312"

[tool.ruff.lint]
select = ["E","W","F","I","N","D","UP","B","A","C4","RET","SIM","ARG","PTH","ANN","S","T20"]
ignore = ["D203","D213","ANN101","ANN102"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["D","ANN","S101"]   # asserts and undocumented fixtures are fine in tests

[tool.ruff.format]
indent-style = "space"
quote-style  = "double"
```

`T20` bans stray `print` in `src/` — the CLI writes through a single output
module so the web ui (`SPEC.md` §14) can capture the same messages. `S` catches
the security footguns that matter here: `subprocess` without a list, `requests`
without a timeout.

**checks run in this order, and all must pass before a commit:**

```
ruff format --check .
ruff check .
mypy src/
pytest -q
```

**never silence a check to get to green.** no new `# noqa`, `# type: ignore`, or
`@pytest.mark.skip` without a comment naming the reason and, where it is
temporary, the condition for removing it. a suppression added to make a commit
pass is a defect, not a fix.
