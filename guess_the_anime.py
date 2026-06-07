# =========================================
#      GUESS THE ANIME - PLAYLIST TOOL
#             by Ramun Flame
# =========================================

from core.app_meta import WINDOW_TITLE

import os
import sys
import copy
import tkinter as tk
import tkinterdnd2 as tkdnd
import threading
from tkinter import messagebox, simpledialog, ttk, StringVar
from pynput import keyboard, mouse
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pygame.pkgdata")
import pyautogui
import subprocess
import _app_scripts.file.app_close as app_close
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.queue_round.youtube.youtube_control as youtube_control
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
from _app_scripts.file.metadata.file_metadata_dict import FileMetadataDict
import _app_scripts.file.auto_update as auto_update
import _app_scripts.file.tutorial as tutorial
import _app_scripts.playback.transport as transport
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.image_loader as image_loader
import _app_scripts.toggles.audio_toggles as audio_toggles
import _app_scripts.file.session_stats as session_stats
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.playlists.marks as playlist_marks
import _app_scripts.search.search as search_ops
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.file.web_server.web_host_actions as web_host_actions
import _app_scripts.queue_round.lightning_rounds.ost_overlay as ost_overlay
import _app_scripts.queue_round.lightning_rounds.characters_overlay as characters_overlay
import _app_scripts.queue_round.lightning_rounds.lightning_settings as lightning_settings
import _app_scripts.file.modal_guard as modal_guard
import _app_scripts.playback.mpv_bootstrap as mpv_bootstrap
import _app_scripts.playback.ffmpeg_check as ffmpeg_check

os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))

from core import app_icon

modal_guard.install_modal_dialog_guard(messagebox, simpledialog)
mpv = mpv_bootstrap.load_mpv_module()

# =========================================
#      *MEDIA PLAYER WRAPPER
# =========================================

import _app_scripts.playback.mpv_events as mpv_events
import _app_scripts.playback.mpv_player_setup as mpv_player_setup

player = mpv_player_setup.create_player(mpv)

# Populate ffmpeg_check's cached availability flag for ffmpeg_check.is_ffmpeg_available().
ffmpeg_check.check_ffmpeg_availability()

import _app_scripts.ui.drag_and_drop as drag_and_drop

# =========================================
#       *GLOBAL VARIABLES/CONSTANTS
# =========================================

from core.game_state import state

# Initialize the metadata cluster's non-empty members; all other
# state.metadata.* dicts keep the empty defaults from core.game_state.
# Consumers read state.metadata.* directly and mutate in place — see the
# identity-contract note in core/game_state.py.
state.metadata.playlist         = copy.deepcopy(playlist_ops.BLANK_PLAYLIST)
state.metadata.file_metadata    = FileMetadataDict(on_change=lambda: metadata_fetch.invalidate_file_metadata_cache())

from core.paths import (
    THEMES_CACHE_FOLDER,
)

state.display.screen_width, state.display.screen_height = pyautogui.size()
from _app_scripts.ui import scaling
scl = scaling.scl

import _app_scripts.data.config_io as config_io
import _app_scripts.data.metadata_io as metadata_io
import _app_scripts.data.updates_io as updates_io


# Lightning-round scalar state and the lightning/bonus settings dicts are
# initialized in core.game_state; consumers read state.lightning.* /
# state.playback.* directly.

import _app_scripts.playback.music as music
state.playback.music_files = music.music_files  # identity-contract alias

# bonus.answers imports ui.lists, which sizes fonts via scl() at import — keep after the scaling setup above.
import _app_scripts.bonus.answers as bonus_answers

state.config.scoreboard_rules = scoreboard_control.load_rules()

# =========================================
#         *VIDEO PLAYBACK/CONTROLS
# =========================================

state.playback.cached_images = image_loader.cached_images

import _app_scripts.toggles.censors as censors
censors.load_censors()

state.playback.check_theme_cache = playlist_marks.check_theme_cache

import _app_scripts.playback.dock_player as dock_player_mod

# =========================================
#                  *LISTS
# =========================================

# The list-header Tk widget refs are created in main_window.build_columns and
# published on state.widgets; the list-display state itself lives in state.lists.

# Sizes fonts via scl() at import — must come after the screen size is set above.
import _app_scripts.ui.lists as lists
import _app_scripts.ui.main_window as main_window

popout_buttons_by_name = {}
state.playback.popout_buttons_by_name = popout_buttons_by_name

# =========================================
#                 *GUI SETUP
# =========================================

config_io._migrate_old_file_structure()
config_io._migrate_playlist_names()
config_io.load_config()

# Initialize themes cache
os.makedirs(THEMES_CACHE_FOLDER, exist_ok=True)
os.makedirs(youtube_control.YOUTUBE_BONUS_TEMPLATES_FOLDER, exist_ok=True)
os.makedirs(youtube_control.YOUTUBE_CENSORS_FOLDER, exist_ok=True)
scoreboard_control.ensure_example_rules_file()
if not os.path.isabs(state.config.directory) and not os.path.exists(state.config.directory):
    os.makedirs(state.config.directory, exist_ok=True)

BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR

try:
    root = tkdnd.Tk()
except ImportError:
    root = tk.Tk()
except Exception:
    root = tk.Tk()

