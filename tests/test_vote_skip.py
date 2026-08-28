"""Regression coverage for post-reveal web vote-skipping."""

from types import SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts.file import scoreboard_control
from _app_scripts.file.web_server import web_client_html, web_host_actions, web_server


@pytest.fixture(autouse=True)
def isolate_vote_skip_state(monkeypatch):
    monkeypatch.setattr(web_server, "_socketio", None)
    monkeypatch.setattr(web_server, "_connected_players", {})
    monkeypatch.setattr(web_server, "_player_meta", {})
    monkeypatch.setattr(web_server, "_host_sids", set())
    monkeypatch.setattr(web_server, "_banned_names", set())
    monkeypatch.setattr(web_server, "_shadow_kicked_players", {})
    monkeypatch.setattr(web_server, "_shadow_kicked_ips", set())
    monkeypatch.setattr(web_server, "_info_public", False)
    monkeypatch.setattr(web_server, "_vote_skip_enabled", False)
    monkeypatch.setattr(web_server, "_vote_skip_open", False)
    monkeypatch.setattr(web_server, "_vote_skip_resolved", False)
    monkeypatch.setattr(web_server, "_vote_skip_epoch", 0)
    monkeypatch.setattr(web_server, "_vote_skip_votes", set())
    monkeypatch.setattr(web_server, "_on_vote_skip_changed_callback", None)
    monkeypatch.setattr(web_server, "_on_vote_skip_passed_callback", None)


def _enable_and_open():
    web_server.set_vote_skip_enabled(True)
    web_server.open_vote_skip()
    return web_server._vote_skip_epoch


def test_vote_is_unavailable_until_full_information_reveal():
    web_server._connected_players["s1"] = "One"
    web_server.set_vote_skip_enabled(True)
    epoch = web_server._vote_skip_epoch

    assert web_server.get_vote_skip_state("s1")["open"] is False
    assert web_server.submit_vote_skip("s1", True, epoch) is False

    web_server.set_info_public(True)

    assert web_server.get_vote_skip_state("s1")["open"] is True


def test_strict_majority_passes_once_and_supports_withdrawal():
    web_server._connected_players.update({
        "s1": "One", "s2": "Two", "s3": "Three", "s4": "Four",
    })
    passed = []
    changes = []
    web_server.set_vote_skip_passed_callback(lambda: passed.append("passed"))
    web_server.set_vote_skip_changed_callback(
        lambda name, voted: changes.append((name, voted))
    )
    epoch = _enable_and_open()

    assert web_server.get_vote_skip_state("s1")["required"] == 3
    assert web_server.submit_vote_skip("s1", True, epoch) is True
    assert web_server.submit_vote_skip("s1", False, epoch) is True
    assert web_server.submit_vote_skip("s1", True, epoch) is True
    assert web_server.submit_vote_skip("s2", True, epoch) is True
    assert passed == []

    assert web_server.submit_vote_skip("s3", True, epoch) is True
    assert passed == ["passed"]
    assert web_server.get_vote_skip_state("s1")["resolved"] is True
    assert web_server.submit_vote_skip("s4", True, epoch) is False
    assert passed == ["passed"]
    assert changes[-1] == ("Three", True)


def test_duplicate_devices_count_once_and_hosts_and_bans_do_not_count():
    web_server._connected_players.update({
        "s1": "One",
        "s1-duplicate": "One",
        "s2": "Two",
        "host": "Host",
        "banned": "Banned",
    })
    web_server._host_sids.add("host")
    web_server._banned_names.add("Banned")
    passed = []
    web_server.set_vote_skip_passed_callback(lambda: passed.append(True))
    epoch = _enable_and_open()

    current = web_server.get_vote_skip_state("s1")
    assert current["eligible_count"] == 2
    assert current["required"] == 2
    assert web_server.get_vote_skip_state("host")["eligible"] is False

    assert web_server.submit_vote_skip("s1", True, epoch) is True
    assert web_server.submit_vote_skip("s1-duplicate", True, epoch) is False
    assert web_server.submit_vote_skip("s2", True, epoch) is True
    assert passed == [True]


def test_theme_reset_invalidates_stale_votes_and_clears_badges():
    web_server._connected_players["s1"] = "One"
    badge_events = []
    web_server.set_vote_skip_changed_callback(
        lambda name, voted: badge_events.append((name, voted))
    )
    epoch = _enable_and_open()

    web_server.reset_vote_skip()

    assert web_server.submit_vote_skip("s1", True, epoch) is False
    assert web_server._vote_skip_votes == set()
    assert badge_events[-1] == ("", False)


def test_vote_badge_uses_existing_scoreboard_protocol(monkeypatch):
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

    web_host_actions._on_vote_skip_changed("Player", True)
    web_host_actions._on_vote_skip_changed("Player", False)
    web_host_actions._on_vote_skip_changed("", False)

    assert set_badges == [
        (("Player", "vote_skip", "⏭"), {"priority": 70})
    ]
    assert cleared == [
        ((), {"player_name": "Player", "key": "vote_skip"}),
        ((), {"key": "vote_skip"}),
    ]


def test_majority_uses_context_appropriate_end_workflow(monkeypatch):
    calls = []
    monkeypatch.setattr(
        state.widgets, "root", SimpleNamespace(after=lambda _delay, fn: fn())
    )
    monkeypatch.setattr(
        web_host_actions.web_search,
        "_invoke_registry_by_id",
        lambda item_id: calls.append(item_id),
    )
    monkeypatch.setattr(
        web_host_actions.transport, "play_next", lambda: calls.append("play_next")
    )
    monkeypatch.setattr(state.lightning, "light_round_started", False)
    monkeypatch.setattr(
        web_host_actions.frame_round, "frame_light_round_started", False
    )

    web_host_actions._on_vote_skip_passed()
    assert calls == ["skip_to_end_ff"]

    calls.clear()
    state.lightning.light_round_started = True
    web_host_actions._on_vote_skip_passed()
    assert calls == ["play_next"]


def test_vote_pane_is_in_question_view_above_emojis():
    html = web_client_html.HTML
    assert html.index('<div id="vote-skip-pane">') < html.index('<div id="emoji-bar">')

