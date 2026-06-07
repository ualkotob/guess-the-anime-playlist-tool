"""Lightning round runtime orchestration — round setup, cleanup, mode
control flow, and the per-mode reveal-effect dispatch.

The manager is the package coordinator: it imports its sibling collaborators
directly, and lightning runtime state lives in ``core.game_state.state``.
"""
from __future__ import annotations

import copy
import os
import random
import threading
from PIL import Image, ImageTk

from core.game_state import state
from _app_scripts.playback import music, streaming, osd_text, ffmpeg_check, transport
from _app_scripts.queue_round.youtube import youtube_control
from _app_scripts.queue_round.lightning_rounds import (
    characters_overlay,
    character_parts_overlay,
    clues_overlay,
    cover_image_overlay,
    edge_overlay,
    emoji_overlay,
    episode_overlay,
    filter_overlay,
    frame_round,
    grow_overlay,
    image_reveal_overlays,
    lightning_settings,
    mismatch_round,
    peek_dispatch,
    peek_overlay,
    profile_overlay,
    scramble_overlay,
    song_overlay,
    swap_overlay,
    synopsis_overlay,
    tag_cloud_overlay,
    title_overlay,
    trivia_round,
    variety_round,
)
from time import time as _wall_time
from _app_scripts.playback import blind_screen, cache_download, coming_up_ui, image_loader, overlay_primitives
from _app_scripts.playback import progress_overlay as progress_overlay_ops
from _app_scripts.toggles import audio_toggles, censors
from _app_scripts.bonus import bonus
from _app_scripts.playlists import entry_paths
from _app_scripts.information import information_popup
from _app_scripts.file.metadata import metadata_display, metadata_fetch
from _app_scripts.file import scoreboard_control
from _app_scripts.file.web_server import web_server
from _app_scripts.queue_round.lightning_rounds import ost_overlay
from _app_scripts.ui import styling


# ---------------------------------------------------------------------------
# Reveal-effect dispatch (used by COVER/IMAGE/c.reveal rounds via
# update_light_round's start-phase block)
# ---------------------------------------------------------------------------
def apply_reveal_mode(reveal_mode, image_source=None, slide_direction=None,
                      slice_vertical=None, slice_count=None, tile_grid_size=None):
    """
    Apply a reveal mode overlay with the specified parameters.

    Args:
        reveal_mode: The reveal mode type ('standard'/'pixel'/'slide'/'blur'/
            'zoom'/'slice'/'tile'/'swap').
        image_source: PIL Image for pixel mode, or None to use
            character_round_answer image.
        slide_direction: Direction for slide mode ('top', 'bottom', 'left',
            'right'), or None for random/default.
        slice_vertical: Bool for slice orientation, or None for random.
        slice_count: Number of slices, or None for default.
        tile_grid_size: Grid size for tiles, or None for default.
    """
    if reveal_mode == 'standard':
        char_answer = copy.copy(state.lightning.character_round_answer)
        cover_answer = cover_image_overlay.light_cover_image
        if char_answer:
            character_parts_overlay.toggle_character_image_overlay(char_answer[1])
        elif cover_answer:
            character_parts_overlay.toggle_character_image_overlay(cover_answer)
    elif reveal_mode == 'pixel':
        if image_source:
            image_reveal_overlays.generate_pixelation_steps(pil_image=image_source)
        else:
            image_reveal_overlays.generate_pixelation_steps()
        image_reveal_overlays.toggle_character_pixel_overlay()
    elif reveal_mode == 'slide':
        if slide_direction:
            image_reveal_overlays.toggle_character_reveal_overlay(direction=slide_direction)
        else:
            image_reveal_overlays.toggle_character_reveal_overlay(
                direction=random.choice(['top', 'bottom', 'left', 'right']))
    elif reveal_mode == 'blur':
        image_reveal_overlays.toggle_character_blur_reveal_overlay(percent=1.0)
    elif reveal_mode == 'zoom':
        image_reveal_overlays.toggle_character_zoom_reveal_overlay(percent=1.0)
    elif reveal_mode == 'slice':
        vertical = slice_vertical if slice_vertical is not None else random.choice([True, False])
        if slice_count:
            image_reveal_overlays.toggle_slice_overlay(num_revealed=1, num_slices=slice_count, vertical=vertical)
        else:
            image_reveal_overlays.toggle_slice_overlay(num_revealed=1, vertical=vertical)
    elif reveal_mode == 'tile':
        grid_size = tile_grid_size if tile_grid_size else 5
        image_reveal_overlays.toggle_tile_overlay(num_revealed=1, grid_size=grid_size)
    elif reveal_mode == 'swap':
        image_reveal_overlays.toggle_tile_overlay(grid_size=10, swap=True)


# ---------------------------------------------------------------------------
# Title-round setup
# ---------------------------------------------------------------------------
def start_title_round():
    fixed_current_round = state.lightning.fixed_current_round
    if fixed_current_round and fixed_current_round.get("title_variant"):
        title_mode = fixed_current_round.get("title_variant")
    else:
        title_mode = title_overlay.get_next_title_mode(title_overlay.get_base_title())
    state.lightning.current_light_variant = title_mode
    if title_mode == 'scramble':
        scramble_overlay.toggle_scramble_overlay()
    elif title_mode == 'swap':
        swap_overlay.toggle_swap_overlay()
    else:
        set_title_light_text()


def set_title_light_text():
    fixed_current_round = state.lightning.fixed_current_round
    title = title_overlay.get_base_title()
    state.lightning.title_light_string = title

    if fixed_current_round and fixed_current_round.get("reveal_letter_order"):
        order = fixed_current_round.get("reveal_letter_order", "").lower().split(",")
        state.lightning.title_light_letters = order
    else:
        title_light_letters = title_overlay.get_unique_letters(title)
        random.shuffle(title_light_letters)
        state.lightning.title_light_letters = title_light_letters


# ---------------------------------------------------------------------------
# Character type filtering (popularity-weighted)
# ---------------------------------------------------------------------------
def get_char_types_by_popularity(data=None, mode=""):
    lightning_mode_settings = state.playback.lightning_mode_settings
    all_types = []
    valid_types = []
    popularity_limit = True
    for char_type, enabled in lightning_mode_settings.get(mode, {}).get("character_types", {}).items():
        if char_type == "popularity_limit":
            popularity_limit = enabled
        else:
            all_types.append(char_type[0])
            if enabled:
                valid_types.append(char_type[0])
    valid_types = valid_types or all_types
    if popularity_limit:
        if not data:
            currently_playing = state.playback.currently_playing
            data = currently_playing.get("data", {})
        popularity = data.get("popularity", 1000) or 3000
        char_options = copy.copy(valid_types)
        if popularity > 100:
            if "s" in char_options:
                char_options.remove("s")
        if popularity > 250:
            if "a" in char_options:
                char_options.remove("a")
        return char_options or valid_types
    else:
        return valid_types


# ---------------------------------------------------------------------------
# Mode selection (button text + popup + Tk chip)
# ---------------------------------------------------------------------------
def toggle_light_mode(type=None, queue=True, show_popup=True):
    light_mode = state.lightning.light_mode
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    lightning_mode_settings = state.playback.lightning_mode_settings
    light_round_number = state.lightning.light_round_number or 0
    LIGHT_ROUND_LENGTH_DEFAULT = lightning_settings.LIGHT_ROUND_LENGTH_DEFAULT
    light_modes = lightning_settings.light_modes

    if type is None or light_mode == type or (variety_round.variety_light_mode_enabled and type == 'variety'):
        unselect_light_modes()
        coming_up_ui.toggle_coming_up_popup(False, "Lightning Round")
    else:
        unselect_light_modes()
        mode = light_modes[type]
        state.lightning.light_mode = type
        light_mode = type
        if type == 'variety':
            variety_round.variety_light_mode_enabled = True
        else:
            state.lightning_ui.selected_mode.set(f"{mode.get('icon')} {type.upper()}")
            styling.configure_style()
            # Keep the popout dropdown chip in sync with the selected mode.
            if popout_buttons_by_name.get("LIGHTNING DROPDOWN"):
                popout_buttons_by_name["LIGHTNING DROPDOWN"].set(state.lightning_ui.selected_mode.get())
        if queue:
            queue_next_lightning_mode()
        if popout_buttons_by_name.get("lightning_start"):
            popout_buttons_by_name["lightning_start"].configure(text="⏹️ STOP")
        if show_popup and light_round_number == 0:
            image_path = "banners/" + type + "_lightning_round.webp"
            pil_banner = None
            if os.path.exists(image_path):
                pil_banner = Image.open(image_path).convert("RGBA")
                pil_banner = pil_banner.resize((400, 225), Image.LANCZOS)
            mode_length = lightning_mode_settings.get(light_mode, {}).get("length", LIGHT_ROUND_LENGTH_DEFAULT)
            if "c. " in light_mode:
                mode_type = 'character'
            else:
                mode_type = 'anime'
            if type == "variety":
                min_length = None
                max_length = None
                for l in lightning_mode_settings:
                    if not min_length or min_length > lightning_mode_settings[l].get("length", LIGHT_ROUND_LENGTH_DEFAULT):
                        min_length = lightning_mode_settings[l].get("length", LIGHT_ROUND_LENGTH_DEFAULT)
                    if not max_length or max_length < lightning_mode_settings[l].get("length", LIGHT_ROUND_LENGTH_DEFAULT):
                        max_length = lightning_mode_settings[l].get("length", LIGHT_ROUND_LENGTH_DEFAULT)
                mode_length = f"{min_length} - {max_length}"
            mode_desc = f"{mode.get('desc')}\nYou have {mode_length} seconds to guess.\n\n1 PT for the first to guess the {mode_type}!"

            coming_up_ui.toggle_coming_up_popup(True, f"{light_mode.replace('c.', 'Character')} Lightning Round", mode_desc, pil_banner, queue=True)


