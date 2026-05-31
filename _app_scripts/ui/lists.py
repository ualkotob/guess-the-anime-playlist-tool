"""LISTS - list-display subsystem extracted from guess_the_anime.py.

Owns every list view rendered in the right column: the playlist, field-theme
lists, fixed-lightning-round lists, the remove view, search lists, and the
persistent-button display engine (scroll, pagination, selection, drag-reorder,
back-navigation stack, header title truncation).

Uses the `_main` module-reference pattern. ALL list STATE stays in main
(list_loaded, list_index, current_list_*, persistent_buttons, drag/highlight
state, the right_column_* header widgets, etc.) because it is read/written by
several sibling modules and by main's GUI setup; this module reaches every one
of them through `_main.X`. The 55 functions below are the only thing that moved.
"""

import os
import tkinter as tk
from tkinter import messagebox


_main = None


def set_context(*, main_module):
    global _main
    _main = main_module


def _theme_context_menu(filename, refresh_func, play_func=None, remove_func=None):
    """Show the standard theme right-click context menu for any theme list.

    play_func:   optional callable with no args used for "Play Now"; defaults to
                 play_video_from_filename(filename).
    remove_func: optional callable with no args; when provided, a "Remove from
                 Playlist" item is appended at the bottom.
    """
    filename = _main.get_clean_filename(filename)
    m = tk.Menu(_main.root, tearoff=0, bg="black", fg="white",
                activebackground=_main.HIGHLIGHT_COLOR, activeforeground="white", font=_main.MENU_FONT)

    # Play Now
    if play_func is None:
        play_func = lambda f=filename: _main.play_video_from_filename(f)
    m.add_command(label="     Play Now", command=play_func)

    m.add_separator()

    # Queue Next / Un-Queue Next
    is_queued = _main.search_ops.search_queue == filename
    queue_label = "✓  Queue Next" if is_queued else "     Queue Next"
    def _toggle_queue(f=filename):
        _main.search_ops.search_queue = None if _main.search_ops.search_queue == f else f
        if _main.search_ops.search_queue and not _main.player.is_playing():
            _main.play_video()
            return
        refresh_func()
        _main.up_next_text()
    m.add_command(label=queue_label, command=_toggle_queue)

    # Add Next
    def _add_next(f=filename):
        _main.playlist["playlist"].insert(_main.playlist["current_index"] + 1, f)
        _main.up_next_text()
        _main.save_config()
    m.add_command(label="     Add Next", command=_add_next)

    m.add_separator()

    # Mark submenu
    sub = tk.Menu(m, tearoff=0, bg="black", fg="white",
                  activebackground=_main.HIGHLIGHT_COLOR, activeforeground="white", font=_main.MENU_FONT)

    def _mark(playlist_name, exclusive=None, f=filename):
        # Remove mutually exclusive marks first
        if exclusive:
            for excl in exclusive:
                if _main.check_theme(f, excl):
                    _main.toggle_theme(excl, filename=f, quiet=True)
        _main.toggle_theme(playlist_name, filename=f, quiet=True)
        refresh_func()

    marks = [
        ("Tagged",    "Tagged Themes",    None),
        ("Favorite",  "Favorite Themes",  None),
        ("Blind",     "Blind Themes",       ["Reveal Themes", "Mute Reveal Themes"]),
        ("Reveal",    "Reveal Themes",      ["Blind Themes", "Mute Reveal Themes"]),
        ("Mute Reveal", "Mute Reveal Themes", ["Blind Themes", "Reveal Themes"]),
    ]
    for label, pname, exclusive in marks:
        is_marked = _main.check_theme(filename, pname, recache=True)
        entry_label = ("✓  " if is_marked else "     ") + label
        sub.add_command(label=entry_label, command=lambda p=pname, e=exclusive: _mark(p, e))

    m.add_cascade(label="     Mark ▸", menu=sub)

    m.add_separator()

    # Add to Playlist
    m.add_command(label="     Add to Playlist…", command=lambda f=filename: _main.add_to_saved_playlist(f))

    if remove_func is not None:
        m.add_separator()
        m.add_command(label="     Remove from Playlist", command=remove_func)

    try:
        _main.popup_menu(m, _main.root.winfo_pointerx(), _main.root.winfo_pointery())
    finally:
        pass


def show_field_themes(update = False, group=[], title=None):
    if group == []:
        field_list = _main.last_themes_listed
        if title is None:  # Preserve existing title when refreshing
            title = _main.current_list_title
    else:
        field_list = group
    if _main.last_themes_listed != group:
        update = True
    def _field_slug_sort_key(file):
        fname = _main.get_clean_filename(file)
        meta = _main.get_metadata(fname)
        slug = (meta.get("slug") or "").upper() if meta else ""
        title_key = (meta.get("eng_title") or meta.get("title") or fname).lower() if meta else fname.lower()
        if slug.startswith("OP"):
            slug_type = 0
            num_str = slug[2:]
        elif slug.startswith("ED"):
            slug_type = 1
            num_str = slug[2:]
        else:
            slug_type = 2
            num_str = slug
        slug_num = int(num_str) if num_str.isdigit() else 0
        return (title_key, slug_type, slug_num)
    field_list.sort(key=_field_slug_sort_key)
    _main.last_themes_listed = field_list
    selected = -1
    if _main.search_ops.search_queue:
        for index, filename in enumerate(field_list):
            if _main.get_clean_filename(filename) == _main.search_ops.search_queue or filename == _main.search_ops.search_queue:
                selected = index
                break
    show_list("field_list", _main.right_column, convert_playlist_to_dict(field_list), get_title, set_field_queue, selected, update, right_click_func=add_field_to_playlist, title=title)


