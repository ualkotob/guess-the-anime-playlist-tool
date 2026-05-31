"""Metadata display + theme-file resolution + series helpers.

Extracted from `guess_the_anime.py` (the METADATA DISPLAY section).

The module owns the right-column/middle-column metadata display logic, the
"up next" widget rendering (and its web-server push), plus the data layer used
across the app for resolving theme filenames, series grouping, and per-anime
metadata.

Pattern: this module uses live attribute access on the main module via the
``_main`` reference (populated by ``set_context``). Most state read here lives
on main; we never copy it.

State staying in main (read by sibling modules through getter callbacks bound
to main's attributes — see [[state-stays-with-its-readers]]):
  - ``updating_metadata``        — bool, async-update lock; read by
                                    ``metadata_fetch``.
  - ``selected_extra_metadata``  — str, panel tab selector; read by
                                    ``metadata_panel``, ``streaming``.
  - ``show_spoiler_tags``        — bool, tag-spoiler toggle; read by
                                    ``metadata_panel``.
  - ``reroll_button``            — widget ref written by
                                    ``update_up_next_display``; held on
                                    main so the GC keeps it alive.
  - ``current_list_title``       — str, right-column header text; written
                                    by ``clear_metadata`` and read in many
                                    places in main.

External state read via ``_main``: left_column, middle_column, right_column,
right_top, popout_up_next, popout_show_metadata, popout_show_up_next, root,
list_loaded, list_set_loaded, _insert_list_title_row, refresh_current_list,
is_docked, scl, show_field_themes, reroll_next, is_reroll_valid,
load_image_from_url, currently_playing, playlist, file_metadata,
anime_metadata, directory_files, get_metadata, get_file_metadata_by_name,
get_file_censors, get_cached_deduplicated_files, check_favorited, check_new,
check_tagged, check_blind_mark, check_peek_mark, check_mute_peek_mark,
metadata_panel, variety_round, lightning_manager, search_ops, web_server,
youtube_queue, get_youtube_metadata_by_filename, get_youtube_display_title,
get_youtube_duration, is_youtube_file, fixed_lightning_queue,
fixed_lightning_round_playlist_data, get_format, get_artists_string,
get_clean_filename, format_seconds, format_slug, get_version_from_filename,
play_video, is_animethemes_stream_file.
"""
from __future__ import annotations

import os
import re
import threading
import webbrowser

import tkinter as tk
from tkinter import messagebox

from _app_scripts.file.metadata import metadata_fetch


# ---------------------------------------------------------------------------
# Context — `_main` is the live main module; populated by set_context.
# ---------------------------------------------------------------------------
_main = None


def set_context(*, main_module):
    g = globals()
    g['_main'] = main_module


# ---------------------------------------------------------------------------
# Module-local constants
# ---------------------------------------------------------------------------

LISTS_TO_CLOSE = ['load_playlist', 'merge_playlist', 'load_system_playlist', 'delete_playlist', 'load_filters', 'delete_filters', 'sort', 'show_fixed_lightning_list', 'show_youtube_playlist', 'show_archived_youtube_playlist']

def clear_metadata():
    """Function to clear metadata fields"""
    _main.left_column.delete(1.0, tk.END)
    _main.middle_column.delete(1.0, tk.END)
    if not _main.list_loaded or _main.list_loaded in LISTS_TO_CLOSE:
        _main.list_set_loaded(None)
        _main.right_column.delete(1.0, tk.END)
        _main.current_list_title = ""
        _main._insert_list_title_row(_main.right_column)

def open_mal_page(mal_id):
    url = f"https://myanimelist.net/anime/{mal_id}"
    webbrowser.open(url)

def anime_themes_video(filename):
    url = f"https://v.animethemes.moe/{filename}"
    webbrowser.open(url)

def open_animethemes_anime_page(slug):
    url = f"https://animethemes.moe/anime/{slug}"
    webbrowser.open(url)

def open_anidb_page(anidb_id):
    url = f"https://anidb.net/anime/{anidb_id}"
    webbrowser.open(url)

def open_anilist_page(anilist_id):
    url = f"https://anilist.co/anime/{anilist_id}"
    webbrowser.open(url)

def reset_metadata(filename = None):
    """Function to reset metadata and add filename"""
    toggleColumnEdit(True)
    clear_metadata()
    if filename is None:
        filename = _main.currently_playing.get('filename')
    _main.left_column.insert(tk.END, "FILE: ", "bold")
    _main.left_column.insert(tk.END, f"{filename}", "white")
    if "[MAL]" not in filename and "[ID]" not in filename and "[IGDB]" not in filename:
        if _main.currently_playing.get("type") == "youtube":
            _main.left_column.window_create(tk.END, window=tk.Button(_main.left_column, text="[YT]", borderwidth=0, pady=0, command=lambda: webbrowser.open(_main.currently_playing.get("data").get("url")), bg="black", fg="white"))
    _main.left_column.insert(tk.END, "\n\n", "blank")
 
def _play_name_key(f):
    """Normalise a filename for play-count matching.

    Strips bracketed ID tags ([MAL]nnn, [IGDB]xxx, [ADB]nnn, [ALT]nnn,
    [ART]…, [SNG]…, [ID]nnn) and the file extension so that files renamed
    to add or change an ID tag still count as the same file.
    """
    base = os.path.splitext(f)[0]
    return re.sub(r'\[(?:MAL|IGDB|ADB|ALT|ART|SNG|ID)\][^[]*', '', base).strip('-').strip()

