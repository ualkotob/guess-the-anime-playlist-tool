"""Episode + Names lightning-round overlay — shared ASS-based grid of up
to 6 boxes that reveal one-at-a-time.

Both modes share the same overlay (``toggle_episode_overlay``); the only
difference is the source list and how items are coloured:

* ``set_light_episodes`` populates ``light_episode_names`` with masked
  episode titles (overlapping anime-title words replaced by underscores).
* ``set_light_names`` populates the same list with ``[role, name]`` pairs
  (m / s / a → main / secondary / appears-in), and ``light_name_overlay``
  is flipped True so ``toggle_episode_overlay`` colours each box by role.

Extracted from `guess_the_anime.py`. ``light_episode_names`` and
``light_name_overlay`` are rebound externally — `clean_up_light_round`
resets both (qualified attribute writes), and `update_light_round`
flips ``light_name_overlay = True`` when starting the names mode (also
qualified). The corresponding `global` decls in main are trimmed.

Owns the ``_EPISODE_ASS_OSD_ID = 55`` constant — moved here from main's
OSD-IDs cluster.
"""
from __future__ import annotations

import re
import random

from core.game_state import state
import _app_scripts.playback.osd_text as osd_text
from . import title_overlay


# ---------------------------------------------------------------------------
# Module state — `light_episode_names` is read externally by main's
# lightning ticker (truthiness + len()) and reset to [] by
# clean_up_light_round. `light_name_overlay` is a boolean flag flipped by
# main when entering names mode and cleared on cleanup.
# ---------------------------------------------------------------------------
episode_overlay_boxes = {}     # active-box dict (cleared on destroy)
light_episode_names   = []     # list of episode titles OR [role, name] pairs
light_name_overlay    = False  # True while showing character names (colour-by-role)

_EPISODE_ASS_OSD_ID = 55  # unique ID for osd-overlay (ASS-based) episode title grid


def set_light_episodes():
    global light_episode_names
    fixed_current_round = state.lightning.fixed_current_round
    currently_playing = state.playback.currently_playing

    episode_names = []
    if fixed_current_round and fixed_current_round.get("episode1"):
        for num in range(6):
            if fixed_current_round.get(f"episode{num+1}"):
                episode_names.append(fixed_current_round.get(f"episode{num+1}"))
            else:
                break
        light_episode_names = episode_names
        return
    data = currently_playing.get("data")
    episodes = data.get("episode_info", []) if data else []
    base_title = title_overlay.get_base_title().lower()
    title_words = set(re.findall(r'\w+', base_title))  # Break base title into words

    if not data or not episodes:
        light_episode_names = ["No Episodes Found"]
        return

    # Score how many title words appear in each episode name
    def score_overlap(ep_name):
        words = set(re.findall(r'\w+', ep_name.lower()))
        return len(title_words & words)

    # Replace title words in the episode name with underscores
    def mask_title_words(text):
        def replace_word(match):
            word = match.group()
            return "_" * len(word) if word.lower() in title_words else word
        return re.sub(r'\w+', replace_word, text)

    # Shuffle and prioritize episodes with lower overlap first
    scored_episodes = sorted(episodes, key=lambda ep: score_overlap(ep[1]))
    episode_names = [mask_title_words(ep[1]) for ep in scored_episodes]

    light_episode_names = episode_names


def check_valid_episodes(data):
    valid_count = 0
    for ep in data.get("episode_info", []):
        valid = True
        if "episode" in ep[1].lower():
            for i in range(12):
                if f"episode {i}" == ep[1].lower():
                    valid = False
                    break
        if valid:
            valid_count += 1
        if valid_count >= 6:
            return True
    return False


