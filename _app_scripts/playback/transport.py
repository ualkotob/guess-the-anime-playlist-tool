"""Playback transport â€” seek / play / pause / next / stop controls.

These functions orchestrate playback: they read shared game data through the
state container (state.metadata.playlist, state.playback.currently_playing,
state.widgets.player/root, state.seek, â€¦) and call sibling playback / metadata /
overlay modules directly.
"""

from core.game_state import state
from core.app_meta import WINDOW_TITLE
from core.app_logging import log_exception
import _app_scripts.toggles.censors as censors

import _app_scripts.toggles.audio_toggles as audio_toggles
import _app_scripts.toggles.autoplay as autoplay_toggles
import _app_scripts.bonus.answers as bonus_answers
from _app_scripts.bonus import buzz
import _app_scripts.playback.cache_download as cache_download
import copy
from datetime import datetime
import _app_scripts.queue_round.lightning_rounds.lightning_settings as lightning_settings
from tkinter import messagebox
import _app_scripts.file.metadata.metadata_display as metadata_display
import os
import _app_scripts.playback.playpause_icon as playpause_icon
import _app_scripts.popout.popout_window as popout_window
import pygame
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.file.session_stats as session_stats
from tkinter import simpledialog
import _app_scripts.queue_round.lightning_rounds.synopsis_overlay as synopsis_overlay
import _app_scripts.queue_round.lightning_rounds.variety_round as variety_round
import _app_scripts.queue_round.youtube.youtube_control as youtube_control

# --- sibling imports for migrated transport functions ---
import _app_scripts.playback.blind_screen as blind_screen
import _app_scripts.bonus.bonus as bonus
import _app_scripts.playback.coming_up_ui as coming_up_ui
import _app_scripts.data.config_io as config_io
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.queue_round.lightning_rounds.frame_round as frame_round
import _app_scripts.information.information_popup as information_popup
import _app_scripts.queue_round.lightning_rounds.lightning_manager as lightning_manager
import _app_scripts.ui.lists as lists
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.playback.music as music
import _app_scripts.playback.osd_text as osd_text
import _app_scripts.queue_round.lightning_rounds.peek_dispatch as peek_dispatch
import _app_scripts.theme.marks as playlist_marks
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.playlists.infinite as infinite
import _app_scripts.playback.progress_bar as progress_bar_ops
import _app_scripts.playback.progress_overlay as progress_overlay_ops
import _app_scripts.queue_round.lightning_rounds.peek_overlay as peek_overlay
import _app_scripts.search.search as search_ops
from _app_scripts.file import session_end
import _app_scripts.playback.streaming as streaming
import threading
import _app_scripts.file.web_server.web_server as web_server
import _app_scripts.queue_round.youtube.youtube_ui as youtube_ui


# --- transport-internal mutable flags (migrated from main module globals) ---
animethemes_stream = None       # True while the current file is an AnimeThemes stream
background_music_rounds = 0      # lightning rounds counted toward background-music rotation
skip_limit = 0                  # consecutive auto-skip guard (missing/unplayable files)
playlist_loaded = False         # set by a fresh playlist load; consumed by play_next/play_video
playlist_changed = False        # vestigial main-side flag (playlist_ops.playlist_changed is authoritative)
playing_next_error = False      # shared with main.update_seek_bar (read/written as transport.playing_next_error)


def set_rules(type=None):
    """Thin wrapper migrated from main (scoreboard rules + web toggle push)."""
    scoreboard_control.set_rules(state.config.scoreboard_rules, type, web_server, bonus_answers._push_web_toggles)


def add_session_history():
    """Thin wrapper migrated from main; records the played theme to session stats."""
    session_stats.add_session_history(state.playback.currently_playing, state.lightning.light_mode,
                                      state.metadata.playlist, playlist_marks.SYSTEM_PLAYLISTS,
                                      bool(state.lightning.fixed_lightning_round_playlist_data))


def update_playlist_name(name=None):
    """Update the window title bar to reflect the current playlist name/count."""
    playlist = state.metadata.playlist
    if name:
        playlist["name"] = name
    extra_text = " âˆž" if playlist.get("infinite") else ""
    state.widgets.root.title(
        f"[{session_stats.get_themes_played_count()}] {WINDOW_TITLE} - {playlist['name']}{extra_text}")
    if web_server.is_running():
        bonus_answers._push_web_toggles()


def seek(value):
    """Function to seek the video (seek-bar Scale command callback)."""
    if state.seek.can_seek:
        state.seek.last_seek_time = value
    else:
        state.seek.can_seek = True


def seek_to(time_ms):
    """Function to seek the video to a specific time in milliseconds."""
    time_ms = int(time_ms)
    player = state.widgets.player
    censors.apply_censors(time_ms / 1000, player.get_length() / 1000)
    state.seek.projected_player_time = time_ms
    player.set_time(time_ms)


def stop():
    """Function to stop the video"""
    state.playback.currently_playing.clear()  # Clear first to prevent idle-active re-entry
    state.controls.video_stopped = True
    lightning_manager.toggle_light_mode()
    state.lightning.light_round_started = False
    state.lightning.light_round_armed = False
    osd_text.set_countdown()
    lightning_manager.set_light_round_number()
    blind_screen.set_black_screen(False)
    information_popup.toggle_title_popup(False)
    if session_end.end_message_window:
        session_end.toggle_end_message()
    state.lightning.fixed_lightning_queue = None
    state.lightning.fixed_lightning_round_playlist_data = None
    state.lightning.fixed_current_round = None
    search_ops.search_queue = None
    youtube_ui.unload_youtube_video()
    bonus.guess_extra()
    state.widgets.player.stop()
    state.widgets.player.set_media(None)  # Reset the media
    progress_bar_ops.update_progress_bar(0,1)
    censors.remove_all_censor_boxes()
    coming_up_ui.toggle_coming_up_popup(False, title=(state.controls.coming_up_queue or {}).get("title", ""))
    state.widgets.seek_bar.set(0)
    lightning_manager.clean_up_light_round(new_round=True)
    state.widgets.root.after(500, lambda: lightning_manager.clean_up_light_round(new_round=True))


