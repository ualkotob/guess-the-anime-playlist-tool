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
import threading
import time
from collections import deque

from _app_scripts.utils import color_to_rgb

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
# Tunnel availability (resolved at import time in web_tunnels)
# ---------------------------------------------------------------------------
from _app_scripts.file.web_server import web_tunnels
# Re-export availability flags: external modules read web_server.NGROK_AVAILABLE
# / web_server.CLOUDFLARED_AVAILABLE to gate tunnel menu/settings entries.
NGROK_AVAILABLE = web_tunnels.NGROK_AVAILABLE
CLOUDFLARED_AVAILABLE = web_tunnels.CLOUDFLARED_AVAILABLE

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
_host_messages: list = []       # host/player message thread entries
_current_rules: dict = {}       # rules header+body shown on the waiting screen
_connected_players: dict = {}   # sid → player name
_player_meta: dict = {}         # sid → {'join_ms': int, 'ip': str} for host duplicate-device view
_submitted_sids: set = set()    # SIDs that submitted in the current question
_shadow_kicked_ips: set = set()  # IPs whose answers are silently discarded (kick)
_shadow_kicked_players: dict = {}  # name → IP for host unban display
_banned_names: set = set()    # names whose answers are silently discarded (name ban)
_emoji_disabled_names: set = set()  # names whose emoji reactions are silently discarded
_message_blocked_names: set = set()  # names whose player->host messages are silently hidden
_message_notifications_blocked_names: set = set()  # names whose messages do not toast/chime hosts
_hard_banned_ips: set = set() # IPs that are disconnected on connect (IP ban)
_emoji_events_by_name: dict = {}   # name -> deque[timestamp]
_emoji_timeout_until: dict = {}    # name -> epoch seconds when timeout ends
_emoji_offense_level: dict = {}    # name -> escalating timeout level
_emoji_last_offense: dict = {}     # name -> epoch seconds of last offense

# Emoji anti-spam settings
_EMOJI_WINDOW_SECONDS = 10.0
_EMOJI_TIMEOUT_THRESHOLD = 50       # >50 in window triggers timeout
_EMOJI_WARN_THRESHOLD = 24          # optional warning threshold
_EMOJI_BURST_WINDOW_SECONDS = 1
_EMOJI_BURST_THRESHOLD = 10         # >=10 in 1s triggers short timeout
_EMOJI_BASE_TIMEOUT_SECONDS = 5.0
_EMOJI_REPEAT_MULTIPLIER = 1.1
_EMOJI_MAX_TIMEOUT_SECONDS = 180.0
_EMOJI_REPEAT_DECAY_SECONDS = 600.0

# Buzzer state
_buzzer_open: bool = False
_buzzer_locked: bool = False
_buzzer_opened_at_ms: int | None = None
_buzzer_disabled_names: set[str] = set()
_ngrok_process = None
_cloudflared_process = None
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
_on_skip_grant_callback = None # callable(name: str) called when skip grant changes (empty = cleared)
_on_buzzer_lock_callback = None # callable(name: str, locked: bool) for per-player buzzer locks
_pending_selections: dict = {}  # name → answer; silently tracks current selection before submit
_skip_grant_player: str = ''  # name of the player currently granted a skip (empty = none)

public_url = None          # Readable from main app after start()
_server_port = 8080        # Port the server is listening on; set in start()


def get_url():
    """Return the best available URL for this server.

    Priority:
    1. public_url — set when ngrok or a Cloudflare tunnel is active.
    2. Local LAN URL — http://<machine-ip>:<port> when only running locally.
    3. Empty string — if the server has not been started.
    """
    if public_url:
        return public_url
    if not _server_started:
        return ""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(("8.8.8.8", 80))  # doesn't send data; just determines the outgoing interface
            ip = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        ip = "localhost"
    return f"http://{ip}:{_server_port}"


def _real_client_ip(environ) -> str | None:
    """Return the originating client's IP, seeing through the ngrok/Cloudflare tunnel.

    Every tunnelled connection reaches Flask from 127.0.0.1 (the local end of the
    tunnel), so REMOTE_ADDR is identical for all players — banning one IP would ban
    everyone. The real client IP is carried in a forwarding header instead:
    Cloudflare sets CF-Connecting-IP; ngrok and generic proxies set X-Forwarded-For
    (the leftmost entry is the original client). Falls back to REMOTE_ADDR for the
    no-tunnel local case.
    """
    if not environ:
        return None
    cf = environ.get('HTTP_CF_CONNECTING_IP')
    if cf:
        return cf.strip()
    xff = environ.get('HTTP_X_FORWARDED_FOR')
    if xff:
        # "client, proxy1, proxy2" — leftmost is the originating client
        first = xff.split(',')[0].strip()
        if first:
            return first
    return environ.get('REMOTE_ADDR')


