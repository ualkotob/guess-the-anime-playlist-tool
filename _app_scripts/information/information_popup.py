"""Information popup — title/artist/studio/season/year info OSD over mpv.

Extracted from `guess_the_anime.py` (the INFORMATION POPUP section).

The popup is rendered as an ASS osd-overlay drawn on the mpv canvas (no Tk
window). The module also owns:

  - the **mpv window tracker** (``_register_mpv_tracked_window`` / poll loop)
    used by sibling subsystems (bonus chars, etc.) to keep Tk Toplevels
    pinned over the mpv window;
  - geometry helpers (``_get_mpv_window_rect``, ``_get_mpv_client_rect_logical``,
    ``_get_osd_video_rect``, ``_get_effective_video_rect``) — used by overlay
    siblings, which import this module and call them directly;
  - data-shaping helpers used both by the popup and by sibling modules:
    ``get_artist_themes_data``, ``get_studio_entries_data``, ``get_format``,
    ``get_episode_display``, ``_shorten_platform``, ``get_tags_string``,
    ``get_tags``, ``get_song_string``;
  - the ``animate_window`` helper kept here for parity with the original
    section (used by main's title-card and dialog animations).

Shared popup state lives on ``state.info_display``:
  - ``title_info_only`` / ``artist_info_display`` / ``studio_info_display`` /
    ``season_info_display`` / ``year_info_display`` — info-mode flags read by
    web-toggle pushes, keyboard shortcuts, popout buttons, lightning logic.
  - ``_title_popup_intent`` — read by ``is_title_window_up`` (re-exported).

State owned here (module-locals):
  - ``_INFO_POPUP_ASS_OSD_ID`` — ASS osd-overlay id for the popup.
  - ``_title_popup_info_type_cache`` — last info_type, used by resize hook.
  - ``_mpv_tracked_windows`` and ``_mpv_tracker_*`` — tracker loop state.
  - ``_title_popup_last_mpv_size`` / ``_title_popup_anim_*`` — slide animation.

Collaborators are reached by importing sibling modules directly (see imports
below). ``_osd_command`` is a thin module-local wrapper around
``state.widgets.player._p.command`` (mirrors the copy in main/censors).
``title_top_info_txt`` is a SETTINGS_SCHEMA config scalar on
``state.config``. No main context injection is needed.
"""
from __future__ import annotations
from core.game_state import state

import math
import re
import time
from datetime import datetime

import _app_scripts.file.web_server.web_server as web_server
import _app_scripts.bonus.bonus as bonus
import _app_scripts.bonus.answers as bonus_answers
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.queue_round.youtube.youtube_ui as youtube_ui
import _app_scripts.queue_round.lightning_rounds.peek_dispatch as peek_dispatch
import _app_scripts.queue_round.lightning_rounds.title_overlay as title_overlay
import _app_scripts.playback.osd_text as osd_text
import _app_scripts.playlists.marks as playlist_marks
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.utils as utils


# ASS osd-overlay id for the anime info popup (was main's _INFO_POPUP_ASS_OSD_ID).
_INFO_POPUP_ASS_OSD_ID = 59


def _osd_command(*args):
    """Send an osd-overlay command to the main player."""
    try:
        state.widgets.player._p.command(*args)
    except Exception:
        pass


def toggle_auto_info_start():
    state.controls.auto_info_start = not state.controls.auto_info_start
    print("Auto Info Popup at start: " + str(state.controls.auto_info_start))


def toggle_auto_info_end():
    state.controls.auto_info_end = not state.controls.auto_info_end
    print("Auto Info Popup at end: " + str(state.controls.auto_info_end))


# ---------------------------------------------------------------------------
# Module-owned state
# ---------------------------------------------------------------------------
_title_popup_info_type_cache = None  # last info_type shown; used by resize tracker

# ── mpv window tracker ─────────────────────────────────────────────────────
# Register any Tkinter Toplevel to follow the mpv window as it moves/resizes.
# Usage: _register_mpv_tracked_window(name, window, callback(mx,my,mw,mh))
_mpv_tracked_windows = {}   # {name: {"window": win, "on_rect_change": fn, "keep_topmost": bool, "lift_on_focus": bool}}
_mpv_tracker_id = None
_mpv_tracker_last_rect = None
_mpv_tracker_last_fg = False   # whether mpv was foreground on the last poll

_title_popup_last_mpv_size = (0, 0)
_title_popup_anim_after  = None   # root.after ID for slide animation
_title_popup_anim_state  = None   # 'in' | 'out' | None
_title_popup_anim_args   = None   # (top_row, title_row, bottom_row, bg_color, fg_color) for redraw


# ===========================================================================
# Info popup toggles — cycle through title/artist/studio/season/year modes.
# Boolean flags (title_info_only, artist_info_display, ...) live on
# state.info_display, read across main and sibling modules.
# ===========================================================================
def toggle_info_popup():
    if is_title_window_up() and (state.info_display.title_info_only or state.info_display.artist_info_display or state.info_display.studio_info_display or state.info_display.season_info_display or state.info_display.year_info_display):
        toggle_title_popup(True)
    else:
        toggle_title_popup(not is_title_window_up())


def toggle_title_info_popup():
    # Cycle through different info display modes
    if is_title_window_up() and not state.info_display.title_info_only and not state.info_display.artist_info_display and not state.info_display.studio_info_display and not state.info_display.season_info_display and not state.info_display.year_info_display:
        toggle_artist_info_popup()
    elif is_title_window_up() and state.info_display.artist_info_display:
        toggle_studio_info_popup()
    elif is_title_window_up() and state.info_display.studio_info_display:
        toggle_season_info_popup()
    elif is_title_window_up() and state.info_display.season_info_display:
        toggle_year_info_popup()
    elif is_title_window_up() and state.info_display.year_info_display:
        toggle_title_popup(True)
    else:
        # If popup is down or showing title only, toggle it
        toggle_title_popup(not is_title_window_up(), info_type="title_only")


def toggle_artist_info_popup():
    if state.info_display.artist_info_display:
        toggle_title_popup(True)
    else:
        toggle_title_popup(True, info_type="artist")


