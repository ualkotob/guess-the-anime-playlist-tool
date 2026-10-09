"""Tests for the AniSongDB full-catalog provider and playback bridge."""

from types import SimpleNamespace
from copy import deepcopy
import json
from pathlib import Path

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
    artist_overrides = json.loads((Path(__file__).parent / "fixtures/anisongdb_artist_overrides.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(state.metadata, "anime_metadata_overrides", {"1": {"anisongdb_matching": artist_overrides}})
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


@pytest.fixture(params=[
    ("GATE: Sore wa Akatsuki no you ni", "GATE~Sore wa Akatsuki no You ni~",
     "Kishida Kyoudan & The Akeboshi Rockets", "KISIDA KYODAN & THE AKEBOSI ROCKETS", "OP2", True, 5),
    ("Akatsuki no Yona", "Akatsuki no Yona", "Ryou Kunihiko", "Ryo Kunihiko", "OP1.1", False, 5),
    ("Level wo Agete Butsuri de Naguru", "Level o Agete Butsuri de Naguru",
     "Kishida Kyoudan & The Akeboshi Rockets", "KISIDA KYODAN & THE AKEBOSI ROCKETS", "OP2", True, 6),
], ids=["gate", "yona", "last_boss"])
def romanized_duplicate(catalog_state, monkeypatch, request):
    monkeypatch.setattr(state.metadata, "animethemes_metadata", {})
    title, source_title, artist, source_artist, wrong_slug, linked_artist, old_version = request.param
    catalog = _catalog()
    catalog["songs"][0].update({"songName": source_title, "songArtist": source_artist,
                                "MQ": None, "artists": [[18, -1]] if linked_artist else []})
    catalog["artists"]["18"]["names"] = [source_artist]
    state.metadata.anime_metadata["1"] = {
        "title": "Example", "anisongdb_projection_version": old_version, "songs": [
            {"type": "OP", "slug": "OP1", "title": title, "artist": [artist],
             "versions": [{"version": 1, "episodes": "1-14"}]},
            {"type": "OP", "slug": wrong_slug, "title": source_title, "artist": [source_artist],
             "anisongdb_only": True, "anisongdb_ann_id": 13, "anisongdb_ann_song_id": 24},
        ],
    }
    state.metadata.file_metadata["1"] = {
        "mal": "1", "anisongdb_ann_id": 13, "anisongdb_projection_version": old_version,
        "themes": {
            "OP1": {"1": {"Example-OP1.webm": {"source": "BD", "resolution": 1080}}},
            wrong_slug: {"1": {"byvisp.webm": {"source": "ANISONGDB", "anisongdb_gap": True}}},
        },
    }
    anisongdb.replace_catalog(catalog)
    return catalog, title, artist, wrong_slug


def test_romanization_repair_merges_saved_extra_into_selectable_file(romanized_duplicate):
    from _app_scripts.playlists import entry_paths

    catalog, title, artist, wrong_slug = romanized_duplicate
    raw = deepcopy(catalog)
    old_reference = entry_paths.make_theme_reference("byvisp.webm", "1", wrong_slug, "1")
    assert anisongdb.registered_projection_version() == state.metadata.file_metadata["1"]["anisongdb_projection_version"]
    assert anisongdb.sync_catalog_to_metadata() == 0
    songs = state.metadata.anime_metadata["1"]["songs"]
    assert len(songs) == 1
    assert (songs[0]["slug"], songs[0]["title"], songs[0]["artist"]) == ("OP1", title, [artist])
    assert songs[0]["versions"] == [{"version": 1, "episodes": "1-14"}]
    themes = state.metadata.file_metadata["1"]["themes"]
    assert set(themes) == {"OP1"}
    assert set(themes["OP1"]["1"]) == {"Example-OP1.webm", "byvisp.webm"}
    assert themes["OP1"]["1"]["byvisp.webm"]["anisongdb_alternate"] is True
    assert metadata_fetch.get_file_metadata_by_name(old_reference)["slug"] == "OP1"
    assert anisongdb.song_metadata(catalog["songs"][0])["artist"] == [artist]
    assert state.metadata.anisongdb_metadata == raw
    before = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == before


def test_old_projection_import_repairs_romanization_duplicates(romanized_duplicate):
    from _app_scripts.file.metadata import metadata_import

    catalog, title, artist, _wrong_slug = romanized_duplicate
    package = {
        "anisongdb_metadata": deepcopy(catalog),
        "anime_metadata": deepcopy(state.metadata.anime_metadata),
        "file_metadata": deepcopy(state.metadata.file_metadata),
    }
    state.metadata.anime_metadata_overrides["1"] = {
        "songs": [{"slug": "OP1", "composer": ["Personal composer"]}],
    }
    overrides = deepcopy(state.metadata.anime_metadata_overrides)
    metadata_import._apply_package_stores(package)
    songs = state.metadata.anime_metadata["1"]["songs"]
    assert [(song["slug"], song["title"], song["artist"]) for song in songs] == [("OP1", title, [artist])]
    assert anisongdb.registered_projection_version() == anisongdb.PROJECTION_VERSION
    assert state.metadata.anime_metadata_overrides == overrides


def test_old_projection_startup_repairs_romanization_and_retains_personal_credit(romanized_duplicate, monkeypatch):
    from _app_scripts.data import metadata_io
    from core.paths import ANISONGDB_METADATA_FILE, ANIME_METADATA_FILE, FILE_METADATA_FILE

    catalog, title, artist, _wrong_slug = romanized_duplicate
    saved = {FILE_METADATA_FILE: deepcopy(state.metadata.file_metadata),
             ANIME_METADATA_FILE: deepcopy(state.metadata.anime_metadata),
             ANISONGDB_METADATA_FILE: deepcopy(catalog)}
    monkeypatch.setattr(metadata_io, "load_metadata_compressed", lambda path, **kwargs: (deepcopy(saved.get(path)), True))
    monkeypatch.setattr(metadata_io.os.path, "exists", lambda path: False)
    monkeypatch.setattr(metadata_io, "load_theme_artist_resolutions", lambda: None)
    saved_calls = []
    monkeypatch.setattr(metadata_io, "save_metadata", lambda **kwargs: saved_calls.append(True))
    state.metadata.anime_metadata_overrides["1"] = {"songs": [{"slug": "OP1", "composer": ["Personal composer"]}]}
    metadata_io.load_metadata()
    assert saved_calls
    songs = state.metadata.anime_metadata["1"]["songs"]
    assert [(song["slug"], song["title"], song["artist"]) for song in songs] == [("OP1", title, [artist])]
    assert songs[0]["composer"] == ["Personal composer"]
    assert anisongdb.registered_projection_version() == anisongdb.PROJECTION_VERSION


def test_export_repairs_old_projection_before_saving(romanized_duplicate, monkeypatch):
    from _app_scripts.data import metadata_io, updates_io

    _catalog, title, artist, _wrong_slug = romanized_duplicate
    saved = []
    for method in ("save_metadata_overrides", "save_animethemes_metadata", "save_anisongdb_metadata"):
        monkeypatch.setattr(metadata_io, method, lambda: None)
    monkeypatch.setattr(metadata_io, "save_metadata", lambda **kwargs: saved.append(deepcopy(state.metadata.anime_metadata)))
    updates_io._persist_metadata_for_export()
    assert [(song["slug"], song["title"], song["artist"]) for song in saved[0]["1"]["songs"]] == [("OP1", title, [artist])]
    assert anisongdb.registered_projection_version() == anisongdb.PROJECTION_VERSION


def test_new_file_index_with_stale_song_rows_triggers_export_repair(romanized_duplicate, monkeypatch):
    from _app_scripts.data import metadata_io, updates_io

    _catalog, title, artist, _wrong_slug = romanized_duplicate
    old_anime = deepcopy(state.metadata.anime_metadata)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.registered_projection_version() == anisongdb.PROJECTION_VERSION
    state.metadata.anime_metadata.clear()
    state.metadata.anime_metadata.update(old_anime)
    assert anisongdb.registered_projection_version() < anisongdb.PROJECTION_VERSION
    for method in ("save_metadata_overrides", "save_animethemes_metadata", "save_anisongdb_metadata", "save_metadata"):
        monkeypatch.setattr(metadata_io, method, lambda **kwargs: None)
    updates_io._persist_metadata_for_export()
    songs = state.metadata.anime_metadata["1"]["songs"]
    assert [(song["slug"], song["title"], song["artist"]) for song in songs] == [("OP1", title, [artist])]
    assert anisongdb.registered_projection_version() == anisongdb.PROJECTION_VERSION


def test_duplicate_provider_rows_with_romanized_credit_remain_one_song(romanized_duplicate):
    catalog, title, artist, _wrong_slug = romanized_duplicate
    catalog = deepcopy(catalog)
    catalog["songs"].append({**catalog["songs"][0], "annSongId": 25, "amqSongId": 9596,
                             "songName": title, "songArtist": artist, "artists": [], "HQ": "second.webm"})
    anisongdb.replace_catalog(catalog)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=title, artists=[artist]) is not None
    anisongdb.sync_catalog_to_metadata()
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 1
    assert "byvisp.webm" in state.metadata.file_metadata["1"]["themes"]["OP1"]["1"]


@pytest.mark.parametrize(("established", "source"), [
    ("Shou Hayami", "Sho Hayami"),
    ("Shou Hayami", "Shō Hayami"),
    ("Yuuki Yoshida", "Yūki Yoshida"),
    ("Yuuki Yoshida", "Yuki Yosida"),
    ("Ryou Kunihiko", "Kunihiko Ryo"),
    ("Youko Takahashi", "Yohko Takahasi"),
    ("Kishida Kyoudan & The Akeboshi Rockets", "KISIDA KYODAN & THE AKEBOSI ROCKETS"),
])
def test_romanized_plain_text_artists_use_same_credit_on_other_anime(catalog_state, established, source):
    state.metadata.anime_metadata["established"] = {"songs": [{"slug": "ED1", "artist": [established]}]}
    catalog = _catalog()
    catalog["songs"][0].update({"songArtist": source, "artists": []})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert state.metadata.anime_metadata["1"]["songs"][0]["artist"] == [established]
    assert catalog["songs"][0]["songArtist"] == source


@pytest.mark.parametrize(("established", "source"), [
    ("Soul", "Sol"),
    ("Court", "Cort"),
    ("Artist One", "Artist Two"),
    ("Ryou Kunihiko", "Ryo Tanaka"),
    ("ば", "は"),
])
def test_same_title_different_performer_is_not_merged(catalog_state, established, source):
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": "Tank!", "artist": [established]}],
    }
    catalog = _catalog()
    catalog["songs"][0].update({"songArtist": source, "artists": []})
    anisongdb.replace_catalog(catalog)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title="Tank!", artists=[established]) is None
    anisongdb.sync_catalog_to_metadata()
    assert [(song["slug"], song["artist"]) for song in state.metadata.anime_metadata["1"]["songs"]] == [
        ("OP1", [established]), ("OP2", [source]),
    ]


def test_ambiguous_romanized_artist_is_not_guessed(catalog_state):
    state.metadata.anime_metadata["existing"] = {
        "songs": [{"slug": "OP1", "artist": ["Ryo Kunihiko"]},
                  {"slug": "OP2", "artist": ["Ryou Kunihiko"]}],
    }
    catalog = _catalog()
    catalog["songs"][0].update({"songArtist": "Ryō Kunihiko", "artists": []})
    anisongdb.replace_catalog(catalog)
    assert anisongdb.canonical_artist_name("Ryō Kunihiko") == "Ryō Kunihiko"
    assert anisongdb.canonical_artist_name("Ryo Kunihiko") == "Ryo Kunihiko"
    assert anisongdb.canonical_artist_name("Ryou Kunihiko") == "Ryou Kunihiko"


