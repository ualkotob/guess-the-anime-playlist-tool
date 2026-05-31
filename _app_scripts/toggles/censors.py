"""
Censor boxes — OSD rendering, file loading, editor UI.
Extracted from guess_the_anime.py.
"""

import os
import json
import copy
import random as _random
import tkinter as tk
from tkinter import messagebox, simpledialog
from PIL import ImageColor
import numpy as np
import pyperclip
import pyautogui

from core.game_state import state

# ---------------------------------------------------------------------------
# Context (injected by set_context at startup)
# ---------------------------------------------------------------------------
_root = None
_player = None
_get_black_overlay = None          # lambda: black_overlay
_get_video_frame_active = None     # lambda: _video_frame_active
_get_effective_video_rect = None   # function ref
_osd_command_fn = None             # _osd_command function ref
_get_zoom_state = None             # lambda: (z, ox, oy) or None
_get_projected_player_time = None  # lambda: projected_player_time
_get_mismatch_visuals = None       # lambda: mismatch_visuals
_get_currently_streaming = None    # lambda: streaming.currently_streaming
_get_light_round_started = None    # lambda: light_round_started
_play_next_fn = None               # play_next function ref
_is_title_window_up = None         # is_title_window_up function ref
_get_mpv_client_rect_logical = None  # _get_mpv_client_rect_logical function ref
_get_file_metadata_by_name = None  # get_file_metadata_by_name function ref
_atomic_json_write_fn = None       # _atomic_json_write function ref
_get_window_position_and_setup = None  # get_window_position_and_setup function ref
_ToolTip = None                    # ToolTip class ref
_get_filter_state = None           # lambda: (variant, progress) or None when no filter active
_get_censor_filter_thresholds = None  # lambda: (blur_pct, pixelize_pct)

# Settings (injected by update_settings)
_CENSOR_JSON_FILE = "censors/censors.json"
_CENSORS_FOLDER = "censors"
_CENSOR_ASS_OSD_IDS = list(range(100, 140))
_BACKGROUND_COLOR = "gray12"


def set_context(
    root,
    player,
    get_black_overlay,
    get_video_frame_active,
    get_effective_video_rect,
    osd_command,
    get_projected_player_time,
    get_mismatch_visuals,
    get_currently_streaming,
    get_light_round_started,
    play_next_fn,
    is_title_window_up,
    get_mpv_client_rect_logical,
    get_file_metadata_by_name,
    atomic_json_write,
    get_window_position_and_setup,
    ToolTip_class,
    get_zoom_state=None,
    get_filter_state=None,
    get_censor_filter_thresholds=None,
):
    global _root, _player, _get_black_overlay, _get_video_frame_active
    global _get_effective_video_rect, _osd_command_fn, _get_projected_player_time
    global _get_mismatch_visuals, _get_currently_streaming
    global _get_light_round_started
    global _play_next_fn, _is_title_window_up, _get_mpv_client_rect_logical
    global _get_file_metadata_by_name, _atomic_json_write_fn
    global _get_window_position_and_setup
    global _ToolTip, _get_zoom_state, _get_filter_state, _get_censor_filter_thresholds
    _root = root
    _player = player
    _get_black_overlay = get_black_overlay
    _get_video_frame_active = get_video_frame_active
    _get_effective_video_rect = get_effective_video_rect
    _osd_command_fn = osd_command
    _get_projected_player_time = get_projected_player_time
    _get_mismatch_visuals = get_mismatch_visuals
    _get_currently_streaming = get_currently_streaming
    _get_light_round_started = get_light_round_started
    _play_next_fn = play_next_fn
    _is_title_window_up = is_title_window_up
    _get_mpv_client_rect_logical = get_mpv_client_rect_logical
    _get_file_metadata_by_name = get_file_metadata_by_name
    _atomic_json_write_fn = atomic_json_write
    _get_window_position_and_setup = get_window_position_and_setup
    _ToolTip = ToolTip_class
    if get_zoom_state is not None:
        _get_zoom_state = get_zoom_state
    if get_filter_state is not None:
        _get_filter_state = get_filter_state
    if get_censor_filter_thresholds is not None:
        _get_censor_filter_thresholds = get_censor_filter_thresholds


def update_settings(censor_json_file=None, censors_folder=None,
                    censor_ass_osd_ids=None, background_color=None):
    global _CENSOR_JSON_FILE, _CENSORS_FOLDER, _CENSOR_ASS_OSD_IDS, _BACKGROUND_COLOR
    if censor_json_file is not None:
        _CENSOR_JSON_FILE = censor_json_file
    if censors_folder is not None:
        _CENSORS_FOLDER = censors_folder
    if censor_ass_osd_ids is not None:
        _CENSOR_ASS_OSD_IDS = censor_ass_osd_ids
    if background_color is not None:
        _BACKGROUND_COLOR = background_color


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
censor_list = {}
other_censor_lists = []
_youtube_censor_list    = {}   # {filename: [censor, ...]} — populated at YouTube play time
_save_youtube_censors_fn = None
_get_yt_video_id_fn      = None
_is_youtube_file_fn      = None
censors_enabled = True
censors_nsfw_enabled = True

censor_boxes = {}
_censor_osd = None       # unused; kept so any stale references don't NameError
_censor_osd_img = None   # unused; kept so any stale references don't NameError
_censor_osd_last_size = (0, 0)  # (osd_w, osd_h) at last commit — redraw on resize

mute_censor_used = False

current_censors = {}
censor_editor = None
censor_editor_pinned = [False]
censor_entry_widgets = []
censor_page_offset = 0
save_censors_button = None


# ---------------------------------------------------------------------------
# OSD helpers
# ---------------------------------------------------------------------------
def _osd_command(*args):
    if _osd_command_fn:
        _osd_command_fn(*args)


def _commit_censor_osd():
    """Draw censor boxes via ASS osd-overlay (IDs 100–139), one slot per box."""
    global _censor_osd_last_size
    active = [(d["censor"], d.get("color", "black"))
              for d in censor_boxes.values() if not d.get("destroying")]

    def _clear_all_slots():
        for _sid in _CENSOR_ASS_OSD_IDS:
            _osd_command('osd-overlay', _sid, 'none', '', 0, 0, 0, 'no')

    # Hide while blind/black overlay is active.
    if not active or _get_black_overlay() is not None:
        _clear_all_slots()
        _censor_osd_last_size = (0, 0)
        return

    # Hide while blur/pixelize filter is suppressing censors.
    if _is_filter_suppressing_censors():
        _clear_all_slots()
        _censor_osd_last_size = (0, 0)
        return

    # Get actual mpv OSD (window) dimensions
    try:
        osd_w = int(_player._p.osd_width or 0)
        osd_h = int(_player._p.osd_height or 0)
    except Exception:
        osd_w, osd_h = 0, 0
    if not osd_w or not osd_h:
        osd_w = _root.winfo_screenwidth()
        osd_h = _root.winfo_screenheight()

    # Compute video rect within OSD space (letterbox/pillarbox aware, framed-video aware)
    if _get_video_frame_active():
        _, _, video_x, video_y, video_w, video_h = _get_effective_video_rect()
    else:
        try:
            vw, vh = _player.video_get_size(0)
        except Exception:
            vw, vh = 0, 0
        if vw and vh:
            if (vw == 720 and vh in (480, 478)) or (vw == 716 and vh == 478):
                ar = 16 / 9
            else:
                ar = vw / vh
            osd_ar = osd_w / osd_h
            if ar >= osd_ar:
                video_w = osd_w
                video_h = int(osd_w / ar)
                video_x = 0
                video_y = (osd_h - video_h) // 2
            else:
                video_h = osd_h
                video_w = int(osd_h * ar)
                video_x = (osd_w - video_w) // 2
                video_y = 0
        else:
            video_x, video_y, video_w, video_h = 0, 0, osd_w, osd_h

    def _to_ass_color(color_str):
        try:
            r, g, b = ImageColor.getrgb(color_str)[:3]
        except Exception:
            r, g, b = 0, 0, 0
        return f"&H{b:02X}{g:02X}{r:02X}&"

    used_slots = 0
    for censor, color_str in active:
        if used_slots >= len(_CENSOR_ASS_OSD_IDS):
            break
        cw = int(video_w * censor.get('size_w', 0.0) / 100)
        ch = int(video_h * censor.get('size_h', 0.0) / 100)
        if cw <= 0 or ch <= 0:
            continue
        cx = video_x + int((video_w - cw) * censor.get('pos_x', 0.0) / 100)
        cy = video_y + int((video_h - ch) * censor.get('pos_y', 0.0) / 100)
        # Apply zoom vf filter transform so censor boxes track the zoomed video.
        # The zoom filter crops a 1/z fraction of the frame then scales it back up;
        # we apply the same crop+scale to the censor box coordinates.
        if _get_zoom_state:
            _zs = _get_zoom_state()
            if _zs:
                _z, _ox, _oy = _zs
                # Normalise box to [0,1] video space
                _left_n  = (cx - video_x) / video_w
                _top_n   = (cy - video_y) / video_h
                _w_n     = cw / video_w
                _h_n     = ch / video_h
                # Crop origin in normalised video space (matches vf lavfi crop expr)
                _crop_x  = (1 - 1 / _z) * (0.5 + _ox)
                _crop_y  = (1 - 1 / _z) * (0.5 + _oy)
                # Map to display space
                _nl = (_left_n - _crop_x) * _z
                _nt = (_top_n  - _crop_y) * _z
                _nw = _w_n * _z
                _nh = _h_n * _z
                # Clip to visible area
                _cl = max(0.0, _nl);  _cr = min(1.0, _nl + _nw)
                _ct = max(0.0, _nt);  _cb = min(1.0, _nt + _nh)
                if _cr <= _cl or _cb <= _ct:
                    continue  # Censor scrolled off-screen
                cx = video_x + int(_cl * video_w)
                cy = video_y + int(_ct * video_h)
                cw = int((_cr - _cl) * video_w)
                ch = int((_cb - _ct) * video_h)
        ass_color = _to_ass_color(color_str)
        slot_id = _CENSOR_ASS_OSD_IDS[used_slots]
        rotation = censor.get('rotation') or 0.0
        shape    = censor.get('shape') or 'rect'
        import math as _math_osd
        rcx = cx + cw / 2
        rcy = cy + ch / 2
        hw_f, hh_f = cw / 2.0, ch / 2.0
        if rotation:
            _rad = _math_osd.radians(rotation)
            _cos_r, _sin_r = _math_osd.cos(_rad), _math_osd.sin(_rad)
            def _rot(lx, ly, _c=_cos_r, _s=_sin_r, _rcx=rcx, _rcy=rcy):
                return (int(_rcx + lx * _c - ly * _s),
                        int(_rcy + lx * _s + ly * _c))
        else:
            def _rot(lx, ly, _rcx=rcx, _rcy=rcy):
                return (int(_rcx + lx), int(_rcy + ly))
        if shape == 'ellipse':
            KAPPA = 0.5523
            kw, kh = hw_f * KAPPA, hh_f * KAPPA
            hw, hh = hw_f, hh_f
            pts = [_rot(x, y) for x, y in [
                (0, -hh),
                (kw, -hh), (hw, -kh), (hw, 0),
                (hw,  kh), (kw,  hh), (0,  hh),
                (-kw, hh), (-hw, kh), (-hw, 0),
                (-hw, -kh), (-kw, -hh), (0, -hh),
            ]]
            def _c(p): return f"{p[0]} {p[1]}"
            ass_payload = (
                f"{{\\an7\\pos(0,0)\\1c{ass_color}\\bord0\\shad0\\p1}}"
                f"m {_c(pts[0])} "
                f"b {_c(pts[1])} {_c(pts[2])} {_c(pts[3])} "
                f"b {_c(pts[4])} {_c(pts[5])} {_c(pts[6])} "
                f"b {_c(pts[7])} {_c(pts[8])} {_c(pts[9])} "
                f"b {_c(pts[10])} {_c(pts[11])} {_c(pts[12])}"
                f"{{\\p0}}"
            )
        else:
            p0 = _rot(-hw_f, -hh_f)
            p1 = _rot( hw_f, -hh_f)
            p2 = _rot( hw_f,  hh_f)
            p3 = _rot(-hw_f,  hh_f)
            ass_payload = (
                f"{{\\an7\\pos(0,0)\\1c{ass_color}\\bord0\\shad0\\p1}}"
                f"m {p0[0]} {p0[1]} l {p1[0]} {p1[1]} {p2[0]} {p2[1]} {p3[0]} {p3[1]}"
                f"{{\\p0}}"
            )
        try:
            _osd_command('osd-overlay', slot_id, 'ass-events',
                         ass_payload, osd_w, osd_h, -1, 'no')
        except Exception as e:
            print(f"Censor OSD slot {slot_id} error: {e}")
        used_slots += 1

    # Clear any unused slots from a previous call that had more boxes
    for slot_id in _CENSOR_ASS_OSD_IDS[used_slots:]:
        _osd_command('osd-overlay', slot_id, 'none', '', 0, 0, 0, 'no')

    _censor_osd_last_size = (osd_w, osd_h)


