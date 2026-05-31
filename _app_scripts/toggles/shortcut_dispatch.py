"""Runtime keyboard + mouse shortcut dispatch.

Owns the pynput on_press/on_release/on_mouse_* handlers and the in-flight
mouse-drag animation state (grow overlay + zoom filter). Reads cross-cutting
main state (disable_shortcuts, list_loaded, playlist, _shortcut_dispatch, etc.)
and dispatches into main functions through the `_main` module reference.

`disable_shortcuts` and `_shortcut_dispatch` stay in main because many other
sites read/build them; this module reads them live via `_main.X`.
"""

import tkinter as tk
from pynput import keyboard, mouse

import _app_scripts.file.modal_guard as modal_guard
from _app_scripts.queue_round.lightning_rounds import (
    grow_overlay,
    peek_overlay,
    edge_overlay,
    filter_overlay,
)

_main = None

# Mouse-drag animation state (owned here; grow_overlay resets via direct attr
# write — see grow_overlay.toggle_grow_overlay destroy path).
mouse_left_pressed = False
mouse_dragging_grow_overlay = False
mouse_dragging_zoom_filter = False
target_mouse_position = None
animation_after_id = None
zoom_filter_animation_after_id = None


def set_context(*, main_module):
    global _main
    _main = main_module


def toggle_disable_shortcuts():
    _main.disable_shortcuts = not _main.disable_shortcuts
    print("Keyboard Shortcuts Disabled: " + str(_main.disable_shortcuts))
    # Close the search list if open so typed text doesn't trigger a search
    if _main.list_loaded in ["search", "search_add"]:
        _main._close_list(_main.right_column)


def _is_blocked_text_entry():
    """Return True if any Entry widget currently has keyboard focus.
    Pynput should be blocked whenever an Entry is focused — the toolbar search
    bar handles its own keys via Tkinter <KeyRelease>, and pynput-based search
    mode (list_loaded == 'search') is only active when no Entry is focused.
    Must be called from the main Tkinter thread."""
    try:
        focused = _main.root.focus_get()
        return focused is not None and isinstance(focused, tk.Entry)
    except Exception:
        return False


def on_press(key):
    def _handle(key=key):
        try:
            if modal_guard.is_modal_dialog_open():
                return
            if _is_blocked_text_entry():
                return
            if _main.disable_shortcuts:
                pass
            elif grow_overlay.grow_overlay_boxes:
                move_amount = 10  # pixels per key press
                if key == key.up:
                    _main.move_grow_position(0, -move_amount)
                elif key == key.down:
                    _main.move_grow_position(0, move_amount)
                elif key == key.left:
                    _main.move_grow_position(-move_amount, 0)
                elif key == key.right:
                    _main.move_grow_position(move_amount, 0)
            elif key == key.up:
                _main.list_move(-1)
            elif key == key.down:
                _main.list_move(1)
        except AttributeError:
            try:
                if _main.list_loaded == "search":
                    pass
                elif not _main.playlist.get("infinite", False) and (key.char == '-'):
                    _main.player.set_time(_main.player.get_time() - 1000)
                elif not _main.playlist.get("infinite", False) and (key.char == '+'):
                    _main.player.set_time(_main.player.get_time() + 1000)
            except AttributeError as e:
                print(f"Error: {e}")
    try:
        _main.root.after(0, _handle)
    except RuntimeError:
        pass