def update_popout_title_button_text(show=None):
    """Refresh toggle-state colours for info/title/artist/studio/season/year popup
    buttons in the popout.  The old single-cycling button pattern is replaced by
    separate buttons for each popup action, so we just call _refresh_popout_toggles."""
    popout_window._refresh_popout_toggles()


def toggle_studio_info_popup():
    if state.info_display.studio_info_display:
        toggle_title_popup(True)
    else:
        toggle_title_popup(True, info_type="studio")


def toggle_season_info_popup():
    if state.info_display.season_info_display:
        toggle_title_popup(True)
    else:
        toggle_title_popup(True, info_type="season")


def toggle_year_info_popup():
    if state.info_display.year_info_display:
        toggle_title_popup(True)
    else:
        toggle_title_popup(True, info_type="year")


def animate_window(window, target_x, target_y, steps=20, delay=5, bounce=True, fade="in", destroy=False, callback=None):
    """Smoothly moves a Tkinter window to a new position with optional bounce, fade effects, and a completion callback."""
    if not window:
        return

    start_x = window.winfo_x()
    start_y = window.winfo_y()

    delta_x = (target_x - start_x) / steps
    delta_y = (target_y - start_y) / steps

    original_alpha = 0.8  # Default transparency
    if fade == "in":
        window.attributes("-alpha", 0)  # Start fully transparent

    def step(i=0):
        if i <= steps and window and window.winfo_exists():
            bounce_strength = math.sin((i / steps) * math.pi) * 5 if bounce and i > steps * 0.7 else 0

            new_x = int(start_x + delta_x * i + bounce_strength)
            new_y = int(start_y + delta_y * i + bounce_strength)
            window.geometry(f"+{new_x}+{new_y}")

            if fade == "in":
                alpha = min(original_alpha, (i / steps) * original_alpha)
                window.attributes("-alpha", alpha)
            elif fade == "out":
                alpha = max(0, ((steps - i) / steps) * original_alpha)
                window.attributes("-alpha", alpha)

            if i < steps:
                window.after(delay, lambda: step(i + 1))
            elif destroy and window:
                window.destroy()
                if callback:
                    callback()
            else:
                # Final geometry and callback after a short delay
                window.after(delay * 2, lambda: (
                    window.geometry(f"+{new_x}+{new_y}"),
                    callback() if callback else None
                ))
    step()


# ===========================================================================
# Artist / Studio data shaping (used by the popup and by metadata_panel)
# ===========================================================================
def get_artist_themes_data(artist_name, current_filename=None, max_display=None, include_current=False):
    """Extract and format all themes by a given artist.

    Returns a dict with structure:
    {
        "artist": artist_name,
        "themes": [
            {"anime_title": str, "themes": [str], "popularity": int},
            ...
        ],
        "total_count": int,
        "theme_count": int,
        "truncated": bool
    }
    """
    if not artist_name:
        return {"artist": artist_name, "themes": [], "total_count": 0, "theme_count": 0, "truncated": False}

    def _theme_sort_key(slug):
        """Sort OP before ED, then others; numeric order within each group."""
        s = str(slug or "").upper().strip()
        m = re.match(r'^([A-Z]+)\s*(\d+)?', s)
        if m:
            prefix = m.group(1)
            num = int(m.group(2)) if m.group(2) else 0
        else:
            prefix = s
            num = 0
        if prefix.startswith("OP"):
            grp = 0
        elif prefix.startswith("ED"):
            grp = 1
        else:
            grp = 2
        return (grp, num, s)

    def _popularity_sort_value(v):
        """Return numeric popularity for sorting; unknown/invalid values sort last."""
        if v is None:
            return float("inf")
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        if not s or s.upper() == "N/A":
            return float("inf")
        try:
            return float(s)
        except (TypeError, ValueError):
            return float("inf")

    same_artists = metadata_display.get_filenames_from_artist(artist_name)

    # Group themes by anime and collect popularity
    anime_themes = {}  # {anime_title: {"themes": [theme_list], "popularity": popularity_val}}
    for f in same_artists:
        if include_current or current_filename is None or f != current_filename:
            f_data = metadata_fetch.get_metadata(f)
            if f_data:
                anime_title = metadata_display.get_display_title(f_data)
                theme_slug = f_data.get("slug", "")
                popularity = f_data.get("popularity", 999999)

                if anime_title not in anime_themes:
                    anime_themes[anime_title] = {
                        "themes": [],
                        "popularity": popularity
                    }
                anime_themes[anime_title]["themes"].append({"slug": theme_slug, "filename": f})

    # Sort by popularity (lower number = more popular)
    all_sorted_anime = sorted(anime_themes.items(),
                             key=lambda x: _popularity_sort_value(x[1].get("popularity")))
    total_count = len(all_sorted_anime)
    theme_count = sum(len(info["themes"]) for _, info in all_sorted_anime)

    # Apply max_display limit if provided
    if max_display:
        sorted_anime = all_sorted_anime[:max_display]
        truncated = total_count > max_display
    else:
        sorted_anime = all_sorted_anime
        truncated = False

    # Sort alphabetically by anime title
    sorted_anime = sorted(sorted_anime, key=lambda x: x[0])

    # Build output structure for web consumption
    themes_list = []
    for anime_title, info in sorted_anime:
        _sorted_slugs = sorted(info["themes"], key=lambda t: _theme_sort_key(t["slug"]))
        themes_list.append({
            "anime_title": anime_title,
            "themes": _sorted_slugs,
            "popularity": info["popularity"]
        })

    return {
        "artist": artist_name,
        "themes": themes_list,
        "total_count": total_count,
        "theme_count": theme_count,
        "truncated": truncated
    }


