"""Unified media-player abstraction over the mpv backend.

All time values are in milliseconds (consistent with the rest of the app).
Volume uses the 0-200 scale that the app has always used (mpv 0-100 is doubled).

The class is constructed once in main with a configured mpv.MPV instance; main
owns the property observers and event callbacks, and the player instance lives
on state.widgets.player.
"""

from core.app_logging import log_exception


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
        # Observer-backed property cache. Every direct property read is a
        # synchronous round-trip into the libmpv core and can block the calling
        # (Tk) thread whenever the core is busy (seek/load/buffering). The seek
        # ticker reads these many times per 50ms tick, so hot-path getters serve
        # these cached values instead; mpv's event thread keeps them fresh.
        self._c_time_pos = None
        self._c_duration = None
        self._c_pause = True
        self._c_core_idle = True
        self._c_width = None
        self._c_height = None
        self._c_osd_width = 0
        self._c_osd_height = 0
        try:
            self._p.observe_property('time-pos', self._on_time_pos)
            self._p.observe_property('duration', self._on_duration)
            self._p.observe_property('pause', self._on_pause)
            self._p.observe_property('core-idle', self._on_core_idle)
            self._p.observe_property('width', self._on_width)
            self._p.observe_property('height', self._on_height)
            self._p.observe_property('osd-width', self._on_osd_width)
            self._p.observe_property('osd-height', self._on_osd_height)
        except Exception:
            log_exception("MediaPlayer: failed to register property-cache observers")

    # ---- Property-cache observer callbacks (run on mpv's event thread) ----
    def _on_time_pos(self, _name, value):   self._c_time_pos = value
    def _on_duration(self, _name, value):   self._c_duration = value
    def _on_pause(self, _name, value):      self._c_pause = bool(value)
    def _on_core_idle(self, _name, value):  self._c_core_idle = bool(value)
    def _on_width(self, _name, value):      self._c_width = value
    def _on_height(self, _name, value):     self._c_height = value
    def _on_osd_width(self, _name, value):  self._c_osd_width = int(value or 0)
    def _on_osd_height(self, _name, value): self._c_osd_height = int(value or 0)

    # ---- Core playback ----
    def play(self):
        """Resume playback (does NOT load a new file)."""
        try:
            self._c_pause = False  # optimistic; observer confirms shortly after
            self._p.pause = False
        except Exception:
            pass

    def pause(self):
        try:
            self._c_pause = True  # optimistic; observer confirms shortly after
            self._p.pause = True
        except Exception:
            pass

    def stop(self):
        try:
            self._c_time_pos = None  # optimistic; observers confirm shortly after
            self._c_core_idle = True
            self._p.stop()
        except Exception:
            pass

    def is_playing(self) -> bool:
        try:
            return (not self._c_pause) and (not self._c_core_idle) and (self._c_time_pos is not None)
        except Exception:
            return False

    # ---- Time (all in milliseconds) ----
    def get_time_ms(self) -> int:
        try:
            return max(0, int((self._c_time_pos or 0) * 1000))
        except Exception:
            return 0

    def set_time_ms(self, ms: int):
        try:
            self._p.seek(ms / 1000.0, 'absolute+exact')
        except Exception:
            pass

    def get_length_ms(self) -> int:
        try:
            return max(0, int((self._c_duration or 0) * 1000))
        except Exception:
            return 0

    # ---- Time: compat shims (same unit â€” ms) ----
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
            w, h = self._c_width, self._c_height
            if w and h:
                return (w, h)
        except Exception:
            pass
        return (0, 0)

    def video_get_size(self, track=0) -> tuple:
        return self.get_video_size()

    def get_osd_size(self) -> tuple:
        """Return (osd_w, osd_h) from the observer cache — safe for per-tick use."""
        return (self._c_osd_width, self._c_osd_height)

    # ---- Media loading ----
    def load(self, path: str, opts: list = None):
        """Load and play a file/URL. opts is ignored (mpv handles format detection)."""
        self.set_media(path)

    def unload(self):
        """Stop and clear current media."""
        self.stop()

    def get_path(self) -> str:
        """Return the path/URL of the currently loaded file, or None."""
        try:
            return self._p.path
        except Exception:
            return None

    def set_media(self, path_or_none, start_seconds=None):
        """Load path/URL, optionally starting at a specific time, or stop."""
        if path_or_none is None:
            self.unload()
        else:
            try:
                # Optimistic cache reset: the previous file's time/duration must
                # not leak into is_playing()/get_time() during the load window
                # (matches the direct-read behavior, where both were None here).
                self._c_time_pos = None
                self._c_duration = None
                if start_seconds is not None and start_seconds > 0:
                    self._p.command(
                        'loadfile', str(path_or_none), 'replace', '-1',
                        f'start={start_seconds}'
                    )
                else:
                    self._p.play(str(path_or_none))
            except Exception:
                # A failed load means silence on stage — make sure it's traceable.
                log_exception("mpv failed to load media: %s", path_or_none)

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
