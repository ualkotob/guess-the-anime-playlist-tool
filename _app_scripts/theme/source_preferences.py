"""Theme source policy and the actual origin of downloaded video files."""

import os
import threading
from urllib.parse import urlparse

from core.game_state import state
from core.paths import CONFIG_FOLDER
from _app_scripts.theme import anisongdb


ANIMETHEMES = "animethemes"
ANISONGDB = "anisongdb"
SOURCE_CHOICES = {
    "prefer_animethemes": "Prefer AnimeThemes",
    "prefer_anisongdb": "Prefer AniSongDB",
    "animethemes_only": "AnimeThemes only",
    "anisongdb_only": "AniSongDB only",
}
DOWNLOAD_SOURCES_FILE = os.path.join(CONFIG_FOLDER, "theme_download_sources.json")
_download_sources = {}
_sources_loaded = False
_sources_lock = threading.RLock()


def online_sources():
    choice = state.config.theme_online_source
    if choice == "animethemes_only":
        return (ANIMETHEMES,)
    if choice == "anisongdb_only":
        return (ANISONGDB,)
    if choice == "prefer_anisongdb":
        return (ANISONGDB, ANIMETHEMES)
    return (ANIMETHEMES, ANISONGDB)


def source_for_url(url):
    host = (urlparse(url).hostname or "").lower()
    if host == "animethemes.moe" or host.endswith(".animethemes.moe"):
        return ANIMETHEMES
    if host == "animemusicquiz.com" or host.endswith(".animemusicquiz.com"):
        return ANISONGDB
    return None


def file_source(filename, properties=None):
    """Identify the catalog provider, independently of BD/DVD/TV quality tags."""
    if properties is None:
        from _app_scripts.file.metadata import metadata_fetch
        properties = (metadata_fetch.get_file_metadata_by_name(filename) or {}).get("file_properties") or {}
    if str(properties.get("source", "")).upper() == "ANISONGDB":
        return ANISONGDB
    kind = anisongdb.classify_filename(filename)
    if kind == anisongdb.SOURCE_ANISONGDB:
        return ANISONGDB
    if kind == anisongdb.SOURCE_MANUAL or str(properties.get("source", "")).upper() == "LOCAL":
        return None
    if filename.lower().endswith((".webm", ".mp4")):
        return ANIMETHEMES
    return None


def _path_key(path):
    # A converted MP4 retains the provenance of the original WebM.
    return os.path.normcase(os.path.splitext(os.path.abspath(path))[0])


def _load_download_sources():
    global _sources_loaded
    if _sources_loaded:
        return
    import json
    with _sources_lock:
        if _sources_loaded:
            return
        try:
            with open(DOWNLOAD_SOURCES_FILE, encoding="utf-8") as handle:
                records = json.load(handle)
            if isinstance(records, dict):
                _download_sources.update(records)
        except (OSError, ValueError):
            pass
        _sources_loaded = True


def download_record(path):
    if not path:
        return {}
    _load_download_sources()
    with _sources_lock:
        record = _download_sources.get(_path_key(path), {})
        return record if isinstance(record, dict) else {}


def record_download(path, url):
    _load_download_sources()
    with _sources_lock:
        _download_sources[_path_key(path)] = {
            "source": source_for_url(url),
            "url": url,
            "filename": os.path.basename(urlparse(url).path),
        }


def save_download_sources():
    from _app_scripts.utils import _atomic_json_write
    _load_download_sources()
    with _sources_lock:
        os.makedirs(os.path.dirname(DOWNLOAD_SOURCES_FILE), exist_ok=True)
        _atomic_json_write(DOWNLOAD_SOURCES_FILE, _download_sources, indent=2)


def move_download_record(old_path, new_path):
    record = download_record(old_path)
    if record:
        with _sources_lock:
            _download_sources[_path_key(new_path)] = record
            _download_sources.pop(_path_key(old_path), None)
        save_download_sources()


def downloaded_source(filename, path):
    return download_record(path).get("source") or file_source(filename)


def downloaded_allowed(filename, path):
    source = downloaded_source(filename, path)
    return (
        source is None
        or source in online_sources()
        or state.config.theme_allow_excluded_downloads
    )


def available_path(filename):
    from _app_scripts.playlists import entry_paths
    from _app_scripts.playback import cache_download
    return entry_paths.get_directory_file_path(filename) or cache_download.get_cached_file_path(filename)


def selection_key(filename):
    """Rank availability and source before the usual per-file quality rules."""
    path = available_path(filename)
    local = bool(path and downloaded_allowed(filename, path))
    source = downloaded_source(filename, path) if local else file_source(filename)
    sources = online_sources()
    rank = sources.index(source) if source in sources else (0 if source is None else len(sources))
    if state.config.theme_downloaded_first:
        # Among downloaded copies, retain the existing censors/quality ranking.
        return (0 if local else 1, 0 if local else rank)
    return (rank, 0 if local else 1)


def file_allowed(filename, *, local_only=False):
    path = available_path(filename)
    if path and downloaded_allowed(filename, path):
        return True
    return not local_only and file_source(filename) in online_sources()
