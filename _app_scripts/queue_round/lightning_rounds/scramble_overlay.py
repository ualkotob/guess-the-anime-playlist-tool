"""Scramble lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders the title's letters
scattered inside a large box; on each "place letters" tick the next
N letters lerp toward their target slots. The unplaced letters wiggle
on a 400ms loop driven by `root.after`.

Two stacked mpv image overlays are used: a static base (box + header +
underline slots) and an animated letters layer cleared per frame.

``scramble_overlay_root`` is the rebound sentinel — main reads it via
``scramble_overlay.scramble_overlay_root``. ``scramble_overlay_letters``
is a list mutated in place (never rebound), so a main-side alias
``scramble_overlay_letters = scramble_overlay.scramble_overlay_letters``
stays valid for the external `.append`/iteration sites.
"""
from __future__ import annotations

import random

from PIL import Image, ImageDraw

from core.game_state import state
from . import title_overlay


# ---------------------------------------------------------------------------
# Module state — `scramble_overlay_root` is read externally by main;
# `scramble_overlay_letters` is aliased by main but mutated in-place only.
# ---------------------------------------------------------------------------
scramble_overlay_root          = None   # sentinel — True when active, None when not
_scramble_base_overlay         = None   # mpv image overlay: static box + header + slots
_scramble_img_overlay          = None   # mpv image overlay: animated letters layer
_scramble_letters_img          = None   # persistent full-screen RGBA canvas for letters
_scramble_box_rect             = None   # (x0, y0, x1, y1) interior of box for per-frame clear
_scramble_ltr_font             = None   # cached PIL letter font
_scramble_osd_size             = (0, 0)
_scramble_anim_after           = None   # pending root.after id for wiggle loop
scramble_title_text            = ""
scramble_overlay_letters: list = []     # {char, index, x, y, target, wiggle, placed}
scramble_letter_placed_indices: set = set()
scramble_animating             = False


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
_get_mpv_window_rect = None
_get_ass_font = None
_get_courier_font = None
_get_character_round_answer = lambda: None
_get_fixed_current_round = lambda: None


def set_context(*, get_mpv_window_rect, get_ass_font, get_courier_font,
                get_character_round_answer, get_fixed_current_round):
    g = globals()
    g['_get_mpv_window_rect'] = get_mpv_window_rect
    g['_get_ass_font'] = get_ass_font
    g['_get_courier_font'] = get_courier_font
    g['_get_character_round_answer'] = get_character_round_answer
    g['_get_fixed_current_round'] = get_fixed_current_round