def _req_client_ip(req) -> str | None:
    """Real client IP for the current Flask/SocketIO request (see _real_client_ip)."""
    try:
        return _real_client_ip(req.environ)
    except Exception:
        return getattr(req, 'remote_addr', None)


def _sid_client_ip(sid) -> str | None:
    """Real client IP for a given Socket.IO sid (see _real_client_ip)."""
    try:
        return _real_client_ip(_socketio.server.get_environ(sid))
    except Exception:
        return None


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
    'disabled_names': sorted(_buzzer_disabled_names),
  }
  if to_sid:
    _socketio.emit('buzzer_state', payload, to=to_sid)
  else:
    _socketio.emit('buzzer_state', payload)


def _visible_messages_for(name: str) -> list:
  """Messages a given player should see: their own to-host messages plus
  host messages addressed to them (or broadcast to all)."""
  out = []
  for m in _host_messages:
    if m.get('sender') == 'host':
      to = m.get('to', '')
      if to in ('', 'all') or to == name:
        out.append(m)
    elif m.get('name', '') == name:
      out.append(m)
  return out

def _host_visible_messages() -> list:
  """Messages visible to hosts after per-player message blocks."""
  out = []
  for m in _host_messages:
    if m.get('sender') != 'host' and m.get('name', '') in _message_blocked_names:
      continue
    out.append(m)
  return out

def _emit_host_messages(to_sid: str = None):
  """Emit message-thread entries.

  Host clients get the full inbox; each player gets only the messages
  visible to them (their own + host replies addressed to them or all).
  """
  if not FLASK_AVAILABLE or _socketio is None:
    return
  if to_sid:
    if to_sid in _host_sids:
      _socketio.emit('host_messages_update', {'messages': _host_visible_messages()}, to=to_sid)
    else:
      name = _connected_players.get(to_sid, '')
      _socketio.emit('host_messages_update', {'messages': _visible_messages_for(name)}, to=to_sid)
    return
  full = {'messages': _host_visible_messages()}
  for sid in list(_host_sids):
    _socketio.emit('host_messages_update', full, to=sid)
  for sid, name in list(_connected_players.items()):
    if sid in _host_sids:
      continue
    _socketio.emit('host_messages_update', {'messages': _visible_messages_for(name)}, to=sid)


def _emit_host_message_toast(entry: dict):
  """Emit a live toast event for a new message.

  Player→host messages toast to host clients; host→player replies toast to
  the targeted player(s) (or all players when broadcast)."""
  if not FLASK_AVAILABLE or _socketio is None:
    return
  payload = dict(entry or {})
  if payload.get('sender') == 'host':
    to = payload.get('to', '')
    for sid, name in list(_connected_players.items()):
      if sid in _host_sids:
        continue
      if to in ('', 'all') or to == name:
        _socketio.emit('host_message_toast', payload, to=sid)
  else:
    if payload.get('name', '') in _message_notifications_blocked_names:
      return
    for sid in list(_host_sids):
      _socketio.emit('host_message_toast', payload, to=sid)


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
  elif c == 'open':
    if not is_buzzer_round:
      return False
    _reset_buzzer(open_after_reset=True)
    _submitted_answers = []
    _submitted_sids = set()
    _pending_selections = {}
    _broadcast_players_update()
    _emit_peer_answers_update()
    if _host_sids:
      for sid in list(_host_sids):
        _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)
  else:
    return False
  _emit_buzzer_state()
  return True


def buzzer_is_locked() -> bool:
  return bool(_buzzer_locked)


def set_player_buzzer_disabled(name: str, disabled: bool) -> bool:
  name = str(name or '').strip()
  if not name:
    return False
  before = name in _buzzer_disabled_names
  if disabled:
    _buzzer_disabled_names.add(name)
  else:
    _buzzer_disabled_names.discard(name)
  after = name in _buzzer_disabled_names
  if before == after:
    return after
  _broadcast_players_update()
  _emit_buzzer_state()
  if _on_buzzer_lock_callback is not None:
    try:
      _on_buzzer_lock_callback(name, after)
    except Exception:
      pass
  return after


def toggle_player_buzzer_disabled(name: str) -> bool:
  name = str(name or '').strip()
  return set_player_buzzer_disabled(name, name not in _buzzer_disabled_names)


