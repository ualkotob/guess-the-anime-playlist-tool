"""
_app_scripts/cache_download.py — AnimThemes file download and local cache management.

Owns all download state and the periodic UI-update polling loop that was previously
scattered through the main module.

Call set_context() once at startup and update_settings() from load_config().
"""

import json
import os
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import requests

# ---------------------------------------------------------------------------
# Module-level state (moved from main globals)
# ---------------------------------------------------------------------------

active_downloads        = {}   # {filename: thread_object}
download_cancel_flags   = {}   # {filename: bool} — set True to abort
cache_metadata          = {}   # {filename: {size, path, play_count, last_played}}
downloads_completed     = 0
download_ui_update_pending = False
pending_play_queue      = {}   # {filename: {playlist_entry, fullscreen, start_time, timeout}}
download_progress       = {}   # {filename: {downloaded_mb, total_mb, popup, progress_bar, status_label}}

# ---------------------------------------------------------------------------
# Context / settings (populated via set_context / update_settings)
# ---------------------------------------------------------------------------

_root                             = None
_cache_metadata_file              = None
_themes_cache_folder              = None
_directory_files                  = None   # mutable dict reference
_get_directory                    = None   # callable() -> str
_get_metadata                     = None   # callable(filename) -> dict
_get_clean_filename               = None   # callable(entry) -> str
_is_animethemes_file              = None   # callable(filename) -> bool
_get_playlist                     = None   # callable() -> dict
_get_fixed_lightning              = None   # callable() -> (queue, playlist_data)
_show_playlist                    = None   # callable(update=True)
_update_extra_metadata            = None   # callable()
_up_next_text                     = None   # callable()
_play_filename                    = None   # callable(playlist_entry, fullscreen)
_play_filename_streaming_fallback = None   # callable(playlist_entry, fullscreen)
_get_currently_playing            = None   # callable() -> dict
_get_list_loaded                  = None   # callable() -> str

_themes_cache_size    = 500    # MB — updated by update_settings()
_auto_download_themes = False  # updated by update_settings()
_app_version          = "1.0"  # updated by update_settings()


def set_context(
    root,
    cache_metadata_file,
    themes_cache_folder,
    directory_files,
    get_directory,
    get_metadata,
    get_clean_filename,
    is_animethemes_file,
    get_playlist,
    get_fixed_lightning,
    show_playlist_fn,
    update_extra_metadata_fn,
    up_next_text_fn,
    play_filename_fn,
    play_filename_streaming_fallback_fn,
    get_currently_playing,
    get_list_loaded,
):
    global _root, _cache_metadata_file, _themes_cache_folder, _directory_files
    global _get_directory, _get_metadata, _get_clean_filename, _is_animethemes_file
    global _get_playlist, _get_fixed_lightning, _show_playlist, _update_extra_metadata
    global _up_next_text, _play_filename, _play_filename_streaming_fallback
    global _get_currently_playing, _get_list_loaded
    _root                             = root
    _cache_metadata_file              = cache_metadata_file
    _themes_cache_folder              = themes_cache_folder
    _directory_files                  = directory_files
    _get_directory                    = get_directory
    _get_metadata                     = get_metadata
    _get_clean_filename               = get_clean_filename
    _is_animethemes_file              = is_animethemes_file
    _get_playlist                     = get_playlist
    _get_fixed_lightning              = get_fixed_lightning
    _show_playlist                    = show_playlist_fn
    _update_extra_metadata            = update_extra_metadata_fn
    _up_next_text                     = up_next_text_fn
    _play_filename                    = play_filename_fn
    _play_filename_streaming_fallback = play_filename_streaming_fallback_fn
    _get_currently_playing            = get_currently_playing
    _get_list_loaded                  = get_list_loaded


