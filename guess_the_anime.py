# =========================================
#      GUESS THE ANIME - PLAYLIST TOOL
#             by Ramun Flame
# =========================================

APP_VERSION = "19.6"  # Update this when making releases
GITHUB_REPO = "ualkotob/guess-the-anime-playlist-tool"

import os
import sys
import random
import math
import json
import requests
import re
import copy
from datetime import datetime
import tkinter as tk
import tkinterdnd2 as tkdnd
import ctypes
from ctypes import wintypes
import threading
import queue
from tkinter import filedialog, messagebox, simpledialog, ttk, StringVar, font, Menu
import webbrowser
from PIL import ImageFont, ImageColor
from tinytag import TinyTag
from pynput import keyboard, mouse
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pygame.pkgdata")
import pygame
import pyperclip
import pyautogui
import subprocess
from tkinter.font import Font
import unicodedata
import _app_scripts.file.web_server.web_server as web_server
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.queue_round.youtube.youtube_control as youtube_control
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
from _app_scripts.file.metadata.file_metadata_dict import FileMetadataDict
import _app_scripts.utils as utils
import _app_scripts.file.auto_update as auto_update
import _app_scripts.file.tutorial as tutorial
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.image_loader as image_loader
import _app_scripts.playback.osd_text as osd_text
import _app_scripts.playback.progress_bar as progress_bar_ops
import _app_scripts.playback.progress_overlay as progress_overlay_ops
import _app_scripts.toggles.audio_toggles as audio_toggles
import _app_scripts.toggles.autoplay as autoplay_toggles
import _app_scripts.toggles.shortcut_actions as shortcut_actions
import _app_scripts.file.session_stats as session_stats
import _app_scripts.queue_round.fixed_lightning as fixed_lightning
import _app_scripts.queue_round.fixed_lightning_actions as fixed_lightning_actions
import _app_scripts.queue_round.youtube.youtube_ui as youtube_ui
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.playlists.marks as playlist_marks
import _app_scripts.directory.stats as stats_ops
import _app_scripts.search.search as search_ops
import _app_scripts.bonus.bonus_template_editor as bonus_template_editor
import _app_scripts.queue_round.youtube.youtube_editor as youtube_editor
import _app_scripts.toggles.shortcut_editor as shortcut_editor
import _app_scripts.file.generic_settings_editor as generic_settings_editor
import _app_scripts.file.settings_popup as settings_popup
import _app_scripts.file.settings_actions as settings_actions
import _app_scripts.ui.windowing as windowing
import _app_scripts.popout.popout_layout_editor as popout_layout_editor
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.file.metadata.metadata_panel as metadata_panel
import _app_scripts.file.metadata.metadata_import as metadata_import
import _app_scripts.queue_round.lightning_rounds.clues_overlay as clues_overlay
import _app_scripts.queue_round.lightning_rounds.emoji_overlay as emoji_overlay
import _app_scripts.queue_round.lightning_rounds.song_overlay as song_overlay
import _app_scripts.queue_round.lightning_rounds.synopsis_overlay as synopsis_overlay
import _app_scripts.queue_round.lightning_rounds.title_overlay as title_overlay
import _app_scripts.queue_round.lightning_rounds.scramble_overlay as scramble_overlay
import _app_scripts.queue_round.lightning_rounds.swap_overlay as swap_overlay
import _app_scripts.queue_round.lightning_rounds.peek_overlay as peek_overlay
import _app_scripts.queue_round.lightning_rounds.edge_overlay as edge_overlay
import _app_scripts.queue_round.lightning_rounds.grow_overlay as grow_overlay
import _app_scripts.queue_round.lightning_rounds.filter_overlay as filter_overlay
import _app_scripts.queue_round.lightning_rounds.peek_dispatch as peek_dispatch
import _app_scripts.file.web_server.web_host_actions as web_host_actions
import _app_scripts.queue_round.lightning_rounds.profile_overlay as profile_overlay
import _app_scripts.queue_round.lightning_rounds.tag_cloud_overlay as tag_cloud_overlay
import _app_scripts.queue_round.lightning_rounds.episode_overlay as episode_overlay
import _app_scripts.queue_round.lightning_rounds.ost_overlay as ost_overlay
import _app_scripts.queue_round.lightning_rounds.characters_overlay as characters_overlay
import _app_scripts.queue_round.lightning_rounds.cover_image_overlay as cover_image_overlay
import _app_scripts.queue_round.lightning_rounds.character_parts_overlay as character_parts_overlay
import _app_scripts.queue_round.lightning_rounds.image_reveal_overlays as image_reveal_overlays
import _app_scripts.queue_round.lightning_rounds.lightning_settings as lightning_settings
import _app_scripts.queue_round.lightning_rounds.lightning_manager as lightning_manager
import _app_scripts.queue_round.lightning_rounds.variety_round as variety_round
import _app_scripts.queue_round.lightning_rounds.frame_round as frame_round
import _app_scripts.queue_round.lightning_rounds.mismatch_round as mismatch_round
import _app_scripts.queue_round.lightning_rounds.trivia_round as trivia_round
import _app_scripts.file.modal_guard as modal_guard
import _app_scripts.file.tooltip as tooltip
import _app_scripts.playback.mpv_bootstrap as mpv_bootstrap
import _app_scripts.playback.ffmpeg_check as ffmpeg_check

os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))

# App icon (32x32 PNG, base64-encoded from guess_the_anime.ico)
_APP_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAIa0lEQVR42q1Xa3CU1Rl+zjnf7n67m91k"
    "NxdYQyDhpgFBmYQgYAhNFS1VBohB8QJ0YKpVpKVoodo2UxQVtVZmOt5ai0ORFkZrrWNlxEu9lijV"
    "VAiNFUokIIFwSYCQsN855+mPb0kR5TqemTPfzJ5z3ud9n/d9n3NW4PRDKcAYAEj2GgWTnnyhNuP7"
    "Wd0/ASQBYD+wb4dytn0i5TsIBV5EW9t7CoABMp9zH0oCQH7+pQOy4n+70w177zoO26UkHUUKQQKk"
    "Umx3HP7DcXi36+rzY/HXkJs7Xvo25LmCOxIAEok7bgtHuEdKH0wKTcAQsBqgBkjAZn7TBLhPSP4o"
    "HCZykj8XmUDOOnIFANmJBUtDLo8Z96SkAaj79KFevJh63Tqa99+nXrmS3pQp9AB6vkOagH4iFCKy"
    "E/fLs3TCpz03d/y8cJgEvDRgTYYB74oraNraeOKwJPXq1bSuSysl00JYAul7XJdI5E07YycIyLKy"
    "ssBFWbGNXX6OtZWSFIK6qIimo6MH1LS10WzZQkuS6TRJ0lu2jARolaLOpKo6mvUFcs+PERDw52mo"
    "z8ub+GQwRALaA0jHIQHqpUt9ZM+jfv116lSKJhCgd+uttNaSWtN0dtLk5/tsCUkCek0wSCTypmdY"
    "cE6KXpVZzI3Hf7dTSkvAMwApJS1Ab8MGGpKapFdR4RelELQATUODzwpJr7y8hwUC3n4hbHEs/jwA"
    "1J4iDYKAQF2dnBDJ2kS/mEzm60c0YgS7q6uZrqykdRxSSlIpGoBm0ybSWlpjqEtLMx0je2xMjUS3"
    "oawskEH/2jQIBQADB8bnuOE99FvMHu/AV6ZSPjN1dX4dkNRNTTSBgK8RQlAD1gK8JRRuQ//+2Sc6"
    "8JV8xLuDToAnEQ8pAfF/52kMzAMPQC1cCEGCQoALFkB53vH6CeGrkU0ggf1fsnCCeQICa6BuCLut"
    "p2TAzy29+fMz7WBoDh+mV1NzPPUkQJOxMTnq7kItguok6ijqUCcVBFLx/k+PyyowHmDs14FnjOtU"
    "iubgQfLoUZoDB6jHjPHXMx1DgMfOHwHM2GihLY4NekEIoA518vg0CF98BBDF45Xhck53r7QfKtBC0"
    "Jwkej15ck/evcce89dCoS/t1fBtvK3AGaFJ5tvhUUQcyzN6oAAIVQU4LRDGhp0H/zj60R822xZvff"
    "t2dZ7yMNp0w5zIlxCZ/jAgAG74J8SqVZA7d2bKjT1bbQZldSiB56wnSouLvHuH3lE2tHVdrvDMy+"
    "NQ5UAJCQATf1F+O3lzR3rXtPdsSa/B7BeNsUNmWuwkXaCjUWpfrr8yj53bLxWLIlkcnBrCvdfWk3"
    "Pa0/dX3EkAkzPYSI7rN6bFzNhivRs2Gs5q5idXv0CZk8PZrksCTB+Xz54CvPFG6q4u6s5OetOmfW"
    "nNZs4Q4CzXpZNIsnHSS+TMbfSu/8Rw5lb7rX5jWwAkVCpR+NiKkfeOOy+cIqmltd1IxQeiNJSPu1"
    "rXoUAEcInRsBAgAKkUaC3s3LlwRo2CDARgYzGIZ5+FUArWWlgIBAA8HXSxOGCxpmwJqgqrodMdEEIK"
    "KYMcktUv+69t7+aoiwuG/mXh+bMhHddY0yWVcGD0EQzLLwN0N36yrx5JFcJorSEzd4kBwO3bYaur"
    "YdNp2MWLgaZPASEgKSBBPO66uFl5WDR4Dm6/4Bbo9H440oGlgXTCJhVKyBd3v1kuEMTEsb1GPvrI"
    "iLsGVeSNMki3C0MjKSQcFcGU92/G2pYG3CQVatK7MEEf1z/BEBAMAocP9RRevQKWhwrwByqM6T0Qr"
    "1b+HsZ6EDRQEEQoaRv2faTmf3xf8zut9fOF8K/gnHAs+tDdpT+Y89MLvg8pg8ZLtyulIjigD+KyN2"
    "aidO8giKCHbrEB5WYvSmlQ4gGKQEsQ+AwCHzjZ6OJFcL1cNORswrrq5UiFCuCZTgSD2QbWqF99thz"
    "3NP5mZcfBjvkC2OtrgJDG0gJAzYSSqmUPX7SwcFjuCKO79kgnEBcftn+MqW/OxZKDNyEtg2hQLTg"
    "sD+HDQCONNKLi6FC4zMJQXYh862BRdDlWjH8Q4/Mq4XkHGHALbFN7o7rjX0t3v7z1tR8DWCWFhKV"
    "VCgAJilrUqk/R1LilvXnV6l2v9HGlGj4mv0LAalMY6StzImHctesp1Ohy9LfZGG0G4HPRJuKI4Lbu"
    "y1BoosijizuDy7GgYjau7TMVsF1GOVH5xNYVcmb9wj837No4VUG+dw2uUY1oBADbczdvxmYSVErIQ"
    "0e6jzy/tuWtbQ2d/64szx2elXSTZkT2xeK/bBZ/2vM6qjAcR5DGR4GtSAuNUq8vlHDwsHoBIy8cg"
    "SWliwgB09zZ4szZcPeBhz5+cl5nd+ciJeRBA+tsxuZTPtVFLWqV8vWvXyrZ+8WnKu8jZ20jv7dDX1"
    "IyklPFeL6NX3OSW8XLo6P5dzzCGeJKjiwuI2dt15z1OZ+peohFuUWvABigII/p/1k90Z1jSgWJW2o"
    "Hf7e9+dr17LqxyUsVFNklmM3r3Am8OlLFZZjL3nl9bMf1G70d123g9MGTDkFiHoBjSuuc638D6d+S"
    "EgAGFyZ7r33u8t9y/VVrGI8lWZxVzL6xvsyL9WL9VWv40hXPsDiv6A0AQ8416tOzEcDscf3H7uwT"
    "LzJTRCWniEtZEi823xl0WSsc3PpNRH3SF3NdXZ3MSiZLnXBk8xRZaYe5g44OjJQcrRHjrApH/hMo"
    "SAwjKc4GXJzpPgIQKYTzD/XaO+HI8HDQKv1p4AuphcWQ9Hk0gurV6EZvd7Q1IXajM3Pn87RRnamn"
    "vwQkDsMT4WC3hpkQs65MmRyRb+KiU6ZlU6gVrU77z9L7u9/CGYKfy/AZSwZr8rN61w+MlHQNihR3"
    "58d6fYBEYNpZsgoA+B96i9z9MuacjQAAAABJRU5ErkJggg=="
)

modal_guard.install_modal_dialog_guard(messagebox, simpledialog)
mpv = mpv_bootstrap.load_mpv_module()


# =========================================
#      *MEDIA PLAYER WRAPPER
# =========================================

from _app_scripts.playback.media_player import MediaPlayer


player = None

def _mpv_opts(**extra):
    """Return common mpv.MPV constructor keyword arguments."""
    return dict(
        keep_open='yes',
        idle='yes',
        input_default_bindings=False,
        input_vo_keyboard=False,
        osc=False,
        force_media_title='Guess the Anime! - Playlist Tool',
        auto_window_resize='no',
        **extra
    )

# Create the main mpv player instance
try:
    player = MediaPlayer(mpv.MPV(**_mpv_opts(force_window='no')))
    # When mpv goes idle without Python having called stop() (e.g. user closes the
    # window via CLOSE_WIN → mpv stop), schedule our Python stop() on the main thread.
    # Debounced: ignore transient idle-active=True flips that occur during seeks.
    _idle_stop_after_id = None
    def _on_player_idle(name, is_idle):
        global _idle_stop_after_id
        if is_idle and globals().get('currently_playing'):
            # Snapshot currently_playing now (on mpv thread) so the 400ms callback
            # isn't fooled by later state changes.
            _cp_snapshot = globals().get('currently_playing')
            def _do_idle_stop(snapshot=_cp_snapshot):
                global _idle_stop_after_id
                _idle_stop_after_id = None
                # Only call stop() if currently_playing hasn't changed since we fired
                # (i.e. stop() wasn't already called by something else).
                if globals().get('currently_playing') is snapshot and snapshot:
                    try:
                        globals()['stop']()
                    except Exception:
                        pass
            try:
                root = globals().get('root')
                if root:
                    _idle_stop_after_id = root.after(200, _do_idle_stop)
            except Exception:
                pass
        elif not is_idle:
            # idle-active went False (seek completed / playback resumed) — cancel pending stop
            try:
                root = globals().get('root')
                if root and _idle_stop_after_id is not None:
                    root.after_cancel(_idle_stop_after_id)
                    _idle_stop_after_id = None
            except Exception:
                pass
    player._p.observe_property('idle-active', _on_player_idle)

    def _on_fullscreen_change(name, is_fs):
        # Sync autoplay_fullscreen when the user toggles fullscreen in mpv while a video
        # is actively playing (double-click, TAB, etc.). Do NOT sync during startup or
        # shutdown — mpv exits fullscreen on close which would poison the saved preference.
        # Use time_pos instead of is_playing() so a momentary pause (e.g. from the click
        # handler firing on the first half of a double-click) doesn't block the sync.
        try:
            root = globals().get('root')
            p = globals().get('player')
            if root and p and p._p.time_pos is not None:
                def _sync_mpv_fullscreen():
                    state.controls.autoplay_fullscreen = bool(is_fs)
                    _sync_control_globals()
                root.after(0, _sync_mpv_fullscreen)
        except Exception:
            pass
    player._p.observe_property('fullscreen', _on_fullscreen_change)

    def _on_osd_width_change(name, new_w):
        """Re-render the coming-up PIL image overlay when the OSD is resized."""
        try:
            if not coming_up_ui._coming_up_osd_visible:
                return
            frame = coming_up_ui._coming_up_current_frame
            if not frame:
                return
            title_text, details, pil_image = frame
            osd_w, osd_h = int(player._p.osd_width or 0), int(player._p.osd_height or 0)
            if not osd_w or not osd_h:
                return
            target_y = max(4, round(osd_h * 0.014))
            _root = globals().get('root')
            if _root:
                _root.after(0, lambda: coming_up_ui._render_coming_up_frame(
                    title_text, details, pil_image, target_y, osd_w, osd_h, 1.0))
        except Exception:
            pass
    player._p.observe_property('osd-width', _on_osd_width_change)

    @player._p.event_callback('playback-restart')
    def _on_playback_restart(_):
        """Fired once per file load when the first frame is ready and OSD dims are valid.
        Reapplies blind/reveal overlays that may have been lost during the mpv OSD reset."""
        try:
            _root = globals().get('root')
            if not _root:
                return
            def _reapply():
                _bo = blind_screen.black_overlay
                _cache = blind_screen._blind_osd_color_cache or 'black'
                # Reapply blind OSD (covers blind rounds AND the pre-load cover for reveal rounds)
                if _bo:
                    _set_blind_osd_alpha(_cache, 255)
                # For non-lightning reveal rounds: reapply active peek overlay then lift blind
                if not globals().get('light_mode') and not globals().get('light_round_started'):
                    _fvf = filter_overlay.filter_vf_active
                    _fvf_var = filter_overlay._filter_vf_variant
                    _eo = edge_overlay.edge_overlay_box
                    _po = peek_overlay.peek_overlay1
                    _go = grow_overlay.grow_overlay_boxes
                    # Reapply ASS-based overlays (osd dims are now valid)
                    if _fvf and _fvf_var:
                        toggle_filter_vf(_fvf_var, filter_overlay._filter_vf_last_progress[0])
                    if _eo:
                        toggle_edge_overlay(block_percent=99)
                    if _po:
                        toggle_peek_overlay()
                    # If any peek overlay is active and we put up a pre-load black screen, lift it
                    if _bo and (_fvf or _eo or _po or _go):
                        _root.after(50, lambda: set_black_screen(False))
            _root.after(0, _reapply)
        except Exception:
            pass

    def _on_eof_reached(name, value):
        """Observed property: fires when eof-reached changes.
        Only True on natural playback end (keep_open=yes pauses at last frame).
        Does NOT fire for stop(), player.stop(), or window close."""
        try:
            if not value:
                return
            _root = globals().get('root')
            if _root:
                _root.after(0, _handle_video_end)
        except Exception:
            pass
    player._p.observe_property('eof-reached', _on_eof_reached)

    # Click inside the mpv window → play/pause (Windows API window subclassing).
    # player._p.window_id gives the HWND once mpv creates its window.
    # We subclass the window proc to intercept WM_LBUTTONDOWN/WM_LBUTTONUP.
    # Time-based detection: clicks < 300 ms; drags take longer.
    _mpv_wndproc_refs = {}  # hwnd → (new_proc, original_proc); keeps ctypes objects alive
    _mpv_click_queue   = queue.Queue()  # thread-safe click signals from mpv wndproc → main thread
    _playpause_pending = [None]          # root.after ID for deferred play_pause (double-click guard)

    def _setup_mpv_click_handler(hwnd):
        import ctypes, ctypes.wintypes, time as _time
        if not hwnd or hwnd in _mpv_wndproc_refs:
            return
        GWL_WNDPROC = -4
        WM_LBUTTONDOWN   = 0x0201
        WM_LBUTTONUP     = 0x0202
        WM_LBUTTONDBLCLK = 0x0203
        _press_time       = [None]
        _last_down_time   = [0.0]
        _is_double_press  = [False]
        # System double-click interval (ms → s); used to detect the second press
        # when the window class does NOT have CS_DBLCLKS (no WM_LBUTTONDBLCLK).
        _DBLCLK_S = ctypes.windll.user32.GetDoubleClickTime() / 1000.0
        # Must set restype to c_ssize_t; default c_int truncates 64-bit pointers.
        _GetWindowLongPtrW = ctypes.windll.user32.GetWindowLongPtrW
        _GetWindowLongPtrW.restype = ctypes.c_ssize_t
        _SetWindowLongPtrW = ctypes.windll.user32.SetWindowLongPtrW
        _SetWindowLongPtrW.restype = ctypes.c_ssize_t
        _CallWindowProcW = ctypes.windll.user32.CallWindowProcW
        _CallWindowProcW.restype = ctypes.c_ssize_t
        _CallWindowProcW.argtypes = [
            ctypes.c_ssize_t, ctypes.wintypes.HWND, ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        ]
        original = _GetWindowLongPtrW(hwnd, GWL_WNDPROC)
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.wintypes.HWND, ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        )
        def _wndproc(h, msg, wp, lp):
            if msg == WM_LBUTTONDOWN:
                now = _time.monotonic()
                _is_double_press[0] = (now - _last_down_time[0]) < _DBLCLK_S
                _last_down_time[0] = now
                _press_time[0] = now
            elif msg == WM_LBUTTONUP:
                pt = _press_time[0]
                _press_time[0] = None
                if pt is not None and _time.monotonic() - pt < 0.3:
                    if _is_double_press[0]:
                        # Second UP of double-click (no-CS_DBLCLKS case) — cancel first.
                        _mpv_click_queue.put_nowait(None)
                    else:
                        # Normal single click — queue it for deferred processing.
                        # Do NOT call root.after() here: this callback runs on mpv's
                        # window thread and touching the Tcl/Tk lock deadlocks when
                        # the main thread holds it.
                        _mpv_click_queue.put_nowait(True)
            elif msg == WM_LBUTTONDBLCLK:
                # CS_DBLCLKS IS set: replaces the second WM_LBUTTONDOWN.
                # Cancel the first click and reset state so the following LBUTTONUP
                # and the next single-click are not misidentified as doubles.
                _mpv_click_queue.put_nowait(None)
                _press_time[0] = None    # suppress the upcoming LBUTTONUP
                _last_down_time[0] = 0.0  # prevent next click being flagged as double
            return _CallWindowProcW(original, h, msg, wp, lp)
        new_proc = WNDPROC(_wndproc)
        _SetWindowLongPtrW(hwnd, GWL_WNDPROC, new_proc)
        _mpv_wndproc_refs[hwnd] = (new_proc, original)

    def _on_mpv_window_id(name, value):
        try:
            hwnd = int(value or 0)
            if hwnd:
                # Call directly — SetWindowLongPtrW is thread-safe and
                # _setup_mpv_click_handler no longer touches Tcl/Tk.
                # Also works before root exists (at startup).
                _setup_mpv_click_handler(hwnd)
        except Exception:
            pass

    player._p.observe_property('window-id', _on_mpv_window_id)

except Exception as _e:
    try:
        messagebox.showerror("mpv error", f"Failed to create mpv player:\n{_e}")
    except Exception:
        print(f"FATAL: Failed to create mpv player: {_e}")
    sys.exit(1)

def _poll_mpv_clicks():
    """Main-thread poller that drains _mpv_click_queue and calls play_pause().

    The mpv wndproc callback runs on mpv's window thread and cannot safely call
    root.after() (which acquires the Tcl/Tk interpreter lock).  Instead it puts
    a sentinel on _mpv_click_queue; this function polls that queue every 50 ms
    from the main thread where Tk calls are safe.
    """
    try:
        while not _mpv_click_queue.empty():
            item = _mpv_click_queue.get_nowait()
            if item is True:
                # Defer play_pause by 200 ms.  This gives the cancel sentinel from
                # the second click of a double-click time to arrive and abort the
                # timer before it fires, without any perceptible lag on single clicks.
                if _playpause_pending[0] is None:
                    def _fire(_pending=_playpause_pending):
                        _pending[0] = None
                        if not (grow_overlay.grow_overlay_boxes or (
                                filter_overlay.filter_vf_active and
                                filter_overlay._filter_vf_variant == 'zoom')):
                            play_pause()
                    _playpause_pending[0] = root.after(200, _fire)
            elif item is None:
                # Cancel any pending deferred play_pause.
                if _playpause_pending[0] is not None:
                    root.after_cancel(_playpause_pending[0])
                    _playpause_pending[0] = None
    except Exception:
        pass
    root.after(50, _poll_mpv_clicks)

check_ffmpeg_availability = ffmpeg_check.check_ffmpeg_availability
is_ffmpeg_available = ffmpeg_check.is_ffmpeg_available
ffmpeg_available = check_ffmpeg_availability()

# =========================================
#          DRAG AND DROP SUPPORT
# =========================================

def enable_drag_and_drop(widget, callback):
    """Enable drag-and-drop for files from Windows Explorer."""
    
    # Method 1: Try tkinterdnd2 (best option)
    try:
        
        root = widget.winfo_toplevel()
        if hasattr(root, 'drop_target_register') or isinstance(root, tkdnd.Tk):
            widget.drop_target_register(tkdnd.DND_FILES)
            
            def handle_drop(event):
                global external_drag_active
                external_drag_active = False  # Clear external drag state
                
                files = widget.tk.splitlist(event.data)
                if files and callback:
                    callback(files, event=event)
                return "copy"
            
            widget.dnd_bind('<<Drop>>', handle_drop)
            return True
        else:
            raise Exception("Root window not tkinterdnd2-enabled")
            
    except Exception as e:
        print(f"tkinterdnd2 failed: {e}")
    
    # Method 2: Windows API (more reliable than before)
    if sys.platform.startswith('win'):
        try:
            # Get window handle
            hwnd = widget.winfo_id()
            
            # Enable file dropping
            ctypes.windll.shell32.DragAcceptFiles(hwnd, True)
            
            # Store the original window procedure
            GWL_WNDPROC = -4
            original_wndproc = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
            
            def window_proc(hwnd, msg, wparam, lparam):
                WM_DROPFILES = 0x0233
                if msg == WM_DROPFILES:
                    try:
                        file_count = ctypes.windll.shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                        files = []
                        
                        for i in range(file_count):
                            length = ctypes.windll.shell32.DragQueryFileW(wparam, i, None, 0)
                            buffer = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.shell32.DragQueryFileW(wparam, i, buffer, length + 1)
                            files.append(buffer.value)
                        
                        ctypes.windll.shell32.DragFinish(wparam)
                        
                        if files and callback:
                            # Use after_idle to safely call callback from main thread
                            # Note: Windows API doesn't provide event coordinates easily
                            widget.after_idle(lambda f=files: callback(f, event=None))
                        return 0
                    except Exception as e:
                        print(f"Drop handling error: {e}")
                
                # Call original window procedure
                return ctypes.windll.user32.CallWindowProcW(original_wndproc, hwnd, msg, wparam, lparam)
            
            # Set up the window procedure with proper signature
            WNDPROC = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            new_wndproc = WNDPROC(window_proc)
            
            # Replace window procedure
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, new_wndproc)
            
            # Store reference to prevent garbage collection
            widget._drag_drop_wndproc = new_wndproc
            widget._original_wndproc = original_wndproc
            
            return True
            
        except Exception as e:
            print(f"Windows API drag-and-drop failed: {e}")
    
    # Method 3: Fallback to file dialogs
    try:
        def show_file_dialog(event=None):
            files = filedialog.askopenfilenames(
                title="Select media files to add to playlist",
                filetypes=[
                    ("Media files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.mp3 *.wav *.ogg *.m4a *.flac"),
                    ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm"),
                    ("Audio files", "*.mp3 *.wav *.ogg *.m4a *.flac"),
                    ("All files", "*.*")
                ]
            )
            if files and callback:
                callback(list(files), event=None)
        
        def show_context_menu(event):
            menu = Menu(widget, tearoff=0)
            menu.add_command(label="📁 Add Files to Playlist...", command=show_file_dialog)
            popup_menu(menu, event.x_root, event.y_root)
        
        widget.bind("<Button-3>", show_context_menu)
        widget.bind("<Double-Button-1>", show_file_dialog)
        
        print(f"📁 File selection enabled on {widget.__class__.__name__}: Right-click or double-click")
        return True
        
    except Exception as e:
        print(f"Could not set up file selection: {e}")
        return False

def handle_dropped_files(files, event=None):
    """Handle files dropped from Windows Explorer."""
    global hovered_button_index
    
    added_files = []
    
    # Try to detect drop position using coordinates (since hover events don't work during external drag)
    insert_position = None
    
    if event is not None and list_loaded == "playlist":
        try:
            if 'right_column' in globals():
                # Get the playlist widget position and bounds
                right_column.update_idletasks()
                widget_x = right_column.winfo_rootx()
                widget_y = right_column.winfo_rooty()
                widget_width = right_column.winfo_width()
                widget_height = right_column.winfo_height()
                
                if (widget_x <= event.x_root <= widget_x + widget_width and
                    widget_y <= event.y_root <= widget_y + widget_height):
                    
                    # Calculate relative position within the text widget
                    relative_x = event.x_root - widget_x
                    relative_y = event.y_root - widget_y
                    
                    # Use Text widget's index method to get the line at the drop position
                    try:
                        text_index = right_column.index(f"@{relative_x},{relative_y}")
                        drop_line = int(text_index.split('.')[0])
                        
                        if list_loaded == "playlist":
                            insert_position = max(0, drop_line - 1 + playlist_page_offset)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                        else:
                            content = right_column.get("1.0", "2.0")
                            if "items above" in content:
                                drop_line = max(1, drop_line - 1)
                            
                            # Convert to 0-based index and clamp to valid range
                            insert_position = max(0, drop_line - 1)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                    except (ValueError, tk.TclError):
                        button_height = scl(12) + 8
                        insert_position = max(0, int(relative_y / button_height))
                        playlist_size = len(playlist.get("playlist", []))
                        insert_position = min(insert_position, playlist_size)
        except Exception as e:
            print(f"DEBUG: Event position detection failed: {e}")
    
    if insert_position is None and list_loaded == "playlist":
        try:
            mouse_x, mouse_y = pyautogui.position()
            
            if 'right_column' in globals():
                right_column.update_idletasks()
                widget_x = right_column.winfo_rootx()
                widget_y = right_column.winfo_rooty()
                widget_width = right_column.winfo_width()
                widget_height = right_column.winfo_height()
                
                if (widget_x <= mouse_x <= widget_x + widget_width and
                    widget_y <= mouse_y <= widget_y + widget_height):
                    
                    # Calculate relative position within the text widget
                    relative_x = mouse_x - widget_x
                    relative_y = mouse_y - widget_y
                    
                    # Use Text widget's index method to get the line at the mouse position
                    try:
                        text_index = right_column.index(f"@{relative_x},{relative_y}")
                        drop_line = int(text_index.split('.')[0])
                        
                        if list_loaded == "playlist":
                            insert_position = max(0, drop_line - 1 + playlist_page_offset)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                        else:
                            content = right_column.get("1.0", "2.0")
                            if "items above" in content:
                                drop_line = max(1, drop_line - 1)
                            
                            # Convert to 0-based index and clamp to valid range
                            insert_position = max(0, drop_line - 1)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                    except (ValueError, tk.TclError):
                        button_height = scl(12) + 8
                        relative_position = max(0, int(relative_y / button_height))
                        if list_loaded == "playlist":
                            insert_position = relative_position + playlist_page_offset
                        else:
                            insert_position = relative_position
                        playlist_size = len(playlist.get("playlist", []))
                        insert_position = min(insert_position, playlist_size)
        except Exception as e:
            print(f"DEBUG: Mouse position detection failed: {e}")
    
    # Method 3: Default fallback
    if insert_position is None:
        current_index = playlist.get("current_index", -1)
        insert_position = current_index + 1 if current_index >= 0 else len(playlist["playlist"])
    
    # Clear any leftover hover state
    hovered_button_index = None
    
    for file_path in files:
        if os.path.isfile(file_path):
            # Get just the filename without path
            filename = os.path.basename(file_path)
            
            # Always add to playlist (allow duplicates)
            if filename in directory_files:
                # Local file - store just filename
                playlist_entry = filename
            else:
                # External file - store full path
                playlist_entry = file_path
            
            # Insert at the specified position
            playlist["playlist"].insert(insert_position, playlist_entry)
            added_files.append(filename)  # Still show just filename in messages
            
            current_index = playlist.get("current_index", -1)
            if current_index >= 0 and insert_position <= current_index:
                playlist["current_index"] = current_index + 1
            
            insert_position += 1  # Increment for next file
    
    # Show summary message
    if added_files:
        # Update the playlist display after adding files
        try:
            show_playlist(update=True)
        except NameError:
            # If show_playlist function doesn't exist, try other display functions
            try:
                show_list("playlist", None, None, None, None, None, update=True)
            except:
                print("Could not refresh playlist display")
    
    # Clear hover state after drop
    hovered_button_index = None
        
    if list_loaded == "playlist":
        show_playlist(True)
    if added_files:
        prefetch_next_themes()

# =========================================
#       *GLOBAL VARIABLES/CONSTANTS
# =========================================

BLANK_PLAYLIST = {
    "name":"",
    "current_index":-1,
    "lightning_history": {},
    "background_track_history": [],
    "infinite":False,
    "difficulty":2,
    "order": 0,
    "pop_time_order": [],
    "playlist":[]
}
playlist = copy.deepcopy(BLANK_PLAYLIST)
playlist_loaded = False

def _notify_playlist_list_updated():
    global current_list_content, current_list_selected
    if list_loaded == "playlist":
        current_list_content = convert_playlist_to_dict(playlist["playlist"])
        current_list_selected = playlist["current_index"]
        refresh_current_list()

video_stopped = True
can_seek = True

file_metadata = FileMetadataDict(on_change=lambda: invalidate_file_metadata_cache())
from core.paths import (
    ANILIST_METADATA_FILE,
)
from core.game_state import state

def _sync_control_globals():
    """Keep legacy scalar globals synced while controls migrate to state."""
    globals().update(
        autoplay_toggle=state.controls.autoplay_toggle,
        special_repeat_track_mode=state.controls.special_repeat_track_mode,
        autoplay_fullscreen=state.controls.autoplay_fullscreen,
        mpv_always_on_top=state.controls.mpv_always_on_top,
        volume_level=state.controls.volume_level,
        bgm_volume=state.controls.bgm_volume,
        stream_volume_boost=state.controls.stream_volume_boost,
        disable_video_audio=state.controls.disable_video_audio,
        light_muted=state.controls.light_muted,
    )

def _sync_control_state_from_globals():
    """Import legacy scalar globals into state.controls after config/schema loads."""
    state.controls.autoplay_toggle = globals().get("autoplay_toggle", state.controls.autoplay_toggle)
    state.controls.special_repeat_track_mode = globals().get(
        "special_repeat_track_mode",
        state.controls.special_repeat_track_mode,
    )
    state.controls.autoplay_fullscreen = globals().get(
        "autoplay_fullscreen",
        state.controls.autoplay_fullscreen,
    )
    state.controls.mpv_always_on_top = globals().get(
        "mpv_always_on_top",
        state.controls.mpv_always_on_top,
    )
    state.controls.volume_level = globals().get("volume_level", state.controls.volume_level)
    state.controls.bgm_volume = globals().get("bgm_volume", state.controls.bgm_volume)
    state.controls.stream_volume_boost = globals().get(
        "stream_volume_boost",
        state.controls.stream_volume_boost,
    )
    state.controls.disable_video_audio = globals().get(
        "disable_video_audio",
        state.controls.disable_video_audio,
    )
    state.controls.light_muted = globals().get("light_muted", state.controls.light_muted)
    _sync_control_globals()

file_metadata_overrides = {}
anime_metadata = {}
anidb_metadata = {}
ai_metadata = {}
anime_metadata_overrides = {}
youtube_metadata = youtube_control.youtube_metadata  # dict shared with youtube_control (updated in-place)
anilist_metadata = {}
directory = "themes"
directory_files = {}

# --- Wire metadata cluster into GameState ---
# These aliases point at the SAME dict instances `state.metadata.*` owns.
# All loaders below mutate these dicts in place (clear/update) instead of
# reassigning, so the aliases and `state.metadata.*` stay in sync forever.
# See core/game_state.py for the invariant.
state.metadata.playlist                  = playlist
state.metadata.directory_files           = directory_files
state.metadata.file_metadata             = file_metadata
state.metadata.file_metadata_overrides   = file_metadata_overrides
state.metadata.anime_metadata            = anime_metadata
state.metadata.anidb_metadata            = anidb_metadata
state.metadata.ai_metadata               = ai_metadata
state.metadata.anime_metadata_overrides  = anime_metadata_overrides
state.metadata.anilist_metadata          = anilist_metadata
state.metadata.youtube_metadata          = youtube_metadata

get_file_path = entry_paths.get_file_path
get_clean_filename = entry_paths.get_clean_filename

is_youtube_file = youtube_control.is_youtube_file

get_youtube_metadata_by_filename = youtube_control.get_youtube_metadata_by_filename

host = ""
volume_level = 100
stream_volume_boost = 0
_sync_control_state_from_globals()
title_top_info_txt = ""
end_session_txt = ""
inverted_colors = False
inverted_positions = False
scale_main_ui = False
auto_fetch_missing = False
special_round_warning = True
special_round_playlist = True
skip_play_seconds = 0
skip_jump_seconds = 5
selected_rules_file = ""
YOUTUBE_API_KEY = ""
OPENAI_API_KEY = ""
SERPAPI_KEY = ""
IGDB_CLIENT_ID = ""
IGDB_CLIENT_SECRET = ""
WEB_SERVER_ENABLED = False
NGROK_DOMAIN = ""
HOST_PASSWORD = ""
CLOUDFLARE_TUNNEL_TOKEN = ""
CLOUDFLARE_PUBLIC_URL = ""
NGROK_AVAILABLE = web_server.NGROK_AVAILABLE
CLOUDFLARED_AVAILABLE = web_server.CLOUDFLARED_AVAILABLE
LAUNCH_SCOREBOARD_ON_STARTUP = False
AUTO_EXIT_SCOREBOARD = False
from core.paths import (
    CENSORS_FOLDER,
    RULES_FOLDER,
    PLAYLISTS_FOLDER,
    FILTERS_FOLDER,
    CENSOR_JSON_FILE,
    THEMES_CACHE_FOLDER,
    CACHE_METADATA_FILE,
)
themes_cache_size = 500  # Size in MB
auto_download_themes = False  # overwritten by load_config() via SETTINGS_SCHEMA
bgm_volume = 1.0  # overwritten by load_config() via SETTINGS_SCHEMA
stream_volume_boost = 0  # overwritten by load_config() via SETTINGS_SCHEMA
HIGHLIGHT_COLOR = "gray26"
OVERLAY_BACKGROUND_COLOR = "black"
OVERLAY_TEXT_COLOR = "white"
INVERSE_OVERLAY_BACKGROUND_COLOR = "white"
INVERSE_OVERLAY_TEXT_COLOR = "black"
MIDDLE_OVERLAY_BACKGROUND_COLOR = "dark gray"
OVERLAY_COLOR_OPTIONS = ["black", "white"]

