from types import SimpleNamespace

from core.game_state import state
from _app_scripts.data import config_io
from _app_scripts.file import scoreboard_control
from _app_scripts.file.web_server import web_host_actions
from _app_scripts.playback import transport


def test_sync_scoreboard_colors_setting_defaults_on():
    setting = next(
        item
        for item in config_io.SETTINGS_SCHEMA
        if item["key"] == "SYNC_SCOREBOARD_COLORS"
    )

    assert setting["default"] is True
    assert setting["requires_scoreboard"] is True
    assert setting["label"] == "Sync Scoreboard Colors:"


def test_theme_colors_are_reapplied_only_when_enabled(monkeypatch):
    sent = []
    monkeypatch.setattr(state.colors, "OVERLAY_BACKGROUND_COLOR", "navy")
    monkeypatch.setattr(state.colors, "OVERLAY_TEXT_COLOR", "gold")
    monkeypatch.setattr(
        transport.scoreboard_control,
        "send_colors",
        lambda bg, text: sent.append((bg, text)),
    )

    monkeypatch.setattr(state.config, "SYNC_SCOREBOARD_COLORS", True)
    transport._sync_scoreboard_theme_colors()
    monkeypatch.setattr(state.config, "SYNC_SCOREBOARD_COLORS", False)
    transport._sync_scoreboard_theme_colors()

    assert sent == [("navy", "gold")]


def test_scoreboard_color_sender_never_sends_when_sync_is_disabled(monkeypatch):
    sent = []
    monkeypatch.setattr(state.config, "SYNC_SCOREBOARD_COLORS", False)
    monkeypatch.setattr(scoreboard_control, "send_command", sent.append)

    result = scoreboard_control.send_colors("navy", "gold")

    assert result is False
    assert sent == []


def test_first_scoreboard_connection_does_not_sync_colors_when_disabled(monkeypatch):
    color_calls = []

    class _Socket:
        def connect(self, _address):
            pass

        def sendall(self, _payload):
            pass

        def close(self):
            pass

    class _ImmediateThread:
        def __init__(self, target, daemon):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(state.config, "SYNC_SCOREBOARD_COLORS", False)
    monkeypatch.setattr(scoreboard_control, "_colors_sent", False)
    monkeypatch.setattr(scoreboard_control.socket, "socket", _Socket)
    monkeypatch.setattr(scoreboard_control.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        scoreboard_control,
        "send_colors",
        lambda: color_calls.append(True),
    )

    scoreboard_control.send_command("show")

    assert color_calls == []
    assert scoreboard_control._colors_sent is False


def test_scoreboard_color_sender_sends_when_sync_is_enabled(monkeypatch):
    sent = []
    monkeypatch.setattr(state.config, "SYNC_SCOREBOARD_COLORS", True)
    monkeypatch.setattr(scoreboard_control, "send_command", sent.append)

    result = scoreboard_control.send_colors("navy", "gold")

    assert result is True
    assert sent == ["[COLORS][BACK]navy[TEXT]gold"]


def test_web_host_volume_accepts_values_above_100(monkeypatch):
    applied = []
    monkeypatch.setattr(
        state.widgets,
        "root",
        SimpleNamespace(after=lambda _delay, callback: callback()),
    )
    monkeypatch.setattr(
        web_host_actions.audio_toggles,
        "set_volume",
        lambda value: applied.append(value),
    )

    web_host_actions._handle_host_action("set_volume", {"volume": 175})

    assert applied == [175]
