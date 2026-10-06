"""Tests for the AniSongDB full-catalog provider and playback bridge."""

from types import SimpleNamespace
from copy import deepcopy

import pytest

from core.game_state import state
from _app_scripts.file.metadata import metadata_display, metadata_fetch
from _app_scripts.playback import cache_download
from _app_scripts.playlists import playlist as playlist_ops
from _app_scripts.theme import anisongdb


def _catalog():
    return {
        "anime": {
            "13": {
                "animeJPName": "Cowboy Bebop",
                "animeENName": "Cowboy Bebop",
                "animeAltName": ["カウボーイビバップ"],
                "animeVintage": "Spring 1998",
                "animeType": "TV",
                "animeCategory": "Normal",
                "linked_ids": {
                    "myanimelist": 1,
                    "anidb": 23,
                    "anilist": 1,
                    "kitsu": 1,
                },
                "genres": ["Action", "Sci-Fi"],
                "tags": ["Space"],
            }
        },
        "artists": {
            "18": {
                "names": ["Seatbelts", "SEATBELTS"],
                "type": "Group",
                "disambiguation": None,
                "groups": [],
                "line_ups": [],
            },
            "19": {
                "names": ["Yoko Kanno"],
                "type": "Person",
                "disambiguation": None,
                "groups": [],
                "line_ups": [],
            },
        },
        "songs": [
            {
                "annId": 13,
                "annSongId": 24,
                "amqSongId": 9595,
                "songType": 1,
                "songNumber": 1,
                "songCategory": "Standard",
                "songName": "Tank!",
                "songArtist": "Seatbelts",
                "songComposer": "Yoko Kanno",
                "songArranger": "Yoko Kanno",
                "songDifficulty": 25,
                "songLength": 90,
                "isDub": False,
                "isRebroadcast": False,
                "HQ": "byvisp.webm",
                "MQ": "t0nxjm.webm",
                "audio": "tank.mp3",
                "artists": [[18, -1]],
                "composers": [[19, -1]],
                "arrangers": [[19, -1]],
            }
        ],
    }


@pytest.fixture
def catalog_state(monkeypatch):
    monkeypatch.setattr(state.metadata, "anisongdb_metadata", {})
    monkeypatch.setattr(state.metadata, "file_metadata", {})
    monkeypatch.setattr(state.metadata, "file_metadata_overrides", {})
    monkeypatch.setattr(state.metadata, "anime_metadata", {})
    monkeypatch.setattr(state.metadata, "anime_metadata_overrides", {})
    monkeypatch.setattr(
        state.metadata,
        "anidb_metadata",
        {"23": {"tags": ["space"], "characters": ["Spike"], "episode_info": {"1": {}}}},
    )
    monkeypatch.setattr(state.metadata, "anilist_metadata", {"1": {"title": "Cowboy Bebop"}})
    monkeypatch.setattr(state.metadata, "ai_metadata", {})
    monkeypatch.setattr(state.metadata, "directory_files", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})
    monkeypatch.setattr(metadata_fetch, "_metadata_cache", {})
    anisongdb.replace_catalog(_catalog())
    yield


def test_fetch_catalog_uses_full_dump_endpoint_and_validates_tables():
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return _catalog()

    session = SimpleNamespace(
        get=lambda *args, **kwargs: calls.append((args, kwargs)) or Response()
    )
    assert anisongdb.fetch_catalog(request_session=session) == _catalog()
    args, kwargs = calls[0]
    assert args == (anisongdb.CATALOG_URL,)
    assert "GuessTheAnime/" in kwargs["headers"]["User-Agent"]


@pytest.mark.parametrize(
    "payload",
    [{}, {"anime": {}, "artists": {}, "songs": {}}, []],
)
def test_fetch_catalog_rejects_malformed_responses(payload):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    with pytest.raises(ValueError):
        anisongdb.fetch_catalog(request_session=SimpleNamespace(get=lambda *a, **k: Response()))


@pytest.mark.parametrize(
    "filename",
    [
        "byvisp.webm",
        "Cowboy Bebop [AMQ]9595.webm",
        "Theme [ASDB]9595.mp4",
        "[ANNSONG]24.webm",
    ],
)
def test_catalog_lookup_supports_native_names_and_embedded_ids(catalog_state, filename):
    song = anisongdb.find_song(filename)
    assert song["songName"] == "Tank!"


def test_mal_and_slug_resolve_an_unambiguous_song(catalog_state):
    song = anisongdb.resolve_song_for_mal_slug("1", "OP1")
    assert song["amqSongId"] == 9595


def test_mal_and_slug_do_not_guess_between_distinct_songs(catalog_state):
    catalog = _catalog()
    catalog["songs"].append({
        **catalog["songs"][0],
        "annSongId": 99,
        "amqSongId": 9999,
        "songName": "Different Song",
        "songArtist": "Different Artist",
        "HQ": "other1.webm",
        "MQ": None,
    })
    anisongdb.replace_catalog(catalog)

    assert anisongdb.resolve_song_for_mal_slug("1", "OP1") is None
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title="Tank!")["amqSongId"] == 9595


def test_anisongdb_id_tags_are_not_misclassified_as_animethemes(catalog_state):
    assert cache_download.is_animethemes_stream_file("Theme [AMQ]9595.webm") is False
    assert cache_download.is_animethemes_stream_file("Theme [ANNSONG]24.webm") is False


@pytest.mark.parametrize(
    "filename",
    [
        "byvisp.webm",
        "jr5btc27871w1vn7.webm",
        "Theme [ASDB]9595.mp4",
    ],
)
def test_native_filename_candidate_detection(filename):
    assert anisongdb.looks_like_native_filename(filename) is True


