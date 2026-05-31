"""Tag-cloud lightning-round overlay — spirally lays out anime tags
around screen-centre, sized by weight, then reveals them one by one as
the timer counts down. Tag weights come from AniList (cubic-scaled
ranks) when available; otherwise from MAL-based weights with a "only
MAL tags" hint appended.

Extracted from `guess_the_anime.py`. Layout is precomputed once when
the OSD size or tag count changes, then each tick just re-issues a
fresh ASS payload with the first N tags visible.

``tag_cloud_tags`` is rebound externally — `clean_up_light_round` in
main resets it to `[]` between rounds. That write site is qualified as
``tag_cloud_overlay.tag_cloud_tags = []`` and the corresponding
`global` decl is trimmed (Python disallows qualified names in
`global`).

Owns the `_TAG_CLOUD_ASS_OSD_ID = 56` constant — moved here from
main's OSD-IDs cluster.
"""
from __future__ import annotations

import math
import random

from core.game_state import state


# ---------------------------------------------------------------------------
# Module state — `tag_cloud_tags` is read externally by main's lightning
# ticker (truthiness + len()) and reset to [] by clean_up_light_round.
# ---------------------------------------------------------------------------
tag_cloud_tags        = []
tag_cloud_positions   = []
_tag_cloud_last_osd_h = 0
_tag_cloud_font_sizes = []  # parallel to tag_cloud_tags; recomputed when osd_h changes

_TAG_CLOUD_ASS_OSD_ID = 56  # unique ID for osd-overlay (ASS-based) tag cloud


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
_osd_command           = None
_get_tags              = None
_color_str_to_ass_bgr  = None
_get_overlay_text_color = lambda: '#ffffff'
_get_overlay_background_color = lambda: '#000000'


def set_context(*, osd_command, get_tags, color_str_to_ass_bgr,
                get_overlay_text_color, get_overlay_background_color):
    g = globals()
    g['_osd_command'] = osd_command
    g['_get_tags'] = get_tags
    g['_color_str_to_ass_bgr'] = color_str_to_ass_bgr
    g['_get_overlay_text_color'] = get_overlay_text_color
    g['_get_overlay_background_color'] = get_overlay_background_color


def set_cloud_tags():
    global tag_cloud_tags
    currently_playing = state.playback.currently_playing
    anilist_metadata = state.metadata.anilist_metadata
    lightning_mode_settings = state.playback.lightning_mode_settings

    data = currently_playing.get("data")
    if data:
        tags = []
        use_anilist = lightning_mode_settings.get("tags", {}).get("use_anilist_tags", True)

        anilist_tags_found = False
        if use_anilist:
            anilist_id = data.get("anilist")
            if anilist_id and str(anilist_id) in anilist_metadata:
                anilist_data = anilist_metadata[str(anilist_id)]
                anilist_tags_list = anilist_data.get("tags", [])
                if anilist_tags_list:
                    # Use AniList tags with their rank as weight (rank is 0-100)
                    for tag in anilist_tags_list:
                        if not tag.get("spoiler", False):  # Skip spoiler tags
                            rank = tag.get("rank", 50)
                            # Use cubic scaling to create dramatic visual difference
                            weight = int(((rank / 100) ** 3) * 1000)
                            tags.append({
                                "name": tag.get("name", ""),
                                "weight": weight
                            })
                    anilist_tags_found = True

        if not anilist_tags_found and data.get("tags"):
            for tag in data.get("tags"):
                tags.append({"name": tag[0].replace(" - to be split and deleted", "").replace(" -- to be split and deleted", ""), "weight": tag[1]})

        if not tags:
            for tag in _get_tags(data):
                tags.append({"name": tag, "weight": 600})
            tags.append({"name": "only MAL tags", "weight": 600})
    else:
        tags = [
            {"name": "no tags found", "weight": 600}
        ]
    tag_cloud_tags = sorted(tags, key=lambda t: t["weight"], reverse=True)

    random.shuffle(tag_cloud_tags)
    if currently_playing.get("data", {}).get("season"):
        tag_cloud_tags.insert(0, {"name": currently_playing.get("data", {}).get("season")[-4:], "weight": 600})


