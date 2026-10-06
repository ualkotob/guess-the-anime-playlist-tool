"""Search focus recovery and delayed playlist-render regression coverage."""

from types import SimpleNamespace

import pytest

from core.game_state import state
from _app_scripts.search import search as search_ops
from _app_scripts.ui import lists


class _Root:
    def __init__(self):
        self.active = False
        self.focused = None
        self.grab = None
        self.pending = []

    def after_idle(self, callback):
        self.pending.append(callback)

    def run_idle(self):
        pending, self.pending = self.pending, []
        for callback in pending:
            callback()


class _Entry:
    def __init__(self, root, text="Banana Fish"):
        self.root = root
        self.text = text
        self.selection = None
        self.state = "normal"

    def winfo_exists(self):
        return True

    def winfo_toplevel(self):
        return self.root

    def grab_current(self):
        return self.root.grab

    def cget(self, name):
        return self.state

    def focus_set(self):
        # A regular Tk focus request does not restore native window activation.
        self.root.focused = self

    def focus_force(self):
        self.root.active = True
        self.root.focused = self

    def focus_get(self):
        return self.root.focused if self.root.active else None

    def get(self):
        return self.text

    def select_range(self, start, end):
        self.selection = (start, end)


class _Column:
    def __init__(self, root):
        self.root = root

    def focus_get(self):
        return self.root.focused if self.root.active else None

    def focus_set(self):
        self.root.focused = self

    def config(self, **kwargs):
        pass

    def delete(self, *args):
        pass

    def window_create(self, *args, **kwargs):
        pass

    def insert(self, *args):
        pass


@pytest.fixture
def search_field(monkeypatch):
    root = _Root()
    entry = _Entry(root)
    monkeypatch.setattr(state.widgets, "root", root)
    monkeypatch.setattr(search_ops, "search_bar_entry", entry)
    monkeypatch.setattr(search_ops.modal_guard, "modal_dialog_open", False)
    return root, entry


def test_search_click_recovers_native_focus_without_selecting_query(search_field):
    root, entry = search_field
    entry.focus_set()
    assert entry.focus_get() is None

    assert search_ops.on_search_click(SimpleNamespace(widget=entry)) is None

    root.run_idle()
    assert entry.focus_get() is entry
    assert entry.get() == "Banana Fish"
    assert entry.selection is None  # Normal Entry binding still controls the caret.


def _render_playlist(monkeypatch, root):
    monkeypatch.setattr(state, "lists", SimpleNamespace(
        list_loaded="field", list_index=0, current_list_offset=0,
        persistent_buttons=[object()],
    ))
    monkeypatch.setattr(state.metadata, "playlist", {"current_index": -1})
    monkeypatch.setattr(state.lightning, "fixed_lightning_round_playlist_data", None)
    monkeypatch.setattr(lists, "get_list_entries_count", lambda: 1)
    monkeypatch.setattr(lists, "_insert_list_title_row", lambda column: None)
    monkeypatch.setattr(lists, "update_persistent_button", lambda *args: None)
    monkeypatch.setattr(lists, "update_list_scrollbar", lambda: None)
    monkeypatch.setattr(lists.handle_persistent_right_click, "right_click_func", None, raising=False)
    column = _Column(root)
    lists.show_list("playlist", column, {"theme": "theme.webm"},
                    lambda *args: "Theme", lambda *args: None, 0, update=True)
    return column


def test_delayed_playlist_render_does_not_take_focus_after_search_click(search_field, monkeypatch):
    root, entry = search_field
    search_ops.on_search_click(SimpleNamespace(widget=entry))

    _render_playlist(monkeypatch, root)

    assert entry.focus_get() is entry
    assert state.lists.list_loaded == "playlist"


def test_playlist_render_still_focuses_list_when_search_is_unfocused(search_field, monkeypatch):
    root, entry = search_field
    column = _render_playlist(monkeypatch, root)
    assert root.focused is column


@pytest.mark.parametrize("dialog_kind", ["standard", "custom"])
def test_search_focus_does_not_bypass_an_active_dialog(search_field, monkeypatch, dialog_kind):
    root, entry = search_field
    dialog = SimpleNamespace()
    dialog.winfo_toplevel = lambda: dialog
    root.focused = dialog
    if dialog_kind == "standard":
        monkeypatch.setattr(search_ops.modal_guard, "modal_dialog_open", True)
    else:
        root.grab = dialog

    search_ops.on_search_click(SimpleNamespace(widget=entry))

    assert root.focused is dialog
    assert root.active is False
    if dialog_kind == "custom":
        assert root.grab is dialog


def test_search_shortcut_recovers_focus_and_selects_existing_query(search_field):
    root, entry = search_field
    search_ops._focus_search_entry()
    assert entry.focus_get() is entry
    assert entry.selection == (0, search_ops.tk.END)


def test_idle_diagnostic_ignores_a_replaced_search_widget(search_field, monkeypatch):
    root, entry = search_field
    warnings = []
    monkeypatch.setattr(search_ops, "log_warning", lambda *args: warnings.append(args))
    search_ops.on_search_click(SimpleNamespace(widget=entry))
    root.active = False
    monkeypatch.setattr(search_ops, "search_bar_entry", _Entry(root))
    root.run_idle()
    assert warnings == []


def test_failed_focus_recovery_is_logged_for_diagnosis(search_field, monkeypatch):
    root, entry = search_field
    warnings = []
    monkeypatch.setattr(search_ops, "log_warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(entry, "focus_force", lambda: None)
    search_ops.on_search_click(SimpleNamespace(widget=entry))
    root.run_idle()
    assert len(warnings) == 1
    assert "could not acquire focus" in warnings[0][0]
