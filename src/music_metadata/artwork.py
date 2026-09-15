"""the verified artwork chain (SPEC.md §7c, as amended by F37).

**the danger is not resolution, it is identity.** an image returned for a track
is the cover of whichever release the matcher landed on, and that is a
compilation often enough to matter (F34). so every candidate is verified against
the release §7b already chose, before its bytes are used.

the chain, first candidate that verifies wins:

```text
1. §7b has already chosen the release  ->  album name + album artist
2. candidate A — itunes album search
3. candidate B — itunes song search       <- replaces musicfetch (F37)
4. candidate C — spotify's album image, correct by construction, ~640px
5. nothing verifies -> keep the existing art and flag the track (G5)
```

**the name check must reject, not coerce.** searching itunes for `Calvin Harris
18 Months` returns exactly one album: `96 Months`, a different record. a fuzzy
ratio or a "closest result wins" rule would embed the wrong cover with no signal
that anything went wrong.

the artist is checked too, which §7c does not say. measured live: searching
`*NSYNC No Strings Attached` returns a *second* album of that exact name by
Brian Robert Jones. matching on `collectionName` alone accepts it the moment
apple reorders its results.
"""

from __future__ import annotations

import hashlib
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from music_metadata.release import strip_edition
from music_metadata.sources.itunes import Itunes, ItunesRelease

# §7c / OQ-1: 3000² is the decision.
#
# measured live 2026-09-14: **apple caps at each album's own master, and the
# master size varies per album.** `No Strings Attached` serves 3600² for any
# request above it; `18 Months` serves 3000². neither reaches the 4500 ceiling
# F5 records, and over-asking never errors — it silently returns the master.
#
# so 3000 is not a technical ceiling, it is OQ-1's storage decision, and it is a
# safe one: every album measured serves at least 3000.
SIZES = (3000, 1400, 600)

CANDIDATE_ALBUM_SEARCH = "itunes-album-search"
CANDIDATE_SONG_SEARCH = "itunes-song-search"
CANDIDATE_SPOTIFY = "spotify-album-image"
# **an operator-supplied link outranks every search** (§9b). it is the one
# candidate that needs no verification: nothing was guessed, so there is
# nothing to reject. it is also the only way to reach a release the search
# index does not carry — measured on `Checkers`, which returns zero results
# for every term tried across five stores but looks up cleanly by id, at
# 3000px against spotify's 640.
CANDIDATE_MANUAL = "operator-supplied"

# https://music.apple.com/us/album/checkers/1657261196?i=1657261206
#                                            ^collection    ^track
_APPLE_URL = re.compile(
  r"music\.apple\.com/[^/]+/(?:album|song)/[^/]*/(?P<collection>\d+)"
)
_APPLE_TRACK = re.compile(r"[?&]i=(?P<track>\d+)")

# the size segment apple puts at the end of every artwork URL.
_SIZE_SEGMENT = re.compile(r"/\d+x\d+bb\.jpg$")

# a JPEG small enough to be an error page or a placeholder rather than a cover.
MIN_PLAUSIBLE_BYTES = 10_000


@dataclass(frozen=True, slots=True)
class Artwork:
  """the bytes chosen for a track, and where they came from."""

  data: bytes
  mime: str
  width: int
  candidate: str
  source_release: str
  url: str

  @property
  def sha256(self) -> str:
    """Hash of the fetched bytes, for the cache."""
    return hashlib.sha256(self.data).hexdigest()


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
  """Read a JPEG's real pixel dimensions from its SOF marker.

  This is not cosmetic. F54 measured that apple serves each album's own master
  and silently returns that for any larger request — asking for 3000 can yield
  1425. recording the size we *asked for* would put a false number in the cache
  and in any later audit.

  Args:
    data: the JPEG bytes.

  Returns:
    Width and height, or None if the markers cannot be read.
  """
  index = 2
  while index < len(data) - 9:
    if data[index] != 0xFF:
      return None
    marker = data[index + 1]
    if marker in (0xC0, 0xC1, 0xC2):
      height, width = struct.unpack(">HH", data[index + 5 : index + 9])
      return (width, height)
    try:
      index += 2 + struct.unpack(">H", data[index + 2 : index + 4])[0]
    except struct.error:
      return None
  return None


