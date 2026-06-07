"""Image reveal-effect overlays — PIXEL / REVEAL / BLUR / ZOOM / SLICE / TILE
lightning rounds. All six progressively de-obscure the same source image:
``cover_image_overlay.light_cover_image`` if a COVER or IMAGE round is
active, else the character image stored in
``get_character_round_answer()[1]``.

Bundled in one module because they share that source-selection chain,
the OSD compositing pattern (scale-to ``image_width_percent``, centered,
black bordered), and the mpv image-overlay backend. SLICE/TILE additionally
add a "swap" mode in which all parts are visible but shuffled.

External readers (qualified at the call sites in main):

* ``image_reveal_overlays.character_pixel_overlay`` / ``character_pixel_images``
  — PIXEL sentinel + len() in the lightning ticker.
* ``image_reveal_overlays.reveal_image_window`` — REVEAL sentinel.
* ``image_reveal_overlays.blur_reveal_image_window`` — BLUR sentinel.
* ``image_reveal_overlays.zoom_reveal_image_window`` — ZOOM sentinel.
* ``image_reveal_overlays.slice_overlay_window`` / ``slice_overlay_parts``
  — SLICE sentinel + slot-count display.
* ``image_reveal_overlays.tile_overlay_window`` / ``tile_overlay_parts``
  / ``tile_overlay_swap`` — TILE sentinel + part count + mode flag.

Reads shared lightning settings from ``core.game_state.state`` and receives
``character_round_answer`` / ``fixed_current_round`` through narrow callbacks.

Sibling module ``cover_image_overlay`` imported lazily inside the
source-selection helpers to read ``light_cover_image`` without a circular
top-level import.
"""
from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageTk

from core.game_state import state
from ...ui.scaling import scl


# ---------------------------------------------------------------------------
# Module state — see module docstring for the external-read story.
# ---------------------------------------------------------------------------
# PIXEL
character_pixel_overlay   = None   # mpv image overlay object
character_pixel_images    = []     # precomputed pixelation steps (PIL Images)
# REVEAL
available_c_reveal_modes  = []
last_c_reveal_mode        = ""
reveal_image_window       = None   # mpv image overlay
reveal_direction          = None
# BLUR
blur_reveal_image_window  = None   # mpv image overlay
# ZOOM
zoom_reveal_image_window  = None   # mpv image overlay
zoom_reveal_crop          = None
# SLICE
slice_overlay_window      = None   # mpv image overlay (None when inactive)
slice_overlay_parts       = []     # [(PIL.Image, box), ...] generated once per round
slice_overlay_order       = []     # shuffled indices into slice_overlay_parts
# TILE
tile_overlay_window       = None   # mpv image overlay (None when inactive)
tile_overlay_parts        = []     # [(PIL.Image, box, (row, col)), ...]
tile_overlay_order        = []     # shuffled indices into tile_overlay_parts
tile_overlay_swap         = False  # True while running in swap mode
tile_overlay_grid_size    = 4


# ---------------------------------------------------------------------------
# Shared image-source selection (cover image > character image > bail)
# ---------------------------------------------------------------------------
def _get_source_tk():
    """Pick the source Tkinter PhotoImage for a reveal effect.

    Order:
      1. cover_image_overlay.light_cover_image (set by COVER/IMAGE rounds)
      2. get_character_round_answer()[1] (CHARACTER round)
    Returns the Tkinter image or None if neither is available.
    """
    from _app_scripts.queue_round.lightning_rounds import cover_image_overlay
    if cover_image_overlay.light_cover_image:
        return cover_image_overlay.light_cover_image
    character_round_answer = state.lightning.character_round_answer
    if not character_round_answer:
        return None
    return character_round_answer[1]


def _get_source_pil():
    """Same source chain as ``_get_source_tk`` but returns a PIL copy."""
    tk_img = _get_source_tk()
    if tk_img is None:
        return None
    return ImageTk.getimage(tk_img).copy()


def _get_osd_dims():
    player = state.widgets.player
    try:
        osd_w = int(player._p.osd_width  or 0) or 1920
        osd_h = int(player._p.osd_height or 0) or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080
    return osd_w, osd_h


