"""Regression coverage for the per-player FIFO buzzer answer timer."""

import importlib.util
import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from _app_scripts.file.web_server import web_client_html


class _FakeRoot:
    def __init__(self):
        self.pending = {}
        self.next_id = 0

    def after(self, _delay, callback):
        self.next_id += 1
        self.pending[self.next_id] = callback
        return self.next_id

    def after_cancel(self, callback_id):
        self.pending.pop(callback_id, None)


@pytest.fixture
def buzz_module(monkeypatch):
    """Load buzz.py with a light bonus stub to avoid unrelated app imports."""
    bonus_stub = ModuleType("_app_scripts.bonus.bonus")
    bonus_stub.BONUS_SETTINGS_DEFAULT = {
        "buzzer": {
            "pause_on_buzz": False,
            "answer_timer_seconds": 10,
            "player_buzz_popup": False,
            "player_buzz_popup_properties": {"margin": 40, "gap": 10},
        }
    }
    bonus_package = importlib.import_module("_app_scripts.bonus")
    monkeypatch.setattr(bonus_package, "bonus", bonus_stub, raising=False)
    monkeypatch.setitem(sys.modules, "_app_scripts.bonus.bonus", bonus_stub)
    path = Path(__file__).parents[1] / "_app_scripts" / "bonus" / "buzz.py"
    spec = importlib.util.spec_from_file_location("_buzzer_queue_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_consecutive_buzzes_receive_full_individual_windows(monkeypatch, buzz_module):
    buzz = buzz_module
    pushed = []
    cleared = []
    root = _FakeRoot()
    monkeypatch.setattr(buzz.state.widgets, "root", root, raising=False)
    monkeypatch.setattr(
        buzz,
        "_buzzer_settings",
        lambda: {
            "pause_on_buzz": False,
            "answer_timer_seconds": 10,
            "player_buzz_popup": False,
        },
    )
    monkeypatch.setattr(
        buzz.web_server,
        "push_timer",
        lambda seconds, paused=False, **meta: pushed.append((seconds, paused, meta)),
    )
    monkeypatch.setattr(buzz.web_server, "clear_timer", lambda: cleared.append(True))

    buzz._enqueue_timed_buzz(1, "Alice")
    buzz._enqueue_timed_buzz(2, "Bob")

    assert [item["name"] for item in buzz._buzz_answer_queue] == ["Alice", "Bob"]
    assert pushed == [(10.0, False, {"player": "Alice", "rank": 1})]

    buzz._advance_answer_queue_main()

    assert [item["name"] for item in buzz._buzz_answer_queue] == ["Bob"]
    assert pushed[-1] == (10.0, False, {"player": "Bob", "rank": 2})

    buzz._advance_answer_queue_main()

    assert buzz._buzz_answer_queue == []
    assert cleared == [True]


def test_buzzer_resumes_only_the_pause_it_owns(monkeypatch, buzz_module):
    buzz = buzz_module
    player = type("Player", (), {})()
    player.playing = True
    player.is_playing = lambda: player.playing
    player.get_media = lambda: "theme.mp4"
    monkeypatch.setattr(buzz.state.widgets, "player", player, raising=False)
    monkeypatch.setattr(
        buzz,
        "_buzzer_settings",
        lambda: {"pause_on_buzz": True, "answer_timer_seconds": 10},
    )

    transport_stub = ModuleType("_app_scripts.playback.transport")
    calls = []

    def play_pause(*, source="manual"):
        calls.append(source)
        player.playing = not player.playing

    transport_stub.play_pause = play_pause
    playback_package = importlib.import_module("_app_scripts.playback")
    monkeypatch.setattr(playback_package, "transport", transport_stub, raising=False)
    monkeypatch.setitem(sys.modules, "_app_scripts.playback.transport", transport_stub)

    frame_stub = ModuleType("_app_scripts.queue_round.lightning_rounds.frame_round")
    frame_stub.frame_light_round_started = False
    frame_stub.frame_light_round_pause = False
    lightning_package = importlib.import_module("_app_scripts.queue_round.lightning_rounds")
    monkeypatch.setattr(lightning_package, "frame_round", frame_stub, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "_app_scripts.queue_round.lightning_rounds.frame_round",
        frame_stub,
    )

    buzz._pause_for_answer_queue()
    buzz._pause_for_answer_queue()

    assert calls == ["buzzer"]
    assert player.playing is False

    buzz._resume_owned_pause()

    assert calls == ["buzzer", "buzzer"]
    assert player.playing is True

    buzz._pause_for_answer_queue()
    buzz.cancel_auto_resume()
    buzz._resume_owned_pause()

    assert calls == ["buzzer", "buzzer", "buzzer"]
    assert player.playing is False


def test_waiting_card_is_replaced_by_full_active_card(monkeypatch, buzz_module):
    buzz = buzz_module
    root = _FakeRoot()
    created = []
    monkeypatch.setattr(buzz.state.widgets, "root", root, raising=False)
    monkeypatch.setattr(
        buzz,
        "_buzzer_settings",
        lambda: {
            "pause_on_buzz": False,
            "answer_timer_seconds": 10,
            "player_buzz_popup": True,
        },
    )

    def show_card(rank, name, *, active=False):
        created.append((rank, name, active))
        return {"active": active}

    monkeypatch.setattr(buzz, "_show_buzz_queue_card", show_card)
    monkeypatch.setattr(buzz, "_layout_buzz_queue_cards", lambda: None)
    monkeypatch.setattr(buzz, "_refresh_buzz_queue_cards", lambda _remaining=None: None)
    monkeypatch.setattr(buzz, "_destroy_queue_card", lambda _item: None)
    monkeypatch.setattr(buzz, "_pause_for_answer_queue", lambda: None)
    monkeypatch.setattr(buzz.web_server, "push_timer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(buzz.web_server, "clear_timer", lambda: None)

    buzz._enqueue_timed_buzz(1, "Alice")
    buzz._enqueue_timed_buzz(2, "Bob")
    buzz._advance_answer_queue_main()

    assert created == [
        (1, "Alice", True),
        (2, "Bob", False),
        (2, "Bob", True),
    ]


def test_web_client_exposes_buzzer_queue_controls_and_player_timer():
    html = web_client_html.HTML
    for extra_id in ("buzz_next", "buzz_pause", "buzz_timer"):
        assert f'data-extra-id="{extra_id}"' in html
    assert "set_buzzer_pause" in html
    assert "set_buzzer_timer" in html
    assert "slider.step = '1'" in html
    assert "slider.min = '0'" in html
    assert "slider.max = '60'" in html
    assert 'id="timer-player"' in html
