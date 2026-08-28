"""Regression coverage for source-backed (living) playlist refreshes."""

import copy
import json
from types import SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts.playlists import playlist_sources


@pytest.fixture(autouse=True)
def _restore_loaded_playlist():
    original = copy.deepcopy(state.metadata.playlist)
    yield
    state.metadata.playlist.clear()
    state.metadata.playlist.update(original)


def _source(source_type):
    source = {
        "type": source_type,
        "include_non_local": False,
        "auto_update": True,
    }
    if source_type == "anilist":
        source.update(user_id="viewer", only_watched=True)
    else:
        source["hashid"] = "playlist-id"
    return source


def test_loaded_refresh_preserves_current_theme_and_updates_ui(monkeypatch):
    source = _source("anilist")
    state.metadata.playlist.clear()
    state.metadata.playlist.update(
        name="Viewer's AniList",
        source=source,
        playlist=["a.webm", "current.webm", "c.webm"],
        current_index=1,
    )
    indexes = []
    notifications = []
    monkeypatch.setattr(
        playlist_sources.playlist,
        "_notify_playlist_list_updated",
        lambda: notifications.append(True),
    )
    monkeypatch.setattr(
        "_app_scripts.playback.transport.update_current_index",
        lambda index: indexes.append(index),
    )

    changed = playlist_sources._apply_loaded_playlist_refresh(
        "Viewer's AniList",
        source,
        ["new.webm", "a.webm", "current.webm", "c.webm"],
    )

    assert changed is True
    assert state.metadata.playlist["playlist"] == [
        "new.webm", "a.webm", "current.webm", "c.webm"
    ]
    assert state.metadata.playlist["current_index"] == 2
    assert indexes == [2]
    assert notifications == [True]


def test_late_refresh_does_not_change_a_different_loaded_playlist(monkeypatch):
    source = _source("anilist")
    state.metadata.playlist.clear()
    state.metadata.playlist.update(
        name="Another Playlist",
        source=source,
        playlist=["keep.webm"],
        current_index=0,
    )
    monkeypatch.setattr(
        "_app_scripts.playback.transport.update_current_index",
        lambda _index: pytest.fail("unrelated playlist was updated"),
    )

    changed = playlist_sources._apply_loaded_playlist_refresh(
        "Viewer's AniList", source, ["replacement.webm"]
    )

    assert changed is False
    assert state.metadata.playlist["playlist"] == ["keep.webm"]


@pytest.mark.parametrize("source_type", ["anilist", "animethemes"])
def test_startup_refresh_updates_disk_and_loaded_copy(
    monkeypatch, tmp_path, source_type
):
    source = _source(source_type)
    saved = {
        "name": "Living Playlist",
        "source": source,
        "playlist": ["old.webm"],
        "current_index": 0,
    }
    playlist_path = tmp_path / "Living Playlist.json"
    playlist_path.write_text(json.dumps(saved), encoding="utf-8")
    state.metadata.playlist.clear()
    # Deliberately differs from disk too: this covers a stale config snapshot
    # left by the old behavior on a previous run.
    state.metadata.playlist.update(
        name="Living Playlist",
        source=source,
        playlist=["stale-config.webm"],
        current_index=0,
    )
    monkeypatch.setattr(playlist_sources, "PLAYLISTS_FOLDER", str(tmp_path))
    monkeypatch.setattr(
        state.widgets,
        "root",
        SimpleNamespace(after=lambda _delay, callback: callback()),
    )
    monkeypatch.setattr(
        playlist_sources.playlist,
        "_notify_playlist_list_updated",
        lambda: None,
    )
    monkeypatch.setattr(
        "_app_scripts.playback.transport.update_current_index",
        lambda _index: None,
    )
    matching = ["new.webm", "kept.webm"]
    if source_type == "anilist":
        monkeypatch.setattr(
            playlist_sources,
            "get_anilist_matching_files",
            lambda *_args: matching,
        )
    else:
        monkeypatch.setattr(
            playlist_sources,
            "get_animethemes_matching_files",
            lambda *_args: (matching, "Living Playlist", len(matching)),
        )

    playlist_sources._update_living_playlists_in_background()

    assert json.loads(playlist_path.read_text(encoding="utf-8"))["playlist"] == matching
    assert state.metadata.playlist["playlist"] == matching


def test_loaded_copy_reconciles_when_saved_playlist_was_already_current(
    monkeypatch, tmp_path
):
    source = _source("anilist")
    matching = ["already-current.webm"]
    saved = {
        "name": "Living Playlist",
        "source": source,
        "playlist": matching,
        "current_index": 0,
    }
    (tmp_path / "Living Playlist.json").write_text(
        json.dumps(saved), encoding="utf-8"
    )
    state.metadata.playlist.clear()
    state.metadata.playlist.update(
        name="Living Playlist",
        source=source,
        playlist=["stale-config.webm"],
        current_index=0,
    )
    monkeypatch.setattr(playlist_sources, "PLAYLISTS_FOLDER", str(tmp_path))
    monkeypatch.setattr(
        state.widgets,
        "root",
        SimpleNamespace(after=lambda _delay, callback: callback()),
    )
    monkeypatch.setattr(
        playlist_sources,
        "get_anilist_matching_files",
        lambda *_args: matching,
    )
    monkeypatch.setattr(
        playlist_sources.playlist,
        "_notify_playlist_list_updated",
        lambda: None,
    )
    monkeypatch.setattr(
        "_app_scripts.playback.transport.update_current_index",
        lambda _index: None,
    )

    playlist_sources._update_living_playlists_in_background()

    assert state.metadata.playlist["playlist"] == matching
