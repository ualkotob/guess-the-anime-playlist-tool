import pytest

from _app_scripts.playback import cache_download


class _Popup:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class _Root:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, callback, *args):
        self.after_calls.append((delay, callback, args))


@pytest.fixture
def download_state(monkeypatch):
    monkeypatch.setattr(cache_download, "active_downloads", {})
    monkeypatch.setattr(cache_download, "download_cancel_flags", {})
    monkeypatch.setattr(cache_download, "download_progress", {})
    monkeypatch.setattr(cache_download, "pending_play_queue", {})


def test_cancel_closes_popup_before_worker_finishes(download_state):
    filename = "Show-OP1.webm"
    popup = _Popup()
    cache_download.active_downloads[filename] = object()
    cache_download.download_progress[filename] = {"popup": popup}
    cache_download.pending_play_queue[filename] = {"playlist_entry": filename}

    cache_download.cancel_download(filename, popup)

    assert popup.destroyed is True
    assert cache_download.download_cancel_flags[filename] is True
    assert filename not in cache_download.download_progress
    assert filename not in cache_download.pending_play_queue
    assert filename in cache_download.active_downloads


def test_cancel_closes_orphaned_popup_without_active_worker(download_state):
    popup = _Popup()

    cache_download.cancel_download("Show-OP1.webm", popup)

    assert popup.destroyed is True


def test_ui_cleanup_closes_finished_download_popup(download_state):
    filename = "Show-OP1.webm"
    popup = _Popup()
    cache_download.download_progress[filename] = {"popup": popup}

    cache_download._close_download_popup(filename)

    assert popup.destroyed is True
    assert filename not in cache_download.download_progress


def test_stream_fallback_cancels_download_and_closes_popup(download_state, monkeypatch):
    filename = "Show-OP1.webm"
    popup = _Popup()
    root = _Root()
    cache_download.active_downloads[filename] = object()
    cache_download.download_progress[filename] = {"popup": popup}
    cache_download.pending_play_queue[filename] = {
        "playlist_entry": filename,
        "fullscreen": False,
        "start_time": 0,
        "timeout": 30,
    }
    monkeypatch.setattr(cache_download.state.widgets, "root", root)
    monkeypatch.setattr(cache_download.time, "time", lambda: 31)

    cache_download.check_download_ui_updates()

    assert popup.destroyed is True
    assert cache_download.download_cancel_flags[filename] is True
    assert filename not in cache_download.pending_play_queue


def test_timeout_stream_starts_while_cancelled_worker_is_still_active(download_state, monkeypatch):
    from _app_scripts.playback import transport
    filename = "Show-OP1.webm"
    url = "https://v.animethemes.moe/" + filename
    root = _Root()
    cache_download.active_downloads[filename] = object()
    cache_download.pending_play_queue[filename] = {
        "playlist_entry": filename, "fullscreen": False, "start_time": 0, "timeout": 30,
    }
    monkeypatch.setattr(cache_download.state.widgets, "root", root)
    monkeypatch.setattr(cache_download.time, "time", lambda: 31)
    monkeypatch.setattr(cache_download, "get_theme_stream_url", lambda *a, **k: url)
    resolutions = []
    monkeypatch.setattr(transport, "play_filename", lambda entry, fullscreen:
                        resolutions.append(cache_download.resolve_playable_path(
                            filename, entry, None, fullscreen)))
    monkeypatch.setattr(cache_download, "queue_play_when_ready", lambda *args:
                        pytest.fail("Streaming fallback requeued behind its cancelled worker"))
    cache_download.check_download_ui_updates()
    for delay, callback, args in root.after_calls:
        if delay == 100:
            callback(*args)
    assert filename in cache_download.active_downloads
    assert cache_download.download_cancel_flags[filename] is True
    assert resolutions == [(url, True)]


def test_ui_polling_survives_unexpected_failure(download_state, monkeypatch):
    root = _Root()
    monkeypatch.setattr(cache_download.state.widgets, "root", root)
    monkeypatch.setattr(cache_download, "_check_download_ui_updates", lambda:
                        (_ for _ in ()).throw(RuntimeError("metadata changed")))
    errors = []
    monkeypatch.setattr(cache_download, "log_exception", errors.append)
    cache_download.check_download_ui_updates()
    assert errors
    assert root.after_calls == [(500, cache_download.check_download_ui_updates, ())]
