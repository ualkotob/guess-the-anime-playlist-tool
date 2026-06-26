"""Drag-and-drop support — external file-drop handling.

Owns the two functions that let users drag media files from Windows Explorer
onto the app (or pick them via dialog fallback) and insert them into the
playlist at the drop position:

- `enable_drag_and_drop(widget, callback)` - wires a widget for file drops using
  tkinterdnd2, falling back to a raw Win32 WM_DROPFILES window-proc hook, then to
  a right-click / double-click file dialog.
- `handle_dropped_files(files, event=None)` - the drop callback; computes the
  insert position from the cursor over the playlist list and adds the files.

Reads/writes drop state directly on `state.lists` (`external_drag_active`,
`hovered_button_index`), shared with the list-display engine (`ui/lists.py`).
Sibling modules are imported directly: `windowing` (popup_menu), `lists`
(show_playlist/show_list refresh), `cache_download` (prefetch_next_themes).
"""

import os
from core.game_state import state
from .scaling import scl
import sys
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import filedialog, Menu
import tkinterdnd2 as tkdnd
import pyautogui

import _app_scripts.ui.windowing as windowing
from . import lists
from ..playback import cache_download


def enable_drag_and_drop(widget, callback):
    """Enable drag-and-drop for files from Windows Explorer."""

    # Method 1: Try tkinterdnd2 (best option)
    try:

        root = widget.winfo_toplevel()
        if hasattr(root, 'drop_target_register') or isinstance(root, tkdnd.Tk):
            widget.drop_target_register(tkdnd.DND_FILES)

            def handle_drop(event):
                state.lists.external_drag_active = False  # Clear external drag state

                files = widget.tk.splitlist(event.data)
                if files and callback:
                    callback(files, event=event)
                return "copy"

            widget.dnd_bind('<<Drop>>', handle_drop)
            return True
        else:
            raise Exception("Root window not tkinterdnd2-enabled")

    except Exception as e:
        print(f"tkinterdnd2 failed: {e}")

    # Method 2: Windows API (more reliable than before)
    if sys.platform.startswith('win'):
        try:
            # Get window handle
            hwnd = widget.winfo_id()

            # Enable file dropping
            ctypes.windll.shell32.DragAcceptFiles(hwnd, True)

            # Store the original window procedure
            GWL_WNDPROC = -4
            original_wndproc = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)

            def window_proc(hwnd, msg, wparam, lparam):
                WM_DROPFILES = 0x0233
                if msg == WM_DROPFILES:
                    try:
                        file_count = ctypes.windll.shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                        files = []

                        for i in range(file_count):
                            length = ctypes.windll.shell32.DragQueryFileW(wparam, i, None, 0)
                            buffer = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.shell32.DragQueryFileW(wparam, i, buffer, length + 1)
                            files.append(buffer.value)

                        ctypes.windll.shell32.DragFinish(wparam)

                        if files and callback:
                            # Use after_idle to safely call callback from main thread
                            # Note: Windows API doesn't provide event coordinates easily
                            widget.after_idle(lambda f=files: callback(f, event=None))
                        return 0
                    except Exception as e:
                        print(f"Drop handling error: {e}")

                # Call original window procedure
                return ctypes.windll.user32.CallWindowProcW(original_wndproc, hwnd, msg, wparam, lparam)

            # Set up the window procedure with proper signature
            WNDPROC = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            new_wndproc = WNDPROC(window_proc)

            # Replace window procedure
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, new_wndproc)

            # Store reference to prevent garbage collection
            widget._drag_drop_wndproc = new_wndproc
            widget._original_wndproc = original_wndproc

            return True

        except Exception as e:
            print(f"Windows API drag-and-drop failed: {e}")

    # Method 3: Fallback to file dialogs
    try:
        def show_file_dialog(event=None):
            files = filedialog.askopenfilenames(
                title="Select media files to add to playlist",
                filetypes=[
                    ("Media files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.mp3 *.wav *.ogg *.m4a *.flac"),
                    ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm"),
                    ("Audio files", "*.mp3 *.wav *.ogg *.m4a *.flac"),
                    ("All files", "*.*")
                ]
            )
            if files and callback:
                callback(list(files), event=None)

        def show_context_menu(event):
            menu = Menu(widget, tearoff=0)
            menu.add_command(label="📁 Add Files to Playlist...", command=show_file_dialog)
            windowing.popup_menu(menu, event.x_root, event.y_root)

        widget.bind("<Button-3>", show_context_menu)
        widget.bind("<Double-Button-1>", show_file_dialog)

        print(f"📁 File selection enabled on {widget.__class__.__name__}: Right-click or double-click")
        return True

    except Exception as e:
        print(f"Could not set up file selection: {e}")
        return False


