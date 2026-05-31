"""DOCK PLAYER — extracted from guess_the_anime.py.

Two window-state actions on the main Tk root:
    toggle_player_collapse  — hide/show the info panel (▼/▲ button), shrinks
                              the window height accordingly.
    dock_player             — "DOCK" toggle: pins window to bottom-left,
                              80% alpha, topmost. Untoggle restores.

State owned (all rebound at runtime — external readers must qualify through
this module, NOT via stale main-side aliases):
    undock_position          previous (x,y) before dock
    dock_was_minimized       was the window iconified when we docked?
    player_collapsed         currently collapsed?
    original_window_height   saved height to restore on uncollapse
    original_min_height      saved min-height to restore on uncollapse

Uses the `_main` module-reference pattern. `windowing` imported directly.
"""

from ..ui import windowing


_main = None


def set_context(*, main_module):
    global _main
    _main = main_module


# --- State ---
undock_position = []
dock_was_minimized = False
player_collapsed = False
original_window_height = None
original_min_height = None


def toggle_player_collapse():
    """Collapses or expands the player info columns."""
    global player_collapsed, original_window_height, original_min_height

    root = _main.root
    info_panel = _main.info_panel
    first_row_frame = _main.first_row_frame
    collapse_button = _main.collapse_button
    scl = _main.scl

    player_collapsed = not player_collapsed

    if player_collapsed:
        if original_window_height is None:
            original_window_height = root.winfo_height()
            original_min_height = root.minsize()[1]

        info_panel_height = info_panel.winfo_height()

        info_panel.pack_forget()

        root.update_idletasks()

        new_height = original_window_height - info_panel_height
        new_min_height = original_min_height - info_panel_height
        root.minsize(scl(900, "UI"), new_min_height)
        root.geometry(f"{root.winfo_width()}x{new_height}")

        if windowing.is_docked():
            windowing.move_root_to_bottom()

        collapse_button.config(text="▲")
    else:
        info_panel.pack(after=first_row_frame, fill="both", expand=True, padx=scl(10, "UI"), pady=scl(5, "UI"))

        if original_window_height is not None:
            root.geometry(f"{root.winfo_width()}x{original_window_height}")
        if original_min_height is not None:
            root.minsize(scl(900, "UI"), original_min_height)

        if windowing.is_docked():
            windowing.move_root_to_bottom()

        collapse_button.config(text="▼")


def dock_player():
    """Toggles the Tkinter window between front and back, moves it to bottom left,
    adjusts transparency, and removes the title bar when brought forward."""
    global undock_position, dock_was_minimized

    root = _main.root
    dock_button = _main.dock_button
    right_top = _main.right_top

    _main.button_seleted(dock_button, not windowing.is_docked())
    if windowing.is_docked():
        root.attributes("-topmost", False)
        root.attributes("-alpha", 1.0)
        if not _main.disable_shortcuts:
            windowing.move_root_to_bottom(False)
        elif undock_position[1] < root.winfo_y():
            root.after(10, lambda: root.geometry(f"+{undock_position[0]}+{undock_position[1]}"))
        if dock_was_minimized:
            dock_was_minimized = False
            root.iconify()
    else:
        dock_was_minimized = root.state() == 'iconic'
        if dock_was_minimized:
            root.deiconify()
        import tkinter as tk
        right_top.delete(1.0, tk.END)
        undock_position = (root.winfo_x(), root.winfo_y())
        root.attributes("-alpha", 0.8)
        root.attributes("-topmost", True)
        windowing.move_root_to_bottom()
        root.lift()
    _main.up_next_text()
    if _main.list_loaded:
        _main.refresh_current_list()
