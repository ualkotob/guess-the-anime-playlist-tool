"""Tests for saved playlist filter application helpers."""

import copy
import json

import pytest

from core.game_state import state
import _app_scripts.playlists.filters as filters


@pytest.fixture
def clean_playlist():
    saved = copy.deepcopy(state.metadata.playlist)
    yield state.metadata.playlist
    state.metadata.playlist.clear()
    state.metadata.playlist.update(saved)


def test_apply_saved_filter_filters_standard_playlist(monkeypatch, clean_playlist):
    clean_playlist.clear()
    clean_playlist.update({"playlist": ["a.webm"], "infinite": False})
    calls = []

    monkeypatch.setattr(
        filters,
        "get_all_filters",
        lambda: {0: {"name": "High Score", "filter": {"score_min": 8.5}}},
    )
    monkeypatch.setattr(
        filters,
        "filter_playlist",
        lambda f, notify=True: calls.append((f, notify)) or ["a.webm"],
    )

    assert filters.apply_saved_filter("High Score", notify=False) is True
    assert calls == [({"score_min": 8.5}, False)]


def test_apply_saved_filter_updates_infinite_playlist(monkeypatch, clean_playlist):
    clean_playlist.clear()
    clean_playlist.update({"playlist": [], "infinite": True, "filter": {}})
    saved_filter = {"keywords": "mecha"}
    calls = []

    monkeypatch.setattr(
        filters,
        "get_all_filters",
        lambda: {0: {"name": "Robots", "filter": saved_filter}},
    )
    monkeypatch.setattr(filters.infinite, "refresh_pop_time_groups", lambda: calls.append("refresh"))
    monkeypatch.setattr(filters.config_io, "save_config", lambda: calls.append("save"))

    assert filters.apply_saved_filter("Robots") is True
    assert clean_playlist["filter"] == saved_filter
    assert clean_playlist["filter"] is not saved_filter
    assert calls == ["refresh", "save"]


def test_apply_saved_filter_returns_false_for_missing_filter(monkeypatch, clean_playlist):
    clean_playlist.clear()
    clean_playlist.update({"playlist": ["a.webm"], "infinite": False})
    monkeypatch.setattr(filters, "get_all_filters", lambda: {})

    assert filters.apply_saved_filter("Missing") is False

def test_ensure_default_infinite_filter_saved_creates_missing_filter(monkeypatch, tmp_path):
    monkeypatch.setattr(filters, "FILTERS_FOLDER", str(tmp_path))

    assert filters.ensure_default_infinite_filter_saved() is True

    filter_path = tmp_path / f"{filters.DEFAULT_INFINITE_FILTER_NAME}.json"
    data = json.loads(filter_path.read_text())
    assert data == {
        "name": filters.DEFAULT_INFINITE_FILTER_NAME,
        "filter": filters.DEFAULT_INFINITE_FILTER,
    }


def test_ensure_default_infinite_filter_saved_keeps_existing_filter(monkeypatch, tmp_path):
    monkeypatch.setattr(filters, "FILTERS_FOLDER", str(tmp_path))
    existing = {
        "name": filters.DEFAULT_INFINITE_FILTER_NAME,
        "filter": {"keywords": "custom"},
    }
    filter_path = tmp_path / f"{filters.DEFAULT_INFINITE_FILTER_NAME}.json"
    filter_path.write_text(json.dumps(existing))

    assert filters.ensure_default_infinite_filter_saved() is False
    assert json.loads(filter_path.read_text()) == existing


