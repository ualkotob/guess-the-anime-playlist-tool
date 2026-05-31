"""FIXED LIGHTNING ROUNDS (main-side actions) — extracted from
guess_the_anime.py (Step 83, 2026-05-28).

Owns the 7 main-side helpers that drive the right-column "FIXED LIGHTNING
ROUND PLAYLISTS" list, queue/play actions, and the context menu. All
mutated state (`fixed_lightning_queue`, `fixed_lightning_round_playlist_data`,
`fixed_current_round`, `fixed_lightning_rounds_list`) stays in main per
[[state-stays-with-its-readers]] — those names are rebound from many sites
across main + cross-module readers via `_main.X`. This module reads them via
`_main.X` and writes the rebound `fixed_lightning_queue` via
`_main.fixed_lightning_queue = ...`.

The editor/manager (`open_fixed_lightning_manager`) lives in sibling
module `fixed_lightning.py`; this module is just the list/queue actions.

Uses the `_main` module-reference pattern (Steps 70/71/75/79/80/81/82).
"""

import os
import json
import copy
import random
import tkinter as tk

from . import fixed_lightning


_main = None


def set_context(*, main_module):
    global _main
    _main = main_module


def load_fixed_lightning_rounds(filter_missing_themes=False):
    """Load fixed lightning round playlists from folder"""
    rounds_list = _main.fixed_lightning_rounds_list
    rounds_list.clear()

    folder = fixed_lightning.FIXED_LIGHTNING_FOLDER
    if os.path.exists(folder):
        json_files = sorted(
            [f for f in os.listdir(folder) if f.endswith(".json")],
            key=lambda f: json.load(open(os.path.join(folder, f), 'r', encoding='utf-8')).get("date_modified", ""),
            reverse=True
        )
        for filename in json_files:
            try:
                filepath = os.path.join(folder, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    round_name = data.get("name", filename[:-5])

                    # Calculate total duration and count valid rounds
                    total_duration = 0
                    valid_rounds = []

                    for round_data in data.get("rounds", []):
                        theme = round_data.get("theme", "")
                        if not filter_missing_themes or _main.get_clean_filename(theme) in _main.directory_files or _main.is_animethemes_stream_file(theme):
                            duration = round_data.get("duration", _main.lightning_mode_settings_default.get(round_data.get("type", "regular"), {}).get("length", 12))
                            answer_duration = round_data.get("answer_duration", 8)

                            total_duration += duration + answer_duration
                            valid_rounds.append(round_data)

                    # Update data with only valid rounds
                    data["rounds"] = valid_rounds

                    rounds_list.append({
                        "name": round_name,
                        "filename": filename,
                        "filepath": filepath,
                        "data": data,
                        "creator": data.get("creator", "N/A"),
                        "description": data.get("description", "No description"),
                        "rounds": valid_rounds,
                        "total_duration": total_duration,
                        "round_count": len(valid_rounds)
                    })
            except Exception as e:
                print(f"Error loading fixed lightning round playlist {filename}: {e}")

    return rounds_list


def _fl_set_queue_and_notify(round_info):
    """Set fixed_lightning_queue and show the coming-up popup + prefetch. Does NOT play."""
    _main.fixed_lightning_queue = round_info
    name = round_info.get('name', 'Unnamed Round')
    desc = round_info.get('description', '')
    creator = round_info.get('creator', '')
    date_created = round_info.get("data", {}).get('date_created', 'N/A').split(" ")[0]
    date_modified = round_info.get("data", {}).get('date_modified', 'N/A').split(" ")[0]
    rounds_count = round_info.get('round_count', 0)
    total_duration = round_info.get('total_duration', 0)
    created_string = f"Created: {date_created}"
    if date_created != date_modified:
        created_string += f" (Modified: {date_modified})"
    minutes = int(total_duration // 60)
    seconds = int(total_duration % 60)
    duration_str = f"{minutes}:{seconds:02d}"
    details_text = f"Created by: {creator}\n{created_string}\nRounds: {rounds_count} | Duration: {duration_str} mins\n\n{desc}"
    _main.toggle_coming_up_popup(True, name, details_text, queue=True)
    _main.prefetch_next_themes()


def _queue_fixed_lightning_round_by_index(index, randomize=False):
    """Queue a fixed lightning round by list index, optionally shuffling its rounds."""
    rounds_list = _main.fixed_lightning_rounds_list
    if not (0 <= index < len(rounds_list)):
        return
    ri = copy.deepcopy(rounds_list[index])
    if randomize:
        random.shuffle(ri.get("rounds", []))
    _fl_set_queue_and_notify(ri)
    _main.queue_next_lightning_mode()
    show_fixed_lightning_list(update=True)
    _main.up_next_text()


def _play_fixed_lightning_round_now(index, randomize=False):
    """Immediately play a fixed lightning round by list index, optionally shuffling its rounds."""
    rounds_list = _main.fixed_lightning_rounds_list
    if not (0 <= index < len(rounds_list)):
        return
    ri = copy.deepcopy(rounds_list[index])
    if randomize:
        random.shuffle(ri.get("rounds", []))
    _fl_set_queue_and_notify(ri)
    show_fixed_lightning_list(update=True)
    _main.up_next_text()
    _main.play_video()


def _fixed_lightning_context_menu(index):
    """Show right-click context menu for a fixed lightning list item."""
    rounds_list = _main.fixed_lightning_rounds_list
    if index < 0 or index >= len(rounds_list):
        return

    round_info = rounds_list[index]

    def _do_queue_next(randomize=False):
        if randomize:
            _queue_fixed_lightning_round_by_index(index, randomize=True)
        else:
            # Mirror left-click toggle behaviour for non-randomized queue
            if _main.fixed_lightning_queue and _main.fixed_lightning_queue.get("name") == round_info.get("name"):
                _main.fixed_lightning_queue = None
                _main.toggle_coming_up_popup(False, round_info.get('name', 'Unnamed Round'))
                show_fixed_lightning_list(update=True)
                _main.up_next_text()
            else:
                _queue_fixed_lightning_round_by_index(index, randomize=False)

    def _do_play_now(randomize=False):
        _play_fixed_lightning_round_now(index, randomize=randomize)

    root = _main.root
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Play Now", command=lambda: _do_play_now(False))
    menu.add_command(label="Play Now (Randomized)", command=lambda: _do_play_now(True))
    menu.add_separator()
    menu.add_command(label="Queue Next", command=lambda: _do_queue_next(False))
    menu.add_command(label="Queue Next (Randomized)", command=lambda: _do_queue_next(True))

    try:
        menu.tk_popup(root.winfo_pointerx(), root.winfo_pointery())
    finally:
        menu.grab_release()


def show_fixed_lightning_list(update=False):
    """Show fixed lightning round playlists list in right column"""
    load_fixed_lightning_rounds(filter_missing_themes=True)

    rounds_list = _main.fixed_lightning_rounds_list
    rounds_dict = {i: round_info for i, round_info in enumerate(rounds_list)}

    def get_round_name(key, value):
        total_duration = value.get('total_duration', 0)
        minutes = int(total_duration // 60)
        seconds = int(total_duration % 60)
        duration_str = f"[{minutes}:{seconds:02d}] "
        name = _main.shorten_youtube_title(value.get("name", "Unnamed Round"))
        return duration_str + name

    selected = -1
    fl_queue = _main.fixed_lightning_queue
    if fl_queue:
        for i, round_info in enumerate(rounds_list):
            if round_info.get("name") == fl_queue.get("name"):
                selected = i
                break

    _main.show_list("fixed_lightning", _main.right_column, rounds_dict, get_round_name, queue_fixed_lightning_round, selected, update, right_click_func=_fixed_lightning_context_menu, title="FIXED LIGHTNING ROUND PLAYLISTS")


def queue_fixed_lightning_round(index):
    """Queue a selected fixed lightning round playlist"""
    rounds_list = _main.fixed_lightning_rounds_list

    if 0 <= index < len(rounds_list):
        round_info = rounds_list[index]
        name = round_info.get('name', 'Unnamed Round')
        if _main.fixed_lightning_queue == round_info:
            _main.fixed_lightning_queue = None
            _main.toggle_coming_up_popup(False, name)
        else:
            _main.fixed_lightning_queue = round_info

            desc = round_info.get('description')
            creator = round_info.get('creator')
            date_created = round_info.get("data").get('date_created', 'N/A').split(" ")[0]
            date_modified = round_info.get("data").get('date_modified', 'N/A').split(" ")[0]
            rounds_count = round_info.get('round_count', 0)
            total_duration = round_info.get('total_duration', 0)

            created_string = f"Created: {date_created}"
            if date_created != date_modified:
                created_string += f" (Modified: {date_modified})"

            # Format duration as minutes:seconds
            minutes = int(total_duration // 60)
            seconds = int(total_duration % 60)
            duration_str = f"{minutes}:{seconds:02d}"

            details_text = f"Created by: {creator}\n{created_string}\nRounds: {rounds_count} | Duration: {duration_str} mins\n\n{desc}"

            _main.toggle_coming_up_popup(True, f"{name}", details_text, queue=True)
            _main.queue_next_lightning_mode()

            # Prefetch themes from the queued playlist
            _main.prefetch_next_themes()

    show_fixed_lightning_list(update=True)
    _main.up_next_text()
