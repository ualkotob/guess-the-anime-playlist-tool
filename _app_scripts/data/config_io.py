"""Config file I/O — save_config / load_config plus one-time migrations and
popout-layout preset I/O.

Cross-module references go through `_main.X`; set_context binds it.

This module is unusually heavy on `_main.` prefixes because save_config /
load_config touch ~30 cross-cutting globals on the main module (loaded
dynamically against SETTINGS_SCHEMA via setattr/getattr). Per
[[state-stays-with-its-readers]] those globals stay in main and are reached
through the main_module reference rather than being relocated here.
"""
import os
import json
import copy
from datetime import datetime

from _app_scripts import utils
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

_main = None  # populated by set_context()


def set_context(*, main_module):
    global _main
    _main = main_module


_atomic_json_write = utils._atomic_json_write


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
    if hasattr(_main, "_sync_control_state_from_globals"):
        _main._sync_control_state_from_globals()
    files_folder = os.path.dirname(CONFIG_FILE)  # Get the folder path

    if not os.path.exists(files_folder):
        os.makedirs(files_folder)
    lightning_diff = utils.compute_settings_diff(_main.lightning_mode_settings_default, _main.lightning_mode_settings) or {}

    utils._save_settings_presets(LIGHTNING_SETTINGS_FOLDER, _main.saved_lightning_mode_settings,
                                 _main.lightning_mode_settings_default, update_fn=_main.update_lightning_mode_settings)
    utils._save_settings_presets(INFINITE_SETTINGS_FOLDER, _main.saved_infinite_settings,
                                 _main.INFINITE_SETTINGS_DEFAULT, convert_inf=True)
    utils._save_settings_presets(BONUS_SETTINGS_FOLDER, _main.saved_bonus_settings, _main.BONUS_SETTINGS_DEFAULT)

    config = {
        "host": _main.host,
        **{s["config_key"]: getattr(_main, s["key"]) for s in _main.SETTINGS_SCHEMA},
        "color_options": _main.OVERLAY_COLOR_OPTIONS,
        "directory": _main.directory,
        "lightning_mode_settings": lightning_diff,
        "selected_light_mode_settings": _main.selected_light_mode_settings,
        "selected_infinite_settings": _main.selected_infinite_settings,
        "bonus_settings": utils.compute_settings_diff(_main.BONUS_SETTINGS_DEFAULT, _main.bonus_settings) or {},
        "selected_bonus_settings": _main.selected_bonus_settings,
        "popout_layout": _main.popout_layout if _main.popout_layout is not None else [],
        "metadata_last_updated": _main.metadata_last_updated,
        "censors_last_updated": _main.censors_last_updated,
        "popout_columns": _main.popout_columns,
        "shortcuts": getattr(_main, "shortcuts_config", {}),
        "playlist": _main.playlist,
        "directory_files": _main.directory_files,
        "tutorial_shown": getattr(_main, "tutorial_shown", False),
        "set_toggles": {
            "censors_enabled": _main.censors.censors_enabled,
            "censors_nsfw_enabled": _main.censors.censors_nsfw_enabled,
            "auto_info_start": _main.auto_info_start,
            "auto_info_end": _main.auto_info_end,
            "auto_refresh_toggle": _main.auto_refresh_toggle,
            "disable_shortcuts": _main.disable_shortcuts,
            "progress_bar_enabled": _main.progress_bar_enabled,
            "autoplay_fullscreen": state.controls.autoplay_fullscreen,
            "mpv_always_on_top": state.controls.mpv_always_on_top,
            "player_collapsed": _main.dock_player_mod.player_collapsed,
        },
    }

    # Convert infinities and diff infinite_settings against defaults before saving
    if _main.playlist.get("infinite_settings"):
        config["playlist"] = copy.deepcopy(_main.playlist)
        inf_diff = utils.compute_settings_diff(_main.INFINITE_SETTINGS_DEFAULT, config["playlist"]["infinite_settings"]) or {}
        config["playlist"]["infinite_settings"] = utils.convert_infinities_to_markers(inf_diff)

    _main.update_current_index(save=False)
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
            # Load all schema settings
            _type_cast = {"int": int, "float": float, "bool": bool}
            for _s in _main.SETTINGS_SCHEMA:
                _val = config.get(_s["config_key"], _s["default"])
                _cast = _type_cast.get(_s["type"])
                setattr(_main, _s["key"], _cast(_val) if _cast else _val)
            if hasattr(_main, "_sync_control_state_from_globals"):
                _main._sync_control_state_from_globals()
            _main.host = config.get("host", "")
            _loaded_playlist = config.get("playlist", copy.deepcopy(_main.BLANK_PLAYLIST))
            _main.playlist.clear()
            _main.playlist.update(_loaded_playlist)
            if _main.playlist.get("infinite_settings") is not None:
                def _deep_merge(base, override):
                    result = copy.deepcopy(base)
                    for k, v in override.items():
                        if isinstance(v, dict) and isinstance(result.get(k), dict):
                            result[k] = _deep_merge(result[k], v)
                        else:
                            result[k] = copy.deepcopy(v)
                    return result
                _main.playlist["infinite_settings"] = _deep_merge(_main.INFINITE_SETTINGS_DEFAULT, _main.playlist["infinite_settings"])
            if "background_track_history" not in _main.playlist:
                _main.playlist["background_track_history"] = []
            utils._migrate_theme_flags(_main.playlist.get("filter", {}))
            _loaded_directory_files = config.get("directory_files", {})
            _main.directory_files.clear()
            _main.directory_files.update(_loaded_directory_files)
            _main.directory = config.get("directory", "themes")
            _main.scoreboard_rules = _main.load_rules(_main.selected_rules_file)
            _main.set_rules()
            _main.lightning_mode_settings.clear()
            _main.lightning_mode_settings.update(_main.update_lightning_mode_settings(config.get("lightning_mode_settings", copy.deepcopy(_main.lightning_mode_settings_default))))
            _main.selected_light_mode_settings = config.get("selected_light_mode_settings", "")
            _main.saved_lightning_mode_settings = utils.convert_infinity_markers(utils._load_settings_presets(LIGHTNING_SETTINGS_FOLDER))

            _main.selected_infinite_settings = config.get("selected_infinite_settings", "")
            _main.saved_infinite_settings = utils.convert_infinity_markers(utils._load_settings_presets(INFINITE_SETTINGS_FOLDER))

            _main.saved_bonus_settings = utils._load_settings_presets(BONUS_SETTINGS_FOLDER)
            for _bn, _bd in _main.saved_bonus_settings.items():
                _main.saved_bonus_settings[_bn] = utils.sync_with_default(copy.deepcopy(_bd), _main.BONUS_SETTINGS_DEFAULT)
            _main.bonus_settings.clear()
            _main.bonus_settings.update(utils.sync_with_default(
                copy.deepcopy(config.get("bonus_settings", {})), _main.BONUS_SETTINGS_DEFAULT
            ))
            _main.selected_bonus_settings = config.get("selected_bonus_settings", "")
            if _main.selected_bonus_settings and _main.selected_bonus_settings in _main.saved_bonus_settings:
                _main.bonus_settings.clear()
                _main.bonus_settings.update(copy.deepcopy(_main.saved_bonus_settings[_main.selected_bonus_settings]))

            _main.inverted_colors = config.get("inverted_colors", False)
            # mpv players do not need per-load recreation
            try:
                _main.set_volume(state.controls.volume_level)
            except Exception:
                pass
            if _main.selected_light_mode_settings and _main.selected_light_mode_settings in _main.saved_lightning_mode_settings:
                # A named template is selected — load it (overrides the inline saved settings)
                _main.lightning_mode_settings.clear()
                _main.lightning_mode_settings.update(_main.update_lightning_mode_settings(_main.saved_lightning_mode_settings[_main.selected_light_mode_settings]))

            if _main.selected_infinite_settings and _main.selected_infinite_settings in _main.saved_infinite_settings:
                _main.infinite_settings.clear()
                _main.infinite_settings.update(utils.sync_with_default(copy.deepcopy(_main.saved_infinite_settings[_main.selected_infinite_settings]), _main.INFINITE_SETTINGS_DEFAULT))

            if _main.OPENAI_API_KEY:
                _main.set_openai_client_key(_main.OPENAI_API_KEY)
            _main.metadata_fetch.set_credentials(_main.IGDB_CLIENT_ID, _main.IGDB_CLIENT_SECRET)
            _main.cache_download.update_settings(
                themes_cache_size=_main.themes_cache_size,
                auto_download_themes=_main.auto_download_themes,
                app_version=_main.APP_VERSION,
            )
            _main.streaming.update_settings(youtube_api_key=_main.YOUTUBE_API_KEY)
            try:
                _main.update_playlist_name()
                _main.update_current_index()
            except Exception:
                pass
            _main.OVERLAY_COLOR_OPTIONS = config.get("color_options", ["black", "white"])
            _main.INVERSE_OVERLAY_BACKGROUND_COLOR = config.get("text_color", "white")
            _main.INVERSE_OVERLAY_TEXT_COLOR = config.get("back_color", "black")
            _main.MIDDLE_OVERLAY_BACKGROUND_COLOR = utils.interpolate_color(_main.OVERLAY_BACKGROUND_COLOR, _main.INVERSE_OVERLAY_BACKGROUND_COLOR, 0.6)
            _main.send_scoreboard_colors()
            _main.metadata_last_updated = config.get("metadata_last_updated", 0)
            _main.censors_last_updated = config.get("censors_last_updated", 0)
            # Popout layout — None means "use default"
            _saved_layout = config.get("popout_layout", None)
            _main.popout_layout = _saved_layout if _saved_layout else None  # empty list → None (use default)
            _main.popout_columns = int(config.get("popout_columns", 5))
            _main.shortcuts_config = config.get("shortcuts", {})
            _main.tutorial_shown = config.get("tutorial_shown", False)
            _main.web_server.set_host_password(_main.HOST_PASSWORD)
            if _main.keep_set_toggles:
                _t = config.get("set_toggles", {})
                if "censors_enabled" in _t:
                    _main.censors.censors_enabled = bool(_t["censors_enabled"])
                if "censors_nsfw_enabled" in _t:
                    _main.censors.censors_nsfw_enabled = bool(_t["censors_nsfw_enabled"])
                if "auto_info_start" in _t:
                    _main.auto_info_start = bool(_t["auto_info_start"])
                if "auto_info_end" in _t:
                    _main.auto_info_end = bool(_t["auto_info_end"])
                if "auto_refresh_toggle" in _t:
                    _main.auto_refresh_toggle = bool(_t["auto_refresh_toggle"])
                if "disable_shortcuts" in _t:
                    _main.disable_shortcuts = bool(_t["disable_shortcuts"])
                if "progress_bar_enabled" in _t:
                    _main.progress_bar_enabled = bool(_t["progress_bar_enabled"])
                if "autoplay_fullscreen" in _t:
                    state.controls.autoplay_fullscreen = bool(_t["autoplay_fullscreen"])
                    _main.autoplay_fullscreen = state.controls.autoplay_fullscreen
                if "mpv_always_on_top" in _t:
                    state.controls.mpv_always_on_top = bool(_t["mpv_always_on_top"])
                    _main.mpv_always_on_top = state.controls.mpv_always_on_top
                    try:
                        _main.player._p.ontop = state.controls.mpv_always_on_top
                    except Exception:
                        pass
                if _t.get("player_collapsed") and not _main.dock_player_mod.player_collapsed:
                    setattr(_main, "_pending_restore_collapsed", True)
    except Exception as e:
        log_exception("Error loading config from %s", CONFIG_FILE)
        _backup_broken_config(e)
        return False
    return False
