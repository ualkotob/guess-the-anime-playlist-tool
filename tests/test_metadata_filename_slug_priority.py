"""Regression tests for ambiguous file entries in file metadata."""

import pytest

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch
from _app_scripts.file.metadata import metadata_panel
from _app_scripts.playback import transport
from _app_scripts.playlists import entry_paths
from _app_scripts.search import search as search_ops


def _theme_entry(filename):
    return {
        "1": {
            filename: {
                "lyrics": False,
                "nc": False,
                "resolution": 720,
                "source": "WEB",
            }
        }
    }


@pytest.fixture
def shared_theme(monkeypatch):
    filename = "Example-OP1.webm"
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "1": {"name": "Example", "themes": {"OP1": _theme_entry(filename)}},
        "2": {"name": "Example OVA", "themes": {"OP1": _theme_entry(filename)}},
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {
        "1": {"title": "Example", "series": ["Example"], "popularity": 2000},
        "2": {"title": "Example OVA", "series": ["Example"], "popularity": 100},
    })
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal_candidates", {})
    monkeypatch.setattr(metadata_fetch, "_metadata_cache", {})
    metadata_fetch.build_filename_to_mal_map()
    return filename


@pytest.mark.parametrize("reverse_order", [False, True])
@pytest.mark.parametrize("extension", [".webm", ".mp4"])
def test_shared_filename_prefers_popularity_over_series_and_insertion_order(
    shared_theme, reverse_order, extension,
):
    if reverse_order:
        state.metadata.file_metadata = dict(reversed(state.metadata.file_metadata.items()))
    metadata_fetch.build_filename_to_mal_map()

    filename = shared_theme.replace(".webm", extension)
    assert metadata_fetch.get_file_metadata_by_name(filename)["mal"] == "2"
    assert metadata_fetch.get_metadata("[L]" + filename)["mal"] == "2"


@pytest.mark.parametrize("rank", [None, "N/A", 0, -1, 50])
def test_shared_filename_uses_current_popularity_after_map_is_built(shared_theme, rank):
    state.metadata.anime_metadata["2"]["popularity"] = rank
    expected = "2" if rank == 50 else "1"

    assert metadata_fetch.get_file_metadata_by_name(shared_theme)["mal"] == expected


def test_shared_filename_uses_popularity_loaded_after_file_index(shared_theme):
    anime_metadata = dict(state.metadata.anime_metadata)
    state.metadata.anime_metadata.clear()
    metadata_fetch.build_filename_to_mal_map()
    state.metadata.anime_metadata.update(anime_metadata)

    assert metadata_fetch.get_metadata(shared_theme)["mal"] == "2"


def test_direct_reference_keeps_less_popular_theme(shared_theme):
    reference = entry_paths.make_theme_reference(shared_theme, "1", "OP1", "1")

    assert metadata_fetch.get_metadata(shared_theme)["mal"] == "2"
    assert metadata_fetch.get_metadata(reference)["mal"] == "1"
    assert metadata_fetch.get_metadata("[L]" + reference)["mal"] == "1"


@pytest.mark.parametrize("explicit_reference", [False, True])
def test_fixed_round_playback_resolves_popular_theme(shared_theme, monkeypatch, explicit_reference):
    theme = (entry_paths.make_theme_reference(shared_theme, "1", "OP1", "1")
             if explicit_reference else shared_theme)
    round_data = {"type": "regular", "theme": theme}
    monkeypatch.setattr(state.lightning, "fixed_current_round", round_data)
    monkeypatch.setattr(state.config, "auto_fetch_missing", False)
    monkeypatch.setattr(entry_paths, "get_file_path", lambda _entry: None)
    # Stop before loading media, after the fixed round has resolved its metadata.
    monkeypatch.setattr(transport.cache_download, "resolve_playable_path", lambda *args: None)

    assert transport.play_filename(round_data["theme"], fullscreen=False) is False
    assert metadata_fetch._metadata_cache[theme]["mal"] == ("1" if explicit_reference else "2")


def test_op_filename_wins_when_file_is_listed_as_opening_and_ending(monkeypatch):
    filename = "YuushakeiNiShosu-OP1.webm"
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "56009": {
            "themes": {
                "OP1": _theme_entry(filename),
                "ED1": _theme_entry(filename),
            }
        }
    })
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})

    metadata_fetch.build_filename_to_mal_map()

    assert metadata_fetch.get_file_metadata_by_name(filename)["slug"] == "OP1"
    assert metadata_fetch.get_file_metadata_by_name("YuushakeiNiShosu-OP1.mp4")["slug"] == "OP1"


