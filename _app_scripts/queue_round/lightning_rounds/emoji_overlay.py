"""Emoji lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders a centered box with up to 6
emoji clues representing the current anime, via a PIL image overlay on
top of the mpv video.

``emoji_overlay_window`` is a sentinel (truthy while active, None when
not). Main reads it via ``emoji_overlay.emoji_overlay_window`` since
the module rebinds it on toggle.
"""
from __future__ import annotations

import os
import unicodedata

from PIL import Image, ImageDraw

from core.game_state import state


# ---------------------------------------------------------------------------
# Module-private state
# ---------------------------------------------------------------------------
emoji_overlay_window = None    # truthy when overlay active, None when not
_emoji_img_overlay = None


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
currently_playing: dict = {}
ai_metadata: dict = {}
_get_display_title = None
_extract_response_text = None
_save_metadata = None
_get_ass_font = None
_get_mpv_window_rect = None
_get_openai_api_key = lambda: ''
_get_overlay_background_color = lambda: 'black'
_get_overlay_text_color = lambda: 'white'


def set_context(*, currently_playing, ai_metadata, get_display_title,
                extract_response_text, save_metadata, get_ass_font,
                get_mpv_window_rect, get_openai_api_key,
                get_overlay_background_color, get_overlay_text_color):
    g = globals()
    g['currently_playing'] = currently_playing
    g['ai_metadata'] = ai_metadata
    g['_get_display_title'] = get_display_title
    g['_extract_response_text'] = extract_response_text
    g['_save_metadata'] = save_metadata
    g['_get_ass_font'] = get_ass_font
    g['_get_mpv_window_rect'] = get_mpv_window_rect
    g['_get_openai_api_key'] = get_openai_api_key
    g['_get_overlay_background_color'] = get_overlay_background_color
    g['_get_overlay_text_color'] = get_overlay_text_color


def get_emoji_clues_for_title(data):
    """Uses OpenAI to generate emoji clues for the anime's title/concept."""
    mal_id = data.get("mal")
    if mal_id and mal_id in ai_metadata and "emojis" in ai_metadata[mal_id]:
        return ai_metadata[mal_id]["emojis"]
    from _app_scripts.queue_round.lightning_rounds import trivia_round
    client = trivia_round.client
    api_key = _get_openai_api_key()
    if not client or not api_key:
        return ["❓"]
    title = _get_display_title(data)
    year = int(data.get("season", "9999")[-4:])
    prompt = (
        f"Give me exactly 6 emojis that represent the anime '{title}' ({year}). "
        "Order them in a way to make the easier emojis later. "
        "Do NOT use any words or character names. "
        "Only output emojis, separated by spaces."
    )
    try:
        response = client.responses.create(
            model="gpt-4-turbo",
            input=prompt
        )
        # Extract emojis from response
        content = _extract_response_text(response)
        # Split by whitespace - compound emojis stay intact since ZWJ isn't whitespace
        emojis = content.split()

        # Limit to 6 emojis
        emojis = emojis[:6]

        if mal_id:
            ai_metadata.setdefault(mal_id, {})["emojis"] = emojis
            _save_metadata()

        return emojis if emojis else ["❓"]
    except Exception as e:
        print("Emoji GPT error:", e)
        return ["❓"]


