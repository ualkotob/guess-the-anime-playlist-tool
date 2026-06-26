"""Config file I/O — save_config / load_config plus one-time migrations and
popout-layout preset I/O.

Fully decoupled from the main module: sibling feature modules are imported
directly, cross-cutting config settings live on `state.config` / `state.colors`
(SETTINGS_SCHEMA entries tagged {"state": "config"} route through the generic
load/save loops), and the few playback-hub callables (playlist-name refresh,
current-index update, scoreboard rules apply) are reached on the transport
sibling directly.
"""
import os
import json
import copy
from datetime import datetime

from _app_scripts import utils
import _app_scripts.toggles.censors as censors
import _app_scripts.playback.dock_player as dock_player
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.playback.transport as transport
import _app_scripts.file.web_server.web_server as web_server
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.toggles.audio_toggles as audio_toggles
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.playlists.infinite as infinite
import _app_scripts.bonus.bonus as bonus
import _app_scripts.queue_round.lightning_rounds.lightning_settings as lightning_settings
import _app_scripts.queue_round.lightning_rounds.trivia_round as trivia_round
from core.app_logging import log_exception
from core.game_state import state
from core.paths import (
    CONFIG_FILE,
    CACHE_METADATA_FILE,
    CENSOR_JSON_FILE,
    CENSORS_FOLDER,
    RULES_FOLDER,
    LIGHTNING_SETTINGS_FOLDER,
    INFINITE_SETTINGS_FOLDER,
    BONUS_SETTINGS_FOLDER,
    POPOUT_LAYOUTS_FOLDER,
    PLAYLISTS_FOLDER,
)

_atomic_json_write = utils._atomic_json_write