def _build_web_series_themes(data, playing_filename):
    """Serialize series theme information for the web server metadata push."""
    if not data:
        return []
    playing_slug = data.get("slug")

    # Pre-build a play-count map keyed by normalised filename (cheap dict lookup per theme)
    _play_counts = {}
    _play_last = {}
    if _main.playlist.get("infinite"):
        _pl = _main.playlist.get("playlist", [])
        _cur_idx = _main.playlist.get("current_index", 0)
        _played = _pl[:_cur_idx + 1]
        for _i, _item in enumerate(_played):
            _f = _item[3:] if _item.startswith("[L]") else _item
            _k = _play_name_key(_f)
            _play_counts[_k] = _play_counts.get(_k, 0) + 1
            _play_last[_k] = _i

    def _serialize_anime(anime_dict, anime_id, is_playing_anime):
        mal_key = str(anime_id)
        theme_list = list(anime_dict.get("songs", []))

        # Include local-only slugs that aren't in the fetched songs list
        known_slugs = {t.get("slug") for t in theme_list}
        fm_entry = _main.file_metadata.get(mal_key, {})
        for slug_key in fm_entry.get("themes", {}):
            if slug_key not in known_slugs:
                s = slug_key[:2].upper()
                t_type = "OP" if s == "OP" else ("ED" if s == "ED" else "OTHER")
                theme_list.append({"type": t_type, "slug": slug_key, "title": None,
                                   "artist": [], "episodes": None, "versions": []})

        theme_list.sort(key=metadata_fetch._song_slug_sort_key)

        sections_map = {}
        for theme in theme_list:
            t = theme.get("type", "OTHER")
            sections_map.setdefault(t, []).append(theme)

        sections_out = []
        for type_str, type_themes in sections_map.items():
            header = "OPENINGS" if type_str == "OP" else ("ENDINGS" if type_str == "ED" else f"{type_str}S")
            themes_out = []
            for theme in type_themes:
                theme_slug = theme.get("slug")
                is_playing_theme = is_playing_anime and (theme_slug == playing_slug)

                fn = get_theme_filename(mal_key, theme_slug)
                overall_suffix = overall_theme_num_display(fn) if fn else ""

                versions = theme.get("versions", [])
                serialized_versions = []
                if versions:
                    for v in versions:
                        v_num = v.get("version")
                        if len(versions) == 1:
                            v_fn = get_theme_filename(mal_key, theme_slug, v_num)
                        else:
                            v_fn = get_theme_filename(mal_key, theme_slug, v_num, need_version=True)
                            if v_num == 1 and not v_fn:
                                v_fn = get_theme_filename(mal_key, theme_slug, None, need_version=True)

                        is_playing_ver = False
                        if is_playing_theme and v_fn:
                            try:
                                actual_v_num = v_num if v_num is not None else 1
                                is_playing_ver = (int(_main.get_version_from_filename(playing_filename)) == actual_v_num)
                            except (TypeError, ValueError):
                                is_playing_ver = (v_fn == playing_filename)

                        serialized_versions.append({
                            "version": v_num,
                            "episodes": v.get("episodes"),
                            "flags": _get_version_flags(v),
                            "filename": v_fn,
                            "plays": _play_counts.get(_play_name_key(v_fn), 0) if v_fn else 0,
                            "plays_ago": (_cur_idx - _play_last[_play_name_key(v_fn)]) if v_fn and _play_name_key(v_fn) in _play_last and _play_last[_play_name_key(v_fn)] < _cur_idx else None,
                            "favorited": bool(_main.check_favorited(v_fn)) if v_fn else False,
                            "file_props": get_file_props_label(v_fn) if v_fn else "",
                            "is_playing": bool(is_playing_ver),
                        })

                _th_artists = theme.get("artist") or []
                themes_out.append({
                    "slug": theme_slug,
                    "overall_suffix": overall_suffix,
                    "title": theme.get("title"),
                    "filename": fn,
                    "plays": _play_counts.get(_play_name_key(fn), 0) if fn else 0,
                    "plays_ago": (_cur_idx - _play_last[_play_name_key(fn)]) if fn and _play_name_key(fn) in _play_last and _play_last[_play_name_key(fn)] < _cur_idx else None,
                    "favorited": bool(_main.check_favorited(fn)) if fn else False,
                    "artists": _th_artists,
                    "artists_str": _main.get_artists_string(_th_artists, total=False),
                    "is_playing": bool(is_playing_theme),
                    "special": bool(theme.get("special")),
                    "versions": serialized_versions,
                    "flags": _get_version_flags(theme) if not versions else [],
                    "episodes": theme.get("episodes") if not versions else None,
                })
            sections_out.append({"type": type_str, "header": header, "themes": themes_out})

        _section_order = {"OP": 0, "ED": 1}
        sections_out.sort(key=lambda s: _section_order.get(s["type"], 2))

        return {
            "anime_id": mal_key,
            "igdb_id": anime_dict.get("igdb"),
            "igdb_slug": anime_dict.get("igdb_slug"),
            "title": get_display_title(anime_dict),
            "format": _main.get_format(anime_dict),
            "season": anime_dict.get("season"),
            "is_playing_anime": bool(is_playing_anime),
            "sections": sections_out,
        }

    playing_mal = str(data.get("mal"))
    if not data.get("series"):
        return [_serialize_anime(data, playing_mal, True)]
    all_series = get_all_theme_from_series(data)
    if len(all_series) <= 1:
        return [_serialize_anime(data, playing_mal, True)]
    return [_serialize_anime(anime, str(aid), str(aid) == playing_mal)
            for aid, anime in all_series]


