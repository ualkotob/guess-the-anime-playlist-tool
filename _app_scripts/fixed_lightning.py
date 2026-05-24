"""
Fixed Lightning Rounds — type definitions, field metadata, editor UI.
Extracted from guess_the_anime.py.
"""

import os
import re
import json
import copy
import random
import webbrowser
from datetime import datetime
from io import BytesIO
import tkinter as tk
from tkinter import ttk, messagebox

try:
    from PIL import Image, ImageTk
    import requests as _requests
except ImportError:
    Image = None
    ImageTk = None
    _requests = None

from core.game_state import state

# ---------------------------------------------------------------------------
# Context (injected by set_context at startup)
# ---------------------------------------------------------------------------
_BACKGROUND_COLOR = "gray12"
_HIGHLIGHT_COLOR = "#333"
_get_window_position_and_setup = None
_ToolTip = None
_get_clean_filename = None
_is_animethemes_stream_file = None
_get_title = None
_get_metadata = None
_get_display_title = None
_get_base_title = None
_play_video_from_filename = None
_player = None
_lightning_mode_settings_default = {}   # direct dict reference, set in set_context
# directory_files / playlist are read directly from state.metadata.*
# currently_playing, fl_rounds_list, lightning_mode_settings are read directly from state.playback.*
_play_video = None
_set_fl_queue = None                    # fn(v): sets main-file fixed_lightning_queue
_set_fl_round_playlist_data = None      # fn(v): sets main-file fixed_lightning_round_playlist_data
_show_fixed_lightning_list = None       # fn ref (stays in main)
_load_fixed_lightning_rounds = None     # fn ref (stays in main)
_open_image_popup = None
_stream_url = None
_load_music_files = None
# music_files is read directly from state.playback.music_files

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
last_selected_round_type = "regular"   # Track last selected round type for new rounds
_manager_window = None                 # Singleton manager window

# ---------------------------------------------------------------------------
# Fixed round type definitions
# ---------------------------------------------------------------------------

FIXED_LIGHTNING_ROUNDS = {
    "global": [
        "theme",
        "start_time",
        "duration",
        "answer_duration",
        "background_track"
    ],
    "blind": [
        "blind_header",
        "music_icon",
        "blind_variant"
    ],
    "clip": [
        "clip_header",
        "clip_start_time",
        "clip_url",
        "clip_title",
        "clip_author",
        "clip_source_as_song",
        "censor_bottom",
        "framed_video",
        "clip_for_answer",
        "clip_replay_for_answer",
        "volume_adjustment"
    ],
    "clues": [
    ],
    "cover": [
        "image_variant",
        "cover_fill",
        "image_url",
        "image_source",
        "cover_header",
        "slide_direction",
        "image_selected_area",
        "image_ending_area",
        "slice_count",
        "slice_vertical",
        "tile_grid_size"
    ],
    "episodes": [
        "episodes_header",
        "episode1",
        "episode2",
        "episode3",
        "episode4",
        "episode5",
        "episode6"
    ],
    "frame": [
        "frame1",
        "frame2",
        "frame3",
        "frame4",
        "test_frame",
        "test_frame",
        "test_frame",
        "test_frame"
    ],
    "image": [
        "image_variant",
        "image_url",
        "answer_image_url",
        "answer_show_both",
        "image_source",
        "image_header",
        "slide_direction",
        "image_selected_area",
        "image_ending_area",
        "slice_count",
        "slice_vertical",
        "tile_grid_size"
    ],
    "ost": [
        "ost_header",
        "clip_start_time",
        "clip_url",
        "clip_title",
        "clip_author",
        "clip_source_as_song",
        "framed_video",
        "clip_for_answer",
        "clip_replay_for_answer",
        "reveal_title_halfway",
        "music_icon",
        "volume_adjustment"
    ],
    "regular": [],
    "song": [
        "song_title_reveal_time",
        "song_artist_reveal_time",
        "song_slug_reveal_time",
        "song_music_reveal_time"
    ],
    "synopsis": [
        "synopsis_header",
        "synopsis_text",
        "overlay_during_answer",
        "reveal_speed"
    ],
    "title": [
        "title_header",
        "title_variant",
        "reveal_starting_count",
        "reveal_letter_order",
        "scramble_place_order"
        # "swap_groups"
    ],
    "trivia": [
        "trivia_header",
        "trivia_question",
        "overlay_during_answer",
        "reveal_speed",
        "answer_header",
        "trivia_answer",
        "mc_choice_2",
        "mc_choice_3",
        "mc_choice_4",
        "mc_points"
    ]
}

# Built lazily in set_context (some entries reference lightning_mode_settings_default)
FIXED_LIGHTNING_ROUND_FIELD_INDEX = {}

FIXED_LIGHTNING_FOLDER = "fixed_playlists"


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------

