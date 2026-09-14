import pytest

from music_metadata.naming import (
  join_artists,
  normalise_mix,
  remixer_from_mix,
  render_title,
  split_filename,
  split_title,
)

# --- separator style (§7a, OQ-7 decided) -------------------------------------


def test_a_single_artist_has_no_separator():
  assert join_artists(["Arijit Singh"]) == "Arijit Singh"


def test_two_artists_are_joined_with_an_ampersand():
  assert join_artists(["Benny Dayal", "Shalmali Kholgade"]) == (
    "Benny Dayal & Shalmali Kholgade"
  )


def test_three_artists_use_commas_then_an_ampersand():
  assert join_artists(["Benny Dayal", "Shalmali Kholgade", "Divya Kumar"]) == (
    "Benny Dayal, Shalmali Kholgade & Divya Kumar"
  )


def test_no_artists_is_empty():
  assert join_artists([]) == ""


def test_blank_artists_are_dropped():
  assert join_artists(["A", "", "  ", "B"]) == "A & B"


# --- mix normalisation (§7a table) -------------------------------------------


@pytest.mark.parametrize(
  ("raw", "expected"),
  [
    ("Extended Mix", "Extended"),
    ("Extended Version", "Extended"),
    ("Extended", "Extended"),
    ("extended mix", "Extended"),
    ("Radio Edit", "Radio Edit"),
    ("Radio Mix", "Radio Edit"),
    ("Radio Version", "Radio Edit"),
    ("Original Mix", "Original"),
    ("Original Version", "Original"),
  ],
)
def test_the_normalisation_table(raw, expected):
  """§7a: the library holds both `[extended mix]` and bare `[extended]`."""
  assert normalise_mix(raw) == expected


@pytest.mark.parametrize(
  "raw",
  ["Odd Mob Remix", "Continuous Mix", "Instrumental", "Club Mix", "Tiësto Flip"],
)
def test_mixes_that_pass_through_unchanged(raw):
  assert normalise_mix(raw) == raw


def test_an_absent_mix_is_none():
  assert normalise_mix(None) is None
  assert normalise_mix("") is None


# --- remixer identity (§7a) --------------------------------------------------


@pytest.mark.parametrize(
  ("mix", "remixer"),
  [
    ("Odd Mob Remix", "Odd Mob"),
    ("Tiësto Remix", "Tiësto"),
    ("Skrillex Flip", "Skrillex"),
    ("Habstrakt VIP", "Habstrakt"),
    ("Dom Dolla Edit", "Dom Dolla"),
    ("MK Bootleg", "MK"),
  ],
)
def test_a_third_party_remix_yields_a_remixer(mix, remixer):
  assert remixer_from_mix(mix) == remixer


@pytest.mark.parametrize(
  "mix",
  ["Extended", "Extended Mix", "Radio Edit", "Club Mix", "Original", "Instrumental"],
)
def test_an_extended_mix_is_not_a_remix(mix):
  """§7a: the original artist reworking their own track is not a remixer."""
  assert remixer_from_mix(mix) is None


def test_no_mix_means_no_remixer():
  assert remixer_from_mix(None) is None


def test_a_bare_remix_with_no_name_yields_no_remixer():
  assert remixer_from_mix("Remix") is None


# --- parsing what apple and spotify actually send (§7a, F25) -----------------


def test_a_bare_name_parses_to_itself():
  got = split_title("Blessings")

  assert got.name == "Blessings"
  assert got.features == ()
  assert got.mix is None


def test_a_trailing_dash_suffix_becomes_the_mix():
  """F25: apple and spotify render mixes as `Name - Odd Mob Remix`."""
  got = split_title("Blessings - Odd Mob Remix")

  assert got.name == "Blessings"
  assert got.mix == "Odd Mob Remix"


def test_a_dash_suffix_is_normalised():
  assert split_title("Blessings - Extended Mix").mix == "Extended"


def test_a_feature_in_the_title_is_extracted():
  got = split_title("Levitating (feat. DaBaby)")

  assert got.name == "Levitating"
  assert got.features == ("DaBaby",)


