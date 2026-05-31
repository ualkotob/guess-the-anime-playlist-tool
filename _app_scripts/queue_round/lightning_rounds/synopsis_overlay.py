"""Synopsis / Trivia lightning-round OSD overlay.

Extracted from `guess_the_anime.py`. Renders the SYNOPSIS / TRIVIA text
box and (optionally) the 2×2 multiple-choice grid as a single ASS-OSD
event group on top of the mpv video.

State sharing pattern
---------------------
This module owns three indexing-state names that other parts of main
also write to (``set_light_trivia``, ``play_video``):

    synopsis_start_index   - int / None
    synopsis_end_index     - int / None
    synopsis_split         - list[str] / None

Main sets them via the module-qualified form
``synopsis_overlay.synopsis_start_index = ...`` — that mutates the
canonical module attribute, which is the same binding the module's
own ``global`` statements rebind. No main-side alias is created (one
would silently desync). Same goes for ``_mc_last_choices`` (which one
external caller reads).
"""
from __future__ import annotations

import random
import tkinter.font as _tkfont

from core.game_state import state


# ---------------------------------------------------------------------------
# Module state — some names are externally read/written via
# `synopsis_overlay.<name>` qualified access (see module docstring).
# ---------------------------------------------------------------------------
synopsis_start_index = None
synopsis_end_index = None
synopsis_split = None

synopsis_overlay = None
synopsis_label = None
_synopsis_height_cache: dict = {}   # {full_text_key: body_height_px}

mc_choices_overlay = None
_mc_last_choices: list = []       # exposed (no leading underscore-only) — main reads it
_mc_last_correct_answer = None
_mc_answer_phase = False
_mc_cell_widgets: list = []       # (cell_frame, label_widget, choice_str) entries


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
currently_playing: dict = {}
_get_mpv_window_rect = None
_osd_command = None
_color_str_to_ass_bgr = None
_SYNOPSIS_ASS_OSD_ID = 58
_get_fixed_current_round = lambda: None
_get_light_round_length = lambda: 12
_get_display_screen_width = lambda: 1920
_get_display_screen_height = lambda: 1080
_get_middle_overlay_background_color = lambda: 'dark gray'
_get_overlay_background_color = lambda: 'black'
_get_overlay_text_color = lambda: 'white'


def set_context(*, currently_playing, get_mpv_window_rect, osd_command,
                color_str_to_ass_bgr, synopsis_ass_osd_id,
                get_fixed_current_round, get_light_round_length,
                get_display_screen_width, get_display_screen_height,
                get_middle_overlay_background_color,
                get_overlay_background_color, get_overlay_text_color):
    g = globals()
    g['currently_playing'] = currently_playing
    g['_get_mpv_window_rect'] = get_mpv_window_rect
    g['_osd_command'] = osd_command
    g['_color_str_to_ass_bgr'] = color_str_to_ass_bgr
    g['_SYNOPSIS_ASS_OSD_ID'] = synopsis_ass_osd_id
    g['_get_fixed_current_round'] = get_fixed_current_round
    g['_get_light_round_length'] = get_light_round_length
    g['_get_display_screen_width'] = get_display_screen_width
    g['_get_display_screen_height'] = get_display_screen_height
    g['_get_middle_overlay_background_color'] = get_middle_overlay_background_color
    g['_get_overlay_background_color'] = get_overlay_background_color
    g['_get_overlay_text_color'] = get_overlay_text_color


# ---------------------------------------------------------------------------
# Synopsis / trivia text picking + word-redaction
# ---------------------------------------------------------------------------
TITLE_GENERIC_WORDS = {"the", "a", "an", "as", "and", "of", "in", "on", "to",
                       "with", "for", "by", "at", "from", "no", "his", "her",
                       "he", "she", "so"}