def stop_all_queues():
    """Clear all queued special rounds: lightning, YouTube, search, and fixed lightning."""
    # Clear lightning mode + button text
    lightning_manager.unselect_light_modes()
    coming_up_ui.toggle_coming_up_popup(False, "Lightning Round")
    # Clear YouTube queue (handles its own popup + button state)
    youtube_ui.unload_youtube_video()
    # Clear search queue
    if search_ops.search_queue:
        search_ops.search_queue = None
    # Clear fixed lightning (queued and/or currently active playlist)
    if state.lightning.fixed_lightning_queue or state.lightning.fixed_lightning_round_playlist_data:
        fl_name = (state.lightning.fixed_lightning_queue or state.lightning.fixed_lightning_round_playlist_data or {}).get("name")
        state.lightning.fixed_lightning_queue = None
        state.lightning.fixed_lightning_round_playlist_data = None
        state.lightning.fixed_current_round = None
        if fl_name:
            coming_up_ui.toggle_coming_up_popup(False, fl_name)
        lists.update_playlist_display()
    # Clear the armed "Auto Queue at Start" selection too
    peek_dispatch.set_auto_reveal(None, None, toggle=False)
    peek_dispatch.set_auto_reveal_seconds(0, toggle=False)
    metadata_display.up_next_text()


def player_play(override_autoplay=False):
    if state.controls.autoplay_toggle != 3 or override_autoplay:
        state.widgets.player.play()
    else:
        state.widgets.player.stop()


def set_skip_direction(dir):
    state.seek.skip_direction = dir


def thread_prefetch_metadata():
    if state.config.auto_fetch_missing:
        threading.Thread(target=metadata_fetch.pre_fetch_metadata, daemon=True).start()


def skip_to_lightning_answer():
    if frame_round.frame_light_round_started:
        try:
            if frame_round.frame_light_round_frame_index is None or frame_round.frame_light_round_frame_index < 4:
                frame_round.frame_light_round_frame_index = 4
                frame_round.frame_light_round_frame_time = 0
                osd_text.bottom_info()
                music.play_background_music(False)
                blind_screen.set_black_screen(False)
                information_popup.toggle_title_popup(True)
                return True
        except Exception:
            log_exception("skip_to_lightning_answer: frame-round answer skip failed")
    if state.lightning.light_round_started and state.lightning.light_round_start_time is not None:
        try:
            one_second_answer = state.lightning.light_blind_one_second_count is not None
            if state.lightning.light_blind_one_second_count is not None:
                state.lightning.light_blind_one_second_count = None
                state.lightning.light_answer_wall_start = None
                state.lightning.light_answer_last_tick = None

            # Already in answer phase â€” let play_next fall through to light_round_transition
            if state.lightning.light_answer_wall_start is not None:
                return False

            if streaming.currently_streaming:
                # Seek the stream player to stream_start_time + light_round_length so
                # update_light_round's elapsed calculation crosses the round-end threshold.
                seek_target_ms = round((state.lightning.stream_start_time + state.lightning.light_round_length + 0.1) * 1000)
                state.widgets.player.set_time(seek_target_ms)
                return True

            answer_time = state.lightning.light_round_start_time if one_second_answer else state.lightning.light_round_start_time + state.lightning.light_round_length
            target_ms = int((answer_time + (0 if one_second_answer else 0.05)) * 1000)
            seek_to(target_ms)
            state.widgets.player.play()
            return True
        except Exception as e:
            print(f"[DBG skip_to_lightning_answer] exception: {e}")
            log_exception("skip_to_lightning_answer: lightning answer seek failed")
    return False


def check_next_queue_round(next_filename_set):
    if state.metadata.playlist["current_index"]+1 < len(state.metadata.playlist["playlist"]):
        next_filename = entry_paths.get_clean_filename(state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]+1])
        if next_filename_set == next_filename:
            if state.config.special_round_playlist:
                if playlist_marks.check_blind_mark(next_filename):
                    blind_screen.toggle_blind_round()
                elif playlist_marks.check_peek_mark(next_filename):
                    peek_dispatch.toggle_peek_round()
                elif playlist_marks.check_mute_peek_mark(next_filename):
                    peek_dispatch.toggle_mute_peek_round()


def update_current_index(value = None, save = True):
    """Function to update the playlist button counter label"""
    try:
        if value != None:
            state.metadata.playlist["current_index"] = value
        _plmb = state.widgets.playlist_menu_button
        if _plmb:
            if state.metadata.playlist.get("infinite", False):
                out_of = infinite.total_infinite_files - len(infinite.cached_skipped_themes)
                counter = f"\u221e/{out_of}"
            else:
                out_of = len(state.metadata.playlist["playlist"])
                counter = f"{state.metadata.playlist['current_index']+1}/{out_of}"
            _plmb.config(text=f"PLAYLIST {counter}\u25be")
        
        if state.lists.list_loaded == "playlist" and value is not None:
            # Update the selected index to match the current playing item
            state.lists.current_list_selected = value
            entries_count = lists.get_list_entries_count()
            current_start = state.lists.current_list_offset
            current_end = state.lists.current_list_offset + entries_count
            
            look_ahead = min(3, len(state.metadata.playlist["playlist"]) - value - 1)  # Don't look beyond playlist end
            needs_scroll = (value < current_start or value >= current_end or 
                          (value + look_ahead) >= current_end)
            
            if needs_scroll:
                ideal_offset = max(0, value - 1)  # Show current with 1 item before if possible
                max_offset = max(0, len(state.metadata.playlist["playlist"]) - entries_count)
                state.lists.current_list_offset = min(ideal_offset, max_offset)
            lists.refresh_current_list()
            
        if save:
            config_io.save_config()
        if web_server.is_running():
            if state.lightning.fixed_lightning_round_playlist_data and state.lightning.fixed_lightning_round_playlist_data.get("rounds"):
                fixed_rounds = state.lightning.fixed_lightning_round_playlist_data.get("rounds", [])
                fixed_index = state.lightning.fixed_lightning_round_playlist_data.get("current_index", 0)
                web_server.push_playlist_info(len(fixed_rounds), fixed_index, counter=(f'{fixed_index+1}/{len(fixed_rounds)}' if fixed_rounds else '0/0'), label=state.lightning.fixed_lightning_round_playlist_data.get('name') or 'Fixed Playlist')
            elif state.metadata.playlist.get('infinite', False):
                out_of = infinite.total_infinite_files - len(infinite.cached_skipped_themes)
                web_server.push_playlist_info(-1, -1, counter=f'\u221e/{out_of}', label=state.metadata.playlist.get('name') or 'Playlist')
            else:
                out_of = len(state.metadata.playlist['playlist'])
                cur = state.metadata.playlist['current_index']
                web_server.push_playlist_info(out_of, cur, counter=f'{cur+1}/{out_of}', label=state.metadata.playlist.get('name') or 'Playlist')
    except NameError:
        pass  # root isn't defined yet â€” possibly too early in startup


