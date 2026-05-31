"""PLAY/PAUSE ICON — extracted from guess_the_anime.py.

A transient fading play/pause icon flashed in the centre of the mpv OSD when the
user toggles playback. Uses create_image_overlay() (overlay_add plane) so it
renders above every ASS osd-overlay layer.

State owned (module-private, no external readers):
    _playpause_icon_after_ids   root.after IDs for the in-progress fade animation
    _playpause_img_overlay      mpv ImageOverlay (PIL bitmap) for the icon

Public function:
    _show_playpause_icon(paused)   flash the icon (True=pause bars, False=play triangle)
Private:
    _clear_playpause_icon()        cancel animation + remove overlay (called internally)

Uses the `_main` module-reference pattern. OVERLAY_BACKGROUND_COLOR /
OVERLAY_TEXT_COLOR are read live through `_main` (rebound by load_config).
"""

import numpy as np
from PIL import Image, ImageDraw


_main = None


def set_context(*, main_module):
    global _main
    _main = main_module


# --- State ---
_playpause_icon_after_ids = []   # root.after IDs for the current play/pause fade animation
_playpause_img_overlay    = None  # mpv ImageOverlay (PIL bitmap) for the play/pause icon


def _clear_playpause_icon():
    """Cancel any in-progress play/pause icon animation and remove the overlay."""
    global _playpause_icon_after_ids, _playpause_img_overlay
    root = _main.root
    for aid in _playpause_icon_after_ids:
        try:
            root.after_cancel(aid)
        except Exception:
            pass
    _playpause_icon_after_ids = []
    if _playpause_img_overlay is not None:
        try:
            _playpause_img_overlay.remove()
        except Exception:
            pass
        _playpause_img_overlay = None


