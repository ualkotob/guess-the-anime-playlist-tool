"""Metadata package import (URL or local zip).

Extracted from `guess_the_anime.py` to keep the main file lean. Call
:func:`set_context` once at startup to inject the small set of main-file
helpers / shared state this module needs, then call
:func:`import_data_from_package` exactly as before.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import threading
import time
import tkinter as tk
import zipfile
from tkinter import messagebox

import requests


# ---------------------------------------------------------------------------
# Injected dependencies (populated by set_context)
# ---------------------------------------------------------------------------
get_window_position_and_setup = None
save_metadata = None
load_metadata = None
scan_directory = None
show_playlist = None
save_config = None

# Metadata dicts — by-reference, mutated in-place via .update()/[]= assignment
file_metadata = None
file_metadata_overrides = None
anime_metadata = None
anidb_metadata = None
ai_metadata = None
anilist_metadata = None

# main module's globals() — needed for reads/writes against vars that get
# reassigned in main (list_loaded, metadata_last_updated)
main_globals = {}


def set_context(*, get_window_position_and_setup,
                save_metadata, load_metadata, scan_directory, show_playlist,
                save_config,
                file_metadata, file_metadata_overrides,
                anime_metadata, anidb_metadata, ai_metadata, anilist_metadata,
                main_globals):
    g = globals()
    g['get_window_position_and_setup'] = get_window_position_and_setup
    g['save_metadata'] = save_metadata
    g['load_metadata'] = load_metadata
    g['scan_directory'] = scan_directory
    g['show_playlist'] = show_playlist
    g['save_config'] = save_config
    g['file_metadata'] = file_metadata
    g['file_metadata_overrides'] = file_metadata_overrides
    g['anime_metadata'] = anime_metadata
    g['anidb_metadata'] = anidb_metadata
    g['ai_metadata'] = ai_metadata
    g['anilist_metadata'] = anilist_metadata
    g['main_globals'] = main_globals


def import_data_from_package(source, is_local=False, prompt=True):
    """Import metadata from a package (URL or local file)."""
    # Ask for confirmation
    source_text = f"local file:\n{source}" if is_local else f"remote source:\n{source}"
    delete_text = "\n\nNote: The local file will be deleted after successful import." if is_local else ""

    if prompt:
        confirm = messagebox.askyesno(
            "Import Metadata Package",
            f"This will download and merge metadata from {source_text}\n\n"
            f"All metadata files (anime, anidb, ai, anilist) will be merged with your existing data.{delete_text}\n\n"
            "Continue?"
        )

        if not confirm:
            return

    import_window = tk.Toplevel()
    import_window.title("Importing...")
    import_window.configure(bg="black")
    import_window.geometry("400x150")
    get_window_position_and_setup(import_window, offset_x=200, offset_y=200)

    # Status label
    status_label = tk.Label(import_window, text="Starting import...",
                           font=("Arial", 12), bg="black", fg="yellow")
    status_label.pack(pady=40)

    def do_import():
        """Perform the actual import operation."""

        imported_items = []
        errors = []
        temp_dir = None
        package_deleted = False

        try:
            # Get the zip package (download or use local file)
            if is_local:
                if not import_window.winfo_exists():
                    return
                status_label.config(text="Loading local package...", fg="yellow")
                import_window.update()
                zip_path = os.path.abspath(source)
                if not os.path.exists(zip_path):
                    raise FileNotFoundError(f"Local package not found: {zip_path}")
                temp_dir = tempfile.mkdtemp()
            else:
                if not import_window.winfo_exists():
                    return
                status_label.config(text="Downloading package...", fg="yellow")
                import_window.update()
                response = requests.get(source, timeout=60)
                response.raise_for_status()
                temp_dir = tempfile.mkdtemp()
                zip_path = os.path.join(temp_dir, "metadata_package.zip")
                with open(zip_path, 'wb') as f:
                    f.write(response.content)

            if not import_window.winfo_exists():
                return
            status_label.config(text="Extracting package...")
            import_window.update()

            # Extract the zip
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(temp_dir)

            # Import metadata files
            metadata_files = [
                ('metadata/file_metadata.json', 'file_metadata', lambda d: file_metadata),
                ('metadata/file_metadata_overrides.json', 'file_metadata_overrides', lambda d: file_metadata_overrides),
                ('metadata/anime_metadata.json', 'anime_metadata', lambda d: anime_metadata),
                ('metadata/anidb_metadata.json', 'anidb_metadata', lambda d: anidb_metadata),
                ('metadata/ai_metadata.json', 'ai_metadata', lambda d: ai_metadata),
                ('metadata/anilist_metadata.json', 'anilist_metadata', lambda d: anilist_metadata),
            ]

            for file_path, name, get_dict in metadata_files:
                try:
                    if not import_window.winfo_exists():
                        return
                    status_label.config(text=f"Importing {name}...")
                    import_window.update()

                    # Check for .gz version first
                    full_path = os.path.join(temp_dir, file_path)
                    gz_path = full_path + '.gz'

                    if os.path.exists(gz_path):
                        with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
                            imported_data = json.load(f)
                    elif os.path.exists(full_path):
                        with open(full_path, 'r', encoding='utf-8') as f:
                            imported_data = json.load(f)
                    else:
                        continue  # File not in package, skip

                    # Merge with existing data
                    current_dict = get_dict(None)
                    count = 0
                    for key, value in imported_data.items():
                        if key not in current_dict:
                            count += 1
                        current_dict[key] = value

                    # Update the global variable based on which file it is
                    if name == 'file_metadata':
                        file_metadata.update(imported_data)
                    elif name == 'file_metadata_overrides':
                        file_metadata_overrides.update(imported_data)
                    elif name == 'anime_metadata':
                        anime_metadata.update(imported_data)
                    elif name == 'anidb_metadata':
                        anidb_metadata.update(imported_data)
                    elif name == 'ai_metadata':
                        ai_metadata.update(imported_data)
                    elif name == 'anilist_metadata':
                        anilist_metadata.update(imported_data)

                    imported_items.append(f"{name}: {len(imported_data)} entries ({count} new)")

                except Exception as e:
                    errors.append(f"Failed to import {name}: {e}")

            # Save all metadata
            if imported_items:
                save_metadata()
                # Reload metadata and refresh directory to show imported data
                load_metadata()
                scan_directory()
                if main_globals.get('list_loaded') == "playlist":
                    show_playlist(True)

        except requests.exceptions.RequestException as e:
            errors.append(f"Failed to download package: {e}")
        except zipfile.BadZipFile:
            errors.append("Invalid zip file")
        except Exception as e:
            errors.append(f"Error during import: {e}")
        finally:
            # Clean up temp directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass

        # Show results
        if imported_items and not errors:
            # Delete local package if import was successful
            if is_local and not package_deleted:
                try:
                    os.remove(source)
                    package_deleted = True
                    print(f"Deleted local metadata package: {source}")
                except Exception as e:
                    print(f"Could not delete local package: {e}")

            if import_window.winfo_exists():
                status_label.config(text="Import completed successfully!", fg="green")
            result_msg = "Successfully imported:\n\n" + "\n".join(imported_items)
            if is_local and package_deleted:
                result_msg += "\n\nLocal package has been deleted."
            if import_window.winfo_exists():
                import_window.destroy()

            # Update metadata timestamp after successful import
            if is_local:
                # For local imports, use current time
                main_globals['metadata_last_updated'] = int(time.time())
            else:
                # For remote imports, use Last-Modified from the response we already have
                try:
                    last_modified = response.headers.get('Last-Modified')
                    if last_modified:
                        from email.utils import parsedate_to_datetime
                        main_globals['metadata_last_updated'] = int(parsedate_to_datetime(last_modified).timestamp())
                    else:
                        main_globals['metadata_last_updated'] = int(time.time())
                except:
                    main_globals['metadata_last_updated'] = int(time.time())
            save_config()
        elif errors:
            if import_window.winfo_exists():
                status_label.config(text="Import completed with errors", fg="red")
            error_msg = "Import completed with the following errors:\n\n" + "\n\n".join(errors)
            if imported_items:
                error_msg += "\n\nSuccessfully imported:\n" + "\n".join(imported_items)
            messagebox.showerror("Import Errors", error_msg)
        else:
            if import_window.winfo_exists():
                status_label.config(text="Ready", fg="white")

    # Start import in thread to keep UI responsive
    import_thread = threading.Thread(target=do_import, daemon=True)
    import_thread.start()