# =============================================
#            SETTINGS SCHEMA
# Each entry defines one configurable setting.
# key        - attribute name on state.<state> (every entry is tagged
#              {"state": "<cluster>"}; the load/save loops below dispatch via it)
# config_key - JSON key in config.json
# label      - Row label in settings popup (None = grouped row, no own label)
# type       - int | float | bool | str | password | color | rules_file
#              group="skip_group" entries are rendered together in one row
# default    - Default when missing from config
# tooltip    - ToolTip text in settings popup
# width      - Entry widget width (optional, default 10)
# min/max    - Clamping for int/float (optional)
# after_save - "restart_warning" | "reset_serpapi" (optional post-save callback key)
#
# Owned here (consumed by save_config/load_config below). main imports it as
# `from data.config_io import SETTINGS_SCHEMA` only so the settings popup can
# render it; the save/load loops below reference the local `SETTINGS_SCHEMA`.
# =============================================
SETTINGS_SCHEMA = [
    {"key": "volume_level",                    "config_key": "volume_level",                    "label": "Volume Level:",              "type": "int",      "default": 100,   "width": 10, "state": "controls", "tooltip": "Master volume level for all audio playback (0-100)."},
    {"key": "stream_volume_boost",             "config_key": "stream_volume_boost",             "label": "Stream Volume Boost:",       "type": "int",      "default": 0,     "width": 10, "state": "controls", "tooltip": "Additional volume boost specifically for stream audio from YouTube clips/trailers."},
    {"key": "bgm_volume","config_key": "bgm_volume","label": "BGM Volume:",     "type": "float",    "default": 1.0,   "width": 10, "min": 0.0, "max": 1.5, "state": "controls", "tooltip": "Volume multiplier for background music (0.0 - 1.5). Scales the dB curve output."},
    {"key": "themes_cache_size",               "config_key": "themes_cache_size",               "label": "Themes Cache Size (MB):",    "type": "int",      "default": 500,   "width": 10, "min": 0,   "state": "config", "tooltip": "Maximum size of the themes cache folder in MB. Downloaded themes are cached for faster playback."},
    {"key": "auto_download_themes",             "config_key": "auto_download_themes",             "label": "Auto-Download Themes:",       "type": "bool",     "default": False,          "state": "config", "tooltip": "When enabled, downloaded themes are saved directly to your themes directory as permanent files instead of the temporary cache."},
    # Skip group — 4 entries rendered as one row in the popup
    {"key": "skip_play_seconds",     "config_key": "skip_play_seconds",  "label": "Skip Play Settings:", "type": "float", "default": 0,   "width": 6, "min": 0, "group": "skip_group", "state": "config", "tooltip": "Play Seconds: Duration to play before auto-skip (0 = disabled)"},
    {"key": "skip_jump_seconds",     "config_key": "skip_jump_seconds",  "label": None,                  "type": "float", "default": 5,   "width": 6, "min": 0, "group": "skip_group", "state": "config", "tooltip": "Jump Seconds: Distance to jump forward when skip triggers"},
    {"key": "SKIP_FADE_WINDOW_MS",   "config_key": "skip_fade_out_ms",   "label": None,                  "type": "int",   "default": 350, "width": 6, "min": 0, "group": "skip_group", "state": "config", "tooltip": "Fade Out (ms): Milliseconds to fade volume down before skip"},
    {"key": "SKIP_FADE_IN_WINDOW_MS","config_key": "skip_fade_in_ms",    "label": None,                  "type": "int",   "default": 300, "width": 6, "min": 0, "group": "skip_group", "state": "config", "tooltip": "Fade In (ms): Milliseconds to fade volume up after skip"},
    # Color — special rendering: dropdown + add/delete buttons
    {"key": "OVERLAY_BACKGROUND_COLOR", "config_key": "back_color",  "label": "Background Color:", "type": "color", "default": "black", "state": "colors", "tooltip": "Background color of overlay windows."},
    {"key": "OVERLAY_TEXT_COLOR",        "config_key": "text_color",  "label": "Text Color:",       "type": "color", "default": "white", "state": "colors", "tooltip": "Text color displayed in overlay windows."},
    # Booleans
    {"key": "inverted_positions",    "config_key": "inverted_positions",    "label": "Inverted Positions:",      "type": "bool", "default": False, "state": "config", "tooltip": "Swaps alignment of some elements to adjust for scoreboard position. Enable if scoreboard is aligned right."},
    {"key": "scale_main_ui",         "config_key": "scale_main_ui",         "label": "Scale Main UI:",            "type": "bool", "default": False, "state": "display", "tooltip": "Scales the main UI based on screen resolution. Requires restart.", "after_save": "restart_warning"},
    {"key": "auto_fetch_missing",    "config_key": "auto_fetch_missing",    "label": "Auto Fetch Missing:",       "type": "bool", "default": False, "state": "config", "tooltip": "Automatically fetches metadata if it's not found while playing themes."},
    {"key": "special_round_warning", "config_key": "special_round_warning", "label": "Special Round Warning:",   "type": "bool", "default": True,  "state": "config", "tooltip": "Shows a warning before special rounds begin."},
    {"key": "special_round_playlist","config_key": "special_round_playlist","label": "Special Round Playlist:",  "type": "bool", "default": True,  "state": "config", "tooltip": "Auto-queue special rounds based on system playlist marks."},
    # Rules file — special rendering: folder-scanned dropdown
    {"key": "selected_rules_file", "config_key": "selected_rules_file", "state": "config", "label": "Rules File:",              "type": "rules_file", "default": "", "tooltip": "Select which rules file to use for the scoreboard. Files must end with 'rules.json'."},
    # API keys — password type (masked entry)
    {"key": "YOUTUBE_API_KEY", "config_key": "youtube_api_key", "label": "YouTube API Key:", "type": "password", "default": "", "width": 30, "state": "config", "tooltip": "API key for YouTube integration features. Required for Clip and Ost lightning rounds."},
    {"key": "OPENAI_API_KEY",  "config_key": "openai_api_key",  "label": "OpenAI API Key:",  "type": "password", "default": "", "width": 30, "state": "config", "tooltip": "API key for OpenAI/ChatGPT integration features. Required for Trivia and Emoji lightning rounds."},
    {"key": "SERPAPI_KEY",     "config_key": "serpapi_key",     "label": "SerpAPI Key:",      "type": "password", "default": "", "width": 30, "state": "config", "after_save": "reset_serpapi", "tooltip": "SerpAPI key for Image lightning round (serpapi.com)."},
    {"key": "IGDB_CLIENT_ID",     "config_key": "igdb_client_id",     "label": "IGDB Client ID:",      "type": "password", "default": "", "width": 30, "state": "config", "tooltip": "Twitch/IGDB client ID for game metadata. Get it at dev.twitch.tv."},
    {"key": "IGDB_CLIENT_SECRET", "config_key": "igdb_client_secret", "label": "IGDB Client Secret:", "type": "password", "default": "", "width": 30, "state": "config", "tooltip": "Twitch/IGDB client secret for game metadata. Get it at dev.twitch.tv."},
    # Text fields
    {"key": "title_top_info_txt", "config_key": "title_top_info_txt", "label": "Title Only Info Text:", "type": "str", "default": "", "width": 30, "tooltip": "Custom text displayed above title when showing title-only information.", "state": "config"},
    {"key": "end_session_txt",    "config_key": "end_session_txt",    "label": "End Session Text:",      "type": "str", "default": "", "width": 30, "state": "config", "tooltip": "Custom text displayed at the top of the end session display."},
    # Scoreboard
    {"key": "LAUNCH_SCOREBOARD_ON_STARTUP", "config_key": "launch_scoreboard_on_startup", "label": "Auto-start Scoreboard:", "type": "bool", "default": False, "requires_scoreboard": True, "state": "config", "tooltip": "Automatically launch the scoreboard when the app starts."},
    {"key": "AUTO_EXIT_SCOREBOARD",         "config_key": "auto_exit_scoreboard",         "label": "Auto-exit Scoreboard:",  "type": "bool", "default": False, "requires_scoreboard": True, "state": "config", "tooltip": "Automatically close the scoreboard when this app exits."},
    # Web server
    {"key": "WEB_SERVER_ENABLED", "config_key": "web_server_enabled", "label": "Auto-start Web Server:", "type": "bool", "default": False, "requires_tunnel": True, "state": "config", "tooltip": "Automatically start the web answer server when the app launches. Can also be started/stopped manually from the Bonus Questions menu."},
    {"key": "NGROK_DOMAIN",       "config_key": "ngrok_domain",       "label": "Ngrok Domain:",          "type": "str",      "default": "", "width": 30, "requires_ngrok": True, "state": "config", "tooltip": "Your ngrok static domain (e.g. your-name.ngrok-free.app). Exposes the web server publicly. Requires ngrok.exe on PATH."},
    {"key": "CLOUDFLARE_TUNNEL_TOKEN", "config_key": "cloudflare_tunnel_token", "label": "Cloudflare Tunnel Token:", "type": "password", "default": "", "width": 30, "requires_cloudflared": True, "state": "config", "tooltip": "Token from the Cloudflare Zero Trust dashboard (Networks → Tunnels). Takes priority over ngrok when set."},
    {"key": "CLOUDFLARE_PUBLIC_URL",   "config_key": "cloudflare_public_url",   "label": "Cloudflare Public URL:",   "type": "str",      "default": "", "width": 30, "requires_cloudflared": True, "state": "config", "tooltip": "The public HTTPS URL for your Cloudflare tunnel (e.g. https://gta.yourdomain.com). Must match the hostname configured in the Cloudflare dashboard."},
    {"key": "HOST_PASSWORD",      "config_key": "host_password",      "label": "Host Password:",         "type": "password", "default": "", "width": 30, "requires_tunnel": True, "state": "config", "tooltip": "If set, entering this password on the join screen grants host view (live answer panel + metadata). Leave blank to disable."},
    # Toggles persistence
    {"key": "keep_set_toggles", "config_key": "keep_set_toggles", "label": "Keep Set Toggles:", "type": "bool", "default": True, "state": "config", "tooltip": "Remember the state of Censors, Auto Refresh, Info Start, Info End, Keyboard Shortcuts, Progress Bar, Fullscreen, Collapsed Interface, and Always On Top toggles across restarts."},
]


