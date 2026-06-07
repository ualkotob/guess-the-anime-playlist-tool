"""Filter-peek renderer — applies an mpv `vf` (libavfilter) chain that
covers/distorts the video for the blur/outline/pixelize/wave/zoom peek
variants. Intensity fades to 0 (filter removed) as the round progresses.

Extracted from `guess_the_anime.py`. The toggle owns the vf chain and the
on-screen intensity label; the dispatch that *selects* a peek variant
(``_activate_peek_variant``) still lives in main because it also routes
to the edge/grow/slice renderers.

Module-level state (`filter_vf_active`, `_filter_vf_variant`, …) is
read/written externally — main qualifies as `filter_overlay.<name>`.
The mutable boxes (`_filter_vf_last_progress`, `_filter_zoom_offset`)
are shared by reference, so list-index writes from main mutate the same
underlying objects without needing module qualification.
"""
from __future__ import annotations

from core.game_state import state
from _app_scripts.playback import osd_text


# ---------------------------------------------------------------------------
# Module state — `filter_vf_active` is the truthiness sentinel read by main
# in ~15 places (popout toggles, lightning ticker, zoom-drag loop). The
# `_filter_vf_last_progress` / `_filter_zoom_offset` boxes are shared by
# reference so list-index writes from main mutate the same objects.
# ---------------------------------------------------------------------------
filter_vf_active        = False    # True while a vf filter peek variant is running
_filter_vf_variant      = None     # which filter variant is active ('blur', 'pixelize', 'zoom', ...)
_filter_vf_last         = None     # last vf string sent — skip redundant mpv calls
_filter_vf_last_progress = [0.0]   # mutable box so widen/narrow can read/write current progress
_filter_zoom_offset     = [0.0, 0.0]  # [ox, oy] crop centre offset in [-0.5, 0.5] for zoom_filter


def get_zoom_state():
    """Return (zoom_factor, offset_x, offset_y) while a zoom filter is visibly
    magnifying the frame (factor > 1.005), else None.  Read by censors to keep
    censor boxes tracking the zoomed video."""
    if filter_vf_active and _filter_vf_variant == 'zoom':
        z = round(1 + 14 * (1 - _filter_vf_last_progress[0]), 4)
        if z > 1.005:
            return (z, _filter_zoom_offset[0], _filter_zoom_offset[1])
    return None


def get_filter_state():
    """Return (variant, progress) while any vf filter peek is active, else None."""
    if filter_vf_active:
        return (_filter_vf_variant, _filter_vf_last_progress[0])
    return None


def _filter_intensity_label(variant, progress):
    """Return a human-readable intensity label for the current filter peek variant."""
    intensity = round((1.0 - progress) * 100)
    if variant == 'blur':
        return f"BLUR: {intensity}%"
    elif variant == 'outline':
        return f"OUTLINE: {intensity}%"
    elif variant == 'pixelize':
        return f"PIXELIZE: {intensity}%"
    elif variant == 'wave':
        return f"WAVE: {intensity}%"
    elif variant == 'zoom':
        return f"ZOOM: {intensity}%"
    return variant.upper()


def _update_filter_intensity_bottom_label(variant, progress):
    lightning_mode_settings = state.playback.lightning_mode_settings
    _bottom_font_size = 80 if lightning_mode_settings.get("_misc_settings", {}).get("framed_video") else 40
    osd_text.bottom_info(_filter_intensity_label(variant, progress),
                 size=_bottom_font_size,
                 inverse=state.lightning.character_round_answer)