def test_descriptive_animethemes_name_is_not_native_candidate():
    assert anisongdb.looks_like_native_filename("CowboyBebop-OP1.webm") is False


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        ("byvisp.webm", anisongdb.SOURCE_ANISONGDB),
        ("CowboyBebop-OP1-NCBD1080.webm", anisongdb.SOURCE_ANIMETHEMES),
        ("Anything-OP1-[MAL]1[ART]Artist[SNG]Song.webm", anisongdb.SOURCE_MANUAL),
        ("Game-OP1-[IGDB]game-id.webm", anisongdb.SOURCE_MANUAL),
        ("13 Cowboy Bebop Opening 1 - Tank! by Seatbelts.webm", anisongdb.SOURCE_UNKNOWN),
        ("unstructured theme.webm", anisongdb.SOURCE_UNKNOWN),
    ],
)
def test_filename_source_classification(filename, source):
    assert anisongdb.classify_filename(filename) == source


def test_full_catalog_registration_preserves_ids_metadata_and_media(catalog_state):
    assert anisongdb.sync_catalog_to_metadata() == 1

    data = metadata_fetch.get_metadata("byvisp.webm")
    props = data["file_properties"]
    assert data["mal"] == "1"
    assert data["slug"] == "OP1"
    assert data["anisongdb_ann_id"] == 13
    assert data["anisongdb_ann_song_id"] == 24
    assert data["anisongdb_amq_song_id"] == 9595
    # Routine playlist/list metadata stays compact; full provider data is
    # expanded only for explicit detail/fetch paths.
    assert "anisongdb" not in data
    full_data = dict(data)
    anisongdb.apply_full_metadata("byvisp.webm", full_data)
    assert full_data["anisongdb"]["anime"]["genres"] == ["Action", "Sci-Fi"]
    assert full_data["anisongdb"]["artists"][0]["names"] == ["Seatbelts", "SEATBELTS"]
    assert full_data["anisongdb"]["video_sources"] == [
        {
            "quality": "HQ",
            "resolution": 720,
            "media": "byvisp.webm",
            "url": "https://naedist.animemusicquiz.com/byvisp.webm",
        },
        {
            "quality": "MQ",
            "resolution": 480,
            "media": "t0nxjm.webm",
            "url": "https://naedist.animemusicquiz.com/t0nxjm.webm",
        },
    ]
    assert data["title"] == "Cowboy Bebop"
    assert full_data["anisongdb_song"]["composer"] == ["Yoko Kanno"]
    assert props["source"] == "ANISONGDB"
    assert props["anisongdb_gap"] is True
    assert props["anisongdb_preferred"] is True
    assert props.get("anisongdb_alternate") is None
    assert props["anisongdb_media"] == "byvisp.webm"
    assert props["anisongdb_amq_song_id"] == 9595
    assert props["stream_url"] == "https://naedist.animemusicquiz.com/byvisp.webm"
    assert state.metadata.file_metadata["1"]["kitsu"] == "1"
    assert state.metadata.anime_metadata["1"]["anisongdb_tags"] == ["Space"]
    assert cache_download.is_anisongdb_stream_file("byvisp.webm") is True
    assert cache_download.is_animethemes_stream_file("byvisp.webm") is False
    assert cache_download.is_remote_theme_file("byvisp.webm") is True
    assert anisongdb.gap_filenames() == ["byvisp.webm"]
    assert anisongdb.gap_filenames(preferred_only=False) == ["byvisp.webm"]
    assert cache_download.get_theme_stream_urls("byvisp.webm") == [
        "https://naedist.animemusicquiz.com/byvisp.webm",
        "https://naedist.animemusicquiz.com/t0nxjm.webm",
    ]


def test_projection_preserves_distinct_theme_slots_with_shared_amq_song_id(
    catalog_state,
):
    catalog = _catalog()
    opening = catalog["songs"][0]
    insert = {
        **opening,
        "annSongId": 23,
        "songType": 3,
        "songNumber": 0,
        "HQ": "insert.webm",
        "MQ": None,
    }
    catalog["songs"] = [insert, opening]
    anisongdb.replace_catalog(catalog)

    assert anisongdb.sync_catalog_to_metadata() == 2

    songs = state.metadata.anime_metadata["1"]["songs"]
    assert {song["slug"] for song in songs} == {"OP1", "IN23"}
    op = next(song for song in songs if song["slug"] == "OP1")
    assert op["title"] == "Tank!"
    assert op["artist"] == ["Seatbelts"]
    result = metadata_fetch.get_metadata("byvisp.webm")
    assert result["slug"] == "OP1"
    assert next(song for song in result["songs"] if song["slug"] == "OP1") == op


def test_song_sort_order_is_op_then_ed_then_insert_and_numeric():
    songs = [
        {"type": "ED", "slug": "ED2"},
        {"type": "IN", "slug": "IN40301"},
        {"type": "OP", "slug": "OP10"},
        {"type": "ED", "slug": "ED1"},
        {"type": "OP", "slug": "OP2"},
        {"type": "OP", "slug": "OP1v2"},
        {"type": "OP", "slug": "OP1"},
    ]

    assert [song["slug"] for song in metadata_fetch.sort_songs(songs)] == [
        "OP1",
        "OP1v2",
        "OP2",
        "OP10",
        "ED1",
        "ED2",
        "IN40301",
    ]


