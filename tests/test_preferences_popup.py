"""Exercise the real Preferences widgets without opening a visible window."""

import tkinter as tk
from tkinter import font, ttk

import pytest

from core.game_state import state
from _app_scripts.file import settings_popup


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def preferences(monkeypatch, tk_root):
    root = tk_root
    monkeypatch.setattr(state.widgets, "root", root)
    monkeypatch.setattr(settings_popup, "settings_window", None)
    monkeypatch.setattr(settings_popup.windowing, "get_window_position_and_setup", lambda window: window.withdraw())
    monkeypatch.setattr(settings_popup.scoreboard_control, "get_available_rules_files", lambda: [])
    monkeypatch.setattr(settings_popup.scoreboard_control, "AVAILABLE", True)
    monkeypatch.setattr(settings_popup.web_server, "NGROK_AVAILABLE", True)
    monkeypatch.setattr(settings_popup.web_server, "CLOUDFLARED_AVAILABLE", True)
    monkeypatch.setattr(state.config, "theme_online_source", "prefer_animethemes")
    monkeypatch.setattr(state.config, "theme_downloaded_first", True)
    monkeypatch.setattr(state.config, "theme_allow_excluded_downloads", True)
    settings_popup.show_settings_popup()
    root.update_idletasks()
    window = settings_popup.settings_window
    yield window
    window.destroy()
    root.withdraw()


def _widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _widgets(child)


def test_source_choices_enable_download_exception_only_for_only_modes(preferences):
    widgets = list(_widgets(preferences))
    source = next(widget for widget in widgets if isinstance(widget, ttk.Combobox)
                  and "Prefer AnimeThemes" in widget["values"])
    exception = next(widget for widget in widgets if isinstance(widget, tk.Checkbutton)
                     and widget.getvar(widget["textvariable"]) == "Allow downloaded copies")
    assert str(source["state"]) == "readonly"
    assert str(exception["state"]) == "disabled"
    source.set("AniSongDB only")
    assert str(exception["state"]) == "normal"
    source.set("Prefer AniSongDB")
    assert str(exception["state"]) == "disabled"


def test_preferences_columns_have_matching_rows_and_unclipped_labels(preferences):
    # Allocate the real layout off screen; withdrawn windows retain 1px sizes.
    preferences.geometry(f"{preferences.winfo_reqwidth()}x{preferences.winfo_reqheight()}+10000+10000")
    preferences.master.geometry("1x1+10000+10000")
    preferences.master.deiconify()
    preferences.deiconify()
    preferences.update()
    main_frame = preferences.winfo_children()[0]
    columns_frame = main_frame.winfo_children()[0]
    columns = columns_frame.winfo_children()
    assert len(columns) == 2
    assert columns[0].winfo_reqwidth() <= columns[1].winfo_width()
    assert columns[0].winfo_width() == columns[1].winfo_width()
    row_counts = []
    row_heights = set()
    for column in columns:
        labels = [widget for widget in column.winfo_children() if isinstance(widget, tk.Label)]
        row_counts.append(len(labels))
        for label in labels:
            label_font = font.Font(root=preferences, font=label["font"])
            assert label_font.measure(label["text"]) <= label.winfo_reqwidth() - 4
            row = int(label.grid_info()["row"])
            row_heights.add(column.grid_bbox(0, row, 1, row)[3])
    assert len(row_heights) == 1
    assert next(iter(row_heights)) >= 36
    assert abs(row_counts[0] - row_counts[1]) <= 1
    source_label = next(widget for widget in columns[0].winfo_children()
                        if isinstance(widget, tk.Label) and widget["text"] == "Online Source:")
    row = int(source_label.grid_info()["row"])
    following = {int(widget.grid_info()["row"]): widget["text"] for widget in columns[0].winfo_children()
                 if isinstance(widget, tk.Label)}
    assert following[row + 1] == "Downloaded Files:"
    assert following[row + 2] == "Excluded Downloads:"


def test_save_uses_stable_source_value_and_both_checkboxes(preferences, monkeypatch):
    from _app_scripts.playlists import playlist, infinite

    widgets = list(_widgets(preferences))
    source = next(widget for widget in widgets if isinstance(widget, ttk.Combobox)
                  and "Prefer AnimeThemes" in widget["values"])
    source.set("AniSongDB only")
    for widget in widgets:
        if isinstance(widget, tk.Checkbutton) and widget["textvariable"] and widget.getvar(widget["textvariable"]) in {
                "Use downloaded files first", "Allow downloaded copies"}:
            widget.invoke()
    saved = []
    monkeypatch.setattr(settings_popup.config_io, "save_config", lambda: saved.append((
        state.config.theme_online_source, state.config.theme_downloaded_first,
        state.config.theme_allow_excluded_downloads)))
    monkeypatch.setattr(settings_popup.config_io, "load_config", lambda: None)
    monkeypatch.setattr(playlist, "invalidate_deduplicated_cache", lambda: None)
    monkeypatch.setattr(infinite, "reset_infinite_caches", lambda: None)
    save = next(widget for widget in widgets if isinstance(widget, tk.Button) and widget["text"] == "SAVE SETTINGS")
    save.invoke()
    assert saved == [("anisongdb_only", False, False)]
