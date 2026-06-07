# Popout controls window.
import os
import tkinter as tk
from tkinter import ttk, font

from core.game_state import state
from _app_scripts.queue_round.youtube import youtube_ui
import _app_scripts.search.search as search_ops
import _app_scripts.ui.lists as lists
import _app_scripts.ui.windowing as windowing
import _app_scripts.ui.menu_builder as menu_builder
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.file.metadata.metadata_panel as metadata_panel
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.queue_round.lightning_rounds.lightning_manager as lightning_manager

# ---------------------------------------------------------------------------
# Module-level state for popout widgets/fonts/flags.
# ---------------------------------------------------------------------------
popout_controls = None
popout_up_next = None
popout_currently_playing = None
popout_currently_playing_extra = None
popout_up_next_font = None
popout_button_font = None
popout_current_font = None
popout_current_extra_font = None
resize_after_id = None
popout_searching = False

# All collaborators are called directly on their owning modules (lists /
# windowing / menu_builder / metadata_display / metadata_panel / playlist_ops /
# youtube_ui / search_ops / lightning_manager).
POPOUT_SEARCH_DEFAULT = "SEARCH THEMES"
BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR
HIGHLIGHT_COLOR = state.colors.HIGHLIGHT_COLOR

def _update_up_next_display(*args, **kwargs):
    # Lazy import avoids a circular import: metadata_display imports this module.
    from _app_scripts.file.metadata import metadata_display
    metadata_display.update_up_next_display(*args, **kwargs)


# ---------------------------------------------------------------------------
# POPOUT LAYOUT CONFIGURATION
# ---------------------------------------------------------------------------
# Each entry: {"type": "action"|"widget"|"gap", "id": str, "colspan": int}
#   "action"  — resolved via get_flat_registry() by id; renders as a button
#   "widget"  — one of the special inline widgets (search, youtube, dropdowns…)
#   "gap"     — empty placeholder cell
#
# Special widget IDs:
#   "SEARCH ENTRY"        — text entry for theme search
#   "SEARCH DROPDOWN"     — combobox listing search results
#   "SEARCH QUEUE"        — button to queue/add the selected search result
#   "YOUTUBE DROPDOWN"    — combobox listing downloaded YouTube videos
#   "YOUTUBE QUEUE"       — button to queue the selected YouTube video
#   "LIGHTNING DROPDOWN"  — combobox to pick the lightning round mode
#   "DIFFICULTY DROPDOWN" — combobox to pick infinite-playlist difficulty
#   "toggle_metadata"     — button that shows/hides the currently-playing info area
# ---------------------------------------------------------------------------
POPOUT_LAYOUT_DEFAULT = [
    # ── Marks ───────────────────────────────────────────────────────────────
    {"type": "action", "id": "mute_peek_mark",        "colspan": 1, "custom_label": "MARK"},
    {"type": "action", "id": "tag",                   "colspan": 1},
    {"type": "action", "id": "favorite",              "colspan": 1},
    {"type": "action", "id": "info_popup",            "colspan": 1},
    {"type": "action", "id": "title_popup",           "colspan": 1},
    # ── Blind controls ──────────────────────────────────────────────────────
    {"type": "action", "id": "blind_mark",            "colspan": 1, "custom_label": "MARK"},
    {"type": "action", "id": "blind",                 "colspan": 1},
    {"type": "action", "id": "queue_blind_round",     "colspan": 1},
    {"type": "action", "id": "mute",                  "colspan": 1},
    {"type": "action", "id": "queue_mute_peek_round", "colspan": 1},
    # ── Peek controls ───────────────────────────────────────────────────────
    {"type": "action", "id": "peek_mark",             "colspan": 1, "custom_label": "MARK"},
    {"type": "action", "id": "peek",                  "colspan": 1},
    {"type": "action", "id": "queue_peek_round",      "colspan": 1},
    {"type": "action", "id": "narrow_peek",           "colspan": 1},
    {"type": "action", "id": "widen_peek",            "colspan": 1},
    # ── Bonus questions ─────────────────────────────────────────────────────
    {"type": "action", "id": "bonus_year",            "colspan": 1},
    {"type": "action", "id": "bonus_members",         "colspan": 1},
    {"type": "action", "id": "bonus_score",           "colspan": 1},
    {"type": "action", "id": "bonus_tags",            "colspan": 1},
    {"type": "action", "id": "bonus_multiple",        "colspan": 1},
    {"type": "action", "id": "bonus_rank",            "colspan": 1},
    {"type": "action", "id": "bonus_studio",          "colspan": 1},
    {"type": "action", "id": "bonus_artist",          "colspan": 1},
    {"type": "action", "id": "bonus_song",            "colspan": 1},
    {"type": "action", "id": "bonus_chars",           "colspan": 1},
    {"type": "action", "id": "bonus_freeform",        "colspan": 1},
    # ── Lightning ───────────────────────────────────────────────────────────
    {"type": "widget", "id": "LIGHTNING DROPDOWN",    "colspan": 2},
    {"type": "action", "id": "lightning_start",       "colspan": 1},
    {"type": "action", "id": "lightning_variety",     "colspan": 1},
    {"type": "widget", "id": "DIFFICULTY DROPDOWN",   "colspan": 2},
    # ── YouTube ─────────────────────────────────────────────────────────────
    {"type": "widget", "id": "YOUTUBE DROPDOWN",      "colspan": 2},
    {"type": "widget", "id": "YOUTUBE QUEUE",         "colspan": 1},
    # ── Search ──────────────────────────────────────────────────────────────
    {"type": "widget", "id": "SEARCH ENTRY",          "colspan": 2},
    {"type": "widget", "id": "SEARCH DROPDOWN",       "colspan": 2},
    {"type": "widget", "id": "SEARCH QUEUE",          "colspan": 1},
    # ── Misc ────────────────────────────────────────────────────────────────
    {"type": "action", "id": "dock_player",           "colspan": 1},
    {"type": "action", "id": "censors",               "colspan": 1},
    {"type": "widget", "id": "toggle_metadata",       "colspan": 1},
    {"type": "action", "id": "filter_editor",         "colspan": 1},
    {"type": "action", "id": "end_session",           "colspan": 1},
    # ── Player controls ─────────────────────────────────────────────────────
    {"type": "action", "id": "reroll_next",           "colspan": 1},
    {"type": "action", "id": "play_pause",            "colspan": 1, "icon_only": True},
    {"type": "action", "id": "stop",                  "colspan": 1, "icon_only": True},
    {"type": "action", "id": "previous",              "colspan": 1, "icon_only": True},
    {"type": "action", "id": "next",                  "colspan": 1, "icon_only": True},
]


