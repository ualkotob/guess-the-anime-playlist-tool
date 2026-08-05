"""Characters lightning-round overlay — 2x2 grid of character thumbnails
drawn via mpv's PIL image-overlay (not ASS like most other lightning
overlays). Characters are fetched from AniDB by URL and cached.

Extracted from `guess_the_anime.py`. The module owns its overlay state
(``characters_overlay_boxes``, ``_characters_img_overlay``) plus the
character image lists (``characters_round_characters``,
``characters_round_names``,
``characters_round_image_cache_default``,
``characters_round_image_cache_default_urls``).

``characters_round_characters`` is read AND written externally — main's
``clean_up_light_round`` resets it to ``[]``, the lightning ticker
populates it from the prefetched queue, and the CHARACTER ZOOMED round
(``get_char_parts_round_character``) re-uses the same global to stash
zoomed image slices. All those external rebind sites are qualified as
``characters_overlay.characters_round_characters = ...`` and the
corresponding `global` decls in main are trimmed.

``characters_round_image_cache_default`` is read externally by the
cover/image lightning rounds as a fallback placeholder image — all
those reads are qualified as ``characters_overlay.characters_round_image_cache_default[...]``.

Uses PIL image-overlay instead of ASS, so unlike the other lightning
overlays it does not own an OSD-ID constant.
"""
from __future__ import annotations

import copy
import random
import threading

from PIL import Image, ImageTk

from core.game_state import state
from ...playback import image_loader, osd_text
from . import character_roster


# ---------------------------------------------------------------------------
# Module state — see module docstring for the external-write story.
# ---------------------------------------------------------------------------
characters_overlay_boxes              = {}
_characters_img_overlay               = None
characters_round_characters           = []
characters_round_names                = []
characters_round_image_cache_default  = []
characters_round_image_cache_default_urls = [
    "https://w0.peakpx.com/wallpaper/104/618/HD-wallpaper-anime-error-female-dress-black-cute-hair-windows-girl-anime-page.jpg",
    "https://i.imgflip.com/1xuu83.jpg",
    "https://www.pngarts.com/files/8/Confused-Anime-PNG-Background-Image.png",
    "https://cdn.anidb.net/misc/confused.png",
]


def get_cached_characters_round_images(
    urls, default=False, queue=False, names=None, loaded_names=None
):
    chars = []
    root = state.widgets.root
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    img_size = int(min(screen_width, screen_height) * 0.35)
    for index, url in enumerate(urls):
        name = names[index] if names and index < len(names) else ""
        try:
            tk_img = image_loader.load_image_from_url(url, size=(img_size, img_size))
        except Exception as e:
            print(f"get_cached_characters_round_images: skipping {url!r}: {e}")
            tk_img = None
        if tk_img:
            if default:
                characters_round_image_cache_default.append(tk_img)
            elif queue:
                chars.append(tk_img)
                if loaded_names is not None:
                    loaded_names.append(name)
            else:
                characters_round_characters.append(tk_img)
                characters_round_names.append(name)
        else:
            if not default and index < len(characters_round_image_cache_default):
                if queue:
                    chars.append(characters_round_image_cache_default[index])
                    if loaded_names is not None:
                        loaded_names.append(name)
                else:
                    characters_round_characters.append(characters_round_image_cache_default[index])
                    characters_round_names.append(name)
    if queue:
        return chars


def load_default_char_images():
    get_cached_characters_round_images(characters_round_image_cache_default_urls, default=True)


def get_characters_round_characters(data=None, queue=False, include_names=False):
    global characters_round_characters, characters_round_names
    if not data:
        currently_playing = state.playback.currently_playing
        data = currently_playing.get("data")

    if data and data.get("characters"):
        main = []
        secondary = []
        appear = []
        for character in character_roster.dedupe_characters_by_name(
            data["characters"]
        ):
            if len(character) < 3 or not character[2]:
                continue
            item = (
                "https://cdn-eu.anidb.net/images/main/" + character[2],
                character[1] if len(character) > 1 else "",
            )
            if character[0] == "m":
                main.append(item)
            elif character[0] == "s":
                secondary.append(item)
            elif character[0] == "a":
                appear.append(item)

        random.shuffle(main)
        random.shuffle(secondary)
        random.shuffle(appear)

        # Start building result with up to 2 appear, 1 secondary, 1 main
        result = []
        total = 0
        for group in [[appear, 2], [secondary, 1], [main, 1]]:
            result += [item for item in group[0] if item not in result][:group[1]]
            total += group[1]
            # If not enough, fill from any remaining (no duplicates)
            remaining = [item for item in (appear + secondary + main) if item not in result]
            result += remaining[:total - len(result)]
        selected = result[:4]
        urls = [item[0] for item in selected]
        names = [item[1] for item in selected]
        if queue:
            loaded_names = []
            images = get_cached_characters_round_images(
                urls, queue=True, names=names, loaded_names=loaded_names
            )
            if include_names:
                return {"images": images, "names": loaded_names}
            return images
        characters_round_characters = []
        characters_round_names = []
        if not urls:
            return
        get_cached_characters_round_images([urls[0]], names=[names[0]])
        def get_characters_round_characters_worker():
            get_cached_characters_round_images(urls[1:4], names=names[1:4])
        threading.Thread(target=get_characters_round_characters_worker, daemon=True).start()
    else:
        if queue:
            images = copy.copy(characters_round_image_cache_default)
            if include_names:
                return {"images": images, "names": [""] * len(images)}
            return images
        else:
            characters_round_characters = copy.copy(characters_round_image_cache_default)
            characters_round_names = [""] * len(characters_round_characters)


