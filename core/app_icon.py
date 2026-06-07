"""Application window icon asset.

Holds the base64-encoded 32x32 PNG app icon (generated from
guess_the_anime.ico) and a helper to apply it to a Tk root window. Kept out of
`guess_the_anime.py` so the large data blob does not clutter the orchestration
hub; the decoded PhotoImage reference is retained at module level so Tk does not
garbage-collect it.
"""

import base64
import tkinter as tk

# App icon (32x32 PNG, base64-encoded from guess_the_anime.ico)
APP_ICON_B64 = (
    "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"
)

# Retain the decoded PhotoImage so Tk does not garbage-collect the icon.
_icon_img = None


def set_app_icon(root):
    """Decode the embedded icon and apply it to the given Tk root window."""
    global _icon_img
    try:
        _icon_img = tk.PhotoImage(data=base64.b64decode(APP_ICON_B64))
        root.iconphoto(True, _icon_img)
    except Exception:
        pass