def _w(name, value):
    globals()[name] = value
    return value


# ---------------------------------------------------------------------------
# Popout info-area toggles + button-state refresh (extracted from main).
# popout_show_* flags live in state.popout; popout widgets are this module's own globals.
# ---------------------------------------------------------------------------
def toggle_show_popout_currently_playing():
    state.popout.show_currently_playing = not state.popout.show_currently_playing
    currently_playing = state.playback.currently_playing
    if state.popout.show_currently_playing:
        if currently_playing.get("data"):
            metadata_panel.update_popout_currently_playling(currently_playing.get("data"))
        popout_currently_playing.configure(pady=0, fg="white")
    else:
        # Show placeholder when hidden with gray text
        popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
        popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
        popout_currently_playing_extra.delete(1.0, tk.END)
        popout_currently_playing_extra.config(state=tk.DISABLED)
    popout_controls.event_generate("<Configure>")


def toggle_show_popout_up_next():
    state.popout.show_up_next = not state.popout.show_up_next
    if state.popout.show_up_next:
        _update_up_next_display(popout_up_next)
    else:
        _update_up_next_display(popout_up_next, clear=True)
    popout_controls.event_generate("<Configure>")


def toggle_show_popout_metadata():
    state.popout.show_metadata = not state.popout.show_metadata
    currently_playing = state.playback.currently_playing
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    lists.button_seleted(popout_buttons_by_name["toggle_metadata"], state.popout.show_metadata)
    if state.popout.show_metadata:
        if state.popout.show_currently_playing and currently_playing.get("data"):
            metadata_panel.update_popout_currently_playling(currently_playing.get("data"))
            popout_currently_playing.configure(pady=0, fg="white")
        elif not state.popout.show_currently_playing:
            # Show placeholder with gray text
            popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
            popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
            popout_currently_playing_extra.delete(1.0, tk.END)
            popout_currently_playing_extra.config(state=tk.DISABLED)
    else:
        # Clear currently playing completely
        popout_currently_playing.configure(text="", fg="white")
        popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
        popout_currently_playing_extra.delete(1.0, tk.END)
        popout_currently_playing_extra.config(state=tk.DISABLED)
    # Always update up-next display
    if state.popout.show_up_next:
        _update_up_next_display(popout_up_next)
    else:
        _update_up_next_display(popout_up_next, clear=False)
    popout_controls.event_generate("<Configure>")


