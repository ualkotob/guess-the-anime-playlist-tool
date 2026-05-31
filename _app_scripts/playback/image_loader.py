"""Shared image loading and resizing helpers."""

from io import BytesIO

import requests
from PIL import Image, ImageTk


cached_images = {}


def _load_pil_from_url(url):
    if cached_images.get(url):
        return cached_images[url]

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        cached_images[url] = image
        return image
    except Exception as e:
        print(f"image_loader: failed to load {url!r}: {e}")
        return None


def fit_image_in_box(image, size):
    """Resize an RGBA PIL image to fit inside size and center it in a transparent box."""
    if not size:
        return image.copy()

    box_width, box_height = size
    img_width, img_height = image.size
    scale = min(box_width / img_width, box_height / img_height)
    new_size = (int(img_width * scale), int(img_height * scale))
    resized = image.resize(new_size, Image.LANCZOS)

    background = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    offset_x = (box_width - new_size[0]) // 2
    offset_y = (box_height - new_size[1]) // 2
    background.paste(resized, (offset_x, offset_y), resized)
    return background


def load_image_from_url(url, size=(400, 400)):
    """Load a URL image, fit it into size, and return an ImageTk.PhotoImage."""
    image = _load_pil_from_url(url)
    if image is None:
        return None
    if not size:
        return ImageTk.PhotoImage(image)
    return ImageTk.PhotoImage(fit_image_in_box(image, size))


def load_pil_image_from_url(url, size=(400, 225)):
    """Load a URL image, fit it into size, and return a PIL RGBA Image."""
    image = _load_pil_from_url(url)
    if image is None:
        return None
    return fit_image_in_box(image, size)
