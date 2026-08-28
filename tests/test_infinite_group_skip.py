"""Infinite-playlist next-group action tests."""

import copy

import pytest

from core.game_state import state
import _app_scripts.playlists.infinite as infinite


class _RootStub:
    def __init__(self):
        self.scheduled = []
        self.cancelled = []

    def after(self, delay, callback):
        token = f"after-{len(self.scheduled)}"
        self.scheduled.append((delay, callback))
        return token

    def after_cancel(self, token):
        self.cancelled.append(token)


@pytest.fixture
def skip_state(monkeypatch):
    saved_playlist = copy.deepcopy(state.metadata.playlist)
    saved_root = state.widgets.root
    saved_debounce = infinite._reroll_debounce_id
    root = _RootStub()
    state.widgets.root = root
    infinite._reroll_debounce_id = None

    monkeypatch.setattr(infinite.entry_paths, "get_clean_filename", lambda value: value)
    monkeypatch.setattr(infinite.cache_download, "is_downloading", lambda _value: False)
    monkeypatch.setattr(infinite.cache_download, "cancel_download", lambda _value: None)
    monkeypatch.setattr(infinite.cache_download, "prefetch_next_themes", lambda: None)
    monkeypatch.setattr(infinite.metadata_display, "up_next_text", lambda: None)
    monkeypatch.setattr(infinite.lightning_manager, "queue_next_lightning_mode", lambda: None)
    monkeypatch.setattr(infinite.transport, "update_current_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(infinite.playlist_ops, "_notify_playlist_list_updated", lambda: None)

    yield root

    state.metadata.playlist.clear()
    state.metadata.playlist.update(saved_playlist)
    state.widgets.root = saved_root
    infinite._reroll_debounce_id = saved_debounce


def test_skip_promotes_preselected_next_group(skip_state, monkeypatch):
    playlist = state.metadata.playlist
    playlist.clear()
    playlist.update({
        "infinite": True,
        "current_index": 0,
        "playlist": ["current.webm", "same-group.webm"],
        "speculative_tail": ["next-group.webm", "later-group.webm"],
        "order": 4,
    })

    def advance_order():
        playlist["order"] += 1

    monkeypatch.setattr(infinite, "next_playlist_order", advance_order)

    infinite.skip_infinite_group()

    assert playlist["playlist"] == ["current.webm", "next-group.webm"]
    assert playlist["speculative_tail"] == ["later-group.webm"]
    assert playlist["order"] == 5
    assert any(callback is infinite.fill_speculative_tail
               for _delay, callback in skip_state.scheduled)


def test_skip_generates_next_group_when_tail_is_empty(skip_state, monkeypatch):
    playlist = state.metadata.playlist
    playlist.clear()
    playlist.update({
        "infinite": True,
        "current_index": 0,
        "playlist": ["current.webm", "same-group.webm"],
        "speculative_tail": [],
        "spec_order": 8,
    })
    calls = []

    def clear_tail():
        calls.append("clear")
        playlist["speculative_tail"] = []

    def generate(*, increment):
        calls.append(("generate", increment))
        playlist["playlist"].append("generated-next-group.webm")

    monkeypatch.setattr(infinite, "_clear_speculative_tail", clear_tail)
    monkeypatch.setattr(infinite, "get_next_infinite_track", generate)

    infinite.skip_infinite_group()

    assert calls == ["clear", ("generate", True)]
    assert playlist["playlist"] == ["current.webm", "generated-next-group.webm"]
    assert "spec_order" not in playlist


def test_skip_is_noop_when_no_queued_infinite_track(skip_state):
    playlist = state.metadata.playlist
    playlist.clear()
    playlist.update({
        "infinite": True,
        "current_index": 0,
        "playlist": ["current.webm"],
        "speculative_tail": ["future.webm"],
    })
    before = copy.deepcopy(playlist)

    infinite.skip_infinite_group()

    assert playlist == before
    assert skip_state.scheduled == []
