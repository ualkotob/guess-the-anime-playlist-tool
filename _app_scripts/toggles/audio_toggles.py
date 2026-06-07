"""Audio mute, volume, and test distortion toggle commands."""

import pygame

import _app_scripts.playback.streaming as streaming
import _app_scripts.playback.music as music
from core.game_state import state

AUDIO_DISTORTION_FILTERS = {
    "echo": "aecho=0.8:0.8:500|700:0.4|0.3",
    "flanger": "flanger",
    "vibrato": "lavfi=[vibrato=f=7:d=0.5]",
    "telephone": "lavfi=[highpass=f=300,lowpass=f=3400]",
    "underwater": "lavfi=[lowpass=f=400,aecho=0.5:0.5:300:0.8]",
    "chipmunk": "lavfi=[asetrate=88200,aresample=44100]",
    "demon": "lavfi=[asetrate=22050,aresample=44100]",
    "vaporwave": "lavfi=[asetrate=35280,aresample=44100]",
    "8bit_game": "lavfi=[acrusher=level_in=8:bits=2:mode=log,aresample=8000,aresample=44100]",
    "robot": "lavfi=[aecho=0.9:0.9:10|20|30:0.9|0.9|0.9,vibrato=f=30:d=0.9]",
}

audio_distortions_active = set()


def _set_main_volume_level(value):
    state.controls.volume_level = int(value)


def set_volume(value):
    """Set video and background-music volume from the app volume level."""
    volume_level = int(value)
    _set_main_volume_level(volume_level)

    player = state.widgets.player
    if streaming.currently_streaming:
        fixed_current_round = state.lightning.fixed_current_round
        volume_adjustment = (
            fixed_current_round.get("volume_adjustment", 0)
            if fixed_current_round
            else 0
        )
        stream_volume_boost = state.controls.stream_volume_boost
        stream_volume_level = int(
            volume_level * (1 + ((stream_volume_boost + volume_adjustment) / 100))
        )
        player.audio_set_volume(stream_volume_level)
    else:
        player.audio_set_volume(volume_level)

    if music.music_loaded:
        if state.controls.disable_video_audio or volume_level == 0:
            vol = 0.0
        else:
            # dB-based curve: perceptually linear across the full scale.
            bgm_db_range = 45
            bgm_volume = state.controls.bgm_volume
            vol = bgm_volume * (10 ** ((volume_level / 200 - 1) * bgm_db_range / 20))
        pygame.mixer.music.set_volume(vol)

    state.widgets.volume_label.config(text=str(state.controls.volume_level))


def increase_volume():
    """Increase volume by 5."""
    set_volume(min(200, state.controls.volume_level + 5))


def decrease_volume():
    """Decrease volume by 5."""
    set_volume(max(0, state.controls.volume_level - 5))


def increase_volume_small(event=None):
    """Increase volume by 1 (used for right-click)."""
    set_volume(min(200, state.controls.volume_level + 1))
    return "break"


def decrease_volume_small(event=None):
    """Decrease volume by 1 (used for right-click)."""
    set_volume(max(0, state.controls.volume_level - 1))
    return "break"


def _apply_audio_distortions():
    filters = [
        AUDIO_DISTORTION_FILTERS[k]
        for k in audio_distortions_active
        if k in AUDIO_DISTORTION_FILTERS
    ]
    try:
        state.widgets.player._p["af"] = ",".join(filters) if filters else ""
    except Exception as e:
        print(f"Audio distortion apply error: {e}")


def toggle_audio_distortion(key):
    if key in audio_distortions_active:
        audio_distortions_active.clear()
    else:
        audio_distortions_active.clear()
        audio_distortions_active.add(key)
    _apply_audio_distortions()
    print(f"Audio distortions active: {audio_distortions_active}")


def toggle_mute(muted=None, lightning=False):
    light_mode = state.lightning.light_mode
    light_round_started = state.lightning.light_round_started
    disable_video_audio = state.controls.disable_video_audio
    light_muted = state.controls.light_muted
    player = state.widgets.player

    if light_mode or light_round_started or lightning:
        if muted is None:
            muted = not light_muted
        state.controls.light_muted = muted
        if not disable_video_audio:
            player.audio_set_mute(muted)
            if not muted:
                set_volume(state.controls.volume_level)
        music.play_background_music(
            muted
            and not streaming.currently_streaming
            and light_mode not in ["clip", "ost"]
        )
    else:
        if muted is None:
            muted = not disable_video_audio
        state.controls.disable_video_audio = muted
        player.audio_set_mute(muted)
        if music.music_loaded:
            set_volume(state.controls.volume_level)
