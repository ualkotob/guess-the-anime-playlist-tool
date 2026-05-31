"""Autoplay and related playback-window toggle commands."""

from core.game_state import state

_ctx = {}


def set_context(
    *,
    player,
    root,
    tk,
    popup_menu,
    save_config,
    highlight_color,
    sync_legacy_globals=None,
    get_autoplay_button=None,
):
    _ctx.clear()
    _ctx.update(locals())


def _get_state(name, default=None):
    return getattr(state.controls, name, default)


def _set_state(name, value):
    setattr(state.controls, name, value)
    sync_legacy_globals = _ctx.get("sync_legacy_globals")
    if sync_legacy_globals:
        sync_legacy_globals()


def _get_autoplay_button():
    get_autoplay_button = _ctx.get("get_autoplay_button")
    return get_autoplay_button() if get_autoplay_button else None


def toggle_mpv_always_on_top():
    value = not bool(_get_state("mpv_always_on_top", False))
    _set_state("mpv_always_on_top", value)
    try:
        _ctx["player"]._p.ontop = value
    except Exception:
        pass
    _ctx["save_config"]()


def toggle_autoplay_fullscreen():
    value = not bool(_get_state("autoplay_fullscreen", True))
    _set_state("autoplay_fullscreen", value)
    try:
        _ctx["player"].set_fullscreen(value)
    except Exception:
        pass
    _ctx["save_config"]()


def update_autoplay_button():
    button = _get_autoplay_button()
    if button is None:
        return

    autoplay_toggle = _get_state("autoplay_toggle", 0)
    special_repeat_track_mode = _get_state("special_repeat_track_mode", False)

    if special_repeat_track_mode:
        button.configure(text="🔂", fg="green")
    elif autoplay_toggle == 0:
        button.configure(text="🔁", fg="white")
    elif autoplay_toggle == 1:
        button.configure(text="🔂", fg="white")
    elif autoplay_toggle == 2:
        button.configure(text="🔁", fg=_ctx["highlight_color"])
    elif autoplay_toggle == 3:
        button.configure(text="❌", fg="red")


def set_autoplay_mode(mode):
    _set_state("special_repeat_track_mode", False)
    _set_state("autoplay_toggle", mode)
    update_autoplay_button()


def toggle_autoplay():
    if _get_state("special_repeat_track_mode", False):
        toggle_special_repeat()
        return

    autoplay_toggle = _get_state("autoplay_toggle", 0) + 1
    if autoplay_toggle == 4:
        autoplay_toggle = 0
    _set_state("autoplay_toggle", autoplay_toggle)
    update_autoplay_button()


def show_autoplay_menu(event=None):
    toggle_autoplay()  # advance to next mode on every left-click

    tk = _ctx["tk"]
    root = _ctx["root"]
    autoplay_toggle = _get_state("autoplay_toggle", 0)
    special_repeat_track_mode = _get_state("special_repeat_track_mode", False)
    highlight_color = _ctx["highlight_color"]

    menu = tk.Menu(
        root,
        tearoff=0,
        bg="black",
        fg="white",
        activebackground=highlight_color,
        activeforeground="white",
        font=("Arial", 11),
    )
    menu.add_command(
        label="🔁 AUTOPLAY: Advance to next track when video ends.",
        command=lambda: set_autoplay_mode(0),
        foreground="white",
        background=highlight_color
        if autoplay_toggle == 0 and not special_repeat_track_mode
        else "black",
    )
    menu.add_command(
        label="🔂 SINGLE REPEAT: Replay current track when it ends.",
        command=lambda: set_autoplay_mode(1),
        foreground="white",
        background=highlight_color
        if autoplay_toggle == 1 and not special_repeat_track_mode
        else "black",
    )
    menu.add_command(
        label="🔁 DISABLE AUTOPLAY: Don't advance to the next track when the video ends.",
        command=lambda: set_autoplay_mode(2),
        foreground="white",
        background=highlight_color
        if autoplay_toggle == 2 and not special_repeat_track_mode
        else "black",
    )
    menu.add_command(
        label="❌ MANUAL  —  Video loads but does not play automatically. Use ⏯ to play.",
        command=lambda: set_autoplay_mode(3),
        foreground="white",
        background=highlight_color
        if autoplay_toggle == 3 and not special_repeat_track_mode
        else "black",
    )
    menu.add_separator()
    menu.add_command(
        label=("✅" if special_repeat_track_mode else "  ")
        + "🔂 SPECIAL REPEAT: Replay indefinitely until manually skipped.",
        command=toggle_special_repeat,
        foreground="white",
        background=highlight_color if special_repeat_track_mode else "black",
    )
    menu.update_idletasks()

    button = _get_autoplay_button()
    if button is None:
        return
    x = button.winfo_rootx()
    y = button.winfo_rooty() - menu.winfo_reqheight() - 5
    _ctx["popup_menu"](menu, x, y)


def toggle_special_repeat(event=None):
    """Toggle special repeat-track mode. Cleared when play_next is called."""
    special_repeat_track_mode = not bool(_get_state("special_repeat_track_mode", False))
    _set_state("special_repeat_track_mode", special_repeat_track_mode)
    _set_state("autoplay_toggle", 1 if special_repeat_track_mode else 0)
    update_autoplay_button()
