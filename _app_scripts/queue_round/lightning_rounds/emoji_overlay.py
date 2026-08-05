"""Emoji lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders a centered box with up to 6
emoji clues representing the current anime, via a PIL image overlay on
top of the mpv video.

``emoji_overlay_window`` is a sentinel (truthy while active, None when
not). Main reads it via ``emoji_overlay.emoji_overlay_window`` since
the module rebinds it on toggle.
"""
from __future__ import annotations

import json
import os
import unicodedata

from PIL import Image, ImageDraw

from core.game_state import state
import _app_scripts.playback.osd_text as osd_text
from ...file.metadata import metadata_display
from ...data import metadata_io


# ---------------------------------------------------------------------------
# Module-private state
# ---------------------------------------------------------------------------
emoji_overlay_window = None    # truthy when overlay active, None when not
_emoji_img_overlay = None
EMOJI_REASONING_EFFORT = "low"
EMOJI_MAX_OUTPUT_TOKENS = 200

_EMOJI_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "emoji_clues",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "emojis": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["emojis"],
        "additionalProperties": False,
    },
}


def _is_emoji_base(codepoint):
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0x2300 <= codepoint <= 0x23FF
        or 0x2B00 <= codepoint <= 0x2BFF
        or 0x2190 <= codepoint <= 0x21FF
        or 0x25A0 <= codepoint <= 0x25FF
        or codepoint in {
            0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139,
            0x3030, 0x303D, 0x3297, 0x3299,
        }
    )


def _is_single_emoji(value):
    """Return True for one emoji grapheme, including ZWJ/flag sequences."""
    if not isinstance(value, str):
        return False
    value = unicodedata.normalize("NFC", value)
    if not value or any(character.isspace() or character.isalnum() for character in value):
        return False

    base_count = 0
    regional_run = 0
    joins_next_base = False
    for character in value:
        codepoint = ord(character)
        if codepoint == 0x200D:
            if base_count == 0 or joins_next_base:
                return False
            joins_next_base = True
            continue
        if (
            codepoint in {0xFE0E, 0xFE0F, 0x20E3}
            or 0x1F3FB <= codepoint <= 0x1F3FF
            or 0xE0020 <= codepoint <= 0xE007F
        ):
            continue
        if 0x1F1E6 <= codepoint <= 0x1F1FF:
            if regional_run % 2 == 0:
                base_count += 1
            regional_run += 1
            joins_next_base = False
            continue
        regional_run = 0
        if not _is_emoji_base(codepoint):
            return False
        if not joins_next_base:
            base_count += 1
        joins_next_base = False
    return base_count == 1 and not joins_next_base and regional_run != 1


def validate_emoji_clues(emojis):
    if not isinstance(emojis, list) or len(emojis) != 6:
        return None
    if not all(isinstance(emoji, str) for emoji in emojis):
        return None
    normalized = [unicodedata.normalize("NFC", emoji) for emoji in emojis]
    if len(set(normalized)) != 6 or not all(_is_single_emoji(emoji) for emoji in normalized):
        return None
    return normalized


def parse_emoji_response(content):
    if not content:
        return None
    try:
        parsed = json.loads(content)
        emojis = parsed.get("emojis") if isinstance(parsed, dict) else parsed
    except (json.JSONDecodeError, TypeError):
        emojis = content.split()
    return validate_emoji_clues(emojis)


# ---------------------------------------------------------------------------
def get_cached_emoji_clues(data):
    from _app_scripts.queue_round.lightning_rounds import trivia_round
    entry = trivia_round.get_ai_metadata_entry(data.get("mal")) or {}
    return validate_emoji_clues(entry.get("emojis"))


def get_emoji_clues_for_title(data, allow_api=True):
    """Uses OpenAI to generate emoji clues for the anime's title/concept."""
    mal_id = data.get("mal")
    cached_emojis = get_cached_emoji_clues(data)
    if cached_emojis:
        return cached_emojis
    from _app_scripts.queue_round.lightning_rounds import trivia_round
    client = trivia_round.client
    api_key = state.config.OPENAI_API_KEY
    if not allow_api or not client or not api_key or not trivia_round.is_openai_available():
        return None
    title = metadata_display.get_display_title(data)
    year = int(data.get("season", "9999")[-4:])
    prompt = f"""
        Create exactly 6 distinct emoji clues that progressively help players
        identify the anime "{title}" ({year}).

        Difficulty order:
        - Positions 1-2: subtle but fair clues.
        - Positions 3-4: recognizable, work-specific clues.
        - Positions 5-6: iconic or near-decisive clues.

        Use six different concrete concepts, such as an important object,
        setting, ability, creature, occupation, relationship, or recurring
        motif. Prefer clues specific to this anime over generic genre or mood
        symbols. Do not repeat an emoji or represent the same concept twice.
        Avoid major spoilers. Do not use words, letters, numbers, or names.
        Do not directly translate or rebus the title in positions 1-4;
        title-derived clues are allowed only in positions 5-6.

        Silently compare two possible sequences and select the one with the
        smoothest difficulty progression. Fill the structured `emojis` field
        with the six clues and no explanation.
        """
    if year > trivia_round.gpt_cutoff_year:
        synopsis = " ".join((data.get("synopsis") or "").split())
        if synopsis:
            prompt += f"""
            Recent-title context (use only for accurate clue selection):
            [{synopsis[:500]}]
            """
    try:
        response = client.responses.create(
            model=trivia_round.OPENAI_MODEL,
            input=prompt,
            reasoning={"effort": EMOJI_REASONING_EFFORT},
            max_output_tokens=EMOJI_MAX_OUTPUT_TOKENS,
            text={"format": _EMOJI_RESPONSE_FORMAT},
        )
        content = trivia_round.extract_response_text(response)
        emojis = parse_emoji_response(content)
        if not emojis:
            return None

        if mal_id:
            trivia_round.get_ai_metadata_entry(mal_id, create=True)["emojis"] = emojis
            metadata_io.save_metadata()

        return emojis if emojis else None
    except Exception as e:
        trivia_round._record_api_failure(e)
        return None


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
        data = state.playback.currently_playing.get("data", {})
        emojis = get_emoji_clues_for_title(data, allow_api=False)
    if not emojis:
        return False

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
    # Lazy import: information_popup is a higher layer than this overlay.
    from ...information import information_popup
    _mx, _my, _mw_phys, _mh_phys = information_popup._get_mpv_window_rect()
    if not _mw_phys:
        _mw_phys, _mh_phys = osd_w, osd_h
    _phys_mod = min(_mw_phys / 2560, _mh_phys / 1440)
    _screen_dpi = root.winfo_fpixels('1i')
    header_font_px = max(1, round(max(1, int(70 * _phys_mod)) * _screen_dpi / 72))

    # Colours
    try:
        r16, g16, b16 = root.winfo_rgb(state.colors.OVERLAY_BACKGROUND_COLOR)
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
        r16, g16, b16 = root.winfo_rgb(state.colors.OVERLAY_TEXT_COLOR)
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
    title_font = osd_text._get_ass_font(header_font_px, bold=True)
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
    return True