@pytest.mark.parametrize(("established", "source"), [
    ("YUKA", "YUUKA"), ("Mana", "Maana"), ("ANI", "Anii"),
    ("Natumi.", "Natsumi"), ("neko", "Neeko"), ("Miyuu", "MIYU"),
])
def test_distinct_provider_artist_ids_prevent_romanized_stage_name_merge(catalog_state, established, source):
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": "Tank!", "artist": [established]}],
    }
    catalog = _catalog()
    catalog["artists"].update({"18": {"names": [source]}, "20": {"names": [established]}})
    catalog["songs"][0]["songArtist"] = source
    anisongdb.replace_catalog(catalog)
    assert anisongdb.canonical_artist_name(source) == source
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title="Tank!", artists=[established]) is None
    anisongdb.sync_catalog_to_metadata()
    assert [(song["slug"], song["artist"]) for song in state.metadata.anime_metadata["1"]["songs"]] == [
        ("OP1", [established]), ("OP2", [source]),
    ]


def test_same_artist_id_allows_romanized_alias(catalog_state):
    state.metadata.anime_metadata["existing"] = {"songs": [{"slug": "OP1", "artist": ["Yuuki Yoshida"]}]}
    catalog = _catalog()
    catalog["artists"]["18"]["names"] = ["Yuki Yosida", "Yuuki Yoshida"]
    catalog["songs"][0]["songArtist"] = "Yuki Yosida"
    anisongdb.replace_catalog(catalog)
    assert anisongdb.song_metadata(catalog["songs"][0])["artist"] == ["Yuuki Yoshida"]


@pytest.mark.parametrize(("established", "source"), [("KOCHO", "Cho-ko"), ("JP", "P.J.")])
def test_name_order_matching_does_not_reverse_stage_names(catalog_state, established, source):
    state.metadata.anime_metadata["existing"] = {"songs": [{"slug": "OP1", "artist": [established]}]}
    catalog = _catalog()
    catalog["songs"][0].update({"songArtist": source, "artists": []})
    anisongdb.replace_catalog(catalog)
    assert anisongdb.canonical_artist_name(source) == source


@pytest.mark.parametrize("title", ["Tank! (acoustic)", "Tank! (live)", "Tank! (instrumental)", "Tank! TV version"])
def test_artist_romanization_does_not_hide_distinct_recordings(catalog_state, title):
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Ryou Kunihiko"]}],
    }
    catalog = _catalog()
    catalog["songs"][0].update({"songName": title, "songArtist": "Ryo Kunihiko", "artists": []})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    songs = state.metadata.anime_metadata["1"]["songs"]
    assert [(song["slug"], song["title"]) for song in songs] == [("OP1", "Tank!"), ("OP2", title)]
    assert songs[1]["artist"] == ["Ryou Kunihiko"]


@pytest.mark.parametrize(("title", "source_title", "source_artist", "matches"), [
    ("Main Theme (Seikai no Senki II Version)", "Main Theme (Seikai no Senki II ver.)", "Seatbelts", True),
    ("Tank! (Live Version)", "Tank! (live ver.)", "Seatbelts", True),
    ("Tank! TV version", "Tank! TV ver.", "Seatbelts", True),
    ("Tank! TV ver", "Tank! TV ver.", "Seatbelts", True),
    ("Tank! 2007 ver.", "Tank! 2007ver.", "Seatbelts", True),
    ("Tank! M870 ver.", "Tank! M870ver.", "Seatbelts", True),
    ("Tank! Ver. First 2", "Tank! Ver.First 2", "Seatbelts", True),
    ("Tank! Ver. 2", "Tank! Ver.2", "Seatbelts", True),
    ("Tank! M870 ver.", "Tank! M700ver.", "Seatbelts", False),
    ("Tank! Ver. 2", "Tank! Ver.3", "Seatbelts", False),
    ("Tank! Ver. First 2", "Tank! Ver.Starting 3", "Seatbelts", False),
    ("Tank! forever", "Tank! for eversion", "Seatbelts", False),
    ("Tank! (Instrumental Version)", "Tank! (Instrumental Ver.)", "Seatbelts", True),
    ("Tank! (Live Version)", "Tank! (acoustic ver.)", "Seatbelts", False),
    ("Tank! (English Version)", "Tank! (Japanese ver.)", "Seatbelts", False),
    ("Tank!", "Tank! (Live ver.)", "Seatbelts", False),
    ("Tank! (Live Version)", "Tank! (Live ver.)", "Another Singer", False),
    ("Main Theme (Seikai no Senki II Version)", "Main Theme (Seikai no Senki III ver.)", "Seatbelts", False),
])
def test_version_abbreviation_preserves_arrangement_work_and_performer(catalog_state, title, source_title, source_artist, matches):
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": title, "artist": ["Seatbelts"]}],
    }
    catalog = _catalog()
    catalog["songs"][0].update(songName=source_title, songArtist=source_artist, artists=[])
    anisongdb.replace_catalog(catalog)
    assert bool(anisongdb.resolve_song_for_mal_slug("1", "OP1", title=title, artists=["Seatbelts"])) == matches
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == (["OP1"] if matches else ["OP1", "OP2"])


@pytest.mark.parametrize("source_title", [
    "Level o Agete Butsuri de Naguru (acoustic)",
    "Level o Agete Butsuri de Naguru (live)",
    "Level o Agete Butsuri de Naguru (instrumental)",
    "Level o Agete Butsuri de Naguru TV version",
    "Level wa Agete Butsuri de Naguru",
])
def test_particle_matching_preserves_other_words_and_recording_qualifiers(catalog_state, source_title):
    title = "Level wo Agete Butsuri de Naguru"
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": title, "artist": ["Seatbelts"]}],
    }
    catalog = _catalog()
    catalog["songs"][0]["songName"] = source_title
    anisongdb.replace_catalog(catalog)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=title, artists=["Seatbelts"]) is None
    anisongdb.sync_catalog_to_metadata()
    assert [(song["slug"], song["title"]) for song in state.metadata.anime_metadata["1"]["songs"]] == [
        ("OP1", title), ("OP2", source_title),
    ]


def test_particle_matching_requires_same_performer(catalog_state):
    title = "Level wo Agete Butsuri de Naguru"
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": title, "artist": ["Different Performer"]}],
    }
    catalog = _catalog()
    catalog["songs"][0]["songName"] = "Level o Agete Butsuri de Naguru"
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1", "OP2"]


@pytest.mark.parametrize(("title", "source_title"), [("WO", "O"), ("Sword World", "Sord Orld")])
def test_particle_matching_does_not_rewrite_short_titles_or_parts_of_words(catalog_state, title, source_title):
    catalog = _catalog()
    catalog["songs"][0]["songName"] = source_title
    anisongdb.replace_catalog(catalog)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=title, artists=["Seatbelts"]) is None


@pytest.mark.parametrize(("title", "source_title"), [
    ("Seishun Kyousoukyoku", "Seishun Kyosokyoku"),
    ("Ryuusei", "Ryūsei"),
    ("Café Alpha", "Cafe Alpha"),
    ("Qué Será, Será", "Que sera sera"),
    ("Nijiiro Takaramono", "Niji-iro Takaramono"),
    ("Miiro", "Mi-iro"),
    ("Tomodachi Ijou x Teki Miman", "Tomodachi Ijou×Teki Miman"),
])
def test_title_spelling_variants_merge_into_established_slot(catalog_state, title, source_title):
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": title, "artist": ["Seatbelts"]}],
    }
    catalog = _catalog()
    catalog["songs"][0].update({"songName": source_title, "songNumber": 2})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [(song["slug"], song["title"]) for song in state.metadata.anime_metadata["1"]["songs"]] == [("OP1", title)]
    assert anisongdb.theme_slug(catalog["songs"][0]) == "OP1"


@pytest.mark.parametrize(("title", "source_title"), [
    ("Shine", "Sine"), ("Shion", "Sion"), ("WO", "O"),
    ("Ryusei", "Ryuusei (acoustic)"), ("Ryusei", "Ryuusei Remix"),
])
def test_title_normalization_retains_distinct_words_and_recordings(catalog_state, title, source_title):
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": title, "artist": ["Seatbelts"]}],
    }
    catalog = _catalog()
    catalog["songs"][0]["songName"] = source_title
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1", "OP2"]


def test_contextual_name_order_match_when_both_orders_are_established(catalog_state):
    state.metadata.anime_metadata["other"] = {"songs": [{"slug": "OP1", "artist": ["Shion Tsuji"]}]}
    state.metadata.anime_metadata["1"] = {
        "songs": [{"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Tsuji Shion"]}],
    }
    catalog = _catalog()
    catalog["songs"][0].update({"artists": [], "songArtist": "Shion Tsuji", "songNumber": 2})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1"]


@pytest.mark.parametrize("group_credit", [False, True])
def test_full_cast_roster_selects_duet_over_solo_despite_source_number(catalog_state, group_credit):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Artist A"]},
        {"type": "OP", "slug": "OP2", "title": "Tank!", "artist": ["Artist B", "Artist A"]},
    ]}
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Artist A"], "type": "person"},
        "21": {"names": ["Artist B"], "type": "person"},
        "22": {"names": ["The Duet"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[20, -1], [21, -1]]},
        ]},
    })
    catalog["songs"][0].update({"artists": [[22, 0]] if group_credit else [[20, -1], [21, -1]],
                               "songArtist": "The Duet" if group_credit else "Artist A & Artist B"})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(catalog["songs"][0]) == "OP2"
    assert anisongdb.resolve_song_for_mal_slug("1", "OP2", title="Tank!", artists=["Artist A", "Artist B"]) is catalog["songs"][0]
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 2


def test_group_roster_does_not_merge_with_subset_or_unknown_cast(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Artist A"]},
    ]}
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Artist A"]}, "21": {"names": ["Artist B"]},
        "22": {"names": ["The Duet"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[20, -1], [21, -1]]},
            {"line_up_type": "vocalists", "members": [[20, -1]]},
        ]},
    })
    catalog["songs"][0].update({"artists": [[22, 0]], "songArtist": "The Duet"})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1", "OP2"]
    catalog["songs"][0]["artists"] = [[22, -1]]
    assert not anisongdb._performer_rosters_match(catalog["songs"][0], ["Artist A", "Artist B"])


@pytest.mark.parametrize("slot", ["OP2-HD", "OP2-TV", "OP2-Sound"])
def test_qualified_slots_reuse_established_spelling_and_files(catalog_state, slot):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": slot, "title": "Tank!", "artist": ["Seatbelts"]},
    ]}
    state.metadata.file_metadata["1"] = {"mal": "1", "themes": {slot: {"1": {"Existing.webm": {"source": "BD"}}}}}
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == [slot]
    assert list(state.metadata.file_metadata["1"]["themes"]) == [slot]
    assert "byvisp.webm" in state.metadata.file_metadata["1"]["themes"][slot]["1"]
    assert anisongdb.resolve_song_for_mal_slug("1", slot, title="Tank!", artists=["Seatbelts"])


def test_standard_slot_wins_over_same_slot_clip_qualifier(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": slug, "title": "Tank!", "artist": ["Seatbelts"]}
        for slug in ("OP2", "OP2-HD")
    ]}
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(state.metadata.anisongdb_metadata["songs"][0]) == "OP2"
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 2


def test_qualified_dub_slot_does_not_claim_original_language_recording(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1-EN", "title": "Tank!", "artist": ["Seatbelts"]},
    ]}
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1-EN", title="Tank!", artists=["Seatbelts"]) is None
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 2


def test_titled_anchor_wins_over_unidentified_source_number_slot(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP2", "title": "Tank!", "artist": ["Seatbelts"]},
    ]}
    state.metadata.file_metadata["1"] = {"mal": "1", "themes": {"OP1": {"1": {"Unknown.webm": {"source": "BD"}}}}}
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(state.metadata.anisongdb_metadata["songs"][0]) == "OP2"
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 1