def get_studio_entries_data(studio_name, current_filename=None, max_display=None, include_current=False):
    """Extract and format unique anime entries by a given studio.

    Mirrors the previous studio popup logic:
      - unique anime titles by studio
      - if over max, collapse to most-popular unique series entries
      - alphabetical display with optional "...and X more series"
    """
    if not studio_name:
        return {
            "studio": studio_name,
            "entries": [],
            "series_groups": [],
            "header_type": "titles",
            "total_count": 0,
            "entry_count": 0,
            "truncated": False,
        }

    current_title = None
    if not include_current and current_filename:
        _cur_data = metadata_fetch.get_metadata(current_filename)
        if _cur_data:
            current_title = metadata_display.get_display_title(_cur_data)

    def _extract_year(_d):
        for _v in (_d.get("season"), _d.get("aired"), _d.get("release")):
            if not _v:
                continue
            _m = re.search(r'\b(19|20)\d{2}\b', str(_v))
            if _m:
                return _m.group(0)
        return None

    same_studio = metadata_display.get_filenames_from_studio(studio_name)
    unique_titles = []
    unique_shows = []  # [title, popularity, series, year]
    for f in same_studio:
        d = metadata_fetch.get_metadata(f)
        if not d:
            continue
        t = metadata_display.get_display_title(d)
        if current_title and t == current_title:
            continue
        if t not in unique_titles:
            _raw_pop = d.get("popularity", None)
            popularity = _raw_pop if (_raw_pop is not None and _raw_pop != float('inf')) else None
            series = metadata_display.series_list(d)
            year = _extract_year(d)
            unique_shows.append([t, popularity, series, year])
            unique_titles.append(t)

    # Build series grouping data for web dialog rendering.
    series_groups_map = {}
    for t, p, s, y in unique_shows:
        t_display = f"{t} ({y})" if y else t
        series_key = (s[0] if s else t) or t
        if series_key not in series_groups_map:
            series_groups_map[series_key] = {
                "series": series_key,
                "entries": [],
                "popularity": p,
            }
        series_groups_map[series_key]["entries"].append(t_display)
        if p is not None and (series_groups_map[series_key]["popularity"] is None or p < series_groups_map[series_key]["popularity"]):
            series_groups_map[series_key]["popularity"] = p

    header_type = "titles"
    series_dict = {}
    candidates = []  # [display_title, popularity]

    if max_display and len(unique_shows) > max_display:
        # only use most popular title of each series
        for t, p, s, y in unique_shows:
            t_display = f"{t} ({y})" if y else t
            series_key = s[0] if s else t
            count = series_dict[series_key][2] + 1 if series_key in series_dict else 1
            count_string = f" [{count} seasons]" if count > 1 else ""
            if series_key not in series_dict or (p is not None and (series_dict[series_key][1] is None or p < series_dict[series_key][1])):
                series_dict[series_key] = [f"{t_display}{count_string}", p, count]
            else:
                series_dict[series_key][0] = f"{series_dict[series_key][0].split(' [')[0]}{count_string}"
            series_dict[series_key][2] = count

        candidates = [[v[0], v[1]] for v in series_dict.values()]
        header_type = "series"
    else:
        candidates = [[f"{t} ({y})" if y else t, p] for t, p, _, y in unique_shows]

    total_count = len(candidates)
    truncated = False
    if max_display and len(candidates) > max_display:
        candidates = sorted(candidates, key=lambda x: x[1] if x[1] is not None else 9999999)[:max_display]
        truncated = True

    display_entries = sorted([t for t, _ in candidates])

    # Preserve prior behavior note for collapsed-series mode.
    if header_type == "series" and series_dict and len(display_entries) < len(series_dict):
        display_entries.append(f"...and {len(series_dict) - len(display_entries)} more series")

    series_groups = []
    for _k, _g in series_groups_map.items():
        _entries = sorted(list(set(_g["entries"])))
        _sort_key = _g["series"] if len(_entries) > 1 else (_entries[0] if _entries else _g["series"])
        series_groups.append({
            "series": _g["series"],
            "entries": _entries,
            "count": len(_entries),
            "popularity": _g["popularity"],
            "sort_key": _sort_key,
        })
    series_groups = sorted(series_groups, key=lambda x: str(x.get("sort_key", "")).lower())

    return {
        "studio": studio_name,
        "entries": display_entries,
        "series_groups": series_groups,
        "header_type": header_type,
        "total_count": total_count,
        "entry_count": total_count,
        "truncated": truncated,
    }


# ===========================================================================
# mpv window rect + tracker
# ===========================================================================
def _get_mpv_window_rect():
    """Return (x, y, w, h) of the mpv player **client area** on screen.
    Using the client rect (not the full window rect) excludes the title bar and
    window borders so that peek overlays align with the actual video area.
    Falls back to (0, 0, screen_w, screen_h) if the window handle is unavailable."""
    try:
        import ctypes, ctypes.wintypes
        hwnd = int(state.widgets.player._p.window_id or 0)
        if hwnd:
            # GetClientRect gives dimensions relative to the client origin (always 0,0)
            client_rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client_rect))
            w = client_rect.right - client_rect.left
            h = client_rect.bottom - client_rect.top
            if w > 0 and h > 0:
                # ClientToScreen converts the client (0,0) to screen coordinates
                pt = ctypes.wintypes.POINT()
                pt.x = 0
                pt.y = 0
                ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
                return pt.x, pt.y, w, h
    except Exception:
        pass
    sw = state.widgets.root.winfo_screenwidth()
    sh = state.widgets.root.winfo_screenheight()
    return 0, 0, sw, sh


def _get_mpv_client_rect_logical():
    """Return (x, y, w, h) of the mpv client area in Tkinter **logical** pixels.
    Divides Win32 physical pixel coords by the per-monitor DPI scale so the
    result can be passed directly to win.geometry() without position/size errors
    on screens with DPI scaling != 100%.
    Falls back to (0, 0, screen_w, screen_h) when the HWND is unavailable."""
    try:
        import ctypes, ctypes.wintypes
        hwnd = int(state.widgets.player._p.window_id or 0)
        if hwnd:
            try:
                dpi = ctypes.windll.shcore.GetDpiForWindow(hwnd)
                scale = dpi / 96.0
            except Exception:
                scale = state.widgets.root.winfo_fpixels('1i') / 96.0
            client = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client))
            w_phys = client.right - client.left
            h_phys = client.bottom - client.top
            if w_phys > 0 and h_phys > 0:
                pt = ctypes.wintypes.POINT()
                pt.x = 0
                pt.y = 0
                ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
                return (round(pt.x / scale), round(pt.y / scale),
                        round(w_phys / scale), round(h_phys / scale))
    except Exception:
        pass
    return 0, 0, state.widgets.root.winfo_screenwidth(), state.widgets.root.winfo_screenheight()


