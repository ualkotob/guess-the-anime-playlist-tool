"""UI scaling helper.

`scl(num, type=None)` scales a pixel value by the screen resolution relative
to the 2560x1440 reference. When ``type == "UI"`` and the user has not enabled
``scale_main_ui``, the value is returned unscaled (the main UI stays at its
designed size unless explicitly opted in).

Reads screen geometry and the scale toggle from ``state.display``.
"""

from core.game_state import state


def scl(num, type=None):
    if type == "UI" and not state.display.scale_main_ui:
        return num
    modifier_w = state.display.screen_width / 2560
    modifier_h = state.display.screen_height / 1440
    modifier = min(modifier_w, modifier_h)
    return int(num * modifier)
