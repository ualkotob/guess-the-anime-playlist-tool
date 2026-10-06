"""Tests for the self-bootstrapping AnimeThemes catalog provider."""

from __future__ import annotations

import copy

import pytest

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch
from _app_scripts.playback import cache_download
from _app_scripts.playlists import playlist
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
def isolated_metadata():
    stores = (
        "file_metadata",
        "anime_metadata",
        "animethemes_metadata",
        "anisongdb_metadata",
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