def toggle_emoji_overlay(emojis=None, destroy=False, max_emojis=None, title="EMOJIS"):
    global emoji_overlay_window, _emoji_img_overlay

    player = state.widgets.player
    root = state.widgets.root

    NUM_EMOJI_SLOTS = 6

    if destroy:
        if _emoji_img_overlay is not None:
            try:
                _emoji_img_overlay.remove()
            except Exception:
                pass
            _emoji_img_overlay = None
        emoji_overlay_window = None
        return

    if not emojis:
        data = currently_playing.get("data", {})
        emojis = get_emoji_clues_for_title(data)

    if max_emojis is not None:
        emojis = emojis[:max_emojis]

    padded_emojis = (emojis + [""] * NUM_EMOJI_SLOTS)[:NUM_EMOJI_SLOTS]

    try:
        osd_w = player._p.osd_width  or 1920
        osd_h = player._p.osd_height or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080

    modifier = min(osd_w / 2560, osd_h / 1440)
    def ws(n): return max(1, int(n * modifier))

    # Header font size — mirrors synopsis exactly: physical window mod × screen DPI → OSD pixels
    _mx, _my, _mw_phys, _mh_phys = _get_mpv_window_rect()
    if not _mw_phys:
        _mw_phys, _mh_phys = osd_w, osd_h
    _phys_mod = min(_mw_phys / 2560, _mh_phys / 1440)
    _screen_dpi = root.winfo_fpixels('1i')
    header_font_px = max(1, round(max(1, int(70 * _phys_mod)) * _screen_dpi / 72))

    # Colours
    try:
        r16, g16, b16 = root.winfo_rgb(_get_overlay_background_color())
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
        r16, g16, b16 = root.winfo_rgb(_get_overlay_text_color())
        fg_r, fg_g, fg_b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        bg_r, bg_g, bg_b = 0, 0, 0
        fg_r, fg_g, fg_b = 255, 255, 255
    bg = (bg_r, bg_g, bg_b, 230)   # 0.9 alpha — matches Toplevel alpha=0.9
    fg = (fg_r, fg_g, fg_b, 255)

    # Box geometry (matches 70% wide × 35% tall, centered)
    box_w  = int(osd_w * 0.70)
    box_h  = int(osd_h * 0.35)
    box_x  = (osd_w - box_w) // 2
    box_y  = (osd_h - box_h) // 2
    border = ws(4)
    pad    = ws(20)

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    # Background + border
    draw.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], fill=bg)
    draw.rectangle([box_x, box_y, box_x + box_w, box_y + box_h],
                   outline=fg, width=border)

    # Title — style matches synopsis header (bold, underline under text only)
    title_font = _get_ass_font(header_font_px, bold=True)
    title_bottom = box_y + pad + header_font_px + ws(20)   # fallback
    if title_font:
        tb = draw.textbbox((0, 0), title, font=title_font)
        tx = box_x + pad - tb[0]
        ty = box_y + pad - tb[1]
        draw.text((tx, ty), title, font=title_font, fill=fg)
        # Underline spans only the text width — same as synopsis \u1 ASS tag
        ul_y  = ty + tb[3] + max(1, round(header_font_px * 0.05))
        ul_x1 = tx + tb[0]   # visual left edge of text
        ul_x2 = tx + tb[2]   # visual right edge of text
        ul_h  = max(2, round(header_font_px * 0.07))
        draw.rectangle([ul_x1, ul_y, ul_x2, ul_y + ul_h], fill=fg)
        title_bottom = ul_y + ul_h + ws(20)

    # Emoji slots — extra side padding so emojis don't crowd the box edges
    slot_size      = ws(200)
    emoji_side_pad = pad * 2          # larger inset on left/right vs. the text pad
    emoji_area_w   = box_w - emoji_side_pad * 2
    total_slots    = NUM_EMOJI_SLOTS
    slot_gap       = max(ws(10), (emoji_area_w - slot_size * total_slots) // max(1, total_slots - 1))
    emoji_area_h   = box_h - (title_bottom - box_y) - pad
    slot_y         = title_bottom + (emoji_area_h - slot_size) // 2

    # Emoji font (loaded once per size)
    _efont = None
    for _fp in [r"C:\Windows\Fonts\seguiemj.ttf",
                r"C:\Windows\Fonts\NotoColorEmoji.ttf",
                r"C:\Windows\Fonts\seguisym.ttf"]:
        if os.path.exists(_fp):
            try:
                from PIL import ImageFont as _IFnt
                _efont = _IFnt.truetype(_fp, size=int(slot_size * 1.2))
                break
            except Exception:
                pass

    for i, emoji_char in enumerate(padded_emojis):
        if not emoji_char or not _efont:
            continue
        slot_x = box_x + emoji_side_pad + i * (slot_size + slot_gap)
        try:
            ec = unicodedata.normalize('NFC', emoji_char)
            cs = slot_size * 8
            em_im  = Image.new("RGBA", (cs, cs), (0, 0, 0, 0))
            em_drw = ImageDraw.Draw(em_im)
            em_drw.text((cs // 2, cs // 2), ec, font=_efont,
                        anchor="mm", embedded_color=True)
            bbox = em_im.getbbox()
            if not bbox:
                continue
            cropped = em_im.crop(bbox)
            cw, ch  = cropped.size
            scale   = min(slot_size / cw, slot_size / ch)
            if scale < 1:
                cw, ch  = int(cw * scale), int(ch * scale)
                cropped = cropped.resize((cw, ch), Image.LANCZOS)
            ox = slot_x + (slot_size - cw) // 2
            oy = slot_y  + (slot_size - ch) // 2
            canvas.paste(cropped, (ox, oy), cropped)
        except Exception:
            pass

    if _emoji_img_overlay is None:
        _emoji_img_overlay = player._p.create_image_overlay()
    _emoji_img_overlay.update(canvas)
    emoji_overlay_window = True   # sentinel so game-loop guard stays truthy
