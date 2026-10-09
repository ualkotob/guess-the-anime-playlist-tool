"""Source policies across saved playlists, disk copies, URLs, and prefetch."""

import json
import threading
from types import SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts.file.metadata import metadata_display, metadata_fetch, metadata_panel
from _app_scripts.playback import cache_download, transport
from _app_scripts.playlists import entry_paths, playlist as playlist_ops
from _app_scripts.theme import source_preferences as sources


AT_FILE = "ExampleShow-OP1.webm"
AS_FILE = "abcdef.webm"
AT_URL = "https://v.animethemes.moe/" + AT_FILE
AS_URL = "https://naedist.animemusicquiz.com/" + AS_FILE


@pytest.fixture
def theme_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(state.config, "theme_online_source", "prefer_animethemes")
    monkeypatch.setattr(state.config, "theme_downloaded_first", True)
    monkeypatch.setattr(state.config, "theme_allow_excluded_downloads", True)
    monkeypatch.setattr(state.metadata, "directory_files", {})
    monkeypatch.setattr(state.metadata, "file_metadata_overrides", {})
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "123": {"name": "Example Show", "mal": "123", "themes": {"OP1": {"1": {
            AT_FILE: {"source": "BD", "resolution": 1080, "anisongdb_stream_url": AS_URL},
            AS_FILE: {"source": "ANISONGDB", "resolution": 720, "stream_url": AS_URL,
                      "anisongdb_alternate": True},
        }}}},
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})
    monkeypatch.setattr(metadata_fetch, "_metadata_cache", {})
    monkeypatch.setattr(sources, "_download_sources", {})
    monkeypatch.setattr(sources, "_sources_loaded", True)
    monkeypatch.setattr(sources, "DOWNLOAD_SOURCES_FILE", str(tmp_path / "sources.json"))
    monkeypatch.setattr(cache_download, "_download_failures", {})
    monkeypatch.setattr(cache_download, "active_downloads", {})
    monkeypatch.setattr(cache_download, "get_cached_file_path", lambda _filename: None)
    monkeypatch.setattr(metadata_display.censors, "get_file_censors", lambda _filename: None)
    metadata_fetch.build_filename_to_mal_map()
    return tmp_path


@pytest.mark.parametrize("policy,expected", [
    ("prefer_animethemes", [AT_URL, AS_URL]),
    ("prefer_anisongdb", [AS_URL, AT_URL]),
    ("animethemes_only", [AT_URL]),
    ("anisongdb_only", [AS_URL]),
])
@pytest.mark.parametrize("filename", [AT_FILE, AS_FILE])
def test_remote_source_order_and_exclusions(theme_sources, policy, expected, filename):
    state.config.theme_online_source = policy
    assert cache_download.get_theme_stream_urls(filename) == expected


def test_provenance_reads_do_not_wait_for_slow_save(theme_sources, monkeypatch):
    from _app_scripts import utils
    path = str(theme_sources / AS_FILE)
    sources.record_download(path, AS_URL)
    blocked, release, read_done = threading.Event(), threading.Event(), threading.Event()
    records = []
    def slow_write(*args, **kwargs):
        blocked.set()
        assert release.wait(3)
    monkeypatch.setattr(utils, "_atomic_json_write", slow_write)
    writer = threading.Thread(target=sources.save_download_sources)
    def read():
        records.append(sources.download_record(path))
        read_done.set()
    reader = threading.Thread(target=read)
    writer.start()
    try:
        assert blocked.wait(2)
        reader.start()
        assert read_done.wait(1), "UI provenance lookup waited for a disk save"
    finally:
        release.set()
        writer.join(3)
        if reader.ident is not None:
            reader.join(3)
    assert records[0]["source"] == "anisongdb"
    assert not writer.is_alive()


