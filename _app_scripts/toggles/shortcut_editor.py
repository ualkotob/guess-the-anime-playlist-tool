# _app_scripts/shortcut_editor.py
# Keyboard shortcut viewer/editor window - extracted from guess_the_anime.py (Step 35).
import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------------------------------
# Injected context (populated by set_context() at startup)
# ---------------------------------------------------------------------------
get_window_position_and_setup = None
get_menu_registry = None
get_flat_registry = None
shortcut_display_name = None
bind_shortcuts = None
rebuild_shortcut_dispatch = None
save_config = None
_get_shortcuts_config = None
_set_shortcuts_config = None
BACKGROUND_COLOR = "gray12"
DEFAULT_SHORTCUTS = {}
FIXED_SHORTCUTS = {}
scl = None


def set_context(*, get_window_position_and_setup, get_menu_registry, get_flat_registry,
                shortcut_display_name, bind_shortcuts, rebuild_shortcut_dispatch,
                save_config, get_shortcuts_config, set_shortcuts_config,
                background_color, default_shortcuts, fixed_shortcuts, scl):
    g = globals()
    g['scl'] = scl
    g['get_window_position_and_setup'] = get_window_position_and_setup
    g['get_menu_registry'] = get_menu_registry
    g['get_flat_registry'] = get_flat_registry
    g['shortcut_display_name'] = shortcut_display_name
    g['bind_shortcuts'] = bind_shortcuts
    g['rebuild_shortcut_dispatch'] = rebuild_shortcut_dispatch
    g['save_config'] = save_config
    g['_get_shortcuts_config'] = get_shortcuts_config
    g['_set_shortcuts_config'] = set_shortcuts_config
    g['BACKGROUND_COLOR'] = background_color
    g['DEFAULT_SHORTCUTS'] = default_shortcuts
    g['FIXED_SHORTCUTS'] = fixed_shortcuts


