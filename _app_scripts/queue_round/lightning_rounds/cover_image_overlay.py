"""COVER + IMAGE lightning-round helpers — both rounds load a PIL image
into the shared ``light_cover_image`` state which other reveal-mode
overlays (slice/tile/grow/edge/peek/filter/...) then read to draw.

Extracted from `guess_the_anime.py`. Both rounds are bundled here
because they share ``light_cover_image``:

* COVER fetches the AniDB cover_url and stores it.
* IMAGE fetches a Google key-visual via SerpAPI, falls back to the
  cover_url, and finally falls back to the placeholder image owned by
  ``characters_overlay.characters_round_image_cache_default``. IMAGE also
  records the source URL in ``last_image_source`` so the answer screen
  can show "IMAGE SOURCE: <domain>".

External writers/readers (all qualified at the call sites in main):

* ``cover_image_overlay.light_cover_image`` — read by every reveal-mode
  overlay's body (slice/tile/blur/zoom/etc.) and by the answer-screen
  cover-answer composition; reset to ``None`` in `clean_up_light_round`.
* ``cover_image_overlay.last_image_source`` — read by the answer-screen
  IMAGE-SOURCE banner; reset to ``["", ""]`` by `get_light_image_from_google`.
* ``cover_image_overlay.serpapi_limited`` — read by the queue
  prefetcher's "is image round possible?" gate.

Reads shared playback/settings state from ``core.game_state.state`` and
receives ``fixed_current_round`` / ``SERPAPI_KEY`` through narrow callbacks.
"""
from __future__ import annotations

import random
from io import BytesIO

import requests
from PIL import Image, ImageTk

from core.game_state import state
from . import title_overlay
from ...file.metadata import metadata_display


# ---------------------------------------------------------------------------
# Module state — externally read; see module docstring.
# ---------------------------------------------------------------------------
light_cover_image = None
last_image_source = ["", ""]  # [filename, image_url]

# COVER reveal-mode rotation
available_cover_reveal_modes = []
last_cover_reveal_mode = ""

# IMAGE reveal-mode rotation
available_image_reveal_modes = []
last_image_reveal_mode = ""

# SerpAPI state
SERPAPI_SEARCH_URL = "https://serpapi.com/search"
serpapi_limited = False
serpapi_limited_count = 0
_cached_serpapi_image_results = {}


# =============================================================================
# COVER LIGHTNING ROUND
# =============================================================================

def get_next_cover_reveal_mode():
    global available_cover_reveal_modes, last_cover_reveal_mode
    lightning_mode_settings = state.playback.lightning_mode_settings

    if not available_cover_reveal_modes:
        all_variants = []
        available_variants = []
        for variant, enabled in lightning_mode_settings.get("cover", {}).get("variants", {}).items():
            all_variants.append(variant)
            if enabled:
                available_variants.append(variant)
        available_variants = available_variants or all_variants
        while not available_cover_reveal_modes:
            available_cover_reveal_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_cover_reveal_modes) > 1 and available_cover_reveal_modes[0] == last_cover_reveal_mode:
                available_cover_reveal_modes = []

    last_cover_reveal_mode = available_cover_reveal_modes.pop(0)
    return last_cover_reveal_mode


def get_light_cover_image():
    """Load the AniDB cover into light_cover_image (falls back to placeholder)."""
    global light_cover_image
    # Import here to avoid a circular import (characters_overlay is a sibling module).
    from _app_scripts.queue_round.lightning_rounds import characters_overlay

    currently_playing = state.playback.currently_playing
    light_cover_image = None
    cover_url = currently_playing.get("data", {}).get("cover")
    if cover_url:
        try:
            # Load image without transparent box padding
            response = requests.get(cover_url)
            response.raise_for_status()
            image = Image.open(BytesIO(response.content)).convert("RGBA")
            max_dimension = 2000
            if image.width > max_dimension or image.height > max_dimension:
                scale = min(max_dimension / image.width, max_dimension / image.height)
                new_size = (int(image.width * scale), int(image.height * scale))
                image = image.resize(new_size, Image.LANCZOS)
            light_cover_image = ImageTk.PhotoImage(image)
        except Exception:
            pass
    light_cover_image = light_cover_image or characters_overlay.characters_round_image_cache_default[0]


# =============================================================================
# IMAGE LIGHTNING ROUND
# =============================================================================

def _build_image_search_queries(data):
    """Build search queries for anime images."""
    title = metadata_display.get_display_title(data)
    base_title = title_overlay.get_base_title(title=title)
    year = (data.get("season", "") or "")[-4:]
    year_token = year if year.isdigit() else ""

    queries = []
    for t in [title, base_title]:
        if not t:
            continue
        if year_token:
            queries.append(f"{t} anime key visual {year_token}")
        queries.append(f"{t} anime key visual")
        queries.append(f"{t} anime official art")

    seen = set()
    deduped = []
    for q in queries:
        if q not in seen:
            deduped.append(q)
            seen.add(q)
    return deduped