def unselect_light_modes():
    state.lightning.light_mode = None
    variety_round.variety_light_mode_enabled = False
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    if popout_buttons_by_name.get("lightning_start"):
        popout_buttons_by_name["lightning_start"].configure(text="▶ START")


def select_lightning_mode():
    """Apply the lightning mode currently chosen in the selector dropdown/chip."""
    selected_display = state.lightning_ui.selected_mode.get()
    mode_key = state.lightning_ui.title_to_key[selected_display]
    toggle_light_mode(mode_key)


# ---------------------------------------------------------------------------
# Round start-time picker — picks a random in-bounds start position for
# REGULAR/REVEAL/BLIND/SONG rounds (avoiding censor windows), or honors a
# fixed-round's preset start_time.
# ---------------------------------------------------------------------------
def get_light_round_time():
    fixed_lightning_round_playlist_data = state.lightning.fixed_lightning_round_playlist_data
    fixed_current_round                 = state.lightning.fixed_current_round
    light_round_length                  = state.lightning.light_round_length
    light_round_answer_length           = state.lightning.light_round_answer_length
    light_mode                          = state.lightning.light_mode
    currently_playing                   = state.playback.currently_playing
    player                              = state.widgets.player

    if fixed_lightning_round_playlist_data and fixed_current_round and fixed_current_round.get("start_time") is not None:
        start_time = fixed_current_round.get("start_time")
        if fixed_current_round.get("type") not in ["regular", "reveal", "blind", "song"]:
            start_time = max(start_time - light_round_length, 1.1)
        if start_time is not None:
            return start_time
    length = player.get_length() / 1000
    buffer = 10
    need_censors = light_mode in ['regular', 'reveal']
    need_mute_censors = light_mode in ['regular', 'blind', 'song']
    if not need_censors:
        buffer = 1
    if length < (light_round_length + light_round_answer_length + (buffer * 2) + 1):
        return 1  # If the video is too short, start from 1
    start_time = None
    try_count = 0
    file_censors = censors.get_file_censors(currently_playing.get('filename')) if (need_censors or need_mute_censors) else None
    while start_time is None:
        start_time = random.randrange(buffer, int(length - (light_round_length + light_round_answer_length + buffer)))
        try_count += 1
        if try_count <= 20 and file_censors:
            end_time = start_time + light_round_length
            for censor in file_censors:
                if (((censor.get("mute") or censor.get("skip")) and need_mute_censors) or (not (censor.get("mute") or censor.get("skip")) and need_censors)) and (not (censor['end'] < start_time or censor['start'] > end_time)):
                    start_time = None
                    break
    return start_time


# ---------------------------------------------------------------------------
# Round cleanup — invoked at the start of every round (with new_round=True)
# and at the answer-phase transition (new_round=False). Tears down every
# active overlay, restores mpv state (mismatch hook, original video track,
# audio mute), and resets the cross-cutting round state to its defaults.
# ---------------------------------------------------------------------------
def clean_up_light_round(new_round=False):
    player = state.widgets.player
    fixed_current_round       = state.lightning.fixed_current_round
    light_mode                = state.lightning.light_mode
    lightning_mode_settings   = state.playback.lightning_mode_settings
    disable_video_audio       = state.controls.disable_video_audio
    from _app_scripts.playback import blind_screen as _blind_screen
    _video_frame_active       = _blind_screen._video_frame_active

    if new_round:
        state.lightning.light_answer_wall_start = None
        state.lightning.light_answer_last_tick = None

    mismatch_round._uninstall_mismatch_hook()
    mismatch_round._mismatch_hwnd = 0
    mismatch_round._main_hwnd     = 0
    mismatch_round._note_hwnd     = 0

    # Restore original video track (don't video-remove — that reinitializes VO and causes a glitch;
    # just switching the track ID is seamless and the orphaned external track is dropped on next load)
    if mismatch_round._mismatch_active:
        mismatch_round._mismatch_active = False
        try:
            orig_vid = mismatch_round._mismatch_orig_vid
            if orig_vid is not None:
                player._p.vid = orig_vid
        except Exception:
            pass
        mismatch_round._mismatch_vid_track_id = None
        mismatch_round._mismatch_orig_vid     = None

    if new_round or not fixed_current_round or not fixed_current_round.get("clip_for_answer"):
        streaming.stop_stream(restore=not new_round)
        state.controls.light_muted = False
        if not disable_video_audio:
            audio_toggles.toggle_mute(False, True)

    mismatch_round.mismatch_visuals            = None
    state.lightning.character_round_answer      = None
    cover_image_overlay.light_cover_image       = None
    trivia_round.light_trivia_answer            = None
    episode_overlay.light_name_overlay          = False
    frame_round.frame_light_round_started       = False
    characters_overlay.characters_round_characters = []
    tag_cloud_overlay.tag_cloud_tags            = []
    episode_overlay.light_episode_names         = []
    state.lightning.light_speed_modifier = 1
    state.lightning.light_blind_one_second_count = None
    player.set_rate(1)

    # Per-round-start teardown of the always-destroyable overlays (no answer-phase carry-over).
    for overlay in [
        progress_overlay_ops.set_progress_overlay,
        title_overlay.toggle_title_overlay,
        scramble_overlay.toggle_scramble_overlay,
        swap_overlay.toggle_swap_overlay,
        peek_overlay.toggle_peek_overlay,
        edge_overlay.toggle_edge_overlay,
        grow_overlay.toggle_grow_overlay,
        image_reveal_overlays.toggle_tile_overlay,
        image_reveal_overlays.toggle_character_pixel_overlay,
        image_reveal_overlays.toggle_character_reveal_overlay,
        overlay_primitives.spawn_pulsating_music_note,
        overlay_primitives.toggle_outer_edge_overlay,
        character_parts_overlay.toggle_character_image_overlay,
        image_reveal_overlays.toggle_character_blur_reveal_overlay,
        image_reveal_overlays.toggle_character_zoom_reveal_overlay,
        image_reveal_overlays.toggle_slice_overlay,
    ]:
        overlay(destroy=True)
    if True:  # pending change to not remove for answer
        for overlay in [
            clues_overlay.toggle_clues_overlay,
            song_overlay.toggle_song_overlay,
            characters_overlay.toggle_characters_overlay,
            tag_cloud_overlay.toggle_tag_cloud_overlay,
            episode_overlay.toggle_episode_overlay,
            emoji_overlay.toggle_emoji_overlay,
            profile_overlay.toggle_character_profile_overlay,
        ]:
            overlay(destroy=True)
    filter_overlay.toggle_filter_vf(destroy=True)
    if new_round:
        blind_screen.set_video_frame(False)
    elif _video_frame_active:
        # Clip/OST answer phases play the main theme, not the clip — use framed_video
        # (not framed_video_clip) to decide whether the frame carries over.
        _clip_for_answer = fixed_current_round and fixed_current_round.get("clip_for_answer")
        if light_mode in ('clip', 'ost') and not _clip_for_answer:
            if lightning_mode_settings.get("_misc_settings", {}).get("framed_video"):
                blind_screen.set_video_frame(True, answer_phase=True)
            else:
                blind_screen.set_video_frame(False)
        else:
            blind_screen.set_video_frame(True, answer_phase=True)
    if not new_round and fixed_current_round and fixed_current_round.get("overlay_during_answer") and synopsis_overlay._mc_last_choices:
        synopsis_overlay.toggle_mc_choices_overlay(highlight=True)
    else:
        synopsis_overlay.toggle_mc_choices_overlay(destroy=True)
    if new_round or (not (fixed_current_round and fixed_current_round.get("overlay_during_answer"))):
        synopsis_overlay.toggle_synopsis_overlay(destroy=True)
    for info in [osd_text.bottom_info, osd_text.top_info]:
        info()
    scoreboard_control.send_command("show")


# ---------------------------------------------------------------------------
# Answer-phase → next-round transition. Tears down the answer-phase wall-clock
# state, halts playback, raises the blind, and schedules play_next on the
# main Tk loop. Called from update_light_round when the answer phase expires.
# ---------------------------------------------------------------------------
def light_round_transition():
    state.lightning.light_answer_wall_start = None
    state.lightning.light_answer_last_tick = None
    state.lightning.light_round_started = False
    state.lightning._showed_lightning_answer = False
    if state.controls.autoplay_toggle == 2:
        transport.stop()
        return
    state.controls.video_stopped = True
    state.widgets.player.pause()
    osd_text.set_countdown()
    if web_server.is_running():
        web_server.clear_timer()
    information_popup.toggle_title_popup(False, instant=True)
    from _app_scripts.playback import blind_screen as _blind_screen
    blind_screen.set_black_screen(True)
    if _blind_screen._video_frame_active:
        blind_screen.set_video_frame(False)
    clean_up_light_round(new_round=True)
    state.widgets.root.after(500, transport.play_next)