def _build_played_series_map(played, cur_idx):
    """Build a dict mapping every series name seen in played entries to
    {count, last_idx} for series-play lookups.  All get_metadata calls hit
    the in-memory cache so this is fast even for large playlists."""
    series_map = {}   # series_name -> {'count': int, 'last_idx': int}
    for _i, _item in enumerate(played):
        _f = _item[3:] if _item.startswith("[L]") else _item
        _md = _main.get_metadata(_f)
        if not _md:
            continue
        for _s in series_set(_md):
            if _s not in series_map:
                series_map[_s] = {'count': 0, 'last_idx': -1}
            series_map[_s]['count'] += 1
            series_map[_s]['last_idx'] = _i
    return series_map


def _calc_plays_info(filename, data, pl, cur_idx):
    """Return dicts with file-play and series-play stats for the given filename.

    Only counts playlist entries up to and including cur_idx (i.e. already played).

    Returns (file_plays, series_plays) where each is a dict:
      count      – int total occurrences (normal + lightning)
      ago        – int | None  distance to most-recent prior normal occurrence
      lightning  – int lightning-round occurrences
    series_plays is None when no other series matches exist.
    """
    _clean = lambda f: f[3:] if f.startswith("[L]") else f

    _cur_key = _play_name_key(filename)

    # Only consider entries at or before the current index (already played)
    played = pl[:cur_idx + 1]

    # ── file plays ────────────────────────────────────────────────────────────
    f_normal = sum(1 for item in played if _play_name_key(_clean(item)) == _cur_key and not item.startswith("[L]"))
    f_light  = sum(1 for item in played if item.startswith("[L]") and _play_name_key(_clean(item)) == _cur_key)
    f_count  = f_normal + f_light
    f_prev   = [i for i, item in enumerate(played) if _play_name_key(_clean(item)) == _cur_key
                and not item.startswith("[L]") and i < cur_idx]
    f_ago    = (cur_idx - max(f_prev)) if f_prev else None

    file_plays = {"count": f_count-f_light, "ago": f_ago, "lightning": f_light}

    # ── series plays ──────────────────────────────────────────────────────────
    # Count ALL played entries sharing a series with this file, including the
    # current file itself.
    series_plays = None
    if data:
        _cur_series_set = series_set(data)
        s_normal = f_normal   # seed with this file's own normal plays
        s_light  = f_light    # …and its lightning plays
        s_prev   = list(f_prev)  # …and its prior-occurrence indices
        for _i, _item in enumerate(played):
            _cf = _clean(_item)
            if _play_name_key(_cf) == _cur_key:
                continue  # already seeded above
            _fd = _main.get_metadata(_cf)
            if not _fd:
                continue
            if _cur_series_set & series_set(_fd):
                if _item.startswith("[L]"):
                    s_light += 1
                else:
                    s_normal += 1
                    if _i < cur_idx:
                        s_prev.append(_i)
        total = s_normal + s_light
        # Only show series line when there are other-file entries
        if total > f_count:
            s_ago = (cur_idx - max(s_prev)) if s_prev else None
            series_plays = {"count": total-s_light, "ago": s_ago, "lightning": s_light}

    return file_plays, series_plays


def _fmt_plays(p):
    """Format a plays dict {count, ago, lightning} into a display string."""
    s = str(p["count"])
    if p["ago"] is not None:
        s += f" ({p['ago']} Ago)"
    if p["lightning"]:
        s += f" ({p['lightning']} L)"
    return s


def update_metadata_queue(index):
    """Function to update metadata display asynchronously"""
    if _main.updating_metadata:
        _main.root.after(100, update_metadata_queue, index)
    elif index == _main.playlist["current_index"]:
        _main.updating_metadata = True
        threading.Thread(target=_main.update_metadata, daemon=True).start()



def toggle_spoiler_tags():
    _main.show_spoiler_tags = not _main.show_spoiler_tags
    _main.update_extra_metadata()

def select_extra_metadata(extra_metadata):
    _main.selected_extra_metadata = extra_metadata
    _main.update_extra_metadata()

def open_image_popup(url, title="Image"):
    """Display any image URL in a centered popup. Can be called directly."""
    if not url:
        messagebox.showwarning("No Image", "No image URL provided.")
        return
    try:
        popup = tk.Toplevel()
        popup.title(title)
        popup.configure(bg="black")
        tk_img = _main.load_image_from_url(url, size=(600, 800))
        if tk_img:
            label = tk.Label(popup, image=tk_img, bg="black")
            label.image = tk_img
            label.pack(pady=10)
        else:
            tk.Label(popup, text="[Failed to load image]",
                    font=("Arial", 12), bg="black", fg="white").pack(pady=10)
        popup.update_idletasks()
        w = popup.winfo_width()
        h = popup.winfo_height()
        sw = popup.winfo_screenwidth()
        sh = popup.winfo_screenheight()
        popup.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
    except Exception as e:
        messagebox.showerror("Image Load Error", f"Could not load image: {e}")