def _mpv_tracker_poll():
    global _mpv_tracker_id, _mpv_tracker_last_rect, _mpv_tracker_last_fg
    if not _mpv_tracked_windows:
        _mpv_tracker_id = None
        _mpv_tracker_last_rect = None
        _mpv_tracker_last_fg = False
        return
    rect = _get_mpv_window_rect()
    if rect != _mpv_tracker_last_rect:
        _mpv_tracker_last_rect = rect
        for name in list(_mpv_tracked_windows):
            info = _mpv_tracked_windows.get(name)
            if not info:
                continue
            win = info.get("window")
            if win is not None:
                try:
                    exists = win.winfo_exists()
                except Exception:
                    exists = False
                if not exists:
                    _mpv_tracked_windows.pop(name, None)
                    continue
            try:
                info["on_rect_change"](*rect)
            except Exception:
                pass
    # Re-lift keep_topmost windows every poll so the title popup always wins z-order.
    for name in list(_mpv_tracked_windows):
        info = _mpv_tracked_windows.get(name)
        if not info or not info.get("keep_topmost"):
            continue
        win = info.get("window")
        if win is None:
            continue
        try:
            if win.winfo_exists():
                win.lift()
        except Exception:
            pass
    # Lift lift_on_focus windows only when mpv just became foreground
    try:
        import ctypes
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        mpv_hwnd = int(state.widgets.player._p.window_id or 0)
        mpv_fg = bool(mpv_hwnd and fg_hwnd == mpv_hwnd)
    except Exception:
        mpv_fg = False
    if mpv_fg and not _mpv_tracker_last_fg:
        for name in list(_mpv_tracked_windows):
            info = _mpv_tracked_windows.get(name)
            if not info or not info.get("lift_on_focus"):
                continue
            win = info.get("window")
            if win is None:
                continue
            try:
                if win.winfo_exists():
                    win.lift()
            except Exception:
                pass
    _mpv_tracker_last_fg = mpv_fg
    _mpv_tracker_id = state.widgets.root.after(150, _mpv_tracker_poll)


def _register_mpv_tracked_window(name, window, on_rect_change, keep_topmost=False, lift_on_focus=False):
    global _mpv_tracker_id
    _mpv_tracked_windows[name] = {"window": window, "on_rect_change": on_rect_change, "keep_topmost": keep_topmost, "lift_on_focus": lift_on_focus}
    if _mpv_tracker_id is None:
        _mpv_tracker_id = state.widgets.root.after(150, _mpv_tracker_poll)


def _unregister_mpv_tracked_window(name):
    _mpv_tracked_windows.pop(name, None)


# ===========================================================================
# OSD geometry + title popup OSD draw
# ===========================================================================
def _blind_osd_on_mpv_rect(mx, my, mw, mh):
    """Refresh the blind OSD when the mpv window size changes so it stays full-canvas."""
    from _app_scripts.playback import blind_screen
    if blind_screen.black_overlay:
        blind_screen._set_blind_osd_alpha(blind_screen._blind_osd_color_cache, 255)


def _get_osd_video_rect():
    """Return (osd_w, osd_h, vid_x, vid_y, vid_w, vid_h) in OSD pixel coordinates.
    vid_x/y/w/h is the letterboxed video area within the OSD canvas.
    Returns all zeros if OSD is not ready.
    """
    try:
        osd_w = int(state.widgets.player._p.osd_width or 0)
        osd_h = int(state.widgets.player._p.osd_height or 0)
    except Exception:
        return 0, 0, 0, 0, 0, 0
    if not osd_w or not osd_h:
        return 0, 0, 0, 0, 0, 0
    try:
        vw, vh = state.widgets.player.video_get_size(0)
    except Exception:
        vw, vh = 0, 0
    if vw and vh:
        if (vw == 720 and vh in (480, 478)) or (vw == 716 and vh == 478):
            video_ar = 16.0 / 9.0
        else:
            video_ar = vw / vh
        osd_ar = osd_w / osd_h
        if video_ar >= osd_ar:
            disp_w = osd_w
            disp_h = int(osd_w / video_ar)
            vid_x = 0
            vid_y = (osd_h - disp_h) // 2
        else:
            disp_h = osd_h
            disp_w = int(osd_h * video_ar)
            vid_x = (osd_w - disp_w) // 2
            vid_y = 0
    else:
        vid_x, vid_y, disp_w, disp_h = 0, 0, osd_w, osd_h
    return osd_w, osd_h, vid_x, vid_y, disp_w, disp_h


def _get_effective_video_rect():
    """Like _get_osd_video_rect but adjusts for active framed-video zoom/pan.
    Returns (osd_w, osd_h, vid_x, vid_y, vid_w, vid_h) where vid_* is the
    actual visible video area in OSD pixels (smaller when framed_video is on).
    """
    from _app_scripts.playback import blind_screen
    osd_w, osd_h, vid_x, vid_y, vid_w, vid_h = _get_osd_video_rect()
    if not blind_screen._video_frame_active or not vid_w:
        return osd_w, osd_h, vid_x, vid_y, vid_w, vid_h
    scale = 2 ** blind_screen._video_frame_zoom
    new_w = round(vid_w * scale)
    new_h = round(vid_h * scale)
    y_shift = round(new_h * abs(blind_screen._FRAME_PAN_Y))
    new_x = round((osd_w - new_w) / 2)
    new_y = round((osd_h - new_h) / 2) - y_shift
    return osd_w, osd_h, new_x, new_y, new_w, new_h