# =============================================
#            *SETTINGS SCHEMA
# Each entry defines one configurable setting.
# key        - Python global variable name
# config_key - JSON key in config.json
# label      - Row label in settings popup (None = grouped row, no own label)
# type       - int | float | bool | str | password | color | rules_file
#              group="skip_group" entries are rendered together in one row
# default    - Default when missing from config
# tooltip    - ToolTip text in settings popup
# width      - Entry widget width (optional, default 10)
# min/max    - Clamping for int/float (optional)
# after_save - "restart_warning" | "reset_serpapi" (optional post-save callback key)
# =============================================
SETTINGS_SCHEMA = [
    {"key": "volume_level",                    "config_key": "volume_level",                    "label": "Volume Level:",              "type": "int",      "default": 100,   "width": 10, "tooltip": "Master volume level for all audio playback (0-100)."},
    {"key": "stream_volume_boost",             "config_key": "stream_volume_boost",             "label": "Stream Volume Boost:",       "type": "int",      "default": 0,     "width": 10, "tooltip": "Additional volume boost specifically for stream audio from YouTube clips/trailers."},
    {"key": "bgm_volume","config_key": "bgm_volume","label": "BGM Volume:",     "type": "float",    "default": 1.0,   "width": 10, "min": 0.0, "max": 1.5, "tooltip": "Volume multiplier for background music (0.0 - 1.5). Scales the dB curve output."},
    {"key": "themes_cache_size",               "config_key": "themes_cache_size",               "label": "Themes Cache Size (MB):",    "type": "int",      "default": 500,   "width": 10, "min": 0,   "tooltip": "Maximum size of the themes cache folder in MB. Downloaded themes are cached for faster playback."},
    {"key": "auto_download_themes",             "config_key": "auto_download_themes",             "label": "Auto-Download Themes:",       "type": "bool",     "default": False,          "tooltip": "When enabled, downloaded themes are saved directly to your themes directory as permanent files instead of the temporary cache."},
    # Skip group — 4 entries rendered as one row in the popup
    {"key": "skip_play_seconds",     "config_key": "skip_play_seconds",  "label": "Skip Play Settings:", "type": "float", "default": 0,   "width": 6, "min": 0, "group": "skip_group", "tooltip": "Play Seconds: Duration to play before auto-skip (0 = disabled)"},
    {"key": "skip_jump_seconds",     "config_key": "skip_jump_seconds",  "label": None,                  "type": "float", "default": 5,   "width": 6, "min": 0, "group": "skip_group", "tooltip": "Jump Seconds: Distance to jump forward when skip triggers"},
    {"key": "SKIP_FADE_WINDOW_MS",   "config_key": "skip_fade_out_ms",   "label": None,                  "type": "int",   "default": 350, "width": 6, "min": 0, "group": "skip_group", "tooltip": "Fade Out (ms): Milliseconds to fade volume down before skip"},
    {"key": "SKIP_FADE_IN_WINDOW_MS","config_key": "skip_fade_in_ms",    "label": None,                  "type": "int",   "default": 300, "width": 6, "min": 0, "group": "skip_group", "tooltip": "Fade In (ms): Milliseconds to fade volume up after skip"},
    # Color — special rendering: dropdown + add/delete buttons
    {"key": "OVERLAY_BACKGROUND_COLOR", "config_key": "back_color",  "label": "Background Color:", "type": "color", "default": "black", "tooltip": "Background color of overlay windows."},
    {"key": "OVERLAY_TEXT_COLOR",        "config_key": "text_color",  "label": "Text Color:",       "type": "color", "default": "white", "tooltip": "Text color displayed in overlay windows."},
    # Booleans
    {"key": "inverted_positions",    "config_key": "inverted_positions",    "label": "Inverted Positions:",      "type": "bool", "default": False, "tooltip": "Swaps alignment of some elements to adjust for scoreboard position. Enable if scoreboard is aligned right."},
    {"key": "scale_main_ui",         "config_key": "scale_main_ui",         "label": "Scale Main UI:",            "type": "bool", "default": False, "tooltip": "Scales the main UI based on screen resolution. Requires restart.", "after_save": "restart_warning"},
    {"key": "auto_fetch_missing",    "config_key": "auto_fetch_missing",    "label": "Auto Fetch Missing:",       "type": "bool", "default": False, "tooltip": "Automatically fetches metadata if it's not found while playing themes."},
    {"key": "special_round_warning", "config_key": "special_round_warning", "label": "Special Round Warning:",   "type": "bool", "default": True,  "tooltip": "Shows a warning before special rounds begin."},
    {"key": "special_round_playlist","config_key": "special_round_playlist","label": "Special Round Playlist:",  "type": "bool", "default": True,  "tooltip": "Auto-queue special rounds based on system playlist marks."},
    # Rules file — special rendering: folder-scanned dropdown
    {"key": "selected_rules_file", "config_key": "selected_rules_file", "label": "Rules File:",              "type": "rules_file", "default": "", "tooltip": "Select which rules file to use for the scoreboard. Files must end with 'rules.json'."},
    # API keys — password type (masked entry)
    {"key": "YOUTUBE_API_KEY", "config_key": "youtube_api_key", "label": "YouTube API Key:", "type": "password", "default": "", "width": 30, "tooltip": "API key for YouTube integration features. Required for Clip and Ost lightning rounds."},
    {"key": "OPENAI_API_KEY",  "config_key": "openai_api_key",  "label": "OpenAI API Key:",  "type": "password", "default": "", "width": 30, "tooltip": "API key for OpenAI/ChatGPT integration features. Required for Trivia and Emoji lightning rounds."},
    {"key": "SERPAPI_KEY",     "config_key": "serpapi_key",     "label": "SerpAPI Key:",      "type": "password", "default": "", "width": 30, "tooltip": "SerpAPI key for Image lightning round (serpapi.com).", "after_save": "reset_serpapi"},
    {"key": "IGDB_CLIENT_ID",     "config_key": "igdb_client_id",     "label": "IGDB Client ID:",      "type": "password", "default": "", "width": 30, "tooltip": "Twitch/IGDB client ID for game metadata. Get it at dev.twitch.tv."},
    {"key": "IGDB_CLIENT_SECRET", "config_key": "igdb_client_secret", "label": "IGDB Client Secret:", "type": "password", "default": "", "width": 30, "tooltip": "Twitch/IGDB client secret for game metadata. Get it at dev.twitch.tv."},
    # Text fields
    {"key": "title_top_info_txt", "config_key": "title_top_info_txt", "label": "Title Only Info Text:", "type": "str", "default": "", "width": 30, "tooltip": "Custom text displayed above title when showing title-only information."},
    {"key": "end_session_txt",    "config_key": "end_session_txt",    "label": "End Session Text:",      "type": "str", "default": "", "width": 30, "tooltip": "Custom text displayed at the top of the end session display."},
    # Scoreboard
    {"key": "LAUNCH_SCOREBOARD_ON_STARTUP", "config_key": "launch_scoreboard_on_startup", "label": "Auto-start Scoreboard:", "type": "bool", "default": False, "requires_scoreboard": True, "tooltip": "Automatically launch the scoreboard when the app starts."},
    {"key": "AUTO_EXIT_SCOREBOARD",         "config_key": "auto_exit_scoreboard",         "label": "Auto-exit Scoreboard:",  "type": "bool", "default": False, "requires_scoreboard": True, "tooltip": "Automatically close the scoreboard when this app exits."},
    # Web server
    {"key": "WEB_SERVER_ENABLED", "config_key": "web_server_enabled", "label": "Auto-start Web Server:", "type": "bool", "default": False, "requires_tunnel": True, "tooltip": "Automatically start the web answer server when the app launches. Can also be started/stopped manually from the Bonus Questions menu."},
    {"key": "NGROK_DOMAIN",       "config_key": "ngrok_domain",       "label": "Ngrok Domain:",          "type": "str",      "default": "", "width": 30, "requires_ngrok": True, "tooltip": "Your ngrok static domain (e.g. your-name.ngrok-free.app). Exposes the web server publicly. Requires ngrok.exe on PATH."},
    {"key": "CLOUDFLARE_TUNNEL_TOKEN", "config_key": "cloudflare_tunnel_token", "label": "Cloudflare Tunnel Token:", "type": "password", "default": "", "width": 30, "requires_cloudflared": True, "tooltip": "Token from the Cloudflare Zero Trust dashboard (Networks → Tunnels). Takes priority over ngrok when set."},
    {"key": "CLOUDFLARE_PUBLIC_URL",   "config_key": "cloudflare_public_url",   "label": "Cloudflare Public URL:",   "type": "str",      "default": "", "width": 30, "requires_cloudflared": True, "tooltip": "The public HTTPS URL for your Cloudflare tunnel (e.g. https://gta.yourdomain.com). Must match the hostname configured in the Cloudflare dashboard."},
    {"key": "HOST_PASSWORD",      "config_key": "host_password",      "label": "Host Password:",         "type": "password", "default": "", "width": 30, "requires_tunnel": True, "tooltip": "If set, entering this password on the join screen grants host view (live answer panel + metadata). Leave blank to disable."},
    # Toggles persistence
    {"key": "keep_set_toggles", "config_key": "keep_set_toggles", "label": "Keep Set Toggles:", "type": "bool", "default": True, "tooltip": "Remember the state of Censors, Auto Refresh, Info Start, Info End, Keyboard Shortcuts, Progress Bar, Fullscreen, Collapsed Interface, and Always On Top toggles across restarts."},
]

# Initialise all schema settings to their defaults at module level so they always
# exist as globals even before load_config() is called.
_type_cast_init = {"int": int, "float": float, "bool": bool}
for _s in SETTINGS_SCHEMA:
    if _s["key"] not in dir():
        _cast = _type_cast_init.get(_s["type"])
        globals()[_s["key"]] = _cast(_s["default"]) if _cast else _s["default"]
del _s, _cast, _type_cast_init
_sync_control_state_from_globals()

DISPLAY_SCREEN_WIDTH, DISPLAY_SCREEN_HEIGHT = pyautogui.size()
def scl(num, type=None):
    if type == "UI" and not scale_main_ui:
        return num
    modifier_w, modifier_h = DISPLAY_SCREEN_WIDTH / 2560, DISPLAY_SCREEN_HEIGHT / 1440
    modifier = min(modifier_w, modifier_h)
    return int(num*modifier)

# =========================================
#         *FETCHING ANIME METADATA
# =========================================


fetch_anilist_user_ids = metadata_fetch.fetch_anilist_user_ids

pre_fetch_metadata = metadata_fetch.pre_fetch_metadata
invalidate_file_metadata_cache = metadata_fetch.invalidate_file_metadata_cache
build_filename_to_mal_map = metadata_fetch.build_filename_to_mal_map
get_metadata = metadata_fetch.get_metadata
get_file_metadata_by_name = metadata_fetch.get_file_metadata_by_name
get_version_from_filename = metadata_fetch.get_version_from_filename

refetch_metadata = metadata_fetch.refetch_metadata


aired_to_season_year = metadata_fetch.aired_to_season_year



get_artists_string = metadata_fetch.get_artists_string
fetch_all_metadata = metadata_fetch.fetch_all_metadata
refresh_all_anilist_metadata = metadata_fetch.refresh_all_anilist_metadata
refresh_all_metadata = metadata_fetch.refresh_all_metadata
refresh_all_igdb_metadata = metadata_fetch.refresh_all_igdb_metadata
# =========================================
#         *METADATA DISPLAY — see _app_scripts/file/metadata/metadata_display.py
# =========================================
import _app_scripts.file.metadata.metadata_display as metadata_display

# State that stays in main: read by sibling modules through getter callbacks
# bound to main's attributes (see [[state-stays-with-its-readers]]). The
# metadata_display module writes to these via _main.X.
updating_metadata       = False    # async-update lock (read by metadata_fetch)
selected_extra_metadata = "synopsis"  # panel tab selector (read by metadata_panel, streaming)
show_spoiler_tags       = False    # spoiler-tags toggle (read by metadata_panel)
reroll_button           = None     # right-column reroll button (widget ref)

metadata_display.set_context(main_module=sys.modules[__name__])

# Aliases for metadata_panel re-exports (these were assigned here originally;
# the new module reads them via _main).
update_metadata                = metadata_panel.update_metadata
update_popout_currently_playling = metadata_panel.update_popout_currently_playling
update_extra_metadata          = metadata_panel.update_extra_metadata
update_series_song_information = metadata_panel.update_series_song_information

# Public-API aliases so the rest of main + sibling modules that look up
# main.X keep working without a rename pass.
clear_metadata                = metadata_display.clear_metadata
open_mal_page                 = metadata_display.open_mal_page
anime_themes_video            = metadata_display.anime_themes_video
open_animethemes_anime_page   = metadata_display.open_animethemes_anime_page
open_anidb_page               = metadata_display.open_anidb_page
open_anilist_page             = metadata_display.open_anilist_page
reset_metadata                = metadata_display.reset_metadata
update_metadata_queue         = metadata_display.update_metadata_queue
toggle_spoiler_tags           = metadata_display.toggle_spoiler_tags
select_extra_metadata         = metadata_display.select_extra_metadata
open_image_popup              = metadata_display.open_image_popup
create_cover_popup            = metadata_display.create_cover_popup
up_next_text                  = metadata_display.up_next_text
update_up_next_display        = metadata_display.update_up_next_display
adjust_up_next_height         = metadata_display.adjust_up_next_height
get_display_title             = metadata_display.get_display_title
_safe_int                     = metadata_display._safe_int
is_game                       = metadata_display.is_game
add_field_total_button        = metadata_display.add_field_total_button
series_list                   = metadata_display.series_list
series_set                    = metadata_display.series_set
series_primary                = metadata_display.series_primary
series_overlap                = metadata_display.series_overlap
series_cache_key              = metadata_display.series_cache_key
get_all_matching_field        = metadata_display.get_all_matching_field
get_all_theme_from_series     = metadata_display.get_all_theme_from_series
get_overall_theme_number      = metadata_display.get_overall_theme_number
get_slug_extra                = metadata_display.get_slug_extra
has_same_start                = metadata_display.has_same_start
get_filenames_from_artist     = metadata_display.get_filenames_from_artist
get_filenames_from_studio     = metadata_display.get_filenames_from_studio
add_multiple_data_line        = metadata_display.add_multiple_data_line
add_single_data_line          = metadata_display.add_single_data_line
overall_theme_num_display     = metadata_display.overall_theme_num_display
get_file_props_label          = metadata_display.get_file_props_label
_get_version_flags            = metadata_display._get_version_flags
get_file_marks                = metadata_display.get_file_marks
prioritize_theme_files        = metadata_display.prioritize_theme_files
get_theme_filename            = metadata_display.get_theme_filename
get_theme_filenames           = metadata_display.get_theme_filenames
play_video_from_filename      = metadata_display.play_video_from_filename
toggleColumnEdit              = metadata_display.toggleColumnEdit

# Private helpers + module-local constant used by other main-level code.
_play_name_key                = metadata_display._play_name_key
_build_web_series_themes      = metadata_display._build_web_series_themes
_calc_plays_info              = metadata_display._calc_plays_info
_fmt_plays                    = metadata_display._fmt_plays
_build_played_series_map      = metadata_display._build_played_series_map
LISTS_TO_CLOSE                = metadata_display.LISTS_TO_CLOSE
# =========================================
#            *YOUTUBE VIDEOS
# =========================================

youtube_queue = None
get_youtube_duration = youtube_ui.get_youtube_duration
get_youtube_metadata_from_index = youtube_ui.get_youtube_metadata_from_index
unload_youtube_video = youtube_ui.unload_youtube_video
get_youtube_display_title = youtube_ui.get_youtube_display_title
stream_youtube = youtube_ui.stream_youtube
check_youtube_video_playing = youtube_ui.check_youtube_video_playing
_youtube_playlist = youtube_ui._youtube_playlist
show_youtube_playlist = youtube_ui.show_youtube_playlist
shorten_youtube_title = youtube_ui.shorten_youtube_title
get_youtube_title = youtube_ui.get_youtube_title
_set_youtube_queue = youtube_ui._set_youtube_queue
load_youtube_video = youtube_ui.load_youtube_video
_archived_youtube_playlist = youtube_ui._archived_youtube_playlist
show_archived_youtube_playlist = youtube_ui.show_archived_youtube_playlist
load_archived_youtube_video = youtube_ui.load_archived_youtube_video
load_bonus_template = youtube_ui.load_bonus_template
load_youtube_censors = youtube_ui.load_youtube_censors
save_youtube_censors = youtube_ui.save_youtube_censors
update_youtube_metadata = youtube_ui.update_youtube_metadata
insert_column_line = youtube_ui.insert_column_line
save_youtube_metadata = youtube_control.save_youtube_metadata

load_youtube_metadata = youtube_control.load_youtube_metadata


# =========================================
#           *CREATE PLAYLIST
# =========================================

playlist_changed = False

empty_playlist = playlist_ops.empty_playlist

# Generate playlist button
generate_playlist_button = playlist_ops.generate_playlist_button




generate_anilist_playlist = playlist_ops.generate_anilist_playlist

generate_animethemes_playlist = playlist_ops.generate_animethemes_playlist

generate_session_log_playlist = playlist_ops.generate_session_log_playlist

update_living_playlists = playlist_ops.update_living_playlists

_playlist_has_unsaved_changes = playlist_ops._playlist_has_unsaved_changes


new_playlist = playlist_ops.new_playlist

create_infinite_playlist = playlist_ops.create_infinite_playlist

# =========================================
#            *SHUFFLE PLAYLIST
# =========================================

randomize_playlist = playlist_ops.randomize_playlist
weighted_randomize = playlist_ops.weighted_randomize

# =========================================
#          *INFINITE PLAYLISTS
# =========================================

INFINITE_SETTINGS_DEFAULT = {
    "max_history_check": 10000,
    "difficulty_groups": {
        "easy": {
            "range": [1, 250],
            "cooldown": [0.5, 0.6],
            "file_boost_limit": 20
        },
        "medium": {
            "range": [251, 1000],
            "cooldown": [0.75, 0.9],
            "file_boost_limit": 5
        },
        "hard": {
            "range": [1001, float('inf')],
            "cooldown": [1.0, 1.0],
            "file_boost_limit": 1
        },
        "all": {
            "range": [1, float('inf')],
            "cooldown": [1.0, 1.5],
            "file_boost_limit": 1
        }
    },
    "ending_limit_ratio": 0.5,
    "recent_boost_multiplier": [20,10,5],
    "favorites_boost_multiplier": 2,
    "score_boost": {
        "min_score": 7.5,
        "multiplier": 1.0
    },
    "group_series": True,
    "tag_cooldown": 1,
    "include_non_local_files": False,
    "deduplicate_files": True,
    "deduplicate_versions": False,
    "preload_track_count": 5
}

infinite_settings = INFINITE_SETTINGS_DEFAULT.copy()

difficulty_options = ["MODE: VERY EASY","MODE: EASY","MODE: NORMAL","MODE: HARD","MODE: VERY HARD","MODE: RANDOM"]
INT_INF = float('inf')

get_infinite_settings = playlist_ops.get_infinite_settings
select_difficulty = playlist_ops.select_difficulty
_set_difficulty_from_menu = playlist_ops._set_difficulty_from_menu
get_cached_deduplicated_files = playlist_ops.get_cached_deduplicated_files
invalidate_deduplicated_cache = playlist_ops.invalidate_deduplicated_cache
deduplicate_theme_versions = playlist_ops.deduplicate_theme_versions
get_directory_files = playlist_ops.get_directory_files
get_pop_time_groups = playlist_ops.get_pop_time_groups
get_next_infinite_track = playlist_ops.get_next_infinite_track
_promote_or_generate_next = playlist_ops._promote_or_generate_next
is_reroll_valid = playlist_ops.is_reroll_valid
reroll_next = playlist_ops.reroll_next
# =========================================
#         *SAVING/LOADING DATA
# =========================================

convert_infinities_to_markers = utils.convert_infinities_to_markers
convert_infinity_markers = utils.convert_infinity_markers

# ----- Config I/O + migrations + popout-layout presets ----- see _app_scripts/data/config_io.py
import _app_scripts.data.config_io as config_io

config_io.set_context(main_module=sys.modules[__name__])

_atomic_json_write          = config_io._atomic_json_write
_migrate_old_file_structure = config_io._migrate_old_file_structure
_migrate_playlist_names     = config_io._migrate_playlist_names
_load_popout_layout_presets = config_io._load_popout_layout_presets
_save_popout_layout_preset  = config_io._save_popout_layout_preset
save_config                 = config_io.save_config
load_config                 = config_io.load_config

_load_settings_presets   = utils._load_settings_presets
_save_settings_presets   = utils._save_settings_presets
_migrate_theme_flags     = utils._migrate_theme_flags

interpolate_color = utils.interpolate_color

# Color interpolation functions

tutorial_shown = False  # Written to config after first launch
ToolTip = tooltip.ToolTip


def update_playlist_name(name=None):
    if name:
        playlist["name"] = name
    extra_text = ""
    if playlist.get("infinite"):
        extra_text = " ∞"
    root.title(f"[{get_themes_played_count()}] {WINDOW_TITLE} - {playlist["name"]}{extra_text}")
    if web_server.is_running():
        _push_web_toggles()

# ----- Metadata I/O ---- see _app_scripts/data/metadata_io.py
import _app_scripts.data.metadata_io as metadata_io

metadata_io.set_context(main_module=sys.modules[__name__])

save_metadata           = metadata_io.save_metadata
save_metadata_overrides = metadata_io.save_metadata_overrides
load_metadata           = metadata_io.load_metadata
# REVIEW_MODIFIER and estimate_* live in metadata_io now; re-exported for
# any callers that still look them up on main.
REVIEW_MODIFIER             = metadata_io.REVIEW_MODIFIER
estimate_manual_popularity  = metadata_io.estimate_manual_popularity
estimate_manual_rank        = metadata_io.estimate_manual_rank

# ----- Update checks / import / export ----- see _app_scripts/data/updates_io.py
import _app_scripts.data.updates_io as updates_io

# Track when metadata was last updated (Unix timestamp). State stays in main
# because save_config reads it. updates_io writes via _main.X = ...
metadata_last_updated = 0
censors_last_updated  = 0

updates_io.set_context(main_module=sys.modules[__name__])

IMPORT_PACKAGE_URL              = updates_io.IMPORT_PACKAGE_URL
IMPORT_CENSORS_URL              = updates_io.IMPORT_CENSORS_URL
LOCAL_METADATA_PACKAGE          = updates_io.LOCAL_METADATA_PACKAGE
import_data_from_package        = updates_io.import_data_from_package
check_for_metadata_updates      = updates_io.check_for_metadata_updates
check_for_censor_updates        = updates_io.check_for_censor_updates
download_scoreboard             = updates_io.download_scoreboard
check_for_local_metadata_package = updates_io.check_for_local_metadata_package
export_metadata_package         = updates_io.export_metadata_package
import_censors                  = updates_io.import_censors
import_data_from_source         = updates_io.import_data_from_source


deep_merge = utils.deep_merge


# =========================================
#           *HELP/*TUTORIAL POPUP
# =========================================

show_tutorial_popup = tutorial.open_tutorial_popup


# =========================================
#           *SAVE/*LOAD PLAYLISTS
# =========================================

save = playlist_ops.save
save_as = playlist_ops.save_as
_load_playlist_by_name = playlist_ops._load_playlist_by_name

load = playlist_ops.load
load_system_playlist = playlist_ops.load_system_playlist
delete = playlist_ops.delete
merge_playlist = playlist_ops.merge_playlist
delete_file_by_filename = playlist_ops.delete_file_by_filename
open_file_folder_by_filename = playlist_ops.open_file_folder_by_filename
rename_file_by_filename = playlist_ops.rename_file_by_filename
edit_file_volume_by_filename = playlist_ops.edit_file_volume_by_filename
convert_file_format_by_filename = playlist_ops.convert_file_format_by_filename
cut_before_current_time = playlist_ops.cut_before_current_time
cut_after_current_time = playlist_ops.cut_after_current_time
cleanup_old_update_exes = auto_update.cleanup_old_update_exes
check_for_updates_on_startup = auto_update.check_for_updates_on_startup

# =========================================
#           *STATS DISPLAY
# =========================================

year_stats = stats_ops.show_year_stats
season_stats = stats_ops.show_season_stats
artist_stats = stats_ops.show_artist_stats
series_stats = stats_ops.show_series_stats
studio_stats = stats_ops.show_studio_stats
tag_stats = stats_ops.show_tag_stats
anilist_tag_stats = stats_ops.show_anilist_tag_stats
slug_stats = stats_ops.show_slug_stats
type_stats = stats_ops.show_type_stats

load_filters = playlist_ops.load_filters
delete_filters = playlist_ops.delete_filters
filters = playlist_ops.filters
get_lowest_parameter = playlist_ops.get_lowest_parameter
get_highest_parameter = playlist_ops.get_highest_parameter
get_all_tags = playlist_ops.get_all_tags
get_all_studios = playlist_ops.get_all_studios

get_song_by_slug = utils.get_song_by_slug

_best_duplicate_map = {}
sort_playlist = playlist_ops.sort_playlist
SEARCH_BAR_PLACEHOLDER = "SEARCH THEMES"

search = search_ops.search
add_theme_next = search_ops.add_theme_next
add_search_playlist = search_ops.add_search_playlist
set_search_queue = search_ops.set_search_queue
search_playlist = search_ops.search_playlist
get_playlists_dict = playlist_ops.get_playlists_dict

# =========================================
#        *LIGHTNING ROUND SETTINGS
# =========================================

light_round_started = False
light_round_start_time = None
light_round_number = 0
LIGHT_ROUND_LENGTH_DEFAULT = lightning_settings.LIGHT_ROUND_LENGTH_DEFAULT
light_round_length = 12
LIGHT_ROUND_ANSWER_LENGTH_DEFAULT = lightning_settings.LIGHT_ROUND_ANSWER_LENGTH_DEFAULT
light_round_answer_length = 8
light_mode = None
light_modes = lightning_settings.light_modes

lightning_mode_settings_default = lightning_settings.lightning_mode_settings_default

lightning_mode_settings = {}
state.playback.lightning_mode_settings = lightning_mode_settings
selected_light_mode_settings = ""
saved_lightning_mode_settings = {}
selected_settings = ""
saved_infinite_settings = {}
selected_infinite_settings = ""
bonus_settings = {}
# Wire into state.playback. See core/game_state.py for identity contract.
state.playback.bonus_settings = bonus_settings
saved_bonus_settings = {}
selected_bonus_settings = ""


open_settings_editor = settings_actions.open_settings_editor
open_infinite_settings_editor = settings_actions.open_infinite_settings_editor
open_bonus_settings_editor = settings_actions.open_bonus_settings_editor

update_lightning_mode_settings = lightning_settings.update_lightning_mode_settings

sync_with_default = utils.sync_with_default
compute_settings_diff = utils.compute_settings_diff

toggle_light_mode = lightning_manager.toggle_light_mode
unselect_light_modes = lightning_manager.unselect_light_modes
def stop_all_queues():
    """Clear all queued special rounds: lightning, YouTube, search, and fixed lightning."""
    global fixed_lightning_queue, fixed_lightning_round_playlist_data, fixed_current_round
    # Clear lightning mode + button text
    unselect_light_modes()
    toggle_coming_up_popup(False, "Lightning Round")
    # Clear YouTube queue (handles its own popup + button state)
    unload_youtube_video()
    # Clear search queue
    if search_ops.search_queue:
        search_ops.search_queue = None
    # Clear fixed lightning (queued and/or currently active playlist)
    if fixed_lightning_queue or fixed_lightning_round_playlist_data:
        fl_name = (fixed_lightning_queue or fixed_lightning_round_playlist_data or {}).get("name")
        fixed_lightning_queue = None
        fixed_lightning_round_playlist_data = None
        fixed_current_round = None
        if fl_name:
            toggle_coming_up_popup(False, fl_name)
        update_playlist_display()
    up_next_text()


# =========================================
#          *LIGHTNING ROUND START
# =========================================

light_speed_modifier = 1
light_blind_one_second_count = None
stream_start_time = 0
current_light_mode = None
current_light_variant = None
title_light_string = ""
title_light_letters = None
_light_answer_wall_start = None  # wall-clock time when the answer phase began (set on first tick)
_light_answer_last_tick  = None  # wall-clock time of last update_light_round call in answer phase (pause compensation)
_wall_time = __import__('time').time  # alias so the 'time' parameter inside update_light_round doesn't shadow it
_showed_lightning_answer = False
update_light_round = lightning_manager.update_light_round

# Lightning round runtime helpers — extracted to lightning_manager.py.
# Aliased here so existing call sites (update_light_round, the *. rounds,
# settings menus, etc.) keep using the bare names.
clean_up_light_round   = lightning_manager.clean_up_light_round
light_round_transition = lightning_manager.light_round_transition


#=========================================
#       *LIGHTNING ROUND ALIASES + LOCAL PRIMITIVES
#=========================================
# All lightning-round logic lives in _app_scripts/queue_round/lightning_rounds/.
# The aliases below let main’s existing call sites use bare names. A few
# code blocks interspersed below are general-purpose primitives that stay
# in main (used by non-lightning paths too) — see inline notes.

# --- Re-exports from lightning_manager + per-round modules ---
queue_next_lightning_mode  = lightning_manager.queue_next_lightning_mode
set_variety_light_mode     = variety_round.set_variety_light_mode
get_series_popularity      = variety_round.get_series_popularity
has_lightning_mode_info    = variety_round.has_lightning_mode_info
set_openai_client_key      = trivia_round.set_openai_client_key
extract_response_text      = trivia_round.extract_response_text
generate_anime_trivia      = trivia_round.generate_anime_trivia
get_cached_sfw_themes      = mismatch_round.get_cached_sfw_themes

# --- Per-overlay module aliases (only those still referenced by name in main) ---
toggle_mc_choices_overlay = synopsis_overlay.toggle_mc_choices_overlay
get_base_title            = title_overlay.get_base_title
# PEEK (dispatch + renderer + filter)
get_next_peek_mode        = peek_dispatch.get_next_peek_mode
_activate_peek_variant    = peek_dispatch._activate_peek_variant
is_peek_active            = peek_dispatch.is_peek_active
toggle_peek               = peek_dispatch.toggle_peek
toggle_peek_round         = peek_dispatch.toggle_peek_round
toggle_mute_peek_round    = peek_dispatch.toggle_mute_peek_round
_queue_peek_variant       = peek_dispatch._queue_peek_variant
_queue_peek_random        = peek_dispatch._queue_peek_random
narrow_peek               = peek_dispatch.narrow_peek
widen_peek                = peek_dispatch.widen_peek
get_peek_gap              = peek_dispatch.get_peek_gap
toggle_peek_overlay       = peek_overlay.toggle_peek_overlay
toggle_filter_vf          = filter_overlay.toggle_filter_vf
toggle_edge_overlay       = edge_overlay.toggle_edge_overlay
toggle_grow_overlay       = grow_overlay.toggle_grow_overlay
move_grow_position        = grow_overlay.move_grow_position
load_default_char_images  = characters_overlay.load_default_char_images

# character_round_answer state stays in main (read by every character-mode
# round + the lightning ticker; character_parts_overlay reads it via
# main_globals['character_round_answer']).
character_round_answer = None

# --- ASS OSD ID constants (lightning + bonus + playback overlays) ---
_PROGRESS_ASS_OSD_ID      = 52   # thin progress bar
# _BLIND_ASS_OSD_ID (53) moved to _app_scripts/playback/blind_screen.py
_OUTER_EDGE_ASS_OSD_ID    = 54   # bottom censor bar
_CENSOR_ASS_OSD_IDS       = list(range(100, 140))  # IDs 100-139 for up to 40 censor boxes — mpv renders lower IDs on top, so higher IDs render behind peek/grow/edge (50-59)
_OST_COVER_ASS_OSD_ID     = 57   # OST answer transition cover
_SYNOPSIS_ASS_OSD_ID      = 58   # synopsis / trivia box
_INFO_POPUP_ASS_OSD_ID    = 59   # anime info popup
# _FRAME_BORDER_ASS_OSD_ID (80) / _FRAME_OUTLINE_ASS_OSD_ID (81) moved to blind_screen.py
# play/pause icon state (_playpause_icon_after_ids, _playpause_img_overlay) moved to
# _app_scripts/playback/playpause_icon.py

# --- get_title_text_lines (Tk Font measurement; injected into title_overlay via set_context) ---
def get_title_text_lines(text, max_width, font=("Courier New", scl(80), "bold")):
    f = Font(family=font[0], size=font[1], weight=font[2])
    words = text.split(" ")
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        if f.measure(test_line) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

# --- Scoreboard helpers (general; here historically) ---
def send_scoreboard_command(cmd): scoreboard_control.send_command(cmd)
def is_scoreboard_running(): return scoreboard_control.is_running()
open_scoreboard = scoreboard_control.open_scoreboard
def send_scoreboard_colors(): scoreboard_control.send_colors(OVERLAY_BACKGROUND_COLOR, OVERLAY_TEXT_COLOR)
def send_scoreboard_score(player_name, delta): scoreboard_control.send_score(player_name, delta)
def read_all_score_changes(): return scoreboard_control.read_score_changes()
def add_score_changes_to_session(): scoreboard_control.add_score_changes_to_session(session_stats.session_data)

# --- _osd_command — shared osd-overlay wrapper used by 20+ overlay sites across main ---
def _osd_command(*args):
    """Send an osd-overlay command to the main player."""
    try:
        player._p.command(*args)
    except Exception:
        pass

# --- spawn_pulsating_music_note — used by MISMATCH and other lightning paths; general overlay primitive ---
_note_img_overlay = None
_note_anim_after = None

