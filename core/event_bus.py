"""Tiny pub/sub event bus for decoupling app modules.

Usage:
    from core.event_bus import events

    def on_playlist_changed(payload):
        ...

    events.subscribe("playlist_changed", on_playlist_changed)
    events.publish("playlist_changed", {"name": "..."})

Design notes:
    - Synchronous: subscribers run on the caller's thread, in subscription order.
    - Exceptions in one subscriber are logged but do not stop others.
    - No wildcards, no priorities, no async — intentionally minimal so it
      stays easy to reason about. If those become needed, add them then.
    - Subscribers should be cheap; long work belongs on a background thread.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable

Subscriber = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Subscriber]] = {}

    def subscribe(self, event_name: str, callback: Subscriber) -> None:
        self._subs.setdefault(event_name, []).append(callback)

    def unsubscribe(self, event_name: str, callback: Subscriber) -> None:
        subs = self._subs.get(event_name)
        if not subs:
            return
        try:
            subs.remove(callback)
        except ValueError:
            pass

    def publish(self, event_name: str, payload: Any = None) -> None:
        for cb in list(self._subs.get(event_name, ())):
            try:
                cb(payload)
            except Exception:
                # A misbehaving subscriber must not block the rest.
                traceback.print_exc()


# Module-level singleton used throughout the app.
events = EventBus()
