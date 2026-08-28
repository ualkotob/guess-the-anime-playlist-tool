from _app_scripts.file import session_end


class _Root:
    def winfo_rgb(self, _color):
        return 0, 0, 0


class _Player:
    def __init__(self):
        self._p = type("Mpv", (), {"osd_width": 1920, "osd_height": 1080})()


class _Font:
    def getlength(self, text):
        return len(text) * 10

    def getmask(self, text, mode=""):
        del mode
        from PIL import ImageFont
        return ImageFont.load_default().getmask(text)


def test_end_screen_uses_regular_font_on_every_machine(monkeypatch):
    narrow_requests = []

    def get_font(_size, *, bold, narrow):
        del bold
        narrow_requests.append(narrow)
        return _Font()

    monkeypatch.setattr(session_end.state.widgets, "root", _Root())
    monkeypatch.setattr(session_end.state.widgets, "player", _Player())
    monkeypatch.setattr(session_end.osd_text, "_get_ass_font", get_font)
    monkeypatch.setattr(
        session_end.session_stats,
        "get_session_summary_counts",
        lambda: {
            "themes_played": 0,
            "opening_count": 0,
            "ending_count": 0,
            "lightning_count": 0,
            "fixed_playlist_count": 0,
            "youtube_count": 0,
        },
    )
    monkeypatch.setattr(session_end.session_stats, "session_start_time", "invalid")
    monkeypatch.setattr(session_end.session_stats, "session_data", [])
    monkeypatch.setattr(
        session_end.session_stats,
        "get_top_series_from_session",
        lambda _data: (None, 0),
    )
    monkeypatch.setattr(
        session_end.session_stats,
        "get_top_artists_from_session",
        lambda _data: ([], 0),
    )
    monkeypatch.setattr(session_end.state.config, "end_session_txt", "THANKS")
    monkeypatch.setattr(session_end.state.config, "inverted_positions", False)
    monkeypatch.setattr(session_end.state.colors, "OVERLAY_BACKGROUND_COLOR", "black")
    monkeypatch.setattr(session_end.state.colors, "OVERLAY_TEXT_COLOR", "white")

    assert session_end._end_msg_build_canvas(0) is not None
    assert narrow_requests
    assert not any(narrow_requests)
