"""Menu / toolbar builder and keyboard-shortcut infrastructure.

Builds tk.Menus from the declarative registry (_app_scripts/ui/menu_registry.py),
resolves shortcut accelerators, binds shortcuts to the root window, maintains the
runtime key->command dispatch table, and constructs the first-row toolbar buttons
+ search bar. The GUI factory helpers ``create_button`` and ``attach_menu_tooltip``
live here too.

Shortcut overrides live in ``state.shortcuts.config``; the runtime shortcut
dispatch table lives in ``state.shortcuts.dispatch``. The toolbar button widgets
this module creates live on ``state.widgets``; the search bar entry lives on the
search module (``search_ops.search_bar_entry``).
"""

import os
from core.game_state import state
from _app_scripts.popout import popout_window
from _app_scripts.popout import popout_layout_editor
from .scaling import scl
import tkinter as tk
from tkinter import ttk

from . import windowing
from . import menu_registry
from . import lists
from . import drag_and_drop
from ..playback import cache_download
from ..playback import dock_player
from ..file import tooltip
import _app_scripts.playlists.infinite as infinite
import _app_scripts.search.search as search_ops

# Fonts mirrored from main (fixed values, matching the duplicate-constant
# convention used across the extracted modules).
ROOT_FONT = ("Segoe UI", scl(9, "UI"))
MENU_FONT = ("Segoe UI", scl(10, "UI"))

# --- GUI factory helpers (relocated from main; used only by this module) ---

def create_button(frame, label, func, add_space=False, enabled=False,
                  help_title="", help_text="", right_click=None):
    """Creates a button with optional tooltip on hover and a configurable right-click action."""
    bg = state.colors.HIGHLIGHT_COLOR if enabled else "black"
    hover_bg = "gray35" if not enabled else "gray45"

    button = tk.Button(frame, text=label, command=func, bg=bg, fg="white", font=ROOT_FONT,
                       borderwidth=0, padx=scl(6, "UI"), pady=scl(3, "UI"), relief="flat")
    button.pack(side="left", padx=0)

    # Tooltip on hover (must be created BEFORE hover bindings so our add='+' runs after)
    tooltip_text = (f"{help_title}\n\n{help_text}" if help_title and help_text
                    else help_text or help_title)
    if tooltip_text:
        tooltip.ToolTip(button, tooltip_text)

    # Hover highlight — bound with add='+' so ToolTip's bindings still fire too
    def _on_enter(e, b=button, hbg=hover_bg):
        b.config(bg=hbg)
    def _on_leave(e, b=button, obg=bg):
        b.config(bg=obg)
    button.bind("<Enter>", _on_enter, add="+")
    button.bind("<Leave>", _on_leave, add="+")

    # Right-click: (action, label_func) tuple → call action then flash label for 1 s
    if right_click is not None:
        if isinstance(right_click, tuple):
            _rc_action, _rc_label = right_click
            if not callable(_rc_action) or not _rc_label:
                return
            def _on_right_click(event, btn=button, act=_rc_action, lf=_rc_label):
                act()
                flash = lf() if callable(lf) else lf
                if not getattr(btn, "_flash_after_id", None):
                    # Not currently flashing — safe to capture real original
                    btn._flash_orig = btn.cget("text")
                else:
                    # Already flashing — cancel timer, keep the already-stored original
                    btn.after_cancel(btn._flash_after_id)
                btn.config(text=flash)
                btn._flash_after_id = btn.after(1000, lambda b=btn: (
                    b.config(text=b._flash_orig),
                    setattr(b, "_flash_after_id", None)
                ))
            button.bind("<Button-3>", _on_right_click)
        else:
            button.bind("<Button-3>", lambda event: right_click())

    return button


_menu_tooltip_win = [None]
_menu_tooltip_after = [None]


def dismiss_menu_tooltip():
    """Cancel any pending menu-tooltip timer and destroy the tooltip window.

    Shared by the hover handlers and main's on_app_close cleanup; after-ids are
    interpreter-global so any widget's after_cancel works.
    """
    if _menu_tooltip_after[0]:
        try:
            state.widgets.root.after_cancel(_menu_tooltip_after[0])
        except Exception:
            pass
        _menu_tooltip_after[0] = None
    if _menu_tooltip_win[0]:
        try:
            _menu_tooltip_win[0].destroy()
        except Exception:
            pass
        _menu_tooltip_win[0] = None