def get_buzzer_disabled_names() -> list[str]:
  return sorted(_buzzer_disabled_names)


_PLAYER_COLOR_MATCH_THRESHOLD = 32


def _normalize_hex_color(color: str) -> str:
    color = str(color or '').strip().lower()
    if len(color) == 4 and color.startswith('#'):
        return '#' + ''.join(ch * 2 for ch in color[1:])
    return color


def _color_rgb(color: str) -> tuple[int, int, int] | None:
    color = _normalize_hex_color(color)
    if not color:
        return None
    if len(color) == 7 and color.startswith('#'):
        try:
            return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        except ValueError:
            return None
    return color_to_rgb(color)


def _player_colors_too_close(bg: str, text: str) -> bool:
    bg_rgb = _color_rgb(bg)
    text_rgb = _color_rgb(text)
    if not bg_rgb or not text_rgb:
        return _normalize_hex_color(bg) == _normalize_hex_color(text)
    return max(abs(a - b) for a, b in zip(bg_rgb, text_rgb)) <= _PLAYER_COLOR_MATCH_THRESHOLD


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*rgb)


def _nudge_player_text_color(bg: str, text: str) -> str:
    bg_rgb = _color_rgb(bg)
    text_rgb = _color_rgb(text)
    if not bg_rgb or not text_rgb:
        return text

    target_delta = _PLAYER_COLOR_MATCH_THRESHOLD + 1
    diffs = [text_rgb[i] - bg_rgb[i] for i in range(3)]
    ranked_channels = sorted(range(3), key=lambda i: abs(diffs[i]), reverse=True)

    for idx in ranked_channels:
        direction = 1 if diffs[idx] >= 0 else -1
        target = bg_rgb[idx] + direction * target_delta
        if 0 <= target <= 255:
            nudged = list(text_rgb)
            nudged[idx] = target
            return _rgb_to_hex(tuple(nudged))

    for idx in ranked_channels:
        direction = -1 if diffs[idx] >= 0 else 1
        target = bg_rgb[idx] + direction * target_delta
        if 0 <= target <= 255:
            nudged = list(text_rgb)
            nudged[idx] = target
            return _rgb_to_hex(tuple(nudged))

    return text


def _sanitize_player_colors(bg: str, text: str) -> tuple[str, str]:
    if bg and text and _player_colors_too_close(bg, text):
        text = _nudge_player_text_color(bg, text)
    return bg, text


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
# Mobile-friendly HTML page
# ---------------------------------------------------------------------------
# The full HTML/CSS/JS web client lives in web_client_html.py as a module-level
# string so PyInstaller still bundles it into the single exe (no data files or
# _MEIPASS handling), keeping this file focused on server logic.
from _app_scripts.file.web_server.web_client_html import HTML as _HTML


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


def push_question(title, info='', choices=None, drum=None, stepper=None, tags=None, year=None, tags_max=None, autocomplete=None, rank_slider=None, buzzer_only=False, character_choices=None, character_picks=None):
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
    if autocomplete:        _current_question['autocomplete']       = autocomplete
    if buzzer_only:         _current_question['buzzer_only']        = True
    if character_choices:   _current_question['character_choices']  = character_choices
    if character_picks:     _current_question['character_picks']    = character_picks

    # Reset buzzer each round.
    # Buzzer bonus starts unlocked; other questions keep buzzer closed.
    _reset_buzzer(open_after_reset=bool(buzzer_only))
    _socketio.emit('question', _current_question)
    # Clear any pending skip grant when a new question starts
    push_skip_grant('')
    _emit_buzzer_state()


def push_skip_grant(name: str):
    """Grant or revoke a one-time skip for a specific player.
    Pass empty string to clear the current grant."""
    global _skip_grant_player
    prev = _skip_grant_player
    _skip_grant_player = name
    if not _socketio:
        return
    # Revoke previous holder
    if prev and prev != name:
        for sid, pname in list(_connected_players.items()):
            if pname == prev:
                _socketio.emit('skip_grant_update', {'active': False}, to=sid)
    # Grant new holder
    if name:
        for sid, pname in list(_connected_players.items()):
            if pname == name:
                _socketio.emit('skip_grant_update', {'active': True}, to=sid)
    # Always push to all hosts so their row buttons refresh
    _socketio.emit('skip_grant_host_update', {'name': name})
    if _on_skip_grant_callback is not None:
        try:
            _on_skip_grant_callback(name)
        except Exception:
            pass


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


