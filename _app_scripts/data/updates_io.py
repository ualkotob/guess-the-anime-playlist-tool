"""Remote metadata + censor update checks, import, and export.

Houses the GitHub-Releases-backed update flow:
  - check_for_metadata_updates / check_for_censor_updates  (HEAD checks)
  - import_data_from_source                                (kick remote import)
  - check_for_local_metadata_package                       (prompt for local zip)
  - export_metadata_package                                (write zip + open folder)
  - import_censors                                         (download + replace)
  - download_scoreboard                                    (thin scoreboard kickoff)

Remote update timestamps live in ``state.update_timestamps`` and are persisted
by config_io.
"""
import os
import json
import time
import platform
import threading
import zipfile

import requests
import tkinter as tk
from tkinter import messagebox, filedialog

from _app_scripts import utils
from _app_scripts.file.metadata import metadata_import
from _app_scripts.file import scoreboard_control
from _app_scripts.toggles import censors
from _app_scripts.data import config_io
from _app_scripts.ui import windowing, menu_builder
from core.paths import (
    CENSORS_FOLDER,
    FILE_METADATA_FILE,
    FILE_METADATA_OVERRIDES_FILE,
    ANIME_METADATA_FILE,
    ANIME_METADATA_OVERRIDES_FILE,
    ANIDB_METADATA_FILE,
    AI_METADATA_FILE,
    ANILIST_METADATA_FILE,
)
from core.game_state import state


# Import data package URL - modify this to point to your exported metadata package
IMPORT_PACKAGE_URL    = "https://github.com/ualkotob/guess-the-anime-playlist-tool/releases/download/data-latest/metadata_package.zip"
IMPORT_CENSORS_URL    = "https://github.com/ualkotob/guess-the-anime-playlist-tool/releases/download/data-latest/ramuns_censors.json"
LOCAL_METADATA_PACKAGE = "metadata/metadata_package.zip"

import_data_from_package = metadata_import.import_data_from_package


def check_for_metadata_updates():
    """Check if newer metadata is available on GitHub and prompt user to download."""
    try:
        # Do a HEAD request to get Last-Modified header without downloading
        response = requests.head(IMPORT_PACKAGE_URL, timeout=5, allow_redirects=True)
        if response.status_code == 200:
            last_modified = response.headers.get('Last-Modified')
            if last_modified:
                # Parse Last-Modified to Unix timestamp
                from email.utils import parsedate_to_datetime
                remote_timestamp = int(parsedate_to_datetime(last_modified).timestamp())

                # Only prompt if remote is newer than local
                if remote_timestamp > state.update_timestamps.metadata_last_updated:
                    # Format date for display
                    from datetime import datetime
                    date_str = datetime.fromtimestamp(remote_timestamp).strftime('%Y-%m-%d')
                    result = messagebox.askyesno(
                        "Metadata Update Available",
                        f"New metadata is available (updated {date_str}).\n\n"
                        f"Would you like to download and import it now?\n\n"
                        f"This will merge the latest data with your existing metadata."
                    )
                    if result:
                        import_data_from_source(prompt=False)
                    else:
                        # User declined - update timestamp so they don't get asked again until next update
                        state.update_timestamps.metadata_last_updated = remote_timestamp
                        config_io.save_config()
    except Exception as e:
        # Silently fail - don't bother user if check fails
        print(f"Could not check for metadata updates: {e}")


