# _app_scripts/playlist_ops.py
# Extracted playlist operations from guess_the_anime.py
import copy
import json
import os
import platform
import random
import re
import subprocess
import sys
import threading
from collections import Counter
from datetime import datetime

import requests
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk

from _app_scripts import utils
from core.game_state import state
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.transport as transport
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.playlists.marks as playlist_marks
import _app_scripts.information.information_popup as information_popup
import _app_scripts.toggles.censors as censors
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.file.metadata.metadata_panel as metadata_panel
import _app_scripts.file.session_stats as session_stats
import _app_scripts.queue_round.lightning_rounds.variety_round as variety_round
import _app_scripts.queue_round.lightning_rounds.lightning_manager as lightning_manager
import _app_scripts.data.config_io as config_io
import _app_scripts.data.metadata_io as metadata_io
import _app_scripts.ui.lists as lists
from core.paths import PLAYLISTS_FOLDER, FILTERS_FOLDER
from core.app_meta import APP_VERSION
from _app_scripts.playlists.marks import SYSTEM_PLAYLISTS

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

INFINITE_SETTINGS_DEFAULT = {
    "max_history_check": 10000,
    "difficulty_groups": {
        "easy": {"range": [1, 250], "cooldown": [0.5, 0.6], "file_boost_limit": 20},
        "medium": {"range": [251, 1000], "cooldown": [0.75, 0.9], "file_boost_limit": 5},
        "hard": {"range": [1001, float('inf')], "cooldown": [1.0, 1.0], "file_boost_limit": 1},
        "all": {"range": [1, float('inf')], "cooldown": [1.0, 1.5], "file_boost_limit": 1},
    },
    "ending_limit_ratio": 0.5,
    "recent_boost_multiplier": [20, 10, 5],
    "favorites_boost_multiplier": 2,
    "score_boost": {"min_score": 7.5, "multiplier": 1.0},
    "group_series": True,
    "tag_cooldown": 1,
    "include_non_local_files": False,
    "deduplicate_files": True,
    "deduplicate_versions": False,
    "preload_track_count": 5,
}

infinite_settings = INFINITE_SETTINGS_DEFAULT.copy()

difficulty_ranges = [
    ["easy"],
    ["easy", "medium"],
    ["easy", "medium", "hard"],
    ["medium", "hard"],
    ["hard"],
    ["easy", "medium", "hard"],
]

INT_INF = float('inf')
SEASON_ORDER = ["Winter", "Spring", "Summer", "Fall"]

cached_pop_time_group = None
cached_show_files_map = None
cached_boosted_show_files_map = None
cached_pop_time_cooldown = 0
cached_skipped_themes = []
total_infinite_files = 0
cached_deduplicated_files = None
cached_deduplicated_files_timestamp = 0
series_cooldowns_cache = None
file_cooldowns_cache = None
_refetch_debounce_id = None
_spec_pick_running = False
playlist_loaded = False
series_totals = None
filter_popup = None
_lowest_version_map = {}
_reroll_debounce_id = None

SORTING_TYPES = [
    {"sort": "filename", "order": "asc"}, {"sort": "filename", "order": "desc"},
    {"sort": "title", "order": "asc"}, {"sort": "title", "order": "desc"},
    {"sort": "eng_title", "order": "asc"}, {"sort": "eng_title", "order": "desc"},
    {"sort": "score", "order": "asc"}, {"sort": "score", "order": "desc"},
    {"sort": "members", "order": "asc"}, {"sort": "members", "order": "desc"},
    {"sort": "season", "order": "asc"}, {"sort": "season", "order": "desc"},
]



def _notify_playlist_list_updated():
    """Refresh the right-column list view when the live playlist changes,
    but only while the playlist list (not a system/filter list) is shown."""
    if state.lists.list_loaded == "playlist":
        playlist = state.metadata.playlist
        state.lists.current_list_content = lists.convert_playlist_to_dict(playlist["playlist"])
        state.lists.current_list_selected = playlist["current_index"]
        lists.refresh_current_list()


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


def get_anilist_matching_files(user_id, only_watched, include_non_local):
    """Fetch and return matching files for an AniList user."""
    user_anime_ids = metadata_fetch.fetch_anilist_user_ids(user_id, only_watched)
    if not user_anime_ids:
        return None

    matching_files = []
    for file in get_directory_files(include_non_local=include_non_local):
        data = metadata_fetch.get_metadata(file)
        if data and str(data.get("anilist")) in user_anime_ids:
            matching_files.append(file)

    return matching_files


def get_animethemes_matching_files(hashid, include_non_local):
    """Fetch and return matching files, playlist name, and total count for an AnimeThemes playlist."""
    headers = {
        'User-Agent': f'GuessTheAnime/{APP_VERSION} '
                      f'(https://github.com/ualkotob/guess-the-anime-playlist-tool)'
    }
    response = requests.get(
        f'https://api.animethemes.moe/playlist/{hashid}'
        f'?include=tracks.video&fields[playlist]=name&fields[video]=path',
        headers=headers,
    )
    if response.status_code != 200:
        return None, None, None

    data = response.json()
    playlist_name = data.get('playlist', {}).get('name', hashid)
    tracks = data.get('playlist', {}).get('tracks', [])

    if not tracks:
        return [], playlist_name, 0

    available_files = set(get_directory_files(include_non_local=include_non_local)) if not include_non_local else set()

    matching_files = []
    total_count = 0
    for track in tracks:
        video = track.get('video', {})
        if video and video.get('path'):
            total_count += 1
            filename = os.path.basename(video['path'])
            if include_non_local or filename in available_files:
                matching_files.append(filename)

    if total_count == 0:
        return [], playlist_name, 0

    return matching_files, playlist_name, total_count


def create_living_playlist_with_confirmation(matching_files, playlist_name, source_data, total_available=None):
    """Create a playlist with confirmation dialog and store source metadata."""
    if not matching_files:
        return False

    if total_available is not None:
        message = f"{len(matching_files)} of {total_available} themes found. Create playlist?"
    else:
        message = f"{len(matching_files)} matches found. Create playlist?"

    confirm = messagebox.askyesno("Create Playlist", message)
    if not confirm:
        return False

    auto_update = messagebox.askyesno(
        "Auto-Update Playlist",
        "Should this playlist automatically update with new matching themes on startup?",
    )

    new_playlist(matching_files, playlist_name)
    source_data["auto_update"] = auto_update
    state.metadata.playlist["source"] = source_data
    return True


def generate_anilist_playlist(include_non_local=None):
    user_id = simpledialog.askstring("AniList User ID", "Enter the AniList user ID:")
    if not user_id:
        return

    only_watched = messagebox.askyesno("AniList Only Watched",
                                       "Do you want to limit results to only watched entries?")
    if include_non_local is None:
        include_non_local = messagebox.askyesno(
            "Create Playlist: Include non-local files",
            "Would you like to include non-local files from metadata(they will stream)?",
        )

    matching_files = get_anilist_matching_files(user_id, only_watched, include_non_local)

    if matching_files is None:
        messagebox.showerror("Error", "Could not fetch AniList data or no entries found.")
        return

    if not matching_files:
        messagebox.showwarning("Playlist Error",
                               "No matching video files found for this AniList user.")
        return

    source_data = {
        "type": "anilist",
        "user_id": user_id,
        "only_watched": only_watched,
        "include_non_local": include_non_local,
    }
    create_living_playlist_with_confirmation(matching_files, f"{user_id}'s AniList", source_data)


def generate_animethemes_playlist(include_non_local=None):
    hashid = simpledialog.askstring("AnimeThemes Playlist",
                                    "Enter the AnimeThemes playlist hashid:")
    if not hashid:
        return

    if include_non_local is None:
        include_non_local = messagebox.askyesno(
            "Create Playlist: Include non-local files",
            "Would you like to include non-local files from metadata(they will stream)?",
        )

    try:
        matching_files, playlist_name, total_count = get_animethemes_matching_files(hashid, include_non_local)

        if matching_files is None:
            messagebox.showerror("Error", "Could not fetch playlist.")
            return

        if not matching_files:
            messagebox.showwarning("Playlist Error",
                                   "No matching video files found for this AnimeThemes playlist.")
            return

        source_data = {
            "type": "animethemes",
            "hashid": hashid,
            "include_non_local": include_non_local,
        }
        create_living_playlist_with_confirmation(matching_files, playlist_name, source_data, total_count)

    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch AnimeThemes playlist: {str(e)}")


def generate_session_log_playlist():
    """Create a playlist by matching themes from a saved session log (.txt) file."""
    filepath = filedialog.askopenfilename(
        title="Open Session Log",
        initialdir="sessions" if os.path.isdir("sessions") else ".",
        filetypes=[("Session log files", "*.txt"), ("All files", "*.*")],
    )
    if not filepath:
        return

    anime_metadata = state.metadata.anime_metadata
    file_metadata = state.metadata.file_metadata
    directory_files = state.metadata.directory_files

    title_to_mals = {}
    for mal_id, data in anime_metadata.items():
        for t in filter(None, [data.get("eng_title"), data.get("title"),
                                *(data.get("synonyms") or [])]):
            ts = str(t).strip()
            if ts:
                title_to_mals.setdefault(ts.lower(), []).append(mal_id)

    mal_slug_to_files = {}
    for mal_id, mal_data in file_metadata.items():
        for slug, slug_data in mal_data.get("themes", {}).items():
            for version_data in slug_data.values():
                for fname in version_data.keys():
                    if fname in directory_files:
                        mal_slug_to_files.setdefault((mal_id, slug), []).append(fname)

    def _unformat_slug(fmt):
        if fmt.startswith("Opening "):
            return "OP" + fmt[8:]
        if fmt.startswith("Ending "):
            return "ED" + fmt[7:]
        return fmt

    timestamp_re = re.compile(r'^\d{2}:\d{2}:\d{2}: ?')
    skip_markers = ('[YOUTUBE VIDEO', '[FIXED LIGHTNING ROUNDS', '[SCOREBOARD]', '[BONUS?')
    lightning_re = re.compile(r'^\[LIGHTNING ROUND #\d+\([^)]+\)\] - ')
    slug_op_ed_re = re.compile(r'^(.*) - ((?:Opening|Ending)\s*\d+)(?=\s*(?:\(|$))')
    ext_re = re.compile(r'\s(\S+\.(?:webm|mkv|mp4|avi|mov))\s*$', re.IGNORECASE)

    matched = []
    unmatched_lines = []
    total_lines = 0
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.rstrip('\n\r')
                if not timestamp_re.match(line):
                    continue
                original_body = timestamp_re.sub('', line)
                body = original_body
                if any(body.startswith(m) for m in skip_markers):
                    continue
                is_lightning = bool(lightning_re.match(body))
                body = lightning_re.sub('', body)
                total_lines += 1

                filename_hint = None
                fn_m = ext_re.search(body)
                if fn_m:
                    filename_hint = fn_m.group(1)
                    body = body[:fn_m.start()]

                title = None
                slug = None
                op_ed_m = slug_op_ed_re.match(body.strip())
                if op_ed_m:
                    title = op_ed_m.group(1).strip()
                    slug = _unformat_slug(op_ed_m.group(2).strip())
                else:
                    body_stripped = re.sub(r'\s*\([^(]*\)\s*$', '', body).strip()
                    sep = body_stripped.rfind(' - ')
                    if sep != -1:
                        title = body_stripped[:sep].strip()
                        slug = body_stripped[sep + 3:].strip()

                found = None
                if filename_hint and filename_hint in directory_files:
                    found = filename_hint
                elif title is not None and slug:
                    for mal_id in title_to_mals.get(title.lower(), []):
                        candidates = mal_slug_to_files.get((mal_id, slug), [])
                        if candidates:
                            found = candidates[0]
                            break

                if found:
                    matched.append(f"[L]{found}" if is_lightning else found)
                else:
                    unmatched_lines.append(original_body.rstrip())

    except Exception as e:
        messagebox.showerror("Error", f"Failed to read session log:\n{e}")
        return

    unmatched = len(unmatched_lines)
    if unmatched_lines:
        print(f"[Session Log Playlist] {unmatched} unmatched lines:")
        for ul in unmatched_lines:
            print(f"  UNMATCHED: {ul}")

    if not matched:
        messagebox.showwarning(
            "No Matches",
            f"No matching local files found.\n"
            f"({total_lines} theme lines parsed, {unmatched} unmatched)",
        )
        return

    msg = f"{len(matched)} of {total_lines} theme lines matched to local files."
    if unmatched:
        msg += f"\n{unmatched} could not be matched."
    msg += "\n\nCreate playlist?"
    if not messagebox.askyesno("Create Playlist from Session Log", msg):
        return

    basename = os.path.splitext(os.path.basename(filepath))[0]
    if basename.startswith("guess_the_anime_"):
        playlist_name = basename[len("guess_the_anime_"):]
    else:
        playlist_name = basename

    new_playlist(matched, playlist_name)


