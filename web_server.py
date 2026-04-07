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
_current_question = None   # dict pushed to newly-connecting clients
_taken_years: set = set()   # years already submitted in the current year-round
_host_name: str = ''            # name that grants host-view access
_host_sids: set = set()         # connected socket SIDs granted host access
_submitted_answers: list = []   # answers collected for the current question
_current_rules: dict = {}       # rules header+body shown on the waiting screen
_connected_players: dict = {}   # sid → player name
_submitted_sids: set = set()    # SIDs that submitted in the current question
_shadow_kicked_ips: set = set()  # IPs whose answers are silently discarded (kick)
_shadow_kicked_players: dict = {}  # name → IP for host unban display
_banned_names: set = set()    # names whose answers are silently discarded (name ban)
_hard_banned_ips: set = set() # IPs that are disconnected on connect (IP ban)
_ngrok_process = None
_server_started = False    # True once start() completes successfully
_titles_provider = None         # callable() → list[str]; set by main app
_player_names_provider = None   # callable() → list[str]; set by main app
_player_colors: dict = {}       # name → {bg: str, text: str}; in-memory color state
_color_cmd_lock = threading.Lock()  # guards scoreboard_color_commands.json writes
_SCOREBOARD_DATA = 'scoreboard_data'
_session_lines: list = []  # latest session history text lines
_session_filename: str = 'session_history.txt'  # download filename
_timer_state: dict = {}    # {seconds, paused} while a timer is active; empty = no timer

public_url = None          # Readable from main app after start()


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
  <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #111; color: #fff;
      font-family: 'Segoe UI', sans-serif;
      min-height: 100vh;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      padding: 20px; gap: 8px;
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
      padding: 8px 12px; pointer-events: none;
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
      background: rgba(0,0,0,0.75); z-index: 700;
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
    .drum-value-display {
      text-align: center; font-size: 1.1em; color: #aaa; margin-bottom: 14px;
    }

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
    .stepper-display {
      text-align: center; font-size: 2em; font-weight: bold;
      padding: 14px; background: #1a1a1a; border: 1px solid #444; border-radius: 8px;
      margin-bottom: 10px; letter-spacing: 1px;
      width: 100%; box-sizing: border-box; color: #fff;
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
    #player-list-wrap {
      position: fixed; bottom: 16px; left: 12px; z-index: 200;
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
    #kick-btn-name { background: #2a1a3a; color: #a8f; }
    #kick-btn-name:hover { background: #3a1a5a; color: #ccf; }
    #kick-btn-ip { background: #1a2a3a; color: #48f; }
    #kick-btn-ip:hover { background: #1a3a5a; color: #8cf; }
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
      display: grid; grid-template-columns: repeat(6, 1fr);
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
      position: absolute; left: 50%; transform: translateX(-50%);
      background: #0d0d1a; border: 1px solid #334; border-radius: 20px;
      padding: 5px 18px; pointer-events: none; white-space: nowrap;
    }
    #timer-display {
      font-family: monospace; font-size: 1.15em; font-weight: bold;
      color: #ffffff; letter-spacing: 0.06em;
    }
    #timer-display.timer-warning { color: #ff4444; }
  </style>
