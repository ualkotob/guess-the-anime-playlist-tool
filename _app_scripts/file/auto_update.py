"""Auto-update functionality.

Reads the app version + GitHub repo from core.app_meta, the root window from
state.widgets, and window positioning from windowing.
"""

import os
import re
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

import requests

from core.app_meta import APP_VERSION, GITHUB_REPO
from core.game_state import state
import _app_scripts.ui.windowing as windowing


def _setup_window(window, offset_x=0, offset_y=0):
    """Position *window* relative to the root window."""
    windowing.get_window_position_and_setup(window, offset_x=offset_x, offset_y=offset_y)


# ---------------------------------------------------------------------------
# Core update logic
# ---------------------------------------------------------------------------

def check_for_updates():
    """Check GitHub releases for newer version."""
    try:
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(api_url, timeout=10)

        if response.status_code == 200:
            release_data = response.json()
            latest_version = release_data.get("tag_name", "").lstrip("v")  # Remove 'v' prefix if present

            if compare_versions(latest_version, APP_VERSION):
                return {
                    "update_available": True,
                    "latest_version": latest_version,
                    "current_version": APP_VERSION,
                    "release_data": release_data
                }
            else:
                return {
                    "update_available": False,
                    "latest_version": latest_version,
                    "current_version": APP_VERSION
                }
        else:
            return {"error": f"Failed to check for updates: HTTP {response.status_code}"}

    except requests.exceptions.RequestException as e:
        return {"error": f"Network error checking for updates: {str(e)}"}
    except Exception as e:
        return {"error": f"Error checking for updates: {str(e)}"}


def compare_versions(version1, version2):
    """Compare two version strings. Returns True if version1 > version2."""
    try:
        def version_tuple(v):
            return tuple(map(int, (v.split("."))))
        return version_tuple(version1) > version_tuple(version2)
    except Exception:
        return False


def cleanup_old_update_exes():
    """Delete any versioned update exes left over from a previous update (e.g. guess_the_anime_v19.2.exe)."""
    if not getattr(sys, 'frozen', False):
        return
    try:
        exe_dir = os.path.dirname(sys.executable)
        current_name = os.path.basename(sys.executable)
        for fname in os.listdir(exe_dir):
            if fname == current_name:
                continue
            if re.match(r'guess_the_anime_v[\d.]+\.exe$', fname, re.IGNORECASE):
                try:
                    os.remove(os.path.join(exe_dir, fname))
                    print(f"Cleaned up old update exe: {fname}")
                except Exception as e:
                    print(f"Could not remove old update exe {fname}: {e}")
    except Exception as e:
        print(f"cleanup_old_update_exes error: {e}")


def cleanup_updater_files():
    """Remove leftover updater.exe / updater.log files from previous updates.

    Paths are relative to the cwd, which main sets to the app root at startup.
    """
    files_to_clean = ["updater.exe", "updater.log"]
    for filename in files_to_clean:
        if os.path.exists(filename):
            try:
                os.remove(filename)
                print(f"Cleaned up: {filename}")
            except Exception as e:
                print(f"Could not clean up {filename}: {e}")