def get_title(key, value):
    try:
        is_lightning = value.startswith("[L]")
        lightning_icon = "⚡" if is_lightning else ""
        
        filename = _main.get_clean_filename(value)
        
        if _main.is_youtube_file(filename):
            youtube_data = _main.get_youtube_metadata_by_filename(filename)
            if youtube_data:
                title = _main.get_youtube_display_title(youtube_data)
                display_name = f"{lightning_icon}[YT] {title}"
            else:
                display_name = lightning_icon + filename
        else:
            # Regular theme file handling
            data = _main.get_metadata(filename)
            if data:
                title = _main.get_display_title(data)
                display_name = title + " " + data.get("slug")
                version_num = data.get("version")
                if version_num and version_num not in ["null", "1"]:
                    display_name += f"v{version_num}"
                if os.path.isabs(value):
                    display_name = "📁 " + display_name
                display_name = lightning_icon + display_name
            else:
                display_name = filename
                if os.path.isabs(value):
                    display_name = "📁 " + display_name
                display_name = lightning_icon + display_name
        
        if filename not in _main.directory_files and "SEARCHING" not in filename:
            if _main.is_animethemes_stream_file(filename):
                display_name = _main.stream_icon + display_name
            else:
                display_name = "❌" + display_name
        return display_name
        
    except:
        filename = _main.get_clean_filename(value)
        is_lightning = value.startswith("[L]")
        lightning_icon = "⚡" if is_lightning else ""
        return lightning_icon + (("📁 " + filename) if os.path.isabs(value) else filename)


def set_field_queue(index):
    if _main.last_themes_listed and index >= 0:
        filename = _main.get_clean_filename(_main.last_themes_listed[index])
        if _main.search_ops.search_queue == filename:
            _main.search_ops.search_queue = None
        else:
            _main.search_ops.search_queue = filename
            if not _main.player.is_playing():
                _main.play_video()
                return
        show_field_themes(True)
        _main.up_next_text()


def add_field_to_playlist(index):
    if _main.last_themes_listed and index >= 0:
        filename = _main.get_clean_filename(_main.last_themes_listed[index])
        _theme_context_menu(filename, lambda: show_field_themes(True))


def show_playlist(update = False):
    # Check if fixed lightning round is active - display those rounds instead
    if _main.fixed_lightning_round_playlist_data and _main.fixed_lightning_round_playlist_data.get("rounds"):
        rounds = _main.fixed_lightning_round_playlist_data.get("rounds", [])
        rounds_dict = convert_fixed_rounds_to_dict(rounds)
        current_index = _main.fixed_lightning_round_playlist_data.get("current_index", 0)
        show_list("playlist", _main.right_column, rounds_dict, get_fixed_round_title, play_fixed_round_by_index, current_index, update, right_click_func=None, title=_main.fixed_lightning_round_playlist_data.get("name") or "FIXED LIGHTNING ROUNDS")
    else:
        def _playlist_right_click(index):
            if not (0 <= index < len(_main.playlist["playlist"])):
                return
            filename = _main.playlist["playlist"][index]
            clean = _main.get_clean_filename(filename)
            _theme_context_menu(
                clean,
                refresh_func=lambda: show_playlist(True),
                play_func=lambda i=index: _main.play_video(i),
                remove_func=lambda i=index: remove_theme(i),
            )

        show_list("playlist", _main.right_column, convert_playlist_to_dict(_main.playlist["playlist"]), get_title, _main.play_video, _main.playlist["current_index"], update, right_click_func=_playlist_right_click, title=_main.playlist.get("name") or "PLAYLIST")


def convert_fixed_rounds_to_dict(rounds):
    """Convert fixed lightning rounds to dict for display"""
    return {f"round_{i}": round_data for i, round_data in enumerate(rounds)}


def get_fixed_round_title(key, round_data):
    """Get display title for a fixed lightning round"""
    theme = round_data.get("theme", "Unknown")
    round_type = round_data.get("type", "regular")
    
    # Get anime title from metadata if possible
    try:
        data = _main.get_metadata(theme, fetch=False)
        title = _main.get_display_title(data)
    except:
        title = theme
    
    # Get icon from light_modes dictionary
    icon = _main.light_modes.get(round_type, {}).get("icon", "⚡")
    
    return f"{icon}{title}"


def play_fixed_round_by_index(index):
    """Play a fixed lightning round by index"""
    
    if not _main.fixed_lightning_round_playlist_data:
        return
    
    rounds = _main.fixed_lightning_round_playlist_data.get("rounds", [])
    if 0 <= index < len(rounds):
        # Calculate skip direction based on current vs target index
        current_index = _main.fixed_lightning_round_playlist_data.get("current_index", 0)
        _main.skip_direction = 1 if index > current_index else -1
        
        # Set to one before target so play_video advances to it
        _main.fixed_lightning_round_playlist_data["current_index"] = index - _main.skip_direction
        
        # Play the video which will advance to the target index
        _main.play_video()


def remove(update = False):
    show_list("remove", _main.right_column, convert_playlist_to_dict(_main.playlist["playlist"]), get_title, remove_theme, _main.playlist["current_index"], update, title="REMOVE THEME")


def convert_playlist_to_dict(playlis):
    return {f"{video}_{i}": video for i, video in enumerate(playlis)}


def update_playlist_display():
    """Helper function to update the playlist display when the playlist changes"""
    if _main.list_loaded == "playlist":
        
        # Check if fixed lightning round is active
        if _main.fixed_lightning_round_playlist_data and _main.fixed_lightning_round_playlist_data.get("rounds"):
            rounds = _main.fixed_lightning_round_playlist_data.get("rounds", [])
            _main.current_list_content = convert_fixed_rounds_to_dict(rounds)
            _main.current_list_selected = _main.fixed_lightning_round_playlist_data.get("current_index", 0)
            _main.current_list_name_func = get_fixed_round_title
        else:
            _main.current_list_content = convert_playlist_to_dict(_main.playlist["playlist"])
            _main.current_list_selected = _main.playlist["current_index"]
            _main.current_list_name_func = get_title
        
        refresh_current_list()


