"""End-of-session OSD: 'Thanks for playing!' message with session breakdown and slide-in animation."""

import time
from datetime import datetime

from PIL import Image, ImageDraw

from _app_scripts.file import session_stats
from core.app_logging import log_exception
from core.game_state import state
import _app_scripts.playback.osd_text as osd_text
import _app_scripts.file.scoreboard_control as scoreboard_control
# bonus.answers imports this module back; `import ... as` binds the module
# object so call-time attribute access stays cycle-safe.
import _app_scripts.bonus.answers as bonus_answers

# ---------------------------------------------------------------------------
# Module-owned state
# ---------------------------------------------------------------------------
end_message_window = None    # True = OSD visible, None = hidden
_end_msg_img_overlay = None
_end_msg_anim_after = None

DEFAULT_END_SESSION_MESSAGE = "THANKS FOR\nPLAYING!♥"

# Re-export for backwards compatibility with code that read it on session_end
get_op_ed_counts = session_stats.get_op_ed_counts

# ---------------------------------------------------------------------------
# End-session entry point
# ---------------------------------------------------------------------------
def end_session():
    if not end_message_window:
        state.controls.video_stopped = True
    else:
        state.controls.video_stopped = False
    toggle_end_message()
    scoreboard_control.send_command("end")


# ---------------------------------------------------------------------------
# Canvas rendering
# ---------------------------------------------------------------------------
def _end_msg_build_canvas(y_top):
    """Build a full OSD RGBA canvas with the end-session stats box at y_top."""
    player = state.widgets.player
    root = state.widgets.root
    try:
        osd_w = int(player._p.osd_width  or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return None
    if not osd_w or not osd_h:
        return None

    modifier = min(osd_w / 2560, osd_h / 1440)
    pad = max(8,  round(25 * modifier))
    vertical_pad = max(6, round(18 * modifier))
    gap = max(1,  round(5  * modifier))
    sep = max(1,  round(2  * modifier))

    def _fs(pt):
        return max(8, round(pt * modifier * 1.4))

    # Gather stats
    summary = session_stats.get_session_summary_counts()
    total_played = summary["themes_played"]
    opening_count = summary["opening_count"]
    ending_count = summary["ending_count"]
    lightning_count = summary["lightning_count"]
    fixed_playlist_count = summary["fixed_playlist_count"]
    youtube_count = summary["youtube_count"]

    end_session_txt = state.config.end_session_txt
    raw_msg  = end_session_txt.replace("\\n", "\n") if end_session_txt else DEFAULT_END_SESSION_MESSAGE
    safe_msg = raw_msg.replace("\U0001f90d", "♥").replace("❤️", "♥").replace("❤", "♥")

    dt_str   = datetime.now().strftime("%b %d, %Y")
    date_str = f"GUESS THE ANIME! {dt_str.upper()}"

    try:
        sd     = datetime.strptime(session_stats.session_start_time, '%Y-%m-%d_%H-%M')
        t0_str = sd.strftime("%#I:%M %p")
        dur    = datetime.now() - sd
    except Exception:
        t0_str = "N/A"
        dur    = None
    is_dst   = time.daylight and time.localtime().tm_isdst
    tz_name  = time.tzname[1 if is_dst else 0]
    tz_abbr  = ''.join(w[0].upper() for w in tz_name.split())
    t1_str   = datetime.now().strftime("%#I:%M %p")
    time_txt = f"{t0_str} - {t1_str} {tz_abbr}"
    if dur:
        time_txt += f" [{dur.seconds // 3600}h {(dur.seconds // 60) % 60}m]"

    top_series_name, top_series_count = session_stats.get_top_series_from_session(session_stats.session_data)
    top_artists,     top_artist_count = session_stats.get_top_artists_from_session(session_stats.session_data)

    # Row definitions: (kind, text, pt, bold)
    # kind: "msg" | "text" | "sep"
    rows = []
    for line in safe_msg.split("\n"):
        rows.append(("msg",  line,         90, True))
    rows.append(("sep",  None,              sep, False))
    rows.append(("text", date_str,          35, True))
    rows.append(("text", time_txt,          30, False))
    rows.append(("sep",  None,              sep, False))
    rows.append(("text", "SESSION BREAKDOWN:", 40, True))
    rows.append(("text", f"{total_played} THEMES PLAYED", 55, True))
    rows.append(("text", f"{opening_count} OPENINGS  •  {ending_count} ENDINGS", 35, False))
    if lightning_count:
        rows.append(("text", f"{lightning_count} LIGHTNING ROUND{'S' if lightning_count != 1 else ''}", 35, False))
    if fixed_playlist_count:
        rows.append(("text", f"{fixed_playlist_count} FIXED PLAYLIST{'S' if fixed_playlist_count != 1 else ''}", 35, False))
    if youtube_count:
        rows.append(("text", f"{youtube_count} YOUTUBE VIDEO{'S' if youtube_count != 1 else ''}", 35, False))
    if top_series_name:
        rows.append(("sep",  None,          sep, False))
        rows.append(("text", "MOST PLAYED SERIES:", 35, True))
        rows.append(("text", f"{top_series_name} ({top_series_count})", 28, False))
    if top_artists:
        rows.append(("sep",  None,          sep, False))
        artist_header = "MOST PLAYED ARTIST:" if len(top_artists) == 1 else "MOST PLAYED ARTISTS:"
        rows.append(("text", artist_header, 35, True))
        for artist in top_artists:
            rows.append(("text", f"{artist} ({top_artist_count})", 28, False))

    def _row_advance(index, kind, size):
        # Large multi-line messages need less leading than the smaller stats rows.
        if kind == "msg" and index + 1 < len(rows) and rows[index + 1][0] == "msg":
            return round(size * 0.82) + gap
        return size + gap

    # Measure widths to determine box width
    min_box_w  = round(osd_w * 0.28)
    max_text_w = min_box_w
    for kind, text, pt, bold in rows:
        if kind in ("msg", "text") and text:
            size = _fs(pt)
            fnt  = osd_text._get_ass_font(size, bold=bold, narrow=True)
            if fnt:
                try:
                    w = round(fnt.getlength(text))
                except AttributeError:
                    w = len(text) * size // 2
                max_text_w = max(max_text_w, w)
    box_w = min(round(osd_w * 0.52), max_text_w + 2 * pad)

    # Horizontal squeeze applied after rendering (like ASS \fscx).
    # Render sprite at full box_w so font metrics stay accurate, then resize.
    H_SQUEEZE = 0.95  # 1.0 = no change; 0.80 = 80% width (noticeably condensed)

    # Measure total height
    total_h = 2 * vertical_pad
    for index, (kind, text, pt, bold) in enumerate(rows):
        size = _fs(pt)
        total_h += _row_advance(index, kind, size)

    squeezed_w = round(box_w * H_SQUEEZE)
    inverted_positions = state.config.inverted_positions
    box_x = max(4, round(10 * modifier)) if inverted_positions else osd_w - squeezed_w - max(4, round(10 * modifier))

    # Colours
    try:
        r16, g16, b16 = root.winfo_rgb(state.colors.OVERLAY_BACKGROUND_COLOR)
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
        r16, g16, b16 = root.winfo_rgb(state.colors.OVERLAY_TEXT_COLOR)
        fg_r, fg_g, fg_b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        bg_r, bg_g, bg_b = 0,   0,   0
        fg_r, fg_g, fg_b = 255, 255, 255

    # Render box sprite once (origin at 0,0) then paste onto full canvas at y_top.
    # This lets the animation loop skip re-rendering text every frame.
    sprite = Image.new("RGBA", (box_w, total_h), (0, 0, 0, 0))
    sdraw  = ImageDraw.Draw(sprite)
    sdraw.rectangle([0, 0, box_w - 1, total_h - 1], fill=(bg_r, bg_g, bg_b, 210))

    cy = vertical_pad
    for index, (kind, text, pt, bold) in enumerate(rows):
        size = _fs(pt)
        if kind == "sep":
            sdraw.rectangle([pad, cy, box_w - pad - 1, cy + size - 1],
                            fill=(fg_r, fg_g, fg_b, 200))
            cy += _row_advance(index, kind, size)
        else:
            fnt    = osd_text._get_ass_font(size, bold=bold, narrow=True)
            if text and fnt:
                try:
                    tw = round(fnt.getlength(text))
                except AttributeError:
                    tw = len(text) * size // 2
                tx = (box_w - tw) // 2
                sdraw.text((tx, cy), text, font=fnt, fill=(fg_r, fg_g, fg_b, 255))
            cy += _row_advance(index, kind, size)

    # Store sprite on function so _end_msg_composite_canvas can reuse it
    # Squish horizontally — render was at full box_w for accurate font metrics
    if H_SQUEEZE != 1.0:
        sprite = sprite.resize((squeezed_w, total_h), Image.LANCZOS)
    _end_msg_build_canvas._sprite   = sprite
    _end_msg_build_canvas._box_x    = box_x
    _end_msg_build_canvas._osd_size = (osd_w, osd_h)

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    canvas.paste(sprite, (box_x, y_top))
    return canvas


def _end_msg_composite_canvas(y_top):
    """Fast path: paste pre-rendered box sprite onto a blank canvas at y_top.
    Falls back to full rebuild if the sprite or OSD size has changed."""
    player = state.widgets.player
    try:
        osd_w = int(player._p.osd_width  or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return None
    if not osd_w or not osd_h:
        return None

    cached = getattr(_end_msg_build_canvas, '_osd_size', None)
    if cached != (osd_w, osd_h) or not hasattr(_end_msg_build_canvas, '_sprite'):
        return _end_msg_build_canvas(y_top)

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    canvas.paste(_end_msg_build_canvas._sprite, (_end_msg_build_canvas._box_x, y_top))
    return canvas


def _end_msg_slide_cancel():
    global _end_msg_anim_after
    root = state.widgets.root
    if _end_msg_anim_after is not None:
        try:
            root.after_cancel(_end_msg_anim_after)
        except Exception:
            pass
        _end_msg_anim_after = None


def _end_msg_slide_in():
    global _end_msg_img_overlay
    player = state.widgets.player
    root = state.widgets.root
    _end_msg_slide_cancel()
    try:
        osd_w = int(player._p.osd_width  or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    modifier = min(osd_w / 2560, osd_h / 1440)
    target_y = max(4, round(10 * modifier))
    duration = 15.0         # seconds — slow credits-style reveal
    t0       = time.perf_counter()

    if _end_msg_img_overlay is None:
        _end_msg_img_overlay = player._p.create_image_overlay()

    # Pre-render the box sprite once so the animation loop only does cheap pastes
    _end_msg_build_canvas(osd_h)   # builds sprite, caches on function object

    _last_size = [0, 0]   # [osd_w, osd_h] at last canvas push; detect resize

    def _step():
        global _end_msg_anim_after
        if not end_message_window:
            return
        t    = min(1.0, (time.perf_counter() - t0) / duration)
        ease = t                               # linear — constant speed
        try:
            cur_w = int(player._p.osd_width  or osd_w)
            cur_h = int(player._p.osd_height or osd_h)
        except Exception:
            cur_w, cur_h = osd_w, osd_h

        size_changed = (cur_w != _last_size[0] or cur_h != _last_size[1])

        # Recompute target_y if OSD resized (also invalidates cached sprite)
        if size_changed:
            mod = min(cur_w / 2560, cur_h / 1440)
            t_y = max(4, round(10 * mod))
        else:
            t_y = target_y

        y = round(cur_h + (t_y - cur_h) * ease)

        if t < 1.0 or size_changed:
            # Fast path: just paste the pre-rendered sprite; full rebuild only on resize
            c = _end_msg_composite_canvas(y)
            if c:
                try:
                    _end_msg_img_overlay.update(c)
                except Exception:
                    pass
            _last_size[0] = cur_w
            _last_size[1] = cur_h

        if t < 1.0:
            _end_msg_anim_after = root.after(15, _step)     # ~120 fps during animation
        else:
            _end_msg_anim_after = root.after(250, _step)   # slow poll for resize after

    _step()


def toggle_end_message(speed=500):
    """Toggles the 'Thanks for playing!' message with detailed stats."""
    global end_message_window, _end_msg_img_overlay
    try:
        if end_message_window:
            _end_msg_slide_cancel()
            if _end_msg_img_overlay is not None:
                try:
                    _end_msg_img_overlay.remove()
                except Exception:
                    pass
                _end_msg_img_overlay = None
            end_message_window = None
            bonus_answers._push_web_toggles()
            return

        end_message_window = True
        _end_msg_slide_in()
        session_stats.save_session_history(create_text_file=True, silent=False)
        bonus_answers._push_web_toggles()
    except Exception as e:
        log_exception("Error displaying end session message")
        print("Error displaying end session message:", e)