def _backup_broken_config(error):
    """Preserve an unreadable config so the app can recover without data loss."""
    if not os.path.exists(CONFIG_FILE):
        print(f"Error loading config: {error}")
        return None

    base, ext = os.path.splitext(CONFIG_FILE)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{base}.broken-{timestamp}{ext or '.json'}"
    counter = 1
    while os.path.exists(backup_path):
        backup_path = f"{base}.broken-{timestamp}-{counter}{ext or '.json'}"
        counter += 1

    try:
        os.replace(CONFIG_FILE, backup_path)
        print(f"Error loading config: {error}")
        print(f"Moved unreadable config to: {backup_path}")
        return backup_path
    except Exception as backup_error:
        log_exception("Could not back up unreadable config %s", CONFIG_FILE)
        print(f"Error loading config: {error}")
        print(f"Warning: could not back up unreadable config: {backup_error}")
        return None


def _migrate_old_file_structure():
    """One-time migration from the legacy 'files/' folder to the new folder layout.

    Explicit files:
      files/config.json          → config/config.json
      files/cache_metadata.json  → themes_cache/cache_metadata.json
      files/censors.json         → censors/censors.json
      files/ramuns_censors.json  → censors/ramuns_censors.json

    All *.json files in files/ ending with 'rules.json' (case-insensitive) → rules/

    After migration, removes 'files/' if it is empty.

    Preset migration (saved_lightning_mode_settings / saved_infinite_settings) always
    runs against config/config.json so it works even if files/ was already removed.
    """
    if os.path.exists("files"):
        explicit = [
            (os.path.join("files", "config.json"),         CONFIG_FILE),
            (os.path.join("files", "cache_metadata.json"), CACHE_METADATA_FILE),
            (os.path.join("files", "censors.json"),        CENSOR_JSON_FILE),
            (os.path.join("files", "ramuns_censors.json"), os.path.join(CENSORS_FOLDER, "ramuns_censors.json")),
        ]
        for src, dst in explicit:
            if os.path.exists(src) and not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                os.replace(src, dst)
                print(f"Migrated {src} → {dst}")

        # Move all rules files (any *.json ending with 'rules.json') to rules/
        try:
            for fname in os.listdir("files"):
                if fname.lower().endswith("rules.json") and os.path.isfile(os.path.join("files", fname)):
                    dst = os.path.join(RULES_FOLDER, fname)
                    if not os.path.exists(dst):
                        os.makedirs(RULES_FOLDER, exist_ok=True)
                        os.replace(os.path.join("files", fname), dst)
                        print(f"Migrated files/{fname} → {dst}")
        except Exception as e:
            print(f"Warning: rules migration error: {e}")

        # Remove files/ if now empty (ignoring subdirectories)
        try:
            remaining = [f for f in os.listdir("files") if os.path.isfile(os.path.join("files", f))]
            if not remaining:
                # Only remove the folder itself if there are no subdirectories either
                if not any(os.path.isdir(os.path.join("files", d)) for d in os.listdir("files")):
                    os.rmdir("files")
                    print("Removed empty 'files/' folder.")
        except Exception:
            pass

    # Migrate saved_lightning_mode_settings and saved_infinite_settings from config.json.
    # This runs unconditionally so it works even when files/ was already removed in a prior run.
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                old_config = json.load(f)
            for name, diff in old_config.get("saved_lightning_mode_settings", {}).items():
                dst = os.path.join(LIGHTNING_SETTINGS_FOLDER, f"{name}.json")
                if not os.path.exists(dst):
                    os.makedirs(LIGHTNING_SETTINGS_FOLDER, exist_ok=True)
                    with open(dst, "w", encoding="utf-8") as f:
                        json.dump(diff, f, indent=4)
                    print(f"Migrated lightning preset '{name}' → {dst}")
            for name, diff in old_config.get("saved_infinite_settings", {}).items():
                dst = os.path.join(INFINITE_SETTINGS_FOLDER, f"{name}.json")
                if not os.path.exists(dst):
                    os.makedirs(INFINITE_SETTINGS_FOLDER, exist_ok=True)
                    with open(dst, "w", encoding="utf-8") as f:
                        json.dump(diff, f, indent=4)
                    print(f"Migrated infinite preset '{name}' → {dst}")
    except Exception as e:
        print(f"Warning: preset migration error: {e}")