def test_missing_metadata_targets_include_streaming_only_anisongdb_entries(catalog_state):
    state.metadata.anidb_metadata.clear()
    state.metadata.anilist_metadata.clear()
    anisongdb.sync_catalog_to_metadata()

    targets = metadata_fetch._collect_missing_metadata_targets()

    assert targets["known_anime"] == 1
    assert [item[0] for item in targets["mal"]] == ["1"]
    assert targets["anilist"] == ["1"]
    assert targets["anidb"] == [("23", "1")]
    assert targets["resolve_ids"] == []


def test_existing_anisongdb_stub_fetches_all_linked_metadata(catalog_state, monkeypatch):
    state.metadata.anidb_metadata.clear()
    state.metadata.anilist_metadata.clear()
    monkeypatch.setattr(state.playback, "currently_playing", {})
    anisongdb.sync_catalog_to_metadata()

    monkeypatch.setattr(
        metadata_fetch,
        "fetch_tenrai_metadata",
        lambda _mal_id: {
            "title": "Cowboy Bebop",
            "title_english": "Cowboy Bebop",
            "title_synonyms": [],
            "aired": {"string": "Apr 3, 1998 to Apr 24, 1999"},
            "season": "spring",
            "year": 1998,
            "score": 8.75,
            "rank": 50,
            "members": 2000000,
            "popularity": 43,
            "type": "TV",
            "source": "Original",
            "episodes": 26,
            "studios": [{"name": "Sunrise"}],
            "genres": [{"name": "Action"}],
            "themes": [],
            "demographics": [],
            "synopsis": "Bounty hunters in space.",
            "images": {"jpg": {"large_image_url": "https://example/cover.jpg"}},
            "trailer": {},
        },
    )
    monkeypatch.setattr(
        metadata_fetch,
        "fetch_anilist_metadata",
        lambda **_kwargs: (
            "1",
            {"title": "Cowboy Bebop", "tags": [], "characters": []},
        ),
    )
    monkeypatch.setattr(
        metadata_fetch,
        "fetch_anidb_metadata",
        lambda _anidb_id: {
            "tags": [["space", 600]],
            "characters": [["a", "Spike Spiegel", "spike.jpg", "male"]],
            "episodes": [[1, "Asteroid Blues"]],
        },
    )

    result = metadata_fetch.fetch_metadata("byvisp.webm", batch_mode=True)

    assert result["members"] == 2000000
    assert state.metadata.anime_metadata["1"]["synopsis"] == "Bounty hunters in space."
    assert state.metadata.anilist_metadata["1"]["title"] == "Cowboy Bebop"
    assert state.metadata.anidb_metadata["23"]["tags"] == [["space", 600]]


