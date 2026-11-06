"""Dates must identify a specific playlist occurrence without new recording."""

from datetime import datetime, timedelta
import json
import threading

import pytest

from core.game_state import state
from _app_scripts.file import last_played
from _app_scripts.file.metadata import metadata_display, metadata_fetch


def _filename(number):
    return f"Theme{number}-OP1-[MAL]{number}.webm"


def _key(number):
    return ("theme", str(number), "OP1")


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(metadata_fetch, "get_file_metadata_by_name", lambda _filename: {})
    anime = {str(i): {"title": f"Anime {i}", "eng_title": f"Anime {i}",
                     "songs": [{"slug": "OP1", "title": f"Song {i}"}]}
             for i in range(1, 31)}
    files = {str(i): {"themes": {"OP1": {"1": {_filename(i): {}}}}} for i in range(1, 31)}
    return last_played.Resolver(tuple(anime.items()), tuple(files.items()), metadata_display._file_play_key)


def _events(numbers, start=datetime(2026, 10, 31, 12)):
    return tuple(last_played.Event(_key(i) if i else None, start + timedelta(minutes=j))
                 for j, i in enumerate(numbers))


def _history(numbers, offset=0):
    return tuple((_key(number), offset + index) for index, number in enumerate(numbers))


def _text(numbers):
    return "\n".join(f"12:{i:02}:00: Anime {number} - Opening 1 (Song {number} by Artist)"
                     for i, number in enumerate(numbers))


def test_resolver_requires_unambiguous_title_and_song(monkeypatch):
    monkeypatch.setattr(metadata_fetch, "get_file_metadata_by_name", lambda _filename: {})
    anime = [("1", {"title": "Original", "eng_title": "Same title", "synonyms": ["Old title"],
                    "songs": [{"slug": "OP1", "title": "First Song"}]}),
             ("2", {"title": "Remake", "eng_title": "Same title",
                    "songs": [{"slug": "OP1", "title": "Second Song"}]})]
    resolve = last_played.Resolver(anime, [], metadata_display._file_play_key).resolve

    assert resolve("Same title - Opening 1 (Second Song by Artist)") == _key(2)
    assert resolve("Same title - Opening 1") is None
    assert resolve("Same title - Opening 1 (Unknown Song by Artist)") is None
    assert resolve("Old title - Opening 1 (First Song by Artist)") == _key(1)
    assert resolve("Original - Opening 1 (Wrong Song by Artist)") is None


@pytest.mark.parametrize("filename,text,expected", [
    ("old.txt", "2026-10-31 23:59:30: Anime 1 - Opening 1 (Song 1 by Artist)", datetime(2026, 10, 31, 23, 59, 30)),
    ("guess_the_anime_2026-10-31_12-00.txt", "12:05:06: Anime 1 - Opening 1 (Song 1 by Artist)", datetime(2026, 10, 31, 12, 5, 6)),
    ("renamed.txt", "OCTOBER 31, 2026\n12:05:06: Anime 1 - Opening 1 (Song 1 by Artist)", datetime(2026, 10, 31, 12, 5, 6)),
])
def test_old_and_new_timestamp_formats(resolver, filename, text, expected):
    events = last_played.parse_text(text, filename, resolver)
    assert events == (last_played.Event(_key(1), expected),)


def test_midnight_rolls_date_once_and_afternoon_backwards_jump_does_not(resolver):
    text = "\n".join([
        "23:59:30: Anime 1 - Opening 1 (Song 1 by Artist)",
        "00:00:15: Anime 2 - Opening 1 (Song 2 by Artist)",
        "17:00:00: Anime 3 - Opening 1 (Song 3 by Artist)",
        "14:00:00: Anime 4 - Opening 1 (Song 4 by Artist)",
    ])
    events = last_played.parse_text(text, "guess_the_anime_2026-10-31_23-00.txt", resolver)
    assert events[1].when == datetime(2026, 11, 1, 0, 0, 15)
    assert events[-1].when == datetime(2026, 11, 1, 14)
    assert events[-2].key is None


def test_conflicting_session_date_does_not_guess(resolver):
    events = last_played.parse_text("NOVEMBER 01, 2026\n" + _text([1]),
                                    "guess_the_anime_2026-10-31_12-00.txt", resolver)
    assert events[0].key == _key(1)
    assert events[0].when is None


