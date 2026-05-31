"""Grow lightning-round renderer — four ASS panels surrounding a visible
hole, which grows over the round as `block_percent` decreases.

Extracted from `guess_the_anime.py`. Uses mpv's `osd-overlay` with
ass-events (no pixel data uploaded; GPU-rendered). The hole can be
positioned via `set_grow_position` (random) or `move_grow_position`
(keyboard nudge), and main's `smooth_move_grow_overlay` mouse-drag also
writes ``grow_overlay.grow_position`` directly.

``grow_overlay_boxes`` and ``grow_position`` are rebound sentinels —
main reads them via the qualified module attribute.
"""
from __future__ import annotations

import random
import time as _time_mod

from core.game_state import state


# ---------------------------------------------------------------------------
# Module state — read externally by main (truthiness/position sentinels).
# ---------------------------------------------------------------------------
grow_overlay_boxes      = {}     # sentinel — {"active": True} while active
grow_position           = None   # (cx, cy) in OSD coords; also written by main's drag loop
last_grow_block_percent = 100    # last block_percent (read by main's drag loop)
_grow_osd_last_ms       = 0.0    # wall time of last ASS push; throttle to ~60fps
_GROW_ASS_OSD_ID        = 51     # unique ID for osd-overlay (ASS-based) grow panel


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
_osd_command = None
_get_effective_video_rect = None


def set_context(*, osd_command, get_effective_video_rect):
    g = globals()
    g['_osd_command'] = osd_command
    g['_get_effective_video_rect'] = get_effective_video_rect


def set_grow_position():
    """Pick a random hole center inside a 0.3 margin of the OSD."""
    global grow_position
    player = state.widgets.player
    root = state.widgets.root
    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        osd_w, osd_h = root.winfo_screenwidth(), root.winfo_screenheight()
    if not osd_w:
        osd_w, osd_h = root.winfo_screenwidth(), root.winfo_screenheight()
    margin = int(min(osd_w, osd_h) * 0.3)
    cx = random.randint(margin, osd_w - margin)
    cy = random.randint(margin, osd_h - margin)
    grow_position = (cx, cy)


def move_grow_position(dx, dy):
    """Move the grow overlay box by dx, dy pixels, constrained to the OSD canvas."""
    global grow_position
    if grow_position is None:
        return
    player = state.widgets.player
    root = state.widgets.root
    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        osd_w, osd_h = root.winfo_screenwidth(), root.winfo_screenheight()
    if not osd_w:
        osd_w, osd_h = root.winfo_screenwidth(), root.winfo_screenheight()
    cx, cy = grow_position
    cx = min(max(cx + dx, 0), osd_w)
    cy = min(max(cy + dy, 0), osd_h)
    grow_position = (cx, cy)
    toggle_grow_overlay(block_percent=last_grow_block_percent, position=(cx, cy))


def _draw_grow_osd(block_percent, cx_osd, cy_osd):
    """Draw four ASS panels surrounding a visible hole centered at (cx_osd, cy_osd).
    Uses mpv osd-overlay (ass-events) — no pixel data uploaded, GPU-rendered.
    The payload starts with '{' so mpv's text-echo produces nothing visible.
    """
    global _grow_osd_last_ms
    now = _time_mod.monotonic()
    if (now - _grow_osd_last_ms) < 0.016:  # ~60fps cap
        return
    try:
        osd_w, osd_h, fv_x, fv_y, fv_w, fv_h = _get_effective_video_rect()
        if not osd_w:
            return
        visible_w = int(fv_w * (1.0 - block_percent / 100.0))
        visible_h = int(fv_h * (1.0 - block_percent / 100.0))
        hole_l = max(fv_x, cx_osd - visible_w // 2)
        hole_t = max(fv_y, cy_osd - visible_h // 2)
        hole_r = min(fv_x + fv_w, cx_osd + visible_w // 2)
        hole_b = min(fv_y + fv_h, cy_osd + visible_h // 2)

        # Build the four surrounding panels as ASS vector paths.
        # All paths share one \p1 drawing block; multiple 'm' subpaths = multiple filled regions.
        # When framed video is active, panels are clipped to the framed rect (not the full OSD).
        out_l, out_t, out_r, out_b = fv_x, fv_y, fv_x + fv_w, fv_y + fv_h
        paths = []
        if hole_t > out_t:                    # top strip (inside framed rect)
            paths.append(f"m {out_l} {out_t} l {out_r} {out_t} {out_r} {hole_t} {out_l} {hole_t}")
        if hole_b < out_b:                    # bottom strip
            paths.append(f"m {out_l} {hole_b} l {out_r} {hole_b} {out_r} {out_b} {out_l} {out_b}")
        if hole_l > out_l:                    # left strip (between top/bottom strips)
            paths.append(f"m {out_l} {hole_t} l {hole_l} {hole_t} {hole_l} {hole_b} {out_l} {hole_b}")
        if hole_r < out_r:                    # right strip
            paths.append(f"m {hole_r} {hole_t} l {out_r} {hole_t} {out_r} {hole_b} {hole_r} {hole_b}")

        if not paths:
            # Fully uncovered — nothing to draw
            _osd_command('osd-overlay', _GROW_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
            return

        ass_payload = (
            "{\\an7\\pos(0,0)\\1c&H000000&\\bord0\\shad0\\p1}"
            + " ".join(paths)
            + "{\\p0}"
        )
        _osd_command('osd-overlay', _GROW_ASS_OSD_ID, 'ass-events',
                     ass_payload, osd_w, osd_h, 0, 'no')
        _grow_osd_last_ms = now
    except Exception as e:
        print(f"Grow OSD (ASS) error: {e}")


def toggle_grow_overlay(block_percent=100, position="center", destroy=False):
    global grow_overlay_boxes, last_grow_block_percent, grow_position

    player = state.widgets.player
    root = state.widgets.root

    if destroy:
        try:
            _osd_command('osd-overlay', _GROW_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        grow_overlay_boxes.clear()
        # Stop any in-progress smooth animation (shortcut_dispatch owns the drag loop state).
        # Lazy import — shortcut_dispatch imports this module at top-level.
        from _app_scripts.toggles import shortcut_dispatch
        shortcut_dispatch.mouse_dragging_grow_overlay = False
        anim_id = shortcut_dispatch.animation_after_id
        if anim_id:
            try:
                root.after_cancel(anim_id)
            except Exception:
                pass
            shortcut_dispatch.animation_after_id = None
        return

    last_grow_block_percent = block_percent
    block_percent = max(0, min(100, block_percent))

    # Determine center position in OSD coordinates
    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        osd_w, osd_h = 0, 0
    if not osd_w:
        return

    if isinstance(position, tuple):
        cx, cy = position
        grow_position = (cx, cy)
    else:
        from _app_scripts.playback import blind_screen
        if blind_screen._video_frame_active:
            _, _, fv_x, fv_y, fv_w, fv_h = _get_effective_video_rect()
            cx, cy = fv_x + fv_w // 2, fv_y + fv_h // 2
        else:
            cx, cy = osd_w // 2, osd_h // 2
        grow_position = (cx, cy)

    _draw_grow_osd(block_percent, cx, cy)
    grow_overlay_boxes = {"active": True}  # sentinel so external truthiness checks work