def spawn_pulsating_music_note(x=0, y=0, font_size=scl(100), destroy=False):
    global _note_img_overlay, _note_anim_after

    # Cancel any running animation
    if _note_anim_after is not None:
        try:
            root.after_cancel(_note_anim_after)
        except Exception:
            pass
        _note_anim_after = None

    # Remove existing overlay
    if _note_img_overlay is not None:
        try:
            _note_img_overlay.remove()
        except Exception:
            pass
        _note_img_overlay = None

    if destroy:
        return

    # Pick a random bright color once per spawn
    note_color = (random.randint(100, 255), random.randint(100, 255), random.randint(100, 255), 255)

    # Try Segoe UI Emoji so we can render 🎵 properly; fall back to Arial ♪
    _emoji_font_cache = {}
    def _get_note_font(px):
        if px not in _emoji_font_cache:
            from PIL import ImageFont
            for path in ["C:/Windows/Fonts/seguiemj.ttf", "C:/Windows/Fonts/seguisym.ttf"]:
                try:
                    _emoji_font_cache[px] = ImageFont.truetype(path, px)
                    break
                except Exception:
                    pass
            else:
                _emoji_font_cache[px] = _get_ass_font(px, bold=False)
        return _emoji_font_cache[px]

    NOTE_TEXT = "\U0001F3B5"  # 🎵

    _note_img_overlay = player._p.create_image_overlay()
    _step = [0.0]
    _last_osd = [0, 0]  # track last known OSD size for dynamic rebase
    _frame_cache = [None, None, None]  # [last_px, last_canvas_w, last_canvas]

    def _note_step():
        global _note_img_overlay, _note_anim_after
        if _note_img_overlay is None:
            return
        try:
            cur_osd_w = player._p.osd_width or 1920
            cur_osd_h = player._p.osd_height or 1080
        except Exception:
            cur_osd_w, cur_osd_h = 1920, 1080

        # Dynamically rebase whenever OSD size changes
        if cur_osd_w != _last_osd[0] or cur_osd_h != _last_osd[1]:
            _last_osd[0] = cur_osd_w
            _last_osd[1] = cur_osd_h
            _step[1] = max(60, int(cur_osd_h * 0.30))   # base_px
            _step[2] = int(_step[1] * 1.15)              # max_px
            _frame_cache[0] = None  # force redraw on resize

        base_px = _step[1]
        max_px  = _step[2]

        if not player.is_playing():
            _note_anim_after = root.after(50, _note_step)
            return

        _step[0] += 0.9  # pulse speed
        px = int(base_px + math.sin(_step[0]) * (max_px - base_px) / 2)

        # Only re-render when the pixel size actually changed
        if px == _frame_cache[0] and cur_osd_w == _frame_cache[1]:
            _note_anim_after = root.after(50, _note_step)
            return

        from PIL import Image, ImageDraw
        canvas = Image.new("RGBA", (cur_osd_w, cur_osd_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        font = _get_note_font(px)
        if font:
            bbox = draw.textbbox((0, 0), NOTE_TEXT, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (cur_osd_w - tw) // 2 - bbox[0]
            ty = (cur_osd_h - th) // 2 - bbox[1]
            # 8-point outline — vastly cheaper than a full grid loop
            border = max(3, px // 22)
            for dx, dy in ((-border, 0), (border, 0), (0, -border), (0, border),
                           (-border, -border), (border, -border), (-border, border), (border, border)):
                draw.text((tx + dx, ty + dy), NOTE_TEXT, font=font, fill=(0, 0, 0, 200))
            draw.text((tx, ty), NOTE_TEXT, font=font, fill=note_color)

        _frame_cache[0] = px
        _frame_cache[1] = cur_osd_w
        _frame_cache[2] = canvas
        try:
            _note_img_overlay.update(canvas)
        except Exception:
            _note_img_overlay = None
            return
        _note_anim_after = root.after(50, _note_step)

    # Initialise the per-step size slots before the first call
    try:
        _init_h = player._p.osd_height or 1080
    except Exception:
        _init_h = 1080
    _step.append(max(60, int(_init_h * 0.30)))   # index 1: base_px
    _step.append(int(_step[1] * 1.15))            # index 2: max_px
    _step.append(0)                               # index 3: unused sentinel
    _note_step()
#          *STREAMING/*CACHE
# =========================================



def is_animethemes_stream_file(filename):
    not_animethemes_strings = ["[ID]", "[MAL]", "[IGDB]"]
    if any(s in filename for s in not_animethemes_strings) or ".webm" not in filename.lower():
        return False
    return True

animethemes_stream = None
stream_icon = '📶'
active_downloads        = cache_download.active_downloads        # module-owned; alias for legacy refs
download_cancel_flags   = cache_download.download_cancel_flags   # module-owned
cache_metadata          = cache_download.cache_metadata          # module-owned
downloads_completed     = 0  # local alias; see cache_download.downloads_completed
download_ui_update_pending = False  # local alias; see cache_download.download_ui_update_pending
pending_play_queue      = cache_download.pending_play_queue      # module-owned
download_progress       = cache_download.download_progress       # module-owned

get_animethemes_stream_url = cache_download.get_animethemes_stream_url
load_cache_metadata = cache_download.load_cache_metadata
get_cached_file_path = cache_download.get_cached_file_path
entry_paths.set_context(
    directory_files=directory_files,
    get_cached_file_path=get_cached_file_path,
    play_name_key=_play_name_key,
)
download_animethemes_file = cache_download.download_animethemes_file
move_cached_file_to_directory = cache_download.move_cached_file_to_directory
cancel_download = cache_download.cancel_download
prefetch_next_themes = cache_download.prefetch_next_themes


# =========================================
#          *CLIP/*TRAILER LIGHTNING ROUND
# =========================================
# Logic already extracted in prior steps:
#   * Streaming/playback → _app_scripts.playback.streaming
#   * YouTube ID + URL helpers → _app_scripts.queue_round.youtube.youtube_control
# `last_image_source` (formerly here) now lives on cover_image_overlay since
# it is written by IMAGE-round image fetching and read only by the
# answer-screen IMAGE-SOURCE banner.
import _app_scripts.playback.streaming as streaming

extract_youtube_id_from_trailer = youtube_control.extract_youtube_id_from_trailer

get_youtube_stream_url = youtube_control.get_youtube_stream_url

stream_url = streaming.stream_url
stop_stream = streaming.stop_stream
play_trailer = streaming.play_trailer
get_stream_start_time = streaming.get_stream_start_time
play_random_clip = streaming.play_random_clip
load_random_clips = streaming.load_random_clips
stream_clip = streaming.stream_clip
test_print = streaming.test_print

# ===== Overlay window tracker =====
# Keeps Tkinter Toplevel overlays pinned over the mpv window as it moves/resizes.
_tracked_overlay_windows = {}           # Toplevel -> (img_w, img_h, y_nudge_frac, centered, on_resize)
_last_mpv_rect_tracker = (None, None, None, None)
_overlay_tracker_running = False
_overlay_tracker_sync_tick = 0   # counts 100ms ticks; forces positional re-sync every 5 ticks (500ms)


def _do_overlay_tracker():
    global _last_mpv_rect_tracker, _overlay_tracker_running, _overlay_tracker_sync_tick
    # Prune destroyed windows
    for w in list(_tracked_overlay_windows):
        try:
            if not w.winfo_exists():
                del _tracked_overlay_windows[w]
        except Exception:
            _tracked_overlay_windows.pop(w, None)

    if not _tracked_overlay_windows:
        _overlay_tracker_running = False
        _last_mpv_rect_tracker = (None, None, None, None)
        _overlay_tracker_sync_tick = 0
        return

    mx, my, mw, mh = _get_mpv_window_rect()
    lmx, lmy, lmw, lmh = _last_mpv_rect_tracker

    _overlay_tracker_sync_tick += 1
    periodic_sync = (_overlay_tracker_sync_tick >= 5)
    if periodic_sync:
        _overlay_tracker_sync_tick = 0

    if mw and lmx is not None:
        dx = mx - lmx
        dy = my - lmy
        dw = mw - lmw
        dh = mh - lmh
        changed = bool(dx or dy or dw or dh)

        if changed or periodic_sync:
            # Deduplicate on_resize callbacks — each unique callable runs once per tick
            called_callbacks = set()
            for win, (img_w, img_h, y_nudge, cent, on_resize, on_size_change) in list(_tracked_overlay_windows.items()):
                try:
                    if not win.winfo_exists():
                        continue
                    if on_size_change:
                        # Only rebuild when the mpv window actually resized; otherwise delta-move
                        if dw or dh:
                            cb_id = id(on_size_change)
                            if cb_id not in called_callbacks:
                                called_callbacks.add(cb_id)
                                on_size_change()
                        elif changed:
                            win.geometry(f"+{win.winfo_x() + dx}+{win.winfo_y() + dy}")
                    elif on_resize:
                        cb_id = id(on_resize)
                        if cb_id not in called_callbacks:
                            called_callbacks.add(cb_id)
                            on_resize()
                    elif cent:
                        x = mx + (mw - img_w) // 2
                        y = my + (mh - img_h) // 2 + int(mh * y_nudge)
                        win.geometry(f"+{x}+{y}")
                    elif changed:
                        win.geometry(f"+{win.winfo_x() + dx}+{win.winfo_y() + dy}")
                except Exception:
                    pass

    if mw:
        _last_mpv_rect_tracker = (mx, my, mw, mh)

    # Lift image overlay windows only when _mpv_tracker_poll is NOT running
    # (i.e. no title popup). When _mpv_tracker_poll IS running it handles all
    # lifting in the correct z-order (overlays first, then popup on top).
    if information_popup._mpv_tracker_id is None:
        for win in list(_tracked_overlay_windows):
            try:
                if win.winfo_exists():
                    win.lift()
            except Exception:
                pass

    root.after(100, _do_overlay_tracker)

_outer_edge_overlay_active = None
def toggle_outer_edge_overlay(destroy=False, pixels=65, color="black"):
    """Bottom censor bar drawn via mpv osd-overlay (ASS).  Covers the bottom `pixels`
    screen-pixels-equivalent of the video, e.g. to hide Crunchyroll watermarks."""
    global _outer_edge_overlay_active

    if destroy:
        if _outer_edge_overlay_active:
            _outer_edge_overlay_active = None
            try:
                _osd_command('osd-overlay', _OUTER_EDGE_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
            except Exception:
                pass
        return

    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    # When framed_video is active, anchor bar to the bottom of the framed video rect.
    if blind_screen._video_frame_active:
        _, _, fv_x, fv_y, fv_w, fv_h = _get_effective_video_rect()
        # Scale bar height relative to the framed video height instead of the full OSD height.
        bar_h = max(1, round(pixels * fv_h / 1080))
        bar_x = fv_x
        bar_y = fv_y + fv_h - bar_h
        bar_w = fv_w
    else:
        # Scale bar height from reference 1080p screen pixels to OSD pixels.
        bar_h = max(1, round(pixels * osd_h / 1080))
        bar_x, bar_y, bar_w = 0, osd_h - bar_h, osd_w
    color_bgr = _color_str_to_ass_bgr(color)

    ass_payload = (
        f"{{\\an7\\pos(0,{bar_y})"
        f"\\1c&H{color_bgr}&\\1a&H00&\\bord0\\shad0\\p1}}"
        f"m {bar_x} 0 l {bar_x+bar_w} 0 {bar_x+bar_w} {bar_h} {bar_x} {bar_h}{{\\p0}}"
    )
    try:
        _osd_command('osd-overlay', _OUTER_EDGE_ASS_OSD_ID, 'ass-events',
                          ass_payload, osd_w, osd_h, 1, 'no')  # z=1, same as blind layer
    except Exception:
        return
    _outer_edge_overlay_active = True  # sentinel — truthy while active

# =========================================
#          *OST LIGHTNING ROUND
# =========================================
# Extracted to _app_scripts.queue_round.lightning_rounds.ost_overlay.
# Stateless helper — no set_context needed.
extract_track_name_from_youtube_title = ost_overlay.extract_track_name_from_youtube_title
# =========================================
#          *OVERLAY PRIMITIVES
# =========================================
# This section was historically labelled "LIGHTNING ROUND OVERLAYS" but on
# audit almost every helper here is general-purpose UI infrastructure used
# by bonus rounds, playback, the web server timer, and every extracted
# overlay module via set_context injection — not lightning-specific.
# The two helpers that ARE lightning-specific (update_light_round_number,
# set_light_round_number) have been moved to lightning_manager.
update_light_round_number = lightning_manager.update_light_round_number
set_light_round_number    = lightning_manager.set_light_round_number

set_countdown = osd_text.set_countdown
bottom_info = osd_text.bottom_info
top_info = osd_text.top_info
_get_courier_font = osd_text._get_courier_font
_get_ass_font = osd_text._get_ass_font
_get_floating_osd_id = osd_text._get_floating_osd_id
_color_str_to_ass_bgr = osd_text._color_str_to_ass_bgr
floating_windows = osd_text.floating_windows
_ass_wrap_text = osd_text._ass_wrap_text
set_floating_text = osd_text.set_floating_text
_get_fixed_playlist_progress = progress_overlay_ops._get_fixed_playlist_progress
_rebuild_progress_bg_layer = progress_overlay_ops._rebuild_progress_bg_layer
_redraw_progress_overlay = progress_overlay_ops._redraw_progress_overlay
_progress_overlay_tick = progress_overlay_ops._progress_overlay_tick
set_progress_overlay = progress_overlay_ops.set_progress_overlay
pulsate_music_icon = progress_overlay_ops.pulsate_music_icon
# =========================================
#          *FIXED LIGHTNING ROUNDS
# =========================================
# FIXED_LIGHTNING_ROUNDS, FIXED_LIGHTNING_ROUND_FIELD_INDEX and editor UI
# are now in _app_scripts/fixed_lightning.py
FIXED_LIGHTNING_FOLDER = fixed_lightning.FIXED_LIGHTNING_FOLDER

fixed_lightning_queue = None  # {"name": str, "rounds": list, "current_index": int}
fixed_lightning_round_playlist_data = {}  # Loaded JSON data for current fixed round
fixed_current_round = None # Current round data
fixed_lightning_rounds_list = []  # List of available fixed lightning rounds
# Wire into state.playback. See core/game_state.py for identity contract.
state.playback.fl_rounds_list = fixed_lightning_rounds_list

fixed_lightning_actions.set_context(main_module=sys.modules[__name__])
load_fixed_lightning_rounds         = fixed_lightning_actions.load_fixed_lightning_rounds
_queue_fixed_lightning_round_by_index = fixed_lightning_actions._queue_fixed_lightning_round_by_index
_play_fixed_lightning_round_now     = fixed_lightning_actions._play_fixed_lightning_round_now
show_fixed_lightning_list           = fixed_lightning_actions.show_fixed_lightning_list
queue_fixed_lightning_round         = fixed_lightning_actions.queue_fixed_lightning_round

open_fixed_lightning_manager = fixed_lightning.open_fixed_lightning_manager

# =========================================
#            *MUSIC — see _app_scripts/playback/music.py
# =========================================

import _app_scripts.playback.music as music
state.playback.music_files = music.music_files  # identity-contract alias
load_music_files               = music.load_music_files
play_background_music          = music.play_background_music

background_music_rounds = 0  # Track rounds where background music is actually playing

# =========================================
#            *INFORMATION POPUP — see _app_scripts/information/information_popup.py
# =========================================
import _app_scripts.information.information_popup as information_popup

# Boolean info-type flags stay in main: read in many places (popout button
# state, web toggles, lightning round logic, keyboard shortcuts). The popup
# module writes them via _main.X = ...; see [[state-stays-with-its-readers]].
title_info_only = False
artist_info_display = False
studio_info_display = False
season_info_display = False
year_info_display = False
_title_popup_intent = False  # True as soon as we intend to show the popup

information_popup.set_context(main_module=sys.modules[__name__])

# Public API aliases (kept so the rest of main + sibling modules calling
# main.X continue to work without a rename pass).
toggle_info_popup               = information_popup.toggle_info_popup
toggle_title_info_popup         = information_popup.toggle_title_info_popup
toggle_artist_info_popup        = information_popup.toggle_artist_info_popup
toggle_studio_info_popup        = information_popup.toggle_studio_info_popup
toggle_season_info_popup        = information_popup.toggle_season_info_popup
toggle_year_info_popup          = information_popup.toggle_year_info_popup
update_popout_title_button_text = information_popup.update_popout_title_button_text
animate_window                  = information_popup.animate_window
get_artist_themes_data          = information_popup.get_artist_themes_data
get_studio_entries_data         = information_popup.get_studio_entries_data
_get_mpv_window_rect            = information_popup._get_mpv_window_rect
_get_mpv_client_rect_logical    = information_popup._get_mpv_client_rect_logical
_register_mpv_tracked_window    = information_popup._register_mpv_tracked_window
_unregister_mpv_tracked_window  = information_popup._unregister_mpv_tracked_window
_blind_osd_on_mpv_rect          = information_popup._blind_osd_on_mpv_rect
_get_osd_video_rect             = information_popup._get_osd_video_rect
_get_effective_video_rect       = information_popup._get_effective_video_rect
_hide_title_popup_osd           = information_popup._hide_title_popup_osd
_draw_title_popup_osd           = information_popup._draw_title_popup_osd
_title_popup_slide_in           = information_popup._title_popup_slide_in
_title_popup_slide_out          = information_popup._title_popup_slide_out
is_title_window_up              = information_popup.is_title_window_up
toggle_title_popup              = information_popup.toggle_title_popup
get_format                      = information_popup.get_format
get_episode_display             = information_popup.get_episode_display
_shorten_platform               = information_popup._shorten_platform
get_tags_string                 = information_popup.get_tags_string
get_tags                        = information_popup.get_tags
get_song_string                 = information_popup.get_song_string

# =========================================
#         *BONUS QUESTIONS  — see _app_scripts/bonus.py
# =========================================
import _app_scripts.bonus.bonus as bonus
import _app_scripts.bonus.answers as bonus_answers

BONUS_SETTINGS_DEFAULT = bonus.BONUS_SETTINGS_DEFAULT

guess_extra = bonus.guess_extra

# =========================================
#         *RULES — see _app_scripts/scoreboard_control.py
# =========================================

get_available_rules_files = scoreboard_control.get_available_rules_files
load_rules = scoreboard_control.load_rules
scoreboard_rules = load_rules()
def set_rules(type=None): scoreboard_control.set_rules(scoreboard_rules, type, web_server, _push_web_toggles)

# =========================================
#         *VIDEO PLAYBACK/CONTROLS
# =========================================

currently_playing = {}
# Wire into state.playback. See core/game_state.py for identity contract.
state.playback.currently_playing = currently_playing
def play_video(index=playlist["current_index"]):
    """Function to play a specific video by index"""
    global video_stopped, light_round_start_time
    global title_light_string, title_light_letters, playlist_loaded, playing_next_error, light_round_started
    global fixed_lightning_queue, fixed_lightning_round_playlist_data, fixed_current_round, light_round_answer_length
    global current_light_mode, current_light_variant, playlist_changed
    playlist_loaded = False
    playlist_changed = False
    playlist_ops.playlist_changed = False
    light_round_start_time = None
    synopsis_overlay.synopsis_start_index = None
    title_light_string = ""
    title_light_letters = None
    clean_up_light_round(True)
    light_round_started = False
    current_light_mode = None
    current_light_variant = None
    video_stopped = True
    playing_next_error = False
    if web_server.is_running():
        web_server.push_skip_grant('')
    if not (bonus.guessing_extra == "buzzer" and auto_bonus_start == "buzzer"):
        guess_extra()
    toggle_title_popup(False)
    set_countdown()
    toggle_coming_up_popup(False)
    if session_end.end_message_window:
        toggle_end_message()

    if playlist["current_index"] < len(playlist["playlist"]) and index + 1 >= len(playlist["playlist"]) and not youtube_queue and not search_ops.search_queue and not fixed_lightning_queue:
        _promote_or_generate_next()
    
    if fixed_lightning_queue or fixed_lightning_round_playlist_data:
        if fixed_lightning_queue and (not fixed_lightning_round_playlist_data or (fixed_lightning_round_playlist_data.get("name") != fixed_lightning_queue.get("name"))):
            fixed_lightning_round_playlist_data = copy.deepcopy(fixed_lightning_queue)
            fixed_lightning_round_playlist_data["current_index"] = 0
            # Update playlist display to show fixed rounds
            update_playlist_display()
            
            # Add session log entry for starting fixed rounds
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            fixed_rounds_entry = {
                "timestamp": timestamp,
                "type": "fixed_rounds_start",
                "playlist_name": fixed_lightning_round_playlist_data.get("name", "Unknown"),
                "creator": fixed_lightning_round_playlist_data.get("creator", "N/A"),
                "round_count": len(fixed_lightning_round_playlist_data.get("rounds", []))
            }
            session_stats.add_entry(fixed_rounds_entry)
            save_session_history(create_text_file=False)
        else:
            fixed_lightning_round_playlist_data["current_index"] += skip_direction
        index = fixed_lightning_round_playlist_data["current_index"]
        if index < 0 or index >= len(fixed_lightning_round_playlist_data.get("rounds", [])):
            _was_test = fixed_lightning_round_playlist_data.get('is_test', False)
            fixed_lightning_round_playlist_data = None
            fixed_lightning_queue = None
            fixed_current_round = None
            light_round_answer_length = lightning_mode_settings["_misc_settings"].get("answer_length", LIGHT_ROUND_ANSWER_LENGTH_DEFAULT)
            
            # Revert playlist display back to normal
            update_playlist_display()
            
            toggle_light_mode()
            if _was_test:
                stop()
            else:
                play_video(playlist["current_index"] + skip_direction)
            return
        fixed_current_round = fixed_lightning_round_playlist_data.get("rounds", [])[index]
        filename = fixed_current_round.get("theme")
        rnd_mode = fixed_current_round.get("type", "regular")
        light_round_answer_length = fixed_current_round.get("answer_duration", lightning_mode_settings["_misc_settings"].get("answer_length", LIGHT_ROUND_ANSWER_LENGTH_DEFAULT))
        
        # Update playlist display to show current fixed round
        update_playlist_display()
        
        if light_mode != rnd_mode:
            toggle_light_mode(rnd_mode, queue=False, show_popup=False)
        if play_filename(filename):
            root.after(3000, thread_prefetch_metadata)
            root.after(1000, queue_next_lightning_mode)
        up_next_text()
    elif youtube_queue is not None:
        currently_playing.clear()
        currently_playing.update({
            "type":"youtube",
            "filename": youtube_queue.get("filename"),
            "data":youtube_queue
        })
        set_black_screen(False)
        reset_metadata()
        update_youtube_metadata()
        if "guess the character" in (get_youtube_display_title(youtube_queue)).lower():
            set_rules("character")
        else:
            set_rules("anime")
        
        video_path = os.path.join("youtube", youtube_queue.get("filename"))
        archive_path = os.path.join("youtube", "archive", youtube_queue.get("filename"))
        if os.path.exists(video_path):
            stream_youtube(video_path)
        elif os.path.exists(archive_path):
            stream_youtube(archive_path)
        else:
            # Stream from YouTube URL using yt-dlp
            video_id = youtube_queue.get('video_id') or youtube_queue.get('url')
            if video_id:
                print(f"Streaming from YouTube: {video_id}")
                youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                stream_url, duration = get_youtube_stream_url(youtube_url)
                if stream_url:
                    stream_youtube(stream_url)
                else:
                    print(f"Failed to get stream URL for {video_id}")
            else:
                print("Warning: Video not downloaded and no video_id found")
                stream_youtube(video_path)  # Try anyway
        
        unload_youtube_video()
        up_next_text()
    elif search_ops.search_queue:
        if is_youtube_file(search_ops.search_queue):
            youtube_data = get_youtube_metadata_by_filename(search_ops.search_queue)
            if youtube_data:
                currently_playing.clear()
                currently_playing.update({
                    "type":"youtube",
                    "filename": search_ops.search_queue,
                    "data":youtube_data
                })
                set_black_screen(False)
                reset_metadata()
                update_youtube_metadata(youtube_data)
                if "guess the character" in (get_youtube_display_title(youtube_data)).lower():
                    set_rules("character")
                else:
                    set_rules("anime")
                youtube_file_path = get_file_path(search_ops.search_queue)
                if youtube_file_path and os.path.exists(youtube_file_path):
                    stream_youtube(youtube_file_path)
                elif os.path.exists(os.path.join("youtube", search_ops.search_queue)):
                    stream_youtube(os.path.join("youtube", search_ops.search_queue))
                else:
                    # Stream from YouTube URL using yt-dlp
                    video_id = youtube_data.get('url')
                    if video_id:
                        print(f"Streaming from YouTube: {video_id}")
                        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                        stream_url, duration = get_youtube_stream_url(youtube_url)
                        if stream_url:
                            stream_youtube(stream_url)
                        else:
                            print(f"Failed to get stream URL for {video_id}")
                    else:
                        stream_youtube(os.path.join("youtube", search_ops.search_queue))  # Try anyway
            else:
                play_filename(search_ops.search_queue)
        else:
            play_filename(search_ops.search_queue)
        search_ops.search_queue = None
        up_next_text()
        if "SEARCH QUEUE" in popout_buttons_by_name:
            button_seleted(popout_buttons_by_name["SEARCH QUEUE"], False)
    elif 0 <= index < len(playlist["playlist"]):
        same_index = index == playlist["current_index"]
        update_current_index(index)
        up_next_text()
        
        playlist_entry = playlist["playlist"][playlist["current_index"]]
        filename = get_clean_filename(playlist_entry)
        
        if is_youtube_file(filename):
            youtube_data = get_youtube_metadata_by_filename(filename)
            if youtube_data:
                currently_playing.clear()
                currently_playing.update({
                    "type":"youtube",
                    "filename": filename,
                    "data":youtube_data
                })
                set_black_screen(False)
                reset_metadata()
                update_youtube_metadata(youtube_data)
                if "guess the character" in (get_youtube_display_title(youtube_data)).lower():
                    set_rules("character")
                else:
                    set_rules("anime")
                youtube_file_path = get_file_path(playlist_entry)
                if youtube_file_path and os.path.exists(youtube_file_path):
                    stream_youtube(youtube_file_path)
                elif os.path.exists(os.path.join("youtube", filename)):
                    stream_youtube(os.path.join("youtube", filename))
                else:
                    # Stream from YouTube URL using yt-dlp
                    video_id = youtube_data.get('url')
                    if video_id:
                        print(f"Streaming from YouTube: {video_id}")
                        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                        stream_url, duration = get_youtube_stream_url(youtube_url)
                        if stream_url:
                            stream_youtube(stream_url)
                        else:
                            print(f"Failed to get stream URL for {video_id}")
                    else:
                        stream_youtube(os.path.join("youtube", filename))  # Try anyway
            else:
                if play_filename(playlist_entry, fullscreen=not same_index or state.controls.autoplay_toggle != 1):
                    root.after(3000, thread_prefetch_metadata)
                    root.after(1000, queue_next_lightning_mode)
        else:
            if play_filename(playlist_entry, fullscreen=not same_index or state.controls.autoplay_toggle != 1):
                root.after(3000, thread_prefetch_metadata)
                root.after(1000, queue_next_lightning_mode)
    else:
        if index < 0:
            play_next()
        else:
            messagebox.showinfo("Playlist Error", "Invalid playlist index.")
        return
    
    if playlist["current_index"]+1 < len(playlist["playlist"]):
        next_filename = get_clean_filename(playlist["playlist"][playlist["current_index"]+1])
        root.after(1000, check_next_queue_round, next_filename)
    add_session_history()

def check_next_queue_round(next_filename_set):
    if playlist["current_index"]+1 < len(playlist["playlist"]):
        next_filename = get_clean_filename(playlist["playlist"][playlist["current_index"]+1])
        if next_filename_set == next_filename:
            if special_round_playlist:
                if check_blind_mark(next_filename):
                    toggle_blind_round()
                elif check_peek_mark(next_filename):
                    toggle_peek_round()
                elif check_mute_peek_mark(next_filename):
                    toggle_mute_peek_round()

skip_limit = 0
def skip_filename():
    global skip_limit
    blind_screen.blind_round_toggle = False
    peek_dispatch.peek_round_toggle = False
    peek_dispatch.mute_peek_round_toggle = False
    skip_limit += 1
    play_video(playlist["current_index"] + skip_direction)  # Try playing the next video

def play_filename_streaming_fallback(playlist_entry, fullscreen=True):
    """Handle streaming fallback when download times out."""
    global animethemes_stream
    
    # Extract filename from dict if necessary
    if isinstance(playlist_entry, dict):
        filename = playlist_entry.get('filename', playlist_entry.get('filepath', ''))
    else:
        filename = playlist_entry
    
    # Force streaming mode by setting filepath to stream URL
    filename = get_clean_filename(filename) 
    stream_url = None
    if isinstance(playlist_entry, dict) and '_stream_url' in playlist_entry:
        stream_url = playlist_entry['_stream_url']
    else:
        stream_url = get_animethemes_stream_url(filename)
    
    # Create modified entry with filepath
    if isinstance(playlist_entry, dict):
        modified_entry = playlist_entry.copy()
        modified_entry['filepath'] = stream_url
    else:
        modified_entry = {'filename': playlist_entry, 'filepath': stream_url}
    
    animethemes_stream = True
    return play_filename(modified_entry, fullscreen)

def play_filename(playlist_entry, fullscreen=True):
    global previous_media, skip_limit, animethemes_stream
    _pe_str = playlist_entry.get('filename', playlist_entry.get('filepath', '')) if isinstance(playlist_entry, dict) else playlist_entry
    filename = get_clean_filename(_pe_str)
    data = get_metadata(filename, fetch=auto_fetch_missing)
    
    local_filepath = get_file_path(playlist_entry)
    result = cache_download.resolve_playable_path(filename, playlist_entry, local_filepath, fullscreen)
    if result is None:
        return False
    filepath, animethemes_stream = result
    
    if skip_limit <= 10:
        if not filepath or not (os.path.exists(filepath) or animethemes_stream):  # Check if file exists
            print(f"File not found: {filepath}. Skipping...")
            skip_filename()
            return False
        elif not fixed_current_round and not variety_round.variety_light_mode_enabled and light_mode and not has_lightning_mode_info(data, light_mode):
            print(f"Not enough info for {filename}. Skipping...")
            skip_filename()
            return False
    
    # Start prefetching next themes after we've started playing
    threading.Thread(target=prefetch_next_themes, daemon=True).start()
    
    currently_playing.clear()
    currently_playing.update({
        "type":"theme",
        "filename":filename,
        "playlist_entry":playlist_entry,
        "data":data
    })
    censors.on_play_starting()
    if variety_round.variety_light_mode_enabled:
        set_variety_light_mode()
    if auto_info_start:
        toggle_title_popup(True)
    if auto_bonus_start and not (fixed_current_round and fixed_current_round.get("mc_choice_2")):
        pick = _pick_random_bonus() if auto_bonus_start == "random" else auto_bonus_start
        if pick == "buzzer" and bonus.guessing_extra == "buzzer":
            _web_buzzer_open()
            send_scoreboard_command("[CLEAR_SUBMITTED]")
            for _pname in web_server.get_connected_player_names():
                send_scoreboard_command(f"[SERVED]{_pname}")
            _refresh_popout_toggles()
            if web_server.is_running():
                _push_web_toggles()
        else:
            guess_extra(pick)
    # Update metadata display asynchronously
    update_metadata_queue(playlist["current_index"])
    previous_media = filepath  # store path string for repeat playback
    # Pre-load black cover: applied before set_media so OSD dims from the previous
    # video are still valid. Prevents the new file's first decoded frame from being
    # visible before blind/reveal overlays are active. The playback-restart hook
    # (or the blind_round_toggle branch below) reapplies/removes it as needed.
    if not light_mode and (blind_screen.blind_round_toggle or peek_dispatch.peek_round_toggle or peek_dispatch.mute_peek_round_toggle):
        _pre_load_blind_color = get_image_color() if blind_screen.blind_round_toggle else 'black'
        set_black_screen(True, smooth=False, color=_pre_load_blind_color)
    player.set_media(filepath)
    censors.reset_for_new_file(filename)
    global light_round_number, light_round_length, background_music_rounds
    if light_mode:
        if "c." in light_mode:
            set_rules("character")
        elif light_mode == "trivia":
            set_rules("trivia")
        else:
            set_rules("anime")
        
        # Exclude modes that don't play background music: clip, ost (streaming), regular, blind (play theme audio)
        if light_mode not in ['clip', 'ost', 'regular', 'blind']:
            if background_music_rounds > 0 and background_music_rounds % lightning_mode_settings["_misc_settings"]["background_music"]["rounds_per_track"] == 0:
                music.next_background_track()
            background_music_rounds += 1
        
        light_round_number = light_round_number + 1
        if light_mode != 'reveal':
            update_light_round_number()
            
        light_round_length = lightning_mode_settings.get(light_mode, {}).get("length", LIGHT_ROUND_LENGTH_DEFAULT)
        if fixed_lightning_round_playlist_data and fixed_current_round:
            light_round_length = fixed_current_round.get("duration", light_round_length)
        if not blind_screen.black_overlay:
            set_black_screen(True)
            root.after(500, player_play)
        else:
            player_play()
            set_volume(state.controls.volume_level)
    else:
        set_rules()
        light_round_number = 0
        set_countdown()
        set_light_round_number()
        toggle_coming_up_popup(False, "Lightning Round")
        if blind_screen.blind_round_toggle:
            blind_screen.manual_blind = True
            root.after(500, player_play)
        elif peek_dispatch.peek_round_toggle or peek_dispatch.mute_peek_round_toggle:
            blind_screen.manual_blind = False
            toggle_peek()
            if not peek_dispatch.peek_round_toggle:
                music.next_background_track()
                toggle_mute(True)
            root.after(500, player_play)
            # Don't remove the black screen here — playback-restart hook lifts it
            # once the peek overlay is confirmed active on the new file's first frame.
        else:
            blind_screen.manual_blind = False
            player_play()
            root.after(0, lambda: set_black_screen(False))
    blind_screen.blind_round_toggle = False
    peek_dispatch.peek_round_toggle = False
    peek_dispatch.mute_peek_round_toggle = False
    if fullscreen and state.controls.autoplay_fullscreen and light_mode not in ['clip', 'ost']:
        root.after(150, lambda: player.set_fullscreen(True))
    if light_mode not in ['frame', 'clip', 'ost', 'blind']:
        retry_delay = 250
        if animethemes_stream:
            retry_delay = 5000  # Longer delay for streaming to allow time for buffering
        if state.controls.autoplay_toggle != 3:
            root.after(retry_delay, play_video_retry, 5, filename)  # Retry playback
    
    if playlist.get("infinite", False):
        lightning_changed = False
        current_entry = playlist["playlist"][playlist["current_index"]]
        if not fixed_current_round and currently_playing.get("filename") == get_clean_filename(current_entry):
            if light_mode:  # Lightning round
                if not current_entry.startswith("[L]"):
                    playlist["playlist"][playlist["current_index"]] = "[L]" + current_entry
                    lightning_changed = True
            else:  # Normal round
                if current_entry.startswith("[L]"):
                    playlist["playlist"][playlist["current_index"]] = current_entry[3:]
                    lightning_changed = True
        
        if lightning_changed:
            root.after(10, refresh_current_list)
    
    # Update playlist name to reflect new count (will be updated when session log is added)
    root.after(100, update_playlist_name)
    skip_limit = 0
    save_config()
    return True

def player_play(override_autoplay=False):
    if state.controls.autoplay_toggle != 3 or override_autoplay:
        player.play()
    else:
        player.stop()

# =========================================
#         *SESSION LOGS
# =========================================


# session_data and session_start_time live in session_stats module
session_data        = session_stats.session_data        # mutable list alias
session_start_time  = None                              # mirrored via session_stats.session_start_time

reset_session_history = session_stats.reset_session_history
get_top_series_from_session = session_stats.get_top_series_from_session
get_top_artist_from_session = session_stats.get_top_artist_from_session
get_unique_themes_played = session_stats.get_unique_themes_played
get_themes_played_count = session_stats.get_themes_played_count
get_current_session_lightning_tracks = session_stats.get_current_session_lightning_tracks
create_new_session = session_stats.create_new_session
def add_session_history():                   session_stats.add_session_history(currently_playing, light_mode, playlist, SYSTEM_PLAYLISTS, bool(fixed_lightning_round_playlist_data))
save_session_history = session_stats.save_session_history

# =========================================
#         *PLAYBACK
# =========================================

def thread_prefetch_metadata():
    if auto_fetch_missing:
        threading.Thread(target=pre_fetch_metadata, daemon=True).start()

def play_video_retry(retries, filename=None):
    global video_stopped
    retry_delay = 2000
    if animethemes_stream:
        retry_delay = 5000 + 1000*(5-retries)  # Increase delay with each retry for streaming
    if (not player.is_playing() or player.get_length() == 0) and filename and currently_playing.get("filename") == filename:
        if retries > 0:
            if retries < 5:
                print(f"Retrying playback for: {currently_playing.get('filename')}")
                player_play()
            root.after(retry_delay, play_video_retry, retries - 1, filename)  # Retry playback
            return
        else:
            play_video(playlist["current_index"] + skip_direction)
    set_skip_direction(1)
    video_stopped = False

previous_media = None

def _handle_video_end():
    """Called on the main thread when a video reaches its natural end.
    Contains the advance-or-loop logic previously polled by check_video_end."""
    global video_stopped
    if video_stopped or state.controls.autoplay_toggle == 2:
        return
    # During the lightning question phase the player has paused at EOF (keep-open=yes).
    # Calling play_next() here risks falling through to the next-track path if any
    # state variable is momentarily inconsistent.  Instead, seek past the round
    # boundary directly and call player.play() so that update_light_round (which only
    # runs when the player IS playing) detects elapsed >= light_round_length and
    # triggers the answer phase normally.
    if light_round_started and light_round_start_time is not None and _light_answer_wall_start is None:
        try:
            if streaming.currently_streaming:
                seek_target_ms = round((stream_start_time + light_round_length + 0.1) * 1000)
                player.set_time(seek_target_ms)
            else:
                answer_ms = int((light_round_start_time + light_round_length + 0.05) * 1000)
                seek_to(answer_ms)
            was_playing = player.is_playing()
            if not was_playing:
                player.play()
        except Exception as e:
            print(f"[DBG _handle_video_end] exception in lightning branch: {e}")
        video_stopped = True  # guard against re-entry if eof-reached fires again
        return
    if state.controls.autoplay_toggle == 0:
        play_next()
        video_stopped = True
    else:
        player.pause()
        player.set_media(previous_media)
        player.play()


def update_current_index(value = None, save = True):
    """Function to update the playlist button counter label"""
    try:
        if value != None:
            playlist["current_index"] = value
        if globals().get("playlist_menu_button"):
            if playlist.get("infinite", False):
                out_of = playlist_ops.total_infinite_files - len(playlist_ops.cached_skipped_themes)
                counter = f"\u221e/{out_of}"
            else:
                out_of = len(playlist["playlist"])
                counter = f"{playlist['current_index']+1}/{out_of}"
            playlist_menu_button.config(text=f"PLAYLIST {counter}\u25be")
        
        if list_loaded == "playlist" and value is not None:
            global current_list_offset, current_list_selected
            # Update the selected index to match the current playing item
            current_list_selected = value
            entries_count = get_list_entries_count()
            current_start = current_list_offset
            current_end = current_list_offset + entries_count
            
            look_ahead = min(3, len(playlist["playlist"]) - value - 1)  # Don't look beyond playlist end
            needs_scroll = (value < current_start or value >= current_end or 
                          (value + look_ahead) >= current_end)
            
            if needs_scroll:
                ideal_offset = max(0, value - 1)  # Show current with 1 item before if possible
                max_offset = max(0, len(playlist["playlist"]) - entries_count)
                current_list_offset = min(ideal_offset, max_offset)
            refresh_current_list()
            
        if save:
            save_config()
        if web_server.is_running():
            if fixed_lightning_round_playlist_data and fixed_lightning_round_playlist_data.get("rounds"):
                fixed_rounds = fixed_lightning_round_playlist_data.get("rounds", [])
                fixed_index = fixed_lightning_round_playlist_data.get("current_index", 0)
                web_server.push_playlist_info(len(fixed_rounds), fixed_index, counter=(f'{fixed_index+1}/{len(fixed_rounds)}' if fixed_rounds else '0/0'), label=fixed_lightning_round_playlist_data.get('name') or 'Fixed Playlist')
            elif playlist.get('infinite', False):
                out_of = playlist_ops.total_infinite_files - len(playlist_ops.cached_skipped_themes)
                web_server.push_playlist_info(-1, -1, counter=f'\u221e/{out_of}', label=playlist.get('name') or 'Playlist')
            else:
                out_of = len(playlist['playlist'])
                cur = playlist['current_index']
                web_server.push_playlist_info(out_of, cur, counter=f'{cur+1}/{out_of}', label=playlist.get('name') or 'Playlist')
    except NameError:
        pass  # root isn't defined yet — possibly too early in startup

_cached_images = image_loader.cached_images
state.playback.cached_images = _cached_images
load_image_from_url = image_loader.load_image_from_url
load_pil_image_from_url = image_loader.load_pil_image_from_url

def go_to_index():
    """Function to jump to a specific index"""
    total = len(playlist["playlist"])
    index = simpledialog.askinteger("Go to Index", f"Enter track number (1\u2013{total}):", minvalue=1, maxvalue=total)
    if index is not None:
        play_video(index - 1)

# Play/pause icon overlay extracted to _app_scripts/playback/playpause_icon.py
import _app_scripts.playback.playpause_icon as playpause_icon
playpause_icon.set_context(main_module=sys.modules[__name__])
_show_playpause_icon = playpause_icon._show_playpause_icon


def play_pause():
    """Function to play/pause the video"""
    global video_stopped
    video_stopped = True
    if frame_round.frame_light_round_started:
        frame_round.frame_light_round_pause = not frame_round.frame_light_round_pause
        _show_playpause_icon(frame_round.frame_light_round_pause)
        return
    elif light_mode and lightning_mode_settings.get(light_mode, {}).get("muted") and light_mode not in ['clip', 'ost']:
        if player.is_playing():
            pygame.mixer.music.pause()
        elif light_round_start_time and ((player.get_time()/1000) < (light_round_start_time+light_round_length)):
            pygame.mixer.music.unpause()
    if player.is_playing():
        video_stopped = True
        player.pause()
        _show_playpause_icon(True)
    elif player.get_media():
        player.play()
        video_stopped = False
        _show_playpause_icon(False)
    else:
        play_video(playlist["current_index"])

# Function to play next video
skip_direction = 1
def set_skip_direction(dir):
    global skip_direction
    skip_direction = dir

def skip_to_lightning_answer():
    global light_blind_one_second_count
    if frame_round.frame_light_round_started:
        try:
            if frame_round.frame_light_round_frame_index is None or frame_round.frame_light_round_frame_index < 4:
                frame_round.frame_light_round_frame_index = 4
                frame_round.frame_light_round_frame_time = 0
                bottom_info()
                play_background_music(False)
                set_black_screen(False)
                toggle_title_popup(True)
                return True
        except Exception:
            pass
    if light_round_started and light_round_start_time is not None:
        try:
            if light_blind_one_second_count:
                player.play()
                light_blind_one_second_count = None
                player.play()

            # Already in answer phase — let play_next fall through to light_round_transition
            if _light_answer_wall_start is not None:
                return False

            if streaming.currently_streaming:
                # Seek the stream player to stream_start_time + light_round_length so
                # update_light_round's elapsed calculation crosses the round-end threshold.
                seek_target_ms = round((stream_start_time + light_round_length + 0.1) * 1000)
                player.set_time(seek_target_ms)
                return True

            answer_time = light_round_start_time + light_round_length
            target_ms = int((answer_time + 0.05) * 1000)
            seek_to(target_ms)
            return True
        except Exception as e:
            print(f"[DBG skip_to_lightning_answer] exception: {e}")
    return False

def play_next():
    if skip_to_lightning_answer():
        return
    elif (light_round_started or ((light_mode or fixed_lightning_queue) and light_round_number == 0)) and not blind_screen.black_overlay:
        light_round_transition()
        return
    if state.controls.special_repeat_track_mode:
        toggle_special_repeat()
    set_skip_direction(1)
    if playlist_loaded or playlist_ops.playlist_changed:
        play_video(playlist["current_index"])
    elif fixed_lightning_round_playlist_data or fixed_lightning_queue:
        play_video(playlist["current_index"])
    else:
        if playlist["current_index"] + 1 >= len(playlist["playlist"]):
            _promote_or_generate_next()
        if playlist["current_index"] + 1 < len(playlist["playlist"]):
            play_video(playlist["current_index"] + 1)

def play_previous():
    """Function to play previous video"""
    if playlist["current_index"] - 1 >= 0:
        set_skip_direction(-1)
        play_video(playlist["current_index"] - 1)

def stop():
    """Function to stop the video"""
    global video_stopped, light_round_started
    global fixed_lightning_queue, fixed_lightning_round_playlist_data, fixed_current_round
    currently_playing.clear()  # Clear first to prevent idle-active re-entry
    video_stopped = True
    toggle_light_mode()
    light_round_started = False
    set_countdown()
    set_light_round_number()
    set_black_screen(False)
    toggle_title_popup(False)
    if session_end.end_message_window:
        toggle_end_message()
    fixed_lightning_queue = None
    fixed_lightning_round_playlist_data = None
    fixed_current_round = None
    search_ops.search_queue = None
    unload_youtube_video()
    guess_extra()
    player.stop()
    player.set_media(None)  # Reset the media
    update_progress_bar(0,1)
    remove_all_censor_boxes()
    toggle_coming_up_popup(False, title=(coming_up_queue or {}).get("title", ""))
    seek_bar.set(0)
    clean_up_light_round(new_round=True)
    root.after(500, lambda: clean_up_light_round(new_round=True))

last_seek_time = None
def seek(value):
    """Function to seek the video"""
    global can_seek
    if can_seek:
        global last_seek_time
        last_seek_time = value
    else:
        can_seek = True

def seek_to(time_ms):
    """Function to seek the video to a specific time in milliseconds"""
    global projected_player_time
    time_ms = int(time_ms)
    apply_censors(time_ms/1000, player.get_length()/1000)
    projected_player_time = time_ms
    player.set_time(time_ms)

# Skip fade window (milliseconds)
SKIP_FADE_WINDOW_MS = 350
SKIP_FADE_IN_WINDOW_MS = 300
skip_fade_in_elapsed_ms = None

last_player_time = 0
projected_player_time = 0
last_skip_anchor_ms = None
SEEK_POLLING = 50
last_error = None
last_error_count = 0
playing_next_error = False
_web_playback_counter = 0   # throttle web playback state pushes to ~1/sec
def update_seek_bar():
    """Function to update the seek bar"""
    global last_player_time, projected_player_time, last_error, last_error_count, coming_up_queue, playing_next_error, can_seek, last_skip_anchor_ms, skip_fade_in_elapsed_ms
    try:
        if not player.is_playing():
            player_time = player.get_time()
            if player_time != last_player_time or last_player_time != projected_player_time:
                last_player_time = player_time
                projected_player_time = player_time
                if not last_seek_time:
                    can_seek = False
                    seek_bar.set(player_time/1000)
        else:
            player_time = player.get_time()
            if player_time != last_player_time:
                last_player_time = player_time
                projected_player_time = player_time
            else:
                projected_player_time = projected_player_time + SEEK_POLLING * light_speed_modifier
            skip_play_ms = int(max(0, float(skip_play_seconds)) * 1000)
            skip_jump_ms = int(max(0, float(skip_jump_seconds)) * 1000)
            skip_triggered = False
            if not light_round_started and bonus.guessing_extra and web_server.is_running():
                if (bonus.guessing_extra == "yt_bonus" and bonus._yt_bonus_current_question
                        and bonus._yt_bonus_current_question.get("end_time", 0) > 0):
                    _time_left = max(0.0, bonus._yt_bonus_current_question["end_time"] - projected_player_time / 1000)
                else:
                    _eff_rem = _effective_remaining_ms(
                        projected_player_time, player.get_length(),
                        currently_playing.get("filename")
                    )
                    _time_left = _eff_rem / 1000.0 - (8 if auto_info_end else 0)
                web_server.push_timer(_time_left, paused=True)
            if currently_playing.get("type") != "youtube" and not light_round_started and skip_play_ms > 0 and skip_jump_ms > 0:
                if last_skip_anchor_ms is None or last_seek_time or projected_player_time < last_skip_anchor_ms:
                    last_skip_anchor_ms = projected_player_time
                time_since_anchor = projected_player_time - last_skip_anchor_ms
                time_to_skip = skip_play_ms - time_since_anchor
                fade_window_ms = min(skip_play_ms, SKIP_FADE_WINDOW_MS)
                if skip_fade_in_elapsed_ms is None and not state.controls.disable_video_audio and fade_window_ms > 0:
                    if time_to_skip <= fade_window_ms:
                        fade_factor = max(0.0, min(1.0, time_to_skip / fade_window_ms))
                        player.audio_set_volume(int(state.controls.volume_level * fade_factor))
                    else:
                        player.audio_set_volume(state.controls.volume_level)
                if time_since_anchor >= (skip_play_ms - SEEK_POLLING):
                    # Nudge past the boundary so it doesn't immediately re-trigger
                    skip_offset = max(SEEK_POLLING, 1)
                    total_length_ms = player.get_length()
                    if total_length_ms > 0 and (projected_player_time + skip_jump_ms + skip_offset) >= total_length_ms:
                        play_next()
                    else:
                        seek_to(projected_player_time + skip_jump_ms + skip_offset)
                    last_skip_anchor_ms = projected_player_time + skip_jump_ms
                    skip_fade_in_elapsed_ms = 0
                    skip_triggered = True
            else:
                last_skip_anchor_ms = None
                skip_fade_in_elapsed_ms = None

            if not skip_triggered:
                if not state.controls.disable_video_audio and skip_fade_in_elapsed_ms is not None:
                    skip_fade_in_elapsed_ms += (SEEK_POLLING * light_speed_modifier)
                    fade_factor = max(0.0, min(1.0, skip_fade_in_elapsed_ms / max(1, SKIP_FADE_IN_WINDOW_MS)))
                    player.audio_set_volume(int(state.controls.volume_level * fade_factor))
                    if fade_factor >= 1.0:
                        skip_fade_in_elapsed_ms = None
                length = player.get_length()/1000
                time = projected_player_time/1000
                if blind_screen.manual_blind and not light_round_started:
                    _eff_time, _eff_len = _apply_skip_censor_to_progress(
                        time * 1000, length * 1000, currently_playing.get("filename")
                    )
                    set_progress_overlay(_eff_time / 1000, _eff_len / 1000)
                if peek_overlay.peek_overlay1 and not light_round_started:
                    gap = get_peek_gap(currently_playing.get("data"))
                    progress = ((time+peek_dispatch.peek_modifier)%24/12)*100
                    if progress >= 100:
                        direction = "right"
                        progress -= 100
                    else:
                        direction = "down"
                    toggle_peek_overlay(direction=direction, progress=progress, gap=gap)
                if length > 0:
                    # Auto-revoke skip grant when already within the last 3 seconds
                    if web_server.is_running() and web_server.get_skip_grant_player():
                        if time >= length - 3:
                            web_server.push_skip_grant('')
                    if not last_seek_time:
                        can_seek = False
                        seek_bar.config(to=length)
                        seek_bar.set(time)
                    if currently_playing.get("type") == "youtube":
                        start = currently_playing.get("data").get("start")
                        end = currently_playing.get("data").get("end")
                        yt_end_time = end if end != 0 else length
                        if time < start:
                            player.set_time(round(start*1000)+100)
                        elif end != 0 and time >= end:
                            player.pause()
                            play_next()
                        elif (yt_end_time - time) <= 8:
                            if (not is_title_window_up() or title_info_only) and auto_info_end and (not bonus.guessing_extra or bonus.guessing_extra == "buzzer"):
                                toggle_title_popup(True)
                        # Bonus template auto-trigger
                        for _bq_i, _bq in enumerate(bonus._yt_bonus_template_questions):
                            _bq_start = _bq.get("start_time", 0)
                            _bq_end = _bq.get("end_time", 0)
                            if _bq_i not in bonus._yt_bonus_template_triggered and time >= _bq_start:
                                if _bq_end > 0 and time >= _bq_end:
                                    # Already past this question's window — skip silently
                                    bonus._yt_bonus_template_triggered.add(_bq_i)
                                    bonus._yt_bonus_template_scored.add(_bq_i)
                                else:
                                    bonus._yt_bonus_template_triggered.add(_bq_i)
                                    bonus._yt_bonus_current_question = _bq
                                    bonus._yt_bonus_pts = float(_bq.get("points", 1))
                                    guess_extra("yt_bonus")
                                break
                            elif (_bq_i in bonus._yt_bonus_template_triggered and
                                  _bq_i not in bonus._yt_bonus_template_scored and
                                  _bq_end > 0 and time >= _bq_end):
                                bonus._yt_bonus_template_scored.add(_bq_i)
                                if bonus.guessing_extra == "yt_bonus":
                                    guess_extra("yt_bonus")
                                break
                        apply_censors(time, length)
                    else:
                        if not light_round_started and not video_stopped and (
                                _effective_remaining_ms(time * 1000, length * 1000,
                                                        currently_playing.get("filename")) / 1000.0 <= 8):
                            if (not is_title_window_up() or title_info_only) and auto_info_end:
                                toggle_title_popup(True)
                            if coming_up_queue:
                                toggle_coming_up_popup(True, title=coming_up_queue["title"], details=coming_up_queue["details"], image=coming_up_queue["image"], up_next=coming_up_queue["up_next"])
                                coming_up_queue = None
                        update_light_round(time)
                        apply_censors(time, length)
                update_progress_bar(projected_player_time, player.get_length(), currently_playing.get("filename"))
    except Exception as e:
        error_str = str(e)
        if not playing_next_error:
            if error_str == last_error:
                last_error_count += 1
                print(f"\rError: {error_str} x {last_error_count}", end='', flush=True)
            else:
                last_error = error_str
                last_error_count = 1
                if last_error_count > 20:
                    playing_next_error = True
                    play_next()
                print(f"\nError: {error_str} x 1", flush=True)
    # Push playback state to web host clients ~every 1 second
    global _web_playback_counter
    _web_playback_counter += 1
    if _web_playback_counter >= 20 and web_server.is_running():
        _web_playback_counter = 0
        try:
            web_server.push_playback_state(
                projected_player_time,
                player.get_length(),
                player.is_playing(),
                state.controls.volume_level,
                state.controls.autoplay_toggle,
                state.controls.bgm_volume,
                bzz_modifier=bonus_settings.get('buzzer', BONUS_SETTINGS_DEFAULT['buzzer']).get('sound_volume', 1.0),
                strm_boost=state.controls.stream_volume_boost
            )
            _push_web_toggles()
        except Exception:
            pass
    root.after(SEEK_POLLING, update_seek_bar)

format_seconds = utils.format_seconds

# =========================================
#            *COMING UP UI — see _app_scripts/playback/coming_up_ui.py
# =========================================
import _app_scripts.playback.coming_up_ui as coming_up_ui
coming_up_ui.set_context(
    get_ass_font=_get_ass_font,
    ass_wrap_text=_ass_wrap_text,
    osd_command=_osd_command,
    color_str_to_ass_bgr=_color_str_to_ass_bgr,
    seek_to=seek_to,
    main_globals=globals(),
)

# coming_up_queue stays in main because main's seek-bar ticker (update_seek_bar)
# rebinds it. The module reads/writes through main_globals['coming_up_queue'].
coming_up_queue = None

# Aliases for external callers (sibling modules + in-main call sites)
toggle_coming_up_popup = coming_up_ui.toggle_coming_up_popup
fast_forward_to_end    = coming_up_ui.fast_forward_to_end
show_skip_to_end_osd   = coming_up_ui.show_skip_to_end_osd

format_slug = utils.format_slug

# =========================================
#            *PROGRESS BAR
# =========================================

progress_bar = None  # kept for compatibility checks elsewhere (always None now)
progress_bar_enabled = True
_draw_progress_osd = progress_bar_ops._draw_progress_osd
_clear_progress_osd = progress_bar_ops._clear_progress_osd
_effective_remaining_ms = progress_bar_ops._effective_remaining_ms
_apply_skip_censor_to_progress = progress_bar_ops._apply_skip_censor_to_progress
update_progress_bar = progress_bar_ops.update_progress_bar

# =========================================
#            *BLIND SCREEN — see _app_scripts/playback/blind_screen.py
# =========================================
# Blind/black OSD overlay, framed-video effect, blind-round queue toggle.
# All state (black_overlay, blind_enabled, manual_blind, _blind_osd_color_cache,
# _video_frame_active/_zoom/_color, blind_round_toggle) lives in the module.
# External readers reach state via `blind_screen.X` (rebound at runtime — main
# aliases would desync). Function aliases below are stable refs.

import _app_scripts.playback.blind_screen as blind_screen

blind_screen.set_context(main_module=sys.modules[__name__])

set_video_frame        = blind_screen.set_video_frame
_set_blind_osd_alpha   = blind_screen._set_blind_osd_alpha
blind                  = blind_screen.blind
set_black_screen       = blind_screen.set_black_screen
set_blind_enabled      = blind_screen.set_blind_enabled
toggle_blind_round     = blind_screen.toggle_blind_round

# =========================================
#              *BLACK DESKTOP
# =========================================

# ---- OST cover overlay (used during OST → answer transition) ----
# Uses an ASS OSD overlay (same pipeline as the blind) so it always renders
# on top of the video regardless of window z-order.
_ost_cover_overlay = None

def _show_ost_cover():
    """Draw a solid ASS OSD overlay covering the full mpv canvas, using the blind's last color."""
    global _ost_cover_overlay
    _ost_cover_overlay = True
    try:
        osd_w = int(player._p.osd_width or 0) or root.winfo_screenwidth()
        osd_h = int(player._p.osd_height or 0) or root.winfo_screenheight()
        # Match the existing blind color for a seamless transition
        color_str = blind_screen._blind_osd_color_cache or "#000000"
        try:
            r16, g16, b16 = root.winfo_rgb(color_str)
            r, g, b = r16 >> 8, g16 >> 8, b16 >> 8
        except Exception:
            r, g, b = 0, 0, 0
        color_hex = f"{b:02X}{g:02X}{r:02X}"  # ASS: BGR
        path = f"m 0 0 l {osd_w} 0 {osd_w} {osd_h} 0 {osd_h}"
        ass = f"{{\\an7\\pos(0,0)\\1c&H{color_hex}&\\1a&H00&\\bord0\\shad0\\p1}}" + path + "{\\p0}"
        _osd_command('osd-overlay', _OST_COVER_ASS_OSD_ID, 'ass-events', ass, osd_w, osd_h, 1, 'no')
    except Exception:
        pass

def _hide_ost_cover():
    global _ost_cover_overlay
    _ost_cover_overlay = None
    try:
        _osd_command('osd-overlay', _OST_COVER_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
    except Exception:
        pass

# =========================================
#              *CENSOR BOXES
# =========================================
import _app_scripts.toggles.censors as censors

# Mutable containers shared by reference (mutations in censors module propagate here)
censor_list        = censors.censor_list
other_censor_lists = censors.other_censor_lists

_commit_censor_osd = censors._commit_censor_osd
remove_all_censor_boxes = censors.remove_all_censor_boxes
load_censors = censors.load_censors
apply_censors = censors.apply_censors
get_file_censors = censors.get_file_censors
get_random_blind_color = censors.get_random_blind_color
get_image_color = censors.get_image_color
update_censor_button_count = censors.update_censor_button_count



open_censor_editor = censors.open_censor_editor

censors.load_censors()

# =========================================
#            *TAG/*FAVORITE FILES
# =========================================
SYSTEM_PLAYLISTS = playlist_marks.SYSTEM_PLAYLISTS

get_playlist = playlist_marks.get_playlist
_push_web_marks = playlist_marks._push_web_marks

# _push_web_toggles owned by bonus_answers (joins _push_web_teams/_push_web_scores
# there). bonus_answers is imported above (L1918), so this alias resolves; the
# function reaches all main state/module-aliases via _main.X at call time.
_push_web_toggles = bonus_answers._push_web_toggles

toggle_theme = playlist_marks.toggle_theme
check_theme_cache = playlist_marks.check_theme_cache
state.playback.check_theme_cache = check_theme_cache
check_theme = playlist_marks.check_theme
tag = playlist_marks.tag
check_tagged = playlist_marks.check_tagged
favorite = playlist_marks.favorite
check_favorited = playlist_marks.check_favorited
check_new = playlist_marks.check_new
blind_mark = playlist_marks.blind_mark
check_blind_mark = playlist_marks.check_blind_mark
peek_mark = playlist_marks.peek_mark
check_peek_mark = playlist_marks.check_peek_mark
mute_peek_mark = playlist_marks.mute_peek_mark
check_mute_peek_mark = playlist_marks.check_mute_peek_mark
add_to_saved_playlist = playlist_marks.add_to_saved_playlist
handle_bulk_marking = playlist_marks.handle_bulk_marking
bulk_tag_playlist = playlist_marks.bulk_tag_playlist
bulk_favorite_playlist = playlist_marks.bulk_favorite_playlist
bulk_blind_mark_playlist = playlist_marks.bulk_blind_mark_playlist
bulk_peek_mark_playlist = playlist_marks.bulk_peek_mark_playlist
bulk_mute_peek_mark_playlist = playlist_marks.bulk_mute_peek_mark_playlist

def check_missing_artists():
    playlist["name"] = "Missing Artists"
    def remove_previous_playlist():
        try:
            os.remove(os.path.join(PLAYLISTS_FOLDER, f"{playlist["name"]}.json"))
        except Exception as e:
            print(e)
            pass
    missing_artists = []
    previous_removed = False
    for filename in directory_files:
        data = get_metadata(filename)
        for theme in data.get("songs",[]):
            if theme.get("slug") == data.get("slug") and theme.get("artist") == []:
                if not previous_removed:
                    remove_previous_playlist()
                    previous_removed = True
                toggle_theme(playlist["name"], filename)
                missing_artists.append(filename)
    playlist["playlist"] = missing_artists
    update_current_index(0)

# =========================================
#               *DOCK PLAYER
# =========================================

import _app_scripts.playback.dock_player as dock_player_mod
dock_player_mod.set_context(main_module=sys.modules[__name__])
toggle_player_collapse = dock_player_mod.toggle_player_collapse
dock_player = dock_player_mod.dock_player

move_root_to_bottom = windowing.move_root_to_bottom
is_docked = windowing.is_docked
popup_menu = windowing.popup_menu
get_window_position_and_setup = windowing.get_window_position_and_setup

# =========================================
#                  *LISTS
# =========================================

last_themes_listed = {}

list_loaded = None
list_index = 0
list_func = None
playlist_page_offset = 0

persistent_buttons = []  # Store the reusable buttons for any list type
button_to_index_map = {}  # Map button widgets to their current indices
current_list_offset = 0  # Offset for any list type
current_list_content = {}  # Store current list content
current_list_name_func = None  # Store current name function
current_list_selected = -1  # Store the currently selected/playing item index
current_list_show_numbers = True  # Whether to show "N: " index prefix on list buttons
current_list_title = ""  # Title shown at top of list, if any
_list_action_from_keyboard = False  # True when list_select() was triggered by a key press
right_column_header = None  # Persistent header Frame packed above right_column
right_column_header_label = None  # Label widget inside right_column_header
right_column_back_button = None  # ← back button; shown when _list_nav_stack is non-empty
list_title_label = None  # Points to right_column_header_label when active
right_column_scrollbar = None  # Custom scrollbar for the list display
list_header_font = None  # Font used by the list title header (set at GUI time)
_list_nav_stack = []  # Stack of 0-arg callables; each restores the previous list

_truncate_after_id = [None]  # debounce handle for _truncate_header_title

# Drag and drop variables
drag_start_index = None
drag_current_y = None

hovered_button_index = None
external_drag_active = False

# Global variables to track highlight tags
current_highlight_tag = None
current_source_tag = None
highlighted_buttons = {}  # Track highlighted button widgets

import _app_scripts.ui.lists as lists
lists.set_context(main_module=sys.modules[__name__])

_theme_context_menu = lists._theme_context_menu
show_field_themes = lists.show_field_themes
get_title = lists.get_title
set_field_queue = lists.set_field_queue
add_field_to_playlist = lists.add_field_to_playlist
show_playlist = lists.show_playlist
convert_fixed_rounds_to_dict = lists.convert_fixed_rounds_to_dict
get_fixed_round_title = lists.get_fixed_round_title
play_fixed_round_by_index = lists.play_fixed_round_by_index
remove = lists.remove
convert_playlist_to_dict = lists.convert_playlist_to_dict
update_playlist_display = lists.update_playlist_display
remove_theme = lists.remove_theme
button_seleted = lists.button_seleted
get_list_entries_count = lists.get_list_entries_count
push_list_nav = lists.push_list_nav
clear_list_nav = lists.clear_list_nav
_update_back_button = lists._update_back_button
_go_back_list = lists._go_back_list
_close_list = lists._close_list
_insert_list_title_row = lists._insert_list_title_row
_truncate_header_title = lists._truncate_header_title
_do_truncate_header_title = lists._do_truncate_header_title
_set_header_label = lists._set_header_label
update_list_scrollbar = lists.update_list_scrollbar
on_list_scrollbar_set = lists.on_list_scrollbar_set
create_persistent_list_buttons = lists.create_persistent_list_buttons
list_scroll_up = lists.list_scroll_up
list_scroll_down = lists.list_scroll_down
refresh_current_list = lists.refresh_current_list
update_persistent_list_display = lists.update_persistent_list_display
get_display_width = lists.get_display_width
truncate_by_display_width = lists.truncate_by_display_width
update_persistent_button = lists.update_persistent_button
handle_persistent_button_click = lists.handle_persistent_button_click
handle_persistent_right_click = lists.handle_persistent_right_click
handle_persistent_button_enter = lists.handle_persistent_button_enter
handle_persistent_button_leave = lists.handle_persistent_button_leave
handle_persistent_drag_start = lists.handle_persistent_drag_start
list_set_loaded = lists.list_set_loaded
list_unload = lists.list_unload
list_move = lists.list_move
list_select = lists.list_select
show_list = lists.show_list
start_playlist_drag = lists.start_playlist_drag
handle_drag_motion = lists.handle_drag_motion
highlight_drag_source = lists.highlight_drag_source
highlight_button_at_index = lists.highlight_button_at_index
clear_button_highlights = lists.clear_button_highlights
clear_target_highlights = lists.clear_target_highlights
clear_drop_highlight = lists.clear_drop_highlight
on_button_enter = lists.on_button_enter
on_button_leave = lists.on_button_leave
end_playlist_drag = lists.end_playlist_drag
add_single_line = lists.add_single_line


# =========================================
#                 *TOGGLES
# =========================================
# Toggle commands moved to their thematic homes:
#   buzzer ctrl → _app_scripts/bonus/buzz.py
#   auto bonus  → _app_scripts/bonus/bonus.py
#   auto info   → _app_scripts/information/information_popup.py
#   auto refresh→ _app_scripts/file/metadata/metadata_fetch.py
#   disable_shortcuts → _app_scripts/toggles/shortcut_dispatch.py
# State (auto_info_start, auto_info_end, auto_refresh_toggle, auto_bonus_start,
# disable_shortcuts) stays in main per [[state-stays-with-its-readers]].
auto_info_start = False
auto_bonus_start = None  # None = disabled; 'random' or a bonus type key = enabled
auto_info_end = False
auto_refresh_toggle = False

toggle_auto_info_start   = information_popup.toggle_auto_info_start
toggle_auto_info_end     = information_popup.toggle_auto_info_end
set_auto_bonus_start     = bonus.set_auto_bonus_start
_pick_random_bonus       = bonus._pick_random_bonus
toggle_auto_auto_refresh = metadata_fetch.toggle_auto_auto_refresh
# toggle_disable_shortcuts is aliased after shortcut_dispatch import (below).
# _web_buzzer_lock / _reset / _open are aliased after buzz import (below).

toggle_censor_bar = censors.toggle_censor_bar
toggle_censor_nsfw_bar = censors.toggle_censor_nsfw_bar

toggle_progress_bar = progress_bar_ops.toggle_progress_bar

disable_video_audio = False
light_muted = False
_sync_control_state_from_globals()

_AUDIO_DISTORTION_FILTERS = audio_toggles.AUDIO_DISTORTION_FILTERS
_audio_distortions_active = audio_toggles.audio_distortions_active
_apply_audio_distortions = audio_toggles._apply_audio_distortions
toggle_audio_distortion = audio_toggles.toggle_audio_distortion
toggle_mute = audio_toggles.toggle_mute

# =========================================
#              *END SESSION \u2014 see _app_scripts/file/session_end.py
# =========================================

from _app_scripts.file import session_end

session_end.set_context(
    get_ass_font=_get_ass_font,
    push_web_toggles=_push_web_toggles,
    send_scoreboard_command=send_scoreboard_command,
    main_globals=globals(),
)

end_session = session_end.end_session
toggle_end_message = session_end.toggle_end_message
get_op_ed_counts = session_stats.get_op_ed_counts
DEFAULT_END_SESSION_MESSAGE = session_end.DEFAULT_END_SESSION_MESSAGE




# =========================================
#            *POPOUT CONTROLS
# =========================================

# ---------------------------------------------------------------------------
# POPOUT LAYOUT CONFIGURATION
# ---------------------------------------------------------------------------
# Each entry: {"type": "action"|"widget"|"gap", "id": str, "colspan": int}
#   "action"  — resolved via get_flat_registry() by id; renders as a button
#   "widget"  — one of the special inline widgets (search, youtube, dropdowns…)
#   "gap"     — empty placeholder cell
#
# Special widget IDs:
#   "SEARCH ENTRY"        — text entry for theme search
#   "SEARCH DROPDOWN"     — combobox listing search results
#   "SEARCH QUEUE"        — button to queue/add the selected search result
#   "YOUTUBE DROPDOWN"    — combobox listing downloaded YouTube videos
#   "YOUTUBE QUEUE"       — button to queue the selected YouTube video
#   "LIGHTNING DROPDOWN"  — combobox to pick the lightning round mode
#   "DIFFICULTY DROPDOWN" — combobox to pick infinite-playlist difficulty
#   "toggle_metadata"     — button that shows/hides the currently-playing info area
# ---------------------------------------------------------------------------

POPOUT_LAYOUT_DEFAULT = [
    # ── Marks ───────────────────────────────────────────────────────────────
    {"type": "action", "id": "mute_peek_mark",        "colspan": 1, "custom_label": "MARK"},
    {"type": "action", "id": "tag",                   "colspan": 1},
    {"type": "action", "id": "favorite",              "colspan": 1},
    {"type": "action", "id": "info_popup",            "colspan": 1},
    {"type": "action", "id": "title_popup",           "colspan": 1},
    # ── Blind controls ──────────────────────────────────────────────────────
    {"type": "action", "id": "blind_mark",            "colspan": 1, "custom_label": "MARK"},
    {"type": "action", "id": "blind",                 "colspan": 1},
    {"type": "action", "id": "queue_blind_round",     "colspan": 1},
    {"type": "action", "id": "mute",                  "colspan": 1},
    {"type": "action", "id": "queue_mute_peek_round", "colspan": 1},
    # ── Peek controls ───────────────────────────────────────────────────────
    {"type": "action", "id": "peek_mark",             "colspan": 1, "custom_label": "MARK"},
    {"type": "action", "id": "peek",                  "colspan": 1},
    {"type": "action", "id": "queue_peek_round",      "colspan": 1},
    {"type": "action", "id": "narrow_peek",           "colspan": 1},
    {"type": "action", "id": "widen_peek",            "colspan": 1},
    # ── Bonus questions ─────────────────────────────────────────────────────
    {"type": "action", "id": "bonus_year",            "colspan": 1},
    {"type": "action", "id": "bonus_members",         "colspan": 1},
    {"type": "action", "id": "bonus_score",           "colspan": 1},
    {"type": "action", "id": "bonus_tags",            "colspan": 1},
    {"type": "action", "id": "bonus_multiple",        "colspan": 1},
    {"type": "action", "id": "bonus_rank",            "colspan": 1},
    {"type": "action", "id": "bonus_studio",          "colspan": 1},
    {"type": "action", "id": "bonus_artist",          "colspan": 1},
    {"type": "action", "id": "bonus_song",            "colspan": 1},
    {"type": "action", "id": "bonus_chars",           "colspan": 1},
    {"type": "action", "id": "bonus_freeform",        "colspan": 1},
    # ── Lightning ───────────────────────────────────────────────────────────
    {"type": "widget", "id": "LIGHTNING DROPDOWN",    "colspan": 2},
    {"type": "action", "id": "lightning_start",       "colspan": 1},
    {"type": "action", "id": "lightning_variety",     "colspan": 1},
    {"type": "widget", "id": "DIFFICULTY DROPDOWN",   "colspan": 2},
    # ── YouTube ─────────────────────────────────────────────────────────────
    {"type": "widget", "id": "YOUTUBE DROPDOWN",      "colspan": 2},
    {"type": "widget", "id": "YOUTUBE QUEUE",         "colspan": 1},
    # ── Search ──────────────────────────────────────────────────────────────
    {"type": "widget", "id": "SEARCH ENTRY",          "colspan": 2},
    {"type": "widget", "id": "SEARCH DROPDOWN",       "colspan": 2},
    {"type": "widget", "id": "SEARCH QUEUE",          "colspan": 1},
    # ── Misc ────────────────────────────────────────────────────────────────
    {"type": "action", "id": "dock_player",           "colspan": 1},
    {"type": "action", "id": "censors",               "colspan": 1},
    {"type": "widget", "id": "toggle_metadata",       "colspan": 1},
    {"type": "action", "id": "filter_editor",         "colspan": 1},
    {"type": "action", "id": "end_session",           "colspan": 1},
    # ── Player controls ─────────────────────────────────────────────────────
    {"type": "action", "id": "reroll_next",           "colspan": 1},
    {"type": "action", "id": "play_pause",            "colspan": 1, "icon_only": True},
    {"type": "action", "id": "stop",                  "colspan": 1, "icon_only": True},
    {"type": "action", "id": "previous",              "colspan": 1, "icon_only": True},
    {"type": "action", "id": "next",                  "colspan": 1, "icon_only": True},
]

# User-customised layout — None means "use POPOUT_LAYOUT_DEFAULT"
popout_layout: list | None = None
popout_columns: int = 5

popout_controls = None
popout_buttons_by_name = {}
state.playback.popout_buttons_by_name = popout_buttons_by_name
popout_up_next = None
popout_up_next_font = None
popout_current_font = None
popout_current_extra_font = None
popout_currently_playing = None
popout_currently_playing_extra = None
popout_button_font = None
resize_after_id = None
popout_show_metadata = True
popout_show_up_next = False
popout_show_currently_playing = False

def toggle_show_popout_currently_playing():
    global popout_show_currently_playing
    popout_show_currently_playing = not popout_show_currently_playing
    if popout_show_currently_playing:
        if currently_playing.get("data"):
            update_popout_currently_playling(currently_playing.get("data"))
        popout_currently_playing.configure(pady=0, fg="white")
    else:
        # Show placeholder when hidden with gray text
        popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
        popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
        popout_currently_playing_extra.delete(1.0, tk.END)
        popout_currently_playing_extra.config(state=tk.DISABLED)
    popout_controls.event_generate("<Configure>")

def toggle_show_popout_up_next():
    global popout_show_up_next
    popout_show_up_next = not popout_show_up_next
    if popout_show_up_next:
        update_up_next_display(popout_up_next)
    else:
        update_up_next_display(popout_up_next, clear=True)
    popout_controls.event_generate("<Configure>")

def toggle_show_popout_metadata():
    global popout_show_metadata
    popout_show_metadata = not popout_show_metadata
    button_seleted(popout_buttons_by_name["toggle_metadata"], popout_show_metadata)
    if popout_show_metadata:
        if popout_show_currently_playing and currently_playing.get("data"):
            update_popout_currently_playling(currently_playing.get("data"))
            popout_currently_playing.configure(pady=0, fg="white")
        elif not popout_show_currently_playing:
            # Show placeholder with gray text
            popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
            popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
            popout_currently_playing_extra.delete(1.0, tk.END)
            popout_currently_playing_extra.config(state=tk.DISABLED)
    else:
        # Clear currently playing completely
        popout_currently_playing.configure(text="", fg="white")
        popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
        popout_currently_playing_extra.delete(1.0, tk.END)
        popout_currently_playing_extra.config(state=tk.DISABLED)
    # Always update up-next display
    if popout_show_up_next:
        update_up_next_display(popout_up_next)
    else:
        update_up_next_display(popout_up_next, clear=False)
    popout_controls.event_generate("<Configure>")


def _refresh_popout_toggles():
    """Refresh the highlight state (and any dynamic text) of all action buttons
    currently displayed in the popout.  Safe to call at any time — silently
    exits if the popout is closed or the button no longer exists."""
    if not popout_controls:
        return
    try:
        flat = get_flat_registry()
    except Exception:
        return
    for item_id, widget in list(popout_buttons_by_name.items()):
        if not isinstance(widget, tk.Button):
            continue
        try:
            if not widget.winfo_exists():
                continue
        except Exception:
            continue
        reg_item = flat.get(item_id)
        if reg_item is None:
            continue
        # ── Update text for dynamic button_label / label lambdas ─────────────
        bl = reg_item.get("button_label") or reg_item.get("label", "")
        if callable(bl):
            icon = reg_item.get("icon", "")
            if callable(icon):
                icon = icon()
            # apply per-button overrides stashed at creation time
            custom_label = getattr(widget, "_spec_custom_label", "")
            show_icon    = getattr(widget, "_spec_show_icon", True)
            icon_only    = getattr(widget, "_spec_icon_only", False)
            if icon_only and icon:
                new_text = icon
            else:
                if custom_label:
                    bl_text = custom_label
                else:
                    bl_text = bl()
                if not show_icon:
                    icon = ""
                new_text = (f"{icon}{bl_text}".strip() if icon else bl_text).strip()
            try:
                widget.configure(text=new_text)
            except Exception:
                pass
        # ── Update highlight colour for toggle state ──────────────────────────
        toggle_fn = reg_item.get("toggle")
        if toggle_fn:
            try:
                is_on = bool(toggle_fn())
                widget.configure(bg=HIGHLIGHT_COLOR if is_on else "black")
            except Exception:
                pass


popout_searching = False
POPOUT_SEARCH_DEFAULT = "SEARCH THEMES"
create_popout_controls = popout_window.create_popout_controls




# =========================================
#                 *GUI SETUP
# =========================================

# Load saved configuration on startup
_migrate_old_file_structure()
_migrate_playlist_names()
load_config()

# Initialize themes cache
os.makedirs(THEMES_CACHE_FOLDER, exist_ok=True)
os.makedirs(RULES_FOLDER, exist_ok=True)
os.makedirs(youtube_control.YOUTUBE_BONUS_TEMPLATES_FOLDER, exist_ok=True)
os.makedirs(youtube_control.YOUTUBE_CENSORS_FOLDER, exist_ok=True)
_example_rules_path = os.path.join(RULES_FOLDER, "Example Rules.json")
if not os.path.exists(_example_rules_path):
    _example_rules = {
        "global_title": [
            "# **__RULES FOR GUESSING:__**"
        ],
        "standard": [
            "**2 PTs** Anime *(priority for full title)*",
            "> **+1 PT** OP/ED # *(e.g., Ending 2)*",
            "####### ",
            "**1 PT** Song Title / **1 PT** Artist/Band",
            "####### ",
            "*Copy and Edit this file to customize your rules.*"
        ],
        "lightning_anime": [
            "**1 PT** Anime *(full title not needed)*",
            "####### ",
            "Series accepted if title not said."
        ],
        "lightning_character": [
            "**2 PTs** Character *(full name priority)*",
            "**1 PT** Anime *(full title not needed)*",
            "####### ",
            "Series accepted if title not said."
        ],
        "lightning_trivia": [
            "**1 PT** Trivia Answer",
            "####### ",
            "Generated by AI, may be wrong."
        ],
        "global_end": [],
        "server_footer": [
            "# PLAY: **[URL]**"
        ]
    }
    try:
        with open(_example_rules_path, "w", encoding="utf-8") as _f:
            json.dump(_example_rules, _f, indent=4, ensure_ascii=False)
    except OSError as _e:
        print(f"[Rules] Could not create example rules file: {_e}")
if not os.path.isabs(directory) and not os.path.exists(directory):
    os.makedirs(directory, exist_ok=True)

BACKGROUND_COLOR = "gray12"
WINDOW_TITLE = f"Guess the Anime! Playlist Tool v{APP_VERSION}"

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
youtube_control.set_context(root)
utils.set_context(root)
osd_text.set_context(
    root=root,
    player=player,
    osd_command=_osd_command,
    web_server=web_server,
    is_bonus_guessing=lambda: bonus.guessing_extra,
    get_inverted_positions=lambda: inverted_positions,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    get_inverse_overlay_text_color=lambda: INVERSE_OVERLAY_TEXT_COLOR,
    get_inverse_overlay_background_color=lambda: INVERSE_OVERLAY_BACKGROUND_COLOR,
)
progress_overlay_ops.set_context(
    root=root,
    player=player,
    unregister_mpv_tracked_window=_unregister_mpv_tracked_window,
    get_fixed_lightning_round_playlist_data=lambda: fixed_lightning_round_playlist_data,
    get_fixed_current_round=lambda: fixed_current_round,
    get_light_mode=lambda: light_mode,
    get_lightning_mode_settings=lambda: lightning_mode_settings,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
    get_middle_overlay_background_color=lambda: MIDDLE_OVERLAY_BACKGROUND_COLOR,
    light_round_length_default=LIGHT_ROUND_LENGTH_DEFAULT,
    light_round_answer_length_default=LIGHT_ROUND_ANSWER_LENGTH_DEFAULT,
)
progress_bar_ops.set_context(
    player=player,
    osd_command=_osd_command,
    progress_osd_id=_PROGRESS_ASS_OSD_ID,
    get_progress_bar_enabled=lambda: progress_bar_enabled,
    set_progress_bar_enabled=lambda value: globals().update(progress_bar_enabled=value),
    get_light_round_started=lambda: light_round_started,
    get_light_round_start_time=lambda: light_round_start_time,
    get_light_answer_wall_start=lambda: _light_answer_wall_start,
    get_light_round_length=lambda: light_round_length,
    get_light_round_answer_length=lambda: light_round_answer_length,
    get_projected_player_time=lambda: projected_player_time,
    get_fixed_lightning_round_playlist_data=lambda: fixed_lightning_round_playlist_data,
    get_fixed_playlist_progress=_get_fixed_playlist_progress,
    wall_time=_wall_time,
    censors=censors,
    censor_json_file=CENSOR_JSON_FILE,
    apply_censors=apply_censors,
)
windowing.set_context(
    root=root,
    animate_window=animate_window,
)
auto_update.set_context(root, GITHUB_REPO, APP_VERSION, get_window_position_and_setup)
bonus_template_editor.set_context(
    get_window_position_and_setup=get_window_position_and_setup,
    seek_to=seek_to,
    get_projected_player_time=lambda: projected_player_time,
    background_color=BACKGROUND_COLOR,
    highlight_color=HIGHLIGHT_COLOR,
)
youtube_editor.set_context(
    get_window_position_and_setup=get_window_position_and_setup,
    get_projected_player_time=lambda: projected_player_time,
    play_video=play_video,
    set_youtube_queue=lambda v: globals().update(youtube_queue=v),
    get_ffmpeg_available=lambda: ffmpeg_available,
    root=root,
    background_color=BACKGROUND_COLOR,
)
generic_settings_editor.set_context(
    get_window_position_and_setup=get_window_position_and_setup,
)
open_generic_settings_editor = generic_settings_editor.open_generic_settings_editor
settings_actions.set_context(
    open_generic_settings_editor=open_generic_settings_editor,
    save_config=save_config,
    push_web_toggles=_push_web_toggles,
    sync_with_default=sync_with_default,
    get_lightning_settings=lambda: lightning_mode_settings,
    get_lightning_defaults=lambda: lightning_mode_settings_default,
    get_saved_lightning_settings=lambda: saved_lightning_mode_settings,
    get_selected_lightning_settings=lambda: selected_light_mode_settings,
    set_selected_lightning_settings=lambda value: globals().update(selected_light_mode_settings=value),
    get_infinite_settings=get_infinite_settings,
    get_infinite_defaults=lambda: INFINITE_SETTINGS_DEFAULT,
    get_saved_infinite_settings=lambda: saved_infinite_settings,
    get_selected_infinite_settings=lambda: selected_infinite_settings,
    set_selected_infinite_settings=lambda value: globals().update(selected_infinite_settings=value),
    is_infinite_playlist_active=lambda: playlist.get("infinite", False),
    refetch_pop_time_groups=lambda: get_pop_time_groups(refetch=True),
    clear_infinite_caches=lambda: globals().update(
        cached_pop_time_group=None,
        series_cooldowns_cache=None,
    ),
    get_bonus_settings=lambda: bonus_settings,
    get_bonus_defaults=lambda: BONUS_SETTINGS_DEFAULT,
    get_saved_bonus_settings=lambda: saved_bonus_settings,
    get_selected_bonus_settings=lambda: selected_bonus_settings,
    set_selected_bonus_settings=lambda value: globals().update(selected_bonus_settings=value),
)
open_shortcut_editor = shortcut_editor.open_shortcut_editor
cache_download.set_context(
    root=root,
    cache_metadata_file=CACHE_METADATA_FILE,
    themes_cache_folder=THEMES_CACHE_FOLDER,
    get_directory=lambda: directory,
    get_metadata=get_metadata,
    get_clean_filename=get_clean_filename,
    is_animethemes_file=is_animethemes_stream_file,
    get_fixed_lightning=lambda: (fixed_lightning_queue, fixed_lightning_round_playlist_data),
    show_playlist_fn=lambda update=True: show_playlist(update),
    update_extra_metadata_fn=update_extra_metadata,
    up_next_text_fn=up_next_text,
    play_filename_fn=play_filename,
    play_filename_streaming_fallback_fn=play_filename_streaming_fallback,
    get_list_loaded=lambda: list_loaded,
    get_search_queue=lambda: search_ops.search_queue,
)
cache_download.update_settings(
    themes_cache_size=themes_cache_size,
    auto_download_themes=auto_download_themes,
    app_version=APP_VERSION,
)
load_cache_metadata()
session_stats.set_context(
    get_metadata=get_metadata,
    get_song_string=get_song_string,
    get_display_title=get_display_title,
    get_youtube_display_title=get_youtube_display_title,
    get_file_metadata_by_name=get_file_metadata_by_name,
    update_playlist_name=update_playlist_name,
)
def _streaming_set_video_stopped(v):
    global video_stopped
    video_stopped = v
streaming.set_context(
    root=root,
    player=player,
    get_previous_media=lambda: previous_media,
    get_projected_player_time=lambda: projected_player_time,
    get_light_round_start_time=lambda: light_round_start_time,
    get_light_round_length=lambda: light_round_length,
    get_fixed_current_round=lambda: fixed_current_round,
    set_video_stopped=_streaming_set_video_stopped,
    get_light_mode=lambda: light_mode,
    get_display_title=get_display_title,
    is_game=is_game,
    get_base_title=get_base_title,
    get_format=get_format,
    get_selected_extra_metadata=lambda: selected_extra_metadata,
    hide_ost_cover_fn=_hide_ost_cover,
    update_extra_metadata_fn=update_extra_metadata,
)
streaming.update_settings(youtube_api_key=YOUTUBE_API_KEY)
censors.set_context(
    root=root,
    player=player,
    get_black_overlay=lambda: blind_screen.black_overlay,
    get_video_frame_active=lambda: blind_screen._video_frame_active,
    get_effective_video_rect=_get_effective_video_rect,
    osd_command=_osd_command,
    get_projected_player_time=lambda: projected_player_time,
    get_mismatch_visuals=lambda: mismatch_round.mismatch_visuals,
    get_currently_streaming=lambda: streaming.currently_streaming,
    get_light_round_started=lambda: light_round_started,
    play_next_fn=play_next,
    is_title_window_up=is_title_window_up,
    get_mpv_client_rect_logical=_get_mpv_client_rect_logical,
    get_file_metadata_by_name=get_file_metadata_by_name,
    atomic_json_write=_atomic_json_write,
    get_window_position_and_setup=get_window_position_and_setup,
    ToolTip_class=ToolTip,
    get_zoom_state=lambda: (
        (round(1 + 14 * (1 - filter_overlay._filter_vf_last_progress[0]), 4),
         filter_overlay._filter_zoom_offset[0], filter_overlay._filter_zoom_offset[1])
        if filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'zoom'
           and round(1 + 14 * (1 - filter_overlay._filter_vf_last_progress[0]), 4) > 1.005
        else None
    ),
    get_filter_state=lambda: (filter_overlay._filter_vf_variant, filter_overlay._filter_vf_last_progress[0]) if filter_overlay.filter_vf_active else None,
    get_censor_filter_thresholds=lambda: (
        lightning_mode_settings.get("reveal", {}).get("blur_censor_percent", 40),
        lightning_mode_settings.get("reveal", {}).get("pixelize_censor_percent", 40),
    ),
)
censors.update_settings(
    censor_json_file=CENSOR_JSON_FILE,
    censors_folder=CENSORS_FOLDER,
    censor_ass_osd_ids=_CENSOR_ASS_OSD_IDS,
    background_color=BACKGROUND_COLOR,
)
censors.set_youtube_context(
    save_youtube_censors_fn=youtube_control.save_youtube_censors,
    get_video_id_from_filename_fn=youtube_control.get_video_id_from_youtube_filename,
    is_youtube_file_fn=youtube_control.is_youtube_file,
)
bonus.set_context(
    root=root,
    player=player,
    get_light_mode=lambda: light_mode,
    get_light_round_started=lambda: light_round_started,
    get_fixed_current_round=lambda: fixed_current_round,
    get_coming_up_osd_box_h=lambda: coming_up_ui._coming_up_osd_box_h,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    toggle_coming_up_popup=toggle_coming_up_popup,
    toggle_mc_choices_overlay=toggle_mc_choices_overlay,
    send_scoreboard_command=scoreboard_control.send_command,
    evaluate_and_submit_fn=lambda: bonus_answers._evaluate_and_submit_bonus_answers(),
    push_web_toggles_fn=_push_web_toggles,
    refresh_popout_toggles_fn=_refresh_popout_toggles,
    register_mpv_tracked_window=_register_mpv_tracked_window,
    unregister_mpv_tracked_window=_unregister_mpv_tracked_window,
    get_display_title=get_display_title,
    get_base_title=get_base_title,
    get_tags=get_tags,
    get_all_tags=playlist_ops.get_all_tags,
    get_all_studios=playlist_ops.get_all_studios,
    series_list=series_list,
    series_set=series_set,
    series_overlap=series_overlap,
    series_primary=series_primary,
    get_series_popularity=get_series_popularity,
    is_game=is_game,
    aired_to_season_year=aired_to_season_year,
    get_lowest_parameter=playlist_ops.get_lowest_parameter,
    get_highest_parameter=playlist_ops.get_highest_parameter,
    load_pil_image_from_url=load_pil_image_from_url,
    get_ass_font=_get_ass_font,
    main_module=sys.modules[__name__],
)

def _set_fl_queue(v):
    global fixed_lightning_queue
    fixed_lightning_queue = v

def _set_fl_round_playlist_data(v):
    global fixed_lightning_round_playlist_data
    fixed_lightning_round_playlist_data = v

fixed_lightning.set_context(
    background_color=BACKGROUND_COLOR,
    highlight_color=HIGHLIGHT_COLOR,
    get_window_position_and_setup=get_window_position_and_setup,
    ToolTip=ToolTip,
    get_clean_filename=get_clean_filename,
    is_animethemes_stream_file=is_animethemes_stream_file,
    get_title=get_title,
    get_metadata=get_metadata,
    get_display_title=get_display_title,
    get_base_title=get_base_title,
    play_video_from_filename=play_video_from_filename,
    player=player,
    lightning_mode_settings_default=lightning_mode_settings_default,
    play_video=play_video,
    set_fl_queue=_set_fl_queue,
    set_fl_round_playlist_data=_set_fl_round_playlist_data,
    show_fixed_lightning_list=show_fixed_lightning_list,
    load_fixed_lightning_rounds=load_fixed_lightning_rounds,
    open_image_popup=open_image_popup,
    stream_url=stream_url,
    load_music_files=load_music_files,
)

try:
    import base64
    _icon_img = tk.PhotoImage(data=base64.b64decode(_APP_ICON_B64))
    root.iconphoto(True, _icon_img)
except Exception:
    pass
ROOT_FONT = ("Segoe UI", scl(9, "UI"))
MENU_FONT = ("Segoe UI", scl(10, "UI"))
playlist_marks.set_context(
    playlists_folder=PLAYLISTS_FOLDER,
    blank_playlist=BLANK_PLAYLIST,
    get_active_playlist=lambda: playlist,
    get_currently_playing=lambda: currently_playing,
    get_playlists_dict=get_playlists_dict,
    update_current_index=update_current_index,
    update_series_song_information=update_series_song_information,
    is_title_window_up=is_title_window_up,
    is_title_info_only=lambda: title_info_only,
    toggle_title_popup=toggle_title_popup,
    web_server=web_server,
    root=root,
    highlight_color=HIGHLIGHT_COLOR,
    menu_font=MENU_FONT,
    popup_menu=popup_menu,
    atomic_json_write=_atomic_json_write,
    convert_infinity_markers=convert_infinity_markers,
)
# root.resizable(False, False)

# Enable drag-and-drop on main window
def setup_main_window_drag_drop():
    try:
        # Enable drag-and-drop on main window
        enable_drag_and_drop(root, handle_dropped_files)
    except Exception as e:
        print(f"Could not enable drag-and-drop on main window: {e}")

# Setup drag-and-drop after window is fully initialized
root.after(500, setup_main_window_drag_drop)


def create_button(frame, label, func, add_space=False, enabled=False,
                  help_title="", help_text="", right_click=None):
    """Creates a button with optional tooltip on hover and a configurable right-click action."""
    bg = HIGHLIGHT_COLOR if enabled else "black"
    hover_bg = "gray35" if not enabled else "gray45"

    button = tk.Button(frame, text=label, command=func, bg=bg, fg="white", font=ROOT_FONT,
                       borderwidth=0, padx=scl(6, "UI"), pady=scl(3, "UI"), relief="flat")
    button.pack(side="left", padx=0)

    # Tooltip on hover (must be created BEFORE hover bindings so our add='+' runs after)
    tooltip_text = (f"{help_title}\n\n{help_text}" if help_title and help_text
                    else help_text or help_title)
    if tooltip_text:
        ToolTip(button, tooltip_text)

    # Hover highlight — bound with add='+' so ToolTip's bindings still fire too
    def _on_enter(e, b=button, hbg=hover_bg):
        b.config(bg=hbg)
    def _on_leave(e, b=button, obg=bg):
        b.config(bg=obg)
    button.bind("<Enter>", _on_enter, add="+")
    button.bind("<Leave>", _on_leave, add="+")

    # Right-click: (action, label_func) tuple → call action then flash label for 1 s
    if right_click is not None:
        if isinstance(right_click, tuple):
            _rc_action, _rc_label = right_click
            if not callable(_rc_action) or not _rc_label:
                return
            def _on_right_click(event, btn=button, act=_rc_action, lf=_rc_label):
                act()
                flash = lf() if callable(lf) else lf
                if not getattr(btn, "_flash_after_id", None):
                    # Not currently flashing — safe to capture real original
                    btn._flash_orig = btn.cget("text")
                else:
                    # Already flashing — cancel timer, keep the already-stored original
                    btn.after_cancel(btn._flash_after_id)
                btn.config(text=flash)
                btn._flash_after_id = btn.after(1000, lambda b=btn: (
                    b.config(text=b._flash_orig),
                    setattr(b, "_flash_after_id", None)
                ))
            button.bind("<Button-3>", _on_right_click)
        else:
            button.bind("<Button-3>", lambda event: right_click())

    # if add_space:
    #     blank_space(frame)

    return button


_menu_tooltip_win = [None]
_menu_tooltip_after = [None]

def attach_menu_tooltip(menu, tooltips):
    """Show a tooltip near the cursor after hovering 1 second over a menu item.
    tooltips: dict mapping integer item index -> tooltip string."""
    def on_select(event):
        if _menu_tooltip_after[0]:
            try:
                menu.after_cancel(_menu_tooltip_after[0])
            except Exception:
                pass
            _menu_tooltip_after[0] = None
        if _menu_tooltip_win[0]:
            try:
                _menu_tooltip_win[0].destroy()
            except Exception:
                pass
            _menu_tooltip_win[0] = None
        try:
            idx = menu.index("active")
        except Exception:
            return
        if idx is None or idx not in tooltips or not tooltips[idx]:
            return
        x = menu.winfo_pointerx() + 18
        y = menu.winfo_pointery() + 6
        text = tooltips[idx]
        def show_tooltip():
            _menu_tooltip_after[0] = None
            try:
                tw = tk.Toplevel()
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                tw.attributes("-topmost", True)
                tk.Label(tw, text=text, justify="left", bg="#ffffcc", fg="black",
                         relief="solid", bd=1, font=("Arial", 9), wraplength=320, padx=5, pady=3).pack()
                _menu_tooltip_win[0] = tw
            except Exception:
                pass
        _menu_tooltip_after[0] = menu.after(1000, show_tooltip)

    def on_hide(event):
        if _menu_tooltip_after[0]:
            try:
                menu.after_cancel(_menu_tooltip_after[0])
            except Exception:
                pass
            _menu_tooltip_after[0] = None
        if _menu_tooltip_win[0]:
            try:
                _menu_tooltip_win[0].destroy()
            except Exception:
                pass
            _menu_tooltip_win[0] = None

    menu.bind("<<MenuSelect>>", on_select)
    menu.bind("<Unmap>", on_hide)

# First row
first_row_frame = tk.Frame(root, bg=BACKGROUND_COLOR)
first_row_frame.pack(pady=(0, 0), fill="x", anchor="w")
first_row_border = tk.Frame(root, bg="gray30", height=1)
first_row_border.pack(fill="x")

def select_directory():
    global directory
    directory_path = filedialog.askdirectory()
    if directory_path:
        directory = directory_path
        scan_directory()

def scan_directory(queue=False):
    def worker():
        if not directory:
            return
        print("Scanning Directory...", end="", flush=True)
        # Mutate in place — keep identity for state.metadata.directory_files
        # and the module-level alias.
        directory_files.clear()
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith((".mp4", ".webm", ".mkv")):
                    directory_files[file] = os.path.join(root, file)
        invalidate_deduplicated_cache()
        save_config()
        get_cached_sfw_themes()
        if playlist.get("infinite", False):
            get_pop_time_groups(refetch=True)
            update_current_index()
        print(f"\rScanning Directory....COMPLETE ({len(directory_files)} files)")
    if queue:
        threading.Thread(target=worker, daemon=True).start()
    else:
        worker()

# =========================================
#           *MENU REGISTRY + BUILDER
# =========================================

def build_menu(parent_menu, items):
    """Build a tk.Menu from a declarative list of item dicts.

    Each item is either the string "---" (separator) or a dict with keys:
      id              : str  — stable identifier for shortcut binding, popout layout, flat lookup
      icon            : str  — emoji/symbol prepended to the label (optional; kept separate for button use)
      label           : str  — display text (required unless type=="radiogroup"); rendered as "{icon}  {label}"
      button_label    : str  — short text for popout buttons (optional; falls back to label)
      command         : callable — action on click
      tooltip         : str  — hover tooltip text (optional)
      (shortcut display is auto-resolved from DEFAULT_SHORTCUTS by item id — not stored per item)
      toggle    : callable -> bool — if present, item becomes a checkbutton;
                  return value drives active highlight
      condition : callable -> bool — if present and returns False, item is skipped
      submenu   : list  — if present, item becomes a cascade; value is a nested items list
      type      : "radiogroup" — special: generates one radiobutton per option
        options : list[str]   — radio labels
        variable: callable -> int — returns current selected index
        command : callable(int) — called with selected index
    """
    # Attach to the menu widget itself so vars live exactly as long as the menu does.
    # Without this, CPython can GC the BooleanVar/StringVar while Tcl still holds
    # a reference, causing TclErrors when the menu or root window is closed.
    _booleans = []
    parent_menu._keep_vars = _booleans

    def _make_menu():
        return tk.Menu(parent_menu, tearoff=0, bg="black", fg="white",
                       activebackground=HIGHLIGHT_COLOR, activeforeground="white",
                       font=MENU_FONT)

    def _add_items(menu, item_list):
        tooltip_map = {}
        visual_idx  = 0          # actual menu entry index (separators count)

        def _render_label(item):
            """Compose visible menu label + right-aligned accelerator text.
            Returns (label_text, accel_text_or_empty)."""
            raw_label = item["label"]() if callable(item.get("label")) else item.get("label", "")
            icon = item.get("icon", "")
            if callable(icon):
                icon = icon()
            item_id = item.get("id")
            key = get_shortcut(item_id) if item_id else None
            sd  = _shortcut_display_name(key) if key else None
            text = f"{icon}  {raw_label}" if icon else raw_label

            accel_parts = []
            if sd:
                accel_parts.append(sd)
            cycle_pos = item.get("cycle_pos")
            if cycle_pos:
                cyc_id, pos = cycle_pos
                cyc_key = get_shortcut(cyc_id)
                if cyc_key:
                    cyc_sd = _shortcut_display_name(cyc_key)
                    accel_parts.append(f"{cyc_sd}\u21bb{pos}")

            accel = "   ".join(accel_parts)
            return text, accel

        for item in item_list:
            # --- separator ---
            if item == "---" or (isinstance(item, dict) and item.get("type") == "separator"):
                if isinstance(item, dict) and "condition" in item and not item["condition"]():
                    continue
                menu.add_separator()
                visual_idx += 1
                continue

            # --- condition gate ---
            if "condition" in item and not item["condition"]():
                continue

            # --- radiogroup ---
            if item.get("type") == "radiogroup":
                cur = item["variable"]()
                rv  = tk.StringVar(value=item["options"][cur])
                _booleans.append(rv)
                start_idx = visual_idx
                for i, opt in enumerate(item["options"]):
                    menu.add_radiobutton(
                        label=opt, variable=rv, value=opt,
                        command=(lambda idx=i, _item=item: _item["command"](idx)) if "command" in item else None,
                        selectcolor=HIGHLIGHT_COLOR,
                    )
                    if "tooltip" in item:
                        tooltip_map[visual_idx] = item["tooltip"]
                    visual_idx += 1
                menu.entryconfig(start_idx + cur, background=HIGHLIGHT_COLOR, foreground="white")
                continue

            rendered, accel = _render_label(item)

            # --- cascade (submenu) ---
            if "submenu" in item:
                sub = _make_menu()
                _add_items(sub, item["submenu"])
                menu.add_cascade(label=rendered, menu=sub, accelerator=accel)
                if "toggle" in item and item["toggle"]():
                    menu.entryconfig(visual_idx, background=HIGHLIGHT_COLOR, foreground="white")
                if "tooltip" in item:
                    tooltip_map[visual_idx] = item["tooltip"]
                visual_idx += 1
                continue

            # --- toggle (checkbutton) ---
            if "toggle" in item:
                state = item["toggle"]()
                bv = tk.BooleanVar(value=state)
                _booleans.append(bv)
                menu.add_checkbutton(
                    label=rendered,
                    accelerator=accel,
                    variable=bv,
                    command=item["command"],
                    selectcolor=HIGHLIGHT_COLOR,
                )
                if state:
                    menu.entryconfig(visual_idx, background=HIGHLIGHT_COLOR, foreground="white")
                if "tooltip" in item:
                    tooltip_map[visual_idx] = item["tooltip"]
                visual_idx += 1
                continue

            # --- plain command ---
            menu.add_command(label=rendered, accelerator=accel, command=item["command"])
            if "tooltip" in item:
                tooltip_map[visual_idx] = item["tooltip"]
            visual_idx += 1

        if tooltip_map:
            attach_menu_tooltip(menu, tooltip_map)

    _add_items(parent_menu, items)


# ---------------------------------------------------------------------------
# SHORTCUT INFRASTRUCTURE
# ---------------------------------------------------------------------------

# Default shortcuts: {id → key_char_or_name}.
# Single-char shortcuts are the literal character pynput returns via key.char.
# "BackSpace" is the only special-key name currently used.
DEFAULT_SHORTCUTS = {
    # ── Playlist / Queue ──────────────────────────────────────────────────
    "view_playlist":        "p",
    "lightning_variety":    "v",
    "show_youtube":         "y",
    "show_fixed_lightning": "f",
    # ── Popups ────────────────────────────────────────────────────────────
    "info_popup":           "i",
    "title_popup":          "o",
    "end_session":          "e",
    # ── Toggle / Overlays ─────────────────────────────────────────────────
    "blind":                "BackSpace",
    "peek":                 "=",
    "narrow_peek":          "[",
    "widen_peek":           "]",
    "mute":                 "m",
    "censors":              "c",
    "enable_shortcuts":     "`",
    "view_shortcuts":       None,
    "close_list":           "k",
    # ── Theme ─────────────────────────────────────────────────────────────
    "tag":                  "t",
    "favorite":             "*",
    # ── Bonus questions (direct) ──────────────────────────────────────────
    "bonus_multiple":       "u",
    "bonus_tags":           "n",
    "bonus_chars":          "j",
    # ── Cycling (hidden) ──────────────────────────────────────────────────
    "cycle_blind_peek":     "b",
    "cycle_light_mode":     "l",
    "cycle_guess_stats":    "g",
    "cycle_guess_other":    "h",
    # ── Navigation (hidden) ───────────────────────────────────────────────
    "dock_player":          "d",
    "search_themes":        "s",
    "reroll_next":          "r",
    # ── Scoreboard (hidden) ───────────────────────────────────────────────
    "scoreboard_align":     "a",
    "scoreboard_extend":    "x",
    "scoreboard_shrink":    "z",
    "scoreboard_grow":      "w",
    "scoreboard_toggle":    "q",
}

# Human-readable display overrides for special key names
_SHORTCUT_DISPLAY = {
    "BackSpace": "Bksp",
    "space":     "Space",
    "esc":       "Esc",
    "right":     "Right",
    "left":      "Left",
    "up":        "Up",
    "down":      "Down",
    "tab":       "Tab",
    "enter":     "Enter",
}

def _shortcut_display_name(key_str):
    """Return a human-readable label for a key string (e.g. 'BackSpace' → 'Bksp')."""
    return _SHORTCUT_DISPLAY.get(key_str, key_str) if key_str else None

# Hardcoded special-key bindings that are handled directly in on_release/on_press via keyboard.Key.*
# These cannot be remapped through the shortcut editor — shown as locked read-only rows.
# Format: {id: (key_string, label, note_or_None)}
FIXED_SHORTCUTS = {
    "play_pause":    ("space", "Play / Pause",         None),
    "stop":          ("esc",   "Stop",                 None),
    "next":          ("right", "Next Track",           None),
    "previous":      ("left",  "Previous Track",       None),
    "fullscreen":    ("tab",   "Toggle Fullscreen",    None),
    "list_enter":    ("enter", "Select from List",     None),
    "list_move_up":  ("up",    "Navigate List Up",     None),
    "list_move_down":("down",  "Navigate List Down",   None),
}

# User overrides loaded from config: {id → key_char_or_name}
# Preserve any value already populated by load_config() at startup.
shortcuts_config = globals().get("shortcuts_config") or {}

# Currently active bindings: {id → key_string} — used by shortcuts editor for display
bound_shortcuts = {}

def get_shortcut(item_id, default=None):
    """Return the active shortcut key for item_id.

    Resolves: shortcuts_config override → DEFAULT_SHORTCUTS → default argument.
    """
    if not item_id:
        return default
    return shortcuts_config.get(item_id, DEFAULT_SHORTCUTS.get(item_id, default))


def get_flat_registry():
    """Return a flat {id: item} dict across all menus and submenus (items with an id only).

    Useful for shortcut binding, popout layout lookup, and the shortcuts editor.
    Includes hidden and scoreboard items — everything with an id.
    """
    flat = {}

    def _walk(item_list):
        for item in item_list:
            if item == "---":
                continue
            if not isinstance(item, dict):
                continue
            if "id" in item:
                flat[item["id"]] = item
            if "submenu" in item:
                _walk(item["submenu"])

    registry = _get_menu_registry()
    for section_items in registry.values():
        _walk(section_items)
    return flat

def bind_shortcuts():
    """Bind all registry shortcuts to root, respecting user overrides.

    Safe to call multiple times — unbinds old key before binding new one.
    Only binds items that have an 'id' with a shortcut in DEFAULT_SHORTCUTS or shortcuts_config.
    Does not bind items whose shortcut has been cleared (set to "" in shortcuts_config).
    """
    flat = get_flat_registry()
    for item_id, item in flat.items():
        key = get_shortcut(item_id)

        # Unbind previous binding for this id if key changed
        old_key = bound_shortcuts.get(item_id)
        if old_key and old_key != key:
            try:
                root.unbind(f"<{old_key}>")
            except Exception:
                pass
            bound_shortcuts.pop(item_id, None)

        if not key:
            continue

        cmd = item.get("command")
        if not cmd:
            continue

        try:
            root.bind(f"<{key}>", lambda e, c=cmd: c())
            bound_shortcuts[item_id] = key
        except Exception:
            pass


# Runtime dispatch table: {key_char_or_name: command}.
# Built from DEFAULT_SHORTCUTS + registry commands. Queried directly by on_release.
_shortcut_dispatch = {}

def rebuild_shortcut_dispatch():
    """Build the in-memory key → command dispatch table.

    Call once at startup (after all functions are defined) and again any time
    shortcuts_config is modified so on_release always uses the current bindings.
    """
    global _shortcut_dispatch
    flat = get_flat_registry()
    dispatch = {}
    for item_id, item in flat.items():
        key = get_shortcut(item_id)   # shortcuts_config override → DEFAULT_SHORTCUTS → None
        cmd = item.get("command")
        if key and cmd:
            dispatch[key] = cmd
    _shortcut_dispatch = dispatch


# ---------------------------------------------------------------------------
# REGISTRY HELPERS — computed predicates used as `condition` / `command` lambdas
#                   in the theme menu submenus below.
# ---------------------------------------------------------------------------

def _cp_is_local_file():
    """Return True if the currently playing file exists in the local directory."""
    f = currently_playing.get("filename", "")
    return bool(f and f in directory_files and os.path.exists(directory_files.get(f, "")))

def _cp_is_stream():
    """Return True if the currently playing file is an AnimeThemes stream (not locally stored)."""
    f = currently_playing.get("filename", "")
    return bool(f and is_animethemes_stream_file(f) and not _cp_is_local_file())

def download_current_theme():
    """Download or move the currently playing theme to the local directory."""
    f = currently_playing.get("filename", "")
    if not f:
        return
    if get_cached_file_path(f) is not None:
        move_cached_file_to_directory(f, None)
    else:
        download_animethemes_file(f, None)


# ---------------------------------------------------------------------------
# MENU_REGISTRY — all item definitions (label / command / tooltip / toggle /
#                 condition / submenu / type).  Separators are the string "---".
# Lambdas referencing globals are fine here because this dict is evaluated
# inside create_first_row_buttons(), which runs after all functions are defined.
# ---------------------------------------------------------------------------
def _get_menu_registry():
    return {

    # ── DIRECTORY ────────────────────────────────────────────────────────────
    "directory": [
        {"id": "dir_by_artist", "icon": "🎤", "label": "Themes by Artist",
         "tooltip": "List all themes grouped by artist.",
         "submenu": [
             {"id": "dir_by_artist_alpha", "label": "Alphabetical",  "command": lambda: artist_stats('alpha'), "tooltip": "Sort artists alphabetically."},
             {"id": "dir_by_artist_count", "label": "Theme Total",   "command": lambda: artist_stats('count'), "tooltip": "Sort artists by number of themes (most first)."},
         ]},
        {"id": "dir_by_season", "icon": "🌸", "label": "Themes by Season",
         "command": season_stats, "tooltip": "List all themes grouped by season."},
        {"id": "dir_by_series", "icon": "📚", "label": "Themes by Series",
         "tooltip": "List all themes grouped by series.",
         "submenu": [
             {"id": "dir_by_series_alpha",      "label": "Alphabetical",  "command": lambda: series_stats('alpha'),      "tooltip": "Sort series alphabetically."},
             {"id": "dir_by_series_popularity", "label": "Popularity",    "command": lambda: series_stats('popularity'), "tooltip": "Sort series by MAL popularity rank (most popular first)."},
             {"id": "dir_by_series_count",      "label": "Theme Total",   "command": lambda: series_stats('count'),      "tooltip": "Sort series by number of themes (most first)."},
         ]},
        {"id": "dir_by_slug",   "icon": "🔑", "label": "Themes by Slug",
         "tooltip": "List all themes grouped by slug (OP1, ED2, etc.).",
         "submenu": [
             {"id": "dir_by_slug_alpha", "label": "Alphabetical",  "command": lambda: slug_stats('alpha'), "tooltip": "Sort slugs alphabetically."},
             {"id": "dir_by_slug_count", "label": "Theme Total",   "command": lambda: slug_stats('count'), "tooltip": "Sort slugs by number of themes (most first)."},
         ]},
        {"id": "dir_by_studio", "icon": "🏢", "label": "Themes by Studio",
         "tooltip": "List all themes grouped by studio.",
         "submenu": [
             {"id": "dir_by_studio_alpha", "label": "Alphabetical",  "command": lambda: studio_stats('alpha'), "tooltip": "Sort studios alphabetically."},
             {"id": "dir_by_studio_count", "label": "Theme Total",   "command": lambda: studio_stats('count'), "tooltip": "Sort studios by number of themes (most first)."},
         ]},
        {"id": "dir_by_tag",    "icon": "🏷",  "label": "Themes by Tag (MAL)",
         "tooltip": "List all themes grouped by MAL tag.",
         "submenu": [
             {"id": "dir_by_tag_alpha", "label": "Alphabetical",  "command": lambda: tag_stats('alpha'), "tooltip": "Sort MAL tags alphabetically."},
             {"id": "dir_by_tag_count", "label": "Theme Total",   "command": lambda: tag_stats('count'), "tooltip": "Sort MAL tags by number of themes (most first)."},
         ]},
        {"id": "dir_by_anilist_tag", "icon": "🔖", "label": "Themes by Tag (AniList)",
         "tooltip": "List all themes grouped by AniList tag.",
         "submenu": [
             {"id": "dir_by_anilist_tag_alpha", "label": "Alphabetical",  "command": lambda: anilist_tag_stats('alpha'), "tooltip": "Sort AniList tags alphabetically."},
             {"id": "dir_by_anilist_tag_count", "label": "Theme Total",   "command": lambda: anilist_tag_stats('count'), "tooltip": "Sort AniList tags by number of themes (most first)."},
         ]},
        {"id": "dir_by_type",   "icon": "📺", "label": "Themes by Type",
         "command": type_stats,   "tooltip": "List all themes grouped by format/type."},
        {"id": "dir_by_year",   "icon": "📅", "label": "Themes by Year",
         "command": year_stats,   "tooltip": "List all themes grouped by year."},
    ],

    # ── FILE ────────────────────────────────────────────────────────────────
    "file": [
        {"id": "choose_directory", "icon": "📁", "label": "Choose Theme Directory",
         "button_label": "DIRECTORY", "command": select_directory,
         "tooltip": ("Choose the folder where your anime themes are stored.\n\n"
                     "The app expects files from AnimeThemes (torrent or downloaded).\n"
                     "It searches subfolders, so pick the top-level folder.\n\n"
                     "Custom files must be labeled as:\n"
                     "AnimeName-OP1-[MAL]49618[ART]Minami[SNG]Rude Lose Dance.webm")},
        "---",
        {"label": "Import", "icon": "►", "tooltip": "Import metadata or censors from GitHub.",
         "submenu": [
             {"id": "import_data", "label": "Import Data (from GitHub)",
              "button_label": "IMPORT DATA", "command": import_data_from_source,
              "tooltip": "Imports metadata from a remote GitHub.\nDownloads a zip package and merges all metadata with your existing data."},
             {"id": "import_censors", "label": "Import Censors (Ramun's)",
              "button_label": "IMPORT CENSORS", "command": import_censors,
              "tooltip": "Downloads and imports Ramun's censors from GitHub.\nSaved as 'ramuns_censors.json' in your files folder."},
         ]},
        {"id": "export_data", "icon": "📤", "label": "Export Data",
         "button_label": "EXPORT", "command": export_metadata_package,
         "tooltip": "Exports all metadata files into a zip package for backup or sharing."},
        "---",
        {"id": "fetch_all_metadata", "icon": "❓", "label": "Fetch All Missing Metadata",
         "button_label": "FETCH ALL", "command": fetch_all_metadata,
         "tooltip": "Check all files in the directory for missing metadata and fetch any that are absent."},
        {"label": "Refresh Metadata", "icon": "⭮",
         "tooltip": "Refresh metadata from external sources.",
         "submenu": [
             {"id": "refresh_jikan", "icon": "⭮", "label": "Refresh Jikan (MAL)",
              "button_label": "REFRESH JIKAN", "command": refresh_all_metadata,
              "tooltip": "Refresh Jikan (MAL) metadata — score and members — for files in your directory."},
             {"id": "refresh_anilist", "icon": "A", "label": "Refresh AniList",
              "button_label": "REFRESH ANILIST", "command": refresh_all_anilist_metadata,
              "tooltip": "Refresh AniList metadata — scores, rankings, tags, characters — for files in your directory."},
             {"id": "refresh_igdb", "icon": "🎮", "label": "Refresh IGDB",
              "button_label": "REFRESH IGDB", "command": refresh_all_igdb_metadata,
              "tooltip": "Refresh IGDB metadata for game files in your directory."},
         ]},
        "---",
        {"icon": "🌐",
            "label": lambda: "Stop Web Server" if web_server.is_running() else "Start Web Server",
            "command": toggle_web_server,
            "toggle": lambda: web_server.is_running(),
            "condition": lambda: NGROK_AVAILABLE or CLOUDFLARED_AVAILABLE,
            "tooltip": "Start or stop the web answer server that lets players submit bonus answers from their browser."
        },
        {"id": "open_scoreboard",  "icon": "▶", "label": "Open Scoreboard",
        "command": open_scoreboard,
        "condition": lambda: scoreboard_control.AVAILABLE and not is_scoreboard_running(),
        "tooltip": "Launch the scoreboard."},
        {"id": "close_scoreboard", "icon": "✕", "label": "Close Scoreboard",
        "command": lambda: send_scoreboard_command("quit"),
        "condition": lambda: is_scoreboard_running(),
        "tooltip": "Send a quit command to the running scoreboard."},
        {"id": "download_scoreboard", "icon": "⬇", "label": "Download Scoreboard",
        "command": download_scoreboard,
        "condition": lambda: not scoreboard_control.AVAILABLE,
        "tooltip": "Download the Universal Scoreboard — a companion overlay for tracking scores during sessions."},
        {"id": "update_scoreboard", "icon": "🔄", "label": "Update Scoreboard",
        "command": lambda: scoreboard_control.send_command("check_update"),
        "condition": lambda: is_scoreboard_running(),
        "tooltip": "Ask the running scoreboard to check for and install a newer version."},
        {"label": "Scoreboard Actions", "icon": "⚙️",
        "condition": lambda: is_scoreboard_running(),
        "tooltip": "Control the scoreboard window.",
        "submenu": [
            {"id": "scoreboard_toggle",  "icon": "👁",  "label": "Toggle Visibility",
            "command": lambda: send_scoreboard_command("toggle"),
            "tooltip": "Show or hide the scoreboard."},
            {"id": "scoreboard_align",   "icon": "⇄",  "label": "Flip Alignment",
            "command": lambda: send_scoreboard_command("align"),
            "tooltip": "Toggle scoreboard between left and right alignment."},
            "---",
            {"id": "scoreboard_extend",  "icon": "▤",   "label": "Toggle Extended Stats",
            "command": lambda: send_scoreboard_command("extend"),
            "tooltip": "Toggle the extended statistics view."},
            "---",
            {"id": "scoreboard_grow",    "icon": "△",  "label": "Grow",
            "command": lambda: send_scoreboard_command("grow"),
            "tooltip": "Increase the scoreboard size."},
            {"id": "scoreboard_shrink",  "icon": "▽",  "label": "Shrink",
            "command": lambda: send_scoreboard_command("shrink"),
            "tooltip": "Decrease the scoreboard size."},
        ]},
        "---",
        {"id": "reset_session", "icon": "🗑",
         "label": lambda: f"Reset Session History [{get_themes_played_count()}]",
         "button_label": "RESET SESSION", "command": reset_session_history,
         "tooltip": "Clear the current session history.\nStarts a fresh session from this point."},
        "---",
        {"id": "settings", "icon": "⚙️", "label": "Configuration Settings",
         "button_label": "SETTINGS", "command": show_settings_popup,
         "tooltip": "Open settings to configure volume, colors, API keys, scaling, and more."},
        "---",
        {"id": "help", "icon": "❓", "label": "Help & Tutorial",
         "button_label": "HELP",
         "command": show_tutorial_popup,
         "tooltip": "Open the Help & Tutorial window with a step-by-step guide to using the app."},
        {"id": "github", "icon": "🔗", "label": "View on GitHub",
         "button_label": "GITHUB",
         "command": lambda: webbrowser.open("https://github.com/ualkotob/guess-the-anime-playlist-tool"),
         "tooltip": "Open the GitHub repository for this app in your browser."},
        "---",
        {"id": "exit", "icon": "✕", "label": "Exit",
         "button_label": "EXIT", "command": lambda: on_app_close(),
         "tooltip": "Close the application."},
    ],

    # ── PLAYLIST ────────────────────────────────────────────────────────────
    "playlist": [
        {"label": "Create Playlist", "icon": "➕",
         "submenu": [
             {"id": "create_infinite", "icon": "∞", "label": "Infinite",
              "button_label": "INFINITE",
              "tooltip": ("Creates a playlist that automatically adds new tracks as you reach the end"
                          " balancing popularity and season groups. Can be configured heavily.\n\n"
                          "This is the recommended playlist to use."),
              "submenu": [
                  {"id": "create_infinite_local", "label": "Local Files Only",
                   "command": lambda: create_infinite_playlist(include_non_local=False),
                   "tooltip": "Create an infinite playlist using only files present in your local directory."},
                  {"id": "create_infinite_stream", "icon": stream_icon, "label": "Include Streaming Themes",
                   "command": lambda: create_infinite_playlist(include_non_local=True),
                   "tooltip": "Include non-local themes that will be streamed from AnimeThemes."},
              ]},
             "---",
             {"id": "create_standard", "label": "Standard (all files)",
              "button_label": "CREATE",
              "tooltip": ("Creates a playlist using all videos found in the directory.\n\n"
                          "Not recommended unless you have a curated local list of themes."),
              "submenu": [
                  {"id": "create_standard_local", "label": "Local Files Only",
                   "command": lambda: generate_playlist_button(include_non_local=False),
                   "tooltip": "Create a playlist using only files present in your local directory."},
                  {"id": "create_standard_stream", "icon": stream_icon, "label": "Include Streaming Themes",
                   "command": lambda: generate_playlist_button(include_non_local=True),
                   "tooltip": "Include non-local themes from metadata that will be streamed from AnimeThemes."},
              ]},
             {"id": "create_anilist", "label": "From AniList ID",
              "button_label": "ANILIST",
              "tooltip": "Creates a playlist from an AniList user's anime list.",
              "submenu": [
                  {"id": "create_anilist_local", "label": "Local Files Only",
                   "command": lambda: generate_anilist_playlist(include_non_local=False),
                   "tooltip": "Match only themes that are stored locally in your directory."},
                  {"id": "create_anilist_stream", "icon": stream_icon, "label": "Include Streaming Themes",
                   "command": lambda: generate_anilist_playlist(include_non_local=True),
                   "tooltip": "Include non-local themes from metadata that will be streamed from AnimeThemes."},
              ]},
             {"id": "create_animethemes", "label": "From AnimeThemes Playlist",
              "button_label": "ANIMETHEMES",
              "tooltip": ("Creates a playlist from an AnimeThemes playlist hashid.\n"
                          "URL format: https://animethemes.moe/playlist/hashid"),
              "submenu": [
                  {"id": "create_animethemes_local", "label": "Local Files Only",
                   "command": lambda: generate_animethemes_playlist(include_non_local=False),
                   "tooltip": "Match only themes that are stored locally in your directory."},
                  {"id": "create_animethemes_stream", "icon": stream_icon, "label": "Include Streaming Themes",
                   "command": lambda: generate_animethemes_playlist(include_non_local=True),
                   "tooltip": "Include non-local themes from metadata that will be streamed from AnimeThemes."},
              ]},
             {"id": "create_session_log", "label": "From Session Log",
              "button_label": "SESSION LOG",
              "tooltip": ("Creates a playlist by matching themes from a saved session log file.\n\n"
                          "Session .txt files are stored in the sessions/ folder.\n"
                          "Themes are matched against your local files/metadata using title and slug."),
              "command": generate_session_log_playlist},
             "---",
             {"id": "empty_playlist", "label": "Empty Playlist",
              "button_label": "EMPTY", "command": empty_playlist,
              "tooltip": "Creates an empty playlist."},
         ]},
        "---",
        {"id": "view_playlist", "icon": "👁", "label": "View Playlist",
         "button_label": "PLAYLIST", "shortcut": True, "command": show_playlist,
         "tooltip": ("List all themes in the playlist. Scrolls to the current index.\n"
                     "Select a theme to jump to it immediately.")},
        {"id": "go_to_index", "icon": "→", "label": "Go to Index",
         "command": go_to_index,
         "condition": lambda: not playlist.get("infinite", False),
         "tooltip": "Jump to a specific track number in the playlist."},
        {"id": "remove_theme", "icon": "➖", "label": "Remove Theme",
         "button_label": "REMOVE", "command": remove,
         "tooltip": ("Remove a theme from the playlist.\n\n"
                     "There is a confirmation dialogue after selecting.")},
        "---",
        {"id": "save_playlist", "label": "Save Playlist",
         "button_label": "SAVE", "command": save,
         "tooltip": ("Save the current playlist to its existing file in the playlists/ folder.\n\n"
                     "The current index is also saved so you can resume where you left off.")},
        {"id": "save_playlist_as", "label": "Save Playlist As",
         "button_label": "SAVE AS", "command": save_as,
         "tooltip": ("Save the current playlist under a new name.\n\n"
                     "You will be prompted for a name. Entering an existing name will overwrite it.\n"
                     "The current index is also saved so you can resume where you left off.")},
        {"id": "load_playlist", "label": "Load Playlist",
         "button_label": "LOAD", "command": load,
         "tooltip": ("Load a saved playlist.\n\n"
                     "Won't interrupt the currently playing theme.")},
        {"id": "load_system_playlist", "icon": "📋", "label": "Load System Playlist",
         "button_label": "SYSTEM LIST", "command": load_system_playlist,
         "tooltip": "Load a system playlist: Tagged, Favorite, Blind, Reveal, Mute Reveal, New, or Missing Artists."},
        {"id": "merge_playlist", "icon": "➕", "label": "Merge Playlist",
         "button_label": "MERGE", "command": merge_playlist,
         "condition": lambda: not playlist.get("infinite", False),
         "tooltip": ("Merge another playlist into the current one.\n"
                     "Only non-infinite playlists are listed. Duplicates are skipped.")},
        {"id": "delete_playlist", "icon": "❌", "label": "Delete a Playlist",
         "button_label": "DELETE", "command": delete,
         "tooltip": "Select a playlist from the list to delete. You will be asked to confirm."},
        "---",
        {"label": "Filter Playlist", "icon": "",
         "submenu": [
             {"id": "filter_editor", "label": "Open Filter Editor",
              "button_label": "FILTER", "command": filters,
              "tooltip": ("Open a window to create, apply, and save playlist filters.")},
             {"id": "load_filter", "icon": "💾", "label": "Load Saved Filter",
              "button_label": "LOAD FILTER", "command": load_filters,
              "tooltip": "Apply a previously saved filter to the current playlist."},
             {"id": "delete_filter", "icon": "❌", "label": "Delete Saved Filter",
              "button_label": "DEL FILTER", "command": delete_filters,
              "tooltip": "Delete a saved filter. You will be asked to confirm."},
         ]},
        "---",
        {"label": "Sort Playlist", "icon": "🔀",
         "condition": lambda: not playlist.get("infinite", False),
         "tooltip": "Sort the playlist by field and direction.",
         "submenu": [
             {"label": "Filename",
              "tooltip": "Sort by the theme's filename.",
              "submenu": [
                  {"id": "sort_filename_asc",  "label": "Ascending ↑",  "command": lambda: sort_playlist(0),
                   "tooltip": "Sort filenames A → Z."},
                  {"id": "sort_filename_desc", "label": "Descending ↓", "command": lambda: sort_playlist(1),
                   "tooltip": "Sort filenames Z → A."},
              ]},
             {"label": "Title",
              "tooltip": "Sort by the anime's Japanese title.",
              "submenu": [
                  {"id": "sort_title_asc",  "label": "Ascending ↑",  "command": lambda: sort_playlist(2),
                   "tooltip": "Sort titles A → Z."},
                  {"id": "sort_title_desc", "label": "Descending ↓", "command": lambda: sort_playlist(3),
                   "tooltip": "Sort titles Z → A."},
              ]},
             {"label": "English Title",
              "tooltip": "Sort by the anime's English title.",
              "submenu": [
                  {"id": "sort_eng_title_asc",  "label": "Ascending ↑",  "command": lambda: sort_playlist(4),
                   "tooltip": "Sort English titles A → Z."},
                  {"id": "sort_eng_title_desc", "label": "Descending ↓", "command": lambda: sort_playlist(5),
                   "tooltip": "Sort English titles Z → A."},
              ]},
             {"label": "Score",
              "tooltip": "Sort by MAL score.",
              "submenu": [
                  {"id": "sort_score_asc",  "label": "Ascending ↑",  "command": lambda: sort_playlist(6),
                   "tooltip": "Sort lowest score first."},
                  {"id": "sort_score_desc", "label": "Descending ↓", "command": lambda: sort_playlist(7),
                   "tooltip": "Sort highest score first."},
              ]},
             {"label": "Members",
              "tooltip": "Sort by MAL member count (popularity).",
              "submenu": [
                  {"id": "sort_members_asc",  "label": "Ascending ↑",  "command": lambda: sort_playlist(8),
                   "tooltip": "Sort least popular first."},
                  {"id": "sort_members_desc", "label": "Descending ↓", "command": lambda: sort_playlist(9),
                   "tooltip": "Sort most popular first."},
              ]},
             {"label": "Season",
              "tooltip": "Sort by the anime's airing season and year.",
              "submenu": [
                  {"id": "sort_season_asc",  "label": "Ascending ↑",  "command": lambda: sort_playlist(10),
                   "tooltip": "Sort oldest season first."},
                  {"id": "sort_season_desc", "label": "Descending ↓", "command": lambda: sort_playlist(11),
                   "tooltip": "Sort newest season first."},
              ]},
         ]},
        {"label": "Shuffle Playlist", "icon": "🔀",
         "condition": lambda: not playlist.get("infinite", False),
         "submenu": [
             {"id": "shuffle_playlist", "label": "Random",
              "button_label": "SHUFFLE", "command": randomize_playlist,
              "tooltip": "Completely random shuffle of the current playlist."},
             {"id": "weighted_shuffle", "icon": "⚖️", "label": "Weighted",
              "button_label": "W.SHUFFLE", "command": weighted_randomize,
              "tooltip": ("Weighted shuffle balancing popular/niche and old/new anime, "
                          "while avoiding the same series appearing too close together.\n"
                          "Ideal for trivia sessions.")},
         ]},
        {"type": "radiogroup",
         "condition": lambda: playlist.get("infinite", False),
         "options": difficulty_options,
         "variable": lambda: playlist.get("difficulty", 2),
         "command": _set_difficulty_from_menu},
        {"id": "infinite_settings", "icon": "🛠", "label": "Infinite Settings",
         "button_label": "INF. SETTINGS", "command": open_infinite_settings_editor,
         "condition": lambda: playlist.get("infinite", False),
         "tooltip": "Open the Infinite Settings editor to configure infinite playlist behavior."},
        "---",
        {"label": "Bulk Mark Playlist", "icon": "►",
         "tooltip": "Apply or remove a mark for every theme in the current playlist.",
         "submenu": [
             {"id": "bulk_tag",           "icon": "❌", "label": "Bulk Tag Playlist",
              "button_label": "BULK TAG",      "command": bulk_tag_playlist,
              "tooltip": "Bulk tag or untag every theme in the current playlist. Requires confirmation."},
             {"id": "bulk_favorite",      "icon": "❤",  "label": "Bulk Favorite Playlist",
              "button_label": "BULK FAV",      "command": bulk_favorite_playlist,
              "tooltip": "Bulk favorite or unfavorite every theme in the current playlist. Requires confirmation."},
             {"id": "bulk_blind_mark",    "icon": "👁", "label": "Bulk Blind Mark Playlist",
              "button_label": "BULK BLIND",    "command": bulk_blind_mark_playlist,
              "tooltip": "Bulk blind-mark or unmark every theme. Mutually exclusive with Reveal/Mute Reveal. Requires confirmation."},
             {"id": "bulk_peek_mark",     "icon": "👀", "label": "Bulk Reveal Mark Playlist",
              "button_label": "BULK RV",        "command": bulk_peek_mark_playlist,
              "tooltip": "Bulk reveal-mark or unmark every theme in the playlist. Mutually exclusive with Blind/Mute Reveal. Requires confirmation."},
             {"id": "bulk_mute_peek_mark","icon": "🔇", "label": "Bulk Mute Reveal Mark Playlist",
              "button_label": "BULK MUTE RV",   "command": bulk_mute_peek_mark_playlist,
              "tooltip": "Bulk mute-reveal-mark or unmark every theme in the playlist. Mutually exclusive with Blind/Reveal. Requires confirmation."},
         ]},
    ],

    # ── QUEUE ────────────────────────────────────────────────────────────────
    "queue": [
        {"id": "queue_blind_round", "icon": "👁", "label": "Blind Round",
         "button_label": "BLIND NEXT", "shortcut": True, "command": toggle_blind_round,
         "toggle":  lambda: blind_screen.blind_round_toggle,
         "cycle_pos": ("cycle_blind_peek", 1),
         "tooltip": "Queue the next theme as a Blind Round — audio only, screen covered."},
        {"id": "queue_peek_round", "icon": "👀", "label": "Reveal Round",
         "button_label": "REVEAL NEXT", "shortcut": True, "command": toggle_peek_round,
         "toggle":  lambda: peek_dispatch.peek_round_toggle,
         "cycle_pos": ("cycle_blind_peek", 2),
         "tooltip": "Queue the next theme as a Reveal Round — visuals are partially obscured (blur, zoom, slice, etc.).",
         "submenu": [
             {"label": "Turn Off", "icon": "✖", "command": toggle_peek_round,
              "condition": lambda: peek_dispatch.peek_round_toggle},
             {"icon": "🔀", "label": "Random", "command": lambda: _queue_peek_random(mute=False),
              "toggle": lambda: peek_dispatch.peek_round_toggle and peek_dispatch._queued_peek_variant[0] is None},
             "---",
             *[{"icon": icon, "label": label,
                "command": lambda v=v: _queue_peek_variant(v, mute=False),
                "toggle": lambda v=v: peek_dispatch.peek_round_toggle and peek_dispatch._queued_peek_variant[0] == v,
                "tooltip": tooltip}
               for v, (icon, label, tooltip) in peek_dispatch._PEEK_VARIANT_LABELS.items()],
         ]},
        {"id": "queue_mute_peek_round", "icon": "🔇", "label": "Mute Reveal Round",
         "button_label": "MUTE RV NEXT", "shortcut": True, "command": toggle_mute_peek_round,
         "toggle":  lambda: peek_dispatch.mute_peek_round_toggle,
         "cycle_pos": ("cycle_blind_peek", 3),
         "tooltip": "Queue the next theme as a Mute Reveal Round — visuals partially obscured, audio muted.",
         "submenu": [
             {"label": "Turn Off", "icon": "✖", "command": toggle_mute_peek_round,
              "condition": lambda: peek_dispatch.mute_peek_round_toggle},
             {"icon": "🔀", "label": "Random", "command": lambda: _queue_peek_random(mute=True),
              "toggle": lambda: peek_dispatch.mute_peek_round_toggle and peek_dispatch._queued_peek_variant[0] is None},
             "---",
             *[{"icon": icon, "label": label,
                "command": lambda v=v: _queue_peek_variant(v, mute=True),
                "toggle": lambda v=v: peek_dispatch.mute_peek_round_toggle and peek_dispatch._queued_peek_variant[0] == v,
                "tooltip": tooltip}
               for v, (icon, label, tooltip) in peek_dispatch._PEEK_VARIANT_LABELS.items()],
         ]},
        "---",
        {"icon": "⚡", "label": "Lightning Rounds",
         "tooltip": "Start a lightning round of a chosen type.",
         "submenu": [
             {"id": f"lightning_{k}", "icon": v.get("icon", ""), "label": k.upper(),
              "button_label": k.upper(),
              "command": (lambda k=k: toggle_light_mode(k)),
              "toggle":  lambda k=k: light_mode == k,
              "tooltip": v.get("desc", "")}
             for k, v in light_modes.items()
         ]},
        {"id": "lightning_variety", "icon": "🎲", "label": "Variety Lightning Round",
         "button_label": "VARIETY", "shortcut": True, "command": lambda: toggle_light_mode("variety"),
         "toggle":  lambda: light_mode == "variety",
         "tooltip": "Start a Variety Lightning Round — randomly picks round types weighted by popularity."},
        {"id": "lightning_settings", "icon": "🛠", "label": "Lightning Settings",
         "button_label": "LT.SETTINGS", "command": open_settings_editor,
         "tooltip": "Edit length, variants, and variety settings for each lightning round type."},
        "---",
        {"id": "show_youtube", "icon": "▶", "label": "YouTube Videos",
         "button_label": "YOUTUBE", "shortcut": True, "command": show_youtube_playlist,
         "tooltip": "Browse and queue a YouTube video to play after the current theme."},
        {"id": "show_archived_youtube", "icon": "📦", "label": "Archived YouTube Videos",
         "button_label": "ARCHIVED YT", "command": show_archived_youtube_playlist,
         "tooltip": "Browse and queue an archived YouTube video."},
        {"id": "manage_youtube", "icon": "🎥", "label": "Manage YouTube Videos",
         "button_label": "MANAGE YT", "command": youtube_editor.open_youtube_editor,
         "tooltip": "Add, edit, and archive YouTube videos for queuing."},
        "---",
        {"id": "show_fixed_lightning", "icon": "📋", "label": "Fixed Lightning Rounds",
         "button_label": "FIXED ROUND", "shortcut": True, "command": show_fixed_lightning_list,
         "tooltip": "Queue up a curated fixed lightning round playlist."},
        {"id": "manage_fixed_rounds", "icon": "📋", "label": "Manage Fixed Lightning Rounds",
         "button_label": "MANAGE FIXED", "command": open_fixed_lightning_manager,
         "tooltip": "Create and manage curated fixed lightning round playlists."},
    ],

    # ── BONUS ─────────────────────────────────────────────────────────────────
    "bonus": [
        {"label": "Auto Bonus at Start", "icon": "🎲",
         "toggle": lambda: auto_bonus_start is not None,
         "tooltip": "Automatically start a bonus question at the beginning of each theme.",
         "submenu": [
             {"icon": "✕", "label": "Off",              "command": lambda: set_auto_bonus_start(auto_bonus_start), "condition": lambda: auto_bonus_start is not None, "toggle": lambda: False, "tooltip": "Disable auto bonus at start."},
             "---",
             {"icon": "🎲", "label": "Random",          "command": lambda: set_auto_bonus_start("random"),     "toggle": lambda: auto_bonus_start == "random",     "tooltip": "Pick a random bonus type each time."},
             "---",
             {"icon": "💬", "label": "Free Form",        "command": lambda: set_auto_bonus_start("freeform"),   "toggle": lambda: auto_bonus_start == "freeform",   "condition": lambda: bonus_settings.get("freeform", {}).get("show_in_menu", True), "tooltip": "Open a free-answer prompt."},
             {"icon": "🔔", "label": "Buzzer",        "command": lambda: set_auto_bonus_start("buzzer"),   "toggle": lambda: auto_bonus_start == "buzzer",   "condition": lambda: bonus_settings.get("buzzer", {}).get("show_in_menu", True), "tooltip": "Open a buzzer prompt."},
             "---",
             {"icon": "４", "label": "Multiple Choice",  "command": lambda: set_auto_bonus_start("multiple"),   "toggle": lambda: auto_bonus_start == "multiple",   "condition": lambda: bonus_settings.get("multiple", {}).get("show_in_menu", True), "tooltip": "Multiple-choice: guess the anime from 4 options."},
             {"icon": "📅", "label": "Year",             "command": lambda: set_auto_bonus_start("year"),       "toggle": lambda: auto_bonus_start == "year",       "condition": lambda: bonus_settings.get("year", {}).get("show_in_menu", True), "tooltip": "Guess the year this anime first aired."},
             {"icon": "🏆", "label": "Score",            "command": lambda: set_auto_bonus_start("score"),      "toggle": lambda: auto_bonus_start == "score",      "condition": lambda: bonus_settings.get("score", {}).get("show_in_menu", True), "tooltip": "Guess the MyAnimeList score (0.0–10.0)."},
             {"icon": "👥", "label": "Members",          "command": lambda: set_auto_bonus_start("members"),    "toggle": lambda: auto_bonus_start == "members",    "condition": lambda: bonus_settings.get("members", {}).get("show_in_menu", True), "tooltip": "Guess the number of MyAnimeList members."},
             {"icon": "🥇", "label": "Popularity Rank",  "command": lambda: set_auto_bonus_start("popularity"), "toggle": lambda: auto_bonus_start == "popularity", "condition": lambda: bonus_settings.get("popularity", {}).get("show_in_menu", True), "tooltip": "Guess the popularity rank on MyAnimeList."},
             {"icon": "🔖", "label": "Tags",             "command": lambda: set_auto_bonus_start("tags"),       "toggle": lambda: auto_bonus_start == "tags",       "condition": lambda: bonus_settings.get("tags", {}).get("show_in_menu", True), "tooltip": "Guess the genres/themes/demographics tags."},
             {"icon": "🏢", "label": "Studio",           "command": lambda: set_auto_bonus_start("studio"),     "toggle": lambda: auto_bonus_start == "studio",     "condition": lambda: bonus_settings.get("studio", {}).get("show_in_menu", True), "tooltip": "Guess the studio that made this anime."},
             {"icon": "🎤", "label": "Artist",           "command": lambda: set_auto_bonus_start("artist"),     "toggle": lambda: auto_bonus_start == "artist",     "condition": lambda: bonus_settings.get("artist", {}).get("show_in_menu", True), "tooltip": "Guess the artist who performed the theme."},
             {"icon": "🎵", "label": "Song Title",       "command": lambda: set_auto_bonus_start("song"),       "toggle": lambda: auto_bonus_start == "song",       "condition": lambda: bonus_settings.get("song", {}).get("show_in_menu", True), "tooltip": "Guess the name of the song."},
             {"icon": "👤", "label": "Characters",       "command": lambda: set_auto_bonus_start("characters"), "toggle": lambda: auto_bonus_start == "characters", "condition": lambda: bonus_settings.get("characters", {}).get("show_in_menu", True), "tooltip": "Pick the correct characters from the anime."},
         ]},
        "---",
        {"id": "bonus_freeform",  "icon": "💬", "label": "Free Form",          "button_label": "FREE FORM",  "shortcut": True, "command": lambda: guess_extra("freeform"),   "toggle": lambda: bonus.guessing_extra == "freeform",   "cycle_pos": ("cycle_guess_other", 1), "condition": lambda: bonus_settings.get("freeform", {}).get("show_in_menu", True), "tooltip": "Open a free-answer prompt."},
        {"id": "bonus_buzzer",    "icon": "🔔", "label": "Buzzer",             "button_label": "BUZZER",     "shortcut": True, "command": lambda: guess_extra("buzzer"),     "toggle": lambda: bonus.guessing_extra == "buzzer",     "condition": lambda: web_server.is_running() and bonus_settings.get("buzzer", {}).get("show_in_menu", True), "tooltip": "Open a buzzer-only web bonus round."},
        {"id": "buzzer_lock", "icon": "🔒", "label": "Lock", "button_label": "BUZZ LOCK",
        "command": _web_buzzer_lock,
        "toggle": lambda: web_server.buzzer_is_locked(),
        "condition": lambda: web_server.is_running() and bonus.guessing_extra == "buzzer",
        "tooltip": "Toggle buzzer lock."},
        {"id": "buzzer_reset", "icon": "♻️", "label": "Reset", "button_label": "BUZZ RESET",
        "command": _web_buzzer_reset,
        "condition": lambda: web_server.is_running() and bonus.guessing_extra == "buzzer",
        "tooltip": "Clear submitted buzzes without changing lock state."},
        "---",
        {"id": "bonus_multiple", "icon": "４", "label": "Multiple Choice",  "button_label": "MULTIPLE",  "shortcut": True, "command": lambda: guess_extra("multiple"),  "toggle": lambda: bonus.guessing_extra == "multiple",  "condition": lambda: bonus_settings.get("multiple", {}).get("show_in_menu", True), "tooltip": "Multiple-choice: guess the anime from 4 options."},
        {"id": "bonus_year",     "icon": "📅", "label": "Year",              "button_label": "YEAR",       "shortcut": True, "command": lambda: guess_extra("year"),       "toggle": lambda: bonus.guessing_extra == "year",       "cycle_pos": ("cycle_guess_stats", 1), "condition": lambda: bonus_settings.get("year", {}).get("show_in_menu", True), "tooltip": "Guess the year this anime first aired."},
        {"id": "bonus_score",    "icon": "🏆", "label": "Score",             "button_label": "SCORE",      "shortcut": True, "command": lambda: guess_extra("score"),      "toggle": lambda: bonus.guessing_extra == "score",      "cycle_pos": ("cycle_guess_stats", 2), "condition": lambda: bonus_settings.get("score", {}).get("show_in_menu", True), "tooltip": "Guess the MyAnimeList score (0.0–10.0)."},
        {"id": "bonus_members",  "icon": "👥", "label": "Members",           "button_label": "MEMBERS",    "shortcut": True, "command": lambda: guess_extra("members"),    "toggle": lambda: bonus.guessing_extra == "members",    "cycle_pos": ("cycle_guess_stats", 4), "condition": lambda: bonus_settings.get("members", {}).get("show_in_menu", True), "tooltip": "Guess the number of MyAnimeList members."},
        {"id": "bonus_rank",     "icon": "🥇", "label": "Popularity Rank",   "button_label": "RANK",       "shortcut": True, "command": lambda: guess_extra("popularity"), "toggle": lambda: bonus.guessing_extra == "popularity", "cycle_pos": ("cycle_guess_stats", 3), "condition": lambda: bonus_settings.get("popularity", {}).get("show_in_menu", True), "tooltip": "Guess the popularity rank on MyAnimeList."},
        {"id": "bonus_tags",     "icon": "🔖", "label": "Tags",              "button_label": "TAGS",       "shortcut": True, "command": lambda: guess_extra("tags"),       "toggle": lambda: bonus.guessing_extra == "tags",       "condition": lambda: bonus_settings.get("tags", {}).get("show_in_menu", True), "tooltip": "Guess the genres/themes/demographics tags."},
        {"id": "bonus_studio",   "icon": "🏢", "label": "Studio",            "button_label": "STUDIO",     "shortcut": True, "command": lambda: guess_extra("studio"),     "toggle": lambda: bonus.guessing_extra == "studio",     "cycle_pos": ("cycle_guess_other", 2), "condition": lambda: bonus_settings.get("studio", {}).get("show_in_menu", True), "tooltip": "Guess the studio that made this anime."},
        {"id": "bonus_artist",   "icon": "🎤", "label": "Artist",            "button_label": "ARTIST",     "shortcut": True, "command": lambda: guess_extra("artist"),     "toggle": lambda: bonus.guessing_extra == "artist",     "cycle_pos": ("cycle_guess_other", 4), "condition": lambda: bonus_settings.get("artist", {}).get("show_in_menu", True), "tooltip": "Guess the artist who performed the theme."},
        {"id": "bonus_song",     "icon": "🎵", "label": "Song Title",        "button_label": "SONG",       "shortcut": True, "command": lambda: guess_extra("song"),       "toggle": lambda: bonus.guessing_extra == "song",       "cycle_pos": ("cycle_guess_other", 3), "condition": lambda: bonus_settings.get("song", {}).get("show_in_menu", True), "tooltip": "Guess the name of the song."},
        {"id": "bonus_chars",    "icon": "👤", "label": "Characters",        "button_label": "CHARACTERS", "shortcut": True, "command": lambda: guess_extra("characters"), "toggle": lambda: bonus.guessing_extra == "characters", "condition": lambda: bonus_settings.get("characters", {}).get("show_in_menu", True), "tooltip": "Identify 2 characters from this anime out of 6 shown."},
        "---",
        {"label": "Bonus Settings", "icon": "⚙️", "button_label": "BONUS SETTINGS", "command": open_bonus_settings_editor, "tooltip": "Configure points, lightning points, and random eligibility for each bonus type."},
    ],

    # ── INFORMATION ───────────────────────────────────────────────────────────
    "information": [
        {"id": "info_popup", "icon": "ℹ", "label": "Info Popup",
         "button_label": "INFO", "shortcut": True, "command": toggle_info_popup,
         "toggle":  lambda: is_title_window_up() and not title_info_only,
         "tooltip": "Show or hide the information popup at the bottom of the screen."},
        {"id": "title_popup", "icon": "𝕋", "label": "Title Popup",
         "button_label": "TITLE", "shortcut": True, "command": toggle_title_info_popup,
         "toggle":  lambda: is_title_window_up() and title_info_only,
         "tooltip": "Show or hide the title popup at the bottom of the screen."},
        {"id": "artist_info", "icon": "🎤", "label": "Artist Info",
         "button_label": "ARTIST INFO", "shortcut": True, "command": toggle_artist_info_popup,
         "toggle":  lambda: bool(artist_info_display),
         "tooltip": "Show or hide the info popup listing themes by this artist."},
        {"id": "studio_info", "icon": "🏢", "label": "Studio Info",
         "button_label": "STUDIO INFO", "shortcut": True, "command": toggle_studio_info_popup,
         "toggle":  lambda: bool(studio_info_display),
         "tooltip": "Show or hide the info popup listing anime by this studio."},
        {"id": "season_rankings", "icon": "📅", "label": "Season Rankings",
         "button_label": "SEASON", "shortcut": True, "command": toggle_season_info_popup,
         "toggle":  lambda: bool(season_info_display),
         "tooltip": "Show or hide the info popup with season popularity rankings."},
        {"id": "year_rankings", "icon": "🗓", "label": "Year Rankings",
         "button_label": "YEAR", "shortcut": True, "command": toggle_year_info_popup,
         "toggle":  lambda: bool(year_info_display),
         "tooltip": "Show or hide the info popup with year popularity rankings."},
        "---",
        {"id": "auto_info_start", "icon": "⏪", "label": "Auto-show at Start",
         "button_label": "AUTO START", "shortcut": True, "command": toggle_auto_info_start,
         "toggle":  lambda: auto_info_start,
         "tooltip": "When enabled, automatically shows the info popup at the start of each theme."},
        {"id": "auto_info_end", "icon": "⏩", "label": "Auto-show at End",
         "button_label": "AUTO END", "shortcut": True, "command": toggle_auto_info_end,
         "toggle":  lambda: auto_info_end,
         "tooltip": "When enabled, automatically shows the info popup during the last 8 seconds."},
        "---",
        {"id": "end_session", "icon": "", "label": "End Screen",
         "button_label": "END SESSION", "shortcut": True, "command": end_session,
         "tooltip": "Display the end session screen with a scrolling message and themes played count."},
    ],

    # ── TOGGLE ───────────────────────────────────────────────────────────────
    "toggles": [
        {"id": "blind", "icon": "👁", "label": "Blind",
         "button_label": "BLIND",
         "shortcut": True, "command": lambda: blind(True),
         "toggle":  lambda: blind_screen.black_overlay is not None,
         "tooltip": "Covers the screen with a color matching the average screen color. Shows a progress bar if a video is playing."},
        {"id": "peek", "icon": "👀", "label": "Reveal",
         "button_label": "REVEAL",
         "shortcut": True, "command": toggle_peek,
         "toggle":  lambda: bool(peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active),
         "submenu": [
             {"label": "Turn Off", "icon": "✖", "command": toggle_peek,
              "condition": lambda: bool(peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active)},
             {"id": "peek_random",   "label": "Random",   "icon": "🔀", "shortcut": True, "command": lambda: _activate_peek_variant(get_next_peek_mode()),
              "condition": lambda: not bool(peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active)},
             {"type": "separator", "condition": lambda: not bool(peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active)},
             {"id": "peek_blur",     "label": "Blur",     "icon": "🌫", "shortcut": True,
              "command": lambda: toggle_peek() if (filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'blur') else _activate_peek_variant('blur'),
              "toggle": lambda: bool(filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'blur'),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("blur", True)},
             {"id": "peek_edge",     "label": "Edge",     "icon": "◼",  "shortcut": True,
              "command": lambda: toggle_peek() if edge_overlay.edge_overlay_box else _activate_peek_variant('edge'),
              "toggle": lambda: bool(edge_overlay.edge_overlay_box),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("edge", True)},
             {"id": "peek_grow",     "label": "Grow",     "icon": "⬛", "shortcut": True,
              "command": lambda: toggle_peek() if grow_overlay.grow_overlay_boxes else _activate_peek_variant('grow'),
              "toggle": lambda: bool(grow_overlay.grow_overlay_boxes),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("grow", True)},
             {"id": "peek_outline",   "label": "Outline",   "icon": "✏️",  "shortcut": True,
              "command": lambda: toggle_peek() if (filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'outline') else _activate_peek_variant('outline'),
              "toggle": lambda: bool(filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'outline'),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("outline", True)},
             {"id": "peek_pixelize", "label": "Pixelize", "icon": "🟦", "shortcut": True,
              "command": lambda: toggle_peek() if (filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'pixelize') else _activate_peek_variant('pixelize'),
              "toggle": lambda: bool(filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'pixelize'),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("pixelize", True)},
             {"id": "peek_slice",    "label": "Slice",    "icon": "◧",  "shortcut": True,
              "command": lambda: toggle_peek() if peek_overlay.peek_overlay1 else _activate_peek_variant('slice'),
              "toggle": lambda: bool(peek_overlay.peek_overlay1),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("slice", True)},
             {"id": "peek_wave",     "label": "Wave",     "icon": "🌊", "shortcut": True,
              "command": lambda: toggle_peek() if (filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'wave') else _activate_peek_variant('wave'),
              "toggle": lambda: bool(filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'wave'),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("wave", True)},
             {"id": "peek_zoom",     "label": "Zoom",     "icon": "🔍", "shortcut": True,
              "command": lambda: toggle_peek() if (filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'zoom') else _activate_peek_variant('zoom'),
              "toggle": lambda: bool(filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'zoom'),
              "condition": lambda: lightning_mode_settings.get("reveal",{}).get("show_in_menu",{}).get("zoom", True)},
         ],
         "tooltip": "When off: opens a submenu to pick a variant (or random). When on: turns off."},
        {"id": "narrow_peek", "icon": "◀", "label": "Reveal Less",
         "button_label": "RV LESS",
         "shortcut": True, "command": narrow_peek,
         "tooltip": "Reveals less — increases the obscuring effect."},
        {"id": "widen_peek", "icon": "▶", "label": "Reveal More",
         "button_label": "RV MORE",
         "shortcut": True, "command": widen_peek,
         "tooltip": "Reveals more — decreases the obscuring effect."},
        {"id": "mute", "icon": "🔇", "label": "Mute",
         "button_label": "MUTE",
         "shortcut": True, "command": toggle_mute,
         "toggle":  lambda: state.controls.light_muted if (light_mode or light_round_started) else state.controls.disable_video_audio,
         "tooltip": "Toggles muting the video/theme audio."},
        {"id": "distort_audio", "icon": "🎚", "label": "Distort Audio",
         "button_label": "DISTORT",
         "toggle": lambda: bool(_audio_distortions_active),
         "tooltip": "Apply audio distortion filters to make themes harder to recognise.",
         "submenu": [
             {"id": "distort_echo",       "icon": "🔊", "label": "Echo",       "shortcut": True, "command": lambda: toggle_audio_distortion("echo"),      "toggle": lambda: "echo"       in _audio_distortions_active, "tooltip": "Echo / reverb effect."},
             {"id": "distort_flanger",    "icon": "🌀", "label": "Flanger",    "shortcut": True, "command": lambda: toggle_audio_distortion("flanger"),   "toggle": lambda: "flanger"    in _audio_distortions_active, "tooltip": "Swirling / wobbly flanger effect."},
             {"id": "distort_vibrato",    "icon": "🎵", "label": "Vibrato",    "shortcut": True, "command": lambda: toggle_audio_distortion("vibrato"),   "toggle": lambda: "vibrato"    in _audio_distortions_active, "tooltip": "Pitch oscillation at 7 Hz."},
             {"id": "distort_telephone",  "icon": "📞", "label": "Telephone",  "shortcut": True, "command": lambda: toggle_audio_distortion("telephone"), "toggle": lambda: "telephone"  in _audio_distortions_active, "tooltip": "Narrow phone-band filter (300–3400 Hz only)."},
             {"id": "distort_underwater", "icon": "🌊", "label": "Underwater", "shortcut": True, "command": lambda: toggle_audio_distortion("underwater"),"toggle": lambda: "underwater" in _audio_distortions_active, "tooltip": "Heavy lowpass + reverb — muffled underwater effect."},
             {"id": "distort_chipmunk",   "icon": "🐿", "label": "Chipmunk",   "shortcut": True, "command": lambda: toggle_audio_distortion("chipmunk"),  "toggle": lambda: "chipmunk"   in _audio_distortions_active, "tooltip": "2× pitch up — chipmunk voice."},
             {"id": "distort_demon",      "icon": "😈", "label": "Demon",      "shortcut": True, "command": lambda: toggle_audio_distortion("demon"),     "toggle": lambda: "demon"      in _audio_distortions_active, "tooltip": "0.5× pitch down — deep demon voice."},
             {"id": "distort_vaporwave",  "icon": "🌸", "label": "Vaporwave",  "shortcut": True, "command": lambda: toggle_audio_distortion("vaporwave"), "toggle": lambda: "vaporwave"  in _audio_distortions_active, "tooltip": "0.8× pitch — slowed + slightly lower."},
             {"id": "distort_8bit_game",  "icon": "👾", "label": "8-bit Game", "shortcut": True, "command": lambda: toggle_audio_distortion("8bit_game"), "toggle": lambda: "8bit_game"  in _audio_distortions_active, "tooltip": "2-bit depth @ 8 kHz — retro video game bleeps."},
             {"id": "distort_robot",      "icon": "🤖", "label": "Robot",      "shortcut": True, "command": lambda: toggle_audio_distortion("robot"),     "toggle": lambda: "robot"      in _audio_distortions_active, "tooltip": "Rapid micro-echoes + 30 Hz vibrato — robotic stutter."},
         ]},
        "---",
        {"id": "censors", "label": "Censors Toggle",
         "icon": lambda: f"({sum(1 for c in (get_file_censors(currently_playing.get('filename','')) or []) if not c.get('nsfw') and not c.get('mute') and not c.get('skip'))})",
         "button_label": "CENSORS",
         "shortcut": True, "command": toggle_censor_bar,
         "toggle":  lambda: censors.censors_enabled,
         "tooltip": "Toggle regular censor bars on or off. NSFW censors have a separate toggle."},
        {"id": "censors_nsfw", "label": "NSFW Censors Toggle",
         "icon": lambda: f"({sum(1 for c in (get_file_censors(currently_playing.get('filename','')) or []) if c.get('nsfw'))})",
         "button_label": "NSFW CENS.",
         "shortcut": True, "command": toggle_censor_nsfw_bar,
         "toggle":  lambda: censors.censors_nsfw_enabled,
         "tooltip": "Toggle NSFW censor bars on or off. Regular censors have a separate toggle."},
        {"id": "censor_editor", "icon": "➕", "label": "Censor Editor",
         "button_label": "CENSOR ED.",
         "command": lambda: open_censor_editor(True),
         "tooltip": "Opens the censor editor to add, edit, or delete censor boxes for the current theme."},
        "---",
        {"id": "always_on_top", "icon": "📌", "label": "Always On Top",
         "button_label": "ON TOP",
         "command": toggle_mpv_always_on_top,
         "toggle": lambda: state.controls.mpv_always_on_top,
         "tooltip": "Keep the mpv player window on top of all other windows."},
        {"id": "auto_refresh", "icon": "♻", "label": "Auto Refresh Metadata",
         "button_label": "AUTO REFRESH",
         "command": toggle_auto_auto_refresh,
         "toggle":  lambda: auto_refresh_toggle,
         "tooltip": "Toggle auto refreshing jikan metadata (score, members) as themes play — never refreshes the same anime twice per session."},
        {"id": "fullscreen", "icon": "⛶", "label": "Fullscreen",
         "button_label": "FULLSCREEN",
         "command": toggle_autoplay_fullscreen,
         "toggle": lambda: state.controls.autoplay_fullscreen,
         "tooltip": "Toggle whether the player starts in fullscreen when a track plays."},
        {"id": "progress_bar", "icon": "▬", "label": "Progress Bar",
         "button_label": "PROGRESS",
         "shortcut": True, "command": toggle_progress_bar,
         "toggle":  lambda: progress_bar_enabled,
         "tooltip": "Toggle a subtle progress bar overlay showing the current playback position."},
         "---",
        {"id": "enable_shortcuts", "icon": "", "label": "Enable Shortcuts",
         "button_label": "SHORTCUTS",
         "shortcut": True, "command": toggle_disable_shortcuts,
         "toggle":  lambda: not disable_shortcuts,
         "tooltip": "Toggle shortcut keys on or off."},
        {"id": "view_shortcuts", "icon": "", "label": "Edit/View Shortcuts",
         "button_label": "VIEW KEYS",
         "shortcut": True, "command": open_shortcut_editor,
         "tooltip": "View and edit keyboard shortcuts."},
    ],

    # ── THEME ────────────────────────────────────────────────────────────────
    "theme": [
        {"label": "No theme loaded", "command": lambda: None,
         "condition": lambda: not currently_playing.get("filename"),
         "tooltip": "No theme is currently playing."},
        {"id": "tag", "icon": "❌", "label": "Tag",
         "button_label": "TAG", "shortcut": True, "command": tag,
         "condition": lambda: bool(currently_playing.get("filename")),
         "toggle":  lambda: bool(check_tagged(currently_playing.get("filename"))),
         "tooltip": "Add or remove the current theme from the 'Tagged Themes' playlist."},
        {"id": "favorite", "icon": "❤", "label": "Favorite",
         "button_label": "FAVORITE", "shortcut": True, "command": favorite,
         "condition": lambda: bool(currently_playing.get("filename")),
         "toggle":  lambda: bool(check_favorited(currently_playing.get("filename"))),
         "tooltip": "Add or remove the current theme from the 'Favorite Themes' playlist."},
        {"id": "blind_mark", "icon": "👁", "label": "Blind Mark",
         "button_label": "BLIND MARK", "shortcut": True, "command": blind_mark,
         "condition": lambda: bool(currently_playing.get("filename")),
         "toggle":  lambda: bool(check_blind_mark(currently_playing.get("filename"))),
         "tooltip": "Add or remove the current theme from the 'Blind Themes' auto-round playlist."},
        {"id": "peek_mark", "icon": "👀", "label": "Reveal Mark",
         "button_label": "RV MARK", "shortcut": True, "command": peek_mark,
         "condition": lambda: bool(currently_playing.get("filename")),
         "toggle":  lambda: bool(check_peek_mark(currently_playing.get("filename"))),
         "tooltip": "Add or remove the current theme from the Reveal playlist (plays as a Reveal Round)."},
        {"id": "mute_peek_mark", "icon": "🔇", "label": "Mute Reveal Mark",
         "button_label": "MUTE RV MRK", "shortcut": True, "command": mute_peek_mark,
         "condition": lambda: bool(currently_playing.get("filename")),
         "toggle":  lambda: bool(check_mute_peek_mark(currently_playing.get("filename"))),
         "tooltip": "Add or remove the current theme from the Mute Reveal playlist (plays as a Mute Reveal Round)."},
        {"id": "add_to_playlist", "icon": "➕", "label": "Add to Playlist",
         "button_label": "ADD TO LIST", "command": add_to_saved_playlist,
         "condition": lambda: bool(currently_playing.get("filename")),
         "tooltip": "Add the current theme to one of your saved (non-system) playlists."},
        "---",
        {"id": "refetch_metadata", "icon": "📥", "label": "Fetch Theme Data",
         "button_label": "FETCH DATA", "command": refetch_metadata,
         "condition": lambda: bool(currently_playing.get("filename")),
         "tooltip": "Fetch metadata for the currently playing theme from AnimeThemes, Jikan, AniList, and AniDB."},
        "---",
        {"id": "copy_filename", "icon": "⮺",  "label": "Copy Filename",
        "button_label": "COPY NAME", "command": lambda: pyperclip.copy(currently_playing.get("filename", "")),
        "condition": lambda: bool(currently_playing.get("filename")),
        "tooltip": "Copy the filename to the clipboard."},
        {"id": "download_theme", "icon": "⬇️", "label": "Download",
        "button_label": "DOWNLOAD", "command": download_current_theme,
        "condition": lambda: bool(currently_playing.get("filename")) and _cp_is_stream(),
              "tooltip": "Download or move this file to the local directory."},
        {"label": "File Actions", "icon": "📁",
         "condition": lambda: bool(currently_playing.get("filename")) and not _cp_is_stream(),
         "tooltip": "File operations for the currently playing theme.",
         "submenu": [
             {"id": "open_folder", "icon": "📁", "label": "Open Folder",
              "button_label": "OPEN FOLDER",  "command": lambda: open_file_folder_by_filename(currently_playing.get("filename", "")),
              "condition": lambda: _cp_is_local_file(),
              "tooltip": "Open the folder containing this file."},
             {"id": "cut_before", "icon": "✂️", "label": "Cut Before",
              "button_label": "CUT BEFORE", "command": lambda: cut_before_current_time(currently_playing.get("filename", "")),
              "condition": lambda: ffmpeg_available and _cp_is_local_file(),
              "tooltip": "Cut the file before the current playback position."},
             {"id": "cut_after", "icon": "✂️", "label": "Cut After",
              "button_label": "CUT AFTER", "command": lambda: cut_after_current_time(currently_playing.get("filename", "")),
              "condition": lambda: ffmpeg_available and _cp_is_local_file(),
              "tooltip": "Cut the file after the current playback position."},
             {"id": "rename_theme", "icon": "✏️", "label": "Rename",
              "button_label": "RENAME", "command": lambda: rename_file_by_filename(currently_playing.get("filename", "")),
              "condition": lambda: _cp_is_local_file(),
              "tooltip": "Rename the currently playing file."},
             {"id": "convert_theme", "icon": "🔄", "label": "Convert",
              "button_label": "CONVERT", "command": lambda: convert_file_format_by_filename(currently_playing.get("filename", "")),
              "condition": lambda: ffmpeg_available and _cp_is_local_file(),
              "tooltip": "Convert the file to a different format."},
             {"id": "edit_volume_theme","icon": "🔊", "label": "Edit Volume",
              "button_label": "EDIT VOL", "command": lambda: edit_file_volume_by_filename(currently_playing.get("filename", "")),
              "condition": lambda: ffmpeg_available and _cp_is_local_file(),
              "tooltip": "Adjust the audio volume of this file."},
             {"id": "delete_theme_file","icon": "❌", "label": "Delete File",
              "button_label": "DELETE FILE", "command": lambda: delete_file_by_filename(currently_playing.get("filename", "")),
              "condition": lambda: _cp_is_local_file(),
              "tooltip": "Permanently delete this file."},
         ]},
        {"label": "External Sites", "icon": "🔗",
         "condition": lambda: bool(currently_playing.get("data")),
         "tooltip": "Open external database pages for this anime.",
         "submenu": [
             {"id": "open_igdb", "label": "IGDB",
              "button_label": "IGDB", "command": lambda: webbrowser.open(f"https://www.igdb.com/games/{(currently_playing.get('data') or {}).get('igdb_slug') or (currently_playing.get('data') or {}).get('igdb')}"),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("igdb")) and is_game(currently_playing.get("data") or {}),
              "tooltip": "Open the IGDB page for this game."},
             {"id": "open_mal", "label": "MyAnimeList",
              "button_label": "MAL", "command": lambda: open_mal_page((currently_playing.get("data") or {}).get("mal")),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("mal")) and not is_game(currently_playing.get("data") or {}),
              "tooltip": "Open the MyAnimeList page for this anime."},
             {"id": "open_anidb", "label": "AniDB",
              "button_label": "ANIDB", "command": lambda: open_anidb_page((currently_playing.get("data") or {}).get("anidb")),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("anidb")) and not is_game(currently_playing.get("data") or {}),
              "tooltip": "Open the AniDB page for this anime."},
             {"id": "open_anilist", "label": "AniList",
              "button_label": "ANILIST", "command": lambda: open_anilist_page((currently_playing.get("data") or {}).get("anilist")),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("anilist")) and not is_game(currently_playing.get("data") or {}),
              "tooltip": "Open the AniList page for this anime."},
             {"id": "open_animethemes", "label": "AnimeThemes",
              "button_label": "ANIMETHEMES", "command": lambda: open_animethemes_anime_page((currently_playing.get("data") or {}).get("animethemes_slug")),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("animethemes_slug")) and "[MAL]" not in currently_playing.get("filename", "") and "[ID]" not in currently_playing.get("filename", "") and currently_playing.get("type") == "theme",
              "tooltip": "Open the AnimeThemes page for this anime."},
             {"id": "stream_animethemes", "icon": "▶", "label": "Stream on AnimeThemes",
              "button_label": "STREAM AT", "command": lambda: anime_themes_video(currently_playing.get("filename", "")),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("animethemes_slug")) and "[MAL]" not in currently_playing.get("filename", "") and "[ID]" not in currently_playing.get("filename", "") and currently_playing.get("type") == "theme",
              "tooltip": "Stream this theme on the AnimeThemes website."},
         ]},
        {"label": "Media", "icon": "🖼",
         "condition": lambda: bool((currently_playing.get("data") or {}).get("trailer") or (currently_playing.get("data") or {}).get("cover") or (OPENAI_API_KEY and currently_playing.get("data"))),
         "tooltip": "Cover art, trailer, and AI trivia for this anime.",
         "submenu": [
             {"id": "show_cover", "icon": "🖼",  "label": "Show Cover",
              "button_label": "COVER", "command": lambda: create_cover_popup(f"{get_display_title(currently_playing.get('data') or {})} Cover", (currently_playing.get('data') or {}).get('cover'))(),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("cover")),
              "tooltip": "Show the cover art for this anime."},
             {"id": "copy_cover_url", "icon": "⍘",   "label": "Copy Cover URL",
              "button_label": "COPY COVER", "command": lambda: pyperclip.copy((currently_playing.get("data") or {}).get("cover", "")),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("cover")),
              "tooltip": "Copy the cover art URL to the clipboard."},
             {"id": "play_trailer", "icon": "▶",   "label": "Play Trailer",
              "button_label": "TRAILER", "command": play_trailer,
              "condition": lambda: bool((currently_playing.get("data") or {}).get("trailer")),
              "tooltip": "Play the trailer for this anime."},
             {"id": "copy_trailer_url",  "icon": "⍘",   "label": "Copy Trailer URL",
              "button_label": "COPY TRAILER", "command": lambda: pyperclip.copy((currently_playing.get("data") or {}).get("trailer", "")),
              "condition": lambda: bool((currently_playing.get("data") or {}).get("trailer")),
              "tooltip": "Copy the trailer URL to the clipboard."},
             {"id": "anime_trivia", "icon": "💡",  "label": "Trivia",
              "button_label": "TRIVIA", "command": lambda: generate_anime_trivia(currently_playing.get("data"), True),
              "condition": lambda: bool(currently_playing.get("data")) and bool(OPENAI_API_KEY),
              "tooltip": "Generate AI trivia about this anime. Prints in console."},
         ]},
    ],

    # ── HIDDEN (shortcuts only — no UI display) ─────────────────────────────
    "hidden": [
        {"id": "dock_player", "icon": "📌", "label": "Dock Player",
         "button_label": "DOCK", "shortcut": True, "command": dock_player,
         "tooltip": "Toggle docking the player to the bottom of the screen."},
        {"id": "search_themes",     "label": "Search Themes",
         "shortcut": True, "command": lambda: search(add=playlist.get("infinite", False)),
         "tooltip": "Open the theme search (shortcut-key mode)."},
        {"id": "reroll_next", "icon": lambda: "🔄" if is_reroll_valid() else "", "label": "Re-roll Next Track",
         "button_label": lambda: "RE-ROLL" if is_reroll_valid() else "", "shortcut": True, "command": reroll_next,
         "tooltip": "Re-fetch the next track in infinite mode (only at the penultimate position)."},
        {"id": "cycle_light_mode",  "label": "Cycle Lightning Mode",
         "button_label": "CYCLE LIGHT", "shortcut": True, "command": cycle_light_mode,
         "tooltip": "Cycle through all lightning round modes in order."},
        {"id": "cycle_blind_peek",  "label": "Cycle Blind / Reveal",
         "button_label": "CYCLE BLIND/RV", "shortcut": True, "command": cycle_blind_peek,
         "tooltip": "Cycle: off → blind round → reveal round → mute reveal round."},
        {"id": "cycle_guess_stats", "label": "Cycle Stat Questions",
         "button_label": "CYCLE STAT ?s", "shortcut": True, "command": cycle_guess_stats,
         "tooltip": "Cycle bonus questions: year → score → popularity → members."},
        {"id": "cycle_guess_other", "label": "Cycle Other Questions",
         "button_label": "CYCLE OTHER ?s", "shortcut": True, "command": cycle_guess_other,
         "tooltip": "Cycle bonus questions: freeform → studio → song → artist."},
        # ── PLAYER CONTROLS (no toolbar button — popout / shortcuts only) ──
        {"id": "play_pause", "icon": "⏯",  "label": "Play/Pause",  "button_label": "PLAY/PAUSE",
         "button_label": "PLAY/PAUSE", "shortcut": True, "command": play_pause,  "tooltip": "Toggle play or pause."},
        {"id": "stop", "icon": "⏹", "label": "Stop", "button_label": "STOP",
         "shortcut": True, "command": stop, "tooltip": "Stop playback."},
        {"id": "previous", "icon": "⏮", "label": "Previous","button_label": "PREVIOUS",
         "shortcut": True, "command": play_previous, "tooltip": "Go to the previous theme."},
        {"id": "next", "icon": "⏭", "label": "Next","button_label": "NEXT",
         "shortcut": True, "command": play_next, "tooltip": "Go to the next theme."},
        {"id": "skip_to_end", "icon": "⏭", "label": "Skip to End", "button_label": "SKIP TO END",
         "shortcut": True, "command": lambda: (seek_to(player.get_length() - 3000), root.after(0, show_skip_to_end_osd)) if player.get_length() > 3000 else None,
         "tooltip": "Seek the current track to the last few seconds.",
         "submenu": [
             {"id": "skip_to_end_seek",    "icon": "⏭", "label": "Skip to End (Seek)",
              "shortcut": True,
              "command": lambda: (seek_to(player.get_length() - 3000), root.after(0, show_skip_to_end_osd)) if player.get_length() > 3000 else None,
              "tooltip": "Instantly seek the current track to the last few seconds."},
             {"id": "skip_to_end_ff",      "icon": "⏩", "label": "Fast Forward to End",
              "shortcut": True,
              "command": lambda: fast_forward_to_end(4, 500) if player.get_length() > 3000 else None,
              "tooltip": "Play at 4× speed for 0.5 s then seek to the last few seconds."},
             {"id": "skip_to_end_ff_slow", "icon": "⏩", "label": "Fast Forward to End (slow)",
              "shortcut": True,
              "command": lambda: fast_forward_to_end(4, 2000) if player.get_length() > 3000 else None,
              "tooltip": "Play at 4× speed for 2 s then seek to the last few seconds."},
         ]},
        {"id": "lightning_start", "label": "Start/Stop Lightning",
         "button_label": lambda: "⏹ STOP" if light_mode else "▶ START",
         "shortcut": True, "command": select_lightning_mode,
         "toggle":  lambda: bool(light_mode),
         "tooltip": "Start or stop the currently selected lightning round mode."},
        {"id": "close_list", "label": "Close List",
         "button_label": "CLOSE LIST", "shortcut": True, "command": lambda: _close_list(right_column),
         "tooltip": "Close the currently open list or panel in the right column."},
    ],

    # ── BUTTON RIGHT-CLICK ACTIONS ────────────────────────────────────────────
    # Maps section name → callable invoked when the toolbar button is right-clicked.
    # Add an entry here to attach a shortcut action to a button's right-click.
    "_right_click": {
        # Each entry: (action, label_func) — label_func called *after* action so it reflects new state
        #file open settings
        "file": (lambda: show_settings_popup(), lambda: "CONFIG"),
        "playlist" : (lambda: show_playlist(), lambda: "SHOW PLAYLIST" if list_loaded == "playlist" else "HIDE PLAYLIST"),
        "queue": (lambda: toggle_light_mode("variety"), lambda: "VARIETY UP NEXT" if light_mode == "variety" else "VARIETY DISABLED"),
        "bonus":   (lambda: guess_extra("multiple"), lambda: "MULTIPLE CHOICE"),
        "information": (toggle_info_popup, lambda: "INFO POPUP"),
        "theme": (lambda: tag() if bool(currently_playing.get("filename")) else None, lambda: ("TAG ON" if bool(check_tagged(currently_playing.get("filename"))) else "TAG OFF") if bool(currently_playing.get("filename")) else None),
        "toggles": (toggle_disable_shortcuts,
                    lambda: "KEYS ON" if not disable_shortcuts else "KEYS OFF"),
        "popout": (lambda: create_popout_controls(), lambda: "POPOUT OPEN"),
        "directory": (lambda: toggle_censor_bar(), lambda: "CENSORS ON" if censors.censors_enabled else "CENSORS OFF"),
    },

    }  # end _get_menu_registry()


