"""musicfetch is used for exactly one thing: F19's url -> ISRC."""

import httpx
import pytest

from music_metadata.sources.base import SourceError
from music_metadata.sources.musicfetch import Musicfetch
from music_metadata.sources.ratelimit import TokenBucket

TRACK = {
  "result": {
    "type": "track",
    "name": "Bye Bye Bye",
    "isrc": "USJI10000001",
    "duration": 199000,
    "artists": [{"name": "*NSYNC"}],
    "services": {"spotify": {"id": "x"}, "youtubeMusic": {"id": "fxHjlCBHuzA"}},
  }
}

VIDEO = {
  "result": {
    "type": "track",
    "name": "*NSYNC - Bye Bye Bye (Official Video)",
    "services": {"youtube": {"id": "Eo"}, "youtubeMusic": {"id": "Eo"}},
  }
}


def client(payload, status=200):
  def handler(request):
    return httpx.Response(status, json=payload)

  return Musicfetch(
    token="t",
    bucket=TokenBucket(10_000),
    transport=httpx.MockTransport(handler),
  )


def test_a_track_url_yields_the_isrc():
  match = client(TRACK).isrc_for_url("https://music.youtube.com/watch?v=fxHjlCBHuzA")

  assert match.isrc == "USJI10000001"


def test_the_name_is_the_track_not_the_artist():
  """regression: a walrus named `name` in the artists comprehension leaked
  into the enclosing scope and overwrote the track name."""
  match = client(TRACK).isrc_for_url("https://music.youtube.com/watch?v=x")

  assert match.name == "Bye Bye Bye"
  assert match.artists == ("*NSYNC",)


def test_the_duration_comes_back_in_seconds():
  """so a recovered ISRC can be checked against the file it is for (G10)."""
  assert client(TRACK).isrc_for_url("https://x").duration_s == 199.0


def test_an_official_video_is_reported_as_a_video_not_a_failure():
  """measured: the video upload resolves to youtube services and no release.

  telling the operator to use the track link is actionable; telling them the
  lookup failed is not.
  """
  match = client(VIDEO).isrc_for_url("https://www.youtube.com/watch?v=Eo")

  assert match.isrc is None
  assert match.looks_like_a_video


def test_a_url_that_resolved_elsewhere_is_not_called_a_video():
  """the hint must only fire when youtube really is all there was."""
  payload = {"result": {"name": "x", "services": {"spotify": {"id": "s"}}}}
  match = client(payload).isrc_for_url("https://x")

  assert match.isrc is None
  assert not match.looks_like_a_video


def test_a_rejected_token_is_an_error_not_a_miss():
  """401 must not read as "no isrc for this url"."""
  with pytest.raises(SourceError):
    client({"error": {"status": 401}}, status=401).isrc_for_url("https://x")


def test_a_body_of_the_wrong_shape_yields_nothing_rather_than_raising():
  assert client({"result": "nope"}).isrc_for_url("https://x").isrc is None