def _refresh_popout_toggles():
    """Refresh the highlight state (and any dynamic text) of all action buttons
    currently displayed in the popout.  Safe to call at any time — silently
    exits if the popout is closed or the button no longer exists."""
    if not popout_controls:
        return
    try:
        flat = menu_builder.get_flat_registry()
    except Exception:
        return
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    for item_id, widget in list(popout_buttons_by_name.items()):
        if not isinstance(widget, tk.Button):
            continue
        try:
            if not widget.winfo_exists():
                continue
        except Exception:
            continue
        reg_item = flat.get(item_id)
        if reg_item is None:
            continue
        # ── Update text for dynamic button_label / label lambdas ─────────────
        bl = reg_item.get("button_label") or reg_item.get("label", "")
        if callable(bl):
            icon = reg_item.get("icon", "")
            if callable(icon):
                icon = icon()
            # apply per-button overrides stashed at creation time
            custom_label = getattr(widget, "_spec_custom_label", "")
            show_icon    = getattr(widget, "_spec_show_icon", True)
            icon_only    = getattr(widget, "_spec_icon_only", False)
            if icon_only and icon:
                new_text = icon
            else:
                if custom_label:
                    bl_text = custom_label
                else:
                    bl_text = bl()
                if not show_icon:
                    icon = ""
                new_text = (f"{icon}{bl_text}".strip() if icon else bl_text).strip()
            try:
                widget.configure(text=new_text)
            except Exception:
                pass
        # ── Update highlight colour for toggle state ──────────────────────────
        toggle_fn = reg_item.get("toggle")
        if toggle_fn:
            try:
                is_on = bool(toggle_fn())
                widget.configure(bg=HIGHLIGHT_COLOR if is_on else "black")
            except Exception:
                pass


