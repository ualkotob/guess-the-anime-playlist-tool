"""Edge lightning-round renderer — a solid center box that covers the
video interior, leaving only the edges visible. The covered area shrinks
over the round.

Extracted from `guess_the_anime.py`. Uses mpv's `osd-overlay` with
ass-events (GPU-rendered vector rect), matching peek_overlay and grow_overlay
so that floating text (z=3) correctly renders on top.

``edge_overlay_box`` is the rebound sentinel — main reads it via
``edge_overlay.edge_overlay_box``.
"""
from __future__ import annotations

from core.game_state import state
import _app_scripts.playback.osd_text as osd_text


# ---------------------------------------------------------------------------
# Module state — `edge_overlay_box` is read externally as a truthiness sentinel.
# ---------------------------------------------------------------------------
edge_overlay_box        = None  # sentinel — True while edge overlay is active
edge_overlay_after_id   = None  # pending root.after id for deferred OSD setup
last_edge_block_percent = 100   # last block_percent (for retry after OSD ready)

_EDGE_ASS_OSD_ID = 55  # unique ID for osd-overlay (ASS-based) edge panel


def _draw_edge_osd(block_percent):
    """Draw a solid center box covering the video interior using ASS vectors."""
    try:
        import _app_scripts.information.information_popup as information_popup
        osd_w, osd_h, vid_x, vid_y, vid_w, vid_h = information_popup._get_effective_video_rect()
        if not osd_w or not vid_w:
            return
        visible_pct = 100 - block_percent
        margin = int(min(vid_w, vid_h) * (visible_pct / 100.0 / 2.0))
        box_w = max(0, vid_w - margin * 2)
        box_h = max(0, vid_h - margin * 2)
        if not box_w or not box_h:
            osd_text.osd_command('osd-overlay', _EDGE_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
            return
        bx = vid_x + margin
        by = vid_y + margin
        bx2 = bx + box_w
        by2 = by + box_h
        ass_payload = (
            "{\\an7\\pos(0,0)\\1c&H000000&\\bord0\\shad0\\p1}"
            f"m {bx} {by} l {bx2} {by} {bx2} {by2} {bx} {by2}"
            "{\\p0}"
        )
        osd_text.osd_command('osd-overlay', _EDGE_ASS_OSD_ID, 'ass-events',
                     ass_payload, osd_w, osd_h, 0, 'no')
    except Exception as e:
        print(f"Edge OSD (ASS) error: {e}")


def toggle_edge_overlay(block_percent=100, destroy=False):
    global edge_overlay_box, edge_overlay_after_id, last_edge_block_percent
    last_edge_block_percent = block_percent

    root = state.widgets.root

    if destroy:
        if edge_overlay_after_id:
            try:
                root.after_cancel(edge_overlay_after_id)
            except Exception:
                pass
            edge_overlay_after_id = None
        try:
            osd_text.osd_command('osd-overlay', _EDGE_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        edge_overlay_box = None
        return

    block_percent = max(0, min(100, block_percent))

    import _app_scripts.information.information_popup as information_popup
    osd_w, osd_h, vid_x, vid_y, vid_w, vid_h = information_popup._get_effective_video_rect()
    if not osd_w or not vid_w:
        if edge_overlay_after_id:
            try:
                root.after_cancel(edge_overlay_after_id)
            except Exception:
                pass
        edge_overlay_after_id = root.after(250, lambda: toggle_edge_overlay(block_percent=last_edge_block_percent))
        return

    if edge_overlay_after_id:
        try:
            root.after_cancel(edge_overlay_after_id)
        except Exception:
            pass
        edge_overlay_after_id = None

    edge_overlay_box = True  # sentinel so external truthiness checks work
    _draw_edge_osd(block_percent)
