"""Tests for the pure/state-machine helpers in web_server.py.

These never start the Flask server or any socket — they exercise the
module-level state logic (IP resolution, message visibility, emoji
moderation, buzzer commands) directly.
"""

import time

import pytest

import _app_scripts.file.web_server.web_server as ws


@pytest.fixture(autouse=True)
def isolate_module_state(monkeypatch):
    """Snapshot/restore every piece of module state these tests touch."""
    monkeypatch.setattr(ws, "_host_messages", [])
    monkeypatch.setattr(ws, "_emoji_disabled_names", set())
    monkeypatch.setattr(ws, "_message_blocked_names", set())
    monkeypatch.setattr(ws, "_message_notifications_blocked_names", set())
    monkeypatch.setattr(ws, "_emoji_timeout_until", {})
    monkeypatch.setattr(ws, "_emoji_offense_level", {})
    monkeypatch.setattr(ws, "_emoji_last_offense", {})
    monkeypatch.setattr(ws, "_current_question", None)
    monkeypatch.setattr(ws, "_buzzer_open", False)
    monkeypatch.setattr(ws, "_buzzer_locked", False)
    monkeypatch.setattr(ws, "_buzzer_opened_at_ms", None)
    monkeypatch.setattr(ws, "_on_buzzer_reset_callback", None)
    monkeypatch.setattr(ws, "_timer_state", {})


# ---------------------------------------------------------------------------
# Client IP resolution (tunnel-aware)
# ---------------------------------------------------------------------------