def search_serpapi_image_urls(query, max_results=8):
    """Return a list of image URLs from SerpAPI image search."""
    global serpapi_limited, serpapi_limited_count
    SERPAPI_KEY = state.config.SERPAPI_KEY

    if not SERPAPI_KEY or serpapi_limited:
        return []

    if query in _cached_serpapi_image_results:
        return _cached_serpapi_image_results.get(query, [])

    params = {
        "api_key": SERPAPI_KEY,
        "engine": "google",
        "q": query,
        "tbm": "isch",
        "num": max(1, min(10, max_results))
    }

    try:
        response = requests.get(SERPAPI_SEARCH_URL, params=params, timeout=8)
        if response.status_code in (403, 429):
            serpapi_limited_count += 1
            if serpapi_limited_count >= 3:
                serpapi_limited = True
            try:
                print(f"SerpAPI error {response.status_code}: {response.text}")
            except Exception:
                pass
            return []
        response.raise_for_status()
        data = response.json()

        if data.get("error"):
            serpapi_limited_count += 1
            if serpapi_limited_count >= 3:
                serpapi_limited = True
            try:
                print(f"SerpAPI error: {data.get('error')}")
            except Exception:
                pass
            return []

        # SerpAPI returns images in 'images_results' array
        items = data.get("images_results", [])
        if not items:
            try:
                print(f"SerpAPI returned 0 images for query: {query}")
            except Exception:
                pass
            return []

        # Get original image URLs
        urls = [item.get("original") for item in items if item.get("original")]
        if urls:
            _cached_serpapi_image_results[query] = urls
        serpapi_limited_count = 0
        return urls
    except Exception as e:
        serpapi_limited_count += 1
        if serpapi_limited_count >= 3:
            serpapi_limited = True
        try:
            print(f"SerpAPI request failed: {e}")
        except Exception:
            pass
        return []


def get_google_image_url(data=None):
    """Pick a random image URL for the given anime data using SerpAPI."""
    currently_playing = state.playback.currently_playing
    fixed_current_round = state.lightning.fixed_current_round
    if not data:
        data = currently_playing.get("data")
    if fixed_current_round:
        return fixed_current_round.get("image_url")
    if not data:
        return None
    queries = _build_image_search_queries(data)
    for query in queries:
        urls = search_serpapi_image_urls(query)
        if urls:
            return random.choice(urls)
    return None


def get_next_image_reveal_mode():
    global available_image_reveal_modes, last_image_reveal_mode
    lightning_mode_settings = state.playback.lightning_mode_settings

    if not available_image_reveal_modes:
        all_variants = []
        available_variants = []
        for variant, enabled in lightning_mode_settings.get("image", {}).get("variants", {}).items():
            all_variants.append(variant)
            if enabled:
                available_variants.append(variant)
        available_variants = available_variants or all_variants
        while not available_image_reveal_modes:
            available_image_reveal_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_image_reveal_modes) > 1 and available_image_reveal_modes[0] == last_image_reveal_mode:
                available_image_reveal_modes = []

    last_image_reveal_mode = available_image_reveal_modes.pop(0)
    return last_image_reveal_mode


def get_light_image_from_google():
    """Load a Google image into light_cover_image (fallback to cover/default)."""
    global light_cover_image, last_image_source
    # Lazy import to avoid circular sibling import.
    from _app_scripts.queue_round.lightning_rounds import characters_overlay

    from _app_scripts.queue_round.lightning_rounds import lightning_manager
    currently_playing = state.playback.currently_playing
    lightning_queue_data = lightning_manager.lightning_queue_data

    light_cover_image = None
    last_image_source = ["", ""]

    filename = currently_playing.get("filename")
    queued_url = None
    if filename:
        queued_url = lightning_queue_data.get(filename, {}).get("image_url")

    tried_urls = []
    for url in [queued_url, get_google_image_url(currently_playing.get("data"))]:
        if not url or url in tried_urls:
            continue
        tried_urls.append(url)
        try:
            # Load image without transparent box padding
            response = requests.get(url)
            response.raise_for_status()
            image = Image.open(BytesIO(response.content)).convert("RGBA")
            max_dimension = 2000
            if image.width > max_dimension or image.height > max_dimension:
                scale = min(max_dimension / image.width, max_dimension / image.height)
                new_size = (int(image.width * scale), int(image.height * scale))
                image = image.resize(new_size, Image.LANCZOS)
            light_cover_image = ImageTk.PhotoImage(image)
            if light_cover_image:
                last_image_source = [filename, url]
                break
        except Exception:
            continue

    if not light_cover_image:
        try:
            print("Image lightning round: no Google image found, falling back to cover art.")
        except Exception:
            pass
        cover_url = currently_playing.get("data", {}).get("cover")
        if cover_url:
            try:
                # Load image without transparent box padding
                response = requests.get(cover_url)
                response.raise_for_status()
                image = Image.open(BytesIO(response.content)).convert("RGBA")
                max_dimension = 2000
                if image.width > max_dimension or image.height > max_dimension:
                    scale = min(max_dimension / image.width, max_dimension / image.height)
                    new_size = (int(image.width * scale), int(image.height * scale))
                    image = image.resize(new_size, Image.LANCZOS)
                light_cover_image = ImageTk.PhotoImage(image)
            except Exception:
                light_cover_image = None

    light_cover_image = light_cover_image or characters_overlay.characters_round_image_cache_default[0]
