"""Coverage for the Bz Multi toggle: players re-buzz once their buzz is served."""

import copy
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts.file.web_server import web_client_html, web_host_actions
from _app_scripts.file.web_server import web_server as ws
from _app_scripts.ui import menu_registry


# Importing the lightweight embedded client first matches the app's web-module
# initialization order and avoids pulling the large bonus graph in isolation.
assert web_client_html.HTML
bonus = web_host_actions.bonus
bonus_answers = web_host_actions.bonus_answers

COOLDOWN = ws._BUZZ_REBUZZ_COOLDOWN_MS


class _FakeSocketIO:
    def __init__(self):
        self.emits = []

    def emit(self, event, payload=None, to=None):
        self.emits.append((event, payload, to))


@pytest.fixture(autouse=True)
def isolate_buzzer_state(monkeypatch):
    monkeypatch.setattr(ws, "_current_question", {"buzzer_only": True})
    monkeypatch.setattr(ws, "_submitted_answers", [])
    monkeypatch.setattr(ws, "_submitted_sids", set())
    monkeypatch.setattr(ws, "_pending_selections", {})
    monkeypatch.setattr(ws, "_buzzer_open", True)
    monkeypatch.setattr(ws, "_buzzer_locked", False)
    monkeypatch.setattr(ws, "_buzzer_opened_at_ms", 0)
    monkeypatch.setattr(ws, "_buzzer_multi_buzz", False)
    monkeypatch.setattr(ws, "_buzz_pending", {})
    monkeypatch.setattr(ws, "_buzz_last_press_ms", {})
    monkeypatch.setattr(ws, "_on_buzzer_reset_callback", None)


def _names():
    return [a["name"] for a in ws._submitted_answers]


# ---------------------------------------------------------------------------
# Server buzz gate
# ---------------------------------------------------------------------------

def test_single_buzz_mode_still_allows_one_buzz_per_player():
    assert ws._accept_buzz("Alice", 1000)[0] == 1
    assert ws._accept_buzz("Bob", 1100)[0] == 2
    ws.release_buzz("Alice", ws._buzz_pending["Alice"])

    assert ws._accept_buzz("Alice", 1000 + COOLDOWN * 10) is None
    assert _names() == ["Alice", "Bob"]


def test_multi_buzz_waits_for_release_then_requeues_player():
    ws.set_multi_buzz(True)
    rank, answer, alice_id = ws._accept_buzz("Alice", 1000)
    assert (rank, answer) == (1, "[#1] 1000 ms")
    ws._accept_buzz("Bob", 1200)

    # Still unserved: blocked even after the cooldown has passed.
    assert ws._accept_buzz("Alice", 1000 + COOLDOWN + 1) is None

    ws.release_buzz("Alice", alice_id)
    rank, _answer, second_id = ws._accept_buzz("Alice", 1000 + COOLDOWN + 1)

    assert rank == 3
    assert second_id != alice_id
    assert _names() == ["Alice", "Bob", "Alice"]


def test_multi_buzz_cooldown_blocks_fast_rebuzz():
    ws.set_multi_buzz(True)
    _rank, _answer, buzz_id = ws._accept_buzz("Alice", 1000)
    ws.release_buzz("Alice", buzz_id)

    assert ws._accept_buzz("Alice", 1000 + COOLDOWN - 1) is None
    assert ws._accept_buzz("Alice", 1000 + COOLDOWN) is not None


def test_stale_release_does_not_free_a_newer_buzz():
    ws.set_multi_buzz(True)
    _rank, _answer, old_id = ws._accept_buzz("Alice", 1000)
    ws.control_buzzer("reset")
    _rank, _answer, new_id = ws._accept_buzz("Alice", 1100)

    ws.release_buzz("Alice", old_id)

    assert ws._buzz_pending == {"Alice": new_id}


def test_reset_clears_pending_and_cooldown():
    ws.set_multi_buzz(True)
    ws._accept_buzz("Alice", 1000)

    ws.control_buzzer("reset")

    assert ws._buzz_pending == {}
    assert ws._accept_buzz("Alice", 1001)[0] == 1


def test_enabling_multi_buzz_mid_round_respects_unserved_buzz():
    ws._accept_buzz("Alice", 1000)
    ws.set_multi_buzz(True)

    assert ws._accept_buzz("Alice", 1000 + COOLDOWN) is None


def test_buzzer_state_reports_multi_buzz_and_pending(monkeypatch):
    sock = _FakeSocketIO()
    monkeypatch.setattr(ws, "_socketio", sock)
    monkeypatch.setattr(ws, "FLASK_AVAILABLE", True)

    ws.set_multi_buzz(True)
    _rank, _answer, buzz_id = ws._accept_buzz("Alice", 1000)
    ws._emit_buzzer_state()
    pending_payload = sock.emits[-1][1]
    ws.release_buzz("Alice", buzz_id)
    released_payload = sock.emits[-1][1]

    assert pending_payload["multi_buzz"] is True
    assert pending_payload["pending_names"] == ["Alice"]
    assert pending_payload["rebuzz_cooldown_ms"] == COOLDOWN
    assert released_payload["pending_names"] == []


def test_remove_answer_entry_removes_only_matching_buzz(monkeypatch):
    monkeypatch.setattr(ws, "_socketio", _FakeSocketIO())
    monkeypatch.setattr(ws, "FLASK_AVAILABLE", True)
    ws._submitted_answers[:] = [
        {"name": "Alice", "answer": "[#1] 100 ms"},
        {"name": "Bob", "answer": "[#2] 200 ms"},
        {"name": "Alice", "answer": "[#3] 900 ms"},
    ]

    ws.remove_answer_entry("Alice", "[#3] 900 ms")

    assert ws._submitted_answers == [
        {"name": "Alice", "answer": "[#1] 100 ms"},
        {"name": "Bob", "answer": "[#2] 200 ms"},
    ]


