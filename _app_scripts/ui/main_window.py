"""Builders for the main window's GUI widget tree.

Extracted from guess_the_anime.py to keep that file a thin bootstrap. Each
builder creates its widgets, packs them, and publishes the long-lived ones onto
state.widgets for the rest of the app to read. Widgets that nothing outside the
builder references stay local.
"""

import tkinter as tk
from tkinter import ttk, font
import tkinterdnd2 as tkdnd

from core.game_state import state
from core.app_meta import WINDOW_TITLE
from core import app_icon
from _app_scripts.ui.scaling import scl
from _app_scripts.ui import styling
import _app_scripts.ui.lists as lists
import _app_scripts.ui.drag_and_drop as drag_and_drop
import _app_scripts.playback.transport as transport
import _app_scripts.toggles.audio_toggles as audio_toggles
import _app_scripts.toggles.autoplay as autoplay_toggles


def create_root_window():
    """Create and configure the top-level app window and the first-row toolbar host.

    Returns (root, first_row_frame); the caller publishes both onto state.widgets.
    Uses tkinterdnd2's Tk subclass for native file-drop support, falling back to a
    plain tk.Tk() if it is unavailable. Drag-and-drop is wired on a 500ms delay so
    the window is realized first.
    """
    BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR

    try:
        root = tkdnd.Tk()
    except ImportError:
        root = tk.Tk()
    except Exception:
        root = tk.Tk()

    ROOT_MIN_HEIGHT = 540
    root.title(WINDOW_TITLE)
    root.geometry(f"{scl(1200, 'UI')}x{scl(ROOT_MIN_HEIGHT, 'UI')}")
    root.minsize(scl(900, "UI"), scl(ROOT_MIN_HEIGHT, "UI"))  # prevent controls squishing
    root.configure(bg=BACKGROUND_COLOR)

    app_icon.set_app_icon(root)

    def setup_main_window_drag_drop():
        try:
            drag_and_drop.enable_drag_and_drop(root, drag_and_drop.handle_dropped_files)
        except Exception as e:
            print(f"Could not enable drag-and-drop on main window: {e}")

    root.after(500, setup_main_window_drag_drop)

    # First row (toolbar host) + its thin bottom border
    first_row_frame = tk.Frame(root, bg=BACKGROUND_COLOR)
    first_row_frame.pack(pady=(0, 0), fill="x", anchor="w")
    first_row_border = tk.Frame(root, bg="gray30", height=1)
    first_row_border.pack(fill="x")

    return root, first_row_frame


