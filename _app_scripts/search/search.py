# _app_scripts/search_ops.py
# Theme search operations extracted from playlist_ops.py
import re
import threading

import tkinter as tk
from tkinter import simpledialog

from core.game_state import state

# ---------------------------------------------------------------------------
# Injected context (populated by set_context())
# ---------------------------------------------------------------------------
_root = None
_right_column = None
_get_disable_shortcuts = None
_show_list = None
_theme_context_menu = None
_get_title = None
_up_next_text = None
_prefetch_next_themes = None
_save_config = None
_play_video = None
_player = None
_get_song_string = None
_get_metadata = None
# playlist is read directly from state.metadata.playlist
_get_directory_files = None
_deduplicate_theme_versions = None

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
search_term = ""
search_bar_entry = None  # set externally after UI creation
SEARCH_BAR_PLACEHOLDER = "SEARCH THEMES"
search_queue = None
search_results = []
_search_token = 0

# ---------------------------------------------------------------------------
# set_context()
# ---------------------------------------------------------------------------
def set_context(
    root, right_column,
    get_disable_shortcuts, show_list, theme_context_menu,
    get_title, up_next_text, prefetch_next_themes,
    save_config, play_video, player,
    get_song_string, get_metadata,
    get_directory_files, deduplicate_theme_versions,
):
    global _root, _right_column
    global _get_disable_shortcuts, _show_list, _theme_context_menu
    global _get_title, _up_next_text, _prefetch_next_themes
    global _save_config, _play_video, _player
    global _get_song_string, _get_metadata
    global _get_directory_files, _deduplicate_theme_versions

    _root = root
    _right_column = right_column
    _get_disable_shortcuts = get_disable_shortcuts
    _show_list = show_list
    _theme_context_menu = theme_context_menu
    _get_title = get_title
    _up_next_text = up_next_text
    _prefetch_next_themes = prefetch_next_themes
    _save_config = save_config
    _play_video = play_video
    _player = player
    _get_song_string = get_song_string
    _get_metadata = get_metadata
    _get_directory_files = get_directory_files
    _deduplicate_theme_versions = deduplicate_theme_versions


# ===========================================================================
#  SEARCHING THEMES
# ===========================================================================

def _apply_search_results(token, results, term, update, add):
    """Called on the main thread once a background search finishes."""
    global search_results, _search_token
    if token != _search_token:
        return
    search_results = results
    selected = 0
    if search_queue and search_queue in search_results:
        selected = search_results.index(search_queue) + 1
    search_list = {file: file for file in (["SEARCHING: " + term] + search_results)}

    def _search_right_click(index):
        if index > 0:
            _theme_context_menu(search_results[index - 1], lambda: search(True, False))

    if add:
        _show_list("search_add", _right_column, search_list, _get_title, add_search_playlist, selected, update,
                   right_click_func=_search_right_click, title="SEARCH: ADD TO PLAYLIST")
    else:
        _show_list("search", _right_column, search_list, _get_title, set_search_queue, selected, update,
                   right_click_func=_search_right_click, title="SEARCH RESULTS")


def search(update=False, ask=True, add=False):
    global search_results, search_term, _search_token
    if ask and _get_disable_shortcuts():
        search_term_ask = simpledialog.askstring("Search Themes", "Search Term:", initialvalue=search_term, parent=_root)
        if not search_term_ask:
            return
        search_term = search_term_ask
        update = True
    _search_token += 1
    token = _search_token
    term = search_term
    if term == "":
        search_results = []
        _apply_search_results(token, [], term, update, add)
        return

    def _run():
        results = search_playlist(term)
        _root.after(0, lambda: _apply_search_results(token, results, term, update, add))

    threading.Thread(target=_run, daemon=True).start()


def search_add(update=False, ask=True):
    search(update, ask, True)


def add_theme_next(filename, prevent_duplicates=True):
    """Insert a theme immediately after the current index."""
    filename = str(filename or "").strip()
    if not filename:
        return False
    playlist = state.metadata.playlist
    pl = playlist.get("playlist", [])
    cur = int(playlist.get("current_index", -1))
    insert_at = max(0, min(len(pl), cur + 1))
    if prevent_duplicates and filename in pl[insert_at:]:
        return False
    pl.insert(insert_at, filename)
    return True


def add_search_playlist(index):
    if index > 0:
        filename = search_results[index - 1]
        add_theme_next(filename, prevent_duplicates=True)
        search_add(True, False)
        _up_next_text()
        _prefetch_next_themes()
        _save_config()


def set_search_queue(index):
    global search_queue
    if index > 0:
        filename = search_results[index - 1]
        if search_queue == filename:
            search_queue = None
        else:
            search_queue = filename
            if not _player.is_playing():
                _play_video()
                return
        search(True, False)
        _up_next_text()
        _prefetch_next_themes()


def _focus_search_entry():
    """Focus the toolbar search entry, clearing placeholder if present."""
    if search_bar_entry and search_bar_entry.winfo_exists():
        if search_bar_entry.get() == SEARCH_BAR_PLACEHOLDER:
            search_bar_entry.delete(0, tk.END)
            search_bar_entry.configure(fg="white")
        else:
            search_bar_entry.select_range(0, tk.END)
        search_bar_entry.focus_set()
    else:
        search(add=state.metadata.playlist.get("infinite", False))


def search_playlist(search_term):
    """Returns filenames matching the search term (deduplicated)."""
    search_term = search_term.lower()
    search_term_norm = re.sub(r"\s+", " ", search_term).strip()
    _has_season_word = bool(re.search(r"\b(winter|spring|summer|fall)\b", search_term_norm))
    _has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", search_term_norm))
    _season_query_enabled = _has_season_word and _has_year
    priority_results = []
    results = []
    artist_results = []
    for filename in _get_directory_files(include_non_local=True):
        metadata = _get_metadata(filename)
        filename_trim = filename.lower().replace(".webm", "").replace(".mp4", "")
        title = metadata.get("title", "").lower()
        english_title = (metadata.get("eng_title") or "").lower()
        studios = ", ".join(metadata.get("studios") or []).lower()
        season = re.sub(r"\s+", " ", str(metadata.get("season") or "").lower()).strip()
        studio_match = bool(studios and search_term in studios)
        season_match = bool(_season_query_enabled and season and search_term_norm in season)
        if (english_title or title).startswith(search_term):
            priority_results.append(filename)
        elif (search_term in filename_trim) or (title and search_term in title) or (english_title and search_term in english_title) or studio_match or season_match:
            results.append(filename)
        else:
            song_string = _get_song_string(metadata, artist_limit=None).lower()
            if song_string and search_term in song_string:
                artist_results.append(filename)

    def _slug_sort_key(file):
        meta = _get_metadata(file)
        slug = (meta.get("slug") or "").upper()
        title_key = (meta.get("eng_title") or meta.get("title") or file).lower()
        if slug.startswith("OP"):
            slug_type = 0
            num_str = slug[2:]
        elif slug.startswith("ED"):
            slug_type = 1
            num_str = slug[2:]
        else:
            slug_type = 2
            num_str = slug
        slug_num = int(num_str) if num_str.isdigit() else 0
        return (title_key, slug_type, slug_num)

    priority_results.sort(key=_slug_sort_key)
    results.sort(key=_slug_sort_key)
    artist_results.sort(key=_slug_sort_key)
    return _deduplicate_theme_versions(priority_results + results + artist_results)