def _scramble_build_base():
    """Build and push the static base overlay (box + header + slots).
    Also allocates a fresh transparent letters canvas.
    Sets module globals: _scramble_base_overlay, _scramble_img_overlay (if None),
                         _scramble_letters_img, _scramble_box_rect,
                         _scramble_ltr_font, _scramble_osd_size.
    Returns (target_coords, (osd_w, osd_h))."""
    global _scramble_base_overlay, _scramble_img_overlay
    global _scramble_letters_img, _scramble_box_rect
    global _scramble_ltr_font, _scramble_osd_size

    player = state.widgets.player
    root = state.widgets.root
    cra = _get_character_round_answer()

    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        osd_w, osd_h = 0, 0
    if not osd_w or not osd_h:
        osd_w = root.winfo_screenwidth()
        osd_h = root.winfo_screenheight()

    mod = min(osd_w / 2560, osd_h / 1440)
    def ws(n): return max(1, int(n * mod))

    _mx, _my, mw_phys, mh_phys = _get_mpv_window_rect()
    if not mw_phys:
        mw_phys, mh_phys = osd_w, osd_h
    phys_mod   = min(mw_phys / 2560, mh_phys / 1440)
    screen_dpi = root.winfo_fpixels('1i')
    hdr_fs = max(1, round(max(1, int(70 * phys_mod)) * screen_dpi / 72))
    ltr_fs = max(1, round(max(1, int(80 * phys_mod)) * screen_dpi / 72))

    hdr_font = _get_ass_font(hdr_fs, bold=True)
    ltr_font = _get_courier_font(ltr_fs)
    bg, fg   = title_overlay._title_colors()
    border   = ws(4)
    spacing  = ws(64)

    lines      = title_overlay._title_wrap_lines(scramble_title_text, round(osd_w * 0.7) - ws(40), ltr_font)
    overlay_w  = round(osd_w * 0.7)
    overlay_h  = len(lines) * ws(100) + ws(320)
    box_full_h = int(osd_h * 0.7)
    bx         = (osd_w - overlay_w) // 2
    box_full_y = (osd_h - box_full_h) // 2
    by         = (osd_h - overlay_h) // 2

    base_canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw        = ImageDraw.Draw(base_canvas)

    draw.rectangle([bx, box_full_y, bx + overlay_w, box_full_y + box_full_h], fill=bg)
    draw.rectangle([bx, box_full_y, bx + overlay_w, box_full_y + box_full_h], outline=fg, width=border)

    title_txt = "CHARACTER NAME:" if cra else "TITLE:"
    if hdr_font:
        hx = bx + ws(30)
        hy = box_full_y + ws(30)
        hb = draw.textbbox((hx, hy), title_txt, font=hdr_font, anchor="lt")
        draw.text((hx, hy), title_txt, font=hdr_font, fill=fg, anchor="lt")
        ul_y = hb[3] + max(2, ws(6))
        draw.rectangle([hb[0], ul_y, hb[2], ul_y + max(4, ws(10))], fill=fg)

    target_coords = {}
    slot_idx = 0
    line_y   = by + ws(270)
    for line in lines:
        chars   = list(line)
        total_w = len(chars) * spacing
        line_x  = osd_w // 2 - total_w // 2 + spacing // 2
        for ch in chars:
            if ch == " ":
                line_x += spacing
                continue
            cx, cy = line_x, line_y
            ul_w = spacing - ws(6)
            ul_h = max(1, ws(2))
            draw.rectangle([cx - ul_w // 2, cy + ws(36), cx - ul_w // 2 + ul_w, cy + ws(36) + ul_h], fill=fg)
            target_coords[slot_idx] = (cx, cy)
            slot_idx += 1
            line_x += spacing
        line_y += ws(100)

    # Push static base (create overlay on first build, reuse on rebuild)
    if _scramble_base_overlay is None:
        _scramble_base_overlay = player._p.create_image_overlay()
    _scramble_base_overlay.update(base_canvas)

    # Create letters overlay on first build only
    if _scramble_img_overlay is None:
        _scramble_img_overlay = player._p.create_image_overlay()

    # Fresh transparent canvas for the animated letters layer
    _scramble_letters_img = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))

    # Clear rect is the box interior (inside the border)
    _scramble_box_rect = (bx + border, box_full_y + border,
                          bx + overlay_w - border, box_full_y + box_full_h - border)
    _scramble_ltr_font = ltr_font
    _scramble_osd_size = (osd_w, osd_h)

    return target_coords, (osd_w, osd_h)


def _scramble_redraw():
    """Clear the box region on the letters canvas, stamp all letters, push to OSD.
    No base-image copy — the static base lives on its own overlay."""
    if _scramble_letters_img is None or _scramble_img_overlay is None:
        return
    _, fg = title_overlay._title_colors()
    draw  = ImageDraw.Draw(_scramble_letters_img)
    # Single rectangle fill to clear — much cheaper than full-image copy
    draw.rectangle(_scramble_box_rect, fill=(0, 0, 0, 0))
    for letter in scramble_overlay_letters:
        draw.text((int(letter["x"]), int(letter["y"])), letter["char"],
                  font=_scramble_ltr_font, fill=fg, anchor="mm")
    try:
        _scramble_img_overlay.update(_scramble_letters_img)
    except Exception:
        pass