def update_living_playlists():
    """Update all saved playlists with source metadata (living playlists) in background."""
    def update_in_background():
        try:
            if not os.path.exists(PLAYLISTS_FOLDER):
                return

            updated_playlists = []

            for filename in os.listdir(PLAYLISTS_FOLDER):
                if not filename.endswith('.json'):
                    continue

                filepath = os.path.join(PLAYLISTS_FOLDER, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        saved_playlist = json.load(f)

                    saved_playlist = utils.convert_infinity_markers(saved_playlist)

                    source = saved_playlist.get('source')
                    if not source:
                        continue

                    if not source.get('auto_update', True):
                        continue

                    source_type = source.get('type')
                    existing_files = set(saved_playlist.get('playlist', []))
                    all_matching = None

                    if source_type == 'anilist':
                        user_id = source.get('user_id')
                        only_watched = source.get('only_watched', False)
                        include_non_local = source.get('include_non_local', False)
                        all_matching = get_anilist_matching_files(user_id, only_watched, include_non_local)

                    elif source_type == 'animethemes':
                        hashid = source.get('hashid')
                        include_non_local = source.get('include_non_local', False)
                        result = get_animethemes_matching_files(hashid, include_non_local)
                        if result:
                            all_matching, _, _ = result

                    if all_matching is not None:
                        all_matching_set = set(all_matching)
                        new_files = [f for f in all_matching if f not in existing_files]
                        removed_files = [f for f in existing_files if f not in all_matching_set]

                        if new_files or removed_files:
                            saved_playlist['playlist'] = all_matching
                            playlist_to_save = copy.deepcopy(saved_playlist)
                            if playlist_to_save.get("infinite_settings"):
                                playlist_to_save["infinite_settings"] = utils.convert_infinities_to_markers(
                                    playlist_to_save["infinite_settings"]
                                )
                            with open(filepath, 'w', encoding='utf-8') as f:
                                json.dump(playlist_to_save, f, indent=4)

                            playlist_name = saved_playlist.get('name', filename[:-5])
                            change_summary = []
                            if new_files:
                                change_summary.append(f"+{len(new_files)}")
                            if removed_files:
                                change_summary.append(f"-{len(removed_files)}")
                            updated_playlists.append((playlist_name, len(new_files), len(removed_files)))
                            print(f"Updated playlist '{playlist_name}': {' '.join(change_summary)} themes")
                            for theme in removed_files:
                                print(f"  - {theme}")
                            for theme in new_files:
                                print(f"  + {theme}")

                except Exception as e:
                    print(f"Error updating playlist {filename}: {e}")
        except Exception as e:
            print(f"Error in update_living_playlists: {e}")

    thread = threading.Thread(target=update_in_background, daemon=True)
    thread.start()


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
                save_as()
        return
    elif playlist.get("name") in SYSTEM_PLAYLISTS:
        return

    playlist_name = playlist["name"]
    saved_playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")

    if not os.path.exists(saved_playlist_path):
        confirm = messagebox.askyesno("Save Playlist",
                                      f"Do you want to save your current playlist before {text}?")
        if confirm:
            save()
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
                save()
    except Exception as e:
        print(f"Error comparing playlists: {e}")
        confirm = messagebox.askyesno("Save Playlist",
                                      f"Do you want to save your current playlist before {text}?")
        if confirm:
            save()


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
    playlist["infinite_settings"] = copy.deepcopy(infinite_settings)
    playlist["infinite_settings"]["include_non_local_files"] = (
        include_non_local if include_non_local is not None else False
    )
    playlist["filter"] = {
        "themes_exclude": [
            "OVERLAP (Without Censors)", "NSFW (Without Censors)",
            "TRANSITION (Without Censors)", "MOVIE EDs (Without Censors)",
        ],
        "playlist_filter_exclude": ["Tagged Themes", "New Themes"],
    }
    get_pop_time_groups(refetch=True)
    get_next_infinite_track()
    def _init_tail():
        fill_speculative_tail()
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
#  INFINITE PLAYLISTS
# ===========================================================================

def get_infinite_settings():
    """Get infinite settings from current playlist or fall back to global settings."""
    playlist = state.metadata.playlist
    stored = playlist.get("infinite_settings")
    if stored is None:
        return infinite_settings
    return {**INFINITE_SETTINGS_DEFAULT, **stored}






def get_last_three_seasons():
    now = datetime.now()
    current_season_string = f"{['Winter', 'Spring', 'Summer', 'Fall'][(now.month - 1) // 3]} {now.year}"
    season, year = current_season_string.split()
    year = int(year)
    index = SEASON_ORDER.index(season)

    last_three = []
    for i in range(3):
        cur_index = (index - i) % 4
        year_offset = (index - i) < 0
        cur_year = year - 1 if year_offset else year
        last_three.append(f"{SEASON_ORDER[cur_index]} {cur_year}")

    return last_three


def get_boost_multiplier(season_string):
    for i, s in enumerate(get_last_three_seasons()):
        if s == season_string:
            return get_infinite_settings()["recent_boost_multiplier"][i]
    return 1


def get_series_boost_multiplier(series, cache=None):
    """Return the lowest seasonal boost across a series."""
    if not series:
        return 1
    if isinstance(series, str):
        series = [series]
    series_key = tuple(sorted(series))
    if cache is not None and series_key in cache:
        return cache[series_key]
    series_target = set(series)
    series_boost = 1
    directory_files = state.metadata.directory_files
    for _filename in directory_files:
        _data = metadata_fetch.get_metadata(_filename)
        if not _data:
            continue
        if metadata_display.series_set(_data) & series_target:
            series_boost = min(series_boost, get_boost_multiplier(_data.get("season", "Fall 2000")))
            if series_boost <= 1:
                break
    if cache is not None:
        cache[series_key] = series_boost
    return series_boost


def select_difficulty(event=None):
    playlist = state.metadata.playlist
    difficulty_dropdown = state.playlist_ui.difficulty_dropdown
    value = difficulty_dropdown.get()
    for i, d in enumerate(state.playlist_ui.difficulty_options):
        if d == value:
            playlist["difficulty"] = i
            refresh_pop_time_groups()
    difficulty_dropdown.selection_clear()
    difficulty_dropdown.icursor(tk.END)
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
        value = difficulty_dropdown.get()
        popout_buttons_by_name["DIFFICULTY DROPDOWN"].set(value)
    popout_window._refresh_popout_toggles()
    config_io.save_config()


def _set_difficulty_from_menu(idx):
    """Set infinite playlist difficulty from a menu radiobutton selection."""
    playlist = state.metadata.playlist
    playlist["difficulty"] = idx
    refresh_pop_time_groups()
    try:
        state.playlist_ui.selected_difficulty.set(state.playlist_ui.difficulty_options[idx])
        state.playlist_ui.difficulty_dropdown.selection_clear()
    except Exception:
        pass
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
        popout_buttons_by_name["DIFFICULTY DROPDOWN"].set(state.playlist_ui.difficulty_options[idx])
    popout_window._refresh_popout_toggles()
    config_io.save_config()


def _clear_speculative_tail():
    """Cancel downloads for and discard all speculative tail entries."""
    playlist = state.metadata.playlist
    for f in playlist.get("speculative_tail", []):
        clean = entry_paths.get_clean_filename(f)
        if cache_download.is_downloading(clean):
            cache_download.cancel_download(clean)
    playlist["speculative_tail"] = []
    playlist.pop("spec_order", None)


def refresh_pop_time_groups(refetch_next=True):
    playlist = state.metadata.playlist
    get_pop_time_groups(refetch=True)
    transport.update_current_index(save=False)
    if refetch_next and playlist["current_index"] == len(playlist["playlist"]) - 2:
        refetch_next_track()
    elif refetch_next:
        _clear_speculative_tail()
        global _refetch_debounce_id
        if _refetch_debounce_id is not None:
            state.widgets.root.after_cancel(_refetch_debounce_id)
        _refetch_debounce_id = state.widgets.root.after(5000, _start_refetch_prefetch)


def _start_refetch_prefetch():
    global _refetch_debounce_id
    _refetch_debounce_id = None
    playlist = state.metadata.playlist
    if playlist.get("playlist"):
        cn = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(cn):
            cache_download.cancel_download(cn)
    cache_download.prefetch_next_themes()


def refetch_next_track():
    global _refetch_debounce_id
    playlist = state.metadata.playlist

    if playlist.get("playlist"):
        old_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(old_next):
            cache_download.cancel_download(old_next)

    _clear_speculative_tail()

    if _refetch_debounce_id is not None:
        state.widgets.root.after_cancel(_refetch_debounce_id)
        _refetch_debounce_id = None

    playlist["playlist"].pop(len(playlist["playlist"]) - 1)
    get_next_infinite_track(increment=False)

    if playlist.get("playlist"):
        new_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(new_next):
            cache_download.cancel_download(new_next)

    metadata_display.up_next_text()
    state.widgets.root.after(1000, lightning_manager.queue_next_lightning_mode)

    state.widgets.root.after(100, lambda: fill_speculative_tail())

    _refetch_debounce_id = state.widgets.root.after(5000, _start_refetch_prefetch)


def reset_infinite_caches():
    """Clear cached infinite-playlist grouping/cooldown data."""
    global cached_pop_time_group, series_cooldowns_cache, file_cooldowns_cache
    cached_pop_time_group = None
    series_cooldowns_cache = None
    file_cooldowns_cache = None


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


def get_pop_time_groups(refetch=False):
    global cached_pop_time_group, cached_show_files_map, cached_boosted_show_files_map
    global cached_pop_time_cooldown, cached_skipped_themes, total_infinite_files

    playlist = state.metadata.playlist
    inf_settings = get_infinite_settings()
    playlist_history = playlist["playlist"][-inf_settings.get("max_history_check", 5000):]
    if refetch or not cached_pop_time_group:
        group_limits = difficulty_ranges[playlist["difficulty"]]
        sorted_groups = [[] for _ in range(3)]
        cached_skipped_themes = []

        directory_options = (
            filter_playlist(playlist["filter"])
            if playlist.get("filter")
            else get_directory_files(
                include_non_local=inf_settings.get("include_non_local_files", False),
                deduplicate_files=False, deduplicate_versions=False,
            )
        )

        if inf_settings.get("deduplicate_files", False):
            directory_options = deduplicate_theme_versions(
                directory_options,
                keep_versions=not inf_settings.get("deduplicate_versions", False),
            )

        total_infinite_files = len(directory_options)
        all_metadata = {f: metadata_fetch.get_metadata(f) for f in directory_options}
        current_session_lightning = session_stats.get_current_session_lightning_tracks()

        playlist_mal_history = []
        for f in playlist_history:
            clean_f = entry_paths.get_clean_filename(f)
            metadata = metadata_fetch.get_metadata(clean_f)
            if metadata and metadata.get("mal"):
                if not f.startswith("[L]") or clean_f in current_session_lightning:
                    playlist_mal_history.append(metadata.get("mal"))

        mal_last_index = {}
        for idx, mal_id in enumerate(playlist_mal_history):
            mal_last_index[mal_id] = idx
        history_len = len(playlist_mal_history)

        playlist_marks.check_theme("", "Favorite Themes")
        check_theme_cache = state.playback.check_theme_cache
        favorited_set = check_theme_cache.get("Favorite Themes", set())

        last_three = get_last_three_seasons()
        recent_boost = inf_settings["recent_boost_multiplier"]
        season_boost_map = {s: recent_boost[i] for i, s in enumerate(last_three)}

        difficulty_groups_list = [
            (k, inf_settings["difficulty_groups"].get(l))
            for k, l in enumerate(group_limits)
        ]
        score_boost_min = inf_settings["score_boost"]["min_score"]
        score_boost_mult = inf_settings["score_boost"]["multiplier"]
        fav_boost = inf_settings["favorites_boost_multiplier"]
        group_series = inf_settings["group_series"]

        shows_files_map = {}
        for f, d in all_metadata.items():
            if not d:
                cached_skipped_themes.append(f)
                continue

            if group_series:
                p = variety_round.get_series_popularity(d)
            else:
                p = d.get("popularity") or INT_INF
            mal = d.get("mal")
            placed = False

            for k, difficulty_group in difficulty_groups_list:
                dg_range = difficulty_group["range"]
                if dg_range[0] <= p <= dg_range[1]:
                    boost = 0
                    if mal not in shows_files_map:
                        boost += (max(0, (d.get("score", 0) or 0) - score_boost_min) % 0.5) * score_boost_mult
                        boost += season_boost_map.get(d.get("season", "Fall 2000"), 1)
                        if mal in mal_last_index:
                            distance_from_end = history_len - 1 - mal_last_index[mal]
                        else:
                            distance_from_end = history_len
                        distance_boost = (distance_from_end // 2000) * (distance_from_end // 2000)
                        boost += distance_boost
                    elif len(shows_files_map[mal]) <= difficulty_group["file_boost_limit"]:
                        boost += 1

                    if fav_boost and f in favorited_set:
                        boost += fav_boost

                    sorted_groups[k].extend([f] * int(boost))
                    shows_files_map.setdefault(mal, []).append(f)
                    placed = True
                    break

            if not placed:
                cached_skipped_themes.append(f)

        if playlist["difficulty"] == 5:
            sorted_groups = [[sorted_groups[0] + sorted_groups[1] + sorted_groups[2], [], []], [[], [], []], [[], [], []]]
        else:
            year_cache = {}
            for entry, meta in all_metadata.items():
                if meta:
                    if meta.get("aired"):
                        season = metadata_fetch.aired_to_season_year(meta.get("aired"), False)
                    else:
                        season = meta.get("season", "9999")[-4:]
                    year_cache[entry] = int(season[-4:])

            def sort_by_year(entries):
                return sorted(entries, key=lambda e: year_cache.get(e.replace("[EXTRA]", ""), 9999), reverse=True)

            for i, g in enumerate(sorted_groups):
                sorted_subgroups = split_into_three(sort_by_year(g))
                for sublist in sorted_subgroups:
                    random.shuffle(sublist)
                sorted_groups[i] = sorted_subgroups

        cached_pop_time_group = sorted_groups
        cached_show_files_map = shows_files_map

        if playlist["difficulty"] == 5:
            sorted_groups = create_virtual_groups_for_random(sorted_groups)

        compute_cooldowns(sorted_groups, True)

    if refetch or not cached_boosted_show_files_map:
        file_last_index = {}
        for idx, f in enumerate(playlist_history):
            file_last_index[f] = idx
        ph_len = len(playlist_history)
        fav_boost = get_infinite_settings()["favorites_boost_multiplier"]
        playlist_marks.check_theme("", "Favorite Themes")
        check_theme_cache = state.playback.check_theme_cache
        favorited_set = check_theme_cache.get("Favorite Themes", set())

        boosted_show_files_map = {}
        for mal_id, files in cached_show_files_map.items():
            for file in files:
                file_boost = 1
                if file in file_last_index:
                    distance_from_end = ph_len - 1 - file_last_index[file]
                else:
                    distance_from_end = ph_len
                file_boost += (distance_from_end // 2000) * (distance_from_end // 2000)
                if fav_boost and file in favorited_set:
                    file_boost = file_boost * fav_boost
                boosted_show_files_map.setdefault(mal_id, []).extend([file] * int(file_boost))
        cached_pop_time_cooldown = 0
        cached_boosted_show_files_map = boosted_show_files_map

    return copy.deepcopy(cached_pop_time_group), copy.deepcopy(cached_boosted_show_files_map)


def next_playlist_order():
    global cached_pop_time_cooldown
    playlist = state.metadata.playlist
    playlist["order"] += 1
    if playlist["order"] >= len(playlist["pop_time_order"]):
        old_len = len(playlist["pop_time_order"])
        playlist["order"] = 0
        playlist["pop_time_order"] = playlist.pop("next_pop_time_order", None) or get_pop_time_order()
        playlist["next_pop_time_order"] = get_pop_time_order()
        if "spec_order" in playlist:
            playlist["spec_order"] = max(0, playlist["spec_order"] - old_len)
    cached_pop_time_cooldown += 1
    if cached_pop_time_cooldown > 50:
        def worker():
            get_pop_time_groups(True)
        threading.Thread(target=worker, daemon=True).start()
        cached_pop_time_cooldown = 0


def next_spec_order():
    playlist = state.metadata.playlist
    playlist["spec_order"] = playlist.get("spec_order", playlist["order"]) + 1


def _get_pop_time_entry(order_val):
    playlist = state.metadata.playlist
    pop = playlist["pop_time_order"]
    if order_val < len(pop):
        return pop[order_val]
    nxt = playlist.get("next_pop_time_order", [])
    idx = order_val - len(pop)
    if idx < len(nxt):
        return nxt[idx]
    return pop[order_val % len(pop)]


def get_next_infinite_track(increment=True, speculative=False):
    playlist = state.metadata.playlist
    if not playlist.get("infinite", False):
        return

    if speculative:
        snap = _build_spec_snapshot()
        next_spec_order()
        result, final_spec_order = _select_speculative_track(snap)
        if result and final_spec_order > playlist.get("spec_order", 0):
            playlist["spec_order"] = final_spec_order
        return result

    if increment:
        next_playlist_order()
    inf_settings = get_infinite_settings()
    snap = _build_spec_snapshot()
    snap["initial_spec_order"] = playlist["order"] - 1
    snap["spec_tail"] = []
    hist_limit = inf_settings.get("max_history_check", 5000)
    snap["playlist_history"] = list(playlist["playlist"][-hist_limit:])
    snap["last50"] = list(playlist["playlist"][-50:])

    result, _ = _select_speculative_track(snap)
    if result:
        playlist["playlist"].append(result)
        if playlist["current_index"] == -1:
            transport.update_current_index(0)
        else:
            transport.update_current_index()
        _notify_playlist_list_updated()
        cache_download.prefetch_next_themes()
    return result


def _start_reroll_prefetch():
    """Called 5 s after the last re-roll to download the chosen next track."""
    global _reroll_debounce_id
    _reroll_debounce_id = None
    cache_download.prefetch_next_themes()


def is_reroll_valid():
    """Check if re-roll is currently valid."""
    playlist = state.metadata.playlist
    return (
        playlist.get("infinite", False)
        and playlist["current_index"] == len(playlist["playlist"]) - 2
    )


def reroll_next():
    """Re-roll the next track in infinite mode immediately."""
    global _reroll_debounce_id
    if not is_reroll_valid():
        return

    playlist = state.metadata.playlist

    if playlist["playlist"]:
        old_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(old_next):
            cache_download.cancel_download(old_next)

    if _reroll_debounce_id is not None:
        state.widgets.root.after_cancel(_reroll_debounce_id)
        _reroll_debounce_id = None

    playlist["playlist"].pop()
    get_next_infinite_track(increment=False)
    metadata_display.up_next_text()
    state.widgets.root.after(1000, lightning_manager.queue_next_lightning_mode)

    if playlist["playlist"]:
        new_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(new_next):
            cache_download.cancel_download(new_next)

    _reroll_debounce_id = state.widgets.root.after(5000, _start_reroll_prefetch)


_spec_pick_running = False


def _build_spec_snapshot():
    """Snapshot all data needed by _select_speculative_track. MUST be called on the main thread."""
    playlist = state.metadata.playlist
    inf_settings = get_infinite_settings()
    groups, shows_files_map = get_pop_time_groups()
    spec_tail = list(playlist.get("speculative_tail", []))
    full_hist = playlist["playlist"] + spec_tail
    hist_limit = inf_settings.get("max_history_check", 5000)
    return {
        "groups": groups,
        "shows_files_map": shows_files_map,
        "spec_tail": spec_tail,
        "playlist_history": list(full_hist[-hist_limit:]),
        "last50": list(playlist["playlist"][-50:]) + spec_tail,
        "initial_spec_order": playlist.get("spec_order", playlist["order"]),
        "pop_time_order": list(playlist["pop_time_order"]),
        "next_pop_time_order": list(playlist.get("next_pop_time_order", [])),
        "difficulty": playlist["difficulty"],
        "inf_settings": inf_settings,
        "light_mode": state.lightning.light_mode,
    }


def _select_speculative_track(snap):
    """Pure selection function — reads only from *snap*, writes nothing global.
    Safe to run in a background thread. Returns (selected_file, final_spec_order).
    """
    inf_settings = snap["inf_settings"]
    groups = snap["groups"]
    shows_files_map = snap["shows_files_map"]
    pop_time_order = snap["pop_time_order"]
    nxt_pop_order = snap["next_pop_time_order"]
    playlist_history = snap["playlist_history"]
    spec_tail = snap["spec_tail"]
    snap_light_mode = snap["light_mode"]
    spec_order = snap["initial_spec_order"] + 1

    def _local_pop_entry(order_val):
        if order_val < len(pop_time_order):
            return pop_time_order[order_val]
        idx = order_val - len(pop_time_order)
        if idx < len(nxt_pop_order):
            return nxt_pop_order[idx]
        return pop_time_order[order_val % max(len(pop_time_order), 1)]

    effective_difficulty_range = difficulty_ranges[snap["difficulty"]]
    _min_s_limit, _min_f_limit = get_cooldown_for_popularity(1, effective_difficulty_range, groups)
    s_limit_mod, f_limit_mod = 1, 1

    p, t = _local_pop_entry(spec_order)
    if p < len(groups) and t < len(groups[p]) and groups[p][t]:
        random.shuffle(groups[p][t])

    selected_file = None
    checked_mal_ids = set()
    try_count = 0
    tag_cooldown_failures = 0
    tag_failed_files = []
    max_tag_tries = min(len(groups[p][t]) // 3, 5) if (p < len(groups) and t < len(groups[p])) else 0
    _hist_entry_cache = {}

    op_count, ed_count = session_stats.get_op_ed_counts(snap["last50"])
    series_boost_cache = {}
    current_session_lightning = session_stats.get_current_session_lightning_tracks()

    recent_tags_union = set()
    if inf_settings.get("tag_cooldown"):
        tag_cooldown_limit = inf_settings["tag_cooldown"]
        for recent_file in (playlist_history + spec_tail)[-tag_cooldown_limit:]:
            recent_tags_union.update(information_popup.get_tags(metadata_fetch.get_metadata(entry_paths.get_clean_filename(recent_file))))

    while not selected_file:
        if p < len(groups) and t < len(groups[p]):
            group_op_count, group_ed_count = session_stats.get_op_ed_counts(groups[p][t])
        else:
            group_op_count, group_ed_count = 0, 0
        if group_ed_count == 0 or (ed_count + op_count) == 0:
            need_op = False
        else:
            need_op = (
                (ed_count / (ed_count + op_count)) > inf_settings["ending_limit_ratio"]
                and (group_op_count / (2 * group_ed_count)) > 0.05
            )

        if p >= len(groups) or t >= len(groups[p]) or not groups[p][t]:
            if try_count > 18:
                return None, spec_order
            spec_order += 1
            p, t = _local_pop_entry(spec_order)
            if p < len(groups) and t < len(groups[p]) and groups[p][t]:
                random.shuffle(groups[p][t])
            max_tag_tries = min(len(groups[p][t]) // 4, 5) if (p < len(groups) and t < len(groups[p])) else 0
            tag_cooldown_failures = 0
            try_count += 1
            continue

        file = groups[p][t].pop(0)
        if file is None:
            try_count += 1
            continue

        extra_file = False
        if "[EXTRA]" in file:
            file = file.replace("[EXTRA]", "")
            extra_file = True
        else:
            selected_mal = metadata_fetch.get_metadata(file).get("mal")

        if extra_file or selected_mal not in checked_mal_ids:
            if extra_file:
                show_files = [file]
            else:
                checked_mal_ids.add(selected_mal)
                show_files = shows_files_map.get(selected_mal, [])
                random.shuffle(show_files)
            checked_files = set()
            while show_files and not selected_file:
                selected_file = show_files.pop(0)
                if selected_file in checked_files:
                    selected_file = None
                    continue
                checked_files.add(selected_file)
                d = metadata_fetch.get_metadata(selected_file)

                if need_op and not utils.is_slug_op(d.get("slug")):
                    selected_file = None
                    continue

                s_pop = variety_round.get_series_popularity(d)
                f_pop = d.get("popularity") or INT_INF
                _base_s_cd, _ = get_cooldown_for_popularity(s_pop, effective_difficulty_range, groups)
                _, _base_f_cd = get_cooldown_for_popularity(f_pop, effective_difficulty_range, groups)
                s_limit = int(_base_s_cd * s_limit_mod)
                f_limit = int(_base_f_cd * f_limit_mod)

                if inf_settings.get("tag_cooldown") and recent_tags_union and tag_cooldown_failures < max_tag_tries:
                    selected_tags = set(information_popup.get_tags(d))
                    if selected_tags & recent_tags_union:
                        tag_failed_files.append(selected_file)
                        selected_file = None
                        tag_cooldown_failures += 1
                        if tag_cooldown_failures >= max_tag_tries:
                            groups[p][t].extend(tag_failed_files)
                            tag_failed_files = []
                    if not selected_file:
                        continue

                if s_limit > 1 or f_limit > 1:
                    series = metadata_display.series_list(d)
                    file_boost = get_boost_multiplier(d.get("season", "Fall 2000"))
                    series_boost = get_series_boost_multiplier(series, cache=series_boost_cache)
                    d_mal = d.get("mal")
                    d_slug = d.get("slug")
                    d_series = set(series)
                    f_break = max(_min_f_limit * f_limit_mod, f_limit / file_boost)
                    s_thresh = max(_min_s_limit * s_limit_mod, s_limit / series_boost)
                    cooldown_count = 0
                    selected_base_f = metadata_display._play_name_key(selected_file)

                    for f in reversed(playlist_history):
                        is_l = f.startswith("[L]")
                        cooldown_count += 0.25 if is_l else 1
                        clean_f = entry_paths.get_clean_filename(f)
                        if not snap_light_mode and is_l and clean_f not in current_session_lightning:
                            continue
                        if cooldown_count >= f_break:
                            break
                        if clean_f not in _hist_entry_cache:
                            f_d = metadata_fetch.get_metadata(clean_f)
                            _hist_entry_cache[clean_f] = (
                                metadata_display._play_name_key(clean_f),
                                f_d.get("mal"),
                                f_d.get("slug"),
                                metadata_display.series_set(f_d),
                            )
                        _base_f, _f_mal, _f_slug, _f_series = _hist_entry_cache[clean_f]
                        if (clean_f == selected_file or _base_f == selected_base_f
                                or (_f_mal == d_mal and _f_slug == d_slug)
                                or (cooldown_count <= s_thresh and bool(d_series & _f_series))):
                            selected_file = None
                            break

        if not groups[p][t]:
            groups, shows_files_map = get_pop_time_groups()
            if p < len(groups) and t < len(groups[p]) and groups[p][t]:
                random.shuffle(groups[p][t])
                tag_cooldown_failures = 0
            checked_mal_ids = set()
            if recent_tags_union:
                recent_tags_union = set()
            else:
                s_limit_mod = s_limit_mod * 0.9
                f_limit_mod = f_limit_mod * 0.9

    return selected_file, spec_order


def fill_speculative_tail(n=None):
    """Pre-pick up to n speculative tracks beyond the committed next."""
    global _spec_pick_running
    playlist = state.metadata.playlist
    if not playlist.get("infinite", False):
        return
    if n is None:
        n = get_infinite_settings().get("preload_track_count", 3)
    if "speculative_tail" not in playlist:
        playlist["speculative_tail"] = []
    if "next_pop_time_order" not in playlist:
        playlist["next_pop_time_order"] = get_pop_time_order()
    if "spec_order" not in playlist:
        playlist["spec_order"] = playlist["order"]
    if len(playlist["speculative_tail"]) >= n:
        return
    if _spec_pick_running:
        state.widgets.root.after(30, lambda: fill_speculative_tail(n))
        return

    snap = _build_spec_snapshot()
    next_spec_order()
    _spec_pick_running = True

    def _worker():
        global _spec_pick_running
        try:
            result, final_spec_order = _select_speculative_track(snap)
        except Exception as e:
            print(f"[spec pick thread error] {e}")
            result, final_spec_order = None, snap["initial_spec_order"]

        def _on_main():
            global _spec_pick_running
            _spec_pick_running = False
            if result:
                playlist["speculative_tail"].append(result)
                if final_spec_order > playlist.get("spec_order", 0):
                    playlist["spec_order"] = final_spec_order
            if len(playlist.get("speculative_tail", [])) < n:
                state.widgets.root.after(5, lambda: fill_speculative_tail(n))

        state.widgets.root.after(0, _on_main)

    threading.Thread(target=_worker, daemon=True).start()


def _promote_or_generate_next():
    """Advance infinite playlist by one track."""
    playlist = state.metadata.playlist
    if not playlist.get("infinite", False):
        return
    tail = playlist.get("speculative_tail", [])
    if tail:
        promoted = tail.pop(0)
        next_playlist_order()
        playlist["playlist"].append(promoted)
        if playlist["current_index"] == -1:
            transport.update_current_index(0)
        else:
            transport.update_current_index()
        _notify_playlist_list_updated()
        cache_download.prefetch_next_themes()
        state.widgets.root.after(50, lambda: fill_speculative_tail())
    else:
        _threaded_generate_next()
        playlist.pop("spec_order", None)
        state.widgets.root.after(50, lambda: fill_speculative_tail())


def _threaded_generate_next():
    """Run a non-speculative infinite pick in a background thread."""
    playlist = state.metadata.playlist
    next_playlist_order()
    snap = _build_spec_snapshot()
    snap["initial_spec_order"] = playlist["order"] - 1

    def _worker():
        try:
            result, _ = _select_speculative_track(snap)
        except Exception as e:
            print(f"[threaded generate next error] {e}")
            result = None

        def _apply():
            if result:
                playlist["playlist"].append(result)
                if playlist["current_index"] == -1:
                    transport.update_current_index(0)
                else:
                    transport.update_current_index()
                _notify_playlist_list_updated()
                cache_download.prefetch_next_themes()
            else:
                get_next_infinite_track()

        state.widgets.root.after(0, _apply)

    threading.Thread(target=_worker, daemon=True).start()


def get_cooldown_for_popularity(popularity_rank, difficulty_range, groups):
    """Calculate cooldowns using computed values with smooth interpolation."""
    if not series_cooldowns_cache or not file_cooldowns_cache:
        return 84, 385

    if len(series_cooldowns_cache) == 1:
        return int(series_cooldowns_cache[0]), int(file_cooldowns_cache[0])
    elif len(series_cooldowns_cache) == 2:
        group1_series, group2_series = series_cooldowns_cache
        group1_file, group2_file = file_cooldowns_cache

        if difficulty_range == ["easy", "medium"]:
            easy_series, medium_series, hard_series = group1_series, group2_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group2_file, group2_file
        elif difficulty_range == ["medium", "hard"]:
            easy_series, medium_series, hard_series = group1_series, group1_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group1_file, group2_file
        else:
            easy_series, medium_series, hard_series = group1_series, group1_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group1_file, group2_file
    else:
        easy_series, medium_series, hard_series = series_cooldowns_cache
        easy_file, medium_file, hard_file = file_cooldowns_cache

    if popularity_rank <= 50:
        series_cooldown = easy_series
        file_cooldown = easy_file
    elif popularity_rank <= 250:
        progress = (popularity_rank - 50) / 200
        series_cooldown = easy_series + (progress * (medium_series - easy_series))
        file_cooldown = easy_file + (progress * (medium_file - easy_file))
    elif popularity_rank <= 1000:
        progress = (popularity_rank - 250) / 750
        series_cooldown = medium_series + (progress * (hard_series - medium_series))
        file_cooldown = medium_file + (progress * (hard_file - medium_file))
    else:
        inf_settings = get_infinite_settings()
        max_rank_for_scaling = inf_settings.get("max_history_check", 10000)
        capped_rank = min(popularity_rank, max_rank_for_scaling)
        progress = (capped_rank - 1000) / max(max_rank_for_scaling - 1000, 1)
        file_cooldown = hard_file + (progress * (inf_settings.get("max_history_check", 10000) - hard_file))
        if hard_file > 0:
            series_to_file_ratio = hard_series / hard_file
        else:
            series_to_file_ratio = 1
        series_cooldown = file_cooldown * series_to_file_ratio

    return int(series_cooldown), int(file_cooldown)


def create_virtual_groups_for_random(sorted_groups):
    """Create virtual groups for random mode by redistributing files by popularity ranges."""
    all_files_flat = []
    for group in sorted_groups:
        for subgroup in group:
            all_files_flat.extend(subgroup)

    virtual_groups = [[], [], []]
    for file in all_files_flat:
        clean_file = file.replace("[EXTRA]", "")
        metadata = metadata_fetch.get_metadata(clean_file)
        popularity = metadata.get("popularity") or float('inf')

        if popularity <= 250:
            virtual_groups[0].append(file)
        elif popularity <= 1000:
            virtual_groups[1].append(file)
        else:
            virtual_groups[2].append(file)

    structured_virtual_groups = []
    for i, virtual_group in enumerate(virtual_groups):
        def get_year(entry):
            meta = metadata_fetch.get_metadata(entry.replace("[EXTRA]", ""))
            if meta and meta.get("aired"):
                season = metadata_fetch.aired_to_season_year(meta.get("aired"), False)
            else:
                season = meta.get("season", "9999")[-4:] if meta else "9999"
            return int(season[-4:])

        sorted_virtual_group = sorted(virtual_group, key=get_year, reverse=True)
        virtual_subgroups = split_into_three(sorted_virtual_group)

        for sublist in virtual_subgroups:
            random.shuffle(sublist)

        structured_virtual_groups.append(virtual_subgroups)

    return structured_virtual_groups


def compute_cooldowns(groups, refetch=False):
    global series_cooldowns_cache, file_cooldowns_cache
    playlist = state.metadata.playlist
    if not series_cooldowns_cache or refetch:
        series_cooldowns = []
        file_cooldowns = []

        inf_settings = get_infinite_settings()
        difficulty_range = difficulty_ranges[playlist["difficulty"]]

        for i, group in enumerate(groups):
            if i >= len(difficulty_range):
                continue
            difficulty_group = inf_settings["difficulty_groups"][difficulty_range[i]]
            all_files = [f for subgroup in group for f in subgroup]
            unique_files = set(f.replace("[EXTRA]", "") for f in all_files)
            file_count = len(unique_files)
            unique_series = set(metadata_display.series_cache_key(metadata_fetch.get_metadata(f.replace("[EXTRA]", ""))) for f in all_files)
            series_count = len(unique_series)

            base_s_cd = series_count
            base_f_cd = file_count

            s_cd = int(base_s_cd * difficulty_group["cooldown"][0])
            f_cd = int(base_f_cd * difficulty_group["cooldown"][1])

            series_cooldowns.append(s_cd)
            file_cooldowns.append(f_cd)

        series_cooldowns_cache, file_cooldowns_cache = series_cooldowns, file_cooldowns
    return series_cooldowns_cache, file_cooldowns_cache


# ===========================================================================
#  SAVE / LOAD PLAYLISTS
# ===========================================================================

def save():
    playlist = state.metadata.playlist
    save_playlist(playlist, playlist["current_index"], state.widgets.root)


def save_as():
    save_playlist_as(state.widgets.root)


def _write_playlist(name):
    """Write the current playlist to disk under the given name."""
    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")
    playlist = state.metadata.playlist
    playlist_to_save = copy.deepcopy(playlist)
    if playlist_to_save.get("infinite_settings"):
        playlist_to_save["infinite_settings"] = utils.convert_infinities_to_markers(
            playlist_to_save["infinite_settings"]
        )
    utils._atomic_json_write(filename, playlist_to_save, indent=4)
    transport.update_playlist_name(name)
    config_io.save_config()
    print(f"Playlist saved as {filename}")


def save_playlist(playlist, index, parent=None):
    """Saves the playlist using its current name. Falls back to Save As if unnamed."""
    if not playlist.get("name"):
        save_playlist_as(parent)
        return
    _write_playlist(playlist["name"])


def save_playlist_as(parent=None):
    """Prompts for a name, then saves the playlist."""
    playlist = state.metadata.playlist
    name = simpledialog.askstring(
        "Save Playlist As", "Enter playlist name:",
        initialvalue=playlist["name"], parent=parent,
    )
    if not name:
        return
    elif name.lower() == "missing artists":
        check_missing_artists()
        return
    playlist["name"] = name
    _write_playlist(name)


def _load_playlist_by_name(name: str, save_first: bool = False) -> bool:
    """Core playlist loading shared by load_playlist() and the web select_playlist action."""
    global playlist_loaded
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")
    if not os.path.exists(filename):
        print(f"Playlist {name} not found.")
        return False
    if save_first and state.metadata.playlist.get('name'):
        _write_playlist(state.metadata.playlist['name'])
    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = utils.convert_infinity_markers(data)
    state.metadata.playlist.clear()
    state.metadata.playlist.update(data)
    transport.update_playlist_name()
    print(f"Loaded playlist: {name}")
    playlist_loaded = True
    playlist = state.metadata.playlist
    if playlist.get("infinite"):
        refresh_pop_time_groups(False)
    if name.lower() == "missing artists":
        check_missing_artists()
    transport.update_current_index()
    config_io.save_config()
    return True


def load_playlist(index):
    """Loads a saved playlist from JSON."""
    list_loaded = state.lists.list_loaded
    if list_loaded == "load_playlist":
        playlists = get_playlists_dict(exclude_system=True)
    elif list_loaded == "load_system_playlist":
        playlists = get_playlists_dict(system_only=True)
    else:
        playlists = get_playlists_dict()

    if index not in playlists:
        print(f"Invalid playlist index: {index}")
        return None
    name = playlists[index]

    confirm_save_playlist("loading a new playlist")
    if not _load_playlist_by_name(name):
        return None
    list_loaded = state.lists.list_loaded
    if list_loaded == "load_playlist":
        load(True)
    elif list_loaded == "load_system_playlist":
        load_system_playlist(True)


def load(update=False):
    playlist = state.metadata.playlist
    selected = -1
    playlists = get_playlists_dict(exclude_system=True)
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
    lists.show_list(
        "load_playlist", state.widgets.right_column, playlists, get_playlist_name,
        load_playlist, selected, update, delete_playlist, title="LOAD PLAYLIST",
    )


def load_system_playlist(update=False):
    playlist = state.metadata.playlist
    selected = -1
    playlists = get_playlists_dict(system_only=True)
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
    lists.show_list(
        "load_system_playlist", state.widgets.right_column, playlists, get_playlist_name,
        load_playlist, selected, update, delete_playlist, title="SYSTEM PLAYLISTS",
    )


def delete(update=False):
    playlist = state.metadata.playlist
    selected = -1
    playlists = get_playlists_dict()
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
    lists.show_list(
        "delete_playlist", state.widgets.right_column, playlists, get_playlist_name,
        delete_playlist, selected, update, title="DELETE PLAYLIST",
    )


def get_mergeable_playlists():
    playlists = get_playlists_dict()
    current_name = state.metadata.playlist.get("name", "")
    mergeable = []
    for _, name in playlists.items():
        if current_name and name == current_name:
            continue
        data = playlist_marks.get_playlist(name)
        if data.get("infinite"):
            continue
        mergeable.append(name)
    return {i: name for i, name in enumerate(mergeable)}


def merge_playlist(update=False):
    if state.metadata.playlist.get("infinite", False):
        return
    playlists = get_mergeable_playlists()
    if not playlists:
        messagebox.showinfo("Merge Playlist", "No non-infinite playlists available to merge.")
        return
    lists.show_list(
        "merge_playlist", state.widgets.right_column, playlists, get_playlist_name,
        merge_playlist_select, -1, update, title="MERGE INTO PLAYLIST",
    )


def merge_playlist_select(index):
    global playlist_changed
    playlists = get_mergeable_playlists()
    if index not in playlists:
        return
    name = playlists[index]
    data = playlist_marks.get_playlist(name)
    if data.get("infinite"):
        return
    confirm = messagebox.askyesno("Merge Playlist",
                                   f"Add themes from '{name}' to the current playlist?")
    if not confirm:
        return
    playlist = state.metadata.playlist
    existing = set(playlist.get("playlist", []))
    added = 0
    for item in data.get("playlist", []):
        if item not in existing:
            playlist["playlist"].append(item)
            existing.add(item)
            added += 1
    if added > 0:
        playlist_changed = True
        config_io.save_config()
        transport.update_current_index(save=False)
        merge_playlist(True)
    messagebox.showinfo("Merge Playlist", f"Added {added} new theme(s) from '{name}'.")


def delete_playlist(index):
    """Deletes a playlist by index after confirmation."""
    list_loaded = state.lists.list_loaded
    if list_loaded == "load_playlist":
        playlists = get_playlists_dict(exclude_system=True)
    elif list_loaded == "load_system_playlist":
        playlists = get_playlists_dict(system_only=True)
    else:
        playlists = get_playlists_dict()

    if index not in playlists:
        print("Invalid playlist index.")
        return

    name = playlists[index]
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")

    confirm = messagebox.askyesno("Delete Playlist",
                                   f"Are you sure you want to delete '{name}'?")
    if not confirm:
        return

    try:
        os.remove(filename)
        check_theme_cache = state.playback.check_theme_cache
        if check_theme_cache.get("name"):
            del check_theme_cache["name"]
        if check_theme_cache.get(name):
            del check_theme_cache[name]
        print(f"Deleted playlist: {name}")
    except Exception as e:
        print(f"Error deleting playlist: {e}")
        return

    list_loaded = state.lists.list_loaded
    if list_loaded == "load_playlist":
        load(True)
    elif list_loaded == "load_system_playlist":
        load_system_playlist(True)
    elif list_loaded == "delete_playlist":
        delete(True)


def delete_file_by_filename(filename):
    """Find the full path from directory_files and delete the file after confirmation."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Delete File",
                             f"The file does not exist or is not found:\n{filename}")
        return

    confirm = messagebox.askyesno("Delete File",
                                   f"Are you sure you want to delete this file?\n\n{filename}")
    if confirm:
        try:
            transport.stop()

            file_data = metadata_fetch.get_file_metadata_by_name(filename)

            os.remove(filepath)
            print(f"Deleted file: {filename}")
            del directory_files[filename]
            invalidate_deduplicated_cache()

            file_metadata = state.metadata.file_metadata
            metadata_updated = False
            if file_data and not cache_download.is_animethemes_stream_file(filename):
                mal_id = file_data.get("mal")
                slug = file_data.get("slug")
                version = str(file_data.get("version")) if file_data.get("version") is not None else "null"

                if mal_id and slug and mal_id in file_metadata:
                    themes = file_metadata[mal_id].get("themes", {})
                    if slug in themes and version in themes[slug] and filename in themes[slug][version]:
                        del themes[slug][version][filename]
                        metadata_updated = True

                        if not themes[slug][version]:
                            del themes[slug][version]
                        if not themes[slug]:
                            del themes[slug]

            if metadata_updated:
                metadata_fetch.build_filename_to_mal_map()
                metadata_io.save_metadata()

            currently_playing = state.playback.currently_playing
            if currently_playing and currently_playing.get("filename") == filename:
                state.widgets.root.after(100, lambda: metadata_panel.update_extra_metadata())

        except Exception as e:
            messagebox.showerror("Error", f"Could not delete file:\n{e}")
    else:
        print(f"Deletion canceled for file: {filename}")


def open_file_folder_by_filename(filename):
    """Find the full path from directory_files and open its containing folder."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Open Folder",
                             f"The file does not exist or is not found:\n{filename}")
        return

    try:
        if platform.system() == "Windows":
            subprocess.run(["explorer", "/select,", os.path.normpath(filepath)])
        elif platform.system() == "Darwin":
            subprocess.run(["open", "-R", filepath])
        else:
            subprocess.run(["xdg-open", os.path.dirname(filepath)])
        print(f"Opened folder for: {filename}")
    except Exception as e:
        messagebox.showerror("Error", f"Could not open folder:\n{e}")


def rename_file_by_filename(filename):
    """Rename a file and update all relevant metadata and directory references."""
    directory_files = state.metadata.directory_files
    file_metadata = state.metadata.file_metadata
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Rename File",
                             f"The file does not exist or is not found:\n{filename}")
        return

    current_base, extension = os.path.splitext(filename)
    new_base = simpledialog.askstring("Rename File",
                                      "Enter new filename (without extension):",
                                      initialvalue=current_base)

    if not new_base:
        return

    new_base = new_base.strip()
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    if any(char in new_base for char in invalid_chars):
        messagebox.showerror("Invalid Name",
                             f"Filename cannot contain: {' '.join(invalid_chars)}")
        return

    new_filename = new_base + extension
    directory = os.path.dirname(filepath)
    new_filepath = os.path.join(directory, new_filename)

    if new_filename in directory_files and new_filename != filename:
        messagebox.showerror("Rename Error",
                             f"A file with the name '{new_filename}' already exists in the directory list.")
        return

    if os.path.exists(new_filepath) and new_filepath != filepath:
        messagebox.showerror("Rename Error", f"A file already exists at:\n{new_filepath}")
        return

    currently_playing = state.playback.currently_playing
    if currently_playing.get("filename") == filename:
        transport.stop()

    try:
        os.rename(filepath, new_filepath)

        if filename in directory_files:
            del directory_files[filename]
        directory_files[new_filename] = new_filepath
        invalidate_deduplicated_cache()

        file_data = metadata_fetch.get_file_metadata_by_name(filename)
        if file_data:
            mal_id = file_data.get("mal")
            slug = file_data.get("slug")
            version = str(file_data.get("version")) if file_data.get("version") is not None else "null"

            if mal_id and slug and mal_id in file_metadata:
                themes = file_metadata[mal_id].get("themes", {})
                if slug in themes and version in themes[slug]:
                    if filename in themes[slug][version]:
                        themes[slug][version][new_filename] = themes[slug][version][filename]
                        del themes[slug][version][filename]
                        metadata_fetch.build_filename_to_mal_map()

        playlist = state.metadata.playlist
        if playlist and playlist.get("playlist"):
            for i, playlist_file in enumerate(playlist["playlist"]):
                clean_playlist_file = playlist_file[3:] if playlist_file.startswith("[L]") else playlist_file
                if clean_playlist_file == filename:
                    prefix = "[L]" if playlist_file.startswith("[L]") else ""
                    playlist["playlist"][i] = prefix + new_filename

        if currently_playing.get("filename") == filename:
            currently_playing["filename"] = new_filename
            if "playlist_entry" in currently_playing:
                old_entry = currently_playing["playlist_entry"]
                prefix = "[L]" if old_entry.startswith("[L]") else ""
                currently_playing["playlist_entry"] = prefix + new_filename

        metadata_io.save_metadata()
        config_io.save_config()

        if currently_playing.get("filename") == new_filename:
            metadata_panel.update_metadata()
        print(f"Renamed '{filename}' to '{new_filename}'")

    except Exception as e:
        messagebox.showerror("Rename Error", f"Failed to rename file:\n{e}")
        print(f"Error renaming file: {e}")


def edit_file_volume_by_filename(filename):
    """Find the full path from directory_files and edit the volume using ffmpeg."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Edit Volume",
                             f"The file does not exist or is not found:\n{filename}")
        return

    volume_str = simpledialog.askstring(
        "Edit Volume",
        "Enter volume multiplier (e.g., 0.5 for half volume, 2.0 for double volume):\n\n"
        "Examples:\n• 0.5 = 50% volume\n• 1.0 = original volume\n• 2.0 = 200% volume",
        initialvalue="1.0",
    )

    if not volume_str:
        return

    try:
        volume_level_set = float(volume_str)
        if volume_level_set <= 0:
            messagebox.showerror("Invalid Volume", "Volume level must be greater than 0")
            return
    except ValueError:
        messagebox.showerror("Invalid Volume",
                             "Please enter a valid number (e.g., 0.5, 1.0, 2.0)")
        return

    confirm = messagebox.askyesno(
        "Edit Volume",
        f"This will modify the volume of:\n{filename}\n\n"
        f"Volume multiplier: {volume_level_set}\n\n"
        "The video will be stopped and the original file will be replaced.\nContinue?",
    )
    if not confirm:
        return

    transport.stop()
    base, ext = os.path.splitext(filepath)
    temp_filepath = f"{base}_temp_volume{ext}"

    try:
        ffmpeg_cmd = [
            "ffmpeg", "-i", filepath,
            "-af", f"volume={volume_level_set}",
            "-c:v", "copy", "-y", temp_filepath,
        ]

        result = subprocess.run(
            ffmpeg_cmd, capture_output=True, text=True,
            encoding='utf-8', errors='ignore', timeout=300,
        )

        if result.returncode == 0:
            if os.path.exists(temp_filepath):
                os.remove(filepath)
                os.rename(temp_filepath, filepath)
                messagebox.showinfo(
                    "Volume Edited",
                    f"Successfully edited volume:\n{filename}\n\nVolume multiplier: {volume_level_set}x",
                )
                print(f"Successfully edited volume for: {filename} (volume: {volume_level_set}x)")
            else:
                messagebox.showerror("Error", "Temporary file was not created successfully")
        else:
            try:
                error_msg = result.stderr if result.stderr else "Unknown ffmpeg error"
            except UnicodeDecodeError:
                error_msg = "FFmpeg error (unable to decode error message)"
            messagebox.showerror("FFmpeg Error", f"Failed to edit volume:\n\n{error_msg}")
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)

    except subprocess.TimeoutExpired:
        messagebox.showerror("Timeout",
                             "Operation timed out. The file may be too large or ffmpeg is not responding.")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
    except FileNotFoundError:
        messagebox.showerror(
            "FFmpeg Not Found",
            "FFmpeg is not installed or not found in PATH.\n\n"
            "Please install FFmpeg and ensure it's available in your system PATH.",
        )
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while editing volume:\n{e}")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)


def convert_file_format_by_filename(filename):
    """Convert a file to a different format using ffmpeg."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("File Not Found",
                             f"The file does not exist or is not found:\n{filename}")
        return

    format_str = simpledialog.askstring(
        "Convert Format",
        "Enter output format (file extension):\n\n"
        "Examples:\n• mp4\n• webm\n• mkv\n• avi\n• mov\n• mp3\n• wav\n\n"
        "Enter format without the dot:",
        initialvalue="webm",
    )

    if not format_str:
        return

    output_format = format_str.strip().lower()
    if output_format.startswith('.'):
        output_format = output_format[1:]

    base, _ = os.path.splitext(filepath)
    output_filepath = f"{base}.{output_format}"

    confirm = messagebox.askyesno(
        "Convert Format",
        f"This will convert:\n{filename}\n\nTo format: {output_format.upper()}\n"
        f"Output file: {os.path.basename(output_filepath)}\n\nContinue?",
    )
    if not confirm:
        return

    transport.stop()

    try:
        if output_format in ['mp4', 'mov']:
            video_codec = "libx264"
            audio_codec = "aac"
            audio_settings = ["-b:a", "256k"]
            video_settings = ["-crf", "18"]
        elif output_format == 'webm':
            video_codec = "libvpx-vp9"
            audio_codec = "libopus"
            audio_settings = ["-b:a", "128k"]
            video_settings = ["-crf", "25", "-b:v", "0"]
        elif output_format in ['mkv', 'avi']:
            video_codec = "libx264"
            audio_codec = "aac"
            audio_settings = ["-b:a", "256k"]
            video_settings = ["-crf", "18"]
        elif output_format == 'mp3':
            video_codec = None
            audio_codec = "libmp3lame"
            audio_settings = ["-b:a", "320k"]
            video_settings = []
        elif output_format == 'wav':
            video_codec = None
            audio_codec = "pcm_s16le"
            audio_settings = []
            video_settings = []
        elif output_format in ['ogg', 'oga']:
            video_codec = None
            audio_codec = "libvorbis"
            audio_settings = ["-q:a", "8"]
            video_settings = []
        else:
            video_codec = None
            audio_codec = None
            audio_settings = ["-b:a", "256k"]
            video_settings = []

        ffmpeg_cmd = ["ffmpeg", "-i", filepath]

        if video_codec:
            ffmpeg_cmd.extend(["-c:v", video_codec])
            if output_format == 'webm':
                ffmpeg_cmd.extend(["-deadline", "best", "-cpu-used", "0"])
            else:
                ffmpeg_cmd.extend(["-preset", "slow"])
            ffmpeg_cmd.extend(video_settings)
        elif video_codec is None and output_format not in ['mp3', 'wav', 'ogg', 'oga']:
            ffmpeg_cmd.extend(["-c:v", "copy"])

        if audio_codec:
            ffmpeg_cmd.extend(["-c:a", audio_codec])
            ffmpeg_cmd.extend(audio_settings)
        elif audio_codec is None:
            ffmpeg_cmd.extend(["-c:a", "copy"])

        if output_format in ['mp3', 'wav', 'ogg', 'oga']:
            ffmpeg_cmd.extend(["-vn"])

        ffmpeg_cmd.extend(["-y", output_filepath])

        print(f"Converting {filename} to {output_format.upper()} format...")
        result = subprocess.run(ffmpeg_cmd, text=True, encoding='utf-8', errors='ignore')

        if result.returncode == 0 and os.path.exists(output_filepath):
            messagebox.showinfo("Conversion Complete",
                                f"File converted successfully!\nSaved as: {os.path.basename(output_filepath)}")
            print(f"Conversion completed successfully: {os.path.basename(output_filepath)}")

            try:
                if platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", os.path.normpath(output_filepath)])
                elif platform.system() == "Darwin":
                    subprocess.run(["open", "-R", output_filepath])
                else:
                    subprocess.run(["xdg-open", os.path.dirname(output_filepath)])
            except Exception as e:
                print(f"Could not open folder: {e}")

            replace = messagebox.askyesno(
                "Replace Original",
                f"Do you want to replace the original file with the converted version?\n\n"
                f"Original: {filename}\nConverted: {os.path.basename(output_filepath)}\n\n"
                "This cannot be undone!",
            )

            if replace:
                try:
                    os.remove(filepath)
                    original_base, _ = os.path.splitext(filepath)
                    new_original_path = f"{original_base}.{output_format}"
                    os.rename(output_filepath, new_original_path)

                    original_base_name, old_ext = os.path.splitext(filename)
                    new_filename = f"{original_base_name}.{output_format}"

                    if filename in directory_files:
                        del directory_files[filename]
                        directory_files[new_filename] = new_original_path
                    invalidate_deduplicated_cache()

                    file_metadata = state.metadata.file_metadata
                    file_data = metadata_fetch.get_file_metadata_by_name(filename)
                    if file_data:
                        mal_id = file_data.get("mal")
                        slug = file_data.get("slug")
                        version = str(file_data.get("version")) if file_data.get("version") is not None else "null"

                        if mal_id and slug and mal_id in file_metadata:
                            themes = file_metadata[mal_id].get("themes", {})
                            if slug in themes and version in themes[slug]:
                                if filename in themes[slug][version]:
                                    themes[slug][version][new_filename] = themes[slug][version][filename]
                                    del themes[slug][version][filename]
                                    metadata_fetch.build_filename_to_mal_map()

                    playlist = state.metadata.playlist
                    if playlist and playlist.get("playlist"):
                        for i, playlist_file in enumerate(playlist["playlist"]):
                            if playlist_file == filename:
                                playlist["playlist"][i] = new_filename

                    metadata_io.save_metadata()
                    config_io.save_config()

                    messagebox.showinfo("File Replaced",
                                       f"Original file has been replaced with the converted version.\n"
                                       f"Metadata updated for: {new_filename}")
                    print(f"Replaced {filename} with converted {output_format.upper()} version")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to replace original file:\n{e}")
        else:
            print(f"FFmpeg conversion failed with return code {result.returncode}")
            messagebox.showerror("Conversion Error",
                                 f"Failed to convert file to {output_format.upper()} format.\n\n"
                                 "Check the console for detailed error information.")
            if os.path.exists(output_filepath):
                os.remove(output_filepath)

    except subprocess.TimeoutExpired:
        messagebox.showerror("Timeout",
                             "Conversion timed out after 15 minutes.")
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
    except FileNotFoundError:
        messagebox.showerror("FFmpeg Not Found",
                             "FFmpeg is not installed or not found in PATH.\n\n"
                             "Please install FFmpeg and ensure it's available in your system PATH.")
    except Exception as e:
        messagebox.showerror("Error",
                             f"An unexpected error occurred during conversion:\n\n{str(e)}")
        if os.path.exists(output_filepath):
            os.remove(output_filepath)


def _cut_video_at_time(filename, cut_mode):
    """Shared helper to cut video before or after current time using FFmpeg."""
    if not state.widgets.player.get_media():
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title,
                             "No video is currently loaded. Please load a video first.")
        return

    current_time_ms = state.widgets.player.get_time()
    if current_time_ms <= 0:
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title, "Cannot determine current playback time.")
        return

    current_time_sec = current_time_ms / 1000.0

    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)
    if not filepath or not os.path.exists(filepath):
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title,
                             f"The file does not exist or is not found:\n{filename}")
        return

    minutes = int(current_time_sec // 60)
    seconds = int(current_time_sec % 60)
    milliseconds = int((current_time_sec % 1) * 1000)
    time_display = f"{minutes}:{seconds:02d}.{milliseconds:03d}"

    if cut_mode == "before":
        confirm_title = "Cut Before Current Time"
        confirm_msg = (
            f"This will cut the video BEFORE the current time:\n{filename}\n\n"
            f"Current time: {time_display}\n"
            f"Result: Keep everything AFTER {time_display}\n\nContinue?"
        )
        suffix = "_cut_before"
        log_msg = f"before {time_display}"
    else:
        confirm_title = "Cut After Current Time"
        confirm_msg = (
            f"This will cut the video AFTER the current time:\n{filename}\n\n"
            f"Current time: {time_display}\n"
            f"Result: Keep everything BEFORE {time_display}\n\nContinue?"
        )
        suffix = "_cut_after"
        log_msg = f"after {time_display}"

    confirm = messagebox.askyesno(confirm_title, confirm_msg)
    if not confirm:
        return

    cutting_method = messagebox.askyesnocancel(
        "Choose Cutting Method",
        "Choose cutting precision:\n\n"
        "YES = FAST CUT (stream copy)\n"
        "  • Very fast, no quality loss\n"
        "  • May cut a few seconds off due to keyframes\n\n"
        "NO = PRECISE CUT (re-encode)\n"
        "  • Frame-accurate cutting\n"
        "  • Slower, slight quality loss\n\n"
        "CANCEL = Abort operation",
    )

    if cutting_method is None:
        return

    use_stream_copy = cutting_method

    base, ext = os.path.splitext(filepath)
    precision_suffix = "_fast" if use_stream_copy else "_precise"
    cut_filepath = f"{base}{suffix}{precision_suffix}{ext}"

    try:
        _, output_ext = os.path.splitext(cut_filepath)
        output_ext = output_ext.lower()

        if output_ext == '.webm':
            video_codec_options = ["libvpx-vp9", "libvpx", "libx264"]
            audio_codec_options = ["libvorbis", "libopus", "aac"]
        elif output_ext == '.mp4':
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]
        elif output_ext == '.mkv':
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]
        else:
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]

        def check_codec_available(codec_name, codec_type="encoder"):
            try:
                result = subprocess.run(
                    ["ffmpeg", "-hide_banner", f"-{codec_type}s"],
                    capture_output=True, text=True, timeout=10,
                )
                return codec_name in result.stdout
            except Exception:
                return False

        video_codec = next((c for c in video_codec_options if check_codec_available(c)), None)
        audio_codec = next((c for c in audio_codec_options if check_codec_available(c)), None)

        if output_ext == '.webm' and (video_codec in ["libx264", "h264"] or audio_codec == "aac"):
            print("Warning: WebM codecs not available, switching to MP4 format")
            cut_filepath = os.path.splitext(cut_filepath)[0] + ".mp4"
            output_ext = '.mp4'
            if not video_codec:
                video_codec = "libx264"
            if not audio_codec:
                audio_codec = "aac"

        if not use_stream_copy:
            if not video_codec:
                messagebox.showerror("Codec Error",
                                     f"No suitable video encoder found for {output_ext} format.\n"
                                     "Try using fast cut (stream copy) instead.")
                return
            if not audio_codec:
                messagebox.showerror("Codec Error",
                                     f"No suitable audio encoder found for {output_ext} format.\n"
                                     "Try using fast cut (stream copy) instead.")
                return

        def _audio_quality_args(codec):
            if codec == "libvorbis":
                return ["-q:a", "6"]
            elif codec in ("libopus", "aac", "mp3"):
                return ["-b:a", "192k"]
            return []

        if cut_mode == "before":
            if use_stream_copy:
                ffmpeg_cmd = [
                    "ffmpeg", "-ss", str(current_time_sec), "-i", filepath,
                    "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", cut_filepath,
                ]
            else:
                ffmpeg_cmd = (
                    ["ffmpeg", "-i", filepath, "-ss", str(current_time_sec),
                     "-c:v", video_codec, "-c:a", audio_codec, "-preset", "fast",
                     "-avoid_negative_ts", "make_zero", "-y"]
                    + _audio_quality_args(audio_codec)
                    + [cut_filepath]
                )
        else:
            if use_stream_copy:
                ffmpeg_cmd = [
                    "ffmpeg", "-i", filepath, "-t", str(current_time_sec),
                    "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", cut_filepath,
                ]
            else:
                ffmpeg_cmd = (
                    ["ffmpeg", "-i", filepath, "-t", str(current_time_sec),
                     "-c:v", video_codec, "-c:a", audio_codec, "-preset", "fast",
                     "-avoid_negative_ts", "make_zero", "-y"]
                    + _audio_quality_args(audio_codec)
                    + [cut_filepath]
                )

        if use_stream_copy:
            result = subprocess.run(
                ffmpeg_cmd, capture_output=True, text=True,
                encoding='utf-8', errors='ignore', timeout=300,
            )
        else:
            result = subprocess.run(ffmpeg_cmd, text=True, encoding='utf-8', errors='ignore', timeout=600)

        if result.returncode == 0 and os.path.exists(cut_filepath):
            success_msg = f"Video cut successfully!\nSaved as: {os.path.basename(cut_filepath)}"
            if not use_stream_copy:
                success_msg += "\n\n(Re-encoded for frame precision)"
            messagebox.showinfo("Cut Complete", success_msg)

            try:
                if platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", os.path.normpath(cut_filepath)])
                elif platform.system() == "Darwin":
                    subprocess.run(["open", "-R", cut_filepath])
                else:
                    subprocess.run(["xdg-open", os.path.dirname(cut_filepath)])
            except Exception as e:
                print(f"Could not open folder: {e}")

            replace = messagebox.askyesno(
                "Replace Original",
                f"Do you want to replace the original file with the cut version?\n\n"
                f"Original: {filename}\nCut file: {os.path.basename(cut_filepath)}\n\n"
                "This cannot be undone!",
            )

            if replace:
                try:
                    transport.stop()
                    os.remove(filepath)
                    os.rename(cut_filepath, filepath)
                    messagebox.showinfo("File Replaced",
                                       "Original file has been replaced with the cut version.")
                    print(f"Replaced {filename} with cut version ({log_msg})")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to replace original file:\n{e}")
        else:
            if hasattr(result, 'stderr') and result.stderr:
                error_details = result.stderr.strip()
                error_summary = error_details.split('\n')[-1] if error_details else "Unknown FFmpeg error"
            else:
                error_summary = f"FFmpeg exited with code {result.returncode}"
            messagebox.showerror("FFmpeg Error", f"Failed to cut video:\n\n{error_summary}")
            if os.path.exists(cut_filepath):
                os.remove(cut_filepath)

    except subprocess.TimeoutExpired as e:
        messagebox.showerror("Timeout", f"Operation timed out after {e.timeout} seconds.")
        if os.path.exists(cut_filepath):
            os.remove(cut_filepath)
    except FileNotFoundError:
        messagebox.showerror("FFmpeg Not Found",
                             "FFmpeg is not installed or not found in PATH.\n\n"
                             "Please install FFmpeg and ensure it's available in your system PATH.")
    except Exception as e:
        messagebox.showerror("Error", f"An unexpected error occurred:\n\n{str(e)}")
        if os.path.exists(cut_filepath):
            os.remove(cut_filepath)


