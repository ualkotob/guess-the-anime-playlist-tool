"""Web-host persistence coverage for buzzer pause and answer timer settings."""

import copy
from types import SimpleNamespace

from core.game_state import state
from _app_scripts.file.web_server import web_client_html, web_host_actions
from _app_scripts.ui import menu_registry


# Importing the lightweight embedded client first matches the app's web-module
# initialization order and avoids pulling the large bonus graph in isolation.
assert web_client_html.HTML
bonus = web_host_actions.bonus


def test_web_buzzer_settings_update_active_selected_preset(monkeypatch):
    active = copy.deepcopy(bonus.BONUS_SETTINGS_DEFAULT)
    saved = {"Game Night": copy.deepcopy(bonus.BONUS_SETTINGS_DEFAULT)}
    monkeypatch.setattr(state.playback, "bonus_settings", active)
    monkeypatch.setattr(state.settings_presets, "selected_bonus_settings", "Game Night")
    monkeypatch.setattr(state.settings_presets, "saved_bonus_settings", saved)
    monkeypatch.setattr(state.widgets, "root", SimpleNamespace(after=lambda _delay, fn: fn()))

    saves = []
    pushes = []
    resets = []
    monkeypatch.setattr(web_host_actions.config_io, "save_config", lambda: saves.append(True))
    monkeypatch.setattr(web_host_actions.bonus_answers, "_push_web_toggles", lambda: pushes.append(True))
    monkeypatch.setattr(web_host_actions.buzz, "reset_answer_queue", lambda: resets.append(True))

    web_host_actions._handle_host_action(
        "set_buzzer_pause", {"enabled": True}
    )
    web_host_actions._handle_host_action(
        "set_buzzer_timer", {"seconds": 15}
    )

    assert active["buzzer"]["pause_on_buzz"] is True
    assert active["buzzer"]["answer_timer_seconds"] == 15
    assert saved["Game Night"]["buzzer"]["pause_on_buzz"] is True
    assert saved["Game Night"]["buzzer"]["answer_timer_seconds"] == 15
    assert len(saves) == 2
    assert len(pushes) == 2
    assert resets == []

    web_host_actions._handle_host_action(
        "set_buzzer_timer", {"seconds": 0}
    )

    assert resets == [True]


def test_desktop_bonus_menu_contains_buzzer_pause_and_timer():
    ids = {
        item.get("id")
        for item in menu_registry.get_menu_registry()["bonus"]
        if isinstance(item, dict)
    }

    assert {"buzzer_pause", "buzzer_timer"} <= ids