def play_video(index=-1):  # def-time default was BLANK_PLAYLIST["current_index"] == -1
    """Function to play a specific video by index"""
    global playlist_loaded, playing_next_error
    global playlist_changed
    playlist_loaded = False
    playlist_changed = False
    playlist_ops.playlist_changed = False
    state.lightning.light_round_start_time = None
    synopsis_overlay.synopsis_start_index = None
    state.lightning.title_light_string = ""
    state.lightning.title_light_letters = None
    lightning_manager.clean_up_light_round(True)
    peek_dispatch.stop_timed_reveal()  # clear any timed auto-reveal carried from the previous round
    state.lightning.light_round_started = False
    state.lightning.light_round_armed = True
    state.lightning.current_light_mode = None
    state.lightning.current_light_variant = None
    state.controls.video_stopped = True
    playing_next_error = False
    if web_server.is_running():
        web_server.push_skip_grant('')
    if not (bonus.guessing_extra == "buzzer" and state.controls.auto_bonus_start == "buzzer"):
        bonus.guess_extra()
    information_popup.toggle_title_popup(False)
    osd_text.set_countdown()
    coming_up_ui.toggle_coming_up_popup(False)
    if session_end.end_message_window:
        session_end.toggle_end_message()

    if state.metadata.playlist["current_index"] < len(state.metadata.playlist["playlist"]) and index + 1 >= len(state.metadata.playlist["playlist"]) and not state.playback.youtube_queue and not search_ops.search_queue and not state.lightning.fixed_lightning_queue:
        infinite._promote_or_generate_next()
    
    if state.lightning.fixed_lightning_queue or state.lightning.fixed_lightning_round_playlist_data:
        if state.lightning.fixed_lightning_queue and (not state.lightning.fixed_lightning_round_playlist_data or (state.lightning.fixed_lightning_round_playlist_data.get("name") != state.lightning.fixed_lightning_queue.get("name"))):
            state.lightning.fixed_lightning_round_playlist_data = copy.deepcopy(state.lightning.fixed_lightning_queue)
            state.lightning.fixed_lightning_round_playlist_data["current_index"] = 0
            # Update playlist display to show fixed rounds
            lists.update_playlist_display()
            
            # Add session log entry for starting fixed rounds
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            fixed_rounds_entry = {
                "timestamp": timestamp,
                "type": "fixed_rounds_start",
                "playlist_name": state.lightning.fixed_lightning_round_playlist_data.get("name", "Unknown"),
                "creator": state.lightning.fixed_lightning_round_playlist_data.get("creator", "N/A"),
                "round_count": len(state.lightning.fixed_lightning_round_playlist_data.get("rounds", []))
            }
            session_stats.add_entry(fixed_rounds_entry)
            session_stats.save_session_history(create_text_file=False)
        else:
            state.lightning.fixed_lightning_round_playlist_data["current_index"] += state.seek.skip_direction
        index = state.lightning.fixed_lightning_round_playlist_data["current_index"]
        if index < 0 or index >= len(state.lightning.fixed_lightning_round_playlist_data.get("rounds", [])):
            _was_test = state.lightning.fixed_lightning_round_playlist_data.get('is_test', False)
            state.lightning.fixed_lightning_round_playlist_data = None
            state.lightning.fixed_lightning_queue = None
            state.lightning.fixed_current_round = None
            state.lightning.light_round_answer_length = state.playback.lightning_mode_settings["_misc_settings"].get("answer_length", lightning_settings.LIGHT_ROUND_ANSWER_LENGTH_DEFAULT)

            # Revert playlist display back to normal
            lists.update_playlist_display()
            
            lightning_manager.toggle_light_mode()
            if _was_test:
                stop()
            else:
                play_video(state.metadata.playlist["current_index"] + state.seek.skip_direction)
            return
        state.lightning.fixed_current_round = state.lightning.fixed_lightning_round_playlist_data.get("rounds", [])[index]
        filename = state.lightning.fixed_current_round.get("theme")
        rnd_mode = state.lightning.fixed_current_round.get("type", "regular")
        state.lightning.light_round_answer_length = state.lightning.fixed_current_round.get("answer_duration", state.playback.lightning_mode_settings["_misc_settings"].get("answer_length", lightning_settings.LIGHT_ROUND_ANSWER_LENGTH_DEFAULT))
        
        # Update playlist display to show current fixed round
        lists.update_playlist_display()
        
        if state.lightning.light_mode != rnd_mode:
            lightning_manager.toggle_light_mode(rnd_mode, queue=False, show_popup=False)
        if play_filename(filename):
            state.widgets.root.after(3000, thread_prefetch_metadata)
            state.widgets.root.after(1000, lightning_manager.queue_next_lightning_mode)
        metadata_display.up_next_text()
    elif state.playback.youtube_queue is not None:
        state.playback.currently_playing.clear()
        state.playback.currently_playing.update({
            "type":"youtube",
            "filename": state.playback.youtube_queue.get("filename"),
            "data":state.playback.youtube_queue
        })
        blind_screen.set_black_screen(False)
        metadata_display.reset_metadata()
        youtube_ui.update_youtube_metadata()
        if "guess the character" in (youtube_ui.get_youtube_display_title(state.playback.youtube_queue)).lower():
            set_rules("character")
        else:
            set_rules("anime")
        
        video_path = os.path.join("youtube", state.playback.youtube_queue.get("filename"))
        archive_path = os.path.join("youtube", "archive", state.playback.youtube_queue.get("filename"))
        if os.path.exists(video_path):
            youtube_ui.stream_youtube(video_path)
        elif os.path.exists(archive_path):
            youtube_ui.stream_youtube(archive_path)
        else:
            # Stream from YouTube URL using yt-dlp
            video_id = state.playback.youtube_queue.get('video_id') or state.playback.youtube_queue.get('url')
            if video_id:
                print(f"Streaming from YouTube: {video_id}")
                youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                stream_url, duration = youtube_control.get_youtube_stream_url(youtube_url)
                if stream_url:
                    youtube_ui.stream_youtube(stream_url)
                else:
                    print(f"Failed to get stream URL for {video_id}")
            else:
                print("Warning: Video not downloaded and no video_id found")
                youtube_ui.stream_youtube(video_path)  # Try anyway
        
        youtube_ui.unload_youtube_video()
        metadata_display.up_next_text()
    elif search_ops.search_queue:
        if youtube_control.is_youtube_file(search_ops.search_queue):
            youtube_data = youtube_control.get_youtube_metadata_by_filename(search_ops.search_queue)
            if youtube_data:
                state.playback.currently_playing.clear()
                state.playback.currently_playing.update({
                    "type":"youtube",
                    "filename": search_ops.search_queue,
                    "data":youtube_data
                })
                blind_screen.set_black_screen(False)
                metadata_display.reset_metadata()
                youtube_ui.update_youtube_metadata(youtube_data)
                if "guess the character" in (youtube_ui.get_youtube_display_title(youtube_data)).lower():
                    set_rules("character")
                else:
                    set_rules("anime")
                youtube_file_path = entry_paths.get_file_path(search_ops.search_queue)
                if youtube_file_path and os.path.exists(youtube_file_path):
                    youtube_ui.stream_youtube(youtube_file_path)
                elif os.path.exists(os.path.join("youtube", search_ops.search_queue)):
                    youtube_ui.stream_youtube(os.path.join("youtube", search_ops.search_queue))
                else:
                    # Stream from YouTube URL using yt-dlp
                    video_id = youtube_data.get('url')
                    if video_id:
                        print(f"Streaming from YouTube: {video_id}")
                        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                        stream_url, duration = youtube_control.get_youtube_stream_url(youtube_url)
                        if stream_url:
                            youtube_ui.stream_youtube(stream_url)
                        else:
                            print(f"Failed to get stream URL for {video_id}")
                    else:
                        youtube_ui.stream_youtube(os.path.join("youtube", search_ops.search_queue))  # Try anyway
            else:
                play_filename(search_ops.search_queue)
        else:
            play_filename(search_ops.search_queue)
        search_ops.search_queue = None
        metadata_display.up_next_text()
        if "SEARCH QUEUE" in state.playback.popout_buttons_by_name:
            lists.button_seleted(state.playback.popout_buttons_by_name["SEARCH QUEUE"], False)
    elif 0 <= index < len(state.metadata.playlist["playlist"]):
        same_index = index == state.metadata.playlist["current_index"]
        update_current_index(index)
        metadata_display.up_next_text()
        
        playlist_entry = state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]]
        filename = entry_paths.get_clean_filename(playlist_entry)
        
        if youtube_control.is_youtube_file(filename):
            youtube_data = youtube_control.get_youtube_metadata_by_filename(filename)
            if youtube_data:
                state.playback.currently_playing.clear()
                state.playback.currently_playing.update({
                    "type":"youtube",
                    "filename": filename,
                    "data":youtube_data
                })
                blind_screen.set_black_screen(False)
                metadata_display.reset_metadata()
                youtube_ui.update_youtube_metadata(youtube_data)
                if "guess the character" in (youtube_ui.get_youtube_display_title(youtube_data)).lower():
                    set_rules("character")
                else:
                    set_rules("anime")
                youtube_file_path = entry_paths.get_file_path(playlist_entry)
                if youtube_file_path and os.path.exists(youtube_file_path):
                    youtube_ui.stream_youtube(youtube_file_path)
                elif os.path.exists(os.path.join("youtube", filename)):
                    youtube_ui.stream_youtube(os.path.join("youtube", filename))
                else:
                    # Stream from YouTube URL using yt-dlp
                    video_id = youtube_data.get('url')
                    if video_id:
                        print(f"Streaming from YouTube: {video_id}")
                        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                        stream_url, duration = youtube_control.get_youtube_stream_url(youtube_url)
                        if stream_url:
                            youtube_ui.stream_youtube(stream_url)
                        else:
                            print(f"Failed to get stream URL for {video_id}")
                    else:
                        youtube_ui.stream_youtube(os.path.join("youtube", filename))  # Try anyway
            else:
                if play_filename(playlist_entry, fullscreen=not same_index or state.controls.autoplay_toggle != 1):
                    state.widgets.root.after(3000, thread_prefetch_metadata)
                    state.widgets.root.after(1000, lightning_manager.queue_next_lightning_mode)
        else:
            if play_filename(playlist_entry, fullscreen=not same_index or state.controls.autoplay_toggle != 1):
                state.widgets.root.after(3000, thread_prefetch_metadata)
                state.widgets.root.after(1000, lightning_manager.queue_next_lightning_mode)
    else:
        if index < 0:
            play_next()
        else:
            messagebox.showinfo("Playlist Error", "Invalid playlist index.")
        return
    
    if state.metadata.playlist["current_index"]+1 < len(state.metadata.playlist["playlist"]):
        next_filename = entry_paths.get_clean_filename(state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]+1])
        state.widgets.root.after(1000, check_next_queue_round, next_filename)
    add_session_history()