def create_cover_popup(title, cover_url):
    def _popup():
        open_image_popup(cover_url, title)
    return _popup



def up_next_text():
    update_up_next_display(_main.right_top)
    if _main.popout_up_next and _main.popout_show_metadata:
        update_up_next_display(_main.popout_up_next)
    # Refresh list display to adjust button count based on right_top content
    if _main.list_loaded:
        # Small delay to ensure text widget is fully updated
        _main.root.after(10, _main.refresh_current_list)
    if _main.web_server.is_running():
        try:
            _push_web_up_next()
        except Exception:
            pass


def _push_web_up_next():
    """Compute up-next data and push to web host clients."""
    fixed_data = _main.fixed_lightning_round_playlist_data or _main.fixed_lightning_queue
    fixed_rounds = fixed_data.get("rounds", []) if fixed_data else []
    fixed_current_index = fixed_data.get("current_index", -1) if fixed_data else -1
    fixed_coming_up = fixed_data and (fixed_current_index + 1) < len(fixed_rounds)

    has_next = _main.youtube_queue or _main.search_ops.search_queue or fixed_coming_up or _main.playlist["current_index"] + 1 < len(_main.playlist["playlist"])
    if not has_next:
        _main.web_server.push_up_next({"end_of_playlist": True})
        return

    mode_label = ""
    try:
        if _main.youtube_queue:
            playlist_entry = _main.youtube_queue.get("filename")
        elif _main.search_ops.search_queue:
            playlist_entry = _main.search_ops.search_queue
        elif fixed_coming_up:
            next_round = fixed_rounds[fixed_current_index + 1]
            playlist_entry = next_round.get("theme")
            mode_label = f"[{next_round.get('type', '').upper()}]"
        else:
            playlist_entry = _main.playlist["playlist"][_main.playlist["current_index"] + 1]

        next_filename = _main.get_clean_filename(playlist_entry)

        if _main.youtube_queue or _main.is_youtube_file(next_filename):
            yt_data = _main.youtube_queue or _main.get_youtube_metadata_by_filename(next_filename) or {}
            yt_title = _main.get_youtube_display_title(yt_data) or next_filename
            yt_duration = _main.format_seconds(_main.get_youtube_duration(yt_data)) if yt_data else ""
            detail = f"Duration: {yt_duration}" if yt_duration else ""
            _main.web_server.push_up_next({"title": yt_title, "detail": detail, "mode_label": mode_label})
        else:
            d = _main.get_metadata(next_filename)
            title = get_display_title(d)
            slug = _main.format_slug(d.get("slug", ""))
            version_num = d.get("version")
            if version_num and version_num not in ["1", "null"]:
                version_num = f"v{version_num}"
            else:
                version_num = ""
            if _main.lightning_manager.lightning_queue and _main.lightning_manager.lightning_queue[0] == next_filename and _main.variety_round.variety_light_mode_enabled:
                mode_label = mode_label or f"[{_main.lightning_manager.lightning_queue[1].upper()}]"
            _members_num = _safe_int(d.get('members', 0), 0)
            members = f"{_members_num:,}"
            popularity = f"#{d.get('popularity')}" if d.get('popularity') else ""
            season = d.get("season", "")
            detail_parts = [f"{slug}{version_num}"]
            if members or popularity:
                detail_parts.append(f"{members} ({popularity})" if popularity else members)
            if season:
                detail_parts.append(season)
            _main.web_server.push_up_next({
                "title": title,
                "marks": get_file_marks(next_filename),
                "detail": " | ".join(detail_parts),
                "mode_label": mode_label,
                "reroll": _main.is_reroll_valid(),
            })
    except Exception:
        _main.web_server.push_up_next({})