def remove_theme(index):
    playlist_entry = _main.playlist["playlist"][index]
    display_name = os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry
    confirm = messagebox.askyesno("Remove Theme", f"Are you sure you want to remove '{display_name}' from '{_main.playlist["name"]}'?")
    if not confirm:
        return  # User canceled
    del _main.playlist["playlist"][index]
    
    # Update current_list_content to reflect the removal
    if _main.list_loaded == "playlist":
        _main.current_list_content = convert_playlist_to_dict(_main.playlist["playlist"])
        if _main.current_list_selected > index:
            _main.current_list_selected -= 1
        elif _main.current_list_selected == index and _main.current_list_selected >= len(_main.playlist["playlist"]):
            _main.current_list_selected = len(_main.playlist["playlist"]) - 1 if _main.playlist["playlist"] else -1
        refresh_current_list()
    elif _main.list_loaded == "remove":
        _main.current_list_content = convert_playlist_to_dict(_main.playlist["playlist"])
        # If we're in the remove view, we need to refresh that too
        remove_theme(True)


def button_seleted(button, selected):
    if hasattr(button, 'configure') and button.winfo_exists():
        if selected:
            button.configure(bg=_main.HIGHLIGHT_COLOR, fg="white")
        else:
            button.configure(bg="black", fg="white")


def get_list_entries_count():
    """Get the number of entries to show in lists based on available height."""
    try:
        # Get the actual height of the right_column widget
        _main.right_column.update_idletasks()  # Ensure geometry is updated
        available_height = _main.right_column.winfo_height()
        
        # If height is not yet available (window not fully initialized), use default logic
        if available_height <= 1:
            content = _main.right_top.get(1.0, tk.END)
            content_stripped = content.strip()
            base = 13 if (not content_stripped or content_stripped == "" or len(content_stripped) == 0) else 12
            return base
        
        # Estimate button height including padding/spacing
        # Each button is roughly 25-30 pixels with spacing, using 28 as safe estimate
        button_height_estimate = _main.scl(26, "UI")  # Adjusted for UI scaling
        
        # Calculate how many buttons can fit, with minimum of 8 and maximum of 20
        calculated_count = available_height // button_height_estimate
        
        return calculated_count
        
    except Exception:
        return 12  # Default fallback


def push_list_nav(restore_fn):
    """Push restore_fn onto the back-navigation stack and show the ← button.
    Captures current_list_offset so scrolling position is restored on back."""
    saved_offset = _main.current_list_offset
    def _restore():
        restore_fn()
        _main.current_list_offset = saved_offset
        refresh_current_list()
        update_list_scrollbar()
    _main._list_nav_stack.append(_restore)
    _update_back_button()


def clear_list_nav():
    """Clear the back-navigation stack and hide the ← button."""
    _main._list_nav_stack.clear()
    _update_back_button()


def _update_back_button():
    btn = getattr(_main, 'right_column_back_button', None)
    if btn is None or not btn.winfo_exists():
        return
    # Toggle visibility via fg colour — never pack/unpack so layout stays stable.
    btn.config(fg='white' if _main._list_nav_stack else _main.BACKGROUND_COLOR)


def _go_back_list():
    """Pop and invoke the top of the navigation stack."""
    if _main._list_nav_stack:
        restore_fn = _main._list_nav_stack.pop()
        _update_back_button()
        restore_fn()


def _close_list(column, keep_focus=False):
    """Close the current list view and clear the column."""
    _main._list_nav_stack.clear()
    _update_back_button()
    _was_search = _main.list_loaded in ["search", "search_add"]
    _main.current_list_title = ""
    _insert_list_title_row(column)  # hides the header frame
    list_unload(column)
    try:
        column.config(state=tk.NORMAL)
        column.delete(1.0, tk.END)
        column.config(state=tk.DISABLED)
    except Exception:
        pass
    update_list_scrollbar()
    # Clear the toolbar search entry if a search list was closed
    if _was_search and not keep_focus:
        try:
            _main.search_ops.search_term = ""
            if _main.search_bar_entry and _main.search_bar_entry.winfo_exists():
                _main.search_bar_entry.delete(0, tk.END)
                _main.search_bar_entry.insert(0, _main.SEARCH_BAR_PLACEHOLDER)
                _main.search_bar_entry.configure(fg="gray50")
                _main.root.focus()
        except Exception:
            pass
    # Restore extra metadata if a theme is currently loaded
    if _main.currently_playing.get("data") or _main.currently_playing.get("type") == "youtube":
        _main.update_extra_metadata(column)


def _insert_list_title_row(column):
    """Show, update, or hide the title header frame above right_column."""
    if _main.right_column_header is None:
        return
    if _main.current_list_title:
        # Truncate using right_column's width (always rendered) BEFORE packing,
        # so the label never has the full long text and can't push the frame wider.
        _do_truncate_header_title()
        if not _main.right_column_header.winfo_ismapped():
            _main.right_column_header.pack(fill="x", before=_main.right_column_row)
        _main.list_title_label = _main.right_column_header_label
    else:
        if _main.right_column_header.winfo_ismapped():
            _main.right_column_header.pack_forget()
        _main.list_title_label = None


def _truncate_header_title(event=None):
    """Schedule header-title truncation, debounced to avoid Configure feedback loops."""
    if _main._truncate_after_id[0] is not None:
        try:
            _main.right_column_header.after_cancel(_main._truncate_after_id[0])
        except Exception:
            pass
    _main._truncate_after_id[0] = _main.right_column_header.after(25, _do_truncate_header_title)


