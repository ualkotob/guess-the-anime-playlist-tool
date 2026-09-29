"""Playlist filtering: the filter popup UI, saved-filter load/delete, the
metadata-aggregation helpers that populate the popup (seasons, artists, tags,
studios, parameter ranges), and filter_playlist() which applies a filter dict
to the live playlist (or, for infinite playlists, narrows the source pool).

Extracted from playlist.py. filter_playlist is also called by playlist's
infinite pop-time grouping, so playlist imports this module and this module
imports playlist (for get_infinite_settings / get_directory_files /
refresh_pop_time_groups / get_playlists_dict) — both references are runtime
only, so the cycle resolves cleanly.
"""
import copy
import hashlib
import json
import math
import os
import re

import tkinter as tk
from tkinter import messagebox, simpledialog
from tkinter import ttk

from core.game_state import state
from core.paths import PLAYLISTS_FOLDER, FILTERS_FOLDER
from _app_scripts import utils
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.information.information_popup as information_popup
import _app_scripts.toggles.censors as censors
import _app_scripts.ui.lists as lists
import _app_scripts.playback.transport as transport
import _app_scripts.data.config_io as config_io
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.ui.windowing as windowing
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.playlists.infinite as infinite

BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR
INT_INF = float('inf')

filter_popup = None
DEFAULT_INFINITE_FILTER_NAME = "Default Infinite Playlist Filter"
DEFAULT_THEME_TYPE = "Opening + Ending"
THEME_TYPE_OPTIONS = [DEFAULT_THEME_TYPE, "Opening", "Ending", "Insert", "All"]
ANISONGDB_RISK_WITHOUT_CENSORS = "ASDB NSFW (Without Censors)"
ANISONGDB_RISK_WITH_CENSORS = "ASDB NSFW (With Censors)"
DEFAULT_INFINITE_FILTER = {
    "themes_exclude": [
        "OVERLAP (Without Censors)", "NSFW (Without Censors)",
        ANISONGDB_RISK_WITHOUT_CENSORS,
        "TRANSITION (Without Censors)", "MOVIE EDs (Without Censors)",
    ],
    "playlist_filter_exclude": ["Tagged Themes", "New Themes"],
}

THEME_FILTER_OPTIONS = [
    "DUPLICATES", "LATER VERSIONS",
    "OVERLAP (Without Censors)", "OVERLAP (With Censors)",
    "NSFW (Without Censors)", "NSFW (With Censors)",
    ANISONGDB_RISK_WITHOUT_CENSORS, ANISONGDB_RISK_WITH_CENSORS,
    "SPOILER (Without Censors)", "SPOILER (With Censors)",
    "TRANSITION (Without Censors)", "TRANSITION (With Censors)",
    "MOVIE EDs (Without Censors)", "MOVIE EDs (With Censors)",
]

FILTER_LIST_KEYS = {
    "playlist_filter", "playlist_filter_and", "playlist_filter_exclude",
    "themes_include", "themes_exclude", "artists", "studios",
    "tags_include", "tags_include_and", "tags_exclude",
}
FILTER_FLOAT_KEYS = {"score_min", "score_max"}
FILTER_INT_KEYS = {
    "rank_min", "rank_max", "members_min", "members_max",
    "popularity_min", "popularity_max",
}
FILTER_KEYS = (
    FILTER_LIST_KEYS | FILTER_FLOAT_KEYS | FILTER_INT_KEYS |
    {"keywords", "theme_type", "season_min", "season_max"}
)

# The web editor remembers the unfiltered base of the most recent ordinary
# playlist.  This lets a host loosen a filter after applying it; evaluating
# against the already-filtered result would otherwise make removed entries
# impossible to recover without reloading the playlist.
_editor_regular_source = None
_editor_regular_name = None
_editor_regular_result_revision = None
_editor_regular_filter = {}


