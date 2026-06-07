"""Helpers for resolving playlist entries to paths and clean filenames."""

import os

from core.game_state import state
import _app_scripts.playback.cache_download as cache_download


def get_file_path(playlist_entry):
    """Return the full file path for a playlist entry, or None if missing."""
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry

    if os.path.isabs(clean_entry):
        return clean_entry if os.path.exists(clean_entry) else None

    directory_files = state.metadata.directory_files
    if clean_entry in directory_files:
        return directory_files[clean_entry]

    cached_path = cache_download.get_cached_file_path(clean_entry)
    if cached_path:
        return cached_path

    return None


def get_clean_filename(playlist_entry, base_only=False):
    """Remove [L] prefix and return the playlist entry filename."""
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    if base_only:
        # Lazy import: metadata_display imports entry_paths, so reach it at call time.
        import _app_scripts.file.metadata.metadata_display as metadata_display
        clean_entry = metadata_display._play_name_key(clean_entry)
    return os.path.basename(clean_entry) if os.path.isabs(clean_entry) else clean_entry