def attach_menu_tooltip(menu, tooltips):
    """Show a tooltip near the cursor after hovering 1 second over a menu item.
    tooltips: dict mapping integer item index -> tooltip string."""
    def on_select(event):
        dismiss_menu_tooltip()
        try:
            idx = menu.index("active")
        except Exception:
            return
        if idx is None or idx not in tooltips or not tooltips[idx]:
            return
        x = menu.winfo_pointerx() + 18
        y = menu.winfo_pointery() + 6
        text = tooltips[idx]
        def show_tooltip():
            _menu_tooltip_after[0] = None
            try:
                tw = tk.Toplevel()
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                tw.attributes("-topmost", True)
                tk.Label(tw, text=text, justify="left", bg="#ffffcc", fg="black",
                         relief="solid", bd=1, font=("Arial", 9), wraplength=320, padx=5, pady=3).pack()
                _menu_tooltip_win[0] = tw
            except Exception:
                pass
        _menu_tooltip_after[0] = menu.after(1000, show_tooltip)

    def on_hide(event):
        dismiss_menu_tooltip()

    menu.bind("<<MenuSelect>>", on_select)
    menu.bind("<Unmap>", on_hide)


def build_menu(parent_menu, items):
    """Build a tk.Menu from a declarative list of item dicts.

    Each item is either the string "---" (separator) or a dict with keys:
      id              : str  — stable identifier for shortcut binding, popout layout, flat lookup
      icon            : str  — emoji/symbol prepended to the label (optional; kept separate for button use)
      label           : str  — display text (required unless type=="radiogroup"); rendered as "{icon}  {label}"
      button_label    : str  — short text for popout buttons (optional; falls back to label)
      command         : callable — action on click
      tooltip         : str  — hover tooltip text (optional)
      (shortcut display is auto-resolved from DEFAULT_SHORTCUTS by item id — not stored per item)
      toggle    : callable -> bool — if present, item becomes a checkbutton;
                  return value drives active highlight
      condition : callable -> bool — if present and returns False, item is skipped
      submenu   : list  — if present, item becomes a cascade; value is a nested items list
      type      : "radiogroup" — special: generates one radiobutton per option
        options : list[str]   — radio labels
        variable: callable -> int — returns current selected index
        command : callable(int) — called with selected index
    """
    # Attach to the menu widget itself so vars live exactly as long as the menu does.
    # Without this, CPython can GC the BooleanVar/StringVar while Tcl still holds
    # a reference, causing TclErrors when the menu or root window is closed.
    _booleans = []
    parent_menu._keep_vars = _booleans

    def _make_menu():
        return tk.Menu(parent_menu, tearoff=0, bg="black", fg="white",
                       activebackground=state.colors.HIGHLIGHT_COLOR, activeforeground="white",
                       font=MENU_FONT)

    def _add_items(menu, item_list):
        tooltip_map = {}
        visual_idx  = 0          # actual menu entry index (separators count)

        def _render_label(item):
            """Compose visible menu label + right-aligned accelerator text.
            Returns (label_text, accel_text_or_empty)."""
            raw_label = item["label"]() if callable(item.get("label")) else item.get("label", "")
            icon = item.get("icon", "")
            if callable(icon):
                icon = icon()
            item_id = item.get("id")
            key = get_shortcut(item_id) if item_id else None
            sd  = _shortcut_display_name(key) if key else None
            text = f"{icon}  {raw_label}" if icon else raw_label

            accel_parts = []
            if sd:
                accel_parts.append(sd)
            cycle_pos = item.get("cycle_pos")
            if cycle_pos:
                cyc_id, pos = cycle_pos
                cyc_key = get_shortcut(cyc_id)
                if cyc_key:
                    cyc_sd = _shortcut_display_name(cyc_key)
                    accel_parts.append(f"{cyc_sd}\u21bb{pos}")

            accel = "   ".join(accel_parts)
            return text, accel

        for item in item_list:
            # --- separator ---
            if item == "---" or (isinstance(item, dict) and item.get("type") == "separator"):
                if isinstance(item, dict) and "condition" in item and not item["condition"]():
                    continue
                menu.add_separator()
                visual_idx += 1
                continue

            # --- condition gate ---
            if "condition" in item and not item["condition"]():
                continue

            # --- radiogroup ---
            if item.get("type") == "radiogroup":
                cur = item["variable"]()
                rv  = tk.StringVar(value=item["options"][cur])
                _booleans.append(rv)
                start_idx = visual_idx
                for i, opt in enumerate(item["options"]):
                    menu.add_radiobutton(
                        label=opt, variable=rv, value=opt,
                        command=(lambda idx=i, _item=item: _item["command"](idx)) if "command" in item else None,
                        selectcolor=state.colors.HIGHLIGHT_COLOR,
                    )
                    if "tooltip" in item:
                        tooltip_map[visual_idx] = item["tooltip"]
                    visual_idx += 1
                menu.entryconfig(start_idx + cur, background=state.colors.HIGHLIGHT_COLOR, foreground="white")
                continue

            rendered, accel = _render_label(item)

            # --- cascade (submenu) ---
            if "submenu" in item:
                sub = _make_menu()
                _add_items(sub, item["submenu"])
                menu.add_cascade(label=rendered, menu=sub, accelerator=accel)
                if "toggle" in item and item["toggle"]():
                    menu.entryconfig(visual_idx, background=state.colors.HIGHLIGHT_COLOR, foreground="white")
                if "tooltip" in item:
                    tooltip_map[visual_idx] = item["tooltip"]
                visual_idx += 1
                continue

            # --- toggle (checkbutton) ---
            if "toggle" in item:
                is_on = item["toggle"]()
                bv = tk.BooleanVar(value=is_on)
                _booleans.append(bv)
                menu.add_checkbutton(
                    label=rendered,
                    accelerator=accel,
                    variable=bv,
                    command=item["command"],
                    selectcolor=state.colors.HIGHLIGHT_COLOR,
                )
                if is_on:
                    menu.entryconfig(visual_idx, background=state.colors.HIGHLIGHT_COLOR, foreground="white")
                if "tooltip" in item:
                    tooltip_map[visual_idx] = item["tooltip"]
                visual_idx += 1
                continue

            # --- plain command ---
            menu.add_command(label=rendered, accelerator=accel, command=item["command"])
            if "tooltip" in item:
                tooltip_map[visual_idx] = item["tooltip"]
            visual_idx += 1

        if tooltip_map:
            attach_menu_tooltip(menu, tooltip_map)

    _add_items(parent_menu, items)