class FilterValidationError(ValueError):
    """Raised when an untrusted filter definition cannot be normalized."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _normalized_string_list(value, key, errors):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        errors.append(f"{key} must be a list")
        return []
    if len(value) > 500:
        errors.append(f"{key} has too many selections")
        value = list(value)[:500]
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            errors.append(f"{key} contains a non-text selection")
            continue
        item = item.strip()
        if not item:
            continue
        if len(item) > 200:
            errors.append(f"{key} contains a selection that is too long")
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def normalize_filter(filters, *, strict=False):
    """Return a safe, canonical filter dictionary.

    Saved desktop filters are normalized permissively for backwards
    compatibility. Browser submissions use ``strict=True`` so malformed or
    unknown fields are reported instead of silently reaching filter logic.
    """
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise FilterValidationError(["Filter data must be an object"])

    source = copy.deepcopy(filters)
    utils._migrate_theme_flags(source)
    errors = []
    if strict:
        unknown = sorted(set(source) - FILTER_KEYS)
        if unknown:
            errors.append("Unknown filter fields: " + ", ".join(unknown))

    normalized = {}
    for key in FILTER_LIST_KEYS:
        if key not in source:
            continue
        values = _normalized_string_list(source.get(key), key, errors)
        if strict and key.startswith("playlist_filter"):
            unsafe_names = [
                value for value in values
                if value != os.path.basename(value) or "/" in value or "\\" in value
            ]
            if unsafe_names:
                errors.append(f"{key} contains an invalid playlist name")
                values = [value for value in values if value not in unsafe_names]
        if key in {"themes_include", "themes_exclude"}:
            unknown_flags = [value for value in values if value not in THEME_FILTER_OPTIONS]
            if strict and unknown_flags:
                errors.append(f"{key} contains unknown theme rules")
            values = [value for value in values if value in THEME_FILTER_OPTIONS]
        if values:
            normalized[key] = values

    if "keywords" in source:
        value = source.get("keywords")
        if not isinstance(value, str):
            errors.append("keywords must be text")
        else:
            value = value.strip()
            if len(value) > 500:
                errors.append("keywords is too long")
            elif value:
                normalized["keywords"] = value

    theme_type = source.get("theme_type")
    if theme_type not in (None, "", "Both", DEFAULT_THEME_TYPE):
        if theme_type in {"Opening", "Ending", "Insert", "All"}:
            normalized["theme_type"] = theme_type
        else:
            errors.append(
                "theme_type must be Opening + Ending, Opening, Ending, Insert, or All"
            )

    for key in FILTER_FLOAT_KEYS | FILTER_INT_KEYS:
        if key not in source or source.get(key) in (None, ""):
            continue
        value = source.get(key)
        try:
            if isinstance(value, bool):
                raise ValueError
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
            if key in FILTER_FLOAT_KEYS:
                if not 0 <= number <= 10:
                    raise ValueError
                normalized[key] = round(number, 1)
            else:
                if not number.is_integer() or not 0 <= number <= 2_147_483_647:
                    raise ValueError
                normalized[key] = int(number)
        except (TypeError, ValueError):
            limit = "between 0 and 10" if key in FILTER_FLOAT_KEYS else "a non-negative whole number"
            errors.append(f"{key} must be {limit}")

    for key in ("season_min", "season_max"):
        if key not in source or source.get(key) in (None, ""):
            continue
        value = source.get(key)
        if not isinstance(value, str) or not re.fullmatch(
            r"(?:Winter|Spring|Summer|Fall)\s+\d{4}", value.strip()
        ):
            errors.append(f"{key} must be a season such as Spring 2024")
        else:
            normalized[key] = value.strip()

    ordered_pairs = [
        ("score_min", "score_max"),
        ("members_min", "members_max"),
        # Rank and popularity use best-number / worst-number semantics: the
        # *_max field is the best accepted number and *_min is the worst.
        ("rank_max", "rank_min"),
        ("popularity_max", "popularity_min"),
    ]
    for low_key, high_key in ordered_pairs:
        if low_key in normalized and high_key in normalized and normalized[low_key] > normalized[high_key]:
            errors.append(f"{low_key} cannot be greater than {high_key}")
    if "season_min" in normalized and "season_max" in normalized:
        if utils._season_to_tuple(normalized["season_min"]) > utils._season_to_tuple(normalized["season_max"]):
            errors.append("season_min cannot be later than season_max")

    if errors:
        raise FilterValidationError(errors)
    return normalized


def _playlist_revision(files=None):
    playlist = state.metadata.playlist
    values = list(playlist.get("playlist", [])) if files is None else list(files)
    payload = json.dumps(
        [playlist.get("name", ""), bool(playlist.get("infinite")), values],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def load_filters(update=False):
    filters = get_all_filters()
    lists.show_list("load_filters", state.widgets.right_column, filters, get_filter_name, load_filter, -1, update, delete_filter, title="LOAD FILTER")


def get_filter_name(key, value):
    return value.get("name")


def upgrade_default_infinite_filter(filter_dict):
    """Add new safety defaults only when a filter is the untouched old default."""
    if not isinstance(filter_dict, dict):
        return False
    migrated_filter = copy.deepcopy(filter_dict)
    utils._migrate_theme_flags(migrated_filter)
    if migrated_filter == DEFAULT_INFINITE_FILTER:
        if filter_dict == DEFAULT_INFINITE_FILTER:
            return False
        filter_dict.clear()
        filter_dict.update(copy.deepcopy(DEFAULT_INFINITE_FILTER))
        return True
    legacy_default = copy.deepcopy(DEFAULT_INFINITE_FILTER)
    legacy_default["themes_exclude"].remove(ANISONGDB_RISK_WITHOUT_CENSORS)
    if migrated_filter != legacy_default:
        return False
    filter_dict.clear()
    filter_dict.update(copy.deepcopy(DEFAULT_INFINITE_FILTER))
    return True



def ensure_default_infinite_filter_saved():
    """Create the default preset, or safely upgrade an untouched old default."""
    existing_filters = get_all_filters()
    for filter_data in existing_filters.values():
        if filter_data.get("name") == DEFAULT_INFINITE_FILTER_NAME:
            if upgrade_default_infinite_filter(filter_data.get("filter")):
                filter_path = os.path.join(
                    FILTERS_FOLDER, f"{DEFAULT_INFINITE_FILTER_NAME}.json"
                )
                utils._atomic_json_write(
                    filter_path,
                    {
                        "name": DEFAULT_INFINITE_FILTER_NAME,
                        "filter": copy.deepcopy(DEFAULT_INFINITE_FILTER),
                    },
                    indent=4,
                )
                return True
            return False
    os.makedirs(FILTERS_FOLDER, exist_ok=True)
    filter_path = os.path.join(FILTERS_FOLDER, f"{DEFAULT_INFINITE_FILTER_NAME}.json")
    utils._atomic_json_write(
        filter_path,
        {"name": DEFAULT_INFINITE_FILTER_NAME, "filter": copy.deepcopy(DEFAULT_INFINITE_FILTER)},
        indent=4,
    )
    return True


def load_filter(index):
    """Applies a saved filter from JSON."""
    filters_by_index = get_all_filters()
    filter_data = filters_by_index[index]
    name = filter_data.get('name')
    confirm = messagebox.askyesno("Filter Playlist", f"Are you sure you want to apply the filter '{name}'?")
    if not confirm:
        return
    apply_saved_filter(name, filters_by_index=filters_by_index)


def apply_saved_filter(name, filters_by_index=None, notify=True):
    """Apply a saved filter by name without showing the desktop confirmation."""
    filters_by_index = filters_by_index if filters_by_index is not None else get_all_filters()
    filter_data = next(
        (data for data in filters_by_index.values() if data.get("name") == name),
        None,
    )
    if not filter_data:
        return False
    filters = normalize_filter(filter_data.get("filter") or {})
    playlist = state.metadata.playlist
    if playlist.get("infinite"):
        playlist["filter"] = filters
        print("Applied Filters:", filters)
        infinite.refresh_pop_time_groups()
        config_io.save_config()
    else:
        filter_playlist(filters, notify=notify)
    return True


def delete_filters(update=False):
    filters = get_all_filters()
    lists.show_list("delete_filters", state.widgets.right_column, filters, get_filter_name, delete_filter, -1, update, title="DELETE FILTER")


def delete_filter(index):
    """Deletes a filter by index after confirmation."""
    filters = get_all_filters()
    if index not in filters:
        print("Invalid filter index.")
        return
    name = filters[index].get('name')
    filename = os.path.join(FILTERS_FOLDER, f"{name}.json")
    confirm = messagebox.askyesno("Delete Filter", f"Are you sure you want to delete '{name}'?")
    if not confirm:
        return
    try:
        os.remove(filename)
        print(f"Deleted filter: {name}")
    except Exception as e:
        print(f"Error deleting filter: {e}")
        return
    list_loaded = state.lists.list_loaded
    if list_loaded == "load_filters":
        load_filters(True)
    elif list_loaded == "delete_filters":
        delete_filters(True)


def filters():
    show_filter_popup()


def _season_sort_key(season):
    try:
        part, year = season.split()
        return int(year), {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}.get(part, 99)
    except (AttributeError, TypeError, ValueError):
        return 9999, 99


def _aggregate_filter_metadata(playlis):
    """Collect filter options and numeric ranges in one pass over each title.

    A playlist can contain several video versions and several themes for the
    same anime. All fields used here are anime-level fields, so processing the
    first file for each metadata entry is sufficient and avoids repeatedly
    walking the same (potentially very large) song list.
    """
    if not metadata_fetch.filename_to_mal:
        metadata_fetch.build_filename_to_mal_map()

    seasons = set()
    artists = set()
    studios = set()
    tags = set()
    numeric_values = {
        "score": [],
        "rank": [],
        "members": [],
        "popularity": [],
    }
    seen_entries = set()

    for filename in playlis:
        lookup = metadata_fetch.filename_to_mal.get(filename)
        if lookup is None:
            lookup = metadata_fetch.filename_to_mal.get(os.path.splitext(filename)[0])
        identity = (
            ("metadata", str(lookup.get("mal_id")))
            if isinstance(lookup, dict) and lookup.get("mal_id") is not None
            else ("file", filename)
        )
        if identity in seen_entries:
            continue
        seen_entries.add(identity)

        data = metadata_fetch.get_metadata(filename)
        if not data:
            continue
        season = data.get("season")
        if season:
            seasons.add(season)

        for key, values in numeric_values.items():
            value = data.get(key)
            if value is None:
                continue
            try:
                values.append(float(value) if key == "score" else int(value))
            except (TypeError, ValueError, OverflowError):
                continue

        for song in data.get("songs") or []:
            if not isinstance(song, dict):
                continue
            artists.update(
                artist
                for artist in (song.get("artist") or [])
                if isinstance(artist, str) and artist
            )
        studios.update(
            studio
            for studio in (data.get("studios") or [])
            if isinstance(studio, str) and studio
        )
        tags.update(
            tag
            for tag in information_popup.get_tags(data)
            if isinstance(tag, str) and tag
        )

    def value_range(key, fallback_min=0, fallback_max=0):
        values = numeric_values[key]
        return {
            "min": min(values) if values else fallback_min,
            "max": max(values) if values else fallback_max,
        }

    return {
        "seasons": sorted(seasons, key=_season_sort_key),
        "artists": sorted(artists, key=str.lower),
        "studios": sorted(studios, key=str.lower),
        "tags": sorted(tags, key=str.lower),
        "ranges": {
            "score": value_range("score", 0, 10),
            "rank": value_range("rank"),
            "members": value_range("members"),
            "popularity": value_range("popularity"),
        },
    }


def show_filter_popup():
    """Opens a properly formatted, scrollable popup for filtering the playlist."""
    global filter_popup
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        inf_settings = infinite.get_infinite_settings()
        playlis = playlist_ops.get_directory_files(include_non_local=inf_settings.get("include_non_local_files", False), deduplicate_files=False, deduplicate_versions=False)
    else:
        playlis = playlist["playlist"]
    aggregate = _aggregate_filter_metadata(playlis)
    ranges = aggregate["ranges"]

    def update_score_range(event=None):
        min_score = min_score_slider.get()
        max_score = max_score_slider.get()
        if min_score > max_score:
            if event == min_score:
                max_score_slider.set(min_score)
            else:
                min_score_slider.set(max_score)

    def filter_entry_range(title, root_frame, start, end):
        frame = tk.Frame(root_frame, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        tk.Label(frame, text=title + " RANGE:", bg=BACKGROUND_COLOR, fg="white").pack(side="left")
        min_entry = tk.Entry(frame, bg="black", fg="white", justify="center", width=8)
        min_entry.pack(side="left")
        tk.Label(frame, text=" TO ", bg=BACKGROUND_COLOR, fg="white").pack(side="left")
        max_entry = tk.Entry(frame, bg="black", fg="white", justify="center", width=8)
        max_entry.pack(side="left")
        return {"min": min_entry, "max": max_entry}

    def filter_entry_listbox(title, root_frame, data, height=6):
        frame = tk.Frame(root_frame, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        label_and_list = tk.Frame(frame, bg=BACKGROUND_COLOR)
        label_and_list.pack(fill="x")
        tk.Label(label_and_list, text=title, bg=BACKGROUND_COLOR, fg="white").pack(side="left")
        listbox = tk.Listbox(label_and_list, selectmode=tk.MULTIPLE, height=height, width=28, exportselection=False, bg="black", fg="white")
        listbox.pack(side="left", fill="x", expand=True)
        scrollbar = tk.Scrollbar(label_and_list, command=listbox.yview, bg="black")
        scrollbar.pack(side="right", fill="y")
        listbox.config(yscrollcommand=scrollbar.set)
        if data:
            listbox.insert(tk.END, *data)
        listbox._filter_indices = {item: index for index, item in enumerate(data)}

        def on_mousewheel(event):
            listbox.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
        listbox.bind("<MouseWheel>", on_mousewheel)
        return listbox

    try:
        filter_popup.destroy()
    except Exception:
        pass
    popup = tk.Toplevel(bg="black")
    popup.title("Filter Playlist")
    popup_width = 550
    popup_height = 700
    filter_popup = popup
    popup.update_idletasks()
    popout_controls = popout_window.popout_controls
    if popout_controls and popout_controls.winfo_exists():
        x = popout_controls.winfo_x()
        y = popout_controls.winfo_y()
    else:
        x, y = windowing.get_window_position_and_setup()
    popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")

    main_frame = tk.Frame(popup, bg=BACKGROUND_COLOR)
    main_frame.pack(fill="both", expand=True)

    canvas = tk.Canvas(main_frame, bg=BACKGROUND_COLOR)
    scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=BACKGROUND_COLOR)
    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    columns_frame = tk.Frame(scrollable_frame, bg=BACKGROUND_COLOR)
    columns_frame.pack(fill="both", expand=True)

    left_column = tk.Frame(columns_frame, bg=BACKGROUND_COLOR)
    left_column.pack(side="left", fill="both", expand=True, padx=10)

    right_column = tk.Frame(columns_frame, bg=BACKGROUND_COLOR)
    right_column.pack(side="right", fill="both", expand=True, padx=10)

    available_playlists = list(playlist_ops.get_playlists_dict().values())
    playlist_listbox = filter_entry_listbox("PLAYLISTS\nINCLUDE\n(OR)", left_column, available_playlists, height=4)
    playlist_and_listbox = filter_entry_listbox("PLAYLISTS\nINCLUDE\n(AND)", left_column, available_playlists, height=4)

    tk.Label(left_column, text="KEYWORDS (separated by commas):", bg=BACKGROUND_COLOR, fg="white").pack(anchor="w", pady=(5, 0))
    keywords_entry = tk.Text(left_column, height=1, width=31, bg="black", fg="white", wrap="word")
    keywords_entry.pack(pady=(0, 5))

    theme_type_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    theme_type_frame.pack(fill="x", pady=5)

    tk.Label(theme_type_frame, text="THEME TYPE:", bg=BACKGROUND_COLOR, fg="white").pack(side="left", padx=(0, 7))

    theme_var = tk.StringVar(value=DEFAULT_THEME_TYPE)
    theme_type_combobox = ttk.Combobox(
        theme_type_frame, textvariable=theme_var,
        values=THEME_TYPE_OPTIONS, width=20,
        style="Black.TCombobox", state="readonly",
    )
    theme_type_combobox.pack(side="left", fill="x", expand=True)

    score_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    score_frame.pack(fill="x", pady=5)
    tk.Label(score_frame, text="SCORE\nRANGE", bg=BACKGROUND_COLOR, fg="white").pack(side="left")
    lowest_score = ranges["score"]["min"]
    highest_score = ranges["score"]["max"]
    min_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, orient="horizontal", bg="black", fg="white", command=update_score_range)
    min_score_slider.pack(fill="x")
    max_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, orient="horizontal", bg="black", fg="white", command=update_score_range)
    max_score_slider.pack(fill="x")

    lowest_rank, highest_rank = ranges["rank"]["min"], ranges["rank"]["max"]
    lowest_members, highest_members = ranges["members"]["min"], ranges["members"]["max"]
    lowest_popularity = ranges["popularity"]["min"]
    highest_popularity = ranges["popularity"]["max"]
    rank_entry = filter_entry_range("RANK               ", left_column, highest_rank, lowest_rank)
    members_entry = filter_entry_range("MEMBERS       ", left_column, lowest_members, highest_members)
    popularity_entry = filter_entry_range(
        "POPULARITY  ", left_column, highest_popularity, lowest_popularity
    )

    season_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    season_frame.pack(fill="x", pady=(5, 10))

    tk.Label(season_frame, text="AIRED:   ", bg=BACKGROUND_COLOR, fg="white").pack(side="left")

    all_seasons = aggregate["seasons"]

    season_start_var = tk.StringVar()
    season_end_var = tk.StringVar()

    season_start_dropdown = ttk.Combobox(season_frame, textvariable=season_start_var, values=all_seasons, height=10, width=12, style="Black.TCombobox", state="readonly")
    season_start_dropdown.pack(side="left")

    def unhighlight_season_start_dropdown(event):
        season_start_dropdown.selection_clear()
        season_start_dropdown.icursor(tk.END)
    season_start_dropdown.bind("<<ComboboxSelected>>", unhighlight_season_start_dropdown)

    tk.Label(season_frame, text="TO", bg=BACKGROUND_COLOR, fg="white").pack(side="left")

    season_end_dropdown = ttk.Combobox(season_frame, textvariable=season_end_var, values=list(reversed(all_seasons)), height=10, width=12, style="Black.TCombobox", state="readonly")
    season_end_dropdown.pack(side="left")

    def unhighlight_season_end_dropdown(event):
        season_end_dropdown.selection_clear()
        season_end_dropdown.icursor(tk.END)
    season_end_dropdown.bind("<<ComboboxSelected>>", unhighlight_season_end_dropdown)

    theme_exclude_options = THEME_FILTER_OPTIONS
    themes_include_listbox = filter_entry_listbox("THEMES\nINCLUDE\n(OR)", left_column, theme_exclude_options, height=4)
    themes_exclude_listbox = filter_entry_listbox("THEMES\nEXCLUDE\n(OR)", left_column, theme_exclude_options, height=4)
    playlist_exclude_listbox = filter_entry_listbox("PLAYLISTS\nEXCLUDE\n(OR)", right_column, available_playlists, height=4)
    artists_listbox = filter_entry_listbox(
        "ARTISTS\nINCLUDE\n(OR)", right_column, aggregate["artists"]
    )
    studio_listbox = filter_entry_listbox(
        "STUDIOS\nINCLUDE\n(OR)", right_column, aggregate["studios"]
    )
    all_tags = aggregate["tags"]
    tags_listbox = filter_entry_listbox("TAGS\nINCLUDE\n(OR)", right_column, all_tags)
    tags_and_listbox = filter_entry_listbox("TAGS\nINCLUDE\n(AND)", right_column, all_tags)
    excluded_tags_listbox = filter_entry_listbox("TAGS\nEXCLUDE\n(OR)", right_column, all_tags)

    def set_default_values(force_defaults=False):
        filter_data = {} if force_defaults else playlist.get("filter", {})
        if "playlist_filter" in filter_data and isinstance(filter_data["playlist_filter"], str):
            filter_data["playlist_filter"] = [filter_data["playlist_filter"]]
        keywords_entry.delete("1.0", tk.END)
        keywords_entry.insert("1.0", filter_data.get("keywords", ""))
        selected_theme_type = filter_data.get("theme_type", DEFAULT_THEME_TYPE)
        if selected_theme_type == "Both":
            selected_theme_type = DEFAULT_THEME_TYPE
        theme_var.set(selected_theme_type)
        min_score_slider.set(filter_data.get("score_min", lowest_score))
        max_score_slider.set(filter_data.get("score_max", highest_score))
        rank_entry["min"].delete(0, tk.END)
        rank_entry["min"].insert(0, filter_data.get("rank_min", highest_rank))
        rank_entry["max"].delete(0, tk.END)
        rank_entry["max"].insert(0, filter_data.get("rank_max", lowest_rank))
        season_start_var.set(filter_data.get("season_min", all_seasons[0] if all_seasons else ""))
        season_end_var.set(filter_data.get("season_max", all_seasons[-1] if all_seasons else ""))
        members_entry["min"].delete(0, tk.END)
        members_entry["min"].insert(0, filter_data.get("members_min", lowest_members))
        members_entry["max"].delete(0, tk.END)
        members_entry["max"].insert(0, filter_data.get("members_max", highest_members))
        popularity_entry["min"].delete(0, tk.END)
        popularity_entry["min"].insert(0, filter_data.get("popularity_min", highest_popularity))
        popularity_entry["max"].delete(0, tk.END)
        popularity_entry["max"].insert(0, filter_data.get("popularity_max", lowest_popularity))
        for listbox, key in [
            (playlist_listbox, "playlist_filter"),
            (playlist_and_listbox, "playlist_filter_and"),
            (playlist_exclude_listbox, "playlist_filter_exclude"),
            (artists_listbox, "artists"),
            (studio_listbox, "studios"),
            (tags_listbox, "tags_include"),
            (tags_and_listbox, "tags_include_and"),
            (excluded_tags_listbox, "tags_exclude"),
            (themes_exclude_listbox, "themes_exclude"),
            (themes_include_listbox, "themes_include"),
        ]:
            listbox.selection_clear(0, tk.END)
            if not force_defaults and key in filter_data:
                values = filter_data[key]
                for value in values:
                    index = listbox._filter_indices.get(value)
                    if index is not None:
                        listbox.selection_set(index)

    set_default_values()

    def extract_filter():
        def assign_filter_range_value(filter, type, entry, start, end):
            if start > end:
                if int(entry['min'].get()) < start: filter[type + '_min'] = int(entry['min'].get())
                if int(entry['max'].get()) > end: filter[type + '_max'] = int(entry['max'].get())
            else:
                if int(entry['min'].get()) > start: filter[type + '_min'] = int(entry['min'].get())
                if int(entry['max'].get()) < end: filter[type + '_max'] = int(entry['max'].get())
            return filter

        f = {}
        if playlist_listbox.curselection(): f["playlist_filter"] = [playlist_listbox.get(i) for i in playlist_listbox.curselection()]
        if playlist_and_listbox.curselection(): f["playlist_filter_and"] = [playlist_and_listbox.get(i) for i in playlist_and_listbox.curselection()]
        if playlist_exclude_listbox.curselection(): f["playlist_filter_exclude"] = [playlist_exclude_listbox.get(i) for i in playlist_exclude_listbox.curselection()]
        if keywords_entry.get("1.0", "end-1c").strip() != "": f['keywords'] = str(keywords_entry.get("1.0", "end-1c").strip())
        if theme_var.get() != DEFAULT_THEME_TYPE: f['theme_type'] = str(theme_var.get())
        if float(min_score_slider.get()) != round(lowest_score, 1): f['score_min'] = float(min_score_slider.get())
        if float(max_score_slider.get()) != round(highest_score, 1): f['score_max'] = float(max_score_slider.get())
        f = assign_filter_range_value(f, 'rank', rank_entry, highest_rank, lowest_rank)
        f = assign_filter_range_value(f, 'members', members_entry, lowest_members, highest_members)
        f = assign_filter_range_value(
            f, 'popularity', popularity_entry, highest_popularity, lowest_popularity
        )
        if all_seasons and season_start_var.get() != all_seasons[0]: f["season_min"] = season_start_var.get()
        if all_seasons and season_end_var.get() != all_seasons[-1]: f["season_max"] = season_end_var.get()
        if themes_exclude_listbox.curselection(): f["themes_exclude"] = [themes_exclude_listbox.get(i) for i in themes_exclude_listbox.curselection()]
        if themes_include_listbox.curselection(): f["themes_include"] = [themes_include_listbox.get(i) for i in themes_include_listbox.curselection()]
        if artists_listbox.curselection(): f["artists"] = [artists_listbox.get(i) for i in artists_listbox.curselection()]
        if studio_listbox.curselection(): f["studios"] = [studio_listbox.get(i) for i in studio_listbox.curselection()]
        if tags_listbox.curselection(): f["tags_include"] = [tags_listbox.get(i) for i in tags_listbox.curselection()]
        if tags_and_listbox.curselection(): f["tags_include_and"] = [tags_and_listbox.get(i) for i in tags_and_listbox.curselection()]
        if excluded_tags_listbox.curselection(): f["tags_exclude"] = [excluded_tags_listbox.get(i) for i in excluded_tags_listbox.curselection()]
        return f

    def apply_filter():
        f = extract_filter()
        playlist = state.metadata.playlist
        if playlist.get("infinite"):
            playlist["filter"] = f
            print("Applied Filters:", f)
            infinite.refresh_pop_time_groups()
            config_io.save_config()
        else:
            filter_playlist(f)
        popup.destroy()

    def reset_filter():
        set_default_values(True)

    def save_filter_action():
        f = extract_filter()
        if not os.path.exists(FILTERS_FOLDER):
            os.makedirs(FILTERS_FOLDER)
        filter_name = simpledialog.askstring("Save Filter", "Enter a name for this filter:")
        if not filter_name:
            return
        filter_path = os.path.join(FILTERS_FOLDER, f"{filter_name}.json")
        try:
            utils._atomic_json_write(filter_path, {"name": filter_name, "filter": f}, indent=4)
            messagebox.showinfo("Success", f"Filter '{filter_name}' saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save filter: {e}")

    button_frame = tk.Frame(popup, bg="black")
    button_frame.pack(fill="x", pady=10)
    tk.Button(button_frame, text="APPLY FILTER TO PLAYLIST", bg="black", fg="white", command=apply_filter).pack(side="left", padx=10)
    tk.Button(button_frame, text="CLEAR ALL FILTERS", bg="black", fg="white", command=reset_filter).pack(side="left", padx=10)
    tk.Button(button_frame, text="SAVE FILTER", bg="black", fg="white", command=save_filter_action).pack(side="right", padx=10)


def get_all_seasons(playlis):
    seasons = set()
    for file in playlis:
        data = metadata_fetch.get_metadata(file)
        if data:
            season = data.get("season")
            if season:
                seasons.add(season)

    def season_key(season_str):
        try:
            part, year = season_str.split()
            season_order = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
            return (int(year), season_order.get(part, 99))
        except Exception:
            return (9999, 99)

    return sorted(seasons, key=season_key)


def get_all_filters():
    """Returns all saved filters as a dictionary."""
    filters_dict = {}
    if not os.path.exists(FILTERS_FOLDER):
        os.makedirs(FILTERS_FOLDER)
    for index, filename in enumerate(os.listdir(FILTERS_FOLDER)):
        if filename.endswith(".json"):
            filter_path = os.path.join(FILTERS_FOLDER, filename)
            try:
                with open(filter_path, "r") as file:
                    filters_dict[index] = json.load(file)
            except Exception as e:
                print(f"Failed to load {filename}: {e}")
    return filters_dict


def get_lowest_parameter(parameter, playlis=None):
    lowest = 10000000
    if not playlis:
        playlist = state.metadata.playlist
        if playlist.get("infinite", False):
            playlis = list(state.metadata.directory_files.keys())
        else:
            playlis = playlist["playlist"]
    for filename in playlis:
        data = metadata_fetch.get_metadata(filename)
        if data:
            item = data.get(parameter, lowest)
            if item and item < lowest:
                lowest = item
    return lowest


def get_highest_parameter(parameter, playlis=None):
    highest = 0
    if not playlis:
        playlist = state.metadata.playlist
        if playlist.get("infinite", False):
            playlis = list(state.metadata.directory_files.keys())
        else:
            playlis = playlist["playlist"]
    for filename in playlis:
        data = metadata_fetch.get_metadata(filename)
        if data:
            item = data.get(parameter, highest)
            if item and item > highest:
                highest = item
    return highest


def get_all_artists(playlis):
    artists = set()
    for filename in playlis:
        data = metadata_fetch.get_metadata(filename)
        if data:
            for song in data.get('songs', []):
                for artist in song.get("artist", []):
                    artists.add(artist)
    return sorted(artists, key=str.lower)


def get_all_tags(playlis=None, game=True, double=False):
    tags = []

    def add_tag(anime):
        if game or not metadata_display.is_game(anime):
            for tag in information_popup.get_tags(anime):
                if double or tag not in tags:
                    tags.append(tag)

    if playlis:
        for f in playlis:
            data = metadata_fetch.get_metadata(f)
            if data:
                add_tag(data)
    else:
        for anime in state.metadata.anime_metadata.values():
            add_tag(anime)
    return sorted(tags)


def get_all_studios(playlis, games=True, repeats=False):
    studios = []
    for filename in playlis:
        data = metadata_fetch.get_metadata(filename)
        if data and (games or not metadata_display.is_game(data)):
            for studio in data.get('studios', []):
                if studio not in studios or repeats:
                    studios.append(studio)
    return sorted(studios)


def get_saved_filter(name):
    """Return a named saved filter definition, or ``None`` when not found."""
    target = str(name or "").strip()
    for data in get_all_filters().values():
        if data.get("name") == target:
            try:
                return normalize_filter(data.get("filter") or {})
            except FilterValidationError:
                return None
    return None


def save_filter_definition(name, filters, *, overwrite=False):
    """Validate and save a web-created filter using a safe filename."""
    name = str(name or "").strip()
    errors = []
    if not name:
        errors.append("A filter name is required")
    if len(name) > 80:
        errors.append("Filter names must be 80 characters or fewer")
    if name in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        errors.append("The filter name contains characters Windows cannot use")
    if name.endswith("."):
        errors.append("Filter names cannot end with a period")
    stem = name.rstrip(" .").split(".", 1)[0].upper()
    if stem in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        errors.append("That filter name is reserved by Windows")
    if errors:
        raise FilterValidationError(errors)

    normalized = normalize_filter(filters, strict=True)
    os.makedirs(FILTERS_FOLDER, exist_ok=True)
    existing_path = None
    for filename in os.listdir(FILTERS_FOLDER):
        if filename.lower() == f"{name}.json".lower():
            existing_path = os.path.join(FILTERS_FOLDER, filename)
            break
    if existing_path and not overwrite:
        raise FileExistsError(name)
    path = existing_path or os.path.join(FILTERS_FOLDER, f"{name}.json")
    utils._atomic_json_write(path, {"name": name, "filter": normalized}, indent=4)
    return normalized


def _editor_source_and_filter():
    """Return a stable editor source and the last web-applied draft."""
    global _editor_regular_source, _editor_regular_name
    global _editor_regular_result_revision, _editor_regular_filter

    playlist = state.metadata.playlist
    if playlist.get("infinite"):
        return get_filter_source(), normalize_filter(playlist.get("filter") or {})

    live = list(playlist.get("playlist", []))
    live_revision = _playlist_revision(live)
    name = playlist.get("name", "")
    if (
        _editor_regular_source is not None
        and _editor_regular_name == name
        and _editor_regular_result_revision == live_revision
    ):
        return list(_editor_regular_source), copy.deepcopy(_editor_regular_filter)

    _editor_regular_source = list(live)
    _editor_regular_name = name
    _editor_regular_result_revision = live_revision
    _editor_regular_filter = {}
    return list(live), {}


def get_filter_editor_context(saved_name=None):
    """Build the host web editor's filter, option lists, and source token."""
    source, current_filter = _editor_source_and_filter()
    selected_name = str(saved_name or "").strip()
    if selected_name:
        selected_filter = get_saved_filter(selected_name)
        if selected_filter is None:
            raise FilterValidationError(["The selected saved filter no longer exists"])
        current_filter = selected_filter

    aggregate = _aggregate_filter_metadata(source)

    saved_filters = sorted(
        (data.get("name") for data in get_all_filters().values() if data.get("name")),
        key=str.lower,
    )
    playlists = sorted(set(playlist_ops.get_playlists_dict().values()), key=str.lower)
    return {
        "filter": current_filter,
        "selected_name": selected_name,
        "is_infinite": bool(state.metadata.playlist.get("infinite")),
        "playlist_name": state.metadata.playlist.get("name") or "Playlist",
        "source_total": len(source),
        "source_revision": _playlist_revision(source),
        "live_revision": _playlist_revision(),
        "saved_filters": saved_filters,
        "options": {
            "playlists": playlists,
            "seasons": aggregate["seasons"],
            "artists": aggregate["artists"],
            "studios": aggregate["studios"],
            "tags": aggregate["tags"],
            "theme_rules": list(THEME_FILTER_OPTIONS),
        },
        "ranges": aggregate["ranges"],
    }