# ---------------------------------------------------------------------------
# Host-side release points (buzz.py)
# ---------------------------------------------------------------------------

class _FakeRoot:
    def after(self, _delay, _callback):
        return 1

    def after_cancel(self, _callback_id):
        pass


@pytest.fixture
def buzz_module(monkeypatch):
    """Load buzz.py with a light bonus stub to avoid unrelated app imports."""
    bonus_stub = ModuleType("_app_scripts.bonus.bonus")
    bonus_stub.BONUS_SETTINGS_DEFAULT = {"buzzer": {"player_buzz_popup_properties": {}}}
    bonus_package = importlib.import_module("_app_scripts.bonus")
    monkeypatch.setattr(bonus_package, "bonus", bonus_stub, raising=False)
    monkeypatch.setitem(sys.modules, "_app_scripts.bonus.bonus", bonus_stub)
    path = Path(__file__).parents[1] / "_app_scripts" / "bonus" / "buzz.py"
    spec = importlib.util.spec_from_file_location("_buzzer_multi_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.state.widgets, "root", _FakeRoot(), raising=False)
    monkeypatch.setattr(module.web_server, "push_timer", lambda *_a, **_k: None)
    monkeypatch.setattr(module.web_server, "clear_timer", lambda: None)
    released = []
    monkeypatch.setattr(module.web_server, "release_buzz",
                        lambda name, buzz_id: released.append((name, buzz_id)))
    module._released = released
    return module


def _use_settings(monkeypatch, buzz, **settings):
    base = {"pause_on_buzz": False, "answer_timer_seconds": 10, "player_buzz_popup": False}
    base.update(settings)
    monkeypatch.setattr(buzz, "_buzzer_settings", lambda: base)


def test_timed_queue_releases_buzz_when_turn_ends(monkeypatch, buzz_module):
    buzz = buzz_module
    _use_settings(monkeypatch, buzz)

    buzz._enqueue_timed_buzz(1, "Alice", 11)
    buzz._enqueue_timed_buzz(2, "Bob", 12)
    assert buzz._released == []

    buzz._advance_answer_queue_main()
    assert buzz._released == [("Alice", 11)]

    buzz._reset_answer_queue_main()
    assert buzz._released == [("Alice", 11), ("Bob", 12)]


def test_untimed_buzz_is_released_immediately(monkeypatch, buzz_module):
    buzz = buzz_module
    _use_settings(monkeypatch, buzz, answer_timer_seconds=0)

    buzz._handle_buzz_ui(1, "Alice", buzz.time.monotonic(), 21)

    assert buzz._released == [("Alice", 21)]


def test_sound_preview_has_nothing_to_release(monkeypatch, buzz_module):
    buzz = buzz_module
    monkeypatch.setattr(buzz.threading, "Thread", lambda **_k: SimpleNamespace(start=lambda: None))

    buzz._play_buzz_sound(1, "Test")

    assert buzz._released == []


# ---------------------------------------------------------------------------
# Setting persistence, menus, and desktop answer list
# ---------------------------------------------------------------------------

def test_web_buzzer_multi_updates_preset_and_server(monkeypatch):
    active = copy.deepcopy(bonus.BONUS_SETTINGS_DEFAULT)
    saved = {"Game Night": copy.deepcopy(bonus.BONUS_SETTINGS_DEFAULT)}
    monkeypatch.setattr(state.playback, "bonus_settings", active)
    monkeypatch.setattr(state.settings_presets, "selected_bonus_settings", "Game Night")
    monkeypatch.setattr(state.settings_presets, "saved_bonus_settings", saved)
    monkeypatch.setattr(state.widgets, "root", SimpleNamespace(after=lambda _delay, fn: fn()))
    monkeypatch.setattr(web_host_actions.config_io, "save_config", lambda: None)
    monkeypatch.setattr(web_host_actions.bonus_answers, "_push_web_toggles", lambda: None)

    assert active["buzzer"]["multi_buzz"] is False

    web_host_actions._handle_host_action("set_buzzer_multi", {"enabled": True})

    assert active["buzzer"]["multi_buzz"] is True
    assert saved["Game Night"]["buzzer"]["multi_buzz"] is True
    assert ws._buzzer_multi_buzz is True


def test_bz_multi_is_in_desktop_menu_and_web_controls():
    ids = {
        item.get("id")
        for item in menu_registry.get_menu_registry()["bonus"]
        if isinstance(item, dict)
    }
    assert "buzzer_multi" in ids

    html = web_client_html.HTML
    assert 'data-extra-id="buzz_multi"' in html
    assert "set_buzzer_multi" in html
    assert "pending_names" in html


def test_remove_pending_answer_exact_or_all(monkeypatch):
    pending = [
        {"name": "Alice", "answer": "[#1] 100 ms"},
        {"name": "Bob", "answer": "[#2] 200 ms"},
        {"name": "Alice", "answer": "[#3] 900 ms"},
    ]
    monkeypatch.setattr(bonus, "_pending_bonus_answers", pending)

    assert bonus_answers._remove_pending_answer("Alice", "[#3] 900 ms") is True
    assert [e["answer"] for e in pending] == ["[#1] 100 ms", "[#2] 200 ms"]
    assert bonus_answers._remove_pending_answer("Alice", "[#9] 0 ms") is False

    assert bonus_answers._remove_pending_answer("Alice") is True
    assert pending == [{"name": "Bob", "answer": "[#2] 200 ms"}]