def set_context(
    background_color,
    highlight_color,
    get_window_position_and_setup,
    ToolTip,
    get_clean_filename,
    is_animethemes_stream_file,
    get_title,
    get_metadata,
    get_display_title,
    get_base_title,
    play_video_from_filename,
    player,
    lightning_mode_settings_default,
    play_video,
    set_fl_queue,
    set_fl_round_playlist_data,
    show_fixed_lightning_list,
    load_fixed_lightning_rounds,
    open_image_popup,
    stream_url,
    load_music_files,
):
    global _BACKGROUND_COLOR, _HIGHLIGHT_COLOR
    global _get_window_position_and_setup, _ToolTip
    global _get_clean_filename, _is_animethemes_stream_file
    global _get_title, _get_metadata, _get_display_title, _get_base_title
    global _play_video_from_filename, _player
    global _lightning_mode_settings_default
    global _play_video
    global _set_fl_queue, _set_fl_round_playlist_data
    global _show_fixed_lightning_list, _load_fixed_lightning_rounds
    global _open_image_popup, _stream_url, _load_music_files
    global FIXED_LIGHTNING_ROUND_FIELD_INDEX

    os.makedirs(FIXED_LIGHTNING_FOLDER, exist_ok=True)

    _BACKGROUND_COLOR = background_color
    _HIGHLIGHT_COLOR = highlight_color
    _get_window_position_and_setup = get_window_position_and_setup
    _ToolTip = ToolTip
    _get_clean_filename = get_clean_filename
    _is_animethemes_stream_file = is_animethemes_stream_file
    _get_title = get_title
    _get_metadata = get_metadata
    _get_display_title = get_display_title
    _get_base_title = get_base_title
    _play_video_from_filename = play_video_from_filename
    _player = player
    _lightning_mode_settings_default = lightning_mode_settings_default
    _play_video = play_video
    _set_fl_queue = set_fl_queue
    _set_fl_round_playlist_data = set_fl_round_playlist_data
    _show_fixed_lightning_list = show_fixed_lightning_list
    _load_fixed_lightning_rounds = load_fixed_lightning_rounds
    _open_image_popup = open_image_popup
    _stream_url = stream_url
    _load_music_files = load_music_files

    lmd = lightning_mode_settings_default
    FIXED_LIGHTNING_ROUND_FIELD_INDEX = {
        # Optional metadata per field:
        # tooltip: Hover text shown on the field label in the fixed-round editor.
        "theme": {"type": "file", "required": True, "tooltip": "Theme filename used for this round. Use SET TO CURRENT to capture the currently playing theme."},
        "start_time": {"type": "time", "required": False, "tooltip": "Start timestamp in seconds for the round theme. In rounds that don't use theme during the question, this is when the theme will start during the answer phase."},
        "duration": {"type": "duration", "required": False, "tooltip": "Main guessing duration in seconds before answer phase begins. Use CALC FROM NOW to automatically calculate based on current theme position from start_time."},
        "answer_duration": {"type": "duration", "required": False, "tooltip": "Answer reveal duration in seconds. Use CALC FROM NOW to automatically calculate based on current theme position from start_time."},
        "background_track": {"type": "music_track", "required": False, "show_if_muted": True, "tooltip": "Optional background music file to play for muted rounds. Will choose a random track each time if left empty."},
        "blind_variant": {"type": "dropdown", "required": False, "options": lmd.get("blind", {}).get("variants", {}), "default": "standard", "tooltip": "Blind round variant behavior (for example standard, one-second, mismatch, etc.)."},
        "frame1": {"type": "time", "required": True, "tooltip": "First frame timestamp in seconds."},
        "frame2": {"type": "time", "required": True, "tooltip": "Second frame timestamp in seconds."},
        "frame3": {"type": "time", "required": True, "tooltip": "Third frame timestamp in seconds."},
        "frame4": {"type": "time", "required": True, "tooltip": "Fourth frame timestamp in seconds."},
        "test_frame": {"type": "time", "required": False, "tooltip": "Extra frame timestamp fields to hold more frames for convenience when picking frames. Not used in actual rounds, just for creation/testing."},
        "synopsis_header": {"type": "text", "required": False, "default": "Synopsis", "tooltip": "Header text shown above the synopsis overlay."},
        "synopsis_text": {"type": "textarea", "required": True, "height": 10, "tooltip": "Synopsis body text revealed during the round."},
        "overlay_during_answer": {"type": "toggle", "required": False, "default": False, "tooltip": "Keep the synopsis/trivia overlay visible during answer phase."},
        "reveal_speed": {"type": "time", "required": False, "default": None, "tooltip": "Word reveal speed in seconds for synopsis/trivia text overlays. The text will be fully revealed at the timestamp entered here."},
        "answer_header": {"type": "text", "required": False, "tooltip": "Optional answer header text shown in trivia answer phase."},
        "trivia_header": {"type": "text", "required": False, "default": "Trivia", "tooltip": "Header text shown above the trivia question."},
        "trivia_question": {"type": "textarea", "required": True, "height": 10, "tooltip": "Trivia prompt shown during the question phase."},
        "trivia_answer": {"type": "text", "required": True, "tooltip": "Correct answer text for the trivia round."},
        "mc_choice_2": {"type": "text", "required": False, "tooltip": "Optional multiple-choice distractor option #2."},
        "mc_choice_3": {"type": "text", "required": False, "tooltip": "Optional multiple-choice distractor option #3."},
        "mc_choice_4": {"type": "text", "required": False, "tooltip": "Optional multiple-choice distractor option #4."},
        "mc_points": {"type": "integer", "required": False, "default": 1, "tooltip": "Points awarded for a correct trivia answer."},
        "clip_header": {"type": "text", "required": False, "default": "Random Clip", "tooltip": "Overlay header text for clip rounds."},
        "ost_header": {"type": "text", "required": False, "default": "SOUNDTRACK / OST", "tooltip": "Overlay header text for OST rounds."},
        "clip_start_time": {"type": "time", "required": False, "tooltip": "Start timestamp in seconds for the clip/OST URL."},
        "clip_url": {"type": "video_url", "required": True, "tooltip": "Direct video URL used in clip/OST rounds. GO TO URL opens browser, STREAM previews in player."},
        "clip_title": {"type": "text", "required": False, "tooltip": "Display title for the clip source."},
        "clip_author": {"type": "text", "required": False, "tooltip": "Display channel/author for the clip source."},
        "censor_bottom": {"type": "toggle", "required": False, "default": False, "tooltip": "Apply bottom censor behavior during clip playback."},
        "framed_video": {"type": "toggle", "required": False, "default": None, "tooltip": "Show clip/OST inside the framed video border. Overrides the global framed_video_clip setting for clip rounds. Defaults to off for OST rounds."},
        "clip_source_as_song": {"type": "toggle", "required": False, "default": False, "tooltip": "Show clip title and author as song name and artist in the info popup instead of the stored song metadata."},
        "clip_for_answer": {"type": "toggle", "required": False, "default": False, "tooltip": "Reuse the clip media during answer phase instead of the normal answer flow. Enable Replay to seek back to clip_start_time when the answer phase begins."},
        "clip_replay_for_answer": {"type": "toggle", "required": False, "default": False, "group_with_previous": True, "show_if": {"clip_for_answer": [True]}, "tooltip": "When clip_for_answer is active, seek back to clip_start_time (or the beginning) when the answer phase starts, replaying the clip from the top."},
        "reveal_title_halfway": {"type": "toggle", "required": False, "default": True, "tooltip": "Reveal the title halfway through the OST round."},
        "blind_header": {"type": "text", "required": False, "default": "", "tooltip": "Header text for blind rounds."},
        "music_icon": {"type": "text", "required": False, "tooltip": "Custom icon/text shown on music progress overlays."},
        "volume_adjustment": {"type": "integer", "required": False, "default": 0, "tooltip": "Per-round volume offset applied during clip/OST playback."},
        # Image round fields
        "image_variant": {
            "type": "dropdown",
            "required": True,
            "options": lmd.get("image", {}).get("variants", {}),
            "default": "standard",
            "tooltip": "Reveal style for image/cover rounds (standard, slide, slice, tile, zoom, etc.)."
        },
        "image_url": {"type": "image_url", "required": True, "tooltip": "Primary image URL used by image/cover reveal rounds."},
        "answer_image_url": {"type": "image_url", "required": False, "tooltip": "Optional alternate image URL shown for answer phase."},
        "answer_show_both": {"type": "toggle", "required": False, "default": False, "tooltip": "If enabled, answer view can show both round and answer images."},
        "cover_fill": {"type": "cover_fill", "required": False, "tooltip": "Helper button that fills Image URL from the selected theme's cover metadata."},
        "cover_header": {"type": "text", "required": False, "default": "Cover", "tooltip": "Header text for cover rounds."},
        "image_source": {"type": "text", "required": False, "tooltip": "Optional source/credit line shown for the image."},
        "image_header": {"type": "text", "required": False, "default": "Image", "tooltip": "Header text for image rounds."},
        # Reveal-specific fields
        "slide_direction": {
            "type": "dropdown",
            "required": False,
            "options": {"top": "Top", "bottom": "Bottom", "left": "Left", "right": "Right"},
            "default": "top",
            "show_if": {"image_variant": ["slide"]},
            "tooltip": "Direction the slide reveal moves from."
        },
        # Zoom-specific fields
        "image_selected_area": {
            "type": "area_selector",
            "required": False,
            "default": None,
            "show_if": {"image_variant": ["zoom"]},
            "tooltip": "Starting crop area for zoom reveal. Click SELECT AREA and drag on the image."
        },
        "image_ending_area": {
            "type": "area_selector",
            "required": False,
            "default": None,
            "show_if": {"image_variant": ["zoom"]},
            "tooltip": "Ending crop area for zoom reveal. Used to control where zoom-out finishes."
        },
        # Slice-specific fields
        "slice_count": {
            "type": "integer",
            "required": False,
            "default": 10,
            "show_if": {"image_variant": ["slice"]},
            "tooltip": "Number of slices used by slice variant. Higher values create thinner slices."
        },
        "slice_vertical": {
            "type": "toggle",
            "required": False,
            "default": True,
            "show_if": {"image_variant": ["slice"]},
            "tooltip": "Slice orientation for slice variant. On = vertical slices, Off = horizontal slices."
        },
        # Tile-specific fields
        "tile_grid_size": {
            "type": "integer",
            "required": False,
            "default": 4,
            "show_if": {"image_variant": ["tile"]},
            "tooltip": "Grid dimension for tile variant (for example 4 means 4x4 tiles)."
        },
        "song_title_reveal_time": {"type": "time", "required": False, "tooltip": "Seconds from round start when song title is revealed."},
        "song_artist_reveal_time": {"type": "time", "required": False, "tooltip": "Seconds from round start when artist name is revealed."},
        "song_slug_reveal_time": {"type": "time", "required": False, "tooltip": "Seconds from round start when OP/ED slug info is revealed."},
        "song_music_reveal_time": {"type": "time", "required": False, "tooltip": "Seconds from round start when the music snippet reveal begins."},
        "episodes_header": {"type": "text", "required": False, "default": "Episode Titles", "tooltip": "Header text shown above episode title clues."},
        "episode1": {"type": "text", "required": True, "tooltip": "First episode title clue (required)."},
        "episode2": {"type": "text", "required": False, "tooltip": "Second episode title clue."},
        "episode3": {"type": "text", "required": False, "tooltip": "Third episode title clue."},
        "episode4": {"type": "text", "required": False, "tooltip": "Fourth episode title clue."},
        "episode5": {"type": "text", "required": False, "tooltip": "Fifth episode title clue."},
        "episode6": {"type": "text", "required": False, "tooltip": "Sixth episode title clue."},
        "title_variant": {
            "type": "dropdown",
            "required": True,
            "options": lmd.get("title", {}).get("variants", {}),
            "default": "reveal",
            "tooltip": "Title round mode (reveal, scramble, or swap)."
        },
        "title_header": {"type": "text", "required": False, "default": "MUST SAY FULL TITLE", "tooltip": "Header text shown for title rounds."},
        "reveal_starting_count": {"type": "integer", "required": False, "default": 0, "show_if": {"title_variant": ["reveal"]}, "tooltip": "How many letters are shown immediately at the start of reveal mode."},
        "reveal_letter_order": {"type": "letter_select", "required": False, "show_if": {"title_variant": ["reveal"]}, "tooltip": "Custom sequence of letters to reveal in reveal mode. Use SELECT LETTERS."},
        "scramble_place_order": {"type": "letter_order_select", "required": False, "show_if": {"title_variant": ["scramble"]}, "tooltip": "Placement order for letters in scramble mode. Use SELECT ORDER to define it."},
        "swap_groups": {"type": "text", "required": False, "show_if": {"title_variant": ["swap"]}, "tooltip": "Optional swap grouping/config text for swap variant behavior."}
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def should_show_field(field_name, round_data):
    """Check if a field should be shown based on show_if conditions"""
    field_config = FIXED_LIGHTNING_ROUND_FIELD_INDEX.get(field_name, {})

    # show_if_muted: only show when the round type is a muted round
    # Exclude ost/clip since they already have their own audio source
    _NO_BG_TRACK_TYPES = {"ost", "clip"}
    if field_config.get("show_if_muted"):
        round_type = round_data.get("type", "")
        if not state.playback.lightning_mode_settings.get(round_type, {}).get("muted"):
            return False
        if round_type in _NO_BG_TRACK_TYPES:
            return False

    show_if = field_config.get("show_if")

    if not show_if:
        return True  # No condition, always show

    # show_if format: {"field_name": ["value1", "value2", ...]}
    for condition_field, valid_values in show_if.items():
        current_value = round_data.get(condition_field)
        if current_value is None:
            # Fall back to the field's declared default so new rounds respect defaults
            current_value = FIXED_LIGHTNING_ROUND_FIELD_INDEX.get(condition_field, {}).get("default")
        if current_value not in valid_values:
            return False

    return True


# ---------------------------------------------------------------------------
# Manager window
# ---------------------------------------------------------------------------

def open_fixed_lightning_manager():
    """Open the fixed lightning round playlists manager window"""
    global _manager_window

    def manager_close():
        global _manager_window
        _manager_window.destroy()
        _manager_window = None

    if _manager_window:
        manager_close()
        return

    # Create new window
    _manager_window = tk.Toplevel()
    _manager_window.title("Fixed Lightning Round Playlists Manager")
    _manager_window.configure(bg=_BACKGROUND_COLOR)
    _manager_window.geometry("600x400")
    _get_window_position_and_setup(_manager_window)

    _manager_window.protocol("WM_DELETE_WINDOW", manager_close)

    font_big = ("Arial", 12)
    font_button = ("Arial", 10, "bold")
    fg_color = "white"

    selected_round = [None]  # Use list to allow modification in nested functions

    def refresh_ui():
        """Refresh the manager UI"""
        # Clear existing widgets
        for widget in _manager_window.winfo_children():
            widget.destroy()

        # Reload rounds
        _load_fixed_lightning_rounds()

        # Main container
        main_frame = tk.Frame(_manager_window, bg=_BACKGROUND_COLOR)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left side - List of rounds
        left_frame = tk.Frame(main_frame, bg=_BACKGROUND_COLOR)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Listbox with scrollbar
        list_scroll_frame = tk.Frame(left_frame, bg=_BACKGROUND_COLOR)
        list_scroll_frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_scroll_frame)
        scrollbar.pack(side="right", fill="y")

        rounds_listbox = tk.Listbox(list_scroll_frame, bg="black", fg=fg_color, font=font_big,
                                    selectbackground=_HIGHLIGHT_COLOR, yscrollcommand=scrollbar.set)
        rounds_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=rounds_listbox.yview)

        for round_info in state.playback.fl_rounds_list:
            rounds_listbox.insert(tk.END, round_info['name'])
            has_missing = False
            for rnd in round_info['data'].get('rounds', []):
                theme = rnd.get('theme', '')
                clean_theme = _get_clean_filename(theme)
                if theme and clean_theme not in state.metadata.directory_files and not _is_animethemes_stream_file(theme):
                    has_missing = True
                    break
            if has_missing:
                idx = rounds_listbox.size() - 1
                rounds_listbox.itemconfig(idx, fg='red')

        # Details panel (bottom of left side)
        details_frame = tk.Frame(left_frame, bg="black", relief="ridge", bd=2)
        details_frame.pack(fill="x", pady=(10, 0))

        details_label = tk.Label(details_frame, text="Select a round to view details",
                                font=("Arial", 9), bg="black", fg=fg_color,
                                justify="left", anchor="w", wraplength=280)
        details_label.pack(fill="x", padx=5, pady=5)

        def on_select(event):
            """Handle round selection"""
            selection = rounds_listbox.curselection()
            if selection:
                idx = selection[0]
                selected_round[0] = idx
                round_info = state.playback.fl_rounds_list[idx]

                # Update details
                data = round_info['data']
                desc = data.get('description', 'No description')
                creator = data.get('creator', 'Unknown')
                date_created = data.get('date_created', 'N/A')
                date_modified = data.get('date_modified', 'N/A')
                rounds_count = round_info.get('round_count', 0)
                total_duration = round_info.get('total_duration', 0)

                # Format duration as minutes:seconds
                minutes = int(total_duration // 60)
                seconds = int(total_duration % 60)
                duration_str = f"{minutes}:{seconds:02d}"

                details_text = f"Name: {round_info['name']}\nCreator: {creator}\nRounds: {rounds_count}\nTotal Duration: {duration_str}\nCreated: {date_created}\nModified: {date_modified}\n\n{desc}"
                details_label.config(text=details_text)

        rounds_listbox.bind('<<ListboxSelect>>', on_select)

        def on_double_click(event):
            """Handle double-click to open edit rounds menu"""
            selection = rounds_listbox.curselection()
            if selection:
                selected_round[0] = selection[0]
                edit_round()

        rounds_listbox.bind('<Double-Button-1>', on_double_click)

        # Right side - Action buttons
        right_frame = tk.Frame(main_frame, bg=_BACKGROUND_COLOR)
        right_frame.pack(side="right", fill="y")

        def show_metadata_dialog(title="New Fixed Round", existing_data=None):
            """Show dialog to enter/edit metadata (name, description, creator)"""
            dialog = tk.Toplevel(_manager_window)
            dialog.title(title)
            dialog.configure(bg=_BACKGROUND_COLOR)
            dialog.transient(_manager_window)
            dialog.grab_set()

            # Center on parent
            dialog.update_idletasks()
            x = _manager_window.winfo_x() + 50
            y = _manager_window.winfo_y() + 50
            dialog.geometry(f"400x300+{x}+{y}")

            result = {}

            # Name
            tk.Label(dialog, text="Name:", font=("Arial", 10), bg=_BACKGROUND_COLOR, fg="white").pack(pady=(10, 0), padx=10, anchor="w")
            name_entry = tk.Entry(dialog, font=("Arial", 10), bg="black", fg="white", width=45, insertbackground="white")
            name_entry.pack(pady=(0, 10), padx=10)
            if existing_data:
                name_entry.insert(0, existing_data.get('name', ''))

            # Description
            tk.Label(dialog, text="Description:", font=("Arial", 10), bg=_BACKGROUND_COLOR, fg="white").pack(pady=(0, 0), padx=10, anchor="w")
            desc_text = tk.Text(dialog, font=("Arial", 10), bg="black", fg="white", width=45, height=5, insertbackground="white")
            desc_text.pack(pady=(0, 10), padx=10)
            if existing_data:
                desc_text.insert("1.0", existing_data.get('description', ''))

            # Creator
            tk.Label(dialog, text="Creator:", font=("Arial", 10), bg=_BACKGROUND_COLOR, fg="white").pack(pady=(0, 0), padx=10, anchor="w")
            creator_entry = tk.Entry(dialog, font=("Arial", 10), bg="black", fg="white", width=45, insertbackground="white")
            creator_entry.pack(pady=(0, 10), padx=10)
            if existing_data:
                creator_entry.insert(0, existing_data.get('creator', ''))

            # Buttons
            button_frame = tk.Frame(dialog, bg=_BACKGROUND_COLOR)
            button_frame.pack(pady=10)

            def on_ok():
                result['name'] = name_entry.get().strip()
                result['description'] = desc_text.get("1.0", "end-1c").strip()
                result['creator'] = creator_entry.get().strip()
                result['confirmed'] = True
                dialog.destroy()

            def on_cancel():
                result['confirmed'] = False
                dialog.destroy()

            ok_btn = tk.Button(button_frame, text="OK", font=("Arial", 10, "bold"), bg="black", fg="white", command=on_ok, width=10)
            ok_btn.pack(side="left", padx=5)

            cancel_btn = tk.Button(button_frame, text="Cancel", font=("Arial", 10, "bold"), bg="black", fg="white", command=on_cancel, width=10)
            cancel_btn.pack(side="left", padx=5)

            # Focus name field
            name_entry.focus_set()

            dialog.wait_window()

            return result

        def add_new_round():
            """Add a new fixed lightning round playlist"""
            # Show metadata dialog
            metadata = show_metadata_dialog("New Fixed Round")

            if not metadata.get('confirmed'):
                return

            name = metadata.get('name', '')
            if not name:
                messagebox.showwarning("Invalid Name", "Round name cannot be empty.")
                return

            if any(r['name'].lower() == name.lower() for r in state.playback.fl_rounds_list):
                messagebox.showwarning("Duplicate Name", "A round with this name already exists.")
                return

            description = metadata.get('description', '')
            creator = metadata.get('creator', '')

            # Create filename (sanitize)
            filename = re.sub(r'[^a-z0-9_]', '', name.lower().replace(' ', '_'))
            if not filename:
                filename = "round"
            filename = f"{filename}.json"

            filepath = os.path.join(FIXED_LIGHTNING_FOLDER, filename)

            if os.path.exists(filepath):
                messagebox.showwarning("File Exists", "A round file with this name already exists.")
                return

            # Create JSON structure with metadata
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            round_data = {
                "name": name,
                "description": description,
                "creator": creator,
                "date_created": now,
                "date_modified": now,
                "rounds": []
            }

            # Save to file
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(round_data, f, indent=4)
                refresh_ui()
                # Refresh the main list
                _show_fixed_lightning_list(update=True)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create round: {e}")

        def edit_metadata():
            """Edit metadata for selected round"""
            if selected_round[0] is None:
                messagebox.showwarning("No Selection", "Please select a round to edit.")
                return

            round_info = state.playback.fl_rounds_list[selected_round[0]]

            # Show metadata dialog with existing data
            metadata = show_metadata_dialog("Edit Metadata", round_info['data'])

            if not metadata.get('confirmed'):
                return

            name = metadata.get('name', '')
            if not name:
                messagebox.showwarning("Invalid Name", "Round name cannot be empty.")
                return

            if any(r['name'].lower() == name.lower() and r['filepath'] != round_info['filepath']
                   for r in state.playback.fl_rounds_list):
                messagebox.showwarning("Duplicate Name", "A round with this name already exists.")
                return

            # Update metadata
            _old_name = round_info['data'].get('name', '')
            _old_desc = round_info['data'].get('description', '')
            _old_creator = round_info['data'].get('creator', '')
            round_info['data']['name'] = name
            round_info['data']['description'] = metadata.get('description', '')
            round_info['data']['creator'] = metadata.get('creator', '')
            if (round_info['data']['name'] != _old_name or
                round_info['data']['description'] != _old_desc or
                round_info['data']['creator'] != _old_creator):
                round_info['data']['date_modified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            old_filepath = round_info['filepath']
            expected_filename = f"{name}.json"
            new_filepath = os.path.join(FIXED_LIGHTNING_FOLDER, expected_filename)

            # Save to file
            try:
                # If name changed and new file doesn't exist, rename
                if old_filepath != new_filepath:
                    if os.path.exists(new_filepath):
                        messagebox.showwarning("File Exists", f"Cannot rename: {expected_filename} already exists.")
                        return
                    # Save to new location and delete old file
                    with open(new_filepath, 'w', encoding='utf-8') as f:
                        json.dump(round_info['data'], f, indent=4)
                    os.remove(old_filepath)
                    round_info['filepath'] = new_filepath
                else:
                    # Just save to existing file
                    with open(round_info['filepath'], 'w', encoding='utf-8') as f:
                        json.dump(round_info['data'], f, indent=4)

                refresh_ui()
                _show_fixed_lightning_list(update=True)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update metadata: {e}")

        def edit_round():
            """Edit the selected round"""
            if selected_round[0] is None:
                messagebox.showwarning("No Selection", "Please select a round to edit.")
                return

            # Get manager window position
            _manager_window.update_idletasks()
            x = _manager_window.winfo_x()
            y = _manager_window.winfo_y()

            # Hide manager and open editor at same position
            _manager_window.withdraw()
            round_info = state.playback.fl_rounds_list[selected_round[0]]
            open_round_editor(round_info, _manager_window, (x, y))

        def delete_round():
            """Delete the selected round"""
            if selected_round[0] is None:
                messagebox.showwarning("No Selection", "Please select a round to delete.")
                return

            round_info = state.playback.fl_rounds_list[selected_round[0]]

            # Confirm deletion
            result = messagebox.askyesno("Confirm Delete",
                                        f"Are you sure you want to delete '{round_info['name']}'?\n\nThis cannot be undone.",
                                        parent=_manager_window)
            if not result:
                return

            # Delete file
            try:
                os.remove(round_info['filepath'])
                selected_round[0] = None
                refresh_ui()
                # Refresh the main list
                _show_fixed_lightning_list(update=True)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete round: {e}")

        # Action buttons
        add_button = tk.Button(right_frame, text="NEW PLAYLIST", font=font_button, bg="black", fg="white",
                              command=add_new_round, width=18, pady=10)
        add_button.pack(pady=(0, 10))

        edit_meta_button = tk.Button(right_frame, text="EDIT METADATA", font=font_button, bg="black", fg="white",
                               command=edit_metadata, width=18, pady=10)
        edit_meta_button.pack(pady=(0, 10))

        edit_button = tk.Button(right_frame, text="EDIT ROUNDS", font=font_button, bg="black", fg="white",
                               command=edit_round, width=18, pady=10)
        edit_button.pack(pady=(0, 10))

        delete_button = tk.Button(right_frame, text="DELETE", font=font_button, bg="black", fg="white",
                                  command=delete_round, width=18, pady=10)
        delete_button.pack(pady=(0, 10))

    # Initial UI load
    refresh_ui()


# ---------------------------------------------------------------------------
# Round editor
# ---------------------------------------------------------------------------

def open_round_editor(round_info, manager_window=None, position=None):
    """Open the round editor for a specific fixed lightning round playlist"""
    editor_window = tk.Toplevel()
    editor_window.title(f"Edit Playlist: {round_info['name']}")
    editor_window.configure(bg=_BACKGROUND_COLOR)
    editor_window.geometry("700x500")

    if position:
        editor_window.geometry(f"+{position[0]}+{position[1]}")

    def on_close():
        editor_window.destroy()
        if manager_window:
            manager_window.deiconify()

    editor_window.protocol("WM_DELETE_WINDOW", on_close)

    font_big = ("Arial", 12)
    font_button = ("Arial", 10, "bold")
    fg_color = "white"

    selected_round_index = [None]
    _saved_rounds_snapshot = json.dumps(round_info['data'].get('rounds', []), sort_keys=True)

    def save_rounds():
        """Save changes to the JSON file"""
        try:
            nonlocal _saved_rounds_snapshot
            _current_snapshot = json.dumps(round_info['data'].get('rounds', []), sort_keys=True)
            if _current_snapshot != _saved_rounds_snapshot:
                round_info['data']['date_modified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                _saved_rounds_snapshot = _current_snapshot

            with open(round_info['filepath'], 'w', encoding='utf-8') as f:
                json.dump(round_info['data'], f, indent=4)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def refresh_editor():
        """Refresh the editor UI"""
        for widget in editor_window.winfo_children():
            widget.destroy()

        # Main container
        main_frame = tk.Frame(editor_window, bg=_BACKGROUND_COLOR)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left side - List of rounds within this fixed round
        left_frame = tk.Frame(main_frame, bg=_BACKGROUND_COLOR)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        list_label = tk.Label(left_frame, text=f"Rounds in '{round_info['name']}'",
                             font=font_big, bg=_BACKGROUND_COLOR, fg=fg_color)
        list_label.pack(pady=(0, 5))

        # Listbox with scrollbar
        list_scroll_frame = tk.Frame(left_frame, bg=_BACKGROUND_COLOR)
        list_scroll_frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_scroll_frame)
        scrollbar.pack(side="right", fill="y")

        rounds_listbox = tk.Listbox(list_scroll_frame, bg="black", fg=fg_color, font=("Arial", 10),
                                    selectbackground=_HIGHLIGHT_COLOR, yscrollcommand=scrollbar.set)
        rounds_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=rounds_listbox.yview)

        rounds = round_info['data'].get('rounds', [])
        for i, rnd in enumerate(rounds):
            rnd_type = rnd.get('type', 'unknown').upper()
            rnd_theme = rnd.get('theme', 'No theme')
            display_name = _get_title(rnd_theme, rnd_theme)
            if len(display_name) > 50:
                display_name = display_name[:47] + "..."
            rounds_listbox.insert(tk.END, f"{i+1}. [{rnd_type}] {display_name}")
            clean_theme = _get_clean_filename(rnd_theme)
            if rnd_theme and clean_theme not in state.metadata.directory_files and not _is_animethemes_stream_file(rnd_theme):
                rounds_listbox.itemconfig(i, fg='red')

        # Details panel
        details_frame = tk.Frame(left_frame, bg="black", relief="ridge", bd=2)
        details_frame.pack(fill="x", pady=(10, 0))

        details_label = tk.Label(details_frame, text="Select a round to view details",
                                font=("Arial", 9), bg="black", fg=fg_color,
                                justify="left", anchor="w", wraplength=350)
        details_label.pack(fill="x", padx=5, pady=5)

        def on_select(event):
            """Handle round selection"""
            selection = rounds_listbox.curselection()
            if selection:
                idx = selection[0]
                selected_round_index[0] = idx
                rnd = rounds[idx]

                # Build details string
                details_lines = [f"Type: {rnd.get('type', 'unknown')}"]
                details_lines.append(f"Filename: {rnd.get('theme', 'N/A')}")

                if 'start_time' in rnd and rnd['start_time']:
                    details_lines.append(f"Start: {rnd['start_time']}s")
                if 'duration' in rnd and rnd['duration']:
                    details_lines.append(f"Duration: {rnd['duration']}s")
                if 'answer_duration' in rnd and rnd['answer_duration']:
                    details_lines.append(f"Answer: {rnd['answer_duration']}s")

                # Type-specific fields
                if rnd.get('type') == 'blind' and 'blind_variant' in rnd:
                    details_lines.append(f"Variant: {rnd['blind_variant']}")
                elif rnd.get('type') == 'frame':
                    frames = [f"{k}: {v}s" for k, v in rnd.items() if k.startswith('frame')]
                    if frames:
                        details_lines.append("Frames: " + ", ".join(frames))

                details_label.config(text="\n".join(details_lines))

        rounds_listbox.bind('<<ListboxSelect>>', on_select)

        def on_double_click(event):
            """Handle double-click to open field editor"""
            selection = rounds_listbox.curselection()
            if selection:
                selected_round_index[0] = selection[0]
                edit_selected_round()

        rounds_listbox.bind('<Double-Button-1>', on_double_click)

        if selected_round_index[0] is not None and selected_round_index[0] < len(rounds):
            rounds_listbox.selection_set(selected_round_index[0])
            scroll_to_index = max(0, selected_round_index[0] - 5)
            rounds_listbox.see(scroll_to_index)
            # Trigger the selection event to update details
            rounds_listbox.event_generate('<<ListboxSelect>>')

        # Right side - Action buttons
        right_frame = tk.Frame(main_frame, bg=_BACKGROUND_COLOR)
        right_frame.pack(side="right", fill="y")

        def add_round():
            """Add a new round to this fixed lightning round playlist"""
            # Get editor window position
            editor_window.update_idletasks()
            x = editor_window.winfo_x()
            y = editor_window.winfo_y()

            # Close editor and open field editor at same position
            editor_window.withdraw()
            open_round_field_editor(round_info, None, refresh_editor, editor_window, (x, y))

        def edit_selected_round():
            """Edit the selected round"""
            if selected_round_index[0] is None:
                messagebox.showwarning("No Selection", "Please select a round to edit.")
                return

            # Get editor window position before closing
            editor_window.update_idletasks()
            x = editor_window.winfo_x()
            y = editor_window.winfo_y()

            # Close editor and open field editor at same position
            editor_window.withdraw()
            open_round_field_editor(round_info, selected_round_index[0], refresh_editor, editor_window, (x, y))

        def delete_selected_round():
            """Delete the selected round"""
            if selected_round_index[0] is None:
                messagebox.showwarning("No Selection", "Please select a round to delete.")
                return

            result = messagebox.askyesno("Confirm Delete",
                                        "Are you sure you want to delete this round?",
                                        parent=editor_window)
            if result:
                del round_info['data']['rounds'][selected_round_index[0]]
                save_rounds()
                selected_round_index[0] = None
                refresh_editor()

        def move_up():
            """Move selected round up"""
            if selected_round_index[0] is None or selected_round_index[0] == 0:
                return
            idx = selected_round_index[0]
            rounds[idx], rounds[idx-1] = rounds[idx-1], rounds[idx]
            selected_round_index[0] = idx - 1
            save_rounds()
            refresh_editor()

        def move_down():
            """Move selected round down"""
            if selected_round_index[0] is None or selected_round_index[0] >= len(rounds) - 1:
                return
            idx = selected_round_index[0]
            rounds[idx], rounds[idx+1] = rounds[idx+1], rounds[idx]
            selected_round_index[0] = idx + 1
            save_rounds()
            refresh_editor()

        def randomize_rounds():
            """Randomize the order of all rounds"""
            if not rounds:
                return
            result = messagebox.askyesno("Confirm Randomize",
                                        "Are you sure you want to randomize the order of all rounds?",
                                        parent=editor_window)
            if result:
                random.shuffle(rounds)
                selected_round_index[0] = None
                save_rounds()
                refresh_editor()

        def clone_and_edit_round():
            """Clone the selected round and open it for editing"""
            if selected_round_index[0] is None:
                messagebox.showwarning("No Selection", "Please select a round to clone.")
                return

            # Clone the selected round
            cloned_round = copy.deepcopy(rounds[selected_round_index[0]])
            rounds.append(cloned_round)
            save_rounds()

            # Get editor window position before closing
            editor_window.update_idletasks()
            x = editor_window.winfo_x()
            y = editor_window.winfo_y()

            new_index = len(rounds) - 1
            editor_window.withdraw()
            open_round_field_editor(round_info, new_index, refresh_editor, editor_window, (x, y))

        # Action buttons
        add_button = tk.Button(right_frame, text="ADD ROUND", font=font_button, bg="black", fg="white",
                              command=add_round, width=15, pady=8)
        add_button.pack(pady=(0, 8))

        clone_edit_button = tk.Button(right_frame, text="CLONE & EDIT", font=font_button, bg="black", fg="white",
                                      command=clone_and_edit_round, width=15, pady=8)
        clone_edit_button.pack(pady=(0, 8))

        edit_button = tk.Button(right_frame, text="EDIT", font=font_button, bg="black", fg="white",
                               command=edit_selected_round, width=15, pady=8)
        edit_button.pack(pady=(0, 8))

        delete_button = tk.Button(right_frame, text="DELETE", font=font_button, bg="black", fg="white",
                                  command=delete_selected_round, width=15, pady=8)
        delete_button.pack(pady=(0, 8))

        tk.Frame(right_frame, bg=_BACKGROUND_COLOR, height=10).pack()

        up_button = tk.Button(right_frame, text="▲ MOVE UP", font=font_button, bg="black", fg="white",
                             command=move_up, width=15, pady=8)
        up_button.pack(pady=(0, 8))

        down_button = tk.Button(right_frame, text="▼ MOVE DOWN", font=font_button, bg="black", fg="white",
                               command=move_down, width=15, pady=8)
        down_button.pack(pady=(0, 8))

        randomize_button = tk.Button(right_frame, text="🎲 RANDOMIZE", font=font_button, bg="black", fg="white",
                                     command=randomize_rounds, width=15, pady=8)
        randomize_button.pack(pady=(0, 8))

        tk.Frame(right_frame, bg=_BACKGROUND_COLOR, height=20).pack()

        save_button = tk.Button(right_frame, text="SAVE", font=font_button, bg="black", fg="white",
                               command=save_rounds, width=15, pady=8)
        save_button.pack(pady=(0, 8))

        def close_and_return():
            """Close editor and return to manager"""
            editor_window.destroy()
            if manager_window and manager_window.winfo_exists():
                manager_window.deiconify()

        def save_and_return():
            """Save changes and return to manager"""
            save_rounds()
            close_and_return()

        save_return_button = tk.Button(right_frame, text="SAVE & RETURN", font=font_button, bg="black", fg="white",
                                      command=save_and_return, width=15, pady=8)
        save_return_button.pack(pady=(0, 8))

        close_button = tk.Button(right_frame, text="RETURN", font=font_button, bg="black", fg="white",
                                command=close_and_return, width=15, pady=8)
        close_button.pack(pady=(0, 8))

    refresh_editor()


# ---------------------------------------------------------------------------
# Letter order selector
# ---------------------------------------------------------------------------

def open_letter_order_selector(title_text, target_entry, parent=None, mode="index"):
    """
    Popup that lets you click letters in a title to define a letter-based field.
    mode="index"  → outputs comma-separated 0-based indices: "3,6,2,7"  (scramble_place_order)
    mode="letter" → outputs comma-separated characters:      "n,a,r,u"  (reveal_letter_order / reveal_starting_letters)
    """
    # Strip spaces to get the indexed characters (matching how scramble/reveal works)
    stripped = title_text.replace(" ", "")

    popup = tk.Toplevel(parent)
    popup.title("Select Letter Order" if mode == "index" else "Select Letters")
    popup.configure(bg=_BACKGROUND_COLOR)
    popup.resizable(False, False)
    if parent:
        popup.geometry(f"+{parent.winfo_x()+40}+{parent.winfo_y()+40}")
    popup.grab_set()

    tk.Label(popup, text="Click letters in the order you want them revealed.\nClick again to deselect.",
             font=("Arial", 10), bg=_BACKGROUND_COLOR, fg="white", justify="center").pack(pady=(10, 5))

    # Track selection order:
    #   mode="index"  → list of int indices (one entry per click)
    #   mode="letter" → list of unique lowercase letter strings (all duplicates share one entry)
    selected_order = []

    btn_frame = tk.Frame(popup, bg=_BACKGROUND_COLOR)
    btn_frame.pack(padx=20, pady=5)

    letter_buttons = {}  # index -> button

    def get_preview_string():
        if mode == "letter":
            return ",".join(selected_order)  # already unique letter strings
        return ",".join(str(i) for i in selected_order)

    def refresh_buttons():
        for idx, btn in letter_buttons.items():
            if mode == "letter":
                letter = stripped[idx].lower()
                if letter in selected_order:
                    pos = selected_order.index(letter) + 1
                    btn.config(text=f"{stripped[idx]}\n{pos}", bg="#2a6496", fg="white",
                               font=("Courier New", 14, "bold"))
                else:
                    btn.config(text=f"{stripped[idx]}\n ", bg="#333", fg="white",
                               font=("Courier New", 14, "bold"))
            else:
                if idx in selected_order:
                    pos = selected_order.index(idx) + 1
                    btn.config(text=f"{stripped[idx]}\n{pos}", bg="#2a6496", fg="white",
                               font=("Courier New", 14, "bold"))
                else:
                    btn.config(text=f"{stripped[idx]}\n ", bg="#333", fg="white",
                               font=("Courier New", 14, "bold"))

    def on_letter_click(idx):
        if mode == "letter":
            letter = stripped[idx].lower()
            if letter in selected_order:
                selected_order.remove(letter)
            else:
                selected_order.append(letter)
        else:
            if idx in selected_order:
                selected_order.remove(idx)
            else:
                selected_order.append(idx)
        refresh_buttons()
        preview_var.set(get_preview_string())

    # Lay out buttons — spaces shown as blank visual separators, letters as clickable buttons
    ROW_SIZE = 12
    row_frame = None
    col_count = 0
    stripped_idx = 0
    for char in title_text:
        if col_count == 0:
            row_frame = tk.Frame(btn_frame, bg=_BACKGROUND_COLOR)
            row_frame.pack(pady=2)
        if char == " ":
            tk.Label(row_frame, text=" ", width=3, height=2,
                     bg=_BACKGROUND_COLOR, font=("Courier New", 14)).pack(side="left", padx=2)
        else:
            idx = stripped_idx
            btn = tk.Button(row_frame, text=f"{char}\n ", width=3, height=2,
                            font=("Courier New", 14, "bold"), bg="#333", fg="white",
                            command=lambda idx=idx: on_letter_click(idx))
            btn.pack(side="left", padx=2)
            letter_buttons[idx] = btn
            stripped_idx += 1
        col_count += 1
        if col_count >= ROW_SIZE:
            col_count = 0

    # Pre-populate from existing entry value
    existing = target_entry.get().strip()
    if existing:
        if mode == "index":
            for part in existing.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part)
                    if 0 <= idx < len(stripped):
                        selected_order.append(idx)
        else:  # letter mode: just restore the unique letters in their saved order
            seen = set()
            for part in existing.split(","):
                letter = part.strip().lower()
                if letter and letter not in seen:
                    seen.add(letter)
                    selected_order.append(letter)
    refresh_buttons()

    # Preview label
    preview_var = tk.StringVar(value=get_preview_string())
    preview_frame = tk.Frame(popup, bg=_BACKGROUND_COLOR)
    preview_frame.pack(pady=(5, 0))
    tk.Label(preview_frame, text="Order string:", font=("Arial", 9), bg=_BACKGROUND_COLOR, fg="gray").pack(side="left")
    tk.Label(preview_frame, textvariable=preview_var, font=("Courier New", 10), bg=_BACKGROUND_COLOR, fg="white").pack(side="left", padx=5)

    # Buttons
    ctrl_frame = tk.Frame(popup, bg=_BACKGROUND_COLOR)
    ctrl_frame.pack(pady=10)

    def clear_all():
        selected_order.clear()
        preview_var.set("")
        refresh_buttons()

    def confirm():
        target_entry.delete(0, tk.END)
        target_entry.insert(0, preview_var.get())
        popup.destroy()

    tk.Button(ctrl_frame, text="Clear", font=("Arial", 10), bg="#aa3333", fg="white",
              command=clear_all, width=8).pack(side="left", padx=5)
    tk.Button(ctrl_frame, text="Confirm", font=("Arial", 10, "bold"), bg="#2a6496", fg="white",
              command=confirm, width=8).pack(side="left", padx=5)
    tk.Button(ctrl_frame, text="Cancel", font=("Arial", 10), bg="#444", fg="white",
              command=popup.destroy, width=8).pack(side="left", padx=5)