# ---------------------------------------------------------------------------
# Censor box management
# ---------------------------------------------------------------------------
def toggle_censor_box(filename, censor, enabled, time=None):
    censor_id = f"{filename}:{censor.get('pos_x', 0.0)}x{censor.get('pos_y', 0.0)}--{censor.get('size_w', 0.0)}x{censor.get('size_h', 0.0)}-{censor.get('start', 0)}-{censor.get('end', 0)}"
    if censor_id in censor_boxes:
        if not enabled and not censor_boxes[censor_id].get("destroying"):
            if time is None:
                time = _get_projected_player_time() / 1000
            censor_boxes[censor_id]["destroying"] = True
            def delete_censor(cid, cen):
                if cid not in censor_boxes:
                    return
                pj_time = _get_projected_player_time() / 1000
                _type_enabled = (censors_nsfw_enabled if cen.get('nsfw') else censors_enabled)
                if (_type_enabled and show_censor(cen, check_title=True)
                        and pj_time <= cen.get("end") and pj_time >= cen.get("start")
                        and not _is_filter_suppressing_censors()):
                    censor_boxes[cid]["destroying"] = False
                elif censor_boxes[cid].get("destroying"):
                    del censor_boxes[cid]
                    _commit_censor_osd()
            if time > censor.get("end") + 0.2:
                _root.after(200, delete_censor, censor_id, censor)
            else:
                delete_censor(censor_id, censor)
        elif enabled:
            censor_boxes[censor_id]["destroying"] = False
    elif enabled:
        censor_boxes[censor_id] = {
            "censor": censor,
            "color": "black",
            "destroying": False,
        }
    return censor_boxes.get(censor_id)




def remove_all_censor_boxes(filename=None):
    # If filename given, remove boxes for OTHER files (not the current one).
    # If no filename, remove everything.
    censors_to_delete = [cid for cid in censor_boxes if not filename or filename not in cid]
    for cid in censors_to_delete:
        del censor_boxes[cid]
    if not censor_boxes:
        for _sid in _CENSOR_ASS_OSD_IDS:
            _osd_command('osd-overlay', _sid, 'none', '', 0, 0, 0, 'no')


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------
def load_censors():
    global censor_list, other_censor_lists

    # Load main censor file
    if os.path.exists(_CENSOR_JSON_FILE):
        with open(_CENSOR_JSON_FILE, "r") as a:
            censor_list = json.load(a)
            print(f"Loaded censors for {len(censor_list)} files...")

    # Load all other JSON files in the censors folder as additional censor lists
    if os.path.exists(_CENSORS_FOLDER):
        main_basename = os.path.basename(_CENSOR_JSON_FILE)
        for fname in sorted(os.listdir(_CENSORS_FOLDER)):
            if fname.endswith(".json") and fname != main_basename:
                try:
                    with open(os.path.join(_CENSORS_FOLDER, fname), "r") as f:
                        data = json.load(f)
                        other_censor_lists.append(data)
                        print(f"Loaded {len(data)} entries from {fname}")
                except Exception as e:
                    print(f"Failed to load {fname}: {e}")


def _prime_start_censors(filename):
    """Immediately activate any censors whose start==0 for the incoming file."""
    if (not censors_enabled and not censors_nsfw_enabled) or _get_mismatch_visuals() or _get_currently_streaming():
        return
    file_censors = get_file_censors(filename)
    if not file_censors:
        return
    _osd_dirty = False
    for censor in file_censors:
        if censor.get('start', 1) != 0:
            continue
        if censor.get('mute') or censor.get('skip'):
            continue
        if censor.get('nsfw') and not censors_nsfw_enabled:
            continue
        if not censor.get('nsfw') and not censors_enabled:
            continue
        if not show_censor(censor, check_title=False):
            continue
        if _is_filter_suppressing_censors():
            continue
        entry = toggle_censor_box(filename, censor, True)
        if entry is not None:
            color = censor.get('color') or 'black'
            if entry.get('color') != color or not entry.get('committed'):
                entry['color'] = color
                _osd_dirty = True
    if _osd_dirty:
        _commit_censor_osd()
        for entry in censor_boxes.values():
            if not entry.get('destroying'):
                entry['committed'] = True


def apply_censors(time, length):
    """Apply Censors"""
    global censor_used, mute_censor_used
    if (censors_enabled or censors_nsfw_enabled) and not _get_mismatch_visuals() and not _get_currently_streaming():
        check_file_censors(state.playback.currently_playing.get('filename'), time, True)
    else:
        remove_all_censor_boxes()
        if mute_censor_used:
            _target_mute = (
                state.controls.light_muted
                if _get_light_round_started()
                else state.controls.disable_video_audio
            )
            _player.audio_set_mute(_target_mute)
            mute_censor_used = False


def toggle_censor_bar(toggle=None):
    global censors_enabled
    if toggle is not None:
        censors_enabled = toggle
    else:
        censors_enabled = not censors_enabled
    print("Censor Bar Enabled: " + str(censors_enabled))
    apply_censors(_player.get_time() / 1000, _player.get_length() / 1000)
    if not censors_enabled and not censors_nsfw_enabled:
        remove_all_censor_boxes()


def toggle_censor_nsfw_bar(toggle=None):
    global censors_nsfw_enabled
    if toggle is not None:
        censors_nsfw_enabled = toggle
    else:
        censors_nsfw_enabled = not censors_nsfw_enabled
    print("NSFW Censor Bar Enabled: " + str(censors_nsfw_enabled))
    apply_censors(_player.get_time() / 1000, _player.get_length() / 1000)
    if not censors_enabled and not censors_nsfw_enabled:
        remove_all_censor_boxes()


def set_youtube_context(save_youtube_censors_fn, get_video_id_from_filename_fn, is_youtube_file_fn):
    """Inject YouTube-specific censor save/load helpers. Call once at startup."""
    global _save_youtube_censors_fn, _get_yt_video_id_fn, _is_youtube_file_fn
    _save_youtube_censors_fn = save_youtube_censors_fn
    _get_yt_video_id_fn      = get_video_id_from_filename_fn
    _is_youtube_file_fn      = is_youtube_file_fn


def set_youtube_censors_for_file(filename, censors_list):
    """Populate the YouTube censor cache for *filename*. Call when a YouTube video starts."""
    if filename is not None:
        _youtube_censor_list[filename] = censors_list or []


