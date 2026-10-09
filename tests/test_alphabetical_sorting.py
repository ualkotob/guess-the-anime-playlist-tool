"""Alphabetical theme ordering stays consistent across desktop and web views."""

from types import SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts import utils
from _app_scripts.directory import stats
from _app_scripts.file.metadata import metadata_fetch
from _app_scripts.file.web_server import web_host_actions, web_search
from _app_scripts.playlists import entry_paths, filters, playlist
from _app_scripts.ui import lists


@pytest.mark.parametrize("name, expected", [
    ("The Amber", "amber"),
    ("tHE Amber", "amber"),
    ("  THE\t Amber  ", "amber"),
    ("Theoretical", "theoretical"),
    ("The", "the"),
    ("Beyond the Sky", "beyond the sky"),
    ("A Birch", "a birch"),
    ("An Apple", "an apple"),
    ("", ""),
    (None, ""),
])
def test_alphabetical_comparison_ignores_only_the_leading_the_word(name, expected):
    assert utils.alphabetical_sort_key(name) == expected


@pytest.fixture
def themes(monkeypatch):
    metadata = {
        "Birch-OP1.webm": {"title": "Birch", "eng_title": "Birch", "slug": "OP1"},
        "The Amber-OP10.webm": {"title": "The Amber", "eng_title": "THE Amber", "slug": "OP10"},
        "The Amber-OP2.webm": {"title": "The Amber", "eng_title": "THE Amber", "slug": "OP2"},
    }
    for filename, data in metadata.items():
        data.update({
            "filename": filename, "series": [data["title"]],
            "studios": ["Shared Studio"], "songs": [{
                "slug": data["slug"], "title": "Song", "artist": [data["title"]],
            }],
        })
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda entry: metadata.get(entry, {}))
    monkeypatch.setattr(metadata_fetch, "get_file_metadata_by_name", lambda entry: metadata.get(entry, {}))
    monkeypatch.setattr(playlist, "get_cached_deduplicated_files", lambda: list(metadata))
    return metadata


@pytest.mark.parametrize("index", range(6))
def test_playlist_text_sorts_ignore_the_in_both_directions(monkeypatch, themes, index):
    monkeypatch.setattr(state.metadata, "playlist", {"playlist": list(themes)})
    monkeypatch.setattr(playlist.transport, "update_current_index", lambda *_: None)
    monkeypatch.setattr(lists, "show_playlist", lambda: None)
    monkeypatch.setattr(playlist.config_io, "save_config", lambda: None)

    playlist.sort_playlist(index)

    expected = ["The Amber-OP10.webm", "The Amber-OP2.webm", "Birch-OP1.webm"]
    assert state.metadata.playlist["playlist"] == (expected[::-1] if index % 2 else expected)
    assert themes["The Amber-OP2.webm"]["title"] == "The Amber"


def test_field_view_keeps_natural_theme_number_order_and_refresh_sort(monkeypatch, themes):
    monkeypatch.setattr(state.lists, "last_themes_listed", [])
    monkeypatch.setattr(state.lists, "field_sort_key", None)
    monkeypatch.setattr(state.lists, "field_name_func", None)
    monkeypatch.setattr(state.lists, "current_list_title", "Themes")
    monkeypatch.setattr(lists.search_ops, "search_queue", None)
    monkeypatch.setattr(lists, "show_list", lambda *args, **kwargs: None)

    lists.show_field_themes(group=list(themes))
    lists.show_field_themes(update=True)

    assert state.lists.last_themes_listed == [
        "The Amber-OP2.webm", "The Amber-OP10.webm", "Birch-OP1.webm",
    ]


@pytest.mark.parametrize("mode", ["alpha_asc", "alpha_desc"])
def test_directory_playlist_theme_sorts_ignore_the(themes, mode):
    entries, _ = stats._build_playlist_theme_list(list(themes), mode)
    if mode == "alpha_desc":
        expected = ["Birch-OP1.webm", "The Amber-OP10.webm", "The Amber-OP2.webm"]
    else:
        expected = ["The Amber-OP10.webm", "The Amber-OP2.webm", "Birch-OP1.webm"]
    assert entries == expected


