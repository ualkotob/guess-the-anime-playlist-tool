# Configuration settings popup.
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from core.game_state import state
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.data.config_io as config_io
import _app_scripts.ui.windowing as windowing
import _app_scripts.file.tooltip as tooltip
import _app_scripts.file.web_server.web_server as web_server

BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR

# Module-private window state (was a main-file global)
settings_window = None


def _get_setting_value(setting):
    """Read a schema setting's live value from its state cluster.

    Every SETTINGS_SCHEMA entry is tagged {"state": "<cluster>"}, so the value
    always lives at state.<cluster>.<key> (same dispatch config_io load/save use).
    """
    return getattr(getattr(state, setting["state"]), setting["key"])


def _set_setting_value(setting, value):
    """Write a schema setting's value back to its state cluster."""
    setattr(getattr(state, setting["state"]), setting["key"], value)


def show_settings_popup():
    """Opens a settings popup for editing configuration values."""
    global settings_window
    root = state.widgets.root

    if settings_window and settings_window.winfo_exists():
        try:
            settings_window.destroy()
        except tk.TclError:
            pass
        settings_window = None

    def is_valid_color(color):
        if not color:
            return False
        if color.startswith('#'):
            hex_part = color[1:]
            if len(hex_part) in (3, 6):
                try:
                    int(hex_part, 16)
                    return True
                except ValueError:
                    return False
            return False
        try:
            test_frame = tk.Frame(settings_window, bg=color)
            test_frame.destroy()
            return True
        except tk.TclError:
            return False

    def add_color(color_var, dropdown):
        new_color = simpledialog.askstring("Add Color",
            "Enter color name or hex code:\n\n"
            "Examples:\n"
            "• Color names: darkblue, lightgreen, gold\n"
            "• Hex codes: #FF5733, #00FF00, #123ABC")
        if new_color:
            new_color = new_color.strip()
            if new_color in state.colors.OVERLAY_COLOR_OPTIONS:
                messagebox.showinfo("Color Already Exists", f"'{new_color}' is already in the color list.")
                return
            if is_valid_color(new_color):
                state.colors.OVERLAY_COLOR_OPTIONS.append(new_color)
                dropdown['values'] = state.colors.OVERLAY_COLOR_OPTIONS
                color_var.set(new_color)
            else:
                messagebox.showerror("Invalid Color",
                    f"'{new_color}' is not a valid color.\n\n"
                    "Please use:\n"
                    "• Valid color names (red, blue, darkgreen, etc.)\n"
                    "• Valid hex codes (#FF5733, #00FF00, etc.)")

    def delete_color(color_var, back_dd, text_dd):
        current_color = color_var.get()
        if not current_color:
            messagebox.showwarning("No Color Selected", "Please select a color to delete.")
            return
        default_colors = ["black", "white", "red", "green", "blue", "yellow", "cyan", "magenta",
                          "gray", "orange", "purple", "pink", "brown", "lime", "navy", "maroon"]
        if current_color in default_colors:
            messagebox.showwarning("Cannot Delete", f"'{current_color}' is a default color and cannot be deleted.")
            return
        if not messagebox.askyesno("Delete Color", f"Delete '{current_color}' from the color list?"):
            return
        if current_color in state.colors.OVERLAY_COLOR_OPTIONS:
            state.colors.OVERLAY_COLOR_OPTIONS.remove(current_color)
            back_dd['values'] = state.colors.OVERLAY_COLOR_OPTIONS
            text_dd['values'] = state.colors.OVERLAY_COLOR_OPTIONS
            color_var.set("black")

    def _schema_val(s):
        return _get_setting_value(s)

    def save_settings():
        try:
            # Snapshot originals for after_save callbacks
            _orig = {s["key"]: _schema_val(s) for s in config_io.SETTINGS_SCHEMA if s.get("after_save")}

            # Apply all schema settings from their tk vars
            for s in config_io.SETTINGS_SCHEMA:
                if s["key"] not in _setting_vars:
                    continue
                var = _setting_vars[s["key"]]
                t = s["type"]
                if t == "int":
                    val = int(var.get())
                elif t == "float":
                    val = float(var.get())
                elif t == "bool":
                    val = var.get()
                else:  # str, password, color, rules_file
                    val = var.get().strip()
                if t in ("int", "float"):
                    if "min" in s:
                        val = max(s["min"], val)
                    if "max" in s:
                        val = min(s["max"], val)
                _set_setting_value(s, val)

            config_io.save_config()
            config_io.load_config()

            # After-save callbacks
            for s in config_io.SETTINGS_SCHEMA:
                after = s.get("after_save")
                if after == "restart_warning":
                    if _orig[s["key"]] != _schema_val(s):
                        messagebox.showinfo("Restart Required",
                                            "The 'Scale Main UI' setting has been changed.\n\n"
                                            "Please restart the application for this change to take effect.")
                elif after == "reset_serpapi":
                    if _orig[s["key"]] != _schema_val(s):
                        from _app_scripts.queue_round.lightning_rounds import cover_image_overlay
                        cover_image_overlay.serpapi_limited = False
                        cover_image_overlay.serpapi_limited_count = 0

            save_btn.config(text="SAVED!", bg="darkgreen")
            settings_window.after(300, lambda: save_btn.config(text="SAVE SETTINGS", bg="black"))

        except ValueError as e:
            messagebox.showerror("Invalid Value", f"Settings must be valid numbers.\nError: {e}")

    # Create popup window
    settings_window = tk.Toplevel(bg=BACKGROUND_COLOR)
    settings_window.title("Configuration Settings")
    settings_window.resizable(False, False)

    def on_settings_close():
        global settings_window
        if settings_window and settings_window.winfo_exists():
            settings_window.destroy()
        settings_window = None

    settings_window.protocol("WM_DELETE_WINDOW", on_settings_close)

    try:
        settings_window.transient(root)
        windowing.get_window_position_and_setup(settings_window)
    except tk.TclError:
        pass

    main_frame = tk.Frame(settings_window, bg=BACKGROUND_COLOR)
    main_frame.pack(padx=15, pady=15)

    # Two-column layout
    cols_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    cols_frame.pack(fill="x")
    col_left  = tk.Frame(cols_frame, bg=BACKGROUND_COLOR)
    col_right = tk.Frame(cols_frame, bg=BACKGROUND_COLOR)
    col_left.pack(side="left", anchor="n", padx=(0, 20))
    col_right.pack(side="left", anchor="n")

    # tk vars keyed by schema key
    _setting_vars = {}
    # color dropdown widget refs (for shared delete_color)
    _color_dropdowns = {}

    def _render_simple_row(s, parent):
        """Auto-render a row for int / float / str / password / bool schema entries."""
        frame = tk.Frame(parent, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        lbl = tk.Label(frame, text=s["label"], bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
        lbl.pack(side="left")
        if s.get("tooltip"):
            tooltip.ToolTip(lbl, s["tooltip"])
        t = s["type"]
        if t == "bool":
            cur = _schema_val(s)
            var = tk.BooleanVar(value=cur)
            text_var = tk.StringVar(value="Enabled" if cur else "Disabled")
            btn = tk.Checkbutton(frame, variable=var, textvariable=text_var,
                                 bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                 command=lambda v=var, tv=text_var: tv.set("Enabled" if v.get() else "Disabled"))
            btn.pack(side="left", padx=(5, 0))
        else:
            var = tk.StringVar(value=str(_schema_val(s)))
            kw = {"textvariable": var, "bg": "black", "fg": "white",
                  "insertbackground": "white",
                  "width": s.get("width", 10), "justify": "center"}
            if t == "password":
                kw["show"] = "*"
                kw["justify"] = "left"
            tk.Entry(frame, **kw).pack(side="left", padx=(5, 0))
        _setting_vars[s["key"]] = var

    def _render_skip_group(parent):
        """Render the four skip settings as a single consolidated row."""
        group = [s for s in config_io.SETTINGS_SCHEMA if s.get("group") == "skip_group"]
        frame = tk.Frame(parent, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        lbl = tk.Label(frame, text=group[0]["label"], bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
        lbl.pack(side="left")
        tooltip.ToolTip(lbl, "Auto-skip settings: play duration, jump distance, and fade timing.")
        inputs = tk.Frame(frame, bg=BACKGROUND_COLOR)
        inputs.pack(side="left", padx=(5, 0))
        for sg in group:
            var = tk.StringVar(value=str(_schema_val(sg)))
            entry = tk.Entry(inputs, textvariable=var, bg="black", fg="white",
                             insertbackground="white",
                             width=sg.get("width", 6), justify="center")
            entry.pack(side="left", padx=(0, 3))
            if sg.get("tooltip"):
                tooltip.ToolTip(entry, sg["tooltip"])
            _setting_vars[sg["key"]] = var

    def _render_color_row(s, parent):
        """Render a color dropdown row with add/delete buttons."""
        frame = tk.Frame(parent, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        lbl = tk.Label(frame, text=s["label"], bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
        lbl.pack(side="left")
        tooltip.ToolTip(lbl, s["tooltip"])
        var = tk.StringVar(value=_schema_val(s))
        dropdown = ttk.Combobox(frame, textvariable=var, values=state.colors.OVERLAY_COLOR_OPTIONS, width=15)
        dropdown.pack(side="left", padx=(5, 2))
        _setting_vars[s["key"]] = var
        _color_dropdowns[s["key"]] = dropdown
        tk.Button(frame, text="➕", bg="black", fg="white", width=3,
                  command=lambda v=var, d=dropdown: add_color(v, d)).pack(side="left", padx=(0, 2))
        def _make_delete(cv):
            def _do():
                delete_color(cv,
                             _color_dropdowns.get("OVERLAY_BACKGROUND_COLOR"),
                             _color_dropdowns.get("OVERLAY_TEXT_COLOR"))
            return _do
        tk.Button(frame, text="❌", bg="black", fg="white", width=3,
                  command=_make_delete(var)).pack(side="left")

    def _render_rules_file_row(s, parent):
        """Render the rules-file folder-scanned dropdown."""
        frame = tk.Frame(parent, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        lbl = tk.Label(frame, text=s["label"], bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
        lbl.pack(side="left")
        tooltip.ToolTip(lbl, s["tooltip"])
        var = tk.StringVar(value=_schema_val(s))
        ttk.Combobox(frame, textvariable=var, values=scoreboard_control.get_available_rules_files(),
                     width=25, state="readonly").pack(side="left", padx=(5, 0))
        _setting_vars[s["key"]] = var

    # Collect visible rows first so we can split evenly
    _visible_rows = []
    _skip_group_seen = False
    for s in config_io.SETTINGS_SCHEMA:
        if s.get("requires_ngrok") and not web_server.NGROK_AVAILABLE:
            continue
        if s.get("requires_cloudflared") and not web_server.CLOUDFLARED_AVAILABLE:
            continue
        if s.get("requires_tunnel") and not (web_server.NGROK_AVAILABLE or web_server.CLOUDFLARED_AVAILABLE):
            continue
        if s.get("requires_scoreboard") and not scoreboard_control.AVAILABLE:
            continue
        if s.get("group") == "skip_group":
            if not _skip_group_seen:
                _visible_rows.append(("skip_group", None))
                _skip_group_seen = True
            continue
        _visible_rows.append((s["type"], s))

    # Split into two roughly equal columns
    half = (len(_visible_rows) + 1) // 2
    for i, (t, s) in enumerate(_visible_rows):
        parent = col_left if i < half else col_right
        if t == "skip_group":
            _render_skip_group(parent)
        elif t == "color":
            _render_color_row(s, parent)
        elif t == "rules_file":
            _render_rules_file_row(s, parent)
        else:
            _render_simple_row(s, parent)

    # Buttons
    button_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    button_frame.pack(fill="x", pady=(20, 0))

    save_btn = tk.Button(button_frame, text="SAVE SETTINGS", command=save_settings,
                         bg="black", fg="white", font=("Arial", 12, "bold"), width=15)
    save_btn.pack(side="left", padx=(3, 10))

    tk.Button(button_frame, text="CANCEL", command=on_settings_close,
              bg="black", fg="white", font=("Arial", 12, "bold"), width=15).pack(side="left")
