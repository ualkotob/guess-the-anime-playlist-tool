"""Helpers for resolving playlist entries to paths and clean filenames."""

import os


_directory_files = {}
_get_cached_file_path = None
_play_name_key = None


def set_context(*, directory_files, get_cached_file_path, play_name_key):
    global _directory_files, _get_cached_file_path, _play_name_key
    _directory_files = directory_files
    _get_cached_file_path = get_cached_file_path
    _play_name_key = play_name_key


def get_file_path(playlist_entry):
    """Return the full file path for a playlist entry, or None if missing."""
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry

    if os.path.isabs(clean_entry):
        return clean_entry if os.path.exists(clean_entry) else None

    if clean_entry in _directory_files:
        return _directory_files[clean_entry]

    if _get_cached_file_path:
        cached_path = _get_cached_file_path(clean_entry)
        if cached_path:
            return cached_path

    return None


def get_clean_filename(playlist_entry, base_only=False):
    """Remove [L] prefix and return the playlist entry filename."""
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    if base_only and _play_name_key:
        clean_entry = _play_name_key(clean_entry)
    return os.path.basename(clean_entry) if os.path.isabs(clean_entry) else clean_entry
