"""Helpers for resolving playlist entries to paths and clean filenames."""

import os

from core.game_state import state
import _app_scripts.playback.cache_download as cache_download


_INTERCHANGEABLE_THEME_EXTENSIONS = (".webm", ".mp4")
_THEME_REFERENCE_PREFIX = "[THEME_REF]"
_THEME_REFERENCE_SEPARATOR = "::"


def make_theme_reference(filename, mal_id, slug, version=None):
    """Return an internal playlist entry that keeps a shared file's identity."""
    existing_reference = parse_theme_reference(filename)
    if mal_id is None or not slug:
        return filename if existing_reference else get_clean_filename(filename)
    filename = get_clean_filename(filename)
    if not filename:
        return filename
    version_text = "" if version is None else str(version)
    return (
        f"{_THEME_REFERENCE_PREFIX}{mal_id}|{slug}|{version_text}"
        f"{_THEME_REFERENCE_SEPARATOR}{filename}"
    )


def parse_theme_reference(playlist_entry):
    """Parse an internal shared-theme reference, or return ``None``."""
    if not isinstance(playlist_entry, str):
        return None
    entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    if not entry.startswith(_THEME_REFERENCE_PREFIX):
        return None
    payload = entry[len(_THEME_REFERENCE_PREFIX):]
    if _THEME_REFERENCE_SEPARATOR not in payload:
        return None
    identity, filename = payload.split(_THEME_REFERENCE_SEPARATOR, 1)
    parts = identity.split("|", 2)
    if len(parts) != 3 or not parts[0] or not parts[1] or not filename:
        return None
    return {
        "mal_id": parts[0],
        "slug": parts[1],
        "version": parts[2] or None,
        "filename": filename,
    }


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
    if isinstance(playlist_entry, dict):
        playlist_entry = playlist_entry.get("filename", playlist_entry.get("filepath", ""))
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    reference = parse_theme_reference(clean_entry)
    if reference:
        clean_entry = reference["filename"]

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
    """Remove internal prefixes and return the physical filename."""
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    reference = parse_theme_reference(clean_entry)
    if reference:
        clean_entry = reference["filename"]
    if base_only:
        # Lazy import: metadata_display imports entry_paths, so reach it at call time.
        import _app_scripts.file.metadata.metadata_display as metadata_display
        clean_entry = metadata_display._play_name_key(clean_entry)
    return os.path.basename(clean_entry) if os.path.isabs(clean_entry) else clean_entry