def _fold(text: str) -> str:
  """Normalise a name for comparison only.

  Args:
    text: the raw name.

  Returns:
    A comparison key with case and punctuation removed.
  """
  return re.sub(r"[^a-z0-9]+", "", text.lower())


def matches_release(
  candidate: ItunesRelease, album_name: str, album_artist: str
) -> bool:
  """Whether an itunes result is the release §7b chose.

  Accepts an exact match on normalised text, or the chosen album name contained
  in the result's — a deluxe edition of the right album is still the right
  cover. Rejects everything else, including a result whose name merely
  *contains* a word from the chosen one.

  Args:
    candidate: the itunes result.
    album_name: the album §7b chose.
    album_artist: that release's artist.

  Returns:
    True only when the result is that release.
  """
  if not candidate.artwork_url_100:
    return False

  # **compare album *families*, not exact names.** the edition qualifier is
  # the one part of the name that does not identify the record: `El Dorado`
  # and `El Dorado (Deluxe)` are the same album, and apple's artwork is a
  # per-album master either way (F54). without this, the name §7b chose could
  # never match the name itunes indexes.
  want_album = _fold(strip_edition(album_name))
  got_album = _fold(strip_edition(candidate.collection_name))
  if not want_album or not got_album:
    return False
  # the result may be longer than what we asked for, never shorter.
  if want_album not in got_album:
    return False

  want_artist = _fold(album_artist)
  got_artist = _fold(candidate.artist_name)
  if not want_artist:
    return True
  return want_artist in got_artist or got_artist in want_artist


def apple_collection_id(url: str) -> int | None:
  """Read the collection id out of an apple music link.

  Args:
    url: a `music.apple.com` album or song link.

  Returns:
    The collection id, or None when the url is not one.
  """
  found = _APPLE_URL.search(url)
  return int(found.group("collection")) if found else None


def upgrade_url(artwork_url_100: str, size: int) -> str:
  """Rewrite an artwork URL to ask for a larger square (F5).

  Args:
    artwork_url_100: the URL itunes returned.
    size: the pixel width to request.

  Returns:
    The rewritten URL, or the original when it carries no size segment.
  """
  return _SIZE_SEGMENT.sub(f"/{size}x{size}bb.jpg", artwork_url_100)


def first_verified(
  candidates: list[ItunesRelease], album_name: str, album_artist: str
) -> ItunesRelease | None:
  """Return the first candidate that is the chosen release.

  Args:
    candidates: itunes results, in the order itunes returned them.
    album_name: the album §7b chose.
    album_artist: that release's artist.

  Returns:
    The verified result, or None when none of them is that release.
  """
  for candidate in candidates:
    if matches_release(candidate, album_name, album_artist):
      return candidate
  return None


# fetching image bytes is not a JSON call, so it does not go through `Source`.
# the timeout is still mandatory: a stalled CDN connection must not hang a run.
_FETCH_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)


def fetch_bytes(url: str, client: httpx.Client | None = None) -> bytes | None:
  """Fetch image bytes, or None when the URL does not serve a usable image.

  Args:
    url: the artwork URL.
    client: an existing client to reuse; one is made per call otherwise.

  Returns:
    The bytes, or None on a non-200, a short read, or a transport failure.
  """
  owned = client is None
  client = client or httpx.Client(timeout=_FETCH_TIMEOUT)
  try:
    response = client.get(url)
  except httpx.HTTPError:
    return None
  finally:
    if owned:
      client.close()

  if response.status_code != httpx.codes.OK:
    return None
  # a short read is apple serving a placeholder or an error page, not a cover.
  if len(response.content) < MIN_PLAUSIBLE_BYTES:
    return None
  return response.content


