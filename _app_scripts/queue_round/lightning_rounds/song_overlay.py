"""Song lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders the SONG TITLE / theme slug /
SONG ARTIST boxes stacked vertically on top of the mpv video, with an
animated pulsing music-note emoji beside the theme box. Drawn via a PIL
image overlay; the animation loop runs on ``root.after``.

``song_overlay_boxes`` is a sentinel dict that's rebound between ``{}``
and ``{"active": True}`` on toggle. Main's external reader (in
``update_light_round``) reads through ``song_overlay.song_overlay_boxes``
so it always sees the module-current value rather than a stale alias.
The other module state (`_song_img_overlay`, `_song_anim_after`,
`_song_base_cache`, `_song_note_color`, `_song_note_px_cache`,
`_song_last_flags`) has no external readers — kept private.
"""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from core.game_state import state


# ---------------------------------------------------------------------------
# Module-private state
# ---------------------------------------------------------------------------
song_overlay_boxes = {}   # truthy {"active":True} while active — game-loop guard relies on it
_song_img_overlay = None
_song_anim_after = None
_song_base_cache = [None, None, 0, 0]   # [state_key, PIL Image, note_x, note_y]
_song_note_color = [None]
_song_note_px_cache = {}                # px → PIL font
_song_last_flags = {"show_title": True, "show_artist": True, "show_theme": True, "show_music": True}


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
currently_playing: dict = {}
_format_slug = None
_get_song_string = None
_get_ass_font = None
_wall_time = None
_get_overlay_background_color = lambda: 'black'
_get_overlay_text_color = lambda: 'white'


def set_context(*, currently_playing, format_slug, get_song_string,
                get_ass_font, wall_time,
                get_overlay_background_color, get_overlay_text_color):
    g = globals()
    g['currently_playing'] = currently_playing
    g['_format_slug'] = format_slug
    g['_get_song_string'] = get_song_string
    g['_get_ass_font'] = get_ass_font
    g['_wall_time'] = wall_time
    g['_get_overlay_background_color'] = get_overlay_background_color
    g['_get_overlay_text_color'] = get_overlay_text_color


