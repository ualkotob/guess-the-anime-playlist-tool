import pytest

from _app_scripts.playback import transport
from _app_scripts.queue_round.lightning_rounds import (
    frame_round,
    lightning_manager,
    round_start_guard,
)


class _Player:
    def __init__(self):
        self.mute_calls = []

    def audio_set_mute(self, muted):
        self.mute_calls.append(muted)


class _OrderedPlayer:
    def __init__(self, events):
        self.events = events

    def audio_set_mute(self, muted):
        self.events.append(("mute", muted))

    def set_media(self, filepath, start_seconds=None):
        self.events.append(("load", filepath, start_seconds))


class _DeferredRoot:
    def __init__(self):
        self.callbacks = []

    def after(self, delay, callback):
        self.callbacks.append((delay, callback))
        return len(self.callbacks)


def test_muted_lightning_media_is_muted_before_load(monkeypatch):
    player = _Player()
    monkeypatch.setattr(transport.state.widgets, "player", player)
    monkeypatch.setattr(transport.state.lightning, "light_mode", "title")
    monkeypatch.setattr(
        transport.state.playback,
        "lightning_mode_settings",
        {"title": {"muted": True}},
    )
    monkeypatch.setattr(transport.state.controls, "light_muted", False)

    assert transport._pre_mute_incoming_lightning_media() is True
    assert player.mute_calls == [True]
    assert transport.state.controls.light_muted is True


def test_audible_lightning_media_keeps_existing_audio_state(monkeypatch):
    player = _Player()
    monkeypatch.setattr(transport.state.widgets, "player", player)
    monkeypatch.setattr(transport.state.lightning, "light_mode", "regular")
    monkeypatch.setattr(
        transport.state.playback,
        "lightning_mode_settings",
        {"regular": {"muted": False}},
    )
    monkeypatch.setattr(transport.state.controls, "light_muted", False)

    assert transport._pre_mute_incoming_lightning_media() is False
    assert player.mute_calls == []
    assert transport.state.controls.light_muted is False


@pytest.mark.parametrize(
    ("mode", "muted"),
    [
        ("regular", False),
        ("blind", False),
        ("reveal", False),
        ("title", True),
        ("trivia", True),
        ("emoji", True),
    ],
)
def test_lightning_cover_and_mute_are_applied_before_media_load(
    monkeypatch, mode, muted
):
    events = []
    player = _OrderedPlayer(events)
    monkeypatch.setattr(transport.state.widgets, "player", player)
    monkeypatch.setattr(transport.state.lightning, "light_mode", mode)
    monkeypatch.setattr(
        transport.state.playback,
        "lightning_mode_settings",
        {mode: {"muted": muted}},
    )
    monkeypatch.setattr(transport.state.controls, "light_muted", False)
    monkeypatch.setattr(transport.blind_screen, "blind_round_toggle", False)
    monkeypatch.setattr(transport.peek_dispatch, "peek_round_toggle", False)
    monkeypatch.setattr(
        transport.peek_dispatch, "mute_peek_round_toggle", False
    )
    monkeypatch.setattr(
        transport.blind_screen,
        "set_black_screen",
        lambda toggle, **kwargs: events.append(("blind", toggle, kwargs)),
    )

    transport._load_incoming_media("theme.webm", start_seconds=1.25)

    expected = [("blind", True, {"smooth": False})]
    if muted:
        expected.append(("mute", True))
    expected.append(("load", "theme.webm", 1.25))
    assert events == expected


def test_non_lightning_media_does_not_gain_a_startup_cover(monkeypatch):
    events = []
    monkeypatch.setattr(transport.state.widgets, "player", _OrderedPlayer(events))
    monkeypatch.setattr(transport.state.lightning, "light_mode", None)
    monkeypatch.setattr(transport.blind_screen, "blind_round_toggle", False)
    monkeypatch.setattr(transport.peek_dispatch, "peek_round_toggle", False)
    monkeypatch.setattr(
        transport.peek_dispatch, "mute_peek_round_toggle", False
    )
    monkeypatch.setattr(
        transport.blind_screen,
        "set_black_screen",
        lambda *args, **kwargs: events.append(("blind", args, kwargs)),
    )

    transport._load_incoming_media("theme.webm")

    assert events == [("load", "theme.webm", None)]


def test_delayed_startup_callback_is_discarded_after_generation_changes(
    monkeypatch,
):
    root = _DeferredRoot()
    calls = []
    monkeypatch.setattr(round_start_guard.state.widgets, "root", root)
    monkeypatch.setattr(
        round_start_guard.state.playback,
        "currently_playing",
        {"filename": "repeated.webm"},
    )
    monkeypatch.setattr(round_start_guard.state.lightning, "round_generation", 10)

    round_start_guard.after(500, calls.append, "uncover")
    round_start_guard.begin_round()
    round_start_guard.state.playback.currently_playing["filename"] = (
        "repeated.webm"
    )
    root.callbacks[0][1]()

    assert calls == []