def _infermata_catalog():
    catalog = _catalog()
    catalog["anime"] = {"23706": {"animeENName": "Date A Bullet", "linked_ids": {"myanimelist": 40416}}}
    catalog["artists"] = {
        "8347": {"names": ["Spotlight Kids"], "type": "person"},
        "12932": {"names": ["Go Sakabe"], "type": "person"},
    }
    catalog["songs"][0].update({
        "annId": 23706, "annSongId": 31187, "amqSongId": 62982,
        "songName": "Infermata", "songArtist": "Spotlight Kids",
        "songCategory": "Instrumental", "songComposer": "Go Sakabe", "songArranger": "Go Sakabe",
        "artists": [[8347, -1]], "composers": [[12932, -1]], "arrangers": [[12932, -1]],
        "HQ": "vv165o.webm", "MQ": None,
    })
    return catalog


def test_unaccounted_credit_role_repairs_infermata_and_survives_reload(catalog_state):
    catalog = _infermata_catalog()
    original = deepcopy(catalog)
    source = catalog["songs"][0]
    anchor = {"type": "OP", "slug": "OP1", "title": "Infermata", "artist": ["Gou Sakabe"]}
    state.metadata.anime_metadata["40416"] = {
        "title": "Date A Bullet: Dead or Bullet", "anisongdb_projection_version": 9,
        "songs": [anchor, {**anisongdb.file_identity(source), "type": "OP", "slug": "OP2",
                           "title": "Infermata", "artist": ["Spotlight Kids"], "anisongdb_only": True}],
    }
    state.metadata.file_metadata["40416"] = {
        "mal": "40416", "anisongdb_projection_version": 9, "themes": {
            "OP1": {"1": {"DateABullet-OP1.webm": {"source": "BD", "resolution": 1080}}},
            "OP2": {"1": {"vv165o.webm": {**anisongdb.file_identity(source), "source": "ANISONGDB", "anisongdb_gap": True}}},
        },
    }
    anisongdb.replace_catalog(catalog)
    # Old saved numbering alone cannot legitimize conflicting credits.
    assert anisongdb.resolve_song_for_mal_slug("40416", "OP1", title="Infermata", artists=["Gou Sakabe"]) is None
    anisongdb.sync_catalog_to_metadata()
    songs = state.metadata.anime_metadata["40416"]["songs"]
    assert [(song["slug"], song["artist"]) for song in songs] == [("OP1", ["Gou Sakabe"])]
    assert songs[0]["composer"] == ["Go Sakabe"]
    props = state.metadata.file_metadata["40416"]["themes"]["OP1"]["1"]["vv165o.webm"]
    assert props["anisongdb_alternate"] is True
    assert props.get("anisongdb_gap") is None
    assert state.metadata.anisongdb_metadata == original
    assert not anisongdb._artist_names_match("Spotlight Kids", "Gou Sakabe")
    before = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == before
    anisongdb.build_indexes(force=True)
    assert anisongdb.theme_slug(source) == "OP1"
    assert anisongdb.resolve_song_for_mal_slug("40416", "OP1", title="Infermata", artists=["Gou Sakabe"]) is source
    assert anisongdb.resolve_song_for_mal_slug("40416", "OP1", title="Infermata", artists=["Unrelated Artist"]) is None
    state.metadata.file_metadata["40416"]["anisongdb_projection_version"] = 9
    assert anisongdb.resolve_song_for_mal_slug("40416", "OP1", title="Infermata", artists=["Gou Sakabe"]) is None


@pytest.mark.parametrize("role", ["composer", "arranger"])
def test_unaccounted_credit_role_is_general_and_handles_different_numbers(catalog_state, role):
    catalog = _catalog()
    catalog["songs"][0].update({"songNumber": 3, "songComposer": None, "songArranger": None,
                                "composers": [], "arrangers": []})
    catalog["songs"][0][role + "s"] = [[19, -1]]
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP2", "title": "Tank!", "artist": ["Yoko Kanno"]},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP2"]
    assert anisongdb.theme_slug(catalog["songs"][0]) == "OP2"
    assert anisongdb.resolve_song_for_mal_slug("1", "OP2", title="Tank!", artists=["Yoko Kanno"]) is catalog["songs"][0]


@pytest.fixture(params=["recording", "official_credit"])
def reviewed_recording(catalog_state, monkeypatch, request):
    catalog = _catalog()
    source = catalog["songs"][0]
    source.update({"songArtist": "Source Performer", "artists": [],
                   "songComposer": None, "songArranger": None, "composers": [], "arrangers": []})
    anchor = {"type": "OP", "slug": "OP1", "title": "Tank! (TV Cut)", "artist": ["Established Performer"]}
    state.metadata.anime_metadata["1"] = {"songs": [anchor]}
    state.metadata.file_metadata["1"] = {
        "themes": {"OP1": {"1": {"Example-OP1.webm": {"source": "BD", "resolution": 1080}}}},
    }
    kind = "recordings" if request.param == "recording" else "official_credits"
    record = {"ann_song_id": "24", "amq_song_id": "9595", "source_title": "Tank!",
              "source_artist": "Source Performer", "category": "Standard", "source_slug": "OP1",
              "source_video": "byvisp.webm", "slug": "OP1", "title": "Tank! (TV Cut)",
              "artist": ["Established Performer"], "native_file": "Example-OP1.webm",
              "reference": "https://example.com/official-theme-credit"}
    state.metadata.anime_metadata_overrides["1"] = {"anisongdb_matching": {kind: [record]}}
    anisongdb.replace_catalog(catalog)
    yield source, anchor


def test_reviewed_recording_repairs_conflicting_credits_and_label_without_artist_alias(reviewed_recording):
    source, anchor = reviewed_recording
    original = deepcopy(state.metadata.anisongdb_metadata)
    assert not anisongdb._matches_theme(source, anchor["title"], anchor["artist"])
    assert not anisongdb._artist_names_match(source["songArtist"], anchor["artist"][0])
    anisongdb.sync_catalog_to_metadata()
    assert [(song["slug"], song["title"], song["artist"]) for song in state.metadata.anime_metadata["1"]["songs"]] == [
        ("OP1", "Tank! (TV Cut)", ["Established Performer"]),
    ]
    files = state.metadata.file_metadata["1"]["themes"]["OP1"]["1"]
    assert files["byvisp.webm"]["anisongdb_alternate"] is True
    assert files["Example-OP1.webm"]["source"] == "BD"
    assert state.metadata.anisongdb_metadata == original
    before = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == before
    anisongdb.build_indexes(force=True)
    assert anisongdb.theme_slug(source) == "OP1"
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=anchor["artist"]) is source
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=["Unrelated Performer"]) is None
    state.metadata.anime_metadata["1"]["anisongdb_projection_version"] = anisongdb.PROJECTION_VERSION - 1
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=anchor["artist"]) is None


def test_reviewed_recording_can_use_a_later_established_cut_and_restore_its_slot(reviewed_recording):
    source, anchor = reviewed_recording
    themes = state.metadata.file_metadata["1"]["themes"]
    verified = themes["OP1"]["1"].pop("Example-OP1.webm")
    themes["OP1"]["1"]["Other-OP1.webm"] = {"source": "BD", "resolution": 1080}
    themes["OP1"]["2"] = {"Example-OP1.webm": verified}
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1"
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1"]
    anisongdb.build_indexes(force=True)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=anchor["artist"]) is source
    # A different verified filename cannot silently reuse the saved decision.
    themes["OP1"]["2"].clear()
    assert not anisongdb._reviewed_theme_match(source, anchor, "OP1")


def test_reviewed_media_repairs_partial_source_credit_on_a_complete_native_roster(reviewed_recording):
    source, anchor = reviewed_recording
    anchor["artist_complete_roster"] = True
    other = deepcopy(source)
    other.update({"annSongId": 25, "amqSongId": 9596, "songNumber": 2,
                  "songArtist": "Source Performer & Guest", "HQ": "duet00.webm", "MQ": None})
    state.metadata.anisongdb_metadata["songs"].append(other)
    anisongdb.build_indexes(force=True)
    assert not anisongdb._literal_performer_rosters_match(source, anchor["artist"])
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1"
    assert anisongdb.theme_slug(other) != "OP1"
    assert anchor["artist"] == ["Established Performer"]
    saved = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == saved
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=anchor["artist"]) is source
    source["HQ"] = "changed.webm"
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) != "OP1"
    assert anisongdb.theme_slug(other) != "OP1"


@pytest.mark.parametrize("changed", [
    "mal", "ann", "amq", "source_title", "source_credit", "source_guest", "category", "source_slot",
    "source_video", "missing_video", "target_title", "target_credit", "target_guest", "target_slot",
    "target_video", "target_video_source",
])
def test_reviewed_recording_requires_the_verified_usage_media_and_complete_credits(reviewed_recording, changed):
    source, anchor = reviewed_recording
    assert anisongdb._reviewed_theme_match(source, anchor, "OP1")
    if changed == "mal":
        state.metadata.anisongdb_metadata["anime"]["13"]["linked_ids"]["myanimelist"] = 2
    elif changed == "ann":
        source["annSongId"] = 25
    elif changed == "amq":
        source["amqSongId"] = 9596
    elif changed == "source_title":
        source["songName"] = "Tank! (acoustic)"
    elif changed in ("source_credit", "source_guest"):
        source["songArtist"] = "Other Performer" if changed == "source_credit" else "Source Performer feat. Guest"
    elif changed == "category":
        source["songCategory"] = "Cover"
    elif changed == "source_slot":
        source["songNumber"] = 2
    elif changed == "source_video":
        source["HQ"] = "other1.webm"
    elif changed == "missing_video":
        source.update({"HQ": None, "MQ": None})
    elif changed == "target_title":
        anchor["title"] = "Tank! (acoustic)"
    elif changed in ("target_credit", "target_guest"):
        anchor["artist"] = ["Other Performer"] if changed == "target_credit" else ["Established Performer", "Guest"]
    elif changed == "target_slot":
        anchor["slug"] = "OP2"
    elif changed == "target_video":
        state.metadata.file_metadata["1"]["themes"]["OP1"]["1"].clear()
    else:
        state.metadata.file_metadata["1"]["themes"]["OP1"]["1"]["Example-OP1.webm"]["source"] = "ANISONGDB"
    assert not anisongdb._reviewed_theme_match(source, anchor, anchor["slug"])
    anisongdb.sync_catalog_to_metadata()
    if changed == "mal":
        assert not state.metadata.anime_metadata["1"]["songs"][0].get("anisongdb_ann_song_id")
    else:
        assert anisongdb.theme_slug(source) != anchor["slug"]


def test_reviewed_recording_does_not_absorb_a_second_unverified_cover(reviewed_recording):
    source, anchor = reviewed_recording
    cover = {**deepcopy(source), "annSongId": 25, "amqSongId": 9596, "songNumber": 2,
             "HQ": "other1.webm", "MQ": None}
    state.metadata.anisongdb_metadata["songs"].append(cover)
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1"
    assert anisongdb.theme_slug(cover) == "OP2"
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=anchor["artist"]) is source


def test_verified_slot_wins_over_another_cast_with_matching_answer_credits(reviewed_recording):
    source, anchor = reviewed_recording
    other = {**deepcopy(source), "annSongId": 25, "amqSongId": 9596, "songNumber": 2,
             "songName": anchor["title"], "songArtist": "Established Performer",
             "artists": [{"id": 20, "names": ["Established Performer"], "type": "person"}],
             "HQ": "other1.webm", "MQ": None}
    state.metadata.anime_metadata["1"]["songs"].append({**deepcopy(anchor), "slug": "OP2"})
    state.metadata.anisongdb_metadata["songs"].append(other)
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1"
    assert anisongdb.theme_slug(other) == "OP2"
    anisongdb.build_indexes(force=True)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=anchor["artist"]) is source
    assert anisongdb.resolve_song_for_mal_slug("1", "OP2", title=anchor["title"], artists=anchor["artist"]) is other
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=["Unrelated Performer"]) is None


