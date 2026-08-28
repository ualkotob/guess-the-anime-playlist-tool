"""Regression coverage for durable skip-decline scoreboard badges."""

import json

import pytest

from _app_scripts.file import scoreboard_control
from _app_scripts.file.web_server import web_host_actions, web_server


@pytest.fixture(autouse=True)
def _restore_skip_decline_state():
    old_callback = web_server._on_skip_decline_callback
    old_declines = set(web_server._skip_declined_players)
    yield
    web_server._on_skip_decline_callback = old_callback
    web_server._skip_declined_players.clear()
    web_server._skip_declined_players.update(old_declines)


def test_scoreboard_custom_badge_protocol_is_json_and_bounded(monkeypatch):
    commands = []
    monkeypatch.setattr(scoreboard_control, "send_command", commands.append)

    scoreboard_control.set_player_badge(
        "A [Player]", "skip_declined", "123456789", priority=500
    )

    prefix = "[PLAYER_BADGE]"
    assert commands[0].startswith(prefix)
    assert json.loads(commands[0][len(prefix):]) == {
        "player": "A [Player]",
        "key": "skip_declined",
        "text": "12345678",
        "priority": 100,
        "crossed_out": False,
    }


def test_scoreboard_badge_can_clear_one_player_or_one_status(monkeypatch):
    commands = []
    monkeypatch.setattr(scoreboard_control, "send_command", commands.append)

    scoreboard_control.clear_player_badge("Player", "skip_declined")
    scoreboard_control.clear_player_badge(key="skip_declined")

    prefix = "[PLAYER_BADGE_CLEAR]"
    assert json.loads(commands[0][len(prefix):]) == {
        "player": "Player",
        "key": "skip_declined",
    }
    assert json.loads(commands[1][len(prefix):]) == {
        "key": "skip_declined"
    }


def test_declines_are_retained_until_question_boundary():
    events = []
    web_server.set_skip_decline_callback(
        lambda name, declined: events.append((name, declined))
    )

    web_server._set_skip_declined("One", True)
    web_server._set_skip_declined("Two", True)

    assert web_server._skip_declined_players == {"One", "Two"}
    assert events == [("One", True), ("Two", True)]

    web_server._clear_skip_declines()

    assert web_server._skip_declined_players == set()
    assert events[-1] == ("", False)


def test_theme_reset_clears_skip_declines():
    events = []
    web_server.set_skip_decline_callback(
        lambda name, declined: events.append((name, declined))
    )
    web_server._set_skip_declined("One", True)

    web_server.reset_vote_skip()

    assert web_server._skip_declined_players == set()
    assert events[-1] == ("", False)


def test_reoffering_skip_removes_only_that_players_decline():
    web_server._skip_declined_players.update({"One", "Two"})

    web_server._set_skip_declined("One", False)

    assert web_server._skip_declined_players == {"Two"}


def test_skip_decline_callback_uses_generic_badge(monkeypatch):
    set_badges = []
    cleared = []
    monkeypatch.setattr(
        scoreboard_control,
        "set_player_badge",
        lambda *args, **kwargs: set_badges.append((args, kwargs)),
    )
    monkeypatch.setattr(
        scoreboard_control,
        "clear_player_badge",
        lambda *args, **kwargs: cleared.append((args, kwargs)),
    )

    web_host_actions._on_skip_declined_changed("Player", True)
    web_host_actions._on_skip_declined_changed("Player", False)
    web_host_actions._on_skip_declined_changed("", False)

    assert set_badges == [
        (
            ("Player", "skip_declined", "\u25b6\u25b6"),
            {"crossed_out": True},
        )
    ]
    assert cleared == [
        ((), {"player_name": "Player", "key": "skip_declined"}),
        ((), {"key": "skip_declined"}),
    ]


def test_locked_player_suppresses_crossed_out_skip_badge(monkeypatch):
    set_badges = []
    monkeypatch.setattr(
        web_server, "get_buzzer_disabled_names", lambda: ["Player"]
    )
    monkeypatch.setattr(
        scoreboard_control,
        "set_player_badge",
        lambda *args, **kwargs: set_badges.append((args, kwargs)),
    )

    web_host_actions._on_skip_declined_changed("Player", True)

    assert set_badges == []


def test_lock_hides_decline_badge_without_losing_web_state(monkeypatch):
    commands = []
    cleared = []
    web_server._skip_declined_players.add("Player")
    monkeypatch.setattr(scoreboard_control, "send_command", commands.append)
    monkeypatch.setattr(
        scoreboard_control,
        "clear_player_badge",
        lambda *args, **kwargs: cleared.append((args, kwargs)),
    )

    web_host_actions._on_buzzer_lock_changed("Player", True)

    assert commands == ["[BUZZER_LOCK]Player"]
    assert cleared == [
        ((), {"player_name": "Player", "key": "skip_declined"})
    ]
    assert web_server.has_skip_declined("Player") is True


def test_unlock_restores_retained_decline_badge(monkeypatch):
    commands = []
    set_badges = []
    web_server._skip_declined_players.add("Player")
    monkeypatch.setattr(scoreboard_control, "send_command", commands.append)
    monkeypatch.setattr(
        scoreboard_control,
        "set_player_badge",
        lambda *args, **kwargs: set_badges.append((args, kwargs)),
    )

    web_host_actions._on_buzzer_lock_changed("Player", False)

    assert commands == ["[BUZZER_UNLOCK]Player"]
    assert set_badges == [
        (
            ("Player", "skip_declined", "\u25b6\u25b6"),
            {"crossed_out": True},
        )
    ]


def test_unlock_does_not_invent_decline_badge(monkeypatch):
    set_badges = []
    monkeypatch.setattr(scoreboard_control, "send_command", lambda command: None)
    monkeypatch.setattr(
        scoreboard_control,
        "set_player_badge",
        lambda *args, **kwargs: set_badges.append((args, kwargs)),
    )

    web_host_actions._on_buzzer_lock_changed("Player", False)

    assert set_badges == []
