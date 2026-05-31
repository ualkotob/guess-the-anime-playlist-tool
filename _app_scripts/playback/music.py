"""Background music for lightning rounds.

Loads `./music/*.{mp3,wav,ogg}` into a shuffled playlist, picks the next track
with a half-playlist no-repeat history, and pumps pygame.mixer.music for
play/pause/random-start. The visual "Now Playing" floating label is rendered
via the injected ``set_floating_text`` (a main-resident overlay primitive).

State staying here (in line with [[state-stays-with-its-readers]]):
  - music_files          — list, mutated in place via .clear()/.extend();
                           same object also aliased onto state.playback.music_files
                           and onto main as ``music_files`` for backward compat.
  - current_music_index  — int, reassigned. External readers must qualify
                           through this module (``music.current_music_index``).
  - music_loaded         — bool, reassigned; same external-qualify rule.
  - music_changed        — bool, internal only.
  - checked_music_folder — bool, internal only (one-shot warning gate).

State staying in main:
  - background_music_rounds — round-counter; only mutated by main's
                              play_filename, not by anything in here.
"""
from __future__ import annotations

import os
import random

import pygame
from tinytag import TinyTag

from core.game_state import state
from _app_scripts.queue_round.lightning_rounds import frame_round


# ---------------------------------------------------------------------------
# Module init — ensure the music folder exists and the mixer is up before
# play_background_music tries to touch pygame.mixer.music.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MUSIC_DIR = os.path.join(_PROJECT_ROOT, "music")
if not os.path.exists(_MUSIC_DIR):
    os.makedirs(_MUSIC_DIR)

pygame.mixer.init()


# ---------------------------------------------------------------------------
# Module-owned state
# ---------------------------------------------------------------------------
valid_music_ext = (".mp3", ".wav", ".ogg")
music_files = []                # populated by load_music_files()
current_music_index = 0
music_loaded = False
music_changed = False
checked_music_folder = False


# ---------------------------------------------------------------------------
# Context (injected by set_context)
# ---------------------------------------------------------------------------
_set_floating_text = None
_set_volume = None
_is_peek_active = None
_get_fixed_current_round = None
_get_light_mode = None
_get_light_round_started = None
_get_character_round_answer = None
_LIGHT_ROUND_LENGTH_DEFAULT = 10


def set_context(*, set_floating_text, set_volume, is_peek_active,
                get_fixed_current_round, get_light_mode,
                get_light_round_started, get_character_round_answer,
                light_round_length_default):
    g = globals()
    g['_set_floating_text'] = set_floating_text
    g['_set_volume'] = set_volume
    g['_is_peek_active'] = is_peek_active
    g['_get_fixed_current_round'] = get_fixed_current_round
    g['_get_light_mode'] = get_light_mode
    g['_get_light_round_started'] = get_light_round_started
    g['_get_character_round_answer'] = get_character_round_answer
    g['_LIGHT_ROUND_LENGTH_DEFAULT'] = light_round_length_default


# ---------------------------------------------------------------------------
# Playlist loading + next-track selection
# ---------------------------------------------------------------------------
def load_music_files():
    """Load all music files from the ``music`` folder (shuffled)."""
    global current_music_index
    if os.path.exists(_MUSIC_DIR):
        music_files.clear()
        music_files.extend(os.path.join(_MUSIC_DIR, f) for f in os.listdir(_MUSIC_DIR) if f.endswith(valid_music_ext))
        random.shuffle(music_files)
        current_music_index = 0


def next_background_track():
    """Advance current_music_index, skipping anything in the recent-half history."""
    global current_music_index, music_changed
    if music_files:
        playlist = state.metadata.playlist
        track_history = playlist.get("background_track_history", [])
        total_tracks = len(music_files)

        # Calculate how many tracks to avoid (half of total tracks)
        avoid_count = total_tracks // 2

        # Get list of recently used tracks to avoid
        recent_tracks = track_history[-avoid_count:] if avoid_count > 0 else []

        # Find next available track that hasn't been used recently
        attempts = 0
        original_index = current_music_index

        while attempts < total_tracks:
            current_music_index = (current_music_index + 1) % total_tracks
            current_track_path = music_files[current_music_index]
            current_track_basename = os.path.basename(current_track_path)

            # If this track is not in recent history, use it
            if current_track_basename not in recent_tracks:
                break

            attempts += 1

        # If all tracks are in recent history, just use the next one
        if attempts >= total_tracks:
            current_music_index = (original_index + 1) % total_tracks

        music_changed = True


