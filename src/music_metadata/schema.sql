-- the sidecar cache (SPEC.md §9a). a permanent store keyed by identity, not a
-- scratch file: a re-run must cost no API calls, or "improving the resolver
-- re-tags the library for free" (§4) is not true.

-- one row per file on disk. path is the identity.
--
-- NOTE, and it is a deliberate departure from §9a's wording: audio_md5 and isrc
-- are indexed but NOT unique. §9a says "unique(audio_md5) and unique(isrc)",
-- which the measured library contradicts — 6 ISRCs appear on two files each
-- (cache/dupisrc.txt) and 3 audio md5s do too (cache/dupaudio.txt). §11a's
-- duplicate taxonomy classifies those pairs by comparing the two rows, so both
-- members have to exist to be compared. a unique constraint would reject the
-- second row at insert and leave nothing to classify.
CREATE TABLE IF NOT EXISTS files (
  path          TEXT PRIMARY KEY,
  audio_md5     TEXT NOT NULL,
  duration_s    REAL NOT NULL,
  isrc_from_tag TEXT,
  mtime         REAL,
  probed_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS files_audio_md5 ON files (audio_md5);
CREATE INDEX IF NOT EXISTS files_isrc ON files (isrc_from_tag);

-- raw responses, one row per recording. the resolved fields are a VIEW over
-- these: storing raw payloads is what lets a parsing fix be replayed offline
-- instead of forcing a re-fetch of 1,494 tracks (§9a).
CREATE TABLE IF NOT EXISTS recordings (
  isrc             TEXT PRIMARY KEY,
  fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
  source_version   INTEGER NOT NULL,
  raw_spotify      TEXT,
  raw_musicbrainz  TEXT,
  raw_work         TEXT,
  raw_beatport     TEXT,
  raw_itunes       TEXT,
  raw_discogs      TEXT
);
CREATE INDEX IF NOT EXISTS recordings_source_version
  ON recordings (source_version);

-- the equivalence map: which service id we matched, and how much to trust it.
-- matched_by records whether the id came from an exact ISRC lookup or a text
-- search, because F9 showed search-derived links are not ISRC-verified.
CREATE TABLE IF NOT EXISTS service_ids (
  isrc       TEXT NOT NULL,
  service    TEXT NOT NULL,
  service_id TEXT,
  url        TEXT,
  matched_by TEXT,
  verified   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (isrc, service)
);

-- computed lazily, kept forever. the MBID and the fingerprint live here and
-- never in ID3, so the audio files stay clean and a future acoustid pass stays
-- cheap (§15).
CREATE TABLE IF NOT EXISTS fingerprints (
  isrc        TEXT PRIMARY KEY,
  chromaprint TEXT NOT NULL,
  duration_s  REAL NOT NULL
);

-- 3-4 GB of covers, fetched once. source_release is what §7c verified the
-- artwork against, so a later audit can tell which release a cover came from.
CREATE TABLE IF NOT EXISTS artwork (
  isrc           TEXT PRIMARY KEY,
  source_release TEXT,
  url_template   TEXT,
  width          INTEGER,
  sha256         TEXT,
  local_path     TEXT
);

-- drives the web ui's progress (§14). a 72-minute resolve cannot block an
-- http request, so its state lives here rather than in the request.
CREATE TABLE IF NOT EXISTS jobs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL,
  state      TEXT NOT NULL DEFAULT 'pending',
  progress   REAL NOT NULL DEFAULT 0.0,
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  error      TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs (state);

-- what the resolver last wrote into library.toml, per (md5, field).
--
-- §9b's merge rule needs this and nothing else can supply it: on the next run,
-- a value in the file that still equals what we generated is ours to refresh,
-- and a value that differs was edited by the operator and is preserved. without
-- a record of what we generated, those two cases are indistinguishable and the
-- resolver would either clobber every edit or never refresh anything.
CREATE TABLE IF NOT EXISTS map_generated (
  audio_md5 TEXT NOT NULL,
  field     TEXT NOT NULL,
  value     TEXT,
  PRIMARY KEY (audio_md5, field)
);

-- the review queue (§14). the gates in §8 refuse to guess — a flagged track is
-- a decision someone has to make, and §6 is explicit that disagreements are
-- "queued for review, never auto-resolved". a flag in a log file is worthless;
-- here it is a worklist.
CREATE TABLE IF NOT EXISTS review (
  audio_md5 TEXT NOT NULL,
  flag      TEXT NOT NULL,
  file      TEXT,
  proposed  TEXT,
  source    TEXT,
  PRIMARY KEY (audio_md5, flag)
);
CREATE INDEX IF NOT EXISTS review_flag ON review (flag);
