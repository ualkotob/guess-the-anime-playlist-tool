"""Safety guard for delayed work associated with a lightning media load.

This module intentionally does not own lightning mode setup.  It only gives
startup callbacks a stable round identity so work queued for an older file
cannot uncover, unmute, or resume a newer round.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.game_state import state


@dataclass(frozen=True)
class RoundToken:
    generation: int
    filename: str | None


def begin_round():
    """Invalidate prior callbacks and return the new round generation."""
    state.lightning.round_generation += 1
    return state.lightning.round_generation


def capture():
    return RoundToken(
        generation=state.lightning.round_generation,
        filename=state.playback.currently_playing.get("filename"),
    )


def is_current(token):
    if token.generation != state.lightning.round_generation:
        return False
    if token.filename is None:
        return True
    return token.filename == state.playback.currently_playing.get("filename")


def call_if_current(token, callback, *args, **kwargs):
    if not is_current(token):
        return None
    return callback(*args, **kwargs)


def after(delay_ms, callback, *args, token=None, **kwargs):
    """Schedule callback only while its originating round remains current."""
    token = token or capture()

    def guarded_callback():
        return call_if_current(token, callback, *args, **kwargs)

    return state.widgets.root.after(delay_ms, guarded_callback)
