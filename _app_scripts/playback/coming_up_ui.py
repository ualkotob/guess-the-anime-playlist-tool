"""
Coming-up popup OSD + skip-to-end / fast-forward-to-end UI.

Extracted from guess_the_anime.py "COMING UP UI" section. Owns its own ASS OSD
state and the small flash overlays; the *coming_up_queue* dict that holds a
queued popup lives in main (it is mutated by main's seek-bar ticker), so reads
and writes against it go through main_globals.
"""

import math
import time

from PIL import Image

from core.game_state import state


_get_ass_font = None
_ass_wrap_text = None
_osd_command = None
_color_str_to_ass_bgr = None
_seek_to = None
_main_globals = None


def set_context(*, get_ass_font, ass_wrap_text, osd_command,
                color_str_to_ass_bgr, seek_to, main_globals):
    global _get_ass_font, _ass_wrap_text, _osd_command
    global _color_str_to_ass_bgr, _seek_to, _main_globals
    _get_ass_font = get_ass_font
    _ass_wrap_text = ass_wrap_text
    _osd_command = osd_command
    _color_str_to_ass_bgr = color_str_to_ass_bgr
    _seek_to = seek_to
    _main_globals = main_globals


_COMING_UP_ASS_OSD_ID        = 80
_SKIP_TO_END_ASS_OSD_ID      = 81  # brief "SKIPPED TO END" flash overlay
_coming_up_osd_visible        = False
_coming_up_osd_current_title  = ""     # uppercased title currently displayed
_coming_up_img_overlay        = None   # mpv ImageOverlay for thumbnail
_coming_up_anim_after         = None   # root.after ID for slide-in animation
_coming_up_osd_box_h          = 0      # rendered box height in OSD px (for hide/resize)
_coming_up_osd_box_w          = 0      # rendered box width in OSD px
_coming_up_current_frame      = None   # (title_text, details, pil_image) of what is currently shown


def _coming_up_get_osd_dims():
    player = state.widgets.player
    try:
        return int(player._p.osd_width or 0), int(player._p.osd_height or 0)
    except Exception:
        return 0, 0