@pytest.mark.parametrize(
  "raw",
  [
    "Levitating (feat. DaBaby)",
    "Levitating (ft. DaBaby)",
    "Levitating (featuring DaBaby)",
    "Levitating (Feat. DaBaby)",
  ],
)
def test_every_feature_spelling_is_recognised(raw):
  assert split_title(raw).features == ("DaBaby",)


def test_multiple_features_are_split():
  got = split_title("Sweet Nothing (feat. Florence Welch & Calvin Harris)")

  assert got.features == ("Florence Welch", "Calvin Harris")


def test_comma_separated_features_are_split():
  got = split_title("Fuckin' Problems (feat. Drake, 2 Chainz & Kendrick Lamar)")

  assert got.features == ("Drake", "2 Chainz", "Kendrick Lamar")


def test_a_bracketed_mix_is_read():
  got = split_title("Blessings [Odd Mob Remix]")

  assert got.name == "Blessings"
  assert got.mix == "Odd Mob Remix"


def test_features_and_a_mix_together():
  got = split_title("Blessings (feat. Clementine Douglas) [Extended Mix]")

  assert got.name == "Blessings"
  assert got.features == ("Clementine Douglas",)
  assert got.mix == "Extended"


def test_a_parenthetical_mix_is_read_as_a_mix_not_a_feature():
  got = split_title("Blessings (Odd Mob Remix)")

  assert got.name == "Blessings"
  assert got.features == ()
  assert got.mix == "Odd Mob Remix"


def test_a_from_suffix_is_left_alone():
  """§7b: choosing the right release removes `(From "…")`; §7a never strips it.

  if it still reaches the parser the release choice was wrong, and silently
  deleting it would hide that.
  """
  got = split_title('Kamariya (From "Stree")')

  assert got.name == 'Kamariya (From "Stree")'


# --- rendering the canonical shape (§7a) -------------------------------------


def test_a_bare_name_renders_bare():
  assert render_title("Blessings", (), None) == "Blessings"


def test_features_render_in_the_parenthetical():
  assert render_title("Blessings", ("Clementine Douglas",), None) == (
    "Blessings (ft. Clementine Douglas)"
  )


def test_a_mix_renders_in_the_bracket():
  assert render_title("Blessings", (), "Odd Mob Remix") == "Blessings [Odd Mob Remix]"


def test_both_render_in_order():
  """§7a: `{Name} (ft. {Featured artists}) [{Mix name}]`."""
  assert render_title("Blessings", ("Clementine Douglas",), "Extended") == (
    "Blessings (ft. Clementine Douglas) [Extended]"
  )


def test_multiple_features_are_comma_separated_in_the_title():
  """§7a: the parenthetical carries featured artists, comma-separated."""
  assert render_title("Track", ("A", "B", "C"), None) == "Track (ft. A, B, C)"


def test_rendering_is_stable_through_a_parse():
  raw = "Blessings (feat. Clementine Douglas) [Extended Mix]"
  got = split_title(raw)

  assert render_title(got.name, got.features, got.mix) == (
    "Blessings (ft. Clementine Douglas) [Extended]"
  )


def test_original_is_never_invented():
  """§7a: `Original` goes to TIT3 only when the source states it."""
  assert split_title("Blessings").mix is None
  assert render_title("Blessings", (), None) == "Blessings"


# --- the filename, which §6 ranks above spotify and itunes -------------------


def test_a_filename_splits_on_the_separator():
  assert split_filename("*NSYNC - Bye Bye Bye") == ("*NSYNC", "Bye Bye Bye")


def test_a_filename_with_a_feature_keeps_it_in_the_title_part():
  artist, title = split_filename("Arizona Zervas - OH MY LORD (ft. 24kGoldn)")

  assert artist == "Arizona Zervas"
  assert title == "OH MY LORD (ft. 24kGoldn)"


def test_a_filename_title_parses_the_feature_out():
  _, title = split_filename("Arizona Zervas - OH MY LORD (ft. 24kGoldn)")

  assert split_title(title).features == ("24kGoldn",)


def test_a_filename_with_no_separator_is_all_title():
  assert split_filename("Untitled") == ("", "Untitled")


def test_only_the_first_separator_splits():
  artist, title = split_filename("A - B - C")

  assert artist == "A"
  assert title == "B - C"
