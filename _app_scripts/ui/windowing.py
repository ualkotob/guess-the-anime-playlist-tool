"""Window positioning helpers shared by Tk popup modules."""

from core.game_state import state


def move_root_to_bottom(toggle=True):
    """Move the Tk root window to the bottom-center of the screen."""
    # Lazy import: windowing is a low-level UI helper pulled in by many of the
    # popup modules that information_popup imports, so reach it at call time.
    import _app_scripts.information.information_popup as information_popup
    root = state.widgets.root
    root.update_idletasks()

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    window_width = root.winfo_width()
    window_height = root.winfo_height()

    taskbar_height = 0
    y_position = screen_height - window_height - taskbar_height
    x_position = screen_width / 2 - window_width / 2 - taskbar_height

    y_position = max(0, y_position)
    x_position = int(max(0, x_position))

    if not toggle:
        root.after(1, lambda: information_popup.animate_window(root, x_position, screen_height))
    else:
        root.geometry(f"+{x_position}+{screen_height}")
        root.after(10, lambda: information_popup.animate_window(root, x_position, y_position - 30))


def is_docked():
    return state.widgets.root.attributes("-topmost")


def popup_menu(menu, x, y):
    """Show a tk.Menu at (x, y), keeping it visible while the player is docked."""
    root = state.widgets.root
    docked = is_docked()
    if docked:
        root.attributes("-topmost", False)
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()
        if docked:
            root.attributes("-topmost", True)


def get_window_position_and_setup(window=None, set_topmost_if_docked=True, offset_x=0, offset_y=0):
    """Return root position and optionally place/configure a child window."""
    root = state.widgets.root
    root.update_idletasks()
    x = root.winfo_x() + offset_x
    y = root.winfo_y() + offset_y

    if window:
        window.update_idletasks()
        window.geometry(f"+{x}+{y}")

        if set_topmost_if_docked and is_docked():
            window.attributes("-topmost", True)

        window.lift()
        window.focus_force()

    return (x, y)