def fetch_largest(
  artwork_url_100: str,
  fetch: Callable[[str], bytes | None] = fetch_bytes,
) -> tuple[bytes, int, str] | None:
  """Fetch the largest square apple will serve, stepping down on failure.

  §7c: step 3000 -> 1400 -> 600 rather than failing the track.

  Args:
    artwork_url_100: the URL itunes returned.
    fetch: injectable byte fetcher.

  Returns:
    The bytes, the width fetched, and the URL used — or None if every size
    failed.
  """
  for size in SIZES:
    url = upgrade_url(artwork_url_100, size)
    data = fetch(url)
    if data is not None:
      # the real dimensions, not the requested ones — apple caps at the
      # album's master and does so silently (F54).
      measured = jpeg_dimensions(data)
      return (data, measured[0] if measured else size, url)
  return None


def artwork_from_link(
  itunes: Itunes,
  link: str,
  fetch: Callable[[str], bytes | None] = fetch_bytes,
) -> Artwork | None:
  """Resolve artwork from a link the operator pasted into the map.

  Two shapes are accepted, because both are things an operator actually has:
  an apple music page link, and a direct image url.

  Args:
    itunes: the itunes adapter, for the id lookup.
    link: the pasted value.
    fetch: injectable byte fetcher.

  Returns:
    The artwork, or None when the link yields nothing.
  """
  link = link.strip()
  if not link:
    return None

  collection = apple_collection_id(link)
  if collection is not None:
    releases = itunes.lookup(collection).releases
    for release in releases:
      if not release.artwork_url_100:
        continue
      got = fetch_largest(release.artwork_url_100, fetch=fetch)
      if got is None:
        continue
      data, width, url = got
      return Artwork(
        data=data,
        mime="image/jpeg",
        width=width,
        candidate=CANDIDATE_MANUAL,
        source_release=release.collection_name,
        url=url,
      )
    return None

  # a direct image url: taken as given, since the operator asserted it.
  direct = fetch(link)
  if direct is None or len(direct) < MIN_PLAUSIBLE_BYTES:
    return None
  return Artwork(
    data=direct,
    mime="image/jpeg",
    width=0,
    candidate=CANDIDATE_MANUAL,
    source_release="",
    url=link,
  )


def resolve_artwork(
  itunes: Itunes,
  album_name: str,
  album_artist: str,
  track_name: str,
  spotify_image_url: str | None = None,
  fetch: Callable[[str], bytes | None] = fetch_bytes,
) -> Artwork | None:
  """Walk §7c's chain and return the first artwork that verifies.

  Args:
    itunes: the itunes adapter.
    album_name: the album §7b chose.
    album_artist: that release's artist.
    track_name: the track name, for the song-search candidate.
    spotify_image_url: spotify's own album image, correct by construction but
      capped around 640px.
    fetch: injectable byte fetcher.

  Returns:
    The verified artwork, or None — in which case §7c keeps the existing
    embedded art and G5 flags the track, rather than substituting an
    unverified image.
  """
  # the edition qualifier is stripped from the *search term* because itunes
  # returns nothing for it; the chosen album name is still what gets verified
  # against, and still what lands in the tag.
  searches = (
    (
      CANDIDATE_ALBUM_SEARCH,
      f"{album_artist} {strip_edition(album_name)}".strip(),
      itunes.search_albums,
    ),
    (
      CANDIDATE_SONG_SEARCH,
      f"{album_artist} {track_name}".strip(),
      itunes.search_songs,
    ),
  )
  for candidate_name, term, search in searches:
    if not term:
      continue
    verified = first_verified(search(term).releases, album_name, album_artist)
    if verified is None or not verified.artwork_url_100:
      continue
    got = fetch_largest(verified.artwork_url_100, fetch=fetch)
    if got is None:
      continue
    data, width, url = got
    return Artwork(
      data=data,
      mime="image/jpeg",
      width=width,
      candidate=candidate_name,
      source_release=verified.collection_name,
      url=url,
    )

  # candidate C: correct by construction — it is the chosen release's own image
  # — but capped around 640px, so it is last rather than first.
  if spotify_image_url:
    fallback = fetch(spotify_image_url)
    if fallback is not None:
      return Artwork(
        data=fallback,
        mime="image/jpeg",
        width=0,
        candidate=CANDIDATE_SPOTIFY,
        source_release=album_name,
        url=spotify_image_url,
      )

  return None