def update_up_next_display(widget, clear=False):
    widget.config(state=tk.NORMAL, wrap="word")
    widget.delete(1.0, tk.END)
    if not _main.popout_show_metadata:
        widget.config(height=0)
        widget.config(state=tk.DISABLED)
        return
    is_popout = widget == _main.popout_up_next
    PLACEHOLDER_TEXT = "NEXT: CLICK TO SHOW/HIDE"
    if is_popout and not _main.popout_show_up_next:
        widget.config(height=1)
        widget.insert(tk.END, PLACEHOLDER_TEXT, "center")
        widget.config(state=tk.DISABLED)
        return
    if clear:
        widget.config(height=1)
        widget.insert(tk.END, "", "center")
        widget.config(state=tk.DISABLED)
        return
    widget.config(height=0)
    if not clear:
        if not _main.is_docked() or is_popout:
            if not (_main.fixed_lightning_round_playlist_data or _main.fixed_lightning_queue) or _main.youtube_queue or _main.search_ops.search_queue:
                next_filename = None
                if _main.playlist["current_index"] + 1 < len(_main.playlist["playlist"]):
                    playlist_entry = _main.playlist["playlist"][_main.playlist["current_index"] + 1]
                    next_filename = _main.get_clean_filename(playlist_entry)
                if next_filename and _main.is_reroll_valid():
                    _main.reroll_button = tk.Button(
                            widget, text="🔄", font=("Arial", 11, "bold"), borderwidth=0,
                            pady=0, command=_main.reroll_next, bg="black", fg="white"
                        )
                    if not is_popout:
                        widget.window_create(
                            tk.END,
                            window=_main.reroll_button
                        )
                else:
                    _main.reroll_button = None
            if not is_popout:
                widget.insert(tk.END, "NEXT: ", "bold")

            next_up_text = "End of playlist"
            fixed_data = _main.fixed_lightning_round_playlist_data or _main.fixed_lightning_queue
            fixed_rounds = fixed_data.get("rounds", []) if fixed_data else []
            fixed_current_index = fixed_data.get("current_index", -1) if fixed_data else -1
            fixed_coming_up = fixed_data and (fixed_current_index + 1) < len(fixed_rounds)
            if _main.youtube_queue or _main.search_ops.search_queue or fixed_coming_up or _main.playlist["current_index"] + 1 < len(_main.playlist["playlist"]):
                try:
                    if _main.youtube_queue:
                        playlist_entry = _main.youtube_queue.get("filename")
                    elif _main.search_ops.search_queue:
                        playlist_entry = _main.search_ops.search_queue
                    elif fixed_coming_up:
                        next_round = fixed_rounds[fixed_current_index + 1]
                        playlist_entry = next_round.get("theme")
                        next_mode = next_round.get("type")
                        widget.insert(tk.END, f"[{next_mode.upper()}] ", "white")
                    else:
                        playlist_entry = _main.playlist["playlist"][_main.playlist["current_index"] + 1]
                    next_filename = _main.get_clean_filename(playlist_entry)
                    if _main.youtube_queue or _main.is_youtube_file(next_filename):
                        youtube_data = _main.youtube_queue or _main.get_youtube_metadata_by_filename(next_filename) or {}
                        yt_title = _main.get_youtube_display_title(youtube_data) or next_filename
                        yt_duration = _main.format_seconds(_main.get_youtube_duration(youtube_data)) if youtube_data else ""
                        next_up_text = f"{yt_title}"
                        if yt_duration:
                            next_up_text += f"\nDuration: {yt_duration}"
                    else:
                        next_up_data = _main.get_metadata(next_filename)
                        version_num = next_up_data.get("version")
                        if version_num and version_num not in ["1", "null"]:
                            version_num = f"v{version_num}"
                        else:
                            version_num = ""
                        title = get_display_title(next_up_data)
                        if is_popout and len(title) > 35:
                            title = title[:32] + "..."
                        if _main.lightning_manager.lightning_queue and _main.lightning_manager.lightning_queue[0] == next_filename and _main.variety_round.variety_light_mode_enabled:
                            widget.insert(tk.END, f"[{_main.lightning_manager.lightning_queue[1].upper()}] ", "white")
                        _members_num = _safe_int(next_up_data.get('members', 0), 0)
                        next_up_text = (
                            f"{get_file_marks(next_filename)}{title}\n"
                            f"{_main.format_slug(next_up_data.get('slug'))}{version_num} | {_members_num:,} "
                            f"(#{next_up_data.get('popularity')}) | {next_up_data.get('season')}"
                        )
                    if is_popout:
                        next_up_text = f"NEXT: {next_up_text.replace("\n", " - ")}"
                except Exception:
                    if _main.youtube_queue:
                        next_up_text = _main.youtube_queue.get("filename")
                    elif _main.search_ops.search_queue:
                        next_up_text = _main.search_ops.search_queue
                    else:
                        playlist_entry = _main.playlist["playlist"][_main.playlist["current_index"] + 1]
                        next_up_text = _main.get_clean_filename(playlist_entry)
            widget.insert(tk.END, f"{next_up_text}", "white")
            adjust_up_next_height(widget, is_popout)
            widget.config(state=tk.DISABLED)
            return
    widget.config(state=tk.DISABLED, wrap="word")

def adjust_up_next_height(widget, is_popout):
    widget.config(state=tk.NORMAL, wrap="word")
    widget.update_idletasks()   # ensure display lines are measured at actual rendered width
    total_lines = widget.count("1.0", "end", "displaylines")[0]
    if is_popout:
        # subtract the trailing-newline phantom line, but always keep at least 2
        total_lines = 2
        widget.config(state=tk.NORMAL, height=total_lines, wrap="word")
    else:
        # main player needs +1 to avoid clipping the last display line
        widget.config(state=tk.NORMAL, height=total_lines + 1, wrap="word")
    widget.config(state=tk.DISABLED, wrap="word")

def get_display_title(data):
    def _pick(v):
        s = str(v or "").strip()
        return s if s and s.upper() != "N/A" else None

    return (
        _pick(data.get("eng_title"))
        or _pick(data.get("title"))
        or next((_pick(s) for s in (data.get("synonyms") or []) if _pick(s)), None)
        or "No Title Found"
    )

def _safe_int(value, default=0):
    """Best-effort int conversion for metadata values like None, '', 'N/A', or comma-formatted numbers."""
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value or value.upper() == "N/A":
                return default
        return int(value)
    except (TypeError, ValueError):
        return default

def is_game(data):
    return _main.get_format(data) == "Game" or _main.get_format(data) == "Visual Novel" or data.get("platforms")

def add_field_total_button(column, group, blank = True, show_count=True, button_text=None, title=None):
    count = len(group)
    if count > 0:
        if not button_text:
            if show_count:
                button_text = f"[{count}]"
            else:
                button_text = "▶"
        btn = tk.Button(column, text=button_text, borderwidth=0, pady=0, command=lambda: _main.show_field_themes(group=group, title=title), bg="black", fg="white", font=("Arial", _main.scl(11), "bold"))
        column.window_create(tk.END, window=btn)
    if blank:
        column.insert(tk.END, "\n\n", "blank")

