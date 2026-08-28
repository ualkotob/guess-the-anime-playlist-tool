"""Regression tests for shared desktop/web play-history calculations."""

from _app_scripts.file.metadata import metadata_display, metadata_fetch
from _app_scripts.file.web_server import web_search


def _metadata(title, series):
    return {
        "title": title,
        "eng_title": title,
        "series": [series],
        "songs": [],
        "studios": [],
    }


def test_web_ago_uses_previous_normal_play_not_latest_lightning(monkeypatch):
    metadata = {
        "a.webm": _metadata("Theme A", "Series A"),
        "x.webm": _metadata("Theme X", "Series X"),
        "current.webm": _metadata("Current Theme", "Series Current"),
    }
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda filename: metadata.get(filename, {}))
    monkeypatch.setattr(web_search.information_popup, "get_format", lambda _meta: "TV")

    playlist = ["a.webm", "x.webm", "[L]a.webm", "current.webm"]
    cur_idx = 3
    history = metadata_display._prepare_play_history(playlist, cur_idx)

    desktop_file, _ = metadata_display._calc_plays_info(
        "a.webm", metadata["a.webm"], playlist, cur_idx
    )
    web_result = web_search._build_theme_web_result("a.webm", history)

    assert desktop_file == {"count": 1, "ago": 3, "lightning": 1}
    assert web_result["plays"] == desktop_file["count"]
    assert web_result["plays_ago"] == desktop_file["ago"]
    assert web_result["lightning_plays"] == desktop_file["lightning"]


def test_shared_series_stats_ignore_lightning_as_ago_reference(monkeypatch):
    metadata = {
        "a.webm": _metadata("Theme A", "Shared Series"),
        "b.webm": _metadata("Theme B", "Shared Series"),
        "current.webm": _metadata("Current Theme", "Shared Series"),
    }
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda filename: metadata.get(filename, {}))
    monkeypatch.setattr(web_search.information_popup, "get_format", lambda _meta: "TV")

    playlist = ["a.webm", "[L]b.webm", "current.webm"]
    cur_idx = 2
    history = metadata_display._prepare_play_history(playlist, cur_idx)
    _, desktop_series = metadata_display._calc_plays_info(
        "current.webm", metadata["current.webm"], playlist, cur_idx
    )
    web_result = web_search._build_theme_web_result("current.webm", history)

    assert desktop_series == {"count": 2, "ago": 2, "lightning": 1}
    assert web_result["series_plays"] == desktop_series["count"]
    assert web_result["series_plays_ago"] == desktop_series["ago"]
    assert web_result["series_lightning_plays"] == desktop_series["lightning"]