@pytest.mark.parametrize("discrepancy", ["version_label", "partial_cast"])
def test_reviewed_recording_resolves_when_another_provider_row_shares_its_slot(reviewed_recording, monkeypatch, discrepancy):
    source, anchor = reviewed_recording
    catalog = state.metadata.anisongdb_metadata
    catalog["artists"].update({
        "20": {"names": ["Established Performer"], "type": "person"},
        "21": {"names": ["Guest Performer"], "type": "person"},
    })
    other = {**deepcopy(source), "annSongId": 25, "amqSongId": 9596, "songNumber": 2,
             "songName": anchor["title"], "songArtist": "Established Performer", "artists": [[20, -1]],
             "HQ": "other1.webm", "MQ": None}
    if discrepancy == "version_label":
        source["songArtist"] = "Established Performer"
        source["artists"] = [[20, -1]]
        matching = state.metadata.anime_metadata_overrides["1"]["anisongdb_matching"]
        next(iter(matching.values()))[0]["source_artist"] = source["songArtist"]
    else:
        other["songArtist"] = "Established Performer & Guest Performer"
        other["artists"].append([21, -1])
    catalog["songs"].append(other)
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == anisongdb.theme_slug(other) == "OP1"
    anisongdb.build_indexes(force=True)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title=anchor["title"], artists=anchor["artist"]) is source


def test_unaccounted_pass_preserves_cover_when_original_matches_later_in_catalog(catalog_state):
    catalog = _catalog()
    cover = catalog["songs"][0]
    original = {**deepcopy(cover), "annSongId": 25, "amqSongId": 9596, "songNumber": 2,
                "songArtist": "Yoko Kanno", "artists": [[19, -1]], "HQ": "original.webm", "MQ": None}
    catalog["songs"].append(original)
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP2", "title": "Tank!", "artist": ["Yoko Kanno"]},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(original) == "OP2"
    assert anisongdb.theme_slug(cover) != "OP2"
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 2
    assert anisongdb.resolve_song_for_mal_slug("1", "OP2", title="Tank!", artists=["Yoko Kanno"]) is original


@pytest.mark.parametrize("conflict", ["two_sources", "two_anchors", "no_author", "recording_label", "other_type", "partial_authors"])
def test_unaccounted_pass_keeps_ambiguous_or_unsupported_recordings_separate(catalog_state, conflict):
    catalog = _catalog()
    source = catalog["songs"][0]
    anchor = {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Yoko Kanno"]}
    anchors = [anchor]
    if conflict == "two_sources":
        catalog["songs"].append({**deepcopy(source), "annSongId": 25, "amqSongId": 9596,
                                 "songNumber": 2, "songArtist": "Another Band", "artists": [],
                                 "songComposer": None, "songArranger": None, "composers": [], "arrangers": [],
                                 "HQ": "other.webm", "MQ": None})
    elif conflict == "two_anchors":
        anchors.append({**anchor, "slug": "OP2"})
    elif conflict == "no_author":
        source.update({"songComposer": None, "songArranger": None, "composers": [], "arrangers": []})
    elif conflict == "recording_label":
        source["songName"] = "Tank! (acoustic)"
    elif conflict == "other_type":
        source["songType"] = 2
    elif conflict == "partial_authors":
        anchor["artist"].append("Another Composer")
    state.metadata.anime_metadata["1"] = {"songs": anchors}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) not in {anchor["slug"] for anchor in anchors}
    assert any(song.get("anisongdb_only") for song in state.metadata.anime_metadata["1"]["songs"])


@pytest.mark.parametrize("source, target", [
    ("ROUND TABLE featuring Nino", "ROUND TABLE feat. Nino"),
    ("ROUND TABLE featuring Nino", "ROUND TABLE feat.Nino"),
    ("Dylan & Catherine", "Dylan and Catherine"),
    ("Yuuichi Ikuzawa", "Yuuichi Ikusawa"),
    ("Daiichi Uchuu Sokudo", "First Astronomical Velocity"),
])
def test_credit_spelling_rules_merge_known_collaboration_and_alias_variants(catalog_state, source, target):
    catalog = _catalog()
    catalog["artists"]["18"]["names"] = [source]
    catalog["songs"][0]["songArtist"] = source
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": [target]},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1"]


def test_known_literal_collaboration_matches_all_separately_credited_names(catalog_state):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["CHiCO"], "type": "person"},
        "21": {"names": ["HoneyWorks"], "type": "group"},
        "22": {"names": ["CHiCO with HoneyWorks"], "type": "group"},
        "23": {"names": ["Another Singer"], "type": "person"},
    })
    catalog["songs"][0].update({"songArtist": "CHiCO with HoneyWorks", "artists": [[22, -1]]})
    anisongdb.replace_catalog(catalog)
    assert anisongdb._performer_rosters_match(catalog["songs"][0], ["HoneyWorks", "CHiCO"])
    assert not anisongdb._performer_rosters_match(catalog["songs"][0], ["HoneyWorks"])
    catalog["songs"][0]["artists"].append([23, -1])
    assert not anisongdb._performer_rosters_match(catalog["songs"][0], ["HoneyWorks", "CHiCO"])


def test_full_credit_spelling_matches_when_provider_record_only_names_the_singer(catalog_state):
    catalog = _catalog()
    catalog["artists"]["700"] = {"names": ["Nino"], "type": "person"}
    source = catalog["songs"][0]
    source.update({"songArtist": "ROUND TABLE featuring Nino", "artists": [[700, -1]]})
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["ROUND TABLE feat.Nino"]},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1"
    assert not anisongdb._matches_theme(source, "Tank!", ["ROUND TABLE feat. Another Singer"])


def test_person_alias_roster_preserves_the_complete_credit_and_artist_ids(catalog_state):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Yoko Hikasa", "Hibiki from BEST FRIENDS!"], "type": "person"},
        "21": {"names": ["Another Singer"], "type": "person"},
    })
    source = catalog["songs"][0]
    source.update({"songArtist": "Hibiki from BEST FRIENDS!", "artists": [[20, -1]]})
    anisongdb.replace_catalog(catalog)
    assert anisongdb._performer_rosters_match(source, ["Youko Hikasa"])
    source["artists"].append([21, -1])
    assert not anisongdb._performer_rosters_match(source, ["Youko Hikasa"])
    assert anisongdb._performer_rosters_match(source, ["Another Singer", "Youko Hikasa"])
    state.metadata.anisongdb_metadata["artists"]["22"] = {"names": ["Youko Hikasa"], "type": "person"}
    anisongdb._artist_id_index = None
    assert not anisongdb._performer_rosters_match(source, ["Another Singer", "Youko Hikasa"])


@pytest.mark.parametrize("cast", ["selected", "unknown", "competing", "cycle"])
def test_nested_group_casts_require_known_members_without_competing_casts(catalog_state, cast):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Singer A"], "type": "person"},
        "21": {"names": ["Singer B"], "type": "person"},
        "23": {"names": ["Singer C"], "type": "person"},
        "24": {"names": ["Lead Singer"], "type": "person"},
        "22": {"names": ["Subgroup"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[20, -1], [21, -1]]},
            {"line_up_type": "vocalists", "members": [[23, -1]]},
        ]},
    })
    catalog["artists"]["18"].update({"line_ups": [
        {"line_up_type": "vocalists", "members": [[22, -1 if cast == "unknown" else 0], [24, -1]]},
    ]})
    if cast == "competing":
        catalog["artists"]["22"]["line_ups"][1]["members"] = [[20, -1]]
    if cast == "cycle":
        catalog["artists"]["22"]["line_ups"][0]["members"] = [[18, 0]]
    source = catalog["songs"][0]
    source["artists"] = [[18, 0]]
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Singer A"]},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == ("OP1" if cast == "selected" else "OP2")
    assert state.metadata.anisongdb_metadata == original


@pytest.mark.parametrize("cast", ["selected", "unknown", "competing", "cycle"])
@pytest.mark.parametrize("nested", [False, True])
def test_nested_cast_preserves_the_subgroup_credit_with_the_same_guards(catalog_state, cast, nested):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Singer A"], "type": "person"},
        "21": {"names": ["Singer B"], "type": "person"},
        "22": {"names": ["Subgroup"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[20, -1]]},
            {"line_up_type": "vocalists", "members": [[21, -1]]},
        ]},
    })
    catalog["artists"]["18"].update({"line_ups": [
        {"line_up_type": "vocalists", "members": [[22, -1 if cast == "unknown" else 0], [21, -1]]},
    ]})
    if nested:
        catalog["artists"]["23"] = {"names": ["Intermediate Group"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[22, -1 if cast == "unknown" else 0]]},
        ]}
        catalog["artists"]["18"]["line_ups"][0]["members"][0] = [23, 0]
    if cast == "competing":
        catalog["artists"]["18"]["line_ups"].append({"line_up_type": "vocalists", "members": [[22, 0]]})
    if cast == "cycle":
        catalog["artists"]["22"]["line_ups"][0]["members"] = [[18, 0]]
    source = catalog["songs"][0]
    source["artists"] = [[18, 0]]
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Subgroup"]},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == ("OP1" if cast == "selected" else "OP2")
    assert state.metadata.anisongdb_metadata == original


@pytest.mark.parametrize("missing_guest", [False, True])
def test_multiple_groups_must_each_be_represented_in_unaccounted_credit(catalog_state, missing_guest):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Singer A"], "type": "person"},
        "21": {"names": ["Singer B"], "type": "person"},
        "22": {"names": ["Singer C"], "type": "person"},
        "23": {"names": ["Singer D"], "type": "person"},
        "24": {"names": ["The Other Group"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[21, -1], [23, -1]]},
        ]},
        "25": {"names": ["Guest Singer"], "type": "person"},
    })
    catalog["artists"]["18"].update({"line_ups": [
        {"line_up_type": "vocalists", "members": [[20, -1], [22, -1]]},
    ]})
    source = catalog["songs"][0]
    source.update({"songArtist": "Seatbelts & The Other Group", "artists": [[18, 0], [24, 0]]})
    if missing_guest:
        source["artists"].append([25, -1])
        source["songArtist"] += " & Guest Singer"
    anisongdb.replace_catalog(catalog)
    assert bool(anisongdb._unaccounted_credit_evidence(source, ["Singer A", "Singer B"])) is not missing_guest
    assert not anisongdb._unaccounted_credit_evidence(source, ["Singer A"])


@pytest.mark.parametrize("guest", [False, True])
def test_explicit_group_credit_accounts_for_every_named_member(catalog_state, guest):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Singer A"], "type": "person", "groups": [[18, 0]]},
        "21": {"names": ["Singer B"], "type": "person", "groups": [[18, 0]]},
        "22": {"names": ["Guest Singer"], "type": "person"},
    })
    catalog["artists"]["18"].update({"line_ups": [
        {"line_up_type": "vocalists", "members": [[20, -1], [21, -1]]},
    ]})
    source = catalog["songs"][0]
    source.update({"songArtist": "Seatbelts:Singer A & Singer B", "artists": [[20, -1], [21, -1]]})
    if guest:
        source["artists"].append([22, -1])
        source["songArtist"] += " & Guest Singer"
    anisongdb.replace_catalog(catalog)
    assert bool(anisongdb._unaccounted_credit_evidence(source, ["Seatbelts"])) is not guest