def skip_filename():
    global skip_limit
    blind_screen.blind_round_toggle = False
    peek_dispatch.peek_round_toggle = False
    peek_dispatch.mute_peek_round_toggle = False
    skip_limit += 1
    play_video(state.metadata.playlist["current_index"] + state.seek.skip_direction)  # Try playing the next video


def play_filename_streaming_fallback(playlist_entry, fullscreen=True):
    """Handle streaming fallback when download times out."""
    global animethemes_stream
    
    # Extract filename from dict if necessary
    if isinstance(playlist_entry, dict):
        filename = playlist_entry.get('filename', playlist_entry.get('filepath', ''))
    else:
        filename = playlist_entry
    
    # Force streaming mode by setting filepath to stream URL
    filename = entry_paths.get_clean_filename(filename) 
    stream_url = None
    if isinstance(playlist_entry, dict) and '_stream_url' in playlist_entry:
        stream_url = playlist_entry['_stream_url']
    else:
        stream_url = cache_download.get_animethemes_stream_url(filename)
    
    # Create modified entry with filepath
    if isinstance(playlist_entry, dict):
        modified_entry = playlist_entry.copy()
        modified_entry['filepath'] = stream_url
    else:
        modified_entry = {'filename': playlist_entry, 'filepath': stream_url}
    
    animethemes_stream = True
    return play_filename(modified_entry, fullscreen)


