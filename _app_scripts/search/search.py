# Theme search operations.
import re
import threading

import tkinter as tk
from tkinter import simpledialog

from core.game_state import state
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.ui.lists as lists
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.transport as transport
import _app_scripts.data.config_io as config_io
import _app_scripts.information.information_popup as information_popup
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch

# Collaborators (read directly off state / sibling modules).
# play_video reached via transport sibling; root/right_column/player read from
# state.widgets; show_list/theme_context_menu/get_title from lists; up_next_text
# from metadata_display; prefetch_next_themes from cache_download; save_config
# from config_io; get_song_string from information_popup; get_metadata from
# metadata_fetch.
# playlist is read directly from state.metadata.playlist
# directory_files / deduplicate_theme_versions are read directly from playlist_ops

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
search_term = ""
search_bar_entry = None  # set externally after UI creation
SEARCH_BAR_PLACEHOLDER = "SEARCH THEMES"
search_queue = None
search_results = []
_search_token = 0

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
            lists._theme_context_menu(search_results[index - 1], lambda: search(True, False))

    if add:
        lists.show_list("search_add", state.widgets.right_column, search_list, lists.get_title, add_search_playlist, selected, update,
                        right_click_func=_search_right_click, title="SEARCH: ADD TO PLAYLIST")
    else:
        lists.show_list("search", state.widgets.right_column, search_list, lists.get_title, set_search_queue, selected, update,
                        right_click_func=_search_right_click, title="SEARCH RESULTS")


def search(update=False, ask=True, add=False):
    global search_results, search_term, _search_token
    if ask and state.controls.disable_shortcuts:
        search_term_ask = simpledialog.askstring("Search Themes", "Search Term:", initialvalue=search_term, parent=state.widgets.root)
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
        state.widgets.root.after(0, lambda: _apply_search_results(token, results, term, update, add))

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
        metadata_display.up_next_text()
        cache_download.prefetch_next_themes()
        config_io.save_config()


def set_search_queue(index):
    global search_queue
    if index > 0:
        filename = search_results[index - 1]
        if search_queue == filename:
            search_queue = None
        else:
            search_queue = filename
            if not state.widgets.player.is_playing():
                transport.play_video()
                return
        search(True, False)
        metadata_display.up_next_text()
        cache_download.prefetch_next_themes()


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
    for filename in playlist_ops.get_directory_files(include_non_local=True):
        metadata = metadata_fetch.get_metadata(filename)
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
            song_string = information_popup.get_song_string(metadata, artist_limit=None).lower()
            if song_string and search_term in song_string:
                artist_results.append(filename)

    def _slug_sort_key(file):
        meta = metadata_fetch.get_metadata(file)
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
    return playlist_ops.deduplicate_theme_versions(priority_results + results + artist_results)