@pytest.mark.parametrize("changed", ["none", "partial_fix", "name", "cast", "lineup"])
def test_reviewed_missing_members_require_the_observed_provider_group(catalog_state, changed):
    catalog = _catalog()
    known = (5026, 5358, 5566, 5631, 5671, 5672, 5678, 5781, 5966, 6096, 6101, 7057)
    for identifier in (*known, 5005, 5074):
        catalog["artists"][str(identifier)] = {"names": [f"Singer {identifier}"], "type": "person"}
    group = {"names": ["CINDERELLA PROJECT"], "type": "group", "line_ups": [
        {"line_up_type": "vocalists", "members": [[identifier, -1] for identifier in known]},
    ]}
    catalog["artists"]["6095"] = group
    selected = 0
    if changed == "partial_fix":
        group["line_ups"][0]["members"].append([5005, -1])
    elif changed == "name":
        group["names"] = ["Another Group"]
    elif changed == "cast":
        group["line_ups"][0]["members"].pop()
    elif changed == "lineup":
        group["line_ups"].append(deepcopy(group["line_ups"][0]))
        selected = 1
    source = catalog["songs"][0]
    source.update({"songArtist": group["names"][0], "artists": [[6095, selected]]})
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    evidence = anisongdb._unaccounted_credit_evidence(source, ["Singer 5005", "Singer 5074"])
    assert bool(evidence) == (changed in {"none", "partial_fix"})
    assert state.metadata.anisongdb_metadata == original


@pytest.mark.parametrize("unknown_cast", [False, True])
def test_unaccounted_group_members_match_partial_credits_only_with_known_cast(catalog_state, unknown_cast):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Artist A"], "type": "person"},
        "21": {"names": ["Artist B"], "type": "person"},
        "22": {"names": ["Artist C"], "type": "person"},
        "23": {"names": ["Artist D"], "type": "person"},
        "24": {"names": ["The Band"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[20, -1], [21, -1], [22, -1]]},
            {"line_up_type": "vocalists", "members": [[23, -1]]},
        ]},
    })
    source = catalog["songs"][0]
    source.update({"songArtist": "The Band", "artists": [[24, -1 if unknown_cast else 0]]})
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Artist A", "Artist B"]},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == ("OP2" if unknown_cast else "OP1")
    assert state.metadata.anisongdb_metadata == original
    if not unknown_cast:
        assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title="Tank!", artists=["Artist A", "Artist B"]) is source
        # No global alias between the group and an individual member.
        assert not anisongdb._artist_names_match("The Band", "Artist A")


@pytest.mark.parametrize("conflict", ["missing_membership", "bare_person_credit", "wrong_lineup"])
def test_explicit_group_member_credit_requires_provider_membership(catalog_state, conflict):
    catalog = _catalog()
    catalog["artists"].update({
        "20": {"names": ["Singer", "The Band:Singer"], "type": "person", "groups": [[21, 0]]},
        "21": {"names": ["The Band"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[20, -1]]},
        ]},
    })
    source = catalog["songs"][0]
    source.update({"songArtist": "The Band:Singer", "artists": [[20, -1]]})
    anisongdb.replace_catalog(catalog)
    assert anisongdb._unaccounted_credit_evidence(source, ["The Band"]) == ("credited_group_member",)
    if conflict == "missing_membership":
        state.metadata.anisongdb_metadata["artists"]["20"]["groups"] = []
    elif conflict == "bare_person_credit":
        source["songArtist"] = "Singer"
    elif conflict == "wrong_lineup":
        state.metadata.anisongdb_metadata["artists"]["21"]["line_ups"][0]["members"] = [[19, -1]]
    assert not anisongdb._unaccounted_credit_evidence(source, ["The Band"])


@pytest.mark.parametrize("artist_id, source_name, target", [
    (5827, "M\u30fbA\u30fbO", "Mao Ichimichi"),
    (7959, "satomiki", "Miki Satou"),
    (8112, "Akihito Hayashi", "Akito Hayashi"),
    (6558, "Runa Mizutani (NanosizeMir)", "Runa Mizutani"),
    (4599, "Anna (BON-BON BLANCO)", "Anna"),
    (7447, "sana (sajou no hana)", "sana"),
    (6852, "+\u03b1/Alfakyun.", "Alfakyun"),
    (2736, "Takayoshi Tanimoto", "Tanimoto Takeyoshi"),
    (2056, "Chika Nakayama", "Nakayama Chinatsu"),
    (357, "Yuka Sato", "Arika Sato"),
    (6917, "ohashiTrio", "Trio Oohashi"),
    (881, "U-ka saegusa", "Yuuka Saegusa"),
    (21689, "Hajime Chino", "\u3061\u306e\u306f\u3058\u3081"),
    (4000, "Super Flying Boy", "Chou Hikou Shounen"),
    (4941, "Hiroki Maekawa", "Hiroki"),
    (4611, "369", "Miroku"),
    (5098, "a flood of circle", "flood of circle"),
    (6793, "Hashiguchikanaderiya", "Kanaderiya Hashiguchi"),
    (6882, "Wa-suta", "Wa-suta iDOL Street"),
    (3445, "HOME MADE Kazoku", "HOME MADE \u5bb6\u65cf"),
    (18179, "Izumi Nakasone", "Ikumi Nakasone"),
    (6852, "+\u03b1/Alfakyun.", "\u03b1/Arukifakyun"),
    (5095, "Pokemon BW Gasshou-dan", "Pokemon BW Choral Gang"),
    (5781, "Mirai from BEST FRIENDS!", "Mirai"),
    (5996, "Karen from BEST FRIENDS!", "Karen"),
    (3834, "ANNA TSUCHIYA inspi' NANA(BLACK STONES)", "Tsuchiya, Anna inspi' Nana ~Black Stones~"),
    (9262, "Yuka Yashiro", "Ruka Yashiro"),
    (4334, "Ayumi Fujimura", "Ayumi Fujiwara"),
    (4664, "Haruna Yokota", "Yokota Haruno"),
    (1518, "Osamu Masaki", "Osami Masaki"),
    (6908, "Hino Shiritsu Nanaomidori Shougakkou Gasshou-dan", "Hino City Nanaomidori Elementary School Choir"),
    (1140, "Puchi Pri's", "Puchipurizu"),
    (19995, "Ichika Kato", "Icchi-"),
    (19994, "Kinjou Narumi", "Naruga"),
    (22936, "Kikokumaru Shounen Gasshou-dan", "Kikoukumaru's Man Chorus Group"),
    (3292, "Roppongi Dansei Gasshou-dan", "Roppongi Gasshoudan"),
    (6386, "RINKU (Mistera Feo)", "RINKU"),
    (6386, "RINK(Mistera Feo)", "RINK"),
    (8448, "Miya Kotuki", "Miya Kotsuki"),
    (1823, "Kouichi Kawazu", "Kouichi Kawatsu"),
    (6674, "Fujirokkyu (Kari)", "Fujirokyu"),
    (208, "Litz", "Rittsu"),
    (848, "Micchi to Chatterers", "Mitchi to Chataraz"),
    (1766, "Honey Knights", "Honey Nights"),
    (4561, "K\u039bN\u039b", "K\u2227N\u2227"),
    (3740, "Ryozy Mazda", "Matsuda Ryouji"),
    (7931, "Odawara Jousei Koukou Motemen-bu", "Odawara Jouboshi Koukou Motemen-bu"),
    (17207, "Sakuragaoka Shoubou-tai", "Sakuragaoka Shoboudan"),
    (8486, "Kojima Shokuhin Koujou Staff", "Kojima Food Factory Staff"),
    (84, "Kou Ikeda", "Ikeda"),
    (718, "Misae Takamatsu (Sakura Sakura)", "Misae Takamatsu"),
    (1988, "Hibari Jidou Gasshou-dan", "Hibari Children Chorus"),
    (10369, "Mana Kobayashi", "Mana"),
    (767, "Yoshiyuki Ohsawa", "Toshiyuki Ohsawa"),
    (21680, "Chiaki Sato", "Chiaki Satou"),
    (1847, "London Boots 1-go 2-go", "London Boots Ichi-go Ni-go"),
    (4248, "7!!", "Seven Oops"),
])
def test_reviewed_stage_identity_is_scoped_to_source_id_and_unaccounted_title(catalog_state, artist_id, source_name, target):
    catalog = _catalog()
    catalog["artists"][str(artist_id)] = {"names": [source_name], "type": "person"}
    catalog["songs"][0].update({"songArtist": source_name, "artists": [[artist_id, -1]]})
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": [target]},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1"]
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title="Tank!", artists=[target]) is catalog["songs"][0]
    assert state.metadata.anisongdb_metadata == original
    wrong = {**catalog["songs"][0], "artists": [{"id": artist_id + 1, "names": [source_name], "type": "person"}]}
    assert not anisongdb._unaccounted_credit_evidence(wrong, [target])
    changed_name = {**catalog["songs"][0], "artists": [{"id": artist_id, "names": ["Unrelated Singer"], "type": "person"}]}
    assert not anisongdb._unaccounted_credit_evidence(changed_name, [target])


def test_reviewed_stage_identity_cannot_swallow_an_accounted_same_name_cover(catalog_state):
    catalog = _catalog()
    catalog["artists"].update({
        "7959": {"names": ["satomiki"], "type": "person"},
        "21622": {"names": ["Miki Satou"], "type": "person", "disambiguation": "1980 Chewing Gum Company"},
    })
    modern = catalog["songs"][0]
    modern.update({"songArtist": "satomiki", "artists": [[7959, -1]]})
    older = {**deepcopy(modern), "annSongId": 25, "amqSongId": 9596, "songNumber": 2,
             "songArtist": "Miki Satou", "artists": [[21622, -1]], "HQ": "older.webm", "MQ": None}
    catalog["songs"].append(older)
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP2", "title": "Tank!", "artist": ["Miki Satou"]},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(older) == "OP2"
    assert anisongdb.theme_slug(modern) != "OP2"
    assert not anisongdb._artist_names_match("satomiki", "Miki Satou")


def test_character_alias_preserves_actor_credit_and_video_without_established_song_metadata(catalog_state):
    catalog = _catalog()
    catalog["artists"]["5996"] = {"names": ["Azusa Tadokoro", "Karen from BEST FRIENDS!"], "type": "person"}
    source = catalog["songs"][0]
    source.update({"songArtist": "Azusa Tadokoro", "artists": [[5996, -1]]})
    state.metadata.anime_metadata["1"] = {"songs": []}
    state.metadata.file_metadata["1"] = {"themes": {"OP1": {"1": {
        "Bebop-OP1.webm": {"source": "BD", "resolution": 1080},
    }}}}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert state.metadata.anime_metadata["1"]["songs"][0]["artist"] == ["Azusa Tadokoro"]
    assert "byvisp.webm" in state.metadata.file_metadata["1"]["themes"]["OP1"]["1"]
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title="Tank!", artists=["Azusa Tadokoro"]) is source
    before = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == before


@pytest.mark.parametrize("conflict", [None, "actor_id", "actor_name", "another_cast"])
def test_actor_reading_in_group_credit_requires_the_reviewed_member_and_cast(catalog_state, conflict):
    catalog = _catalog()
    names = ["Shiori Hanaoka", "Ami Mizuno", "Aina Rutou", "Yuka Yashiro"]
    for actor_id, name in zip(range(9259, 9263), names):
        catalog["artists"][str(actor_id)] = {"names": [name], "type": "person"}
    cast = [[identifier, -1] for identifier in range(9259, 9263)]
    catalog["artists"]["8395"] = {"names": ["Idolls!"], "type": "group", "line_ups": [
        {"line_up_type": "vocalists", "members": cast},
        {"line_up_type": "vocalists", "members": [[19, -1]]},
    ]}
    source = catalog["songs"][0]
    source.update({"songArtist": "Idolls!", "artists": [[8395, 0]]})
    if conflict == "actor_id":
        catalog["artists"]["9263"] = deepcopy(catalog["artists"]["9262"])
        cast[-1][0] = 9263
    elif conflict == "actor_name":
        catalog["artists"]["9262"]["names"] = ["Another Singer"]
    elif conflict == "another_cast":
        source["artists"][0][1] = 1
    performers = [*names[:3], "Ruka Yashiro"]
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": performers},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "OP1") is (conflict is None)
    assert state.metadata.anisongdb_metadata == original


