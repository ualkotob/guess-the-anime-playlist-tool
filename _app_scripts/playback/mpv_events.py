"""mpv player event/observer wiring.

Holds the mpv property observers + window-click subclassing:
  * idle-active → debounced auto-stop when mpv goes idle without a Python stop()
  * fullscreen → sync autoplay_fullscreen on user-driven fullscreen toggles
  * osd-width → re-render the coming-up overlay on OSD resize
  * playback-restart → reapply blind/peek/reveal overlays once OSD dims are valid
  * eof-reached → route natural playback end to _handle_video_end
  * window-id → subclass the mpv HWND wndproc to turn clicks into play/pause

Main calls register_observers(player) once and schedules _poll_mpv_clicks.
"""
import queue

from core.game_state import state
from _app_scripts.playback import coming_up_ui, blind_screen, transport
from _app_scripts.queue_round.lightning_rounds import (
    filter_overlay, edge_overlay, peek_overlay, grow_overlay,
)

# --- module-owned state ---
_idle_stop_after_id = None
_mpv_wndproc_refs = {}     # hwnd → (new_proc, original_proc); keeps ctypes objects alive
_mpv_click_queue = queue.Queue()   # thread-safe click signals from mpv wndproc → main thread
_playpause_pending = [None]        # root.after ID for deferred play_pause (double-click guard)


def _on_player_idle(name, is_idle):
    # When mpv goes idle without Python having called stop() (e.g. user closes the
    # window via CLOSE_WIN → mpv stop), schedule our Python stop() on the main thread.
    # Debounced: ignore transient idle-active=True flips that occur during seeks.
    global _idle_stop_after_id
    if is_idle and state.playback.currently_playing:
        # Snapshot currently_playing now (on mpv thread) so the 200ms callback
        # isn't fooled by later state changes.
        _cp_snapshot = state.playback.currently_playing
        def _do_idle_stop(snapshot=_cp_snapshot):
            global _idle_stop_after_id
            _idle_stop_after_id = None
            # Only call stop() if currently_playing hasn't changed since we fired
            # (i.e. stop() wasn't already called by something else).
            if state.playback.currently_playing is snapshot and snapshot:
                try:
                    transport.stop()
                except Exception:
                    pass
        try:
            root = state.widgets.root
            if root:
                _idle_stop_after_id = root.after(200, _do_idle_stop)
        except Exception:
            pass
    elif not is_idle:
        # idle-active went False (seek completed / playback resumed) — cancel pending stop
        try:
            root = state.widgets.root
            if root and _idle_stop_after_id is not None:
                root.after_cancel(_idle_stop_after_id)
                _idle_stop_after_id = None
        except Exception:
            pass


def _on_fullscreen_change(name, is_fs):
    # Sync autoplay_fullscreen when the user toggles fullscreen in mpv while a video
    # is actively playing (double-click, TAB, etc.). Do NOT sync during startup or
    # shutdown — mpv exits fullscreen on close which would poison the saved preference.
    # Use time_pos instead of is_playing() so a momentary pause (e.g. from the click
    # handler firing on the first half of a double-click) doesn't block the sync.
    try:
        root = state.widgets.root
        p = state.widgets.player
        if root and p and p._p.time_pos is not None:
            def _sync_mpv_fullscreen():
                state.controls.autoplay_fullscreen = bool(is_fs)
            root.after(0, _sync_mpv_fullscreen)
    except Exception:
        pass


def _on_osd_width_change(name, new_w):
    """Re-render the coming-up PIL image overlay when the OSD is resized."""
    try:
        if not coming_up_ui._coming_up_osd_visible:
            return
        frame = coming_up_ui._coming_up_current_frame
        if not frame:
            return
        title_text, details, pil_image = frame
        player = state.widgets.player
        osd_w, osd_h = int(player._p.osd_width or 0), int(player._p.osd_height or 0)
        if not osd_w or not osd_h:
            return
        target_y = max(4, round(osd_h * 0.014))
        _root = state.widgets.root
        if _root:
            _root.after(0, lambda: coming_up_ui._render_coming_up_frame(
                title_text, details, pil_image, target_y, osd_w, osd_h, 1.0))
    except Exception:
        pass


