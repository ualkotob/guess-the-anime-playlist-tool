"""Frame lightning round — reveals four still frames from the video.

Owns frame-round state and timing. The round picks four frames spaced across
the (uncensored) video duration, pauses on each in turn, then plays the full
clip for the answer phase.
"""
from __future__ import annotations
from core.game_state import state
from _app_scripts.playback import osd_text, music, coming_up_ui, blind_screen
from _app_scripts.playback import progress_bar as progress_bar_ops
from _app_scripts.toggles import censors
from _app_scripts.information import information_popup

import random


# ---------------------------------------------------------------------------
# Frame-round state
# ---------------------------------------------------------------------------
frame_light_round_started = False
frame_light_round_frames = None
frame_light_round_frame_index = None
frame_light_round_frame_time = None
frame_light_round_pause = False


def get_frame_light_round_frames():
    frames = []
    if state.lightning.fixed_lightning_round_playlist_data and state.lightning.fixed_current_round:
        for f in range(4):
            frames.append(state.lightning.fixed_current_round.get('frame'+str(f+1)))
        return frames
    buffer = 5
    video_length_ms = state.widgets.player.get_length()
    total_length = video_length_ms - ((buffer + state.lightning.light_round_answer_length + 1) * 1000)
    start_time_ms = buffer * 1000
    end_time_ms = start_time_ms + total_length

    # Get file censors and build list of valid time ranges (excluding skip censors)
    file_censors = censors.get_file_censors(state.playback.currently_playing.get('filename'))

    # Build list of valid time ranges by excluding skip censors
    valid_ranges = []
    current_start = start_time_ms / 1000

    # Sort censors by start time
    skip_censors = [c for c in file_censors if c.get('skip')]
    skip_censors.sort(key=lambda c: c['start'])

    for censor in skip_censors:
        censor_start = censor['start']
        censor_end = censor['end'] if censor['end'] else video_length_ms / 1000

        # Add the valid range before this skip censor
        if current_start < censor_start and current_start < end_time_ms / 1000:
            range_end = min(censor_start, end_time_ms / 1000)
            if range_end > current_start:
                valid_ranges.append((current_start, range_end))

        # Move past this skip censor
        current_start = max(current_start, censor_end)

    # Add final range after all skip censors
    if current_start < end_time_ms / 1000:
        valid_ranges.append((current_start, end_time_ms / 1000))

    # If no valid ranges, fall back to original behavior
    if not valid_ranges:
        valid_ranges = [(start_time_ms / 1000, end_time_ms / 1000)]

    # Calculate total valid time
    total_valid_time = sum(end - start for start, end in valid_ranges)
    quadrant_time = total_valid_time / 4

    # Select one frame from each quadrant of valid time
    for quadrant in range(4):
        target_time_start = quadrant * quadrant_time
        target_time_end = (quadrant + 1) * quadrant_time

        # Find which valid range(s) this quadrant falls into
        frame = None
        try_count = 0

        while frame is None and try_count < 20:
            accumulated_time = 0
            # Find the valid range that contains our target time
            random_time_in_quadrant = random.uniform(target_time_start, target_time_end)

            for range_start, range_end in valid_ranges:
                range_duration = range_end - range_start
                if accumulated_time <= random_time_in_quadrant < accumulated_time + range_duration:
                    # This range contains our random point
                    offset = random_time_in_quadrant - accumulated_time
                    frame = range_start + offset

                    is_censored = False
                    for censor in file_censors:
                        if not censor.get('skip') and not censor.get('mute'):
                            if frame > censor['start'] and frame < censor['end']:
                                is_censored = True
                                break

                    if is_censored:
                        frame = None
                        try_count += 1
                        break

                    if total_length > 60000 and len(frames) > 0 and (frame - frames[-1]) <= 5:
                        frame = None
                        try_count += 1
                        break

                    break

                accumulated_time += range_duration

        # If we couldn't find a valid frame after 20 tries, pick any time in the quadrant
        if frame is None:
            accumulated_time = 0
            random_time_in_quadrant = random.uniform(target_time_start, target_time_end)
            for range_start, range_end in valid_ranges:
                range_duration = range_end - range_start
                if accumulated_time <= random_time_in_quadrant < accumulated_time + range_duration:
                    offset = random_time_in_quadrant - accumulated_time
                    frame = range_start + offset
                    break
                accumulated_time += range_duration

        if frame is not None:
            frames.append(frame)

    random.shuffle(frames)
    return frames