def test_parser_excludes_lightning_fixed_and_youtube_but_keeps_unknown_boundaries(resolver):
    text = "\n".join([
        "12:00:00: [LIGHTNING ROUND #1(BLIND)] - Anime 1 - Opening 1 (Song 1 by Artist)",
        "12:01:00: LIGHTNING ROUND #2(REGULAR) - Anime 2 - Opening 1 (Song 2 by Artist)",
        "12:02:00: [SCOREBOARD] Alice +1 PT",
        "12:03:00: [BONUS? MEMBERS] answer",
        "12:04:00: [YOUTUBE VIDEO(url)] - Video",
        "12:05:00: [FIXED LIGHTNING ROUNDS START] Example by Host (2 rounds)",
        "12:06:00: Anime 3 - Opening 1 (Song 3 by Artist)",
        "12:07:00: [LIGHTNING ROUND #1(TRIVIA)] - Anime 4 - Opening 1 (Song 4 by Artist)",
        "12:08:00: Unknown title - Opening 1 (Unknown Song)",
        "12:09:00: Anime 5 - Opening 1 (Song 5 by Artist)",
    ])
    events = last_played.parse_text(text, "guess_the_anime_2026-10-31_12-00.txt", resolver)
    assert [event.key for event in events if event.key] == [_key(5)]
    assert sum(event.key is None for event in events) >= 3


def test_live_session_uses_existing_identity_fields_and_exclusions(resolver):
    fields = last_played._SESSION_FIELDS
    entries = [
        {"type": "theme", "filename": _filename(1), "id": "1", "slug": "OP1", "timestamp": "2026-10-31 12:00:00"},
        {"type": "theme", "filename": _filename(2), "lightning_mode": "regular", "timestamp": "2026-10-31 12:01:00"},
        {"type": "theme", "filename": _filename(3), "fixed_playlist": True, "timestamp": "2026-10-31 12:02:00"},
        {"type": "youtube", "filename": _filename(4), "timestamp": "2026-10-31 12:03:00"},
    ]
    original = json.dumps(entries)
    events = last_played.parse_session(tuple(tuple(entry.get(field) for field in fields) for entry in entries), resolver)
    assert [event.key for event in events if event.key] == [_key(1)]
    assert events[0].when == datetime(2026, 10, 31, 12)
    assert json.dumps(entries) == original


def test_alignment_preserves_actual_indices_and_playlist_segments():
    histories = {"a": tuple((_key(i), j * 2) for j, i in enumerate(range(1, 9))),
                 "b": _history(range(11, 19))}
    events = _events([*range(1, 9), 0, *range(11, 19)])
    dates = last_played.align_dates(histories, [events])
    assert dates["a"][14] == events[7].when
    assert dates["b"][0] == events[9].when
    assert len(dates["a"]) == len(dates["b"]) == 8


@pytest.mark.parametrize("numbers", [[1], [1, 2, 3, 4, 5], [1, 2, 3, 0, 4, 5, 6]])
def test_short_or_unknown_interrupted_sequences_are_not_attributed(numbers):
    assert last_played.align_dates({"a": _history(range(1, 9))}, [_events(numbers)]) == {}


def test_repeated_and_copied_history_does_not_prove_provenance():
    history = _history(range(1, 9))
    assert last_played.align_dates({"a": history, "copy": history}, [_events(range(1, 9))]) == {}
    assert last_played.align_dates({"a": history + _history(range(1, 9), offset=8)}, [_events(range(1, 9))]) == {}
    assert last_played.align_dates({"a": _history([1] * 6)}, [_events([1] * 6)]) == {}


def test_unique_extension_identifies_a_playlist_with_a_shared_prefix():
    histories = {"a": _history(range(1, 11)), "b": _history([1, 2, 3, 4, 5, 6, 20, 21])}
    assert last_played.align_dates(histories, [_events(range(1, 7))]) == {}
    dates = last_played.align_dates(histories, [_events(range(1, 11))])
    assert len(dates["a"]) == 10
    assert "b" not in dates


def test_duplicate_snapshots_are_harmless_but_conflicting_dates_are_hidden():
    histories = {"a": _history(range(1, 9))}
    events = _events(range(1, 9))
    assert len(last_played.align_dates(histories, [events, events])["a"]) == 8
    conflicting = _events(range(1, 9), start=datetime(2026, 11, 1, 12))
    assert not last_played.align_dates(histories, [events, conflicting]).get("a")


def test_standalone_preview_cannot_receive_a_timestamp_from_neighboring_runs():
    histories = {"a": _history(range(1, 17))}
    events = _events([*range(1, 9), 29, *range(9, 17)])
    dates = last_played.align_dates(histories, [events])["a"]
    assert len(dates) == 16
    assert events[8].when not in dates.values()


