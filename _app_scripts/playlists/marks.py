"""Playlist mark helpers for tags, favorites, reveal marks, and saved playlists."""

import copy
import json
import os
import tkinter as tk
from tkinter import messagebox


SYSTEM_PLAYLISTS = [
    "Tagged Themes",
    "Favorite Themes",
    "New Themes",
    "Missing Artists",
    "Blind Themes",
    "Reveal Themes",
    "Mute Reveal Themes",
]

check_theme_cache = {}
_ctx = {}


def set_context(
    *,
    playlists_folder,
    blank_playlist,
    get_active_playlist,
    get_currently_playing,
    get_playlists_dict,
    update_current_index,
    update_series_song_information,
    is_title_window_up,
    is_title_info_only,
    toggle_title_popup,
    web_server,
    root,
    highlight_color,
    menu_font,
    popup_menu,
    atomic_json_write,
    convert_infinity_markers,
):
    _ctx.clear()
    _ctx.update(locals())


def get_playlist(playlist_name):
    playlist_path = os.path.join(_ctx["playlists_folder"], f"{playlist_name}.json")
    if os.path.exists(playlist_path):
        with open(playlist_path, "r", encoding="utf-8") as f:
            return json.load(f)

    new_playlist = copy.deepcopy(_ctx["blank_playlist"])
    new_playlist["name"] = playlist_name
    return new_playlist


def _push_web_marks(filename=None):
    """Push the current theme's mark states to all web host clients."""
    web_server = _ctx["web_server"]
    if not web_server.is_running():
        return

    currently_playing = _ctx["get_currently_playing"]()
    fn = filename or currently_playing.get("filename") or ""
    web_server.push_marks({
        "tagged": bool(check_theme(fn, "Tagged Themes")),
        "favorited": bool(check_theme(fn, "Favorite Themes")),
        "blind": bool(check_theme(fn, "Blind Themes")),
        "peek": bool(check_theme(fn, "Reveal Themes")),
        "mute_peek": bool(check_theme(fn, "Mute Reveal Themes")),
    })


def toggle_theme(playlist_name, filename=None, quiet=False, add=False):
    """Toggle a theme in a specified playlist."""
    currently_playing = _ctx["get_currently_playing"]()
    if not filename:
        if currently_playing.get("filename"):
            filename = currently_playing.get("filename")
        else:
            return

    playlists_folder = _ctx["playlists_folder"]
    playlist_path = os.path.join(playlists_folder, f"{playlist_name}.json")
    data = get_playlist(playlist_name)
    theme_list = data["playlist"]

    type_string = "saved to"
    if filename in theme_list:
        if not add:
            theme_list.remove(filename)
            type_string = "removed from"
        else:
            return
    else:
        if not theme_list:
            theme_list = [filename]
        else:
            theme_list.append(filename)

    data["playlist"] = theme_list

    if not os.path.exists(playlists_folder):
        os.makedirs(playlists_folder)

    _ctx["atomic_json_write"](playlist_path, data, indent=4)
    if not quiet:
        print(f"{filename} {type_string} playlist '{playlist_name}'.")

    active_playlist = _ctx["get_active_playlist"]()
    if active_playlist.get("name") == playlist_name:
        if filename in theme_list:
            if filename not in active_playlist["playlist"]:
                active_playlist["playlist"].append(filename)
            if currently_playing.get("filename") == filename:
                active_playlist["current_index"] = len(active_playlist["playlist"]) - 1
            _ctx["update_current_index"]()
        else:
            if filename in active_playlist["playlist"]:
                active_playlist["playlist"].remove(filename)
                if currently_playing.get("filename") == filename:
                    active_playlist["current_index"] -= 1
                    _ctx["update_current_index"]()

    check_theme(playlist_name=playlist_name, recache=True)

    if currently_playing.get("filename") == filename and _ctx["web_server"].is_running():
        _push_web_marks(filename)

    if currently_playing.get("data") and currently_playing.get("filename") == filename:
        data = currently_playing.get("data")
        _ctx["update_series_song_information"](data, data.get("mal"))

    if (
        playlist_name == "Favorite Themes"
        and currently_playing.get("filename") == filename
        and _ctx["is_title_window_up"]()
        and not _ctx["is_title_info_only"]()
    ):
        _ctx["toggle_title_popup"](True)