@pytest.mark.parametrize("policy,downloaded_first,allow_excluded,expected", [
    ("prefer_animethemes", True, True, AT_FILE),
    ("prefer_anisongdb", True, True, AT_FILE),
    ("prefer_anisongdb", False, True, AS_FILE),
    ("anisongdb_only", True, True, AT_FILE),
    ("anisongdb_only", False, True, AS_FILE),
    ("anisongdb_only", True, False, AS_FILE),
    ("anisongdb_only", False, False, AS_FILE),
])
def test_saved_playlist_uses_downloaded_file_policy(theme_sources, policy, downloaded_first, allow_excluded, expected):
    state.config.theme_online_source = policy
    state.config.theme_downloaded_first = downloaded_first
    state.config.theme_allow_excluded_downloads = allow_excluded
    path = theme_sources / AT_FILE
    path.write_bytes(b"video")
    state.metadata.directory_files[AT_FILE] = str(path)
    assert cache_download.select_theme_entry(AT_FILE) == expected
    assert metadata_display.get_theme_filename("123", "OP1", 1) == expected
    assert path.exists()


def test_preference_applies_to_cached_copies_too(theme_sources, monkeypatch):
    state.config.theme_online_source = "prefer_anisongdb"
    monkeypatch.setattr(cache_download, "get_cached_file_path",
                        lambda filename: str(theme_sources / AT_FILE) if filename == AT_FILE else None)
    assert cache_download.select_theme_entry(AT_FILE) == AT_FILE
    state.config.theme_downloaded_first = False
    assert cache_download.select_theme_entry(AT_FILE) == AS_FILE


def test_runtime_mapping_keeps_shared_theme_identity_and_lightning_marker(theme_sources):
    state.config.theme_online_source = "prefer_anisongdb"
    entry = "[L]" + entry_paths.make_theme_reference(AT_FILE, "123", "OP1", "1")
    selected = cache_download.select_theme_entry(entry)
    assert selected.startswith("[L]")
    assert entry_paths.parse_theme_reference(selected) == {
        "mal_id": "123", "slug": "OP1", "version": "1", "filename": AS_FILE,
    }


def test_switching_to_shared_video_adds_identity_and_scopes_remote_fallback(theme_sources, monkeypatch):
    other_file = "OtherShow-OP1.webm"
    state.metadata.file_metadata["456"] = {
        "mal": "456", "name": "Other Show", "themes": {"OP1": {"1": {
            other_file: {"source": "BD"},
            AS_FILE: {"source": "ANISONGDB", "stream_url": AS_URL, "anisongdb_gap": True},
        }}},
    }
    metadata_fetch.build_filename_to_mal_map()
    state.config.theme_online_source = "prefer_anisongdb"
    selected = cache_download.select_theme_entry(AT_FILE)
    assert entry_paths.parse_theme_reference(selected) == {
        "mal_id": "123", "slug": "OP1", "version": "1", "filename": AS_FILE,
    }
    assert cache_download.get_theme_stream_urls(selected) == [AS_URL, AT_URL]
    requested = []

    def response(url, **_kwargs):
        requested.append(url)
        if url == AS_URL:
            raise RuntimeError("preferred source unavailable")
        return SimpleNamespace(headers={}, raise_for_status=lambda: None, iter_content=lambda **_kw: [b"video"])

    monkeypatch.setattr(cache_download.requests, "get", response)
    assert cache_download._download_theme_file_to_path(AS_FILE, theme_sources / AS_FILE, theme_entry=selected)
    assert requested == [AS_URL, AT_URL]


def test_resolver_passes_shared_theme_identity_to_download(theme_sources, monkeypatch):
    state.config.theme_online_source = "prefer_anisongdb"
    selected = entry_paths.make_theme_reference(AS_FILE, "123", "OP1", "1")
    downloaded = []
    monkeypatch.setattr(cache_download, "download_to_cache", lambda filename, **kwargs: downloaded.append((filename, kwargs)) or False)
    assert cache_download.resolve_playable_path(AS_FILE, selected, None, False) == (AS_URL, True)
    assert downloaded == [(AS_FILE, {"silent": False, "theme_entry": selected})]