# ---------------------------------------------------------------------------
# SHORTCUT INFRASTRUCTURE
# ---------------------------------------------------------------------------

# Default shortcuts: {id → key_char_or_name}.
# Single-char shortcuts are the literal character pynput returns via key.char.
# "BackSpace" is the only special-key name currently used.
DEFAULT_SHORTCUTS = {
    # ── Playlist / Queue ──────────────────────────────────────────────────
    "view_playlist":        "p",
    "lightning_variety":    "v",
    "show_youtube":         "y",
    "show_fixed_lightning": "f",
    # ── Popups ────────────────────────────────────────────────────────────
    "info_popup":           "i",
    "title_popup":          "o",
    "end_session":          "e",
    # ── Toggle / Overlays ─────────────────────────────────────────────────
    "blind":                "BackSpace",
    "peek":                 "=",
    "narrow_peek":          "[",
    "widen_peek":           "]",
    "mute":                 "m",
    "censors":              "c",
    "enable_shortcuts":     "`",
    "view_shortcuts":       None,
    "close_list":           "k",
    # ── Theme ─────────────────────────────────────────────────────────────
    "tag":                  "t",
    "favorite":             "*",
    # ── Bonus questions (direct) ──────────────────────────────────────────
    "bonus_multiple":       "u",
    "bonus_tags":           "n",
    "bonus_chars":          "j",
    # ── Cycling (hidden) ──────────────────────────────────────────────────
    "cycle_blind_peek":     "b",
    "cycle_light_mode":     "l",
    "cycle_guess_stats":    "g",
    "cycle_guess_other":    "h",
    # ── Navigation (hidden) ───────────────────────────────────────────────
    "dock_player":          "d",
    "search_themes":        "s",
    "reroll_next":          "r",
    # ── Scoreboard (hidden) ───────────────────────────────────────────────
    "scoreboard_align":     "a",
    "scoreboard_extend":    "x",
    "scoreboard_shrink":    "z",
    "scoreboard_grow":      "w",
    "scoreboard_toggle":    "q",
}

# Human-readable display overrides for special key names
_SHORTCUT_DISPLAY = {
    "BackSpace": "Bksp",
    "space":     "Space",
    "esc":       "Esc",
    "right":     "Right",
    "left":      "Left",
    "up":        "Up",
    "down":      "Down",
    "tab":       "Tab",
    "enter":     "Enter",
}

