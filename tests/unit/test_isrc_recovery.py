"""pasting the wrong kind of youtube link is the expected case, not an error.

the two links look identical to a human — same page, same song — and only the
video id distinguishes them. so recovery is the feature, and the duration check
is what keeps it honest.
"""

from music_metadata.isrc_recovery import Recovery, Status, clean_title, recover
from music_metadata.sources.musicfetch import UrlMatch

TRACK = UrlMatch(
  isrc="USJI10000001",
  name="Bye Bye Bye",
  artists=("*NSYNC",),
  duration_s=199.0,
  raw={"services": {"spotify": {}, "youtubeMusic": {}}},
)
VIDEO = UrlMatch(
  isrc=None,
  name="*NSYNC - Bye Bye Bye (Official Video)",
  artists=(),
  duration_s=203.0,
  raw={"services": {"youtube": {}, "youtubeMusic": {}, "youtubeShorts": {}}},
)


class FakeClient:
  """answers by video id, so a test can stage a video and its track."""

  def __init__(self, by_id, calls=None):
    self.by_id = by_id
    self.calls = calls if calls is not None else []

  def isrc_for_url(self, url):
    self.calls.append(url)
    vid = url.rsplit("v=", 1)[-1]
    return self.by_id.get(vid, UrlMatch(None, None, (), None, {}))


def test_a_track_link_resolves_directly():
  out = recover(
    "https://music.youtube.com/watch?v=trk", FakeClient({"trk": TRACK}), 199.0
  )

  assert out.status is Status.OK
  assert out.isrc == "USJI10000001"
  assert out.usable


def test_a_video_link_is_recovered_by_searching_for_the_track():
  """the operator pasted the official video; they meant the song."""
  client = FakeClient({"vid": VIDEO, "trk": TRACK})
  out = recover(
    "https://www.youtube.com/watch?v=vid", client, 199.0, search=lambda q: ["trk"]
  )

  assert out.status is Status.RECOVERED
  assert out.isrc == "USJI10000001"
  assert out.usable
  assert "recovered from a video" in out.note


def test_the_search_uses_the_title_with_the_marketing_stripped():
  seen = []

  def search(query):
    seen.append(query)
    return ["trk"]

  recover(
    "https://www.youtube.com/watch?v=vid",
    FakeClient({"vid": VIDEO, "trk": TRACK}),
    199.0,
    search=search,
  )

  assert seen == ["*NSYNC - Bye Bye Bye"]


def test_a_recovered_track_of_the_wrong_length_is_refused():
  """a search can land on a live version or a remix; G10 still applies."""
  client = FakeClient({"vid": VIDEO, "trk": TRACK})
  out = recover(
    "https://www.youtube.com/watch?v=vid", client, 320.0, search=lambda q: ["trk"]
  )

  assert not out.usable


def test_a_directly_resolved_track_of_the_wrong_length_is_refused():
  out = recover("https://x/watch?v=trk", FakeClient({"trk": TRACK}), 320.0)

  assert out.status is Status.DURATION_MISMATCH
  assert not out.usable
  assert "different recording" in out.note


def test_the_search_keeps_trying_until_one_verifies():
  """the first hit can be a live cut; take the first that agrees on length."""
  wrong = UrlMatch("XX0000000000", "Bye Bye Bye (Live)", (), 400.0, {"services": {}})
  client = FakeClient({"vid": VIDEO, "live": wrong, "trk": TRACK})
  out = recover(
    "https://x/watch?v=vid", client, 199.0, search=lambda q: ["live", "trk"]
  )

  assert out.isrc == "USJI10000001"


def test_a_video_that_cannot_be_recovered_says_what_to_do():
  out = recover(
    "https://x/watch?v=vid", FakeClient({"vid": VIDEO}), 199.0, search=lambda q: []
  )

  assert out.status is Status.VIDEO_UNRESOLVED
  assert "paste that link instead" in out.note
  assert not out.usable


def test_with_no_local_duration_the_result_is_returned_unchecked():
  """the check needs both sides; absence is not evidence against the ISRC."""
  out = recover("https://x/watch?v=trk", FakeClient({"trk": TRACK}), None)

  assert out.usable


def test_an_unplaceable_link_is_not_called_a_video():
  out = recover("https://x/watch?v=nope", FakeClient({}), 199.0)

  assert out.status is Status.NOT_FOUND


def test_clean_title_strips_only_the_marketing():
  assert clean_title("A - B (Official Video)") == "A - B"
  assert clean_title("A - B [Official Audio]") == "A - B"
  assert clean_title("A - B (Live at Wembley)") == "A - B (Live at Wembley)"


def test_recovery_reports_the_artist_and_name_for_display():
  out = recover("https://x/watch?v=trk", FakeClient({"trk": TRACK}), 199.0)

  assert out.who == "*NSYNC"
  assert out.name == "Bye Bye Bye"


def test_an_empty_recovery_is_not_usable():
  assert not Recovery(status=Status.ERROR).usable
