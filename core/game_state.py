"""Central application state container.

Exposes a single `state` object owning the app's live mutable state,
grouped into `SimpleNamespace` clusters.

DICT IDENTITY CONTRACT: the dict/list clusters (metadata, playback) hold
mutable containers that code across the app reads via `state.<cluster>.X`
and mutates in place. Replace contents in place (`.clear(); .update(new)`),
never reassign `state.<cluster>.X = new` after startup — the few remaining
playback aliases in `guess_the_anime.py` and function-local refs (e.g.
`youtube_control` mutating `state.metadata.youtube_metadata` in place) would
silently desync.
Scalar clusters (controls, lightning, lists, ...) have no main-side mirror
and are freely reassigned — state is their single source of truth.
"""

from __future__ import annotations

from types import SimpleNamespace


class GameState:
    """Single source of truth for application state."""

    def __init__(self) -> None:
        # Metadata cluster — dict-identity contract (see module docstring).
        # playlist and file_metadata are replaced once at startup by
        # guess_the_anime.py (before any consumer holds a reference);
        # youtube_metadata is loaded in-place by youtube_control. Every
        # other member keeps the empty default below.
        self.metadata = SimpleNamespace(
            playlist={},                    # replaced once with a BLANK_PLAYLIST deepcopy at startup
            directory_files={},
            file_metadata={},               # replaced once with FileMetadataDict at startup
            file_metadata_overrides={},
            anime_metadata={},
            anidb_metadata={},
            ai_metadata={},
            anime_metadata_overrides={},
            anilist_metadata={},
            youtube_metadata={},            # loaded in-place by youtube_control.load_youtube_metadata()
        )
        # Playback cluster — dict/list state mutated in place (dict-identity
        # contract, same as metadata).
        self.playback = SimpleNamespace(
            youtube_queue=None,
            previous_media=None,            # last played media path (string) for repeat playback

            currently_playing={},
            bonus_settings={},
            fl_rounds_list=[],
            popout_buttons_by_name={},
            cached_images={},
            music_files=[],
            check_theme_cache={},
            lightning_mode_settings={},
        )
        # Control cluster — scalar playback/UI control state (reassignable).
        self.controls = SimpleNamespace(
            autoplay_toggle=0,
            special_repeat_track_mode=False,
            autoplay_fullscreen=True,
            mpv_always_on_top=False,
            volume_level=100,
            bgm_volume=1.0,
            stream_volume_boost=0,
            disable_video_audio=False,
            light_muted=False,
            disable_shortcuts=True,         # keyboard-shortcut master switch
            progress_bar_enabled=True,      # mpv OSD playback progress bar
            tutorial_shown=False,           # persisted: tutorial auto-shown once
            video_stopped=True,             # runtime: playback halted / EOF guard (not persisted)
            updating_metadata=False,        # runtime: async metadata-update lock (not persisted)
            coming_up_queue=None,           # runtime: dict|None queued "coming up" popup (rebound by seek-bar ticker)
            pending_restore_collapsed=False, # runtime: apply saved collapsed player state after UI render
            auto_info_start=False,          # persisted: auto-show info popup at round start
            auto_info_end=False,            # persisted: auto-show info popup at round end
            auto_refresh_toggle=False,      # persisted: auto-refresh metadata on fetch
            auto_bonus_start=None,          # runtime: None=off, 'random' or a bonus type key=on
            auto_reveal_start=None,         # runtime (not saved): None=off | 'auto' | 'blind' | 'reveal' | 'mute' — auto-queue a round each theme
            auto_reveal_variant=None,       # runtime (not saved): None=random | a peek variant key — forced variant for auto-reveal
            auto_reveal_seconds=0,          # runtime (not saved): 0=off (static) | int seconds — fade the reveal overlay fully off over this long
        )
        # Lightning cluster — scalar lightning-round state (reassignable;
        # single source of truth, no main-side mirror).
        self.lightning = SimpleNamespace(
            light_mode=None,
            character_round_answer=None,
            light_round_started=False,
            light_round_armed=False,        # a track just started (play_video ran); round is eligible to begin until the start window passes

            light_round_length=12,
            light_round_number=0,
            light_round_start_time=None,
            light_round_answer_length=8,
            fixed_lightning_queue=None,             # {"name": str, "rounds": list, "current_index": int}
            fixed_lightning_round_playlist_data={}, # loaded JSON data for current fixed round
            fixed_current_round=None,               # current round data
            current_light_mode=None,
            current_light_variant=None,
            title_light_string="",
            title_light_letters=None,
            light_speed_modifier=1,
            light_blind_one_second_count=None,
            light_answer_wall_start=None,           # wall-clock time when the answer phase began (set on first tick)
            light_answer_last_tick=None,            # wall-clock time of last update_light_round call in answer phase (pause compensation)
            stream_start_time=0,            # clip/OST round: stream offset (s) the answer phase seeks from
            _showed_lightning_answer=False, # answer phase already revealed this round (one-shot guard)
        )
        # Lists cluster — right-column list-display state (reassignable;
        # single source of truth, no main-side mirror). The list-header Tk
        # widget refs live in state.widgets below.
        self.lists = SimpleNamespace(
            last_themes_listed={},
            list_loaded=None,
            list_index=0,
            list_func=None,
            playlist_page_offset=0,
            persistent_buttons=[],
            button_to_index_map={},
            current_list_offset=0,
            current_list_content={},
            current_list_name_func=None,
            current_list_selected=-1,
            current_list_show_numbers=True,
            current_list_title="",
            # Persists the active field-themes sort across in-place refreshes
            # (e.g. queueing a theme) — set when a fresh list is shown.
            field_sort_key=None,
            # Persists a custom label renderer for the field-themes list (e.g.
            # the play-count labels used by the playlist "Most Played" sort).
            field_name_func=None,
            _list_action_from_keyboard=False,
            _list_nav_stack=[],
            _truncate_after_id=[None],
            drag_start_index=None,
            drag_current_y=None,
            hovered_button_index=None,
            external_drag_active=False,
            current_highlight_tag=None,
            current_source_tag=None,
            highlighted_buttons={},
        )
        # Widget cluster — long-lived Tk widgets, each assigned once at
        # startup right after the widget is created.
        self.widgets = SimpleNamespace(
            root=None,
            player=None,
            left_column=None,
            middle_column=None,
            right_column=None,
            # Right-column list panel sub-widgets + first-row toolbar frame,
            # all created once at startup and read by extracted UI modules.
            info_panel=None,
            first_row_frame=None,
            right_top=None,
            right_column_row=None,
            right_column_scrollbar=None,
            right_column_header=None,
            right_column_header_label=None,
            right_column_back_button=None,
            list_header_font=None,
            # First-row toolbar toggle buttons (created once by menu_builder).
            collapse_button=None,
            dock_button=None,
            popout_controls_button=None,
            playlist_menu_button=None,
            file_menu_button=None,
            queue_menu_button=None,
            bonus_menu_button=None,
            popup_menu_button=None,
            theme_menu_button=None,
            toggle_menu_button=None,
            directory_menu_button=None,
            # Controls-frame volume readout label; created once at startup,
            # reconfigured by toggles.audio_toggles.set_volume (its only reader).
            volume_label=None,
            # Controls-frame autoplay/repeat-mode button; created once at
            # startup, read/reconfigured by toggles.autoplay (its only reader).
            autoplay_button=None,
            # Right-column "reroll" button, created/destroyed by metadata_display
            # (its only reader/writer).
            reroll_button=None,
            # Points to right_column_header_label when a list title is shown;
            # written by ui.lists (its only writer).
            list_title_label=None,
        )
        # Config cluster — persisted scalar settings. SETTINGS_SCHEMA entries
        # tagged {"state": "config"} are routed here by config_io/settings_popup;
        # defaults below mirror the schema defaults.
        self.config = SimpleNamespace(
            YOUTUBE_API_KEY="",
            OPENAI_API_KEY="",
            SERPAPI_KEY="",
            IGDB_CLIENT_ID="",
            IGDB_CLIENT_SECRET="",
            directory="themes",             # configured themes source folder (persisted by config_io, not schema-driven)
            selected_rules_file="",         # scoreboard rules file (SETTINGS_SCHEMA key tagged {"state": "config"})
            title_top_info_txt="",          # custom text above title in title-only info (SETTINGS_SCHEMA key tagged {"state": "config"})
            scoreboard_rules=None,          # loaded scoreboard rules dict (load_rules() output); written by config_io + web_host_actions, read by main set_rules()
            themes_cache_size=500,          # MB; read by cache_download for the cache cap
            auto_download_themes=False,     # save downloads to themes dir vs temp cache
            skip_play_seconds=0,            # auto-skip play duration (0 = disabled)
            skip_jump_seconds=5,            # forward jump distance on skip
            SKIP_FADE_WINDOW_MS=350,        # ms fade-out before skip
            SKIP_FADE_IN_WINDOW_MS=300,     # ms fade-in after skip
            inverted_positions=False,       # swap element alignment for right-aligned scoreboard
            auto_fetch_missing=False,       # auto-fetch metadata when missing during play
            special_round_warning=True,     # show warning before special rounds
            special_round_playlist=True,    # auto-queue special rounds from system marks
            startup_check_updates=True,     # check GitHub for app updates on startup
            startup_check_metadata=True,    # check for newer metadata package on startup
            startup_check_censors=True,     # check for newer censors on startup
            end_session_txt="",             # custom end-session display text
            LAUNCH_SCOREBOARD_ON_STARTUP=False,
            AUTO_EXIT_SCOREBOARD=False,
            WEB_SERVER_ENABLED=False,
            NGROK_DOMAIN="",
            CLOUDFLARE_TUNNEL_TOKEN="",
            CLOUDFLARE_PUBLIC_URL="",
            HOST_PASSWORD="",
            keep_set_toggles=True,          # remember toggle states across restarts
            # Non-schema config globals (config_io round-trips them by hand).
            host="",                        # persisted host identity (config round-trip)
            inverted_colors=False,          # legacy color-invert flag (loaded from config only)
        )
        # Display cluster — screen geometry + UI-scaling toggle read by scl().
        # screen_* are set at startup from pyautogui.size(); scale_main_ui is a
        # SETTINGS_SCHEMA {"state": "display"} key. Defaults mirror scl's
        # reference resolution (modifier 1.0) before startup sets them.
        self.display = SimpleNamespace(
            scale_main_ui=False,
            screen_width=2560,
            screen_height=1440,
        )
        # Popout cluster — persisted layout config for the detachable popout
        # controls window (config_io reads/writes by hand, not via SETTINGS_SCHEMA).
        self.popout = SimpleNamespace(
            layout=None,    # list | None — user-saved grid; None → POPOUT_LAYOUT_DEFAULT
            columns=5,      # int — popout grid column count
            show_metadata=True,
            show_up_next=False,
            show_currently_playing=False,
        )
        # Metadata panel runtime UI state shared by metadata_display,
        # metadata_panel, and streaming.
        self.metadata_panel = SimpleNamespace(
            selected_extra_metadata="synopsis",
            show_spoiler_tags=False,
        )
        # Info-display cluster — which information-popup type is currently
        # active. Written by information_popup; read by answers/menu_registry/
        # shortcut_dispatch/marks.
        self.info_display = SimpleNamespace(
            title_info_only=False,
            artist_info_display=False,
            studio_info_display=False,
            season_info_display=False,
            year_info_display=False,
            _title_popup_intent=False,
        )
        # Lightning round dropdown state created during GUI setup and shared
        # by main, popout controls, and lightning_manager.
        self.lightning_ui = SimpleNamespace(
            light_mode_options=[],
            title_to_key={},
            selected_mode=None,
        )
        # Playlist UI refs created lazily by menu_builder and read by
        # playlist/popout/shortcut modules.
        self.playlist_ui = SimpleNamespace(
            difficulty_options=[
                "MODE: VERY EASY", "MODE: EASY", "MODE: NORMAL",
                "MODE: HARD", "MODE: VERY HARD", "MODE: RANDOM",
            ],
            difficulty_dropdown=None,
            selected_difficulty=None,
        )
        # Settings preset cluster - saved profile dictionaries plus selected
        # profile names for the generic settings editors and config I/O.
        self.settings_presets = SimpleNamespace(
            selected_light_mode_settings="",
            saved_lightning_mode_settings={},
            selected_infinite_settings="",
            saved_infinite_settings={},
            selected_bonus_settings="",
            saved_bonus_settings={},
        )
        # Shortcut cluster - persisted user overrides {menu item id -> key}.
        # Mutate config in place so editor/menu readers keep a stable dict.
        self.shortcuts = SimpleNamespace(
            config={},
            dispatch={},          # runtime {key -> command} table, built by menu_builder.rebuild_shortcut_dispatch
        )
        # Remote data update timestamps persisted in config.json.
        self.update_timestamps = SimpleNamespace(
            metadata_last_updated=0,
            censors_last_updated=0,
        )
        # Seek/skip cluster — runtime scalar state for the playback hub
        # (seek-bar ticker, seek helpers, play navigation). Members:
        #   projected_player_time   — interpolated playback position (ms)
        #   last_player_time        — last raw mpv-reported position (ms)
        #   last_seek_time          — pending seek target set by the seek bar
        #   last_skip_anchor_ms     — anchor for the auto-skip-preview feature
        #   skip_fade_in_elapsed_ms — audio fade-in progress after a preview skip
        #   can_seek                — guard so programmatic seek-bar sets don't recurse
        #   skip_direction          — +1/-1 next/previous navigation direction
        #   SEEK_POLLING            — ticker interval (ms); shared by the seek-bar
        #                             loop and frame_round's frame ticker (constant)
        #   last_error              — last repeated playback-error string (ticker throttle)
        #   last_error_count        — consecutive count of last_error (ticker throttle)
        #   web_playback_counter    — tick counter throttling web playback-state pushes (~1/sec)
        self.seek = SimpleNamespace(
            SEEK_POLLING=50,
            projected_player_time=0,
            last_player_time=0,
            last_seek_time=None,
            last_skip_anchor_ms=None,
            skip_fade_in_elapsed_ms=None,
            can_seek=True,
            skip_direction=1,
            last_error=None,
            last_error_count=0,
            web_playback_counter=0,
        )
        # Colors cluster — overlay/highlight colors. OVERLAY_* are SETTINGS_SCHEMA
        # {"state": "colors"} keys; INVERSE_*/MIDDLE_* are derived by config_io.
        self.colors = SimpleNamespace(
            BACKGROUND_COLOR="gray12",      # fixed app/window/widget background accent (not user-set)
            HIGHLIGHT_COLOR="gray26",
            OVERLAY_BACKGROUND_COLOR="black",
            OVERLAY_TEXT_COLOR="white",
            INVERSE_OVERLAY_BACKGROUND_COLOR="white",
            INVERSE_OVERLAY_TEXT_COLOR="black",
            MIDDLE_OVERLAY_BACKGROUND_COLOR="dark gray",
            OVERLAY_COLOR_OPTIONS=["black", "white"],  # user-extendable overlay color choices (settings popup append/remove; config_io persists)
        )


# Module-level singleton used throughout the app.
state = GameState()
