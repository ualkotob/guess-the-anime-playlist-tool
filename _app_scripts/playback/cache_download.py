"""AnimThemes file download and local cache management.

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
from core.app_logging import log_warning
from core.app_meta import APP_VERSION
from core.paths import THEMES_CACHE_FOLDER, CACHE_METADATA_FILE
import _app_scripts.search.search as search_ops
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.file.metadata.metadata_panel as metadata_panel
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.playback.transport as transport

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
# AnimThemes URL helper
# ---------------------------------------------------------------------------

def get_animethemes_stream_url(filename):
    """Return the AnimThemes CDN URL for *filename*."""
    return f"https://v.animethemes.moe/{filename}"


# ---------------------------------------------------------------------------
# Cache metadata I/O
# ---------------------------------------------------------------------------

def load_cache_metadata():
    global cache_metadata
    try:
        if os.path.exists(CACHE_METADATA_FILE):
            with open(CACHE_METADATA_FILE, "r", encoding="utf-8") as f:
                cache_metadata = json.load(f)
        else:
            cache_metadata = {}
    except Exception as e:
        print(f"Error loading cache metadata: {e}")
        cache_metadata = {}


def save_cache_metadata():
    try:
        os.makedirs(os.path.dirname(CACHE_METADATA_FILE), exist_ok=True)
        with open(CACHE_METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_metadata, f, indent=2)
    except Exception as e:
        print(f"Error saving cache metadata: {e}")




def get_cached_file_path(filename):
    """Return full path to a cached file, or None if not cached."""
    if filename in cache_metadata:
        rel_path = cache_metadata[filename].get("path", filename)
        cache_path = os.path.join(THEMES_CACHE_FOLDER, rel_path)
        if os.path.exists(cache_path):
            return cache_path
    # Fallback: flat legacy structure
    cache_path = os.path.join(THEMES_CACHE_FOLDER, filename)
    if os.path.exists(cache_path):
        return cache_path
    return None


def update_cache_play_count(filename):
    """Increment play count and refresh last_played for a cached file."""
    if filename in cache_metadata:
        cache_metadata[filename]["play_count"] = cache_metadata[filename].get("play_count", 0) + 1
        cache_metadata[filename]["last_played"] = datetime.now().isoformat()
        save_cache_metadata()


def evict_cache_for_size(needed_size_bytes):
    """Evict LRU files until *needed_size_bytes* of headroom exists.

    Returns True when enough space was freed.
    """
    current_size = sum(m.get("size", 0) for m in cache_metadata.values())
    cache_limit_bytes = state.config.themes_cache_size * 1024 * 1024

    if current_size + needed_size_bytes <= cache_limit_bytes:
        return True

    cached_files = [
        {
            "filename": fn,
            "size": m.get("size", 0),
            "play_count": m.get("play_count", 0),
            "last_played": m.get("last_played", ""),
        }
        for fn, m in cache_metadata.items()
    ]
    cached_files.sort(key=lambda x: x["last_played"])

    space_needed = current_size + needed_size_bytes - cache_limit_bytes
    space_freed = 0

    for file_info in cached_files:
        if space_freed >= space_needed:
            break
        fn = file_info["filename"]
        rel_path = cache_metadata.get(fn, {}).get("path", fn)
        cache_path = os.path.join(THEMES_CACHE_FOLDER, rel_path)
        try:
            if os.path.exists(cache_path):
                os.remove(cache_path)
                # Clean up empty parent dirs
                cache_dir = os.path.dirname(cache_path)
                try:
                    while cache_dir != THEMES_CACHE_FOLDER and os.path.exists(cache_dir):
                        if not os.listdir(cache_dir):
                            os.rmdir(cache_dir)
                            cache_dir = os.path.dirname(cache_dir)
                        else:
                            break
                except Exception:
                    pass
                space_freed += file_info["size"]
            del cache_metadata[fn]
        except Exception as e:
            print(f"Error evicting {fn}: {e}")

    save_cache_metadata()
    return space_freed >= space_needed


# ---------------------------------------------------------------------------
# Core download engine
# ---------------------------------------------------------------------------

def _download_animethemes_file_to_path(filename, dest_path, progress_callback=None):
    """Low-level streaming download of an AnimThemes file to *dest_path*.

    Returns True on success, False on failure / cancellation.
    """
    try:
        url = get_animethemes_stream_url(filename)
        headers = {
            "User-Agent": (
                f"GuessTheAnime/{APP_VERSION} "
                "(https://github.com/ualkotob/guess-the-anime-playlist-tool)"
            )
        }
        response = requests.get(url, stream=True, timeout=30, headers=headers)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if download_cancel_flags.get(filename):
                    print(f"Download cancelled: {filename}")
                    return False
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(
                            downloaded / 1024 / 1024,
                            total_size / 1024 / 1024,
                        )
        return True
    except Exception as e:
        print(f"Download error for {filename}: {e}")
        return False


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
        command=lambda: cancel_download(filename), width=10, relief=tk.FLAT,
    )
    cancel_button.pack(side=tk.LEFT, padx=5)

    retry_button = tk.Button(
        button_frame, text="Retry", font=("Arial", 10),
        bg=button_bg, fg=fg_color, activebackground=button_hover,
        command=lambda: retry_download(filename), width=10, relief=tk.FLAT,
    )
    retry_button.pack(side=tk.LEFT, padx=5)

    popup.update_idletasks()
    width, height = 500, 170
    x = (popup.winfo_screenwidth() // 2) - (width // 2)
    y = (popup.winfo_screenheight() // 2) - (height // 2)
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

def cancel_download(filename):
    """Signal an active download to abort."""
    if filename in active_downloads:
        download_cancel_flags[filename] = True
        print(f"Cancelling download: {filename}")
        pending_play_queue.pop(filename, None)


def retry_download(filename):
    """Cancel any in-flight download for *filename* and restart it."""
    pending_play_info = pending_play_queue.get(filename)

    if filename in active_downloads:
        print(f"Stopping current download to retry: {filename}")
        cancel_download(filename)

        def start_retry():
            download_cancel_flags.pop(filename, None)
            if pending_play_info:
                pending_play_queue[filename] = pending_play_info
                pending_play_queue[filename]["start_time"] = time.time()
            # Close existing popup if present
            if filename in download_progress:
                popup_ref = download_progress[filename].get("popup")
                if popup_ref:
                    try:
                        popup_ref.destroy()
                    except Exception:
                        pass
                del download_progress[filename]
            if pending_play_info:
                pending_play_queue[filename] = {
                    **pending_play_info,
                    "start_time": time.time(),
                }
            download_to_cache(filename, silent=False)
            print(f"Retrying download: {filename}")

        state.widgets.root.after(500, start_retry)
    else:
        download_cancel_flags.pop(filename, None)
        # Close existing popup
        if filename in download_progress:
            popup_ref = download_progress[filename].get("popup")
            if popup_ref:
                try:
                    popup_ref.destroy()
                except Exception:
                    pass
            del download_progress[filename]

        if pending_play_info:
            pending_play_queue[filename] = {
                **pending_play_info,
                "start_time": time.time(),
            }
        download_to_cache(filename, silent=False)
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


def download_to_cache(filename, silent=False):
    """Start a background download of *filename* to the local cache (or themes directory).

    Returns True if the download was started, False if already in progress / already on disk.
    """
    global downloads_completed, download_ui_update_pending

    if filename in active_downloads:
        return False
    if get_cached_file_path(filename):
        return False
    if filename in state.metadata.directory_files:
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
            data       = metadata_fetch.get_metadata(filename)
            season_str = data.get("season", "")
            if season_str and season_str != "N/A":
                parts  = season_str.split()
                season = parts[0] if len(parts) >= 2 else "Unknown"
                year   = parts[1] if len(parts) >= 2 else "Unknown"
            else:
                season = year = "Unknown"

            directory    = state.config.directory
            to_directory = state.config.auto_download_themes and bool(directory)
            if to_directory:
                dest_path = os.path.join(directory, year, season, filename)
                rel_path  = None
            else:
                rel_path  = os.path.join(year, season, filename)
                dest_path = os.path.join(THEMES_CACHE_FOLDER, rel_path)
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

            success = _download_animethemes_file_to_path(filename, dest_path, progress_callback)

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
            downloads_completed += 1

            if to_directory:
                state.metadata.directory_files[filename] = dest_path
                state.widgets.root.after(100, lambda: _show_playlist(True))
            else:
                evict_cache_for_size(actual_size)
                cache_metadata[filename] = {
                    "path":       rel_path,
                    "size":       actual_size,
                    "play_count": 0,
                    "last_played": datetime.now().isoformat(),
                }
                save_cache_metadata()

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
            if filename in download_progress:
                popup_ref = download_progress[filename].get("popup")
                if popup_ref:
                    try:
                        state.widgets.root.after(0, popup_ref.destroy)
                    except Exception:
                        pass
                del download_progress[filename]

    thread = threading.Thread(target=do_cache_download, daemon=True)
    active_downloads[filename] = thread
    thread.start()
    return True




# ---------------------------------------------------------------------------
# Direct download to themes directory (non-cache path)
# ---------------------------------------------------------------------------

def download_animethemes_file(filename, button=None):
    """Download *filename* directly into the themes directory (year/season/ structure)."""
    def update_button(text):
        if button and isinstance(button, tk.Button):
            try:
                button.config(text=text)
            except Exception:
                pass

    def do_download():
        try:
            update_button("Starting...")
            data       = metadata_fetch.get_metadata(filename)
            season_str = data.get("season", "")
            if season_str and season_str != "N/A":
                parts  = season_str.split()
                season = parts[0] if len(parts) >= 2 else "Unknown"
                year   = parts[1] if len(parts) >= 2 else "Unknown"
            else:
                season = year = "Unknown"

            directory = state.config.directory
            dest_dir  = os.path.join(directory, year, season) if directory else os.path.join(year, season)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)

            update_button("Downloading...")

            def progress_callback(mb_downloaded, mb_total):
                update_button(f"{mb_downloaded:.1f}/{mb_total:.1f} MB")

            success = _download_animethemes_file_to_path(filename, dest_path, progress_callback)

            if not success:
                update_button("Error")
                from tkinter import messagebox
                messagebox.showerror("Download Error", f"Failed to download {filename}")
                return

            state.metadata.directory_files[filename] = dest_path
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

            data       = metadata_fetch.get_metadata(filename)
            season_str = data.get("season", "")
            if season_str and season_str != "N/A":
                parts  = season_str.split()
                season = parts[0] if len(parts) >= 2 else "Unknown"
                year   = parts[1] if len(parts) >= 2 else "Unknown"
            else:
                season = year = "Unknown"

            directory = state.config.directory
            dest_dir  = os.path.join(directory, year, season) if directory else os.path.join(year, season)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)

            shutil.move(cached_path, dest_path)

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
    """Return True if *filename* is an AnimThemes .webm theme (not a local ID/MAL/IGDB file)."""
    not_animethemes_strings = ["[ID]", "[MAL]", "[IGDB]"]
    if any(s in filename for s in not_animethemes_strings) or ".webm" not in filename.lower():
        return False
    return True


def resolve_playable_path(filename, playlist_entry, local_filepath, fullscreen):
    """Resolve a playable file path for *filename*.

    Implements the full resolution chain:
        pre-specified path → local file → cache → background download → direct stream.

    Returns ``(filepath, is_animethemes_stream)`` on success, or ``None`` if
    playback has been queued for later (caller should abort with ``return False``).
    """
    # Already downloading — queue instead of blocking
    if is_downloading(filename):
        print(f"Download in progress, queuing play: {filename}")
        queue_play_when_ready(filename, playlist_entry, fullscreen)
        return None

    # Explicit filepath already embedded in the playlist entry (e.g. streaming fallback)
    if isinstance(playlist_entry, dict) and 'filepath' in playlist_entry:
        filepath = playlist_entry['filepath']
        is_stream = bool(filepath and filepath.startswith('https://v.animethemes.moe/'))
        return (filepath, is_stream)

    # Use the pre-resolved local filepath supplied by the caller
    filepath = local_filepath
    is_stream = False

    # Fallback chain for animethemes files not found locally
    if not filepath and is_animethemes_stream_file(filename):
        cached_path = get_cached_file_path(filename)
        if cached_path:
            filepath = cached_path
        else:
            download_started = download_to_cache(filename, silent=False)
            if download_started:
                queue_play_when_ready(filename, playlist_entry, fullscreen)
                return None
            else:
                # Cache full or other issue — stream directly
                filepath = get_animethemes_stream_url(filename)
                is_stream = True

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
    if filename in state.metadata.directory_files:
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
    directory_files = state.metadata.directory_files
    is_cached = get_cached_file_path(filename) is not None
    is_local = filename in directory_files and os.path.exists(directory_files[filename])
    is_stream = is_animethemes_stream_file(filename) and not is_local if filename else False
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
        upcoming.append(entry_paths.get_clean_filename(sq))
    for i in range(1, MAX_LOOKAHEAD + 1):
        next_idx = (current_idx + i) % len(playlist_items)
        upcoming.append(entry_paths.get_clean_filename(playlist_items[next_idx]))
    for tail_entry in playlist.get("speculative_tail", []):
        upcoming.append(entry_paths.get_clean_filename(tail_entry))

    new_started = 0
    for fn in upcoming:
        if new_started >= MAX_NEW_DOWNLOADS:
            break
        if not is_animethemes_stream_file(fn):
            continue
        if fn in active_downloads:
            continue
        if check_file_availability(fn):
            continue
        download_to_cache(fn, silent=True)
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
            if (next_fn and is_animethemes_stream_file(next_fn)
                    and not check_file_availability(next_fn)):
                download_to_cache(next_fn, silent=True)


# ---------------------------------------------------------------------------
# Periodic UI update loop  (replaces check_download_ui_updates in main)
# ---------------------------------------------------------------------------

def check_download_ui_updates():
    """Periodically update download progress popups and process completed-download plays.

    Reschedules itself every 500 ms via root.after().  The initial call is placed
    by main with root.after(500, cache_download.check_download_ui_updates).
    """
    global download_ui_update_pending, pending_play_queue, download_progress

    if download_ui_update_pending:
        download_ui_update_pending = False
        try:
            metadata_display.up_next_text()
        except Exception:
            pass

    for fn, info in list(download_progress.items()):
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
            print(
                f"Download timeout ({play_info['timeout']}s), "
                f"falling back to streaming: {fn}"
            )
            completed.append(fn)
            stream_url = get_animethemes_stream_url(fn)
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

    state.widgets.root.after(500, check_download_ui_updates)