@pytest.mark.parametrize("kind", ["title", "series", "artist"])
def test_desktop_directory_groups_keep_labels_and_ignore_the(monkeypatch, themes, kind):
    groups = []
    monkeypatch.setattr(stats, "_run_stat_in_background", lambda title, compute: groups.extend(compute()))
    getattr(stats, f"{kind}_stats")(list(themes), "alpha")
    assert [label for label, _ in groups] == ["The Amber", "Birch"]


@pytest.fixture
def synchronous_web_actions(monkeypatch):
    monkeypatch.setattr(state.widgets, "root", SimpleNamespace(after=lambda delay, callback: callback()))
    monkeypatch.setattr(web_host_actions.threading, "Thread", lambda target, **kwargs: SimpleNamespace(start=target))


@pytest.mark.parametrize("kind", ["title", "series", "artist"])
def test_web_directory_groups_match_desktop_order(monkeypatch, themes, synchronous_web_actions, kind):
    groups = []
    monkeypatch.setattr(web_host_actions.web_server, "push_directory_groups", lambda result, *args, **kwargs: groups.extend(result))
    web_host_actions._handle_host_action("get_directory_groups", {"stat_type": f"{kind}_alpha"})
    assert [group["label"] for group in groups] == ["The Amber", "Birch"]


def test_web_directory_themes_sort_by_title_and_theme_number(monkeypatch, themes, synchronous_web_actions):
    results = []
    monkeypatch.setattr(web_search, "_build_play_history", lambda: {})
    monkeypatch.setattr(web_search, "_build_theme_web_result", lambda filename, history: filename)
    monkeypatch.setattr(web_host_actions.web_server, "push_directory_themes", lambda result, *args, **kwargs: results.extend(result))

    web_host_actions._handle_host_action("get_directory_themes", {
        "stat_type": "studio", "group_label": "Shared Studio",
    })

    assert results == ["The Amber-OP2.webm", "The Amber-OP10.webm", "Birch-OP1.webm"]


def test_autocomplete_keeps_full_titles_and_ignores_the(monkeypatch, themes):
    monkeypatch.setattr(metadata_fetch, "_metadata_cache", themes)
    monkeypatch.setattr(web_search.metadata_display, "get_display_title", lambda data: data["title"])
    assert web_search.get_all_anime_titles() == ["The Amber", "Birch"]


def test_filter_artist_names_follow_the_same_order(themes):
    assert filters.get_all_artists(list(themes)) == ["The Amber", "Birch"]


def test_theme_sort_uses_shared_theme_reference_title(monkeypatch):
    reference = entry_paths.make_theme_reference("shared.webm", "123", "OP1")
    metadata = {
        "shared.webm": {"title": "Zebra", "slug": "OP1"},
        reference: {"title": "The Amber", "slug": "OP1"},
        "birch.webm": {"title": "Birch", "slug": "OP1"},
    }
    monkeypatch.setattr(metadata_fetch, "get_metadata", lambda entry: metadata[entry])
    assert sorted(["birch.webm", reference], key=lists.theme_sort_key) == [reference, "birch.webm"]
    entries, _ = stats._build_playlist_theme_list(["birch.webm", reference], "alpha_asc")
    assert entries == [reference, "birch.webm"]


def test_theme_sort_uses_youtube_title_without_display_icons(monkeypatch):
    monkeypatch.setattr(lists.youtube_control, "is_youtube_file", lambda _: True)
    monkeypatch.setattr(lists.youtube_control, "get_youtube_metadata_by_filename", lambda _: {"title": "The Amber"})
    monkeypatch.setattr(lists.youtube_control, "get_youtube_display_title", lambda data: data["title"])
    assert lists.theme_sort_key("youtube-video.mp4")[0] == "amber"
