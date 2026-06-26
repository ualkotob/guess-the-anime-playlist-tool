"""Blind screen overlays.

Owns the blind (black) OSD overlay used by blind rounds, the OST → answer
transition, and as a pre-load cover for reveal rounds; plus the "framed video"
effect used by the FRAME lightning round (zoom-out with image-color matte and
white outline ring).

State owned (rebound at runtime — read it through this module, never cache):
    black_overlay              None = inactive; True = active
    _blind_osd_color_cache     last color used; needed for hide path
    blind_enabled              True while a blind round is in progress
    manual_blind               True when user manually triggered blind (not round-driven)
    _video_frame_active        True while the framed-video effect is active
    _video_frame_zoom          current zoom level (negative log scale)
    _video_frame_color         matte color (sampled at activation)
    blind_round_toggle         True while "Blind Round" is queued for next play

Constants owned:
    _BLIND_ASS_OSD_ID, _FRAME_BORDER_ASS_OSD_ID, _FRAME_OUTLINE_ASS_OSD_ID
    _FRAME_VIDEO_ZOOM, _FRAME_VIDEO_ZOOM_ANSWER, _FRAME_PAN_Y

Public functions:
    set_video_frame, set_black_screen, set_blind_enabled, blind, toggle_blind_round
Private functions (called from main and the lightning ticker):
    _draw_frame_border_osd, _set_blind_osd_alpha

Sibling modules (peek_dispatch, streaming, censors) are imported directly.
Main-file behavior is supplied through narrow callbacks.
"""

from . import streaming
from . import progress_overlay
from . import osd_text
from . import coming_up_ui
from ..queue_round.lightning_rounds import peek_dispatch
from ..toggles import censors
from ..toggles import audio_toggles
from ..information import information_popup
from ..ui import styling
from core.game_state import state


# --- ASS OSD ID constants (only used by this module) ---
_BLIND_ASS_OSD_ID         = 53   # blind / black overlay
_FRAME_BORDER_ASS_OSD_ID  = 80   # framed-video black fill
_FRAME_OUTLINE_ASS_OSD_ID = 81   # framed-video white outline


# --- State ---
black_overlay = None      # None = blind inactive; True = blind active (OSD-based)
_blind_osd_color_cache = "#000000"  # last color used; needed for hide path
blind_enabled = False
manual_blind = False

_video_frame_active = False
_FRAME_VIDEO_ZOOM         = -0.45   # 2^(-0.45) ~= 73.3% — question phase
_FRAME_VIDEO_ZOOM_ANSWER  = -0.45   # 2^(-0.45) ~= 73.3% — answer phase
_FRAME_PAN_Y              = -0.03   # shift video upward (fraction of display height)
_video_frame_zoom  = _FRAME_VIDEO_ZOOM   # currently applied zoom level
_video_frame_color = "#000000"          # sampled at activation; avoids re-reading during draw

blind_round_toggle = False