def _animate_scramble():
    """400ms wiggle tick: bounce unplaced letters and push updated frame."""
    global _scramble_anim_after
    if not scramble_animating or not scramble_overlay_root:
        return
    player = state.widgets.player
    root = state.widgets.root
    try:
        cur_w = int(player._p.osd_width or 0)
        cur_h = int(player._p.osd_height or 0)
    except Exception:
        cur_w, cur_h = 0, 0
    if cur_w and (cur_w, cur_h) != _scramble_osd_size:
        toggle_scramble_overlay(rebuild=True)
        return
    if player.is_playing():
        for letter in scramble_overlay_letters:
            if not letter["placed"]:
                wx, wy = letter["wiggle"]
                letter["x"] += wx
                letter["y"] += wy
                letter["wiggle"] = (-wx, -wy)
    _scramble_redraw()
    _scramble_anim_after = root.after(400, _animate_scramble)


def toggle_scramble_overlay(num_letters=0, destroy=False, rebuild=False):
    global scramble_overlay_root, _scramble_base_overlay, _scramble_img_overlay
    global _scramble_letters_img, _scramble_box_rect, _scramble_ltr_font
    global _scramble_anim_after, scramble_animating
    global scramble_title_text

    root = state.widgets.root
    fixed_current_round = _get_fixed_current_round()

    if destroy:
        scramble_animating = False
        if _scramble_anim_after is not None:
            try:
                root.after_cancel(_scramble_anim_after)
            except Exception:
                pass
            _scramble_anim_after = None
        for ov in (_scramble_base_overlay, _scramble_img_overlay):
            if ov is not None:
                try:
                    ov.remove()
                except Exception:
                    pass
        _scramble_base_overlay = None
        _scramble_img_overlay  = None
        _scramble_letters_img  = None
        _scramble_box_rect     = None
        _scramble_ltr_font     = None
        scramble_overlay_root  = None
        scramble_overlay_letters.clear()
        scramble_letter_placed_indices.clear()
        return

    def _scatter_geometry(osd_w, osd_h, ltr_font):
        mod = min(osd_w / 2560, osd_h / 1440)
        def ws(n): return max(1, int(n * mod))
        overlay_w  = round(osd_w * 0.7)
        bx         = (osd_w - overlay_w) // 2
        lines      = title_overlay._title_wrap_lines(scramble_title_text, overlay_w - ws(40), ltr_font)
        overlay_h  = len(lines) * ws(100) + ws(320)
        by         = (osd_h - overlay_h) // 2
        box_full_h = int(osd_h * 0.7)
        box_full_y = (osd_h - box_full_h) // 2
        box_full_b = box_full_y + box_full_h
        left_x  = bx + ws(50)
        right_x = bx + overlay_w - ws(50)
        scatter_top = box_full_y + ws(190)
        scatter_bot = box_full_b - ws(50)
        # Slot row y-positions — letters must avoid a band around each
        slot_ys      = [by + ws(270) + l * ws(100) for l in range(len(lines))]
        slot_margin  = ws(110)  # half-height clearance around each slot row
        return left_x, right_x, scatter_top, scatter_bot, ws(70), slot_ys, slot_margin

    if rebuild and scramble_overlay_letters:
        saved_letters = [(l["char"], l["index"], l["placed"]) for l in scramble_overlay_letters]
        saved_placed  = set(scramble_letter_placed_indices)
        scramble_animating = False
        if _scramble_anim_after is not None:
            try:
                root.after_cancel(_scramble_anim_after)
            except Exception:
                pass
            _scramble_anim_after = None
        scramble_overlay_letters.clear()
        scramble_letter_placed_indices.clear()

        target_coords, osd_size = _scramble_build_base()
        osd_w, osd_h = osd_size
        left_x, right_x, scatter_top, scatter_bot, min_dist, slot_ys, slot_margin = \
            _scatter_geometry(osd_w, osd_h, _scramble_ltr_font)

        letter_positions = []
        for char, idx, was_placed in saved_letters:
            if idx not in target_coords:
                continue
            tx, ty = target_coords[idx]
            if was_placed:
                sx, sy = float(tx), float(ty)
            else:
                sx, sy = float(osd_w // 2), float(osd_h // 2)
                for _ in range(150):
                    sy = float(random.randint(scatter_top, scatter_bot))
                    sx = float(random.randint(left_x, right_x))
                    if any(abs(sy - slot_y) < slot_margin for slot_y in slot_ys):
                        continue
                    if not any(abs(sx - px) < min_dist and abs(sy - py) < min_dist
                               for px, py in letter_positions):
                        break
            letter_positions.append((sx, sy))
            wx = random.choice([-1, 1]) * random.randint(1, 2)
            wy = random.choice([-1, 1]) * random.randint(1, 2)
            scramble_overlay_letters.append({
                "char": char, "index": idx,
                "x": sx, "y": sy,
                "target": (float(tx), float(ty)),
                "wiggle": (wx, wy),
                "placed": was_placed,
            })
        scramble_letter_placed_indices.update(saved_placed)
        scramble_animating = True
        _animate_scramble()
        return

    # --- Initial creation ---
    if not scramble_overlay_root:
        scramble_title_text = title_overlay.get_base_title()

        target_coords, osd_size = _scramble_build_base()
        osd_w, osd_h = osd_size
        left_x, right_x, scatter_top, scatter_bot, min_dist, slot_ys, slot_margin = \
            _scatter_geometry(osd_w, osd_h, _scramble_ltr_font)

        flat_chars = [(c, i) for i, c in enumerate(scramble_title_text.replace(" ", ""))
                      if i in target_coords]
        if fixed_current_round and fixed_current_round.get("scramble_place_order"):
            order_indices = [int(x.strip()) for x in
                             fixed_current_round["scramble_place_order"].split(",")
                             if x.strip().isdigit()]
            ordered     = [p for idx in order_indices for p in flat_chars if p[1] == idx]
            ordered_set = {p[1] for p in ordered}
            remaining   = [p for p in flat_chars if p[1] not in ordered_set]
            random.shuffle(remaining)
            flat_chars  = ordered + remaining
        else:
            random.shuffle(flat_chars)

        letter_positions = []
        for i, (char, idx) in enumerate(flat_chars):
            tx, ty = target_coords[idx]
            sx, sy = float(osd_w // 2), float(osd_h // 2)
            for _ in range(150):
                sy = float(random.randint(scatter_top, scatter_bot))
                sx = float(random.randint(left_x, right_x))
                if any(abs(sy - slot_y) < slot_margin for slot_y in slot_ys):
                    continue
                if not any(abs(sx - px) < min_dist and abs(sy - py) < min_dist
                           for px, py in letter_positions):
                    break
            letter_positions.append((sx, sy))
            wx = random.choice([-1, 1]) * random.randint(1, 2)
            wy = random.choice([-1, 1]) * random.randint(1, 2)
            scramble_overlay_letters.append({
                "char": char, "index": idx,
                "x": sx, "y": sy,
                "target": (float(tx), float(ty)),
                "wiggle": (wx, wy),
                "placed": False,
            })

        scramble_overlay_root = True
        scramble_animating    = True
        _animate_scramble()

    # Place letters up to num_letters (lerp one step toward target)
    for i, letter in enumerate(scramble_overlay_letters):
        if i < num_letters and not letter["placed"]:
            letter["placed"] = True
            scramble_letter_placed_indices.add(letter["index"])
        if letter["placed"]:
            tx, ty = letter["target"]
            letter["x"] += (tx - letter["x"]) * 0.2
            letter["y"] += (ty - letter["y"]) * 0.2
    if num_letters > 0:
        _scramble_redraw()