def _do_truncate_header_title():
    """Actually compute and apply ellipsis truncation to the header label."""
    _main._truncate_after_id[0] = None
    if not _main.current_list_title or _main.right_column_header_label is None:
        return
    font_obj = _main.list_header_font
    if font_obj is None:
        return
    # Use right_column's width as reference — it's always rendered with the correct width.
    # right_column_header.winfo_width() returns 1 until the frame is laid out, so
    # we can't rely on it here (especially before the header is packed the first time).
    ref_width = _main.right_column.winfo_width() if _main.right_column and _main.right_column.winfo_exists() else 0
    if ref_width < 20:
        _set_header_label(_main.current_list_title)
        return
    close_btn_est = _main.scl(80, "UI")
    back_btn_est = _main.scl(32, "UI")  # back button always occupies space
    available_w = max(20, ref_width - close_btn_est - back_btn_est)
    text = _main.current_list_title
    if font_obj.measure(text) <= available_w:
        _set_header_label(text)
        return
    for i in range(len(text) - 1, 0, -1):
        truncated = text[:i] + "\u2026"
        if font_obj.measure(truncated) <= available_w:
            _set_header_label(truncated)
            return
    _set_header_label("\u2026")


def _set_header_label(text):
    """Set header label text only if it differs, preventing spurious Configure events."""
    if _main.right_column_header_label and _main.right_column_header_label.cget("text") != text:
        _main.right_column_header_label.config(text=text)


def update_list_scrollbar():
    """Sync the custom scrollbar thumb to reflect the current list offset, showing/hiding as needed."""
    if _main.right_column_scrollbar is None:
        return
    needs_scroll = False
    if _main.list_loaded and _main.current_list_content:
        list_size = len(_main.current_list_content)
        entries_count = get_list_entries_count()
        if list_size > entries_count:
            needs_scroll = True
            first = _main.current_list_offset / list_size
            last = min(1.0, (_main.current_list_offset + entries_count) / list_size)
            _main.right_column_scrollbar.set(first, last)
    if needs_scroll:
        if not _main.right_column_scrollbar.winfo_ismapped():
            _main.right_column_scrollbar.pack(side="right", fill="y")
    else:
        if _main.right_column_scrollbar.winfo_ismapped():
            _main.right_column_scrollbar.pack_forget()


def on_list_scrollbar_set(action, *args):
    """Handle scrollbar drag/click to change the list offset."""
    if not _main.list_loaded or not _main.current_list_content:
        return
    list_size = len(_main.current_list_content)
    entries_count = get_list_entries_count()
    max_offset = max(0, list_size - entries_count)
    if action == "moveto":
        fraction = float(args[0])
        _main.current_list_offset = max(0, min(max_offset, round(fraction * list_size)))
    elif action == "scroll":
        amount = int(args[0])
        unit = args[1]
        if unit == "pages":
            _main.current_list_offset = max(0, min(max_offset, _main.current_list_offset + amount * entries_count))
        else:
            _main.current_list_offset = max(0, min(max_offset, _main.current_list_offset + amount))
    refresh_current_list()


def create_persistent_list_buttons(column, target_count=None):
    """Create persistent buttons that will be reused for any list display."""
    
    if target_count is None:
        target_count = get_list_entries_count()
    
    # Clear any existing buttons
    for btn in _main.persistent_buttons:
        try:
            btn.destroy()
        except:
            pass
    
    _main.persistent_buttons = []
    _main.button_to_index_map = {}
    
    # Create buttons based on target count
    entries_count = target_count
    for i in range(entries_count):
        btn = tk.Button(column, text="", borderwidth=0, pady=0,
                       bg="black", fg="white", font=("Consolas", _main.scl(11, "UI")),
                       command=lambda idx=i: handle_persistent_button_click(idx))
        
        # Add all the event bindings
        btn.bind("<Button-3>", lambda e, idx=i: handle_persistent_right_click(e, idx))
        btn.bind("<MouseWheel>", lambda e: _main.handle_list_scroll(e))
        btn.bind("<Button-4>", lambda e: _main.handle_btn_scroll_up(e))
        btn.bind("<Button-5>", lambda e: _main.handle_btn_scroll_down(e))
        btn.bind("<Enter>", lambda e, idx=i: handle_persistent_button_enter(e, idx))
        btn.bind("<Leave>", lambda e, idx=i: handle_persistent_button_leave(e, idx))
        
        if _main.list_loaded == "playlist":
            btn.bind("<Button-1>", lambda e, idx=i: handle_persistent_drag_start(e, idx))
            btn.bind("<B1-Motion>", lambda e: handle_drag_motion(e))
            btn.bind("<ButtonRelease-1>", lambda e: end_playlist_drag(e))
        
        _main.persistent_buttons.append(btn)
    
    return _main.persistent_buttons


def list_scroll_up():
    if _main.list_loaded:
        _main.current_list_offset = max(0, _main.current_list_offset - 1)
        refresh_current_list()


def list_scroll_down():
    if _main.list_loaded:
        list_size = len(_main.current_list_content)
        entries_count = get_list_entries_count()
        max_offset = max(0, list_size - entries_count)
        _main.current_list_offset = min(max_offset, _main.current_list_offset + 1)
        refresh_current_list()