def _draw_frame_border_osd():
    """Draw the framed-video effect: image-color fill in margins + white outline ring around the video."""
    player = state.widgets.player
    root = state.widgets.root
    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not (osd_w and osd_h):
        return
    scale = 2 ** _video_frame_zoom
    _, _, vid_x, vid_y, vid_w, vid_h = information_popup._get_osd_video_rect()
    if not vid_w:
        vid_x, vid_y, vid_w, vid_h = 0, 0, osd_w, osd_h
    # Video rect after zoom + vertical pan applied from OSD centre
    new_w = round(vid_w * scale)
    new_h = round(vid_h * scale)
    y_shift = round(new_h * abs(_FRAME_PAN_Y))  # upward shift in OSD pixels
    new_x = round((osd_w - new_w) / 2)
    new_y = round((osd_h - new_h) / 2) - y_shift
    # Outline ring thickness (scales with OSD size)
    ring_px = max(3, round(min(osd_w, osd_h) * 0.006))
    ox, oy = new_x - ring_px, new_y - ring_px
    ow, oh = new_w + ring_px * 2, new_h + ring_px * 2
    # Fill color sampled at activation time (stored in _video_frame_color)
    color_str = _video_frame_color
    try:
        r16, g16, b16 = root.winfo_rgb(color_str)
        r, g, b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        r, g, b = 0, 0, 0
    color_hex = f"{b:02X}{g:02X}{r:02X}"
    # OSD 80: image-color fill, clipped to leave the outline+video area transparent
    canvas_path = f"m 0 0 l {osd_w} 0 {osd_w} {osd_h} 0 {osd_h}"
    ass_bg = (
        f"{{\\an7\\pos(0,0)\\1c&H{color_hex}&\\1a&H00&\\bord0\\shad0"
        f"\\iclip({ox},{oy},{ox+ow},{oy+oh})\\p1}}"
        + canvas_path + "{\\p0}"
    )
    # OSD 81: white donut outline ring (clockwise outer, CCW inner -> hollow)
    outer = f"m {ox} {oy} l {ox+ow} {oy} {ox+ow} {oy+oh} {ox} {oy+oh}"
    inner = f"m {new_x} {new_y} l {new_x} {new_y+new_h} {new_x+new_w} {new_y+new_h} {new_x+new_w} {new_y}"
    ass_ring = (
        "{\\an7\\pos(0,0)\\1c&HFFFFFF&\\1a&H00&\\bord0\\shad0\\p1}"
        + outer + " " + inner + "{\\p0}"
    )
    try:
        osd_text.osd_command('osd-overlay', _FRAME_BORDER_ASS_OSD_ID, 'ass-events',
                     ass_bg, osd_w, osd_h, 0, 'no')  # z=0: behind blind (z=1)
    except Exception as e:
        print(f"[frame_border] bg OSD error: {e}")
    try:
        osd_text.osd_command('osd-overlay', _FRAME_OUTLINE_ASS_OSD_ID, 'ass-events',
                     ass_ring, osd_w, osd_h, 0, 'no')  # z=0: behind blind (z=1)
    except Exception as e:
        print(f"[frame_border] ring OSD error: {e}")


def set_video_frame(enabled, answer_phase=False):
    """Enable, update, or disable the framed-video lightning round effect."""
    global _video_frame_active, _video_frame_zoom, _video_frame_color
    player = state.widgets.player
    _video_frame_active = bool(enabled)
    if not enabled:
        _video_frame_zoom = _FRAME_VIDEO_ZOOM
        _video_frame_color = "#000000"
        try:
            player._p.video_zoom = 0
        except Exception:
            pass
        try:
            player._p.video_pan_y = 0
        except Exception:
            pass
        for _oid in (_FRAME_BORDER_ASS_OSD_ID, _FRAME_OUTLINE_ASS_OSD_ID):
            try:
                osd_text.osd_command('osd-overlay', _oid, 'none', '', 0, 0, 0, 'no')
            except Exception:
                pass
        information_popup._unregister_mpv_tracked_window("frame_border")
        return
    _video_frame_zoom = _FRAME_VIDEO_ZOOM_ANSWER if answer_phase else _FRAME_VIDEO_ZOOM
    # Use the same color the blind was rendered with; fall back to sampling if not set
    _video_frame_color = _blind_osd_color_cache if _blind_osd_color_cache and _blind_osd_color_cache != "#000000" else (censors.get_image_color() or censors.get_random_blind_color())
    try:
        player._p.video_zoom = _video_frame_zoom
    except Exception:
        pass
    try:
        player._p.video_pan_y = _FRAME_PAN_Y
    except Exception:
        pass
    def _on_mpv_rect(mx, my, mw, mh):
        if _video_frame_active:
            _draw_frame_border_osd()
    information_popup._register_mpv_tracked_window("frame_border", None, _on_mpv_rect)
    _draw_frame_border_osd()