def play_filename(playlist_entry, fullscreen=True):
    global skip_limit, animethemes_stream
    _pe_str = playlist_entry.get('filename', playlist_entry.get('filepath', '')) if isinstance(playlist_entry, dict) else playlist_entry
    filename = entry_paths.get_clean_filename(_pe_str)
    data = metadata_fetch.get_metadata(filename, fetch=state.config.auto_fetch_missing)
    
    local_filepath = entry_paths.get_file_path(playlist_entry)
    result = cache_download.resolve_playable_path(filename, playlist_entry, local_filepath, fullscreen)
    if result is None:
        return False
    filepath, animethemes_stream = result
    
    if skip_limit <= 10:
        if not filepath or not (os.path.exists(filepath) or animethemes_stream):  # Check if file exists
            print(f"File not found: {filepath}. Skipping...")
            skip_filename()
            return False
        elif not state.lightning.fixed_current_round and not variety_round.variety_light_mode_enabled and state.lightning.light_mode and not variety_round.has_lightning_mode_info(data, state.lightning.light_mode):
            print(f"Not enough info for {filename}. Skipping...")
            skip_filename()
            return False
    
    # Start prefetching next themes after we've started playing
    threading.Thread(target=cache_download.prefetch_next_themes, daemon=True).start()
    
    state.playback.currently_playing.clear()
    state.playback.currently_playing.update({
        "type":"theme",
        "filename":filename,
        "playlist_entry":playlist_entry,
        "data":data
    })
    censors.on_play_starting()
    if variety_round.variety_light_mode_enabled:
        variety_round.set_variety_light_mode()
    if state.controls.auto_info_start:
        information_popup.toggle_title_popup(True)
    if state.controls.auto_bonus_start and not (state.lightning.fixed_current_round and state.lightning.fixed_current_round.get("mc_choice_2")):
        pick = bonus._pick_random_bonus() if state.controls.auto_bonus_start == "random" else state.controls.auto_bonus_start
        if pick == "buzzer" and bonus.guessing_extra == "buzzer":
            buzz._web_buzzer_open()
            scoreboard_control.send_command("[CLEAR_SUBMITTED]")
            for _pname in web_server.get_connected_player_names():
                scoreboard_control.send_command(f"[SERVED]{_pname}")
            popout_window._refresh_popout_toggles()
            if web_server.is_running():
                bonus_answers._push_web_toggles()
        else:
            bonus.guess_extra(pick)
    # Auto-queue a reveal round at the start of every theme (the "Auto Reveal at
    # Start" option — analogous to auto_bonus_start above). Skipped when a round
    # is already armed manually this turn, so a deliberate host queue overrides
    # the auto default for that one round. armed_auto_reveal gates the timed fade
    # kicked off at the peek consumption site below.
    armed_auto_reveal = False
    if (state.controls.auto_reveal_start and not state.lightning.light_mode
            and not blind_screen.blind_round_toggle
            and not peek_dispatch.peek_round_toggle
            and not peek_dispatch.mute_peek_round_toggle):
        _ar_mode = state.controls.auto_reveal_start
        if _ar_mode == "auto":
            # Pick the round type from this theme's popularity (easy→mute, medium→blind, hard→reveal).
            _ar_mode = peek_dispatch.resolve_auto_reveal_mode(data)
        if _ar_mode == "blind":
            blind_screen.blind_round_toggle = True
        else:
            peek_dispatch._queued_peek_variant[0] = state.controls.auto_reveal_variant
            if _ar_mode == "mute":
                peek_dispatch.mute_peek_round_toggle = True
            else:
                peek_dispatch.peek_round_toggle = True
            armed_auto_reveal = state.controls.auto_reveal_seconds > 0
    # Update metadata display asynchronously
    metadata_display.update_metadata_queue(state.metadata.playlist["current_index"])
    state.playback.previous_media = filepath  # store path string for repeat playback
    # Pre-load black cover: applied before set_media so OSD dims from the previous
    # video are still valid. Prevents the new file's first decoded frame from being
    # visible before blind/reveal overlays are active. The playback-restart hook
    # (or the blind_round_toggle branch below) reapplies/removes it as needed.
    if not state.lightning.light_mode and (blind_screen.blind_round_toggle or peek_dispatch.peek_round_toggle or peek_dispatch.mute_peek_round_toggle):
        _pre_load_blind_color = censors.get_image_color() if blind_screen.blind_round_toggle else 'black'
        blind_screen.set_black_screen(True, smooth=False, color=_pre_load_blind_color)
    start_skip_end = censors.get_start_skip_end(filename)
    state.widgets.player.set_media(filepath, start_seconds=start_skip_end)
    censors.reset_for_new_file(filename)
    global background_music_rounds
    if state.lightning.light_mode:
        if "c." in state.lightning.light_mode:
            set_rules("character")
        elif state.lightning.light_mode == "trivia":
            set_rules("trivia")
        else:
            set_rules("anime")
        
        # Exclude modes that don't play background music: clip, ost (streaming), regular, blind (play theme audio)
        if state.lightning.light_mode not in ['clip', 'ost', 'regular', 'blind']:
            if background_music_rounds > 0 and background_music_rounds % state.playback.lightning_mode_settings["_misc_settings"]["background_music"]["rounds_per_track"] == 0:
                music.next_background_track()
            background_music_rounds += 1
        
        state.lightning.light_round_number = state.lightning.light_round_number + 1
        if state.lightning.light_mode != 'reveal':
            lightning_manager.update_light_round_number()
            
        state.lightning.light_round_length = state.playback.lightning_mode_settings.get(state.lightning.light_mode, {}).get("length", lightning_settings.LIGHT_ROUND_LENGTH_DEFAULT)
        if state.lightning.fixed_lightning_round_playlist_data and state.lightning.fixed_current_round:
            state.lightning.light_round_length = state.lightning.fixed_current_round.get("duration", state.lightning.light_round_length)
        if not blind_screen.black_overlay:
            blind_screen.set_black_screen(True)
            state.widgets.root.after(500, player_play)
        else:
            player_play()
            audio_toggles.set_volume(state.controls.volume_level)
    else:
        set_rules()
        state.lightning.light_round_number = 0
        osd_text.set_countdown()
        lightning_manager.set_light_round_number()
        coming_up_ui.toggle_coming_up_popup(False, "Lightning Round")
        if blind_screen.blind_round_toggle:
            blind_screen.manual_blind = True
            state.widgets.root.after(500, player_play)
        elif peek_dispatch.peek_round_toggle or peek_dispatch.mute_peek_round_toggle:
            blind_screen.manual_blind = False
            peek_dispatch.toggle_peek()
            if armed_auto_reveal:
                # Fade this auto-queued reveal fully off over N seconds of playback.
                peek_dispatch.start_timed_reveal(state.controls.auto_reveal_seconds)
            if not peek_dispatch.peek_round_toggle:
                music.next_background_track()
                audio_toggles.toggle_mute(True)
            state.widgets.root.after(500, player_play)
            # Don't remove the black screen here â€” playback-restart hook lifts it
            # once the peek overlay is confirmed active on the new file's first frame.
        else:
            blind_screen.manual_blind = False
            player_play()
            state.widgets.root.after(0, lambda: blind_screen.set_black_screen(False))
    blind_screen.blind_round_toggle = False
    peek_dispatch.peek_round_toggle = False
    peek_dispatch.mute_peek_round_toggle = False
    if fullscreen and state.controls.autoplay_fullscreen and state.lightning.light_mode not in ['clip', 'ost']:
        state.widgets.root.after(150, lambda: state.widgets.player.set_fullscreen(True))
    if state.lightning.light_mode not in ['frame', 'clip', 'ost', 'blind']:
        retry_delay = 250
        if animethemes_stream:
            retry_delay = 5000  # Longer delay for streaming to allow time for buffering
        if state.controls.autoplay_toggle != 3:
            state.widgets.root.after(retry_delay, play_video_retry, 5, filename)  # Retry playback
    
    if state.metadata.playlist.get("infinite", False):
        lightning_changed = False
        current_entry = state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]]
        if not state.lightning.fixed_current_round and state.playback.currently_playing.get("filename") == entry_paths.get_clean_filename(current_entry):
            if state.lightning.light_mode:  # Lightning round
                if not current_entry.startswith("[L]"):
                    state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]] = "[L]" + current_entry
                    lightning_changed = True
            else:  # Normal round
                if current_entry.startswith("[L]"):
                    state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]] = current_entry[3:]
                    lightning_changed = True
        
        if lightning_changed:
            state.widgets.root.after(10, lists.refresh_current_list)
    
    # Update playlist name to reflect new count (will be updated when session log is added)
    state.widgets.root.after(100, update_playlist_name)
    skip_limit = 0
    config_io.save_config()
    return True