def test_ensure_default_infinite_filter_saved_upgrades_untouched_old_default(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(filters, "FILTERS_FOLDER", str(tmp_path))
    old_default = copy.deepcopy(filters.DEFAULT_INFINITE_FILTER)
    old_default["themes_exclude"].remove(filters.ANISONGDB_RISK_WITHOUT_CENSORS)
    filter_path = tmp_path / f"{filters.DEFAULT_INFINITE_FILTER_NAME}.json"
    filter_path.write_text(
        json.dumps({"name": filters.DEFAULT_INFINITE_FILTER_NAME, "filter": old_default})
    )

    assert filters.ensure_default_infinite_filter_saved() is True
    assert json.loads(filter_path.read_text())["filter"] == filters.DEFAULT_INFINITE_FILTER


def test_upgrade_default_infinite_filter_preserves_custom_filters():
    custom = {"themes_exclude": ["NSFW (Without Censors)"]}

    assert filters.upgrade_default_infinite_filter(custom) is False
    assert custom == {"themes_exclude": ["NSFW (Without Censors)"]}


def test_upgrade_default_infinite_filter_migrates_long_anisongdb_name():
    old_default = copy.deepcopy(filters.DEFAULT_INFINITE_FILTER)
    index = old_default["themes_exclude"].index(
        filters.ANISONGDB_RISK_WITHOUT_CENSORS
    )
    old_default["themes_exclude"][index] = (
        "ANISONGDB ECCHI/NUDITY (Without Censors)"
    )

    assert filters.upgrade_default_infinite_filter(old_default) is True
    assert old_default == filters.DEFAULT_INFINITE_FILTER


def test_normalize_filter_migrates_long_anisongdb_risk_names():
    assert filters.normalize_filter(
        {
            "themes_exclude": [
                "ANISONGDB ECCHI/NUDITY (Without Censors)",
            ]
        }
    ) == {"themes_exclude": [filters.ANISONGDB_RISK_WITHOUT_CENSORS]}


def test_normalize_filter_canonicalizes_browser_values():
    normalized = filters.normalize_filter(
        {
            "theme_type": "Both",
            "score_min": "7.25",
            "rank_max": "10",
            "rank_min": 500,
            "artists": [" Artist ", "Artist", ""],
        },
        strict=True,
    )

    assert normalized == {
        "score_min": 7.2,
        "rank_max": 10,
        "rank_min": 500,
        "artists": ["Artist"],
    }


@pytest.mark.parametrize("default_value", [None, "", "Both", "Opening + Ending"])
def test_normalize_filter_omits_default_theme_type(default_value):
    assert filters.normalize_filter({"theme_type": default_value}, strict=True) == {}


@pytest.mark.parametrize("theme_type", ["Opening", "Ending", "Insert", "All"])
def test_normalize_filter_accepts_theme_types(theme_type):
    assert filters.normalize_filter({"theme_type": theme_type}, strict=True) == {
        "theme_type": theme_type,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"unknown": True},
        {"score_min": 11},
        {"rank_max": 500, "rank_min": 10},
        {"season_min": "2024 Spring"},
        {"themes_exclude": ["NOT A REAL RULE"]},
    ],
)
def test_normalize_filter_rejects_invalid_browser_values(payload):
    with pytest.raises(filters.FilterValidationError):
        filters.normalize_filter(payload, strict=True)


def test_evaluate_filter_does_not_mutate_live_playlist(monkeypatch, clean_playlist):
    clean_playlist.clear()
    clean_playlist.update({"playlist": ["a.webm", "b.webm"], "current_index": 1, "infinite": False})
    metadata = {
        "a.webm": {"score": 9, "title": "A", "slug": "OP1"},
        "b.webm": {"score": 5, "title": "B", "slug": "OP1"},
    }
    monkeypatch.setattr(filters.metadata_fetch, "get_metadata", metadata.get)

    assert filters.evaluate_filter({"score_min": 8}) == ["a.webm"]
    assert clean_playlist["playlist"] == ["a.webm", "b.webm"]
    assert clean_playlist["current_index"] == 1


def test_evaluate_filter_excludes_inserts_by_default_and_can_include_them(monkeypatch):
    filenames = ["opening.webm", "ending.webm", "insert.webm", "other.webm"]
    metadata = {
        "opening.webm": {"slug": "OP1"},
        "ending.webm": {"slug": "ED2"},
        "insert.webm": {"slug": "IN3"},
        "other.webm": {"slug": "PV1"},
    }
    monkeypatch.setattr(filters.metadata_fetch, "get_metadata", metadata.get)

    assert filters.evaluate_filter({}, filenames) == ["opening.webm", "ending.webm"]
    assert filters.evaluate_filter({"theme_type": "Insert"}, filenames) == ["insert.webm"]
    assert filters.evaluate_filter({"theme_type": "All"}, filenames) == filenames


