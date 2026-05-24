# _app_scripts/popout_layout_editor.py
# Popout layout editor window - extracted from guess_the_anime.py (Step 27).
import os
import copy
import tkinter as tk
from tkinter import simpledialog

from core.paths import POPOUT_LAYOUTS_FOLDER

# ---------------------------------------------------------------------------
# Injected context (populated by set_context() at startup)
# ---------------------------------------------------------------------------
get_flat_registry = None
_get_menu_registry = None
save_config = None
create_popout_controls = None
_save_popout_layout_preset = None
_load_popout_layout_presets = None
_get_popout_layout = None
_set_popout_layout = None
_get_popout_columns = None
_set_popout_columns = None
_get_popout_controls = None
_set_popout_controls = None
POPOUT_LAYOUT_DEFAULT = None
_POPOUT_SPECIAL_LABELS = {
    "SEARCH ENTRY":       "Search Entry",
    "SEARCH DROPDOWN":    "Search Results Dropdown",
    "SEARCH QUEUE":       "Queue Search Result",
    "YOUTUBE DROPDOWN":   "YouTube Videos Dropdown",
    "YOUTUBE QUEUE":      "Queue YouTube Video",
    "LIGHTNING DROPDOWN": "Lightning Mode Dropdown",
    "DIFFICULTY DROPDOWN":"Difficulty Dropdown",
    "toggle_metadata":    "Toggle Metadata Area",
}
ROOT_FONT = None
MENU_FONT = None
BACKGROUND_COLOR = "gray12"
HIGHLIGHT_COLOR = "gray26"


def set_context(*, flat_registry, menu_registry, save_config_fn, create_popout_controls_fn,
                save_preset_fn, load_presets_fn,
                get_popout_layout, set_popout_layout,
                get_popout_columns, set_popout_columns,
                get_popout_controls, set_popout_controls,
                popout_layout_default,
                root_font, menu_font, background_color, highlight_color):
    global get_flat_registry, _get_menu_registry, save_config, create_popout_controls
    global _save_popout_layout_preset, _load_popout_layout_presets
    global _get_popout_layout, _set_popout_layout, _get_popout_columns, _set_popout_columns
    global _get_popout_controls, _set_popout_controls
    global POPOUT_LAYOUT_DEFAULT, ROOT_FONT, MENU_FONT
    global BACKGROUND_COLOR, HIGHLIGHT_COLOR
    get_flat_registry = flat_registry
    _get_menu_registry = menu_registry
    save_config = save_config_fn
    create_popout_controls = create_popout_controls_fn
    _save_popout_layout_preset = save_preset_fn
    _load_popout_layout_presets = load_presets_fn
    _get_popout_layout = get_popout_layout
    _set_popout_layout = set_popout_layout
    _get_popout_columns = get_popout_columns
    _set_popout_columns = set_popout_columns
    _get_popout_controls = get_popout_controls
    _set_popout_controls = set_popout_controls
    POPOUT_LAYOUT_DEFAULT = popout_layout_default
    ROOT_FONT = root_font
    MENU_FONT = menu_font
    BACKGROUND_COLOR = background_color
    HIGHLIGHT_COLOR = highlight_color


