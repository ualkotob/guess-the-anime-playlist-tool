import pytest

from _app_scripts.playback import transport
from _app_scripts.queue_round.lightning_rounds import lightning_manager


class _PlayingPlayer:
    def is_playing(self):
        return True


def _configure_normal_answer_tick(monkeypatch):
    lightning = lightning_manager.state.lightning
    playback = lightning_manager.state.playback

    monkeypatch.setattr(lightning_manager.state.widgets, "player", _PlayingPlayer())
    monkeypatch.setattr(lightning, "light_round_start_time", 10)
    monkeypatch.setattr(lightning, "light_round_length", 5)
    monkeypatch.setattr(lightning, "light_round_answer_length", 10)
    monkeypatch.setattr(lightning, "light_round_started", True)
    monkeypatch.setattr(lightning, "light_answer_wall_start", None)
    monkeypatch.setattr(lightning, "light_answer_last_tick", None)
    monkeypatch.setattr(lightning, "light_blind_one_second_count", None)
    monkeypatch.setattr(lightning, "_showed_lightning_answer", False)
    monkeypatch.setattr(lightning, "character_round_answer", None)
    monkeypatch.setattr(lightning, "fixed_current_round", None)
    monkeypatch.setattr(lightning, "fixed_lightning_round_playlist_data", None)
    monkeypatch.setattr(lightning, "light_mode", "title")
    monkeypatch.setattr(playback, "currently_playing", {"filename": "theme.webm"})
    monkeypatch.setattr(
        playback,
        "lightning_mode_settings",
        {"blind": {"length": 5}},
    )
    monkeypatch.setattr(lightning_manager.streaming, "currently_streaming", None)
    monkeypatch.setattr(lightning_manager.streaming, "last_streamed", [None] * 4)
    monkeypatch.setattr(lightning_manager.cover_image_overlay, "light_cover_image", None)
    monkeypatch.setattr(lightning_manager.cover_image_overlay, "last_image_source", [None, None])
    monkeypatch.setattr(lightning_manager.trivia_round, "light_trivia_answer", None)
    monkeypatch.setattr(lightning_manager.mismatch_round, "mismatch_visuals", None)
    monkeypatch.setattr(lightning_manager, "_wall_time", lambda: 100)
    monkeypatch.setattr(
        lightning_manager.information_popup, "toggle_title_popup", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        lightning_manager.blind_screen, "set_black_screen", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(lightning_manager, "update_light_round_number", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lightning_manager.osd_text, "set_countdown", lambda *_args, **_kwargs: None)


def test_failed_answer_cleanup_is_retried(monkeypatch):
    _configure_normal_answer_tick(monkeypatch)
    cleanup_calls = []

    def fail_once(*_args, **_kwargs):
        cleanup_calls.append(None)
        if len(cleanup_calls) == 1:
            raise RuntimeError("transient cleanup failure")

    monkeypatch.setattr(lightning_manager, "clean_up_light_round", fail_once)

    with pytest.raises(RuntimeError, match="transient cleanup failure"):
        lightning_manager.update_light_round(15.1)

    assert lightning_manager.state.lightning._showed_lightning_answer is False

    lightning_manager.update_light_round(15.1)

    assert len(cleanup_calls) == 2
    assert lightning_manager.state.lightning._showed_lightning_answer is True


def test_paused_playback_still_ticks_active_answer_timer(monkeypatch):
    calls = []

    class PausedPlayer:
        def is_playing(self):
            return False

        def get_time(self):
            return 15_100

        def get_length(self):
            return 120_000

    class Root:
        def after(self, *_args):
            pass

    monkeypatch.setattr(transport.state.widgets, "player", PausedPlayer())
    monkeypatch.setattr(transport.state.widgets, "root", Root())
    monkeypatch.setattr(transport.state.widgets, "seek_bar", object(), raising=False)
    monkeypatch.setattr(transport.state.seek, "last_player_time", 15_100)
    monkeypatch.setattr(transport.state.seek, "projected_player_time", 15_100)
    monkeypatch.setattr(transport.state.seek, "web_playback_counter", 0)
    monkeypatch.setattr(
        transport.state.lightning, "light_answer_wall_start", 100.0
    )
    monkeypatch.setattr(
        transport.lightning_manager,
        "update_light_round",
        lambda time: calls.append(time),
    )
    monkeypatch.setattr(transport.web_server, "is_running", lambda: False)

    transport.update_seek_bar()

    assert calls == [15.1]


def test_answer_timer_excludes_time_spent_paused(monkeypatch):
    class Player:
        playing = False

        def is_playing(self):
            return self.playing

    player = Player()
    transition_calls = []
    wall_times = iter([105.0, 106.0])
    lightning = lightning_manager.state.lightning

    monkeypatch.setattr(lightning_manager.state.widgets, "player", player)
    monkeypatch.setattr(lightning, "light_round_start_time", 10)
    monkeypatch.setattr(lightning, "light_round_length", 5)
    monkeypatch.setattr(lightning, "light_round_answer_length", 3)
    monkeypatch.setattr(lightning, "light_round_started", True)
    monkeypatch.setattr(lightning, "light_answer_wall_start", 100.0)
    monkeypatch.setattr(lightning, "light_answer_last_tick", 100.0)
    monkeypatch.setattr(lightning, "light_blind_one_second_count", None)
    monkeypatch.setattr(lightning, "_showed_lightning_answer", True)
    monkeypatch.setattr(lightning, "fixed_lightning_round_playlist_data", None)
    monkeypatch.setattr(lightning, "light_mode", "title")
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"blind": {"length": 5}},
    )
    monkeypatch.setattr(lightning_manager.streaming, "currently_streaming", None)
    monkeypatch.setattr(lightning_manager, "_wall_time", lambda: next(wall_times))
    monkeypatch.setattr(
        lightning_manager, "light_round_transition", lambda: transition_calls.append(True)
    )
    monkeypatch.setattr(
        lightning_manager.osd_text, "set_countdown", lambda *_args, **_kwargs: None
    )

    lightning_manager.update_light_round(15.1)
    player.playing = True
    lightning_manager.update_light_round(15.1)

    assert lightning.light_answer_wall_start == 105.0
    assert transition_calls == []


def test_resuming_ticks_answer_timer_before_player_starts(monkeypatch):
    events = []

    class PausedPlayer:
        def is_playing(self):
            return False

        def get_media(self):
            return "theme.webm"

        def get_time(self):
            return 15_100

        def play(self):
            events.append("play")

    player = PausedPlayer()
    monkeypatch.setattr(transport.state.widgets, "player", player)
    monkeypatch.setattr(transport.frame_round, "frame_light_round_started", False)
    monkeypatch.setattr(transport.state.lightning, "light_mode", None)
    monkeypatch.setattr(
        transport.state.lightning, "light_answer_wall_start", 100.0
    )
    monkeypatch.setattr(
        transport.lightning_manager,
        "update_light_round",
        lambda time: events.append(("timer", time)),
    )
    monkeypatch.setattr(
        transport.playpause_icon,
        "_show_playpause_icon",
        lambda paused: events.append(("icon", paused)),
    )

    transport.play_pause()

    assert events[:2] == [("timer", 15.1), "play"]