def check_for_censor_updates():
    """Check if newer censors are available on GitHub and prompt user to download."""
    # Check if ramuns_censors.json doesn't exist AND last_updated is not 0
    # If both conditions are true, skip the check (no file and never checked before)
    ramuns_censors_file = os.path.join(CENSORS_FOLDER, "ramuns_censors.json")
    if not os.path.exists(ramuns_censors_file) and state.update_timestamps.censors_last_updated != 0:
        return

    try:
        # Do a HEAD request to get Last-Modified header without downloading
        response = requests.head(IMPORT_CENSORS_URL, timeout=5, allow_redirects=True)
        if response.status_code == 200:
            last_modified = response.headers.get('Last-Modified')
            if last_modified:
                # Parse Last-Modified to Unix timestamp
                from email.utils import parsedate_to_datetime
                remote_timestamp = int(parsedate_to_datetime(last_modified).timestamp())

                # Only prompt if remote is newer than local
                if remote_timestamp > state.update_timestamps.censors_last_updated:
                    # Format date for display
                    from datetime import datetime
                    date_str = datetime.fromtimestamp(remote_timestamp).strftime('%Y-%m-%d')
                    result = messagebox.askyesno(
                        "Censor Update Available",
                        f"New censors are available (updated {date_str}).\n\n"
                        f"Would you like to download and import them now?\n\n"
                        f"This will save as 'ramuns_censors.json' in your files folder."
                    )
                    if result:
                        import_censors(prompt=False)
                    else:
                        # User declined - update timestamp so they don't get asked again until next update
                        state.update_timestamps.censors_last_updated = remote_timestamp
                        config_io.save_config()
    except Exception as e:
        # Silently fail - don't bother user if check fails
        print(f"Could not check for censor updates: {e}")


# ── Universal Scoreboard integration — see _app_scripts/scoreboard_control.py ─

def download_scoreboard():
    scoreboard_control.download_scoreboard(
        state.widgets.root,
        state.colors.HIGHLIGHT_COLOR,
        windowing.get_window_position_and_setup,
        config_io.save_config,
        menu_builder.create_first_row_buttons,
    )


def check_for_local_metadata_package():
    """Check if metadata package exists locally and prompt user to import it."""
    if os.path.exists(LOCAL_METADATA_PACKAGE):
        response = messagebox.askyesno(
            "Metadata Package Found",
            f"Found metadata package in:\n{LOCAL_METADATA_PACKAGE}\n\n"
            "Would you like to import and merge this metadata now?\n\n"
            "Note: The package will be deleted after successful import."
        )

        if response:
            import_data_from_package(LOCAL_METADATA_PACKAGE, is_local=True, prompt=False)


def export_metadata_package():
    """Export all metadata files into a consolidated zip package."""
    try:
        # Ask where to save the package
        export_path = filedialog.asksaveasfilename(
            title="Export Metadata Package",
            defaultextension=".zip",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            initialfile="metadata_package.zip"
        )

        if not export_path:
            return  # User cancelled

        # List of files to include in package
        files_to_export = [
            (FILE_METADATA_FILE, "metadata/file_metadata.json"),
            (FILE_METADATA_OVERRIDES_FILE, "metadata/file_metadata_overrides.json"),
            (ANIME_METADATA_FILE, "metadata/anime_metadata.json"),
            (ANIDB_METADATA_FILE, "metadata/anidb_metadata.json"),
            (AI_METADATA_FILE, "metadata/ai_metadata.json"),
            (ANILIST_METADATA_FILE, "metadata/anilist_metadata.json"),
            (ANIME_METADATA_OVERRIDES_FILE, "metadata/anime_metadata_overrides.json"),
        ]
        # anime_metadata_overrides is always plain JSON — separate it out
        plain_json_files = [(ANIME_METADATA_OVERRIDES_FILE, "metadata/anime_metadata_overrides.json")]
        compressed_files = files_to_export[:-1]  # all except overrides

        # Check for .gz versions first
        files_found = []
        files_missing = []

        for source_file, zip_path in compressed_files:
            if os.path.exists(source_file + '.gz'):
                files_found.append((source_file + '.gz', zip_path + '.gz'))
            elif os.path.exists(source_file):
                files_found.append((source_file, zip_path))
            else:
                files_missing.append(source_file)

        for source_file, zip_path in plain_json_files:
            if os.path.exists(source_file):
                files_found.append((source_file, zip_path))
            else:
                files_missing.append(source_file)

        if not files_found:
            messagebox.showerror("Export Error", "No metadata files found to export!")
            return

        # Create the zip package
        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for source_file, zip_path in files_found:
                zipf.write(source_file, zip_path)

        # Show success message
        message = f"Successfully exported {len(files_found)} file(s) to:\n{export_path}"
        if files_missing:
            message += f"\n\nNote: {len(files_missing)} file(s) were not found and skipped."

        messagebox.showinfo("Export Complete", message)

        # Open the folder containing the export
        folder = os.path.dirname(export_path)
        if platform.system() == "Windows":
            os.startfile(folder)

    except Exception as e:
        messagebox.showerror("Export Error", f"Failed to export metadata package:\n\n{e}")