def update_settings(themes_cache_size=500, auto_download_themes=False, app_version="1.0"):
    """Sync runtime-configurable settings into the module.  Call from load_config()."""
    global _themes_cache_size, _auto_download_themes, _app_version
    _themes_cache_size    = themes_cache_size
    _auto_download_themes = auto_download_themes
    _app_version          = app_version


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
        if os.path.exists(_cache_metadata_file):
            with open(_cache_metadata_file, "r", encoding="utf-8") as f:
                cache_metadata = json.load(f)
        else:
            cache_metadata = {}
    except Exception as e:
        print(f"Error loading cache metadata: {e}")
        cache_metadata = {}


def save_cache_metadata():
    try:
        os.makedirs(os.path.dirname(_cache_metadata_file), exist_ok=True)
        with open(_cache_metadata_file, "w", encoding="utf-8") as f:
            json.dump(cache_metadata, f, indent=2)
    except Exception as e:
        print(f"Error saving cache metadata: {e}")


def get_cache_size_mb():
    total = sum(m.get("size", 0) for m in cache_metadata.values())
    return total / (1024 * 1024)


def get_cached_file_path(filename):
    """Return full path to a cached file, or None if not cached."""
    if filename in cache_metadata:
        rel_path = cache_metadata[filename].get("path", filename)
        cache_path = os.path.join(_themes_cache_folder, rel_path)
        if os.path.exists(cache_path):
            return cache_path
    # Fallback: flat legacy structure
    cache_path = os.path.join(_themes_cache_folder, filename)
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
    cache_limit_bytes = _themes_cache_size * 1024 * 1024

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
        cache_path = os.path.join(_themes_cache_folder, rel_path)
        try:
            if os.path.exists(cache_path):
                os.remove(cache_path)
                # Clean up empty parent dirs
                cache_dir = os.path.dirname(cache_path)
                try:
                    while cache_dir != _themes_cache_folder and os.path.exists(cache_dir):
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
                f"GuessTheAnime/{_app_version} "
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
    popup = tk.Toplevel(_root)
    popup.overrideredirect(True)
    popup.attributes("-topmost", True)
    popup.transient(_root)

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

        _root.after(500, start_retry)
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
    if filename in _directory_files:
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
            data       = _get_metadata(filename)
            season_str = data.get("season", "")
            if season_str and season_str != "N/A":
                parts  = season_str.split()
                season = parts[0] if len(parts) >= 2 else "Unknown"
                year   = parts[1] if len(parts) >= 2 else "Unknown"
            else:
                season = year = "Unknown"

            directory    = _get_directory()
            to_directory = _auto_download_themes and bool(directory)
            if to_directory:
                dest_path = os.path.join(directory, year, season, filename)
                rel_path  = None
            else:
                rel_path  = os.path.join(year, season, filename)
                dest_path = os.path.join(_themes_cache_folder, rel_path)
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
                        pass
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
                _directory_files[filename] = dest_path
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
                        _root.after(0, popup_ref.destroy)
                    except Exception:
                        pass
                del download_progress[filename]

    thread = threading.Thread(target=do_cache_download, daemon=True)
    active_downloads[filename] = thread
    thread.start()
    return True


