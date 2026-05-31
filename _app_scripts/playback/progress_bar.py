"""Thin mpv OSD progress bar for playback and lightning rounds."""

import json
import os

from PIL import ImageColor


_ctx = {}

_PROGRESS_BAR_HEIGHT_PCT = 0.008
_PROGRESS_BAR_ASS_ALPHA = 0xB2


def set_context(
    *,
    player,
    osd_command,
    progress_osd_id,
    get_progress_bar_enabled,
    set_progress_bar_enabled,
    get_light_round_started,
    get_light_round_start_time,
    get_light_answer_wall_start,
    get_light_round_length,
    get_light_round_answer_length,
    get_projected_player_time,
    get_fixed_lightning_round_playlist_data,
    get_fixed_playlist_progress,
    wall_time,
    censors,
    censor_json_file,
    apply_censors,
):
    _ctx.clear()
    _ctx.update(locals())


def _draw_progress_osd(fraction, color_str="grey"):
    """Draw the progress bar OSD using ASS overlay."""
    player = _ctx["player"]
    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        osd_w, osd_h = 0, 0
    if not osd_w or not osd_h:
        return

    fill_w = max(0, int(osd_w * fraction))
    if fill_w <= 0:
        _clear_progress_osd()
        return

    bar_h = max(4, int(osd_h * _PROGRESS_BAR_HEIGHT_PCT))
    y0 = osd_h - bar_h

    try:
        rgb = ImageColor.getrgb(color_str)
    except Exception:
        rgb = (128, 128, 128)
    r, g, b = rgb
    color_hex = f"{b:02X}{g:02X}{r:02X}"
    alpha_hex = f"{_PROGRESS_BAR_ASS_ALPHA:02X}"

    path = f"m 0 {y0} l {fill_w} {y0} {fill_w} {osd_h} 0 {osd_h}"
    ass_payload = (
        f"{{\\an7\\pos(0,0)\\1c&H{color_hex}&\\1a&H{alpha_hex}&\\bord0\\shad0\\p1}}"
        + path
        + "{\\p0}"
    )
    try:
        _ctx["osd_command"]("osd-overlay", _ctx["progress_osd_id"], "ass-events", ass_payload, osd_w, osd_h, 2, "no")
    except Exception as e:
        print(f"Progress OSD error: {e}")


def _clear_progress_osd():
    try:
        _ctx["osd_command"]("osd-overlay", _ctx["progress_osd_id"], "none", "", 0, 0, 0, "no")
    except Exception:
        pass


def _effective_remaining_ms(current_ms, total_ms, filename):
    """Remaining ms of audible content, subtracting upcoming skip-censor durations."""
    raw = max(0.0, total_ms - current_ms)
    censors = _ctx["censors"]
    if not (censors.censors_enabled or censors.censors_nsfw_enabled) or not filename:
        return raw
    file_censors = censors.get_file_censors(filename) or []
    cur_s = current_ms / 1000.0
    skip_ahead_s = 0.0
    for c in file_censors:
        if not c.get("skip"):
            continue
        s = float(c.get("start", 0))
        e = float(c.get("end", 0))
        if e - s <= 0 or e <= cur_s:
            continue
        skip_ahead_s += e - max(s, cur_s)
    return max(0.0, raw - skip_ahead_s * 1000.0)


def _apply_skip_censor_to_progress(current_time_ms, total_time_ms, filename):
    """Adjust current/total time in ms to exclude skip-censor durations."""
    if not filename:
        return current_time_ms, total_time_ms
    try:
        censor_json_file = _ctx["censor_json_file"]
        if not os.path.exists(censor_json_file):
            return current_time_ms, total_time_ms
        with open(censor_json_file, "r", encoding="utf-8") as f:
            censor_data = json.load(f)
        file_censors = censor_data.get(filename, [])
        cur_s = current_time_ms / 1000.0
        tot_s = total_time_ms / 1000.0
        total_skip = 0.0
        skip_before = 0.0
        for censor in [c for c in file_censors if c.get("skip")]:
            s, e = censor["start"], censor["end"]
            dur = e - s
            if dur <= 0:
                continue
            total_skip += dur
            if e <= cur_s:
                skip_before += dur
            elif s < cur_s:
                skip_before += cur_s - s
        eff_cur = max(0.0, cur_s - skip_before) * 1000.0
        eff_tot = max(1.0, tot_s - total_skip) * 1000.0
        return eff_cur, eff_tot
    except Exception:
        return current_time_ms, total_time_ms


def update_progress_bar(current_time, total_time, filename=None):
    if not _ctx["get_progress_bar_enabled"]():
        _clear_progress_osd()
        return

    if _ctx["get_light_round_started"]() and _ctx["get_light_round_start_time"]() is not None:
        light_answer_wall_start = _ctx["get_light_answer_wall_start"]()
        light_round_length = _ctx["get_light_round_length"]()
        if light_answer_wall_start is not None:
            current_round_elapsed = light_round_length + (_ctx["wall_time"]() - light_answer_wall_start)
        else:
            current_round_elapsed = max(
                0.0,
                _ctx["get_projected_player_time"]() / 1000.0 - _ctx["get_light_round_start_time"](),
            )
        if _ctx["get_fixed_lightning_round_playlist_data"]():
            playlist_progress = _ctx["get_fixed_playlist_progress"](current_round_elapsed)
            if playlist_progress:
                current_time = playlist_progress[0] * 10
                total_time = playlist_progress[1] * 10
                filename = None
        else:
            round_total = light_round_length + _ctx["get_light_round_answer_length"]()
            current_time = min(current_round_elapsed, round_total) * 1000
            total_time = round_total * 1000
            filename = None

    if total_time <= 0:
        return

    effective_current_time, effective_total_time = _apply_skip_censor_to_progress(
        current_time,
        total_time,
        filename,
    )
    _draw_progress_osd(effective_current_time / effective_total_time)


def toggle_progress_bar():
    enabled = not _ctx["get_progress_bar_enabled"]()
    _ctx["set_progress_bar_enabled"](enabled)
    print("Progress Bar Enabled: " + str(enabled))
    player = _ctx["player"]
    _ctx["apply_censors"](player.get_time() / 1000, player.get_length() / 1000)
    update_progress_bar(player.get_time(), player.get_length())