def pick_synopsis():
    global synopsis_start_index, synopsis_split, synopsis_end_index
    if not synopsis_start_index:
        fixed_current_round = _get_fixed_current_round()
        light_round_length = _get_light_round_length()
        if fixed_current_round:
            synopsis = fixed_current_round.get("synopsis_text", "No synopsis found.").replace("\n", " \n")
            synopsis_split = synopsis.split(" ")
            synopsis_start_index = 0
            synopsis_end_index = len(synopsis_split)
            return
        synopsis = (currently_playing.get("data", {}).get("synopsis") or "No synopsis found.")
        for extra_characters in ["\n\n[Written by MAL Rewrite]", "\n\n(Source: adapted from ANN)",
                                 "\n\n(Source: Yen Press)", " \n\n", "\n \n", "\n\n", "\n"]:
            synopsis = synopsis.replace(extra_characters, " ")
        synopsis_split = synopsis.split(" ")
        length = len(synopsis_split)
        if length <= light_round_length * 2:
            synopsis_start_index = 0
        else:
            synopsis_start_index = random.randint(0, length - 41)
        synopsis_end_index = synopsis_start_index + 41


def is_end_of_sentence(word):
    if word and len(word) > 0:
        return word[-1] in ['.', '!', '?']
    else:
        True  # noqa — preserved verbatim from original (was a bareword too)


def get_light_synopsis_string(words=None):
    from _app_scripts.queue_round.lightning_rounds import trivia_round
    fixed_current_round = _get_fixed_current_round()
    light_trivia_answer = trivia_round.light_trivia_answer
    if not words:
        words = (synopsis_end_index or len(synopsis_split)) - (synopsis_start_index or 0)
    if not fixed_current_round and synopsis_start_index > 0 and not is_end_of_sentence(synopsis_split[synopsis_start_index - 1]):
        text = "..."
    else:
        text = ""
    word = ""
    for w in range(words):
        if len(synopsis_split) > (w + synopsis_start_index):
            word = synopsis_split[synopsis_start_index + w]
            if not light_trivia_answer and not fixed_current_round:
                data = currently_playing.get("data", {})
                word_check = word.lower().strip(',!.":')
                if "'s" in word_check and word_check[len(word_check) - 1] == "s" and word_check[len(word_check) - 2] == "'":
                    word_check = word_check.split("'s")[0]
                if word_check not in TITLE_GENERIC_WORDS and word_check in ((data.get("eng_title") or "") + " " + data.get("title")).replace(":", "").lower().split():
                    word = word.lower().replace(word_check, "_" * len(word_check))
            if w > 0:
                text = text + " " + word
            else:
                text = text + word
        if not fixed_current_round and w == 40 and not is_end_of_sentence(word):
            text = text + "..."
    return text


# ---------------------------------------------------------------------------
# OSD overlay toggles + redraw
# ---------------------------------------------------------------------------
def toggle_mc_choices_overlay(choices=None, destroy=False, highlight=False, correct=None, quick_destroy=False):
    """ASS OSD — MC choices drawn inline with the synopsis box in a single OSD call."""
    global mc_choices_overlay, _mc_last_choices, _mc_last_correct_answer, _mc_cell_widgets, _mc_answer_phase

    if destroy:
        mc_choices_overlay = None
        _mc_cell_widgets = []
        _mc_last_choices = []
        _mc_last_correct_answer = None
        _mc_answer_phase = False
        _synopsis_osd_redraw(synopsis_text=synopsis_label if isinstance(synopsis_label, str) else None)
        return

    if quick_destroy:
        mc_choices_overlay = None
        _mc_cell_widgets = []
        _synopsis_osd_redraw(synopsis_text=synopsis_label if isinstance(synopsis_label, str) else None)
        return

    if highlight:
        _mc_answer_phase = True
        _synopsis_osd_redraw(synopsis_text=synopsis_label if isinstance(synopsis_label, str) else None)
        return

    if choices:
        if correct is not None:
            _mc_last_correct_answer = correct
        _mc_last_choices = list(choices)
        _mc_answer_phase = False
        _synopsis_osd_redraw(synopsis_text=synopsis_label if isinstance(synopsis_label, str) else None)


