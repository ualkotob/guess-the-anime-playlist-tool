"""Animated music-note progress overlay for lightning/OST rounds."""

import colorsys
import math
import os
import random
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core.game_state import state

import _app_scripts.queue_round.lightning_rounds.lightning_settings as lightning_settings


def is_light_progress_bar_active():
    return bool(light_progress_bar)
progress_overlay = None         # sentinel — True when active, None when not
light_progress_bar = None       # sentinel — True when active (checked externally), None when not
music_icon_label = None         # kept for compat; unused in mpv PIL mode
pulse_step = 0
progress_bar_ready = False
_pulse_sizes = (48, 60)
_progress_img_overlay  = None
_progress_bar_color    = None   # (r, g, b) chosen at creation
_progress_icon_color   = None   # (r, g, b) chosen at creation
_progress_music_icon   = "\U0001f3b5"
_progress_pulse_step   = 0.0
_progress_last_time    = 0.0
_progress_last_total   = 1.0
_progress_tick_gen     = 0      # incremented each time the tick loop is started; old loops self-terminate
# Per-creation caches (rebuilt on first call; avoid re-computation every frame)
_progress_bg_layer     = None   # pre-rendered static background RGBA PIL image
_progress_bg_np        = None   # numpy view of bg layer — (h, w, 4) uint8, read-only
_progress_canvas_np    = None   # persistent writable working buffer — (h, w, 4) uint8
_progress_icon_cache   = None   # pre-rendered emoji RGBA image at max size (PIL)
_progress_icon_frames  = {}     # {icon_px: (np_array, cw, ch)} — pre-cached every size
_progress_icon_base_px = 48
_progress_icon_max_px  = 60
_progress_cached_osd   = (0, 0) # (osd_w, osd_h) when _progress_bg_layer was built
_progress_bg_col       = (30, 30, 30, 204)
_progress_fg_col       = (255, 255, 255, 255)
# Pre-computed layout constants (rebuilt when osd size changes)
_progress_bar_x        = 0
_progress_bar_y        = 0
_progress_bar_w        = 0
_progress_bar_h        = 0
_progress_bar_ol       = 1      # bar outline width in px
_progress_icon_slot_w  = 0
_progress_icon_cy      = 0
_progress_prev_icon_box = (0, 0, 0, 0)  # (ox, oy, ox+cw, oy+ch) of last icon blit — sub-image coords
# Sub-image BGRA premult buffers — only covers the box area, not the full OSD
_progress_sub_x    = 0       # box top-left x in OSD coords
_progress_sub_y    = 0       # box top-left y in OSD coords
_progress_sub_w    = 0       # box width
_progress_sub_h    = 0       # box height
_progress_bgra_arr = None    # (sub_h, sub_w, 4) uint8 premult BGRA — writable per-frame buffer
_progress_bgbg_arr = None    # (sub_h, sub_w, 4) uint8 premult BGRA — read-only bg reference
_progress_fill_strip = None  # (bar_inner_h, 1, 4) uint8 premult BGRA — shaded column, broadcast per frame
# ── Bar shading style: 1=glossy pill  2=tubular/center-lit  3=inner bevel  4=soft gradient  5=two-tone ──
_PROGRESS_BAR_SHADE_STYLE = 4


def _get_fixed_playlist_progress(current_round_elapsed_secs):
    """Return (elapsed*100, total*100) across the whole fixed playlist, or None if not active.

    Scales the progress bar to show the position within the entire fixed round
    playlist rather than just the current round.  Each round contributes its
    question duration plus its answer duration to the total.
    """
    fixed_lightning_round_playlist_data = state.lightning.fixed_lightning_round_playlist_data
    if not fixed_lightning_round_playlist_data:
        return None
    rounds = fixed_lightning_round_playlist_data.get("rounds", [])
    current_idx = fixed_lightning_round_playlist_data.get("current_index", 0)
    if not rounds:
        return None
    total = 0.0
    elapsed = 0.0
    lightning_mode_settings = state.playback.lightning_mode_settings
    for i, r in enumerate(rounds):
        rtype = r.get("type", "regular")
        default_dur = lightning_mode_settings.get(rtype, {}).get("length", lightning_settings.LIGHT_ROUND_LENGTH_DEFAULT)
        default_ans = lightning_mode_settings["_misc_settings"].get("answer_length", lightning_settings.LIGHT_ROUND_ANSWER_LENGTH_DEFAULT)
        dur = float(r.get("duration", default_dur))
        ans = float(r.get("answer_duration", default_ans))
        total += dur + ans
        if i < current_idx:
            elapsed += dur + ans
        elif i == current_idx:
            elapsed += min(float(current_round_elapsed_secs), dur + ans)
    return (round(elapsed * 100), round(total * 100))