def open_popout_layout_editor():
    """Positional grid-based popout layout editor.

    Items live at explicit (row, col) positions.  Empty cells are shown as
    drop targets — no [gap] item needed for blank space.
    • Drag a tile to an empty cell  → move it there.
    • Drag a tile onto another tile → replace the target (target removed).
    • Drag from the picker to any cell → add / replace.
    • ✕ on a tile removes it, leaving the cell empty.
    Save reloads the popout without closing this editor.
    """

    ged_flat  = get_flat_registry()
    ged_reg   = _get_menu_registry()
    ged_cols  = [_get_popout_columns()]   # mutable int box
    ged_nrows = [0]                # mutable row count (auto-grows)

    # ── Convert flat list ↔ positional dict ─────────────────────────────────
    def _list_to_grid(layout_list):
        """Convert flowing list (may have gap items) → positional dict {(r,c): spec}."""
        grid = {}
        r, c = 0, 0
        cols = ged_cols[0]
        for item in layout_list:
            itype = item.get("type", "action")
            cs = max(1, min(item.get("colspan", 1), cols))
            if c + cs > cols:
                r += 1
                c = 0
            if itype != "gap":
                grid[(r, c)] = {k: v for k, v in item.items()}
            c += cs
        return grid

    def _grid_to_flowing_list(grid_dict):
        """Convert positional dict → flowing list with gap items (for saving)."""
        if not grid_dict:
            return []
        cols = ged_cols[0]
        valid = {(r, c): s for (r, c), s in grid_dict.items() if c < cols}
        if not valid:
            return []
        max_row = max(r for r, c in valid)
        covered = set()
        for (r, c), spec in valid.items():
            cs = max(1, min(spec.get("colspan", 1), cols - c))
            for dc in range(1, cs):
                covered.add((r, c + dc))
        result = []
        for ri in range(max_row + 1):
            for ci in range(cols):
                if (ri, ci) in covered:
                    continue
                spec = valid.get((ri, ci))
                result.append(dict(spec) if spec else {"type": "gap", "colspan": 1})
        return result

    _pl = _get_popout_layout()
    ged_work = _list_to_grid(
        _pl if _pl is not None else POPOUT_LAYOUT_DEFAULT
    )

    # ── Window ───────────────────────────────────────────────────────────────
    ged_win = tk.Toplevel()
    ged_win.title("Configure Popout Layout — Grid View")
    ged_win.configure(bg=BACKGROUND_COLOR)
    ged_win.resizable(True, True)

    # ── top bar ──────────────────────────────────────────────────────────────
    top = tk.Frame(ged_win, bg=BACKGROUND_COLOR)
    top.pack(fill="x", padx=10, pady=(8, 0))
    tk.Label(top, text="Columns:", bg=BACKGROUND_COLOR, fg="white",
              font=ROOT_FONT).pack(side="left")
    col_var = tk.IntVar(value=ged_cols[0])
    def _on_col_change(*_):
        ged_cols[0] = max(1, col_var.get())
        _ged_rebuild_both()
    col_spin = tk.Spinbox(top, from_=1, to=16, textvariable=col_var, width=4,
                           bg="black", fg="white", buttonbackground="black",
                           font=ROOT_FONT, command=_on_col_change)
    col_spin.pack(side="left", padx=4)
    col_spin.bind("<FocusOut>", _on_col_change)

    def _add_row():
        ged_nrows[0] = max(ged_nrows[0], 1) + 1
        _ged_rebuild_both()

    def _del_last_row():
        if ged_nrows[0] <= 1:
            return
        last = ged_nrows[0] - 1
        for ci in range(ged_cols[0]):
            ged_work.pop((last, ci), None)
        ged_nrows[0] -= 1
        _ged_rebuild_both()

    tk.Button(top, text="+ Row", font=ROOT_FONT, bg="black", fg="white",
               relief="flat", command=_add_row).pack(side="left", padx=(10, 2))
    tk.Button(top, text="− Row", font=ROOT_FONT, bg="black", fg="white",
               relief="flat", command=_del_last_row).pack(side="left", padx=2)
    tk.Label(top,
              text="  Drag to empty cell = move  •  Drag onto tile = replace  •  ✕ = remove",
              bg=BACKGROUND_COLOR, fg="gray", font=ROOT_FONT).pack(side="left", padx=10)

    # ── body ──────────────────────────────────────────────────────────────────
    body = tk.Frame(ged_win, bg=BACKGROUND_COLOR)
    body.pack(fill="both", expand=True, padx=10, pady=6)
    body.grid_columnconfigure(0, weight=1)   # grid expands
    body.grid_columnconfigure(2, weight=0)   # picker is fixed-width, no expansion
    body.grid_rowconfigure(0, weight=1)

    # ── Grid canvas (left) ────────────────────────────────────────────────────
    grid_outer = tk.Frame(body, bg=BACKGROUND_COLOR)
    grid_outer.grid(row=0, column=0, sticky="nsew")
    grid_canvas = tk.Canvas(grid_outer, bg="gray10", highlightthickness=0)
    grid_vsb = tk.Scrollbar(grid_outer, orient="vertical", command=grid_canvas.yview)
    grid_canvas.configure(yscrollcommand=grid_vsb.set)
    grid_vsb.pack(side="right", fill="y")
    grid_canvas.pack(side="left", fill="both", expand=True)
    grid_inner = tk.Frame(grid_canvas, bg="gray10")
    grid_canvas.create_window((0, 0), window=grid_inner, anchor="nw")
    grid_inner.bind("<Configure>",
                     lambda e: grid_canvas.configure(scrollregion=grid_canvas.bbox("all")))

    # ── Picker canvas (right, fixed width) ───────────────────────────────────
    tk.Frame(body, bg="gray40", width=1).grid(row=0, column=1, sticky="ns", padx=6)
    pick_outer = tk.Frame(body, bg=BACKGROUND_COLOR, width=260)
    pick_outer.grid(row=0, column=2, sticky="ns")
    pick_outer.pack_propagate(False)
    pick_canvas = tk.Canvas(pick_outer, bg=BACKGROUND_COLOR, highlightthickness=0,
                             width=260)
    pick_vsb = tk.Scrollbar(pick_outer, orient="vertical", command=pick_canvas.yview)
    pick_canvas.configure(yscrollcommand=pick_vsb.set)
    pick_vsb.pack(side="right", fill="y")
    pick_canvas.pack(side="left", fill="both", expand=True)
    pick_inner = tk.Frame(pick_canvas, bg=BACKGROUND_COLOR)
    pick_win_id = pick_canvas.create_window((0, 0), window=pick_inner, anchor="nw")
    pick_inner.bind("<Configure>",
                     lambda e: (pick_canvas.configure(scrollregion=pick_canvas.bbox("all")),
                                pick_canvas.itemconfigure(pick_win_id, width=pick_canvas.winfo_width())))

    # Mouse-wheel scrolling on picker (enter/leave to avoid global capture)
    def _pick_scroll(event):
        pick_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_pick_enter(e):
        pick_canvas.bind_all("<MouseWheel>", _pick_scroll)

    def _on_pick_leave(e):
        pick_canvas.unbind_all("<MouseWheel>")

    pick_outer.bind("<Enter>", _on_pick_enter, add="+")
    pick_outer.bind("<Leave>", _on_pick_leave, add="+")
    ged_win.bind("<Destroy>", lambda e: pick_canvas.unbind_all("<MouseWheel>"),
                  add="+")

    # ── Drag state ────────────────────────────────────────────────────────────
    _gds: dict     = {"active": False, "src": None}
    _ghost_lbl     = [None]
    _tile_frames   = []   # list of ((row, col), frame)
    _empty_frames  = []   # list of ((row, col), frame)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _resolve_label(item_id: str, itype: str) -> str:
        if itype == "gap":
            return "[gap]"
        if item_id in _POPOUT_SPECIAL_LABELS:
            return _POPOUT_SPECIAL_LABELS[item_id]
        reg = ged_flat.get(item_id, {})
        lbl = reg.get("button_label") or reg.get("label", item_id)
        if callable(lbl):
            lbl = lbl()
        return str(lbl)

    def _destroy_ghost():
        if _ghost_lbl[0]:
            try:
                _ghost_lbl[0].destroy()
            except Exception:
                pass
        _ghost_lbl[0] = None

    def _make_ghost(text: str, x: int, y: int):
        _destroy_ghost()
        g = tk.Label(grid_inner, text=text, bg=HIGHLIGHT_COLOR, fg="white",
                      font=ROOT_FONT, relief="raised", padx=6, pady=4)
        g.place(x=x, y=y)
        g.lift()
        _ghost_lbl[0] = g

    def _find_tile_under(x_root: int, y_root: int):
        """Return (grid_pos, frame) for the tile under cursor, or (None, None)."""
        for pos, tf in _tile_frames:
            try:
                rx, ry = tf.winfo_rootx(), tf.winfo_rooty()
                rw, rh = tf.winfo_width(), tf.winfo_height()
            except Exception:
                continue
            if rx <= x_root <= rx + rw and ry <= y_root <= ry + rh:
                return pos, tf
        return None, None

    def _find_empty_under(x_root: int, y_root: int):
        """Return (grid_pos, frame) for the empty cell under cursor, or (None, None)."""
        for pos, ef in _empty_frames:
            try:
                rx, ry = ef.winfo_rootx(), ef.winfo_rooty()
                rw, rh = ef.winfo_width(), ef.winfo_height()
            except Exception:
                continue
            if rx <= x_root <= rx + rw and ry <= y_root <= ry + rh:
                return pos, ef
        return None, None

    def _highlight_all(x_root: int, y_root: int):
        for _, tf in _tile_frames:
            try:
                rx, ry = tf.winfo_rootx(), tf.winfo_rooty()
                rw, rh = tf.winfo_width(), tf.winfo_height()
                tf.configure(bg="gray40" if (rx <= x_root <= rx + rw
                                             and ry <= y_root <= ry + rh)
                              else "gray22")
            except Exception:
                pass
        for _, ef in _empty_frames:
            try:
                rx, ry = ef.winfo_rootx(), ef.winfo_rooty()
                rw, rh = ef.winfo_width(), ef.winfo_height()
                ef.configure(bg="gray30" if (rx <= x_root <= rx + rw
                                             and ry <= y_root <= ry + rh)
                              else "gray15")
            except Exception:
                pass

    # ── Grid rebuild ──────────────────────────────────────────────────────────
    def _ged_rebuild():
        for w in grid_inner.winfo_children():
            w.destroy()
        _tile_frames.clear()
        _empty_frames.clear()
        _destroy_ghost()
        _gds["active"] = False

        cols = ged_cols[0]

        # Determine row count: at least ged_nrows, or enough to fit occupied rows
        if ged_work:
            max_occ = max(r for r, c in ged_work)
        else:
            max_occ = -1
        nrows = max(ged_nrows[0], max_occ + 1, 1)
        ged_nrows[0] = nrows

        # Which cells are covered by colspan of their left neighbour
        covered = set()
        for (r, c), spec in ged_work.items():
            if c >= cols:
                continue
            cs = max(1, min(spec.get("colspan", 1), cols - c))
            for dc in range(1, cs):
                covered.add((r, c + dc))

        for ri in range(nrows):
            ci = 0
            while ci < cols:
                if (ri, ci) in covered:
                    ci += 1
                    continue

                spec = ged_work.get((ri, ci))
                if spec is not None:
                    cs       = max(1, min(spec.get("colspan", 1), cols - ci))
                    item_id  = spec.get("id", "")
                    itype    = spec.get("type", "action")
                    lbl_text = _resolve_label(item_id, itype)

                    tile = tk.Frame(grid_inner, bg="gray22", relief="raised", bd=2)
                    tile.grid(row=ri, column=ci, columnspan=cs,
                               sticky="nsew", padx=2, pady=2)
                    _tile_frames.append(((ri, ci), tile))

                    # ── top-right buttons: ✎ edit  ✕ remove ─────────────────
                    def _rm_tile(pos=(ri, ci)):
                        ged_work.pop(pos, None)
                        _ged_rebuild_both()
                    rm_btn = tk.Button(tile, text="✕", font=ROOT_FONT,
                                        bg="gray22", fg="gray50", width=2,
                                        relief="flat", bd=0, command=_rm_tile)
                    rm_btn.pack(side="right", anchor="ne", padx=(0, 2), pady=2)

                    def _open_edit(pos=(ri, ci), it=itype):
                        s = ged_work.get(pos)
                        if s is None:
                            return
                        pop = tk.Toplevel(ged_win)
                        pop.title("Edit tile")
                        pop.configure(bg=BACKGROUND_COLOR)
                        pop.resizable(False, False)
                        pad = {"padx": 8, "pady": 3}

                        # colspan
                        tk.Label(pop, text="Colspan:", bg=BACKGROUND_COLOR,
                                  fg="white", font=ROOT_FONT).grid(row=0, column=0, sticky="w", **pad)
                        sv = tk.IntVar(value=s.get("colspan", 1))
                        tk.Spinbox(pop, from_=1, to=ged_cols[0], textvariable=sv, width=4,
                                    bg="black", fg="white", buttonbackground="black",
                                    font=ROOT_FONT).grid(row=0, column=1, sticky="ew", **pad)

                        if it == "action":
                            # indicatoron=False turns the checkbutton into a toggle button:
                            # bg=unchecked color, selectcolor=checked color — reliable on Windows
                            _cb_kw = dict(
                                indicatoron=False,
                                bg="gray35", fg="white",
                                selectcolor="steelblue4",
                                activebackground="gray45",
                                activeforeground="white",
                                font=ROOT_FONT,
                                relief="raised", padx=8, pady=2,
                            )
                            iv = tk.BooleanVar(value=s.get("show_icon", True))
                            tk.Checkbutton(pop, text="Show icon", variable=iv,
                                            **_cb_kw
                                            ).grid(row=1, column=0, sticky="w", **pad)

                            iov = tk.BooleanVar(value=s.get("icon_only", False))
                            tk.Checkbutton(pop, text="Icon only", variable=iov,
                                            **_cb_kw
                                            ).grid(row=1, column=1, sticky="w", **pad)

                            tk.Label(pop, text="Custom label:", bg=BACKGROUND_COLOR,
                                      fg="white", font=ROOT_FONT).grid(row=2, column=0, sticky="w", **pad)
                            lv = tk.StringVar(value=s.get("custom_label", ""))
                            tk.Entry(pop, textvariable=lv, bg="black", fg="white",
                                      insertbackground="white", font=ROOT_FONT, width=18
                                      ).grid(row=2, column=1, sticky="ew", **pad)
                        else:
                            iv = iov = lv = None

                        def _apply():
                            s["colspan"] = max(1, sv.get())
                            if it == "action":
                                s["show_icon"]    = iv.get()
                                s["icon_only"]    = iov.get()
                                s["custom_label"] = lv.get().strip()
                            pop.destroy()
                            _ged_rebuild_both()

                        tk.Button(pop, text="Apply", font=ROOT_FONT,
                                   bg=HIGHLIGHT_COLOR, fg="white",
                                   command=_apply).grid(
                            row=10, column=0, columnspan=2, pady=(6, 8))
                        pop.bind("<Return>", lambda e: _apply())
                        pop.update_idletasks()
                        pw = pop.winfo_reqwidth()
                        ph = pop.winfo_reqheight()
                        gx = ged_win.winfo_rootx() + (ged_win.winfo_width() - pw) // 2
                        gy = ged_win.winfo_rooty() + (ged_win.winfo_height() - ph) // 2
                        pop.geometry(f"+{gx}+{gy}")
                        pop.after(1, pop.lift)
                        pop.grab_set()

                    edit_btn = tk.Button(tile, text="✎", font=ROOT_FONT,
                                          bg="gray22", fg="gray60", width=2,
                                          relief="flat", bd=0,
                                          command=_open_edit)

                    tk.Label(tile, text=lbl_text, bg="gray22", fg="white",
                              font=ROOT_FONT, anchor="center", wraplength=120,
                              pady=2).pack(fill="x", expand=True, padx=4)

                    # place ✎ at bottom-right corner (after pack so it overlays)
                    edit_btn.place(relx=1.0, rely=1.0, anchor="se", x=-2, y=-2)

                    # ── Drag bindings ─────────────────────────────────────────
                    def _tile_press(e, pos=(ri, ci), aid=item_id,
                                    ait=itype, txt=lbl_text):
                        _gds.update(active=True,
                                     src={"kind": "grid", "pos": pos,
                                          "id": aid, "type": ait})
                        gx = e.x_root - grid_inner.winfo_rootx() - 30
                        gy = e.y_root - grid_inner.winfo_rooty() - 15
                        _make_ghost(txt, gx, gy)

                    def _tile_motion(e):
                        if not _gds["active"]:
                            return
                        gx = e.x_root - grid_inner.winfo_rootx() - 30
                        gy = e.y_root - grid_inner.winfo_rooty() - 15
                        if _ghost_lbl[0]:
                            _ghost_lbl[0].place(x=gx, y=gy)
                        _highlight_all(e.x_root, e.y_root)

                    def _tile_release(e):
                        if not _gds["active"]:
                            return
                        src = _gds["src"]
                        _gds["active"] = False
                        _destroy_ghost()
                        tgt_tile,  _ = _find_tile_under(e.x_root, e.y_root)
                        tgt_empty, _ = _find_empty_under(e.x_root, e.y_root)
                        if tgt_tile is not None:
                            if src["kind"] == "grid":
                                # Tile → tile: swap the two items
                                sp = src["pos"]
                                if sp != tgt_tile:
                                    a = ged_work.get(sp)
                                    b = ged_work.get(tgt_tile)
                                    if a is not None:
                                        ged_work[tgt_tile] = a
                                    else:
                                        ged_work.pop(tgt_tile, None)
                                    if b is not None:
                                        ged_work[sp] = b
                                    else:
                                        ged_work.pop(sp, None)
                            elif src["kind"] == "picker":
                                # Picker → tile: replace target
                                ged_work[tgt_tile] = {
                                    "type": src["type"], "id": src["id"],
                                    "colspan": 1,
                                }
                            _ged_rebuild_both()
                        elif tgt_empty is not None:
                            # Any source → empty cell: move / add
                            if src["kind"] == "grid":
                                sp = src["pos"]
                                s = ged_work.pop(sp, None)
                                if s:
                                    ged_work[tgt_empty] = s
                            elif src["kind"] == "picker":
                                ged_work[tgt_empty] = {
                                    "type": src["type"], "id": src["id"],
                                    "colspan": 1,
                                }
                            _ged_rebuild_both()

                    for child in [tile, rm_btn] + list(tile.winfo_children()):
                        if child is rm_btn or child is edit_btn:
                            continue
                        child.bind("<Button-1>",        _tile_press)
                        child.bind("<B1-Motion>",        _tile_motion)
                        child.bind("<ButtonRelease-1>",  _tile_release)
                    rm_btn.bind("<B1-Motion>",       _tile_motion)
                    rm_btn.bind("<ButtonRelease-1>", _tile_release)

                    ci += cs

                else:
                    # Empty cell — drop target
                    empty = tk.Frame(grid_inner, bg="gray15",
                                      relief="groove", bd=1)
                    empty.grid(row=ri, column=ci, sticky="nsew", padx=2, pady=2)
                    _empty_frames.append(((ri, ci), empty))

                    def _empty_enter(e, ef=empty):
                        if _gds["active"]:
                            ef.configure(bg="gray30")

                    def _empty_leave(e, ef=empty):
                        ef.configure(bg="gray15")

                    empty.bind("<Enter>", _empty_enter)
                    empty.bind("<Leave>", _empty_leave)
                    ci += 1

        for ri in range(nrows):
            grid_inner.grid_rowconfigure(ri, weight=1, minsize=60)
        for ci2 in range(cols):
            grid_inner.grid_columnconfigure(ci2, weight=1, minsize=80)

        grid_inner.update_idletasks()
        grid_canvas.configure(scrollregion=grid_canvas.bbox("all"))

    # ── Picker rebuild (collapsible tree, starts fully collapsed) ─────────────
    _pick_collapsed: dict = {}

    def _build_picker():
        for w in pick_inner.winfo_children():
            w.destroy()

        active_ids = {s["id"] for s in ged_work.values() if s.get("type") != "gap"}

        def _pick_item(item_id: str, itype: str, display: str):
            rf = tk.Frame(pick_inner, bg=BACKGROUND_COLOR)
            rf.pack(fill="x", padx=4, pady=1)
            lbl = tk.Label(rf, text=display, bg=BACKGROUND_COLOR,
                            fg="white", font=ROOT_FONT, anchor="w", cursor="fleur")
            lbl.pack(side="left", fill="x", expand=True, padx=4)

            def _press(e, aid=item_id, ait=itype, txt=display):
                _gds.update(active=True,
                             src={"kind": "picker", "id": aid, "type": ait})
                gx = e.x_root - grid_inner.winfo_rootx() - 30
                gy = e.y_root - grid_inner.winfo_rooty() - 15
                _make_ghost(txt, gx, gy)

            def _motion(e):
                if not _gds["active"]:
                    return
                gx = e.x_root - grid_inner.winfo_rootx() - 30
                gy = e.y_root - grid_inner.winfo_rooty() - 15
                if _ghost_lbl[0]:
                    _ghost_lbl[0].place(x=gx, y=gy)
                _highlight_all(e.x_root, e.y_root)

            def _release(e, aid=item_id, ait=itype):
                if not _gds["active"]:
                    return
                _gds["active"] = False
                _destroy_ghost()
                tgt_tile,  _ = _find_tile_under(e.x_root, e.y_root)
                tgt_empty, _ = _find_empty_under(e.x_root, e.y_root)
                if tgt_tile is not None:
                    ged_work[tgt_tile] = {"type": ait, "id": aid, "colspan": 1}
                    _ged_rebuild_both()
                elif tgt_empty is not None:
                    ged_work[tgt_empty] = {"type": ait, "id": aid, "colspan": 1}
                    _ged_rebuild_both()

            for w in [lbl, rf]:
                w.bind("<Button-1>",        _press)
                w.bind("<B1-Motion>",        _motion)
                w.bind("<ButtonRelease-1>",  _release)

        def _render_pick_tree(items, depth: int, path: str):
            indent = depth * 12
            for item in items:
                if item == "---":
                    tk.Frame(pick_inner, bg="gray30", height=1
                              ).pack(fill="x", padx=indent + 4, pady=1)
                    continue
                if not isinstance(item, dict):
                    continue
                item_id  = item.get("id", "")
                sub_path = f"{path}/{item_id or item.get('label', '')}"

                if "submenu" in item:
                    # Default collapsed on first build
                    if sub_path not in _pick_collapsed:
                        _pick_collapsed[sub_path] = True
                    collapsed = _pick_collapsed[sub_path]
                    arrow = "▶" if collapsed else "▼"
                    icon_txt = item.get("icon", "")
                    if callable(icon_txt):
                        icon_txt = icon_txt()
                    sub_lbl = item.get("label", "")
                    display = f"{icon_txt} {sub_lbl}".strip() if icon_txt else sub_lbl
                    hdr_bg = "gray22" if depth == 0 else "gray18"

                    hdr = tk.Frame(pick_inner, bg=hdr_bg)
                    hdr.pack(fill="x", padx=indent,
                              pady=(4 if depth == 0 else 1, 0))

                    def _tog(pk=sub_path):
                        _pick_collapsed[pk] = not _pick_collapsed.get(pk, True)
                        _build_picker()
                    tk.Button(hdr, text=arrow, bg=hdr_bg, fg="gray70",
                               font=ROOT_FONT, relief="flat", bd=0,
                               command=_tog).pack(side="left")
                    tk.Label(hdr, text=display, bg=hdr_bg, fg="white",
                              font=ROOT_FONT, anchor="w"
                              ).pack(side="left", fill="x", expand=True, padx=4)

                    if (item_id and (item.get("button_label") or item.get("label"))
                            and item_id not in active_ids):
                        own_lbl = item.get("button_label") or item.get("label", item_id)
                        if callable(own_lbl):
                            own_lbl = own_lbl()
                        icon2 = item.get("icon", "")
                        if callable(icon2):
                            icon2 = icon2()
                        own_disp = (f"{icon2} {own_lbl}".strip()
                                     if icon2 else str(own_lbl))
                        if not collapsed:
                            _pick_item(item_id, "action", own_disp)

                    if not collapsed:
                        _render_pick_tree(item["submenu"], depth + 1, sub_path)
                    continue

                if not item_id:
                    continue
                if not (item.get("button_label") or item.get("label")):
                    continue
                if item_id in active_ids:
                    continue

                icon_txt = item.get("icon", "")
                if callable(icon_txt):
                    icon_txt = icon_txt()
                lbl_raw = item.get("button_label") or item.get("label", item_id)
                if callable(lbl_raw):
                    lbl_raw = lbl_raw()
                display = (f"{icon_txt} {lbl_raw}".strip()
                            if icon_txt else str(lbl_raw))
                _pick_item(item_id, "action", display)

        # Special widgets
        sp_avail = [wid for wid in _POPOUT_SPECIAL_LABELS
                     if wid not in active_ids]
        if sp_avail:
            sp_path = "__sp__"
            if sp_path not in _pick_collapsed:
                _pick_collapsed[sp_path] = True
            collapsed = _pick_collapsed[sp_path]
            arrow = "▶" if collapsed else "▼"
            sp_hdr = tk.Frame(pick_inner, bg="gray22")
            sp_hdr.pack(fill="x", pady=(4, 0))
            def _tog_sp():
                _pick_collapsed["__sp__"] = not _pick_collapsed.get("__sp__", True)
                _build_picker()
            tk.Button(sp_hdr, text=arrow, bg="gray22", fg="gray70",
                       font=ROOT_FONT, relief="flat", bd=0,
                       command=_tog_sp).pack(side="left")
            tk.Label(sp_hdr, text="Special Widgets", bg="gray22",
                      fg="white", font=ROOT_FONT, anchor="w"
                      ).pack(side="left", fill="x", expand=True, padx=4)
            if not collapsed:
                for wid in sp_avail:
                    _pick_item(wid, "widget", _POPOUT_SPECIAL_LABELS[wid])

        # Registry sections (all collapsed by default)
        for sec_key, sec_items in ged_reg.items():
            if sec_key.startswith("_"):
                continue
            sec_label = sec_key.replace("_", " ").title()
            sec_path  = f"_sec_{sec_key}"
            if sec_path not in _pick_collapsed:
                _pick_collapsed[sec_path] = True
            collapsed  = _pick_collapsed[sec_path]
            arrow      = "▶" if collapsed else "▼"
            sec_hdr = tk.Frame(pick_inner, bg="gray22")
            sec_hdr.pack(fill="x", pady=(4, 0))
            def _tog_sec(pk=sec_path):
                _pick_collapsed[pk] = not _pick_collapsed.get(pk, True)
                _build_picker()
            tk.Button(sec_hdr, text=arrow, bg="gray22", fg="gray70",
                       font=ROOT_FONT, relief="flat", bd=0,
                       command=_tog_sec).pack(side="left")
            tk.Label(sec_hdr, text=f"  {sec_label}", bg="gray22",
                      fg="white", font=ROOT_FONT, anchor="w"
                      ).pack(side="left", fill="x", expand=True, padx=4)
            if not collapsed:
                _render_pick_tree(sec_items, 1, sec_path)

        pick_inner.update_idletasks()
        pick_canvas.configure(scrollregion=pick_canvas.bbox("all"))

        # Bind mouse-wheel to every picker child so scrolling works anywhere
        def _bind_wheel(w):
            w.bind("<MouseWheel>", _pick_scroll)
            for child in w.winfo_children():
                _bind_wheel(child)
        _bind_wheel(pick_inner)

    def _fit_ged_win():
        """Resize the editor window to snugly fit current grid content + picker panel."""
        ged_win.update_idletasks()
        gw = max(grid_inner.winfo_reqwidth(), 200)
        gh = max(grid_inner.winfo_reqheight(), 100)
        # Right panel: scrollbar ≈17 + divider+pad ≈13 + picker 260 + window chrome 40
        extra_w = 17 + 13 + 260 + 40
        # Vertical chrome: top bar + bottom bar + section padding
        extra_h = top.winfo_reqheight() + bot.winfo_reqheight() + 40
        total_w = gw + extra_w
        total_h = gh + extra_h
        sw = ged_win.winfo_screenwidth()
        sh = ged_win.winfo_screenheight()
        total_w = min(max(total_w, 500), int(sw * 0.95))
        total_h = min(max(total_h, 350), int(sh * 0.90))
        ged_win.geometry(f"{total_w}x{total_h}")

    def _ged_rebuild_both():
        _ged_rebuild()
        _build_picker()
        ged_win.after(20, _fit_ged_win)

    # ── bottom bar ────────────────────────────────────────────────────────────
    bot = tk.Frame(ged_win, bg=BACKGROUND_COLOR)
    bot.pack(fill="x", padx=10, pady=8)

    def _ged_save():
        _set_popout_layout(_grid_to_flowing_list(ged_work) or None)
        _set_popout_columns(max(1, col_var.get()))
        save_config()
        # Reload popout if open — keep this editor window open
        if _get_popout_controls():
            _reopen_popout()

    def _reopen_popout():
        pc = _get_popout_controls()
        if pc:
            try:
                pc.destroy()
            except Exception:
                pass
            _set_popout_controls(None)   # must clear before calling create
        create_popout_controls()

    def _ged_reset():
        ged_work.clear()
        ged_work.update(_list_to_grid(copy.deepcopy(POPOUT_LAYOUT_DEFAULT)))
        col_var.set(5)
        ged_cols[0] = 5
        ged_nrows[0] = 0
        _ged_rebuild_both()

    # Left group: Save / Reset / Close
    left_bot = tk.Frame(bot, bg=BACKGROUND_COLOR)
    left_bot.pack(side="left")
    tk.Button(left_bot, text="Save", font=ROOT_FONT,
               bg=HIGHLIGHT_COLOR, fg="white", width=10,
               command=_ged_save).pack(side="left", padx=4)
    tk.Button(left_bot, text="Reset to Default", font=ROOT_FONT,
               bg="black", fg="white", width=16,
               command=_ged_reset).pack(side="left", padx=4)
    tk.Button(left_bot, text="Close", font=ROOT_FONT,
               bg="black", fg="white", width=10,
               command=ged_win.destroy).pack(side="left", padx=4)

    # Right group: preset label + Save Preset / Load Preset / Delete Preset
    right_bot = tk.Frame(bot, bg=BACKGROUND_COLOR)
    right_bot.pack(side="right")

    tk.Label(right_bot, text="Layout preset:", bg=BACKGROUND_COLOR,
              fg="gray70", font=ROOT_FONT).pack(side="left", padx=(0, 4))

    preset_var = tk.StringVar(value="")  # tracks the currently active preset name
    preset_name_lbl = tk.Label(right_bot, textvariable=preset_var,
                                bg=BACKGROUND_COLOR, fg="white",
                                font=ROOT_FONT, width=18, anchor="w")
    preset_name_lbl.pack(side="left", padx=(0, 4))

    def _ged_save_preset():
        current = preset_var.get().strip()
        name = simpledialog.askstring("Save Layout Preset",
                                       "Preset name:", initialvalue=current,
                                       parent=ged_win)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        layout_list = _grid_to_flowing_list(ged_work)
        try:
            _save_popout_layout_preset(name, layout_list, ged_cols[0])
        except Exception as e:
            print(f"Failed to save layout preset '{name}': {e}")
        preset_var.set(name)
        _refresh_preset_menu()

    def _ged_load_preset(name):
        presets = _load_popout_layout_presets()
        if name not in presets:
            return
        data = presets[name]
        loaded_layout = data.get("layout", [])
        loaded_cols   = int(data.get("columns", ged_cols[0]))
        ged_work.clear()
        ged_work.update(_list_to_grid(loaded_layout))
        col_var.set(loaded_cols)
        ged_cols[0] = loaded_cols
        ged_nrows[0] = 0
        preset_var.set(name)
        _ged_rebuild_both()

    def _ged_delete_preset():
        name = preset_var.get().strip()
        if not name:
            return
        path = os.path.join(POPOUT_LAYOUTS_FOLDER, f"{name}.json")
        if os.path.exists(path):
            os.remove(path)
        preset_var.set("")
        _refresh_preset_menu()

    # Dropdown menu for existing presets
    _preset_menu_btn = [None]
    _preset_menu     = [None]

    def _refresh_preset_menu():
        if _preset_menu[0]:
            _preset_menu[0].delete(0, "end")
            presets = _load_popout_layout_presets()
            for pname in presets:
                _preset_menu[0].add_command(
                    label=pname, command=lambda n=pname: _ged_load_preset(n))
            if not presets:
                _preset_menu[0].add_command(label="(no saved presets)", state="disabled")

    def _show_preset_menu():
        _refresh_preset_menu()
        btn = _preset_menu_btn[0]
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() - _preset_menu[0].winfo_reqheight()
        try:
            _preset_menu[0].tk_popup(x, y)
        finally:
            _preset_menu[0].grab_release()

    _preset_menu[0] = tk.Menu(ged_win, tearoff=0, bg="gray20", fg="white",
                               activebackground=HIGHLIGHT_COLOR,
                               activeforeground="white", font=MENU_FONT)
    _refresh_preset_menu()

    load_btn = tk.Button(right_bot, text="▾ Load", font=ROOT_FONT,
                          bg="black", fg="white", command=_show_preset_menu)
    load_btn.pack(side="left", padx=(0, 2))
    _preset_menu_btn[0] = load_btn

    tk.Button(right_bot, text="Save Preset", font=ROOT_FONT,
               bg="black", fg="white",
               command=_ged_save_preset).pack(side="left", padx=(0, 2))
    tk.Button(right_bot, text="Delete", font=ROOT_FONT,
               bg="black", fg="#c06060",
               command=_ged_delete_preset).pack(side="left", padx=(0, 4))

    _ged_rebuild_both()
