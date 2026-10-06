from types import SimpleNamespace

from core.game_state import state
from _app_scripts.playback import coming_up_ui


class _Font:
    def getlength(self, text):
        return len(text) * 10


def test_details_wrap_to_popup_width_and_box_covers_text(monkeypatch):
    player = SimpleNamespace(_p=SimpleNamespace())
    monkeypatch.setattr(state.widgets, "player", player)
    monkeypatch.setattr(state.colors, "OVERLAY_BACKGROUND_COLOR", "black")
    monkeypatch.setattr(state.colors, "OVERLAY_TEXT_COLOR", "white")
    monkeypatch.setattr(coming_up_ui.osd_text, "_get_ass_font", lambda _size: _Font())
    wrap_calls = []

    def wrap(text, _size, width):
        wrap_calls.append((text, width))
        return [text]

    monkeypatch.setattr(coming_up_ui.osd_text, "_ass_wrap_text", wrap)
    monkeypatch.setattr(coming_up_ui.osd_text, "osd_command", lambda *_args: None)

    details = "x" * 40
    coming_up_ui._render_coming_up_frame(
        "TAGS", details, None, 10, 1000, 500, 1.0
    )

    detail_width = next(width for text, width in wrap_calls if text == details)
    assert detail_width == 630  # 65% box cap minus 10px padding per side
    assert coming_up_ui._coming_up_osd_box_w == 420