def test_covered_anisongdb_version_becomes_primary_without_duplicate_song(theme_sources):
    state.config.theme_online_source = "prefer_anisongdb"
    assert playlist_ops.get_directory_files(include_non_local=True) == [AS_FILE]
    state.metadata.directory_files[AT_FILE] = str(theme_sources / AT_FILE)
    assert playlist_ops.get_directory_files(include_non_local=True) == [AT_FILE]
    state.config.theme_downloaded_first = False
    assert playlist_ops.get_directory_files(include_non_local=True) == [AS_FILE]


def test_exclusion_applies_to_local_only_pools_and_version_list(theme_sources):
    state.config.theme_online_source = "anisongdb_only"
    state.metadata.directory_files[AT_FILE] = str(theme_sources / AT_FILE)
    assert playlist_ops.get_directory_files(include_non_local=False) == [AT_FILE]
    state.config.theme_allow_excluded_downloads = False
    assert playlist_ops.get_directory_files(include_non_local=False) == []
    assert metadata_display.get_theme_filenames("123", "OP1", 1) == [AS_FILE]


def test_explicit_stream_url_cannot_bypass_exclusion(theme_sources, monkeypatch):
    state.config.theme_online_source = "anisongdb_only"
    monkeypatch.setattr(cache_download, "download_to_cache", lambda *_args, **_kwargs: False)
    assert cache_download.resolve_playable_path(
        AT_FILE, {"filename": AT_FILE, "filepath": AT_URL}, None, False,
    ) == (AS_URL, True)


def test_explicit_local_path_cannot_bypass_strict_exclusion(theme_sources):
    state.config.theme_online_source = "anisongdb_only"
    state.config.theme_allow_excluded_downloads = False
    path = str(theme_sources / AT_FILE)
    assert cache_download.resolve_playable_path(
        AT_FILE, {"filename": AT_FILE, "filepath": path}, path, False,
    ) == (None, False)


def test_failed_preferred_download_reuses_permitted_existing_copy(theme_sources, monkeypatch):
    state.config.theme_online_source = "anisongdb_only"
    state.config.theme_downloaded_first = False
    state.metadata.directory_files[AT_FILE] = str(theme_sources / AT_FILE)
    requests = []

    def unavailable(url, **_kwargs):
        requests.append(url)
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(cache_download.requests, "get", unavailable)
    assert cache_download._download_theme_file_to_path(AS_FILE, str(theme_sources / AS_FILE)) is False
    assert requests == [AS_URL]
    assert cache_download.select_theme_entry(AT_FILE) == AT_FILE
    state.config.theme_allow_excluded_downloads = False
    assert cache_download.select_theme_entry(AT_FILE) == AS_FILE


def test_excluded_source_is_never_requested_during_download(theme_sources, monkeypatch):
    state.config.theme_online_source = "anisongdb_only"
    requests = []

    def response(url, **_kwargs):
        requests.append(url)
        return SimpleNamespace(headers={}, raise_for_status=lambda: None,
                               iter_content=lambda **_kw: [b"video"])

    monkeypatch.setattr(cache_download.requests, "get", response)
    path = theme_sources / AT_FILE
    assert cache_download._download_theme_file_to_path(AT_FILE, str(path)) is True
    assert requests == [AS_URL]
    assert sources.download_record(str(path))["filename"] == AS_FILE
    state.config.theme_online_source = "animethemes_only"
    state.config.theme_allow_excluded_downloads = False
    assert sources.downloaded_allowed(AT_FILE, str(path)) is False


def test_failed_preferred_source_uses_existing_fallback_without_downloading_it(theme_sources, monkeypatch):
    state.config.theme_online_source = "prefer_anisongdb"
    state.config.theme_downloaded_first = False
    state.metadata.directory_files[AT_FILE] = str(theme_sources / AT_FILE)
    requests = []

    def unavailable(url, **_kwargs):
        requests.append(url)
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(cache_download.requests, "get", unavailable)
    assert cache_download._download_theme_file_to_path(AS_FILE, str(theme_sources / AS_FILE)) is False
    assert requests == [AS_URL]
    assert cache_download.select_theme_entry(AT_FILE) == AT_FILE