def on_release(key):
    def _handle(key=key):
        try:
            if modal_guard.is_modal_dialog_open():
                return
            if _is_blocked_text_entry():
                return
            if _main.popout_searching:
                pass
            elif _main.disable_shortcuts:
                try:
                    enable_key = _main.get_shortcut("enable_shortcuts")
                    if enable_key and key.char == enable_key:
                        cmd = _main._shortcut_dispatch.get(enable_key)
                        if cmd:
                            cmd()
                        else:
                            _main.toggle_disable_shortcuts()  # fallback before dispatch is built
                except:
                    pass
            elif _main.list_loaded in ["search", "search_add"]:
                if key == keyboard.Key.esc:
                    _main.search(add=_main.playlist.get("infinite", False))
                elif key == keyboard.Key.backspace:
                    if _main.search_ops.search_term != "":
                        _main.search_ops.search_term = _main.search_ops.search_term[:-1]
                    _main.search(True, add=_main.playlist.get("infinite", False))
                elif key == keyboard.Key.space:
                    _main.search_ops.search_term = _main.search_ops.search_term + " "
                    _main.search(True, add=_main.playlist.get("infinite", False))
                elif key == keyboard.Key.enter:
                    _main.list_select()
                    _main.search_ops.search_term = ""
                    _main.list_unload(_main.right_column)
                elif isinstance(key, keyboard.KeyCode) and key.char:
                    _main.search_ops.search_term = _main.search_ops.search_term + key.char
                    _main.search(True, add=_main.playlist.get("infinite", False))
            else:
                if isinstance(key, keyboard.Key):
                    if not grow_overlay.grow_overlay_boxes:
                        if key == keyboard.Key.right:
                            _main.play_next()
                        elif key == keyboard.Key.left:
                            _main.play_previous()
                    if key == keyboard.Key.space:
                        _main.play_pause()
                    elif key == keyboard.Key.esc:
                        _main.stop()
                    elif key == keyboard.Key.tab:
                        _main.player.toggle_fullscreen()
                    elif key == keyboard.Key.backspace:
                        if (peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active):
                            _main.toggle_peek()
                        else:
                            _main.blind(True)
                    elif key == keyboard.Key.enter:
                        _main.list_select()
                elif isinstance(key, keyboard.KeyCode) and key.char:
                    # --- Registry-driven dispatch ---
                    # Covers all shortcuts defined in DEFAULT_SHORTCUTS (or user overrides).
                    # Context-sensitive and aliased keys are handled below.
                    cmd = _main._shortcut_dispatch.get(key.char)
                    if cmd:
                        _main.root.after(0, cmd)
                    # --- 'i' has context-sensitive logic: shows info OR clears title popup ---
                    elif key.char == 'i':
                        if _main.is_title_window_up() and (_main.artist_info_display or _main.studio_info_display):
                            _main.toggle_title_popup(True)
                        else:
                            _main.toggle_info_popup()
                    # --- '+' is a secondary alias for '=' (peek toggle), not in DEFAULT_SHORTCUTS ---
                    elif key.char == '+':
                        _main.toggle_peek()
                    # --- Digits: context-sensitive (list select vs seek position) ---
                    elif key.char.isdigit():
                        if _main.list_loaded and _main.list_loaded != "playlist":
                            _main.list_index = int(key.char) - 1
                            _main.list_select()
                        else:
                            seek_value = _main.player.get_length() - ((_main.player.get_length() / 10) * (10 - int(key.char)))
                            _main.seek_to(int(seek_value))
                    # --- Infinite difficulty adjust (condition-gated, not suitable for registry) ---
                    elif _main.playlist.get("infinite") and (key.char in ['<', ',']):
                        if _main.playlist["difficulty"] > 0:
                            _main.playlist["difficulty"] -= 1
                            _main.difficulty_dropdown.current(_main.playlist["difficulty"])
                            _main.select_difficulty()
                    elif _main.playlist.get("infinite") and (key.char in ['>', '.']):
                        if _main.playlist["difficulty"] < len(_main.difficulty_options) - 1:
                            _main.playlist["difficulty"] += 1
                            _main.difficulty_dropdown.current(_main.playlist["difficulty"])
                            _main.select_difficulty()
        except AttributeError as e:
            print(f"Error: {e}")
    try:
        _main.root.after(0, _handle)
    except RuntimeError:
        pass


def smooth_move_zoom_filter_overlay():
    """Smoothly animate the zoom crop centre toward the target mouse position."""
    global zoom_filter_animation_after_id
    if not mouse_dragging_zoom_filter or not target_mouse_position:
        zoom_filter_animation_after_id = None
        return
    tx, ty = target_mouse_position
    # Normalise relative to the mpv player window so windowed mode works correctly
    try:
        mx, my, mw, mh = _main._get_mpv_window_rect()
    except Exception:
        mx, my, mw, mh = 0, 0, _main.root.winfo_screenwidth(), _main.root.winfo_screenheight()
    if mw <= 0 or mh <= 0:
        mx, my, mw, mh = 0, 0, _main.root.winfo_screenwidth(), _main.root.winfo_screenheight()
    norm_x = (tx - mx) / mw - 0.5
    norm_y = (ty - my) / mh - 0.5
    norm_x = max(-0.45, min(0.45, norm_x))
    norm_y = max(-0.45, min(0.45, norm_y))
    lerp = 0.15
    filter_overlay._filter_zoom_offset[0] += (norm_x - filter_overlay._filter_zoom_offset[0]) * lerp
    filter_overlay._filter_zoom_offset[1] += (norm_y - filter_overlay._filter_zoom_offset[1]) * lerp
    # force cache miss so vf is actually updated
    filter_overlay._filter_vf_last = None
    try:
        _main.toggle_filter_vf(filter_overlay._filter_vf_variant, filter_overlay._filter_vf_last_progress[0])
    except Exception:
        pass
    dist = ((norm_x - filter_overlay._filter_zoom_offset[0])**2 + (norm_y - filter_overlay._filter_zoom_offset[1])**2) ** 0.5
    if mouse_dragging_zoom_filter and dist > 0.003:
        zoom_filter_animation_after_id = _main.root.after(16, smooth_move_zoom_filter_overlay)
    else:
        zoom_filter_animation_after_id = None