def _show_playpause_icon(paused):
    """Flash a fading play or pause icon centred on the mpv OSD.

    Uses create_image_overlay() (overlay_add plane) so it renders above all
    ASS osd-overlay layers (blind z=1, progress z=2, etc.).
    paused=True  → two vertical bars (pause symbol)
    paused=False → right-pointing triangle (play symbol)

    Border effect: draw expanded shapes in border color → GaussianBlur → draw
    fill on top.  This replicates the visual look of ASS \\bord + \\blur.
    Pre-rendered once at 2× (LANCZOS downscale for anti-aliasing).
    Per-frame: numpy alpha-scale — uniform, reliable fade for fill AND border.
    """
    global _playpause_icon_after_ids, _playpause_img_overlay
    player = _main.player
    root = _main.root
    _clear_playpause_icon()

    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    # Resolve theme colors (RGB for PIL)
    try:
        r16, g16, b16 = root.winfo_rgb(_main.OVERLAY_BACKGROUND_COLOR)
        fill_rgb = (r16 >> 8, g16 >> 8, b16 >> 8)
        r16, g16, b16 = root.winfo_rgb(_main.OVERLAY_TEXT_COLOR)
        bord_rgb = (r16 >> 8, g16 >> 8, b16 >> 8)
    except Exception:
        fill_rgb = (255, 255, 255)
        bord_rgb = (0,   0,   0)

    cx, cy = osd_w // 2, osd_h // 2
    h    = max(60, int(osd_h * 0.24))   # icon height in OSD pixels
    bord = max(2, h // 18)              # border thickness
    hh   = h // 2

    # Pre-render at 1× — hard border, no blur needed
    img = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    if paused:
        bw  = max(2, int(h * 0.22))
        gap = max(4, int(h * 0.20))
        x1, x2 = cx - bw - gap // 2, cx - gap // 2
        x3, x4 = cx + gap // 2,       cx + bw + gap // 2
        y1, y2 = cy - hh, cy + hh
        # outward border: draw expanded rect behind, fill rect on top
        d.rectangle([x1 - bord, y1 - bord, x2 + bord, y2 + bord], fill=bord_rgb + (255,))
        d.rectangle([x3 - bord, y1 - bord, x4 + bord, y2 + bord], fill=bord_rgb + (255,))
        d.rectangle([x1, y1, x2, y2], fill=fill_rgb + (255,))
        d.rectangle([x3, y1, x4, y2], fill=fill_rgb + (255,))
    else:
        tx = cx - int(h * 0.30)
        rx = cx + int(h * 0.35)
        # Compute properly expanded triangle via per-edge outward normals + miter joins.
        # Winding: A(top-left) → B(right tip) → C(bottom-left) = clockwise.
        # Outward unit normal for clockwise edge dir (dx,dy) = (dy/l, -dx/l).
        import math as _math
        d_px = rx - tx
        l    = _math.hypot(d_px, hh)
        n_ab = ( hh / l, -d_px / l)   # top-right edge
        n_bc = ( hh / l,  d_px / l)   # bottom-right edge
        n_ca = (-1.0,     0.0      )   # left edge
        def _miter(n1, n2, e):
            dot   = n1[0]*n2[0] + n1[1]*n2[1]
            denom = 1.0 + dot
            if abs(denom) < 1e-6:
                return (e * n1[0], e * n1[1])
            return (e * (n1[0] + n2[0]) / denom, e * (n1[1] + n2[1]) / denom)
        oA = _miter(n_ca, n_ab, bord)
        oB = _miter(n_ab, n_bc, bord)
        oC = _miter(n_bc, n_ca, bord)
        exp_pts = [(int(tx + oA[0]), int(cy - hh + oA[1])),
                   (int(rx + oB[0]), int(cy      + oB[1])),
                   (int(tx + oC[0]), int(cy + hh + oC[1]))]
        fill_pts = [(tx, cy - hh), (rx, cy), (tx, cy + hh)]
        d.polygon(exp_pts,  fill=bord_rgb + (255,))
        d.polygon(fill_pts, fill=fill_rgb  + (255,))

    base_np  = np.array(img, dtype=np.uint16)   # (h, w, 4) uint16 for safe multiply
    base_a   = base_np[:, :,  3]                 # uint16 alpha, scaled per frame

    def _render_frame(anim_a):
        """Return a full-OSD RGBA premultiplied image scaled by anim_a (0–255).

        mpv overlay_add expects premultiplied BGRA: RGB must be scaled together
        with alpha, otherwise bright pixels appear stuck at full brightness.
        """
        out          = np.empty((osd_h, osd_w, 4), dtype=np.uint8)
        out[:, :, :3] = ((base_np[:, :, :3] * anim_a) // 255).astype(np.uint8)
        out[:, :,  3] = ((base_a            * anim_a) // 255).astype(np.uint8)
        return Image.fromarray(out)

    # Create overlay after the progress bar overlay → higher ID → renders on top
    _playpause_img_overlay = player._p.create_image_overlay()

    def _apply(alpha_val):
        if _playpause_img_overlay is None:
            return
        try:
            _playpause_img_overlay.update(_render_frame(alpha_val))
        except Exception:
            pass

    def _finish():
        global _playpause_img_overlay
        if _playpause_img_overlay is not None:
            try:
                _playpause_img_overlay.remove()
            except Exception:
                pass
            _playpause_img_overlay = None

    # Show first frame immediately (synchronously) — no perceived delay
    _apply(255)

    # Schedule hold then fade-out only
    HOLD, FADE_OUT = 250, 120
    N_OUT = 4
    schedule = []
    for i in range(1, N_OUT + 1):
        schedule.append((HOLD + int(FADE_OUT * i / N_OUT),
                         int(255 * (1.0 - i / N_OUT))))                        # 255→0

    _playpause_icon_after_ids = [
        root.after(delay, lambda a=alpha: _apply(a))
        for delay, alpha in schedule
    ]
    _playpause_icon_after_ids.append(
        root.after(HOLD + FADE_OUT + 50, _finish)
    )
