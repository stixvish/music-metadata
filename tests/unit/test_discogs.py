import httpx

from music_metadata.sources.discogs import Discogs, release_from_raw
from music_metadata.sources.ratelimit import TokenBucket

SEARCH = {
  "results": [
    {"id": 3996511, "title": "Calvin Harris - 18 Months", "style": ["House"]},
    {"id": 3991301, "title": "Calvin Harris - 18 Months"},
  ]
}

# the real shape, trimmed. captured live 2026-09-14. note that the search
# endpoint's flat `label` array merges these two groups; the release endpoint
# does not, which is the whole reason F46 requires the second call.
RELEASE = {
  "id": 3996511,
  "title": "18 Months",
  "styles": ["House", "Synth-pop", "Electro"],
  "genres": ["Electronic"],
  "labels": [
    {"name": "Sony Music", "catno": "88697859231", "entity_type_name": "Label"},
    {"name": "Fly Eye", "catno": "88697859231", "entity_type_name": "Label"},
  ],
  "companies": [
    {"name": "Sony DADC", "entity_type_name": "Pressed By"},
    {"name": "EMI Music Publishing", "entity_type_name": "Published By"},
  ],
}


class FakeClock:
  def __init__(self):
    self.t = 0.0

  def now(self):
    return self.t

  def sleep(self, s):
    self.t += s


def make(handler):
  clock = FakeClock()
  return Discogs(
    token="t",
    bucket=TokenBucket(60, now=clock.now, sleep=clock.sleep),
    transport=httpx.MockTransport(handler),
    sleep=clock.sleep,
  )


def test_the_token_is_sent_as_an_authorization_header():
  seen = {}

  def handler(request):
    seen["auth"] = request.headers.get("authorization")
    seen["ua"] = request.headers.get("user-agent")
    return httpx.Response(200, json=SEARCH)

  make(handler).search_release_id("Calvin Harris", "18 Months")

  assert seen["auth"] == "Discogs token=t"
  assert "music-metadata" in seen["ua"]


def test_search_returns_the_first_release_id():
  got, _ = make(lambda r: httpx.Response(200, json=SEARCH)).search_release_id("a", "b")

  assert got == 3996511


def test_search_with_no_results_is_none():
  got, _ = make(lambda r: httpx.Response(200, json={"results": []})).search_release_id(
    "a", "b"
  )

  assert got is None


def test_the_release_supplies_the_label():
  got, _ = make(lambda r: httpx.Response(200, json=RELEASE)).release(3996511)

  assert got.label == "Sony Music"


def test_a_pressing_plant_is_not_a_label():
  """F46: the search endpoint folds plants and publishers into `label`.

  letting `Sony DADC` or `EMI Music Publishing` reach TPUB is exactly the
  failure the release endpoint exists to avoid.
  """
  got, _ = make(lambda r: httpx.Response(200, json=RELEASE)).release(3996511)

  assert "Sony DADC" not in got.labels
  assert "EMI Music Publishing" not in got.labels
  assert got.labels == ("Sony Music", "Fly Eye")


def test_styles_are_carried_as_the_genre_fallback():
  """F47: discogs `styles` beats itunes `primaryGenreName`."""
  got, _ = make(lambda r: httpx.Response(200, json=RELEASE)).release(3996511)

  assert got.style == "House"
  assert got.styles == ("House", "Synth-pop", "Electro")


def test_the_catalog_number_is_carried():
  got, _ = make(lambda r: httpx.Response(200, json=RELEASE)).release(3996511)

  assert got.catalog_number == "88697859231"


def test_a_missing_release_is_none():
  got, _ = make(lambda r: httpx.Response(404)).release(1)

  assert got is None


def test_a_release_with_no_labels_still_parses():
  body = {"id": 1, "title": "x", "styles": ["Techno"]}
  got, _ = make(lambda r: httpx.Response(200, json=body)).release(1)

  assert got.label is None
  assert got.style == "Techno"


def test_a_label_entry_with_no_entity_type_is_kept():
  """older discogs releases omit the field; assuming it is noise would drop
  real labels."""
  body = {"id": 1, "title": "x", "labels": [{"name": "Some Label"}]}

  assert release_from_raw(body).labels == ("Some Label",)


def test_a_stored_payload_re_parses_offline():
  assert release_from_raw(RELEASE).label == "Sony Music"


def test_re_parsing_junk_is_none_not_a_crash():
  assert release_from_raw(None) is None
  assert release_from_raw({"no": "id"}) is None