def test_preview_of_the_next_theme_creates_a_conflict_instead_of_a_false_date():
    histories = {"a": _history(range(1, 17))}
    events = _events([*range(1, 9), *range(8, 17)])
    dates = last_played.align_dates(histories, [events])["a"]
    assert 7 not in dates
    assert dates[8] == events[9].when


def test_info_uses_exact_previous_theme_and_series_occurrences(monkeypatch):
    metadata = {
        "a": {"mal": "1", "slug": "OP1", "series": ["Shared"]},
        "b": {"mal": "2", "slug": "OP1", "series": ["Shared"]},
    }
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda filename: metadata.get(filename, {}))
    monkeypatch.setattr(metadata_fetch, "get_file_metadata_by_name", lambda filename: metadata.get(filename, {}))
    date_a = datetime(2026, 10, 24, 12, 1, 2)
    date_b = datetime(2026, 10, 31, 12, 3, 4)
    queried = []

    def get_dates(indices, *_context):
        queried.append(indices)
        return {0: date_a, 2: date_b, 4: datetime(2026, 11, 4, 12)}

    monkeypatch.setattr(last_played, "get_dates", get_dates)
    theme, series = metadata_display._calc_plays_info("a", metadata["a"], ["a", "x", "b", "[L]b", "a"], 4, include_dates=True)
    assert queried == [{0, 2}]
    assert theme["last_played"] == "2026-10-24T12:01:02"
    assert series["last_played"] == "2026-10-31T12:03:04"
    assert series["last_played_text"] == "Oct 31, 2026 at 12:03:04 PM"


def test_an_older_known_date_cannot_replace_a_newer_undated_play(monkeypatch):
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda filename: {"mal": "1", "slug": "OP1"})
    monkeypatch.setattr(last_played, "get_dates", lambda indices, *_context: {0: datetime(2026, 10, 24, 12)})
    theme, series = metadata_display._calc_plays_info("a", {"mal": "1", "slug": "OP1"}, ["a", "a", "a"], 2, include_dates=True)
    assert theme["ago"] == 1
    assert "last_played" not in theme
    assert "last_played" not in series


def test_cached_lookup_validates_name_generation_and_unchanged_prefix():
    cache = last_played.DateCache(lambda: None)
    request = last_played.Request("a", ("one", "two", "three"), (), 4)
    when = datetime(2026, 10, 31, 12)
    cache._result = (request, {1: when})
    assert cache.lookup("a", request.entries + ("four",), 4, {1}) == {1: when}
    assert cache.lookup("b", request.entries, 4, {1}) == {}
    assert cache.lookup("a", request.entries, 5, {1}) == {}
    assert cache.lookup("a", ("changed", "two", "three"), 4, {1}) == {}