def toggle_episode_overlay(num_episodes=6, destroy=False):
    """Episode title grid drawn via mpv osd-overlay (ASS).  Reveals up to num_episodes boxes."""
    player = state.widgets.player

    if destroy:
        episode_overlay_boxes.clear()
        try:
            osd_text.osd_command('osd-overlay', _EPISODE_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        return

    num_episodes = min(num_episodes, len(light_episode_names))
    if num_episodes == 0:
        return

    total_episodes = len(light_episode_names)
    selected_episodes = light_episode_names[:num_episodes]

    # Grid layout (same rules as before)
    if total_episodes == 1:
        columns, rows = 1, 1
    elif total_episodes == 2:
        columns, rows = 2, 1
    elif total_episodes == 3:
        columns, rows = 3, 1
    elif total_episodes == 4:
        columns, rows = 2, 2
    elif total_episodes == 5:
        columns, rows = 3, 2
    else:
        columns, rows = 2, 3

    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    modifier = min(osd_w / 2560, osd_h / 1440)
    bord_px = max(2, round(4 * modifier))   # border thickness
    gap = max(4, round(10 * modifier))       # gap between boxes

    grid_w = round(osd_w * 0.7)
    grid_h = round(osd_h * 0.7)
    box_width  = grid_w // columns
    box_height = grid_h // rows
    grid_start_x = (osd_w - box_width * columns) // 2
    grid_start_y = (osd_h - box_height * rows)   // 2

    pad_x = max(6, round(osd_w * 0.008))

    bg_alpha  = "19"  # ~90% opaque
    base_fs = max(10, round(55 * modifier * 1.6))

    OVERLAY_TEXT_COLOR = state.colors.OVERLAY_TEXT_COLOR
    OVERLAY_BACKGROUND_COLOR = state.colors.OVERLAY_BACKGROUND_COLOR
    text_bgr = osd_text._color_str_to_ass_bgr(OVERLAY_TEXT_COLOR)
    bg_bgr   = osd_text._color_str_to_ass_bgr(OVERLAY_BACKGROUND_COLOR)
    bord_bgr = osd_text._color_str_to_ass_bgr(OVERLAY_TEXT_COLOR)

    lines_payload = []
    for i, ep in enumerate(selected_episodes):
        title = ep
        _text_bgr = text_bgr
        _bg_bgr   = bg_bgr
        if light_name_overlay and isinstance(ep, (list, tuple)):
            _color_key = ep[0]
            title = ep[1]
            _bg_color = {"a": '#374151', "s": '#065F46', "m": '#1E3A8A'}.get(_color_key, '#374151')
            _bg_bgr   = osd_text._color_str_to_ass_bgr(_bg_color)
            _text_bgr = osd_text._color_str_to_ass_bgr("white")

        col = i % columns
        row = i // columns
        bx = grid_start_x + col * box_width
        by = grid_start_y + row * box_height
        # Inner box (inset by gap on each side)
        ix, iy = bx + gap, by + gap
        iw, ih = box_width - gap * 2, box_height - gap * 2

        text_area_w = iw - (pad_x + bord_px) * 2

        # Shrink font until text fits in ≤3 wrapped lines
        fs = base_fs
        text_lines = osd_text._ass_wrap_text(str(title), fs, text_area_w)
        while fs > 10 and len(text_lines) > 3:
            fs -= 1
            text_lines = osd_text._ass_wrap_text(str(title), fs, text_area_w)
        ass_text = '\\N'.join(text_lines)

        # Border rect
        lines_payload.append(
            f"{{\\an7\\pos({ix},{iy})"
            f"\\1c&H{bord_bgr}&\\1a&H00&\\bord0\\shad0\\p1}}"
            f"m 0 0 l {iw} 0 {iw} {ih} 0 {ih}{{\\p0}}"
        )
        # Fill rect (inset by border width)
        fx, fy = ix + bord_px, iy + bord_px
        fw, fh = iw - bord_px * 2, ih - bord_px * 2
        lines_payload.append(
            f"{{\\an7\\pos({fx},{fy})"
            f"\\1c&H{_bg_bgr}&\\1a&H{bg_alpha}&\\bord0\\shad0\\p1}}"
            f"m 0 0 l {fw} 0 {fw} {fh} 0 {fh}{{\\p0}}"
        )
        # Text (centered in inner box)
        cx = ix + iw // 2
        cy = iy + ih // 2
        lines_payload.append(
            f"{{\\an5\\pos({cx},{cy})"
            f"\\1c&H{_text_bgr}&\\1a&H00&"
            f"\\bord0\\shad0"
            f"\\fs{fs}\\b1}}{ass_text}"
        )
        episode_overlay_boxes[f"ep_{i}"] = True

    ass_payload = '\n'.join(lines_payload)
    try:
        osd_text.osd_command('osd-overlay', _EPISODE_ASS_OSD_ID, 'ass-events',
                          ass_payload, osd_w, osd_h, 3, 'no')
    except Exception as e:
        print(f"Episode overlay OSD error: {e}")


def set_light_names():
    global light_episode_names
    currently_playing = state.playback.currently_playing
    data = currently_playing.get("data")

    if data and data.get("characters"):
        main = []
        secondary = []
        appear = []
        for character in data["characters"]:
            name = character[1]
            if character[0] == "m":
                main.append([character[0], name])
            elif character[0] == "s":
                secondary.append([character[0], name])
            elif character[0] == "a":
                appear.append([character[0], name])

        # Shuffle all groups
        random.shuffle(main)
        random.shuffle(secondary)
        random.shuffle(appear)

        used_names = set()
        result = []

        # Helper to add up to n characters from a group without duplicates
        def add_unique(group, n):
            added = 0
            for char in group:
                if char[1] not in used_names:
                    result.append(char)
                    used_names.add(char[1])
                    added += 1
                if added == n:
                    break
            return added

        # Attempt to add 3 appear, 2 secondary, 1 main
        needed = 6
        needed -= add_unique(appear, 3)
        needed -= add_unique(secondary, 2)
        needed -= add_unique(main, 1)

        # Fill any leftovers from all characters
        remaining = appear + secondary + main
        for char in remaining:
            if needed == 0:
                break
            if char[1] not in used_names:
                result.append(char)
                used_names.add(char[1])
                needed -= 1

        light_episode_names = result[:6]  # Ensure only 6 are kept