def _shortcut_display_name(key_str):
    """Return a human-readable label for a key string (e.g. 'BackSpace' → 'Bksp')."""
    return _SHORTCUT_DISPLAY.get(key_str, key_str) if key_str else None

# Hardcoded special-key bindings that are handled directly in on_release/on_press via keyboard.Key.*
# These cannot be remapped through the shortcut editor — shown as locked read-only rows.
# Format: {id: (key_string, label, note_or_None)}
FIXED_SHORTCUTS = {
    "play_pause":    ("space", "Play / Pause",         None),
    "stop":          ("esc",   "Stop",                 None),
    "next":          ("right", "Next Track",           None),
    "previous":      ("left",  "Previous Track",       None),
    "fullscreen":    ("tab",   "Toggle Fullscreen",    None),
    "list_enter":    ("enter", "Select from List",     None),
    "list_move_up":  ("up",    "Navigate List Up",     None),
    "list_move_down":("down",  "Navigate List Down",   None),
}

# Currently active bindings: {id → key_string} — used by shortcuts editor for display
bound_shortcuts = {}

def get_shortcut(item_id, default=None):
    """Return the active shortcut key for item_id.

    Resolves: state.shortcuts.config override → DEFAULT_SHORTCUTS → default argument.
    """
    if not item_id:
        return default
    return state.shortcuts.config.get(item_id, DEFAULT_SHORTCUTS.get(item_id, default))


def get_flat_registry():
    """Return a flat {id: item} dict across all menus and submenus (items with an id only).

    Useful for shortcut binding, popout layout lookup, and the shortcuts editor.
    Includes hidden and scoreboard items — everything with an id.
    """
    flat = {}

    def _walk(item_list):
        for item in item_list:
            if item == "---":
                continue
            if not isinstance(item, dict):
                continue
            if "id" in item:
                flat[item["id"]] = item
            if "submenu" in item:
                _walk(item["submenu"])

    registry = menu_registry.get_menu_registry()
    for section_items in registry.values():
        _walk(section_items)
    return flat

def bind_shortcuts():
    """Bind all registry shortcuts to root, respecting user overrides.

    Safe to call multiple times — unbinds old key before binding new one.
    Only binds items that have an 'id' with a shortcut in DEFAULT_SHORTCUTS or state.shortcuts.config.
    Does not bind items whose shortcut has been cleared (set to "" in state.shortcuts.config).
    """
    flat = get_flat_registry()
    for item_id, item in flat.items():
        key = get_shortcut(item_id)

        # Unbind previous binding for this id if key changed
        old_key = bound_shortcuts.get(item_id)
        if old_key and old_key != key:
            try:
                state.widgets.root.unbind(f"<{old_key}>")
            except Exception:
                pass
            bound_shortcuts.pop(item_id, None)

        if not key:
            continue

        cmd = item.get("command")
        if not cmd:
            continue

        try:
            state.widgets.root.bind(f"<{key}>", lambda e, c=cmd: c())
            bound_shortcuts[item_id] = key
        except Exception:
            pass

def rebuild_shortcut_dispatch():
    """Build the in-memory key → command dispatch table.

    Call once at startup (after all functions are defined) and again any time
    state.shortcuts.config is modified so on_release always uses the current bindings.
    """
    flat = get_flat_registry()
    dispatch = {}
    for item_id, item in flat.items():
        key = get_shortcut(item_id)   # state.shortcuts.config override → DEFAULT_SHORTCUTS → None
        cmd = item.get("command")
        if key and cmd:
            dispatch[key] = cmd
    state.shortcuts.dispatch = dispatch

# ---------------------------------------------------------------------------
# REGISTRY HELPERS — computed predicates used as `condition` / `command` lambdas
#                   in the theme menu submenus below.
# ---------------------------------------------------------------------------

def _cp_is_local_file():
    """Return True if the currently playing file exists in the local directory."""
    f = state.playback.currently_playing.get("filename", "")
    return bool(f and f in state.metadata.directory_files and os.path.exists(state.metadata.directory_files.get(f, "")))

def _cp_is_stream():
    """Return True if the currently playing file is an AnimeThemes stream (not locally stored)."""
    f = state.playback.currently_playing.get("filename", "")
    return bool(f and cache_download.is_animethemes_stream_file(f) and not _cp_is_local_file())