def _compute_tag_font_sizes(osd_h):
    """Compute and cache font sizes for all tags based on current osd_h."""
    global _tag_cloud_font_sizes, _tag_cloud_last_osd_h
    _tag_cloud_last_osd_h = osd_h
    weights = [t["weight"] for t in tag_cloud_tags]
    if not weights:
        _tag_cloud_font_sizes = []
        return
    min_w, max_w = min(weights), max(weights)
    _fs_modifier = osd_h / 1440
    n = len(tag_cloud_tags)
    min_fs_ref = max(22, 60 - n)
    max_fs_ref = max(min_fs_ref + 40, 100 - n // 4)
    min_fs = max(10, round(min_fs_ref * _fs_modifier * 1.6))
    max_fs = max(min_fs + round(20 * _fs_modifier * 1.6), round(max_fs_ref * _fs_modifier * 1.6))
    fs_range = max_fs - min_fs
    sizes = []
    for t in tag_cloud_tags:
        normalized = (t["weight"] - min_w) / (max_w - min_w + 1e-5)
        amplified = normalized ** 2
        sizes.append(max(10, int(min_fs + fs_range * amplified)))
    _tag_cloud_font_sizes = sizes


def _plan_tag_cloud_layout(osd_w, osd_h):
    """Pre-compute positions for ALL tags at once, strictly within screen bounds.
    Falls back to smaller font sizes when a tag can't fit at its assigned size.
    Populates tag_cloud_positions and updates _tag_cloud_font_sizes in-place."""
    global tag_cloud_positions, _tag_cloud_font_sizes

    cx, cy = osd_w // 2, osd_h // 2
    top_margin    = round(osd_h * 0.12)
    bottom_margin = round(osd_h * 0.12)
    left_margin   = round(osd_w * 0.03)
    right_margin  = round(osd_w * 0.03)
    x_min, x_max = left_margin, osd_w - right_margin
    y_min, y_max = top_margin, osd_h - bottom_margin

    def est_dims(fs, text):
        w = round(len(text) * fs * 0.55)
        h = round(fs * 1.3)
        return w, h

    def overlaps_any(pos, placed):
        ax, ay, aw, ah = pos
        for bx, by, bw, bh in placed:
            if not (ax + aw < bx or ax > bx + bw or ay + ah < by or ay > by + bh):
                return True
        return False

    font_sizes = list(_tag_cloud_font_sizes)
    placed = []

    for i, tag in enumerate(tag_cloud_tags):
        text = tag["name"]
        placed_this = False
        # Try progressively smaller font sizes until the tag fits on-screen
        for fs_try in range(font_sizes[i], 9, -3):
            w, h = est_dims(fs_try, text)
            if w > (x_max - x_min) or h > (y_max - y_min):
                continue
            # Spiral outward from center; cap radius so tags stay on-screen
            angle, radius = 0.0, 0.0
            max_radius = max(osd_w, osd_h) * 0.7
            best_x = best_y = None
            while radius <= max_radius:
                x = max(x_min, min(int(cx + radius * math.cos(angle)) - w // 2, x_max - w))
                y = max(y_min, min(int(cy + radius * math.sin(angle)) - h // 2, y_max - h))
                if not overlaps_any((x, y, w, h), placed):
                    best_x, best_y = x, y
                    break
                angle += 0.5
                radius += 4
            if best_x is not None:
                font_sizes[i] = fs_try
                placed.append((best_x, best_y, w, h))
                placed_this = True
                break
        if not placed_this:
            # Absolute fallback: minimum size, clamped, ignoring overlaps
            w, h = est_dims(10, text)
            w = min(w, x_max - x_min)
            h = min(h, y_max - y_min)
            px = max(x_min, min(cx - w // 2, x_max - w))
            py = max(y_min, min(cy - h // 2, y_max - h))
            font_sizes[i] = 10
            placed.append((px, py, w, h))

    tag_cloud_positions = placed
    _tag_cloud_font_sizes = font_sizes


def toggle_tag_cloud_overlay(num_tags=1, destroy=False):
    global _tag_cloud_last_osd_h, _tag_cloud_font_sizes
    player = state.widgets.player

    if destroy:
        tag_cloud_positions.clear()
        _tag_cloud_font_sizes = []
        _tag_cloud_last_osd_h = 0
        try:
            _osd_command('osd-overlay', _TAG_CLOUD_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        return

    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    num_tags = min(num_tags, len(tag_cloud_tags))
    if not num_tags:
        return

    # Recompute font sizes (and clear cached positions) if osd_h changed
    if osd_h != _tag_cloud_last_osd_h or len(_tag_cloud_font_sizes) != len(tag_cloud_tags):
        _compute_tag_font_sizes(osd_h)
        tag_cloud_positions.clear()

    # Plan ALL positions up front on first call, guaranteeing on-screen placement
    if not tag_cloud_positions:
        _plan_tag_cloud_layout(osd_w, osd_h)

    # Build ASS payload for all visible tags
    OVERLAY_TEXT_COLOR = _get_overlay_text_color()
    OVERLAY_BACKGROUND_COLOR = _get_overlay_background_color()
    text_bgr = _color_str_to_ass_bgr(OVERLAY_TEXT_COLOR)
    bg_bgr   = _color_str_to_ass_bgr(OVERLAY_BACKGROUND_COLOR)
    lines = []
    for i in range(num_tags):
        tag = tag_cloud_tags[i]
        px, py, tw, th = tag_cloud_positions[i]
        fs  = _tag_cloud_font_sizes[i]
        tx  = px + tw // 2
        ty  = py + th // 2
        bord = max(2, round(fs * 0.12))
        # Bold text; border acts as per-glyph background (perfectly consistent padding)
        lines.append(
            f"{{\\an5\\pos({tx},{ty})\\1c&H{text_bgr}&\\1a&H00&"
            f"\\3c&H{bg_bgr}&\\3a&H40&\\bord{bord}\\shad0\\fs{fs}\\b1}}{tag['name']}"
        )
    ass_payload = "\n".join(lines)
    try:
        _osd_command('osd-overlay', _TAG_CLOUD_ASS_OSD_ID, 'ass-events',
                          ass_payload, osd_w, osd_h, 3, 'no')
    except Exception as e:
        print(f"Tag cloud OSD error: {e}")