def open_shortcut_editor():
    """Interactive keyboard shortcut viewer and editor."""

    _SECTION_NAMES = {
        "playlist":   "Playlist",
        "queue":      "Queue",
        "popups":     "Popups",
        "toggles":    "Toggles",
        "theme":      "Theme",
        "hidden":     "Hidden / Controls",
        "scoreboard": "Scoreboard",
        "directory":  "Directory",
        "file":       "File",
    }
    _MODIFIER_KEYSYMS = {
        "Shift_L", "Shift_R", "Control_L", "Control_R",
        "Alt_L", "Alt_R", "Meta_L", "Meta_R",
        "Super_L", "Super_R", "Caps_Lock", "Num_Lock", "Scroll_Lock",
    }

    def _collect_shortcuttable():
        """Walk registry and return {section_key: [items]} for items with shortcut=True."""
        result = {}
        for section_key, items in get_menu_registry().items():
            section_items = []
            for entry in items:
                if entry == "---" or not isinstance(entry, dict):
                    continue
                if entry.get("shortcut"):
                    section_items.append(entry)
                for sub in entry.get("submenu", []):
                    if isinstance(sub, dict) and sub.get("shortcut"):
                        section_items.append(sub)
            if section_items:
                result[section_key] = section_items
        return result

    shortcuttable = _collect_shortcuttable()
    flat  = get_flat_registry()
    draft = dict(_get_shortcuts_config())   # working copy — committed only on Save

    BG         = BACKGROUND_COLOR
    FG         = "white"
    DIM        = "#888888"
    CAPTURE_BG = "#1e3a6e"
    CAPTURE_FG = "#ffdd44"
    BTN_BG     = "#2a2a2a"
    SAVE_BG    = "#1c5c1c"
    CLEAR_BG   = "#5c1c1c"

    win = tk.Toplevel()
    win.title("Keyboard Shortcuts")
    win.configure(bg=BG)
    win.resizable(False, True)
    get_window_position_and_setup(win)

    # ── search bar ───────────────────────────────────────────────────────────
    search_frame = tk.Frame(win, bg=BG)
    search_frame.pack(fill="x", padx=8, pady=(8, 0))
    tk.Label(search_frame, text="🔍", bg=BG, fg=DIM,
             font=("Arial", scl(10))).pack(side="left")
    search_var = tk.StringVar()
    search_entry = tk.Entry(search_frame, textvariable=search_var, bg="#1a1a1a",
                            fg=FG, insertbackground=FG, relief="flat",
                            font=("Arial", scl(10)), bd=4)
    search_entry.pack(side="left", fill="x", expand=True, padx=4)

    # ── scrollable area ──────────────────────────────────────────────────────
    scroll_frame = tk.Frame(win, bg=BG)
    scroll_frame.pack(fill="both", expand=True, padx=8, pady=(4, 0))

    canvas = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0)
    vsb    = tk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas, bg=BG)
    cwin  = canvas.create_window((0, 0), window=inner, anchor="nw")

    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))

    # Bind scroll wheel only while mouse is over the scroll area
    def _scroll(e):
        canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
    scroll_frame.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _scroll))
    scroll_frame.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ── state ────────────────────────────────────────────────────────────────
    capturing_id    = [None]
    row_frames      = {}   # item_id → tk.Frame
    key_labels      = {}   # item_id → key tk.Label
    section_hdrs    = {}   # section_key → header tk.Frame
    row_search_text = {}   # item_id → lower-case label text

    # ── helpers ──────────────────────────────────────────────────────────────
    def _effective_key(item_id):
        # draft[item_id] = ""  means explicitly cleared (no key)
        # item_id not in draft means fall back to DEFAULT_SHORTCUTS
        if item_id in draft:
            return draft[item_id] or None
        return DEFAULT_SHORTCUTS.get(item_id) or None

    def _display_key(item_id):
        k = _effective_key(item_id)
        if not k:
            return ""
        return shortcut_display_name(k) or k

    def _all_shortcuttable_ids():
        return {item["id"] for items in shortcuttable.values()
                for item in items if item.get("id")}

    def _conflict_for(new_key, exclude_id):
        for aid in _all_shortcuttable_ids():
            if aid == exclude_id:
                continue
            if _effective_key(aid) == new_key:
                item = flat.get(aid, {})
                return item.get("label") or aid.replace("_", " ").title()
        return None

    # ── row filter ────────────────────────────────────────────────────────────
    def _apply_filter(*_):
        q = search_var.get().lower().strip()
        for section_key, hdr in section_hdrs.items():
            section_visible = False
            for item in shortcuttable.get(section_key, []):
                item_id = item.get("id")
                if not item_id:
                    continue
                rf = row_frames.get(item_id)
                if not rf:
                    continue
                match = not q or q in row_search_text.get(item_id, "")
                if match:
                    rf.pack(fill="x", padx=8, pady=1)
                    section_visible = True
                else:
                    rf.pack_forget()
            if section_visible:
                hdr.pack(fill="x", pady=(8, 1))
            else:
                hdr.pack_forget()
        canvas.after(10, lambda: canvas.configure(scrollregion=canvas.bbox("all")))

    search_var.trace_add("write", _apply_filter)

    # ── capture mode ─────────────────────────────────────────────────────────
    def _set_row_colors(item_id, bg, key_fg):
        rf = row_frames.get(item_id)
        kl = key_labels.get(item_id)
        if rf:
            rf.configure(bg=bg)
            for child in rf.winfo_children():
                try:
                    child.configure(bg=bg)
                except tk.TclError:
                    pass
        if kl:
            kl.configure(bg=bg, fg=key_fg)

    def _exit_capture(item_id):
        capturing_id[0] = None
        win.unbind("<KeyPress>")
        _set_row_colors(item_id, BG, FG)
        if item_id in key_labels:
            key_labels[item_id].configure(text=_display_key(item_id))

    def _enter_capture(item_id):
        prev = capturing_id[0]
        if prev:
            _exit_capture(prev)
        if prev == item_id:
            return   # clicking active row again cancels capture
        capturing_id[0] = item_id
        _set_row_colors(item_id, CAPTURE_BG, CAPTURE_FG)
        key_labels[item_id].configure(text="press key…")
        win.bind("<KeyPress>", _on_key_capture)
        win.focus_force()

    def _on_key_capture(event):
        item_id = capturing_id[0]
        if not item_id:
            return
        if event.keysym == "Escape":
            _exit_capture(item_id)
            return
        if event.keysym in _MODIFIER_KEYSYMS:
            return
        if event.char and event.char.isprintable() and len(event.char) == 1:
            new_key = event.char
        elif event.keysym in ("BackSpace", "Delete", "Return", "Tab"):
            new_key = event.keysym
        else:
            return
        conflict = _conflict_for(new_key, item_id)
        if conflict:
            kl = key_labels[item_id]
            kl.configure(text=f"used by: {conflict}", fg="#ff6666", bg=CAPTURE_BG)
            win.after(1600, lambda: _exit_capture(item_id))
            return
        draft[item_id] = new_key
        _exit_capture(item_id)

    def _reset_one(item_id):
        """Remove override — falls back to default (or blank if no default)."""
        draft.pop(item_id, None)
        if capturing_id[0] == item_id:
            _exit_capture(item_id)
        elif item_id in key_labels:
            key_labels[item_id].configure(text=_display_key(item_id))

    def _clear_one(item_id):
        """Explicitly unassign — no key even if there's a default."""
        if capturing_id[0] == item_id:
            _exit_capture(item_id)
        if item_id in DEFAULT_SHORTCUTS:
            draft[item_id] = ""   # explicit override: no key
        else:
            draft.pop(item_id, None)
        if item_id in key_labels:
            key_labels[item_id].configure(text="", fg=FG, bg=BG)

    # ── build rows ────────────────────────────────────────────────────────────
    fnt_section = ("Arial", scl(9),  "bold")
    fnt_row     = ("Arial", scl(10))
    fnt_key     = ("Courier New", scl(10), "bold")
    fnt_dim     = ("Arial", scl(8))

    for section_key, items in shortcuttable.items():
        section_title = _SECTION_NAMES.get(section_key,
                                           section_key.replace("_", " ").title())
        sh = tk.Frame(inner, bg=BG)
        sh.pack(fill="x", pady=(8, 1))
        section_hdrs[section_key] = sh
        tk.Label(sh, text=section_title.upper(), font=fnt_section,
                 bg=BG, fg=DIM).pack(side="left", padx=8)
        tk.Frame(sh, bg=DIM, height=1).pack(side="left", fill="x", expand=True, padx=4, pady=6)

        for item in items:
            item_id    = item.get("id")
            if not item_id:
                continue
            label_text = item.get("label") or item_id.replace("_", " ").title()
            row_search_text[item_id] = label_text.lower()

            is_fixed    = item_id in FIXED_SHORTCUTS
            default_key = DEFAULT_SHORTCUTS.get(item_id)
            if is_fixed:
                fixed_key, _fixed_lbl, _fixed_note = FIXED_SHORTCUTS[item_id]
                def_display = shortcut_display_name(fixed_key) or fixed_key
            else:
                def_display = (shortcut_display_name(default_key) or default_key) if default_key else ""

            row = tk.Frame(inner, bg=BG)
            row.pack(fill="x", padx=8, pady=1)
            row_frames[item_id] = row

            tk.Label(row, text=label_text, font=fnt_row, bg=BG, fg=FG,
                     anchor="w").pack(side="left", fill="x", expand=True)

            if is_fixed:
                # Fixed row: bright key display + "hardcoded" label on the right, no edit controls
                tk.Label(row, text="hardcoded", font=fnt_dim, bg=BG, fg=DIM,
                         width=9, anchor="e").pack(side="left")
                tk.Label(row, text=def_display, font=fnt_key,
                         bg=BG, fg=FG, width=6, anchor="center",
                         relief="groove").pack(side="left", padx=(4, 2))
                # Spacer to align with the two buttons on editable rows
                tk.Label(row, text="", bg=BG, width=4).pack(side="left", padx=(0, 2))
            else:
                tk.Label(row, text=f"({def_display})" if def_display else "",
                         font=fnt_dim, bg=BG, fg=DIM, width=6, anchor="e").pack(side="left")

                kl = tk.Label(row, text=_display_key(item_id), font=fnt_key,
                              bg=BG, fg=FG, width=6, anchor="center",
                              relief="groove", cursor="hand2")
                kl.pack(side="left", padx=(4, 2))
                key_labels[item_id] = kl
                kl.bind("<Button-1>",  lambda e, i=item_id: _enter_capture(i))
                row.bind("<Button-1>", lambda e, i=item_id: _enter_capture(i))

                tk.Button(row, text="×", font=fnt_row, bg=BTN_BG, fg="#cc4444",
                          relief="flat", bd=0, cursor="hand2",
                          command=lambda i=item_id: _clear_one(i)).pack(side="left", padx=(0, 1))
                tk.Button(row, text="↺", font=fnt_row, bg=BTN_BG, fg=DIM,
                          relief="flat", bd=0, cursor="hand2",
                          command=lambda i=item_id: _reset_one(i)).pack(side="left", padx=(0, 2))

    # ── fixed-only section: keys with no registry entry ──────────────────────
    registry_ids = set(row_frames.keys())
    extra_fixed  = [(fid, fdata) for fid, fdata in FIXED_SHORTCUTS.items()
                    if fid not in registry_ids]
    if extra_fixed:
        sh = tk.Frame(inner, bg=BG)
        sh.pack(fill="x", pady=(8, 1))
        section_hdrs["_fixed_extra"] = sh
        tk.Label(sh, text="ALWAYS-ON KEYS", font=fnt_section,
                 bg=BG, fg=DIM).pack(side="left", padx=8)
        tk.Frame(sh, bg=DIM, height=1).pack(side="left", fill="x", expand=True, padx=4, pady=6)

        for fid, (fkey, flabel, fnote) in extra_fixed:
            fkey_display = shortcut_display_name(fkey) or fkey
            hint_text    = fnote or "hardcoded"
            row_search_text[fid] = flabel.lower()
            row = tk.Frame(inner, bg=BG)
            row.pack(fill="x", padx=8, pady=1)
            row_frames[fid] = row

            tk.Label(row, text=flabel, font=fnt_row, bg=BG, fg=FG,
                     anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text=hint_text, font=fnt_dim, bg=BG, fg=DIM,
                     width=9, anchor="e").pack(side="left")
            tk.Label(row, text=fkey_display, font=fnt_key,
                     bg=BG, fg=FG, width=6, anchor="center",
                     relief="groove").pack(side="left", padx=(4, 2))
            tk.Label(row, text="", bg=BG, width=4).pack(side="left", padx=(0, 2))

        # Register extra entries into the section filtering dict
        shortcuttable["_fixed_extra"] = [{"id": fid} for fid, _ in extra_fixed]
        _SECTION_NAMES["_fixed_extra"] = "Always-on Keys"

    # ── bottom bar ────────────────────────────────────────────────────────────
    bar = tk.Frame(win, bg=BG)
    bar.pack(fill="x", padx=8, pady=8)

    def _reset_all():
        if not messagebox.askyesno("Reset All Shortcuts",
                                   "Reset all shortcuts to their defaults?",
                                   parent=win):
            return
        draft.clear()
        if capturing_id[0]:
            _exit_capture(capturing_id[0])
        for iid, kl in key_labels.items():
            kl.configure(text=_display_key(iid), fg=FG, bg=BG)

    def _clear_all():
        if not messagebox.askyesno("Clear All Shortcuts",
                                   "Remove all shortcut assignments, including defaults?",
                                   parent=win):
            return
        if capturing_id[0]:
            _exit_capture(capturing_id[0])
        for iid in _all_shortcuttable_ids():
            if iid in FIXED_SHORTCUTS:
                continue   # hardcoded — cannot clear
            if iid in DEFAULT_SHORTCUTS:
                draft[iid] = ""
            else:
                draft.pop(iid, None)
        for iid, kl in key_labels.items():
            kl.configure(text="", fg=FG, bg=BG)

    def _save():
        if capturing_id[0]:
            _exit_capture(capturing_id[0])
        new_cfg = {k: v for k, v in draft.items()
                   if v != DEFAULT_SHORTCUTS.get(k)}
        _set_shortcuts_config(new_cfg)
        rebuild_shortcut_dispatch()
        bind_shortcuts()
        save_config()

    def _cancel():
        if capturing_id[0]:
            _exit_capture(capturing_id[0])
        canvas.unbind_all("<MouseWheel>")
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _cancel)

    left_bar = tk.Frame(bar, bg=BG)
    left_bar.pack(side="left")
    tk.Button(left_bar, text="Reset All to Defaults", font=fnt_row,
              bg=BTN_BG, fg="white", relief="flat", bd=0,
              padx=8, pady=4, command=_reset_all).pack(side="left", padx=(0, 4))
    tk.Button(left_bar, text="Clear All", font=fnt_row,
              bg=CLEAR_BG, fg="white", relief="flat", bd=0,
              padx=8, pady=4, command=_clear_all).pack(side="left")

    tk.Button(bar, text="Cancel", font=fnt_row,
              bg=BTN_BG, fg="white", relief="flat", bd=0,
              padx=12, pady=4, command=_cancel).pack(side="right", padx=4)
    tk.Button(bar, text="Save", font=fnt_row,
              bg=SAVE_BG, fg="white", relief="flat", bd=0,
              padx=16, pady=4, command=_save).pack(side="right", padx=4)

    win.update_idletasks()
    x, y = win.winfo_x(), win.winfo_y()
    win.geometry(f"480x640+{x}+{y}")
    win.minsize(460, 400)
    win.maxsize(700, 1000)
