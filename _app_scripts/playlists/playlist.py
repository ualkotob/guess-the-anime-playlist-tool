# _app_scripts/playlist_ops.py
# Extracted playlist operations from guess_the_anime.py
import copy
import json
import os
import random
import threading
from collections import Counter

from tkinter import messagebox

from _app_scripts import utils
from core.game_state import state
from core.event_bus import events
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.transport as transport
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.theme.marks as playlist_marks
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.data.config_io as config_io
import _app_scripts.playlists.playlist_io as playlist_io
import _app_scripts.playlists.infinite as infinite
import _app_scripts.playlists.filters as playlist_filters
import _app_scripts.ui.lists as lists
from core.paths import PLAYLISTS_FOLDER
from _app_scripts.theme.marks import SYSTEM_PLAYLISTS

# Collaborators (read directly off state / sibling modules).
# Metadata-cluster dicts (playlist, directory_files, file_metadata, anime_metadata)
# are read directly from `state.metadata.*`; widgets from `state.widgets.*`.
# check_theme_cache is read directly from state.playback.check_theme_cache
# popout_buttons_by_name is read directly from state.playback.popout_buttons_by_name
# All former sibling-callback getters are inlined to their owning modules
# (metadata_fetch / metadata_display / information_popup / censors / lists /
# playlist_marks / cache_download / config_io / metadata_io / session_stats /
# variety_round / lightning_manager / metadata_panel / popout_window / entry_paths).
# The playback-hub fns (update_current_index / update_playlist_name / stop) are
# reached on the transport sibling directly.
# Canonical empty-playlist template. Owned here; callers (config_io, main)
# read it directly as `playlist_ops.BLANK_PLAYLIST`. Copy with
# copy.deepcopy() before mutating.
BLANK_PLAYLIST = {
    "name": "",
    "current_index": -1,
    "lightning_history": {},
    "background_track_history": [],
    "infinite": False,
    "difficulty": 2,
    "order": 0,
    "pop_time_order": [],
    "playlist": [],
}
BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
playlist_changed = False

cached_deduplicated_files = None
cached_deduplicated_files_timestamp = 0
series_totals = None

SORTING_TYPES = [
    {"sort": "filename", "order": "asc"}, {"sort": "filename", "order": "desc"},
    {"sort": "title", "order": "asc"}, {"sort": "title", "order": "desc"},
    {"sort": "eng_title", "order": "asc"}, {"sort": "eng_title", "order": "desc"},
    {"sort": "score", "order": "asc"}, {"sort": "score", "order": "desc"},
    {"sort": "members", "order": "asc"}, {"sort": "members", "order": "desc"},
    {"sort": "season", "order": "asc"}, {"sort": "season", "order": "desc"},
]



def _notify_playlist_list_updated():
    """Announce a live-playlist mutation. The right-column list view refreshes
    via its core.event_bus subscription (lists._on_playlist_changed), keeping
    this logic module from driving the list UI directly."""
    events.publish("playlist_changed")


# ===========================================================================
#  CREATE PLAYLIST
# ===========================================================================

def generate_playlist(include_non_local=False):
    """Function to generate a playlist"""
    global playlist_changed
    playlist_changed = True
    playlis = []
    for file in get_directory_files(include_non_local=include_non_local):
        playlis.append(file)
    return playlis


def check_missing_artists():
    """Build the 'Missing Artists' system playlist: themes whose own song entry
    has an empty artist list."""
    playlist = state.metadata.playlist
    playlist["name"] = "Missing Artists"

    def remove_previous_playlist():
        try:
            os.remove(os.path.join(PLAYLISTS_FOLDER, f"{playlist['name']}.json"))
        except Exception as e:
            print(e)

    missing_artists = []
    previous_removed = False
    for filename in state.metadata.directory_files:
        data = metadata_fetch.get_metadata(filename)
        for theme in data.get("songs", []):
            if theme.get("slug") == data.get("slug") and theme.get("artist") == []:
                if not previous_removed:
                    remove_previous_playlist()
                    previous_removed = True
                playlist_marks.toggle_theme(playlist["name"], filename)
                missing_artists.append(filename)
    playlist["playlist"] = missing_artists
    transport.update_current_index(0)


def empty_playlist():
    playlist = state.metadata.playlist
    confirm = messagebox.askyesno("Clear Playlist", "Are you sure you want to create an empty playlist?")
    if not confirm:
        return
    new_playlist([], name=playlist.get("name"))
    state.metadata.playlist.clear()
    state.metadata.playlist.update(copy.deepcopy(BLANK_PLAYLIST))


