"""Regression tests for shared desktop/web play-history calculations."""

import pytest

from core.game_state import state
from _app_scripts.directory import stats as directory_stats
from _app_scripts.file.metadata import metadata_display, metadata_fetch
from _app_scripts.file.web_server import web_search
from _app_scripts.playlists import entry_paths


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


@pytest.mark.parametrize("series_value", [None, [], ""])
def test_missing_series_counts_the_same_mal_entry(monkeypatch, series_value):
    metadata = {
        "opening.webm": {
            "mal": "1", "slug": "OP1", "title": "Opening Title", "series": series_value,
        },
        "ending.webm": {"mal": 1, "slug": "ED1", "title": "Different Title"},
        "other.webm": {"mal": "2", "slug": "OP1", "title": "Opening Title"},
    }
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda filename: metadata.get(filename, {}))
    monkeypatch.setattr(web_search.information_popup, "get_format", lambda _meta: "TV")
    playlist = ["opening.webm", "ending.webm", "[L]ending.webm", "other.webm", "opening.webm", "ending.webm"]
    history = metadata_display._prepare_play_history(playlist, 4)

    theme_plays, series_plays = metadata_display._calc_plays_info(
        "opening.webm", metadata["opening.webm"], playlist, 4
    )
    web_result = web_search._build_theme_web_result("opening.webm", history)

    assert theme_plays == {"count": 2, "ago": 4, "lightning": 0}
    assert series_plays == {"count": 3, "ago": 3, "lightning": 1}
    assert (web_result["series_plays"], web_result["series_plays_ago"], web_result["series_lightning_plays"]) == (3, 3, 1)


def test_series_plays_are_available_when_only_one_theme_has_played(monkeypatch):
    data = {"mal": "123", "slug": "OP1"}
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda _filename: data)
    playlist = ["opening.webm", "[L]opening.webm", "opening.webm"]

    theme_plays, series_plays = metadata_display._calc_plays_info("opening.webm", data, playlist, 2)

    assert theme_plays == {"count": 2, "ago": 2, "lightning": 1}
    assert series_plays == theme_plays


def test_named_series_still_counts_related_anime_and_same_mal_themes(monkeypatch):
    metadata = {
        "opening.webm": {"mal": "1", "slug": "OP1", "series": ["Shared Series"]},
        "ending.webm": {"mal": "1", "slug": "ED1"},
        "related.webm": {"mal": "2", "slug": "OP1", "series": ["Shared Series"]},
        "other.webm": {"mal": "3", "slug": "OP1", "series": ["Other Series"]},
    }
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda filename: metadata.get(filename, {}))
    playlist = ["related.webm", "ending.webm", "other.webm", "opening.webm"]
    history = metadata_display._prepare_play_history(playlist, 3)

    _, named_series = metadata_display._calc_plays_info(
        "opening.webm", metadata["opening.webm"], (), 3, prepared_history=history
    )
    _, unnamed_series = metadata_display._calc_plays_info(
        "ending.webm", metadata["ending.webm"], (), 3, prepared_history=history
    )

    assert named_series == {"count": 3, "ago": 2, "lightning": 0}
    assert unnamed_series == {"count": 2, "ago": 2, "lightning": 0}