def test_failed_download_preserves_existing_destination(theme_sources, monkeypatch):
    state.config.theme_online_source = "anisongdb_only"
    destination = theme_sources / AS_FILE
    destination.write_bytes(b"existing video")

    def chunks(**_kwargs):
        yield b"partial replacement"
        raise RuntimeError("connection interrupted")

    monkeypatch.setattr(cache_download.requests, "get", lambda *_args, **_kwargs:
                        SimpleNamespace(headers={}, raise_for_status=lambda: None, iter_content=chunks))
    assert cache_download._download_theme_file_to_path(AS_FILE, str(destination)) is False
    assert destination.read_bytes() == b"existing video"
    assert not (theme_sources / (AS_FILE + ".part")).exists()


def test_origin_survives_reload_conversion_and_cache_move(theme_sources, monkeypatch):
    old_path = str(theme_sources / AT_FILE)
    sources.record_download(old_path, AS_URL)
    sources.save_download_sources()
    assert json.loads((theme_sources / "sources.json").read_text())
    monkeypatch.setattr(sources, "_download_sources", {})
    monkeypatch.setattr(sources, "_sources_loaded", False)
    converted = str(theme_sources / AT_FILE.replace(".webm", ".mp4"))
    assert sources.downloaded_source(AT_FILE, converted) == sources.ANISONGDB
    moved = str(theme_sources / "permanent" / AT_FILE)
    sources.move_download_record(old_path, moved)
    assert sources.download_record(moved)["source"] == sources.ANISONGDB
    assert sources.download_record(old_path) == {}


def test_failed_direct_stream_falls_back_to_permitted_downloaded_copy(theme_sources, monkeypatch):
    state.config.theme_online_source = "anisongdb_only"
    state.config.theme_downloaded_first = False
    state.metadata.directory_files[AT_FILE] = str(theme_sources / AT_FILE)
    monkeypatch.setattr(transport, "animethemes_stream", True)
    monkeypatch.setattr(state.widgets, "player", SimpleNamespace(is_playing=lambda: False, get_length=lambda: 0))
    monkeypatch.setattr(state.playback, "currently_playing", {
        "filename": AS_FILE, "playlist_entry": {"filename": AS_FILE, "filepath": AS_URL},
    })
    played = []
    monkeypatch.setattr(transport, "play_filename", played.append)
    transport.play_video_retry(0, AS_FILE)
    assert played == [{"filename": AT_FILE}]


def test_prefetch_uses_preferred_alternative_for_existing_playlist(theme_sources, monkeypatch):
    state.config.theme_online_source = "prefer_anisongdb"
    state.config.theme_downloaded_first = False
    state.metadata.directory_files[AT_FILE] = str(theme_sources / AT_FILE)
    monkeypatch.setattr(state.metadata, "playlist", {"playlist": [AT_FILE], "current_index": 0})
    monkeypatch.setattr(cache_download.search_ops, "search_queue", None)
    monkeypatch.setattr(state.lightning, "fixed_lightning_queue", None)
    monkeypatch.setattr(state.lightning, "fixed_lightning_round_playlist_data", None)
    downloaded = []

    def download(filename, silent=False):
        downloaded.append(filename)
        cache_download.active_downloads[filename] = True
        return True

    monkeypatch.setattr(cache_download, "download_to_cache", download)
    cache_download.prefetch_next_themes()
    assert downloaded == [AS_FILE]


