"""Remote-theme download and local cache management.

Owns all download state and the periodic UI-update polling loop. Runtime cache
settings are read directly off state.config / core.app_meta at call time.
"""

import json
import os
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import requests

from core.game_state import state
from core.app_logging import log_exception, log_warning
from core.app_meta import APP_VERSION
from core.paths import THEMES_CACHE_FOLDER, CACHE_METADATA_FILE
import _app_scripts.search.search as search_ops
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.file.metadata.metadata_panel as metadata_panel
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.playback.transport as transport
from _app_scripts.theme import anisongdb, source_preferences

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

active_downloads        = {}   # {filename: thread_object}
download_cancel_flags   = {}   # {filename: bool} — set True to abort
cache_metadata          = {}   # {filename: {size, path, play_count, last_played}}
downloads_completed     = 0    # mutated by do_cache_download via AugAssign
download_ui_update_pending = False
pending_play_queue      = {}   # {filename: {playlist_entry, fullscreen, start_time, timeout}}
download_progress       = {}   # {filename: {downloaded_mb, total_mb, popup, progress_bar, status_label}}
_cache_lock             = threading.RLock()
# Disk work is serialized separately; playback only needs the short state lock.
_cache_io_lock          = threading.RLock()
_cache_save_timer       = None
_cache_save_lock        = threading.Lock()
_download_failures      = {}   # filename -> policy active when its sources failed


def _source_policy():
    return (state.config.theme_online_source, state.config.theme_downloaded_first,
            state.config.theme_allow_excluded_downloads)

# Runtime-configurable settings are read directly at call time:
#   state.config.themes_cache_size / state.config.auto_download_themes, and
#   APP_VERSION (core.app_meta). directory / directory_files / playlist come off
#   state.config / state.metadata.*; play_filename / streaming-fallback are on the
#   transport sibling.


def _show_playlist(update=True):
    # Lazy import: ui.lists imports cache_download, so a module-level import
    # here would be a circular dependency.
    from ..ui import lists
    lists.show_playlist(update)


# ---------------------------------------------------------------------------
# Public convenience predicates
# ---------------------------------------------------------------------------

def is_downloading(filename):
    return filename in active_downloads


# ---------------------------------------------------------------------------
# Remote theme source helpers
# ---------------------------------------------------------------------------

def get_animethemes_stream_url(filename):
    """Return the AnimeThemes CDN URL for *filename*."""
    return f"https://v.animethemes.moe/{filename}"


def _remote_file_properties(filename):
    data = metadata_fetch.get_file_metadata_by_name(filename) or {}
    properties = data.get("file_properties") or {}
    return properties if isinstance(properties, dict) else {}


def get_theme_stream_url(filename, *, explicit_file=False):
    """Return the preferred registered source URL for a remote theme."""
    urls = get_theme_stream_urls(filename, explicit_file=explicit_file)
    return urls[0] if urls else None


def get_anisongdb_stream_url(filename):
    """Return the AniSongDB URL registered for a gap or fallback source."""
    properties = _remote_file_properties(filename)
    url = properties.get("anisongdb_stream_url")
    if not url and str(properties.get("source", "")).upper() == "ANISONGDB":
        url = properties.get("stream_url")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return url
    return None