def play_video_retry(retries, filename=None):
    retry_delay = 2000
    if animethemes_stream:
        retry_delay = 5000 + 1000*(5-retries)  # Increase delay with each retry for streaming
    if (not state.widgets.player.is_playing() or state.widgets.player.get_length() == 0) and filename and state.playback.currently_playing.get("filename") == filename:
        if retries > 0:
            if retries < 5:
                print(f"Retrying playback for: {state.playback.currently_playing.get('filename')}")
                player_play()
            state.widgets.root.after(retry_delay, play_video_retry, retries - 1, filename)  # Retry playback
            return
        else:
            play_video(state.metadata.playlist["current_index"] + state.seek.skip_direction)
    set_skip_direction(1)
    state.controls.video_stopped = False


def _handle_video_end():
    """Called on the main thread when a video reaches its natural end.
    Contains the advance-or-loop logic previously polled by check_video_end."""
    if state.controls.video_stopped or state.controls.autoplay_toggle == 2:
        return
    # During the lightning question phase the player has paused at EOF (keep-open=yes).
    # Calling play_next() here risks falling through to the next-track path if any
    # state variable is momentarily inconsistent.  Instead, seek past the round
    # boundary directly and call player.play() so that update_light_round (which only
    # runs when the player IS playing) detects elapsed >= light_round_length and
    # triggers the answer phase normally.
    if state.lightning.light_round_started and state.lightning.light_round_start_time is not None and state.lightning.light_answer_wall_start is None:
        try:
            if streaming.currently_streaming:
                seek_target_ms = round((state.lightning.stream_start_time + state.lightning.light_round_length + 0.1) * 1000)
                state.widgets.player.set_time(seek_target_ms)
            else:
                answer_ms = int((state.lightning.light_round_start_time + state.lightning.light_round_length + 0.05) * 1000)
                seek_to(answer_ms)
            was_playing = state.widgets.player.is_playing()
            if not was_playing:
                state.widgets.player.play()
        except Exception as e:
            print(f"[DBG _handle_video_end] exception in lightning branch: {e}")
        state.controls.video_stopped = True  # guard against re-entry if eof-reached fires again
        return
    if state.controls.autoplay_toggle == 0:
        play_next()
        state.controls.video_stopped = True
    else:
        state.widgets.player.pause()
        state.widgets.player.set_media(state.playback.previous_media)
        state.widgets.player.play()


def go_to_index():
    """Function to jump to a specific index"""
    total = len(state.metadata.playlist["playlist"])
    index = simpledialog.askinteger("Go to Index", f"Enter track number (1\u2013{total}):", minvalue=1, maxvalue=total)
    if index is not None:
        play_video(index - 1)


