"""Verify real event-bus wiring between app modules.

The bus (core.event_bus) decouples logic modules from UI modules; these tests
pin the contract so a renamed event string or dropped subscription is caught.
"""

from core.event_bus import events

import _app_scripts.ui.lists as lists
import _app_scripts.playlists.playlist as playlist_ops


def test_lists_subscribes_to_playlist_changed():
    assert lists._on_playlist_changed in events._subs.get("playlist_changed", [])


def test_notify_playlist_list_updated_publishes():
    seen = []

    def spy(payload):
        seen.append(payload)

    events.subscribe("playlist_changed", spy)
    try:
        # state.lists.list_loaded is not "playlist" in tests, so the real
        # subscriber no-ops; the spy proves the publish happens.
        playlist_ops._notify_playlist_list_updated()
    finally:
        events.unsubscribe("playlist_changed", spy)
    assert seen == [None]