def _on_playback_restart(_):
    """Fired once per file load when the first frame is ready and OSD dims are valid.
    Reapplies blind/reveal overlays that may have been lost during the mpv OSD reset."""
    try:
        _root = state.widgets.root
        if not _root:
            return
        def _reapply():
            _bo = blind_screen.black_overlay
            _cache = blind_screen._blind_osd_color_cache or 'black'
            # Reapply blind OSD (covers blind rounds AND the pre-load cover for reveal rounds)
            if _bo:
                blind_screen._set_blind_osd_alpha(_cache, 255)
            # For non-lightning reveal rounds: reapply active peek overlay then lift blind
            if not state.lightning.light_mode and not state.lightning.light_round_started:
                _fvf = filter_overlay.filter_vf_active
                _fvf_var = filter_overlay._filter_vf_variant
                _eo = edge_overlay.edge_overlay_box
                _po = peek_overlay.peek_overlay1
                _go = grow_overlay.grow_overlay_boxes
                # Reapply ASS-based overlays (osd dims are now valid)
                if _fvf and _fvf_var:
                    filter_overlay.toggle_filter_vf(_fvf_var, filter_overlay._filter_vf_last_progress[0])
                if _eo:
                    edge_overlay.toggle_edge_overlay(block_percent=99)
                if _po:
                    peek_overlay.toggle_peek_overlay()
                # If any peek overlay is active and we put up a pre-load black screen, lift it
                if _bo and (_fvf or _eo or _po or _go):
                    _root.after(50, lambda: blind_screen.set_black_screen(False))
        _root.after(0, _reapply)
    except Exception:
        pass


def _on_eof_reached(name, value):
    """Observed property: fires when eof-reached changes.
    Only True on natural playback end (keep_open=yes pauses at last frame).
    Does NOT fire for stop(), player.stop(), or window close."""
    try:
        if not value:
            return
        _root = state.widgets.root
        if _root:
            _root.after(0, transport._handle_video_end)
    except Exception:
        pass


def _setup_mpv_click_handler(hwnd):
    # Click inside the mpv window → play/pause (Windows API window subclassing).
    # player._p.window_id gives the HWND once mpv creates its window.
    # We subclass the window proc to intercept WM_LBUTTONDOWN/WM_LBUTTONUP.
    # Time-based detection: clicks < 300 ms; drags take longer.
    import ctypes, ctypes.wintypes, time as _time
    if not hwnd or hwnd in _mpv_wndproc_refs:
        return
    GWL_WNDPROC = -4
    WM_LBUTTONDOWN   = 0x0201
    WM_LBUTTONUP     = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    _press_time       = [None]
    _last_down_time   = [0.0]
    _is_double_press  = [False]
    # System double-click interval (ms → s); used to detect the second press
    # when the window class does NOT have CS_DBLCLKS (no WM_LBUTTONDBLCLK).
    _DBLCLK_S = ctypes.windll.user32.GetDoubleClickTime() / 1000.0
    # Must set restype to c_ssize_t; default c_int truncates 64-bit pointers.
    _GetWindowLongPtrW = ctypes.windll.user32.GetWindowLongPtrW
    _GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _SetWindowLongPtrW = ctypes.windll.user32.SetWindowLongPtrW
    _SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _CallWindowProcW = ctypes.windll.user32.CallWindowProcW
    _CallWindowProcW.restype = ctypes.c_ssize_t
    _CallWindowProcW.argtypes = [
        ctypes.c_ssize_t, ctypes.wintypes.HWND, ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
    ]
    original = _GetWindowLongPtrW(hwnd, GWL_WNDPROC)
    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.wintypes.HWND, ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
    )
    def _wndproc(h, msg, wp, lp):
        if msg == WM_LBUTTONDOWN:
            now = _time.monotonic()
            _is_double_press[0] = (now - _last_down_time[0]) < _DBLCLK_S
            _last_down_time[0] = now
            _press_time[0] = now
        elif msg == WM_LBUTTONUP:
            pt = _press_time[0]
            _press_time[0] = None
            if pt is not None and _time.monotonic() - pt < 0.3:
                if _is_double_press[0]:
                    # Second UP of double-click (no-CS_DBLCLKS case) — cancel first.
                    _mpv_click_queue.put_nowait(None)
                else:
                    # Normal single click — queue it for deferred processing.
                    # Do NOT call root.after() here: this callback runs on mpv's
                    # window thread and touching the Tcl/Tk lock deadlocks when
                    # the main thread holds it.
                    _mpv_click_queue.put_nowait(True)
        elif msg == WM_LBUTTONDBLCLK:
            # CS_DBLCLKS IS set: replaces the second WM_LBUTTONDOWN.
            # Cancel the first click and reset state so the following LBUTTONUP
            # and the next single-click are not misidentified as doubles.
            _mpv_click_queue.put_nowait(None)
            _press_time[0] = None    # suppress the upcoming LBUTTONUP
            _last_down_time[0] = 0.0  # prevent next click being flagged as double
        return _CallWindowProcW(original, h, msg, wp, lp)
    new_proc = WNDPROC(_wndproc)
    _SetWindowLongPtrW(hwnd, GWL_WNDPROC, new_proc)
    _mpv_wndproc_refs[hwnd] = (new_proc, original)