def create_popout_controls(title="Popout Controls"):
    """Open the customisable popout controls window.

    Layout is driven by `popout_layout` (user-saved) or `POPOUT_LAYOUT_DEFAULT`.
    All action buttons are resolved from the flat menu registry by ID so they
    are always up-to-date; special widgets are rendered inline.
    """
    global popout_controls, popout_up_next, popout_up_next_font, popout_button_font
    global popout_currently_playing, popout_currently_playing_extra
    global popout_current_font, popout_current_extra_font

    # Local aliases for state + read-once items
    currently_playing = state.playback.currently_playing
    youtube_metadata = state.metadata.youtube_metadata
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    playlist = state.metadata.playlist
    popout_layout = state.popout.layout
    popout_columns = state.popout.columns
    light_mode_options = state.lightning_ui.light_mode_options
    selected_mode = state.lightning_ui.selected_mode
    difficulty_options = state.playlist_ui.difficulty_options
    difficulty_dropdown = state.playlist_ui.difficulty_dropdown
    root = state.widgets.root

    # ── shared cross-widget refs (mutable container for closure capture) ────
    _refs: dict = {}   # "search_dropdown", "yt_video_map", "yt_var"

    # ── shared search state ──────────────────────────────────────────────────
    search_var = tk.StringVar(value=search_ops.search_term if search_ops.search_term else POPOUT_SEARCH_DEFAULT)
    search_results_var = tk.StringVar(value="")
    search_results_map: dict = {}

    # ── shared YouTube state ─────────────────────────────────────────────────
    yt_var = tk.StringVar(value="")
    yt_video_list: list = []
    yt_video_map: dict = {}
    for _key, _val in youtube_metadata.get("videos", {}).items():
        if os.path.exists(os.path.join("youtube", _val["filename"])):
            _title = _val.get("custom_title") or _val.get("title")
            yt_video_list.append(_title)
            yt_video_map[_title] = _key

    # ── close handler ────────────────────────────────────────────────────────
    def on_popout_close():
        global popout_controls, popout_up_next, popout_currently_playing, popout_currently_playing_extra
        lists.button_seleted(state.widgets.popout_controls_button, False)
        popout_buttons_by_name.clear()
        popout_controls.destroy()
        popout_controls = _w('popout_controls', None)
        popout_up_next = _w('popout_up_next', None)
        popout_currently_playing = _w('popout_currently_playing', None)
        popout_currently_playing_extra = _w('popout_currently_playing_extra', None)

    # Toggle: close if already open
    if popout_controls:
        on_popout_close()
        return

    # ── create window ────────────────────────────────────────────────────────
    popout_controls = _w('popout_controls', tk.Toplevel())
    popout_controls.title(title)
    popout_controls.configure(bg=BACKGROUND_COLOR)

    popout_width, popout_height = 1440, 810
    popout_controls.geometry(f"{popout_width}x{popout_height}")
    root.update_idletasks()
    main_width = root.winfo_width()
    offset_x = (main_width - popout_width) // 2
    windowing.get_window_position_and_setup(popout_controls, offset_x=offset_x, offset_y=50)
    popout_controls.protocol("WM_DELETE_WINDOW", on_popout_close)

    # ── fonts ────────────────────────────────────────────────────────────────
    popout_up_next_font        = _w('popout_up_next_font', font.Font(family="Helvetica", size=20, weight="bold"))
    popout_current_font        = _w('popout_current_font', font.Font(family="Helvetica", size=25, weight="bold"))
    popout_current_extra_font  = _w('popout_current_extra_font', font.Font(family="Helvetica", size=10, weight="bold"))
    popout_button_font         = _w('popout_button_font', font.Font(family="Helvetica", size=20, weight="bold"))

    # ── resize handler ───────────────────────────────────────────────────────
    def on_popout_resize(event):
        global resize_after_id
        def do_resize():
            if not popout_controls or not popout_currently_playing:
                return
            width  = popout_controls.winfo_width()
            height = popout_controls.winfo_height()
            min_dim = min(width * 0.5, height)
            popout_button_font.configure(size=max(10, int(min_dim / 25)))
            if state.popout.show_metadata:
                popout_up_next_font.configure(size=max(10, int(min_dim / 30)))
                popout_current_font.configure(size=max(10, int(min_dim / 25)))
                popout_current_extra_font.configure(size=max(10, int(min_dim / 50)))
                popout_currently_playing.configure(wraplength=int(width * 0.95))
                if popout_up_next:
                    metadata_display.adjust_up_next_height(popout_up_next, True)
            else:
                popout_up_next_font.configure(size=1)
                popout_current_font.configure(size=1)
                popout_current_extra_font.configure(size=1)
                popout_currently_playing.configure(wraplength=0)
            for w in popout_buttons_by_name.values():
                if isinstance(w, tk.Button):
                    w.configure(font=popout_button_font)
        if resize_after_id is not None:
            try:
                popout_controls.after_cancel(resize_after_id)
            except Exception:
                pass
        resize_after_id = _w('resize_after_id', popout_controls.after(150, do_resize))
    popout_controls.bind("<Configure>", on_popout_resize)

    # ── determine active layout and column count ──────────────────────────────
    _layout  = popout_layout if (popout_layout is not None) else POPOUT_LAYOUT_DEFAULT
    _columns = popout_columns

    # ── currently-playing info area ───────────────────────────────────────────
    row = 0
    popout_currently_playing = _w('popout_currently_playing', tk.Label(
        popout_controls, font=popout_current_font, bg=BACKGROUND_COLOR, fg="white",
        text="", anchor="center", justify="center", padx=5, pady=5,
    ))
    popout_currently_playing.grid(row=row, column=0, columnspan=_columns,
                                   sticky="nsew", padx=5, pady=(10, 10))
    popout_controls.grid_rowconfigure(row, weight=0)
    popout_currently_playing.bind("<ButtonRelease-1>",
                                   lambda e: toggle_show_popout_currently_playing())
    row += 1

    popout_currently_playing_extra = _w('popout_currently_playing_extra', tk.Text(
        popout_controls, font=popout_current_extra_font, bg=BACKGROUND_COLOR,
        fg="white", bd=0, height=4,
    ))
    popout_currently_playing_extra.grid(row=row, column=0, columnspan=_columns,
                                         sticky="nsew", padx=5, pady=(0, 0))
    popout_controls.grid_rowconfigure(row, weight=0)
    popout_currently_playing_extra.tag_configure("white", foreground="white", justify="center")
    popout_currently_playing_extra.bind("<ButtonRelease-1>",
                                        lambda e: toggle_show_popout_currently_playing())
    row += 1

    # ── helper: build button text from a registry item + optional spec overrides ─
    def _btn_text(item, spec=None):
        icon = item.get("icon", "")
        if callable(icon):
            icon = icon()
        lbl = item.get("button_label") or item.get("label", "")
        if callable(lbl):
            lbl = lbl()
        if spec is not None:
            if spec.get("custom_label", ""):
                lbl = spec["custom_label"]
            if not spec.get("show_icon", True):
                icon = ""
            if spec.get("icon_only", False) and icon:
                return icon
        return (f"{icon}{lbl}".strip() if icon else str(lbl)).strip()

    # ── helper: wrap a command to refresh toggles afterward ───────────────────
    def _wrap(cmd):
        def _inner():
            cmd()
            _refresh_popout_toggles()
        return _inner

    # ── flat registry (evaluated once at window-open time) ───────────────────
    flat_reg = menu_builder.get_flat_registry()

    # ── layout rendering ──────────────────────────────────────────────────────
    row += 1   # leave a visual gap row between info area and buttons
    col = 0

    for spec in _layout:
        itype   = spec.get("type", "action")
        item_id = spec.get("id", "")
        colspan = max(1, spec.get("colspan", 1))

        # wrap to next row if needed
        if col + colspan > _columns:
            row += 1
            col = 0

        # ── GAP ──────────────────────────────────────────────────────────────
        if itype == "gap":
            tk.Label(popout_controls, text="", bg=BACKGROUND_COLOR).grid(
                row=row, column=col, columnspan=colspan, sticky="nsew")
            col += colspan
            continue

        # ── SPECIAL WIDGET ───────────────────────────────────────────────────
        if itype == "widget":
            widget = None

            # ─ Search entry ──────────────────────────────────────────────────
            if item_id == "SEARCH ENTRY":
                w = tk.Entry(
                    popout_controls, textvariable=search_var,
                    font=popout_button_font, bg="black", fg="white",
                    insertbackground="white",
                )
                def _on_key(event=None, _sv=search_var, _rv=search_results_var,
                            _rm=search_results_map):
                    q = _sv.get().strip()
                    if not q or q == POPOUT_SEARCH_DEFAULT:
                        search_ops.search_term = ""
                        _rm.clear()
                        _rv.set("")
                        dd = _refs.get("search_dropdown")
                        if dd:
                            dd["values"] = []
                        return
                    search_ops.search_term = q
                    search_ops.search_results = search_ops.search_playlist(q)
                    titles = [lists.get_title(f, f) for f in search_ops.search_results]
                    _rm.clear()
                    for i, f in enumerate(search_ops.search_results):
                        _rm[titles[i]] = f
                    dd = _refs.get("search_dropdown")
                    if dd:
                        dd["values"] = titles
                    _rv.set(titles[0] if titles else "")
                def _on_focus_in(e, _sv=search_var):
                    global popout_searching
                    popout_searching = _w('popout_searching', True)
                    if _sv.get() == POPOUT_SEARCH_DEFAULT:
                        _sv.set("")
                def _on_focus_out(e, _sv=search_var):
                    global popout_searching
                    popout_searching = _w('popout_searching', False)
                    if not _sv.get().strip():
                        _sv.set(POPOUT_SEARCH_DEFAULT)
                w.bind("<FocusIn>",   _on_focus_in)
                w.bind("<FocusOut>",  _on_focus_out)
                w.bind("<KeyRelease>", _on_key)
                widget = w

            # ─ Search results dropdown ───────────────────────────────────────
            elif item_id == "SEARCH DROPDOWN":
                titles = [lists.get_title(f, f) for f in search_ops.search_results]
                for i, f in enumerate(search_ops.search_results):
                    search_results_map[titles[i]] = f
                w = ttk.Combobox(
                    popout_controls, values=titles,
                    textvariable=search_results_var,
                    font=popout_button_font, height=10,
                    style="Black.TCombobox", state="readonly",
                )
                def _on_sd_change(event, _w=w):
                    _w.selection_clear()
                    _w.icursor(tk.END)
                w.bind("<<ComboboxSelected>>", _on_sd_change)
                _refs["search_dropdown"] = w
                widget = w

            # ─ Search queue button ───────────────────────────────────────────
            elif item_id == "SEARCH QUEUE":
                def _queue_search(_rv=search_results_var, _rm=search_results_map):
                    sel = _rv.get()
                    if sel and sel in _rm:
                        fn = _rm[sel]
                        if playlist.get("infinite"):
                            if fn in search_ops.search_results:
                                search_ops.add_search_playlist(search_ops.search_results.index(fn) + 1)
                            search_var.set(POPOUT_SEARCH_DEFAULT)
                            _rv.set("")
                            _rm.clear()
                            dd = _refs.get("search_dropdown")
                            if dd:
                                dd["values"] = []
                        else:
                            if fn in search_ops.search_results:
                                search_ops.set_search_queue(search_ops.search_results.index(fn) + 1)
                    b = popout_buttons_by_name.get("SEARCH QUEUE")
                    if b:
                        lists.button_seleted(b, bool(search_ops.search_queue))
                btn_text = "ADD NEXT" if playlist.get("infinite") else "QUEUE NEXT"
                w = tk.Button(
                    popout_controls, text=btn_text,
                    font=popout_button_font, command=_queue_search,
                    bg="black", fg="white",
                )
                widget = w

            # ─ YouTube video dropdown ────────────────────────────────────────
            elif item_id == "YOUTUBE DROPDOWN":
                w = ttk.Combobox(
                    popout_controls, values=yt_video_list,
                    textvariable=yt_var,
                    font=popout_button_font, height=10,
                    style="Black.TCombobox", state="readonly",
                )
                def _yt_set_default(_w=w):
                    _w.set("YOUTUBE VIDEOS")
                w.after(100, _yt_set_default)
                def _on_yt_change(event, _w=w):
                    _w.selection_clear()
                    _w.icursor(tk.END)
                w.bind("<<ComboboxSelected>>", _on_yt_change)
                _refs["yt_dropdown"] = w
                widget = w

            # ─ YouTube queue button ──────────────────────────────────────────
            elif item_id == "YOUTUBE QUEUE":
                def _queue_yt(_ym=yt_video_map):
                    dd = _refs.get("yt_dropdown")
                    if not dd:
                        return
                    sel = dd.get()
                    if sel and sel in _ym:
                        vid_id = _ym[sel]
                        youtube_ui.show_youtube_playlist()
                        keys = list(youtube_ui._youtube_playlist.keys())
                        try:
                            idx = keys.index(vid_id)
                        except ValueError:
                            idx = None
                        if idx is not None:
                            youtube_ui.load_youtube_video(idx)
                    b = popout_buttons_by_name.get("YOUTUBE QUEUE")
                    if b:
                        lists.button_seleted(b, bool(state.playback.youtube_queue))
                w = tk.Button(
                    popout_controls, text="QUEUE NEXT",
                    font=popout_button_font, command=_queue_yt,
                    bg="black", fg="white",
                )
                widget = w

            # ─ Lightning mode dropdown ───────────────────────────────────────
            elif item_id == "LIGHTNING DROPDOWN":
                w = ttk.Combobox(
                    popout_controls,
                    values=[disp for _, disp in light_mode_options],
                    font=popout_button_font,
                    height=len(light_mode_options),
                    style="Black.TCombobox", state="readonly",
                )
                w.set(selected_mode.get())
                def _on_ld_change(event, _w=w):
                    ld = popout_buttons_by_name.get("LIGHTNING DROPDOWN")
                    if ld:
                        selected_mode.set(ld.get())
                        if state.lightning.light_mode:
                            lightning_manager.select_lightning_mode()
                    _w.selection_clear()
                    _w.icursor(tk.END)
                w.bind("<<ComboboxSelected>>", _on_ld_change)
                widget = w

            # ─ Difficulty dropdown ───────────────────────────────────────────
            elif item_id == "DIFFICULTY DROPDOWN":
                w = ttk.Combobox(
                    popout_controls, values=difficulty_options,
                    font=popout_button_font,
                    height=len(difficulty_options),
                    style="Black.TCombobox", state="readonly",
                )
                w.set(difficulty_options[playlist.get("difficulty", 2)])
                def _on_diff_change(event, _w=w):
                    dd = popout_buttons_by_name.get("DIFFICULTY DROPDOWN")
                    if dd:
                        difficulty_dropdown.set(dd.get())
                        playlist_ops.select_difficulty()
                    _w.selection_clear()
                    _w.icursor(tk.END)
                w.bind("<<ComboboxSelected>>", _on_diff_change)
                if not playlist.get("infinite"):
                    w.grid_remove()
                widget = w

            # ─ Metadata toggle button ────────────────────────────────────────
            elif item_id == "toggle_metadata":
                w = tk.Button(
                    popout_controls, text="METADATA",
                    font=popout_button_font,
                    command=toggle_show_popout_metadata,
                    bg=HIGHLIGHT_COLOR if state.popout.show_metadata else "black",
                    fg="white",
                )
                widget = w

            if widget is not None:
                widget.grid(row=row, column=col, columnspan=colspan,
                            sticky="nsew", padx=2, pady=1)
                popout_buttons_by_name[item_id] = widget
            col += colspan
            continue

        # ── ACTION BUTTON ─────────────────────────────────────────────────────
        if itype == "action":
            reg_item = flat_reg.get(item_id)
            if reg_item is None:
                col += colspan
                continue
            btn_text   = _btn_text(reg_item, spec)
            cmd        = reg_item.get("command")
            toggle_fn  = reg_item.get("toggle")
            wrapped    = _wrap(cmd) if cmd else (lambda: None)
            btn_bg     = HIGHLIGHT_COLOR if (toggle_fn and toggle_fn()) else "black"
            btn = tk.Button(
                popout_controls, text=btn_text,
                fg="white", bg=btn_bg,
                command=wrapped,
                font=popout_button_font,
                justify="center",
            )
            # stash overrides so _refresh_popout_toggles can re-apply them
            btn._spec_show_icon    = spec.get("show_icon", True)
            btn._spec_custom_label = spec.get("custom_label", "")
            btn._spec_icon_only    = spec.get("icon_only", False)
            btn.grid(row=row, column=col, columnspan=colspan,
                     sticky="nsew", padx=2, pady=1)
            popout_buttons_by_name[item_id] = btn
            col += colspan
            continue

    # ── up-next text area ─────────────────────────────────────────────────────
    row += 1
    popout_up_next = _w('popout_up_next', tk.Text(
        popout_controls, font=popout_up_next_font, bg=BACKGROUND_COLOR,
        fg="white", wrap="word", bd=0, height=1,
    ))
    popout_up_next.grid(row=row, column=0, columnspan=_columns,
                        sticky="nsew", padx=5, pady=(5, 10))
    popout_controls.grid_rowconfigure(row, weight=0)
    popout_up_next.tag_configure("bold",   font=popout_up_next_font.copy())
    popout_up_next.tag_configure("white",  foreground="white",  justify="center")
    popout_up_next.tag_configure("center", foreground="gray",   justify="center")
    popout_up_next.bind("<ButtonRelease-1>", lambda e: toggle_show_popout_up_next())

    # ── grid weight ───────────────────────────────────────────────────────────
    up_next_row = row
    for i in range(_columns):
        popout_controls.grid_columnconfigure(i, weight=1)
    # Info rows and the gap row have fixed / natural height; only button rows grow
    popout_controls.grid_rowconfigure(0, weight=0)                      # currently-playing label
    popout_controls.grid_rowconfigure(1, weight=0)                      # currently-playing extra text
    popout_controls.grid_rowconfigure(2, weight=0, minsize=6)           # visual gap (no widget)
    for i in range(3, up_next_row):                                     # button rows
        popout_controls.grid_rowconfigure(i, weight=1)
    popout_controls.grid_rowconfigure(up_next_row, weight=1)  # up-next expands too

    lists.button_seleted(state.widgets.popout_controls_button, True)
    if currently_playing.get("data"):
        metadata_panel.update_popout_currently_playling(currently_playing.get("data"))
        popout_controls.after(500, metadata_display.up_next_text)