@pytest.fixture
def replacement_metadata(monkeypatch):
    # The old manual file is deliberately absent from metadata, as after deletion.
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "1": {
            "themes": {
                "OP1": {
                    "1": {
                        "byvisp.webm": {"source": "ANISONGDB"},
                        "CowboyBebop-OP1-NCBD1080.webm": {"source": "BD"},
                    },
                    "2": {"CowboyBebop-OP1v2.webm": {"source": "BD"}},
                },
            },
        },
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {
        "1": _metadata("Cowboy Bebop", "Cowboy Bebop"),
    })
    for name in ("anisongdb_metadata", "anidb_metadata", "ai_metadata"):
        monkeypatch.setattr(state.metadata, name, {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal_candidates", {})
    monkeypatch.setattr(metadata_fetch, "_metadata_cache", {})
    monkeypatch.setattr(web_search.information_popup, "get_format", lambda _meta: "TV")
    metadata_fetch.build_filename_to_mal_map()


def test_missing_series_includes_deleted_manual_themes(replacement_metadata):
    state.metadata.anime_metadata["1"].pop("series")
    playlist = [
        "OldTitle-ED1-[MAL]1.webm",
        "[L]OldTitle-IN1-[MAL]1.webm",
        "OldTitle-OP1-[MAL]2.webm",
        "byvisp.webm",
    ]

    theme_plays, series_plays = metadata_display._calc_plays_info(
        "byvisp.webm", metadata_fetch.get_metadata("byvisp.webm"), playlist, 3
    )

    assert theme_plays == {"count": 1, "ago": None, "lightning": 0}
    assert series_plays == {"count": 2, "ago": 3, "lightning": 1}


@pytest.mark.parametrize("old_filename", [
    "OldTitle-OP1-[MAL]1[ART]Seatbelts[SNG]Tank!.webm",
    "OldTitle-op1[MAL]0001.mp4",
    "CowboyBebop-OP1-NCBD1080.webm",
    "CowboyBebop-OP1v2.webm",
])
def test_replacement_keeps_normal_lightning_and_ago_counts(replacement_metadata, old_filename):
    playlist = [old_filename, "unrelated.webm", "[L]" + old_filename, "byvisp.webm", old_filename]
    history = metadata_display._prepare_play_history(playlist, 3)
    data = metadata_fetch.get_metadata("byvisp.webm")

    desktop_file, _ = metadata_display._calc_plays_info("byvisp.webm", data, playlist, 3)
    web_result = web_search._build_theme_web_result("byvisp.webm", history)
    # Theme/version file options call the same counter without merged anime data.
    theme_file, _ = metadata_display._calc_plays_info(
        "CowboyBebop-OP1-NCBD1080.mp4", None, (), 3, prepared_history=history
    )

    assert desktop_file == {"count": 2, "ago": 3, "lightning": 1}
    assert theme_file == desktop_file
    assert (web_result["plays"], web_result["plays_ago"], web_result["lightning_plays"]) == (2, 3, 1)


@pytest.mark.parametrize("other_filename", [
    "CowboyBebop-OP1-[MAL]2.webm",
    "CowboyBebop-ED1-[MAL]1.webm",
    "CowboyBebop-OP2-[MAL]1.webm",
    "CowboyBebop-OP1_EN-[MAL]1.webm",
])
def test_different_anime_or_slug_has_separate_plays(replacement_metadata, other_filename):
    playlist = [other_filename, "[L]" + other_filename, "byvisp.webm"]

    file_plays, _ = metadata_display._calc_plays_info("byvisp.webm", None, playlist, 2)

    assert file_plays == {"count": 1, "ago": None, "lightning": 0}


def test_manual_replacement_also_keeps_anisongdb_history(replacement_metadata):
    manual = "NewTitle-OP1-[MAL]1.webm"
    playlist = ["byvisp.webm", "[L]CowboyBebop-OP1-NCBD1080.webm", manual]

    file_plays, _ = metadata_display._calc_plays_info(manual, None, playlist, 2)

    assert file_plays == {"count": 2, "ago": 2, "lightning": 1}


def test_shared_video_references_keep_distinct_anime_identities(replacement_metadata):
    main_theme = entry_paths.make_theme_reference("shared.webm", "1", "OP1", "1")
    side_story_theme = entry_paths.make_theme_reference("shared.webm", "2", "OP1", "1")
    playlist = [main_theme, "[L]" + side_story_theme, side_story_theme, "byvisp.webm"]

    file_plays, _ = metadata_display._calc_plays_info("byvisp.webm", None, playlist, 3)
    side_story_plays, _ = metadata_display._calc_plays_info(side_story_theme, None, playlist, 3)

    assert file_plays == {"count": 2, "ago": 3, "lightning": 0}
    assert side_story_plays == {"count": 1, "ago": 1, "lightning": 1}


def test_unidentified_files_keep_normalized_filename_matching(replacement_metadata):
    playlist = ["Unknown-OP1-[ID]old.webm", "[L]Unknown-OP1-[ID]new.mp4"]

    file_plays, _ = metadata_display._calc_plays_info("Unknown-OP1.webm", None, playlist, 1)

    assert file_plays == {"count": 1, "ago": 1, "lightning": 1}


def test_most_played_view_counts_replaced_files_together(replacement_metadata, monkeypatch):
    manual = "OldTitle-OP1-[MAL]1.webm"
    playlist = ["other.webm", manual, "[L]" + manual, "byvisp.webm"]
    monkeypatch.setattr(directory_stats.lists, "get_title", lambda _key, value: value)

    entries, name_func = directory_stats._build_playlist_theme_list(playlist, "played")

    assert entries == [manual, "byvisp.webm", "other.webm"]
    assert name_func(None, manual).endswith("(2▶ 1⚡)")
    assert name_func(None, "byvisp.webm").endswith("(2▶ 1⚡)")
    assert name_func(None, "other.webm").endswith("(1▶ 0⚡)")


def test_shared_video_counts_use_the_selected_anime_in_theme_lists(replacement_metadata, monkeypatch):
    filename = "byvisp.webm"
    monkeypatch.setattr(state.metadata, "directory_files", {filename: "themes/" + filename})
    state.metadata.file_metadata["2"] = {
        "themes": {"OP1": {"1": {filename: {"source": "ANISONGDB"}}}},
    }
    state.metadata.anime_metadata["2"] = {"title": "Side Story", "series": []}
    metadata_fetch.build_filename_to_mal_map()
    main = entry_paths.make_theme_reference(filename, "1", "OP1", "1")
    side = entry_paths.make_theme_reference(filename, "2", "OP1", "1")
    playlist = [main, main, "[L]" + side, side]
    monkeypatch.setattr(state.metadata, "playlist", {
        "playlist": playlist, "current_index": 3, "infinite": True,
    })
    monkeypatch.setattr(metadata_display.playlist_marks, "check_favorited", lambda _filename: False)
    monkeypatch.setattr(directory_stats.lists, "get_title", lambda _key, value: value)

    anime = metadata_display._build_web_series_themes(metadata_fetch.get_metadata(side), filename)[0]
    theme = anime["sections"][0]["themes"][0]
    entries, name_func = directory_stats._build_playlist_theme_list(playlist, "played")

    assert theme["files"][0]["filename"] == filename
    assert (theme["plays"], theme["plays_ago"], theme["lightning_plays"]) == (1, None, 1)
    assert entries == [main, side]
    assert name_func(None, main).endswith("(2▶ 0⚡)")
    assert name_func(None, side).endswith("(1▶ 1⚡)")
