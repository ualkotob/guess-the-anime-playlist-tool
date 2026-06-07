"""CHARACTER PARTS lightning-round helpers — picks a character image,
renders it as a single mpv image-overlay (or 4 zoomed parts for the
*PARTS variant). Used by every character-based reveal mode
(PIXEL/REVEAL/BLUR/ZOOM/PARTS) which all consume the shared
``character_round_answer`` (the picked [name, image, gender, desc]).

Extracted from `guess_the_anime.py`.

``character_round_answer`` deliberately stays in main — it's read by
the lightning ticker, every PIXEL/REVEAL/BLUR/ZOOM reveal overlay, the
cleanup answer-screen, and the background-music floating-text. Until
lightning state migrates into ``core.game_state`` it lives in main and
this module reads/writes it via ``state.lightning.character_round_answer``.

External readers/writers of module state (all qualified at the call
sites in main):

* ``character_parts_overlay.character_image_overlay`` — read by the
  lightning ticker to decide whether the mpv image overlay needs a
  resize-after-OSD-known refresh.

Reads shared lightning, playback, playlist, and metadata state from
``core.game_state.state``.

Sibling module ``characters_overlay`` is imported lazily inside the
functions that need its placeholder image fallback, to dodge a
circular sibling import.
"""
from __future__ import annotations

import random
import re

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from core.game_state import state
from ...ui.scaling import scl
from ...playback import image_loader


# ---------------------------------------------------------------------------
# Module state — see module docstring for the external-write story.
# ---------------------------------------------------------------------------
# ``character_round_answer`` deliberately stays in main (read by every
# character-mode lightning round, not just *PARTS); this module reads
# and writes it via ``state.lightning.character_round_answer`` until the
# eventual lightning-state migration to ``core.game_state``.
character_image_overlay           = None   # mpv image overlay object
_character_image_overlay_source   = None   # last `character` arg, for re-resize


# =============================================================================
# Name + description helpers
# =============================================================================

def match_character_names(name1, name2):
    """
    Check if two character names match, accounting for firstname/lastname variations.

    Examples:
        "John Smith" matches "Smith John"
        "Eren Yeager" matches "Yeager Eren"
    """
    if not name1 or not name2:
        return False

    # Normalize names (lowercase, remove extra spaces)
    name1_clean = " ".join(name1.lower().split())
    name2_clean = " ".join(name2.lower().split())

    # Direct match
    if name1_clean == name2_clean:
        return True

    # Split into parts
    parts1 = name1_clean.split()
    parts2 = name2_clean.split()

    # If different number of parts, no match (we're being strict here)
    if len(parts1) != len(parts2):
        return False

    if len(parts1) == 2 and len(parts2) == 2:
        if parts1[0] == parts2[1] and parts1[1] == parts2[0]:
            return True

    if set(parts1) == set(parts2):
        return True

    return False


def get_anilist_character_description(character_name, anilist_id):
    """Get character description from AniList metadata."""
    anilist_metadata = state.metadata.anilist_metadata
    if not anilist_id or str(anilist_id) not in anilist_metadata:
        return ""

    anilist_data = anilist_metadata[str(anilist_id)]
    anilist_characters = anilist_data.get("characters", [])

    for char in anilist_characters:
        char_name = char.get("name", "")
        if match_character_names(character_name, char_name):
            desc = char.get("description", "")
            if desc:
                # Clean HTML tags
                desc = re.sub(r'<[^>]+>', '', desc)
                # Clean spoiler tags
                desc = re.sub(r'~!.*?!~', '[SPOILER]', desc)
                # Clean markdown bold (__text__ or **text**)
                desc = re.sub(r'__([^_]+)__', r'\1', desc)
                desc = re.sub(r'\*\*([^*]+)\*\*', r'\1', desc)
                # Remove character links entirely (relatives)
                desc = re.sub(r'\[([^\]]+)\]\([^\)]+\)', '', desc)
                desc = desc.replace('\\n', '\n')
                # Remove entire lines that contain "Relatives:"
                desc = re.sub(r'^.*Relatives:.*$\n?', '', desc, flags=re.MULTILINE)
                desc = re.sub(r'(Height: [^\n]+?)(\s*\n)', r'\1.\2', desc)
                desc = re.sub(r'(Position: [^\n]+?)(\s*\n)', r'\1.\2', desc)
                # Clean up multiple consecutive newlines
                desc = re.sub(r'\n{3,}', '\n\n', desc)
                # Clean up extra spaces
                desc = re.sub(r' {2,}', ' ', desc)
                return desc.strip()

    return ""


