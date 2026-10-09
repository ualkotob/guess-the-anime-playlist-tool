"""Tests for the self-bootstrapping AnimeThemes catalog provider."""

from __future__ import annotations

import copy

import pytest

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch
from _app_scripts.playback import cache_download
from _app_scripts.playlists import playlist
from _app_scripts.playlists import entry_paths
from _app_scripts.theme import animethemes
from _app_scripts.ui import menu_registry


def _anime(anime_id=1, *, mal_id="1", basename="Example-OP1.webm"):
    resources = [
        {
            "site": "AniList",
            "external_id": 101,
            "link": "https://anilist.co/anime/101",
        }
    ]
    if mal_id is not None:
        resources.insert(
            0,
            {
                "site": "MyAnimeList",
                "external_id": int(mal_id),
                "link": f"https://myanimelist.net/anime/{mal_id}",
            },
        )
    return {
        "id": anime_id,
        "name": "Example Anime",
        "slug": "example_anime",
        "year": 2024,
        "season": "Spring",
        "media_format": "TV",
        "synopsis": "An example.",
        "resources": resources,
        "series": [{"name": "Example Series"}],
        "studios": [{"name": "Example Studio"}],
        "images": [{"facet": "Large Cover", "link": "https://img/cover.jpg"}],
        "animethemes": [
            {
                "id": 11,
                "type": "OP",
                "slug": "OP1",
                "sequence": 1,
                "song": {
                    "title": "Example Song",
                    "artists": [{"name": "Example Artist"}],
                },
                "animethemeentries": [
                    {
                        "id": 21,
                        "version": 1,
                        "episodes": "1-12",
                        "spoiler": False,
                        "nsfw": False,
                        "videos": [
                            {
                                "id": 31,
                                "basename": basename,
                                "path": f"2024/Spring/{basename}",
                                "lyrics": False,
                                "nc": True,
                                "overlap": "None",
                                "resolution": 1080,
                                "size": 1234,
                                "source": "BD",
                                "subbed": False,
                                "uncen": False,
                                "tags": "NCBD1080",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _catalog(*anime):
    return {"anime": list(anime), "fetched_at": 1, "projection_version": 0}


@pytest.fixture(autouse=True)
def isolated_metadata(monkeypatch):
    stores = (
        "file_metadata",
        "anime_metadata",
        "animethemes_metadata",
        "anisongdb_metadata",
        "anidb_metadata",
        "anilist_metadata",
        "anime_metadata_overrides",
        "theme_artist_resolutions",
        "directory_files",
    )
    saved = {
        name: copy.deepcopy(getattr(state.metadata, name))
        for name in stores
    }
    saved_animethemes_cache = copy.deepcopy(metadata_fetch.animethemes_cache)
    for name in stores:
        getattr(state.metadata, name).clear()
    metadata_fetch.animethemes_cache.clear()
    metadata_fetch.build_filename_to_mal_map()
    metadata_fetch.invalidate_metadata_cache()
    monkeypatch.setattr(metadata_fetch.metadata_io, "save_animethemes_metadata", lambda: None)
    yield
    for name, value in saved.items():
        target = getattr(state.metadata, name)
        target.clear()
        target.update(value)
    metadata_fetch.animethemes_cache.clear()
    metadata_fetch.animethemes_cache.update(saved_animethemes_cache)
    animethemes.build_indexes(force=True)
    metadata_fetch.build_filename_to_mal_map()
    metadata_fetch.invalidate_metadata_cache()


class _Response:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


def test_fetch_catalog_follows_pagination_and_requests_full_relationships():
    first = _anime(basename="First-OP1.webm")
    second = _anime(anime_id=2, mal_id="2", basename="Second-ED1.webm")
    session = _Session(
        [
            _Response({"anime": [first], "links": {"next": "next"}}),
            _Response({"anime": [second], "links": {"next": None}}),
        ]
    )

    result = animethemes.fetch_catalog(
        request_session=session,
        sleep_func=lambda _seconds: None,
    )

    assert result["anime"] == [first, second]
    assert len(session.calls) == 2
    assert session.calls[0][1]["params"]["page[size]"] == 100
    assert session.calls[1][1]["params"]["page[number]"] == 2
    assert "animethemes.animethemeentries.videos" in session.calls[0][1]["params"]["include"]
    assert "animethemes.song.artists" in session.calls[0][1]["params"]["include"]


def test_fetch_failure_does_not_replace_existing_catalog():
    state.metadata.animethemes_metadata.update(_catalog(_anime()))
    previous = copy.deepcopy(state.metadata.animethemes_metadata)
    session = _Session([_Response({"unexpected": []})])

    with pytest.raises(ValueError):
        animethemes.fetch_catalog(request_session=session)

    assert state.metadata.animethemes_metadata == previous


def test_blank_state_projection_creates_browsable_streaming_catalog():
    animethemes.replace_catalog(
        _catalog(
            _anime(),
            _anime(
                anime_id=2,
                mal_id=None,
                basename="NoMalAnime-ED1.webm",
            ),
        )
    )

    assert animethemes.sync_catalog_to_metadata() == 2
    assert state.metadata.file_metadata["1"]["anilist"] == "101"
    assert state.metadata.file_metadata["1"]["animethemes_slug"] == "example_anime"
    assert "ANIMETHEMES:2" in state.metadata.file_metadata
    assert state.metadata.anime_metadata["1"]["title"] == "Example Anime"
    assert state.metadata.anime_metadata["1"]["aired"] is None
    assert state.metadata.anime_metadata["1"]["season"] == "Spring 2024"
    assert state.metadata.anime_metadata["1"]["studios"] == ["Example Studio"]
    assert state.metadata.anime_metadata["1"]["songs"][0]["artist"] == [
        "Example Artist"
    ]

    remote_files = playlist.get_directory_files(include_non_local=True)
    assert "Example-OP1.webm" in remote_files
    assert "NoMalAnime-ED1.webm" in remote_files
    assert playlist.get_directory_files(include_non_local=False) == []
    assert cache_download.is_remote_theme_file("Example-OP1.webm") is True


def test_catalog_owned_anime_is_queued_for_missing_mal_metadata():
    animethemes.replace_catalog(_catalog(_anime()))
    animethemes.sync_catalog_to_metadata()

    targets = metadata_fetch._collect_missing_metadata_targets()

    assert [item[0] for item in targets["mal"]] == ["1"]


def test_successful_mal_fetch_completes_catalog_owned_anime(monkeypatch):
    animethemes.replace_catalog(_catalog(_anime()))
    animethemes.sync_catalog_to_metadata()
    anime_data = state.metadata.anime_metadata["1"]
    monkeypatch.setattr(
        metadata_fetch,
        "fetch_tenrai_metadata",
        lambda _mal_id: {
            "title": "Example Anime",
            "title_english": "Example Anime",
            "title_synonyms": [],
            "aired": {"string": "Apr 1, 2024 to Jun 17, 2024"},
            "season": "spring",
            "year": 2024,
            "score": 7.5,
            "rank": 1000,
            "members": 100000,
            "popularity": 2000,
            "type": "TV",
            "source": "Original",
            "episodes": 12,
            "studios": [{"name": "Example Studio"}],
            "genres": [{"name": "Action"}],
            "themes": [],
            "demographics": [],
            "synopsis": "Enriched synopsis.",
            "images": {"jpg": {"large_image_url": "https://img/mal.jpg"}},
            "trailer": {},
        },
    )
    monkeypatch.setattr(metadata_fetch.metadata_io, "save_metadata", lambda: None)

    metadata_fetch.refresh_tenrai_data("1", anime_data)

    assert animethemes.CATALOG_OWNED_MARKER not in anime_data
    assert metadata_fetch._mal_metadata_missing(anime_data) is False
    assert metadata_fetch._collect_missing_metadata_targets()["mal"] == []


def test_refresh_replaces_catalog_rows_but_preserves_local_and_rich_metadata():
    state.metadata.directory_files["Local-OP9-[MAL]1.webm"] = "themes/local.webm"
    state.metadata.file_metadata["1"] = {
        "name": "Rich Anime",
        "themes": {
            "OP9": {
                "null": {
                    "Local-OP9-[MAL]1.webm": {"source": "LOCAL"},
                }
            },
            "OP1": {
                "1": {
                    "Stale-OP1.webm": {
                        "source": "BD",
                        animethemes.CATALOG_MARKER: True,
                    }
                }
            },
        },
    }
    state.metadata.anime_metadata["1"] = {
        "title": "Rich Anime",
        "score": 9.5,
        "genres": ["Action"],
        "songs": [],
    }
    animethemes.replace_catalog(_catalog(_anime()))

    animethemes.sync_catalog_to_metadata()

    entry = state.metadata.file_metadata["1"]
    assert "Local-OP9-[MAL]1.webm" in entry["themes"]["OP9"]["null"]
    assert "Stale-OP1.webm" not in entry["themes"]["OP1"]["1"]
    assert "Example-OP1.webm" in entry["themes"]["OP1"]["1"]
    assert state.metadata.anime_metadata["1"]["title"] == "Rich Anime"
    assert state.metadata.anime_metadata["1"]["score"] == 9.5
    assert state.metadata.anime_metadata["1"]["genres"] == ["Action"]


def test_refresh_does_not_erase_curated_artist_missing_from_catalog():
    state.metadata.anime_metadata["1"] = {
        "title": "Rich Anime",
        "songs": [
            {
                "slug": "OP1",
                "title": "Curated Song",
                "artist": ["Curated Artist"],
            }
        ],
    }
    anime = _anime()
    anime["animethemes"][0]["song"]["title"] = None
    anime["animethemes"][0]["song"]["artists"] = []
    animethemes.replace_catalog(_catalog(anime))

    animethemes.sync_catalog_to_metadata()

    song = state.metadata.anime_metadata["1"]["songs"][0]
    assert song["title"] == "Curated Song"
    assert song["artist"] == ["Curated Artist"]


def test_retained_catalog_serves_existing_per_file_lookup_without_http(monkeypatch):
    anime = _anime()
    animethemes.replace_catalog(_catalog(anime))
    monkeypatch.setattr(
        metadata_fetch.requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("unexpected HTTP request"),
    )

    assert metadata_fetch.fetch_animethemes_metadata("Example-OP1.webm") is anime
    assert metadata_fetch.fetch_animethemes_metadata(mal_id="1") is anime


@pytest.mark.parametrize(
    ("lookup", "expected_filter", "expected_value"),
    [
        (
            {"filename": "Example-OP1.webm"},
            "filter[video][basename-like]",
            "Example-%",
        ),
        (
            {"mal_id": "1"},
            "filter[resource][external_id]",
            "1",
        ),
    ],
)
def test_refetch_bypasses_retained_catalog_and_requests_live_data(
    monkeypatch,
    lookup,
    expected_filter,
    expected_value,
):
    stale_anime = _anime()
    fresh_anime = _anime()
    fresh_anime["name"] = "Fresh Anime"
    animethemes.replace_catalog(_catalog(stale_anime))
    metadata_fetch.animethemes_cache[
        metadata_fetch._animethemes_cache_key("Example-OP1.webm", split=True)
    ] = stale_anime
    calls = []

    def fake_get(_url, params):
        calls.append(params)
        return _Response({"anime": [fresh_anime]})

    monkeypatch.setattr(metadata_fetch.requests, "get", fake_get)

    assert (
        metadata_fetch.fetch_animethemes_metadata(**lookup, refetch=True)
        is fresh_anime
    )
    assert len(calls) == 1
    assert calls[0][expected_filter] == expected_value


def test_stale_prefix_catalog_does_not_block_exact_live_lookup(monkeypatch):
    stale_anime = _anime(basename="Example-OP1.webm")
    newer_anime = _anime(basename="Example-OP2.webm")
    animethemes.replace_catalog(_catalog(stale_anime))
    calls = []

    def fake_get(_url, params):
        calls.append(params)
        return _Response({"anime": [newer_anime]})

    monkeypatch.setattr(metadata_fetch.requests, "get", fake_get)

    # The fast prefix lookup may identify the anime from the retained catalog,
    # but an exact fallback must still be able to discover a newly added video.
    assert (
        metadata_fetch.fetch_animethemes_metadata("Example-OP2.webm")
        is stale_anime
    )
    assert (
        metadata_fetch.fetch_animethemes_metadata(
            "Example-OP2.webm",
            split=False,
        )
        is newer_anime
    )
    assert (
        metadata_fetch.fetch_animethemes_metadata(
            "Example-OP2.webm",
            split=False,
        )
        is newer_anime
    )
    assert len(calls) == 1
    assert (
        calls[0]["filter[video][basename-like]"]
        == "Example-OP2.webm"
    )


@pytest.mark.parametrize("action", ["playing_reference", "playing_data", "playlist", "default_fetch", "playing_dictionary", "playlist_dictionary", "default_dictionary"])
def test_refetch_actions_preserve_shared_theme_identity(monkeypatch, action):
    filename = "ElfenLied-OP1.webm"
    reference = entry_paths.make_theme_reference(filename, "376", "OP1", "1")
    playlist_entry = {"filename": reference} if action.endswith("dictionary") else reference
    monkeypatch.setattr(state.metadata, "playlist", {"playlist": [playlist_entry], "current_index": 0})
    playing = {}
    if action.startswith("playing_"):
        playing = {
            "type": "theme",
            "filename": filename,
            "playlist_entry": playlist_entry if action in ("playing_reference", "playing_dictionary") else filename,
            "data": {"mal": "376", "slug": "OP1", "version": "1"},
        }
    monkeypatch.setattr(state.playback, "currently_playing", playing)
    calls = []
    monkeypatch.setattr(
        metadata_fetch, "_fetch_metadata_impl",
        lambda *args: calls.append(args),
    )

    if action.startswith("default_"):
        metadata_fetch.fetch_metadata()
    else:
        metadata_fetch.refetch_metadata()

    assert calls == [(reference, True, "", False)]


def _shared_anime(anime_id, mal_id, *, nsfw=False):
    anime = _anime(anime_id, mal_id=mal_id, basename="ElfenLied-OP1.webm")
    anime["name"] = "Elfen Lied" if mal_id == "226" else "Elfen Lied Special"
    anime["slug"] = "elfen_lied" if mal_id == "226" else "elfen_lied_special"
    anime["series"] = [{"name": "Elfen Lied"}]
    opening = anime["animethemes"][0]
    opening["song"]["title"] = "LILIUM"
    opening["animethemeentries"][0]["nsfw"] = nsfw
    ending = copy.deepcopy(opening)
    ending.update({"type": "ED", "slug": "ED1"})
    ending["song"]["title"] = "be your girl"
    ending["animethemeentries"][0]["videos"][0]["basename"] = "ElfenLied-ED1.webm"
    anime["animethemes"].append(ending)
    return anime


@pytest.mark.parametrize("filename", ["ElfenLied-OP1.webm", "ElfenLied-ED1.webm", "ElfenLied-OP1.mp4"])
@pytest.mark.parametrize("current_mal", ["376", "226"])
def test_shared_theme_refetch_updates_special_flags_and_keeps_current_anime(monkeypatch, filename, current_mal):
    main = _shared_anime(704, "226")
    stale_special = _shared_anime(4957, "376")
    fresh_special = _shared_anime(4957, "376", nsfw=True)
    # Live per-file responses do not include studios; keep the catalog copy.
    fresh_special.pop("studios")
    animethemes.replace_catalog(_catalog(main, stale_special))
    animethemes.sync_catalog_to_metadata()
    slug = "ED1" if "-ED" in filename else "OP1"
    reference = entry_paths.make_theme_reference(filename, "376", slug, "1")
    assert metadata_fetch.get_metadata(reference)["songs"][0]["nsfw"] is False
    current_reference = entry_paths.make_theme_reference(filename, current_mal, slug, "1")
    playing = {"type": "theme", "filename": filename, "playlist_entry": current_reference, "data": {"mal": current_mal}}
    monkeypatch.setattr(state.playback, "currently_playing", playing)
    monkeypatch.setattr(state.metadata, "playlist", {"playlist": [reference], "current_index": 0})
    calls = []

    def fake_get(_url, params):
        calls.append(params)
        # A filename-only lookup would return the main series first.
        rows = [fresh_special] if params.get("filter[resource][external_id]") == "376" else [main, fresh_special]
        return _Response({"anime": rows})

    monkeypatch.setattr(metadata_fetch.requests, "get", fake_get)
    monkeypatch.setattr(metadata_fetch, "fetch_tenrai_metadata", lambda _mal_id: None)
    monkeypatch.setattr(metadata_fetch, "fetch_anilist_metadata", lambda **_kwargs: (None, None))
    monkeypatch.setattr(metadata_fetch.metadata_display, "update_metadata_queue", lambda _index: None)
    saves = []
    monkeypatch.setattr(metadata_fetch.metadata_io, "save_animethemes_metadata", lambda: saves.append(True))

    result = metadata_fetch.fetch_metadata(reference, refetch=True, batch_mode=True)

    assert result["mal"] == "376"
    assert playing["data"]["mal"] == current_mal
    assert {song["slug"] for song in result["songs"]} == {"OP1", "ED1"}
    assert all(song["nsfw"] and song["versions"][0]["nsfw"] for song in result["songs"])
    assert all(song["nsfw"] for song in state.metadata.anime_metadata["226"]["songs"])
    assert all(song["nsfw"] for song in metadata_fetch.get_metadata(reference)["songs"])
    assert "filter[video][basename-like]" not in calls[0]
    assert len(calls) == 1
    assert reference not in metadata_fetch.fetching_metadata
    assert saves == [True]
    retained = metadata_fetch.fetch_animethemes_metadata(mal_id="376")
    assert retained["studios"] == stale_special["studios"]
    assert all(theme["animethemeentries"][0]["nsfw"] for theme in retained["animethemes"])
    assert len(calls) == 1
    assert all(
        not name.startswith("[THEME_REF]")
        for versions in state.metadata.file_metadata["376"]["themes"].values()
        for files in versions.values()
        for name in files
    )


def test_failed_special_refetch_does_not_fall_back_to_shared_main_series(monkeypatch):
    main = _shared_anime(704, "226")
    special = _shared_anime(4957, "376")
    animethemes.replace_catalog(_catalog(main, special))
    animethemes.sync_catalog_to_metadata()
    reference = entry_paths.make_theme_reference("ElfenLied-OP1.webm", "376", "OP1", "1")
    monkeypatch.setattr(state.playback, "currently_playing", {})
    calls = []

    def fake_get(_url, params):
        calls.append(params)
        return _Response({"anime": []})

    monkeypatch.setattr(metadata_fetch.requests, "get", fake_get)
    before = copy.deepcopy(state.metadata.anime_metadata)

    assert metadata_fetch.fetch_metadata(reference, refetch=True, batch_mode=True) == {}
    assert len(calls) == 1
    assert calls[0]["filter[resource][external_id]"] == "376"
    assert state.metadata.anime_metadata == before
    assert reference not in metadata_fetch.fetching_metadata


def test_cached_fetch_keeps_explicit_special_identity(monkeypatch):
    animethemes.replace_catalog(_catalog(_shared_anime(704, "226"), _shared_anime(4957, "376")))
    animethemes.sync_catalog_to_metadata()
    reference = entry_paths.make_theme_reference("ElfenLied-OP1.webm", "376", "OP1", "1")
    monkeypatch.setattr(state.playback, "currently_playing", {})
    monkeypatch.setattr(metadata_fetch, "_linked_metadata_complete", lambda *_args: True)
    monkeypatch.setattr(metadata_fetch.requests, "get", lambda *_args, **_kwargs: pytest.fail("unexpected HTTP request"))

    result = metadata_fetch.fetch_metadata(reference)

    assert result["mal"] == "376"
    assert result["title"] == "Elfen Lied Special"


def test_manual_mal_refetch_retains_id_when_api_video_is_shared(monkeypatch):
    animethemes.replace_catalog(_catalog(_shared_anime(704, "226"), _shared_anime(4957, "376")))
    animethemes.sync_catalog_to_metadata()
    fresh_special = _shared_anime(4957, "376", nsfw=True)
    monkeypatch.setattr(state.playback, "currently_playing", {})
    calls = []

    def fake_get(_url, params):
        calls.append(params)
        assert params["filter[resource][external_id]"] == "376"
        return _Response({"anime": [fresh_special]})

    monkeypatch.setattr(metadata_fetch.requests, "get", fake_get)
    monkeypatch.setattr(metadata_fetch, "fetch_arm_ids", lambda _mal_id: {"anilist": "101", "anidb": "1544"})
    monkeypatch.setattr(metadata_fetch, "fetch_tenrai_metadata", lambda _mal_id: None)
    monkeypatch.setattr(metadata_fetch, "fetch_anilist_metadata", lambda **_kwargs: (None, None))
    monkeypatch.setattr(metadata_fetch, "fetch_anidb_metadata", lambda _anidb: {"tags": [], "characters": [], "episodes": []})
    monkeypatch.setattr(metadata_fetch, "extract_video_file_properties", lambda _filename: {})

    result = metadata_fetch.fetch_metadata("Special-OP1-[MAL]376.webm", refetch=True, batch_mode=True)

    assert result["mal"] == "376"
    assert all(song["nsfw"] for song in result["songs"])
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["nsfw", "spoiler"])
def test_shared_catalog_projection_unions_flags_without_rewriting_raw_api(field):
    main = _shared_anime(704, "226")
    special = _shared_anime(4957, "376")
    main["animethemes"][0]["animethemeentries"][0][field] = True
    animethemes.replace_catalog(_catalog(main, special))

    animethemes.sync_catalog_to_metadata()

    for mal_id in ("226", "376"):
        opening, ending = state.metadata.anime_metadata[mal_id]["songs"]
        assert opening[field] is True
        assert opening["versions"][0][field] is True
        assert not ending.get(field)
    assert special["animethemes"][0]["animethemeentries"][0][field] is False


def test_shared_ending_spoiler_is_consistent_without_changing_episode_ranges():
    anime = _anime(basename="StrikeWitchesS3-ED6-NCBD1080.webm")
    ending = anime["animethemes"][0]
    ending.update({"type": "ED", "slug": "ED6"})
    ending["animethemeentries"][0]["episodes"] = "6"
    finale = copy.deepcopy(ending)
    finale["slug"] = "ED12"
    finale["animethemeentries"][0].update({"episodes": "12", "spoiler": True})
    anime["animethemes"].append(finale)
    animethemes.replace_catalog(_catalog(anime))

    animethemes.sync_catalog_to_metadata()

    songs = state.metadata.anime_metadata["1"]["songs"]
    assert all(song["spoiler"] and song["versions"][0]["spoiler"] for song in songs)
    assert [song["episodes"] for song in songs] == ["6", "12"]


def test_shared_flags_remain_specific_to_physical_video_versions():
    main = _anime()
    special = _anime(2, mal_id="2")
    special["animethemes"][0]["animethemeentries"][0].update({"nsfw": True, "spoiler": True})
    clean = copy.deepcopy(main["animethemes"][0]["animethemeentries"][0])
    clean["version"] = 2
    clean["videos"][0]["basename"] = "Different-OP1v2.webm"
    main["animethemes"][0]["animethemeentries"].append(clean)
    animethemes.replace_catalog(_catalog(main, special))

    animethemes.sync_catalog_to_metadata()

    song = state.metadata.anime_metadata["1"]["songs"][0]
    first, second = song["versions"]
    assert first["nsfw"] and first["spoiler"]
    assert second["nsfw"] is False and second["spoiler"] is False
    assert song["nsfw"] is True
    assert not song.get("spoiler")


@pytest.mark.parametrize("field", ["nsfw", "spoiler"])
def test_saved_shared_video_flags_survive_missing_api_catalog_and_mp4_conversion(field):
    for mal_id, filename, flagged in (("1", "Shared-OP1.webm", True), ("2", "Shared-OP1.mp4", False), ("3", "Other-OP1.webm", False)):
        state.metadata.file_metadata[mal_id] = {"themes": {"OP1": {"1": {filename: {}}}}}
        state.metadata.anime_metadata[mal_id] = {
            "songs": [{"slug": "OP1", field: flagged, "versions": [{"version": 1, field: flagged}]}]
        }

    assert animethemes.reconcile_shared_video_flags() == 1

    song = state.metadata.anime_metadata["2"]["songs"][0]
    assert song[field] is True and song["versions"][0][field] is True
    assert state.metadata.anime_metadata["3"]["songs"][0][field] is False
    assert animethemes.reconcile_shared_video_flags() == 0


def test_refetch_of_missing_api_nsfw_flag_keeps_shared_warning(monkeypatch):
    main = _shared_anime(704, "226", nsfw=True)
    special = _shared_anime(4957, "376")
    animethemes.replace_catalog(_catalog(main, special))
    animethemes.sync_catalog_to_metadata()
    monkeypatch.setattr(state.playback, "currently_playing", {})
    monkeypatch.setattr(metadata_fetch.requests, "get", lambda _url, params: _Response({"anime": [special]}))
    monkeypatch.setattr(metadata_fetch, "fetch_tenrai_metadata", lambda _mal_id: None)
    monkeypatch.setattr(metadata_fetch, "fetch_anilist_metadata", lambda **_kwargs: (None, None))
    reference = entry_paths.make_theme_reference("ElfenLied-OP1.webm", "376", "OP1", "1")

    result = metadata_fetch.fetch_metadata(reference, refetch=True, batch_mode=True)

    assert result["mal"] == "376"
    assert all(song["nsfw"] and song["versions"][0]["nsfw"] for song in result["songs"])
    assert all(song["nsfw"] for song in metadata_fetch.get_metadata(reference)["songs"])
    assert all(not theme["animethemeentries"][0]["nsfw"] for theme in special["animethemes"])


def test_save_and_display_keep_shared_flags_after_stale_overrides(monkeypatch, tmp_path):
    main = _shared_anime(704, "226", nsfw=True)
    special = _shared_anime(4957, "376")
    animethemes.replace_catalog(_catalog(main, special))
    animethemes.sync_catalog_to_metadata()
    state.metadata.anime_metadata_overrides["376"] = {
        "songs": [{"slug": "OP1", "artist": ["Curated Artist"], "nsfw": False,
                   "versions": [{"version": 1, "nsfw": False}]}]
    }
    reference = entry_paths.make_theme_reference("ElfenLied-OP1.webm", "376", "OP1", "1")
    monkeypatch.setattr(state.playback, "currently_playing", {})
    monkeypatch.setattr(metadata_fetch, "_linked_metadata_complete", lambda *_args: True)
    saved = {}
    io = metadata_fetch.metadata_io
    monkeypatch.setattr(io, "FILE_METADATA_FILE", str(tmp_path / "file_metadata.json"))
    monkeypatch.setattr(io, "save_metadata_compressed", lambda path, data, **_kwargs: saved.update({path: copy.deepcopy(data)}))

    result = metadata_fetch.fetch_metadata(reference)
    opening = next(song for song in result["songs"] if song["slug"] == "OP1")
    assert opening["nsfw"] and opening["versions"][0]["nsfw"]
    assert opening["artist"] == ["Curated Artist"]
    io._do_save_metadata()

    opening = saved[io.ANIME_METADATA_FILE]["376"]["songs"][0]
    assert opening["nsfw"] and opening["versions"][0]["nsfw"]
    assert opening["artist"] == ["Curated Artist"]


def test_unique_video_keeps_its_existing_override_behavior():
    anime = _anime()
    anime["animethemes"][0]["animethemeentries"][0]["nsfw"] = True
    animethemes.replace_catalog(_catalog(anime))
    animethemes.sync_catalog_to_metadata()
    songs = state.metadata.anime_metadata["1"]["songs"]
    songs[0]["nsfw"] = False
    songs[0]["versions"][0]["nsfw"] = False

    assert animethemes.reconcile_shared_video_flags() == 0
    assert not animethemes.apply_shared_video_flags("1", songs)[0]["nsfw"]


def test_load_repairs_shared_flags_even_when_catalog_projection_is_current(monkeypatch, tmp_path):
    main = _shared_anime(704, "226", nsfw=True)
    special = _shared_anime(4957, "376")
    animethemes.replace_catalog(_catalog(main, special))
    animethemes.sync_catalog_to_metadata()
    for song in state.metadata.anime_metadata["376"]["songs"]:
        song["nsfw"] = False
        song["versions"][0]["nsfw"] = False
    io = metadata_fetch.metadata_io
    stores = {
        io.FILE_METADATA_FILE: copy.deepcopy(state.metadata.file_metadata),
        io.ANIME_METADATA_FILE: copy.deepcopy(state.metadata.anime_metadata),
        io.ANIMETHEMES_METADATA_FILE: copy.deepcopy(state.metadata.animethemes_metadata),
    }
    monkeypatch.setattr(io, "load_metadata_compressed", lambda path, **_kwargs: (copy.deepcopy(stores.get(path)), True))
    for name in ("MANUAL_METADATA_FILE", "ANIME_METADATA_OVERRIDES_FILE", "THEME_ARTIST_RESOLUTIONS_FILE"):
        monkeypatch.setattr(io, name, str(tmp_path / name))
    saves = []
    monkeypatch.setattr(io, "save_metadata", lambda: saves.append(True))
    monkeypatch.setattr(animethemes, "sync_catalog_to_metadata", lambda: pytest.fail("current catalog projection should not rebuild"))

    io.load_metadata()

    assert all(song["nsfw"] and song["versions"][0]["nsfw"] for song in state.metadata.anime_metadata["376"]["songs"])
    assert saves == [True]


def test_projection_upgrade_repairs_legacy_fake_aired_value():
    animethemes.replace_catalog(_catalog(_anime()))
    animethemes.sync_catalog_to_metadata()
    state.metadata.anime_metadata["1"]["aired"] = "N/A"
    state.metadata.file_metadata["1"]["animethemes_projection_version"] = 1

    animethemes.sync_catalog_to_metadata()

    assert state.metadata.anime_metadata["1"]["aired"] is None
    assert (
        state.metadata.file_metadata["1"]["animethemes_projection_version"]
        == animethemes.PROJECTION_VERSION
    )


def test_refresh_menu_exposes_animethemes_catalog_action():
    refresh_menu = next(
        item
        for item in menu_registry.get_menu_registry()["file"]
        if isinstance(item, dict) and item.get("label") == "Refresh Metadata"
    )
    item = next(
        child
        for child in refresh_menu["submenu"]
        if child.get("id") == "refresh_animethemes"
    )
    assert item["command"] is metadata_fetch.refresh_animethemes_catalog