def test_anisongdb_ecchi_nudity_filter_distinguishes_censor_coverage(monkeypatch):
    filenames = [
        "uncensored.webm",
        "censored.webm",
        "hentai.webm",
        "future-hentai-tag.webm",
        "gore.webm",
        "animethemes.webm",
    ]
    base = {
        "slug": "OP1",
        "songs": [{"slug": "OP1"}],
        "anisongdb_genres": ["Ecchi"],
        "anisongdb_tags": ["Nudity"],
        "file_properties": {"source": "ANISONGDB"},
    }
    metadata = {
        "uncensored.webm": copy.deepcopy(base),
        "censored.webm": copy.deepcopy(base),
        "hentai.webm": {
            **copy.deepcopy(base),
            "anisongdb_genres": [],
            "anisongdb_tags": [],
            "genres": ["Hentai"],
        },
        "future-hentai-tag.webm": {
            **copy.deepcopy(base),
            "anisongdb_genres": [],
            "anisongdb_tags": ["Hentai"],
        },
        "gore.webm": {
            **copy.deepcopy(base),
            "anisongdb_genres": [],
            "anisongdb_tags": ["Gore"],
        },
        "animethemes.webm": {
            **copy.deepcopy(base),
            "file_properties": {"source": "BD"},
        },
    }
    monkeypatch.setattr(filters.metadata_fetch, "get_metadata", metadata.get)
    monkeypatch.setattr(
        filters.censors,
        "get_file_censors",
        lambda filename: [{"nsfw": True}] if filename == "censored.webm" else [],
    )

    assert filters.evaluate_filter(
        {"themes_exclude": [filters.ANISONGDB_RISK_WITHOUT_CENSORS]}, filenames
    ) == ["censored.webm", "gore.webm", "animethemes.webm"]
    assert filters.evaluate_filter(
        {"themes_exclude": [filters.ANISONGDB_RISK_WITH_CENSORS]}, filenames
    ) == [
        "uncensored.webm",
        "hentai.webm",
        "future-hentai-tag.webm",
        "gore.webm",
        "animethemes.webm",
    ]


@pytest.mark.parametrize("censored", [False, True])
@pytest.mark.parametrize("theme_nsfw", [False, True])
def test_matched_anisongdb_uses_nsfw_from_any_animethemes_version(monkeypatch, censored, theme_nsfw):
    first = "Anime-OP1v1.webm"
    second = "Anime-OP1v2.webm"
    matched = "matched.webm"
    unmatched = "unmatched.webm"
    filenames = [first, second, matched, unmatched]
    theme = {
        "slug": "OP1", "nsfw": theme_nsfw,
        "versions": [{"version": 1, "nsfw": False}, {"version": 2, "nsfw": True}],
    }
    base = {"slug": "OP1", "songs": [theme], "file_properties": {"source": "BD"}}
    metadata = {
        first: copy.deepcopy(base), second: copy.deepcopy(base),
        matched: {**copy.deepcopy(base), "file_properties": {"source": "ANISONGDB", "anisongdb_alternate": True}},
        unmatched: {
            "slug": "OP2", "songs": [theme, {"slug": "OP2", "anisongdb_only": True}],
            "file_properties": {"source": "ANISONGDB"},
        },
    }
    monkeypatch.setattr(filters.metadata_fetch, "get_metadata", metadata.get)
    monkeypatch.setattr(filters, "extract_version", lambda filename: 2 if filename == second else 1)
    monkeypatch.setattr(filters.censors, "get_file_censors", lambda filename: [{"nsfw": True}] if censored and filename == matched else [])

    assert filters.evaluate_filter({"themes_exclude": ["NSFW (Without Censors)"]}, filenames) == (
        [first, matched, unmatched] if censored else [first, unmatched]
    )
    assert filters.evaluate_filter({"themes_exclude": ["NSFW (With Censors)"]}, filenames) == (
        [first, second, unmatched] if censored else filenames
    )
    assert filters.evaluate_filter({"themes_include": ["NSFW (Without Censors)"]}, filenames) == (
        [second] if censored else [second, matched]
    )
    assert filters.evaluate_filter({"themes_include": ["NSFW (With Censors)"]}, filenames) == (
        [matched] if censored else []
    )


def test_filter_metadata_aggregation_processes_each_anime_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        filters.metadata_fetch,
        "filename_to_mal",
        {
            "op.webm": {"mal_id": "1"},
            "ed.webm": {"mal_id": "1"},
            "other.webm": {"mal_id": "2"},
        },
    )
    metadata = {
        "op.webm": {
            "season": "Spring 2020",
            "score": 8.5,
            "rank": 10,
            "members": 100,
            "popularity": 50,
            "songs": [{"artist": ["Artist B", "Artist A"]}],
            "studios": ["Studio B"],
            "genres": ["Action"],
        },
        "other.webm": {
            "season": "Winter 2019",
            "score": 7,
            "rank": 20,
            "members": 50,
            "popularity": 100,
            "songs": [{"artist": ["Artist C"]}],
            "studios": ["Studio A"],
            "themes": ["School"],
        },
    }

    def get_metadata(filename):
        calls.append(filename)
        return metadata.get(filename)

    monkeypatch.setattr(filters.metadata_fetch, "get_metadata", get_metadata)

    aggregate = filters._aggregate_filter_metadata(["op.webm", "ed.webm", "other.webm"])

    assert calls == ["op.webm", "other.webm"]
    assert aggregate["seasons"] == ["Winter 2019", "Spring 2020"]
    assert aggregate["artists"] == ["Artist A", "Artist B", "Artist C"]
    assert aggregate["studios"] == ["Studio A", "Studio B"]
    assert aggregate["tags"] == ["Action", "School"]
    assert aggregate["ranges"] == {
        "score": {"min": 7.0, "max": 8.5},
        "rank": {"min": 10, "max": 20},
        "members": {"min": 50, "max": 100},
        "popularity": {"min": 50, "max": 100},
    }


