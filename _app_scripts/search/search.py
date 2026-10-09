# Theme search operations.
import re
import threading
from dataclasses import dataclass

import tkinter as tk
from tkinter import simpledialog

from _app_scripts import utils
from core.game_state import state
from core.app_logging import log_exception, log_warning
from _app_scripts.file import modal_guard
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.ui.lists as lists
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.transport as transport
import _app_scripts.data.config_io as config_io
import _app_scripts.information.information_popup as information_popup
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
from _app_scripts.theme import source_preferences

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
_search_worker_lock = threading.Lock()
_search_index_lock = threading.Lock()
_search_index = None
_search_index_key = None
_catalog_matches = {}
_index_prepare_lock = threading.Lock()
# Rebuilding takes seconds of CPU; wait until the user stops changing themes.
INDEX_REFRESH_DELAY = 10.0
_index_refresh_timer = None
_index_refresh_lock = threading.Lock()

# ===========================================================================
#  SEARCHING THEMES
# ===========================================================================

def _apply_search_results(token, results, term, update, add):
    """Called on the main thread once a background search finishes."""
    global search_results, _search_token
    if token != _search_token or term != search_term:
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
        # A slow catalog refresh must not start another full scan per keystroke.
        # Waiting workers discard superseded queries before doing any work.
        with _search_worker_lock:
            if token != _search_token or term != search_term:
                return
            results = search_playlist(term)
        if token == _search_token and term == search_term:
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


def _request_search_focus(entry):
    """Restore native window focus on an explicit search click or shortcut."""
    if modal_guard.is_modal_dialog_open():
        return False
    try:
        if entry is not search_bar_entry or not entry.winfo_exists():
            return False
        if entry.cget("state") == "disabled":
            log_warning("Toolbar search field is unexpectedly disabled")
            return False
        # Respect a custom modal popup as well as standard Tk dialogs.
        grab = entry.grab_current()
        if grab is not None and grab.winfo_toplevel() != entry.winfo_toplevel():
            return False
        # Tk's Entry click binding only calls focus_set(), which can leave the
        # native Windows window unfocused after returning from another window.
        # This runs only on a user click/shortcut, never a search-result update.
        entry.focus_force()

        def check_focus():
            try:
                if entry is not search_bar_entry or not entry.winfo_exists() or modal_guard.is_modal_dialog_open():
                    return
                focused = entry.focus_get()
                if focused is None:
                    log_warning("Search field could not acquire focus (entry=%s, grab=%s, state=%s)",
                                entry, entry.grab_current(), entry.cget("state"))
            except tk.TclError:
                pass  # The toolbar or root was destroyed during the idle callback.

        state.widgets.root.after_idle(check_focus)
        return True
    except tk.TclError:
        log_exception("Failed to focus the toolbar search field")
        return False


def on_search_click(event):
    """Let the normal Entry binding position the caret after focus recovery."""
    _request_search_focus(event.widget)


def _focus_search_entry():
    """Focus the toolbar search entry, clearing placeholder if present."""
    if search_bar_entry and search_bar_entry.winfo_exists():
        if not _request_search_focus(search_bar_entry):
            return
        if search_bar_entry.get() == SEARCH_BAR_PLACEHOLDER:
            search_bar_entry.delete(0, tk.END)
            search_bar_entry.configure(fg="white")
        else:
            search_bar_entry.select_range(0, tk.END)
    else:
        search(add=state.metadata.playlist.get("infinite", False))


@dataclass(frozen=True, slots=True)
class _SearchRow:
    entry: str
    filename: str
    title: str
    english_title: str
    studios: str
    season: str
    song: str
    sort_key: tuple
    theme_key: object
    file_priority: tuple
    artists: tuple
    studio_names: tuple


def _search_data_key():
    """Keep cached text tied to metadata, physical files and source policy."""
    return (
        metadata_fetch.metadata_cache_generation,
        id(metadata_fetch.filename_to_mal), len(metadata_fetch.filename_to_mal),
        id(metadata_fetch._metadata_cache),
        id(state.metadata.file_metadata), id(state.metadata.anime_metadata),
        tuple(state.metadata.directory_files.copy().items()),
        source_preferences.online_sources(), state.config.theme_downloaded_first,
        state.config.theme_allow_excluded_downloads,
        source_preferences.download_sources_key(), cache_download.cache_availability_key(),
        # Only censor presence affects file selection, not coordinates/timing.
        tuple(tuple(name for name, boxes in censor_list.copy().items() if boxes)
              for censor_list in (metadata_display.censors.censor_list,
                                  *metadata_display.censors.other_censor_lists,
                                  metadata_display.censors._youtube_censor_list)),
    )


