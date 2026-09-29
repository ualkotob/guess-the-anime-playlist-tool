"""Metadata package import (URL or local zip).

Extracted from `guess_the_anime.py` to keep the main file lean. Reads shared
metadata dicts from `state.metadata` and reaches sibling modules directly;
call :func:`import_data_from_package` exactly as before.
"""
from __future__ import annotations
from core.game_state import state

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

from _app_scripts import utils
import _app_scripts.ui.windowing as windowing
import _app_scripts.data.config_io as config_io
import _app_scripts.data.metadata_io as metadata_io
import _app_scripts.ui.lists as lists
import _app_scripts.directory.scan as directory_scan


METADATA_PACKAGE_FILES = (
    ('metadata/file_metadata.json', 'file_metadata'),
    ('metadata/file_metadata_overrides.json', 'file_metadata_overrides'),
    ('metadata/anime_metadata.json', 'anime_metadata'),
    ('metadata/anime_metadata_overrides.json', 'anime_metadata_overrides'),
    ('metadata/animethemes_metadata.json', 'animethemes_metadata'),
    ('metadata/anisongdb_metadata.json', 'anisongdb_metadata'),
    ('metadata/anidb_metadata.json', 'anidb_metadata'),
    ('metadata/ai_metadata.json', 'ai_metadata'),
    ('metadata/anilist_metadata.json', 'anilist_metadata'),
)


def _merge_package_entries(current_dict, imported_data):
    """Merge one package store with package entries taking precedence.

    Metadata packages are release snapshots: an entry present in the package
    must replace the same local entry, while entries that exist only locally
    are retained.
    """
    new_count = sum(key not in current_dict for key in imported_data)
    current_dict.update(imported_data)
    return new_count


def _persist_imported_metadata():
    """Persist an import before reloading it from disk.

    This must be synchronous.  A debounced save followed by ``load_metadata``
    reloads the old files and discards the freshly imported in-memory data.
    """
    if state.metadata.animethemes_metadata:
        from _app_scripts.theme import animethemes

        animethemes.build_indexes(force=True)
        animethemes.sync_catalog_to_metadata()
    if state.metadata.anisongdb_metadata:
        from _app_scripts.theme import anisongdb

        anisongdb.build_indexes(force=True)
        anisongdb.sync_catalog_to_metadata()
    metadata_io.save_animethemes_metadata()
    metadata_io.save_anisongdb_metadata()
    metadata_io.save_metadata(immediate=True)
    metadata_io.load_metadata()


def _merge_package_store(name, imported_data):
    """Apply a package store without changing the user's override stores."""
    if name.endswith("_overrides"):
        # Overrides in an exported package are publisher corrections. Fold
        # them into the release data; load_metadata() will subsequently apply
        # this user's own override files at the highest precedence.
        base_name = name.removesuffix("_overrides")
        current_dict = getattr(state.metadata, base_name)
        new_count = sum(key not in current_dict for key in imported_data)
        utils.deep_merge(current_dict, imported_data)
        return new_count

    current_dict = getattr(state.metadata, name)
    return _merge_package_entries(current_dict, imported_data)


def import_data_from_package(source, is_local=False, prompt=True):
    """Import metadata from a package (URL or local file)."""
    # Ask for confirmation
    source_text = f"local file:\n{source}" if is_local else f"remote source:\n{source}"
    delete_text = "\n\nNote: The local file will be deleted after successful import." if is_local else ""

    if prompt:
        confirm = messagebox.askyesno(
            "Import Metadata Package",
            f"This will download and merge metadata from {source_text}\n\n"
            f"All metadata files (anime, AniSongDB, AniDB, AI, AniList) will be merged with your existing data.{delete_text}\n\n"
            "Continue?"
        )

        if not confirm:
            return

    import_window = tk.Toplevel()
    import_window.title("Importing...")
    import_window.configure(bg="black")
    import_window.geometry("400x150")
    windowing.get_window_position_and_setup(import_window, offset_x=200, offset_y=200)

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
            for file_path, name in METADATA_PACKAGE_FILES:
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

                    # Merge with existing data. Package entries are the newer
                    # release data and therefore win over matching local ones.
                    count = _merge_package_store(name, imported_data)

                    imported_items.append(f"{name}: {len(imported_data)} entries ({count} new)")

                except Exception as e:
                    errors.append(f"Failed to import {name}: {e}")

            # Save all metadata
            if imported_items:
                # Persist synchronously before reloading. save_metadata() is
                # normally debounced, which previously caused this reload to
                # restore the old on-disk data and lose the entire import.
                _persist_imported_metadata()
                # Refresh directory/list views to show imported data.
                directory_scan.scan_directory()
                if state.lists.list_loaded == "playlist":
                    lists.show_playlist(True)

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
                except Exception:
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
                state.update_timestamps.metadata_last_updated = int(time.time())
            else:
                # For remote imports, use Last-Modified from the response we already have
                try:
                    last_modified = response.headers.get('Last-Modified')
                    if last_modified:
                        from email.utils import parsedate_to_datetime
                        state.update_timestamps.metadata_last_updated = int(parsedate_to_datetime(last_modified).timestamp())
                    else:
                        state.update_timestamps.metadata_last_updated = int(time.time())
                except Exception:
                    state.update_timestamps.metadata_last_updated = int(time.time())
            config_io.save_config()
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
