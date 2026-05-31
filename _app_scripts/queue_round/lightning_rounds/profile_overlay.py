"""Profile lightning-round overlay — renders a two-panel character
profile (left: word-by-word BIO; right: blurred → sharp character
image) inside a single inverse-palette box. Word count and image
countdown are driven by the lightning ticker via tick-by-tick
`toggle_character_profile_overlay(word_count=…, image_countdown=…)`
calls.

Extracted from `guess_the_anime.py`. The image source is always
`character_round_answer[1]` (this overlay only runs in character
rounds). Inverse palette colours are supplied by narrow callbacks;
`lightning_mode_settings` is read from `state.playback`.

``profile_overlay_window`` is the truthiness sentinel read by main's
lightning ticker. ``quick_destroy`` re-invokes the toggle with the last
seen word_count/image_countdown, so those two values persist in
module-level `_profile_last_*` vars.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageTk, ImageFilter

from core.game_state import state


# ---------------------------------------------------------------------------
# Module state — `profile_overlay_window` is read by main as a truthiness
# sentinel in the lightning ticker. The `_profile_last_*` pair stores the
# last-seen tick parameters so `quick_destroy` can re-render identically.
# ---------------------------------------------------------------------------
profile_overlay_window         = None   # sentinel — True when active, None when not
_profile_img_overlay           = None
_profile_last_word_count       = 0
_profile_last_image_countdown  = 15


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
_get_ass_font = None
_get_character_round_answer = lambda: None
_get_inverse_overlay_background_color = lambda: '#ffffff'
_get_inverse_overlay_text_color = lambda: '#000000'


def set_context(*, get_ass_font, get_character_round_answer,
                get_inverse_overlay_background_color, get_inverse_overlay_text_color):
    g = globals()
    g['_get_ass_font'] = get_ass_font
    g['_get_character_round_answer'] = get_character_round_answer
    g['_get_inverse_overlay_background_color'] = get_inverse_overlay_background_color
    g['_get_inverse_overlay_text_color'] = get_inverse_overlay_text_color


def toggle_character_profile_overlay(word_count=0, image_countdown=15, destroy=False, quick_destroy=False):
    """Displays a character profile with gender, a word-by-word BIO, and delayed image reveal."""
    global profile_overlay_window, _profile_img_overlay
    global _profile_last_word_count, _profile_last_image_countdown

    if destroy or quick_destroy:
        if _profile_img_overlay is not None:
            try:
                _profile_img_overlay.remove()
            except Exception:
                pass
            _profile_img_overlay = None
        profile_overlay_window = None
        if quick_destroy:
            toggle_character_profile_overlay(
                word_count=_profile_last_word_count,
                image_countdown=_profile_last_image_countdown,
            )
        return

    character_round_answer = _get_character_round_answer()
    if not character_round_answer:
        return

    lightning_mode_settings = state.playback.lightning_mode_settings
    INVERSE_OVERLAY_BACKGROUND_COLOR = _get_inverse_overlay_background_color()
    INVERSE_OVERLAY_TEXT_COLOR = _get_inverse_overlay_text_color()
    player = state.widgets.player
    root = state.widgets.root

    _profile_last_word_count = word_count
    _profile_last_image_countdown = image_countdown

    name, img, gender, desc = character_round_answer

    try:
        osd_w = player._p.osd_width  or 1920
        osd_h = player._p.osd_height or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080

    osd_mod = min(osd_w / 2560, osd_h / 1440)
    def ws(n): return max(1, int(n * osd_mod))

    # Font sizes: Tkinter used point sizes, PIL uses pixels.
    # Apply the same DPI conversion as synopsis/emoji headers so they match.
    _screen_dpi   = root.winfo_fpixels('1i')
    title_font_px = max(1, round(ws(60) * _screen_dpi / 72))
    body_font_px  = max(1, round(ws(50) * _screen_dpi / 72))

    # Colours — profile uses INVERSE palette
    try:
        r16, g16, b16 = root.winfo_rgb(INVERSE_OVERLAY_BACKGROUND_COLOR)
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
        r16, g16, b16 = root.winfo_rgb(INVERSE_OVERLAY_TEXT_COLOR)
        fg_r, fg_g, fg_b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        bg_r, bg_g, bg_b = 255, 255, 255
        fg_r, fg_g, fg_b = 0, 0, 0
    bg = (bg_r, bg_g, bg_b, round(0.95 * 255))   # alpha=0.95 matches Toplevel
    fg = (fg_r, fg_g, fg_b, 255)

    # Layout — exact ratios from Tkinter version
    width_percent = lightning_mode_settings.get("_misc_settings", {}).get("image_width_percent", 70) / 100
    target_w    = int(osd_w * width_percent)
    target_h    = int(osd_h * 0.7)
    border      = max(1, round(4 * osd_mod))   # highlightthickness=4
    outer_pad_x = ws(5)    # padx=5 on frames
    outer_pad_y = ws(10)   # pady=10 on frames
    inner_pad   = ws(10)   # padx=ws(10) on labels
    desc_w      = (target_w // 3) * 2   # left panel: 2/3 of total width
    img_panel_w = target_w - desc_w     # right panel: 1/3

    box_x = (osd_w - target_w) // 2
    box_y = (osd_h - target_h) // 2

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    # Background + border
    draw.rectangle([box_x, box_y, box_x + target_w, box_y + target_h], fill=bg)
    draw.rectangle([box_x, box_y, box_x + target_w, box_y + target_h],
                   outline=fg, width=border)

    title_font = _get_ass_font(title_font_px, bold=True)
    body_font  = _get_ass_font(body_font_px,  bold=False)

    # Left panel text origin (inside border + outer padding + label padding)
    text_x = box_x + outer_pad_x + inner_pad
    text_y = box_y + outer_pad_y + inner_pad

    # Wrap width: from text_x to the right edge of the desc panel minus a right margin
    wrap_w = (box_x + desc_w) - text_x - inner_pad

    # Title: "CHARACTER DESCRIPTION:" bold + underline
    title_bottom = text_y + title_font_px + inner_pad   # fallback if font missing
    if title_font:
        TITLE = "CHARACTER DESCRIPTION:"
        tb = draw.textbbox((0, 0), TITLE, font=title_font)
        draw.text((text_x - tb[0], text_y - tb[1]), TITLE, font=title_font, fill=fg)
        ul_gap = max(1, round(title_font_px * 0.05))
        ul_h   = max(2, round(title_font_px * 0.07))
        ul_y   = text_y - tb[1] + tb[3] + ul_gap
        draw.rectangle([text_x, ul_y, text_x + (tb[2] - tb[0]), ul_y + ul_h], fill=fg)
        title_bottom = ul_y + ul_h + inner_pad

    # Body: "Gender: X. [description]" — word-wrapped, up to word_count+2 words, max 11 lines
    full_text   = f"Gender: {gender.capitalize()}. {desc}"
    all_words   = full_text.split()
    limited     = all_words[:word_count + 2]
    max_lines   = 11

    if body_font and limited:
        # Measure space width by comparing "a b" vs "ab" to avoid zero-width issues
        _sp_bb  = draw.textbbox((0, 0), "a b", font=body_font)
        _ab_bb  = draw.textbbox((0, 0), "ab",  font=body_font)
        space_w = max(1, (_sp_bb[2] - _sp_bb[0]) - (_ab_bb[2] - _ab_bb[0]))

        lines     = []
        cur_words = []
        cur_w     = 0

        for word in limited:
            wbb    = draw.textbbox((0, 0), word, font=body_font)
            word_w = wbb[2] - wbb[0]
            test_w = cur_w + (space_w if cur_words else 0) + word_w
            if cur_words and test_w > wrap_w:
                lines.append(' '.join(cur_words))
                if len(lines) >= max_lines:
                    cur_words = []
                    break
                cur_words = [word]
                cur_w     = word_w
            else:
                cur_words.append(word)
                cur_w = test_w

        if cur_words and len(lines) < max_lines:
            lines.append(' '.join(cur_words))

        # If not all limited words were shown, add ellipsis to the last line
        shown_words = sum(len(l.split()) for l in lines)
        if shown_words < len(limited) and lines:
            last_words = lines[-1].split()
            for trim in range(len(last_words), 0, -1):
                candidate = ' '.join(last_words[:trim]) + '...'
                cbb = draw.textbbox((0, 0), candidate, font=body_font)
                if (cbb[2] - cbb[0]) <= wrap_w:
                    lines[-1] = candidate
                    break

        # Line height: cap height + ~15% leading to match Tk label spacing
        lhbb   = draw.textbbox((0, 0), "Ag", font=body_font)
        line_h = (lhbb[3] - lhbb[1]) + max(1, round(body_font_px * 0.15))

        cy = title_bottom
        for line in lines:
            lbb = draw.textbbox((0, 0), line, font=body_font)
            draw.text((text_x - lbb[0], cy - lbb[1]), line, font=body_font, fill=fg)
            cy += line_h

    # Right panel: character image — blurred when countdown > 0, sharp when 0
    pil_img = ImageTk.getimage(img).copy().convert("RGBA")
    max_img_w = img_panel_w - outer_pad_x * 2   # stay within right panel + padding
    max_img_h = target_h    - outer_pad_y * 2
    scale_w = max_img_w / pil_img.width
    scale_h = max_img_h / pil_img.height
    scale   = min(scale_w, scale_h)
    sc_w    = int(pil_img.width  * scale)
    sc_h    = int(pil_img.height * scale)
    sc_img  = pil_img.resize((sc_w, sc_h), Image.LANCZOS)

    if image_countdown > 0:
        display_img = sc_img.filter(ImageFilter.GaussianBlur(radius=100))
    else:
        display_img = sc_img

    # Centre image in right panel
    right_x = box_x + desc_w
    paste_x = right_x + (img_panel_w - sc_w) // 2
    paste_y = box_y   + (target_h   - sc_h) // 2
    canvas.paste(display_img, (paste_x, paste_y), display_img)

    if _profile_img_overlay is None:
        _profile_img_overlay = player._p.create_image_overlay()
    _profile_img_overlay.update(canvas)
    profile_overlay_window = True   # sentinel for game-loop guards