# ---------------------------------------------------------------------------
# Play / pause / restart of the background mixer
# ---------------------------------------------------------------------------
def play_background_music(toggle):
    """Play or pause background music."""
    global music_loaded, current_music_index, music_changed, checked_music_folder

    if not music_files:  # Ensure music is loaded
        load_music_files()

    if not music_files:  # If still empty, return
        if not checked_music_folder:
            print("No music files found in 'music' folder. Add music files to this folder to play background music during lightning rounds.")
            checked_music_folder = True
        return

    fixed_current_round       = _get_fixed_current_round()
    disable_video_audio       = state.controls.disable_video_audio
    lightning_mode_settings   = state.playback.lightning_mode_settings
    volume_level              = state.controls.volume_level

    # If the current fixed round specifies a background track, pin to that track
    if toggle and fixed_current_round:
        pinned = (fixed_current_round.get("background_track") or "").strip()
        if pinned:
            matched = next(
                (i for i, f in enumerate(music_files) if os.path.basename(f) == pinned),
                None
            )
            if matched is not None and matched != current_music_index:
                current_music_index = matched
                music_changed = True  # Force reload with the pinned track
            # If not found, fall through to whatever track was already queued

    if music_loaded and not music_changed:
        if toggle and not disable_video_audio:
            pygame.mixer.music.unpause()
            now_playing_background_music(music_files[current_music_index])
        else:
            pygame.mixer.music.pause()
            now_playing_background_music()
    else:
        if toggle:
            music_loaded = True
            track_path = music_files[current_music_index]
            pygame.mixer.music.load(track_path)

            if lightning_mode_settings.get("_misc_settings", {}).get("background_music", {}).get("random_start", False):
                try:
                    # Get track duration using tinytag
                    tag = TinyTag.get(track_path)
                    duration = tag.duration if tag.duration else 0

                    # Start at random position (leave 10 seconds at end to avoid abrupt restart)
                    play_length = _LIGHT_ROUND_LENGTH_DEFAULT * 2 * lightning_mode_settings["_misc_settings"]["background_music"]["rounds_per_track"]
                    if duration > play_length:
                        max_start = duration - play_length
                        random_start_pos = random.uniform(0, max_start)
                        pygame.mixer.music.play(-1, start=random_start_pos)  # -1 loops indefinitely
                    else:
                        pygame.mixer.music.play(-1)  # -1 loops indefinitely
                except Exception:
                    pygame.mixer.music.play(-1)  # -1 loops indefinitely
            else:
                pygame.mixer.music.play(-1)  # -1 loops indefinitely

            _set_volume(volume_level)
            music_changed = False
            # Record track usage only when actually played
            record_background_track_usage(track_path)
            now_playing_background_music(track_path)


def record_background_track_usage(track_path):
    """Record the usage of a background track in the current playlist's history."""
    if not track_path:
        return

    playlist = state.metadata.playlist

    # Ensure background_track_history exists in playlist
    if "background_track_history" not in playlist:
        playlist["background_track_history"] = []

    # Add track to history (avoid duplicates) - store only basename
    track_basename = os.path.basename(track_path)
    if not playlist["background_track_history"] or playlist["background_track_history"][-1] != track_basename:
        playlist["background_track_history"].append(track_basename)

    # Keep history manageable - limit to total number of tracks available
    # This ensures we can always find non-recent tracks when we have enough variety
    max_history = len(music_files) if music_files else 50
    if len(playlist["background_track_history"]) > max_history:
        playlist["background_track_history"] = playlist["background_track_history"][-max_history:]


def now_playing_background_music(track=None):
    """Update the 'Now Playing' floating label (or hide it during reveal phases)."""
    lightning_mode_settings = state.playback.lightning_mode_settings
    light_mode              = _get_light_mode()
    light_round_started     = _get_light_round_started()
    light_muted             = state.controls.light_muted
    character_round_answer  = _get_character_round_answer()

    hide_during_reveal = lightning_mode_settings.get("_misc_settings", {}).get("background_music", {}).get("hide_display_during_reveal", False)
    is_reveal_mode = ((light_mode == 'reveal' and light_round_started) or not light_muted or _is_peek_active())
    if not frame_round.frame_light_round_started and (hide_during_reveal and is_reveal_mode):
        track = None
    if track:
        # Try to extract metadata using tinytag
        display_text = None
        try:
            tag = TinyTag.get(track)
            if tag.album and " [OST]" in tag.album:
                # Build display text from available metadata
                parts = []
                if tag.title:
                    parts.append(tag.title)
                if tag.artist:
                    parts.append(f"by {tag.artist}")
                if tag.album:
                    parts.append(tag.album)

                if parts:
                    display_text = "\n".join(parts)
        except Exception:
            pass

        if not display_text:
            basename = os.path.basename(track)
            for ext in valid_music_ext:
                basename = basename.replace(ext, "")
            if " [OST] - " in basename:
                _ost_name, _track_name = basename.split(" [OST] - ", 1)
                display_text = f"{_track_name}\n{_ost_name.strip()} [OST]"
            else:
                display_text = basename

        track = "NOW PLAYING:\n" + display_text
    _set_floating_text("Now Playing Background Music", track, position="bottom left", size=14, inverse=character_round_answer, align="left")
