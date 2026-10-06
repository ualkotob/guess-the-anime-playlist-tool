"""Regression tests for ambiguous file entries in file metadata."""

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch
from _app_scripts.file.metadata import metadata_panel
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
            "songs": [{"slug": "OP1", "title": "LILIUM"}],
        },
        "376": {
            "title": "Elfen Lied OVA",
            "series": ["Elfen Lied"],
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
