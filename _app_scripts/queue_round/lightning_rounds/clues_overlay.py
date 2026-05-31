"""Clues lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders a 3-column grid of metadata
clues (Type/Source/Episodes/Season/Studio/Tags/Score/Members/Song) on top
of the mpv video via a PIL image overlay.

External code in the main file mutates ``_clues_cell_values`` by key
(e.g. ``_clues_cell_values["Tags"] = ...``); to keep those in-place
mutations valid across the module boundary, this module never rebinds
``_clues_cell_values`` — it only mutates it via ``.clear()`` / ``.update()``.
Main aliases ``_clues_cell_values = clues_overlay._clues_cell_values``.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from core.game_state import state


# ---------------------------------------------------------------------------
# Module-private state (canonical owners — main aliases to these)
# ---------------------------------------------------------------------------
_clues_img_overlay = None
_clues_cell_values: dict = {}   # key → text string currently displayed


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
_get_ass_font = None
get_format = None
currently_playing: dict = {}
_get_overlay_background_color = lambda: 'black'
_get_overlay_text_color = lambda: 'white'


def set_context(*, get_ass_font, get_format, currently_playing,
                get_overlay_background_color, get_overlay_text_color):
    g = globals()
    g['_get_ass_font'] = get_ass_font
    g['get_format'] = get_format
    g['currently_playing'] = currently_playing
    g['_get_overlay_background_color'] = get_overlay_background_color
    g['_get_overlay_text_color'] = get_overlay_text_color


def _draw_clues_canvas():
    """Render the current _clues_cell_values as an mpv PIL image overlay."""
    global _clues_img_overlay
    player = state.widgets.player
    root = state.widgets.root
    try:
        osd_w = int(player._p.osd_width  or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    modifier = min(osd_w / 2560, osd_h / 1440)
    def fs(pt): return max(6, round(pt * modifier * 1.15))

    try:
        r16, g16, b16 = root.winfo_rgb(_get_overlay_background_color())
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
        r16, g16, b16 = root.winfo_rgb(_get_overlay_text_color())
        fg_r, fg_g, fg_b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        bg_r, bg_g, bg_b = 0,   0,   0
        fg_r, fg_g, fg_b = 255, 255, 255

    box_w   = round(osd_w * 0.70)
    box_h   = round(osd_h * 0.80)
    box_x   = (osd_w - box_w) // 2
    box_y   = (osd_h - box_h) // 2
    gap     = max(2, round(8  * modifier))
    pad     = max(4, round(16 * modifier))
    border  = max(1, round(4  * modifier))
    title_fs = fs(58)
    title_fnt = _get_ass_font(title_fs, bold=True)

    n_cols   = 3
    col_w    = (box_w - gap * (n_cols - 1)) // n_cols
    song_h   = round(box_h * 0.22)
    top_h    = box_h - song_h - gap
    # Row 0 is single-line values only — give it just enough height for title + one value line
    val_fs_approx = fs(70)
    row0_h   = title_fs + max(1, round(2 * modifier)) + max(1, round(2 * modifier)) + max(2, round(4 * modifier)) + val_fs_approx + 2 * pad
    row0_h   = min(row0_h, round(top_h * 0.34))   # cap at 34% so it can't dominate
    rows12_h = (top_h - row0_h - gap * 2) // 2    # rows 1 and 2 share the rest equally

    def cell_rect(row, col, colspan=1, rowspan=1):
        x = box_x + col * (col_w + gap)
        w = col_w * colspan + gap * (colspan - 1)
        if row == 0:
            y = box_y
            h = row0_h
        elif row == 1:
            y = box_y + row0_h + gap
            h = rows12_h * rowspan + gap * (rowspan - 1)
        elif row == 2:
            y = box_y + row0_h + gap + rows12_h + gap
            h = rows12_h
        else:                         # song row
            y = box_y + top_h + gap
            h = song_h
        return x, y, w, h

    # (key, row, col, colspan, rowspan, title_label)
    CELLS = [
        ("Type",     0, 0, 1, 1, "TYPE"),
        ("Source",   0, 1, 1, 1, "SOURCE"),
        ("Episodes", 0, 2, 1, 1, "EPISODES"),
        ("Season",   1, 0, 1, 1, "SEASON"),
        ("Studio",   1, 1, 1, 1, "STUDIO"),
        ("Tags",     1, 2, 1, 2, "TAGS"),
        ("Score",    2, 0, 1, 1, "SCORE"),
        ("Members",  2, 1, 1, 1, "MEMBERS"),
        ("Song",     3, 0, 3, 1, None),
    ]

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    line_gap = max(1, round(2 * modifier))

    for key, row, col, colspan, rowspan, title_label in CELLS:
        cx, cy, cw, ch = cell_rect(row, col, colspan, rowspan)
        value = _clues_cell_values.get(key, "")

        draw.rectangle([cx, cy, cx + cw - 1, cy + ch - 1],
                       fill=(bg_r, bg_g, bg_b, 204),
                       outline=(fg_r, fg_g, fg_b, 200), width=border)

        iy = cy + pad
        inner_w = cw - 2 * pad

        # Title (bold, centred, underlined)
        if title_label and title_fnt:
            try:
                tw = round(title_fnt.getlength(title_label))
            except AttributeError:
                tw = len(title_label) * title_fs // 2
            tx = cx + (cw - tw) // 2
            draw.text((tx, iy), title_label,
                      font=title_fnt, fill=(fg_r, fg_g, fg_b, 255))
            ul_y = iy + title_fs + max(1, round(2 * modifier))
            ul_h = max(1, round(2 * modifier))
            draw.rectangle([tx, ul_y, tx + tw - 1, ul_y + ul_h - 1],
                           fill=(fg_r, fg_g, fg_b, 220))
            iy = ul_y + ul_h + max(2, round(4 * modifier))

        # Value (regular, auto-sized, height-clamped)
        if value:
            lines  = value.split('\n')
            val_pt = 70 - max(0, (len(lines) - 5) * 5)
            val_fs = fs(val_pt)
            remaining_h = cy + ch - pad - iy
            # Shrink until all lines fit vertically
            while val_fs > 6:
                total_text_h = len(lines) * val_fs + max(0, len(lines) - 1) * line_gap
                if total_text_h <= remaining_h:
                    break
                val_fs = max(6, val_fs - 1)
            val_fnt = _get_ass_font(val_fs, bold=False)
            if val_fnt:
                total_text_h  = len(lines) * val_fs + max(0, len(lines) - 1) * line_gap
                text_y        = iy + max(0, (remaining_h - total_text_h) // 2)
                for line in lines:
                    try:
                        lw = round(val_fnt.getlength(line))
                    except AttributeError:
                        lw = len(line) * val_fs // 2
                    fnt_use, lw_use = val_fnt, lw
                    if lw > inner_w and line:
                        scaled_fs = max(6, round(val_fs * inner_w / lw))
                        fnt_use = _get_ass_font(scaled_fs, bold=False)
                        try:
                            lw_use = round(fnt_use.getlength(line))
                        except AttributeError:
                            lw_use = len(line) * scaled_fs // 2
                    draw.text((cx + (cw - lw_use) // 2, text_y), line,
                              font=fnt_use, fill=(fg_r, fg_g, fg_b, 255))
                    text_y += val_fs + line_gap

    if _clues_img_overlay is None:
        _clues_img_overlay = player._p.create_image_overlay()
    _clues_img_overlay.update(canvas)


def toggle_clues_overlay(destroy=False, **_ignored):
    """Show or hide the clues lightning-round OSD (mpv PIL image overlay)."""
    global _clues_img_overlay

    if destroy:
        _clues_cell_values.clear()
        if _clues_img_overlay is not None:
            try:
                _clues_img_overlay.remove()
            except Exception:
                pass
            _clues_img_overlay = None
        return

    if _clues_cell_values:
        return  # already visible

    data = currently_playing.get("data")
    if not data:
        return

    _clues_cell_values.clear()
    _clues_cell_values.update({
        "Type":     get_format(data),
        "Source":   data.get("source", ""),
        "Season":   data.get("season", "").replace(" ", "\n"),
        "Studio":   "\n".join(data.get("studios", [])),
        "Episodes": "",
        "Tags":     "",
        "Score":    "",
        "Members":  "",
        "Song":     "",
    })
    _draw_clues_canvas()