def test_worker_reuses_unchanged_files_and_removes_deleted_sources(resolver, tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    playlists = tmp_path / "playlists"
    sessions.mkdir()
    playlists.mkdir()
    path = sessions / "guess_the_anime_2026-10-31_12-00.txt"
    path.write_text(_text(range(1, 9)), encoding="utf-8")
    cache = last_played.DateCache(lambda: resolver, sessions, playlists)
    request = last_played.Request("a", tuple(_filename(i) for i in range(1, 9)), (), 1)
    parsed = []
    original = last_played.parse_text

    def count_parse(*args):
        parsed.append(1)
        return original(*args)

    monkeypatch.setattr(last_played, "parse_text", count_parse)
    assert len(cache.build(request)) == 8
    original_history = cache._history
    monkeypatch.setattr(cache, "_history", lambda *_args: pytest.fail("unchanged inputs rebuilt history"))
    assert len(cache.build(request)) == 8
    monkeypatch.setattr(cache, "_history", original_history)
    assert parsed == [1]
    path.unlink()
    assert cache.build(request) == {}


def test_changed_logs_and_metadata_invalidate_the_cached_result(resolver, tmp_path, monkeypatch):
    path = tmp_path / "guess_the_anime_2026-10-31_12-00.txt"
    path.write_text(_text(range(1, 9)), encoding="utf-8")
    made = []

    def factory():
        made.append(1)
        return resolver

    cache = last_played.DateCache(factory, tmp_path, tmp_path / "playlists")
    entries = tuple(_filename(i) for i in range(1, 9))
    first = cache.build(last_played.Request("a", entries, (), 1))
    assert first[0] == datetime(2026, 10, 31, 12)
    path.write_text(_text(range(1, 9)).replace("12:", "13:") + "\n", encoding="utf-8")
    second = cache.build(last_played.Request("a", entries, (), 1))
    assert second[0] == datetime(2026, 10, 31, 13)
    assert made == [1]
    cache.build(last_played.Request("a", entries, (), 2))
    assert made == [1, 1]


def test_desktop_and_web_info_share_one_date_enriched_calculation(monkeypatch):
    from _app_scripts.file.metadata import metadata_panel

    class Column:
        parts = None

        def __init__(self):
            self.parts = []

        def insert(self, _index, text, _tag):
            self.parts.append(text)

    column = Column()
    monkeypatch.setattr(state.widgets, "left_column", column)
    monkeypatch.setattr(state.metadata, "playlist", {"name": "a", "infinite": True, "playlist": ["example"], "current_index": 0})
    monkeypatch.setattr(state.playback, "currently_playing", {"type": "theme", "filename": "example", "data": None})
    monkeypatch.setattr(metadata_panel.popout_window, "popout_currently_playing", False)
    monkeypatch.setattr(metadata_display, "reset_metadata", lambda: None)
    monkeypatch.setattr(metadata_display, "toggleColumnEdit", lambda *_args: None)
    monkeypatch.setattr(metadata_panel, "update_extra_metadata", lambda: None)
    monkeypatch.setattr(metadata_display, "_build_web_series_themes", lambda *_args: [])
    monkeypatch.setattr(metadata_panel.playlist_marks, "_push_web_marks", lambda *_args: None)
    monkeypatch.setattr(metadata_panel.web_server, "is_running", lambda: True)
    theme = {"count": 2, "ago": 10, "lightning": 0, "last_played_short": "OCT-31", "last_played_age": "4d ago"}
    series = {"count": 4, "ago": 5, "lightning": 1, "last_played_short": "NOV-1", "last_played_age": "3d ago"}
    calls = []
    published = []

    def calculate(*_args, **kwargs):
        calls.append(kwargs)
        return theme, series

    monkeypatch.setattr(metadata_display, "_calc_plays_info", calculate)
    monkeypatch.setattr(metadata_panel, "_publish_web_metadata", lambda payload, _filename: published.append(payload))
    metadata_panel.update_metadata()
    assert calls == [{"include_dates": True}]
    assert "THEME PLAYS: " in column.parts
    assert "SERIES PLAYS: " in column.parts
    assert "2 (10 Ago / OCT-31 / 4d)" in column.parts
    assert "4 (5 Ago / NOV-1 / 3d) (1 L)" in column.parts
    assert not any("LAST PLAYED" in part for part in column.parts)
    assert published[0]["file_plays"] is theme
    assert published[0]["series_plays"] is series


def test_worker_coalesces_and_does_not_publish_an_obsolete_request(monkeypatch):
    cache = last_played.DateCache(lambda: None)
    entered = threading.Event()
    release = threading.Event()
    first = last_played.Request("old", (), (), 1)
    latest = last_played.Request("current", (), (), 1)

    def build(request):
        if request == first:
            entered.set()
            assert release.wait(3)
        return {0: datetime(2026, 10, 31, 12)}

    monkeypatch.setattr(cache, "build", build)
    cache.request(first)
    try:
        assert entered.wait(3)
        cache.request(latest)
    finally:
        release.set()
    assert cache.idle.wait(3)
    assert cache._result[0] == latest


def test_render_lookup_does_not_read_files_or_launch_work(monkeypatch):
    cache = last_played.DateCache(lambda: None)
    entries = ("one", "two")
    when = datetime(2026, 10, 31, 12)
    cache._result = (last_played.Request("a", entries, (), 0), {0: when})
    monkeypatch.setattr(last_played, "_cache", cache)
    monkeypatch.setattr(state.metadata, "playlist", {"name": "a", "infinite": True, "playlist": list(entries), "current_index": 1})
    monkeypatch.setattr(metadata_fetch, "metadata_cache_generation", 0)
    monkeypatch.setattr(last_played.Path, "read_text", lambda *_a, **_kw: pytest.fail("render read a file"))
    monkeypatch.setattr(last_played.threading, "Thread", lambda *_a, **_kw: pytest.fail("render launched a worker"))
    assert last_played.get_dates({0}) == {0: when}


def test_start_refreshes_current_info_when_dates_arrive_without_duplicate_pollers(monkeypatch):
    class Root:
        def __init__(self):
            self.scheduled = []

        def winfo_exists(self):
            return True

        def after(self, delay, callback):
            self.scheduled.append((delay, callback))

    class Cache:
        def __init__(self):
            self.requests = []
            self.changed = threading.Event()
            self.changed.set()

        def request(self, request):
            self.requests.append(request)

    root, cache = Root(), Cache()
    request = last_played.Request("a", ("one",), (), 0)
    refreshed = []
    monkeypatch.setattr(state.widgets, "root", root)
    monkeypatch.setattr(state.metadata, "playlist", {"current_index": 0})
    monkeypatch.setattr(state.playback, "currently_playing", {"type": "theme", "filename": "one"})
    monkeypatch.setattr(last_played, "_cache", cache)
    monkeypatch.setattr(last_played, "_started", False)
    monkeypatch.setattr(last_played, "_snapshot", lambda: request)
    monkeypatch.setattr(metadata_display, "update_metadata_queue", refreshed.append)
    last_played.start()
    last_played.start()
    assert cache.requests == [request]
    assert refreshed == [0]
    assert len(root.scheduled) == 1
    assert not cache.changed.is_set()


@pytest.mark.parametrize("when,now,expected", [
    (datetime(2026, 8, 26), datetime(2026, 11, 4), "AUG-26"),
    (datetime(2025, 12, 31), datetime(2026, 1, 1), "DEC-31"),
    (datetime(2025, 8, 26, 12), datetime(2026, 8, 26, 11, 59, 59), "AUG-26"),
    (datetime(2025, 8, 26, 12), datetime(2026, 8, 26, 12), "AUG-26-25"),
    (datetime(2006, 8, 8), datetime(2026, 11, 4), "AUG-8-06"),
    (datetime(2024, 2, 29, 12), datetime(2025, 2, 28, 12), "FEB-29-24"),
    (datetime(2027, 1, 1), datetime(2026, 11, 4), "JAN-1-27"),
])
def test_compact_date_omits_year_for_less_than_a_full_year_ago(when, now, expected):
    assert last_played.short_date(when, now) == expected


@pytest.mark.parametrize("when,now,expected", [
    (datetime(2026, 11, 4, 11, 59, 40), datetime(2026, 11, 4, 12), "just now"),
    (datetime(2026, 11, 4, 11, 59), datetime(2026, 11, 4, 12), "1min ago"),
    (datetime(2026, 11, 4, 11, 50), datetime(2026, 11, 4, 12), "10min ago"),
    (datetime(2026, 11, 4, 10), datetime(2026, 11, 4, 12), "2h ago"),
    (datetime(2026, 11, 4, 9, 57), datetime(2026, 11, 4, 12), "2h 3min ago"),
    (datetime(2026, 11, 3, 12), datetime(2026, 11, 4, 12), "1d ago"),
    (datetime(2026, 11, 1, 12), datetime(2026, 11, 4, 12), "3d ago"),
    (datetime(2026, 1, 31, 12), datetime(2026, 2, 28, 12), "1m ago"),
    (datetime(2026, 9, 4, 12), datetime(2026, 11, 4, 12), "2m ago"),
    (datetime(2026, 8, 8, 12), datetime(2026, 10, 11, 12), "2m 3d ago"),
    (datetime(2024, 2, 29, 12), datetime(2025, 2, 28, 12), "1y ago"),
    (datetime(2024, 2, 29, 12), datetime(2025, 3, 1, 12), "1y 1d ago"),
    (datetime(2024, 11, 4, 12), datetime(2026, 11, 4, 12), "2y ago"),
    (datetime(2025, 8, 8, 12), datetime(2026, 10, 11, 12), "1y 2m 3d ago"),
    (datetime(2026, 11, 4, 12, 2), datetime(2026, 11, 4, 12), "in 2min"),
])
def test_relative_age_uses_completed_units_and_handles_month_ends(when, now, expected):
    assert last_played.relative_age(when, now) == expected


def test_inline_format_keeps_unknown_date_fallback_and_lightning_count():
    assert metadata_display._fmt_plays({"count": 10, "ago": 2668, "lightning": 3,
                                       "last_played_short": "AUG-8", "last_played_age": "2m 3d ago"}) == "10 (2668 Ago / AUG-8 / 2m 3d) (3 L)"
    assert metadata_display._fmt_plays({"count": 10, "ago": 2668, "lightning": 3}) == "10 (2668 Ago) (3 L)"