# ── Series utility helpers ────────────────────────────────────────────────────

def series_list(data, fallback_title=True):
    """Always returns a list of series strings, never None/str.
    If the entry has no series and fallback_title is True, uses the title."""
    s = data.get("series") if data else None
    if isinstance(s, str):
        s = [s] if s else []
    if not s:
        s = [data.get("title")] if (fallback_title and data and data.get("title")) else []
    return [x for x in s if x]  # drop None/empty

def series_set(data, fallback_title=True):
    """Set version of series_list for fast overlap checks."""
    return set(series_list(data, fallback_title))

def series_primary(data):
    """One deterministic 'display/grouping' series string."""
    lst = series_list(data)
    return lst[0] if lst else (data.get("title") if data else None)

def series_overlap(a, b):
    """True if data dicts a and b share at least one series."""
    return bool(series_set(a) & series_set(b))

def series_cache_key(data):
    """Stable, hashable key for cache dicts (order-independent)."""
    return tuple(sorted(series_list(data)))

# ─────────────────────────────────────────────────────────────────────────────

def get_all_matching_field(field, match):
    filenames = []
    match_set = set(match) if isinstance(match, list) else None
    for filename in _main.directory_files:
        file_data = _main.get_metadata(filename)
        if file_data:
            if field == "type":
                file_field = _main.get_format(file_data)
                if file_field and file_field == match:
                    filenames.append(filename)
            elif field == "series" and match_set:
                if series_set(file_data) & match_set:
                    filenames.append(filename)
            else:
                file_field = file_data.get(field, "")
                if file_field and file_field == match:
                    filenames.append(filename)

    return sorted(filenames)

def get_all_theme_from_series(data):
    target_set = series_set(data, fallback_title=False)
    if not target_set:
        return []

    # Step 1: Find all anime sharing at least one series
    related_anime = []
    for anime_id, anime in _main.anime_metadata.items():
        if series_set(anime, fallback_title=False) & target_set:
            related_anime.append((anime_id, anime))

    # Step 2: Deduplicate — if an IGDB entry and a non-IGDB entry refer to the
    # same game, keep only the IGDB entry. Two entries are considered the same if
    # they share the same metadata title OR if their filenames share the same
    # title portion (the part between the ID bracket and the slug suffix).

    def _filename_title_norm(anime_id):
        """Return a normalised title extracted from the first filename for this entry."""
        fm = _main.file_metadata.get(str(anime_id), {})
        for _slug, _versions in fm.get("themes", {}).items():
            for _vk, _files in _versions.items():
                for fn in _files:
                    # Strip leading ID bracket: "[12345] Title-OP1.ext" or "[IGDB]id Title-OP1.ext"
                    name = re.sub(r"^\[[^\]]*\]\S*\s*", "", fn)
                    # Strip trailing slug+version+extension: "-OP1v2.webm"
                    name = re.sub(r"-[A-Za-z]+\d+.*$", "", name, flags=re.IGNORECASE)
                    name = name.strip().lower()
                    if name:
                        return name
        return None

    igdb_entries = [(aid, a) for aid, a in related_anime if str(aid).startswith("IGDB:")]
    if igdb_entries:
        igdb_match_keys = set()
        for igdb_id, igdb_anime in igdb_entries:
            igdb_match_keys.add(igdb_anime.get("title", "").strip().lower())
            fn_title = _filename_title_norm(igdb_id)
            if fn_title:
                igdb_match_keys.add(fn_title)

        def _is_duplicate_of_igdb(anime_id, anime):
            if str(anime_id).startswith("IGDB:"):
                return False
            # Only deduplicate entries that are actually games — an anime adaptation
            # can share a title with a game (e.g. Scarlet Nexus) and must not be removed.
            if not is_game(anime):
                return False
            if anime.get("title", "").strip().lower() in igdb_match_keys:
                return True
            fn_title = _filename_title_norm(anime_id)
            if fn_title and fn_title in igdb_match_keys:
                return True
            return False

        related_anime = [
            (anime_id, anime)
            for anime_id, anime in related_anime
            if not _is_duplicate_of_igdb(anime_id, anime)
        ]

    # Step 3: Sort anime by release (season/year)
    def sort_key(anime):
        season = anime.get("season", "")
        year = int(season[-4:]) if season and season[-4:].isdigit() else 9999
        season_order = ["Winter", "Spring", "Summer", "Fall"]
        for i, s in enumerate(season_order):
            if s in season:
                return (year, i)
        return (year, 99)

    related_anime.sort(key=lambda x: sort_key(x[1]))
    return related_anime