def _migrate_playlist_names():
    """Rename legacy system playlist files: 'Peek Themes' → 'Reveal Themes',
    'Mute Peek Themes' → 'Mute Reveal Themes'."""
    renames = [
        ("Peek Themes.json",      "Reveal Themes.json"),
        ("Mute Peek Themes.json", "Mute Reveal Themes.json"),
    ]
    for old_name, new_name in renames:
        old_path = os.path.join(PLAYLISTS_FOLDER, old_name)
        new_path = os.path.join(PLAYLISTS_FOLDER, new_name)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                os.replace(old_path, new_path)
                print(f"Migrated playlist '{old_name}' → '{new_name}'")
            except Exception as e:
                print(f"Warning: could not rename playlist '{old_name}': {e}")


def _load_popout_layout_presets():
    """Return {name: {layout: [...], columns: N}} for all saved popout layout presets."""
    presets = {}
    if not os.path.exists(POPOUT_LAYOUTS_FOLDER):
        return presets
    for fname in sorted(os.listdir(POPOUT_LAYOUTS_FOLDER)):
        if fname.endswith(".json"):
            name = fname[:-5]
            try:
                with open(os.path.join(POPOUT_LAYOUTS_FOLDER, fname), "r", encoding="utf-8") as f:
                    presets[name] = json.load(f)
            except Exception as e:
                print(f"Failed to load popout layout preset '{fname}': {e}")
    return presets