def _render_coming_up_frame(title_text, details, pil_image, y, osd_w, osd_h, alpha_frac=1.0):
    """Render one animation frame of the coming-up popup at OSD y position.

    alpha_frac: 0.0 = fully transparent, 1.0 = final opacity (background ≈80%, text 100%).
    Mirrors the original Tkinter layout: title (large, underlined) → optional thumbnail → details.
    *pil_image* must be a PIL RGBA Image or None.
    """
    global _coming_up_img_overlay, _coming_up_osd_box_h, _coming_up_osd_box_w, _coming_up_current_frame
    _coming_up_current_frame = (title_text, details, pil_image)

    player = state.widgets.player

    modifier = min(osd_w / 2560, osd_h / 1440)

    fs_title   = max(14, round(40 * modifier * 1.6))   # ≈ scl(40)
    fs_details = max(10, round(20 * modifier * 1.6))   # ≈ scl(20)

    pad_x  = max(8, round(osd_w * 0.010))
    pad_y  = max(6, round(osd_h * 0.012))
    gap    = max(4, round(fs_details * 0.3))
    margin = max(4, round(10 * modifier))

    def _measure_w(text_block, fs):
        fnt = _get_ass_font(fs)
        max_w = 0
        for line in text_block.split('\n'):
            if not line:
                continue
            try:
                w = round(fnt.getlength(line)) if fnt else round(len(line) * fs * 0.52)
            except AttributeError:
                w = fnt.getsize(line)[0] if fnt else round(len(line) * fs * 0.52)
            if w > max_w:
                max_w = w
        return max_w or fs

    def _line_h(fs, n):
        return round(n * fs * 1.0)

    # Cap box width at 65% of OSD width; pre-wrap title to fit so height is accurate
    max_box_w = min(round(osd_w * 0.65), osd_w - 2 * margin)
    title_wrap_max = max_box_w - 2 * pad_x

    title_wrapped = title_text
    if title_text:
        wrapped_title_lines = []
        for ln in title_text.split('\n'):
            if ln.strip():
                greedy = _ass_wrap_text(ln, fs_title, title_wrap_max)
                if len(greedy) > 1:
                    # Binary-search for the minimum wrap width that still fits in the same
                    # number of lines — this gives the most evenly balanced split.
                    n = len(greedy)
                    full_w = _measure_w(ln, fs_title)
                    lo = max(1, math.ceil(full_w / n))
                    hi = title_wrap_max
                    while lo < hi:
                        mid = (lo + hi) // 2
                        if len(_ass_wrap_text(ln, fs_title, mid)) <= n:
                            hi = mid
                        else:
                            lo = mid + 1
                    wrapped_title_lines.extend(_ass_wrap_text(ln, fs_title, lo))
                else:
                    wrapped_title_lines.extend(greedy)
            else:
                wrapped_title_lines.append('')
        title_wrapped = '\n'.join(wrapped_title_lines)

    # Wrap details preserving explicit newlines, word-wrapping each segment independently
    wrap_max = round(osd_w * 0.80)
    details_wrapped = details
    if details and details.strip():
        wrapped_lines = []
        for ln in details.split('\n'):
            if ln.strip():
                wrapped_lines.extend(_ass_wrap_text(ln, fs_details, wrap_max))
            else:
                wrapped_lines.append('')
        details_wrapped = '\n'.join(wrapped_lines)

    title_lines   = title_wrapped.count('\n') + 1    if title_wrapped                             else 0
    details_lines = details_wrapped.count('\n') + 1 if (details_wrapped and details_wrapped.strip()) else 0

    row_h_title   = _line_h(fs_title,   title_lines)   if title_lines   else 0
    row_h_details = _line_h(fs_details, details_lines) if details_lines else 0

    img_w_osd = round(400 * modifier) if pil_image else 0
    img_h_osd = round(225 * modifier) if pil_image else 0

    inner_h = (row_h_title
               + (gap if title_lines  and (pil_image or details_lines) else 0)
               + img_h_osd
               + (gap if pil_image    and details_lines                else 0)
               + row_h_details)
    box_h = inner_h + 2 * pad_y

    widths = []
    if title_wrapped:                                widths.append(_measure_w(title_wrapped,   fs_title))
    if details_wrapped and details_wrapped.strip():  widths.append(_measure_w(details_wrapped, fs_details))
    if pil_image:                                    widths.append(img_w_osd)
    box_w = (round(max(widths) * 0.91) if widths else fs_title) + 2 * pad_x
    box_w = min(box_w, max_box_w)

    _coming_up_osd_box_h = box_h
    _coming_up_osd_box_w = box_w

    bx = (osd_w - box_w) // 2
    by = y
    cx = osd_w // 2

    bg_bgr = _color_str_to_ass_bgr(_main_globals['OVERLAY_BACKGROUND_COLOR'])
    fg_bgr = _color_str_to_ass_bgr(_main_globals['OVERLAY_TEXT_COLOR'])

    # ASS alpha: 0x00=opaque, 0xFF=transparent.
    # Background target: 0x33 ≈ 80% opaque, matching the original -alpha 0.8.
    bg_ass_alpha = max(0, min(255, round(0x33 + (255 - 0x33) * (1.0 - alpha_frac))))
    fg_ass_alpha = max(0, min(255, round(255 * (1.0 - alpha_frac))))
    bg_alpha_hex = f"{bg_ass_alpha:02X}"
    fg_alpha_hex = f"{fg_ass_alpha:02X}"

    def _esc(text):
        return text.replace('{', '').replace('}', '').replace('\n', r'\N')

    events = []

    # Background rectangle
    events.append(
        f"{{\\an7\\pos({bx},{by})"
        f"\\1c&H{bg_bgr}&\\1a&H{bg_alpha_hex}&\\bord0\\shad0\\p1}}"
        f"m 0 0 l {box_w} 0 {box_w} {box_h} 0 {box_h}{{\\p0}}"
    )

    ty = by + pad_y
    _title_tags  = "\\bord0\\shad0\\b1\\q2\\u1"
    _detail_tags = "\\bord0\\shad0\\b1\\q2"

    if title_lines:
        events.append(
            f"{{\\an8\\pos({cx},{ty})"
            f"\\1c&H{fg_bgr}&\\1a&H{fg_alpha_hex}&{_title_tags}"
            f"\\fs{fs_title}}}{_esc(title_wrapped)}"
        )
        ty += row_h_title + gap

    img_top_y = ty   # OSD y where the thumbnail will be pasted (for PIL overlay)
    if pil_image:
        ty += img_h_osd + gap

    if details_lines:
        events.append(
            f"{{\\an8\\pos({cx},{ty})"
            f"\\1c&H{fg_bgr}&\\1a&H{fg_alpha_hex}&{_detail_tags}"
            f"\\fs{fs_details}}}{_esc(details_wrapped)}"
        )

    try:
        _osd_command('osd-overlay', _COMING_UP_ASS_OSD_ID, 'ass-events',
                     "\n".join(events), osd_w, osd_h, 3, 'no')
    except Exception as e:
        print(f"Coming-up OSD error: {e}")

    # PIL image overlay for thumbnail (layered on top of the ASS background)
    if pil_image is not None:
        try:
            canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
            img_x  = bx + (box_w - img_w_osd) // 2
            img_y  = img_top_y
            scaled = (pil_image.resize((img_w_osd, img_h_osd), Image.LANCZOS)
                      if pil_image.size != (img_w_osd, img_h_osd) else pil_image.copy())
            if alpha_frac < 1.0:
                r, g, b, a = scaled.split()
                a = a.point(lambda px: int(px * alpha_frac))
                scaled = Image.merge("RGBA", (r, g, b, a))
            # Clip if the box is still sliding in from off the top
            src, paste_x, paste_y = scaled, img_x, img_y
            if paste_y < 0:
                crop_top = -paste_y
                if crop_top < img_h_osd:
                    src      = scaled.crop((0, crop_top, img_w_osd, img_h_osd))
                    paste_y  = 0
                else:
                    src = None
            if src is not None:
                canvas.paste(src, (paste_x, paste_y), src)
            if _coming_up_img_overlay is None:
                _coming_up_img_overlay = player._p.create_image_overlay()
            _coming_up_img_overlay.update(canvas)
        except Exception as e:
            print(f"Coming-up image OSD error: {e}")
    elif _coming_up_img_overlay is not None:
        try:
            _coming_up_img_overlay.remove()
        except Exception:
            pass
        _coming_up_img_overlay = None