def smooth_move_grow_overlay():
    """Smoothly animate the grow overlay toward the target mouse position."""
    global animation_after_id

    if not mouse_dragging_grow_overlay or not target_mouse_position:
        animation_after_id = None
        return

    current_x, current_y = grow_overlay.grow_position if grow_overlay.grow_position else (0, 0)
    raw_target_x, raw_target_y = target_mouse_position

    # Convert screen coordinates to OSD (mpv client area) coordinates
    try:
        mpv_ox, mpv_oy, mpv_ow, mpv_oh = _main._get_mpv_window_rect()
    except Exception:
        mpv_ox, mpv_oy = 0, 0
    osd_target_x = raw_target_x - mpv_ox
    osd_target_y = raw_target_y - mpv_oy

    lerp_factor = 0.15  # Adjust this value: lower = smoother/slower, higher = faster
    new_x = current_x + (osd_target_x - current_x) * lerp_factor
    new_y = current_y + (osd_target_y - current_y) * lerp_factor

    # Update position
    grow_overlay.grow_position = (int(new_x), int(new_y))
    _main.toggle_grow_overlay(block_percent=grow_overlay.last_grow_block_percent, position=grow_overlay.grow_position)

    distance = ((osd_target_x - new_x) ** 2 + (osd_target_y - new_y) ** 2) ** 0.5
    if mouse_dragging_grow_overlay and distance > 2:  # Stop when very close
        animation_after_id = _main.root.after(16, smooth_move_grow_overlay)  # ~60 FPS
    else:
        animation_after_id = None


def on_mouse_click(x, y, button, pressed):
    """Handle mouse click events."""
    global mouse_left_pressed, mouse_dragging_grow_overlay, mouse_dragging_zoom_filter, target_mouse_position, animation_after_id

    if pressed:
        if button == mouse.Button.left:
            mouse_left_pressed = True
            if grow_overlay.grow_overlay_boxes:
                mx, my, mw, mh = _main._get_mpv_window_rect()
                if mx <= x < mx + mw and my <= y < my + mh:
                    mouse_dragging_grow_overlay = True
                    target_mouse_position = (x, y)
                    if animation_after_id is None:
                        smooth_move_grow_overlay()
            elif filter_overlay.filter_vf_active and filter_overlay._filter_vf_variant == 'zoom':
                mx, my, mw, mh = _main._get_mpv_window_rect()
                if mx <= x < mx + mw and my <= y < my + mh:
                    mouse_dragging_zoom_filter = True
                    target_mouse_position = (x, y)
                    if zoom_filter_animation_after_id is None:
                        smooth_move_zoom_filter_overlay()

        elif button == mouse.Button.right:
            _main.widen_peek()
    else:
        if button == mouse.Button.left:
            mouse_left_pressed = False
            mouse_dragging_grow_overlay = False
            mouse_dragging_zoom_filter = False
            target_mouse_position = None
            # Cancel animation
            if animation_after_id:
                _main.root.after_cancel(animation_after_id)
                animation_after_id = None
            if _main.last_seek_time:
                seek_time = int(float(_main.last_seek_time)) * 1000
                _main.seek_to(seek_time)
                _main.last_seek_time = None
                def clear_last_seek_time():
                    _main.last_seek_time = None
                _main.root.after(100, clear_last_seek_time)
        # Add your mouse release handling logic here


def on_mouse_move(x, y):
    """Handle mouse move events - set target position for smooth animation."""
    global target_mouse_position

    # If left mouse is pressed and we're dragging the grow overlay
    if mouse_dragging_grow_overlay and mouse_left_pressed:
        mx, my, mw, mh = _main._get_mpv_window_rect()
        if mx <= x < mx + mw and my <= y < my + mh:
            target_mouse_position = (x, y)
            if animation_after_id is None:
                smooth_move_grow_overlay()
    elif mouse_dragging_zoom_filter and mouse_left_pressed:
        mx, my, mw, mh = _main._get_mpv_window_rect()
        if mx <= x < mx + mw and my <= y < my + mh:
            target_mouse_position = (x, y)
            if zoom_filter_animation_after_id is None:
                smooth_move_zoom_filter_overlay()


def on_mouse_scroll(x, y, dx, dy):
    """Handle mouse scroll events."""
    # Add your scroll handling logic here