def _rebuild_progress_bg_layer(osd_w, osd_h):
    """Pre-render the static background, layout constants, and ALL icon sizes.
    Called once at creation and again only if OSD resolution changes."""
    global _progress_bg_layer, _progress_bg_np, _progress_canvas_np
    global _progress_icon_cache, _progress_icon_frames, _progress_cached_osd
    global _progress_icon_base_px, _progress_icon_max_px
    global _progress_bar_x, _progress_bar_y, _progress_bar_w, _progress_bar_h, _progress_bar_ol
    global _progress_icon_slot_w, _progress_icon_cy
    global _progress_bg_col, _progress_fg_col
    global _progress_prev_icon_box
    global _progress_sub_x, _progress_sub_y, _progress_sub_w, _progress_sub_h
    global _progress_bgra_arr, _progress_bgbg_arr
    global _progress_fill_strip

    osd_mod = min(osd_w / 2560, osd_h / 1440)
    def ws(n): return max(1, int(n * osd_mod))

    # Colours — resolve once here, cache for fast access every frame
    root = state.widgets.root
    try:
        r16, g16, b16 = root.winfo_rgb(state.colors.OVERLAY_BACKGROUND_COLOR)
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
        r16, g16, b16 = root.winfo_rgb(state.colors.OVERLAY_TEXT_COLOR)
        fg_r, fg_g, fg_b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        bg_r, bg_g, bg_b = 30, 30, 30
        fg_r, fg_g, fg_b = 255, 255, 255
    alpha  = round(0.8 * 255)
    bg     = (bg_r, bg_g, bg_b, alpha)
    fg     = (fg_r, fg_g, fg_b, 255)
    _progress_bg_col = bg
    _progress_fg_col = fg

    # Layout
    box_w  = round(osd_w * 0.7)
    box_h  = round(osd_h * 0.5)
    box_x  = (osd_w - box_w) // 2
    box_y  = (osd_h - box_h) // 2
    border = max(1, round(4 * osd_mod))
    inner_x = box_x + border
    inner_y = box_y + border
    inner_w = box_w - 2 * border
    inner_h = box_h - 2 * border

    bar_w  = round(osd_w * 0.6)
    bar_h  = max(8, round(osd_h / 10))
    bar_cx = inner_x + inner_w // 2
    bar_cy = inner_y + round(inner_h * 0.7)
    bar_x  = bar_cx - bar_w // 2
    bar_y  = bar_cy - bar_h // 2
    bar_ol = max(2, round(5 * osd_mod))   # bar outline thickness

    _progress_bar_x = bar_x
    _progress_bar_y = bar_y
    _progress_bar_w = bar_w
    _progress_bar_h = bar_h
    _progress_bar_ol = bar_ol
    _progress_icon_slot_w = ws(40)
    _progress_icon_cy = inner_y + round(inner_h * 0.35)
    _progress_prev_icon_box = (0, 0, 0, 0)  # reset on rebuild

    # Icon size range — DPI queried once here
    _screen_dpi = root.winfo_fpixels('1i')
    _progress_icon_base_px = max(8,  round(ws(160) * _screen_dpi / 72))
    _progress_icon_max_px  = max(10, round(ws(200) * _screen_dpi / 72))

    # ── Static background layer (PIL then numpy) ─────────────────────────
    layer = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    d     = ImageDraw.Draw(layer)
    d.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], fill=bg)
    d.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], outline=fg, width=border)
    try:
        mr16, mg16, mb16 = root.winfo_rgb(state.colors.MIDDLE_OVERLAY_BACKGROUND_COLOR)
        tr, tg, tb_ = mr16 >> 8, mg16 >> 8, mb16 >> 8
    except Exception:
        tr = max(0, bg_r - 30); tg = max(0, bg_g - 30); tb_ = max(0, bg_b - 30)
    d.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                fill=(tr, tg, tb_, alpha))
    d.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                outline=fg, width=bar_ol)
    _progress_bg_layer  = layer
    _progress_bg_np     = np.array(layer, dtype=np.uint8)  # read-only reference
    _progress_canvas_np = _progress_bg_np.copy()           # writable working buffer
    _progress_cached_osd = (osd_w, osd_h)

    # ── Sub-image BGRA premult buffer — covers only the box, not the full OSD ──
    # This lets overlay_add work on ~3× less data than a full OSD-sized image.
    _progress_sub_x = box_x
    _progress_sub_y = box_y
    _progress_sub_w = box_w
    _progress_sub_h = box_h
    _bg_sub = _progress_bg_np[box_y:box_y + box_h, box_x:box_x + box_w]
    _a16    = _bg_sub[:, :, 3].astype(np.uint16)
    _bgbg   = np.empty_like(_bg_sub)
    _bgbg[:, :, 0] = (_bg_sub[:, :, 2].astype(np.uint16) * _a16 // 255).astype(np.uint8)  # B = R·α
    _bgbg[:, :, 1] = (_bg_sub[:, :, 1].astype(np.uint16) * _a16 // 255).astype(np.uint8)  # G = G·α
    _bgbg[:, :, 2] = (_bg_sub[:, :, 0].astype(np.uint16) * _a16 // 255).astype(np.uint8)  # R = B·α
    _bgbg[:, :, 3] = _bg_sub[:, :, 3]
    _progress_bgbg_arr = _bgbg            # read-only bg reference
    _progress_bgra_arr = _bgbg.copy()     # writable per-frame buffer

    # ── Pre-compute shaded fill strip: (bar_inner_h, 1, 4) BGRA premult ──
    # All fully opaque (α=255) so premult == identity — cheap broadcast per frame.
    br, bg_c, bb = _progress_bar_color
    inner_h_bar = max(1, bar_h - bar_ol * 2)   # height of fill region
    _strip = np.empty((inner_h_bar, 1, 4), dtype=np.uint8)
    for _row in range(inner_h_bar):
        _t = _row / max(1, inner_h_bar - 1)    # 0.0 (top) → 1.0 (bottom)
        _style = _PROGRESS_BAR_SHADE_STYLE
        if _style == 1:
            # ── Refined glossy pill ──────────────────────────────────────────
            # Thin bright gloss at top, quick drop to base, gentle shadow at bottom.
            if _t < 0.12:   _f = 1.45
            elif _t < 0.30: _f = 1.15
            elif _t < 0.80: _f = 1.0
            else:            _f = 0.72
        elif _style == 2:
            # ── Tubular / center-lit ─────────────────────────────────────────
            # Brightest at the vertical centre, symmetrically dark toward both edges.
            _f = 0.75 + 0.50 * (1.0 - abs(_t - 0.5) * 2.0)
        elif _style == 3:
            # ── Flat + inner bevel ───────────────────────────────────────────
            # 2px bright line on top, 2px dark line on bottom, solid in between.
            if _row < 2:                      _f = 1.70
            elif _row >= inner_h_bar - 2:     _f = 0.45
            else:                              _f = 1.0
        elif _style == 4:
            # ── Soft linear gradient (light → dark) ──────────────────────────
            _f = 1.30 - 0.60 * _t
        else:
            # ── Two-tone split ───────────────────────────────────────────────
            # Top half bright, 1px separator, bottom half dark.
            _mid = inner_h_bar // 2
            if _row == _mid:                  _f = 1.55   # bright separator line
            elif _row < _mid:                 _f = 1.25
            else:                             _f = 0.72
        _rr = int(min(255, br * _f))
        _gg = int(min(255, bg_c * _f))
        _bb = int(min(255, bb * _f))
        _strip[_row, 0] = (_bb, _gg, _rr, 255)   # BGRA layout
    _progress_fill_strip = _strip

    # ── Icon range: pulsation oscillates AROUND base_px by ±delta/2 ────────
    # formula: base + sin * (max - base) / 2  →  range [base-delta/2, base+delta/2]
    _screen_dpi        = root.winfo_fpixels('1i')
    _progress_icon_base_px = max(8,  round(ws(160) * _screen_dpi / 72))
    _progress_icon_max_px  = max(10, round(ws(200) * _screen_dpi / 72))
    _ic_delta          = _progress_icon_max_px - _progress_icon_base_px
    _ic_cache_min      = max(8, _progress_icon_base_px - _ic_delta // 2)
    _ic_cache_max      = _progress_icon_base_px + _ic_delta // 2

    # ── Detect whether the icon is emoji or plain text ───────────────────
    ic = unicodedata.normalize('NFC', _progress_music_icon)
    _is_emoji = any(
        0x1F300 <= ord(ch) or
        0x2600  <= ord(ch) <= 0x27BF or   # misc symbols / dingbats
        0xFE00  <= ord(ch) <= 0xFE0F      # variation selectors
        for ch in ic
    )

    # ── Pre-render icon at max size (LANCZOS once) ───────────────────────
    max_px = _ic_cache_max
    if _is_emoji:
        _efont_em = None
        for _fp in [r"C:\Windows\Fonts\seguiemj.ttf",
                    r"C:\Windows\Fonts\NotoColorEmoji.ttf",
                    r"C:\Windows\Fonts\seguisym.ttf"]:
            if os.path.exists(_fp):
                try:
                    _efont_em = ImageFont.truetype(_fp, size=max_px * 8)
                    break
                except Exception:
                    pass
        cs = max_px * 12   # extra headroom for ascenders
        em = Image.new("RGBA", (cs, cs), (0, 0, 0, 0))
        if _efont_em:
            ImageDraw.Draw(em).text((cs // 2, cs // 2), ic,
                                    font=_efont_em, anchor="mm", embedded_color=True)
    else:
        # Plain text icon (e.g. "( ͡° ͜ʖ ͡°)", "📺" text etc.) — use a regular Unicode font
        _efont_txt = None
        for _fp in [r"C:\Windows\Fonts\segoeui.ttf",
                    r"C:\Windows\Fonts\arial.ttf",
                    r"C:\Windows\Fonts\DejaVuSans.ttf"]:
            if os.path.exists(_fp):
                try:
                    _efont_txt = ImageFont.truetype(_fp, size=max_px * 4)
                    break
                except Exception:
                    pass
        cs = max_px * 12
        em = Image.new("RGBA", (cs, cs), (0, 0, 0, 0))
        _txt_col = (*_progress_icon_color, 255)
        if _efont_txt:
            ImageDraw.Draw(em).text((cs // 2, cs // 2), ic,
                                    font=_efont_txt, fill=_txt_col, anchor="mm")
        else:
            # absolute fallback
            ImageDraw.Draw(em).text((cs // 2, cs // 2), ic, fill=_txt_col, anchor="mm")

    bbox = em.getbbox()
    if bbox:
        # Add a small margin so glyphs with ascenders don't clip at the bbox edge
        pad  = max(4, (bbox[3] - bbox[1]) // 10)
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                min(cs, bbox[2] + pad), min(cs, bbox[3] + pad))
        cropped = em.crop(bbox)
        cw0, ch0 = cropped.size
        sc  = min(max_px / cw0, max_px / ch0) if cw0 and ch0 else 1.0
        cw2 = max(1, int(cw0 * sc))
        ch2 = max(1, int(ch0 * sc))
        master = cropped.resize((cw2, ch2), Image.LANCZOS)
        # ── Tint the icon with the random icon colour ─────────────────────
        _tr, _tg, _tb = _progress_icon_color
        _master_np = np.array(master, dtype=np.uint16)
        _master_np[:, :, 0] = (_master_np[:, :, 0] * _tr // 255).clip(0, 255)
        _master_np[:, :, 1] = (_master_np[:, :, 1] * _tg // 255).clip(0, 255)
        _master_np[:, :, 2] = (_master_np[:, :, 2] * _tb // 255).clip(0, 255)
        _master_np = _master_np.astype(np.uint8)

        # ── Bake white outline (done once here, free at runtime) ──────────
        # Dilate the alpha channel by _OL pixels in 8 directions → outline mask.
        _OL  = max(1, max_px // 28)           # outline thickness scales with icon size
        _PAD = _OL * 2 + 6                    # generous margin: covers diagonal + LANCZOS bleed at all cache sizes
        # Pad canvas so outline always has room and doesn't clip at any edge
        _ph_np, _pw_np = _master_np.shape[:2]
        _padded = np.zeros((_ph_np + _PAD * 2, _pw_np + _PAD * 2, 4), dtype=np.uint8)
        _padded[_PAD:_PAD + _ph_np, _PAD:_PAD + _pw_np] = _master_np
        _master_np = _padded
        _orig_a  = _master_np[:, :, 3].astype(np.uint8)
        _dil_a   = _orig_a.copy()
        for _dy in range(-_OL, _OL + 1):
            for _dx in range(-_OL, _OL + 1):
                if _dx == 0 and _dy == 0:
                    continue
                if _dx * _dx + _dy * _dy > _OL * _OL:   # circular kernel — skip corners
                    continue
                _shifted = np.roll(np.roll(_orig_a, _dy, axis=0), _dx, axis=1)
                # Zero out wrapped edges so roll doesn't bleed across borders
                if _dy > 0:  _shifted[:_dy,  :] = 0
                elif _dy < 0: _shifted[_dy:,  :] = 0
                if _dx > 0:  _shifted[:,  :_dx] = 0
                elif _dx < 0: _shifted[:, _dx:] = 0
                np.maximum(_dil_a, _shifted, out=_dil_a)
        # Outline pixels = dilated area minus original opaque pixels
        _outline_mask = (_dil_a.astype(np.uint16) * (255 - _orig_a.astype(np.uint16)) // 255).astype(np.uint8)
        # Build final RGBA: start with white outline layer, composite tinted icon on top
        _out_np = np.zeros((_master_np.shape[0], _master_np.shape[1], 4), dtype=np.uint8)
        _out_np[:, :, 0] = 255   # R white
        _out_np[:, :, 1] = 255   # G white
        _out_np[:, :, 2] = 255   # B white
        _out_np[:, :, 3] = _outline_mask
        # Alpha-composite tinted icon over white outline
        _fa = _master_np[:, :, 3].astype(np.uint16)
        _ia = (255 - _fa)
        _out_np[:, :, 0] = (_master_np[:, :, 0].astype(np.uint16) * _fa // 255 +
                            _out_np[:, :, 0].astype(np.uint16) * _ia // 255).clip(0, 255).astype(np.uint8)
        _out_np[:, :, 1] = (_master_np[:, :, 1].astype(np.uint16) * _fa // 255 +
                            _out_np[:, :, 1].astype(np.uint16) * _ia // 255).clip(0, 255).astype(np.uint8)
        _out_np[:, :, 2] = (_master_np[:, :, 2].astype(np.uint16) * _fa // 255 +
                            _out_np[:, :, 2].astype(np.uint16) * _ia // 255).clip(0, 255).astype(np.uint8)
        _out_np[:, :, 3] = np.maximum(_orig_a, _outline_mask)

        master = Image.fromarray(_out_np)
        _progress_icon_cache = master
    else:
        _progress_icon_cache = None

    # ── Pre-cache ALL icon pixel sizes for the FULL pulsation range ───────
    # Each frame is a dict lookup — zero resize cost per frame.
    _progress_icon_frames = {}
    if _progress_icon_cache is not None:
        src = _progress_icon_cache
        sw, sh = src.size
        for px in range(_ic_cache_min, _ic_cache_max + 1):
            sc  = min(px / sw, px / sh) if sw and sh else 1.0
            pw  = max(1, int(sw * sc))
            ph  = max(1, int(sh * sc))
            resized = src.resize((pw, ph), Image.LANCZOS)
            _progress_icon_frames[px] = (np.array(resized, dtype=np.uint8), pw, ph)
    # Store the effective cache bounds so the redraw clamp uses the same range
    _progress_icon_base_px = _ic_cache_min
    _progress_icon_max_px  = _ic_cache_max

    # Convert all cached RGBA icon frames → premultiplied BGRA (done once at build time)
    for _px in list(_progress_icon_frames.keys()):
        _rgba, _pw, _ph = _progress_icon_frames[_px]
        _ia16   = _rgba[:, :, 3].astype(np.uint16)
        _bgra_f = np.empty_like(_rgba)
        _bgra_f[:, :, 0] = (_rgba[:, :, 2].astype(np.uint16) * _ia16 // 255).astype(np.uint8)  # B
        _bgra_f[:, :, 1] = (_rgba[:, :, 1].astype(np.uint16) * _ia16 // 255).astype(np.uint8)  # G
        _bgra_f[:, :, 2] = (_rgba[:, :, 0].astype(np.uint16) * _ia16 // 255).astype(np.uint8)  # R
        _bgra_f[:, :, 3] = _rgba[:, :, 3]
        _progress_icon_frames[_px] = (_bgra_f, _pw, _ph)


def _redraw_progress_overlay():
    """Render one frame directly into a premultiplied-BGRA sub-image buffer
    and upload via overlay_add — no full-OSD PIL copies, no alpha_composite."""
    global _progress_prev_icon_box

    if _progress_bgra_arr is None or _progress_img_overlay is None:
        return
    player = state.widgets.player
    try:
        osd_w = player._p.osd_width
        osd_h = player._p.osd_height
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    if _progress_cached_osd != (osd_w, osd_h):
        _rebuild_progress_bg_layer(osd_w, osd_h)

    # Icon size: pulsates symmetrically around the midpoint of the cached range
    _ic_mid = (_progress_icon_base_px + _progress_icon_max_px) // 2
    _ic_amp = (_progress_icon_max_px - _progress_icon_base_px) / 2
    icon_px = int(round(_ic_mid + math.sin(_progress_pulse_step) * _ic_amp))
    icon_px = max(_progress_icon_base_px, min(_progress_icon_max_px, icon_px))

    # Progress geometry
    total   = _progress_last_total if _progress_last_total > 0 else 1
    ratio   = min(max(_progress_last_time / total, 0.0), 1.0)
    fill_w  = round(_progress_bar_w * ratio)
    icon_cx = _progress_bar_x + round(ratio * max(0, _progress_bar_w - _progress_icon_slot_w))

    # Sub-image coordinate offsets (all array indices are relative to the box corner)
    sx = _progress_sub_x
    sy = _progress_sub_y
    sw = _progress_sub_w
    sh = _progress_sub_h
    bx = _progress_bar_x - sx
    by = _progress_bar_y - sy
    bw = _progress_bar_w
    bh = _progress_bar_h
    ol = _progress_bar_ol

    # ── Restore bar region from bg ─────────────────────────────────────────
    _progress_bgra_arr[by:by + bh, bx:bx + bw] = _progress_bgbg_arr[by:by + bh, bx:bx + bw]

    # ── Restore previous icon region from bg (coordinates are sub-image) ──
    ox0, oy0, ox1, oy1 = _progress_prev_icon_box
    if ox1 > ox0 and oy1 > oy0:
        oy0c = max(0, oy0); oy1c = min(sh, oy1)
        ox0c = max(0, ox0); ox1c = min(sw, ox1)
        if oy1c > oy0c and ox1c > ox0c:
            _progress_bgra_arr[oy0c:oy1c, ox0c:ox1c] = _progress_bgbg_arr[oy0c:oy1c, ox0c:ox1c]

    # ── Draw fill bar (inside outline) — shaded strip broadcast across fill width ──
    if fill_w > ol * 2:
        fill_x1 = bx + ol
        fill_x2 = min(bx + fill_w, bx + bw - ol)
        fill_y1 = by + ol
        fill_y2 = by + bh - ol
        if fill_x2 > fill_x1 and fill_y2 > fill_y1 and _progress_fill_strip is not None:
            strip_h = _progress_fill_strip.shape[0]
            # Guard in case strip height doesn't match (e.g. right after a rebuild)
            use_h = min(fill_y2 - fill_y1, strip_h)
            _progress_bgra_arr[fill_y1:fill_y1 + use_h, fill_x1:fill_x2] = \
                _progress_fill_strip[:use_h]    # numpy broadcasts (use_h,1,4) → (use_h, fill_w, 4)

    # ── Alpha-composite pre-cached icon (premultiplied BGRA frames) ────────
    frame = _progress_icon_frames.get(icon_px)
    if frame is not None:
        icon_arr, iw, ih = frame                        # icon_arr is premult BGRA
        ox  = icon_cx - sx - iw // 2
        oy  = _progress_icon_cy - sy - ih // 2
        src_x0 = max(0, -ox);    src_y0 = max(0, -oy)
        dst_x0 = max(0,  ox);    dst_y0 = max(0,  oy)
        dst_x1 = min(sw, ox + iw); dst_y1 = min(sh, oy + ih)
        if dst_x1 > dst_x0 and dst_y1 > dst_y0:
            src_x1 = src_x0 + (dst_x1 - dst_x0)
            src_y1 = src_y0 + (dst_y1 - dst_y0)
            src = icon_arr[src_y0:src_y1, src_x0:src_x1]
            dst = _progress_bgra_arr[dst_y0:dst_y1, dst_x0:dst_x1]
            # Premultiplied compositing (integer): out = src + dst·(1 − src_α/255)
            inv_a  = (255 - src[:, :, 3]).astype(np.uint16)
            result = (src.astype(np.uint16)
                      + (dst.astype(np.uint16) * inv_a[:, :, None] + 127) // 255)
            _progress_bgra_arr[dst_y0:dst_y1, dst_x0:dst_x1] = result.clip(0, 255).astype(np.uint8)
        _progress_prev_icon_box = (ox, oy, ox + iw, oy + ih)    # sub-image coords
    else:
        _progress_prev_icon_box = (0, 0, 0, 0)

    # ── Upload sub-image directly (bypass PIL alpha_composite + tobytes) ───
    # ~3× less data than a full OSD-sized overlay; no PIL allocation per frame.
    source = '&' + str(_progress_bgra_arr.ctypes.data)
    player._p.overlay_add(
        _progress_img_overlay.overlay_id,
        sx, sy, source, 0, 'bgra',
        sw, sh, sw * 4
    )


def _progress_overlay_tick(_gen=None):
    """50 ms animation tick: advance the pulse step and redraw the progress overlay."""
    global _progress_pulse_step
    if _gen != _progress_tick_gen:
        return  # a newer tick loop has taken over — self-terminate
    if _progress_img_overlay is None:
        return  # overlay destroyed — let the loop die
    root = state.widgets.root
    player = state.widgets.player
    if not player.is_playing():
        root.after(500, _progress_overlay_tick, _gen)   # check again later when paused
        return
    _progress_pulse_step += 0.55
    _redraw_progress_overlay()
    root.after(50, _progress_overlay_tick, _gen)


def set_progress_overlay(current_time=None, total_length=None, destroy=False):
    global progress_overlay, light_progress_bar, music_icon_label, progress_bar_ready
    global _progress_img_overlay, _progress_bar_color, _progress_icon_color, _progress_music_icon
    global _progress_pulse_step, _progress_last_time, _progress_last_total, _progress_tick_gen
    global _progress_bg_layer, _progress_bg_np, _progress_canvas_np
    global _progress_icon_cache, _progress_icon_frames, _progress_cached_osd, _progress_prev_icon_box
    global _progress_bgra_arr, _progress_bgbg_arr, _progress_fill_strip
    global _progress_sub_x, _progress_sub_y, _progress_sub_w, _progress_sub_h

    if destroy:
        # Lazy import: progress_overlay is a playback primitive below information_popup.
        import _app_scripts.information.information_popup as information_popup
        information_popup._unregister_mpv_tracked_window("progress_overlay")
        if _progress_img_overlay is not None:
            try:
                _progress_img_overlay.remove()
            except Exception:
                pass
            _progress_img_overlay = None
        progress_overlay    = None
        light_progress_bar  = None
        music_icon_label    = None
        progress_bar_ready  = False
        _progress_pulse_step  = 0.0
        _progress_tick_gen  += 1      # invalidate any running tick loop
        _progress_bg_layer    = None
        _progress_bg_np       = None
        _progress_canvas_np   = None
        _progress_icon_cache  = None
        _progress_icon_frames = {}
        _progress_cached_osd  = (0, 0)
        _progress_prev_icon_box = (0, 0, 0, 0)
        _progress_bgra_arr  = None
        _progress_bgbg_arr  = None
        _progress_fill_strip = None
        _progress_sub_x = _progress_sub_y = _progress_sub_w = _progress_sub_h = 0
        return

    # Store latest time so the animation tick always has fresh values
    if current_time is not None:
        _progress_last_time = current_time
    if total_length is not None:
        _progress_last_total = total_length

    if progress_overlay is None:
        # First call: pick random colours and icon, create OSD, start animation loop
        _progress_bar_color  = (random.randint(0, 200), random.randint(0, 200), random.randint(0, 200))
        _ic_h = random.random()                              # random hue 0–1
        _ic_r, _ic_g, _ic_b = colorsys.hsv_to_rgb(_ic_h, 0.85, 1.0)   # vivid, full brightness
        _progress_icon_color = (int(_ic_r * 255), int(_ic_g * 255), int(_ic_b * 255))
        fixed_current_round = state.lightning.fixed_current_round
        light_mode = state.lightning.light_mode
        if fixed_current_round and fixed_current_round.get("music_icon"):
            _progress_music_icon = fixed_current_round["music_icon"]
        elif light_mode == 'ost':
            _progress_music_icon = "\U0001f3bc"   # 🎼
        else:
            _progress_music_icon = "\U0001f3b5"   # 🎵
        player = state.widgets.player
        _progress_img_overlay = player._p.create_image_overlay()
        progress_overlay   = True   # sentinel
        light_progress_bar = True   # sentinel checked externally (line ~14773)
        progress_bar_ready = True
        # Build the cached background layer and pre-render emoji before first draw
        try:
            _osd_w = player._p.osd_width
            _osd_h = player._p.osd_height
        except Exception:
            _osd_w, _osd_h = 0, 0
        if _osd_w and _osd_h:
            _rebuild_progress_bg_layer(_osd_w, _osd_h)
        # Draw one frame immediately, then start the 50 ms animation loop
        _progress_tick_gen += 1
        _redraw_progress_overlay()
        root = state.widgets.root
        root.after(50, _progress_overlay_tick, _progress_tick_gen)

def pulsate_music_icon(label, sizes=None, _step=None, _font="Arial", _interval=50):
    global pulse_step

    # Retry until the label exists
    if not label.winfo_exists():
        return  # Stop if truly gone

    root = state.widgets.root
    if not label.winfo_ismapped():
        root.after(100, pulsate_music_icon, label, sizes, _step, _font, _interval)  # Wait and retry
        return

    player = state.widgets.player
    if not player.is_playing():
        root.after(500, pulsate_music_icon, label, sizes, _step, _font, _interval)  # Check again later if paused
        return

    base_size, max_size = sizes if sizes is not None else _pulse_sizes
    speed = 0.5

    # Use a private step for non-global callers so shared pulse_step isn't double-incremented
    if sizes is not None:
        if _step is None:
            _step = [0.0]
        _step[0] += speed
        step_val = _step[0]
    else:
        pulse_step += speed
        step_val = pulse_step
        _step = None

    new_size = int(base_size + (math.sin(step_val) * (max_size - base_size) / 2))
    label.config(font=(_font, new_size))
    root.after(_interval, pulsate_music_icon, label, sizes, _step, _font, _interval)