def test_delayed_startup_callback_runs_for_current_round(monkeypatch):
    root = _DeferredRoot()
    calls = []
    monkeypatch.setattr(round_start_guard.state.widgets, "root", root)
    monkeypatch.setattr(
        round_start_guard.state.playback,
        "currently_playing",
        {"filename": "current.webm"},
    )
    monkeypatch.setattr(round_start_guard.state.lightning, "round_generation", 20)

    round_start_guard.after(300, calls.append, "ready")
    root.callbacks[0][1]()

    assert calls == ["ready"]


def test_normal_lightning_answer_restores_audio(monkeypatch):
    stop_calls = []
    mute_calls = []
    monkeypatch.setattr(
        lightning_manager.streaming,
        "stop_stream",
        lambda restore=True: stop_calls.append(restore),
    )
    monkeypatch.setattr(
        lightning_manager.audio_toggles,
        "toggle_mute",
        lambda muted=None, lightning=False: mute_calls.append((muted, lightning)),
    )
    monkeypatch.setattr(lightning_manager.state.controls, "light_muted", True)

    lightning_manager._restore_lightning_answer_audio(False, None, False)

    assert stop_calls == [True]
    assert mute_calls == [(False, True)]
    assert lightning_manager.state.controls.light_muted is False


def test_answer_clip_is_preserved_but_unmuted(monkeypatch):
    stop_calls = []
    mute_calls = []
    monkeypatch.setattr(
        lightning_manager.streaming,
        "stop_stream",
        lambda restore=True: stop_calls.append(restore),
    )
    monkeypatch.setattr(
        lightning_manager.audio_toggles,
        "toggle_mute",
        lambda muted=None, lightning=False: mute_calls.append((muted, lightning)),
    )
    monkeypatch.setattr(lightning_manager.state.controls, "light_muted", True)

    lightning_manager._restore_lightning_answer_audio(
        False, {"clip_for_answer": True}, False
    )

    assert stop_calls == []
    assert mute_calls == [(False, True)]
    assert lightning_manager.state.controls.light_muted is False


def test_frame_round_restores_audio_before_starting_answer(monkeypatch):
    events = []

    class FramePlayer:
        def __init__(self):
            self.playing = False
            self.time = 40_000

        def is_playing(self):
            return self.playing

        def pause(self):
            self.playing = False

        def play(self):
            events.append("play")
            self.playing = True

        def get_length(self):
            return 120_000

        def get_time(self):
            return self.time

        def set_time(self, time):
            self.time = time

    class UpdateRoot:
        def update(self):
            pass

    monkeypatch.setattr(frame_round.state.widgets, "player", FramePlayer())
    monkeypatch.setattr(frame_round.state.widgets, "root", UpdateRoot())
    monkeypatch.setattr(
        frame_round.state.playback,
        "currently_playing",
        {"filename": "frame.webm"},
    )
    monkeypatch.setattr(
        frame_round.state.playback,
        "lightning_mode_settings",
        {"_misc_settings": {"framed_video": False}},
    )
    monkeypatch.setattr(frame_round.state.lightning, "light_round_length", 12)
    monkeypatch.setattr(
        frame_round.state.lightning, "fixed_current_round", None
    )
    monkeypatch.setattr(frame_round.state.controls, "disable_video_audio", False)
    monkeypatch.setattr(frame_round.state.controls, "light_muted", True)
    monkeypatch.setattr(frame_round, "frame_light_round_started", True)
    monkeypatch.setattr(frame_round, "frame_light_round_pause", False)
    monkeypatch.setattr(frame_round, "frame_light_round_frames", [10, 20, 30, 40])
    monkeypatch.setattr(frame_round, "frame_light_round_frame_index", 3)
    monkeypatch.setattr(frame_round, "frame_light_round_frame_time", 3_000)
    monkeypatch.setattr(frame_round.censors, "apply_censors", lambda *_args: None)
    monkeypatch.setattr(
        frame_round.information_popup, "is_title_window_up", lambda: False
    )
    monkeypatch.setattr(
        frame_round.information_popup,
        "toggle_title_popup",
        lambda *_args, **_kwargs: events.append("title"),
    )
    monkeypatch.setattr(
        frame_round.blind_screen,
        "set_black_screen",
        lambda *_args, **_kwargs: events.append("uncover"),
    )
    monkeypatch.setattr(
        frame_round.osd_text, "set_countdown", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        frame_round.osd_text, "bottom_info", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        frame_round.music,
        "play_background_music",
        lambda enabled: events.append(("music", enabled)),
    )
    monkeypatch.setattr(frame_round.round_start_guard, "after", lambda *_args: None)
    monkeypatch.setattr(
        lightning_manager.streaming, "stop_stream", lambda restore=True: None
    )
    monkeypatch.setattr(
        lightning_manager.audio_toggles,
        "toggle_mute",
        lambda muted=None, lightning=False: events.append(
            ("mute", muted, lightning)
        ),
    )

    frame_round.update_frame_light_round("frame.webm")

    assert ("mute", False, True) in events
    assert events.index(("mute", False, True)) < events.index("play")
    assert frame_round.state.controls.light_muted is False