def get_file_censors(filename):
    if not filename:
        return None
    if filename in _youtube_censor_list:
        return _youtube_censor_list[filename]
    filenames = [filename, filename.replace(".mp4", ".webm")]
    for f in filenames:
        file_censors = censor_list.get(f)
        if not file_censors:
            for c_list in other_censor_lists:
                other_file_censors = c_list.get(f)
                if other_file_censors:
                    return other_file_censors
        else:
            return file_censors
    return []


def show_censor(censor, check_title=True):
    return (not check_title or not _is_title_window_up() or censor.get("nsfw") or censor.get("skip"))


def _is_filter_suppressing_censors():
    """Return True when a blur/pixelize filter is active and its intensity exceeds the configured threshold."""
    if _get_filter_state is None:
        return False
    fs = _get_filter_state()
    if fs is None:
        return False
    variant, progress = fs
    if variant not in ('blur', 'pixelize'):
        return False
    thresholds = _get_censor_filter_thresholds() if _get_censor_filter_thresholds else (40, 40)
    blur_pct, pix_pct = thresholds
    intensity = (1.0 - progress) * 100.0
    threshold = blur_pct if variant == 'blur' else pix_pct
    return intensity >= threshold


def check_file_censors(filename, time, check_title=True):
    global censor_used, mute_censor_used

    file_censors = get_file_censors(filename)
    censor_found = False
    mute_found = False
    _image_color = None
    _osd_dirty = False
    if file_censors:
        for censor in file_censors:
            if censor.get('nsfw') and not censors_nsfw_enabled:
                toggle_censor_box(filename, censor, False)
                continue
            if not censor.get('nsfw') and not censors_enabled:
                toggle_censor_box(filename, censor, False)
                continue
            if show_censor(censor, check_title) and (time >= censor.get('start', 0) and time <= censor.get('end', 0)):
                if censor.get("skip"):
                    skip_length = censor.get('end', 0) - censor.get('start', 0)
                    if not _get_light_round_started() and time < censor.get('start', 0) + (skip_length / 4):
                        if censor.get('end', 0) < _player.get_length() / 1000:
                            _player.set_time(round(censor.get('end', 0) * 1000))
                        else:
                            _play_next_fn()
                    censor_found = True
                elif not censor.get("mute"):
                    if _is_filter_suppressing_censors():
                        toggle_censor_box(filename, censor, False)
                        continue
                    censor_entry = toggle_censor_box(filename, censor, True)
                    if censor_entry is not None:
                        _censor_color = censor.get("color") or _image_color
                        if not _censor_color:
                            _image_color = get_image_color()
                            _censor_color = _image_color or "black"
                        try:
                            _cur_osd_size = (int(_player._p.osd_width or 0), int(_player._p.osd_height or 0))
                        except Exception:
                            _cur_osd_size = (0, 0)
                        if censor_entry.get("color") != _censor_color or not censor_entry.get("committed") or _cur_osd_size != _censor_osd_last_size:
                            censor_entry["color"] = _censor_color
                            _osd_dirty = True
                else:
                    _player.audio_set_mute(True)
                    mute_censor_used = True
                    mute_found = True
                censor_found = True
            elif not (censor.get("mute") or censor.get("skip")):
                toggle_censor_box(filename, censor, False)

    if _osd_dirty:
        _commit_censor_osd()
        for entry in censor_boxes.values():
            if not entry.get("destroying"):
                entry["committed"] = True
        _osd_dirty = False

    if not mute_found and mute_censor_used:
        _target_mute = (
            state.controls.light_muted
            if _get_light_round_started()
            else state.controls.disable_video_audio
        )
        _player.audio_set_mute(_target_mute)
        mute_censor_used = False

    return censor_found


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def get_random_blind_color():
    return f"#{_random.randint(0, 0xFFFFFF):06x}"


def get_image_color():
    """Return the average colour of the current mpv video frame as a hex string.
    Areas covered by active censor boxes are excluded from the average.
    Falls back to a random color if no video frame is available.
    """
    fallback_color = get_random_blind_color()
    try:
        try:
            img = _player._p.screenshot_raw()
        except Exception:
            return fallback_color
        if img is None:
            return get_random_blind_color()
        arr = np.array(img.convert('RGB'))
        ih, iw = arr.shape[0], arr.shape[1]
        mask = np.ones((ih, iw), dtype=bool)
        active_censors = [d["censor"] for d in censor_boxes.values() if not d.get("destroying")]
        for censor in active_censors:
            cw = int(iw * censor.get('size_w', 0.0) / 100)
            ch = int(ih * censor.get('size_h', 0.0) / 100)
            if cw <= 0 or ch <= 0:
                continue
            cx = int((iw - cw) * censor.get('pos_x', 0.0) / 100)
            cy = int((ih - ch) * censor.get('pos_y', 0.0) / 100)
            mask[cy:cy + ch, cx:cx + cw] = False
        pixels = arr[mask]
        if len(pixels) == 0:
            # Censors cover the entire frame — sample the full frame instead
            pixels = arr.reshape(-1, 3)
        l = len(pixels)
        if l == 0:
            return get_random_blind_color()
        r, g, b = (int(pixels[:, i].sum() / l) for i in range(3))
        return rgbtohex(r, g, b)
    except Exception as e:
        print(f"get_image_color error: {e}")
        return get_random_blind_color()


def rgbtohex(r, g, b):
    return f'#{r:02x}{g:02x}{b:02x}'


def update_censor_button_count():
    currently_playing = state.playback.currently_playing
    if currently_playing.get("filename"):
        pass
        # if popout_buttons_by_name.get("censors"):
        #     popout_buttons_by_name["censors"].configure(text=f"CENSORS({censors_num})")


def on_play_starting():
    """Refresh censor state when a new track begins. Call before player.set_media()."""
    update_censor_button_count()
    if censor_editor:
        update_censor_editor_for_new_play()


def reset_for_new_file(filename):
    """Clear censor overlays and prime start-censors for *filename*. Call after player.set_media()."""
    remove_all_censor_boxes()
    if filename:
        _prime_start_censors(filename)