# ---------------------------------------------------------------------------
# Per-field round editor
# ---------------------------------------------------------------------------

def open_round_field_editor(round_info, round_index, refresh_callback, parent_window=None, position=None):
    """Open field editor for adding/editing a single round"""
    global last_selected_round_type
    is_new = round_index is None

    if is_new:
        round_data = {}
    else:
        round_data = round_info['data']['rounds'][round_index].copy()

    field_window = tk.Toplevel()
    field_window.title("Add Round" if is_new else "Edit Round")
    field_window.configure(bg=_BACKGROUND_COLOR)

    if position:
        field_window.geometry(f"+{position[0]}+{position[1]}")

    def on_close():
        field_window.destroy()
        if parent_window:
            parent_window.deiconify()

    field_window.protocol("WM_DELETE_WINDOW", on_close)

    font_label = ("Arial", 10)
    font_entry = ("Arial", 10)
    fg_color = "white"

    # Get available round types
    round_types = [k for k in FIXED_LIGHTNING_ROUNDS.keys() if k != "global"]

    # Container
    container = tk.Frame(field_window, bg=_BACKGROUND_COLOR)
    container.pack(fill="both", expand=False, padx=10, pady=10)

    # Type selection
    type_frame = tk.Frame(container, bg=_BACKGROUND_COLOR)
    type_frame.pack(fill="x", pady=(0, 10))

    tk.Label(type_frame, text="Round Type:", font=font_label, bg=_BACKGROUND_COLOR, fg=fg_color).pack(side="left", padx=(0, 10))

    # For existing rounds, use the round's type
    default_type = round_data.get('type', last_selected_round_type if last_selected_round_type else round_types[0])
    type_var = tk.StringVar(value=default_type)
    type_dropdown = ttk.Combobox(type_frame, textvariable=type_var, values=round_types,
                                 state='readonly', font=font_entry, width=20)
    type_dropdown.pack(side="left")

    scrollable_frame = tk.Frame(container, bg=_BACKGROUND_COLOR)
    scrollable_frame.pack(fill="both", expand=True, pady=(5, 0))

    field_widgets = {}

    def rebuild_fields():
        """Rebuild field widgets based on selected type"""
        # Preserve theme value across rebuilds
        if "theme" in field_widgets:
            theme_getter = field_widgets["theme"][1]
            current_theme = theme_getter()
            if current_theme:
                round_data["theme"] = current_theme
        for widget in scrollable_frame.winfo_children():
            widget.destroy()
        field_widgets.clear()

        selected_type = type_var.get()

        all_fields = FIXED_LIGHTNING_ROUNDS['global'] + FIXED_LIGHTNING_ROUNDS.get(selected_type, [])

        if selected_type == 'frame' and 'start_time' in all_fields:
            all_fields = [f for f in all_fields if f != 'start_time']

        # Use a view of round_data with type reflecting the current dropdown selection
        round_data_with_type = dict(round_data, type=selected_type)

        last_field_frame = [None]

        for field_name in all_fields:
            field_info = FIXED_LIGHTNING_ROUND_FIELD_INDEX.get(field_name, {"type": "file", "required": True})
            group_with_previous = field_info.get("group_with_previous", False)
            # group_with_previous fields manage their own visibility inline; skip normal check
            if not group_with_previous and not should_show_field(field_name, round_data_with_type):
                continue
            field_type = field_info.get("type", "file")
            is_required = field_info.get("required", False)

            # Create field frame (or reuse previous one for inline companions)
            if group_with_previous and last_field_frame[0] is not None:
                # All companion widgets go into a subframe so we can pack/forget it atomically
                companion_frame = tk.Frame(last_field_frame[0], bg=_BACKGROUND_COLOR)
                companion_frame.pack(side="left")
                tk.Label(companion_frame, text=" | ", font=font_label, bg=_BACKGROUND_COLOR, fg="#555").pack(side="left")
                label_text = field_name.replace("_", " ").title()
                label_widget = tk.Label(companion_frame, text=label_text + ":", font=font_label, bg=_BACKGROUND_COLOR, fg="#aaa")
                label_widget.pack(side="left", padx=(0, 4))
                tooltip_text = field_info.get("tooltip", "")
                if tooltip_text:
                    _ToolTip(label_widget, tooltip_text)
                # Dynamic show/hide: watch the parent toggle specified in show_if
                _show_if = field_info.get("show_if", {})
                _parent_var = None
                if _show_if:
                    _parent_fn = next(iter(_show_if))
                    _parent_widget = field_widgets.get(_parent_fn)
                    if _parent_widget and _parent_widget[0] == "toggle":
                        _parent_var = _parent_widget[1]
                # Set initial visibility
                if not should_show_field(field_name, round_data_with_type):
                    companion_frame.pack_forget()
                # Bind to parent var for live toggling
                if _parent_var is not None:
                    def _bind_companion(cf=companion_frame, pv=_parent_var):
                        def _toggle(*_):
                            if pv.get():
                                cf.pack(side="left")
                            else:
                                cf.pack_forget()
                        pv.trace_add("write", _toggle)
                    _bind_companion()
                # Subsequent widget packing targets the companion subframe
                field_frame = companion_frame
            else:
                field_frame = tk.Frame(scrollable_frame, bg=_BACKGROUND_COLOR)
                field_frame.pack(fill="x", pady=5)
                last_field_frame[0] = field_frame

                # Label
                label_text = field_name.replace("_", " ").title()
                # Custom labels for zoom area fields
                if field_name == "image_selected_area":
                    label_text = "Starting Zoom Area"
                elif field_name == "image_ending_area":
                    label_text = "Ending Zoom Area"
                if is_required:
                    label_text += " *"
                label_widget = tk.Label(field_frame, text=label_text, font=font_label, bg=_BACKGROUND_COLOR,
                                       fg=fg_color, width=20, anchor="w")
                label_widget.pack(side="left", padx=(0, 10))

                # Show field-specific tooltip from config, with a useful fallback for unlabeled fields.
                tooltip_text = field_info.get("tooltip", "")
                if not tooltip_text:
                    type_label = field_type.replace("_", " ")
                    tooltip_parts = [f"{label_text.replace(' *', '')}", f"Type: {type_label}"]
                    if is_required:
                        tooltip_parts.append("Required")
                    if "default" in field_info and field_info.get("default") not in (None, ""):
                        tooltip_parts.append(f"Default: {field_info.get('default')}")
                    tooltip_text = "\n".join(tooltip_parts)
                _ToolTip(label_widget, tooltip_text)

            # Input widget based on field type
            if field_type == "file":
                # Simple label with button to select currently playing
                file_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                file_frame.pack(side="left")

                # Display current value with get_title
                initial_value = round_data.get(field_name, "")
                display_value = _get_title(initial_value, initial_value) if initial_value else "(No theme selected)"

                label = tk.Label(file_frame, text=display_value, font=font_entry,
                               bg=_BACKGROUND_COLOR, fg="white", anchor="w")
                label.pack(side="left", padx=(0, 10))

                # Store the actual filename (not display name)
                actual_filename = [initial_value]

                def set_currently_playing():
                    filename = state.playback.currently_playing.get("filename", "")
                    if filename:
                        actual_filename[0] = filename
                        display_name = _get_title(filename, filename)
                        label.config(text=display_name)

                def play_selected():
                    if actual_filename[0]:
                        _play_video_from_filename(actual_filename[0])

                select_btn = tk.Button(file_frame, text="SET TO CURRENT", font=font_entry,
                                      bg="black", fg="white", command=set_currently_playing)
                select_btn.pack(side="left", padx=(0, 5))

                play_btn = tk.Button(file_frame, text="▶", font=font_entry,
                                    bg="black", fg="white", width=3, command=play_selected)
                play_btn.pack(side="left")

                # Getter function returns actual filename
                def get_filename():
                    return actual_filename[0]

                field_widgets[field_name] = ("file_search", get_filename)

            elif field_type == "duration":
                # Duration field with +/- buttons (increment by 1 second)
                # Get default duration from lightning_mode_settings_default
                round_type = type_var.get()
                default_duration = _lightning_mode_settings_default.get(round_type, {}).get("length", 12)
                if field_name == "answer_duration":
                    default_duration = 8  # Default answer duration

                duration_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                duration_frame.pack(side="left")

                minus_btn = tk.Button(duration_frame, text="-", font=font_entry, bg="black", fg="white", width=2)
                minus_btn.pack(side="left")

                entry = tk.Entry(duration_frame, font=font_entry, bg="black", fg="white", width=8, justify="center", insertbackground="white")
                current_val = round_data.get(field_name, default_duration)
                entry.insert(0, str(current_val))
                entry.pack(side="left", padx=3)

                plus_btn = tk.Button(duration_frame, text="+", font=font_entry, bg="black", fg="white", width=2)
                plus_btn.pack(side="left", padx=(0, 5))

                default_btn = tk.Button(duration_frame, text="DEFAULT", font=font_entry, bg="black", fg="white", width=9)
                default_btn.pack(side="left", padx=(0, 5))

                calc_btn = tk.Button(duration_frame, text="CALC FROM NOW", font=font_entry, bg="black", fg="white")
                calc_btn.pack(side="left")

                def increment_duration(e=entry):
                    try:
                        val = float(e.get() or 0)
                        e.delete(0, tk.END)
                        e.insert(0, str(int(val + 1)))
                    except:
                        pass

                def decrement_duration(e=entry):
                    try:
                        val = float(e.get() or 0)
                        e.delete(0, tk.END)
                        e.insert(0, str(max(0, int(val - 1))))
                    except:
                        pass

                def set_to_default(e=entry, d=default_duration):
                    e.delete(0, tk.END)
                    e.insert(0, str(d))

                def calc_from_now(e=entry, fn=field_name):
                    try:
                        now = _player.get_time() / 1000.0
                        # For clip/ost rounds use clip_start_time as the reference:
                        #   duration       — always (clip/ost question counts from clip start)
                        #   answer_duration — only when clip_for_answer is toggled on
                        clip_start_widget = field_widgets.get("clip_start_time")
                        use_clip_start = False
                        if clip_start_widget:
                            if fn == "duration":
                                use_clip_start = True
                            elif fn == "answer_duration":
                                cfa = field_widgets.get("clip_for_answer")
                                use_clip_start = bool(cfa and cfa[1].get())
                        if use_clip_start:
                            start = float(clip_start_widget[1].get() or 0)
                        else:
                            start_widget = field_widgets.get("start_time")
                            start = float(start_widget[1].get() or 0) if start_widget else 0.0
                        duration = max(0, round(now - start))
                        e.delete(0, tk.END)
                        e.insert(0, str(duration))
                    except:
                        pass

                plus_btn.config(command=increment_duration)
                minus_btn.config(command=decrement_duration)
                default_btn.config(command=set_to_default)
                calc_btn.config(command=calc_from_now)

                tk.Label(duration_frame, text="(sec)", font=("Arial", 8), bg=_BACKGROUND_COLOR,
                        fg="gray").pack(side="left", padx=(5, 0))

                field_widgets[field_name] = ("duration", entry, default_duration)

            elif field_type == "integer":
                # Integer field with +/- buttons (can go negative)
                default_value = field_info.get("default", 0)

                integer_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                integer_frame.pack(side="left")

                minus_btn = tk.Button(integer_frame, text="-", font=font_entry, bg="black", fg="white", width=2)
                minus_btn.pack(side="left")

                entry = tk.Entry(integer_frame, font=font_entry, bg="black", fg="white", width=8, justify="center", insertbackground="white")
                current_val = round_data.get(field_name, default_value)
                entry.insert(0, str(current_val))
                entry.pack(side="left", padx=3)

                plus_btn = tk.Button(integer_frame, text="+", font=font_entry, bg="black", fg="white", width=2)
                plus_btn.pack(side="left", padx=(0, 5))

                default_btn = tk.Button(integer_frame, text="DEFAULT", font=font_entry, bg="black", fg="white", width=9)
                default_btn.pack(side="left")

                def increment_integer(e=entry):
                    try:
                        val = int(e.get() or 0)
                        e.delete(0, tk.END)
                        e.insert(0, str(val + 1))
                    except:
                        pass

                def decrement_integer(e=entry):
                    try:
                        val = int(e.get() or 0)
                        e.delete(0, tk.END)
                        e.insert(0, str(val - 1))
                    except:
                        pass

                def set_to_default(e=entry, d=default_value):
                    e.delete(0, tk.END)
                    e.insert(0, str(d))

                plus_btn.config(command=increment_integer)
                minus_btn.config(command=decrement_integer)
                default_btn.config(command=set_to_default)

                field_widgets[field_name] = ("integer", entry, default_value)

            elif field_type == "time":
                # Time field with +/- buttons (increment by 0.1), NOW button, and GO TO button
                time_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                time_frame.pack(side="left")

                minus_btn = tk.Button(time_frame, text="-", font=font_entry, bg="black", fg="white", width=2)
                minus_btn.pack(side="left")

                entry = tk.Entry(time_frame, font=font_entry, bg="black", fg="white", width=8, justify="center", insertbackground="white")
                entry.insert(0, str(round_data.get(field_name, "")))
                entry.pack(side="left", padx=3)

                plus_btn = tk.Button(time_frame, text="+", font=font_entry, bg="black", fg="white", width=2)
                plus_btn.pack(side="left", padx=(0, 5))

                now_btn = tk.Button(time_frame, text="NOW", font=font_entry, bg="black", fg="white", width=5)
                now_btn.pack(side="left", padx=(0, 5))

                set_btn = tk.Button(time_frame, text="GO TO", font=font_entry, bg="black", fg="white", width=6)
                set_btn.pack(side="left")

                def increment_time(step=0.1, e=entry):
                    try:
                        val = float(e.get() or 0)
                        e.delete(0, tk.END)
                        e.insert(0, f"{val + step:.1f}")
                    except:
                        pass

                def decrement_time(step=0.1, e=entry):
                    try:
                        val = float(e.get() or 0)
                        e.delete(0, tk.END)
                        e.insert(0, f"{max(0, val - step):.1f}")
                    except:
                        pass

                def set_now(e=entry):
                    try:
                        current_time = _player.get_time() / 1000.0  # Convert ms to seconds
                        if current_time > 0:
                            e.delete(0, tk.END)
                            e.insert(0, f"{current_time:.1f}")
                    except:
                        pass

                def set_to_time(e=entry):
                    try:
                        time_val = float(e.get() or 0)
                        _player.set_time(round(time_val * 1000))  # Convert seconds to ms
                    except:
                        pass

                plus_btn.config(command=increment_time)
                minus_btn.config(command=decrement_time)
                plus_btn.bind("<Button-3>", lambda e, f=increment_time: f(1.0))
                minus_btn.bind("<Button-3>", lambda e, f=decrement_time: f(1.0))
                now_btn.config(command=set_now)
                set_btn.config(command=set_to_time)

                tk.Label(time_frame, text="(sec)", font=("Arial", 8), bg=_BACKGROUND_COLOR,
                        fg="gray").pack(side="left", padx=(5, 0))

                field_widgets[field_name] = ("entry", entry)

            elif field_type == "dropdown":
                # Dropdown field
                options = list(field_info.get("options", {}).keys())
                default_value = field_info.get("default", "")
                current_value = round_data.get(field_name, default_value)

                var = tk.StringVar(value=current_value)
                dropdown = ttk.Combobox(field_frame, textvariable=var, values=options,
                                       state='readonly', font=font_entry, width=32)
                dropdown.pack(side="left")

                # If this is a variant selector, rebuild fields when it changes
                if field_name.endswith("_variant"):
                    def on_variant_change(event, fn=field_name, v=var):
                        round_data[fn] = v.get()
                        rebuild_fields()
                    dropdown.bind("<<ComboboxSelected>>", on_variant_change)

                field_widgets[field_name] = ("dropdown", var)

            elif field_type == "text":
                # Single-line text field
                entry = tk.Entry(field_frame, font=font_entry, bg="black", fg="white", width=35, insertbackground="white")
                default_value = field_info.get("default", "")
                current_value = round_data.get(field_name, default_value)
                if current_value:
                    entry.insert(0, current_value)
                entry.pack(side="left")
                field_widgets[field_name] = ("text", entry)

            elif field_type == "letter_order_select":
                # Text entry + button that opens a visual letter-picker popup
                los_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                los_frame.pack(side="left")
                entry = tk.Entry(los_frame, font=font_entry, bg="black", fg="white", width=28, insertbackground="white")
                current_value = round_data.get(field_name, "")
                if current_value:
                    entry.insert(0, current_value)
                entry.pack(side="left", padx=(0, 5))
                def open_selector(e=entry, fw=field_widgets, fn=field_name):
                    theme_wid = fw.get("theme")
                    theme_filename = theme_wid[1]() if theme_wid else ""
                    data = _get_metadata(theme_filename) if theme_filename else {}
                    title_text = _get_base_title(title=_get_display_title(data or {})) if theme_filename else ""
                    if not title_text:
                        messagebox.showwarning("No Theme", "Please set the theme first.", parent=field_window)
                        return
                    open_letter_order_selector(title_text, e, field_window)
                tk.Button(los_frame, text="SELECT ORDER", font=font_entry,
                          bg="black", fg="white", command=open_selector).pack(side="left")
                field_widgets[field_name] = ("text", entry)

            elif field_type == "letter_select":
                # Text entry + button that opens the letter selector in letter-output mode
                ls_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                ls_frame.pack(side="left")
                entry = tk.Entry(ls_frame, font=font_entry, bg="black", fg="white", width=28, insertbackground="white")
                current_value = round_data.get(field_name, "")
                if current_value:
                    entry.insert(0, current_value)
                entry.pack(side="left", padx=(0, 5))
                def open_letter_selector(e=entry, fw=field_widgets, fn=field_name):
                    theme_wid = fw.get("theme")
                    theme_filename = theme_wid[1]() if theme_wid else ""
                    data = _get_metadata(theme_filename) if theme_filename else {}
                    title_text = _get_base_title(title=_get_display_title(data or {})) if theme_filename else ""
                    if not title_text:
                        messagebox.showwarning("No Theme", "Please set the theme first.", parent=field_window)
                        return
                    open_letter_order_selector(title_text, e, field_window, mode="letter")
                tk.Button(ls_frame, text="SELECT LETTERS", font=font_entry,
                          bg="black", fg="white", command=open_letter_selector).pack(side="left")
                field_widgets[field_name] = ("text", entry)

            elif field_type == "image_url":
                # Image URL field with VIEW IMAGE button
                url_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                url_frame.pack(side="left")
                entry = tk.Entry(url_frame, font=font_entry, bg="black", fg="white", width=35, insertbackground="white")
                default_value = field_info.get("default", "")
                current_value = round_data.get(field_name, default_value)
                if current_value:
                    entry.insert(0, current_value)
                entry.pack(side="left", padx=(0, 5))
                def view_img(e=entry):
                    url = e.get().strip()
                    if url:
                        _open_image_popup(url, "Image Preview")
                    else:
                        messagebox.showwarning("No URL", "Please enter an image URL first.")
                tk.Button(url_frame, text="VIEW IMAGE", font=font_entry,
                          bg="black", fg="white", command=view_img).pack(side="left")
                field_widgets[field_name] = ("text", entry)

            elif field_type == "cover_fill":
                # Read-only helper: shows cover URL from the round's theme file, with a fill button
                cf_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                cf_frame.pack(side="left")
                def _theme_cover_url():
                    theme_wid = field_widgets.get("theme")
                    if theme_wid:
                        filename = theme_wid[1]()
                        if filename:
                            return (_get_metadata(filename) or {}).get("cover") or ""
                    return ""
                cover_url_var = [_theme_cover_url()]
                url_label = tk.Label(cf_frame,
                                     text=cover_url_var[0] if cover_url_var[0] else "(no cover available)",
                                     font=("Arial", 8), bg=_BACKGROUND_COLOR, fg="gray",
                                     width=40, anchor="w")
                url_label.pack(side="left", padx=(0, 5))
                def fill_cover_url(lbl=url_label, var=cover_url_var):
                    url = _theme_cover_url()
                    var[0] = url
                    lbl.config(text=url if url else "(no cover available)")
                    img_wid = field_widgets.get("image_url")
                    if img_wid:
                        img_wid[1].delete(0, tk.END)
                        if url:
                            img_wid[1].insert(0, url)
                    else:
                        messagebox.showwarning("Not Ready", "Image URL field not found.")
                tk.Button(cf_frame, text="FILL IMAGE URL", font=font_entry,
                          bg="black", fg="white", command=fill_cover_url).pack(side="left")
                # cover_fill is a helper only — not added to field_widgets so it's never saved

            elif field_type == "textarea":
                text_widget = tk.Text(field_frame, font=font_entry, bg="black", fg="white",
                                     width=40, height=field_info.get("height", 4), wrap="word", insertbackground="white")
                text_widget.pack(side="left")

                current_value = round_data.get(field_name, "")
                if current_value:
                    text_widget.insert("1.0", current_value)

                field_widgets[field_name] = ("textarea", text_widget)

            elif field_type == "toggle":
                # Toggle field (checkbox)
                default_value = field_info.get("default", False)
                current_value = round_data.get(field_name, default_value)

                var = tk.BooleanVar(value=current_value)
                checkbox = tk.Checkbutton(field_frame, variable=var, bg=_BACKGROUND_COLOR,
                                         activebackground=_BACKGROUND_COLOR, selectcolor="black",
                                         fg="white", activeforeground="white")
                checkbox.pack(side="left")
                field_widgets[field_name] = ("toggle", var)

            elif field_type == "area_selector":
                # Area selector field with SELECT AREA button
                area_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                area_frame.pack(side="left")

                # Store the selected area
                selected_area = [round_data.get(field_name, None)]

                # Display current selection
                if selected_area[0]:
                    # Display as percentages for clarity
                    area_text = f"x:{selected_area[0]['x_pct']:.1%}, y:{selected_area[0]['y_pct']:.1%}, w:{selected_area[0]['w_pct']:.1%}, h:{selected_area[0]['h_pct']:.1%}"
                else:
                    area_text = "(No area selected)"

                area_label = tk.Label(area_frame, text=area_text, font=font_entry,
                                     bg=_BACKGROUND_COLOR, fg="white", width=30, anchor="w")
                area_label.pack(side="left", padx=(0, 5))

                def open_area_selector(_field_name=field_name, _selected_area=selected_area, _area_label=area_label):
                    # Get image URL from image_url field
                    image_url_widget = field_widgets.get("image_url")
                    if not image_url_widget:
                        messagebox.showwarning("No Image URL", "Please set the Image URL field first.")
                        return

                    image_url = image_url_widget[1].get().strip()
                    if not image_url:
                        messagebox.showwarning("No Image URL", "Please set the Image URL field first.")
                        return

                    # Download and show image for area selection
                    try:
                        response = _requests.get(image_url, timeout=10)
                        response.raise_for_status()
                        pil_img = Image.open(BytesIO(response.content))

                        # Create popup window for area selection
                        selector_window = tk.Toplevel()
                        # Set title based on field type
                        window_title = "Select Starting Zoom Area" if _field_name == "image_selected_area" else "Select Ending Zoom Area"
                        selector_window.title(window_title)
                        selector_window.configure(bg="black")

                        # Calculate display size
                        screen_w = selector_window.winfo_screenwidth()
                        screen_h = selector_window.winfo_screenheight()
                        max_w = int(screen_w * 0.8)
                        max_h = int(screen_h * 0.8)

                        img_w, img_h = pil_img.size
                        scale_w = max_w / img_w
                        scale_h = max_h / img_h
                        scale = min(scale_w, scale_h, 1.0)

                        display_w = int(img_w * scale)
                        display_h = int(img_h * scale)

                        display_img = pil_img.resize((display_w, display_h), Image.LANCZOS)
                        tk_img = ImageTk.PhotoImage(display_img)

                        # Canvas for image and selection
                        canvas = tk.Canvas(selector_window, width=display_w, height=display_h,
                                         bg="black", highlightthickness=0)
                        canvas.pack(padx=10, pady=10)
                        canvas.create_image(0, 0, anchor="nw", image=tk_img)
                        canvas.image = tk_img

                        # Selection rectangle
                        selection_rect = [None]
                        start_pos = [None, None]

                        def on_mouse_down(event):
                            start_pos[0] = event.x
                            start_pos[1] = event.y
                            if selection_rect[0]:
                                canvas.delete(selection_rect[0])
                            selection_rect[0] = canvas.create_rectangle(
                                event.x, event.y, event.x, event.y,
                                outline="red", width=3
                            )

                        def on_mouse_drag(event):
                            if selection_rect[0]:
                                canvas.coords(selection_rect[0],
                                            start_pos[0], start_pos[1], event.x, event.y)

                        def on_mouse_up(event):
                            if start_pos[0] is not None:
                                # Calculate area in display coordinates
                                x1 = min(start_pos[0], event.x)
                                y1 = min(start_pos[1], event.y)
                                x2 = max(start_pos[0], event.x)
                                y2 = max(start_pos[1], event.y)

                                # Convert to original image coordinates
                                orig_x = int(x1 / scale)
                                orig_y = int(y1 / scale)
                                orig_w = int((x2 - x1) / scale)
                                orig_h = int((y2 - y1) / scale)

                                # Ensure area is within bounds
                                orig_x = max(0, min(orig_x, img_w - 1))
                                orig_y = max(0, min(orig_y, img_h - 1))
                                orig_w = max(1, min(orig_w, img_w - orig_x))
                                orig_h = max(1, min(orig_h, img_h - orig_y))

                                # Store as percentages of image dimensions
                                _selected_area[0] = {
                                    "x_pct": orig_x / img_w,
                                    "y_pct": orig_y / img_h,
                                    "w_pct": orig_w / img_w,
                                    "h_pct": orig_h / img_h
                                }

                                _area_label.config(text=f"x:{_selected_area[0]['x_pct']:.1%}, y:{_selected_area[0]['y_pct']:.1%}, w:{_selected_area[0]['w_pct']:.1%}, h:{_selected_area[0]['h_pct']:.1%}")
                                selector_window.destroy()

                        canvas.bind("<Button-1>", on_mouse_down)
                        canvas.bind("<B1-Motion>", on_mouse_drag)
                        canvas.bind("<ButtonRelease-1>", on_mouse_up)

                        # Instructions
                        instruction_text = "Click and drag to select the starting zoom area (zoomed in)" if _field_name == "image_selected_area" else "Click and drag to select the ending zoom area (zoomed out)"
                        instructions = tk.Label(selector_window,
                                              text=instruction_text,
                                              font=("Arial", 12), bg="black", fg="white")
                        instructions.pack(pady=(0, 10))

                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to load image: {e}")

                def clear_selection(_selected_area=selected_area, _area_label=area_label):
                    _selected_area[0] = None
                    _area_label.config(text="(No area selected)")

                select_btn = tk.Button(area_frame, text="SELECT AREA", font=font_entry,
                                      bg="black", fg="white", command=open_area_selector)
                select_btn.pack(side="left", padx=(0, 5))

                clear_btn = tk.Button(area_frame, text="CLEAR", font=font_entry,
                                    bg="black", fg="white", width=6, command=clear_selection)
                clear_btn.pack(side="left")

                field_widgets[field_name] = ("area_selector", lambda area=selected_area: area[0])

            elif field_type == "music_track":
                # Typable dropdown populated with detected music files (alphabetical, autocomplete)
                mt_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                mt_frame.pack(side="left")
                music_files = state.playback.music_files
                if not music_files:
                    _load_music_files()
                    music_files = state.playback.music_files
                track_basenames = sorted([os.path.basename(f) for f in music_files], key=str.lower)
                current_value = round_data.get(field_name, "")
                var = tk.StringVar(value=current_value)
                combo = ttk.Combobox(mt_frame, textvariable=var, values=track_basenames,
                                     state='normal', font=font_entry, width=35)
                combo.pack(side="left", padx=(0, 5))

                suggest_popup = tk.Toplevel(combo)
                suggest_popup.withdraw()
                suggest_popup.overrideredirect(True)
                suggest_popup.configure(bg="white")

                suggest_frame = tk.Frame(suggest_popup, bg="black", highlightthickness=1, highlightbackground="white")
                suggest_frame.pack(fill="both", expand=True)
                suggest_list = tk.Listbox(
                    suggest_frame,
                    bg="black",
                    fg="white",
                    selectbackground="#303030",
                    selectforeground="white",
                    activestyle="none",
                    exportselection=False,
                    height=6,
                    width=35,
                    font=font_entry,
                )
                suggest_list.pack(fill="both", expand=True)
                _mt_suggest_visible = [False]

                def _mt_show_suggestions(items, _combo=combo, _popup=suggest_popup, _list=suggest_list):
                    _list.delete(0, tk.END)
                    for item in items[:100]:
                        _list.insert(tk.END, item)
                    if _list.size() == 0:
                        _mt_hide_suggestions()
                        return
                    try:
                        visible_rows = min(_list.size(), 6)
                        _list.configure(height=visible_rows)
                        _combo.update_idletasks()
                        _list.update_idletasks()
                        x = _combo.winfo_rootx()
                        y = _combo.winfo_rooty() + _combo.winfo_height() + 2
                        w = _combo.winfo_width()
                        h = suggest_frame.winfo_reqheight()
                        _popup.geometry(f"{w}x{h}+{x}+{y}")
                        _popup.deiconify()
                        _popup.lift()
                    except Exception:
                        _mt_hide_suggestions()
                        return
                    _mt_suggest_visible[0] = True

                def _mt_hide_suggestions(_popup=suggest_popup):
                    try:
                        _popup.withdraw()
                    except Exception:
                        pass
                    _mt_suggest_visible[0] = False

                def _mt_apply_suggestion(_event=None, _combo=combo, _list=suggest_list, _var=var):
                    selection = _list.curselection()
                    if not selection:
                        return "break"
                    value = _list.get(selection[0])
                    _var.set(value)
                    _mt_hide_suggestions()
                    _combo.focus_set()
                    _combo.icursor(tk.END)
                    return "break"

                def _mt_autocomplete(event, _combo=combo, _names=track_basenames):
                    if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
                        return
                    typed = _combo.get().lower()
                    if not typed:
                        _combo['values'] = _names
                        _mt_hide_suggestions()
                        return
                    filtered = [n for n in _names if n.lower().startswith(typed)]
                    shown = filtered if filtered else _names
                    _combo['values'] = shown
                    _mt_show_suggestions(shown)

                def _mt_focus_out(_event=None, _combo=combo):
                    def _later():
                        try:
                            focused = _combo.focus_get()
                        except KeyError:
                            focused_name = str(_combo.tk.call("focus") or "")
                            if "popdown" in focused_name:
                                return
                            focused = None
                        if focused in (suggest_list, combo, suggest_popup):
                            return
                        _mt_hide_suggestions()
                    _combo.after(120, _later)

                def _mt_down_key(_event=None):
                    if _mt_suggest_visible[0] and suggest_list.size() > 0:
                        suggest_list.focus_set()
                        suggest_list.selection_clear(0, tk.END)
                        suggest_list.selection_set(0)
                        suggest_list.activate(0)
                        return "break"

                def _mt_destroy_popup(_event=None, _popup=suggest_popup):
                    try:
                        _popup.destroy()
                    except Exception:
                        pass

                combo.bind('<KeyRelease>', _mt_autocomplete)
                combo.bind('<FocusOut>', _mt_focus_out)
                combo.bind('<Down>', _mt_down_key)
                combo.bind('<Escape>', lambda e: (_mt_hide_suggestions(), "break")[1])
                combo.bind('<Destroy>', _mt_destroy_popup)
                suggest_list.bind('<ButtonRelease-1>', _mt_apply_suggestion)
                suggest_list.bind('<Return>', _mt_apply_suggestion)
                suggest_list.bind('<Escape>', lambda e: (_mt_hide_suggestions(), combo.focus_set(), "break")[2])

                def clear_track(v=var, _combo=combo, _names=track_basenames):
                    v.set("")
                    _combo['values'] = _names
                    _mt_hide_suggestions()
                tk.Button(mt_frame, text="CLEAR", font=font_entry,
                          bg="black", fg="white", width=6, command=clear_track).pack(side="left")
                field_widgets[field_name] = ("dropdown", var)

            elif field_type == "video_url":
                # Video URL field with two buttons
                url_frame = tk.Frame(field_frame, bg=_BACKGROUND_COLOR)
                url_frame.pack(side="left")

                entry = tk.Entry(url_frame, font=font_entry, bg="black", fg="white", width=35, insertbackground="white")
                current_value = round_data.get(field_name, "")
                if current_value:
                    entry.insert(0, current_value)
                entry.pack(side="left", padx=(0, 5))

                def open_url_in_browser(e=entry):
                    url = e.get().strip()
                    if url:
                        webbrowser.open(url)

                def stream_in_player(e=entry):
                    url = e.get().strip()
                    if url:
                        # Stream YouTube URL using stream_url (same as YOUTUBE CLIP LIST)
                        _stream_url(url, None, None, new_player=False)

                open_btn = tk.Button(url_frame, text="GO TO URL", font=font_entry,
                                    bg="black", fg="white", command=open_url_in_browser)
                open_btn.pack(side="left", padx=(0, 5))

                stream_btn = tk.Button(url_frame, text="STREAM", font=font_entry,
                                      bg="black", fg="white", command=stream_in_player)
                stream_btn.pack(side="left")

                field_widgets[field_name] = ("video_url", entry)

    type_dropdown.bind('<<ComboboxSelected>>', lambda e: rebuild_fields())

    # Initial field build
    rebuild_fields()

    # Buttons
    button_frame = tk.Frame(field_window, bg=_BACKGROUND_COLOR)
    button_frame.pack(fill="x", padx=10, pady=(10, 10))

    def save_round():
        """Save the round data"""
        global last_selected_round_type
        # Collect data
        new_round_data = {"type": type_var.get()}

        last_selected_round_type = type_var.get()

        selected_type = type_var.get()
        all_fields = FIXED_LIGHTNING_ROUNDS['global'] + FIXED_LIGHTNING_ROUNDS.get(selected_type, [])

        if selected_type == 'frame' and 'start_time' in all_fields:
            all_fields = [f for f in all_fields if f != 'start_time']

        # Validate and collect field data
        for field_name in all_fields:
            field_info = FIXED_LIGHTNING_ROUND_FIELD_INDEX.get(field_name, {"type": "file", "required": True})
            field_type = field_info.get("type", "file")
            is_required = field_info.get("required", False)

            if field_name not in field_widgets:
                continue

            widget_data = field_widgets[field_name]
            widget_type = widget_data[0]

            if widget_type == "entry":
                widget = widget_data[1]
                value = widget.get().strip()
            elif widget_type == "text":
                widget = widget_data[1]
                value = widget.get().strip()
            elif widget_type == "duration":
                widget = widget_data[1]
                default_val = widget_data[2]
                value = widget.get().strip()
                # Convert to number
                if value:
                    try:
                        value = int(float(value))
                        if value == default_val:
                            continue
                    except ValueError:
                        messagebox.showwarning("Invalid Value", f"'{field_name.replace('_', ' ').title()}' must be a number.")
                        return False
            elif widget_type == "integer":
                widget = widget_data[1]
                default_val = widget_data[2]
                value = widget.get().strip()
                # Convert to number
                if value:
                    try:
                        value = int(float(value))
                        if value == default_val:
                            continue
                    except ValueError:
                        messagebox.showwarning("Invalid Value", f"'{field_name.replace('_', ' ').title()}' must be a number.")
                        return False
            elif widget_type == "dropdown":
                widget = widget_data[1]
                value = widget.get()
            elif widget_type == "textarea":
                widget = widget_data[1]
                value = widget.get("1.0", "end-1c").strip()
            elif widget_type == "file_search":
                # widget is a getter function
                widget = widget_data[1]
                value = widget().strip()
            elif widget_type == "toggle":
                widget = widget_data[1]
                value = widget.get()
            elif widget_type == "video_url":
                widget = widget_data[1]
                value = widget.get().strip()
            elif widget_type == "area_selector":
                # widget is a getter function that returns the area dict
                widget = widget_data[1]
                value = widget()
            else:
                value = ""

            # Validate required fields
            if is_required and not value and field_type != "area_selector":
                messagebox.showwarning("Required Field", f"'{field_name.replace('_', ' ').title()}' is required.")
                return False

            # Convert time fields to numbers
            if field_type == "time" and value:
                try:
                    value = float(value)
                except ValueError:
                    messagebox.showwarning("Invalid Value", f"'{field_name.replace('_', ' ').title()}' must be a number.")
                    return False

            # Only add non-empty values (or toggles which can be False, or area_selector which can be a dict, or numeric zero)
            if value or value == 0 or field_type == "toggle" or (field_type == "area_selector" and value is not None):
                new_round_data[field_name] = value

        # Save to round info
        nonlocal is_new, round_index
        if is_new:
            if 'rounds' not in round_info['data']:
                round_info['data']['rounds'] = []
            round_info['data']['rounds'].append(new_round_data)
            round_index = len(round_info['data']['rounds']) - 1
            is_new = False
            field_window.title("Edit Round")
            round_info['data']['date_modified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            _old_round_json = json.dumps(round_info['data']['rounds'][round_index], sort_keys=True)
            round_info['data']['rounds'][round_index] = new_round_data
            if json.dumps(new_round_data, sort_keys=True) != _old_round_json:
                round_info['data']['date_modified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Save to file
        try:
            with open(round_info['filepath'], 'w', encoding='utf-8') as f:
                json.dump(round_info['data'], f, indent=4)
            refresh_callback()
            save_button.configure(text="SAVED!")
            field_window.after(300, lambda: save_button.configure(text="SAVE"))
            return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")
            return False

    def return_to_editor():
        """Close field editor and return to parent editor window"""
        field_window.destroy()
        if parent_window:
            parent_window.deiconify()

    def save_and_return():
        """Save round and return to parent editor window"""
        if save_round():  # Only return if save was successful
            field_window.after(400, return_to_editor)

    def test_round():
        """Test this single round by queueing it as a temporary fixed lightning round playlist"""
        # If this is a new round (not saved yet), require saving first
        if is_new:
            messagebox.showwarning("Save Required", "Please save the round before testing.")
            return

        # Use the existing saved round data
        test_round_data = round_info['data']['rounds'][round_index].copy()
        selected_type = test_round_data.get('type', 'regular')

        # Create a temporary fixed lightning round structure
        temp_round_info = {
            'name': f'[TEST] {selected_type.upper()}',
            'description': 'Test round - single round from saved data',
            'creator': 'Test',
            'round_count': 1,
            'rounds': [test_round_data],
            'total_duration': test_round_data.get('duration', 0) + test_round_data.get('answer_duration', 0),
            'data': {
                'name': f'[TEST] {selected_type.upper()}',
                'description': 'Test round - single round from saved data',
                'creator': 'Test',
                'date_created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date_modified': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rounds': [test_round_data]
            },
            'filepath': None  # No file path for temp round
        }

        # Queue the test round
        temp_round_info['is_test'] = True
        _set_fl_queue(temp_round_info)
        _set_fl_round_playlist_data(None)  # Reset any existing data
        _play_video(state.metadata.playlist["current_index"])

    save_button = tk.Button(button_frame, text="SAVE", font=("Arial", 10, "bold"),
                           bg="black", fg="white", command=save_round, width=15, pady=8)
    save_button.pack(side="left", padx=(0, 10))

    save_return_button = tk.Button(button_frame, text="SAVE & RETURN", font=("Arial", 10, "bold"),
                                   bg="black", fg="white", command=save_and_return, width=15, pady=8)
    save_return_button.pack(side="left", padx=(0, 10))

    test_button = tk.Button(button_frame, text="TEST ROUND", font=("Arial", 10, "bold"),
                           bg="green", fg="white", command=test_round, width=15, pady=8)
    test_button.pack(side="left", padx=(0, 10))

    return_button = tk.Button(button_frame, text="RETURN", font=("Arial", 10, "bold"),
                             bg="black", fg="white", command=return_to_editor, width=15, pady=8)
    return_button.pack(side="left")