def get_overall_theme_number(filename):
    """Returns the overall opening/ending number across the series based on the filename."""
    data = _main.get_metadata(filename)
    if not data or is_game(data):
        return None
    
    target_slug = data.get("slug")
    slug_extra = get_slug_extra(target_slug)
    theme_type = target_slug[:2]  # "OP" or "ED"
    if theme_type not in ["OP", "ED"]:
        return None
    
    target_series = data.get("series")
    mal_id = data.get("mal")
    if not mal_id or not target_slug:
        return None

    if not target_series:
        # Standalone anime — calculate within this anime's own songs only
        _solo_anime = _main.anime_metadata.get(str(mal_id)) or _main.anime_metadata.get(mal_id)
        if not _solo_anime:
            return None
        related_anime = [(mal_id, _solo_anime)]
    else:
        related_anime = get_all_theme_from_series(data)
    
    is_parody = "Parody" in data.get("themes", [])

    def clean_title(title):
        for end in [" (TV)", " 1st", ":", " no Kajitsu"]:
            title = title.split(end)[0]
        return title

    # Step 3: Count themes of the same type, stopping at the target
    overall_index = 0
    decimal = 0
    base_title = None
    display_base_title = None
    for anime_id, anime in related_anime:
        current_slug_num = 0
        theme_gap = 0
        anime_title = clean_title(anime.get("title"))
        anime_display_title = clean_title(get_display_title(anime))
        if (has_same_start(data.get("title"), anime.get("title"), length=1) or has_same_start(get_display_title(data), get_display_title(anime), length=1)) and not is_game(anime) and (is_parody == ("Parody" in anime.get("themes")) and _main.get_format(data) == _main.get_format(anime)):
            if not base_title or not display_base_title:
                if anime_title in data.get("title"):
                    base_title = anime_title
                elif anime_display_title in get_display_title(data):
                    display_base_title = anime_display_title
                elif not base_title or display_base_title:
                    continue
            if (base_title and base_title in anime_title) or (display_base_title and display_base_title in anime_display_title):
                for song in anime.get("songs", []):
                    if song["type"] == theme_type:
                        # Skip if slug_extra doesn't match (only count themes with same variant)
                        if not (slug_extra == get_slug_extra(song.get("slug"))):
                            continue
                        
                        # Extract number from slug like "OP1", "ED23", etc.
                        song_slug = song.get("slug", "")
                        slug_num = int(''.join(filter(str.isdigit, song_slug.split('-')[0].split('_')[0][2:])))
                        
                        # Track gap only for themes with matching slug_extra
                        theme_gap += slug_num - current_slug_num
                        current_slug_num = slug_num
                        
                        if (song.get("overlap") == "Over") or song.get("special") or (song.get("overlap") == "Transition" and song.get("spoiler")):
                            theme_gap -= 1
                            decimal += 0.1
                        elif song.get("skip"):
                            theme_gap -= 1
                            continue
                        else:
                            overall_index += theme_gap
                            theme_gap = 0
                            decimal = 0
                        if anime_id == mal_id and song["slug"] == target_slug:
                            return overall_index+decimal

    return None


def get_slug_extra(slug):
    slug_extra = ""
    if "-" in slug:
        slug_extra = slug.split("-")[1]
    elif "_" in slug:
        slug_extra = slug.split("_")[1]
    return slug_extra

def has_same_start(s1, s2, length=3):
    return s1[:length].lower() == s2[:length].lower()

def get_filenames_from_artist(match):
    filenames = []
    for filename in _main.get_cached_deduplicated_files():
        file_data = _main.get_metadata(filename)
        if file_data:
            for theme in file_data.get("songs", []) or []:
                if file_data.get("slug") == theme.get("slug"):
                    for artist in theme.get("artist", []) or []:
                        if artist == match:
                            filenames.append(filename)

    return sorted(filenames)

def get_filenames_from_studio(match):
    filenames = []
    for filename in _main.get_cached_deduplicated_files():
        file_data = _main.get_metadata(filename)
        if file_data:
            for studio in file_data.get("studios", []) or []:
                if studio == match:
                    filenames.append(filename)

    return sorted(filenames)



def add_multiple_data_line(column, data, title, get, blank = True):
    column.insert(tk.END, title, "bold")
    count = 0
    for item in data.get(get, []):
        count += 1
        name = item
        if count > 1:
            name = ", " + name 
        column.insert(tk.END, name, "white")
    if count == 0:
        column.insert(tk.END, "N/A", "white")
    if blank:
        column.insert(tk.END, "\n\n", "blank")

def add_single_data_line(column, data, title, get, blank = True, title_font="bold"):
    column.insert(tk.END, title, title_font)
    if data:
        column.insert(tk.END, f"{data.get(get, "N/A")}", "white")
    else:
        column.insert(tk.END, "N/A", "white")
    if blank:
        column.insert(tk.END, "\n\n", "blank")

def overall_theme_num_display(filename):
    overall_num = get_overall_theme_number(filename)
    data = _main.get_metadata(filename)
    if overall_num and str(overall_num) not in data.get("slug"):
        return " (" + str(overall_num) + ")"
    else:
        return ""

def get_file_props_label(filename):
    """Build a compact property label for a theme file showing resolution, source, NC, Lyrics."""
    fp = (_main.get_file_metadata_by_name(filename) or {}).get("file_properties", {})
    parts = []
    res = fp.get("resolution")
    if res:
        parts.append(str(res))
    src = fp.get("source")
    if src:
        parts.append(src)
    if fp.get("nc"):
        parts.append("NC")
    if fp.get("lyrics"):
        parts.append("Lyrics")
    return f"[{' '.join(parts)}]" if parts else ""

def _get_version_flags(obj):
    """Return list of flag strings for a version or theme dict."""
    flags = []
    if obj.get("overlap") == "Over":
        flags.append("(OVERLAP)")
    if obj.get("overlap") == "Transition":
        flags.append("(TRANSITION)")
    if obj.get("spoiler"):
        flags.append("(SPOILER)")
    if obj.get("nsfw"):
        flags.append("(NSFW)")
    return flags