def download_current_theme():
    """Download or move the currently playing theme to the local directory."""
    f = state.playback.currently_playing.get("filename", "")
    if not f:
        return
    if cache_download.get_cached_file_path(f) is not None:
        cache_download.move_cached_file_to_directory(f, None)
    else:
        cache_download.download_animethemes_file(f, None)

def _open_toolbar_menu(name: str, button: tk.Button, section_key: str):
    """Open a registry-backed toolbar dropdown with toggle behaviour.

    tk_popup() blocks via Tcl's tkwait until the menu is dismissed.
    When it returns, the dismiss-click has been handled by the OS but the
    corresponding Tk ButtonRelease / command= event is still pending in the
    queue.  We check winfo_pointerxy() right here — synchronously, before
    the event loop resumes — to set a suppress flag that command= will see.
    """
    if getattr(button, '_suppress_open', False):
        button._suppress_open = False
        return

    registry = menu_registry.get_menu_registry()
    m = tk.Menu(state.widgets.root, tearoff=0, bg="black", fg="white",
                activebackground=state.colors.HIGHLIGHT_COLOR, activeforeground="white", font=MENU_FONT)
    build_menu(m, registry[section_key])
    windowing.popup_menu(m, button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    # Menu just closed.  If the pointer is still over this button, the button
    # click dismissed it — suppress the pending command= so we don't reopen.
    try:
        px, py = state.widgets.root.winfo_pointerxy()
        bx, by = button.winfo_rootx(), button.winfo_rooty()
        if bx <= px < bx + button.winfo_width() and by <= py < by + button.winfo_height():
            button._suppress_open = True
    except Exception:
        pass


def create_first_row_buttons():
    for widget in list(state.widgets.first_row_frame.winfo_children()):
        try:
            widget.destroy()
        except Exception:
            pass

    _rc = menu_registry.get_menu_registry().get("_right_click", {})

    state.widgets.collapse_button = create_button(state.widgets.first_row_frame, "▼", dock_player.toggle_player_collapse, False,
                                help_text="Collapses or expands the player info columns. "
                                "Click to toggle between collapsed (arrow up) and expanded (arrow down) states.")

    state.widgets.dock_button = create_button(state.widgets.first_row_frame, "DOCK", dock_player.dock_player, True,
                                help_text="Docks the player on the bottom of the screen and makes it semitransparent. " +
                                "Click again to undock.\n\nWhen shortcuts are enabled it will" + 
                                " hide it at the bottom of the screen. Otherwise it will return to its " + 
                                "previous position.\n\nIt can be useful if you need to share any "+
                                "information on the player, or use any buttons that don't have "+
                                "shortcuts. Also if you are just browsing.")

    def show_popout_menu(event=None):
        button = state.widgets.popout_controls_button
        if getattr(button, '_suppress_open', False):
            button._suppress_open = False
            return
        m = tk.Menu(state.widgets.root, tearoff=0, bg="black", fg="white",
                    activebackground=state.colors.HIGHLIGHT_COLOR, activeforeground="white", font=MENU_FONT)
        m.add_command(label="🗖  Open Popout", command=popout_window.create_popout_controls)
        m.add_command(label="⚙  Configure Layout", command=popout_layout_editor.open_popout_layout_editor)
        windowing.popup_menu(m, button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        try:
            px, py = state.widgets.root.winfo_pointerxy()
            bx, by = button.winfo_rootx(), button.winfo_rooty()
            if bx <= px < bx + button.winfo_width() and by <= py < by + button.winfo_height():
                button._suppress_open = True
        except Exception:
            pass

    state.widgets.popout_controls_button = create_button(state.widgets.first_row_frame, "🗖POPOUT▾", show_popout_menu, True,
                                help_text="Open or configure the popout controls window.\n"
                                "Right-Click Shortcut: Open Popout",
                                right_click=_rc.get("popout"))
    
    
    def show_file_menu(event=None):
        _open_toolbar_menu("file", state.widgets.file_menu_button, "file")

    state.widgets.file_menu_button = create_button(state.widgets.first_row_frame, "FILE▾", show_file_menu, True,
                                help_text="Opens the file menu with options for choosing a directory, importing/exporting data, metadata tools, settings, and help.",
                                right_click=_rc.get("file"))

    def show_playlist_menu(event=None):
        _open_toolbar_menu("playlist", state.widgets.playlist_menu_button, "playlist")

    if state.metadata.playlist.get("infinite", False):
        _pl_out_of = infinite.total_infinite_files - len(infinite.cached_skipped_themes)
        _pl_counter = f"\u221e/{_pl_out_of}"
    else:
        _pl_counter = f"{state.metadata.playlist['current_index']+1}/{len(state.metadata.playlist['playlist'])}"

    state.widgets.playlist_menu_button = create_button(state.widgets.first_row_frame, f"PLAYLIST {_pl_counter}\u25be", show_playlist_menu, True,
                                    help_text=("Options for creating and managing playlists. \n"
                                    "Right-Click Shortcut: Show Playlist"),
                                    right_click=_rc.get("playlist"))

    # Enable drag-and-drop on the playlist menu button
    def setup_playlist_drag_drop():
        try:
            drag_and_drop.enable_drag_and_drop(state.widgets.playlist_menu_button, drag_and_drop.handle_dropped_files)
        except Exception as e:
            print(f"Could not enable drag-and-drop on playlist button: {e}")
    state.widgets.root.after(100, setup_playlist_drag_drop)

    def show_queue_menu(event=None):
        _open_toolbar_menu("queue", state.widgets.queue_menu_button, "queue")

    state.widgets.queue_menu_button = create_button(state.widgets.first_row_frame, "QUEUE ROUND▾", show_queue_menu, True,
                                      help_text=("Queue special rounds, lightning rounds, and more.\n"
                                                 "Right-Click Shortcut: Toggle Variety Mode"),
                                      right_click=_rc.get("queue"))

    def show_bonus_menu(event=None):
        _open_toolbar_menu("bonus", state.widgets.bonus_menu_button, "bonus")

    state.widgets.bonus_menu_button = create_button(state.widgets.first_row_frame, "BONUS▾", show_bonus_menu, True,
                                      help_text=("Start bonus questions for the current theme.\n"
                                                 "Right-Click Shortcut: Multiple Choice"),
                                      right_click=_rc.get("bonus"))

    def show_popup_menu(event=None):
        _open_toolbar_menu("information", state.widgets.popup_menu_button, "information")

    state.widgets.popup_menu_button = create_button(state.widgets.first_row_frame, "INFORMATION▾", show_popup_menu, True,
                                      help_text=("Popup information and the end session screen.\n"
                                                 "Right-Click Shortcut: Show Information Popup"),
                                      right_click=_rc.get("information"))

    def show_theme_menu(event=None):
        _open_toolbar_menu("theme", state.widgets.theme_menu_button, "theme")

    state.widgets.theme_menu_button = create_button(state.widgets.first_row_frame, "THEME▾", show_theme_menu, True,
                                      help_text=("Options related to current theme including marking, fetching data, and more.\n"
                                                 "Right-Click Shortcut: Tag/untag theme"),
                                      right_click=_rc.get("theme"))

    def show_toggle_menu(event=None):
        _open_toolbar_menu("toggles", state.widgets.toggle_menu_button, "toggles")

    state.widgets.toggle_menu_button = create_button(state.widgets.first_row_frame, "TOGGLES▾", show_toggle_menu, True,
                                       help_text=("Various system toggles.\n"
                                                  "Right-Click Shortcut: Toggle Keyboard Shortcuts"),
                                       right_click=_rc.get("toggles"))

    if state.metadata.playlist.get("infinite", False):
        state.playlist_ui.selected_difficulty = tk.StringVar()
        state.playlist_ui.selected_difficulty.set(state.playlist_ui.difficulty_options[state.metadata.playlist["difficulty"]])
        # Destroy any previous instance — parented to root so it won't be caught
        # by the first_row_frame.winfo_children() destroy loop (avoiding TclError)
        try:
            if state.playlist_ui.difficulty_dropdown.winfo_exists():
                state.playlist_ui.difficulty_dropdown.destroy()
        except Exception:
            pass
        state.playlist_ui.difficulty_dropdown = ttk.Combobox(state.widgets.root,
                                values=state.playlist_ui.difficulty_options,
                                textvariable=state.playlist_ui.selected_difficulty,
                                width=17,
                                height=len(state.playlist_ui.difficulty_options),
                                state="readonly",
                                style="Black.TCombobox",
                                font=ROOT_FONT)
        # Not packed/displayed — difficulty is selected via PLAYLIST▾ menu
        state.playlist_ui.difficulty_dropdown.bind("<<ComboboxSelected>>", infinite.select_difficulty)

        if state.playback.popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
            state.playback.popout_buttons_by_name.get("DIFFICULTY DROPDOWN").grid()
        if state.playback.popout_buttons_by_name.get("SEARCH QUEUE"):
            state.playback.popout_buttons_by_name.get("SEARCH QUEUE").config(text="ADD NEXT")
    else:
        if state.playback.popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
            state.playback.popout_buttons_by_name.get("DIFFICULTY DROPDOWN").grid_remove()
        if state.playback.popout_buttons_by_name.get("SEARCH QUEUE"):
            state.playback.popout_buttons_by_name.get("SEARCH QUEUE").config(text="QUEUE NEXT")
    

    def show_directory_menu(event=None):
        _open_toolbar_menu("directory", state.widgets.directory_menu_button, "directory")
    state.widgets.directory_menu_button = create_button(state.widgets.first_row_frame, "DIRECTORY▾", show_directory_menu, True,
                                help_text=("Browse themes grouped by different parameters.\n\n"
                                           "Right-Click Shortcut: Toggle Censor Bars"),
                                right_click=_rc.get("directory"))

    search_ops.search_bar_entry = tk.Entry(
        state.widgets.first_row_frame,
        bg="black",
        fg="gray50",
        insertbackground="white",
        font=ROOT_FONT,
        relief="flat",
        highlightthickness=scl(1, "UI"),
        highlightcolor="gray40",
        highlightbackground="gray25",
    )
    search_ops.search_bar_entry.insert(0, search_ops.SEARCH_BAR_PLACEHOLDER)
    search_ops.search_bar_entry.pack(side="left", fill="x", expand=True, padx=(scl(4, "UI"), 0), pady=scl(0, "UI"))

    def on_search_focus_in(event=None):
        popout_window.popout_searching = True
        if search_ops.search_bar_entry.get() == search_ops.SEARCH_BAR_PLACEHOLDER:
            search_ops.search_bar_entry.delete(0, tk.END)
            search_ops.search_bar_entry.configure(fg="white")

    def on_search_focus_out(event=None):
        popout_window.popout_searching = False
        if not search_ops.search_bar_entry.get().strip():
            search_ops.search_bar_entry.delete(0, tk.END)
            search_ops.search_bar_entry.insert(0, search_ops.SEARCH_BAR_PLACEHOLDER)
            search_ops.search_bar_entry.configure(fg="gray50")

    _search_debounce = [None]

    def on_search_key_release(event=None):
        if event and event.keysym in ("Escape", "Return", "Tab"):
            return
        current_text = search_ops.search_bar_entry.get()
        if current_text == search_ops.SEARCH_BAR_PLACEHOLDER:
            return
        if search_ops.search_term == current_text:
            return
        search_ops.search_term = current_text
        if not current_text:
            if state.lists.list_loaded in ["search", "search_add"]:
                lists._close_list(state.widgets.right_column, keep_focus=True)
            return
        # Debounce: cancel any pending search and schedule a new one
        if _search_debounce[0]:
            state.widgets.root.after_cancel(_search_debounce[0])
        _search_debounce[0] = state.widgets.root.after(200, lambda: search_ops.search(update=True, ask=False, add=state.metadata.playlist.get("infinite", False)))

    def on_search_return(event=None):
        lists.list_select()

    def on_search_escape(event=None):
        search_ops.search_term = ""
        search_ops.search_bar_entry.delete(0, tk.END)
        search_ops.search_bar_entry.insert(0, search_ops.SEARCH_BAR_PLACEHOLDER)
        search_ops.search_bar_entry.configure(fg="gray50")
        state.widgets.root.focus()
        if state.lists.list_loaded in ["search", "search_add"]:
            lists._close_list(state.widgets.right_column)

    search_ops.search_bar_entry.bind("<FocusIn>", on_search_focus_in)
    search_ops.search_bar_entry.bind("<FocusOut>", on_search_focus_out)
    search_ops.search_bar_entry.bind("<KeyRelease>", on_search_key_release)
    search_ops.search_bar_entry.bind("<Return>", on_search_return)
    search_ops.search_bar_entry.bind("<Escape>", on_search_escape)
    tooltip.ToolTip(search_ops.search_bar_entry,
            "Search themes by title, filename, artist, and song name.\n\n"
            "Click themes to queue next, right-click to add to the playlist.")