def _download_update(update_info):
    """Download the new exe from GitHub releases and exit, prompting user to run it.

    Called on the main thread after user confirms. Shows a progress window,
    downloads in a background thread, then closes the app.
    """
    release_data = update_info.get("release_data", {})
    latest_version = update_info["latest_version"]

    # Find the exe asset in the release
    asset_url = None
    for asset in release_data.get("assets", []):
        if asset.get("name", "").lower() == "guess_the_anime.exe":
            asset_url = asset["browser_download_url"]
            break

    if not asset_url:
        messagebox.showerror("Update Failed",
                             "Could not find guess_the_anime.exe in the latest release.\n"
                             "Please download it manually from the GitHub releases page.")
        open_github_releases()
        return

    exe_dir = os.path.dirname(sys.executable)
    new_exe_name = f"guess_the_anime_v{latest_version}.exe"
    new_exe_path = os.path.join(exe_dir, new_exe_name)

    # Progress window
    prog_win = tk.Toplevel()
    prog_win.title("Downloading Update...")
    prog_win.geometry("380x110")
    prog_win.configure(bg="black")
    prog_win.resizable(False, False)
    prog_win.transient(state.widgets.root)
    prog_win.grab_set()
    _setup_window(prog_win, offset_x=100, offset_y=100)

    tk.Label(prog_win, text=f"Downloading version {latest_version}...",
             bg="black", fg="white", font=("Arial", 11)).pack(pady=(16, 4))
    prog_var = tk.DoubleVar()
    prog_bar = ttk.Progressbar(prog_win, variable=prog_var, maximum=100, length=320)
    prog_bar.pack(pady=4)
    pct_label = tk.Label(prog_win, text="0%", bg="black", fg="#aaaaaa", font=("Arial", 9))
    pct_label.pack()
    prog_win.update()

    download_error = [None]

    def do_download():
        try:
            response = requests.get(asset_url, stream=True, timeout=60)
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            with open(new_exe_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded / total * 100
                            prog_win.after(0, lambda p=pct: (prog_var.set(p),
                                                              pct_label.config(text=f"{p:.0f}%")))
        except Exception as e:
            download_error[0] = str(e)
        finally:
            prog_win.after(0, on_download_done)

    def on_download_done():
        try:
            prog_win.destroy()
        except Exception:
            pass

        if download_error[0]:
            # Clean up partial file
            try:
                os.remove(new_exe_path)
            except Exception:
                pass
            messagebox.showerror("Download Failed",
                                 f"Could not download the update:\n{download_error[0]}\n\n"
                                 "Please download it manually from the GitHub releases page.")
            open_github_releases()
            return

        messagebox.showinfo("Update Ready",
                            f"Version {latest_version} has been downloaded as:\n"
                            f"  {new_exe_name}\n\n"
                            f"Please close this window and run {new_exe_name} to complete the update.\n"
                            f"The old exe will be removed automatically on first launch.")
        state.widgets.root.destroy()

    threading.Thread(target=do_download, daemon=True).start()


def _show_update_dialog(update_info):
    """Show the update-available dialog and handle the user's choice."""
    release_data = update_info.get("release_data", {})
    release_body = release_data.get("body", "No release notes available.")
    is_frozen = getattr(sys, 'frozen', False)

    if is_frozen:
        prompt = "Would you like to download the update? The app will close when the download is complete."
    else:
        prompt = "Would you like to open the GitHub releases page to download it?"

    result = messagebox.askyesno("Update Available",
                                 f"New version available!\n\n"
                                 f"Current version: {update_info['current_version']}\n"
                                 f"Latest version: {update_info['latest_version']}\n\n"
                                 f"Release Notes:\n{release_body[:300]}{'...' if len(release_body) > 300 else ''}\n\n"
                                 + prompt)
    if result:
        if is_frozen:
            _download_update(update_info)
        else:
            open_github_releases()




def open_github_releases():
    """Open the GitHub releases page in the default browser."""
    try:
        releases_url = f"https://github.com/{GITHUB_REPO}/releases"
        webbrowser.open(releases_url)
    except Exception:
        releases_url = f"https://github.com/{GITHUB_REPO}/releases"
        messagebox.showerror("Browser Error",
                             f"Could not open browser automatically.\n\n"
                             f"Please manually visit:\n{releases_url}")


def check_for_updates_on_startup():
    """Check for updates on startup in a background thread to avoid blocking UI."""
    def background_check():
        try:
            update_info = check_for_updates()

            if update_info.get("error"):
                print(f"Update check failed: {update_info['error']}")
                return

            if update_info.get("update_available"):
                state.widgets.root.after(0, lambda: _show_update_dialog(update_info))

        except Exception as e:
            print(f"Startup update check failed: {str(e)}")

    threading.Thread(target=background_check, daemon=True).start()