_skip_to_end_after = None  # root.after handle for the skip-to-end flash animation

def show_skip_to_end_osd():
    """Show a brief centered 'SKIPPED TO END' ASS overlay that fades out."""
    global _skip_to_end_after
    player = state.widgets.player
    root = state.widgets.root
    if _skip_to_end_after is not None:
        try:
            root.after_cancel(_skip_to_end_after)
        except Exception:
            pass
        _skip_to_end_after = None

    HOLD_MS  = 1400   # time fully visible
    FADE_MS  = 500    # fade-out duration
    STEPS    = 20

    def _render(alpha_frac):
        try:
            osd_w = int(player._p.osd_width  or 0) or 1920
            osd_h = int(player._p.osd_height or 0) or 1080
            modifier = min(osd_w / 2560, osd_h / 1440)
            fs = max(18, round(52 * modifier * 1.6))
            cx, cy = osd_w // 2, osd_h // 2

            label = "⏭ SKIPPED TO END"
            fnt = _get_ass_font(fs)
            try:
                text_w = round(fnt.getlength(label)) if fnt else round(len(label) * fs * 0.55)
            except AttributeError:
                text_w = fnt.getsize(label)[0] if fnt else round(len(label) * fs * 0.55)

            pad_x = max(10, round(fs * 0.55))
            pad_y = max(6,  round(fs * 0.30))
            line_h = round(fs * 1.15)
            box_w  = text_w + 2 * pad_x
            box_h  = line_h + 2 * pad_y
            bx = cx - box_w // 2
            by = cy - box_h // 2

            # Blue palette — dark navy fill, bright-blue border, white text
            # ASS colors are &HBBGGRR& (little-endian BGR)
            bg_bgr     = "3A1A0D"   # #0D1A3A dark navy
            border_bgr = "AA6633"   # #3366AA medium blue
            text_bgr   = "FFFFFF"   # white

            bg_a     = max(0, min(255, round(0x1A + (255 - 0x1A) * (1.0 - alpha_frac))))  # nearly opaque
            border_a = max(0, min(255, round(255 * (1.0 - alpha_frac))))
            text_a   = border_a
            bg_ah     = f"{bg_a:02X}"
            border_ah = f"{border_a:02X}"
            text_ah   = f"{text_a:02X}"

            bord_w = max(2, round(3 * modifier * 1.6))

            events = [
                # Background fill + blue border using drawing mode
                f"{{\\an7\\pos({bx},{by})"
                f"\\1c&H{bg_bgr}&\\1a&H{bg_ah}&"
                f"\\3c&H{border_bgr}&\\3a&H{border_ah}&"
                f"\\bord{bord_w}\\shad0\\p1}}"
                f"m 0 0 l {box_w} 0 {box_w} {box_h} 0 {box_h}{{\\p0}}",
                # Text — white, dark outline for readability
                f"{{\\an5\\pos({cx},{cy})"
                f"\\1c&H{text_bgr}&\\1a&H{text_ah}&"
                f"\\3c&H{border_bgr}&\\3a&H{border_ah}&"
                f"\\bord{bord_w}\\shad0\\b1\\fs{fs}}}{label}",
            ]
            _osd_command('osd-overlay', _SKIP_TO_END_ASS_OSD_ID, 'ass-events',
                         "\n".join(events), osd_w, osd_h, 3, 'no')
        except Exception as e:
            print(f"Skip-to-end OSD error: {e}")

    def _clear():
        global _skip_to_end_after
        _skip_to_end_after = None
        try:
            _osd_command('osd-overlay', _SKIP_TO_END_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass

    def _fade(step):
        global _skip_to_end_after
        if step > STEPS:
            _clear()
            return
        alpha = 1.0 - (step / STEPS)
        _render(alpha)
        _skip_to_end_after = root.after(FADE_MS // STEPS, lambda s=step+1: _fade(s))

    _render(1.0)
    _skip_to_end_after = root.after(HOLD_MS, lambda: _fade(0))


_ff_to_end_after = None   # root.after handle for fast-forward polling

def fast_forward_to_end(speed=4, ff_ms=500):
    """Play at `speed`x for `ff_ms` milliseconds for a visual FF effect,
    then seek directly to 3 seconds before the end and restore normal rate."""
    global _ff_to_end_after
    player = state.widgets.player
    root = state.widgets.root
    currently_playing = _main_globals['currently_playing']
    length_ms = player.get_length()
    if length_ms <= 3000:
        return
    # Cancel any existing FF session
    if _ff_to_end_after is not None:
        try:
            root.after_cancel(_ff_to_end_after)
        except Exception:
            pass
        _ff_to_end_after = None
    filename_at_start = currently_playing.get("filename")
    normal_rate = _main_globals['light_speed_modifier']  # preserve lightning-round rate
    player.set_rate(speed)
    show_skip_to_end_osd()

    def _finish():
        global _ff_to_end_after
        _ff_to_end_after = None
        if currently_playing.get("filename") != filename_at_start:
            return
        player.set_rate(normal_rate)
        cur_length_ms = player.get_length()
        if cur_length_ms > 3000:
            _seek_to(cur_length_ms - 3000)
        # root.after(0, show_skip_to_end_osd)

    _ff_to_end_after = root.after(ff_ms, _finish)


def _hide_coming_up_osd():
    """Immediately clear the coming-up ASS overlay and PIL image overlay."""
    global _coming_up_osd_visible, _coming_up_osd_current_title
    global _coming_up_img_overlay, _coming_up_anim_after
    root = state.widgets.root
    if _coming_up_anim_after is not None:
        try:
            root.after_cancel(_coming_up_anim_after)
        except Exception:
            pass
        _coming_up_anim_after = None
    try:
        _osd_command('osd-overlay', _COMING_UP_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
    except Exception:
        pass
    if _coming_up_img_overlay is not None:
        try:
            _coming_up_img_overlay.remove()
        except Exception:
            pass
        _coming_up_img_overlay = None
    _coming_up_osd_visible       = False
    _coming_up_osd_current_title = ""


def toggle_coming_up_popup(show, title="", details="", image=None, up_next=True, queue=False):
    """Creates or destroys the lightning round announcement popup (OSD-based).

    *image* must be a PIL RGBA Image or None — callers pass the PIL image directly,
    not an ImageTk.PhotoImage.
    """
    global _coming_up_osd_current_title, _coming_up_anim_after
    player = state.widgets.player
    root = state.widgets.root

    if not show:
        if _coming_up_osd_visible:
            if title == "" or (title and title.lower() in _coming_up_osd_current_title.lower()):
                _hide_coming_up_osd()
        coming_up_queue = _main_globals.get('coming_up_queue')
        if coming_up_queue:
            if title in coming_up_queue["title"]:
                _main_globals['coming_up_queue'] = None
        return

    if queue and player.is_playing():
        _main_globals['coming_up_queue'] = {
            "title":   title,
            "details": details,
            "image":   image,
            "up_next": up_next,
        }
        return

    title_text = ("UP NEXT: " + title.upper() + "!") if up_next else title.upper()
    if title_text == _coming_up_osd_current_title:
        return

    # Cancel any in-progress slide-in; clear whatever is currently shown
    if _coming_up_anim_after is not None:
        try:
            root.after_cancel(_coming_up_anim_after)
        except Exception:
            pass
        _coming_up_anim_after = None
    if _coming_up_osd_visible:
        _hide_coming_up_osd()

    osd_w, osd_h = _coming_up_get_osd_dims()
    if not osd_w or not osd_h:
        return

    _coming_up_osd_current_title = title_text

    # Pre-render off-screen to populate _coming_up_osd_box_h before the animation starts
    _render_coming_up_frame(title_text, details, image, -9999, osd_w, osd_h, 0.0)
    box_h = _coming_up_osd_box_h
    if not box_h:
        return

    target_y = max(4, round(osd_h * 0.014))  # ≈20 px at 1440p, matches original y=20

    # Slide-in animation: time-based, ~100 ms duration
    duration = 0.10   # seconds
    poll     = 5      # ms between frames
    t0 = time.perf_counter()

    def _slide_step():
        global _coming_up_anim_after, _coming_up_osd_visible
        t = min((time.perf_counter() - t0) / duration, 1.0)
        bounce = math.sin(t * math.pi) * 5 if t > 0.7 else 0
        y = int(-box_h + (target_y + box_h) * t + bounce)
        _render_coming_up_frame(title_text, details, image, y, osd_w, osd_h, t)
        if t < 1.0:
            _coming_up_anim_after = root.after(poll, _slide_step)
        else:
            _coming_up_osd_visible = True
            _coming_up_anim_after  = None

    root.after(10, _slide_step)
