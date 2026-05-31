"""Title lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders the masked anime title (or
character name) with per-letter reveal via a PIL image overlay on top
of the mpv video.

Also exposes title-related helpers (`_title_colors`, `_title_wrap_lines`,
`get_base_title`, `get_unique_letters`, `get_title_light_string`,
`get_next_title_mode`) that the SCRAMBLE / SWAP / PEEK overlays still
rely on — main re-aliases them so those modules continue to find them.

``title_overlay_window`` is the rebound sentinel (truthy when active,
None otherwise). Main reads it via
``title_overlay.title_overlay_window`` so it always sees the
module-current value rather than a stale alias.
"""
from __future__ import annotations

import random

from PIL import Image, ImageDraw

from core.game_state import state


# ---------------------------------------------------------------------------
# Module state — `title_overlay_window` is externally read by main as a
# sentinel via `title_overlay.title_overlay_window`.
# ---------------------------------------------------------------------------
available_title_modes: list = []
last_title_mode = ""

title_overlay_window = None      # sentinel — True when active
_title_img_overlay = None        # mpv image overlay object
_title_osd_size = (0, 0)         # (osd_w, osd_h) at last build
_title_base_img = None           # PIL RGBA image with box + underscores but no letters
_title_letter_pos: list = []     # (cx, cy) OSD coords for each non-space char slot
_title_revealed: list = []       # revealed char or '' for each slot


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
currently_playing: dict = {}
_scl = None
_get_title_text_lines = None
_get_mpv_window_rect = None
_get_ass_font = None
_get_courier_font = None
_get_title_light_string_value = lambda: ""
_get_title_light_letters = lambda: []
_get_character_round_answer = lambda: None
_get_overlay_background_color = lambda: 'black'
_get_overlay_text_color = lambda: 'white'
_get_inverse_overlay_background_color = lambda: 'white'
_get_inverse_overlay_text_color = lambda: 'black'


def set_context(*, currently_playing, scl, get_title_text_lines,
                get_mpv_window_rect, get_ass_font, get_courier_font,
                get_title_light_string_value, get_title_light_letters,
                get_character_round_answer, get_overlay_background_color,
                get_overlay_text_color, get_inverse_overlay_background_color,
                get_inverse_overlay_text_color):
    g = globals()
    g['currently_playing'] = currently_playing
    g['_scl'] = scl
    g['_get_title_text_lines'] = get_title_text_lines
    g['_get_mpv_window_rect'] = get_mpv_window_rect
    g['_get_ass_font'] = get_ass_font
    g['_get_courier_font'] = get_courier_font
    g['_get_title_light_string_value'] = get_title_light_string_value
    g['_get_title_light_letters'] = get_title_light_letters
    g['_get_character_round_answer'] = get_character_round_answer
    g['_get_overlay_background_color'] = get_overlay_background_color
    g['_get_overlay_text_color'] = get_overlay_text_color
    g['_get_inverse_overlay_background_color'] = get_inverse_overlay_background_color
    g['_get_inverse_overlay_text_color'] = get_inverse_overlay_text_color