def _draw_character_caption(draw, name, x, y, img_size, border_px):
    """Draw a fitted one-line name caption inside the bottom of a card."""
    if not name or name.strip().casefold() == "unknown":
        return

    name = name.strip()
    pad = max(4, round(img_size * 0.018))
    max_text_width = img_size - (border_px + pad) * 2
    font_px = max(16, round(img_size * 0.09))
    min_font_px = max(11, round(img_size * 0.045))
    font = None
    text_bbox = None
    while font_px >= min_font_px:
        font = osd_text._get_ass_font(font_px, bold=True)
        if not font:
            return
        text_bbox = draw.textbbox((0, 0), name, font=font)
        if text_bbox[2] - text_bbox[0] <= max_text_width:
            break
        font_px -= 2

    if not text_bbox:
        return
    if text_bbox[2] - text_bbox[0] > max_text_width:
        base_name = name
        while base_name:
            base_name = base_name[:-1].rstrip()
            name = base_name + "…"
            text_bbox = draw.textbbox((0, 0), name, font=font)
            if text_bbox[2] - text_bbox[0] <= max_text_width:
                break

    text_height = text_bbox[3] - text_bbox[1]
    caption_height = max(round(img_size * 0.16), text_height + pad * 2)
    left = x + border_px
    right = x + img_size - border_px - 1
    bottom = y + img_size - border_px - 1
    top = bottom - caption_height
    draw.rectangle([left, top, right, bottom], fill=(0, 0, 0, 205))
    text_width = text_bbox[2] - text_bbox[0]
    text_x = x + (img_size - text_width) // 2 - text_bbox[0]
    text_y = top + (caption_height - text_height) // 2 - text_bbox[1]
    draw.text((text_x, text_y), name, font=font, fill=(255, 255, 255, 255))


def _get_grid_margin_y(osd_h, img_size, in_between, answer_view=False):
    margin_y = (osd_h - img_size * 2 - in_between) // 2
    if answer_view:
        margin_y -= round(osd_h * 0.0275)
    return max(0, margin_y)


def toggle_characters_overlay(num_characters=4, destroy=False, show_names=False):
    """Toggles the Characters Lightning Round overlay in a 2x2 grid (mpv PIL image overlay)."""
    global characters_overlay_boxes, _characters_img_overlay
    player = state.widgets.player

    if destroy:
        if _characters_img_overlay is not None:
            try:
                _characters_img_overlay.remove()
            except Exception:
                pass
            _characters_img_overlay = None
        characters_overlay_boxes = {}
        return

    num_characters = min(num_characters, len(characters_round_characters), 4)
    if num_characters == 0:
        return

    try:
        osd_w = player._p.osd_width  or 1920
        osd_h = player._p.osd_height or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080

    img_size   = int(min(osd_w, osd_h) * 0.35)
    in_between = osd_w // 80
    margin_x   = (osd_w - img_size * 2 - in_between) // 2
    margin_y   = _get_grid_margin_y(
        osd_h, img_size, in_between, answer_view=show_names
    )
    border_px  = max(2, round(4 * min(osd_w / 1920, osd_h / 1080)))  # matches highlightthickness=4
    inner      = img_size - border_px * 2

    grid_positions = [(0, 0), (1, 0), (0, 1), (1, 1)]

    from PIL import Image as _PILImage, ImageDraw as _PILDraw
    canvas = _PILImage.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw   = _PILDraw.Draw(canvas)

    for i in range(num_characters):
        col, row = grid_positions[i]
        x = margin_x + col * (img_size + in_between)
        y = margin_y + row * (img_size + in_between)

        # Black background (alpha=0.9 → 230)
        draw.rectangle([x, y, x + img_size - 1, y + img_size - 1], fill=(0, 0, 0, 230))

        # Character image
        src = (characters_round_characters[i]
               if i < len(characters_round_characters)
               else characters_round_image_cache_default[i]
               if i < len(characters_round_image_cache_default)
               else None)
        if src is not None:
            try:
                pil_img = ImageTk.getimage(src)
                pil_img = pil_img.resize((inner, inner), Image.LANCZOS)
                if pil_img.mode != "RGBA":
                    pil_img = pil_img.convert("RGBA")
                # Apply 0.9 alpha to image pixels to match Toplevel alpha
                r, g, b, a = pil_img.split()
                a = a.point(lambda v: int(v * 0.9))
                pil_img = Image.merge("RGBA", (r, g, b, a))
                canvas.paste(pil_img, (x + border_px, y + border_px), pil_img)
            except Exception:
                pass

        if show_names and i < len(characters_round_names):
            _draw_character_caption(
                draw,
                characters_round_names[i],
                x,
                y,
                img_size,
                border_px,
            )

        # White border (alpha=230 to match Tkinter 0.9 window alpha)
        draw.rectangle([x, y, x + img_size - 1, y + img_size - 1],
                       outline=(255, 255, 255, 230), width=border_px)

    if _characters_img_overlay is None:
        _characters_img_overlay = player._p.create_image_overlay()
    _characters_img_overlay.update(canvas)
    characters_overlay_boxes = {"active": True}