def preview_filter_definition(filters, *, source_revision=None):
    """Evaluate a browser draft against the editor's stable source."""
    source, _ = _editor_source_and_filter()
    current_source_revision = _playlist_revision(source)
    if source_revision and source_revision != current_source_revision:
        return {"ok": False, "stale": True, "errors": ["The filter source changed; reopen the editor"]}
    try:
        normalized = normalize_filter(filters, strict=True)
    except FilterValidationError as exc:
        return {"ok": False, "errors": exc.errors}
    try:
        matched = evaluate_filter(normalized, source)
    except Exception as exc:
        print(f"Unable to preview playlist filter: {exc}")
        return {"ok": False, "errors": ["Unable to evaluate this filter"]}
    return {
        "ok": True,
        "filter": normalized,
        "matched": len(matched),
        "total": len(source),
        "source_revision": current_source_revision,
    }


def apply_saved_filter_from_web(name):
    """Apply a saved filter through the web editor's reversible source."""
    saved_filter = get_saved_filter(name)
    if saved_filter is None:
        return {"ok": False, "errors": ["The selected saved filter no longer exists"]}
    source, _ = _editor_source_and_filter()
    return apply_filter_definition(
        saved_filter,
        source_revision=_playlist_revision(source),
        live_revision=_playlist_revision(),
    )