def _open_toolbar_menu(name: str, button: tk.Button, section_key: str):
    """Open a registry-backed toolbar dropdown with toggle behaviour.

    tk_popup() blocks via Tcl's tkwait until the menu is dismissed.
    When it returns, the dismiss-click has been handled by the OS but the
    corresponding Tk ButtonRelease / command= event is still pending in the
    queue.  We check winfo_pointerxy() right here — synchronously, before
    the event loop resumes — to set a suppress flag that command= will see.
    """
    if getattr(button, '_suppress_open', False):
        button._suppress_open = False
        return

    registry = _get_menu_registry()
    m = tk.Menu(root, tearoff=0, bg="black", fg="white",
                activebackground=HIGHLIGHT_COLOR, activeforeground="white", font=MENU_FONT)
    build_menu(m, registry[section_key])
    popup_menu(m, button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    # Menu just closed.  If the pointer is still over this button, the button
    # click dismissed it — suppress the pending command= so we don't reopen.
    try:
        px, py = root.winfo_pointerxy()
        bx, by = button.winfo_rootx(), button.winfo_rooty()
        if bx <= px < bx + button.winfo_width() and by <= py < by + button.winfo_height():
            button._suppress_open = True
    except Exception:
        pass


def create_first_row_buttons():
    for widget in list(first_row_frame.winfo_children()):
        try:
            widget.destroy()
        except Exception:
            pass

    _rc = _get_menu_registry().get("_right_click", {})

    global collapse_button
    collapse_button = create_button(first_row_frame, "▼", toggle_player_collapse, False,
                                help_text="Collapses or expands the player info columns. "
                                "Click to toggle between collapsed (arrow up) and expanded (arrow down) states.")
    
    global dock_button
    dock_button = create_button(first_row_frame, "DOCK", dock_player, True,
                                help_text="Docks the player on the bottom of the screen and makes it semitransparent. " +
                                "Click again to undock.\n\nWhen shortcuts are enabled it will" + 
                                " hide it at the bottom of the screen. Otherwise it will return to its " + 
                                "previous position.\n\nIt can be useful if you need to share any "+
                                "information on the player, or use any buttons that don't have "+
                                "shortcuts. Also if you are just browsing.")

    def show_popout_menu(event=None):
        if getattr(popout_controls_button, '_suppress_open', False):
            popout_controls_button._suppress_open = False
            return
        m = tk.Menu(root, tearoff=0, bg="black", fg="white",
                    activebackground=HIGHLIGHT_COLOR, activeforeground="white", font=MENU_FONT)
        m.add_command(label="🗖  Open Popout", command=create_popout_controls)
        m.add_command(label="⚙  Configure Layout", command=popout_layout_editor.open_popout_layout_editor)
        popup_menu(m, popout_controls_button.winfo_rootx(),
                   popout_controls_button.winfo_rooty() + popout_controls_button.winfo_height())
        try:
            px, py = root.winfo_pointerxy()
            bx, by = popout_controls_button.winfo_rootx(), popout_controls_button.winfo_rooty()
            if bx <= px < bx + popout_controls_button.winfo_width() and by <= py < by + popout_controls_button.winfo_height():
                popout_controls_button._suppress_open = True
        except Exception:
            pass

    global popout_controls_button
    popout_controls_button = create_button(first_row_frame, "🗖POPOUT▾", show_popout_menu, True,
                                help_text="Open or configure the popout controls window.\n"
                                "Right-Click Shortcut: Open Popout",
                                right_click=_rc.get("popout"))
    
    
    def show_file_menu(event=None):
        _open_toolbar_menu("file", file_menu_button, "file")

    global file_menu_button
    file_menu_button = create_button(first_row_frame, "FILE▾", show_file_menu, True,
                                help_text="Opens the file menu with options for choosing a directory, importing/exporting data, metadata tools, settings, and help.",
                                right_click=_rc.get("file"))

    def show_playlist_menu(event=None):
        _open_toolbar_menu("playlist", playlist_menu_button, "playlist")

    if playlist.get("infinite", False):
        _pl_out_of = playlist_ops.total_infinite_files - len(playlist_ops.cached_skipped_themes)
        _pl_counter = f"\u221e/{_pl_out_of}"
    else:
        _pl_counter = f"{playlist['current_index']+1}/{len(playlist['playlist'])}"

    global playlist_menu_button
    playlist_menu_button = create_button(first_row_frame, f"PLAYLIST {_pl_counter}\u25be", show_playlist_menu, True,
                                    help_text=("Options for creating and managing playlists. \n"
                                    "Right-Click Shortcut: Show Playlist"),
                                    right_click=_rc.get("playlist"))

    # Enable drag-and-drop on the playlist menu button
    def setup_playlist_drag_drop():
        try:
            enable_drag_and_drop(playlist_menu_button, handle_dropped_files)
        except Exception as e:
            print(f"Could not enable drag-and-drop on playlist button: {e}")
    root.after(100, setup_playlist_drag_drop)

    def show_queue_menu(event=None):
        _open_toolbar_menu("queue", queue_menu_button, "queue")

    global queue_menu_button
    queue_menu_button = create_button(first_row_frame, "QUEUE ROUND▾", show_queue_menu, True,
                                      help_text=("Queue special rounds, lightning rounds, and more.\n"
                                                 "Right-Click Shortcut: Toggle Variety Mode"),
                                      right_click=_rc.get("queue"))

    def show_bonus_menu(event=None):
        _open_toolbar_menu("bonus", bonus_menu_button, "bonus")

    global bonus_menu_button
    bonus_menu_button = create_button(first_row_frame, "BONUS▾", show_bonus_menu, True,
                                      help_text=("Start bonus questions for the current theme.\n"
                                                 "Right-Click Shortcut: Multiple Choice"),
                                      right_click=_rc.get("bonus"))

    def show_popup_menu(event=None):
        _open_toolbar_menu("information", popup_menu_button, "information")

    global popup_menu_button
    popup_menu_button = create_button(first_row_frame, "INFORMATION▾", show_popup_menu, True,
                                      help_text=("Popup information and the end session screen.\n"
                                                 "Right-Click Shortcut: Show Information Popup"),
                                      right_click=_rc.get("information"))

    def show_theme_menu(event=None):
        _open_toolbar_menu("theme", theme_menu_button, "theme")

    global theme_menu_button
    theme_menu_button = create_button(first_row_frame, "THEME▾", show_theme_menu, True,
                                      help_text=("Options related to current theme including marking, fetching data, and more.\n"
                                                 "Right-Click Shortcut: Tag/untag theme"),
                                      right_click=_rc.get("theme"))

    def show_toggle_menu(event=None):
        _open_toolbar_menu("toggles", toggle_menu_button, "toggles")

    global toggle_menu_button
    toggle_menu_button = create_button(first_row_frame, "TOGGLES▾", show_toggle_menu, True,
                                       help_text=("Various system toggles.\n"
                                                  "Right-Click Shortcut: Toggle Keyboard Shortcuts"),
                                       right_click=_rc.get("toggles"))

    if playlist.get("infinite", False):
        global selected_difficulty
        selected_difficulty = tk.StringVar()
        selected_difficulty.set(difficulty_options[playlist["difficulty"]])
        global difficulty_dropdown
        # Destroy any previous instance — parented to root so it won't be caught
        # by the first_row_frame.winfo_children() destroy loop (avoiding TclError)
        try:
            if difficulty_dropdown.winfo_exists():
                difficulty_dropdown.destroy()
        except Exception:
            pass
        difficulty_dropdown = ttk.Combobox(root,
                                values=difficulty_options,
                                textvariable=selected_difficulty,
                                width=17,
                                height=len(difficulty_options),
                                state="readonly",
                                style="Black.TCombobox",
                                font=ROOT_FONT)
        # Not packed/displayed — difficulty is selected via PLAYLIST▾ menu
        difficulty_dropdown.bind("<<ComboboxSelected>>", select_difficulty)

        if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
            popout_buttons_by_name.get("DIFFICULTY DROPDOWN").grid()
        if popout_buttons_by_name.get("SEARCH QUEUE"):
            popout_buttons_by_name.get("SEARCH QUEUE").config(text="ADD NEXT")
    else:
        if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
            popout_buttons_by_name.get("DIFFICULTY DROPDOWN").grid_remove()
        if popout_buttons_by_name.get("SEARCH QUEUE"):
            popout_buttons_by_name.get("SEARCH QUEUE").config(text="QUEUE NEXT")
    
    global search_button, add_search_button, search_bar_entry, directory_menu_button

    def show_directory_menu(event=None):
        _open_toolbar_menu("directory", directory_menu_button, "directory")
    directory_menu_button = create_button(first_row_frame, "DIRECTORY▾", show_directory_menu, True,
                                help_text=("Browse themes grouped by different parameters.\n\n"
                                           "Right-Click Shortcut: Toggle Censor Bars"),
                                right_click=_rc.get("directory"))

    search_bar_entry = tk.Entry(
        first_row_frame,
        bg="black",
        fg="gray50",
        insertbackground="white",
        font=ROOT_FONT,
        relief="flat",
        highlightthickness=scl(1, "UI"),
        highlightcolor="gray40",
        highlightbackground="gray25",
    )
    search_bar_entry.insert(0, SEARCH_BAR_PLACEHOLDER)
    search_bar_entry.pack(side="left", fill="x", expand=True, padx=(scl(4, "UI"), 0), pady=scl(0, "UI"))
    search_ops.search_bar_entry = search_bar_entry

    def on_search_focus_in(event=None):
        global popout_searching
        popout_searching = True
        if search_bar_entry.get() == SEARCH_BAR_PLACEHOLDER:
            search_bar_entry.delete(0, tk.END)
            search_bar_entry.configure(fg="white")

    def on_search_focus_out(event=None):
        global popout_searching
        popout_searching = False
        if not search_bar_entry.get().strip():
            search_bar_entry.delete(0, tk.END)
            search_bar_entry.insert(0, SEARCH_BAR_PLACEHOLDER)
            search_bar_entry.configure(fg="gray50")

    _search_debounce = [None]

    def on_search_key_release(event=None):
        if event and event.keysym in ("Escape", "Return", "Tab"):
            return
        current_text = search_bar_entry.get()
        if current_text == SEARCH_BAR_PLACEHOLDER:
            return
        if search_ops.search_term == current_text:
            return
        search_ops.search_term = current_text
        if not current_text:
            if list_loaded in ["search", "search_add"]:
                _close_list(right_column, keep_focus=True)
            return
        # Debounce: cancel any pending search and schedule a new one
        if _search_debounce[0]:
            root.after_cancel(_search_debounce[0])
        _search_debounce[0] = root.after(200, lambda: search(update=True, ask=False, add=playlist.get("infinite", False)))

    def on_search_return(event=None):
        list_select()

    def on_search_escape(event=None):
        search_ops.search_term = ""
        search_bar_entry.delete(0, tk.END)
        search_bar_entry.insert(0, SEARCH_BAR_PLACEHOLDER)
        search_bar_entry.configure(fg="gray50")
        root.focus()
        if list_loaded in ["search", "search_add"]:
            _close_list(right_column)

    search_bar_entry.bind("<FocusIn>", on_search_focus_in)
    search_bar_entry.bind("<FocusOut>", on_search_focus_out)
    search_bar_entry.bind("<KeyRelease>", on_search_key_release)
    search_bar_entry.bind("<Return>", on_search_return)
    search_bar_entry.bind("<Escape>", on_search_escape)
    ToolTip(search_bar_entry,
            "Search themes by title, filename, artist, and song name.\n\n"
            "Click themes to queue next, right-click to add to the playlist.")

    search_button = search_bar_entry
    add_search_button = None

# Hidden state-tracking buttons (lightning round) and dropdowns

# Define the Lightning Round modes and their metadata
light_mode_options = [
    (key, f"{mode['icon']} {key.upper()}")
    for key, mode in light_modes.items()
    if key != "variety"
]

# Mapping from display string ("ICON NAME") back to the key
title_to_key = {display: key for key, display in light_mode_options}

selected_mode = StringVar(value=light_mode_options[0][1])  # default to first display string

style = ttk.Style()
style.theme_use('clam')
def configure_style():
    style.configure("Black.TCombobox",
                    fieldbackground="black",   # background of selected value
                    background="black",        # dropdown arrow area
                    foreground="white",        # text color
                    arrowcolor="white",        # arrow color
                    justify='center')        

    # Also style the readonly state explicitly
    style.map("Black.TCombobox",
        fieldbackground=[('readonly', 'black')],
        foreground=[('readonly', 'white')]
    )
configure_style()
def unhighlight_selection(event, setting=False):
    if popout_buttons_by_name.get("LIGHTNING DROPDOWN"):
        popout_buttons_by_name["LIGHTNING DROPDOWN"].set(selected_mode.get())
    if not setting and light_mode:
        select_lightning_mode()

# Start button using selected mode
def select_lightning_mode():
    selected_display = selected_mode.get()
    mode_key = title_to_key[selected_display]
    toggle_light_mode(mode_key)

info_panel = tk.Frame(root, bg="black")
info_panel.pack(fill="both", expand=True, padx=scl(10, "UI"), pady=scl(5, "UI"))

# Left Column
left_column = tk.Text(info_panel, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                      insertbackground="white", state=tk.DISABLED,
                      selectbackground=HIGHLIGHT_COLOR, wrap="word")
left_column.pack(side="left", fill="both", expand=True)

# Middle Column
middle_column = tk.Text(info_panel, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                        insertbackground="white", state=tk.DISABLED,
                        selectbackground=HIGHLIGHT_COLOR, wrap="word")
middle_column.pack(side="left", fill="both", expand=True)

right_column_container = tk.Frame(info_panel, bg="black")
right_column_container.pack(side="left", fill="both", expand=True)

# Top Shorter Column (e.g., header, stats, etc.)
right_top = tk.Text(right_column_container, height=0, width=scl(40, "UI"), bg="black", fg="white",
                    insertbackground="white", state=tk.DISABLED,
                    selectbackground=HIGHLIGHT_COLOR, wrap="word")
right_top.pack(fill="x")

# List title header — shown/hidden by _insert_list_title_row, fills full column width
_header_font = font.Font(family="Consolas", size=scl(11, "UI"), weight="bold", underline=True)
list_header_font = _header_font  # expose as global for _truncate_header_title
right_column_header = tk.Frame(right_column_container, bg=BACKGROUND_COLOR)
right_column_back_button = tk.Button(right_column_header, text="\u2190", bg=BACKGROUND_COLOR, fg=BACKGROUND_COLOR,
                                      font=_header_font, borderwidth=0, pady=0,
                                      command=_go_back_list)
right_column_back_button.pack(side="left")  # always packed; visibility toggled via fg color
right_column_header_label = tk.Label(right_column_header, text="", bg=BACKGROUND_COLOR, fg="white",
                                      font=_header_font, anchor="center", justify="center")
right_column_header_label.pack(side="left", fill="x", expand=True)
tk.Button(right_column_header, text="\u2715", bg=BACKGROUND_COLOR, fg="white",
          font=_header_font, borderwidth=0, pady=0,
          command=lambda: _close_list(right_column)).pack(side="right")
# <Configure> is intentionally bound to right_column (below), not right_column_header,
# so that changing the label text inside the header never re-triggers truncation.
# Not packed yet — _insert_list_title_row shows/hides it before right_column_row

# Main Right Column (with custom canvas scrollbar)
right_column_row = tk.Frame(right_column_container, bg="black")
right_column_row.pack(fill="both", expand=True)

# Build a fully styled scrollbar by borrowing clam elements (native tk.Scrollbar ignores colors on Windows)
_sb_style = ttk.Style()
_sb_style.element_create("List.trough", "from", "clam")
_sb_style.element_create("List.thumb", "from", "clam")
_sb_style.element_create("List.uparrow", "from", "clam")
_sb_style.element_create("List.downarrow", "from", "clam")
_sb_style.layout("List.Vertical.TScrollbar", [
    ("List.trough", {"sticky": "ns", "children": [
        ("List.uparrow",   {"side": "top",    "sticky": ""}),
        ("List.downarrow", {"side": "bottom", "sticky": ""}),
        ("List.thumb",     {"unit": "1",      "sticky": "nswe"}),
    ]})
])
_sb_style.configure("List.Vertical.TScrollbar",
    background="gray38", troughcolor="gray15",
    arrowcolor="gray65", borderwidth=0,
    gripcount=0, arrowsize=scl(13, "UI"))
_sb_style.map("List.Vertical.TScrollbar",
    background=[("active", "gray58"), ("pressed", "gray68")])

right_column_scrollbar = ttk.Scrollbar(right_column_row, orient="vertical",
                                        command=on_list_scrollbar_set,
                                        style="List.Vertical.TScrollbar")
# Not packed initially — update_list_scrollbar shows/hides it as needed
right_column = tk.Text(right_column_row, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                       insertbackground="white", state=tk.DISABLED,
                       selectbackground=HIGHLIGHT_COLOR, wrap="word",
                       spacing1=0, spacing2=0, spacing3=0)
right_column.pack(side="left", fill="both", expand=True)
# Bind truncation to right_column so that header-label text changes never
# feed back into more Configure events (right_column is our width reference anyway).
right_column.bind("<Configure>", _truncate_header_title)

# Expose the core long-lived widgets on the shared state container so
# extracted modules can read them via `state.widgets.*` instead of
# receiving them through set_context (see core/game_state.py).
state.widgets.root = root
state.widgets.player = player
state.widgets.left_column = left_column
state.widgets.middle_column = middle_column
state.widgets.right_column = right_column
youtube_ui.set_context(
    get_youtube_queue=lambda: youtube_queue,
    set_youtube_queue=lambda value: globals().update(youtube_queue=value),
    youtube_metadata=youtube_metadata,
    get_playlist=lambda: playlist,
    show_list=show_list,
    get_right_column=lambda: right_column,
    stream_icon=stream_icon,
    load_pil_image_from_url=load_pil_image_from_url,
    format_seconds=format_seconds,
    player=player,
    player_play=player_play,
    root=root,
    set_video_stopped=lambda value: globals().update(video_stopped=value),
    toggle_coming_up_popup=toggle_coming_up_popup,
    play_video=play_video,
    up_next_text=up_next_text,
    get_popout_buttons_by_name=lambda: popout_buttons_by_name,
    button_selected=button_seleted,
    bonus=bonus,
    get_currently_playing=lambda: currently_playing,
    censors=censors,
    get_left_column=lambda: left_column,
    get_middle_column=lambda: middle_column,
    get_popout_currently_playing=lambda: popout_currently_playing,
    update_popout_currently_playing=update_popout_currently_playling,
    web_server=web_server,
)

tutorial.set_action_context(
    root=root,
    bg_color=BACKGROUND_COLOR,
    hl_color=HIGHLIGHT_COLOR,
    root_font=ROOT_FONT,
    scl=scl,
    get_window_pos=get_window_position_and_setup,
    get_tutorial_shown=lambda: tutorial_shown,
    set_tutorial_shown=lambda value: globals().update(tutorial_shown=value),
    save_config=save_config,
)

popout_layout_editor.set_context(
    flat_registry=get_flat_registry,
    menu_registry=_get_menu_registry,
    save_config_fn=save_config,
    create_popout_controls_fn=create_popout_controls,
    save_preset_fn=_save_popout_layout_preset,
    load_presets_fn=_load_popout_layout_presets,
    get_popout_layout=lambda: globals().get('popout_layout'),
    set_popout_layout=lambda v: globals().update(popout_layout=v),
    get_popout_columns=lambda: globals().get('popout_columns'),
    set_popout_columns=lambda v: globals().update(popout_columns=v),
    get_popout_controls=lambda: globals().get('popout_controls'),
    set_popout_controls=lambda v: globals().update(popout_controls=v),
    popout_layout_default=POPOUT_LAYOUT_DEFAULT,
    root_font=ROOT_FONT,
    menu_font=MENU_FONT,
    background_color=BACKGROUND_COLOR,
    highlight_color=HIGHLIGHT_COLOR,
)
metadata_import.set_context(
    get_window_position_and_setup=get_window_position_and_setup,
    save_metadata=save_metadata,
    load_metadata=load_metadata,
    scan_directory=scan_directory,
    show_playlist=show_playlist,
    save_config=save_config,
    file_metadata=file_metadata,
    file_metadata_overrides=file_metadata_overrides,
    anime_metadata=anime_metadata,
    anidb_metadata=anidb_metadata,
    ai_metadata=ai_metadata,
    anilist_metadata=anilist_metadata,
    main_globals=globals(),
)
clues_overlay.set_context(
    get_ass_font=_get_ass_font,
    get_format=get_format,
    currently_playing=currently_playing,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
)
emoji_overlay.set_context(
    currently_playing=currently_playing,
    ai_metadata=ai_metadata,
    get_display_title=get_display_title,
    extract_response_text=extract_response_text,
    save_metadata=save_metadata,
    get_ass_font=_get_ass_font,
    get_mpv_window_rect=_get_mpv_window_rect,
    get_openai_api_key=lambda: OPENAI_API_KEY,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
)
song_overlay.set_context(
    currently_playing=currently_playing,
    format_slug=format_slug,
    get_song_string=get_song_string,
    get_ass_font=_get_ass_font,
    wall_time=_wall_time,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
)
synopsis_overlay.set_context(
    currently_playing=currently_playing,
    get_mpv_window_rect=_get_mpv_window_rect,
    osd_command=_osd_command,
    color_str_to_ass_bgr=_color_str_to_ass_bgr,
    synopsis_ass_osd_id=_SYNOPSIS_ASS_OSD_ID,
    get_fixed_current_round=lambda: fixed_current_round,
    get_light_round_length=lambda: light_round_length,
    get_display_screen_width=lambda: DISPLAY_SCREEN_WIDTH,
    get_display_screen_height=lambda: DISPLAY_SCREEN_HEIGHT,
    get_middle_overlay_background_color=lambda: MIDDLE_OVERLAY_BACKGROUND_COLOR,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
)
title_overlay.set_context(
    currently_playing=currently_playing,
    scl=scl,
    get_title_text_lines=get_title_text_lines,
    get_mpv_window_rect=_get_mpv_window_rect,
    get_ass_font=_get_ass_font,
    get_courier_font=_get_courier_font,
    get_title_light_string_value=lambda: title_light_string,
    get_title_light_letters=lambda: title_light_letters,
    get_character_round_answer=lambda: character_round_answer,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
    get_inverse_overlay_background_color=lambda: INVERSE_OVERLAY_BACKGROUND_COLOR,
    get_inverse_overlay_text_color=lambda: INVERSE_OVERLAY_TEXT_COLOR,
)
scramble_overlay.set_context(
    get_mpv_window_rect=_get_mpv_window_rect,
    get_ass_font=_get_ass_font,
    get_courier_font=_get_courier_font,
    get_character_round_answer=lambda: character_round_answer,
    get_fixed_current_round=lambda: fixed_current_round,
)
swap_overlay.set_context(
    get_mpv_window_rect=_get_mpv_window_rect,
    get_ass_font=_get_ass_font,
    get_courier_font=_get_courier_font,
    get_character_round_answer=lambda: character_round_answer,
)
peek_overlay.set_context(
    osd_command=_osd_command,
    get_effective_video_rect=_get_effective_video_rect,
)
edge_overlay.set_context(
    osd_command=_osd_command,
    get_effective_video_rect=_get_effective_video_rect,
)
grow_overlay.set_context(
    osd_command=_osd_command,
    get_effective_video_rect=_get_effective_video_rect,
)
filter_overlay.set_context(
    bottom_info=bottom_info,
    get_character_round_answer=lambda: character_round_answer,
)
peek_dispatch.set_context(
    send_scoreboard_command=send_scoreboard_command,
    set_black_screen=set_black_screen,
    set_progress_overlay=set_progress_overlay,
    refresh_popout_toggles=_refresh_popout_toggles,
    toggle_blind_round=toggle_blind_round,
    toggle_coming_up_popup=toggle_coming_up_popup,
    toggle_mute=toggle_mute,
    main_globals=globals(),
)
profile_overlay.set_context(
    get_ass_font=_get_ass_font,
    get_character_round_answer=lambda: character_round_answer,
    get_inverse_overlay_background_color=lambda: INVERSE_OVERLAY_BACKGROUND_COLOR,
    get_inverse_overlay_text_color=lambda: INVERSE_OVERLAY_TEXT_COLOR,
)
tag_cloud_overlay.set_context(
    osd_command=_osd_command,
    get_tags=get_tags,
    color_str_to_ass_bgr=_color_str_to_ass_bgr,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
)
episode_overlay.set_context(
    osd_command=_osd_command,
    color_str_to_ass_bgr=_color_str_to_ass_bgr,
    ass_wrap_text=_ass_wrap_text,
    get_base_title=get_base_title,
    get_fixed_current_round=lambda: fixed_current_round,
    get_overlay_text_color=lambda: OVERLAY_TEXT_COLOR,
    get_overlay_background_color=lambda: OVERLAY_BACKGROUND_COLOR,
)
characters_overlay.set_context(
    load_image_from_url=load_image_from_url,
)
cover_image_overlay.set_context(
    get_display_title=get_display_title,
    get_base_title=get_base_title,
    get_serpapi_key=lambda: SERPAPI_KEY,
    get_fixed_current_round=lambda: fixed_current_round,
)
character_parts_overlay.set_context(
    load_image_from_url=load_image_from_url,
    scl=scl,
    main_globals=globals(),
)
image_reveal_overlays.set_context(
    scl=scl,
    get_character_round_answer=lambda: character_round_answer,
    get_fixed_current_round=lambda: fixed_current_round,
)
lightning_manager.set_context(
    main_globals=globals(),
    main_module=sys.modules[__name__],
    toggle_coming_up_popup=toggle_coming_up_popup,
    configure_style=configure_style,
    unhighlight_selection=unhighlight_selection,
    queue_next_lightning_mode=queue_next_lightning_mode,
    get_file_censors=get_file_censors,
    selected_mode=selected_mode,
    set_progress_overlay=set_progress_overlay,
    get_light_progress_bar=progress_overlay_ops.is_light_progress_bar_active,
    spawn_pulsating_music_note=spawn_pulsating_music_note,
    toggle_outer_edge_overlay=toggle_outer_edge_overlay,
    stop_stream=stop_stream,
    toggle_mute=toggle_mute,
    set_video_frame=set_video_frame,
    send_scoreboard_command=send_scoreboard_command,
    bottom_info=bottom_info,
    top_info=top_info,
)
metadata_panel.set_context(
    scl_fn=scl,
    get_file_path_fn=get_file_path,
    add_single_data_line_fn=add_single_data_line,
    show_youtube_playlist_fn=show_youtube_playlist,
    load_image_from_url_fn=load_image_from_url,
    insert_list_title_row_fn=_insert_list_title_row,
    select_extra_metadata_fn=select_extra_metadata,
    toggle_spoiler_tags_fn=toggle_spoiler_tags,
    download_animethemes_file_fn=download_animethemes_file,
    move_cached_file_to_directory_fn=move_cached_file_to_directory,
    load_random_clips_fn=load_random_clips,
    stream_clip_fn=stream_clip,
    reset_metadata_fn=reset_metadata,
    play_name_key_fn=_play_name_key,
    build_web_series_themes_fn=_build_web_series_themes,
    calc_plays_info_fn=_calc_plays_info,
    fmt_plays_fn=_fmt_plays,
    get_all_theme_from_series_fn=get_all_theme_from_series,
    play_video_from_filename_fn=play_video_from_filename,
    save_metadata_fn=save_metadata,
    save_metadata_overrides_fn=save_metadata_overrides,
    get_theme_filename_fn=get_theme_filename,
    get_theme_filenames_fn=get_theme_filenames,
    get_filenames_from_artist_fn=get_filenames_from_artist,
    is_animethemes_stream_file_fn=is_animethemes_stream_file,
    stream_icon_val=stream_icon,
    get_display_title_fn=get_display_title,
    safe_int_fn=_safe_int,
    is_game_fn=is_game,
    add_field_total_button_fn=add_field_total_button,
    get_all_matching_field_fn=get_all_matching_field,
    get_filenames_from_studio_fn=get_filenames_from_studio,
    add_multiple_data_line_fn=add_multiple_data_line,
    overall_theme_num_display_fn=overall_theme_num_display,
    get_version_flags_fn=_get_version_flags,
    get_file_marks_fn=get_file_marks,
    toggleColumnEdit_fn=toggleColumnEdit,
    get_artist_themes_data_fn=get_artist_themes_data,
    get_studio_entries_data_fn=get_studio_entries_data,
    get_format_fn=get_format,
    get_episode_display_fn=get_episode_display,
    shorten_platform_fn=_shorten_platform,
    get_tags_string_fn=get_tags_string,
    get_tags_fn=get_tags,
    get_song_string_fn=get_song_string,
    push_web_marks_fn=_push_web_marks,
    check_favorited_fn=check_favorited,
    get_file_props_label_fn=get_file_props_label,
    get_current_list_title=lambda: globals().get('current_list_title'),
    set_current_list_title=lambda v: globals().update(current_list_title=v),
    get_list_loaded=lambda: globals().get('list_loaded'),
    get_selected_extra_metadata=lambda: globals().get('selected_extra_metadata'),
    get_show_spoiler_tags=lambda: globals().get('show_spoiler_tags'),
    get_youtube_api_key=lambda: globals().get('YOUTUBE_API_KEY'),
    get_popout_currently_playing=lambda: globals().get('popout_currently_playing'),
    get_popout_currently_playing_extra=lambda: globals().get('popout_currently_playing_extra'),
    get_popout_show_metadata=lambda: globals().get('popout_show_metadata'),
    get_popout_show_currently_playing=lambda: globals().get('popout_show_currently_playing'),
    get_youtube_queue=lambda: globals().get('youtube_queue'),
    set_updating_metadata=lambda v: globals().update(updating_metadata=v),
    lists_to_close=LISTS_TO_CLOSE,
    highlight_color=HIGHLIGHT_COLOR,
)
shortcut_editor.set_context(
    get_window_position_and_setup=get_window_position_and_setup,
    get_menu_registry=_get_menu_registry,
    get_flat_registry=get_flat_registry,
    shortcut_display_name=_shortcut_display_name,
    bind_shortcuts=bind_shortcuts,
    rebuild_shortcut_dispatch=rebuild_shortcut_dispatch,
    save_config=save_config,
    get_shortcuts_config=lambda: shortcuts_config,
    set_shortcuts_config=lambda v: globals().update(shortcuts_config=v),
    background_color=BACKGROUND_COLOR,
    default_shortcuts=DEFAULT_SHORTCUTS,
    fixed_shortcuts=FIXED_SHORTCUTS,
    scl=scl,
)
settings_popup.set_context(
    get_window_position_and_setup=get_window_position_and_setup,
    get_available_rules_files=get_available_rules_files,
    load_config=load_config,
    save_config=save_config,
    ToolTip=ToolTip,
    background_color=BACKGROUND_COLOR,
    overlay_color_options=OVERLAY_COLOR_OPTIONS,
    settings_schema=SETTINGS_SCHEMA,
    cloudflared_available=CLOUDFLARED_AVAILABLE,
    ngrok_available=NGROK_AVAILABLE,
    main_globals=globals(),
)
show_settings_popup = settings_popup.show_settings_popup
popout_window.set_context(
    w=lambda name, value: globals().update({name: value}) or value,
    button_seleted_fn=button_seleted,
    get_window_position_and_setup_fn=get_window_position_and_setup,
    adjust_up_next_height_fn=adjust_up_next_height,
    toggle_show_popout_currently_playing_fn=toggle_show_popout_currently_playing,
    toggle_show_popout_up_next_fn=toggle_show_popout_up_next,
    toggle_show_popout_metadata_fn=toggle_show_popout_metadata,
    refresh_popout_toggles_fn=_refresh_popout_toggles,
    update_popout_currently_playling_fn=update_popout_currently_playling,
    up_next_text_fn=up_next_text,
    select_lightning_mode_fn=select_lightning_mode,
    select_difficulty_fn=select_difficulty,
    show_youtube_playlist_fn=show_youtube_playlist,
    load_youtube_video_fn=load_youtube_video,
    search_playlist_fn=search_playlist,
    get_title_fn=get_title,
    add_search_playlist_fn=add_search_playlist,
    set_search_queue_fn=set_search_queue,
    get_flat_registry_fn=get_flat_registry,
    get_popout_show_metadata=lambda: globals().get('popout_show_metadata'),
    get_popout_layout=lambda: globals().get('popout_layout'),
    get_popout_columns=lambda: globals().get('popout_columns'),
    get_popout_controls_button=lambda: globals().get('popout_controls_button'),
    get_light_mode_options=lambda: globals().get('light_mode_options'),
    get_selected_mode=lambda: globals().get('selected_mode'),
    get_light_mode=lambda: globals().get('light_mode'),
    get_difficulty_options=lambda: globals().get('difficulty_options'),
    get_difficulty_dropdown=lambda: globals().get('difficulty_dropdown'),
    get_youtube_queue=lambda: globals().get('youtube_queue'),
    get_youtube_playlist=lambda: globals().get('_youtube_playlist'),
    popout_search_default=POPOUT_SEARCH_DEFAULT,
    popout_layout_default=POPOUT_LAYOUT_DEFAULT,
    background_color=BACKGROUND_COLOR,
    highlight_color=HIGHLIGHT_COLOR,
)
playlist_ops.set_context(
    root=root,
    player=player,
    right_column=right_column,
    get_filename_to_mal=lambda: metadata_fetch.filename_to_mal,
    get_list_loaded=lambda: list_loaded,
    get_light_mode=lambda: light_mode,
    get_popout_controls=lambda: popout_controls,
    get_difficulty_dropdown=lambda: difficulty_dropdown,
    get_selected_difficulty=lambda: selected_difficulty,
    get_metadata=get_metadata,
    get_clean_filename=get_clean_filename,
    get_file_metadata_by_name=get_file_metadata_by_name,
    get_tags=get_tags,
    get_file_censors=get_file_censors,
    get_format=get_format,
    is_game=is_game,
    is_animethemes_stream_file=is_animethemes_stream_file,
    is_downloading=cache_download.is_downloading,
    series_overlap=series_overlap,
    series_primary=series_primary,
    series_list=series_list,
    series_set=series_set,
    series_cache_key=series_cache_key,
    get_series_popularity=get_series_popularity,
    get_op_ed_counts=get_op_ed_counts,
    play_name_key=_play_name_key,
    get_version_from_filename=get_version_from_filename,
    check_theme=check_theme,
    prioritize_theme_files=prioritize_theme_files,
    aired_to_season_year=aired_to_season_year,
    fetch_anilist_user_ids=fetch_anilist_user_ids,
    get_saved_playlist=get_playlist,
    update_current_index=update_current_index,
    update_playlist_name=update_playlist_name,
    show_playlist=show_playlist,
    show_list=show_list,
    notify_playlist_list_updated=_notify_playlist_list_updated,
    save_config=save_config,
    save_metadata=save_metadata,
    up_next_text=up_next_text,
    prefetch_next_themes=prefetch_next_themes,
    queue_next_lightning_mode=queue_next_lightning_mode,
    stop=stop,
    download_to_cache=cache_download.download_to_cache,
    cancel_download=cancel_download,
    check_missing_artists=check_missing_artists,
    build_filename_to_mal_map=build_filename_to_mal_map,
    update_extra_metadata=update_extra_metadata,
    update_metadata=update_metadata,
    refresh_popout_toggles=_refresh_popout_toggles,
    get_current_session_lightning_tracks=get_current_session_lightning_tracks,
    playlists_folder=PLAYLISTS_FOLDER,
    filters_folder=FILTERS_FOLDER,
    system_playlists=SYSTEM_PLAYLISTS,
    blank_playlist=BLANK_PLAYLIST,
    app_version=APP_VERSION,
    background_color=BACKGROUND_COLOR,
)

stats_ops.set_context(
    root=root,
    right_column=right_column,
    get_metadata=get_metadata,
    get_file_metadata_by_name=get_file_metadata_by_name,
    get_tags=get_tags,
    get_format=get_format,
    show_field_themes=show_field_themes,
    show_list=show_list,
    push_list_nav=push_list_nav,
    clear_list_nav=clear_list_nav,
)
stats_ops.set_action_context(
    get_deduplicated_files=playlist_ops.get_cached_deduplicated_files,
    get_anilist_metadata=lambda: anilist_metadata,
)

search_ops.set_context(
    root=root,
    right_column=right_column,
    get_disable_shortcuts=lambda: disable_shortcuts,
    show_list=show_list,
    theme_context_menu=_theme_context_menu,
    get_title=get_title,
    up_next_text=up_next_text,
    prefetch_next_themes=prefetch_next_themes,
    save_config=save_config,
    play_video=play_video,
    player=player,
    get_song_string=get_song_string,
    get_metadata=get_metadata,
    get_directory_files=playlist_ops.get_directory_files,
    deduplicate_theme_versions=playlist_ops.deduplicate_theme_versions,
)

def _set_cached_pop_time_group(v):
    global cached_pop_time_group
    cached_pop_time_group = v

def _set_series_cooldowns_cache(v):
    global series_cooldowns_cache
    series_cooldowns_cache = v

metadata_fetch.set_context(
    # metadata-cluster dicts are read directly from state.metadata.* now
    get_directory=lambda: directory,
    get_light_mode=lambda: light_mode,
    get_updating_metadata=lambda: updating_metadata,
    get_variety_light_mode=lambda: variety_round.variety_light_mode_enabled,
    get_auto_refresh_toggle=lambda: auto_refresh_toggle,
    set_cached_pop_time_group=_set_cached_pop_time_group,
    set_series_cooldowns_cache=_set_series_cooldowns_cache,
    deep_merge_fn=deep_merge,
    estimate_manual_popularity_fn=estimate_manual_popularity,
    estimate_manual_rank_fn=estimate_manual_rank,
    extract_youtube_id_from_trailer_fn=extract_youtube_id_from_trailer,
    get_clean_filename_fn=get_clean_filename,
    get_file_path_fn=get_file_path,
    get_filenames_from_artist_fn=get_filenames_from_artist,
    is_ffmpeg_available_fn=is_ffmpeg_available,
    queue_next_lightning_mode_fn=queue_next_lightning_mode,
    save_metadata_fn=save_metadata,
    scan_directory_fn=scan_directory,
    toggle_theme_fn=toggle_theme,
    update_metadata_fn=update_metadata,
    update_metadata_queue_fn=update_metadata_queue,
    anilist_metadata_file=ANILIST_METADATA_FILE,
    review_modifier=REVIEW_MODIFIER,
    main_module=sys.modules[__name__],
)

right_column.bind("<B1-Motion>", lambda e: handle_drag_motion(e) if drag_start_index is not None else None)
right_column.bind("<ButtonRelease-1>", lambda e: end_playlist_drag(e) if drag_start_index is not None else None)

def handle_list_scroll(event):
    if list_loaded:
        if hasattr(event, 'delta') and event.delta > 0:  # Scroll up
            list_scroll_up()
        elif hasattr(event, 'delta') and event.delta < 0:  # Scroll down
            list_scroll_down()
        return "break"  # Prevent default scrolling behavior
    return None

def handle_btn_scroll_up(e):
    if list_loaded:
        list_scroll_up()
        return "break"
    return None

def handle_btn_scroll_down(e):
    if list_loaded:
        list_scroll_down()
        return "break"
    return None

right_column.bind("<MouseWheel>", handle_list_scroll)
right_column.bind("<Button-4>", lambda e: handle_btn_scroll_up(e))  # Linux scroll up
right_column.bind("<Button-5>", lambda e: handle_btn_scroll_down(e))  # Linux scroll down

# Video controls
controls_frame = tk.Frame(root, bg="black")
controls_frame.pack(pady=0, fill="x", expand=False)
controls_frame.pack_propagate(False)  # Prevent children from controlling frame size
controls_frame.configure(height=scl(80, "UI"))  # Set fixed height for controls

def update_volume_display():
    """Update the volume label display."""
    volume_label.config(text=str(state.controls.volume_level))

set_volume = audio_toggles.set_volume
increase_volume = audio_toggles.increase_volume
decrease_volume = audio_toggles.decrease_volume
increase_volume_small = audio_toggles.increase_volume_small
decrease_volume_small = audio_toggles.decrease_volume_small

audio_toggles.set_context(
    player=player,
    pygame=pygame,
    get_light_mode=lambda: light_mode,
    get_light_round_started=lambda: light_round_started,
    update_volume_display=update_volume_display,
    play_background_music=play_background_music,
    streaming=streaming,
    music=music,
    get_fixed_current_round=lambda: fixed_current_round,
    sync_legacy_globals=_sync_control_globals,
)

music.set_context(
    set_floating_text=set_floating_text,
    set_volume=set_volume,
    is_peek_active=is_peek_active,
    get_fixed_current_round=lambda: fixed_current_round,
    get_light_mode=lambda: light_mode,
    get_light_round_started=lambda: light_round_started,
    get_character_round_answer=lambda: character_round_answer,
    light_round_length_default=LIGHT_ROUND_LENGTH_DEFAULT,
)

# Volume control container
volume_container = tk.Frame(controls_frame, bg="black", highlightbackground="white", highlightthickness=2, padx=2, pady=2)
volume_container.pack(side="left", padx=(scl(10, "UI"), scl(5, "UI")))

# Left side: icon and number
volume_left_frame = tk.Frame(volume_container, bg="black")
volume_left_frame.pack(side="left", padx=(2, 0))

# Volume icon
volume_icon = tk.Label(volume_left_frame, text="🔊", bg="black", fg="white", 
                        font=("Arial", scl(12, "UI"), "bold"), pady=0)
volume_icon.pack(pady=0)

# Volume label (displays current volume)
volume_label = tk.Label(volume_left_frame, text=str(state.controls.volume_level), bg="black", fg="white",
                         font=("Arial", scl(14, "UI"), "bold"), width=3, pady=0)
volume_label.pack(pady=0)

# Right side: buttons
volume_buttons_frame = tk.Frame(volume_container, bg="black")
volume_buttons_frame.pack(side="left", padx=(0, 2))

# Volume up button
volume_up_button = tk.Button(volume_buttons_frame, text="➕", command=increase_volume, bg="black", fg="white", 
                              font=("Arial", scl(12, "UI"), "bold"), border=0, width=2, height=1, pady=0)
volume_up_button.pack(pady=0)
volume_up_button.bind("<Button-3>", increase_volume_small)

# Volume down button
volume_down_button = tk.Button(volume_buttons_frame, text="➖", command=decrease_volume, bg="black", fg="white", 
                                font=("Arial", scl(12, "UI"), "bold"), border=0, width=2, height=1, pady=0)
volume_down_button.pack(pady=0)
volume_down_button.bind("<Button-3>", decrease_volume_small)

play_pause_button = tk.Button(controls_frame, text="⏯", command=play_pause, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
play_pause_button.pack(side="left", padx=0)

stop_button = tk.Button(controls_frame, text="⏹", command=stop, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
stop_button.pack(side="left", padx=0)

previous_button = tk.Button(controls_frame, text="⏮", command=play_previous, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
previous_button.pack(side="left", padx=0)

next_button = tk.Button(controls_frame, text="⏭", command=play_next, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
next_button.pack(side="left", padx=0)
def _next_btn_right_click(e):
    root.after(0, lambda: _invoke_registry_by_id("skip_to_end_ff"))
next_button.bind("<Button-3>", _next_btn_right_click)

# load_config() already ran and may have set these legacy globals; migrate them
# into state.controls and keep compatibility globals in sync during the transition.
state.controls.autoplay_toggle = globals().get("autoplay_toggle", state.controls.autoplay_toggle)
state.controls.autoplay_fullscreen = globals().get("autoplay_fullscreen", state.controls.autoplay_fullscreen)
state.controls.mpv_always_on_top = globals().get("mpv_always_on_top", state.controls.mpv_always_on_top)
state.controls.special_repeat_track_mode = globals().get(
    "special_repeat_track_mode",
    state.controls.special_repeat_track_mode,
)
_sync_control_globals()
toggle_mpv_always_on_top = autoplay_toggles.toggle_mpv_always_on_top
toggle_autoplay_fullscreen = autoplay_toggles.toggle_autoplay_fullscreen
_update_autoplay_button = autoplay_toggles.update_autoplay_button
set_autoplay_mode = autoplay_toggles.set_autoplay_mode
toggle_autoplay = autoplay_toggles.toggle_autoplay
show_autoplay_menu = autoplay_toggles.show_autoplay_menu
toggle_special_repeat = autoplay_toggles.toggle_special_repeat

autoplay_toggles.set_context(
    player=player,
    root=root,
    tk=tk,
    popup_menu=popup_menu,
    save_config=save_config,
    highlight_color=HIGHLIGHT_COLOR,
    sync_legacy_globals=_sync_control_globals,
    get_autoplay_button=lambda: autoplay_button,
)

autoplay_button = tk.Button(controls_frame, text="🔁", command=show_autoplay_menu, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2, anchor="center", justify="center")
autoplay_button.pack(side="left", padx=0, pady=(0,scl(15, "UI")))
autoplay_button.bind('<Button-3>', toggle_special_repeat)

# Seek bar
seek_bar = tk.Scale(controls_frame, from_=0, to=1000, orient=tk.HORIZONTAL, command=seek, length=2000, resolution=0.1, bg="black", fg="white")
seek_bar.pack(side="left", fill="x", padx=(scl(5, "UI"),scl(10, "UI")))

left_font_name = "Arial"
middle_font_name = "Arial"
right_font_name = "Arial"

# Text formatting tags
left_column.tag_configure("bold", font=(left_font_name, scl(12, "UI"), "bold"), foreground="white")
left_column.tag_configure("underline", underline=True)
middle_column.tag_configure("bold", font=(middle_font_name, scl(12, "UI"), "bold"), foreground="white")
middle_column.tag_configure("highlight", background="#333333", foreground="white", font=(middle_font_name, scl(12, "UI"), "bold"))  # Dark gray highlight
middle_column.tag_configure("underline", underline=True)
right_column.tag_configure("bold", font=(right_font_name, scl(12, "UI"), "bold"), foreground="white")
right_column.tag_configure("highlight", background=HIGHLIGHT_COLOR, foreground="white", font=(right_font_name, scl(12, "UI"), "bold"))  # Dark gray highlight
right_column.tag_configure("highlightreg", background=HIGHLIGHT_COLOR, foreground="white", font=(right_font_name, scl(12, "UI")))  # Dark gray highlight
right_column.tag_configure("underline", underline=True)
left_column.tag_configure("white", foreground="white", font=(left_font_name, scl(12, "UI")))
left_column.tag_configure("blank", foreground="white", font=(left_font_name, scl(3, "UI")))
middle_column.tag_configure("white", foreground="white", font=(middle_font_name, scl(12, "UI")))
middle_column.tag_configure("blank", foreground="white", font=(middle_font_name, scl(6, "UI")))
right_column.tag_configure("white", foreground="white", font=(right_font_name, scl(12, "UI")))
right_column.tag_configure("blank", foreground="white", font=(right_font_name, scl(6, "UI")))
right_top.tag_configure("bold", font=(right_font_name, scl(12, "UI"), "bold"), foreground="white")
right_top.tag_configure("white", foreground="white", font=(right_font_name, scl(12, "UI")))

shortcut_actions.set_context(
    light_modes=light_modes,
    get_light_mode=lambda: light_mode,
    toggle_light_mode=toggle_light_mode,
    peek_dispatch=peek_dispatch,
    get_blind_round_toggle=lambda: blind_screen.blind_round_toggle,
    toggle_blind_round=toggle_blind_round,
    toggle_peek_round=toggle_peek_round,
    toggle_mute_peek_round=toggle_mute_peek_round,
    bonus=bonus,
    guess_extra=guess_extra,
)
cycle_light_mode = shortcut_actions.cycle_light_mode
cycle_blind_peek = shortcut_actions.cycle_blind_peek
cycle_guess_stats = shortcut_actions.cycle_guess_stats
cycle_guess_other = shortcut_actions.cycle_guess_other

# =========================================
#            *KEYBOARD SHORTCUTS
# =========================================
# All runtime keyboard + mouse dispatch lives in
# _app_scripts/toggles/shortcut_dispatch.py. `disable_shortcuts` stays in main
# because many other sites read/toggle it; `_shortcut_dispatch` is built in
# main from the menu registry (see rebuild_shortcut_dispatch). The module
# reads both live via the `_main` module reference.

if 'disable_shortcuts' not in globals():
    disable_shortcuts = True

from _app_scripts.toggles import shortcut_dispatch
shortcut_dispatch.set_context(main_module=sys.modules[__name__])

toggle_disable_shortcuts = shortcut_dispatch.toggle_disable_shortcuts

on_press        = shortcut_dispatch.on_press
on_release      = shortcut_dispatch.on_release
on_mouse_click  = shortcut_dispatch.on_mouse_click
on_mouse_move   = shortcut_dispatch.on_mouse_move
on_mouse_scroll = shortcut_dispatch.on_mouse_scroll



# =========================================
#                *STARTUP
# =========================================

# Start keyboard listener
keyboard_listener = keyboard.Listener(
    on_press=on_press,
    on_release=on_release)
keyboard_listener.start()

# Start mouse listener
mouse_listener = mouse.Listener(
    on_click=on_mouse_click,
    on_move=on_mouse_move,
    on_scroll=on_mouse_scroll)
mouse_listener.start()

update_playlist_name()
update_current_index()
load_youtube_metadata()
load_metadata()
check_for_local_metadata_package()
root.after(3000, check_for_metadata_updates)  # Check for updates after 3 seconds
root.after(3000, check_for_censor_updates)  # Check for censor updates after 3 seconds

# =========================================
#         *WEB SERVER (BONUS ANSWERS) — see _app_scripts/bonus/answers.py
# =========================================
# Scoring + poll loop owned by bonus_answers. Aliases below are for sites that
# still pass the function by reference (root.after rescheduling, web_host_actions).
_poll_web_answers = bonus_answers._poll_web_answers

def _start_web_server():
    if not NGROK_AVAILABLE and not CLOUDFLARED_AVAILABLE:
        print("[Web Server] No tunnel found (ngrok or cloudflared) — web answer server disabled. "
              "Place ngrok.exe or cloudflared.exe next to this app or install one to PATH.")
        return
    if WEB_SERVER_ENABLED:
        web_server.start(port=8080, ngrok_domain=NGROK_DOMAIN or None,
                         cloudflare_token=CLOUDFLARE_TUNNEL_TOKEN or None,
                         cloudflare_url=CLOUDFLARE_PUBLIC_URL or None)
        root.after(1000, _poll_web_answers)

def toggle_web_server():
    """Manually start or stop the web answer server from the menu."""
    if web_server.is_running():
        web_server.stop()
        print("[Web Server] Stopped.")
    else:
        web_server.start(port=8080, ngrok_domain=NGROK_DOMAIN or None,
                         cloudflare_token=CLOUDFLARE_TUNNEL_TOKEN or None,
                         cloudflare_url=CLOUDFLARE_PUBLIC_URL or None)
        root.after(1000, _poll_web_answers)

def get_all_anime_titles():
    """Return sorted unique anime display titles from the metadata cache for autocomplete."""
    seen = set()
    titles = []
    for data in metadata_fetch._metadata_cache.values():
        if not isinstance(data, dict):
            continue
        t = get_display_title(data)
        if t and t != "No Title Found" and t not in seen:
            seen.add(t)
            titles.append(t)
    return sorted(titles)

_start_web_server()
if LAUNCH_SCOREBOARD_ON_STARTUP and scoreboard_control.AVAILABLE and not is_scoreboard_running():
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
web_server.set_titles_provider(get_all_anime_titles)
web_server.set_player_names_provider(lambda: (
    __import__('json').load(open(
        __import__('os').path.join('scoreboard_data', 'scoreboard_leaderboard.json'), encoding='utf-8'))
    if __import__('os').path.exists(
        __import__('os').path.join('scoreboard_data', 'scoreboard_leaderboard.json')) else []
))
web_server.set_host_password(HOST_PASSWORD)

def _invoke_registry_by_id(item_id: str):
    """Look up a menu registry item by id and call its command (searches submenus recursively)."""
    def _search(items):
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("id") == item_id:
                cmd = item.get("command")
                if callable(cmd):
                    cmd()
                return True
            if _search(item.get("submenu") or []):
                return True
        return False
    registry = _get_menu_registry()
    for section in registry.values():
        if isinstance(section, list):
            if _search(section):
                return True
    return False

def _fmt_seconds(seconds) -> str:
    """Format a duration in seconds as M:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02}"

def _build_play_maps():
    """Build play-count and series-play maps from the current playlist history."""
    _pl = playlist.get('playlist', [])
    _cur_idx = playlist.get('current_index', 0)
    _played = _pl[:_cur_idx + 1]
    _play_count_map = {}
    _play_last_map = {}
    for _i, _item in enumerate(_played):
        _f = _item[3:] if _item.startswith('[L]') else _item
        _k = _play_name_key(_f)
        _play_count_map[_k] = _play_count_map.get(_k, 0) + 1
        _play_last_map[_k] = _i
    _series_play_map = _build_played_series_map(_played, _cur_idx)
    return _play_count_map, _play_last_map, _series_play_map, _cur_idx

def _build_theme_web_result(fn, _play_count_map, _play_last_map, _series_play_map, _cur_idx, query_lower=''):
    """Build a single theme result dict for web push_theme_search_results / push_directory_themes."""
    meta = get_metadata(fn)
    title_en = str(meta.get('eng_title') or '').strip()
    title_jp = str(meta.get('title') or '').strip()
    title = title_en or title_jp or fn
    slug = meta.get('slug') or ''
    song_title = ''
    artist_name = ''
    for s in (meta.get('songs') or []):
        if s.get('slug') == slug:
            song_title = s.get('title') or ''
            artist_name = get_artists_string(s.get('artist') or [], total=False)
            break
    _fn_series = series_set(meta)
    _sp_count = sum(_series_play_map[_s]['count'] for _s in _fn_series if _s in _series_play_map)
    _sp_last = min((_series_play_map[_s]['last_idx'] for _s in _fn_series if _s in _series_play_map), default=None)
    _pk = _play_name_key(fn)
    return {
        'filename': fn,
        'title': title,
        'title_en': title_en,
        'title_jp': title_jp,
        'slug': slug,
        'song': song_title,
        'artist': artist_name,
        'season': str(meta.get('season') or '').strip(),
        'format': str(get_format(meta) or '').strip(),
        'studio': ', '.join([str(x).strip() for x in (meta.get('studios') or []) if str(x).strip()]),
        'song_match': bool(query_lower and song_title and query_lower in song_title.lower()),
        'artist_match': bool(query_lower and artist_name and query_lower in artist_name.lower()),
        'plays': _play_count_map.get(_pk, 0),
        'plays_ago': (_cur_idx - _play_last_map[_pk]) if _pk in _play_last_map and _play_last_map[_pk] < _cur_idx else None,
        'series_plays': _sp_count,
        'series_plays_ago': (_cur_idx - _sp_last) if _sp_last is not None and _sp_last < _cur_idx else None,
    }

def _queue_theme_standard(fn: str):
    """Queue a specific theme file as search_queue, or dequeue it if already queued."""
    if not fn:
        return
    if search_ops.search_queue == fn:
        search_ops.search_queue = None
        up_next_text()
    else:
        search_ops.search_queue = fn
        if not player.is_playing():
            play_video()
            return
        up_next_text()
    prefetch_next_themes()

web_host_actions.set_context(main_module=sys.modules[__name__])
_handle_host_action = web_host_actions._handle_host_action
web_server.set_host_action_callback(_handle_host_action)

bonus_answers.set_context(main_module=sys.modules[__name__])

# ---------------------------------------------------------------------------
# Buzzer (toast + segment-based WAV synth) — see _app_scripts/bonus/buzz.py
# ---------------------------------------------------------------------------
from _app_scripts.bonus import buzz
buzz.set_context(main_module=sys.modules[__name__])
BUZZ_PRESETS = buzz.BUZZ_PRESETS
_play_buzz_sound = buzz._play_buzz_sound
_web_buzzer_lock  = buzz._web_buzzer_lock
_web_buzzer_reset = buzz._web_buzzer_reset
_web_buzzer_open  = buzz._web_buzzer_open
web_server.set_buzz_callback(_play_buzz_sound)

def _on_skip_grant_changed(name):
    if name:
        send_scoreboard_command(f"[SKIP_GRANT]{name}")
    else:
        send_scoreboard_command("[SKIP_GRANT_CLEAR]")

web_server.set_skip_grant_callback(_on_skip_grant_changed)
scan_directory(True)
create_first_row_buttons()
rebuild_shortcut_dispatch()
threading.Thread(target=load_default_char_images, daemon=True).start()

# Clean up any leftover updater files from previous updates
def cleanup_updater_files():
    """Remove updater.exe and updater.log files if they exist."""
    files_to_clean = ["updater.exe", "updater.log"]
    for filename in files_to_clean:
        if os.path.exists(filename):
            try:
                os.remove(filename)
                print(f"Cleaned up: {filename}")
            except Exception as e:
                print(f"Could not clean up {filename}: {e}")

# Clean up updater files on startup
cleanup_updater_files()

# Add debounced resize handler to refresh list display when window resize is complete
resize_timer_id = None

def on_window_resize(event):
    """Handle window resize events with debouncing - only update after resize is complete."""
    global resize_timer_id
    
    # Only handle resize events from the root window
    if event.widget != root or not list_loaded:
        return
    
    # Cancel any pending resize update
    if resize_timer_id is not None:
        root.after_cancel(resize_timer_id)
    
    # Schedule a new update after 500ms of no resize events (resize finished)
    resize_timer_id = root.after(500, refresh_list_on_resize)

def refresh_list_on_resize():
    """Refresh the current list display with updated button count."""
    global resize_timer_id
    
    # Clear the timer ID since we're executing now
    resize_timer_id = None
    
    if list_loaded and current_list_content is not None:
        current_button_count = len(persistent_buttons) if persistent_buttons else 0
        new_entries_count = get_list_entries_count()
        
        if current_button_count != new_entries_count:
            # Get current list type and refresh it
            # Force recreation of buttons by temporarily clearing list_loaded
            temp_loaded = list_loaded
            list_set_loaded("")
            show_list(temp_loaded, right_column, current_list_content, current_list_name_func,
                      list_func, current_list_selected, update=True, title=current_list_title)

# Bind resize event to root window
root.bind("<Configure>", on_window_resize)

check_download_ui_updates = cache_download.check_download_ui_updates

root.after(1000, create_new_session)

# Start updating the seek bar
root.after(1000, update_seek_bar)
# root.after(1000, check_video_end)  # replaced by mpv end-file event callback (_on_end_file)
# Set initial volume
root.after(1000, set_volume, state.controls.volume_level)
root.after(1000, cleanup_old_update_exes)
root.after(3000, check_for_updates_on_startup)
root.after(1000, update_living_playlists)
root.after(500, check_download_ui_updates)  # Start checking for download UI updates

def on_app_close():
    """Safely destroy hidden root-parented widgets before closing to avoid TclError."""
    # Cancel any pending tooltip after() callback so it can't fire on a destroyed widget
    if _menu_tooltip_after[0]:
        try:
            root.after_cancel(_menu_tooltip_after[0])
        except Exception:
            pass
        _menu_tooltip_after[0] = None
    if _menu_tooltip_win[0]:
        try:
            _menu_tooltip_win[0].destroy()
        except Exception:
            pass
        _menu_tooltip_win[0] = None

    for name in ("difficulty_dropdown",):
        widget = globals().get(name)
        if widget is not None:
            try:
                widget.unbind_all("<<ComboboxSelected>>")
                widget.destroy()
            except Exception:
                pass
    # quit() exits the mainloop cleanly before destroy() tears down the widgets
    try:
        web_server.stop()
    except Exception:
        pass
    try:
        save_config()
    except Exception:
        pass
    if AUTO_EXIT_SCOREBOARD and is_scoreboard_running():
        send_scoreboard_command("quit")
    try:
        root.quit()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass

root.protocol("WM_DELETE_WINDOW", on_app_close)

# Start the mpv click poller (drains _mpv_click_queue on the main thread)
root.after(50, _poll_mpv_clicks)

# Auto-open tutorial on first launch (tutorial_shown is False until user closes it once)
if not tutorial_shown:
    root.after(500, show_tutorial_popup)

# Restore saved collapsed state (applied after UI is fully rendered)
if globals().get('_pending_restore_collapsed'):
    root.after(100, toggle_player_collapse)

root.mainloop()