def play_pause():
    """Function to play/pause the video"""
    state.controls.video_stopped = True
    if frame_round.frame_light_round_started:
        frame_round.frame_light_round_pause = not frame_round.frame_light_round_pause
        playpause_icon._show_playpause_icon(frame_round.frame_light_round_pause)
        return
    elif state.lightning.light_mode and state.playback.lightning_mode_settings.get(state.lightning.light_mode, {}).get("muted") and state.lightning.light_mode not in ['clip', 'ost']:
        if state.widgets.player.is_playing():
            pygame.mixer.music.pause()
        elif state.lightning.light_round_start_time and ((state.widgets.player.get_time()/1000) < (state.lightning.light_round_start_time+state.lightning.light_round_length)):
            pygame.mixer.music.unpause()
    if state.widgets.player.is_playing():
        state.controls.video_stopped = True
        state.widgets.player.pause()
        playpause_icon._show_playpause_icon(True)
    elif state.widgets.player.get_media():
        state.widgets.player.play()
        state.controls.video_stopped = False
        playpause_icon._show_playpause_icon(False)
    else:
        play_video(state.metadata.playlist["current_index"])


def play_next():
    if skip_to_lightning_answer():
        return
    elif (state.lightning.light_round_started or ((state.lightning.light_mode or state.lightning.fixed_lightning_queue) and state.lightning.light_round_number == 0)) and not blind_screen.black_overlay:
        lightning_manager.light_round_transition()
        return
    if state.controls.special_repeat_track_mode:
        autoplay_toggles.toggle_special_repeat()
    set_skip_direction(1)
    if playlist_loaded or playlist_ops.playlist_changed:
        play_video(state.metadata.playlist["current_index"])
    elif state.lightning.fixed_lightning_round_playlist_data or state.lightning.fixed_lightning_queue:
        play_video(state.metadata.playlist["current_index"])
    else:
        if state.metadata.playlist["current_index"] + 1 >= len(state.metadata.playlist["playlist"]):
            infinite._promote_or_generate_next()
        if state.metadata.playlist["current_index"] + 1 < len(state.metadata.playlist["playlist"]):
            play_video(state.metadata.playlist["current_index"] + 1)


def play_previous():
    """Function to play previous video"""
    if state.metadata.playlist["current_index"] - 1 >= 0:
        set_skip_direction(-1)
        play_video(state.metadata.playlist["current_index"] - 1)