def build_columns(root):
    """Build the three info columns + the right-column list UI (header, scrollbar,
    list text widget, bindings) and configure their text-formatting tags.

    Publishes the long-lived column widgets onto state.widgets; the right-column
    container is local (only its children are read elsewhere).
    """
    BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR

    info_panel = tk.Frame(root, bg="black")
    info_panel.pack(fill="both", expand=True, padx=scl(10, "UI"), pady=scl(5, "UI"))

    # Left Column
    left_column = tk.Text(info_panel, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                          insertbackground="white", state=tk.DISABLED,
                          selectbackground=state.colors.HIGHLIGHT_COLOR, wrap="word")
    left_column.pack(side="left", fill="both", expand=True)

    # Middle Column
    middle_column = tk.Text(info_panel, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                            insertbackground="white", state=tk.DISABLED,
                            selectbackground=state.colors.HIGHLIGHT_COLOR, wrap="word")
    middle_column.pack(side="left", fill="both", expand=True)

    right_column_container = tk.Frame(info_panel, bg="black")
    right_column_container.pack(side="left", fill="both", expand=True)

    # Top Shorter Column (e.g., header, stats, etc.)
    right_top = tk.Text(right_column_container, height=0, width=scl(40, "UI"), bg="black", fg="white",
                        insertbackground="white", state=tk.DISABLED,
                        selectbackground=state.colors.HIGHLIGHT_COLOR, wrap="word")
    right_top.pack(fill="x")

    # List title header — shown/hidden by _insert_list_title_row, fills full column width
    _header_font = font.Font(family="Consolas", size=scl(11, "UI"), weight="bold", underline=True)
    list_header_font = _header_font  # expose for _truncate_header_title
    right_column_header = tk.Frame(right_column_container, bg=BACKGROUND_COLOR)
    right_column_back_button = tk.Button(right_column_header, text="←", bg=BACKGROUND_COLOR, fg=BACKGROUND_COLOR,
                                          font=_header_font, borderwidth=0, pady=0,
                                          command=lists._go_back_list)
    right_column_back_button.pack(side="left")  # always packed; visibility toggled via fg color
    right_column_header_label = tk.Label(right_column_header, text="", bg=BACKGROUND_COLOR, fg="white",
                                          font=_header_font, anchor="center", justify="center")
    right_column_header_label.pack(side="left", fill="x", expand=True)
    tk.Button(right_column_header, text="✕", bg=BACKGROUND_COLOR, fg="white",
              font=_header_font, borderwidth=0, pady=0,
              command=lambda: lists._close_list(right_column)).pack(side="right")
    # <Configure> is intentionally bound to right_column (below), not right_column_header,
    # so that changing the label text inside the header never re-triggers truncation.
    # Not packed yet — _insert_list_title_row shows/hides it before right_column_row

    # Main Right Column (with custom canvas scrollbar)
    right_column_row = tk.Frame(right_column_container, bg="black")
    right_column_row.pack(fill="both", expand=True)

    # Build a fully styled scrollbar by borrowing clam elements (native tk.Scrollbar ignores colors on Windows)
    styling.configure_list_scrollbar_style()

    right_column_scrollbar = ttk.Scrollbar(right_column_row, orient="vertical",
                                            command=lists.on_list_scrollbar_set,
                                            style="List.Vertical.TScrollbar")
    # Not packed initially — update_list_scrollbar shows/hides it as needed
    right_column = tk.Text(right_column_row, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                           insertbackground="white", state=tk.DISABLED,
                           selectbackground=state.colors.HIGHLIGHT_COLOR, wrap="word",
                           spacing1=0, spacing2=0, spacing3=0)
    right_column.pack(side="left", fill="both", expand=True)
    # Bind truncation to right_column so that header-label text changes never
    # feed back into more Configure events (right_column is our width reference anyway).
    right_column.bind("<Configure>", lists._truncate_header_title)

    # Expose the long-lived column widgets on state.widgets for extracted modules.
    state.widgets.left_column = left_column
    state.widgets.middle_column = middle_column
    state.widgets.right_column = right_column
    state.widgets.info_panel = info_panel
    state.widgets.right_top = right_top
    state.widgets.right_column_row = right_column_row
    state.widgets.right_column_scrollbar = right_column_scrollbar
    state.widgets.right_column_header = right_column_header
    state.widgets.right_column_header_label = right_column_header_label
    state.widgets.right_column_back_button = right_column_back_button
    state.widgets.list_header_font = list_header_font

    right_column.bind("<B1-Motion>", lambda e: lists.handle_drag_motion(e) if state.lists.drag_start_index is not None else None)
    right_column.bind("<ButtonRelease-1>", lambda e: lists.end_playlist_drag(e) if state.lists.drag_start_index is not None else None)

    right_column.bind("<MouseWheel>", lists.handle_list_scroll)
    right_column.bind("<Button-4>", lambda e: lists.handle_btn_scroll_up(e))  # Linux scroll up
    right_column.bind("<Button-5>", lambda e: lists.handle_btn_scroll_down(e))  # Linux scroll down

    # Text formatting tags
    left_font_name = "Arial"
    middle_font_name = "Arial"
    right_font_name = "Arial"
    left_column.tag_configure("bold", font=(left_font_name, scl(12, "UI"), "bold"), foreground="white")
    left_column.tag_configure("underline", underline=True)
    middle_column.tag_configure("bold", font=(middle_font_name, scl(12, "UI"), "bold"), foreground="white")
    middle_column.tag_configure("highlight", background="#333333", foreground="white", font=(middle_font_name, scl(12, "UI"), "bold"))  # Dark gray highlight
    middle_column.tag_configure("underline", underline=True)
    right_column.tag_configure("bold", font=(right_font_name, scl(12, "UI"), "bold"), foreground="white")
    right_column.tag_configure("highlight", background=state.colors.HIGHLIGHT_COLOR, foreground="white", font=(right_font_name, scl(12, "UI"), "bold"))  # Dark gray highlight
    right_column.tag_configure("highlightreg", background=state.colors.HIGHLIGHT_COLOR, foreground="white", font=(right_font_name, scl(12, "UI")))  # Dark gray highlight
    right_column.tag_configure("underline", underline=True)
    left_column.tag_configure("white", foreground="white", font=(left_font_name, scl(12, "UI")))
    left_column.tag_configure("blank", foreground="white", font=(left_font_name, scl(3, "UI")))
    middle_column.tag_configure("white", foreground="white", font=(middle_font_name, scl(12, "UI")))
    middle_column.tag_configure("blank", foreground="white", font=(middle_font_name, scl(6, "UI")))
    right_column.tag_configure("white", foreground="white", font=(right_font_name, scl(12, "UI")))
    right_column.tag_configure("blank", foreground="white", font=(right_font_name, scl(6, "UI")))
    right_top.tag_configure("bold", font=(right_font_name, scl(12, "UI"), "bold"), foreground="white")
    right_top.tag_configure("white", foreground="white", font=(right_font_name, scl(12, "UI")))


