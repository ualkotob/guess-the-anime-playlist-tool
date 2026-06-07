"""Application close/teardown.

`on_app_close()` is the single app-shutdown entry point, reached both from the
root window's WM_DELETE_WINDOW protocol (wired in _main) and the menu registry's
EXIT button. It reads every collaborator off `state` / sibling modules directly,
so it needs no set_context injection.
"""

from core.game_state import state
import _app_scripts.ui.menu_builder as menu_builder
import _app_scripts.data.config_io as config_io
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.file.web_server.web_server as web_server


def on_app_close():
    """Safely destroy hidden root-parented widgets before closing to avoid TclError."""
    root = state.widgets.root
    # Cancel any pending tooltip after() callback so it can't fire on a destroyed widget
    menu_builder.dismiss_menu_tooltip()

    widget = state.playlist_ui.difficulty_dropdown
    if widget is not None:
        try:
            widget.unbind_all("<<ComboboxSelected>>")
            widget.destroy()
        except Exception:
            pass
    # quit() exits the mainloop cleanly before destroy() tears down the widgets
    try:
        web_server.stop()
    except Exception:
        pass
    try:
        config_io.save_config()
    except Exception:
        pass
    if state.config.AUTO_EXIT_SCOREBOARD and scoreboard_control.is_running():
        scoreboard_control.send_command("quit")
    try:
        root.quit()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