def clean_character_description(name, desc):
    # 1. Replace hyperlinks like: http://... [text] → text
    desc = re.sub(r'http\S+\s+\[([^\]]+)\]', r'\1', desc)

    # 2. Remove spoiler markdown tags and their content
    desc = re.sub(r'~!([^!]+)!~', '', desc)  # AniList format: ~!text!~
    desc = re.sub(r'\|\|([^|]+)\|\|', '', desc)  # Discord format: ||text||
    desc = re.sub(r'>!([^!]+)!<', '', desc)  # Reddit format: >!text!<

    # Remove literal [SPOILER] markers (case-insensitive)
    desc = re.sub(r'\[spoiler\]', '', desc, flags=re.IGNORECASE)

    # 3. Remove character name (first + last and variants)
    if name:
        parts = name.split()
        for variant in [name, name.replace(" ", ""), *parts]:
            pattern = re.compile(re.escape(variant), re.IGNORECASE)
            replacement = "_" * len(variant)
            desc = pattern.sub(replacement, desc)

    # 4. Remove "(Source: " and everything after it
    source_index = desc.find("(Source:")
    if source_index != -1:
        desc = desc[:source_index].strip()

    # 5. Normalize whitespace and newlines
    desc = desc.replace("\n", " ").strip()
    desc = re.sub(r'\s+', ' ', desc)

    return desc


# =============================================================================
# Character picker
# =============================================================================

def get_character_round_image(types=['m'], min_desc_length=0, data=None, queue=False, mode=None):
    """
    Returns the character image (Tk-compatible), and updates character_round_answer as:
    [name, image, gender, description]
    Falls back to secondary characters if no matches found in preferred types.
    Avoids recently used characters in lightning history, if possible.
    """
    # Lazy import to dodge circular sibling import.
    from _app_scripts.queue_round.lightning_rounds import characters_overlay

    light_mode         = state.lightning.light_mode
    currently_playing  = state.playback.currently_playing
    playlist           = state.metadata.playlist

    mode = mode or light_mode

    if not data:
        data = currently_playing.get("data")

    def return_image(name, img, gender="Unknown", desc="No description available.", queue=False):
        if queue:
            return [name, img, gender, desc]
        else:
            state.lightning.character_round_answer = [name, img, gender, desc]
            return img

    if not data or not data.get("characters"):
        return return_image("Unknown", characters_overlay.characters_round_image_cache_default[0], queue=queue)

    def get_candidates(allowed_types):
        def clean(text):
            return text.strip() if text and text.strip() else ""

        return [
            (
                c[1],  # name
                "https://cdn-eu.anidb.net/images/main/" + c[2],  # image URL
                clean(c[3]) if len(c) > 3 else "Unknown",  # gender
                clean_character_description(c[1], clean(c[4])) if len(c) > 4 else ""  # description
            )
            for c in data["characters"]
            if c[0] in allowed_types
        ]

    # Get the current character-based lightning mode history
    char_history = []
    if mode and mode.startswith("c."):
        char_history = playlist.get("lightning_history", {}).get(mode, [])

    candidates = []
    for i, t in enumerate(types):
        for candidate in get_candidates([t]):
            for i in range(len(types)-i):
                candidates.append(candidate)

    if not candidates:
        search_types = types + ['a'] if 's' in types else types + ['s']
        candidates = get_candidates(search_types)

    if not candidates:
        return return_image("Unknown", characters_overlay.characters_round_image_cache_default[0], queue=queue)

    # First, try to find a candidate with sufficient description (check both AniDB and AniList)
    long_desc_candidates = []
    for c in candidates:
        name, url, gender, anidb_desc = c
        if len(anidb_desc) >= min_desc_length:
            long_desc_candidates.append(c)
        # If AniDB description is too short, check AniList
        elif min_desc_length > 0 and data.get("anilist"):
            anilist_desc = get_anilist_character_description(name, data.get("anilist"))
            if anilist_desc:
                # Clean the character name from the AniList description
                cleaned_anilist_desc = clean_character_description(name, anilist_desc)
                if len(cleaned_anilist_desc) >= min_desc_length:
                    # Create new candidate tuple with cleaned AniList description
                    long_desc_candidates.append((name, url, gender, cleaned_anilist_desc))

    # Try filtering out characters in the history
    def filter_history(pool):
        filtered = [c for c in pool if c[0] not in char_history]
        return filtered if filtered else pool  # fallback to full pool if empty

    filtered_pool = filter_history(long_desc_candidates) if long_desc_candidates else filter_history(candidates)

    random.shuffle(filtered_pool)
    name, chosen_url, gender, desc = filtered_pool[0]

    # If description is missing or very short, try to get it from AniList
    MIN_DESC_THRESHOLD = 120  # Consider descriptions under this length as "short"
    if (not desc or len(desc) < MIN_DESC_THRESHOLD) and data.get("anilist"):
        anilist_desc = get_anilist_character_description(name, data.get("anilist"))
        if anilist_desc and len(anilist_desc) > len(desc):
            desc = clean_character_description(name, anilist_desc)

    # Try loading the image
    tk_img = image_loader.load_image_from_url(chosen_url, size=None)
    if not tk_img:
        return return_image(name, characters_overlay.characters_round_image_cache_default[0], gender, desc, queue=queue)

    return return_image(name, tk_img, gender, desc, queue=queue)