def _get_search_index():
    global _search_index, _search_index_key, _catalog_matches
    # Desktop and web searches share one index, including while it is rebuilt.
    with _search_index_lock:
        key = _search_data_key()
        if _search_index is not None and key == _search_index_key:
            return _search_index
        rows = []
        with source_preferences.availability_snapshot():
            for filename in playlist_ops.get_directory_files(include_non_local=True):
                filename_trim = filename.lower().replace(".webm", "").replace(".mp4", "")
                for theme_entry in metadata_fetch.get_theme_references(filename):
                    file_data = metadata_fetch.get_file_metadata_by_name(theme_entry) or {}
                    priority = metadata_display.theme_file_priority(theme_entry, file_data)
                    if priority is None:
                        continue
                    metadata = metadata_fetch.get_metadata(theme_entry)
                    song = next((song for song in metadata.get("songs") or []
                                 if song.get("slug") == metadata.get("slug")), {})
                    title = (metadata.get("title") or "").lower()
                    english_title = (metadata.get("eng_title") or "").lower()
                    rows.append(_SearchRow(
                        theme_entry, filename_trim, title, english_title,
                        ", ".join(metadata.get("studios") or []).lower(),
                        re.sub(r"\s+", " ", str(metadata.get("season") or "").lower()).strip(),
                        information_popup.get_song_string(metadata, artist_limit=None).lower(),
                        (utils.alphabetical_sort_key(english_title or title or theme_entry),
                         metadata_fetch.song_slug_sort_key(metadata.get("slug") or "")),
                        (file_data["mal"], file_data["slug"])
                        if file_data.get("mal") and file_data.get("slug") else theme_entry,
                        priority,
                        tuple(dict.fromkeys(song.get("artist") or [])),
                        tuple(dict.fromkeys(metadata.get("studios") or [])),
                    ))
        # Artist/studio counts use the same selected file and shared-theme
        # identities as search. Build once, rather than scan for every label.
        best_rows = {}
        for row in rows:
            previous = best_rows.get(row.theme_key)
            if previous is None or row.file_priority < previous.file_priority:
                best_rows[row.theme_key] = row
        matches = {"artist": {}, "studio": {}}
        for row in best_rows.values():
            for field, names in (("artist", row.artists), ("studio", row.studio_names)):
                for name in names:
                    matches[field].setdefault(name, []).append(row.entry)
        _catalog_matches = {field: {name: tuple(sorted(entries)) for name, entries in groups.items()}
                            for field, groups in matches.items()}
        _search_index = rows
        # Lazy catalog initialization can change the key while constructing it.
        # Keep the original key so a concurrent metadata edit causes a rebuild.
        _search_index_key = key
        return rows


def prepare_search_index():
    """Build searchable text after a directory scan, before the first query."""
    if not _index_prepare_lock.acquire(blocking=False):
        return
    def prepare():
        try:
            _get_search_index()
        except Exception:
            log_exception("Failed to prepare the theme search index")
        finally:
            _index_prepare_lock.release()
    try:
        threading.Thread(target=prepare, daemon=True).start()
    except Exception:
        _index_prepare_lock.release()
        raise


def _schedule_index_refresh():
    """Refresh a stale index once theme changes settle, not during a render."""
    global _index_refresh_timer
    with _index_refresh_lock:
        if _index_refresh_timer is not None:
            _index_refresh_timer.cancel()
        _index_refresh_timer = threading.Timer(INDEX_REFRESH_DELAY, prepare_search_index)
        _index_refresh_timer.daemon = True
        _index_refresh_timer.start()


def get_catalog_matches(field, name, *, wait=True):
    """Get indexed artist/studio themes; UI callers can request ready data only.

    None means the first index is still being built. An empty list means a
    completed lookup found no themes. A rendering callback never waits for the
    indexing worker: it reads the last completed index, which a quiet-period
    refresh brings up to date. Downloads and metadata fetches invalidate the
    index on nearly every theme change, yet rarely change who sang a theme.
    """
    if wait:
        _get_search_index()
        with _search_index_lock:
            return list(_catalog_matches.get(field, {}).get(name, ()))
    if _search_index is None:
        if not _search_index_lock.locked():
            prepare_search_index()
        return None
    # Built together with _search_index; a rebuild replaces the whole mapping.
    matches = _catalog_matches
    _schedule_index_refresh()
    return list(matches.get(field, {}).get(name, ()))


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
    for row in _get_search_index():
        if (row.english_title or row.title).startswith(search_term):
            priority_results.append(row)
        elif (search_term in row.filename or search_term in row.title
              or search_term in row.english_title or search_term in row.studios
              or (_season_query_enabled and search_term_norm in row.season)):
            results.append(row)
        elif search_term in row.song:
            artist_results.append(row)

    priority_results.sort(key=lambda row: row.sort_key)
    results.sort(key=lambda row: row.sort_key)
    artist_results.sort(key=lambda row: row.sort_key)
    matching_rows = priority_results + results + artist_results
    # Apply the same ranking as playlist deduplication to the matching subset.
    # Keeping it in the index avoids disk/metadata lookups even for one letter.
    best_rows = {}
    for row in matching_rows:
        previous = best_rows.get(row.theme_key)
        if previous is None or row.file_priority < previous.file_priority:
            best_rows[row.theme_key] = row
    seen = set()
    deduplicated = []
    for row in matching_rows:
        if best_rows[row.theme_key] is row and row.entry not in seen:
            seen.add(row.entry)
            deduplicated.append(row.entry)
    return deduplicated
