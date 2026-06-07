"""Thin mpv OSD progress bar for playback and lightning rounds."""

import json
import os
import time

from PIL import ImageColor

from core.game_state import state
from core.paths import CENSOR_JSON_FILE
import _app_scripts.playback.osd_text as osd_text
import _app_scripts.playback.progress_overlay as progress_overlay


_PROGRESS_ASS_OSD_ID = 52   # thin progress bar OSD overlay slot
_PROGRESS_BAR_HEIGHT_PCT = 0.008
_PROGRESS_BAR_ASS_ALPHA = 0xB2

# Last fraction drawn while a fixed lightning playlist was active. Used to
# freeze the bar across the inter-round transition (when light_round_started
# is briefly False and the next round hasn't registered yet) so it doesn't
# snap to the raw video position and back.
_last_fixed_fraction = None


def _draw_progress_osd(fraction, color_str="grey"):
    """Draw the progress bar OSD using ASS overlay."""
    player = state.widgets.player
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
        osd_text.osd_command("osd-overlay", _PROGRESS_ASS_OSD_ID, "ass-events", ass_payload, osd_w, osd_h, 2, "no")
    except Exception as e:
        print(f"Progress OSD error: {e}")


def _clear_progress_osd():
    try:
        osd_text.osd_command("osd-overlay", _PROGRESS_ASS_OSD_ID, "none", "", 0, 0, 0, "no")
    except Exception:
        pass


def _effective_remaining_ms(current_ms, total_ms, filename):
    """Remaining ms of audible content, subtracting upcoming skip-censor durations."""
    raw = max(0.0, total_ms - current_ms)
    # Lazy import: progress_bar (playback) sits below the censors toggle module.
    import _app_scripts.toggles.censors as censors
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
        if not os.path.exists(CENSOR_JSON_FILE):
            return current_time_ms, total_time_ms
        with open(CENSOR_JSON_FILE, "r", encoding="utf-8") as f:
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
    global _last_fixed_fraction
    if not state.controls.progress_bar_enabled:
        _clear_progress_osd()
        return

    fixed_active = bool(state.lightning.fixed_lightning_round_playlist_data)

    if state.lightning.light_round_started and state.lightning.light_round_start_time is not None:
        light_answer_wall_start = state.lightning.light_answer_wall_start
        light_round_length = state.lightning.light_round_length
        if light_answer_wall_start is not None:
            current_round_elapsed = light_round_length + (time.time() - light_answer_wall_start)
        else:
            current_round_elapsed = max(
                0.0,
                state.seek.projected_player_time / 1000.0 - state.lightning.light_round_start_time,
            )
        if fixed_active:
            playlist_progress = progress_overlay._get_fixed_playlist_progress(current_round_elapsed)
            if playlist_progress:
                current_time = playlist_progress[0] * 10
                total_time = playlist_progress[1] * 10
                filename = None
        else:
            round_total = light_round_length + state.lightning.light_round_answer_length
            current_time = min(current_round_elapsed, round_total) * 1000
            total_time = round_total * 1000
            filename = None
    elif fixed_active and _last_fixed_fraction is not None:
        # Between rounds of a fixed playlist (the next round hasn't registered
        # light_round_started/light_round_start_time yet): hold the bar at the
        # last playlist fraction instead of snapping to the raw video position.
        _draw_progress_osd(_last_fixed_fraction)
        return
    elif not fixed_active:
        _last_fixed_fraction = None

    if total_time <= 0:
        return

    effective_current_time, effective_total_time = _apply_skip_censor_to_progress(
        current_time,
        total_time,
        filename,
    )
    fraction = effective_current_time / effective_total_time
    if fixed_active:
        _last_fixed_fraction = fraction
    _draw_progress_osd(fraction)


def toggle_progress_bar():
    enabled = not state.controls.progress_bar_enabled
    state.controls.progress_bar_enabled = enabled
    print("Progress Bar Enabled: " + str(enabled))
    # Lazy import: progress_bar (playback) sits below the censors toggle module.
    import _app_scripts.toggles.censors as censors
    player = state.widgets.player
    censors.apply_censors(player.get_time() / 1000, player.get_length() / 1000)
    update_progress_bar(player.get_time(), player.get_length())