def setup_frame_light_round():
    from _app_scripts.queue_round.lightning_rounds import lightning_manager
    global frame_light_round_started, frame_light_round_frames, frame_light_round_frame_index, frame_light_round_frame_time, frame_light_round_pause
    coming_up_ui.toggle_coming_up_popup(False, "Lightning Round")
    frame_light_round_started = True
    state.widgets.player.pause()
    frame_light_round_frames = get_frame_light_round_frames()
    frame_light_round_frame_index = -1
    frame_light_round_frame_time = 5000
    frame_light_round_pause = False
    music.play_background_music(True)
    lightning_manager.update_light_round_number()
    if state.playback.lightning_mode_settings.get("_misc_settings", {}).get("framed_video"):
        state.widgets.root.after(300, blind_screen.set_video_frame, True)
    # Increased delay to give video more time to load before attempting first frame
    state.widgets.root.after(1000, update_frame_light_round, state.playback.currently_playing.get('filename'))
    state.widgets.root.after(1300, blind_screen.set_black_screen, False)


def update_frame_light_round(currently_playing_filename):
    from _app_scripts.queue_round.lightning_rounds import lightning_manager
    global frame_light_round_frame_index, frame_light_round_frame_time

    if not frame_light_round_started or state.playback.currently_playing.get('filename') != currently_playing_filename:
        return

    show_frame_length = (state.lightning.light_round_length/4)*1000
    if not frame_light_round_pause:
        if not state.widgets.player.is_playing():
            if frame_light_round_frames and 0 <= frame_light_round_frame_index < len(frame_light_round_frames):
                time = int(frame_light_round_frames[frame_light_round_frame_index]*1000)
                length = state.widgets.player.get_length()
                censors.apply_censors(time/1000,length/1000)
        frame_light_round_frame_time = frame_light_round_frame_time + state.seek.SEEK_POLLING
        if frame_light_round_frame_index < 4:
            music.play_background_music(True)
            if state.widgets.player.is_playing():
                state.widgets.player.pause()
        else:
            state.widgets.player.play()
    else:
        music.play_background_music(False)
        if state.widgets.player.is_playing():
            state.widgets.player.pause()
    if frame_light_round_frame_index == 4:
        start_str = "next"
        if not state.lightning.light_mode or (state.lightning.fixed_lightning_round_playlist_data and state.lightning.fixed_lightning_round_playlist_data.get("current_index") == state.lightning.fixed_lightning_round_playlist_data.get("round_count") - 1):
            start_str = "end"
        osd_text.set_countdown(start_str + " in..." + str(round(((state.lightning.light_round_answer_length*1000)-frame_light_round_frame_time)/1000)))
        if frame_light_round_frame_time >= state.lightning.light_round_answer_length*1000:
            lightning_manager.light_round_transition()
            return
    else:
        if frame_light_round_frame_index > -1:
            osd_text.set_countdown(int(((state.lightning.light_round_length*1000)-((show_frame_length*frame_light_round_frame_index)+frame_light_round_frame_time))/1000))
        if frame_light_round_frame_time >= show_frame_length:
            # Check if video is loaded before attempting to show next frame
            length = state.widgets.player.get_length()
            if length <= 0:
                # Video not loaded yet, wait for next cycle without incrementing frame
                state.widgets.root.after(state.seek.SEEK_POLLING, update_frame_light_round, currently_playing_filename)
                return

            frame_light_round_frame_index = frame_light_round_frame_index + 1
            if frame_light_round_frame_index < len(frame_light_round_frames):
                frame_light_round_frame_time = 0
                if frame_light_round_frame_index == 0:
                    frame_light_round_frame_time = -1000
                time = int(frame_light_round_frames[frame_light_round_frame_index]*1000)
                censors.apply_censors(time/1000, length/1000)

                # Attempt to set time with retry limit to avoid infinite loop
                max_attempts = 20
                for attempt in range(max_attempts):
                    state.widgets.player.set_time(time)
                    state.widgets.root.update()  # Process pending events
                    if abs(state.widgets.player.get_time() - time) < 100:  # Within 100ms is close enough
                        break

                # Ensure player stays paused after seeking
                if state.widgets.player.is_playing():
                    state.widgets.player.pause()

                progress_bar_ops.update_progress_bar(time, length, state.playback.currently_playing.get("filename"))
                osd_text.bottom_info(str(frame_light_round_frame_index+1) + "/" + str(len(frame_light_round_frames)))
            elif not information_popup.is_title_window_up():
                frame_light_round_frame_time = 0
                state.widgets.player.play()
                information_popup.toggle_title_popup(True)
                osd_text.bottom_info()
                music.play_background_music(False)

    state.widgets.root.after(state.seek.SEEK_POLLING, update_frame_light_round, currently_playing_filename)
