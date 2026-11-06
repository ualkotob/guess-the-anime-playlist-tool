import copy

import pytest

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


@pytest.mark.parametrize("first_plays", [None, 0, 1, 23])
def test_end_screen_uses_regular_font_on_every_machine(monkeypatch, first_plays):
    narrow_requests = []
    rendered_text = []

    original_text = session_end.ImageDraw.ImageDraw.text

    def draw_text(draw, xy, text, *args, **kwargs):
        rendered_text.append(text)
        return original_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(session_end.ImageDraw.ImageDraw, "text", draw_text)
    monkeypatch.setattr(session_end, "_get_first_time_plays", lambda: first_plays)

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
    first_play_lines = [text for text in rendered_text if "FIRST-TIME" in text]
    if first_plays is None:
        assert first_play_lines == []
    else:
        suffix = "S" if first_plays != 1 else ""
        assert first_play_lines == [f"{first_plays} FIRST-TIME PLAY{suffix}"]


def _theme(filename, **extra):
    return {"type": "theme", "filename": filename, **extra}


@pytest.fixture
def first_play_history(monkeypatch):
    playlist = {
        "infinite": True,
        "name": "Saved infinite playlist",
        "infinite_settings": {},
        "playlist": [],
        "current_index": -1,
    }
    monkeypatch.setattr(session_end.state.metadata, "playlist", playlist)
    monkeypatch.setattr(session_end.session_stats, "session_data", [])
    monkeypatch.setattr(session_end, "_FIRST_TIME_PLAYS_MIN_HISTORY", 3)
    monkeypatch.setattr(
        session_end.metadata_display.metadata_fetch,
        "get_file_metadata_by_name",
        lambda _filename: {},
    )
    return playlist


@pytest.mark.parametrize(("history", "session", "expected"), [
    (["old.webm", "older.webm", "new.webm"], [_theme("new.webm")], 1),
    (["old.webm", "new.webm", "new.webm"], [_theme("new.webm"), _theme("new.webm")], 1),
    (["old.webm", "new.webm", "old.webm"], [_theme("new.webm"), _theme("old.webm")], 1),
    (["old.webm", "other.webm", "old.webm"], [_theme("old.webm")], 0),
    (["old.webm", "other.webm", "new.webm"], [_theme("outside.webm")], None),
    (["old.webm", "other.webm", "new.webm"], [_theme("new.webm", lightning_mode="blind")], None),
    (["old.webm", "other.webm", "new.webm"], [_theme("new.webm", fixed_playlist=True)], None),
    (["old.webm", "other.webm", "new.webm"], [_theme("new.webm", type="youtube")], None),
    (["old.webm", "other.webm", "new.webm"], [], None),
    (["old.webm", "other.webm", "[L]new.webm", "new.webm"], [_theme("new.webm")], 1),
    (["old.webm", "other.webm", "[L]new.webm"], [_theme("new.webm")], None),
    (["old.webm", "other.webm", "new.webm"], [
        _theme("new.webm", lightning_mode="blind"), _theme("new.webm"),
    ], 1),
    (["old.webm", "other.webm", "new.webm"], [
        _theme("new.webm"), {"type": "scoreboard_score", "player": "Alice"},
        {"type": "fixed_rounds_start"},
    ], 1),
])
def test_first_play_count_uses_only_existing_regular_history(
    monkeypatch, first_play_history, history, session, expected
):
    first_play_history.update(playlist=history, current_index=len(history) - 1)
    monkeypatch.setattr(session_end.session_stats, "session_data", session)
    before_playlist = copy.deepcopy(first_play_history)
    before_session = copy.deepcopy(session)

    assert session_end._get_first_time_plays() == expected
    assert first_play_history == before_playlist
    assert session == before_session


@pytest.mark.parametrize("change", [
    {"infinite": False},
    {"name": ""},
    {"infinite_settings": {"show_first_time_plays_on_end_card": False}},
    {"current_index": -1},
    {"current_index": 1},
])
def test_first_play_count_respects_toggle_and_playlist_eligibility(
    monkeypatch, first_play_history, change
):
    first_play_history.update(playlist=["old.webm", "older.webm", "new.webm"], current_index=2)
    first_play_history.update(change)
    monkeypatch.setattr(session_end.session_stats, "session_data", [_theme("new.webm")])

    assert session_end._get_first_time_plays() is None


def test_unplayed_queue_and_speculative_tail_do_not_count(monkeypatch, first_play_history):
    first_play_history.update(
        playlist=["old.webm", "older.webm", "new.webm", "new.webm", "outside.webm"],
        current_index=2,
        speculative_tail=["new.webm", "another.webm"],
    )
    monkeypatch.setattr(session_end.session_stats, "session_data", [
        _theme("new.webm"), _theme("outside.webm"),
    ])

    assert session_end._get_first_time_plays() == 1


@pytest.mark.parametrize("prior_regular", [998, 999])
def test_default_history_threshold_ignores_lightning_entries(
    monkeypatch, first_play_history, prior_regular
):
    monkeypatch.setattr(session_end, "_FIRST_TIME_PLAYS_MIN_HISTORY", 1000)
    history = ["old.webm"] * prior_regular + ["[L]lightning.webm"] * 50 + ["new.webm"]
    first_play_history.update(playlist=history, current_index=len(history) - 1)
    monkeypatch.setattr(session_end.session_stats, "session_data", [_theme("new.webm")])

    assert session_end._get_first_time_plays() == (1 if prior_regular == 999 else None)


@pytest.mark.parametrize("previous_normal", [False, True])
def test_first_play_matching_agrees_with_tracker_across_sources_and_versions(
    monkeypatch, first_play_history, previous_normal
):
    metadata = {
        "source-a.webm": {"mal": 123, "slug": "OP1"},
        "source-b.mp4": {"mal": "123", "slug": "OP1"},
    }
    monkeypatch.setattr(
        session_end.metadata_display.metadata_fetch,
        "get_file_metadata_by_name",
        lambda filename: metadata.get(filename, {}),
    )
    history = ["old.webm", "older.webm"]
    if previous_normal:
        history.append("[THEME_REF]123|OP1|1::source-a.webm")
    history.append("[THEME_REF]123|OP1|2::source-b.mp4")
    first_play_history.update(playlist=history, current_index=len(history) - 1)
    monkeypatch.setattr(session_end.session_stats, "session_data", [
        _theme("source-b.mp4", id="123", slug="OP1"),
    ])

    assert session_end._get_first_time_plays() == (0 if previous_normal else 1)


def test_older_session_entry_can_use_current_file_metadata(monkeypatch, first_play_history):
    monkeypatch.setattr(
        session_end.metadata_display.metadata_fetch,
        "get_file_metadata_by_name",
        lambda filename: {"mal": 123, "slug": "OP1"} if filename == "new.webm" else {},
    )
    first_play_history.update(playlist=["old.webm", "older.webm", "new.webm"], current_index=2)
    monkeypatch.setattr(session_end.session_stats, "session_data", [_theme("new.webm")])

    assert session_end._get_first_time_plays() == 1
