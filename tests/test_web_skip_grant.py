"""Regression coverage for name-based, reconnectable web skip grants."""

import pytest

from _app_scripts.file.web_server import web_client_html, web_server


class RecordingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, data, to=None):
        self.events.append((event, data, to))


@pytest.fixture(autouse=True)
def isolate_skip_grant(monkeypatch):
    socket = RecordingSocket()
    monkeypatch.setattr(web_server, "_socketio", socket)
    monkeypatch.setattr(web_server, "_connected_players", {})
    monkeypatch.setattr(web_server, "_host_sids", set())
    monkeypatch.setattr(web_server, "_skip_grant_player", "")
    monkeypatch.setattr(web_server, "_on_skip_grant_callback", None)
    return socket


def test_offline_player_can_hold_skip_grant(isolate_skip_grant):
    web_server.push_skip_grant("Offline Player")

    assert web_server.get_skip_grant_player() == "Offline Player"
    assert (
        "skip_grant_host_update",
        {"name": "Offline Player"},
        None,
    ) in isolate_skip_grant.events


@pytest.mark.parametrize(
    ("name", "active"),
    [("Offline Player", True), ("Someone Else", False)],
)
def test_grant_state_is_delivered_after_player_identifies(
    isolate_skip_grant, monkeypatch, name, active
):
    monkeypatch.setattr(web_server, "_skip_grant_player", "Offline Player")

    web_server._sync_skip_grant_for_player("player-sid", name)

    assert isolate_skip_grant.events[-1] == (
        "skip_grant_update",
        {"active": active},
        "player-sid",
    )


def test_scoreboard_exposes_drag_drop_and_offline_skip_controls():
    html = web_client_html.HTML

    assert "_scEnablePlayerTeamDrag(row, p)" in html
    assert "_scEnableTeamDrop(header, team)" in html
    assert "_scSetTeamForPlayers([playerName], team)" in html
    assert "shown only when player is connected" not in html
    assert "skipGrantBtn.style.display = _isConnectedPlayer" not in html