ROOT_MIN_HEIGHT = 540
root.title(WINDOW_TITLE)
root.geometry(f"{scl(1200, "UI")}x{scl(ROOT_MIN_HEIGHT, "UI")}")
root.minsize(scl(900, "UI"), scl(ROOT_MIN_HEIGHT, "UI"))  # Set minimum window size to prevent controls squishing
root.configure(bg=BACKGROUND_COLOR)  # Set background color to black
cache_download.load_cache_metadata()

app_icon.set_app_icon(root)
# root.resizable(False, False)

def setup_main_window_drag_drop():
    try:
        drag_and_drop.enable_drag_and_drop(root, drag_and_drop.handle_dropped_files)
    except Exception as e:
        print(f"Could not enable drag-and-drop on main window: {e}")

root.after(500, setup_main_window_drag_drop)

# First row
first_row_frame = tk.Frame(root, bg=BACKGROUND_COLOR)
first_row_frame.pack(pady=(0, 0), fill="x", anchor="w")
first_row_border = tk.Frame(root, bg="gray30", height=1)
first_row_border.pack(fill="x")

import _app_scripts.directory.scan as directory_scan
# Sizes fonts via scl() at import — must come after the screen size is set above.
import _app_scripts.ui.menu_builder as menu_builder

# Lightning Round mode options + display-string→key mapping.
state.lightning_ui.light_mode_options = [
    (key, f"{mode['icon']} {key.upper()}")
    for key, mode in lightning_settings.light_modes.items()
    if key != "variety"
]
state.lightning_ui.title_to_key = {display: key for key, display in state.lightning_ui.light_mode_options}
state.lightning_ui.selected_mode = StringVar(value=state.lightning_ui.light_mode_options[0][1])  # default to first display string

style = ttk.Style()
style.theme_use('clam')
from _app_scripts.ui import styling
configure_style = styling.configure_style  # dark Black.TCombobox style
configure_style()

# Three info columns + right-column list UI (header, scrollbar, bindings, tags).
main_window.build_columns(root)

# Long-lived widgets owned directly by main (root window, mpv player, first row).
state.widgets.root = root
state.widgets.player = player
state.widgets.first_row_frame = first_row_frame

# Video controls row (volume box, transport buttons, seek bar).
main_window.build_controls_row(root)

from _app_scripts.toggles import shortcut_dispatch

# =========================================
#                *STARTUP
# =========================================

keyboard_listener = keyboard.Listener(
    on_press=shortcut_dispatch.on_press,
    on_release=shortcut_dispatch.on_release)
keyboard_listener.start()

mouse_listener = mouse.Listener(
    on_click=shortcut_dispatch.on_mouse_click,
    on_move=shortcut_dispatch.on_mouse_move,
    on_scroll=shortcut_dispatch.on_mouse_scroll)
mouse_listener.start()

transport.update_playlist_name()
transport.update_current_index()
youtube_control.load_youtube_metadata()
metadata_io.load_metadata()
updates_io.check_for_local_metadata_package()
root.after(3000, updates_io.check_for_metadata_updates)
root.after(3000, updates_io.check_for_censor_updates)

bonus_answers._start_web_server()
if state.config.LAUNCH_SCOREBOARD_ON_STARTUP and scoreboard_control.AVAILABLE and not scoreboard_control.is_running():
    if os.path.isfile("scoreboard.exe"):
        subprocess.Popen(["scoreboard.exe"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif os.path.isfile("universal_scoreboard.exe"):
        subprocess.Popen(["universal_scoreboard.exe"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif not getattr(sys, 'frozen', False):
        # Only use sys.executable as a Python interpreter when NOT running as a
        # compiled exe — if frozen, sys.executable is this app, not Python.
        if os.path.isfile("scoreboard.py"):
            subprocess.Popen([sys.executable, "scoreboard.py"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        elif os.path.isfile("universal_scoreboard.py"):
            subprocess.Popen([sys.executable, "universal_scoreboard.py"], creationflags=subprocess.CREATE_NEW_CONSOLE)
web_host_actions.wire_web_server()
directory_scan.scan_directory(True)
menu_builder.create_first_row_buttons()
menu_builder.rebuild_shortcut_dispatch()
threading.Thread(target=characters_overlay.load_default_char_images, daemon=True).start()

auto_update.cleanup_updater_files()

root.bind("<Configure>", lists.on_window_resize)


root.after(1000, session_stats.create_new_session)
root.after(1000, transport.update_seek_bar)
root.after(1000, audio_toggles.set_volume, state.controls.volume_level)
root.after(1000, auto_update.cleanup_old_update_exes)
root.after(3000, auto_update.check_for_updates_on_startup)
root.after(1000, playlist_ops.update_living_playlists)
root.after(500, cache_download.check_download_ui_updates)

root.protocol("WM_DELETE_WINDOW", app_close.on_app_close)
root.after(50, mpv_events._poll_mpv_clicks)

# Auto-open tutorial on first launch (tutorial_shown stays False until user closes it once)
if not state.controls.tutorial_shown:
    root.after(500, tutorial.open_tutorial_popup)

if state.controls.pending_restore_collapsed:
    root.after(100, dock_player_mod.toggle_player_collapse)

root.mainloop()
