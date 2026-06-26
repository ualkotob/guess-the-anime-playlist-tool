"""General-purpose mpv-overlay effects, not specific to any one lightning mode.

Both are reached by lightning_manager via direct import but are plain
overlay helpers:

    spawn_pulsating_music_note(...)   centre-screen pulsating 🎵 image overlay
                                      (create_image_overlay plane, animated)
    toggle_outer_edge_overlay(...)    bottom censor bar drawn via mpv osd-overlay
                                      (ASS), e.g. to hide watermarks

State owned (module-private, no external readers):
    _note_img_overlay / _note_anim_after   pulsating-note overlay + animation id
    _outer_edge_overlay_active             sentinel (truthy while bar is shown)
"""

import math
import random

from core.game_state import state
import _app_scripts.playback.osd_text as osd_text


# ASS osd-overlay layer id for the bottom censor bar.
_OUTER_EDGE_ASS_OSD_ID = 54


# --- spawn_pulsating_music_note — used by MISMATCH and other lightning paths ---
_note_img_overlay = None
_note_anim_after = None


def spawn_pulsating_music_note(x=0, y=0, font_size=100, destroy=False):
    # x / y / font_size are vestigial (kept for signature compatibility); the
    # note is always centred and sized relative to the live OSD height.
    global _note_img_overlay, _note_anim_after
    player = state.widgets.player
    root = state.widgets.root

    # Cancel any running animation
    if _note_anim_after is not None:
        try:
            root.after_cancel(_note_anim_after)
        except Exception:
            pass
        _note_anim_after = None

    # Remove existing overlay
    if _note_img_overlay is not None:
        try:
            _note_img_overlay.remove()
        except Exception:
            pass
        _note_img_overlay = None

    if destroy:
        return

    # Pick a random bright color once per spawn
    note_color = (random.randint(100, 255), random.randint(100, 255), random.randint(100, 255), 255)

    # Try Segoe UI Emoji so we can render 🎵 properly; fall back to Arial ♪
    _emoji_font_cache = {}
    def _get_note_font(px):
        if px not in _emoji_font_cache:
            from PIL import ImageFont
            for path in ["C:/Windows/Fonts/seguiemj.ttf", "C:/Windows/Fonts/seguisym.ttf"]:
                try:
                    _emoji_font_cache[px] = ImageFont.truetype(path, px)
                    break
                except Exception:
                    pass
            else:
                _emoji_font_cache[px] = osd_text._get_ass_font(px, bold=False)
        return _emoji_font_cache[px]

    NOTE_TEXT = "\U0001F3B5"  # 🎵

    _note_img_overlay = player._p.create_image_overlay()
    _step = [0.0]
    _last_osd = [0, 0]  # track last known OSD size for dynamic rebase
    _frame_cache = [None, None, None]  # [last_px, last_canvas_w, last_canvas]

    def _note_step():
        global _note_img_overlay, _note_anim_after
        if _note_img_overlay is None:
            return
        try:
            cur_osd_w = player._p.osd_width or 1920
            cur_osd_h = player._p.osd_height or 1080
        except Exception:
            cur_osd_w, cur_osd_h = 1920, 1080

        # Dynamically rebase whenever OSD size changes
        if cur_osd_w != _last_osd[0] or cur_osd_h != _last_osd[1]:
            _last_osd[0] = cur_osd_w
            _last_osd[1] = cur_osd_h
            _step[1] = max(60, int(cur_osd_h * 0.30))   # base_px
            _step[2] = int(_step[1] * 1.15)              # max_px
            _frame_cache[0] = None  # force redraw on resize

        base_px = _step[1]
        max_px  = _step[2]

        if not player.is_playing():
            _note_anim_after = root.after(50, _note_step)
            return

        _step[0] += 0.9  # pulse speed
        px = int(base_px + math.sin(_step[0]) * (max_px - base_px) / 2)

        # Only re-render when the pixel size actually changed
        if px == _frame_cache[0] and cur_osd_w == _frame_cache[1]:
            _note_anim_after = root.after(50, _note_step)
            return

        from PIL import Image, ImageDraw
        canvas = Image.new("RGBA", (cur_osd_w, cur_osd_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        font = _get_note_font(px)
        if font:
            bbox = draw.textbbox((0, 0), NOTE_TEXT, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (cur_osd_w - tw) // 2 - bbox[0]
            ty = (cur_osd_h - th) // 2 - bbox[1]
            # 8-point outline — vastly cheaper than a full grid loop
            border = max(3, px // 22)
            for dx, dy in ((-border, 0), (border, 0), (0, -border), (0, border),
                           (-border, -border), (border, -border), (-border, border), (border, border)):
                draw.text((tx + dx, ty + dy), NOTE_TEXT, font=font, fill=(0, 0, 0, 200))
            draw.text((tx, ty), NOTE_TEXT, font=font, fill=note_color)

        _frame_cache[0] = px
        _frame_cache[1] = cur_osd_w
        _frame_cache[2] = canvas
        try:
            _note_img_overlay.update(canvas)
        except Exception:
            _note_img_overlay = None
            return
        _note_anim_after = root.after(50, _note_step)

    # Initialise the per-step size slots before the first call
    try:
        _init_h = player._p.osd_height or 1080
    except Exception:
        _init_h = 1080
    _step.append(max(60, int(_init_h * 0.30)))   # index 1: base_px
    _step.append(int(_step[1] * 1.15))            # index 2: max_px
    _step.append(0)                               # index 3: unused sentinel
    _note_step()


# --- toggle_outer_edge_overlay — bottom censor bar (ASS osd-overlay) ---
_outer_edge_overlay_active = None


def toggle_outer_edge_overlay(destroy=False, pixels=65, color="black"):
    """Bottom censor bar drawn via mpv osd-overlay (ASS).  Covers the bottom `pixels`
    screen-pixels-equivalent of the video, e.g. to hide Crunchyroll watermarks."""
    global _outer_edge_overlay_active

    if destroy:
        if _outer_edge_overlay_active:
            _outer_edge_overlay_active = None
            try:
                osd_text.osd_command('osd-overlay', _OUTER_EDGE_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
            except Exception:
                pass
        return

    try:
        osd_w = int(state.widgets.player._p.osd_width or 0)
        osd_h = int(state.widgets.player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    # When framed_video is active, anchor bar to the bottom of the framed video rect.
    # Lazy import: overlay_primitives is a low-level OSD primitive below blind_screen.
    import _app_scripts.playback.blind_screen as blind_screen
    import _app_scripts.information.information_popup as information_popup
    if blind_screen._video_frame_active:
        _, _, fv_x, fv_y, fv_w, fv_h = information_popup._get_effective_video_rect()
        # Scale bar height relative to the framed video height instead of the full OSD height.
        bar_h = max(1, round(pixels * fv_h / 1080))
        bar_x = fv_x
        bar_y = fv_y + fv_h - bar_h
        bar_w = fv_w
    else:
        # Scale bar height from reference 1080p screen pixels to OSD pixels.
        bar_h = max(1, round(pixels * osd_h / 1080))
        bar_x, bar_y, bar_w = 0, osd_h - bar_h, osd_w
    color_bgr = osd_text._color_str_to_ass_bgr(color)

    ass_payload = (
        f"{{\\an7\\pos(0,{bar_y})"
        f"\\1c&H{color_bgr}&\\1a&H00&\\bord0\\shad0\\p1}}"
        f"m {bar_x} 0 l {bar_x+bar_w} 0 {bar_x+bar_w} {bar_h} {bar_x} {bar_h}{{\\p0}}"
    )
    try:
        osd_text.osd_command('osd-overlay', _OUTER_EDGE_ASS_OSD_ID, 'ass-events',
                          ass_payload, osd_w, osd_h, 1, 'no')  # z=1, same as blind layer
    except Exception:
        return
    _outer_edge_overlay_active = True  # sentinel — truthy while active