def reveal_answer(correct_display: str, q_type: str = '', correct_tags: list = None,
                  score_hints: dict = None, player_scores: dict = None):
    """Broadcast the correct answer for the just-completed question to all clients.

    score_hints:   optional {player_name: 'exact'|'close'|'none'} for colour-coding.
    player_scores: optional {player_name: float} — points each player earned.
    """
    if not FLASK_AVAILABLE or _socketio is None:
        return
    q = _current_question or {}
    title = q.get('title', '')
    # Build a display-only question_data subset (no initial/interactive fields)
    question_data = {}
    if q.get('choices'):
        question_data['choices'] = q['choices']
    if q.get('tags'):
        question_data['tags'] = q['tags']
        question_data['tags_max'] = q.get('tags_max', len(q['tags']))
    if q.get('rank_slider'):
        rs = q['rank_slider']
        question_data['rank_slider'] = {'min': rs.get('min', 1), 'max': rs.get('max', 9999)}
    if q.get('character_choices'):
        question_data['character_choices'] = q['character_choices']
        question_data['character_picks']   = q.get('character_picks', 1)
    _socketio.emit('answer_reveal', {
        'question': title,
        'correct': correct_display,
        'q_type': q_type,
        'correct_tags': correct_tags or [],
        'question_data': question_data,
        'all_answers': list(_submitted_answers),
        'score_hints': score_hints or {},
        'player_scores': player_scores or {},
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
    push_skip_grant('')


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


def get_connected_player_names():
    """Return a list of currently connected player names (including hosts)."""
    return list(_connected_players.values())


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


def _sanitize_for_json(obj):
    """Recursively replace float inf/nan with None so the payload is JSON-safe."""
    import math
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def push_metadata(data_dict: dict):
    """Push currently-playing metadata to all connected host clients.

    data_dict should contain fields mirroring what update_metadata() renders in
    the left column (title, eng_title, aired, score, members, tags, studios, etc.).
    Pass an empty dict to clear the metadata panel.
    """
    global _current_metadata
    _current_metadata = _sanitize_for_json(data_dict or {})
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


def push_archived_youtube_list(videos: list, queued_id: str = None):
    """Push archived YouTube video list to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'videos': videos, 'queued_id': queued_id}
        for sid in list(_host_sids):
            _socketio.emit('archived_youtube_list', payload, to=sid)


def push_lightning_presets_list(presets: list, selected: str = None):
    """Push lightning settings preset list to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'presets': presets, 'selected': selected}
        for sid in list(_host_sids):
            _socketio.emit('lightning_presets_list', payload, to=sid)


def push_fixed_lightning_list(rounds: list, queued_name: str = None):
    """Push fixed lightning round list to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'rounds': rounds, 'queued_name': queued_name}
        for sid in list(_host_sids):
            _socketio.emit('fixed_lightning_list', payload, to=sid)


def push_rules_list(files: list, selected_file: str = None):
    """Push available rules files list to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'files': files, 'selected': selected_file}
        for sid in list(_host_sids):
            _socketio.emit('rules_list', payload, to=sid)


def push_playlist_list(names: list, system_names: list = None, current: str = None, changed: bool = False):
    """Push available saved playlist names to all host clients."""
    if FLASK_AVAILABLE and _socketio and _host_sids:
        payload = {'names': names, 'system_names': system_names or [], 'current': current, 'changed': changed}
        for sid in list(_host_sids):
            _socketio.emit('playlist_list', payload, to=sid)


def push_filter_list(filters: list, to_sid: str = None):
    """Push available saved playlist-filter names to host clients."""
    if FLASK_AVAILABLE and _socketio:
        payload = {'filters': filters}
        sids = [to_sid] if to_sid else list(_host_sids)
        for sid in sids:
            _socketio.emit('filter_list', payload, to=sid)


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


def push_playback_state(current_ms: int, length_ms: int, playing: bool, volume: int = None, autoplay: int = None, bgm_modifier: float = None, bzz_modifier: float = None, strm_boost: int = None):
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
    if strm_boost is not None:
        _playback_state['strm_boost'] = int(strm_boost)
    if FLASK_AVAILABLE and _socketio and _host_sids:
        for sid in list(_host_sids):
            _socketio.emit('playback_state', _playback_state, to=sid)


def push_scores(data: dict):
    """Push scoreboard player data to all connected clients."""
    if FLASK_AVAILABLE and _socketio:
        _socketio.emit('scores_update', data)