@pytest.mark.parametrize("conflict", [None, "source_guest", "target_guest", "artist_id", "source_name", "duplicate_target"])
def test_reviewed_artist_spelling_in_collaboration_requires_every_performer(catalog_state, conflict):
    _title_alias_override("49778", 44996, "Senya Ichiya", "Senya Ichiya feat. Izumi Nakasone (HY)")
    catalog = _catalog()
    catalog["anime"]["13"]["linked_ids"]["myanimelist"] = 49778
    catalog["artists"].update({
        "6359": {"names": ["Hilcrhyme"], "type": "group"},
        "18179": {"names": ["Izumi Nakasone"], "type": "person"},
        "18180": {"names": ["Izumi Nakasone"], "type": "person"},
        "18181": {"names": ["Another Singer"], "type": "person"},
    })
    source = catalog["songs"][0]
    source.update({"annSongId": 44996, "songType": 2, "songName": "Senya Ichiya",
                   "songArtist": "Hilcrhyme feat. Izumi Nakasone", "artists": [[6359, -1], [18179, -1]]})
    artists = ["Hilcrhyme", "Ikumi Nakasone"]
    if conflict == "source_guest":
        source["artists"].append([18181, -1])
    elif conflict == "target_guest":
        artists.append("Another Singer")
    elif conflict == "artist_id":
        source["artists"][1][0] = 18180
    elif conflict == "source_name":
        catalog["artists"]["18179"]["names"] = ["Another Singer"]
    elif conflict == "duplicate_target":
        artists = ["Ikumi Nakasone", "Ikumi Nakasone"]
    title = "Senya Ichiya feat. Izumi Nakasone (HY)"
    state.metadata.anime_metadata["49778"] = {"songs": [
        {"type": "ED", "slug": "ED1", "title": title, "artist": artists},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "ED1") is (conflict is None)
    assert state.metadata.anisongdb_metadata == original
    if conflict is None:
        assert anisongdb.resolve_song_for_mal_slug("49778", "ED1", title=title, artists=artists) is source


@pytest.mark.parametrize("mal, song_id, title, target_title, performers", [
    ("58567", 44374, "ReawakeR", "ReawakeR (feat. Felix of Stray Kids)", ["LiSA", "Felix"]),
    ("58066", 44361, "Shujinkou ni Narou!", "Shujinkou ni Narou! feat. Airi Suzuki", ["Masayoshi Ooishi", "Airi Suzuki"]),
])
@pytest.mark.parametrize("conflict", [None, "song_id", "anime_id", "source_title", "missing_guest", "other_guest"])
def test_reviewed_feature_title_requires_matching_work_and_complete_guest_credits(catalog_state, mal, song_id, title, target_title, performers, conflict):
    _title_alias_override(mal, song_id, title, target_title)
    catalog = _catalog()
    catalog["anime"]["13"]["linked_ids"]["myanimelist"] = mal if conflict != "anime_id" else "2"
    catalog["artists"].update({
        "100": {"names": [performers[0]], "type": "person"},
        "101": {"names": [performers[1]], "type": "person"},
    })
    source = catalog["songs"][0]
    source.update({"annSongId": song_id + (conflict == "song_id"), "songName": title,
                   "songArtist": " feat. ".join(performers), "artists": [[100, -1], [101, -1]]})
    if conflict == "source_title":
        source["songName"] += " (acoustic)"
    target_artists = list(performers)
    if conflict == "missing_guest":
        target_artists.pop()
    elif conflict == "other_guest":
        target_artists[1] = "Another Singer"
    target_mal = mal if conflict != "anime_id" else "2"
    state.metadata.anime_metadata[target_mal] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": target_title, "artist": target_artists},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "OP1") is (conflict is None)
    assert state.metadata.anisongdb_metadata == original
    if conflict is None:
        assert anisongdb.resolve_song_for_mal_slug(mal, "OP1", title=target_title, artists=target_artists) is source


@pytest.mark.parametrize("mal, song_id, source_title, target_title, producer, vocalist, target_producer, target_vocalist, aliases", [
    ("50582", 40650, "Aim", "I'm", "Kujira Yumemi", "Tsumugi Shachi (from Kiminone)",
     "Kujira Yumemi", "Shachi Tsumugi", ["Tsumugi Shachi"]),
    ("35248", 16617, "Break The Doors", "Break The Doors feat. Aina The End (BiSH)",
     "TeddyLoid", "AiNA THE END (BiSH)", "TeddyLoid", "AiNA THE END", ["AiNA THE END"]),
    ("31157", 17800, "Yowa no Tsuki ~Fantaisie-Impromptu yori~", "Yowa no Tsuki ~From Fantaisie-Impromptu~",
     "EHAMIC", "galaco", "EHAMIC", "Galaco", []),
    ("31157", 17792, "Eine Kleine Yoru no Musik", "Ainekuraine Yoru no Music",
     "tofubeats", "Kana Hoshizaki", "tofubeat", "Kana Hoshizaki", []),
    ("35334", 19577, "Eine Kleine Yoru no Musik", "Ainekuraine Yoru no Music",
     "tofubeats", "Kana Hoshizaki", "tofubeat", "Kana Hoshizaki", []),
])
@pytest.mark.parametrize("conflict", [None, "missing_producer", "missing_vocalist", "source_guest", "target_guest", "unrepresented_record", "different_vocalist", "other_song", "other_version"])
def test_reviewed_title_preserves_literal_producer_and_vocalist_when_table_is_partial(
    catalog_state, mal, song_id, source_title, target_title, producer, vocalist,
    target_producer, target_vocalist, aliases, conflict,
):
    _title_alias_override(mal, song_id, source_title, target_title)
    catalog = _catalog()
    catalog["anime"]["13"]["linked_ids"]["myanimelist"] = mal
    catalog["artists"]["100"] = {"names": [vocalist, *aliases], "type": "person"}
    catalog["artists"]["101"] = {"names": ["Guest Singer"], "type": "person"}
    catalog["artists"]["102"] = {"names": [producer], "type": "person"}
    source = catalog["songs"][0]
    source.update({"annSongId": song_id, "songName": source_title,
                   "songArtist": producer + " feat. " + vocalist, "artists": [[100, -1]]})
    target_artists = [target_producer, target_vocalist]
    if conflict == "missing_producer":
        target_artists.pop(0)
        source["artists"].append([102, -1])
    elif conflict == "missing_vocalist":
        target_artists.pop()
    elif conflict == "source_guest":
        source["songArtist"] += " & Guest Singer"
    elif conflict == "target_guest":
        target_artists.append("Guest Singer")
    elif conflict == "unrepresented_record":
        source["artists"].append([101, -1])
    elif conflict == "different_vocalist":
        target_artists[-1] = "Guest Singer"
    elif conflict == "other_song":
        source["annSongId"] += 1
    elif conflict == "other_version":
        source["songName"] += " (acoustic)"
    state.metadata.anime_metadata[mal] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": target_title, "artist": target_artists},
    ]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "OP1") is (conflict is None)
    assert state.metadata.anisongdb_metadata == original
    if conflict is None:
        anisongdb.build_indexes(force=True)
        assert anisongdb.resolve_song_for_mal_slug(mal, "OP1", title=target_title, artists=target_artists) is source
        assert "byvisp.webm" in state.metadata.file_metadata[mal]["themes"]["OP1"]["1"]


@pytest.mark.parametrize("credit", ["Tom-H@ck featuring Masayoshi Oishi", "Tom-H@ck", "Masayoshi Oishi", "Tom-H@ck featuring Guest Singer"])
def test_original_oxt_billing_requires_the_complete_duo(catalog_state, credit):
    catalog = _catalog()
    catalog["artists"]["5822"] = {"names": ["Masayoshi Oishi"], "type": "person"}
    source = catalog["songs"][0]
    source.update({"songName": "Go EXCEED!!", "songArtist": credit, "artists": [[5822, -1]]})
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Go EXCEED!!", "artist": ["OxT"]},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "OP1") is (credit == "Tom-H@ck featuring Masayoshi Oishi")
    assert not anisongdb._artist_names_match("Masayoshi Oishi", "OxT")
    assert not anisongdb._artist_names_match("Tom-H@ck", "OxT")


@pytest.mark.parametrize("conflict", [None, "member_id", "other_cast", "extra_target"])
def test_mewkledreamy_duo_stage_names_require_identified_members(catalog_state, conflict):
    catalog = _catalog()
    catalog["artists"].update({
        "19994": {"names": ["Kinjou Narumi"], "type": "person"},
        "19995": {"names": ["Ichika Kato"], "type": "person"},
        "8492": {"names": ["Icchy & Naru"], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[19994, -1], [19995, -1]]},
            {"line_up_type": "vocalists", "members": [[19, -1]]},
        ]},
    })
    source = catalog["songs"][0]
    source.update({"songArtist": "Icchy & Naru", "artists": [[8492, 0]]})
    if conflict == "member_id":
        catalog["artists"]["19996"] = deepcopy(catalog["artists"]["19994"])
        catalog["artists"]["8492"]["line_ups"][0]["members"][0][0] = 19996
    elif conflict == "other_cast":
        source["artists"][0][1] = 1
    performers = ["Icchi-", "Naruga"] + (["Guest Singer"] if conflict == "extra_target" else [])
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": performers},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "OP1") is (conflict is None)


def _title_alias_override(mal, song_id, source_title, title):
    state.metadata.anime_metadata_overrides.setdefault(mal, {})["anisongdb_matching"] = {
        "title_aliases": [{"ann_song_id": str(song_id), "source_title": source_title, "title": title}],
    }


def _rude_lose_catalog():
    _title_alias_override("49618", 38542, "Rude Lose Dance", "Rude Loose Dance")
    catalog = _catalog()
    catalog["anime"]["13"]["linked_ids"]["myanimelist"] = 49618
    catalog["songs"][0].update({"annSongId": 38542, "songName": "Rude Lose Dance", "songArtist": "Minami", "artists": []})
    return catalog


def test_reviewed_title_alias_repairs_typo_and_keeps_raw_title(catalog_state):
    state.metadata.anime_metadata["49618"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Rude Loose Dance", "artist": ["Minami"]},
    ]}
    catalog = _rude_lose_catalog()
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["49618"]["songs"]] == ["OP1"]
    assert state.metadata.anisongdb_metadata == original