def test_skip_to_frame_answer_uses_shared_answer_start(monkeypatch):
    calls = []
    monkeypatch.setattr(frame_round, "frame_light_round_started", True)
    monkeypatch.setattr(frame_round, "frame_light_round_frame_index", 2)
    monkeypatch.setattr(
        frame_round,
        "start_frame_light_round_answer",
        lambda: calls.append("answer"),
    )

    assert transport.skip_to_lightning_answer() is True
    assert frame_round.frame_light_round_frame_index == 4
    assert calls == ["answer"]


def test_failed_lightning_stream_uses_theme_fallback(monkeypatch):
    calls = []
    filename = "round.webm"
    source_url = "https://www.youtube.com/watch?v=abcdefghijk"
    monkeypatch.setattr(
        lightning_manager.state.playback, "currently_playing", {"filename": filename}
    )
    monkeypatch.setattr(
        lightning_manager.state.lightning, "light_round_start_time", 7.25
    )
    monkeypatch.setattr(
        lightning_manager.streaming,
        "currently_streaming",
        ["Clip", source_url, "Channel"],
    )
    monkeypatch.setattr(
        lightning_manager.variety_round, "variety_light_mode_enabled", False
    )
    monkeypatch.setattr(
        lightning_manager.streaming,
        "fallback_to_theme",
        lambda start: calls.append(("fallback", start)) or True,
    )
    monkeypatch.setattr(
        lightning_manager.audio_toggles,
        "toggle_mute",
        lambda muted=None, lightning=False: calls.append(
            ("mute", muted, lightning)
        ),
    )
    monkeypatch.setattr(
        lightning_manager.round_start_guard,
        "after",
        lambda delay, callback, *args: calls.append(
            ("after", delay, callback, args)
        ),
    )

    assert lightning_manager._fallback_failed_lightning_stream(filename) is True

    assert calls[0] == ("fallback", 7.25)
    assert calls[1] == ("mute", False, False)
    assert calls[2][0:2] == ("after", 500)
    assert calls[2][2] is lightning_manager.blind_screen.set_black_screen
    assert calls[2][3] == (False,)


def test_prefetched_download_must_be_complete_when_download_is_required(
    monkeypatch,
):
    source_url = "https://www.youtube.com/watch?v=abcdefghijk"
    cache_path = "youtube/cache/abcdefghijk.mp4"
    monkeypatch.setattr(
        lightning_manager.youtube_control,
        "_get_yt_cache_path",
        lambda _url: cache_path,
    )
    monkeypatch.setattr(
        lightning_manager.os.path,
        "exists",
        lambda path: path == cache_path + ".part",
    )
    monkeypatch.setitem(
        lightning_manager.youtube_control._cached_streams,
        source_url,
        ("https://video.example/track", 120, "Clip", "Channel"),
    )

    assert (
        lightning_manager._prefetched_youtube_media_ready(
            source_url, require_download=True
        )
        is False
    )
    assert (
        lightning_manager._prefetched_youtube_media_ready(
            source_url, require_download=False
        )
        is True
    )


def test_variety_unavailable_youtube_media_selects_another_type(monkeypatch):
    selections = []
    monkeypatch.setattr(
        lightning_manager.variety_round, "variety_light_mode_enabled", True
    )
    monkeypatch.setattr(lightning_manager.state.lightning, "fixed_current_round", None)
    monkeypatch.setattr(lightning_manager.state.lightning, "light_mode", "clip")
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "clip"
    )
    monkeypatch.setattr(lightning_manager.state.lightning, "light_round_started", True)
    monkeypatch.setattr(lightning_manager.state.lightning, "light_round_armed", False)
    monkeypatch.setattr(
        lightning_manager.state.lightning, "light_round_start_time", 11.0
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"title": {"length": 9}},
    )

    def choose_fallback(excluded_modes):
        selections.append(excluded_modes)
        lightning_manager.state.lightning.light_mode = "title"
        return "title", False

    monkeypatch.setattr(
        lightning_manager.variety_round,
        "set_variety_light_mode",
        choose_fallback,
    )
    monkeypatch.setattr(lightning_manager, "lightning_queue", ["round.webm", "clip"])

    assert lightning_manager._select_variety_media_fallback("clip") == "title"

    assert selections == [["clip", "ost"]]
    assert lightning_manager.lightning_queue is None
    assert lightning_manager.state.lightning.current_light_mode is None
    assert lightning_manager.state.lightning.light_round_started is False
    assert lightning_manager.state.lightning.light_round_armed is True
    assert lightning_manager.state.lightning.light_round_start_time == 11.0
    assert lightning_manager.state.lightning.light_round_length == 9
