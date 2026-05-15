"""scoreboard_control.py — Scoreboard integration for Guess the Anime!

Handles:
  - Socket communication to the running scoreboard process
  - Process detection and launching
  - Score-change log reading
  - Rules file loading and formatting
  - GitHub release checking and exe downloading
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time

import requests

# ── Paths (resolved relative to the project root, not the cwd) ────────────────
# When frozen by PyInstaller (--onefile), __file__ points into a temp extraction
# directory. sys.executable is always the real exe / script location.
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Detection ─────────────────────────────────────────────────────────────────

AVAILABLE = (
    os.path.isfile(os.path.join(_ROOT_DIR, "scoreboard.exe")) or
    os.path.isfile(os.path.join(_ROOT_DIR, "scoreboard.py")) or
    os.path.isfile(os.path.join(_ROOT_DIR, "universal_scoreboard.exe")) or
    os.path.isfile(os.path.join(_ROOT_DIR, "universal_scoreboard.py"))
)

RULES_FOLDER   = os.path.join(_ROOT_DIR, "rules")
_DATA_FOLDER   = os.path.join(_ROOT_DIR, "scoreboard_data")
_GITHUB_REPO   = "ualkotob/universal-scoreboard"
_API_URL       = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_RELEASES_PAGE = f"https://github.com/{_GITHUB_REPO}/releases"

# ── Module state ──────────────────────────────────────────────────────────────

visible_hint      = None   # None = unknown, True = visible, False = hidden
_colors_sent      = False
_align_sent       = False
version_seen      = ""     # latest release tag the user has been notified about
_update_available = None   # None = unchecked, True = update found, False = current

# ── Dependency callbacks (set by main app) ────────────────────────────────────

_colors_getter   = None   # callable() → (bg_color, text_color)
_inverted_getter = None   # callable() → bool


def set_getters(colors_fn=None, inverted_fn=None):
    """Register callbacks so the module can read live app colours/layout settings.

    Call once at startup:
        scoreboard_control.set_getters(
            colors_fn=lambda: (OVERLAY_BACKGROUND_COLOR, OVERLAY_TEXT_COLOR),
            inverted_fn=lambda: inverted_positions,
        )
    """
    global _colors_getter, _inverted_getter
    if colors_fn is not None:
        _colors_getter = colors_fn
    if inverted_fn is not None:
        _inverted_getter = inverted_fn


# ── Socket communication ──────────────────────────────────────────────────────

def send_command(cmd):
    """Send *cmd* to the scoreboard over localhost:5555 (non-blocking)."""
    global visible_hint
    _cmd = str(cmd).strip().lower()
    if _cmd == "show":
        visible_hint = True
    elif _cmd in ("hide", "quit"):
        visible_hint = False
    elif _cmd == "toggle":
        visible_hint = (not visible_hint) if isinstance(visible_hint, bool) else None

    def _worker():
        global _colors_sent, _align_sent
        try:
            s = socket.socket()
            s.connect(("localhost", 5555))
            s.sendall(cmd.encode())
            s.close()
            if not _colors_sent:
                _colors_sent = True
                send_colors()
            if not _align_sent:
                _align_sent = True
        except ConnectionRefusedError:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def is_running():
    """Return True if the scoreboard is listening on port 5555."""
    try:
        s = socket.socket()
        s.settimeout(0.1)
        s.connect(("localhost", 5555))
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def open_scoreboard():
    """Launch the scoreboard executable or script if not already running."""
    global visible_hint
    if is_running():
        return
    for exe in ("universal_scoreboard.exe", "scoreboard.exe"):
        if os.path.isfile(exe):
            visible_hint = True
            subprocess.Popen([exe], creationflags=subprocess.CREATE_NEW_CONSOLE)
            return
    for script in ("universal_scoreboard.py", "scoreboard.py"):
        if os.path.isfile(script):
            visible_hint = True
            subprocess.Popen([sys.executable, script], creationflags=subprocess.CREATE_NEW_CONSOLE)
            return


def send_colors(bg=None, text=None):
    """Send colour settings to the scoreboard.

    With no arguments the stored callback values are used; explicit *bg*/*text*
    override them.
    """
    if bg is None or text is None:
        if _colors_getter:
            _bg, _txt = _colors_getter()
            bg   = bg   or _bg
            text = text or _txt
    if bg and text:
        send_command(f"[COLORS][BACK]{bg}[TEXT]{text}")


def send_score(player_name, delta):
    """Tell the scoreboard to apply *delta* to *player_name*'s score."""
    send_command(f"[SCORE_WRITE][PLAYER]{player_name}[DELTA]{delta}")


def send_align(inverted=None):
    """Send alignment command based on *inverted* flag (or stored callback)."""
    if inverted is None and _inverted_getter:
        inverted = _inverted_getter()
    send_command("align right" if inverted else "align left")


# ── Score-change log ──────────────────────────────────────────────────────────

def read_score_changes():
    """Read all score-change entries from scoreboard_data/score_changes.json."""
    try:
        path = os.path.join(_DATA_FOLDER, "score_changes.json")
        if not os.path.exists(path):
            return []
        changes = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    changes.append(json.loads(line))
        return changes
    except Exception as e:
        print(f"[Scoreboard] Error reading score changes: {e}")
        return []


def add_score_changes_to_session(session_data):
    """Merge scoreboard score-change entries into *session_data* (in-place, no duplicates)."""
    existing_ts = {
        e.get("timestamp")
        for e in session_data
        if e.get("type") == "scoreboard_score"
    }
    for change in read_score_changes():
        if change.get("timestamp") in existing_ts:
            continue
        session_data.append({
            "timestamp": change["timestamp"],
            "type":      "scoreboard_score",
            "player":    change["player"],
            "old_score": change["old_score"],
            "new_score": change["new_score"],
            "delta":     change["delta"],
        })


# ── Rules ─────────────────────────────────────────────────────────────────────

def get_available_rules_files(folder=None):
    """Return a list of .json rule filenames in *folder*, always starting with ''."""
    folder = folder or RULES_FOLDER
    try:
        files = [
            f for f in os.listdir(folder)
            if f.endswith(".json") and os.path.isfile(os.path.join(folder, f))
        ]
        return [""] + sorted(files)
    except FileNotFoundError:
        return [""]


def load_rules(filename=None, folder=None):
    """Load a rules JSON from *folder*/*filename*.  Returns {} on failure or empty name."""
    folder = folder or RULES_FOLDER
    if not filename:
        return {}
    path = os.path.join(folder, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"[Scoreboard] Error parsing rules '{path}': {e}")
        return {}


def set_rules(rules_dict, type=None, web_server=None, push_web_toggles=None):
    """Format *rules_dict* and send it to the scoreboard (and web clients if running)."""
    if not rules_dict:
        return

    rules_txt = f"[RULES]{chr(10).join(rules_dict.get('global_title', []))}\n"
    if type == "anime":
        rules_txt += "\n".join(rules_dict.get("lightning_anime", []))
    elif type == "character":
        rules_txt += "\n".join(rules_dict.get("lightning_character", []))
    elif type == "trivia":
        rules_txt += "\n".join(rules_dict.get("lightning_trivia", []))
    else:
        rules_txt += "\n".join(rules_dict.get("standard", []))
    if rules_dict.get("global_end"):
        rules_txt += "\n" + "\n".join(rules_dict.get("global_end", []))

    if web_server is not None:
        web_header = "\n".join(rules_dict.get("global_title", []))
        web_rules  = rules_txt.replace("[RULES]", "", 1)
        if web_header:
            web_rules = web_rules.replace(web_header, "", 1)
        web_server.set_rules_text(web_header, web_rules.strip())

        if web_server.is_running():
            if push_web_toggles:
                push_web_toggles()
            footer = "\n".join(rules_dict.get("server_footer", []))
            url    = web_server.get_url().replace("http://", "").replace("https://", "")
            rules_txt += "\n" + footer.replace("[URL]", url)

    send_command(rules_txt)


# ── GitHub release helpers ────────────────────────────────────────────────────

def _fetch_latest_release():
    """Return (tag, download_url, body) for the latest scoreboard release, or raise."""
    resp = requests.get(_API_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    tag  = data.get("tag_name", "")
    body = data.get("body", "")
    url  = next(
        (a["browser_download_url"] for a in data.get("assets", [])
         if a["name"] == "universal_scoreboard.exe"),
        None,
    )
    return tag, url, body


def download_scoreboard(root, highlight_color, window_pos_fn, save_config_fn, on_complete_fn=None):
    """Show a confirmation dialog then download *universal_scoreboard.exe* from GitHub."""
    import tkinter as tk
    from tkinter import messagebox

    confirmed = messagebox.askyesno(
        "Download Universal Scoreboard",
        "Universal Scoreboard is a separate overlay program that works alongside "
        "the Guess the Anime! Playlist Tool.\n\n"
        "It shows a live scoreboard for your players during sessions, lets you "
        "adjust scores, archive past sessions, and more.\n\n"
        "Download universal_scoreboard.exe from GitHub?\n"
        "(~45 MB, saved next to this program)",
    )
    if not confirmed:
        return

    def _do_download():
        try:
            tag, url, _ = _fetch_latest_release()
            if not url:
                root.after(0, lambda: messagebox.showerror(
                    "Download Failed",
                    "Could not find universal_scoreboard.exe in the latest release.\n"
                    f"Please download manually:\n{_RELEASES_PAGE}",
                ))
                return

            dest = "universal_scoreboard.exe"
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total      = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(dest + ".tmp", "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = int(downloaded * 100 / total)
                                root.after(0, lambda p=pct: _sb_dl_progress(p))
            os.replace(dest + ".tmp", dest)

            global AVAILABLE, version_seen, _update_available
            AVAILABLE         = True
            version_seen      = tag
            _update_available = False
            save_config_fn()

            root.after(0, lambda: messagebox.showinfo(
                "Download Complete",
                f"universal_scoreboard.exe downloaded (version {tag}).\n\n"
                "You can now launch it from the FILE menu → Open Scoreboard.",
            ))
            if on_complete_fn:
                root.after(0, on_complete_fn)
        except Exception as e:
            try:
                os.remove("universal_scoreboard.exe.tmp")
            except OSError:
                pass
            root.after(0, lambda: messagebox.showerror(
                "Download Failed",
                f"Could not download the scoreboard:\n{e}\n\n"
                f"Download manually from:\n{_RELEASES_PAGE}",
            ))
        finally:
            root.after(0, _sb_dl_close)

    # Progress window
    _sb_dl_win = tk.Toplevel(root)
    _sb_dl_win.title("Downloading Scoreboard…")
    _sb_dl_win.configure(bg="black")
    _sb_dl_win.resizable(False, False)
    _sb_dl_win.transient(root)
    _sb_dl_win.grab_set()
    window_pos_fn(_sb_dl_win, offset_x=100, offset_y=100)
    tk.Label(_sb_dl_win, text="Downloading universal_scoreboard.exe…",
             bg="black", fg="white", font=("Arial", 11)).pack(padx=20, pady=(16, 6))
    _sb_pct_var = tk.StringVar(value="0%")
    tk.Label(_sb_dl_win, textvariable=_sb_pct_var,
             bg="black", fg=highlight_color, font=("Arial", 13, "bold")).pack(pady=(0, 16))

    def _sb_dl_progress(pct):
        try:
            _sb_pct_var.set(f"{pct}%")
            _sb_dl_win.update_idletasks()
        except Exception:
            pass

    def _sb_dl_close():
        try:
            _sb_dl_win.grab_release()
            _sb_dl_win.destroy()
        except Exception:
            pass

    threading.Thread(target=_do_download, daemon=True).start()


def check_for_update(root, save_config_fn, silent_if_current=True):
    """Check GitHub for a newer scoreboard release and prompt to update if found."""
    import webbrowser
    from tkinter import messagebox

    global version_seen, _update_available
    if not AVAILABLE:
        return
    try:
        tag, url, body = _fetch_latest_release()
        if not tag:
            return

        if tag == version_seen:
            _update_available = False
            if not silent_if_current:
                messagebox.showinfo(
                    "Scoreboard Up to Date",
                    f"You already have the latest scoreboard (version {tag}).",
                )
            return

        local_exists = os.path.isfile("universal_scoreboard.exe") or os.path.isfile("scoreboard.exe")
        if local_exists and not version_seen and silent_if_current:
            # Existing exe with unknown local version — avoid false startup prompts.
            return
        if not local_exists and silent_if_current:
            return

        _update_available = True
        result = messagebox.askyesno(
            "Scoreboard Update Available",
            f"A new version of Universal Scoreboard is available!\n\n"
            f"Version: {tag}\n\n"
            f"Release notes:\n{body[:300]}{'…' if len(body) > 300 else ''}\n\n"
            "Download and install it now? (~45 MB)",
        )
        if result:
            if url:
                _install_update(tag, url, root, save_config_fn)
            else:
                webbrowser.open(_RELEASES_PAGE)
    except Exception as e:
        if not silent_if_current:
            messagebox.showerror("Update Check Failed", f"Could not check scoreboard updates:\n{e}")
        else:
            print(f"[Scoreboard] Update check failed: {e}")


def _install_update(tag, url, root, save_config_fn):
    """Download and atomically replace the scoreboard exe in a background thread."""
    from tkinter import messagebox

    dest = next(
        (f for f in ("universal_scoreboard.exe", "scoreboard.exe") if os.path.isfile(f)),
        "universal_scoreboard.exe",
    )

    def _close_running(timeout=4.0):
        try:
            if not is_running():
                return True
            send_command("quit")
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not is_running():
                    return True
                time.sleep(0.1)
            return not is_running()
        except Exception:
            return False

    def _do_install():
        global version_seen, _update_available
        try:
            if not _close_running():
                root.after(0, lambda: messagebox.showerror(
                    "Update Failed",
                    "Could not close the running scoreboard automatically.\n\n"
                    "Please close the scoreboard and try updating again.",
                ))
                return

            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(dest + ".tmp", "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            os.replace(dest + ".tmp", dest)

            version_seen      = tag
            _update_available = False
            save_config_fn()

            root.after(0, lambda: messagebox.showinfo(
                "Scoreboard Updated",
                f"Universal Scoreboard updated to version {tag}.",
            ))
        except Exception as e:
            try:
                os.remove(dest + ".tmp")
            except OSError:
                pass
            root.after(0, lambda: messagebox.showerror(
                "Update Failed",
                f"Could not install update:\n{e}\n\n"
                f"Download manually:\n{_RELEASES_PAGE}",
            ))

    threading.Thread(target=_do_install, daemon=True).start()


def check_for_update_on_startup(root, save_config_fn):
    """Run a silent update check in the background at startup."""
    def _bg():
        try:
            check_for_update(root, save_config_fn, silent_if_current=True)
        except Exception as e:
            print(f"[Scoreboard] Startup update check failed: {e}")
    threading.Thread(target=_bg, daemon=True).start()
