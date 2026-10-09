"""Search reuse, live invalidation and selection while typing."""

import threading
from types import SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts.data import metadata_io
from _app_scripts.file.metadata import metadata_display, metadata_fetch
from _app_scripts.playback import cache_download
from _app_scripts.search import search as search_ops
from _app_scripts.theme import source_preferences as sources


MAIN = "BananaFish-ED1.webm"
NC = "BananaFish-ED1-NC.webm"
ACOUSTIC = "acoustic.webm"
RED = "BananaFish-ED2.webm"
RED_ALTERNATE = "red-alternate.webm"


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    cache_folder = tmp_path / "cache"
    cache_folder.mkdir()
    monkeypatch.setattr(cache_download, "THEMES_CACHE_FOLDER", str(cache_folder))
    monkeypatch.setattr(cache_download, "cache_metadata", {})
    monkeypatch.setattr(sources, "_download_sources", {})
    monkeypatch.setattr(sources, "_sources_loaded", True)
    monkeypatch.setattr(state.config, "theme_online_source", "prefer_animethemes")
    monkeypatch.setattr(state.config, "theme_downloaded_first", True)
    monkeypatch.setattr(state.config, "theme_allow_excluded_downloads", True)
    monkeypatch.setattr(state.metadata, "directory_files", {})
    monkeypatch.setattr(state.metadata, "file_metadata_overrides", {})
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "123": {"name": "Banana Fish", "mal": "123", "themes": {
            "ED1": {"1": {MAIN: {"resolution": 1080}, NC: {"resolution": 720, "nc": True}}},
            "ED1.1": {"1": {ACOUSTIC: {"source": "ANISONGDB", "stream_url": "https://example.com/acoustic.webm"}}},
            "ED2": {"1": {
                RED: {"resolution": 1080},
                RED_ALTERNATE: {"source": "ANISONGDB", "stream_url": "https://example.com/red.webm",
                                "anisongdb_alternate": True},
            }},
        }},
        "456": {"name": "Other", "mal": "456", "themes": {"OP1": {"1": {"Other-OP1.webm": {}}}}},
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {
        "123": {"title": "Banana Fish", "studios": ["MAPPA"], "season": "  Summer   2018 ", "songs": [
            {"slug": "ED1", "title": "Prayer X", "artist": ["King Gnu"]},
            {"slug": "ED1.1", "title": "Prayer X (acoustic)", "artist": ["King Gnu"]},
            {"slug": "ED2", "title": "RED", "artist": ["Survive Said The Prophet"]},
        ]},
        "456": {"title": "Other", "eng_title": "Banana Split", "songs": []},
    })
    monkeypatch.setattr(metadata_fetch, "_metadata_cache", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal_candidates", {})
    monkeypatch.setattr(metadata_fetch, "metadata_cache_generation", 0)
    monkeypatch.setattr(metadata_display.censors, "censor_list", {})
    monkeypatch.setattr(metadata_display.censors, "other_censor_lists", [])
    monkeypatch.setattr(metadata_display.censors, "_youtube_censor_list", {})
    monkeypatch.setattr(search_ops, "_search_index", None)
    monkeypatch.setattr(search_ops, "_search_index_key", None)
    monkeypatch.setattr(search_ops, "_schedule_index_refresh", lambda: None)
    metadata_fetch.build_filename_to_mal_map()
    return cache_folder


def test_typing_reuses_text_and_selection_without_catalog_or_path_lookups(catalog, monkeypatch):
    search_ops.search_playlist("b")

    def repeated_work(*args, **kwargs):
        pytest.fail("A subsequent query rebuilt catalog data or probed theme paths")

    monkeypatch.setattr(search_ops.playlist_ops, "get_directory_files", repeated_work)
    monkeypatch.setattr(metadata_fetch, "get_metadata", repeated_work)
    monkeypatch.setattr(sources, "available_path", repeated_work)
    monkeypatch.setattr(search_ops.information_popup, "get_song_string", repeated_work)
    for query in ("ba", "ban", "banana"):
        assert search_ops.search_playlist(query) == [MAIN, ACOUSTIC, RED, "Other-OP1.webm"]


def test_index_build_does_not_probe_the_disk_for_uncached_catalog_entries(catalog, monkeypatch):
    def repeated_disk_check(*args):
        pytest.fail("The index probed an uncached remote filename")

    monkeypatch.setattr(cache_download, "get_cached_file_path", repeated_disk_check)
    assert search_ops.search_playlist("banana") == [MAIN, ACOUSTIC, RED, "Other-OP1.webm"]


def test_search_sorts_without_leading_the_and_keeps_it_searchable(catalog):
    state.metadata.anime_metadata["123"]["title"] = "The Amber"
    state.metadata.anime_metadata["456"].update({
        "title": "Birch", "eng_title": "Birch", "studios": ["MAPPA"],
    })
    metadata_fetch.invalidate_metadata_cache()

    assert search_ops.search_playlist("mappa") == [MAIN, ACOUSTIC, RED, "Other-OP1.webm"]
    assert search_ops.search_playlist("the amber") == [MAIN, ACOUSTIC, RED]


def test_refresh_without_metadata_changes_keeps_index(catalog, monkeypatch):
    search_ops.search_playlist("banana")
    original_index = search_ops._search_index
    monkeypatch.setattr(state.controls, "auto_refresh_toggle", False)
    metadata_fetch.get_metadata(MAIN, refresh=True)
    assert search_ops.search_playlist("banana") == [MAIN, ACOUSTIC, RED, "Other-OP1.webm"]
    assert search_ops._search_index is original_index


@pytest.mark.parametrize("query,expected", [
    ("NC", [NC]),
    ("acoustic", [ACOUSTIC]),
    ("King Gnu", [MAIN, ACOUSTIC]),
    ("mappa", [MAIN, ACOUSTIC, RED]),
    ("summer  2018", [MAIN, ACOUSTIC, RED]),
    ("2018", []),
])
def test_matching_keeps_filename_subsets_song_artists_and_season_rules(catalog, query, expected):
    assert search_ops.search_playlist(query) == expected


def test_source_and_download_preferences_refresh_index(catalog):
    assert search_ops.search_playlist("Survive") == [RED]
    state.config.theme_online_source = "prefer_anisongdb"
    assert search_ops.search_playlist("Survive") == [RED_ALTERNATE]
    state.metadata.directory_files[RED] = str(catalog / RED)
    assert search_ops.search_playlist("Survive") == [RED]
    state.config.theme_downloaded_first = False
    assert search_ops.search_playlist("Survive") == [RED_ALTERNATE]
    state.config.theme_online_source = "animethemes_only"
    assert search_ops.search_playlist("acoustic") == []


def test_cache_download_and_removal_refresh_index(catalog):
    state.config.theme_online_source = "prefer_anisongdb"
    assert search_ops.search_playlist("Survive") == [RED_ALTERNATE]
    path = catalog / RED
    path.write_bytes(b"video")
    cache_download.cache_metadata[RED] = {"path": RED}
    assert search_ops.search_playlist("Survive") == [RED]
    path.unlink()
    # Deletion must be detected even before the stale cache record is evicted.
    assert search_ops.search_playlist("Survive") == [RED_ALTERNATE]


def test_cache_inventory_keeps_unregistered_legacy_converted_files(catalog):
    state.config.theme_online_source = "prefer_anisongdb"
    (catalog / RED.replace(".webm", ".mp4")).write_bytes(b"video")
    assert cache_download.cache_metadata == {}
    assert search_ops.search_playlist("Survive") == [RED]


def test_download_provenance_and_same_size_directory_changes_refresh_index(catalog):
    state.config.theme_online_source = "animethemes_only"
    state.config.theme_allow_excluded_downloads = False
    path = str(catalog / MAIN)
    state.metadata.directory_files[MAIN] = path
    state.metadata.directory_files[NC] = str(catalog / NC)
    assert search_ops.search_playlist("Prayer X") == [MAIN]
    sources.record_download(path, "https://naedist.animemusicquiz.com/song.webm")
    assert search_ops.search_playlist("Prayer X") == [NC]
    state.metadata.directory_files[MAIN] = str(catalog / "moved.webm")
    assert search_ops.search_playlist("Prayer X") == [MAIN]


def test_metadata_edit_refreshes_cached_search_text(catalog):
    assert search_ops.search_playlist("acoustic") == [ACOUSTIC]
    state.metadata.anime_metadata["123"]["songs"][1]["title"] = "New song title"
    metadata_fetch.invalidate_metadata_cache([ACOUSTIC])
    assert search_ops.search_playlist("acoustic") == [ACOUSTIC]  # filename still matches
    assert search_ops.search_playlist("New song title") == [ACOUSTIC]


def test_saving_artist_override_refreshes_index(catalog, monkeypatch):
    assert search_ops.search_playlist("New Artist") == []
    state.metadata.anime_metadata["123"]["songs"][1]["artist"] = ["New Artist"]
    monkeypatch.setattr(metadata_io, "save_metadata_atomic", lambda *args: None)
    metadata_io.save_metadata_overrides()
    assert search_ops.search_playlist("New Artist") == [ACOUSTIC]


def test_censor_changes_refresh_file_ranking(catalog):
    assert search_ops.search_playlist("Prayer X") == [MAIN, ACOUSTIC]
    metadata_display.censors.censor_list[NC] = [{"start": 0, "end": 1}]
    assert search_ops.search_playlist("Prayer X") == [NC, ACOUSTIC]
    metadata_display.censors.censor_list.clear()
    assert search_ops.search_playlist("Prayer X") == [MAIN, ACOUSTIC]


def test_file_map_rebuild_keeps_shared_anime_search_results(catalog):
    assert search_ops.search_playlist("Banana Fish") == [MAIN, ACOUSTIC, RED]
    state.metadata.file_metadata["789"] = {
        "mal": "789", "themes": {"OP1": {"1": {MAIN: {}}}},
    }
    state.metadata.anime_metadata["789"] = {"title": "Banana Fish Special"}
    metadata_fetch.invalidate_metadata_cache()
    metadata_fetch.build_filename_to_mal_map()
    results = search_ops.search_playlist("Banana Fish")
    assert [metadata_fetch.get_metadata(entry)["title"] for entry in results] == [
        "Banana Fish", "Banana Fish", "Banana Fish", "Banana Fish Special",
    ]


def test_only_latest_waiting_query_runs(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls, callbacks, workers = [], [], []
    real_thread = threading.Thread

    def run_query(term):
        calls.append(term)
        if term == "b":
            started.set()
            assert release.wait(2)
        return [term]

    def start_thread(*args, **kwargs):
        worker = real_thread(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(search_ops.threading, "Thread", start_thread)
    monkeypatch.setattr(search_ops, "search_playlist", run_query)
    monkeypatch.setattr(search_ops, "_search_worker_lock", threading.Lock())
    monkeypatch.setattr(search_ops, "_search_token", 0)
    monkeypatch.setattr(search_ops, "search_term", "b")
    monkeypatch.setattr(state.widgets, "root", SimpleNamespace(after=lambda delay, callback: callbacks.append(callback)))
    search_ops.search(ask=False)
    assert started.wait(2)
    search_ops.search_term = "ba"
    search_ops.search(ask=False)
    search_ops.search_term = "ban"
    search_ops.search(ask=False)
    release.set()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    assert calls == ["b", "ban"]
    assert len(callbacks) == 1


@pytest.mark.parametrize("current_term", ["ba", ""])
def test_result_waiting_for_ui_is_rejected_after_typing_or_clearing(monkeypatch, current_term):
    monkeypatch.setattr(search_ops, "_search_token", 1)
    monkeypatch.setattr(search_ops, "search_term", current_term)
    monkeypatch.setattr(search_ops, "search_results", [])
    search_ops._apply_search_results(1, [MAIN], "b", True, False)
    assert search_ops.search_results == []


def test_artist_and_studio_index_reuses_search_and_preserves_file_ranking(catalog, monkeypatch):
    search_ops.search_playlist("banana")
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda *a, **k:
                        pytest.fail("Artist/studio lookup rescanned metadata"))
    assert metadata_display.get_filenames_from_artist("King Gnu") == sorted([MAIN, ACOUSTIC])
    assert metadata_display.get_filenames_from_studio("MAPPA") == sorted([MAIN, ACOUSTIC, RED])
    assert metadata_display.get_filenames_from_artist("king gnu") == []
    assert search_ops.get_catalog_matches("artist", "King Gnu", wait=False) == sorted([MAIN, ACOUSTIC])


def test_artist_index_tracks_source_cache_and_metadata_changes(catalog):
    assert metadata_display.get_filenames_from_artist("Survive Said The Prophet") == [RED]
    state.config.theme_online_source = "anisongdb_only"
    assert metadata_display.get_filenames_from_artist("Survive Said The Prophet") == [RED_ALTERNATE]
    state.metadata.anime_metadata["123"]["songs"][2]["artist"] = ["New Artist"]
    metadata_fetch.invalidate_metadata_cache()
    assert metadata_display.get_filenames_from_artist("Survive Said The Prophet") == []
    assert metadata_display.get_filenames_from_artist("New Artist") == [RED_ALTERNATE]
    path = catalog / RED
    path.write_bytes(b"video")
    cache_download.cache_metadata[RED] = {"path": RED}
    assert metadata_display.get_filenames_from_artist("New Artist") == [RED]
    path.unlink()
    assert metadata_display.get_filenames_from_artist("New Artist") == [RED_ALTERNATE]


def test_render_lookup_does_not_wait_for_index_worker(catalog):
    with search_ops._search_index_lock:
        assert search_ops.get_catalog_matches("artist", "King Gnu", wait=False) is None


def test_render_lookup_reuses_last_index_while_it_is_stale_or_rebuilding(catalog, monkeypatch):
    refreshes = []
    monkeypatch.setattr(search_ops, "_schedule_index_refresh", lambda: refreshes.append(True))
    assert metadata_display.get_filenames_from_artist("King Gnu") == sorted([MAIN, ACOUSTIC])
    metadata_fetch.invalidate_metadata_cache()  # As a prefetch download's metadata fetch does.
    assert search_ops._search_data_key() != search_ops._search_index_key
    monkeypatch.setattr(search_ops, "_get_search_index", lambda: pytest.fail("A render rebuilt the index"))
    monkeypatch.setattr(search_ops, "prepare_search_index", lambda: pytest.fail("A render started a rebuild"))
    assert search_ops.get_catalog_matches("artist", "King Gnu", wait=False) == sorted([MAIN, ACOUSTIC])
    with search_ops._search_index_lock:  # The quiet-period refresh is running.
        assert search_ops.get_catalog_matches("studio", "MAPPA", wait=False) == sorted([MAIN, ACOUSTIC, RED])
        assert metadata_fetch.get_artists_string(["King Gnu"], total=True) == "King Gnu [2]"
    assert len(refreshes) == 3


def test_info_popup_waits_only_for_the_first_index(catalog, monkeypatch):
    from _app_scripts.information import information_popup
    monkeypatch.setattr(search_ops, "prepare_search_index", lambda: None)
    # Startup: nothing to reuse yet, so the popup builds the index itself.
    assert information_popup.get_artist_themes_data("King Gnu")["theme_count"] == 2
    metadata_fetch.invalidate_metadata_cache()  # As a prefetch download's metadata fetch does.
    monkeypatch.setattr(search_ops, "_get_search_index", lambda: pytest.fail("The popup waited for a refresh"))
    assert information_popup.get_artist_themes_data("King Gnu")["theme_count"] == 2
    assert information_popup.get_studio_entries_data("MAPPA")["entry_count"] == 1


def test_index_refresh_waits_for_theme_changes_to_settle(monkeypatch):
    timers = []
    class Timer:
        def __init__(self, delay, callback):
            self.delay, self.callback, self.cancelled = delay, callback, False
            timers.append(self)
        def start(self):
            pass
        def cancel(self):
            self.cancelled = True
    monkeypatch.setattr(search_ops.threading, "Timer", Timer)
    monkeypatch.setattr(search_ops, "_index_refresh_timer", None)
    for _ in range(3):
        search_ops._schedule_index_refresh()
    assert [timer.cancelled for timer in timers] == [True, True, False]
    assert timers[-1].delay == search_ops.INDEX_REFRESH_DELAY
    assert timers[-1].callback is search_ops.prepare_search_index


def test_artist_count_fills_in_after_index_preparation(catalog, monkeypatch):
    from _app_scripts.file.metadata import metadata_display
    callbacks, buttons, shown = [], [], []
    class Button:
        def __init__(self, *args, **kwargs):
            self.options = kwargs
            self.exists = True
            buttons.append(self)
        def config(self, **kwargs):
            self.options.update(kwargs)
        def winfo_exists(self):
            return self.exists
        def destroy(self):
            self.exists = False
    monkeypatch.setattr(metadata_display.tk, "Button", Button)
    monkeypatch.setattr(search_ops, "prepare_search_index", lambda: None)
    monkeypatch.setattr(state.widgets, "root", SimpleNamespace(after=lambda delay, callback: callbacks.append(callback)))
    monkeypatch.setattr(metadata_display.lists, "show_field_themes", lambda **kwargs: shown.append(kwargs))
    column = SimpleNamespace(window_create=lambda *a, **k: None)
    metadata_display.add_catalog_total_button(column, "artist", "King Gnu")
    assert buttons[0].options["state"] == "disabled"
    search_ops._get_search_index()
    callbacks.pop(0)()
    assert buttons[0].options["text"] == "[2]"
    assert buttons[0].options["state"] == "normal"
    buttons[0].options["command"]()
    assert shown == [{"group": sorted([MAIN, ACOUSTIC]), "title": "King Gnu"}]


def test_web_theme_list_reuses_one_file_inventory(catalog, monkeypatch):
    calls = []
    inventory = cache_download.available_cached_files
    def counted_inventory():
        calls.append(True)
        return inventory()
    monkeypatch.setattr(cache_download, "available_cached_files", counted_inventory)
    monkeypatch.setattr(cache_download, "get_cached_file_path", lambda *a:
                        pytest.fail("Web theme rendering probed an uncached catalog file"))
    monkeypatch.setattr(state.metadata, "playlist", {})
    for song in state.metadata.anime_metadata["123"]["songs"]:
        song["type"] = "ED"
    data = {**state.metadata.anime_metadata["123"], "mal": "123", "slug": "ED1"}
    result = metadata_display._build_web_series_themes(data, MAIN)
    assert len(calls) == 1
    assert result[0]["anime_id"] == "123"
    themes = [theme for section in result[0]["sections"] for theme in section["themes"]]
    assert next(theme for theme in themes if theme["slug"] == "ED1")["filename"] == MAIN
