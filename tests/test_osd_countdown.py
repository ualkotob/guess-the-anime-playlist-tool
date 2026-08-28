"""Regression coverage for the shared countdown/mute overlay."""

from _app_scripts.playback import osd_text


def test_mute_badge_composes_with_and_survives_countdown(monkeypatch):
    rendered = []
    monkeypatch.setattr(
        osd_text,
        "set_floating_text",
        lambda name, value, **kwargs: rendered.append((name, value, kwargs)),
    )
    monkeypatch.setattr(osd_text, "_countdown_value", None)
    monkeypatch.setattr(osd_text, "_countdown_position", "top right")
    monkeypatch.setattr(osd_text, "_countdown_inverse", False)
    monkeypatch.setattr(osd_text, "_countdown_muted", False)

    osd_text.set_countdown_muted(True)
    osd_text.set_countdown(8)
    osd_text.set_countdown()
    osd_text.set_countdown_muted(False)

    assert rendered == [
        ("Countdown", "🔇", {"position": "top right", "inverse": False}),
        ("Countdown", "8  🔇", {"position": "top right", "inverse": False}),
        ("Countdown", "🔇", {"position": "top right", "inverse": False}),
        ("Countdown", None, {"position": "top right", "inverse": False}),
    ]


def test_mute_badge_follows_countdown_position_and_style(monkeypatch):
    rendered = []
    monkeypatch.setattr(
        osd_text,
        "set_floating_text",
        lambda name, value, **kwargs: rendered.append((value, kwargs)),
    )
    monkeypatch.setattr(osd_text, "_countdown_value", None)
    monkeypatch.setattr(osd_text, "_countdown_position", "top right")
    monkeypatch.setattr(osd_text, "_countdown_inverse", False)
    monkeypatch.setattr(osd_text, "_countdown_muted", False)

    osd_text.set_countdown(5, position="center", inverse=True)
    osd_text.set_countdown_muted(True)

    assert rendered[-1] == ("5  🔇", {"position": "center", "inverse": True})