def check_theme(filename=None, playlist_name=None, recache=False):
    """Check if a theme exists in a specified playlist."""
    if playlist_name and (recache or not check_theme_cache.get(playlist_name)):
        playlist_path = os.path.join(_ctx["playlists_folder"], f"{playlist_name}.json")
        if os.path.exists(playlist_path):
            with open(playlist_path, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                loaded_data = _ctx["convert_infinity_markers"](loaded_data)
                check_theme_cache[playlist_name] = set(loaded_data.get("playlist", []))
        else:
            check_theme_cache[playlist_name] = set()
    return filename in check_theme_cache.get(playlist_name, set())


def tag():
    toggle_theme("Tagged Themes")


def check_tagged(filename):
    return check_theme(filename, "Tagged Themes")


def favorite():
    toggle_theme("Favorite Themes")


def check_favorited(filename):
    return check_theme(filename, "Favorite Themes")


def check_new(filename):
    return check_theme(filename, "New Themes")


def blind_mark(remove=False):
    if not remove:
        filename = _ctx["get_currently_playing"]().get("filename")
        if check_peek_mark(filename):
            peek_mark(True)
        if check_mute_peek_mark(filename):
            mute_peek_mark(True)
    toggle_theme("Blind Themes")


def check_blind_mark(filename):
    return check_theme(filename, "Blind Themes")


def peek_mark(remove=False):
    if not remove:
        filename = _ctx["get_currently_playing"]().get("filename")
        if check_blind_mark(filename):
            blind_mark(True)
        if check_mute_peek_mark(filename):
            mute_peek_mark(True)
    toggle_theme("Reveal Themes")


def check_peek_mark(filename):
    return check_theme(filename, "Reveal Themes")


def mute_peek_mark(remove=False):
    if not remove:
        filename = _ctx["get_currently_playing"]().get("filename")
        if check_blind_mark(filename):
            blind_mark(True)
        if check_peek_mark(filename):
            peek_mark(True)
    toggle_theme("Mute Reveal Themes")


def check_mute_peek_mark(filename):
    return check_theme(filename, "Mute Reveal Themes")


def add_to_saved_playlist(filename=None):
    """Show a popup submenu to add the current theme to a non-system, non-infinite playlist."""
    if not filename:
        filename = _ctx["get_currently_playing"]().get("filename")
    if not filename:
        return

    all_playlists = _ctx["get_playlists_dict"](exclude_system=True)
    playlists = {}
    for idx, name in all_playlists.items():
        data = get_playlist(name)
        if not data.get("infinite"):
            playlists[idx] = name
    if not playlists:
        messagebox.showinfo("Add to Playlist", "No saved playlists found.\nCreate a playlist first.")
        return

    root = _ctx["root"]
    m = tk.Menu(
        root,
        tearoff=0,
        bg="black",
        fg="white",
        activebackground=_ctx["highlight_color"],
        activeforeground="white",
        font=_ctx["menu_font"],
    )
    for idx, name in playlists.items():
        already_in = check_theme(filename, name)
        label = ("✓  " if already_in else "     ") + name

        def _add(n=name):
            toggle_theme(n, filename=filename)

        m.add_command(label=label, command=_add)
    _ctx["popup_menu"](m, root.winfo_pointerx(), root.winfo_pointery())


def handle_bulk_marking(playlist_name, check_func, mutually_exclusive_playlists=None):
    """Handle bulk marking/unmarking of an entire playlist based on current item's state."""
    active_playlist = _ctx["get_active_playlist"]()
    currently_playing = _ctx["get_currently_playing"]()
    if not active_playlist.get("playlist") or not currently_playing.get("filename"):
        return

    current_filename = currently_playing.get("filename")
    current_is_marked = check_func(current_filename)
    action = "unmark" if current_is_marked else "mark"

    playlist_count = len(active_playlist["playlist"])
    confirm = messagebox.askyesno(
        f"Bulk {action.title()} Confirmation",
        f"Are you sure you want to {action} all {playlist_count} items in the playlist for '{playlist_name}'?",
    )

    if not confirm:
        return

    for filename in active_playlist["playlist"]:
        if current_is_marked:
            if check_func(filename):
                toggle_theme(playlist_name, filename=filename, quiet=True)
        else:
            if not check_func(filename):
                if mutually_exclusive_playlists:
                    for exclusive_playlist, exclusive_check_func in mutually_exclusive_playlists:
                        if exclusive_check_func(filename):
                            toggle_theme(exclusive_playlist, filename=filename, quiet=True)

                toggle_theme(playlist_name, filename=filename, quiet=True, add=True)

    action_past = "unmarked" if current_is_marked else "marked"
    print(f"Bulk {action_past} entire playlist for '{playlist_name}'")


def bulk_tag_playlist(event=None):
    handle_bulk_marking("Tagged Themes", check_tagged)


def bulk_favorite_playlist(event=None):
    handle_bulk_marking("Favorite Themes", check_favorited)


def bulk_blind_mark_playlist(event=None):
    mutually_exclusive = [
        ("Reveal Themes", check_peek_mark),
        ("Mute Reveal Themes", check_mute_peek_mark),
    ]
    handle_bulk_marking("Blind Themes", check_blind_mark, mutually_exclusive)


def bulk_peek_mark_playlist(event=None):
    mutually_exclusive = [
        ("Blind Themes", check_blind_mark),
        ("Mute Reveal Themes", check_mute_peek_mark),
    ]
    handle_bulk_marking("Reveal Themes", check_peek_mark, mutually_exclusive)


def bulk_mute_peek_mark_playlist(event=None):
    mutually_exclusive = [
        ("Blind Themes", check_blind_mark),
        ("Reveal Themes", check_peek_mark),
    ]
    handle_bulk_marking("Mute Reveal Themes", check_mute_peek_mark, mutually_exclusive)
