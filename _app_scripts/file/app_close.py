"""Application close/teardown.

`on_app_close()` is the single app-shutdown entry point, reached both from the
root window's WM_DELETE_WINDOW protocol (wired in _main) and the menu registry's
EXIT button. It reads every collaborator off `state` / sibling modules directly.
"""

import threading
import tkinter as tk
from tkinter import ttk

from core.game_state import state
import _app_scripts.ui.menu_builder as menu_builder
import _app_scripts.data.config_io as config_io
import _app_scripts.data.metadata_io as metadata_io
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.file.web_server.web_server as web_server


_closing = False   # reentrancy guard
_SAVE_TIMEOUT_MS = 15000   # force-close even if the flush overruns (atomic writes → safe)


def _show_closing_popup(root):
    """Borderless 'saving & closing' splash with an indeterminate moving bar,
    centered over the root window (falling back to the screen if root isn't
    mapped). A real Tk Toplevel — not an mpv OSD — so it shows on the control
    window / main screen; the bar animates because the heavy metadata flush
    runs on a background thread (this event loop stays free). Returns
    (popup, bar) or (None, None)."""
    try:
        popup = tk.Toplevel(root)
        popup.overrideredirect(True)
        popup.configure(bg="#1e1e1e", highlightthickness=1, highlightbackground="#444")
        popup.attributes("-topmost", True)
        tk.Label(
            popup, text="Saving data & closing…",
            bg="#1e1e1e", fg="white", font=("Segoe UI", 14),
        ).pack(padx=48, pady=(26, 14))
        try:
            style = ttk.Style(popup)
            style.configure("Closing.Horizontal.TProgressbar",
                            troughcolor="#2a2a2a", background="#4aa3ff",
                            borderwidth=0, thickness=10)
            bar = ttk.Progressbar(popup, mode="indeterminate", length=320,
                                  style="Closing.Horizontal.TProgressbar")
        except Exception:
            bar = ttk.Progressbar(popup, mode="indeterminate", length=320)
        bar.pack(padx=48, pady=(0, 28))
        bar.start(15)   # animate the moving block every 15ms
        popup.update_idletasks()
        pw, ph = popup.winfo_reqwidth(), popup.winfo_reqheight()
        try:
            if root.winfo_ismapped() and root.winfo_width() > 1:
                x = root.winfo_rootx() + (root.winfo_width() - pw) // 2
                y = root.winfo_rooty() + (root.winfo_height() - ph) // 2
            else:
                raise RuntimeError("root not mapped")
        except Exception:
            x = (root.winfo_screenwidth() - pw) // 2
            y = (root.winfo_screenheight() - ph) // 2
        popup.geometry(f"{pw}x{ph}+{x}+{y}")
        try:
            popup.update()      # map + paint now so it's visible before save_config()
            popup.grab_set()    # modal: swallow stray clicks on the closing UI
        except Exception:
            pass
        return popup, bar
    except Exception:
        return None, None


def _teardown(root, popup):
    """quit() the mainloop then destroy widgets — the single close path."""
    if state.config.AUTO_EXIT_SCOREBOARD and scoreboard_control.is_running():
        try:
            scoreboard_control.send_command("quit")
        except Exception:
            pass
    try:
        if popup is not None:
            popup.destroy()
    except Exception:
        pass
    try:
        root.quit()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def on_app_close():
    """Safely destroy hidden root-parented widgets before closing to avoid TclError."""
    global _closing
    if _closing:
        return
    _closing = True
    root = state.widgets.root
    # Cancel any pending tooltip after() callback so it can't fire on a destroyed widget
    menu_builder.dismiss_menu_tooltip()

    widget = state.playlist_ui.difficulty_dropdown
    if widget is not None:
        try:
            widget.unbind_all("<<ComboboxSelected>>")
            widget.destroy()
        except Exception:
            pass
    try:
        web_server.stop()
    except Exception:
        pass

    popup, _bar = _show_closing_popup(root)

    # save_config() touches Tk widgets (update_current_index → button/list), so
    # it must run on this (main) thread; it's small. The metadata flush is the
    # multi-second part and is pure file I/O, so it runs on a worker while the
    # splash bar keeps animating on the event loop below.
    try:
        config_io.save_config()
    except Exception:
        pass

    done = threading.Event()

    def _flush_worker():
        try:
            metadata_io.flush_pending_metadata_save()
        except Exception:
            pass
        finally:
            done.set()

    threading.Thread(target=_flush_worker, name="app-close-flush", daemon=True).start()

    # Poll on the Tk loop so the bar animates; close when the flush finishes or
    # the safety timeout elapses.
    if root is not None:
        deadline = [_SAVE_TIMEOUT_MS // 50]

        def _wait_for_flush():
            deadline[0] -= 1
            if done.is_set() or deadline[0] <= 0:
                _teardown(root, popup)
                return
            try:
                root.after(50, _wait_for_flush)
            except Exception:
                _teardown(root, popup)

        try:
            root.after(50, _wait_for_flush)
            return
        except Exception:
            pass
    # No usable event loop — flush synchronously and tear down.
    done.wait(_SAVE_TIMEOUT_MS / 1000.0)
    _teardown(root, popup)