# ---------------------------------------------------------------------------
# Variant picker
# ---------------------------------------------------------------------------
def get_next_title_mode(title_text):
    global available_title_modes, last_title_mode

    root = state.widgets.root
    lightning_mode_settings = state.playback.lightning_mode_settings

    all_variants = []
    available_variants = []
    for variant, enabled in lightning_mode_settings.get("title", {}).get("variants", {}).items():
        all_variants.append(variant)
        if enabled:
            available_variants.append(variant)
    available_variants = available_variants or all_variants

    allowed_modes = []
    all_variants = []
    available_variants = []
    for variant, enabled in lightning_mode_settings.get("title", {}).get("variants", {}).items():
        all_variants.append(variant)
        if enabled:
            available_variants.append(variant)
    available_variants = available_variants or all_variants

    if not available_title_modes:
        shuffled = random.sample(available_variants, k=len(available_variants))
        if len(shuffled) > 1 and shuffled[0] == last_title_mode:
            # Move last_title_mode to the end
            shuffled = shuffled[1:] + [shuffled[0]]
        available_title_modes = shuffled

    def get_line_count():
        screen_width = root.winfo_screenwidth()
        max_width = screen_width * 0.7 - _scl(40)
        lines = _get_title_text_lines(title_text, max_width, font=("Courier New", _scl(80), "bold"))
        return len(lines)

    def get_long_word_count(length=5):
        total = 0
        for word in title_text.split(" "):
            if len(word) >= length:
                total += 1
        return total

    allowed_modes = []
    if get_line_count() <= 2:
        allowed_modes.append("scramble")
    if len(get_unique_letters(get_base_title())) >= 7:
        allowed_modes.append("reveal")
    if get_long_word_count(6):
        allowed_modes.append("swap")

    allowed_in_queue = [m for m in available_title_modes if m in allowed_modes]
    if allowed_in_queue:
        # Strictly only pick from allowed variants
        non_repeat = [m for m in allowed_in_queue if m != last_title_mode]
        if non_repeat:
            mode = non_repeat[0]
        else:
            mode = allowed_in_queue[0]
        if mode in available_title_modes:
            available_title_modes.remove(mode)
        last_title_mode = mode
        return mode
    # If no allowed variants at all, only then pick from the rest
    if not allowed_modes:
        if available_title_modes:
            mode = available_title_modes.pop(0)
            last_title_mode = mode
            return mode
        # Should never happen, but fallback to a random variant
        mode = random.choice(available_variants)
        last_title_mode = mode
        return mode
    # If there are allowed_modes but none are in the queue, reshuffle queue to try again
    available_title_modes[:] = random.sample(
        [m for m in available_variants if m in allowed_modes],
        k=len([m for m in available_variants if m in allowed_modes]),
    )
    # Try again recursively (should always succeed now)
    return get_next_title_mode(title_text)


# ---------------------------------------------------------------------------
# Title helpers — also consumed by SCRAMBLE / SWAP / PEEK overlays via
# main-side aliases.
# ---------------------------------------------------------------------------
def get_unique_letters(title):
    letters = []
    for letter in title:
        if letter != " " and letter.lower() not in letters:
            letters.append(letter.lower())
    return letters


def get_title_light_string(letters=0):
    title_light_string = _get_title_light_string_value() or ""
    title_light_letters = _get_title_light_letters() or []
    revealed_title = ""
    for letter in title_light_string:
        if letter != " ":
            new_letter = "ˍ"
            for l in range(min(len(title_light_letters), letters)):
                if title_light_letters[l] == letter.lower():
                    new_letter = letter
                    continue
            revealed_title = revealed_title + new_letter
        else:
            revealed_title = revealed_title + letter

    return revealed_title


def get_base_title(data=None, title=None):
    if not title:
        cra = _get_character_round_answer()
        if cra:
            return cra[0]
        if not data:
            data = currently_playing.get("data", {})
        if data:
            title = data.get('eng_title') or data.get("title") or ""
        else:
            title = ""
    # Remove common season/series/part suffixes
    for p in [': ', ' ']:
        for s in ['Season', 'Series', 'Part']:
            for n in ['0','1','2','3','4','5','6','7','8','9','III','II','IV','I','VIIII','VIII','VII','VI','V','X']:
                title = title.replace(f"{p}{s} {n}", "")
    for p in [': ', ' ']:
        for t in ['The ', '']:
            for n in ['First','Second','Third','Fourth','Fifth','1st','2nd','3rd','4th','5th','6th','Final']:
                for s in ['Season', 'Series', 'Part']:
                    title = title.replace(f"{p}{t}{n} {s}", "")
    return title or ""


