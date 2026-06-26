"""Saving, loading, deleting and merging of named playlists on disk.

Extracted from playlist.py. confirm_save_playlist() (still in playlist.py)
calls save()/save_as() here, and these functions call back into playlist for
confirm_save_playlist / check_missing_artists / refresh_pop_time_groups /
get_playlists_dict / get_playlist_name — all runtime-only, so the playlist
<-> playlist_io cycle resolves cleanly. playlist_changed remains owned by
playlist.py (transport reads playlist_ops.playlist_changed), so
merge_playlist_select writes it through the module.
"""
import copy
import json
import os

from tkinter import messagebox, simpledialog

from core.game_state import state
from core.paths import PLAYLISTS_FOLDER
from _app_scripts import utils
import _app_scripts.playback.transport as transport
import _app_scripts.data.config_io as config_io
import _app_scripts.ui.lists as lists
import _app_scripts.theme.marks as playlist_marks
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.playlists.infinite as infinite

playlist_loaded = False


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
        playlist_ops.check_missing_artists()
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
        infinite.refresh_pop_time_groups(False)
    if name.lower() == "missing artists":
        playlist_ops.check_missing_artists()
    transport.update_current_index()
    config_io.save_config()
    return True


def load_playlist(index):
    """Loads a saved playlist from JSON."""
    list_loaded = state.lists.list_loaded
    if list_loaded == "load_playlist":
        playlists = playlist_ops.get_playlists_dict(exclude_system=True)
    elif list_loaded == "load_system_playlist":
        playlists = playlist_ops.get_playlists_dict(system_only=True)
    else:
        playlists = playlist_ops.get_playlists_dict()

    if index not in playlists:
        print(f"Invalid playlist index: {index}")
        return None
    name = playlists[index]

    playlist_ops.confirm_save_playlist("loading a new playlist")
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
    playlists = playlist_ops.get_playlists_dict(exclude_system=True)
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
    lists.show_list(
        "load_playlist", state.widgets.right_column, playlists, playlist_ops.get_playlist_name,
        load_playlist, selected, update, delete_playlist, title="LOAD PLAYLIST",
    )


def load_system_playlist(update=False):
    playlist = state.metadata.playlist
    selected = -1
    playlists = playlist_ops.get_playlists_dict(system_only=True)
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
    lists.show_list(
        "load_system_playlist", state.widgets.right_column, playlists, playlist_ops.get_playlist_name,
        load_playlist, selected, update, delete_playlist, title="SYSTEM PLAYLISTS",
    )


def delete(update=False):
    playlist = state.metadata.playlist
    selected = -1
    playlists = playlist_ops.get_playlists_dict()
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
    lists.show_list(
        "delete_playlist", state.widgets.right_column, playlists, playlist_ops.get_playlist_name,
        delete_playlist, selected, update, title="DELETE PLAYLIST",
    )


def get_mergeable_playlists():
    playlists = playlist_ops.get_playlists_dict()
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
        "merge_playlist", state.widgets.right_column, playlists, playlist_ops.get_playlist_name,
        merge_playlist_select, -1, update, title="MERGE INTO PLAYLIST",
    )


def merge_playlist_select(index):
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
        playlist_ops.playlist_changed = True
        config_io.save_config()
        transport.update_current_index(save=False)
        merge_playlist(True)
    messagebox.showinfo("Merge Playlist", f"Added {added} new theme(s) from '{name}'.")


def delete_playlist(index):
    """Deletes a playlist by index after confirmation."""
    list_loaded = state.lists.list_loaded
    if list_loaded == "load_playlist":
        playlists = playlist_ops.get_playlists_dict(exclude_system=True)
    elif list_loaded == "load_system_playlist":
        playlists = playlist_ops.get_playlists_dict(system_only=True)
    else:
        playlists = playlist_ops.get_playlists_dict()

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