@pytest.mark.parametrize("policy", list(sources.SOURCE_CHOICES))
@pytest.mark.parametrize("filename,url", [(AT_FILE, AT_URL), (AS_FILE, AS_URL)])
def test_explicit_file_ignores_source_and_download_preferences(theme_sources, monkeypatch, policy, filename, url):
    state.config.theme_online_source = policy
    state.config.theme_downloaded_first = True
    state.config.theme_allow_excluded_downloads = False
    # A better downloaded alternative must not replace the clicked video.
    other = AS_FILE if filename == AT_FILE else AT_FILE
    state.metadata.directory_files[other] = str(theme_sources / other)
    reference = entry_paths.make_theme_reference(filename, "123", "OP1", "1")
    entry = {"filename": reference, "_explicit_file": True}
    monkeypatch.setattr(cache_download, "download_to_cache", lambda *args, **kwargs: False)
    assert cache_download.select_theme_entry(entry) is entry
    assert cache_download.get_theme_stream_urls(reference, explicit_file=True) == [url]
    assert cache_download.resolve_playable_path(filename, entry, None, False) == (url, True)


def test_explicit_file_uses_excluded_downloaded_copy(theme_sources):
    state.config.theme_online_source = "animethemes_only"
    state.config.theme_allow_excluded_downloads = False
    path = str(theme_sources / AS_FILE)
    sources.record_download(path, AS_URL)
    entry = {"filename": AS_FILE, "_explicit_file": True}
    assert cache_download.resolve_playable_path(AS_FILE, entry, path, False) == (path, False)


def test_explicit_file_rejects_previously_saved_fallback(theme_sources, monkeypatch):
    path = str(theme_sources / AS_FILE)
    sources.record_download(path, AT_URL)
    monkeypatch.setattr(cache_download, "get_cached_file_path", lambda filename: path if filename == AS_FILE else None)
    monkeypatch.setattr(cache_download, "download_to_cache", lambda *args, **kwargs: False)
    entry = {"filename": AS_FILE, "_explicit_file": True}
    assert cache_download.resolve_playable_path(AS_FILE, entry, path, False) == (AS_URL, True)


@pytest.mark.parametrize("success", [True, False])
def test_explicit_download_requests_only_the_selected_video(theme_sources, monkeypatch, success):
    state.config.theme_online_source = "animethemes_only"
    requested = []

    def response(url, **kwargs):
        requested.append(url)
        if not success:
            raise RuntimeError("Selected video unavailable")
        return SimpleNamespace(headers={}, raise_for_status=lambda: None,
                               iter_content=lambda **kwargs: [b"selected video"])

    monkeypatch.setattr(cache_download.requests, "get", response)
    destination = theme_sources / AS_FILE
    assert cache_download._download_theme_file_to_path(AS_FILE, destination, explicit_file=True) is success
    assert requested == [AS_URL]
    if success:
        assert destination.read_bytes() == b"selected video"
        assert sources.download_record(str(destination))["source"] == sources.ANISONGDB
    else:
        assert not destination.exists()


def test_cache_worker_carries_explicit_choice_and_replaces_wrong_fallback(theme_sources, monkeypatch):
    destination = theme_sources / AS_FILE
    destination.write_bytes(b"wrong fallback video")
    sources.record_download(str(destination), AT_URL)
    monkeypatch.setattr(cache_download, "get_cached_file_path", lambda filename: str(destination))
    monkeypatch.setattr(cache_download, "download_cancel_flags", {})
    monkeypatch.setattr(cache_download, "download_progress", {})
    monkeypatch.setattr(cache_download, "_resolve_download_destination", lambda filename: (str(destination), AS_FILE, False))
    monkeypatch.setattr(cache_download, "_finalize_cached_file", lambda *args: True)
    monkeypatch.setattr(sources, "save_download_sources", lambda: None)
    monkeypatch.setattr(cache_download, "downloads_completed", 0)
    monkeypatch.setattr(cache_download, "download_ui_update_pending", False)
    requested = []

    def response(url, **kwargs):
        requested.append(url)
        return SimpleNamespace(headers={}, raise_for_status=lambda: None,
                               iter_content=lambda **kwargs: [b"selected video"])

    class _Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(cache_download.requests, "get", response)
    monkeypatch.setattr(cache_download.threading, "Thread", _Thread)
    reference = entry_paths.make_theme_reference(AS_FILE, "123", "OP1", "1")
    assert cache_download.download_to_cache(AS_FILE, silent=True, theme_entry=reference, explicit_file=True)
    assert requested == [AS_URL]
    assert destination.read_bytes() == b"selected video"
    assert sources.download_record(str(destination))["filename"] == AS_FILE