def cut_before_current_time(filename):
    """Cut the video before the current playback time using FFmpeg."""
    _cut_video_at_time(filename, "before")


def cut_after_current_time(filename):
    """Cut the video after the current playback time using FFmpeg."""
    _cut_video_at_time(filename, "after")


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
#  FILTERING PLAYLISTS
# ===========================================================================

filter_popup = None


def load_filters(update=False):
    filters = get_all_filters()
    lists.show_list("load_filters", state.widgets.right_column, filters, get_filter_name, load_filter, -1, update, delete_filter, title="LOAD FILTER")


def get_filter_name(key, value):
    return value.get("name")


def load_filter(index):
    """Applies a saved filter from JSON."""
    filter_data = get_all_filters()[index]
    name = filter_data.get('name')
    confirm = messagebox.askyesno("Filter Playlist", f"Are you sure you want to apply the filter '{name}'?")
    if not confirm:
        return
    filters = filter_data.get("filter")
    utils._migrate_theme_flags(filters)
    playlist = state.metadata.playlist
    if playlist.get("infinite"):
        playlist["filter"] = filters
        print("Applied Filters:", filters)
        refresh_pop_time_groups()
        config_io.save_config()
    else:
        filter_playlist(filters)


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


def show_filter_popup():
    """Opens a properly formatted, scrollable popup for filtering the playlist."""
    global filter_popup
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        inf_settings = get_infinite_settings()
        playlis = get_directory_files(include_non_local=inf_settings.get("include_non_local_files", False), deduplicate_files=False, deduplicate_versions=False)
    else:
        playlis = playlist["playlist"]

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
        for item in data:
            listbox.insert(tk.END, item)

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
    popout_controls = popout_window.popout_controls
    if popout_controls and popout_controls.winfo_exists():
        popup.update_idletasks()
        x = popout_controls.winfo_x()
        y = popout_controls.winfo_y()
        popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")
    else:
        popup.geometry(f"{popup_width}x{popup_height}")

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

    available_playlists = list(get_playlists_dict().values())
    playlist_listbox = filter_entry_listbox("PLAYLISTS\nINCLUDE\n(OR)", left_column, available_playlists, height=4)
    playlist_and_listbox = filter_entry_listbox("PLAYLISTS\nINCLUDE\n(AND)", left_column, available_playlists, height=4)

    tk.Label(left_column, text="KEYWORDS (separated by commas):", bg=BACKGROUND_COLOR, fg="white").pack(anchor="w", pady=(5, 0))
    keywords_entry = tk.Text(left_column, height=1, width=31, bg="black", fg="white", wrap="word")
    keywords_entry.pack(pady=(0, 5))

    theme_type_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    theme_type_frame.pack(fill="x", pady=5)

    tk.Label(theme_type_frame, text="THEME TYPE:", bg=BACKGROUND_COLOR, fg="white").pack(side="left", padx=(0, 7))

    theme_var = tk.StringVar(value="Both")
    theme_type_combobox = ttk.Combobox(
        theme_type_frame, textvariable=theme_var,
        values=["Both", "Opening", "Ending"], width=20,
        style="Black.TCombobox", state="readonly",
    )
    theme_type_combobox.pack(side="left", fill="x", expand=True)

    score_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    score_frame.pack(fill="x", pady=5)
    tk.Label(score_frame, text="SCORE\nRANGE", bg=BACKGROUND_COLOR, fg="white").pack(side="left")
    lowest_score = get_lowest_parameter("score", playlis)
    highest_score = get_highest_parameter("score", playlis)
    min_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, orient="horizontal", bg="black", fg="white", command=update_score_range)
    min_score_slider.pack(fill="x")
    max_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, orient="horizontal", bg="black", fg="white", command=update_score_range)
    max_score_slider.pack(fill="x")

    rank_entry = filter_entry_range("RANK               ", left_column, get_highest_parameter("rank", playlis), get_lowest_parameter("rank", playlis))
    members_entry = filter_entry_range("MEMBERS       ", left_column, get_lowest_parameter("members", playlis), get_highest_parameter("members", playlis))
    popularity_entry = filter_entry_range("POPULARITY  ", left_column, get_highest_parameter("popularity", playlis), get_lowest_parameter("popularity", playlis))

    season_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    season_frame.pack(fill="x", pady=(5, 10))

    tk.Label(season_frame, text="AIRED:   ", bg=BACKGROUND_COLOR, fg="white").pack(side="left")

    all_seasons = get_all_seasons(playlis)

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

    theme_exclude_options = [
        "DUPLICATES", "LATER VERSIONS",
        "OVERLAP (Without Censors)", "OVERLAP (With Censors)",
        "NSFW (Without Censors)", "NSFW (With Censors)",
        "SPOILER (Without Censors)", "SPOILER (With Censors)",
        "TRANSITION (Without Censors)", "TRANSITION (With Censors)",
        "MOVIE EDs (Without Censors)", "MOVIE EDs (With Censors)",
    ]
    themes_include_listbox = filter_entry_listbox("THEMES\nINCLUDE\n(OR)", left_column, theme_exclude_options, height=4)
    themes_exclude_listbox = filter_entry_listbox("THEMES\nEXCLUDE\n(OR)", left_column, theme_exclude_options, height=4)
    playlist_exclude_listbox = filter_entry_listbox("PLAYLISTS\nEXCLUDE\n(OR)", right_column, available_playlists, height=4)
    artists_listbox = filter_entry_listbox("ARTISTS\nINCLUDE\n(OR)", right_column, get_all_artists(playlis))
    studio_listbox = filter_entry_listbox("STUDIOS\nINCLUDE\n(OR)", right_column, get_all_studios(playlis))
    all_tags = get_all_tags(playlis)
    tags_listbox = filter_entry_listbox("TAGS\nINCLUDE\n(OR)", right_column, all_tags)
    tags_and_listbox = filter_entry_listbox("TAGS\nINCLUDE\n(AND)", right_column, all_tags)
    excluded_tags_listbox = filter_entry_listbox("TAGS\nEXCLUDE\n(OR)", right_column, all_tags)

    def set_default_values(force_defaults=False):
        filter_data = {} if force_defaults else playlist.get("filter", {})
        if "playlist_filter" in filter_data and isinstance(filter_data["playlist_filter"], str):
            filter_data["playlist_filter"] = [filter_data["playlist_filter"]]
        keywords_entry.delete("1.0", tk.END)
        keywords_entry.insert("1.0", filter_data.get("keywords", ""))
        theme_var.set(filter_data.get("theme_type", "Both"))
        min_score_slider.set(filter_data.get("score_min", lowest_score))
        max_score_slider.set(filter_data.get("score_max", highest_score))
        rank_entry["min"].delete(0, tk.END)
        rank_entry["min"].insert(0, filter_data.get("rank_min", get_highest_parameter("rank", playlis)))
        rank_entry["max"].delete(0, tk.END)
        rank_entry["max"].insert(0, filter_data.get("rank_max", get_lowest_parameter("rank", playlis)))
        season_start_var.set(filter_data.get("season_min", all_seasons[0] if all_seasons else ""))
        season_end_var.set(filter_data.get("season_max", all_seasons[-1] if all_seasons else ""))
        members_entry["min"].delete(0, tk.END)
        members_entry["min"].insert(0, filter_data.get("members_min", get_lowest_parameter("members", playlis)))
        members_entry["max"].delete(0, tk.END)
        members_entry["max"].insert(0, filter_data.get("members_max", get_highest_parameter("members", playlis)))
        popularity_entry["min"].delete(0, tk.END)
        popularity_entry["min"].insert(0, filter_data.get("popularity_min", get_highest_parameter("popularity", playlis)))
        popularity_entry["max"].delete(0, tk.END)
        popularity_entry["max"].insert(0, filter_data.get("popularity_max", get_lowest_parameter("popularity", playlis)))
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
                for i in range(listbox.size()):
                    if listbox.get(i) in values:
                        listbox.selection_set(i)

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
        if theme_var.get() != "Both": f['theme_type'] = str(theme_var.get())
        if float(min_score_slider.get()) != round(lowest_score, 1): f['score_min'] = float(min_score_slider.get())
        if float(max_score_slider.get()) != round(highest_score, 1): f['score_max'] = float(max_score_slider.get())
        f = assign_filter_range_value(f, 'rank', rank_entry, get_highest_parameter("rank", playlis), get_lowest_parameter("rank", playlis))
        f = assign_filter_range_value(f, 'members', members_entry, get_lowest_parameter("members", playlis), get_highest_parameter("members", playlis))
        f = assign_filter_range_value(f, 'popularity', popularity_entry, get_highest_parameter("popularity", playlis), get_lowest_parameter("popularity", playlis))
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
            refresh_pop_time_groups()
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
    artists = []
    for filename in playlis:
        data = metadata_fetch.get_metadata(filename)
        if data:
            for song in data.get('songs', []):
                for artist in song.get("artist", []):
                    if artist not in artists:
                        artists.append(artist)
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


