"""Queued reveal filters must survive async loads and end with their round."""

import pytest

from core.game_state import state
from _app_scripts.playback.media_player import MediaPlayer, _STARTUP_COVER_FILTER
from _app_scripts.queue_round.lightning_rounds import filter_overlay


class _Mpv:
    """Defer load options, including mpv's restoration of per-file settings."""

    brightness = 0
    contrast = 0
    hwdec_current = "no"

    def __init__(self):
        self.vf = ""
        self.pending_options = ""
        self.saved_vf = None
        self.reject_next_filter = False
        self.loads = []

    def observe_property(self, *_args):
        pass

    def command(self, *args):
        if args[:2] == ("vf", "set"):
            if self.reject_next_filter:
                self.reject_next_filter = False
                raise RuntimeError("video chain is not ready")
            self.vf = args[2]

    def command_async(self, *args):
        if args[0] == "loadfile":
            self.loads.append(args)
            self.pending_options = args[4]
        elif args[:2] == ("vf", "add"):
            # mpv replaces an existing filter when its label matches.
            self.vf = self.vf.replace(_STARTUP_COVER_FILTER, "").strip(",")
            self.vf = ",".join(part for part in (self.vf, args[2]) if part)
        elif args[:2] == ("vf", "remove"):
            self.vf = self.vf.replace(_STARTUP_COVER_FILTER, "").strip(",")
        elif args[:2] == ("set", "brightness"):
            self.brightness = float(args[2])
        elif args[:2] == ("set", "contrast"):
            self.contrast = float(args[2])

    def finish_load(self):
        if self.saved_vf is not None:
            self.vf, self.saved_vf = self.saved_vf, None
        options = dict(
            option.split("=", 1)
            for option in self.pending_options.split(",") if option
        )
        if "vf" in options:
            self.saved_vf = self.vf
            self.vf = options["vf"]
        for name in ("brightness", "contrast"):
            if name in options:
                setattr(self, name, float(options[name]))


@pytest.fixture
def player(monkeypatch):
    player = MediaPlayer(_Mpv())
    monkeypatch.setattr(state.widgets, "player", player)
    monkeypatch.setattr(filter_overlay, "filter_vf_active", True)
    monkeypatch.setattr(filter_overlay, "_filter_vf_variant", None)
    monkeypatch.setattr(filter_overlay, "_filter_vf_last", None)
    monkeypatch.setattr(filter_overlay, "_filter_vf_last_progress", [0.0])
    monkeypatch.setattr(filter_overlay, "_filter_zoom_offset", [0.0, 0.0])
    monkeypatch.setattr(filter_overlay.osd_text, "bottom_info", lambda *_a, **_kw: None)
    return player


@pytest.mark.parametrize("variant", ["blur", "pixelize", "outline", "wave", "zoom"])
@pytest.mark.parametrize("activate_before_load_finishes", [True, False])
def test_queued_filter_stays_on_its_theme(player, variant, activate_before_load_finishes):
    player.set_media("reveal.webm", cover_video=True)
    if not activate_before_load_finishes:
        player._p.finish_load()

    filter_overlay._filter_vf_variant = variant
    filter_overlay.toggle_filter_vf(variant, 0)
    if activate_before_load_finishes:
        player._p.finish_load()

    # The playback-restart callback requests the same filter again. Its cache
    # must agree with the player even if load options were applied in between.
    filter_overlay.toggle_filter_vf(variant, 0)
    player.release_startup_video_cover()
    applied_filter = player._p.vf
    assert applied_filter
    assert _STARTUP_COVER_FILTER not in applied_filter

    filter_overlay.toggle_filter_vf(destroy=True)
    assert not filter_overlay.filter_vf_active
    assert player._p.vf == ""

    player.set_media("normal.webm")
    player._p.finish_load()
    assert player._p.vf == ""


@pytest.mark.parametrize("cover_video", [True, False])
def test_next_round_does_not_restore_the_previous_filter(player, cover_video):
    player.set_media("pixelize.webm", cover_video=True)
    filter_overlay.toggle_filter_vf("pixelize", 0)
    player._p.finish_load()
    player.release_startup_video_cover()
    filter_overlay.toggle_filter_vf(destroy=True)

    player.set_media("next.webm", cover_video=cover_video)
    if cover_video:
        filter_overlay.toggle_filter_vf("zoom", 0.5)
    player._p.finish_load()
    player.release_startup_video_cover()

    assert "scale=iw/80" not in player._p.vf
    assert ("crop=" in player._p.vf) == cover_video


@pytest.mark.parametrize("action", ["destroy", "fully_reveal"])
def test_filter_cleanup_keeps_the_startup_cover_until_release(player, action):
    player.set_media("reveal.webm", cover_video=True)
    player._p.finish_load()
    filter_overlay.toggle_filter_vf("pixelize", 0)
    if action == "destroy":
        filter_overlay.toggle_filter_vf(destroy=True)
    else:
        filter_overlay.toggle_filter_vf("pixelize", 1)

    assert player._p.vf == _STARTUP_COVER_FILTER
    player.release_startup_video_cover()
    assert player._p.vf == ""
    assert player._p.brightness == player._p.contrast == 0


def test_blind_load_preserves_an_armed_reveal_and_releases_only_its_cover(player):
    filter_overlay.toggle_filter_vf("pixelize", 0.25)
    armed_filter = player._p.vf
    player.set_media("blind.webm", cover_video=True)
    player._p.finish_load()
    assert player._p.vf == f"{armed_filter},{_STARTUP_COVER_FILTER}"
    player.release_startup_video_cover()
    assert player._p.vf == armed_filter


def test_failed_filter_submission_is_retried_at_the_same_progress(player):
    player._p.reject_next_filter = True
    filter_overlay.toggle_filter_vf("pixelize", 0)
    assert player._p.vf == ""

    filter_overlay.toggle_filter_vf("pixelize", 0)
    assert "scale=iw/80" in player._p.vf