def _title_colors():
    """Return (bg_rgba, fg_rgba) tuples based on current overlay color settings."""
    root = state.widgets.root
    cra = _get_character_round_answer()
    try:
        bg_key = _get_overlay_background_color() if not cra else _get_inverse_overlay_background_color()
        r, g, b = [v >> 8 for v in root.winfo_rgb(bg_key)]
        bg = (r, g, b, 217)
    except Exception:
        bg = (0, 0, 0, 217) if not cra else (255, 255, 255, 217)
    try:
        fg_key = _get_overlay_text_color() if not cra else _get_inverse_overlay_text_color()
        r, g, b = [v >> 8 for v in root.winfo_rgb(fg_key)]
        fg = (r, g, b, 255)
    except Exception:
        fg = (255, 255, 255, 255) if not cra else (0, 0, 0, 255)
    return bg, fg


def _title_wrap_lines(text, max_w_px, pil_font):
    """Word-wrap *text* into lines that fit within *max_w_px* using PIL font measurement."""
    if pil_font is None:
        # fallback: never wrap
        return [text]
    _draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    words = text.split(" ")
    lines = []
    cur = ""
    for word in words:
        test = (cur + " " + word).strip()
        bb = _draw.textbbox((0, 0), test, font=pil_font)
        if bb[2] - bb[0] <= max_w_px or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [text]