def test_failed_anisongdb_fetch_releases_in_flight_marker(catalog_state, monkeypatch):
    anisongdb.sync_catalog_to_metadata()
    metadata_fetch.fetching_metadata.clear()
    monkeypatch.setattr(
        metadata_fetch,
        "fetch_tenrai_metadata",
        lambda _mal_id: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        metadata_fetch.fetch_metadata("byvisp.webm", batch_mode=True)

    assert "byvisp.webm" not in metadata_fetch.fetching_metadata


def test_linked_id_resolution_reports_only_newly_resolved_sources():
    status, complete = metadata_fetch._linked_id_resolution_status(
        ("anilist",),
        {"anidb": "23"},
    )

    assert status == "✗ AniList unavailable"
    assert complete is False

    status, complete = metadata_fetch._linked_id_resolution_status(
        ("anilist", "anidb"),
        {"anidb": "23"},
    )

    assert status == "⚠ Resolved AniDB; AniList unavailable"
    assert complete is False


def test_anilist_not_found_message_identifies_the_lookup(monkeypatch, capsys):
    response = SimpleNamespace(
        status_code=404,
        text='{"errors":[{"message":"Not Found."}]}',
    )
    monkeypatch.setattr(metadata_fetch.requests, "post", lambda *_args, **_kwargs: response)

    assert metadata_fetch.fetch_anilist_metadata(mal_id="52864") == (None, None)
    output = capsys.readouterr().out
    assert output == "AniList has no anime entry for MAL 52864. "
    assert "errors" not in output


def test_catalog_exposes_matching_animethemes_song_as_selectable_alternate(catalog_state):
    state.metadata.file_metadata["1"] = {
        "name": "Cowboy Bebop",
        "mal": "1",
        "themes": {
            "OP1": {
                "1": {
                    "CowboyBebop-OP1.webm": {
                        "source": "BD",
                        "resolution": 1080,
                    }
                }
            }
        },
    }
    state.metadata.anime_metadata["1"] = {
        "title": "Cowboy Bebop",
        "songs": [{"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["SEATBELTS"]}],
    }

    assert anisongdb.sync_catalog_to_metadata() == 0

    songs = state.metadata.anime_metadata["1"]["songs"]
    assert len(songs) == 1
    assert songs[0]["artist"] == ["SEATBELTS"]
    assert songs[0]["anisongdb_amq_song_id"] == 9595
    assert songs[0]["composer"] == ["Yoko Kanno"]
    existing_props = state.metadata.file_metadata["1"]["themes"]["OP1"]["1"][
        "CowboyBebop-OP1.webm"
    ]
    assert existing_props["source"] == "BD"
    assert existing_props["anisongdb_ann_song_id"] == 24
    assert existing_props["anisongdb_amq_song_id"] == 9595
    assert existing_props["anisongdb_media"] == "byvisp.webm"
    alternate_props = state.metadata.file_metadata["1"]["themes"]["OP1"]["1"][
        "byvisp.webm"
    ]
    assert alternate_props["source"] == "ANISONGDB"
    assert alternate_props["anisongdb_alternate"] is True
    assert alternate_props.get("anisongdb_gap") is None
    assert metadata_display.get_theme_filenames("1", "OP1", 1) == [
        "CowboyBebop-OP1.webm",
        "byvisp.webm",
    ]
    assert metadata_display.get_theme_filename("1", "OP1", 1) == "CowboyBebop-OP1.webm"
    assert cache_download.get_theme_stream_urls("CowboyBebop-OP1.webm") == [
        "https://v.animethemes.moe/CowboyBebop-OP1.webm",
        "https://naedist.animemusicquiz.com/byvisp.webm",
        "https://naedist.animemusicquiz.com/t0nxjm.webm",
    ]
    full_data = metadata_fetch.get_metadata("CowboyBebop-OP1.webm")
    anisongdb.apply_full_metadata("CowboyBebop-OP1.webm", full_data)
    assert full_data["anisongdb"]["songName"] == "Tank!"
    assert full_data["anisongdb"][
        "video_sources"
    ][0]["media"] == "byvisp.webm"
    assert anisongdb.gap_filenames() == []


def test_anisongdb_artist_aliases_use_existing_animethemes_spelling(catalog_state):
    catalog = _catalog()
    catalog["artists"]["18"] = {
        "names": ["Hatsune Miku", "Kemurikusa"],
        "type": "Group",
        "disambiguation": None,
        "groups": [],
        "line_ups": [],
    }
    catalog["songs"][0].update(
        {
            "songName": "Known Miku Theme",
            "songArtist": "Hatsune Miku",
        }
    )
    catalog["anime"].update(
        {
            "14": {
                "animeJPName": "AniSongDB Miku Anime",
                "animeENName": "AniSongDB Miku Anime",
                "linked_ids": {"myanimelist": 2},
            },
            "15": {
                "animeJPName": "Kemurikusa Context",
                "animeENName": "Kemurikusa Context",
                "linked_ids": {"myanimelist": 3},
            },
        }
    )
    catalog["songs"].extend(
        [
            {
                **catalog["songs"][0],
                "annId": 14,
                "annSongId": 25,
                "amqSongId": 9596,
                "songName": "New Miku Theme",
                "HQ": "mikutheme.webm",
                "MQ": None,
            },
            {
                **catalog["songs"][0],
                "annId": 15,
                "annSongId": 26,
                "amqSongId": 9597,
                "songName": "Kemurikusa Theme",
                "songArtist": "Yuuyu feat. Kemurikusa",
                "HQ": "kemurikusa.webm",
                "MQ": None,
            },
        ]
    )
    state.metadata.file_metadata["1"] = {
        "name": "Known Miku Anime",
        "mal": "1",
        "themes": {
            "OP1": {
                "1": {
                    "KnownMiku-OP1.webm": {
                        "source": "BD",
                        "resolution": 1080,
                    }
                }
            }
        },
    }
    state.metadata.anime_metadata["1"] = {
        "title": "Known Miku Anime",
        "songs": [
            {
                "type": "OP",
                "slug": "OP1",
                "title": "Known Miku Theme",
                "artist": ["Miku Hatsune"],
            }
        ],
    }
    anisongdb.replace_catalog(catalog)

    assert anisongdb.sync_catalog_to_metadata() == 2
    assert state.metadata.anime_metadata["1"]["songs"][0]["artist"] == [
        "Miku Hatsune"
    ]
    assert state.metadata.anime_metadata["2"]["songs"][0]["artist"] == [
        "Miku Hatsune"
    ]
    assert state.metadata.anime_metadata["3"]["songs"][0]["artist"] == [
        "Kemurikusa"
    ]
    assert catalog["artists"]["18"]["names"] == ["Hatsune Miku", "Kemurikusa"]


def test_web_theme_payload_lists_anisongdb_as_a_version_file_option(
    catalog_state, monkeypatch
):
    state.metadata.file_metadata["1"] = {
        "name": "Cowboy Bebop",
        "mal": "1",
        "themes": {
            "OP1": {
                "1": {
                    "CowboyBebop-OP1.webm": {
                        "source": "BD",
                        "resolution": 1080,
                    }
                }
            }
        },
    }
    state.metadata.anime_metadata["1"] = {
        "title": "Cowboy Bebop",
        "songs": [
            {
                "type": "OP",
                "slug": "OP1",
                "title": "Tank!",
                "artist": ["SEATBELTS"],
                "versions": [{"version": 1, "episodes": "1-26"}],
            }
        ],
    }
    monkeypatch.setattr(
        state.metadata,
        "playlist",
        {"infinite": False, "playlist": [], "current_index": 0},
    )
    monkeypatch.setattr(metadata_display, "overall_theme_num_display", lambda _filename: "")

    anisongdb.sync_catalog_to_metadata()
    data = dict(state.metadata.anime_metadata["1"])
    data.update({"mal": "1", "slug": "OP1"})
    series = metadata_display._build_web_series_themes(data, "byvisp.webm")

    version = series[0]["sections"][0]["themes"][0]["versions"][0]
    assert version["filename"] == "CowboyBebop-OP1.webm"
    assert [item["filename"] for item in version["files"]] == [
        "CowboyBebop-OP1.webm",
        "byvisp.webm",
    ]
    assert version["files"][0]["file_props"] == "[1080 BD]"
    assert version["files"][1]["file_props"] == "[720 ANISONGDB]"
    assert version["files"][1]["is_playing"] is True


def test_covered_alternate_stays_out_of_source_pool_until_local(catalog_state):
    animethemes_file = "CowboyBebop-OP1.webm"
    state.metadata.file_metadata["1"] = {
        "name": "Cowboy Bebop",
        "mal": "1",
        "themes": {"OP1": {"1": {animethemes_file: {"source": "DVD", "resolution": 480}}}},
    }
    state.metadata.anime_metadata["1"] = {
        "title": "Cowboy Bebop",
        "songs": [{"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["SEATBELTS"]}],
    }
    anisongdb.sync_catalog_to_metadata()

    remote_pool = playlist_ops.get_directory_files(include_non_local=True)
    assert animethemes_file in remote_pool
    assert "byvisp.webm" not in remote_pool

    state.metadata.directory_files[animethemes_file] = "themes/CowboyBebop-OP1.webm"
    assert metadata_display.get_theme_filenames("1", "OP1", 1) == [
        animethemes_file,
        "byvisp.webm",
    ]
    state.metadata.directory_files["byvisp.webm"] = "themes/byvisp.webm"
    assert "byvisp.webm" in playlist_ops.get_directory_files(include_non_local=False)


def test_gap_lookup_wins_when_same_media_is_alternate_elsewhere(catalog_state):
    state.metadata.file_metadata.update({
        "1": {
            "themes": {
                "OP1": {
                    "1": {
                        "shared.webm": {
                            "source": "ANISONGDB",
                            "stream_url": "https://example/alternate",
                            "anisongdb_alternate": True,
                        }
                    }
                }
            }
        },
        "2": {
            "themes": {
                "ED1": {
                    "1": {
                        "shared.webm": {
                            "source": "ANISONGDB",
                            "stream_url": "https://example/gap",
                            "anisongdb_gap": True,
                        }
                    }
                }
            }
        },
    })

    metadata_fetch.build_filename_to_mal_map()

    data = metadata_fetch.get_file_metadata_by_name("shared.webm")
    assert data["mal"] == "2"
    assert data["slug"] == "ED1"
    assert data["file_properties"]["anisongdb_gap"] is True


def test_animethemes_download_can_fall_back_to_anisongdb(catalog_state, monkeypatch, tmp_path):
    filename = "CowboyBebop-OP1.webm"
    state.metadata.file_metadata["1"] = {
        "name": "Cowboy Bebop",
        "mal": "1",
        "themes": {"OP1": {"1": {filename: {"source": "BD"}}}},
    }
    anisongdb.sync_catalog_to_metadata()
    calls = []

    class Response:
        headers = {"content-length": "5"}

        def __init__(self, succeeds):
            self.succeeds = succeeds

        def raise_for_status(self):
            if not self.succeeds:
                raise RuntimeError("primary unavailable")

        def iter_content(self, chunk_size):
            assert chunk_size == 8192
            return [b"video"]

    def fake_get(url, **_kwargs):
        calls.append(url)
        return Response(url.startswith("https://naedist.animemusicquiz.com/"))

    monkeypatch.setattr(cache_download.requests, "get", fake_get)
    destination = tmp_path / filename

    assert cache_download._download_theme_file_to_path(filename, destination) is True
    assert destination.read_bytes() == b"video"
    assert calls == [
        "https://v.animethemes.moe/CowboyBebop-OP1.webm",
        "https://naedist.animemusicquiz.com/byvisp.webm",
    ]


def test_catalog_marks_only_slugs_missing_from_other_sources_as_gaps(catalog_state):
    catalog = _catalog()
    catalog["songs"].append(
        {
            **catalog["songs"][0],
            "annSongId": 25,
            "amqSongId": 9596,
            "songType": 2,
            "songName": "The Real Folk Blues",
            "HQ": "ending.webm",
            "MQ": None,
        }
    )
    anisongdb.replace_catalog(catalog)
    state.metadata.file_metadata["1"] = {
        "name": "Cowboy Bebop",
        "mal": "1",
        "themes": {
            "OP1": {"1": {"CowboyBebop-OP1.webm": {"source": "BD"}}},
        },
    }

    assert anisongdb.sync_catalog_to_metadata() == 1
    themes = state.metadata.file_metadata["1"]["themes"]
    assert set(themes) == {"OP1", "ED1"}
    assert themes["OP1"]["1"]["byvisp.webm"]["anisongdb_alternate"] is True
    assert themes["ED1"]["1"]["ending.webm"]["anisongdb_gap"] is True
    assert anisongdb.gap_filenames() == ["ending.webm"]
    assert anisongdb.gap_filenames(theme_types={"OP"}) == []
    assert anisongdb.gap_filenames(theme_types={"ED"}) == ["ending.webm"]


def test_manual_local_file_also_satisfies_gap_coverage(catalog_state):
    state.metadata.file_metadata["1"] = {
        "name": "Cowboy Bebop",
        "mal": "1",
        "themes": {
            "OP1": {"null": {"Custom-OP1-[MAL]1.webm": {"source": "LOCAL"}}},
        },
    }

    assert anisongdb.sync_catalog_to_metadata() == 0
    assert anisongdb.gap_filenames() == []
    assert state.metadata.file_metadata["1"]["themes"]["OP1"]["1"][
        "byvisp.webm"
    ]["anisongdb_alternate"] is True


def test_normal_fetch_detects_native_anisongdb_file(catalog_state):
    result = metadata_fetch.fetch_metadata("byvisp.webm", batch_mode=True)

    assert result["mal"] == "1"
    assert result["title"] == "Cowboy Bebop"
    assert result["anisongdb_song"]["title"] == "Tank!"
    assert result["anisongdb_song"]["artist"] == ["Seatbelts"]
    assert result["anisongdb"]["audio"] == "tank.mp3"


def test_manual_mal_file_uses_slug_to_fill_missing_song_data(catalog_state, monkeypatch):
    monkeypatch.setattr(metadata_fetch, "fetch_arm_ids", lambda _mal: {"anidb": "23", "anilist": "1"})
    monkeypatch.setattr(
        metadata_fetch,
        "fetch_animethemes_metadata",
        lambda *args, **kwargs: {"animethemes": []},
    )
    monkeypatch.setattr(metadata_fetch, "fetch_tenrai_metadata", lambda _mal: None)

    filename = "Custom-OP1-[mal]1.webm"
    result = metadata_fetch.fetch_metadata(filename, batch_mode=True)

    song = next(item for item in result["songs"] if item["slug"] == "OP1")
    props = metadata_fetch.get_file_metadata_by_name(filename)["file_properties"]
    assert song["title"] == "Tank!"
    assert song["artist"] == ["Seatbelts"]
    assert song["composer"] == ["Yoko Kanno"]
    assert props["source"] == "LOCAL"
    assert props["anisongdb_ann_song_id"] == 24
    assert props["anisongdb_amq_song_id"] == 9595
    assert result["anisongdb"]["songDifficulty"] == 25


def test_insert_song_media_id_gets_a_stable_unique_slug(catalog_state):
    catalog = _catalog()
    catalog["songs"].append(
        {
            "annId": 13,
            "annSongId": 20270,
            "amqSongId": 42209,
            "songType": 3,
            "songNumber": 0,
            "songCategory": "Standard",
            "songName": "Green Bird",
            "songArtist": "Gabriela Robin",
            "isDub": False,
            "isRebroadcast": False,
            "HQ": "ins001.webm",
            "MQ": None,
            "artists": [],
            "composers": [],
            "arrangers": [],
        }
    )
    anisongdb.replace_catalog(catalog)

    filename = "ins001.webm"
    song = anisongdb.find_song(filename)
    assert anisongdb.theme_slug(song) == "IN20270"
    assert anisongdb.register_detected_file(filename, song) is True
    assert metadata_fetch.get_metadata(filename)["slug"] == "IN20270"


def test_tagged_renamed_file_uses_best_available_stream(catalog_state):
    filename = "Cowboy Bebop-OP1-[AMQ]9595.webm"
    assert anisongdb.register_detected_file(filename) is True
    props = metadata_fetch.get_metadata(filename)["file_properties"]
    assert props["anisongdb_media"] == "byvisp.webm"
    assert props["resolution"] == 720


def test_native_mq_file_keeps_its_exact_media_variant(catalog_state):
    assert anisongdb.register_detected_file("t0nxjm.webm") is True
    props = metadata_fetch.get_metadata("t0nxjm.webm")["file_properties"]
    assert props["anisongdb_media"] == "t0nxjm.webm"
    assert props["resolution"] == 480
    assert props["stream_url"].endswith("/t0nxjm.webm")


def test_registered_theme_can_fall_back_to_direct_stream(catalog_state, monkeypatch):
    anisongdb.sync_catalog_to_metadata()
    monkeypatch.setattr(cache_download, "get_cached_file_path", lambda _filename: None)
    monkeypatch.setattr(cache_download, "download_to_cache", lambda *_args, **_kwargs: False)

    assert cache_download.resolve_playable_path(
        "byvisp.webm", "byvisp.webm", None, fullscreen=False
    ) == ("https://naedist.animemusicquiz.com/byvisp.webm", True)


def test_overall_theme_number_accepts_missing_animethemes_fields(catalog_state, monkeypatch):
    data = {
        "mal": "1",
        "slug": "OP1",
        "title": "Cowboy Bebop",
        "eng_title": "Cowboy Bebop",
        "type": "TV",
        "themes": None,
        "songs": [{"type": "OP", "slug": "OP1"}],
    }
    state.metadata.anime_metadata["1"] = data
    monkeypatch.setattr(metadata_display.metadata_fetch, "get_metadata", lambda _name: data)

    assert metadata_display.get_overall_theme_number("byvisp.webm") == 1


@pytest.fixture
def mismatched_endings(catalog_state, monkeypatch):
    monkeypatch.setattr(state.metadata, "animethemes_metadata", {})
    catalog = {
        "anime": {"20197": {"animeJPName": "Banana Fish", "linked_ids": {"myanimelist": 36649}}},
        "artists": {},
        # The dump is not necessarily in ending-number order.
        "songs": [
            {"annId": 20197, "annSongId": 22230, "amqSongId": 48488, "songType": 2,
             "songNumber": 3, "songName": "RED", "songArtist": "Survive Said The Prophet",
             "songComposer": "Survive Said The Prophet", "songArranger": "Survive Said The Prophet",
             "HQ": "red.webm"},
            {"annId": 20197, "annSongId": 21018, "amqSongId": 45307, "songType": 2,
             "songNumber": 1, "songName": "Prayer X", "songArtist": "King Gnu", "HQ": "prayer.webm"},
            {"annId": 20197, "annSongId": 47939, "amqSongId": 81962, "songType": 2,
             "songNumber": 2, "songName": "Prayer X (acoustic)", "songArtist": "King Gnu",
             "songComposer": "Daiki Tsuneta", "songArranger": "King Gnu", "HQ": "acoustic.webm"},
        ],
    }
    anisongdb.replace_catalog(catalog)
    wrong_identity = {
        "anisongdb_ann_id": 20197, "anisongdb_ann_song_id": 47939, "anisongdb_amq_song_id": 81962,
    }
    state.metadata.anime_metadata["36649"] = {
        "title": "Banana Fish", "eng_title": "Banana Fish", "type": "TV", "themes": [],
        "songs": [
            {"type": "ED", "slug": "ED1", "title": "Prayer X", "artist": ["King Gnu"],
             "composer": ["Curated composer"]},
            {"type": "ED", "slug": "ED2", "title": "RED", "artist": ["Survive Said The Prophet"],
             "composer": ["Daiki Tsuneta"], "arranger": ["King Gnu"], **wrong_identity},
            {"type": "ED", "slug": "ED3", "title": "RED", "artist": ["Survive Said The Prophet"],
             "anisongdb_only": True, "anisongdb_ann_id": 20197, "anisongdb_ann_song_id": 22230},
        ],
    }
    state.metadata.file_metadata["36649"] = {
        "name": "Banana Fish", "mal": "36649", "anisongdb_ann_id": 20197,
        "anisongdb_projection_version": 4,
        "themes": {
            "ED1": {"1": {"BananaFish-ED1.webm": {"source": "BD"}}},
            "ED2": {"1": {"BananaFish-ED2.webm": {
                "source": "BD", **wrong_identity,
                "anisongdb_stream_url": anisongdb.media_url("acoustic.webm"),
                "anisongdb_fallback_stream_urls": [anisongdb.media_url("wrong.webm")],
            }, "acoustic.webm": {"source": "ANISONGDB", "anisongdb_alternate": True}}},
            "ED3": {"1": {"red.webm": {"source": "ANISONGDB", "anisongdb_gap": True}}},
        },
    }
    return catalog


def test_known_song_identity_resolves_across_numbers_and_rejects_conflicts(mismatched_endings):
    song = anisongdb.resolve_song_for_mal_slug(
        "36649", "ED2", title="RED", artists=["Survive Said The Prophet"],
    )
    assert song["songNumber"] == 3
    assert anisongdb.resolve_song_for_mal_slug("36649", "ED2", title="Unknown song") is None
    assert anisongdb.resolve_song_for_mal_slug("36649", "ED2", title="RED", artists=["King Gnu"]) is None


def test_projection_repairs_saved_mismatches_and_persists_decimal_slots(mismatched_endings):
    assert anisongdb.sync_catalog_to_metadata() == 1
    songs = state.metadata.anime_metadata["36649"]["songs"]
    assert [(song["slug"], song["title"]) for song in songs] == [
        ("ED1", "Prayer X"), ("ED1.1", "Prayer X (acoustic)"), ("ED2", "RED"),
    ]
    assert songs[0]["composer"] == ["Curated composer"]
    assert songs[1]["artist"] == ["King Gnu"]
    assert songs[1]["anisongdb_source_slug"] == "ED2"
    assert songs[2]["anisongdb_source_slug"] == "ED3"
    assert songs[2]["anisongdb_ann_song_id"] == 22230
    assert songs[2]["composer"] == ["Survive Said The Prophet"]
    assert songs[2]["arranger"] == ["Survive Said The Prophet"]
    themes = state.metadata.file_metadata["36649"]["themes"]
    assert set(themes) == {"ED1", "ED1.1", "ED2"}
    red = themes["ED2"]["1"]["BananaFish-ED2.webm"]
    assert red["source"] == "BD"
    assert red["anisongdb_ann_song_id"] == 22230
    assert red["anisongdb_stream_url"] == anisongdb.media_url("red.webm")
    assert "anisongdb_fallback_stream_urls" not in red
    assert themes["ED2"]["1"]["red.webm"]["anisongdb_alternate"] is True
    assert anisongdb.gap_filenames() == ["acoustic.webm"]
    assert metadata_fetch.get_metadata("acoustic.webm")["slug"] == "ED1.1"
    assert metadata_display.get_overall_theme_number("acoustic.webm") == 1.1
    assert metadata_display.get_overall_theme_number("red.webm") == 2
    before = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == before


def test_saved_mapping_restores_without_recalculating_numbering(mismatched_endings):
    anisongdb.sync_catalog_to_metadata()
    anisongdb.replace_catalog(deepcopy(mismatched_endings))
    assert anisongdb.theme_slug(anisongdb.find_song("red.webm")) == "ED2"
    assert anisongdb.theme_slug(anisongdb.find_song("acoustic.webm")) == "ED1.1"
    assert anisongdb.resolve_song_for_mal_slug("36649", "ED1.1")["songName"] == "Prayer X (acoustic)"


def test_extra_ending_after_last_anchor_uses_next_integer(mismatched_endings):
    catalog = deepcopy(mismatched_endings)
    catalog["songs"].append({
        "annId": 20197, "annSongId": 999, "amqSongId": 888, "songType": 2,
        "songNumber": 4, "songName": "Final ending", "songArtist": "King Gnu", "HQ": "final.webm",
    })
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    song = next(song for song in state.metadata.anime_metadata["36649"]["songs"] if song["title"] == "Final ending")
    assert song["slug"] == "ED3"
    assert song["anisongdb_source_slug"] == "ED4"


def test_decimal_slugs_sort_parse_and_keep_distinct_play_identity():
    slugs = ["ED2", "ED1.2", "ED1v2", "ED1.01", "ED1", "ED1.1"]
    assert metadata_fetch.sort_songs(slugs) == ["ED1", "ED1v2", "ED1.01", "ED1.1", "ED1.2", "ED2"]
    filename = "BananaFish-ED1.1v2-[MAL]36649.webm"
    assert metadata_fetch._filename_theme_slug(filename) == "ED1.1"
    assert metadata_fetch._filename_theme_slug("BananaFish-ED1.1") == "ED1.1"
    assert metadata_fetch.get_version_from_filename(filename) == "2"
    assert metadata_display._file_play_key(filename, {}) == ("theme", "36649", "ED1.1")


def test_older_imported_snapshot_is_migrated_without_deleting_metadata(mismatched_endings):
    from _app_scripts.file.metadata import metadata_import

    old_package = {
        "anisongdb_metadata": deepcopy(mismatched_endings),
        "anime_metadata": deepcopy(state.metadata.anime_metadata),
        "file_metadata": deepcopy(state.metadata.file_metadata),
    }
    state.metadata.anime_metadata["local-only"] = {"title": "Local entry"}
    metadata_import._apply_package_stores(old_package)
    assert state.metadata.anime_metadata["local-only"] == {"title": "Local entry"}
    assert [song["slug"] for song in state.metadata.anime_metadata["36649"]["songs"]] == ["ED1", "ED1.1", "ED2"]
    assert anisongdb.registered_projection_version() == anisongdb.PROJECTION_VERSION


def test_updated_export_replaces_wrong_entries_and_preserves_user_overrides(mismatched_endings):
    from _app_scripts.file.metadata import metadata_import

    old_files = deepcopy(state.metadata.file_metadata)
    old_anime = deepcopy(state.metadata.anime_metadata)
    anisongdb.sync_catalog_to_metadata()
    package = {
        "anime_metadata": deepcopy(state.metadata.anime_metadata),
        "file_metadata": deepcopy(state.metadata.file_metadata),
    }
    state.metadata.file_metadata.clear()
    state.metadata.file_metadata.update(old_files)
    state.metadata.anime_metadata.clear()
    state.metadata.anime_metadata.update(old_anime)
    state.metadata.anime_metadata_overrides["36649"] = {"songs": [{"slug": "ED2", "artist": ["Personal credit"]}]}
    overrides = deepcopy(state.metadata.anime_metadata_overrides)
    metadata_import._apply_package_stores(package)
    assert [song["slug"] for song in state.metadata.anime_metadata["36649"]["songs"]] == ["ED1", "ED1.1", "ED2"]
    assert state.metadata.file_metadata["36649"]["themes"]["ED2"]["1"]["BananaFish-ED2.webm"]["anisongdb_ann_song_id"] == 22230
    assert state.metadata.anime_metadata_overrides == overrides


def test_old_playlist_references_follow_repaired_media_within_same_anime(mismatched_endings):
    from _app_scripts.playlists import entry_paths

    old_red = entry_paths.make_theme_reference("red.webm", "36649", "ED3", "1")
    old_acoustic = entry_paths.make_theme_reference("acoustic.webm", "36649", "ED2", "1")
    anisongdb.sync_catalog_to_metadata()
    assert metadata_fetch.get_file_metadata_by_name(old_red)["slug"] == "ED2"
    assert metadata_fetch.get_file_metadata_by_name(old_acoustic)["slug"] == "ED1.1"
    assert metadata_display._file_play_key(old_acoustic) == ("theme", "36649", "ED1.1")
    data = metadata_fetch.get_metadata(old_red)
    assert data["slug"] == "ED2"
    assert next(song for song in data["songs"] if song["slug"] == data["slug"])["title"] == "RED"


def test_more_than_nine_inserted_endings_fit_between_existing_slots(mismatched_endings):
    catalog = deepcopy(mismatched_endings)
    catalog["songs"][0]["songNumber"] = 14
    template = catalog["songs"].pop()
    for i in range(12):
        catalog["songs"].append({
            **template, "annSongId": 50000 + i, "amqSongId": 60000 + i,
            "songNumber": i + 2, "songName": f"Extra ending {i}", "HQ": f"extra{i}.webm",
        })
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    songs = state.metadata.anime_metadata["36649"]["songs"]
    assert songs[0]["slug"] == "ED1"
    assert songs[-1]["slug"] == "ED2"
    assert [song["title"] for song in songs[1:-1]] == [f"Extra ending {i}" for i in range(12)]
    assert len({song["slug"] for song in songs}) == 14


def test_mixed_projection_versions_trigger_repair(mismatched_endings):
    state.metadata.file_metadata["another"] = {"anisongdb_projection_version": anisongdb.PROJECTION_VERSION}
    assert anisongdb.registered_projection_version() == 4


def test_startup_migrates_cached_metadata_and_reapplies_personal_overrides(mismatched_endings, monkeypatch):
    from _app_scripts.data import metadata_io
    from core.paths import ANISONGDB_METADATA_FILE, ANIME_METADATA_FILE, FILE_METADATA_FILE

    saved = {
        FILE_METADATA_FILE: deepcopy(state.metadata.file_metadata),
        ANIME_METADATA_FILE: deepcopy(state.metadata.anime_metadata),
        ANISONGDB_METADATA_FILE: deepcopy(mismatched_endings),
    }
    monkeypatch.setattr(metadata_io, "load_metadata_compressed", lambda path, **kwargs: (deepcopy(saved.get(path)), True))
    monkeypatch.setattr(metadata_io.os.path, "exists", lambda path: False)
    monkeypatch.setattr(metadata_io, "load_theme_artist_resolutions", lambda: None)
    saved_calls = []
    monkeypatch.setattr(metadata_io, "save_metadata", lambda **kwargs: saved_calls.append(True))
    state.metadata.anime_metadata_overrides["36649"] = {"songs": [{"slug": "ED2", "composer": ["Personal composer"]}]}
    metadata_io.load_metadata()
    assert saved_calls
    songs = state.metadata.anime_metadata["36649"]["songs"]
    assert [song["slug"] for song in songs] == ["ED1", "ED1.1", "ED2"]
    assert songs[-1]["composer"] == ["Personal composer"]
    assert songs[-1]["anisongdb_ann_song_id"] == 22230
