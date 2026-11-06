"""A stuck media clock must not hold a playlist forever."""

from types import SimpleNamespace

from core.game_state import state
from _app_scripts.playback import transport


def test_stalled_theme_advances_after_timeout(monkeypatch):
    now = [0.0]
    position = [1000]
    paused = [False]
    skipped = []
    player = SimpleNamespace(
        is_paused=lambda: paused[0],
        get_time=lambda: position[0],
        get_length=lambda: 90000,
        seek_recently=lambda _seconds: False,
    )
    monkeypatch.setattr(transport, "_theme_stall", {
        "since": 0.0, "position": None, "filename": "broken.webm",
        "started": False, "limit": 5, "startup_limit": 8,
    })
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport, "skip_filename", lambda: skipped.append(True))
    monkeypatch.setattr(transport, "log_warning", lambda *_args: None)
    monkeypatch.setattr(state.controls, "video_stopped", False)
    monkeypatch.setattr(state.controls, "autoplay_toggle", 0)
    theme = {"type": "theme", "filename": "broken.webm"}

    assert not transport._theme_playback_stalled(player, theme)
    now[0] = 4
    assert not transport._theme_playback_stalled(player, theme)
    paused[0] = True
    now[0] = 6
    assert not transport._theme_playback_stalled(player, theme)
    paused[0] = False
    position[0] = 2000
    now[0] = 7
    assert not transport._theme_playback_stalled(player, theme)
    now[0] = 13
    assert transport._theme_playback_stalled(player, theme)
    assert skipped == [True]


def test_stall_guard_ignores_other_media_and_stopped_playback(monkeypatch):
    player = SimpleNamespace(is_paused=lambda: False, get_time=lambda: 0, get_length=lambda: 0)
    monkeypatch.setattr(transport, "_theme_stall", {
        "since": 0.0, "position": 0, "filename": "broken.webm",
        "started": True, "limit": 5, "startup_limit": 8,
    })
    monkeypatch.setattr(transport.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(state.controls, "video_stopped", False)
    monkeypatch.setattr(state.controls, "autoplay_toggle", 0)
    assert not transport._theme_playback_stalled(player, {"type": "youtube", "filename": "broken.webm"})
    assert not transport._theme_playback_stalled(player, {"type": "theme", "filename": "next.webm"})
    state.controls.video_stopped = True
    assert not transport._theme_playback_stalled(player, {"type": "theme", "filename": "broken.webm"})


def test_startup_and_recent_seek_get_grace_periods(monkeypatch):
    now = [0.0]
    seek_recent = [False]
    skipped = []
    player = SimpleNamespace(
        is_paused=lambda: False,
        get_time=lambda: 0,
        seek_recently=lambda _seconds: seek_recent[0],
    )
    monkeypatch.setattr(transport, "_theme_stall", {
        "since": 0.0, "position": None, "filename": "loading.webm",
        "started": False, "limit": 5, "startup_limit": 8,
    })
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport, "skip_filename", lambda: skipped.append(True))
    monkeypatch.setattr(transport, "log_warning", lambda *_args: None)
    monkeypatch.setattr(state.controls, "video_stopped", False)
    monkeypatch.setattr(state.controls, "autoplay_toggle", 0)
    theme = {"type": "theme", "filename": "loading.webm"}
    assert not transport._theme_playback_stalled(player, theme)
    now[0] = 6
    assert not transport._theme_playback_stalled(player, theme)
    seek_recent[0] = True
    now[0] = 7
    assert not transport._theme_playback_stalled(player, theme)
    seek_recent[0] = False
    now[0] = 14
    assert not transport._theme_playback_stalled(player, theme)
    now[0] = 22
    assert transport._theme_playback_stalled(player, theme)
    assert skipped == [True]