# ---------------------------------------------------------------------------
# Per-tick update for the current lightning round. Drives every per-mode
# overlay animation, the answer-phase transition, the round-start setup
# for every light_mode branch, and the streaming-clip pipeline. Ported
# from main unchanged in structure; lightning runtime scalars live on
# `state.lightning` and collaborators are called on their sibling modules
# directly.
# ---------------------------------------------------------------------------
def update_light_round(time):
    # During clip/OST rounds use actual player position relative to stream_start_time.
    # _stream_wall_start is used purely as a sentinel — True once the initial seek has fired.
    # Using player position means the timer naturally pauses when the player is paused.
    if streaming.currently_streaming and state.lightning.light_round_start_time is not None:
        if streaming.get_stream_wall_start() is not None:
            elapsed = max(0, state.widgets.player.get_time() / 1000.0 - state.lightning.stream_start_time)
        else:
            elapsed = 0
        time = state.lightning.light_round_start_time + elapsed
    # Disarm the round once the track's start window passes with no mode active, so that
    # arming a light_mode mid-track waits for the next track instead of firing immediately.
    # When a mode IS active, `armed` is left set regardless of position — a slow-loading
    # theme whose first observed position is already past 1s must still be able to start.
    if state.lightning.light_round_armed and not state.lightning.light_mode and time >= 1:
        state.lightning.light_round_armed = False
    if not state.lightning.light_round_start_time and (state.lightning.light_mode == 'frame' or frame_round.frame_light_round_started):
        if time < 1 and not frame_round.frame_light_round_started:
            state.widgets.player.pause()
            frame_round.setup_frame_light_round()
        return
    if (time > 1 or state.lightning.light_answer_wall_start is not None) and state.lightning.light_round_start_time != None and state.lightning.light_round_started:
        # Once the wall clock is set we're permanently in the answer phase regardless of Player position
        # (seeking the theme backwards must not flip us back into question-phase logic)
        _in_answer_phase = state.lightning.light_answer_wall_start is not None or time >= state.lightning.light_round_start_time + state.lightning.light_round_length
        _now = _wall_time()
        if _in_answer_phase and state.lightning.light_answer_wall_start is None:
            state.lightning.light_answer_wall_start = _now
            state.lightning.light_answer_last_tick = _now
        # Pause compensation: when the player is paused, slide the reference
        # start forward so that _answer_elapsed stays frozen.  Checking
        # player.is_playing() directly is reliable and avoids false positives
        # from OS timer jitter that plagued the old gap-threshold approach.
        if state.lightning.light_answer_wall_start is not None and state.lightning.light_answer_last_tick is not None:
            if not state.widgets.player.is_playing():
                state.lightning.light_answer_wall_start += _now - state.lightning.light_answer_last_tick
        state.lightning.light_answer_last_tick = _now
        _answer_elapsed = (_now - state.lightning.light_answer_wall_start) if state.lightning.light_answer_wall_start is not None else 0
        if _in_answer_phase and _answer_elapsed >= state.lightning.light_round_answer_length:
            light_round_transition()
        elif _in_answer_phase:
            start_str = "next"
            blind_length = state.playback.lightning_mode_settings.get("blind", {}).get("length", lightning_settings.LIGHT_ROUND_LENGTH_DEFAULT)
            BLIND_ONE_SECOND_TIME = 4
            if state.lightning.light_blind_one_second_count != None and state.lightning.light_blind_one_second_count < blind_length:
                if state.lightning.light_blind_one_second_count % BLIND_ONE_SECOND_TIME == 0:
                    state.lightning.light_blind_one_second_count += 1
                    state.widgets.player.pause()
                    progress_overlay_ops.set_progress_overlay(state.lightning.light_round_length*100, state.lightning.light_round_length*100)
                    def update_light_blind_count():
                        if not state.lightning.light_blind_one_second_count:
                            return
                        if (state.lightning.light_blind_one_second_count + 1) % BLIND_ONE_SECOND_TIME == 0:
                            state.widgets.player.set_time(round(float(state.lightning.light_round_start_time) * 1000))
                            state.widgets.player.play()
                        state.lightning.light_blind_one_second_count += 1
                        osd_text.set_countdown(round(blind_length - state.lightning.light_blind_one_second_count))
                    for s in range(BLIND_ONE_SECOND_TIME-1):
                        state.widgets.root.after(1000 * (s+1), update_light_blind_count)
                    osd_text.set_countdown(round(blind_length - state.lightning.light_blind_one_second_count))
            else:
                if not state.lightning._showed_lightning_answer:
                    state.lightning._showed_lightning_answer = True
                    char_answer = copy.copy(state.lightning.character_round_answer)
                    cover_answer = cover_image_overlay.light_cover_image
                    image_answer_source = None  # source text shown as answer (no header, width_max=0.55)
                    if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("type") == "image":
                        answer_image_url = (state.lightning.fixed_current_round.get("answer_image_url") or "").strip()
                        answer_show_both = state.lightning.fixed_current_round.get("answer_show_both", False)
                        if answer_image_url:
                            try:
                                answer_image = image_loader.load_image_from_url(answer_image_url, size=None)
                                if answer_show_both:
                                    if cover_image_overlay.light_cover_image:
                                        cover_answer = [cover_image_overlay.light_cover_image, answer_image]
                                    else:
                                        cover_answer = answer_image
                                else:
                                    cover_answer = answer_image
                            except Exception:
                                pass
                            # Collect source text to show as answer instead of the IMAGE SOURCE header
                            if cover_image_overlay.last_image_source[0] == state.playback.currently_playing.get("filename") and cover_image_overlay.last_image_source[1]:
                                if state.lightning.fixed_current_round.get("image_source"):
                                    image_answer_source = state.lightning.fixed_current_round.get("image_source")
                                else:
                                    src_url = cover_image_overlay.last_image_source[1]
                                    image_answer_source = src_url.split('/')[2] if src_url.startswith('http') else src_url
                    trivia_answer = trivia_round.light_trivia_answer
                    if mismatch_round.mismatch_visuals:
                        top_info_data = "MISMATCHED VISUALS:\n" + mismatch_round.mismatch_visuals
                    elif (streaming.last_streamed[0] == state.playback.currently_playing.get("filename") and streaming.last_streamed[1] and streaming.last_streamed[1] != "Trailer"
                            and not (state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("clip_source_as_song"))):
                        top_info_data = f"YOUTUBE VIDEO:\n{streaming.last_streamed[1]}\nby {streaming.last_streamed[3] or ''}"
                    elif image_answer_source:
                        top_info_data = None  # will be shown via top_info(image_answer_source) below
                    elif cover_image_overlay.last_image_source[0] == state.playback.currently_playing.get("filename") and cover_image_overlay.last_image_source[1]:
                        if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("image_source"):
                            domain = state.lightning.fixed_current_round.get("image_source")
                        else:
                            # Extract domain from URL
                            url = cover_image_overlay.last_image_source[1]
                            domain = url.split('/')[2] if url.startswith('http') else url
                        top_info_data = f"IMAGE SOURCE:\n{domain}"
                    else:
                        top_info_data = None
                    if state.lightning.light_mode == 'ost' and not (state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("clip_for_answer")):
                        ost_overlay._show_ost_cover()  # hide video during transition; removed by stop_stream
                    information_popup.toggle_title_popup(True)
                    blind_screen.set_black_screen(False)
                    update_light_round_number()
                    clean_up_light_round()
                    max_width_size = 0.55 if (state.lightning.light_round_answer_length < 10) else 0.5

                    if synopsis_overlay.synopsis_start_index is not None and state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("overlay_during_answer"):
                        synopsis_overlay.toggle_synopsis_overlay(text=synopsis_overlay.get_light_synopsis_string())
                    if top_info_data:
                        osd_text.top_info(top_info_data, 20)
                    if char_answer:
                        osd_text.top_info(char_answer[0], width_max=max_width_size) 
                        character_parts_overlay.toggle_character_image_overlay(char_answer[1])
                    if cover_answer:
                        character_parts_overlay.toggle_character_image_overlay(cover_answer)
                    if trivia_answer:
                        _uses_mc_highlight = (state.lightning.fixed_current_round or {}).get("overlay_during_answer") and synopsis_overlay._mc_last_choices
                        if _uses_mc_highlight:
                            # Correct answer shown via highlighted MC overlay; show header only
                            _ans_header = (state.lightning.fixed_current_round or {}).get("answer_header", "")
                            if _ans_header:
                                osd_text.top_info(_ans_header, width_max=max_width_size)
                        else:
                            _ans_header = (state.lightning.fixed_current_round or {}).get("answer_header", "")
                            _ans_display = f"{_ans_header}:\n{trivia_answer}" if _ans_header else trivia_answer
                            osd_text.top_info(_ans_display, width_max=max_width_size)
                    if image_answer_source:
                        osd_text.top_info(image_answer_source, width_max=max_width_size)
                    # For clip_for_answer rounds the stream keeps playing during the answer phase.
                    # If clip_replay_for_answer is set, seek back to clip_start_time (or 0) to
                    # replay the clip from the beginning. Otherwise seek forward to where the
                    # answer portion starts (stream_start_time + round_length).
                    if (state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("clip_for_answer")
                            and state.lightning.stream_start_time is not None):
                        if state.lightning.fixed_current_round.get("clip_replay_for_answer"):
                            _replay_target_sec = state.lightning.fixed_current_round.get("clip_start_time") or 0
                            state.widgets.player.set_time(round(_replay_target_sec * 1000))
                            state.widgets.player.play()
                        else:
                            _clip_answer_target_ms = int((state.lightning.stream_start_time + state.lightning.light_round_length) * 1000)
                            if abs(state.widgets.player.get_time() - _clip_answer_target_ms) > 2000:
                                state.widgets.player.set_time(_clip_answer_target_ms)
                    # For fixed rounds where start_time means the theme's answer entry point
                    # (i.e. non-regular/peek/blind/song types), seek the theme to start_time and unmute
                    # so the theme plays during the answer phase regardless of where Player currently is.
                    _seek_types = ["regular", "reveal", "blind", "song"]
                    if (state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("start_time") is not None
                            and state.lightning.fixed_current_round.get("type") not in _seek_types
                            and not state.lightning.fixed_current_round.get("clip_for_answer")):
                        state.widgets.player.set_time(round(state.lightning.fixed_current_round["start_time"] * 1000))
                        state.widgets.player.play()
                        audio_toggles.toggle_mute(False, True)
                if not state.lightning.light_mode or (state.lightning.fixed_lightning_round_playlist_data and state.lightning.fixed_lightning_round_playlist_data.get("current_index") == state.lightning.fixed_lightning_round_playlist_data.get("round_count") - 1):
                    start_str = "end"
                osd_text.set_countdown(start_str + " in..." + str(round(state.lightning.light_round_answer_length - _answer_elapsed)))
        else:
            time_left = (state.lightning.light_round_length-(time - state.lightning.light_round_start_time))
            if time_left < 1 and state.lightning.light_speed_modifier != 1:
                state.lightning.light_speed_modifier = 1
                state.widgets.player.set_rate(state.lightning.light_speed_modifier)
            if state.lightning.current_light_mode == 'song' or song_overlay.song_overlay_boxes:
                show_title_time = state.lightning.light_round_length if not state.lightning.fixed_current_round else state.lightning.fixed_current_round.get("song_title_reveal_time", state.lightning.light_round_length)
                show_artist_time = state.lightning.light_round_length * 0.75 if not state.lightning.fixed_current_round else state.lightning.fixed_current_round.get("song_artist_reveal_time", state.lightning.light_round_length * 0.75)
                show_slug_time = state.lightning.light_round_length * 0.5 if not state.lightning.fixed_current_round else state.lightning.fixed_current_round.get("song_slug_reveal_time", state.lightning.light_round_length * 0.5)
                show_music_time = state.lightning.light_round_length * (1/3) if not state.lightning.fixed_current_round else state.lightning.fixed_current_round.get("song_music_reveal_time", state.lightning.light_round_length * (1/3))
                song_overlay.toggle_song_overlay(show_title=time_left<=show_title_time, show_artist=time_left<=show_artist_time, show_theme=time_left<=show_slug_time, show_music=time_left<=show_music_time)
                state.widgets.player.audio_set_mute(time_left > show_music_time)
                music.play_background_music(time_left > show_music_time)
            elif clues_overlay._clues_cell_values:
                data = state.playback.currently_playing.get("data")
                if time_left <= 15:
                    clues_overlay._clues_cell_values["Tags"] = "\n".join(information_popup.get_tags(data))
                else:
                    clues_overlay._clues_cell_values["Tags"] = f"in...{round(time_left-15)}"
                if time_left <= 10:
                    clues_overlay._clues_cell_values["Episodes"] = information_popup.get_episode_display(data, suffix="")
                    clues_overlay._clues_cell_values["Score"]    = f"{data.get('score')}\n#{data.get('rank')}"
                    _members_num = metadata_display._safe_int(data.get('members', 0), 0)
                    clues_overlay._clues_cell_values["Members"]  = f"{_members_num:,}\n#{data.get('popularity') or 'N/A'}"
                else:
                    clues_overlay._clues_cell_values["Episodes"] = f"in...{round(time_left-10)}"
                    clues_overlay._clues_cell_values["Score"]    = f"in...{round(time_left-10)}"
                    clues_overlay._clues_cell_values["Members"]  = f"in...{round(time_left-10)}"
                if time_left <= 5:
                    clues_overlay._clues_cell_values["Song"] = f"{data.get('slug')}: {information_popup.get_song_string(data)}"
                else:
                    clues_overlay._clues_cell_values["Song"] = f"SONG in...{round(time_left-5)}"
                clues_overlay._draw_clues_canvas()
            elif synopsis_overlay.synopsis_start_index is not None:
                answer_time = 8
                if trivia_round.light_trivia_answer:
                    answer_time = 6
                synopsis_words = synopsis_overlay.get_light_synopsis_string().split(" " if state.lightning.fixed_current_round else None)
                _reveal_speed = state.lightning.fixed_current_round.get("reveal_speed") if state.lightning.fixed_current_round else None
                if _reveal_speed is not None:
                    # reveal_speed = seconds from start at which full text is shown; 0 = show all immediately
                    elapsed = state.lightning.light_round_length - time_left
                    if _reveal_speed <= 0:
                        progress = 1.0
                    else:
                        progress = max(0.0, min(1.0, elapsed / _reveal_speed))
                else:
                    reveal_duration = state.lightning.light_round_length - answer_time
                    if reveal_duration > 0:
                        elapsed = state.lightning.light_round_length - time_left
                        progress = max(0.0, min(1.0, elapsed / reveal_duration))
                    else:
                        progress = 1.0
                word_count = max(1, round(len(synopsis_words) * progress))
                shown_text = " ".join(synopsis_words[:word_count])
                synopsis_overlay.toggle_synopsis_overlay(text=shown_text)
            elif state.lightning.current_light_mode == 'emoji' or emoji_overlay.emoji_overlay_window:
                # Reveal emojis one by one over the round
                emojis = emoji_overlay.get_emoji_clues_for_title(state.playback.currently_playing.get("data"))
                elapsed = state.lightning.light_round_length - max(0, time_left)
                progress = max(0, min(1, elapsed / state.lightning.light_round_length))
                emoji_count = max(1, round(len(emojis) * progress)+1)
                emoji_overlay.toggle_emoji_overlay(emojis=emojis, max_emojis=emoji_count)
            elif progress_overlay_ops.is_light_progress_bar_active():
                progress_overlay_ops.set_progress_overlay(round((time - state.lightning.light_round_start_time)*100), state.lightning.light_round_length*100)
                if streaming.currently_streaming and (not state.lightning.fixed_current_round or state.lightning.fixed_current_round.get("reveal_title_halfway")):
                    half_time = (state.lightning.light_round_length / 2)
                    track_name = ost_overlay.extract_track_name_from_youtube_title(streaming.last_streamed[1], state.playback.currently_playing.get("data", {}))
                    if track_name.strip() != "":
                        if time_left >= half_time:
                            osd_text.bottom_info(f"TRACK NAME in...{round(time_left-half_time)}")
                        else:
                            osd_text.bottom_info(track_name)
            elif (state.lightning.current_light_mode == 'title' and state.lightning.current_light_variant == 'reveal') or title_overlay.title_overlay_window:
                if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("reveal_letter_order"):
                    starting_letters = int(state.lightning.fixed_current_round.get("reveal_starting_count", 0))
                    final_count = len(state.lightning.fixed_current_round.get("reveal_letter_order", "").split(","))
                    reveal_count = final_count - starting_letters
                    interval = reveal_count / 5 if reveal_count > 0 else 1
                else:
                    starting_letters = min(5, max(1, len(state.lightning.title_light_letters) // 5))
                    interval = len(state.lightning.title_light_letters) * 0.09
                    final_count = round((5*interval)+starting_letters)
                word_num = min(final_count, int(((state.lightning.light_round_length-time_left)/3)*interval)+starting_letters)
                osd_text.bottom_info(f"{word_num}/{final_count} REVEALS", inverse=state.lightning.character_round_answer)
                title_overlay.toggle_title_overlay(title_overlay.get_title_light_string(word_num))
            elif scramble_overlay.scramble_overlay_root or state.lightning.current_light_variant == 'scramble':
                if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("scramble_place_order"):
                    order_count = len([x for x in state.lightning.fixed_current_round["scramble_place_order"].split(",") if x.strip().isdigit()])
                    total_letters = min(order_count, len(scramble_overlay.scramble_overlay_letters))
                else:
                    total_letters = max(1, round(len(scramble_overlay.scramble_overlay_letters) * 0.45))
                placement_cutoff = state.lightning.light_round_length * (2 / 3)

                if time_left >= state.lightning.light_round_length - placement_cutoff:
                    # We're still in the placement phase
                    elapsed = state.lightning.light_round_length - time_left
                    progress = elapsed / placement_cutoff  # 0 to 1
                    word_num = int(total_letters * progress)
                else:
                    # Final 1/3 — all letters placed, time to guess
                    word_num = total_letters
                osd_text.bottom_info(f"{word_num}/{total_letters} PLACEMENTS", inverse=state.lightning.character_round_answer)
                scramble_overlay.toggle_scramble_overlay(num_letters=word_num)
            elif swap_overlay.swap_overlay_root or state.lightning.current_light_variant == 'swap':
                # Total swaps you want to show, based on number of pairs
                if len(swap_overlay.swap_pairs) <= 2:
                    total_swaps = 0
                else:
                    total_swaps = round(len(swap_overlay.swap_pairs) * 0.4)

                # Define the cutoff point — after this, no more swaps
                swap_cutoff = state.lightning.light_round_length * (2 / 3)

                if time_left >= state.lightning.light_round_length - swap_cutoff:
                    # Still in swap phase
                    elapsed = state.lightning.light_round_length - time_left
                    progress = elapsed / swap_cutoff  # 0 to 1
                    word_num = int(total_swaps * progress)
                else:
                    # In the final 1/3 — guessing phase
                    word_num = total_swaps
                osd_text.bottom_info(f"{word_num}/{total_swaps} SWAPS", inverse=state.lightning.character_round_answer)
                swap_overlay.toggle_swap_overlay(num_swaps=word_num)
            elif peek_overlay.peek_overlay1:
                gap = peek_dispatch.get_peek_gap(state.playback.currently_playing.get("data"))
                peek_overlay.toggle_peek_overlay(direction=peek_dispatch.peek_light_direction, progress=((state.lightning.light_round_length-time_left)/state.lightning.light_round_length)*100, gap=gap)
                music.now_playing_background_music(music.music_files[music.current_music_index])
            elif edge_overlay.edge_overlay_box:
                edge_max = max(15, min(70, (state.playback.currently_playing.get("data").get('popularity') or 3000)/12))
                progress = (state.lightning.light_round_length - time_left) / state.lightning.light_round_length
                block_percent = 100 - (edge_max * progress)  # from 100% to 80%
                edge_overlay.toggle_edge_overlay(block_percent=block_percent)
                music.now_playing_background_music(music.music_files[music.current_music_index])
            elif grow_overlay.grow_overlay_boxes:
                grow_max = max(20, min(60, (state.playback.currently_playing.get("data").get('popularity') or 3000)/10))
                progress = (state.lightning.light_round_length - time_left) / state.lightning.light_round_length
                block_percent = 100 - (grow_max * progress)  # from 100% to 80%
                grow_overlay.toggle_grow_overlay(block_percent=block_percent, position=grow_overlay.grow_position)
                music.now_playing_background_music(music.music_files[music.current_music_index])
            elif filter_overlay.filter_vf_active:
                progress = (state.lightning.light_round_length - time_left) / state.lightning.light_round_length
                progress = min(max(progress, 0.0), 1.0)
                filter_overlay.toggle_filter_vf(filter_overlay._filter_vf_variant, progress)
                filter_overlay._update_filter_intensity_bottom_label(filter_overlay._filter_vf_variant, progress)
                music.now_playing_background_music(music.music_files[music.current_music_index])
            elif characters_overlay.characters_overlay_boxes:
                reveal_num = min(4, (int(state.lightning.light_round_length - (time_left)) // (state.lightning.light_round_length // 4)) + 1)
                characters_overlay.toggle_characters_overlay(num_characters=reveal_num)
                osd_text.bottom_info(f"{reveal_num}/{4}", inverse=state.lightning.character_round_answer)
            elif character_parts_overlay.character_image_overlay:
                character_parts_overlay._update_character_image_overlay()
            elif image_reveal_overlays.character_pixel_overlay:
                total_steps = len(image_reveal_overlays.character_pixel_images)
                step_num = min(total_steps-1, (int(state.lightning.light_round_length - (time_left)) // (state.lightning.light_round_length // total_steps)))
                image_reveal_overlays.toggle_character_pixel_overlay(step=step_num)
                osd_text.bottom_info(f"{step_num+1}/{total_steps}", inverse=state.lightning.character_round_answer)
            elif image_reveal_overlays.blur_reveal_image_window:
                progress = (state.lightning.light_round_length - max(0, time_left)) / state.lightning.light_round_length
                progress = min(max(progress, 0.0), 1.0)
                blur_percent = 100 - (100 * progress)
                image_reveal_overlays.toggle_character_blur_reveal_overlay(percent=blur_percent / 100, destroy=False)
                osd_text.bottom_info(f"BLUR: {round(blur_percent)}%", inverse=state.lightning.character_round_answer)
            elif image_reveal_overlays.zoom_reveal_image_window:
                progress = ((state.lightning.light_round_length - 1) - max(0, time_left-1)) / (state.lightning.light_round_length-1)
                progress = min(max(progress, 0.0), 1.0)
                zoom_percent = 100 - (100 * progress)
                image_reveal_overlays.toggle_character_zoom_reveal_overlay(percent=zoom_percent / 100, destroy=False)
                osd_text.bottom_info(f"ZOOM OUT: {round(100 - zoom_percent)}%", inverse=state.lightning.character_round_answer)
            elif image_reveal_overlays.slice_overlay_window:
                progress = (state.lightning.light_round_length - max(0, time_left-1)) / state.lightning.light_round_length
                progress = min(max(progress, 0.0), 1.0)
                total_parts = len(image_reveal_overlays.slice_overlay_parts) // 2
                slices_to_show = max(1, min(total_parts, round(total_parts * progress)))
                image_reveal_overlays.toggle_slice_overlay(num_revealed=slices_to_show)
                osd_text.bottom_info(f"{slices_to_show}/{total_parts}", inverse=state.lightning.character_round_answer)
            elif image_reveal_overlays.tile_overlay_window:
                if not image_reveal_overlays.tile_overlay_swap:
                    progress = (state.lightning.light_round_length - max(0, time_left-1)) / state.lightning.light_round_length
                    progress = min(max(progress, 0.0), 1.0)
                    total_parts = len(image_reveal_overlays.tile_overlay_parts) // 2
                    tiles_to_show = max(1, min(total_parts, round(total_parts * progress)))
                    image_reveal_overlays.toggle_tile_overlay(num_revealed=tiles_to_show)
                    osd_text.bottom_info(f"{tiles_to_show}/{total_parts}", inverse=state.lightning.character_round_answer)
                else:
                    # Swap tiles one by one over the round
                    total_swaps = len(image_reveal_overlays.tile_overlay_parts) // 4
                    elapsed = state.lightning.light_round_length - max(0, time_left)
                    progress = max(0, min(1, elapsed / state.lightning.light_round_length))
                    swaps_to_show = max(1, round(total_swaps * progress))
                    image_reveal_overlays.toggle_tile_overlay(num_revealed=swaps_to_show, swap=True)
                    osd_text.bottom_info(f"{swaps_to_show}/{total_swaps} SWAPS", inverse=state.lightning.character_round_answer)
            elif image_reveal_overlays.reveal_image_window:
                progress = (state.lightning.light_round_length - max(0, time_left-1)) / state.lightning.light_round_length
                progress = min(max(progress, 0.0), 1.0)
                block_percent = 100 - (100 * progress)
                image_reveal_overlays.toggle_character_reveal_overlay(percent=block_percent / 100, destroy=False)
            elif profile_overlay.profile_overlay_window:
                total_words = 70 #len(bio_text.split())

                progress = (state.lightning.light_round_length - time_left) / state.lightning.light_round_length

                # Reveal bio over the first 10 seconds
                max_bio_time = 12
                if time_left > state.lightning.light_round_length - max_bio_time:
                    partial = 1 - ((time_left - (state.lightning.light_round_length - max_bio_time)) / max_bio_time)
                    words_to_show = int(partial * total_words)
                else:
                    words_to_show = total_words

                # Show image in last 5 seconds
                image_countdown = max(0, int(time_left - 3))

                # Call the toggle
                profile_overlay.toggle_character_profile_overlay(word_count=words_to_show, image_countdown=image_countdown)
                if image_countdown > 0:
                    osd_text.bottom_info(f"IMAGE IN {image_countdown}...", inverse=True)
                else:
                    osd_text.bottom_info()
            elif tag_cloud_overlay.tag_cloud_tags:
                starting_tags = 1
                final_count = len(tag_cloud_overlay.tag_cloud_tags)
                time_left_t = time_left - 5
                light_round_length_t = state.lightning.light_round_length - 5

                # Use the actual light round length
                progress = (light_round_length_t - time_left_t) / (light_round_length_t)
                progress = max(0, min(progress, 1))  # Clamp between 0 and 1

                # Calculate how many tags to show
                tags_num = min(final_count, int(progress * final_count) + starting_tags)

                # Update overlay and label
                osd_text.bottom_info(f"{tags_num}/{final_count}")
                tag_cloud_overlay.toggle_tag_cloud_overlay(tags_num)
            elif episode_overlay.light_episode_names:
                total_eps = min(len(episode_overlay.light_episode_names), 6)
                reveal_num = min(6, (int(state.lightning.light_round_length - time_left) // (state.lightning.light_round_length // total_eps)) + 1)
                episode_overlay.toggle_episode_overlay(reveal_num)
                osd_text.bottom_info(f"{reveal_num}/{total_eps}", inverse=state.lightning.character_round_answer)
            if edge_overlay.edge_overlay_box:
                osd_text.set_countdown(round(time_left/state.lightning.light_speed_modifier), position="center")
            elif state.lightning.light_blind_one_second_count is not None:
                blind_length = state.playback.lightning_mode_settings.get("blind", {}).get("length", lightning_settings.LIGHT_ROUND_LENGTH_DEFAULT)
                osd_text.set_countdown(round(blind_length - state.lightning.light_blind_one_second_count))
            else:
                osd_text.set_countdown(round(time_left/state.lightning.light_speed_modifier), inverse=state.lightning.character_round_answer)
    if state.lightning.light_mode and state.lightning.light_answer_wall_start is None:
        if time < 1:
            coming_up_ui.toggle_coming_up_popup(False, "Lightning Round")
        if not state.lightning.light_round_started and state.lightning.light_round_armed:
            state.lightning.light_round_started = True
            state.lightning.light_round_armed = False
            state.lightning._showed_lightning_answer = False
            state.lightning.current_light_mode = state.lightning.light_mode
            if state.playback.lightning_mode_settings.get("_misc_settings", {}).get("framed_video"):
                state.widgets.root.after(300, blind_screen.set_video_frame, True)
            if state.lightning.light_mode in ['regular', 'reveal']:
                state.widgets.root.after(500, blind_screen.set_black_screen, False)
            def set_double_speed():
                state.lightning.light_speed_modifier = 2
                state.widgets.player.set_rate(state.lightning.light_speed_modifier)
                state.lightning.light_round_length = state.lightning.light_round_length * state.lightning.light_speed_modifier
                osd_text.bottom_info(f"x{state.lightning.light_speed_modifier} SPEED")
            def set_one_second():
                state.lightning.light_blind_one_second_count = 0
                state.lightning.light_round_length = 1
                osd_text.bottom_info("ONE SECOND")
            if state.lightning.light_round_start_time is None:
                state.lightning.light_round_start_time = get_light_round_time()
            if state.playback.lightning_mode_settings.get(state.lightning.light_mode, {}).get("muted"):
                audio_toggles.toggle_mute(True)
            if state.lightning.light_mode == 'blind':
                if state.lightning.fixed_current_round:
                    blind_mode = state.lightning.fixed_current_round.get("blind_variant", "standard")
                    if state.lightning.fixed_current_round.get("blind_header"):
                        osd_text.top_info(state.lightning.fixed_current_round.get("blind_header"))
                else:
                    blind_variants = state.playback.lightning_mode_settings.get("blind",{}).get("variants",{})
                    standard, double_speed, mismatch, one_second = blind_variants.get("standard"), blind_variants.get("double_speed"), blind_variants.get("mismatch"), blind_variants.get("one_second")
                    blind_modes = ['standard', 'standard', 'standard', 'mismatch']
                    allowed_blind_modes = []
                    for m in blind_modes:
                        if blind_variants.get(m):
                            allowed_blind_modes.append(m)
                    # Only fall back to the full list for non-mismatch modes; mismatch
                    # requires its own setup and shouldn't be selected unless enabled.
                    allowed_blind_modes = allowed_blind_modes or [m for m in blind_modes if m != 'mismatch']
                    blind_mode = random.choice(allowed_blind_modes)
                if blind_mode == "mismatch":
                    # Explicitly init the round here — the mismatch seek moves the
                    # player past position 1s so the normal time < 1 gate won't fire.
                    if not state.lightning.light_round_started:
                        state.lightning.light_round_started = True
                        progress_overlay_ops.set_progress_overlay(0, state.lightning.light_round_length * 100)
                    # Mute the player directly (not toggle_mute — that triggers background music)
                    # so the theme audio doesn't play from position 0 while we load the
                    # mismatch video and seek to light_round_start_time.
                    state.widgets.player.audio_set_mute(True)
                    def _start_mismatch_after_theme(theme_path):
                        if state.playback.currently_playing.get("filename") != _cur_fn:
                            state.widgets.player.audio_set_mute(False)
                            return
                        if not theme_path:
                            state.widgets.player.audio_set_mute(False)
                            return
                        # Add the mismatch video as an external track on the main player.
                        # Stay paused through video-add AND the seek so mpv's internal
                        # sync operations don't interrupt the audio pipeline.
                        try:
                            mismatch_round._mismatch_orig_vid = state.widgets.player._p.vid
                            _was_paused = state.widgets.player._p.pause
                            if not _was_paused:
                                state.widgets.player._p.pause = True
                            state.widgets.player._p.command('video-add', theme_path, 'select')
                            # Seek to round start while still paused — no audio disruption
                            try:
                                state.widgets.player._p.seek(float(state.lightning.light_round_start_time), 'absolute')
                            except Exception:
                                pass
                            # Find the newly added external video track ID
                            mismatch_round._mismatch_vid_track_id = None
                            try:
                                tracks = state.widgets.player._p.track_list or []
                                ext_vids = [t for t in tracks if t.get('type') == 'video' and t.get('external')]
                                if ext_vids:
                                    mismatch_round._mismatch_vid_track_id = ext_vids[-1].get('id')
                            except Exception:
                                pass
                            # Always unpause — we want the round playing regardless of initial state
                            state.widgets.player._p.pause = False
                        except Exception as e:
                            print(f"[mismatch] exception in video-add block: {e}")
                            state.widgets.player.audio_set_mute(False)
                            return
                        # Unmute now that we're at the right position with the right video
                        state.widgets.player.audio_set_mute(False)
                        audio_toggles.set_volume(state.controls.volume_level)
                        mismatch_round._mismatch_active = True
                        overlay_primitives.spawn_pulsating_music_note()
                        blind_screen.set_black_screen(False)
                        osd_text.top_info("MISMATCHED VISUALS")
                        osd_text.bottom_info("GUESS BY MUSIC ONLY")
                        update_light_round_number()
                    _cur_fn = state.playback.currently_playing.get("filename")
                    def _theme_worker():
                        theme_path = state.metadata.directory_files.get(mismatch_round.get_mismatched_theme())
                        state.widgets.root.after(0, _start_mismatch_after_theme, theme_path)
                    threading.Thread(target=_theme_worker, daemon=True).start()
                else:
                    if not state.lightning.fixed_current_round:
                        is_op = mismatch_round.is_slug_op(state.playback.currently_playing.get('data', {}).get('slug', ""))
                        def pick_double_or_one_second(is_op):
                            if double_speed and one_second:
                                if not is_op or random.randint(1, 2) == 1:
                                    return "double_speed"
                                else:
                                    return "one_second"
                            elif double_speed:
                                return "double_speed"
                            elif one_second:
                                return "one_second"
                        if double_speed or one_second:
                            if not standard:
                                blind_mode = pick_double_or_one_second(is_op)
                            else:
                                popularity = state.playback.currently_playing.get("data", {}).get("popularity", 1000) or 3000
                                if (popularity <= 100 and random.randint(1, 3) == 1) or (popularity <= 250 and random.randint(1, 6) == 1):
                                    blind_mode = pick_double_or_one_second(is_op)
                    if blind_mode == "double_speed":
                        set_double_speed()
                    elif blind_mode == "one_second":
                        set_one_second()
                    progress_overlay_ops.set_progress_overlay(0, state.lightning.light_round_length*100)
            elif state.lightning.light_mode == 'clues':
                clues_overlay.toggle_clues_overlay()
            elif state.lightning.light_mode == 'song':
                song_overlay.toggle_song_overlay(show_title=False, show_artist=False, show_theme=False, show_music=False)
            elif state.lightning.light_mode == 'synopsis':
                synopsis_overlay.pick_synopsis()
                synopsis_overlay.toggle_synopsis_overlay(text=synopsis_overlay.get_light_synopsis_string(words = 1))
            elif state.lightning.light_mode == 'trivia':
                trivia_data = lightning_queue_data.get(state.playback.currently_playing.get("filename", {}), {}).get("trivia", [])
                trivia_round.set_light_trivia(trivia_data=trivia_data)
                synopsis_overlay.toggle_synopsis_overlay(text=synopsis_overlay.get_light_synopsis_string(words = 1))
            elif state.lightning.light_mode == "emoji":
                emoji_overlay.toggle_emoji_overlay(max_emojis=1)
            elif state.lightning.light_mode == 'title':
                start_title_round()
                top_header = ""
                if state.lightning.fixed_current_round:
                    top_header = state.lightning.fixed_current_round.get("title_header", "")
                else:
                    top_header = "MUST SAY FULL TITLE"
                osd_text.top_info(top_header.upper())
            elif state.lightning.light_mode == 'reveal':
                scoreboard_control.send_command("hide")
                peek_mode = peek_dispatch.get_next_peek_mode()
                if peek_mode == 'edge':
                    edge_overlay.toggle_edge_overlay()
                elif peek_mode == 'grow':
                    grow_overlay.set_grow_position()
                    grow_overlay.toggle_grow_overlay(position=grow_overlay.grow_position)
                elif peek_mode == 'slice':
                    peek_dispatch.choose_peek_direction()
                    peek_overlay.toggle_peek_overlay()
                elif peek_mode in ('blur', 'outline', 'pixelize', 'wave', 'zoom'):
                    filter_overlay.filter_vf_active = True
                    filter_overlay._filter_vf_variant = peek_mode
                    filter_overlay.toggle_filter_vf(peek_mode, 0)
            elif state.lightning.light_mode == 'characters':
                characters_overlay.characters_round_characters = lightning_queue_data.get(state.playback.currently_playing.get("filename", {}), {}).get("characters", [])
                if not characters_overlay.characters_round_characters:
                    characters_overlay.get_characters_round_characters()
                characters_overlay.toggle_characters_overlay(num_characters=1)
                osd_text.top_info("CHARACTERS")
            elif state.lightning.light_mode in ['cover', 'image']:
                header = ""
                reveal_mode = ""
                if state.lightning.light_mode == 'cover':
                    cover_image_overlay.get_light_cover_image()
                    if state.lightning.fixed_current_round:
                        header = state.lightning.fixed_current_round.get("cover_header", "")
                        reveal_mode = state.lightning.fixed_current_round.get("image_variant", "standard")
                    else:
                        header = "COVER ART"
                        reveal_mode = cover_image_overlay.get_next_cover_reveal_mode()
                elif state.lightning.light_mode == 'image':
                    cover_image_overlay.get_light_image_from_google()
                    if state.lightning.fixed_current_round:
                        header = state.lightning.fixed_current_round.get("image_header", "")
                        reveal_mode = state.lightning.fixed_current_round.get("image_variant", "standard")
                    else:
                        header = "RANDOM IMAGE"
                        reveal_mode = cover_image_overlay.get_next_image_reveal_mode()
                fixed_round = state.lightning.fixed_current_round or {}
                slide_direction = fixed_round.get("slide_direction", "top")
                slice_count = fixed_round.get("slice_count", 10)
                slice_vertical = fixed_round.get("slice_vertical", True)
                tile_grid_size = fixed_round.get("tile_grid_size", 4)
                osd_text.top_info(header.upper())
                apply_reveal_mode(reveal_mode, 
                                    image_source=ImageTk.getimage(cover_image_overlay.light_cover_image).convert("RGBA"),
                                    slide_direction=slide_direction,
                                    slice_vertical=slice_vertical,
                                    slice_count=slice_count,
                                    tile_grid_size=tile_grid_size)
            elif 'c.' in state.lightning.light_mode:
                osd_text.top_info("GUESS THE CHARACTER", inverse=True)
                state.lightning.character_round_answer = lightning_queue_data.get(state.playback.currently_playing.get("filename", {}), {}).get("character_answer")
                if not state.lightning.character_round_answer:
                    min_desc = 0
                    if state.lightning.light_mode == 'c. profile':
                        min_desc = 120
                    character_parts_overlay.get_character_round_image(types=get_char_types_by_popularity(mode=state.lightning.light_mode), min_desc_length=min_desc)
                if state.lightning.light_mode == 'c. reveal':
                    c_reveal_mode = image_reveal_overlays.get_next_c_reveal_mode()
                    if c_reveal_mode == 'parts':
                        character_parts_overlay.get_char_parts_round_character()
                        characters_overlay.toggle_characters_overlay(num_characters=1)
                    else:
                        apply_reveal_mode(c_reveal_mode, slice_vertical=False)
                elif state.lightning.light_mode == 'c. profile':
                    profile_overlay.toggle_character_profile_overlay()
                elif state.lightning.light_mode == 'c. name':
                    osd_text.top_info("MUST SAY FULL NAME", inverse=True)
                    start_title_round()
                if state.playback.lightning_mode_settings.get(state.lightning.light_mode).get("muted"):
                    music.now_playing_background_music(track = None)
                    audio_toggles.toggle_mute(True)
            elif state.lightning.light_mode == 'tags':
                tag_cloud_overlay.set_cloud_tags()
                osd_text.top_info("TAGS")
                tag_cloud_overlay.toggle_tag_cloud_overlay(1)
            elif state.lightning.light_mode == 'episodes':
                episode_overlay.set_light_episodes()
                episode_overlay.toggle_episode_overlay(1)
                if state.lightning.fixed_current_round:
                    top_header = state.lightning.fixed_current_round.get("episodes_header", "")
                else:
                    top_header = "EPISODE TITLES"
                osd_text.top_info(top_header.upper())
            elif state.lightning.light_mode == 'names':
                episode_overlay.light_name_overlay = True
                episode_overlay.set_light_names()
                episode_overlay.toggle_episode_overlay(1)
                osd_text.top_info("CHARACTER NAMES")
            elif state.lightning.light_mode in ['clip', 'ost']:
                _always_dl_clip = ffmpeg_check.is_ffmpeg_available() and state.playback.lightning_mode_settings.get("_misc_settings", {}).get("always_download_clip", False)
                def _ensure_clip_downloaded(yt_url):
                    """If always_download_clip is on and the file isn't cached, start the download then show the wait popup."""
                    if not (yt_url and _always_dl_clip):
                        return
                    cache_path = youtube_control._get_yt_cache_path(yt_url)
                    if not cache_path or (os.path.exists(cache_path) and not os.path.exists(cache_path + '.part')):
                        return  # already cached (or no video ID) — nothing to do
                    # Start download if not already running
                    vid_id = youtube_control.extract_youtube_id_from_url(yt_url)
                    if vid_id and vid_id not in youtube_control._yt_cache_downloads_in_progress:
                        cache_mb = int(state.playback.lightning_mode_settings.get("_misc_settings", {}).get("download_cache_mb", 0))
                        effective_mb = cache_mb if cache_mb > 0 else 500
                        threading.Thread(
                            target=youtube_control._yt_cache_download_bg,
                            args=(yt_url, cache_path, effective_mb),
                            daemon=True
                        ).start()
                    youtube_control._yt_cache_wait_popup(yt_url)
                if state.lightning.fixed_current_round:
                    url, name, channel = state.lightning.fixed_current_round.get("clip_url"), state.lightning.fixed_current_round.get("clip_title"), state.lightning.fixed_current_round.get("clip_author")
                    _ensure_clip_downloaded(url)
                    length = streaming.stream_url(url, name, channel)
                else:
                    clip_variants = state.playback.lightning_mode_settings.get("clip", {}).get("variants", {})
                    clip_enabled, trailer_enabled = clip_variants.get("random_clip"), clip_variants.get("trailer")
                    length = 0
                    is_ost = (state.lightning.light_mode == 'ost')
                    if is_ost:    
                        url = lightning_queue_data.get(state.playback.currently_playing.get("filename", {}), {}).get("ost_url")
                    else:
                        url = lightning_queue_data.get(state.playback.currently_playing.get("filename", {}), {}).get("clip_url")
                    if not url:
                        if not streaming.youtube_api_limited and state.config.YOUTUBE_API_KEY and (clip_enabled or is_ost):
                            length = streaming.play_random_clip(ost=is_ost)
                        elif state.playback.currently_playing.get("data", {}).get("trailer") and trailer_enabled and is_ost:
                            length = streaming.play_trailer()
                    elif trailer_enabled and url[1] == 'trailer':
                        length = streaming.play_trailer()
                    else:
                        _ensure_clip_downloaded(url[0])
                        length = streaming.stream_url(url[0], url[1], url[2])
                if streaming.currently_streaming:
                    # Compute start time now if we have a known length; otherwise defer until player is ready
                    if length > 0:
                        state.lightning.stream_start_time = streaming.get_stream_start_time(length)
                    else:
                        _cst = state.lightning.fixed_current_round.get("clip_start_time") if state.lightning.fixed_current_round else None
                        state.lightning.stream_start_time = max(0, _cst) if _cst is not None else 0
                    streaming.test_print(f"Length: {length} | Stream Start Time: {state.lightning.stream_start_time}")
                    # player is already loading the stream (set_media called in stream_url)
                    streaming.test_print(streaming.currently_streaming)
                    def wait_for_stream(filename, count):
                        streaming.test_print(F"Waiting...{count}")
                        def restart_player():
                            state.widgets.player.stop()
                            state.widgets.player.play()
                            state.widgets.root.after(100, wait_for_stream, filename, 0)
                        if filename != state.playback.currently_playing.get("filename") or not streaming.currently_streaming:
                            return
                        elif state.widgets.player.is_playing() and state.widgets.player.get_length() > 0:
                            # If length was unknown when stream started, calculate start time now
                            actual_length = state.widgets.player.get_length() / 1000
                            _cst = state.lightning.fixed_current_round.get("clip_start_time") if state.lightning.fixed_current_round else None
                            if state.lightning.stream_start_time == 0 and not (state.lightning.fixed_current_round and _cst is not None):
                                state.lightning.stream_start_time = streaming.get_stream_start_time(actual_length)
                                streaming.test_print(f"Deferred stream start time: {state.lightning.stream_start_time} (length={actual_length})")
                            def stream_overlay():
                                from _app_scripts.playback import blind_screen as _blind_screen
                                if state.lightning.light_answer_wall_start is not None or not state.lightning.light_round_started:
                                    return  # answer phase already started — don't re-apply overlays
                                if state.lightning.light_mode == 'ost':
                                    # Per-round framed_video override (fixed rounds only)
                                    _framed_ost = (state.lightning.fixed_current_round.get("framed_video")
                                                   if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("framed_video") is not None
                                                   else False)
                                    if _framed_ost and not _blind_screen._video_frame_active:
                                        blind_screen.set_video_frame(True)
                                    if not _blind_screen.black_overlay:  # already up — skip re-application
                                        blind_screen.set_black_screen(True)  # OST is audio-only; hide video with blind overlay
                                    _top_font_size_ost = 80
                                    if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("ost_header"):
                                        osd_text.top_info(state.lightning.fixed_current_round.get("ost_header").upper(), _top_font_size_ost)
                                    else:
                                        osd_text.top_info("SOUNDTRACK / OST", _top_font_size_ost)
                                else:
                                    # Clear the blind that play_filename raised before the clip loaded
                                    # Per-round framed_video override (fixed rounds); falls back to global framed_video_clip
                                    _framed_clip = (state.lightning.fixed_current_round.get("framed_video")
                                                    if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("framed_video") is not None
                                                    else state.playback.lightning_mode_settings.get("_misc_settings", {}).get("framed_video_clip"))
                                    if _framed_clip and not _blind_screen._video_frame_active:
                                        blind_screen.set_video_frame(True)
                                    blind_screen.set_black_screen(False)
                                    _top_font_size = 80 if _framed_clip else 40
                                    if (state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("censor_bottom")) or (not state.lightning.fixed_current_round and streaming.last_streamed[3] and "Crunchyroll" in streaming.last_streamed[3]):
                                        overlay_primitives.toggle_outer_edge_overlay()
                                    if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("clip_header"):
                                        osd_text.top_info(state.lightning.fixed_current_round.get("clip_header").upper(), _top_font_size)
                                    elif streaming.last_streamed[1] == "Trailer":
                                        osd_text.top_info("TRAILER", _top_font_size)
                                    else:
                                        osd_text.top_info("RANDOM CLIP", _top_font_size)
                                update_light_round_number()
                            def set_stream_start():
                                from _app_scripts.playback import blind_screen as _blind_screen
                                # For OST rounds raise the blind immediately so the video is
                                # never visible; stream_overlay will confirm it later.
                                if state.lightning.light_mode == 'ost' and not _blind_screen.black_overlay:
                                    blind_screen.set_black_screen(True)
                                state.widgets.player.set_time(round(float(state.lightning.stream_start_time) * 1000))
                                # Mark seek as done — update_light_round uses this as a sentinel.
                                streaming.set_stream_wall_start(True)
                                # Unmute now so the stream is audible immediately on seek.
                                audio_toggles.toggle_mute(False, True)
                                # Initialise the OST progress bar exactly once right here so it
                                # starts from 0 without any later stream_overlay call resetting it.
                                if state.lightning.light_mode == 'ost':
                                    progress_overlay_ops.set_progress_overlay(0, state.lightning.light_round_length*100)
                                volume_adjustment = state.lightning.fixed_current_round.get("volume_adjustment", 0) if state.lightning.fixed_current_round else 0
                                _stream_volume_level = int(state.controls.volume_level * (1 + ((state.controls.stream_volume_boost + volume_adjustment) / 100)))
                                state.widgets.player.audio_set_volume(_stream_volume_level)
                            def start_player():
                                if filename != state.playback.currently_playing.get("filename") or not streaming.currently_streaming:
                                    return
                                if state.lightning.light_answer_wall_start is not None or not state.lightning.light_round_started:
                                    return  # answer phase already started — don't interfere
                                target_ms = round(float(state.lightning.stream_start_time) * 1000)
                                current_ms = state.widgets.player.get_time()
                                streaming.test_print(f"start_player check: current={current_ms} target={target_ms}")
                                # If the player is more than 2.5 s behind the target the seek
                                # didn't take (stream playing from 0).  Re-attempt once.
                                if state.widgets.player.is_playing() and current_ms < target_ms - 2500:
                                    streaming.test_print(f"Seek miss — retrying seek to {target_ms}")
                                    state.widgets.player.set_time(target_ms)
                                    def _check_retry():
                                        if filename != state.playback.currently_playing.get("filename") or not streaming.currently_streaming:
                                            return
                                        if state.widgets.player.is_playing() and state.widgets.player.get_time() < target_ms - 2500:
                                            streaming.test_print("Seek retry failed — restarting stream")
                                            restart_player()
                                    state.widgets.root.after(2000, _check_retry)
                                # else: playing from (approximately) the right position
                            state.widgets.root.after(2000, start_player)
                            set_stream_start()
                            for time in [500, 1000, 1500, 2000]:
                                state.widgets.root.after(time, stream_overlay)
                        elif count >= 5000:
                            restart_player()
                        else:
                            count += 100
                            state.widgets.root.after(100, wait_for_stream, filename, count)
                    wait_for_stream(state.playback.currently_playing.get("filename"), 0)
                else:
                    if variety_round.last_variety_forced:
                        variety_round.variety_mode_cooldown_counts['clip'] = state.playback.lightning_mode_settings.get("clip", {}).get("variety", {}).get("cooldown", {}).get("max_gap", 0)
                    audio_toggles.toggle_mute(False)
                    state.widgets.root.after(500, blind_screen.set_black_screen, False)
            # Auto-trigger MC bonus if this fixed round defines MC choices
            if state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("mc_choice_2"):
                bonus.guess_extra("fixed_mc")
            variety_round.append_lightning_history()
            osd_text.set_countdown(int(state.lightning.light_round_length), inverse=state.lightning.character_round_answer)
            update_light_round_number(inverse=state.lightning.character_round_answer)
        if not streaming.currently_streaming and state.lightning.light_round_started and state.lightning.light_answer_wall_start is None:
            #only if not already at time (skip during answer phase — answer seek may target an earlier position)
            if state.lightning.light_round_start_time is not None and state.seek.projected_player_time < round(float(state.lightning.light_round_start_time) * 1000):
                state.widgets.player.set_time(round(float(state.lightning.light_round_start_time) * 1000))

# =========================================
#       *LIGHTNING QUEUE DISPATCHER
# =========================================
#
# Central queue orchestrator. Picks the next round's mode (delegating to
# variety_round when variety mode is active) and pre-fetches whatever
# resources that mode needs (clip URLs, character data, trivia, etc.).

lightning_queue = None
lightning_queue_data = {}
def queue_next_lightning_mode():
    def queue_next_lightning_mode_worker():
        global lightning_queue
        lightning_queue = None
        fixed_data = None
        next_fixed_round = None
        if state.lightning.fixed_lightning_queue or state.lightning.fixed_lightning_round_playlist_data:
            fixed_data = state.lightning.fixed_lightning_round_playlist_data or state.lightning.fixed_lightning_queue

            if fixed_data.get("current_index", 0)+1 >= len(fixed_data.get("rounds", [])):
                return
            next_fixed_round = fixed_data.get("rounds", [])[fixed_data.get("current_index", -1)+1]
            next_filename = next_fixed_round.get("theme")
        else:
            next_index = state.metadata.playlist["current_index"] + 1
            if next_index < len(state.metadata.playlist["playlist"]) and (entry_paths.get_file_path(state.metadata.playlist["playlist"][next_index]) or cache_download.is_animethemes_stream_file(state.metadata.playlist["playlist"][next_index])):
                next_filename = entry_paths.get_clean_filename(state.metadata.playlist["playlist"][next_index])
            else:
                return
        
        data = metadata_fetch.get_metadata(next_filename)
        if next_filename not in lightning_queue_data:
            lightning_queue_data[next_filename] = {}

        excluded_modes = []
        next_mode = None
        while not next_mode:
            if next_fixed_round:
                next_mode = next_fixed_round.get("type")
            elif variety_round.variety_light_mode_enabled:
                next_mode = variety_round.set_variety_light_mode(next_filename, excluded_modes=excluded_modes)
            else:
                next_mode = state.lightning.light_mode
            if next_mode in ["clip", 'ost']:
                clip_variants = state.playback.lightning_mode_settings.get("clip", {}).get("variants", {})
                clip_enabled, trailer_enabled = clip_variants.get("random_clip"), clip_variants.get("trailer")
                url, name, channel, length = None, None, None, None
                yt_source_url = None  # Original YouTube URL (url may be resolved CDN URL for fixed rounds)
                if next_fixed_round:
                    clip_url = next_fixed_round.get("clip_url")
                    yt_source_url = clip_url
                    url, length, name, channel = youtube_control.get_youtube_stream_url(clip_url, include_other_info=True)
                    name = next_fixed_round.get("clip_title") or name
                    channel = next_fixed_round.get("clip_author") or channel
                else:
                    if not streaming.youtube_api_limited and state.config.YOUTUBE_API_KEY and clip_enabled:
                        url, name, channel = streaming.play_random_clip(data, True, ost=(next_mode=='ost'))
                    if url:
                        yt_source_url = url
                        length = youtube_control.get_youtube_stream_url(url)
                    elif next_mode != 'ost' and data.get("trailer") and trailer_enabled:
                        url = f"https://www.youtube.com/watch?v={data.get("trailer")}"
                        yt_source_url = url
                        name = "trailer"
                        channel = None
                        length = youtube_control.get_youtube_stream_url(url)
                    elif variety_round.variety_light_mode_enabled:
                        excluded_modes.append(next_mode)
                        next_mode = None
                if next_mode == "ost":
                    lightning_queue_data[next_filename]["ost_url"] = [url, name, channel, length]
                else:
                    lightning_queue_data[next_filename]["clip_url"] = [url, name, channel, length]
                # Pre-download to local cache if the setting is enabled and ffmpeg is available
                if yt_source_url and ffmpeg_check.is_ffmpeg_available():
                    cache_mb = int(state.playback.lightning_mode_settings.get("_misc_settings", {}).get("download_cache_mb", 0))
                    always_dl = state.playback.lightning_mode_settings.get("_misc_settings", {}).get("always_download_clip", False)
                    # When always_download_clip is on and no cache size is configured, use 500 MB as headroom
                    effective_cache_mb = cache_mb if cache_mb > 0 else (500 if always_dl else 0)
                    if effective_cache_mb > 0:
                        cache_path = youtube_control._get_yt_cache_path(yt_source_url)
                        if cache_path and not os.path.exists(cache_path) and not os.path.exists(cache_path + '.part'):
                            threading.Thread(
                                target=youtube_control._yt_cache_download_bg,
                                args=(yt_source_url, cache_path, effective_cache_mb),
                                daemon=True
                            ).start()
            elif "c. " in next_mode:
                min_desc = 0
                if next_mode == 'c. profile':
                    min_desc = 120
                lightning_queue_data[next_filename]["character_answer"] = character_parts_overlay.get_character_round_image(types=get_char_types_by_popularity(data, next_mode), min_desc_length=min_desc, data=data, queue=True, mode=next_mode)
            elif next_mode == "characters":
                lightning_queue_data[next_filename]["characters"] = characters_overlay.get_characters_round_characters(data=data, queue=True)
            elif next_mode == "trivia":
                if not fixed_data:
                    trivia_question = trivia_round.set_light_trivia(data=data, queue=True)
                    if trivia_question[1] == "None" and variety_round.variety_light_mode_enabled:
                        excluded_modes.append('trivia')
                        next_mode = None
                    else:
                        lightning_queue_data[next_filename]["trivia"] = trivia_question
            elif next_mode == "emoji":
                if not data.get("emojis"):
                    emoji_overlay.get_emoji_clues_for_title(data)
            elif next_mode == "image":
                if next_fixed_round and next_fixed_round.get("image_url"):
                    image_url = next_fixed_round.get("image_url")
                else:
                    image_url = cover_image_overlay.get_google_image_url(data)
                if image_url:
                    lightning_queue_data[next_filename]["image_url"] = image_url
                elif variety_round.variety_light_mode_enabled:
                    excluded_modes.append("image")
                    next_mode = None
        metadata_display.up_next_text()
    
    if state.lightning.light_mode or state.lightning.fixed_lightning_queue or state.lightning.fixed_lightning_round_playlist_data:
        threading.Thread(target=queue_next_lightning_mode_worker, daemon=True).start()

# ---------------------------------------------------------------------------
# Lightning round number display. Maintains `state.lightning.light_round_number`
# (incremented in main's play_video / reset by stop_all_queues) and
# pushes it to the bottom-right floating text overlay.
# ---------------------------------------------------------------------------
def update_light_round_number(inverse=False):
    if state.lightning.fixed_lightning_round_playlist_data:
        state.lightning.light_round_number = state.lightning.fixed_lightning_round_playlist_data.get("current_index", 0) + 1
        set_light_round_number(f"#{state.lightning.light_round_number}", inverse=inverse)
    else:
        set_light_round_number("#" + str(state.lightning.light_round_number), inverse=inverse)


def set_light_round_number(value=None, inverse=False):
    size = 80
    if value:
        if len(value) >= 5:
            size = 48
        elif len(value) >= 4:
            size = 62
    osd_text.set_floating_text("Lightning Round Number", value, position="bottom right", size=size, inverse=inverse)