def update_seek_bar():
    """Recurring seek-bar / playback tick (rescheduled every SEEK_POLLING ms)."""
    global playing_next_error
    player = state.widgets.player
    seek_bar = state.widgets.seek_bar
    currently_playing = state.playback.currently_playing
    try:
        if not player.is_playing():
            player_time = player.get_time()
            if player_time != state.seek.last_player_time or state.seek.last_player_time != state.seek.projected_player_time:
                state.seek.last_player_time = player_time
                state.seek.projected_player_time = player_time
                if not state.seek.last_seek_time:
                    state.seek.can_seek = False
                    seek_bar.set(player_time/1000)
        else:
            player_time = player.get_time()
            if player_time != state.seek.last_player_time:
                state.seek.last_player_time = player_time
                state.seek.projected_player_time = player_time
            else:
                state.seek.projected_player_time = state.seek.projected_player_time + state.seek.SEEK_POLLING * state.lightning.light_speed_modifier
            skip_play_ms = int(max(0, float(state.config.skip_play_seconds)) * 1000)
            skip_jump_ms = int(max(0, float(state.config.skip_jump_seconds)) * 1000)
            skip_triggered = False
            # Throttled to every 5th tick (~4Hz): push_timer broadcasts to every
            # connected client, and at full tick rate (20Hz) the serialize+enqueue
            # cost scales with the player count on the main thread. The client
            # display has whole-second granularity, so 4Hz is visually identical.
            if (state.seek.web_playback_counter % 5 == 0 and not state.lightning.light_round_started
                    and bonus.guessing_extra and web_server.is_running()):
                if (bonus.guessing_extra == "yt_bonus" and bonus._yt_bonus_current_question
                        and bonus._yt_bonus_current_question.get("end_time", 0) > 0):
                    _time_left = max(0.0, bonus._yt_bonus_current_question["end_time"] - state.seek.projected_player_time / 1000)
                else:
                    _eff_rem = progress_bar_ops._effective_remaining_ms(
                        state.seek.projected_player_time, player.get_length(),
                        currently_playing.get("filename")
                    )
                    _time_left = _eff_rem / 1000.0 - (8 if state.controls.auto_info_end else 0)
                web_server.push_timer(_time_left, paused=True)
            if currently_playing.get("type") != "youtube" and not state.lightning.light_round_started and skip_play_ms > 0 and skip_jump_ms > 0:
                if state.seek.last_skip_anchor_ms is None or state.seek.last_seek_time or state.seek.projected_player_time < state.seek.last_skip_anchor_ms:
                    state.seek.last_skip_anchor_ms = state.seek.projected_player_time
                time_since_anchor = state.seek.projected_player_time - state.seek.last_skip_anchor_ms
                time_to_skip = skip_play_ms - time_since_anchor
                fade_window_ms = min(skip_play_ms, state.config.SKIP_FADE_WINDOW_MS)
                if state.seek.skip_fade_in_elapsed_ms is None and not state.controls.disable_video_audio and fade_window_ms > 0:
                    if time_to_skip <= fade_window_ms:
                        fade_factor = max(0.0, min(1.0, time_to_skip / fade_window_ms))
                        player.audio_set_volume(int(state.controls.volume_level * fade_factor))
                    else:
                        player.audio_set_volume(state.controls.volume_level)
                if time_since_anchor >= (skip_play_ms - state.seek.SEEK_POLLING):
                    # Nudge past the boundary so it doesn't immediately re-trigger
                    skip_offset = max(state.seek.SEEK_POLLING, 1)
                    total_length_ms = player.get_length()
                    if total_length_ms > 0 and (state.seek.projected_player_time + skip_jump_ms + skip_offset) >= total_length_ms:
                        play_next()
                    else:
                        seek_to(state.seek.projected_player_time + skip_jump_ms + skip_offset)
                    state.seek.last_skip_anchor_ms = state.seek.projected_player_time + skip_jump_ms
                    state.seek.skip_fade_in_elapsed_ms = 0
                    skip_triggered = True
            else:
                state.seek.last_skip_anchor_ms = None
                state.seek.skip_fade_in_elapsed_ms = None

            if not skip_triggered:
                if not state.controls.disable_video_audio and state.seek.skip_fade_in_elapsed_ms is not None:
                    state.seek.skip_fade_in_elapsed_ms += (state.seek.SEEK_POLLING * state.lightning.light_speed_modifier)
                    fade_factor = max(0.0, min(1.0, state.seek.skip_fade_in_elapsed_ms / max(1, state.config.SKIP_FADE_IN_WINDOW_MS)))
                    player.audio_set_volume(int(state.controls.volume_level * fade_factor))
                    if fade_factor >= 1.0:
                        state.seek.skip_fade_in_elapsed_ms = None
                length = player.get_length()/1000
                time = state.seek.projected_player_time/1000
                if blind_screen.manual_blind and not state.lightning.light_round_started:
                    _eff_time, _eff_len = progress_bar_ops._apply_skip_censor_to_progress(
                        time * 1000, length * 1000, currently_playing.get("filename")
                    )
                    progress_overlay_ops.set_progress_overlay(_eff_time / 1000, _eff_len / 1000)
                if peek_overlay.peek_overlay1 and not state.lightning.light_round_started:
                    gap = peek_dispatch.get_peek_gap(currently_playing.get("data"))
                    progress = ((time+peek_dispatch.peek_modifier)%24/12)*100
                    if progress >= 100:
                        direction = "right"
                        progress -= 100
                    else:
                        direction = "down"
                    peek_overlay.toggle_peek_overlay(direction=direction, progress=progress, gap=gap)
                if length > 0:
                    # Auto-revoke skip grant when already within the last 3 seconds
                    if web_server.is_running() and web_server.get_skip_grant_player():
                        if time >= length - 3:
                            web_server.push_skip_grant('')
                    if not state.seek.last_seek_time:
                        state.seek.can_seek = False
                        seek_bar.config(to=length)
                        seek_bar.set(time)
                    if currently_playing.get("type") == "youtube":
                        start = currently_playing.get("data").get("start")
                        end = currently_playing.get("data").get("end")
                        yt_end_time = end if end != 0 else length
                        if time < start:
                            player.set_time(round(start*1000)+100)
                        elif end != 0 and time >= end:
                            player.pause()
                            play_next()
                        elif (yt_end_time - time) <= 8:
                            if (not information_popup.is_title_window_up() or state.info_display.title_info_only) and state.controls.auto_info_end and (not bonus.guessing_extra or bonus.guessing_extra == "buzzer"):
                                information_popup.toggle_title_popup(True)
                        # Bonus template auto-trigger
                        for _bq_i, _bq in enumerate(bonus._yt_bonus_template_questions):
                            _bq_start = _bq.get("start_time", 0)
                            _bq_end = _bq.get("end_time", 0)
                            if _bq_i not in bonus._yt_bonus_template_triggered and time >= _bq_start:
                                if _bq_end > 0 and time >= _bq_end:
                                    # Already past this question's window â€” skip silently
                                    bonus._yt_bonus_template_triggered.add(_bq_i)
                                    bonus._yt_bonus_template_scored.add(_bq_i)
                                else:
                                    bonus._yt_bonus_template_triggered.add(_bq_i)
                                    bonus._yt_bonus_current_question = _bq
                                    bonus._yt_bonus_pts = float(_bq.get("points", 1))
                                    bonus.guess_extra("yt_bonus")
                                break
                            elif (_bq_i in bonus._yt_bonus_template_triggered and
                                  _bq_i not in bonus._yt_bonus_template_scored and
                                  _bq_end > 0 and time >= _bq_end):
                                bonus._yt_bonus_template_scored.add(_bq_i)
                                if bonus.guessing_extra == "yt_bonus":
                                    bonus.guess_extra("yt_bonus")
                                break
                        censors.apply_censors(time, length)
                    else:
                        if not state.lightning.light_round_started and not state.controls.video_stopped and (
                                progress_bar_ops._effective_remaining_ms(time * 1000, length * 1000,
                                                        currently_playing.get("filename")) / 1000.0 <= 8):
                            if (not information_popup.is_title_window_up() or state.info_display.title_info_only) and state.controls.auto_info_end:
                                information_popup.toggle_title_popup(True)
                            if state.controls.coming_up_queue:
                                _cuq = state.controls.coming_up_queue
                                coming_up_ui.toggle_coming_up_popup(True, title=_cuq["title"], details=_cuq["details"], image=_cuq["image"], up_next=_cuq["up_next"])
                                state.controls.coming_up_queue = None
                        lightning_manager.update_light_round(time)
                        peek_dispatch.update_timed_reveal(time)
                        censors.apply_censors(time, length)
                progress_bar_ops.update_progress_bar(state.seek.projected_player_time, player.get_length(), currently_playing.get("filename"))
    except Exception as e:
        error_str = str(e)
        if not playing_next_error:
            if error_str == state.seek.last_error:
                state.seek.last_error_count += 1
                print(f"\rError: {error_str} x {state.seek.last_error_count}", end='', flush=True)
            else:
                state.seek.last_error = error_str
                state.seek.last_error_count = 1
                if state.seek.last_error_count > 20:
                    playing_next_error = True
                    play_next()
                print(f"\nError: {error_str} x 1", flush=True)
    # Push playback state to web host clients ~every 1 second
    state.seek.web_playback_counter += 1
    if state.seek.web_playback_counter >= 20 and web_server.is_running():
        state.seek.web_playback_counter = 0
        try:
            web_server.push_playback_state(
                state.seek.projected_player_time,
                player.get_length(),
                player.is_playing(),
                state.controls.volume_level,
                state.controls.autoplay_toggle,
                state.controls.bgm_volume,
                bzz_modifier=state.playback.bonus_settings.get('buzzer', bonus.BONUS_SETTINGS_DEFAULT['buzzer']).get('sound_volume', 1.0),
                strm_boost=state.controls.stream_volume_boost
            )
            bonus_answers._push_web_toggles()
        except Exception:
            pass
    state.widgets.root.after(state.seek.SEEK_POLLING, update_seek_bar)