@pytest.mark.parametrize("conflict", [None, "song_id", "artist_id", "source_title", "target_guest"])
def test_reviewed_title_and_source_identity_reconcile_rewrite_with_both_guards(catalog_state, conflict):
    _title_alias_override("31716", 15494, "Sasayaka na Hajimari", "Sasayaki na Hajimari")
    catalog = _catalog()
    catalog["anime"]["13"]["linked_ids"]["myanimelist"] = 31716
    catalog["artists"]["6558"] = {"names": ["Runa Mizutani (NanosizeMir)"], "type": "person"}
    source = catalog["songs"][0]
    source.update({"annSongId": 15494, "songType": 2, "songName": "Sasayaka na Hajimari",
                   "songArtist": "Runa Mizutani (NanosizeMir)", "artists": [[6558, -1]],
                   "composers": [], "arrangers": [], "songComposer": None, "songArranger": None})
    target = {"type": "ED", "slug": "ED1", "title": "Sasayaki na Hajimari", "artist": ["Runa Mizutani"]}
    if conflict == "song_id":
        source["annSongId"] = 15495
    elif conflict == "artist_id":
        catalog["artists"]["6559"] = deepcopy(catalog["artists"]["6558"])
        source["artists"] = [[6559, -1]]
    elif conflict == "source_title":
        source["songName"] += " (acoustic)"
    elif conflict == "target_guest":
        target["artist"].append("Guest Performer")
    state.metadata.anime_metadata["31716"] = {"songs": [target]}
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == ("ED1" if conflict is None else "ED2")
    assert state.metadata.anisongdb_metadata == original
    if conflict is None:
        anisongdb.build_indexes(force=True)
        assert anisongdb.resolve_song_for_mal_slug("31716", "ED1", title=target["title"], artists=target["artist"]) is source


@pytest.mark.parametrize("conflict", ["anime", "song_id", "source_title", "target_title", "performers"])
def test_reviewed_title_alias_cannot_match_outside_reviewed_identity(catalog_state, conflict):
    mal, title, artists = "49618", "Rude Loose Dance", ["Minami"]
    catalog = _rude_lose_catalog()
    if conflict == "anime":
        mal = "1"
        catalog["anime"]["13"]["linked_ids"]["myanimelist"] = 1
    elif conflict == "song_id":
        catalog["songs"][0]["annSongId"] = 38543
    elif conflict == "source_title":
        catalog["songs"][0]["songName"] += " (live)"
    elif conflict == "target_title":
        title += " (acoustic)"
    elif conflict == "performers":
        # A shared singer is insufficient for a curated title exception.
        artists.append("Another Singer")
    state.metadata.anime_metadata[mal] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": title, "artist": artists},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata[mal]["songs"]] == ["OP1", "OP2"]


@pytest.mark.parametrize(("source", "established"), [
    ("RSP", "Real Street Project"), ("Rica Matsumoto", "Rika Matsumoto"),
    ("Alisa Mizuki", "Arisa Mizuki"), ("Tohoshinki", "TVXQ"),
    ("Daisy X Daisy", "Daisy\u00d7Daisy"),
    ("Daisy x Daisy", "Daisy\u00d7Daisy"),
    ("Daisy \u00d7 Daisy", "Daisy\u00d7Daisy"),
    ("Curriculu Machine feat.W.K. (Watanabe Kazuhiro)", "Curriculu Machine feat. W.K."),
    ("livetune adding Fukase(from SEKAI NO OWARI)", "livetune adding Fukase"),
    ("HARU & SAYAKA from UNIVERS★L D", "Haru & Sayaka from UNIVERSE★LD"),
    ("Shifo from UNIVERS★L D", "Shifo from UNIVERSE★LD"),
])
def test_reviewed_artist_aliases_merge_credits_without_changing_established_names(catalog_state, source, established):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": [established]},
    ]}
    catalog = _catalog()
    catalog["songs"][0].update({"songArtist": source, "artists": [], "songNumber": 2})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    songs = state.metadata.anime_metadata["1"]["songs"]
    assert [(song["slug"], song["artist"]) for song in songs] == [("OP1", [established])]
    assert anisongdb.song_metadata(catalog["songs"][0])["artist"] == [established]


@pytest.mark.parametrize("source", [
    "Daisy X Daisy", "Daisy x Daisy", "Daisy \u00d7 Daisy", "Daisy\u00d7Daisy",
])
def test_reviewed_daisy_aliases_resolve_without_catalog_credits(catalog_state, source):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Known theme", "artist": ["Daisy\u00d7Daisy"]},
    ]}

    assert anisongdb.canonical_artist_name(source) == "Daisy\u00d7Daisy"
    assert anisongdb.canonical_artist_name("DAISY CHAIN") == "DAISY CHAIN"


def test_known_artist_identity_conflict_overrides_reviewed_alias(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Rika Matsumoto"]},
    ]}
    catalog = _catalog()
    catalog["artists"].update({"18": {"names": ["Rica Matsumoto"]}, "20": {"names": ["Rika Matsumoto"]}})
    catalog["songs"][0]["songArtist"] = "Rica Matsumoto"
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1", "OP2"]


@pytest.mark.parametrize("record_type", ["person", "group"])
def test_provider_alias_identity_matches_person_or_band_stage_name(catalog_state, record_type):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Established Name"]},
    ]}
    catalog = _catalog()
    catalog["artists"]["18"] = {"names": ["Stage Name", "Established Name"], "type": record_type}
    catalog["songs"][0].update({"songArtist": "Stage Name", "songNumber": 2})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1"]


def test_unselected_group_feature_credit_cannot_match_another_cast(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["The Group featuring Singer B"]},
    ]}
    catalog = _catalog()
    catalog["artists"]["18"] = {"names": ["The Group", "The Group featuring Singer A", "The Group featuring Singer B"], "type": "group"}
    catalog["songs"][0].update({"songArtist": "The Group featuring Singer A", "songNumber": 2})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1", "OP2"]


def test_contextual_group_roster_accounts_for_all_other_credited_performers(catalog_state):
    catalog = _catalog()
    catalog["artists"].update({
        "18": {"names": ["The Group", "The Group featuring Singer A & Singer B"], "type": "group"},
        "20": {"names": ["Singer C"], "type": "person"},
    })
    catalog["songs"][0].update({"songArtist": "The Group featuring Singer A & Singer B, Singer C", "artists": [[18, -1], [20, -1]]})
    anisongdb.replace_catalog(catalog)
    assert anisongdb._performer_rosters_match(catalog["songs"][0], ["The Group", "Singer A", "Singer B", "Singer C"])
    assert not anisongdb._performer_rosters_match(catalog["songs"][0], ["The Group", "Singer A", "Singer B"])


def test_reload_restores_every_file_mapping_when_multiple_provider_rows_share_a_theme(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP2", "title": "Tank!", "artist": ["Seatbelts"]},
    ]}
    catalog = _catalog()
    catalog["songs"][0]["songNumber"] = 3
    catalog["songs"].append({**catalog["songs"][0], "annSongId": 25, "amqSongId": 9596, "songNumber": 4, "HQ": "second.webm", "MQ": None})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert [anisongdb.theme_slug(song) for song in catalog["songs"]] == ["OP2", "OP2"]
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 1
    # Rebuilding indexes reproduces a fresh process loading the saved stores.
    anisongdb.build_indexes(force=True)
    assert [anisongdb.theme_slug(song) for song in catalog["songs"]] == ["OP2", "OP2"]
    assert len(anisongdb.songs_for_mal_slug("1", "OP2")) == 2


def test_covered_theme_retains_every_distinct_provider_clip(catalog_state):
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP2", "title": "Tank!", "artist": ["Seatbelts"]},
    ]}
    state.metadata.file_metadata["1"] = {"themes": {"OP2": {"1": {
        "CowboyBebop-OP2.webm": {"source": "BD", "resolution": 1080},
    }}}}
    catalog = _catalog()
    catalog["songs"][0]["songNumber"] = 3
    catalog["songs"].append({**catalog["songs"][0], "annSongId": 25, "amqSongId": 9596, "songNumber": 4, "HQ": "second.webm", "MQ": None})
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    files = state.metadata.file_metadata["1"]["themes"]["OP2"]["1"]
    assert set(files) == {"CowboyBebop-OP2.webm", "byvisp.webm", "second.webm"}
    assert all(files[name]["anisongdb_alternate"] for name in ("byvisp.webm", "second.webm"))
    anisongdb.build_indexes(force=True)
    assert [anisongdb.theme_slug(song) for song in catalog["songs"]] == ["OP2", "OP2"]
    before = deepcopy(state.metadata.file_metadata)
    anisongdb.sync_catalog_to_metadata()
    assert state.metadata.file_metadata == before


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
    state.metadata.anime_metadata["another"] = {"anisongdb_projection_version": anisongdb.PROJECTION_VERSION}
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


@pytest.mark.parametrize("separator", [" & ", " with ", " to ", " feat. ", " adding "])
@pytest.mark.parametrize("conflict", [None, "missing_name", "extra_record", "unknown_cast", "competing_cast", "changed_title"])
def test_complete_written_unit_credit_keeps_every_name_and_rejects_cast_conflicts(catalog_state, separator, conflict):
    catalog = _catalog()
    names = ["Alpha Singer", "Beta Singer"]
    catalog["artists"].update({
        "90001": {"names": [names[0]], "type": "person"},
        "90002": {"names": [names[1]], "type": "person"},
        "90003": {"names": ["Other Singer"], "type": "person"},
        "90004": {"names": ["Another Singer"], "type": "person"},
        "90005": {"names": [separator.join(names)], "type": "group", "line_ups": [
            {"line_up_type": "vocalists", "members": [[90001, -1], [90002, -1]]},
        ]},
    })
    source = catalog["songs"][0]
    source.update({"songArtist": separator.join(names), "artists": [[90005, 0]]})
    if conflict == "missing_name":
        names = names[:1]
    elif conflict == "extra_record":
        source["artists"].append([90003, -1])
    elif conflict in ("unknown_cast", "competing_cast"):
        group = catalog["artists"]["90005"]
        group["line_ups"].append({"line_up_type": "vocalists", "members": [[90003, -1], [90004, -1]]})
        source["artists"][0][1] = -1 if conflict == "unknown_cast" else 1
    target = {"type": "OP", "slug": "OP1", "title": "Other Song" if conflict == "changed_title" else "Tank!", "artist": names}
    state.metadata.anime_metadata["1"] = {"songs": [target]}
    if conflict == "missing_name":
        # The solo recording already accounts for this slot. The complete
        # written duet must not replace it by matching only one member.
        solo = deepcopy(source)
        solo.update({"annSongId": 25, "amqSongId": 9596, "songArtist": names[0],
                     "artists": [[90001, -1]], "HQ": "solo.webm", "MQ": "solo-mq.webm"})
        catalog["songs"].append(solo)
    original = deepcopy(catalog)
    anisongdb.replace_catalog(catalog)
    assert anisongdb._matches_theme(source, target["title"], names) == (conflict is None)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "OP1") == (conflict is None)
    assert state.metadata.anisongdb_metadata == original


@pytest.mark.parametrize("guest", ["feat.", "ft.", "with", "adding"])
def test_complete_producer_credit_survives_vocalist_only_source_table(catalog_state, guest):
    catalog = _catalog()
    catalog["artists"]["90001"] = {"names": ["Named Vocalist"], "type": "person"}
    source = catalog["songs"][0]
    source.update({"songArtist": f"Named Producer {guest} Named Vocalist", "artists": [[90001, -1]]})
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Named Producer", "Named Vocalist"]},
    ]}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1"
    assert not anisongdb._literal_performer_rosters_match(source, ["Named Producer"])
    assert not anisongdb._literal_performer_rosters_match(source, ["Named Vocalist"])


@pytest.mark.parametrize("source, target, producer, guest", [
    ("Curriculu Machine feat.W.K. (Watanabe Kazuhiro)", "Curriculu Machine feat. W.K.", "Curriculu Machine", "W.K."),
    ("livetune adding Fukase(from SEKAI NO OWARI)", "livetune adding Fukase", "livetune", "Fukase"),
    ("HARU & SAYAKA from UNIVERS★L D", "Haru & Sayaka from UNIVERSE★LD", "HARU", "SAYAKA from UNIVERS★L D"),
])
def test_complete_collaboration_alias_never_drops_or_changes_a_guest(catalog_state, source, target, producer, guest):
    assert anisongdb._artist_names_match(source, target)
    for incomplete in (producer, guest, f"{producer} featuring Another Guest", f"{target} & Another Guest"):
        assert not anisongdb._artist_names_match(source, incomplete)