# ---------------------------------------------------------------------------
# RectangleDrawerOverlay
# ---------------------------------------------------------------------------
class RectangleDrawerOverlay:
    """
    Draw a selection on the mpv window, then enter an edit mode where:
      - Dragging outside the selection rotates it
      - Dragging a handle resizes it
      - Confirm/Redraw/Cancel buttons are embedded in the canvas (no popup window)
    """
    _HS  = 7   # handle half-size in pixels
    _HIT = 13  # handle hit-test radius

    def __init__(self, on_rectangle_picked, initial=None):
        """
        initial: dict with keys w_pct, h_pct, x_pct, y_pct, rotation (all floats, same units as _confirm output)
        If provided the overlay opens directly in edit mode with that selection pre-loaded.
        """
        import math as _math
        self._math = _math
        self.on_rectangle_picked = on_rectangle_picked

        mpv_x, mpv_y, mpv_w, mpv_h = _get_mpv_client_rect_logical()
        self.mpv_w, self.mpv_h = mpv_w, mpv_h

        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.geometry(f"{mpv_w}x{mpv_h}+{mpv_x}+{mpv_y}")
        self.root.attributes("-alpha", 0.55)
        self.root.attributes("-topmost", True)
        self.root.configure(cursor="cross")
        self.root.focus_force()

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Draw state
        self._draw_rect = None
        self.start_x = self.start_y = None

        # Edit state
        self.sel_cx = self.sel_cy = 0.0
        self.sel_w = self.sel_h = 0.0
        self.sel_rot = 0.0
        self.sel_shape = "rect"
        self._mode = "draw"
        self._drag_mode = None
        self._drag_ref = {}
        self._static_items = []
        self._dynamic_items = []
        self._rot_knob_x = -9999.0
        self._rot_knob_y = -9999.0

        # Compute video rect
        try:
            vw, vh = _player.video_get_size(0)
        except Exception:
            vw, vh = 0, 0
        if vw and vh:
            video_ar = 16/9 if ((vw == 720 and vh in (480, 478)) or (vw == 716 and vh == 478)) else vw/vh
            win_ar = mpv_w / mpv_h if mpv_h else 1
            if video_ar >= win_ar:
                self.video_w = mpv_w
                self.video_h = int(mpv_w / video_ar)
                self.video_x, self.video_y = 0, (mpv_h - self.video_h) // 2
            else:
                self.video_h = mpv_h
                self.video_w = int(mpv_h * video_ar)
                self.video_x, self.video_y = (mpv_w - self.video_w) // 2, 0
        else:
            self.video_x = self.video_y = 0
            self.video_w, self.video_h = mpv_w, mpv_h

        if self.video_x > 0 or self.video_y > 0:
            self.canvas.create_rectangle(
                self.video_x, self.video_y,
                self.video_x + self.video_w, self.video_y + self.video_h,
                outline="green", width=3, dash=(10, 5))

        self.canvas.bind("<ButtonPress-1>",   self._draw_press)
        self.canvas.bind("<B1-Motion>",       self._draw_drag)
        self.canvas.bind("<ButtonRelease-1>", self._draw_release)
        self.root.bind("<Escape>",            lambda e: self.root.destroy())
        self.root.bind("<ButtonRelease-2>",   lambda e: self.root.destroy())

        if initial:
            try:
                w_px  = self.video_w * initial['w_pct'] / 100
                h_px  = self.video_h * initial['h_pct'] / 100
                cx = self.video_x + (self.video_w - w_px) * initial['x_pct'] / 100 + w_px / 2
                cy = self.video_y + (self.video_h - h_px) * initial['y_pct'] / 100 + h_px / 2
                self.sel_cx, self.sel_cy = cx, cy
                self.sel_w,  self.sel_h  = w_px, h_px
                self.sel_rot = initial.get('rotation', 0.0)
                self.sel_shape = initial.get('shape', 'rect') or 'rect'
                self._mode = "edit"
                self.root.after(10, self._enter_edit)
            except Exception as _e:
                print("RectangleDrawerOverlay: bad initial values:", _e)

    # ------------------------------------------------------------------ snapping helpers

    def _should_snap(self):
        rot = self.sel_rot % 360
        return self.sel_shape == 'rect' and (rot < 0.5 or rot > 359.5)

    def _clamp_to_video(self):
        if not self._should_snap():
            return
        if self.video_w <= 0 or self.video_h <= 0:
            return
        if self.sel_w > self.video_w:
            self.sel_w = float(self.video_w)
        if self.sel_h > self.video_h:
            self.sel_h = float(self.video_h)
        hw, hh = self.sel_w / 2, self.sel_h / 2
        self.sel_cx = max(self.video_x + hw, min(self.video_x + self.video_w  - hw, self.sel_cx))
        self.sel_cy = max(self.video_y + hh, min(self.video_y + self.video_h - hh, self.sel_cy))

    def _clamp_xy_to_video(self, x, y):
        x = max(self.video_x, min(self.video_x + self.video_w, x))
        y = max(self.video_y, min(self.video_y + self.video_h, y))
        return x, y

    # ------------------------------------------------------------------ math

    def _to_screen(self, lx, ly):
        m = self._math
        r = m.radians(self.sel_rot)
        c, s = m.cos(r), m.sin(r)
        return (self.sel_cx + lx*c - ly*s,
                self.sel_cy + lx*s + ly*c)

    def _to_local(self, sx, sy):
        m = self._math
        r = m.radians(self.sel_rot)
        c, s = m.cos(r), m.sin(r)
        dx, dy = sx - self.sel_cx, sy - self.sel_cy
        return c*dx + s*dy, -s*dx + c*dy

    def _corners(self):
        hw, hh = self.sel_w/2, self.sel_h/2
        return [self._to_screen(lx, ly) for lx, ly in [(-hw,-hh),(hw,-hh),(hw,hh),(-hw,hh)]]

    def _handles(self):
        hw, hh = self.sel_w/2, self.sel_h/2
        pts = [("nw",-hw,-hh), ("n",0,-hh), ("ne",hw,-hh),
               ("e", hw, 0),
               ("se",hw, hh), ("s",0, hh), ("sw",-hw,hh),
               ("w",-hw, 0)]
        return [(n, self._to_screen(lx, ly)) for n, lx, ly in pts]

    def _hit_handle(self, mx, my):
        for name, (hx, hy) in self._handles():
            if abs(mx-hx) <= self._HIT and abs(my-hy) <= self._HIT:
                return name
        return None

    def _in_selection(self, mx, my):
        lx, ly = self._to_local(mx, my)
        return abs(lx) <= self.sel_w/2 and abs(ly) <= self.sel_h/2

    # ------------------------------------------------------------------ draw mode

    def _draw_press(self, event):
        self.start_x, self.start_y = self._clamp_xy_to_video(event.x, event.y)
        self._draw_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#FF3333", width=3, fill="")

    def _draw_drag(self, event):
        sx, sy = self.start_x, self.start_y
        ex, ey = self._clamp_xy_to_video(event.x, event.y)
        self.canvas.coords(self._draw_rect,
                           min(sx, ex), min(sy, ey),
                           max(sx, ex), max(sy, ey))

    def _draw_release(self, event):
        ex, ey = self._clamp_xy_to_video(event.x, event.y)
        w = abs(ex - self.start_x)
        h = abs(ey - self.start_y)
        if w < 4 or h < 4:
            return
        self.sel_cx = (self.start_x + ex) / 2
        self.sel_cy = (self.start_y + ey) / 2
        self.sel_w, self.sel_h, self.sel_rot = w, h, 0.0
        self.canvas.delete(self._draw_rect)
        self._draw_rect = None
        self.canvas.unbind("<ButtonPress-1>")
        self.canvas.unbind("<B1-Motion>")
        self.canvas.unbind("<ButtonRelease-1>")
        self._mode = "edit"
        self._enter_edit()

    # ------------------------------------------------------------------ edit mode

    def _enter_edit(self):
        self._setup_static_ui()
        self._redraw_selection()
        self.canvas.bind("<ButtonPress-1>",   self._edit_press)
        self.canvas.bind("<B1-Motion>",       self._edit_drag)
        self.canvas.bind("<ButtonRelease-1>", self._edit_release)
        self.canvas.bind("<Motion>",          self._edit_motion)

    def _setup_static_ui(self):
        FONT    = ("Arial", 11, "bold")
        FONT_SM = ("Arial", 10)

        bar = tk.Frame(self.canvas, bg="#1e1e1e", bd=0)
        tk.Button(bar, text="\u2714 Confirm", font=FONT, bg="#226622", fg="white",
                  bd=0, relief="flat", command=self._confirm).pack(side="left", padx=6, pady=4)
        tk.Button(bar, text="\u21a9 Redraw",  font=FONT, bg="#555555", fg="white",
                  bd=0, relief="flat", command=self._do_redraw).pack(side="left", padx=6, pady=4)
        tk.Button(bar, text="\u2715 Cancel",  font=FONT, bg="#662222", fg="white",
                  bd=0, relief="flat", command=self.root.destroy).pack(side="left", padx=6, pady=4)
        tk.Frame(bar, bg="#444", width=1).pack(side="left", fill="y", padx=8, pady=4)
        _full_btn = tk.Button(bar, text="\u26f6 Full",    font=FONT_SM, bg="#334", fg="white",
                  bd=0, relief="flat", command=self._snap_fullscreen)
        _full_btn.pack(side="left", padx=4, pady=4)
        _ToolTip(_full_btn, "Expand selection to cover the entire video")
        _rot0_btn = tk.Button(bar, text="\u21ba 0\u00b0",      font=FONT_SM, bg="#334", fg="#FFFF00",
                  bd=0, relief="flat", command=self._reset_rotation)
        _rot0_btn.pack(side="left", padx=4, pady=4)
        _ToolTip(_rot0_btn, "Reset rotation to 0\u00b0")
        _shape_labels = {'rect': '\u25ad Rect', 'ellipse': '\u2b2d Ellipse'}
        self._shape_btn = tk.Button(bar, text=_shape_labels[self.sel_shape],
                                    font=FONT_SM, bg="#334", fg="white",
                                    bd=0, relief="flat", command=self._toggle_shape)
        self._shape_btn.pack(side="left", padx=4, pady=4)
        _ToolTip(self._shape_btn, "Toggle censor shape between rectangle and ellipse")
        self._static_items.append(
            self.canvas.create_window(self.mpv_w // 2, self.mpv_h - 10,
                                      window=bar, anchor="s"))

        snap = tk.Frame(self.canvas, bg="#1e1e1e")
        bkw = dict(font=("Arial", 11), bg="#334", fg="white", width=2, bd=1, relief="raised")
        tk.Label(snap, text="Snap", font=("Arial", 9), bg="#1e1e1e", fg="#aaa").grid(row=0, column=0, columnspan=3, pady=(2, 0))
        _s_up  = tk.Button(snap, text="\u2191",  command=self._snap_top,     **bkw); _s_up.grid(row=1, column=1, padx=2, pady=2);  _ToolTip(_s_up,  "Snap top edge to video boundary")
        _s_lft = tk.Button(snap, text="\u2190",  command=self._snap_left,    **bkw); _s_lft.grid(row=2, column=0, padx=2, pady=2); _ToolTip(_s_lft, "Snap left edge to video boundary")
        _s_ctr = tk.Button(snap, text="\u25a3",  command=self._snap_center,  **bkw); _s_ctr.grid(row=2, column=1, padx=2, pady=2); _ToolTip(_s_ctr, "Centre selection in the video")
        _s_rgt = tk.Button(snap, text="\u2192",  command=self._snap_right,   **bkw); _s_rgt.grid(row=2, column=2, padx=2, pady=2); _ToolTip(_s_rgt, "Snap right edge to video boundary")
        _s_dn  = tk.Button(snap, text="\u2193",  command=self._snap_bottom,  **bkw); _s_dn.grid(row=3, column=1, padx=2, pady=2);  _ToolTip(_s_dn,  "Snap bottom edge to video boundary")
        self._static_items.append(
            self.canvas.create_window(self.mpv_w - 8, 8, window=snap, anchor="ne"))

        self._static_items.append(
            self.canvas.create_text(
                10, 10,
                text="Drag yellow circle = rotate   |   Drag handles = resize   |   Drag inside box = move",
                anchor="nw", fill="#aaaaaa", font=("Arial", 10)))

    def _toggle_shape(self):
        self.sel_shape = 'ellipse' if self.sel_shape == 'rect' else 'rect'
        _labels = {'rect': '\u25ad Rect', 'ellipse': '\u2b2d Ellipse'}
        self._shape_btn.config(text=_labels[self.sel_shape])
        self._redraw_selection()

    def _reset_rotation(self):
        self.sel_rot = 0.0
        self._redraw_selection()

    def _snap_fullscreen(self):
        self.sel_cx  = self.video_x + self.video_w / 2
        self.sel_cy  = self.video_y + self.video_h / 2
        self.sel_w   = self.video_w
        self.sel_h   = self.video_h
        self.sel_rot = 0.0
        self._redraw_selection()

    def _snap_left(self):
        self.sel_cx = self.video_x + self.sel_w / 2
        self._redraw_selection()

    def _snap_right(self):
        self.sel_cx = self.video_x + self.video_w - self.sel_w / 2
        self._redraw_selection()

    def _snap_top(self):
        self.sel_cy = self.video_y + self.sel_h / 2
        self._redraw_selection()

    def _snap_bottom(self):
        self.sel_cy = self.video_y + self.video_h - self.sel_h / 2
        self._redraw_selection()

    def _snap_center(self):
        self.sel_cx = self.video_x + self.video_w / 2
        self.sel_cy = self.video_y + self.video_h / 2
        self._redraw_selection()

    def _redraw_selection(self):
        for item in self._dynamic_items:
            self.canvas.delete(item)
        self._dynamic_items.clear()

        if self.sel_shape == 'ellipse':
            import math as _m
            hw, hh = self.sel_w / 2, self.sel_h / 2
            pts = []
            for i in range(60):
                a = _m.radians(i * 6)
                pts.append(self._to_screen(hw * _m.cos(a), hh * _m.sin(a)))
            flat = [v for p in pts for v in p]
            self._dynamic_items.append(
                self.canvas.create_polygon(*flat, outline="#FF3333", width=3,
                                           fill="#FF3333", stipple="gray25", smooth=False))
        else:
            pts = self._corners()
            flat = [v for p in pts for v in p]
            self._dynamic_items.append(
                self.canvas.create_polygon(*flat, outline="#FF3333", width=3,
                                           fill="#FF3333", stipple="gray25"))

        tc_x, tc_y = self._to_screen(0, -self.sel_h/2)
        tx, ty = self._to_screen(0, -self.sel_h/2 - 36)
        self._rot_knob_x, self._rot_knob_y = tx, ty
        self._dynamic_items += [
            self.canvas.create_line(tc_x, tc_y, tx, ty,
                                    fill="#FFFF00", width=2, dash=(6, 3)),
            self.canvas.create_oval(tx-8, ty-8, tx+8, ty+8,
                                    fill="#FFFF00", outline="#cccc00", width=2)]

        rot_label = f"{self.sel_rot:.1f}\u00b0"
        self._dynamic_items.append(
            self.canvas.create_text(tx + 12, ty, text=rot_label,
                                    anchor="w", fill="#FFFF00", font=("Arial", 9)))

        HS = self._HS
        for name, (hx, hy) in self._handles():
            self._dynamic_items.append(
                self.canvas.create_rectangle(hx-HS, hy-HS, hx+HS, hy+HS,
                                             fill="white", outline="#333333", width=1))

    def _hit_rot_knob(self, mx, my):
        return (abs(mx - self._rot_knob_x) <= self._HIT and
                abs(my - self._rot_knob_y) <= self._HIT)

    def _edit_motion(self, event):
        mx, my = event.x, event.y
        if self._hit_rot_knob(mx, my):
            self.root.configure(cursor="exchange")
        elif self._hit_handle(mx, my):
            self.root.configure(cursor="sizing")
        elif self._in_selection(mx, my):
            self.root.configure(cursor="fleur")
        else:
            self.root.configure(cursor="")

    def _edit_press(self, event):
        mx, my = event.x, event.y
        if self._hit_rot_knob(mx, my):
            self._drag_mode = "rotate"
            angle = self._math.atan2(my - self.sel_cy, mx - self.sel_cx)
            self._drag_ref = dict(angle0=angle, rot0=self.sel_rot)
        else:
            handle = self._hit_handle(mx, my)
            if handle:
                self._drag_mode = f"resize_{handle}"
                self._drag_ref = dict(cx=self.sel_cx, cy=self.sel_cy,
                                      w=self.sel_w,   h=self.sel_h,
                                      rot=self.sel_rot)
            elif self._in_selection(mx, my):
                self._drag_mode = "move"
                self._drag_ref = dict(mx0=mx, my0=my,
                                      cx0=self.sel_cx, cy0=self.sel_cy)
            else:
                self._drag_mode = None

    def _edit_drag(self, event):
        mx, my = event.x, event.y
        mode = self._drag_mode
        if not mode:
            return

        if mode == "rotate":
            curr = self._math.atan2(my - self.sel_cy, mx - self.sel_cx)
            delta = self._math.degrees(curr - self._drag_ref["angle0"])
            self.sel_rot = (self._drag_ref["rot0"] + delta) % 360
            self._redraw_selection()

        elif mode == "move":
            ref = self._drag_ref
            self.sel_cx = ref["cx0"] + (mx - ref["mx0"])
            self.sel_cy = ref["cy0"] + (my - ref["my0"])
            self._clamp_to_video()
            self._redraw_selection()

        elif mode.startswith("resize_"):
            handle = mode[7:]
            ref = self._drag_ref
            old_cx, old_cy = ref["cx"], ref["cy"]
            old_w,  old_h  = ref["w"],  ref["h"]
            old_rot        = ref["rot"]
            self.sel_cx, self.sel_cy = old_cx, old_cy
            self.sel_w,  self.sel_h  = old_w,  old_h
            self.sel_rot             = old_rot
            lx, ly = self._to_local(mx, my)
            hw0, hh0 = old_w/2, old_h/2
            new_hw, new_hh = hw0, hh0
            dcx, dcy = 0.0, 0.0
            if "e" in handle:
                new_hw = max(6, (lx + hw0) / 2);  dcx = (lx - hw0) / 2
            if "w" in handle:
                new_hw = max(6, (hw0 - lx) / 2);  dcx = (lx + hw0) / 2
            if "s" in handle:
                new_hh = max(6, (ly + hh0) / 2);  dcy = (ly - hh0) / 2
            if "n" in handle:
                new_hh = max(6, (hh0 - ly) / 2);  dcy = (ly + hh0) / 2
            self.sel_w = new_hw * 2
            self.sel_h = new_hh * 2
            m = self._math
            r = m.radians(old_rot)
            c, s = m.cos(r), m.sin(r)
            self.sel_cx = old_cx + dcx*c - dcy*s
            self.sel_cy = old_cy + dcx*s + dcy*c
            self._clamp_to_video()
            self._redraw_selection()

    def _edit_release(self, event):
        self._drag_mode = None
        self._drag_ref = {}

    # ------------------------------------------------------------------ actions

    def _confirm(self):
        cx, cy = self.sel_cx, self.sel_cy
        w,  h  = self.sel_w,  self.sel_h
        left   = cx - w/2
        top    = cy - h/2
        vl     = left - self.video_x
        vt     = top  - self.video_y
        x_pct  = (vl / (self.video_w - w)) * 100 if (self.video_w - w) > 0 else 0
        y_pct  = (vt / (self.video_h - h)) * 100 if (self.video_h - h) > 0 else 0
        w_pct  = w / self.video_w * 100 if self.video_w > 0 else 0
        h_pct  = h / self.video_h * 100 if self.video_h > 0 else 0
        w_pct  = max(0.0, w_pct)
        h_pct  = max(0.0, h_pct)
        rot    = round(self.sel_rot, 2)
        result = f"{w_pct:.2f}x{h_pct:.2f},{x_pct:.2f}x{y_pct:.2f},{rot:.2f},{self.sel_shape}"
        pyperclip.copy(result)
        self.on_rectangle_picked(result)
        self.root.destroy()

    def _do_redraw(self):
        for item in self._static_items + self._dynamic_items:
            self.canvas.delete(item)
        self._static_items.clear()
        self._dynamic_items.clear()
        self._drag_mode = None
        self._drag_ref = {}
        self._mode = "draw"
        self.canvas.unbind("<Motion>")
        self.canvas.unbind("<ButtonPress-1>")
        self.canvas.unbind("<B1-Motion>")
        self.canvas.unbind("<ButtonRelease-1>")
        self.canvas.bind("<ButtonPress-1>",   self._draw_press)
        self.canvas.bind("<B1-Motion>",       self._draw_drag)
        self.canvas.bind("<ButtonRelease-1>", self._draw_release)
        self.root.configure(cursor="cross")

    def edge_round(self, position):
        if position < 1:
            return 0
        elif position > 99:
            return 100
        return position


