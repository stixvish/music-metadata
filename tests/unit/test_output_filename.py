from music_metadata.naming import output_filename


def test_the_name_is_built_from_the_tags_not_the_old_filename():
  """§7a's shape, so the file on disk says what the tags say."""
  assert (
    output_filename("Bye Bye Bye", "*NSYNC", ".aiff") == "*nsync - bye bye bye.aiff"
  )


def test_everything_is_lowercased():
  """macOS is case-insensitive, so a casing fix would otherwise be a rename.

  rekordbox tracks files by path; renaming one it has already imported costs
  a relink. lowercasing everything means a later correction to an artist's
  capitalisation never moves the file.
  """
  assert output_filename("LOUD", "ZOHARA", ".wav") == "zohara - loud.wav"
  assert output_filename("loud", "zohara", ".wav") == "zohara - loud.wav"


def test_the_extension_is_preserved():
  """a wav stays a wav: §9 copies audio, it never transcodes."""
  assert output_filename("x", "y", ".wav").endswith(".wav")
  assert output_filename("x", "y", ".aiff").endswith(".aiff")


def test_path_separators_cannot_escape_the_output_directory():
  """a title with a slash must not create a subdirectory."""
  name = output_filename("AC/DC Tribute", "Some/One", ".aiff")

  assert "/" not in name
  assert not name.startswith(".")


def test_a_colon_is_removed_because_finder_shows_it_as_a_slash():
  assert ":" not in output_filename("Track: The Sequel", "Artist", ".aiff")


def test_a_missing_artist_or_title_still_yields_a_usable_name():
  """resolution can fail; the copy still has to land somewhere sensible."""
  assert output_filename("", "", ".aiff") == "untitled.aiff"
  assert output_filename("song", "", ".aiff") == "song.aiff"


def test_trailing_dots_and_spaces_are_trimmed():
  assert output_filename("Song.", "Artist ", ".aiff") == "artist - song.aiff"
