"""Unified media-player abstraction over the mpv backend.

All time values are in milliseconds (consistent with the rest of the app).
Volume uses the 0-200 scale that the app has always used (mpv 0-100 is doubled).

The class is constructed once in main with a configured mpv.MPV instance; main
owns the property observers and event callbacks, and the player instance lives
on state.widgets.player.
"""

from core.app_logging import log_exception


_STARTUP_COVER_FILTER_LABEL = "@gta-startup-cover"
_STARTUP_COVER_FILTER = (
    f"{_STARTUP_COVER_FILTER_LABEL}:"
    "lavfi=[drawbox=color=black:t=fill]"
)


class MediaPlayer:
    """
    Unified media-player abstraction - Phase 2: mpv backend.

    All time values are in milliseconds (consistent with the rest of the app).
    Volume uses the 0-200 scale that the app has always used (mpv 0-100 is doubled).
    """

    def __init__(self, mpv_player):
        self._p = mpv_player          # underlying mpv.MPV instance
        # A lightning/reveal load can ask mpv to replace every incoming frame
        # with a solid fill. Unlike an OSD overlay, this happens in the video
        # pipeline and therefore cannot disappear during mpv's per-file OSD
        # reset. The normal blind-screen uncover removes it once the real
        # round cover is ready.
        self._startup_video_cover_active = False
        self._startup_video_cover_brightness = 0.0
        self._startup_video_cover_contrast = 0.0
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
        self._c_disp_width = None
        self._c_disp_height = None
        self._c_osd_width = 0
        self._c_osd_height = 0
        try:
            self._p.observe_property('time-pos', self._on_time_pos)
            self._p.observe_property('duration', self._on_duration)
            self._p.observe_property('pause', self._on_pause)
            self._p.observe_property('core-idle', self._on_core_idle)
            self._p.observe_property('width', self._on_width)
            self._p.observe_property('height', self._on_height)
            self._p.observe_property('video-params', self._on_video_params)
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

    def invalidate_video_geometry(self):
        """Forget the cached size of the file that is being replaced.

        mpv keeps serving the outgoing file's `width`/`video-params` until the
        incoming one has been decoded, so anything laid out during the load
        window (the reveal cover is drawn *before* the load so no frame can
        leak) would otherwise be sized for the file that just ended — a 4:3
        video covered by a 16:9 cover never shows its left/right edges.
        Until the observers refresh, `get_display_aspect()` reports 0.0, which
        `letterbox_rect` treats as "unknown" and expands to the full canvas:
        over-covering is safe, under-covering leaks frames.
        """
        self._c_width = self._c_height = None
        self._c_disp_width = self._c_disp_height = None

    def refresh_video_geometry(self):
        """Direct-read the current file's size into the cache; return True if known.

        Called once per file from the playback-restart hook. The observers
        normally fill this in first, but mpv only emits `video-params` when the
        value *changes*, so a file whose size matches the previous one could
        leave the cache empty after `invalidate_video_geometry()`.
        """
        if self._c_disp_width and self._c_disp_height:
            return True
        try:
            params = self._p.video_params or {}
            self._c_disp_width  = int(params['dw']) or None
            self._c_disp_height = int(params['dh']) or None
        except Exception:
            pass
        if not (self._c_disp_width and self._c_disp_height):
            try:
                self._c_width  = self._p.width or None
                self._c_height = self._p.height or None
            except Exception:
                pass
        return bool(self.get_display_size()[0])

    def _on_video_params(self, _name, value):
        """Cache the decoder's aspect-corrected display size (video-params/dw+dh).

        `video-params` is the decoder's output *before* the vf chain, so the
        filter-peek/zoom filters never perturb it. dw/dh already have the
        container's pixel aspect ratio applied — the only reliable way to tell
        an anamorphic 720x480 DVD rip (16:9) from a 4:3 one, since both report
        width=720, height=480.
        """
        try:
            self._c_disp_width  = int(value['dw']) or None
            self._c_disp_height = int(value['dh']) or None
        except Exception:
            self._c_disp_width = self._c_disp_height = None

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

    def get_display_size(self) -> tuple:
        """Return (w, h) of the video as mpv *displays* it — the stored size with
        the container's pixel aspect ratio applied. Use this, never the stored
        size, for on-screen geometry (censor boxes, overlays, letterbox rects).
        Falls back to the stored size until mpv reports video-params; served
        from the observer cache, so it is safe on the seek-tick hot path."""
        w, h = self._c_disp_width, self._c_disp_height
        if w and h:
            return (int(w), int(h))
        return self.get_video_size()

    def get_display_aspect(self) -> float:
        """Display aspect ratio (w / h) of the current video, or 0.0 if unknown."""
        w, h = self.get_display_size()
        return (w / h) if (w and h) else 0.0

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

    def release_startup_video_cover(self):
        """Restore video output after the persistent startup cover is safe."""
        if not getattr(self, "_startup_video_cover_active", False):
            return
        try:
            self._p.command(
                "vf", "remove", _STARTUP_COVER_FILTER_LABEL
            )
        except Exception:
            pass
        brightness = getattr(self, "_startup_video_cover_brightness", 0.0)
        contrast = getattr(self, "_startup_video_cover_contrast", 0.0)
        try:
            self._p.brightness = brightness
            self._p.contrast = contrast
        except Exception:
            try:
                self._p.command("set", "brightness", str(brightness))
                self._p.command("set", "contrast", str(contrast))
            except Exception:
                pass
        self._startup_video_cover_active = False

    def set_media(self, path_or_none, start_seconds=None, cover_video=False):
        """Load media, optionally starting covered or at a specific time."""
        if path_or_none is None:
            self.release_startup_video_cover()
            self.unload()
        else:
            try:
                # Optimistic cache reset: the previous file's time/duration must
                # not leak into is_playing()/get_time() during the load window
                # (matches the direct-read behavior, where both were None here).
                self._c_time_pos = None
                self._c_duration = None
                # The incoming file's geometry is not known yet; mpv would keep
                # reporting the outgoing file's until it has been decoded.
                self.invalidate_video_geometry()
                options = []
                if cover_video:
                    if not getattr(self, "_startup_video_cover_active", False):
                        try:
                            self._startup_video_cover_brightness = float(
                                self._p.brightness or 0.0
                            )
                        except Exception:
                            self._startup_video_cover_brightness = 0.0
                        try:
                            self._startup_video_cover_contrast = float(
                                self._p.contrast or 0.0
                            )
                        except Exception:
                            self._startup_video_cover_contrast = 0.0
                    self._startup_video_cover_active = True
                    # The labeled drawbox replaces the decoded image with a
                    # solid frame before presentation. Contrast/brightness are
                    # a hardware-output fallback if lavfi cannot initialize.
                    options.append("brightness=-100")
                    options.append("contrast=-100")
                    options.append(f"vf={_STARTUP_COVER_FILTER}")
                else:
                    self.release_startup_video_cover()

                if isinstance(path_or_none, (tuple, list)) and len(path_or_none) == 2:
                    video_url, audio_url = path_or_none
                    options.insert(0, f'audio-file={audio_url}')
                    if start_seconds is not None and start_seconds > 0:
                        options.append(f'start={start_seconds}')
                    self._p.command(
                        'loadfile', str(video_url), 'replace', '-1', ','.join(options)
                    )
                elif start_seconds is not None and start_seconds > 0:
                    options.insert(0, f'start={start_seconds}')
                    self._p.command(
                        'loadfile', str(path_or_none), 'replace', '-1',
                        ','.join(options)
                    )
                elif options:
                    self._p.command(
                        'loadfile', str(path_or_none), 'replace', '-1',
                        ','.join(options)
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