def _image_width_percent():
    lightning_mode_settings = state.playback.lightning_mode_settings
    return lightning_mode_settings.get("_misc_settings", {}).get("image_width_percent", 70) / 100


# =============================================================================
# PIXEL LIGHTNING ROUND
# =============================================================================

def generate_pixelation_steps(steps=6, final_pixel_size=4, max_pixel_size=35, pil_image=None):
    """
    Generates progressively less pixelated versions of the image using easing.
    Stores them in module state for ``toggle_character_pixel_overlay``.
    """
    global character_pixel_images
    if not pil_image:
        character_round_answer = state.lightning.character_round_answer
        pil_image = ImageTk.getimage(character_round_answer[1]).convert("RGBA")
    width, height = pil_image.size

    # Ease-out function: starts fast, slows down at the end
    def ease_out_quad(t):
        return 1 - (1 - t) ** 2

    pixel_sizes = []
    for i in range(steps):
        t = i / (steps - 1)
        eased = ease_out_quad(t)
        size = int(max_pixel_size - (max_pixel_size - final_pixel_size) * eased)
        pixel_sizes.append(max(size, 1))

    pixelated_images = []
    for px in pixel_sizes:
        downscaled = pil_image.resize((max(1, width // px), max(1, height // px)), Image.NEAREST)
        pixelated = downscaled.resize((width, height), Image.NEAREST)
        pixelated_images.append(pixelated)

    character_pixel_images = pixelated_images


def toggle_character_pixel_overlay(step=0, destroy=False):
    """Show the character image pixelated at the given step (0 = most pixelated)."""
    global character_pixel_overlay
    player = state.widgets.player

    if destroy:
        if character_pixel_overlay is not None:
            try:
                character_pixel_overlay.remove()
            except Exception:
                pass
            character_pixel_overlay = None
        return

    if not character_pixel_images or step >= len(character_pixel_images):
        return

    osd_w, osd_h = _get_osd_dims()

    pil_step = character_pixel_images[step]
    img_w, img_h = pil_step.size
    width_percent = _image_width_percent()
    target_w = int(osd_w * width_percent)
    target_h = int(osd_h * 0.7)
    scale = min(target_w / img_w, target_h / img_h)
    new_w, new_h = max(1, int(img_w * scale)), max(1, int(img_h * scale))
    resized = pil_step.resize((new_w, new_h), Image.LANCZOS)

    border = scl(4)
    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    cx = (osd_w - new_w) // 2
    cy = (osd_h - new_h) // 2
    ImageDraw.Draw(canvas).rectangle(
        [cx - border, cy - border, cx + new_w + border, cy + new_h + border],
        fill=(0, 0, 0, 242)
    )
    canvas.paste(resized.convert("RGBA"), (cx, cy))

    if character_pixel_overlay is None:
        character_pixel_overlay = player._p.create_image_overlay()
    try:
        character_pixel_overlay.update(canvas)
    except Exception:
        pass


# =============================================================================
# REVEAL LIGHTNING ROUND
# =============================================================================

def get_next_c_reveal_mode():
    global available_c_reveal_modes, last_c_reveal_mode
    lightning_mode_settings = state.playback.lightning_mode_settings

    if not available_c_reveal_modes:
        all_variants = []
        available_variants = []
        for variant, enabled in lightning_mode_settings.get("c. reveal", {}).get("variants", {}).items():
            all_variants.append(variant)
            if enabled:
                available_variants.append(variant)
        available_variants = available_variants or all_variants
        while not available_c_reveal_modes:
            available_c_reveal_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_c_reveal_modes) > 1 and available_c_reveal_modes[0] == last_c_reveal_mode:
                available_c_reveal_modes = []

    last_c_reveal_mode = available_c_reveal_modes.pop(0)
    return last_c_reveal_mode


def toggle_character_reveal_overlay(percent=1.0, destroy=False, direction="top"):
    """
    Displays the character image with a black overlay covering a percentage of it.
    `percent` should be between 0.0 (fully revealed) and 1.0 (fully covered).
    `direction` can be 'top', 'bottom', 'left', or 'right' to control the reveal direction.
    """
    global reveal_image_window, reveal_direction
    player = state.widgets.player

    if destroy:
        if reveal_image_window is not None:
            try:
                reveal_image_window.remove()
            except Exception:
                pass
            reveal_image_window = None
        reveal_direction = None
        return

    pil_img = _get_source_pil()
    if pil_img is None:
        return

    if reveal_direction is None:
        reveal_direction = direction

    osd_w, osd_h = _get_osd_dims()

    width_percent = _image_width_percent()
    target_width  = int(osd_w * width_percent)
    target_height = int(osd_h * 0.7)
    scale = min(target_width / pil_img.width, target_height / pil_img.height)
    iw = int(pil_img.width  * scale)
    ih = int(pil_img.height * scale)
    pil_img = pil_img.resize((iw, ih), Image.LANCZOS).convert("RGBA")

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    ix = (osd_w - iw) // 2
    iy = (osd_h - ih) // 2
    draw = ImageDraw.Draw(canvas)
    border = scl(4)
    draw.rectangle([ix - border, iy - border, ix + iw + border, iy + ih + border], fill=(0, 0, 0, 242))
    canvas.paste(pil_img, (ix, iy))

    # Draw black cover rect according to direction + percent
    if reveal_direction == "top":
        draw.rectangle([ix, iy, ix + iw, iy + int(ih * percent)], fill=(0, 0, 0, 255))
    elif reveal_direction == "bottom":
        draw.rectangle([ix, iy + int(ih * (1 - percent)), ix + iw, iy + ih], fill=(0, 0, 0, 255))
    elif reveal_direction == "left":
        draw.rectangle([ix, iy, ix + int(iw * percent), iy + ih], fill=(0, 0, 0, 255))
    elif reveal_direction == "right":
        draw.rectangle([ix + int(iw * (1 - percent)), iy, ix + iw, iy + ih], fill=(0, 0, 0, 255))

    if reveal_image_window is None:
        reveal_image_window = player._p.create_image_overlay()
    try:
        reveal_image_window.update(canvas)
    except Exception:
        pass


# =============================================================================
# BLUR LIGHTNING ROUND
# =============================================================================

def toggle_character_blur_reveal_overlay(percent=1.0, destroy=False):
    """
    Displays the character image with a blurred overlay that clears as percent decreases.
    percent: 1.0 = fully blurred, 0.0 = fully clear.
    """
    global blur_reveal_image_window
    player = state.widgets.player

    if destroy:
        if blur_reveal_image_window is not None:
            try:
                blur_reveal_image_window.remove()
            except Exception:
                pass
            blur_reveal_image_window = None
        return

    pil_img = _get_source_pil()
    if pil_img is None:
        return

    osd_w, osd_h = _get_osd_dims()

    width_percent = _image_width_percent()
    target_width  = int(osd_w * width_percent)
    target_height = int(osd_h * 0.7)
    scale = min(target_width / pil_img.width, target_height / pil_img.height)
    iw = int(pil_img.width  * scale)
    ih = int(pil_img.height * scale)
    pil_img = pil_img.resize((iw, ih), Image.LANCZOS)

    blur_radius = int(50 * percent)
    blurred = pil_img.filter(ImageFilter.GaussianBlur(radius=blur_radius)).convert("RGBA")

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    ix = (osd_w - iw) // 2
    iy = (osd_h - ih) // 2
    border = scl(4)
    ImageDraw.Draw(canvas).rectangle([ix - border, iy - border, ix + iw + border, iy + ih + border], fill=(0, 0, 0, 242))
    canvas.paste(blurred, (ix, iy))

    if blur_reveal_image_window is None:
        blur_reveal_image_window = player._p.create_image_overlay()
    try:
        blur_reveal_image_window.update(canvas)
    except Exception:
        pass


# =============================================================================
# ZOOM LIGHTNING ROUND
# =============================================================================

def pick_interesting_zoom_crop(pil_img, crop_size=(0.35, 0.35), attempts=50, initial_zoom=16):
    """
    Picks a visually interesting crop for zoom reveal.
    Returns (crop_x, crop_y, crop_w, crop_h) in pixel coordinates.
    For fixed rounds with selected area: the area itself is returned.
    For automatic selection: finds an area that looks interesting when zoomed in.
    """
    fixed_current_round = state.lightning.fixed_current_round

    # Check if we're in a fixed round with a pre-selected area
    if fixed_current_round and fixed_current_round.get("image_selected_area"):
        selected_area = fixed_current_round["image_selected_area"]
        img_w, img_h = pil_img.size
        x = int(selected_area["x_pct"] * img_w)
        y = int(selected_area["y_pct"] * img_h)
        w = int(selected_area["w_pct"] * img_w)
        h = int(selected_area["h_pct"] * img_h)
        return (x, y, w, h)

    img_w, img_h = pil_img.size
    crop_w = int(img_w * crop_size[0])
    crop_h = int(img_h * crop_size[1])
    best_crop = None
    best_score = -1

    # Calculate the view size at initial zoom (for non-fixed rounds)
    view_w = int(img_w / initial_zoom)
    view_h = int(img_h / initial_zoom)

    for _ in range(attempts):
        x = random.randint(0, img_w - crop_w)
        y = random.randint(0, img_h - crop_h)

        center_x = x + crop_w // 2
        center_y = y + crop_h // 2

        left = max(0, center_x - view_w // 2)
        top = max(0, center_y - view_h // 2)
        right = min(img_w, left + view_w)
        bottom = min(img_h, top + view_h)
        zoomed_crop = pil_img.crop((left, top, right, bottom))

        arr = np.array(zoomed_crop.convert("L"))
        score = arr.var()
        if score > best_score:
            best_score = score
            best_crop = (x, y, crop_w, crop_h)
        if score > 500:
            break
    return best_crop if best_crop else (0, 0, crop_w, crop_h)


def toggle_character_zoom_reveal_overlay(percent=1.0, destroy=False):
    """
    Displays the character image zoomed in at an interesting spot, then zooms out as percent decreases.
    percent: 1.0 = fully zoomed in, 0.0 = fully zoomed out.
    """
    global zoom_reveal_image_window, zoom_reveal_crop
    player = state.widgets.player
    fixed_current_round = state.lightning.fixed_current_round

    if destroy:
        if zoom_reveal_image_window is not None:
            try:
                zoom_reveal_image_window.remove()
            except Exception:
                pass
            zoom_reveal_image_window = None
        zoom_reveal_crop = None
        return

    pil_img = _get_source_pil()
    if pil_img is None:
        return

    osd_w, osd_h = _get_osd_dims()

    width_percent = _image_width_percent()
    target_width  = int(osd_w * width_percent)
    target_height = int(osd_h * 0.7)
    scale = min(target_width / pil_img.width, target_height / pil_img.height)
    new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
    pil_img = pil_img.resize(new_size, Image.LANCZOS)

    # Pick an interesting crop position once
    initial_zoom = 16  # Zoom factor for non-fixed rounds
    if zoom_reveal_crop is None:
        zoom_reveal_crop = pick_interesting_zoom_crop(pil_img, initial_zoom=initial_zoom)

    crop_x, crop_y, crop_w, crop_h = zoom_reveal_crop

    has_fixed_area = fixed_current_round and fixed_current_round.get("image_selected_area")
    has_ending_area = fixed_current_round and fixed_current_round.get("image_ending_area")

    if has_fixed_area:
        if has_ending_area:
            # Interpolate from starting area to ending area
            ending_area = fixed_current_round["image_ending_area"]
            end_x = int(ending_area["x_pct"] * new_size[0])
            end_y = int(ending_area["y_pct"] * new_size[1])
            end_w = int(ending_area["w_pct"] * new_size[0])
            end_h = int(ending_area["h_pct"] * new_size[1])

            view_w = int(crop_w + (end_w - crop_w) * (1 - percent))
            view_h = int(crop_h + (end_h - crop_h) * (1 - percent))

            start_center_x = crop_x + crop_w // 2
            start_center_y = crop_y + crop_h // 2
            end_center_x = end_x + end_w // 2
            end_center_y = end_y + end_h // 2

            center_x = int(start_center_x + (end_center_x - start_center_x) * (1 - percent))
            center_y = int(start_center_y + (end_center_y - start_center_y) * (1 - percent))
        else:
            # Interpolate from starting area to full image
            view_w = int(crop_w + (new_size[0] - crop_w) * (1 - percent))
            view_h = int(crop_h + (new_size[1] - crop_h) * (1 - percent))
            center_x = crop_x + crop_w // 2
            center_y = crop_y + crop_h // 2
    else:
        # For non-fixed rounds: use zoom factor for more dramatic zoom
        initial_zoom = 16
        zoom = 1.0 + percent * (initial_zoom - 1)
        view_w = int(new_size[0] / zoom)
        view_h = int(new_size[1] / zoom)
        center_x = crop_x + crop_w // 2
        center_y = crop_y + crop_h // 2

    left = max(0, center_x - view_w // 2)
    top = max(0, center_y - view_h // 2)
    right = min(new_size[0], left + view_w)
    bottom = min(new_size[1], top + view_h)

    # Adjust if we hit edges - expand in the opposite direction to maintain view size
    if right - left < view_w:
        left = max(0, right - view_w)
    if bottom - top < view_h:
        top = max(0, bottom - view_h)
    if left == 0 and right - left < view_w:
        right = min(new_size[0], left + view_w)
    if top == 0 and bottom - top < view_h:
        bottom = min(new_size[1], top + view_h)

    cropped = pil_img.crop((left, top, right, bottom))

    crop_w_actual = right - left
    crop_h_actual = bottom - top

    # Scale cropped region to fit display while maintaining aspect ratio
    scale_w = new_size[0] / crop_w_actual
    scale_h = new_size[1] / crop_h_actual
    scale_fit = min(scale_w, scale_h)

    scaled_w = int(crop_w_actual * scale_fit)
    scaled_h = int(crop_h_actual * scale_fit)
    cropped = cropped.resize((scaled_w, scaled_h), Image.LANCZOS)

    # Center the scaled crop on a black background
    composite = Image.new("RGBA", new_size, (0, 0, 0, 255))
    offset_x = (new_size[0] - scaled_w) // 2
    offset_y = (new_size[1] - scaled_h) // 2
    composite.paste(cropped.convert("RGBA"), (offset_x, offset_y))

    # Place composite centered on full OSD canvas
    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    ix = (osd_w - new_size[0]) // 2
    iy = (osd_h - new_size[1]) // 2
    border = scl(4)
    ImageDraw.Draw(canvas).rectangle(
        [ix - border, iy - border, ix + new_size[0] + border, iy + new_size[1] + border],
        fill=(0, 0, 0, 242)
    )
    canvas.paste(composite, (ix, iy))

    if zoom_reveal_image_window is None:
        zoom_reveal_image_window = player._p.create_image_overlay()
    try:
        zoom_reveal_image_window.update(canvas)
    except Exception:
        pass


# =============================================================================
# SLICE LIGHTNING ROUND
# =============================================================================

def generate_image_slices(tk_img, num_slices=10, vertical=True):
    """Slice the image into num_slices vertical (or horizontal) parts.
    Returns a list of (PIL image, box) tuples (not Tkinter PhotoImages).
    """
    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size
    slices = []
    for i in range(num_slices):
        if vertical:
            left = int(i * w / num_slices)
            right = int((i + 1) * w / num_slices)
            box = (left, 0, right, h)
        else:
            top = int(i * h / num_slices)
            bottom = int((i + 1) * h / num_slices)
            box = (0, top, w, bottom)
        part = pil_img.crop(box)
        slices.append((part, box))
    return slices


def toggle_slice_overlay(num_revealed=10, num_slices=10, vertical=True, swap=False, destroy=False):
    """Show the image sliced into num_slices parts.
    If swap=True, all slices are visible but their positions are shuffled.
    If swap=False, only num_revealed slices are shown in a random order.
    """
    global slice_overlay_window, slice_overlay_parts, slice_overlay_order
    player = state.widgets.player

    if destroy:
        if slice_overlay_window is not None:
            try:
                slice_overlay_window.remove()
            except Exception:
                pass
            slice_overlay_window = None
        slice_overlay_parts = []
        slice_overlay_order = []
        return

    tk_img = _get_source_tk()
    if tk_img is None:
        return

    # Generate slices only once
    if not slice_overlay_parts or len(slice_overlay_parts) != num_slices:
        slice_overlay_parts = generate_image_slices(tk_img, num_slices, vertical)
        slice_overlay_order = list(range(num_slices))
        random.shuffle(slice_overlay_order)

    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size

    # Compose slices onto a transparent background
    composite = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if swap:
        swap_order = slice_overlay_order[:]
        random.shuffle(swap_order)
        for i, idx in enumerate(swap_order):
            part, box = slice_overlay_parts[idx]
            if vertical:
                left = int(i * w / num_slices)
                right = int((i + 1) * w / num_slices)
                new_box = (left, 0, right, h)
                # Resize part to fit new_box
                part_resized = part.resize((right - left, h), Image.LANCZOS)
            else:
                top = int(i * h / num_slices)
                bottom = int((i + 1) * h / num_slices)
                new_box = (0, top, w, bottom)
                part_resized = part.resize((w, bottom - top), Image.LANCZOS)
            composite.paste(part_resized, new_box)
    else:
        # Reveal slices in random order
        for i in range(num_revealed):
            idx = slice_overlay_order[i]
            part, box = slice_overlay_parts[idx]
            composite.paste(part, box)

    osd_w, osd_h = _get_osd_dims()
    width_percent = _image_width_percent()
    target_w = int(osd_w * width_percent)
    target_h = int(osd_h * 0.7)
    scale = min(target_w / w, target_h / h)
    img_w = int(w * scale)
    img_h = int(h * scale)
    composite = composite.resize((img_w, img_h), Image.LANCZOS)

    osd_canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    ix = (osd_w - img_w) // 2
    iy = (osd_h - img_h) // 2
    border = scl(4)
    ImageDraw.Draw(osd_canvas).rectangle(
        [ix - border, iy - border, ix + img_w + border, iy + img_h + border],
        fill=(0, 0, 0, 242),
    )
    osd_canvas.paste(composite, (ix, iy), composite)

    if slice_overlay_window is None:
        slice_overlay_window = player._p.create_image_overlay()
    try:
        slice_overlay_window.update(osd_canvas)
    except Exception:
        pass


# =============================================================================
# TILE LIGHTNING ROUND
# =============================================================================

def is_solid_color(image_crop, tolerance=30):
    arr = np.array(image_crop.convert("RGB"))
    # If the standard deviation is low, it's a solid color
    return arr.std() < tolerance


def generate_image_grid_slices(tk_img, grid_size=4, ignore_solid=True):
    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size
    tile_w = w // grid_size
    tile_h = h // grid_size
    slices = []
    for row in range(grid_size):
        for col in range(grid_size):
            left = col * tile_w
            top = row * tile_h
            right = left + tile_w if col < grid_size - 1 else w
            bottom = top + tile_h if row < grid_size - 1 else h
            box = (left, top, right, bottom)
            part = pil_img.crop(box)
            if not is_solid_color(part, tolerance=30) or not ignore_solid:  # Only add if not solid
                slices.append((part, box, (row, col)))
    return slices


def toggle_tile_overlay(num_revealed=1, grid_size=4, swap=False, destroy=False):
    """
    If swap=False: reveals num_revealed tiles in a random order, rest hidden.
    If swap=True: all tiles shown, but only num_revealed unique swaps are restored to correct positions.
    Tiles in the wrong position are dimmed.
    """
    global tile_overlay_window, tile_overlay_parts, tile_overlay_order, tile_overlay_swap, tile_overlay_grid_size
    player = state.widgets.player

    if destroy:
        if tile_overlay_window is not None:
            try:
                tile_overlay_window.remove()
            except Exception:
                pass
            tile_overlay_window = None
        tile_overlay_parts = []
        tile_overlay_order = []
        tile_overlay_swap = False
        return

    tk_img = _get_source_tk()
    if tk_img is None:
        return

    # Only generate once per round
    if not tile_overlay_parts:
        tile_overlay_grid_size = grid_size
        tile_overlay_parts = generate_image_grid_slices(tk_img, grid_size, ignore_solid=not swap)
        tile_overlay_order = list(range(len(tile_overlay_parts)))

        if swap:
            # For swap mode, start with correct order and create meaningful scramble
            toggle_tile_overlay.swap_order = tile_overlay_order[:]  # Start correct: [0,1,2,3,4,...]

            # Create swap pairs that will scramble the puzzle meaningfully
            swap_pairs = []
            used = set()
            order_copy = toggle_tile_overlay.swap_order[:]
            available_positions = list(range(len(order_copy)))
            random.shuffle(available_positions)

            # Create random pairs and apply swaps to scramble the order
            i = 0
            while i < len(available_positions) - 1:
                pos_a = available_positions[i]
                pos_b = available_positions[i + 1]

                if pos_a not in used and pos_b not in used:
                    # Swap these two random positions to create the scrambled puzzle
                    order_copy[pos_a], order_copy[pos_b] = order_copy[pos_b], order_copy[pos_a]
                    swap_pairs.append((pos_a, pos_b))
                    used.update([pos_a, pos_b])
                    i += 2
                else:
                    i += 1

            # The scrambled order becomes our starting state
            toggle_tile_overlay.swap_order = order_copy
            random.shuffle(swap_pairs)  # Randomize which swaps happen when
            toggle_tile_overlay.swap_pairs = swap_pairs
        else:
            # For regular mode, shuffle normally
            random.shuffle(tile_overlay_order)

    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size
    composite = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if swap:
        tile_overlay_swap = True
        swap_order = toggle_tile_overlay.swap_order[:]
        # Perform up to num_revealed unique swaps from precomputed swap_pairs
        if hasattr(toggle_tile_overlay, "swap_pairs"):
            swaps_to_do = toggle_tile_overlay.swap_pairs[:num_revealed]
            for a, b in swaps_to_do:
                # Actually swap the tiles at positions a and b
                swap_order[a], swap_order[b] = swap_order[b], swap_order[a]
        grid_cols = tile_overlay_grid_size
        for i, idx in enumerate(swap_order):
            part, box, (row, col) = tile_overlay_parts[idx]
            grid_row = i // grid_cols
            grid_col = i % grid_cols
            left = grid_col * (w // grid_cols)
            top = grid_row * (h // grid_cols)
            right = left + (w // grid_cols) if grid_col < grid_cols - 1 else w
            bottom = top + (h // grid_cols) if grid_row < grid_cols - 1 else h
            new_box = (left, top, right, bottom)
            part_resized = part.resize((right - left, bottom - top), Image.LANCZOS)
            if idx != i:
                overlay = Image.new("RGBA", part_resized.size, (0, 0, 0, 100))
                part_resized = Image.alpha_composite(part_resized, overlay)
            if (right - left) > 0 and (bottom - top) > 0:
                composite.paste(part_resized, new_box)
    else:
        # Reveal tiles in the same shuffled order each time
        for i in range(num_revealed):
            idx = tile_overlay_order[i]
            part, box, _ = tile_overlay_parts[idx]
            composite.paste(part, box)

    osd_w, osd_h = _get_osd_dims()
    width_percent = _image_width_percent()
    target_w = int(osd_w * width_percent)
    target_h = int(osd_h * 0.7)
    scale = min(target_w / w, target_h / h)
    img_w = int(w * scale)
    img_h = int(h * scale)
    composite = composite.resize((img_w, img_h), Image.LANCZOS)

    osd_canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    ix = (osd_w - img_w) // 2
    iy = (osd_h - img_h) // 2
    border = scl(4)
    ImageDraw.Draw(osd_canvas).rectangle(
        [ix - border, iy - border, ix + img_w + border, iy + img_h + border],
        fill=(0, 0, 0, 242),
    )
    osd_canvas.paste(composite, (ix, iy), composite)

    if tile_overlay_window is None:
        tile_overlay_window = player._p.create_image_overlay()
    try:
        tile_overlay_window.update(osd_canvas)
    except Exception:
        pass
