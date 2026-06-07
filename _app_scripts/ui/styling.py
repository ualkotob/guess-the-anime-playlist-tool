"""Shared ttk style definitions.

`configure_style()` (re)applies the dark "Black.TCombobox" combobox style used
across the app's ttk.Combobox widgets (playlist season pickers, popout
dropdowns, menu builder dropdowns). It is called once at startup and again after
theme changes so the combobox styling survives a `style.theme_use(...)` reset.

ttk styles live in a single per-interpreter database keyed by the default Tk
root, so a fresh `ttk.Style()` handle here mutates the very same named styles the
rest of the app reads — there is no need to share one Style instance. The
function only runs after the root window exists (startup + theme-change paths),
which is when `ttk.Style()` is valid.
"""
from tkinter import ttk

from _app_scripts.ui.scaling import scl


def configure_style():
    """Apply the dark combobox styling for the "Black.TCombobox" ttk style."""
    style = ttk.Style()
    style.configure("Black.TCombobox",
                    fieldbackground="black",   # background of selected value
                    background="black",        # dropdown arrow area
                    foreground="white",        # text color
                    arrowcolor="white",        # arrow color
                    justify='center')

    # Also style the readonly state explicitly
    style.map("Black.TCombobox",
        fieldbackground=[('readonly', 'black')],
        foreground=[('readonly', 'white')]
    )


def configure_list_scrollbar_style():
    """Build the fully styled "List.Vertical.TScrollbar" for the list display.

    Native tk.Scrollbar ignores colors on Windows, so this borrows clam's
    trough/thumb/arrow elements into a custom layout that honors background,
    trough, and arrow colors. Called once at GUI build time (the right-column
    scrollbar is created right after).
    """
    style = ttk.Style()
    style.element_create("List.trough", "from", "clam")
    style.element_create("List.thumb", "from", "clam")
    style.element_create("List.uparrow", "from", "clam")
    style.element_create("List.downarrow", "from", "clam")
    style.layout("List.Vertical.TScrollbar", [
        ("List.trough", {"sticky": "ns", "children": [
            ("List.uparrow",   {"side": "top",    "sticky": ""}),
            ("List.downarrow", {"side": "bottom", "sticky": ""}),
            ("List.thumb",     {"unit": "1",      "sticky": "nswe"}),
        ]})
    ])
    style.configure("List.Vertical.TScrollbar",
        background="gray38", troughcolor="gray15",
        arrowcolor="gray65", borderwidth=0,
        gripcount=0, arrowsize=scl(13, "UI"))
    style.map("List.Vertical.TScrollbar",
        background=[("active", "gray58"), ("pressed", "gray68")])