def wait_for_download(filename, timeout=30):
    """Block until *filename*'s download finishes (or times out).

    Returns True if download completed, False on timeout / not downloading.
    """
    if filename not in active_downloads:
        return True
    active_downloads[filename].join(timeout=timeout)
    return filename not in active_downloads


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
            data       = _get_metadata(filename)
            season_str = data.get("season", "")
            if season_str and season_str != "N/A":
                parts  = season_str.split()
                season = parts[0] if len(parts) >= 2 else "Unknown"
                year   = parts[1] if len(parts) >= 2 else "Unknown"
            else:
                season = year = "Unknown"

            directory = _get_directory()
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

            _directory_files[filename] = dest_path
            mb = os.path.getsize(dest_path) / 1024 / 1024
            update_button(f"✓ {mb:.1f} MB")
            print(f"Downloaded {filename} to {dest_path}")

            if _get_list_loaded() == "playlist":
                _root.after(100, lambda: _show_playlist(True))
            cp = _get_currently_playing()
            if cp and cp.get("filename") == filename:
                _root.after(100, _update_extra_metadata)

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

            data       = _get_metadata(filename)
            season_str = data.get("season", "")
            if season_str and season_str != "N/A":
                parts  = season_str.split()
                season = parts[0] if len(parts) >= 2 else "Unknown"
                year   = parts[1] if len(parts) >= 2 else "Unknown"
            else:
                season = year = "Unknown"

            directory = _get_directory()
            dest_dir  = os.path.join(directory, year, season) if directory else os.path.join(year, season)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)

            shutil.move(cached_path, dest_path)

            # Clean up empty cache directories
            cache_dir = os.path.dirname(cached_path)
            try:
                while cache_dir != _themes_cache_folder and os.path.exists(cache_dir):
                    if not os.listdir(cache_dir):
                        os.rmdir(cache_dir)
                        cache_dir = os.path.dirname(cache_dir)
                    else:
                        break
            except Exception:
                pass

            _directory_files[filename] = dest_path

            if filename in cache_metadata:
                del cache_metadata[filename]
                save_cache_metadata()

            mb = os.path.getsize(dest_path) / 1024 / 1024
            update_button(f"✓ {mb:.1f} MB")
            print(f"Moved {filename} from cache to {dest_path}")

            if _get_list_loaded() == "playlist":
                _root.after(100, lambda: _show_playlist(True))
            cp = _get_currently_playing()
            if cp and cp.get("filename") == filename:
                _root.after(100, _update_extra_metadata)

        except Exception as e:
            update_button("Error")
            from tkinter import messagebox
            print(f"Move error for {filename}: {e}")
            messagebox.showerror("Move Error", f"Failed to move {filename}:\n\n{e}")

    threading.Thread(target=do_move, daemon=True).start()


# ---------------------------------------------------------------------------
# File availability check
# ---------------------------------------------------------------------------

def check_file_availability(filename):
    """Return True if *filename* is already on disk (directory or cache)."""
    if filename in _directory_files:
        return True
    if get_cached_file_path(filename):
        return True
    return False


# ---------------------------------------------------------------------------
# Prefetch
# ---------------------------------------------------------------------------

def prefetch_next_themes():
    """Start up to 2 new downloads for upcoming playlist entries (and fixed-round queue)."""
    MAX_LOOKAHEAD    = 5
    MAX_NEW_DOWNLOADS = 2

    playlist = _get_playlist()
    if not playlist.get("playlist"):
        return

    current_idx    = playlist.get("current_index", 0)
    playlist_items = playlist["playlist"]

    upcoming = []
    for i in range(1, MAX_LOOKAHEAD + 1):
        next_idx = (current_idx + i) % len(playlist_items)
        upcoming.append(_get_clean_filename(playlist_items[next_idx]))
    for tail_entry in playlist.get("speculative_tail", []):
        upcoming.append(_get_clean_filename(tail_entry))

    new_started = 0
    for fn in upcoming:
        if new_started >= MAX_NEW_DOWNLOADS:
            break
        if not _is_animethemes_file(fn):
            continue
        if fn in active_downloads:
            continue
        if check_file_availability(fn):
            continue
        download_to_cache(fn, silent=True)
        new_started += 1

    # Also prefetch from fixed lightning round queue
    fq, fpd = _get_fixed_lightning()
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
            if (next_fn and _is_animethemes_file(next_fn)
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
            _up_next_text()
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
            _root.after(
                100,
                lambda pe=play_info["playlist_entry"], fs=play_info["fullscreen"]:
                    _play_filename(pe, fs),
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
            _root.after(
                100,
                lambda pe=streaming_entry, fs=play_info["fullscreen"]:
                    _play_filename_streaming_fallback(pe, fs),
            )

    for fn in completed:
        pending_play_queue.pop(fn, None)

    _root.after(500, check_download_ui_updates)