def apply_filter_definition(filters, *, source_revision=None, live_revision=None):
    """Apply an explicit web-editor draft, preserving the current item."""
    global _editor_regular_result_revision, _editor_regular_filter

    source, _ = _editor_source_and_filter()
    if source_revision and source_revision != _playlist_revision(source):
        return {"ok": False, "stale": True, "errors": ["The filter source changed; reopen the editor"]}
    if live_revision and live_revision != _playlist_revision():
        return {"ok": False, "stale": True, "errors": ["The playlist changed while this filter was open"]}
    try:
        normalized = normalize_filter(filters, strict=True)
    except FilterValidationError as exc:
        return {"ok": False, "errors": exc.errors}

    playlist = state.metadata.playlist
    if playlist.get("infinite"):
        old_filter = copy.deepcopy(playlist.get("filter") or {})
        playlist["filter"] = copy.deepcopy(normalized)
        print("Applied Filters:", normalized)
        try:
            infinite.refresh_pop_time_groups()
        except Exception as exc:
            playlist["filter"] = old_filter
            print(f"Unable to apply infinite playlist filter: {exc}")
            return {"ok": False, "errors": ["Unable to apply this filter"]}
        config_io.save_config()
        return {
            "ok": True,
            "filter": normalized,
            "matched": infinite.total_infinite_files,
            "total": len(source),
            "source_revision": _playlist_revision(source),
            "live_revision": _playlist_revision(),
        }

    live = list(playlist.get("playlist", []))
    old_index = playlist.get("current_index", -1)
    current_file = live[old_index] if 0 <= old_index < len(live) else None
    try:
        filtered = evaluate_filter(normalized, source)
    except Exception as exc:
        print(f"Unable to apply playlist filter: {exc}")
        return {"ok": False, "errors": ["Unable to apply this filter"]}
    playlist["playlist"] = filtered
    if current_file in filtered:
        new_index = filtered.index(current_file)
    else:
        new_index = 0 if filtered else -1
    print("Applied Filters:", normalized)
    lists.show_playlist(True)
    transport.update_current_index(new_index)
    _editor_regular_filter = copy.deepcopy(normalized)
    _editor_regular_result_revision = _playlist_revision(filtered)
    return {
        "ok": True,
        "filter": normalized,
        "matched": len(filtered),
        "total": len(source),
        "current_index": new_index,
        "source_revision": _playlist_revision(source),
        "live_revision": _editor_regular_result_revision,
    }