def handle_dropped_files(files, event=None):
    """Handle files dropped from Windows Explorer."""
    added_files = []

    # Try to detect drop position using coordinates (since hover events don't work during external drag)
    insert_position = None

    if event is not None and state.lists.list_loaded == "playlist":
        try:
            if state.widgets.right_column is not None:
                # Get the playlist widget position and bounds
                state.widgets.right_column.update_idletasks()
                widget_x = state.widgets.right_column.winfo_rootx()
                widget_y = state.widgets.right_column.winfo_rooty()
                widget_width = state.widgets.right_column.winfo_width()
                widget_height = state.widgets.right_column.winfo_height()

                if (widget_x <= event.x_root <= widget_x + widget_width and
                    widget_y <= event.y_root <= widget_y + widget_height):

                    # Calculate relative position within the text widget
                    relative_x = event.x_root - widget_x
                    relative_y = event.y_root - widget_y

                    # Use Text widget's index method to get the line at the drop position
                    try:
                        text_index = state.widgets.right_column.index(f"@{relative_x},{relative_y}")
                        drop_line = int(text_index.split('.')[0])

                        if state.lists.list_loaded == "playlist":
                            insert_position = max(0, drop_line - 1 + state.lists.playlist_page_offset)
                            playlist_size = len(state.metadata.playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                        else:
                            content = state.widgets.right_column.get("1.0", "2.0")
                            if "items above" in content:
                                drop_line = max(1, drop_line - 1)

                            # Convert to 0-based index and clamp to valid range
                            insert_position = max(0, drop_line - 1)
                            playlist_size = len(state.metadata.playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                    except (ValueError, tk.TclError):
                        button_height = scl(12) + 8
                        insert_position = max(0, int(relative_y / button_height))
                        playlist_size = len(state.metadata.playlist.get("playlist", []))
                        insert_position = min(insert_position, playlist_size)
        except Exception as e:
            print(f"DEBUG: Event position detection failed: {e}")

    if insert_position is None and state.lists.list_loaded == "playlist":
        try:
            mouse_x, mouse_y = pyautogui.position()

            if state.widgets.right_column is not None:
                state.widgets.right_column.update_idletasks()
                widget_x = state.widgets.right_column.winfo_rootx()
                widget_y = state.widgets.right_column.winfo_rooty()
                widget_width = state.widgets.right_column.winfo_width()
                widget_height = state.widgets.right_column.winfo_height()

                if (widget_x <= mouse_x <= widget_x + widget_width and
                    widget_y <= mouse_y <= widget_y + widget_height):

                    # Calculate relative position within the text widget
                    relative_x = mouse_x - widget_x
                    relative_y = mouse_y - widget_y

                    # Use Text widget's index method to get the line at the mouse position
                    try:
                        text_index = state.widgets.right_column.index(f"@{relative_x},{relative_y}")
                        drop_line = int(text_index.split('.')[0])

                        if state.lists.list_loaded == "playlist":
                            insert_position = max(0, drop_line - 1 + state.lists.playlist_page_offset)
                            playlist_size = len(state.metadata.playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                        else:
                            content = state.widgets.right_column.get("1.0", "2.0")
                            if "items above" in content:
                                drop_line = max(1, drop_line - 1)

                            # Convert to 0-based index and clamp to valid range
                            insert_position = max(0, drop_line - 1)
                            playlist_size = len(state.metadata.playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                    except (ValueError, tk.TclError):
                        button_height = scl(12) + 8
                        relative_position = max(0, int(relative_y / button_height))
                        if state.lists.list_loaded == "playlist":
                            insert_position = relative_position + state.lists.playlist_page_offset
                        else:
                            insert_position = relative_position
                        playlist_size = len(state.metadata.playlist.get("playlist", []))
                        insert_position = min(insert_position, playlist_size)
        except Exception as e:
            print(f"DEBUG: Mouse position detection failed: {e}")

    # Method 3: Default fallback
    if insert_position is None:
        current_index = state.metadata.playlist.get("current_index", -1)
        insert_position = current_index + 1 if current_index >= 0 else len(state.metadata.playlist["playlist"])

    # Clear any leftover hover state
    state.lists.hovered_button_index = None

    for file_path in files:
        if os.path.isfile(file_path):
            # Get just the filename without path
            filename = os.path.basename(file_path)

            # Always add to playlist (allow duplicates)
            if filename in state.metadata.directory_files:
                # Local file - store just filename
                playlist_entry = filename
            else:
                # External file - store full path
                playlist_entry = file_path

            # Insert at the specified position
            state.metadata.playlist["playlist"].insert(insert_position, playlist_entry)
            added_files.append(filename)  # Still show just filename in messages

            current_index = state.metadata.playlist.get("current_index", -1)
            if current_index >= 0 and insert_position <= current_index:
                state.metadata.playlist["current_index"] = current_index + 1

            insert_position += 1  # Increment for next file

    # Show summary message
    if added_files:
        # Update the playlist display after adding files
        try:
            lists.show_playlist(update=True)
        except NameError:
            # If show_playlist function doesn't exist, try other display functions
            try:
                lists.show_list("playlist", None, None, None, None, None, update=True)
            except Exception:
                print("Could not refresh playlist display")

    # Clear hover state after drop
    state.lists.hovered_button_index = None

    if state.lists.list_loaded == "playlist":
        lists.show_playlist(True)
    if added_files:
        cache_download.prefetch_next_themes()