def _on_mpv_window_id(name, value):
    try:
        hwnd = int(value or 0)
        if hwnd:
            # Call directly — SetWindowLongPtrW is thread-safe and
            # _setup_mpv_click_handler no longer touches Tcl/Tk.
            # Also works before root exists (at startup).
            _setup_mpv_click_handler(hwnd)
    except Exception:
        pass


def _poll_mpv_clicks():
    """Main-thread poller that drains _mpv_click_queue and calls play_pause().

    The mpv wndproc callback runs on mpv's window thread and cannot safely call
    root.after() (which acquires the Tcl/Tk interpreter lock).  Instead it puts
    a sentinel on _mpv_click_queue; this function polls that queue every 50 ms
    from the main thread where Tk calls are safe.
    """
    root = state.widgets.root
    try:
        while not _mpv_click_queue.empty():
            item = _mpv_click_queue.get_nowait()
            if item is True:
                # Defer play_pause by 200 ms.  This gives the cancel sentinel from
                # the second click of a double-click time to arrive and abort the
                # timer before it fires, without any perceptible lag on single clicks.
                if _playpause_pending[0] is None:
                    def _fire(_pending=_playpause_pending):
                        _pending[0] = None
                        if not (grow_overlay.grow_overlay_boxes or (
                                filter_overlay.filter_vf_active and
                                filter_overlay._filter_vf_variant == 'zoom')):
                            transport.play_pause()
                    _playpause_pending[0] = root.after(200, _fire)
            elif item is None:
                # Cancel any pending deferred play_pause.
                if _playpause_pending[0] is not None:
                    root.after_cancel(_playpause_pending[0])
                    _playpause_pending[0] = None
    except Exception:
        pass
    root.after(50, _poll_mpv_clicks)


def register_observers(player):
    """Wire all mpv property observers + the window-click handler onto `player`.

    Called once by main right after the MediaPlayer is constructed."""
    player._p.observe_property('idle-active', _on_player_idle)
    player._p.observe_property('fullscreen', _on_fullscreen_change)
    player._p.observe_property('osd-width', _on_osd_width_change)
    player._p.event_callback('playback-restart')(_on_playback_restart)
    player._p.observe_property('eof-reached', _on_eof_reached)
    player._p.observe_property('window-id', _on_mpv_window_id)