def get_filter_source():
    """Return the current unmodified source used by playlist filtering."""
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        inf_settings = infinite.get_infinite_settings()
        return playlist_ops.get_directory_files(
            include_non_local=inf_settings.get("include_non_local_files", False),
            deduplicate_files=False,
            deduplicate_versions=False,
        )
    return list(playlist.get("playlist", []))


def evaluate_filter(filters, playlis=None):
    """Evaluate a filter without changing the live playlist or its index."""
    filters = normalize_filter(filters)
    playlis = list(get_filter_source() if playlis is None else playlis)

    filtered = []

    has_playlist_filter = "playlist_filter" in filters
    has_playlist_filter_and = "playlist_filter_and" in filters
    has_playlist_filter_exclude = "playlist_filter_exclude" in filters
    has_keywords = "keywords" in filters
    # Theme-type filtering is always active. Historically an absent value (or
    # the legacy value "Both") meant openings and endings; keep that behavior
    # while making inserts explicitly opt-in.
    filter_theme_type = filters.get("theme_type", DEFAULT_THEME_TYPE)
    has_theme_type = filter_theme_type != "All"
    has_score_min = "score_min" in filters
    has_score_max = "score_max" in filters
    has_rank_min = "rank_min" in filters
    has_rank_max = "rank_max" in filters
    has_members_min = "members_min" in filters
    has_members_max = "members_max" in filters
    has_popularity_min = "popularity_min" in filters
    has_popularity_max = "popularity_max" in filters
    has_season_min = "season_min" in filters
    has_season_max = "season_max" in filters
    has_themes_exclude = "themes_exclude" in filters
    has_themes_include = "themes_include" in filters
    has_themes_filtering = has_themes_exclude or has_themes_include
    has_artists = "artists" in filters
    has_studios = "studios" in filters
    has_tags_include = "tags_include" in filters
    has_tags_include_and = "tags_include_and" in filters
    has_tags_exclude = "tags_exclude" in filters

    filter_score_min = filters.get("score_min")
    filter_score_max = filters.get("score_max")
    filter_rank_min = filters.get("rank_min")
    filter_rank_max = filters.get("rank_max")
    filter_members_min = filters.get("members_min")
    filter_members_max = filters.get("members_max")
    filter_popularity_min = filters.get("popularity_min")
    filter_popularity_max = filters.get("popularity_max")
    filter_season_min_tuple = utils._season_to_tuple(filters["season_min"]) if has_season_min else None
    filter_season_max_tuple = utils._season_to_tuple(filters["season_max"]) if has_season_max else None

    if has_keywords:
        keyword_list = [kw.strip().lower() for kw in filters["keywords"].split(",") if kw.strip()]
    else:
        keyword_list = []

    filter_artists_set = set(filters["artists"]) if has_artists else None
    filter_studios_set = set(filters["studios"]) if has_studios else None
    filter_tags_include_set = set(filters["tags_include"]) if has_tags_include else None
    filter_tags_include_and_set = set(filters["tags_include_and"]) if has_tags_include_and else None
    filter_tags_exclude_set = set(filters["tags_exclude"]) if has_tags_exclude else None

    if has_themes_filtering:
        themes_exclude_set = set(filters.get("themes_exclude", []))
        themes_include_set = set(filters.get("themes_include", []))
        all_theme_filter_flags = themes_exclude_set | themes_include_set
        needs_nsfw_check = "NSFW (With Censors)" in all_theme_filter_flags or "NSFW (Without Censors)" in all_theme_filter_flags
        needs_anisongdb_risk_check = (
            ANISONGDB_RISK_WITH_CENSORS in all_theme_filter_flags
            or ANISONGDB_RISK_WITHOUT_CENSORS in all_theme_filter_flags
        )
        needs_overlap_check = "OVERLAP (With Censors)" in all_theme_filter_flags or "OVERLAP (Without Censors)" in all_theme_filter_flags
        needs_spoiler_check = "SPOILER (With Censors)" in all_theme_filter_flags or "SPOILER (Without Censors)" in all_theme_filter_flags
        needs_transition_check = "TRANSITION (With Censors)" in all_theme_filter_flags or "TRANSITION (Without Censors)" in all_theme_filter_flags
        needs_movie_ed_check = "MOVIE EDs (With Censors)" in all_theme_filter_flags or "MOVIE EDs (Without Censors)" in all_theme_filter_flags
        needs_duplicates = "DUPLICATES" in all_theme_filter_flags
        needs_versions = "LATER VERSIONS" in all_theme_filter_flags
        exclude_duplicates = has_themes_exclude and "DUPLICATES" in themes_exclude_set
        include_duplicates = has_themes_include and "DUPLICATES" in themes_include_set
        exclude_versions = has_themes_exclude and "LATER VERSIONS" in themes_exclude_set
        include_versions = has_themes_include and "LATER VERSIONS" in themes_include_set
    else:
        needs_duplicates = False
        needs_versions = False

    def _load_playlist_files(names):
        result = set()
        for name in (names if isinstance(names, list) else [names]):
            if not isinstance(name, str) or name != os.path.basename(name) or "/" in name or "\\" in name:
                continue
            path = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        result.update(json.load(f).get("playlist", []))
                except (OSError, json.JSONDecodeError, AttributeError):
                    continue
        return result

    playlist_filter_files = _load_playlist_files(filters["playlist_filter"]) if has_playlist_filter else set()
    playlist_filter_and_sets = []
    if has_playlist_filter_and:
        for name in filters["playlist_filter_and"]:
            playlist_filter_and_sets.append(_load_playlist_files([name]))
    playlist_filter_exclude_files = _load_playlist_files(filters["playlist_filter_exclude"]) if has_playlist_filter_exclude else set()

    if needs_duplicates:
        build_best_duplicate_map(playlis)
    if needs_versions:
        build_version_index(playlis)

    for filename in playlis:
        if has_playlist_filter and filename not in playlist_filter_files:
            continue
        if has_playlist_filter_and and not all(filename in s for s in playlist_filter_and_sets):
            continue
        if has_playlist_filter_exclude and filename in playlist_filter_exclude_files:
            continue

        data = metadata_fetch.get_metadata(filename)
        if not data:
            continue

        if has_score_min or has_score_max:
            score = float(data.get("score") or 0)
            if has_score_min and score < filter_score_min:
                continue
            if has_score_max and score > filter_score_max:
                continue

        if has_rank_min or has_rank_max:
            try:
                rank = int(data.get("rank") or 100000)
            except (TypeError, ValueError):
                rank = 100000
            if has_rank_min and rank > filter_rank_min:
                continue
            if has_rank_max and rank < filter_rank_max:
                continue

        if has_members_min or has_members_max:
            members = int(data.get("members") or 0)
            if has_members_max and members > filter_members_max:
                continue
            if has_members_min and members < filter_members_min:
                continue

        if has_popularity_min or has_popularity_max:
            try:
                popularity = int(data.get("popularity") or INT_INF)
            except (TypeError, ValueError, OverflowError):
                popularity = INT_INF
            if has_popularity_min and popularity > filter_popularity_min:
                continue
            if has_popularity_max and popularity < filter_popularity_max:
                continue

        if has_season_min or has_season_max:
            season_tuple = utils._season_to_tuple(data.get("season", ""))
            if has_season_min and season_tuple < filter_season_min_tuple:
                continue
            if has_season_max and season_tuple > filter_season_max_tuple:
                continue

        if has_keywords:
            title = (data.get("title") or "").lower()
            eng_title = (data.get("eng_title", "") or "").lower()
            filename_lower = filename.lower()
            if not any(kw in filename_lower or kw in title or kw in eng_title for kw in keyword_list):
                continue

        if has_theme_type:
            slug = str(data.get("slug") or "").upper()
            if slug.startswith("OP"):
                theme_type = "Opening"
            elif slug.startswith("ED"):
                theme_type = "Ending"
            elif slug.startswith("IN"):
                theme_type = "Insert"
            else:
                theme_type = "Other"
            if filter_theme_type == DEFAULT_THEME_TYPE:
                if theme_type not in {"Opening", "Ending"}:
                    continue
            elif filter_theme_type != theme_type:
                continue

        if has_tags_include or has_tags_include_and or has_tags_exclude:
            tags = set(information_popup.get_tags(data))
            if has_tags_include and tags.isdisjoint(filter_tags_include_set):
                continue
            if has_tags_include_and and not filter_tags_include_and_set.issubset(tags):
                continue
            if has_tags_exclude and not tags.isdisjoint(filter_tags_exclude_set):
                continue

        if has_artists or has_studios:
            if has_artists:
                slug = data.get("slug", "")
                theme = utils.get_song_by_slug(data, slug) or {}
                artists = theme.get("artist", [])
                if filter_artists_set.isdisjoint(artists):
                    continue
            if has_studios:
                studios = data.get("studios", [])
                if filter_studios_set.isdisjoint(studios):
                    continue

        if has_themes_filtering:
            theme_flags = set()
            slug = data.get("slug", "")
            theme = utils.get_song_by_slug(data, slug)
            if theme:
                file_version = extract_version(filename)
                current_version_data = None
                has_censors = None
                versions = theme.get("versions")
                if versions:
                    for version_data in versions:
                        if version_data.get("version") == file_version:
                            current_version_data = version_data
                            break
                source = current_version_data if current_version_data else theme
                overlap = source.get("overlap")
                if needs_overlap_check and overlap == "Over":
                    if has_censors is None:
                        has_censors = bool(censors.get_file_censors(filename))
                    theme_flags.add("OVERLAP (With Censors)" if has_censors else "OVERLAP (Without Censors)")
                elif needs_transition_check and overlap == "Transition":
                    if has_censors is None:
                        has_censors = bool(censors.get_file_censors(filename))
                    theme_flags.add("TRANSITION (With Censors)" if has_censors else "TRANSITION (Without Censors)")
                if needs_spoiler_check and source.get("spoiler"):
                    if has_censors is None:
                        has_censors = bool(censors.get_file_censors(filename))
                    theme_flags.add("SPOILER (With Censors)" if has_censors else "SPOILER (Without Censors)")
                if needs_nsfw_check and source.get("nsfw"):
                    if has_censors is None:
                        has_censors = bool(censors.get_file_censors(filename))
                    theme_flags.add("NSFW (With Censors)" if has_censors else "NSFW (Without Censors)")
                if needs_movie_ed_check and information_popup.get_format(data) == "Movie" and "ED" in slug:
                    if has_censors is None:
                        has_censors = bool(censors.get_file_censors(filename))
                    theme_flags.add("MOVIE EDs (With Censors)" if has_censors else "MOVIE EDs (Without Censors)")

            if needs_anisongdb_risk_check:
                file_properties = data.get("file_properties") or {}
                is_anisongdb_video = (
                    str(file_properties.get("source") or "").upper() == "ANISONGDB"
                )
                anisongdb_risk_labels = set()
                for field in ("anisongdb_genres", "anisongdb_tags", "genres"):
                    values = data.get(field) or []
                    if isinstance(values, str):
                        values = [values]
                    anisongdb_risk_labels.update(
                        str(value).casefold() for value in values
                    )
                has_anisongdb_risk = bool(
                    {"ecchi", "nudity", "hentai"} & anisongdb_risk_labels
                )
                if is_anisongdb_video and has_anisongdb_risk:
                    if has_censors is None:
                        has_censors = bool(censors.get_file_censors(filename))
                    theme_flags.add(
                        ANISONGDB_RISK_WITH_CENSORS
                        if has_censors
                        else ANISONGDB_RISK_WITHOUT_CENSORS
                    )

            if has_themes_exclude and not theme_flags.isdisjoint(themes_exclude_set):
                continue
            if has_themes_include and theme_flags.isdisjoint(themes_include_set):
                continue
            if (exclude_duplicates and not check_best_duplicate_theme(filename, data)) or (include_duplicates and check_best_duplicate_theme(filename, data)):
                continue
            if (exclude_versions and not check_lowest_version(filename, data)) or (include_versions and check_lowest_version(filename, data)):
                continue

        filtered.append(filename)

    return filtered