</head>
<body>
  <div id="top-bar">
    <button id="history-btn" onclick="_openHistory()" style="display:none">&#8635; SESSION HISTORY</button>
    <div id="timer-bar" style="visibility:hidden"><div id="timer-display">0:00</div></div>
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
        <button id="kick-btn-shadow">Kick (Shadow)</button>
        <button id="kick-btn-name">Name Ban</button>
        <button id="kick-btn-ip">IP Ban</button>
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
    <input id="name-input" placeholder="Your name (no spaces)&hellip;" maxlength="30" autofocus list="player-names-list"/>
    <button id="name-btn" onclick="saveName()">Join</button>
  </div>

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
      <button id="host-toggle" onclick="_toggleHostPanel()">&#128065; Answers (0)</button>
      <div id="host-panel"><div id="host-answers"></div></div>
    </div>
    <div id="emoji-bar">
      <p>React</p>
      <div id="emoji-btns">
        <button id="emoji-add-btn" title="Edit reactions" onclick="_openEmojiPicker()">&#9998; Edit</button>
      </div>
    </div>
  </div>

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
          <!-- Oranges -->
          <span class="cp-swatch" style="background:peachpuff;border-color:#555" onclick="_colorpickPickPreset('peachpuff')" title="peachpuff"></span>
          <span class="cp-swatch" style="background:lightsalmon;border-color:#555" onclick="_colorpickPickPreset('lightsalmon')" title="lightsalmon"></span>
          <span class="cp-swatch" style="background:coral" onclick="_colorpickPickPreset('coral')" title="coral"></span>
          <span class="cp-swatch" style="background:orange" onclick="_colorpickPickPreset('orange')" title="orange"></span>
          <span class="cp-swatch" style="background:darkorange" onclick="_colorpickPickPreset('darkorange')" title="darkorange"></span>
          <span class="cp-swatch" style="background:sienna" onclick="_colorpickPickPreset('sienna')" title="sienna"></span>
          <span class="cp-swatch" style="background:chocolate" onclick="_colorpickPickPreset('chocolate')" title="chocolate"></span>
          <!-- Yellows -->
          <span class="cp-swatch" style="background:lightyellow;border-color:#555" onclick="_colorpickPickPreset('lightyellow')" title="lightyellow"></span>
          <span class="cp-swatch" style="background:yellow;border-color:#555" onclick="_colorpickPickPreset('yellow')" title="yellow"></span>
          <span class="cp-swatch" style="background:khaki;border-color:#555" onclick="_colorpickPickPreset('khaki')" title="khaki"></span>
          <span class="cp-swatch" style="background:gold;border-color:#555" onclick="_colorpickPickPreset('gold')" title="gold"></span>
          <span class="cp-swatch" style="background:goldenrod" onclick="_colorpickPickPreset('goldenrod')" title="goldenrod"></span>
          <span class="cp-swatch" style="background:darkgoldenrod" onclick="_colorpickPickPreset('darkgoldenrod')" title="darkgoldenrod"></span>
          <span class="cp-swatch" style="background:olive" onclick="_colorpickPickPreset('olive')" title="olive"></span>
          <!-- Greens -->
          <span class="cp-swatch" style="background:lightgreen;border-color:#555" onclick="_colorpickPickPreset('lightgreen')" title="lightgreen"></span>
          <span class="cp-swatch" style="background:lime;border-color:#555" onclick="_colorpickPickPreset('lime')" title="lime"></span>
          <span class="cp-swatch" style="background:limegreen" onclick="_colorpickPickPreset('limegreen')" title="limegreen"></span>
          <span class="cp-swatch" style="background:forestgreen" onclick="_colorpickPickPreset('forestgreen')" title="forestgreen"></span>
          <span class="cp-swatch" style="background:green" onclick="_colorpickPickPreset('green')" title="green"></span>
          <span class="cp-swatch" style="background:seagreen" onclick="_colorpickPickPreset('seagreen')" title="seagreen"></span>
          <span class="cp-swatch" style="background:darkgreen" onclick="_colorpickPickPreset('darkgreen')" title="darkgreen"></span>
          <!-- Teals -->
          <span class="cp-swatch" style="background:lightcyan;border-color:#555" onclick="_colorpickPickPreset('lightcyan')" title="lightcyan"></span>
          <span class="cp-swatch" style="background:aquamarine;border-color:#555" onclick="_colorpickPickPreset('aquamarine')" title="aquamarine"></span>
          <span class="cp-swatch" style="background:turquoise" onclick="_colorpickPickPreset('turquoise')" title="turquoise"></span>
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
          <!-- Purples -->
          <span class="cp-swatch" style="background:plum;border-color:#555" onclick="_colorpickPickPreset('plum')" title="plum"></span>
          <span class="cp-swatch" style="background:violet;border-color:#555" onclick="_colorpickPickPreset('violet')" title="violet"></span>
          <span class="cp-swatch" style="background:orchid" onclick="_colorpickPickPreset('orchid')" title="orchid"></span>
          <span class="cp-swatch" style="background:mediumpurple" onclick="_colorpickPickPreset('mediumpurple')" title="mediumpurple"></span>
          <span class="cp-swatch" style="background:blueviolet" onclick="_colorpickPickPreset('blueviolet')" title="blueviolet"></span>
          <span class="cp-swatch" style="background:purple" onclick="_colorpickPickPreset('purple')" title="purple"></span>
          <span class="cp-swatch" style="background:indigo" onclick="_colorpickPickPreset('indigo')" title="indigo"></span>
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
      <div id="history-box-title">&#128290; Session History</div>
      <div id="history-text-area">No history yet.</div>
      <div id="history-footer">
        <a id="history-dl-btn" href="/history/download" download="session_history.txt">&#11015; Download</a>
        <button id="history-close-btn" onclick="_closeHistory()">Close</button>
      </div>
    </div>
  </div>

  <div id="player-list-wrap" style="display:none">
    <button id="player-list-btn" onclick="_togglePlayerList()">&#128101; <span id="player-count">0</span></button>
    <div id="player-list-panel">
      <div id="player-list-items"></div>
    </div>
  </div>

  <div id="anime-ac-wrap" class="ac-wrap" style="display:none">
    <input id="anime-ac-input" class="ac-input" placeholder="Your answer…" autocomplete="off"/>
    <div id="anime-ac-drop" class="ac-drop"></div>
  </div>

  <script>
    const socket = io();
    socket.on('connect', () => { if (playerName) socket.emit('set_name', { name: playerName }); });
    let selectedChoice = null;   // multiple-choice selection
    let playerName = localStorage.getItem('gta_name') || '';
    let _currentQid  = null;      // qid of the active question
    let _currentQuestionTitle = '';  // title of the active question
    let _myLastAnswer = null;        // player's answer for the current question
    let _prevQTitle = '';            // previous question's title
    let _prevQCorrect = null;        // previous question's correct answer (display string)
    let _prevQType = '';             // question type of previous question
    let _prevQCorrectTags = [];      // correct tag list for 'tags' type questions
    let _toggleBtnRef = null;     // reference to active toggle button (year/score)
    let _isHost = false;
    let _playerListOpen = false;
    let _peerAnswersOpen = false;
    let _playerColors = {};    // name → {bg, text}
    let _lastPlayerList = [];  // most recent players_update list
    let _colorpickTarget = null;
    let _colorpickBgValue = '';
    let _colorpickTextValue = '';
    let _colorpickActiveField = null;
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
    function saveName() {
      const v = document.getElementById('name-input').value.trim().replace(/\s+/g, '_');
      if (!v) return;
      playerName = v;
      localStorage.setItem('gta_name', playerName);
      socket.emit('set_name', { name: playerName });
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
      const ITEM_H  = 60;
      const WRAP_H  = 180;

      const years = [];
      for (let y = min; y <= max; y++) years.push(y);

      const wrap = document.createElement('div');
      wrap.className = 'drum-wrap';
      wrap.style.cssText = 'height:' + WRAP_H + 'px; margin-bottom:10px;';

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
      area.appendChild(wrap);

      const initIdx = Math.max(0, years.indexOf(Math.max(min, Math.min(max, initVal))));
      const takenSet = new Set();

      function getIdx() {
        return Math.max(0, Math.min(Math.round(scroller.scrollTop / ITEM_H), years.length - 1));
      }
      function getValue() { return years[getIdx()]; }
      function highlight() {
        const idx = getIdx();
        scroller.querySelectorAll('.drum-item').forEach((el, i) => {
          const vi = i - 1;
          const isTaken = el.textContent && takenSet.has(parseInt(el.textContent, 10));
          el.style.color          = isTaken ? '#c44' : (vi === idx ? '#fff' : '');
          el.style.fontSize       = vi === idx ? '1.7em' : '';
          el.style.textDecoration = isTaken ? 'line-through' : '';
        });
      }
      function markTaken(y) { takenSet.add(y); highlight(); }
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

      scroller.addEventListener('scroll', highlight, { passive: true });
      return { getValue, markTaken };
    }

    /* ══════════════════════════════════════════
       DRUM PICKER  (score)
       data.drum = { min, max, step, initial, decimals }
    ══════════════════════════════════════════ */
    function buildDrum(area, cfg) {
      const { min, max, step, initial, decimals, reverse } = cfg;
      const vals = [];
      for (let v = min; v <= max + 1e-9; v = Math.round((v + step) * 1e6) / 1e6)
        vals.push(parseFloat(v.toFixed(decimals)));
      if (reverse) vals.reverse();

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

      const display = document.createElement('div');
      display.className = 'drum-value-display';
      area.appendChild(wrap);
      area.appendChild(display);

      const ITEM_H = 60;

      function getCentered() {
        const idx = Math.round(scroller.scrollTop / ITEM_H);
        return Math.max(0, Math.min(idx, vals.length - 1));
      }

      function updateDisplay() {
        const idx = getCentered();
        const v = vals[idx];
        display.textContent = 'Selected: ' + (decimals > 0 ? v.toFixed(decimals) : String(v));
        // highlight centre item
        const items = scroller.querySelectorAll('.drum-item');
        items.forEach((el, i) => {
          const vi = i - 1; // offset for top padding
          if (vi === idx) { el.style.color = '#fff'; el.style.fontSize = '1.7em'; }
          else            { el.style.color = ''; el.style.fontSize = ''; }
        });
      }

      // Scroll to initial value — deferred so the browser has laid out the scroller
      const initIdx = vals.findIndex(v => Math.abs(v - initial) < step / 2);
      setTimeout(() => { scroller.scrollTop = Math.max(0, initIdx) * ITEM_H; updateDisplay(); }, 0);
      scroller.addEventListener('scroll', updateDisplay, { passive: true });

      return { getValue: () => vals[getCentered()] };
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
      area.appendChild(display);
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
      });

      // Group steps into rows of 3
      const stepDefs = cfg.steps || [];
      for (let i = 0; i < stepDefs.length; i += 3) {
        const chunk = stepDefs.slice(i, i + 3);
        const row = document.createElement('div');
        row.className = 'stepper-row cols-' + (chunk.length === 2 ? '2' : '3');
        chunk.forEach(s => {
          const btn = document.createElement('button');
          btn.className = 'step-btn ' + (s.delta < 0 ? 'neg' : 'pos');
          btn.textContent = s.label;
          btn.onclick = () => {
            value = Math.max(min, Math.min(max, value + s.delta));
            refresh();
          };
          row.appendChild(btn);
        });
        area.appendChild(row);
      }

      return { getValue: () => value };
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

    // constraints: { min, max, step, decimals }  (optional — only for numeric types)
    function buildToggleable(area, freeInput, typeKey, buildFn, constraints) {
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'input-toggle';
      _toggleBtnRef = toggleBtn;   // expose so submitAnswer can disable it

      function setup() {
        area.innerHTML = '';
        area.appendChild(toggleBtn);
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
    let drumHandle    = null;
    let stepperHandle = null;
    let tagHandle     = null;
    let _takenYears   = new Set();  // years taken this round (year questions only)

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
      document.getElementById('free-input').disabled = true;
      const acInp = document.getElementById('anime-ac-input');
      if (acInp) { acInp.disabled = true; }
      document.getElementById('choices-area').style.pointerEvents = 'none';
      document.getElementById('choices-area').style.opacity = '0.5';
      if (_toggleBtnRef) { _toggleBtnRef.disabled = true; _toggleBtnRef.style.opacity = '0.35'; }
    }

    /* ── Socket events ── */
    socket.on('question', data => {
      _currentQuestionTitle = data.title || '';
      _myLastAnswer = null;
      _currentQid   = data.qid || null;
      _toggleBtnRef = null;
      document.getElementById('waiting').style.display = 'none';
      document.getElementById('question-area').style.display = 'block';
      document.getElementById('q-title').textContent = data.title;
      document.getElementById('q-info').textContent = data.info || '';
      document.getElementById('sent-msg').style.display = 'none';
      // Clear host panel for new question (keep toggle visible if already host)
      document.getElementById('host-answers').innerHTML = '';
      document.getElementById('host-panel').style.display = 'none';
      const _ht = document.getElementById('host-toggle');
      if (_ht.style.display !== 'none') _ht.textContent = '\uD83D\uDC41 Submitted Answers (0)';
      document.getElementById('peer-answers-wrap').style.display = 'none';
      document.getElementById('peer-answers-list').innerHTML = '';
      _peerAnswersOpen = false;
      document.getElementById('submit-btn').disabled = false;
      document.getElementById('free-input').disabled = false;
      const acInpReset = document.getElementById('anime-ac-input');
      if (acInpReset) acInpReset.disabled = false;
      selectedChoice = null;
      drumHandle = null; stepperHandle = null; tagHandle = null;
      _takenYears = new Set();

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
          };
          area.appendChild(btn);
        });

      } else if (data.year) {
        /* ── Year picker with drum↔text toggle ── */
        buildToggleable(area, freeInput, 'year', a => buildYearPicker(a,
            _savedAnswer ? {...data.year, initial: parseInt(_savedAnswer, 10)} : data.year),
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
        buildToggleable(area, freeInput, 'score', a => buildDrum(a,
            _savedAnswer ? {...data.drum, initial: parseFloat(_savedAnswer)} : data.drum),
          { min: data.drum.min, max: data.drum.max, step: data.drum.step, decimals: data.drum.decimals });
        if (_savedAnswer && freeInput.style.display !== 'none') freeInput.value = _savedAnswer;

      } else if (data.stepper) {
        /* ── Stepper ── */
        stepperHandle = buildStepper(area,
          _savedAnswer ? {...data.stepper, initial: parseFloat(_savedAnswer)} : data.stepper);

      } else if (data.tags) {
        /* ── Tag chips (multi-select) ── */
        tagHandle = buildTags(area, data.tags, data.tags_max);
        if (_savedAnswer) tagHandle.restoreSelected(_savedAnswer);
        // Submit starts disabled until at least one chip is picked
        document.getElementById('submit-btn').disabled = true;

      } else {
        /* ── Free text (with optional anime autocomplete) ── */
        if (data.autocomplete === 'anime') {
          _loadAnimeTitles(() => { _setupAnimeAc(_savedAnswer); });
        } else {
          freeInput.oninput = null;
          freeInput.style.display = 'block';
          freeInput.value = '';
          freeInput.focus();
        }
      }

      if (_alreadyAnswered) _lockSubmittedUI(_savedAnswer);
    });

    socket.on('rules_update', data => {
      _applyRules(data.header || '', data.body || '');
    });

    socket.on('year_taken', data => {
      const y = data.year;
      _takenYears.add(String(y));
      if (drumHandle && drumHandle.markTaken) drumHandle.markTaken(y);
    });

    socket.on('host_granted', data => {
      _isHost = true;
      document.getElementById('host-toggle').style.display = 'block';
      _refreshHostAnswers(data.answers || []);
      _refreshPlayerList(_lastPlayerList);
      // Hide peer answers panel — host has their own answers view
      document.getElementById('peer-answers-wrap').style.display = 'none';
      document.getElementById('peer-answers-list').innerHTML = '';
      _peerAnswersOpen = false;
    });

    socket.on('player_colors_update', data => {
      _playerColors = data.colors || {};
      _updateLabelSwatch();
      _refreshPlayerList(_lastPlayerList);
    });

    socket.on('answer_update', data => {
      _refreshHostAnswers(data.answers || []);
    });

    socket.on('players_update', data => {
      _lastPlayerList = data.players || [];
      _refreshPlayerList(_lastPlayerList);
    });

    socket.on('peer_answers_update', data => {
      if (!_isHost) _refreshPeerAnswers(data.answers || []);
    });

    socket.on('answer_reveal', data => {
      _prevQTitle        = data.question      || '';
      _prevQCorrect      = data.correct       || '';
      _prevQType         = data.q_type        || '';
      _prevQCorrectTags  = data.correct_tags  || [];
    });

    socket.on('clear', data => {
      document.getElementById('waiting').style.display = 'block';
      document.getElementById('question-area').style.display = 'none';
      _applyRules((data && data.rules_header) || '', (data && data.rules_body) || '');
      _showPrevQuestion();
    });

    /* ── Timer ── */
    socket.on('timer_update', data => {
      _timerSeconds = parseFloat(data.seconds) || 0;
      _timerPaused  = !!data.paused;
      _timerRunning = true;
      _timerLastTs  = null;
      document.getElementById('timer-bar').style.visibility = 'visible';
      _renderTimer();
      if (_timerRafId) { cancelAnimationFrame(_timerRafId); _timerRafId = null; }
      if (!_timerPaused && _timerSeconds > 0) _timerRafId = requestAnimationFrame(_timerRaf);
    });
    socket.on('timer_clear', () => {
      _timerRunning = false;
      _timerLastTs  = null;
      if (_timerRafId) { cancelAnimationFrame(_timerRafId); _timerRafId = null; }
      document.getElementById('timer-bar').style.visibility = 'hidden';
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
      const mins  = Math.floor(total / 60);
      const secs  = total % 60;
      disp.textContent = mins > 0 ? (mins + ':' + String(secs).padStart(2, '0')) : String(secs);
      disp.className   = total <= 5 ? 'timer-warning' : '';
    }

    /* ── History modal ── */
    let _historyText = '';
    function _openHistory() {
      document.getElementById('history-text-area').textContent = _historyText || 'No history yet.';
      document.getElementById('history-overlay').classList.add('active');
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
      p.style.display = p.style.display === 'none' ? 'block' : 'none';
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
        const rm = document.createElement('button');
        rm.className = 'ha-remove';
        rm.title = 'Remove this answer';
        rm.textContent = '\u00d7';
        rm.onclick = () => _confirm(
          'Remove answer from ' + a.name + '?', 'Remove',
          () => socket.emit('remove_answer', { index: idx })
        );
        div.appendChild(text);
        div.appendChild(rm);
        // Right-click also removes
        div.addEventListener('contextmenu', e => {
          e.preventDefault();
          _confirm('Remove answer from ' + a.name + '?', 'Remove',
            () => socket.emit('remove_answer', { index: idx }));
        });
        container.appendChild(div);
      });
      const ht = document.getElementById('host-toggle');
      ht.textContent = '\uD83D\uDC41 Answers (' + answers.length + ')';
    }

    /* ── Kick options modal ── */
    function _kickOptions(name) {
      document.getElementById('kick-player-name').textContent = 'Action for: ' + name;
      document.getElementById('kick-btn-shadow').onclick = () => { _kickCancel(); socket.emit('remove_player', { name }); };
      document.getElementById('kick-btn-name').onclick   = () => { _kickCancel(); socket.emit('name_ban',      { name }); };
      document.getElementById('kick-btn-ip').onclick     = () => { _kickCancel(); socket.emit('ip_ban',        { name }); };
      document.getElementById('kick-overlay').classList.add('active');
    }
    function _kickCancel() {
      document.getElementById('kick-overlay').classList.remove('active');
    }

    socket.on('banned', () => {
      document.getElementById('name-screen').style.display    = 'none';
      document.getElementById('question-box').style.display   = 'none';
      document.getElementById('player-list-wrap').style.display = 'none';
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
      // Nature & weather
      '🌈','⚡','🌊','💧','🌸','🍀','🌙','☀️','❄️','🌪️','⛩️',
      // Objects & symbols
      '🔥','⭐','🌟','✨','💥','💫','🎉','🎊','🎈','🚀','🛸','👑','💎','🔮','🪄','🎁','🧸',
      '🎵','🎶','🎤','🎸','📷','📱','💻','🔑','⚙️','🧲','⏩',
      '✅','❌','⚠️','❓','❗','💯','🔔','📢','💬','👀','🫂',
      // Numbers
      '0️⃣','1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟',
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
    }
    function _sendEmoji(emoji) {
      socket.emit('send_emoji', { emoji });
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
    }
    function _resetEmojiDefaults() {
      _saveSavedEmojis([..._DEFAULT_EMOJIS]);
      _rebuildEmojiBar();
      _openEmojiPicker();  // re-render picker highlights
    }
    function _closeEmojiPicker() {
      document.getElementById('emoji-picker-overlay').classList.remove('active');
    }
    document.addEventListener('DOMContentLoaded', () => {
      _rebuildEmojiBar();
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
        div.appendChild(icon);
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
          } else if (p.name !== playerName) {
            btn.className = 'pl-remove';
            btn.title = 'Manage player';
            btn.textContent = '\u00d7';
            btn.onclick = () => _kickOptions(p.name);
            div.appendChild(btn);
          }
        }
        items.appendChild(div);
      });
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
      toggle.textContent = '\uD83D\uDC41 Others\u2019 answers (' + answers.length + ')';
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
    function submitAnswer() {
      let answer = null;

      if (drumHandle) {
        answer = String(drumHandle.getValue());
        if (_takenYears.has(answer)) {
          const errDiv = document.getElementById('free-error');
          errDiv.textContent = String(answer) + ' is already taken. Pick another year.';
          errDiv.style.display = 'block';
          return;
        }
      } else if (stepperHandle) answer = String(stepperHandle.getValue());
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
        if (_takenYears.size && _takenYears.has(answer)) {
          errDiv.textContent = answer + ' is already taken. Pick another year.';
          errDiv.style.display = 'block'; return;
        }
      }

      socket.emit('submit_answer', { name: playerName, answer: answer });
       _myLastAnswer = answer;

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


