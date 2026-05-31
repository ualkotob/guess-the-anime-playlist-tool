# _app_scripts/settings_popup.py
# Configuration settings popup - extracted from guess_the_anime.py (Step 37).
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from core.game_state import state
import _app_scripts.file.scoreboard_control as scoreboard_control

# ---------------------------------------------------------------------------
# Injected context (populated by set_context() at startup)
# ---------------------------------------------------------------------------
get_window_position_and_setup = None
get_available_rules_files = None
load_config = None
save_config = None
ToolTip = None
BACKGROUND_COLOR = "gray12"
OVERLAY_COLOR_OPTIONS = ()
SETTINGS_SCHEMA = ()
CLOUDFLARED_AVAILABLE = False
NGROK_AVAILABLE = False
# Reference to the main module's globals() dict. Settings live as
# module-level variables in main, so reads/writes from the SETTINGS_SCHEMA
# must go through this — using settings_popup's own globals() instead
# would KeyError on the first setting access.
main_globals = {}

# Module-private window state (was a main-file global)
settings_window = None


def set_context(*, get_window_position_and_setup, get_available_rules_files,
                load_config, save_config, ToolTip,
                background_color, overlay_color_options, settings_schema,
                cloudflared_available, ngrok_available, main_globals):
    g = globals()
    g['main_globals'] = main_globals
    g['get_window_position_and_setup'] = get_window_position_and_setup
    g['get_available_rules_files'] = get_available_rules_files
    g['load_config'] = load_config
    g['save_config'] = save_config
    g['ToolTip'] = ToolTip
    g['BACKGROUND_COLOR'] = background_color
    g['OVERLAY_COLOR_OPTIONS'] = overlay_color_options
    g['SETTINGS_SCHEMA'] = settings_schema
    g['CLOUDFLARED_AVAILABLE'] = cloudflared_available
    g['NGROK_AVAILABLE'] = ngrok_available


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
            if new_color in OVERLAY_COLOR_OPTIONS:
                messagebox.showinfo("Color Already Exists", f"'{new_color}' is already in the color list.")
                return
            if is_valid_color(new_color):
                OVERLAY_COLOR_OPTIONS.append(new_color)
                dropdown['values'] = OVERLAY_COLOR_OPTIONS
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
        if current_color in OVERLAY_COLOR_OPTIONS:
            OVERLAY_COLOR_OPTIONS.remove(current_color)
            back_dd['values'] = OVERLAY_COLOR_OPTIONS
            text_dd['values'] = OVERLAY_COLOR_OPTIONS
            color_var.set("black")

    def save_settings():
        try:
            # Snapshot originals for after_save callbacks
            _orig = {s["key"]: main_globals[s["key"]] for s in SETTINGS_SCHEMA if s.get("after_save")}

            # Apply all schema settings from their tk vars
            for s in SETTINGS_SCHEMA:
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
                main_globals[s["key"]] = val

            save_config()
            load_config()

            # After-save callbacks
            for s in SETTINGS_SCHEMA:
                after = s.get("after_save")
                if after == "restart_warning":
                    if _orig[s["key"]] != main_globals[s["key"]]:
                        messagebox.showinfo("Restart Required",
                                            "The 'Scale Main UI' setting has been changed.\n\n"
                                            "Please restart the application for this change to take effect.")
                elif after == "reset_serpapi":
                    if _orig[s["key"]] != main_globals[s["key"]]:
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
        get_window_position_and_setup(settings_window)
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
            ToolTip(lbl, s["tooltip"])
        t = s["type"]
        if t == "bool":
            var = tk.BooleanVar(value=main_globals[s["key"]])
            text_var = tk.StringVar(value="Enabled" if main_globals[s["key"]] else "Disabled")
            btn = tk.Checkbutton(frame, variable=var, textvariable=text_var,
                                 bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                 command=lambda v=var, tv=text_var: tv.set("Enabled" if v.get() else "Disabled"))
            btn.pack(side="left", padx=(5, 0))
        else:
            var = tk.StringVar(value=str(main_globals[s["key"]]))
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
        group = [s for s in SETTINGS_SCHEMA if s.get("group") == "skip_group"]
        frame = tk.Frame(parent, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        lbl = tk.Label(frame, text=group[0]["label"], bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
        lbl.pack(side="left")
        ToolTip(lbl, "Auto-skip settings: play duration, jump distance, and fade timing.")
        inputs = tk.Frame(frame, bg=BACKGROUND_COLOR)
        inputs.pack(side="left", padx=(5, 0))
        for sg in group:
            var = tk.StringVar(value=str(main_globals[sg["key"]]))
            entry = tk.Entry(inputs, textvariable=var, bg="black", fg="white",
                             insertbackground="white",
                             width=sg.get("width", 6), justify="center")
            entry.pack(side="left", padx=(0, 3))
            if sg.get("tooltip"):
                ToolTip(entry, sg["tooltip"])
            _setting_vars[sg["key"]] = var

    def _render_color_row(s, parent):
        """Render a color dropdown row with add/delete buttons."""
        frame = tk.Frame(parent, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        lbl = tk.Label(frame, text=s["label"], bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
        lbl.pack(side="left")
        ToolTip(lbl, s["tooltip"])
        var = tk.StringVar(value=main_globals[s["key"]])
        dropdown = ttk.Combobox(frame, textvariable=var, values=OVERLAY_COLOR_OPTIONS, width=15)
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
        ToolTip(lbl, s["tooltip"])
        var = tk.StringVar(value=main_globals[s["key"]])
        ttk.Combobox(frame, textvariable=var, values=get_available_rules_files(),
                     width=25, state="readonly").pack(side="left", padx=(5, 0))
        _setting_vars[s["key"]] = var

    # Collect visible rows first so we can split evenly
    _visible_rows = []
    _skip_group_seen = False
    for s in SETTINGS_SCHEMA:
        if s.get("requires_ngrok") and not NGROK_AVAILABLE:
            continue
        if s.get("requires_cloudflared") and not CLOUDFLARED_AVAILABLE:
            continue
        if s.get("requires_tunnel") and not (NGROK_AVAILABLE or CLOUDFLARED_AVAILABLE):
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
