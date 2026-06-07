"""Themes-directory selection + scan.

`scan_directory` walks the configured `state.config.directory` for video files
and rebuilds the in-place `state.metadata.directory_files` map (preserving its
identity); `select_directory` prompts for a new folder.

Sibling helpers are imported directly, including the current-index refresh hub
`transport.update_current_index`; main keeps `select_directory` /
`scan_directory` aliases for the menu registry, metadata_fetch / metadata_import
(injected callbacks) and startup.
"""
import os
import threading
from tkinter import filedialog

from core.game_state import state
from _app_scripts.playlists import playlist
from _app_scripts.data import config_io
from _app_scripts.queue_round.lightning_rounds import mismatch_round
from _app_scripts.playback import transport


def select_directory():
    directory_path = filedialog.askdirectory()
    if directory_path:
        state.config.directory = directory_path
        scan_directory()


def scan_directory(queue=False):
    def worker():
        directory = state.config.directory
        if not directory:
            return
        directory_files = state.metadata.directory_files
        print("Scanning Directory...", end="", flush=True)
        # Mutate in place — keep identity for state.metadata.directory_files.
        directory_files.clear()
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith((".mp4", ".webm", ".mkv")):
                    directory_files[file] = os.path.join(root, file)
        playlist.invalidate_deduplicated_cache()
        config_io.save_config()
        mismatch_round.get_cached_sfw_themes()
        if state.metadata.playlist.get("infinite", False):
            playlist.get_pop_time_groups(refetch=True)
            transport.update_current_index()
        print(f"\rScanning Directory....COMPLETE ({len(directory_files)} files)")
    if queue:
        threading.Thread(target=worker, daemon=True).start()
    else:
        worker()
