"""Swap lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders the title's letters with
half of the swappable pairs already swapped; each tick animates the next
pair back into place along arcing paths. Two stacked mpv image overlays
are used: a static base (box + header + underline slots) and an animated
letters layer cleared per frame.

``swap_overlay_root`` is the rebound sentinel — main reads it via
``swap_overlay.swap_overlay_root``. ``swap_pairs`` and
``swap_overlay_letters`` are lists mutated in place (never rebound after
module init), so main-side aliases stay valid for the external `len()`
and iteration sites.

Uses ``title_overlay`` for shared helpers (`_title_colors`,
`_title_wrap_lines`, `get_base_title`).
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from core.game_state import state
from . import title_overlay
import _app_scripts.playback.osd_text as osd_text


# ---------------------------------------------------------------------------
# Module state — `swap_overlay_root` is read externally by main; `swap_pairs`
# is aliased by main but only mutated in place.
# ---------------------------------------------------------------------------
swap_overlay_root     = None  # sentinel — True when active, None when not
_swap_static_overlay  = None  # mpv overlay: box + header + underlines (pushed once)
_swap_letters_overlay = None  # mpv overlay: all letters on transparent canvas
_swap_letters_img     = None  # persistent full-screen RGBA canvas for letters
_swap_box_rect        = None  # (x0, y0, x1, y1) interior of box for per-frame clear
_swap_ltr_font        = None  # cached PIL letter font
swap_title_text       = ""
swap_pairs: list      = []
swap_completed        = 0
swap_overlay_letters: list = []  # {char, index, pos:(cx,cy), correct, base_char}
_swap_osd_size        = (0, 0)
_swap_anim_after      = None  # pending root.after id for arc animation


def _swap_colors():
    """(bg_rgba, fg_rgba, gray_rgba) — title's bg/fg plus midpoint gray."""
    bg, fg = title_overlay._title_colors()
    gray = tuple((bg[i] + fg[i]) // 2 for i in range(3)) + (255,)
    return bg, fg, gray


def _build_swap_base():
    """Build and push the static base overlay (box + header + underlines only,
    no letters). Allocates a fresh letters canvas.
    Sets module globals: _swap_static_overlay, _swap_letters_overlay (if None),
                         _swap_letters_img, _swap_box_rect, _swap_ltr_font,
                         _swap_osd_size.
    Returns (target_coords, (osd_w, osd_h))."""
    global _swap_static_overlay, _swap_letters_overlay
    global _swap_letters_img, _swap_box_rect, _swap_ltr_font, _swap_osd_size

    player = state.widgets.player
    root = state.widgets.root
    cra = state.lightning.character_round_answer

    try:
        osd_w = int(player._p.osd_width  or 0) or 1920
        osd_h = int(player._p.osd_height or 0) or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080

    mod = min(osd_w / 2560, osd_h / 1440)
    def ws(n): return max(1, int(n * mod))

    # Lazy import: information_popup is a higher layer than this overlay.
    from ...information import information_popup
    _mx, _my, mw_phys, mh_phys = information_popup._get_mpv_window_rect()
    if not mw_phys:
        mw_phys, mh_phys = osd_w, osd_h
    phys_mod   = min(mw_phys / 2560, mh_phys / 1440)
    screen_dpi = root.winfo_fpixels('1i')
    hdr_fs = max(1, round(max(1, int(70 * phys_mod)) * screen_dpi / 72))
    ltr_fs = max(1, round(max(1, int(80 * phys_mod)) * screen_dpi / 72))

    hdr_font = osd_text._get_ass_font(hdr_fs, bold=True)
    ltr_font = osd_text._get_courier_font(ltr_fs)

    bg, fg, _ = _swap_colors()
    border  = ws(4)
    spacing = ws(64)

    lines = title_overlay._title_wrap_lines(swap_title_text, round(osd_w * 0.7) - ws(40), ltr_font)
    overlay_w = round(osd_w * 0.7)
    overlay_h = len(lines) * ws(100) + ws(320)
    bx = (osd_w - overlay_w) // 2
    by = (osd_h - overlay_h) // 2

    base_canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw        = ImageDraw.Draw(base_canvas)

    draw.rectangle([bx, by, bx + overlay_w, by + overlay_h], fill=bg)
    draw.rectangle([bx, by, bx + overlay_w, by + overlay_h], outline=fg, width=border)

    title_txt = "CHARACTER NAME:" if cra else "TITLE:"
    if hdr_font:
        hx = bx + ws(30)
        hy = by + ws(30)
        hb = draw.textbbox((hx, hy), title_txt, font=hdr_font, anchor="lt")
        draw.text((hx, hy), title_txt, font=hdr_font, fill=fg, anchor="lt")
        ul_y = hb[3] + max(2, ws(6))
        draw.rectangle([hb[0], ul_y, hb[2], ul_y + max(4, ws(10))], fill=fg)

    target_coords = {}
    slot_idx = 0
    line_y = by + ws(270)
    for line in lines:
        chars = list(line)
        total_w = len(chars) * spacing
        line_x = osd_w // 2 - total_w // 2 + spacing // 2
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

    if _swap_static_overlay is None:
        _swap_static_overlay = player._p.create_image_overlay()
    _swap_static_overlay.update(base_canvas)

    if _swap_letters_overlay is None:
        _swap_letters_overlay = player._p.create_image_overlay()

    _swap_letters_img = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    _swap_box_rect    = (bx + border, by + border, bx + overlay_w - border, by + overlay_h - border)
    _swap_ltr_font    = ltr_font
    _swap_osd_size    = (osd_w, osd_h)

    return target_coords, (osd_w, osd_h)


def _swap_stamp_letters(skip_indices=None, extra_letters=None):
    """Clear the box interior on the letters canvas, stamp all letters (except
    skip_indices), optionally add extra_letters [(ch, cx, cy, fill)], push to OSD."""
    if _swap_letters_img is None or _swap_letters_overlay is None:
        return
    _, fg, gray = _swap_colors()
    draw = ImageDraw.Draw(_swap_letters_img)
    draw.rectangle(_swap_box_rect, fill=(0, 0, 0, 0))
    for letter in swap_overlay_letters:
        if skip_indices and letter["index"] in skip_indices:
            continue
        cx, cy = letter["pos"]
        fill = fg if letter["correct"] else gray
        if _swap_ltr_font:
            draw.text((cx, cy), letter["char"], font=_swap_ltr_font, fill=fill, anchor="mm")
    if extra_letters:
        for ch, cx, cy, fill in extra_letters:
            if _swap_ltr_font:
                draw.text((int(cx), int(cy)), ch, font=_swap_ltr_font, fill=fill, anchor="mm")
    try:
        _swap_letters_overlay.update(_swap_letters_img)
    except Exception:
        pass


def toggle_swap_overlay(num_swaps=0, destroy=False, rebuild=False):
    global swap_overlay_root, _swap_static_overlay, _swap_letters_overlay
    global _swap_letters_img, _swap_box_rect, _swap_ltr_font
    global swap_title_text, swap_completed
    global _swap_osd_size, _swap_anim_after

    import random

    player = state.widgets.player
    root = state.widgets.root

    if destroy:
        swap_overlay_root = None
        if _swap_anim_after is not None:
            try:
                root.after_cancel(_swap_anim_after)
            except Exception:
                pass
            _swap_anim_after = None
        for ov in (_swap_static_overlay, _swap_letters_overlay):
            if ov is not None:
                try:
                    ov.remove()
                except Exception:
                    pass
        _swap_static_overlay  = None
        _swap_letters_overlay = None
        _swap_letters_img     = None
        _swap_box_rect        = None
        _swap_ltr_font        = None
        swap_overlay_letters.clear()
        swap_pairs.clear()
        _swap_osd_size = (0, 0)
        return

    if rebuild and swap_overlay_letters:
        target_coords, _ = _build_swap_base()
        # Refresh stored positions to new OSD coords
        for letter in swap_overlay_letters:
            idx = letter["index"]
            if idx in target_coords:
                letter["pos"] = target_coords[idx]
        _swap_stamp_letters()
        return

    # Auto-rebuild if OSD size changed (window resize)
    if swap_overlay_root and swap_overlay_letters:
        try:
            _cur_osd_w = int(player._p.osd_width  or 0) or 1920
            _cur_osd_h = int(player._p.osd_height or 0) or 1080
        except Exception:
            _cur_osd_w, _cur_osd_h = 1920, 1080
        if (_cur_osd_w, _cur_osd_h) != _swap_osd_size:
            toggle_swap_overlay(num_swaps=num_swaps, rebuild=True)
            return

    bg, fg, gray = _swap_colors()

    if not swap_overlay_root:
        swap_title_text = title_overlay.get_base_title()

        try:
            osd_w = int(player._p.osd_width  or 0) or 1920
            osd_h = int(player._p.osd_height or 0) or 1080
        except Exception:
            osd_w, osd_h = 1920, 1080

        mod = min(osd_w / 2560, osd_h / 1440)
        def ws(n): return max(1, int(n * mod))

        spacing   = ws(64)
        overlay_w = round(osd_w * 0.7)
        lines     = title_overlay._title_wrap_lines(swap_title_text, overlay_w - ws(40), _swap_ltr_font or osd_text._get_courier_font(
            max(1, round(max(1, int(80 * min(osd_w/2560, osd_h/1440))) *
                root.winfo_fpixels('1i') / 72))))
        overlay_h = len(lines) * ws(100) + ws(320)
        by = (osd_h - overlay_h) // 2

        base_chars         = []
        word_visual_groups = []
        current_word       = []
        target_coords      = {}

        line_y = by + ws(270)
        for line in lines:
            chars   = list(line)
            total_w = len(chars) * spacing
            line_x  = osd_w // 2 - total_w // 2 + spacing // 2
            for ch in chars:
                if ch == " ":
                    if current_word:
                        word_visual_groups.append(current_word)
                        current_word = []
                    line_x += spacing
                    continue
                idx = len(base_chars)
                base_chars.append(ch)
                current_word.append(idx)
                target_coords[idx] = (line_x, line_y)
                line_x += spacing
            if current_word:
                word_visual_groups.append(current_word)
                current_word = []
            line_y += ws(100)

        total_letters = len(base_chars)
        kept = set(i for i, c in enumerate(base_chars) if c == "_")

        for group in word_visual_groups:
            available = [i for i in group if base_chars[i] != "_" and i not in kept]
            if available:
                kept.add(random.choice(available))

        min_keep      = round(total_letters * 0.25)
        extra_needed  = max(0, min_keep - len(kept))
        remaining     = [i for i in range(total_letters) if i not in kept and base_chars[i] != "_"]
        if extra_needed and len(remaining) >= extra_needed:
            kept.update(random.sample(remaining, extra_needed))

        swappable = [i for i in range(total_letters) if i not in kept]
        random.shuffle(swappable)
        swap_pairs.clear()
        used = set()
        while len(swappable) >= 2:
            a = swappable.pop()
            b = swappable.pop()
            if base_chars[a] != base_chars[b]:
                swap_pairs.append((a, b))
                used.add(a); used.add(b)
        if swappable:
            kept.add(swappable[0])

        scrambled = base_chars[:]
        for a, b in swap_pairs:
            scrambled[a], scrambled[b] = scrambled[b], scrambled[a]

        swap_overlay_letters.clear()
        for i, char in enumerate(scrambled):
            if i not in target_coords:
                continue
            cx, cy = target_coords[i]
            correct = scrambled[i] == base_chars[i]
            if base_chars[i] == "_":
                char = "_"; correct = True
            swap_overlay_letters.append({
                "char":      char,
                "index":     i,
                "pos":       (cx, cy),
                "correct":   correct,
                "base_char": base_chars[i],
            })

        swap_completed    = 0
        swap_overlay_root = True

        # Build static base (creates overlays) then stamp all letters
        _build_swap_base()
        _swap_stamp_letters()

    # --- Trigger next swap animation ---
    if swap_completed < num_swaps and swap_completed < len(swap_pairs):
        a, b = swap_pairs[swap_completed]
        item_a = next((l for l in swap_overlay_letters if l["index"] == a), None)
        item_b = next((l for l in swap_overlay_letters if l["index"] == b), None)
        if item_a and item_b:
            _animate_swap_letters(item_a, item_b)
        swap_completed += 1


def _animate_swap_letters(letter_a, letter_b):
    steps = 10
    step  = [0]

    player = state.widgets.player
    root = state.widgets.root

    x0, y0 = letter_a["pos"]
    x1, y1 = letter_b["pos"]
    _, fg, _ = _swap_colors()
    skip = {letter_a["index"], letter_b["index"]}

    def get_arc_pos(t, p0, p1, up=True):
        try:
            osd_w = int(player._p.osd_width  or 0) or 1920
            osd_h = int(player._p.osd_height or 0) or 1080
        except Exception:
            osd_w, osd_h = 1920, 1080
        mod   = min(osd_w / 2560, osd_h / 1440)
        arc_h = max(20, int(40 * mod))
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        curve = arc_h * (1 - (2 * t - 1) ** 2)
        y -= curve if up else -curve
        return x, y

    def animate():
        global _swap_anim_after
        if _swap_letters_overlay is None:
            return
        t = step[0] / steps
        if t > 1.0:
            letter_a["char"], letter_b["char"] = letter_b["char"], letter_a["char"]
            letter_a["correct"] = True
            letter_b["correct"] = True
            _swap_stamp_letters()
            _swap_anim_after = None
            return
        ax, ay = get_arc_pos(t, (x0, y0), (x1, y1), up=True)
        bx, by = get_arc_pos(t, (x1, y1), (x0, y0), up=False)
        _swap_stamp_letters(skip_indices=skip, extra_letters=[
            (letter_a["char"], ax, ay, fg),
            (letter_b["char"], bx, by, fg),
        ])
        step[0] += 1
        _swap_anim_after = root.after(16, animate)

    animate()