def filter_playlist(filters, notify=True):
    """Apply a filter to a standard playlist, or evaluate an infinite one.

    This keeps the long-standing public behavior for desktop and infinite
    playlist callers. New preview code must call :func:`evaluate_filter`.
    """
    playlist = state.metadata.playlist
    normalized = normalize_filter(filters)
    filtered = evaluate_filter(normalized)
    if not playlist.get("infinite"):
        playlist["playlist"] = filtered
        print("Applied Filters:", normalized)
        lists.show_playlist(True)
        transport.update_current_index(0 if filtered else -1)
        if notify:
            messagebox.showinfo("Playlist Filtered", f"Playlist filtered to {len(filtered)} videos.")
    return filtered


_best_duplicate_map = {}


def build_best_duplicate_map(playlis):
    global _best_duplicate_map
    _best_duplicate_map = {}
    directory_files = state.metadata.directory_files
    for file in playlis:
        file_path = directory_files.get(file)
        if not file_path:
            continue
        data = metadata_fetch.get_metadata(file)
        if not data:
            continue
        key = (data.get("mal"), data.get("slug"), extract_version(file))
        try:
            file_size = os.path.getsize(file_path)
        except Exception:
            continue
        if key not in _best_duplicate_map or file_size > _best_duplicate_map[key][1]:
            _best_duplicate_map[key] = (file, file_size)


def check_best_duplicate_theme(filename, data):
    key = (data.get("mal"), data.get("slug"), extract_version(filename))
    best_file, _ = _best_duplicate_map.get(key, (filename, None))
    return filename == best_file


def extract_version(filename):
    version_str = metadata_fetch.get_version_from_filename(filename)
    if version_str:
        try:
            return int(version_str)
        except (ValueError, TypeError):
            pass
    match = re.search(r'v(\d+)', filename)
    if match:
        return int(match.group(1))
    return 1


_lowest_version_map = {}


def build_version_index(playlis):
    global _lowest_version_map
    _lowest_version_map = {}
    for file in playlis:
        data = metadata_fetch.get_metadata(file)
        if not data:
            continue
        mal = data.get("mal")
        slug = data.get("slug")
        ver = extract_version(file)
        key = (mal, slug)
        if not mal or not slug:
            continue
        if key not in _lowest_version_map or ver < _lowest_version_map[key][0]:
            _lowest_version_map[key] = (ver, file)


def check_lowest_version(filename, data):
    key = (data.get("mal"), data.get("slug"))
    ver = extract_version(filename)
    if key not in _lowest_version_map:
        return True
    lowest_ver, _ = _lowest_version_map[key]
    return ver <= lowest_ver
