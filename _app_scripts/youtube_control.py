"""youtube_control.py — YouTube management for Guess the Anime!

Handles:
  - YouTube metadata persistence (load / save / query)
  - Bonus-template file I/O
  - yt-dlp stream-URL resolution and local video-cache management
  - Downloading YouTube videos via yt-dlp
  - Utility helpers (duration, display title, ID extraction)

UI-heavy functions (playlist display, editor dialogs, streaming player
integration) stay in guess_the_anime.py — see *YOUTUBE VIDEOS section.
"""

import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None

# ── Root-directory resolution ─────────────────────────────────────────────────
# When frozen by PyInstaller (--onefile) __file__ points into a temp dir;
# sys.executable always points at the real exe / script location.
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Path constants ────────────────────────────────────────────────────────────

YOUTUBE_METADATA_FILE = os.path.join(_ROOT_DIR, "metadata", "youtube_metadata.json")
YOUTUBE_FOLDER        = os.path.join(_ROOT_DIR, "youtube")
YOUTUBE_CACHE_FOLDER  = os.path.join(_ROOT_DIR, "youtube", "cache")

# ── Module state ──────────────────────────────────────────────────────────────

# youtube_metadata is updated in-place by load_youtube_metadata() so that any
# alias held by the caller (main) automatically sees the new data.
youtube_metadata: dict = {}

# Stream-URL cache: url → (direct_url, duration_s, title, channel)
_cached_streams: dict = {}

# Active YT-to-cache downloads (vid_id strings)
_yt_cache_downloads_in_progress: set = set()
# Progress info per vid_id: {downloaded, total, speed, eta}
_yt_download_progress: dict = {}

# Injected at startup by set_context()
_root = None


def set_context(root_widget):
    """Provide the main tk.Tk root so popup dialogs can use it."""
    global _root
    _root = root_widget


# ── Utility helpers ───────────────────────────────────────────────────────────

def get_youtube_duration(data):
    start  = data.get("start")
    end    = data.get("end")
    length = data.get("duration")
    if end == 0:
        end = length
    return round(end - start)


def get_youtube_display_title(data):
    return data.get("custom_title") or data.get("title")


def shorten_youtube_title(title):
    pattern = re.compile(
        r"(can you guess the|guess the|how well do you know|can you|guess"
        r"|their|from the|from|by|with|its|just)\s*",
        re.IGNORECASE,
    )
    return pattern.sub("", title)


