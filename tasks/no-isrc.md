# tracks with no ISRC

55 of 1,494 files carry no ISRC tag (§2's measured baseline).
They are **already in the pipeline** — `library.toml` has an entry for each,
and `apply` writes them with whatever the filename yields. What is missing is
the ISRC, which is the key every other field hangs off.

## how to fill one in

Find the entry in `library.toml` by its md5 (the heading), and set `isrc`:

```toml
["5154f8a0e01e0dfd0cda86c43eb7ac41"]
file     = "The Killers - Mr. Brightside.aiff"
isrc     = "GBAHT0400322"          # <- paste it here
```

A hand-edited value outranks every source (§9b) and survives every
regenerate — the merge compares against what was last generated, so anything
you changed is preserved verbatim.

**If a track genuinely is not on Spotify** — a YouTube Music exclusive, say —
leave `isrc` empty and hand-edit `title`, `artist` and `album` instead. The
same preservation rule applies, and the track stops being flagged once the
fields it needs are present.

## the fast way: recover it from a YouTube link

`tools/yt_isrc.py` turns a YouTube Music link into an ISRC (F19), and writes it
straight into `library.toml`:

```bash
# check one
uv run python tools/yt_isrc.py look "https://music.youtube.com/watch?v=m2zUrruKjDQ"
#   USIR20400274  The Killers — Mr. Brightside

# fill many: one `<filename><TAB><url>` line each
uv run python tools/yt_isrc.py fill pairs.txt
```

**Use the YouTube _Music_ link, not the video link.** An official-video upload
is a different entity and resolves to no release; the tool says so rather than
reporting a failure.

Nothing is written unless the recovered ISRC's duration matches the file within
5s, so a mispasted link is caught rather than tagged:

```text
SKIP  Becky Hill - My Heart Goes: USJI10000001 is 200s but the file is 149s
      (51s apart) — wrong track? (G10)
```

## the list

| #   | file                                                                                 | duration | md5 (control-F this)               | search                                                                                                                         |
| --- | ------------------------------------------------------------------------------------ | -------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `A$AP Rocky - Fuckin' Problems (ft. Drake, 2 Chainz & Kendrick Lamar).aiff`          | 3:53     | `88a0bc73ae97ee9c7744de964e5abf8e` | [spotify](https://open.spotify.com/search/A%24AP%20Rocky%20Fuckin%27%20Problems)                                               |
| 2   | `AP Dhillon - Summer High.aiff`                                                      | 2:57     | `65474864af8e9831ea8bfde7dce4546d` | [spotify](https://open.spotify.com/search/AP%20Dhillon%20Summer%20High)                                                        |
| 3   | `Akhtar Chinnal - Afghan Jalebi [Film Version].aiff`                                 | 3:44     | `bff45048b0ee2f33b0ae82ad7113774c` | [spotify](https://open.spotify.com/search/Akhtar%20Chinnal%20Afghan%20Jalebi)                                                  |
| 4   | `American Authors - Best Day of My Life.aiff`                                        | 3:14     | `479164870a9ad5a029932ab93dd09fc9` | [spotify](https://open.spotify.com/search/American%20Authors%20Best%20Day%20of%20My%20Life)                                    |
| 5   | `Ariana Grande & Justin Bieber - Stuck with U.aiff`                                  | 3:48     | `2deb970630aca7af76c4442c3aa21240` | [spotify](https://open.spotify.com/search/Ariana%20Grande%20%26%20Justin%20Bieber%20Stuck%20with%20U)                          |
| 6   | `Arijit Singh - Pachtaoge.aiff`                                                      | 3:46     | `497e0350a0b65a49107ea8e93733a89a` | [spotify](https://open.spotify.com/search/Arijit%20Singh%20Pachtaoge)                                                          |
| 7   | `Arijit Singh - Tum Hi Ho [Remix].aiff`                                              | 3:57     | `49b84dccc69cb30e8652138497c5e6e2` | [spotify](https://open.spotify.com/search/Arijit%20Singh%20Tum%20Hi%20Ho)                                                      |
| 8   | `Becky Hill - My Heart Goes (La Di Da) (ft. Topic).aiff`                             | 2:28     | `bd87af301a63a070ff98967d7c8c2fc2` | [spotify](https://open.spotify.com/search/Becky%20Hill%20My%20Heart%20Goes)                                                    |
| 9   | `Calvin Harris & Clementine Douglas - Blessings (ft. Clementine Douglas).aiff`       | 5:30     | `2a2c97f016c6bc713b273cbffce0094c` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20%26%20Clementine%20Douglas%20Blessings)                            |
| 10  | `Calvin Harris & Jazzy - Satisfy.aiff`                                               | 3:06     | `113fa1a845b1e8f71f4044971a56d443` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20%26%20Jazzy%20Satisfy)                                             |
| 11  | `Calvin Harris & Nicky Romero - Iron.aiff`                                           | 3:39     | `af71032d23c6c26445583e3335142a31` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20%26%20Nicky%20Romero%20Iron)                                       |
| 12  | `Calvin Harris & Swae Lee - Lean on Me.aiff`                                         | 3:52     | `ff18986d6080897ff9728deb26ccc6f5` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20%26%20Swae%20Lee%20Lean%20on%20Me)                                 |
| 13  | `Calvin Harris - Cash Out (ft. ScHoolboy Q, PARTYNEXTDOOR & D.R.A.M.).aiff`          | 3:55     | `dd498e6b90e6385852be81f6b76e239d` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20Cash%20Out)                                                        |
| 14  | `Calvin Harris - Day One (ft. Pharrell & Pusha T).aiff`                              | 3:20     | `ad27b9ff9362958d4c3ec1e50c1a411a` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20Day%20One)                                                         |
| 15  | `Calvin Harris - Holiday (ft. Snoop Dogg, John Legend & Takeoff).aiff`               | 2:49     | `7a295b4c64f7d28e0c7a88c4f47a9eca` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20Holiday)                                                           |
| 16  | `Calvin Harris - Let's Go (ft. Ne-Yo) [Swanky Tunes & Hard Rock Sofa Remix].aiff`    | 5:50     | `2629d40eff417684918c1e1901d02e4e` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20Let%27s%20Go)                                                      |
| 17  | `Calvin Harris - Mansion.aiff`                                                       | 2:07     | `40be6e4c178548e9265446623145a56d` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20Mansion)                                                           |
| 18  | `Calvin Harris - Sweet Nothing (ft. Florence Welch) [Diplo + Grandtheft remix].aiff` | 5:06     | `c905eb4c6e59d2abce4b9d35a9a67ea6` | [spotify](https://open.spotify.com/search/Calvin%20Harris%20Sweet%20Nothing)                                                   |
| 19  | `David Guetta & Laidback Luke - I Need You Now (ft. Samantha Jade).aiff`             | 3:13     | `1f787afe9b915149e592bde036fc585f` | [spotify](https://open.spotify.com/search/David%20Guetta%20%26%20Laidback%20Luke%20I%20Need%20You%20Now)                       |
| 20  | `David Guetta, Bebe Rexha & J Balvin - Say My Name.aiff`                             | 3:18     | `794c39881573093d1d0d665e8636fe2c` | [spotify](https://open.spotify.com/search/David%20Guetta%2C%20Bebe%20Rexha%20%26%20J%20Balvin%20Say%20My%20Name)               |
| 21  | `Dominic Fike - Vampire.aiff`                                                        | 3:06     | `324c152d9c0025ea7a7b3e6bdb60905a` | [spotify](https://open.spotify.com/search/Dominic%20Fike%20Vampire)                                                            |
| 22  | `Drake - Headlines.aiff`                                                             | 3:56     | `3b30af8818ff996912115a660613fb43` | [spotify](https://open.spotify.com/search/Drake%20Headlines)                                                                   |
| 23  | `Fetty Wap - 679 (ft. Monty).aiff`                                                   | 3:06     | `64dbb6af1381996dce4e9d5bbe86ab14` | [spotify](https://open.spotify.com/search/Fetty%20Wap%20679)                                                                   |
| 24  | `Fetty Wap - 679 (ft. Remy Boyz).aiff`                                               | 3:16     | `b7a946826a3dde32a18615482d9bba32` | [spotify](https://open.spotify.com/search/Fetty%20Wap%20679)                                                                   |
| 25  | `Fetty Wap - Trap Queen.aiff`                                                        | 3:42     | `58cb2327bfe7c27c5d843dcc380bd620` | [spotify](https://open.spotify.com/search/Fetty%20Wap%20Trap%20Queen)                                                          |
| 26  | `Flatbush ZOMBiES - Crown (ft. Portugal. The Man).aiff`                              | 4:57     | `d848d96568fbd24b076558ad9994cae9` | [spotify](https://open.spotify.com/search/Flatbush%20ZOMBiES%20Crown)                                                          |
| 27  | `Jackson Wang - LMLY.aiff`                                                           | 3:29     | `2457353ef80ec38d08bf88c6b5cd7ceb` | [spotify](https://open.spotify.com/search/Jackson%20Wang%20LMLY)                                                               |
| 28  | `Jay Sean - Down (ft. Lil Wayne).aiff`                                               | 3:32     | `9fcfe4dfda5f09e748a85be44d7558ef` | [spotify](https://open.spotify.com/search/Jay%20Sean%20Down)                                                                   |
| 29  | `Justin Bieber - Baby (ft. Ludacris).aiff`                                           | 3:34     | `0f3ce5bc7e66cf52e5ec6a137305637c` | [spotify](https://open.spotify.com/search/Justin%20Bieber%20Baby)                                                              |
| 30  | `Justin Bieber - Beauty and a Beat (ft. Nicki Minaj).aiff`                           | 3:47     | `37619092c02c38567479ce94c1301ee0` | [spotify](https://open.spotify.com/search/Justin%20Bieber%20Beauty%20and%20a%20Beat)                                           |
| 31  | `Justin Bieber - One Less Lonely Girl.aiff`                                          | 3:49     | `83b660ec2f8e7ecaf9004caa4eb46022` | [spotify](https://open.spotify.com/search/Justin%20Bieber%20One%20Less%20Lonely%20Girl)                                        |
| 32  | `KSI & Lil Wayne - Lose.aiff`                                                        | 3:25     | `42e5fe2e7fd892cd17c6672c4193f9f4` | [spotify](https://open.spotify.com/search/KSI%20%26%20Lil%20Wayne%20Lose)                                                      |
| 33  | `Karan Aujla - Tauba Tauba.aiff`                                                     | 3:27     | `79383c5349a975f0887dfe322c70c1ed` | [spotify](https://open.spotify.com/search/Karan%20Aujla%20Tauba%20Tauba)                                                       |
| 34  | `Lil Baby & Drake - Yes Indeed.aiff`                                                 | 2:22     | `f4ab2446bfe45bba8b20b03e57d19108` | [spotify](https://open.spotify.com/search/Lil%20Baby%20%26%20Drake%20Yes%20Indeed)                                             |
| 35  | `Lil Baby & Gunna - Drip Too Hard.aiff`                                              | 2:25     | `a93247a1be313f0b0e4162bfea6ec615` | [spotify](https://open.spotify.com/search/Lil%20Baby%20%26%20Gunna%20Drip%20Too%20Hard)                                        |
| 36  | `Lil Baby & Lil Durk - Who I Want.aiff`                                              | 2:53     | `b1df1ae641bb29a5c83b4135fdf73f1d` | [spotify](https://open.spotify.com/search/Lil%20Baby%20%26%20Lil%20Durk%20Who%20I%20Want)                                      |
| 37  | `Lil Baby - Commercial (ft. Lil Uzi Vert).aiff`                                      | 3:34     | `eb7170f26f72f3cd22b654edf41a5f7e` | [spotify](https://open.spotify.com/search/Lil%20Baby%20Commercial)                                                             |
| 38  | `Lil Baby - Life Goes On (ft. Gunna & Lil Uzi Vert).aiff`                            | 4:07     | `276477cfe57d86b82408595f0c389747` | [spotify](https://open.spotify.com/search/Lil%20Baby%20Life%20Goes%20On)                                                       |
| 39  | `Mac Miller & Empire Of The Sun - The Spins.aiff`                                    | 3:15     | `805abf0ac79a886765775656c773a015` | [spotify](https://open.spotify.com/search/Mac%20Miller%20%26%20Empire%20Of%20The%20Sun%20The%20Spins)                          |
| 40  | `Macklemore & Ryan Lewis - Can't Hold Us (ft. Ray Dalton).aiff`                      | 4:18     | `3efc1d1591a8c7c2603dfefbc06a8eeb` | [spotify](https://open.spotify.com/search/Macklemore%20%26%20Ryan%20Lewis%20Can%27t%20Hold%20Us)                               |
| 41  | `Major Lazer - Light It Up (ft. Nyla & Fuse ODG) [remix].aiff`                       | 2:46     | `0e25b204ec22c9ff25b736128759af7b` | [spotify](https://open.spotify.com/search/Major%20Lazer%20Light%20It%20Up)                                                     |
| 42  | `Migos - Fight Night.aiff`                                                           | 3:36     | `9e61e78fd82d3757d9e4d97e8b289b76` | [spotify](https://open.spotify.com/search/Migos%20Fight%20Night)                                                               |
| 43  | `Migos - Get Right Witcha.aiff`                                                      | 4:17     | `c13995b2bd210fea25b1e094f9efba28` | [spotify](https://open.spotify.com/search/Migos%20Get%20Right%20Witcha)                                                        |
| 44  | `Mika Singh & Prakriti Kakar - Hawa Hawa.aiff`                                       | 4:32     | `5a5b8e6c5a6f723e12bd9db4709f1128` | [spotify](https://open.spotify.com/search/Mika%20Singh%20%26%20Prakriti%20Kakar%20Hawa%20Hawa)                                 |
| 45  | `NAV - With Me.aiff`                                                                 | 2:54     | `9e7e3b8f48929dd815310ba2dce43209` | [spotify](https://open.spotify.com/search/NAV%20With%20Me)                                                                     |
| 46  | `Post Malone - 92 Explorer.aiff`                                                     | 3:31     | `ea0e70ca785db9f0965f71275bb3511a` | [spotify](https://open.spotify.com/search/Post%20Malone%2092%20Explorer)                                                       |
| 47  | `Rihanna - We Found Love (ft. Calvin Harris).aiff`                                   | 3:35     | `6368da54548d3ebf3aa0aecbcc244fb7` | [spotify](https://open.spotify.com/search/Rihanna%20We%20Found%20Love)                                                         |
| 48  | `Sean Kingston - Take You There.aiff`                                                | 3:56     | `fd0a2b0c2456c4a122b40addbd5f86c8` | [spotify](https://open.spotify.com/search/Sean%20Kingston%20Take%20You%20There)                                                |
| 49  | `Snoop Dogg, Wiz Khalifa & Bruno Mars - Young, Wild & Free.aiff`                     | 3:27     | `e0f158b2a1043a5502d587f2a837e55b` | [spotify](https://open.spotify.com/search/Snoop%20Dogg%2C%20Wiz%20Khalifa%20%26%20Bruno%20Mars%20Young%2C%20Wild%20%26%20Free) |
| 50  | `Sunidhi Chauhan & Labh Janjua - Dance Pe Chance.aiff`                               | 4:20     | `2070271f1de8b045eb54996d20f60578` | [spotify](https://open.spotify.com/search/Sunidhi%20Chauhan%20%26%20Labh%20Janjua%20Dance%20Pe%20Chance)                       |
| 51  | `Sunidhi Chauhan - Girls Like To Swing.aiff`                                         | 4:03     | `34952ee1c60bb3a9544fa9f914c211ce` | [spotify](https://open.spotify.com/search/Sunidhi%20Chauhan%20Girls%20Like%20To%20Swing)                                       |
| 52  | `The Killers - Mr. Brightside.aiff`                                                  | 3:42     | `5154f8a0e01e0dfd0cda86c43eb7ac41` | [spotify](https://open.spotify.com/search/The%20Killers%20Mr.%20Brightside)                                                    |
| 53  | `Yeah Yeah Yeahs - Heads Will Roll [A-Trak remix].aiff`                              | 3:23     | `4416c7e747b5331035db719b3a9a0be1` | [spotify](https://open.spotify.com/search/Yeah%20Yeah%20Yeahs%20Heads%20Will%20Roll)                                           |
| 54  | `ZAYN - Pillowtalk.aiff`                                                             | 3:22     | `01d5cd2ef52d62e0dd6251a0740943af` | [spotify](https://open.spotify.com/search/ZAYN%20Pillowtalk)                                                                   |
| 55  | `Zack Knight & Jasmin Walia - Bom Diggy Diggy.aiff`                                  | 3:58     | `0d8c0d7712f888ae882f79980c31a4cd` | [spotify](https://open.spotify.com/search/Zack%20Knight%20%26%20Jasmin%20Walia%20Bom%20Diggy%20Diggy)                          |