def test_download_retry_retains_explicit_file_and_anime_identity(theme_sources, monkeypatch):
    reference = entry_paths.make_theme_reference(AS_FILE, "123", "OP1", "1")
    entry = {"filename": reference, "_explicit_file": True}
    monkeypatch.setattr(cache_download, "pending_play_queue", {AS_FILE: {
        "playlist_entry": entry, "fullscreen": False, "start_time": 0, "timeout": 30,
    }})
    monkeypatch.setattr(cache_download, "download_progress", {})
    monkeypatch.setattr(cache_download, "download_cancel_flags", {})
    downloads = []
    monkeypatch.setattr(cache_download, "download_to_cache", lambda filename, **kwargs: downloads.append((filename, kwargs)))
    cache_download.retry_download(AS_FILE)
    assert downloads == [(AS_FILE, {"silent": False, "theme_entry": reference, "explicit_file": True})]
    assert cache_download.pending_play_queue[AS_FILE]["playlist_entry"] == entry


def test_download_timeout_streams_the_explicit_file(theme_sources, monkeypatch):
    state.config.theme_online_source = "animethemes_only"
    reference = entry_paths.make_theme_reference(AS_FILE, "123", "OP1", "1")
    entry = {"filename": reference, "_explicit_file": True}
    monkeypatch.setattr(cache_download, "pending_play_queue", {AS_FILE: {
        "playlist_entry": entry, "fullscreen": False, "start_time": 0, "timeout": 30,
    }})
    monkeypatch.setattr(cache_download, "download_progress", {})
    monkeypatch.setattr(cache_download, "download_cancel_flags", {})
    monkeypatch.setattr(cache_download, "download_ui_update_pending", False)
    cache_download.active_downloads[AS_FILE] = object()
    callbacks = []
    root = SimpleNamespace(after=lambda delay, callback, *args: callbacks.append((delay, callback, args)))
    monkeypatch.setattr(state.widgets, "root", root)
    monkeypatch.setattr(cache_download.time, "time", lambda: 31)
    played = []
    monkeypatch.setattr(transport, "play_filename_streaming_fallback", lambda entry, fullscreen: played.append((entry, fullscreen)))
    cache_download.check_download_ui_updates()
    for delay, callback, args in callbacks:
        if delay == 100:
            callback(*args)
    assert played == [({**entry, "_stream_url": AS_URL}, False)]


def test_failed_explicit_stream_reports_error_without_substituting(theme_sources, monkeypatch):
    state.metadata.directory_files[AT_FILE] = str(theme_sources / AT_FILE)
    entry = {"filename": AS_FILE, "_explicit_file": True}
    monkeypatch.setattr(transport, "animethemes_stream", True)
    monkeypatch.setattr(state.controls, "video_stopped", False)
    monkeypatch.setattr(state.widgets, "player", SimpleNamespace(is_playing=lambda: False, get_length=lambda: 0))
    monkeypatch.setattr(state.playback, "currently_playing", {"filename": AS_FILE, "playlist_entry": entry})
    errors = []
    monkeypatch.setattr(transport.messagebox, "showerror", lambda *args: errors.append(args))

    def unexpected_play(*args, **kwargs):
        pytest.fail("Explicit selection fell back to another theme or video")

    monkeypatch.setattr(transport, "play_filename", unexpected_play)
    monkeypatch.setattr(transport, "play_video", unexpected_play)
    transport.play_video_retry(0, AS_FILE)
    assert errors and AS_FILE in errors[0][1]
    assert state.controls.video_stopped
    assert cache_download.downloaded_fallback_entry(entry) is None