def extract_youtube_id_from_trailer(trailer_data):
    """Extract a YouTube video ID from a trailer dict (youtube_id / embed_url / url)."""
    if not trailer_data:
        return None
    youtube_id = trailer_data.get("youtube_id")
    if youtube_id:
        return youtube_id
    embed_url = trailer_data.get("embed_url")
    if embed_url:
        match = re.search(r"/embed/([a-zA-Z0-9_-]+)", embed_url)
        if match:
            return match.group(1)
    url = trailer_data.get("url")
    if url:
        match = re.search(r"[?&]v=([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
    return None


# ── Metadata helpers ──────────────────────────────────────────────────────────

def is_youtube_file(filename):
    """Return True if *filename* matches a YouTube video in youtube_metadata."""
    for _vid_id, video in youtube_metadata.get("videos", {}).items():
        if video.get("filename") == filename:
            return True
    return False


def get_youtube_metadata_by_filename(filename):
    """Return merged video + channel metadata dict for *filename*, or None."""
    for video_id, video in youtube_metadata.get("videos", {}).items():
        if video.get("filename") == filename:
            channel_info = youtube_metadata.get("channels", {}).get(
                video.get("channel_id"), {"name": "N/A", "subscriber_count": 0}
            )
            return video | channel_info | {"url": video_id}
    return None


def get_youtube_metadata_from_index(index=None, key_id=None):
    """Return video + channel metadata by numeric index or video-ID key."""
    for idx, (key, value) in enumerate(youtube_metadata.get("videos", {}).items()):
        if (key_id and key_id == key) or idx == index:
            value["url"] = key
            channel_info = youtube_metadata.get("channels", {}).get(
                value.get("channel_id"), {"name": "N/A", "subscriber_count": 0}
            )
            return value | channel_info
    return None


# ── Metadata persistence ──────────────────────────────────────────────────────

def save_youtube_metadata():
    """Atomically write youtube_metadata to YOUTUBE_METADATA_FILE."""
    metadata_folder = os.path.dirname(YOUTUBE_METADATA_FILE)
    os.makedirs(metadata_folder, exist_ok=True)
    tmp = YOUTUBE_METADATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(youtube_metadata, f, indent=4, ensure_ascii=False)
    try:
        os.replace(tmp, YOUTUBE_METADATA_FILE)
    except OSError:
        os.rename(tmp, YOUTUBE_METADATA_FILE)


def load_youtube_metadata():
    """Load youtube_metadata from disk, updating the shared dict **in-place**.

    Updating in-place (rather than replacing the reference) ensures any alias
    held by the caller (e.g. ``youtube_metadata = youtube_control.youtube_metadata``
    in main) stays valid after the load.

    Returns True if the file was found and loaded, False otherwise.
    """
    if not os.path.exists(YOUTUBE_METADATA_FILE):
        return False
    with open(YOUTUBE_METADATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    youtube_metadata.clear()
    youtube_metadata.update(data)
    print(
        "Loaded youtube metadata for "
        + str(len(youtube_metadata.get("videos", [])))
        + " videos..."
    )
    # Migration: add date_added to entries that lack it
    migration_needed = False
    for _vid_id, video in youtube_metadata.get("videos", {}).items():
        if "date_added" not in video:
            upload_date = video.get("upload_date", "")
            if upload_date:
                try:
                    video["date_added"] = datetime.strptime(upload_date, "%Y%m%d").isoformat()
                except (ValueError, TypeError):
                    video["date_added"] = datetime.now().isoformat()
            else:
                video["date_added"] = datetime.now().isoformat()
            migration_needed = True
    if migration_needed:
        save_youtube_metadata()
    return True


# ── Bonus-template file I/O ───────────────────────────────────────────────────

def get_bonus_template_path(video_id):
    return os.path.join(YOUTUBE_FOLDER, "bonus_templates", f"{video_id}.json")


def load_bonus_template(video_id):
    path = get_bonus_template_path(video_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("questions", [])
        except Exception:
            return []
    return []


def save_bonus_template(video_id, questions):
    os.makedirs(os.path.join(YOUTUBE_FOLDER, "bonus_templates"), exist_ok=True)
    path = get_bonus_template_path(video_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"questions": questions}, f, indent=2, ensure_ascii=False)


# ── YT-cache path helpers ─────────────────────────────────────────────────────

def _get_yt_cache_path(youtube_url):
    """Return the local cache .mp4 path for a YouTube URL, or None."""
    match = re.search(r"(?:v=|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})", youtube_url or "")
    if not match:
        return None
    return os.path.join(YOUTUBE_CACHE_FOLDER, f"{match.group(1)}.mp4")


def _get_yt_meta_path(youtube_url):
    """Return the sidecar metadata .json path for a YouTube URL, or None."""
    match = re.search(r"(?:v=|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})", youtube_url or "")
    if not match:
        return None
    return os.path.join(YOUTUBE_CACHE_FOLDER, f"{match.group(1)}.json")


def _load_yt_meta(youtube_url):
    """Load cached metadata dict for a YouTube URL from its sidecar JSON, or None."""
    meta_path = _get_yt_meta_path(youtube_url)
    if not meta_path or not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_yt_meta(youtube_url, title, channel, duration):
    """Save title/channel/duration to a sidecar JSON next to the cached mp4."""
    meta_path = _get_yt_meta_path(youtube_url)
    if not meta_path:
        return
    try:
        os.makedirs(YOUTUBE_CACHE_FOLDER, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {"title": title, "channel": channel, "duration": duration, "url": youtube_url},
                f,
                ensure_ascii=False,
            )
    except Exception as e:
        print(f"[YT cache] Failed to save metadata for {youtube_url}: {e}")


def _evict_yt_cache(max_mb):
    """Delete oldest .mp4 files from YOUTUBE_CACHE_FOLDER until total is under max_mb."""
    if max_mb <= 0:
        return
    cache_dir = YOUTUBE_CACHE_FOLDER
    if not os.path.isdir(cache_dir):
        return
    files = []
    total = 0
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".mp4"):
            continue
        fpath = os.path.join(cache_dir, fname)
        try:
            sz    = os.path.getsize(fpath)
            mtime = os.path.getmtime(fpath)
            files.append((mtime, sz, fpath))
            total += sz
        except OSError:
            pass
    files.sort()  # oldest first
    limit = max_mb * 1024 * 1024
    for _mtime, sz, fpath in files:
        if total <= limit:
            break
        try:
            os.remove(fpath)
            total -= sz
        except OSError:
            pass
        meta = fpath.replace(".mp4", ".json")
        if os.path.exists(meta):
            try:
                os.remove(meta)
            except OSError:
                pass


def _yt_cache_download_bg(youtube_url, cache_path, max_mb):
    """Background thread: download youtube_url to cache_path via yt-dlp, then evict."""
    if YoutubeDL is None:
        return
    vid_id = os.path.splitext(os.path.basename(cache_path))[0]
    if vid_id in _yt_cache_downloads_in_progress:
        return
    _yt_cache_downloads_in_progress.add(vid_id)
    try:
        os.makedirs(YOUTUBE_CACHE_FOLDER, exist_ok=True)
        part_path = cache_path + ".part"

        def _progress_hook(d):
            if d["status"] == "downloading":
                _yt_download_progress[vid_id] = {
                    "downloaded": d.get("downloaded_bytes") or 0,
                    "total":      d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                    "speed":      d.get("speed") or 0,
                    "eta":        d.get("eta"),
                }

        ydl_opts = {
            "format":             "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "merge_output_format":"mp4",
            "outtmpl":            cache_path,
            "quiet":              True,
            "no_warnings":        True,
            "noprogress":         True,
            "progress_hooks":     [_progress_hook],
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        if os.path.exists(cache_path) and info:
            _save_yt_meta(
                youtube_url,
                title=info.get("title", ""),
                channel=info.get("channel") or info.get("uploader", ""),
                duration=info.get("duration", 0),
            )
            _evict_yt_cache(max_mb)
    except Exception as e:
        print(f"[YT cache] Download failed for {youtube_url}: {e}")
    finally:
        _yt_cache_downloads_in_progress.discard(vid_id)
        _yt_download_progress.pop(vid_id, None)


# ── YT-cache wait popup ───────────────────────────────────────────────────────

def _yt_cache_wait_popup(youtube_url, timeout=120):
    """Show a blocking popup (root.wait_window) while a YT cache download finishes.

    Returns True if the cache file is ready when the popup closes, False otherwise.
    Requires set_context(root) to have been called first.
    """
    if _root is None:
        return False
    match = re.search(r"(?:v=|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})", youtube_url or "")
    if not match:
        return False
    vid_id     = match.group(1)
    cache_path = os.path.join(YOUTUBE_CACHE_FOLDER, f"{vid_id}.mp4")

    # Already done — no popup needed
    if vid_id not in _yt_cache_downloads_in_progress:
        return os.path.exists(cache_path)

    bg_color, fg_color, border_color = "#1e1e1e", "white", "#444"

    popup = tk.Toplevel(_root)
    popup.overrideredirect(True)
    popup.attributes("-topmost", True)
    popup.transient(_root)

    main_frame  = tk.Frame(popup, bg=border_color, padx=2, pady=2)
    main_frame.pack(fill="both", expand=True)
    inner_frame = tk.Frame(main_frame, bg=bg_color)
    inner_frame.pack(fill="both", expand=True)

    tk.Label(
        inner_frame, text="Downloading clip…", font=("Arial", 12, "bold"),
        bg=bg_color, fg=fg_color,
    ).pack(pady=(15, 5))

    style = ttk.Style()
    style.theme_use("default")
    style.configure(
        "YTWait.Horizontal.TProgressbar",
        troughcolor="#333", background="#0078d7",
        bordercolor=bg_color, lightcolor="#0078d7", darkcolor="#0078d7",
    )
    pb = ttk.Progressbar(
        inner_frame, length=380, mode="indeterminate",
        style="YTWait.Horizontal.TProgressbar",
    )
    pb.pack(pady=(0, 6), padx=20, ipady=6)
    pb.start(12)

    status_var = tk.StringVar(value="Waiting for download to complete…")
    tk.Label(
        inner_frame, textvariable=status_var, font=("Arial", 10),
        bg=bg_color, fg="#aaa",
    ).pack(pady=(0, 4))

    result  = [False]
    start_t = time.time()

    def _poll():
        elapsed = time.time() - start_t
        if vid_id not in _yt_cache_downloads_in_progress:
            result[0] = os.path.exists(cache_path)
            try:
                popup.destroy()
            except Exception:
                pass
            return
        if elapsed >= timeout:
            status_var.set("Timed out — falling back to stream.")
            popup.after(1000, popup.destroy)
            return
        prog = _yt_download_progress.get(vid_id)
        if prog and prog.get("downloaded"):
            dl    = prog["downloaded"]
            total = prog["total"]
            eta   = prog.get("eta")
            mb_dl = dl / 1_048_576
            if total:
                pct      = min(100, dl * 100 / total)
                mb_total = total / 1_048_576
                eta_str  = f"  ETA {eta}s" if eta is not None else ""
                status_var.set(f"{pct:.0f}%  {mb_dl:.1f}/{mb_total:.1f} MB{eta_str}")
                pb.stop()
                pb.configure(mode="determinate")
                pb["value"] = pct
            else:
                status_var.set(f"{mb_dl:.1f} MB downloaded…")
                if pb["mode"] != "indeterminate":
                    pb.configure(mode="indeterminate")
                    pb.start(12)
        else:
            status_var.set(f"Downloading clip… ({int(elapsed)}s)")
        popup.after(250, _poll)

    def _on_cancel():
        result[0] = False
        try:
            popup.destroy()
        except Exception:
            pass

    tk.Button(
        inner_frame, text="Skip (stream instead)", font=("Arial", 10),
        bg="#333", fg=fg_color, activebackground="#555",
        command=_on_cancel, relief=tk.FLAT,
    ).pack(pady=(0, 12))

    popup.update_idletasks()
    w, h = 430, 165
    x = (_root.winfo_screenwidth()  - w) // 2
    y = (_root.winfo_screenheight() - h) // 2
    popup.geometry(f"{w}x{h}+{x}+{y}")
    popup.deiconify()
    popup.lift()
    popup.update()
    popup.after(250, _poll)
    _root.wait_window(popup)
    return result[0]


# ── YT stream-URL resolution ──────────────────────────────────────────────────

def get_youtube_stream_url(youtube_url, include_other_info=False):
    """Resolve a YouTube URL to a direct stream URL via yt-dlp (in-memory cached).

    Returns (stream_url, duration) or (stream_url, duration, title, channel)
    depending on *include_other_info*.  Falls back to (None, 0[, "", ""]) on error.
    """
    try:
        if youtube_url in _cached_streams:
            cached = _cached_streams[youtube_url]
            if include_other_info and len(cached) > 2:
                return cached
            elif not include_other_info:
                return cached[:2]

        if YoutubeDL is None:
            return (None, 0, "", "") if include_other_info else (None, 0)

        ydl_opts = {"format": "best[ext=mp4]/best", "quiet": True, "no_warnings": True}
        with YoutubeDL(ydl_opts) as ydl:
            info     = ydl.extract_info(youtube_url, download=False)
            stream   = info["url"]
            duration = info.get("duration", 0)
            title    = info.get("title", "")
            uploader = info.get("uploader", "")
            channel  = info.get("channel", uploader)

        _cached_streams[youtube_url] = (stream, duration, title, channel)
        # Persist sidecar so a locally-cached file can load metadata offline
        cache_p = _get_yt_cache_path(youtube_url)
        if cache_p and os.path.exists(cache_p):
            _save_yt_meta(youtube_url, title=title, channel=channel, duration=duration)

        return (stream, duration, title, channel) if include_other_info else (stream, duration)
    except Exception:
        _cached_streams[youtube_url] = (None, 0, "", "")
        return (None, 0, "", "") if include_other_info else (None, 0)


# ── YouTube video download ────────────────────────────────────────────────────

def download_youtube_video(video_id, button, refresh_ui_callback):
    """Download *video_id* from YouTube into the youtube/ folder via yt-dlp.

    *button* is an optional tk.Button whose text is updated with progress.
    *refresh_ui_callback* is called (on the yt-dlp thread) when the download
    completes successfully.
    """
    if YoutubeDL is None:
        return
    video    = youtube_metadata["videos"][video_id]
    filename = os.path.join(YOUTUBE_FOLDER, video["filename"])
    max_total = {"bytes": 0}

    def update_button(text):
        try:
            if hasattr(button, "config"):
                button.config(text=text)
        except Exception:
            pass

    def on_progress(d):
        if d["status"] == "downloading":
            downloaded     = d.get("downloaded_bytes", 0)
            reported_total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            if (reported_total > max_total["bytes"] * 1.05
                    or reported_total < max_total["bytes"] * 0.95):
                max_total["bytes"] = reported_total
            elif max_total["bytes"] == 0:
                max_total["bytes"] = reported_total
            total        = max_total["bytes"]
            downloaded_mb = downloaded / 1_024 / 1_024
            total_mb      = total / 1_024 / 1_024
            update_button(f"{downloaded_mb:.1f}/{total_mb:.1f} MB")
        elif d["status"] == "finished":
            update_button("Merging...")

    def do_download():
        update_button("Starting...")
        try:
            ydl_opts = {
                "format":             "bestvideo+bestaudio/best",
                "outtmpl":            filename,
                "quiet":              True,
                "progress_hooks":     [on_progress],
                "merge_output_format":"mp4",
            }
            os.makedirs(YOUTUBE_FOLDER, exist_ok=True)
            with YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=True
                )
            save_youtube_metadata()
            refresh_ui_callback()
        except Exception as e:
            update_button("Error")
            print(f"Download error for {video_id}: {e}")

    if os.path.exists(filename):
        update_button(f"{round(os.path.getsize(filename) / 1_024 / 1_024, 1)} MB")
    else:
        threading.Thread(target=do_download, daemon=True).start()