def build_controls_row(root):
    """Build the bottom video-controls row: volume box, transport buttons, seek bar.

    Publishes volume_label, autoplay_button, and seek_bar onto state.widgets; the
    transport buttons and volume sub-widgets are local (nothing else reads them).
    """
    # Video controls
    controls_frame = tk.Frame(root, bg="black")
    controls_frame.pack(pady=0, fill="x", expand=False)
    controls_frame.pack_propagate(False)  # Prevent children from controlling frame size
    controls_frame.configure(height=scl(80, "UI"))  # Set fixed height for controls

    # Volume control container
    volume_container = tk.Frame(controls_frame, bg="black", highlightbackground="white", highlightthickness=2, padx=2, pady=2)
    volume_container.pack(side="left", padx=(scl(10, "UI"), scl(5, "UI")))

    # Left side: icon and number
    volume_left_frame = tk.Frame(volume_container, bg="black")
    volume_left_frame.pack(side="left", padx=(2, 0))

    # Volume icon
    volume_icon = tk.Label(volume_left_frame, text="🔊", bg="black", fg="white",
                            font=("Arial", scl(12, "UI"), "bold"), pady=0)
    volume_icon.pack(pady=0)

    # Volume label (displays current volume)
    volume_label = tk.Label(volume_left_frame, text=str(state.controls.volume_level), bg="black", fg="white",
                             font=("Arial", scl(14, "UI"), "bold"), width=3, pady=0)
    volume_label.pack(pady=0)
    state.widgets.volume_label = volume_label

    # Right side: buttons
    volume_buttons_frame = tk.Frame(volume_container, bg="black")
    volume_buttons_frame.pack(side="left", padx=(0, 2))

    # Volume up button
    volume_up_button = tk.Button(volume_buttons_frame, text="➕", command=audio_toggles.increase_volume, bg="black", fg="white",
                                  font=("Arial", scl(12, "UI"), "bold"), border=0, width=2, height=1, pady=0)
    volume_up_button.pack(pady=0)
    volume_up_button.bind("<Button-3>", audio_toggles.increase_volume_small)

    # Volume down button
    volume_down_button = tk.Button(volume_buttons_frame, text="➖", command=audio_toggles.decrease_volume, bg="black", fg="white",
                                    font=("Arial", scl(12, "UI"), "bold"), border=0, width=2, height=1, pady=0)
    volume_down_button.pack(pady=0)
    volume_down_button.bind("<Button-3>", audio_toggles.decrease_volume_small)

    play_pause_button = tk.Button(controls_frame, text="⏯", command=transport.play_pause, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
    play_pause_button.pack(side="left", padx=0)

    stop_button = tk.Button(controls_frame, text="⏹", command=transport.stop, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
    stop_button.pack(side="left", padx=0)

    previous_button = tk.Button(controls_frame, text="⏮", command=transport.play_previous, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
    previous_button.pack(side="left", padx=0)

    next_button = tk.Button(controls_frame, text="⏭", command=transport.play_next, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
    next_button.pack(side="left", padx=0)
    def _next_btn_right_click(e):
        # Local import: web_search loads after GUI build in main; the handler only
        # fires at runtime, so importing here avoids pulling it in at builder load.
        import _app_scripts.file.web_server.web_search as web_search
        root.after(0, lambda: web_search._invoke_registry_by_id("skip_to_end_ff"))
    next_button.bind("<Button-3>", _next_btn_right_click)

    autoplay_button = tk.Button(controls_frame, text="🔁", command=autoplay_toggles.show_autoplay_menu, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2, anchor="center", justify="center")
    state.widgets.autoplay_button = autoplay_button
    autoplay_button.pack(side="left", padx=0, pady=(0,scl(15, "UI")))
    autoplay_button.bind('<Button-3>', autoplay_toggles.toggle_special_repeat)

    # Seek bar
    seek_bar = tk.Scale(controls_frame, from_=0, to=1000, orient=tk.HORIZONTAL, command=transport.seek, length=2000, resolution=0.1, bg="black", fg="white")
    seek_bar.pack(side="left", fill="x", padx=(scl(5, "UI"),scl(10, "UI")))
    state.widgets.seek_bar = seek_bar  # mirror for transport.stop (reads state.widgets.seek_bar)