def filter_playlist(filters):
    """Filters the playlist based on given criteria."""
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        inf_settings = get_infinite_settings()
        playlis = get_directory_files(include_non_local=inf_settings.get("include_non_local_files", False), deduplicate_files=False, deduplicate_versions=False)
    else:
        playlis = playlist["playlist"]

    filtered = []

    has_playlist_filter = "playlist_filter" in filters
    has_playlist_filter_and = "playlist_filter_and" in filters
    has_playlist_filter_exclude = "playlist_filter_exclude" in filters
    has_keywords = "keywords" in filters
    has_theme_type = "theme_type" in filters
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
    filter_theme_type = filters.get("theme_type")
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
            path = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")
            if os.path.exists(path):
                with open(path, "r") as f:
                    result.update(json.load(f).get("playlist", []))
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
            rank = data.get("rank") or 100000
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
            popularity = data.get("popularity") or INT_INF
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
            title = data.get("title", "").lower()
            eng_title = (data.get("eng_title", "") or "").lower()
            filename_lower = filename.lower()
            if not any(kw in filename_lower or kw in title or kw in eng_title for kw in keyword_list):
                continue

        if has_theme_type:
            theme_type = utils.format_slug(data.get("slug"))
            if filter_theme_type not in theme_type:
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
                theme = utils.get_song_by_slug(data, slug)
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

            if has_themes_exclude and not theme_flags.isdisjoint(themes_exclude_set):
                continue
            if has_themes_include and theme_flags.isdisjoint(themes_include_set):
                continue
            if (exclude_duplicates and not check_best_duplicate_theme(filename, data)) or (include_duplicates and check_best_duplicate_theme(filename, data)):
                continue
            if (exclude_versions and not check_lowest_version(filename, data)) or (include_versions and check_lowest_version(filename, data)):
                continue

        filtered.append(filename)

    if not playlist.get("infinite"):
        playlist["playlist"] = filtered
        print("Applied Filters:", filters)
        lists.show_playlist(True)
        transport.update_current_index(0)
        messagebox.showinfo("Playlist Filtered", f"Playlist filtered to {len(playlist['playlist'])} videos.")
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
