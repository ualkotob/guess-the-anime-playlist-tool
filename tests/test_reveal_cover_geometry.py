"""Regression coverage for reveal-cover geometry across a file change.

A queued reveal round draws its cover *before* the next file is loaded so that
no frame of it can leak. mpv keeps answering with the outgoing file's size for
the whole of that window, so the cover must not be laid out from it: a cover
sized for a 16:9 file never uncovers a 4:3 file's left and right edges.
"""

import re

from core.game_state import state
from _app_scripts.playback import blind_screen
from _app_scripts.playback.media_player import MediaPlayer
from _app_scripts.queue_round.lightning_rounds import (
    edge_overlay,
    grow_overlay,
    peek_dispatch,
    peek_overlay,
)


class _FakeMpv:
    """Minimal mpv stand-in: records loads, serves direct property reads."""

    def __init__(self):
        self.commands = []
        self.video_params = None
        self.width = None
        self.height = None

    def play(self, path):
        self.commands.append(("play", path))

    def command(self, *args):
        self.commands.append(args)


def _player(osd_size, display_size=None):
    """A MediaPlayer on a fake mpv, sized `osd_size`, showing `display_size`."""
    player = MediaPlayer.__new__(MediaPlayer)
    player._p = _FakeMpv()
    player._c_time_pos = player._c_duration = None
    player._c_width = player._c_height = None
    player._c_disp_width = player._c_disp_height = None
    player._c_osd_width, player._c_osd_height = osd_size
    if display_size:
        w, h = display_size
        player._on_video_params("video-params", {"dw": w, "dh": h})
    return player


def _edge_cover(monkeypatch, player, block_percent=99):
    """Draw the edge cover and return its (x, y, w, h) in OSD pixels."""
    payloads = []
    monkeypatch.setattr(state.widgets, "player", player)
    monkeypatch.setattr(state.widgets, "root", None)
    monkeypatch.setattr(blind_screen, "_video_frame_active", False)
    monkeypatch.setattr(edge_overlay, "edge_overlay_after_id", None)
    monkeypatch.setattr(edge_overlay, "edge_overlay_box", None)
    monkeypatch.setattr(edge_overlay.osd_text, "osd_command",
                        lambda *args: payloads.append(args))

    edge_overlay.toggle_edge_overlay(block_percent=block_percent)

    payload = next(args[3] for args in payloads if args[2] == "ass-events")
    drawing = payload.split(r"\p1}")[1].split("{")[0]   # just the "m x y l ..." path
    coords = [int(n) for n in re.findall(r"-?\d+", drawing)]
    xs, ys = coords[0::2], coords[1::2]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def test_cover_for_the_incoming_file_is_not_sized_to_the_outgoing_one(monkeypatch):
    # UltraManiac-OP1.webm plays 4:3 in a 16:9 window, so its video rect stops
    # 240px short of each side of the canvas and the cover follows it in.
    player = _player((1920, 1080), display_size=(1440, 1080))
    assert _edge_cover(monkeypatch, player) == (245, 5, 1430, 1070)

    # Queue the next round's reveal: the cover is drawn before the load, while
    # mpv still reports that 4:3 file. Sized to its rect it would leave a 16:9
    # incoming file's left and right strips showing, so the load drops the
    # shape and the unknown aspect expands to the whole canvas. Over-covering
    # is safe — the playback-restart hook shrinks it to the real rect.
    player.set_media("next.mkv")

    assert player.get_display_aspect() == 0.0
    assert _edge_cover(monkeypatch, player) == (5, 5, 1910, 1070)


def test_refresh_video_geometry_seeds_a_file_mpv_never_re_reports():
    # mpv only emits video-params on a *change*, so a file whose size matches
    # the one it replaced would strand the cache empty after the load reset.
    player = _player((1920, 1080), display_size=(1920, 1080))
    player.set_media("same_shape.mkv")
    assert player.get_display_size() == (0, 0)

    player._p.video_params = {"dw": 1920, "dh": 1080}
    assert player.refresh_video_geometry() is True
    assert player.get_display_size() == (1920, 1080)

    # No video-params yet (still muxing the first frame) — the stored size is
    # better than nothing, and is all an unfiltered file needs.
    player.set_media("no_params_yet.mkv")
    player._p.video_params = None
    player._p.width, player._p.height = 1280, 720
    assert player.refresh_video_geometry() is True
    assert player.get_display_size() == (1280, 720)


def test_slice_draw_records_its_parameters_for_a_later_relayout(monkeypatch):
    monkeypatch.setattr(state.widgets, "player", _player((1920, 1080), (1920, 1080)))
    monkeypatch.setattr(blind_screen, "_video_frame_active", False)
    monkeypatch.setattr(peek_overlay, "peek_overlay1", None)
    monkeypatch.setattr(peek_overlay, "peek_overlay2", None)
    monkeypatch.setattr(peek_overlay, "last_peek_params",
                        {"direction": "right", "progress": 0, "gap": 1})
    monkeypatch.setattr(peek_overlay.osd_text, "osd_command", lambda *args: None)
    monkeypatch.setattr(peek_dispatch, "gap_modifier", 0)

    peek_overlay.toggle_peek_overlay(direction="down", progress=35, gap=2.2)

    assert peek_overlay.last_peek_params == {
        "direction": "down", "progress": 35, "gap": 2.2,
    }


def test_relayout_replays_the_rounds_current_position(monkeypatch):
    block_percents = []
    monkeypatch.setattr(peek_overlay, "peek_overlay1", None)
    monkeypatch.setattr(edge_overlay, "edge_overlay_box", True)
    monkeypatch.setattr(edge_overlay, "last_edge_block_percent", 72.5)
    monkeypatch.setattr(grow_overlay, "grow_overlay_boxes", {})
    monkeypatch.setattr(edge_overlay, "toggle_edge_overlay",
                        lambda block_percent: block_percents.append(block_percent))

    peek_dispatch.redraw_active_reveal()

    # Not 99: re-laying out on the new file must not rewind a reveal that is
    # already part-way open (a seek re-fires the same hook mid-round).
    assert block_percents == [72.5]


def test_relayout_keeps_the_slice_direction_and_gap(monkeypatch):
    draws = []
    monkeypatch.setattr(peek_overlay, "peek_overlay1", True)
    monkeypatch.setattr(peek_overlay, "last_peek_params",
                        {"direction": "down", "progress": 40.0, "gap": 3.4})
    monkeypatch.setattr(peek_overlay, "toggle_peek_overlay",
                        lambda **kwargs: draws.append(kwargs))

    peek_dispatch.redraw_active_reveal()

    assert draws == [{"direction": "down", "progress": 40.0, "gap": 3.4}]


def test_relayout_covers_grow(monkeypatch):
    draws = []
    monkeypatch.setattr(peek_overlay, "peek_overlay1", None)
    monkeypatch.setattr(edge_overlay, "edge_overlay_box", None)
    monkeypatch.setattr(grow_overlay, "grow_overlay_boxes", {"active": True})
    monkeypatch.setattr(grow_overlay, "last_grow_block_percent", 88.0)
    monkeypatch.setattr(grow_overlay, "grow_position", (640, 360))
    monkeypatch.setattr(grow_overlay, "toggle_grow_overlay",
                        lambda **kwargs: draws.append(kwargs))

    peek_dispatch.redraw_active_reveal()

    assert draws == [{"block_percent": 88.0, "position": (640, 360)}]