def _save_popout_layout_preset(name, layout_list, columns):
    """Write a single popout layout preset to POPOUT_LAYOUTS_FOLDER/<name>.json."""
    os.makedirs(POPOUT_LAYOUTS_FOLDER, exist_ok=True)
    path = os.path.join(POPOUT_LAYOUTS_FOLDER, f"{name}.json")
    utils._atomic_json_write(path, {"layout": layout_list, "columns": columns}, indent=4)


def save_config():
    """Function to save configuration"""
    files_folder = os.path.dirname(CONFIG_FILE)  # Get the folder path

    if not os.path.exists(files_folder):
        os.makedirs(files_folder)
    lightning_diff = utils.compute_settings_diff(lightning_settings.lightning_mode_settings_default, state.playback.lightning_mode_settings) or {}

    presets = state.settings_presets

    utils._save_settings_presets(LIGHTNING_SETTINGS_FOLDER, presets.saved_lightning_mode_settings,
                                 lightning_settings.lightning_mode_settings_default, update_fn=lightning_settings.update_lightning_mode_settings)
    utils._save_settings_presets(INFINITE_SETTINGS_FOLDER, presets.saved_infinite_settings,
                                 infinite.INFINITE_SETTINGS_DEFAULT, convert_inf=True)
    utils._save_settings_presets(BONUS_SETTINGS_FOLDER, presets.saved_bonus_settings, bonus.BONUS_SETTINGS_DEFAULT)

    config = {
        "host": state.config.host,
        **{s["config_key"]: getattr(getattr(state, s["state"]), s["key"]) for s in SETTINGS_SCHEMA},
        "color_options": state.colors.OVERLAY_COLOR_OPTIONS,
        "directory": state.config.directory,
        "lightning_mode_settings": lightning_diff,
        "selected_light_mode_settings": presets.selected_light_mode_settings,
        "selected_infinite_settings": presets.selected_infinite_settings,
        "bonus_settings": utils.compute_settings_diff(bonus.BONUS_SETTINGS_DEFAULT, state.playback.bonus_settings) or {},
        "selected_bonus_settings": presets.selected_bonus_settings,
        "popout_layout": state.popout.layout if state.popout.layout is not None else [],
        "metadata_last_updated": state.update_timestamps.metadata_last_updated,
        "censors_last_updated": state.update_timestamps.censors_last_updated,
        "popout_columns": state.popout.columns,
        "shortcuts": state.shortcuts.config,
        "playlist": state.metadata.playlist,
        "directory_files": state.metadata.directory_files,
        "tutorial_shown": state.controls.tutorial_shown,
        "set_toggles": {
            "censors_enabled": censors.censors_enabled,
            "censors_nsfw_enabled": censors.censors_nsfw_enabled,
            "auto_info_start": state.controls.auto_info_start,
            "auto_info_end": state.controls.auto_info_end,
            "auto_refresh_toggle": state.controls.auto_refresh_toggle,
            "disable_shortcuts": state.controls.disable_shortcuts,
            "progress_bar_enabled": state.controls.progress_bar_enabled,
            "autoplay_fullscreen": state.controls.autoplay_fullscreen,
            "mpv_always_on_top": state.controls.mpv_always_on_top,
            "player_collapsed": dock_player.player_collapsed,
        },
    }

    # Convert infinities and diff infinite_settings against defaults before saving
    if state.metadata.playlist.get("infinite_settings"):
        config["playlist"] = copy.deepcopy(state.metadata.playlist)
        inf_diff = utils.compute_settings_diff(infinite.INFINITE_SETTINGS_DEFAULT, config["playlist"]["infinite_settings"]) or {}
        config["playlist"]["infinite_settings"] = utils.convert_infinities_to_markers(inf_diff)

    transport.update_current_index(save=False)
    utils._atomic_json_write(CONFIG_FILE, config, indent=4, allow_nan=False)