def toggle_synopsis_overlay(text=None, destroy=False, quick_destroy=False):
    """ASS OSD overlay for the Synopsis / Trivia lightning round."""
    global synopsis_overlay, synopsis_label

    if destroy or quick_destroy:
        synopsis_overlay = None
        synopsis_label = None
        _synopsis_height_cache.clear()
        try:
            _osd_command('osd-overlay', _SYNOPSIS_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        return

    if text is None:
        return

    synopsis_label = text
    _synopsis_osd_redraw(synopsis_text=text)


def _synopsis_osd_redraw(synopsis_text=None):
    """Redraws synopsis box + MC grid together in one OSD call."""
    player = state.widgets.player
    root = state.widgets.root

    from _app_scripts.queue_round.lightning_rounds import trivia_round
    DISPLAY_SCREEN_WIDTH  = _get_display_screen_width()
    DISPLAY_SCREEN_HEIGHT = _get_display_screen_height()
    light_trivia_answer   = trivia_round.light_trivia_answer
    fixed_current_round   = _get_fixed_current_round()
    MIDDLE_OVERLAY_BACKGROUND_COLOR = _get_middle_overlay_background_color()
    OVERLAY_BACKGROUND_COLOR = _get_overlay_background_color()
    OVERLAY_TEXT_COLOR = _get_overlay_text_color()

    text = synopsis_text or ""

    try:
        osd_w = int(player._p.osd_width or 0) or DISPLAY_SCREEN_WIDTH
        osd_h = int(player._p.osd_height or 0) or DISPLAY_SCREEN_HEIGHT
    except Exception:
        osd_w, osd_h = DISPLAY_SCREEN_WIDTH, DISPLAY_SCREEN_HEIGHT

    osd_mod = min(osd_w / 2560, osd_h / 1440)
    def ws_osd(n): return max(1, int(n * osd_mod))

    _mx, _my, mw_phys, mh_phys = _get_mpv_window_rect()
    if not mw_phys:
        mw_phys, mh_phys = DISPLAY_SCREEN_WIDTH, DISPLAY_SCREEN_HEIGHT
    phys_mod = min(mw_phys / 2560, mh_phys / 1440)
    def ws_phys(n): return max(1, int(n * phys_mod))

    _is_trivia = light_trivia_answer or bool((fixed_current_round or {}).get("trivia_question"))
    if _is_trivia:
        bg_color = MIDDLE_OVERLAY_BACKGROUND_COLOR
        fg_color = OVERLAY_BACKGROUND_COLOR
    else:
        bg_color = OVERLAY_BACKGROUND_COLOR
        fg_color = OVERLAY_TEXT_COLOR

    bg_bgr = _color_str_to_ass_bgr(bg_color)
    fg_bgr = _color_str_to_ass_bgr(fg_color)

    if fixed_current_round and (fixed_current_round.get("synopsis_header") or fixed_current_round.get("trivia_header")):
        header = ((fixed_current_round.get("synopsis_header") or fixed_current_round.get("trivia_header")).upper() + ":")
    elif light_trivia_answer:
        header = "TRIVIA:"
    else:
        header = "SYNOPSIS:"

    bord_px        = ws_osd(4)
    frame_pad      = ws_osd(20)
    label_padx     = ws_osd(10)
    label_pady_top = ws_osd(10)

    fs_tk_body_render = ws_phys(70)
    fs_tk_header      = ws_phys(70)
    screen_dpi        = root.winfo_fpixels('1i')

    overlay_w_phys  = round(mw_phys * 0.7)
    wraplength_phys = round(overlay_w_phys * 1.09)
    box_w           = round(osd_w * 0.7)
    log_to_osd      = osd_w / mw_phys if mw_phys else 1.0

    fs_body   = round(fs_tk_body_render * screen_dpi / 72)
    fs_header_px = round(fs_tk_header * screen_dpi / 72)

    line_h_render = round(fs_tk_body_render * 1.35 * log_to_osd)
    header_h      = round(fs_tk_header      * 1.35 * log_to_osd)

    # Count synopsis body lines (cached per full text)
    full_text = text
    if text:
        try:
            full_text = get_light_synopsis_string() or text
        except Exception:
            pass
    n_body_lines = 0
    if full_text:
        cache_key = (full_text, mw_phys, mh_phys, fs_tk_body_render)
        if cache_key not in _synopsis_height_cache:
            _mfnt = _tkfont.Font(family="Arial", size=fs_tk_body_render)
            _sp = _mfnt.measure(' ')
            _wl = wraplength_phys - ws_phys(5)
            _n = 0
            for _para in full_text.split('\n'):
                _cur_w2, _has = 0, False
                _para_lines = 1
                for _w2 in _para.split():
                    _ww2 = _mfnt.measure(_w2)
                    _gap2 = _sp if _has else 0
                    if _has and _cur_w2 + _gap2 + _ww2 > _wl:
                        _para_lines += 1; _cur_w2 = _ww2
                    else:
                        _cur_w2 += _gap2 + _ww2
                    _has = True
                _n += _para_lines
            _synopsis_height_cache[cache_key] = max(_n, 1)
        n_body_lines = _synopsis_height_cache[cache_key]

    syn_box_h = (ws_osd(20) + bord_px + header_h + ws_osd(10) +
                 n_body_lines * line_h_render + ws_osd(20) + bord_px) if full_text else 0

    # MC grid geometry
    mc_choices    = _mc_last_choices or []
    has_mc        = bool(mc_choices)
    mc_gap        = ws_osd(10) if (has_mc and syn_box_h) else 0
    mc_box_h      = 0
    mc_fs_body    = 0
    mc_cell_w     = 0
    mc_col_gap    = ws_osd(6)
    mc_cell_pad_x = ws_osd(12)
    mc_cell_pad_y = ws_osd(10)
    _mc_choice_lines = []  # pre-computed wrapped lines per choice
    _mc_line_h = 0
    _mc_row_h = []
    if has_mc:
        max_len    = max((len(c) for c in mc_choices), default=10)
        fs_tk_mc   = ws_phys(max(48, min(60, round(60 - (max_len - 10) * (60 - 48) / 40))))
        mc_fs_body = round(fs_tk_mc * screen_dpi / 72)
        mc_rows    = (len(mc_choices) + 1) // 2
        mc_cell_w  = (box_w - bord_px * 2 - mc_col_gap * 2) // 2
        # Word-wrap each choice to the cell width so mc_cell_h accounts for multi-line text
        _mc_fnt           = _tkfont.Font(family="Arial", size=fs_tk_mc)
        _mc_sp            = _mc_fnt.measure(' ')
        _mc_cell_w_phys   = round(mc_cell_w / log_to_osd) if log_to_osd else mc_cell_w
        _mc_text_w_phys   = round((_mc_cell_w_phys - 2 * round(mc_cell_pad_x / log_to_osd if log_to_osd else mc_cell_pad_x)) * 1.12)
        _MC_LABELS        = ["A", "B", "C", "D"]
        for _lbl, _ch in zip(_MC_LABELS, mc_choices):
            _full = f"[{_lbl}]  {_ch}"
            _cw2, _cwords2, _wlines = 0, [], []
            for _word2 in _full.split():
                _ww2 = _mc_fnt.measure(_word2)
                _gap2 = _mc_sp if _cwords2 else 0
                if _cwords2 and _cw2 + _gap2 + _ww2 > _mc_text_w_phys:
                    _wlines.append(' '.join(_cwords2)); _cwords2, _cw2 = [_word2], _ww2
                else:
                    _cwords2.append(_word2); _cw2 += _gap2 + _ww2
            _wlines.append(' '.join(_cwords2))
            _mc_choice_lines.append(_wlines)
        _mc_line_h = round(fs_tk_mc * 1.35 * log_to_osd)
        for _r in range(mc_rows):
            _row_max = max((len(_mc_choice_lines[_r * 2 + _c]) for _c in range(2) if _r * 2 + _c < len(_mc_choice_lines)), default=1)
            _mc_row_h.append(_mc_line_h * _row_max + mc_cell_pad_y * 2)
        mc_box_h   = sum(_mc_row_h) + (mc_rows - 1) * ws_osd(12) + bord_px * 2 + ws_osd(8)

    total_h = syn_box_h + mc_gap + mc_box_h
    bx      = (osd_w - box_w) // 2
    syn_by  = osd_h // 2 - ws_osd(30) - total_h // 2

    events = []

    # Synopsis box — single rect with ASS \bord for the border so the fill alpha
    # composites directly against the video (not against a separate solid border rect).
    if syn_box_h:
        hx = bx + frame_pad
        hy = syn_by + frame_pad
        tx = hx + label_padx
        ty = hy + header_h + label_pady_top
        events.append(f"{{\\an7\\pos({bx},{syn_by})"
                      f"\\1c&H{bg_bgr}&\\1a&H19&"
                      f"\\3c&H{fg_bgr}&\\3a&H00&\\bord{bord_px}\\shad0\\p1}}"
                      f"m 0 0 l {box_w} 0 {box_w} {syn_box_h} 0 {syn_box_h}{{\\p0}}")
        events.append(f"{{\\an7\\pos({hx},{hy})\\1c&H{fg_bgr}&\\1a&H00&"
                      f"\\3c&H000000&\\3a&HFF&\\bord0\\shad0\\fs{fs_header_px}\\b1\\u1\\q2}}{header}")
        _fnt2 = _tkfont.Font(family="Arial", size=fs_tk_body_render)
        _sp_w2 = _fnt2.measure(' ')
        _lines2 = []
        for _para2 in text.split('\n'):
            _cw2, _cwords2 = 0, []
            for _word2 in _para2.split():
                _ww2 = _fnt2.measure(_word2)
                _gap2 = _sp_w2 if _cwords2 else 0
                if _cwords2 and _cw2 + _gap2 + _ww2 > wraplength_phys:
                    _lines2.append(' '.join(_cwords2)); _cwords2, _cw2 = [_word2], _ww2
                else:
                    _cwords2.append(_word2); _cw2 += _gap2 + _ww2
            _lines2.append(' '.join(_cwords2))
        events.append(f"{{\\an7\\pos({tx},{ty})\\1c&H{fg_bgr}&\\1a&H00&"
                      f"\\3c&H000000&\\3a&HFF&\\bord0\\shad0\\fs{fs_body}\\q2}}"
                      + '\\N'.join(_lines2))

    # MC grid — same fix: single rect with \bord for border
    if has_mc:
        mc_by  = syn_by + syn_box_h + mc_gap
        LABELS = ["A", "B", "C", "D"]
        _mc_row_top = []
        _cur_y = mc_by + bord_px + ws_osd(12)
        for _rh in _mc_row_h:
            _mc_row_top.append(_cur_y)
            _cur_y += _rh + ws_osd(12)
        for i, (label, choice, choice_lines) in enumerate(zip(LABELS, mc_choices, _mc_choice_lines)):
            row, col   = divmod(i, 2)
            is_correct = (_mc_answer_phase and _mc_last_correct_answer and choice == _mc_last_correct_answer)
            cell_bg_bgr = _color_str_to_ass_bgr(fg_color if is_correct else bg_color)
            cell_fg_bgr = _color_str_to_ass_bgr(bg_color if is_correct else fg_color)
            cx     = bx + bord_px + col * (mc_cell_w + mc_col_gap * 2)
            cell_y = _mc_row_top[row]
            cw, ch = mc_cell_w, _mc_row_h[row]
            events.append(f"{{\\an7\\pos({cx},{cell_y})"
                          f"\\1c&H{cell_bg_bgr}&\\1a&H19&"
                          f"\\3c&H{cell_fg_bgr}&\\3a&H00&\\bord{bord_px}\\shad0\\p1}}"
                          f"m 0 0 l {cw} 0 {cw} {ch} 0 {ch}{{\\p0}}")
            cell_tx = cx + mc_cell_pad_x
            _text_h = _mc_line_h * len(choice_lines)
            _inner_h = ch - mc_cell_pad_y * 2
            cell_ty = cell_y + mc_cell_pad_y + max(0, (_inner_h - _text_h) // 2)
            events.append(f"{{\\an7\\pos({cell_tx},{cell_ty})\\1c&H{cell_fg_bgr}&\\1a&H00&"
                          f"\\3c&H000000&\\3a&HFF&\\bord0\\shad0\\fs{mc_fs_body}\\q2}}"
                          + '\\N'.join(choice_lines))

    try:
        _osd_command('osd-overlay', _SYNOPSIS_ASS_OSD_ID, 'ass-events',
                     "\n".join(events), osd_w, osd_h, 2, 'no')
    except Exception as e:
        print(f"Synopsis OSD error: {e}")
