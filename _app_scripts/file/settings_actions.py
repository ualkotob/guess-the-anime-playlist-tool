"""Configured actions that open the app's settings editors."""

import copy


_ctx = {}


def set_context(
    *,
    open_generic_settings_editor,
    save_config,
    push_web_toggles,
    sync_with_default,
    get_lightning_settings,
    get_lightning_defaults,
    get_saved_lightning_settings,
    get_selected_lightning_settings,
    set_selected_lightning_settings,
    get_infinite_settings,
    get_infinite_defaults,
    get_saved_infinite_settings,
    get_selected_infinite_settings,
    set_selected_infinite_settings,
    is_infinite_playlist_active,
    refetch_pop_time_groups,
    clear_infinite_caches,
    get_bonus_settings,
    get_bonus_defaults,
    get_saved_bonus_settings,
    get_selected_bonus_settings,
    set_selected_bonus_settings,
):
    _ctx.clear()
    _ctx.update(locals())


def open_settings_editor():
    """Open lightning mode settings editor."""
    def on_apply(new_settings, selected_name):
        _ctx["set_selected_lightning_settings"](selected_name)
        _ctx["push_web_toggles"]()

    _ctx["open_generic_settings_editor"](
        title="Lightning Mode Settings Editor",
        current_settings_dict=_ctx["get_lightning_settings"](),
        default_settings_dict=_ctx["get_lightning_defaults"](),
        saved_settings_dict=_ctx["get_saved_lightning_settings"](),
        selected_setting_name=_ctx["get_selected_lightning_settings"](),
        on_apply_callback=on_apply,
        on_save_config_callback=_ctx["save_config"],
    )


def open_infinite_settings_editor():
    """Open infinite playlist settings editor."""
    active_settings = _ctx["get_infinite_settings"]()

    def on_apply(new_settings, selected_name):
        _ctx["set_selected_infinite_settings"](selected_name)
        if _ctx["is_infinite_playlist_active"]():
            _ctx["refetch_pop_time_groups"]()
        _ctx["clear_infinite_caches"]()

    _ctx["open_generic_settings_editor"](
        title="Infinite Playlist Settings Editor",
        current_settings_dict=active_settings,
        default_settings_dict=_ctx["get_infinite_defaults"](),
        saved_settings_dict=_ctx["get_saved_infinite_settings"](),
        selected_setting_name=_ctx["get_selected_infinite_settings"](),
        on_apply_callback=on_apply,
        on_save_config_callback=_ctx["save_config"],
    )


def open_bonus_settings_editor():
    """Open bonus round settings editor."""
    bonus_settings = _ctx["get_bonus_settings"]()
    bonus_defaults = _ctx["get_bonus_defaults"]()
    sync_with_default = _ctx["sync_with_default"]

    if not bonus_settings:
        bonus_settings.clear()
        bonus_settings.update(copy.deepcopy(bonus_defaults))
    synced = sync_with_default(copy.deepcopy(bonus_settings), bonus_defaults)
    bonus_settings.clear()
    bonus_settings.update(synced)

    def on_apply(new_settings, selected_name):
        _ctx["set_selected_bonus_settings"](selected_name)
        synced = sync_with_default(copy.deepcopy(new_settings), bonus_defaults)
        bonus_settings.clear()
        bonus_settings.update(synced)
        _ctx["push_web_toggles"]()

    _ctx["open_generic_settings_editor"](
        title="Bonus Round Settings Editor",
        current_settings_dict=bonus_settings,
        default_settings_dict=bonus_defaults,
        saved_settings_dict=_ctx["get_saved_bonus_settings"](),
        selected_setting_name=_ctx["get_selected_bonus_settings"](),
        on_apply_callback=on_apply,
        on_save_config_callback=_ctx["save_config"],
    )