def test_official_credit_link_does_not_claim_strict_audio_proof_or_global_alias(reviewed_recording):
    source, anchor = reviewed_recording
    assert anisongdb._reviewed_recording_match(source, anchor, "OP1") == bool(list(anisongdb.iter_reviewed_matches("recordings")))
    assert anisongdb._reviewed_official_credit_match(source, anchor, "OP1") == bool(list(anisongdb.iter_reviewed_matches("official_credits")))
    assert not anisongdb._artist_names_match(source["songArtist"], anchor["artist"][0])


def test_published_matching_overrides_survive_import_reload_and_catalog_refresh(reviewed_recording):
    from _app_scripts.file.metadata import metadata_import

    source, anchor = reviewed_recording
    published = deepcopy(state.metadata.anime_metadata_overrides)
    state.metadata.anime_metadata_overrides["1"] = {"songs": [{"slug": "OP1", "composer": ["Personal Composer"]}]}
    personal = deepcopy(state.metadata.anime_metadata_overrides)
    metadata_import._apply_package_stores({"anime_metadata_overrides": published})
    assert anisongdb.theme_slug(source) == "OP1"
    assert state.metadata.anime_metadata_overrides == personal
    assert anchor["composer"] == ["Personal Composer"]
    saved = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == saved
    assert anisongdb._reviewed_theme_match(source, anchor, "OP1")


def test_matching_override_edits_take_effect_without_a_restart(reviewed_recording):
    source, anchor = reviewed_recording
    assert anisongdb._reviewed_theme_match(source, anchor, "OP1")
    state.metadata.anime_metadata_overrides["1"]["anisongdb_matching"] = {}
    assert not anisongdb._reviewed_theme_match(source, anchor, "OP1")


def test_artist_aliases_are_metadata_data_and_rebuild_after_override_edits(catalog_state):
    state.metadata.anime_metadata_overrides.clear()
    anisongdb.build_indexes(force=True)
    assert not anisongdb._artist_names_match("Stage credit", "Original artist")
    state.metadata.anime_metadata["1"] = {"anisongdb_matching": {
        "artist_aliases": [{"names": ["Stage credit", "Original artist"]}],
    }}
    anisongdb.build_indexes(force=True)
    assert anisongdb._artist_names_match("Stage credit", "Original artist")
    state.metadata.anime_metadata_overrides["1"] = {"anisongdb_matching": {"artist_aliases": []}}
    anisongdb.build_indexes(force=True)
    assert not anisongdb._artist_names_match("Stage credit", "Original artist")


def test_shared_artist_override_identity_has_personal_priority_and_cached_reads(catalog_state):
    state.metadata.anime_metadata_overrides.clear()
    state.metadata.anime_metadata["2"] = {"anisongdb_matching": {
        "source_artist_aliases": [{"artist_id": "18", "source_name": "Seatbelts", "names": ["Wrong credit"]}],
    }}
    state.metadata.anime_metadata_overrides["1"] = {"anisongdb_matching": {
        "source_artist_aliases": [{"artist_id": "18", "source_name": "Seatbelts", "names": ["Reviewed credit"]}],
    }}
    anisongdb.build_indexes(force=True)
    record = {"id": "18", "names": ["Seatbelts"]}
    assert anisongdb._source_artist_aliases(record) == ["Reviewed credit"]
    assert anisongdb._source_artist_aliases({**record, "id": "19"}) == []
    assert anisongdb._source_artist_aliases({**record, "names": ["Other band"]}) == []
    misses = anisongdb._reviewed_artist_data.cache_info().misses
    for _ in range(100):
        assert anisongdb._source_artist_aliases(record) == ["Reviewed credit"]
    assert anisongdb._reviewed_artist_data.cache_info().misses == misses


@pytest.mark.parametrize("records", [None, "bad", [None], [{}], [{"names": "bad"}], [{"names": ["One"]}], [{"names": ["One", None]}]])
def test_malformed_artist_override_data_is_ignored(catalog_state, records):
    state.metadata.anime_metadata_overrides["1"] = {"anisongdb_matching": {
        kind: records for kind in ("artist_aliases", "source_artist_aliases", "group_member_additions")
    }}
    anisongdb.build_indexes(force=True)
    assert all(not rows for rows in anisongdb._reviewed_artist_data().values())


def test_artist_alias_override_import_repairs_existing_metadata_and_preserves_personal_data(catalog_state):
    from _app_scripts.file.metadata import metadata_import

    state.metadata.anime_metadata_overrides.clear()
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Original artist"]},
    ]}
    state.metadata.file_metadata["1"] = {"themes": {"OP1": {"1": {"Example-OP1.webm": {"source": "BD"}}}}}
    source = state.metadata.anisongdb_metadata["songs"][0]
    source.update({"songArtist": "Stage credit", "artists": [], "songNumber": 2})
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 2
    personal = {"1": {"songs": [{"slug": "OP1", "composer": ["Personal composer"]}]}}
    state.metadata.anime_metadata_overrides.update(deepcopy(personal))
    metadata_import._apply_package_stores({"anime_metadata_overrides": {"1": {"anisongdb_matching": {
        "artist_aliases": [{"names": ["Stage credit", "Original artist"]}],
    }}}})
    assert anisongdb.theme_slug(source) == "OP1"
    assert len(state.metadata.anime_metadata["1"]["songs"]) == 1
    assert state.metadata.anime_metadata_overrides == personal
    saved = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.build_indexes(force=True)
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == saved


def test_incomplete_matching_override_is_ignored(reviewed_recording):
    source, anchor = reviewed_recording
    state.metadata.anime_metadata_overrides["1"]["anisongdb_matching"] = {"recordings": [{"ann_song_id": "24"}]}
    assert not anisongdb._reviewed_theme_match(source, anchor, "OP1")


@pytest.fixture
def reviewed_cast_repair(catalog_state, monkeypatch):
    catalog = _catalog()
    source = catalog["songs"][0]
    source.update({"songArtist": "Singer A", "artists": [], "songNumber": 2})
    anchor = {"type": "OP", "slug": "OP1", "title": "Tank!", "artist": ["Wrong Singer"]}
    state.metadata.anime_metadata["1"] = {"songs": [anchor]}
    state.metadata.file_metadata["1"] = {
        "themes": {"OP1": {"1": {"Example-OP1.webm": {"source": "BD", "resolution": 1080}}}},
    }
    state.metadata.anime_metadata_overrides["1"] = {"songs": [
        {"slug": "OP1", "artist": ["Singer A"], "artist_complete_roster": True},
    ]}
    for number, credit in ((1, "Singer A & Singer B & Singer C"), (3, "Singer A & Singer B")):
        other = deepcopy(source)
        other.update({"annSongId": 24 + number, "amqSongId": 9595 + number, "songNumber": number,
                      "songArtist": credit, "HQ": f"cast{number:02d}.webm", "MQ": None})
        catalog["songs"].append(other)
    anisongdb.replace_catalog(catalog)
    return source, anchor


@pytest.mark.parametrize("old_artists", [["Wrong Singer"], [], ["Singer A"]])
def test_native_credit_repair_keeps_solo_duet_and_trio_separate_and_survives_reload(reviewed_cast_repair, old_artists):
    source, anchor = reviewed_cast_repair
    anchor["artist"] = old_artists
    raw = deepcopy(state.metadata.anisongdb_metadata)
    anisongdb.sync_catalog_to_metadata()
    assert anchor["artist"] == ["Singer A"]
    assert anisongdb.theme_slug(source) == "OP1"
    rows = anisongdb.build_indexes()["mal"]["1"]
    assert len({anisongdb.theme_slug(song) for song in rows}) == 3
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1", title="Tank!", artists=["Singer A"]) is source
    assert state.metadata.anisongdb_metadata == raw
    first = deepcopy((state.metadata.anime_metadata, state.metadata.file_metadata))
    anisongdb.sync_catalog_to_metadata()
    assert (state.metadata.anime_metadata, state.metadata.file_metadata) == first
    anisongdb.build_indexes(force=True)
    assert anisongdb.theme_slug(source) == "OP1"
    assert len({anisongdb.theme_slug(song) for song in rows}) == 3


@pytest.mark.parametrize("override", [["Personal Singer"], ["Wrong Singer"], []])
def test_native_credit_repair_respects_explicit_artist_overrides(reviewed_cast_repair, override):
    _source, anchor = reviewed_cast_repair
    state.metadata.anime_metadata_overrides["1"] = {"songs": [{"slug": "OP1", "artist": override}]}
    anisongdb._apply_native_theme_overrides(anisongdb._existing_non_anisongdb_coverage())
    assert anchor["artist"] == override
    assert state.metadata.anime_metadata_overrides["1"]["songs"][0]["artist"] == override


def test_native_override_does_not_create_a_missing_established_theme(reviewed_cast_repair):
    _source, anchor = reviewed_cast_repair
    state.metadata.file_metadata["1"]["themes"]["OP1"]["1"].clear()
    before = deepcopy(anchor)
    anisongdb._apply_native_theme_overrides(anisongdb._existing_non_anisongdb_coverage())
    assert anchor == before


def test_corrected_override_retains_complete_cast_guard(reviewed_cast_repair):
    source, anchor = reviewed_cast_repair
    anchor["artist"] = ["Singer A"]
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1"
    assert len({anisongdb.theme_slug(song) for song in anisongdb.build_indexes()["mal"]["1"]}) == 3
    assert state.metadata.anime_metadata_overrides["1"]["songs"][0]["artist"] == ["Singer A"]


def test_bd_opening_matches_its_own_title_and_restores_qualified_slot(catalog_state):
    catalog = _catalog()
    source = catalog["songs"][0]
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP1", "title": "Different TV Song", "artist": ["Seatbelts"]},
        {"type": "OP", "slug": "OP1-BD", "title": "Tank!", "artist": ["Seatbelts"]},
    ]}
    state.metadata.file_metadata["1"] = {"themes": {
        "OP1": {"1": {"Example-OP1.webm": {"source": "WEB"}}},
        "OP1-BD": {"1": {"Example-OP1-BD.webm": {"source": "BD"}}},
    }}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert anisongdb.theme_slug(source) == "OP1-BD"
    assert "byvisp.webm" in state.metadata.file_metadata["1"]["themes"]["OP1-BD"]["1"]
    assert [song["slug"] for song in state.metadata.anime_metadata["1"]["songs"]] == ["OP1", "OP1-BD"]
    anisongdb.build_indexes(force=True)
    assert anisongdb.resolve_song_for_mal_slug("1", "OP1-BD", title="Tank!", artists=["Seatbelts"]) is source


@pytest.mark.parametrize("shared_native", [True, False])
def test_tv_and_bd_numbers_share_standard_slot_only_with_same_native_video(catalog_state, shared_native):
    catalog = _catalog()
    source = catalog["songs"][0]
    source["songNumber"] = 6
    state.metadata.anime_metadata["1"] = {"songs": [
        {"type": "OP", "slug": "OP4", "title": "Tank!", "artist": ["Seatbelts"]},
        {"type": "OP", "slug": "OP6-BD", "title": "Tank!", "artist": ["Seatbelts"]},
    ]}
    state.metadata.file_metadata["1"] = {"themes": {
        "OP4": {"1": {"Example-OP6.webm": {"source": "BD"}}},
        "OP6-BD": {"1": {("Example-OP6.webm" if shared_native else "Different-OP6.webm"): {"source": "BD"}}},
    }}
    anisongdb.replace_catalog(catalog)
    anisongdb.sync_catalog_to_metadata()
    assert (anisongdb.theme_slug(source) == "OP4") is shared_native
    anisongdb.build_indexes(force=True)
    assert (anisongdb.theme_slug(source) == "OP4") is shared_native
