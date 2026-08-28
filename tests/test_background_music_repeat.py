"""Regression tests for background-music repeat protection."""

import copy

import pytest

from core.game_state import state
from _app_scripts.playback import music
from _app_scripts.queue_round.lightning_rounds import lightning_settings


@pytest.fixture(autouse=True)
def _restore_music_state():
    old_playlist = copy.deepcopy(state.metadata.playlist)
    old_settings = copy.deepcopy(state.playback.lightning_mode_settings)
    old_files = list(music.music_files)
    old_index = music.current_music_index
    old_changed = music.music_changed
    yield
    state.metadata.playlist.clear()
    state.metadata.playlist.update(old_playlist)
    state.playback.lightning_mode_settings.clear()
    state.playback.lightning_mode_settings.update(old_settings)
    music.music_files[:] = old_files
    music.current_music_index = old_index
    music.music_changed = old_changed


def _set_library(names, history=(), current_index=0, percent=50):
    music.music_files[:] = [f"C:/music/{name}" for name in names]
    music.current_music_index = current_index
    music.music_changed = False
    state.metadata.playlist.clear()
    state.metadata.playlist.update(
        playlist=[],
        current_index=-1,
        background_track_history=list(history),
    )
    state.playback.lightning_mode_settings.clear()
    state.playback.lightning_mode_settings.update(
        {"_misc_settings": {"background_music": {
            "repeat_after_percent": percent
        }}}
    )


def test_repeat_protection_defaults_to_existing_fifty_percent():
    background = lightning_settings.lightning_mode_settings_default[
        "_misc_settings"
    ]["background_music"]

    assert background["repeat_after_percent"] == 50
    state.playback.lightning_mode_settings.clear()
    assert music.get_repeat_protection_count(5) == 2


def test_old_lightning_settings_gain_repeat_protection_default():
    settings = lightning_settings.update_lightning_mode_settings(
        {"_misc_settings": {"background_music": {"rounds_per_track": 4}}}
    )

    assert settings["_misc_settings"]["background_music"][
        "repeat_after_percent"
    ] == 50


@pytest.mark.parametrize(
    ("percent", "expected"),
    [(0, 0), (25, 2), (50, 5), (75, 7), (100, 9)],
)
def test_repeat_percentage_maps_to_bounded_cooldown(percent, expected):
    _set_library([f"{i}.mp3" for i in range(10)], percent=percent)

    assert music.get_repeat_protection_count(10) == expected


def test_next_track_skips_recent_distinct_tracks():
    _set_library(
        ["a.mp3", "b.mp3", "c.mp3", "d.mp3"],
        history=["b.mp3", "c.mp3", "b.mp3"],
        current_index=0,
        percent=50,
    )

    music.next_background_track()

    assert music.current_music_index == 3
    assert music.music_changed is True


def test_history_entries_for_removed_music_do_not_consume_protection():
    _set_library(
        ["a.mp3", "b.mp3", "c.mp3", "d.mp3"],
        history=["removed.mp3", "b.mp3"],
        current_index=0,
        percent=50,
    )

    music.next_background_track()

    assert music.current_music_index == 2


def test_one_hundred_percent_cycles_every_other_track_before_repeat():
    _set_library(
        ["a.mp3", "b.mp3", "c.mp3", "d.mp3"],
        history=["a.mp3", "b.mp3", "c.mp3", "d.mp3"],
        current_index=3,
        percent=100,
    )

    music.next_background_track()

    assert music.current_music_index == 0


def test_recorded_history_is_bounded_but_supports_later_percentage_changes():
    _set_library(
        ["a.mp3", "b.mp3", "c.mp3"],
        history=["old.mp3", "a.mp3", "b.mp3"],
        percent=25,
    )

    music.record_background_track_usage("C:/music/c.mp3")

    assert state.metadata.playlist["background_track_history"] == [
        "a.mp3", "b.mp3", "c.mp3"
    ]