def import_censors(prompt=True):
    """Import censors from remote source and replace existing file."""
    # Ask for confirmation
    if prompt:
        confirm = messagebox.askyesno(
            "Import Ramun's Censors",
            f"This will download the latest censors from:\n{IMPORT_CENSORS_URL}\n\n"
            f"This will be saved as 'ramuns_censors.json' in your files folder.\n\n"
            "Continue?"
        )

        if not confirm:
            return

    import_window = tk.Toplevel()
    import_window.title("Importing Censors...")
    import_window.configure(bg="black")
    import_window.geometry("400x150")
    windowing.get_window_position_and_setup(import_window, offset_x=200, offset_y=200)

    # Status label
    status_label = tk.Label(import_window, text="Downloading censors...",
                           font=("Arial", 12), bg="black", fg="yellow")
    status_label.pack(pady=40)

    def do_import():
        """Perform the actual import operation."""
        try:
            if not import_window.winfo_exists():
                return
            status_label.config(text="Downloading censors...", fg="yellow")
            import_window.update()

            response = requests.get(IMPORT_CENSORS_URL, timeout=60)
            response.raise_for_status()

            if not import_window.winfo_exists():
                return
            status_label.config(text="Saving censors...", fg="yellow")
            import_window.update()

            # Parse the downloaded JSON
            new_censors = response.json()

            # Ensure the files folder exists
            ramuns_censors_file = os.path.join(CENSORS_FOLDER, "ramuns_censors.json")
            folder = os.path.dirname(ramuns_censors_file)
            if not os.path.exists(folder):
                os.makedirs(folder)

            # Replace the existing file
            utils._atomic_json_write(ramuns_censors_file, new_censors, indent=4)

            # Update the global censor_list
            censors.other_censor_lists.append(new_censors)

            if not import_window.winfo_exists():
                return
            status_label.config(text="Complete!", fg="green")
            import_window.update()

            # Update timestamp
            try:
                last_modified = response.headers.get('Last-Modified')
                if last_modified:
                    from email.utils import parsedate_to_datetime
                    state.update_timestamps.censors_last_updated = int(parsedate_to_datetime(last_modified).timestamp())
                else:
                    state.update_timestamps.censors_last_updated = int(time.time())
            except Exception:
                state.update_timestamps.censors_last_updated = int(time.time())
            config_io.save_config()

            print(f"Imported {len(new_censors)} censors from ramuns_censors.json.")
            if import_window.winfo_exists():
                import_window.destroy()
            censors.update_censor_button_count()

        except requests.exceptions.RequestException as e:
            if import_window.winfo_exists():
                status_label.config(text="Download failed!", fg="red")
            messagebox.showerror("Download Error", f"Failed to download censors:\n\n{e}")
        except json.JSONDecodeError as e:
            if import_window.winfo_exists():
                status_label.config(text="Invalid JSON!", fg="red")
            messagebox.showerror("Parse Error", f"Downloaded file is not valid JSON:\n\n{e}")
        except Exception as e:
            if import_window.winfo_exists():
                status_label.config(text="Import failed!", fg="red")
            messagebox.showerror("Import Error", f"Failed to import censors:\n\n{e}")

    # Start import in a thread
    thread = threading.Thread(target=do_import, daemon=True)
    thread.start()


def import_data_from_source(prompt=True):
    """Import metadata from remote package."""
    import_data_from_package(IMPORT_PACKAGE_URL, is_local=False, prompt=prompt)
