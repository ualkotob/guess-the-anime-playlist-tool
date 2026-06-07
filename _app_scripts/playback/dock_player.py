"""Dock player — window-state actions on the main Tk root.

    toggle_player_collapse  — hide/show the info panel (▼/▲ button), shrinks
                              the window height accordingly.
    dock_player             — "DOCK" toggle: pins window to bottom-left,
                              80% alpha, topmost. Untoggle restores.

State owned (rebound at runtime — read it through this module, never cache):
    undock_position          previous (x,y) before dock
    dock_was_minimized       was the window iconified when we docked?
    player_collapsed         currently collapsed?
    original_window_height   saved height to restore on uncollapse
    original_min_height      saved min-height to restore on uncollapse
"""

from ..ui import windowing, lists
from ..ui.scaling import scl
from ..file.metadata import metadata_display
from core.game_state import state


# --- State ---
undock_position = []
dock_was_minimized = False
player_collapsed = False
original_window_height = None
original_min_height = None


def toggle_player_collapse():
    """Collapses or expands the player info columns."""
    global player_collapsed, original_window_height, original_min_height

    root = state.widgets.root
    info_panel = state.widgets.info_panel
    first_row_frame = state.widgets.first_row_frame
    collapse_button = state.widgets.collapse_button

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

    root = state.widgets.root
    dock_button = state.widgets.dock_button
    right_top = state.widgets.right_top

    lists.button_seleted(dock_button, not windowing.is_docked())
    if windowing.is_docked():
        root.attributes("-topmost", False)
        root.attributes("-alpha", 1.0)
        if not state.controls.disable_shortcuts:
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
    metadata_display.up_next_text()
    if state.lists.list_loaded:
        lists.refresh_current_list()
