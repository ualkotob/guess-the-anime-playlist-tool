"""Regression coverage for manually muting an active reveal round."""

from core.game_state import state
from _app_scripts.toggles import audio_toggles


class _Player:
    def __init__(self):
        self.mute_calls = []

    def audio_set_mute(self, muted):
        self.mute_calls.append(muted)


def test_manual_mute_changes_reveal_badge(monkeypatch):
    player = _Player()
    badge_states = []
    monkeypatch.setattr(state.widgets, "player", player)
    monkeypatch.setattr(state.lightning, "light_mode", None)
    monkeypatch.setattr(state.lightning, "light_round_started", False)
    monkeypatch.setattr(state.controls, "disable_video_audio", False)
    monkeypatch.setattr(audio_toggles.music, "music_loaded", False)
    monkeypatch.setattr(
        audio_toggles,
        "_sync_reveal_mute_badge",
        lambda muted: badge_states.append(muted),
    )

    audio_toggles.toggle_mute(True)
    audio_toggles.toggle_mute(False)

    assert player.mute_calls == [True, False]
    assert badge_states == [True, False]


def test_badge_sync_only_draws_during_reveal(monkeypatch):
    from _app_scripts.playback import osd_text
    from _app_scripts.queue_round.lightning_rounds import peek_dispatch

    badge_states = []
    monkeypatch.setattr(
        osd_text, "set_countdown_muted", lambda muted: badge_states.append(muted)
    )
    monkeypatch.setattr(peek_dispatch, "is_peek_active", lambda: False)

    audio_toggles._sync_reveal_mute_badge(True)
    assert badge_states == []

    monkeypatch.setattr(peek_dispatch, "is_peek_active", lambda: True)
    audio_toggles._sync_reveal_mute_badge(True)
    audio_toggles._sync_reveal_mute_badge(False)
    assert badge_states == [True, False]