def push_score_history(entries: list, to_sid: str = None):
    """Push score change history entries to host client(s)."""
    if not FLASK_AVAILABLE or not _socketio:
        return
    payload = {'entries': entries}
    if to_sid:
        _socketio.emit('score_history', payload, to=to_sid)
    else:
        for sid in list(_host_sids):
            _socketio.emit('score_history', payload, to=sid)


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


def set_skip_grant_callback(fn):
    """Register a callable(name: str) invoked when the skip grant changes. Empty string = cleared."""
    global _on_skip_grant_callback
    _on_skip_grant_callback = fn


def set_buzzer_lock_callback(fn):
    """Register a callable(name: str, locked: bool) for per-player buzzer locks."""
    global _on_buzzer_lock_callback
    _on_buzzer_lock_callback = fn


def get_skip_grant_player() -> str:
    """Return the name of the player currently holding the skip grant, or empty string."""
    return _skip_grant_player


def start(port=8080, ngrok_domain=None, cloudflare_token=None, cloudflare_url=None):
    """Start the Flask/SocketIO server in a daemon thread, optionally launch ngrok.

    Returns True if server started, False if Flask is unavailable.
    Subsequent start() calls after stop() reuse the same thread and SocketIO
    instance to avoid the "address already in use" crash that would cause all
    server-to-client emits to silently fail.
    """
    global _server_started, _server_thread, _server_port
    global _ngrok_process, _cloudflared_process, public_url
    _server_port = port
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
    if cloudflare_token and cloudflare_url:
        _cloudflared_process, url = web_tunnels.start_cloudflared(cloudflare_token, cloudflare_url)
        if url:
            public_url = url
    elif ngrok_domain:
        _ngrok_process, url = web_tunnels.start_ngrok(ngrok_domain, port)
        if url:
            public_url = url
    else:
        print(f"[Web Server] Running locally on port {port} (no tunnel configured.)")
    return True


