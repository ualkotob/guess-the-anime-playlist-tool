import re
from types import SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts.information import information_popup


class _Font:
    def __init__(self, size):
        self.size = size

    def getlength(self, text):
        return sum(2 if ord(char) > 127 else 1 for char in text) * self.size * 0.5


def _rendered_width(text, size):
    # mpv's ASS rendering is narrower than PIL's Arial Bold metrics.
    return round(_Font(size).getlength(text) * 0.91)


@pytest.mark.parametrize("osd_width, osd_height", [(640, 360), (1280, 720)])
def test_long_alternate_title_stays_inside_popup(monkeypatch, osd_width, osd_height):
    player = SimpleNamespace(_p=SimpleNamespace(osd_width=osd_width, osd_height=osd_height))
    monkeypatch.setattr(state.widgets, "player", player)
    monkeypatch.setattr(information_popup.osd_text, "_get_ass_font", _Font)
    monkeypatch.setattr(information_popup.osd_text, "_color_str_to_ass_bgr", lambda _color: "FFFFFF")
    commands = []
    monkeypatch.setattr(information_popup, "_osd_command", lambda *args: commands.append(args))

    alternate_title = " ".join(["Tsuuhou sareta Cheat Fuyo Majutsushi wa Kimama"] * 12)
    inline_bottom_row = f"MAL Score: 7.4 | {alternate_title} | MAL Members: 100,000\nStudio | TV"
    information_popup._draw_title_popup_osd(
        "Opening 1 | Ember Torch by sumika | Fall 2026",
        "The Laid-Off Cheat-Granting Mage Enjoys a Second Lease on Life",
        "MAL Score: 7.4 | MAL Members: 100,000\nAniList Score: 74% | Action, Comedy, Fantasy | Airing | TV | Manga",
        "black", "white", alternate_title, inline_bottom_row,
        ("MAL Score: 7.4", "MAL Members: 100,000"),
    )

    events = commands[-1][3].split("\n")
    box = re.search(r"\\pos\((\d+),(\d+)\).*?l (\d+) 0 \d+ (\d+)", events[0])
    x, y, width, height = map(int, box.groups())
    assert 0 <= x and x + width <= osd_width
    assert 0 <= y and y + height <= osd_height

    assert len(events) == 6  # background, top, primary, first title line, combined second line, details
    assert r"\N" not in events[2]  # the primary title shrinks instead of wrapping
    normal_title_size = max(14, round(50 * min(osd_width / 2560, osd_height / 1440) * 1.6))
    assert int(re.search(r"\\fs(\d+)", events[2]).group(1)) < normal_title_size
    assert r"\an8" in events[3] and r"\N" not in events[3]
    second_event = events[4]
    assert r"\an8" in second_event
    font_size = int(re.search(r"\\fs(\d+)", second_event).group(1))
    second_row = second_event.split("}", 1)[1]
    prefix, suffix = "MAL Score: 7.4 | ", " | MAL Members: 100,000"
    assert second_row.startswith(prefix) and second_row.endswith(suffix)
    assert second_row.count(" | ") == 2
    assert _rendered_width(second_row, font_size) <= width
    second_title_line = second_row[len(prefix):-len(suffix)]
    assert second_title_line.endswith("…")
    first_title_line = events[3].split("}", 1)[1]
    first_font_size = int(re.search(r"\\fs(\d+)", events[3]).group(1))
    assert first_font_size == font_size
    assert abs(_rendered_width(first_title_line, font_size) - _rendered_width(second_title_line, font_size)) < 120
    first_x = int(re.search(r"\\pos\((\d+),", events[3]).group(1))
    second_x = int(re.search(r"\\pos\((\d+),", events[4]).group(1))
    title_center = (
        osd_width - _rendered_width(second_row, font_size)
        + _rendered_width(prefix, font_size)
        + _rendered_width(prefix + second_title_line, font_size)
    ) / 2
    assert second_x == osd_width // 2
    assert abs(first_x - title_center) <= 1
    assert first_x != second_x  # asymmetric statistics shift the title's center
    assert x <= first_x - _rendered_width(first_title_line, font_size) / 2
    assert first_x + _rendered_width(first_title_line, font_size) / 2 <= x + width


def test_two_line_title_keeps_the_full_text_when_it_fits(monkeypatch):
    monkeypatch.setattr(information_popup.osd_text, "_get_ass_font", _Font)
    title = (
        "Tsuuhou sareta Cheat Fuyo Majutsushi wa Kimama na Second Life wo Ouka suru. "
        "Ore wa Buki dake ja Naku, Arayuru Mono ni Kyoka Point wo Fuyo Dekiru shi, "
        "Ore no Ishi de Itsudemo Kouka wo Kaijo Dekiru kedo, Nokotta Hitotachi Daijoubu?"
    )
    first, second, fs = information_popup._split_popup_title_with_sides(
        title, 12, 1240, 950
    )
    assert first + " " + second == title
    assert fs == 12
    assert _rendered_width(first, fs) <= 1240
    assert _rendered_width(second, fs) <= 950
    assert abs(_rendered_width(first, fs) - _rendered_width(second, fs)) < 100


def test_short_alternate_title_keeps_the_existing_single_line_layout(monkeypatch):
    player = SimpleNamespace(_p=SimpleNamespace(osd_width=1280, osd_height=720))
    monkeypatch.setattr(state.widgets, "player", player)
    monkeypatch.setattr(information_popup.osd_text, "_get_ass_font", _Font)
    monkeypatch.setattr(information_popup.osd_text, "_color_str_to_ass_bgr", lambda _color: "FFFFFF")
    commands = []
    monkeypatch.setattr(information_popup, "_osd_command", lambda *args: commands.append(args))

    inline_bottom_row = "MAL Score: 7.4 | Short Japanese Title | MAL Members: 100,000\nStudio | TV"
    information_popup._draw_title_popup_osd(
        "Opening 1 | Theme | Fall 2026", "English Title", "MAL Score: 7.4 | MAL Members: 100,000\nStudio | TV",
        "black", "white", "Short Japanese Title", inline_bottom_row,
        ("MAL Score: 7.4", "MAL Members: 100,000"),
    )

    events = commands[-1][3].split("\n")
    assert len(events) == 4  # background, top, primary title, existing metadata block
    assert "MAL Score: 7.4 | Short Japanese Title | MAL Members: 100,000" in events[-1]


def test_unspaced_japanese_title_wraps_without_overflow(monkeypatch):
    monkeypatch.setattr(information_popup.osd_text, "_get_ass_font", _Font)
    title = "異世界で勇者になった私の長い物語" * 5
    lines = information_popup._wrap_popup_text(title, 20, 120)
    assert "".join(lines) == title
    assert len(lines) > 1
    assert all(_rendered_width(line, 20) <= 120 for line in lines)


def test_popup_background_hugs_the_rendered_text(monkeypatch):
    player = SimpleNamespace(_p=SimpleNamespace(osd_width=1280, osd_height=720))
    monkeypatch.setattr(state.widgets, "player", player)
    monkeypatch.setattr(information_popup.osd_text, "_get_ass_font", _Font)
    commands = []
    monkeypatch.setattr(information_popup, "_osd_command", lambda *args: commands.append(args))

    information_popup._draw_title_popup_osd("", "A familiar anime title", "", "black", "white")

    background, title_event = commands[-1][3].split("\n")
    box_width = int(re.search(r"l (\d+) 0", background).group(1))
    size = int(re.search(r"\\fs(\d+)", title_event).group(1))
    assert box_width - _rendered_width("A familiar anime title", size) == 4