def refresh_current_list():
    """Refresh the current list display without changing the list type."""
    if _main.list_loaded == "playlist":
        # Update the current list content from the actual playlist data
        
        # Check if fixed lightning round is active
        if _main.fixed_lightning_round_playlist_data and _main.fixed_lightning_round_playlist_data.get("rounds"):
            rounds = _main.fixed_lightning_round_playlist_data.get("rounds", [])
            _main.current_list_content = convert_fixed_rounds_to_dict(rounds)
            _main.current_list_name_func = get_fixed_round_title
        else:
            _main.current_list_content = convert_playlist_to_dict(_main.playlist["playlist"])
            _main.current_list_name_func = get_title
        
        entries_count = get_list_entries_count()
        current_count = len(_main.persistent_buttons) if _main.persistent_buttons else 0
        
        if current_count != entries_count:
            # Directly recreate buttons and layout
            if _main.persistent_buttons:
                try:
                    column = _main.persistent_buttons[0].master
                    create_persistent_list_buttons(column, entries_count)
                    
                    # Recreate layout
                    column.config(state=tk.NORMAL, wrap="none")
                    column.delete(1.0, tk.END)
                    for button_index in range(entries_count):
                        try:
                            column.window_create(tk.END, window=_main.persistent_buttons[button_index])
                            column.insert(tk.END, "\n")
                        except tk.TclError:
                            pass
                    column.config(state=tk.DISABLED)
                except (IndexError, AttributeError, tk.TclError):
                    return
        
        # For playlist, just update the persistent buttons directly instead of calling show_playlist
        if _main.persistent_buttons and _main.current_list_content:
            start_index = _main.current_list_offset
            end_index = min(len(_main.current_list_content), start_index + entries_count)
            
            for button_index in range(entries_count):
                item_index = start_index + button_index
                if item_index < end_index:
                    update_persistent_button(button_index, item_index, _main.current_list_name_func, _main.current_list_content, _main.current_list_selected)
                else:
                    update_persistent_button(button_index, -1, _main.current_list_name_func, _main.current_list_content, _main.current_list_selected)
        else:
            show_playlist(update=True)
    elif _main.list_loaded and _main.current_list_content:
        # For other lists, update the display directly
        update_persistent_list_display()
    update_list_scrollbar()


def update_persistent_list_display():
    """Update the persistent buttons with current list content."""
    
    if not _main.current_list_content or not _main.current_list_name_func:
        return
    
    list_size = len(_main.current_list_content)
    start_index = _main.current_list_offset
    entries_count = get_list_entries_count()
    end_index = min(list_size, start_index + entries_count)
    
    # Update each persistent button
    for button_index in range(entries_count):
        _li = start_index + button_index
        if _li < end_index:
            update_persistent_button(button_index, _li, _main.current_list_name_func, _main.current_list_content, _main.current_list_selected)
        else:
            try:
                _main.persistent_buttons[button_index].config(text="", state="disabled")
            except (tk.TclError, IndexError):
                pass


def get_display_width(text):
    """Calculate display width treating Unicode icons as 2 characters each."""
    width = 0
    for char in text:
        if char in ['⚡', '📁', _main.stream_icon, '❌']:
            width += 2
        else:
            width += 1
    return width


def truncate_by_display_width(text, max_width):
    """Truncate text based on display width, treating Unicode icons as 2 characters."""
    if get_display_width(text) <= max_width:
        return text
    
    # Find the truncation point
    current_width = 0
    for i, char in enumerate(text):
        char_width = 2 if char in ['⚡', '📁', _main.stream_icon, '❌'] else 1
        if current_width + char_width > max_width:
            return text[:i]
        current_width += char_width
    
    return text


def update_persistent_button(button_index, item_index, name_func, content_dict, selected):
    """Update a single persistent button with new content."""
    
    if button_index >= len(_main.persistent_buttons):
        return
    
    btn = _main.persistent_buttons[button_index]
    
    try:
        if not btn.winfo_exists():
            return
    except tk.TclError:
        return
    
    _main.button_to_index_map[btn] = item_index
    
    items_list = list(content_dict.items())
    if item_index < len(items_list) and item_index >= 0:
        key, value = items_list[item_index]
        index_prefix = str(item_index + 1) + ": " if _main.current_list_show_numbers else ""
        title_part = name_func(key, value)

        max_total_width = 47
        available_width = max_total_width - get_display_width(index_prefix)
        
        if get_display_width(title_part) > available_width:
            keep_width = available_width - 1  # Account for "…" (1 character width)
            if keep_width > 0:
                half_width = keep_width // 2
                # Find truncation points that respect character boundaries
                left_part = truncate_by_display_width(title_part, half_width)
                
                # For right part, work backwards from the end
                right_width = keep_width - get_display_width(left_part)
                right_part = ""
                if right_width > 0:
                    temp_width = 0
                    for i in range(len(title_part) - 1, -1, -1):
                        char = title_part[i]
                        char_width = 2 if char in ['⚡', '📁'] else 1
                        if temp_width + char_width > right_width:
                            break
                        temp_width += char_width
                        right_part = char + right_part
                
                title_part = left_part + "…" + right_part
            else:
                title_part = truncate_by_display_width(title_part, available_width)
        
        name = index_prefix + title_part
        
        # Update button appearance
        if item_index == selected:
            font = ("Consolas", _main.scl(11, "UI"), "bold")
            bg = _main.HIGHLIGHT_COLOR
        elif not _main.disable_shortcuts and item_index == _main.list_index:
            font = ("Consolas", _main.scl(11, "UI"))
            bg = _main.HIGHLIGHT_COLOR
        else:
            font = ("Consolas", _main.scl(11, "UI"))
            bg = "black"
        
        try:
            btn.config(text=name, font=font, bg=bg, fg="white", state="normal")
        except tk.TclError:
            return
    else:
        try:
            btn.config(text="", state="disabled")
        except tk.TclError:
            return


def handle_persistent_button_click(button_index):
    """Handle click on a persistent button."""
    try:
        if button_index < len(_main.persistent_buttons):
            btn = _main.persistent_buttons[button_index]
            if btn in _main.button_to_index_map and btn.winfo_exists():
                actual_index = _main.button_to_index_map[btn]
                if _main.list_func:
                    _main.list_func(actual_index)
    except (tk.TclError, IndexError):
        pass