# ---------------------------------------------------------------------------
# ColorPickerOverlay
# ---------------------------------------------------------------------------
class ColorPickerOverlay:
    def __init__(self, on_color_picked):
        self.on_color_picked = on_color_picked
        self.root = tk.Toplevel()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(cursor="cross", bg="black")

        self._preview = tk.Toplevel(self.root)
        self._preview.wm_overrideredirect(True)
        self._preview.attributes("-topmost", True)
        self._preview.attributes("-alpha", 0.92)
        self._swatch = tk.Label(self._preview, width=8, height=2, relief="solid", bd=1)
        self._swatch.pack()
        self._hex_label = tk.Label(self._preview, font=("Consolas", 11, "bold"),
                                   width=9, relief="solid", bd=0, padx=4, pady=2)
        self._hex_label.pack()
        self._after_id = None
        self.root.bind("<Motion>", self._on_motion)
        self.root.bind("<Button-1>", self.on_click)
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<ButtonRelease-2>", lambda e: self.root.destroy())

    def _on_motion(self, event):
        if self._after_id:
            return
        self._after_id = self.root.after(33, lambda: self._update_preview(event.x_root, event.y_root))

    def _update_preview(self, x, y):
        self._after_id = None
        try:
            color = pyautogui.screenshot(region=(x, y, 1, 1)).getpixel((0, 0))
            hex_color = '#{:02X}{:02X}{:02X}'.format(*color[:3])
            brightness = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            fg = "black" if brightness > 128 else "white"
            self._swatch.config(bg=hex_color)
            self._hex_label.config(text=hex_color, bg=hex_color, fg=fg)
            self._preview.wm_geometry(f"+{x+20}+{y+20}")
        except Exception:
            pass

    def on_click(self, event):
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._preview.destroy()
        self.root.attributes("-alpha", 0.0)
        self.root.update()

        color = pyautogui.screenshot().getpixel((event.x_root, event.y_root))
        hex_color = '#{:02X}{:02X}{:02X}'.format(*color)
        pyperclip.copy(hex_color)

        self.on_color_picked(hex_color)
        self.root.after(100, self.root.destroy)