def _hide_title_popup_osd():
    """Remove the anime info ASS overlay from the mpv canvas and stop any slide animation."""
    global _title_popup_anim_state
    _title_popup_slide_cancel()
    _title_popup_anim_state = None
    try:
        _osd_command('osd-overlay', _INFO_POPUP_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
    except Exception:
        pass


def _draw_title_popup_osd(top_row, title_row, bottom_row, bg_color, fg_color, y_offset=0):
    """Render the anime info popup as an ASS osd-overlay at the bottom-center of the mpv canvas.

    Mirrors the original tkinter layout:
      top_row    — small bold text  (ASS fs ≈ scl(20))
      title_row  — large bold text  (ASS fs ≈ scl(50), shrink-to-fit)
      bottom_row — small bold text  (ASS fs ≈ scl(15))
    A semi-transparent background box (alpha 0.8) is drawn beneath all rows.
    y_offset > 0 shifts the box downward (used for slide-out below the screen).
    """
    try:
        osd_w = int(state.widgets.player._p.osd_width or 0)
        osd_h = int(state.widgets.player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    modifier = min(osd_w / 2560, osd_h / 1440)

    # Font sizes: match tkinter scl(20)/scl(50)/scl(15) scaled by osd modifier.
    # The ×1.6 matches the conversion used in set_floating_text.
    fs_top    = max(10, round(20 * modifier * 1.6))
    fs_title  = max(14, round(50 * modifier * 1.6))
    fs_bottom = max(10, round(15 * modifier * 1.6))

    pad_x  = max(2, round(osd_h * 0.001))   # left/right padding (tight)
    pad_y  = max(4, round(osd_h * 0.005))   # top/bottom padding (slightly more room)
    margin = max(4, round(10 * modifier))
    gap    = max(2, round(fs_top * 0.1))    # vertical gap between rows

    def _line_h(fs, n):
        return round(n * fs * 1.0)

    def _measure_w(text_block, fs):
        """Max rendered pixel width of any line in text_block at the given fs."""
        fnt = osd_text._get_ass_font(fs)
        max_w = 0
        for line in text_block.split('\n'):
            if not line:
                continue
            try:
                w = round(fnt.getlength(line)) if fnt else round(len(line) * fs * 0.52)
            except AttributeError:
                w = fnt.getsize(line)[0] if fnt else round(len(line) * fs * 0.52)
            if w > max_w:
                max_w = w
        return max_w or fs

    # Shrink title font until it fits, matching adjust_font_size behaviour.
    max_title_px = osd_w - round(osd_h * 0.25)
    while fs_title > 14 and _measure_w(title_row, fs_title) + pad_x * 2 > max_title_px:
        fs_title -= 1

    top_lines    = top_row.count('\n') + 1    if top_row    else 0
    title_lines  = title_row.count('\n') + 1  if title_row  else 0
    bottom_lines = bottom_row.count('\n') + 1 if bottom_row else 0

    row_h_top    = _line_h(fs_top,    top_lines)    if top_lines    else 0
    row_h_title  = _line_h(fs_title,  title_lines)  if title_lines  else 0
    row_h_bottom = _line_h(fs_bottom, bottom_lines)  if bottom_lines else 0

    inner_h = (row_h_top
               + (gap if top_lines and (title_lines or bottom_lines) else 0)
               + row_h_title
               + (gap if title_lines and bottom_lines else 0)
               + row_h_bottom)
    box_h = inner_h + 2 * pad_y

    widths = []
    if top_row:    widths.append(_measure_w(top_row,    fs_top))
    if title_row:  widths.append(_measure_w(title_row,  fs_title))
    if bottom_row: widths.append(_measure_w(bottom_row, fs_bottom))
    # PIL overestimates ASS bold render width; scale down to tighten the box.
    box_w = (round(max(widths) * 0.91) if widths else fs_title) + 2 * pad_x
    box_w = min(box_w, osd_w - 2 * margin)

    bx = (osd_w - box_w) // 2
    by = osd_h - margin - box_h + y_offset
    cx = osd_w // 2   # horizontal center for \an8 anchored text

    bg_bgr = osd_text._color_str_to_ass_bgr(bg_color)
    fg_bgr = osd_text._color_str_to_ass_bgr(fg_color)

    def _esc(text):
        """Escape ASS control chars and convert Python newlines to ASS hard newlines."""
        return text.replace('{', '').replace('}', '').replace('\n', r'\N')

    events = []

    # Background rectangle
    events.append(
        f"{{\\an7\\pos({bx},{by})"
        f"\\1c&H{bg_bgr}&\\1a&H33&\\bord0\\shad0\\p1}}"
        f"m 0 0 l {box_w} 0 {box_w} {box_h} 0 {box_h}{{\\p0}}"
    )

    ty = by + pad_y
    # \an8 = top-center anchor; \q2 = no automatic word-wrap
    _txt_tags = "\\bord0\\shad0\\b1\\q2"
    if top_lines:
        events.append(
            f"{{\\an8\\pos({cx},{ty})"
            f"\\1c&H{fg_bgr}&\\1a&H00&{_txt_tags}"
            f"\\fs{fs_top}}}{_esc(top_row)}"
        )
        ty += row_h_top + gap
    if title_lines:
        events.append(
            f"{{\\an8\\pos({cx},{ty})"
            f"\\1c&H{fg_bgr}&\\1a&H00&{_txt_tags}"
            f"\\fs{fs_title}}}{_esc(title_row)}"
        )
        ty += row_h_title + gap
    if bottom_lines:
        events.append(
            f"{{\\an8\\pos({cx},{ty})"
            f"\\1c&H{fg_bgr}&\\1a&H00&{_txt_tags}"
            f"\\fs{fs_bottom}}}{_esc(bottom_row)}"
        )

    try:
        _osd_command('osd-overlay', _INFO_POPUP_ASS_OSD_ID, 'ass-events',
                     "\n".join(events), osd_w, osd_h, 4, 'no')
    except Exception as e:
        print(f"Info popup OSD error: {e}")


def _title_popup_slide_cancel():
    """Cancel any in-flight slide animation without clearing the OSD."""
    global _title_popup_anim_after
    if _title_popup_anim_after is not None:
        try:
            state.widgets.root.after_cancel(_title_popup_anim_after)
        except Exception:
            pass
        _title_popup_anim_after = None


def _title_popup_slide_in(top_row, title_row, bottom_row, bg_color, fg_color):
    """Animate the title popup sliding up from below the screen (time-based, ~100 ms duration)."""
    global _title_popup_anim_state, _title_popup_anim_args
    _title_popup_slide_cancel()
    _title_popup_anim_state = 'in'
    _title_popup_anim_args  = (top_row, title_row, bottom_row, bg_color, fg_color)
    try:
        osd_h = int(state.widgets.player._p.osd_height or 0)
    except Exception:
        osd_h = 0
    duration = 0.10   # seconds
    poll     = 5      # ms between frames
    t0 = time.perf_counter()

    def _step():
        global _title_popup_anim_after, _title_popup_anim_state
        if _title_popup_anim_state != 'in':
            return
        t = min((time.perf_counter() - t0) / duration, 1.0)
        bounce = math.sin(t * math.pi) * 5 if t > 0.7 else 0
        y_offset = int((osd_h if osd_h else 400) * (1.0 - t) + bounce)
        _draw_title_popup_osd(top_row, title_row, bottom_row, bg_color, fg_color, y_offset)
        if t < 1.0:
            _title_popup_anim_after = state.widgets.root.after(poll, _step)
        else:
            _title_popup_anim_after  = None
            _title_popup_anim_state  = None
            _draw_title_popup_osd(top_row, title_row, bottom_row, bg_color, fg_color, 0)

    _step()


def _title_popup_slide_out():
    """Animate the title popup sliding down off the bottom of the screen (time-based, ~100 ms duration),
    then clear the OSD."""
    global _title_popup_anim_after, _title_popup_anim_state
    _title_popup_slide_cancel()
    if _title_popup_anim_args is None:
        _hide_title_popup_osd()
        return
    _title_popup_anim_state = 'out'
    top_row, title_row, bottom_row, bg_color, fg_color = _title_popup_anim_args
    try:
        osd_h = int(state.widgets.player._p.osd_height or 0)
    except Exception:
        osd_h = 0
    duration = 0.10
    poll     = 5
    t0 = time.perf_counter()

    def _step():
        global _title_popup_anim_after, _title_popup_anim_state
        if _title_popup_anim_state != 'out':
            return
        t = min((time.perf_counter() - t0) / duration, 1.0)
        y_offset = int((osd_h if osd_h else 400) * t)
        _draw_title_popup_osd(top_row, title_row, bottom_row, bg_color, fg_color, y_offset)
        if t < 1.0:
            _title_popup_anim_after = state.widgets.root.after(poll, _step)
        else:
            _title_popup_anim_after  = None
            _title_popup_anim_state  = None
            _hide_title_popup_osd()

    _title_popup_anim_after = state.widgets.root.after(0, _step)


def _title_popup_on_mpv_rect(mx, my, mw, mh):
    global _title_popup_last_mpv_size
    if not state.info_display._title_popup_intent:
        return
    if (mw, mh) != _title_popup_last_mpv_size:
        # mpv window resized — instant redraw with new OSD dimensions, no animation
        _title_popup_last_mpv_size = (mw, mh)
        _title_popup_slide_cancel()
        if _title_popup_anim_args:
            _draw_title_popup_osd(*_title_popup_anim_args, y_offset=0)
        else:
            toggle_title_popup(True, _title_popup_info_type_cache)
    # mpv window moved — OSD tracks automatically, nothing to do


def is_title_window_up():
    return state.info_display._title_popup_intent


def toggle_title_popup(show, info_type=None, instant=False):
    """Creates or destroys the title popup at the bottom middle of the screen."""
    global _title_popup_info_type_cache, _title_popup_last_mpv_size
    if show:
        _already_up = state.info_display._title_popup_intent  # True when switching info type while popup is already visible
        _title_popup_info_type_cache = info_type
        state.info_display.title_info_only = info_type == "title_only"
        state.info_display.artist_info_display = info_type == "artist"
        state.info_display.studio_info_display = info_type == "studio"
        state.info_display.season_info_display = info_type == "season"
        state.info_display.year_info_display = info_type == "year"
        state.info_display._title_popup_intent = True
        bonus_answers._push_web_toggles()
        update_popout_title_button_text(show)
        if not state.info_display.title_info_only:
            web_server.set_info_public(True)
    else:
        state.info_display.title_info_only = False
        state.info_display.artist_info_display = False
        state.info_display.studio_info_display = False
        state.info_display.season_info_display = False
        state.info_display.year_info_display = False
        state.info_display._title_popup_intent = False
        bonus_answers._push_web_toggles()
        update_popout_title_button_text(show)
        web_server.set_info_public(False)
        _unregister_mpv_tracked_window("title_popup")
        if instant:
            _hide_title_popup_osd()
        else:
            _title_popup_slide_out()
        return

    if bonus.guessing_extra == "buzzer":
        if web_server.is_running():
            web_server.control_buzzer("reset")
            if not web_server.buzzer_is_locked():
                web_server.control_buzzer("lock")
        scoreboard_control.send_command("[CLEAR_SUBMITTED]")
    elif bonus.guessing_extra:
        bonus.guess_extra(bonus.guessing_extra)

    from _app_scripts.playback import blind_screen
    if blind_screen.black_overlay:
        blind_screen.blind()
    if peek_dispatch.is_peek_active():
        peek_dispatch.toggle_peek(False)

    top_row = ""
    title_row = ""
    bottom_row = ""
    bg_color = state.colors.OVERLAY_BACKGROUND_COLOR
    fg_color = state.colors.OVERLAY_TEXT_COLOR
    data = state.playback.currently_playing.get("data")
    fixed_current_round = state.lightning.fixed_current_round
    _use_clip_as_song = bool(
        fixed_current_round and
        fixed_current_round.get("type") in ("ost", "clip") and
        fixed_current_round.get("clip_source_as_song")
    )
    if _use_clip_as_song and data:
        _clip_title = fixed_current_round.get("clip_title") or ""
        _clip_author = fixed_current_round.get("clip_author") or ""
        _patched_songs = [
            dict(s, title=_clip_title, artist=[_clip_author] if _clip_author else s.get("artist"))
            if s.get("slug") == data.get("slug") else s
            for s in data.get("songs", [])
        ]
        data = dict(data, songs=_patched_songs)
    if data:
        if state.playback.currently_playing.get("type") == "youtube":
            title = youtube_ui.get_youtube_display_title(data)
            full_title = data.get("title")
            if full_title == title:
                full_title = ""
            else:
                full_title = full_title + "\n"
            uploaded = f"{datetime.strptime(data.get("upload_date"), "%Y%m%d").strftime("%Y-%m-%d")}"
            views = f"{data.get("view_count"):,}"
            likes = f"{data.get("like_count"):,}"
            channel = data.get("name")
            subscribers = f"{data.get("subscriber_count"):,}"
            duration = str(utils.format_seconds(youtube_ui.get_youtube_duration(data))) + " mins"
            fg_color = state.colors.INVERSE_OVERLAY_TEXT_COLOR
            bg_color = state.colors.INVERSE_OVERLAY_BACKGROUND_COLOR

            top_row = f"Uploaded by {channel} ({subscribers} subscribers)"
            title_row = title
            bottom_row = f"{full_title}Views: {views} | Likes: {likes} | {uploaded} | {duration}"
        else:
            japanese_title = data.get("title")
            title = metadata_display.get_display_title(data)
            theme = utils.format_slug(data.get("slug"))
            version_num = data.get("version")
            if version_num and version_num not in ["null", "1"]:
                version_num = f"v{version_num}"
            else:
                version_num = ""
            if playlist_marks.check_favorited(state.playback.currently_playing.get("filename", "")):
                marks = "❤"
            else:
                marks = ""
            song_title = get_song_string(data, type="title") or ""
            song_artist = get_song_string(data, type="artist_string") or ""
            if len(song_title) > 40:
                song_title = song_title[:37] + "…"
            song = f"{song_title} by {song_artist}" if song_title else song_artist
            if metadata_display.is_game(data):
                aired = data.get("release")
                bg_color = "Dark Red"
                fg_color = "white"
            else:
                aired = data.get("season")
            _studios_list = data.get("studios")
            if len(_studios_list) > 3:
                studio = ", ".join(_studios_list[:3]) + f" +{len(_studios_list) - 3}"
            else:
                studio = ", ".join(_studios_list)
            _tags_list = get_tags(data)
            if len(_tags_list) > 10:
                tags = ", ".join(_tags_list[:10]) + f" +{len(_tags_list) - 10}"
            else:
                tags = ", ".join(_tags_list)
            type = get_format(data)
            source = data.get("source")
            if data.get("platforms"):
                episodes = ", ".join(_shorten_platform(p) for p in data.get("platforms"))
                if data.get("reviews"):
                    _reviews_num = metadata_display._safe_int(data.get("reviews", 0), 0)
                    members = f"Reviews: {_reviews_num:,}"
                else:
                    members = ""
                if data.get("score"):
                    score = f"Score: {data.get("score")}"
                else:
                    score = ""
            else:
                episodes = get_episode_display(data)
                _members_num = metadata_display._safe_int(data.get("members", 0), 0)
                _pop_display = data.get("popularity") or "N/A"
                members = f"MAL Members: {_members_num:,} (#{_pop_display})"
                score = f"MAL Score: {data.get("score")} (#{data.get("rank")})"
            if info_type != "title_only":
                title_row = title
                if _use_clip_as_song:
                    top_row = f"{theme}{version_num}{metadata_display.overall_theme_num_display(state.playback.currently_playing.get('filename'))} | {song} | {aired}"
                else:
                    top_row = f"{marks}{theme}{version_num}{metadata_display.overall_theme_num_display(state.playback.currently_playing.get('filename'))} | {song} | {aired}"

                if info_type == "artist":
                    artists = get_song_string(data, type="artist")
                    artists_num = len(artists) or 1
                    artist_max = (33 // artists_num) - 2
                    for artist in artists:
                        # Use helper function to get artist themes data
                        artist_data = get_artist_themes_data(artist, state.playback.currently_playing.get("filename"), max_display=artist_max)

                        if artist_data["themes"]:
                            artist_themes_lines = []
                            for item in artist_data["themes"]:
                                themes_str = "/".join(
                                    t["slug"] if isinstance(t, dict) else t
                                    for t in item["themes"]
                                )
                                artist_themes_lines.append(f"{item['anime_title']}: {themes_str}")

                            # Add "...and X more" if there are more entries
                            if artist_data["truncated"]:
                                artist_themes_lines.append(f"...and {artist_data['total_count'] - len(artist_data['themes'])} more")

                            artist_themes_string = "\n".join(artist_themes_lines)
                            top_row = f"All themes by {artist}:\n{artist_themes_string}\n\n{top_row}"

                elif info_type == "studio":
                    studios_num = len(data.get("studios", [])) or 1
                    studio_max = (33 // studios_num) - 2
                    for _studio_name in data.get("studios", []):
                        studio_data = get_studio_entries_data(_studio_name, state.playback.currently_playing.get("filename"), max_display=studio_max)
                        if studio_data["entries"]:
                            studio_entries_string = "\n".join(studio_data["entries"])
                            top_row = f"All {studio_data['header_type']} by {_studio_name}:\n{studio_entries_string}\n\n{top_row}"

                elif info_type == "season":
                    season = data.get("season")
                    current_format = get_format(data)
                    if season:
                        # Get all anime from same season and format from anilist_metadata, sorted by AniList score ranking
                        ranked_anime = []
                        for anilist_id, anilist_data in state.metadata.anilist_metadata.items():
                            mal_id = anilist_data.get("mal_id")
                            if not mal_id:
                                continue

                            anime_data = state.metadata.anime_metadata.get(str(mal_id), {})
                            file_season = anime_data.get("season")

                            anilist_format = anilist_data.get("format", "")
                            file_format = anilist_format.replace("_", " ") if anilist_format else ""

                            if file_season != season or file_format.upper() != current_format.upper():
                                continue

                            t = anime_data.get("eng_title") or anilist_data.get("title") or anime_data.get("title", "Unknown")
                            popularity_rank = anilist_data.get("popularity_rank_season", float('inf'))
                            _anime_score = anilist_data.get("score")
                            ranked_anime.append((t, popularity_rank, _anime_score))

                        ranked_anime = [(t, rank, s) for t, rank, s in ranked_anime if rank != float('inf')]
                        ranked_anime.sort(key=lambda x: x[1])

                        season_titles = [f"{rank}. {t} ({s}%)" if s else f"{rank}. {t}" for t, rank, s in ranked_anime[:30]]

                        if season_titles:
                            top_row = f"Most Popular {current_format} from {season} (on AniList):\n{chr(10).join(season_titles)}\n\n{top_row}"

                elif info_type == "year":
                    season = data.get("season", "")
                    current_format = get_format(data)
                    year = season[-4:] if len(season) >= 4 else ""
                    if year and year.isdigit():
                        all_anime = []
                        for anilist_id, anilist_data in state.metadata.anilist_metadata.items():
                            mal_id = anilist_data.get("mal_id")
                            if not mal_id:
                                continue

                            anime_data = state.metadata.anime_metadata.get(str(mal_id), {})
                            file_season = anime_data.get("season", "")

                            anilist_format = anilist_data.get("format", "")
                            file_format = anilist_format.replace("_", " ") if anilist_format else ""

                            if not file_season.endswith(year) or file_format.upper() != current_format.upper():
                                continue

                            t = anime_data.get("eng_title") or anilist_data.get("title") or anime_data.get("title", "Unknown")
                            popularity_rank = anilist_data.get("popularity_rank_year", float('inf'))
                            _anime_score = anilist_data.get("score")
                            all_anime.append((t, popularity_rank, _anime_score))

                        all_anime = [(t, rank, s) for t, rank, s in all_anime if rank != float('inf')]
                        all_anime.sort(key=lambda x: x[1])

                        year_titles = [f"{rank}. {t} ({s}%)" if s else f"{rank}. {t}" for t, rank, s in all_anime[:30]]

                        if year_titles:
                            top_row = f"Most Popular {current_format} from {year} (on AniList):\n{chr(10).join(year_titles)}\n\n{top_row}"

                middle_row_string = f"{score} | {japanese_title} | {members}\n"
                if not score and not members:
                    if japanese_title != title:
                        middle_row_string = f"{japanese_title}\n"
                    else:
                        middle_row_string = ""

                anilist_row_string = ""
                anilist_id = data.get("anilist")
                if anilist_id and str(anilist_id) in state.metadata.anilist_metadata:
                    anilist_data = state.metadata.anilist_metadata[str(anilist_id)]
                    anilist_score = anilist_data.get("score")
                    anilist_popularity = anilist_data.get("popularity")

                    if anilist_score or anilist_popularity:
                        anilist_parts = []

                        if anilist_score:
                            score_str = f"AniList Score: {anilist_score}%"
                            rank_parts = []
                            if anilist_data.get("score_rank_season"):
                                rank_parts.append(f"#{anilist_data['score_rank_season']} Season")
                            if anilist_data.get("score_rank_year"):
                                rank_parts.append(f"#{anilist_data['score_rank_year']} Year")
                            if anilist_data.get("score_rank_all"):
                                rank_parts.append(f"#{anilist_data['score_rank_all']} All-Time")
                            if rank_parts:
                                score_str += f" ({' / '.join(rank_parts)})"
                            anilist_parts.append(score_str)

                        if anilist_popularity:
                            pop_str = f"AniList Members: {anilist_popularity:,}"
                            rank_parts = []
                            if anilist_data.get("popularity_rank_season"):
                                rank_parts.append(f"#{anilist_data['popularity_rank_season']} Season")
                            if anilist_data.get("popularity_rank_year"):
                                rank_parts.append(f"#{anilist_data['popularity_rank_year']} Year")
                            if anilist_data.get("popularity_rank_all"):
                                rank_parts.append(f"#{anilist_data['popularity_rank_all']} All-Time")
                            if rank_parts:
                                pop_str += f" ({' / '.join(rank_parts)})"
                            anilist_parts.append(pop_str)

                        if anilist_parts:
                            anilist_row_string = " | ".join(anilist_parts) + "\n"

                bottom_row = f"{middle_row_string}{anilist_row_string}{studio} | {tags} | {episodes} | {type} | {source}"
            else:
                title_row = title_overlay.get_base_title()
                japanese_title = title_overlay.get_base_title(title=japanese_title)
                if state.config.title_top_info_txt:
                    top_row = state.config.title_top_info_txt
                if japanese_title != title:
                    bottom_row = f"{japanese_title}"
    else:
        title_row = state.playback.currently_playing.get("filename", "No Media Playing").split(".")[0]

    _title_popup_slide_in(top_row, title_row, bottom_row, bg_color, fg_color) if not _already_up else _draw_title_popup_osd(top_row, title_row, bottom_row, bg_color, fg_color, 0)
    _mx, _my, _mw, _mh = _get_mpv_window_rect()
    _title_popup_last_mpv_size = (_mw, _mh)
    _register_mpv_tracked_window("title_popup", None, _title_popup_on_mpv_rect)


# ===========================================================================
# Lightweight data helpers (also used by sibling modules via main re-exports)
# ===========================================================================
def get_format(data):
    """Get the format from AniList metadata, replacing underscores with spaces. Falls back to anime metadata format."""
    anilist_id = data.get("anilist")
    if anilist_id and str(anilist_id) in state.metadata.anilist_metadata:
        anilist_data = state.metadata.anilist_metadata[str(anilist_id)]
        anilist_format = anilist_data.get("format")
        if anilist_format == "TV_SHORT":
            return "TV Short"
    # Fallback to regular anime metadata format
    return data.get("type", "")


def get_episode_display(data, suffix=" Episodes"):
    """Return a human-readable episode count string.
    Games with no episode data show 'N/A'; still-airing shows show 'Airing'.
    When an episode count exists it is returned as '<n> Episodes' (suffix can be overridden or set to '' for bare number).
    """
    episodes = data.get("episodes")
    if episodes:
        return f"{episodes}{suffix}" if suffix else str(episodes)
    return "N/A" if metadata_display.is_game(data) else "Airing"


def _shorten_platform(name):
    if name == "PC (Microsoft Windows)":
        return "PC"
    if name.startswith("Nintendo "):
        return name[len("Nintendo "):]
    if name.startswith("PlayStation "):
        return "PS" + name[len("PlayStation "):]
    return name


def get_tags_string(data):
    return ", ".join(get_tags(data))


def get_tags(data):
    def _normalize_tag_values(value):
        if not value:
            return []
        if isinstance(value, dict):
            return []
        if isinstance(value, (list, tuple, set)):
            return [item for item in value if item]
        return [value]

    tags = []
    for category in ["genres", "themes", "demographics"]:
        tags.extend(_normalize_tag_values(data.get(category)))
    return tags


def get_song_string(data, type=None, totals=False, artist_limit=3):
    for theme in data.get("songs", []):
        if theme.get("slug") == data.get("slug"):
            if type:
                if type == "artist_string":
                    return metadata_fetch.get_artists_string(theme.get("artist"), total=totals, limit=artist_limit)
                else:
                    return theme.get(type)
            else:
                return (theme.get("title", "N/A") or "N/A") + " by " + metadata_fetch.get_artists_string(theme.get("artist"), total=totals, limit=artist_limit)
    return ""
