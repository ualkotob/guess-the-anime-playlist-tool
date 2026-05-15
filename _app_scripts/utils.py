"""
_app_scripts/utils.py — Pure utility helpers extracted from guess_the_anime.py.

Contains:
  - JSON infinity serialization helpers
  - Theme-flag migration helper
  - Atomic file I/O (JSON)
  - Compressed metadata I/O
  - Color conversion helpers
  - Deep-merge helpers
  - Season / slug helpers
"""

import copy
import gzip
import json
import os
import re
import tempfile
import tkinter as tk
from datetime import datetime

# ---------------------------------------------------------------------------
# JSON infinity serialization helpers
# ---------------------------------------------------------------------------

def convert_infinities_to_markers(obj):
    """Recursively convert infinity values to special markers before JSON serialization"""
    if isinstance(obj, float):
        if obj == float('inf'):
            return "__INFINITY__"
        elif obj == float('-inf'):
            return "__NEG_INFINITY__"
        return obj
    elif isinstance(obj, dict):
        return {k: convert_infinities_to_markers(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_infinities_to_markers(item) for item in obj]
    return obj


def convert_infinity_markers(obj):
    """Recursively convert special infinity markers back to float('inf')"""
    if isinstance(obj, str):
        if obj == "__INFINITY__":
            return float('inf')
        elif obj == "__NEG_INFINITY__":
            return float('-inf')
        elif obj == "inf":
            return float('inf')
        elif obj == "-inf":
            return float('-inf')
        return obj
    elif isinstance(obj, dict):
        return {k: convert_infinity_markers(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_infinity_markers(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Theme-flag migration helper
# ---------------------------------------------------------------------------

_THEME_FLAG_MIGRATIONS = {
    "OVERLAP": "OVERLAP (Without Censors)",
    "SPOILER": "SPOILER (Without Censors)",
}


def _migrate_theme_flags(filter_dict):
    """Rename legacy theme flag strings to their censor-split equivalents in-place."""
    if not isinstance(filter_dict, dict):
        return
    for key in ("themes_exclude", "themes_include"):
        val = filter_dict.get(key)
        if isinstance(val, list):
            filter_dict[key] = [_THEME_FLAG_MIGRATIONS.get(v, v) for v in val]


# ---------------------------------------------------------------------------
# Atomic file I/O (JSON)
# ---------------------------------------------------------------------------

def _atomic_json_write(path, data, **dump_kwargs):
    """Write *data* as JSON to *path* atomically.

    Writes to a sibling .tmp file first, then uses os.replace() to swap it in.
    os.replace() is atomic on both Windows (same-volume) and POSIX, so a crash
    mid-write will leave the original file intact rather than corrupting it.
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kwargs)
        os.replace(tmp, path)
    except Exception:
        # Clean up the temp file if anything went wrong, then re-raise
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def save_metadata_atomic(filepath, data, encoding=None, ensure_ascii=True):
    """Atomically save JSON data to prevent corruption on crash."""

    metadata_folder = os.path.dirname(filepath)
    if not os.path.exists(metadata_folder):
        os.makedirs(metadata_folder)

    # Write to temp file first
    fd, temp_path = tempfile.mkstemp(dir=metadata_folder, suffix='.json', text=True)
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            json.dump(data, f, indent=4, ensure_ascii=ensure_ascii)
        # Atomic rename (overwrites existing file safely)
        os.replace(temp_path, filepath)
    except Exception as e:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except Exception:
            pass
        raise e


def save_metadata_compressed(filepath, data, encoding='utf-8', ensure_ascii=True):
    """Save metadata with compressed version, and readable version only if it already exists."""

    if os.path.exists(filepath):
        save_metadata_atomic(filepath, data, encoding=encoding, ensure_ascii=ensure_ascii)

    try:
        metadata_folder = os.path.dirname(filepath)
        if not os.path.exists(metadata_folder):
            os.makedirs(metadata_folder)

        # Create temp file with .gz extension
        fd, temp_path = tempfile.mkstemp(dir=metadata_folder, suffix='.json.gz')

        try:
            # Use GzipFile to set the correct filename in gzip header
            with gzip.GzipFile(filename=os.path.basename(filepath), fileobj=os.fdopen(fd, 'wb'), mode='wb') as gz_file:
                json_str = json.dumps(data, ensure_ascii=ensure_ascii, indent=4)
                gz_file.write(json_str.encode(encoding))
            # Atomic rename
            os.replace(temp_path, filepath + '.gz')
        except Exception as e:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise e
    except Exception:
        pass  # Compression is optional optimization


def load_metadata_compressed(filepath, encoding='utf-8', name="metadata"):
    """Load metadata from compressed version first, fallback to regular file."""

    if os.path.exists(filepath + '.gz'):
        try:
            with gzip.open(filepath + '.gz', 'rt', encoding=encoding) as f:
                return json.load(f), True
        except Exception as e:
            print(f"Warning: Failed to load compressed {name}: {e}")

    if os.path.exists(filepath):
        with open(filepath, "r", encoding=encoding) as f:
            return json.load(f), False

    return None, False


# ---------------------------------------------------------------------------
# Color conversion helpers
# ---------------------------------------------------------------------------

def interpolate_color(color1, color2, factor=0.3):
    """
    Interpolate between two colors.
    Args:
        color1: Starting color (hex string or color name)
        color2: Ending color (hex string or color name)
        factor: Float between 0.0 and 1.0 (0.0 = color1, 1.0 = color2, 0.5 = halfway)
    Returns:
        Hex color string
    """
    # Convert both colors to RGB using tkinter's color resolution
    rgb1 = color_to_rgb(color1)
    rgb2 = color_to_rgb(color2)

    # Clamp factor between 0 and 1
    factor = max(0.0, min(1.0, factor))

    # Interpolate each RGB component
    r = rgb1[0] + (rgb2[0] - rgb1[0]) * factor
    g = rgb1[1] + (rgb2[1] - rgb1[1]) * factor
    b = rgb1[2] + (rgb2[2] - rgb1[2]) * factor

    return rgb_to_hex((int(r), int(g), int(b)))


def color_to_rgb(color):
    """Convert any color (hex, name, etc.) to RGB tuple using tkinter"""
    try:
        temp_root = None
        if _tk_root is None:
            temp_root = tk.Tk()
            temp_root.withdraw()  # Hide the temporary window
            widget_parent = temp_root
        else:
            widget_parent = _tk_root

        # Create a temporary tkinter widget to resolve color names
        temp_widget = tk.Label(widget_parent)
        # Use winfo_rgb to convert any color format to RGB values (0-65535 range)
        rgb_16bit = temp_widget.winfo_rgb(color)
        temp_widget.destroy()

        if temp_root:
            temp_root.destroy()

        # Convert from 16-bit (0-65535) to 8-bit (0-255) RGB
        return tuple(int(val / 257) for val in rgb_16bit)
    except (tk.TclError, NameError):
        # If color is invalid, try parsing as hex manually
        if isinstance(color, str) and color.startswith('#'):
            hex_color = color.lstrip('#')
            if len(hex_color) == 3:  # Handle short hex like #FFF
                hex_color = ''.join([c * 2 for c in hex_color])
            try:
                return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
            except (ValueError, IndexError):
                pass
        return (128, 128, 128)


def rgb_to_hex(rgb):
    """Convert RGB tuple to hex color"""
    return "#{:02x}{:02x}{:02x}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


# Module-level tkinter root reference (set via set_context for efficiency)
_tk_root = None


def set_context(root):
    """Provide the application's tkinter root so color_to_rgb avoids creating temp windows."""
    global _tk_root
    _tk_root = root


# ---------------------------------------------------------------------------
# Deep-merge helpers
# ---------------------------------------------------------------------------

def deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        elif isinstance(value, list) and isinstance(base.get(key), list) and key == "songs":
            merge_songs_by_slug(base[key], value)
        else:
            base[key] = value


def merge_songs_by_slug(base_songs, override_songs):
    slug_index = {song.get("slug"): song for song in base_songs if isinstance(song, dict)}
    for override_song in override_songs:
        slug = override_song.get("slug")
        if not slug:
            continue
        base_song = slug_index.get(slug)
        if base_song:
            deep_merge(base_song, override_song)
        else:
            base_songs.append(override_song)  # New song, not found in base


# ---------------------------------------------------------------------------
# Season / slug helpers
# ---------------------------------------------------------------------------

def _season_to_tuple(season_str):
    """Convert a season string like 'Fall 2020' to a sortable tuple."""
    try:
        part, year = season_str.split()
        _season_order = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
        return (int(year), _season_order.get(part, -1))
    except Exception:
        return (0, -1)  # Very early season so it passes min filters but fails max


def get_song_by_slug(data, slug):
    """Returns the list of artists for the song matching the given slug."""
    for theme in data.get("songs", []):  # Iterate through themes
        if theme["slug"] == slug:  # Find the matching slug
            return theme
    return {}  # Return empty list if no match


# ---------------------------------------------------------------------------
# Settings sync / diff helpers
# ---------------------------------------------------------------------------

def sync_with_default(saved, default):
    # First, remove any keys not in the default
    keys_to_remove = [key for key in saved if key not in default]
    for key in keys_to_remove:
        del saved[key]

    # Then, add missing keys and recurse into nested dicts
    for key, default_value in default.items():
        if key not in saved:
            saved[key] = default_value
        elif isinstance(default_value, dict) and isinstance(saved[key], dict):
            sync_with_default(saved[key], default_value)
        else:
            # Optional: If types mismatch, replace with default
            if not isinstance(saved[key], type(default_value)):
                saved[key] = default_value
    return saved


def compute_settings_diff(default, saved):
    """Return a dict containing only the keys in `saved` that differ from `default`.
    Works recursively for nested dicts. If a nested dict has no differing keys, it's omitted.
    """
    if not isinstance(saved, dict) or not isinstance(default, dict):
        return copy.deepcopy(saved) if saved != default else None

    diff = {}
    for key, val in saved.items():
        if key not in default:
            # Key not in default - store it
            diff[key] = copy.deepcopy(val)
            continue
        default_val = default[key]
        if isinstance(val, dict) and isinstance(default_val, dict):
            sub = compute_settings_diff(default_val, val)
            if sub:
                diff[key] = sub
        else:
            if val != default_val:
                diff[key] = copy.deepcopy(val)
    return diff if diff else None


def _load_settings_presets(folder):
    """Load all preset JSON files from a folder, returning {name: diff_dict}."""
    presets = {}
    if not os.path.exists(folder):
        return presets
    for fname in sorted(os.listdir(folder)):
        if fname.endswith(".json"):
            name = fname[:-5]
            try:
                with open(os.path.join(folder, fname), "r", encoding="utf-8") as f:
                    presets[name] = json.load(f)
            except Exception as e:
                print(f"Failed to load preset '{fname}': {e}")
    return presets


def _save_settings_presets(folder, saved_dict, default_dict, update_fn=None, convert_inf=False):
    """Sync all presets in saved_dict to individual JSON files in folder.
    Writes current presets as diffs against default_dict, removes orphan files."""
    os.makedirs(folder, exist_ok=True)
    for name, settings in saved_dict.items():
        if update_fn:
            full = update_fn(settings)
        else:
            full = sync_with_default(copy.deepcopy(settings), default_dict)
        diff = compute_settings_diff(default_dict, full)
        data = diff if diff is not None else {}
        if convert_inf:
            data = convert_infinities_to_markers(data)
        try:
            _atomic_json_write(os.path.join(folder, f"{name}.json"), data, indent=4)
        except Exception as e:
            print(f"Failed to save preset '{name}': {e}")
    # Remove orphan files
    current_names = set(saved_dict.keys())
    for fname in os.listdir(folder):
        if fname.endswith(".json") and fname[:-5] not in current_names:
            try:
                os.remove(os.path.join(folder, fname))
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Misc pure helpers
# ---------------------------------------------------------------------------

def format_seconds(seconds):
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f"{minutes:02}:{remaining_seconds:02}"


def parse_timestamp_flexible(timestamp_str):
    """Parse timestamp that can be either 'HH:MM:SS' or 'YYYY-MM-DD HH:MM:SS' format"""
    try:
        # Try full datetime format first
        if len(timestamp_str) > 8:  # Full datetime format
            return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        else:  # Time-only format - use today's date
            time_part = datetime.strptime(timestamp_str, '%H:%M:%S').time()
            return datetime.combine(datetime.now().date(), time_part)
    except ValueError:
        return datetime.now()


def split_array(arr, parts=2):
    if parts <= 0:
        raise ValueError("Number of parts must be positive")

    avg_len = len(arr) / float(parts)
    output = []
    last = 0.0

    while last < len(arr):
        output.append(arr[int(last):int(last + avg_len)])
        last += avg_len

    return output


def format_slug(slug):
    """Converts OP/ED notation to full text format."""
    if slug.startswith("OP"):
        return f"Opening {slug[2:]}"
    elif slug.startswith("ED"):
        return f"Ending {slug[2:]}"
    return slug  # Return unchanged if it doesn't match


def is_slug_op(slug):
    return slug.startswith("OP")