def get_file_marks(filename):
    marks = ""
    if _main.check_new(filename):
        marks = marks + "-NEW- "
    if _main.check_favorited(filename):
        marks = marks + "❤"
    if _main.check_tagged(filename):
        marks = marks + "❌"
    if _main.check_blind_mark(filename):
        marks = marks + "👁"
    if _main.check_peek_mark(filename):
        marks = marks + "👀"
    if _main.check_mute_peek_mark(filename):
        marks = marks + "🔇"
    return marks

def prioritize_theme_files(filenames):
    """Prioritize a list of theme files by local availability, censors, resolution, lyrics, and NC status.
    
    Returns the best filename from the list.
    """
    if not filenames:
        return None
    
    if len(filenames) == 1:
        return filenames[0]
    
    # Prioritize local files over streamable ones
    local_files = [f for f in filenames if f in _main.directory_files]
    if local_files:
        filenames = local_files
    
    # Prioritize files with censors
    files_with_censors = [f for f in filenames if _main.get_file_censors(f)]
    if files_with_censors:
        filenames = files_with_censors
    
    # Collect files with their properties
    files_with_props = []
    for f in filenames:
        file_data = _main.get_file_metadata_by_name(f)
        if not file_data:
            files_with_props.append((f, {}))
            continue
        
        props = file_data.get("file_properties", {})
        files_with_props.append((f, props))
    
    # Sort by: resolution (desc), lyrics (desc), not NC (desc)
    def sort_key(item):
        filename, props = item
        res = props.get("resolution", 0)
        if not isinstance(res, (int, float)):
            res = 0
        lyrics = 1 if props.get("lyrics") else 0
        not_nc = 1 if not props.get("nc") else 0
        return (-res, -lyrics, -not_nc)  # Negative for descending order
    
    files_with_props.sort(key=sort_key)
    
    return files_with_props[0][0] if files_with_props else filenames[0]

def _collect_theme_filenames(mal_id, slug, version=None, need_version=False):
    """Collect all matching theme filenames for a (mal_id, slug) — shared core
    of get_theme_filename and get_theme_filenames. Returns a list (may contain
    duplicates if a file is registered under multiple version_str keys).
    """
    mal_id_str = str(mal_id)
    anime_entry = _main.file_metadata.get(mal_id_str)
    if not anime_entry:
        return []
    themes = anime_entry.get("themes", {})
    if not themes or slug not in themes:
        return []
    slug_versions = themes[slug]
    found_filenames = []
    for version_str, files_dict in slug_versions.items():
        # Always include "null"-versioned files (local files with no explicit version tag)
        if version_str == "null":
            for filename in files_dict.keys():
                if filename in _main.directory_files or _main.is_animethemes_stream_file(filename):
                    found_filenames.append(filename)
            continue
        file_version = int(version_str) if version_str.isdigit() else None
        # Version matching logic
        if version is None:
            if need_version and file_version is not None:
                continue
        elif file_version != version:
            # Special case: version 1 files might not have explicit version (stored as "1")
            if not (version == 1 and version_str == "1"):
                continue
        for filename in files_dict.keys():
            if filename in _main.directory_files or _main.is_animethemes_stream_file(filename):
                found_filenames.append(filename)
    return found_filenames

def get_theme_filename(mal_id, slug, version=None, need_version=False):
    """Find filename for a given MAL ID and slug combination.

    Args:
        mal_id: The MyAnimeList ID (string or int)
        slug: The theme slug (e.g., "OP1", "ED2")
        version: Specific version number (optional, int or None)
        need_version: If True, requires explicit version match

    Returns:
        Filename if found, None otherwise
    """
    return prioritize_theme_files(_collect_theme_filenames(mal_id, slug, version, need_version))

def get_theme_filenames(mal_id, slug, version=None, need_version=False):
    """Like get_theme_filename but returns all matching files sorted by quality (best first)."""
    found_filenames = list(dict.fromkeys(_collect_theme_filenames(mal_id, slug, version, need_version)))
    if not found_filenames:
        return []
    local_files = [f for f in found_filenames if f in _main.directory_files]
    if local_files:
        found_filenames = local_files
    files_with_props = []
    for f in found_filenames:
        file_data = _main.get_file_metadata_by_name(f)
        props = file_data.get("file_properties", {}) if file_data else {}
        files_with_props.append((f, props))
    def sort_key(item):
        _, props = item
        res = props.get("resolution", 0)
        if not isinstance(res, (int, float)):
            res = 0
        lyrics = 1 if props.get("lyrics") else 0
        not_nc = 1 if not props.get("nc") else 0
        return (-res, -lyrics, -not_nc)
    files_with_props.sort(key=sort_key)
    return [f for f, _ in files_with_props]

def play_video_from_filename(filename):
    _main.search_ops.search_queue = filename
    _main.play_video()

def toggleColumnEdit(toggle):
    if toggle:
        # Allow editing
        _main.left_column.config(state=tk.NORMAL, wrap="word")
        _main.middle_column.config(state=tk.NORMAL, wrap="word")
        _main.right_column.config(state=tk.NORMAL, wrap="word")
    else:
        # Do not allow editing
        _main.left_column.config(state=tk.DISABLED, wrap="word")
        _main.middle_column.config(state=tk.DISABLED, wrap="word")
        _main.right_column.config(state=tk.DISABLED, wrap="word")
