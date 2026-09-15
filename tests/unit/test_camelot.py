"""§7f's table, moved out of the tool's `__main__` block into real tests."""

import pytest

from music_metadata.camelot import to_camelot

# every key beatport returned during spec research, plus both anchor pairs.
MEASURED = [
  ("Eb Minor", "2A"),
  ("B Minor", "10A"),
  ("Ab Minor", "1A"),
  ("Db Major", "3B"),
  ("D Major", "10B"),
  ("E Major", "12B"),
  ("C Minor", "5A"),
  ("B Major", "1B"),
  ("G Minor", "6A"),
  ("A Minor", "8A"),
  ("C Major", "8B"),
]


@pytest.mark.parametrize(("key", "code"), MEASURED)
def test_every_key_beatport_returned(key, code):
  assert to_camelot(key) == code


@pytest.mark.parametrize(
  ("key", "code"),
  [("1A", "Ab Minor"), ("1B", "B Major"), ("8A", "A Minor"), ("8B", "C Major")],
)
def test_the_published_anchors(key, code):
  """§7f: verified against published charts, not derived from memory."""
  assert to_camelot(code) == key


@pytest.mark.parametrize(
  ("key", "code"),
  [
    ("D# Minor", "2A"),
    ("G# Minor", "1A"),
    ("C# Major", "3B"),
    ("Gb Major", "2B"),
    ("A# Minor", "3A"),
  ],
)
def test_enharmonic_spellings(key, code):
  assert to_camelot(key) == code


@pytest.mark.parametrize(
  ("key", "code"), [("f# minor", "11A"), ("F MAJOR", "7B"), ("Bb maj", "6B")]
)
def test_case_and_abbreviation_variants(key, code):
  assert to_camelot(key) == code


@pytest.mark.parametrize("key", ["", "nonsense", "H Minor", "C", None, "Eb Sideways"])
def test_an_unparseable_key_is_none(key):
  """§7f: a wrong key survives into a set and gets trusted. None does not."""
  assert to_camelot(key) is None


def test_unicode_accidentals_are_accepted():
  assert to_camelot("E♭ Minor") == "2A"
  assert to_camelot("F♯ Minor") == "11A"


def test_all_twenty_four_codes_are_reachable_and_unique():
  """the wheel has exactly 24 positions; a collision would silently mislabel."""
  roots_major = ["C", "G", "D", "A", "E", "B", "F#", "Db", "Ab", "Eb", "Bb", "F"]
  roots_minor = ["A", "E", "B", "F#", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D"]

  codes = [to_camelot(f"{r} Major") for r in roots_major]
  codes += [to_camelot(f"{r} Minor") for r in roots_minor]

  assert None not in codes
  assert len(set(codes)) == 24
  assert set(codes) == {f"{n}{letter}" for n in range(1, 13) for letter in "AB"}


def test_relative_keys_share_a_number():
  """`nA` and `nB` share the same seven notes — that is what the wheel means."""
  assert to_camelot("C Major")[:-1] == to_camelot("A Minor")[:-1]
  assert to_camelot("B Major")[:-1] == to_camelot("Ab Minor")[:-1]