def set_host_name(name: str):
    """Set the player name that grants host-view access on the web client."""
    global _host_name
    _host_name = (name or '').strip()


def set_rules_text(header: str, body: str):
    """Set the rules header and body shown on the waiting screen between questions."""
    global _current_rules
    _current_rules = {'header': (header or '').strip(), 'body': (body or '').strip()}
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('rules_update', _current_rules)


def push_question(title, info='', choices=None, drum=None, stepper=None, tags=None, year=None, tags_max=None, autocomplete=None):
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
    """
    global _current_question
    if not FLASK_AVAILABLE or _socketio is None:
        return
    import time as _time
    global _submitted_answers, _submitted_sids
    _submitted_answers = []
    _submitted_sids = set()
    _broadcast_players_update()
    _current_question = {'title': title, 'info': info, 'choices': choices or [],
                         'qid': str(int(_time.time() * 1000))}
    if drum:              _current_question['drum']        = drum
    if stepper:           _current_question['stepper']     = stepper
    if tags:              _current_question['tags']        = tags
    if tags_max:          _current_question['tags_max']    = tags_max
    if year:
        global _taken_years
        _taken_years = set()
        _current_question['year']        = year
        _current_question['taken_years'] = []
    if autocomplete:      _current_question['autocomplete'] = autocomplete
    _socketio.emit('question', _current_question)


def remove_answer_by_name(name: str):
    """Remove all submitted answers for the given player name and broadcast the update."""
    global _submitted_answers
    if not FLASK_AVAILABLE or _socketio is None:
        return
    _submitted_answers[:] = [a for a in _submitted_answers if a['name'] != name]
    _removal_queue.put(name)
    _broadcast_players_update()
    for sid in list(_submitted_sids):
        _socketio.emit('peer_answers_update', {'answers': list(_submitted_answers)}, to=sid)
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
    global _current_question, _submitted_answers, _submitted_sids
    if not FLASK_AVAILABLE or _socketio is None:
        return
    _current_question = None
    _submitted_answers = []
    _submitted_sids = set()
    _socketio.emit('clear', {'rules_header': _current_rules.get('header',''), 'rules_body': _current_rules.get('body','')})
    _broadcast_players_update()


def get_answers():
    """Drain and return all pending answers as a list of {name, answer} dicts."""
    answers = []
    while True:
        try:
            answers.append(_answer_queue.get_nowait())
        except queue.Empty:
            break
    return answers


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


def start(port=8080, ngrok_domain=None):
    """Start the Flask/SocketIO server in a daemon thread, optionally launch ngrok.

    Returns True if server started, False if Flask is unavailable.
    """
    global _server_started
    if not FLASK_AVAILABLE:
        return False
    _build_app()
    t = threading.Thread(
        target=lambda: _socketio.run(
            _app, host='0.0.0.0', port=port,
            allow_unsafe_werkzeug=True, log_output=False
        ),
        daemon=True
    )
    t.start()
    _server_started = True
    if ngrok_domain:
        _start_ngrok(ngrok_domain, port)
    else:
        print(f"[Web Server] Running locally on port {port} (no ngrok domain set).")
    return True


def stop():
    """Terminate the ngrok process if running."""
    global _ngrok_process, _server_started
    _server_started = False
    if _ngrok_process:
        _ngrok_process.terminate()
        _ngrok_process = None


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
<h1 style="text-align:center">&#128290; SESSION HISTORY</h1>
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
        _broadcast_players_update()
        if any(a['name'] == name for a in _submitted_answers):
            _submitted_sids.add(_req.sid)
            emit('peer_answers_update', {'answers': list(_submitted_answers)})
        if _host_name and name == _host_name:
            _host_sids.add(_req.sid)
            emit('host_granted', {'answers': list(_submitted_answers)})

    @_socketio.on('submit_answer')
    def handle_answer(data):
        from flask import request as _req
        if _req.remote_addr in _shadow_kicked_ips:
            return  # silently discard (shadow kick)
        name   = str(data.get('name',   'Anonymous')).strip()[:50] or 'Anonymous'
        if name in _banned_names:
            return  # silently discard (name ban)
        answer = str(data.get('answer', '')).strip()[:200]
        _answer_queue.put({'name': name, 'answer': answer})
        _submitted_answers.append({'name': name, 'answer': answer})
        _submitted_sids.add(_req.sid)
        _broadcast_players_update()
        for sid in list(_submitted_sids):
            _socketio.emit('peer_answers_update', {'answers': list(_submitted_answers)}, to=sid)
        if _host_sids:
            for sid in list(_host_sids):
                _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)
        if _current_question and 'year' in _current_question:
            try:
                yr = int(answer)
                _taken_years.add(yr)
                _current_question['taken_years'] = list(_taken_years)
                _socketio.emit('year_taken', {'year': yr})
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
        for sid in list(_submitted_sids):
            _socketio.emit('peer_answers_update', {'answers': list(_submitted_answers)}, to=sid)
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
        for sid in list(_submitted_sids):
            _socketio.emit('peer_answers_update', {'answers': list(_submitted_answers)}, to=sid)
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
        for sid in list(_submitted_sids):
            _socketio.emit('peer_answers_update', {'answers': list(_submitted_answers)}, to=sid)
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
        for sid in list(_submitted_sids):
            _socketio.emit('peer_answers_update', {'answers': list(_submitted_answers)}, to=sid)
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

    @_socketio.on('send_emoji')
    def handle_send_emoji(data):
        from flask import request as _req
        if _req.remote_addr in _shadow_kicked_ips:
            return
        name = _connected_players.get(_req.sid, '').strip()
        if not name or name in _banned_names:
            return
        emoji = str(data.get('emoji', '')).strip()
        # Accept any emoji-like string: non-empty, ≤10 chars, no ASCII characters
        if not emoji or len(emoji) > 10 or any(ord(c) < 128 for c in emoji):
            return
        _emoji_queue.put((name, emoji))


def _broadcast_players_update():
    """Emit current player list (with submitted state) to all connected clients."""
    if not _socketio:
        return
    submitted_names = {a['name'] for a in _submitted_answers}
    seen = set()
    players = []
    for name in _connected_players.values():
        if name not in seen:
            seen.add(name)
            players.append({'name': name, 'submitted': name in submitted_names, 'kicked': False})
    for name in _shadow_kicked_players:
        if name not in seen:
            seen.add(name)
            players.append({'name': name, 'submitted': name in submitted_names, 'kicked': True})
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