def _draw_song_base(show_title, show_artist, show_theme, osd_w, osd_h):
    """Render the static song boxes (theme / title / artist) to a full OSD RGBA canvas."""
    root = state.widgets.root
    modifier = min(osd_w / 2560, osd_h / 1440)
    def fs(pt): return max(6, round(pt * modifier))

    try:
        r16, g16, b16 = root.winfo_rgb(_get_overlay_background_color())
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
        r16, g16, b16 = root.winfo_rgb(_get_overlay_text_color())
        fg_r, fg_g, fg_b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        bg_r, bg_g, bg_b = 0, 0, 0
        fg_r, fg_g, fg_b = 255, 255, 255

    bg   = (bg_r, bg_g, bg_b, 217)   # ~0.85 alpha
    fg   = (fg_r, fg_g, fg_b, 255)
    bdr_color = fg

    pad    = max(9, round(31 * modifier))
    border = max(1, round(4  * modifier))
    max_inner_w = round(osd_w * 0.72)
    cx = osd_w // 2

    data         = currently_playing.get("data", {})
    slug         = _format_slug(data.get("slug"))
    song_title   = _get_song_string(data, "title")
    artist_str   = _get_song_string(data, "artist_string")
    theme_label  = _format_slug(slug).upper()

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    def truncate_fit(text, font, max_w):
        """Shorten text with ellipsis until it fits within max_w pixels."""
        bb = draw.textbbox((0, 0), text, font=font)
        if bb[2] - bb[0] <= max_w:
            return text, bb
        t = text
        while len(t) > 1:
            t = t[:-1]
            candidate = t.rstrip() + "…"
            bb = draw.textbbox((0, 0), candidate, font=font)
            if bb[2] - bb[0] <= max_w:
                return candidate, bb
        return "…", draw.textbbox((0, 0), "…", font=font)

    def draw_box(header, body, y_top, hdr_fs_pt, body_fs_pt, body_fs_min_pt, measure_only=False):
        hdr_font = _get_ass_font(fs(hdr_fs_pt), bold=True)
        if not hdr_font:
            return
        # Header measurement
        hb = draw.textbbox((0, 0), header, font=hdr_font)
        hw = hb[2] - hb[0]
        hh = hb[3] - hb[1]
        # Body: reduce font until width fits, then truncate as last resort
        body_font = None
        bb = (0, 0, 0, 0)
        bw = bh = 0
        if body:
            bfs     = fs(body_fs_pt)
            bfs_min = fs(body_fs_min_pt)
            while bfs >= bfs_min:
                bf = _get_ass_font(bfs, bold=True)
                if bf:
                    b = draw.textbbox((0, 0), body, font=bf)
                    if b[2] - b[0] <= max_inner_w:
                        body_font = bf
                        bb = b
                        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
                        break
                bfs = max(bfs_min, bfs - 2)
            if body_font is None:
                body_font = _get_ass_font(bfs_min, bold=True)
                if body_font:
                    body, bb = truncate_fit(body, body_font, max_inner_w)
                    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
            else:
                # Even when it fitted, save adjusted bb for accurate positioning
                body, bb = truncate_fit(body, body_font, max_inner_w)
                bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        # Underline bar
        ul_gap = max(2, round(3  * modifier))
        ul_h   = max(2, round(5  * modifier))
        # Box geometry
        content_h = hh + ul_gap + ul_h + (pad + bh if body_font and body else 0)
        box_h     = content_h + pad * 2
        box_w     = min(max(hw, bw) + pad * 2 + border * 2, round(osd_w * 0.80))
        bx        = cx - box_w // 2
        by        = round(y_top)
        if measure_only:
            return bx, by, box_w, box_h
        # Background + border
        draw.rectangle([bx, by, bx + box_w, by + box_h], fill=bg)
        draw.rectangle([bx, by, bx + box_w, by + box_h], outline=bdr_color, width=border)
        # Header — compensate bbox offsets so visual top lands at by+pad
        hx = cx - hw // 2 - hb[0]
        hy = by + pad - hb[1]
        draw.text((hx, hy), header, font=hdr_font, fill=fg)
        # Underline: only under the text, not the full box width
        ul_y  = hy + hb[3] + ul_gap
        ul_x0 = hx + hb[0]
        ul_x1 = hx + hb[2]
        draw.rectangle([ul_x0, ul_y, ul_x1, ul_y + ul_h], fill=fg)
        # Body — compensate bbox[0]/[1] so text is visually centred inside the box
        if body_font and body:
            bx2 = cx - bw // 2 - bb[0]
            by2 = by + pad + hh + ul_gap + ul_h + pad - bb[1]
            draw.text((bx2, by2), body, font=body_font, fill=fg)
        return bx, by, box_w, box_h

    note_gap    = max(8, round(20 * modifier))
    box_gap     = max(6, round(18 * modifier))   # gap between stacked boxes
    theme_right = round(osd_w * 0.72)   # fallback if theme box not shown
    theme_cy    = round(osd_h * 0.32)   # fallback

    # Measure each visible box so we can calculate positions before drawing
    title_m  = draw_box("SONG TITLE",  song_title, 0, 72, 200, 24, measure_only=True) if show_title  else None
    theme_m  = draw_box(theme_label,   None,        0, 72, 72,  20, measure_only=True) if show_theme  else None
    # (artist box has no measurement dependency — drawn directly below)

    # Center song title vertically; stack theme above and artist below it
    title_h  = title_m[3]  if title_m  else 0
    theme_h  = theme_m[3]  if theme_m  else 0

    title_y  = (osd_h - title_h) // 2
    theme_y  = title_y - box_gap - theme_h
    artist_y = title_y + title_h + box_gap

    if show_theme:
        rect = draw_box(theme_label, None, theme_y, 72, 72, 20)
        if rect:
            theme_right = rect[0] + rect[2] + note_gap
            theme_cy    = rect[1] + rect[3] // 2
    if show_title:
        draw_box("SONG TITLE", song_title, title_y, 72, 200, 24)
    if show_artist:
        draw_box("SONG ARTIST", artist_str, artist_y, 72, 130, 24)

    return canvas, theme_right, theme_cy