def toggle_filter_vf(variant=None, progress=0, destroy=False):
    """Apply or remove the vf filter for filter-peek variants.
    variant: 'blur' | 'pixelize'
    progress: 0.0 (start, max filter) → 1.0 (end, no filter)
    destroy: clear the filter immediately.
    """
    global filter_vf_active, _filter_vf_variant, _filter_vf_last
    player = state.widgets.player
    if destroy:
        filter_vf_active = False
        _filter_vf_variant = None
        _filter_vf_last = None
        _filter_vf_last_progress[0] = 0.0
        _filter_zoom_offset[0] = 0.0
        _filter_zoom_offset[1] = 0.0
        osd_text.bottom_info()  # clear blur/pixelize/zoom intensity label
        try:
            player._p.command('vf', 'set', '')
        except Exception:
            pass
        return
    progress = min(max(progress, 0.0), 1.0)
    _filter_vf_last_progress[0] = progress
    vf_str = ''
    if variant == 'blur':
        # Use avgblur (sliding-window box blur) instead of gblur (IIR Gaussian).
        # avgblur clips radius to the frame dimension, so no crash on any video size.
        # format=yuv420p inside lavfi normalises VP8/WebM frame format before the filter.
        # Radius 200 at progress=0 gives strong blur visually comparable to gblur sigma=120.
        radius = max(1, round(200 * (1 - progress)))
        if radius >= 1:
            vf_str = f'lavfi=[format=yuv420p,avgblur=sizeX={radius}:sizeY={radius}]'
    elif variant == 'pixelize':
        divisor = max(1, round(80 * (1 - progress)))
        if divisor > 1:
            vf_str = f'lavfi=[scale=iw/{divisor}:ih/{divisor}:flags=neighbor,scale=iw*{divisor}:ih*{divisor}:flags=neighbor]'
    elif variant == 'outline':
        # Edge-detect: high threshold controls how many edges show
        # progress=0 → high=0.99 (only boldest edges, sparsest outline)
        # progress=1 → high=0.01 (maximum edges, densest outline)
        high = round(max(0.01, 0.99 - 0.98 * progress), 4)
        vf_str = f'lavfi=[edgedetect=low=0.005:high={high},negate]'
    elif variant == 'wave':
        # Sine-wave spatial warp using geq: large amplitude (progress=0) → flat (progress=1)
        # format=gbrp forces RGB so r()/g()/b() pixel access works correctly
        amp = round(150 * (1 - progress))  # 150px → 0
        if amp > 0:
            expr = f"r(X+{amp}*sin(6.28318*Y/80),Y)"
            vf_str = f"lavfi=[format=gbrp,geq=r='{expr}':g='{expr.replace('r(','g(')}':b='{expr.replace('r(','b(')}',format=yuv420p]"
        else:
            vf_str = ''
    elif variant == 'zoom':
        z = round(1 + 14 * (1 - progress), 4)  # 15x zoomed in → 1.0x (full frame)
        if z > 1.005:
            ox, oy = _filter_zoom_offset
            # ox/oy in [-0.5, 0.5] — shift crop within the spare space (iw - iw/z)
            crop_w = f'iw/{z}'
            crop_h = f'ih/{z}'
            cx_expr = f'(iw-iw/{z})*(0.5+{round(ox, 4)})'
            cy_expr = f'(ih-ih/{z})*(0.5+{round(oy, 4)})'
            vf_str = f'lavfi=[crop={crop_w}:{crop_h}:{cx_expr}:{cy_expr},scale=iw*{z}:ih*{z}]'
    if vf_str == _filter_vf_last:
        return
    _filter_vf_last = vf_str
    if not vf_str:
        try:
            player._p.command('vf', 'set', '')
        except Exception:
            pass
        return
    # Choose prefix based on whether hardware decoding is actually active right now.
    # hwdownload is required before lavfi filters when hwdec is on (GPU frames can't
    # be processed by software filters).  Using hwdownload with software frames causes
    # a crash at render time (not at command time, so try/except can't catch it).
    _hwdec_cur = ''
    try:
        _hwdec_cur = player._p.hwdec_current or ''
        if isinstance(_hwdec_cur, list):
            _hwdec_cur = _hwdec_cur[0] if _hwdec_cur else ''
    except Exception:
        pass
    _is_hw = str(_hwdec_cur).strip().lower() not in ('', 'no', 'none', 'auto', 'auto-safe')
    _prefix = 'hwdownload,format=yuv420p,' if _is_hw else ''
    try:
        player._p.command('vf', 'set', _prefix + vf_str)
    except Exception as e:
        print(f"[vf] error setting filter '{_prefix + vf_str}': {e}", flush=True)
