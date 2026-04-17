"""web_server.py — Live audience answer submission for Guess The Anime.

Players open the public URL on any device and submit answers in real time.
The host's Python app polls get_answers() to print/display submitted answers.

Quick start:
  1. Set WEB_SERVER_ENABLED = True and NGROK_DOMAIN in config.
  2. Run the app normally — the server and ngrok start automatically.
  3. Players visit your ngrok URL, enter their name, and submit answers.
"""

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque

logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('flask.app').setLevel(logging.ERROR)

# Suppress Flask/werkzeug startup banner lines that use click.echo rather
# than the logging module (e.g. "* Serving Flask app", "* Debug mode: off",
# "* Running on http://...").  Other click output is left untouched.
try:
    import click as _click
    _FLASK_BANNER_PREFIXES = (' * Serving Flask', ' * Debug mode', ' * Running on')
    _orig_click_echo = _click.echo
    def _filtered_click_echo(message=None, *args, **kwargs):
        if message and any(str(message).startswith(p) for p in _FLASK_BANNER_PREFIXES):
            return
        _orig_click_echo(message, *args, **kwargs)
    _click.echo = _filtered_click_echo
except ImportError:
    pass

try:
    from flask import Flask, render_template_string
    from flask_socketio import SocketIO, emit, disconnect
    # Explicit imports so PyInstaller bundles the threading backend.
    # engineio loads async drivers dynamically — without these, the frozen
    # exe can't find any valid async_mode and raises ValueError at startup.
    try:
        import simple_websocket          # noqa: F401 — threading backend dep
        import engineio.async_drivers.threading  # noqa: F401 — driver module
    except ImportError:
        pass
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("[Web Server] Flask not installed. Run: pip install flask flask-socketio")

# ---------------------------------------------------------------------------
# Ngrok availability (checked once at import time)
# ---------------------------------------------------------------------------
def _find_ngrok_cmd():
    """Return the ngrok command string if found, else None."""
    exe_dir = os.path.dirname(sys.executable)
    ngrok_local = os.path.join(exe_dir, 'ngrok.exe')
    if os.path.isfile(ngrok_local):
        return ngrok_local
    # Check PATH via shutil.which (works cross-platform)
    import shutil
    return shutil.which('ngrok')

NGROK_CMD = _find_ngrok_cmd()   # None if not found
NGROK_AVAILABLE = NGROK_CMD is not None

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_app = None
_socketio = None
_answer_queue = queue.Queue()
_removal_queue = queue.Queue()  # names removed by host via web panel
_emoji_queue = queue.Queue()    # (name, emoji) tuples sent by players
_served_queue = queue.Queue()   # names of players who were served the current question
_current_question = None   # dict pushed to newly-connecting clients
_taken_years:  set = set()   # years already submitted in the current year-round
_taken_scores: set = set()   # scores already submitted in the current drum-round
_taken_ranks:  set = set()   # ranks already submitted in the current rank-round
_host_password: str = ''        # password that grants host-view access
_host_sids: set = set()         # connected socket SIDs granted host access
_submitted_answers: list = []   # answers collected for the current question
_host_messages: list = []       # player->host inbox entries: {name, text, ts}
_current_rules: dict = {}       # rules header+body shown on the waiting screen
_connected_players: dict = {}   # sid → player name
_submitted_sids: set = set()    # SIDs that submitted in the current question
_shadow_kicked_ips: set = set()  # IPs whose answers are silently discarded (kick)
_shadow_kicked_players: dict = {}  # name → IP for host unban display
_banned_names: set = set()    # names whose answers are silently discarded (name ban)
_emoji_disabled_names: set = set()  # names whose emoji reactions are silently discarded
_hard_banned_ips: set = set() # IPs that are disconnected on connect (IP ban)
_emoji_events_by_name: dict = {}   # name -> deque[timestamp]
_emoji_timeout_until: dict = {}    # name -> epoch seconds when timeout ends
_emoji_offense_level: dict = {}    # name -> escalating timeout level
_emoji_last_offense: dict = {}     # name -> epoch seconds of last offense

# Emoji anti-spam settings
_EMOJI_WINDOW_SECONDS = 10.0
_EMOJI_TIMEOUT_THRESHOLD = 50       # >50 in window triggers timeout
_EMOJI_WARN_THRESHOLD = 24          # optional warning threshold
_EMOJI_BURST_WINDOW_SECONDS = 1.0
_EMOJI_BURST_THRESHOLD = 10         # >=10 in 1s triggers short timeout
_EMOJI_BASE_TIMEOUT_SECONDS = 5.0
_EMOJI_REPEAT_MULTIPLIER = 1.1
_EMOJI_MAX_TIMEOUT_SECONDS = 180.0
_EMOJI_REPEAT_DECAY_SECONDS = 600.0

# Buzzer state
_buzzer_open: bool = False
_buzzer_locked: bool = False
_buzzer_opened_at_ms: int | None = None
_ngrok_process = None
_server_thread = None      # Thread running _socketio.run(); kept alive across stop()/start() cycles
_server_started = False    # True once start() completes successfully
_titles_provider = None         # callable() → list[str]; set by main app
_player_names_provider = None   # callable() → list[str]; set by main app
_player_colors: dict = {}       # name → {bg: str, text: str}; in-memory color state
_color_cmd_lock = threading.Lock()  # guards scoreboard_color_commands.json writes
_SCOREBOARD_DATA = 'scoreboard_data'
_session_lines: list = []  # latest session history text lines
_session_filename: str = 'session_history.txt'  # download filename
_timer_state: dict = {}    # {seconds, paused} while a timer is active; empty = no timer
_current_metadata: dict = {}  # latest currently-playing metadata; pushed to host clients
_info_public: bool = False    # when True, metadata button is shown to all clients
_playback_state: dict = {}    # {current_ms, length_ms, playing} pushed to host clients
_up_next: dict = {}           # up-next track info; pushed to host clients
_current_marks: dict = {}     # {tagged, favorited, blind, peek, mute_peek} for current theme
_current_toggles: dict = {}   # {blind, peek, mute, censors, shortcuts, dock, censor_count}
_host_action_callback = None  # callable(action, data) set by main app for remote control
_on_buzz_callback = None       # callable(rank: int, name: str) called when a player buzzes in
_pending_selections: dict = {}  # name → answer; silently tracks current selection before submit

public_url = None          # Readable from main app after start()


def _get_emoji_status(name: str) -> dict:
  """Return emoji moderation status for a player name."""
  now = time.time()
  until = float(_emoji_timeout_until.get(name, 0.0) or 0.0)
  remaining = max(0.0, until - now)
  return {
    'name': name,
    'muted': bool(name in _emoji_disabled_names),
    'timed_out': remaining > 0.0,
    'timeout_until': until,
    'remaining_ms': int(remaining * 1000),
  }


def _emit_emoji_status_for_name(name: str):
  """Emit current emoji moderation status to all connected clients with this player name."""
  if not FLASK_AVAILABLE or _socketio is None or not name:
    return
  payload = _get_emoji_status(name)
  for sid, pname in list(_connected_players.items()):
    if pname == name:
      try:
        _socketio.emit('emoji_status', payload, to=sid)
      except Exception:
        pass


def _apply_emoji_timeout(name: str, short: bool = False) -> float:
  """Apply progressive timeout for a player and return duration seconds."""
  now = time.time()
  lvl = int(_emoji_offense_level.get(name, 0) or 0)
  last = float(_emoji_last_offense.get(name, 0.0) or 0.0)
  # Decay offense after a long quiet period.
  if lvl > 0 and last > 0 and (now - last) > _EMOJI_REPEAT_DECAY_SECONDS:
    lvl = max(0, lvl - 1)
  lvl += 1
  _emoji_offense_level[name] = lvl
  _emoji_last_offense[name] = now

  if short:
    duration = min(_EMOJI_MAX_TIMEOUT_SECONDS, 8.0)
  else:
    duration = min(_EMOJI_MAX_TIMEOUT_SECONDS, _EMOJI_BASE_TIMEOUT_SECONDS * (_EMOJI_REPEAT_MULTIPLIER ** (lvl - 1)))
  _emoji_timeout_until[name] = now + duration
  return duration


def _emit_buzzer_state(to_sid: str = None):
  """Emit current buzzer state to clients (optionally one sid)."""
  if not FLASK_AVAILABLE or _socketio is None:
    return
  order = []
  if _current_question and _current_question.get('buzzer_only'):
    order = [{'name': str(a.get('name', ''))} for a in list(_submitted_answers)]
  payload = {
    'open': bool(_buzzer_open),
    'locked': bool(_buzzer_locked),
    'order': order,
  }
  if to_sid:
    _socketio.emit('buzzer_state', payload, to=to_sid)
  else:
    _socketio.emit('buzzer_state', payload)


def _emit_host_messages(to_sid: str = None):
  """Emit host inbox entries to host clients."""
  if not FLASK_AVAILABLE or _socketio is None:
    return
  payload = {'messages': list(_host_messages)}
  if to_sid:
    _socketio.emit('host_messages_update', payload, to=to_sid)
  else:
    for sid in list(_host_sids):
      _socketio.emit('host_messages_update', payload, to=sid)


def _emit_host_message_toast(entry: dict):
  """Emit a live toast event to host clients for a new inbox message."""
  if not FLASK_AVAILABLE or _socketio is None:
    return
  for sid in list(_host_sids):
    _socketio.emit('host_message_toast', dict(entry or {}), to=sid)


def _emit_peer_answers_update():
  """Emit peer answer list.

  Normal rounds: only to players who already submitted.
  Buzzer rounds: to everyone (host excluded; host has answer_update panel).
  """
  if not FLASK_AVAILABLE or _socketio is None:
    return
  payload = {'answers': list(_submitted_answers)}
  if _current_question and _current_question.get('buzzer_only'):
    for sid in list(_connected_players.keys()):
      if sid not in _host_sids:
        _socketio.emit('peer_answers_update', payload, to=sid)
  else:
    for sid in list(_submitted_sids):
      _socketio.emit('peer_answers_update', payload, to=sid)


def _reset_buzzer(open_after_reset: bool = False):
  """Reset buzzer order and state; optionally open immediately."""
  global _buzzer_open, _buzzer_locked, _buzzer_opened_at_ms
  _buzzer_open = bool(open_after_reset)
  _buzzer_locked = False
  _buzzer_opened_at_ms = int(time.time() * 1000) if _buzzer_open else None


def control_buzzer(cmd: str) -> bool:
  """Apply a buzzer command and broadcast updated state.

  Supported commands: lock (toggle), reset.
  Returns True if a command was applied.
  """
  global _buzzer_open, _buzzer_locked, _buzzer_opened_at_ms
  global _submitted_answers, _submitted_sids, _pending_selections
  c = str(cmd or '').strip().lower()
  is_buzzer_round = bool(_current_question and _current_question.get('buzzer_only'))

  if c in ('lock', 'toggle_lock'):
    if not is_buzzer_round:
      return False
    _buzzer_open = True
    _buzzer_locked = not _buzzer_locked
    _buzzer_opened_at_ms = None if _buzzer_locked else int(time.time() * 1000)
  elif c == 'reset':
    if not is_buzzer_round:
      return False
    _submitted_answers = []
    _submitted_sids = set()
    _pending_selections = {}
    if _buzzer_open and not _buzzer_locked:
      _buzzer_opened_at_ms = int(time.time() * 1000)
    _broadcast_players_update()
    _emit_peer_answers_update()
    if _host_sids:
      for sid in list(_host_sids):
        _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)
  else:
    return False
  _emit_buzzer_state()
  return True


def buzzer_is_open() -> bool:
  return bool(_buzzer_open)


def buzzer_is_locked() -> bool:
  return bool(_buzzer_locked)


def _write_color_command(name: str, bg: str, text: str):
    """Append/replace a color command in the shared file so the scoreboard can pick it up."""
    f_path = os.path.join(_SCOREBOARD_DATA, 'scoreboard_color_commands.json')
    with _color_cmd_lock:
        try:
            existing = []
            if os.path.exists(f_path):
                with open(f_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
        except Exception:
            existing = []
        existing = [c for c in existing if c.get('name') != name]
        existing.append({'name': name, 'bg': bg, 'text': text})
        try:
            with open(f_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False)
        except Exception as e:
            print(f"[color cmd] write error: {e}")

# ---------------------------------------------------------------------------
# Mobile-friendly HTML page (inlined so the app bundles as a single exe)
# ---------------------------------------------------------------------------
_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Guess The Anime</title>
  <link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAIa0lEQVR42q1Xa3CU1Rl+zjnf7n67m91kNxdYQyDhpgFBmYQgYAhNFS1VBohB8QJ0YKpVpKVoodo2UxQVtVZmOt5ai0ORFkZrrWNlxEu9lijVVAiNFUokIIFwSYCQsN855+mPb0kR5TqemTPfzJ5z3ud9n/d9n3NW4PRDKcAYAEj2GgWTnnyhNuP7Wd0/ASQBYD+wb4dytn0i5TsIBV5EW9t7CoABMp9zH0oCQH7+pQOy4n+70w177zoO26UkHUUKQQKkUmx3HP7DcXi36+rzY/HXkJs7Xvo25LmCOxIAEok7bgtHuEdKH0wKTcAQsBqgBkjAZn7TBLhPSP4oHCZykj8XmUDOOnIFANmJBUtDLo8Z96SkAaj79KFevJh63Tqa99+nXrmS3pQp9AB6vkOagH4iFCKyE/fLs3TCpz03d/y8cJgEvDRgTYYB74oraNraeOKwJPXq1bSuSysl00JYAul7XJdI5E07YycIyLKyssBFWbGNXX6OtZWSFIK6qIimo6MH1LS10WzZQkuS6TRJ0lu2jARolaLOpKo6mvUFcs+PERDw52moz8ub+GQwRALaA0jHIQHqpUt9ZM+jfv116lSKJhCgd+uttNaSWtN0dtLk5/tsCUkCek0wSCTypmdYcE6KXpVZzI3Hf7dTSkvAMwApJS1Ab8MGGpKapFdR4RelELQATUODzwpJr7y8hwUC3n4hbHEs/jwA1J4iDYKAQF2dnBDJ2kS/mEzm60c0YgS7q6uZrqykdRxSSlIpGoBm0ybSWlpjqEtLMx0je2xMjUS3oawskEH/2jQIBQADB8bnuOE99FvMHu/AV6ZSPjN1dX4dkNRNTTSBgK8RQlAD1gK8JRRuQ//+2Sc68JV8xLuDToAnEQ8pAfF/52kMzAMPQC1cCEGCQoALFkB53vH6CeGrkU0ggf1fsnCCeQICa6BuCLutp2TAzy29+fMz7WBoDh+mV1NzPPUkQJOxMTnq7kItguok6ijqUCcVBFLx/k+PyyowHmDs14FnjOtUiubgQfLoUZoDB6jHjPHXMx1DgMfOHwHM2GihLY4NekEIoA518vg0CF98BBDF45Xhck53r7QfKtBC0Jwkej15ck/evcce89dCoS/t1fBtvK3AGaFJ5tvhUUQcyzN6oAAIVQU4LRDGhp0H/zj60R822xZvfft2dZ7yMNp0w5zIlxCZ/jAgAG74J8SqVZA7d2bKjT1bbQZldSiB56wnSouLvHuH3lE2tHVdrvDMy+NQ5UAJCQATf1F+O3lzR3rXtPdsSa/B7BeNsUNmWuwkXaCjUWpfrr8yj53bLxWLIlkcnBrCvdfWk3Pa0/dX3EkAkzPYSI7rN6bFzNhivRs2Gs5q5idXv0CZk8PZrksCTB+Xz54CvPFG6q4u6s5OetOmfWnNZs4Q4CzXpZNIsnHSS+TMbfSu/8Rw5lb7rX5jWwAkVCpR+NiKkfeOOy+cIqmltd1IxQeiNJSPu1rXoUAEcInRsBAgAKkUaC3s3LlwRo2CDARgYzGIZ5+FUArWWlgIBAA8HXSxOGCxpmwJqgqrodMdEEIKKYMcktUv+69t7+aoiwuG/mXh+bMhHddY0yWVcGD0EQzLLwN0N36yrx5JFcJorSEzd4kBwO3bYaurYdNp2MWLgaZPASEgKSBBPO66uFl5WDR4Dm6/4Bbo9H440oGlgXTCJhVKyBd3v1kuEMTEsb1GPvrIiLsGVeSNMki3C0MjKSQcFcGU92/G2pYG3CQVatK7MEEf1z/BEBAMAocP9RRevQKWhwrwByqM6T0Qr1b+HsZ6EDRQEEQoaRv2faTmf3xf8zut9fOF8K/gnHAs+tDdpT+Y89MLvg8pg8ZLtyulIjigD+KyN2aidO8giKCHbrEB5WYvSmlQ4gGKQEsQ+AwCHzjZ6OJFcL1cNORswrrq5UiFCuCZTgSD2QbWqF99thz3NP5mZcfBjvkC2OtrgJDG0gJAzYSSqmUPX7SwcFjuCKO79kgnEBcftn+MqW/OxZKDNyEtg2hQLTgsD+HDQCONNKLi6FC4zMJQXYh862BRdDlWjH8Q4/Mq4XkHGHALbFN7o7rjX0t3v7z1tR8DWCWFhKVVCgAJilrUqk/R1LilvXnV6l2v9HGlGj4mv0LAalMY6StzImHctesp1Ohy9LfZGG0G4HPRJuKI4Lbuy1BoosijizuDy7GgYjau7TMVsF1GOVH5xNYVcmb9wj837No4VUG+dw2uUY1oBADbczdvxmYSVErIQ0e6jzy/tuWtbQ2d/64szx2elXSTZkT2xeK/bBZ/2vM6qjAcR5DGR4GtSAuNUq8vlHDwsHoBIy8cgSWliwgB09zZ4szZcPeBhz5+cl5nd+ciJeRBA+tsxuZTPtVFLWqV8vWvXyrZ+8WnKu8jZ20jv7dDX1IyklPFeL6NX3OSW8XLo6P5dzzCGeJKjiwuI2dt15z1OZ+peohFuUWvABigII/p/1k90Z1jSgWJW2oHf7e9+dr17LqxyUsVFNklmM3r3Am8OlLFZZjL3nl9bMf1G70d123g9MGTDkFiHoBjSuuc638D6d+SEgAGFyZ7r33u8t9y/VVrGI8lWZxVzL6xvsyL9WL9VWv40hXPsDiv6A0AQ8416tOzEcDscf3H7uwTLzJTRCWniEtZEi823xl0WSsc3PpNRH3SF3NdXZ3MSiZLnXBk8xRZaYe5g44OjJQcrRHjrApH/hMoSAwjKc4GXJzpPgIQKYTzD/XaO+HI8HDQKv1p4AuphcWQ9Hk0gurV6EZvd7Q1IXajM3Pn87RRnamnvwQkDsMT4WC3hpkQs65MmRyRb+KiU6ZlU6gVrU77z9L7u9/CGYKfy/AZSwZr8rN61w+MlHQNihR358d6fYBEYNpZsgoA+B96i9z9MuacjQAAAABJRU5ErkJggg=="/>
  <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #111; color: #fff;
      font-family: 'Segoe UI', sans-serif;
      display: flex; flex-direction: column;
      align-items: center; justify-content: flex-start;
      padding: 60px 20px 92px; gap: 8px;
    }
    h1 {
      font-size: 0.9em; color: #5566aa; letter-spacing: 0.22em;
      text-transform: uppercase; font-weight: 700; margin-bottom: 4px;
    }
    .box { width: 100%; max-width: 480px; }
    #waiting { text-align: center; color: #555; font-size: 1.1em; padding: 16px 0; }
    #waiting-msg {
      font-size: 0.95em; color: #445; letter-spacing: 0.06em;
      text-transform: uppercase; font-weight: 500;
    }
    #waiting-rules {
      margin-top: 16px;
      background: #1a1a1a; border: 1px solid #333; border-radius: 10px;
      padding: 14px 18px; text-align: left;
      color: #aaa; font-size: 0.88em; white-space: pre-line; line-height: 1.7;
    }
    #waiting-rules-header {
      text-align: center; font-size: 0.9em; font-weight: bold;
      color: #777; letter-spacing: 0.05em; margin-bottom: 8px;
      border-bottom: 1px solid #2a2a2a; padding-bottom: 6px;
    }
    #history-link {
      display: inline-block; margin-top: 14px;
      color: #446; font-size: 0.82em; text-decoration: none;
      border: 1px solid #223; border-radius: 6px; padding: 5px 12px;
      transition: color .15s, border-color .15s;
    }
    #history-link:hover { color: #88a; border-color: #446; }
    /* ── Top bar (history | timer | player label) ── */
    #top-bar {
      position: fixed; top: 0; left: 0; right: 0;
      z-index: 300; display: flex; align-items: center;
      padding: 8px 12px; min-height: 44px; pointer-events: none;
      transition: left 0.25s ease, right 0.25s ease;
    }
    /* ── History button (top-left) ── */
    #history-btn {
      pointer-events: auto;
      background: transparent; border: none;
      color: #555; font-size: 0.78em; cursor: pointer; padding: 0 2px;
    }
    #history-btn:hover { color: #888; }
    /* ── History modal ── */
    #history-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 760;
      align-items: flex-end; justify-content: center;
    }
    #history-overlay.active { display: flex; }
    #history-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 16px 16px 0 0;
      width: 100%; max-width: 480px; padding: 16px 12px 28px;
      max-height: 80vh; display: flex; flex-direction: column; gap: 10px;
    }
    #history-box-title {
      font-size: 0.82em; color: #556; text-transform: uppercase;
      letter-spacing: .07em; text-align: center;
    }
    #history-text-area {
      flex: 1; overflow: auto; white-space: pre; font-family: monospace;
      font-size: 0.76em; line-height: 1.7; color: #999;
      background: #111; border: 1px solid #222; border-radius: 8px; padding: 10px;
    }
    #history-footer { display: flex; gap: 8px; }
    #history-dl-btn {
      flex: 1; padding: 11px; background: #1a2a1a; border: 1px solid #3a5a3a;
      border-radius: 8px; color: #8c8; font-size: 0.9em; cursor: pointer;
      text-decoration: none; text-align: center;
    }
    #history-dl-btn:hover { background: #1f3a1f; }
    #history-close-btn {
      flex: 1; padding: 11px; background: #222; border: 1px solid #444;
      border-radius: 8px; color: #aaa; font-size: 0.95em; cursor: pointer;
    }
    #history-close-btn:hover { background: #333; color: #fff; }
    #prev-question {
      margin-top: 16px;
      background: #131320; border: 1px solid #334; border-radius: 10px;
      padding: 14px 18px; text-align: left; font-size: 0.88em; line-height: 1.6;
    }
    #prev-question-label {
      text-align: center; font-size: 0.82em; font-weight: bold;
      color: #445; letter-spacing: 0.07em; margin-bottom: 10px;
      border-bottom: 1px solid #223; padding-bottom: 6px;
    }
    #prev-question-title { color: #888; margin-bottom: 8px; }
    #prev-question-correct { color: #556; margin-bottom: 4px; }
    #prev-question-mine { color: #aaa; }
    .pq-tag {
      display: inline-block; padding: 1px 7px; border-radius: 4px;
      margin: 1px 2px; font-size: 0.9em;
    }
    .pq-tag-correct { background: #1a3a1a; color: #5c5; border: 1px solid #2a5a2a; }
    .pq-tag-wrong   { background: #3a1a1a; color: #f66; border: 1px solid #5a2a2a; }
    #q-card {
      background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px;
      padding: 14px 18px; margin-bottom: 18px;
    }
    #q-title { font-size: 1.15em; font-weight: bold; margin-bottom: 6px; line-height: 1.3; color: #fff; }
    #q-info  { font-size: 0.88em; color: #888; white-space: pre-line; line-height: 1.5; margin: 0; }

    /* ── Multiple-choice buttons ── */
    .choice-btn {
      display: block; width: 100%; padding: 13px 16px; margin: 7px 0;
      background: #222; border: 1px solid #444; border-radius: 8px;
      color: #fff; font-size: 0.97em; cursor: pointer; text-align: left;
      transition: background .15s;
    }
    .choice-btn:hover   { background: #2a2a2a; }
    .choice-btn.selected { background: #1a2e45; border-color: #3a7abf; }

    /* ── Drum picker ── */
    .drum-wrap {
      position: relative; width: 100%; height: 180px;
      overflow: hidden; margin-bottom: 16px;
      border-radius: 10px;
    }
    .drum-scroll {
      height: 100%; overflow-y: scroll;
      scroll-snap-type: y mandatory;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
    }
    .drum-scroll::-webkit-scrollbar { display: none; }
    .drum-item {
      height: 60px; display: flex; align-items: center; justify-content: center;
      font-size: 1.5em; font-weight: bold;
      scroll-snap-align: center;
      color: #777; transition: color .15s, font-size .15s;
      cursor: default; user-select: none;
    }
    /* fade top/bottom */
    .drum-wrap::before, .drum-wrap::after {
      content: ''; position: absolute; left: 0; right: 0; height: 60px;
      pointer-events: none; z-index: 2;
    }
    .drum-wrap::before { top: 0;    background: linear-gradient(#111, transparent); }
    .drum-wrap::after  { bottom: 0; background: linear-gradient(transparent, #111); }
    /* centre highlight bar */
    .drum-highlight {
      position: absolute; top: 50%; left: 0; right: 0;
      transform: translateY(-50%); height: 60px;
      border-top: 1px solid #3a7abf; border-bottom: 1px solid #3a7abf;
      pointer-events: none; z-index: 1;
    }
    .drum-nav {
      display: flex; flex-direction: column; justify-content: center; gap: 8px;
    }
    .drum-nav-btn {
      min-width: 78px; width: auto; height: 46px; padding: 0 6px;
      background: #1e1e1e; border: 1px solid #445; border-radius: 6px;
      color: #aab; font-size: 1.2em; font-weight: 700; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: color .15s, border-color .15s;
      letter-spacing: 0;
    }
    .drum-nav-btn:hover { color: #fff; border-color: #66a; background: #252535; }
    .drum-nav-btn:active { background: #2a2a2a; }
    .drum-shortcuts {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 6px;
      margin-top: 8px;
      margin-bottom: 10px;
    }
    .drum-shortcut-btn {
      padding: 5px 8px;
      min-width: 50px;
      background: #171726;
      border: 1px solid #334;
      border-radius: 6px;
      color: #9ab;
      font-size: 0.9em;
      cursor: pointer;
      line-height: 1.1;
    }
    .drum-shortcut-btn:hover { color: #def; border-color: #557; background: #202035; }

    /* ── Input mode toggle ── */
    .input-toggle {
      display: block; width: 100%; margin-bottom: 10px;
      padding: 8px; background: transparent;
      border: 1px solid #333; border-radius: 6px;
      color: #555; font-size: 0.8em; cursor: pointer;
      transition: color .15s, border-color .15s;
    }
    .input-toggle:hover { color: #aaa; border-color: #555; }

    /* ── Stepper (members / popularity) ── */
    .stepper-wrap { margin-bottom: 16px; }
    .stepper-input-wrap { position: relative; margin-bottom: 10px; }
    .stepper-display {
      text-align: center; font-size: 2em; font-weight: bold;
      padding: 14px 40px 14px 14px; background: #1a1a1a; border: 1px solid #444; border-radius: 8px;
      letter-spacing: 1px;
      width: 100%; box-sizing: border-box; color: #fff;
    }
    .stepper-type-hint {
      position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
      font-size: 0.65em; font-weight: bold; color: #777;
      background: #2a2a2a; border: 1px solid #555; border-radius: 3px;
      padding: 2px 5px; pointer-events: none; letter-spacing: 0; user-select: none;
    }
    .stepper-row {
      display: grid; gap: 6px; margin-bottom: 6px;
    }
    .stepper-row.cols-3 { grid-template-columns: repeat(3, 1fr); }
    .stepper-row.cols-2 { grid-template-columns: repeat(2, 1fr); }
    .step-btn {
      padding: 12px 0; background: #222; border: 1px solid #444;
      border-radius: 8px; color: #fff; font-size: 0.95em;
      cursor: pointer; transition: background .12s;
    }
    .step-btn:hover { background: #2e2e2e; }
    .step-btn.neg { color: #f88; }
    .step-btn.pos { color: #8f8; }

    /* ── Rank slider (popularity) ── */
    .rank-display-wrap { position: relative; margin-bottom: 12px; }
    .rank-display {
      text-align: center; font-size: 2em; font-weight: bold;
      padding: 14px 40px 14px 14px; background: #1a1a1a; border: 1px solid #444; border-radius: 8px;
      width: 100%; box-sizing: border-box; color: #fff; letter-spacing: 1px;
    }
    .rank-type-hint {
      position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
      font-size: 0.65em; font-weight: bold; color: #777;
      background: #2a2a2a; border: 1px solid #555; border-radius: 3px;
      padding: 2px 5px; pointer-events: none; letter-spacing: 0; user-select: none;
    }
    .rank-slider-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .rank-slider-label { font-size: 0.72em; color: #666; white-space: nowrap; }
    .rank-slider-wrap { position: relative; flex: 1; display: flex; align-items: center; }
    .rank-slider {
      width: 100%; -webkit-appearance: none; appearance: none;
      height: 8px; border-radius: 4px; outline: none; cursor: pointer;
    }
    .rank-slider::-webkit-slider-thumb {
      -webkit-appearance: none; width: 22px; height: 22px;
      border-radius: 50%; background: #fff; border: 2px solid #3a7abf; cursor: pointer;
    }
    .rank-slider::-moz-range-thumb {
      width: 22px; height: 22px;
      border-radius: 50%; background: #fff; border: 2px solid #3a7abf; cursor: pointer; border: none;
    }
    .rank-preset-row { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; margin-bottom: 8px; justify-content: center; }
    .rank-preset-btn {
      padding: 6px 10px; background: #222; border: 1px solid #444;
      border-radius: 6px; color: #aaa; font-size: 0.8em; cursor: pointer;
      transition: background .12s, border-color .12s;
    }
    .rank-preset-btn:hover { background: #2e2e2e; border-color: #666; color: #ddd; }
    .rank-preset-btn.rank-active { border-color: #3a7abf; color: #7ab8f5; background: #1a2333; }
    .rank-adj-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 5px; margin-top: 2px; }
    .rank-adj-btn {
      padding: 9px 0; background: #222; border: 1px solid #444;
      border-radius: 6px; font-size: 0.82em; cursor: pointer; color: #aaa;
      transition: background .12s;
    }
    .rank-adj-btn:hover { background: #2e2e2e; }
    .rank-adj-btn.rank-better { color: #8f8; }
    .rank-adj-btn.rank-worse  { color: #f88; }
    .rank-peer-overlay {
      position: absolute; left: 0; right: 0; top: 50%; transform: translateY(-50%);
      height: 8px; pointer-events: none; border-radius: 4px; overflow: visible;
    }
    .rank-peer-tick {
      position: absolute; top: 50%; transform: translate(-50%, -50%);
      width: 4px; height: 24px; border-radius: 2px;
      background: rgba(255,200,60,0.85);
    }

    /* ── Tag chips ── */
    .tag-grid {
      display: flex; flex-wrap: wrap; gap: 8px;
      margin-bottom: 14px;
    }
    .tag-chip {
      padding: 8px 14px; background: #222; border: 1px solid #444;
      border-radius: 20px; color: #ccc; font-size: 0.9em;
      cursor: pointer; transition: background .12s, border-color .12s;
      user-select: none;
    }
    .tag-chip:hover   { background: #2a2a2a; }
    .tag-chip.selected { background: #1a2e45; border-color: #3a7abf; color: #fff; }
    .tag-chip.used    { background: #111; border-color: #333; color: #444; cursor: default; }

    /* ── Free text ── */
    #free-input {
      width: 100%; padding: 12px;
      background: #222; border: 1px solid #444; border-radius: 8px;
      color: #fff; font-size: 1em; margin-bottom: 12px;
    }

    /* ── Submit ── */
    #submit-btn {
      width: 100%; padding: 14px; background: #2a6a2a;
      border: none; border-radius: 8px;
      color: #fff; font-size: 1.05em; cursor: pointer;
      transition: background .15s;
    }
    #submit-btn:hover:not(:disabled) { background: #3a8a3a; }
    #submit-btn:disabled { background: #444; cursor: default; }
    #sent-msg { text-align: center; color: #5af; font-size: 0.95em; margin-top: 10px; display: none; }

    /* ── Emoji picker ── */
    #emoji-bar {
      display: none; margin-top: 8px;
      text-align: center;
    }
    #emoji-bar p {
      font-size: 0.78em; color: #556; margin: 0 0 8px;
      text-transform: uppercase; letter-spacing: .05em;
    }
    #emoji-status {
      display: none;
      margin: 8px 0 0;
      font-size: 0.82em;
      color: #d99;
      letter-spacing: .02em;
    }
    #host-msg-row {
      display: flex;
      gap: 6px;
      margin-top: 10px;
      align-items: center;
    }
    #host-msg-input {
      flex: 1;
      min-width: 0;
      padding: 8px 10px;
      background: #1a1a2a;
      border: 1px solid #334;
      border-radius: 8px;
      color: #dde;
      font-size: 0.86em;
    }
    #host-msg-send {
      padding: 8px 10px;
      background: #202040;
      border: 1px solid #446;
      border-radius: 8px;
      color: #bcd;
      font-size: 0.82em;
      cursor: pointer;
      white-space: nowrap;
    }
    #host-msg-send:hover { background: #2a2a55; color: #def; }

    #host-messages-wrap {
      margin-top: 10px;
      margin-bottom: 8px;
      border: 1px solid #2f3550;
      border-radius: 10px;
      background: #101326;
      padding: 8px;
      text-align: left;
    }
    #host-messages-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
      font-size: 0.78em;
      color: #88a;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    #hm-right-controls {
      display: flex; align-items: center; gap: 5px;
    }
    #hm-popup-btn {
      background: transparent; border: none; padding: 0 2px;
      font-size: 1.08em; cursor: pointer; line-height: 1;
      opacity: 0.8; transition: opacity 0.15s;
    }
    #hm-popup-btn:hover { opacity: 1; }
    #hm-popup-btn.off { opacity: 0.35; filter: grayscale(1); }
    #hm-vol-wrap {
      display: flex; align-items: center; gap: 3px;
    }
    #hm-bell-btn {
      background: transparent; border: none; padding: 0 2px;
      font-size: 1.15em; cursor: pointer; line-height: 1;
      opacity: 0.75; transition: opacity 0.15s;
    }
    #hm-bell-btn:hover { opacity: 1; }
    #hm-bell-btn.muted { opacity: 0.35; filter: grayscale(1); }
    #hm-vol-slider {
      -webkit-appearance: none; appearance: none;
      width: 72px; height: 4px;
      border-radius: 2px; background: #334; outline: none; cursor: pointer;
    }
    #hm-vol-slider::-webkit-slider-thumb {
      -webkit-appearance: none; appearance: none;
      width: 13px; height: 13px; border-radius: 50%;
      background: #6699ff; cursor: pointer;
    }
    #hm-vol-slider::-moz-range-thumb {
      width: 13px; height: 13px; border-radius: 50%;
      background: #6699ff; cursor: pointer; border: none;
    }
    #host-messages-clear {
      background: transparent;
      border: 1px solid #334;
      border-radius: 6px;
      color: #778;
      font-size: 0.75em;
      padding: 3px 7px;
      cursor: pointer;
    }
    #host-messages-clear:hover { color: #ccd; border-color: #556; }
    #host-messages-list {
      max-height: 170px;
      overflow-y: auto;
      border: 1px solid #202034;
      border-radius: 8px;
      background: #0b0b16;
      padding: 5px 7px;
    }
    .hm-item {
      padding: 5px 0;
      border-bottom: 1px solid #171727;
      font-size: 0.84em;
      color: #c7cce0;
      word-break: break-word;
      line-height: 1.35;
    }
    .hm-item:last-child { border-bottom: none; }
    .hm-name { color: #9fc4ff; font-weight: bold; }
    .hm-ts {
      color: #667;
      font-size: 0.82em;
      margin-left: 6px;
      white-space: nowrap;
      display: inline-block;
    }

    @keyframes hostToastIn {
      from { opacity: 0; transform: translateX(-50%) translateY(16px) scale(0.96); }
      to   { opacity: 1; transform: translateX(-50%) translateY(0)    scale(1); }
    }
    @keyframes hostToastGlow {
      0%,100% { box-shadow: 0 0 6px 2px rgba(100,160,255,0.4),  0 0 18px 4px rgba(80,130,255,0.2),  0 8px 28px rgba(0,0,0,0.6); border-color: #6699ff; }
      50%     { box-shadow: 0 0 16px 6px rgba(140,200,255,0.75), 0 0 36px 10px rgba(100,160,255,0.35), 0 8px 28px rgba(0,0,0,0.6); border-color: #aaddff; }
    }
    #host-msg-toast {
      display: none;
      position: fixed;
      left: 50%;
      bottom: 18px;
      transform: translateX(-50%);
      z-index: 950;
      width: min(94vw, 560px);
      background: rgba(12,18,40,0.97);
      border: 2px solid #6699ff;
      border-radius: 12px;
      box-shadow: 0 0 0 0 rgba(120,180,255,0.55), 0 8px 28px rgba(0,0,0,0.6);
      padding: 13px 16px 13px 52px;
      color: #dde7ff;
      font-size: 1.05em;
      line-height: 1.4;
    }
    #host-msg-toast::before {
      content: '\2709';
      position: absolute;
      left: 13px;
      top: 50%;
      transform: translateY(-50%);
      font-size: 1.6em;
      color: #88bbff;
    }
    #host-msg-toast.active {
      display: block;
      animation: hostToastIn 0.22s ease-out, hostToastGlow 1.2s ease-in-out 0.22s infinite;
    }
    #host-msg-toast .from { color: #aaccff; font-weight: bold; font-size: 1.06em; margin-bottom: 3px; }
    #host-msg-toast .body {
      color: #e8eeff;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    #gta-toast {
      display: none;
      position: fixed;
      left: 50%;
      top: 72px;
      transform: translateX(-50%);
      z-index: 951;
      width: min(90vw, 420px);
      background: rgba(20,20,30,0.95);
      border: 1px solid #663;
      border-radius: 10px;
      padding: 10px 12px;
      color: #ffd;
      font-size: 0.95em;
      text-align: center;
      box-shadow: 0 6px 18px rgba(0,0,0,0.45);
    }
    #gta-toast.active { display: block; }
    .emoji-btn {
      background: transparent; border: 1px solid #2a2a3a;
      border-radius: 8px; padding: 6px 8px;
      font-size: 1.4em; cursor: pointer; line-height: 1;
      transition: border-color .15s, transform .1s;
    }
    .emoji-btn:hover  { border-color: #556; transform: scale(1.15); }
    .emoji-btn:active { transform: scale(0.95); }
    .emoji-btn:disabled { opacity: 0.35; cursor: default; transform: none; }
    #emoji-add-btn {
      background: #2a2a3a; border: 1px solid #556;
      border-radius: 8px; padding: 6px 10px;
      font-size: 1.1em; cursor: pointer; line-height: 1; color: #ccd;
      transition: background .15s, transform .1s;
    }
    #emoji-add-btn:hover { background: #3a3a5a; transform: scale(1.1); }
    /* Emoji picker overlay */
    #emoji-picker-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.7); z-index: 600;
      align-items: flex-end; justify-content: center;
    }
    #emoji-picker-overlay.active { display: flex; }
    #emoji-picker-box {
      background: #1a1a2e; border: 1px solid #446; border-radius: 16px 16px 0 0;
      width: 100%; max-width: 480px; padding: 16px 12px 28px;
      max-height: 70vh; display: flex; flex-direction: column;
    }
    #emoji-picker-title {
      font-size: 0.78em; color: #778; text-transform: uppercase;
      letter-spacing: .06em; margin-bottom: 12px; text-align: center;
    }
    #emoji-picker-grid {
      display: flex; flex-wrap: wrap; gap: 4px;
      justify-content: center; overflow-y: auto;
    }
    .ep-btn {
      background: transparent; border: 1px solid #2a2a3a;
      border-radius: 8px; padding: 7px 9px; font-size: 1.5em;
      cursor: pointer; line-height: 1;
      transition: border-color .12s, transform .1s;
    }
    .ep-btn:hover  { border-color: #556; transform: scale(1.15); }
    .ep-btn:active { transform: scale(0.9); }
    .ep-btn.ep-saved { border-color: #446; background: #1a1a3a; }
    #emoji-picker-close {
      margin-top: 14px; flex: 1; padding: 11px;
      background: #222; border: 1px solid #444; border-radius: 8px;
      color: #aaa; font-size: 0.95em; cursor: pointer;
    }
    #emoji-picker-close:hover { background: #333; color: #fff; }
    #emoji-picker-reset {
      margin-top: 14px; flex: 1; padding: 11px;
      background: #1a1a2a; border: 1px solid #446; border-radius: 8px;
      color: #88a; font-size: 0.95em; cursor: pointer;
    }
    #emoji-picker-reset:hover { background: #22223a; color: #aaf; }
    #emoji-picker-footer { display: flex; gap: 8px; }

    /* ── Buzzer panel ── */
    #buzzer-panel {
      display: none;
      margin-top: 10px;
      padding: 10px;
      background: #141425;
      border: 1px solid #2f2f4a;
      border-radius: 10px;
      text-align: center;
    }
    #buzzer-status {
      font-size: 0.84em;
      color: #99a;
      margin-bottom: 8px;
      letter-spacing: .02em;
    }
    #buzz-btn {
      width: 100%;
      padding: 30px 13px;
      height: 120px;
      border: 2px solid #228;
      border-radius: 10px;
      background: #2a4a78;
      color: #ffffff;
      font-size: 2.2em;
      font-weight: bold;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    #buzz-btn:hover:not(:disabled) { background: #3a6ab8; border-color: #44f; }
    #buzz-btn:disabled { background: #555; color: #999; border-color: #666; cursor: default; opacity: 1; }
    #buzzer-order {
      margin-top: 8px;
      max-height: 130px;
      overflow-y: auto;
      text-align: left;
      font-size: 0.82em;
      color: #b8bfd3;
      border-top: 1px solid #24243a;
      padding-top: 6px;
      display: none;
    }
    .bz-row { padding: 2px 4px; border-radius: 4px; }
    .bz-row.bz-me { background: #1f2f4a; color: #d9ebff; }

    /* ── Name screen ── */
    #name-screen { text-align: center; }
    #name-input {
      width: 100%; padding: 12px;
      background: #222; border: 1px solid #444; border-radius: 8px;
      color: #fff; font-size: 1em; margin-bottom: 12px;
    }
    #name-btn {
      width: 100%; padding: 14px; background: #2a4a6a;
      border: none; border-radius: 8px;
      color: #fff; font-size: 1.05em; cursor: pointer;
    }
    #name-btn:hover { background: #3a6a9a; }
    #player-label {
      margin-left: auto; pointer-events: auto;
      font-size: 0.78em; color: #555; cursor: pointer;
    }
    #player-label:hover { color: #aaa; }

    /* ── Player list pill ── */
    /* ── Bottom-left button group (players + controls) ── */
    #bottom-left-wrap {
      position: fixed; bottom: 16px; left: 12px; z-index: 200;
      display: flex; flex-direction: row; gap: 8px; align-items: center;
    }
    #player-list-wrap {
      position: relative;
    }
    #player-list-btn {
      background: #1a1a2a; border: 1px solid #334; border-radius: 20px;
      color: #aaa; font-size: 0.82em; padding: 7px 13px; cursor: pointer;
      box-shadow: 0 2px 8px rgba(0,0,0,0.4); white-space: nowrap;
    }
    #player-list-btn:hover { color: #ccc; background: #22223a; }
    #player-list-panel {
      display: none; position: absolute; bottom: calc(100% + 6px); left: 0;
      background: #0d0d1a; border: 1px solid #334; border-radius: 10px;
      min-width: 160px; max-width: 240px; max-height: 260px; overflow-y: auto;
      padding: 6px 0; box-shadow: 0 4px 16px rgba(0,0,0,0.5);
    }
    .pl-item {
      padding: 8px 14px; font-size: 0.88em; color: #ccc;
      display: flex; align-items: center; gap: 8px; white-space: nowrap;
    }
    .pl-check { color: #5f5; }
    .pl-dot   { color: #555; }
    .pl-crown { color: #fc0; font-size: 0.85em; flex-shrink: 0; }

    /* ── Peer answers (post-submit) ── */
    #peer-answers-wrap { margin-top: 14px; }
    #peer-answers-toggle {
      width: 100%; text-align: left; background: transparent;
      border: 1px solid #2a2a3a; border-radius: 6px; color: #888;
      font-size: 0.85em; padding: 8px 12px; cursor: pointer;
      transition: color .15s, border-color .15s;
    }
    #peer-answers-toggle:hover { color: #bbb; border-color: #445; }
    #peer-answers-list {
      display: none; margin-top: 6px;
      background: #0d0d1a; border: 1px solid #2a2a3a; border-radius: 8px;
      padding: 6px 8px; max-height: 220px; overflow-y: auto;
    }
    .pa-item {
      padding: 5px 2px; border-bottom: 1px solid #1a1a2a;
      font-size: 0.88em; color: #ccc; word-break: break-word;
    }
    .pa-item:last-child { border-bottom: none; }
    .pa-name { color: #88f; font-weight: bold; }

    /* ── Anime autocomplete dropdown ── */
    .ac-wrap { position: relative; margin-bottom: 12px; }
    .ac-input {
      width: 100%; padding: 12px;
      background: #222; border: 1px solid #444; border-radius: 8px;
      color: #fff; font-size: 1em; box-sizing: border-box;
    }
    .ac-input:focus { outline: none; border-color: #4a934a; }
    .ac-drop {
      position: absolute; left: 0; right: 0;
      background: #1a1a1a; border: 1px solid #444; border-top: none;
      border-radius: 0 0 8px 8px;
      max-height: 210px; overflow-y: auto;
      z-index: 100; display: none;
    }
    .ac-item {
      padding: 10px 12px; font-size: 0.95em; color: #ccc;
      cursor: pointer; border-bottom: 1px solid #2a2a2a;
    }
    .ac-item:last-child { border-bottom: none; }
    .ac-item:hover, .ac-item.ac-active { background: #1a3d1a; color: #fff; }
    .ac-item em { color: #4a934a; font-style: normal; font-weight: bold; }

    /* ── Host answers panel ── */
    #host-toggle {
      display: none; width: 100%; margin-top: 8px; padding: 8px;
      background: #1a1a3a; border: 1px solid #334; border-radius: 6px;
      color: #88f; font-size: 0.85em; cursor: pointer;
      transition: background .15s;
    }
    #host-toggle:hover { background: #242460; }
    #host-panel {
      display: none; margin-top: 8px;
      background: #0d0d1a; border: 1px solid #334; border-radius: 8px;
      padding: 8px; max-height: 300px; overflow-y: auto;
    }
    .host-answer {
      padding: 4px 0; border-bottom: 1px solid #1a1a2a;
      font-size: 0.88em; color: #ccc; word-break: break-word;
      display: flex; align-items: baseline; gap: 6px;
    }
    .host-answer:last-child { border-bottom: none; }
    .host-answer .ha-name { color: #88f; font-weight: bold; }
    .host-answer .ha-text { flex: 1; }
    .ha-remove, .pl-remove {
      flex-shrink: 0; background: transparent; border: none;
      color: #644; font-size: 0.9em; cursor: pointer; padding: 0 2px;
      line-height: 1; border-radius: 3px;
    }
    .ha-remove:hover, .pl-remove:hover { color: #f66; background: #2a1a1a; }
    .pl-kicked { opacity: 0.45; text-decoration: line-through; }
    .pl-unban { color: #4a4; }
    .pl-unban:hover { color: #6f6; background: #1a2a1a; }

    /* ── Kick options modal ── */
    #kick-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.7); z-index: 500;
      align-items: center; justify-content: center;
    }
    #kick-overlay.active { display: flex; }
    #kick-box {
      background: #1a1a2a; border: 1px solid #446; border-radius: 12px;
      padding: 24px 20px; max-width: 290px; width: 90%; text-align: center;
    }
    #kick-player-name {
      font-size: 0.95em; color: #ccc; margin-bottom: 16px;
    }
    .kick-opt-btns { display: flex; flex-direction: column; gap: 8px; }
    .kick-opt-btns button {
      padding: 10px; border: none; border-radius: 8px;
      font-size: 0.9em; cursor: pointer;
    }
    #kick-btn-shadow { background: #3a2a1a; color: #fa8; }
    #kick-btn-shadow:hover { background: #5a3a1a; color: #fcc; }
    #kick-btn-rename { background: #1a2f1a; color: #9fd48c; }
    #kick-btn-rename:hover { background: #214021; color: #d4ffb8; }
    #kick-btn-name { background: #2a1a3a; color: #a8f; }
    #kick-btn-name:hover { background: #3a1a5a; color: #ccf; }
    #kick-btn-ip { background: #1a2a3a; color: #48f; }
    #kick-btn-ip:hover { background: #1a3a5a; color: #8cf; }
    #kick-btn-emoji { background: #1f2a16; color: #9fd48c; }
    #kick-btn-emoji:hover { background: #2b3a1d; color: #c9efb8; }
    #kick-btn-cancel { background: #222; color: #aaa; }
    #kick-btn-cancel:hover { background: #333; color: #fff; }

    /* ── Confirmation modal ── */
    #confirm-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.7); z-index: 500;
      align-items: center; justify-content: center;
    }
    #confirm-overlay.active { display: flex; }
    #confirm-box {
      background: #1a1a2a; border: 1px solid #446; border-radius: 12px;
      padding: 24px 20px; max-width: 320px; width: 90%; text-align: center;
    }
    #confirm-msg {
      font-size: 0.95em; color: #ccc; margin-bottom: 20px; line-height: 1.5;
    }
    .confirm-btns { display: flex; gap: 10px; }
    .confirm-btns button {
      flex: 1; padding: 12px; border: none; border-radius: 8px;
      font-size: 0.95em; cursor: pointer;
    }
    #confirm-yes { background: #6a1a1a; color: #f88; }
    #confirm-yes:hover { background: #8a2020; color: #fff; }
    #confirm-no  { background: #222; color: #aaa; }
    #confirm-no:hover { background: #333; color: #fff; }

    /* ── Player color swatch ── */
    .pl-swatch {
      display: inline-block; width: 12px; height: 12px;
      border-radius: 3px; border: 3px solid #444;
      flex-shrink: 0; cursor: pointer;
    }
    .pl-swatch.pl-swatch-empty { background: #333; border-style: dashed; border-width: 1px; border-color: #444; }
    #player-label-swatch {
      display: inline-block; width: 10px; height: 10px;
      border-radius: 2px; border: 3px solid #555;
      margin-left: 5px; vertical-align: middle; cursor: pointer;
    }
    #player-label-swatch.pl-swatch-empty { background: #2a2a2a; border-style: dashed; border-width: 1px; border-color: #555; }

    /* ── Color picker modal ── */
    #colorpick-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 600;
      align-items: center; justify-content: center;
    }
    #colorpick-overlay.active { display: flex; }
    #colorpick-box {
      background: #1a1a2a; border: 1px solid #446; border-radius: 12px;
      padding: 22px 20px; max-width: 340px; width: 92%;
      max-height: 90vh; overflow-y: auto;
    }
    #colorpick-title {
      font-size: 0.9em; color: #aaa; margin-bottom: 18px;
      letter-spacing: 0.05em; text-align: center;
    }
    /* page 1 */
    .colorpick-field-btn {
      display: flex; align-items: center; width: 100%; box-sizing: border-box;
      background: #22223a; border: 1px solid #334; border-radius: 8px;
      color: #ccc; font-size: 0.9em; cursor: pointer; padding: 11px 14px;
      margin-bottom: 10px; gap: 10px;
    }
    .colorpick-field-btn:hover { border-color: #556; background: #2a2a45; }
    .colorpick-field-name { text-align: left; }
    .cp-field-val { flex: 1; text-align: right; font-size: 0.75em; color: #777; padding-right: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .colorpick-field-swatch {
      width: 26px; height: 26px; border-radius: 5px;
      border: 1px solid #555; flex-shrink: 0;
    }
    .colorpick-field-swatch.cp-no-color { background: #111; border-style: dashed; }
    .colorpick-btns { display: flex; gap: 10px; margin-top: 14px; }
    .colorpick-btns button {
      flex: 1; padding: 11px; border: none; border-radius: 8px;
      font-size: 0.9em; cursor: pointer;
    }
    #colorpick-save   { background: #1a3a5a; color: #8cf; }
    #colorpick-save:hover   { background: #1a4a7a; color: #fff; }
    #colorpick-cancel { background: #222; color: #aaa; }
    #colorpick-cancel:hover { background: #333; color: #fff; }
    /* page 2 */
    .cp-p2-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
    .cp-back-btn {
      background: transparent; border: none; color: #88a;
      font-size: 0.82em; cursor: pointer; padding: 2px 4px;
    }
    .cp-back-btn:hover { color: #ccf; }
    #cp-p2-label {
      flex: 1; font-size: 0.82em; color: #aaa;
      text-align: center; text-transform: uppercase; letter-spacing: 0.06em;
    }
    .cp-clear-btn {
      background: transparent; border: 1px solid #444; border-radius: 5px;
      color: #888; font-size: 0.78em; cursor: pointer; padding: 3px 8px;
    }
    .cp-clear-btn:hover { color: #f88; border-color: #844; }
    .cp-palette {
      display: grid; grid-template-columns: repeat(8, 1fr);
      gap: 6px; margin-bottom: 12px;
    }
    .cp-swatch {
      display: block; aspect-ratio: 1; border-radius: 5px;
      border: 2px solid transparent; cursor: pointer;
      transition: border-color .1s, transform .1s;
    }
    .cp-swatch:hover { border-color: #fff; transform: scale(1.15); }
    .cp-custom-toggle {
      width: 100%; background: #22223a; border: 1px solid #334; border-radius: 7px;
      color: #88a; font-size: 0.82em; cursor: pointer; padding: 7px;
      margin-bottom: 8px; box-sizing: border-box;
    }
    .cp-custom-toggle:hover { border-color: #556; color: #ccf; }
    .cp-custom-row { display: flex; align-items: center; gap: 8px; padding: 4px 0 6px; }
    .cp-custom-row input[type=color] {
      width: 44px; height: 32px; border: 1px solid #444; border-radius: 6px;
      background: #222; cursor: pointer; padding: 2px; flex-shrink: 0;
    }
    .cp-hex-input {
      flex: 1; background: #111; border: 1px solid #444; border-radius: 5px;
      color: #ccc; font-size: 0.82em; font-family: monospace; padding: 5px 8px;
    }
    .cp-hex-input:focus { outline: none; border-color: #668; }

    /* ── Timer pill ── */
    #timer-bar {
      position: fixed; left: 50%; top: 14px; transform: translateX(-50%);
      background: #0d0d1a; border: 1px solid #334; border-radius: 20px;
      padding: 5px 18px; pointer-events: none; z-index: 301;
      transition: transform 0.25s ease;
      display: inline-flex; align-items: center; gap: 10px; white-space: nowrap; overflow: visible;
    }
    #timer-display {
      font-family: monospace; font-size: 3em; font-weight: bold;
      color: #ffffff; letter-spacing: 0.06em;
      white-space: nowrap;
      flex: 0 0 auto; margin-right: 6px;
    }
    #timer-display.timer-warning { color: #ff4444; }
    #timer-title {
      font-size: 0.9em; color: #5566aa; letter-spacing: 0.22em;
      text-transform: uppercase; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 32vw;
    }
    .tt-mobile { display: none; }
    @media (max-width: 480px) {
      #timer-title { font-size: 0.75em; letter-spacing: 0.1em; white-space: normal; text-align: center; }
      #timer-bar { padding: 5px 12px; }
      .tt-desktop { display: none; }
      .tt-mobile { display: inline; line-height: 1.1; }
    }
    h1 { display: none; }

    /* ── Fixed floating buttons ── */
    #controls-wrap {
      /* positioned inside #bottom-left-wrap, no fixed positioning needed */
    }
    #metadata-wrap {
      position: fixed; bottom: 16px; right: 12px; z-index: 200;
      display: flex; flex-direction: row; flex-wrap: nowrap; gap: 6px; align-items: center;
      transition: right 0.25s ease;
    }
    #current-time {
      background: #1a1a2a; border: 1px solid #334; border-radius: 20px;
      color: #aaa; font-size: 0.82em; padding: 7px 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
      pointer-events: none;
      min-width: 84px;
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      font-variant-numeric: tabular-nums;
      line-height: 1;
      overflow: hidden;
      white-space: nowrap;
    }
    @media (max-width: 768px) {
      #current-time { display: none; }
    }
    #current-time { order: 1; margin-right: 6px; }
    #metadata-btn { order: 2; }
    #controls-btn {
      background: #1a1a2a; border: 1px solid #334; border-radius: 20px;
      color: #aaa; font-size: 0.82em; padding: 7px 13px; cursor: pointer;
      box-shadow: 0 2px 8px rgba(0,0,0,0.4); white-space: nowrap;
    }
    #controls-btn:hover { color: #ccc; background: #22223a; }
    #metadata-btn {
      background: #1a1a2a; border: 1px solid #334; border-radius: 20px;
      color: #aaa; font-size: 0.82em; padding: 7px 13px; cursor: pointer;
      box-shadow: 0 2px 8px rgba(0,0,0,0.4); white-space: nowrap;
    }
    #metadata-btn:hover { color: #ccc; background: #22223a; }
    /* ── Controller panel close button (desktop only) ── */
    #ctrl-close-btn { display: none; }
    #meta-close-btn  { display: none; }

    /* ── Playback controller modal ── */
    #controller-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 750;
      align-items: flex-end; justify-content: center;
    }
    #controller-overlay.active { display: flex; }
    /* ── Ctrl list popup (lightning / youtube / fixed / search) ── */
    #ctrl-list-popup-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 840;
      align-items: center; justify-content: center;
    }
    #ctrl-list-popup-overlay.active { display: flex; }
    #ctrl-list-popup-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 14px;
      width: 90%; max-width: 440px; max-height: min(55vh, 480px);
      display: flex; flex-direction: column; gap: 8px;
      padding: 14px 16px 18px; box-shadow: 0 8px 32px rgba(0,0,0,0.7);
      overflow: hidden;
    }
    #ctrl-list-popup-box.search-mode { max-width: 760px; width: 96%; }
    #ctrl-list-popup-header {
      display: flex; align-items: center; justify-content: space-between;
    }
    #ctrl-list-popup-title {
      font-size: 0.8em; color: #88a; text-transform: uppercase;
      letter-spacing: .06em; font-weight: 600;
    }
    #ctrl-list-popup-close {
      background: none; border: none; color: #445; cursor: pointer;
      font-size: 1.1em; padding: 0 2px; line-height: 1;
    }
    #ctrl-list-popup-close:hover { color: #aaa; }
    #ctrl-list-popup-search-row {
      display: none; gap: 6px;
    }
    #ctrl-list-popup-search-row.active { display: flex; }
    #ctrl-list-popup-search-input {
      flex: 1; background: #0e0e1e; border: 1px solid #334; border-radius: 6px;
      color: #ccd; font-size: 0.82em; padding: 5px 8px; outline: none; min-width: 0;
    }
    #ctrl-list-popup-search-input::placeholder { color: #446; }
    #ctrl-list-popup-search-input:focus { border-color: #557; }
    #ctrl-list-popup-search-submit {
      background: #1a1a30; border: 1px solid #334; border-radius: 6px;
      color: #88a; font-size: 0.82em; padding: 5px 10px; cursor: pointer;
    }
    #ctrl-list-popup-search-submit:hover { background: #252540; color: #ccd; }
    #ctrl-list-popup-list {
      flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column;
      gap: 2px;
      scrollbar-width: thin; scrollbar-color: #334 transparent;
    }
    .ctrl-popup-item {
      padding: 8px 10px; cursor: pointer; border-radius: 6px;
      color: #ccd; font-size: 0.88em; line-height: 1.4;
      display: flex; align-items: baseline; gap: 6px;
    }
    .ctrl-popup-item:hover { background: #1a1a2e; color: #eef; }
    .ctrl-popup-item.ctrl-yt-active { background: #1a2a1a; color: #afa; }
    .ctrl-popup-divider {
      height: 1px;
      margin: 6px 8px;
      background: #2a2a3f;
      border-radius: 1px;
      opacity: 0.85;
    }
    .ctrl-popup-item-dur { color: #556; font-size: 0.85em; flex-shrink: 0; }
    .ctrl-popup-item-title { flex: 1; }
    .ctrl-popup-item-add {
      flex-shrink: 0; background: none; border: 1px solid #334; border-radius: 4px;
      color: #557; font-size: 0.8em; padding: 1px 6px; cursor: pointer; line-height: 1.4;
    }
    .ctrl-popup-item-add:hover { color: #aaf; border-color: #446; }
    .ctrl-popup-item-song { color: #778; font-size: 0.85em; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 42%; }
    .ctrl-popup-search-text {
      min-width: 0;
      display: grid;
      grid-template-rows: auto auto auto;
      gap: 2px;
      align-content: center;
    }
    .ctrl-popup-search-line {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }
    .ctrl-popup-search-line.song { color: #ccd; font-size: 0.88em; }
    .ctrl-popup-search-line.artist { color: #9aa7c6; font-size: 0.82em; }
    .ctrl-popup-search-line.meta { color: #778; font-size: 0.78em; }
    .ctrl-search-hit {
      color: #ffe8a6;
      background: rgba(180, 130, 30, 0.28);
      border-radius: 3px;
      padding: 0 2px;
    }
    .ctrl-popup-item-back {
      color: #778; font-size: 0.82em; padding: 5px 10px;
      cursor: pointer; border-radius: 6px; display: flex; align-items: center; gap: 5px;
    }
    .ctrl-popup-item-back:hover { background: #1a1a2e; color: #aab; }
    #controller-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 16px 16px 0 0;
      width: 100%; max-width: 480px; padding: 10px 20px 32px;
      display: flex; flex-direction: column; gap: 12px;
      max-height: 85vh; overflow-y: auto;
    }
    .ctrl-section {
      display: block;
    }
    /* ── Controller info toggle bar ── */
    .ctrl-collapse-toggle {
      display: flex; justify-content: space-between; align-items: center;
      cursor: pointer; padding: 5px 2px; border-bottom: 1px solid #223;
    }
    .ctrl-collapse-label {
      font-size: 0.75em; color: #88a; letter-spacing: .05em; text-transform: uppercase;
    }
    .ctrl-collapse-chevron { font-size: 0.8em; color: #556; }
    @media (min-width: 1000px) {
      #controller-box {
        padding-left: 0;
        padding-top: 0;
      }
      #ctrl-section-playlist.section-open {
        flex: 1;
        min-height: 0;
      }
      #ctrl-section-playlist.section-open > #ctrl-playlist-panel {
        min-height: 0;
      }
      .ctrl-section.section-open {
        display: grid;
        grid-template-columns: 16px minmax(0, 1fr);
        column-gap: 4px;
        align-items: stretch;
      }
      .ctrl-section.section-open > .ctrl-collapse-toggle {
        border-bottom: none;
        border-right: none;
        padding: 0;
        justify-content: center;
        min-height: 100%;
        writing-mode: vertical-rl;
        text-orientation: sideways;
        transform: rotate(180deg);
        gap: 2px;
      }
      .ctrl-section.section-open > .ctrl-collapse-toggle .ctrl-collapse-label {
        font-size: 0.6em;
        letter-spacing: .04em;
        white-space: nowrap;
      }
      .ctrl-section.section-open > .ctrl-collapse-toggle .ctrl-collapse-chevron {
        font-size: 0.62em;
      }
      .ctrl-section.section-open #ctrl-playlist-counter {
        display: inline;
        margin-left: 0;
        font-size: 0.68em;
        writing-mode: inherit;
        text-orientation: inherit;
        white-space: nowrap;
      }
      .ctrl-section.section-open > #ctrl-upnext-panel,
      .ctrl-section.section-open > #ctrl-playlist-panel,
      .ctrl-section.section-open > #ctrl-controls-panel,
      .ctrl-section.section-open > #ctrl-infotext-panel {
        min-width: 0;
      }
    }
    /* ── Scoreboard toggle button (bottom-center, host-only) ── */
    #sc-view-wrap {
      position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
      z-index: 200; display: none;
      max-height: calc(100vh - 40px); flex-direction: column;
      pointer-events: none;
      transition: transform 0.25s ease;
    }
    #sc-view-btn {
      pointer-events: auto;
    }
    #sc-view-btn {
      background: #1a1a2a; border: 1px solid #334; border-radius: 20px;
      color: #aaa; font-size: 0.82em; padding: 7px 13px; cursor: pointer;
      box-shadow: 0 2px 8px rgba(0,0,0,0.4); white-space: nowrap;
    }
    #sc-view-btn:hover { color: #ccc; background: #22223a; }
    #sc-view-btn.sc-view-active { color: #aaf; border-color: #446; background: #1a1a3a; }
    /* ── Scoreboard main view ── */
    #scoreboard-view {
      width: 100%; max-width: 520px; display: none;
      background: #1e1e1e; border-radius: 6px;
      font-family: 'Segoe UI', sans-serif; color: #e0e0e0;
      padding: 0; overflow: hidden;
      flex-direction: column; max-height: calc(100vh - 150px);
    }
    /* toolbar */
    #sc-toolbar {
      display: flex; align-items: center; gap: 4px;
      padding: 5px 6px 4px; background: #1e1e1e; border-bottom: 1px solid #2e2e2e;
    }
    #sc-toolbar-title {
      flex: 1; font-size: 0.7em; color: #555; text-transform: uppercase;
      letter-spacing: .08em; padding-left: 2px;
    }
    .sc-toolbar-btn {
      font-family: 'Segoe UI', sans-serif; font-size: 0.68em; font-weight: bold;
      border-radius: 3px; cursor: pointer; line-height: 1;
      padding: 3px 7px; border: 1px solid #555;
      background: #303030; color: #aaa;
    }
    .sc-toolbar-btn:hover { background: #404040; color: #fff; border-color: #666; }
    .sc-toolbar-btn:active { background: #202020; }
    #sc-submit-btn {
      background: #1a2040; color: #88aaff; border-color: #3355aa;
    }
    #sc-submit-btn:hover { background: #253060; border-color: #4466cc; }
    #sc-clear-btn {
      background: #2a1010; color: #cc6666; border-color: #7a2222;
      font-family: 'Segoe UI Emoji', 'Segoe UI', sans-serif; font-size: 0.85em; font-weight: normal;
      width: 24px; height: 22px; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
    }
    #sc-clear-btn:hover { background: #3a1515; border-color: #aa3333; }
    #sc-archive-btn {
      background: #3a2a10; color: #ffd38a; border-color: #9a6a22;
    }
    #sc-archive-btn:hover { background: #4a3515; border-color: #bb8a33; }
    #sc-archive-btn:active { background: #2a1d0a; }
    #sc-archive-btn:disabled {
      background: #2a2115; color: #9a8a6a; border-color: #5a4a32; cursor: default;
    }
    /* TOGETHER / AUTO toolbar toggles */
    .sc-toggle-btn {
      font-family: 'Segoe UI Emoji', 'Segoe UI', sans-serif; font-size: 0.85em;
      border-radius: 3px; cursor: pointer; line-height: 1;
      width: 24px; height: 22px; padding: 0;
      border: 1px solid #444;
      background: #252525; color: #888;
      display: inline-flex; align-items: center; justify-content: center;
    }
    .sc-toggle-btn:hover { border-color: #666; }
    .sc-toggle-btn.sc-toggle-on { color: #66dd88; border-color: #44aa60; background: #1a3022; }
    /* column headers */
    #sc-col-headers {
      display: flex; align-items: center; gap: 4px;
      padding: 2px 6px 2px 10px; background: #1e1e1e;
      border-bottom: 1px solid #2a2a2a;
    }
    .sc-ch { font-size: 0.62em; color: #555; font-family: 'Segoe UI', sans-serif; }
    #sc-ch-adjust { flex: 0 0 auto; }
    #sc-ch-score  { flex: 0 0 52px; text-align: right; }
    #sc-ch-player { flex: 1; padding-left: 8px; }
    #sc-ch-menu   { flex: 0 0 22px; }
    /* scroll area */
    #sc-scroll {
      overflow-y: auto;
      background: #1e1e1e;
    }
    #sc-scroll::-webkit-scrollbar { width: 8px; background: #1e1e1e; }
    #sc-scroll::-webkit-scrollbar-thumb { background: #444; border-radius: 4px; }
    /* player rows */
    .sc-row {
      display: flex; align-items: center; gap: 4px;
      margin: 1px 4px; padding: 0 4px;
      height: 34px; border-radius: 4px;
      border: 1px solid #2e2e2e; background: #252525;
      box-sizing: border-box; cursor: default;
    }
    .sc-row:hover { border-color: #444; }
    .sc-row.sc-ghost {
      border-color: #2a2a2a; background: #1e1e1e;
    }
    .sc-ghost-sep {
      height: 1px; background: #2a2a2a; margin: 4px 6px;
    }
    /* delta buttons */
    .sc-deltas { display: flex; gap: 2px; flex: 0 0 auto; align-items: center; }
    .sc-delta-btn {
      font-family: 'Segoe UI', sans-serif; font-size: 0.68em; font-weight: bold;
      width: 22px; height: 24px; border-radius: 3px; cursor: pointer;
      border: 1px solid; padding: 0; line-height: 1;
    }
    .sc-delta-neg { background: #5a1f1f; color: #ff8080; border-color: #7a3030; }
    .sc-delta-neg:hover { background: #7a2828; border-color: #cc5555; }
    .sc-delta-neg:active { background: #3a1010; }
    .sc-delta-pos { background: #1f4a2a; color: #66dd88; border-color: #2e6e3e; }
    .sc-delta-pos:hover { background: #286638; border-color: #44aa60; }
    .sc-delta-pos:active { background: #103020; }
    /* score cell */
    .sc-score-cell {
      flex: 0 0 52px; text-align: right;
      font-family: var(--sc-score-font, 'Consolas', monospace); font-size: 0.9em; font-weight: bold;
      color: #d0d0d0; cursor: pointer; padding: 0 2px; white-space: nowrap;
    }
    .sc-score-input {
      width: 52px; text-align: right;
      font-family: var(--sc-score-font, 'Consolas', monospace); font-size: 0.9em;
      background: #2a2a2a; border: 1px solid #777; border-radius: 3px;
      color: #e0e0e0; padding: 1px 3px;
      -moz-appearance: textfield;
    }
    .sc-score-input::-webkit-inner-spin-button,
    .sc-score-input::-webkit-outer-spin-button { display: none; }
    /* name cell */
    .sc-name-cell {
      flex: 1; font-family: var(--sc-name-font, 'Segoe UI', sans-serif); font-size: 0.85em; color: #d0d0d0;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      padding-left: 6px; cursor: pointer;
    }
    .sc-name-cell.with-swatch { padding-left: 3px; }
    .sc-name-input {
      flex: 1; font-family: var(--sc-name-font, 'Segoe UI', sans-serif); font-size: 0.85em;
      background: #2a2a2a; border: 1px solid #777; border-radius: 3px;
      color: #e0e0e0; padding: 1px 5px; min-width: 0;
    }
    /* color swatch */
    .sc-swatch {
      flex: 0 0 6px; height: 22px; border-radius: 2px;
      align-self: center;
    }
    /* menu button */
    .sc-menu-btn {
      flex: 0 0 22px; height: 28px; width: 28px;
      background: transparent; border: none; cursor: pointer;
      color: #888; font-size: 0.9em; line-height: 1;
      border-radius: 3px; padding: 0;
      touch-action: manipulation;
    }
    .sc-menu-btn:hover { color: #ccc; }
    /* add player row */
    #sc-sep { height: 1px; background: #333; margin: 3px 0; }
    #sc-add-row {
      display: flex; gap: 4px; padding: 4px 6px;
      background: #1e1e1e;
    }
    #sc-add-input {
      flex: 1; background: #2a2a2a; border: 1px solid #444; color: #e0e0e0;
      border-radius: 3px; padding: 2px 6px;
      font-family: 'Segoe UI', sans-serif; font-size: 0.82em;
    }
    #sc-add-input:focus { border-color: #777; outline: none; }
    #sc-add-btn {
      background: #303030; border: 1px solid #555; color: #aaa;
      border-radius: 3px; padding: 2px 10px; cursor: pointer;
      font-family: 'Segoe UI', sans-serif; font-size: 0.82em;
    }
    #sc-add-btn:hover { background: #404040; color: #fff; }
    /* ── Panel inline re-collapse button (replaces header when expanded) ── */
    .ctrl-panel-header { display: flex; justify-content: flex-end; padding: 2px 0 3px; margin-top: 0; }
    .ctrl-panel-close-btn {
      background: none; border: none; color: #445; cursor: pointer;
      font-size: 0.72em; padding: 0 2px; line-height: 1.4;
      text-transform: uppercase; letter-spacing: .04em;
    }
    .ctrl-panel-close-btn:hover { color: #88a; }
    /* ── Controller info panel ── */
    #ctrl-info-panel {
      font-size: 0.8em; color: #ccc; line-height: 1.6;
      padding: 0 2px 2px; text-align: center;
    }
    #ctrl-info-top {
      font-size: 0.78em; color: #88a; margin-bottom: 2px;
      white-space: pre-wrap; word-break: break-word;
    }
    #ctrl-info-main {
      font-size: 1.05em; font-weight: bold; color: #dde;
      white-space: normal; word-break: break-word;
    }
    #ctrl-info-bottom {
      font-size: 0.78em; color: #778; margin-top: 2px;
      white-space: pre-wrap; word-break: break-word;
    }
    /* ── Up Next panel ── */
    #ctrl-upnext-panel {
      font-size: 0.82em; color: #ccd; line-height: 1.5;
      padding: 0 2px 2px;
      text-align: center;
    }
    #ctrl-upnext-mode { font-size: 0.8em; color: #88a; margin-bottom: 1px; }
    #ctrl-upnext-title { font-weight: bold; color: #dde; word-break: break-word; }
    .ctrl-upnext-label { font-size: 0.78em; color: #88a; font-weight: normal; letter-spacing: .05em; }
    #ctrl-upnext-detail { font-size: 0.82em; color: #778; margin-top: 1px; }
    #ctrl-upnext-actions {
      display: flex; flex-wrap: wrap; gap: 5px; justify-content: center;
      margin-top: 4px; margin-bottom: 10px;
    }
    .ctrl-upnext-queue-btn {
      background: #12151a; border: 1px solid #3a4450; border-radius: 5px;
      color: #5a6878; font-size: 0.85em; padding: 6px 12px 6px 8px; cursor: pointer;
      transition: background .15s, color .15s;
    }
    @media (hover: hover) {
      .ctrl-upnext-queue-btn:hover { background: #3d1010; color: #f88; border-color: #f88; }
      #ctrl-upnext-reroll:hover { background: #102040; color: #9cf; border-color: #9cf; }
    }
    .ctrl-upnext-queue-btn.ctrl-toggle-active {
      background: #3a1010; border-color: #cc5050; color: #ff8888;
      box-shadow: 0 0 6px 0 rgba(200,60,60,0.5);
    }
    #ctrl-upnext-reroll {
      background: #071825; border-color: #1a6090; color: #44aadd;
      box-shadow: 0 0 5px 0 rgba(30,120,200,0.25);
    }
    @media (hover: hover) {
      #ctrl-upnext-reroll:hover { background: #0d2a40; color: #88ccff; border-color: #3399cc; box-shadow: 0 0 8px 0 rgba(30,150,220,0.45); }
    }
    /* ── Controls panel sub-grid spacing ── */
    #ctrl-controls-panel {
      display: flex; flex-direction: row; flex-wrap: wrap; gap: 7px;
      justify-content: center; padding: 4px 0;
    }
    /* ── Bonus panel ── */
    #ctrl-bonus-panel {
      padding: 0 2px 2px;
    }
    #ctrl-bonus-grid {
      display: flex; flex-wrap: wrap; gap: 7px; justify-content: center;
    }
    .ctrl-bonus-btn {
      background: #1a1a30; border: 1px solid #334; border-radius: 5px;
      color: #aac; font-size: 0.78em; padding: 5px 10px; cursor: pointer;
      transition: background .15s, color .15s;
      min-width: 54px; text-align: center; line-height: 1.2;
    }
    .ctrl-bonus-btn:hover { background: #252540; color: #ddf; }
    .ctrl-bonus-btn.ctrl-bonus-more {
      background: none; border-color: #223; color: #556; font-size: 0.88em;
      padding: 8px 10px;
    }
    .ctrl-bonus-btn.ctrl-bonus-more:hover { color: #88a; border-color: #334; }
    /* ── Button section color coding ── */
    .ctrl-sect-queue  { background: #211507; border-color: #5a4723; color: #e0b062; box-shadow: none; }
    .ctrl-sect-queue:hover  { background: #31200b; color: #ffd48a; border-color: #ffcf70; box-shadow: 0 0 5px 0 rgba(220,160,40,0.40); }
    .ctrl-sect-bonus  { background: #0c1220; border-color: #334; color: #6af; box-shadow: none; }
    .ctrl-sect-bonus:hover  { background: #102040; color: #9cf; border-color: #9cf; box-shadow: 0 0 5px 0 rgba(30,100,200,0.40); }
    .ctrl-sect-toggle { background: #12151a; border-color: #334; color: #7a8898; }
    .ctrl-sect-toggle:hover { background: #1a2028; color: #aabbd0; border-color: #6a7a90; }
    .ctrl-sect-reveal { background: #0c1810; border-color: #334; color: #6c6; box-shadow: none; }
    .ctrl-sect-reveal:hover { background: #102818; color: #9e9; border-color: #9e9; box-shadow: 0 0 5px 0 rgba(40,140,60,0.40); }
    .ctrl-sect-mark   { background: #1a0c14; border-color: #334; color: #c88; box-shadow: none; }
    .ctrl-sect-mark:hover   { background: #2a1020; color: #eaa; border-color: #eaa; box-shadow: 0 0 5px 0 rgba(140,40,80,0.40); }
    .ctrl-sect-session { background: #1e0c0c; border-color: #5a2d2d; color: #d96a6a; box-shadow: none; }
    .ctrl-sect-session:hover { background: #2e1010; color: #ff9a9a; border-color: #ff8a8a; box-shadow: 0 0 5px 0 rgba(180,50,50,0.40); }
    /* Scoreboard-specific color (distinct) */
    .ctrl-sect-scoreboard { background: #2a083a; border-color: #334; color: #f6a; box-shadow: none; }
    .ctrl-sect-scoreboard:hover { background: #3a0f50; color: #ffd; border-color: #e6a; box-shadow: 0 0 5px 0 rgba(200,80,160,0.40); }
    /* ── Extras popup ── */
    #ctrl-extras-popup-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 820;
      align-items: center; justify-content: center;
    }
    #ctrl-extras-popup-overlay.active { display: flex; }
    #ctrl-extras-popup-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 14px;
      width: 95%; max-width: 680px; max-height: min(70vh, 560px);
      display: flex; flex-direction: column; gap: 10px;
      padding: 14px 16px 18px; box-shadow: 0 8px 32px rgba(0,0,0,0.7);
      overflow-y: auto; scrollbar-width: thin; scrollbar-color: #334 transparent;
    }
    #ctrl-extras-popup-header {
      display: flex; align-items: center; justify-content: space-between;
    }
    #ctrl-extras-popup-title {
      font-size: 0.8em; color: #88a; text-transform: uppercase;
      letter-spacing: .06em; font-weight: 600;
    }
    #ctrl-extras-popup-close {
      background: none; border: none; color: #445; cursor: pointer;
      font-size: 1.1em; padding: 0 2px; line-height: 1;
    }
    #ctrl-extras-popup-close:hover { color: #aaa; }
    .ctrl-extras-sect-label {
      font-size: 0.65em; color: #556; text-transform: uppercase;
      letter-spacing: 0.06em; width: 100%;
    }
    .ctrl-extras-sect-row {
      display: flex; flex-wrap: wrap; gap: 5px; align-items: center;
    }
    #ctrl-extras-edit-btn {
      background: none; border: 1px solid #334; border-radius: 5px;
      color: #556; font-size: 0.72em; padding: 3px 8px; cursor: pointer;
      transition: color .15s, border-color .15s;
    }
    #ctrl-extras-edit-btn:hover { color: #88a; border-color: #668; }
    #ctrl-extras-edit-btn.active { color: #adf; border-color: #adf; }
    #ctrl-extras-edit-hint {
      display: none; font-size: 0.68em; color: #667; text-align: center;
      padding: 2px 0;
    }
    #ctrl-extras-edit-hint.active { display: block; }
    #ctrl-extras-popup-box.edit-mode .ctrl-bonus-btn[data-extra-id] {
      opacity: 0.35; cursor: pointer;
    }
    #ctrl-extras-popup-box.edit-mode .ctrl-bonus-btn[data-extra-id].ctrl-extra-pinned {
      opacity: 1; outline: 2px solid currentColor; outline-offset: 1px;
    }
    #ctrl-extras-popup-box.edit-mode .ctrl-bonus-btn[data-extra-id]:hover { opacity: 0.7; }
    #ctrl-extras-popup-box.edit-mode .ctrl-bonus-btn[data-extra-id].ctrl-extra-pinned:hover { opacity: 1; }
    #ctrl-pinned-extras { display: contents; }
    .ctrl-pinned-break { flex-basis: 100%; height: 0; min-width: 100%; }
    .ctrl-pinned-space { width: 16px; flex-shrink: 0; }
    .ctrl-layout-chip { display:inline-flex; align-items:center; gap:3px; font-size:0.72em; color:#778; background:#0a0a18; border:1px solid #223; border-radius:4px; padding:2px 5px; }
    .ctrl-layout-chip-remove { background:none; border:none; color:#445; cursor:pointer; font-size:0.88em; padding:0 0 0 2px; line-height:1; }
    .ctrl-layout-chip-remove:hover { color:#c88; }
    .ctrl-sect-div {
      width: 1px; height: 24px; background: #334;
      align-self: center; flex-shrink: 0; margin: 0 3px;
    }
    .ctrl-sect-break {
      flex-basis: 100%; height: 0; margin: 0;
    }
    /* ── Info reveal buttons ── */
    #ctrl-info-reveal {
      display: flex; flex-wrap: wrap; gap: 7px; justify-content: center;
      padding: 4px 2px;
    }
    .ctrl-info-reveal-btn {
      background: #12122a; border: 1px solid #2a2a44; border-radius: 6px;
      color: #88a; font-size: 0.88em; padding: 8px 14px; cursor: pointer;
      transition: background .15s, color .15s;
    }
    .ctrl-info-reveal-btn:hover { background: #1e1e3a; color: #ccf; }
    /* ── Mark buttons active state ── */
    .ctrl-mark-btn.ctrl-mark-active { background: #2a1020; border-color: #ee88aa; color: #ffbbcc; box-shadow: 0 0 7px 0 rgba(200,80,120,0.50); }
    .ctrl-mark-btn.ctrl-mark-active:hover { background: #3a1428; border-color: #ffaac0; color: #ffd0dd; }
    /* ── Toggle buttons active state ── */
    #ctrl-toggles-panel { padding: 0 2px 2px; }
    #ctrl-toggles-grid { display: flex; flex-wrap: wrap; gap: 7px; justify-content: center; }
    .ctrl-toggle-btn.ctrl-toggle-active { background: #0d1e2c; border-color: #99bbdd; color: #cce0f5; box-shadow: 0 0 7px 0 rgba(130,180,230,0.50); }
    .ctrl-toggle-btn.ctrl-toggle-active:hover { background: #122438; color: #ddf0ff; border-color: #bbddee; }
    .ctrl-toggle-btn.ctrl-sect-queue.ctrl-toggle-active { background: #3a240a; border-color: #ffd15a; color: #fff0c2; box-shadow: 0 0 7px 0 rgba(235,180,60,0.55); }
    .ctrl-toggle-btn.ctrl-sect-queue.ctrl-toggle-active:hover { background: #4a2d0d; border-color: #ffe08a; color: #fff6d8; }
    .ctrl-sect-session.ctrl-toggle-active { background: #341212; border-color: #ff7a7a; color: #ffd1d1; box-shadow: 0 0 8px 0 rgba(220,80,80,0.55); }
    .ctrl-sect-session.ctrl-toggle-active:hover { background: #431616; border-color: #ffa0a0; color: #ffe2e2; }
    .ctrl-sect-scoreboard.ctrl-toggle-active { background: #3a0f50; border-color: #ff88cc; color: #ffd6ee; box-shadow: 0 0 9px 0 rgba(210,95,180,0.60); }
    .ctrl-sect-scoreboard.ctrl-toggle-active:hover { background: #4a1464; border-color: #ffb3dd; color: #ffe6f5; }
    /* Info reveal buttons: highlight while the matching popup is showing */
    .ctrl-sect-reveal.ctrl-reveal-active { background: #0e2814; border-color: #44ee77; color: #88ffaa; box-shadow: 0 0 8px 1px rgba(50,230,90,0.55); }
    .ctrl-sect-reveal.ctrl-reveal-active:hover { background: #143820; border-color: #77ffaa; color: #bbffcc; }
    .ctrl-bonus-btn.ctrl-bonus-active { background: #0a2050; border-color: #55aaff; color: #aaddff; box-shadow: 0 0 7px 0 rgba(50,140,255,0.50); }
    .ctrl-bonus-btn.ctrl-bonus-active:hover { background: #0e2a66; border-color: #88ccff; color: #cceeff; }
    /* Make Buzz Lock state much more obvious when enabled */
    [data-extra-id="buzz_lock"].ctrl-toggle-active,
    [data-proxy-extra="buzz_lock"].ctrl-toggle-active {
      background: #4a1717;
      border-color: #ff6a6a;
      color: #ffd4d4;
      box-shadow: 0 0 7px 0 rgba(255, 80, 80, 0.40);
    }
    [data-extra-id="buzz_lock"].ctrl-toggle-active:hover,
    [data-proxy-extra="buzz_lock"].ctrl-toggle-active:hover {
      background: #5c1c1c;
      border-color: #ff8a8a;
      color: #ffe4e4;
    }
    /* ── Seek row ── */
    #ctrl-seek-row {
      display: flex; align-items: center; gap: 8px;
    }
    #ctrl-seek-row span {
      font-size: 0.75em; color: #88a; min-width: 2.8em; text-align: center;
      font-variant-numeric: tabular-nums;
    }
    #ctrl-seek {
      flex: 1; -webkit-appearance: none; appearance: none;
      height: 4px; border-radius: 2px; background: #334; outline: none;
      cursor: pointer;
    }
    #ctrl-seek::-webkit-slider-thumb {
      -webkit-appearance: none; width: 16px; height: 16px;
      border-radius: 50%; background: #88f; cursor: pointer;
    }
    #ctrl-seek::-moz-range-thumb {
      width: 16px; height: 16px; border-radius: 50%;
      background: #88f; cursor: pointer; border: none;
    }
    /* ── Main row (volume | buttons | autoplay) ── */
    #ctrl-main-row {
      display: grid; grid-template-columns: 1fr auto 1fr;
      align-items: center;
    }
    #ctrl-vol-wrap { justify-self: start; }
    #ctrl-buttons {
      display: flex; justify-content: center; gap: 2px;
    }
    #ctrl-autoplay-wrap { justify-self: end; }
    .ctrl-btn {
      background: none; border: none;
      color: #ccc; font-size: 2em;
      cursor: pointer; padding: 4px 6px;
      transition: color 0.15s; flex-shrink: 0; line-height: 1;
    }
    .ctrl-btn:hover { color: #fff; }
    .ctrl-btn:active { color: #aaf; }
    .ctrl-btn-sm { font-size: 1.4em; padding: 4px; }
    .ctrl-btn-autoplay { font-size: 1.4em; padding: 4px; }
    .ctrl-btn-autoplay.mode-0 { color: #ccc; }
    .ctrl-btn-autoplay.mode-1 { color: #ccc; }
    .ctrl-btn-autoplay.mode-2 { opacity: 0.35; }
    /* ── Volume slider popup (horizontal) ── */
    #ctrl-vol-wrap { position: relative; display: flex; align-items: center; }
    #ctrl-vol-slider-wrap {
      position: absolute; bottom: 52px; left: 0;
      background: #1a1a30; border: 1px solid #334; border-radius: 10px;
      padding: 8px 12px; display: flex; flex-direction: column;
      align-items: stretch; gap: 6px; z-index: 10; white-space: nowrap;
    }
    #ctrl-vol-slider {
      -webkit-appearance: none; appearance: none;
      width: 130px; height: 4px; border-radius: 2px;
      background: #334; outline: none; cursor: pointer;
    }
    #ctrl-vol-slider::-webkit-slider-thumb {
      -webkit-appearance: none; width: 14px; height: 14px;
      border-radius: 50%; background: #88f; cursor: pointer;
    }
    #ctrl-vol-slider::-moz-range-thumb {
      width: 14px; height: 14px; border-radius: 50%;
      background: #88f; cursor: pointer; border: none;
    }
    #ctrl-vol-label { font-size: 0.7em; color: #88a; min-width: 2em; text-align: right; }
    #ctrl-vol-slider-row { display: flex; align-items: center; gap: 8px; }
    /* ── BZZ row inside volume popup ── */
    #ctrl-bzz-row {
      display: flex; align-items: center; gap: 8px;
      border-bottom: 1px solid #334; padding-bottom: 6px; margin-bottom: 2px;
    }
    #ctrl-bzz-label-hd { font-size: 0.7em; color: #88a; white-space: nowrap; }
    #ctrl-bzz-slider {
      -webkit-appearance: none; appearance: none;
      width: 100px; height: 4px; border-radius: 2px;
      background: #334; outline: none; cursor: pointer;
    }
    #ctrl-bzz-slider::-webkit-slider-thumb {
      -webkit-appearance: none; width: 14px; height: 14px;
      border-radius: 50%; background: #88f; cursor: pointer;
    }
    #ctrl-bzz-slider::-moz-range-thumb {
      width: 14px; height: 14px; border-radius: 50%;
      background: #88f; cursor: pointer; border: none;
    }
    #ctrl-bzz-label { font-size: 0.7em; color: #88a; min-width: 2.5em; text-align: right; }
    /* ── BGM row inside volume popup ── */
    #ctrl-bgm-row {
      display: flex; align-items: center; gap: 8px;
      border-bottom: 1px solid #334; padding-bottom: 6px; margin-bottom: 2px;
    }
    #ctrl-bgm-label-hd { font-size: 0.7em; color: #88a; white-space: nowrap; }
    #ctrl-bgm-slider {
      -webkit-appearance: none; appearance: none;
      width: 100px; height: 4px; border-radius: 2px;
      background: #334; outline: none; cursor: pointer;
    }
    #ctrl-bgm-slider::-webkit-slider-thumb {
      -webkit-appearance: none; width: 14px; height: 14px;
      border-radius: 50%; background: #88f; cursor: pointer;
    }
    #ctrl-bgm-slider::-moz-range-thumb {
      width: 14px; height: 14px; border-radius: 50%;
      background: #88f; cursor: pointer; border: none;
    }
    #ctrl-bgm-label { font-size: 0.7em; color: #88a; min-width: 2.5em; text-align: right; }
    #metadata-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 700;
      align-items: flex-end; justify-content: center;
    }
    #metadata-overlay.active { display: flex; }
    #metadata-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 16px 16px 0 0;
      width: 100%; max-width: 480px; padding: 16px 12px 28px;
      max-height: 85vh; display: flex; flex-direction: column; gap: 10px;
    }
    #meta-history-nav {
      display: flex; flex-direction: column; align-items: center; gap: 4px;
      font-size: 0.75em; color: #556; margin-top: -4px;
    }
    #meta-nav-title {
      font-size: 1.1em; color: #ccd; font-weight: 600; text-align: center;
      word-break: break-word;
    }
    #meta-nav-arrows {
      display: flex; align-items: center; justify-content: center; gap: 4px; width: 100%;
    }
    #meta-nav-arrows.visible { display: flex; }
    #meta-nav-autofollow {
      background: none; border: 1px solid #334; border-radius: 4px;
      color: #556; cursor: pointer; font-size: 0.9em; padding: 2px 6px; line-height: 1.4;
      white-space: nowrap;
    }
    #meta-nav-autofollow.on { color: #8f8; border-color: #4a4; }
    @media (hover: hover) { #meta-nav-autofollow:hover { color: #aaf; border-color: #55a; } }
    .meta-history-btn {
      background: none; border: 1px solid #334; border-radius: 4px;
      color: #88a; cursor: pointer; font-size: 1em; padding: 2px 8px; line-height: 1.4;
    }
    .meta-history-btn.meta-skip-btn { padding: 2px 5px; font-size: 0.85em; }
    .meta-history-btn:disabled { color: #334; border-color: #223; cursor: default; }
    @media (hover: hover) { .meta-history-btn:not(:disabled):hover { color: #bbf; border-color: #55a; } }
    #meta-history-label { min-width: 36px; text-align: center; flex: 1; }
    /* ── Tab bar ── */
    .meta-tabs {
      display: flex; gap: 0; border-bottom: 1px solid #334; margin-bottom: 4px;
    }
    .meta-tab-btn {
      flex: 1; padding: 8px 4px; background: transparent;
      border: none; border-bottom: 2px solid transparent;
      color: #556; font-size: 0.82em; text-transform: uppercase;
      letter-spacing: .07em; cursor: pointer;
    }
    .meta-tab-btn.active { color: #aaf; border-bottom-color: #446; }
    .meta-tab-btn:hover:not(.active) { color: #88a; }
    .meta-tab-pane { display: none; flex: 1; overflow-y: auto; min-height: 0; }
    .meta-tab-pane.active { display: block; }
    #meta-info-head {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      margin: 2px 0 6px;
    }
    #meta-cover-wrap {
      display: none;
      justify-content: flex-start;
      margin: 0;
      flex: 0 0 auto;
    }
    #meta-cover-wrap.active { display: flex; }
    #meta-cover-btn {
      background: #101020;
      border: 1px solid #334;
      border-radius: 8px;
      padding: 3px;
      cursor: pointer;
      line-height: 0;
    }
    #meta-cover-btn:hover { border-color: #557; background: #15152b; }
    #meta-cover-img {
      display: block;
      width: 92px;
      height: 130px;
      object-fit: cover;
      border-radius: 6px;
      background: #0a0a14;
    }
    #meta-theme-head {
      flex: 1;
      min-width: 0;
      font-size: 0.84em;
      line-height: 1.5;
      color: #ccc;
    }
    #meta-theme-head .meta-row { margin-bottom: 0; }
    #meta-cover-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.86); z-index: 862;
      align-items: center; justify-content: center;
      padding: 16px;
    }
    #meta-cover-overlay.active { display: flex; }
    #meta-cover-full {
      max-width: min(92vw, 540px);
      max-height: 90vh;
      object-fit: contain;
      border-radius: 10px;
      border: 1px solid #334;
      background: #111;
      box-shadow: 0 12px 36px rgba(0,0,0,0.5);
    }
    /* ── Playlist tab pane needs flex column so vscroll fills height ── */
    #meta-pane-playlist { display: none; flex-direction: column; overflow: hidden; }
    #meta-pane-playlist.active { display: flex; }
    /* Mobile: fixed height for playlist scroll area */
    #ctrl-playlist-panel #pl-vscroll { height: 110px; }
    /* Playlist panel as flex column so inner vscroll can fill it */
    #ctrl-playlist-panel { flex-direction: column; overflow: hidden; }
    #pl-vscroll { overflow-y: auto; position: relative; }
    #pl-spacer  { position: relative; width: 100%; }
    .pl-row {
      position: absolute; left: 0; right: 0; height: 22px;
      display: flex; align-items: center; padding: 0 6px; gap: 4px;
      font-size: 0.75em; color: #ccd; box-sizing: border-box;
      cursor: pointer; border-bottom: 1px solid rgba(40,40,60,0.5);
    }
    .pl-row:hover { background: #1a1a2e; color: #eef; }
    .pl-row.pl-current { background: #1a1a2e; color: #aaf; font-weight: bold; }
    .pl-row-num   { color: #445; font-size: 0.78em; min-width: 32px; text-align: right; flex-shrink: 0; }
    .pl-row-slug  { color: #88f; font-size: 0.82em; flex-shrink: 0; }
    .pl-row-lightning { font-size: 0.85em; flex-shrink: 0; line-height: 1; }
    .pl-row-title { flex: 1; overflow: hidden; white-space: nowrap; }
    .pl-row-song  { color: #778; font-size: 0.82em; flex-shrink: 0;
                    max-width: 38%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    /* ── Info tab ── */
    #metadata-content {
      font-size: 0.85em; line-height: 1.8; color: #ccc;
    }
    .meta-row { margin-bottom: 1px; word-break: break-word; }
    .meta-label { color: #88f; font-weight: bold; }
    .meta-theme-row { display: flex; gap: 0.4em; align-items: baseline; }
    .mt-theme-content { flex: 1; }
    .mt-continuation { display: block; }
    .mt-fav-mark {
      display: inline-block; margin-left: 6px; color: #ff7aa8;
      font-size: 0.92em; line-height: 1; vertical-align: middle;
    }
    .mt-fav-mark.leading { margin-left: 0; margin-right: 0; }
    .mt-fav-mark.playing { color: #ff94ba; }
    /* ── Themes tab ── */
    #metadata-themes-content { font-size: 0.84em; color: #ccc; }
    .mt-anime-header {
      font-size: 0.8em; color: #88a; font-weight: bold;
      text-transform: uppercase; letter-spacing: .06em;
      margin: 8px 0 4px; border-top: 1px solid #223; padding-top: 6px;
    }
    .mt-anime-header:first-child { border-top: none; margin-top: 0; }
    .mt-section-header {
      font-size: 0.78em; color: #556; text-transform: uppercase;
      letter-spacing: .05em; margin: 6px 0 2px;
    }
    .mt-theme {
      padding: 3px 6px; border-bottom: 1px solid #1a1a2a;
      border-radius: 4px; margin: 1px 0;
      line-height: 1.6;
    }
    .mt-theme:last-child { border-bottom: none; }
    .mt-theme.playing {
      background: #0e1e30; border: 1px solid #2a4a6a;
      border-bottom: 1px solid #2a4a6a;
    }
    .mt-slug { color: #88f; }
    .mt-slug.playing { color: #88f; }
    .mt-title { color: #ccc; }
    .mt-artist { color: #777; font-size: 0.92em; }
    .mt-artist-item { display: inline-block; }
    .artist-themes-btn { background: #181825; border: 1px solid #334; color: #88f; padding: 2px 6px; margin-left: 4px; cursor: pointer; border-radius: 2px; font-size: 0.85em; font-weight: bold; }
    .artist-themes-btn:hover { background: #1f1f35; border-color: #446; color: #aaf; }
    .studio-themes-btn { background: #17201c; border: 1px solid #2f4a3b; color: #8fd5b1; padding: 2px 6px; margin-left: 4px; cursor: pointer; border-radius: 2px; font-size: 0.85em; font-weight: bold; }
    .studio-themes-btn:hover { background: #1b2a23; border-color: #3d6350; color: #b7f3d5; }
    .mt-ver { color: #555; font-size: 0.85em; margin-left: 10px; }
    .mt-ver.playing { color: #8cf; }
    .mt-ver .mt-fav-mark { font-size: 1em; }
    .mt-flags { color: #a88; font-size: 0.82em; }
    .mt-props { color: #555; font-size: 0.80em; }
    .mt-main-row { display: block; }
    .mt-main-row .mt-title { flex: none; }
    .mt-sub-row {
      display: flex; align-items: center; gap: 6px;
    }
    .mt-sub-row-indent { margin-left: 10px; }
    .mt-sub-row .mt-ver { margin-left: 0; }
    .mt-action-btn {
      background: #1a1a2e;
      border: 1px solid #334;
      color: #88a;
      border-radius: 5px;
      padding: 0px 7px;
      font-size: 0.82em;
      cursor: pointer;
      line-height: 1.4;
    }
    .mt-action-btn:hover { background: #24243c; border-color: #557; color: #bbf; }
    #theme-action-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 861;
      align-items: center; justify-content: center;
      padding: 14px;
    }
    #theme-action-overlay.active { display: flex; }
    #pl-entry-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 861;
      align-items: center; justify-content: center; padding: 14px;
    }
    #pl-entry-overlay.active { display: flex; }
    #pl-entry-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 12px;
      width: min(90vw, 420px);
      display: flex; flex-direction: column; gap: 10px; padding: 12px;
    }
    #pl-entry-title {
      color: #aaf; font-size: 0.88em; line-height: 1.35;
      border-bottom: 1px solid #223; padding-bottom: 8px; word-break: break-word;
    }
    #theme-action-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 12px;
      width: min(90vw, 420px);
      display: flex; flex-direction: column; gap: 10px;
      padding: 12px;
    }
    #theme-action-title {
      color: #aaf; font-size: 0.88em; line-height: 1.35;
      border-bottom: 1px solid #223; padding-bottom: 8px;
      word-break: break-word;
    }
    .theme-action-btn {
      width: 100%; text-align: left;
      background: #151525; border: 1px solid #334; color: #ccd;
      border-radius: 8px; padding: 10px 12px; cursor: pointer;
      font-size: 0.9em;
    }
    .theme-action-btn:hover { background: #1d1d33; border-color: #557; color: #eef; }
    .theme-action-btn.play { border-color: #3a5; color: #8fd; }
    .theme-action-btn.queue { border-color: #557; color: #9cf; }
    .theme-action-btn.add { border-color: #775; color: #fdc; }
    #theme-action-cancel {
      margin-top: 2px;
      background: #222; border: 1px solid #444;
      border-radius: 8px; color: #aaa; cursor: pointer;
      font-size: 0.9em; padding: 10px;
    }
    #theme-action-cancel:hover { background: #333; color: #fff; }
    #artist-themes-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.75); z-index: 860;
      align-items: center; justify-content: center;
      padding: 14px;
    }
    #artist-themes-overlay.active { display: flex; }
    #artist-themes-box {
      background: #0d0d1a; border: 1px solid #334; border-radius: 12px;
      width: min(90vw, 620px); max-height: 80vh;
      display: flex; flex-direction: column; overflow: hidden;
    }
    #artist-themes-title {
      padding: 12px 14px; color: #aaf; font-size: 0.9em;
      letter-spacing: .04em; text-transform: uppercase;
      border-bottom: 1px solid #223;
    }
    #artist-themes-content {
      padding: 12px 14px; overflow: auto;
      color: #bbb; line-height: 1.45; font-size: 0.86em;
      background: #111;
      max-height: min(62vh, 620px);
    }
    .artist-themes-summary {
      color: #8aa; font-size: 0.8em; margin-bottom: 10px;
      letter-spacing: .03em; text-transform: uppercase;
    }
    .artist-themes-list { display: flex; flex-direction: column; gap: 8px; }
    .artist-theme-row {
      background: #151525; border: 1px solid #2b2b45; border-radius: 8px;
      padding: 8px 10px;
    }
    .artist-theme-title {
      color: #d9dcff; font-weight: 700;
      line-height: 1.3;
      display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    }
    .artist-theme-chip {
      display: inline-block;
      padding: 1px 7px;
      border-radius: 999px;
      background: #1d2840;
      border: 1px solid #35527a;
      color: #9cc5ff;
      font-size: 0.78em;
      line-height: 1.55;
    }
    .artist-theme-play-btn {
      cursor: pointer;
      transition: background .12s, border-color .12s, color .12s;
    }
    .artist-theme-play-btn:hover { background: #243455; border-color: #5a7fc0; color: #c8e0ff; }
    .artist-theme-play-btn:active { background: #2a3d66; border-color: #7a9fd8; }
    .studio-series-group {
      display: flex; flex-direction: column; gap: 6px;
    }
    .studio-series-title {
      color: #8893b8; font-size: 0.73em; text-transform: uppercase;
      letter-spacing: .06em; margin: 2px 2px 0;
    }
    .artist-themes-empty {
      color: #666; text-align: center; padding: 10px 0;
    }
    #artist-themes-close {
      margin: 10px; padding: 10px; background: #222; border: 1px solid #444;
      border-radius: 8px; color: #aaa; cursor: pointer; font-size: 0.92em;
    }
    #artist-themes-close:hover { background: #333; color: #fff; }
    /* ── More tab ── */
    #metadata-more-content { font-size: 0.84em; color: #ccc; }
    .more-sub-tabs { display: flex; gap: 4px; margin-bottom: 6px; flex-wrap: wrap; }
    .more-sub-btn { padding: 3px 8px; background: #181825; border: 1px solid #334; border-radius: 3px; color: #556; font-size: 0.78em; text-transform: uppercase; letter-spacing: .06em; cursor: pointer; }
    .more-sub-btn.active { color: #aaf; border-color: #446; background: #1a1a35; }
    .more-sub-btn:hover:not(.active) { color: #88a; }
    .more-char-tabs { display: flex; gap: 0; border-bottom: 1px solid #334; margin-bottom: 8px; }
    .more-char-tab-btn { flex: 1; padding: 6px 4px; background: transparent; border: none; border-bottom: 2px solid transparent; color: #556; font-size: 0.82em; text-transform: uppercase; letter-spacing: .07em; cursor: pointer; }
    .more-char-tab-btn.active { color: #aaf; border-bottom-color: #446; }
    .more-char-tab-btn:hover:not(.active) { color: #88a; }
    .more-synopsis { color: #ccc; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
    .more-section { margin: 6px 0 4px; }
    .more-section-header { font-size: 0.78em; color: #88a; font-weight: bold; text-transform: uppercase; letter-spacing: .06em; margin: 8px 0 4px; border-top: 1px solid #223; padding-top: 6px; }
    .more-section-header:first-child { border-top: none; margin-top: 0; }
    .more-tag { display: inline-block; margin: 2px; padding: 1px 5px; background: #181825; border-radius: 3px; color: #aac; font-size: 0.82em; }
    .more-tag.spoiler { color: #a66; }
    .more-char { padding: 3px 0; border-bottom: 1px solid #1a1a2a; line-height: 1.5; }
    .more-char-name { color: #fff; font-weight: bold; }
    .more-char-role { color: #556; font-size: 0.82em; margin-left: 6px; }
    .more-char-va { color: #778; font-size: 0.82em; }
    .more-char-desc { color: #666; font-size: 0.82em; margin-top: 2px; white-space: pre-wrap; word-break: break-word; }
    .more-ep { padding: 1px 0; }
    .more-ep-num { color: #88f; font-weight: bold; margin-right: 6px; }
    /* ── Links tab ── */
    .meta-link-row {
      display: flex; align-items: center; gap: 10px;
      padding: 10px 8px; border-radius: 6px; text-decoration: none;
      border-bottom: 1px solid rgba(60,60,90,0.4); color: #ccd;
    }
    .meta-link-row:hover { background: #1a1a2e; color: #eef; }
    .meta-link-icon { font-size: 1.1em; flex-shrink: 0; }
    .meta-link-label { font-weight: bold; min-width: 110px; flex-shrink: 0; }
    .meta-link-url { color: #557; font-size: 0.78em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    /* ── Close button ── */
    #metadata-close-btn {
      padding: 11px; background: #222; border: 1px solid #444;
      border-radius: 8px; color: #aaa; font-size: 0.95em; cursor: pointer;
    }
    #metadata-close-btn:hover { background: #333; color: #fff; }

    /* ── Wide-screen layout (≥900px) ── */
    @media (min-width: 900px) {
      body {
        padding: 60px 20px 92px;
        transition: padding-left 0.25s ease, padding-right 0.25s ease;
      }
      .box { max-width: 660px; }

      /* Controller shifts content left; metadata shifts content right */
      body.ctrl-open  { padding-left:  calc(360px + 20px); }
      body.meta-open  { padding-right: calc(360px + 20px); }

      /* Controller: LEFT-side panel — overlay is non-blocking so page stays interactive */
      #controller-overlay {
        background: transparent;
        align-items: stretch;
        justify-content: flex-start;
        pointer-events: none;
      }
      #controller-overlay.active { display: flex; }
      #controller-box {
        border-radius: 0;
        width: 360px;
        max-width: 360px;
        height: 100%;
        max-height: none;
        padding: 14px 14px 20px;
        overflow-y: auto;
        border-right: 1px solid #334;
        border-left: none;
        border-top: none;
        pointer-events: auto;
      }

      /* Metadata: right-side panel — same non-blocking approach */
      #metadata-overlay {
        background: transparent;
        align-items: stretch;
        justify-content: flex-end;
        pointer-events: none;
      }
      #metadata-overlay.active { display: flex; }
      #metadata-box {
        border-radius: 0;
        width: 360px;
        max-width: 360px;
        height: 100%;
        max-height: none;
        padding: 14px 12px 20px;
        border-left: 1px solid #334;
        border-top: none;
        pointer-events: auto;
      }

      /* Shift bottom-left group and top-bar when panels are open */
      body.ctrl-open #top-bar           { left: 360px; }
      body.ctrl-open #bottom-left-wrap   { left: calc(360px + 12px); }
      body.meta-open #top-bar            { right: 360px; }
      body.meta-open #metadata-wrap      { right: calc(360px + 12px); }
      /* Shift centered elements (timer / bottom-center buttons) so they stay centered with content */
      body.meta-open #timer-bar, body.meta-open #sc-view-wrap {
        transform: translateX(calc(-50% - 180px));
      }
      body.ctrl-open #timer-bar, body.ctrl-open #sc-view-wrap {
        transform: translateX(calc(-50% + 180px));
      }
      /* Both panels open: keep centered elements centered between panels */
      body.ctrl-open.meta-open #timer-bar,
      body.ctrl-open.meta-open #sc-view-wrap {
        transform: translateX(-50%);
      }
      #bottom-left-wrap { transition: left 0.25s ease; }

      /* Hide Theme Information text in controller — info panel on the right covers it */
      /* (ctrl-info-top/main/bottom are now in the Info tab of ctrl-info-panel) */

      /* Hide controller Info section on widescreen — metadata panel already shows info */
      #ctrl-infotext-toggle { display: none !important; }
      #ctrl-infotext-panel { display: none !important; }

      /* Close button inside controller panel */
      #controller-box { position: relative; }
      /* Playlist expands to fill remaining vertical space on desktop */
      #ctrl-playlist-panel {
        flex: 1;
        min-height: 0;
      }
      #ctrl-playlist-panel #pl-vscroll {
        height: auto;
        flex: 1;
        min-height: 0;
        overflow-y: auto;
      }
      /* Spacer fills remaining height when playlist is collapsed; hidden when playlist is open */
      #ctrl-flex-spacer { flex: 1; }
      #ctrl-flex-spacer.hidden { flex: 0; display: none; }

      #metadata-box { position: relative; }
      #metadata-close-btn { display: none; }

      /* History: wider modal on wide screens */
      #history-box { max-width: 660px; border-radius: 12px; max-height: 70vh; }
      #history-overlay { align-items: center; }
      /* Shrink history box / shift overlay when side panels are open */
      body.ctrl-open #history-overlay { left: 360px; }
      body.meta-open #history-overlay { right: 360px; }
      body.ctrl-open #history-box  { max-width: min(660px, calc(100vw - 360px - 80px)); }
      body.meta-open #history-box  { max-width: min(660px, calc(100vw - 360px - 80px)); }
      body.ctrl-open.meta-open #history-box { max-width: min(660px, calc(100vw - 720px - 80px)); }
    }
  </style>
</head>
<body>
  <div id="timer-bar"><div id="timer-display" style="display:none">0</div><div id="timer-title"><span class="tt-desktop">Guess The Anime</span><span class="tt-mobile">GUESS<br>THE ANIME</span></div></div>
  <div id="top-bar">
    <button id="history-btn" onclick="_openHistory()" style="display:none">&#8635; SESSION HISTORY</button>
    <div id="player-label" title="Click to change name">
      <span id="player-label-text" onclick="changeName()"></span>
      <span id="player-label-swatch" class="pl-swatch-empty" onclick="_openColorPicker(playerName)" title="Set your highlight color"></span>
    </div>
  </div>
  <h1>Guess The Anime</h1>

  <div id="banned-screen" class="box" style="display:none">
    <p style="color:#f66;font-size:1.1em;margin-bottom:8px">&#128581; You have been banned from this session.</p>
    <p style="color:#888;font-size:0.85em">Contact the host if you think this is a mistake.</p>
  </div>

  <div id="kick-overlay">
    <div id="kick-box">
      <div id="kick-player-name"></div>
      <div class="kick-opt-btns">
        <button id="kick-btn-shadow">Kick</button>
        <button id="kick-btn-rename">Rename</button>
        <button id="kick-btn-name">Name Ban</button>
        <button id="kick-btn-ip">IP Ban</button>
        <button id="kick-btn-emoji">Disable Emojis</button>
        <button id="kick-btn-cancel" onclick="_kickCancel()">Cancel</button>
      </div>
    </div>
  </div>

  <div id="confirm-overlay">
    <div id="confirm-box">
      <div id="confirm-msg"></div>
      <div class="confirm-btns">
        <button id="confirm-yes">Remove</button>
        <button id="confirm-no" onclick="_confirmCancel()">Cancel</button>
      </div>
    </div>
  </div>

  <div id="emoji-picker-overlay">
    <div id="emoji-picker-box">
      <div id="emoji-picker-title">Tap to toggle &bull; highlighted = in bar</div>
      <div id="emoji-picker-grid"></div>
      <div id="emoji-picker-footer">
        <button id="emoji-picker-reset" onclick="_resetEmojiDefaults()">Reset defaults</button>
        <button id="emoji-picker-close" onclick="_closeEmojiPicker()">Close</button>
      </div>
    </div>
  </div>

  <div id="name-screen" class="box">
    <p style="margin-bottom:8px;color:#aaa">Enter your name to join</p>
    <p style="margin-bottom:16px;color:#666;font-size:0.85em">This will appear on the scoreboard exactly as typed.</p>
    <datalist id="player-names-list"></datalist>
    <datalist id="anime-titles-list"></datalist>
    <input id="name-input" placeholder="Your name (no spaces)&hellip;" maxlength="30" autofocus list="player-names-list"/>
    <button id="name-btn" onclick="saveName()">Join</button>
    <div id="host-pw-toggle" onclick="_toggleHostPwField()" style="margin-top:18px;color:#333;font-size:0.75em;cursor:pointer;user-select:none">&#128274; Host</div>
    <div id="host-pw-wrap" style="display:none;margin-top:6px">
      <input id="host-pw-input" type="password" placeholder="Host password&hellip;" maxlength="100"
        style="width:100%;padding:9px;background:#111;border:1px solid #333;border-radius:8px;color:#ccc;font-size:0.9em;box-sizing:border-box"/>
    </div>
  </div>

  <div id="scoreboard-view" class="box">
    <!-- toolbar -->
    <div id="sc-toolbar">
      <span id="sc-toolbar-title">Scoreboard</span>
      <button id="sc-tog-auto" class="sc-toggle-btn" onclick="_scToggleAuto()" title="AUTO — Scores send automatically after clicking a delta. Turn off to batch manually.">&#9889;</button>
      <button id="sc-tog-together" class="sc-toggle-btn" onclick="_scToggleTogether()" title="BATCH — Any delta press resets the shared timer for everyone.">&#10697;</button>
      <button id="sc-clear-btn" class="sc-toolbar-btn" onclick="_scClearAll()" title="CLEAR — Remove all players from the scoreboard.">&#128465;</button>
      <button id="sc-archive-btn" class="sc-toolbar-btn" onclick="_scArchive()" title="Archive current session (uses the host name configured in Scoreboard settings).">ARCHIVE</button>
      <span style="flex:1"></span>
      <button id="sc-submit-btn" class="sc-toolbar-btn" onclick="_scSubmitPending()">SUBMIT</button>
    </div>
    <!-- column headers (host only) -->
    <div id="sc-col-headers" style="display:none">
      <span class="sc-ch" id="sc-ch-adjust">ADJUST</span>
      <span class="sc-ch" id="sc-ch-score">SCORE</span>
      <span class="sc-ch" id="sc-ch-player">PLAYER</span>
      <span class="sc-ch" id="sc-ch-menu"></span>
    </div>
    <!-- player rows -->
    <div id="sc-scroll"><div id="sc-players"></div></div>
    <!-- add player (host only) -->
    <div id="sc-host-controls" style="display:none">
      <div id="sc-sep"></div>
      <div id="sc-add-row">
        <!-- hidden dummy fields to prevent password managers from pairing this input -->
        <form id="sc-add-form" autocomplete="off" onsubmit="event.preventDefault(); _scAddPlayer();" style="display:flex; gap:4px; width:100%;">
          <input type="text" name="fake_user" autocomplete="off" tabindex="-1"
                 style="position:absolute; left:-9999px; width:1px; height:1px; opacity:0;" />
          <input type="password" name="fake_pass" autocomplete="new-password" tabindex="-1"
                 style="position:absolute; left:-9999px; width:1px; height:1px; opacity:0;" />
             <input id="sc-add-input" name="player_name" type="search" placeholder="Player name" autocomplete="nickname"
               inputmode="text" autocorrect="off" autocapitalize="none" spellcheck="false" readonly
               enterkeyhint="search" list="player-names-list"
               aria-label="Player name" onfocus="this.removeAttribute('readonly');" onkeydown="if(event.key==='Enter')_scAddPlayer()">
          <button id="sc-add-btn" onclick="_scAddPlayer()">+ Add</button>
        </form>
      </div>
    </div>
  </div>

  <div id="host-answers-anchor-score" class="box"></div>
  <div id="host-messages-anchor-score" class="box"></div>

  <div id="question-box" class="box" style="display:none">
    <div id="waiting">
      <div id="waiting-msg">&#9203; Waiting for next question&hellip;</div>
      <div id="waiting-rules" style="display:none"><div id="waiting-rules-header"></div><div id="waiting-rules-body"></div></div>
      <div id="prev-question" style="display:none">
        <div id="prev-question-label">PREVIOUS QUESTION</div>
        <div id="prev-question-title"></div>
        <div id="prev-question-correct"></div>
        <div id="prev-question-mine"></div>
      </div>
    </div>
    <div id="question-area" style="display:none">
      <div id="host-answers-anchor-question">
        <button id="host-toggle" onclick="_toggleHostPanel()">&#128065; Submitted Answers (0)</button>
        <div id="host-panel">
          <div id="host-answers"></div>
        </div>
      </div>
      <div id="q-card">
        <div id="q-title"></div>
        <div id="q-info"></div>
      </div>
      <div id="choices-area"></div>
      <input id="free-input" placeholder="Your Answer&hellip;" autocomplete="off" style="display:none"/>      <div id="free-error" style="display:none; color:#f66; font-size:0.85em; margin-bottom:8px;"></div>      <button id="submit-btn" onclick="submitAnswer()">Submit</button>
      <div id="sent-msg">&#10003; Answer submitted!</div>
      <div id="peer-answers-wrap" style="display:none">
        <button id="peer-answers-toggle" onclick="_togglePeerAnswers()">&#128065; Submitted Answers (0)</button>
        <div id="peer-answers-list"></div>
      </div>
      <div id="buzzer-panel">
        <div id="buzzer-status">Buzzer idle.</div>
        <button id="buzz-btn" onclick="_pressBuzz()">BUZZ</button>
        <div id="buzzer-order"></div>
      </div>
    </div>
    <div id="host-messages-anchor-question">
      <div id="host-messages-wrap" style="display:none">
        <div id="host-messages-head">
          <span>Host Inbox (<span id="host-messages-count">0</span>)</span>
          <div id="hm-right-controls">
            <button id="hm-popup-btn" onclick="_toggleHostMessagePopups()" title="Toggle host message popups">&#128172;</button>
            <div id="hm-vol-wrap" title="Toggle mute / unmute chime">
              <button id="hm-bell-btn" onclick="_toggleChimeMute()">&#128276;</button>
              <input id="hm-vol-slider" type="range" min="0" max="1" step="0.05"
                oninput="_setChimeVolume(this.value)" />
            </div>
            <button id="host-messages-clear" onclick="_clearHostMessages()">Clear</button>
          </div>
        </div>
        <div id="host-messages-list"></div>
      </div>
    </div>
    <div id="emoji-bar">
      <div id="host-msg-row">
        <input id="host-msg-input" maxlength="280" placeholder="Message host…" autocomplete="off" />
        <button id="host-msg-send" onclick="_sendHostMessage()">Send to Host</button>
      </div>
      <p>React</p>
      <div id="emoji-btns">
        <button id="emoji-add-btn" title="Edit reactions" onclick="_openEmojiPicker()">&#9998; Edit</button>
      </div>
      <div id="emoji-status"></div>
    </div>
  </div>

  <div id="host-msg-toast"></div>
  <div id="gta-toast"></div>

  <div id="colorpick-overlay">
    <div id="colorpick-box">
      <div id="colorpick-title">Set color</div>
      <!-- Page 1: choose field -->
      <div id="colorpick-p1">
        <button class="colorpick-field-btn" onclick="_colorpickOpenField('bg')">
          <span class="colorpick-field-name">Background</span>
          <span class="cp-field-val" id="cp-p1-bg-val"></span>
          <span class="colorpick-field-swatch cp-no-color" id="cp-p1-bg-sw"></span>
        </button>
        <button class="colorpick-field-btn" onclick="_colorpickOpenField('text')">
          <span class="colorpick-field-name">Text</span>
          <span class="cp-field-val" id="cp-p1-text-val"></span>
          <span class="colorpick-field-swatch cp-no-color" id="cp-p1-text-sw"></span>
        </button>
        <div class="colorpick-btns">
          <button id="colorpick-save" onclick="_colorpickSave()">Save</button>
          <button id="colorpick-cancel" onclick="_colorpickClose()">Cancel</button>
        </div>
      </div>
      <!-- Page 2: pick color for one field -->
      <div id="colorpick-p2" style="display:none">
        <div class="cp-p2-header">
          <button class="cp-back-btn" onclick="_colorpickBack()">&#8592; Back</button>
          <span id="cp-p2-label">Background</span>
          <button class="cp-clear-btn" onclick="_colorpickClearField()">clear</button>
        </div>
        <div class="cp-palette">
          <!-- Reds -->
          <span class="cp-swatch" style="background:mistyrose;border-color:#555" onclick="_colorpickPickPreset('mistyrose')" title="mistyrose"></span>
          <span class="cp-swatch" style="background:lightcoral;border-color:#555" onclick="_colorpickPickPreset('lightcoral')" title="lightcoral"></span>
          <span class="cp-swatch" style="background:salmon" onclick="_colorpickPickPreset('salmon')" title="salmon"></span>
          <span class="cp-swatch" style="background:tomato" onclick="_colorpickPickPreset('tomato')" title="tomato"></span>
          <span class="cp-swatch" style="background:crimson" onclick="_colorpickPickPreset('crimson')" title="crimson"></span>
          <span class="cp-swatch" style="background:red" onclick="_colorpickPickPreset('red')" title="red"></span>
          <span class="cp-swatch" style="background:firebrick" onclick="_colorpickPickPreset('firebrick')" title="firebrick"></span>
          <span class="cp-swatch" style="background:maroon" onclick="_colorpickPickPreset('maroon')" title="maroon"></span>
          <span class="cp-swatch" style="background:darkred" onclick="_colorpickPickPreset('darkred')" title="darkred"></span>
          <span class="cp-swatch" style="background:brown" onclick="_colorpickPickPreset('brown')" title="brown"></span>
          <!-- Oranges -->
          <span class="cp-swatch" style="background:peachpuff;border-color:#555" onclick="_colorpickPickPreset('peachpuff')" title="peachpuff"></span>
          <span class="cp-swatch" style="background:lightsalmon;border-color:#555" onclick="_colorpickPickPreset('lightsalmon')" title="lightsalmon"></span>
          <span class="cp-swatch" style="background:coral" onclick="_colorpickPickPreset('coral')" title="coral"></span>
          <span class="cp-swatch" style="background:orange" onclick="_colorpickPickPreset('orange')" title="orange"></span>
          <span class="cp-swatch" style="background:darkorange" onclick="_colorpickPickPreset('darkorange')" title="darkorange"></span>
          <span class="cp-swatch" style="background:sienna" onclick="_colorpickPickPreset('sienna')" title="sienna"></span>
          <span class="cp-swatch" style="background:chocolate" onclick="_colorpickPickPreset('chocolate')" title="chocolate"></span>
          <span class="cp-swatch" style="background:saddlebrown" onclick="_colorpickPickPreset('saddlebrown')" title="saddlebrown"></span>
          <!-- Yellows -->
          <span class="cp-swatch" style="background:lightyellow;border-color:#555" onclick="_colorpickPickPreset('lightyellow')" title="lightyellow"></span>
          <span class="cp-swatch" style="background:yellow;border-color:#555" onclick="_colorpickPickPreset('yellow')" title="yellow"></span>
          <span class="cp-swatch" style="background:khaki;border-color:#555" onclick="_colorpickPickPreset('khaki')" title="khaki"></span>
          <span class="cp-swatch" style="background:gold;border-color:#555" onclick="_colorpickPickPreset('gold')" title="gold"></span>
          <span class="cp-swatch" style="background:goldenrod" onclick="_colorpickPickPreset('goldenrod')" title="goldenrod"></span>
          <span class="cp-swatch" style="background:darkgoldenrod" onclick="_colorpickPickPreset('darkgoldenrod')" title="darkgoldenrod"></span>
          <span class="cp-swatch" style="background:olive" onclick="_colorpickPickPreset('olive')" title="olive"></span>
          <span class="cp-swatch" style="background:darkolivegreen" onclick="_colorpickPickPreset('darkolivegreen')" title="darkolivegreen"></span>
          <!-- Greens -->
          <span class="cp-swatch" style="background:lightgreen;border-color:#555" onclick="_colorpickPickPreset('lightgreen')" title="lightgreen"></span>
          <span class="cp-swatch" style="background:lime;border-color:#555" onclick="_colorpickPickPreset('lime')" title="lime"></span>
          <span class="cp-swatch" style="background:limegreen" onclick="_colorpickPickPreset('limegreen')" title="limegreen"></span>
          <span class="cp-swatch" style="background:forestgreen" onclick="_colorpickPickPreset('forestgreen')" title="forestgreen"></span>
          <span class="cp-swatch" style="background:green" onclick="_colorpickPickPreset('green')" title="green"></span>
          <span class="cp-swatch" style="background:seagreen" onclick="_colorpickPickPreset('seagreen')" title="seagreen"></span>
          <span class="cp-swatch" style="background:darkgreen" onclick="_colorpickPickPreset('darkgreen')" title="darkgreen"></span>
          <span class="cp-swatch" style="background:darkslategray" onclick="_colorpickPickPreset('darkslategray')" title="darkslategray"></span>
          <!-- Teals -->
          <span class="cp-swatch" style="background:lightcyan;border-color:#555" onclick="_colorpickPickPreset('lightcyan')" title="lightcyan"></span>
          <span class="cp-swatch" style="background:aquamarine;border-color:#555" onclick="_colorpickPickPreset('aquamarine')" title="aquamarine"></span>
          <span class="cp-swatch" style="background:mediumaquamarine" onclick="_colorpickPickPreset('mediumaquamarine')" title="mediumaquamarine"></span>
          <span class="cp-swatch" style="background:turquoise" onclick="_colorpickPickPreset('turquoise')" title="turquoise"></span>
          <span class="cp-swatch" style="background:mediumturquoise" onclick="_colorpickPickPreset('mediumturquoise')" title="mediumturquoise"></span>
          <span class="cp-swatch" style="background:darkturquoise" onclick="_colorpickPickPreset('darkturquoise')" title="darkturquoise"></span>
          <span class="cp-swatch" style="background:lightseagreen" onclick="_colorpickPickPreset('lightseagreen')" title="lightseagreen"></span>
          <span class="cp-swatch" style="background:cadetblue" onclick="_colorpickPickPreset('cadetblue')" title="cadetblue"></span>
          <span class="cp-swatch" style="background:teal" onclick="_colorpickPickPreset('teal')" title="teal"></span>
          <span class="cp-swatch" style="background:darkcyan" onclick="_colorpickPickPreset('darkcyan')" title="darkcyan"></span>
          <!-- Blues -->
          <span class="cp-swatch" style="background:lightblue;border-color:#555" onclick="_colorpickPickPreset('lightblue')" title="lightblue"></span>
          <span class="cp-swatch" style="background:skyblue;border-color:#555" onclick="_colorpickPickPreset('skyblue')" title="skyblue"></span>
          <span class="cp-swatch" style="background:deepskyblue" onclick="_colorpickPickPreset('deepskyblue')" title="deepskyblue"></span>
          <span class="cp-swatch" style="background:cornflowerblue" onclick="_colorpickPickPreset('cornflowerblue')" title="cornflowerblue"></span>
          <span class="cp-swatch" style="background:steelblue" onclick="_colorpickPickPreset('steelblue')" title="steelblue"></span>
          <span class="cp-swatch" style="background:royalblue" onclick="_colorpickPickPreset('royalblue')" title="royalblue"></span>
          <span class="cp-swatch" style="background:blue" onclick="_colorpickPickPreset('blue')" title="blue"></span>
          <span class="cp-swatch" style="background:navy" onclick="_colorpickPickPreset('navy')" title="navy"></span>
          <span class="cp-swatch" style="background:darkblue" onclick="_colorpickPickPreset('darkblue')" title="darkblue"></span>
          <span class="cp-swatch" style="background:midnightblue" onclick="_colorpickPickPreset('midnightblue')" title="midnightblue"></span>
          <!-- Purples -->
          <span class="cp-swatch" style="background:plum;border-color:#555" onclick="_colorpickPickPreset('plum')" title="plum"></span>
          <span class="cp-swatch" style="background:violet;border-color:#555" onclick="_colorpickPickPreset('violet')" title="violet"></span>
          <span class="cp-swatch" style="background:orchid" onclick="_colorpickPickPreset('orchid')" title="orchid"></span>
          <span class="cp-swatch" style="background:mediumpurple" onclick="_colorpickPickPreset('mediumpurple')" title="mediumpurple"></span>
          <span class="cp-swatch" style="background:blueviolet" onclick="_colorpickPickPreset('blueviolet')" title="blueviolet"></span>
          <span class="cp-swatch" style="background:purple" onclick="_colorpickPickPreset('purple')" title="purple"></span>
          <span class="cp-swatch" style="background:indigo" onclick="_colorpickPickPreset('indigo')" title="indigo"></span>
          <span class="cp-swatch" style="background:darkslateblue" onclick="_colorpickPickPreset('darkslateblue')" title="darkslateblue"></span>
          <span class="cp-swatch" style="background:darkviolet" onclick="_colorpickPickPreset('darkviolet')" title="darkviolet"></span>
          <span class="cp-swatch" style="background:darkorchid" onclick="_colorpickPickPreset('darkorchid')" title="darkorchid"></span>
          <!-- Pinks -->
          <span class="cp-swatch" style="background:pink;border-color:#555" onclick="_colorpickPickPreset('pink')" title="pink"></span>
          <span class="cp-swatch" style="background:lightpink;border-color:#555" onclick="_colorpickPickPreset('lightpink')" title="lightpink"></span>
          <span class="cp-swatch" style="background:hotpink" onclick="_colorpickPickPreset('hotpink')" title="hotpink"></span>
          <span class="cp-swatch" style="background:palevioletred" onclick="_colorpickPickPreset('palevioletred')" title="palevioletred"></span>
          <span class="cp-swatch" style="background:deeppink" onclick="_colorpickPickPreset('deeppink')" title="deeppink"></span>
          <span class="cp-swatch" style="background:mediumvioletred" onclick="_colorpickPickPreset('mediumvioletred')" title="mediumvioletred"></span>
          <span class="cp-swatch" style="background:magenta" onclick="_colorpickPickPreset('magenta')" title="magenta"></span>
          <span class="cp-swatch" style="background:darkmagenta" onclick="_colorpickPickPreset('darkmagenta')" title="darkmagenta"></span>
          <!-- Neutrals -->
          <span class="cp-swatch" style="background:white;border-color:#555" onclick="_colorpickPickPreset('white')" title="white"></span>
          <span class="cp-swatch" style="background:gainsboro;border-color:#555" onclick="_colorpickPickPreset('gainsboro')" title="gainsboro"></span>
          <span class="cp-swatch" style="background:tan;border-color:#555" onclick="_colorpickPickPreset('tan')" title="tan"></span>
          <span class="cp-swatch" style="background:silver;border-color:#555" onclick="_colorpickPickPreset('silver')" title="silver"></span>
          <span class="cp-swatch" style="background:darkgray" onclick="_colorpickPickPreset('darkgray')" title="darkgray"></span>
          <span class="cp-swatch" style="background:gray" onclick="_colorpickPickPreset('gray')" title="gray"></span>
          <span class="cp-swatch" style="background:dimgray" onclick="_colorpickPickPreset('dimgray')" title="dimgray"></span>
          <span class="cp-swatch" style="background:black" onclick="_colorpickPickPreset('black')" title="black"></span>
        </div>
        <button class="cp-custom-toggle" id="cp-custom-toggle" onclick="_colorpickToggleCustom()">Custom &#9662;</button>
        <div id="cp-custom-body" style="display:none">
          <div class="cp-custom-row">
            <input type="color" id="colorpick-colorinput" value="#ff6600" oninput="_colorpickColorInputChange()"/>
            <input type="text" id="colorpick-hexinput" class="cp-hex-input" maxlength="7" placeholder="#rrggbb" oninput="_colorpickHexInputChange()"/>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div id="history-overlay">
    <div id="history-box">
      <div id="history-box-title">&#8635; Session History</div>
      <div id="history-text-area">No history yet.</div>
      <div id="history-footer">
        <a id="history-dl-btn" href="/history/download" download="session_history.txt">&#11015; Download</a>
        <button id="history-close-btn" onclick="_closeHistory()">Close</button>
      </div>
    </div>
  </div>

  <div id="artist-themes-overlay" onclick="if(event.target===this)_closeArtistThemesDialog()">
    <div id="artist-themes-box">
      <div id="artist-themes-title">Other themes</div>
      <div id="artist-themes-content">No data.</div>
      <button id="artist-themes-close" onclick="_closeArtistThemesDialog()">Close</button>
    </div>
  </div>

  <div id="meta-cover-overlay" onclick="if(event.target===this)_closeMetaCover()">
    <img id="meta-cover-full" alt="Cover art"/>
  </div>

  <div id="theme-action-overlay" onclick="if(event.target===this)_closeThemeActionPrompt()">
    <div id="theme-action-box">
      <div id="theme-action-title">Theme actions</div>
      <button class="theme-action-btn play" onclick="_themeActionRun('play')">&#9654; Play now</button>
      <button class="theme-action-btn queue" onclick="_themeActionRun('queue')">&#9203; Queue next</button>
      <button class="theme-action-btn add" onclick="_themeActionRun('add')">&#10133; Add next</button>
      <button id="theme-action-cancel" onclick="_closeThemeActionPrompt()">Cancel</button>
    </div>
  </div>

  <div id="pl-entry-overlay" onclick="if(event.target===this)_closePlEntryPopup()">
    <div id="pl-entry-box">
      <div id="pl-entry-title">Playlist entry</div>
      <button class="theme-action-btn play" onclick="_plEntryRun('play')">&#9654; Play now</button>
      <button class="theme-action-btn" style="border-color:#a33;color:#f99" onclick="_plEntryRun('delete')">&#x1F5D1; Delete</button>
      <button id="theme-action-cancel" onclick="_closePlEntryPopup()">Cancel</button>
    </div>
  </div>

  <div id="bottom-left-wrap">
    <div id="player-list-wrap" style="display:none">
      <button id="player-list-btn" onclick="_togglePlayerList()">&#128101; <span id="player-count">0</span></button>
      <div id="player-list-panel">
        <div id="player-list-items"></div>
      </div>
    </div>

    <div id="controls-wrap" style="display:none">
      <button id="controls-btn" onclick="_toggleController()" title="Playback Controls">&#x23EF;&#xFE0F;</button>
    </div>
  </div>
  <div id="sc-view-wrap">
    <button id="sc-view-btn" onclick="_toggleScoreboardView()" title="Scoreboard">&#x1F3C6; Scoreboard</button>
  </div>
  <div id="metadata-wrap">
    <div id="current-time" title="Local time">--:--</div>
    <button id="metadata-btn" onclick="_toggleMetadata()">&#x2139;&#xFE0F;</button>
  </div>

  <script>
    (function _initLocalTime() {
      function _fmt() {
        try {
          const el = document.getElementById('current-time');
          if (!el) return;
          const now = new Date();
          const t = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true });
          el.textContent = t.replace(' ', '\u00A0');
        } catch (e) {}
      }
      _fmt();
      setInterval(_fmt, 1000);
    })();
  </script>

  <!-- Playback controller modal (host only) -->
  <div id="ctrl-list-popup-overlay" onmousedown="_ctrlListPopupOverlayMouseDown(event)" onclick="_ctrlListPopupOverlayClick(event)">
    <div id="ctrl-list-popup-box">
      <div id="ctrl-list-popup-header">
        <span id="ctrl-list-popup-title"></span>
        <button id="ctrl-list-popup-close" onclick="_ctrlListPopupClose()">&#x2715;</button>
      </div>
      <div id="ctrl-list-popup-search-row">
        <input type="text" id="ctrl-list-popup-search-input" placeholder="Search themes..."
               onkeydown="if(event.key==='Enter')_ctrlListPopupDoSearch()"
               oninput="_ctrlListPopupSearchDebounce()">
        <button id="ctrl-list-popup-search-submit" onclick="_ctrlListPopupDoSearch()">&#x1F50D;</button>
      </div>
      <div id="ctrl-list-popup-list"></div>
    </div>
  </div>
  <!-- Extras popup (More… button) -->
  <div id="ctrl-extras-popup-overlay" onclick="if(event.target===this)_ctrlCloseExtrasPopup()">
    <div id="ctrl-extras-popup-box">
      <div id="ctrl-extras-popup-header">
        <span id="ctrl-extras-popup-title">More Options</span>
        <div style="display:flex;gap:6px;align-items:center">
          <button id="ctrl-extras-edit-btn" onclick="_ctrlToggleExtrasEditMode()" title="Pin buttons to main panel">&#x1F4CC; Pin</button>
          <button id="ctrl-extras-popup-close" onclick="_ctrlCloseExtrasPopup()">&#x2715;</button>
        </div>
      </div>
      <div id="ctrl-extras-edit-hint">Click a button to pin/unpin it from the main controls</div>
      <div id="ctrl-extras-edit-actions" style="display:none;gap:5px;justify-content:flex-end">
        <button class="ctrl-bonus-btn" style="font-size:0.72em;padding:3px 8px;color:#c77;border-color:#422" onclick="_ctrlClearPinned()" title="Remove all pinned buttons">Clear All</button>
        <button class="ctrl-bonus-btn" style="font-size:0.72em;padding:3px 8px;color:#778;border-color:#223" onclick="_ctrlResetPinned()" title="Reset to default layout">Reset to Defaults</button>
      </div>
      <div class="ctrl-extras-sect-row">
        <span class="ctrl-extras-sect-label">Queue</span>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-queue" data-extra-id="lt" onclick="_ctrlExtraClick('lt')">Lightning</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-queue" data-extra-id="lt_dice" onclick="_ctrlExtraClick('lt_dice')">&#x1F3B2;</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-queue" data-extra-id="yt" onclick="_ctrlExtraClick('yt')">YouTube</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-queue" data-extra-id="fl" onclick="_ctrlExtraClick('fl')">Fixed</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-queue" data-extra-id="search" onclick="_ctrlExtraClick('search')">&#x1F50D;</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-queue" data-extra-id="directory" onclick="_ctrlExtraClick('directory')">&#x1F4C2;</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-queue" data-extra-id="lt_stop" onclick="_ctrlExtraClick('lt_stop')">&#x23F9;</button>
      </div>
      <div class="ctrl-extras-sect-row">
        <span class="ctrl-extras-sect-label">Bonus</span>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="b_multiple" onclick="_ctrlExtraClick('b_multiple')">Multiple</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="b_year" onclick="_ctrlExtraClick('b_year')">Year</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="b_tags" onclick="_ctrlExtraClick('b_tags')">Tags</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="b_members" onclick="_ctrlExtraClick('b_members')">Members</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="b_score" onclick="_ctrlExtraClick('b_score')">Score</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="b_rank" onclick="_ctrlExtraClick('b_rank')">Rank</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="b_free" onclick="_ctrlExtraClick('b_free')">Free</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="bonus_studio" onclick="_ctrlExtraClick('bonus_studio')">Studio</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="bonus_artist" onclick="_ctrlExtraClick('bonus_artist')">Artist</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="bonus_song" onclick="_ctrlExtraClick('bonus_song')">Song</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="bonus_chars" onclick="_ctrlExtraClick('bonus_chars')">Characters</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="bonus_buzzer" onclick="_ctrlExtraClick('bonus_buzzer')">Buzzer</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-bonus" data-extra-id="buzz_lock" onclick="_ctrlExtraClick('buzz_lock')">Buzz Lock</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="buzz_reset" onclick="_ctrlExtraClick('buzz_reset')">Buzz Reset</button>
        <button class="ctrl-bonus-btn ctrl-sect-bonus" data-extra-id="buzz_sound" onclick="_ctrlExtraClick('buzz_sound')" title="Choose buzzer sound preset">Buzz Sound</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-bonus" data-extra-id="auto_bonus" onclick="_ctrlExtraClick('auto_bonus')">Auto Bonus</button>
      </div>
      <div class="ctrl-extras-sect-row">
        <span class="ctrl-extras-sect-label">Toggles &amp; Session</span>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" data-extra-id="tgl_blind" onclick="_ctrlExtraClick('tgl_blind')">Blind</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" data-extra-id="tgl_peek" onclick="_ctrlExtraClick('tgl_peek')">Peek</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" data-extra-id="tgl_narrow" onclick="_ctrlExtraClick('tgl_narrow')">&#x25C0;</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" data-extra-id="tgl_widen" onclick="_ctrlExtraClick('tgl_widen')">&#x25B6;</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" data-extra-id="tgl_mute" onclick="_ctrlExtraClick('tgl_mute')">Mute</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" id="ctrl-tgl-censors" data-extra-id="tgl_censors" onclick="_ctrlExtraClick('tgl_censors')" title="Toggle censors">Censors (<span class="ctrl-censor-count">0</span>)</button>
        <button class="ctrl-bonus-btn ctrl-sect-toggle" data-extra-id="tgl_fullscreen" onclick="_ctrlExtraClick('tgl_fullscreen')">Fullscreen</button>
        <button class="ctrl-bonus-btn ctrl-sect-toggle" data-extra-id="difficulty" onclick="_ctrlExtraClick('difficulty')">Difficulty</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" id="ctrl-tgl-shortcuts" data-extra-id="tgl_shortcuts" onclick="_ctrlExtraClick('tgl_shortcuts')" title="Toggle keyboard shortcuts">Keys</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" id="ctrl-tgl-dock" data-extra-id="tgl_dock" onclick="_ctrlExtraClick('tgl_dock')">Dock</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" id="ctrl-tgl-info-start" data-extra-id="tgl_info_start" onclick="_ctrlExtraClick('tgl_info_start')" title="Toggle auto-show info at start">Info Start</button>
        <button class="ctrl-bonus-btn ctrl-toggle-btn ctrl-sect-toggle" id="ctrl-tgl-info-end" data-extra-id="tgl_info_end" onclick="_ctrlExtraClick('tgl_info_end')" title="Toggle auto-show info at end">Info End</button>
        <button class="ctrl-bonus-btn ctrl-sect-session" id="ctrl-reset-session-btn" data-extra-id="reset_session_history" onclick="_ctrlExtraClick('reset_session_history')">Reset Session [0]</button>
        <button class="ctrl-bonus-btn ctrl-sect-session" data-extra-id="end_session" onclick="_ctrlExtraClick('end_session')">End</button>
      </div>
      <div class="ctrl-extras-sect-row">
        <span class="ctrl-extras-sect-label">Info Reveal &amp; Marks</span>
        <button class="ctrl-bonus-btn ctrl-sect-reveal" data-extra-id="rev_info" onclick="_ctrlExtraClick('rev_info')">Show Information</button>
        <button class="ctrl-bonus-btn ctrl-sect-reveal" data-extra-id="rev_title" onclick="_ctrlExtraClick('rev_title')">Title</button>
        <button class="ctrl-bonus-btn ctrl-sect-reveal" data-extra-id="reveal_artist" onclick="_ctrlExtraClick('reveal_artist')">Artist</button>
        <button class="ctrl-bonus-btn ctrl-sect-reveal" data-extra-id="reveal_studio" onclick="_ctrlExtraClick('reveal_studio')">Studio</button>
        <button class="ctrl-bonus-btn ctrl-sect-reveal" data-extra-id="reveal_season" onclick="_ctrlExtraClick('reveal_season')">Season</button>
        <button class="ctrl-bonus-btn ctrl-sect-reveal" data-extra-id="reveal_year" onclick="_ctrlExtraClick('reveal_year')">Year</button>
        <button class="ctrl-bonus-btn ctrl-mark-btn ctrl-sect-mark" id="ctrl-mark-tag" data-extra-id="mark_tag" onclick="_ctrlExtraClick('mark_tag')">&#x2717;</button>
        <button class="ctrl-bonus-btn ctrl-mark-btn ctrl-sect-mark" id="ctrl-mark-fav" data-extra-id="mark_fav" onclick="_ctrlExtraClick('mark_fav')">♥</button>
        <button class="ctrl-bonus-btn ctrl-mark-btn ctrl-sect-mark" id="ctrl-mark-blind" data-extra-id="mark_blind" onclick="_ctrlExtraClick('mark_blind')">&#x1F441;</button>
        <button class="ctrl-bonus-btn ctrl-mark-btn ctrl-sect-mark" id="ctrl-mark-peek" data-extra-id="mark_peek" onclick="_ctrlExtraClick('mark_peek')">&#x1F440;</button>
        <button class="ctrl-bonus-btn ctrl-mark-btn ctrl-sect-mark" id="ctrl-mark-mute-peek" data-extra-id="mark_mute_peek" onclick="_ctrlExtraClick('mark_mute_peek')">&#x1F507;</button>
      </div>
      <div class="ctrl-extras-sect-row">
        <span class="ctrl-extras-sect-label">Scoreboard</span>
        <button class="ctrl-bonus-btn ctrl-sect-scoreboard" data-extra-id="scoreboard_open_close" onclick="_ctrlExtraClick('scoreboard_open_close')">Open/Close</button>
        <button class="ctrl-bonus-btn ctrl-sect-scoreboard" data-extra-id="scoreboard_toggle" onclick="_ctrlExtraClick('scoreboard_toggle')">Toggle</button>
        <button class="ctrl-bonus-btn ctrl-sect-scoreboard" data-extra-id="scoreboard_align" onclick="_ctrlExtraClick('scoreboard_align')">Align</button>
        <button class="ctrl-bonus-btn ctrl-sect-scoreboard" data-extra-id="scoreboard_extend" onclick="_ctrlExtraClick('scoreboard_extend')">Extend</button>
        <button class="ctrl-bonus-btn ctrl-sect-scoreboard" data-extra-id="scoreboard_grow" onclick="_ctrlExtraClick('scoreboard_grow')">Grow</button>
        <button class="ctrl-bonus-btn ctrl-sect-scoreboard" data-extra-id="scoreboard_shrink" onclick="_ctrlExtraClick('scoreboard_shrink')">Shrink</button>
      </div>
      <div class="ctrl-extras-sect-row" id="ctrl-extras-layout-sect" style="display:none">
        <span class="ctrl-extras-sect-label">Layout</span>
        <div id="ctrl-extras-layout-chips" style="display:contents"></div>
        <button class="ctrl-bonus-btn" style="font-size:0.72em;padding:3px 8px;color:#667;border-color:#223" onclick="_ctrlAddLayoutItem('br')" title="Insert a line break in the pinned buttons">&#x21B5; Break</button>
        <button class="ctrl-bonus-btn" style="font-size:0.72em;padding:3px 8px;color:#667;border-color:#223" onclick="_ctrlAddLayoutItem('sp')" title="Insert a space in the pinned buttons">&#x25A1; Space</button>
      </div>
    </div>
  </div>
  <div id="controller-overlay" onclick="if(event.target===this && window.innerWidth<900)_toggleController()">
    <div id="controller-box">
      <button id="ctrl-close-btn" onclick="_toggleController()" title="Close controls">&#x2715;</button>
      <!-- Collapsible up next panel -->
      <div class="ctrl-section" id="ctrl-section-upnext">
        <div class="ctrl-collapse-toggle" id="ctrl-upnext-toggle" onclick="_ctrlToggleUpNext()">
          <span class="ctrl-collapse-label">&#x203A; Up Next</span>
          <span class="ctrl-collapse-chevron" id="ctrl-upnext-chevron">&#x25BE;</span>
        </div>
        <div id="ctrl-upnext-panel" style="display:none">
          <div id="ctrl-upnext-actions">
            <button class="ctrl-upnext-queue-btn" id="ctrl-queue-blind" onclick="socket.emit('host_action',{action:'invoke',id:'queue_blind_round'})" ontouchend="this.blur()" title="Queue Blind Round">&#x1F441; Blind</button>
            <button class="ctrl-upnext-queue-btn" id="ctrl-queue-peek" onclick="socket.emit('host_action',{action:'invoke',id:'queue_peek_round'})" ontouchend="this.blur()" title="Queue Peek Round">&#x1F440; Peek</button>
            <button class="ctrl-upnext-queue-btn" id="ctrl-queue-mute-peek" onclick="socket.emit('host_action',{action:'invoke',id:'queue_mute_peek_round'})" ontouchend="this.blur()" title="Queue Mute Peek Round">&#x1F507; Mute Peek</button>
            <button class="ctrl-upnext-queue-btn" id="ctrl-upnext-reroll" style="display:none" onclick="socket.emit('host_action',{action:'invoke',id:'reroll_next'})" ontouchend="this.blur()" title="Re-roll next track">&#x1F504; Re-roll</button>
          </div>
          <div id="ctrl-upnext-mode"></div>
          <div id="ctrl-upnext-title"><span class="ctrl-upnext-label">NEXT:</span> <span id="ctrl-upnext-title-text">No upcoming track</span></div>
          <div id="ctrl-upnext-detail"></div>
        </div>
      </div>
      <!-- Collapsible playlist panel -->
      <div class="ctrl-section" id="ctrl-section-playlist">
        <div class="ctrl-collapse-toggle" id="ctrl-playlist-toggle" onclick="_ctrlTogglePlaylist()" style="display:none">
          <span class="ctrl-collapse-label" id="ctrl-playlist-label">&#x203A; Playlist</span>
          <span id="ctrl-playlist-counter" style="font-size:0.75em;color:#556;margin-left:4px"></span>
          <span class="ctrl-collapse-chevron" id="ctrl-playlist-chevron">&#x25BE;</span>
        </div>
        <div id="ctrl-playlist-panel" style="display:none">
          <div id="pl-vscroll">
            <div id="pl-spacer"></div>
          </div>
        </div>
      </div>
      <!-- Flex spacer: pushes Controls + seek to bottom when playlist is collapsed -->
      <div id="ctrl-flex-spacer"></div>
      <!-- Combined controls panel -->
      <div class="ctrl-section" id="ctrl-section-controls">
        <div class="ctrl-collapse-toggle" id="ctrl-controls-toggle" onclick="_ctrlToggleControls()">
          <span class="ctrl-collapse-label">&#x203A; Controls</span>
          <span class="ctrl-collapse-chevron" id="ctrl-controls-chevron">&#x25BE;</span>
        </div>
        <div id="ctrl-controls-panel" style="display:none">
            <div id="ctrl-pinned-extras"></div>
            <button class="ctrl-bonus-btn ctrl-sect-toggle" onclick="_ctrlOpenExtrasPopup()" title="More options">More…</button>
        </div>
      </div>
      <!-- Collapsible info text panel -->
      <div class="ctrl-section" id="ctrl-section-infotext">
        <div class="ctrl-collapse-toggle" id="ctrl-infotext-toggle" onclick="_ctrlToggleInfoText()">
          <span class="ctrl-collapse-label">&#x203A; Info</span>
          <span class="ctrl-collapse-chevron" id="ctrl-infotext-chevron">&#x25BE;</span>
        </div>
        <div id="ctrl-infotext-panel" style="display:none">
            <div id="ctrl-info-top"></div>
            <div id="ctrl-info-main"></div>
            <div id="ctrl-info-bottom"></div>
        </div>
      </div>
      <!-- Seek bar -->
      <div id="ctrl-seek-row">
        <span id="ctrl-time-cur">0:00</span>
        <input id="ctrl-seek" type="range" min="0" max="1000" value="0"
               oninput="_ctrlSeekPreview(this.value)"
               onchange="_ctrlSeekCommit(this.value)">
        <span id="ctrl-time-total">0:00</span>
      </div>
      <!-- Playback buttons + volume -->
      <div id="ctrl-main-row">
        <div id="ctrl-vol-wrap">
          <button class="ctrl-btn ctrl-btn-sm" id="ctrl-vol-btn" onclick="_ctrlToggleVolume()" title="Volume">&#x1F50A;</button>
          <div id="ctrl-vol-slider-wrap" style="display:none">
            <div id="ctrl-bzz-row">
              <span id="ctrl-bzz-label-hd">BUZZ</span>
              <input id="ctrl-bzz-slider" type="range" min="0" max="150" value="100"
                     oninput="_ctrlBzzChange(this.value)">
              <span id="ctrl-bzz-label">100%</span>
            </div>
            <div id="ctrl-bgm-row">
              <span id="ctrl-bgm-label-hd">BGM</span>
              <input id="ctrl-bgm-slider" type="range" min="0" max="150" value="100"
                     oninput="_ctrlBgmChange(this.value)">
              <span id="ctrl-bgm-label">100%</span>
            </div>
            <div id="ctrl-vol-slider-row">
              <input id="ctrl-vol-slider" type="range" min="0" max="100" value="100"
                     oninput="_ctrlVolumeChange(this.value)">
              <span id="ctrl-vol-label">100</span>
            </div>
          </div>
        </div>
        <div id="ctrl-buttons">
          <button class="ctrl-btn" onclick="_ctrlAction('previous')" title="Previous">&#x23EE;&#xFE0F;</button>
          <button class="ctrl-btn" id="ctrl-playpause" onclick="_ctrlAction('play_pause')" title="Play / Pause">&#x23EF;&#xFE0F;</button>
          <button class="ctrl-btn" onclick="_ctrlAction('stop')" title="Stop">&#x23F9;&#xFE0F;</button>
          <button class="ctrl-btn" onclick="_ctrlAction('next')" title="Next">&#x23ED;&#xFE0F;</button>
        </div>
        <div id="ctrl-autoplay-wrap">
          <button class="ctrl-btn ctrl-btn-autoplay mode-0" id="ctrl-autoplay-btn"
                  onclick="_ctrlCycleAutoplay()" title="Autoplay mode">&#x1F501;</button>
        </div>
      </div>
    </div>
  </div>
  <div id="metadata-overlay">
    <div id="metadata-box">
      <button id="meta-close-btn" onclick="_closeMetadata()" title="Close info">&#x2715;</button>
      <div id="meta-history-nav">
        <div id="meta-nav-arrows">
          <button class="meta-history-btn meta-skip-btn" id="meta-history-oldest" onclick="_metaHistorySkip('oldest')" title="Skip to oldest">&#x7C;&#x25C4;</button>
          <button class="meta-history-btn" id="meta-history-prev" onclick="_metaHistoryNav(1)" title="Previous">&#x25C4;</button>
          <span id="meta-history-label">1 / 1</span>
          <button class="meta-history-btn" id="meta-history-next" onclick="_metaHistoryNav(-1)" title="Next">&#x25BA;</button>
          <button class="meta-history-btn meta-skip-btn" id="meta-history-newest" onclick="_metaHistorySkip('newest')" title="Skip to current">&#x25BA;&#x7C;</button>
          <button id="meta-nav-autofollow" onclick="_metaToggleAutoFollow()" title="Auto-follow current">&#x27F3; Live</button>
        </div>
        <span id="meta-nav-title"></span>
      </div>
      <div class="meta-tabs">
        <button class="meta-tab-btn active" onclick="_switchMetadataTab('info')">&#x2139;&#xFE0F; Info</button>
        <button class="meta-tab-btn" onclick="_switchMetadataTab('themes')">&#127925; Themes</button>
        <button class="meta-tab-btn" onclick="_switchMetadataTab('more')">&#x1F4DD; More</button>
      </div>
      <div id="meta-pane-info" class="meta-tab-pane active">
        <div id="meta-info-head">
          <div id="meta-cover-wrap">
            <button id="meta-cover-btn" onclick="_openMetaCover()" title="Open cover">
              <img id="meta-cover-img" alt="Cover art"/>
            </button>
          </div>
          <div id="meta-theme-head"></div>
        </div>
        <div id="metadata-content"><span style="color:#555">No metadata loaded.</span></div>
      </div>
      <div id="meta-pane-themes" class="meta-tab-pane">
        <div id="metadata-themes-content"><span style="color:#555">No themes loaded.</span></div>
      </div>
      <div id="meta-pane-more" class="meta-tab-pane">
        <div id="metadata-more-content"><span style="color:#555">No data loaded.</span></div>
      </div>
      <div id="meta-pane-playlist" class="meta-tab-pane"></div>
      <button id="metadata-close-btn" onclick="_closeMetadata()">Close</button>
    </div>
  </div>

  <div id="anime-ac-wrap" class="ac-wrap" style="display:none">
    <input id="anime-ac-input" class="ac-input" placeholder="Your answer…" autocomplete="off"/>
    <div id="anime-ac-drop" class="ac-drop"></div>
  </div>

  <script>
    (function() {
      function _scaleUI() {
        var scale = Math.min(window.innerWidth / 500, window.innerHeight / 780);
        document.documentElement.style.zoom = Math.max(scale, 1.0);
      }
      _scaleUI();
      window.addEventListener('resize', () => { _scaleUI(); _scFitScroll(); _plRefreshTrunc(); });
    })();

    /* Prevent password managers from pairing autofill with the add-player input by
       randomizing its `name` and forcing autocomplete off at page load. */
    (function preventPlayerAutofill() {
      try {
        const inp = document.getElementById('sc-add-input');
        if (!inp) return;
        // generate a short random name each load
        inp.name = 'pn_' + Math.random().toString(36).slice(2,10);
        inp.setAttribute('autocomplete', 'off');
        const form = document.getElementById('sc-add-form');
        if (form) form.setAttribute('autocomplete', 'off');
      } catch (e) { /* ignore */ }
    })();
  </script>
  <script>
    const socket = io();
    let selectedChoice = null;   // multiple-choice selection
    let playerName = localStorage.getItem('gta_name') || '';
    socket.on('connect', () => {
      if (playerName) socket.emit('set_name', { name: playerName });
      const storedPw = localStorage.getItem('gta_host_pw');
      if (storedPw) { _lastClaimPw = storedPw; socket.emit('claim_host', { password: storedPw }); }
      const buzzCookie = document.cookie.split(';').map(c=>c.trim()).find(c=>c.startsWith('buzz_preset_index='));
      if (buzzCookie) { const idx = parseInt(buzzCookie.split('=')[1]); if (!isNaN(idx)) socket.emit('host_action', {action:'set_buzz_preset', index:idx, silent:true}); }
    });
    let _currentQid  = null;      // qid of the active question
    let _currentQuestionTitle = '';  // title of the active question
    let _myLastAnswer = null;        // player's answer for the current question
    let _prevQTitle = '';            // previous question's title
    let _prevQCorrect = null;        // previous question's correct answer (display string)
    let _prevQType = '';             // question type of previous question
    let _prevQCorrectTags = [];      // correct tag list for 'tags' type questions
    let _answersRevealed = false;    // whether answers have been revealed for the previous question
    let _toggleBtnRef = null;     // reference to active toggle button (year/score)
    let _isHost = false;
    let _lastClaimPw = null;
    let _playerListOpen = false;
    let _peerAnswersOpen = false;
    let _playerColors = {};    // name → {bg, text}
    let _lastPlayerList = [];  // most recent players_update list
    let _colorpickTarget = null;
    let _colorpickBgValue = '';
    let _colorpickTextValue = '';
    let _colorpickActiveField = null;
    let _isBuzzerQuestion = false;
    let _buzzerState = { open: false, locked: false, order: [] };
    let _hostMessages = [];
    let _hostMsgToastTimer = null;
    let _audioCtx = null;
    let _hostMsgPopupsEnabled = true;
    let _chimeVolume = 0.28;
    let _lastChimeVolume = 0.28;
    function _getCookie(name) {
      const m = document.cookie.match('(?:^|; )' + name + '=([^;]*)');
      return m ? decodeURIComponent(m[1]) : null;
    }
    function _setCookie(name, value) {
      const exp = new Date(Date.now() + 365*24*60*60*1000).toUTCString();
      document.cookie = name + '=' + encodeURIComponent(value) + '; expires=' + exp + '; path=/';
    }
    function _updateHostPopupState() {
      const btn = document.getElementById('hm-popup-btn');
      if (!btn) return;
      btn.classList.toggle('off', !_hostMsgPopupsEnabled);
      btn.title = _hostMsgPopupsEnabled ? 'Host message popups: ON' : 'Host message popups: OFF';
    }
    function _setHostMsgPopupsEnabled(enabled, save = true) {
      _hostMsgPopupsEnabled = !!enabled;
      if (save) _setCookie('hm_popups_enabled', _hostMsgPopupsEnabled ? '1' : '0');
      _updateHostPopupState();
    }
    function _toggleHostMessagePopups() {
      _setHostMsgPopupsEnabled(!_hostMsgPopupsEnabled);
    }
    function _initHostMsgPopups() {
      const saved = _getCookie('hm_popups_enabled');
      if (saved !== null) {
        _hostMsgPopupsEnabled = !(saved === '0' || String(saved).toLowerCase() === 'false');
      }
      _updateHostPopupState();
    }
    function _updateBellState() {
      const btn = document.getElementById('hm-bell-btn');
      if (btn) btn.classList.toggle('muted', _chimeVolume === 0);
    }
    function _setChimeVolume(val, save = true) {
      _chimeVolume = parseFloat(val) || 0;
      if (_chimeVolume > 0) _lastChimeVolume = _chimeVolume;
      if (save) _setCookie('hm_chime_vol', String(_chimeVolume));
      const slider = document.getElementById('hm-vol-slider');
      if (slider) slider.value = _chimeVolume;
      _updateBellState();
    }
    function _toggleChimeMute() {
      _setChimeVolume(_chimeVolume === 0 ? _lastChimeVolume : 0);
    }
    function _initChimeVolume() {
      const saved = _getCookie('hm_chime_vol');
      if (saved !== null) _chimeVolume = parseFloat(saved) || 0;
      if (_chimeVolume > 0) _lastChimeVolume = _chimeVolume;
      const slider = document.getElementById('hm-vol-slider');
      if (slider) slider.value = _chimeVolume;
      _updateBellState();
    }
    function _getAudioCtx() {
      if (!_audioCtx) {
        try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch(e) {}
      }
      return _audioCtx;
    }
    // Unlock AudioContext on first user gesture so chimes can play later
    document.addEventListener('click',     () => { try { _getAudioCtx()?.resume(); } catch(e){} }, { once: false, passive: true });
    document.addEventListener('touchstart', () => { try { _getAudioCtx()?.resume(); } catch(e){} }, { once: false, passive: true });
    document.addEventListener('keydown',    () => { try { _getAudioCtx()?.resume(); } catch(e){} }, { once: false, passive: true });
    document.addEventListener('DOMContentLoaded', () => {
      _initHostMsgPopups();
      _initChimeVolume();
    });
    /* ── Timer state ── */
    let _timerSeconds  = 0;
    let _timerPaused   = false;
    let _timerRunning  = false;
    let _timerRafId    = null;
    let _timerLastTs   = null;
    if (playerName) showQuestionBox();

    /* ── Populate player name datalist for autocomplete ── */
    (function loadPlayerNames() {
      fetch('/player_names').then(r => r.json()).then(names => {
        const dl = document.getElementById('player-names-list');
        if (!dl) return;
        dl.innerHTML = '';
        names.forEach(n => {
          const opt = document.createElement('option');
          opt.value = n;
          dl.appendChild(opt);
        });
      }).catch(() => {});
    })();

    /* ── Name management ── */
    function _toggleHostPwField() {
      const wrap = document.getElementById('host-pw-wrap');
      const shown = wrap.style.display !== 'none';
      wrap.style.display = shown ? 'none' : 'block';
      if (!shown) document.getElementById('host-pw-input').focus();
    }
    function saveName() {
      const v = document.getElementById('name-input').value.trim().replace(/\s+/g, '_');
      if (!v) return;
      playerName = v;
      localStorage.setItem('gta_name', playerName);
      socket.emit('set_name', { name: playerName });
      const pw = document.getElementById('host-pw-input').value.trim();
      if (pw) {
        localStorage.setItem('gta_host_pw', pw);
        _lastClaimPw = pw;
        socket.emit('claim_host', { password: pw });
      } else if (localStorage.getItem('gta_host_pw')) {
        const sp = localStorage.getItem('gta_host_pw');
        _lastClaimPw = sp;
        socket.emit('claim_host', { password: sp });
      }
      showQuestionBox();
    }
    function changeName() {
      document.getElementById('question-box').style.display = 'none';
      document.getElementById('name-screen').style.display = 'block';
      document.getElementById('name-input').value = playerName;
    }
    document.getElementById('name-input').addEventListener('keydown', e => {
      if (e.key === ' ') e.preventDefault();
      if (e.key === 'Enter') saveName();
    });
    document.getElementById('host-pw-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') saveName();
    });
    socket.on('host_denied', () => {
      console.warn('[GTA] host_denied');
      try {
        // If the denied attempt matches our last claim attempt, clear stored pw
        const stored = localStorage.getItem('gta_host_pw');
        if (_lastClaimPw && stored && _lastClaimPw === stored) {
          localStorage.removeItem('gta_host_pw');
        }
      } catch (e) {}
      // Show visible toast to inform user
      _showToast('Host access denied');
      // Ensure host-only UI is closed and state reset
      _isHost = false;
      try {
        // Hide host-specific controls/panels but keep metadata/info visible
        const ht = document.getElementById('host-toggle'); if (ht) ht.style.display = 'none';
        const hp = document.getElementById('host-panel'); if (hp) hp.style.display = 'none';
        try { localStorage.setItem('hostPanelOpen', '0'); } catch (e) {}
        const cw = document.getElementById('controls-wrap'); if (cw) cw.style.display = 'none';
        // Keep metadata-wrap (info button) visible for all users
        const _scHC = document.getElementById('sc-host-controls'); if (_scHC) _scHC.style.display = 'none';
        const _scCH = document.getElementById('sc-col-headers'); if (_scCH) _scCH.style.display = 'none';
        // Ensure scoreboard view is closed and panels moved back to question area
        if (typeof _scViewOpen !== 'undefined') {
          _scViewOpen = false;
          try { _scApplyViewState(); } catch (e) {}
        }
        // Ensure the controller overlay is closed and body classes reset
        try {
          if (typeof _controllerOpen !== 'undefined') _controllerOpen = false;
          const overlay = document.getElementById('controller-overlay'); if (overlay) overlay.classList.remove('active');
          document.body.classList.remove('ctrl-open');
          // Hide the scoreboard toggle button for non-host users
          const scBtn = document.getElementById('sc-view-btn'); if (scBtn) scBtn.style.display = 'none';
        } catch(e) {}
        document.getElementById('peer-answers-wrap').style.display = 'block';
      } catch (e) {}
    });
    socket.on('name_forced', data => {
      const newName = String((data && data.name) || '').trim();
      if (!newName) return;
      playerName = newName;
      localStorage.setItem('gta_name', playerName);
      document.getElementById('player-label-text').textContent = '\u{1F464} ' + playerName;
      const ni = document.getElementById('name-input');
      if (ni) ni.value = playerName;
      _updateLabelSwatch();
      // Re-assert name on the socket for consistency after reconnect races.
      socket.emit('set_name', { name: playerName });
    });
    function showQuestionBox() {
      document.getElementById('name-screen').style.display = 'none';
      document.getElementById('question-box').style.display = 'block';
      document.getElementById('player-label-text').textContent = '\u{1F464} ' + playerName;
      _updateLabelSwatch();
      document.getElementById('player-list-wrap').style.display = 'block';
      document.getElementById('history-btn').style.display = 'block';
      document.getElementById('emoji-bar').style.display = 'block';
    }

    /* ══════════════════════════════════════════
       YEAR PICKER  —  single drum, one entry per year
       data.year = { min, max, initial }
    ══════════════════════════════════════════ */
    function buildYearPicker(area, cfg) {
      const curYear = new Date().getFullYear();
      const min     = cfg.min  || 1900;
      const max     = Math.min(cfg.max || curYear, curYear);
      const initVal = (cfg.initial != null && cfg.initial !== 0) ? cfg.initial : curYear;
      let myYear    = cfg.myYear || null;
      const ITEM_H  = 60;
      const WRAP_H  = 180;

      const years = [];
      for (let y = min; y <= max; y++) years.push(y);
      years.reverse(); // top = highest year, bottom = lowest

      const wrap = document.createElement('div');
      wrap.className = 'drum-wrap';
      wrap.style.cssText = 'height:' + WRAP_H + 'px; flex:1;';

      const hl = document.createElement('div');
      hl.className = 'drum-highlight';
      wrap.appendChild(hl);

      const scroller = document.createElement('div');
      scroller.className = 'drum-scroll';
      scroller.style.height = WRAP_H + 'px';

      scroller.appendChild(Object.assign(document.createElement('div'), { className: 'drum-item' }));
      years.forEach(y => {
        const el = document.createElement('div');
        el.className = 'drum-item';
        el.textContent = String(y);
        scroller.appendChild(el);
      });
      scroller.appendChild(Object.assign(document.createElement('div'), { className: 'drum-item' }));

      wrap.appendChild(scroller);

      const _nav = document.createElement('div');
      _nav.className = 'drum-nav';
      [
        { sym: '\u25b2 5', step: -5, title: '+5 years' },
        { sym: '\u25b2 1', step: -1, title: '+1 year' },
        { sym: '\u25bc 1', step:  1, title: '-1 year' },
        { sym: '\u25bc 5', step:  5, title: '-5 years' },
      ].forEach(({ sym, step, title }) => {
        const btn = document.createElement('button');
        btn.className = 'drum-nav-btn';
        btn.textContent = sym;
        btn.title = title;
        const fast = Math.abs(step) >= 5;
        btn.addEventListener('click', () => {
          userInteracted = true;
          scroller.scrollBy({ top: step * ITEM_H, behavior: fast ? 'instant' : 'smooth' });
        });
        _nav.appendChild(btn);
      });
      const _outer = document.createElement('div');
      _outer.style.cssText = 'display:flex; align-items:stretch; gap:8px; margin-bottom:10px;';
      _outer.appendChild(wrap);
      _outer.appendChild(_nav);
      area.appendChild(_outer);

      const yShortcuts = document.createElement('div');
      yShortcuts.className = 'drum-shortcuts';
      const yCandidates = [1960, 1970, 1980, 1990, 2000, 2005, 2010, 2015, 2020, 2025]
        .filter(y => y >= min && y <= max);
      const yUnique = [...new Set(yCandidates)].sort((a, b) => a - b);
      yUnique.forEach(y => {
        const b = document.createElement('button');
        b.className = 'drum-shortcut-btn';
        b.textContent = String(y);
        b.onclick = () => {
          userInteracted = true;
          setYear(y, true);
        };
        yShortcuts.appendChild(b);
      });
      if (yUnique.length) area.appendChild(yShortcuts);

      const initIdx = Math.max(0, years.indexOf(Math.max(min, Math.min(max, initVal))));
      const takenSet = new Set();
      let userInteracted = false;

      function getIdx() {
        return Math.max(0, Math.min(Math.round(scroller.scrollTop / ITEM_H), years.length - 1));
      }
      function getValue() { return years[getIdx()]; }
      function setYear(y, emit = false) {
        const clamped = Math.max(min, Math.min(max, parseInt(y, 10)));
        const idx = years.indexOf(clamped);
        if (idx < 0) return;
        scroller.scrollTop = idx * ITEM_H;
        highlight();
        if (emit) _emitSelect(clamped, true);
      }
      function highlight() {
        const idx = getIdx();
        scroller.querySelectorAll('.drum-item').forEach((el, i) => {
          const vi = i - 1;
          const itemYear = el.textContent ? parseInt(el.textContent, 10) : null;
          const isMyYear = myYear != null && itemYear === myYear;
          const isTaken  = el.textContent && takenSet.has(parseInt(el.textContent, 10)) && !isMyYear;
          el.style.color          = isMyYear ? '#88f' : (isTaken ? '#c44' : (vi === idx ? '#fff' : ''));
          el.style.fontSize       = (vi === idx || isMyYear) ? '1.7em' : '';
          el.style.fontWeight     = isMyYear ? 'bold' : '';
          el.style.textDecoration = isTaken ? 'line-through' : '';
        });
      }
      function markTaken(y) { takenSet.add(y); highlight(); }
      function setMyYear(y) { myYear = y; highlight(); }
      function applyScroll() {
        scroller.scrollTop = initIdx * ITEM_H;
        highlight();
      }

      if (typeof ResizeObserver !== 'undefined') {
        const ro = new ResizeObserver(() => {
          if (scroller.clientHeight > 0) { ro.disconnect(); applyScroll(); }
        });
        ro.observe(scroller);
      } else {
        setTimeout(applyScroll, 150);
      }

      scroller.addEventListener('wheel', () => { userInteracted = true; }, { passive: true });
      scroller.addEventListener('touchstart', () => { userInteracted = true; }, { passive: true });
      scroller.addEventListener('pointerdown', () => { userInteracted = true; }, { passive: true });
      scroller.addEventListener('scroll', () => { highlight(); _emitSelect(getValue(), userInteracted); }, { passive: true });
      return { getValue, markTaken, setMyYear };
    }

    /* ══════════════════════════════════════════
       DRUM PICKER  (score)
       data.drum = { min, max, step, initial, decimals }
    ══════════════════════════════════════════ */
    function buildDrum(area, cfg) {
      const { min, max, step, initial, decimals, reverse } = cfg;
      let myScore = cfg.myScore != null ? cfg.myScore : null;
      const vals = [];
      for (let v = min; v <= max + 1e-9; v = Math.round((v + step) * 1e6) / 1e6)
        vals.push(parseFloat(v.toFixed(decimals)));
      vals.reverse(); // top = highest score, bottom = lowest
      const scoreTakenSet = new Set();
      let userInteracted = false;

      const wrap = document.createElement('div');
      wrap.className = 'drum-wrap';

      const hl = document.createElement('div');
      hl.className = 'drum-highlight';
      wrap.appendChild(hl);

      const scroller = document.createElement('div');
      scroller.className = 'drum-scroll';

      // padding items so first/last value can centre
      for (let p = 0; p < 1; p++) {
        const pad = document.createElement('div');
        pad.className = 'drum-item';
        scroller.appendChild(pad);
      }
      vals.forEach(v => {
        const el = document.createElement('div');
        el.className = 'drum-item';
        el.textContent = decimals > 0 ? v.toFixed(decimals) : String(v);
        scroller.appendChild(el);
      });
      for (let p = 0; p < 1; p++) {
        const pad = document.createElement('div');
        pad.className = 'drum-item';
        scroller.appendChild(pad);
      }
      wrap.appendChild(scroller);

      const _sNav = document.createElement('div');
      _sNav.className = 'drum-nav';
      const _s1   = 1;                             // items per 0.1-unit jump (step=0.1)
      const _sMid = Math.round(0.5 / step) || 1;  // items per 0.5-unit jump
      [
        { sym: '\u25b2 .5', steps: -_sMid, title: '+.5' },
        { sym: '\u25b2 .1', steps: -_s1,   title: '+.1' },
        { sym: '\u25bc .1', steps:  _s1,   title: '-.1' },
        { sym: '\u25bc .5', steps:  _sMid, title: '-.5' },
      ].forEach(({ sym, steps, title }) => {
        const btn = document.createElement('button');
        btn.className = 'drum-nav-btn';
        btn.textContent = sym;
        btn.title = title;
        const fast = Math.abs(steps) >= _sMid;
        btn.addEventListener('click', () => {
          userInteracted = true;
          scroller.scrollBy({ top: steps * ITEM_H, behavior: fast ? 'instant' : 'smooth' });
        });
        _sNav.appendChild(btn);
      });
      const _sOuter = document.createElement('div');
      _sOuter.style.cssText = 'display:flex; align-items:stretch; gap:8px;';
      _sOuter.appendChild(wrap);
      _sOuter.appendChild(_sNav);

      area.appendChild(_sOuter);

      const sShortcuts = document.createElement('div');
      sShortcuts.className = 'drum-shortcuts';
      const quant = (v) => parseFloat((Math.round(v / step) * step).toFixed(decimals));
      const common = decimals > 0
        ? [2.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9]
        : [50, 60, 70, 80, 90];
      const sCandidates = common.map(quant).filter(v => v >= min && v <= max);
      const sUnique = [...new Set(sCandidates)].sort((a, b) => a - b);
      sUnique.forEach(v => {
        const b = document.createElement('button');
        b.className = 'drum-shortcut-btn';
        b.textContent = decimals > 0 ? v.toFixed(decimals) : String(v);
        b.onclick = () => {
          userInteracted = true;
          setScore(v, true);
        };
        sShortcuts.appendChild(b);
      });
      if (sUnique.length) area.appendChild(sShortcuts);

      const ITEM_H = 60;

      function getCentered() {
        const idx = Math.round(scroller.scrollTop / ITEM_H);
        return Math.max(0, Math.min(idx, vals.length - 1));
      }
      function setScore(target, emit = false) {
        if (!vals.length) return;
        let bestIdx = 0;
        let bestDiff = Math.abs(vals[0] - target);
        for (let i = 1; i < vals.length; i++) {
          const d = Math.abs(vals[i] - target);
          if (d < bestDiff) { bestDiff = d; bestIdx = i; }
        }
        scroller.scrollTop = bestIdx * ITEM_H;
        updateDisplay();
        if (emit) _emitSelect(vals[bestIdx], true);
      }

      function updateDisplay() {
        const idx = getCentered();
        const items = scroller.querySelectorAll('.drum-item');
        items.forEach((el, i) => {
          const vi = i - 1; // offset for top padding
          const itemVal = el.textContent ? parseFloat(el.textContent) : null;
          const isMyScore = myScore != null && itemVal != null && Math.abs(itemVal - myScore) < step / 2;
          const isTaken   = itemVal != null && scoreTakenSet.has(itemVal) && !isMyScore;
          el.style.color          = isMyScore ? '#88f' : (isTaken ? '#c44' : (vi === idx ? '#fff' : ''));
          el.style.fontSize       = (vi === idx || isMyScore) ? '1.7em' : '';
          el.style.fontWeight     = isMyScore ? 'bold' : '';
          el.style.textDecoration = isTaken ? 'line-through' : '';
        });
      }
      function markScoreTaken(s) { scoreTakenSet.add(s); updateDisplay(); }
      function setMyScore(s)     { myScore = s; updateDisplay(); }

      // Scroll to initial value — deferred so the browser has laid out the scroller
      const initIdx = vals.findIndex(v => Math.abs(v - initial) < step / 2);
      setTimeout(() => { scroller.scrollTop = Math.max(0, initIdx) * ITEM_H; updateDisplay(); }, 0);
      scroller.addEventListener('wheel', () => { userInteracted = true; }, { passive: true });
      scroller.addEventListener('touchstart', () => { userInteracted = true; }, { passive: true });
      scroller.addEventListener('pointerdown', () => { userInteracted = true; }, { passive: true });
      scroller.addEventListener('scroll', () => { updateDisplay(); _emitSelect(vals[getCentered()], userInteracted); }, { passive: true });

      return { getValue: () => vals[getCentered()], markScoreTaken, setMyScore };
    }

    /* ══════════════════════════════════════════
       STEPPER  (members / popularity)
       data.stepper = { initial, steps: [{label, delta}, …], min, max }
    ══════════════════════════════════════════ */
    function buildStepper(area, cfg) {
      let value = cfg.initial;
      const min = cfg.min ?? 0;
      const max = cfg.max ?? Infinity;

      const display = document.createElement('input');
      display.type = 'text';
      display.inputMode = 'numeric';
      display.className = 'stepper-display';

      function fmt(n) { return n.toLocaleString(); }
      function refresh() { display.value = fmt(value); }
      const inputWrap = document.createElement('div');
      inputWrap.className = 'stepper-input-wrap';
      inputWrap.appendChild(display);
      const typeHint = document.createElement('span');
      typeHint.className = 'stepper-type-hint';
      typeHint.textContent = 'T';
      inputWrap.appendChild(typeHint);
      area.appendChild(inputWrap);
      refresh();

      display.addEventListener('focus', () => {
        display.value = String(value);
      });
      display.addEventListener('keydown', e => {
        // Allow: digits, minus, backspace, delete, arrow keys, tab, enter
        if (!/^[0-9]$/.test(e.key) && !['Backspace','Delete','ArrowLeft','ArrowRight','Tab','Enter','-'].includes(e.key)) {
          e.preventDefault();
        }
        if (e.key === 'Enter') display.blur();
      });
      display.addEventListener('blur', () => {
        const parsed = parseInt(display.value.replace(/[^0-9-]/g, ''), 10);
        if (!isNaN(parsed)) value = Math.max(min, Math.min(max, parsed));
        refresh();
        _emitSelect(value, true);
      });
      for (let i = 0; i < cfg.steps.length; i += 3) {
        const chunk = cfg.steps.slice(i, i + 3);
        const row = document.createElement('div');
        row.className = 'stepper-row cols-' + (chunk.length === 2 ? '2' : '3');
        chunk.forEach(s => {
          const btn = document.createElement('button');
          btn.className = 'step-btn ' + (s.delta < 0 ? 'neg' : 'pos');
          btn.textContent = s.label;
          btn.onclick = () => {
            value = Math.max(min, Math.min(max, value + s.delta));
            refresh();
            _emitSelect(value, true);
          };
          row.appendChild(btn);
        });
        area.appendChild(row);
      }

      return { getValue: () => value };
    }

    /* ══════════════════════════════════════════
       RANK SLIDER  (popularity)
       data.rank_slider = { initial, min, max }
       Left half  [0,500]  : log   max → pivot(1000)
       Right half [500,1000]: quad  pivot(1000) → 1
         Quadratic spreads the top-1000 range much more evenly than log.
         Left = worst (high #)   Right = best (#1 ★)
    ══════════════════════════════════════════ */
    function buildRankSlider(area, cfg) {
      const min   = cfg.min ?? 1;
      const max   = cfg.max ?? 9999;
      const pivot = Math.max(min + 1, Math.min(max - 1, 1000));
      let rank = Math.max(min, Math.min(max, cfg.initial ?? pivot));

      // Left half: log scale  max→pivot  mapped to sv 0→500
      // Right half: quadratic pivot→min  mapped to sv 500→1000
      //   t = (rank - min) / (pivot - min)  [0 at min, 1 at pivot]
      //   sv = 500 + (1 - sqrt(t)) * 500
      function rankToSv(r) {
        r = Math.max(min, Math.min(max, r));
        if (r >= pivot) {
          const t = Math.log(r / max) / Math.log(pivot / max);
          return Math.round(t * 500);
        } else {
          const t = (r - min) / (pivot - min);
          return Math.round(500 + (1 - Math.sqrt(t)) * 500);
        }
      }
      function svToRank(sv) {
        sv = Math.max(0, Math.min(1000, sv));
        if (sv <= 500) {
          const t = sv / 500;
          return Math.round(Math.exp(Math.log(max) + t * (Math.log(pivot) - Math.log(max))));
        } else {
          const u = (sv - 500) / 500;   // 0→1
          const t = (1 - u) * (1 - u);  // quadratic: t=1 at sv=500, t=0 at sv=1000
          return Math.round(min + t * (pivot - min));
        }
      }

      // ─ Number display (editable) ─
      const displayWrap = document.createElement('div');
      displayWrap.className = 'rank-display-wrap';
      const display = document.createElement('input');
      display.type = 'text'; display.inputMode = 'numeric';
      display.className = 'rank-display';
      const typeHint = document.createElement('span');
      typeHint.className = 'rank-type-hint'; typeHint.textContent = 'T';
      displayWrap.appendChild(display); displayWrap.appendChild(typeHint);
      area.appendChild(displayWrap);

      // ─ Slider ─
      const sliderRow = document.createElement('div');
      sliderRow.className = 'rank-slider-row';
      const leftLbl  = document.createElement('span');
      leftLbl.className = 'rank-slider-label';
      leftLbl.textContent = '#' + max.toLocaleString();
      const rightLbl = document.createElement('span');
      rightLbl.className = 'rank-slider-label';
      rightLbl.textContent = '#1 \u2605';
      const slider = document.createElement('input');
      slider.type = 'range'; slider.min = 0; slider.max = 1000; slider.step = 1;
      slider.className = 'rank-slider';
      const sliderWrap = document.createElement('div');
      sliderWrap.className = 'rank-slider-wrap';
      sliderWrap.appendChild(slider);
      const peerOverlay = document.createElement('div');
      peerOverlay.className = 'rank-peer-overlay';
      sliderWrap.appendChild(peerOverlay);
      sliderRow.appendChild(leftLbl); sliderRow.appendChild(sliderWrap); sliderRow.appendChild(rightLbl);
      area.appendChild(sliderRow);

      // ─ Arrow adj buttons — worse (higher #) on left, better (lower #) on right ─
      const adjRow = document.createElement('div');
      adjRow.className = 'rank-adj-row';
      [[+100,'\u25c4100','worse'],[+10,'\u25c410','worse'],[+1,'\u25c41','worse'],
       [-1,'1\u25ba','better'],[-10,'10\u25ba','better'],[-100,'100\u25ba','better']].forEach(([d,lbl,cls]) => {
        const btn = document.createElement('button');
        btn.className = 'rank-adj-btn rank-' + cls;
        btn.textContent = lbl;
        btn.onclick = () => { setRank(rank + d); _emitSelect(rank, true); };
        adjRow.appendChild(btn);
      });
      area.appendChild(adjRow);

      // ─ Preset buttons — worst on left, best (#1) on right ─
      const rawPresets = [10000, 5000, 2500, 1000, 500, 250, 100, 50, 1];
      const presets = rawPresets.filter(p => p >= min && p <= max);
      if (presets.length && presets[0] !== max && max <= 20000) presets.unshift(max);
      const presetRow = document.createElement('div');
      presetRow.className = 'rank-preset-row';
      const presetBtns = [];
      presets.forEach(p => {
        const btn = document.createElement('button');
        btn.className = 'rank-preset-btn';
        btn.textContent = p === 1  ? '#1 \u2605'
          : p % 1000 === 0         ? '#' + (p / 1000) + 'K'
          :                          '#' + p.toLocaleString();
        btn.onclick = () => { setRank(p); _emitSelect(rank, true); };
        presetRow.appendChild(btn);
        presetBtns.push({ val: p, el: btn });
      });
      area.appendChild(presetRow);

      function updateTrack(_sv) {
        slider.style.background = '#333';
      }
      function setRank(r) {
        rank = Math.max(min, Math.min(max, Math.round(r)));
        display.value = '#' + rank.toLocaleString();
        const sv = rankToSv(rank);
        slider.value = sv;
        updateTrack(sv);
        presetBtns.forEach(({ val, el }) =>
          el.classList.toggle('rank-active', val === rank));
      }

      slider.addEventListener('input', () => {
        rank = svToRank(parseInt(slider.value));
        display.value = '#' + rank.toLocaleString();
        updateTrack(parseInt(slider.value));
        presetBtns.forEach(({ val, el }) =>
          el.classList.toggle('rank-active', val === rank));
        _emitSelect(rank, true);
      });
      display.addEventListener('focus', () => { display.value = String(rank); });
      display.addEventListener('keydown', e => {
        if (!/^[0-9]$/.test(e.key) &&
            !['Backspace','Delete','ArrowLeft','ArrowRight','Tab','Enter'].includes(e.key))
          e.preventDefault();
        if (e.key === 'Enter') display.blur();
      });
      display.addEventListener('blur', () => {
        const parsed = parseInt(display.value, 10);
        if (!isNaN(parsed)) setRank(parsed); else setRank(rank);
        _emitSelect(rank, true);
      });

      function updatePeerMarks(answers) {
        peerOverlay.innerHTML = '';
        (answers || []).forEach(a => {
          const r = parseInt(a.answer, 10);
          if (isNaN(r)) return;
          const sv = rankToSv(r);
          const pct = (sv / 1000) * 100;
          const tick = document.createElement('div');
          tick.className = 'rank-peer-tick';
          tick.style.left = pct + '%';
          tick.title = a.name + ': #' + r.toLocaleString();
          peerOverlay.appendChild(tick);
        });
      }

      setRank(rank);
      return { getValue: () => rank, updatePeerMarks };
    }

    /* ══════════════════════════════════════════
       TAG CHIPS
       data.tags = ['Action', 'Comedy', …]
    ══════════════════════════════════════════ */
    function buildTags(area, tags, maxPicks) {
      let selectedTags = new Set();
      const limit = maxPicks || tags.length;

      const counter = document.createElement('div');
      counter.style.cssText = 'text-align:center; font-size:0.85em; color:#aaa;'
        + ' margin-bottom:10px;';

      const grid = document.createElement('div');
      grid.className = 'tag-grid';

      function updateCounter() {
        counter.textContent = selectedTags.size + ' / ' + limit + ' selected';
        document.getElementById('submit-btn').disabled = selectedTags.size === 0;
        if (selectedTags.size > 0) _emitSelect(Array.from(selectedTags).join(','), true);
      }

      tags.forEach(tag => {
        const chip = document.createElement('div');
        chip.className = 'tag-chip';
        chip.textContent = tag;
        chip.dataset.tag = tag;
        chip.onclick = () => {
          if (chip.classList.contains('used')) return;
          if (chip.classList.contains('selected')) {
            chip.classList.remove('selected');
            selectedTags.delete(tag);
          } else {
            if (selectedTags.size >= limit) return;  // at cap
            chip.classList.add('selected');
            selectedTags.add(tag);
          }
          updateCounter();
        };
        grid.appendChild(chip);
      });

      area.appendChild(counter);
      area.appendChild(grid);
      updateCounter();

      return {
        getValue: () => Array.from(selectedTags).join(','),
        // restore previously-selected tags on reconnect
        restoreSelected: (csv) => {
          if (!csv) return;
          csv.split(',').forEach(t => {
            const chip = grid.querySelector('[data-tag="' + t.trim() + '"]');
            if (chip) { chip.classList.add('selected'); selectedTags.add(t.trim()); }
          });
          updateCounter();
        }
      };
    }

    /* ── Drum ↔ text toggle wrapper ── */
    const _textModeKeys = { year: 'gta_text_year', score: 'gta_text_score' };

    function _buildTextShortcuts(typeKey, constraints) {
      if (!constraints) return [];
      const min = Number(constraints.min);
      const max = Number(constraints.max);
      const step = Number(constraints.step || 1);
      const decimals = Number(constraints.decimals || 0);
      const quant = (v) => {
        const q = Math.round(Number(v) / step) * step;
        return Number(q.toFixed(decimals));
      };
      let arr = [];
      if (typeKey === 'year') {
        arr = [1960, 1970, 1980, 1990, 2000, 2005, 2010, 2015, 2020, 2025];
      } else if (typeKey === 'score') {
        arr = decimals > 0
          ? [2.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9]
          : [50, 60, 70, 80, 90];
      }
      return [...new Set(arr.map(quant).filter(v => v >= min && v <= max))].sort((a, b) => a - b);
    }

    // constraints: { min, max, step, decimals }  (optional — only for numeric types)
    function buildToggleable(area, freeInput, typeKey, buildFn, constraints) {
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'input-toggle';
      _toggleBtnRef = toggleBtn;   // expose so submitAnswer can disable it

      function setup() {
        area.innerHTML = '';
        area.appendChild(toggleBtn);
        const oldTextShortcuts = document.getElementById('text-shortcuts-row');
        if (oldTextShortcuts) oldTextShortcuts.remove();
        const textMode = localStorage.getItem(_textModeKeys[typeKey]) === '1';
        if (textMode) {
          toggleBtn.textContent = '\uD83E\uDD41 Switch to drum';
          // Switch to numeric keyboard with browser-enforced min/max/step
          freeInput.type = constraints ? 'number' : 'text';
          if (constraints) {
            freeInput.min  = constraints.min;
            freeInput.max  = constraints.max;
            freeInput.step = constraints.step || 1;
            freeInput.setAttribute('inputmode', 'decimal');
          }
          freeInput.style.display = 'block';
          freeInput.value = '';
          freeInput.focus();
          drumHandle = null;
          const picks = _buildTextShortcuts(typeKey, constraints);
          if (picks.length) {
            const row = document.createElement('div');
            row.id = 'text-shortcuts-row';
            row.className = 'drum-shortcuts';
            picks.forEach(v => {
              const b = document.createElement('button');
              b.className = 'drum-shortcut-btn';
              b.textContent = Number(constraints.decimals || 0) > 0 ? Number(v).toFixed(Number(constraints.decimals || 0)) : String(v);
              b.onclick = () => {
                freeInput.value = b.textContent;
                _emitSelect(b.textContent, true);
                freeInput.focus();
              };
              row.appendChild(b);
            });
            const parent = freeInput.parentNode;
            if (parent) parent.insertBefore(row, freeInput.nextSibling);
          }
        } else {
          toggleBtn.textContent = '\u2328\uFE0F Type instead';
          freeInput.style.display = 'none';
          // Reset to plain text for next time this input is reused
          freeInput.type = 'text';
          freeInput.removeAttribute('min');
          freeInput.removeAttribute('max');
          freeInput.removeAttribute('step');
          freeInput.removeAttribute('inputmode');
          drumHandle = buildFn(area);
        }
      }

      toggleBtn.onclick = () => {
        const cur = localStorage.getItem(_textModeKeys[typeKey]) === '1';
        localStorage.setItem(_textModeKeys[typeKey], cur ? '0' : '1');
        document.getElementById('free-error').style.display = 'none';
        setup();
      };

      setup();
    }

    /* ── Active input handles ── */
    let drumHandle        = null;
    let stepperHandle     = null;
    let rankSliderHandle  = null;
    let tagHandle         = null;
    let _takenYears   = new Set();  // years taken this round (year questions only)
    let _takenScores  = new Set();  // scores taken this round (drum questions only)
    let _takenRanks   = new Set();  // ranks taken this round (rank_slider questions only)

    /* ── Anime title autocomplete ── */
    let _cachedTitles = null;
    let _acActiveIdx = -1;
    function _loadAnimeTitles(cb) {
      if (_cachedTitles !== null) { cb(); return; }
      fetch('/titles').then(r => r.json()).then(titles => {
        _cachedTitles = titles;
        cb();
      }).catch(() => { _cachedTitles = []; cb(); });
    }
    function _acInput()  { return document.getElementById('anime-ac-input'); }
    function _acDrop()   { return document.getElementById('anime-ac-drop'); }
    function _acWrap()   { return document.getElementById('anime-ac-wrap'); }
    function _acShow(items, query) {
      const drop = _acDrop();
      drop.innerHTML = '';
      _acActiveIdx = -1;
      if (!items.length) { drop.style.display = 'none'; return; }
      const q = query.toLowerCase();
      items.forEach((t, i) => {
        const div = document.createElement('div');
        div.className = 'ac-item';
        // Bold the matching portion
        const lo = t.toLowerCase();
        const idx = lo.indexOf(q);
        if (idx >= 0 && q) {
          div.innerHTML = _escHtml(t.slice(0, idx))
            + '<em>' + _escHtml(t.slice(idx, idx + q.length)) + '</em>'
            + _escHtml(t.slice(idx + q.length));
        } else {
          div.textContent = t;
        }
        div.addEventListener('mousedown', e => { e.preventDefault(); _acPick(t); });
        drop.appendChild(div);
      });
      drop.style.display = 'block';
    }
    function _acHide() {
      _acDrop().style.display = 'none';
      _acActiveIdx = -1;
    }
    function _acPick(value) {
      _acInput().value = value;
      _acHide();
      _emitSelect(value, true);
    }
    function _escHtml(s) {
      return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
    function _acMoveCursor(dir) {
      const items = _acDrop().querySelectorAll('.ac-item');
      if (!items.length) return;
      items[_acActiveIdx]?.classList.remove('ac-active');
      _acActiveIdx = Math.max(-1, Math.min(items.length - 1, _acActiveIdx + dir));
      if (_acActiveIdx >= 0) {
        items[_acActiveIdx].classList.add('ac-active');
        items[_acActiveIdx].scrollIntoView({ block: 'nearest' });
      }
    }
    function _setupAnimeAc(savedAnswer) {
      const inp = _acInput();
      _acWrap().style.display = 'block';
      inp.value = savedAnswer || '';
      inp.oninput = () => {
        const q = inp.value;
        if (!_cachedTitles || q.length < 2) { _acHide(); return; }
        const matches = _cachedTitles.filter(t => t.toLowerCase().includes(q.toLowerCase())).slice(0, 50);
        _acShow(matches, q);
        _emitSelect(inp.value.trim(), true);
      };
      inp.onkeydown = e => {
        if (e.key === 'ArrowDown') { e.preventDefault(); _acMoveCursor(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); _acMoveCursor(-1); }
        else if (e.key === 'Enter') {
          const items = _acDrop().querySelectorAll('.ac-item');
          if (_acActiveIdx >= 0 && items[_acActiveIdx]) {
            e.preventDefault();
            _acPick(items[_acActiveIdx].textContent);
          } else {
            _acHide();
            submitAnswer();
          }
        } else if (e.key === 'Escape') { _acHide(); }
      };
      inp.onblur = () => setTimeout(_acHide, 150);
      inp.focus();
    }
    function _teardownAnimeAc() {
      _acWrap().style.display = 'none';
      _acHide();
      const inp = _acInput();
      inp.oninput = null; inp.onkeydown = null; inp.onblur = null; inp.value = '';
    }
    function _getAnimeAcValue() { return _acInput().value.trim(); }

    function _lockSubmittedUI(savedAnswer) {
      // Called after any answer is submitted (or on reconnect when already answered).
      document.getElementById('submit-btn').disabled = true;
      const sentMsg = document.getElementById('sent-msg');
      sentMsg.style.display = 'block';
      sentMsg.textContent = savedAnswer != null
        ? 'Submitted: ' + savedAnswer
        : 'Answer submitted!';
      document.getElementById('free-error').style.display = 'none';
      document.getElementById('free-input').disabled = true;
      const acInp = document.getElementById('anime-ac-input');
      if (acInp) { acInp.disabled = true; }
      document.getElementById('choices-area').style.pointerEvents = 'none';
      document.getElementById('choices-area').style.opacity = '0.5';
      if (_toggleBtnRef) { _toggleBtnRef.disabled = true; _toggleBtnRef.style.opacity = '0.35'; }
    }

    /* ── Socket events ── */
    socket.on('question', data => {
      try {

      } catch(e) {}
      _answersRevealed = false;
      _isBuzzerQuestion = !!(data && data.buzzer_only);
      _currentQuestionTitle = data.title || '';
      _myLastAnswer = null;
      _currentQid   = data.qid || null;
      _toggleBtnRef = null;
      document.getElementById('waiting').style.display = 'none';
      document.getElementById('question-area').style.display = 'block';
      // Ensure per-question UI is visible again (may have been hidden during a clear)
      const qCardShow = document.getElementById('q-card'); if (qCardShow) qCardShow.style.display = '';
      const choicesAreaShow = document.getElementById('choices-area'); if (choicesAreaShow) { choicesAreaShow.style.display = ''; choicesAreaShow.innerHTML = ''; }
      const freeInputShow = document.getElementById('free-input'); if (freeInputShow) { freeInputShow.style.display = 'none'; freeInputShow.value = ''; }
      const submitBtnShow = document.getElementById('submit-btn'); if (submitBtnShow) { submitBtnShow.style.display = ''; submitBtnShow.disabled = false; }
      document.getElementById('prev-question').style.display = 'none';
      // Reset host toggle label to Submitted Answers for the new question
      try { const ht = document.getElementById('host-toggle'); if (ht && ht.style.display !== 'none') ht.textContent = '\uD83D\uDC41 Submitted Answers (0)'; } catch(e) {}
      document.getElementById('q-title').textContent = data.title;
      document.getElementById('q-info').textContent = data.info || '';
      document.getElementById('sent-msg').style.display = 'none';
      // Clear host answers for any new question (they should be reset when a new
      // question arrives). Show the host panel for hosts if they previously left it open.
      const _hostPanelEl = document.getElementById('host-panel');
      document.getElementById('host-answers').innerHTML = '';
      try {
        if (_isHost) {
          _hostPanelEl.style.display = localStorage.getItem('hostPanelOpen') === '1' ? 'block' : 'none';
        } else {
          _hostPanelEl.style.display = 'none';
        }
      } catch(e) { _hostPanelEl.style.display = 'none'; }
      const _ht = document.getElementById('host-toggle');
      // Don't reset the host answers count for hosts; only reset for non-hosts.
      if (!_isHost) {
        if (_ht.style.display !== 'none') _ht.textContent = '\uD83D\uDC41 Submitted Answers (0)';
      }
      document.getElementById('peer-answers-wrap').style.display = 'none';
      document.getElementById('peer-answers-list').innerHTML = '';
      _peerAnswersOpen = false;
      const _peerToggle = document.getElementById('peer-answers-toggle');
      if (_peerToggle) _peerToggle.textContent = '\uD83D\uDC41 Submitted Answers (0)';
      document.getElementById('submit-btn').disabled = false;
      document.getElementById('free-input').disabled = false;
      const acInpReset = document.getElementById('anime-ac-input');
      if (acInpReset) acInpReset.disabled = false;
      selectedChoice = null;
      drumHandle = null; stepperHandle = null; rankSliderHandle = null; tagHandle = null;
      _takenYears  = new Set();
      _takenScores = new Set();
      _takenRanks  = new Set();

      const area = document.getElementById('choices-area');
      area.innerHTML = '';
      const freeInput = document.getElementById('free-input');
      freeInput.style.display = 'none';
      freeInput.type = 'text';
      freeInput.removeAttribute('min'); freeInput.removeAttribute('max');
      freeInput.removeAttribute('step'); freeInput.removeAttribute('inputmode');
      freeInput.removeAttribute('list');
      freeInput.oninput = null;
      _teardownAnimeAc();
      document.getElementById('free-error').style.display = 'none';
      area.style.pointerEvents = ''; area.style.opacity = '';

      const _alreadyAnswered = _currentQid && localStorage.getItem('gta_answered_' + _currentQid);
      const _savedAnswer     = _alreadyAnswered ? localStorage.getItem('gta_answer_' + _currentQid) : null;
      if (_savedAnswer) _myLastAnswer = _savedAnswer;  // restore so taken-year guard allows own year

      if (data.choices && data.choices.length > 0) {
        /* ── Multiple choice ── */
        data.choices.forEach((choice, i) => {
          const label = String.fromCharCode(65 + i);
          const btn = document.createElement('button');
          btn.className = 'choice-btn';
          btn.textContent = '[' + label + '] ' + choice;
          if (_savedAnswer === choice) btn.classList.add('selected');
          btn.onclick = () => {
            document.querySelectorAll('.choice-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            selectedChoice = choice;
            _emitSelect(choice, true);
          };
          area.appendChild(btn);
        });

      } else if (data.year) {
        /* ── Year picker with drum↔text toggle ── */
        buildToggleable(area, freeInput, 'year', a => buildYearPicker(a,
            _savedAnswer ? {...data.year, initial: parseInt(_savedAnswer, 10), myYear: parseInt(_savedAnswer, 10)} : data.year),
          { min: data.year.min, max: data.year.max, step: 1, decimals: 0 });
        if (_savedAnswer && freeInput.style.display !== 'none') freeInput.value = _savedAnswer;
        if (data.taken_years && data.taken_years.length) {
          data.taken_years.forEach(y => {
            _takenYears.add(String(y));
            if (drumHandle && drumHandle.markTaken) drumHandle.markTaken(y);
          });
        }

      } else if (data.drum) {
        /* ── Score drum with drum↔text toggle ── */
        const _drumCfg = _savedAnswer ? {...data.drum, initial: parseFloat(_savedAnswer), myScore: parseFloat(_savedAnswer)} : data.drum;
        buildToggleable(area, freeInput, 'score', a => buildDrum(a, _drumCfg),
          { min: data.drum.min, max: data.drum.max, step: data.drum.step, decimals: data.drum.decimals });
        if (_savedAnswer && freeInput.style.display !== 'none') freeInput.value = _savedAnswer;
        if (data.taken_scores && data.taken_scores.length) {
          data.taken_scores.forEach(s => {
            _takenScores.add(String(s));
            if (drumHandle && drumHandle.markScoreTaken) drumHandle.markScoreTaken(s);
          });
        }

      } else if (data.stepper) {
        /* ── Stepper ── */
        stepperHandle = buildStepper(area,
          _savedAnswer ? {...data.stepper, initial: parseFloat(_savedAnswer)} : data.stepper);

      } else if (data.rank_slider) {
        /* ── Rank slider ── */
        rankSliderHandle = buildRankSlider(area,
          _savedAnswer ? {...data.rank_slider, initial: parseInt(_savedAnswer, 10)} : data.rank_slider);
        if (data.taken_ranks && data.taken_ranks.length) {
          data.taken_ranks.forEach(r => _takenRanks.add(String(r)));
        }

      } else if (data.tags) {
        /* ── Tag chips (multi-select) ── */
        tagHandle = buildTags(area, data.tags, data.tags_max);
        if (_savedAnswer) tagHandle.restoreSelected(_savedAnswer);
        // Submit starts disabled until at least one chip is picked
        document.getElementById('submit-btn').disabled = true;

      } else {
        /* ── Free text (with optional anime autocomplete) ── */
        freeInput.oninput = null;
        clearTimeout(_selectDebounceTimer);
        freeInput.style.display = 'block';
        freeInput.value = _savedAnswer || '';
        freeInput.oninput = () => _emitSelect(freeInput.value.trim(), true);
        if (data.autocomplete === 'anime') {
          _loadAnimeTitles(() => {
            const dl = document.getElementById('anime-titles-list');
            dl.innerHTML = '';
            (_cachedTitles || []).forEach(t => {
              const opt = document.createElement('option'); opt.value = t; dl.appendChild(opt);
            });
            freeInput.setAttribute('list', 'anime-titles-list');
          });
        } else {
          freeInput.removeAttribute('list');
        }
        freeInput.focus();
      }

      if (data.buzzer_only) {
        const choicesAreaOnly = document.getElementById('choices-area');
        if (choicesAreaOnly) { choicesAreaOnly.innerHTML = ''; choicesAreaOnly.style.display = 'none'; }
        const freeOnly = document.getElementById('free-input');
        if (freeOnly) freeOnly.style.display = 'none';
        const submitOnly = document.getElementById('submit-btn');
        if (submitOnly) submitOnly.style.display = 'none';
        document.getElementById('sent-msg').style.display = 'none';
      }

      if (_alreadyAnswered) _lockSubmittedUI(_savedAnswer);
      else if (_myLastAnswer !== null) _lockSubmittedUI(_myLastAnswer.includes(',') ? _myLastAnswer.replace(/,/g, ', ') : _myLastAnswer);

      _updateBuzzerUI();
    });

    socket.on('rules_update', data => {
      _applyRules(data.header || '', data.body || '');
    });

    socket.on('year_taken', data => {
      const y = data.year;
      _takenYears.add(String(y));
      if (drumHandle && drumHandle.markTaken) drumHandle.markTaken(y);
    });

    socket.on('score_taken', data => {
      const s = data.score;
      _takenScores.add(String(s));
      if (drumHandle && drumHandle.markScoreTaken) drumHandle.markScoreTaken(s);
    });

    socket.on('host_granted', data => {
      console.log('[GTA] host_granted received');
      _isHost = true;
      document.getElementById('host-toggle').style.display = 'block';
      try {
        if (localStorage.getItem('hostPanelOpen') === '1') {
          document.getElementById('host-panel').style.display = 'block';
        }
      } catch(e) {}
      document.getElementById('controls-wrap').style.display = 'block';
      document.getElementById('metadata-wrap').style.display = 'block';
      if (!_ctrlPlaylistVisible) document.getElementById('ctrl-playlist-toggle').style.display = '';
      else document.getElementById('ctrl-playlist-toggle').style.display = '';
      document.getElementById('sc-view-wrap').style.display = 'flex';
      const _scHC = document.getElementById('sc-host-controls');
      if (_scHC) _scHC.style.display = 'block';
      const _scCH = document.getElementById('sc-col-headers');
      if (_scCH) _scCH.style.display = 'flex';
      _scRestoreView();
      _refreshHostAnswers(data.answers || []);
      _placeHostAnswers();
      _renderHostMessages(_hostMessages);
      _refreshPlayerList(_lastPlayerList);
      const msgRow = document.getElementById('host-msg-row');
      if (msgRow) msgRow.style.display = 'none';
      // Hide peer answers panel — host has their own answers view
      document.getElementById('peer-answers-wrap').style.display = 'none';
      document.getElementById('peer-answers-list').innerHTML = '';
      _peerAnswersOpen = false;
      _autoOpenSidePanels(true);
      if (_metadataOpen && _metadataTab === 'themes') {
        _renderSeriesThemes(_metaViewData());
      }
    });

    socket.on('player_colors_update', data => {
      _playerColors = data.colors || {};
      _updateLabelSwatch();
      _refreshPlayerList(_lastPlayerList);
    });

    socket.on('answer_update', data => {
      _refreshHostAnswers(data.answers || []);
    });

    socket.on('host_messages_update', data => {
      _renderHostMessages((data && data.messages) || []);
    });

    socket.on('host_message_toast', data => {
      _showHostMessageToast(data || {});
    });

    socket.on('players_update', data => {
      _lastPlayerList = data.players || [];
      _refreshPlayerList(_lastPlayerList);
      _scRenderGhosts();
    });

    socket.on('peer_answers_update', data => {
      if (!_isHost) _refreshPeerAnswers(data.answers || []);
    });

    socket.on('rank_marks_update', data => {
      if (rankSliderHandle) rankSliderHandle.updatePeerMarks(data.answers || []);
    });

    socket.on('rank_taken', data => {
      _takenRanks.add(String(data.rank));
    });

    socket.on('answer_reveal', data => {
      _prevQTitle        = data.question      || '';
      _prevQCorrect      = data.correct       || '';
      _prevQType         = data.q_type        || '';
      _prevQCorrectTags  = data.correct_tags  || [];
      _answersRevealed = true;
      // When answers are revealed, remove the ability to remove answers
      // from the host view (the 'x' button no longer does anything).
      try {
        const hostList = document.getElementById('host-answers');
        if (hostList) {
          hostList.querySelectorAll('.ha-remove').forEach(b => b.remove());
        }
      } catch(e) {}
    });

    socket.on('clear', data => {
      _currentQid = null;
      _isBuzzerQuestion = false;
      // Show waiting message but keep the question-area visible so host answers
      // panel isn't hidden. Hide per-question UI elements instead.
      document.getElementById('waiting').style.display = 'block';
      document.getElementById('question-area').style.display = 'block';
      // Hide question-specific elements but leave host panel visible
      const qCard = document.getElementById('q-card'); if (qCard) qCard.style.display = 'none';
      const choicesArea = document.getElementById('choices-area'); if (choicesArea) { choicesArea.innerHTML = ''; choicesArea.style.display = 'none'; }
      const freeInput = document.getElementById('free-input'); if (freeInput) freeInput.style.display = 'none';
      const submitBtn = document.getElementById('submit-btn'); if (submitBtn) submitBtn.style.display = 'none';
      _applyRules((data && data.rules_header) || '', (data && data.rules_body) || '');
      _showPrevQuestion();
      // Update host toggle to indicate these are previous answers
      try {
        const ht = document.getElementById('host-toggle');
        const hostList = document.getElementById('host-answers');
        const cnt = hostList ? hostList.children.length : 0;
        if (ht && ht.style.display !== 'none') ht.textContent = '\uD83D\uDC41 Previous Submitted Answers (' + cnt + ')';
      } catch(e) {}
      // Mirror the same previous-answer state for non-host peer answers
      try {
        const peerWrap = document.getElementById('peer-answers-wrap');
        const peerList = document.getElementById('peer-answers-list');
        const peerToggle = document.getElementById('peer-answers-toggle');
        const cnt = peerList ? peerList.children.length : 0;
        if (peerToggle) peerToggle.textContent = '\uD83D\uDC41 Previous Submitted Answers (' + cnt + ')';
        if (peerWrap && cnt > 0) {
          peerWrap.style.display = 'block';
          peerList.style.display = _peerAnswersOpen ? 'block' : 'none';
        }
      } catch(e) {}

      _updateBuzzerUI();
    });

    /* ── Timer ── */
    socket.on('timer_update', data => {
      _timerSeconds = parseFloat(data.seconds) || 0;
      _timerPaused  = !!data.paused;
      _timerRunning = true;
      _timerLastTs  = null;
      document.getElementById('timer-bar').style.visibility = 'visible';
      document.getElementById('timer-display').style.display = '';
      document.getElementById('timer-title').style.display = 'none';
      _renderTimer();
      if (_timerRafId) { cancelAnimationFrame(_timerRafId); _timerRafId = null; }
      if (!_timerPaused && _timerSeconds > 0) _timerRafId = requestAnimationFrame(_timerRaf);
    });
    socket.on('timer_clear', () => {
      _timerRunning = false;
      _timerLastTs  = null;
      if (_timerRafId) { cancelAnimationFrame(_timerRafId); _timerRafId = null; }
      document.getElementById('timer-bar').style.visibility = 'visible';
      document.getElementById('timer-display').style.display = 'none';
      document.getElementById('timer-title').style.display = '';
    });
    function _timerRaf(ts) {
      if (!_timerRunning || _timerPaused) { _timerRafId = null; return; }
      if (_timerLastTs !== null) {
        _timerSeconds = Math.max(0, _timerSeconds - (ts - _timerLastTs) / 1000);
      }
      _timerLastTs = ts;
      _renderTimer();
      _timerRafId = _timerSeconds > 0 ? requestAnimationFrame(_timerRaf) : null;
    }
    function _renderTimer() {
      const disp  = document.getElementById('timer-display');
      const total = Math.max(0, Math.ceil(_timerSeconds));
      disp.textContent = String(total);
      disp.className   = total <= 5 ? 'timer-warning' : '';
    }

    /* ── History modal ── */
    let _historyText = '';
    function _openHistory() {
      const zoom = parseFloat(document.documentElement.style.zoom) || 1;
      document.getElementById('history-box').style.maxHeight = Math.floor(window.innerHeight / zoom * 0.80) + 'px';
      document.getElementById('history-text-area').textContent = _historyText || 'No history yet.';
      document.getElementById('history-overlay').classList.add('active');
      // ensure the text area scrolls to the bottom after it's rendered
      requestAnimationFrame(() => {
        try {
          const el = document.getElementById('history-text-area');
          if (el) el.scrollTop = el.scrollHeight;
        } catch (e) {}
      });
    }
    function _closeHistory() {
      document.getElementById('history-overlay').classList.remove('active');
    }
    document.getElementById('history-overlay').addEventListener('click', e => {
      if (e.target === document.getElementById('history-overlay')) _closeHistory();
    });
    socket.on('session_history', data => {
      _historyText = data.text || '';
      const dl = document.getElementById('history-dl-btn');
      if (dl && data.filename) dl.setAttribute('download', data.filename);
    });

    /* ── Previous question display ── */
    function _showPrevQuestion() {
      const box = document.getElementById('prev-question');
      if (!_prevQCorrect) { box.style.display = 'none'; return; }
      document.getElementById('prev-question-title').textContent = _prevQTitle;
      document.getElementById('prev-question-correct').textContent = 'Correct answer: ' + _prevQCorrect.replace(/,/g, ', ');
      const mineDiv = document.getElementById('prev-question-mine');
      if (_prevQType === 'tags') {
        const myTags = _myLastAnswer ? _myLastAnswer.split(',').map(t => t.trim()).filter(Boolean) : [];
        const correctSet = new Set(_prevQCorrectTags.map(t => t.trim().toLowerCase()));
        if (!myTags.length) {
          mineDiv.innerHTML = '';
          mineDiv.style.color = '';
          mineDiv.textContent = 'Your answer: No answer submitted';
        } else {
          mineDiv.style.color = '';
          mineDiv.innerHTML = 'Your answer:\u00a0' + myTags.map(t =>
            '<span class="pq-tag ' + (correctSet.has(t.toLowerCase()) ? 'pq-tag-correct' : 'pq-tag-wrong') + '">' + _escHtml(t) + '</span>'
          ).join('');
        }
      } else {
        const mine = _myLastAnswer ? _myLastAnswer.replace(/,/g, ', ') : '';
        const isCorrect = mine && mine.trim().toLowerCase() === _prevQCorrect.trim().toLowerCase();
        mineDiv.innerHTML = '';
        mineDiv.textContent = mine ? ('Your answer: ' + mine) : 'Your answer: No answer submitted';
        mineDiv.style.color = (mine && isCorrect) ? '#5c5' : '#aaa';
      }
      box.style.display = 'block';
    }

    /* ── Host view helpers ── */
    function _applyRules(header, body) {
      const el = document.getElementById('waiting-rules');
      if (header || body) {
        document.getElementById('waiting-rules-header').textContent = header;
        document.getElementById('waiting-rules-header').style.display = header ? 'block' : 'none';
        document.getElementById('waiting-rules-body').textContent = body;
        el.style.display = 'block';
      } else {
        el.style.display = 'none';
      }
    }

    function _toggleHostPanel() {
      const p = document.getElementById('host-panel');
      const open = p.style.display === 'none';
      p.style.display = open ? 'block' : 'none';
      try { localStorage.setItem('hostPanelOpen', open ? '1' : '0'); } catch(e) {}
    }
    function _placeHostAnswers() {
      const toggle = document.getElementById('host-toggle');
      const panel = document.getElementById('host-panel');
      if (!toggle || !panel) return;
      const qAnchor = document.getElementById('host-answers-anchor-question');
      const sAnchor = document.getElementById('host-answers-anchor-score');
      const target = (_isHost && _scViewOpen) ? sAnchor : qAnchor;
      if (!target) return;
      if (toggle.parentElement !== target) target.appendChild(toggle);
      if (panel.parentElement !== target) target.appendChild(panel);
    }
    function _refreshHostAnswers(answers) {
      const container = document.getElementById('host-answers');
      container.innerHTML = '';
      answers.forEach((a, idx) => {
        const div = document.createElement('div');
        div.className = 'host-answer';
        const text = document.createElement('span');
        text.className = 'ha-text';
        text.innerHTML = '<span class="ha-name">' + _escHtml(a.name) + '</span>: ' + _escHtml(a.answer);
        div.appendChild(text);
        if (!_answersRevealed) {
          const rm = document.createElement('button');
          rm.className = 'ha-remove';
          rm.title = 'Remove this answer';
          rm.textContent = '\u00d7';
          rm.onclick = () => _confirm(
            'Remove answer from ' + a.name + '?', 'Remove',
            () => socket.emit('remove_answer', { index: idx })
          );
          div.appendChild(rm);
          // Right-click also removes
          div.addEventListener('contextmenu', e => {
            e.preventDefault();
            _confirm('Remove answer from ' + a.name + '?', 'Remove',
              () => socket.emit('remove_answer', { index: idx }));
          });
        }
        container.appendChild(div);
      });
      const ht = document.getElementById('host-toggle');
      ht.textContent = '\uD83D\uDC41 Submitted Answers (' + answers.length + ')';
    }

    /* ── Kick options modal ── */
    function _kickOptions(player) {
      const name = (player && player.name) ? player.name : String(player || '');
      if (player && player.host) {
        alert('Host cannot be renamed from this menu.');
        return;
      }
      const emojiMuted = !!(player && player.emoji_muted);
      document.getElementById('kick-player-name').textContent = 'Action for: ' + name;
      document.getElementById('kick-btn-shadow').onclick = () => { _kickCancel(); socket.emit('remove_player', { name }); };
      document.getElementById('kick-btn-rename').onclick = () => {
        const next = prompt('Rename "' + name + '" to:', name);
        if (next === null) return;
        const newName = String(next || '').trim();
        if (!newName || newName === name) return;
        if (/\s/.test(newName)) { alert('Name cannot contain spaces.'); return; }
        if (newName.length > 30) { alert('Name is too long (max 30).'); return; }
        _kickCancel();
        socket.emit('rename_player', { old_name: name, new_name: newName });
      };
      document.getElementById('kick-btn-name').onclick   = () => { _kickCancel(); socket.emit('name_ban',      { name }); };
      document.getElementById('kick-btn-ip').onclick     = () => { _kickCancel(); socket.emit('ip_ban',        { name }); };
      const eb = document.getElementById('kick-btn-emoji');
      if (eb) {
        eb.textContent = emojiMuted ? 'Enable Emojis' : 'Disable Emojis';
        eb.onclick = () => {
          _kickCancel();
          socket.emit(emojiMuted ? 'emoji_enable' : 'emoji_disable', { name });
        };
      }
      document.getElementById('kick-overlay').classList.add('active');
    }
    function _kickCancel() {
      document.getElementById('kick-overlay').classList.remove('active');
    }

    socket.on('banned', () => {
      document.getElementById('name-screen').style.display    = 'none';
      document.getElementById('question-box').style.display   = 'none';
      document.getElementById('player-list-wrap').style.display = 'none';
      document.getElementById('metadata-wrap').style.display  = 'none';
      document.getElementById('controls-wrap').style.display   = 'none';
      document.getElementById('banned-screen').style.display  = 'block';
    });

    /* ── Emoji reactions ── */
    const _CUSTOM_EMOJI_KEY = 'gta_custom_emojis';
    const _DEFAULT_EMOJIS = ['👍','👎','❤️','😂','😮','😢','🔥','⭐','🎉','💀','🤔','👏','⏩'];
    const _PICKER_EMOJIS = [
      // Faces
      '😀','😂','🤣','😅','😊','🥰','😍','🤩','😎','🥳','😏','😒','😔','😢','😭','😤','😠','🤬','😱','😨',
      '🤔','🤗','🤫','🤭','😶','😬','🙄','😴','🥱','😷','🤒','🤯','🥺','🥹','😇','🙃','🫡','🫠','🫣','🤡','👻','💀',
      '☠️','👽','🤖','🎃','🗿','🙈','🙉','🙊',
      // Gestures
      '👍','👎','👏','🙌','🤝','🤜','🤛','✌️','🤞','👌','🤌','🤙','🫰','🤦','☝️','👆','👇','👉','👈','🖐️','✋','🫶',
      // Hearts & love
      '❤️','🧡','💛','💚','💙','💜','🖤','🤍','💔','💕','💞','💓','💗','💖','💘','💝',
      // Animals
      '🐶','🐱','🐭','🐰','🦊','🐻','🐼','🐯','🦁','🐸','🐵','🦄','🐝','🦋','🐢','🦈','🐬','🦉','🦚','🦜',
      // Sports & games
      '⚽','🏀','🎾','🏈','⚾','🎱','🏓','🥊','🎮','🎲','🃏','🏆','🥇','🎯','🎳',
      // Food & drink
      '🍕','🍔','🌮','🍜','🍣','🍱','🧁','🍩','🍪','🍦','🍺','☕','🧃','🥤',
      '🍆','🥑','🍓','🍇','🍉','🍑','🌽','🥕','🧄','🥐','🧀','🍗','🥩','🍳','🍙','🍤','🧆','🫕','🥞',
      // Nature, weather & places
      '🌈','⚡','🌊','💧','🌸','🍀','🌙','☀️','❄️','🌪️','⛩️',
      '🏖️','🏝️','🌴','🌵','🏔️','🗻','🌋','🌅','🌃','⛺','🏕️','🌿','🍂','🍁',
      // Arrows & directional
      '⬆️','⬇️','⬅️','➡️','↗️','↘️','↙️','↖️','↕️','↔️','🔄','🔃','↩️','↪️','⏪','⏩','⏫','⏬','⏭️','⏮️','🔁','🔂',
      // Objects & symbols
      '🔥','⭐','🌟','✨','💥','💫','🎉','🎊','🎈','🚀','🛸','👑','💎','🔮','🪄','🎁','🧸',
      '🎵','🎶','🎤','🎸','📷','📱','💻','🔑','⚙️','🧲','🔍','🔎','📊','📈','📉','🗓️','⏰','⌛','⏳','🔫',
      '✅','❌','⚠️','❓','❗','💯','🔔','📢','💬','👀','🫂','🚫','🔇','🔕','💤','🆗','🆙','🆕','🔝',
      // Anime & manga
      '⚔️','🗡️','🛡️','🏹','🪃','🔱','🌀','💢','💦','💨','💬','💭','‼️','⁉️',
      '🎴','🀄','🎎','🎏','🎐','🏮','🪔','🧧','🎋','🎍','🥷','🧝','🧙','🧛','🧜','🧚','🐉','🐲','🦊','🦝',
      '🌺','🌸','🌼','🌻','🌹','🪷','🍡','🍢','🍥','🍧','🍮','🧋','🍵','🍶','🥢',
      '📜','🗺️','🔭','🧪','🧬','⚗️','🪬','🫧',
      // Numbers
      '0️⃣','1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟',
      // Letters — use the reliable negative-squared letter emojis
      '🅰️','🅱️','🅾️','🅿️','🆎',
    ];

    function _loadSavedEmojis() {
      const stored = localStorage.getItem(_CUSTOM_EMOJI_KEY);
      if (stored === null) {
        _saveSavedEmojis([..._DEFAULT_EMOJIS]);
        return [..._DEFAULT_EMOJIS];
      }
      try { return JSON.parse(stored); }
      catch { return [..._DEFAULT_EMOJIS]; }
    }
    function _saveSavedEmojis(list) {
      localStorage.setItem(_CUSTOM_EMOJI_KEY, JSON.stringify(list));
    }
    let _emojiHostMuted = false;
    let _emojiTimeoutUntilMs = 0;
    let _emojiStatusTimer = null;
    function _setEmojiControlsDisabled(disabled) {
      const bar = document.getElementById('emoji-btns');
      if (!bar) return;
      bar.querySelectorAll('button').forEach(btn => { btn.disabled = !!disabled; });
    }
    function _updateEmojiStatusUI() {
      const el = document.getElementById('emoji-status');
      if (!el) return;
      const now = Date.now();
      const remainingMs = Math.max(0, _emojiTimeoutUntilMs - now);
      if (_emojiHostMuted) {
        el.textContent = 'Emoji reactions disabled by host.';
        el.style.display = 'block';
        _setEmojiControlsDisabled(true);
      } else if (remainingMs > 0) {
        const s = Math.ceil(remainingMs / 1000);
        el.textContent = 'Emoji timeout: ' + s + 's';
        el.style.display = 'block';
        _setEmojiControlsDisabled(true);
      } else {
        el.textContent = '';
        el.style.display = 'none';
        _setEmojiControlsDisabled(false);
      }
    }
    function _applyEmojiStatus(data) {
      const payload = data || {};
      _emojiHostMuted = !!payload.muted;
      const untilSec = Number(payload.timeout_until || 0);
      _emojiTimeoutUntilMs = untilSec > 0 ? Math.floor(untilSec * 1000) : 0;
      _updateEmojiStatusUI();
      if (_emojiStatusTimer == null) {
        _emojiStatusTimer = setInterval(_updateEmojiStatusUI, 250);
      }
    }
    function _rebuildEmojiBar() {
      const container = document.getElementById('emoji-btns');
      const editBtn = document.getElementById('emoji-add-btn');
      Array.from(container.children).forEach(c => { if (c !== editBtn) c.remove(); });
      _loadSavedEmojis().forEach(emoji => {
        const btn = document.createElement('button');
        btn.className = 'emoji-btn';
        btn.textContent = emoji;
        btn.onclick = () => _sendEmoji(emoji);
        container.insertBefore(btn, editBtn);
      });
      _updateEmojiStatusUI();
    }
    function _sendEmoji(emoji) {
      const now = Date.now();
      if (_emojiHostMuted || _emojiTimeoutUntilMs > now) {
        _updateEmojiStatusUI();
        return;
      }
      socket.emit('send_emoji', { emoji });
    }

    function _pressBuzz() {
      if (!_buzzerState.open || _buzzerState.locked) return;
      try {

      } catch(e) {}
      socket.emit('buzz_press', {});
    }

    function _updateBuzzerUI() {
      const panel = document.getElementById('buzzer-panel');
      const status = document.getElementById('buzzer-status');
      const btn = document.getElementById('buzz-btn');
      const list = document.getElementById('buzzer-order');
      if (!panel || !status || !btn || !list) return;

      const inQuestion = !!_currentQid;
      const order = Array.isArray(_buzzerState.order) ? _buzzerState.order : [];
      const myIdx = order.findIndex(x => x && x.name === playerName);
      const isOpen = !!_buzzerState.open;
      const isLocked = !!_buzzerState.locked;
      const shouldShow = !!_isBuzzerQuestion;

      panel.style.display = shouldShow ? 'block' : 'none';
      if (!shouldShow) return;

      if (isLocked) status.textContent = 'Buzzer locked.';
      else if (isOpen) status.textContent = myIdx >= 0 ? ('Buzz received #' + (myIdx + 1)) : 'Buzzer open — press BUZZ';
      else status.textContent = 'Buzzer idle.';

      btn.disabled = !inQuestion || !isOpen || isLocked || myIdx >= 0 || !playerName;

      // Submission order/timing now lives in Submitted Answers UI.
      list.style.display = 'none';
      list.innerHTML = '';
    }

    function _applyBuzzerState(data) {
      _buzzerState = Object.assign({ open: false, locked: false, order: [] }, data || {});
      // host button states
      const lockActive = !!_buzzerState.locked;
      document.querySelectorAll('[data-proxy-extra="buzz_lock"],[data-extra-id="buzz_lock"]').forEach(el => el.classList.toggle('ctrl-toggle-active', lockActive));
      _updateBuzzerUI();
    }

    function _openEmojiPicker() {
      const saved = _loadSavedEmojis();
      const grid = document.getElementById('emoji-picker-grid');
      grid.innerHTML = '';
      _PICKER_EMOJIS.forEach(emoji => {
        const isSaved = saved.includes(emoji);
        const btn = document.createElement('button');
        btn.className = 'ep-btn' + (isSaved ? ' ep-saved' : '');
        btn.textContent = emoji;
        btn.addEventListener('click', () => {
          const list = _loadSavedEmojis();
          const idx = list.indexOf(emoji);
          if (idx >= 0) {
            list.splice(idx, 1);
            btn.classList.remove('ep-saved');
          } else {
            list.push(emoji);
            btn.classList.add('ep-saved');
          }
          _saveSavedEmojis(list);
          _rebuildEmojiBar();
        });
        grid.appendChild(btn);
      });
      document.getElementById('emoji-picker-overlay').classList.add('active');
      const zoom = parseFloat(document.documentElement.style.zoom) || 1;
      document.getElementById('emoji-picker-box').style.maxHeight = Math.floor(window.innerHeight / zoom * 0.70) + 'px';
    }
    function _resetEmojiDefaults() {
      _saveSavedEmojis([..._DEFAULT_EMOJIS]);
      _rebuildEmojiBar();
      _openEmojiPicker();  // re-render picker highlights
    }
    function _closeEmojiPicker() {
      document.getElementById('emoji-picker-overlay').classList.remove('active');
    }
    socket.on('emoji_status', data => {
      _applyEmojiStatus(data || {});
    });
    socket.on('buzzer_state', data => {
      try {
        const d = data || {};

      } catch(e) {}
      _applyBuzzerState(data || {});
    });
    document.addEventListener('DOMContentLoaded', () => {
      _rebuildEmojiBar();
      _updateEmojiStatusUI();
      _updateBuzzerUI();
      _ctrlRenderPinnedExtras();
      _ctrlLoadPanels();
      const msgInput = document.getElementById('host-msg-input');
      if (msgInput) {
        msgInput.addEventListener('keydown', e => {
          if (e.key === 'Enter') _sendHostMessage();
        });
      }
      document.getElementById('emoji-picker-overlay').addEventListener('click', e => {
        if (e.target === document.getElementById('emoji-picker-overlay')) _closeEmojiPicker();
      });
    });

    /* ── Confirmation modal ── */
    let _confirmCallback = null;
    function _confirm(msg, yesLabel, cb) {
      document.getElementById('confirm-msg').textContent = msg;
      document.getElementById('confirm-yes').textContent = yesLabel;
      document.getElementById('confirm-yes').onclick = () => { _confirmCancel(); cb(); };
      document.getElementById('confirm-overlay').classList.add('active');
    }
    function _confirmCancel() {
      document.getElementById('confirm-overlay').classList.remove('active');
      _confirmCallback = null;
    }

    /* ── Player list & peer answers ── */
    /* (_isHost, _playerListOpen, _peerAnswersOpen, _playerColors, _lastPlayerList,
       _colorpickTarget, _colorpickBgValue, _colorpickTextValue, _colorpickActiveField declared at top) */

    /* ── Fetch current colors on page load ── */
    (function _loadPlayerColors() {
      fetch('/player_colors').then(r => r.json()).then(c => {
        _playerColors = c || {};
        _updateLabelSwatch();
        _refreshPlayerList(_lastPlayerList);
      }).catch(() => {});
    })();

    function _playerBgColor(name) {
      const c = _playerColors[name];
      return (c && c.bg) ? c.bg : '';
    }

    function _updateLabelSwatch() {
      const sw = document.getElementById('player-label-swatch');
      if (!sw) return;
      const c    = _playerColors[playerName];
      const bg   = (c && c.bg)   ? c.bg   : '';
      const text = (c && c.text) ? c.text : '';
      if (bg || text) {
        sw.style.background  = text || bg;
        sw.style.borderColor = bg   || text;
        sw.classList.remove('pl-swatch-empty');
      } else {
        sw.style.background  = '';
        sw.style.borderColor = '';
        sw.classList.add('pl-swatch-empty');
      }
    }

    /* ── Color picker modal ── */
    function _colorpickUpdateP1Swatches() {
      const bgSw    = document.getElementById('cp-p1-bg-sw');
      const textSw  = document.getElementById('cp-p1-text-sw');
      const bgVal   = document.getElementById('cp-p1-bg-val');
      const textVal = document.getElementById('cp-p1-text-val');
      if (bgSw) {
        if (_colorpickBgValue) { bgSw.style.background = _colorpickBgValue; bgSw.classList.remove('cp-no-color'); }
        else { bgSw.style.background = ''; bgSw.classList.add('cp-no-color'); }
      }
      if (bgVal) bgVal.textContent = _colorpickBgValue || '';
      if (textSw) {
        if (_colorpickTextValue) { textSw.style.background = _colorpickTextValue; textSw.classList.remove('cp-no-color'); }
        else { textSw.style.background = ''; textSw.classList.add('cp-no-color'); }
      }
      if (textVal) textVal.textContent = _colorpickTextValue || '';
    }
    function _colorpickOpenField(which) {
      _colorpickActiveField = which;
      document.getElementById('cp-p2-label').textContent = which === 'bg' ? 'Background' : 'Text';
      const cur = which === 'bg' ? _colorpickBgValue : _colorpickTextValue;
      const hex = (cur && cur.startsWith('#')) ? cur : (which === 'bg' ? '#ff6600' : '#ffffff');
      document.getElementById('colorpick-colorinput').value = hex;
      document.getElementById('colorpick-hexinput').value = cur ? hex : '';
      document.getElementById('colorpick-p1').style.display = 'none';
      document.getElementById('colorpick-p2').style.display = '';
      document.getElementById('cp-custom-body').style.display = 'none';
      document.getElementById('cp-custom-toggle').textContent = 'Custom \u25be';
    }
    function _colorpickBack() {
      document.getElementById('colorpick-p1').style.display = '';
      document.getElementById('colorpick-p2').style.display = 'none';
      _colorpickActiveField = null;
    }
    function _colorpickPickPreset(color) {
      if (_colorpickActiveField === 'bg')   _colorpickBgValue   = color;
      if (_colorpickActiveField === 'text') _colorpickTextValue = color;
      _colorpickUpdateP1Swatches();
      _colorpickBack();
    }
    function _colorpickClearField() {
      if (_colorpickActiveField === 'bg')   _colorpickBgValue   = '';
      if (_colorpickActiveField === 'text') _colorpickTextValue = '';
      _colorpickUpdateP1Swatches();
      _colorpickBack();
    }
    function _colorpickToggleCustom() {
      const body = document.getElementById('cp-custom-body');
      const btn  = document.getElementById('cp-custom-toggle');
      const open = body.style.display !== 'none';
      body.style.display = open ? 'none' : '';
      btn.textContent = open ? 'Custom \u25be' : 'Custom \u25b4';
    }
    function _colorpickColorInputChange() {
      const color = document.getElementById('colorpick-colorinput').value;
      document.getElementById('colorpick-hexinput').value = color;
      if (_colorpickActiveField === 'bg')   _colorpickBgValue   = color;
      if (_colorpickActiveField === 'text') _colorpickTextValue = color;
      _colorpickUpdateP1Swatches();
    }
    function _colorpickHexInputChange() {
      const hi = document.getElementById('colorpick-hexinput');
      const v = hi.value.trim();
      const hex = v.startsWith('#') ? v : '#' + v;
      if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
        document.getElementById('colorpick-colorinput').value = hex;
        if (_colorpickActiveField === 'bg')   _colorpickBgValue   = hex;
        if (_colorpickActiveField === 'text') _colorpickTextValue = hex;
        _colorpickUpdateP1Swatches();
      }
    }
    function _openColorPicker(name) {
      if (!name) return;
      _colorpickTarget = name;
      _colorpickActiveField = null;
      const c = _playerColors[name] || {};
      _colorpickBgValue   = c.bg   || '';
      _colorpickTextValue = c.text || '';
      _colorpickUpdateP1Swatches();
      document.getElementById('colorpick-p1').style.display = '';
      document.getElementById('colorpick-p2').style.display = 'none';
      document.getElementById('colorpick-title').textContent = 'Color \u2014 ' + name;
      document.getElementById('colorpick-overlay').classList.add('active');
    }
    function _colorpickClose() {
      document.getElementById('colorpick-overlay').classList.remove('active');
      _colorpickTarget = null;
      _colorpickActiveField = null;
    }
    function _colorpickSave() {
      if (!_colorpickTarget) return;
      const bg   = _colorpickBgValue;
      const text = _colorpickTextValue;
      socket.emit('set_player_color', { name: _colorpickTarget, bg, text });
      _playerColors[_colorpickTarget] = { bg, text };
      if (_colorpickTarget === playerName) _updateLabelSwatch();
      _refreshPlayerList(_lastPlayerList);
      _colorpickClose();
    }
    document.getElementById('colorpick-overlay').addEventListener('click', e => {
      if (e.target === document.getElementById('colorpick-overlay')) _colorpickClose();
    });
    function _togglePlayerList() {
      _playerListOpen = !_playerListOpen;
      document.getElementById('player-list-panel').style.display = _playerListOpen ? 'block' : 'none';
    }
    function _refreshPlayerList(players) {
      _lastPlayerList = players;
      const items = document.getElementById('player-list-items');
      const countEl = document.getElementById('player-count');
      if (!items || !countEl) return;
      const visible = _isHost ? players : players.filter(p => !p.kicked);
      countEl.textContent = visible.length;
      items.innerHTML = '';
      visible.forEach(p => {
        const div = document.createElement('div');
        div.className = 'pl-item' + (p.kicked ? ' pl-kicked' : '');
        const icon = document.createElement('span');
        icon.className = p.submitted ? 'pl-check' : 'pl-dot';
        icon.textContent = p.submitted ? '\u2713' : '\u25cf';
        div.appendChild(icon);
        if (p.host) {
          const crown = document.createElement('span');
          crown.className = 'pl-crown';
          crown.textContent = '\uD83D\uDC51';
          crown.title = 'Host';
          div.appendChild(crown);
        }
        const name = document.createElement('span');
        name.textContent = p.name;
        // Color swatch — clickable for own entry or host, read-only for others
        const sw = document.createElement('span');
        const bg   = _playerColors[p.name] && _playerColors[p.name].bg   ? _playerColors[p.name].bg   : '';
        const text = _playerColors[p.name] && _playerColors[p.name].text ? _playerColors[p.name].text : '';
        const canEditColor = (p.name === playerName || _isHost);
        sw.className = 'pl-swatch' + (bg || text ? '' : ' pl-swatch-empty');
        if (bg || text) {
          sw.style.background   = text || bg;
          sw.style.borderColor  = bg   || text;
        }
        if (canEditColor) {
          sw.title = 'Set color';
          sw.style.cursor = 'pointer';
          sw.onclick = (e) => { e.stopPropagation(); _openColorPicker(p.name); };
        } else {
          sw.title = (bg ? bg : 'No color set');
          sw.style.cursor = 'default';
        }
        div.appendChild(name);
        div.appendChild(sw);
        if (_isHost) {
          const btn = document.createElement('button');
          btn.style.marginLeft = 'auto';
          if (p.kicked) {
            btn.className = 'pl-remove pl-unban';
            btn.title = 'Unban player';
            btn.textContent = '\u21a9';
            btn.onclick = () => socket.emit('unban_player', { name: p.name });
            div.appendChild(btn);
          } else if (!p.host && p.name !== playerName) {
            btn.className = 'pl-remove';
            btn.title = 'Manage player';
            btn.textContent = '\u2630';
            btn.onclick = () => _kickOptions(p);
            div.appendChild(btn);
          }
        }
        items.appendChild(div);
      });
    }
    function _fmtHostMsgTime(ts) {
      const d = new Date(Number(ts) || Date.now());
      return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }
    function _placeHostMessages() {
      const wrap = document.getElementById('host-messages-wrap');
      if (!wrap) return;
      const qAnchor = document.getElementById('host-messages-anchor-question');
      const sAnchor = document.getElementById('host-messages-anchor-score');
      const target = (_isHost && _scViewOpen) ? sAnchor : qAnchor;
      if (target && wrap.parentElement !== target) target.appendChild(wrap);
    }
    function _renderHostMessages(messages) {
      _hostMessages = Array.isArray(messages) ? messages : [];
      _placeHostMessages();
      const rows = [..._hostMessages].reverse().map(m => {
        const name = _escHtml((m && m.name) ? m.name : 'Player');
        const text = _escHtml((m && m.text) ? m.text : '');
        const ts = _fmtHostMsgTime(m && m.ts);
        return '<div class="hm-item"><span class="hm-name">' + name + '</span><span class="hm-ts">' + ts + '</span><div>' + text + '</div></div>';
      });
      const wrap = document.getElementById('host-messages-wrap');
      const list = document.getElementById('host-messages-list');
      const cnt = document.getElementById('host-messages-count');
      if (!wrap || !list || !cnt) return;
      if (!_isHost) {
        wrap.style.display = 'none';
        return;
      }
      wrap.style.display = 'block';
      cnt.textContent = String(_hostMessages.length);
      list.innerHTML = rows.join('') || '<div class="hm-item" style="color:#667">No messages yet.</div>';
    }
    function _playHostMsgChime() {
      try {
        const ctx = _getAudioCtx();
        if (!ctx) return;
        ctx.resume().then(() => {
          const t = ctx.currentTime;
          // Two-tone ascending chime
          [[660, 0, 0.12], [880, 0.13, 0.22]].forEach(([freq, start, dur]) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(freq, t + start);
            gain.gain.setValueAtTime(0, t + start);
            gain.gain.linearRampToValueAtTime(Math.max(0.0001, _chimeVolume), t + start + 0.03);
            gain.gain.exponentialRampToValueAtTime(0.0001, t + start + dur);
            osc.connect(gain); gain.connect(ctx.destination);
            osc.start(t + start); osc.stop(t + start + dur);
          });
        });
      } catch (e) {}
      try { navigator.vibrate && navigator.vibrate([60, 40, 80]); } catch (e) {}
    }
    function _showHostMessageToast(entry) {
      if (!_isHost) return;
      if (!_hostMsgPopupsEnabled) {
        _playHostMsgChime();
        return;
      }
      const toast = document.getElementById('host-msg-toast');
      if (!toast) return;
      const name = _escHtml((entry && entry.name) ? entry.name : 'Player');
      const text = _escHtml((entry && entry.text) ? entry.text : '');
      toast.innerHTML = '<div class="from">' + name + '</div><div class="body">' + text + '</div>';
      toast.classList.remove('active');
      void toast.offsetWidth; // force reflow so animation restarts
      toast.classList.add('active');
      _playHostMsgChime();
      if (_hostMsgToastTimer) clearTimeout(_hostMsgToastTimer);
      _hostMsgToastTimer = setTimeout(() => {
        toast.classList.remove('active');
        _hostMsgToastTimer = null;
      }, 6000);
    }

    function _showToast(msg, ms = 3000) {
      try {
        const t = document.getElementById('gta-toast');
        if (!t) return;
        t.textContent = String(msg || '');
        t.classList.add('active');
        setTimeout(() => { try { t.classList.remove('active'); } catch (e) {} }, ms);
      } catch (e) {}
    }
    function _sendHostMessage() {
      if (!playerName || _isHost) return;
      const inp = document.getElementById('host-msg-input');
      if (!inp) return;
      const text = (inp.value || '').trim();
      if (!text) return;
      socket.emit('host_message_send', { text });
      inp.value = '';
    }
    function _clearHostMessages() {
      if (!_isHost) return;
      socket.emit('host_messages_clear', {});
    }
    function _togglePeerAnswers() {
      _peerAnswersOpen = !_peerAnswersOpen;
      document.getElementById('peer-answers-list').style.display = _peerAnswersOpen ? 'block' : 'none';
    }
    function _refreshPeerAnswers(answers) {
      const wrap = document.getElementById('peer-answers-wrap');
      const list = document.getElementById('peer-answers-list');
      const toggle = document.getElementById('peer-answers-toggle');
      if (!wrap || !list || !toggle) return;
      toggle.textContent = '\uD83D\uDC41 Submitted Answers (' + answers.length + ')';
      list.innerHTML = '';
      answers.forEach(a => {
        const div = document.createElement('div');
        div.className = 'pa-item';
        div.innerHTML = '<span class="pa-name">' + _escHtml(a.name) + '</span>: ' + _escHtml(a.answer);
        list.appendChild(div);
      });
      if (answers.length > 0) {
        wrap.style.display = 'block';
        if (!_peerAnswersOpen) {
          _peerAnswersOpen = true;
          list.style.display = 'block';
        }
      }
    }

    /* ── Submit ── */
    // Debounced silent selection tracker — fires select_answer without locking UI
    let _selectDebounceTimer = null;
    function _emitSelect(answer, explicit = false) {
      if (_myLastAnswer !== null) return;  // already submitted this question
      if (!playerName) return;
      if (!explicit) return;
      if (answer === null || answer === undefined || answer === '') return;
      clearTimeout(_selectDebounceTimer);
      _selectDebounceTimer = setTimeout(() => {
        socket.emit('select_answer', { name: playerName, answer: String(answer), explicit: true });
      }, 300);
    }

    function submitAnswer() {
      let answer = null;

      if (drumHandle) {
        answer = String(drumHandle.getValue());
        if (_takenYears.has(answer) && answer !== _myLastAnswer) {
          const errDiv = document.getElementById('free-error');
          errDiv.textContent = String(answer) + ' is already taken. Pick another year.';
          errDiv.style.display = 'block';
          return;
        }
        if (_takenScores.has(answer) && answer !== _myLastAnswer) {
          const errDiv = document.getElementById('free-error');
          errDiv.textContent = String(answer) + ' is already taken. Pick another score.';
          errDiv.style.display = 'block';
          return;
        }
      } else if (stepperHandle) answer = String(stepperHandle.getValue());
      else if (rankSliderHandle) {
        answer = String(rankSliderHandle.getValue());
        if (_takenRanks.has(answer) && answer !== _myLastAnswer) {
          const errDiv = document.getElementById('free-error');
          errDiv.textContent = 'Rank #' + parseInt(answer).toLocaleString() + ' is already taken. Pick another rank.';
          errDiv.style.display = 'block';
          return;
        }
      }
      else if (tagHandle) {
        const v = tagHandle.getValue();
        if (!v) return;   // nothing selected
        answer = v;
      } else if (selectedChoice !== null) {
        answer = selectedChoice;
      } else if (_acWrap().style.display !== 'none') {
        answer = _getAnimeAcValue();
        if (!answer) return;
      } else {
        const raw = document.getElementById('free-input').value.trim();
        if (!raw) return;
        const fi = document.getElementById('free-input');
        const errDiv = document.getElementById('free-error');
        // If constrained numeric input, clamp+validate before sending
        if (fi.type === 'number') {
          const num = parseFloat(raw);
          if (isNaN(num)) {
            errDiv.textContent = 'Please enter a number.';
            errDiv.style.display = 'block'; return;
          }
          const mn = parseFloat(fi.min), mx = parseFloat(fi.max);
          const st = parseFloat(fi.step) || 1;
          if (num < mn || num > mx) {
            errDiv.textContent = 'Must be between ' + mn + ' and ' + mx + '.';
            errDiv.style.display = 'block'; return;
          }
          // Round to nearest step so e.g. 7.77 becomes 7.8 for score
          const decimals = (String(st).split('.')[1] || '').length;
          answer = parseFloat((Math.round(num / st) * st).toFixed(decimals)).toString();
        } else {
          if (!raw) return;
          answer = raw;
        }
        errDiv.style.display = 'none';
        // Taken-year check for text mode
        if (_takenYears.size && _takenYears.has(answer) && answer !== _myLastAnswer) {
          errDiv.textContent = answer + ' is already taken. Pick another year.';
          errDiv.style.display = 'block'; return;
        }
      }

      socket.emit('submit_answer', { name: playerName, answer: answer });
       _myLastAnswer = answer;
      if (drumHandle && drumHandle.setMyYear)   drumHandle.setMyYear(parseInt(answer, 10));
      if (drumHandle && drumHandle.setMyScore)  drumHandle.setMyScore(parseFloat(answer));

      if (tagHandle) {
        /* Tags now single-submit like all other types */
        if (_currentQid) {
          localStorage.setItem('gta_answered_' + _currentQid, '1');
          localStorage.setItem('gta_answer_'   + _currentQid, answer);
        }
        _lockSubmittedUI(answer.replace(/,/g, ', '));
        selectedChoice = null;
      } else {
        if (_currentQid) {
          localStorage.setItem('gta_answered_' + _currentQid, '1');
          localStorage.setItem('gta_answer_'   + _currentQid, answer);
        }
        _lockSubmittedUI(answer);
        selectedChoice = null;
      }
    }

    document.getElementById('free-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') submitAnswer();
    });

    socket.on('auto_submitted', data => {
      // Server flushed our silent selection as a real submission
      const answer = String(data.answer || '');
      if (_myLastAnswer !== null) return;  // already formally submitted
      _myLastAnswer = answer;
      if (_currentQid) {
        localStorage.setItem('gta_answered_' + _currentQid, '1');
        localStorage.setItem('gta_answer_'   + _currentQid, answer);
      }
      _lockSubmittedUI(answer.includes(',') ? answer.replace(/,/g, ', ') : answer);
      selectedChoice = null;
    });

    /* ── Metadata panel (host only) ── */
    let _metadataOpen = false;
    let _metadataTab = 'info';
    const _metaHistory = [];  // oldest → newest
    let _metaHistoryIdx = 0;  // 0 = newest
    let _metaAutoFollow = true;
    let _currentMetadata = null;
    let _metaCoverUrl = '';
    let _themeActionTarget = null;
    let _themeActionSeq = 1;
    let _themeActionMap = {};
    let _sidePanelInitDone = false;

    function _saveSidePanels() {
      const state = { meta: _metadataOpen, ctrl: _controllerOpen };
      document.cookie = 'sidePanels=' + encodeURIComponent(JSON.stringify(state)) + '; path=/; max-age=31536000';
    }

    // Called once when access is first granted. Auto-opens panels on widescreen
    // unless the user had previously explicitly closed them (saved in cookie).
    function _autoOpenSidePanels(isHost) {
      if (_sidePanelInitDone || window.innerWidth < 900) return;
      _sidePanelInitDone = true;
      const match = document.cookie.match(/(?:^|;\s*)sidePanels=([^;]*)/);
      let saved = null;
      if (match) { try { saved = JSON.parse(decodeURIComponent(match[1])); } catch(e) {} }
      // Default open on widescreen; respect saved preference if it exists
      if (!_metadataOpen && (saved ? saved.meta !== false : true)) _toggleMetadata();
      if (isHost && !_controllerOpen && (saved ? saved.ctrl !== false : true)) _toggleController();
    }

    socket.on('info_public_update', data => {
      if (data.show) {
        if (data.metadata) {
          _currentMetadata = data.metadata;
          _metaHistoryPush(_currentMetadata);
        }
        document.getElementById('metadata-wrap').style.display = 'block';
        _autoOpenSidePanels(false);
        // Re-render if panel is already open
        if (_metadataOpen) {
          _renderMetadata(_currentMetadata);
          _renderSeriesThemes(_currentMetadata);
        }
      } else if (!_isHost) {
        // Keep panel open but show empty state
        _currentMetadata = null;
        if (_metadataOpen) {
          _renderMetadata(null);
          _renderSeriesThemes(null);
        }
      }
    });

    /* ── Playback controller ── */
    let _controllerOpen  = false;
    // Default sub-panels open for fresh browsers (saved prefs still override)
    let _ctrlControlsVisible = true;
    let _ctrlInfoTextVisible = true;
    const _ctrlInfoHistory = [];   // oldest → newest
    let _ctrlInfoHistoryIdx = 0;   // 0 = newest end
    let _ctrlUpNextVisible = true;
    let _ctrlPlaylistVisible = true;
    let _ctrlYtListOpen = false;
    let _ctrlYtCurrentId = null;
    let _ctrlLtListOpen = false;
    let _ctrlLtCurrentMode = null;
    let _ctrlFlListOpen = false;
    let _ctrlFlCurrentName = null;
    let _ctrlSearchListOpen = false;
    let _ctrlSearchQueuedFile = null;
    let _ctrlSearchResultsAll = [];
    let _ctrlSearchRenderCount = 0;
    let _ctrlSearchIsInfinite = false;
    let _ctrlSearchQuery = '';
    const _CTRL_SEARCH_PAGE_SIZE = 50;
    let _ctrlDiffListOpen = false;
    let _ctrlDiffCurrent = 2;
    let _ctrlAutoBonusListOpen = false;
    let _ctrlAutoBonusCurrent = null;
    let _ctrlListPopupMode = null;
    let _ctrlListPopupDownInsideBox = false;

    function _ctrlListPopupOverlayMouseDown(ev) {
      const box = document.getElementById('ctrl-list-popup-box');
      _ctrlListPopupDownInsideBox = !!(box && ev && box.contains(ev.target));
    }

    function _ctrlListPopupOverlayClick(ev) {
      const isOverlay = !!(ev && ev.target && ev.currentTarget && ev.target === ev.currentTarget);
      if (!isOverlay) return;
      // If drag started inside popup (e.g. text selection) and ended outside, do not close.
      if (_ctrlListPopupDownInsideBox) {
        _ctrlListPopupDownInsideBox = false;
        return;
      }
      _ctrlListPopupClose();
    }

    function _ctrlListPopupOpen(title, mode) {
      _ctrlListPopupMode = mode;
      const overlay = document.getElementById('ctrl-list-popup-overlay');
      const titleEl = document.getElementById('ctrl-list-popup-title');
      const searchRow = document.getElementById('ctrl-list-popup-search-row');
      const box = document.getElementById('ctrl-list-popup-box');
      const list = document.getElementById('ctrl-list-popup-list');
      if (titleEl) titleEl.textContent = title;
      if (searchRow) searchRow.classList.toggle('active', mode === 'search');
      if (box) box.classList.toggle('search-mode', mode === 'search');
      if (list) list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Loading…</div>';
      if (overlay) overlay.classList.add('active');
    }

    function _ctrlListPopupClose() {
      _ctrlListPopupMode = null;
      _ctrlListPopupDownInsideBox = false;
      _ctrlLtListOpen = false;
      _ctrlYtListOpen = false;
      _ctrlFlListOpen = false;
      _ctrlSearchListOpen = false;
      _ctrlDiffListOpen = false;
      _ctrlAutoBonusListOpen = false;
      _ctrlDirListOpen = false;
      _ctrlBuzzSoundListOpen = false;
      const overlay = document.getElementById('ctrl-list-popup-overlay');
      const box = document.getElementById('ctrl-list-popup-box');
      if (overlay) overlay.classList.remove('active');
      if (box) box.classList.remove('search-mode');
    }
    let _ctrlVolOpen     = false;
    let _ctrlSeeking     = false;
    let _ctrlCurrentMs   = 0;
    let _ctrlLengthMs    = 0;
    let _ctrlPlaying     = false;
    let _ctrlAutoplayMode = 0;

    const _AUTOPLAY_ICONS  = ['\u{1F501}', '\u{1F502}', '\u{1F501}', '\u274C'];
    const _AUTOPLAY_TITLES = [
      'Autoplay: advance to next track',
      'Single repeat: replay current track',
      'Disabled: stop after current track',
      'Manual: video loads but does not play'
    ];

    function _ctrlSetAutoplayMode(mode) {
      _ctrlAutoplayMode = mode;
      const btn = document.getElementById('ctrl-autoplay-btn');
      if (!btn) return;
      btn.textContent = _AUTOPLAY_ICONS[mode];
      btn.title = _AUTOPLAY_TITLES[mode];
      btn.className = 'ctrl-btn ctrl-btn-autoplay mode-' + mode;
    }

    function _ctrlCycleAutoplay() {
      const next = (_ctrlAutoplayMode + 1) % 4;
      _ctrlSetAutoplayMode(next);
      socket.emit('host_action', { action: 'set_autoplay', mode: next });
    }

    function _fmtMs(ms) {
      if (!ms || ms <= 0) return '0:00';
      const s = Math.floor(ms / 1000);
      return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }

    function _ctrlRenderInfo(d) {
      // If d is null, use history navigation; otherwise snap to latest
      if (d !== null) {
        _ctrlInfoHistoryIdx = 0;
        // Seed history from any real data source (metadata_update, info_public_update, etc.)
        if (d.title) {
          const last = _ctrlInfoHistory[_ctrlInfoHistory.length - 1];
          const newSlug = d.current_theme && d.current_theme.slug;
          const lastSlug = last && last.current_theme && last.current_theme.slug;
          if (!last || last.title !== d.title || (newSlug && newSlug !== lastSlug)) {
            _ctrlInfoHistory.push(d);
            if (_ctrlInfoHistory.length > 20) _ctrlInfoHistory.shift();
          }
        }
      }
      const total = _ctrlInfoHistory.length;
      const viewData = total > 0 ? _ctrlInfoHistory[total - 1 - _ctrlInfoHistoryIdx] : d;
      d = viewData;
      const top  = document.getElementById('ctrl-info-top');
      const main = document.getElementById('ctrl-info-main');
      const bot  = document.getElementById('ctrl-info-bottom');
      if (!d || !d.title) {
        if (top)  top.textContent  = '';
        if (main) main.textContent = 'No media loaded';
        if (bot)  bot.innerHTML    = '';
        return;
      }
      // Main: English title (large)
      const title = d.eng_title || d.title || '';
      const jpTitle = d.title || '';
      if (main) main.textContent = title;
      // Top row: slug + song + season
      const ct = d.current_theme || {};
      const slugFmt = ct.slug ? ct.slug.replace(/([A-Z]+)(\d+)/, '$1 $2') : '';
      const vStr    = ct.version && ct.version !== 1 ? ' v' + ct.version : '';
      const suffix  = ct.overall_suffix || '';
      const songParts = [];
      if (ct.title) songParts.push(ct.title);
      if (ct.artists && ct.artists.length) songParts.push(ct.artists_str || ct.artists.join(', '));
      const songStr = songParts.join(' / ');
      const aired   = d.season || d.release || '';
      const topParts = [slugFmt + vStr + suffix, songStr, aired].filter(Boolean);
      if (top) top.textContent = topParts.join('  \u2022  ');
      // Bottom: multi-line like desktop popup
      const B = '  \u2022  ';
      const lines = [];
      // Line 1: MAL score | JP title | members
      const l1 = [];
      if (d.score) l1.push('MAL ' + d.score + (d.rank ? ' (#' + d.rank + ')' : ''));
      if (jpTitle && jpTitle !== title) l1.push(jpTitle);
      if (d.members) l1.push(Number(d.members).toLocaleString() + ' members' + (d.popularity ? ' (#' + d.popularity + ')' : ''));
      if (l1.length) lines.push(l1.join(B));
      // Line 2: studio | tags | episodes | format | source
      const l3 = [];
      const studios = (d.studios || []).join(', ');
      if (studios) l3.push(studios);
      const tagArr = Array.isArray(d.tags) ? d.tags : (d.tags || '').split(',').map(t => t.trim()).filter(Boolean);
      if (tagArr.length) l3.push(tagArr.slice(0, 5).join(', '));
      if (d.episodes) l3.push(d.episodes + ' ep.');
      if (d.format)   l3.push(d.format);
      if (d.source)   l3.push(d.source);
      if (l3.length) lines.push(l3.join(B));
      if (bot) bot.innerHTML = lines.map(l => `<span>${l}</span>`).join('<br>');
    }

    socket.on('playback_state', data => {
      _ctrlCurrentMs = data.current_ms || 0;
      _ctrlLengthMs  = data.length_ms  || 0;
      _ctrlPlaying   = !!data.playing;
      if (!_ctrlSeeking) {
        const seek = document.getElementById('ctrl-seek');
        if (seek) {
          seek.value = _ctrlLengthMs > 0
            ? Math.round((_ctrlCurrentMs / _ctrlLengthMs) * 1000)
            : 0;
        }
      }
      const cur = document.getElementById('ctrl-time-cur');
      const tot = document.getElementById('ctrl-time-total');
      const pp  = document.getElementById('ctrl-playpause');
      if (cur) cur.textContent = _fmtMs(_ctrlCurrentMs);
      if (tot) tot.textContent = _fmtMs(_ctrlLengthMs);
      if (pp)  pp.textContent  = _ctrlPlaying ? '\u23F8\uFE0F' : '\u25B6\uFE0F';
      if (data.volume !== undefined) {
        const vs = document.getElementById('ctrl-vol-slider');
        const vl = document.getElementById('ctrl-vol-label');
        if (vs) vs.value = data.volume;
        if (vl) vl.textContent = data.volume;
      }
      if (data.bgm_modifier !== undefined) {
        _ctrlBgmPct = Math.round(data.bgm_modifier * 100);
        _ctrlBgmRender();
      }
      if (data.bzz_modifier !== undefined) {
        _ctrlBzzPct = Math.round(data.bzz_modifier * 100);
        _ctrlBzzRender();
      }
      if (data.autoplay !== undefined) _ctrlSetAutoplayMode(data.autoplay);
      _ctrlRenderInfo(_currentMetadata);
    });

    socket.on('metadata_update', data => {
      _currentMetadata = data;
      _metaHistoryPush(data);
      _ctrlInfoHistoryIdx = 0; // snap back to latest
      _ctrlRenderInfo(data); // history seeding handled inside _ctrlRenderInfo
      if (_metadataOpen) {
        _renderMetadata(data);
        if (_metaAutoFollow) {
          _renderSeriesThemes(data);
          if (_metadataTab === 'more') _renderMore(data);
        }
        if (_ctrlPlaylistVisible) {
          _plCache.clear();
          _plPending.clear();
          socket.emit('host_action', { action: 'get_playlist_info' });
        }
      }
    });

    function _toggleController() {
      _controllerOpen = !_controllerOpen;
      document.getElementById('controller-overlay').classList.toggle('active', _controllerOpen);
      document.body.classList.toggle('ctrl-open', _controllerOpen);
      if (_controllerOpen) {
        _ctrlRenderInfo(_currentMetadata);
        if (_ctrlLengthMs === 0)
          socket.emit('host_action', { action: 'request_state' });
      } else {
        // Close any open sub-panels when dismissing controller
        if (_ctrlVolOpen) _ctrlToggleVolume();
      }
      _saveSidePanels();
    }

    function _ctrlSavePanels() {
      const state = {
        controls:      _ctrlControlsVisible,
        infotext:      _ctrlInfoTextVisible,
        upnext:        _ctrlUpNextVisible,
        playlist:      _ctrlPlaylistVisible,
        pinnedExtras:  [..._ctrlPinnedExtras],
      };
      try { localStorage.setItem('ctrlPanels', JSON.stringify(state)); } catch(e) {}
    }

    function _ctrlApplyPanelVisibility() {
      const controlsPanel = document.getElementById('ctrl-controls-panel');
      if (controlsPanel) controlsPanel.style.display = _ctrlControlsVisible ? 'flex' : 'none';

      const infoPanel = document.getElementById('ctrl-infotext-panel');
      if (infoPanel) infoPanel.style.display = _ctrlInfoTextVisible ? 'block' : 'none';

      const upNextPanel = document.getElementById('ctrl-upnext-panel');
      if (upNextPanel) upNextPanel.style.display = _ctrlUpNextVisible ? 'block' : 'none';

      const playlistPanel = document.getElementById('ctrl-playlist-panel');
      if (playlistPanel) playlistPanel.style.display = _ctrlPlaylistVisible ? 'flex' : 'none';

      const spacer = document.getElementById('ctrl-flex-spacer');
      if (spacer) spacer.classList.toggle('hidden', _ctrlPlaylistVisible);

      if (_ctrlPlaylistVisible) _plOpen();
      _ctrlSyncSectionArrows();
    }

    function _ctrlLoadPanels() {
      let state;
      try { state = JSON.parse(localStorage.getItem('ctrlPanels') || ''); } catch(e) { state = null; }
      if (!state || typeof state !== 'object') {
        _ctrlApplyPanelVisibility();
      } else {
        if (typeof state.controls === 'boolean') _ctrlControlsVisible = state.controls;
        if (typeof state.infotext === 'boolean') _ctrlInfoTextVisible = state.infotext;
        if (typeof state.upnext === 'boolean') _ctrlUpNextVisible = state.upnext;
        if (typeof state.playlist === 'boolean') _ctrlPlaylistVisible = state.playlist;
        _ctrlApplyPanelVisibility();
      }
      if (state && Array.isArray(state.pinnedExtras)) {
        const cleaned = [];
        const seen = new Set();
        state.pinnedExtras.forEach(raw => {
          if (typeof raw !== 'string') return;
          let id = raw;
          // Migration: Buzz Open was removed; map to Buzz Lock.
          if (id === 'buzz_open') id = 'buzz_lock';
          const isLayout = id.startsWith('_br_') || id.startsWith('_sp_');
          const isKnown = !!_ctrlExtrasConfig[id];
          if (!isLayout && !isKnown) return;
          if (seen.has(id)) return;
          seen.add(id);
          cleaned.push(id);
        });
        _ctrlPinnedExtras = new Set(cleaned);
        _ctrlRenderPinnedExtras();
        // Persist migrated/cleaned preferences immediately.
        _ctrlSavePanels();
      }
      _ctrlSyncSectionArrows();
    }

    function _ctrlSetSectionArrow(toggleId, chevronId, isOpen) {
      const toggle = document.getElementById(toggleId);
      if (toggle) {
        toggle.classList.toggle('is-open', !!isOpen);
        toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        const section = toggle.closest('.ctrl-section');
        if (section) section.classList.toggle('section-open', !!isOpen);
      }
      const chev = document.getElementById(chevronId);
      if (chev) chev.textContent = isOpen ? '\u25BE' : '\u25B8';
    }

    function _ctrlSyncSectionArrows() {
      _ctrlSetSectionArrow('ctrl-controls-toggle', 'ctrl-controls-chevron', _ctrlControlsVisible);
      _ctrlSetSectionArrow('ctrl-infotext-toggle', 'ctrl-infotext-chevron', _ctrlInfoTextVisible);
      _ctrlSetSectionArrow('ctrl-upnext-toggle', 'ctrl-upnext-chevron', _ctrlUpNextVisible);
      _ctrlSetSectionArrow('ctrl-playlist-toggle', 'ctrl-playlist-chevron', _ctrlPlaylistVisible);
    }

    function _ctrlToggleControls() {
      _ctrlControlsVisible = !_ctrlControlsVisible;
      const panel = document.getElementById('ctrl-controls-panel');
      if (panel) panel.style.display = _ctrlControlsVisible ? 'flex' : 'none';
      _ctrlSyncSectionArrows();
      _ctrlSavePanels();
    }
    function _ctrlToggleInfoText() {
      _ctrlInfoTextVisible = !_ctrlInfoTextVisible;
      const panel = document.getElementById('ctrl-infotext-panel');
      if (panel) panel.style.display = _ctrlInfoTextVisible ? 'block' : 'none';
      _ctrlSyncSectionArrows();
      _ctrlSavePanels();
    }

    // ── Scoreboard view ──────────────────────────────────────────────
    let _scViewOpen    = false;
    let _scDeltaBtns   = [];   // [{label, delta}, ...]
    let _scPlayers     = [];   // [{name, score, team}, ...]
    let _scLastData    = null; // most recent scores_update payload
    let _scOptimisticUntil = 0;       // timestamp — ignore incoming renders until this time
    let _scOptimisticPlayers = null;  // snapshot of _scPlayers after last optimistic op
    let _scTeamNames   = [];   // cached team name list for autocomplete
    let _scPending     = {};   // name → accumulated uncommitted delta
    let _scTimers      = {};   // name → per-player setTimeout id
    let _scTimerEnds   = {};   // name → deadline timestamp
    let _scGlobalTimer = null; // shared setTimeout id (TOGETHER mode)
    let _scGlobalTimerEnd = null;
    let _scTogether    = false;
    let _scAuto        = false;
    let _scDelay       = 1500; // ms — mirrors delta_commit_delay config
    let _scArchiveBusy = false;
    let _scArchiveRequestedAt = 0;
    let _scArchivePreCount = 0;
    let _scArchiveBusyTimer = null;

    function _scSetArchiveBusy(busy) {
      _scArchiveBusy = !!busy;
      const btn = document.getElementById('sc-archive-btn');
      if (btn) {
        btn.disabled = _scArchiveBusy;
        btn.textContent = _scArchiveBusy ? 'ARCHIVING…' : 'ARCHIVE';
      }
    }

    function _scLoadPrefs(auto_send, delay_together, commit_delay, score_font, name_font) {
      _scAuto     = !!auto_send;
      _scTogether = !!delay_together;
      if (commit_delay !== undefined) _scDelay = Math.max(0, parseInt(commit_delay) || 0);
      if (score_font) document.documentElement.style.setProperty('--sc-score-font', "'" + score_font + "'");
      if (name_font)  document.documentElement.style.setProperty('--sc-name-font',  "'" + name_font  + "'");
      _scApplyToggleUI();
    }
    function _scApplyToggleUI() {
      const tb = document.getElementById('sc-tog-together');
      const ab = document.getElementById('sc-tog-auto');
      if (tb) tb.classList.toggle('sc-toggle-on', _scTogether);
      if (ab) ab.classList.toggle('sc-toggle-on', _scAuto);
    }
    function _scToggleTogether() {
      _scTogether = !_scTogether;
      _scApplyToggleUI();
      socket.emit('host_action', { action: 'sc_set_prefs', auto_send: _scAuto, delay_together: _scTogether });
    }
    function _scToggleAuto() {
      _scAuto = !_scAuto;
      _scApplyToggleUI();
      if (!_scAuto) {
        // Turning auto off: cancel all timers, keep pending for manual SUBMIT
        Object.values(_scTimers).forEach(t => clearTimeout(t));
        _scTimers = {}; _scTimerEnds = {};
        if (_scGlobalTimer) { clearTimeout(_scGlobalTimer); _scGlobalTimer = null; _scGlobalTimerEnd = null; }
        _scUpdateSubmitBtn();
      }
      socket.emit('host_action', { action: 'sc_set_prefs', auto_send: _scAuto, delay_together: _scTogether });
    }

    /** Mirrors scoreboard.py _queue_delta exactly. */
    function _scQueueDelta(name, delta) {
      // Instant + auto + not-together: fire right away, no accumulation
      if (_scDelay === 0 && _scAuto && !_scTogether) {
        socket.emit('host_action', { action: 'score_adjust', name, delta });
        _scOptimisticPromote(name, delta);
        return;
      }

      // If this is a ghost player, promote them to a real row immediately (score 0)
      // so the pending label shows on a proper scoreboard row rather than the ghost strip.
      // _scCommit/_scFlushAll will then just add the committed delta to their existing score.
      if (!_scPlayers.find(p => p.name === name)) {
        _scOptimisticPromote(name, 0);
      }

      // Accumulate
      _scPending[name] = (_scPending[name] || 0) + delta;
      _scUpdateAllPendingLabels();

      if (!_scAuto) {
        // Manual mode: cancel any running timer, wait for SUBMIT
        if (_scTimers[name]) { clearTimeout(_scTimers[name]); delete _scTimers[name]; delete _scTimerEnds[name]; }
        if (_scGlobalTimer)  { clearTimeout(_scGlobalTimer);  _scGlobalTimer = null; _scGlobalTimerEnd = null; }
        _scUpdateSubmitBtn();
        return;
      }

      if (_scTogether) {
        // Shared timer: any press resets it for ALL players
        Object.values(_scTimers).forEach(t => clearTimeout(t));
        _scTimers = {};
        _scTimerEnds = {};
        if (_scGlobalTimer) { clearTimeout(_scGlobalTimer); _scGlobalTimer = null; _scGlobalTimerEnd = null; }
        if (_scDelay === 0) { _scFlushAll(); return; }
        _scGlobalTimerEnd = Date.now() + _scDelay;
        _scGlobalTimer = setTimeout(() => { _scGlobalTimer = null; _scGlobalTimerEnd = null; _scFlushAll(); }, _scDelay);
        _scUpdateSubmitBtn();
      } else {
        // Per-player timer
        if (_scGlobalTimer) { clearTimeout(_scGlobalTimer); _scGlobalTimer = null; }
        if (_scTimers[name]) clearTimeout(_scTimers[name]);
        if (_scDelay === 0) { _scCommit(name); return; }
        _scTimerEnds[name] = Date.now() + _scDelay;
        _scTimers[name] = setTimeout(() => { delete _scTimers[name]; delete _scTimerEnds[name]; _scCommit(name); _scUpdateSubmitBtn(); }, _scDelay);
        _scUpdateSubmitBtn();
      }
    }

    function _scOptimisticPromote(name, delta) {
      const op = _scPlayers.find(p => p.name === name);
      _scOptimisticUntil = Date.now() + 5000;
      if (op) {
        // Existing player: update score and patch span in-place
        op.score = (op.score || 0) + delta;
        if (_scLastData) _scLastData.players = _scPlayers.map(p => Object.assign({}, p));
        _scOptimisticPlayers = _scPlayers.map(p => Object.assign({}, p));
        const container = document.getElementById('sc-players');
        if (container) {
          const row = container.querySelector('.sc-row[data-name="' + CSS.escape(name) + '"]');
          if (row) { const sc = row.querySelector('.sc-score-cell'); if (sc) sc.textContent = _scFmtScore(op.score); }
        }
      } else {
        // Ghost player: build new players list WITHOUT touching _scPlayers yet
        // so _scRender sees a length/name change and does a full DOM rebuild
        const newPlayers = _scPlayers.map(p => Object.assign({}, p));
        newPlayers.push({ name, score: delta });
        _scOptimisticPlayers = newPlayers.map(p => Object.assign({}, p));
        const renderData = Object.assign({}, _scLastData || {}, { players: newPlayers,
          delta_buttons: (_scLastData && _scLastData.delta_buttons) || _scDeltaBtns.map(d => d.label).join(',') });
        _scRender(renderData);
        // _scRender sets _scPlayers = newPlayers internally
      }
    }

    function _scCommit(name) {
      const delta = _scPending[name] || 0;
      delete _scPending[name];
      delete _scTimerEnds[name];
      _scUpdateAllPendingLabels();
      _scUpdateSubmitBtn();
      if (delta !== 0) {
        socket.emit('host_action', { action: 'score_adjust', name, delta });
        _scOptimisticPromote(name, delta);
      }
    }

    function _scFlushAll() {
      const entries = Object.entries(_scPending);
      entries.forEach(([name, delta]) => {
        if (delta !== 0) socket.emit('host_action', { action: 'score_adjust', name, delta });
      });
      _scPending = {};
      Object.values(_scTimers).forEach(t => clearTimeout(t));
      _scTimers = {};
      _scTimerEnds = {};
      if (_scGlobalTimer) { clearTimeout(_scGlobalTimer); _scGlobalTimer = null; _scGlobalTimerEnd = null; }
      _scUpdateAllPendingLabels();
      _scUpdateSubmitBtn();
      // Optimistic: apply all flushed deltas
      if (entries.length > 0) {
        entries.forEach(([name, delta]) => { if (delta !== 0) _scOptimisticPromote(name, delta); });
      }
    }

    // Countdown ticker on SUBMIT button
    let _scCountdownTick = null;
    function _scUpdateSubmitBtn() {
      const sb = document.getElementById('sc-submit-btn');
      if (!sb) return;
      if (_scCountdownTick) { clearInterval(_scCountdownTick); _scCountdownTick = null; }
      // Find the nearest deadline across all active timers
      const now = Date.now();
      let nearest = Infinity;
      if (_scGlobalTimer !== null && _scGlobalTimerEnd) nearest = Math.min(nearest, _scGlobalTimerEnd);
      Object.entries(_scTimerEnds).forEach(([, t]) => { if (t) nearest = Math.min(nearest, t); });
      if (!isFinite(nearest) || nearest <= now) {
        sb.textContent = 'SUBMIT';
        return;
      }
      function _tick() {
        const rem = Math.max(0, Math.ceil((nearest - Date.now()) / 100) / 10);
        sb.textContent = rem > 0 ? 'SUBMIT ' + rem.toFixed(1) + 's' : 'SUBMIT';
        if (rem <= 0 && _scCountdownTick) { clearInterval(_scCountdownTick); _scCountdownTick = null; }
      }
      _tick();
      _scCountdownTick = setInterval(_tick, 100);
    }

    function _toggleScoreboardView() {
      _scViewOpen = !_scViewOpen;
      _scApplyViewState();
      if (_scViewOpen) {
        if (_scLastData) _scRender(_scLastData);
        socket.emit('host_action', { action: 'get_scores' });
        setTimeout(_scFitScroll, 0);
        setTimeout(_scRenderGhosts, 0);
      }
      const val = encodeURIComponent(_scViewOpen ? 'scoreboard' : 'question');
      document.cookie = 'scView=' + val + '; path=/; max-age=31536000';
    }
    function _scApplyViewState() {
      document.getElementById('scoreboard-view').style.display = _scViewOpen ? 'flex' : 'none';
      document.getElementById('question-box').style.display = _scViewOpen ? 'none' : 'block';
      _placeHostAnswers();
      _placeHostMessages();
      const btn = document.getElementById('sc-view-btn');
      if (btn) {
        btn.classList.toggle('sc-view-active', _scViewOpen);
        btn.innerHTML = _scViewOpen ? '&#x2753; Question' : '&#x1F3C6; Scoreboard';
        btn.title = _scViewOpen ? 'Back to question' : 'Scoreboard';
      }
    }

    function _scParseDeltaBtns(str) {
      if (!str) return [];
      return str.split(',').map(s => s.trim()).filter(Boolean).map(s => ({label: s, delta: parseFloat(s)}));
    }
    function _scFmtScore(s) {
      if (s === undefined || s === null) return '0';
      return (s % 1 === 0) ? String(s) : s.toFixed(1);
    }
    function _scUpdateAdjustWidth() {
      const firstDeltas = document.querySelector('.sc-deltas');
      const adjHeader = document.getElementById('sc-ch-adjust');
      if (firstDeltas && adjHeader) adjHeader.style.width = firstDeltas.offsetWidth + 'px';
    }
    function _scFitScroll() {
      const sc = document.getElementById('sc-scroll');
      if (!sc) return;
      const zoom = parseFloat(document.documentElement.style.zoom) || 1;
      const scTop = sc.getBoundingClientRect().top / zoom;
      const vh = window.innerHeight / zoom;
      // Sum the height of siblings that come AFTER sc-scroll (e.g. add-player row)
      let belowH = 0;
      let el = sc.nextElementSibling;
      while (el) { belowH += el.getBoundingClientRect().height / zoom; el = el.nextElementSibling; }
      const maxH = vh - scTop - belowH - 50;
      sc.style.maxHeight = Math.max(80, maxH) + 'px';
    }

    function _scRender(data) {
      if (!data) return;
      const newPlayers   = data.players || [];
      const newDeltaBtns = _scParseDeltaBtns(data.delta_buttons);
      const container    = document.getElementById('sc-players');
      if (!container) return;

      // Check whether only scores changed (same names, same order, same delta buttons)
      const sameDeltaBtns = newDeltaBtns.length === _scDeltaBtns.length &&
        newDeltaBtns.every((d, i) => d.label === _scDeltaBtns[i].label);
      const sameNames = newPlayers.length === _scPlayers.length &&
        newPlayers.every((p, i) => p.name === _scPlayers[i].name);

      if (sameNames && sameDeltaBtns) {
        // In-place score patch — never destroy DOM
        _scPlayers = newPlayers;
        newPlayers.forEach(p => {
          const row = container.querySelector(`.sc-row[data-name="${CSS.escape(p.name)}"]`);
          if (!row) return;
          const scoreInput = row.querySelector('.sc-score-input');
          // Skip rows where the user is actively editing
          if (scoreInput && scoreInput === document.activeElement) return;
          const scoreSpan = row.querySelector('.sc-score-cell');
          if (scoreSpan && scoreInput && scoreInput.style.display === 'none') {
            scoreSpan.textContent = _scFmtScore(p.score);
          }
        });
        return;
      }

      // Full rebuild only when structure changed AND no input is focused inside the scoreboard
      const focused = container.contains(document.activeElement);
      if (focused) return; // defer — don't destroy an open input

      _scPlayers = newPlayers;
      _scDeltaBtns = newDeltaBtns;
      container.innerHTML = '';

      _scPlayers.forEach(p => {
        const row = document.createElement('div');
        row.className = 'sc-row';
        row.dataset.name = p.name;

        if (_isHost) {
          // Delta buttons
          const deltasWrap = document.createElement('div');
          deltasWrap.className = 'sc-deltas';
          _scDeltaBtns.forEach(d => {
            const btn = document.createElement('button');
            btn.className = 'sc-delta-btn ' + (d.delta < 0 ? 'sc-delta-neg' : 'sc-delta-pos');
            btn.textContent = d.label;
            btn.title = d.label;
            btn.onclick = () => _scQueueDelta(p.name, d.delta);
            deltasWrap.appendChild(btn);
          });
          row.appendChild(deltasWrap);
        }

        // Score display / edit
        const scoreSpan = document.createElement('span');
        scoreSpan.className = 'sc-score-cell';
        scoreSpan.textContent = _scFmtScore(p.score);

        if (_isHost) {
          const scoreInput = document.createElement('input');
          scoreInput.className = 'sc-score-input';
          scoreInput.type = 'number';
          scoreInput.style.display = 'none';

          scoreSpan.title = 'Click to set score';
          scoreSpan.onclick = () => {
            // Read current score from _scPlayers, not stale closure
            const cur = (_scPlayers.find(p2 => p2.name === p.name) || p);
            scoreSpan.style.display = 'none';
            scoreInput.style.display = 'block';
            scoreInput.value = cur.score;
            scoreInput.focus(); scoreInput.select();
          };
          function _commitScore() {
            const v = parseFloat(scoreInput.value);
            scoreInput.style.display = 'none';
            scoreSpan.style.display = '';
            if (!isNaN(v)) _scSetScore(p.name, v);
          }
          scoreInput.onkeydown = e => {
            if (e.key === 'Enter') { e.preventDefault(); _commitScore(); }
            if (e.key === 'Escape') { scoreInput.style.display='none'; scoreSpan.style.display=''; }
          };
          scoreInput.onblur = _commitScore;
          row.appendChild(scoreSpan);
          row.appendChild(scoreInput);

          // Pending label
          const pendingLbl = document.createElement('span');
          pendingLbl.className = 'sc-pending-lbl';
          pendingLbl.dataset.name = p.name;
          pendingLbl.style.cssText = 'font-size:0.7em;font-weight:bold;min-width:28px;display:none;';
          row.appendChild(pendingLbl);
        } else {
          row.appendChild(scoreSpan);
        }

        // Name display / edit
        const nameSpan = document.createElement('span');
        nameSpan.className = 'sc-name-cell';
        nameSpan.textContent = p.name;
        nameSpan.title = p.name;

        if (_isHost) {
          const nameInput = document.createElement('input');
          nameInput.className = 'sc-name-input';
          nameInput.style.display = 'none';

          nameSpan.title = 'Click to rename';
          nameSpan.onclick = () => {
            nameSpan.style.display = 'none';
            nameInput.style.display = 'block';
            nameInput.value = p.name;
            nameInput.focus(); nameInput.select();
          };
          function _commitName() {
            const v = nameInput.value.trim();
            if (v && v !== p.name) _scRenameInline(p.name, v);
            nameInput.style.display = 'none';
            nameSpan.style.display = '';
          }
          nameInput.onkeydown = e => {
            if (e.key === 'Enter') { e.preventDefault(); _commitName(); }
            if (e.key === 'Escape') { nameInput.style.display='none'; nameSpan.style.display=''; }
          };
          nameInput.onblur = _commitName;
          row.appendChild(nameSpan);
          row.appendChild(nameInput);

          // Menu button
          const menuBtn = document.createElement('button');
          menuBtn.className = 'sc-menu-btn';
          menuBtn.textContent = '☰';
          menuBtn.title = 'Options';
          menuBtn.onclick = e => { e.stopPropagation(); _scShowRowMenu(p.name, menuBtn); };
          row.appendChild(menuBtn);
        } else {
          row.appendChild(nameSpan);
        }

        container.appendChild(row);
      });

      setTimeout(() => { _scUpdateAdjustWidth(); _scFitScroll(); _scRenderGhosts(); }, 0);
    }

    function _scRenderGhosts() {
      if (!_scViewOpen || !_isHost) return;
      const container = document.getElementById('sc-players');
      if (!container) return;
      container.querySelectorAll('.sc-ghost, .sc-ghost-sep').forEach(el => el.remove());
      const scored = new Set(_scPlayers.map(p => p.name));
      const ghosts = _lastPlayerList.filter(p => !p.kicked && !scored.has(p.name));
      if (!ghosts.length) return;
      const sep = document.createElement('div');
      sep.className = 'sc-ghost-sep';
      container.appendChild(sep);
      ghosts.forEach(gp => {
        const p = { name: gp.name, score: 0 };
        const row = document.createElement('div');
        row.className = 'sc-row sc-ghost';
        row.dataset.name = p.name;
        row.style.opacity = '0.45';
        // Delta buttons
        const deltasWrap = document.createElement('div');
        deltasWrap.className = 'sc-deltas';
        _scDeltaBtns.forEach(d => {
          const btn = document.createElement('button');
          btn.className = 'sc-delta-btn ' + (d.delta < 0 ? 'sc-delta-neg' : 'sc-delta-pos');
          btn.textContent = d.label;
          btn.title = d.label;
          btn.onclick = () => _scQueueDelta(p.name, d.delta);
          deltasWrap.appendChild(btn);
        });
        row.appendChild(deltasWrap);
        // Score span (clickable like normal rows)
        const scoreSpan = document.createElement('span');
        scoreSpan.className = 'sc-score-cell';
        scoreSpan.textContent = '0';
        if (_isHost) {
          const scoreInput = document.createElement('input');
          scoreInput.className = 'sc-score-input';
          scoreInput.type = 'number';
          scoreInput.style.display = 'none';

          scoreSpan.title = 'Click to set score';
          scoreSpan.onclick = () => {
            scoreSpan.style.display = 'none';
            scoreInput.style.display = 'block';
            scoreInput.value = '0';
            scoreInput.focus(); scoreInput.select();
          };
          function _commitGhostScore() {
            const v = parseFloat(scoreInput.value);
            scoreInput.style.display = 'none';
            scoreSpan.style.display = '';
            if (isNaN(v)) return;
            // If player exists in real rows, use normal setter; otherwise optimistic promote
            if (_scPlayers.find(p2 => p2.name === p.name)) {
              _scSetScore(p.name, v);
            } else {
              socket.emit('host_action', { action: 'score_set', name: p.name, score: v });
              _scOptimisticPromote(p.name, v);
            }
          }
          scoreInput.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); _commitGhostScore(); } if (e.key === 'Escape') { scoreInput.style.display='none'; scoreSpan.style.display=''; } };
          scoreInput.onblur = _commitGhostScore;
          row.appendChild(scoreSpan);
          row.appendChild(scoreInput);
        } else {
          row.appendChild(scoreSpan);
        }
        // Pending label (same as real rows so _scUpdateAllPendingLabels works)
        const pendingLbl = document.createElement('span');
        pendingLbl.className = 'sc-pending-lbl';
        pendingLbl.dataset.name = p.name;
        pendingLbl.style.cssText = 'font-size:0.7em;font-weight:bold;min-width:28px;display:none;';
        row.appendChild(pendingLbl);
        // Name span (editable for host)
        const nameSpan = document.createElement('span');
        nameSpan.className = 'sc-name-cell';
        nameSpan.textContent = p.name;
        nameSpan.title = p.name + ' (not on scoreboard yet)';

        if (_isHost) {
          const nameInput = document.createElement('input');
          nameInput.className = 'sc-name-input';
          nameInput.style.display = 'none';

          nameSpan.title = 'Click to rename (ghost)';
          nameSpan.onclick = () => {
            nameSpan.style.display = 'none';
            nameInput.style.display = 'block';
            nameInput.value = p.name;
            nameInput.focus(); nameInput.select();
          };
          function _commitGhostName() {
            const v = nameInput.value.trim();
            if (v && v !== p.name) {
              // Ask server to rename the player in the web player list (not the scoreboard sheet)
              socket.emit('rename_player', { old_name: p.name, new_name: v });
              // Optimistic local update for the ghost row only
              try {
                row.dataset.name = v;
                nameSpan.textContent = v;
                nameSpan.title = v + ' (not on scoreboard yet)';
                p.name = v;
              } catch (e) {}
            }
            nameInput.style.display = 'none';
            nameSpan.style.display = '';
          }
          nameInput.onkeydown = e => {
            if (e.key === 'Enter') { e.preventDefault(); _commitGhostName(); }
            if (e.key === 'Escape') { nameInput.style.display='none'; nameSpan.style.display=''; }
          };
          nameInput.onblur = _commitGhostName;
          row.appendChild(nameSpan);
          row.appendChild(nameInput);
        } else {
          row.appendChild(nameSpan);
        }
        container.appendChild(row);
      });
    }

    /**
     * Always render when visible. Cache data when hidden so toggling shows fresh state.
     */
    function _scPatchOrRender(data) {
      if (!data) return;
      _scLastData = data;          // always cache latest data
      if (_scViewOpen) _scRender(data);
    }

    function _scUpdateAllPendingLabels() {
      document.querySelectorAll('.sc-pending-lbl').forEach(el => {
        const name = el.dataset.name;
        const pv = _scPending[name] || 0;
        if (pv !== 0) {
          el.textContent = (pv > 0 ? '[+' : '[') + pv + ']';
          el.style.color = pv >= 0 ? '#66dd88' : '#ff7070';
          el.style.display = 'inline';
        } else {
          el.textContent = ''; el.style.display = 'none';
        }
      });
    }

    // Row context menu
    let _scMenuEl = null;
    function _scShowRowMenu(name, anchor) {
      if (_scMenuEl) { _scMenuEl.remove(); _scMenuEl = null; }
      // Resolve latest name from DOM anchor if available (prevents stale prompts)
      let displayName = name;
      try {
        if (anchor && anchor.closest) {
          const rowEl = anchor.closest('.sc-row');
          if (rowEl && rowEl.dataset && rowEl.dataset.name) displayName = rowEl.dataset.name;
        }
      } catch (e) {}
      const menu = document.createElement('div');
      menu.style.cssText = 'position:fixed;background:#252525;border:1px solid #444;border-radius:4px;z-index:9999;min-width:120px;box-shadow:0 3px 10px rgba(0,0,0,0.6);touch-action:manipulation;';
      const zoom = parseFloat(document.documentElement.style.zoom) || 1;
      const rect = anchor.getBoundingClientRect();
      // getBoundingClientRect returns zoomed coords; position:fixed uses pre-zoom CSS coords
      const top = rect.bottom / zoom;
      const right = rect.right / zoom;
      const anchorTop = rect.top / zoom;
      const menuW = 124;
      const menuH = 36;
      const vw = window.innerWidth / zoom;
      const vh = window.innerHeight / zoom;
      let mleft = right - menuW;
      if (mleft < 4) mleft = 4;
      if (mleft + menuW > vw - 4) mleft = vw - menuW - 4;
      const mtop = (top + 2 + menuH > vh - 4)
        ? (anchorTop - menuH - 2)
        : (top + 2);
      menu.style.top = mtop + 'px';
      menu.style.left = mleft + 'px';
      function menuItem(label, color, fn) {
        const item = document.createElement('div');
        item.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:0.82em;color:' + color + ';font-family:Segoe UI,sans-serif;touch-action:manipulation;';
        item.textContent = label;
        item.onmouseenter = () => item.style.background = '#333';
        item.onmouseleave = () => item.style.background = '';
        item.onpointerdown = e => { e.stopPropagation(); menu.remove(); _scMenuEl = null; fn(); };
        menu.appendChild(item);
      }
      menuItem('✕  Remove player', '#cc6666', () => _confirm('Remove ' + displayName + ' from the scoreboard?', 'Remove', () => _scRemove(displayName)));
      menuItem('\uD83D\uDC65  Set team\u2026', '#aabbff', () => _scSetTeamPrompt(displayName, menu));
      // Only show Remove team if the player currently has one
      const curPlayer = _scPlayers.find(p => p.name === displayName);
      if (curPlayer && curPlayer.team) {
        menuItem('\u274C  Remove team', '#cc9966', () => { socket.emit('host_action', { action: 'player_set_team', name: displayName, team: '' }); if (curPlayer) curPlayer.team = ''; });
      }
      document.body.appendChild(menu);
      _scMenuEl = menu;
      setTimeout(() => {
        function h(e) {
          if (!menu.contains(e.target)) {
            menu.remove(); _scMenuEl = null;
            document.removeEventListener('pointerdown', h, true);
          }
        }
        document.addEventListener('pointerdown', h, true);
      }, 0);
    }

    function _scSetTeamPrompt(name, menuEl) {
      // Replace the menu with an inline input+datalist for team selection
      if (menuEl) { menuEl.remove(); _scMenuEl = null; }
      const zoom = parseFloat(document.documentElement.style.zoom) || 1;
      const wrap = document.createElement('div');
      wrap.style.cssText = 'position:fixed;background:#252525;border:1px solid #446;border-radius:6px;z-index:9999;padding:8px 10px;box-shadow:0 3px 12px rgba(0,0,0,0.7);display:flex;flex-direction:column;gap:6px;min-width:180px;';
      // Position near center-bottom of viewport
      const vw = window.innerWidth / zoom;
      const vh = window.innerHeight / zoom;
      wrap.style.left = Math.max(8, (vw / 2) - 90) + 'px';
      wrap.style.top  = Math.max(8, vh * 0.4) + 'px';

      const label = document.createElement('div');
      label.style.cssText = 'font-size:0.75em;color:#88aacc;font-family:Segoe UI,sans-serif;';
      label.textContent = 'Team for ' + name;
      wrap.appendChild(label);

      const inputRow = document.createElement('div');
      inputRow.style.cssText = 'display:flex;gap:5px;align-items:center;';

      const dlId = 'sc-team-dl-' + Date.now();
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.setAttribute('list', dlId);
      inp.placeholder = 'Team name';
      inp.autocomplete = 'off';
      const curPlayer = _scPlayers.find(p => p.name === name);
      if (curPlayer && curPlayer.team) inp.value = curPlayer.team;
      inp.style.cssText = 'flex:1;background:#1a1a2a;border:1px solid #446;border-radius:4px;color:#e0e0ff;padding:4px 7px;font-size:0.82em;font-family:Segoe UI,sans-serif;outline:none;';

      const dl = document.createElement('datalist');
      dl.id = dlId;
      _scTeamNames.forEach(t => { const opt = document.createElement('option'); opt.value = t; dl.appendChild(opt); });

      const okBtn = document.createElement('button');
      okBtn.textContent = 'Set';
      okBtn.style.cssText = 'background:#1a2840;border:1px solid #446;border-radius:4px;color:#aaccff;padding:4px 10px;font-size:0.78em;cursor:pointer;font-family:Segoe UI,sans-serif;';

      inputRow.appendChild(inp);
      inputRow.appendChild(dl);
      inputRow.appendChild(okBtn);
      wrap.appendChild(inputRow);
      document.body.appendChild(wrap);
      inp.focus();

      function commit() {
        const team = inp.value.trim();
        wrap.remove();
        socket.emit('host_action', { action: 'player_set_team', name, team });
        if (curPlayer) curPlayer.team = team;
      }
      okBtn.onpointerdown = e => { e.stopPropagation(); commit(); };
      inp.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); commit(); } if (e.key === 'Escape') wrap.remove(); };

      // Dismiss on outside click
      setTimeout(() => {
        function h(e) { if (!wrap.contains(e.target)) { wrap.remove(); document.removeEventListener('pointerdown', h, true); } }
        document.addEventListener('pointerdown', h, true);
      }, 0);

      // Refresh team list if not loaded yet
      if (!_scTeamNames.length) socket.emit('host_action', { action: 'get_teams' });
    }

    function _scSubmitPending() { _scFlushAll(); }
    function _scSetScore(name, score) {
      socket.emit('host_action', { action: 'score_set', name, score });
      // Optimistic: update _scPlayers and DOM immediately
      const op = _scPlayers.find(p => p.name === name);
      if (op) {
        op.score = score;
        if (_scLastData) _scLastData.players = _scPlayers.map(p => Object.assign({}, p));
        // No long lock needed — DOM is already correct; let server confirm normally
        _scOptimisticUntil = Date.now() + 5000;
        _scOptimisticPlayers = _scPlayers.map(p => Object.assign({}, p));
        const container = document.getElementById('sc-players');
        if (container) {
          const row = container.querySelector('.sc-row[data-name="' + CSS.escape(name) + '"]');
          if (row) {
            const sc = row.querySelector('.sc-score-cell');
            if (sc) sc.textContent = _scFmtScore(score);
          }
        }
      }
    }
    function _scRenameInline(oldName, newName) {
      socket.emit('host_action', { action: 'player_rename', old_name: oldName, new_name: newName });
      // Optimistic: update name in DOM immediately
      _scOptimisticUntil = Date.now() + 5000;
      const op = _scPlayers.find(p => p.name === oldName);
      if (op) {
        op.name = newName;
        if (_scLastData) _scLastData.players = _scPlayers.map(p => Object.assign({}, p));
        _scOptimisticPlayers = _scPlayers.map(p => Object.assign({}, p));
        const container = document.getElementById('sc-players');
        if (container) {
          const row = container.querySelector('.sc-row[data-name="' + CSS.escape(oldName) + '"]');
          if (row) {
            row.dataset.name = newName;
            const ns = row.querySelector('.sc-name-cell');
            if (ns) { ns.textContent = newName; ns.title = newName; }
          }
        }
      }
    }
    function _scRemove(name) {
      socket.emit('host_action', { action: 'player_remove', name });
      // Optimistic: remove row immediately
      _scOptimisticUntil = Date.now() + 5000;
      _scPlayers = _scPlayers.filter(p => p.name !== name);
      if (_scLastData) _scLastData.players = _scPlayers.map(p => Object.assign({}, p));
      _scOptimisticPlayers = _scPlayers.map(p => Object.assign({}, p));
      const container = document.getElementById('sc-players');
      if (container) {
        const row = container.querySelector('.sc-row[data-name="' + CSS.escape(name) + '"]');
        if (row) row.remove();
      }
    }
    function _scAddPlayer() {
      const inp = document.getElementById('sc-add-input');
      if (!inp) return;
      const name = inp.value.trim();
      if (!name) return;
      socket.emit('host_action', { action: 'player_add', name });
      inp.value = '';
      // Optimistic: immediately add the row
      if (!_scPlayers.find(p => p.name === name)) {
        _scOptimisticUntil = Date.now() + 5000;
        // Save old _scPlayers so _scRender's sameNames check detects a structural change
        const prevPlayers = _scPlayers.slice();
        _scPlayers.push({ name, score: 0 });
        if (_scLastData) _scLastData.players = _scPlayers.map(p => Object.assign({}, p));
        _scOptimisticPlayers = _scPlayers.map(p => Object.assign({}, p));
        // Reset to prev so _scRender sees old length vs new length → full rebuild
        _scPlayers = prevPlayers;
        _scRender(_scLastData || { players: [...prevPlayers, { name, score: 0 }], delta_buttons: [] });
        // _scRender sets _scPlayers = newPlayers during full rebuild
      }
    }
    function _scClearAll() {
      if (!confirm('Remove all players from the scoreboard?')) return;
      socket.emit('host_action', { action: 'scores_clear_all' });
      // Optimistic: clear immediately without waiting for server round-trip
      _scPlayers = [];
      if (_scLastData) _scLastData.players = [];
      _scOptimisticUntil = Date.now() + 5000;
      _scOptimisticPlayers = [];
      // Directly wipe DOM — _scRender would no-op (sameNames = both empty)
      const container = document.getElementById('sc-players');
      if (container) container.innerHTML = '';
      setTimeout(() => { _scFitScroll(); _scRenderGhosts(); }, 0);
    }

    function _scArchive() {
      if (_scArchiveBusy) return;
      if (!confirm('Are you sure you want to archive this session and clear the data?')) return;
      _scArchivePreCount = Array.isArray(_scPlayers) ? _scPlayers.length : 0;
      _scArchiveRequestedAt = Date.now();
      _scSetArchiveBusy(true);
      _showToast('Archiving session…');
      socket.emit('host_action', { action: 'scores_archive' });

      // Encourage a quick UI refresh while archive runs.
      setTimeout(() => { socket.emit('host_action', { action: 'get_scores' }); }, 500);
      setTimeout(() => { socket.emit('host_action', { action: 'get_scores' }); }, 1800);

      if (_scArchiveBusyTimer) clearTimeout(_scArchiveBusyTimer);
      _scArchiveBusyTimer = setTimeout(() => {
        if (!_scArchiveBusy) return;
        _scSetArchiveBusy(false);
        _showToast('Archive request sent. Waiting for scoreboard update…', 4200);
        _scArchiveBusyTimer = null;
      }, 12000);
    }

    socket.on('scores_update', data => {
      if (data && data.auto_send !== undefined)
        _scLoadPrefs(data.auto_send, data.delay_together, data.commit_delay, data.score_font, data.name_font);

      if (_scArchiveBusy) {
        const now = Date.now();
        const playersCount = (data && Array.isArray(data.players)) ? data.players.length : -1;
        const elapsed = now - (_scArchiveRequestedAt || now);
        if (playersCount === 0 && (elapsed > 500 || _scArchivePreCount > 0)) {
          _scSetArchiveBusy(false);
          if (_scArchiveBusyTimer) { clearTimeout(_scArchiveBusyTimer); _scArchiveBusyTimer = null; }
          _showToast('Archive complete.', 2200);
        }
      }

      // If an optimistic update was applied recently, hold off re-rendering until either:
      //   a) the server data matches our optimistic snapshot (early release), or
      //   b) the 5-second hard timeout expires.
      if (Date.now() < _scOptimisticUntil && _scOptimisticPlayers) {
        const sp = _scOptimisticPlayers;
        const dp = data && data.players;
        const matches = dp && dp.length === sp.length &&
          sp.every((op, i) => dp[i] && dp[i].name === op.name && dp[i].score === op.score);
        // Always cache prefs/structure fields
        if (_scLastData && data) {
          _scLastData.auto_send      = data.auto_send;
          _scLastData.delay_together = data.delay_together;
          _scLastData.commit_delay   = data.commit_delay;
          _scLastData.score_font     = data.score_font;
          _scLastData.name_font      = data.name_font;
          _scLastData.delta_buttons  = data.delta_buttons;
        } else if (!_scLastData) {
          _scLastData = data;
        }
        if (!matches) return; // server hasn't caught up yet
        // Server confirmed our change — release lock early
        _scOptimisticUntil = 0;
        _scOptimisticPlayers = null;
      }
      _scLastData = data;
      // Render whenever the scoreboard div is actually visible, regardless of state variable
      const sv = document.getElementById('scoreboard-view');
      if (_scViewOpen || (sv && sv.style.display !== 'none' && sv.style.display !== '')) {
        if (!_scViewOpen) _scViewOpen = true; // re-sync state if DOM is ahead
        _scRender(data);
      }
      _scApplyViewState();
    });

    socket.on('teams_update', data => {
      if (data && Array.isArray(data.teams)) _scTeamNames = data.teams;
    });

    // Restore scoreboard view preference when host is granted
    function _scRestoreView() {
      try {
        const vm = document.cookie.match(/(?:^|;\s*)scView=([^;]*)/);
        if (vm && decodeURIComponent(vm[1]) === 'scoreboard') _scViewOpen = true;
      } catch(e) {}
      _scApplyViewState();
      if (_scViewOpen) {
        if (_scLastData) _scRender(_scLastData);
        socket.emit('host_action', { action: 'get_scores' });
        socket.emit('host_action', { action: 'get_teams' });
      }
      // Periodic refresh: re-request scores every 2s while scoreboard is open,
      // but skip if the user has focus inside the scoreboard (editing a field)
      setInterval(() => {
        if (!_scViewOpen) return;
        const sc = document.getElementById('sc-players');
        if (sc && sc.contains(document.activeElement)) return;
        socket.emit('host_action', { action: 'get_scores' });
      }, 2000);
    }

    function _ctrlToggleUpNext() {
      _ctrlUpNextVisible = !_ctrlUpNextVisible;
      const panel = document.getElementById('ctrl-upnext-panel');
      if (panel) panel.style.display = _ctrlUpNextVisible ? 'block' : 'none';
      _ctrlSyncSectionArrows();
      _ctrlSavePanels();
    }

    function _ctrlToggleYouTubeList() {
      const opening = !_ctrlYtListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlYtListOpen = true;
        _ctrlListPopupOpen('YouTube Videos', 'yt');
        socket.emit('request_youtube_list');
      }
    }

    socket.on('youtube_list', data => {
      _ctrlYtCurrentId = data.queued_id || null;
      if (!_ctrlListPopupMode === 'yt' && !_ctrlYtListOpen) return;
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      if (!data.videos || !data.videos.length) {
        list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">No videos available</div>';
        return;
      }
      data.videos.forEach(v => {
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item' + (v.id === _ctrlYtCurrentId ? ' ctrl-yt-active' : '');
        el.title = v.full_title;
        el.innerHTML = '<span class="ctrl-popup-item-dur">[' + v.duration + ']</span><span class="ctrl-popup-item-title">' + _ctrlEscapeHtml(v.title) + '</span>';
        el.onclick = () => {
          socket.emit('host_action', {action: 'queue_youtube', video_id: v.id});
          _ctrlListPopupClose();
        };
        list.appendChild(el);
      });
    });

    function _ctrlEscapeHtml(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function _ctrlTogglePlaylist() {
      _ctrlPlaylistVisible = !_ctrlPlaylistVisible;
      const panel = document.getElementById('ctrl-playlist-panel');
      if (panel) panel.style.display = _ctrlPlaylistVisible ? 'flex' : 'none';
      const spacer = document.getElementById('ctrl-flex-spacer');
      if (spacer) spacer.classList.toggle('hidden', _ctrlPlaylistVisible);
      if (_ctrlPlaylistVisible) _plOpen();
      _ctrlSyncSectionArrows();
      _ctrlSavePanels();
    }

    const _ctrlLtTypes = [
      {id:'lightning_regular',   mode:'regular',   label:'Regular'},
      {id:'lightning_blind',     mode:'blind',     label:'Blind'},
      {id:'lightning_peek',      mode:'peek',      label:'Peek'},
      {id:'lightning_frame',     mode:'frame',     label:'Frame'},
      {id:'lightning_cover',     mode:'cover',     label:'Cover'},
      {id:'lightning_image',     mode:'image',     label:'Image'},
      {id:'lightning_character', mode:'character', label:'Char'},
      {id:'lightning_title',     mode:'title',     label:'Title'},
      {id:'lightning_synopsis',  mode:'synopsis',  label:'Synopsis'},
      {id:'lightning_trivia',    mode:'trivia',    label:'Trivia'},
      {id:'lightning_emoji',     mode:'emoji',     label:'Emoji'},
      {id:'lightning_song',      mode:'song',      label:'Song'},
      {id:'lightning_ost',       mode:'ost',       label:'OST'},
      {id:'lightning_clues',     mode:'clues',     label:'Clues'},
      {id:'lightning_tags',      mode:'tags',      label:'Tags'},
      {id:'lightning_episodes',  mode:'episodes',  label:'Episodes'},
      {id:'lightning_clip',      mode:'clip',      label:'Clip'},
    ];

    function _ctrlCloseAllLists() {
      _ctrlLtListOpen = false;
      _ctrlYtListOpen = false;
      _ctrlFlListOpen = false;
      _ctrlSearchListOpen = false;
      _ctrlDiffListOpen = false;
      _ctrlAutoBonusListOpen = false;
      _ctrlDirListOpen = false;
      _ctrlBuzzSoundListOpen = false;
      _ctrlListPopupClose();
    }

    function _ctrlToggleLtList() {
      const opening = !_ctrlLtListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlLtListOpen = true;
        _ctrlListPopupOpen('Lightning Round Type', 'lt');
        _ctrlRenderLtList();
      }
    }

    function _ctrlRenderLtList() {
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      _ctrlLtTypes.forEach(t => {
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item' + (t.mode === _ctrlLtCurrentMode ? ' ctrl-yt-active' : '');
        el.textContent = t.label;
        el.onclick = () => { socket.emit('host_action', {action: 'invoke', id: t.id}); _ctrlListPopupClose(); };
        list.appendChild(el);
      });
    }

    function _ctrlToggleFlList() {
      const opening = !_ctrlFlListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlFlListOpen = true;
        _ctrlListPopupOpen('Fixed Lightning Rounds', 'fl');
        socket.emit('host_action', {action: 'get_fixed_lightning_list'});
      }
    }

    socket.on('fixed_lightning_list', data => {
      _ctrlFlCurrentName = data.queued_name || null;
      if (!_ctrlFlListOpen) return;
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      if (!data.rounds || !data.rounds.length) {
        list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">No fixed rounds available</div>';
        return;
      }
      data.rounds.forEach(r => {
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item' + (r.name === _ctrlFlCurrentName ? ' ctrl-yt-active' : '');
        el.title = r.description || '';
        el.innerHTML = '<span class="ctrl-popup-item-dur">[' + r.duration + ']</span><span class="ctrl-popup-item-title">' + _ctrlEscapeHtml(r.name) + '</span>';
        el.onclick = () => {
          socket.emit('host_action', {action: 'queue_fixed_lightning', index: r.index});
          _ctrlListPopupClose();
        };
        list.appendChild(el);
      });
    });

    function _ctrlToggleSearchRow() {
      const opening = !_ctrlSearchListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlSearchListOpen = true;
        _ctrlListPopupOpen('Search Themes', 'search');
        const input = document.getElementById('ctrl-list-popup-search-input');
        if (input) { input.value = ''; setTimeout(() => input.focus(), 50); }
      }
    }

    function _ctrlDoSearch() {
      const input = document.getElementById('ctrl-search-input');
      const query = (input ? input.value : '').trim();
      if (!query) return;
      if (input) input.blur();
      const list = document.getElementById('ctrl-search-list');
      if (list) list.innerHTML = '<div style="padding:4px;color:#556;font-size:0.85em">Searching…</div>';
      socket.emit('host_action', {action: 'search_themes', query: query});
    }

    let _ctrlSearchDebounceTimer = null;
    function _ctrlListPopupSearchDebounce() {
      clearTimeout(_ctrlSearchDebounceTimer);
      const input = document.getElementById('ctrl-list-popup-search-input');
      const query = (input ? input.value : '').trim();
      if (!query) {
        const list = document.getElementById('ctrl-list-popup-list');
        if (list) list.innerHTML = '';
        return;
      }
      if (query.length < 3) {
        const list = document.getElementById('ctrl-list-popup-list');
        if (list) list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Type at least 3 characters…</div>';
        return;
      }
      _ctrlSearchDebounceTimer = setTimeout(() => _ctrlListPopupDoSearch(false), 300);
    }

    function _ctrlListPopupDoSearch(blurInput = true) {
      const input = document.getElementById('ctrl-list-popup-search-input');
      const query = (input ? input.value : '').trim();
      if (!query) return;
      if (blurInput && input) input.blur();
      const list = document.getElementById('ctrl-list-popup-list');
      if (list) list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Searching…</div>';
      socket.emit('host_action', {action: 'search_themes', query: query});
    }

    function _ctrlHighlightSearchText(text, query) {
      const src = String(text || '');
      const needle = String(query || '').trim();
      if (!needle) return _ctrlEscapeHtml(src);
      const esc = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const re = new RegExp(esc, 'ig');
      let out = '';
      let last = 0;
      let m;
      while ((m = re.exec(src)) !== null) {
        out += _ctrlEscapeHtml(src.slice(last, m.index));
        out += '<span class="ctrl-search-hit">' + _ctrlEscapeHtml(m[0]) + '</span>';
        last = m.index + m[0].length;
        if (!m[0].length) re.lastIndex += 1;
      }
      out += _ctrlEscapeHtml(src.slice(last));
      return out;
    }

    function _ctrlBuildSearchRow(r, index) {
      const row = document.createElement('div');
      row.className = 'ctrl-popup-item';
      row.title = r.filename;
      row.dataset.filename = r.filename || '';

      const titleEn = String(r.title_en || '').trim();
      const titleJp = String(r.title_jp || '').trim();
      const titleFallback = String(r.title || '').trim();
      const qLower = _ctrlSearchQuery.toLowerCase();
      const enMatch = !!(qLower && titleEn && titleEn.toLowerCase().includes(qLower));
      const jpMatch = !!(qLower && titleJp && titleJp.toLowerCase().includes(qLower));
      const fnMatch = !!(qLower && r.filename && r.filename.toLowerCase().includes(qLower));
      let titleText = titleEn || titleJp || titleFallback || 'Unknown Title';
      if (titleEn && titleJp && jpMatch && !enMatch) {
        titleText = titleEn + ' (' + titleJp + ')';
      } else if (fnMatch && !enMatch && !jpMatch) {
        const fnBase = String(r.filename || '').replace(/^.*[\\/]/, '');
        titleText = (titleEn || titleJp || titleFallback || 'Unknown Title') + ' (' + fnBase + ')';
      }
      const slugText = String(r.slug || '').trim();
      const labelText = slugText ? (titleText + ' ' + slugText) : titleText;
      const topText = (Number(index) + 1) + '. ' + labelText;
      const songText = String(r.song || '').trim();
      const artistText = String(r.artist || '').trim();
      const songByText = (songText && artistText)
        ? (songText + ' by ' + artistText)
        : (songText || artistText || 'Unknown Song');
      const seasonText = String(r.season || '').trim();
      const formatText = String(r.format || '').trim();
      const studioText = String(r.studio || '').trim();
      const metaParts = [seasonText, formatText, studioText].filter(Boolean);
      const metaText = metaParts.join(' | ');

      const actionId = _themeActionRegister(r.filename, labelText);

      const textCol = document.createElement('div');
      textCol.className = 'ctrl-popup-search-text';
      const lineSong = document.createElement('div');
      lineSong.className = 'ctrl-popup-search-line song';
      lineSong.innerHTML = _ctrlHighlightSearchText(topText, _ctrlSearchQuery);
      const lineArtist = document.createElement('div');
      lineArtist.className = 'ctrl-popup-search-line artist';
      lineArtist.innerHTML = _ctrlHighlightSearchText(songByText, _ctrlSearchQuery);
      const lineMeta = document.createElement('div');
      lineMeta.className = 'ctrl-popup-search-line meta';
      lineMeta.innerHTML = _ctrlHighlightSearchText(metaText, _ctrlSearchQuery);
      textCol.appendChild(lineSong);
      textCol.appendChild(lineArtist);
      textCol.appendChild(lineMeta);

      row.appendChild(textCol);

      row.onclick = () => _openThemeActionPrompt(actionId);

      return row;
    }

    function _ctrlRenderSearchResults(reset = false) {
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      if (reset) {
        _ctrlSearchRenderCount = 0;
        list.innerHTML = '';
      }
      const oldMore = list.querySelector('.ctrl-search-more-wrap');
      if (oldMore) oldMore.remove();

      if (!_ctrlSearchResultsAll || !_ctrlSearchResultsAll.length) {
        list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">No results found</div>';
        return;
      }

      const end = Math.min(_ctrlSearchRenderCount + _CTRL_SEARCH_PAGE_SIZE, _ctrlSearchResultsAll.length);
      const frag = document.createDocumentFragment();
      for (let i = _ctrlSearchRenderCount; i < end; i++) {
        frag.appendChild(_ctrlBuildSearchRow(_ctrlSearchResultsAll[i], i));
      }
      list.appendChild(frag);
      _ctrlSearchRenderCount = end;

      if (_ctrlSearchRenderCount < _ctrlSearchResultsAll.length) {
        const wrap = document.createElement('div');
        wrap.className = 'ctrl-search-more-wrap';
        wrap.style.cssText = 'display:flex;justify-content:center;padding:8px 0 4px;';
        const btn = document.createElement('button');
        btn.className = 'ctrl-popup-item-add';
        btn.style.cssText = 'font-size:0.85em;padding:4px 10px;';
        const remaining = _ctrlSearchResultsAll.length - _ctrlSearchRenderCount;
        const step = Math.min(_CTRL_SEARCH_PAGE_SIZE, remaining);
        btn.textContent = 'Show ' + step + ' more';
        btn.onclick = () => _ctrlRenderSearchResults(false);
        wrap.appendChild(btn);
        list.appendChild(wrap);
      }
    }

    socket.on('theme_search_results', data => {
      if (!_ctrlSearchListOpen) return;
      _ctrlSearchIsInfinite = !!(data && data.playlist_infinite);
      _ctrlSearchQuery = String((data && data.query) || '').trim();
      _ctrlSearchResultsAll = Array.isArray(data && data.results) ? data.results : [];
      const titleEl = document.getElementById('ctrl-list-popup-title');
      if (titleEl) titleEl.textContent = 'Search Themes (' + _ctrlSearchResultsAll.length + ')';
      _ctrlRenderSearchResults(true);
    });

    // ── Directory browser ──
    let _ctrlDirListOpen = false;
    let _ctrlDirStatType = null;   // e.g. 'artist'
    let _ctrlDirGroupLabel = null; // e.g. 'Yuki Kajiura'
    let _ctrlDirGroupFiles = [];   // filenames for level-3 back navigation

    const _CTRL_DIR_LS_KEY = 'ctrl_dir_pos';
    function _ctrlDirSavePos(statType, groupLabel) {
      try { localStorage.setItem(_CTRL_DIR_LS_KEY, JSON.stringify({statType: statType || null, groupLabel: groupLabel || null})); } catch(e){}
    }
    function _ctrlDirLoadPos() {
      try { return JSON.parse(localStorage.getItem(_CTRL_DIR_LS_KEY) || 'null') || {}; } catch(e){ return {}; }
    }

    const _ctrlDirStatTypes = [
      {key:'artist',  label:'Themes by Artist'},
      {key:'series',  label:'Themes by Series'},
      {key:'season',  label:'Themes by Season'},
      {key:'year',    label:'Themes by Year'},
      {key:'studio',  label:'Themes by Studio'},
      {key:'tag',     label:'Themes by Tag'},
      {key:'type',    label:'Themes by Type'},
      {key:'slug',    label:'Themes by Slug'},
    ];

    function _ctrlToggleDirectoryList() {
      const opening = !_ctrlDirListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlDirListOpen = true;
        const saved = _ctrlDirLoadPos();
        if (saved.statType) {
          // Restore to last-used stat type (or group if one was open)
          _ctrlDirStatType = saved.statType;
          _ctrlDirGroupLabel = saved.groupLabel || null;
          const statLabel = (_ctrlDirStatTypes.find(t => t.key === saved.statType) || {}).label || 'Directory';
          _ctrlListPopupOpen(statLabel + ' — Loading…', 'dir_type');
          const list = document.getElementById('ctrl-list-popup-list');
          if (list) list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Loading…</div>';
          if (saved.groupLabel) {
            socket.emit('host_action', {action: 'get_directory_themes', stat_type: saved.statType, group_label: saved.groupLabel});
          } else {
            socket.emit('host_action', {action: 'get_directory_groups', stat_type: saved.statType});
          }
        } else {
          _ctrlDirStatType = null;
          _ctrlListPopupOpen('Directory', 'dir_type');
          _ctrlRenderDirStatTypes();
        }
      }
    }

    function _ctrlRenderDirStatTypes() {
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      const saved = _ctrlDirLoadPos();
      if (saved.statType) {
        // Show a quick "last used" hint at top
        const hint = document.createElement('div');
        hint.style.cssText = 'padding:2px 10px 5px;font-size:0.75em;color:#557;';
        const savedLabel = (_ctrlDirStatTypes.find(t => t.key === saved.statType) || {}).label || saved.statType;
        hint.textContent = 'Last: ' + savedLabel + (saved.groupLabel ? ' › ' + saved.groupLabel : '');
        list.appendChild(hint);
      }
      _ctrlDirStatTypes.forEach(t => {
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item';
        el.textContent = t.label;
        el.onclick = () => {
          _ctrlDirStatType = t.key;
          _ctrlDirGroupLabel = null;
          _ctrlDirSavePos(t.key, null);
          const titleEl = document.getElementById('ctrl-list-popup-title');
          if (titleEl) titleEl.textContent = t.label + ' — Loading…';
          list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Loading…</div>';
          socket.emit('host_action', {action: 'get_directory_groups', stat_type: t.key});
        };
        list.appendChild(el);
      });
    }

    socket.on('directory_groups', data => {
      if (!_ctrlDirListOpen) return;
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      const titleEl = document.getElementById('ctrl-list-popup-title');
      const statLabel = (_ctrlDirStatTypes.find(t => t.key === data.stat_type) || {}).label || 'Directory';
      if (titleEl) titleEl.textContent = statLabel + ' (' + (data.groups ? data.groups.length : 0) + ')';
      // Back button
      const back = document.createElement('div');
      back.className = 'ctrl-popup-item-back';
      back.innerHTML = '&#x2190; Back';
      back.onclick = () => {
        _ctrlDirStatType = null;
        _ctrlDirGroupLabel = null;
        _ctrlDirSavePos(null, null);
        if (titleEl) titleEl.textContent = 'Directory';
        _ctrlRenderDirStatTypes();
      };
      list.appendChild(back);
      const div = document.createElement('div'); div.className = 'ctrl-popup-divider'; list.appendChild(div);
      if (!data.groups || !data.groups.length) {
        const empty = document.createElement('div');
        empty.style.cssText = 'padding:8px;color:#556;font-size:0.85em';
        empty.textContent = 'No entries found';
        list.appendChild(empty);
        return;
      }
      data.groups.forEach(g => {
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item';
        const pct = data.total ? (g.count / data.total * 100).toFixed(1) : 0;
        el.innerHTML = '<span class="ctrl-popup-item-title">' + _ctrlEscapeHtml(g.label) + '</span>' +
                       '<span class="ctrl-popup-item-dur">' + g.count + ' (' + pct + '%)</span>';
        el.onclick = () => {
          _ctrlDirGroupLabel = g.label;
          _ctrlDirSavePos(data.stat_type, g.label);
          if (titleEl) titleEl.textContent = _ctrlEscapeHtml(g.label) + ' — Loading…';
          list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Loading…</div>';
          socket.emit('host_action', {action: 'get_directory_themes', stat_type: _ctrlDirStatType, group_label: g.label});
        };
        list.appendChild(el);
      });
    });

    socket.on('directory_themes', data => {
      if (!_ctrlDirListOpen) return;
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      const box = document.getElementById('ctrl-list-popup-box');
      if (box) box.classList.add('search-mode');
      list.innerHTML = '';
      const titleEl = document.getElementById('ctrl-list-popup-title');
      const groupLabel = data.group_label || _ctrlDirGroupLabel || '';
      const statLabel = (_ctrlDirStatTypes.find(t => t.key === data.stat_type) || {}).label || 'Directory';
      const results = Array.isArray(data.results) ? data.results : [];
      if (titleEl) titleEl.textContent = _ctrlEscapeHtml(groupLabel) + ' (' + results.length + ')';
      // Back button → returns to group list
      const back = document.createElement('div');
      back.className = 'ctrl-popup-item-back';
      back.innerHTML = '&#x2190; ' + _ctrlEscapeHtml(statLabel);
      back.onclick = () => {
        if (box) box.classList.remove('search-mode');
        _ctrlDirGroupLabel = null;
        _ctrlDirSavePos(data.stat_type, null);
        if (titleEl) titleEl.textContent = statLabel + ' — Loading…';
        list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Loading…</div>';
        socket.emit('host_action', {action: 'get_directory_groups', stat_type: data.stat_type});
      };
      list.appendChild(back);
      const divEl = document.createElement('div'); divEl.className = 'ctrl-popup-divider'; list.appendChild(divEl);
      if (!results.length) {
        const empty = document.createElement('div');
        empty.style.cssText = 'padding:8px;color:#556;font-size:0.85em';
        empty.textContent = 'No themes found';
        list.appendChild(empty);
        return;
      }
      // Re-use search row builder — set query to empty so no highlighting
      const savedQuery = _ctrlSearchQuery;
      _ctrlSearchQuery = '';
      results.forEach((r, i) => list.appendChild(_ctrlBuildSearchRow(r, i)));
      _ctrlSearchQuery = savedQuery;
    });

    // ── Buzzer sound preset selector ─────────────────────────────────────────
    let _ctrlBuzzSoundListOpen = false;

    function _ctrlToggleBuzzSoundList() {
      const opening = !_ctrlBuzzSoundListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlBuzzSoundListOpen = true;
        _ctrlListPopupOpen('Buzzer Sound', 'buzz_sound');
        const list = document.getElementById('ctrl-list-popup-list');
        if (list) list.innerHTML = '<div style="padding:8px;color:#556;font-size:0.85em">Loading…</div>';
        socket.emit('host_action', {action: 'get_buzz_presets'});
      }
    }

    socket.on('buzz_presets', data => {
      if (!_ctrlBuzzSoundListOpen) return;
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      const titleEl = document.getElementById('ctrl-list-popup-title');
      if (titleEl) titleEl.textContent = 'Buzzer Sound';
      const hint = document.createElement('div');
      hint.style.cssText = 'padding:3px 10px 6px;font-size:0.75em;color:#557;';
      hint.textContent = 'Click a preset to select and play a test sound.';
      list.appendChild(hint);
      (data.presets || []).forEach(p => {
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item';
        const isCurrent = p.index === data.current;
        if (isCurrent) el.style.cssText = 'background:#1a2a1a;border-left:2px solid #4a8;';
        el.innerHTML =
          '<span style="display:inline-block;width:1.2em;color:#4c8;font-size:0.9em">' +
          (isCurrent ? '\u2713' : '') + '</span>' +
          '<span class="ctrl-popup-item-title">' + _ctrlEscapeHtml(p.name) + '</span>';
        el.onclick = () => {
          socket.emit('host_action', {action: 'set_buzz_preset', index: p.index});
          document.cookie = 'buzz_preset_index=' + p.index + ';path=/;max-age=31536000';
        };
        list.appendChild(el);
      });
    });

    const _ctrlDiffOptions = [
      {label: 'Very Easy', value: 0},
      {label: 'Easy',      value: 1},
      {label: 'Normal',    value: 2},
      {label: 'Hard',      value: 3},
      {label: 'Very Hard', value: 4},
      {label: 'Random',    value: 5},
    ];
    function _ctrlToggleDiffList() {
      const opening = !_ctrlDiffListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlDiffListOpen = true;
        _ctrlListPopupOpen('Difficulty', 'diff');
        _ctrlRenderDiffList();
      }
    }
    function _ctrlRenderDiffList() {
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      _ctrlDiffOptions.forEach(opt => {
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item' + (opt.value === _ctrlDiffCurrent ? ' ctrl-yt-active' : '');
        el.textContent = opt.label;
        el.onclick = () => {
          _ctrlDiffCurrent = opt.value;
          socket.emit('host_action', {action: 'set_difficulty', value: opt.value});
          _ctrlListPopupClose();
        };
        list.appendChild(el);
      });
    }

    const _ctrlAutoBonusOptions = [
      {label: 'Random',          value: 'random'},
      {divider: true},
      {label: 'Multiple Choice', value: 'multiple'},
      {label: 'Year',            value: 'year'},
      {label: 'Score',           value: 'score'},
      {label: 'Members',         value: 'members'},
      {label: 'Popularity Rank', value: 'popularity'},
      {label: 'Tags',            value: 'tags'},
      {label: 'Studio',          value: 'studio'},
      {label: 'Artist',          value: 'artist'},
      {label: 'Song Title',      value: 'song'},
      {divider: true},
      {label: 'Free Form',       value: 'freeform'},
      {label: 'Buzzer',          value: 'buzzer'},
    ];
    function _ctrlToggleAutoBonusList() {
      const opening = !_ctrlAutoBonusListOpen;
      _ctrlCloseAllLists();
      if (opening) {
        _ctrlAutoBonusListOpen = true;
        _ctrlListPopupOpen('Auto Bonus at Start', 'auto_bonus');
        _ctrlRenderAutoBonusList();
      }
    }
    function _ctrlRenderAutoBonusList() {
      const list = document.getElementById('ctrl-list-popup-list');
      if (!list) return;
      list.innerHTML = '';
      if (_ctrlAutoBonusCurrent) {
        const offEl = document.createElement('div');
        offEl.className = 'ctrl-popup-item ctrl-popup-item-off';
        offEl.textContent = '✕  Off';
        offEl.onclick = () => {
          _ctrlAutoBonusCurrent = null;
          socket.emit('host_action', {action: 'set_auto_bonus', value: ''});
          _ctrlListPopupClose();
        };
        list.appendChild(offEl);
        const sepDiv = document.createElement('div');
        sepDiv.className = 'ctrl-popup-divider';
        list.appendChild(sepDiv);
      }
      _ctrlAutoBonusOptions.forEach(opt => {
        if (opt.divider) {
          const div = document.createElement('div');
          div.className = 'ctrl-popup-divider';
          list.appendChild(div);
          return;
        }
        const el = document.createElement('div');
        el.className = 'ctrl-popup-item' + (opt.value === _ctrlAutoBonusCurrent ? ' ctrl-yt-active' : '');
        el.textContent = opt.label;
        el.onclick = () => {
          _ctrlAutoBonusCurrent = opt.value;
          socket.emit('host_action', {action: 'set_auto_bonus', value: opt.value || ''});
          _ctrlListPopupClose();
        };
        list.appendChild(el);
      });
    }

    socket.on('toggles_update', data => {
      _ctrlCurrentToggles = data || {};
      const sessionCount = Math.max(0, Number(data.session_history_count || 0));
      _ctrlUpdateResetSessionButton(sessionCount);
      const map = {
        'ctrl-tgl-blind':     !!data.blind,
        'ctrl-tgl-peek':      !!data.peek,
        'ctrl-tgl-mute':      !!data.mute,
        'ctrl-tgl-censors':   !!data.censors,
        'ctrl-tgl-shortcuts': !!data.shortcuts,
        'ctrl-tgl-dock':      !!data.dock,
        'ctrl-tgl-info-start':!!data.info_start,
        'ctrl-tgl-info-end':  !!data.info_end,
        'ctrl-queue-blind':    !!data.queue_blind,
        'ctrl-queue-peek':     !!data.queue_peek,
        'ctrl-queue-mute-peek':!!data.queue_mute_peek,
      };
      for (const [id, active] of Object.entries(map)) {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('ctrl-toggle-active', active);
      }
      // Highlight active lightning round button (dice = variety)
      document.querySelectorAll('[data-lt-mode]').forEach(el => {
        el.classList.toggle('ctrl-toggle-active', el.dataset.ltMode === data.light_mode);
      });
      // Update lightning types list active row
      _ctrlLtCurrentMode = data.light_mode || null;
      if (_ctrlLtListOpen) _ctrlRenderLtList();
      // Show/hide server-controlled pinned proxies
      document.querySelectorAll('[data-proxy-extra="lt_stop"]').forEach(el => {
        el.style.display = '';
      });
      document.querySelectorAll('[data-proxy-extra="yt"]').forEach(el => {
        el.style.display = data.has_youtube ? '' : 'none';
      });
      document.querySelectorAll('[data-proxy-extra="fl"]').forEach(el => {
        el.style.display = data.has_fixed_lightning ? '' : 'none';
      });
      // Active state on tgl proxy buttons in main panel
      const tglProxyIds = {
        'tgl_blind': !!data.blind, 'tgl_peek': !!data.peek, 'tgl_mute': !!data.mute,
        'tgl_narrow': !!data.peek, 'tgl_widen': !!data.peek,
        'tgl_censors': !!data.censors, 'tgl_shortcuts': !!data.shortcuts, 'tgl_dock': !!data.dock,
        'tgl_info_start': !!data.info_start, 'tgl_info_end': !!data.info_end,
        'lt':      !!data.light_mode,
        'lt_stop': !!(data.light_mode || data.yt_queued || data.fl_queued || data.search_queued || data.fl_active),
        'lt_dice': data.light_mode === 'variety',
        'yt':      !!data.yt_queued,
        'fl':      !!data.fl_queued,
        'search':  !!data.search_queued,
        'end_session': !!data.end_session_popup,
        'scoreboard_open_close': !!data.scoreboard_open,
        'scoreboard_toggle': !!data.scoreboard_visible,
        'scoreboard_align': !!data.scoreboard_open,
        'scoreboard_extend': !!data.scoreboard_open,
        'scoreboard_grow': !!data.scoreboard_open,
        'scoreboard_shrink': !!data.scoreboard_open,
      };
      for (const [eid, active] of Object.entries(tglProxyIds)) {
        document.querySelectorAll(`[data-proxy-extra="${eid}"],[data-extra-id="${eid}"]`).forEach(el => el.classList.toggle('ctrl-toggle-active', active));
      }
      document.querySelectorAll('.ctrl-censor-count').forEach(el => {
        el.textContent = data.censor_count != null ? data.censor_count : 0;
      });
      // Update proxy state for extra toggle buttons in pinned area
      const tglProxyMap = {
        'tgl_censors': !!data.censors,
        'tgl_shortcuts': !!data.shortcuts,
        'tgl_dock': !!data.dock,
        'tgl_info_start': !!data.info_start,
        'tgl_info_end': !!data.info_end,
      };
      for (const [eid, active] of Object.entries(tglProxyMap)) {
        document.querySelectorAll(`[data-proxy-extra="${eid}"]`).forEach(el => el.classList.toggle('ctrl-toggle-active', active));
      }
      // Highlight Info Reveal buttons when their popup is currently showing
      const revealMap = {
        'rev_info':      !!data.info_popup,
        'rev_title':     !!data.title_popup,
        'reveal_artist': !!data.artist_popup,
        'reveal_studio': !!data.studio_popup,
        'reveal_season': !!data.season_popup,
        'reveal_year':   !!data.year_popup,
      };
      for (const [eid, active] of Object.entries(revealMap)) {
        document.querySelectorAll(`[data-extra-id="${eid}"],[data-proxy-extra="${eid}"]`).forEach(el =>
          el.classList.toggle('ctrl-reveal-active', active));
      }
      // Sync difficulty and auto-bonus state
      if (data.difficulty != null) {
        _ctrlDiffCurrent = data.difficulty;
        if (_ctrlDiffListOpen) _ctrlRenderDiffList();
      }
      if ('auto_bonus_start' in data) {
        _ctrlAutoBonusCurrent = data.auto_bonus_start || null;
        if (_ctrlAutoBonusListOpen) _ctrlRenderAutoBonusList();
        document.querySelectorAll('[data-proxy-extra="auto_bonus"]').forEach(el =>
          el.classList.toggle('ctrl-toggle-active', _ctrlAutoBonusCurrent != null));
        document.querySelectorAll('[data-extra-id="auto_bonus"]').forEach(el =>
          el.classList.toggle('ctrl-toggle-active', _ctrlAutoBonusCurrent != null));
      }
      const bonusToExtraId = {
        'multiple':   'b_multiple',
        'year':       'b_year',
        'score':      'b_score',
        'members':    'b_members',
        'popularity': 'b_rank',
        'tags':       'b_tags',
        'freeform':   'b_free',
        'studio':     'bonus_studio',
        'artist':     'bonus_artist',
        'song':       'bonus_song',
        'characters': 'bonus_chars',
        'buzzer':     'bonus_buzzer',
      };
      const activeBonusExtraId = bonusToExtraId[data.active_bonus || ''] || null;
      Object.values(bonusToExtraId).forEach(eid => {
        const active = (eid === activeBonusExtraId);
        document.querySelectorAll(`[data-extra-id="${eid}"],[data-proxy-extra="${eid}"]`).forEach(el =>
          el.classList.toggle('ctrl-bonus-active', active));
      });
    });

    const _CTRL_DEFAULT_PINNED = [
      'b_multiple','b_year','b_tags','b_members','_br_0',
      'tgl_blind','tgl_peek','tgl_narrow','tgl_widen','tgl_mute','_br_1',
      'rev_info','rev_title','mark_tag','mark_fav','_br_2',
      'tgl_censors','tgl_shortcuts','tgl_dock',
    ];
    let _ctrlPinnedExtras = new Set(_CTRL_DEFAULT_PINNED);
    let _ctrlExtrasEditMode = false;
    let _ctrlCurrentToggles = {};

    function _ctrlUpdateResetSessionButton(count) {
      const safeCount = Math.max(0, Number(count || 0));
      const active = safeCount > 0;
      const label = 'Reset Session [' + safeCount + ']';
      const title = safeCount > 0
        ? ('Reset the session history for ' + safeCount + ' theme' + (safeCount !== 1 ? 's' : '') + '.')
        : 'Reset the current session history.';
      document.querySelectorAll('[data-extra-id="reset_session_history"],[data-proxy-extra="reset_session_history"]').forEach(el => {
        el.innerHTML = label;
        el.title = title;
        el.classList.toggle('ctrl-toggle-active', active);
      });
      if (_ctrlExtrasConfig.reset_session_history) {
        _ctrlExtrasConfig.reset_session_history.html = label;
        _ctrlExtrasConfig.reset_session_history.title = title;
      }
    }

    const _ctrlExtrasConfig = {
      // Queue
      'lt_stop':      { classes: 'ctrl-toggle-btn ctrl-sect-queue',           html: '&#x23F9;',  title: 'Stop all queued rounds' },
      'lt':           { classes: 'ctrl-toggle-btn ctrl-sect-queue',           html: 'Lightning', title: 'Open lightning round type chooser' },

      'lt_dice':      { classes: 'ctrl-toggle-btn ctrl-sect-queue',           html: '&#x1F3B2;', title: 'Variety Lightning Round', ltMode: 'variety' },
      'yt':           { classes: 'ctrl-toggle-btn ctrl-sect-queue',           html: 'YouTube',   title: 'YouTube videos', serverCtrl: true },
      'fl':           { classes: 'ctrl-toggle-btn ctrl-sect-queue',           html: 'Fixed',     title: 'Fixed lightning rounds', serverCtrl: true },
      'search':       { classes: 'ctrl-toggle-btn ctrl-sect-queue',           html: '&#x1F50D;', title: 'Search themes' },
      'directory':    { classes: 'ctrl-toggle-btn ctrl-sect-queue',           html: '&#x1F4C2;', title: 'Browse directory (by artist, season, series…)' },
      // Bonus
      'b_multiple':   { classes: 'ctrl-sect-bonus',                           html: 'Multiple',  title: 'Multiple choice: guess the anime from 4 options' },
      'b_year':       { classes: 'ctrl-sect-bonus',                           html: 'Year',      title: 'Guess the year this anime first aired' },
      'b_tags':       { classes: 'ctrl-sect-bonus',                           html: 'Tags',      title: 'Guess the genres/themes/demographics tags' },
      'b_members':    { classes: 'ctrl-sect-bonus',                           html: 'Members',   title: 'Guess the number of MyAnimeList members' },
      'b_score':      { classes: 'ctrl-sect-bonus',                           html: 'Score',     title: 'Guess the MyAnimeList score (0.0–10.0)' },
      'b_rank':       { classes: 'ctrl-sect-bonus',                           html: 'Rank',      title: 'Guess the popularity rank on MyAnimeList' },
      'b_free':       { classes: 'ctrl-sect-bonus',                           html: 'Free',      title: 'Open a free-answer prompt' },
      'bonus_studio': { classes: 'ctrl-sect-bonus',                           html: 'Studio',    title: 'Guess the studio that made this anime' },
      'bonus_artist': { classes: 'ctrl-sect-bonus',                           html: 'Artist',    title: 'Guess the artist who performed the theme' },
      'bonus_song':   { classes: 'ctrl-sect-bonus',                           html: 'Song',      title: 'Guess the name of the song' },
      'bonus_chars':  { classes: 'ctrl-sect-bonus',                           html: 'Characters', title: 'Identify 2 characters from this anime out of 6 shown' },
      'bonus_buzzer': { classes: 'ctrl-sect-bonus',                           html: 'Buzzer',    title: 'Open a buzzer-only web bonus round' },
      'buzz_lock':    { classes: 'ctrl-toggle-btn ctrl-sect-bonus',           html: 'Buzz Lock', title: 'Toggle buzzer lock' },
      'buzz_reset':   { classes: 'ctrl-sect-bonus',                           html: 'Buzz Reset', title: 'Reset buzzer order' },
      'buzz_sound':   { classes: 'ctrl-sect-bonus',                           html: 'Buzz Sound', title: 'Choose buzzer sound preset' },
      'auto_bonus':   { classes: 'ctrl-toggle-btn ctrl-sect-bonus',           html: 'Auto Bonus', title: 'Automatically trigger a bonus round at the start of each theme' },
      // Toggles
      'difficulty':   { classes: 'ctrl-sect-toggle',                          html: 'Difficulty', title: 'Set playlist difficulty filter' },
      'tgl_fullscreen':{ classes: 'ctrl-sect-toggle',                         html: 'Fullscreen', title: 'Toggle VLC fullscreen mode' },
      'tgl_blind':    { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: 'Blind',     title: 'Toggle blind mode' },
      'tgl_peek':     { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: 'Peek',      title: 'Toggle peek (partial reveal)' },
      'tgl_narrow':   { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: '&#x25C0;',  title: 'Narrow peek window' },
      'tgl_widen':    { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: '&#x25B6;',  title: 'Widen peek window' },
      'tgl_mute':     { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: 'Mute',      title: 'Toggle mute' },
      'tgl_censors':  { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: 'Censors (<span class="ctrl-censor-count">0</span>)', title: 'Toggle censors' },
      'tgl_shortcuts':{ classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: 'Keys',      title: 'Toggle keyboard shortcuts' },
      'tgl_dock':     { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: 'Dock',      title: 'Toggle docked player' },
      'tgl_info_start':{ classes: 'ctrl-toggle-btn ctrl-sect-toggle',         html: 'Info Start', title: 'Toggle auto-show info at start' },
      'tgl_info_end': { classes: 'ctrl-toggle-btn ctrl-sect-toggle',          html: 'Info End',  title: 'Toggle auto-show info at end' },
      // Info Reveal
      'rev_info':     { classes: 'ctrl-sect-reveal',                          html: 'Show Information', title: 'Show full information about the current theme' },
      'rev_title':    { classes: 'ctrl-sect-reveal',                          html: 'Title',     title: 'Show anime title only' },
      'reveal_artist':{ classes: 'ctrl-sect-reveal',                          html: 'Artist',    title: 'Open artist info popup' },
      'reveal_studio':{ classes: 'ctrl-sect-reveal',                          html: 'Studio',    title: 'Open studio info popup' },
      'reveal_season':{ classes: 'ctrl-sect-reveal',                          html: 'Season',    title: 'Open season rankings popup' },
      'reveal_year':  { classes: 'ctrl-sect-reveal',                          html: 'Year',      title: 'Open year rankings popup' },
      // Marks
      'mark_tag':     { classes: 'ctrl-mark-btn ctrl-sect-mark',              html: '&#x2717;',  title: 'Tag' },
      'mark_fav':     { classes: 'ctrl-mark-btn ctrl-sect-mark',              html: '♥',         title: 'Favorite' },
      'mark_blind':   { classes: 'ctrl-mark-btn ctrl-sect-mark',              html: '&#x1F441;', title: 'Blind Mark' },
      'mark_peek':    { classes: 'ctrl-mark-btn ctrl-sect-mark',              html: '&#x1F440;', title: 'Peek Mark' },
      'mark_mute_peek':{ classes: 'ctrl-mark-btn ctrl-sect-mark',             html: '&#x1F507;', title: 'Mute Peek Mark' },
      // Session
      'reset_session_history': { classes: 'ctrl-sect-session',                html: 'Reset Session [0]', title: 'Clear the current session history' },
      'end_session':  { classes: 'ctrl-sect-session',                         html: 'End',       title: 'End the current session' },
      // Scoreboard actions (invoke menu commands in main app)
      'scoreboard_open_close': { classes: 'ctrl-sect-scoreboard',             html: 'Open/Close', title: 'Open or close the scoreboard window' },
      'scoreboard_toggle': { classes: 'ctrl-sect-scoreboard',                 html: 'Toggle',    title: 'Toggle scoreboard visibility on screen' },
      'scoreboard_align':  { classes: 'ctrl-sect-scoreboard',                 html: 'Align',     title: 'Flip scoreboard alignment (left/right)' },
      'scoreboard_extend': { classes: 'ctrl-sect-scoreboard',                 html: 'Extend',    title: 'Toggle extended scoreboard stats' },
      'scoreboard_grow':   { classes: 'ctrl-sect-scoreboard',                 html: 'Grow',      title: 'Increase scoreboard size' },
      'scoreboard_shrink': { classes: 'ctrl-sect-scoreboard',                 html: 'Shrink',    title: 'Decrease scoreboard size' },
    };

    const _ctrlExtraActions = {
      'lt':           () => { _ctrlCloseExtrasPopup(); _ctrlToggleLtList(); },
      'lt_stop':      () => socket.emit('host_action',{action:'stop_queues'}),
      'lt_dice':      () => { _ctrlCloseExtrasPopup(); socket.emit('host_action',{action:'invoke',id:'lightning_variety'}); },
      'yt':           () => { _ctrlCloseExtrasPopup(); _ctrlToggleYouTubeList(); },
      'fl':           () => { _ctrlCloseExtrasPopup(); _ctrlToggleFlList(); },
      'search':       () => { _ctrlCloseExtrasPopup(); _ctrlToggleSearchRow(); },
      'directory':    () => { _ctrlCloseExtrasPopup(); _ctrlToggleDirectoryList(); },
      'b_multiple':   () => { socket.emit('host_action',{action:'invoke',id:'bonus_multiple'}); },
      'b_year':       () => { socket.emit('host_action',{action:'invoke',id:'bonus_year'}); },
      'b_tags':       () => { socket.emit('host_action',{action:'invoke',id:'bonus_tags'}); },
      'b_members':    () => { socket.emit('host_action',{action:'invoke',id:'bonus_members'}); },
      'b_score':      () => { socket.emit('host_action',{action:'invoke',id:'bonus_score'}); },
      'b_rank':       () => { socket.emit('host_action',{action:'invoke',id:'bonus_rank'}); },
      'b_free':       () => { socket.emit('host_action',{action:'invoke',id:'bonus_freeform'}); },
      'bonus_studio': () => { socket.emit('host_action',{action:'invoke',id:'bonus_studio'}); _ctrlCloseExtrasPopup(); },
      'bonus_artist': () => { socket.emit('host_action',{action:'invoke',id:'bonus_artist'}); _ctrlCloseExtrasPopup(); },
      'bonus_song':   () => { socket.emit('host_action',{action:'invoke',id:'bonus_song'}); _ctrlCloseExtrasPopup(); },
      'bonus_chars':  () => { socket.emit('host_action',{action:'invoke',id:'bonus_chars'}); _ctrlCloseExtrasPopup(); },
      'bonus_buzzer': () => { socket.emit('host_action',{action:'invoke',id:'bonus_buzzer'}); _ctrlCloseExtrasPopup(); },
      'buzz_lock':    () => socket.emit('host_action',{action:'invoke',id:'buzzer_lock'}),
      'buzz_reset':   () => socket.emit('host_action',{action:'invoke',id:'buzzer_reset'}),
      'buzz_sound':   () => { _ctrlCloseExtrasPopup(); _ctrlToggleBuzzSoundList(); },
      'tgl_blind':    () => socket.emit('host_action',{action:'invoke',id:'blind'}),
      'tgl_peek':     () => socket.emit('host_action',{action:'invoke',id:'peek'}),
      'tgl_narrow':   () => socket.emit('host_action',{action:'invoke',id:'narrow_peek'}),
      'tgl_widen':    () => socket.emit('host_action',{action:'invoke',id:'widen_peek'}),
      'tgl_mute':     () => socket.emit('host_action',{action:'invoke',id:'mute'}),
      'tgl_censors':  () => socket.emit('host_action',{action:'invoke',id:'censors'}),
      'tgl_shortcuts':() => socket.emit('host_action',{action:'invoke',id:'enable_shortcuts'}),
      'tgl_dock':     () => socket.emit('host_action',{action:'invoke',id:'dock_player'}),
      'tgl_info_start':() => socket.emit('host_action',{action:'invoke',id:'auto_info_start'}),
      'tgl_info_end': () => socket.emit('host_action',{action:'invoke',id:'auto_info_end'}),
      'rev_info':     () => { socket.emit('host_action',{action:'invoke',id:'info_popup'}); _ctrlCloseExtrasPopup(); },
      'rev_title':    () => { socket.emit('host_action',{action:'invoke',id:'title_popup'}); _ctrlCloseExtrasPopup(); },
      'reveal_artist':() => { socket.emit('host_action',{action:'invoke',id:'artist_info'}); _ctrlCloseExtrasPopup(); },
      'reveal_studio':() => { socket.emit('host_action',{action:'invoke',id:'studio_info'}); _ctrlCloseExtrasPopup(); },
      'reveal_season':() => { socket.emit('host_action',{action:'invoke',id:'season_rankings'}); _ctrlCloseExtrasPopup(); },
      'reveal_year':  () => { socket.emit('host_action',{action:'invoke',id:'year_rankings'}); _ctrlCloseExtrasPopup(); },
      'mark_tag':     () => socket.emit('host_action',{action:'invoke',id:'tag'}),
      'mark_fav':     () => socket.emit('host_action',{action:'invoke',id:'favorite'}),
      'mark_blind':   () => socket.emit('host_action',{action:'invoke',id:'blind_mark'}),
      'mark_peek':    () => socket.emit('host_action',{action:'invoke',id:'peek_mark'}),
      'mark_mute_peek':() => socket.emit('host_action',{action:'invoke',id:'mute_peek_mark'}),
      'reset_session_history': () => {
        const count = Math.max(0, Number(((_ctrlCurrentToggles || {}).session_history_count) || 0));
        const msg = 'Reset the session history for ' + count + ' theme' + (count !== 1 ? 's' : '') + '?\n\nThis cannot be undone.';
        if (!window.confirm(msg)) return;
        socket.emit('host_action',{action:'reset_session_history'});
        _ctrlCloseExtrasPopup();
      },
      'end_session':  () => { socket.emit('host_action',{action:'invoke',id:'end_session'}); _ctrlCloseExtrasPopup(); },
      // Scoreboard actions — call main app menu registry via invoke
      'scoreboard_open_close': () => socket.emit('host_action',{action:'toggle_scoreboard'}),
      'scoreboard_toggle':      () => socket.emit('host_action',{action:'invoke', id:'scoreboard_toggle'}),
      'scoreboard_align':       () => socket.emit('host_action',{action:'invoke', id:'scoreboard_align'}),
      'scoreboard_extend':      () => socket.emit('host_action',{action:'invoke', id:'scoreboard_extend'}),
      'scoreboard_grow':        () => socket.emit('host_action',{action:'invoke', id:'scoreboard_grow'}),
      'scoreboard_shrink':      () => socket.emit('host_action',{action:'invoke', id:'scoreboard_shrink'}),
      'difficulty':   () => { _ctrlCloseExtrasPopup(); _ctrlToggleDiffList(); },
      'tgl_fullscreen':() => socket.emit('host_action',{action:'invoke',id:'fullscreen'}),
      'auto_bonus':   () => { _ctrlCloseExtrasPopup(); _ctrlToggleAutoBonusList(); },
    };

    function _ctrlSyncExtraTooltips() {
      document.querySelectorAll('[data-extra-id]').forEach(el => {
        const eid = el.dataset.extraId;
        const cfg = _ctrlExtrasConfig[eid];
        if (!cfg) return;
        if (cfg.title) el.title = cfg.title;
        else el.removeAttribute('title');
      });
    }

    function _ctrlExtraClick(eid) {
      if (_ctrlExtrasEditMode) { _ctrlToggleExtraPin(eid); return; }
      const action = _ctrlExtraActions[eid];
      if (action) action();
      const _bonusCloseIds = new Set(['b_multiple','b_year','b_tags','b_members','b_score','b_rank','b_free']);
      if (_bonusCloseIds.has(eid)) _ctrlCloseExtrasPopup();
    }

    function _ctrlExtraAction(eid) {
      const action = _ctrlExtraActions[eid];
      if (action) action();
    }

    function _ctrlToggleExtraPin(eid) {
      if (_ctrlPinnedExtras.has(eid)) {
        _ctrlPinnedExtras.delete(eid);
      } else {
        _ctrlPinnedExtras.add(eid);
      }
      // Update popup button highlight
      const popupBtn = document.querySelector(`[data-extra-id="${eid}"]`);
      if (popupBtn) popupBtn.classList.toggle('ctrl-extra-pinned', _ctrlPinnedExtras.has(eid));
      _ctrlRenderPinnedExtras();
      _ctrlSavePanels();
    }

    function _ctrlRenderPinnedExtras() {
      const container = document.getElementById('ctrl-pinned-extras');
      if (!container) return;
      container.innerHTML = '';
      _ctrlPinnedExtras.forEach(eid => {
        if (typeof eid !== 'string') return;
        if (eid.startsWith('_br_')) {
          const el = document.createElement('div');
          el.className = 'ctrl-pinned-break';
          el.setAttribute('data-layout-id', eid);
          container.appendChild(el);
          return;
        }
        if (eid.startsWith('_sp_')) {
          const el = document.createElement('div');
          el.className = 'ctrl-pinned-space';
          el.setAttribute('data-layout-id', eid);
          container.appendChild(el);
          return;
        }
        const cfg = _ctrlExtrasConfig[eid];
        if (!cfg) return;
        const btn = document.createElement('button');
        btn.className = 'ctrl-bonus-btn ' + cfg.classes;
        btn.innerHTML = cfg.html;
        if (cfg.title) btn.title = cfg.title;
        btn.setAttribute('data-proxy-extra', eid);
        if (cfg.ltMode) btn.setAttribute('data-lt-mode', cfg.ltMode);
        if (cfg.serverCtrl) btn.style.display = 'none'; // hidden until server update
        btn.onclick = () => _ctrlExtraAction(eid);
        container.appendChild(btn);
      });
      _ctrlRenderLayoutChips();
    }

    function _ctrlRenderLayoutChips() {
      const chips = document.getElementById('ctrl-extras-layout-chips');
      if (!chips) return;
      chips.innerHTML = '';
      _ctrlPinnedExtras.forEach(eid => {
        if (!eid.startsWith('_br_') && !eid.startsWith('_sp_')) return;
        const isBreak = eid.startsWith('_br_');
        const chip = document.createElement('span');
        chip.className = 'ctrl-layout-chip';
        chip.textContent = isBreak ? '↵ Break' : '□ Space';
        const rm = document.createElement('button');
        rm.className = 'ctrl-layout-chip-remove';
        rm.textContent = '×';
        rm.title = 'Remove';
        rm.onclick = () => _ctrlRemoveLayoutItem(eid);
        chip.appendChild(rm);
        chips.appendChild(chip);
      });
    }

    function _ctrlClearPinned() {
      _ctrlPinnedExtras.clear();
      document.querySelectorAll('[data-extra-id]').forEach(el => el.classList.remove('ctrl-extra-pinned'));
      _ctrlRenderPinnedExtras();
      _ctrlSavePanels();
    }

    function _ctrlResetPinned() {
      _ctrlPinnedExtras = new Set(_CTRL_DEFAULT_PINNED);
      // Re-mark pinned state in popup if still in edit mode
      document.querySelectorAll('[data-extra-id]').forEach(el => {
        el.classList.toggle('ctrl-extra-pinned', _ctrlPinnedExtras.has(el.dataset.extraId));
      });
      _ctrlRenderPinnedExtras();
      _ctrlSavePanels();
    }

    function _ctrlAddLayoutItem(type) {
      let idx = 0;
      while (_ctrlPinnedExtras.has('_' + type + '_' + idx)) idx++;
      _ctrlPinnedExtras.add('_' + type + '_' + idx);
      _ctrlRenderPinnedExtras();
      _ctrlSavePanels();
    }

    function _ctrlRemoveLayoutItem(eid) {
      _ctrlPinnedExtras.delete(eid);
      _ctrlRenderPinnedExtras();
      _ctrlSavePanels();
    }

    function _ctrlToggleExtrasEditMode() {
      _ctrlExtrasEditMode = !_ctrlExtrasEditMode;
      const box = document.getElementById('ctrl-extras-popup-box');
      if (box) box.classList.toggle('edit-mode', _ctrlExtrasEditMode);
      const editBtn = document.getElementById('ctrl-extras-edit-btn');
      if (editBtn) editBtn.classList.toggle('active', _ctrlExtrasEditMode);
      const hint = document.getElementById('ctrl-extras-edit-hint');
      if (hint) hint.classList.toggle('active', _ctrlExtrasEditMode);
      const layoutSect = document.getElementById('ctrl-extras-layout-sect');
      if (layoutSect) layoutSect.style.display = _ctrlExtrasEditMode ? '' : 'none';
      const editActions = document.getElementById('ctrl-extras-edit-actions');
      if (editActions) editActions.style.display = _ctrlExtrasEditMode ? 'flex' : 'none';
      if (_ctrlExtrasEditMode) {
        // Mark currently pinned buttons
        _ctrlPinnedExtras.forEach(eid => {
          const btn = document.querySelector(`[data-extra-id="${eid}"]`);
          if (btn) btn.classList.add('ctrl-extra-pinned');
        });
      } else {
        document.querySelectorAll('[data-extra-id]').forEach(el => el.classList.remove('ctrl-extra-pinned'));
      }
    }

    function _ctrlOpenExtrasPopup() {
      _ctrlSyncExtraTooltips();
      document.getElementById('ctrl-extras-popup-overlay').classList.add('active');
    }
    function _ctrlCloseExtrasPopup() {
      // Exit edit mode when closing
      if (_ctrlExtrasEditMode) _ctrlToggleExtrasEditMode();
      document.getElementById('ctrl-extras-popup-overlay').classList.remove('active');
    }

    function _ctrlApplyMarks(marks) {
      // Update popup buttons (by ID) and all proxies (by data-proxy-extra)
      const markMap = {
        'mark_tag':      !!marks.tagged,
        'mark_fav':      !!marks.favorited,
        'mark_blind':    !!marks.blind,
        'mark_peek':     !!marks.peek,
        'mark_mute_peek':!!marks.mute_peek,
      };
      const idMap = {
        'mark_tag': 'ctrl-mark-tag', 'mark_fav': 'ctrl-mark-fav',
        'mark_blind': 'ctrl-mark-blind', 'mark_peek': 'ctrl-mark-peek',
        'mark_mute_peek': 'ctrl-mark-mute-peek',
      };
      for (const [eid, active] of Object.entries(markMap)) {
        const el = document.getElementById(idMap[eid]);
        if (el) el.classList.toggle('ctrl-mark-active', active);
        document.querySelectorAll(`[data-proxy-extra="${eid}"]`).forEach(el => el.classList.toggle('ctrl-mark-active', active));
      }
    }

    socket.on('marks_update', data => { _ctrlApplyMarks(data); });

    function _ctrlRenderUpNext(d) {
      const modeEl     = document.getElementById('ctrl-upnext-mode');
      const titleText  = document.getElementById('ctrl-upnext-title-text');
      const detailEl   = document.getElementById('ctrl-upnext-detail');
      const rerollBtn  = document.getElementById('ctrl-upnext-reroll');
      if (!d || !d.title) {
        if (titleText) titleText.textContent = d && d.end_of_playlist ? 'End of playlist' : 'No upcoming track';
        if (modeEl)    modeEl.textContent    = '';
        if (detailEl)  detailEl.textContent  = '';
        if (rerollBtn) rerollBtn.style.display = 'none';
        return;
      }
      if (modeEl)    modeEl.textContent    = d.mode_label || '';
      if (titleText) titleText.textContent = (d.marks || '') + (d.title || '');
      if (detailEl)  detailEl.textContent  = d.detail || '';
      if (rerollBtn) rerollBtn.style.display = d.reroll ? '' : 'none';
    }

    socket.on('up_next_update', data => {
      _ctrlRenderUpNext(data);
      if (_ctrlPlaylistVisible) {
        socket.emit('host_action', { action: 'get_playlist_info' });
      }
    });

    function _ctrlToggleVolume() {
      _ctrlVolOpen = !_ctrlVolOpen;
      const wrap = document.getElementById('ctrl-vol-slider-wrap');
      if (wrap) wrap.style.display = _ctrlVolOpen ? 'flex' : 'none';
      if (_ctrlVolOpen) {
        setTimeout(() => {
          function _volDismiss(e) {
            const vw = document.getElementById('ctrl-vol-wrap');
            if (vw && !vw.contains(e.target)) {
              _ctrlVolOpen = false;
              const w = document.getElementById('ctrl-vol-slider-wrap');
              if (w) w.style.display = 'none';
              document.removeEventListener('pointerdown', _volDismiss, true);
            }
          }
          document.addEventListener('pointerdown', _volDismiss, true);
        }, 0);
      }
    }

    function _ctrlVolumeChange(val) {
      const lbl = document.getElementById('ctrl-vol-label');
      if (lbl) lbl.textContent = val;
      socket.emit('host_action', { action: 'set_volume', volume: parseInt(val, 10) });
    }

    let _ctrlBzzPct = 100; // BZZ (buzz sound_volume) as percentage (0-150)
    function _ctrlBzzRender() {
      const sl = document.getElementById('ctrl-bzz-slider');
      const lb = document.getElementById('ctrl-bzz-label');
      if (sl) sl.value = _ctrlBzzPct;
      if (lb) lb.textContent = _ctrlBzzPct + '%';
    }
    function _ctrlBzzChange(val) {
      _ctrlBzzPct = Math.max(0, Math.min(150, Math.round(parseFloat(val) || 0)));
      const lb = document.getElementById('ctrl-bzz-label');
      if (lb) lb.textContent = _ctrlBzzPct + '%';
      socket.emit('host_action', { action: 'set_bzz_modifier', modifier: _ctrlBzzPct / 100 });
    }

    let _ctrlBgmPct = 100; // BGM modifier as percentage (0-150)
    function _ctrlBgmRender() {
      const sl = document.getElementById('ctrl-bgm-slider');
      const lb = document.getElementById('ctrl-bgm-label');
      if (sl) sl.value = _ctrlBgmPct;
      if (lb) lb.textContent = _ctrlBgmPct + '%';
    }
    function _ctrlBgmChange(val) {
      _ctrlBgmPct = Math.max(0, Math.min(150, Math.round(parseFloat(val) || 0)));
      const lb = document.getElementById('ctrl-bgm-label');
      if (lb) lb.textContent = _ctrlBgmPct + '%';
      socket.emit('host_action', { action: 'set_bgm_modifier', modifier: _ctrlBgmPct / 100 });
    }

    function _ctrlAction(id) {
      socket.emit('host_action', { action: 'invoke', id });
    }

    function _ctrlSeekPreview(val) {
      _ctrlSeeking = true;
      if (_ctrlLengthMs > 0) {
        const previewMs = Math.round((val / 1000) * _ctrlLengthMs);
        const cur = document.getElementById('ctrl-time-cur');
        if (cur) cur.textContent = _fmtMs(previewMs);
      }
    }

    function _ctrlSeekCommit(val) {
      _ctrlSeeking = false;
      if (_ctrlLengthMs > 0) {
        const seekMs = Math.round((val / 1000) * _ctrlLengthMs);
        socket.emit('host_action', { action: 'seek', position_ms: seekMs });
      }
    }

    function _metaViewData() {
      return _metaHistory.length > 0 ? _metaHistory[_metaHistory.length - 1 - _metaHistoryIdx] : _currentMetadata;
    }
    function _toggleMetadata() {
      _metadataOpen = !_metadataOpen;
      document.getElementById('metadata-overlay').classList.toggle('active', _metadataOpen);
      document.body.classList.toggle('meta-open', _metadataOpen);
      if (_metadataOpen) {
        _renderMetadata(_currentMetadata);
        _renderSeriesThemes(_currentMetadata);
        if (_metadataTab === 'more') _renderMore(_currentMetadata);
      }
      _saveSidePanels();
    }
    function _closeMetadata() {
      _metadataOpen = false;
      document.getElementById('metadata-overlay').classList.remove('active');
      document.body.classList.remove('meta-open');
      _closeMetaCover();
      _closeThemeActionPrompt();
      _saveSidePanels();
    }
    function _switchMetadataTab(tab) {
      _metadataTab = tab;
      const allTabs = ['info', 'themes', 'more'];
      document.querySelectorAll('.meta-tab-btn').forEach((b, i) =>
        b.classList.toggle('active', allTabs[i] === tab));
      allTabs.forEach(t => {
        const el = document.getElementById('meta-pane-' + t);
        if (el) el.classList.toggle('active', t === tab);
      });
      _renderMetaCover(_metaViewData());
      if (tab === 'themes') { _renderSeriesThemes(_metaViewData()); _scrollToPlayingTheme(); }
      if (tab === 'more')   _renderMore(_metaViewData());
    }
    function _renderMetaCover(d) {
      const wrap = document.getElementById('meta-cover-wrap');
      const img = document.getElementById('meta-cover-img');
      if (!wrap || !img) return;
      const url = String((d && d.cover) || '').trim();
      _metaCoverUrl = url;
      if (!url || _metadataTab !== 'info') {
        wrap.classList.remove('active');
        if (!url) img.removeAttribute('src');
        _closeMetaCover();
        return;
      }
      wrap.classList.add('active');
      if (img.getAttribute('src') !== url) img.src = url;
    }
    function _openMetaCover() {
      if (!_metaCoverUrl) return;
      const overlay = document.getElementById('meta-cover-overlay');
      const img = document.getElementById('meta-cover-full');
      if (!overlay || !img) return;
      img.src = _metaCoverUrl;
      overlay.classList.add('active');
    }
    function _closeMetaCover() {
      const overlay = document.getElementById('meta-cover-overlay');
      if (!overlay) return;
      overlay.classList.remove('active');
    }
    function _scrollToPlayingTheme() {
      const pane = document.getElementById('meta-pane-themes');
      if (!pane || !pane.classList.contains('active')) return;
      const playingEl = pane.querySelector('.mt-theme.playing');
      if (playingEl) playingEl.scrollIntoView({ block: 'center' });
    }
    document.getElementById('metadata-overlay').addEventListener('click', e => {
      if (e.target === document.getElementById('metadata-overlay') && window.innerWidth < 900) _closeMetadata();
    });

    /* ── Playlist virtual scroll ── */
    const _PL_ROW_H  = 22;
    const _PL_CHUNK  = 100;
    let _plTotal        = 0;
    let _plCurrentIndex = -1;
    let _plCache        = new Map();  // chunkOffset → items[]
    let _plPending      = new Set();  // chunkOffsets in-flight
    let _plScrollBound  = false;

    function _plChunkOffset(i) {
      return Math.floor(i / _PL_CHUNK) * _PL_CHUNK;
    }

    const _plTruncCanvas = document.createElement('canvas');
    function _plSetMidTrunc(span) {
      const full = span.dataset.fullTitle || '';
      const avail = span.offsetWidth;
      if (avail < 20) { span.textContent = full; return; }
      const ctx = _plTruncCanvas.getContext('2d');
      const cs = window.getComputedStyle(span);
      ctx.font = cs.fontSize + ' ' + cs.fontFamily;
      if (ctx.measureText(full).width <= avail) { span.textContent = full; return; }
      const ellW = ctx.measureText('\u2026').width;
      const half = (avail - ellW) / 2;
      let s = 0, e = full.length - 1, head = '', tail = '';
      // grow head from left
      while (s < full.length && ctx.measureText(head + full[s]).width <= half) head += full[s++];
      // grow tail from right
      while (e >= s && ctx.measureText(full[e] + tail).width <= half) tail = full[e--] + tail;
      span.textContent = head + '\u2026' + tail;
    }
    function _plRefreshTrunc() {
      document.querySelectorAll('.pl-row-title[data-full-title]').forEach(_plSetMidTrunc);
    }

    let _plEntryPopupIndex = -1;
    function _openPlEntryPopup(index, label) {
      _plEntryPopupIndex = index;
      const title = document.getElementById('pl-entry-title');
      if (title) title.textContent = label || ('Entry #' + (index + 1));
      const overlay = document.getElementById('pl-entry-overlay');
      if (overlay) overlay.classList.add('active');
    }
    function _closePlEntryPopup() {
      _plEntryPopupIndex = -1;
      const overlay = document.getElementById('pl-entry-overlay');
      if (overlay) overlay.classList.remove('active');
    }
    function _plEntryRun(mode) {
      if (!_isHost || _plEntryPopupIndex < 0) return;
      if (mode === 'play') {
        socket.emit('host_action', { action: 'playlist_goto', index: _plEntryPopupIndex });
      } else if (mode === 'delete') {
        socket.emit('host_action', { action: 'playlist_delete', index: _plEntryPopupIndex });
      }
      _closePlEntryPopup();
    }

    function _plOpen() {
      const vs = document.getElementById('pl-vscroll');
      if (!vs) return;
      if (!_plScrollBound) {
        vs.addEventListener('scroll', () => { _plEnsureChunks(); _plRender(); }, { passive: true });
        _plScrollBound = true;
      }
      if (_plTotal === 0) {
        socket.emit('host_action', { action: 'get_playlist_info' });
      } else {
        _plScrollToCurrent();
        _plEnsureChunks();
        _plRender();
      }
    }

    socket.on('playlist_info', data => {
      _plTotal        = data.total || 0;
      _plCurrentIndex = (data.current_index != null) ? data.current_index : -1;
      _plCache.clear();
      _plPending.clear();
      const label = document.getElementById('ctrl-playlist-label');
      if (label) label.innerHTML = '&#x203A; ' + (data.label || 'Playlist');
      const counter = document.getElementById('ctrl-playlist-counter');
      if (counter) counter.textContent = data.counter || '';
      const spacer = document.getElementById('pl-spacer');
      if (spacer) spacer.style.height = (_plTotal * _PL_ROW_H) + 'px';
      if (_ctrlPlaylistVisible) {
        _plScrollToCurrent();
        _plEnsureChunks();
      }
    });

    socket.on('playlist_chunk', data => {
      const off   = data.offset;
      const items = data.items || [];
      _plPending.delete(off);
      _plCache.set(off, items);
      // Update current index from item flags
      for (const item of items) {
        if (item.current) { _plCurrentIndex = item.i; break; }
      }
      if (_ctrlPlaylistVisible) _plRender();
    });

    function _plScrollToCurrent() {
      if (_plCurrentIndex < 0 || _plTotal === 0) return;
      const vs = document.getElementById('pl-vscroll');
      if (!vs) return;
      const target = _plCurrentIndex * _PL_ROW_H - vs.clientHeight / 2 + _PL_ROW_H / 2;
      vs.scrollTop = Math.max(0, target);
    }

    function _plEnsureChunks() {
      const vs = document.getElementById('pl-vscroll');
      if (!vs || _plTotal === 0) return;
      const first = Math.max(0, Math.floor(vs.scrollTop / _PL_ROW_H) - _PL_CHUNK);
      const last  = Math.min(_plTotal - 1,
                    Math.ceil((vs.scrollTop + vs.clientHeight) / _PL_ROW_H) + _PL_CHUNK);
      for (let off = _plChunkOffset(first); off <= _plChunkOffset(last); off += _PL_CHUNK) {
        if (!_plCache.has(off) && !_plPending.has(off)) {
          _plPending.add(off);
          socket.emit('host_action', { action: 'get_playlist_chunk', offset: off, count: _PL_CHUNK });
        }
      }
    }

    function _plRender() {
      const vs     = document.getElementById('pl-vscroll');
      const spacer = document.getElementById('pl-spacer');
      if (!vs || !spacer || _plTotal === 0) return;
      const scrollTop = vs.scrollTop;
      const vpH       = vs.clientHeight;
      const BUF       = 6;  // rows of buffer beyond viewport
      const firstRow  = Math.max(0,          Math.floor(scrollTop / _PL_ROW_H) - BUF);
      const lastRow   = Math.min(_plTotal - 1, Math.ceil((scrollTop + vpH) / _PL_ROW_H) + BUF);

      // Index existing DOM rows
      const existing = new Map();
      for (const el of Array.from(spacer.children)) {
        const idx = parseInt(el.dataset.plI, 10);
        if (!isNaN(idx)) existing.set(idx, el);
      }
      // Remove out-of-range rows
      for (const [idx, el] of existing) {
        if (idx < firstRow || idx > lastRow) { spacer.removeChild(el); existing.delete(idx); }
      }
      // Add/update rows
      for (let i = firstRow; i <= lastRow; i++) {
        const off  = _plChunkOffset(i);
        const chunk = _plCache.get(off);
        const item  = chunk ? chunk[i - off] : null;
        let el = existing.get(i);
        if (!el) {
          el = document.createElement('div');
          el.className  = 'pl-row';
          el.dataset.plI = i;
          el.style.top  = (i * _PL_ROW_H) + 'px';
          el.innerHTML =
            '<span class="pl-row-num"></span>' +
            '<span class="pl-row-lightning"></span>' +
            '<span class="pl-row-slug"></span>' +
            '<span class="pl-row-title"></span>' +
            '<span class="pl-row-song"></span>';
          el.addEventListener('click', () => {
            _openPlEntryPopup(parseInt(el.dataset.plI, 10), el.querySelector('.pl-row-title') ? el.querySelector('.pl-row-title').textContent : '');
          });
          spacer.appendChild(el);
        }
        el.querySelector('.pl-row-num').textContent   = (i + 1);
        const _rawSlug = item ? (item.slug || '') : '';
        const _isL = _rawSlug.startsWith('[L]');
        el.querySelector('.pl-row-lightning').textContent = _isL ? '\u26A1' : '';
        el.querySelector('.pl-row-slug').textContent  = _isL ? _rawSlug.slice(4) : _rawSlug;
        const _titleSpan = el.querySelector('.pl-row-title');
        _titleSpan.dataset.fullTitle = item ? (item.title || '\u2026') : '\u2026';
        requestAnimationFrame(() => _plSetMidTrunc(_titleSpan));
        const _song   = item ? (item.song   || '') : '';
        const _artist = (item && i === _plCurrentIndex) ? (item.artist || '') : '';
        el.querySelector('.pl-row-song').textContent  = (_artist) ? (_song ? _song + ' \u00B7 ' + _artist : _artist) : _song;
        el.classList.toggle('pl-current', i === _plCurrentIndex);
        el.style.top = (i * _PL_ROW_H) + 'px';
      }
    }

    function _metaHistoryPush(d) {
      if (!d) return;
      const newTitle = d.eng_title || d.title || d.filename || '';
      if (!newTitle) return;
      const last = _metaHistory[_metaHistory.length - 1];
      const lastTitle = last ? (last.eng_title || last.title || last.filename || '') : '';
      const newSlug = d.current_theme && d.current_theme.slug;
      const lastSlug = last && last.current_theme && last.current_theme.slug;
      if (!last || lastTitle !== newTitle || (newSlug && newSlug !== lastSlug)) {
        _metaHistory.push(d);
        if (_metaHistory.length > 20) {
          _metaHistory.shift();
          // Oldest entry removed; keep user on same item (clamp to valid range)
          if (!_metaAutoFollow) _metaHistoryIdx = Math.max(0, _metaHistoryIdx - 1);
        } else if (!_metaAutoFollow) {
          // New entry appended; bump index so user stays on the same item
          _metaHistoryIdx++;
        }
      }
    }
    function _metaHistoryNav(dir) {
      const total = _metaHistory.length;
      if (total < 2) return;
      _metaHistoryIdx = Math.max(0, Math.min(total - 1, _metaHistoryIdx + dir));
      const viewData = _metaHistory[_metaHistory.length - 1 - _metaHistoryIdx];
      _renderMetadata(null);
      _renderSeriesThemes(viewData);
      if (_metadataTab === 'more') _renderMore(viewData);
    }
    function _metaHistorySkip(to) {
      const total = _metaHistory.length;
      if (total < 2) return;
      _metaHistoryIdx = (to === 'newest') ? 0 : total - 1;
      const viewData = _metaHistory[_metaHistory.length - 1 - _metaHistoryIdx];
      _renderMetadata(null);
      _renderSeriesThemes(viewData);
      if (_metadataTab === 'more') _renderMore(viewData);
    }
    function _metaToggleAutoFollow() {
      _metaAutoFollow = !_metaAutoFollow;
      const btn = document.getElementById('meta-nav-autofollow');
      if (btn) btn.classList.toggle('on', _metaAutoFollow);
      if (_metaAutoFollow) _metaHistorySkip('newest');
    }
    function _metaHistoryUpdateNav() {
      const total = _metaHistory.length;
      const arrows = document.getElementById('meta-nav-arrows');
      const titleEl = document.getElementById('meta-nav-title');
      if (arrows) arrows.classList.add('visible');
      const label = document.getElementById('meta-history-label');
      if (label) label.textContent = total > 0 ? ((total - _metaHistoryIdx) + ' / ' + total) : '0 / 0';
      const prev = document.getElementById('meta-history-prev');
      const next = document.getElementById('meta-history-next');
      const oldest = document.getElementById('meta-history-oldest');
      const newest = document.getElementById('meta-history-newest');
      if (prev) prev.disabled = (_metaHistoryIdx >= total - 1) || total <= 1;
      if (next) next.disabled = (_metaHistoryIdx <= 0) || total <= 1;
      if (oldest) oldest.disabled = (_metaHistoryIdx >= total - 1) || total <= 1;
      if (newest) newest.disabled = (_metaHistoryIdx <= 0) || total <= 1;
      const btn = document.getElementById('meta-nav-autofollow');
      if (btn) btn.classList.toggle('on', _metaAutoFollow);
      const viewData = _metaHistory.length > 0 ? _metaHistory[_metaHistory.length - 1 - _metaHistoryIdx] : (_currentMetadata || null);
      if (titleEl) titleEl.textContent = viewData ? (viewData.eng_title || viewData.title || viewData.filename || '') : '';
    }
    function _renderMetadata(d) {
      // null = navigate history; real data = render latest (history push handled by event handlers)
      if (d !== null) {
        if (_metaAutoFollow) {
          _metaHistoryIdx = 0;
        } else {
          // Auto-follow is off: update nav counters only, leave content untouched
          _metaHistoryUpdateNav();
          return;
        }
      }
      _metaHistoryUpdateNav();
      const viewData = _metaHistory.length > 0 ? _metaHistory[_metaHistory.length - 1 - _metaHistoryIdx] : d;
      d = viewData;
      _renderMetaCover(d);
      const box = document.getElementById('metadata-content');
      const themeHead = document.getElementById('meta-theme-head');
      if (!d || !d.title) {
        if (themeHead) themeHead.innerHTML = '';
        box.innerHTML = '<span style="color:#555">No metadata available.</span>';
        return;
      }
      const lines = [];
      let themeHeadHtml = '';
      function favMarkHtml(isFavorite, extraCls) {
        if (!isFavorite) return '';
        return '<span class="mt-fav-mark' + (extraCls ? (' ' + extraCls) : '') + '" title="Favorite">♥</span>';
      }
      function line(label, value) {
        if (value == null || value === '' || value === 'N/A') return;
        lines.push('<div class="meta-row"><span class="meta-label">' + _escHtml(label) + '</span> ' + _escHtml(String(value)) + '</div>');
      }
      if (!d.is_game && d.current_theme && d.current_theme.slug) {
        const ct = d.current_theme;
        const slugLabel = ct.slug + (ct.overall_suffix || '');
        const slugCls = 'mt-slug playing';
        const titleText = ': ' + (ct.title || '????');
        const favHtml = favMarkHtml(!!ct.favorited, 'leading playing');
        let html = '<div class="meta-row"><span class="meta-label">THEME:</span></div>' +
          '<div class="meta-row meta-theme-row"><span class="mt-theme-content">' + favHtml + '<span class="' + slugCls + '">' + _escHtml(slugLabel) + '</span>' +
          '<span class="mt-title">' + _escHtml(titleText) + '</span>';
        if (ct.artists && ct.artists.length) {
          const artistsDisplay = ct.artists.map((a) => {
            const hasThemes = ct.artist_themes && ct.artist_themes[a] && ct.artist_themes[a].themes && ct.artist_themes[a].themes.length > 0;
            if (hasThemes) {
              const count = Number(ct.artist_themes[a].theme_count || 0);
              return '<span class="mt-artist-item"><span class="mt-artist-name">' + _escHtml(a) + '</span><button class="artist-themes-btn" data-artist="' + _escHtml(a) + '">' + count + '</button></span>';
            } else {
              return '<span class="mt-artist-item">' + _escHtml(a) + '</span>';
            }
          }).join(', ');
          html += '<span class="mt-artist mt-continuation">by: ' + artistsDisplay + '</span>';
        }
        let vText = ct.version ? 'v' + ct.version : '';
        if (ct.episodes) vText += (vText ? ': ' : '') + '(Eps: ' + ct.episodes + ')';
        if (ct.flags && ct.flags.length) vText += (vText ? ' ' : '') + ct.flags.join(' ');
        const propsHtml = ct.file_props ? ' <span class="mt-props">' + _escHtml(ct.file_props) + '</span>' : '';
        if (vText || propsHtml)
          html += '<span class="mt-ver playing mt-continuation">' + _escHtml(vText) + propsHtml + '</span>';
        html += '</span></div>';
        themeHeadHtml = html;
      }
      if (themeHead) {
        themeHead.innerHTML = themeHeadHtml || '<span style="color:#555">No theme info.</span>';
      }
      line('TITLE:', d.title);
      line('ENGLISH:', d.eng_title);
      if (d.synonyms && d.synonyms.length) line('SYNONYMS:', d.synonyms.join(', '));
      if (d.is_game) {
        line('RELEASE DATE:', d.release);
      } else {
        const airParts = [d.aired, d.season].filter(Boolean);
        if (airParts.length) line('AIR:', airParts.join(', '));
      }
      if (d.score != null) {
        let scoreVal = String(d.score);
        if (d.rank) scoreVal += ' (#' + d.rank + ')';
        if (!d.is_game && d.members != null)
          scoreVal += '&nbsp;&nbsp;<span class="meta-label">MEMBERS:</span> ' + Number(d.members).toLocaleString() + ' (#' + (d.popularity || 'N/A') + ')';
        lines.push('<div class="meta-row"><span class="meta-label">SCORE:</span> ' + scoreVal + '</div>');
      } else if (!d.is_game && d.members != null) {
        line('MEMBERS:', Number(d.members).toLocaleString() + ' (#' + (d.popularity || 'N/A') + ')');
      }
      if (d.is_game) {
        if (d.reviews != null) line('REVIEWS:', Number(d.reviews || 0).toLocaleString() + ' (#' + (d.popularity || 'N/A') + ')');
      }
      if (d.anilist_score) line('ANILIST SCORE:', d.anilist_score);
      if (d.anilist_popularity != null) {
        const popStr = Number(d.anilist_popularity).toLocaleString() +
          (d.anilist_popularity_ranks && d.anilist_popularity_ranks.length
            ? ' (' + d.anilist_popularity_ranks.join(' / ') + ')' : '');
        line('ANILIST MEMBERS:', popStr);
      }
      if (d.is_game) {
        if (d.platforms && d.platforms.length) line('PLATFORMS:', d.platforms.join(', '));
        line('TYPE:', d.format);
      } else {
        let epsVal = (d.episodes || 'Airing');
        if (d.format) epsVal += '&nbsp;&nbsp;<span class="meta-label">TYPE:</span> ' + _escHtml(String(d.format));
        if (d.source) epsVal += '&nbsp;&nbsp;<span class="meta-label">SOURCE:</span> ' + _escHtml(String(d.source));
        lines.push('<div class="meta-row"><span class="meta-label">EPISODES:</span> ' + epsVal + '</div>');
      }
      if (d.tags && d.tags.length) line('TAGS:', d.tags.join(', '));
      if (d.studios && d.studios.length) {
        if (d.current_theme && d.current_theme.studio_entries) {
          const studiosDisplay = d.studios.map((s) => {
            const hasEntries = d.current_theme.studio_entries[s] && d.current_theme.studio_entries[s].entries && d.current_theme.studio_entries[s].entries.length > 0;
            if (hasEntries) {
              const count = Number(d.current_theme.studio_entries[s].entry_count || 0);
              return '<span class="mt-artist-item"><span class="mt-artist-name">' + _escHtml(s) + '</span><button class="studio-themes-btn" data-studio="' + _escHtml(s) + '">' + count + '</button></span>';
            }
            return '<span class="mt-artist-item">' + _escHtml(s) + '</span>';
          }).join(', ');
          lines.push('<div class="meta-row"><span class="meta-label">STUDIOS:</span> ' + studiosDisplay + '</div>');
        } else {
          line('STUDIOS:', d.studios.join(', '));
        }
      }
      if (d.series) {
        const seriesStr = Array.isArray(d.series) ? d.series.join(', ') : String(d.series);
        line('SERIES:', seriesStr);
      }
      if (d.file_count != null) line('TOTAL PLAYS:', d.file_count + (d.themes_ago || ''));
      box.innerHTML = lines.join('') || '<span style="color:#555">No data.</span>';
      
      // Attach event listeners to artist themes buttons
      const artistBtns = document.querySelectorAll('#meta-pane-info .artist-themes-btn');
      if (artistBtns && d.current_theme && d.current_theme.artist_themes) {
        artistBtns.forEach(btn => {
          btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const artistName = this.getAttribute('data-artist');
            const artistData = d.current_theme.artist_themes[artistName];
            if (artistData) {
              _showArtistThemesDialog(artistName, artistData);
            }
          });
        });
      }
      const studioBtns = document.querySelectorAll('#meta-pane-info .studio-themes-btn');
      if (studioBtns && d.current_theme && d.current_theme.studio_entries) {
        studioBtns.forEach(btn => {
          btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const studioName = this.getAttribute('data-studio');
            const studioData = d.current_theme.studio_entries[studioName];
            if (studioData) _showStudioEntriesDialog(studioName, studioData);
          });
        });
      }
    }

    function _themeSlugSortCmp(a, b) {
      const sA = String(a || '').toUpperCase().trim();
      const sB = String(b || '').toUpperCase().trim();
      const mA = sA.match(/^([A-Z]+)\s*(\d+)?/);
      const mB = sB.match(/^([A-Z]+)\s*(\d+)?/);
      const pA = mA ? mA[1] : sA;
      const pB = mB ? mB[1] : sB;
      const nA = mA && mA[2] ? Number(mA[2]) : 0;
      const nB = mB && mB[2] ? Number(mB[2]) : 0;
      const gA = pA.startsWith('OP') ? 0 : (pA.startsWith('ED') ? 1 : 2);
      const gB = pB.startsWith('OP') ? 0 : (pB.startsWith('ED') ? 1 : 2);
      if (gA !== gB) return gA - gB;
      if (nA !== nB) return nA - nB;
      return sA.localeCompare(sB);
    }

    function _showThemesDialog(titleText, data, emptyText) {
      const overlay = document.getElementById('artist-themes-overlay');
      const title = document.getElementById('artist-themes-title');
      const content = document.getElementById('artist-themes-content');
      if (!overlay || !title || !content) return;

      title.textContent = titleText || 'All themes';

      if (!data || !data.themes || !data.themes.length) {
        content.innerHTML = '<div class="artist-themes-empty">' + _escHtml(emptyText || 'No themes found.') + '</div>';
      } else {
        const animeCount = Number(data.total_count || data.themes.length || 0);
        const themeCount = Number(data.theme_count || 0);
        const summary = '<div class="artist-themes-summary">' + animeCount + ' anime \u2022 ' + themeCount + ' themes</div>';
        const rows = data.themes.map(item => {
          const rawTitle = (item && item.anime_title) ? item.anime_title : 'Unknown Title';
          const animeTitle = _escHtml(rawTitle);
          const slugs = (item && item.themes && item.themes.length)
            ? item.themes.map(s => {
                const slugStr = (s && typeof s === 'object') ? String(s.slug || '') : String(s || '');
                const fn = (s && typeof s === 'object') ? String(s.filename || '') : '';
                if (_isHost && fn) {
                  const aid = _themeActionRegister(fn, rawTitle + ' \u2013 ' + slugStr);
                  return '<button class="artist-theme-chip artist-theme-play-btn" data-taid="' + aid + '" title="Theme actions: ' + _escHtml(slugStr) + '">' + _escHtml(slugStr) + '</button>';
                }
                return '<span class="artist-theme-chip">' + _escHtml(slugStr) + '</span>';
              }).join('')
            : '<span class="artist-theme-chip">Unknown</span>';
          return '<div class="artist-theme-row">' +
            '<div class="artist-theme-title"><span>' + animeTitle + ':</span>' + slugs + '</div>' +
            '</div>';
        }).join('');
        content.innerHTML = summary + '<div class="artist-themes-list">' + rows + '</div>';
        if (_isHost) {
          content.querySelectorAll('.artist-theme-play-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
              e.preventDefault();
              e.stopPropagation();
              _openThemeActionPrompt(this.getAttribute('data-taid'));
            });
          });
        }
      }

      overlay.classList.add('active');
    }

    function _showArtistThemesDialog(artistName, artistData) {
      _showThemesDialog('All themes by ' + (artistName || 'artist'), artistData, 'No themes found.');
    }

    function _fmtStudioEntryHtml(rawEntry) {
      const text = String(rawEntry || 'Unknown Title');
      const m = text.match(/^(.*)\s\(((?:19|20)\d{2})\)$/);
      if (!m) return '<span>' + _escHtml(text) + '</span>';
      const name = _escHtml((m[1] || '').trim() || 'Unknown Title');
      const year = _escHtml(m[2]);
      return '<span>' + name + ' <span style="opacity:.62">(' + year + ')</span></span>';
    }

    function _showStudioEntriesDialog(studioName, studioData) {
      const overlay = document.getElementById('artist-themes-overlay');
      const title = document.getElementById('artist-themes-title');
      const content = document.getElementById('artist-themes-content');
      if (!overlay || !title || !content) return;

      title.textContent = 'All entries by ' + (studioName || 'studio');

      if (!studioData || !studioData.entries || !studioData.entries.length) {
        content.innerHTML = '<div class="artist-themes-empty">No entries found.</div>';
      } else {
        const total = Number(studioData.total_count || studioData.entries.length || 0);
        const groups = (studioData.series_groups && studioData.series_groups.length) ? studioData.series_groups : null;
        const groupCount = groups ? groups.length : 0;
        const summary = groups
          ? '<div class="artist-themes-summary">' + total + ' entries \u2022 ' + groupCount + ' series</div>'
          : '<div class="artist-themes-summary">' + total + ' entries</div>';

        let rows = '';
        if (groups) {
          rows = groups.map(g => {
            const gTitle = _escHtml(String(g.series || 'Unknown Series'));
            const gEntries = (g.entries && g.entries.length) ? g.entries : ['Unknown Title'];
            const showHeader = gEntries.length > 1;
            const entriesHtml = gEntries.map(e => {
              return '<div class="artist-theme-title">' + _fmtStudioEntryHtml(e) + '</div>';
            }).join('');
            return '<div class="artist-theme-row studio-series-group">' +
              (showHeader ? '<div class="studio-series-title">' + gTitle + '</div>' : '') +
              entriesHtml +
              '</div>';
          }).join('');
        } else {
          rows = studioData.entries.map(entry => {
            return '<div class="artist-theme-row"><div class="artist-theme-title">' + _fmtStudioEntryHtml(entry) + '</div></div>';
          }).join('');
        }
        content.innerHTML = summary + '<div class="artist-themes-list">' + rows + '</div>';
      }

      overlay.classList.add('active');
    }

    function _closeArtistThemesDialog() {
      const overlay = document.getElementById('artist-themes-overlay');
      if (overlay) overlay.classList.remove('active');
    }

    function _themeActionRegister(filename, label) {
      if (!filename) return '';
      const id = String(_themeActionSeq++);
      _themeActionMap[id] = { filename, label: label || '' };
      return id;
    }

    function _openThemeActionPrompt(actionId) {
      if (!_isHost) return;
      const payload = _themeActionMap[actionId];
      if (!payload || !payload.filename) return;
      _themeActionTarget = payload;
      const title = document.getElementById('theme-action-title');
      if (title) title.textContent = payload.label ? ('Theme actions: ' + payload.label) : 'Theme actions';
      const overlay = document.getElementById('theme-action-overlay');
      if (overlay) overlay.classList.add('active');
    }

    function _closeThemeActionPrompt() {
      _themeActionTarget = null;
      const overlay = document.getElementById('theme-action-overlay');
      if (overlay) overlay.classList.remove('active');
    }

    function _themeActionRun(mode) {
      if (!_isHost || !_themeActionTarget || !_themeActionTarget.filename) return;
      const fn = _themeActionTarget.filename;
      if (mode === 'play') {
        socket.emit('host_action', { action: 'play_theme_now', filename: fn });
      } else if (mode === 'queue') {
        socket.emit('host_action', { action: 'queue_theme_only', filename: fn });
      } else if (mode === 'add') {
        socket.emit('host_action', { action: 'add_theme', filename: fn });
      }
      _closeThemeActionPrompt();
    }

    function _renderSeriesThemes(d) {
      const box = document.getElementById('metadata-themes-content');
      if (!d || !d.series_themes || !d.series_themes.length) {
        box.innerHTML = '<span style="color:#555">No theme data available.</span>';
        return;
      }
      _themeActionTarget = null;
      const parts = [];
      const favMarkHtml = (isFavorite, extraCls='') => isFavorite
        ? '<span class="mt-fav-mark' + (extraCls ? (' ' + extraCls) : '') + '" title="Favorite">♥</span>'
        : '';
      d.series_themes.forEach(anime => {
        if (d.series_themes.length > 1) {
          const fmtSeason = [anime.format, anime.season].filter(Boolean).join(' / ');
          parts.push('<div class="mt-anime-header">' + _escHtml(anime.title) +
            (fmtSeason ? ' <span style="opacity:.6">[' + _escHtml(fmtSeason) + ']</span>' : '') + '</div>');
        }
        anime.sections.forEach(sec => {
          parts.push('<div class="mt-section-header">' + _escHtml(sec.header) + '</div>');
          sec.themes.forEach(theme => {
            const slugCls = 'mt-slug' + (theme.is_playing ? ' playing' : '');
            const slugText = theme.slug + (theme.overall_suffix || '');
            const titleText = ': ' + (theme.title ? theme.title : '????');
            const themeFilename = String(theme.filename || '').trim();
            const hasVersions = !!(theme.versions && theme.versions.length);
            const themeActionId = (_isHost && !hasVersions && themeFilename)
              ? _themeActionRegister(themeFilename, slugText)
              : '';
            let html = '<div class="mt-theme' + (theme.is_playing ? ' playing' : '') + '"><div class="mt-main-row"><span class="' + slugCls + '">' + _escHtml(slugText) + '</span>' +
              '<span class="mt-title">' + _escHtml(titleText) + '</span></div>';
            if (theme.artists && theme.artists.length) {
              let artistsHtml = _escHtml(theme.artists_str || theme.artists.join(', '));
              if (theme.is_playing && d.current_theme && d.current_theme.artist_themes) {
                artistsHtml = theme.artists.map((a) => {
                  const hasThemes = d.current_theme.artist_themes[a] && d.current_theme.artist_themes[a].themes && d.current_theme.artist_themes[a].themes.length > 0;
                  if (hasThemes) {
                    const count = Number(d.current_theme.artist_themes[a].theme_count || 0);
                    return '<span class="mt-artist-item"><span class="mt-artist-name">' + _escHtml(a) + '</span><button class="artist-themes-btn" data-artist="' + _escHtml(a) + '">' + count + '</button></span>';
                  }
                  return '<span class="mt-artist-item">' + _escHtml(a) + '</span>';
                }).join(', ');
              }
              html += '<div class="mt-artist">by: ' + artistsHtml + '</div>';
            }
            if (theme.versions && theme.versions.length) {
              theme.versions.forEach(v => {
                const vCls = 'mt-ver' + (v.is_playing ? ' playing' : '');
                const subRowClass = _isHost ? 'mt-sub-row' : 'mt-sub-row mt-sub-row-indent';
                let vText = v.version ? 'v' + v.version : '';
                if (v.episodes) vText += (vText ? ': ' : '') + '(Eps: ' + v.episodes + ')';
                if (v.flags && v.flags.length) vText += (vText ? ' ' : '') + v.flags.join(' ');
                const propsHtml = v.file_props ? ' <span class="mt-props">' + _escHtml(v.file_props) + '</span>' : '';
                const vFilename = String(v.filename || '').trim();
                const vActionId = (_isHost && vFilename)
                  ? _themeActionRegister(vFilename, (slugText + (vText ? ' ' + vText : '')))
                  : '';
                const vActionBtn = vActionId
                  ? '<button class="mt-action-btn" data-taid="' + vActionId + '" title="Theme actions">&#9654;</button>'
                  : '';
                const vFavHtml = favMarkHtml(!!v.favorited, (v.is_playing ? 'leading playing' : 'leading'));
                if (vText || propsHtml || vActionBtn || vFavHtml)
                  html += '<div class="' + subRowClass + '">' + vActionBtn + vFavHtml + '<span class="' + vCls + '">' + _escHtml(vText) + propsHtml + '</span></div>';
              });
            } else {
              const subRowClass = _isHost ? 'mt-sub-row' : 'mt-sub-row mt-sub-row-indent';
              let vText = '';
              if (theme.episodes) vText += '(Eps: ' + theme.episodes + ')';
              if (theme.flags && theme.flags.length) vText += (vText ? ' ' : '') + theme.flags.join(' ');
              const tActionBtn = themeActionId
                ? '<button class="mt-action-btn" data-taid="' + themeActionId + '" title="Theme actions">&#9654;</button>'
                : '';
              const themeFavHtml = favMarkHtml(!!theme.favorited, theme.is_playing ? 'leading playing' : 'leading');
              if (vText || tActionBtn || themeFavHtml) html += '<div class="' + subRowClass + '">' + tActionBtn + themeFavHtml + '<span class="mt-ver">' + _escHtml(vText) + '</span></div>';
            }
            if (theme.special) html += ' <span class="mt-flags">(SPECIAL)</span>';
            html += '</div>';
            parts.push(html);
          });
        });
      });
      box.innerHTML = parts.join('');
      const artistBtns = box.querySelectorAll('.artist-themes-btn');
      if (artistBtns && d.current_theme && d.current_theme.artist_themes) {
        artistBtns.forEach(btn => {
          btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const artistName = this.getAttribute('data-artist');
            const artistData = d.current_theme.artist_themes[artistName];
            if (artistData) _showArtistThemesDialog(artistName, artistData);
          });
        });
      }
      box.querySelectorAll('.mt-action-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          _openThemeActionPrompt(this.getAttribute('data-taid'));
        });
      });
      _scrollToPlayingTheme();
    }

    let _moreSubTab = 'synopsis';
    let _moreShowSpoilers = false;
    let _moreCharTab = 'anidb';
    function _renderMore(d) {
      const box = document.getElementById('metadata-more-content');
      if (!box) return;
      if (!d || !d.title) {
        box.innerHTML = '<span style="color:#555">No metadata available.</span>';
        return;
      }
      const tabs = ['synopsis', 'tags', 'characters', 'episodes', 'links'];
      const labels = {'synopsis':'SYNOPSIS','tags':'TAGS','characters':'CHARS','episodes':'EPISODES','links':'LINKS'};
      const btns = tabs.map(t =>
        '<button class="more-sub-btn' + (_moreSubTab === t ? ' active' : '') +
        '" onclick="_switchMoreTab(\'' + t + '\')">' + (labels[t] || t.replace('_',' ').toUpperCase()) + '</button>'
      ).join('');
      box.innerHTML = '<div class="more-sub-tabs">' + btns + '</div>' +
        '<div id="more-sub-content">' + _buildMoreContent(d) + '</div>';
    }
    function _switchMoreTab(tab) {
      _moreSubTab = tab;
      _renderMore(_metaViewData());
    }
    function _switchCharTab(tab) {
      _moreCharTab = tab;
      _renderMore(_metaViewData());
    }
    function _toggleCharImg(id, url) {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.style.display !== 'none') {
        el.style.display = 'none';
      } else {
        const img = el.querySelector('img');
        if (img && !img.getAttribute('src')) img.src = url;
        el.style.display = 'block';
      }
    }
    function _buildMoreContent(d) {
      if (_moreSubTab === 'synopsis') {
        return d.synopsis
          ? '<div class="more-synopsis">' + _escHtml(d.synopsis) + '</div>'
          : '<span style="color:#555">No synopsis available.</span>';
      }
      if (_moreSubTab === 'tags') {
        let html = '';
        if (d.anidb_tags && d.anidb_tags.length) {
          html += '<div class="more-section-header">AniDB Tags</div>';
          html += d.anidb_tags.map(([name, score]) =>
            '<span class="more-tag">' + _escHtml(name.charAt(0).toUpperCase() + name.slice(1)) +
            (score > 0 ? ' <span style="opacity:.6">(' + score + ')</span>' : '') + '</span>'
          ).join('');
        }
        if (d.anilist_tags && d.anilist_tags.length) {
          const spoilerCount = d.anilist_tags.filter(t => t.spoiler).length;
          html += '<div class="more-section-header">AniList Tags';
          if (spoilerCount > 0)
            html += ' <button class="more-sub-btn" style="font-size:0.75em;padding:1px 6px" onclick="_moreShowSpoilers=!_moreShowSpoilers;_renderMore(_metaViewData())">' +
              (_moreShowSpoilers ? '🙈 Hide' : '👁 Show') + ' ' + spoilerCount + ' spoiler' + (spoilerCount !== 1 ? 's' : '') + '</button>';
          html += '</div>';
          html += d.anilist_tags.filter(t => !t.spoiler || _moreShowSpoilers).map(t =>
            '<span class="more-tag' + (t.spoiler ? ' spoiler' : '') + '" title="' +
            _escHtml(t.category || '') + '">' + _escHtml(t.name) +
            ' <span style="opacity:.6">(' + t.rank + '%)</span>' +
            (t.spoiler ? ' <span style="opacity:.5">[S]</span>' : '') + '</span>'
          ).join('');
        }
        return html || '<span style="color:#555">No tag data available.</span>';
      }
      if (_moreSubTab === 'characters') {
        const hasAnidb = d.anidb_characters && d.anidb_characters.length;
        const hasAnilist = d.anilist_characters && d.anilist_characters.length;
        if (!hasAnidb && !hasAnilist) return '<span style="color:#555">No character data available.</span>';
        // Inner tab bar
        let html = '<div class="more-char-tabs">';
        if (hasAnidb)   html += '<button class="more-char-tab-btn' + (_moreCharTab === 'anidb'   ? ' active' : '') + '" onclick="_switchCharTab(\'anidb\')">AniDB</button>';
        if (hasAnilist) html += '<button class="more-char-tab-btn' + (_moreCharTab === 'anilist' ? ' active' : '') + '" onclick="_switchCharTab(\'anilist\')">AniList</button>';
        html += '</div>';
        const activeTab = (hasAnidb && _moreCharTab === 'anidb') || !hasAnilist ? 'anidb' : 'anilist';
        if (activeTab === 'anidb') {
          [['m','Main'],['s','Supporting'],['','Appears']].forEach(([role, label]) => {
            const chars = d.anidb_characters.filter(c => c.role === role || (role === '' && c.role !== 'm' && c.role !== 's'));
            if (!chars.length) return;
            html += '<div style="color:#667;font-size:.78em;text-transform:uppercase;margin:4px 0 2px">' + label + '</div>';
            chars.sort((a,b) => a.name.localeCompare(b.name)).forEach((c, ci) => {
              const imgId = 'mcimg-adb-' + ci + '-' + c.name.replace(/[^a-z0-9]/gi,'');
              html += '<div class="more-char">';
              if (c.url) html += '<button class="more-sub-btn" style="float:right;font-size:0.75em;padding:1px 6px" onclick="_toggleCharImg(\'' + imgId + '\',\'' + _escHtml(c.url) + '\')">VIEW</button>';
              html += '<span class="more-char-name">' + _escHtml(c.name) + '</span>';
              if (c.gender) html += '<span class="more-char-role">' + _escHtml(c.gender) + '</span>';
              if (c.desc) html += '<div class="more-char-desc">' + _escHtml(c.desc.substring(0, 200) + (c.desc.length > 200 ? '…' : '')) + '</div>';
              if (c.url) html += '<div id="' + imgId + '" style="display:none;margin-top:4px"><img style="max-width:100%;border-radius:4px" referrerpolicy="no-referrer"></div>';
              html += '</div>';
            });
          });
        } else {
          [['MAIN','Main'],['SUPPORTING','Supporting'],['BACKGROUND','Background']].forEach(([role, label]) => {
            const chars = d.anilist_characters.filter(c => c.role === role);
            if (!chars.length) return;
            html += '<div style="color:#667;font-size:.78em;text-transform:uppercase;margin:4px 0 2px">' + label + '</div>';
            chars.forEach((c, ci) => {
              const imgId = 'mcimg-al-' + ci + '-' + c.name.replace(/[^a-z0-9]/gi,'');
              html += '<div class="more-char">';
              if (c.url) html += '<button class="more-sub-btn" style="float:right;font-size:0.75em;padding:1px 6px" onclick="_toggleCharImg(\'' + imgId + '\',\'' + _escHtml(c.url) + '\')">VIEW</button>';
              html += '<span class="more-char-name">' + _escHtml(c.name) + '</span>';
              if (c.gender || c.age) html += '<span class="more-char-role">' + _escHtml([c.gender, c.age ? 'Age ' + c.age : ''].filter(Boolean).join(', ')) + '</span>';
              if (c.vas && c.vas.length) html += '<div class="more-char-va">CV: ' + _escHtml(c.vas.join(', ')) + '</div>';
              if (c.desc) html += '<div class="more-char-desc">' + _escHtml(c.desc.substring(0, 200) + (c.desc.length > 200 ? '…' : '')) + '</div>';
              if (c.url) html += '<div id="' + imgId + '" style="display:none;margin-top:4px"><img style="max-width:100%;border-radius:4px" referrerpolicy="no-referrer"></div>';
              html += '</div>';
            });
          });
        }
        return html;
      }
      if (_moreSubTab === 'episodes') {
        if (!d.episode_info || !d.episode_info.length)
          return '<span style="color:#555">No episode data available.</span>';
        return d.episode_info.map(([num, title]) =>
          '<div class="more-ep"><span class="more-ep-num">EP ' + _escHtml(String(num)) + '</span>' + _escHtml(title) + '</div>'
        ).join('');
      }
      if (_moreSubTab === 'links') {
        const links = [];
        if (d.mal_id)
          links.push({ label: 'MyAnimeList', icon: '\ud83d\udd17', url: 'https://myanimelist.net/anime/' + d.mal_id });
        if (d.anidb_id)
          links.push({ label: 'AniDB', icon: '\ud83d\udd17', url: 'https://anidb.net/anime/' + d.anidb_id });
        if (d.anilist_id)
          links.push({ label: 'AniList', icon: '\ud83d\udd17', url: 'https://anilist.co/anime/' + d.anilist_id });
        if (d.animethemes_slug)
          links.push({ label: 'AnimeThemes', icon: '\ud83c\udfb5', url: 'https://animethemes.moe/anime/' + d.animethemes_slug });
        if (!links.length) return '<span style="color:#555">No links available.</span>';
        return links.map(l =>
          '<a class="meta-link-row" href="' + _escHtml(l.url) + '" target="_blank" rel="noopener noreferrer">' +
          '<span class="meta-link-icon">' + l.icon + '</span>' +
          '<span class="meta-link-label">' + _escHtml(l.label) + '</span>' +
          '<span class="meta-link-url">' + _escHtml(l.url) + '</span>' +
          '</a>'
        ).join('');
      }
      return '';
    }
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_titles_provider(fn):
    """Register a callable that returns a list of anime title strings for autocomplete."""
    global _titles_provider
    _titles_provider = fn


def set_player_names_provider(fn):
    """Register a callable that returns the current scoreboard player name list."""
    global _player_names_provider
    _player_names_provider = fn


def set_host_password(password: str):
    """Set the password that grants host-view access on the web client."""
    global _host_password
    _host_password = (password or '').strip()


def set_host_name(name: str):
    """Deprecated: use set_host_password instead."""
    set_host_password(name)


def flush_pending_selections():
    """Drain _pending_selections into _answer_queue and _submitted_answers without clearing other state.
    Call this before scoring so silent selections are included in the results.
    """
    global _pending_selections, _submitted_answers, _submitted_sids
    if not _pending_selections:
        return
    # Build reverse lookup: name → sid
    name_to_sid = {pname: sid for sid, pname in _connected_players.items()}
    already_submitted = {a['name'] for a in _submitted_answers}
    # Build sets of values already locked in by formal submissions so we can
    # skip auto-submitting duplicate answers on no-repeat question types.
    is_year  = _current_question and 'year'        in _current_question
    is_drum  = _current_question and 'drum'        in _current_question
    is_rank  = _current_question and 'rank_slider' in _current_question
    flush_taken_years  = set(_taken_years)   # claimed so far; grows within this flush
    flush_taken_scores = set(_taken_scores)
    flush_taken_ranks  = set(_taken_ranks)
    new_entries = []
    for name, answer in list(_pending_selections.items()):
        if name not in already_submitted:
            # For no-repeat question types, reject if the value is already taken.
            rejected = False
            if is_year:
                try:
                    yr = int(answer)
                    if yr in flush_taken_years:
                        rejected = True
                    else:
                        flush_taken_years.add(yr)
                except (ValueError, TypeError):
                    pass
            elif is_drum:
                try:
                    sc = float(answer)
                    if sc in flush_taken_scores:
                        rejected = True
                    else:
                        flush_taken_scores.add(sc)
                except (ValueError, TypeError):
                    pass
            elif is_rank:
                try:
                    rk = int(answer)
                    if rk in flush_taken_ranks:
                        rejected = True
                    else:
                        flush_taken_ranks.add(rk)
                except (ValueError, TypeError):
                    pass
            if rejected:
                continue  # don't queue or notify — UI stays unlocked
            entry = {'name': name, 'answer': answer}
            _answer_queue.put(entry)
            _submitted_answers.append(entry)
            new_entries.append(entry)
            # Mark their SID as submitted and tell their client
            player_sid = name_to_sid.get(name)
            if player_sid and _socketio:
                _submitted_sids.add(player_sid)
                _socketio.emit('auto_submitted', {'answer': answer}, to=player_sid)
    _pending_selections = {}
    if new_entries and _socketio:
        _broadcast_players_update()
        _emit_peer_answers_update()
        if _host_sids:
            for sid in list(_host_sids):
                _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)


def push_player_colors():
    """Read scoreboard_colors.json and broadcast player_colors_update to all clients."""
    if not FLASK_AVAILABLE or not _socketio:
        return
    merged = {}
    try:
        _sc_path = os.path.join(_SCOREBOARD_DATA, 'scoreboard_colors.json')
        if os.path.exists(_sc_path):
            with open(_sc_path, 'r', encoding='utf-8') as _f:
                merged.update(json.load(_f))
    except Exception:
        pass
    merged.update(_player_colors)
    _socketio.emit('player_colors_update', {'colors': merged})


def set_rules_text(header: str, body: str):
    """Set the rules header and body shown on the waiting screen between questions."""
    global _current_rules
    _current_rules = {'header': (header or '').strip(), 'body': (body or '').strip()}
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('rules_update', _current_rules)


def push_question(title, info='', choices=None, drum=None, stepper=None, tags=None, year=None, tags_max=None, autocomplete=None, rank_slider=None, buzzer_only=False):
    """Push a question to all connected browser clients.

    Args:
        title:       Short question text shown prominently.
        info:        Optional extra context shown below title (supports newlines).
        choices:     List of answer strings for multiple-choice. Pass None for other input types.
        drum:        Dict for drum-picker (score): {min, max, step, initial, decimals}.
        stepper:     Dict for stepper: {initial, min, max, steps: [{label, delta}, ...]}.
        tags:        List of tag strings for multi-select chip grid.
        tags_max:    Max number of tags a player may select (= number of correct tags).
        year:        Dict for year picker (decade+ones drums): {min, max, initial}.
        autocomplete: 'anime' to enable anime-title datalist on the free-text input.
        buzzer_only: If True, hides answer inputs and shows buzzer-only UI for this question.
    """
    global _current_question
    if not FLASK_AVAILABLE or _socketio is None:
        return
    import time as _time
    global _submitted_answers, _submitted_sids, _pending_selections
    _submitted_answers = []
    _submitted_sids = set()
    _pending_selections = {}
    _broadcast_players_update()
    # Notify scoreboard of all currently-connected players being served this question
    for _name in list(_connected_players.values()):
        if _name not in _shadow_kicked_players and _name not in _banned_names:
            _served_queue.put(_name)
    _current_question = {'title': title, 'info': info, 'choices': choices or [],
                         'qid': str(int(_time.time() * 1000))}
    if drum:
        global _taken_scores
        _taken_scores = set()
        _current_question['drum']         = drum
        _current_question['taken_scores'] = []
    if stepper:           _current_question['stepper']      = stepper
    if rank_slider:
        global _taken_ranks
        _taken_ranks = set()
        _current_question['rank_slider']   = rank_slider
        _current_question['taken_ranks']   = []
    if tags:              _current_question['tags']        = tags
    if tags_max:          _current_question['tags_max']    = tags_max
    if year:
        global _taken_years
        _taken_years = set()
        _current_question['year']        = year
        _current_question['taken_years'] = []
    if autocomplete:      _current_question['autocomplete'] = autocomplete
    if buzzer_only:       _current_question['buzzer_only'] = True

    # Reset buzzer each round.
    # Buzzer bonus starts unlocked; other questions keep buzzer closed.
    _reset_buzzer(open_after_reset=bool(buzzer_only))
    _socketio.emit('question', _current_question)
    _emit_buzzer_state()


def remove_answer_by_name(name: str):
    """Remove all submitted answers for the given player name and broadcast the update."""
    global _submitted_answers
    if not FLASK_AVAILABLE or _socketio is None:
        return
    _submitted_answers[:] = [a for a in _submitted_answers if a['name'] != name]
    _removal_queue.put(name)
    _broadcast_players_update()
    _emit_peer_answers_update()
    for sid in list(_host_sids):
        _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)


def reveal_answer(correct_display: str, q_type: str = '', correct_tags: list = None):
    """Broadcast the correct answer for the just-completed question to all clients."""
    if not FLASK_AVAILABLE or _socketio is None:
        return
    title = (_current_question or {}).get('title', '')
    _socketio.emit('answer_reveal', {
        'question': title,
        'correct': correct_display,
        'q_type': q_type,
        'correct_tags': correct_tags or [],
    })


def push_session_history(lines: list, filename: str = None):
    """Update the session history text served at /history and push to all clients."""
    global _session_lines, _session_filename
    _session_lines = list(lines)
    if filename:
        _session_filename = filename
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('session_history', {'text': '\n'.join(_session_lines), 'filename': _session_filename})


def clear_question():
    """Tell all clients to show the 'waiting' screen."""
    global _current_question, _submitted_answers, _submitted_sids, _pending_selections
    if not FLASK_AVAILABLE or _socketio is None:
        return
    # Inject unsubmitted selections as answers before clearing
    already_submitted = {a['name'] for a in _submitted_answers}
    for name, answer in list(_pending_selections.items()):
        if name not in already_submitted:
            _answer_queue.put({'name': name, 'answer': answer})
    _pending_selections = {}
    _current_question = None
    _reset_buzzer(open_after_reset=False)
    _submitted_answers = []
    _submitted_sids = set()
    _socketio.emit('clear', {'rules_header': _current_rules.get('header',''), 'rules_body': _current_rules.get('body','')})
    _emit_buzzer_state()
    _broadcast_players_update()
    set_info_public(False)


def get_answers():
    """Drain and return all pending answers as a list of {name, answer} dicts."""
    answers = []
    while True:
        try:
            answers.append(_answer_queue.get_nowait())
        except queue.Empty:
            break
    return answers


def get_served():
    """Drain and return player names who were just served the current question."""
    names = []
    while True:
        try:
            names.append(_served_queue.get_nowait())
        except queue.Empty:
            break
    return names


def get_removals():
    """Drain and return all names removed by the host via the web panel."""
    names = []
    while True:
        try:
            names.append(_removal_queue.get_nowait())
        except queue.Empty:
            break
    return names


def get_emojis():
    """Drain and return all pending emoji reactions as (name, emoji) tuples."""
    items = []
    while True:
        try:
            items.append(_emoji_queue.get_nowait())
        except queue.Empty:
            break
    return items


def push_timer(seconds: float, paused: bool = False):
    """Show/update a visual countdown timer on all connected client screens.

    The client counts down locally from `seconds`.  Call this again with the
    current remaining time to re-sync (e.g. on resume after a pause).
    Passing paused=True freezes the display at `seconds` without counting.
    Does not lock answers or reveal anything — purely visual.
    """
    global _timer_state
    _timer_state = {'seconds': max(0.0, float(seconds)), 'paused': bool(paused)}
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('timer_update', _timer_state)


def clear_timer():
    """Hide the countdown timer on all connected client screens."""
    global _timer_state
    _timer_state = {}
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('timer_clear', {})


def push_marks(marks: dict):
    """Push current theme mark states to all host clients.

    marks should contain boolean fields: tagged, favorited, blind, peek, mute_peek.
    """
    global _current_marks
    _current_marks = marks or {}
    if FLASK_AVAILABLE and _socketio and _host_sids:
        for sid in list(_host_sids):
            _socketio.emit('marks_update', _current_marks, to=sid)


def push_toggles(toggles: dict):
    """Push current toggle states to all host clients.

    toggles should contain: blind, peek, mute, censors, shortcuts, dock (bools) + censor_count (int).
    """
    global _current_toggles
    _current_toggles = toggles or {}
    if FLASK_AVAILABLE and _socketio and _host_sids:
        for sid in list(_host_sids):
            _socketio.emit('toggles_update', _current_toggles, to=sid)


def push_metadata(data_dict: dict):
    """Push currently-playing metadata to all connected host clients.

    data_dict should contain fields mirroring what update_metadata() renders in
    the left column (title, eng_title, aired, score, members, tags, studios, etc.).
    Pass an empty dict to clear the metadata panel.
    """
    global _current_metadata
    _current_metadata = data_dict or {}
    if FLASK_AVAILABLE and _socketio:
        for sid in list(_host_sids):
            _socketio.emit('metadata_update', _current_metadata, to=sid)
        if _info_public:
            _socketio.emit('info_public_update', {'show': True, 'metadata': _current_metadata})


def set_info_public(show: bool):
    """Show or hide the metadata button for all non-host clients."""
    global _info_public
    _info_public = show
    if not FLASK_AVAILABLE or _socketio is None:
        return
    if show:
        _socketio.emit('info_public_update', {'show': True, 'metadata': _current_metadata})
    else:
        _socketio.emit('info_public_update', {'show': False})


def push_youtube_list(videos: list, queued_id: str = None):
    """Push YouTube video list to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'videos': videos, 'queued_id': queued_id}
        for sid in list(_host_sids):
            _socketio.emit('youtube_list', payload, to=sid)


def push_fixed_lightning_list(rounds: list, queued_name: str = None):
    """Push fixed lightning round list to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'rounds': rounds, 'queued_name': queued_name}
        for sid in list(_host_sids):
            _socketio.emit('fixed_lightning_list', payload, to=sid)


def push_directory_groups(groups: list, stat_type: str, total: int, to_sid: str = None):
    """Push directory group list (e.g. all artists + counts) to host clients."""
    if FLASK_AVAILABLE and _socketio:
        payload = {'groups': groups, 'stat_type': stat_type, 'total': total}
        sids = [to_sid] if to_sid else list(_host_sids)
        for sid in sids:
            _socketio.emit('directory_groups', payload, to=sid)


def push_directory_themes(results: list, stat_type: str, group_label: str, to_sid: str = None):
    """Push the theme list for a directory group to host clients."""
    if FLASK_AVAILABLE and _socketio:
        payload = {'results': results, 'stat_type': stat_type, 'group_label': group_label}
        sids = [to_sid] if to_sid else list(_host_sids)
        for sid in sids:
            _socketio.emit('directory_themes', payload, to=sid)


def push_buzz_presets(presets: list, current_index: int, to_sid: str = None):
    """Push the list of buzzer sound presets (with current selection) to host clients."""
    if FLASK_AVAILABLE and _socketio:
        payload = {'presets': presets, 'current': current_index}
        sids = [to_sid] if to_sid else list(_host_sids)
        for sid in sids:
            _socketio.emit('buzz_presets', payload, to=sid)


def push_theme_search_results(results: list, playlist_infinite: bool = False, query: str = ""):
    """Push theme search results to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'results': results, 'playlist_infinite': bool(playlist_infinite), 'query': str(query or '')}
        for sid in list(_host_sids):
            _socketio.emit('theme_search_results', payload, to=sid)


def push_playlist_info(total: int, current_index: int, to_sid: str = None, counter: str = None, label: str = None):
    """Push playlist length + current position to requesting host client."""
    if FLASK_AVAILABLE and _socketio:
        payload = {'total': total, 'current_index': current_index}
        if counter is not None:
            payload['counter'] = counter
        if label is not None:
            payload['label'] = label
        sids = [to_sid] if to_sid else list(_host_sids)
        for sid in sids:
            _socketio.emit('playlist_info', payload, to=sid)


def push_playlist_chunk(offset: int, items: list, to_sid: str = None):
    """Push a chunk of playlist items to requesting host client."""
    if FLASK_AVAILABLE and _socketio:
        payload = {'offset': offset, 'items': items}
        sids = [to_sid] if to_sid else list(_host_sids)
        for sid in sids:
            _socketio.emit('playlist_chunk', payload, to=sid)


def push_up_next(data_dict: dict):
    """Push up-next track info to all host clients."""
    global _up_next
    _up_next = data_dict or {}
    if FLASK_AVAILABLE and _socketio and _host_sids:
        for sid in list(_host_sids):
            _socketio.emit('up_next_update', _up_next, to=sid)


def push_playback_state(current_ms: int, length_ms: int, playing: bool, volume: int = None, autoplay: int = None, bgm_modifier: float = None, bzz_modifier: float = None):
    """Push current playback position to all host clients (called ~1/sec from main app)."""
    global _playback_state
    _playback_state = {'current_ms': int(current_ms), 'length_ms': int(length_ms), 'playing': bool(playing)}
    if volume is not None:
        _playback_state['volume'] = int(volume)
    if autoplay is not None:
        _playback_state['autoplay'] = int(autoplay)
    if bgm_modifier is not None:
        _playback_state['bgm_modifier'] = float(bgm_modifier)
    if bzz_modifier is not None:
        _playback_state['bzz_modifier'] = float(bzz_modifier)
    if FLASK_AVAILABLE and _socketio and _host_sids:
        for sid in list(_host_sids):
            _socketio.emit('playback_state', _playback_state, to=sid)


def push_scores(data: dict):
    """Push scoreboard player data to all connected clients."""
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('scores_update', data)


def push_teams(names: list):
    """Push team name list to all connected clients (for autocomplete)."""
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('teams_update', {'teams': names})


def set_host_action_callback(fn):
    """Register a callable(action: str, data: dict) invoked when the host sends a remote control command."""
    global _host_action_callback
    _host_action_callback = fn


def set_buzz_callback(fn):
    """Register a callable(rank: int, name: str) invoked each time a player buzzes in."""
    global _on_buzz_callback
    _on_buzz_callback = fn


def start(port=8080, ngrok_domain=None):
    """Start the Flask/SocketIO server in a daemon thread, optionally launch ngrok.

    Returns True if server started, False if Flask is unavailable.
    Subsequent start() calls after stop() reuse the same thread and SocketIO
    instance to avoid the "address already in use" crash that would cause all
    server-to-client emits to silently fail.
    """
    global _server_started, _server_thread
    if not FLASK_AVAILABLE:
        return False
    # Only build and launch the server thread if it isn't already alive.
    # Killing and recreating the thread would leave the old Werkzeug server
    # holding port 8080 while the new _socketio has no active server, which
    # means every push_question / push_player_colors / etc. emit is silently
    # discarded.
    if _server_thread is None or not _server_thread.is_alive():
        _build_app()
        # Capture the freshly-built instances in local vars so the lambda
        # always runs against the correct pair even if globals change later.
        _cur_app = _app
        _cur_sio = _socketio
        t = threading.Thread(
            target=lambda: _cur_sio.run(
                _cur_app, host='0.0.0.0', port=port,
                allow_unsafe_werkzeug=True, log_output=False
            ),
            daemon=True
        )
        t.start()
        _server_thread = t
    _server_started = True
    if ngrok_domain:
        _start_ngrok(ngrok_domain, port)
    else:
        print(f"[Web Server] Running locally on port {port} (no ngrok domain set.)")
    return True


def stop():
    """Mark the server as stopped and clean up ngrok + ephemeral connection state.

    The underlying Flask/SocketIO/Werkzeug thread is intentionally left running
    so that the same _socketio instance stays alive. Killing it would leave the
    old thread holding port 8080 while the new _socketio (created in the next
    start() call) has no active server, causing all server-to-client emits to be
    silently discarded after restart.
    """
    global _ngrok_process, _server_started
    _server_started = False
    if _ngrok_process:
        try:
            _ngrok_process.terminate()
        except Exception:
            pass
        _ngrok_process = None
    # Clear ephemeral connection state so the next start() is fresh.
    global _connected_players, _host_sids, _submitted_sids
    try:
        _connected_players.clear()
    except Exception:
        _connected_players = {}
    try:
        _host_sids.clear()
    except Exception:
        _host_sids = set()
    try:
        _submitted_sids.clear()
    except Exception:
        _submitted_sids = set()
    _pending_selections.clear()
    _submitted_answers.clear()
    _taken_years.clear()
    _taken_scores.clear()
    _taken_ranks.clear()


def is_running():
    """Return True if the server has been started and not stopped."""
    return _server_started


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_app():
    global _app, _socketio
    _app = Flask(__name__)
    _app.config['SECRET_KEY'] = 'gta-web-server'
    # Try threading mode first (requires simple_websocket); fall back to the
    # default auto-detect if the threading backend isn't available in the bundle.
    try:
        _socketio = SocketIO(
            _app, cors_allowed_origins='*', async_mode='threading',
            logger=False, engineio_logger=False
        )
    except ValueError:
        _socketio = SocketIO(
            _app, cors_allowed_origins='*',
            logger=False, engineio_logger=False
        )
    # Silence engineio's "post request handler error" traceback that fires when
    # stale browser tabs (old Socket.IO clients) send malformed payloads on reconnect.
    logging.getLogger('engineio.server').setLevel(logging.CRITICAL)

    @_app.route('/')
    def index():
        return render_template_string(_HTML)

    @_app.route('/history')
    def history():
        lines = _session_lines
        if not lines:
            body = '<p style="color:#666;text-align:center;padding:40px">No session history yet.</p>'
        else:
            escaped = '\n'.join(
                '<span>' + line.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;') + '</span>'
                for line in lines
            )
            body = f'<pre id="history-text">{escaped}</pre>'
        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Session History</title>
<link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAIa0lEQVR42q1Xa3CU1Rl+zjnf7n67m91kNxdYQyDhpgFBmYQgYAhNFS1VBohB8QJ0YKpVpKVoodo2UxQVtVZmOt5ai0ORFkZrrWNlxEu9lijVVAiNFUokIIFwSYCQsN855+mPb0kR5TqemTPfzJ5z3ud9n/d9n3NW4PRDKcAYAEj2GgWTnnyhNuP7Wd0/ASQBYD+wb4dytn0i5TsIBV5EW9t7CoABMp9zH0oCQH7+pQOy4n+70w177zoO26UkHUUKQQKkUmx3HP7DcXi36+rzY/HXkJs7Xvo25LmCOxIAEok7bgtHuEdKH0wKTcAQsBqgBkjAZn7TBLhPSP4oHCZykj8XmUDOOnIFANmJBUtDLo8Z96SkAaj79KFevJh63Tqa99+nXrmS3pQp9AB6vkOagH4iFCKyE/fLs3TCpz03d/y8cJgEvDRgTYYB74oraNraeOKwJPXq1bSuSysl00JYAul7XJdI5E07YycIyLKyssBFWbGNXX6OtZWSFIK6qIimo6MH1LS10WzZQkuS6TRJ0lu2jARolaLOpKo6mvUFcs+PERDw52moz8ub+GQwRALaA0jHIQHqpUt9ZM+jfv116lSKJhCgd+uttNaSWtN0dtLk5/tsCUkCek0wSCTypmdYcE6KXpVZzI3Hf7dTSkvAMwApJS1Ab8MGGpKapFdR4RelELQATUODzwpJr7y8hwUC3n4hbHEs/jwA1J4iDYKAQF2dnBDJ2kS/mEzm60c0YgS7q6uZrqykdRxSSlIpGoBm0ybSWlpjqEtLMx0je2xMjUS3oawskEH/2jQIBQADB8bnuOE99FvMHu/AV6ZSPjN1dX4dkNRNTTSBgK8RQlAD1gK8JRRuQ//+2Sc68JV8xLuDToAnEQ8pAfF/52kMzAMPQC1cCEGCQoALFkB53vH6CeGrkU0ggf1fsnCCeQICa6BuCLutp2TAzy29+fMz7WBoDh+mV1NzPPUkQJOxMTnq7kItguok6ijqUCcVBFLx/k+PyyowHmDs14FnjOtUiubgQfLoUZoDB6jHjPHXMx1DgMfOHwHM2GihLY4NekEIoA518vg0CF98BBDF45Xhck53r7QfKtBC0Jwkej15ck/evcce89dCoS/t1fBtvK3AGaFJ5tvhUUQcyzN6oAAIVQU4LRDGhp0H/zj60R822xZvfft2dZ7yMNp0w5zIlxCZ/jAgAG74J8SqVZA7d2bKjT1bbQZldSiB56wnSouLvHuH3lE2tHVdrvDMy+NQ5UAJCQATf1F+O3lzR3rXtPdsSa/B7BeNsUNmWuwkXaCjUWpfrr8yj53bLxWLIlkcnBrCvdfWk3Pa0/dX3EkAkzPYSI7rN6bFzNhivRs2Gs5q5idXv0CZk8PZrksCTB+Xz54CvPFG6q4u6s5OetOmfWnNZs4Q4CzXpZNIsnHSS+TMbfSu/8Rw5lb7rX5jWwAkVCpR+NiKkfeOOy+cIqmltd1IxQeiNJSPu1rXoUAEcInRsBAgAKkUaC3s3LlwRo2CDARgYzGIZ5+FUArWWlgIBAA8HXSxOGCxpmwJqgqrodMdEEIKKYMcktUv+69t7+aoiwuG/mXh+bMhHddY0yWVcGD0EQzLLwN0N36yrx5JFcJorSEzd4kBwO3bYaurYdNp2MWLgaZPASEgKSBBPO66uFl5WDR4Dm6/4Bbo9H440oGlgXTCJhVKyBd3v1kuEMTEsb1GPvrIiLsGVeSNMki3C0MjKSQcFcGU92/G2pYG3CQVatK7MEEf1z/BEBAMAocP9RRevQKWhwrwByqM6T0Qr1b+HsZ6EDRQEEQoaRv2faTmf3xf8zut9fOF8K/gnHAs+tDdpT+Y89MLvg8pg8ZLtyulIjigD+KyN2aidO8giKCHbrEB5WYvSmlQ4gGKQEsQ+AwCHzjZ6OJFcL1cNORswrrq5UiFCuCZTgSD2QbWqF99thz3NP5mZcfBjvkC2OtrgJDG0gJAzYSSqmUPX7SwcFjuCKO79kgnEBcftn+MqW/OxZKDNyEtg2hQLTgsD+HDQCONNKLi6FC4zMJQXYh862BRdDlWjH8Q4/Mq4XkHGHALbFN7o7rjX0t3v7z1tR8DWCWFhKVVCgAJilrUqk/R1LilvXnV6l2v9HGlGj4mv0LAalMY6StzImHctesp1Ohy9LfZGG0G4HPRJuKI4Lbuy1BoosijizuDy7GgYjau7TMVsF1GOVH5xNYVcmb9wj837No4VUG+dw2uUY1oBADbczdvxmYSVErIQ0e6jzy/tuWtbQ2d/64szx2elXSTZkT2xeK/bBZ/2vM6qjAcR5DGR4GtSAuNUq8vlHDwsHoBIy8cgSWliwgB09zZ4szZcPeBhz5+cl5nd+ciJeRBA+tsxuZTPtVFLWqV8vWvXyrZ+8WnKu8jZ20jv7dDX1IyklPFeL6NX3OSW8XLo6P5dzzCGeJKjiwuI2dt15z1OZ+peohFuUWvABigII/p/1k90Z1jSgWJW2oHf7e9+dr17LqxyUsVFNklmM3r3Am8OlLFZZjL3nl9bMf1G70d123g9MGTDkFiHoBjSuuc638D6d+SEgAGFyZ7r33u8t9y/VVrGI8lWZxVzL6xvsyL9WL9VWv40hXPsDiv6A0AQ8416tOzEcDscf3H7uwTLzJTRCWniEtZEi823xl0WSsc3PpNRH3SF3NdXZ3MSiZLnXBk8xRZaYe5g44OjJQcrRHjrApH/hMoSAwjKc4GXJzpPgIQKYTzD/XaO+HI8HDQKv1p4AuphcWQ9Hk0gurV6EZvd7Q1IXajM3Pn87RRnamnvwQkDsMT4WC3hpkQs65MmRyRb+KiU6ZlU6gVrU77z9L7u9/CGYKfy/AZSwZr8rN61w+MlHQNihR358d6fYBEYNpZsgoA+B96i9z9MuacjQAAAABJRU5ErkJggg=="/>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #111; color: #ccc; font-family: 'Segoe UI', monospace;
          padding: 20px; min-height: 100vh; }}
  h1 {{ color: #aaa; font-size: 1.1em; margin-bottom: 16px; letter-spacing: .05em; }}
  #history-text {{ white-space: pre-wrap; font-size: 0.82em; line-height: 1.7;
                   background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px;
                   padding: 16px; max-width: 900px; margin: 0 auto; }}
  #dl-btn {{ display: block; margin: 16px auto 0; max-width: 220px; padding: 10px 0;
             background: #1a2a1a; border: 1px solid #3a5a3a; border-radius: 8px;
             color: #8c8; font-size: 0.9em; text-align: center;
             cursor: pointer; text-decoration: none; }}
  #dl-btn:hover {{ background: #1f3a1f; }}
</style>
</head><body>
<h1 style="text-align:center">&#8635; SESSION HISTORY</h1>
{body}
<a id="dl-btn" href="/history/download">&#11015; Download .txt</a>
</body></html>"""
        return html

    @_app.route('/history/download')
    def history_download():
        from flask import Response
        text = '\n'.join(_session_lines) if _session_lines else 'No session history yet.'
        return Response(
            text,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{_session_filename}"'}
        )

    @_app.route('/titles')
    def get_titles():
        from flask import jsonify
        titles = _titles_provider() if _titles_provider else []
        return jsonify(titles)

    @_app.route('/player_names')
    def get_player_names():
        from flask import jsonify
        names = _player_names_provider() if _player_names_provider else []
        return jsonify(names)

    @_app.route('/player_colors')
    def get_player_colors_route():
        from flask import jsonify
        # Merge scoreboard file (authoritative) with in-memory (recent web changes)
        merged = {}
        try:
            _sc_path = os.path.join(_SCOREBOARD_DATA, 'scoreboard_colors.json')
            if os.path.exists(_sc_path):
                with open(_sc_path, 'r', encoding='utf-8') as _f:
                    merged.update(json.load(_f))
        except Exception:
            pass
        merged.update(_player_colors)
        return jsonify(merged)

    @_socketio.on('set_player_color')
    def handle_set_player_color(data):
        from flask import request as _req
        name = str(data.get('name', '')).strip()
        bg   = str(data.get('bg',   '')).strip()
        text = str(data.get('text', '')).strip()
        if not name:
            return
        _player_colors[name] = {'bg': bg, 'text': text}
        _write_color_command(name, bg, text)
        merged = {}
        try:
            _sc_path = os.path.join(_SCOREBOARD_DATA, 'scoreboard_colors.json')
            if os.path.exists(_sc_path):
                with open(_sc_path, 'r', encoding='utf-8') as _f:
                    merged.update(json.load(_f))
        except Exception:
            pass
        merged.update(_player_colors)
        _socketio.emit('player_colors_update', {'colors': merged})

    @_socketio.on('connect')
    def on_connect():
        from flask import request as _req
        if _req.remote_addr in _hard_banned_ips:
            emit('banned', {})
            disconnect()
            return
        # Send the active question immediately to newly-connected clients
        if _current_question:
            emit('question', _current_question)
        else:
            emit('rules_update', _current_rules)
        if _session_lines:
            emit('session_history', {'text': '\n'.join(_session_lines), 'filename': _session_filename})
        if _timer_state:
            emit('timer_update', _timer_state)
        if _info_public and _current_metadata:
            emit('info_public_update', {'show': True, 'metadata': _current_metadata})
        emit('emoji_status', {'muted': False, 'timed_out': False, 'timeout_until': 0, 'remaining_ms': 0})
        _emit_buzzer_state(to_sid=_req.sid)
        # Send playback state to newly-connected hosts after they authenticate via claim_host

    @_socketio.on('disconnect')
    def on_disconnect():
        from flask import request as _req
        _host_sids.discard(_req.sid)
        _connected_players.pop(_req.sid, None)
        _submitted_sids.discard(_req.sid)
        _broadcast_players_update()

    @_socketio.on('set_name')
    def handle_set_name(data):
        from flask import request as _req
        name = str(data.get('name', '')).strip()
        if not name:
            return
        _connected_players[_req.sid] = name
        emit('emoji_status', _get_emoji_status(name))
        _broadcast_players_update()
        if (_current_question and _current_question.get('buzzer_only') and _submitted_answers):
            emit('peer_answers_update', {'answers': list(_submitted_answers)})
        elif any(a['name'] == name for a in _submitted_answers):
            _submitted_sids.add(_req.sid)
            emit('peer_answers_update', {'answers': list(_submitted_answers)})
        # If a question is active, this player is now served
        if _current_question and name not in _shadow_kicked_players and name not in _banned_names:
            _served_queue.put(name)
        # Password-based host grant is handled by the claim_host event

    @_socketio.on('claim_host')
    def handle_claim_host(data):
        from flask import request as _req
        password = str(data.get('password', '')).strip()
        if _host_password and password == _host_password:
            _host_sids.add(_req.sid)
            emit('host_granted', {'answers': list(_submitted_answers)})
            if _current_metadata:
                emit('metadata_update', _current_metadata)
            if _playback_state:
                emit('playback_state', _playback_state)
            if _up_next:
                emit('up_next_update', _up_next)
            if _current_marks:
                emit('marks_update', _current_marks)
            if _current_toggles:
                emit('toggles_update', _current_toggles)
            emit('host_messages_update', {'messages': list(_host_messages)})
        else:
            emit('host_denied', {})

    @_socketio.on('host_message_send')
    def handle_host_message_send(data):
        from flask import request as _req
        if _req.remote_addr in _shadow_kicked_ips:
            return
        name = _connected_players.get(_req.sid, '').strip()
        if not name or name in _banned_names:
            return
        text = str((data or {}).get('text', '')).strip()
        if not text:
            return
        text = text[:280]
        entry = {'name': name, 'text': text, 'ts': int(time.time() * 1000)}
        _host_messages.append(entry)
        if len(_host_messages) > 500:
            del _host_messages[:-500]
        _emit_host_messages()
        _emit_host_message_toast(entry)

    @_socketio.on('host_messages_clear')
    def handle_host_messages_clear(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        _host_messages.clear()
        _emit_host_messages()

    @_socketio.on('select_answer')
    def handle_select(data):
      from flask import request as _req
      if _req.remote_addr in _shadow_kicked_ips:
        return
      sid_name = _connected_players.get(_req.sid, '')
      raw_name = sid_name if sid_name else str((data or {}).get('name', 'Anonymous'))
      name = str(raw_name).strip()[:50] or 'Anonymous'
      if name in _banned_names:
        return
      if not _current_question:
        return
      if not bool((data or {}).get('explicit', False)):
        return
      answer = str(data.get('answer', '')).strip()[:200]
      _pending_selections[name] = answer

    @_socketio.on('submit_answer')
    def handle_answer(data):
      from flask import request as _req
      if _req.remote_addr in _shadow_kicked_ips:
        return  # silently discard (shadow kick)
      sid_name = _connected_players.get(_req.sid, '')
      raw_name = sid_name if sid_name else str((data or {}).get('name', 'Anonymous'))
      name = str(raw_name).strip()[:50] or 'Anonymous'
      if name in _banned_names:
        return  # silently discard (name ban)
      answer = str(data.get('answer', '')).strip()[:200]
      _pending_selections.pop(name, None)  # no longer pending once submitted
      _answer_queue.put({'name': name, 'answer': answer})
      _submitted_answers.append({'name': name, 'answer': answer})
      _submitted_sids.add(_req.sid)
      _broadcast_players_update()
      _emit_peer_answers_update()
      if _host_sids:
        for sid in list(_host_sids):
          _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)
      if _current_question and 'rank_slider' in _current_question:
        try:
          rk = int(answer)
          _taken_ranks.add(rk)
          _current_question['taken_ranks'] = list(_taken_ranks)
          _socketio.emit('rank_taken', {'rank': rk})
        except (ValueError, TypeError):
          pass
        _socketio.emit('rank_marks_update', {'answers': list(_submitted_answers)})
      if _current_question and 'year' in _current_question:
        try:
          yr = int(answer)
          _taken_years.add(yr)
          _current_question['taken_years'] = list(_taken_years)
          _socketio.emit('year_taken', {'year': yr})
        except (ValueError, TypeError):
          pass
      if _current_question and 'drum' in _current_question:
        try:
          sc = float(answer)
          _taken_scores.add(sc)
          _current_question['taken_scores'] = list(_taken_scores)
          _socketio.emit('score_taken', {'score': sc})
        except (ValueError, TypeError):
          pass

    @_socketio.on('remove_answer')
    def handle_remove_answer(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        idx = data.get('index')
        if idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(_submitted_answers):
            return
        removed_name = _submitted_answers[idx]['name']
        _submitted_answers.pop(idx)
        _removal_queue.put(removed_name)
        _broadcast_players_update()
        _emit_peer_answers_update()
        for sid in list(_host_sids):
            _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)

    @_socketio.on('remove_player')
    def handle_remove_player(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str(data.get('name', '')).strip()
        if not name:
            return
        # Remove the player from the session — they can freely rejoin
        for sid, pname in list(_connected_players.items()):
            if pname == name:
                del _connected_players[sid]
                _submitted_sids.discard(sid)
        # Remove all submitted answers for this player
        _submitted_answers[:] = [a for a in _submitted_answers if a['name'] != name]
        _broadcast_players_update()
        _emit_peer_answers_update()
        for sid in list(_host_sids):
            _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)

    @_socketio.on('rename_player')
    def handle_rename_player(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        old_name = str((data or {}).get('old_name', '')).strip()[:50]
        new_name = str((data or {}).get('new_name', '')).strip()[:50]
        if not old_name or not new_name or old_name == new_name:
            return
        if ' ' in new_name:
            return
        if new_name in _banned_names:
            return
        # Avoid duplicate connected names
        if any(pname == new_name for pname in _connected_players.values()):
            return

        changed = False
        renamed_sids = []
        for sid, pname in list(_connected_players.items()):
          if sid in _host_sids:
            continue
          if pname == old_name:
            _connected_players[sid] = new_name
            changed = True
            renamed_sids.append(sid)
        if not changed:
            return

        # Migrate pending selection
        if old_name in _pending_selections:
            old_pending = _pending_selections.pop(old_name)
            if new_name not in _pending_selections:
                _pending_selections[new_name] = old_pending

        # Migrate submitted answers
        for a in _submitted_answers:
            if a.get('name') == old_name:
                a['name'] = new_name

        # Migrate shadow-kick display entry
        if old_name in _shadow_kicked_players and new_name not in _shadow_kicked_players:
            _shadow_kicked_players[new_name] = _shadow_kicked_players.pop(old_name)

        # Migrate in-memory color and notify scoreboard command channel
        if old_name in _player_colors and new_name not in _player_colors:
            _player_colors[new_name] = _player_colors.pop(old_name)
            try:
                clr = _player_colors.get(new_name) or {}
                _write_color_command(new_name, str(clr.get('bg', '') or ''), str(clr.get('text', '') or ''))
            except Exception:
                pass

        _broadcast_players_update()
        _emit_peer_answers_update()
        for sid in renamed_sids:
            _socketio.emit('name_forced', {'name': new_name}, to=sid)
        for sid in list(_host_sids):
            _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)

    @_socketio.on('name_ban')
    def handle_name_ban(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str(data.get('name', '')).strip()
        if not name:
            return
        _banned_names.add(name)
        ip = None
        for sid, pname in list(_connected_players.items()):
            if pname == name:
                try:
                    environ = _socketio.server.get_environ(sid)
                    ip = environ.get('REMOTE_ADDR') if environ else None
                except Exception:
                    pass
                del _connected_players[sid]
                _submitted_sids.discard(sid)
        _shadow_kicked_players[name] = ip
        _submitted_answers[:] = [a for a in _submitted_answers if a['name'] != name]
        _broadcast_players_update()
        _emit_peer_answers_update()
        for sid in list(_host_sids):
            _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)

    @_socketio.on('ip_ban')
    def handle_ip_ban(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str(data.get('name', '')).strip()
        if not name:
            return
        ip = None
        for sid, pname in list(_connected_players.items()):
            if pname == name:
                try:
                    environ = _socketio.server.get_environ(sid)
                    ip = environ.get('REMOTE_ADDR') if environ else None
                    if ip:
                        _hard_banned_ips.add(ip)
                except Exception:
                    pass
                try:
                    _socketio.server.disconnect(sid)
                except Exception:
                    pass
                _connected_players.pop(sid, None)
                _submitted_sids.discard(sid)
        _shadow_kicked_players[name] = ip
        _submitted_answers[:] = [a for a in _submitted_answers if a['name'] != name]
        _broadcast_players_update()
        _emit_peer_answers_update()
        for sid in list(_host_sids):
            _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)

    @_socketio.on('unban_player')
    def handle_unban_player(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str(data.get('name', '')).strip()
        if not name:
            return
        ip = _shadow_kicked_players.pop(name, None)
        if ip:
            _shadow_kicked_ips.discard(ip)
            _hard_banned_ips.discard(ip)
        _banned_names.discard(name)
        _broadcast_players_update()

    @_socketio.on('emoji_disable')
    def handle_emoji_disable(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str(data.get('name', '')).strip()
        if not name:
            return
        _emoji_disabled_names.add(name)
        _broadcast_players_update()
        _emit_emoji_status_for_name(name)

    @_socketio.on('emoji_enable')
    def handle_emoji_enable(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str(data.get('name', '')).strip()
        if not name:
            return
        _emoji_disabled_names.discard(name)
        _broadcast_players_update()
        _emit_emoji_status_for_name(name)

    @_socketio.on('send_emoji')
    def handle_send_emoji(data):
        from flask import request as _req
        if _req.remote_addr in _shadow_kicked_ips:
            return
        name = _connected_players.get(_req.sid, '').strip()
        if not name or name in _banned_names:
            return
        if name in _emoji_disabled_names:
            emit('emoji_status', _get_emoji_status(name))
            return

        now = time.time()
        timeout_until = float(_emoji_timeout_until.get(name, 0.0) or 0.0)
        if timeout_until > now:
            emit('emoji_status', _get_emoji_status(name))
            return

        emoji = str(data.get('emoji', '')).strip()
        # Accept emoji-like strings: non-empty, ≤10 chars.
        # Reject plain ASCII words (letters) but allow keycap digits
        # (they include combining/non-ASCII codepoints). Require at least
        # one non-ASCII codepoint to ensure it's an emoji-like string.
        if not emoji or len(emoji) > 10:
            return
        # reject if contains ASCII letters (prevents words)
        if any(c.isalpha() and ord(c) < 128 for c in emoji):
            return
        # require at least one non-ASCII codepoint (emoji or combining marks)
        if not any(ord(c) >= 128 for c in emoji):
            return

        # Rolling-window anti-spam tracking
        dq = _emoji_events_by_name.get(name)
        if dq is None:
            dq = deque()
            _emoji_events_by_name[name] = dq

        # Keep only recent events within longest relevant window.
        max_window = max(_EMOJI_WINDOW_SECONDS, _EMOJI_BURST_WINDOW_SECONDS)
        while dq and (now - dq[0]) > max_window:
            dq.popleft()
        dq.append(now)

        # Burst guard first.
        burst_count = 0
        for ts in reversed(dq):
            if (now - ts) <= _EMOJI_BURST_WINDOW_SECONDS:
                burst_count += 1
            else:
                break
        if burst_count >= _EMOJI_BURST_THRESHOLD:
            _apply_emoji_timeout(name, short=True)
            emit('emoji_status', _get_emoji_status(name))
            return

        # Standard threshold in rolling window.
        window_count = 0
        for ts in reversed(dq):
            if (now - ts) <= _EMOJI_WINDOW_SECONDS:
                window_count += 1
            else:
                break
        if window_count > _EMOJI_TIMEOUT_THRESHOLD:
            _apply_emoji_timeout(name, short=False)
            emit('emoji_status', _get_emoji_status(name))
            return

        # Optional warning pulse to help client show near-limit state.
        if window_count >= _EMOJI_WARN_THRESHOLD:
            emit('emoji_status', _get_emoji_status(name))

        _emoji_queue.put((name, emoji))

    @_socketio.on('buzzer_control')
    def handle_buzzer_control(data):
      from flask import request as _req
      if _req.sid not in _host_sids:
        return
      cmd = str((data or {}).get('cmd', '')).strip().lower()
      control_buzzer(cmd)

    @_socketio.on('buzz_press')
    def handle_buzz_press(data):
      from flask import request as _req
      if _req.remote_addr in _shadow_kicked_ips:
        return
      name = _connected_players.get(_req.sid, '').strip()
      if not name or name in _banned_names:
        return
      if (not _current_question) or (not _current_question.get('buzzer_only')):
        return
      if (not _buzzer_open) or _buzzer_locked:
        return
      # One buzz per player per open/reset cycle.
      if any(item.get('name') == name for item in _submitted_answers):
        return
      rank = len(_submitted_answers) + 1
      now_ms = int(time.time() * 1000)
      base_ms = _buzzer_opened_at_ms if isinstance(_buzzer_opened_at_ms, int) else now_ms
      elapsed_ms = max(0, now_ms - base_ms)
      answer = f"[#{rank}] {elapsed_ms} ms"
      _pending_selections.pop(name, None)
      _answer_queue.put({'name': name, 'answer': answer})
      _submitted_answers.append({'name': name, 'answer': answer})
      _submitted_sids.add(_req.sid)
      _broadcast_players_update()
      _emit_peer_answers_update()
      if _host_sids:
        for sid in list(_host_sids):
          _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)
      _emit_buzzer_state()
      if _on_buzz_callback is not None:
        try:
          _on_buzz_callback(rank, name)
        except Exception:
          pass

    @_socketio.on('host_action')
    def handle_host_action(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        action = str(data.get('action', '')).strip()
        if not action or _host_action_callback is None:
            return
        data['_sid'] = _req.sid
        try:
            _host_action_callback(action, data)
        except Exception:
            pass

    @_socketio.on('request_youtube_list')
    def handle_request_youtube_list():
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        if _host_action_callback is not None:
            try:
                _host_action_callback('get_youtube_list', {'_sid': _req.sid})
            except Exception:
                pass


def _broadcast_players_update():
    """Emit current player list (with submitted state) to all connected clients."""
    if not _socketio:
        return
    submitted_names = {a['name'] for a in _submitted_answers}
    host_names = {name for sid, name in _connected_players.items() if sid in _host_sids}
    seen = set()
    players = []
    for name in _connected_players.values():
        if name not in seen:
            seen.add(name)
        players.append({
          'name': name,
          'submitted': name in submitted_names,
          'kicked': False,
          'host': name in host_names,
          'emoji_muted': name in _emoji_disabled_names,
        })
    for name in _shadow_kicked_players:
        if name not in seen:
            seen.add(name)
        players.append({
          'name': name,
          'submitted': name in submitted_names,
          'kicked': True,
          'host': False,
          'emoji_muted': name in _emoji_disabled_names,
        })
    _socketio.emit('players_update', {'players': players})


def _start_ngrok(domain, port):
    global _ngrok_process, public_url
    # Strip any protocol prefix the user may have pasted into config
    domain = domain.removeprefix('https://').removeprefix('http://').rstrip('/')
    # Resolve ngrok: prefer the exe dir (works inside a frozen .exe) then fall back to PATH
    try:
        _ngrok_process = subprocess.Popen(
            [NGROK_CMD, 'http', '--domain', domain, str(port)],  # NGROK_CMD resolved at import
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        public_url = f'https://{domain}'
        print(f'[Web Server] Live at: {public_url}')
    except FileNotFoundError:
        print('[Web Server] ngrok.exe not found in PATH or exe directory. Server is local-only.')
