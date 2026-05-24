"""Central application state container.

This module exposes a single `state` object that owns the live mutable
dicts which used to be scattered as module-level globals in
`guess_the_anime.py`. New code should read/write `state.metadata.<name>`
directly. Legacy code in `guess_the_anime.py` continues to use the
module-level aliases (`playlist`, `file_metadata`, `anime_metadata`, ...);
those aliases point to the SAME dict instances that `state.metadata`
owns, so updates made through one path are visible through the other.

IMPORTANT — DICT IDENTITY IS PART OF THE CONTRACT
    Never reassign `state.metadata.X = new_dict`. To replace contents,
    always do `state.metadata.X.clear(); state.metadata.X.update(new)`.
    Reassignment would silently break the legacy module-level aliases
    (and any other captured reference) by leaving them pointing at the
    previous dict.

The container is intentionally minimal right now. Additional clusters
(playback flags, UI state, settings, etc.) will be added as their
migrations land. Each cluster is a `SimpleNamespace` so attribute access
stays cheap and obvious.
"""

from __future__ import annotations

from types import SimpleNamespace


class GameState:
    """Single source of truth for application state.

    Currently owns: the metadata cluster (anime/file metadata caches,
    playlist, directory file index, overrides, and the YouTube metadata
    dict shared with `_app_scripts/youtube_control`).

    The metadata-cluster dicts are pre-populated as empty containers so
    callers can safely take a reference at import time. The exception is
    ``file_metadata``, which the main file must replace (in place, via
    ``state.metadata.file_metadata = <FileMetadataDict>``) once during
    startup before the dict is used — this is the only sanctioned
    reassignment, and it must happen before any consumer holds a
    reference.
    """

    def __init__(self) -> None:
        self.metadata = SimpleNamespace(
            playlist={},
            directory_files={},
            file_metadata={},               # replaced once with FileMetadataDict at startup
            file_metadata_overrides={},
            anime_metadata={},
            anidb_metadata={},
            ai_metadata={},
            anime_metadata_overrides={},
            anilist_metadata={},
            youtube_metadata={},            # aliased to youtube_control.youtube_metadata at startup
        )
        # Playback cluster — dict/list-valued state mutated in place from
        # the main file. Same identity contract as `metadata`: never
        # reassign, always mutate via .clear()/.update()/.extend() so
        # module-level aliases stay in sync.
        self.playback = SimpleNamespace(
            currently_playing={},
            bonus_settings={},
            fl_rounds_list=[],
            popout_buttons_by_name={},
            cached_images={},
            music_files=[],
            check_theme_cache={},
            lightning_mode_settings={},
        )
        # Widget cluster — references to long-lived Tk widgets created
        # once at startup. UNLIKE the dict clusters above, each is set
        # exactly once (the widget object itself is the shared thing);
        # the main file assigns them via `state.widgets.<name> = <widget>`
        # right after each widget is created.
        self.widgets = SimpleNamespace(
            root=None,
            player=None,
            left_column=None,
            middle_column=None,
            right_column=None,
        )


# Module-level singleton used throughout the app.
state = GameState()