def test_ed_filename_wins_regardless_of_metadata_order(monkeypatch):
    filename = "Example-ED1.webm"
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "1": {
            "themes": {
                "ED1": _theme_entry(filename),
                "OP1": _theme_entry(filename),
            }
        }
    })
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})

    metadata_fetch.build_filename_to_mal_map()

    assert metadata_fetch.get_file_metadata_by_name(filename)["slug"] == "ED1"


def test_main_series_wins_when_video_is_shared_with_side_story(monkeypatch):
    filename = "ElfenLied-OP1.webm"
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "226": {
            "name": "Elfen Lied",
            "themes": {"OP1": _theme_entry(filename)},
        },
        "376": {
            "name": (
                "Elfen Lied: Tooriame nite - Arui wa, Shoujo wa Ikani "
                "Shite Sono Shinjou ni Itatta ka?"
            ),
            "themes": {"OP1": _theme_entry(filename)},
        },
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {
        "226": {
            "title": "Elfen Lied",
            "eng_title": "Elfen Lied",
            "series": ["Elfen Lied"],
            "type": "TV",
        },
        "376": {
            "title": (
                "Elfen Lied: Tooriame nite - Arui wa, Shoujo wa Ikani "
                "Shite Sono Shinjou ni Itatta ka?"
            ),
            "series": ["Elfen Lied"],
            "type": "OVA",
        },
    })
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})

    metadata_fetch.build_filename_to_mal_map()

    result = metadata_fetch.get_file_metadata_by_name(filename)
    assert result["mal"] == "226"
    assert result["name"] == "Elfen Lied"


def test_opening_wins_when_shared_filename_has_no_slug(monkeypatch):
    filename = "SharedTheme.webm"
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "1": {
            "name": "Example",
            "themes": {
                "OP1": _theme_entry(filename),
                "ED1": _theme_entry(filename),
            },
        }
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {
        "1": {"title": "Example", "series": ["Example"]},
    })
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})

    metadata_fetch.build_filename_to_mal_map()

    assert metadata_fetch.get_file_metadata_by_name(filename)["slug"] == "OP1"


def test_shared_video_has_distinct_search_and_navigation_entries(monkeypatch):
    filename = "ElfenLied-OP1.webm"
    monkeypatch.setattr(state.metadata, "file_metadata", {
        "226": {
            "name": "Elfen Lied",
            "themes": {"OP1": _theme_entry(filename)},
        },
        "376": {
            "name": "Elfen Lied OVA",
            "themes": {"OP1": _theme_entry(filename)},
        },
    })
    monkeypatch.setattr(state.metadata, "anime_metadata", {
        "226": {
            "title": "Elfen Lied",
            "series": ["Elfen Lied"],
            "popularity": 300,
            "songs": [{"slug": "OP1", "title": "LILIUM"}],
        },
        "376": {
            "title": "Elfen Lied OVA",
            "series": ["Elfen Lied"],
            "popularity": 3000,
            "songs": [{"slug": "OP1", "title": "LILIUM"}],
        },
    })
    monkeypatch.setattr(metadata_fetch, "filename_to_mal", {})
    monkeypatch.setattr(metadata_fetch, "filename_to_mal_candidates", {})
    metadata_fetch.invalidate_metadata_cache()
    metadata_fetch.build_filename_to_mal_map()

    references = metadata_fetch.get_theme_references(filename)
    assert len(references) == 2
    assert entry_paths.get_clean_filename(references[0]) == filename
    assert [metadata_fetch.get_metadata(ref)["title"] for ref in references] == [
        "Elfen Lied",
        "Elfen Lied OVA",
    ]

    monkeypatch.setattr(
        search_ops.playlist_ops,
        "get_directory_files",
        lambda include_non_local=True: [filename],
    )
    results = search_ops.search_playlist("Elfen Lied")

    assert [metadata_fetch.get_metadata(ref)["title"] for ref in results] == [
        "Elfen Lied",
        "Elfen Lied OVA",
    ]
    assert metadata_fetch.get_metadata(references[1])["mal"] == "376"

    played = []

    class _Button:
        def __init__(self, *args, **kwargs):
            self.command = kwargs["command"]

        def bind(self, *args, **kwargs):
            pass

    monkeypatch.setattr(metadata_panel.tk, "Button", _Button)
    monkeypatch.setattr(
        metadata_panel.metadata_display,
        "play_video_from_filename",
        played.append,
    )
    button = metadata_panel._create_theme_play_button(
        None, filename, "Play", mal_id="376", slug="OP1", version="1"
    )
    button.command()

    assert metadata_fetch.get_metadata(played[0])["mal"] == "376"