def load_config():
    """Function to load configuration"""
    # NOTE: `playlist` and `directory_files` are intentionally NOT rebound
    # here. They are mutated in place (clear + update) so the module-level
    # aliases on main and `state.metadata.*` keep the same identity.
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            # Convert infinity markers back to float('inf')
            config = utils.convert_infinity_markers(config)
            # Load all schema settings (every entry is tagged {"state": "<cluster>"})
            _type_cast = {"int": int, "float": float, "bool": bool}
            for _s in SETTINGS_SCHEMA:
                _val = config.get(_s["config_key"], _s["default"])
                _cast = _type_cast.get(_s["type"])
                _v = _cast(_val) if _cast else _val
                setattr(getattr(state, _s["state"]), _s["key"], _v)
            state.config.host = config.get("host", "")
            _loaded_playlist = config.get("playlist", copy.deepcopy(playlist_ops.BLANK_PLAYLIST))
            state.metadata.playlist.clear()
            state.metadata.playlist.update(_loaded_playlist)
            if state.metadata.playlist.get("infinite_settings") is not None:
                def _deep_merge(base, override):
                    result = copy.deepcopy(base)
                    for k, v in override.items():
                        if isinstance(v, dict) and isinstance(result.get(k), dict):
                            result[k] = _deep_merge(result[k], v)
                        else:
                            result[k] = copy.deepcopy(v)
                    return result
                state.metadata.playlist["infinite_settings"] = _deep_merge(infinite.INFINITE_SETTINGS_DEFAULT, state.metadata.playlist["infinite_settings"])
            if "background_track_history" not in state.metadata.playlist:
                state.metadata.playlist["background_track_history"] = []
            utils._migrate_theme_flags(state.metadata.playlist.get("filter", {}))
            _loaded_directory_files = config.get("directory_files", {})
            state.metadata.directory_files.clear()
            state.metadata.directory_files.update(_loaded_directory_files)
            state.config.directory = config.get("directory", "themes")
            state.config.scoreboard_rules = scoreboard_control.load_rules(state.config.selected_rules_file)
            transport.set_rules()
            state.playback.lightning_mode_settings.clear()
            state.playback.lightning_mode_settings.update(lightning_settings.update_lightning_mode_settings(config.get("lightning_mode_settings", copy.deepcopy(lightning_settings.lightning_mode_settings_default))))
            presets = state.settings_presets
            presets.selected_light_mode_settings = config.get("selected_light_mode_settings", "")
            presets.saved_lightning_mode_settings.clear()
            presets.saved_lightning_mode_settings.update(utils.convert_infinity_markers(utils._load_settings_presets(LIGHTNING_SETTINGS_FOLDER)))

            presets.selected_infinite_settings = config.get("selected_infinite_settings", "")
            presets.saved_infinite_settings.clear()
            presets.saved_infinite_settings.update(utils.convert_infinity_markers(utils._load_settings_presets(INFINITE_SETTINGS_FOLDER)))

            presets.saved_bonus_settings.clear()
            presets.saved_bonus_settings.update(utils._load_settings_presets(BONUS_SETTINGS_FOLDER))
            for _bn, _bd in presets.saved_bonus_settings.items():
                presets.saved_bonus_settings[_bn] = utils.sync_with_default(copy.deepcopy(_bd), bonus.BONUS_SETTINGS_DEFAULT)
            state.playback.bonus_settings.clear()
            state.playback.bonus_settings.update(utils.sync_with_default(
                copy.deepcopy(config.get("bonus_settings", {})), bonus.BONUS_SETTINGS_DEFAULT
            ))
            presets.selected_bonus_settings = config.get("selected_bonus_settings", "")
            if presets.selected_bonus_settings and presets.selected_bonus_settings in presets.saved_bonus_settings:
                state.playback.bonus_settings.clear()
                state.playback.bonus_settings.update(copy.deepcopy(presets.saved_bonus_settings[presets.selected_bonus_settings]))

            state.config.inverted_colors = config.get("inverted_colors", False)
            # mpv players do not need per-load recreation
            try:
                audio_toggles.set_volume(state.controls.volume_level)
            except Exception:
                log_exception("load_config: failed to apply saved volume level")
            if presets.selected_light_mode_settings and presets.selected_light_mode_settings in presets.saved_lightning_mode_settings:
                # A named template is selected — load it (overrides the inline saved settings)
                state.playback.lightning_mode_settings.clear()
                state.playback.lightning_mode_settings.update(lightning_settings.update_lightning_mode_settings(presets.saved_lightning_mode_settings[presets.selected_light_mode_settings]))

            if presets.selected_infinite_settings and presets.selected_infinite_settings in presets.saved_infinite_settings:
                # Apply the named preset to the global template that
                # get_infinite_settings() falls back to when the current
                # playlist has no stored settings of its own.
                infinite.infinite_settings.clear()
                infinite.infinite_settings.update(utils.sync_with_default(copy.deepcopy(presets.saved_infinite_settings[presets.selected_infinite_settings]), infinite.INFINITE_SETTINGS_DEFAULT))

            if state.config.OPENAI_API_KEY:
                trivia_round.set_openai_client_key(state.config.OPENAI_API_KEY)
            metadata_fetch.set_credentials(state.config.IGDB_CLIENT_ID, state.config.IGDB_CLIENT_SECRET)
            try:
                transport.update_playlist_name()
                transport.update_current_index()
            except Exception:
                log_exception("load_config: failed to refresh playlist name/index display")
            state.colors.OVERLAY_COLOR_OPTIONS = config.get("color_options", ["black", "white"])
            state.colors.INVERSE_OVERLAY_BACKGROUND_COLOR = config.get("text_color", "white")
            state.colors.INVERSE_OVERLAY_TEXT_COLOR = config.get("back_color", "black")
            state.colors.MIDDLE_OVERLAY_BACKGROUND_COLOR = utils.interpolate_color(state.colors.OVERLAY_BACKGROUND_COLOR, state.colors.INVERSE_OVERLAY_BACKGROUND_COLOR, 0.6)
            scoreboard_control.send_colors(state.colors.OVERLAY_BACKGROUND_COLOR, state.colors.OVERLAY_TEXT_COLOR)
            state.update_timestamps.metadata_last_updated = config.get("metadata_last_updated", 0)
            state.update_timestamps.censors_last_updated = config.get("censors_last_updated", 0)
            # Popout layout — None means "use default"
            _saved_layout = config.get("popout_layout", None)
            state.popout.layout = _saved_layout if _saved_layout else None  # empty list → None (use default)
            state.popout.columns = int(config.get("popout_columns", 5))
            state.shortcuts.config.clear()
            state.shortcuts.config.update(config.get("shortcuts", {}))
            state.controls.tutorial_shown = config.get("tutorial_shown", False)
            web_server.set_host_password(state.config.HOST_PASSWORD)
            if state.config.keep_set_toggles:
                _t = config.get("set_toggles", {})
                if "censors_enabled" in _t:
                    censors.censors_enabled = bool(_t["censors_enabled"])
                if "censors_nsfw_enabled" in _t:
                    censors.censors_nsfw_enabled = bool(_t["censors_nsfw_enabled"])
                if "auto_info_start" in _t:
                    state.controls.auto_info_start = bool(_t["auto_info_start"])
                if "auto_info_end" in _t:
                    state.controls.auto_info_end = bool(_t["auto_info_end"])
                if "auto_refresh_toggle" in _t:
                    state.controls.auto_refresh_toggle = bool(_t["auto_refresh_toggle"])
                if "disable_shortcuts" in _t:
                    state.controls.disable_shortcuts = bool(_t["disable_shortcuts"])
                if "progress_bar_enabled" in _t:
                    state.controls.progress_bar_enabled = bool(_t["progress_bar_enabled"])
                if "autoplay_fullscreen" in _t:
                    state.controls.autoplay_fullscreen = bool(_t["autoplay_fullscreen"])
                if "mpv_always_on_top" in _t:
                    state.controls.mpv_always_on_top = bool(_t["mpv_always_on_top"])
                    try:
                        state.widgets.player._p.ontop = state.controls.mpv_always_on_top
                    except Exception:
                        pass
                if _t.get("player_collapsed") and not dock_player.player_collapsed:
                    state.controls.pending_restore_collapsed = True
    except Exception as e:
        log_exception("Error loading config from %s", CONFIG_FILE)
        _backup_broken_config(e)
        return False
    return False
