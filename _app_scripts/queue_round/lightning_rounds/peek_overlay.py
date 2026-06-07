"""Peek lightning-round renderer — the two-panel ASS overlay that reveals
the video by sliding apart in a chosen direction.

Extracted from `guess_the_anime.py`. Only the renderer (`toggle_peek_overlay`)
and its directly-owned sentinels (`peek_overlay1`, `peek_overlay2`, `peeking`)
plus the panel ASS OSD ID live here. The reveal-mode dispatch
(`_activate_peek_variant`, `narrow_peek`/`widen_peek`, `toggle_filter_vf`,
peek round toggles, queued variants) remains in main for now — they touch
edge / grow / filter state that hasn't been extracted yet.

Sentinels are rebound externally readable: main reads them via
``peek_overlay.peek_overlay1``. ``gap_modifier`` lives in the sibling
``peek_dispatch`` module (read/reset via lazy sibling import to avoid a
top-level import cycle).
"""
from __future__ import annotations

import _app_scripts.playback.osd_text as osd_text


# ---------------------------------------------------------------------------
# Module state — `peek_overlay1`/`peek_overlay2` are read externally by main
# (truthiness sentinels). `peeking` is internal-only legacy state.
# ---------------------------------------------------------------------------
peek_overlay1     = None  # sentinel — True while peek panels are active
peek_overlay2     = None  # sentinel — second panel, kept symmetric with overlay1
peeking           = False
_PEEK_ASS_OSD_ID  = 50    # unique ID for osd-overlay (ASS-based) peek panels


def toggle_peek_overlay(destroy=False, direction="right", progress=0, gap=1):
    """Toggles two black panels that reveal the video in a chosen direction by percentage.
    Uses mpv's osd-overlay with ass-events type.  The text argument passed to mpv contains
    only the ASS text-field payload (starting with '{'), NOT the full 'Dialogue: ...' header
    line.  mpv wraps each line in a Dialogue event internally, so the payload is all that is
    needed — and because the payload starts with '{', nothing shows as visible OSD text even
    if mpv echoes the text argument through its status-message layer.

    Args:
        destroy (bool): Whether to remove the overlays.
        direction (str): 'left', 'right', 'up', or 'down'.
        progress (int): How much to reveal, from 0 (fully covered) to 100 (fully uncovered).
        gap (int): The gap between the two panels as a percentage of the video width/height.
    """
    global peek_overlay1, peek_overlay2, peeking

    if destroy:
        try:
            osd_text.osd_command('osd-overlay', _PEEK_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        from . import peek_dispatch
        peek_dispatch.gap_modifier = 0
        peeking = False
        peek_overlay1 = None
        peek_overlay2 = None
        return

    if not 0 <= progress <= 100:
        return

    if peek_overlay1 is None:
        peek_overlay1 = True  # sentinel — not a Tkinter window
    if peek_overlay2 is None:
        peek_overlay2 = True

    import _app_scripts.information.information_popup as information_popup
    osd_w, osd_h, vid_x, vid_y, vid_w, vid_h = information_popup._get_effective_video_rect()
    if not osd_w or not vid_w:
        return

    from . import peek_dispatch
    gap_pixels = int(((gap + peek_dispatch.gap_modifier) / 100) * vid_w)

    # Compute the two panel rectangles in OSD pixel space
    if direction == "left":
        p1_x, p1_y = vid_x, vid_y
        p1_w = int(vid_w * (1 - progress / 100))
        p1_h = vid_h
        p2_x = vid_x + int(vid_w * (1 - progress / 100)) + gap_pixels
        p2_y = vid_y
        p2_w = vid_w - int(vid_w * (1 - progress / 100)) - gap_pixels
        p2_h = vid_h

    elif direction == "right":
        p1_x = vid_x + int(vid_w * progress / 100) + gap_pixels
        p1_y = vid_y
        p1_w = vid_w - int(vid_w * progress / 100) - gap_pixels
        p1_h = vid_h
        p2_x, p2_y = vid_x, vid_y
        p2_w = int(vid_w * progress / 100)
        p2_h = vid_h

    elif direction == "up":
        p1_x, p1_y = vid_x, vid_y
        p1_w = vid_w
        p1_h = int(vid_h * (1 - progress / 100))
        p2_x = vid_x
        p2_y = vid_y + int(vid_h * (1 - progress / 100)) + gap_pixels
        p2_w = vid_w
        p2_h = vid_h - int(vid_h * (1 - progress / 100)) - gap_pixels

    elif direction == "down":
        p1_x = vid_x
        p1_y = vid_y + int(vid_h * progress / 100) + gap_pixels
        p1_w = vid_w
        p1_h = vid_h - int(vid_h * progress / 100) - gap_pixels
        p2_x, p2_y = vid_x, vid_y
        p2_w = vid_w
        p2_h = int(vid_h * progress / 100)

    else:
        return

    # Build ASS drawing paths for filled black rectangles.
    # \an7\pos(0,0) puts the origin at OSD top-left so m/l coords = OSD pixels.
    # \p1 = drawing scale 1 (1 unit = 1 OSD pixel with res set to osd size).
    # The payload starts with '{' so even if mpv echoes the text arg as a status
    # message it will be entirely inside tags — nothing is visible.
    shapes = []
    if p1_w > 0 and p1_h > 0:
        x1, y1, x2, y2 = int(p1_x), int(p1_y), int(p1_x + p1_w), int(p1_y + p1_h)
        shapes.append(f"m {x1} {y1} l {x2} {y1} {x2} {y2} {x1} {y2}")
    if p2_w > 0 and p2_h > 0:
        x1, y1, x2, y2 = int(p2_x), int(p2_y), int(p2_x + p2_w), int(p2_y + p2_h)
        shapes.append(f"m {x1} {y1} l {x2} {y1} {x2} {y2} {x1} {y2}")

    if not shapes:
        try:
            osd_text.osd_command('osd-overlay', _PEEK_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        return

    # Pass only the ASS text-field payload — no 'Dialogue:' header prefix.
    ass_payload = (
        "{\\an7\\pos(0,0)\\1c&H000000&\\bord0\\shad0\\p1}"
        + " ".join(shapes)
        + "{\\p0}"
    )

    try:
        osd_text.osd_command('osd-overlay', _PEEK_ASS_OSD_ID, 'ass-events',
                     ass_payload, osd_w, osd_h, 0, 'no')
    except Exception as e:
        print(f"Peek OSD (ASS) error: {e}")