def stop():
    """Mark the server as stopped and clean up ngrok + ephemeral connection state.

    The underlying Flask/SocketIO/Werkzeug thread is intentionally left running
    so that the same _socketio instance stays alive. Killing it would leave the
    old thread holding port 8080 while the new _socketio (created in the next
    start() call) has no active server, causing all server-to-client emits to be
    silently discarded after restart.
    """
    global _ngrok_process, _cloudflared_process, _server_started
    _server_started = False
    if _ngrok_process:
        try:
            _ngrok_process.terminate()
        except Exception:
            pass
        _ngrok_process = None
    if _cloudflared_process:
        try:
            _cloudflared_process.terminate()
        except Exception:
            pass
        _cloudflared_process = None
    # Clear ephemeral connection state so the next start() is fresh.
    global _connected_players, _host_sids, _submitted_sids, _player_meta
    try:
        _connected_players.clear()
    except Exception:
        _connected_players = {}
    try:
        _player_meta.clear()
    except Exception:
        _player_meta = {}
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

    @_app.route('/proxy_image')
    def proxy_image():
        from flask import request as _req, Response
        import urllib.request as _ur
        import urllib.parse as _up
        url = _req.args.get('url', '')
        # Only proxy images from AniDB CDN to prevent SSRF
        parsed = _up.urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc.endswith('anidb.net'):
            return Response('Forbidden', status=403)
        try:
            with _ur.urlopen(_ur.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=10) as resp:
                data = resp.read()
                ct = resp.headers.get_content_type() or 'image/jpeg'
            return Response(data, content_type=ct)
        except Exception:
            return Response('Not Found', status=404)

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
        name = str(data.get('name', '')).strip()
        bg   = str(data.get('bg',   '')).strip()
        text = str(data.get('text', '')).strip()
        if not name:
            return
        bg, text = _sanitize_player_colors(bg, text)
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
        if _req_client_ip(_req) in _hard_banned_ips:
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
        # Send skip grant if this player is the granted one
        name_on_connect = _connected_players.get(_req.sid, '')
        if name_on_connect and name_on_connect == _skip_grant_player:
            emit('skip_grant_update', {'active': True})
        # Send playback state to newly-connected hosts after they authenticate via claim_host

    @_socketio.on('disconnect')
    def on_disconnect():
        from flask import request as _req
        _host_sids.discard(_req.sid)
        _connected_players.pop(_req.sid, None)
        _player_meta.pop(_req.sid, None)
        _submitted_sids.discard(_req.sid)
        _broadcast_players_update()

    @_socketio.on('set_name')
    def handle_set_name(data):
        from flask import request as _req
        name = str(data.get('name', '')).strip()
        if not name:
            return
        _connected_players[_req.sid] = name
        # Record per-device metadata (join time + IP) for the host duplicate view.
        # Keep the original join time if this sid is just re-asserting its name.
        existing = _player_meta.get(_req.sid)
        if existing:
            existing['name'] = name
        else:
            _ip = _sid_client_ip(_req.sid)
            _player_meta[_req.sid] = {'join_ms': int(time.time() * 1000), 'ip': _ip, 'name': name}
        emit('emoji_status', _get_emoji_status(name))
        _emit_host_messages(to_sid=_req.sid)
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
            emit('host_messages_update', {'messages': _host_visible_messages()})
        else:
            emit('host_denied', {})

    @_socketio.on('host_message_send')
    def handle_host_message_send(data):
        from flask import request as _req
        if _req_client_ip(_req) in _shadow_kicked_ips:
            return
        name = _connected_players.get(_req.sid, '').strip()
        if not name or name in _banned_names:
            return
        if name in _message_blocked_names:
            return
        text = str((data or {}).get('text', '')).strip()
        if not text:
            return
        text = text[:280]
        entry = {'name': name, 'text': text, 'ts': int(time.time() * 1000),
                 'sender': 'player', 'to': ''}
        _host_messages.append(entry)
        if len(_host_messages) > 500:
            del _host_messages[:-500]
        _emit_host_messages()
        _emit_host_message_toast(entry)

    @_socketio.on('host_message_reply')
    def handle_host_message_reply(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        text = str((data or {}).get('text', '')).strip()
        if not text:
            return
        text = text[:280]
        to = str((data or {}).get('to', '')).strip()[:50]
        if to.lower() == 'all':
            to = 'all'
        host_name = _connected_players.get(_req.sid, '').strip() or 'Host'
        entry = {'name': host_name, 'text': text, 'ts': int(time.time() * 1000),
                 'sender': 'host', 'to': to}
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

    @_socketio.on('host_message_block')
    def handle_host_message_block(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str((data or {}).get('name', '')).strip()[:50]
        if not name:
            return
        blocked = (data or {}).get('blocked')
        if blocked is None:
            blocked = name not in _message_blocked_names
        if bool(blocked):
            _message_blocked_names.add(name)
        else:
            _message_blocked_names.discard(name)
        _emit_host_messages()
        _broadcast_players_update()

    @_socketio.on('host_message_notifications_block')
    def handle_host_message_notifications_block(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str((data or {}).get('name', '')).strip()[:50]
        if not name:
            return
        blocked = (data or {}).get('blocked')
        if blocked is None:
            blocked = name not in _message_notifications_blocked_names
        if bool(blocked):
            _message_notifications_blocked_names.add(name)
        else:
            _message_notifications_blocked_names.discard(name)
        _broadcast_players_update()

    @_socketio.on('select_answer')
    def handle_select(data):
      from flask import request as _req
      if _req_client_ip(_req) in _shadow_kicked_ips:
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
      if _req_client_ip(_req) in _shadow_kicked_ips:
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

        # Migrate message-thread entries (player sends keyed by name, host
        # replies targeted by name) so the renamed player keeps their thread.
        msgs_changed = False
        for m in _host_messages:
            if m.get('sender') == 'host':
                if m.get('to') == old_name:
                    m['to'] = new_name
                    msgs_changed = True
            elif m.get('name') == old_name:
                m['name'] = new_name
                msgs_changed = True

        if old_name in _message_blocked_names:
            _message_blocked_names.discard(old_name)
            _message_blocked_names.add(new_name)
        if old_name in _message_notifications_blocked_names:
            _message_notifications_blocked_names.discard(old_name)
            _message_notifications_blocked_names.add(new_name)
        buzzer_lock_migrated = False
        if old_name in _buzzer_disabled_names and new_name not in _buzzer_disabled_names:
            _buzzer_disabled_names.discard(old_name)
            _buzzer_disabled_names.add(new_name)
            buzzer_lock_migrated = True

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
        if buzzer_lock_migrated:
            _emit_buzzer_state()
            if _on_buzzer_lock_callback is not None:
                try:
                    _on_buzzer_lock_callback(old_name, False)
                    _on_buzzer_lock_callback(new_name, True)
                except Exception:
                    pass
        _emit_peer_answers_update()
        if msgs_changed:
            _emit_host_messages()
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
                ip = _sid_client_ip(sid) or ip
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
                ip = _sid_client_ip(sid) or ip
                if ip:
                    _hard_banned_ips.add(ip)
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

    @_socketio.on('remove_device')
    def handle_remove_device(data):
        """Drop a single device's connection by sid (host duplicate-device view).

        Unlike remove_player (which targets every socket sharing a name), this
        severs only the one connection so a legitimate same-name device stays.
        Shared answer/scoreboard identity is left intact; the person can rejoin.
        """
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        target = str((data or {}).get('sid', '')).strip()
        if not target or target not in _connected_players:
            return
        try:
            _socketio.server.disconnect(target)
        except Exception:
            pass
        _connected_players.pop(target, None)
        _player_meta.pop(target, None)
        _submitted_sids.discard(target)
        _host_sids.discard(target)
        _broadcast_players_update()

    @_socketio.on('ip_ban_device')
    def handle_ip_ban_device(data):
        """IP-ban + disconnect a single device by sid (host duplicate-device view).

        Bans only that socket's IP. If the banned IP is shared with a legit
        same-name device the host was warned via the same_ip flag in the UI.
        """
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        target = str((data or {}).get('sid', '')).strip()
        if not target or target not in _connected_players:
            return
        name = _connected_players.get(target, '')
        ip = (_player_meta.get(target) or {}).get('ip') or _sid_client_ip(target)
        if ip:
            _hard_banned_ips.add(ip)
        try:
            _socketio.server.disconnect(target)
        except Exception:
            pass
        _connected_players.pop(target, None)
        _player_meta.pop(target, None)
        _submitted_sids.discard(target)
        _host_sids.discard(target)
        # Only flag the whole name as kicked (and strip its answers) if no other
        # device still holds that name — otherwise a legit device stays untouched.
        if name and not any(pname == name for pname in _connected_players.values()):
            _shadow_kicked_players[name] = ip
            _submitted_answers[:] = [a for a in _submitted_answers if a['name'] != name]
        _broadcast_players_update()
        _emit_peer_answers_update()
        for sid in list(_host_sids):
            _socketio.emit('answer_update', {'answers': list(_submitted_answers)}, to=sid)

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
        if _req_client_ip(_req) in _shadow_kicked_ips:
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

        # Count emoji units: ZWJ sequences/flags count as 1, everything else per codepoint.
        import re as _re
        _egc = _re.compile(
            r'[\U0001F1E0-\U0001F1FF]{2}'   # regional indicator flag pairs
            r'|(?:[^\u200D\uFE0F\u20E3][\uFE0F\u20E3]?(?:\u200D[^\u200D\uFE0F\u20E3][\uFE0F]?)+)'  # ZWJ sequences
            r'|[^\u200D\uFE0F\u20E3][\uFE0F\u20E3]?',  # single emoji (with optional variation/keycap)
        )
        emoji_unit_count = max(1, len(_egc.findall(emoji)))

        # Keep only recent events within longest relevant window.
        # burst_dq tracks socket events (1 per send, regardless of set size) for click-rate detection.
        # dq tracks emoji units (set size counts) for the rolling-window volume threshold.
        max_window = max(_EMOJI_WINDOW_SECONDS, _EMOJI_BURST_WINDOW_SECONDS)
        while dq and (now - dq[0]) > max_window:
            dq.popleft()
        for _ in range(max(1, round(emoji_unit_count / 2))):
            dq.append(now)

        # Burst guard: counts socket events, not emoji units, to detect rapid clicking/autoclicking.
        burst_dq = _emoji_events_by_name.get(name + '__burst')
        if burst_dq is None:
            burst_dq = deque()
            _emoji_events_by_name[name + '__burst'] = burst_dq
        while burst_dq and (now - burst_dq[0]) > _EMOJI_BURST_WINDOW_SECONDS:
            burst_dq.popleft()
        burst_dq.append(now)
        burst_count = len(burst_dq)
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
      if _req_client_ip(_req) in _shadow_kicked_ips:
        return
      name = _connected_players.get(_req.sid, '').strip()
      if not name or name in _banned_names:
        return
      if (not _current_question) or (not _current_question.get('buzzer_only')):
        return
      if (not _buzzer_open) or _buzzer_locked or name in _buzzer_disabled_names:
        if name in _buzzer_disabled_names:
          emit('buzzer_state', {'open': bool(_buzzer_open), 'locked': bool(_buzzer_locked), 'order': [{'name': str(a.get('name', ''))} for a in list(_submitted_answers)] if (_current_question and _current_question.get('buzzer_only')) else [], 'disabled_names': sorted(_buzzer_disabled_names)})
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

    @_socketio.on('toggle_skip_grant')
    def handle_toggle_skip_grant(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str((data or {}).get('name', '')).strip()
        # Toggle: if already granted to this player, revoke; otherwise grant
        new_name = '' if (_skip_grant_player == name) else name
        push_skip_grant(new_name)

    @_socketio.on('toggle_buzzer_lock')
    def handle_toggle_buzzer_lock(data):
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        name = str((data or {}).get('name', '')).strip()
        if name:
            toggle_player_buzzer_disabled(name)

    @_socketio.on('player_skip_request')
    def handle_player_skip_request(data):
        from flask import request as _req
        name = _connected_players.get(_req.sid, '').strip()
        if not name or name != _skip_grant_player:
            return
        if name in _banned_names or _req_client_ip(_req) in _shadow_kicked_ips:
            return
        # Consume the grant (one-time use)
        push_skip_grant('')
        # Seek to last 3 seconds instead of skipping to next track
        if _host_action_callback is not None:
            try:
                _host_action_callback('seek_near_end', {'_sid': None})
            except Exception:
                pass

    @_socketio.on('player_skip_decline')
    def handle_player_skip_decline(data):
        from flask import request as _req
        name = _connected_players.get(_req.sid, '').strip()
        if not name or name != _skip_grant_player:
            return
        if name in _banned_names or _req_client_ip(_req) in _shadow_kicked_ips:
            return
        push_skip_grant('')

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

    @_socketio.on('request_archived_youtube_list')
    def handle_request_archived_youtube_list():
        from flask import request as _req
        if _req.sid not in _host_sids:
            return
        if _host_action_callback is not None:
            try:
                _host_action_callback('get_archived_youtube_list', {'_sid': _req.sid})
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
        else:
            continue
        players.append({
          'name': name,
          'submitted': name in submitted_names,
          'kicked': False,
          'host': name in host_names,
          'emoji_muted': name in _emoji_disabled_names,
          'messages_blocked': name in _message_blocked_names,
          'message_notifications_blocked': name in _message_notifications_blocked_names,
          'buzzer_locked': name in _buzzer_disabled_names,
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
          'messages_blocked': name in _message_blocked_names,
          'message_notifications_blocked': name in _message_notifications_blocked_names,
          'buzzer_locked': name in _buzzer_disabled_names,
        })
    # Deduped list goes to everyone (player-facing UI is unchanged).
    _socketio.emit('players_update', {'players': players})
    # Hosts additionally get a per-device list so duplicate-name connections
    # (e.g. an impostor joining under another player's name) are individually
    # visible and kickable. This overrides the deduped list above for hosts only.
    if _host_sids:
        # Group connected sids by name, ordered by join time.
        by_name = {}
        for sid, name in _connected_players.items():
            meta = _player_meta.get(sid) or {}
            by_name.setdefault(name, []).append(
                (sid, meta.get('join_ms', 0), meta.get('ip')))
        host_players = []
        for name, devices in by_name.items():
            devices.sort(key=lambda d: d[1])
            ips = [d[2] for d in devices if d[2]]
            for idx, (sid, join_ms, ip) in enumerate(devices, start=1):
                same_ip = bool(ip and ips.count(ip) > 1)
                host_players.append({
                  'name': name,
                  'sid': sid,
                  'dup_index': idx,
                  'dup_total': len(devices),
                  'join_ms': join_ms,
                  'ip': ip or '',
                  'same_ip': same_ip,
                  'submitted': name in submitted_names,
                  'kicked': False,
                  'host': name in host_names,
                  'emoji_muted': name in _emoji_disabled_names,
                  'messages_blocked': name in _message_blocked_names,
                  'message_notifications_blocked': name in _message_notifications_blocked_names,
                  'buzzer_locked': name in _buzzer_disabled_names,
                })
        for name in _shadow_kicked_players:
            host_players.append({
              'name': name,
              'sid': '',
              'dup_index': 1,
              'dup_total': 1,
              'join_ms': 0,
              'ip': '',
              'same_ip': False,
              'submitted': name in submitted_names,
              'kicked': True,
              'host': False,
              'emoji_muted': name in _emoji_disabled_names,
              'messages_blocked': name in _message_blocked_names,
              'message_notifications_blocked': name in _message_notifications_blocked_names,
              'buzzer_locked': name in _buzzer_disabled_names,
            })
        for _hsid in list(_host_sids):
            _socketio.emit('players_update', {'players': host_players}, to=_hsid)
