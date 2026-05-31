# _app_scripts/generic_settings_editor.py
# Generic tree-based settings editor - extracted from guess_the_anime.py (Step 36).
import ast
import copy

import tkinter as tk
from tkinter import ttk, simpledialog

from core.game_state import state
import _app_scripts.utils as utils

# ---------------------------------------------------------------------------
# Injected context (populated by set_context() at startup)
# ---------------------------------------------------------------------------
get_window_position_and_setup = None

# Module-private window state (was a main-file global)
generic_settings_editor_window = None


def set_context(*, get_window_position_and_setup):
    g = globals()
    g['get_window_position_and_setup'] = get_window_position_and_setup


def open_generic_settings_editor(
    title,
    current_settings_dict,
    default_settings_dict,
    saved_settings_dict,
    selected_setting_name,
    on_apply_callback,
    on_save_config_callback
):
    """
    Generic settings editor with tree UI.
    
    Args:
        title: Window title
        current_settings_dict: The current settings dictionary to edit (will be modified in-place)
        default_settings_dict: The default settings dictionary for comparison
        saved_settings_dict: Dictionary of saved preset settings
        selected_setting_name: Current selected preset name
        on_apply_callback: Callback(new_settings, selected_name) called when Apply is clicked
        on_save_config_callback: Callback() called when settings need to be saved to config
    """
    
    root = state.widgets.root

    def parse_literal(value):
        try:
            parsed = ast.literal_eval(value)
            # Convert infinity markers back to float('inf')
            if isinstance(parsed, str):
                if parsed == "__INFINITY__":
                    return float('inf')
                elif parsed == "__NEG_INFINITY__":
                    return float('-inf')
                elif parsed == "inf":
                    return float('inf')
                elif parsed == "-inf":
                    return float('-inf')
            return parsed
        except Exception:
            if isinstance(value, str):
                if value == "__INFINITY__":
                    return float('inf')
                elif value == "__NEG_INFINITY__":
                    return float('-inf')
                elif value == "inf":
                    return float('inf')
                elif value == "-inf":
                    return float('-inf')
            return value

    def insert_into_tree(tree, parent, d, default_sub=None):
        """Insert items into the tree. If `default_sub` is provided, compare values to it
        and tag modified nodes with 'modified'."""
        if default_sub is None:
            default_sub = default_settings_dict if isinstance(default_settings_dict, dict) else {}

        if isinstance(d, dict):
            for key, val in d.items():
                if key == "range" and isinstance(val, (list, tuple)) and len(val) == 2:
                    node_id = tree.insert(parent, 'end', text=str(key), open=False)
                    # Compare with default
                    def_range = default_sub.get(key) if isinstance(default_sub, dict) else None
                    tree.insert(node_id, 'end', text=f"min: {val[0]}", open=False)
                    tree.insert(node_id, 'end', text=f"max: {val[1]}", open=False)
                    # If default range exists and differs, tag parent
                    if isinstance(def_range, (list, tuple)) and len(def_range) == 2 and (def_range[0] != val[0] or def_range[1] != val[1]):
                        tree.item(node_id, tags=('modified',))
                elif isinstance(val, (bool, int, float, str)) or val is None:
                    node_text = f"{key}: {val}"
                    node_id = tree.insert(parent, 'end', text=node_text, open=False)
                    # Compare with default
                    default_val = None
                    if isinstance(default_sub, dict) and key in default_sub:
                        default_val = default_sub[key]
                    # For display types, parse_literal used elsewhere; we compare raw Python values
                    if default_val is not None and val != default_val:
                        tree.item(node_id, tags=('modified',))
                else:
                    node_id = tree.insert(parent, 'end', text=str(key), open=False)
                    sub_default = default_sub.get(key) if isinstance(default_sub, dict) else {}
                    insert_into_tree(tree, node_id, val, sub_default)
                    # If any child is tagged modified, tag this parent too
                    for child in tree.get_children(node_id):
                        if 'modified' in tree.item(child, 'tags'):
                            tree.item(node_id, tags=('modified',))
                            break
        elif isinstance(d, (list, tuple)):
            for i, val in enumerate(d):
                node_id = tree.insert(parent, 'end', text=f"[{i}]", open=False)
                sub_default = None
                if isinstance(default_sub, (list, tuple)) and i < len(default_sub):
                    sub_default = default_sub[i]
                insert_into_tree(tree, node_id, val, sub_default)
                for child in tree.get_children(node_id):
                    if 'modified' in tree.item(child, 'tags'):
                        tree.item(node_id, tags=('modified',))
                        break
        else:
            node_id = tree.insert(parent, 'end', text=str(d), open=False)
            if default_sub is not None and not isinstance(default_sub, dict) and d != default_sub:
                tree.item(node_id, tags=('modified',))

    def tree_to_dict(tree, parent=''):
        children = tree.get_children(parent)
        if not children:
            text = tree.item(parent, 'text')
            if ": " in text:
                key, val = text.rsplit(": ", 1)
                return {key: parse_literal(val)}
            return parse_literal(text)

        if len(children) == 2:
            texts = [tree.item(child, 'text') for child in children]
            if (texts[0].startswith('min: ') and texts[1].startswith('max: ')) or (texts[1].startswith('min: ') and texts[0].startswith('max: ')):
                min_val = None
                max_val = None
                for child in children:
                    t = tree.item(child, 'text')
                    if t.startswith('min: '):
                        min_val = parse_literal(t[5:])
                    elif t.startswith('max: '):
                        max_val = parse_literal(t[5:])
                return [min_val, max_val]

        # If this node is a dict key node and has exactly one child, and that child has no children,
        # treat the child as the value leaf node
        if len(children) == 1:
            only_child = children[0]
            if not tree.get_children(only_child):
                text = tree.item(only_child, 'text')
                if ": " in text:
                    key, val = text.rsplit(": ", 1)
                    return {key: parse_literal(val)}
                return parse_literal(text)

        is_list = all(tree.item(child, 'text').startswith('[') for child in children)
        if is_list:
            return [tree_to_dict(tree, child) for child in children]

        result = {}
        for child in children:
            text = tree.item(child, 'text')
            # If leaf is 'key: value', split and use key, value
            if not tree.get_children(child) and ": " in text:
                key, val = text.rsplit(": ", 1)
                result[key] = parse_literal(val)
            else:
                key = text
                val = tree_to_dict(tree, child)
                result[key] = val
        return result

    def rebuild_tree(data):
        tree.delete(*tree.get_children())
        insert_into_tree(tree, '', data, default_settings_dict)

    def on_double_click(event):
        item_id = tree.selection()[0]

        if tree.get_children(item_id):
            return

        old_value = tree.item(item_id, 'text')

        if ": True" in old_value or ": False" in old_value:
            key, val = old_value.rsplit(": ", 1)
            if val == "True":
                new_val = "False"
            else:
                new_val = "True"
            tree.item(item_id, text=f"{key}: {new_val}")
            return

        if ": " in old_value and not tree.get_children(item_id):
            key, val = old_value.rsplit(": ", 1)
            entry = tk.Entry(tree, bg="#2a2a2a", fg="white", insertbackground="white")
            entry.insert(0, val)
            x, y, w, h = tree.bbox(item_id)
            entry.place(x=x, y=y, width=w)

            def save_edit(event):
                new_val = entry.get()
                tree.item(item_id, text=f"{key}: {new_val}")
                entry.destroy()

            entry.bind('<Return>', save_edit)
            entry.focus()
            return

        # Try to parse the old_value to actual Python type (legacy fallback)
        parsed_value = parse_literal(old_value)
        if isinstance(parsed_value, bool):
            new_value = not parsed_value
            tree.item(item_id, text=str(new_value))
            return

        # Otherwise, allow editing with Entry widget (legacy fallback)
        entry = tk.Entry(tree, bg="#2a2a2a", fg="white", insertbackground="white")
        entry.insert(0, old_value)
        x, y, w, h = tree.bbox(item_id)
        entry.place(x=x, y=y, width=w)

        def save_edit(event):
            tree.item(item_id, text=entry.get())
            entry.destroy()

        entry.bind('<Return>', save_edit)
        entry.focus()

    def apply_changes():
        nonlocal current_settings
        current_settings = tree_to_dict(tree)
        current_settings_dict.clear()
        # Store full settings in memory, but persistent storage will keep only diffs
        current_settings_dict.update(copy.deepcopy(current_settings))
        apply_button.configure(text="APPLIED!")
        on_apply_callback(current_settings, selected_settings)
        root.after(300, lambda: apply_button.configure(text="Apply"))
        on_save_config_callback()
        # Refresh tree to update modified highlighting (compare against defaults)
        try:
            tree.delete(*tree.get_children())
            insert_into_tree(tree, '', current_settings_dict, default_settings_dict)
        except Exception:
            pass

    def save_as():
        nonlocal selected_settings
        name = simpledialog.askstring("Save Settings As", "Enter a name for these settings:", initialvalue=saved_var.get())
        if name:
            saved_settings_dict[name] = copy.deepcopy(tree_to_dict(tree))
            refresh_saved_dropdown()
            saved_var.set(name)
            selected_settings = name
            on_save_config_callback()

    def load_selected():
        nonlocal selected_settings
        name = saved_var.get()
        if name in saved_settings_dict:
            selected_settings = name
            saved_settings_dict[name] = utils.sync_with_default(saved_settings_dict[name], default_settings_dict)
            rebuild_tree(saved_settings_dict[name])

    def delete_selected():
        nonlocal selected_settings
        name = saved_var.get()
        if name in saved_settings_dict:
            del saved_settings_dict[name]
            saved_var.set("")
            selected_settings = ""
            refresh_saved_dropdown()
            on_save_config_callback()

    def load_defaults():
        nonlocal selected_settings
        selected_settings = ""
        saved_var.set("")
        rebuild_tree(default_copy)

    def refresh_saved_dropdown():
        menu = saved_menu["menu"]
        menu.delete(0, "end")
        for name in saved_settings_dict:
            menu.add_command(label=name, command=lambda val=name: saved_var.set(val))
        saved_var.set(selected_settings)

    global generic_settings_editor_window
    if generic_settings_editor_window and generic_settings_editor_window.winfo_exists():
        generic_settings_editor_window.destroy()
    
    # Pop-out window
    window = tk.Toplevel()
    window.title(title)
    window.geometry("400x450")
    window.configure(bg="#1e1e1e")
    get_window_position_and_setup(window)
    
    # Track this window globally
    generic_settings_editor_window = window

    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure("Treeview", background="#1e1e1e", foreground="white", fieldbackground="#1e1e1e")
    style.configure("Treeview.Heading", background="#2a2a2a", foreground="white")
    style.map("Treeview", background=[("selected", "#333")])

    tree = ttk.Treeview(window)
    try:
        tree.tag_configure('modified', foreground='orange')
    except Exception:
        pass
    tree.pack(expand=True, fill='both', padx=10, pady=10)
    tree.bind('<Double-1>', on_double_click)

    # Load data
    default_copy = copy.deepcopy(default_settings_dict)
    current_settings = copy.deepcopy(current_settings_dict)
    selected_settings = selected_setting_name
    insert_into_tree(tree, '', current_settings, default_copy)

    # Control panel
    controls = tk.Frame(window, bg="#1e1e1e")
    controls.pack(fill='x', padx=10)

    apply_button = tk.Button(controls, text="Apply", command=apply_changes, bg="#444", fg="white")
    apply_button.pack(side="left", padx=5)
    tk.Button(controls, text="Save As", command=save_as, bg="#444", fg="white").pack(side="left", padx=5)
    tk.Button(controls, text="Load Defaults", command=load_defaults, bg="#444", fg="white").pack(side="left", padx=5)
    # Trim Saved button removed — trimming is performed automatically when saving.

    saved_var = tk.StringVar()
    saved_menu = tk.OptionMenu(controls, saved_var, "")
    saved_menu.configure(bg="#444", fg="white", highlightthickness=0, activebackground="#666")
    saved_menu["menu"].config(bg="#2a2a2a", fg="white")
    saved_menu.pack(side="left", padx=5)

    tk.Button(controls, text="Load", command=load_selected, bg="#444", fg="white").pack(side="left", padx=(0, 3))
    tk.Button(controls, text="X", command=delete_selected, bg="#aa3333", fg="white").pack(side="left")

    refresh_saved_dropdown()
