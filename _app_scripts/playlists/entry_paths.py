"""Helpers for resolving playlist entries to paths and clean filenames."""

import os

from core.game_state import state
import _app_scripts.playback.cache_download as cache_download


_INTERCHANGEABLE_THEME_EXTENSIONS = (".webm", ".mp4")


def get_interchangeable_filenames(filename):
    """Return *filename* followed by its equivalent WebM/MP4 filename.

    AnimeThemes playlists normally retain the canonical ``.webm`` name even
    when a user converts the local file to ``.mp4``. Keep that logical name,
    but allow either container to satisfy local playback and availability
    checks.
    """
    stem, extension = os.path.splitext(filename)
    extension = extension.lower()
    variants = [filename]
    if extension in _INTERCHANGEABLE_THEME_EXTENSIONS:
        variants.extend(
            stem + candidate
            for candidate in _INTERCHANGEABLE_THEME_EXTENSIONS
            if candidate != extension
        )
    return variants


def get_directory_file_path(filename):
    """Return an exact or extension-equivalent path from ``directory_files``."""
    clean_filename = get_clean_filename(filename)
    directory_files = state.metadata.directory_files
    for candidate in get_interchangeable_filenames(clean_filename):
        if candidate in directory_files:
            return directory_files[candidate]
    return None


def get_file_path(playlist_entry):
    """Return the full file path for a playlist entry, or None if missing."""
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry

    if os.path.isabs(clean_entry):
        for candidate in get_interchangeable_filenames(clean_entry):
            if os.path.exists(candidate):
                return candidate
        return None

    directory_path = get_directory_file_path(clean_entry)
    if directory_path:
        return directory_path

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