def handle_persistent_right_click(event, button_index):
    """Handle right click on a persistent button."""
    try:
        if button_index < len(_main.persistent_buttons):
            btn = _main.persistent_buttons[button_index]
            if btn in _main.button_to_index_map and btn.winfo_exists():
                actual_index = _main.button_to_index_map[btn]
                if hasattr(handle_persistent_right_click, 'right_click_func') and handle_persistent_right_click.right_click_func:
                    handle_persistent_right_click.right_click_func(actual_index)
    except (tk.TclError, IndexError):
        pass


def handle_persistent_button_enter(event, button_index):
    """Handle mouse enter on persistent button."""
    if button_index < len(_main.persistent_buttons):
        btn = _main.persistent_buttons[button_index]
        if btn in _main.button_to_index_map:
            actual_index = _main.button_to_index_map[btn]
            on_button_enter(event, actual_index)


def handle_persistent_button_leave(event, button_index):
    """Handle mouse leave on persistent button."""
    if button_index < len(_main.persistent_buttons):
        btn = _main.persistent_buttons[button_index]
        if btn in _main.button_to_index_map:
            actual_index = _main.button_to_index_map[btn]
            on_button_leave(event, actual_index)


def handle_persistent_drag_start(event, button_index):
    """Handle drag start on persistent button."""
    if button_index < len(_main.persistent_buttons):
        btn = _main.persistent_buttons[button_index]
        if btn in _main.button_to_index_map:
            actual_index = _main.button_to_index_map[btn]
            start_playlist_drag(event, actual_index)


def list_set_loaded(type):
    _main.list_loaded = type


def list_unload(column):
    # Clean up persistent buttons when switching away from playlist
    if _main.list_loaded == "playlist" and _main.persistent_buttons:
        for btn in _main.persistent_buttons:
            try:
                btn.destroy()
            except:
                pass
        _main.persistent_buttons = []
    
    list_set_loaded(None)
    update_list_scrollbar()
    _main.update_extra_metadata()


def list_move(amount):
    if _main.list_loaded and _main.current_list_content:
        # Move selection with wrapping
        old_index = _main.list_index
        list_size = len(_main.current_list_content)
        
        if amount > 0:  # Moving down
            _main.list_index = (_main.list_index + 1) % list_size
        else:  # Moving up
            _main.list_index = (_main.list_index - 1) % list_size
        
        entries_count = get_list_entries_count()
        if _main.list_index < _main.current_list_offset:
            _main.current_list_offset = _main.list_index
            refresh_current_list()
        elif _main.list_index >= _main.current_list_offset + entries_count:
            _main.current_list_offset = _main.list_index - entries_count + 1
            refresh_current_list()
        elif old_index != _main.list_index:
            refresh_current_list()
    else:
        _main.left_column.yview_scroll(amount, "units")
        _main.middle_column.yview_scroll(amount, "units")
        _main.right_column.yview_scroll(amount, "units")


def list_select():
    if _main.list_loaded:
        _main._list_action_from_keyboard = True
        try:
            _main.list_func(_main.list_index)
        finally:
            _main._list_action_from_keyboard = False


