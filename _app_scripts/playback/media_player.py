"""
Unified media-player abstraction - Phase 2: mpv backend.

All time values are in milliseconds (consistent with the rest of the app).
Volume uses the 0-200 scale that the app has always used (mpv 0-100 is doubled).

Extracted from guess_the_anime.py. The class is constructed once in main with
a configured mpv.MPV instance; main owns the property observers and event
callbacks (which reach into many main globals) and the player instance lives
on state.widgets.player.
"""


class MediaPlayer:
    """
    Unified media-player abstraction - Phase 2: mpv backend.

    All time values are in milliseconds (consistent with the rest of the app).
    Volume uses the 0-200 scale that the app has always used (mpv 0-100 is doubled).
    """

    def __init__(self, mpv_player):
        self._p = mpv_player          # underlying mpv.MPV instance
        # Register double-click to toggle fullscreen (mirrors Player default behaviour)
        try:
            self._p.command('keybind', 'MBTN_LEFT_DBL', 'cycle fullscreen')
        except Exception:
            pass
        # Close button stops playback (hides window) without destroying the player instance
        try:
            self._p.command('keybind', 'CLOSE_WIN', 'stop')
        except Exception:
            pass

    # ---- Core playback ----
    def play(self):
        """Resume playback (does NOT load a new file)."""
        try:
            self._p.pause = False
        except Exception:
            pass

    def pause(self):
        try:
            self._p.pause = True
        except Exception:
            pass

    def stop(self):
        try:
            self._p.stop()
        except Exception:
            pass

    def is_playing(self) -> bool:
        try:
            return (not self._p.pause) and (not self._p.core_idle) and (self._p.time_pos is not None)
        except Exception:
            return False

    # ---- Time (all in milliseconds) ----
    def get_time_ms(self) -> int:
        try:
            return max(0, int((self._p.time_pos or 0) * 1000))
        except Exception:
            return 0

    def set_time_ms(self, ms: int):
        try:
            self._p.seek(ms / 1000.0, 'absolute+exact')
        except Exception:
            pass

    def get_length_ms(self) -> int:
        try:
            return max(0, int((self._p.duration or 0) * 1000))
        except Exception:
            return 0

    # ---- Time: compat shims (same unit — ms) ----
    def get_time(self) -> int:    return self.get_time_ms()
    def set_time(self, ms: int):  self.set_time_ms(ms)
    def get_length(self) -> int:  return self.get_length_ms()

    # ---- Volume: 0-200 scale (app convention) ----
    def set_volume(self, v: int):
        try:
            self._p.volume = max(0.0, min(100.0, v / 2.0))
        except Exception:
            pass

    def get_volume(self) -> int:
        try:
            return int((self._p.volume or 0) * 2)
        except Exception:
            return 0

    # ---- Volume: compat shims ----
    def audio_set_volume(self, v: int):    self.set_volume(v)
    def audio_get_volume(self) -> int:     return self.get_volume()

    def audio_set_mute(self, muted: bool):
        try:
            self._p.mute = bool(muted)
        except Exception:
            pass

    def audio_get_mute(self) -> bool:
        try:
            return bool(self._p.mute)
        except Exception:
            return False

    # ---- Speed ----
    def set_speed(self, rate: float):
        try:
            self._p.speed = rate
        except Exception:
            pass

    def set_rate(self, rate: float):  self.set_speed(rate)  # compat

    # ---- Fullscreen ----
    def set_fullscreen(self, b: bool):
        try:
            self._p.fullscreen = bool(b)
        except Exception:
            pass

    def toggle_fullscreen(self):
        try:
            self._p.fullscreen = not self._p.fullscreen
        except Exception:
            pass

    # ---- Video info ----
    def get_video_size(self) -> tuple:
        try:
            w, h = self._p.width, self._p.height
            if w and h:
                return (w, h)
        except Exception:
            pass
        return (0, 0)

    def video_get_size(self, track=0) -> tuple:
        return self.get_video_size()

    # ---- Media loading ----
    def load(self, path: str, opts: list = None):
        """Load and play a file/URL. opts is ignored (mpv handles format detection)."""
        self.set_media(path)

    def unload(self):
        """Stop and clear current media."""
        try:
            self._p.stop()
        except Exception:
            pass

    def get_path(self) -> str:
        """Return the path/URL of the currently loaded file, or None."""
        try:
            return self._p.path
        except Exception:
            return None

    def set_media(self, path_or_none):
        """Load path/URL and start playing, or stop if None."""
        if path_or_none is None:
            self.unload()
        else:
            try:
                self._p.play(str(path_or_none))
            except Exception:
                pass

    def get_media(self):
        """Return the currently loaded path string (compat shim)."""
        return self.get_path()

    # ---- State compat (no-op with mpv) ----
    def get_state(self):
        return None

    # ---- Window embedding (Phase 3) ----
    def set_hwnd(self, hwnd: int):
        try:
            self._p.wid = str(hwnd)
        except Exception:
            pass
