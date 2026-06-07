"""mpv.MPV construction + observer wiring for the app's single MediaPlayer.

Main loads the mpv module via mpv_bootstrap, then calls create_player(mpv) once
to build the configured MediaPlayer and register its property observers. The
returned instance is published on state.widgets.player during GUI setup.
"""

import sys
from tkinter import messagebox

from _app_scripts.playback.media_player import MediaPlayer
import _app_scripts.playback.mpv_events as mpv_events


def _mpv_opts(**extra):
    """Return common mpv.MPV constructor keyword arguments."""
    return dict(
        keep_open='yes',
        idle='yes',
        input_default_bindings=False,
        input_vo_keyboard=False,
        osc=False,
        force_media_title='Guess the Anime! - Playlist Tool',
        auto_window_resize='no',
        **extra
    )


def create_player(mpv):
    """Build the MediaPlayer, register observers, and return it.

    On failure, show an error (falling back to print) and sys.exit(1) — the app
    cannot run without a working mpv player.
    """
    try:
        player = MediaPlayer(mpv.MPV(**_mpv_opts(force_window='no')))
        mpv_events.register_observers(player)
        return player
    except Exception as _e:
        try:
            messagebox.showerror("mpv error", f"Failed to create mpv player:\n{_e}")
        except Exception:
            print(f"FATAL: Failed to create mpv player: {_e}")
        sys.exit(1)