def _set_blind_osd_alpha(color_str, alpha):
    """Show or hide the blind OSD using ASS osd-overlay (z=1, below progress bar at z=2)."""
    # ASS alpha: 0x00=opaque, 0xFF=transparent. Convert from PIL-style 0-255 opacity.
    player = state.widgets.player
    root = state.widgets.root
    if alpha <= 0:
        # Hide — clear the overlay
        try:
            osd_text.osd_command('osd-overlay', _BLIND_ASS_OSD_ID, 'none', '', 0, 0, 0, 'no')
        except Exception:
            pass
        return
    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
        if not (osd_w and osd_h):
            return
    except Exception:
        return
    try:
        r16, g16, b16 = root.winfo_rgb(color_str)
        r, g, b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        r, g, b = 0, 0, 0
    # ASS color: &HBBGGRR&; alpha tag: &HXX& where 0=opaque, 255=transparent
    color_hex = f"{b:02X}{g:02X}{r:02X}"
    ass_alpha = max(0, 255 - alpha)  # invert: PIL 255=opaque -> ASS 0x00=opaque
    alpha_hex = f"{ass_alpha:02X}"
    path = f"m 0 0 l {osd_w} 0 {osd_w} {osd_h} 0 {osd_h}"
    ass_payload = (
        f"{{\\an7\\pos(0,0)\\1c&H{color_hex}&\\1a&H{alpha_hex}&\\bord0\\shad0\\p1}}"
        + path
        + "{\\p0}"
    )
    try:
        osd_text.osd_command('osd-overlay', _BLIND_ASS_OSD_ID, 'ass-events',
                          ass_payload, osd_w, osd_h, 1, 'no')  # z=1
    except Exception as e:
        print(f"Blind OSD error: {e}")


def blind(manual=False):
    """Toggle blind (black) overlay."""
    global manual_blind
    if black_overlay is None:
        manual_blind = manual
        set_black_screen(True)
    else:
        manual_blind = False
        if not streaming.currently_streaming:
            audio_toggles.toggle_mute(False, True)
        set_black_screen(False)
        progress_overlay.set_progress_overlay(destroy=True)


def set_black_screen(toggle, smooth=True, color=None):
    global black_overlay, _blind_osd_color_cache
    if toggle:
        _color = color if color else censors.get_image_color()
        # If no explicit color was requested and the sampled color is near-black
        # (first frame not yet decoded or video fades in from black), use a
        # random color so the blind doesn't appear solid black.
        if not color and _color:
            try:
                _h = _color.lstrip('#')
                if len(_h) == 6 and (int(_h[0:2], 16) + int(_h[2:4], 16) + int(_h[4:6], 16)) < 60:
                    _color = censors.get_random_blind_color()
            except Exception:
                pass
        _blind_osd_color_cache = _color
        black_overlay = True
        _set_blind_osd_alpha(_color, 255)
        set_blind_enabled(True)
        information_popup._register_mpv_tracked_window("blind_osd", None, information_popup._blind_osd_on_mpv_rect)
    else:
        if black_overlay:
            _set_blind_osd_alpha(_blind_osd_color_cache, 0)
        black_overlay = None
        information_popup._unregister_mpv_tracked_window("blind_osd")
        set_blind_enabled(False)
        censors._commit_censor_osd()  # restore censor overlay now that blind is gone
    state.widgets.root.after(100, styling.configure_style)


def set_blind_enabled(toggle):
    global blind_enabled, manual_blind
    if toggle and not black_overlay:
        toggle = False
    blind_enabled = toggle
    if not toggle:
        manual_blind = False


def toggle_blind_round():
    global blind_round_toggle
    blind_round_toggle = not blind_round_toggle
    if blind_round_toggle:
        if peek_dispatch.peek_round_toggle:
            peek_dispatch.toggle_peek_round()
        if peek_dispatch.mute_peek_round_toggle:
            peek_dispatch.toggle_mute_peek_round()

        if state.config.special_round_warning:
            coming_up_ui.toggle_coming_up_popup(True, "Blind Round", "Guess the anime from just the music.\nNormal rules apply.", queue=True)
    else:
        coming_up_ui.toggle_coming_up_popup(False, "Blind Round")
