from _app_scripts.queue_round.lightning_rounds import mismatch_round


class _Mpv:
    def __init__(self, vid):
        self.vid = vid


class _Player:
    def __init__(self, vid):
        self._p = _Mpv(vid)


def _configure_mismatch(monkeypatch, *, selected_vid):
    monkeypatch.setattr(mismatch_round.state.widgets, "player", _Player(selected_vid))
    monkeypatch.setattr(mismatch_round, "_mismatch_active", True)
    monkeypatch.setattr(mismatch_round, "_mismatch_reveal_pending", True)
    monkeypatch.setattr(mismatch_round, "_mismatch_vid_track_id", 9)


def test_mismatch_cover_stays_up_until_external_track_is_selected(monkeypatch):
    reveals = []
    _configure_mismatch(monkeypatch, selected_vid=3)
    from _app_scripts.playback import blind_screen

    monkeypatch.setattr(
        blind_screen, "set_black_screen", lambda toggle: reveals.append(toggle)
    )

    assert mismatch_round._reveal_mismatch_if_ready() is False
    assert mismatch_round._mismatch_reveal_pending is True
    assert reveals == []


def test_mismatch_cover_lifts_after_external_track_restart(monkeypatch):
    reveals = []
    _configure_mismatch(monkeypatch, selected_vid=9)
    from _app_scripts.playback import blind_screen

    monkeypatch.setattr(
        blind_screen, "set_black_screen", lambda toggle: reveals.append(toggle)
    )

    assert mismatch_round._reveal_mismatch_if_ready() is True
    assert mismatch_round._mismatch_reveal_pending is False
    assert reveals == [False]

    # Duplicate playback-restart events must not uncover twice.
    assert mismatch_round._reveal_mismatch_if_ready() is False
    assert reveals == [False]