# ---------------------------------------------------------------------------
# Base frame build + toggle
# ---------------------------------------------------------------------------
def _build_title_base(title_text):
    """Build the static PIL frame (box + header + underscore slots). Returns (img, letter_positions, ltr_font, (osd_w, osd_h))."""
    player = state.widgets.player
    root = state.widgets.root
    cra = _get_character_round_answer()
    try:
        osd_w = int(player._p.osd_width  or 0) or 1920
        osd_h = int(player._p.osd_height or 0) or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080

    mod = min(osd_w / 2560, osd_h / 1440)
    def ws(n): return max(1, int(n * mod))

    # Use physical window mod for font sizing (matches song/synopsis approach)
    _mx, _my, mw_phys, mh_phys = _get_mpv_window_rect()
    if not mw_phys:
        mw_phys, mh_phys = osd_w, osd_h
    phys_mod = min(mw_phys / 2560, mh_phys / 1440)
    screen_dpi = root.winfo_fpixels('1i')
    # Font pixel sizes for PIL (physical → DPI → OSD space)
    hdr_fs  = max(1, round(max(1, int(70 * phys_mod)) * screen_dpi / 72))   # header "TITLE:"
    ltr_fs  = max(1, round(max(1, int(80 * phys_mod)) * screen_dpi / 72))   # big letter (Courier)
    us_fs   = max(1, round(max(1, int(65 * phys_mod)) * screen_dpi / 72))   # underscore (Courier)
    _ = us_fs  # reserved (underline drawn as rectangle below)

    hdr_font = _get_ass_font(hdr_fs, bold=True)
    ltr_font = _get_courier_font(ltr_fs)

    bg, fg = _title_colors()
    border = ws(4)

    # Line-wrap using PIL font measurement (consistent with OSD coords)
    spacing = ws(64)
    overlay_w = round(osd_w * 0.7)

    lines = _title_wrap_lines(title_text, overlay_w - ws(40), ltr_font)

    overlay_h = len(lines) * ws(100) + ws(320)
    bx = (osd_w - overlay_w) // 2
    by = (osd_h - overlay_h) // 2

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    # Box background + border
    draw.rectangle([bx, by, bx + overlay_w, by + overlay_h], fill=bg)
    draw.rectangle([bx, by, bx + overlay_w, by + overlay_h], outline=fg, width=border)

    # Header "TITLE:" / "CHARACTER NAME:" with underline under text only
    title_txt = "CHARACTER NAME:" if cra else "TITLE:"
    if hdr_font:
        hx = bx + ws(30)
        hy = by + ws(30)
        hb = draw.textbbox((hx, hy), title_txt, font=hdr_font, anchor="lt")
        draw.text((hx, hy), title_txt, font=hdr_font, fill=fg, anchor="lt")
        # Underline spans text width only (matches Tkinter 'underline' font style)
        ul_y = hb[3] + max(2, ws(6))
        draw.rectangle([hb[0], ul_y, hb[2], ul_y + max(4, ws(10))], fill=fg)

    # Underscore slots + record letter positions
    letter_positions = []
    line_y = by + ws(270)  # vertical centre of the first letter row
    for line in lines:
        chars = list(line)
        total_w = len(chars) * spacing
        line_x = osd_w // 2 - total_w // 2 + spacing // 2
        for ch in chars:
            if ch == " ":
                line_x += spacing
                continue
            cx = line_x
            cy = line_y
            # Draw a thin underline rule instead of the '_' glyph (glyph is too thick)
            ul_w = spacing - ws(6)
            ul_h = max(1, ws(2))
            draw.rectangle([cx - ul_w // 2, cy + ws(36), cx - ul_w // 2 + ul_w, cy + ws(36) + ul_h], fill=fg)
            letter_positions.append((cx, cy))
            line_x += spacing
        line_y += ws(100)

    return canvas, letter_positions, ltr_font, (osd_w, osd_h)


def toggle_title_overlay(title_text=None, destroy=False):
    """mpv PIL image overlay — masked anime title with per-letter reveal."""
    global title_overlay_window, _title_img_overlay, _title_osd_size
    global _title_base_img, _title_letter_pos, _title_revealed

    player = state.widgets.player
    root = state.widgets.root

    if destroy:
        title_overlay_window = None
        _title_base_img = None
        _title_letter_pos = []
        _title_revealed = []
        _title_osd_size = (0, 0)
        if _title_img_overlay is not None:
            try:
                _title_img_overlay.remove()
            except Exception:
                pass
            _title_img_overlay = None
        return

    if not title_text:
        return

    # Get current OSD size; rebuild base if it changed or is absent
    try:
        osd_w = int(player._p.osd_width  or 0) or 1920
        osd_h = int(player._p.osd_height or 0) or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080

    if _title_img_overlay is None or _title_osd_size != (osd_w, osd_h) or _title_base_img is None:
        _title_base_img, _title_letter_pos, _ltr_font, _title_osd_size = _build_title_base(title_text)
        _title_revealed = [""] * len(_title_letter_pos)
        if _title_img_overlay is None:
            _title_img_overlay = player._p.create_image_overlay()
        title_overlay_window = True  # sentinel

    # Determine which letters should now be visible from title_text
    flat_chars = [c for c in title_text if c != " "]
    new_revealed = []
    for i, ch in enumerate(flat_chars):
        new_revealed.append("" if ch == "ˍ" else ch)
    # Pad/trim to slot count
    while len(new_revealed) < len(_title_letter_pos):
        new_revealed.append("")
    new_revealed = new_revealed[:len(_title_letter_pos)]

    if new_revealed == _title_revealed:
        return  # nothing changed — skip redraw

    _title_revealed = new_revealed

    # Composite letters onto a copy of the base image
    canvas = _title_base_img.copy()
    draw   = ImageDraw.Draw(canvas)

    # Rebuild ltr_font from cache (size may vary per OSD)
    _mx, _my, mw_phys, mh_phys = _get_mpv_window_rect()
    if not mw_phys:
        mw_phys, mh_phys = osd_w, osd_h
    phys_mod   = min(mw_phys / 2560, mh_phys / 1440)
    screen_dpi = root.winfo_fpixels('1i')
    ltr_fs = max(1, round(max(1, int(80 * phys_mod)) * screen_dpi / 72))
    ltr_font = _get_courier_font(ltr_fs)

    _, fg = _title_colors()

    for i, (cx, cy) in enumerate(_title_letter_pos):
        ch = _title_revealed[i]
        if not ch or not ltr_font:
            continue
        # anchor="mm" centres the glyph at (cx, cy) — matches Tkinter anchor=center
        draw.text((cx, cy), ch, font=ltr_font, fill=fg, anchor="mm")

    try:
        _title_img_overlay.update(canvas)
    except Exception:
        pass
