"""Theme rendering and web publication must not wait for catalog counts."""

import pytest
from types import SimpleNamespace

from core.game_state import state
from _app_scripts.file.metadata import metadata_panel, metadata_display
from _app_scripts.search import search


@pytest.fixture
def web_updates(monkeypatch):
    pushed, workers = [], []
    monkeypatch.setattr(metadata_panel, "_web_metadata_token", 0)
    monkeypatch.setattr(state.playback, "currently_playing", {
        "filename": "song.webm", "playlist_entry": "song.webm", "data": {},
    })
    monkeypatch.setattr(metadata_panel.web_server, "push_metadata", pushed.append)
    monkeypatch.setattr(metadata_panel.web_server, "is_running", lambda: True)
    monkeypatch.setattr(metadata_panel.threading, "Thread", lambda *, target, **kwargs:
                        SimpleNamespace(start=lambda: workers.append(target)))
    monkeypatch.setattr(search, "get_catalog_matches", lambda field, name, *, wait:
                        ["song.webm"] if wait else None)
    monkeypatch.setattr(metadata_panel.information_popup, "get_artist_themes_data",
                        lambda name, filename, **kwargs: {"theme_count": 1, "themes": kwargs["filenames"]})
    monkeypatch.setattr(metadata_panel.information_popup, "get_studio_entries_data",
                        lambda name, filename, **kwargs: {"entry_count": 1, "entries": kwargs["filenames"]})
    metadata = {"filename": "song.webm", "studios": ["Studio"],
                "current_theme": {"artists": ["Artist"], "slug": "OP1"},
                "series_themes": [{"anime_id": "1", "sections": ["OPENINGS"]}]}
    return metadata, pushed, workers


def test_web_info_publishes_theme_list_before_artist_and_studio_counts(web_updates):
    metadata, pushed, workers = web_updates
    metadata_panel._publish_web_metadata(metadata, "song.webm")
    assert pushed == [metadata]
    assert "artist_themes" not in pushed[0]["current_theme"]
    assert len(workers) == 1
    workers.pop()()
    assert len(pushed) == 2
    assert pushed[1]["series_themes"] == metadata["series_themes"]
    assert pushed[1]["current_theme"]["artist_themes"]["Artist"]["theme_count"] == 1
    assert pushed[1]["current_theme"]["studio_entry_total"] == 1
    assert "artist_themes" not in metadata["current_theme"]


@pytest.mark.parametrize("change", ["track", "refresh", "stop_server"])
def test_late_web_counts_cannot_overwrite_a_newer_display(web_updates, monkeypatch, change):
    metadata, pushed, workers = web_updates
    metadata_panel._publish_web_metadata(metadata, "song.webm")
    old_worker = workers.pop()
    if change == "track":
        state.playback.currently_playing = {"filename": "other.webm", "data": {}}
    elif change == "refresh":
        metadata_panel._publish_web_metadata({**metadata, "title": "New title"}, "song.webm")
    else:
        monkeypatch.setattr(metadata_panel.web_server, "is_running", lambda: False)
    count = len(pushed)
    old_worker()
    assert len(pushed) == count


def test_series_membership_is_reused_only_within_one_render(monkeypatch):
    scans = []
    class AnimeMetadata(dict):
        def items(self):
            scans.append(True)
            return super().items()
    monkeypatch.setattr(state.metadata, "anime_metadata", AnimeMetadata({
        "1": {"title": "One", "series": ["Series"], "season": "Spring 2000"},
        "2": {"title": "Two", "series": ["Series"], "season": "Spring 2001"},
    }))
    monkeypatch.setattr(metadata_display.source_preferences, "availability_snapshot",
                        metadata_display.contextmanager(lambda: iter([None])))
    data = {"series": ["Series"]}
    with metadata_display.theme_render_snapshot():
        assert len(metadata_display.get_all_theme_from_series(data)) == 2
        assert len(metadata_display.get_all_theme_from_series({**data, "slug": "ED1"})) == 2
    assert len(scans) == 1
    state.metadata.anime_metadata["3"] = {"title": "Three", "series": ["Series"]}
    with metadata_display.theme_render_snapshot():
        assert len(metadata_display.get_all_theme_from_series(data)) == 3
    assert len(scans) == 2