# ---------------------------------------------------------------------------
# Title/slug helpers
# ---------------------------------------------------------------------------
def extract_title_and_slug_from_filename(filename):
    """Extracts the title part, slug, and version from an anime filename."""
    try:
        parts = filename.split("-")
        if len(parts) >= 2:
            title_part = parts[0]

            file_data = _get_file_metadata_by_name(filename)
            if file_data and file_data.get('slug'):
                slug = file_data['slug']
                version = file_data.get('version')
            else:
                slug = parts[1].split(".")[0].split("v")[0]
                version_part = parts[1].split(".")[0]
                if "v" in version_part:
                    version = version_part.split("v")[1] if len(version_part.split("v")) > 1 else None
                else:
                    version = None

            return title_part, slug, version
    except Exception:
        pass
    return None, None, None


def find_similar_theme_censors(current_filename):
    """Finds censors from files with the same title and slug but different versions/quality."""
    current_title, current_slug, current_version = extract_title_and_slug_from_filename(current_filename)

    if not current_title or not current_slug:
        return {}

    similar_censors = {}

    for filename, censors in censor_list.items():
        if filename == current_filename:
            continue
        title, slug, version = extract_title_and_slug_from_filename(filename)
        if title == current_title and slug == current_slug:
            similar_censors[filename] = censors

    for c_list in other_censor_lists:
        for filename, censors in c_list.items():
            if filename == current_filename:
                continue
            title, slug, version = extract_title_and_slug_from_filename(filename)
            if title == current_title and slug == current_slug:
                similar_censors[filename] = censors

    return similar_censors


# ---------------------------------------------------------------------------
# Censor editor
# ---------------------------------------------------------------------------
def update_censor_editor_for_new_play():
    """Update the censor editor with new censors data when a new song plays, preserving window position."""
    global current_censors, censor_editor, censor_page_offset, censor_entry_widgets

    if not censor_editor:
        return

    filename = state.playback.currently_playing.get("filename")
    if filename:
        current_censors = copy.deepcopy(get_file_censors(filename))

    censor_editor.title(f"Censor Editor for {filename}")

    censor_page_offset = 0

    for widgets in censor_entry_widgets:
        for widget in widgets:
            widget.destroy()
    censor_entry_widgets.clear()

    open_censor_editor(refresh_only=True)