def test_web_filter_can_widen_again_from_stable_source(monkeypatch, clean_playlist):
    clean_playlist.clear()
    clean_playlist.update({
        "name": "Test",
        "playlist": ["a.webm", "b.webm"],
        "current_index": 1,
        "infinite": False,
    })
    metadata = {
        "a.webm": {"score": 9, "title": "A", "slug": "OP1", "songs": [], "studios": []},
        "b.webm": {"score": 5, "title": "B", "slug": "OP1", "songs": [], "studios": []},
    }
    monkeypatch.setattr(filters.metadata_fetch, "get_metadata", metadata.get)
    monkeypatch.setattr(filters.information_popup, "get_tags", lambda data: [])
    monkeypatch.setattr(filters, "get_all_filters", lambda: {})
    monkeypatch.setattr(filters.playlist_ops, "get_playlists_dict", lambda: {})
    monkeypatch.setattr(filters.lists, "show_playlist", lambda *args: None)
    monkeypatch.setattr(
        filters.transport,
        "update_current_index",
        lambda value: clean_playlist.__setitem__("current_index", value),
    )
    monkeypatch.setattr(filters, "_editor_regular_source", None)
    monkeypatch.setattr(filters, "_editor_regular_name", None)
    monkeypatch.setattr(filters, "_editor_regular_result_revision", None)
    monkeypatch.setattr(filters, "_editor_regular_filter", {})

    context = filters.get_filter_editor_context()
    first = filters.apply_filter_definition(
        {"score_min": 8},
        source_revision=context["source_revision"],
        live_revision=context["live_revision"],
    )
    assert first["ok"] is True
    assert clean_playlist["playlist"] == ["a.webm"]

    second = filters.apply_filter_definition(
        {},
        source_revision=first["source_revision"],
        live_revision=first["live_revision"],
    )
    assert second["ok"] is True
    assert clean_playlist["playlist"] == ["a.webm", "b.webm"]


def test_web_filter_rejects_apply_after_playlist_changes(monkeypatch, clean_playlist):
    clean_playlist.clear()
    clean_playlist.update({"name": "Test", "playlist": ["a.webm"], "current_index": 0, "infinite": False})
    monkeypatch.setattr(filters.metadata_fetch, "get_metadata", lambda filename: {
        "score": 9, "title": "A", "slug": "OP1", "songs": [], "studios": [],
    })
    monkeypatch.setattr(filters.information_popup, "get_tags", lambda data: [])
    monkeypatch.setattr(filters, "get_all_filters", lambda: {})
    monkeypatch.setattr(filters.playlist_ops, "get_playlists_dict", lambda: {})
    monkeypatch.setattr(filters, "_editor_regular_source", None)
    monkeypatch.setattr(filters, "_editor_regular_name", None)
    monkeypatch.setattr(filters, "_editor_regular_result_revision", None)

    context = filters.get_filter_editor_context()
    clean_playlist["playlist"].append("b.webm")
    result = filters.apply_filter_definition(
        {},
        source_revision=context["source_revision"],
        live_revision=context["live_revision"],
    )

    assert result["ok"] is False
    assert result["stale"] is True
    assert clean_playlist["playlist"] == ["a.webm", "b.webm"]


@pytest.mark.parametrize("name", ["../escape", "bad/name", "CON", "CON.txt", "trailing."])
def test_save_filter_definition_rejects_unsafe_windows_names(monkeypatch, tmp_path, name):
    monkeypatch.setattr(filters, "FILTERS_FOLDER", str(tmp_path))

    with pytest.raises(filters.FilterValidationError):
        filters.save_filter_definition(name, {})
