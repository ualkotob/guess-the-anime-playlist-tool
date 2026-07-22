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
import json
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
DEFAULT_INFINITE_FILTER = {
    "themes_exclude": [
        "OVERLAP (Without Censors)", "NSFW (Without Censors)",
        "TRANSITION (Without Censors)", "MOVIE EDs (Without Censors)",
    ],
    "playlist_filter_exclude": ["Tagged Themes", "New Themes"],
}


def load_filters(update=False):
    filters = get_all_filters()
    lists.show_list("load_filters", state.widgets.right_column, filters, get_filter_name, load_filter, -1, update, delete_filter, title="LOAD FILTER")


def get_filter_name(key, value):
    return value.get("name")



def ensure_default_infinite_filter_saved():
    """Create the default infinite playlist filter preset if it is missing."""
    existing_filters = get_all_filters()
    for filter_data in existing_filters.values():
        if filter_data.get("name") == DEFAULT_INFINITE_FILTER_NAME:
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
    filters = copy.deepcopy(filter_data.get("filter") or {})
    utils._migrate_theme_flags(filters)
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


def show_filter_popup():
    """Opens a properly formatted, scrollable popup for filtering the playlist."""
    global filter_popup
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        inf_settings = infinite.get_infinite_settings()
        playlis = playlist_ops.get_directory_files(include_non_local=inf_settings.get("include_non_local_files", False), deduplicate_files=False, deduplicate_versions=False)
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


def filter_playlist(filters, notify=True):
    """Filters the playlist based on given criteria."""
    playlist = state.metadata.playlist
    if playlist.get("infinite", False):
        inf_settings = infinite.get_infinite_settings()
        playlis = playlist_ops.get_directory_files(include_non_local=inf_settings.get("include_non_local_files", False), deduplicate_files=False, deduplicate_versions=False)
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
        if notify:
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