def open_censor_editor(refresh=False, refresh_only=False, filename=None):
    global current_censors, censor_editor, censor_entry_widgets
    global censor_page_offset
    global save_censors_button

    CENSORS_PER_PAGE = 10

    def censor_editor_close():
        global censor_editor, censor_entry_widgets, censor_page_offset
        censor_entry_widgets = []
        censor_page_offset = 0
        censor_editor.destroy()
        censor_editor = None

    if filename is None:
        filename = state.playback.currently_playing.get("filename")
    if filename:
        current_censors = copy.deepcopy(get_file_censors(filename))

    font_size = 14
    font_big = ("Arial", font_size)
    fg_color = "white"
    bg_color = "black"
    row_pady = 0
    entry_ipady = 4
    _similar_censors_cache = find_similar_theme_censors(filename) if filename else {}

    if censor_editor:
        if refresh_only:
            censor_editor.title(f"Censor Editor for {filename}")
            for widgets in censor_entry_widgets:
                for widget in widgets:
                    if widget.winfo_exists():
                        widget.destroy()
            censor_entry_widgets.clear()
            for widget in list(censor_editor.winfo_children()):
                try:
                    row = int(widget.grid_info().get("row", -1))
                    if row >= 999:
                        widget.destroy()
                except Exception:
                    pass
        else:
            censor_editor_close()
            if not refresh:
                return
            censor_editor = tk.Toplevel()
            censor_editor.configure(bg=_BACKGROUND_COLOR)
            censor_editor.protocol("WM_DELETE_WINDOW", censor_editor_close)
            _get_window_position_and_setup(censor_editor)
            censor_editor.attributes("-topmost", bool(censor_editor_pinned[0]))
    else:
        censor_editor = tk.Toplevel()
        censor_editor.configure(bg=_BACKGROUND_COLOR)
        censor_editor.protocol("WM_DELETE_WINDOW", censor_editor_close)
        _get_window_position_and_setup(censor_editor)
        censor_editor.attributes("-topmost", bool(censor_editor_pinned[0]))

    _aot_state = censor_editor_pinned

    def create_header_with_pagination():
        for widget in censor_editor.winfo_children():
            row = int(widget.grid_info().get("row", -1))
            if row in [0, 1]:
                widget.destroy()

        total_censors = len(current_censors) if current_censors else 0
        total_pages = (total_censors + CENSORS_PER_PAGE - 1) // CENSORS_PER_PAGE if total_censors > 0 else 1

        header_row = 0
        if total_pages > 1:
            current_page = (censor_page_offset // CENSORS_PER_PAGE) + 1

            prev_btn = tk.Button(censor_editor, text="\u25c4 PREV", font=font_big, bg=bg_color, fg=fg_color,
                                command=lambda: page_prev(), state="normal" if current_page > 1 else "disabled")
            prev_btn.grid(row=0, column=0, padx=4, pady=6)

            page_label = tk.Label(censor_editor, text=f"Page {current_page}/{total_pages} ({total_censors} total)",
                                font=font_big, bg=_BACKGROUND_COLOR, fg=fg_color)
            page_label.grid(row=0, column=1, columnspan=5, padx=8, pady=6)

            next_btn = tk.Button(censor_editor, text="NEXT \u25ba", font=font_big, bg=bg_color, fg=fg_color,
                                command=lambda: page_next(), state="normal" if current_page < total_pages else "disabled")
            next_btn.grid(row=0, column=6, columnspan=2, padx=4, pady=6)

            header_row = 1

        headers = ["SIZE", "POSITION", "START", "END", "COLOR", "NSFW"]
        for col, header in enumerate(headers):
            tk.Label(censor_editor, text=header, font=font_big, bg=_BACKGROUND_COLOR, fg=fg_color).grid(row=header_row, column=col, padx=8, pady=6)

        def _toggle_aot(btn=None):
            _aot_state[0] = not _aot_state[0]
            censor_editor.attributes("-topmost", _aot_state[0])
            if btn:
                btn.config(text="\U0001f4cc PIN",
                           fg="#00cc66" if _aot_state[0] else fg_color)
        actions_header_frame = tk.Frame(censor_editor, bg=_BACKGROUND_COLOR)
        tk.Label(actions_header_frame, text="ACTIONS", font=font_big, bg=_BACKGROUND_COLOR, fg=fg_color).pack(side="left")
        aot_btn = tk.Button(actions_header_frame, text="\U0001f4cc PIN", font=("Arial", 11), bg=bg_color,
                            fg="#00cc66" if _aot_state[0] else fg_color,
                            bd=0, relief="flat", command=lambda: _toggle_aot(aot_btn))
        aot_btn.pack(side="right", padx=(8, 0))
        actions_header_frame.grid(row=header_row, column=6, padx=8, pady=6, sticky="ew")

    def page_prev():
        global censor_page_offset
        if censor_page_offset >= CENSORS_PER_PAGE:
            censor_page_offset -= CENSORS_PER_PAGE
            refresh_ui()

    def page_next():
        global censor_page_offset
        total_censors = len(current_censors)
        if censor_page_offset + CENSORS_PER_PAGE < total_censors:
            censor_page_offset += CENSORS_PER_PAGE
            refresh_ui()

    create_header_with_pagination()

    censor_editor.title(f"Censor Editor for {filename}")

    def current_time_func():
        return _get_projected_player_time() / 1000

    def pick_color_func(label):
        def set_color(hex_color):
            label.hex_color = hex_color
            label.config(bg=hex_color, text="")
        ColorPickerOverlay(set_color)
        save_to_current()

    def pick_target_func(size_var, pos_rot_var, shape_btn=None):
        initial = None
        try:
            sw, sh = (float(v) for v in size_var.get().split("x"))
            pr = pos_rot_var.get().split("x")
            px, py = float(pr[0]), float(pr[1])
            rot = float(pr[2]) if len(pr) > 2 else 0.0
            shape = getattr(shape_btn, 'shape', 'rect') if shape_btn else 'rect'
            if not (sw == 100.0 and sh == 100.0 and px == 0.0 and py == 0.0 and rot == 0.0):
                initial = dict(w_pct=sw, h_pct=sh, x_pct=px, y_pct=py, rotation=rot, shape=shape)
        except Exception:
            pass

        def set_target(rect_text):
            try:
                parts = rect_text.split(",")
                size_var.set(parts[0])
                rot_str = parts[2] if len(parts) > 2 else "0.0"
                pos_rot_var.set(f"{parts[1]}x{rot_str}")
                if shape_btn is not None and len(parts) > 3:
                    new_shape = parts[3] if parts[3] in ('rect', 'ellipse') else 'rect'
                    shape_btn.shape = new_shape
                    _lbl = {'rect': '\u25ad', 'ellipse': '\u2b2d'}
                    shape_btn.config(text=_lbl[new_shape])
                    save_to_current()
            except Exception as e:
                print("Failed to parse rectangle:", e)
        RectangleDrawerOverlay(set_target, initial=initial)

    def save_censor_func():
        global censor_list
        if _is_youtube_file_fn and _save_youtube_censors_fn and _get_yt_video_id_fn and _is_youtube_file_fn(filename):
            video_id = _get_yt_video_id_fn(filename)
            if video_id:
                _youtube_censor_list[filename] = current_censors
                _save_youtube_censors_fn(video_id, current_censors)
                update_censor_button_count()
                return
        censor_list[filename] = current_censors
        _atomic_json_write_fn(_CENSOR_JSON_FILE, censor_list, indent=4)
        update_censor_button_count()

    def refresh_ui():
        global current_censors, censor_page_offset
        for widgets in censor_entry_widgets:
            for widget in widgets:
                widget.destroy()
        censor_entry_widgets.clear()

        current_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))

        total_censors = len(current_censors)
        total_pages = (total_censors + CENSORS_PER_PAGE - 1) // CENSORS_PER_PAGE if total_censors > 0 else 1

        if censor_page_offset >= total_censors and total_censors > 0:
            censor_page_offset = max(0, total_censors - CENSORS_PER_PAGE)

        start_idx = censor_page_offset
        end_idx = min(start_idx + CENSORS_PER_PAGE, total_censors)
        page_censors = current_censors[start_idx:end_idx]

        total_censors = len(current_censors)
        total_pages = (total_censors + CENSORS_PER_PAGE - 1) // CENSORS_PER_PAGE if total_censors > 0 else 1
        censor_start_row = 2 if total_pages > 1 else 1

        def build_time_frame(var, row, col, back_color, is_start=True):
            frame = tk.Frame(censor_editor, bg=back_color)
            tk.Button(frame, text="\u2796", width=2, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(v.get() - 0.1, 1))).pack(side="left")
            tk.Entry(frame, textvariable=var, width=5, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color).pack(side="left", ipady=entry_ipady)
            tk.Button(frame, text="\u2795", width=2, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(v.get() + 0.1, 1))).pack(side="left")
            now_button = tk.Button(frame, text="NOW", width=5, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(current_time_func(), 1)))
            now_button.pack(side="left")
            if is_start:
                now_button.bind("<Button-3>", lambda e, v=var: v.set(0.0))
            else:
                now_button.bind("<Button-3>", lambda e, v=var: v.set(round((_player.get_length() / 1000) + 0.1, 1)))
            frame.grid(row=row, column=col, padx=6, pady=row_pady)
            return frame

        def _make_nsfw_btn(c):
            _initial_nsfw = bool(c.get("nsfw", False))
            _nsfw_btn = tk.Button(censor_editor,
                                  text="\u2717 NSFW" if _initial_nsfw else "\u2713 SFW",
                                  bg="#880000" if _initial_nsfw else "#444444",
                                  font=font_big, width=8, height=1,
                                  fg="white", activeforeground="white", activebackground="#333",
                                  bd=0, relief="flat")
            _nsfw_btn.var = _initial_nsfw
            def _update(b=_nsfw_btn):
                b.config(text="\u2717 NSFW" if b.var else "\u2713 SFW",
                         bg="#880000" if b.var else "#444444")
            def _toggle(b=_nsfw_btn, u=_update):
                b.var = not b.var; u()
            _nsfw_btn.config(command=_toggle)
            return _nsfw_btn

        for display_idx, censor in enumerate(page_censors):
            actual_idx = start_idx + display_idx

            row_widgets = []

            _rot0 = round(censor.get('rotation') or 0.0, 2) if not censor.get("mute") and not censor.get("skip") else 0.0

            size_frame = tk.Frame(censor_editor, bg=_BACKGROUND_COLOR)
            if not censor.get("mute") and not censor.get("skip"):
                size_var = tk.StringVar(value=f"{censor['size_w']}x{censor['size_h']}")
                pos_rot_var = tk.StringVar(value=f"{censor['pos_x']}x{censor['pos_y']}x{_rot0}")
                size_entry = tk.Entry(size_frame, textvariable=size_var, width=10, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color)
                size_entry.pack(side="left", ipady=entry_ipady)
                _shape0 = censor.get('shape') or 'rect'
                _shape_labels = {'rect': '\u25ad', 'ellipse': '\u2b2d'}
                shape_btn = tk.Button(size_frame, text=_shape_labels.get(_shape0, '\u25ad'), width=2,
                                      font=font_big, bg=bg_color, fg=fg_color)
                shape_btn.shape = _shape0
                def _cycle_shape(btn=shape_btn, labels=_shape_labels):
                    btn.shape = 'ellipse' if btn.shape == 'rect' else 'rect'
                    btn.config(text=labels[btn.shape])
                    save_to_current()
                shape_btn.config(command=_cycle_shape)
                _pick_btn = tk.Button(size_frame, text="\U0001f3af", width=3, font=font_big, bg=bg_color, fg=fg_color,
                                      command=lambda sv=size_var, prv=pos_rot_var, sb=shape_btn: pick_target_func(sv, prv, sb))
                _pick_btn.pack(side="left")
                _ToolTip(_pick_btn, "Open area selector to visually pick the censor region")
                shape_btn.pack(side="left", padx=(2, 0))
                _ToolTip(shape_btn, "Toggle censor shape: rectangle (\u25ad) or ellipse (\u2b2d)")
            size_frame.grid(row=display_idx+censor_start_row, column=0, padx=(6, 0), pady=row_pady)

            pos_frame = tk.Frame(censor_editor, bg=_BACKGROUND_COLOR)
            if not censor.get("mute") and not censor.get("skip"):
                tk.Entry(pos_frame, textvariable=pos_rot_var, width=14, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color).pack(side="left", ipady=entry_ipady)
            pos_frame.grid(row=display_idx+censor_start_row, column=1, padx=(0, 6), pady=row_pady)

            start_var = tk.DoubleVar(value=censor['start'])
            end_var = tk.DoubleVar(value=censor['end'])
            start_frame = build_time_frame(start_var, display_idx+censor_start_row, 2, _BACKGROUND_COLOR, is_start=True)
            if censor['end']:
                row_color = _BACKGROUND_COLOR
            else:
                row_color = "white"
            end_frame = build_time_frame(end_var, display_idx+censor_start_row, 3, row_color, is_start=False)

            def remove_color(label):
                label.hex_color = None
                label.config(bg="#333", text="AUTO")
                save_to_current()

            color_frame = tk.Frame(censor_editor, bg=_BACKGROUND_COLOR)
            if censor.get("mute"):
                mute_label = tk.Label(color_frame, text="MUTE CENSOR", width=15, font=font_big, justify="center", bg=bg_color, fg=fg_color, highlightbackground="white", highlightthickness=2)
                mute_label.pack(side="left", ipady=entry_ipady)
            elif censor.get("skip"):
                skip_label = tk.Label(color_frame, text="SKIP CENSOR", width=15, font=font_big, justify="center", bg=bg_color, fg=fg_color, highlightbackground="white", highlightthickness=2)
                skip_label.pack(side="left", ipady=entry_ipady)
            else:
                color = censor.get("color")
                color_box = tk.Label(color_frame, text="AUTO" if not color else "", width=6, font=font_big, bg=color if color else "#333", fg=fg_color, relief="groove")
                color_box.hex_color = color
                color_box.pack(side="left", ipady=entry_ipady)
                tk.Button(color_frame, text="PICK", width=5, font=font_big, bg=bg_color, fg=fg_color, command=lambda b=color_box: pick_color_func(b)).pack(side="left", padx=2)
                tk.Button(color_frame, text="\u27f3", width=2, font=font_big, bg=bg_color, fg=fg_color, command=lambda c=color_box: remove_color(c)).pack(side="left")
            color_frame.grid(row=display_idx+censor_start_row, column=4, padx=6, pady=row_pady)

            nsfw_button = _make_nsfw_btn(censor)
            nsfw_button.grid(row=display_idx+censor_start_row, column=5, padx=6, pady=row_pady)

            actions_frame = tk.Frame(censor_editor, bg=_BACKGROUND_COLOR)
            test_button = tk.Button(actions_frame, text="\u25b6TEST", command=lambda c=actual_idx: test_censor_playback(c), font=font_big, bg="#226622", fg="white", activebackground="#2a8a2a", bd=0, relief="raised", width=6)
            test_button.pack(side="left", padx=(0, 2))
            _ToolTip(test_button, "Preview from 1 second before censor start (right-click = test from end)")
            test_button.bind("<Button-3>", lambda event, c=actual_idx: test_censor_playback_from_end(c))
            test_end_button = tk.Button(actions_frame, text="\u23ed", command=lambda c=actual_idx: test_censor_playback_from_end(c), font=font_big, bg="#226622", fg="white", activebackground="#2a8a2a", bd=0, relief="raised", width=2)
            test_end_button.pack(side="left", padx=(0, 4))
            _ToolTip(test_end_button, "Preview from 1 second before censor end")
            dup_button = tk.Button(actions_frame, text="\U0001f5d0", bg=bg_color, fg=fg_color, width=2, font=font_big, command=lambda i=actual_idx: duplicate_censor(i))
            dup_button.pack(side="left", padx=(0, 4))
            _ToolTip(dup_button, "Duplicate this censor")
            delete_button = tk.Button(actions_frame, text="\u274c", bg=bg_color, fg="red", width=2, font=font_big, command=lambda i=actual_idx: delete_censor(i))
            delete_button.pack(side="left")
            _ToolTip(delete_button, "Delete this censor")
            actions_frame.grid(row=display_idx+censor_start_row, column=6, padx=6, pady=row_pady)
            row_widgets.extend([size_frame, pos_frame, start_frame, end_frame, color_frame, nsfw_button, actions_frame])
            censor_entry_widgets.append(row_widgets)

        if len(current_censors) > CENSORS_PER_PAGE:
            create_header_with_pagination()

        create_bottom_buttons()

    def test_censor_playback(censor, from_end=False):
        save_to_current()
        try:
            if from_end:
                end = float(current_censors[censor].get("end", 0))
                if end > 0:
                    test_time = max(0, (end - 1) * 1000)
                else:
                    test_time = max(0, (float(current_censors[censor].get("start", 0)) - 1) * 1000)
            else:
                start = float(current_censors[censor].get("start", 0))
                test_time = max(0, (start - 1) * 1000)

            _player.set_time(round(test_time))
            _player.play()
        except Exception as e:
            print(f"Error playing censor preview: {e}")

    def test_censor_playback_from_end(censor):
        test_censor_playback(censor, from_end=True)

    def delete_censor(index):
        if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this censor?", parent=censor_editor):
            global censor_page_offset
            save_to_current()
            del current_censors[index]

            total_censors = len(current_censors)
            if total_censors > 0:
                max_offset = ((total_censors - 1) // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
                if censor_page_offset > max_offset:
                    censor_page_offset = max_offset
            else:
                censor_page_offset = 0

            refresh_ui()

    def duplicate_censor(index):
        global censor_page_offset
        save_to_current()
        import copy as _copy
        dup = _copy.deepcopy(current_censors[index])
        current_censors.insert(index + 1, dup)
        target_offset = ((index + 1) // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
        censor_page_offset = target_offset
        refresh_ui()

    def add_new_censor():
        global censor_page_offset
        save_to_current()
        new_censor = {
            "size_w": 100.00, "size_h": 100.00,
            "pos_x": 0.0, "pos_y": 0.0,
            "start": round(current_time_func(), 1), "end": 0.0,
            "color": None, "nsfw": False,
        }
        current_censors.append(new_censor)

        sorted_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))

        new_censor_index = None
        for i, censor in enumerate(sorted_censors):
            if (censor["start"] == new_censor["start"] and
                censor["end"] == new_censor["end"] and
                censor.get("size_w") == new_censor.get("size_w") and
                censor.get("pos_x") == new_censor.get("pos_x")):
                new_censor_index = i
                break

        if new_censor_index is not None:
            target_page_offset = (new_censor_index // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
            censor_page_offset = target_page_offset

        refresh_ui()

    def add_new_mute():
        global censor_page_offset
        save_to_current()
        new_censor = {
            "mute": True,
            "start": round(current_time_func(), 1), "end": 0.0,
            "nsfw": False
        }
        current_censors.append(new_censor)

        sorted_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))

        new_censor_index = None
        for i, censor in enumerate(sorted_censors):
            if (censor["start"] == new_censor["start"] and
                censor["end"] == new_censor["end"] and
                censor.get("mute") == True):
                new_censor_index = i
                break

        if new_censor_index is not None:
            target_page_offset = (new_censor_index // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
            censor_page_offset = target_page_offset

        refresh_ui()

    def add_new_skip():
        global censor_page_offset
        save_to_current()
        new_censor = {
            "skip": True,
            "start": round(current_time_func(), 1), "end": 0.0,
            "nsfw": False
        }
        current_censors.append(new_censor)

        sorted_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))

        new_censor_index = None
        for i, censor in enumerate(sorted_censors):
            if (censor["start"] == new_censor["start"] and
                censor["end"] == new_censor["end"] and
                censor.get("skip") == True):
                new_censor_index = i
                break

        if new_censor_index is not None:
            target_page_offset = (new_censor_index // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
            censor_page_offset = target_page_offset

        refresh_ui()

    def save_to_current():
        for display_i, widgets in enumerate(censor_entry_widgets):
            try:
                actual_i = censor_page_offset + display_i
                if actual_i >= len(current_censors):
                    continue

                if current_censors[actual_i].get("mute", False):
                    current_censors[actual_i] = {
                        "mute": True,
                        "start": float(widgets[2].winfo_children()[1].get()),
                        "end": float(widgets[3].winfo_children()[1].get()),
                        "nsfw": widgets[5].var
                    }
                elif current_censors[actual_i].get("skip", False):
                    current_censors[actual_i] = {
                        "skip": True,
                        "start": float(widgets[2].winfo_children()[1].get()),
                        "end": float(widgets[3].winfo_children()[1].get()),
                        "nsfw": widgets[5].var
                    }
                else:
                    size_parts = widgets[0].winfo_children()[0].get().split("x")
                    pr_parts = widgets[1].winfo_children()[0].get().split("x")
                    rot_val = float(pr_parts[2]) if len(pr_parts) > 2 else 0.0
                    _shape_btn = widgets[0].winfo_children()[1] if len(widgets[0].winfo_children()) > 1 else None
                    _shape_val = getattr(_shape_btn, 'shape', 'rect') if _shape_btn else 'rect'
                    current_censors[actual_i] = {
                        "size_w": float(size_parts[0]),
                        "size_h": float(size_parts[1]),
                        "pos_x": float(pr_parts[0]),
                        "pos_y": float(pr_parts[1]),
                        "rotation": rot_val if rot_val != 0.0 else None,
                        "shape": _shape_val if _shape_val != 'rect' else None,
                        "start": float(widgets[2].winfo_children()[1].get()),
                        "end": float(widgets[3].winfo_children()[1].get()),
                        "color": getattr(widgets[4].winfo_children()[0], 'hex_color', None) if widgets[4].winfo_children()[0].cget("text") != "AUTO" else None,
                        "nsfw": widgets[5].var
                    }
            except Exception as e:
                messagebox.showerror("Save Error", f"Error saving row {display_i+1}: {e}")
                return

    def save_all():
        save_to_current()
        save_censor_func()
        save_censors_button.configure(text="SAVED!")
        _root.after(300, lambda: save_censors_button.configure(text="SAVE CENSOR(S)"))
        remove_all_censor_boxes()
        apply_censors(_player.get_time() / 1000, _player.get_length() / 1000)

    def import_previous_censors():
        similar_censors = _similar_censors_cache
        if not similar_censors:
            messagebox.showinfo("No Similar Censors", "No censors found from previous versions of this theme.")
            return

        if len(similar_censors) > 1:
            censor_lists = list(similar_censors.values())
            first_list = censor_lists[0]
            all_identical = all(censors == first_list for censors in censor_lists[1:])

            if all_identical:
                source_filename = list(similar_censors.keys())[0]
            else:
                options = list(similar_censors.keys())
                choice = simpledialog.askstring(
                    "Choose Source",
                    "Multiple versions found. Enter the number of the file to import from:\n" +
                    "\n".join([f"{i+1}. {fname}" for i, fname in enumerate(options)]) +
                    f"\n\nEnter 1-{len(options)}:"
                )
                try:
                    choice_index = int(choice) - 1
                    if 0 <= choice_index < len(options):
                        source_filename = options[choice_index]
                    else:
                        return
                except (ValueError, TypeError):
                    return
        else:
            source_filename = list(similar_censors.keys())[0]

        imported_censors = copy.deepcopy(similar_censors[source_filename])
        current_censors.extend(imported_censors)

        global censor_page_offset
        total_censors = len(current_censors)
        last_page_offset = ((total_censors - 1) // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
        censor_page_offset = last_page_offset

        refresh_ui()

    bottom_button_widgets = []

    def create_bottom_buttons():
        nonlocal bottom_button_widgets

        for widget in bottom_button_widgets:
            widget.destroy()
        bottom_button_widgets.clear()

        add_censor_btn = tk.Button(censor_editor, text="ADD NEW CENSOR", width=26, font=font_big, bg=bg_color, fg=fg_color, command=add_new_censor)
        add_censor_btn.grid(row=999, column=0, columnspan=2, pady=12)
        bottom_button_widgets.append(add_censor_btn)

        add_mute_btn = tk.Button(censor_editor, text="ADD NEW MUTE", width=16, font=font_big, bg=bg_color, fg=fg_color, command=add_new_mute)
        add_mute_btn.grid(row=999, column=2, columnspan=1, pady=12)
        bottom_button_widgets.append(add_mute_btn)

        add_skip_btn = tk.Button(censor_editor, text="ADD NEW SKIP", width=16, font=font_big, bg=bg_color, fg=fg_color, command=add_new_skip)
        add_skip_btn.grid(row=999, column=3, columnspan=1, pady=12)
        bottom_button_widgets.append(add_skip_btn)

        censor_toggle_lbl = "CENSORS: ON" if censors_enabled else "CENSORS: OFF"
        censor_toggle_bg  = "#226622" if censors_enabled else "#662222"
        censor_toggle_btn = tk.Button(censor_editor, text=censor_toggle_lbl, width=14, font=font_big,
                                       bg=censor_toggle_bg, fg=fg_color, command=lambda: _toggle_censor_from_editor())
        censor_toggle_btn.grid(row=999, column=4, columnspan=1, pady=12)
        bottom_button_widgets.append(censor_toggle_btn)

        def _toggle_censor_from_editor():
            toggle_censor_bar()
            toggle_censor_nsfw_bar(censors_enabled)
            censor_toggle_btn.configure(
                text="CENSORS: ON" if censors_enabled else "CENSORS: OFF",
                bg="#226622" if censors_enabled else "#662222"
            )

        global save_censors_button
        save_censors_button = tk.Button(censor_editor, text="SAVE CENSOR(S)", width=19, font=font_big, bg=bg_color, fg=fg_color, command=save_all)
        save_censors_button.grid(row=999, column=5, columnspan=2, pady=12)
        bottom_button_widgets.append(save_censors_button)

        current_has_censors = len(current_censors) > 0
        similar_censors = _similar_censors_cache
        show_import_button = not current_has_censors and len(similar_censors) > 0

        if show_import_button:
            import_button = tk.Button(censor_editor, text="IMPORT PREVIOUS CENSORS", width=30, font=font_big, bg="dark green", fg=fg_color, command=import_previous_censors)
            import_button.grid(row=1000, column=0, columnspan=6, pady=12)
            bottom_button_widgets.append(import_button)

    refresh_ui()
