"""Shared videos must enter infinite pools under their most popular anime."""

import pytest

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch
from _app_scripts.playback import cache_download
from _app_scripts.playlists import entry_paths, filters, infinite, playlist
from _app_scripts.theme import source_preferences


SHARED = "w0duks.webm"
ORIGINAL = "KamisamaHajimemashita-OP1.webm"
VERSION_TWO = "KamisamaHajimemashita-OP1v2.webm"


@pytest.fixture
def shared_video(monkeypatch, tmp_path):
    monkeypatch.setattr(state.config, "theme_online_source", "prefer_animethemes")
    monkeypatch.setattr(state.config, "theme_downloaded_first", True)
    monkeypatch.setattr(state.config, "theme_allow_excluded_downloads", True)
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "14713": {"name": "Kamisama Kiss", "themes": {"OP1": {
            "1": {
                ORIGINAL: {"source": "BD", "resolution": 720, "nc": True},
                SHARED: {"source": "ANISONGDB", "anisongdb_alternate": True, "resolution": 720, "nc": False},
            },
            "2": {VERSION_TWO: {"source": "BD", "resolution": 720}},
        }}},
        "18661": {"name": "Kamisama Kiss OVA", "themes": {"OP1": {
            "1": {SHARED: {"source": "ANISONGDB", "anisongdb_gap": True, "resolution": 720, "nc": False}},
        }}},
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {
        "14713": {"title": "Kamisama Kiss", "popularity": 321},
        "18661": {"title": "Kamisama Kiss OVA", "popularity": 1799},
    })
    monkeypatch.setattr(state.metadata, "playlist", {
        "infinite": True, "playlist": [], "infinite_settings": {"include_non_local_files": False},
    })
    monkeypatch.setattr(state.metadata, "directory_files", {SHARED: str(tmp_path / SHARED)})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal_candidates", {})
    monkeypatch.setattr(metadata_fetch, "_metadata_cache", {})
    monkeypatch.setattr(metadata_fetch.anisongdb, "has_catalog", lambda: True)
    monkeypatch.setattr(metadata_fetch.anisongdb, "apply_full_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_preferences, "_sources_loaded", True)
    monkeypatch.setattr(source_preferences, "_download_sources", {})
    monkeypatch.setattr(cache_download, "get_cached_file_path", lambda _name: None)
    monkeypatch.setattr(cache_download, "available_cached_files", lambda: {})
    metadata_fetch.build_filename_to_mal_map()
    return tmp_path


def test_popular_owner_wins_for_both_filename_lookup_and_infinite_pool(shared_video):
    assert metadata_fetch.get_file_metadata_by_name(SHARED)["mal"] == "14713"

    entries = infinite.get_infinite_directory_files()

    assert len(entries) == 1
    assert entry_paths.get_clean_filename(entries[0]) == SHARED
    assert metadata_fetch.get_metadata(entries[0])["mal"] == "14713"
    # Search/manual navigation can still address the other owner.
    other_owner = entry_paths.make_theme_reference(SHARED, "18661", "OP1", "1")
    assert metadata_fetch.get_file_metadata_by_name(other_owner)["mal"] == "18661"


@pytest.mark.parametrize("cached", [False, True])
def test_downloaded_animethemes_file_replaces_shared_video(shared_video, monkeypatch, cached):
    path = str(shared_video / ORIGINAL)
    if cached:
        monkeypatch.setattr(cache_download, "available_cached_files", lambda: {ORIGINAL: path})
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda name: path if name == ORIGINAL else None)
    else:
        state.metadata.directory_files[ORIGINAL] = path

    assert infinite.get_infinite_directory_files() == [ORIGINAL]


def test_shared_video_resolution_preserves_distinct_versions(shared_video):
    state.metadata.directory_files.update({
        ORIGINAL: str(shared_video / ORIGINAL),
        VERSION_TWO: str(shared_video / VERSION_TWO),
    })

    entries = infinite.get_infinite_directory_files()

    assert entries == [ORIGINAL, VERSION_TWO]
    assert playlist.deduplicate_theme_versions(entries, keep_versions=True) == entries


@pytest.mark.parametrize("rank", [None, "N/A", 0, 5000])
def test_popularity_can_favor_the_other_owner_and_handles_missing_ranks(shared_video, rank):
    state.metadata.anime_metadata["14713"]["popularity"] = rank

    entries = infinite.get_infinite_directory_files()

    assert len(entries) == 1
    assert metadata_fetch.get_metadata(entries[0])["mal"] == "18661"


def test_infinite_filters_evaluate_the_winning_anime(shared_video):
    # Popularity ranges follow the filter UI: minimum popularity caps the rank.
    assert len(filters.evaluate_filter({"popularity_min": 500})) == 1
    assert filters.evaluate_filter({"popularity_max": 1000}) == []


def test_downloaded_alternative_respects_source_exclusions(shared_video):
    state.metadata.directory_files[ORIGINAL] = str(shared_video / ORIGINAL)
    state.config.theme_online_source = "anisongdb_only"
    state.config.theme_allow_excluded_downloads = False

    entries = infinite.get_infinite_directory_files()

    assert len(entries) == 1
    assert entry_paths.get_clean_filename(entries[0]) == SHARED
    assert metadata_fetch.get_metadata(entries[0])["mal"] == "14713"


def test_source_first_policy_can_still_prefer_anisongdb(shared_video):
    state.metadata.directory_files[ORIGINAL] = str(shared_video / ORIGINAL)
    state.config.theme_online_source = "prefer_anisongdb"
    state.config.theme_downloaded_first = False

    entries = playlist.deduplicate_theme_versions(infinite.get_infinite_directory_files(), keep_versions=True)

    assert len(entries) == 1
    assert entry_paths.get_clean_filename(entries[0]) == SHARED
    assert metadata_fetch.get_metadata(entries[0])["mal"] == "14713"