def toggle_song_overlay(show_title=True, show_artist=True, show_theme=True, show_music=True, destroy=False, quick_destroy=False):
    """Toggles the Song Lightning Round overlay (mpv PIL image overlay)."""
    global song_overlay_boxes, _song_img_overlay, _song_anim_after

    player = state.widgets.player
    root = state.widgets.root

    if destroy or quick_destroy:
        if _song_anim_after is not None:
            try:
                root.after_cancel(_song_anim_after)
            except Exception:
                pass
            _song_anim_after = None
        if _song_img_overlay is not None:
            try:
                _song_img_overlay.remove()
            except Exception:
                pass
            _song_img_overlay = None
        song_overlay_boxes = {}
        _song_base_cache[0] = None
        _song_base_cache[1] = None
        _song_note_px_cache.clear()
        if destroy:
            return
        # quick_destroy: rebuild immediately with saved flags
        toggle_song_overlay(**_song_last_flags)
        return

    # Update flags — the running animation loop reads these each tick
    _song_last_flags.update(show_title=show_title, show_artist=show_artist,
                             show_theme=show_theme, show_music=show_music)

    # If the loop is already running, just let it pick up the new flags
    if _song_img_overlay is not None:
        return

    # First call: create overlay and start animation
    _song_img_overlay = player._p.create_image_overlay()
    song_overlay_boxes = {"active": True}
    _song_note_color[0] = (random.randint(100, 255),
                           random.randint(100, 255),
                           random.randint(100, 255), 255)
    _song_anim_start = [_wall_time()]

    def _song_step():
        global _song_img_overlay, _song_anim_after
        if _song_img_overlay is None:
            return
        flags = _song_last_flags
        st  = flags["show_title"]
        sa  = flags["show_artist"]
        sth = flags["show_theme"]
        sm  = flags["show_music"]
        try:
            osd_w = player._p.osd_width  or 1920
            osd_h = player._p.osd_height or 1080
        except Exception:
            osd_w, osd_h = 1920, 1080

        state_key = (st, sa, sth, osd_w, osd_h)
        if _song_base_cache[0] != state_key:
            _song_base_cache[0] = state_key
            _canvas, _nx, _ny = _draw_song_base(st, sa, sth, osd_w, osd_h)
            _song_base_cache[1] = _canvas
            _song_base_cache[2] = _nx
            _song_base_cache[3] = _ny

        base = _song_base_cache[1]
        canvas = base.copy() if (base is not None and sm) else (
            base if base is not None else Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
        )

        if sm and base is not None:
            modifier   = min(osd_w / 2560, osd_h / 1440)
            base_note  = max(20, round(160 * modifier))
            max_note   = max(24, round(200 * modifier))
            elapsed    = _wall_time() - _song_anim_start[0]
            if not player.is_playing():
                _song_anim_start[0] += 0.05  # freeze elapsed while paused
            # ~1.5 second period for a full pulse cycle
            angle      = elapsed * (2 * math.pi / 1.5)
            px = int(base_note + math.sin(angle) * (max_note - base_note) / 2)
            if px not in _song_note_px_cache:
                from PIL import ImageFont
                font = None
                for path in ["C:/Windows/Fonts/seguiemj.ttf", "C:/Windows/Fonts/seguisym.ttf"]:
                    try:
                        font = ImageFont.truetype(path, px)
                        break
                    except Exception:
                        pass
                _song_note_px_cache[px] = font or _get_ass_font(px, bold=False)
            note_font = _song_note_px_cache[px]
            if note_font:
                draw       = ImageDraw.Draw(canvas)
                NOTE_TEXT  = "\U0001F3B5"
                bbox       = draw.textbbox((0, 0), NOTE_TEXT, font=note_font)
                nh         = bbox[3] - bbox[1]
                note_gap   = max(8, round(30 * modifier))
                nx         = _song_base_cache[2] + note_gap - bbox[0]
                ny         = _song_base_cache[3] - nh // 2 - bbox[1] - nh // 3
                bdr        = max(2, px // 22)
                nc         = _song_note_color[0]
                for dx, dy in ((-bdr, 0), (bdr, 0), (0, -bdr), (0, bdr),
                               (-bdr, -bdr), (bdr, -bdr), (-bdr, bdr), (bdr, bdr)):
                    draw.text((nx + dx, ny + dy), NOTE_TEXT, font=note_font, fill=(0, 0, 0, 200))
                draw.text((nx, ny), NOTE_TEXT, font=note_font, fill=nc)

        try:
            _song_img_overlay.update(canvas)
        except Exception:
            _song_img_overlay = None
            return
        _song_anim_after = root.after(50, _song_step)

    _song_step()