def get_theme_stream_urls(filename, *, explicit_file=False):
    """Return remote source URLs in preferred/fallback order."""
    if not isinstance(filename, str) or not filename:
        return []
    theme_entry = filename
    filename = entry_paths.get_clean_filename(theme_entry)
    data = metadata_fetch.get_file_metadata_by_name(theme_entry) or {}
    properties = data.get("file_properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    if explicit_file:
        # File buttons select a concrete video, including its provider/quality.
        # Automatic source ordering and other videos' fallback URLs do not apply.
        url = (get_animethemes_stream_url(filename) if is_animethemes_stream_file(filename)
               else properties.get("stream_url"))
        return [url] if isinstance(url, str) and url.startswith(("https://", "http://")) else []
    candidates = [properties.get("stream_url")]
    if is_animethemes_stream_file(filename):
        candidates.append(get_animethemes_stream_url(filename))
    candidates.append(get_anisongdb_stream_url(theme_entry))
    fallback_urls = properties.get("anisongdb_fallback_stream_urls", [])
    if isinstance(fallback_urls, list):
        candidates.extend(fallback_urls)
    # Native AniSongDB entries can fall back to the matching AnimeThemes file.
    if source_preferences.file_source(filename, properties) == source_preferences.ANISONGDB:
        for alternate in metadata_display._collect_theme_filenames(data.get("mal"), data.get("slug")):
            if source_preferences.file_source(alternate) == source_preferences.ANIMETHEMES:
                candidates.append(_remote_file_properties(alternate).get("stream_url"))
                candidates.append(get_animethemes_stream_url(alternate))
    urls = []
    sources = source_preferences.online_sources()
    for url in candidates:
        if (
            isinstance(url, str)
            and url.startswith(("https://", "http://"))
            and url not in urls
        ):
            source = source_preferences.source_for_url(url) or source_preferences.file_source(filename, properties)
            if source in sources:
                urls.append(url)
    return sorted(urls, key=lambda url: sources.index(
        source_preferences.source_for_url(url) or source_preferences.file_source(filename, properties)
    ))


def select_theme_entry(playlist_entry):
    """Apply the policy to a saved filename while retaining its theme identity."""
    entry = playlist_entry.get("filename", "") if isinstance(playlist_entry, dict) else playlist_entry
    if isinstance(playlist_entry, dict) and playlist_entry.get("_explicit_file"):
        return playlist_entry
    filename = entry_paths.get_clean_filename(entry)
    if not filename or (isinstance(playlist_entry, dict) and "filepath" in playlist_entry):
        return playlist_entry
    if source_preferences.file_source(filename) is None:
        return playlist_entry
    reference = entry_paths.parse_theme_reference(entry)
    data = metadata_fetch.get_file_metadata_by_name(entry) or {}
    mal_id = reference["mal_id"] if reference else data.get("mal")
    slug = reference["slug"] if reference else data.get("slug")
    version = reference["version"] if reference else data.get("version")
    if isinstance(version, str) and version.isdigit():
        version = int(version)
    candidates = metadata_display._collect_theme_filenames(mal_id, slug, version) if mal_id and slug else []
    candidates = list(dict.fromkeys([filename] + candidates))
    # Keep an explicit file choice when it already has the best policy rank.
    allowed = [candidate for candidate in candidates if source_preferences.file_allowed(candidate)]
    if (_download_failures.get(filename) == _source_policy()
            or any(_download_failures.get(candidate) == _source_policy()
                   for candidate in candidates
                   if source_preferences.file_source(candidate) == source_preferences.online_sources()[0])):
        downloaded = [candidate for candidate in allowed if source_preferences.available_path(candidate)
                      and source_preferences.downloaded_allowed(candidate, source_preferences.available_path(candidate))]
        if downloaded:
            allowed = downloaded
    if not allowed:
        return playlist_entry
    best_rank = min(source_preferences.selection_key(candidate) for candidate in allowed)
    if filename in allowed and source_preferences.selection_key(filename) == best_rank:
        return playlist_entry
    chosen = metadata_display.prioritize_theme_files(allowed)
    if not chosen or chosen == filename:
        return playlist_entry
    chosen_data = metadata_fetch.get_file_metadata_by_name(chosen) or {}
    if reference or (mal_id and slug and (str(chosen_data.get("mal")), chosen_data.get("slug")) != (str(mal_id), slug)):
        chosen = entry_paths.make_theme_reference(chosen, mal_id, slug, version)
    if entry.startswith("[L]"):
        chosen = "[L]" + chosen
    if isinstance(playlist_entry, dict):
        return {**playlist_entry, "filename": chosen}
    return chosen


def downloaded_fallback_entry(playlist_entry):
    """After a stream fails, select an allowed disk copy of the same theme."""
    if isinstance(playlist_entry, dict) and playlist_entry.get("_explicit_file"):
        return None
    if isinstance(playlist_entry, dict):
        playlist_entry = {key: value for key, value in playlist_entry.items()
                          if key not in {"filepath", "_stream_url"}}
        filename = entry_paths.get_clean_filename(playlist_entry.get("filename", ""))
    else:
        filename = entry_paths.get_clean_filename(playlist_entry)
    _download_failures[filename] = _source_policy()
    selected = select_theme_entry(playlist_entry)
    candidate = entry_paths.get_clean_filename(selected.get("filename", "") if isinstance(selected, dict) else selected)
    path = source_preferences.available_path(candidate)
    if candidate != filename and path and source_preferences.downloaded_allowed(candidate, path):
        return selected
    return None


# ---------------------------------------------------------------------------
# Cache metadata I/O
# ---------------------------------------------------------------------------

def load_cache_metadata():
    global cache_metadata
    with _cache_io_lock:
        try:
            if os.path.exists(CACHE_METADATA_FILE):
                with open(CACHE_METADATA_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                with _cache_lock:
                    cache_metadata = loaded if isinstance(loaded, dict) else {}
            else:
                with _cache_lock:
                    cache_metadata = {}
        except Exception as e:
            print(f"Error loading cache metadata: {e}")
            with _cache_lock:
                cache_metadata = {}

        _reconcile_cache_metadata()
        evict_cache_for_size(0)


def save_cache_metadata():
    from _app_scripts.utils import _atomic_json_write
    with _cache_io_lock:
        with _cache_lock:
            snapshot = {name: dict(info) for name, info in cache_metadata.items()
                        if isinstance(info, dict)}
        try:
            os.makedirs(os.path.dirname(CACHE_METADATA_FILE), exist_ok=True)
            _atomic_json_write(CACHE_METADATA_FILE, snapshot, indent=2)
        except Exception as e:
            print(f"Error saving cache metadata: {e}")


def _cache_limit_bytes():
    return max(0, int(state.config.themes_cache_size)) * 1024 * 1024


def _cache_path(rel_path):
    return os.path.join(THEMES_CACHE_FOLDER, rel_path)


def _cleanup_empty_cache_dirs(cache_path):
    cache_root = os.path.normcase(os.path.abspath(THEMES_CACHE_FOLDER))
    cache_dir = os.path.dirname(os.path.abspath(cache_path))
    try:
        while os.path.normcase(cache_dir) != cache_root and os.path.exists(cache_dir):
            if not os.listdir(cache_dir):
                os.rmdir(cache_dir)
                cache_dir = os.path.dirname(cache_dir)
            else:
                break
    except Exception:
        pass


def _reconcile_cache_metadata():
    """Make metadata reflect every file actually present in the cache folder."""
    with _cache_lock:
        reconciled = {name: dict(info) if isinstance(info, dict) else info
                      for name, info in cache_metadata.items()}
    metadata_path = os.path.normcase(os.path.abspath(CACHE_METADATA_FILE))
    known_paths = set()

    for filename, metadata in list(reconciled.items()):
        if not isinstance(metadata, dict):
            del reconciled[filename]
            continue
        rel_path = metadata.get("path", filename)
        cache_path = _cache_path(rel_path)
        if not os.path.isfile(cache_path):
            del reconciled[filename]
            continue
        metadata["size"] = os.path.getsize(cache_path)
        known_paths.add(os.path.normcase(os.path.abspath(cache_path)))

    if os.path.isdir(THEMES_CACHE_FOLDER):
        for folder, _dirs, files in os.walk(THEMES_CACHE_FOLDER):
            for basename in files:
                if basename.endswith(".part"):
                    continue
                cache_path = os.path.join(folder, basename)
                normalized_path = os.path.normcase(os.path.abspath(cache_path))
                if normalized_path == metadata_path or normalized_path in known_paths:
                    continue
                rel_path = os.path.relpath(cache_path, THEMES_CACHE_FOLDER)
                key = basename
                if key in reconciled:
                    key = f"__orphan__:{rel_path}"
                reconciled[key] = {
                    "path": rel_path,
                    "size": os.path.getsize(cache_path),
                    "play_count": 0,
                    "last_played": datetime.fromtimestamp(os.path.getmtime(cache_path)).isoformat(),
                }
                known_paths.add(normalized_path)

    with _cache_lock:
        cache_metadata.clear()
        cache_metadata.update(reconciled)
    save_cache_metadata()




def get_cached_file_path(filename):
    """Return full path to a cached file, or None if not cached."""
    candidates = entry_paths.get_interchangeable_filenames(filename)
    with _cache_lock:
        paths = []
        for candidate in candidates:
            info = cache_metadata.get(candidate)
            if isinstance(info, dict):
                paths.append(_cache_path(info.get("path", candidate)))
            paths.append(_cache_path(candidate))  # Flat legacy structure.
    for path in dict.fromkeys(paths):
        if os.path.exists(path):
            return path
    return None


def _flat_cache_files():
    """Completed files in the flat legacy cache, including conversions."""
    metadata_name = os.path.basename(CACHE_METADATA_FILE)
    try:
        with os.scandir(THEMES_CACHE_FOLDER) as entries:
            return {entry.name: entry.path for entry in entries
                    if not entry.name.endswith((".part", ".tmp"))
                    and entry.name != metadata_name and entry.is_file()}
    except OSError:
        return {}


def cache_availability_key():
    """Track cache additions, removals and conversions for catalog consumers.

    Check registered downloads only, rather than probing every remote song.
    List flat legacy files by name: the folder timestamp also changes on every
    atomic save of the cache metadata file, i.e. after each cached play.
    Play-count updates do not affect availability.
    """
    with _cache_lock:
        filenames = tuple(cache_metadata)
    paths = tuple((filename, get_cached_file_path(filename)) for filename in filenames)
    return paths, tuple(sorted(_flat_cache_files()))


def available_cached_files():
    """Snapshot downloaded paths without probing each remote catalog filename."""
    with _cache_lock:
        filenames = tuple(cache_metadata)
    paths = {}
    for filename in filenames:
        path = get_cached_file_path(filename)
        if path:
            paths[filename] = path
    for name, path in _flat_cache_files().items():
        paths.setdefault(name, path)
    return paths


def _metadata_year_season(data):
    """Return (year, season) when metadata has a usable season value."""
    season_str = (data or {}).get("season", "")
    parts = season_str.split()
    if len(parts) >= 2 and all(parts[:2]) and parts[0] != "N/A" and parts[1] != "N/A":
        return parts[1], parts[0]
    return None


def _get_download_metadata(filename, wait_seconds=20):
    """Wait for an in-flight fetch, then fetch missing metadata if needed."""
    deadline = time.monotonic() + wait_seconds
    while metadata_fetch.fetching_metadata.get(filename) and time.monotonic() < deadline:
        time.sleep(0.1)

    data = metadata_fetch.get_metadata(filename)
    if _metadata_year_season(data):
        return data
    return metadata_fetch.get_metadata(filename, fetch=True)


def _resolve_download_destination(filename):
    """Choose a metadata-backed destination, or stage safely in the cache."""
    year_season = _metadata_year_season(_get_download_metadata(filename))
    directory = state.config.directory
    if year_season and state.config.auto_download_themes and directory:
        year, season = year_season
        return os.path.join(directory, year, season, filename), None, True

    # Do not create Unknown\Unknown folders when metadata is delayed or unavailable.
    rel_path = os.path.join("_pending_metadata", filename)
    return os.path.join(THEMES_CACHE_FOLDER, rel_path), rel_path, False


def update_cache_play_count(filename):
    """Increment play count and refresh last_played for a cached file."""
    with _cache_lock:
        if filename in cache_metadata:
            cache_metadata[filename]["play_count"] = cache_metadata[filename].get("play_count", 0) + 1
            cache_metadata[filename]["last_played"] = datetime.now().isoformat()
        else:
            return
    # A play must not wait behind a worker doing cache eviction or disk writes.
    global _cache_save_timer
    with _cache_save_lock:
        if _cache_save_timer is None:
            def save():
                global _cache_save_timer
                with _cache_save_lock:
                    _cache_save_timer = None
                save_cache_metadata()
            _cache_save_timer = threading.Timer(0.5, save)
            _cache_save_timer.daemon = True
            _cache_save_timer.start()


def evict_cache_for_size(needed_size_bytes):
    """Evict LRU files until *needed_size_bytes* of headroom exists.

    Returns True when enough space was freed.
    """
    needed_size_bytes = max(0, int(needed_size_bytes))
    with _cache_io_lock:
        cache_limit_bytes = _cache_limit_bytes()
        # A completed download always wins over older cache entries. If that
        # one file is larger than the configured cap, retain it as the sole
        # cache entry rather than breaking playback for the active session.
        effective_limit_bytes = max(cache_limit_bytes, needed_size_bytes)

        current_size = 0
        cached_files = []
        metadata_changed = False
        with _cache_lock:
            records = [(name, dict(info) if isinstance(info, dict) else info)
                       for name, info in cache_metadata.items()]
        for filename, metadata in records:
            if not isinstance(metadata, dict):
                with _cache_lock:
                    cache_metadata.pop(filename, None)
                metadata_changed = True
                continue
            rel_path = metadata.get("path", filename)
            cache_path = _cache_path(rel_path)
            if not os.path.isfile(cache_path):
                with _cache_lock:
                    cache_metadata.pop(filename, None)
                metadata_changed = True
                continue
            try:
                actual_size = os.path.getsize(cache_path)
            except OSError:
                continue
            if metadata.get("size") != actual_size:
                with _cache_lock:
                    if filename in cache_metadata:
                        cache_metadata[filename]["size"] = actual_size
                metadata_changed = True
            current_size += actual_size
            cached_files.append({
                "filename": filename,
                "size": actual_size,
                "last_played": metadata.get("last_played", ""),
                "path": cache_path,
            })

        if current_size + needed_size_bytes <= effective_limit_bytes:
            if metadata_changed:
                save_cache_metadata()
            return True

        cached_files.sort(key=lambda item: item["last_played"])
        space_needed = current_size + needed_size_bytes - effective_limit_bytes
        space_freed = 0

        for file_info in cached_files:
            if space_freed >= space_needed:
                break
            filename = file_info["filename"]
            try:
                os.remove(file_info["path"])
                _cleanup_empty_cache_dirs(file_info["path"])
                space_freed += file_info["size"]
                with _cache_lock:
                    cache_metadata.pop(filename, None)
                metadata_changed = True
            except Exception as e:
                print(f"Error evicting {filename}: {e}")

        if metadata_changed:
            save_cache_metadata()
        return space_freed >= space_needed


def _finalize_cached_file(filename, rel_path, cache_path):
    """Atomically evict older entries and register a completed download.

    The new file is always retained. The return value reports whether all
    requested eviction succeeded; a False result means the cache is only
    temporarily over its target (for example, because an old file is locked).
    """
    actual_size = os.path.getsize(cache_path)
    with _cache_io_lock:
        # A stale record for this filename must not make the new file count twice.
        with _cache_lock:
            cache_metadata.pop(filename, None)
        eviction_complete = evict_cache_for_size(actual_size)

        with _cache_lock:
            cache_metadata[filename] = {
                "path": rel_path,
                "size": actual_size,
                "play_count": 0,
                "last_played": datetime.now().isoformat(),
            }
        save_cache_metadata()
        return eviction_complete


# ---------------------------------------------------------------------------
# Core download engine
# ---------------------------------------------------------------------------

def _download_theme_file_to_path(filename, dest_path, progress_callback=None, *, theme_entry=None, explicit_file=False):
    """Low-level streaming download of a remote theme to *dest_path*.

    Returns True on success, False on failure / cancellation.
    """
    dest_path = os.fspath(dest_path)
    partial_path = dest_path + ".part"
    try:
        urls = get_theme_stream_urls(theme_entry or filename, explicit_file=explicit_file)
        if not urls:
            raise ValueError(f"No remote theme source is registered for {filename}")
        headers = {
            "User-Agent": (
                f"GuessTheAnime/{APP_VERSION} "
                "(https://github.com/ualkotob/guess-the-anime-playlist-tool)"
            )
        }
        last_error = None
        for url in urls:
            source = source_preferences.source_for_url(url) or source_preferences.file_source(filename)
            if last_error is not None and source != source_preferences.online_sources()[0]:
                data = metadata_fetch.get_file_metadata_by_name(theme_entry or filename) or {}
                alternatives = metadata_display._collect_theme_filenames(data.get("mal"), data.get("slug"))
                for candidate in [filename] + alternatives:
                    path = source_preferences.available_path(candidate)
                    if (path and source_preferences.downloaded_allowed(candidate, path)
                            and source_preferences.downloaded_source(candidate, path) == source):
                        # Resume playback with the existing fallback, avoiding a
                        # second download of a video already on disk.
                        raise last_error
            try:
                response = requests.get(url, stream=True, timeout=30, headers=headers)
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(partial_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if download_cancel_flags.get(filename):
                            print(f"Download cancelled: {filename}")
                            raise InterruptedError("download cancelled")
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total_size > 0:
                                progress_callback(
                                    downloaded / 1024 / 1024,
                                    total_size / 1024 / 1024,
                                )
                os.replace(partial_path, dest_path)
                source_preferences.record_download(dest_path, url)
                _download_failures.pop(filename, None)
                return True
            except Exception as exc:
                last_error = exc
                try:
                    if os.path.exists(partial_path):
                        os.remove(partial_path)
                except OSError:
                    pass
                if download_cancel_flags.get(filename):
                    return False
        raise last_error
    except Exception as e:
        _download_failures[filename] = _source_policy()
        print(f"Download error for {filename}: {e}")
        return False


# Backward compatibility for third-party callers using the old private name.
_download_animethemes_file_to_path = _download_theme_file_to_path


# ---------------------------------------------------------------------------
# Download popup UI
# ---------------------------------------------------------------------------

def create_download_popup(filename):
    """Create a progress popup window for a file being downloaded.

    Returns a dict with popup widget refs.
    """
    popup = tk.Toplevel(state.widgets.root)
    popup.overrideredirect(True)
    popup.attributes("-topmost", True)
    popup.transient(state.widgets.root)

    bg_color    = "#1e1e1e"
    fg_color    = "white"
    border_color = "#444"
    button_bg   = "#333"
    button_hover = "#555"

    main_frame = tk.Frame(popup, bg=border_color, padx=2, pady=2)
    main_frame.pack(fill="both", expand=True)

    inner_frame = tk.Frame(main_frame, bg=bg_color)
    inner_frame.pack(fill="both", expand=True)

    title_label = tk.Label(
        inner_frame, text="Loading theme...", font=("Arial", 12, "bold"),
        bg=bg_color, fg=fg_color,
    )
    title_label.pack(pady=(15, 5))

    style = ttk.Style()
    style.theme_use("default")
    style.configure(
        "Download.Horizontal.TProgressbar",
        troughcolor="#333", background="#0078d7",
        bordercolor=bg_color, lightcolor="#0078d7", darkcolor="#0078d7",
    )

    progress_bar = ttk.Progressbar(
        inner_frame, length=450, mode="determinate",
        style="Download.Horizontal.TProgressbar",
    )
    progress_bar.pack(pady=(0, 10), padx=20, ipady=8)

    status_label = tk.Label(
        inner_frame, text="Starting download...", font=("Arial", 11),
        bg=bg_color, fg=fg_color,
    )
    status_label.pack(pady=(0, 5))

    button_frame = tk.Frame(inner_frame, bg=bg_color)
    button_frame.pack(pady=(0, 10))

    cancel_button = tk.Button(
        button_frame, text="Cancel", font=("Arial", 10),
        bg=button_bg, fg=fg_color, activebackground=button_hover,
        command=lambda: cancel_download(filename, popup), width=10, relief=tk.FLAT,
    )
    cancel_button.pack(side=tk.LEFT, padx=5)

    retry_button = tk.Button(
        button_frame, text="Retry", font=("Arial", 10),
        bg=button_bg, fg=fg_color, activebackground=button_hover,
        command=lambda: retry_download(filename, popup), width=10, relief=tk.FLAT,
    )
    retry_button.pack(side=tk.LEFT, padx=5)

    popup.update_idletasks()
    width, height = 500, 170
    # Center on the screen mpv occupies (falls back to the primary screen when
    # mpv has no window yet). Lazy import: information_popup pulls in a wide
    # dependency graph that would be a circular import at module load.
    try:
        from ..information import information_popup
        mx, my, mw, mh = information_popup._get_mpv_client_rect_logical()
    except Exception:
        mx, my = 0, 0
        mw, mh = popup.winfo_screenwidth(), popup.winfo_screenheight()
    x = mx + (mw // 2) - (width // 2)
    y = my + (mh // 2) - (height // 2)
    popup.geometry(f"{width}x{height}+{x}+{y}")

    popup.deiconify()
    popup.lift()
    popup.focus_force()
    popup.update()

    return {
        "popup": popup,
        "progress_bar": progress_bar,
        "status_label": status_label,
        "cancel_button": cancel_button,
        "retry_button": retry_button,
    }


# ---------------------------------------------------------------------------
# Download lifecycle management
# ---------------------------------------------------------------------------


def _close_download_popup(filename, popup=None):
    """Destroy and forget a download popup from the Tk/main thread.

    ``popup`` is accepted as a fallback for a button belonging to an orphaned
    registry entry, ensuring Cancel can always dismiss the window.
    """
    info = download_progress.pop(filename, None)
    popup_ref = popup or (info.get("popup") if info else None)
    if popup_ref:
        try:
            popup_ref.destroy()
        except Exception:
            pass


def cancel_download(filename, popup=None):
    """Signal an active download to abort and dismiss its popup immediately."""
    if filename in active_downloads:
        download_cancel_flags[filename] = True
        print(f"Cancelling download: {filename}")
    pending_play_queue.pop(filename, None)
    _close_download_popup(filename, popup)


def retry_download(filename, popup=None):
    """Cancel any in-flight download for *filename* and restart it."""
    _download_failures.pop(filename, None)
    pending_play_info = pending_play_queue.get(filename)
    context = {}
    if pending_play_info:
        entry = pending_play_info["playlist_entry"]
        theme_entry = entry.get("filename", filename) if isinstance(entry, dict) else entry
        if entry_paths.parse_theme_reference(theme_entry):
            context["theme_entry"] = theme_entry
        if isinstance(entry, dict) and entry.get("_explicit_file"):
            context["explicit_file"] = True

    if filename in active_downloads:
        print(f"Stopping current download to retry: {filename}")
        cancel_download(filename, popup)

        def start_retry_when_ready():
            # A requests read cannot be killed from another Python thread. Wait
            # until its bounded network timeout releases the old destination
            # before allowing a new worker to write to the same file.
            if filename in active_downloads:
                state.widgets.root.after(250, start_retry_when_ready)
                return
            download_cancel_flags.pop(filename, None)
            if pending_play_info:
                pending_play_queue[filename] = {
                    **pending_play_info,
                    "start_time": time.time(),
                }
            download_to_cache(filename, silent=False, **context)
            print(f"Retrying download: {filename}")

        state.widgets.root.after(250, start_retry_when_ready)
    else:
        download_cancel_flags.pop(filename, None)
        _close_download_popup(filename, popup)

        if pending_play_info:
            pending_play_queue[filename] = {
                **pending_play_info,
                "start_time": time.time(),
            }
        download_to_cache(filename, silent=False, **context)
        print(f"Retrying download: {filename}")


def queue_play_when_ready(filename, playlist_entry, fullscreen):
    """Called from play_filename when the file is still downloading.

    Ensures a visible progress popup exists and queues the play request.
    """
    if filename not in download_progress or download_progress[filename].get("popup") is None:
        popup_info = create_download_popup(filename)
        if filename in download_progress:
            download_progress[filename]["popup"]        = popup_info["popup"]
            download_progress[filename]["progress_bar"] = popup_info["progress_bar"]
            download_progress[filename]["status_label"] = popup_info["status_label"]
        else:
            download_progress[filename] = {
                "downloaded_mb": download_progress.get(filename, {}).get("downloaded_mb", 0),
                "total_mb":      download_progress.get(filename, {}).get("total_mb", 0),
                "popup":         popup_info["popup"],
                "progress_bar":  popup_info["progress_bar"],
                "status_label":  popup_info["status_label"],
            }

    pending_play_queue[filename] = {
        "playlist_entry": playlist_entry,
        "fullscreen":     fullscreen,
        "start_time":     time.time(),
        "timeout":        30,
    }


def download_to_cache(filename, silent=False, *, theme_entry=None, explicit_file=False):
    """Start a background download of *filename* to the local cache (or themes directory).

    Returns True if the download was started, False if already in progress / already on disk.
    """
    global downloads_completed, download_ui_update_pending
    theme_entry = theme_entry or filename
    filename = entry_paths.get_clean_filename(filename)

    if silent and _download_failures.get(filename) == _source_policy():
        return False

    if filename in active_downloads:
        return False
    cached_path = get_cached_file_path(filename)
    if cached_path and (not explicit_file or source_preferences.matches_selected_file(filename, cached_path)):
        return False
    directory_path = entry_paths.get_directory_file_path(filename)
    if directory_path and (not explicit_file or source_preferences.matches_selected_file(filename, directory_path)):
        return False
    if not get_theme_stream_urls(theme_entry, explicit_file=explicit_file):
        return False

    download_cancel_flags.pop(filename, None)

    if not silent:
        popup_info = create_download_popup(filename)
        download_progress[filename] = {
            "downloaded_mb": 0,
            "total_mb":      0,
            "popup":         popup_info["popup"],
            "progress_bar":  popup_info["progress_bar"],
            "status_label":  popup_info["status_label"],
        }
    else:
        download_progress[filename] = {"downloaded_mb": 0, "total_mb": 0, "popup": None}

    def do_cache_download():
        global downloads_completed, download_ui_update_pending
        try:
            dest_path, rel_path, to_directory = _resolve_download_destination(filename)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            last_percent = [-1]

            def progress_callback(mb_downloaded, mb_total):
                if filename in download_progress:
                    download_progress[filename]["downloaded_mb"] = mb_downloaded
                    download_progress[filename]["total_mb"]      = mb_total
                if not silent:
                    pct = int((mb_downloaded / mb_total) * 100)
                    if pct != last_percent[0] and pct % 5 == 0:
                        label = "Downloading" if to_directory else "Caching"
                        print(
                            f"\r{label} {filename}: {pct}% "
                            f"({mb_downloaded:.1f}/{mb_total:.1f} MB)",
                            end="", flush=True,
                        )
                        last_percent[0] = pct

            if not silent:
                label = "Downloading" if to_directory else "Caching"
                print(f"{label} {filename}: 0%", end="", flush=True)

            if download_cancel_flags.get(filename):
                return

            context = {"theme_entry": theme_entry} if entry_paths.parse_theme_reference(theme_entry) else {}
            if explicit_file:
                context["explicit_file"] = True
            success = _download_theme_file_to_path(filename, dest_path, progress_callback, **context)

            if download_cancel_flags.get(filename):
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        # A leftover partial file could later be mistaken for a valid theme.
                        log_warning("Could not remove cancelled partial download: %s", dest_path)
                if not silent:
                    print(f"\rDownload cancelled: {filename}" + " " * 30)
                return

            if not success:
                if not silent:
                    label = "Download" if to_directory else "Cache download"
                    print(f"\r{label} failed: {filename}" + " " * 30)
                return

            actual_size = os.path.getsize(dest_path)
            source_preferences.save_download_sources()
            downloads_completed += 1

            if to_directory:
                state.metadata.directory_files[filename] = dest_path
                # Let the main-thread UI poller refresh the playlist. Calling
                # Tk's ``after`` from this worker can block during shutdown or
                # a busy main loop and prevent the worker's final cleanup.
                download_ui_update_pending = True
            else:
                _finalize_cached_file(filename, rel_path, dest_path)

            if not silent:
                mb = actual_size / 1024 / 1024
                label = "Downloaded" if to_directory else "Cached"
                print(f"\r{label}: {filename} ({mb:.1f} MB)" + " " * 30)
                download_ui_update_pending = True

        except Exception as e:
            if not silent:
                print(f"Cache download error for {filename}: {e}")
        finally:
            active_downloads.pop(filename, None)
            download_cancel_flags.pop(filename, None)
            # Tk widgets must only be destroyed by the main thread. Leave the
            # registry entry for check_download_ui_updates() to close on its
            # next pass; Cancel may already have removed it.

    thread = threading.Thread(target=do_cache_download, daemon=True)
    active_downloads[filename] = thread
    thread.start()
    return True




# ---------------------------------------------------------------------------
# Direct download to themes directory (non-cache path)
# ---------------------------------------------------------------------------

def download_theme_file(filename, button=None):
    """Download a remote theme into the themes directory (year/season/ structure)."""
    theme_entry = filename
    filename = entry_paths.get_clean_filename(filename)
    def update_button(text):
        if button and isinstance(button, tk.Button):
            try:
                button.config(text=text)
            except Exception:
                pass

    if not get_theme_stream_urls(theme_entry):
        update_button("Source excluded")
        return

    def do_download():
        try:
            update_button("Starting...")
            dest_path, rel_path, to_directory = _resolve_download_destination(filename)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            update_button("Downloading...")

            def progress_callback(mb_downloaded, mb_total):
                update_button(f"{mb_downloaded:.1f}/{mb_total:.1f} MB")

            context = {"theme_entry": theme_entry} if entry_paths.parse_theme_reference(theme_entry) else {}
            success = _download_theme_file_to_path(filename, dest_path, progress_callback, **context)

            if not success:
                update_button("Error")
                from tkinter import messagebox
                messagebox.showerror("Download Error", f"Failed to download {filename}")
                return

            source_preferences.save_download_sources()

            if to_directory:
                state.metadata.directory_files[filename] = dest_path
            else:
                _finalize_cached_file(filename, rel_path, dest_path)
            mb = os.path.getsize(dest_path) / 1024 / 1024
            update_button(f"✓ {mb:.1f} MB")
            print(f"Downloaded {filename} to {dest_path}")

            if state.lists.list_loaded == "playlist":
                state.widgets.root.after(100, lambda: _show_playlist(True))
            cp = state.playback.currently_playing
            if cp and cp.get("filename") == filename:
                state.widgets.root.after(100, metadata_panel.update_extra_metadata)

        except Exception as e:
            update_button("Error")
            from tkinter import messagebox
            print(f"Download error for {filename}: {e}")
            messagebox.showerror("Download Error", f"Failed to download {filename}:\n\n{e}")

    threading.Thread(target=do_download, daemon=True).start()


def download_animethemes_file(filename, button=None):
    """Backward-compatible alias for :func:`download_theme_file`."""
    return download_theme_file(filename, button)


def move_cached_file_to_directory(filename, button=None):
    """Move a cached file into the themes directory (year/season/ structure)."""
    def update_button(text):
        if button and isinstance(button, tk.Button):
            try:
                button.config(text=text)
            except Exception:
                pass

    def do_move():
        import shutil
        from tkinter import messagebox
        try:
            update_button("Moving...")
            cached_path = get_cached_file_path(filename)
            if not cached_path:
                update_button("Not Cached")
                messagebox.showerror("Error", f"File not found in cache: {filename}")
                return

            dest_path, rel_path, to_directory = _resolve_download_destination(filename)
            if not to_directory:
                update_button("Metadata pending")
                messagebox.showinfo("Metadata pending", "This file is still waiting for metadata and remains safely in the cache.")
                return
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.move(cached_path, dest_path)
            source_preferences.move_download_record(cached_path, dest_path)

            # Clean up empty cache directories
            cache_dir = os.path.dirname(cached_path)
            try:
                while cache_dir != THEMES_CACHE_FOLDER and os.path.exists(cache_dir):
                    if not os.listdir(cache_dir):
                        os.rmdir(cache_dir)
                        cache_dir = os.path.dirname(cache_dir)
                    else:
                        break
            except Exception:
                pass

            state.metadata.directory_files[filename] = dest_path

            with _cache_lock:
                if filename in cache_metadata:
                    del cache_metadata[filename]
            save_cache_metadata()

            mb = os.path.getsize(dest_path) / 1024 / 1024
            update_button(f"✓ {mb:.1f} MB")
            print(f"Moved {filename} from cache to {dest_path}")

            if state.lists.list_loaded == "playlist":
                state.widgets.root.after(100, lambda: _show_playlist(True))
            cp = state.playback.currently_playing
            if cp and cp.get("filename") == filename:
                state.widgets.root.after(100, metadata_panel.update_extra_metadata)

        except Exception as e:
            update_button("Error")
            from tkinter import messagebox
            print(f"Move error for {filename}: {e}")
            messagebox.showerror("Move Error", f"Failed to move {filename}:\n\n{e}")

    threading.Thread(target=do_move, daemon=True).start()


# ---------------------------------------------------------------------------
# Playback path resolution
# ---------------------------------------------------------------------------

def is_animethemes_stream_file(filename):
    """Return True if *filename* follows the AnimeThemes remote-file convention."""
    if not isinstance(filename, str):
        return False
    properties = _remote_file_properties(filename)
    if str(properties.get("source", "")).upper() == "ANISONGDB":
        return False
    if anisongdb.classify_filename(filename) in {
        anisongdb.SOURCE_ANISONGDB,
        anisongdb.SOURCE_MANUAL,
    }:
        return False
    not_animethemes_strings = [
        "[ID]", "[MAL]", "[IGDB]", "[ASDB]", "[AMQ]", "[ANNSONG]", "ASDB-",
    ]
    upper_filename = filename.upper()
    if any(s in upper_filename for s in not_animethemes_strings) or ".webm" not in filename.lower():
        return False
    return True


def is_anisongdb_stream_file(filename):
    """Return True when *filename* is registered to an AniSongDB media URL."""
    if not isinstance(filename, str):
        return False
    properties = _remote_file_properties(filename)
    return (
        str(properties.get("source", "")).upper() == "ANISONGDB"
        and bool(properties.get("stream_url"))
    )


def is_anisongdb_alternate_file(filename):
    """Return True for a selectable backup that should not enter source pools."""
    if not isinstance(filename, str):
        return False
    properties = _remote_file_properties(filename)
    return (
        str(properties.get("source", "")).upper() == "ANISONGDB"
        and bool(properties.get("anisongdb_alternate"))
    )


def is_remote_theme_file(filename):
    """Return True for any supported non-local theme source."""
    return is_anisongdb_stream_file(filename) or is_animethemes_stream_file(filename)


def resolve_playable_path(filename, playlist_entry, local_filepath, fullscreen):
    """Resolve a playable file path for *filename*.

    Implements the full resolution chain:
        pre-specified path → local file → cache → background download → direct stream.

    Returns ``(filepath, is_animethemes_stream)`` on success, or ``None`` if
    playback has been queued for later (caller should abort with ``return False``).
    """
    # Already downloading — queue instead of blocking
    theme_entry = playlist_entry.get("filename", filename) if isinstance(playlist_entry, dict) else playlist_entry
    theme_entry = theme_entry if entry_paths.parse_theme_reference(theme_entry) else filename
    context = {"theme_entry": theme_entry} if entry_paths.parse_theme_reference(theme_entry) else {}
    explicit_file = isinstance(playlist_entry, dict) and playlist_entry.get("_explicit_file")
    stream_context = {"explicit_file": True} if explicit_file else {}
    if explicit_file:
        context["explicit_file"] = True
    path_allowed = source_preferences.matches_selected_file if explicit_file else source_preferences.downloaded_allowed
    # Explicit filepath already embedded in the playlist entry (e.g. streaming fallback)
    if isinstance(playlist_entry, dict) and 'filepath' in playlist_entry:
        filepath = playlist_entry['filepath']
        is_stream = bool(filepath and filepath.startswith(('https://', 'http://')))
        if is_stream:
            source = source_preferences.source_for_url(filepath) or source_preferences.file_source(filename)
            if explicit_file or (source is not None and source not in source_preferences.online_sources()):
                filepath = get_theme_stream_url(theme_entry, **stream_context)
                is_stream = bool(filepath)
        elif filepath and not path_allowed(filename, filepath):
            filepath = None
        if not filepath:
            return (None, False)
        return (filepath, is_stream)

    # A forced stream above can start while a cancelled worker shuts down.
    if is_downloading(filename):
        print(f"Download in progress, queuing play: {filename}")
        queue_play_when_ready(filename, playlist_entry, fullscreen)
        return None

    # Use the pre-resolved local filepath supplied by the caller
    filepath = local_filepath
    if filepath and not path_allowed(filename, filepath):
        filepath = None
    is_stream = False

    # Fallback chain for supported remote themes not found locally
    if not filepath and is_remote_theme_file(filename):
        cached_path = get_cached_file_path(filename)
        if cached_path and path_allowed(filename, cached_path):
            filepath = cached_path
        else:
            download_started = (_download_failures.get(filename) != _source_policy()
                                and download_to_cache(filename, silent=False, **context))
            if download_started:
                queue_play_when_ready(filename, playlist_entry, fullscreen)
                return None
            else:
                # Cache full or other issue — stream directly
                filepath = get_theme_stream_url(theme_entry, **stream_context)
                is_stream = bool(filepath)

    # Update play count for cached files
    if filepath and not is_stream:
        cached_path = get_cached_file_path(filename)
        if cached_path and filepath == cached_path:
            update_cache_play_count(filename)

    return (filepath, is_stream)


# ---------------------------------------------------------------------------
# File availability check
# ---------------------------------------------------------------------------

def check_file_availability(filename):
    """Return True if *filename* is already on disk (directory or cache)."""
    if entry_paths.get_directory_file_path(filename):
        return True
    if get_cached_file_path(filename):
        return True
    return False


def get_file_status(filename):
    """Return file availability status for *filename* as a dict.

    Keys:
      is_cached — file exists in the local download cache
      is_local  — file is in the user's directory (not just cache)
      is_stream — file is an AnimThemes stream (and not in the local directory)
    """
    is_cached = get_cached_file_path(filename) is not None
    local_path = entry_paths.get_directory_file_path(filename)
    is_local = bool(local_path and os.path.exists(local_path))
    is_stream = is_remote_theme_file(filename) and not is_local if filename else False
    return {"is_cached": is_cached, "is_local": is_local, "is_stream": is_stream}


# ---------------------------------------------------------------------------
# Prefetch
# ---------------------------------------------------------------------------

def prefetch_next_themes():
    """Start up to 2 new downloads for upcoming playlist entries (and fixed-round queue)."""
    MAX_LOOKAHEAD    = 5
    MAX_NEW_DOWNLOADS = 2

    playlist = state.metadata.playlist
    if not playlist.get("playlist"):
        return

    current_idx    = playlist.get("current_index", 0)
    playlist_items = playlist["playlist"]

    upcoming = []
    # search_queue plays before the playlist next, so prefetch it first
    sq = search_ops.search_queue
    if sq:
        upcoming.append(sq)
    for i in range(1, MAX_LOOKAHEAD + 1):
        next_idx = (current_idx + i) % len(playlist_items)
        upcoming.append(playlist_items[next_idx])
    for tail_entry in playlist.get("speculative_tail", []):
        upcoming.append(tail_entry)

    new_started = 0
    for upcoming_entry in upcoming:
        selected = select_theme_entry(upcoming_entry)
        theme_entry = selected.get("filename", "") if isinstance(selected, dict) else selected
        fn = entry_paths.get_clean_filename(theme_entry)
        if new_started >= MAX_NEW_DOWNLOADS:
            break
        if not is_remote_theme_file(fn):
            continue
        if fn in active_downloads:
            continue
        if check_file_availability(fn):
            continue
        context = {"theme_entry": theme_entry} if entry_paths.parse_theme_reference(theme_entry) else {}
        download_to_cache(fn, silent=True, **context)
        new_started += 1

    # Also prefetch from fixed lightning round queue
    fq, fpd = state.lightning.fixed_lightning_queue, state.lightning.fixed_lightning_round_playlist_data
    source_data = fpd if fpd else fq
    if source_data:
        next_idx = source_data.get("current_index", 0) + 1 if fpd else 0
        rounds   = (
            source_data.get("data", {}).get("rounds", [])
            if "data" in source_data
            else source_data.get("rounds", [])
        )
        if next_idx < len(rounds):
            next_fn = rounds[next_idx].get("theme")
            context = {}
            if next_fn:
                theme_entry = select_theme_entry(next_fn)
                if entry_paths.parse_theme_reference(theme_entry):
                    context = {"theme_entry": theme_entry}
                next_fn = entry_paths.get_clean_filename(theme_entry)
            if (next_fn and is_remote_theme_file(next_fn)
                    and not check_file_availability(next_fn)):
                download_to_cache(next_fn, silent=True, **context)


# ---------------------------------------------------------------------------
# Periodic UI update loop  (replaces check_download_ui_updates in main)
# ---------------------------------------------------------------------------

def check_download_ui_updates():
    """Periodically update download progress popups and process completed-download plays.

    Reschedules itself every 500 ms via root.after().  The initial call is placed
    by main with root.after(500, cache_download.check_download_ui_updates).
    """
    try:
        _check_download_ui_updates()
    except Exception:
        log_exception("Download UI update failed; polling will continue")
    finally:
        try:
            state.widgets.root.after(500, check_download_ui_updates)
        except tk.TclError:
            pass  # The app has closed.


def _check_download_ui_updates():
    global download_ui_update_pending, pending_play_queue, download_progress

    if download_ui_update_pending:
        download_ui_update_pending = False
        try:
            _show_playlist(True)
            metadata_display.up_next_text()
        except Exception:
            pass

    for fn, info in list(download_progress.items()):
        if fn not in active_downloads:
            _close_download_popup(fn)
            continue
        popup = info.get("popup")
        if popup:
            try:
                dl   = info.get("downloaded_mb", 0)
                tot  = info.get("total_mb", 0)
                if tot > 0:
                    pct  = int((dl / tot) * 100)
                    pb   = info.get("progress_bar")
                    lbl  = info.get("status_label")
                    if pb:
                        pb["value"] = pct
                    if lbl:
                        lbl.config(text=f"{dl:.1f} / {tot:.1f} MB ({pct}%)")
            except Exception:
                pass

    completed = []
    for fn, play_info in list(pending_play_queue.items()):
        elapsed = time.time() - play_info["start_time"]
        if fn not in active_downloads:
            completed.append(fn)
            state.widgets.root.after(
                100,
                lambda pe=play_info["playlist_entry"], fs=play_info["fullscreen"]:
                    transport.play_filename(pe, fs),
            )
        elif elapsed > play_info["timeout"]:
            log_warning("Download exceeded %ss; switching to streaming: %s (worker active=%s)",
                        play_info["timeout"], fn, fn in active_downloads)
            print(
                f"Download timeout ({play_info['timeout']}s), "
                f"falling back to streaming: {fn}"
            )
            completed.append(fn)
            # Streaming has taken over, so stop the redundant background
            # download and remove its progress window immediately.
            cancel_download(fn)
            theme_entry = play_info["playlist_entry"]
            if isinstance(theme_entry, dict):
                theme_entry = theme_entry.get("filename", fn)
            stream_context = ({"explicit_file": True}
                              if isinstance(play_info["playlist_entry"], dict) and play_info["playlist_entry"].get("_explicit_file") else {})
            stream_url = get_theme_stream_url(theme_entry if entry_paths.parse_theme_reference(theme_entry) else fn, **stream_context)
            streaming_entry = (
                play_info["playlist_entry"].copy()
                if isinstance(play_info["playlist_entry"], dict)
                else {"filename": fn}
            )
            streaming_entry["_stream_url"] = stream_url
            state.widgets.root.after(
                100,
                lambda pe=streaming_entry, fs=play_info["fullscreen"]:
                    transport.play_filename_streaming_fallback(pe, fs),
            )

    for fn in completed:
        pending_play_queue.pop(fn, None)