def generate_playlist_button(include_non_local=None):
    if include_non_local is None:
        include_non_local = messagebox.askyesno(
            "Create Playlist: Include non-local files",
            "Would you like to include non-local files from metadata(they will stream)?",
        )
    extra_locations = " and metadata" if include_non_local else ""
    confirm = messagebox.askyesno(
        "Create Playlist",
        f"Are you sure you want to create a new playlist with all "
        f"{len(get_directory_files(include_non_local=include_non_local))} files in "
        f"directory{extra_locations}?",
    )
    if not confirm:
        return
    new_playlist(generate_playlist(include_non_local=include_non_local))
    if not state.metadata.playlist["playlist"]:
        messagebox.showwarning("Playlist Error", "No video files found in the directory.")


def _playlist_has_unsaved_changes():
    """Return True if the current playlist has unsaved changes, without showing any dialog."""
    playlist = state.metadata.playlist
    if not playlist.get("name"):
        return len(playlist.get("playlist", [])) > 15
    if playlist.get("name") in SYSTEM_PLAYLISTS:
        return False
    playlist_name = playlist["name"]
    saved_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")
    if not os.path.exists(saved_path):
        return True
    try:
        with open(saved_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        saved = utils.convert_infinity_markers(saved)
        current_data = {
            "playlist": playlist["playlist"],
            "infinite": playlist.get("infinite", False),
            "difficulty": playlist.get("difficulty", 2),
            "order": playlist.get("order", 0),
            "filter": playlist.get("filter", {}),
        }
        saved_data = {
            "playlist": saved.get("playlist", []),
            "infinite": saved.get("infinite", False),
            "difficulty": saved.get("difficulty", 2),
            "order": saved.get("order", 0),
            "filter": saved.get("filter", {}),
        }
        return current_data != saved_data
    except Exception:
        return True


def confirm_save_playlist(text=""):
    playlist = state.metadata.playlist
    if not playlist.get("name"):
        if len(playlist.get("playlist", [])) > 15:
            confirm = messagebox.askyesno("Save Playlist",
                                          f"Do you want to save your current playlist before {text}?")
            if confirm:
                playlist_io.save_as()
        return
    elif playlist.get("name") in SYSTEM_PLAYLISTS:
        return

    playlist_name = playlist["name"]
    saved_playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")

    if not os.path.exists(saved_playlist_path):
        confirm = messagebox.askyesno("Save Playlist",
                                      f"Do you want to save your current playlist before {text}?")
        if confirm:
            playlist_io.save()
        return

    try:
        with open(saved_playlist_path, "r", encoding="utf-8") as f:
            saved_playlist = json.load(f)

        saved_playlist = utils.convert_infinity_markers(saved_playlist)

        current_playlist_data = {
            "playlist": playlist["playlist"],
            "infinite": playlist.get("infinite", False),
            "difficulty": playlist.get("difficulty", 2),
            "order": playlist.get("order", 0),
            "filter": playlist.get("filter", {}),
        }

        saved_playlist_data = {
            "playlist": saved_playlist.get("playlist", []),
            "infinite": saved_playlist.get("infinite", False),
            "difficulty": saved_playlist.get("difficulty", 2),
            "order": saved_playlist.get("order", 0),
            "filter": saved_playlist.get("filter", {}),
        }

        if current_playlist_data != saved_playlist_data:
            confirm = messagebox.askyesno(
                "Save Playlist",
                f"Playlist '{playlist_name}' has unsaved changes. "
                f"Do you want to save before {text}?",
            )
            if confirm:
                playlist_io.save()
    except Exception as e:
        print(f"Error comparing playlists: {e}")
        confirm = messagebox.askyesno("Save Playlist",
                                      f"Do you want to save your current playlist before {text}?")
        if confirm:
            playlist_io.save()


def new_playlist(playlis, name=None):
    global playlist_changed
    confirm_save_playlist("creating a new playlist")
    state.metadata.playlist.clear()
    state.metadata.playlist.update(copy.deepcopy(BLANK_PLAYLIST))
    playlist = state.metadata.playlist
    metadata_display.up_next_text()
    transport.update_playlist_name(name=name)
    playlist["playlist"] = playlis
    transport.update_current_index(0)
    transport.update_playlist_name()
    config_io.save_config()
    playlist_changed = True

    if playlis and len(playlis) > 0:
        first_entry = playlis[0]
        first_filename = entry_paths.get_clean_filename(first_entry)
        directory_files = state.metadata.directory_files
        if cache_download.is_animethemes_stream_file(first_filename) and first_filename not in directory_files:
            threading.Thread(
                target=lambda: cache_download.download_to_cache(first_filename, silent=False),
                daemon=True,
            ).start()


def create_infinite_playlist(include_non_local=None):
    confirm = messagebox.askyesno("Create Infinite Playlist",
                                  "Are you sure you want to create a new infinite playlist?")
    if not confirm:
        return
    new_playlist([])
    playlist = state.metadata.playlist
    playlist["infinite"] = True
    playlist["infinite_settings"] = copy.deepcopy(infinite.infinite_settings)
    playlist["infinite_settings"]["include_non_local_files"] = (
        include_non_local if include_non_local is not None else False
    )
    playlist["filter"] = copy.deepcopy(playlist_filters.DEFAULT_INFINITE_FILTER)

    infinite.get_pop_time_groups(refetch=True)
    infinite.get_next_infinite_track()
    def _init_tail():
        infinite.fill_speculative_tail()
        cache_download.prefetch_next_themes()
    state.widgets.root.after(200, _init_tail)
    transport.update_playlist_name("")
    config_io.save_config()

    if playlist["playlist"] and len(playlist["playlist"]) > 0:
        first_entry = playlist["playlist"][0]
        first_filename = entry_paths.get_clean_filename(first_entry)
        directory_files = state.metadata.directory_files
        if cache_download.is_animethemes_stream_file(first_filename) and first_filename not in directory_files:
            threading.Thread(
                target=lambda: cache_download.download_to_cache(first_filename, silent=False),
                daemon=True,
            ).start()

# ===========================================================================
#  SHUFFLE PLAYLIST
# ===========================================================================

def randomize_playlist():
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        return
    name = playlist.get("name", "")
    confirm = messagebox.askyesno("Shuffle Playlist",
                                   f"Are you sure you want to shuffle '{name}'?")
    if not confirm:
        return
    random.shuffle(playlist["playlist"])
    transport.update_current_index(0)


def weighted_randomize():
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        return
    name = playlist.get("name", "")
    confirm = messagebox.askyesno("Weighted Shuffle Playlist",
                                   f"Are you sure you want to weighted shuffle '{name}'?")
    if not confirm:
        return
    playlist["playlist"] = weighted_shuffle(playlist["playlist"])
    transport.update_current_index(0)


def weighted_shuffle(playlis):
    """Performs a weighted shuffle of the playlist, balancing popularity and season."""
    if not playlis:
        return playlis

    sorted_playlist = sorted(playlis, key=lambda x: metadata_fetch.get_metadata(x).get("members", 0) or 0, reverse=True)
    group_size = len(sorted_playlist) // 3

    popular = sorted_playlist[:group_size]
    mid = sorted_playlist[group_size:group_size * 2]
    niche = sorted_playlist[group_size * 2:]

    def sort_by_year(entries):
        return sorted(entries, key=lambda x: int(metadata_fetch.get_metadata(x).get("season", "9999")[-4:]))

    popular_sorted = sort_by_year(popular)
    mid_sorted = sort_by_year(mid)
    niche_sorted = sort_by_year(niche)

    popular_time_splits = split_into_three(popular_sorted)
    mid_time_splits = split_into_three(mid_sorted)
    niche_time_splits = split_into_three(niche_sorted)

    filename_group = {}
    grp1 = 0
    grp2 = 0
    for group in [popular_time_splits, mid_time_splits, niche_time_splits]:
        for sublist in group:
            random.shuffle(sublist)
            for filename in sublist:
                filename_group[filename] = str(grp1) + str(grp2)
            grp2 += 1
        grp1 += 1
        grp2 = 0

    shuffled_playlist = []
    groups = [popular_time_splits, mid_time_splits, niche_time_splits]

    while any(any(group) for group in groups):
        pop_time_order = get_pop_time_order()
        for o in range(9):
            t = pop_time_order[o][0]
            p = pop_time_order[o][1]
            if p < len(groups) and t < len(groups[p]) and groups[p][t]:
                shuffled_playlist.append(groups[p][t].pop(0))
        groups = [group for group in groups if any(group)]

    final_playlist = shuffled_playlist[:]

    def find_suitable_swap(index):
        spacing = min_spacing
        for swap_index in range(index + spacing, len(final_playlist)):
            if filename_group[entry_paths.get_clean_filename(final_playlist[index])] == filename_group[entry_paths.get_clean_filename(final_playlist[swap_index])]:
                if is_safe_swap(index, swap_index):
                    return swap_index
        for swap_index in range(index - spacing, -1, -1):
            if filename_group[entry_paths.get_clean_filename(final_playlist[index])] == filename_group[entry_paths.get_clean_filename(final_playlist[swap_index])]:
                if is_safe_swap(index, swap_index):
                    return swap_index
        return None

    def is_safe_swap(i1, i2):
        def is_valid_placement(index, entry_data):
            for offset in range(1, min_spacing + 1):
                if index - offset >= 0:
                    if metadata_display.series_overlap(entry_data, metadata_fetch.get_metadata(final_playlist[index - offset])):
                        return False
                if index + offset < len(final_playlist):
                    if metadata_display.series_overlap(entry_data, metadata_fetch.get_metadata(final_playlist[index + offset])):
                        return False
            return True
        data1 = metadata_fetch.get_metadata(final_playlist[i1])
        data2 = metadata_fetch.get_metadata(final_playlist[i2])
        return is_valid_placement(i2, data1) and is_valid_placement(i1, data2)

    get_series_totals(check_all=False)
    swapped_entrys = 1
    skipped_entries = 0
    swap_pass = 0

    print("Weighted Shuffle - STARTING... (may take some time, 15 pass max)")
    while (swapped_entrys > 0 or skipped_entries > 0) and swap_pass < 15:
        swapped_entrys = 0
        skipped_entries = 0
        swap_pass += 1
        exausted_series = []

        for i in range(len(final_playlist)):
            print(
                f"Spacing Same Series Pass {swap_pass} - Checking entry {i + 1} / {len(final_playlist)} "
                f"({swapped_entrys} swapped / {skipped_entries} skipped)",
                end="\r",
            )
            _cur_data = metadata_fetch.get_metadata(entry_paths.get_clean_filename(final_playlist[i]))
            _cur_primary = metadata_display.series_primary(_cur_data)
            total_series = series_totals.get(_cur_primary, 0)
            if total_series > 1:
                if _cur_primary in exausted_series:
                    skipped_entries += 1
                else:
                    min_spacing = int(min(350, max(3, (len(final_playlist) // total_series))) * (0.9 ** swap_pass))
                    for j in range(1, min_spacing + 1):
                        if i + j < len(final_playlist):
                            _next_data = metadata_fetch.get_metadata(entry_paths.get_clean_filename(final_playlist[i + j]))
                            if metadata_display.series_overlap(_cur_data, _next_data):
                                swap_index = find_suitable_swap(i + j)
                                if swap_index:
                                    swapped_entrys += 1
                                    final_playlist[i + j], final_playlist[swap_index] = final_playlist[swap_index], final_playlist[i + j]
                                else:
                                    skipped_entries += 1
                                    exausted_series.append(_cur_primary)
        print("")

    print("Weighted Shuffle - COMPLETE!")
    return final_playlist


def split_into_three(entries):
    size = len(entries) // 3 or 1
    return [entries[:size], entries[size:size * 2], entries[size * 2:]]


def get_pop_time_order():
    all_pairs = [(p, t) for p in [0, 1, 2] for t in [0, 1, 2]]
    while True:
        random.shuffle(all_pairs)
        valid = True
        for i in range(0, 9, 3):
            block = all_pairs[i:i + 3]
            if sorted(p for p, _ in block) != [0, 1, 2]:
                valid = False
                break
            if sorted(t for _, t in block) != [0, 1, 2]:
                valid = False
                break
        if valid:
            return all_pairs


# ===========================================================================
#  DIRECTORY FILES / DEDUPLICATION
# ===========================================================================

def get_cached_deduplicated_files(include_non_local=True):
    global cached_deduplicated_files, cached_deduplicated_files_timestamp
    directory_files = state.metadata.directory_files
    current_timestamp = len(directory_files)
    if (cached_deduplicated_files is None or
            cached_deduplicated_files_timestamp != current_timestamp):
        cached_deduplicated_files = get_directory_files(
            include_non_local=include_non_local,
            deduplicate_versions=True,
        )
        cached_deduplicated_files_timestamp = current_timestamp
    return cached_deduplicated_files


def invalidate_deduplicated_cache():
    global cached_deduplicated_files, cached_deduplicated_files_timestamp
    cached_deduplicated_files = None
    cached_deduplicated_files_timestamp = 0


def deduplicate_theme_versions(filenames, keep_versions=False):
    """Deduplicate files by theme, keeping the best version or best file per version."""
    if not filenames:
        return []

    theme_groups = {}
    for filename in filenames:
        file_data = metadata_fetch.get_file_metadata_by_name(filename)
        if file_data:
            mal_id = file_data.get("mal")
            slug = file_data.get("slug")
            if mal_id and slug:
                if keep_versions:
                    version = file_data.get("version")
                    key = (mal_id, slug, version)
                else:
                    key = (mal_id, slug)
                if key not in theme_groups:
                    theme_groups[key] = []
                theme_groups[key].append(filename)
            else:
                theme_groups[filename] = [filename]
        else:
            theme_groups[filename] = [filename]

    deduplicated_set = set()
    for group_files in theme_groups.values():
        best_file = metadata_display.prioritize_theme_files(group_files)
        if best_file:
            deduplicated_set.add(best_file)

    result = []
    for filename in filenames:
        if filename in deduplicated_set and filename not in result:
            result.append(filename)

    return result


def get_directory_files(include_non_local=False, deduplicate_files=False, deduplicate_versions=False):
    """Get directory files with optional non-local and deduplication."""
    directory_files = state.metadata.directory_files
    filename_to_mal = metadata_fetch.filename_to_mal
    if include_non_local:
        non_local_files = []
        for f in filename_to_mal:
            if '.' not in f:
                continue
            if f in directory_files or not cache_download.is_animethemes_stream_file(f):
                continue
            non_local_files.append(f)
        all_files = list(directory_files.keys()) + non_local_files
    else:
        all_files = list(directory_files.keys())

    if deduplicate_versions:
        return deduplicate_theme_versions(all_files, keep_versions=False)
    elif deduplicate_files:
        return deduplicate_theme_versions(all_files, keep_versions=True)

    return all_files


def get_series_totals(refetch=True, check_all=True):
    global series_totals
    if check_all:
        check_list = get_cached_deduplicated_files()
    else:
        check_list = state.metadata.playlist["playlist"]
    if refetch or not series_totals:
        series_counter = Counter()
        for filename in check_list:
            data = metadata_fetch.get_metadata(filename)
            series = data.get("series") or data.get("title", "Unknown")
            if isinstance(series, list):
                for s in series:
                    series_counter[s] += 1
            else:
                series_counter[series] += 1
        series_totals = series_counter
    return series_totals


# ===========================================================================
#  SORTING PLAYLISTS
# ===========================================================================



def sort_playlist(index):
    """Sorts the playlist in-place based on metadata."""
    playlist = state.metadata.playlist
    key = SORTING_TYPES[index].get("sort")
    order = SORTING_TYPES[index].get("order")
    valid_keys = {"title", "eng_title", "season", "members", "score", "filename"}
    if key not in valid_keys:
        print(f"Invalid sorting key: {key}")
        return

    reverse = order.lower() == "desc"
    season_order = {"Winter": 1, "Spring": 2, "Summer": 3, "Fall": 4}

    def extract_season_data(filename):
        metadata = metadata_fetch.get_metadata(filename)
        season_str = metadata.get("season", "")
        if season_str:
            parts = season_str.split()
            if len(parts) == 2 and parts[0] in season_order:
                return (int(parts[1]), season_order[parts[0]])
        return (float("inf"), float("inf"))

    playlist["playlist"].sort(key=lambda filename: (
        extract_season_data(entry_paths.get_clean_filename(filename)) if key == "season" else
        float(metadata_fetch.get_metadata(entry_paths.get_clean_filename(filename)).get(key, 0) or 0) if key in {"members", "score"} else
        metadata_fetch.get_metadata(entry_paths.get_clean_filename(filename)).get(key, "").lower() if isinstance(metadata_fetch.get_metadata(entry_paths.get_clean_filename(filename)).get(key), str) else "",
        filename.lower()
    ), reverse=reverse)
    transport.update_current_index(0)
    lists.show_playlist()
    config_io.save_config()


def get_playlist_name(key, value):
    data = playlist_marks.get_playlist(value)
    if data.get("infinite"):
        return f"{value}[\u221e]"
    else:
        return f"{value}[{len(data.get('playlist', []))}]"


def get_playlists_dict(exclude_system=False, system_only=False):
    """Returns a dictionary of available playlists indexed numerically."""
    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)
    playlists = sorted(f for f in os.listdir(PLAYLISTS_FOLDER) if f.endswith(".json"))
    playlist_names = [os.path.splitext(p)[0] for p in playlists]
    if exclude_system:
        playlist_names = [name for name in playlist_names if name not in SYSTEM_PLAYLISTS]
    elif system_only:
        playlist_names = [name for name in playlist_names if name in SYSTEM_PLAYLISTS]
    return {i: name for i, name in enumerate(playlist_names)}
