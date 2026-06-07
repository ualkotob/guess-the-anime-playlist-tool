"""Configured actions that open the app's settings editors."""

import copy

from core.game_state import state
import _app_scripts.bonus.bonus as bonus
import _app_scripts.bonus.answers as bonus_answers
import _app_scripts.queue_round.lightning_rounds.lightning_settings as lightning_settings
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.file.generic_settings_editor as generic_settings_editor
import _app_scripts.data.config_io as config_io
import _app_scripts.utils as utils


def open_settings_editor():
    """Open lightning mode settings editor."""
    def on_apply(new_settings, selected_name):
        state.settings_presets.selected_light_mode_settings = selected_name
        bonus_answers._push_web_toggles()

    generic_settings_editor.open_generic_settings_editor(
        title="Lightning Mode Settings Editor",
        current_settings_dict=state.playback.lightning_mode_settings,
        default_settings_dict=lightning_settings.lightning_mode_settings_default,
        saved_settings_dict=state.settings_presets.saved_lightning_mode_settings,
        selected_setting_name=state.settings_presets.selected_light_mode_settings,
        on_apply_callback=on_apply,
        on_save_config_callback=config_io.save_config,
    )


def open_infinite_settings_editor():
    """Open infinite playlist settings editor."""
    active_settings = playlist_ops.get_infinite_settings()

    def on_apply(new_settings, selected_name):
        state.settings_presets.selected_infinite_settings = selected_name
        if state.metadata.playlist.get("infinite", False):
            playlist_ops.get_pop_time_groups(refetch=True)
        playlist_ops.reset_infinite_caches()

    generic_settings_editor.open_generic_settings_editor(
        title="Infinite Playlist Settings Editor",
        current_settings_dict=active_settings,
        default_settings_dict=playlist_ops.INFINITE_SETTINGS_DEFAULT,
        saved_settings_dict=state.settings_presets.saved_infinite_settings,
        selected_setting_name=state.settings_presets.selected_infinite_settings,
        on_apply_callback=on_apply,
        on_save_config_callback=config_io.save_config,
    )


def open_bonus_settings_editor():
    """Open bonus round settings editor."""
    bonus_settings = state.playback.bonus_settings
    bonus_defaults = bonus.BONUS_SETTINGS_DEFAULT
    sync_with_default = utils.sync_with_default

    if not bonus_settings:
        bonus_settings.clear()
        bonus_settings.update(copy.deepcopy(bonus_defaults))
    synced = sync_with_default(copy.deepcopy(bonus_settings), bonus_defaults)
    bonus_settings.clear()
    bonus_settings.update(synced)

    def on_apply(new_settings, selected_name):
        state.settings_presets.selected_bonus_settings = selected_name
        synced = sync_with_default(copy.deepcopy(new_settings), bonus_defaults)
        bonus_settings.clear()
        bonus_settings.update(synced)
        bonus_answers._push_web_toggles()

    generic_settings_editor.open_generic_settings_editor(
        title="Bonus Round Settings Editor",
        current_settings_dict=bonus_settings,
        default_settings_dict=bonus_defaults,
        saved_settings_dict=state.settings_presets.saved_bonus_settings,
        selected_setting_name=state.settings_presets.selected_bonus_settings,
        on_apply_callback=on_apply,
        on_save_config_callback=config_io.save_config,
    )