class TestRealClientIp:
    def test_cloudflare_header_wins(self):
        environ = {
            "HTTP_CF_CONNECTING_IP": "203.0.113.7",
            "HTTP_X_FORWARDED_FOR": "198.51.100.1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        assert ws._real_client_ip(environ) == "203.0.113.7"

    def test_xff_leftmost_entry(self):
        environ = {
            "HTTP_X_FORWARDED_FOR": " 198.51.100.1 , 10.0.0.2, 10.0.0.3",
            "REMOTE_ADDR": "127.0.0.1",
        }
        assert ws._real_client_ip(environ) == "198.51.100.1"

    def test_remote_addr_fallback(self):
        assert ws._real_client_ip({"REMOTE_ADDR": "192.0.2.9"}) == "192.0.2.9"

    def test_empty_environ(self):
        assert ws._real_client_ip(None) is None
        assert ws._real_client_ip({}) is None


# ---------------------------------------------------------------------------
# Message-thread visibility (host <-> player threading)
# ---------------------------------------------------------------------------

class TestVisibleMessagesFor:
    def _seed(self):
        ws._host_messages.extend([
            {"sender": "host", "to": "", "text": "broadcast-empty"},
            {"sender": "host", "to": "all", "text": "broadcast-all"},
            {"sender": "host", "to": "alice", "text": "for-alice"},
            {"name": "alice", "text": "from-alice"},
            {"name": "bob", "text": "from-bob"},
        ])

    def test_player_sees_own_plus_broadcasts_plus_targeted(self):
        self._seed()
        texts = [m["text"] for m in ws._visible_messages_for("alice")]
        assert texts == ["broadcast-empty", "broadcast-all", "for-alice", "from-alice"]

    def test_player_does_not_see_other_players_or_their_dms(self):
        self._seed()
        texts = [m["text"] for m in ws._visible_messages_for("bob")]
        assert "from-alice" not in texts
        assert "for-alice" not in texts
        assert texts == ["broadcast-empty", "broadcast-all", "from-bob"]

    def test_empty_inbox(self):
        assert ws._visible_messages_for("anyone") == []

    def test_host_visibility_hides_blocked_player_messages(self):
        self._seed()
        ws._message_blocked_names.add("alice")
        texts = [m["text"] for m in ws._host_visible_messages()]
        assert "from-alice" not in texts
        assert "from-bob" in texts
        assert "for-alice" in texts


# ---------------------------------------------------------------------------
# Emoji moderation (progressive timeouts)
# ---------------------------------------------------------------------------

class TestEmojiModeration:
    def test_status_clean_player(self):
        status = ws._get_emoji_status("alice")
        assert status["muted"] is False
        assert status["timed_out"] is False
        assert status["remaining_ms"] == 0

    def test_status_reflects_mute_and_timeout(self):
        ws._emoji_disabled_names.add("alice")
        ws._emoji_timeout_until["alice"] = time.time() + 30
        status = ws._get_emoji_status("alice")
        assert status["muted"] is True
        assert status["timed_out"] is True
        assert 0 < status["remaining_ms"] <= 30_000

    def test_first_timeout_uses_base_duration(self):
        duration = ws._apply_emoji_timeout("alice")
        assert duration == ws._EMOJI_BASE_TIMEOUT_SECONDS
        assert ws._emoji_offense_level["alice"] == 1
        assert ws._get_emoji_status("alice")["timed_out"] is True

    def test_repeat_offenses_escalate(self):
        first = ws._apply_emoji_timeout("alice")
        second = ws._apply_emoji_timeout("alice")
        third = ws._apply_emoji_timeout("alice")
        assert first < second < third
        assert ws._emoji_offense_level["alice"] == 3

    def test_durations_capped_at_max(self):
        ws._emoji_offense_level["alice"] = 1000
        duration = ws._apply_emoji_timeout("alice")
        assert duration == ws._EMOJI_MAX_TIMEOUT_SECONDS

    def test_offense_level_decays_after_quiet_period(self):
        ws._apply_emoji_timeout("alice")
        ws._apply_emoji_timeout("alice")
        assert ws._emoji_offense_level["alice"] == 2
        # Simulate a long quiet period, then reoffend: level decays one step
        # before incrementing, landing back at 2 rather than 3.
        ws._emoji_last_offense["alice"] = time.time() - ws._EMOJI_REPEAT_DECAY_SECONDS - 1
        ws._apply_emoji_timeout("alice")
        assert ws._emoji_offense_level["alice"] == 2

    def test_short_timeout_is_brief(self):
        duration = ws._apply_emoji_timeout("alice", short=True)
        assert duration <= 8.0


# ---------------------------------------------------------------------------
# Buzzer state machine
# ---------------------------------------------------------------------------

class TestBuzzer:
    def test_commands_rejected_outside_buzzer_round(self):
        assert ws.control_buzzer("lock") is False
        assert ws.control_buzzer("reset") is False

    def test_unknown_command_rejected(self):
        ws._current_question = {"buzzer_only": True}
        assert ws.control_buzzer("frobnicate") is False
        assert ws.control_buzzer("") is False
        assert ws.control_buzzer(None) is False

    def test_lock_toggles(self):
        ws._current_question = {"buzzer_only": True}
        assert ws.control_buzzer("lock") is True
        assert ws.buzzer_is_locked() is True
        assert ws.control_buzzer("lock") is True
        assert ws.buzzer_is_locked() is False

    def test_reset_buzzer_state(self):
        ws._reset_buzzer(open_after_reset=True)
        assert ws._buzzer_open is True
        assert ws._buzzer_locked is False
        assert ws._buzzer_opened_at_ms is not None
        ws._reset_buzzer(open_after_reset=False)
        assert ws._buzzer_open is False
        assert ws._buzzer_opened_at_ms is None

    def test_reset_notifies_host_side_answer_queue(self):
        calls = []
        ws.set_buzzer_reset_callback(lambda: calls.append("reset"))

        ws._reset_buzzer(open_after_reset=True)

        assert calls == ["reset"]

    def test_player_specific_timer_state(self):
        ws.push_timer(10, player="Alice", rank=2)

        assert ws._timer_state == {
            "seconds": 10.0,
            "paused": False,
            "player": "Alice",
            "rank": 2,
        }