@pytest.mark.parametrize("filename,url,policy,resolution", [
    (AS_FILE, AS_URL, "prefer_animethemes", 720),
    (AT_FILE, AT_URL, "prefer_anisongdb", 1080),
])
def test_theme_button_reaches_player_with_clicked_file(theme_sources, monkeypatch, filename, url, policy, resolution):
    """Exercise the real button, queue, source selection and path resolution."""
    state.config.theme_online_source = policy
    monkeypatch.setattr(state.config, "auto_fetch_missing", False)
    monkeypatch.setattr(state, "lightning", SimpleNamespace(**vars(state.lightning)))
    monkeypatch.setattr(state, "controls", SimpleNamespace(**vars(state.controls)))
    monkeypatch.setattr(state, "playback", SimpleNamespace(**vars(state.playback)))
    state.playback.currently_playing = {}
    state.playback.youtube_queue = None
    state.lightning.fixed_lightning_queue = None
    state.lightning.fixed_lightning_round_playlist_data = None
    state.lightning.fixed_current_round = None
    state.lightning.light_mode = None
    state.controls.auto_info_start = False
    state.controls.auto_bonus_start = None
    state.controls.auto_reveal_start = None
    monkeypatch.setattr(state.metadata, "playlist", {"current_index": 0, "playlist": [AT_FILE]})
    monkeypatch.setattr(transport.search_ops, "search_queue", None)
    monkeypatch.setattr(transport, "animethemes_stream", None)
    monkeypatch.setattr(transport, "skip_limit", 0)
    for name in ("playlist_loaded", "playlist_changed", "playing_next_error"):
        monkeypatch.setattr(transport, name, False)
    monkeypatch.setattr(transport.playlist_ops, "playlist_changed", False)
    other = AT_FILE if filename == AS_FILE else AS_FILE
    state.metadata.directory_files[other] = str(theme_sources / other)
    monkeypatch.setattr(cache_download, "download_to_cache", lambda *args, **kwargs: False)
    monkeypatch.setattr(transport.web_server, "is_running", lambda: False)
    monkeypatch.setattr(transport.session_end, "end_message_window", None)
    for module, names in (
        (transport.round_start_guard, ["begin_round"]),
        (transport.lightning_manager, ["clean_up_light_round"]),
        (transport.osd_text, ["set_countdown_muted", "set_countdown"]),
        (transport.peek_dispatch, ["stop_timed_reveal"]),
        (transport.bonus, ["guess_extra"]),
        (transport.information_popup, ["toggle_title_popup"]),
        (transport.coming_up_ui, ["toggle_coming_up_popup"]),
        (transport.censors, ["on_play_starting"]),
        (metadata_display, ["update_metadata_queue"]),
    ):
        for name in names:
            monkeypatch.setattr(module, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(transport.censors, "get_start_skip_end", lambda filename: None)
    monkeypatch.setattr(transport.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))

    class _Button:
        def __init__(self, *args, **kwargs):
            self.command = kwargs["command"]

        def bind(self, *args):
            pass

    class _PlayerReached(Exception):
        pass

    media = []

    def load_media(filepath, **kwargs):
        media.append(filepath)
        raise _PlayerReached

    monkeypatch.setattr(metadata_panel.tk, "Button", _Button)
    monkeypatch.setattr(transport, "_load_incoming_media", load_media)
    button = metadata_panel._create_theme_play_button(None, filename, "Play", mal_id="123", slug="OP1", version="1")
    with pytest.raises(_PlayerReached):
        button.command()
    assert media == [url]
    playing = state.playback.currently_playing
    assert playing["filename"] == filename
    assert playing["playlist_entry"]["_explicit_file"] is True
    assert playing["data"]["mal"] == "123"
    assert playing["data"]["file_properties"]["resolution"] == resolution