def show_list(type, column, content, name_func, btn_func, selected, update = True, right_click_func=None, items_per_page=None, title=None, show_numbers=True):
    
    # Always resolve the new title upfront so we can detect changes
    new_title = title or ""

    list_size = len(content)
    buttons_need_recreation = False
    
    if _main.list_loaded == type and not update:
        list_unload(column)
        return
    elif _main.list_loaded != type:
        list_set_loaded(type)
        if selected < 0:
            _main.list_index = 0
        else:
            _main.list_index = selected
        _main.list_func = btn_func
        _main.current_list_offset = 0
        buttons_need_recreation = True
        
        # For playlist, center on current playing item
        if type == "playlist":
            entries_count = get_list_entries_count()
            # Use fixed round index if active, otherwise regular playlist index
            if _main.fixed_lightning_round_playlist_data and _main.fixed_lightning_round_playlist_data.get("rounds"):
                current_playing = _main.fixed_lightning_round_playlist_data.get("current_index", -1)
            else:
                current_playing = _main.playlist.get("current_index", -1)
            if current_playing >= 0:
                _main.current_list_offset = max(0, current_playing - entries_count // 2)
                max_offset = max(0, list_size - entries_count)
                _main.current_list_offset = min(_main.current_list_offset, max_offset)
    elif _main.list_index >= list_size:
        _main.list_index = 0
    elif _main.list_index < 0:
        _main.list_index = list_size - 1
    
    # Store current list data
    _main.current_list_content = content
    _main.current_list_name_func = name_func
    
    _main.current_list_selected = selected
    _main.current_list_show_numbers = show_numbers
    
    if type == "playlist":
        _main.playlist_page_offset = _main.current_list_offset

    _main.list_func = btn_func
    handle_persistent_right_click.right_click_func = right_click_func

    # Apply title and update header visibility
    _main.current_list_title = new_title
    _insert_list_title_row(column)

    # Only clear and recreate layout when switching list types
    if buttons_need_recreation:
        column.config(state=tk.NORMAL, wrap="none", spacing1=0, spacing3=0)
        column.delete(1.0, tk.END)
        
        entries_count = get_list_entries_count()
        if not _main.persistent_buttons or len(_main.persistent_buttons) != entries_count:
            create_persistent_list_buttons(column, entries_count)
        else:
            pass  # Button count matches, no recreation needed
        
        # Add buttons to layout
        for button_index in range(entries_count):
            try:
                column.window_create(tk.END, window=_main.persistent_buttons[button_index])
                column.insert(tk.END, "\n")
            except tk.TclError:
                # Button was destroyed, recreate persistent buttons
                create_persistent_list_buttons(column, entries_count)
                column.window_create(tk.END, window=_main.persistent_buttons[button_index])
                column.insert(tk.END, "\n")
        
        column.config(state=tk.DISABLED, spacing1=0, spacing3=0)
    
    # Calculate display boundaries
    entries_count = get_list_entries_count()
    start_index = _main.current_list_offset
    end_index = min(list_size, start_index + entries_count)
    
    if start_index >= list_size:
        _main.current_list_offset = max(0, list_size - entries_count)
        start_index = _main.current_list_offset
        end_index = min(list_size, start_index + entries_count)
    
    # Update each persistent button with current content (no layout changes needed)
    for button_index in range(entries_count):
        item_index = start_index + button_index
        if item_index < end_index:
            update_persistent_button(button_index, item_index, name_func, content, selected)
        else:
            update_persistent_button(button_index, -1, name_func, content, selected)
    
    if buttons_need_recreation:
        # Don't steal focus from the search bar entry
        is_search = type in ("search", "search_add")
        if not (is_search and _main.search_bar_entry and _main.search_bar_entry.winfo_exists()):
            column.focus_set()
    update_list_scrollbar()


def start_playlist_drag(event, index):
    """Start dragging a playlist item."""
    
    # Don't allow dragging for fixed lightning rounds
    if _main.fixed_lightning_round_playlist_data and _main.fixed_lightning_round_playlist_data.get("rounds"):
        return
    
    # Clear any existing highlighting
    clear_drop_highlight()
    
    _main.drag_start_index = index
    _main.drag_current_y = event.y_root
    
    # Highlight the source item being dragged
    highlight_drag_source(index)


def handle_drag_motion(event):
    """Handle dragging motion - can be called from any button."""
    if _main.drag_start_index is None:
        return
    
    _main.drag_current_y = event.y_root
    
    # Update cursor to show dragging is active
    try:
        event.widget.configure(cursor="hand2")
    except (tk.TclError, AttributeError):
        pass
    
    # Calculate and highlight drop target position
    try:
        # Get the widget under the mouse cursor
        widget_under_mouse = _main.root.winfo_containing(event.x_root, event.y_root)
        
        # Clear only target highlights (preserve source highlight)
        clear_target_highlights()
        
        # If we're over a button, highlight it
        if widget_under_mouse and hasattr(widget_under_mouse, 'cget'):
            try:
                button_text = widget_under_mouse.cget('text')
                # Extract index from button text (format: "1: Title Name")
                if ':' in button_text:
                    index_str = button_text.split(':')[0].strip()
                    if index_str.isdigit():
                        target_index = int(index_str) - 1  # Convert to 0-based
                        
                        if target_index != _main.drag_start_index and 0 <= target_index < len(_main.playlist["playlist"]):
                            # Store original colors and highlight
                            _main.highlighted_buttons[target_index] = {
                                'widget': widget_under_mouse,
                                'original_bg': widget_under_mouse.cget('bg'),
                                'original_fg': widget_under_mouse.cget('fg'),
                                'is_target': True
                            }
                            widget_under_mouse.configure(bg=_main.HIGHLIGHT_COLOR, fg="white")
            except (tk.TclError, AttributeError, ValueError):
                pass
            
    except (ValueError, tk.TclError, AttributeError):
        pass


def highlight_drag_source(source_index):
    """Highlight the source item being dragged to look like it's pressed."""
    
    if _main.list_loaded != "playlist":
        return
        
    try:
        highlight_button_at_index(source_index, "white", "black", is_source=True)
        
    except (tk.TclError, AttributeError, ValueError):
        pass


def highlight_button_at_index(target_index, bg_color, fg_color, is_source=False):
    """Highlight the button widget at the specified playlist index."""
    
    try:
        # Find all button widgets in the right_column
        for widget_name in _main.right_column.children:
            widget = _main.right_column.nametowidget(widget_name)
            if hasattr(widget, 'configure') and hasattr(widget, 'cget'):
                try:
                    button_text = widget.cget('text')
                    if button_text.startswith(f"{target_index + 1}:"):
                        # Store original colors
                        if target_index not in _main.highlighted_buttons:
                            _main.highlighted_buttons[target_index] = {
                                'widget': widget,
                                'original_bg': widget.cget('bg'),
                                'original_fg': widget.cget('fg'),
                                'is_source': is_source,
                                'is_target': not is_source
                            }
                        # Apply highlight
                        widget.configure(bg=bg_color, fg=fg_color)
                        break
                except (tk.TclError, AttributeError):
                    continue
    except (tk.TclError, AttributeError):
        pass


def clear_button_highlights():
    """Clear all button highlighting and restore original colors."""
    
    try:
        for index, button_data in _main.highlighted_buttons.items():
            widget = button_data['widget']
            if widget and hasattr(widget, 'configure'):
                try:
                    # Restore original colors
                    widget.configure(
                        bg=button_data['original_bg'],
                        fg=button_data['original_fg']
                    )
                except (tk.TclError, AttributeError):
                    pass
        _main.highlighted_buttons.clear()
    except (tk.TclError, AttributeError):
        pass


def clear_target_highlights():
    """Clear only target button highlights, preserve source highlight."""
    
    try:
        # Find and clear only target highlights
        targets_to_remove = []
        for index, button_data in _main.highlighted_buttons.items():
            if button_data.get('is_target', False):
                widget = button_data['widget']
                if widget and hasattr(widget, 'configure'):
                    try:
                        # Restore original colors
                        widget.configure(
                            bg=button_data['original_bg'],
                            fg=button_data['original_fg']
                        )
                        targets_to_remove.append(index)
                    except (tk.TclError, AttributeError):
                        pass
        
        # Remove cleared targets from the dictionary
        for index in targets_to_remove:
            del _main.highlighted_buttons[index]
            
    except (tk.TclError, AttributeError):
        pass


def clear_drop_highlight():
    """Clear any drop target and source highlighting."""
    try:
        # Clear button highlights
        clear_button_highlights()
        
        # Clear any remaining text highlights
        if _main.current_highlight_tag:
            _main.right_column.tag_delete(_main.current_highlight_tag)
            _main.current_highlight_tag = None
        if _main.current_source_tag:
            _main.right_column.tag_delete(_main.current_source_tag)
            _main.current_source_tag = None
    except (tk.TclError, AttributeError):
        pass


def on_button_enter(event, index):
    """Handle mouse entering a button during drag operation."""
    
    _main.hovered_button_index = index
    
    # Always highlight on hover, unless it's a special button we shouldn't change
    try:
        current_bg = event.widget.cget('bg')
        current_fg = event.widget.cget('fg')
        
        is_current_index = (index == _main.playlist.get("current_index", -1))
        is_drag_source = (_main.drag_start_index is not None and index == _main.drag_start_index)
        
        if not (is_current_index or is_drag_source):
            if index not in _main.highlighted_buttons:
                _main.highlighted_buttons[index] = {
                    'widget': event.widget,
                    'original_bg': current_bg,
                    'original_fg': current_fg
                }
            
            # Apply hover highlight
            event.widget.configure(bg="gray26", fg="white")
        
    except (tk.TclError, AttributeError):
        pass


def on_button_leave(event, index):
    """Handle mouse leaving a button during drag operation."""
    
    # Clear hover tracking when leaving button
    if _main.hovered_button_index == index:
        _main.hovered_button_index = None
    
    # Restore original colors when leaving (unless it's current index or drag source)
    is_current_index = (index == _main.playlist.get("current_index", -1))
    is_drag_source = (_main.drag_start_index is not None and index == _main.drag_start_index)
    
    if not (is_current_index or is_drag_source) and index in _main.highlighted_buttons:
        try:
            button_data = _main.highlighted_buttons[index]
            event.widget.configure(
                bg=button_data['original_bg'],
                fg=button_data['original_fg']
            )
            del _main.highlighted_buttons[index]
        except (tk.TclError, AttributeError, KeyError):
            pass


def end_playlist_drag(event):
    """End dragging and reorder playlist if needed."""
    
    if _main.drag_start_index is None:
        return
    
    # Calculate drop position based on mouse position - use same method as visual highlighting
    try:
        # Get the widget under the mouse cursor (same as visual highlighting)
        widget_under_mouse = _main.root.winfo_containing(event.x_root, event.y_root)
        drop_index = None
        
        # If we're over a button, get its index
        if widget_under_mouse and hasattr(widget_under_mouse, 'cget'):
            try:
                button_text = widget_under_mouse.cget('text')
                # Extract index from button text (format: "1: Title Name")
                if ':' in button_text:
                    index_str = button_text.split(':')[0].strip()
                    if index_str.isdigit():
                        display_index = int(index_str) - 1  # Convert to 0-based
                        if _main.list_loaded == "playlist":
                            drop_index = display_index  # display_index already includes pagination offset
                        else:
                            drop_index = display_index
            except (tk.TclError, AttributeError, ValueError):
                pass
        
        # If no button found, try fallback text position method
        if drop_index is None:
            try:
                text_widget = _main.right_column
                x_rel = event.x_root - text_widget.winfo_rootx()
                y_rel = event.y_root - text_widget.winfo_rooty()
                
                if (0 <= x_rel <= text_widget.winfo_width() and 
                    0 <= y_rel <= text_widget.winfo_height()):
                    
                    text_index = text_widget.index(f"@{x_rel},{y_rel}")
                    drop_line = int(text_index.split('.')[0]) - 1  # Convert to 0-based line index
                    
                    if _main.list_loaded == "playlist":
                        # Each line corresponds to a playlist item, add the pagination offset
                        drop_index = max(0, min(drop_line + _main.playlist_page_offset, len(_main.playlist["playlist"]) - 1))
                    else:
                        if "items above" in text_widget.get("1.0", "2.0"):
                            drop_line = max(0, drop_line - 1)
                        
                        drop_index = max(0, min(drop_line, len(_main.playlist["playlist"]) - 1))
            except (ValueError, tk.TclError):
                pass
        
        if (drop_index is not None and 
            drop_index != _main.drag_start_index and 
            0 <= drop_index < len(_main.playlist["playlist"])):
            
            # Reorder the playlist
            item = _main.playlist["playlist"].pop(_main.drag_start_index)
            _main.playlist["playlist"].insert(drop_index, item)
            
            if _main.playlist["current_index"] == _main.drag_start_index:
                _main.playlist["current_index"] = drop_index
            elif _main.drag_start_index < _main.playlist["current_index"] <= drop_index:
                _main.playlist["current_index"] -= 1
            elif drop_index <= _main.playlist["current_index"] < _main.drag_start_index:
                _main.playlist["current_index"] += 1
            
            # Refresh the playlist display
            show_playlist(True)
    
    except Exception as e:
        print(f"Drag and drop error: {e}")
    
    # Clear drop target highlighting
    clear_drop_highlight()
    
    # Reset drag state
    _main.drag_start_index = None
    _main.drag_current_y = None
    
    # Reset cursor
    try:
        event.widget.configure(cursor="")
        _main.right_column.configure(cursor="")
    except (tk.TclError, AttributeError):
        pass


def add_single_line(column, line, title, newline=True):
    column.insert(tk.END, title + ": ", "bold")
    column.insert(tk.END, line, "white")
    if newline:
        column.insert(tk.END, "\n", "white")
    else:
        column.insert(tk.END, "   ", "white")