# =============================================================================
# Single-image mpv overlay (used by base CHARACTER round + variants)
# =============================================================================

def toggle_character_image_overlay(character=None, destroy=False):
    global character_image_overlay, _character_image_overlay_source

    if destroy or not character:
        if character_image_overlay is not None:
            try:
                character_image_overlay.remove()
            except Exception:
                pass
            character_image_overlay = None
        _character_image_overlay_source = None
        return

    _character_image_overlay_source = character
    _update_character_image_overlay()


def _update_character_image_overlay():
    """Build and push the character image to the mpv OSD overlay."""
    global character_image_overlay
    player = state.widgets.player
    lightning_mode_settings = state.playback.lightning_mode_settings

    character = _character_image_overlay_source
    if not character:
        return

    try:
        osd_w = int(player._p.osd_width  or 0) or 1920
        osd_h = int(player._p.osd_height or 0) or 1080
    except Exception:
        osd_w, osd_h = 1920, 1080

    width_percent = lightning_mode_settings.get("_misc_settings", {}).get("image_width_percent", 70) / 100
    max_width  = int(osd_w * width_percent)
    max_height = int(osd_h * 0.7)

    # Build PIL image (single or multi-image side-by-side)
    if isinstance(character, (list, tuple)):
        pil_images = []
        for img in character:
            if not img:
                continue
            try:
                rgba_img = ImageTk.getimage(img).convert("RGBA")
                try:
                    alpha_bbox = rgba_img.getchannel("A").getbbox()
                    if alpha_bbox:
                        rgba_img = rgba_img.crop(alpha_bbox)
                except Exception:
                    pass
                pil_images.append(rgba_img)
            except Exception:
                continue
        if not pil_images:
            return
        if len(pil_images) == 1:
            pil_image = pil_images[0]
        else:
            target_height = max(img.height for img in pil_images)
            normalized = []
            for img in pil_images:
                if img.height != target_height and img.height > 0:
                    new_w = int(img.width * (target_height / img.height))
                    img = img.resize((max(1, new_w), target_height), Image.LANCZOS)
                normalized.append(img)
            total_width = sum(img.width for img in normalized)
            combined = Image.new("RGBA", (total_width, target_height), (0, 0, 0, 0))
            x_offset = 0
            for img in normalized:
                combined.paste(img, (x_offset, 0), img)
                x_offset += img.width
            pil_image = combined
    else:
        pil_image = ImageTk.getimage(character).convert("RGBA")
        try:
            alpha_bbox = pil_image.getchannel("A").getbbox()
            if alpha_bbox:
                pil_image = pil_image.crop(alpha_bbox)
        except Exception:
            pass

    img_w, img_h = pil_image.size
    scale  = min(max_width / img_w, max_height / img_h)
    new_w  = max(1, int(img_w * scale))
    new_h  = max(1, int(img_h * scale))
    resized = pil_image.resize((new_w, new_h), Image.LANCZOS).convert("RGBA")
    r, g, b, a = resized.split()
    a = a.point(lambda x: int(x * 0.95))
    resized = Image.merge("RGBA", (r, g, b, a))

    border = scl(4)
    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    cx = (osd_w - new_w) // 2
    cy = int((osd_h - new_h) // 2 - osd_h * 0.025)
    # Black border rect
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([cx - border, cy - border, cx + new_w + border, cy + new_h + border], fill=(0, 0, 0, 242))
    canvas.paste(resized, (cx, cy), resized)

    if character_image_overlay is None:
        character_image_overlay = player._p.create_image_overlay()
    try:
        character_image_overlay.update(canvas)
    except Exception:
        pass


# =============================================================================
# *PARTS round helper — zoomed body region crops
# =============================================================================

def generate_weighted_zoomed_parts(tk_img, num_parts=4, target_size=(400, 400)):
    """
    Generate 4 zoomed-in square crops from semantically distinct vertical regions
    (e.g., head, torso, legs, feet). Ensures cropped areas are distinct enough vertically.
    """
    root = state.widgets.root
    pil_image = ImageTk.getimage(tk_img).convert("RGBA")
    img_w, img_h = pil_image.size
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    img_size = int(min(screen_width, screen_height) * 0.35)
    box_w, box_h = img_size, img_size

    chosen_regions = [
        ("feet", (0.70, 1.0), (2, 4.5)),
        ("legs", (0.45, 0.8), (2, 4)),
        ("body", (0.25, 0.55), (1.5, 3.5)),
        ("head", (0.0, 0.33), (1.5, 3))
    ]

    zoomed_parts = []
    used_centers = []

    def is_solid_color(image_crop, tolerance=70):
        arr = np.array(image_crop.convert("L"))
        return arr.std() <= tolerance, arr.std()

    for region_name, (rel_start, rel_end), (zoom_min, zoom_max) in chosen_regions:
        best_attempt, best_amount = None, 0

        for attempt in range(50):
            zoom_factor = random.uniform(zoom_min, zoom_max)
            region_h = int(img_h * (rel_end - rel_start))
            crop_size = int(min(img_w, region_h) / zoom_factor)
            crop_w, crop_h = crop_size, crop_size

            y_min = int(img_h * rel_start)
            y_max = int(img_h * rel_end - crop_h)
            y_max = max(y_min, y_max)

            x_max = img_w - crop_w
            x_max = max(0, x_max)

            offset_x = random.randint(0, x_max) if x_max > 0 else 0
            offset_y = random.randint(y_min, y_max) if y_max > y_min else y_min

            vertical_center = (offset_y + crop_h / 2) / img_h

            too_close = any(abs(vertical_center - prev) < 0.15 for prev in used_centers)
            if too_close:
                continue

            cropped = pil_image.crop((offset_x, offset_y, offset_x + crop_w, offset_y + crop_h))
            is_solid, amount = is_solid_color(cropped)
            if not is_solid:
                used_centers.append(vertical_center)
                break
            elif best_amount < amount:
                best_attempt = cropped
                best_amount = amount

        else:
            cropped = best_attempt

        resized = cropped.resize((box_w, box_h), Image.LANCZOS)
        background = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        background.paste(resized, (0, 0))
        zoomed_parts.append(ImageTk.PhotoImage(background))

    return zoomed_parts


def get_char_parts_round_character():
    """Selects one character matching given types and prepares 4 zoomed parts as separate images."""
    # Lazy import to dodge circular sibling import.
    from _app_scripts.queue_round.lightning_rounds import characters_overlay
    character_round_answer = state.lightning.character_round_answer
    # Generate zoomed-in pieces and store them
    characters_overlay.characters_round_characters = generate_weighted_zoomed_parts(character_round_answer[1])


# =============================================================================
# Eligibility helper used by the queue prefetcher
# =============================================================================

def has_char_descriptions(characters, length, types=None, anilist_id=None):
    """
    Returns True if any character in the list has a description
    of at least the given length (from AniDB or AniList).
    """
    anilist_metadata = state.metadata.anilist_metadata

    # First check AniDB descriptions
    for char in characters:
        if types and char[0] not in types:
            continue
        if len(char) > 4:
            desc = char[4].strip()
            if len(desc) >= length:
                return True

    # If no AniDB descriptions found, check AniList descriptions
    if anilist_id and str(anilist_id) in anilist_metadata:
        anilist_data = anilist_metadata[str(anilist_id)]
        anilist_characters = anilist_data.get("characters", [])

        for char in characters:
            if types and char[0] not in types:
                continue

            char_name = char[1] if len(char) > 1 else ""
            if not char_name:
                continue

            # Try to find matching AniList character
            for anilist_char in anilist_characters:
                anilist_name = anilist_char.get("name", "")
                if match_character_names(char_name, anilist_name):
                    anilist_desc = anilist_char.get("description", "")
                    if anilist_desc:
                        # Clean HTML tags
                        clean_desc = re.sub(r'<[^>]+>', '', anilist_desc)
                        # Clean spoiler tags
                        clean_desc = re.sub(r'~!.*?!~', '[SPOILER]', clean_desc)
                        # Clean markdown bold (__text__ or **text**)
                        clean_desc = re.sub(r'__([^_]+)__', r'\1', clean_desc)
                        clean_desc = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean_desc)
                        # Remove character links entirely
                        clean_desc = re.sub(r'\[([^\]]+)\]\([^\)]+\)', '', clean_desc)
                        # Handle newlines
                        clean_desc = clean_desc.replace('\\n', '\n')
                        # Remove entire lines that contain "Relatives:"
                        clean_desc = re.sub(r'^.*Relatives:.*$\n?', '', clean_desc, flags=re.MULTILINE)
                        # Clean extra spaces
                        clean_desc = re.sub(r' {2,}', ' ', clean_desc)

                        if len(clean_desc.strip()) >= length:
                            return True
                    break

    return False
