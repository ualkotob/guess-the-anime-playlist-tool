"""Regression tests for ambiguous file entries in file metadata."""

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch


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
