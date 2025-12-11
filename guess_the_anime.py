# =========================================
#      GUESS THE ANIME - PLAYLIST TOOL
#             by Ramun Flame
# =========================================

# Version for auto-update functionality
APP_VERSION = "13.0"  # Update this when making releases
GITHUB_REPO = "ualkotob/guess-the-anime-playlist-tool"

import os
import sys
import shutil
import random
import math
import json
import requests
import xml.etree.ElementTree as ET
import re
import dxcam
import time
import copy
import ast
from collections import Counter
import numpy as np
from io import BytesIO
from datetime import datetime
import tkinter as tk
import tkinterdnd2 as tkdnd
import ctypes
from ctypes import wintypes
import threading
from tkinter import filedialog, messagebox, simpledialog, ttk, StringVar, font, Menu
import webbrowser
from PIL import Image, ImageTk, ImageFilter, ImageFont, ImageDraw
import threading  # For asynchronous metadata loading
import vlc
from yt_dlp import YoutubeDL
from pynput import keyboard, mouse
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pygame.pkgdata")
import pygame
import pyperclip
import pyautogui
import socket
from googleapiclient.discovery import build
import openai
import subprocess
import platform
from tkinter.font import Font

os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))

# Explicitly load libvlc.dll and its dependencies
vlc_path = r'C:\Program Files\VideoLAN\VLC'  # Replace with your VLC installation path
os.add_dll_directory(vlc_path)  # Add VLC directory to DLL search path

hw_acc_enabled = True
current_vout = None  # Track current video output module

def load_vlc_parameters(override_vout=None):
    """Load VLC parameters from file, optionally overriding --vout.

    If override_vout is provided, any existing --vout argument is removed and
    replaced with the requested one. Passing override_vout=None leaves any file
    value as-is. Passing override_vout="automatic" removes explicit --vout.
    """
    global hw_acc_enabled
    param_file = os.path.join("files", "vlc-parameters.txt")
    if os.path.isfile(param_file):
        with open(param_file, "r", encoding="utf-8") as f:
            print("Loaded custom vlc parameters.")
            parameters = [line.strip() for line in f if line.strip()]
            if '--avcodec-hw=none' in parameters:
                hw_acc_enabled = False
    else:
        parameters = [
            "--no-xlib",
            "-q",
            "--fullscreen",
            # "--vout=opengl"
        ]

    # Normalize removal of existing --vout if override requested
    if override_vout is not None:
        parameters = [p for p in parameters if not p.startswith('--vout=')]
        if override_vout and override_vout != 'automatic':
            parameters.append(f'--vout={override_vout}')
    return parameters

instance = None
player = None

def _recreate_vlc(params, restore_media=None, restore_time=0, was_playing=False):
    """Internal helper to safely recreate VLC instance/player."""
    global instance, player
    # Stop old player
    try:
        if player:
            player.stop()
    except Exception:
        pass
    # Release old instance (after stopping)
    try:
        if instance:
            instance.release()
    except Exception:
        pass
    # Create new instance; python-vlc expects args expanded
    instance = vlc.Instance(*params)
    player_new = instance.media_player_new()
    # Restore media if requested
    if restore_media is not None:
        try:
            player_new.set_media(restore_media)
            if was_playing:
                player_new.play()
            else:
                # Start then pause later if we need to seek
                player_new.play()
        except Exception as e:
            print(f"Failed to restore media after vout change: {e}")
        # Seek back to prior time (some modules need slight delay)
        if restore_time > 0:
            def _seek_back():
                try:
                    player_new.set_time(restore_time)
                    if not was_playing:
                        player_new.pause()
                except Exception:
                    pass
            try:
                # root may not yet exist at time; guard usage
                if 'root' in globals() and root:
                    root.after(200, _seek_back)
                else:
                    # Fallback simple timer
                    threading.Timer(0.2, _seek_back).start()
            except Exception:
                threading.Timer(0.2, _seek_back).start()
    player = player_new
    return player

def create_vlc_instance(vout=None):
    """Create the initial VLC instance; call once at startup.

    vout: desired video output module (e.g., 'opengl', 'direct3d11').
    """
    global current_vout
    current_vout = vout
    params = load_vlc_parameters(override_vout=vout)
    return _recreate_vlc(params)

def set_vout(vout_module=None, reload_current=False):
    """Change the video output module at runtime by recreating the VLC instance.

    vout_module: Name of the module (e.g., 'opengl', 'direct3d11', 'direct3d9', 'automatic').
    reload_current: Attempt to preserve current media & playback position.
    """
    global current_vout, player
    if not non_webm_opengl:
        return
    if vout_module == current_vout:
        print(f"VLC vout already '{vout_module}', no change.")
        return

    media = None
    was_playing = False
    cur_time = 0
    if reload_current and player is not None:
        try:
            media = player.get_media()
            if media:
                media.retain()  # keep reference
            state = player.get_state()
            was_playing = state == vlc.State.Playing
            try:
                cur_time = player.get_time()
            except Exception:
                cur_time = 0
        except Exception:
            media = None

    new_vout = None if vout_module in (None, 'automatic', '') else vout_module
    params = load_vlc_parameters(override_vout=new_vout)
    current_vout = new_vout
    _recreate_vlc(params, restore_media=media, restore_time=cur_time, was_playing=was_playing)

    if media:
        try:
            media.release()
        except Exception:
            pass

# Create initial player (automatic / file-defined vout)
create_vlc_instance()

# =========================================
#            FFMPEG AVAILABILITY CHECK
# =========================================

ffmpeg_available = False

def check_ffmpeg_availability():
    """Check if ffmpeg is available in system PATH"""
    global ffmpeg_available
    try:
        # Try to run ffmpeg -version to check if it's available
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        ffmpeg_available = result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        ffmpeg_available = False
        print("FFmpeg not found in PATH")
    return ffmpeg_available

def is_ffmpeg_available():
    """Return whether ffmpeg is available"""
    return ffmpeg_available

# Check ffmpeg availability on startup
check_ffmpeg_availability()

# =========================================
#          DRAG AND DROP SUPPORT
# =========================================

def enable_drag_and_drop(widget, callback):
    """Enable drag-and-drop for files from Windows Explorer."""
    
    # Method 1: Try tkinterdnd2 (best option)
    try:
        
        # Check if root is tkinterdnd2-enabled
        root = widget.winfo_toplevel()
        if hasattr(root, 'drop_target_register') or isinstance(root, tkdnd.Tk):
            widget.drop_target_register(tkdnd.DND_FILES)
            
            def handle_drop(event):
                global external_drag_active
                external_drag_active = False  # Clear external drag state
                
                files = widget.tk.splitlist(event.data)
                if files and callback:
                    # Pass event coordinates to callback for position detection
                    callback(files, event=event)
                return "copy"
            
            widget.dnd_bind('<<Drop>>', handle_drop)
            return True
        else:
            raise Exception("Root window not tkinterdnd2-enabled")
            
    except Exception as e:
        print(f"tkinterdnd2 failed: {e}")
    
    # Method 2: Windows API (more reliable than before)
    if sys.platform.startswith('win'):
        try:
            # Get window handle
            hwnd = widget.winfo_id()
            
            # Enable file dropping
            ctypes.windll.shell32.DragAcceptFiles(hwnd, True)
            
            # Store the original window procedure
            GWL_WNDPROC = -4
            original_wndproc = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
            
            def window_proc(hwnd, msg, wparam, lparam):
                WM_DROPFILES = 0x0233
                if msg == WM_DROPFILES:
                    try:
                        file_count = ctypes.windll.shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                        files = []
                        
                        for i in range(file_count):
                            length = ctypes.windll.shell32.DragQueryFileW(wparam, i, None, 0)
                            buffer = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.shell32.DragQueryFileW(wparam, i, buffer, length + 1)
                            files.append(buffer.value)
                        
                        ctypes.windll.shell32.DragFinish(wparam)
                        
                        if files and callback:
                            # Use after_idle to safely call callback from main thread
                            # Note: Windows API doesn't provide event coordinates easily
                            widget.after_idle(lambda f=files: callback(f, event=None))
                        return 0
                    except Exception as e:
                        print(f"Drop handling error: {e}")
                
                # Call original window procedure
                return ctypes.windll.user32.CallWindowProcW(original_wndproc, hwnd, msg, wparam, lparam)
            
            # Set up the window procedure with proper signature
            WNDPROC = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            new_wndproc = WNDPROC(window_proc)
            
            # Replace window procedure
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, new_wndproc)
            
            # Store reference to prevent garbage collection
            widget._drag_drop_wndproc = new_wndproc
            widget._original_wndproc = original_wndproc
            
            return True
            
        except Exception as e:
            print(f"Windows API drag-and-drop failed: {e}")
    
    # Method 3: Fallback to file dialogs
    try:
        def show_file_dialog(event=None):
            files = filedialog.askopenfilenames(
                title="Select media files to add to playlist",
                filetypes=[
                    ("Media files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.mp3 *.wav *.ogg *.m4a *.flac"),
                    ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm"),
                    ("Audio files", "*.mp3 *.wav *.ogg *.m4a *.flac"),
                    ("All files", "*.*")
                ]
            )
            if files and callback:
                callback(list(files), event=None)
        
        def show_context_menu(event):
            menu = Menu(widget, tearoff=0)
            menu.add_command(label="📁 Add Files to Playlist...", command=show_file_dialog)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        
        widget.bind("<Button-3>", show_context_menu)
        widget.bind("<Double-Button-1>", show_file_dialog)
        
        print(f"📁 File selection enabled on {widget.__class__.__name__}: Right-click or double-click")
        return True
        
    except Exception as e:
        print(f"Could not set up file selection: {e}")
        return False

def handle_dropped_files(files, event=None):
    """Handle files dropped from Windows Explorer."""
    global hovered_button_index
    
    added_files = []
    
    # Try to detect drop position using coordinates (since hover events don't work during external drag)
    insert_position = None
    
    # Method 1: Use event coordinates if available (tkinterdnd2)
    if event is not None and list_loaded == "playlist":
        try:
            if 'right_column' in globals():
                # Get the playlist widget position and bounds
                right_column.update_idletasks()
                widget_x = right_column.winfo_rootx()
                widget_y = right_column.winfo_rooty()
                widget_width = right_column.winfo_width()
                widget_height = right_column.winfo_height()
                
                # Check if drop is within playlist bounds
                if (widget_x <= event.x_root <= widget_x + widget_width and
                    widget_y <= event.y_root <= widget_y + widget_height):
                    
                    # Calculate relative position within the text widget
                    relative_x = event.x_root - widget_x
                    relative_y = event.y_root - widget_y
                    
                    # Use Text widget's index method to get the line at the drop position
                    # This automatically accounts for scrolling
                    try:
                        text_index = right_column.index(f"@{relative_x},{relative_y}")
                        drop_line = int(text_index.split('.')[0])
                        
                        # Account for pagination in playlist view
                        if list_loaded == "playlist":
                            # Convert line to actual playlist index (0-based) accounting for pagination
                            insert_position = max(0, drop_line - 1 + playlist_page_offset)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                        else:
                            # Account for the "items above" indicator if present
                            content = right_column.get("1.0", "2.0")
                            if "items above" in content:
                                drop_line = max(1, drop_line - 1)
                            
                            # Convert to 0-based index and clamp to valid range
                            insert_position = max(0, drop_line - 1)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                    except (ValueError, tk.TclError):
                        # Fallback to simple calculation if Text index fails
                        button_height = scl(12) + 8
                        insert_position = max(0, int(relative_y / button_height))
                        playlist_size = len(playlist.get("playlist", []))
                        insert_position = min(insert_position, playlist_size)
        except Exception as e:
            print(f"DEBUG: Event position detection failed: {e}")
    
    # Method 2: Use mouse coordinates if event method failed
    if insert_position is None and list_loaded == "playlist":
        try:
            mouse_x, mouse_y = pyautogui.position()
            
            if 'right_column' in globals():
                right_column.update_idletasks()
                widget_x = right_column.winfo_rootx()
                widget_y = right_column.winfo_rooty()
                widget_width = right_column.winfo_width()
                widget_height = right_column.winfo_height()
                
                # Check if mouse is over the playlist area
                if (widget_x <= mouse_x <= widget_x + widget_width and
                    widget_y <= mouse_y <= widget_y + widget_height):
                    
                    # Calculate relative position within the text widget
                    relative_x = mouse_x - widget_x
                    relative_y = mouse_y - widget_y
                    
                    # Use Text widget's index method to get the line at the mouse position
                    # This automatically accounts for scrolling
                    try:
                        text_index = right_column.index(f"@{relative_x},{relative_y}")
                        drop_line = int(text_index.split('.')[0])
                        
                        # Account for pagination in playlist view
                        if list_loaded == "playlist":
                            # Convert line to actual playlist index (0-based) accounting for pagination
                            insert_position = max(0, drop_line - 1 + playlist_page_offset)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                        else:
                            # Account for the "items above" indicator if present
                            content = right_column.get("1.0", "2.0")
                            if "items above" in content:
                                drop_line = max(1, drop_line - 1)
                            
                            # Convert to 0-based index and clamp to valid range
                            insert_position = max(0, drop_line - 1)
                            playlist_size = len(playlist.get("playlist", []))
                            insert_position = min(insert_position, playlist_size)
                    except (ValueError, tk.TclError):
                        # Fallback to simple calculation if Text index fails
                        button_height = scl(12) + 8
                        relative_position = max(0, int(relative_y / button_height))
                        if list_loaded == "playlist":
                            insert_position = relative_position + playlist_page_offset
                        else:
                            insert_position = relative_position
                        playlist_size = len(playlist.get("playlist", []))
                        insert_position = min(insert_position, playlist_size)
        except Exception as e:
            print(f"DEBUG: Mouse position detection failed: {e}")
    
    # Method 3: Default fallback
    if insert_position is None:
        current_index = playlist.get("current_index", -1)
        insert_position = current_index + 1 if current_index >= 0 else len(playlist["playlist"])
    
    # Clear any leftover hover state
    hovered_button_index = None
    
    for file_path in files:
        if os.path.isfile(file_path):
            # Get just the filename without path
            filename = os.path.basename(file_path)
            
            # Filter for media files (optional - you can remove this filter if you want all files)
            media_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', 
                              '.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac'}
            file_ext = os.path.splitext(filename)[1].lower()
            
            # Always add to playlist (allow duplicates)
            # Check if file is from the current directory
            if filename in directory_files:
                # Local file - store just filename
                playlist_entry = filename
            else:
                # External file - store full path
                playlist_entry = file_path
            
            # Insert at the specified position
            playlist["playlist"].insert(insert_position, playlist_entry)
            added_files.append(filename)  # Still show just filename in messages
            
            # Update current_index if we inserted before it
            current_index = playlist.get("current_index", -1)
            if current_index >= 0 and insert_position <= current_index:
                playlist["current_index"] = current_index + 1
            
            insert_position += 1  # Increment for next file
    
    # Show summary message
    if added_files:
        # Update the playlist display after adding files
        try:
            show_playlist(update=True)
        except NameError:
            # If show_playlist function doesn't exist, try other display functions
            try:
                show_list("playlist", None, None, None, None, None, update=True)
            except:
                print("Could not refresh playlist display")
    
    # Clear hover state after drop
    hovered_button_index = None
        
    # Refresh playlist display if it's currently shown
    if list_loaded == "playlist":
        show_playlist(True)

# =========================================
#       *GLOBAL VARIABLES/CONSTANTS
# =========================================

BLANK_PLAYLIST = {
    "name":"",
    "current_index":-1,
    "lightning_history": {},
    "background_track_history": [],
    "infinite":False,
    "difficulty":2,
    "order": 0,
    "pop_time_order": [],
    "playlist":[]
}
playlist = copy.deepcopy(BLANK_PLAYLIST)
video_stopped = True
can_seek = True
file_metadata = {}
FILE_METADATA_FILE = "metadata/file_metadata.json"
anime_metadata = {}
ANIME_METADATA_FILE = "metadata/anime_metadata.json"
anidb_metadata = {}
ANIDB_METADATA_FILE = "metadata/anidb_metadata.json"
ai_metadata = {}
AI_METADATA_FILE = "metadata/ai_metadata.json"
anime_metadata_overrides = {}
ANIME_METADATA_OVERRIDES_FILE = "metadata/anime_metadata_overrides.json"
manual_metadata_file = "metadata/manual_metadata.json"
youtube_metadata = {}
YOUTUBE_METADATA_FILE = "metadata/youtube_metadata.json"
directory = ""
directory_files = {}

def get_file_path(playlist_entry):
    """Get the full file path for a playlist entry.
    
    Args:
        playlist_entry: Either a filename (for local files) or full path (for external files), may have [L] prefix
    
    Returns:
        Full file path or None if file doesn't exist
    """
    # Remove [L] prefix if present
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    
    if os.path.isabs(clean_entry):
        # It's already a full path (external file)
        return clean_entry if os.path.exists(clean_entry) else None
    else:
        # It's a filename, look it up in directory_files
        return directory_files.get(clean_entry)

def is_external_file(playlist_entry):
    """Check if a playlist entry is an external file (full path) or local file (filename)."""
    # Remove [L] prefix if present before checking
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    return os.path.isabs(clean_entry)

def get_display_filename(playlist_entry):
    """Get the display filename for a playlist entry."""
    return os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry

def get_clean_filename(playlist_entry):
    """Remove [L] prefix to get actual filename for file operations."""
    clean_entry = playlist_entry[3:] if playlist_entry.startswith("[L]") else playlist_entry
    return os.path.basename(clean_entry) if os.path.isabs(clean_entry) else clean_entry

def is_youtube_file(filename):
    """Check if a filename corresponds to a YouTube video in metadata."""
    if not youtube_metadata.get("videos"):
        return False
    
    # Check if any YouTube video has this filename
    for video_id, video in youtube_metadata.get("videos", {}).items():
        if video.get("filename") == filename:
            return True
    return False

def get_youtube_metadata_by_filename(filename):
    """Get YouTube metadata for a specific filename."""
    for video_id, video in youtube_metadata.get("videos", {}).items():
        if video.get("filename") == filename:
            # Add channel info
            channel_info = youtube_metadata.get("channels", {}).get(video.get("channel_id"), {
                "name": "N/A",
                "subscriber_count": 0
            })
            return video | channel_info | {"url": video_id}
    return None

host = ""
volume_level = 100
stream_volume_boost = 0
title_top_info_txt = ""
end_session_txt = ""
inverted_colors = False
inverted_positions = False
half_points = False
non_webm_opengl = False
scale_main_ui = False
auto_fetch_missing = False
special_round_warning = True
YOUTUBE_API_KEY = ""
OPENAI_API_KEY = ""
CONFIG_FILE = "files/config.json"
YOUTUBE_FOLDER = "youtube"
ARCHIVE_FILE = "files/youtube_archive.txt"
PLAYLISTS_FOLDER = "playlists/"
FILTERS_FOLDER = "filters"
YOUTUBE_LINKS_FILE = "files/youtube_links.txt"
CENSOR_FILE = "files/censors.csv"
CENSOR_JSON_FILE = "files/censors.json"
TAGGED_FILE = "files/tagged.txt"
HIGHLIGHT_COLOR = "gray26"
OVERLAY_BACKGROUND_COLOR = "black"
OVERLAY_TEXT_COLOR = "white"
INVERSE_OVERLAY_BACKGROUND_COLOR = "white"
INVERSE_OVERLAY_TEXT_COLOR = "black"
MIDDLE_OVERLAY_BACKGROUND_COLOR = "dark gray"
OVERLAY_COLOR_OPTIONS = ["black", "white"]

DISPLAY_SCREEN_WIDTH, DISPLAY_SCREEN_HEIGHT = pyautogui.size()
def scl(num, type=None):
    if type == "UI" and not scale_main_ui:
        return num
    modifier_w, modifier_h = DISPLAY_SCREEN_WIDTH / 2560, DISPLAY_SCREEN_HEIGHT / 1440
    modifier = min(modifier_w, modifier_h)
    return int(num*modifier)

# =========================================
#         *FETCHING ANIME METADATA
# =========================================

# Function to fetch anime metadata using AnimeThemes.moe API
animethemes_cache = {}
def fetch_animethemes_metadata(filename=None, mal_id=None, split=True):
    url = "https://api.animethemes.moe/anime"
    if filename:
        if split:
            filename = filename.split("-")[0]
            filename_query = filename + "-%"
        else:
            filename_query = filename
        if animethemes_cache.get(filename):
            return animethemes_cache.get(filename)
        params = {
            "filter[has]": "animethemes.animethemeentries.videos",
            "filter[video][basename-like]": filename_query,
            "include": "series,resources,images,animethemes.animethemeentries.videos,animethemes.song.artists"
        }
    else:
        params = {
            "filter[has]": "resources",
            "filter[resource][site]": "MyAnimeList",
            "filter[resource][external_id]": str(mal_id),
            "include": "series,resources,images,animethemes.animethemeentries.videos,animethemes.song.artists"
        }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data.get("anime"):
            if filename:
                animethemes_cache[filename] = data["anime"][0]
            return data["anime"][0]
    return None

# Function to fetch anime metadata using Jikan API
def fetch_jikan_metadata(mal_id):
    url = f"https://api.jikan.moe/v4/anime/{mal_id}/full"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data.get("data"):
            return data["data"]
    return None

def fetch_anidb_metadata(aid):
    url = "http://api.anidb.net:9001/httpapi"
    params = {
        "request": "anime",
        "client": "guesstheanime",
        "clientver": "1",
        "protover": "1",
        "aid": str(aid)
    }

    response = requests.get(url, params=params)
    if not response.ok:
        raise Exception(f"AniDB request failed: {response.status_code}")

    root = ET.fromstring(response.text)
    result = {}

    ### TAGS ###
    tag_elements = root.findall("tags/tag")
    tag_id_map = {tag.get("id"): tag for tag in tag_elements}
    parent_ids = {tag.get("parentid") for tag in tag_elements if tag.get("parentid")}

    tags = []
    for tag in tag_elements:
        if tag.get("globalspoiler") == "true" or tag.get("localspoiler") == "true":
            continue
        tag_id = tag.get("id")
        if tag_id in parent_ids:
            continue  # It's a parent
        name = tag.findtext("name")
        weight = int(tag.get("weight") or 0)
        if name:
            tags.append([name.lower(), weight])
    result["tags"] = tags

    ### CHARACTERS ###
    max_types = {
        "a":{"max":20},
        "s":{"max":15},
        "m":{"max":15}
    }
    characters = []
    all_characters = root.findall("characters/character")
    for char in all_characters:
        name = char.findtext("name")
        char_type = char.get("type")[:1] or "a"
        pic = char.findtext("picture")
        gender = char.findtext("gender")
        desc = char.findtext("description")
        if pic and char_type in ['a','s','m']:
            character = [char_type, name, os.path.basename(pic), gender]
            if desc:
                character.append(desc.split("\nSource:")[0])
            if max_types[char_type].get("count", 0) < max_types[char_type]["max"]:
                max_types[char_type]["count"] = max_types[char_type].get("count", 0) + 1
                characters.append(character)
    result["characters"] = characters

    ### EPISODES ###
    episodes = []
    for ep in root.findall("episodes/episode"):
        epno_elem = ep.find("epno")
        if epno_elem is None or epno_elem.get("type") != "1":
            continue

        epno = epno_elem.text
        if not epno or not epno.isdigit() or (epno.isdigit() and int(epno) >= 50):
            continue

        number = int(epno)

        # Loop through all titles and find the one with xml:lang="en"
        title = None
        for title_elem in ep.findall("title"):
            if title_elem.attrib.get("{http://www.w3.org/XML/1998/namespace}lang") == "en":
                title = title_elem.text.strip()
                break

        # fallback if not found
        if not title:
            title = f"Episode {number}"

        episodes.append([number, title])

    result["episodes"] = episodes

    return result

def fetch_anilist_user_ids(username, watched_only=False):
    """Fetches a set of AniList anime IDs for a given username. Can filter for only watched anime."""
    query = '''
    query ($name: String) {
      MediaListCollection(userName: $name, type: ANIME) {
        lists {
          entries {
            status
            media {
              id
            }
          }
        }
      }
    }
    '''
    variables = {
        "name": username
    }

    response = requests.post(
        "https://graphql.anilist.co",
        json={"query": query, "variables": variables}
    )

    if response.status_code != 200:
        print("AniList API error:", response.text)
        return set()

    try:
        data = response.json()
        ids = {
            str(entry["media"]["id"])
            for lst in data["data"]["MediaListCollection"]["lists"]
            for entry in lst["entries"]
            if (
                "media" in entry
                and entry["media"].get("id")
                and (
                    not watched_only or entry.get("status") in ("COMPLETED", "REPEATING")
                )
            )
        }
        return ids
    except Exception as e:
        print("Failed to parse AniList response:", e)
        return set()

def pre_fetch_metadata():
    for i in range(playlist["current_index"]-1, playlist["current_index"]+3):
        playlist_entry = playlist["playlist"][i] if i >= 0 and i < len(playlist["playlist"]) else None
        if playlist_entry and i != playlist["current_index"]:
            filename = get_clean_filename(playlist_entry)
            filepath = get_file_path(playlist_entry)
            if fetching_metadata.get(filename) is None and filepath and os.path.exists(filepath):
                get_metadata(filename, refresh=True, fetch=True)

# Global cache for merged metadata
_metadata_cache = {}
# Make sure this is initialized as a set!
fetched_metadata = set()

# Performance optimization: cache for file metadata base name lookups
_file_metadata_base_cache = {}
_file_metadata_cache_valid = False

def invalidate_file_metadata_cache():
    """Call this when file_metadata changes"""
    global _file_metadata_cache_valid
    _file_metadata_cache_valid = False

def build_file_metadata_base_cache():
    """Build reverse lookup table for base names (without extensions)"""
    global _file_metadata_base_cache, _file_metadata_cache_valid
    
    if _file_metadata_cache_valid:
        return
    
    _file_metadata_base_cache = {}
    
    for filename in file_metadata:
        base_name = os.path.splitext(filename)[0]
        _file_metadata_base_cache[base_name] = filename
        
    _file_metadata_cache_valid = True

def get_metadata(filename, refresh=False, refresh_all=False, fetch=False):
    global fetched_metadata

    # Fast return if already cached and no refresh/fetch needed
    if not (refresh or fetch) and filename in _metadata_cache:
        return _metadata_cache[filename]

    if filename and not ("-OP" in filename or "-ED" in filename):
        return {}

    file_data = get_file_metadata_by_name(filename)
    if not file_data:
        return fetch_metadata(filename) if fetch else {}

    mal_id = file_data.get('mal')
    anidb_id = file_data.get('anidb')
    anime_data = anime_metadata.get(mal_id) or {}
    anidb_data = anidb_metadata.get(anidb_id, {}) if anidb_id else {}
    ai_data = ai_metadata.get(mal_id, {}) if mal_id else {}
    re_queue_lightning_mode = False
    if anime_data and "-[ID]" not in filename and mal_id:
        if refresh and mal_id not in fetched_metadata and (refresh_all or (auto_refresh_toggle and fetch)):
            fetched_metadata.add(mal_id)
            refresh_jikan_data(mal_id, anime_data)
            if light_mode:
                re_queue_lightning_mode = True
        if refresh and fetch and anidb_id and (anidb_id not in anidb_metadata or auto_refresh_toggle) and not anidb_cooldown and (variety_light_mode_enabled or light_mode in ['character', 'tags', 'episodes', 'names'] or (light_mode and "c." in light_mode)):
            refresh_anidb_data(anidb_id, anime_data)
            re_queue_lightning_mode = True

    result = file_data | anime_data | anidb_data | ai_data
    _metadata_cache[filename] = result
    if re_queue_lightning_mode:
        queue_next_lightning_mode()
    return result

def get_file_metadata_by_name(filename):
    """
    Get file metadata for a filename, trying exact match first, then matching without extension.
    This allows files with different extensions (e.g., .mp4 vs .webm) to share metadata.
    """
    # First try exact match
    file_data = file_metadata.get(filename)
    if file_data:
        return file_data
    
    # If no exact match, try cached base name lookup
    if filename:
        build_file_metadata_base_cache()
        base_name = os.path.splitext(filename)[0]
        cached_filename = _file_metadata_base_cache.get(base_name)
        if cached_filename:
            return file_metadata[cached_filename]
    
    return None

def get_version_from_filename(filename):
    """Extract version information from filename, with metadata lookup as priority."""
    # Try to get version from stored metadata first
    file_data = get_file_metadata_by_name(filename)
    if file_data and file_data.get('version'):
        return file_data['version']
    
    # Fallback to filename parsing
    try:
        parts = filename.split("-")
        if len(parts) >= 2:
            version_part = parts[1].split(".")[0]
            if "v" in version_part:
                return version_part.split("v")[1] if len(version_part.split("v")) > 1 else None
    except:
        pass
    
    return None

def refetch_metadata():
    if currently_playing and currently_playing.get('type') == 'theme':
        filename = currently_playing.get('filename')
    else:
        playlist_entry = get_clean_filename(playlist["playlist"][playlist["current_index"]])
        filename = os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry
    fetch_metadata(filename, True)

def get_external_site_id(anime_themes, site):
    if anime_themes:
        for resource in anime_themes.get("resources", []):
            if resource["site"] == site:
                site_id = str(resource["external_id"])
                if site_id == "None" or ("/episode/" in resource.get("link", "")):
                    return None
                return site_id
    return None

anidb_cooldown = False
fetching_metadata = {}
def fetch_metadata(filename = None, refetch = False, label=""):
    global currently_playing, anidb_cooldown, anidb_delay
    if filename is None:
        playlist_entry = get_clean_filename(playlist["playlist"][playlist["current_index"]])
        filename = os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry
        refetch = True

    print(f"{label}Fetching metadata for {filename}...", end="", flush=True)

    fetching_metadata[filename] = True
    slug = filename.split("-")[1].split(".")[0].split("v")[0]
    version = None
    mal_id = None
    anidb_id = None
    anilist_id = None
    if (not "[MAL]" in filename) and (not "[ID]" in filename):
        anime_themes = fetch_animethemes_metadata(filename)
        # Extract slug and version from animethemes data instead of filename
        slug_found = False
        extra_check = False
        while not slug_found and not extra_check:
            if anime_themes and anime_themes.get("animethemes"):
                for theme in anime_themes.get("animethemes", []):
                    theme_entries = theme.get("animethemeentries", [])
                    for entry in theme_entries:
                        videos = entry.get("videos", [])
                        for video in videos:
                            if video.get("basename") and (filename.split(".")[0] == video.get("basename", "").split(".")[0]):
                                slug = theme.get("slug", slug)
                                version = entry.get("version")
                                slug_found = True
                                break
                        if slug_found:
                            break
                    if slug_found:
                        break
            if not slug_found:
                extra_check = True
                anime_themes = fetch_animethemes_metadata(filename, split=False)
        mal_id = get_external_site_id(anime_themes, "MyAnimeList")
        anidb_id = get_external_site_id(anime_themes, "aniDB")
        anilist_id = get_external_site_id(anime_themes, "AniList")
    elif ("[MAL]" in filename):
        filename_metadata = get_filename_metadata(filename)
        mal_id = filename_metadata.get('mal_id')
        anidb_id = filename_metadata.get('anidb_id')
        anilist_id = filename_metadata.get('anilist_id')
        anime_themes = fetch_animethemes_metadata(mal_id=mal_id)
        if not anime_themes:
            anime_themes = {
                 "animethemes":[]
            }
        else:
            try:
                file = anime_themes.get("animethemes",[{}])[0].get("animethemeentries",[{}])[0].get("videos",[{}])[0].get("basename")
            except:
                file = None
            if file:
                anime_themes = fetch_animethemes_metadata(file) or anime_themes
                anidb_id = anidb_id or get_external_site_id(anime_themes, "aniDB")
                anilist_id = anilist_id or get_external_site_id(anime_themes, "AniList")
        if filename_metadata.get("song"):
            artists_group = []
            for art in filename_metadata.get("artist", "N/A").split('+'):
                artists_group.append(
                    {"name":art}
                )
            anime_themes["animethemes"].append({
                "type": slug[:2],
                "slug": slug,
                "song": {
                    "title": filename_metadata.get("song", "N/A"),
                    "artists": artists_group
                }
            })
        if filename_metadata.get("season"):
            anime_themes["season"] = filename_metadata["season"]
            anime_themes["year"] = filename_metadata["year"]
    else:
        mal_id = re.search(r"\[ID](.*?)(?=\[|$|\.)", filename).group(1)
        anime_themes = {}
    if mal_id:
        file_data = {
            "mal":mal_id,
            "anidb":anidb_id,
            "anilist":anilist_id,
            "slug":slug,
            "version":version
        }
        anime_data = anime_metadata.get(mal_id)
        old_songs = []
        if anime_data:
            old_songs = anime_data.get("songs", [])
        file_metadata[filename] = file_data
        invalidate_file_metadata_cache()  # Invalidate cache when file_metadata changes
        if refetch or not anime_data or not anime_data.get("title"):
            jikan_data = fetch_jikan_metadata(mal_id)
            if jikan_data:
                anime_data = {
                    "title":jikan_data.get("title"),
                    "eng_title":jikan_data.get("title_english", "N/A"),
                    "synonyms":jikan_data.get("title_synonyms", []),
                    "series":get_name_list(anime_themes, "series"),
                    "aired": jikan_data.get("aired", []).get("string"),
                    "season":str(jikan_data.get("season") or "N/A") + " " + str(jikan_data.get("year") or "N/A"),
                    "score":jikan_data.get("score", "N/A"),
                    "rank":jikan_data.get("rank", "N/A"),
                    "members":jikan_data.get("members", "N/A"),
                    "popularity":jikan_data.get("popularity", "N/A"),
                    "type":jikan_data.get("type", "N/A"),
                    "source":jikan_data.get("source", "N/A"),
                    "episodes":jikan_data.get("episodes", "N/A"),
                    "studios":get_name_list(jikan_data, "studios"),
                    "genres":get_name_list(jikan_data, "genres"),
                    "themes":get_name_list(jikan_data, "themes"),
                    "demographics":get_name_list(jikan_data, "demographics"),
                    "synopsis":jikan_data.get('synopsis', "N/A"),
                    "cover":jikan_data.get("images", {}).get("jpg", {}).get("large_image_url"),
                    "trailer":jikan_data.get("trailer", {}).get("youtube_id")
                }
                if "N/A" in anime_data.get("season"):
                    if anime_themes.get("season"):
                        anime_data["season"] = str(anime_themes.get("season", "N/A")) + " " + str(anime_themes.get("year", "N/A"))
                    else:
                        anime_data["season"] = aired_to_season_year(anime_data.get("aired"))
                else:
                    anime_data["season"] = anime_data["season"].capitalize()
                anime_metadata[mal_id] = anime_data
        if anidb_id:
            anidb_data = anidb_metadata.get(anidb_id, {})
            if anime_data and (refetch or not anidb_data.get("characters") or not anidb_data.get("tags") or not anidb_data.get("episode_info")):
                if not anidb_cooldown:
                    anidb = fetch_anidb_metadata(anidb_id)
                    if anidb["tags"] == [] and anidb["characters"] == [] and anidb["episodes"] == []:
                        anidb_cooldown = True
                        print("[aniDB cooldown reached!]")
                    else:
                        anidb_delay = 5
                        anidb_data["tags"] = anidb["tags"]
                        anidb_data["characters"] = anidb["characters"]
                        anidb_data["episode_info"] = anidb["episodes"]
                        anidb_metadata[anidb_id] = anidb_data
        if anime_data:
            # Get new songs from the current fetch
            new_songs = get_theme_list(anime_themes, slug, version)
            # Avoid duplicates by checking slugs (each song has a unique slug)
            all_songs = {song["slug"]: song for song in old_songs + new_songs}.values()
            openings = []
            endings = []
            other = []
            for song in all_songs:
                if "OP" in song["slug"]:
                    openings.append(song)
                elif "ED" in song["slug"]:
                    endings.append(song)
                else:
                    other.append(song)
                    
            def slug_sort_key(song):
                slug = song["slug"]
                match = re.match(r"([A-Z]+)(\d+)(.*)", slug)
                if match:
                    prefix, num, variant = match.groups()
                    is_variant = bool(variant)  # True if there's a suffix like _EN
                    return (prefix, is_variant, int(num))
                else:
                    # Push unrecognized formats to the end
                    return ("ZZZ", True, INT_INF)

            # Sort and combine
            anime_data["songs"] = (
                sorted(openings, key=slug_sort_key) +
                sorted(endings, key=slug_sort_key) +
                sorted(other, key=slug_sort_key)
            )
            anime_data["series"] = get_name_list(anime_themes, "series")
            save_metadata()
            data = file_data | anime_data
            if currently_playing.get('filename') == filename:
                currently_playing["data"] = data
                update_metadata()
            print(f"\r{label}Fetching metadata for {filename}...COMPLETE")
        else:
            data = {}
            print(f"\r{label}Fetching metadata for {filename}...FAILED")
    else:
        data = {}
        print(f"\r{label}Fetching metadata for {filename}...FAILED")
    return data

def get_theme_list(data, file_slug=None, file_version=None):
    openings = []
    endings = []
    other = []
    for theme in data.get("animethemes", {}):
        artists = []
        song = theme.get("song") or {'title': None, 'artists': []}
        theme_data = {
            "type": theme["type"],
            "slug": theme["slug"],
            "title": song.get("title"),
            "artist": artists,
            "episodes": None,
            "nsfw": False
        }
        if song:
            for artist in song.get("artists", []):
                artists.append(artist["name"])
            
            # Collect all versions from animethemeentries
            versions = []
            no_overlap = False
            no_spoiler = False
            if theme.get("animethemeentries"):
                for entry in theme.get("animethemeentries", []):
                    version_data = {
                        "version": entry.get("version"),
                        "episodes": entry.get("episodes", "N/A"),
                        "spoiler": entry.get("spoiler", False),
                        "nsfw": entry.get("nsfw", False)
                    }
                    
                    # Get overlap from first video if available
                    overlap = None
                    if entry.get("videos") and entry["videos"]:
                        overlap = entry["videos"][0].get("overlap")
                        if overlap and overlap != "None":
                            version_data["overlap"] = overlap
                    
                    versions.append(version_data)

                    if file_slug == theme["slug"]:
                        if not theme_data["episodes"]:
                            theme_data["episodes"] = entry["episodes"]
                    if not entry["spoiler"]:
                        no_spoiler = True
                    if entry["nsfw"]:
                        theme_data["nsfw"] = entry["nsfw"]
                    if overlap == "None":
                        no_overlap = True

            theme_data["versions"] = versions
            # Keep legacy fields for backward compatibility (from first version)
            if versions:
                if not no_spoiler and versions[0].get("spoiler"):
                    theme_data["spoiler"] = versions[0]["spoiler"]
                if not theme_data.get("nsfw") and versions[0].get("nsfw"):
                    theme_data["nsfw"] = versions[0]["nsfw"]
                if not no_overlap and versions[0].get("overlap"):
                    theme_data["overlap"] = versions[0]["overlap"]
                if not theme_data.get("episodes") and versions[0].get("episodes"):
                    theme_data["episodes"] = versions[0]["episodes"]
            
            if "OP" in theme["slug"]:
                openings.append(theme_data)
            elif "ED" in theme["slug"]:
                endings.append(theme_data)
            else:
                other.append(theme_data)
    return openings + endings + other

def get_filename_metadata(filename):
    """Extracts MAL ID, artist, and song name from a filename with optional bracketed tags."""
    metadata = {"mal_id": None, "anidb_id": None, "artist": None, "song": None}
    
    # Define patterns for each tag
    mal_match = re.search(r"\[MAL](\d+)", filename)
    anidb_match = re.search(r"\[ADB](\d+)", filename)
    anilist_match = re.search(r"\[ALT](\d+)", filename)
    artist_match = re.search(r"\[ART](.*?)(?=\[|$|\.)", filename)
    song_match = re.search(r"\[SNG](.*?)(?=\[|$|\.)", filename)
    
    # Extract values if found
    if mal_match:
        metadata["mal_id"] = mal_match.group(1)

    if anidb_match:
        metadata["anidb_id"] = anidb_match.group(1)

    if anilist_match:
        metadata["anilist_id"] = anilist_match.group(1)
    
    if artist_match:
        metadata["artist"] = artist_match.group(1).strip()
    
    if song_match:
        metadata["song"] = song_match.group(1).strip()

    season_year = get_last_two_folders(directory_files.get(filename))
    season = season_year[1]
    year = season_year[0]
    if season in ['Winter','Spring','Summer','Fall']:
        metadata["season"] = season
        metadata["year"] = year
    return metadata

def refresh_jikan_data(mal_id, data, label=""):
    title = data.get('title', f"MAL ID: {mal_id}")
    print(f"{label}Refreshing Jikan data for {title}...", end="", flush=True)
    
    jikan_data = fetch_jikan_metadata(mal_id)
    if jikan_data:
        data["title"] = jikan_data.get("title", "N/A")
        data["eng_title"] = jikan_data.get("title_english", "N/A")
        data["synonyms"] = jikan_data.get("title_synonyms", [])
        data["aired"] = jikan_data.get("aired", []).get("string")
        data["score"] = jikan_data.get("score", "N/A")
        data["rank"] = jikan_data.get("rank", "N/A")
        data["members"] = jikan_data.get("members", "N/A")
        data["popularity"] = jikan_data.get("popularity", "N/A")
        data["type"] = jikan_data.get("type", "N/A")
        data["source"] = jikan_data.get("source", "N/A")
        data["episodes"] = jikan_data.get("episodes", "N/A")
        data["studios"] = get_name_list(jikan_data, "studios")
        data["genres"] = get_name_list(jikan_data, "genres")
        data["themes"] = get_name_list(jikan_data, "themes")
        data["demographics"] = get_name_list(jikan_data, "demographics")
        data["synopsis"] = jikan_data.get("synopsis", "N/A")
        data["cover"] = jikan_data.get("images", {}).get("jpg", {}).get("large_image_url")
        data["trailer"] = jikan_data.get("trailer", {}).get("youtube_id")
        
        save_metadata()
        print(f"\r{label}Refreshing Jikan data for {data['title']}...COMPLETE")
    else:
        print(f"\r{label}Refreshing Jikan data for {title}...FAILED")

def refresh_anidb_data(anidb_id, data, label=""):
    global anidb_cooldown, anidb_delay

    fetch_string = "Refreshing"
    if anidb_id not in anidb_metadata:
        fetch_string = "Fetching"
    print(f"{label}{fetch_string} aniDB data for {data['title']}...", end="", flush=True)
    
    anidb = fetch_anidb_metadata(anidb_id)
    if anidb:
        if anidb["tags"] == [] and anidb["characters"] == []:
            anidb_cooldown = True
            print(f"\rRefreshing aniDB data for {data['title']}...FAILED[aniDB cooldown reached!]")
        else:
            anidb_metadata[anidb_id] = {
                "tags": anidb["tags"],
                "characters": anidb["characters"],
                "episode_info": anidb["episodes"]
            }
            save_metadata()
            anidb_delay = 5
            print(f"\r{label}{fetch_string} aniDB data for {data['title']}...COMPLETE")
    else:
        print(f"\r{label}{fetch_string} aniDB data for {data['title']}...FAILED")

def aired_to_season_year(aired_str, start=True):
    """Converts an aired string to 'Season Year' format based on the start or end date."""
    
    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, "%b %d, %Y")
        except:
            return datetime.strptime(date_str, "%B %d, %Y")

    def get_season_from_date(date_obj):
        month = date_obj.month
        if month in [1, 2, 3]:
            return "Winter"
        elif month in [4, 5, 6]:
            return "Spring"
        elif month in [7, 8, 9]:
            return "Summer"
        else:
            return "Fall"

    try:
        if "to" in aired_str:
            parts = aired_str.split("to")
            chosen_part = parts[0].strip() if start else (parts[1].strip() if len(parts) > 1 else "?")
        else:
            chosen_part = aired_str.strip()
        if chosen_part == "?":
            aired_date = datetime.now()
        else:
            aired_date = parse_date(chosen_part)

        season = get_season_from_date(aired_date)
        return f"{season} {aired_date.year}"

    except Exception as e:
        print(f"Error parsing aired string: {aired_str} -> {e}")
        return "N/A"

def get_last_two_folders(filepath):
    path_parts = filepath.split(os.sep)
    # Filter out empty strings that might occur due to leading/trailing separators or double separators
    path_parts = list(filter(None, path_parts))
    if len(path_parts) >= 3:
        return [path_parts[-3], path_parts[-2]]
    else:
        return ["",""]
    
def get_name_list(data, get):
    name_list = []
    for item in data.get(get, []):
        name_list.append(item.get("name"))
    return name_list

def get_artists_string(artists, total = False, limit=None):
    #lists artists as a string, optionally with total count in brackets if limited display rest as & 1 more
    artists_string = "N/A"
    if artists:
        displayed_count = 0
        for artist in artists:
            # Check if we've reached the limit
            if limit is not None and displayed_count >= limit:
                remaining = len(artists) - displayed_count
                if remaining > 0:
                    artists_string += f" & {remaining} more"
                break
                
            if artists_string == "N/A":
                artists_string = artist
            else:
                artists_string = artists_string + ", " + artist
            if total:
                artist_count = len(get_filenames_from_artist(artist))
                if artist_count > 1:
                    artists_string = f"{artists_string} [{artist_count}]"
            
            displayed_count += 1
    return artists_string

anidb_delay = 0
def fetch_all_metadata(delay=0):
    global cached_pop_time_group, series_cooldowns_cache
    """Fetches missing metadata for the entire directory, spacing out API calls."""
    confirm = messagebox.askyesno("Fetch All Missing Metadata", f"Are you sure you want to fetch all missing metadata?")
    if not confirm:
        return  # User canceled
    scan_directory()
    cached_pop_time_group = None
    series_cooldowns_cache = None
    def fetch_all_metadata_worker():
        global anidb_delay
        total_checked = 0
        total_fetched = 0
        total_skipped = 0
        total_missing = 0
        save_new_theme = False

        refresh_jikan = []
        refresh_anidb = []
        fetch_data = []
        for filename in directory_files:
            total_checked += 1
            # Skip if metadata already exists
            file_data = get_file_metadata_by_name(filename)
            if file_data:
                mal_id = file_data.get('mal')
                anidb_id = file_data.get('anidb')
                if mal_id in anime_metadata and (not anidb_id or anidb_id in anidb_metadata):
                    if not anime_metadata.get(mal_id, {}).get("title"):
                        jikan_append = [mal_id, anime_metadata.get(mal_id)]
                        if jikan_append not in refresh_jikan:
                            refresh_jikan.append(jikan_append)
                            total_missing += 1
                    continue
                if anidb_id and (not anidb_id in anidb_metadata):
                    if anidb_cooldown:
                        total_skipped += 1
                    else:
                        anidb_append = [anidb_id, anime_metadata.get(mal_id)]
                        if anidb_append not in refresh_anidb:
                            refresh_anidb.append(anidb_append)
                            total_missing += 1
                    continue
            fetch_data.append(filename)
            total_missing += 1
        if total_missing > 0:
            if fetch_data:
                save_new_theme = messagebox.askyesno("Save Missing Entries To New Themes", f"Would you like to save all missing entries to the 'New Themes' playlist? Entries in the 'New Themes' will not appear in infinite playlists until removed from the 'New Themes' playlist. (Select 'NO' if unsure)")
            for filename in fetch_data:
                if total_fetched > 0 and delay+anidb_delay > 0: 
                    time.sleep(delay+anidb_delay)  # Delay to avoid API rate limits
                    anidb_delay = 0
                try:
                    fetch_metadata(filename, label=f"[{total_fetched+1}/{total_missing}]")  # Call your existing metadata function
                    if save_new_theme:
                        toggle_theme("New Themes", filename=filename, quiet=True)
                    total_fetched += 1
                except Exception as e:
                    print(e)
                    time.sleep(3)  # Delay to avoid API rate limits
                    total_skipped += 1
            for file_refresh in refresh_jikan:
                try:
                    refresh_jikan_data(file_refresh[0], file_refresh[1], label=f"[{total_fetched+1}/{total_missing}]")
                    total_fetched += 1
                except Exception as e:
                    print(e)
                    time.sleep(3)  # Delay to avoid API rate limits
                    total_skipped += 1
            for file_anidb_refresh in refresh_anidb:
                try:
                    if total_fetched > 0 and delay+anidb_delay > 0: 
                        time.sleep(delay+anidb_delay)  # Delay to avoid API rate limits
                        anidb_delay = 0
                    if not anidb_cooldown:
                        if file_anidb_refresh[0] not in anidb_metadata:
                            refresh_anidb_data(file_anidb_refresh[0], file_anidb_refresh[1], label=f"[{total_fetched+1}/{total_missing}]")
                        total_fetched += 1
                    else:
                        total_skipped += 1
                except Exception as e:
                    print(e)
                    time.sleep(3)  # Delay to avoid API rate limits
                    total_skipped += 1

        print("Metadata fetching complete! - Checked:" + str(total_checked) + " Missing:" + str(total_fetched+total_skipped) + " Skipped:" + str(total_skipped))
        if save_new_theme and total_fetched > 0:
            print(f"{total_fetched} files saved to playlist '{"New Themes"}'.")

    # Run in a separate thread so it doesn’t freeze the UI
    threading.Thread(target=fetch_all_metadata_worker, daemon=True).start()

def refresh_all_metadata(delay=1):
    """Refreshes all jikan metadata for files in the directory, spacing out API calls."""
    confirm = messagebox.askyesno("Refresh All Jikan Metadata", f"Are you sure you want to refresh all jikan metadata for files in your directory?")
    if not confirm:
        return  # User canceled
    
    current_year = datetime.now().year
    
    # Get year limit from user input (must be done on main thread)
    year_input = simpledialog.askstring(
        "Year Limit", 
        f"Enter how many years back to refresh (leave empty for all years):\n\nCurrent year: {current_year}",
        initialvalue=""
    )
    
    # If user cancelled the dialog, return
    if year_input is None:
        return
    
    def worker(year_input):
        current_year = datetime.now().year
        # Parse year limit
        year_limit = None
        if year_input and year_input.strip():
            try:
                years_back = int(year_input.strip())
                if years_back > 0:
                    year_limit = current_year - years_back
                    print(f"Refreshing metadata for files from {year_limit} onwards...")
                else:
                    print("Invalid input. Refreshing all metadata...")
            except ValueError:
                print("Invalid input. Refreshing all metadata...")
        else:
            print("Refreshing all metadata...")
        
        # Get list of MAL IDs that we actually have files for
        mal_ids_in_directory = set()
        for filename in directory_files:
            file_data = get_file_metadata_by_name(filename) or {}
            mal_id = file_data.get('mal')
            if mal_id and mal_id.isdigit():
                mal_ids_in_directory.add(mal_id)
        
        # Filter anime_metadata to only include entries we have files for
        entries_to_refresh = []
        for mal_id in mal_ids_in_directory:
            if mal_id in anime_metadata:
                data = anime_metadata[mal_id]
                season = data.get("season", "")
                
                # Check year limit if specified
                if year_limit is None:
                    entries_to_refresh.append((mal_id, data))
                else:
                    # Extract year from season (e.g., "Spring 2023" -> 2023)
                    try:
                        season_year = int(season[-4:] if season and season[-4:].isdigit() else 0)
                        if season_year >= year_limit:
                            entries_to_refresh.append((mal_id, data))
                    except (ValueError, IndexError):
                        # If we can't parse the year, include it to be safe
                        entries_to_refresh.append((mal_id, data))
        
        total_to_refresh = len(entries_to_refresh)
        total_refreshed = 0
        
        print(f"Found {total_to_refresh} entries to refresh from your directory files...")
        
        for mal_id, data in entries_to_refresh:
            try:
                refresh_jikan_data(mal_id, data, label=f"[{total_refreshed + 1}/{total_to_refresh}]")
                total_refreshed += 1
                # time.sleep(delay)  # Delay to avoid API rate limits
            except Exception as e:
                print(f"\nError refreshing {mal_id}: {e}")
                total_refreshed += 1  # Still count it as processed

        print(f"\nMetadata refreshing complete! - Refreshed: {total_refreshed}/{total_to_refresh}")

    # Run in a separate thread so it doesn't freeze the UI
    threading.Thread(target=worker, args=(year_input,), daemon=True).start()

# =========================================
#        *METADATA DISPLAY
# =========================================

def move_new_files():
    for filename in playlist:
        data = get_metadata(filename)
        if not data:
            continue

        filepath = directory_files[filename]
        parent_dir = os.path.abspath(os.path.join(os.path.dirname(filepath), ".."))

        if is_game(data):
            dest_dir = os.path.join(parent_dir, "Games")
        else:
            season_info = data.get("season", "")
            if not season_info or " " not in season_info:
                print(f"Missing or malformed season for: {filename}")
                continue

            season, year_str = season_info.split(" ")
            try:
                year = int(year_str)
            except ValueError:
                print(f"Invalid year in season info: {season_info}")
                continue

            if year < 2000:
                decade = f"{str(year)[-2]}0s"  # e.g., 1995 → "90s"
                dest_dir = os.path.join(parent_dir, decade)
            else:
                dest_dir = os.path.join(parent_dir, str(year), season)

        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, filename)
        print(f"Moving {filename} → {dest_path}")
        shutil.move(filepath, dest_path)

def clear_metadata():
    """Function to clear metadata fields"""
    global list_loaded
    left_column.delete(1.0, tk.END)
    middle_column.delete(1.0, tk.END)
    if list_loaded != "playlist":
        list_set_loaded(None)
        right_column.delete(1.0, tk.END)

def open_mal_page(mal_id):
    url = f"https://myanimelist.net/anime/{mal_id}"
    webbrowser.open(url)

def anime_themes_video(filename):
    url = f"https://v.animethemes.moe/{filename}"
    webbrowser.open(url)

def open_anidb_page(anidb_id):
    url = f"https://anidb.net/anime/{anidb_id}"
    webbrowser.open(url)

def reset_metadata(filename = None):
    """Function to reset metadata and add filename"""
    toggleColumnEdit(True)
    clear_metadata()
    if filename is None:
        filename = currently_playing.get('filename')
    left_column.insert(tk.END, "FILE: ", "bold")
    left_column.insert(tk.END, f"{filename}", "white")
    if "[MAL]" not in filename and "[ID]" not in filename:
        if currently_playing.get("type") == "youtube":
            left_column.window_create(tk.END, window=tk.Button(left_column, text="[YT]", borderwidth=0, pady=0, command=lambda: webbrowser.open(currently_playing.get("data").get("url")), bg="black", fg="white"))
    left_column.insert(tk.END, "\n\n", "blank")
 
def update_metadata_queue(index):
    """Function to update metadata display asynchronously"""
    global updating_metadata
    if updating_metadata:
        root.after(100, update_metadata_queue, index)
    elif index == playlist["current_index"]:
        updating_metadata = True
        threading.Thread(target=update_metadata, daemon=True).start()

updating_metadata = False
def update_metadata():
    global updating_metadata
    try:
        filename = currently_playing.get("filename")
        if filename:
            button_seleted(tag_button, check_tagged(filename))
            button_seleted(favorite_button, check_favorited(filename))
            button_seleted(blind_mark_button, check_blind_mark(filename))
            button_seleted(peek_mark_button, check_peek_mark(filename))
            button_seleted(mute_peek_mark_button, check_mute_peek_mark(filename))
            data = currently_playing.get('data')
            reset_metadata()
            if data:
                add_single_data_line(left_column, data, "TITLE: ", 'title', False)
                add_field_total_button(left_column, get_all_matching_field("mal", data.get("mal")), True)
                add_single_data_line(left_column, data, "ENGLISH: ", 'eng_title', True)
                if data.get("synonyms"):
                    add_multiple_data_line(left_column, data, "SYNONYMS: ", "synonyms", True)
                if is_game(data):
                    add_single_data_line(left_column, data, "RELEASE DATE: ", "release", True)
                else:
                    add_single_data_line(left_column, data, "AIR: ", "aired", False)
                    add_single_data_line(left_column, data, ", ", "season", False, title_font="white")
                    add_field_total_button(left_column, get_all_matching_field("season", data.get("season")), blank=True)
                add_single_data_line(left_column, data, "SCORE: ", 'score', False)
                if not is_game(data):
                    add_single_data_line(left_column, data, " (#", 'rank', False, title_font="white")
                if data.get("platforms"):
                    left_column.insert(tk.END, " REVIEWS: ", "bold")
                    left_column.insert(tk.END, f"{f"{(data.get("reviews", 0) or 0):,}"} (#{data.get("popularity") or "N/A"})", "white")
                else:
                    left_column.insert(tk.END, ") ", "white")
                    left_column.insert(tk.END, "MEMBERS: ", "bold")
                    left_column.insert(tk.END, f"{f"{data.get("members") or 0:,}"} (#{data.get("popularity") or "N/A"})", "white")
                left_column.insert(tk.END, "\n\n", "blank")
                if data.get("platforms"):
                    add_multiple_data_line(left_column, data, "PLATFORMS: ", 'platforms', True)
                    add_single_data_line(left_column, data, "TYPE: ", 'type', False) 
                else:
                    left_column.insert(tk.END, "EPISODES: ", "bold")
                    left_column.insert(tk.END, f"{data.get("episodes") or "Airing"}", "white")
                    add_single_data_line(left_column, data, " TYPE: ", 'type', False) 
                add_single_data_line(left_column, data, " SOURCE: ", 'source', True)
                left_column.insert(tk.END, "TAGS: ", "bold")
                tags = data.get('genres', []) + data.get('themes', []) + data.get('demographics', [])
                for index, tag in enumerate(tags):
                    left_column.insert(tk.END, f"{tag}", "white")
                    add_field_total_button(left_column, get_filenames_from_tag(tag), blank = False)
                    if index < len(tags)-1:
                        left_column.insert(tk.END, f", ", "white")
                left_column.insert(tk.END, "\n\n", "blank")
                left_column.insert(tk.END, "STUDIOS: ", "bold")
                for index, studio in enumerate(data.get("studios", [])):
                    left_column.insert(tk.END, f"{studio}", "white")
                    add_field_total_button(left_column, get_filenames_from_studio(studio), blank = False)
                    if index < len(data.get("studios"))-1:
                        left_column.insert(tk.END, f", ", "white")
                if data.get("series"):
                    left_column.insert(tk.END, "\n\n", "blank")
                    add_multiple_data_line(left_column, data, "SERIES: ", "series", False)
                    add_field_total_button(left_column, get_all_matching_field("series", data.get("series")))

                update_series_song_information(data, data.get("mal"))

            if list_loaded != "playlist":
                update_extra_metadata(data)
                
            toggleColumnEdit(False)

            if popout_currently_playing:
                update_popout_currently_playling(data)
    except Exception as e:
        print("Error updating metadata display: " + str(e))
    updating_metadata = False

def update_popout_currently_playling(data, clear=False):
    is_youtube = currently_playing.get("type") == "youtube"
    popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
    popout_currently_playing_extra.delete(1.0, tk.END)
    if not clear and popout_show_metadata and popout_show_currently_playing:
        if is_youtube:
            title = get_youtube_display_title(data)
        else:
            title = get_display_title(data)
        japanese_title = data.get("title")
        slug = data.get("slug")
        # Handle YouTube videos or missing slug gracefully
        if slug:
            theme = format_slug(slug)
        elif is_youtube:
            theme = "[YouTube]"
        else:
            theme = ""
        song = get_song_string(data)
        tags = get_tags_string(data)
        if is_youtube:
            studio = youtube_queue.get('name')
        else:
            studio = ", ".join(data.get("studios", []))
        type = data.get("type")
        source = data.get("source")
        marks = get_file_marks(currently_playing.get("filename", ""))
        # Fallbacks for YouTube or missing fields
        if data.get("platforms"):
            episodes = ", ".join(data.get("platforms"))
            members = f"Reviews: {(data.get("reviews", 0) or 0):,}"
            score = f"Score: {data.get("score")}" if data.get("score") else ""
        elif is_youtube:
            # YouTube video: show duration, views, likes, etc. if available
            duration = data.get("duration")
            if duration:
                episodes = f"{format_seconds(duration)}"
            else:
                episodes = "YouTube Video"
            members = f"Views: {data.get('view_count'):,}" if data.get('view_count') else ""
            score = f"Likes: {data.get('like_count'):,}" if data.get('like_count') else ""
        else:
            episodes =  data.get("episodes")
            if not episodes:
                episodes = "Airing"
            else:
                episodes = str(episodes) + " Episodes"
            members = f"Members: {data.get("members") or 0:,} (#{data.get("popularity") or "N/A"})"
            score = f"Score: {data.get("score")} (#{data.get("rank")})"
        if is_game(data):
            aired = data.get("release")
        elif is_youtube:
            aired = f"{datetime.strptime(data.get("upload_date"), "%Y%m%d").strftime("%Y-%m-%d")}"
        else:
            aired = data.get("season")
        popout_currently_playing.configure(text=title)
        if is_youtube:
            popout_currently_playing_extra.insert(tk.END, f"Uploaded by {studio} ({data.get('subscriber_count', 0):,} subscribers)\n{japanese_title}\n{members} | {score} | {aired} | {episodes}", "white")
        else:
            popout_currently_playing_extra.insert(tk.END, f"{marks}{theme}{overall_theme_num_display(currently_playing.get('filename'))} | {song} | {aired}\n{score} | {japanese_title} | {members}\n{studio} | {tags} | {episodes} | {type} | {source}", "white")
        popout_currently_playing.configure(fg="white")
    elif popout_show_metadata and not popout_show_currently_playing:
        # Show placeholder when metadata is on but currently playing is hidden
        popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
    else:
        popout_currently_playing.configure(text="", fg="white")
    popout_currently_playing_extra.config(state=tk.DISABLED)

def update_extra_metadata(data, column=None):
    if currently_playing.get("type") == "youtube":
        show_youtube_playlist()
        return
    if column is None:
        column = right_column
    column.config(state=tk.NORMAL, wrap="word")
    column.delete(1.0, tk.END)
    extra_data = [
        "synopsis", "characters", "episode_info", "tags", "links"
    ]
    column.insert(tk.END, "   ", "blank")
    if currently_playing.get("data"):
        for e in extra_data:
            if selected_extra_metadata == e:
                bg=HIGHLIGHT_COLOR
            else:
                bg="black"
            column.window_create(tk.END, window=tk.Button(column, text=(f"{e.upper().replace("EPISODE_INFO", "EPS").replace("CsHARACTERS", "")}"), font=("Arial", scl(11, "UI"), "bold", "underline"), command=lambda x=e: select_extra_metadata(x), padx=scl(2), bg=bg, fg="white"))
        column.insert(tk.END, "\n\n", "blank")
    if not currently_playing.get("data") or selected_extra_metadata == "links":
        data = currently_playing.get("data")
        filename = currently_playing.get("filename")
        _cached_id = f"{get_display_title(data)}-{data.get("season", "9999")[-4:]}"
        _cached_id_base = f"{get_base_title(title=get_display_title(data))}-{data.get("season", "9999")[-4:]}"
        _cached_clips_links = _cached_clips.get(_cached_id) or _cached_clips.get(_cached_id_base) or []
        _cached_ost_clips_links = _cached_ost_clips.get(_cached_id) or _cached_ost_clips.get(_cached_id_base) or []
        links = [
            ["FILE ACTIONS", "header", True],
            ["⎘COPY FILENAME", lambda: pyperclip.copy(filename), True],
            ["📁OPEN FOLDER", lambda: open_file_folder_by_filename(filename), True],
            ["✂️CUT BEFORE", lambda: cut_before_current_time(filename), ffmpeg_available],
            ["✂️CUT AFTER", lambda: cut_after_current_time(filename), ffmpeg_available],
            ["✏️RENAME", lambda: rename_file_by_filename(filename), True],
            ["🔄CONVERT", lambda: convert_file_format_by_filename(filename), ffmpeg_available],
            ["🔊EDIT VOLUME", lambda: edit_file_volume_by_filename(filename), ffmpeg_available],
            ["❌DELETE", lambda: delete_file_by_filename(filename), True],
            ["EXTERNAL SITES", "header", data and not is_game(data)],
            ["ANIMETHEMES", lambda: anime_themes_video(filename), data and "[MAL]" not in filename and "[ID]" not in filename and currently_playing.get("type") == "theme"],
            ["MYANIMELIST", lambda: open_mal_page(data.get("mal")), data.get("mal") and not is_game(data)],
            ["ANIDB", lambda: open_anidb_page(data.get("anidb")), not is_game(data) and data.get("anidb")],
            ["MEDIA", "header", data.get("trailer") or data.get("cover") or (OPENAI_API_KEY and data.get("synopsis"))],
            ["SHOW COVER", lambda: create_cover_popup(f"{get_display_title(data)} Cover", data.get("cover"))(), data.get("cover")],
            ["PLAY TRAILER", play_trailer, data.get("trailer")],
            ["TRIVIA", lambda: generate_anime_trivia(data, True), data and OPENAI_API_KEY],
            ["YOUTUBE CLIPS", "header", data and YOUTUBE_API_KEY],
            ["LOAD YOUTUBE CLIPS", load_random_clips, data and YOUTUBE_API_KEY and not _cached_clips_links],
            ["YOUTUBE CLIP LIST", stream_clip, _cached_clips_links],
            ["YOUTUBE OSTS", "header", data and YOUTUBE_API_KEY],
            ["LOAD YOUTUBE OSTS", lambda: load_random_clips(ost=True), data and YOUTUBE_API_KEY and not _cached_ost_clips_links],
            ["YOUTUBE OST LIST", stream_clip, _cached_ost_clips_links]
        ]
        def create_link_button(name, func, new_line=False, blank=True):
            b = tk.Button(
                column,
                text=name,
                command=func,
                padx=scl(2), pady=scl(1),
                bg="black", fg="white",
                font=("Arial", scl(12))
            )
            column.window_create(tk.END, window=b)
            if new_line:
                column.insert(tk.END, "\n", "blank")
            elif blank:
                column.insert(tk.END, " ")
        
        first_line = True
        for name, command, show in links:
            if show:
                if command == "header":
                    if first_line:
                        first_line = False
                    else:
                        column.insert(tk.END, "\n\n", "blank")
                    column.insert(tk.END, name + ":", "bold")
                    column.insert(tk.END, "\n", "blank")
                else:
                    if name == "YOUTUBE CLIP LIST" or name == "YOUTUBE OST LIST":
                        if name == "YOUTUBE CLIP LIST":
                            clips_to_load = _cached_clips_links
                        else:
                            clips_to_load = _cached_ost_clips_links
                        for clip in clips_to_load:
                            title, video_id, channel_title = clip
                            url = f"https://www.youtube.com/watch?v={video_id}"
                            create_link_button(
                                "▶",
                                lambda v=video_id, t=title, c=channel_title: command(v, t, c),
                                blank=False
                            )
                            create_link_button(
                                "🔗",
                                lambda u=url: webbrowser.open(u),
                                blank=False
                            )
                            column.insert(tk.END, f"{title} by {channel_title}\n", "white")
                    else:
                        create_link_button(name, command)
    elif not data.get(selected_extra_metadata):
        column.insert(tk.END, f"No {selected_extra_metadata.capitalize().replace("_info", "s")} data found.", "white")
    elif selected_extra_metadata == "synopsis":
        add_single_data_line(column, data, "", 'synopsis')
    elif selected_extra_metadata == "characters":
        groups = {
            "main": [],
            "secondary": [],
            "appears": []
        }

        for char in data.get("characters", []):
            role = char[0]
            name = char[1]
            image = char[2]
            gender = char[3] if len(char) > 3 else "Unknown"
            desc = char[4] if len(char) > 4 else ""

            # Store full character info
            entry = (name, image, gender, desc)

            if role == "m":
                groups["main"].append(entry)
            elif role == "s":
                groups["secondary"].append(entry)
            else:
                groups["appears"].append(entry)

        def create_image_popup(name, image_filename, gender, desc):
            def _popup():
                popup = tk.Toplevel()
                popup.title(name)
                popup.configure(bg="black")
                
                # Name
                tk.Label(popup, text=name, font=("Arial", scl(20), "bold", "underline"), bg="black", fg="white", anchor="center").pack(anchor="center", pady=(0, 0))

                # Load image
                tk_img = load_image_from_url("https://cdn-eu.anidb.net/images/main/" + image_filename, size=(scl(700), scl(700)))
                label = tk.Label(popup, image=tk_img, bg="black")
                label.image = tk_img
                label.pack(pady=scl(10))

                # Info section
                info_frame = tk.Frame(popup, bg="black")
                info_frame.pack(padx=scl(20), pady=(0, scl(20)), fill="both", expand=True)

                new_desc = f"Gender: {gender.capitalize()}. {desc.strip()}"
                if new_desc.strip():
                    tk.Label(info_frame, text="DESCRIPTION:", font=("Arial", scl(15), "bold", "underline"), bg="black", fg="white", anchor="w").pack(anchor="w", pady=(scl(10), 0))
                    tk.Label(info_frame, text=new_desc.strip(), font=("Arial", scl(15)), wraplength=scl(700), justify="left", bg="black", fg="white", anchor="w").pack(anchor="w")

            return _popup

        headers = [
            ("Main Characters", groups["main"]),
            ("Supporting Characters", groups["secondary"]),
            ("Also Appears", groups["appears"]),
        ]

        for header, char_list in headers:
            if not char_list:
                continue
            column.insert(tk.END, header.upper() + ":\n", "bold")
            for name, image, gender, desc in sorted(char_list, key=lambda x: x[0].lower()):
                b = tk.Button(
                    column,
                    text=name,
                    command=create_image_popup(name, image, gender, desc),
                    padx=2, pady=1,
                    bg="black", fg="white",
                    font=("Arial", scl(12))
                )
                column.window_create(tk.END, window=b)
                column.insert(tk.END, " ")
            column.insert(tk.END, "\n", "blank")
    elif selected_extra_metadata == "episode_info":
        episodes = sorted(data.get("episode_info", []), key=lambda x: x[0])  # Sort by episode number
        for num, title in episodes:
            column.insert(tk.END, f"EPISODE {num}: ", "bold")
            column.insert(tk.END, f"{title}\n", "white")
    elif selected_extra_metadata == "tags":
        tags = sorted(data.get("tags", []), key=lambda x: (-x[1], x[0].lower()))  # Sort by score descending, then name
        display_tags = []
        for tag, score in tags:
            if score > 0:
                display = f"{tag} ({score})"
            else:
                display = tag
            display_tags.append(display.capitalize())
        column.insert(tk.END, f"{", ".join(display_tags)}", "white")
        column.insert(tk.END, ".", "white")
    column.config(state=tk.DISABLED, wrap="word")
    column.config(state=tk.DISABLED, wrap="word")

selected_extra_metadata = "synopsis"
def select_extra_metadata(extra_metadata):
    global selected_extra_metadata
    selected_extra_metadata = extra_metadata
    update_extra_metadata(currently_playing.get("data"))

def create_cover_popup(title, cover_url):
    def _popup():
        try:
            popup = tk.Toplevel()
            popup.title(title)
            popup.configure(bg="black")

            # Title
            tk.Label(
                popup, text=title, font=("Arial", 18, "bold", "underline"),
                bg="black", fg="white"
            ).pack(pady=(10, 0))

            # Load cover image
            response = requests.get(cover_url)
            img_data = response.content
            pil_image = Image.open(BytesIO(img_data))
            pil_image.thumbnail((700, 800))

            cover_img = ImageTk.PhotoImage(pil_image)
            label = tk.Label(popup, image=cover_img, bg="black")
            label.image = cover_img  # Keep reference
            label.pack(pady=10)

        except Exception as e:
            messagebox.showerror("Image Load Error", f"Could not load image: {e}")

    return _popup

def update_series_song_information(data, mal):
    middle_column.config(state=tk.NORMAL)
    middle_column.delete("1.0", tk.END)
    if not data.get("series"):
        update_song_information(data, mal)
    else:
        all_series_themes = get_all_theme_from_series(data)
        if len(all_series_themes) == 1:
            update_song_information(data, mal)
        else:
            index = 0
            for anime_id, anime in all_series_themes:
                index += 1
                middle_column.insert(tk.END, f"{get_display_title(anime)} [{anime.get("type")} / {anime.get("season")}]:\n", "bold underline")
                if anime_id == data.get("mal"):
                    slug = data.get("slug")
                else:
                    slug = "SKIP"
                update_song_information(anime, mal, slug)
                if index < len(all_series_themes):
                    middle_column.insert(tk.END, "\n", "blank")
    middle_column.config(state=tk.DISABLED)

def update_song_information(data, mal, slug=None):
    openingAdded = False
    endingAdded = False
    extra_scroll = 0
    max_scroll = 3
    if not slug:
        slug = data.get("slug")
    theme_list = data.get("songs", [])
    for index, theme in enumerate(theme_list):
        if not openingAdded and theme["type"] == "OP":
            openingAdded = True
            middle_column.insert(tk.END, "OPENINGS:\n", "bold")
        elif not endingAdded and theme["type"] == "ED":
            endingAdded = True
            middle_column.insert(tk.END, "ENDINGS:\n", "bold")
        version_count = add_op_ed(theme, middle_column, slug, data.get("title"), mal)
        if (extra_scroll and extra_scroll < max_scroll) or theme.get("slug") == slug:
            extra_scroll += 1 + (version_count // 4)
            middle_column.see("end-1c")
        if index < len(theme_list) - 1:
            middle_column.insert(tk.END, "\n", "blank")

def up_next_text():
    update_up_next_display(right_top)
    if popout_up_next and popout_show_metadata:
        update_up_next_display(popout_up_next)
    # Refresh list display to adjust button count based on right_top content
    if list_loaded:
        # Small delay to ensure text widget is fully updated
        root.after(10, refresh_current_list)

reroll_button = None
def update_up_next_display(widget, clear=False):
    global reroll_button
    widget.config(state=tk.NORMAL, wrap="word")
    widget.delete(1.0, tk.END)
    # Don't show up-next if metadata is not enabled
    if not popout_show_metadata:
        widget.config(height=0)
        widget.config(state=tk.DISABLED)
        return
    # Show placeholder if not showing up-next or if cleared
    PLACEHOLDER_TEXT = "NEXT: CLICK TO SHOW/HIDE"
    if not popout_show_up_next:
        widget.config(height=1)
        widget.insert(tk.END, PLACEHOLDER_TEXT, "center")
        widget.config(state=tk.DISABLED)
        return
    if clear:
        widget.config(height=1)
        widget.insert(tk.END, PLACEHOLDER_TEXT, "center")
        widget.config(state=tk.DISABLED)
        return
    widget.config(height=0)
    if not clear:
        is_popout = widget == popout_up_next
        if not is_docked() or is_popout:
            if playlist.get("infinite", False) and playlist["current_index"] == len(playlist["playlist"]) - 2:
                reroll_button = tk.Button(
                        widget, text="🔄", font=("Arial", 11, "bold"), borderwidth=0,
                        pady=0, command=refetch_next_track, bg="black", fg="white"
                    )
                if is_popout:
                    popout_buttons_by_name["reroll"].configure(
                        text="RE-ROLL\nNEXT 🔄",
                        command=refetch_next_track
                    )
                else:
                    widget.window_create(
                        tk.END,
                        window=reroll_button
                    )
            else:
                if is_popout:
                    popout_buttons_by_name["reroll"].configure(
                        text="",
                        command=lambda: None
                    )
                reroll_button = None
            if not is_popout:
                widget.insert(tk.END, "NEXT: ", "bold")

            next_up_text = "End of playlist"
            if playlist["current_index"] + 1 < len(playlist["playlist"]):
                try:
                    playlist_entry = playlist["playlist"][playlist["current_index"] + 1]
                    next_filename = get_clean_filename(playlist_entry)
                    next_up_data = get_metadata(next_filename)
                    version_num = next_up_data.get("version")
                    if version_num and version_num != 1:
                        version_num = f"v{version_num}"
                    else:
                        version_num = ""
                    if lightning_queue and lightning_queue[0] == next_filename and variety_light_mode_enabled:
                        widget.insert(tk.END, f"[{lightning_queue[1].upper()}] ", "white")
                    next_up_text = (
                        f"{get_file_marks(next_filename)}{get_display_title(next_up_data)}\n"
                        f"{format_slug(next_up_data.get('slug'))}{version_num} | {next_up_data.get('members') or 0:,} "
                        f"(#{next_up_data.get('popularity')}) | {next_up_data.get('season')}"
                    )
                    if is_popout:
                        next_up_text = f"NEXT: {next_up_text.replace("\n", " - ")}"
                except Exception:
                    playlist_entry = playlist["playlist"][playlist["current_index"] + 1]
                    next_up_text = get_clean_filename(playlist_entry)
            widget.insert(tk.END, f"{next_up_text}", "white")
            adjust_up_next_height(widget, is_popout)
            widget.config(state=tk.DISABLED)
            return
    widget.config(state=tk.DISABLED, wrap="word")

def adjust_up_next_height(widget, is_popout):
    widget.config(state=tk.NORMAL, wrap="word")
    total_lines = widget.count("1.0", "end", "displaylines")[0]
    if is_popout:
        total_lines = total_lines - 1
    widget.config(state=tk.NORMAL, height=total_lines + 1, wrap="word")
    widget.config(state=tk.DISABLED, wrap="word")

def get_display_title(data):
    return data.get("eng_title") or data.get("title") or "No Title Found"

def is_game(data):
    return data.get("type") == "Game" or data.get("type") == "Visual Novel" or data.get("platforms")

def add_field_total_button(column, group, blank = True, show_count=True, button_text=None):
    count = len(group)
    if count > 0:
        if not button_text:
            if show_count:
                button_text = f"[{count}]"
            else:
                button_text = "▶"
        btn = tk.Button(column, text=button_text, borderwidth=0, pady=0, command=lambda: show_field_themes(group=group), bg="black", fg="white", font=("Arial", scl(11), "bold"))
        column.window_create(tk.END, window=btn)
    if blank:
        column.insert(tk.END, "\n\n", "blank")

def get_all_matching_field(field, match):
    filenames = []
    for filename in directory_files:
        file_data = get_metadata(filename)
        if file_data:
            file_field = file_data.get(field, "")
            if file_field and file_field == match:
                filenames.append(filename)

    return sorted(filenames)

def get_all_theme_from_series(data):
    target_series = data.get("series")

    if isinstance(target_series, str):
        target_series = [target_series]

    # Step 1: Find all anime from same series
    related_anime = []
    for anime_id, anime in anime_metadata.items():
        if anime.get("series") == target_series:
            related_anime.append((anime_id, anime))

    # Step 2: Sort anime by release (season/year)
    def sort_key(anime):
        season = anime.get("season", "")
        year = int(season[-4:]) if season and season[-4:].isdigit() else 9999
        season_order = ["Winter", "Spring", "Summer", "Fall"]
        for i, s in enumerate(season_order):
            if s in season:
                return (year, i)
        return (year, 99)

    related_anime.sort(key=lambda x: sort_key(x[1]))
    return related_anime

def get_overall_theme_number(filename):
    """Returns the overall opening/ending number across the series based on the filename."""
    data = get_metadata(filename)
    if not data or is_game(data):
        return None
    
    target_slug = data.get("slug")
    slug_extra = get_slug_extra(target_slug)
    theme_type = target_slug[:2]  # "OP" or "ED"
    if theme_type not in ["OP", "ED"]:
        return None
    
    target_series = data.get("series")
    mal_id = data.get("mal")
    if not mal_id or not target_series or not target_slug:
        return None
    
    related_anime = get_all_theme_from_series(data)
    
    is_parody = "Parody" in data.get("themes", [])

    def clean_title(title):
        for end in [" (TV)", " 1st", ":", " no Kajitsu"]:
            title = title.split(end)[0]
        return title

    # Step 3: Count themes of the same type, stopping at the target
    overall_index = 0
    decimal = 0
    base_title = None
    display_base_title = None
    for anime_id, anime in related_anime:
        anime_title = clean_title(anime.get("title"))
        anime_display_title = clean_title(get_display_title(anime))
        if (has_same_start(data.get("title"), anime.get("title"), length=1) or has_same_start(get_display_title(data), get_display_title(anime), length=1)) and not is_game(anime) and (is_parody == ("Parody" in anime.get("themes")) and data.get("type") == anime.get("type")):
            if not base_title or not display_base_title:
                if anime_title in data.get("title"):
                    base_title = anime_title
                elif anime_display_title in get_display_title(data):
                    display_base_title = anime_display_title
                elif not base_title or display_base_title:
                    continue
            if (base_title and base_title in anime_title) or (display_base_title and display_base_title in anime_display_title):
                for song in anime.get("songs", []):
                    if song["type"] == theme_type:
                        if not (slug_extra == get_slug_extra(song.get("slug"))):
                            continue
                        elif (song.get("overlap") == "Over") or song.get("special"):
                            decimal += 0.1
                        elif song.get("skip"):
                            continue
                        else:
                            overall_index += 1
                            decimal = 0
                        if anime_id == mal_id and song["slug"] == target_slug:
                            return overall_index+decimal

    return None

def get_all_theme_type(anime, type):
    songs = []
    for song in anime.get("songs", []):
        if song["type"] == type:
            songs.append(song)
    return songs

def get_slug_extra(slug):
    slug_extra = ""
    if "-" in slug:
        slug_extra = slug.split("-")[1]
    elif "_" in slug:
        slug_extra = slug.split("_")[1]
    return slug_extra

def has_same_start(s1, s2, length=3):
    return s1[:length].lower() == s2[:length].lower()

def get_filenames_from_artist(match):
    filenames = []
    for filename in directory_files:
        file_data = get_metadata(filename)
        if file_data:
            for theme in file_data.get("songs", []) or []:
                if file_data.get("slug") == theme.get("slug"):
                    for artist in theme.get("artist", []) or []:
                        if artist == match:
                            filenames.append(filename)

    return sorted(filenames)

def get_filenames_from_studio(match):
    filenames = []
    for filename in directory_files:
        file_data = get_metadata(filename)
        if file_data:
            for studio in file_data.get("studios", []) or []:
                if studio == match:
                    filenames.append(filename)

    return sorted(filenames)

def get_filenames_from_tag(match):
    filenames = []
    for filename in directory_files:
        file_data = get_metadata(filename)
        if file_data:
            for tag in file_data.get('genres', []) + file_data.get('themes', []) + file_data.get('demographics', []):
                if tag == match:
                    filenames.append(filename)
                    break

    return sorted(filenames)

def get_filenames_from_year(match):
    filenames = []
    for filename in directory_files:
        file_data = get_metadata(filename)
        if match in file_data.get("season", ""):
            filenames.append(filename)        

    return sorted(filenames)

def add_multiple_data_line(column, data, title, get, blank = True):
    column.insert(tk.END, title, "bold")
    count = 0
    for item in data.get(get, []):
        count += 1
        name = item
        if count > 1:
            name = ", " + name 
        column.insert(tk.END, name, "white")
    if count == 0:
        column.insert(tk.END, "N/A", "white")
    if blank:
        column.insert(tk.END, "\n\n", "blank")

def add_single_data_line(column, data, title, get, blank = True, title_font="bold"):
    column.insert(tk.END, title, title_font)
    if data:
        column.insert(tk.END, f"{data.get(get, "N/A")}", "white")
    else:
        column.insert(tk.END, "N/A", "white")
    if blank:
        column.insert(tk.END, "\n\n", "blank")

def overall_theme_num_display(filename):
    overall_num = get_overall_theme_number(filename)
    data = get_metadata(filename)
    if overall_num and str(overall_num) not in data.get("slug"):
        return " (" + str(overall_num) + ")"
    else:
        return ""

def add_op_ed(theme, column, slug, title, mal_id):
    theme_slug = theme.get("slug")
    song_title = theme.get("title")
    artist_list = theme.get("artist", [])
    episodes = theme.get("episodes")
    format = "white"
    versions = theme.get("versions", [])
    no_file_icon = "⁃"
    no_versions_icon = "    "

    if theme_slug == slug:
        format = "highlight"

    # Show play button at top for themes without versions OR with only one version
    if not versions or len(versions) == 1:
        # For single version, use the version-specific filename, otherwise use theme filename
        if len(versions) == 1:
            filename = get_theme_filename(title, theme_slug, versions[0].get('version'))
        else:
            filename = get_theme_filename(title, theme_slug)
            
        # ▶ button or fallback
        if filename:
            column.window_create(tk.END, window=tk.Button(column, text="▶", borderwidth=0, pady=0, command=lambda: play_video_from_filename(filename), bg="black", fg="white"))
            column.insert(tk.END, get_file_marks(filename), format)
        else:
            column.insert(tk.END, no_file_icon, format)
    else:
        # Multiple versions - no play button at top
        column.insert(tk.END, no_file_icon, format)
    # Song label - use white for theme title (highlighting is per-version for multiple versions)
    overall_display = ""
    filename = get_theme_filename(title, theme_slug)  # Initialize filename variable
    
    overall_display = overall_theme_num_display(filename)
    # For themes without versions, check if theme matches slug for highlighting
    if theme_slug == slug:
        format = "highlight"
    column.insert(tk.END, f"{theme_slug}{overall_display}: {song_title}\n", format)

    # Artist section - use same format as theme title
    column.insert(tk.END, f"by: ", format)
    if not artist_list:
        column.insert(tk.END, f"N/A ", format)

        # Add [+] button to insert missing artist
        def prompt_and_add_artist():
            artist_input = simpledialog.askstring("Add Artist", "Enter artist name(s)(Use '[AND]' to separate multiple artists.):")
            if not artist_input:
                return
            
            artist_input = artist_input.split("[AND]")

            # Update original metadata (for display)
            theme["artist"] = artist_input

            # Update override metadata
            anime_entry_override = anime_metadata_overrides.setdefault(mal_id, {})
            for entry in anime_metadata[mal_id]["songs"]:
                if entry.get("slug") == theme_slug:
                    break
            else:
                messagebox.showerror("Error", "Could not find original theme entry.")
                return

            # Copy the original song and override the artist
            new_song = {"slug": theme_slug}
            new_song["artist"] = artist_input

            # Replace or insert the song into the override
            override_songs = anime_entry_override.setdefault("songs", [])
            for i, s in enumerate(override_songs):
                if s.get("slug") == theme_slug:
                    override_songs[i] = new_song
                    break
            else:
                override_songs.append(new_song)

            # Also update main metadata live
            for s in anime_metadata[mal_id]["songs"]:
                if s.get("slug") == theme_slug:
                    s["artist"] = [artist_input]
            save_metadata_overrides()
            save_metadata()
            filename = currently_playing.get("filename")
            if filename:
                update_series_song_information(get_metadata(filename), mal_id)

        column.window_create(tk.END, window=tk.Button(column, text="[ADD ARTIST]", command=prompt_and_add_artist, padx=2, bg="black", fg="white"))
    else:
        for index, artist in enumerate(artist_list):
            column.insert(tk.END, f"{artist}", format)
            add_field_total_button(column, get_filenames_from_artist(artist), blank=False)
            if index < len(artist_list) - 1:
                column.insert(tk.END, ", ", format)

    # Versions or Episodes + Flags
    version_format = "white"
    if versions:
        # For single version, don't show individual play buttons since we have one at the top
        if len(versions) == 1:
            version_format = format
            version = versions[0]
            version_num = version.get('version')
            version_text = ""
            if version_num:
                version_text += f"v{version_num}: "
            if version.get('episodes'):
                version_text += f"(Eps: {version.get('episodes')})"
            
            # Add flags for this version
            flags = []
            if version.get("overlap") == "Over":
                flags.append("(OVERLAP)")
            if version.get("overlap") == "Transition":
                flags.append("(TRANSITION)")
            if version.get("spoiler"):
                flags.append("(SPOILER)")
            if version.get("nsfw"):
                flags.append("(NSFW)")

            if flags:
                version_text += f" {' '.join(flags)}"

            # Use the same format as the title for single version
            if version_text:
                column.insert(tk.END, f"\n{version_text}", format)
        else:
            # Multiple versions - display with individual play buttons
            for i, version in enumerate(versions):
                if i > 0:
                    column.insert(tk.END, f"\n", version_format)
                else:
                    column.insert(tk.END, f"\n", format)
                # Determine if this specific version should be highlighted
                version_num = version.get('version')
                version_filename = get_theme_filename(title, theme_slug, version_num, need_version=True)
                if version_num == 1 and not version_filename:
                    version_filename = get_theme_filename(title, theme_slug, None, need_version=True)
                if version_num == None:
                    version_num = 1

                # Check if this version matches the currently playing file
                version_format = "white"
                if theme_slug == slug and version_filename:
                    try:
                        current_filename = currently_playing.get('filename') if 'currently_playing' in globals() else None
                        if current_filename == version_filename:
                            version_format = "highlight"
                    except:
                        pass
                
                if version_filename:
                    column.window_create(tk.END, window=tk.Button(column, text="▶", borderwidth=0, pady=0, command=lambda f=version_filename: play_video_from_filename(f), bg="black", fg="white"))
                    column.insert(tk.END, get_file_marks(version_filename), version_format)
                else:
                    column.insert(tk.END, no_versions_icon, version_format)

                # Version details for multiple versions
                version_text = ""
                if version_num:
                    version_text += f"v{version_num}"
                
                # Add flags for this version
                flags = []
                if version.get("overlap") == "Over":
                    flags.append("(OVERLAP)")
                if version.get("overlap") == "Transition":
                    flags.append("(TRANSITION)")
                if version.get("spoiler"):
                    flags.append("(SPOILER)")
                if version.get("nsfw"):
                    flags.append("(NSFW)")

                if version.get("episodes") or flags:
                    version_text += ":"
                    if version.get('episodes'):
                        version_text += f" (Eps: {version.get('episodes')})"
                    if flags:
                        version_text += f" {' '.join(flags)}"

                column.insert(tk.END, f"{version_text}", version_format)
        column.insert(tk.END, f"", "white")
    else:
        # Backwards compatible: display episodes if no versions available
        # Use same format as determined for the theme title
        version_text = ""
        if episodes:
            version_text += f"(Eps: {episodes})"
        if theme.get("overlap") == "Over":
            version_text += f" (OVERLAP)"
        if theme.get("overlap") == "Transition":
            version_text += f" (TRANSITION)"
        if theme.get("spoiler"):
            version_text += f" (SPOILER)"
        if theme.get("nsfw"):
            version_text += f" (NSFW)"
        if version_text:
            column.insert(tk.END, f"\n{version_text}", format)
    
    if theme.get("special"):
        column.insert(tk.END, f" (SPECIAL)", format)

    column.insert(tk.END, f"\n", version_format)
    return len(versions)

def get_file_marks(filename):
    marks = ""
    if check_new(filename):
        marks = marks + "-NEW- "
    if check_favorited(filename):
        marks = marks + "❤"
    if check_tagged(filename):
        marks = marks + "❌"
    if check_blind_mark(filename):
        marks = marks + "👁"
    if check_peek_mark(filename):
        marks = marks + "👀"
    if check_mute_peek_mark(filename):
        marks = marks + "🔇"
    return marks

def get_theme_filename(title, slug, version=None, need_version=False):
    for filename in directory_files:
        data = get_metadata(filename)
        if data.get("title") == title and data.get("slug") == slug:
            if (version is None and (data.get("version") is None or not need_version)) or (data.get("version") == version):
                return filename
    return None

def play_video_from_filename(filename):
    global search_queue
    search_queue = filename
    play_video()

def toggleColumnEdit(toggle):
    if toggle:
        # Allow editing
        left_column.config(state=tk.NORMAL, wrap="word")
        middle_column.config(state=tk.NORMAL, wrap="word")
        right_column.config(state=tk.NORMAL, wrap="word")
    else:
        # Do not allow editing
        left_column.config(state=tk.DISABLED, wrap="word")
        middle_column.config(state=tk.DISABLED, wrap="word")
        right_column.config(state=tk.DISABLED, wrap="word")

# =========================================
#            *YOUTUBE VIDEOS
# =========================================

youtube_queue = None
def get_youtube_duration(data):
    start = data.get("start")
    end = data.get("end")
    length = data.get('duration')
    if end == 0:
        end = length
    duration = round(end-start)
    return duration

def get_youtube_metadata_from_index(index=None, key_id=None):
    for idx, (key, value) in enumerate(youtube_metadata.get("videos", {}).items()):
        if key_id and key_id == key or idx == index:
            value["url"] = key
            channel_info = youtube_metadata.get("channels", {}).get(value.get("channel_id"), {
                "name": "N/A",
                "subscriber_count": 0
            })
            return value | channel_info

def unload_youtube_video():
    global youtube_queue
    if youtube_queue:
        toggle_coming_up_popup(False, get_youtube_display_title(youtube_queue))
    # Unhighlight the YouTube queue button if it exists
    try:
        if 'YOUTUBE QUEUE' in popout_buttons_by_name:
            button = popout_buttons_by_name['YOUTUBE QUEUE']
            button_seleted(button, False)
        if "YOUTUBE DROPDOWN" in popout_buttons_by_name:
            popout_buttons_by_name['YOUTUBE DROPDOWN'].set("YOUTUBE VIDEOS")
    except Exception:
        pass
    youtube_queue = None

def get_youtube_display_title(data):
    return data.get("custom_title") or data.get("title")

def stream_youtube(youtube_url):
    """Streams a YouTube video in VLC using yt-dlp to get a direct URL."""
    if current_vout != 'opengl':
        set_vout(vout_module='opengl')
    media = instance.media_new(youtube_url)
    player.set_media(media)
    player.play()
    check_youtube_video_playing()

def check_youtube_video_playing():
    if player.is_playing():
        global video_stopped
        video_stopped = False
        player.set_fullscreen(False)
        player.set_fullscreen(True)
    else:
        root.after(1000, check_youtube_video_playing)

_youtube_playlist = {}
def show_youtube_playlist(update = False):
    global _youtube_playlist
    downloaded_videos = {}
    
    # Check both local youtube folder and external files
    for video_id, video in youtube_metadata.get("videos", {}).items():
        filename = video["filename"]
        
        # Check if file exists in youtube folder
        if os.path.exists(os.path.join("youtube", filename)):
            downloaded_videos[video_id] = video
        else:
            # Check if it exists as an external file in current playlist
            for playlist_entry in playlist.get("playlist", []):
                if (os.path.isabs(playlist_entry) and 
                    os.path.basename(playlist_entry) == filename and 
                    os.path.exists(playlist_entry)):
                    downloaded_videos[video_id] = video
                    break

    # Sort by date_added (newest first), then by upload_date as fallback
    def get_sort_key(item):
        video_id, video = item
        # Try to get date_added first, fallback to upload_date
        date_added = video.get("date_added")
        if date_added:
            try:
                return datetime.fromisoformat(date_added)
            except (ValueError, TypeError):
                pass
        
        # Fallback to upload_date
        upload_date = video.get("upload_date", "")
        if upload_date:
            try:
                return datetime.strptime(upload_date, "%Y%m%d")
            except (ValueError, TypeError):
                pass
        
        # If no valid dates, use a very old date so it appears last
        return datetime(1900, 1, 1)
    
    # Sort and convert back to dict
    sorted_videos = sorted(downloaded_videos.items(), key=get_sort_key, reverse=True)
    downloaded_videos = dict(sorted_videos)

    for index, (key, value) in enumerate(downloaded_videos.items()):
        value['index'] = index
    if youtube_queue:
        selected = youtube_queue.get('index', -1) or -1
    else:
        selected = -1
    _youtube_playlist = downloaded_videos
    show_list("youtube", right_column, downloaded_videos, get_youtube_title, load_youtube_video, selected, update)

def get_youtube_title(key, value):
    return f"[{str(format_seconds(get_youtube_duration(value)))}]{get_youtube_display_title(value)}"

def load_youtube_video(index):
    global youtube_queue
    video = get_youtube_metadata_from_index(key_id=list(_youtube_playlist.keys())[index])
    if video and youtube_queue != video:
        unload_youtube_video()
        youtube_queue = video
        title = get_youtube_display_title(youtube_queue)
        try:
            image = load_image_from_url(youtube_queue.get('thumbnail'), size=(400, 225))
        except:
            image = None
        details = (
            "Created by: " + youtube_queue.get("name") + " (" + str(f"{youtube_queue.get("subscriber_count"):,}") + " subscribers)" + "\n"
            "Uploaded: " + str(f"{datetime.strptime(youtube_queue.get("upload_date"), "%Y%m%d").strftime("%Y-%m-%d")}") + " | Duration: " + str(format_seconds(get_youtube_duration(youtube_queue))) + " mins\n\n"
            "1 PT for the first correct answer."
        )
        if player.is_playing():
            toggle_coming_up_popup(True, title, details, image, queue=True)
        else:
            play_video()
    else:
        unload_youtube_video()
    show_youtube_playlist(True)

def update_youtube_metadata(data=None):
    global youtube_queue
    # Use provided data or fall back to youtube_queue
    youtube_data = data or youtube_queue
    if not youtube_data:
        return
        
    insert_column_line(left_column, "TITLE: ", get_youtube_display_title(youtube_data))
    insert_column_line(left_column, "FULL TITLE: ", youtube_data.get('title'))
    insert_column_line(left_column, "UPLOAD DATE: ", f"{datetime.strptime(youtube_data.get('upload_date'), "%Y%m%d").strftime("%Y-%m-%d")}")
    insert_column_line(left_column, "VIEWS: ", f"{youtube_data.get('view_count'):,}")
    insert_column_line(left_column, "LIKES: ", f"{youtube_data.get('like_count'):,}")
    insert_column_line(left_column, "CHANNEL: ", youtube_data.get('name'))
    insert_column_line(left_column, "SUBSCRIBERS: ", f"{youtube_data.get('subscriber_count'):,}")
    insert_column_line(left_column, "DURATION: ", str(format_seconds(get_youtube_duration(youtube_data))) + " mins")
    insert_column_line(middle_column, "DESCRIPTION: ", youtube_data.get('description'))
    show_youtube_playlist()
    if popout_currently_playing:
        update_popout_currently_playling(youtube_queue)

def insert_column_line(column, title, data):
    column.insert(tk.END, title, "bold")
    column.insert(tk.END, f"{data}", "white")
    column.insert(tk.END, "\n\n", "blank")

def save_youtube_metadata():
    """Ensures the metadata folder exists before saving metadata file."""
    metadata_folder = os.path.dirname(YOUTUBE_METADATA_FILE)  # Get the folder path

    # Create the folder if it does not exist
    if not os.path.exists(metadata_folder):
        os.makedirs(metadata_folder)

    with open(YOUTUBE_METADATA_FILE, "w") as f:
        json.dump(youtube_metadata, f, indent=4)

def load_youtube_metadata():
    global youtube_metadata
    if os.path.exists(YOUTUBE_METADATA_FILE):
        with open(YOUTUBE_METADATA_FILE, "r") as f:
            youtube_metadata = json.load(f)
            print("Loaded metadata for " + str(len(youtube_metadata.get("videos", []))) + " youtube videos...")
        
        # Migration: Add date_added field to existing videos that don't have it
        migration_needed = False
        for video_id, video in youtube_metadata.get("videos", {}).items():
            if "date_added" not in video:
                # Use upload_date as fallback, or current date if neither exists
                upload_date = video.get("upload_date", "")
                if upload_date:
                    try:
                        # Convert upload_date to datetime and use as date_added
                        upload_datetime = datetime.strptime(upload_date, "%Y%m%d")
                        video["date_added"] = upload_datetime.isoformat()
                    except (ValueError, TypeError):
                        # If upload_date is invalid, use current date
                        video["date_added"] = datetime.now().isoformat()
                else:
                    # No upload_date, use current date
                    video["date_added"] = datetime.now().isoformat()
                migration_needed = True
        
        # Save the metadata if migration was needed
        if migration_needed:
            save_youtube_metadata()
        
        return True
    return False

youtube_editor_window = None
def open_youtube_editor():
    global youtube_editor_window, youtube_page_offset
    
    # Pagination variables
    if 'youtube_page_offset' not in globals():
        youtube_page_offset = 0
    
    VIDEOS_PER_PAGE = 10
    
    def youtube_editor_close():
        global youtube_editor_window, youtube_page_offset
        button_seleted(manage_youtube_button, False)
        manage_youtube_button.configure(text="➕")
        youtube_page_offset = 0
        youtube_editor_window.destroy()
        youtube_editor_window = None

    button_seleted(manage_youtube_button, True)
    manage_youtube_button.configure(text="❌")

    if youtube_editor_window:
        youtube_editor_close()
        return
    else:
        youtube_editor_window = tk.Toplevel()
        youtube_editor_window.title("YouTube Video Manager")
        youtube_editor_window.configure(bg=BACKGROUND_COLOR)
        youtube_editor_window.protocol("WM_DELETE_WINDOW", youtube_editor_close)
    
    font_big = ("Arial", 14)
    fg_color = "white"

    entry_widgets = []

    def refresh_ui():
        global youtube_page_offset
        for widget in youtube_editor_window.winfo_children():
            widget.destroy()
        entry_widgets.clear()
        
        active_videos = {k: v for k, v in youtube_metadata.get("videos", {}).items() if not v.get("archived")}

        # Sort by date_added (newest first), then by upload_date as fallback
        def get_sort_key_manager(item):
            video_id, video = item
            # Try to get date_added first, fallback to upload_date
            date_added = video.get("date_added")
            if date_added:
                try:
                    return datetime.fromisoformat(date_added)
                except (ValueError, TypeError):
                    pass
            
            # Fallback to upload_date
            upload_date = video.get("upload_date", "")
            if upload_date:
                try:
                    return datetime.strptime(upload_date, "%Y%m%d")
                except (ValueError, TypeError):
                    pass
            
            # If no valid dates, use a very old date so it appears last
            return datetime(1900, 1, 1)

        sorted_videos = sorted(active_videos.items(), key=get_sort_key_manager, reverse=True)
        
        # Calculate pagination
        total_videos = len(sorted_videos)
        total_pages = (total_videos + VIDEOS_PER_PAGE - 1) // VIDEOS_PER_PAGE if total_videos > 0 else 1
        current_page = (youtube_page_offset // VIDEOS_PER_PAGE) + 1
        
        # Ensure page offset is within bounds
        if youtube_page_offset >= total_videos and total_videos > 0:
            youtube_page_offset = max(0, total_videos - VIDEOS_PER_PAGE)
        
        # Get videos for current page
        start_idx = youtube_page_offset
        end_idx = min(start_idx + VIDEOS_PER_PAGE, total_videos)
        page_videos = sorted_videos[start_idx:end_idx]
        
        # Pagination controls (only if more than one page)
        header_row = 0
        if total_pages > 1:
            def page_prev():
                global youtube_page_offset
                if youtube_page_offset >= VIDEOS_PER_PAGE:
                    youtube_page_offset -= VIDEOS_PER_PAGE
                    refresh_ui()
            
            def page_next():
                global youtube_page_offset
                if youtube_page_offset + VIDEOS_PER_PAGE < total_videos:
                    youtube_page_offset += VIDEOS_PER_PAGE
                    refresh_ui()
            
            # Previous button
            prev_btn = tk.Button(youtube_editor_window, text="◀ PREV", font=font_big, bg="black", fg=fg_color, 
                                command=page_prev, state="normal" if current_page > 1 else "disabled")
            prev_btn.grid(row=0, column=0, padx=4, pady=6)
            
            # Page info
            page_label = tk.Label(youtube_editor_window, text=f"Page {current_page}/{total_pages} ({total_videos} total)", 
                                font=font_big, bg=BACKGROUND_COLOR, fg=fg_color)
            page_label.grid(row=0, column=1, columnspan=4, padx=8, pady=6)
            
            # Next button
            next_btn = tk.Button(youtube_editor_window, text="NEXT ▶", font=font_big, bg="black", fg=fg_color,
                                command=page_next, state="normal" if current_page < total_pages else "disabled")
            next_btn.grid(row=0, column=5, padx=4, pady=6)
            
            header_row = 1
        
        # Column headers
        headers = ["Video ID", "Channel", "Title", "Start", "End", "Actions"]
        for col, header in enumerate(headers):
            tk.Label(youtube_editor_window, text=header.upper(), font=font_big, bg=BACKGROUND_COLOR, fg=fg_color).grid(row=header_row, column=col, padx=8, pady=6)

        for display_idx, (video_id, video) in enumerate(page_videos):
            video_row = display_idx + header_row + 1
            row_widgets = []

            tk.Label(youtube_editor_window, text=video_id, font=font_big, fg=fg_color, bg=BACKGROUND_COLOR).grid(row=video_row, column=0, padx=4, pady=4)

            # Channel name
            channel_id = video.get("channel_id")
            channel_name = youtube_metadata.get("channels", {}).get(channel_id, {}).get("name", "Unknown")
            tk.Label(youtube_editor_window, text=channel_name, font=font_big, fg=fg_color, bg=BACKGROUND_COLOR, width=15, anchor="w").grid(row=video_row, column=1, padx=4, pady=4)

            # Title (Entry + Refresh Button)
            title_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)

            url = f"https://www.youtube.com/watch?v={video_id}"
            tk.Button(
                title_frame,
                text="🔗",  # Unicode refresh icon
                font=font_big,
                command=lambda u=url: webbrowser.open(u),
                bg="black",
                fg="white"
            ).pack(side="left")

            title_var = tk.StringVar(value=get_youtube_display_title(video))
            title_entry = tk.Entry(title_frame, textvariable=title_var, font=font_big, width=40, bg="#222", fg=fg_color, insertbackground=fg_color)
            title_entry.pack(side="left")

            def reset_title(event=None, var=title_var, v=video):
                var.set(v.get("title"))

            tk.Button(
                title_frame,
                text="⟳",  # Unicode refresh icon
                font=font_big,
                command=reset_title,
                bg="black",
                fg="white"
            ).pack(side="left")

            title_frame.grid(row=video_row, column=2, padx=4, pady=4)

            start_var = tk.StringVar(value=str(video.get("start", 0)))
            end_var = tk.StringVar(value=str(video.get("end", 0) or video.get("duration")))

            def set_now(var):
                var.set(int(projected_vlc_time / 1000))

            # Start time (Entry + NOW + REFRESH)
            start_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)
            start_entry = tk.Entry(start_frame, textvariable=start_var, font=font_big, width=4, justify="center", bg="#222", fg=fg_color, insertbackground=fg_color)
            start_entry.pack(side="left")

            tk.Button(
                start_frame,
                text="NOW",
                font=font_big,
                command=lambda v=start_var: set_now(v),
                bg="black",
                fg="white"
            ).pack(side="left", padx=2)

            tk.Button(
                start_frame,
                text="⟳",
                font=font_big,
                command=lambda v=start_var: v.set(0),
                bg="black",
                fg="white"
            ).pack(side="left")

            start_frame.grid(row=video_row, column=3, padx=4)

            # End time (Entry + NOW + REFRESH)
            end_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)
            end_entry = tk.Entry(end_frame, textvariable=end_var, font=font_big, width=4, justify="center", bg="#222", fg=fg_color, insertbackground=fg_color)
            end_entry.pack(side="left")

            tk.Button(
                end_frame,
                text="NOW",
                font=font_big,
                command=lambda v=end_var: set_now(v),
                bg="black",
                fg="white"
            ).pack(side="left")

            tk.Button(
                end_frame,
                text="⟳",
                font=font_big,
                command=lambda v=end_var, dur=video.get("duration", 0): v.set(int(dur)),
                bg="black",
                fg="white"
            ).pack(side="left")

            end_frame.grid(row=video_row, column=4, padx=4)

            # Determine if file is downloaded
            filepath = os.path.join("youtube", video["filename"])

            action_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)
            if os.path.exists(filepath):
                def play_youtube_video(vid):
                    save_all()
                    global youtube_queue
                    youtube_queue = get_youtube_metadata_from_index(key_id=vid)
                    play_video()

                # Show Archive/Delete buttons
                def archive_this(vid=video_id):
                    video = youtube_metadata["videos"][vid]
                    video["archived"] = True
                    video["archived_date"] = datetime.now().strftime("%Y-%m-%d")

                    # Ensure archive folder exists
                    archive_folder = os.path.join("youtube", "archive")
                    os.makedirs(archive_folder, exist_ok=True)

                    # Move the file
                    old_path = os.path.join("youtube", video.get("filename", ""))
                    new_path = os.path.join(archive_folder, video.get("filename", ""))

                    if os.path.exists(old_path):
                        try:
                            shutil.move(old_path, new_path)
                            print(f"Moved to archive: {new_path}")
                        except Exception as e:
                            print(f"Error archiving file: {e}")
                    save_youtube_metadata()
                    refresh_ui()
                # Play button
                tk.Button(action_frame, text="▶", font=font_big, bg="green", fg="white", command=lambda vid=video_id: play_youtube_video(vid)).pack(side="left", padx=2)
                tk.Button(action_frame, text="ARCHIVE", font=font_big, bg="#333", fg="white", command=archive_this).pack(side="left", padx=2)
            else:
                # Show Download button
                dl_btn = tk.Button(
                    action_frame,
                    text="DOWNLOAD",
                    font=font_big,
                    bg="black",
                    fg="white"
                )
                dl_btn.config(command=lambda vid=video_id, b=dl_btn: download_youtube_video(vid, b, refresh_ui))
                dl_btn.pack(side="left", padx=2)
                
            def delete_this(vid=video_id):
                video = youtube_metadata["videos"].get(vid)
                if not video:
                    messagebox.showerror("Error", f"Video {vid} not found in metadata.")
                    return

                filename = video.get("filename", "")
                filepath = os.path.join("youtube", filename)
                filesize = os.path.getsize(filepath) / (1024 * 1024) if os.path.exists(filepath) else 0
                filesize_str = f"{filesize:.2f} MB"

                confirm_message = f"Delete video {vid}?\n\nFile: {filename}\nSize: {filesize_str}"
                if messagebox.askyesno("Confirm Delete (CANNOT BE UNDONE)", confirm_message):
                    # Remove from metadata
                    youtube_metadata["videos"].pop(vid, None)

                    # Attempt to delete the file
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                            print(f"Deleted file: {filepath}")
                        except Exception as e:
                            print(f"Failed to delete file {filepath}: {e}")

                    save_youtube_metadata()
                    refresh_ui()

            tk.Button(action_frame, text="❌", font=font_big, fg="red", bg="black", command=delete_this).pack(side="left", padx=2)
            action_frame.grid(row=video_row, column=5, padx=4)
            row_widgets.append(action_frame)
            # Store the widget row
            entry_widgets.append((video_id, [title_entry, start_frame, end_frame]))

        def save_all():
            for video_id, widgets in entry_widgets:
                title_entry = widgets[0]
                start_frame = widgets[1]
                end_frame = widgets[2]

                # Get values from within the nested frames
                start_entry = start_frame.winfo_children()[0]  # Entry is the first child
                end_entry = end_frame.winfo_children()[0]      # Entry is the first child

                title = title_entry.get().strip()
                start = start_entry.get().strip()
                end = end_entry.get().strip()

                video = youtube_metadata["videos"][video_id]
                video["custom_title"] = title if title != video["title"] else ""
                video["start"] = int(start)
                video["end"] = int(end)

            save_youtube_metadata()
            save_youtube_button.configure(text="SAVED!")
            root.after(300, lambda: save_youtube_button.configure(text="SAVE ALL"))

        def extract_video_id(url):
            match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
            return match.group(1) if match else None

        def add_video_by_url():
            if not ffmpeg_available:
                messagebox.showerror("FFmpeg Not Found", "FFmpeg is required to add YouTube videos. Please ensure FFmpeg is installed and accessible in your system PATH.")
                return
            add_video_button.configure(text="ADDING...(PLEASE WAIT)")
            url = simpledialog.askstring("Add YouTube Video", "Enter YouTube video URL:", parent=youtube_editor_window)
            if not url:
                add_video_button.configure(text="ADD VIDEO FROM URL")
                return
        
            video_id = extract_video_id(url)
            if not video_id:
                messagebox.showerror("Invalid URL", "Could not extract video ID from the URL.")
                add_video_button.configure(text="ADD VIDEO FROM URL")
                return

            if video_id in youtube_metadata.get("videos", {}):
                messagebox.showinfo("Duplicate", "This video already exists in the list.")
                add_video_button.configure(text="ADD VIDEO FROM URL")
                return
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'format': 'best',
            }

            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                # Ensure data structure is ready
                if "videos" not in youtube_metadata:
                    youtube_metadata["videos"] = {}
                if "channels" not in youtube_metadata:
                    youtube_metadata["channels"] = {}

                # Add channel info
                channel_id = info.get("channel_id")
                if channel_id:
                    youtube_metadata["channels"][channel_id] = {
                        "name": info.get("channel"),
                        "subscriber_count": info.get("channel_follower_count", 0)
                    }

                # Build filename and store video data
                sanitized_title = re.sub(r'[^A-Za-z0-9]', '', info["title"])
                filename = f"{video_id}-{sanitized_title}.mp4"

                youtube_metadata["videos"][video_id] = {
                    "title": info["title"],
                    "custom_title": "",  # editable title, empty means use default
                    "start": 0,
                    "end": 0,
                    "channel_id": channel_id,
                    "duration": info.get("duration", 0),
                    "view_count": info.get("view_count", 0),
                    "like_count": info.get("like_count", 0),
                    "upload_date": info.get("upload_date", ""),
                    "description": info.get("description", ""),
                    "thumbnail": info.get("thumbnail", ""),
                    "filename": filename,
                    "archived": False,
                    "archived_date": None,
                    "date_added": datetime.now().isoformat()
                }

                save_youtube_metadata()
                refresh_ui()

            except Exception as e:
                add_video_button.configure(text="ADD VIDEO FROM URL")
                messagebox.showerror("Error", f"Failed to add video: {e}")

        def open_archived_youtube_view():
            archive_window = tk.Toplevel()
            archive_window.title("Archived YouTube Videos")
            archive_window.configure(bg=BACKGROUND_COLOR)

            # Set size and make resizable with a scrollable region
            archive_window.geometry("950x600")

            # Scrollable frame setup
            canvas = tk.Canvas(archive_window, bg=BACKGROUND_COLOR, highlightthickness=0)
            scrollbar = tk.Scrollbar(archive_window, orient="vertical", command=canvas.yview)
            scroll_frame = tk.Frame(canvas, bg=BACKGROUND_COLOR)

            scroll_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Sort and filter archived videos
            archived_videos = {
                vid: v for vid, v in youtube_metadata.get("videos", {}).items()
                if v.get("archived")
            }
            sorted_videos = sorted(archived_videos.items(), key=lambda x: x[1].get("archived_date", ""))

            for idx, (video_id, video) in enumerate(sorted_videos):
                title = get_youtube_display_title(video)
                archive_date = video.get("archived_date", "Unknown")
                filename = video.get("filename", "")
                filepath = os.path.join("youtube", "archive", filename)
                size_label = ""

                if os.path.exists(filepath):
                    try:
                        size_mb = os.path.getsize(filepath) / 1024 / 1024
                        size_label = f" ({size_mb:.1f} MB)"
                    except:
                        pass

                row_frame = tk.Frame(scroll_frame, bg=BACKGROUND_COLOR)
                row_frame.grid(row=idx, column=0, sticky="w", padx=8, pady=6)

                # Video ID
                tk.Label(row_frame, text=video_id, width=12, font=font_big, bg=BACKGROUND_COLOR, fg="gray").pack(side="left", padx=6)

                # Title + Size
                tk.Label(row_frame, text=title + size_label, font=font_big, bg=BACKGROUND_COLOR, fg=fg_color, width=40, anchor="w").pack(side="left", padx=6)

                # Archive date
                tk.Label(row_frame, text=archive_date, font=font_big, bg=BACKGROUND_COLOR, fg="#aaa", width=12).pack(side="left", padx=6)

                # Restore Button
                def restore_this(vid=video_id):
                    video = youtube_metadata["videos"][vid]
                    video["archived"] = False
                    video.pop("archived_date", None)

                    old_path = os.path.join("youtube", "archive", video["filename"])
                    new_path = os.path.join("youtube", video["filename"])
                    if os.path.exists(old_path):
                        try:
                            shutil.move(old_path, new_path)
                            print(f"Restored file: {video['filename']}")
                        except Exception as e:
                            print(f"Failed to restore file: {e}")

                    archive_window.destroy()
                    save_youtube_metadata()
                    refresh_ui()

                tk.Button(row_frame, text="RESTORE", font=font_big, bg="green", fg="white", command=restore_this).pack(side="left", padx=4)

                # Delete Button
                def delete_this(vid=video_id):
                    if messagebox.askyesno("Confirm Delete", f"Delete video {vid}?"):
                        video = youtube_metadata["videos"].pop(vid, None)
                        archive_path = os.path.join("youtube", "archive", video["filename"])
                        if os.path.exists(archive_path):
                            try:
                                os.remove(archive_path)
                                print(f"Deleted file: {archive_path}")
                            except Exception as e:
                                print(f"Failed to delete file: {e}")
                        archive_window.destroy()
                        save_youtube_metadata()
                        refresh_ui()

                tk.Button(row_frame, text="❌", font=font_big, fg="red", bg="black", command=delete_this).pack(side="left", padx=4)

        add_video_button = tk.Button(
            youtube_editor_window,
            text="ADD VIDEO FROM URL",
            font=font_big,
            bg="black",
            fg="white",
            command=add_video_by_url
        )
        add_video_button.grid(row=999, column=0, columnspan=2, pady=10)
        save_youtube_button = tk.Button(youtube_editor_window, text="SAVE ALL", font=font_big, command=save_all, bg="black", fg="white")
        save_youtube_button.grid(row=999, column=2, columnspan=2, pady=12)
        archived_count = sum(1 for v in youtube_metadata.get("videos", {}).values() if v.get("archived"))
        tk.Button(youtube_editor_window, text=f"SHOW ARCHIVED({archived_count})", font=font_big, command=open_archived_youtube_view, bg="black", fg="white").grid(row=999, column=3, columnspan=3, pady=12)

    refresh_ui()

def download_youtube_video(video_id, button, refresh_ui_callback):

    video = youtube_metadata["videos"][video_id]
    filename = os.path.join("youtube", video["filename"])
    last_percent = {"value": -1}  # Mutable object to track percent between threads

    def update_button(text):
        if isinstance(button, tk.Button):
            button.config(text=text)

    last_percent = {"value": -1}
    max_total = {"bytes": 0}  # Track the largest stable filesize seen
    def on_progress(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            reported_total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1

            # Update max_total only if it's significantly larger (5% threshold)
            if reported_total > max_total["bytes"] * 1.05 or reported_total < max_total["bytes"] * .95:
                max_total["bytes"] = reported_total
            elif max_total["bytes"] == 0:
                max_total["bytes"] = reported_total

            total = max_total["bytes"]
            percent = int((downloaded / total) * 100)

            last_percent["value"] = percent
            downloaded_mb = downloaded / 1024 / 1024
            total_mb = total / 1024 / 1024
            update_button(f"{downloaded_mb:.1f}/{total_mb:.1f} MB")

        elif d['status'] == 'finished':
            update_button("Merging...")

    def do_download():
        update_button("Starting...")
        try:
            # ydl_opts = {
            #     'format': 'bv*[vcodec^=avc1]+ba*[acodec^=mp4a]/b[ext=mp4]/bv*+ba*/b',
            #     'merge_output_format': 'webm',  # Ensure final file is mp4
            #     'outtmpl': filename,
            #     'quiet': True,
            #     'progress_hooks': [on_progress],
            # }
            # ydl_opts = {
            #     'format': 'bestvideo[ext=webm]+bestaudio[ext=webm]/bestvideo+bestaudio/best',
            #     'merge_output_format': 'webm',
            #     'outtmpl': filename,
            #     'quiet': True,
            #     'progress_hooks': [on_progress],
            # }

            # with YoutubeDL(ydl_opts) as ydl:
            #     ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)

            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': filename,
                'quiet': True,
                'progress_hooks': [on_progress] if on_progress else [],
                'merge_output_format': 'mp4',  # merge first to mp4
            }

            with YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)

            # # Now convert merged mp4 to webm
            # convert_cmd = [
            #     'ffmpeg',
            #     '-i', filename.replace(".webm", ".mp4"),
            #     '-c:v', 'libvpx-vp9',  # VP9 video codec
            #     '-b:v', '2M',          # video bitrate (adjust as needed)
            #     '-c:a', 'libopus',     # Opus audio codec
            #     '-b:a', '128k',        # audio bitrate
            #     filename
            # ]

            # subprocess.run(convert_cmd, check=True)

            save_youtube_metadata()
            refresh_ui_callback()
        except Exception as e:
            update_button("Error")
            print(f"Download error for {video_id}: {e}")

    if os.path.exists(filename):
        filesize = os.path.getsize(filename)
        update_button(f"{round(filesize / 1024 / 1024, 1)} MB")
    else:
        threading.Thread(target=do_download, daemon=True).start()

# =========================================
#           *CREATE PLAYLIST
# =========================================

playlist_changed = False
def generate_playlist():
    """Function to generate a playlist"""
    global playlist_changed
    playlist_changed = True
    playlis = []
    for file in directory_files:
        playlis.append(file)
    return playlis

def empty_playlist():
    global playlist
    confirm = messagebox.askyesno("Clear Playlist", f"Are you sure you want to create an empty playlist?")
    if not confirm:
        return  # User canceled
    new_playlist([], name=playlist.get("name"))
    playlist = copy.deepcopy(BLANK_PLAYLIST)

# Generate playlist button
def generate_playlist_button():
    global playlist
    confirm = messagebox.askyesno("Create Playlist", f"Are you sure you want to create a new playlist with all {len(directory_files)} files in the directory?")
    if not confirm:
        return  # User canceled
    new_playlist(generate_playlist())
    if not playlist["playlist"]:
        messagebox.showwarning("Playlist Error", "No video files found in the directory.")

def generate_anilist_playlist():
    global playlist
    user_id = simpledialog.askstring("AniList User ID", "Enter the AniList user ID:")
    if not user_id:
        return  # User canceled
    
    only_watched = messagebox.askyesno("AniList Only Watched", f"Do you want to limit results to only watched entries?")

    # Fetch AniList data
    user_anime_ids = fetch_anilist_user_ids(user_id, only_watched)
    if not user_anime_ids:
        messagebox.showerror("Error", "Could not fetch AniList data or no entries found.")
        return

    matching_files = []
    for file in directory_files:
        data = get_metadata(file)
        if data and str(data.get("anilist")) in user_anime_ids:
            matching_files.append(file)

    if not matching_files:
        messagebox.showwarning("Playlist Error", "No matching video files found for this AniList user.")
    else:
        confirm = messagebox.askyesno("Create Playlist", f"{len(matching_files)} matches found. Create playlist?")
        if not confirm:
            return
        new_playlist(matching_files, f"{user_id}'s AniList")

def confirm_save_playlist(text=""):
    # If playlist has no name, always ask to save
    if not playlist.get("name"):
        if len(playlist.get("playlist", [])) > 15:
            confirm = messagebox.askyesno("Save Playlist", f"Do you want to save your current playlist before {text}?")
            if confirm:
                save()
        return
    elif playlist.get("name") in SYSTEM_PLAYLISTS:
        return  # Do not ask to save for these special playlists
    
    # Check if a playlist with this name already exists
    playlist_name = playlist["name"]
    saved_playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")
    
    if not os.path.exists(saved_playlist_path):
        # No saved playlist with this name exists, ask to save
        confirm = messagebox.askyesno("Save Playlist", f"Do you want to save your current playlist before {text}?")
        if confirm:
            save()
        return
    
    # Load the saved playlist and compare with current
    try:
        with open(saved_playlist_path, "r", encoding="utf-8") as f:
            saved_playlist = json.load(f)
        
        # Compare key playlist properties
        current_playlist_data = {
            "playlist": playlist["playlist"],
            "infinite": playlist.get("infinite", False),
            "difficulty": playlist.get("difficulty", 2),
            "order": playlist.get("order", 0),
            "filter": playlist.get("filter", {})
        }
        
        saved_playlist_data = {
            "playlist": saved_playlist.get("playlist", []),
            "infinite": saved_playlist.get("infinite", False), 
            "difficulty": saved_playlist.get("difficulty", 2),
            "order": saved_playlist.get("order", 0),
            "filter": saved_playlist.get("filter", {})
        }
        
        # Only ask to save if there are differences
        if current_playlist_data != saved_playlist_data:
            confirm = messagebox.askyesno("Save Playlist", f"Playlist '{playlist_name}' has unsaved changes. Do you want to save before {text}?")
            if confirm:
                save()
    except Exception as e:
        # If there's an error loading the saved playlist, default to asking to save
        print(f"Error comparing playlists: {e}")
        confirm = messagebox.askyesno("Save Playlist", f"Do you want to save your current playlist before {text}?")
        if confirm:
            save()

def new_playlist(playlis, name=None):
    global playlist
    confirm_save_playlist("creating a new playlist")
    playlist = copy.deepcopy(BLANK_PLAYLIST)
    up_next_text()
    update_playlist_name(name=name)
    playlist["playlist"] = playlis
    create_first_row_buttons()
    update_current_index(0)
    update_playlist_name()
    save_config()

def create_infinite_playlist():
    global playlist
    confirm = messagebox.askyesno("Create Infinite Playlist", f"Are you sure you want to create a new infinite playlist?")
    if not confirm:
        return  # User canceled
    new_playlist([])
    playlist["infinite"] = True
    get_pop_time_groups(refetch=True)
    get_next_infinite_track()
    create_first_row_buttons()
    update_playlist_name("")
    save_config()

# =========================================
#            *SHUFFLE PLAYLIST
# =========================================

def randomize_playlist():
    if playlist.get("infinite", False):
        return
    confirm = messagebox.askyesno("Shuffle Playlist", f"Are you sure you want to shuffle '{playlist["name"]}'?")
    if not confirm:
        return  # User canceled
    random.shuffle(playlist["playlist"])
    update_current_index(0)

def weighted_randomize():
    global playlist
    if playlist.get("infinite", False):
        return
    confirm = messagebox.askyesno("Weighted Shuffle Playlist", f"Are you sure you want to weighted shuffle '{playlist["name"]}'?")
    if not confirm:
        return  # User canceled
    playlist["playlist"] = weighted_shuffle(playlist["playlist"])
    update_current_index(0)

def weighted_shuffle(playlis):
    """Performs a weighted shuffle of the playlist, balancing popularity and season while preventing repeats."""
    
    if not playlis:
        return playlis  # Return as is if empty

    # Step 1: Sort by popularity and split into 3 groups
    sorted_playlist = sorted(playlis, key=lambda x: get_metadata(x).get("members", 0) or 0, reverse=True)
    group_size = len(sorted_playlist) // 3  # Split into 3 equal groups

    popular = sorted_playlist[:group_size]
    mid = sorted_playlist[group_size:group_size*2]
    niche = sorted_playlist[group_size*2:]

    # Step 2: Within each popularity group, sort by year (oldest to newest)
    def sort_by_year(entries):
        return sorted(entries, key=lambda x: int(get_metadata(x).get("season", "9999")[-4:]))

    popular_sorted = sort_by_year(popular)
    mid_sorted = sort_by_year(mid)
    niche_sorted = sort_by_year(niche)

    # Step 3: Split each group into 3 time-based sections (Older, Mid, Recent)
    popular_time_splits = split_into_three(popular_sorted)
    mid_time_splits = split_into_three(mid_sorted)
    niche_time_splits = split_into_three(niche_sorted)

    filename_group = {}
    # Step 4: Shuffle each section separately

    grp1 = 0
    grp2 = 0
    for group in [popular_time_splits, mid_time_splits, niche_time_splits]:
        for sublist in group:
            random.shuffle(sublist)
            for filename in sublist:
                filename_group[filename] = str(grp1) + str(grp2)
            grp2 = grp2 + 1
        grp1 = grp1 + 1
        grp2 = 0

    # Step 5: Cascade shuffled groups into a final playlist with randomized order per cycle
    shuffled_playlist = []
    groups = [popular_time_splits, mid_time_splits, niche_time_splits]

    while any(any(group) for group in groups):
        # Step 1: Generate all unique (pop, time) pairs
        pop_time_order = get_pop_time_order()

        for o in range(0,9):
            t = pop_time_order[o][0]
            p = pop_time_order[o][1]
            if p < len(groups) and t < len(groups[p]) and groups[p][t]:  # Ensure list is not empty
                shuffled_playlist.append(groups[p][t].pop(0))  # Pull one entry at a time

        # Remove empty groups
        groups = [group for group in groups if any(group)]

    # Step 6: Prevent repeats (title & series)
    final_playlist = shuffled_playlist[:]

    def find_suitable_swap(index):
        """Finds a suitable index to swap to reduce repetition issues."""
        spacing = min_spacing
        # Check forward first
        for swap_index in range(index + spacing, len(final_playlist)):
            if filename_group[get_clean_filename(final_playlist[index])] == filename_group[get_clean_filename(final_playlist[swap_index])]:
                if is_safe_swap(index, swap_index):
                    return swap_index
        
        # If no forward swap found, check backward
        for swap_index in range(index - spacing, -1, -1):
            if filename_group[get_clean_filename(final_playlist[index])] == filename_group[get_clean_filename(final_playlist[swap_index])]:
                if is_safe_swap(index, swap_index):
                    return swap_index

        return None  # No good swap found

    def is_safe_swap(i1, i2):
        """Checks if swapping entries i1 and i2 resolves spacing issues for both."""
        def is_valid_placement(index, entry_series):
            for offset in range(1, min_spacing + 1):
                # Check before
                if index - offset >= 0:
                    prev = final_playlist[index - offset]
                    prev_series = get_metadata(prev).get("series") or [get_metadata(prev).get("title")]
                    if entry_series == prev_series:
                        return False
                # Check after
                if index + offset < len(final_playlist):
                    next_ = final_playlist[index + offset]
                    next_series = get_metadata(next_).get("series") or [get_metadata(next_).get("title")]
                    if entry_series == next_series:
                        return False
            return True

        # Get entries and their metadata
        entry1 = final_playlist[i1]
        entry2 = final_playlist[i2]
        series1 = get_metadata(entry1).get("series") or [get_metadata(entry1).get("title")]
        series2 = get_metadata(entry2).get("series") or [get_metadata(entry1).get("title")]

        # Check if both would be safely placed after swap
        return (
            is_valid_placement(i2, series1) and
            is_valid_placement(i1, series2)
    )

    get_series_totals(check_all=False)
    swapped_entrys = 1
    skipped_entries = 0
    swap_pass = 0

    print("Weighted Shuffle - STARTING... (may take some time, 15 pass max)")
    while (swapped_entrys > 0 or skipped_entries > 0) and swap_pass < 15:
        swapped_entrys = 0
        skipped_entries = 0
        swap_pass += 1
        exausted_series = []

        for i in range(len(final_playlist)):
            print(f"Spacing Same Series Pass {swap_pass} - Checking entry {i + 1} / {len(final_playlist)} ({swapped_entrys} swapped / {skipped_entries} skipped)", end="\r")  # 🔄 Overwrites same line
            series = get_metadata(get_clean_filename(final_playlist[i])).get("series") or [get_metadata(get_clean_filename(final_playlist[i])).get("title")]
            total_series = series_totals.get(series[0], 0)
            if total_series > 1:
                if series in exausted_series:
                    skipped_entries += 1
                else:
                    min_spacing = int(min(350, max(3, (len(final_playlist) // total_series)) * (0.9 ** swap_pass)))
                    for j in range(1, min_spacing + 1):
                        if i + j < len(final_playlist):
                            next_series = get_metadata(get_clean_filename(final_playlist[i + j])).get("series") or [get_metadata(get_clean_filename(final_playlist[i + j])).get("title")]
                            if series == next_series:
                                swap_index = find_suitable_swap(i + j)
                                if swap_index:
                                    swapped_entrys += 1
                                    final_playlist[i + j], final_playlist[swap_index] = final_playlist[swap_index], final_playlist[i + j]
                                else:
                                    skipped_entries += 1
                                    exausted_series.append(series)
        print(f"")
        
    print("Weighted Shuffle - COMPLETE!")

    return final_playlist

def split_into_three(entries):
    size = len(entries) // 3 or 1  # Ensure at least 1 per split
    return [entries[:size], entries[size:size*2], entries[size*2:]]

def get_pop_time_order():
    all_pairs =  [(p, t) for p in [0,1,2] for t in [0,1,2]]

    # Step 2: Try until we find a valid shuffle
    while True:
        random.shuffle(all_pairs)
        valid = True
        for i in range(0, 9, 3):
            block = all_pairs[i:i+3]
            if sorted(p for p, _ in block) != [0,1,2]:
                valid = False
                break
            if sorted(t for _, t in block) != [0,1,2]:
                valid = False
                break
        if valid:
            return all_pairs

# =========================================
#          *INFINITE PLAYLISTS
# =========================================

def test_infinite_playlist(event=None):
    global playlist
    old_playlist = copy.deepcopy(playlist)
    playlist["playlist"] = []
    playlist["current_index"] = 0

    # We'll collect output for analysis later
    track_logs = []
    test_size = INFINITE_PLAYLIST_LIMIT
    for i in range(test_size):
        selected_file = get_next_infinite_track()
        p, t = playlist["pop_time_order"][playlist["order"]][0], playlist["pop_time_order"][playlist["order"]][1]

        # Prepare track info for logging
        track_info = f"{len(playlist["playlist"])}({p},{t}): {selected_file}"

        print(f"\rTESTING INFINITE PLAYLIST: {len(playlist["playlist"])}/{test_size}", end='', flush=True)
        sys.stdout.flush()

        # Collect the track log (for later use, not for real-time print)
        track_logs.append(track_info)

    # Restore previous playlist
    playlist = old_playlist
    update_current_index()

    # Write all track logs to file
    with open("infinite_playlist_test.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(track_logs))

    print(" Track generation complete. Output: 'infinite_playlist_test.txt'")

def toggle_infinite_playlist():
    if playlist.get("infinite", False):
        playlist["infinite"] = False
    else:
        playlist["infinite"] = True
        if playlist["current_index"]+1 >= len(playlist["playlist"]):
            get_next_infinite_track()
    
    # Refresh list display to show any changes
    if list_loaded == "playlist":
        global current_list_content, current_list_selected
        current_list_content = convert_playlist_to_dict(playlist["playlist"])
        current_list_selected = playlist["current_index"]
        refresh_current_list()
    
    create_first_row_buttons()
    save_config()

SEASON_ORDER = ["Winter", "Spring", "Summer", "Fall"]
def get_last_three_seasons():
    now = datetime.now()
    current_season_string = f"{["Winter", "Spring", "Summer", "Fall"][(now.month - 1) // 3]} {now.year}"
    season, year = current_season_string.split()
    year = int(year)
    index = SEASON_ORDER.index(season)
    
    last_three = []
    for i in range(3):
        cur_index = (index - i) % 4
        year_offset = (index - i) < 0  # if we wrapped to previous year
        cur_year = year - 1 if year_offset else year
        last_three.append(f"{SEASON_ORDER[cur_index]} {cur_year}")
    
    return last_three

def get_boost_multiplier(season_string):
    for i, s in enumerate(get_last_three_seasons()):
        if s == season_string:
            return [20,10,5][i]
    return 1

difficulty_options = ["MODE: VERY EASY","MODE: EASY","MODE: NORMAL","MODE: HARD","MODE: VERY HARD","MODE: RANDOM"]
def select_difficulty(event=None):
    value = difficulty_dropdown.get()
    for i, d in enumerate(difficulty_options):
        if d == value:
            playlist["difficulty"] = i
            refresh_pop_time_groups()
    difficulty_dropdown.selection_clear()
    difficulty_dropdown.icursor(tk.END)
    if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
        value = difficulty_dropdown.get()
        popout_buttons_by_name["DIFFICULTY DROPDOWN"].set(value)
    save_config()

def refresh_pop_time_groups():
    get_pop_time_groups(refetch=True)
    update_current_index(save=False)
    if playlist["current_index"] == len(playlist["playlist"])-2:
        refetch_next_track()

def refetch_next_track():
    playlist["playlist"].pop(len(playlist["playlist"])-1)
    get_next_infinite_track(increment=False)
    up_next_text()
    root.after(1000, queue_next_lightning_mode)

INT_INF = float('inf')
cached_pop_time_group = None
cached_show_files_map = None
cached_boosted_show_files_map = None
cached_pop_time_cooldown = 0
cached_skipped_themes = []
total_infinite_files = 0
difficulty_ranges = [
    ["easy"],
    ["easy", "medium"],
    ["easy", "medium", "hard"],
    ["medium", "hard"],
    ["hard"],
    ["easy", "medium", "hard"]
]

difficulty_groups = {
    "easy": {
        "range": [1, 250],
        "cooldown": [0.5, 0.6],
        "file_boost_limit": 20
    },
    "medium": {
        "range": [251, 1000],
        "cooldown": [0.75, 0.9],
        "file_boost_limit": 5
    },
    "hard": {
        "range": [1001, INT_INF],
        "cooldown": [1.0, 1.0],
        "file_boost_limit": 1
    },
    "all": {
        "range": [1, INT_INF],
        "cooldown": [1.0, 1.5],
        "file_boost_limit": 1
    }
}
def get_pop_time_groups(refetch=False):
    global cached_pop_time_group, cached_show_files_map, cached_boosted_show_files_map, cached_pop_time_cooldown, cached_skipped_themes, total_infinite_files

    if refetch or not cached_pop_time_group:
        group_limits = difficulty_ranges[playlist["difficulty"]]
        sorted_groups = [[] for _ in range(3)]
        cached_skipped_themes = []

        directory_options = filter_playlist(playlist["filter"]) if playlist.get("filter") else copy.deepcopy(directory_files)
        total_infinite_files = len(directory_options)

        # Preload all metadata once
        all_metadata = {f: get_metadata(f) for f in directory_options}
        # Get current session lightning tracks to exclude from cooldown history
        current_session_lightning = get_current_session_lightning_tracks()
        
        # Build playlist history excluding lightning rounds from previous sessions
        playlist_mal_history = []
        for f in playlist["playlist"]:
            clean_f = get_clean_filename(f)
            metadata = get_metadata(clean_f)
            if metadata and metadata.get("mal"):
                # Include if it's not a lightning round, or if it's from current session
                if not f.startswith("[L]") or clean_f in current_session_lightning:
                    playlist_mal_history.append(metadata.get("mal"))

        shows_files_map = {}
        for f, d in all_metadata.items():
            if not d or check_tagged(f) or check_theme(f, "New Themes"):
                cached_skipped_themes.append(f)
                continue

            p = d.get("popularity") or INT_INF
            mal = d.get("mal")
            placed = False

            for k, l in enumerate(group_limits):
                difficulty_group = difficulty_groups.get(l)
                if p >= difficulty_group["range"][0] and p <= difficulty_group["range"][1]:
                    boost = 0
                    if mal not in shows_files_map:
                        boost += max(0, (d.get("score", 0) or 0) - 7)
                        boost += get_boost_multiplier(d.get("season", "Fall 2000"))
                        distance_from_end = 0
                        # More efficient: find exact position and calculate boost directly
                        try:
                            # Find the last occurrence of this MAL ID in playlist history
                            last_index = len(playlist_mal_history) - 1 - playlist_mal_history[::-1].index(mal)
                            # Calculate how far back it was (distance from end)
                            distance_from_end = len(playlist_mal_history) - 1 - last_index
                        except ValueError:
                            # MAL ID not found in history, give maximum boost based on history length
                            distance_from_end = len(playlist_mal_history)
                        distance_boost = (distance_from_end // 2000) * (distance_from_end // 2000)
                        boost += distance_boost
                    elif len(shows_files_map[mal]) <= difficulty_group["file_boost_limit"]:
                        boost += 1

                    sorted_groups[k].extend([f] * int(boost))
                    shows_files_map.setdefault(mal, []).append(f)

                    if check_favorited(f):
                        sorted_groups[k].append(f"{f}[EXTRA]")

                    placed = True
                    break

            if not placed:
                cached_skipped_themes.append(f)
        
        # For random mode, sort all into one group, while keeping the three group structure
        if playlist["difficulty"] == 5:
            sorted_groups = [[sum(sorted_groups, []), [], []], [[],[],[]], [[],[],[]]]
        else:
            # Sort by year (cached)
            def sort_by_year(entries):
                def get_year(entry):
                    meta = all_metadata.get(entry.replace("[EXTRA]", ""), {})
                    if meta.get("aired"):
                        season = aired_to_season_year(meta.get("aired"), False)
                    else:
                        season = meta.get("season", "9999")[-4:]
                    return int(season[-4:])
                return sorted(entries, key=get_year, reverse=True)

            for i, g in enumerate(sorted_groups):
                sorted_subgroups = split_into_three(sort_by_year(g))
                for sublist in sorted_subgroups:
                    random.shuffle(sublist)
                sorted_groups[i] = sorted_subgroups

        cached_pop_time_group = sorted_groups
        cached_show_files_map = shows_files_map
        
        # For random mode, create virtual groups beforehand to get correct cooldown calculations
        if playlist["difficulty"] == 5:
            sorted_groups = create_virtual_groups_for_random(sorted_groups)
        
        compute_cooldowns(sorted_groups, True)
    if refetch or not cached_boosted_show_files_map:
        boosted_show_files_map = {}
        for mal_id, files in cached_show_files_map.items():
            for file in files:
                file_boost = 1
                distance_from_end = 0
                # More efficient: find exact position and calculate boost directly
                try:
                    # Find the last occurrence of this file in playlist history
                    last_index = len(playlist["playlist"]) - 1 - playlist["playlist"][::-1].index(file)
                    # Calculate how far back it was (distance from end)
                    distance_from_end = len(playlist["playlist"]) - 1 - last_index
                    # Give boost based on 1000-entry ranges
                except ValueError:
                    # File not found in history, give maximum boost based on history length
                    distance_from_end = len(playlist["playlist"])
                file_boost += (distance_from_end // 2000) * (distance_from_end // 2000)
                boosted_show_files_map.setdefault(mal_id, []).extend([file] * int(file_boost))
        cached_pop_time_cooldown = 0
        cached_boosted_show_files_map = boosted_show_files_map

    return copy.deepcopy(cached_pop_time_group), copy.deepcopy(cached_boosted_show_files_map)

def next_playlist_order(increment=True):
    global cached_pop_time_cooldown
    if playlist["order"] >= len(playlist["pop_time_order"]) - 1:
        playlist["order"] = 0
        playlist["pop_time_order"] = get_pop_time_order()
    elif increment:
        playlist["order"] += 1
    if increment:
        cached_pop_time_cooldown += 1
        if cached_pop_time_cooldown > 50:
            def worker():
                get_pop_time_groups(True)
            threading.Thread(target=worker, daemon=True).start()
            cached_pop_time_cooldown = 0

INFINITE_PLAYLIST_LIMIT = 10000
def get_next_infinite_track(increment=True):
    if not playlist.get("infinite", False):
        return
    
    next_playlist_order(increment)
    groups, shows_files_map = get_pop_time_groups()
    # Note: compute_cooldowns() was for old discrete system, now using smooth cooldowns
    effective_difficulty_range = difficulty_ranges[playlist["difficulty"]]
    min_s_limit, min_f_limit = base_series_cooldown, base_file_cooldown = get_cooldown_for_popularity(1, effective_difficulty_range, groups)
    s_limit_mod, f_limit_mod = 1, 1
    p, t = playlist["pop_time_order"][playlist["order"]][0], playlist["pop_time_order"][playlist["order"]][1]

    if p < len(groups) and t < len(groups[p]) and groups[p][t]:
        random.shuffle(groups[p][t])
    selected_file = None
    checked_mal_ids = []
    try_count = 0
    op_count, ed_count = get_op_ed_counts(playlist["playlist"][-50:])

    while not selected_file:
        group_op_count, group_ed_count = get_op_ed_counts(groups[p][t])
        if group_ed_count == 0:
            need_op = False
        else:
            need_op = ed_count >= op_count and (group_op_count / (2 * group_ed_count)) > 0.05

        if p >= len(groups) or t >= len(groups[p]) or not groups[p][t]:
            if try_count > 18:
                return
            next_playlist_order()
            p, t = playlist["pop_time_order"][playlist["order"]][0], playlist["pop_time_order"][playlist["order"]][1]
            if groups[p][t]:
                random.shuffle(groups[p][t])
            try_count += 1
            continue
        file = groups[p][t].pop(0)
        extra_file = False
        if "[EXTRA]" in file:
            file = file.replace("[EXTRA]", "")
            extra_file = True
        else:
            selected_mal = get_metadata(file).get("mal")
        if extra_file or selected_mal not in checked_mal_ids:
            if extra_file:
                show_files = [file]
            else:
                checked_mal_ids.append(selected_mal)
                show_files = shows_files_map.get(selected_mal, [])
                random.shuffle(show_files)
            checked_files = []
            while show_files and not selected_file:
                selected_file = show_files.pop(0)
                if selected_file in checked_files:
                    selected_file = None
                    continue
                checked_files.append(selected_file)
                d = get_metadata(selected_file)
                s_pop = get_series_popularity(d)
                
                # Get smooth cooldowns based on popularity rank

                base_series_cooldown, base_file_cooldown = get_cooldown_for_popularity(s_pop, effective_difficulty_range, groups)

                # Apply modifiers like the original system
                s_limit = int(base_series_cooldown * s_limit_mod)
                f_limit = int(base_file_cooldown * f_limit_mod)
                
                if need_op and not is_slug_op(d.get("slug")):
                    selected_file = None
                    continue
                series = d.get("series") or [d.get("title")]
                boost = get_boost_multiplier(d.get("season", "Fall 2000"))
                if s_limit > 1 or f_limit > 1:
                    # Get current session lightning tracks for cooldown exclusion
                    current_session_lightning = get_current_session_lightning_tracks()
                    cooldown_count = 0
                    
                    for f in reversed(playlist["playlist"]):
                        # Skip lightning rounds from previous sessions in cooldown calculations
                        clean_f = get_clean_filename(f)
                        if not light_mode and f.startswith("[L]") and clean_f not in current_session_lightning:
                            continue
                        
                        f_d = get_metadata(clean_f)
                        if f == selected_file or (f_d.get("mal") == d.get("mal") and f_d.get("slug") == d.get("slug")) or (cooldown_count < max(min_s_limit*s_limit_mod, (s_limit/boost)) and series == (f_d.get("series") or [f_d.get("title")])):
                            selected_file = None
                            break
                        
                        cooldown_count += 1
                        if cooldown_count >= max(min_f_limit*f_limit_mod, ((f_limit)/boost)):
                            break
                if selected_file:
                    # Debug print for selected tracks
                    if False:
                        print(f"🎵 INFINITE TRACK: {selected_file}")
                        print(f"   📊 Popularity Rank: {s_pop} | Simple Calculation")  
                        print(f"   ⏰ Series Cooldown: {s_limit:.0f} tracks (base: {base_series_cooldown})")
                        print(f"   ⏰ File Cooldown: {f_limit:.0f} tracks (base: {base_file_cooldown})")
                    
                    playlist["playlist"].append(selected_file)
                    if playlist["current_index"] == -1:
                        update_current_index(0)
                    if len(playlist["playlist"]) > INFINITE_PLAYLIST_LIMIT:
                        while len(playlist["playlist"]) > INFINITE_PLAYLIST_LIMIT:
                            playlist["playlist"].pop(0)
                            update_current_index(playlist["current_index"]-1)
                    else:
                        update_current_index()
                    
                    # Update list display if playlist is currently shown
                    if list_loaded == "playlist":
                        global current_list_content, current_list_selected
                        current_list_content = convert_playlist_to_dict(playlist["playlist"])
                        current_list_selected = playlist["current_index"]
                        refresh_current_list()
                    
                    return selected_file
        if not groups[p][t]:
            groups, shows_files_map = get_pop_time_groups()
            if p < len(groups) and t < len(groups[p]) and groups[p][t]:
                random.shuffle(groups[p][t])
            checked_mal_ids = []
            s_limit_mod = s_limit_mod * 0.9
            f_limit_mod = f_limit_mod * 0.9

def get_cooldown_for_popularity(popularity_rank, difficulty_range, groups):
    """Calculate cooldowns using computed values with smooth interpolation based on popularity rank"""
    # Use the cached cooldown values from compute_cooldowns
    if not series_cooldowns_cache or not file_cooldowns_cache:
        # Fallback - shouldn't happen since compute_cooldowns is called first
        return 84, 385
    
    # Normalize all cases to 3-group structure [easy, medium, hard]
    if len(series_cooldowns_cache) == 1:
        # Single group - return the single value for all popularity ranks
        return int(series_cooldowns_cache[0]), int(file_cooldowns_cache[0])
    elif len(series_cooldowns_cache) == 2:
        # Two groups - extend to 3 groups based on difficulty_range
        group1_series, group2_series = series_cooldowns_cache
        group1_file, group2_file = file_cooldowns_cache
        
        if difficulty_range == ["easy", "medium"]:
            # [easy, medium] → [easy, medium, medium]
            easy_series, medium_series, hard_series = group1_series, group2_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group2_file, group2_file
        elif difficulty_range == ["medium", "hard"]:
            # [medium, hard] → [medium, medium, hard]  
            easy_series, medium_series, hard_series = group1_series, group1_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group1_file, group2_file
        else:
            # Default 2-group case → [group1, group1, group2]
            easy_series, medium_series, hard_series = group1_series, group1_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group1_file, group2_file
    else:
        # Standard 3-group case - use as-is [easy, medium, hard]
        easy_series, medium_series, hard_series = series_cooldowns_cache
        easy_file, medium_file, hard_file = file_cooldowns_cache
    
    # Popularity-based cooldown calculation with smooth transitions
    if popularity_rank <= 50:
        # Ranks 1-50: Use easy cooldowns
        series_cooldown = easy_series
        file_cooldown = easy_file
    elif popularity_rank <= 250:
        # Ranks 51-250: Smooth transition from easy to medium
        # Formula: easy + ((rank-50) * ((medium-easy) / 200))
        progress = (popularity_rank - 50) / 200  # 0.0 to 1.0
        series_cooldown = easy_series + (progress * (medium_series - easy_series))
        file_cooldown = easy_file + (progress * (medium_file - easy_file))
    elif popularity_rank <= 1000:
        # Ranks 251-1000: Smooth transition from medium to hard  
        # Formula: medium + ((rank-250) * ((hard-medium) / 750))
        progress = (popularity_rank - 250) / 750  # 0.0 to 1.0
        series_cooldown = medium_series + (progress * (hard_series - medium_series))
        file_cooldown = medium_file + (progress * (hard_file - medium_file))
    else:
        # Ranks >1000: Smooth transition from hard cooldowns to INFINITE_PLAYLIST_LIMIT
        # Cap the transition at rank 10000 to avoid infinite scaling
        max_rank_for_scaling = INFINITE_PLAYLIST_LIMIT
        capped_rank = min(popularity_rank, max_rank_for_scaling)
        
        # Calculate progress from rank 1000 to max_rank_for_scaling
        progress = (capped_rank - 1000) / (max_rank_for_scaling - 1000)  # 0.0 to 1.0
        
        # File cooldown transitions from hard_file to INFINITE_PLAYLIST_LIMIT
        file_cooldown = hard_file + (progress * (INFINITE_PLAYLIST_LIMIT - hard_file))
        
        # Series cooldown scales proportionately to maintain the same ratio
        # Calculate the ratio of series to file cooldown at the hard tier
        if hard_file > 0:
            series_to_file_ratio = hard_series / hard_file
        else:
            series_to_file_ratio = 1  # Fallback if hard_file is 0
            
        series_cooldown = file_cooldown * series_to_file_ratio
    
    return int(series_cooldown), int(file_cooldown)

def create_virtual_groups_for_random(sorted_groups):
    """Create virtual groups for random mode by redistributing files by popularity ranges."""
    # Gather all files from all groups and redistribute by popularity
    all_files_flat = []
    for group in sorted_groups:
        for subgroup in group:
            all_files_flat.extend(subgroup)
    
    # print(f"🔄 RANDOM MODE: Creating virtual groups from {len(all_files_flat)} total files")
    
    # Create virtual groups by popularity ranges  
    virtual_groups = [[], [], []]  # easy, medium, hard
    for file in all_files_flat:
        clean_file = file.replace("[EXTRA]", "")
        metadata = get_metadata(clean_file)
        popularity = metadata.get("popularity") or float('inf')
        
        # Assign to virtual groups by popularity
        if popularity <= 250:
            virtual_groups[0].append(file)
        elif popularity <= 1000:
            virtual_groups[1].append(file)
        else:
            virtual_groups[2].append(file)
    
    # Structure virtual groups like normal groups (with 3 subgroups each)
    structured_virtual_groups = []
    for i, virtual_group in enumerate(virtual_groups):
        # Sort by year like normal groups do, then split into 3 subgroups
        def get_year(entry):
            meta = get_metadata(entry.replace("[EXTRA]", ""))
            if meta and meta.get("aired"):
                season = aired_to_season_year(meta.get("aired"), False)
            else:
                season = meta.get("season", "9999")[-4:] if meta else "9999"
            return int(season[-4:])
        
        sorted_virtual_group = sorted(virtual_group, key=get_year, reverse=True)
        virtual_subgroups = split_into_three(sorted_virtual_group)
        
        # Shuffle each subgroup like normal groups do
        for sublist in virtual_subgroups:
            random.shuffle(sublist)
            
        structured_virtual_groups.append(virtual_subgroups)
    
    return structured_virtual_groups

series_cooldowns_cache = None
file_cooldowns_cache  = None
def compute_cooldowns(groups, refetch=False):
    global series_cooldowns_cache, file_cooldowns_cache
    if not series_cooldowns_cache or refetch:
        series_cooldowns = []
        file_cooldowns = []

        difficulty_range = difficulty_ranges[playlist["difficulty"]]
        
        # Unified handling for all difficulty modes (including random with virtual groups)
        for i, group in enumerate(groups):
            if i >= len(difficulty_range):
                # Prevent index error
                continue
            difficulty_group = difficulty_groups[difficulty_range[i]]
            all_files = [f for subgroup in group for f in subgroup]
            unique_files = set(f.replace("[EXTRA]", "") for f in all_files)
            file_count = len(unique_files)
            unique_series = set(tuple(get_metadata(f.replace("[EXTRA]", "")).get("series") or [get_metadata(f.replace("[EXTRA]", "")).get("title")]) for f in all_files)
            series_count = len(unique_series)

            # Base cooldowns
            base_s_cd = series_count
            base_f_cd = file_count

            # Apply weights
            s_cd = int(base_s_cd * difficulty_group["cooldown"][0])
            f_cd = int(base_f_cd * difficulty_group["cooldown"][1])

            series_cooldowns.append(s_cd)
            file_cooldowns.append(f_cd)
                
        # print(series_cooldowns)
        # print(file_cooldowns)
        series_cooldowns_cache, file_cooldowns_cache = series_cooldowns, file_cooldowns
    return series_cooldowns_cache, file_cooldowns_cache

# =========================================
#         *SAVING/LOADING DATA
# =========================================

def save_config():
    """Function to save configuration"""
    files_folder = os.path.dirname(CONFIG_FILE)  # Get the folder path

    # Create the folder if it does not exist
    if not os.path.exists(files_folder):
        os.makedirs(files_folder)
    config = {
        "host": host,
        "volume_level": volume_level,
        "stream_volume_boost": stream_volume_boost,
        "back_color": OVERLAY_BACKGROUND_COLOR,
        "text_color": OVERLAY_TEXT_COLOR,
        "color_options": OVERLAY_COLOR_OPTIONS,
        "inverted_positions": inverted_positions,
        "half_points": half_points,
        "non_webm_opengl": non_webm_opengl,
        "scale_main_ui": scale_main_ui,
        "auto_fetch_missing": auto_fetch_missing,
        "special_round_warning": special_round_warning,
        "youtube_api_key": YOUTUBE_API_KEY,
        "openai_api_key": OPENAI_API_KEY,
        "title_top_info_txt": title_top_info_txt,
        "end_session_txt": end_session_txt,
        "directory": directory,
        "lightning_mode_settings": lightning_mode_settings,
        "selected_light_mode_settings": selected_light_mode_settings,
        "saved_lightning_mode_settings": saved_lightning_mode_settings,
        "playlist": playlist,
        "directory_files": directory_files
    }
    update_current_index(save = False)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_config():
    """Function to load configuration"""
    global directory_files, directory, playlist, title_top_info_txt, end_session_txt, host, YOUTUBE_API_KEY, OPENAI_API_KEY
    global lightning_mode_settings, selected_light_mode_settings, saved_lightning_mode_settings, bonus_points
    global OVERLAY_BACKGROUND_COLOR, OVERLAY_TEXT_COLOR, INVERSE_OVERLAY_BACKGROUND_COLOR, INVERSE_OVERLAY_TEXT_COLOR, MIDDLE_OVERLAY_BACKGROUND_COLOR
    global inverted_colors, inverted_positions, half_points, volume_level, stream_volume_boost, OVERLAY_COLOR_OPTIONS, non_webm_opengl, scale_main_ui, auto_fetch_missing, special_round_warning
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            host = config.get("host", "")
            title_top_info_txt = config.get("title_top_info_txt", "")
            end_session_txt = config.get("end_session_txt", "")
            playlist = config.get("playlist", copy.deepcopy(BLANK_PLAYLIST))
            # Ensure backward compatibility for background_track_history
            if "background_track_history" not in playlist:
                playlist["background_track_history"] = []
            directory_files = config.get("directory_files", {})
            directory = config.get("directory", "")
            YOUTUBE_API_KEY = config.get("youtube_api_key", "")
            OPENAI_API_KEY = config.get("openai_api_key", "")
            lightning_mode_settings = update_lightning_mode_settings(config.get("lightning_mode_settings", copy.deepcopy(lightning_mode_settings_default)))
            selected_light_mode_settings = config.get("selected_light_mode_settings", "")
            saved_lightning_mode_settings = config.get("saved_lightning_mode_settings", {})
            inverted_colors = config.get("inverted_colors", False)
            inverted_positions = config.get("inverted_positions", False)
            half_points = config.get("half_points", False)
            non_webm_opengl = config.get("non_webm_opengl", False)
            scale_main_ui = config.get("scale_main_ui", False)
            auto_fetch_missing = config.get("auto_fetch_missing", False)
            special_round_warning = config.get("special_round_warning", True)
            volume_level = config.get("volume_level", 100)
            stream_volume_boost = config.get("stream_volume_boost", 0)
            try:
                set_volume(volume_level)
            except Exception as e:
                pass
            if not selected_light_mode_settings:
                lightning_mode_settings = update_lightning_mode_settings(copy.deepcopy(lightning_mode_settings_default))
            elif selected_light_mode_settings in saved_lightning_mode_settings:
                lightning_mode_settings = update_lightning_mode_settings(saved_lightning_mode_settings[selected_light_mode_settings])
            if OPENAI_API_KEY:
                set_openai_client_key()
            try:
                update_playlist_name()
                update_current_index()
            except Exception as e:
                pass
            if half_points:
                bonus_points = ['½ PT', '1 PT', '½ PT']
            else:
                bonus_points = ['1 PT', '2 PTs', '2 PTs']
            OVERLAY_COLOR_OPTIONS = config.get("color_options", ["black", "white"])
            OVERLAY_BACKGROUND_COLOR = config.get("back_color", "black")
            OVERLAY_TEXT_COLOR = config.get("text_color", "white")
            INVERSE_OVERLAY_BACKGROUND_COLOR = config.get("text_color", "white")
            INVERSE_OVERLAY_TEXT_COLOR = config.get("back_color", "black")
            MIDDLE_OVERLAY_BACKGROUND_COLOR = interpolate_color(OVERLAY_BACKGROUND_COLOR, INVERSE_OVERLAY_BACKGROUND_COLOR, 0.6)
            send_scoreboard_colors()
            send_scoreboard_align()
    except Exception as e:
        os.remove(CONFIG_FILE)
        print(f"Error loading config: {e}")
        return False
    return False

def interpolate_color(color1, color2, factor=0.3):
    """
    Interpolate between two colors.
    Args:
        color1: Starting color (hex string or color name)
        color2: Ending color (hex string or color name)
        factor: Float between 0.0 and 1.0 (0.0 = color1, 1.0 = color2, 0.5 = halfway)
    Returns:
        Hex color string
    """
    # Convert both colors to RGB using tkinter's color resolution
    rgb1 = color_to_rgb(color1)
    rgb2 = color_to_rgb(color2)
    
    # Clamp factor between 0 and 1
    factor = max(0.0, min(1.0, factor))
    
    # Interpolate each RGB component
    r = rgb1[0] + (rgb2[0] - rgb1[0]) * factor
    g = rgb1[1] + (rgb2[1] - rgb1[1]) * factor
    b = rgb1[2] + (rgb2[2] - rgb1[2]) * factor
    
    return rgb_to_hex((int(r), int(g), int(b)))

# Color interpolation functions
def color_to_rgb(color):
    """Convert any color (hex, name, etc.) to RGB tuple using tkinter"""
    try:
        # Create a temporary root window if needed
        temp_root = None
        if 'root' not in globals() or root is None:
            temp_root = tk.Tk()
            temp_root.withdraw()  # Hide the temporary window
            widget_parent = temp_root
        else:
            widget_parent = root
            
        # Create a temporary tkinter widget to resolve color names
        temp_widget = tk.Label(widget_parent)
        # Use winfo_rgb to convert any color format to RGB values (0-65535 range)
        rgb_16bit = temp_widget.winfo_rgb(color)
        temp_widget.destroy()
        
        # Clean up temporary root if we created one
        if temp_root:
            temp_root.destroy()
            
        # Convert from 16-bit (0-65535) to 8-bit (0-255) RGB
        return tuple(int(val / 257) for val in rgb_16bit)
    except (tk.TclError, NameError):
        # If color is invalid, try parsing as hex manually
        if isinstance(color, str) and color.startswith('#'):
            hex_color = color.lstrip('#')
            if len(hex_color) == 3:  # Handle short hex like #FFF
                hex_color = ''.join([c*2 for c in hex_color])
            try:
                return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            except (ValueError, IndexError):
                pass
        # Default to gray if all else fails
        return (128, 128, 128)

def rgb_to_hex(rgb):
    """Convert RGB tuple to hex color"""
    return "#{:02x}{:02x}{:02x}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))

def show_settings_popup():
    """Opens a settings popup for editing configuration values."""
    global volume_level, OVERLAY_BACKGROUND_COLOR, OVERLAY_TEXT_COLOR, inverted_positions, half_points
    global YOUTUBE_API_KEY, OPENAI_API_KEY, title_top_info_txt, end_session_txt
    
    def is_valid_color(color):
        """Validate if a color name or hex code is valid"""
        if not color:
            return False
        
        # Check if it's a valid hex color (3 or 6 digits)
        if color.startswith('#'):
            hex_part = color[1:]
            if len(hex_part) == 3 or len(hex_part) == 6:
                try:
                    int(hex_part, 16)  # Try to parse as hex
                    return True
                except ValueError:
                    return False
            return False
        
        # Test if it's a valid color name by trying to create a temporary widget
        try:
            test_frame = tk.Frame(settings_window, bg=color)
            test_frame.destroy()  # Clean up immediately
            return True
        except tk.TclError:
            return False
    
    def add_color(color_var, dropdown):
        global OVERLAY_COLOR_OPTIONS
        """Add a custom color to the dropdown with validation"""
        new_color = simpledialog.askstring("Add Color", 
            "Enter color name or hex code:\n\n" +
            "Examples:\n" +
            "• Color names: darkblue, lightgreen, gold\n" +
            "• Hex codes: #FF5733, #00FF00, #123ABC")
        
        if new_color:
            new_color = new_color.strip()
            
            if new_color in OVERLAY_COLOR_OPTIONS:
                messagebox.showinfo("Color Already Exists", f"'{new_color}' is already in the color list.")
                return
            
            if is_valid_color(new_color):
                OVERLAY_COLOR_OPTIONS.append(new_color)
                dropdown['values'] = OVERLAY_COLOR_OPTIONS
                color_var.set(new_color)
            else:
                messagebox.showerror("Invalid Color", 
                    f"'{new_color}' is not a valid color.\n\n" +
                    "Please use:\n" +
                    "• Valid color names (red, blue, darkgreen, etc.)\n" +
                    "• Valid hex codes (#FF5733, #00FF00, etc.)")
    
    def delete_color(color_var, back_color_dropdown, text_color_dropdown):
        """Delete a custom color from the dropdown with confirmation"""
        current_color = color_var.get()
        
        if not current_color:
            messagebox.showwarning("No Color Selected", "Please select a color from the dropdown to delete.")
            return
        
        # Don't allow deletion of default colors (first 16 are defaults)
        default_colors = ["black", "white", "red", "green", "blue", "yellow", "cyan", "magenta", "gray", "orange", "purple", "pink", "brown", "lime", "navy", "maroon"]
        if current_color in default_colors:
            messagebox.showwarning("Cannot Delete", f"'{current_color}' is a default color and cannot be deleted.")
            return
        
        # Confirm deletion
        confirm = messagebox.askyesno("Delete Color", f"Are you sure you want to delete '{current_color}' from the color list?")
        if not confirm:
            return
        
        # Remove from global color options
        if current_color in OVERLAY_COLOR_OPTIONS:
            OVERLAY_COLOR_OPTIONS.remove(current_color)
            
            # Update both dropdowns
            back_color_dropdown['values'] = OVERLAY_COLOR_OPTIONS
            text_color_dropdown['values'] = OVERLAY_COLOR_OPTIONS
            
            # Reset to default color if the deleted color was selected
            color_var.set("black")
    
    def save_settings():
        """Save all settings with visual feedback"""
        global volume_level, stream_volume_boost, OVERLAY_BACKGROUND_COLOR, OVERLAY_TEXT_COLOR, inverted_positions, half_points
        global YOUTUBE_API_KEY, OPENAI_API_KEY, title_top_info_txt, end_session_txt, non_webm_opengl, scale_main_ui, auto_fetch_missing, special_round_warning
        
        try:
            # Capture original scale_main_ui value to detect changes
            original_scale_main_ui = scale_main_ui
            
            # Update global variables
            volume_level = int(volume_var.get())
            stream_volume_boost = int(stream_volume_var.get())
            OVERLAY_BACKGROUND_COLOR = back_color_var.get()
            OVERLAY_TEXT_COLOR = text_color_var.get()
            inverted_positions = inverted_pos_var.get()
            half_points = half_points_var.get()
            non_webm_opengl = non_webm_opengl_var.get()
            scale_main_ui = scale_main_ui_var.get()
            auto_fetch_missing = auto_fetch_missing_var.get()
            special_round_warning = special_round_warning_var.get()
            YOUTUBE_API_KEY = youtube_key_var.get()
            OPENAI_API_KEY = openai_key_var.get()
            title_top_info_txt = title_info_var.get()
            end_session_txt = end_session_var.get()
            
            # Check if scale_main_ui changed
            scale_ui_changed = (original_scale_main_ui != scale_main_ui)
            
            # Save to config file
            save_config()
            
            # Reload config to update all dependent global variables and UI elements
            load_config()
            
            # Show visual feedback on button
            save_btn.config(text="SAVED!", bg="darkgreen")
            settings_window.after(300, lambda: save_btn.config(text="SAVE SETTINGS", bg="black"))
            
            # Show restart dialog if scale_main_ui changed
            if scale_ui_changed:
                messagebox.showinfo("Restart Required", 
                                   "The 'Scale Main UI' setting has been changed.\n\n"
                                   "Please restart the application for this change to take effect.")
            
        except ValueError as e:
            messagebox.showerror("Invalid Value", f"Volume levels must be valid integers.\nError: {e}")
    
    # Create popup window
    settings_window = tk.Toplevel(bg=BACKGROUND_COLOR)
    settings_window.title("Configuration Settings")
    settings_window.resizable(False, False)
    
    # Tooltip class for hover explanations
    class ToolTip:
        def __init__(self, widget, text):
            self.widget = widget
            self.text = text
            self.tooltip_window = None
            self.widget.bind("<Enter>", self.show_tooltip)
            self.widget.bind("<Leave>", self.hide_tooltip)
        
        def show_tooltip(self, event=None):
            if self.tooltip_window or not self.text:
                return
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            self.tooltip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tw.attributes("-topmost", True)
            label = tk.Label(tw, text=self.text, justify='left',
                           background="#ffffe0", relief='solid', borderwidth=1,
                           font=("Arial", 9), wraplength=300)
            label.pack()
        
        def hide_tooltip(self, event=None):
            if self.tooltip_window:
                self.tooltip_window.destroy()
                self.tooltip_window = None
    
    # Setting descriptions
    setting_descriptions = {
        "Volume Level": "Master volume level for all audio playback (0-100).",
        "Stream Volume Boost": "Additional volume boost specifically for stream audio from youtube clips/trailers.",
        "Background Color": "Background color of overlay windows.",
        "Text Color": "Text color displayed in overlay windows.",
        "Inverted Positions": "Swaps alignment of some elements to adjust for scoreboard position. Enable if scoreboard is aligned right.",
        "Half Points": "Changes the display of some bonus rounds to half points.",
        "Non-WebM OpenGL": "Uses OpenGL for non-WebM video playback (may improve performance).",
        "Scale Main UI": "Scales the main UI based on screen resolution. Requires restart.",
        "Auto Fetch Missing": "Automatically fetches metadata if it's not found while playing themes.",
        "Special Round Warning": "Shows a warning before special rounds begin.",
        "YouTube API Key": "API key for YouTube integration features. Required for Clip and Ost lightning rounds.",
        "OpenAI API Key": "API key for OpenAI/ChatGPT integration features. Required for Trivia and Emoji lightning rounds.",
        "Title Only Info Text": "Custom text displayed above title when showing title-only information.",
        "End Session Text": "Custom text displayed at the top of the end session display."
    }
    
    # Main frame (no scrollbar needed)
    main_frame = tk.Frame(settings_window, bg=BACKGROUND_COLOR)
    main_frame.pack(padx=15, pady=15)
    
    # Volume Level
    volume_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    volume_frame.pack(fill="x", pady=5)
    volume_label = tk.Label(volume_frame, text="Volume Level:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    volume_label.pack(side="left")
    ToolTip(volume_label, setting_descriptions["Volume Level"])
    volume_var = tk.StringVar(value=str(volume_level))
    volume_entry = tk.Entry(volume_frame, textvariable=volume_var, bg="black", fg="white", width=10)
    volume_entry.pack(side="left", padx=(5, 0))
    
    # Stream Volume Boost
    stream_volume_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    stream_volume_frame.pack(fill="x", pady=5)
    stream_volume_label = tk.Label(stream_volume_frame, text="Stream Volume Boost:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    stream_volume_label.pack(side="left")
    ToolTip(stream_volume_label, setting_descriptions["Stream Volume Boost"])
    stream_volume_var = tk.StringVar(value=str(stream_volume_boost))
    stream_volume_entry = tk.Entry(stream_volume_frame, textvariable=stream_volume_var, bg="black", fg="white", width=10)
    stream_volume_entry.pack(side="left", padx=(5, 0))
    
    # Background Color
    back_color_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    back_color_frame.pack(fill="x", pady=5)
    back_color_label = tk.Label(back_color_frame, text="Background Color:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    back_color_label.pack(side="left")
    ToolTip(back_color_label, setting_descriptions["Background Color"])
    back_color_var = tk.StringVar(value=OVERLAY_BACKGROUND_COLOR)
    back_color_dropdown = ttk.Combobox(back_color_frame, textvariable=back_color_var, values=OVERLAY_COLOR_OPTIONS, width=15)
    back_color_dropdown.pack(side="left", padx=(5, 2))
    tk.Button(back_color_frame, text="➕", command=lambda: add_color(back_color_var, back_color_dropdown), 
             bg="black", fg="white", width=3).pack(side="left", padx=(0, 2))
    tk.Button(back_color_frame, text="❌", command=lambda: delete_color(back_color_var, back_color_dropdown, text_color_dropdown), 
             bg="black", fg="white", width=3).pack(side="left")
    
    # Text Color
    text_color_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    text_color_frame.pack(fill="x", pady=5)
    text_color_label = tk.Label(text_color_frame, text="Text Color:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    text_color_label.pack(side="left")
    ToolTip(text_color_label, setting_descriptions["Text Color"])
    text_color_var = tk.StringVar(value=OVERLAY_TEXT_COLOR)
    text_color_dropdown = ttk.Combobox(text_color_frame, textvariable=text_color_var, values=OVERLAY_COLOR_OPTIONS, width=15)
    text_color_dropdown.pack(side="left", padx=(5, 2))
    tk.Button(text_color_frame, text="➕", command=lambda: add_color(text_color_var, text_color_dropdown), 
             bg="black", fg="white", width=3).pack(side="left", padx=(0, 2))
    tk.Button(text_color_frame, text="❌", command=lambda: delete_color(text_color_var, back_color_dropdown, text_color_dropdown), 
             bg="black", fg="white", width=3).pack(side="left")
    
    # Inverted Positions
    inverted_pos_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    inverted_pos_frame.pack(fill="x", pady=5)
    inverted_pos_label = tk.Label(inverted_pos_frame, text="Inverted Positions:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    inverted_pos_label.pack(side="left")
    ToolTip(inverted_pos_label, setting_descriptions["Inverted Positions"])
    inverted_pos_var = tk.BooleanVar(value=inverted_positions)
    inverted_pos_text = tk.StringVar(value="Enabled" if inverted_positions else "Disabled")
    inverted_pos_btn = tk.Checkbutton(inverted_pos_frame, variable=inverted_pos_var, textvariable=inverted_pos_text, 
                                     bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                     command=lambda: inverted_pos_text.set("Enabled" if inverted_pos_var.get() else "Disabled"))
    inverted_pos_btn.pack(side="left", padx=(5, 0))
    
    # Half Points
    half_points_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    half_points_frame.pack(fill="x", pady=5)
    half_points_label = tk.Label(half_points_frame, text="Half Points:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    half_points_label.pack(side="left")
    ToolTip(half_points_label, setting_descriptions["Half Points"])
    half_points_var = tk.BooleanVar(value=half_points)
    half_points_text = tk.StringVar(value="Enabled" if half_points else "Disabled")
    half_points_btn = tk.Checkbutton(half_points_frame, variable=half_points_var, textvariable=half_points_text, 
                                    bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                    command=lambda: half_points_text.set("Enabled" if half_points_var.get() else "Disabled"))
    half_points_btn.pack(side="left", padx=(5, 0))
    
    # Non-WebM OpenGL
    non_webm_opengl_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    non_webm_opengl_frame.pack(fill="x", pady=5)
    non_webm_opengl_label = tk.Label(non_webm_opengl_frame, text="Non-WebM OpenGL:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    non_webm_opengl_label.pack(side="left")
    ToolTip(non_webm_opengl_label, setting_descriptions["Non-WebM OpenGL"])
    non_webm_opengl_var = tk.BooleanVar(value=non_webm_opengl)
    non_webm_opengl_text = tk.StringVar(value="Enabled" if non_webm_opengl else "Disabled")
    non_webm_opengl_btn = tk.Checkbutton(non_webm_opengl_frame, variable=non_webm_opengl_var, textvariable=non_webm_opengl_text, 
                                        bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                        command=lambda: non_webm_opengl_text.set("Enabled" if non_webm_opengl_var.get() else "Disabled"))
    non_webm_opengl_btn.pack(side="left", padx=(5, 0))
    
    # Scale Main UI
    scale_main_ui_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    scale_main_ui_frame.pack(fill="x", pady=5)
    scale_main_ui_label = tk.Label(scale_main_ui_frame, text="Scale Main UI:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    scale_main_ui_label.pack(side="left")
    ToolTip(scale_main_ui_label, setting_descriptions["Scale Main UI"])
    scale_main_ui_var = tk.BooleanVar(value=scale_main_ui)
    scale_main_ui_text = tk.StringVar(value="Enabled" if scale_main_ui else "Disabled")
    scale_main_ui_btn = tk.Checkbutton(scale_main_ui_frame, variable=scale_main_ui_var, textvariable=scale_main_ui_text, 
                                      bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                      command=lambda: scale_main_ui_text.set("Enabled" if scale_main_ui_var.get() else "Disabled"))
    scale_main_ui_btn.pack(side="left", padx=(5, 0))
    
    # Auto Fetch Missing
    auto_fetch_missing_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    auto_fetch_missing_frame.pack(fill="x", pady=5)
    auto_fetch_missing_label = tk.Label(auto_fetch_missing_frame, text="Auto Fetch Missing:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    auto_fetch_missing_label.pack(side="left")
    ToolTip(auto_fetch_missing_label, setting_descriptions["Auto Fetch Missing"])
    auto_fetch_missing_var = tk.BooleanVar(value=auto_fetch_missing)
    auto_fetch_missing_text = tk.StringVar(value="Enabled" if auto_fetch_missing else "Disabled")
    auto_fetch_missing_btn = tk.Checkbutton(auto_fetch_missing_frame, variable=auto_fetch_missing_var, textvariable=auto_fetch_missing_text, 
                                           bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                           command=lambda: auto_fetch_missing_text.set("Enabled" if auto_fetch_missing_var.get() else "Disabled"))
    auto_fetch_missing_btn.pack(side="left", padx=(5, 0))
    
    # Special Round Warning
    special_round_warning_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    special_round_warning_frame.pack(fill="x", pady=5)
    special_round_warning_label = tk.Label(special_round_warning_frame, text="Special Round Warning:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    special_round_warning_label.pack(side="left")
    ToolTip(special_round_warning_label, setting_descriptions["Special Round Warning"])
    special_round_warning_var = tk.BooleanVar(value=special_round_warning)
    special_round_warning_text = tk.StringVar(value="Enabled" if special_round_warning else "Disabled")
    special_round_warning_btn = tk.Checkbutton(special_round_warning_frame, variable=special_round_warning_var, textvariable=special_round_warning_text, 
                                           bg=BACKGROUND_COLOR, fg="white", selectcolor="black",
                                           command=lambda: special_round_warning_text.set("Enabled" if special_round_warning_var.get() else "Disabled"))
    special_round_warning_btn.pack(side="left", padx=(5, 0))
    
    # YouTube API Key
    youtube_key_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    youtube_key_frame.pack(fill="x", pady=5)
    youtube_key_label = tk.Label(youtube_key_frame, text="YouTube API Key:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    youtube_key_label.pack(side="left")
    ToolTip(youtube_key_label, setting_descriptions["YouTube API Key"])
    youtube_key_var = tk.StringVar(value=YOUTUBE_API_KEY)
    youtube_key_entry = tk.Entry(youtube_key_frame, textvariable=youtube_key_var, bg="black", fg="white", width=30, show="*")
    youtube_key_entry.pack(side="left", padx=(5, 0))
    
    # OpenAI API Key
    openai_key_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    openai_key_frame.pack(fill="x", pady=5)
    openai_key_label = tk.Label(openai_key_frame, text="OpenAI API Key:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    openai_key_label.pack(side="left")
    ToolTip(openai_key_label, setting_descriptions["OpenAI API Key"])
    openai_key_var = tk.StringVar(value=OPENAI_API_KEY)
    openai_key_entry = tk.Entry(openai_key_frame, textvariable=openai_key_var, bg="black", fg="white", width=30, show="*")
    openai_key_entry.pack(side="left", padx=(5, 0))
    
    # Title Top Info Text
    title_info_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    title_info_frame.pack(fill="x", pady=5)
    title_info_label = tk.Label(title_info_frame, text="Title Only Info Text:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    title_info_label.pack(side="left")
    ToolTip(title_info_label, setting_descriptions["Title Only Info Text"])
    title_info_var = tk.StringVar(value=title_top_info_txt)
    title_info_entry = tk.Entry(title_info_frame, textvariable=title_info_var, bg="black", fg="white", width=30)
    title_info_entry.pack(side="left", padx=(5, 0))
    
    # End Session Text
    end_session_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    end_session_frame.pack(fill="x", pady=5)
    end_session_label = tk.Label(end_session_frame, text="End Session Text:", bg=BACKGROUND_COLOR, fg="white", width=20, anchor="w")
    end_session_label.pack(side="left")
    ToolTip(end_session_label, setting_descriptions["End Session Text"])
    end_session_var = tk.StringVar(value=end_session_txt)
    end_session_entry = tk.Entry(end_session_frame, textvariable=end_session_var, bg="black", fg="white", width=30)
    end_session_entry.pack(side="left", padx=(5, 0))
    
    # Buttons
    button_frame = tk.Frame(main_frame, bg=BACKGROUND_COLOR)
    button_frame.pack(fill="x", pady=(20, 0))
    
    save_btn = tk.Button(button_frame, text="SAVE SETTINGS", command=save_settings, 
                        bg="black", fg="white", font=("Arial", 12, "bold"), width=15)
    save_btn.pack(side="left", padx=(3, 10))
    
    cancel_btn = tk.Button(button_frame, text="CANCEL", command=settings_window.destroy, 
                          bg="black", fg="white", font=("Arial", 12, "bold"), width=15)
    cancel_btn.pack(side="left")

def update_playlist_name(name=None):
    if name:
        playlist["name"] = name
    extra_text = ""
    if playlist.get("infinite"):
        extra_text = " ∞"
    root.title(f"[{get_themes_played_count()}] {WINDOW_TITLE} - {playlist["name"]}{extra_text}")

def save_metadata():
    """Ensures the metadata folder exists before saving metadata files."""
    metadata_folder = os.path.dirname(FILE_METADATA_FILE)  # Get the folder path

    # Create the folder if it does not exist
    if not os.path.exists(metadata_folder):
        os.makedirs(metadata_folder)

    # Save metadata files
    with open(FILE_METADATA_FILE, "w") as f:
        json.dump(file_metadata, f, indent=4)  # Pretty-print for readability

    deep_merge(anime_metadata, anime_metadata_overrides)
    with open(ANIME_METADATA_FILE, "w") as f:
        json.dump(anime_metadata, f, indent=4)

    with open(ANIDB_METADATA_FILE, "w") as f:
        json.dump(anidb_metadata, f, indent=4)
    
    with open(AI_METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(ai_metadata, f, indent=4, ensure_ascii=False)

def save_metadata_overrides():
    with open(ANIME_METADATA_OVERRIDES_FILE, "w") as f:
        json.dump(anime_metadata_overrides, f, indent=4)

def load_metadata():
    global file_metadata, anime_metadata, anidb_metadata, anime_metadata_overrides, ai_metadata
    if os.path.exists(FILE_METADATA_FILE):
        with open(FILE_METADATA_FILE, "r") as f:
            file_metadata = json.load(f)
            invalidate_file_metadata_cache()  # Invalidate cache when file_metadata is loaded
            print("Loaded file metadata for " + str(len(file_metadata)) + " files...")
    if os.path.exists(ANIME_METADATA_FILE):
        with open(ANIME_METADATA_FILE, "r") as a:
            anime_metadata = json.load(a)
            print("Loaded anime metadata for " + str(len(anime_metadata)) + " entries...")
    if os.path.exists(ANIDB_METADATA_FILE):
        with open(ANIDB_METADATA_FILE, "r") as a:
            anidb_metadata = json.load(a)
            print("Loaded anidb metadata for " + str(len(anidb_metadata)) + " entries...")
    else:
        split_anime_anidb_metadata()
    
    if os.path.exists(AI_METADATA_FILE):
        with open(AI_METADATA_FILE, "r", encoding="utf-8") as f:
            ai_metadata = json.load(f)
            # Clean up compound emojis when loading
            for mal_id, data in ai_metadata.items():
                if "emojis" in data:
                    data["emojis"] = clean_compound_emojis(data["emojis"])
            print(f"Loaded AI metadata for {len(ai_metadata)} entries.")

    if os.path.exists(manual_metadata_file):
        with open(manual_metadata_file, "r", encoding="utf-8") as m:
            manual_metadata = json.load(m)
            for entry in manual_metadata:
                anime_metadata[entry] = manual_metadata[entry]
                if anime_metadata[entry].get("reviews") and (is_game(anime_metadata[entry])):
                    anime_metadata[entry]["members"] = anime_metadata[entry].get("reviews") * REVIEW_MODIFIER
                if anime_metadata[entry].get("release"):
                    anime_metadata[entry]["aired"] = anime_metadata[entry].get("release")
                    anime_metadata[entry]["season"] = aired_to_season_year(anime_metadata[entry].get("release"))
                anime_metadata[entry]["popularity"] = estimate_manual_popularity(anime_metadata[entry].get("members"))
                anime_metadata[entry]["rank"] = estimate_manual_rank(anime_metadata[entry].get("score"))
    if os.path.exists(ANIME_METADATA_OVERRIDES_FILE):
        with open(ANIME_METADATA_OVERRIDES_FILE, "r") as a:
            anime_metadata_overrides = json.load(a)
            print("Loaded metadata overrides for " + str(len(anime_metadata_overrides)) + " entries...")
            deep_merge(anime_metadata, anime_metadata_overrides)

def split_anime_anidb_metadata():
    global anime_metadata, anidb_metadata

    for file, data in file_metadata.items():
        if data.get("anidb"):
            anime_data = anime_metadata.get(data.get("mal"))
            if anime_data:
                anidb_data = {}
                for field in ["characters", "episode_info","tags"]:
                    if anime_data.get(field):
                        anidb_data[field] = anime_data.get(field)
                    if field in anime_metadata[data.get("mal")]:
                        del anime_metadata[data.get("mal")][field]
                if anidb_data:
                    anidb_metadata[data.get("anidb")] = anidb_data
    save_metadata()


REVIEW_MODIFIER = 500
def estimate_manual_popularity(members):
    """Estimate popularity rank based on member count."""
    if not members:
        return None # Return N/A if no data is available

    # Load all known anime popularity & members counts
    known_popularities = []
    for anime in anime_metadata.values():
        if anime.get("members") and anime.get("popularity") not in ["N/A", None]:
            known_popularities.append((anime["members"], anime["popularity"]))

    if not known_popularities:
        return None  # If no valid data, return N/A

    # Sort by members to find ranking distribution
    known_popularities.sort(reverse=True, key=lambda x: x[0])  # Most members first

    # Find the closest position based on members
    for index, (known_members, known_popularity) in enumerate(known_popularities):
        if (members) >= known_members:
            return known_popularity  # Assign the closest popularity rank

    # If it's lower than all known values, assign the worst rank
    return max(pop for _, pop in known_popularities)

def estimate_manual_rank(score):
    """Estimate rank based on score."""
    if not score:
        return None # Return N/A if no data is available

    # Load all known anime rank & score
    known_ranks = []
    for anime in anime_metadata.values():
        if anime.get("score") and anime.get("rank") not in ["N/A", None]:
            known_ranks.append((anime["score"], anime["rank"]))

    if not known_ranks:
        return None  # If no valid data, return N/A

    # Sort by score to find ranking distribution
    known_ranks.sort(reverse=True, key=lambda x: x[0])  # Highest score first

    # Find the closest position based on score
    for index, (known_score, known_rank) in enumerate(known_ranks):
        if score >= known_score:
            return known_rank  # Assign the closest rank

    # If it's lower than all known values, assign the worst rank
    return max(pop for _, pop in known_ranks)

def deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        elif isinstance(value, list) and isinstance(base.get(key), list) and key == "songs":
            merge_songs_by_slug(base[key], value)
        else:
            base[key] = value

def merge_songs_by_slug(base_songs, override_songs):
    slug_index = {song.get("slug"): song for song in base_songs if isinstance(song, dict)}
    for override_song in override_songs:
        slug = override_song.get("slug")
        if not slug:
            continue
        base_song = slug_index.get(slug)
        if base_song:
            deep_merge(base_song, override_song)
        else:
            base_songs.append(override_song)  # New song, not found in base

# =========================================
#           *SAVE/*LOAD PLAYLISTS
# =========================================

def save(autosave = False):
    save_playlist(playlist, playlist["current_index"], root, autosave)

def save_playlist(playlist, index, parent, autosave):
    """Opens a popup to enter a name, then saves the playlist, and index as JSON."""
    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)

    if autosave:
        name = playlist["name"]
    else:
        # Ask for a playlist name
        name = simpledialog.askstring("Save Playlist", "Enter playlist name:", initialvalue=playlist["name"], parent=parent)
        if not name:
            return  # User canceled
        elif name.lower() == "missing artists":
            check_missing_artists()
    playlist["name"] = name
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")

    # Save playlist data
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(playlist, f, indent=4)
    
    update_playlist_name(name)
    save_config()
    print(f"Playlist saved as {filename}")

playlist_loaded = False

def load_playlist(index):
    """Loads a saved playlist from JSON."""
    global playlist_loaded, playlist
    # Determine which dictionary to use based on the currently loaded list
    if list_loaded == "load_playlist":
        playlists = get_playlists_dict(exclude_system=True)
    elif list_loaded == "load_system_playlist":
        playlists = get_playlists_dict(system_only=True)
    else:
        playlists = get_playlists_dict()
    
    if index not in playlists:
        print(f"Invalid playlist index: {index}")
        return None
    name = playlists[index]
    
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")

    if not os.path.exists(filename):
        print(f"Playlist {name} not found.")
        return None

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    global playlist, playlist_changed
    if playlist["name"] != "" and not disable_shortcuts:
        save(True)
    else:
        confirm_save_playlist("loading a new playlist")
    playlist_changed = False
    playlist = data
    update_playlist_name()
    print(f"Loaded playlist: {name}")
    playlist_loaded = True
    create_first_row_buttons()
    if playlist.get("infinite"):
        refresh_pop_time_groups()
    if name.lower() == "missing artists":
        check_missing_artists()
    update_current_index()
    save_config()
    reload_playlist(True)

def load(update = False):
    selected = -1
    playlists = get_playlists_dict(exclude_system=True)
    # Find the selected index in the filtered dictionary
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
        
    show_list("load_playlist", right_column, playlists, get_playlist_name, load_playlist, selected, update, delete_playlist)

def load_system_playlist(update = False):
    selected = -1
    playlists = get_playlists_dict(system_only=True)
    # Find the selected index in the filtered dictionary
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
        
    show_list("load_system_playlist", right_column, playlists, get_playlist_name, load_playlist, selected, update, delete_playlist)

def delete(update = False):
    selected = -1
    playlists = get_playlists_dict()
    for key, value in playlists.items(): 
        if playlist["name"] == value:
            selected = key
            break
        
    show_list("delete_playlist", right_column, playlists, get_playlist_name, delete_playlist, selected, update)

def delete_playlist(index):
    """Deletes a playlist by index after confirmation."""
    # Determine which dictionary to use based on the currently loaded list
    if list_loaded == "load_playlist":
        playlists = get_playlists_dict(exclude_system=True)
    elif list_loaded == "load_system_playlist":
        playlists = get_playlists_dict(system_only=True)
    else:
        playlists = get_playlists_dict()
    
    if index not in playlists:
        print("Invalid playlist index.")
        return

    name = playlists[index]
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")

    # Confirmation box
    confirm = messagebox.askyesno("Delete Playlist", f"Are you sure you want to delete '{name}'?")
    if not confirm:
        return  # User canceled

    # Delete the file
    try:
        os.remove(filename)
        if check_theme_cache.get("name"):
            del check_theme_cache["name"]
        print(f"Deleted playlist: {name}")
    except Exception as e:
        print(f"Error deleting playlist: {e}")
        return

    # Refresh the list display
    reload_playlist(True)

def delete_file_by_filename(filename):
    """Find the full path from directory_files and delete the file after confirmation."""
    filepath = directory_files.get(filename)
    
    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Delete File", f"The file does not exist or is not found:\n{filename}")
        return

    confirm = messagebox.askyesno("Delete File", f"Are you sure you want to delete this file?\n\n{filename}")
    if confirm:
        try:
            stop()
            os.remove(filepath)
            messagebox.showinfo("File Deleted", f"Successfully deleted:\n{filename}")
            print(f"Deleted file: {filename}")
            # Optionally, remove from your directory_files dict too:
            del directory_files[filename]
        except Exception as e:
            messagebox.showerror("Error", f"Could not delete file:\n{e}")
    else:
        print(f"Deletion canceled for file: {filename}")

def open_file_folder_by_filename(filename):
    """Find the full path from directory_files and open its containing folder."""
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Open Folder", f"The file does not exist or is not found:\n{filename}")
        return

    try:
        if platform.system() == "Windows":
            subprocess.run(["explorer", "/select,", os.path.normpath(filepath)])
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", "-R", filepath])
        else:  # Linux
            # This opens the folder but may not highlight the file depending on the file manager
            subprocess.run(["xdg-open", os.path.dirname(filepath)])
        print(f"Opened folder for: {filename}")
    except Exception as e:
        messagebox.showerror("Error", f"Could not open folder:\n{e}")

def rename_file_by_filename(filename):
    """Rename a file and update all relevant metadata and directory references."""
    global file_metadata, directory_files, playlist, currently_playing
    
    filepath = directory_files.get(filename)
    
    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Rename File", f"The file does not exist or is not found:\n{filename}")
        return
    
    # Get the current base name and extension
    current_base, extension = os.path.splitext(filename)
    
    # Ask for new filename using simple dialog
    new_base = simpledialog.askstring("Rename File", "Enter new filename (without extension):", initialvalue=current_base)
    
    if not new_base:
        return
    
    new_base = new_base.strip()
    
    # Check for invalid characters
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    if any(char in new_base for char in invalid_chars):
        messagebox.showerror("Invalid Name", f"Filename cannot contain: {' '.join(invalid_chars)}")
        return
    
    new_filename = new_base + extension
    
    # Build the new file path
    directory = os.path.dirname(filepath)
    new_filepath = os.path.join(directory, new_filename)
    
    # Check if the new filename already exists in directory_files
    if new_filename in directory_files and new_filename != filename:
        messagebox.showerror("Rename Error", f"A file with the name '{new_filename}' already exists in the directory list.")
        return
    
    # Check if file exists at the new path on disk
    if os.path.exists(new_filepath) and new_filepath != filepath:
        messagebox.showerror("Rename Error", f"A file already exists at:\n{new_filepath}")
        return
    
    # Stop the player if this file is currently playing (do this after getting user input)
    if currently_playing.get("filename") == filename:
        stop()

    try:
        # Rename the actual file
        os.rename(filepath, new_filepath)
        
        # Update directory_files dictionary
        if filename in directory_files:
            del directory_files[filename]
        directory_files[new_filename] = new_filepath
        
        # Update file_metadata if it exists for this file
        if filename in file_metadata:
            file_metadata[new_filename] = file_metadata[filename]
            del file_metadata[filename]
        
        # Update playlist if the file is in current playlist
        if playlist and playlist.get("playlist"):
            for i, playlist_file in enumerate(playlist["playlist"]):
                # Handle both clean filenames and [L] prefixed entries
                clean_playlist_file = playlist_file[3:] if playlist_file.startswith("[L]") else playlist_file
                if clean_playlist_file == filename:
                    prefix = "[L]" if playlist_file.startswith("[L]") else ""
                    playlist["playlist"][i] = prefix + new_filename
        
        # Update currently_playing if it's the current file
        if currently_playing.get("filename") == filename:
            currently_playing["filename"] = new_filename
            # Update playlist_entry in currently_playing if present
            if "playlist_entry" in currently_playing:
                old_entry = currently_playing["playlist_entry"]
                prefix = "[L]" if old_entry.startswith("[L]") else ""
                currently_playing["playlist_entry"] = prefix + new_filename
        
        # Save updated metadata and config
        save_metadata()
        save_config()
        
        # Update the display if this is the currently playing file
        if currently_playing.get("filename") == new_filename:
            update_metadata()
        print(f"Renamed '{filename}' to '{new_filename}'")
        
    except Exception as e:
        messagebox.showerror("Rename Error", f"Failed to rename file:\n{e}")
        print(f"Error renaming file: {e}")

def edit_file_volume_by_filename(filename):
    """Find the full path from directory_files and edit the volume using ffmpeg."""
    filepath = directory_files.get(filename)
    
    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Edit Volume", f"The file does not exist or is not found:\n{filename}")
        return

    # Prompt for volume level
    volume_str = simpledialog.askstring("Edit Volume", 
                                       "Enter volume multiplier (e.g., 0.5 for half volume, 2.0 for double volume):\n\n"
                                       "Examples:\n"
                                       "• 0.5 = 50% volume\n"
                                       "• 1.0 = original volume\n"
                                       "• 2.0 = 200% volume",
                                       initialvalue="1.0")
    
    if not volume_str:
        return  # User canceled
    
    try:
        volume_level_set = float(volume_str)
        if volume_level_set <= 0:
            messagebox.showerror("Invalid Volume", "Volume level must be greater than 0")
            return
    except ValueError:
        messagebox.showerror("Invalid Volume", "Please enter a valid number (e.g., 0.5, 1.0, 2.0)")
        return

    # Confirm the operation
    confirm = messagebox.askyesno("Edit Volume", 
                                 f"This will modify the volume of:\n{filename}\n\n"
                                 f"Volume multiplier: {volume_level_set}\n\n"
                                 "The video will be stopped and the original file will be replaced.\n"
                                 "Continue?")
    if not confirm:
        return

    # Stop the currently playing video
    stop()
    
    # Generate temporary filename
    base, ext = os.path.splitext(filepath)
    temp_filepath = f"{base}_temp_volume{ext}"
    
    try:
        # Build ffmpeg command
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", filepath,
            "-af", f"volume={volume_level_set}",
            "-c:v", "copy",  # Copy video without re-encoding
            "-y",  # Overwrite output file without asking
            temp_filepath
        ]
        
        # Run ffmpeg command with proper encoding handling
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=300)  # 5 minute timeout
        
        if result.returncode == 0:
            # Success - replace original file with the modified one
            if os.path.exists(temp_filepath):
                # Remove original file
                os.remove(filepath)
                # Rename temp file to original filename
                os.rename(temp_filepath, filepath)
                
                messagebox.showinfo("Volume Edited", 
                                  f"Successfully edited volume:\n{filename}\n\n"
                                  f"Volume multiplier: {volume_level_set}x")
                print(f"Successfully edited volume for: {filename} (volume: {volume_level_set}x)")
            else:
                messagebox.showerror("Error", "Temporary file was not created successfully")
        else:
            # Error occurred - safely decode error message
            try:
                error_msg = result.stderr if result.stderr else "Unknown ffmpeg error"
            except UnicodeDecodeError:
                error_msg = "FFmpeg error (unable to decode error message)"
            messagebox.showerror("FFmpeg Error", 
                               f"Failed to edit volume:\n\n{error_msg}")
            # Clean up temp file if it exists
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
                
    except subprocess.TimeoutExpired:
        messagebox.showerror("Timeout", "Operation timed out. The file may be too large or ffmpeg is not responding.")
        # Clean up temp file if it exists
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
    except FileNotFoundError:
        messagebox.showerror("FFmpeg Not Found", 
                           "FFmpeg is not installed or not found in PATH.\n\n"
                           "Please install FFmpeg and ensure it's available in your system PATH.")
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while editing volume:\n{e}")
        # Clean up temp file if it exists
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)

def convert_file_format_by_filename(filename):
    """Find the full path from directory_files and convert to a different format using ffmpeg."""
    filepath = directory_files.get(filename)
    
    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("File Not Found", f"The file does not exist or is not found:\n{filename}")
        return

    # Prompt for output format
    format_str = simpledialog.askstring("Convert Format", 
                                       "Enter output format (file extension):\n\n"
                                       "Examples:\n"
                                       "• mp4 - Most compatible video format\n"
                                       "• webm - Web-optimized format\n"
                                       "• mkv - Flexible container\n"
                                       "• avi - Classic video format\n"
                                       "• mov - QuickTime format\n"
                                       "• mp3 - Audio only\n"
                                       "• wav - Uncompressed audio\n\n"
                                       "Enter format without the dot:",
                                       initialvalue="webm")
    
    if not format_str:
        return
    
    # Clean the format string
    output_format = format_str.strip().lower()
    if output_format.startswith('.'):
        output_format = output_format[1:]
    
    # Generate output filename
    base, _ = os.path.splitext(filepath)
    output_filepath = f"{base}_converted.{output_format}"
    
    # Confirm the operation
    confirm = messagebox.askyesno("Convert Format", 
                                 f"This will convert:\n{filename}\n\n"
                                 f"To format: {output_format.upper()}\n"
                                 f"Output file: {os.path.basename(output_filepath)}\n\n"
                                 "Continue?")
    if not confirm:
        return

    # Stop the currently playing video
    stop()
    
    try:
        # Determine appropriate codecs and settings for the output format
        if output_format in ['mp4', 'mov']:
            # H.264 + AAC for MP4/MOV
            video_codec = "libx264"
            audio_codec = "aac"
            audio_settings = ["-b:a", "192k"]
        elif output_format == 'webm':
            # VP9 + Vorbis for WebM
            video_codec = "libvpx-vp9"
            audio_codec = "libvorbis"
            audio_settings = ["-q:a", "6"]
        elif output_format in ['mkv', 'avi']:
            # H.264 + AAC for MKV/AVI
            video_codec = "libx264"
            audio_codec = "aac"
            audio_settings = ["-b:a", "192k"]
        elif output_format == 'mp3':
            # Audio only - MP3
            video_codec = None
            audio_codec = "libmp3lame"
            audio_settings = ["-b:a", "192k"]
        elif output_format == 'wav':
            # Audio only - WAV (uncompressed)
            video_codec = None
            audio_codec = "pcm_s16le"
            audio_settings = []
        elif output_format in ['ogg', 'oga']:
            # Audio only - Ogg Vorbis
            video_codec = None
            audio_codec = "libvorbis"
            audio_settings = ["-q:a", "6"]
        else:
            # Let FFmpeg auto-detect best codecs for format
            video_codec = None
            audio_codec = None
            audio_settings = ["-b:a", "192k"]  # Default audio bitrate
        
        # Build FFmpeg command
        ffmpeg_cmd = ["ffmpeg", "-i", filepath]
        
        # Add codec settings if specified
        if video_codec:
            ffmpeg_cmd.extend(["-c:v", video_codec, "-preset", "fast"])
        elif video_codec is None and output_format not in ['mp3', 'wav', 'ogg', 'oga']:
            ffmpeg_cmd.extend(["-c:v", "copy"])  # Copy video if not audio-only
        
        if audio_codec:
            ffmpeg_cmd.extend(["-c:a", audio_codec])
            ffmpeg_cmd.extend(audio_settings)
        elif audio_codec is None:
            ffmpeg_cmd.extend(["-c:a", "copy"])  # Copy audio
        
        # Audio-only formats should exclude video
        if output_format in ['mp3', 'wav', 'ogg', 'oga']:
            ffmpeg_cmd.extend(["-vn"])  # No video
        
        ffmpeg_cmd.extend(["-y", output_filepath])
        
        print(f"Converting {filename} to {output_format.upper()} format...")
        print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        
        # Run FFmpeg conversion with progress
        result = subprocess.run(ffmpeg_cmd, text=True, encoding='utf-8', errors='ignore', timeout=900)  # 15 minute timeout
        
        if result.returncode == 0 and os.path.exists(output_filepath):
            # Success - show completion message
            success_msg = f"File converted successfully!\nSaved as: {os.path.basename(output_filepath)}"
            messagebox.showinfo("Conversion Complete", success_msg)
            print(f"✓ Conversion completed successfully: {os.path.basename(output_filepath)}")
            
            # Open folder to show the converted file
            try:
                if platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", os.path.normpath(output_filepath)])
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", "-R", output_filepath])
                else:  # Linux
                    subprocess.run(["xdg-open", os.path.dirname(output_filepath)])
            except Exception as e:
                print(f"Could not open folder: {e}")
            
            # Ask if user wants to replace original file
            replace = messagebox.askyesno("Replace Original", 
                                        f"Do you want to replace the original file with the converted version?\n\n"
                                        f"Original: {filename}\n"
                                        f"Converted: {os.path.basename(output_filepath)}\n\n"
                                        "This cannot be undone!")
            
            if replace:
                try:
                    # Replace original with converted version
                    os.remove(filepath)
                    # Rename to original filename but with new extension
                    original_base, _ = os.path.splitext(filepath)
                    new_original_path = f"{original_base}.{output_format}"
                    os.rename(output_filepath, new_original_path)
                    
                    # Update file metadata with new extension
                    original_base_name, old_ext = os.path.splitext(filename)
                    new_filename = f"{original_base_name}.{output_format}"
                    
                    # Update directory_files dictionary
                    if filename in directory_files:
                        del directory_files[filename]
                        directory_files[new_filename] = new_original_path
                    
                    # Update file_metadata if it exists for this file
                    global file_metadata
                    if filename in file_metadata:
                        # Move metadata to new filename key
                        file_metadata[new_filename] = file_metadata[filename]
                        del file_metadata[filename]
                    
                    # Update playlist if the file is in current playlist
                    global playlist
                    if playlist and playlist.get("playlist"):
                        for i, playlist_file in enumerate(playlist["playlist"]):
                            if playlist_file == filename:
                                playlist["playlist"][i] = new_filename
                    
                    # Save updated metadata and config
                    save_metadata()
                    save_config()
                    
                    messagebox.showinfo("File Replaced", f"Original file has been replaced with the converted version.\nMetadata updated for: {new_filename}")
                    print(f"Replaced {filename} with converted {output_format.upper()} version")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to replace original file:\n{e}")
        else:
            # Error occurred
            print(f"❌ FFmpeg conversion failed with return code {result.returncode}")
            messagebox.showerror("Conversion Error", 
                               f"Failed to convert file to {output_format.upper()} format.\n\n"
                               f"Check the console for detailed error information.")
            
            # Clean up output file if it exists
            if os.path.exists(output_filepath):
                os.remove(output_filepath)
                print(f"Cleaned up incomplete file: {output_filepath}")
                
    except subprocess.TimeoutExpired:
        timeout_msg = "Conversion timed out after 15 minutes"
        print(f"❌ {timeout_msg}")
        messagebox.showerror("Timeout", f"{timeout_msg}. The file may be too large or the conversion is taking too long.")
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
            print(f"Cleaned up incomplete file: {output_filepath}")
    except FileNotFoundError:
        error_msg = "FFmpeg is not installed or not found in PATH"
        print(f"❌ {error_msg}")
        messagebox.showerror("FFmpeg Not Found", 
                           f"{error_msg}.\n\n"
                           "Please install FFmpeg and ensure it's available in your system PATH.")
    except Exception as e:
        print(f"❌ Unexpected error during conversion: {e}")
        print(f"Exception type: {type(e).__name__}")
        messagebox.showerror("Error", f"An unexpected error occurred during conversion:\n\n{str(e)}\n\n"
                           "Check the console for full error details.")
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
            print(f"Cleaned up incomplete file: {output_filepath}")

def _cut_video_at_time(filename, cut_mode):
    """Shared helper function to cut video before or after current time using FFmpeg.
    
    Args:
        filename: The filename to cut
        cut_mode: 'before' to keep everything after current time, 'after' to keep everything before current time
    """
    # Check if video is loaded and get current time
    if not player.get_media():
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title, "No video is currently loaded. Please load a video first.")
        return
    
    current_time_ms = player.get_time()  # milliseconds
    if current_time_ms <= 0:
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title, "Cannot determine current playback time.")
        return
    
    current_time_sec = current_time_ms / 1000.0  # convert to precise seconds
    
    # Find the file path
    filepath = directory_files.get(filename)
    if not filepath or not os.path.exists(filepath):
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title, f"The file does not exist or is not found:\n{filename}")
        return
    
    # Confirm the operation - show precise time with milliseconds
    minutes = int(current_time_sec // 60)
    seconds = int(current_time_sec % 60)
    milliseconds = int((current_time_sec % 1) * 1000)
    time_display = f"{minutes}:{seconds:02d}.{milliseconds:03d}"
    
    if cut_mode == "before":
        confirm_title = "Cut Before Current Time"
        confirm_msg = (f"This will cut the video BEFORE the current time:\n{filename}\n\n"
                      f"Current time: {time_display}\n"
                      f"Result: Keep everything AFTER {time_display}\n\n"
                      "Continue?")
        suffix = "_cut_before"
        log_msg = f"before {time_display}"
    else:  # cut_mode == "after"
        confirm_title = "Cut After Current Time"
        confirm_msg = (f"This will cut the video AFTER the current time:\n{filename}\n\n"
                      f"Current time: {time_display}\n"
                      f"Result: Keep everything BEFORE {time_display}\n\n"
                      "Continue?")
        suffix = "_cut_after"
        log_msg = f"after {time_display}"
    
    confirm = messagebox.askyesno(confirm_title, confirm_msg)
    if not confirm:
        return
    
    # Ask for cutting method
    cutting_method = messagebox.askyesnocancel(
        "Choose Cutting Method",
        f"Choose cutting precision:\n\n"
        f"🚀 YES = FAST CUT (stream copy)\n"
        f"   • Very fast, no quality loss\n"
        f"   • May cut a few seconds off due to keyframes\n"
        f"   • Best for rough cuts\n\n"
        f"🎯 NO = PRECISE CUT (re-encode)\n"
        f"   • Frame-accurate cutting\n"
        f"   • Slower, slight quality loss\n"
        f"   • Exact timing guaranteed\n\n"
        f"CANCEL = Abort operation"
    )
    
    if cutting_method is None:  # User clicked Cancel
        return
    
    use_stream_copy = cutting_method  # True = fast, False = precise
    
    # Generate cut filename
    base, ext = os.path.splitext(filepath)
    precision_suffix = "_fast" if use_stream_copy else "_precise"
    cut_filepath = f"{base}{suffix}{precision_suffix}{ext}"
    
    try:
        # Determine appropriate codecs based on file extension with fallbacks
        _, output_ext = os.path.splitext(cut_filepath)
        output_ext = output_ext.lower()
        
        if output_ext == '.webm':
            # WebM requires VP8/VP9/AV1 video and Vorbis/Opus audio
            # Try VP9 first, fallback to VP8, then change extension to .mp4 with H.264
            video_codec_options = ["libvpx-vp9", "libvpx", "libx264"]
            audio_codec_options = ["libvorbis", "libopus", "aac"]
        elif output_ext == '.mp4':
            # MP4 works well with H.264 and AAC
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]
        elif output_ext == '.mkv':
            # MKV is flexible, use H.264 and AAC
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]
        else:
            # Default to H.264 and AAC for other formats
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]
        
        # Function to check if codec is available
        def check_codec_available(codec_name, codec_type="encoder"):
            try:
                result = subprocess.run(
                    ["ffmpeg", "-hide_banner", f"-{codec_type}s"], 
                    capture_output=True, text=True, timeout=10
                )
                return codec_name in result.stdout
            except:
                return False
        
        # Select the first available video codec
        video_codec = None
        for codec in video_codec_options:
            if check_codec_available(codec):
                video_codec = codec
                break
        
        # Select the first available audio codec
        audio_codec = None
        for codec in audio_codec_options:
            if check_codec_available(codec):
                audio_codec = codec
                break
        
        # If WebM codecs aren't available, change to MP4
        if output_ext == '.webm' and (video_codec in ["libx264", "h264"] or audio_codec == "aac"):
            print(f"Warning: WebM codecs not available, switching to MP4 format")
            base_cut_filepath = os.path.splitext(cut_filepath)[0]
            cut_filepath = base_cut_filepath + ".mp4"
            output_ext = '.mp4'
            if not video_codec:
                video_codec = "libx264"
            if not audio_codec:
                audio_codec = "aac"
        
        # Error if no suitable codecs found for precise cutting
        if not use_stream_copy:  # Only for precise cuts
            if not video_codec:
                error_msg = f"No suitable video encoder found for {output_ext} format"
                print(f"❌ {error_msg}")
                messagebox.showerror("Codec Error", 
                                   f"{error_msg}.\n\n"
                                   f"Available codecs checked: {', '.join(video_codec_options)}\n\n"
                                   "Try using fast cut (stream copy) instead, or install a more complete FFmpeg build.")
                return
            
            if not audio_codec:
                error_msg = f"No suitable audio encoder found for {output_ext} format"
                print(f"❌ {error_msg}")
                messagebox.showerror("Codec Error", 
                                   f"{error_msg}.\n\n"
                                   f"Available codecs checked: {', '.join(audio_codec_options)}\n\n"
                                   "Try using fast cut (stream copy) instead, or install a more complete FFmpeg build.")
                return
        
        # Build ffmpeg command based on cut mode and precision
        if cut_mode == "before":
            # Cut everything before current time = keep everything after
            if use_stream_copy:
                # Fast method - stream copy (may not be frame accurate)
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-ss", str(current_time_sec),  # Start from current time
                    "-i", filepath,
                    "-c", "copy",  # Copy streams without re-encoding
                    "-avoid_negative_ts", "make_zero",  # Handle timestamp issues
                    "-y",  # Overwrite output file without asking
                    cut_filepath
                ]
            else:
                # Precise method - re-encode for frame accuracy
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-i", filepath,
                    "-ss", str(current_time_sec),  # Seek after input for precision
                    "-c:v", video_codec,  # Use appropriate video codec
                    "-c:a", audio_codec,  # Use appropriate audio codec
                    "-preset", "fast",    # Fast encoding preset
                    "-avoid_negative_ts", "make_zero",
                    "-y"
                ]
                
                # Add audio quality settings based on codec
                if audio_codec == "libvorbis":
                    ffmpeg_cmd.extend(["-q:a", "6"])  # Vorbis quality 6 (~192 kbps equivalent)
                elif audio_codec == "libopus":
                    ffmpeg_cmd.extend(["-b:a", "192k"])  # Opus 192 kbps
                elif audio_codec == "aac":
                    ffmpeg_cmd.extend(["-b:a", "192k"])  # AAC 192 kbps
                elif audio_codec == "mp3":
                    ffmpeg_cmd.extend(["-b:a", "192k"])  # MP3 192 kbps
                
                ffmpeg_cmd.append(cut_filepath)
        else:  # cut_mode == "after"
            # Cut everything after current time = keep everything before
            if use_stream_copy:
                # Fast method - stream copy (may not be frame accurate)
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-i", filepath,
                    "-t", str(current_time_sec),  # Duration to keep
                    "-c", "copy",  # Copy streams without re-encoding
                    "-avoid_negative_ts", "make_zero",
                    "-y",
                    cut_filepath
                ]
            else:
                # Precise method - re-encode for frame accuracy
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-i", filepath,
                    "-t", str(current_time_sec),  # Duration to keep
                    "-c:v", video_codec,  # Use appropriate video codec
                    "-c:a", audio_codec,  # Use appropriate audio codec
                    "-preset", "fast",    # Fast encoding preset
                    "-avoid_negative_ts", "make_zero",
                    "-y"
                ]
                
                # Add audio quality settings based on codec
                if audio_codec == "libvorbis":
                    ffmpeg_cmd.extend(["-q:a", "6"])  # Vorbis quality 6 (~192 kbps equivalent)
                elif audio_codec == "libopus":
                    ffmpeg_cmd.extend(["-b:a", "192k"])  # Opus 192 kbps
                elif audio_codec == "aac":
                    ffmpeg_cmd.extend(["-b:a", "192k"])  # AAC 192 kbps
                elif audio_codec == "mp3":
                    ffmpeg_cmd.extend(["-b:a", "192k"])  # MP3 192 kbps
                
                ffmpeg_cmd.append(cut_filepath)
        
        # Show progress message for re-encoding
        if not use_stream_copy:
            print(f"Starting precise cut (re-encoding) for {filename}...")
            print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        else:
            print(f"Starting fast cut (stream copy) for {filename}...")
        
        # Run ffmpeg command with console output
        try:
            if use_stream_copy:
                # Fast method - can capture output normally
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=300)
                if result.stderr:
                    print("FFmpeg output:")
                    print(result.stderr)
            else:
                # Precise method - show real-time progress
                result = subprocess.run(ffmpeg_cmd, text=True, encoding='utf-8', errors='ignore', timeout=600)  # Longer timeout for re-encoding
        except subprocess.TimeoutExpired as e:
            print(f"FFmpeg operation timed out after {e.timeout} seconds")
            raise
        
        if result.returncode == 0 and os.path.exists(cut_filepath):
            # Success - open folder and ask about replacement
            success_msg = f"Video cut successfully!\nSaved as: {os.path.basename(cut_filepath)}"
            if not use_stream_copy:
                success_msg += "\n\n(Re-encoded for frame precision)"
            messagebox.showinfo("Cut Complete", success_msg)
            print(f"✓ Cut operation completed successfully: {os.path.basename(cut_filepath)}")
            
            # Open folder to show the cut file
            try:
                if platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", os.path.normpath(cut_filepath)])
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", "-R", cut_filepath])
                else:  # Linux
                    subprocess.run(["xdg-open", os.path.dirname(cut_filepath)])
            except Exception as e:
                print(f"Could not open folder: {e}")
            
            # Ask if user wants to replace original file
            replace = messagebox.askyesno("Replace Original", 
                                        f"Do you want to replace the original file with the cut version?\n\n"
                                        f"Original: {filename}\n"
                                        f"Cut file: {os.path.basename(cut_filepath)}\n\n"
                                        "This cannot be undone!")
            
            if replace:
                try:
                    # Stop video playback
                    stop()
                    # Replace original with cut version
                    os.remove(filepath)
                    os.rename(cut_filepath, filepath)
                    messagebox.showinfo("File Replaced", f"Original file has been replaced with the cut version.")
                    print(f"Replaced {filename} with cut version ({log_msg})")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to replace original file:\n{e}")
        else:
            # Error occurred
            print(f"❌ FFmpeg failed with return code {result.returncode}")
            
            # Get detailed error information
            if hasattr(result, 'stderr') and result.stderr:
                error_details = result.stderr.strip()
                print("FFmpeg error output:")
                print(error_details)
            else:
                error_details = f"FFmpeg exited with code {result.returncode}"
                print(f"No stderr available, exit code: {result.returncode}")
            
            # Show shorter error in popup, full details in console
            error_summary = error_details.split('\n')[-1] if error_details else "Unknown FFmpeg error"
            messagebox.showerror("FFmpeg Error", 
                               f"Failed to cut video:\n\n{error_summary}\n\n"
                               f"Check the console for full error details.")
            
            # Clean up cut file if it exists
            if os.path.exists(cut_filepath):
                os.remove(cut_filepath)
                print(f"Cleaned up incomplete file: {cut_filepath}")
                
    except subprocess.TimeoutExpired as e:
        timeout_msg = f"Operation timed out after {e.timeout} seconds"
        print(f"❌ {timeout_msg}")
        messagebox.showerror("Timeout", f"{timeout_msg}. The file may be too large or the encoding is taking too long.")
        if os.path.exists(cut_filepath):
            os.remove(cut_filepath)
            print(f"Cleaned up incomplete file: {cut_filepath}")
    except FileNotFoundError as e:
        error_msg = "FFmpeg is not installed or not found in PATH"
        print(f"❌ {error_msg}")
        print(f"FileNotFoundError details: {e}")
        messagebox.showerror("FFmpeg Not Found", 
                           f"{error_msg}.\n\n"
                           "Please install FFmpeg and ensure it's available in your system PATH.\n\n"
                           "Check the console for more details.")
    except Exception as e:
        print(f"❌ Unexpected error during cutting: {e}")
        print(f"Exception type: {type(e).__name__}")
        messagebox.showerror("Error", f"An unexpected error occurred:\n\n{str(e)}\n\n"
                           "Check the console for full error details.")
        if os.path.exists(cut_filepath):
            os.remove(cut_filepath)
            print(f"Cleaned up incomplete file: {cut_filepath}")

def cut_before_current_time(filename):
    """Cut the video before the current playback time using FFmpeg."""
    _cut_video_at_time(filename, "before")

def cut_after_current_time(filename):
    """Cut the video after the current playback time using FFmpeg."""
    _cut_video_at_time(filename, "after")

# =========================================
#           *AUTO-UPDATE FUNCTIONALITY
# =========================================

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

# Removed complex download/cleanup functions - now just opens GitHub releases page

def check_for_updates_button():
    """Button handler to check for updates."""
    try:
        # Show checking message
        check_window = tk.Toplevel()
        check_window.title("Checking for Updates...")
        check_window.geometry("300x80")
        check_window.configure(bg="black")
        check_window.resizable(False, False)
        
        # Center the window
        check_window.transient(root)
        check_window.grab_set()
        
        check_label = tk.Label(check_window, text="Checking for updates...", 
                             bg="black", fg="white", font=("Arial", 12))
        check_label.pack(pady=20)
        
        check_window.update()
        
        # Check for updates
        update_info = check_for_updates()
        check_window.destroy()
        
        if update_info.get("error"):
            messagebox.showerror("Update Check Failed", update_info["error"])
        elif update_info.get("update_available"):
            # Update is available, ask if user wants to open releases page
            release_data = update_info.get("release_data", {})
            release_body = release_data.get("body", "No release notes available.")
            
            result = messagebox.askyesno("Update Available", 
                                       f"New version available!\n\n"
                                       f"Current version: {update_info['current_version']}\n"
                                       f"Latest version: {update_info['latest_version']}\n\n"
                                       f"Release Notes:\n{release_body[:300]}{'...' if len(release_body) > 300 else ''}\n\n"
                                       "Would you like to open the GitHub releases page to download it?")
            if result:
                open_github_releases()
        else:
            messagebox.showinfo("No Updates", 
                              f"You have the latest version ({update_info['current_version']})")
    
    except Exception as e:
        messagebox.showerror("Error", f"Failed to check for updates: {str(e)}")

def open_github_releases():
    """Open the GitHub releases page in the default browser."""
    try:
        releases_url = f"https://github.com/{GITHUB_REPO}/releases"
        webbrowser.open(releases_url)
    except Exception as e:
        releases_url = f"https://github.com/{GITHUB_REPO}/releases"
        messagebox.showerror("Browser Error", 
                           f"Could not open browser automatically.\n\n"
                           f"Please manually visit:\n{releases_url}")

def check_for_updates_on_startup():
    """Check for updates on startup and prompt user if update is available."""
    try:
        # Check for updates in background
        update_info = check_for_updates()
        
        if update_info.get("error"):
            # Silently fail on startup - don't bother user with network errors
            print(f"Update check failed: {update_info['error']}")
            return
        
        if update_info.get("update_available"):
            # Update is available, ask if user wants to open releases page
            release_data = update_info.get("release_data", {})
            release_body = release_data.get("body", "No release notes available.")
            
            result = messagebox.askyesno("Update Available", 
                                       f"New version available!\n\n"
                                       f"Current version: {update_info['current_version']}\n"
                                       f"Latest version: {update_info['latest_version']}\n\n"
                                       f"Release Notes:\n{release_body[:200]}{'...' if len(release_body) > 200 else ''}\n\n"
                                       "Would you like to open the GitHub releases page to download it?")
            if result:
                open_github_releases()
    
    except Exception as e:
        # Silently fail on startup - don't bother user with errors
        print(f"Startup update check failed: {str(e)}")

# =========================================
#           *STATS DISPLAY
# =========================================

def year_stats(column):
    year_counter = Counter()
    year_to_filenames = {}

    for filename in directory_files:
        data = get_metadata(filename)
        season = data.get("season", "")
        year_str = season[-4:] if season and season[-4:].isdigit() else "Unknown"

        # Group into decades
        if year_str.isdigit():
            year = int(year_str)
            if year >= 2000:
                group = str(year)
            elif year >= 1990:
                group = "1990s"
            elif year >= 1980:
                group = "1980s"
            elif year >= 1970:
                group = "1970s"
            elif year >= 1960:
                group = "1960s"
            else:
                group = f"Pre-60s"
        else:
            group = "Unknown"

        year_counter[group] += 1
        year_to_filenames.setdefault(group, []).append(filename)

    # Output to text widget
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY YEAR\n", ("bold", "underline"))

    # Sort order: recent years first, then 90s, 80s, etc.
    def sort_key(group):
        if group.isdigit():
            return -int(group)
        elif group.endswith("s"):
            return -int(group[:4])
        elif group == "Pre-60s":
            return -1950
        else:
            return 9999

    for group in sorted(year_counter, key=sort_key):
        count = year_counter[group]
        percent = round(count / len(directory_files) * 100, 2)
        column.insert(tk.END, f"{group}: ", "bold")
        # column.insert(tk.END, f"{count} ({percent}%)", "white")
        add_field_total_button(column, year_to_filenames[group], False, False, button_text=f"{count} ({percent}%)")
        column.insert(tk.END, "\n")

    column.config(state=tk.DISABLED)

def season_stats(column):
    season_year_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        season_year = data.get("season", "Unknown")
        if not season_year or season_year == "N/A":
            season_year = "Unknown"
        season_year_counter[season_year] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY SEASON\n", ("bold", "underline"))
    def season_sort_key(season_year_str):
        if season_year_str == "Unknown":
            return (9999, 4)  # Sort "Unknown" at the bottom
        try:
            season, year = season_year_str.split()
            season_order = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
            return (int(year), season_order.get(season, 4))
        except:
            return (9999, 4)
    for season_year in sorted(season_year_counter, key=season_sort_key, reverse=True):
        column.insert(tk.END, f"{season_year}: ", "bold")
        column.insert(
            tk.END,
            f"{season_year_counter[season_year]} ({(round(season_year_counter[season_year]/len(directory_files)*100, ndigits=2))}%)",
            "white",
        )
        add_field_total_button(column, get_all_matching_field("season", season_year), False, False)
        column.insert(tk.END, "\n")
    column.config(state=tk.DISABLED)

def tag_stats(column):
    tag_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        # Tags
        tags = data.get("themes", []) + data.get("genres", []) + data.get("demographics", [])
        for tag in tags:
            tag_counter[tag] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY TAG\n", ("bold", "underline"))
    for tag, count in sorted(tag_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{tag}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_filenames_from_tag(tag), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

def series_stats(column):
    series_counter = get_series_totals()
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY SERIES\n", ("bold", "underline"))
    total_buttons = 0
    for series, count in sorted(series_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{series}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        if total_buttons < 300:
            total_buttons += 1
            add_field_total_button(column, get_all_matching_field("series", [series]), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

series_totals = None
def get_series_totals(refetch=True, check_all=True):
    global series_totals
    if check_all:
        check_list = directory_files
    else:
        check_list = playlist["playlist"]
    if refetch or not series_totals:
        series_counter = Counter()
        for filename in check_list:
            data = get_metadata(filename)
            # Series
            series = data.get("series") or data.get("title", "Unknown")
            if isinstance(series, list):
                for s in series:
                    series_counter[s] += 1
            else:
                series_counter[series] += 1
        series_totals = series_counter
    return series_totals
        
def artist_stats(column):
    artist_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        slug = (get_file_metadata_by_name(filename) or {}).get("slug")
        # Artists (only if the slug matches)
        for song in data.get("songs", []):
            if song.get("slug") == slug:
                for artist in song.get("artist", []):
                    artist_counter[artist] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY ARTIST\n", ("bold", "underline"))
    total_buttons = 0
    for artist, count in sorted(artist_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{artist}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        if total_buttons < 300:
            total_buttons += 1
            add_field_total_button(column, get_filenames_from_artist(artist), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

def studio_stats(column):
    studio_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        # Studios
        for studio in data.get("studios", []):
            studio_counter[studio] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY STUDIO\n", ("bold", "underline"))
    for studio, count in sorted(studio_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{studio}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_filenames_from_studio(studio), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

def type_stats(column):
    type_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        type_counter[data.get("type", "Unknown")] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY TYPE\n", ("bold", "underline"))
    for type, count in sorted(type_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{type}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_all_matching_field("type", type), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

def slug_stats(column):
    slug_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        slug_counter[data.get("slug", "Unknown")] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY SLUG\n", ("bold", "underline"))
    for slug, count in sorted(slug_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{slug}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_all_matching_field("slug", slug), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

STAT_TYPES = [
    {"name":"THEMES BY YEAR", "func":year_stats},
    {"name":"THEMES BY SEASON", "func":season_stats},
    {"name":"THEMES BY ARTIST", "func":artist_stats},
    {"name":"THEMES BY SERIES", "func":series_stats},
    {"name":"THEMES BY STUDIO", "func":studio_stats},
    {"name":"THEMES BY TAG", "func":tag_stats},
    {"name":"THEMES BY TYPE", "func":type_stats},
    {"name":"THEMES BY SLUG", "func":slug_stats}
]

def display_theme_stats_in_columns():
    """Displays year stats, artist stats, series stats, and studio stats in the respective UI columns."""
    left_column.config(state=tk.NORMAL)
    left_column.delete("1.0", tk.END)
    left_column.insert(tk.END, "THEME DIRECTORY/STATS\n", ("bold", "underline"))
    for s in STAT_TYPES:
        # left_column.insert(tk.END, f"{s.get("name")}", "bold")
        btn = tk.Button(left_column, text=f"{s.get("name")}▶", font=("Arial", scl(12)), borderwidth=0, pady=0, command=lambda func=s.get("func"): func(middle_column), bg="black", fg="white")
        left_column.window_create(tk.END, window=btn)
        left_column.insert(tk.END, f"\n")
    left_column.config(state=tk.DISABLED)

# =========================================
#           *FILTERING PLAYLISTS
# =========================================

def load_filters(update = False):
    filters = get_all_filters()
    show_list("load_filters", right_column, filters, get_filter_name, load_filter, -1, update, delete_filter)

def get_filter_name(key, value):
    return value.get("name")

def load_filter(index):
    """Applys a saved filter from JSON."""
    filter_data = get_all_filters()[index]
    name = filter_data.get('name')
    confirm = messagebox.askyesno("Filter Playlist", f"Are you sure you want to apply the filter '{name}'?")
    if not confirm:
        return  # User canceled
    filters = filter_data.get("filter")
    if playlist.get("infinite"):
        playlist["filter"] = filters
        print("Applied Filters:", filters)
        refresh_pop_time_groups()
        save_config()
    else:
        filter_playlist(filters)

def delete_filters(update = False):
    filters = get_all_filters()
    show_list("delete_filters", right_column, filters, get_filter_name, delete_filter, -1, update)

def delete_filter(index):
    """Deletes a playlist by index after confirmation."""
    filters = get_all_filters()  # Get dictionary of playlists

    if index not in filters:
        print("Invalid filter index.")
        return

    name = filters[index].get('name')
    filename = os.path.join(FILTERS_FOLDER, f"{name}.json")

    # Confirmation box
    confirm = messagebox.askyesno("Delete Playlist", f"Are you sure you want to delete '{name}'?")
    if not confirm:
        return  # User canceled

    # Delete the file
    try:
        os.remove(filename)
        print(f"Deleted filter: {name}")
    except Exception as e:
        print(f"Error deleting filtert: {e}")
        return

    # Refresh the list display
    reload_playlist(True)

def filters():
    show_filter_popup()

filter_popup = None
def show_filter_popup():
    """Opens a properly formatted, scrollable popup for filtering the playlist."""
    global filter_popup
    if playlist.get("infinite", False):
        playlis = copy.deepcopy(directory_files)
    else:
        playlis = playlist["playlist"]

    def update_score_range(event=None):
        min_score = min_score_slider.get()
        max_score = max_score_slider.get()
        if min_score > max_score:
            if event == min_score:
                max_score_slider.set(min_score)
            else:
                min_score_slider.set(max_score)

    def filter_entry_range(title, root_frame, start, end):
        frame = tk.Frame(root_frame, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        tk.Label(frame, text=title + " RANGE:", bg=BACKGROUND_COLOR, fg="white").pack(side="left")
        min_entry = tk.Entry(frame, bg="black", fg="white", justify="center", width=8)
        min_entry.pack(side="left")
        tk.Label(frame, text=" TO ", bg=BACKGROUND_COLOR, fg="white").pack(side="left")
        max_entry = tk.Entry(frame, bg="black", fg="white", justify="center", width=8)
        max_entry.pack(side="left")
        return {"min": min_entry, "max": max_entry}

    def filter_entry_listbox(title, root_frame, data):
        frame = tk.Frame(root_frame, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)
        label_and_list = tk.Frame(frame, bg=BACKGROUND_COLOR)
        label_and_list.pack(fill="x")
        tk.Label(label_and_list, text=title, bg=BACKGROUND_COLOR, fg="white").pack(side="left")
        listbox = tk.Listbox(label_and_list, selectmode=tk.MULTIPLE, height=6, width=28, exportselection=False, bg="black", fg="white")
        listbox.pack(side="left", fill="x", expand=True)
        scrollbar = tk.Scrollbar(label_and_list, command=listbox.yview, bg="black")
        scrollbar.pack(side="right", fill="y")
        listbox.config(yscrollcommand=scrollbar.set)
        for item in data:
            listbox.insert(tk.END, item)
        return listbox

    try:
        filter_popup.destroy()
    except:
        pass
    popup = tk.Toplevel(bg="black")
    popup.title("Filter Playlist")
    popup_width = 550
    popup_height = 600
    filter_popup = popup
    # If popout_controls exists, use its position
    if popout_controls and popout_controls.winfo_exists():
        popup.update_idletasks()  # Ensure window info is up-to-date
        x = popout_controls.winfo_x()
        y = popout_controls.winfo_y()
        popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")
    else:
        popup.geometry(f"{popup_width}x{popup_height}")

    main_frame = tk.Frame(popup, bg=BACKGROUND_COLOR)
    main_frame.pack(fill="both", expand=True)

    canvas = tk.Canvas(main_frame, bg=BACKGROUND_COLOR)
    scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=BACKGROUND_COLOR)
    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    columns_frame = tk.Frame(scrollable_frame, bg=BACKGROUND_COLOR)
    columns_frame.pack(fill="both", expand=True)

    left_column = tk.Frame(columns_frame, bg=BACKGROUND_COLOR)
    left_column.pack(side="left", fill="both", expand=True, padx=10)

    right_column = tk.Frame(columns_frame, bg=BACKGROUND_COLOR)
    right_column.pack(side="right", fill="both", expand=True, padx=10)

    playlist_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    playlist_frame.pack(fill="x", pady=(5,0))

    tk.Label(playlist_frame, text="PLAYLIST:", bg=BACKGROUND_COLOR, fg="white").pack(side="left", padx=(0, 5))

    available_playlists = ["(None)"] + list(get_playlists_dict().values())
    playlist_var = tk.StringVar(value="(None)")
    playlist_combobox = ttk.Combobox(playlist_frame, textvariable=playlist_var, values=available_playlists, width=20, style="Black.TCombobox", state="readonly")
    playlist_combobox.pack(side="left", fill="x", expand=True)

    tk.Label(left_column, text="KEYWORDS (separated by commas):", bg=BACKGROUND_COLOR, fg="white").pack(anchor="w", pady=(5, 0))
    keywords_entry = tk.Text(left_column, height=1, width=31, bg="black", fg="white", wrap="word")
    keywords_entry.pack(pady=(0, 5))

    theme_type_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    theme_type_frame.pack(fill="x", pady=5)

    tk.Label(theme_type_frame, text="THEME TYPE:", bg=BACKGROUND_COLOR, fg="white").pack(side="left", padx=(0, 7))

    theme_var = tk.StringVar(value="Both")
    theme_type_combobox = ttk.Combobox(
        theme_type_frame,
        textvariable=theme_var,
        values=["Both", "Opening", "Ending"],
        width=20,
        style="Black.TCombobox",
        state="readonly"
    )
    theme_type_combobox.pack(side="left", fill="x", expand=True)

    score_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    score_frame.pack(fill="x", pady=5)
    tk.Label(score_frame, text="SCORE\nRANGE", bg=BACKGROUND_COLOR, fg="white").pack(side="left")
    lowest_score = get_lowest_parameter("score", playlis)
    highest_score = get_highest_parameter("score", playlis)
    min_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, orient="horizontal", bg="black", fg="white", command=update_score_range)
    min_score_slider.pack(fill="x")
    max_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, orient="horizontal", bg="black", fg="white", command=update_score_range)
    max_score_slider.pack(fill="x")

    rank_entry = filter_entry_range("RANK               ", left_column, get_highest_parameter("rank", playlis), get_lowest_parameter("rank", playlis))
    members_entry = filter_entry_range("MEMBERS       ", left_column, get_lowest_parameter("members", playlis), get_highest_parameter("members", playlis))
    popularity_entry = filter_entry_range("POPULARITY  ", left_column, get_highest_parameter("popularity", playlis), get_lowest_parameter("popularity", playlis))

    season_frame = tk.Frame(left_column, bg=BACKGROUND_COLOR)
    season_frame.pack(fill="x", pady=(5,10))

    tk.Label(season_frame, text="AIRED:   ", bg=BACKGROUND_COLOR, fg="white").pack(side="left")

    all_seasons = get_all_seasons(playlis)

    season_start_var = tk.StringVar()
    season_end_var = tk.StringVar()

    season_start_dropdown = ttk.Combobox(season_frame, textvariable=season_start_var, values=all_seasons, height=10, width=12, style="Black.TCombobox", state="readonly")
    season_start_dropdown.pack(side="left")

    def unhighlight_season_start_dropdown(event):
        season_start_dropdown.selection_clear()
        season_start_dropdown.icursor(tk.END)
    season_start_dropdown.bind("<<ComboboxSelected>>", unhighlight_season_start_dropdown)

    tk.Label(season_frame, text="TO", bg=BACKGROUND_COLOR, fg="white").pack(side="left")

    season_end_dropdown = ttk.Combobox(season_frame, textvariable=season_end_var, values=list(reversed(all_seasons)), height=10, width=12, style="Black.TCombobox", state="readonly")
    season_end_dropdown.pack(side="left")

    def unhighlight_season_end_dropdown(event):
        season_end_dropdown.selection_clear()
        season_end_dropdown.icursor(tk.END)
    season_end_dropdown.bind("<<ComboboxSelected>>", unhighlight_season_end_dropdown)
    
    theme_exclude_options = [
        "DUPLICATES",
        "LATER VERSIONS",
        "OVERLAP",
        "NSFW (Without Censors)",
        "NSFW (With Censors)",
        "SPOILER",
        "TRANSITION"
    ]
    themes_include_listbox = filter_entry_listbox("THEMES\nINCLUDE\n(OR)", left_column, theme_exclude_options)
    themes_exclude_listbox = filter_entry_listbox("THEMES\nEXCLUDE\n(OR)", left_column, theme_exclude_options)
    artists_listbox = filter_entry_listbox("ARTISTS\nINCLUDE\n(OR)", right_column, get_all_artists(playlis))
    studio_listbox = filter_entry_listbox("STUDIOS\nINCLUDE\n(OR)", right_column, get_all_studios(playlis))
    all_tags = get_all_tags(playlis)
    tags_listbox = filter_entry_listbox("TAGS\nINCLUDE\n(OR)", right_column, all_tags)
    tags_and_listbox = filter_entry_listbox("TAGS\nINCLUDE\n(AND)", right_column, all_tags)
    excluded_tags_listbox = filter_entry_listbox("TAGS\nEXCLUDE\n(OR)", right_column, all_tags)

    def set_default_values(force_defaults=False):
        filter_data = {} if force_defaults else playlist.get("filter", {})

        # Playlist
        playlist_name = filter_data.get("playlist_filter")
        if playlist_name in available_playlists:
            playlist_var.set(playlist_name)
        else:
            playlist_var.set("(None)")

        # Keywords
        keywords_entry.delete("1.0", tk.END)
        keywords_entry.insert("1.0", filter_data.get("keywords", ""))

        # Theme Type
        theme_var.set(filter_data.get("theme_type", "Both"))

        # Score
        min_score_slider.set(filter_data.get("score_min", lowest_score))
        max_score_slider.set(filter_data.get("score_max", highest_score))

        # Rank Range
        rank_entry["min"].delete(0, tk.END)
        rank_entry["min"].insert(0, filter_data.get("rank_min", get_highest_parameter("rank", playlis)))
        rank_entry["max"].delete(0, tk.END)
        rank_entry["max"].insert(0, filter_data.get("rank_max", get_lowest_parameter("rank", playlis)))

        # Season Range
        season_start_var.set(filter_data.get("season_min", all_seasons[0] if all_seasons else ""))
        season_end_var.set(filter_data.get("season_max", all_seasons[-1] if all_seasons else ""))

        # Members
        members_entry["min"].delete(0, tk.END)
        members_entry["min"].insert(0, filter_data.get("members_min", get_lowest_parameter("members", playlis)))
        members_entry["max"].delete(0, tk.END)
        members_entry["max"].insert(0, filter_data.get("members_max", get_highest_parameter("members", playlis)))

        # Popularity
        popularity_entry["min"].delete(0, tk.END)
        popularity_entry["min"].insert(0, filter_data.get("popularity_min", get_highest_parameter("popularity", playlis)))
        popularity_entry["max"].delete(0, tk.END)
        popularity_entry["max"].insert(0, filter_data.get("popularity_max", get_lowest_parameter("popularity", playlis)))

        # Listbox selections
        for listbox, key in [
            (artists_listbox, "artists"),
            (studio_listbox, "studios"),
            (tags_listbox, "tags_include"),
            (tags_and_listbox, "tags_include_and"),
            (excluded_tags_listbox, "tags_exclude"),
            (themes_exclude_listbox, "themes_exclude"),
            (themes_include_listbox, "themes_include")
        ]:
            listbox.selection_clear(0, tk.END)
            if not force_defaults and key in filter_data:
                values = filter_data[key]
                for i in range(listbox.size()):
                    if listbox.get(i) in values:
                        listbox.selection_set(i)

    set_default_values()

    def extract_filter():
        def assign_filter_range_value(filter, type, entry, start, end):
            if start > end:
                if int(entry['min'].get()) < start: filter[type + '_min'] = int(entry['min'].get())
                if int(entry['max'].get()) > end: filter[type + '_max'] = int(entry['max'].get())
            else:
                if int(entry['min'].get()) > start: filter[type + '_min'] = int(entry['min'].get())
                if int(entry['max'].get()) < end: filter[type + '_max'] = int(entry['max'].get())
            return filter

        filters = {}

        if playlist_var.get() != "(None)": filters["playlist_filter"] = playlist_var.get()
        if keywords_entry.get("1.0", "end-1c").strip() != "": filters['keywords'] = str(keywords_entry.get("1.0", "end-1c").strip())
        if theme_var.get() != "Both": filters['theme_type'] = str(theme_var.get())
        if float(min_score_slider.get()) != round(lowest_score, 1): filters['score_min'] = float(min_score_slider.get())
        if float(max_score_slider.get()) != round(highest_score, 1): filters['score_max'] = float(max_score_slider.get())
        filters = assign_filter_range_value(filters, 'rank', rank_entry, get_highest_parameter("rank", playlis), get_lowest_parameter("rank", playlis))
        filters = assign_filter_range_value(filters, 'members', members_entry, get_lowest_parameter("members", playlis), get_highest_parameter("members", playlis))
        filters = assign_filter_range_value(filters, 'popularity', popularity_entry, get_highest_parameter("popularity", playlis), get_lowest_parameter("popularity", playlis))
        if season_start_var.get() != all_seasons[0]: filters["season_min"] = season_start_var.get()
        if season_end_var.get() != all_seasons[-1]: filters["season_max"] = season_end_var.get()
        if themes_exclude_listbox.curselection(): filters["themes_exclude"] = [themes_exclude_listbox.get(i) for i in themes_exclude_listbox.curselection()]
        if themes_include_listbox.curselection(): filters["themes_include"] = [themes_include_listbox.get(i) for i in themes_include_listbox.curselection()]
        if artists_listbox.curselection(): filters["artists"] = [artists_listbox.get(i) for i in artists_listbox.curselection()]
        if studio_listbox.curselection(): filters["studios"] = [studio_listbox.get(i) for i in studio_listbox.curselection()]
        if tags_listbox.curselection(): filters["tags_include"] = [tags_listbox.get(i) for i in tags_listbox.curselection()]
        if tags_and_listbox.curselection(): filters["tags_include_and"] = [tags_and_listbox.get(i) for i in tags_and_listbox.curselection()]
        if excluded_tags_listbox.curselection(): filters["tags_exclude"] = [excluded_tags_listbox.get(i) for i in excluded_tags_listbox.curselection()]
        return filters

    def apply_filter():
        filters = extract_filter()
        if playlist.get("infinite"):
            playlist["filter"] = filters
            print("Applied Filters:", filters)
            refresh_pop_time_groups()
            save_config()
        else:
            filter_playlist(filters)
        popup.destroy()

    def reset_filter():
        set_default_values(True)

    def save_filter():
        filters = extract_filter()
        if not os.path.exists(FILTERS_FOLDER):
            os.makedirs(FILTERS_FOLDER)
        filter_name = simpledialog.askstring("Save Filter", "Enter a name for this filter:")
        if not filter_name:
            return
        filter_path = os.path.join(FILTERS_FOLDER, f"{filter_name}.json")
        try:
            with open(filter_path, "w") as file:
                json.dump({"name": filter_name, "filter": filters}, file, indent=4)
            messagebox.showinfo("Success", f"Filter '{filter_name}' saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save filter: {e}")

    button_frame = tk.Frame(popup, bg="black")
    button_frame.pack(fill="x", pady=10)
    tk.Button(button_frame, text="APPLY FILTER TO PLAYLIST", bg="black", fg="white", command=apply_filter).pack(side="left", padx=10)
    tk.Button(button_frame, text="RESET TO DEFAULTS", bg="black", fg="white", command=reset_filter).pack(side="left", padx=10)
    tk.Button(button_frame, text="SAVE FILTER", bg="black", fg="white", command=save_filter).pack(side="right", padx=10)

def get_all_seasons(playlis):
    seasons = set()
    for file in playlis:
        data = get_metadata(file)
        if data:
            season = data.get("season")
            if season:
                seasons.add(season)

    def season_key(season_str):
        try:
            part, year = season_str.split()
            season_order = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
            return (int(year), season_order.get(part, 99))
        except Exception:
            return (9999, 99)

    return sorted(seasons, key=season_key)

def get_all_filters():
    """Returns all saved filters as a dictionary."""
    filters_dict = {}
    
    if not os.path.exists(FILTERS_FOLDER):
        os.makedirs(FILTERS_FOLDER)  # Ensure the filters folder exists

    for index, filename in enumerate(os.listdir(FILTERS_FOLDER)):
        if filename.endswith(".json"):
            filter_path = os.path.join(FILTERS_FOLDER, filename)
            try:
                with open(filter_path, "r") as file:
                    filters_dict[index] = json.load(file)  # Remove .json from key
            except Exception as e:
                print(f"Failed to load {filename}: {e}")
    
    return filters_dict

def get_lowest_parameter(parameter, playlis=None):
    lowest = 10000000
    if not playlis:
        if playlist.get("infinite", False):
            playlis = copy.deepcopy(directory_files)
        else:
            playlis = playlist["playlist"]
    for filename in playlis:
        data = get_metadata(filename)
        if data:
            item = data.get(parameter, lowest)
            if item and item < lowest:
                lowest = item
    return lowest

def get_highest_parameter(parameter, playlis=None):
    highest = 0
    if not playlis:
        if playlist.get("infinite", False):
            playlis = copy.deepcopy(directory_files)
        else:
            playlis = playlist["playlist"]
    for filename in playlis:
        data = get_metadata(filename)
        if data:
            item = data.get(parameter, highest)
            if item and item > highest:
                highest = item
    return highest

def get_all_artists(playlis):
    artists = []
    for filename in playlis:
        data = get_metadata(filename)
        if data:
            for song in data.get('songs', []):
                for artist in song.get("artist", []):
                    if artist not in artists:
                        artists.append(artist)
    return sorted(artists, key=str.lower)

def get_all_tags(playlis=None, game=True, double=False):
    tags = []
    def add_tag(anime):
        if game or not is_game(anime):
            for tag in anime.get('genres', []) + anime.get('themes', []) + anime.get('demographics', []):
                if double or tag not in tags:
                    tags.append(tag)
    if playlis:
        for f in playlis:
            data = get_metadata(f)
            if data:
                add_tag(data)
    else:
        for anime in anime_metadata.values():
            add_tag(anime)
    return sorted(tags)

def get_all_studios(playlis, games=True, repeats=False):
    studios = []
    for filename in playlis:
        data = get_metadata(filename)
        if data and (games or not is_game(data)):
            for studio in data.get('studios', []):
                if studio not in studios or repeats:
                    studios.append(studio)
    return sorted(studios)

def filter_playlist(filters):
    """Filters the playlist based on given criteria."""
    global playlist
    if playlist.get("infinite", False):
        playlis = copy.deepcopy(directory_files)
    else:
        playlis = playlist["playlist"]

    filtered = []

    playlist_filter_files = []
    if "playlist_filter" in filters:
        ref_playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{filters['playlist_filter']}.json")
        if os.path.exists(ref_playlist_path):
            with open(ref_playlist_path, "r") as f:
                ref_data = json.load(f)
                playlist_filter_files = set(ref_data.get("playlist", []))
                
    if ("themes_exclude" in filters and "DUPLICATES" in filters["themes_exclude"]) or ("themes_include" in filters and "DUPLICATES" in filters["themes_include"]):
        build_best_duplicate_map(playlis)
    if ("themes_exclude" in filters and "LATER VERSIONS" in filters["themes_exclude"]) or ("themes_include" in filters and "LATER VERSIONS" in filters["themes_include"]):
        build_version_index(playlis)

    for filename in playlis:
        data = get_metadata(filename)
        # Extract metadata
        if not data:
            continue
        title = data.get("title", "").lower()
        eng_title = (data.get("eng_title", "") or "").lower()
        theme_type = format_slug(data.get("slug"))
        score = float(data.get("score") or 0)
        rank = data.get("rank") or 100000
        members = int(data.get("members") or 0)
        popularity = data.get("popularity") or INT_INF
        season = data.get("season", "")  # Example: "Fall 2020"
        def season_to_tuple(season_str):
            try:
                part, year = season_str.split()
                season_order = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
                return (int(year), season_order.get(part, -1))
            except Exception:
                return (0, -1)  # Very early season so it passes min filters but fails max
        season_tuple = season_to_tuple(season)
        theme = get_song_by_slug(data, data.get("slug", ""))
        artists = theme.get("artist", [])
        studios = data.get("studios", [])
        tags = set(data.get("genres", []) + data.get("themes", []) + data.get("demographics", []))  # Ensure tags are a set for fast lookup

        # Apply filters
        if "playlist_filter" in filters and filename not in playlist_filter_files:
            continue
        if "keywords" in filters and not any(any(keyword.lower() in field.lower() for field in [filename, title, eng_title]) for keyword in filters["keywords"].split(",")):
            continue
        if "theme_type" in filters and filters["theme_type"] not in theme_type:
            continue
        if "score_min" in filters and score < filters["score_min"]:
            continue
        if "score_max" in filters and score > filters["score_max"]:
            continue
        if "rank_min" in filters and rank > filters["rank_min"]:
            continue
        if "rank_max" in filters and rank < filters["rank_max"]:
            continue
        if "members_max" in filters and members > filters["members_max"]:
            continue
        if "members_min" in filters and members < filters["members_min"]:
            continue
        if "popularity_min" in filters and popularity > filters["popularity_min"]:
            continue
        if "popularity_max" in filters and popularity < filters["popularity_max"]:
            continue
        if "season_min" in filters and season_tuple < season_to_tuple(filters["season_min"]):
            continue
        if "themes_exclude" in filters or "themes_include" in filters:
            theme_flags = set()
            if theme:
                # Get the specific version for this file
                file_version = extract_version(filename)
                current_version_data = None
                
                # Find the matching version in the versions array
                if theme.get("versions"):
                    for version_data in theme.get("versions", []):
                        if version_data.get("version") == file_version:
                            current_version_data = version_data
                            break
                
                # Check flags for the specific version of this file
                if current_version_data:
                    # Use version-specific flags
                    if current_version_data.get("overlap") == "Over":
                        theme_flags.add("OVERLAP")
                    if current_version_data.get("overlap") == "Transition":
                        theme_flags.add("TRANSITION")
                    if current_version_data.get("spoiler"):
                        theme_flags.add("SPOILER")
                    if ("NSFW (With Censors)" in (filters.get("themes_exclude", []) + filters.get("themes_include", [])) or "NSFW (Without Censors)" in (filters.get("themes_exclude", []) + filters.get("themes_include", []))) and current_version_data.get("nsfw"):
                        censors = get_file_censors(filename)
                        if censors:
                            theme_flags.add("NSFW (With Censors)")
                        else:
                            theme_flags.add("NSFW (Without Censors)")
                else:
                    # Fall back to theme-level flags if version not found (backward compatibility)
                    if theme.get("overlap") == "Over":
                        theme_flags.add("OVERLAP")
                    if theme.get("overlap") == "Transition":
                        theme_flags.add("TRANSITION")
                    if theme.get("spoiler"):
                        theme_flags.add("SPOILER")
                    if ("NSFW (With Censors)" in (filters.get("themes_exclude", []) + filters.get("themes_include", [])) or "NSFW (Without Censors)" in (filters.get("themes_exclude", []) + filters.get("themes_include", []))) and theme.get("nsfw"):
                        censors = get_file_censors(filename)
                        if censors:
                            theme_flags.add("NSFW (With Censors)")
                        else:
                            theme_flags.add("NSFW (Without Censors)")
            if "themes_exclude" in filters and any(flag in filters["themes_exclude"] for flag in theme_flags):
                continue 
            if "themes_include" in filters and not any(flag in filters["themes_include"] for flag in theme_flags):
                continue 
            if ("themes_exclude" in filters and "DUPLICATES" in filters["themes_exclude"] and not check_best_duplicate_theme(filename, data)) or ("themes_include" in filters and "DUPLICATES" in filters["themes_include"] and check_best_duplicate_theme(filename, data)):
                continue
            if ("themes_exclude" in filters and "LATER VERSIONS" in filters["themes_exclude"] and not check_lowest_version(filename, data)) or ("themes_include" in filters and "LATER VERSIONS" in filters["themes_include"] and check_lowest_version(filename, data)):
                continue
        if "season_max" in filters and season_tuple > season_to_tuple(filters["season_max"]):
            continue
        if "artists" in filters and not any(artist in artists for artist in filters["artists"]):
            continue
        if "studios" in filters and not any(studio in studios for studio in filters["studios"]):
            continue
        if "tags_include" in filters and not any(tag in tags for tag in filters["tags_include"]):
            continue
        if "tags_include_and" in filters and not all(tag in tags for tag in filters["tags_include_and"]):
            continue
        if "tags_exclude" in filters and any(tag in tags for tag in filters["tags_exclude"]):
            continue

        # If all checks pass, add to filtered list
        filtered.append(filename)
    if not playlist.get("infinite"):
        playlist["playlist"] = filtered
        print("Applied Filters:", filters)  # Debugging
        show_playlist(True)
        update_current_index(0)
        messagebox.showinfo("Playlist Filtered", f"Playlist filtered to {len(playlist["playlist"])} videos.")
    return filtered

def get_song_by_slug(data, slug):
    """Returns the list of artists for the song matching the given slug."""
    for theme in data.get("songs", []):  # Iterate through themes
        if theme["slug"] == slug:  # Find the matching slug
            return theme
    return {}  # Return empty list if no match

_best_duplicate_map = {}
def build_best_duplicate_map(playlis):
    global _best_duplicate_map
    _best_duplicate_map = {}

    for file in playlis:
        file_path = directory_files.get(file)
        if not file_path:
            continue
        data = get_metadata(file)
        if not data:
            continue

        key = (data.get("mal"), data.get("slug"), extract_version(file))
        try:
            file_size = os.path.getsize(file_path)
        except:
            continue

        if key not in _best_duplicate_map or file_size > _best_duplicate_map[key][1]:
            _best_duplicate_map[key] = (file, file_size)

def check_best_duplicate_theme(filename, data):
    key = (data.get("mal"), data.get("slug"), extract_version(filename))
    best_file, _ = _best_duplicate_map.get(key, (filename, None))
    return filename == best_file

def extract_version(filename):
    """
    Extracts the version number from a filename like:
    'BlackBullet-OP1v2-NCBD1080.webm' -> returns 2
    If no version is found, defaults to 1.
    Now uses metadata lookup with filename parsing as fallback.
    """
    # Try to get version from metadata first
    version_str = get_version_from_filename(filename)
    if version_str:
        try:
            return int(version_str)
        except (ValueError, TypeError):
            pass
    
    # Fallback to regex parsing from filename
    match = re.search(r'v(\d+)', filename)
    if match:
        return int(match.group(1))
    return 1

_lowest_version_map = {}
def build_version_index(playlis):
    global _lowest_version_map
    _lowest_version_map = {}

    for file in playlis:
        data = get_metadata(file)
        if not data:
            continue
        mal = data.get("mal")
        slug = data.get("slug")
        ver = extract_version(file)
        key = (mal, slug)

        if not mal or not slug:
            continue

        if key not in _lowest_version_map or ver < _lowest_version_map[key][0]:
            _lowest_version_map[key] = (ver, file)

def check_lowest_version(filename, data):
    global _lowest_version_map
    key = (data.get("mal"), data.get("slug"))
    ver = extract_version(filename)

    if key not in _lowest_version_map:
        return True  # Unknown, assume it's the only one

    lowest_ver, best_file = _lowest_version_map[key]
    return ver <= lowest_ver

# =========================================
#            *SORTING PLAYLISTS
# =========================================

SORTING_TYPES = [
    {"sort":"filename", "order":"asc"},
    {"sort":"filename", "order":"desc"},
    {"sort":"title", "order":"asc"},
    {"sort":"title", "order":"desc"},
    {"sort":"eng_title", "order":"asc"},
    {"sort":"eng_title", "order":"desc"},
    {"sort":"score", "order":"asc"},
    {"sort":"score", "order":"desc"},
    {"sort":"members", "order":"asc"},
    {"sort":"members", "order":"desc"},
    {"sort":"season", "order":"asc"},
    {"sort":"season", "order":"desc"}
]

def sort(update = False):
    show_list("sort", right_column, {f"{s['sort']} ({s['order']})": s for s in SORTING_TYPES}, get_sort_name, sort_playlist, list_index, update)

def get_sort_name(key, value):
    return value.get('sort').replace("_", " ").title() + " " + value.get('order').upper()

def sort_playlist(index):
    """Sorts the playlist in-place based on metadata retrieved via get_metadata(filename).

    Args:
        playlist (list of str): The playlist containing file paths.
        key (str): The metadata key to sort by (title, eng_title, season, members, score, filename).
        order (str): "asc" for ascending, "desc" for descending (default: "asc").
    """
    global playlist
    key = SORTING_TYPES[index].get("sort")
    order = SORTING_TYPES[index].get("order")
    valid_keys = {"title", "eng_title", "season", "members", "score", "filename"}
    if key not in valid_keys:
        print(f"Invalid sorting key: {key}")
        return

    reverse = order.lower() == "desc"

    # Define season sorting order
    season_order = {"Winter": 1, "Spring": 2, "Summer": 3, "Fall": 4}

    def extract_season_data(filename):
        """Extracts numeric values for sorting from the 'season' field."""
        metadata = get_metadata(filename)
        season_str = metadata.get("season", "")

        if season_str:
            parts = season_str.split()  # Example: ["Fall", "2022"]
            if len(parts) == 2 and parts[0] in season_order:
                season_num = season_order[parts[0]]
                year = int(parts[1])
                return (year, season_num)
        
        return (float("inf"), float("inf"))  # Place missing seasons at the bottom

    # Sort playlist in-place
    playlist["playlist"].sort(key=lambda filename: (
        extract_season_data(get_clean_filename(filename)) if key == "season" else
        float(get_metadata(get_clean_filename(filename)).get(key, 0) or 0) if key in {"members", "score"} else
        get_metadata(get_clean_filename(filename)).get(key, "").lower() if isinstance(get_metadata(get_clean_filename(filename)).get(key), str) else "",
        filename.lower()  # Secondary sort by filename for consistency
    ), reverse=reverse)
    update_current_index(0)
    show_playlist()
    save_config()

# =========================================
#            *SEARCHING THEMES
# =========================================

search_term = ""
search_queue = None
search_results = []
def search(update = False, ask = True, add = False):
    global search_results, search_term
    selected = 0
    if ask and disable_shortcuts:
        search_term_ask = simpledialog.askstring("Search Themes", "Search Term:", initialvalue=search_term, parent=root)
        if not search_term_ask:
            return
        search_term = search_term_ask
        update = True
    if search_term == "":
        search_results = []
    else:
        search_results = search_playlist(search_term)
    search_results.sort(key=lambda file: get_title(file, file).lower())
    if search_queue and search_queue in search_results:
        selected = search_results.index(search_queue)+1
    search_list = {file: file for file in (["SEARCHING: " + search_term] + search_results)}
    if add:
        show_list("search_add", right_column, search_list, get_title, add_search_playlist, selected, update)
    else:
        show_list("search", right_column, search_list, get_title, set_search_queue, selected, update)

def search_add(update = False, ask = True):
    search(update, ask, True)

def add_search_playlist(index):
    global playlist
    if index > 0:
        filename = search_results[index-1]
        playlist["playlist"].insert(playlist["current_index"]+1, filename)
        search_add(True, False)
        up_next_text()
        save_config()

def set_search_queue(index):
    global search_queue
    if index > 0:
        filename = search_results[index-1]
        if search_queue == filename:
            search_queue = None
        else:
            search_queue = filename
            if not player.is_playing():
                play_video()
                return
        search(True, False)

def search_playlist(search_term):
    """Returns a list of filenames where the search term matches the title or english_title.

    Args:
        search_term (str): The term to search for.

    Returns:
        list: Filenames that match the search term.
    """
    search_term = search_term.lower()  # Make search case-insensitive
    results = []
    artist_results = []
    for filename in directory_files:
        metadata = get_metadata(filename)
        filename_trim = filename.lower().replace(".webm", "").replace(".mp4", "")
        title = metadata.get("title", "").lower()
        english_title = metadata.get("eng_title")
        if english_title:
            english_title = english_title.lower()
        if (search_term in filename_trim) or (title and search_term in title) or (english_title and search_term in english_title):
            results.append(filename)
        else:
            song_string = get_song_string(metadata, artist_limit=None).lower()
            if song_string and search_term in song_string:
                artist_results.append(filename)
    return results + artist_results

def get_playlist_name(key, value):
    data = get_playlist(value)
    if data.get("infinite"):
        return f"{value}[∞]"
    else:
        return f"{value}[{len(data.get("playlist"))}]"

def get_playlists_dict(exclude_system=False, system_only=False):
    """Returns a dictionary of available playlists indexed numerically.
    
    Args:
        exclude_system: If True, excludes system playlists
        system_only: If True, only includes system playlists
    """
    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)

    playlists = sorted(f for f in os.listdir(PLAYLISTS_FOLDER) if f.endswith(".json"))
    playlist_names = [os.path.splitext(playlis)[0] for playlis in playlists]
    
    if exclude_system:
        playlist_names = [name for name in playlist_names if name not in SYSTEM_PLAYLISTS]
    elif system_only:
        playlist_names = [name for name in playlist_names if name in SYSTEM_PLAYLISTS]
    
    return {i: name for i, name in enumerate(playlist_names)}

# =========================================
#        *LIGHTNING ROUND SETTINGS
# =========================================

light_round_started = False
light_round_start_time = None
light_round_number = 0
light_round_length_default = 12
light_round_length = 12
light_round_answer_length = 8
light_mode = None
light_modes = {
    "regular":{
        "icon":"🗲",
        "desc":(
            "Opening/Ending starts at a random point."
        )
    },
    "clip":{
        "icon":"🎬",
        "desc":(
            "You will be shown a random clip or trailer."
        )
    },
    "peek":{
        "icon":"👀",
        "desc":(
            "Opening/Ending starts at a random point muted.\n"
            "Only a small part of the screen is shown, and grows or moves over time."
        )
    },
    "frame":{
        "icon":"📷",
        "desc":(
            "You will be shown 4 different frames from the Opening/Ending.\n"
            "Each frame will be shown one at a time."
        )
    },
    "cover":{
        "icon":"📚",
        "desc":(
            "You will be shown the cover of the anime, revealed over time."
        )
    },
    "character":{
        "icon":"👤",
        "desc":(
            "You will be shown 4 characters revealed over time."
        )
    },
    "blind":{
        "icon":"👁",
        "desc":(
            "Opening/Ending starts at a random point.\n"
            "You will only be able to hear the music."
        )
    },
    "title":{
        "icon":"𝕋",
        "desc":(
            "You will need to guess the title as letters are randomly placed in position."
        )
    },
    "synopsis":{
        "icon":"📰",
        "desc":(
            "You will be shown a part of the synopsis.\n"
            "It will be revealed word by word over time."
        )
    },
    "trivia":{
        "icon":"❓",
        "desc":(
            "You will be asked a trivia question about an anime.\n"
            "It will be revealed word by word over time."
        )
    },
    "emoji":{
        "icon":"😄",
        "desc":(
            "You are shown 6 emojis over time."
        )
    },
    "song":{
        "icon":"🎵",
        "desc":(
            "You will be shown song information for the Opening/Ending.\n"
            "It will be revealed over time, and the song plays the last few seconds."
        )
    },
    "ost":{
        "icon":"💿",
        "desc":(
            "You hear part of the anime's OST."
        )
    },
    "clues":{
        "icon":"🔍",
        "desc":(
            "You will be shown various stats."
        )
    },
    "tags":{
        "icon":"🔖",
        "desc":(
            "You will be show detailed tags revealed over time."
        )
    },
    "episodes":{
        "icon":"📺",
        "desc":(
            "You will be shown 6 episode titles.\n"
            "They will be revealed over time."
        )
    },
    "names":{
        "icon":"🎭",
        "desc":(
            "You will be shown 6 character names.\n"
            "They will be revealed over time."
        )
    },
    "c. reveal":{
        "icon":"✨",
        "desc":(
            "You will be shown a character, revealed over time."
        )
    },
    "c. profile":{
        "icon":"📝",
        "desc":(
            "You will be shown the gender and description of a character over time.\n"
            "Image will be revealed in last few seconds."
        )
    },
    "c. name":{
        "icon":"🔤",
        "desc":(
            "You will need to guess the character name as letters are randomly placed in position."
        )
    },
    "variety":{
        "icon":"🎲",
        "desc":(
            "Plays a dynamic mix of lightning rounds based on popularity."
        )
    }
}

lightning_mode_settings_default = {
    "blind": {
        "length": 12,
        "muted": False,
        "variants": {
            "standard": True,
            "double_speed": True,
            "mismatch": True,
            "one_second": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1500],
                "weight":  {
                    "op":10,
                    "ed":3
                }
            },
            "cooldown": {
                "min_gap": 2,
                "max_gap": 7,
                "popularity_force_threshold": {
                    "op":750,
                    "ed":500
                },
                "no_repeat_limit": 0
            }
        }
    },
    "c. name": {
        "length": 20,
        "muted": True,
        "character_types": {
            "main": True,
            "secondary": False,
            "appears": False,
            "popularity_limit": True
        },
        "variety": {
            "enabled": False,
            "popularity": {
                "range": [0, 750],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 250,
                "no_repeat_limit": 40
            }
        }
    },
    "c. profile": {
        "length": 20,
        "muted": True,
        "character_types": {
            "main": True,
            "secondary": True,
            "appears": False,
            "popularity_limit": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 250],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 30,
                "popularity_force_threshold": 750,
                "no_repeat_limit": 40
            }
        }
    },
    "c. reveal": {
        "length": 20,
        "muted": True,
        "variants": {
            "blur": True,
            "parts": True,
            "pixel": True,
            "slice": True,
            "slide": True,
            "swap": True,
            "tile": True,
            "zoom": True
        },
        "character_types": {
            "main": True,
            "secondary": True,
            "appears": False,
            "popularity_limit": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 750],
                "weight": 30
            },
            "cooldown": {
                "min_gap": 5,
                "max_gap": 10,
                "popularity_force_threshold": 750,
                "no_repeat_limit": 40
            }
        }
    },
    "character": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 2,
                "max_gap": 7,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 80
            }
        }
    },
    "clues": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 20,
                "popularity_force_threshold": 250,
                "no_repeat_limit": 40
            }
        }
    },
    "clip": {
        "length": 12,
        "muted": True,
        "variants": {
            "random_clip": True,
            "trailer": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 3,
                "max_gap": 8,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 80
            }
        }
    },
    "cover": {
        "length": 20,
        "muted": True,
        "variants": {
            "blur": True,
            "pixel": True,
            "slice": True,
            "slide": True,
            "swap": True,
            "tile": True,
            "zoom": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 5,
                "max_gap": 15,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 80
            }
        }
    },
    "emoji": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 30,
                "popularity_force_threshold": 100,
                "no_repeat_limit": 40
            }
        }
    },
    "episodes": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1000],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 500,
                "no_repeat_limit": 40
            }
        }
    },
    "frame": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 3000],
                "weight": {
                    "op":10,
                    "ed":5
                }
            },
            "cooldown": {
                "min_gap": 4,
                "max_gap": 20,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 0
            }
        }
    },
    "names": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1000],
                "weight": 5
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 500,
                "no_repeat_limit": 40
            }
        }
    },
    "ost": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 250],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 25,
                "popularity_force_threshold": 100,
                "no_repeat_limit": 40
            }
        }
    },
    "peek": {
        "length": 12,
        "muted": True,
        "variants": {
            "slice": True,
            "edge": True,
            "grow": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 3000],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 3,
                "max_gap": 10,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 0
            }
        }
    },
    "regular": {
        "length": 12,
        "muted": False,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [250, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 0,
                "max_gap": 0,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 0
            }
        }
    },
    "song": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 250],
                "weight": {
                    "op":10,
                    "ed":3
                }
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 25,
                "popularity_force_threshold": {
                    "op":100,
                    "ed":50
                },
                "no_repeat_limit": 40
            }
        }
    },
    "synopsis": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [50, 1500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 4,
                "max_gap": 10,
                "popularity_force_threshold": 1000,
                "no_repeat_limit": 80
            }
        }
    },
    "tags": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 750],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 500,
                "no_repeat_limit": 40
            }
        }
    },
    "title": {
        "length": 20,
        "muted": True,
        "variants": {
            "reveal": True,
            "scramble": True,
            "swap": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 4,
                "max_gap": 6,
                "popularity_force_threshold": 1000,
                "no_repeat_limit": 80
            }
        }
    },
    "trivia": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1000],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 7,
                "max_gap": 15,
                "popularity_force_threshold": 1000,
                "no_repeat_limit": 40
            }
        }
    },
    "variety": {
        "popularity_limit": True,
        "series_mode_limit": True,
        "mode_weight": True,
        "mode_cooldowns": True
    }
}
lightning_mode_settings = {}
selected_light_mode_settings = ""
saved_lightning_mode_settings = {}
selected_settings = ""

def open_settings_editor():
    global lightning_mode_settings, lightning_mode_settings_default, selected_light_mode_settings, saved_lightning_mode_settings, selected_settings

    def parse_literal(value):
        try:
            return ast.literal_eval(value)
        except Exception:
            return value

    def insert_into_tree(tree, parent, d):
        if isinstance(d, dict):
            for key, val in d.items():
                # Special display for 'range' lists of length 2
                if key == "range" and isinstance(val, (list, tuple)) and len(val) == 2:
                    node_id = tree.insert(parent, 'end', text=str(key), open=False)
                    tree.insert(node_id, 'end', text=f"min: {val[0]}", open=False)
                    tree.insert(node_id, 'end', text=f"max: {val[1]}", open=False)
                elif isinstance(val, (bool, int, float, str)) or val is None:
                    node_id = tree.insert(parent, 'end', text=f"{key}: {val}", open=False)
                else:
                    node_id = tree.insert(parent, 'end', text=str(key), open=False)
                    insert_into_tree(tree, node_id, val)
        elif isinstance(d, (list, tuple)):
            for i, val in enumerate(d):
                node_id = tree.insert(parent, 'end', text=f"[{i}]", open=False)
                insert_into_tree(tree, node_id, val)
        else:
            tree.insert(parent, 'end', text=str(d), open=False)

    def tree_to_dict(tree, parent=''):
        children = tree.get_children(parent)
        if not children:
            text = tree.item(parent, 'text')
            # If leaf is 'key: value', split and return {key: value (parsed)}
            if ": " in text:
                key, val = text.rsplit(": ", 1)
                return {key: parse_literal(val)}
            return parse_literal(text)

        # Special handling for 'range' nodes: two children 'min: x', 'max: y'
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
        insert_into_tree(tree, '', data)

    def on_double_click(event):
        item_id = tree.selection()[0]

        # Don't allow editing if the item has children
        if tree.get_children(item_id):
            return

        old_value = tree.item(item_id, 'text')

        # Check for 'key: True' or 'key: False' pattern (toggle boolean)
        if ": True" in old_value or ": False" in old_value:
            key, val = old_value.rsplit(": ", 1)
            if val == "True":
                new_val = "False"
            else:
                new_val = "True"
            tree.item(item_id, text=f"{key}: {new_val}")
            return

        # Check for 'key: value' pattern for any leaf node
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
        global selected_light_mode_settings
        nonlocal current_settings
        current_settings = tree_to_dict(tree)
        lightning_mode_settings.clear()
        lightning_mode_settings.update(copy.deepcopy(current_settings))
        apply_button.configure(text="APPLIED!")
        selected_light_mode_settings = selected_settings
        root.after(300, lambda: apply_button.configure(text="Apply"))
        save_config()

    def save_as():
        global selected_settings
        name = simpledialog.askstring("Save Settings As", "Enter a name for these settings:", initialvalue=saved_var.get())
        if name:
            saved_lightning_mode_settings[name] = copy.deepcopy(tree_to_dict(tree))
            refresh_saved_dropdown()
            saved_var.set(name)
            selected_settings = name
            save_config()

    def load_selected():
        global selected_settings
        name = saved_var.get()
        if name in saved_lightning_mode_settings:
            selected_settings = name
            saved_lightning_mode_settings[name] = update_lightning_mode_settings(saved_lightning_mode_settings[name])
            rebuild_tree(saved_lightning_mode_settings[name])

    def delete_selected():
        global selected_settings
        name = saved_var.get()
        if name in saved_lightning_mode_settings:
            del saved_lightning_mode_settings[name]
            saved_var.set("")
            selected_settings = ""
            refresh_saved_dropdown()
            save_config()

    def load_defaults():
        global selected_settings
        selected_settings = ""
        saved_var.set("")
        rebuild_tree(default_copy)

    def refresh_saved_dropdown():
        global selected_settings
        menu = saved_menu["menu"]
        menu.delete(0, "end")
        for name in saved_lightning_mode_settings:
            menu.add_command(label=name, command=lambda val=name: saved_var.set(val))
        saved_var.set(selected_settings)

    # Pop-out window
    window = tk.Toplevel()
    window.title("Lightning Mode Settings Editor")
    window.geometry("400x450")
    window.configure(bg="#1e1e1e")

    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure("Treeview", background="#1e1e1e", foreground="white", fieldbackground="#1e1e1e")
    style.configure("Treeview.Heading", background="#2a2a2a", foreground="white")
    style.map("Treeview", background=[("selected", "#333")])

    tree = ttk.Treeview(window)
    tree.pack(expand=True, fill='both', padx=10, pady=10)
    tree.bind('<Double-1>', on_double_click)

    # Load data
    default_copy = copy.deepcopy(lightning_mode_settings_default)
    current_settings = copy.deepcopy(lightning_mode_settings)
    selected_settings = selected_light_mode_settings
    insert_into_tree(tree, '', current_settings)

    # Control panel
    controls = tk.Frame(window, bg="#1e1e1e")
    controls.pack(fill='x', padx=10)

    apply_button = tk.Button(controls, text="Apply", command=apply_changes, bg="#444", fg="white")
    apply_button.pack(side="left", padx=5)
    tk.Button(controls, text="Save As", command=save_as, bg="#444", fg="white").pack(side="left", padx=5)
    tk.Button(controls, text="Load Defaults", command=load_defaults, bg="#444", fg="white").pack(side="left", padx=5)

    saved_var = tk.StringVar()
    saved_menu = tk.OptionMenu(controls, saved_var, "")
    saved_menu.configure(bg="#444", fg="white", highlightthickness=0, activebackground="#666")
    saved_menu["menu"].config(bg="#2a2a2a", fg="white")
    saved_menu.pack(side="left", padx=5)

    tk.Button(controls, text="Load", command=load_selected, bg="#444", fg="white").pack(side="left", padx=(0, 3))
    tk.Button(controls, text="X", command=delete_selected, bg="#aa3333", fg="white").pack(side="left")

    refresh_saved_dropdown()

def update_lightning_mode_settings(settings):
    settings = sync_with_default(settings, lightning_mode_settings_default)
    return dict(sorted(settings.items()))

def sync_with_default(saved, default):
    # First, remove any keys not in the default
    keys_to_remove = [key for key in saved if key not in default]
    for key in keys_to_remove:
        del saved[key]

    # Then, add missing keys and recurse into nested dicts
    for key, default_value in default.items():
        if key not in saved:
            saved[key] = default_value
        elif isinstance(default_value, dict) and isinstance(saved[key], dict):
            sync_with_default(saved[key], default_value)
        else:
            # Optional: If types mismatch, replace with default
            if not isinstance(saved[key], type(default_value)):
                saved[key] = default_value
    return saved

def toggle_light_mode(type=None, queue=True):
    global light_mode, variety_light_mode_enabled, light_dropdown, start_light_mode_button
    if type == None or light_mode == type or (variety_light_mode_enabled and type == 'variety'):
        unselect_light_modes()
        toggle_coming_up_popup(False, "Lightning Round")
    else:
        unselect_light_modes()
        mode = light_modes[type]
        light_mode = type
        if type == 'variety':
            variety_light_mode_enabled = True
            button_seleted(globals()['variety_light_mode_button'], True)
        else:
            light_dropdown.set(f"{mode.get("icon")} {type.upper()}")
            configure_style()
            light_dropdown.update_idletasks()
            light_dropdown.configure(state="readonly", style='Black.TCombobox')
            unhighlight_selection(None, setting=True)
            light_dropdown.update_idletasks()
        if queue:
            queue_next_lightning_mode()
        button_seleted(globals()['start_light_mode_button'], True)
        start_light_mode_button.configure(text="⏹️")
        if popout_buttons_by_name.get(start_light_mode_button):
            popout_buttons_by_name[start_light_mode_button].configure(text="⏹️STOP")
        if light_round_number == 0:
            image_path = "banners/" + type + "_lightning_round.webp"
            image_tk = None
            if os.path.exists(image_path):
                image = Image.open(image_path)
                image = image.resize((400, 225), Image.LANCZOS)  # Resize if needed
                image_tk = ImageTk.PhotoImage(image)  # Convert to Tkinter format
            mode_length = lightning_mode_settings.get(light_mode, {}).get("length", light_round_length_default)
            if "c. " in light_mode:
                mode_type = 'character'
            else:
                mode_type = 'anime'
            if type == "variety":
                min_length = 0
                max_length = light_round_length_default
                for l in lightning_mode_settings:
                    if min_length > lightning_mode_settings[l].get("length", light_round_length_default):
                        min_length = lightning_mode_settings[l].get("length", light_round_length_default)
                    if max_length < lightning_mode_settings[l].get("length", light_round_length_default):
                        max_length = lightning_mode_settings[l].get("length", light_round_length_default)
                mode_length = f"{min_length} - {max_length}"
            mode_desc = f"{mode.get("desc")}\nYou have {mode_length} seconds to guess.\n\n1 PT for the first to guess the {mode_type}!"

            toggle_coming_up_popup(True, f"{light_mode.replace("c.", "Character")} Lightning Round", mode_desc, image_tk, queue=True)

def unselect_light_modes():
    global light_mode, variety_light_mode_enabled, start_light_mode_button
    light_mode = None
    variety_light_mode_enabled = False
    button_seleted(globals()['variety_light_mode_button'], False)
    button_seleted(globals()['start_light_mode_button'], False)
    start_light_mode_button.configure(text="▶")
    if popout_buttons_by_name.get(start_light_mode_button):
        popout_buttons_by_name[start_light_mode_button].configure(text="▶START")


# =========================================
#          *LIGHTNING ROUND START
# =========================================

def get_light_round_time():
    length = player.get_length()/1000
    buffer = 10
    need_censors = light_mode in ['regular', 'peek']
    need_mute_censors = light_mode in ['regular', 'blind', 'song']
    if not need_censors:
        buffer = 1
    if length < (light_round_length+light_round_answer_length+(buffer*2)+1):
        return 1  # If the video is too short, start from 1
    start_time = None
    try_count = 0
    while start_time is None:
        start_time = random.randrange(buffer, int(length - (light_round_length+light_round_answer_length+buffer)))
        try_count = try_count + 1
        if try_count < 20 and (need_censors or need_mute_censors):
            file_censors = censor_list.get(currently_playing.get('filename'))
            if file_censors != None:
                end_time = start_time+light_round_length
                for censor in file_censors:
                    if (((censor.get("mute") or censor.get("skip")) and need_mute_censors) or (not (censor.get("mute") or censor.get("skip")) and need_censors)) and (not (censor['end'] < start_time or censor['start'] > end_time)):
                        start_time = None
                        break
    return start_time

light_speed_modifier = 1
light_blind_one_second_count = None
stream_start_time = 0
def update_light_round(time):
    global light_round_started, light_round_start_time, censors_enabled, light_round_length, light_speed_modifier, light_name_overlay
    global stream_start_time, character_round_answer, character_round_characters, light_blind_one_second_count
    if not light_round_start_time and (light_mode == 'frame' or frame_light_round_started):
        if time < 1:
            player.pause()
            if not frame_light_round_started:
                setup_frame_light_round()
        return
    if time > 1 and light_round_start_time != None and light_round_started:
        if time >= light_round_start_time+light_round_length+light_round_answer_length:
            light_round_transition()
            light_round_started = False
        elif(time >= light_round_start_time+light_round_length):
            start_str = "next"
            blind_length = lightning_mode_settings.get("blind", {}).get("length", light_round_length_default)
            if light_blind_one_second_count != None and light_blind_one_second_count < blind_length:
                if light_blind_one_second_count % 3 == 0:
                    light_blind_one_second_count += 1
                    player.pause()
                    set_progress_overlay(light_round_length*100, light_round_length*100)
                    def update_light_blind_count():
                        global light_blind_one_second_count
                        if light_blind_one_second_count % 3 == 2:
                            player.set_time(int(float(light_round_start_time)) * 1000)
                            player.play()
                        light_blind_one_second_count += 1
                        set_countdown(round(blind_length - light_blind_one_second_count))
                    root.after(1000, update_light_blind_count)
                    root.after(2000, update_light_blind_count)
                    set_countdown(round(blind_length - light_blind_one_second_count))
            else:
                if not is_title_window_up():
                    player.set_fullscreen(False)
                    player.set_fullscreen(True)
                    char_answer = copy.copy(character_round_answer)
                    cover_answer = light_cover_image
                    trivia_answer = light_trivia_answer
                    if mismatch_visuals:
                        top_info_data = "MISMATCHED VISUALS:\n" + mismatch_visuals
                    elif last_streamed[0] == currently_playing.get("filename") and last_streamed[1] != "Trailer":
                        top_info_data = f"YOUTUBE VIDEO:\n{last_streamed[1]}\nby {last_streamed[3]}"
                    else:
                        top_info_data = None
                    toggle_title_popup(True)
                    set_black_screen(False)
                    set_light_round_number("#" + str(light_round_number))
                    clean_up_light_round()
                    if top_info_data:
                        top_info(top_info_data, 20)
                    if char_answer:
                        top_info(char_answer[0], width_max=0.55) 
                        toggle_character_image_overlay(char_answer[1])
                    if cover_answer:
                        toggle_character_image_overlay(cover_answer)
                    if trivia_answer:
                        top_info(trivia_answer, width_max=0.55) 
                if not light_mode:
                    start_str = "end"
                set_countdown(start_str + " in..." + str(round(light_round_answer_length-(time - (light_round_start_time+light_round_length)))))
        else:
            time_left = (light_round_length-(time - light_round_start_time))
            if time_left < 1 and light_speed_modifier != 1:
                light_speed_modifier = 1
                player.set_rate(light_speed_modifier)
            if song_overlay_boxes:
                toggle_song_overlay(show_title=True, show_artist=time_left<=9, show_theme=time_left<=6, show_music=time_left<=4)
                player.audio_set_mute(time_left > 4)
                play_background_music(time_left > 4)
            elif clues_overlay:
                data = currently_playing.get("data")
                if time_left <= 15:
                    tags = "\n".join(get_tags(data))
                    val_size = 60 - max(0, (tags.count('\n') - 5) * 5)
                    clues_overlay_labels["Tags"].config(text=tags, font=("Arial", scl(val_size)))
                else:
                    clues_overlay_labels["Tags"].config(text=f"in...{round(time_left-15)}")
                if time_left <= 10:
                    clues_overlay_labels["Episodes"].config(text=str(data.get("episodes") or "Airing"))
                    clues_overlay_labels["Score"].config(text=f"{data.get('score')}\n#{data.get('rank')}")
                    clues_overlay_labels["Members"].config(text=f"{data.get('members') or 0:,}\n#{data.get('popularity') or 'N/A'}")
                else:
                    clues_overlay_labels["Episodes"].config(text=f"in...{round(time_left-10)}")
                    clues_overlay_labels["Score"].config(text=f"in...{round(time_left-10)}")
                    clues_overlay_labels["Members"].config(text=f"in...{round(time_left-10)}")
                if time_left <= 5:
                    theme = data.get("slug")
                    song = get_song_string(data)
                    song_string = f"{theme}: {song}"
                    clues_overlay_labels["Song"].config(text=song_string)
                else:
                    clues_overlay_labels["Song"].config(text=f"SONG in...{round(time_left-5)}")
            elif synopsis_start_index is not None:
                def get_synopsis_progress(time_left, total_duration, words):
                    """
                    Returns the number of words to show based on time left and total duration.
                    `words` should be a list of the synopsis words.
                    """
                    elapsed = total_duration - time_left
                    progress = elapsed / total_duration
                    word_count = round(len(words) * progress)
                    return " ".join(words[:word_count])
                answer_time = 8
                if light_trivia_answer:
                    answer_time = 6
                synopsis_words = get_light_synopsis_string().split()
                shown_text = get_synopsis_progress(max(0, time_left-answer_time), light_round_length-answer_time, synopsis_words)
                toggle_synopsis_overlay(text=shown_text)
            elif emoji_overlay_window:
                # Reveal emojis one by one over the round
                emojis = get_emoji_clues_for_title(currently_playing.get("data"))
                elapsed = light_round_length - max(0, time_left)
                progress = max(0, min(1, elapsed / light_round_length))
                emoji_count = max(1, round(len(emojis) * progress)+1)
                toggle_emoji_overlay(emojis=emojis, max_emojis=emoji_count)
            elif light_progress_bar:
                set_progress_overlay(round((time - light_round_start_time)*100), light_round_length*100)
                if stream_player.is_playing():
                    half_time = (light_round_length / 2)
                    if time_left >= half_time:
                        set_frame_number(f"TRACK NAME in...{round(time_left-half_time)}")
                    else:
                        track_name = extract_track_name_from_youtube_title(last_streamed[1], currently_playing.get("data", {}))
                        set_frame_number(track_name)
            elif title_overlay:
                starting_letters = min(5, max(1, len(title_light_letters) // 5))
                interval = len(title_light_letters) * 0.09
                final_count = round((5*interval)+starting_letters)
                word_num = min(final_count, int(((light_round_length-time_left)/3)*interval)+starting_letters)
                set_frame_number(f"{word_num}/{final_count} REVEALS", inverse=character_round_answer)
                toggle_title_overlay(get_title_light_string(word_num))
            elif scramble_overlay_root:
                total_letters = max(1, round(len(scramble_overlay_letters) * 0.45))  # Just in case
                placement_cutoff = light_round_length * (2 / 3)

                if time_left >= light_round_length - placement_cutoff:
                    # We're still in the placement phase
                    elapsed = light_round_length - time_left
                    progress = elapsed / placement_cutoff  # 0 to 1
                    word_num = int(total_letters * progress)
                else:
                    # Final 1/3 — all letters placed, time to guess
                    word_num = total_letters
                set_frame_number(f"{word_num}/{total_letters} PLACEMENTS", inverse=character_round_answer)
                toggle_scramble_overlay(num_letters=word_num)
            elif swap_overlay_root:
                # Total swaps you want to show, based on number of pairs
                if len(swap_pairs) <= 2:
                    total_swaps = 0
                else:
                    total_swaps = round(len(swap_pairs) * 0.4)

                # Define the cutoff point — after this, no more swaps
                swap_cutoff = light_round_length * (2 / 3)

                if time_left >= light_round_length - swap_cutoff:
                    # Still in swap phase
                    elapsed = light_round_length - time_left
                    progress = elapsed / swap_cutoff  # 0 to 1
                    word_num = int(total_swaps * progress)
                else:
                    # In the final 1/3 — guessing phase
                    word_num = total_swaps
                set_frame_number(f"{word_num}/{total_swaps} SWAPS", inverse=character_round_answer)
                toggle_swap_overlay(num_swaps=word_num)
            elif peek_overlay1:
                gap = get_peek_gap(currently_playing.get("data"))
                toggle_peek_overlay(direction=peek_light_direction, progress=((light_round_length-time_left)/light_round_length)*100, gap=gap)
                now_playing_background_music(music_files[current_music_index])
            elif edge_overlay_box:
                edge_max = max(15, min(70, (currently_playing.get("data").get('popularity') or 3000)/12))
                progress = (light_round_length - time_left) / light_round_length
                block_percent = 100 - (edge_max * progress)  # from 100% to 80%
                toggle_edge_overlay(block_percent=block_percent)
            elif grow_overlay_boxes:
                grow_max = max(20, min(60, (currently_playing.get("data").get('popularity') or 3000)/10))
                progress = (light_round_length - time_left) / light_round_length
                block_percent = 100 - (grow_max * progress)  # from 100% to 80%
                toggle_grow_overlay(block_percent=block_percent, position=grow_position)
                now_playing_background_music(music_files[current_music_index])
            elif character_overlay_boxes:
                reveal_num = min(4, (int(light_round_length - (time_left)) // (light_round_length // 4)) + 1)
                toggle_character_overlay(num_characters=reveal_num)
                set_frame_number(f"{reveal_num}/{4}", inverse=character_round_answer)
            elif character_pixel_overlay:
                total_steps = len(character_pixel_images)
                step_num = min(total_steps-1, (int(light_round_length - (time_left)) // (light_round_length // total_steps)))
                toggle_character_pixel_overlay(step=step_num)
                set_frame_number(f"{step_num+1}/{total_steps}", inverse=character_round_answer)
            elif blur_reveal_image_window:
                progress = (light_round_length - max(0, time_left)) / light_round_length
                progress = min(max(progress, 0.0), 1.0)
                blur_percent = 100 - (100 * progress)
                toggle_character_blur_reveal_overlay(percent=blur_percent / 100, destroy=False)
                set_frame_number(f"BLUR: {round(blur_percent)}%", inverse=character_round_answer)
            elif zoom_reveal_image_window:
                progress = ((light_round_length - 1) - max(0, time_left-1)) / (light_round_length-1)
                progress = min(max(progress, 0.0), 1.0)
                zoom_percent = 100 - (100 * progress)
                toggle_character_zoom_reveal_overlay(percent=zoom_percent / 100, destroy=False)
                set_frame_number(f"ZOOM OUT: {round(100 - zoom_percent)}%", inverse=character_round_answer)
            elif slice_overlay_window:
                progress = (light_round_length - max(0, time_left-1)) / light_round_length
                progress = min(max(progress, 0.0), 1.0) 
                total_parts = len(slice_overlay_parts) // 2
                slices_to_show = max(1, min(total_parts, round(total_parts * progress)))
                toggle_slice_overlay(num_revealed=slices_to_show)
                set_frame_number(f"{slices_to_show}/{total_parts}", inverse=character_round_answer)
            elif tile_overlay_window:
                if not tile_overlay_swap:
                    progress = (light_round_length - max(0, time_left-1)) / light_round_length
                    progress = min(max(progress, 0.0), 1.0) 
                    total_parts = len(tile_overlay_parts) // 2
                    tiles_to_show = max(1, min(total_parts, round(total_parts * progress)))
                    toggle_tile_overlay(num_revealed=tiles_to_show)
                    set_frame_number(f"{tiles_to_show}/{total_parts}", inverse=character_round_answer)
                else:
                    # Swap tiles one by one over the round
                    total_swaps = len(tile_overlay_parts) // 4
                    elapsed = light_round_length - max(0, time_left)
                    progress = max(0, min(1, elapsed / light_round_length))
                    swaps_to_show = max(1, round(total_swaps * progress))
                    toggle_tile_overlay(num_revealed=swaps_to_show, swap=True)
                    set_frame_number(f"{swaps_to_show}/{total_swaps} SWAPS", inverse=character_round_answer)
            elif reveal_image_window:
                progress = (light_round_length - max(0, time_left-1)) / light_round_length
                progress = min(max(progress, 0.0), 1.0)
                block_percent = 100 - (100 * progress)
                toggle_character_reveal_overlay(percent=block_percent / 100, destroy=False)
            elif profile_overlay_window:
                bio_text = character_round_answer[3]
                total_words = 70 #len(bio_text.split())

                progress = (light_round_length - time_left) / light_round_length

                # Reveal bio over the first 10 seconds
                max_bio_time = 12
                if time_left > light_round_length - max_bio_time:
                    partial = 1 - ((time_left - (light_round_length - max_bio_time)) / max_bio_time)
                    words_to_show = int(partial * total_words)
                else:
                    words_to_show = total_words

                # Show image in last 5 seconds
                image_countdown = max(0, int(time_left - 3))

                # Call the toggle
                toggle_character_profile_overlay(word_count=words_to_show, image_countdown=image_countdown)
                if image_countdown > 0:
                    set_frame_number(f"IMAGE IN {image_countdown}...", inverse=True)
                else:
                    set_frame_number()
            elif tag_cloud_tags:
                starting_tags = 1
                final_count = len(tag_cloud_tags)
                time_left_t = time_left - 5
                light_round_length_t = light_round_length - 5

                # Use the actual light round length
                progress = (light_round_length_t - time_left_t) / (light_round_length_t)
                progress = max(0, min(progress, 1))  # Clamp between 0 and 1

                # Calculate how many tags to show
                tags_num = min(final_count, int(progress * final_count) + starting_tags)

                # Update overlay and label
                set_frame_number(f"{tags_num}/{final_count}")
                toggle_tag_cloud_overlay(tags_num)
            elif light_episode_names:
                reveal_num = min(6, (int(light_round_length - time_left) // (light_round_length // 6)) + 1)
                toggle_episode_overlay(reveal_num)
                set_frame_number(f"{reveal_num}/{6}")
            if edge_overlay_box:
                set_countdown(round(time_left/light_speed_modifier), position="center")
            elif light_blind_one_second_count is not None:
                blind_length = lightning_mode_settings.get("blind", {}).get("length", light_round_length_default)
                set_countdown(round(blind_length - light_blind_one_second_count))
            else:
                set_countdown(round(time_left/light_speed_modifier), inverse=character_round_answer)
    if light_mode and time < 1:
        toggle_coming_up_popup(False, "Lightning Round")
        if not light_round_started:
            light_round_started = True
            if light_mode in ['regular', 'peek']:
                root.after(500, set_black_screen, False)
            def set_double_speed():
                global light_round_length, light_speed_modifier
                light_speed_modifier = 2
                player.set_rate(light_speed_modifier)
                light_round_length = light_round_length * light_speed_modifier
                set_frame_number(f"x{light_speed_modifier} SPEED")
            def set_one_second():
                global light_round_length, light_blind_one_second_count
                light_blind_one_second_count = 0
                light_round_length = 1
                set_frame_number(f"ONE SECOND")
            if light_round_start_time is None:
                light_round_start_time = get_light_round_time()
            if lightning_mode_settings.get(light_mode, {}).get("muted"):
                toggle_mute(True)
            if light_mode == 'blind':
                blind_variants = lightning_mode_settings.get("blind",{}).get("variants",{})
                standard, double_speed, mismatch, one_second = blind_variants.get("standard"), blind_variants.get("double_speed"), blind_variants.get("mismatch"), blind_variants.get("one_second")
                blind_modes = ['standard', 'standard', 'standard', 'mismatch']
                allowed_blind_modes = []
                for m in blind_modes:
                    if blind_variants.get(m):
                        allowed_blind_modes.append(m)
                allowed_blind_modes = allowed_blind_modes or blind_modes
                blind_mode = random.choice(allowed_blind_modes)
                if blind_mode == "mismatch":
                    media = instance.media_new(directory_files.get(get_mismatched_theme()))
                    mismatched_player.set_media(media)
                    mismatched_player.play()
                    mismatched_player.set_fullscreen(False)
                    mismatched_player.set_fullscreen(True)
                    spawn_pulsating_music_note(root.winfo_screenwidth() // 2, root.winfo_screenheight() // 2)
                    def wait_for_mismatch(filename):
                        if filename != currently_playing.get("filename"):
                            return
                        elif mismatched_player.is_playing() and mismatched_player.get_length() > 0:
                            def mismatch_overlay():
                                top_info("MISMATCHED VISUALS")
                                set_frame_number("GUESS BY MUSIC ONLY")
                                set_light_round_number("#" + str(light_round_number))
                                pulsating_note_window.attributes("-topmost", True)
                            def set_mismatch_start():
                                mismatched_player.set_time(int(float(light_round_start_time))*1000)
                                mismatched_player.set_fullscreen(False)
                                mismatched_player.set_fullscreen(True)
                            set_mismatch_start()
                            for time in [500, 1000, 1500, 2000]:
                                root.after(time, mismatch_overlay)
                        else:
                            root.after(100, wait_for_mismatch, filename)
                    wait_for_mismatch(currently_playing.get("filename"))
                else:
                    is_op = is_slug_op(currently_playing.get('data', {}).get('slug', ""))
                    def pick_double_or_one_second(is_op):
                        if double_speed and one_second:
                            if not is_op or random.randint(1, 2) == 1:
                                set_double_speed()
                            else:
                                set_one_second()
                        elif double_speed:
                            set_double_speed()
                        elif one_second:
                            set_one_second()
                    if double_speed or one_second:
                        if not standard:
                            pick_double_or_one_second(is_op)
                        else:
                            popularity = currently_playing.get("data", {}).get("popularity", 1000) or 3000
                            if (popularity <= 100 and random.randint(1, 3) == 1) or (popularity <= 250 and random.randint(1, 6) == 1):
                                pick_double_or_one_second(is_op)
                    set_progress_overlay(0, light_round_length*100)
            elif light_mode == 'clues':
                toggle_clues_overlay()
            elif light_mode == 'song':
                toggle_song_overlay(show_title=True, show_artist=False, show_theme=False, show_music=False)
            elif light_mode == 'synopsis':
                pick_synopsis()
                toggle_synopsis_overlay(text=get_light_synopsis_string(words = 1))
            elif light_mode == 'trivia':
                trivia_data = lightning_queue_data.get(currently_playing.get("filename", {}), {}).get("trivia", [])
                set_light_trivia(trivia_data=trivia_data)
                toggle_synopsis_overlay(text=get_light_synopsis_string(words = 1))
            elif light_mode == "emoji":
                toggle_emoji_overlay(max_emojis=1)
            elif light_mode == 'title':
                start_title_round()
                top_info("MUST SAY FULL TITLE")
            elif light_mode == 'peek':
                send_scoreboard_command("hide")
                peek_mode = get_next_peek_mode()
                if peek_mode == 'edge':
                    toggle_edge_overlay()
                elif peek_mode == 'grow':
                    set_grow_position()
                    toggle_grow_overlay(position=grow_position)
                elif peek_mode == 'slice':
                    choose_peek_direction()
                    toggle_peek_overlay()
            elif light_mode == 'character':
                character_round_characters = lightning_queue_data.get(currently_playing.get("filename", {}), {}).get("characters", [])
                if not character_round_characters:
                    get_character_round_characters()
                toggle_character_overlay(num_characters=1)
                top_info("CHARACTERS")
            elif light_mode == 'cover':
                top_info("COVER ART")
                get_light_cover_image()
                cover_reveal_mode = get_next_cover_reveal_mode()
                if cover_reveal_mode == 'pixel':
                    generate_pixelation_steps(pil_image=ImageTk.getimage(light_cover_image).convert("RGBA"))
                    toggle_character_pixel_overlay()
                elif cover_reveal_mode == 'slide':
                    toggle_character_reveal_overlay(direction=random.choice(['top','bottom','left','right']))
                elif cover_reveal_mode == 'blur':
                    toggle_character_blur_reveal_overlay(percent=1.0)
                elif cover_reveal_mode == 'zoom':
                    toggle_character_zoom_reveal_overlay(percent=1.0)
                elif cover_reveal_mode == 'slice':
                    toggle_slice_overlay(num_revealed=1, vertical=random.choice([True, False]))
                elif cover_reveal_mode == 'tile':
                    toggle_tile_overlay(num_revealed=1, grid_size=5)
                elif cover_reveal_mode == 'swap':
                    toggle_tile_overlay(grid_size=10, swap=True)
            elif 'c.' in light_mode:
                top_info("GUESS THE CHARACTER", inverse=True)
                character_round_answer = lightning_queue_data.get(currently_playing.get("filename", {}), {}).get("character_answer")
                if not character_round_answer:
                    min_desc = 0
                    if light_mode == 'c. profile':
                        min_desc = 120
                    get_character_round_image(types=get_char_types_by_popularity(mode=light_mode), min_desc_length=min_desc)
                if light_mode == 'c. reveal':
                    c_reveal_mode = get_next_c_reveal_mode()
                    if c_reveal_mode == 'parts':
                        get_char_parts_round_character()
                        toggle_character_overlay(num_characters=1)
                    elif c_reveal_mode == 'pixel':
                        generate_pixelation_steps()
                        toggle_character_pixel_overlay()
                    elif c_reveal_mode == 'slide':
                        toggle_character_reveal_overlay()
                    elif c_reveal_mode == 'blur':
                        toggle_character_blur_reveal_overlay(percent=1.0)
                    elif c_reveal_mode == 'zoom':
                        toggle_character_zoom_reveal_overlay(percent=1.0)
                    elif c_reveal_mode == 'slice':
                        toggle_slice_overlay(num_revealed=1, vertical=False)
                    elif c_reveal_mode == 'tile':
                        toggle_tile_overlay(num_revealed=1, grid_size=5)
                    elif c_reveal_mode == 'swap':
                        toggle_tile_overlay(grid_size=10, swap=True)
                elif light_mode == 'c. profile':
                    toggle_character_profile_overlay()
                elif light_mode == 'c. name':
                    top_info("MUST SAY FULL NAME", inverse=True)
                    start_title_round()
                if lightning_mode_settings.get(light_mode).get("muted"):
                    now_playing_background_music(track = None)
                    toggle_mute(True)
            elif light_mode == 'tags':
                set_cloud_tags()
                top_info("TAGS")
                toggle_tag_cloud_overlay(1)
            elif light_mode == 'episodes':
                set_light_episodes()
                toggle_episode_overlay(1)
                top_info("EPISODE TITLES")
            elif light_mode == 'names':
                light_name_overlay = True
                set_light_names()
                toggle_episode_overlay(1)
                top_info("CHARACTER NAMES")
            elif light_mode in ['clip', 'ost']:
                clip_variants = lightning_mode_settings.get("clip", {}).get("variants", {})
                clip_enabled, trailer_enabled = clip_variants.get("random_clip"), clip_variants.get("trailer")
                length = 0
                is_ost = (light_mode == 'ost')
                if is_ost:    
                    url = lightning_queue_data.get(currently_playing.get("filename", {}), {}).get("ost_url")
                else:
                    url = lightning_queue_data.get(currently_playing.get("filename", {}), {}).get("clip_url")
                if not url:
                    if not youtube_api_limited and YOUTUBE_API_KEY and (clip_enabled or is_ost):
                        length = play_random_clip(ost=is_ost)
                    elif currently_playing.get("data", {}).get("trailer") and trailer_enabled and is_ost:
                        length = play_trailer()
                elif trailer_enabled and url[1] == 'trailer':
                    length = play_trailer()
                else:
                    length = stream_url(url[0], url[1], url[2])
                if length > 0 and currently_streaming:
                    stream_start_time = get_stream_start_time(length)
                    test_print(f"Length: {length} | Stream Start Time: {stream_start_time}")
                    # stream_player.set_time(int(float(stream_start_time))*1000)
                    player.pause()
                    test_print(currently_streaming)
                    def wait_for_stream(filename, count):
                        test_print(F"Waiting...{count}")
                        stream_player.set_time(int(float(stream_start_time))*1000)
                        def restart_player():
                            stream_player.stop()
                            stream_player.play()
                            root.after(100, wait_for_stream, filename, 0)
                        if filename != currently_playing.get("filename") or not currently_streaming:
                            return
                        elif stream_player.is_playing() and stream_player.get_length() > 0:
                            def stream_overlay():
                                if light_mode == 'ost':
                                    top_info("SOUNDTRACK / OST")
                                    set_progress_overlay(0, light_round_length*100)
                                else:
                                    if last_streamed and last_streamed[3] and "Crunchyroll" in last_streamed[3]:
                                        toggle_outer_edge_overlay()
                                    if last_streamed[1] == "Trailer":
                                        top_info("TRAILER", 40)
                                    else:
                                        top_info("RANDOM CLIP", 40)
                                set_light_round_number("#" + str(light_round_number))
                            def set_stream_start():
                                stream_player.set_time(int(float(stream_start_time))*1000)
                                if light_mode == 'ost':
                                    stream_player.audio_set_volume(volume_level)
                                else:
                                    stream_player.audio_set_volume(volume_level+stream_volume_boost)
                                stream_player.set_fullscreen(False)
                                stream_player.set_fullscreen(True)
                            def start_player():
                                test_print(f"{stream_player.get_time()} =?= {int(float(stream_start_time))*1000}")
                                if stream_player.get_time() == int(float(stream_start_time))*1000:
                                    restart_player()
                                else:
                                    player.play()
                            root.after(2000, start_player)
                            set_stream_start()
                            for time in [500, 1000, 1500, 2000]:
                                root.after(time, stream_overlay)
                        elif count >= 5000:
                            restart_player()
                        else:
                            count += 100
                            root.after(100, wait_for_stream, filename, count)
                    wait_for_stream(currently_playing.get("filename"), 0)
                else:
                    if last_variety_forced:
                        variety_mode_cooldown_counts['clip'] = rnd_data.get("variety", {}).get("cooldown", {}).get("max_gap", 0)
                    toggle_mute(False)
                    root.after(500, set_black_screen, False)
            append_lightning_history()
        player.set_time(int(float(light_round_start_time))*1000)
        set_countdown(light_round_length, inverse=character_round_answer)
        set_light_round_number()
        if light_mode != 'peek':
            set_light_round_number("#" + str(light_round_number), inverse=character_round_answer)

def start_title_round():
    title_mode = get_next_title_mode(get_base_title())
    if title_mode == 'scramble':
        toggle_scramble_overlay()
    elif title_mode == 'swap':
        toggle_swap_overlay()
    else:
        set_title_light_text()
        toggle_title_overlay(get_title_light_string(min(5, max(1, len(title_light_letters) // 5))))
        set_frame_number(f"2/{min(7, len(title_light_string))}")

def set_title_light_text():
    global title_light_letters, title_light_string
    title = get_base_title()
    title_light_letters = get_unique_letters(title)
    title_light_string = title
    random.shuffle(title_light_letters)

def get_char_types_by_popularity(data=None, mode=""):
    all_types = []
    valid_types = []
    popularity_limit = True
    for char_type, enabled in lightning_mode_settings.get(mode, {}).get("character_types", {}).items():
        if char_type == "popularity_limit":
            popularity_limit = enabled
        else:
            all_types.append(char_type[0])
            if enabled:
                valid_types.append(char_type[0])
    valid_types = valid_types or all_types
    if popularity_limit:
        if not data:
            data = currently_playing.get("data", {})
        popularity = data.get("popularity", 1000) or 3000
        char_options = copy.copy(valid_types)
        if popularity > 100:
            if "s" in char_options:
                char_options.remove("s")
        if popularity > 250:
            if "a" in char_options:
                char_options.remove("a")
        return char_options or valid_types
    else:
        return valid_types

def clean_up_light_round():
    global mismatch_visuals, character_round_characters, tag_cloud_tags, light_speed_modifier, light_episode_names, light_name_overlay
    global frame_light_round_started, light_muted, character_round_answer, light_cover_image, light_trivia_answer, light_blind_one_second_count
    mismatched_player.stop()
    mismatched_player.set_media(None)  # Reset the media
    stop_stream()
    mismatch_visuals = None
    character_round_answer = None
    light_cover_image = None
    light_trivia_answer = None
    light_name_overlay = False
    light_muted = False
    frame_light_round_started = False
    character_round_characters = []
    tag_cloud_tags = []
    light_episode_names = []
    light_speed_modifier = 1
    light_blind_one_second_count = None
    player.set_rate(light_speed_modifier)
    for overlay in [set_progress_overlay, toggle_clues_overlay, toggle_song_overlay, toggle_synopsis_overlay, toggle_title_overlay, toggle_scramble_overlay, toggle_swap_overlay, 
                    toggle_peek_overlay, toggle_edge_overlay, toggle_grow_overlay, toggle_character_overlay, toggle_tag_cloud_overlay, toggle_episode_overlay, toggle_tile_overlay,
                    toggle_character_pixel_overlay, toggle_character_reveal_overlay, toggle_character_profile_overlay, spawn_pulsating_music_note, toggle_outer_edge_overlay,
                    toggle_emoji_overlay, toggle_character_image_overlay, toggle_character_blur_reveal_overlay, toggle_character_zoom_reveal_overlay, toggle_slice_overlay]:
        overlay(destroy=True)
    for info in [set_frame_number, top_info]:
        info()
    if not disable_video_audio:
        toggle_mute(False, True)
    if black_overlay:
        black_overlay.attributes("-topmost", True)
    send_scoreboard_command("show")

def light_round_transition():
    global video_stopped
    video_stopped = True
    player.pause()
    set_countdown()
    toggle_title_popup(False)
    set_black_screen(True)
    root.after(500, play_next)

def get_light_bg_color():
    if is_game(currently_playing.get("data")):
        return "Dark Red"
    else:
        return "Black"

# =========================================
#          *VARIETY LIGHTNING ROUND
# =========================================

last_round = None
last_variety_forced = False
variety_light_mode_enabled = False

variety_mode_cooldown_counts = {}
for rnd_name, rnd_data in lightning_mode_settings_default.items():
    vr = rnd_data.get("variety", {})
    if vr:
        cd = vr.get("cooldown", {})
        variety_mode_cooldown_counts[rnd_name] = random.randint(0, cd.get("max_gap", 0))
    else:
        variety_mode_cooldown_counts[rnd_name] = 0

def append_lightning_history():
    data = currently_playing.get("data", {})
    mode_limits = lightning_mode_settings.get(light_mode, {}).get("variety", {}).get("cooldown")
    if mode_limits and mode_limits.get("no_repeat_limit", 0) > 0:
        if "c." in light_mode:
            append = character_round_answer[0]
        elif light_mode == "title":
            append = get_base_title()
        else:
            append = data.get("mal")
        if append:
            playlist["lightning_history"].setdefault(light_mode, []).append(append)
            while len(playlist["lightning_history"][light_mode]) > mode_limits.get("no_repeat_limit"):
                playlist["lightning_history"][light_mode].pop(0)

def check_recent_history(mode, data=None):
    if not data:
        data = currently_playing.get("data", {})
    mode_limits = lightning_mode_settings.get(mode, {}).get("variety", {}).get("cooldown")
    if mode_limits and mode_limits.get("no_repeat_limit"):
        if "c." in mode:
            data = currently_playing.get("data", {})
            history = playlist.get("lightning_history", {}).get(mode, [])
            valid_types = get_char_types_by_popularity(data, mode)
            for char in data.get("characters", []):
                role = char[0]
                name = char[1]
                if role in valid_types and name not in history:
                    return False  # Found a character not in history
            return True  # All valid characters are in history
        elif mode == "title":
            append_check = get_base_title(data)
        else:
            append_check = data.get("mal")

        if append_check:
            return append_check in playlist.get("lightning_history", {}).get(mode, [])
    return False

_series_popularity_cache = None
def get_series_popularity(data):
    global _series_popularity_cache

    if _series_popularity_cache is None:
        _series_popularity_cache = {}
        for anime in anime_metadata.values():
            series = anime.get("series")
            if isinstance(series, list):
                series = series[0] if series else None
            if not series:
                continue
            pop = anime.get("popularity") or 3000
            if series not in _series_popularity_cache or pop < _series_popularity_cache[series]:
                _series_popularity_cache[series] = pop

    series = data.get("series")
    if isinstance(series, list):
        series = series[0] if series else None

    return _series_popularity_cache.get(series, data.get("popularity") or 3000)

def is_slug_op(slug):
    return slug.startswith("OP")

lightning_queue = None
lightning_queue_data = {}
def queue_next_lightning_mode():
    def queue_next_lightning_mode_worker():
        global lightning_queue, lightning_queue_data
        lightning_queue = None
        next_index = playlist["current_index"] + 1
        if next_index < len(playlist["playlist"]) and get_file_path(playlist["playlist"][next_index]):
            next_filename = get_clean_filename(playlist["playlist"][next_index])
        else:
            return
        
        data = get_metadata(next_filename)
        if next_filename not in lightning_queue_data:
            lightning_queue_data[next_filename] = {}

        excluded_modes = []
        next_mode = None
        while not next_mode:
            if variety_light_mode_enabled:
                next_mode = set_variety_light_mode(next_filename, excluded_modes=excluded_modes)
            else:
                next_mode = light_mode
            if next_mode in ["clip", 'ost']:
                clip_variants = lightning_mode_settings.get("clip", {}).get("variants", {})
                clip_enabled, trailer_enabled = clip_variants.get("random_clip"), clip_variants.get("trailer")
                url, name, channel, length = None, None, None, None
                if not youtube_api_limited and YOUTUBE_API_KEY and clip_enabled:
                    url, name, channel = play_random_clip(data, True, ost=(next_mode=='ost'))
                if url:
                    length = get_youtube_stream_url(url)
                elif next_mode != 'ost' and data.get("trailer") and trailer_enabled:
                    url = f"https://www.youtube.com/watch?v={data.get("trailer")}"
                    name = "trailer"
                    channel = None
                    length = get_youtube_stream_url(url)
                elif variety_light_mode_enabled:
                    excluded_modes.append(next_mode)
                    next_mode = None
                if next_mode == "ost":
                    lightning_queue_data[next_filename]["ost_url"] = [url, name, channel, length]
                else:
                    lightning_queue_data[next_filename]["clip_url"] = [url, name, channel, length]
            elif "c. " in next_mode:
                min_desc = 0
                if next_mode == 'c. profile':
                    min_desc = 120
                lightning_queue_data[next_filename]["character_answer"] = get_character_round_image(types=get_char_types_by_popularity(data, next_mode), min_desc_length=min_desc, data=data, queue=True, mode=next_mode)
            elif next_mode == "character":
                lightning_queue_data[next_filename]["characters"] = get_character_round_characters(data=data, queue=True)
            elif next_mode == "trivia":
                trivia_question = set_light_trivia(data=data, queue=True)
                if trivia_question[1] == "None" and variety_light_mode_enabled:
                    excluded_modes.append('trivia')
                    next_mode = None
                else:
                    lightning_queue_data[next_filename]["trivia"] = trivia_question
            elif next_mode == "emoji":
                if not data.get("emojis"):
                    get_emoji_clues_for_title(data)
        up_next_text()
    
    if light_mode:
        threading.Thread(target=queue_next_lightning_mode_worker, daemon=True).start()

def set_variety_light_mode(queue=None, excluded_modes=[]):
    global last_round, variety_light_mode_enabled, variety_mode_cooldown_counts, lightning_queue, last_variety_forced

    forced = False
    if not queue and lightning_queue and lightning_queue[0] == currently_playing.get("filename"):
        next_round = lightning_queue[1]
    else:
        if queue:
            data = get_metadata(queue)
        else:
            data = currently_playing.get('data', {})
        popularity = ((data.get('popularity') or 3000) + get_series_popularity(data)) / 2
        
        is_op = is_slug_op(data.get('slug', ""))
        
        variety_settings = lightning_mode_settings.get("variety", {})
        popularity_limit = variety_settings.get("popularity_limit", True)
        series_mode_limit = variety_settings.get("series_mode_limit", True)
        mode_weight = variety_settings.get("mode_weight", True)
        mode_cooldowns = variety_settings.get("mode_cooldowns", True)

        round_options = []
        for rnd_name, rnd_data in lightning_mode_settings.items():
            v_data = rnd_data.get("variety", {})
            if v_data and v_data["enabled"] and rnd_name not in excluded_modes:
                pop_limit = v_data.get("popularity", {})
                range = pop_limit.get("range", (0,0))
                if not popularity_limit:
                    range = (0,0)
                weight = pop_limit.get("weight", 10)
                if not mode_weight:
                    weight = 1
                elif isinstance(weight, dict):
                    if is_op:
                        weight = weight.get("op")
                    else:
                        weight = weight.get("ed")
                if has_lightning_mode_info(data, rnd_name) and popularity > range[0] and (not range[1] or popularity <= range[1]):
                    round_options += [rnd_name]*weight

        # Remove last round from options to avoid repeats
        round_options = [r for r in round_options if r != last_round]

        # Apply cooldown filtering
        forced_options = []
        forced_max_pop_limit = 3000
        for rnd_name, rnd_data in lightning_mode_settings.items():
            v_data = rnd_data.get("variety", {})
            cd = v_data.get("cooldown", {})
            min_cooldown = cd.get("min_gap", 0)
            max_cooldown = cd.get("max_gap", 10000)
            if not mode_cooldowns:
                min_cooldown = 0
                max_cooldown = 10000
            max_popularity_limit = cd.get("popularity_force_threshold") or INT_INF
            if isinstance(max_popularity_limit, dict):
                if is_op:
                    max_popularity_limit = max_popularity_limit.get("op") or INT_INF
                else:
                    max_popularity_limit = max_popularity_limit.get("ed") or INT_INF
            if rnd_name in round_options:
                count = variety_mode_cooldown_counts.get(rnd_name, 0)
                if (series_mode_limit and check_recent_history(rnd_name, data)) or count < min_cooldown:
                    round_options = [r for r in round_options if r != rnd_name]
                elif (max_cooldown and count >= max_cooldown) and popularity <= max_popularity_limit:
                    if forced_options:
                        if forced_max_pop_limit == max_popularity_limit:
                            forced_options.append(rnd_name)
                        elif forced_max_pop_limit < max_popularity_limit:
                            continue
                    forced_options = [rnd_name]
                    forced_max_pop_limit = max_popularity_limit

        if forced_options:
            next_round = random.choice(forced_options)
            last_variety_forced = True
            forced = True
        elif not round_options:
            next_round = "regular"
        else:
            random.shuffle(round_options)
            next_round = round_options[0]

        if queue:
            lightning_queue = [queue, next_round]
            return next_round
    
    # Update cooldown counters
    for rnd_name in lightning_mode_settings:
        if rnd_name == next_round:
            variety_mode_cooldown_counts[rnd_name] = 0
        else:
            variety_mode_cooldown_counts[rnd_name] += 1

    last_round = next_round

    if not testing_variety:
        unselect_light_modes()
        toggle_light_mode(next_round, False)
        variety_light_mode_enabled = True
        button_seleted(variety_light_mode_button, True)
    return next_round, forced

def has_lightning_mode_info(data, round_type):
    """Returns True if the given round_type has enough info for the file's data."""
    if round_type == "clues":
        return len(get_tags(data)) >= 3
    elif round_type == "song":
        return get_song_string(data, "artist") != "N/A"
    elif round_type == "synopsis":
        return len((data.get("synopsis") or "").split()) > 40
    elif round_type == "title":
        return len(get_base_title(data).replace(" ", "")) >= 7
    elif round_type == "character":
        return len(data.get("characters", [])) >= 4
    elif round_type == "cover":
        return bool(data.get("cover"))
    elif round_type == "tags":
        return len(data.get("tags", [])) >= 10
    elif round_type == "episodes":
        return len(data.get("episode_info", [])) >= 6
    elif round_type == "clip":
        return not is_game(data) and not ((youtube_api_limited or not YOUTUBE_API_KEY) and not data.get("trailer"))
    elif round_type == "ost":
        return not (youtube_api_limited or not YOUTUBE_API_KEY)
    elif round_type == "trivia":
        return data.get("trivia") or (OPENAI_API_KEY and (int(data.get("season", "9999")[-4:]) <= gpt_cutoff_year or len((data.get("synopsis") or "").split()) > 40))
    elif round_type == "emoji":
        return bool(data.get("emojis")) or OPENAI_API_KEY
    elif round_type == "names":
        return len(data.get("characters", [])) >= 6
    elif round_type in ["c. reveal", "c. profile", "c. name"]:
        if not data.get("characters"):
            return False
        if round_type == "c. profile":
            return has_char_descriptions(data.get("characters"), 120, types=get_char_types_by_popularity(data, mode="c. profile"))
        return True
    else:
        return True

testing_variety = False
def test_variety_distrbution(event=None):
    global currently_playing, testing_variety
    
    print("TESTING VARIETY LIGHTNING ROUND DISTRIBUTION:")
    i = 0
    mode_counts = {}
    testing_variety = True
    num_forced = 0
    test_count = 1000
    while i < test_count and playlist["current_index"]+i < len(playlist["playlist"]):
        filename = get_clean_filename(playlist["playlist"][playlist["current_index"]+i])
        data = get_metadata(filename)
        if not data:
            i += 1
            continue
        currently_playing = {
            "type":"theme",
            "filename":filename,
            "data":data
        }
        mode, forced = set_variety_light_mode()
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        i += 1
        if forced:
            num_forced += 1
            mode = f"{mode}[FORCED]"
        print(f"{i}. {get_display_title(data)} {format_slug(data.get("slug"))}[{data.get("popularity")}]: {mode}")
    testing_variety = False
    for m in light_modes:
        if m == "variety":
            print(f"{num_forced}/{test_count} Forced")
        else:
            print(f"{mode_counts.get(m, 0)} - {m}")

# =========================================
#          *FRAME LIGHTNING ROUND
# =========================================

frame_light_round_started = False
frame_light_round_frames = None
frame_light_round_frame_index = None
frame_light_round_frame_time = None
frame_light_round_pause = False

def get_frame_light_round_frames():
    frames = []
    buffer = 5
    length = player.get_length()-((buffer+light_round_answer_length+1)*1000)
    start_time = buffer*1000
    increment = round(length/4)
    try_count = 0
    for f in range(4):
        frame = None
        while frame is None:
            frame = random.randint(start_time, start_time + increment)/1000
            try_count = try_count + 1
            if try_count < 20:
                if length > 60 and len(frames) > 0 and (frame - frames[len(frames)-1]) <= 5:
                    frame = None
                else:
                    file_censors = censor_list.get(currently_playing.get('filename'))
                    if file_censors != None:
                        for censor in file_censors:
                            if (frame) > censor['start'] and (frame) < censor['end']:
                                frame = None
                                break
        start_time = start_time + increment
        try_count = 0
        frames.append(frame)
    random.shuffle(frames)
    return frames

def setup_frame_light_round():
    global frame_light_round_started, frame_light_round_frames, frame_light_round_frame_index, frame_light_round_frame_time, frame_light_round_pause
    toggle_coming_up_popup(False, "Lightning Round")
    frame_light_round_started = True
    player.pause()
    frame_light_round_frames = get_frame_light_round_frames()
    frame_light_round_frame_index = -1
    frame_light_round_frame_time = 5000
    frame_light_round_pause = False
    play_background_music(True)
    set_light_round_number("#" + str(light_round_number))
    root.after(500, update_frame_light_round, currently_playing.get('filename'))
    root.after(800, set_black_screen, False)

def update_frame_light_round(currently_playing_filename):
    global frame_light_round_started, frame_light_round_frames, frame_light_round_frame_index, frame_light_round_frame_time, frame_light_round_pause
    
    if not frame_light_round_started or currently_playing.get('filename') != currently_playing_filename:
        return

    show_frame_length = (light_round_length/4)*1000
    if not frame_light_round_pause:
        if not player.is_playing():
            time = int(frame_light_round_frames[frame_light_round_frame_index]*1000)
            length = player.get_length()
            apply_censors(time/1000,length/1000)
        frame_light_round_frame_time = frame_light_round_frame_time + SEEK_POLLING
        if frame_light_round_frame_index < 4:
            play_background_music(True)
            if player.is_playing():
                player.pause()
        else:
            player.play()
    else:
        play_background_music(False)
        if player.is_playing():
            player.pause()
    if frame_light_round_frame_index == 4:
        start_str = "next"
        if not light_mode:
            start_str = "end"
        set_countdown(start_str + " in..." + str(round(((light_round_answer_length*1000)-frame_light_round_frame_time)/1000)))
        if frame_light_round_frame_time >= light_round_answer_length*1000:
            light_round_transition()
            return
    else:
        if frame_light_round_frame_index > -1:
            set_countdown(int(((light_round_length*1000)-((show_frame_length*frame_light_round_frame_index)+frame_light_round_frame_time))/1000))
        if frame_light_round_frame_time >= show_frame_length:
            frame_light_round_frame_index = frame_light_round_frame_index + 1
            if frame_light_round_frame_index < len(frame_light_round_frames):
                frame_light_round_frame_time = 0
                if frame_light_round_frame_index == 0:
                    frame_light_round_frame_time = -1000
                time = int(frame_light_round_frames[frame_light_round_frame_index]*1000)
                length = player.get_length()
                apply_censors(time/1000, length/1000)
                player.set_time(time)
                player.set_fullscreen(True)
                update_progress_bar(time, length)
                set_frame_number(str(frame_light_round_frame_index+1) + "/" + str(len(frame_light_round_frames)))
            elif not is_title_window_up():
                frame_light_round_frame_time = 0
                player.play()
                toggle_title_popup(True)
                set_frame_number()
                play_background_music(False)
    
    root.after(SEEK_POLLING, update_frame_light_round, currently_playing_filename)

# =========================================
#          *CLUES LIGHTNING ROUND
# =========================================

clues_overlay = None  # Store the overlay window
clues_overlay_labels = {}  # Store references to value labels by name
def toggle_clues_overlay(destroy=False):
    global clues_overlay, clues_overlay_labels

    if destroy:
        if clues_overlay:
            screen_width = root.winfo_screenwidth()
            animate_window(clues_overlay, screen_width, 0, steps=20, delay=5, bounce=False, fade=None, destroy=True)
        clues_overlay = None
        clues_overlay_labels = {}
        return

    data = currently_playing.get("data")
    if not data or clues_overlay:
        return

    # Prepare values
    season = data.get('season', "").replace(" ", "\n")
    studio = "\n".join(data.get("studios", []))
    tags = "\n".join(get_tags(data))
    score = f"{data.get('score')}\n#{data.get('rank')}"
    popularity = f"{data.get('members') or 0:,}\n#{data.get('popularity') or 'N/A'}"
    episodes = str(data.get("episodes") or "Airing")
    type_ = data.get("type", "")
    source = data.get("source", "")
    theme = data.get("slug")
    song = get_song_string(data)

    # Create overlay
    clues_overlay = tk.Toplevel(root)
    clues_overlay.overrideredirect(True)
    clues_overlay.attributes("-topmost", True)
    clues_overlay.attributes("-alpha", 0.8)
    clues_overlay.configure(bg=OVERLAY_BACKGROUND_COLOR)

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    overlay_width = round(screen_width * 0.7)
    overlay_height = round(screen_height * 0.9)
    x = (screen_width - overlay_width) // 2
    y = (screen_height - overlay_height) // 2

    clues_overlay.geometry(f"{overlay_width}x{overlay_height}+{-screen_width}+{y}")
    clues_overlay.update_idletasks()

    # Grid layout
    clues_overlay.grid_columnconfigure(0, weight=1)
    clues_overlay.grid_columnconfigure(1, weight=1)
    clues_overlay.grid_columnconfigure(2, weight=1)
    clues_overlay.grid_rowconfigure(0, weight=1)
    clues_overlay.grid_rowconfigure(1, weight=1)
    clues_overlay.grid_rowconfigure(2, weight=1)
    clues_overlay.grid_rowconfigure(3, weight=1)

    def create_box(row, column, title, value, key, columnspan=1, rowspan=1):
        frame = tk.Frame(clues_overlay, bg=OVERLAY_BACKGROUND_COLOR, padx=scl(20), pady=scl(20), highlightbackground=OVERLAY_TEXT_COLOR, highlightthickness=scl(4))
        frame.grid(row=row, column=column, columnspan=columnspan, rowspan=rowspan, sticky="nsew", padx=scl(10), pady=scl(10))

        if title:
            tk.Label(frame, text=title.upper(), font=("Arial", scl(50), "bold", "underline"), fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR).pack(anchor="center")

        val_size = 70 - max(0, (value.count('\n') - 5) * 5)
        label = tk.Label(frame, text=value, font=("Arial", scl(val_size)), fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                         wraplength=((overlay_width // 3) * columnspan - scl(10)), justify="center")
        label.pack(fill="both", expand=True)
        clues_overlay_labels[key] = label  # Store reference

    create_box(0, 0, "Type", type_, "Type")
    create_box(0, 1, "Source", source, "Source")
    create_box(0, 2, "Episodes", "", "Episodes")
    create_box(1, 0, "Season", season, "Season")
    create_box(1, 1, "Studio", studio, "Studio")
    create_box(1, 2, "Tags", "", "Tags", rowspan=2)
    create_box(2, 0, "Score", "", "Score")
    create_box(2, 1, "Members", "", "Members")
    create_box(3, 0, None, "", "Song", columnspan=3)

    animate_window(clues_overlay, x, y, steps=20, delay=5, bounce=False, fade=None)

# =========================================
#          *SONG LIGHTNING ROUND
# =========================================

song_overlay_boxes = {}
def toggle_song_overlay(show_title=True, show_artist=True, show_theme=True, show_music=True, destroy=False):
    """Toggles the Song Lightning Round overlay with three separate boxes."""
    global song_overlay_boxes, music_icon_label
    
    # Destroy everything if requested
    if destroy:
        for box in song_overlay_boxes.values():
            if box:
                screen_width = root.winfo_screenwidth()
                animate_window(box, screen_width, box.winfo_y(), steps=20, delay=5, bounce=False, fade=None, destroy=True)
        song_overlay_boxes = {}
        return

    # Get screen dimensions
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    box_width = round(screen_width * 0.70)

    center_x = (screen_width - box_width) // 2

    # Load current song data
    data = currently_playing.get("data", {})
    slug = format_slug(data.get("slug"))
    song = get_song_string(data, "title")
    artist = get_song_string(data, "artist")
    theme_label = format_slug(slug).upper()  # e.g. "OPENING 2"

    # Each box: { key: (title, text, y_position, show?) }
    boxes = {
        "theme":   (theme_label, None, 0, int(screen_height * 0.28), scl(60), show_theme),
        "title":   ("SONG TITLE", song, 0, int(screen_height * 0.4), scl(120), show_title),
        "artist":  ("SONG ARTIST", artist, 0, int(screen_height * 0.65), scl(80), show_artist),
        "music":  ("             \n\n", None, 2, int(screen_height * 0.12), scl(70), show_music)
    }

    for key, (title, text, x_offset, y, font_size, show) in boxes.items():
        if show:
            if key not in song_overlay_boxes or (key != "music" and not song_overlay_boxes[key].winfo_exists()):
                box = tk.Toplevel(root)
                box.overrideredirect(True)
                box.attributes("-topmost", True)
                box.attributes("-alpha", 0.85)
                box.configure(bg=OVERLAY_BACKGROUND_COLOR, padx=scl(20), pady=scl(20), highlightbackground=OVERLAY_TEXT_COLOR, highlightthickness=scl(4))

                song_overlay_boxes[key] = box

                # Title label
                if key == "music":
                    title_lbl = tk.Label(box, text=title, font=("Arial", font_size, "bold"), fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR)
                else:
                    title_lbl = tk.Label(box, text=title, font=("Arial", scl(60), "bold", "underline"), fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR)
                if text:
                    title_lbl.pack(anchor="center")
                else:
                    title_lbl.pack(anchor="center", fill="both", expand=True)

                if key == "music":
                    text_lbl = tk.Label(box, text="🎵", font=("Arial", scl(1000)), bg=OVERLAY_BACKGROUND_COLOR, fg=generate_random_color(100,255))
                    text_lbl.place(relx=0.5, rely=0.5, anchor="center")
                    # Start pulsating the music icon
                    pulsate_music_icon(text_lbl)
                elif text:
                    # Text label (optional)
                    text_lbl = tk.Label(box, text=text, font=("Arial", font_size), fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR, justify="center")
                    text_lbl.pack(fill="both", expand=True)
                    adjust_font_size(text_lbl, box_width, base_size=font_size, min_size=scl(20))

                box.update_idletasks()
                box.geometry(f"+{-screen_width}+{y}")  # Adjust for bottom spacing
                box.update_idletasks()
                window_width = box.winfo_reqwidth()
                if key == "music":
                    song_overlay_boxes[key].geometry(f"+{((screen_width - window_width) // 2) + round((screen_width//10)*x_offset)}+{y}")
                else:
                    animate_window(song_overlay_boxes[key], ((screen_width - window_width) // 2) + round((screen_width//10)*x_offset), y, steps=20, delay=5, bounce=False, fade=None)
        elif key in song_overlay_boxes:
            if song_overlay_boxes[key].winfo_x() == center_x:  # Only animate out if it's on screen
                animate_window(song_overlay_boxes[key], screen_width, y, steps=20, delay=5, bounce=False, fade=None, destroy=True)
                song_overlay_boxes[key] = None

# =========================================
#       *TRIVIA LIGHTNING ROUND
# =========================================

client = None
gpt_cutoff_year = 2023
def set_openai_client_key():
    global client
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

def extract_response_text(response):
    texts = []
    for item in response.output:
        if hasattr(item, "content") and item.content:
            for c in item.content:
                if hasattr(c, "text") and c.text:
                    texts.append(c.text)
    return "\n".join(texts) if texts else None

def generate_anime_trivia(data, display=False):
    def no_trivia_available():
        return "No trivia available.", "None"
    
    mal_id = data.get("mal")
    # Get all stored trivia for this anime
    stored_trivia = ai_metadata.get(mal_id, {}).get("trivia") if mal_id else []
    if not isinstance(stored_trivia, list):
        stored_trivia = [stored_trivia] if stored_trivia else []

    if not client:
        # Return a random stored trivia if available
        if stored_trivia:
            question, answer = random.choice(stored_trivia)
            return question, answer
        return "No 'openai_api_key' set in config file.", "None"
    
    title = get_display_title(data)
    year = int(data.get("season", "9999")[-4:])

    media_type = "anime"
    if is_game(data):
        media_type = "game"

    prompt = f"""
        Generate a trivia question and answer about the {media_type} "{title}" ({year}).
        - The question must be under 40 words.
        - Start the question with: "In {title} ({year}),"
        - Avoid questions with ambiguous answers.
        - Avoid spoilers and generic questions like "Who is the main character?"
        - Do NOT make the answer a character name.
        - Do NOT use character names or any words from the anime's title in the answer.
        - Avoid questions where the answer is "Who is ___" or "What is the name of ___".
        - Do NOT make the answer a person's name.
        - Do NOT make the answer a song name or artist.
        - Do NOT ask about the number of episodes.
        - The answer should be concise and direct (not a full sentence).

        Format:
        Question: <your question>
        Answer: <your answer>
        """

    if year > gpt_cutoff_year:
        if len((data.get("synopsis") or "").split()) <= 40:
            return no_trivia_available()
        short_synopsis = data["synopsis"][:300].rsplit('.', 1)[0] + '.'
        prompt += f"""
        The anime may be too recent, so here's a synopsis you can use for context:
        [{short_synopsis}]
        """
    try:
        response = client.responses.create(
            model="gpt-4-turbo",
            input=prompt
        )

        content = extract_response_text(response)
        if display:
            print(content)
        if content and "Question:" in content and "Answer:" in content:
            question, answer = parse_trivia_response(content)
            # Only store if answer is new
            if mal_id and answer and all(answer != a for _, a in stored_trivia):
                ai_metadata.setdefault(mal_id, {}).setdefault("trivia", []).append([question, answer])
                save_metadata()
            return question, answer
        else:
            return no_trivia_available()
    except Exception as e:
        if display:
            print(e)
        return no_trivia_available()

def parse_trivia_response(response_text):
    lines = response_text.split("\n")
    q = next((line[9:] for line in lines if line.startswith("Question:")), None).strip()
    a = next((line[7:] for line in lines if line.startswith("Answer:")), None).strip()
    return q, a

light_trivia_answer = None
def set_light_trivia(data=None, queue=False, trivia_data=None):
    global light_trivia_answer, synopsis_start_index, synopsis_split
    if trivia_data:
        question, answer = trivia_data[0], trivia_data[1]
    else:
        if not data:
            data = currently_playing.get("data")
        question, answer = generate_anime_trivia(data)
    if queue:
        return [question, answer]
    else:
        synopsis_start_index = 0
        synopsis_split = question.split(" ")
        light_trivia_answer = answer

# =========================================
#          *EMOJI LIGHTNING ROUND
# =========================================

def clean_compound_emojis(emojis):
    """Replace problematic compound emojis with their base versions"""
    if not isinstance(emojis, list):
        return emojis
    
    cleaned_emojis = []
    for emoji in emojis:
        # Replace male wizard emoji with base wizard emoji
        if "🧙‍♂" in emoji or emoji == "🧙‍♂️":
            cleaned_emojis.append("🧙")  # Base wizard emoji
        else:
            cleaned_emojis.append(emoji)
    
    return cleaned_emojis

def get_emoji_clues_for_title(data):
    """Uses OpenAI to generate emoji clues for the anime's title/concept."""
    mal_id = data.get("mal")
    if mal_id and mal_id in ai_metadata and "emojis" in ai_metadata[mal_id]:
        return clean_compound_emojis(ai_metadata[mal_id]["emojis"])
    if not client or not OPENAI_API_KEY:
        return ["❓"]
    title = get_display_title(data)
    year = int(data.get("season", "9999")[-4:])
    prompt = (
        f"Give me exactly 6 emojis that represent the anime '{title}' ({year})."
        "Order them in a way to make the easier emojis later."
        "Do NOT use any words or character names. Only output emojis, separated by spaces."
    )
    try:
        response = client.responses.create(
            model="gpt-4-turbo",
            input=prompt
        )
        # Extract emojis from response
        content = extract_response_text(response)
        # Remove the length filter!
        emojis = content.split()
        if mal_id:
            ai_metadata.setdefault(mal_id, {})["emojis"] = emojis
            save_metadata()

        return emojis if emojis else ["❓"]
    except Exception as e:
        print("Emoji GPT error:", e)
        return ["❓"]

def get_emoji_image(emoji_char, size=120):
    try:
        # Ensure we're working with a properly encoded Unicode string
        if isinstance(emoji_char, str):
            # Normalize Unicode to handle compound emojis correctly
            import unicodedata
            emoji_char = unicodedata.normalize('NFC', emoji_char)
        
        font_path = r"C:\Windows\Fonts\seguiemj.ttf"
        font = ImageFont.truetype(font_path, size=size)

        # Use a large enough canvas to prevent cutoffs
        canvas_size = size * 4  # Increased to allow extra space
        im = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 0))
        draw = ImageDraw.Draw(im)

        # Draw in the middle of the large canvas
        center_position = (canvas_size // 2, canvas_size // 2)
        
        # Use embedded_color=True to preserve emoji colors and compound structure
        draw.text(center_position, emoji_char, font=font, anchor="mm", embedded_color=True)

        # Crop the image tightly around content
        bbox = im.getbbox()
        if not bbox:
            raise ValueError("Empty bounding box from rendered emoji.")

        # Calculate cropping box to center into final size
        cropped = im.crop(bbox)

        # Create a new image of the final desired size
        final_image = Image.new("RGBA", (size, size), (255, 255, 255, 0))

        # Paste the cropped emoji into the center of the final image
        cropped_w, cropped_h = cropped.size
        offset_x = (size - cropped_w) // 2
        offset_y = (size - cropped_h) // 2
        final_image.paste(cropped, (offset_x, offset_y), cropped)

        return ImageTk.PhotoImage(final_image)

    except Exception as e:
        print(f"Failed to render emoji {emoji_char}: {e}")
        return None
    
emoji_overlay_window = None
emoji_overlay_labels = None
emoji_overlay_frame = None

def toggle_emoji_overlay(emojis=None, destroy=False, max_emojis=None, title="EMOJIS"):
    global emoji_overlay_window, emoji_overlay_labels, emoji_overlay_frame

    NUM_EMOJI_SLOTS = 6
    SLOT_SIZE = scl(200)

    if destroy:
        if emoji_overlay_window and emoji_overlay_window.winfo_exists():
            emoji_overlay_window.destroy()
        emoji_overlay_window = None
        emoji_overlay_labels = None
        emoji_overlay_frame = None
        return

    if not emojis:
        data = currently_playing.get("data", {})
        emojis = get_emoji_clues_for_title(data)

    if max_emojis is not None:
        emojis = emojis[:max_emojis]

    padded_emojis = emojis + [""] * (NUM_EMOJI_SLOTS - len(emojis))

    # Create overlay and labels only once
    if not (emoji_overlay_window and emoji_overlay_window.winfo_exists()):
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        overlay_w = int(screen_w * 0.7)
        overlay_h = int(screen_h * 0.35)
        x = (screen_w - overlay_w) // 2
        y = (screen_h - overlay_h) // 2

        emoji_overlay_window = tk.Toplevel(root)
        emoji_overlay_window.overrideredirect(True)
        emoji_overlay_window.attributes("-topmost", True)
        emoji_overlay_window.attributes("-alpha", 0.9)
        emoji_overlay_window.configure(bg=OVERLAY_BACKGROUND_COLOR)
        emoji_overlay_window.geometry(f"{overlay_w}x{overlay_h}+{x}+{y}")

        frame = tk.Frame(
            emoji_overlay_window,
            bg=OVERLAY_BACKGROUND_COLOR,
            padx=scl(20),
            pady=scl(20),
            highlightbackground=OVERLAY_TEXT_COLOR,
            highlightthickness=scl(4)
        )
        frame.grid(row=0, column=0, sticky="nsew")
        emoji_overlay_window.grid_rowconfigure(0, weight=1)
        emoji_overlay_window.grid_columnconfigure(0, weight=1)

        title_label = tk.Label(
            frame,
            text=title,
            font=("Arial", scl(70), "bold", "underline"),
            fg=OVERLAY_TEXT_COLOR,
            bg=OVERLAY_BACKGROUND_COLOR,
            anchor="w",
            justify="left"
        )
        title_label.grid(row=0, column=0, sticky="w", pady=(0, scl(20)))

        emoji_row = tk.Frame(frame, bg=OVERLAY_BACKGROUND_COLOR)
        emoji_row.grid(row=1, column=0, sticky="nsew", padx=scl(20), pady=scl(10))
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        emoji_overlay_labels = []
        for i in range(NUM_EMOJI_SLOTS):
            label = tk.Label(
                emoji_row,
                text="",
                width=SLOT_SIZE // scl(20),
                height=SLOT_SIZE // scl(40),
                bg=OVERLAY_BACKGROUND_COLOR
            )
            label.grid(row=0, column=i, padx=scl(10), pady=scl(10), sticky="nsew")
            emoji_row.grid_columnconfigure(i, weight=1, minsize=SLOT_SIZE)
            emoji_overlay_labels.append(label)
        emoji_row.grid_rowconfigure(0, weight=1, minsize=SLOT_SIZE)
        emoji_overlay_frame = frame

    # Update emoji labels
    for i in range(NUM_EMOJI_SLOTS):
        emoji_char = padded_emojis[i]
        label = emoji_overlay_labels[i]
        if emoji_char:
            img = get_emoji_image(emoji_char, size=SLOT_SIZE)
            if img:
                label.config(image=img, text="")
                label.image = img  # Keep reference
            else:
                # Normalize Unicode for compound emojis in text fallback too
                import unicodedata
                normalized_emoji = unicodedata.normalize('NFC', emoji_char)
                label.config(image="", text=normalized_emoji, font=("Segoe UI Emoji", scl(120)), fg=OVERLAY_TEXT_COLOR)
        else:
            label.config(image="", text="", font=("Arial", scl(1)), fg=OVERLAY_BACKGROUND_COLOR)


# =========================================
#          *SYNOPSIS LIGHTNING ROUND
# =========================================

synopsis_start_index = None
synopsis_split = None
def pick_synopsis():
    global synopsis_start_index, synopsis_split
    if not synopsis_start_index:
        synopsis = (currently_playing.get("data", {}).get("synopsis") or "No synopsis found.")
        for extra_characters in ["\n\n[Written by MAL Rewrite]", "\n\n(Source: adapted from ANN)", "\n\n(Source: Yen Press)", " \n\n", "\n \n", "\n\n", "\n"]:
            synopsis = synopsis.replace(extra_characters, " ")
        synopsis_split = synopsis.split(" ")
        length = len(synopsis_split)
        if length <= light_round_length*2:
            synopsis_start_index = 0
        else:
            synopsis_start_index = random.randint(0, length-(light_round_length*2))

def is_end_of_sentence(word):
    if word and len(word) > 0:
        return word[-1] in ['.','!','?']
    else:
        True

TITLE_GENERIC_WORDS = {"the", "a", "an", "as", "and", "of", "in", "on", "to", "with", "for", "by", "at", "from", "no", "his", "her", "he", "she", "so"}
def get_light_synopsis_string(words = 41):
    if synopsis_start_index > 0 and not is_end_of_sentence(synopsis_split[synopsis_start_index-1]):
        text = "..."
    else:
        text = ""
    for w in range(0, words):
        if len(synopsis_split) > (w+synopsis_start_index):
            word = synopsis_split[synopsis_start_index+w]
            if not light_trivia_answer:
                data = currently_playing.get("data", {})
                word_check = word.lower().strip(',!.":')
                if "'s" in word_check and word_check[len(word_check)-1] == "s" and word_check[len(word_check)-2] == "'":
                    word_check = word_check.split("'s")[0]
                if word_check not in TITLE_GENERIC_WORDS and word_check in ((data.get("eng_title") or "") + " " + data.get("title")).replace(":","").lower().split():
                    word = word.lower().replace(word_check, "_" * len(word_check))
            if w > 0:
                text = text + " " + word
            else:
                text = text + word
        if w == 40 and not is_end_of_sentence(word):
            text = text + "..."
    return text

synopsis_overlay = None
synopsis_label = None
def toggle_synopsis_overlay(text=None, destroy=False):
    """
    Toggles a centered overlay for the Synopsis Lightning Round.
    
    Args:
        text (str): The synopsis text to display.
        destroy (bool): If True, destroys the overlay.
    """
    global synopsis_overlay, synopsis_label, synopsis_start_index

    if destroy:
        if synopsis_overlay:
            screen_width = root.winfo_screenwidth()
            animate_window(synopsis_overlay, screen_width, 0, steps=20, delay=5, bounce=False, fade=None, destroy=True)
        synopsis_overlay = None
        return

    if synopsis_overlay is None and text:
        
        title_header_txt = "SYNOPSIS:"
        back_color = OVERLAY_BACKGROUND_COLOR
        front_color = OVERLAY_TEXT_COLOR
        if light_trivia_answer:
            title_header_txt = "TRIVIA:"
            back_color = MIDDLE_OVERLAY_BACKGROUND_COLOR
            front_color = OVERLAY_BACKGROUND_COLOR

        synopsis_overlay = tk.Toplevel(root)
        synopsis_overlay.overrideredirect(True)
        synopsis_overlay.attributes("-topmost", True)
        synopsis_overlay.attributes("-alpha", 0.9)
        synopsis_overlay.configure(bg=back_color)

        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        overlay_width = round(screen_width * 0.7)
        wraplength = overlay_width - scl(60)

        # 📏 Measure how tall the label will need to be
        content_height = measure_text_height(get_light_synopsis_string(), wraplength-scl(5), font=("Arial", scl(60)))+scl(30)
        overlay_height = content_height + scl(160)  # Add space for padding/title

        x = (screen_width - overlay_width) // 2
        y = (screen_height - overlay_height) // 2

        synopsis_overlay.geometry(f"{overlay_width}x{overlay_height}+{-screen_width}+{y}")
        synopsis_overlay.update_idletasks()

        frame = tk.Frame(synopsis_overlay, bg=back_color, padx=scl(20), pady=scl(20), highlightbackground=front_color, highlightthickness=scl(4))
        frame.pack(fill="both", expand=True)


        title_label = tk.Label(frame, text=title_header_txt, font=("Arial", scl(70), "bold", "underline"),
                               fg=front_color, bg=back_color, anchor="w", justify="left")
        title_label.pack(anchor="w")

        synopsis_label = tk.Label(frame, text=text, font=("Arial", scl(60)),
                                  fg=front_color, bg=back_color, wraplength=wraplength,
                                  justify="left", anchor="nw")
        synopsis_label.pack(side="top", anchor="w", fill="x", padx=scl(10), pady=(scl(10), 0))

        animate_window(synopsis_overlay, x, y, steps=20, delay=5, bounce=False, fade=None)

    elif text is not None and synopsis_label and synopsis_label.winfo_exists():
        synopsis_label.config(text=text)

def measure_text_height(text, wraplength, font=("Arial", scl(60)), justify="left"):
    temp_root = tk.Tk()
    temp_root.withdraw()
    label = tk.Label(temp_root, text=text, font=font, wraplength=wraplength, justify=justify)
    label.update_idletasks()
    height = label.winfo_reqheight()
    temp_root.destroy()
    return height

# =========================================
#          *TITLE LIGHTNING ROUND
# =========================================

available_title_modes = []
last_title_mode = ""
def get_next_title_mode(title_text):
    global available_title_modes, last_title_mode

    all_variants = []
    available_variants = []
    for variant, enabled in lightning_mode_settings.get("title", {}).get("variants", {}).items():
        all_variants.append(variant)
        if enabled:
            available_variants.append(variant)
    available_variants = available_variants or all_variants
    if not available_title_modes:
        while not available_title_modes:
            available_title_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_title_modes) > 1 and available_title_modes[0] == last_title_mode:
                available_title_modes = []

    def get_line_count():
        screen_width = root.winfo_screenwidth()
        max_width = screen_width * 0.7 - scl(40)
        lines = get_title_text_lines(title_text, max_width, font=("Courier New", scl(80), "bold"))
        return len(lines)
    
    def get_long_word_count(length=5):
        total = 0
        for word in title_text.split(" "):
            if len(word) >= length:
                total += 1
        return total

    allowed_modes = []
    all_variants = []
    available_variants = []
    for variant, enabled in lightning_mode_settings.get("title", {}).get("variants", {}).items():
        all_variants.append(variant)
        if enabled:
            available_variants.append(variant)
    available_variants = available_variants or all_variants

    if not available_title_modes:
        # Shuffle all available variants, but avoid starting with last_title_mode if possible
        shuffled = random.sample(available_variants, k=len(available_variants))
        if len(shuffled) > 1 and shuffled[0] == last_title_mode:
            # Move last_title_mode to the end
            shuffled = shuffled[1:] + [shuffled[0]]
        available_title_modes = shuffled

    def get_line_count():
        screen_width = root.winfo_screenwidth()
        max_width = screen_width * 0.7 - scl(40)
        lines = get_title_text_lines(title_text, max_width, font=("Courier New", scl(80), "bold"))
        return len(lines)

    def get_long_word_count(length=5):
        total = 0
        for word in title_text.split(" "):
            if len(word) >= length:
                total += 1
        return total

    allowed_modes = []
    if get_line_count() <= 2:
        allowed_modes.append("scramble")
    if len(get_unique_letters(get_base_title())) >= 7:
        allowed_modes.append("reveal")
    if get_long_word_count(6):
        allowed_modes.append("swap")

    # If any allowed modes exist, always pick from those (ignore round-robin fairness for disallowed variants)
    allowed_in_queue = [m for m in available_title_modes if m in allowed_modes]
    if allowed_in_queue:
        # Strictly only pick from allowed variants
        non_repeat = [m for m in allowed_in_queue if m != last_title_mode]
        if non_repeat:
            mode = non_repeat[0]
        else:
            mode = allowed_in_queue[0]
        if mode in available_title_modes:
            available_title_modes.remove(mode)
        last_title_mode = mode
        return mode
    # If no allowed variants at all, only then pick from the rest
    if not allowed_modes:
        if available_title_modes:
            mode = available_title_modes.pop(0)
            last_title_mode = mode
            return mode
        # Should never happen, but fallback to a random variant
        mode = random.choice(available_variants)
        last_title_mode = mode
        return mode
    # If there are allowed_modes but none are in the queue, reshuffle queue to try again
    available_title_modes[:] = random.sample([m for m in available_variants if m in allowed_modes], k=len([m for m in available_variants if m in allowed_modes]))
    # Try again recursively (should always succeed now)
    return get_next_title_mode(title_text)

def get_unique_letters(title):
    letters = []
    for letter in title:
        if letter != " " and letter.lower() not in letters:
            letters.append(letter.lower())
    return letters

def get_title_light_string(letters=0):
    revealed_title = ""
    for letter in title_light_string:
        if letter != " ":
            new_letter = "ˍ"
            for l in range(0, min(len(title_light_letters), letters)):
                if title_light_letters[l] == letter.lower():
                    new_letter = letter
                    continue
            revealed_title = revealed_title + new_letter
        else:
            revealed_title = revealed_title + letter

    return revealed_title

def get_base_title(data=None, title=None):
    if not title:
        if 'character_round_answer' in globals() and character_round_answer:
            return character_round_answer[0]
        if not data and 'currently_playing' in globals():
            data = currently_playing.get("data", {})
        if data:
            title = data.get('eng_title') or data.get("title")
        else:
            title = ""
    # Remove common season/series/part suffixes
    for p in [': ', ' ']:
        for s in ['Season', 'Series', 'Part']:
            for n in ['0','1','2','3','4','5','6','7','8','9','III','II','IV','I','VIIII','VIII','VII','VI','V','X']:
                title = title.replace(f"{p}{s} {n}", "")
    for p in [': ', ' ']:
        for t in ['The ', '']:
            for n in ['First','Second','Third','Fourth','Fifth','1st','2nd','3rd','4th','5th','6th','Final']:
                for s in ['Season', 'Series', 'Part']:
                    title = title.replace(f"{p}{t}{n} {s}", "")
    return title or ""

title_overlay = None
title_overlay_canvas = None
title_overlay_items = []
title_overlay_letters = []

def toggle_title_overlay(title_text=None, destroy=False):
    """Displays an overlay with the masked anime title using persistent underscores and letter overlays."""
    global title_overlay, title_overlay_canvas, title_overlay_items, title_overlay_letters

    if destroy:
        if title_overlay:
            title_overlay.destroy()
        title_overlay = None
        title_overlay_canvas = None
        title_overlay_items = []
        title_overlay_letters = []
        return

    if not title_text:
        return

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    overlay_width = round(screen_width * 0.7)

    title_font = ("Courier New", scl(80), "bold")
    lines = get_title_text_lines(title_text, overlay_width - scl(40), font=title_font)
    overlay_height = len(lines) * scl(100) + scl(320)

    x = (screen_width - overlay_width) // 2
    y = (screen_height - overlay_height) // 2

    spacing = scl(64)
    front_color = OVERLAY_TEXT_COLOR
    back_color = OVERLAY_BACKGROUND_COLOR
    if character_round_answer:
        front_color = INVERSE_OVERLAY_TEXT_COLOR
        back_color = INVERSE_OVERLAY_BACKGROUND_COLOR

    if title_overlay is None:
        title_overlay_items = []
        title_overlay_letters = []

        title_overlay = tk.Toplevel(root)
        title_overlay.overrideredirect(True)
        title_overlay.attributes("-topmost", True)
        title_overlay.attributes("-alpha", 0.9)
        title_overlay.configure(bg=back_color)
        title_overlay.geometry(f"{screen_width}x{screen_height}+0+0")

        title_overlay_canvas = tk.Canvas(title_overlay, bg="pink", highlightthickness=0)
        title_overlay_canvas.pack(fill="both", expand=True)
        title_overlay.attributes("-transparentcolor", "pink")

        # Box and label
        title_overlay_canvas.create_rectangle(
            x, y, x + overlay_width, y + overlay_height,
            fill=back_color, outline=front_color, width=4
        )
        title_txt = "TITLE:"
        if character_round_answer:
            title_txt = "CHARACTER NAME:"
        title_overlay_canvas.create_text(
            x + scl(30), y + scl(30),
            text=title_txt, font=("Arial", scl(70), "bold", "underline"),
            fill=front_color, anchor="nw"
        )

        line_y = y + scl(270)
        idx = 0
        for line in lines:
            total_width = len(line) * spacing
            line_x = screen_width // 2 - total_width // 2 + spacing // 2
            for char in line:
                if char == " ":
                    title_overlay_items.append(None)
                    title_overlay_letters.append(None)
                    line_x += spacing
                    continue

                # Underscore (always shown)
                underscore = title_overlay_canvas.create_text(
                    line_x, line_y,
                    text="_", font=("Courier New", scl(65)),
                    fill=front_color, anchor="center"
                )
                title_overlay_items.append(underscore)

                # Letter (initially empty)
                letter = title_overlay_canvas.create_text(
                    line_x, line_y,
                    text="", font=title_font,
                    fill=front_color, anchor="center"
                )
                title_overlay_letters.append(letter)

                line_x += spacing
                idx += 1
            line_y += scl(100)

    # Update letters on top of underscores
    flat_chars = [c for c in title_text if c != " "]
    i = 0
    for idx, letter_item in enumerate(title_overlay_letters):
        if letter_item is None:
            continue
        char = flat_chars[i] if i < len(flat_chars) else ""
        if char == 'ˍ':
            char = " "
        title_overlay_canvas.itemconfig(letter_item, text=char)
        i += 1

# =========================================
#          *SCRAMBLE LIGHTNING ROUND
# =========================================

scramble_overlay_letters = []
scramble_overlay_targets = []
scramble_overlay_root = None
scramble_title_text = ""
scramble_title_canvas = None
scramble_letter_objects = []
scramble_animating = False
scramble_title_text_items = []
scramble_letter_placed_indices = set()

def toggle_scramble_overlay(num_letters=0, destroy=False):
    global scramble_overlay_letters, scramble_overlay_targets
    global scramble_overlay_root, scramble_title_text, scramble_title_canvas
    global scramble_letter_objects, scramble_animating
    global scramble_title_text_items, scramble_letter_placed_indices

    if destroy:
        scramble_animating = False
        if scramble_overlay_root:
            scramble_overlay_root.destroy()
        scramble_overlay_letters.clear()
        scramble_overlay_targets.clear()
        scramble_letter_objects.clear()
        scramble_title_text_items.clear()
        scramble_letter_placed_indices.clear()
        scramble_overlay_root = None
        scramble_title_canvas = None
        return

    front_color = OVERLAY_TEXT_COLOR
    back_color = OVERLAY_BACKGROUND_COLOR
    if character_round_answer:
        front_color = INVERSE_OVERLAY_TEXT_COLOR
        back_color = INVERSE_OVERLAY_BACKGROUND_COLOR

    if not scramble_overlay_root:
        scramble_title_text = get_base_title()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        title_font = ("Courier New", scl(80), "bold")
        # Split title into lines
        lines = get_title_text_lines(scramble_title_text, screen_w * 0.7 - scl(40), font=title_font)
        overlay_width = round(screen_w * 0.7)
        # Adjust vertical spacing: line height * number of lines + padding
        overlay_height = len(lines) * scl(100) + scl(320)
        x = (screen_w - overlay_width) // 2
        y = (screen_h - overlay_height) // 2
        box_top = y
        box_bottom = y + overlay_height

        # Transparent root
        scramble_overlay_root = tk.Toplevel()
        scramble_overlay_root.overrideredirect(True)
        scramble_overlay_root.attributes("-topmost", True)
        transparent_color = "pink"
        scramble_overlay_root.configure(bg=transparent_color)
        scramble_overlay_root.attributes("-transparentcolor", transparent_color)
        scramble_overlay_root.geometry(f"{screen_w}x{screen_h}+0+0")

        scramble_title_canvas = tk.Canvas(scramble_overlay_root, bg=transparent_color, highlightthickness=0)
        scramble_title_canvas.pack(fill="both", expand=True)

        full_overlay_height = int(screen_h*0.7)
        full_y = (screen_h - full_overlay_height) // 2
        # Draw box and label
        scramble_title_canvas.create_rectangle(
            # x, y, x + overlay_width, y + overlay_height,
            x, full_y, x + overlay_width, full_y + full_overlay_height,
            fill=back_color, outline=front_color, width=scl(4)
        )
        title_text = "TITLE:"
        if character_round_answer:
            title_text = "CHARACTER NAME:"
        scramble_title_canvas.create_text(
            # x + 30, y + 40,
            x + scl(30), full_y + scl(30),
            text=title_text,
            font=("Arial", scl(70), "bold", "underline"),
            fill=front_color,
            anchor="nw"
        )

        scramble_title_text_items.clear()
        scramble_letter_placed_indices.clear()

        spacing = scl(64)  # Increased spacing to avoid overlap
        line_y = y + scl(270)  # Moved text start down 20px for better centering
        target_coords = {}

        for line in lines:
            line_chars = [c for c in line]
            total_width = ((len(line_chars)) * spacing)
            line_x = screen_w // 2 - total_width // 2
            line_x += spacing // 2
            for c in line_chars:
                if c == " ":
                    line_x += spacing
                    continue
                text_item = scramble_title_canvas.create_text(
                    line_x, line_y,
                    text="_", font=("Courier New", scl(65)), fill=front_color, anchor="center"
                )
                target_coords[len(scramble_title_text_items)] = (line_x, line_y)
                scramble_title_text_items.append(text_item)
                line_x += spacing
            line_y += scl(100)

        # Create floating letters
        margin_x = int(screen_w * 0.18)
        top_range = (int(screen_h*0.3), box_top + scl(150))  # start 100px from top, end 150px above box top
        bottom_range = (box_bottom, screen_h - int(screen_h*0.2))  # start 100px below box bottom, leave 150px at bottom

        floating_letters = [{"char": c, "index": i} for i, c in enumerate(scramble_title_text.replace(" ", "")) if c != " " and i in target_coords]
        random.shuffle(floating_letters)

        scramble_overlay_letters.clear()
        scramble_overlay_targets.clear()
        scramble_letter_objects.clear()

        letter_positions = []  # Store positions of already placed letters
        min_distance = scl(80)      # Minimum allowed distance between letters
        
        for i, letter in enumerate(floating_letters):
            idx = letter["index"]
            tx, ty = target_coords[idx]

            # Try up to N times to find a non-colliding position
            for _ in range(50):
                if i % 2 == 0:
                    start_y = random.randint(*top_range)
                else:
                    start_y = random.randint(*bottom_range)
                start_x = random.randint(margin_x, screen_w - margin_x)

                # Check if far enough from all others
                too_close = False
                for (px, py) in letter_positions:
                    if abs(start_x - px) < min_distance and abs(start_y - py) < min_distance:
                        too_close = True
                        break

                if not too_close:
                    break  # Found a valid position

            # Save this position to the list
            letter_positions.append((start_x, start_y))

            wiggle_x = random.choice([-1, 1]) * random.randint(1, 2)
            wiggle_y = random.choice([-1, 1]) * random.randint(1, 2)

            # Draw main letter (white) on top
            label = scramble_title_canvas.create_text(
                start_x, start_y, text=letter["char"],
                font=title_font, fill=front_color
            )
            scramble_title_canvas.tag_raise(label)

            scramble_overlay_letters.append({
                "item": label,
                "char": letter["char"],
                "index": idx,
                "target": (tx, ty),
                "wiggle": (wiggle_x, wiggle_y)
            })
            scramble_overlay_targets.append(idx)
            scramble_letter_objects.append(label)

        scramble_animating = True
        animate_scramble_letters()

    # Move into place
    for i, letter in enumerate(scramble_overlay_letters):
        if i < num_letters:
            if letter["index"] not in scramble_letter_placed_indices:
                scramble_letter_placed_indices.add(letter["index"])
            x0, y0 = scramble_title_canvas.coords(letter["item"])
            x1, y1 = letter["target"]
            new_x = x0 + (x1 - x0) * 0.2
            new_y = y0 + (y1 - y0) * 0.2
            scramble_title_canvas.coords(letter["item"], new_x, new_y)

def animate_scramble_letters():
    if not scramble_animating:
        return
    for letter in scramble_overlay_letters:
        if player.is_playing() and letter["index"] not in scramble_letter_placed_indices:
            wiggle_x, wiggle_y = letter["wiggle"]
            scramble_title_canvas.move(letter["item"], wiggle_x, wiggle_y)
            letter["wiggle"] = (-wiggle_x, -wiggle_y)
    scramble_overlay_root.after(200, animate_scramble_letters)

def get_title_text_lines(text, max_width, font=("Courier New", scl(80), "bold")):
    f = Font(family=font[0], size=font[1], weight=font[2])
    words = text.split(" ")
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        if f.measure(test_line) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

# =========================================
#          *SWAP LIGHTNING ROUND
# =========================================

swap_overlay_root = None
swap_overlay_canvas = None
swap_title_text = ""
swap_title_items = []
swap_pairs = []
swap_animating = False
swap_completed = 0
swap_title_font = ("Courier New", scl(80), "bold")
swap_overlay_letters = []

def toggle_swap_overlay(num_swaps=0, destroy=False):
    global swap_overlay_root, swap_overlay_canvas
    global swap_title_text, swap_title_items, swap_pairs
    global swap_animating, swap_completed, swap_overlay_letters

    if destroy:
        swap_animating = False
        if swap_overlay_root:
            swap_overlay_root.destroy()
        swap_overlay_root = None
        swap_overlay_canvas = None
        swap_title_items.clear()
        swap_overlay_letters.clear()
        swap_pairs.clear()
        return

    front_color = OVERLAY_TEXT_COLOR
    back_color = OVERLAY_BACKGROUND_COLOR
    if character_round_answer:
        front_color = INVERSE_OVERLAY_TEXT_COLOR
        back_color = INVERSE_OVERLAY_BACKGROUND_COLOR

    if not swap_overlay_root:
        swap_title_text = get_base_title()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()

        lines = get_title_text_lines(swap_title_text, screen_w * 0.7 - scl(40), font=swap_title_font)
        overlay_width = round(screen_w * 0.7)
        overlay_height = len(lines) * scl(100) + scl(320)
        x = (screen_w - overlay_width) // 2
        y = (screen_h - overlay_height) // 2

        swap_overlay_root = tk.Toplevel()
        swap_overlay_root.overrideredirect(True)
        swap_overlay_root.attributes("-topmost", True)
        transparent_color = "pink"
        swap_overlay_root.configure(bg=transparent_color)
        swap_overlay_root.attributes("-transparentcolor", transparent_color)
        swap_overlay_root.geometry(f"{screen_w}x{screen_h}+0+0")

        swap_overlay_canvas = tk.Canvas(swap_overlay_root, bg=transparent_color, highlightthickness=0)
        swap_overlay_canvas.pack(fill="both", expand=True)

        swap_overlay_canvas.create_rectangle(
            x, y, x + overlay_width, y + overlay_height,
            fill=back_color, outline=front_color, width=4
        )
        title_text = "TITLE:" if not character_round_answer else "CHARACTER NAME:"
        swap_overlay_canvas.create_text(
            x + scl(30), y + scl(30),
            text=title_text, font=("Arial", scl(70), "bold", "underline"),
            fill=front_color, anchor="nw"
        )

        swap_title_items.clear()
        swap_overlay_letters.clear()

        spacing = scl(64)
        line_y = y + scl(270)
        target_coords = {}
        base_chars = []
        base_indices = []
        word_visual_groups = []
        current_word = []

        for line in lines:
            total_width = len(line) * spacing
            line_x = screen_w // 2 - total_width // 2 + spacing // 2
            for c in line:
                if c == " ":
                    if current_word:
                        word_visual_groups.append(current_word)
                        current_word = []
                    line_x += spacing
                    continue

                idx = len(base_chars)
                base_chars.append(c)
                base_indices.append(idx)
                current_word.append(idx)

                text_item = swap_overlay_canvas.create_text(
                    line_x, line_y,
                    text="_", font=("Courier New", scl(65)),
                    fill=front_color, anchor="center"
                )
                target_coords[idx] = (line_x, line_y)
                swap_title_items.append(text_item)
                line_x += spacing
            if current_word:
                word_visual_groups.append(current_word)
                current_word = []
            line_y += scl(100)

        total_letters = len(base_chars)
        kept = set(i for i, c in enumerate(base_chars) if c == "_")

        # Ensure one correct letter per word
        for group in word_visual_groups:
            available = [i for i in group if base_chars[i] != "_" and i not in kept]
            if available:
                kept.add(random.choice(available))

        # Keep at least 25%
        min_keep = round(total_letters * 0.25)
        extra_needed = max(0, min_keep - len(kept))
        remaining = [i for i in range(total_letters) if i not in kept and base_chars[i] != "_"]
        if extra_needed and len(remaining) >= extra_needed:
            kept.update(random.sample(remaining, extra_needed))

        swappable = [i for i in range(total_letters) if i not in kept]
        random.shuffle(swappable)
        swap_pairs.clear()
        used = set()

        while len(swappable) >= 2:
            a = swappable.pop()
            b = swappable.pop()
            if base_chars[a] != base_chars[b]:
                swap_pairs.append((a, b))
                used.add(a)
                used.add(b)

        # Odd leftover? Mark it kept
        if swappable:
            kept.add(swappable[0])

        # Apply swaps
        scrambled = base_chars[:]
        for a, b in swap_pairs:
            scrambled[a], scrambled[b] = scrambled[b], scrambled[a]

        # Draw final characters
        swap_overlay_letters.clear()
        for i, char in enumerate(scrambled):
            if i not in target_coords:
                continue
            tx, ty = target_coords[i]
            correct = scrambled[i] == base_chars[i]
            fill = front_color if correct else "gray"
            if base_chars[i] == "_":
                char = "_"
                fill = front_color
                correct = True
            letter_item = swap_overlay_canvas.create_text(
                tx, ty,
                text=char,
                font=swap_title_font,
                fill=fill,
                anchor="center"
            )
            swap_overlay_letters.append({
                "item": letter_item,
                "char": char,
                "index": i,
                "pos": (tx, ty),
                "correct": correct,
                "moving": False
            })

        swap_completed = 0
        swap_animating = True

    if swap_completed < num_swaps and swap_completed < len(swap_pairs):
        a, b = swap_pairs[swap_completed]
        item_a = next(l for l in swap_overlay_letters if l["index"] == a)
        item_b = next(l for l in swap_overlay_letters if l["index"] == b)
        animate_swap_letters(item_a, item_b)
        swap_completed += 1


def animate_swap_letters(letter_a, letter_b):
    steps = 20
    arc_height = 40
    step = 0

    x0, y0 = letter_a["pos"]
    x1, y1 = letter_b["pos"]

    def get_arc_pos(t, p0, p1, up=True):
        """Return position along arc."""
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        curve = arc_height * (1 - (2*t - 1)**2)  # peak at t=0.5
        y -= curve if up else -curve
        return x, y

    def animate():
        if player.is_playing():
            nonlocal step
            t = step / steps
            if t > 1:
                swap_overlay_canvas.coords(letter_a["item"], x1, y1)
                swap_overlay_canvas.coords(letter_b["item"], x0, y0)
                letter_a["pos"], letter_b["pos"] = (x1, y1), (x0, y0)
                # ✅ Change colors after swap is complete
                front_color = OVERLAY_TEXT_COLOR
                if character_round_answer:
                    front_color = INVERSE_OVERLAY_TEXT_COLOR
                swap_overlay_canvas.itemconfig(letter_a["item"], fill=front_color)
                swap_overlay_canvas.itemconfig(letter_b["item"], fill=front_color)
                return
            ax, ay = get_arc_pos(t, (x0, y0), (x1, y1), up=True)
            bx, by = get_arc_pos(t, (x1, y1), (x0, y0), up=False)
            swap_overlay_canvas.coords(letter_a["item"], ax, ay)
            swap_overlay_canvas.coords(letter_b["item"], bx, by)
            step += 1
        swap_overlay_root.after(20, animate)

    animate()

# =========================================
#          *PEEK LIGHTNING ROUND
# =========================================

available_peek_modes = []
last_peek_mode = ""
def get_next_peek_mode():
    global available_peek_modes, last_peek_mode

    if not available_peek_modes:
        all_variants = []
        available_variants = []
        for variant, enabled in lightning_mode_settings.get("peek", {}).get("variants", {}).items():
            all_variants.append(variant)
            if enabled:
                available_variants.append(variant)
        available_variants = available_variants or all_variants
        while not available_peek_modes:
            available_peek_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_peek_modes) > 1 and available_peek_modes[0] == last_peek_mode:
                available_peek_modes = []

    last_peek_mode = available_peek_modes.pop(0)
    return last_peek_mode

peek_modifier = 0
gap_modifier = 0
def toggle_peek():
    global peek_modifier, gap_modifier
    if not (peek_overlay1 or edge_overlay_box or grow_overlay_boxes):
        gap_modifier = 0
        peek_mode = get_next_peek_mode()
        send_scoreboard_command("hide")
        if peek_mode == 'edge':
            toggle_edge_overlay(block_percent=99)
        elif peek_mode == 'grow':
            set_grow_position()
            toggle_grow_overlay(block_percent=96, position=grow_position)
        elif peek_mode == 'slice':
            peek_modifier = random.randint(0,24)
            toggle_peek_overlay()
        if black_overlay:
            root.after(100, blind)
        button_seleted(peek_button, True)
    else:
        send_scoreboard_command("show")
        for overlay in [toggle_peek_overlay, toggle_edge_overlay, toggle_grow_overlay]:
            overlay(destroy=True)
        toggle_mute(False)

peek_round_toggle = False
def toggle_peek_round():
    global peek_round_toggle
    peek_round_toggle = not peek_round_toggle
    button_seleted(peek_round_button, peek_round_toggle)
    if peek_round_toggle:
        if blind_round_toggle:
            toggle_blind_round()
        if mute_peek_round_toggle:
            toggle_mute_peek_round()
        if special_round_warning:
            toggle_coming_up_popup(True, "Peek Round", "Guess the anime from a small window revealing the visuals.\nNormal rules apply.", queue=True)
    else:
        toggle_coming_up_popup(False, "Peek Round")

mute_peek_round_toggle = False
def toggle_mute_peek_round():
    global mute_peek_round_toggle
    mute_peek_round_toggle = not mute_peek_round_toggle
    button_seleted(mute_peek_round_button, mute_peek_round_toggle)
    if mute_peek_round_toggle:
        if peek_round_toggle:
            toggle_peek_round()
        if blind_round_toggle:
            toggle_blind_round()
        if special_round_warning:
            toggle_coming_up_popup(True, "Mute Peek Round", "Guess the anime from a small window revealing the visuals.\nAudio will also be muted.\nNormal rules apply.", queue=True)
    else:
        toggle_coming_up_popup(False, "Mute Peek Round")

def narrow_peek():
    global gap_modifier
    gap_modifier -= 1
    gap_modifier = max(0, gap_modifier)
    if edge_overlay_box:
        toggle_edge_overlay(block_percent=99-gap_modifier)
    elif grow_overlay_boxes:
        toggle_grow_overlay(block_percent=96-gap_modifier, position=grow_position)

def widen_peek():
    global gap_modifier
    gap_modifier += 1
    if edge_overlay_box:
        toggle_edge_overlay(block_percent=99-gap_modifier)
    elif grow_overlay_boxes:
        toggle_grow_overlay(block_percent=96-gap_modifier, position=grow_position)

def get_peek_gap(data):
    if light_mode == 'peek' or light_round_started:
        gap = (0 + min(9, (data.get('popularity') or 3000)/100))
    else:
        gap = 0
    return gap

peek_light_direction = None
def choose_peek_direction():
    global peek_light_direction
    new_dir = peek_light_direction
    while new_dir == peek_light_direction:
        new_dir = random.choice(["right","down"])
    peek_light_direction = new_dir

peeking = False
peek_overlay1 = None
peek_overlay2 = None
def toggle_peek_overlay(destroy=False, direction="right", progress=0, gap=0):
    """Toggles two fullscreen overlays that reveal the screen in a chosen direction by percentage.

    Args:
        destroy (bool): Whether to remove the overlays.
        direction (str): 'left', 'right', 'up', or 'down'.
        progress (int): How much to reveal, from 0 (fully covered) to 100 (fully uncovered).
        gap (int): The gap between the two overlays, as a percentage of the screen width/height.
    """
    global gap_modifier, peek_overlay1, peek_overlay2, peeking

    if destroy:
        # Always destroy both overlays and reset state
        if peek_overlay1:
            try:
                if peek_overlay1.winfo_exists():
                    peek_overlay1.destroy()
            except Exception:
                pass
            peek_overlay1 = None
        if peek_overlay2:
            try:
                if peek_overlay2.winfo_exists():
                    peek_overlay2.destroy()
            except Exception:
                pass
            peek_overlay2 = None
        gap_modifier = 0
        peeking = False
        button_seleted(peek_button, False)
        return

    if not 0 <= progress <= 100:
        return

    # If overlays exist but are not valid, destroy them before recreating
    for overlay_var in ['peek_overlay1', 'peek_overlay2']:
        overlay = globals()[overlay_var]
        if overlay and not overlay.winfo_exists():
            try:
                overlay.destroy()
            except Exception:
                pass
            globals()[overlay_var] = None

    # If overlays exist but direction or geometry changed drastically, destroy and recreate
    # (Optional: could add more logic here if overlays get out of sync)


    # Only create overlays if both are None (ensures no duplicates)
    if peek_overlay1 is None and peek_overlay2 is None:

        # image_color = get_image_color()
        image_color = "black"
        # First overlay
        if peek_overlay1 is None:
            peek_overlay1 = tk.Toplevel(root)
            peek_overlay1.overrideredirect(True)
            peek_overlay1.attributes("-topmost", True)
            peek_overlay1.configure(bg=image_color)

        # Second overlay
        if peek_overlay2 is None:
            peek_overlay2 = tk.Toplevel(root)
            peek_overlay2.overrideredirect(True)
            peek_overlay2.attributes("-topmost", True)
            peek_overlay2.configure(bg=image_color)
            
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()

    # Calculate the gap in pixels as a percentage of the screen size
    gap_pixels = int((((gap+gap_modifier) / 100) * screen_width))
    # Initialize overlay dimensions and positions
    first_width = first_height = first_x = first_y = None
    second_width = second_height = second_x = second_y = None

    cover_margin = scl(20)  # pixels to ensure full screen edge coverage

    if direction == "left":
        first_width = screen_width * (1 - progress / 100)
        first_height = screen_height
        first_x = 0
        first_y = 0

        second_width = max(0, screen_width * (progress / 100) - gap_pixels)
        second_height = screen_height
        second_x = first_width + gap_pixels
        second_y = 0

    elif direction == "right":
        first_width = screen_width * (1 - progress / 100)
        first_height = screen_height
        first_x = screen_width - first_width + cover_margin  # Extra cover on edge
        first_y = 0

        second_width = max(0, screen_width * (progress / 100) - gap_pixels)
        second_height = screen_height
        second_x = 0
        second_y = 0

    elif direction == "up":
        first_width = screen_width
        first_height = screen_height * (1 - progress / 100)
        first_x = 0
        first_y = 0

        second_width = screen_width
        second_height = max(0, screen_height * (progress / 100) - gap_pixels)
        second_x = 0
        second_y = first_height + gap_pixels

    elif direction == "down":
        first_width = screen_width
        first_height = screen_height * (1 - progress / 100)
        first_x = 0
        first_y = screen_height - first_height + cover_margin  # Extra cover on edge

        second_width = screen_width
        second_height = max(0, screen_height * (progress / 100) - gap_pixels)
        second_x = 0
        second_y = 0
    else:
        # If direction is invalid, do not proceed to use uninitialized variables
        print("Invalid direction.")
        return

    # Convert to integers for geometry calculation
    first_width = int(first_width)
    first_height = int(first_height)
    first_x = int(first_x)
    first_y = int(first_y)

    second_width = int(second_width)
    second_height = int(second_height)
    second_x = int(second_x)
    second_y = int(second_y)

    # Only update geometry if overlays were just created and geometry variables are set
    if peek_overlay1 and peek_overlay2:
        # Only update geometry if 'first_width' and related variables are defined in this scope
        if direction == "right":
            peek_overlay2.geometry(f"{first_width}x{first_height}+{first_x}+{first_y}")
            peek_overlay1.geometry(f"{second_width}x{second_height}+{second_x}+{second_y}")
        else:
            peek_overlay1.geometry(f"{first_width}x{first_height}+{first_x}+{first_y}")
            peek_overlay2.geometry(f"{second_width}x{second_height}+{second_x}+{second_y}")
        button_seleted(peek_button, True)
        lift_windows()

# =========================================
#          *EDGE LIGHTNING ROUND
# =========================================

edge_overlay_box = None

def toggle_edge_overlay(block_percent=100, destroy=False):
    global edge_overlay_box

    if destroy:
        if edge_overlay_box and edge_overlay_box.winfo_exists():
            edge_overlay_box.destroy()
        edge_overlay_box = None
        button_seleted(peek_button, False)
        return

    # Clamp block_percent
    block_percent = max(0, min(100, block_percent))

    # Get screen dimensions
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    # Determine uniform margin based on the smallest screen dimension
    visible_percent = 100 - block_percent
    margin = int(min(screen_w, screen_h) * (visible_percent / 100 / 2))

    # Calculate final box size
    width = screen_w - margin * 2
    height = screen_h - margin * 2

    x = margin
    y = margin

    # Create or update overlay
    if not edge_overlay_box or not edge_overlay_box.winfo_exists():
        edge_overlay_box = tk.Toplevel()
        edge_overlay_box.overrideredirect(True)
        edge_overlay_box.attributes("-topmost", True)
        edge_overlay_box.configure(bg="black")
        try:
            player.set_fullscreen(False)
            player.set_fullscreen(True)
        except:
            pass

    edge_overlay_box.geometry(f"{width}x{height}+{x}+{y}")
    button_seleted(peek_button, True)
    lift_windows()

scoreboard_colors_sent = False
scoreboard_align_sent = False
def send_scoreboard_command(cmd):
    def send_scoreboard_command_worker():
        global scoreboard_colors_sent, scoreboard_align_sent
        try:
            s = socket.socket()
            s.connect(("localhost", 5555))
            s.sendall(cmd.encode())
            s.close()
            if not scoreboard_colors_sent:
                scoreboard_colors_sent = True
                send_scoreboard_colors()
            if not scoreboard_align_sent:
                scoreboard_align_sent = True
                send_scoreboard_align()
        except ConnectionRefusedError:
            pass
    threading.Thread(target=send_scoreboard_command_worker, daemon=True).start()

def send_scoreboard_colors():
    send_scoreboard_command(f"[COLORS][BACK]{OVERLAY_BACKGROUND_COLOR}[TEXT]{OVERLAY_TEXT_COLOR}")

def send_scoreboard_align():
    if inverted_positions:
        send_scoreboard_command("align right")
    else:
        send_scoreboard_command("align left")

# Score change logging from scoreboard
def read_all_score_changes():
    """Read all score changes from scoreboard log file (does not clear file)"""
    try:
        if not os.path.exists("score_changes.json"):
            return []
        
        changes = []
        with open("score_changes.json", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    changes.append(json.loads(line))
        
        return changes
    except Exception as e:
        print(f"Error reading score changes: {e}")
        return []

def add_score_changes_to_session():
    """Read all score changes and add them to session_data for session logging"""
    global session_data
    changes = read_all_score_changes()
    
    # Keep track of score changes already in session_data to avoid duplicates
    existing_score_entries = [entry for entry in session_data if entry.get("type") == "scoreboard_score"]
    existing_timestamps = {entry.get("timestamp") for entry in existing_score_entries}
    
    for change in changes:
        # Skip if this score change is already in session_data
        if change['timestamp'] in existing_timestamps:
            continue
            
        # Create a session entry for the score change with consistent timestamp format
        score_entry = {
            "timestamp": change['timestamp'],  # Now using consistent datetime format
            "type": "scoreboard_score",
            "player": change['player'],
            "old_score": change['old_score'], 
            "new_score": change['new_score'],
            "delta": change['delta']
        }
        
        # Add to session_data so it appears in the session log
        session_data.append(score_entry)



# =========================================
#          *GROW LIGHTNING ROUND
# =========================================

grow_overlay_boxes = {}
grow_position = None

def set_grow_position():
    global grow_position
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    # Use a safe margin so the square never exceeds the screen
    margin = int(min(screen_w, screen_h) * 0.3)

    cx = random.randint(margin, screen_w - margin)
    cy = random.randint(margin, screen_h - margin)

    grow_position = (cx, cy)

def move_grow_position(dx, dy):
    """Move the grow overlay box by dx, dy pixels, constrained to the screen."""
    global grow_position
    if grow_position is None:
        return
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    cx, cy = grow_position
    cx = min(max(cx + dx, 0), screen_w)
    cy = min(max(cy + dy, 0), screen_h)
    grow_position = (cx, cy)
    toggle_grow_overlay(block_percent=last_grow_block_percent, position=(cx, cy))

last_grow_block_percent = 100
def toggle_grow_overlay(block_percent=100, position="center", destroy=False):
    global grow_overlay_boxes, last_grow_block_percent, grow_position

    if destroy:
        for box in grow_overlay_boxes.values():
            if box and box.winfo_exists():
                box.destroy()
        grow_overlay_boxes.clear()
        button_seleted(peek_button, False)
        return

    last_grow_block_percent = block_percent

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    block_percent = max(0, min(100, block_percent))
    visible_w = int(screen_w * (1 - block_percent / 100))
    visible_h = int(screen_h * (1 - block_percent / 100))

    # Determine center position
    if isinstance(position, tuple):
        cx, cy = position
        # Save position for movement
        grow_position = (cx, cy)
    else:  # center by default
        cx, cy = screen_w // 2, screen_h // 2
        grow_position = (cx, cy)

    left = cx - visible_w // 2
    right = cx + visible_w // 2
    top = cy - visible_h // 2
    bottom = cy + visible_h // 2

    def update_or_create(name, x, y, w, h):
        if name not in grow_overlay_boxes or not grow_overlay_boxes[name].winfo_exists():
            box = tk.Toplevel()
            box.overrideredirect(True)
            box.attributes("-topmost", True)
            box.configure(bg="black")
            grow_overlay_boxes[name] = box
        grow_overlay_boxes[name].geometry(f"{w}x{h}+{x}+{y}")

    # Top
    update_or_create("top", 0, 0, screen_w, max(0, top))
    # Bottom
    update_or_create("bottom", 0, bottom + 5, screen_w, max(0, screen_h - bottom + 20))
    if bottom + 10 < screen_h:
        update_or_create("bottom_buffer", 0, screen_h - 10, screen_w, 10)
    else:
        update_or_create("bottom_buffer", 0, screen_h, screen_w, 0)
    # Left
    update_or_create("left", 0, top - 100, max(0, left), max(0, visible_h + 200))
    # Right
    update_or_create("right", right, top - 100, max(0, screen_w - right + 5), max(0, visible_h + 200))
    if right + 10 < screen_w:
        update_or_create("right_buffer", screen_w - 10, top - 100, 10, max(0, visible_h + 200))
    else:
        update_or_create("right_buffer", screen_w, top - 100, 0, max(0, visible_h + 200))

    if grow_overlay_boxes:
        button_seleted(peek_button, True)
        lift_windows()

# =========================================
#          *MISMATCH LIGHTNING ROUND
# =========================================

cached_sfw_themes = {}
def get_cached_sfw_themes():
    global cached_sfw_themes
    cached_sfw_themes = {
        "ops":[],
        "eds":[]
    }
    for filename in directory_files:
        if not check_nsfw(filename):
            data = get_metadata(filename)
            if data:
                theme = get_song_by_slug(data, data.get("slug", ""))
                if not theme.get("nsfw"):
                    if is_slug_op(data.get("slug")):
                        cached_sfw_themes["ops"].append(filename)
                    else:
                        cached_sfw_themes["eds"].append(filename)

instance2 = vlc.Instance(
    "--no-audio", 
    "--video-on-top",
    "--no-xlib", 
    "-q", 
    "--fullscreen"
)
mismatched_player = instance2.media_player_new()
mismatch_visuals = None
def get_mismatched_theme():
    global mismatch_visuals
    match_data = currently_playing.get("data")
    if not match_data:
        return None

    is_op = is_slug_op(match_data.get("slug"))
    match_tags = set(get_tags(match_data))
    match_series = (match_data.get("series") or [match_data.get("title")])[0]
    match_season = match_data.get("season")  # e.g., "Fall 2020"

    # Convert season to year
    def extract_year(season_str):
        if season_str and isinstance(season_str, str) and season_str[-4:].isdigit():
            return int(season_str[-4:])
        return None

    match_year = extract_year(match_season)

    theme_pool = cached_sfw_themes["ops"] if is_op else cached_sfw_themes["eds"]
    if len(theme_pool) <= 1:
        theme_pool = cached_sfw_themes["ops"] + cached_sfw_themes["eds"]

    candidates = []

    for filename in theme_pool:
        file_data = get_metadata(filename)
        if not file_data:
            continue

        file_series = (file_data.get("series") or [file_data.get("title")])[0]
        if file_series == match_series:
            continue  # skip same series

        file_tags = set(get_tags(file_data))
        file_year = extract_year(file_data.get("season"))

        # Tag similarity
        tag_score = len(match_tags & file_tags)

        # Year proximity score (closer = better)
        year_score = 0
        if match_year and file_year:
            year_diff = abs(match_year - file_year)
            year_score = max(0, 5 - year_diff)  # Closer years get more points

        # Add a little randomness
        random_bonus = random.uniform(0, 1.5)

        total_score = tag_score * 1.5 + year_score + random_bonus

        candidates.append((total_score, filename, file_data))

    # Fallback to any mismatched theme if no candidates
    if not candidates:
        tries = 0
        while tries <= 10:
            filename = random.choice(theme_pool)
            file_data = get_metadata(filename)
            file_series = (file_data.get("series") or [file_data.get("title")])[0]
            if file_series != match_series:
                mismatch_visuals = get_display_title(file_data) + " " + format_slug(file_data.get("slug"))
                return filename
            tries += 1
        return None

    # Sort by score and randomly choose from top 5
    candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = candidates[:5]
    score, chosen_filename, chosen_data = random.choice(top_candidates)

    mismatch_visuals = get_display_title(chosen_data) + " " + format_slug(chosen_data.get("slug"))
    return chosen_filename

def check_nsfw(filename):
    for censor in get_file_censors(filename):
        if censor.get("nsfw"):
            return True
    return False

pulsating_note_window = None
pulsating_note_label = None

def spawn_pulsating_music_note(x=0, y=0, font_size=scl(100), destroy=False):
    global pulsating_note_window, pulsating_note_label

    if destroy:
        if pulsating_note_window and pulsating_note_window.winfo_exists():
            pulsating_note_window.destroy()
        pulsating_note_window = None
        pulsating_note_label = None
        return

    if pulsating_note_window and pulsating_note_window.winfo_exists():
        pulsating_note_window.destroy()

    # Create a transparent top-level window
    pulsating_note_window = tk.Toplevel()
    pulsating_note_window.overrideredirect(True)
    pulsating_note_window.attributes("-topmost", True)
    pulsating_note_window.attributes("-transparentcolor", "black")
    pulsating_note_window.configure(bg="black")

    # Position window to center the note on screen at (x, y)
    width = height = font_size * 3
    pulsating_note_window.geometry(f"{width}x{height}+{x - width // 2}+{y - height // 2}")

    # Create and place the label
    pulsating_note_label = tk.Label(pulsating_note_window, text="🎵", font=("Segoe UI Emoji", font_size),
                                    bg="black", fg=generate_random_color(100, 255))
    pulsating_note_label.place(relx=0.5, rely=0.5, anchor="center")

    # Start animation
    pulsate_music_icon(pulsating_note_label)

# =========================================
#          *CHARACTER LIGHTNING ROUND
# =========================================

character_overlay_boxes = {}
character_round_characters = []
character_round_image_cache_default = []
character_round_image_cache_default_urls =[
    "https://w0.peakpx.com/wallpaper/104/618/HD-wallpaper-anime-error-female-dress-black-cute-hair-windows-girl-anime-page.jpg",
    "https://i.imgflip.com/1xuu83.jpg",
    "https://www.pngarts.com/files/8/Confused-Anime-PNG-Background-Image.png",
    "https://cdn.anidb.net/misc/confused.png",
]

def get_cached_character_round_images(urls, default=False, queue=False):
    global character_round_image_cache_default, character_round_characters
    character_round_chars = []
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    img_size = int(min(screen_width, screen_height) * 0.35)
    for index, url in enumerate(urls):
        tk_img = load_image_from_url(url, size=(img_size, img_size))
        if tk_img:
            if default:
                character_round_image_cache_default.append(tk_img)
            elif queue:
                character_round_chars.append(tk_img)
            else:
                character_round_characters.append(tk_img)
        else:
            if not default and index < len(character_round_image_cache_default):
                if queue:
                    character_round_chars.append(character_round_image_cache_default[index])
                else:
                    character_round_characters.append(character_round_image_cache_default[index])
    if queue:
        return character_round_chars

def load_default_char_images():
    get_cached_character_round_images(character_round_image_cache_default_urls, default=True)

def get_character_round_characters(data=None, queue=False):
    global character_round_characters
    if not data:
        data = currently_playing.get("data")

    if data and data.get("characters"):
        main = []
        secondary = []
        appear = []
        for character in data["characters"]:
            url = "https://cdn-eu.anidb.net/images/main/" + character[2]
            if character[0] == "m":
                main.append(url)
            elif character[0] == "s":
                secondary.append(url)
            elif character[0] == "a":
                appear.append(url)

        random.shuffle(main)
        random.shuffle(secondary)
        random.shuffle(appear)

        # Start building result with up to 2 appear, 1 secondary, 1 main
        result = []
        total = 0
        for group in [[appear, 2],[secondary,1],[main,1]]:
            result += [url for url in group[0] if url not in result][:group[1]]
            total += group[1]
            # If not enough, fill from any remaining (no duplicates)
            remaining = [url for url in (appear + secondary + main) if url not in result]
            result += remaining[:total - len(result)]
        urls = result[:4]
        if queue:
            return get_cached_character_round_images(urls, queue=True)
        character_round_characters = []
        get_cached_character_round_images([urls[0]])
        def get_character_round_characters_worker():
            get_cached_character_round_images(urls[1:4])
        threading.Thread(target=get_character_round_characters_worker, daemon=True).start()
    else:
        if queue:
            return copy.copy(character_round_image_cache_default)
        else:
            character_round_characters = copy.copy(character_round_image_cache_default)

def toggle_character_overlay(num_characters=4, destroy=False):
    """Toggles the Character Lightning Round overlay in a 2x2 grid."""
    global character_overlay_boxes, character_round_characters

    # Destroy if requested
    if destroy:
        for box in character_overlay_boxes.values():
            if box and box.winfo_exists():
                screen_width = root.winfo_screenwidth()
                animate_window(box, screen_width, box.winfo_y(), steps=20, delay=5, bounce=False, fade=None, destroy=True)
        character_overlay_boxes = {}
        return

    # Only use available characters
    num_characters = min(num_characters, len(character_round_characters), 4)

    # Screen and layout setup
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    img_size = int(min(screen_width, screen_height) * 0.35)
    in_between = (screen_width) // 80
    margin_y = (screen_height - img_size * 2 - in_between) // 2
    margin_x = (screen_width - img_size * 2 - in_between) // 2

    # Grid positions: (col, row)
    grid_positions = [(0, 0), (1, 0), (0, 1), (1, 1)]

    for i in range(num_characters):
        key = f"char_{i}"
        if key in character_overlay_boxes and character_overlay_boxes[key].winfo_exists():
            continue

        box = tk.Toplevel(root)
        box.overrideredirect(True)
        box.attributes("-topmost", True)
        box.attributes("-alpha", 0.0)
        box.configure(bg="black", highlightbackground="white", highlightthickness=4)

        character_overlay_boxes[key] = box

        # Load and resize image
        if i < len(character_round_characters):
            tk_img = character_round_characters[i]
        else:
            tk_img = character_round_image_cache_default[i]
        # tk_img = load_image_from_url(character_round_characters[i], size=(img_size, img_size))

        # Set image and label
        label = tk.Label(box, image=tk_img, bg="black")
        label.image = tk_img
        label.pack()

        # Compute position in grid
        col, row = grid_positions[i]
        if col == 1:
            x = in_between + col * (img_size + margin_x)
        else:
            x = margin_x + col * (img_size + margin_x)
        if row == 1:
            y = in_between + row * (img_size + margin_y)
        else:
            y = margin_y + row * (img_size + margin_y)

        # Set size and position directly
        box.geometry(f"{img_size}x{img_size}+{x}+{y}")
        box.attributes("-alpha", 0.9)  # Ensure it's visible

# =========================================
#       *COVER LIGHTNING ROUND
# =========================================

available_cover_reveal_modes = []
last_cover_reveal_mode = ""
def get_next_cover_reveal_mode():
    global available_cover_reveal_modes, last_cover_reveal_mode

    if not available_cover_reveal_modes:
        all_variants = []
        available_variants = []
        for variant, enabled in lightning_mode_settings.get("cover", {}).get("variants", {}).items():
            all_variants.append(variant)
            if enabled:
                available_variants.append(variant)
        available_variants = available_variants or all_variants
        while not available_cover_reveal_modes:
            available_cover_reveal_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_cover_reveal_modes) > 1 and available_cover_reveal_modes[0] == last_cover_reveal_mode:
                available_cover_reveal_modes = []

    last_cover_reveal_mode = available_cover_reveal_modes.pop(0)
    return last_cover_reveal_mode

light_cover_image = None
def get_light_cover_image():
    global light_cover_image
    light_cover_image = None
    cover_url = currently_playing.get("data", {}).get("cover")
    if cover_url:
        light_cover_image = load_image_from_url(cover_url, size=None)
    light_cover_image = light_cover_image or character_round_image_cache_default[0]

# =========================================
#       *PARTS LIGHTNING ROUND
# =========================================

character_round_answer = None
def get_character_round_image(types=['m'], min_desc_length=0, data=None, queue=False, mode=None):
    """
    Returns the character image (Tk-compatible), and updates character_round_answer as:
    [name, image, gender, description]
    Falls back to secondary characters if no matches found in preferred types.
    Avoids recently used characters in lightning history, if possible.
    """
    global character_round_answer

    mode = mode or light_mode

    if not data:
        data = currently_playing.get("data")

    def return_image(name, img, gender="Unknown", desc="No description available.", queue=False):
        global character_round_answer
        if queue:
            return [name, img, gender, desc]
        else:
            character_round_answer = [name, img, gender, desc]
            return img

    if not data or not data.get("characters"):
        return return_image("Unknown", character_round_image_cache_default[0], queue=queue)

    def get_candidates(allowed_types):
        def clean(text):
            return text.strip() if text and text.strip() else ""

        return [
            (
                c[1],  # name
                "https://cdn-eu.anidb.net/images/main/" + c[2],  # image URL
                clean(c[3]) if len(c) > 3 else "Unknown",  # gender
                clean_character_description(c[1], clean(c[4])) if len(c) > 4 else ""  # description
            )
            for c in data["characters"]
            if c[0] in allowed_types
        ]

    # Get the current character-based lightning mode history
    char_history = []
    if light_mode.startswith("c."):
        char_history = playlist.get("lightning_history", {}).get(mode, [])

    # Try types in priority order, fallback to 's' if not present already
    candidates = []
    for i, t in enumerate(types):
        for candidate in get_candidates([t]):
            for i in range(len(types)-i):
                candidates.append(candidate)

    if not candidates:
        search_types = types + ['a'] if 's' in types else types + ['s']
        candidates = get_candidates(search_types)

    if not candidates:
        return return_image("Unknown", character_round_image_cache_default[0], queue=queue)

    # First, try to find a candidate with sufficient description
    long_desc_candidates = [c for c in candidates if len(c[3]) >= min_desc_length]

    # Try filtering out characters in the history
    def filter_history(pool):
        filtered = [c for c in pool if c[0] not in char_history]
        return filtered if filtered else pool  # fallback to full pool if empty

    filtered_pool = filter_history(long_desc_candidates) if long_desc_candidates else filter_history(candidates)

    random.shuffle(filtered_pool)
    name, chosen_url, gender, desc = filtered_pool[0]

    # Try loading the image
    tk_img = load_image_from_url(chosen_url, size=None)
    if not tk_img:
        return return_image(name, character_round_image_cache_default[0], gender, desc, queue=queue)

    return return_image(name, tk_img, gender, desc, queue=queue)

character_image_overlay = None
def toggle_character_image_overlay(character=None, destroy=False):
    global character_image_overlay

    if destroy or not character:
        if character_image_overlay and character_image_overlay.winfo_exists():
            character_image_overlay.destroy()
        character_image_overlay = None
        return

    if character_image_overlay and character_image_overlay.winfo_exists():
        return  # Already shown

    # Screen and scaling setup
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    target_height = int(screen_h * 0.7)

    # Get original image
    pil_image = ImageTk.getimage(character)
    img_w, img_h = pil_image.size
    scale = target_height / img_h
    new_w = int(img_w * scale)
    new_h = target_height
    resized_image = pil_image.resize((new_w, new_h), Image.LANCZOS)

    # White border
    bordered_image = Image.new("RGB", (new_w + scl(8), new_h + scl(8)), "black")
    bordered_image.paste(resized_image, (4, 4))

    tk_img = ImageTk.PhotoImage(bordered_image)

    # Create overlay window
    character_image_overlay = tk.Toplevel(root)
    character_image_overlay.overrideredirect(True)
    character_image_overlay.attributes("-topmost", True)
    character_image_overlay.attributes("-alpha", 0.95)
    character_image_overlay.configure(bg="black")

    x = (screen_w - (new_w)) // 2
    y = (screen_h - (new_h)) // 2 - int(screen_h * 0.015)
    character_image_overlay.geometry(f"{new_w + scl(8)}x{new_h + scl(8)}+{x}+{y}")

    label = tk.Label(character_image_overlay, image=tk_img, bg="black", borderwidth=0)
    label.image = tk_img  # Keep a reference
    label.pack()

def generate_weighted_zoomed_parts(tk_img, num_parts=4, target_size=(400, 400)):
    """
    Generate 4 zoomed-in square crops from semantically distinct vertical regions
    (e.g., head, torso, legs, feet). Ensures cropped areas are distinct enough vertically.
    """
    pil_image = ImageTk.getimage(tk_img).convert("RGBA")
    img_w, img_h = pil_image.size
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    img_size = int(min(screen_width, screen_height) * 0.35)
    box_w, box_h = img_size, img_size

    chosen_regions = [
        ("feet", (0.70, 1.0), (2, 4.5)),
        ("legs", (0.45, 0.8), (2, 4)),
        ("body", (0.25, 0.55), (1.5, 3.5)),
        ("head", (0.0, 0.33), (1.5, 3))
    ]

    zoomed_parts = []
    used_centers = []

    def is_solid_color(image_crop, tolerance=70):
        arr = np.array(image_crop.convert("L"))
        return arr.std() <= tolerance, arr.std()

    for region_name, (rel_start, rel_end), (zoom_min, zoom_max) in chosen_regions:
        best_attempt, best_amount = None, 0

        for attempt in range(50):
            zoom_factor = random.uniform(zoom_min, zoom_max)
            region_h = int(img_h * (rel_end - rel_start))
            crop_size = int(min(img_w, region_h) / zoom_factor)
            crop_w, crop_h = crop_size, crop_size

            y_min = int(img_h * rel_start)
            y_max = int(img_h * rel_end - crop_h)
            y_max = max(y_min, y_max)

            x_max = img_w - crop_w
            x_max = max(0, x_max)

            offset_x = random.randint(0, x_max) if x_max > 0 else 0
            offset_y = random.randint(y_min, y_max) if y_max > y_min else y_min

            vertical_center = (offset_y + crop_h / 2) / img_h

            # Check if too close to existing vertical centers
            too_close = any(abs(vertical_center - prev) < 0.15 for prev in used_centers)
            if too_close:
                continue

            cropped = pil_image.crop((offset_x, offset_y, offset_x + crop_w, offset_y + crop_h))
            is_solid, amount = is_solid_color(cropped)
            if not is_solid:
                used_centers.append(vertical_center)
                break
            elif best_amount < amount:
                best_attempt = cropped
                best_amount = amount

        else:
            cropped = best_attempt

        resized = cropped.resize((box_w, box_h), Image.LANCZOS)
        background = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        background.paste(resized, (0, 0))
        zoomed_parts.append(ImageTk.PhotoImage(background))

    return zoomed_parts

def clean_character_description(name, desc):
    # 1. Replace hyperlinks like: http://... [text] → text
    desc = re.sub(r'http\S+\s+\[([^\]]+)\]', r'\1', desc)

    # 2. Remove character name (first + last and variants)
    if name:
        parts = name.split()
        for variant in [name, name.replace(" ", ""), *parts]:
            pattern = re.compile(re.escape(variant), re.IGNORECASE)
            replacement = "_" * len(variant)
            desc = pattern.sub(replacement, desc)

    # 3. Normalize whitespace and newlines
    desc = desc.replace("\n", " ").strip()
    desc = re.sub(r'\s+', ' ', desc)

    return desc

def get_char_parts_round_character():
    """Selects one character matching given types and prepares 4 zoomed parts as separate images."""
    global character_round_characters

    # Generate zoomed-in pieces and store them
    character_round_characters = generate_weighted_zoomed_parts(character_round_answer[1])

def has_char_descriptions(characters, length, types=None):
    """
    Returns True if any character in the list has a description
    of at least the given length.

    Args:
        characters: List of character entries, each a list/tuple with:
            [role, name, image, gender, (optional) description]
        length: Minimum description length required.
        types: Optional set or list of character roles to include (e.g., ['m', 's']).

    Returns:
        True if a matching character exists, False otherwise.
    """
    for char in characters:
        if types and char[0] not in types:
            continue
        if len(char) > 4:
            desc = char[4].strip()
            if len(desc) >= length:
                return True
    return False

# =========================================
#         *PIXEL LIGHTNING ROUND
# =========================================

def generate_pixelation_steps(steps=6, final_pixel_size=4, max_pixel_size=35, pil_image=None):
    """
    Generates progressively less pixelated versions of the image.
    Returns a list of Tkinter-compatible images (most pixelated first).
    """
    """
    Generates progressively less pixelated versions of the image using easing.
    Returns a list of Tkinter-compatible images (most pixelated first).
    """
    global character_pixel_images
    if not pil_image:
        pil_image = ImageTk.getimage(character_round_answer[1]).convert("RGBA")
    width, height = pil_image.size

    # Ease-out function: starts fast, slows down at the end
    def ease_out_quad(t):
        return 1 - (1 - t) ** 2

    # Create pixel sizes using easing
    pixel_sizes = []
    for i in range(steps):
        t = i / (steps - 1)
        eased = ease_out_quad(t)
        size = int(max_pixel_size - (max_pixel_size - final_pixel_size) * eased)
        pixel_sizes.append(max(size, 1))

    pixelated_images = []
    for px in pixel_sizes:
        downscaled = pil_image.resize((max(1, width // px), max(1, height // px)), Image.NEAREST)
        pixelated = downscaled.resize((width, height), Image.NEAREST)
        pixelated_images.append(ImageTk.PhotoImage(pixelated))

    character_pixel_images = pixelated_images

character_pixel_overlay = None
character_pixel_label = None
character_pixel_images = []  # Store precomputed pixelation steps

def toggle_character_pixel_overlay(step=0, destroy=False):
    """
    Shows the character image pixelated at the given step (0 = most pixelated).
    If destroy=True, removes the overlay.
    """
    global character_pixel_overlay, character_pixel_label, character_pixel_images

    if destroy:
        if character_pixel_overlay and character_pixel_overlay.winfo_exists():
            character_pixel_overlay.destroy()
        character_pixel_overlay = None
        character_pixel_label = None
        return

    if not character_pixel_images or step >= len(character_pixel_images):
        return

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()

    # Scale to 70% of height, keep aspect ratio
    img = ImageTk.getimage(character_pixel_images[step])
    img_w, img_h = img.size
    scale = (screen_height * 0.7) / img_h
    new_w, new_h = int(img_w * scale), int(img_h * scale)

    resized_img = img.resize((new_w, new_h), Image.LANCZOS)
    display_img = ImageTk.PhotoImage(resized_img)

    # Create overlay if needed
    if not character_pixel_overlay or not character_pixel_overlay.winfo_exists():
        character_pixel_overlay = tk.Toplevel(root)
        character_pixel_overlay.overrideredirect(True)
        character_pixel_overlay.attributes("-topmost", True)
        character_pixel_overlay.attributes("-alpha", 0.95)
        character_pixel_overlay.configure(bg="black", highlightbackground="white", highlightthickness=4)

        character_pixel_label = tk.Label(character_pixel_overlay, image=display_img, bg="black", bd=0)
        character_pixel_label.image = display_img
        character_pixel_label.pack()

        x = (screen_width - new_w) // 2
        y = (screen_height - new_h) // 2
        character_pixel_overlay.geometry(f"{new_w}x{new_h}+{x}+{y}")
    else:
        character_pixel_label.configure(image=display_img)
        character_pixel_label.image = display_img

# =========================================
#          *REVEAL LIGHTNING ROUND
# =========================================

available_c_reveal_modes = []
last_c_reveal_mode = ""
def get_next_c_reveal_mode():
    global available_c_reveal_modes, last_c_reveal_mode

    if not available_c_reveal_modes:
        all_variants = []
        available_variants = []
        for variant, enabled in lightning_mode_settings.get("c. reveal", {}).get("variants", {}).items():
            all_variants.append(variant)
            if enabled:
                available_variants.append(variant)
        available_variants = available_variants or all_variants
        while not available_c_reveal_modes:
            available_c_reveal_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_c_reveal_modes) > 1 and available_c_reveal_modes[0] == last_c_reveal_mode:
                available_c_reveal_modes = []

    last_c_reveal_mode = available_c_reveal_modes.pop(0)
    return last_c_reveal_mode

reveal_image_window = None
reveal_cover_id = None
reveal_canvas = None
reveal_direction = None

def toggle_character_reveal_overlay(percent=1.0, destroy=False, direction="top"):
    """
    Displays the character image with a black overlay covering a percentage of it.
    `percent` should be between 0.0 (fully revealed) and 1.0 (fully covered).
    `direction` can be 'top', 'bottom', 'left', or 'right' to control the reveal direction.
    """
    global reveal_image_window, reveal_cover_id, reveal_canvas, reveal_direction

    if destroy:
        if reveal_image_window and reveal_image_window.winfo_exists():
            animate_window(reveal_image_window, root.winfo_screenwidth(), reveal_image_window.winfo_y(), steps=20, destroy=True)
        reveal_image_window = None
        reveal_cover_id = None
        reveal_canvas = None
        return

    if light_cover_image:
        pil_img = ImageTk.getimage(light_cover_image).copy()
    else:
        if not character_round_answer:
            return
        pil_img = ImageTk.getimage(character_round_answer[1]).copy()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    target_height = int(screen_height * 0.7)

    scale = target_height / pil_img.height
    new_size = (int(pil_img.width * scale), target_height)
    pil_img = pil_img.resize(new_size, Image.LANCZOS)
    tk_img = ImageTk.PhotoImage(pil_img)

    if not reveal_image_window or not reveal_image_window.winfo_exists():
        reveal_direction = direction
        reveal_image_window = tk.Toplevel(root)
        reveal_image_window.overrideredirect(True)
        reveal_image_window.attributes("-topmost", True)
        reveal_image_window.attributes("-alpha", 0.98)
        reveal_image_window.configure(bg="white", highlightbackground="black", highlightthickness=4)

        x = (screen_width - new_size[0]) // 2
        y = (screen_height - new_size[1]) // 2
        reveal_image_window.geometry(f"{new_size[0]}x{new_size[1]}+{x}+{y}")

        reveal_canvas = tk.Canvas(reveal_image_window, width=new_size[0], height=new_size[1], highlightthickness=0)
        reveal_canvas.pack()
        reveal_canvas.create_image(0, 0, anchor="nw", image=tk_img)
        reveal_canvas.image = tk_img

        reveal_cover_id = reveal_canvas.create_rectangle(0, 0, new_size[0], new_size[1], fill="black", outline="")

    # Update cover size based on direction and percent
    if reveal_canvas and reveal_cover_id:
        w, h = new_size
        if reveal_direction == "top":
            reveal_canvas.coords(reveal_cover_id, 0, 0, w, int(h * percent))
        elif reveal_direction == "bottom":
            reveal_canvas.coords(reveal_cover_id, 0, int(h * (1 - percent)), w, h)
        elif reveal_direction == "left":
            reveal_canvas.coords(reveal_cover_id, 0, 0, int(w * percent), h)
        elif reveal_direction == "right":
            reveal_canvas.coords(reveal_cover_id, int(w * (1 - percent)), 0, w, h)

# =========================================
#        *BLUR LIGHTNING ROUND
# =========================================

blur_reveal_image_window = None
blur_reveal_canvas = None
def toggle_character_blur_reveal_overlay(percent=1.0, destroy=False):
    """
    Displays the character image with a blurred overlay that clears as percent decreases.
    percent: 1.0 = fully blurred, 0.0 = fully clear.
    """
    global blur_reveal_image_window, blur_reveal_canvas

    if destroy:
        if blur_reveal_image_window and blur_reveal_image_window.winfo_exists():
            blur_reveal_image_window.destroy()
        blur_reveal_image_window = None
        blur_reveal_canvas = None
        return

    if light_cover_image:
        pil_img = ImageTk.getimage(light_cover_image).copy()
    else:
        if not character_round_answer:
            return
        pil_img = ImageTk.getimage(character_round_answer[1]).copy()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    target_height = int(screen_height * 0.7)
    scale = target_height / pil_img.height
    new_size = (int(pil_img.width * scale), target_height)
    pil_img = pil_img.resize(new_size, Image.LANCZOS)

    # Apply blur based on percent
    blur_radius = int(50 * percent)
    blurred_img = pil_img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    tk_blurred_img = ImageTk.PhotoImage(blurred_img)

    # Create overlay window
    if not blur_reveal_image_window or not blur_reveal_image_window.winfo_exists():
        blur_reveal_image_window = tk.Toplevel(root)
        blur_reveal_image_window.overrideredirect(True)
        blur_reveal_image_window.attributes("-topmost", True)
        blur_reveal_image_window.attributes("-alpha", 0.98)
        blur_reveal_image_window.configure(bg="white", highlightbackground="black", highlightthickness=4)

        x = (screen_width - new_size[0]) // 2
        y = (screen_height - new_size[1]) // 2
        blur_reveal_image_window.geometry(f"{new_size[0]}x{new_size[1]}+{x}+{y}")

        blur_reveal_canvas = tk.Canvas(blur_reveal_image_window, width=new_size[0], height=new_size[1], highlightthickness=0)
        blur_reveal_canvas.pack()
        blur_reveal_canvas.create_image(0, 0, anchor="nw", image=tk_blurred_img)
        blur_reveal_canvas.image = tk_blurred_img
    else:
        blur_reveal_canvas.create_image(0, 0, anchor="nw", image=tk_blurred_img)
        blur_reveal_canvas.image = tk_blurred_img

# =========================================
#          *ZOOM LIGHTNING ROUND
# =========================================

zoom_reveal_image_window = None
zoom_reveal_canvas = None
zoom_reveal_crop = None

def pick_interesting_zoom_crop(pil_img, crop_size=(0.35, 0.35), attempts=50, initial_zoom=16):
    """
    Picks a visually interesting crop for zoom reveal, scoring the *zoomed-in* region.
    Returns (crop_x, crop_y, crop_w, crop_h) in pixel coordinates.
    """
    img_w, img_h = pil_img.size
    crop_w = int(img_w * crop_size[0])
    crop_h = int(img_h * crop_size[1])
    best_crop = None
    best_score = -1

    # Calculate the view size at initial zoom
    view_w = int(img_w / initial_zoom)
    view_h = int(img_h / initial_zoom)

    for _ in range(attempts):
        # Pick a random crop
        x = random.randint(0, img_w - crop_w)
        y = random.randint(0, img_h - crop_h)
        # Center of crop
        center_x = x + crop_w // 2
        center_y = y + crop_h // 2
        # Simulate initial zoomed view
        left = max(0, center_x - view_w // 2)
        top = max(0, center_y - view_h // 2)
        right = min(img_w, left + view_w)
        bottom = min(img_h, top + view_h)
        zoomed_crop = pil_img.crop((left, top, right, bottom))
        arr = np.array(zoomed_crop.convert("L"))
        score = arr.var()
        if score > best_score:
            best_score = score
            best_crop = (x, y, crop_w, crop_h)
        if score > 500:  # tweak threshold as needed
            break
    return best_crop if best_crop else (0, 0, crop_w, crop_h)

def toggle_character_zoom_reveal_overlay(percent=1.0, destroy=False):
    """
    Displays the character image zoomed in at an interesting spot, then zooms out as percent decreases.
    percent: 1.0 = fully zoomed in, 0.0 = fully zoomed out.
    """
    global zoom_reveal_image_window, zoom_reveal_canvas, zoom_reveal_crop

    if destroy:
        if 'zoom_reveal_image_window' in globals() and zoom_reveal_image_window and zoom_reveal_image_window.winfo_exists():
            zoom_reveal_image_window.destroy()
        zoom_reveal_image_window = None
        zoom_reveal_canvas = None
        zoom_reveal_crop = None
        return

    if light_cover_image:
        pil_img = ImageTk.getimage(light_cover_image).copy()
    else:
        if not character_round_answer:
            return
        pil_img = ImageTk.getimage(character_round_answer[1]).copy()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    target_height = int(screen_height * 0.7)
    scale = target_height / pil_img.height
    new_size = (int(pil_img.width * scale), target_height)
    pil_img = pil_img.resize(new_size, Image.LANCZOS)

    # Pick an interesting crop position once, using initial zoom
    initial_zoom = 16  # Match your starting zoom
    if 'zoom_reveal_crop' not in globals() or zoom_reveal_crop is None:
        zoom_reveal_crop = pick_interesting_zoom_crop(pil_img, initial_zoom=initial_zoom)

    crop_x, crop_y, crop_w, crop_h = zoom_reveal_crop

    # Calculate zoom level
    zoom = 1.0 + percent * (initial_zoom - 1)  # 1.0 = full image, up to initial_zoom x
    center_x = crop_x + crop_w // 2
    center_y = crop_y + crop_h // 2
    view_w = int(new_size[0] / zoom)
    view_h = int(new_size[1] / zoom)
    left = max(0, center_x - view_w // 2)
    top = max(0, center_y - view_h // 2)
    right = min(new_size[0], left + view_w)
    bottom = min(new_size[1], top + view_h)
    cropped = pil_img.crop((left, top, right, bottom))
    cropped = cropped.resize(new_size, Image.LANCZOS)
    tk_cropped_img = ImageTk.PhotoImage(cropped)

    # Create overlay window
    if 'zoom_reveal_image_window' not in globals() or not zoom_reveal_image_window or not zoom_reveal_image_window.winfo_exists():
        zoom_reveal_image_window = tk.Toplevel(root)
        zoom_reveal_image_window.overrideredirect(True)
        zoom_reveal_image_window.attributes("-topmost", True)
        zoom_reveal_image_window.attributes("-alpha", 0.98)
        zoom_reveal_image_window.configure(bg="white", highlightbackground="black", highlightthickness=4)

        x = (screen_width - new_size[0]) // 2
        y = (screen_height - new_size[1]) // 2
        zoom_reveal_image_window.geometry(f"{new_size[0]}x{new_size[1]}+{x}+{y}")

        zoom_reveal_canvas = tk.Canvas(zoom_reveal_image_window, width=new_size[0], height=new_size[1], highlightthickness=0)
        zoom_reveal_canvas.pack()
        zoom_reveal_canvas.create_image(0, 0, anchor="nw", image=tk_cropped_img)
        zoom_reveal_canvas.image = tk_cropped_img
    else:
        zoom_reveal_canvas.create_image(0, 0, anchor="nw", image=tk_cropped_img)
        zoom_reveal_canvas.image = tk_cropped_img

# =========================================
#          *SLICE LIGHTNING ROUND
# =========================================

def generate_image_slices(tk_img, num_slices=10, vertical=True):
    """
    Slices the image into num_slices vertical (or horizontal) parts.
    Returns a list of PIL images (not Tkinter PhotoImages).
    """
    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size
    slices = []
    for i in range(num_slices):
        if vertical:
            left = int(i * w / num_slices)
            right = int((i + 1) * w / num_slices)
            box = (left, 0, right, h)
        else:
            top = int(i * h / num_slices)
            bottom = int((i + 1) * h / num_slices)
            box = (0, top, w, bottom)
        part = pil_img.crop(box)
        slices.append((part, box))
    return slices

slice_overlay_window = None
slice_overlay_label = None
slice_overlay_parts = []
slice_overlay_order = []

def toggle_slice_overlay(num_revealed=10, num_slices=10, vertical=True, swap=False, destroy=False):
    """
    Shows the image sliced into num_slices parts.
    If swap=True, all slices are visible but their positions are shuffled.
    If swap=False, only num_revealed slices are shown in a random order.
    """
    global slice_overlay_window, slice_overlay_label, slice_overlay_parts, slice_overlay_order

    # Destroy overlay if requested
    if destroy:
        if slice_overlay_window and slice_overlay_window.winfo_exists():
            slice_overlay_window.destroy()
        slice_overlay_window = None
        slice_overlay_label = None
        slice_overlay_parts = []
        slice_overlay_order = []
        return

    # Use character_round_answer or light_cover_image
    if character_round_answer:
        tk_img = character_round_answer[1]
    elif light_cover_image:
        tk_img = light_cover_image
    else:
        return

    # Generate slices only once
    if not slice_overlay_parts or len(slice_overlay_parts) != num_slices:
        slice_overlay_parts = generate_image_slices(tk_img, num_slices, vertical)
        slice_overlay_order = list(range(num_slices))
        random.shuffle(slice_overlay_order)

    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size

    # Compose slices onto a transparent background
    composite = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if swap:
        swap_order = slice_overlay_order[:]
        random.shuffle(swap_order)
        for i, idx in enumerate(swap_order):
            part, box = slice_overlay_parts[idx]
            # Compute new box position for this slice
            if vertical:
                left = int(i * w / num_slices)
                right = int((i + 1) * w / num_slices)
                new_box = (left, 0, right, h)
                # Resize part to fit new_box
                part_resized = part.resize((right - left, h), Image.LANCZOS)
            else:
                top = int(i * h / num_slices)
                bottom = int((i + 1) * h / num_slices)
                new_box = (0, top, w, bottom)
                part_resized = part.resize((w, bottom - top), Image.LANCZOS)
            composite.paste(part_resized, new_box)
    else:
        # Reveal slices in random order
        for i in range(num_revealed):
            idx = slice_overlay_order[i]
            part, box = slice_overlay_parts[idx]
            composite.paste(part, box)

    # Resize for display
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    target_h = int(screen_h * 0.7)
    scale = target_h / h
    img_w = int(w * scale)
    img_h = target_h
    composite = composite.resize((img_w, img_h), Image.LANCZOS)
    tk_composite = ImageTk.PhotoImage(composite)

    # Create or update overlay window
    x = (screen_w - img_w) // 2
    y = (screen_h - img_h) // 2

    if not slice_overlay_window or not slice_overlay_window.winfo_exists():
        slice_overlay_window = tk.Toplevel(root)
        slice_overlay_window.overrideredirect(True)
        slice_overlay_window.attributes("-topmost", True)
        slice_overlay_window.attributes("-alpha", 0.98)
        slice_overlay_window.configure(bg="white", highlightbackground="black", highlightthickness=2)
        slice_overlay_window.geometry(f"{img_w}x{img_h}+{x}+{y}")

        slice_overlay_label = tk.Label(slice_overlay_window, image=tk_composite, bg="white")
        slice_overlay_label.image = tk_composite
        slice_overlay_label.pack()
    else:
        slice_overlay_label.configure(image=tk_composite)
        slice_overlay_label.image = tk_composite
        slice_overlay_window.geometry(f"{img_w}x{img_h}+{x}+{y}")
                
# =========================================
#        *TILE LIGHTNING ROUND
# =========================================

def is_solid_color(image_crop, tolerance=30):
    arr = np.array(image_crop.convert("RGB"))
    # If the standard deviation is low, it's a solid color
    return arr.std() < tolerance

def generate_image_grid_slices(tk_img, grid_size=4, ignore_solid=True):
    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size
    tile_w = w // grid_size
    tile_h = h // grid_size
    slices = []
    for row in range(grid_size):
        for col in range(grid_size):
            left = col * tile_w
            top = row * tile_h
            right = left + tile_w if col < grid_size - 1 else w
            bottom = top + tile_h if row < grid_size - 1 else h
            box = (left, top, right, bottom)
            part = pil_img.crop(box)
            if not is_solid_color(part, tolerance=30) or not ignore_solid:  # Only add if not solid
                slices.append((part, box, (row, col)))
    return slices

tile_overlay_window = None
tile_overlay_label = None
tile_overlay_parts = []
tile_overlay_order = []
tile_overlay_swap = False
tile_overlay_grid_size = 4

def toggle_tile_overlay(num_revealed=1, grid_size=4, swap=False, destroy=False):
    """
    If swap=False: reveals num_revealed tiles in a random order, rest hidden.
    If swap=True: all tiles shown, but only num_revealed unique swaps are restored to correct positions.
    Tiles in the wrong position are dimmed.
    """
    global tile_overlay_window, tile_overlay_label, tile_overlay_parts, tile_overlay_order, tile_overlay_swap, tile_overlay_grid_size

    if destroy:
        if tile_overlay_window and tile_overlay_window.winfo_exists():
            tile_overlay_window.destroy()
        tile_overlay_window = None
        tile_overlay_label = None
        tile_overlay_parts = []
        tile_overlay_order = []
        tile_overlay_swap = False
        return

    if character_round_answer:
        tk_img = character_round_answer[1]
    elif light_cover_image:
        tk_img = light_cover_image
    else:
        return

    # Only generate once per round
    if not tile_overlay_parts:
        tile_overlay_grid_size = grid_size
        tile_overlay_parts = generate_image_grid_slices(tk_img, grid_size, ignore_solid=not swap)
        tile_overlay_order = list(range(len(tile_overlay_parts)))
        
        if swap:
            # For swap mode, start with correct order and create meaningful scramble
            toggle_tile_overlay.swap_order = tile_overlay_order[:]  # Start correct: [0,1,2,3,4,...]
            
            # Create swap pairs that will scramble the puzzle meaningfully
            swap_pairs = []
            used = set()
            order_copy = toggle_tile_overlay.swap_order[:]
            available_positions = list(range(len(order_copy)))
            random.shuffle(available_positions)
            
            # Create random pairs and apply swaps to scramble the order
            i = 0
            while i < len(available_positions) - 1:
                pos_a = available_positions[i]
                pos_b = available_positions[i + 1]
                
                if pos_a not in used and pos_b not in used:
                    # Swap these two random positions to create the scrambled puzzle
                    order_copy[pos_a], order_copy[pos_b] = order_copy[pos_b], order_copy[pos_a]
                    swap_pairs.append((pos_a, pos_b))
                    used.update([pos_a, pos_b])
                    i += 2
                else:
                    i += 1
            
            # The scrambled order becomes our starting state
            toggle_tile_overlay.swap_order = order_copy
            random.shuffle(swap_pairs)  # Randomize which swaps happen when
            toggle_tile_overlay.swap_pairs = swap_pairs
        else:
            # For regular mode, shuffle normally
            random.shuffle(tile_overlay_order)

    pil_img = ImageTk.getimage(tk_img).convert("RGBA")
    w, h = pil_img.size
    composite = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if swap:
        tile_overlay_swap = True
        swap_order = toggle_tile_overlay.swap_order[:]
        # Perform up to num_revealed unique swaps from precomputed swap_pairs
        if hasattr(toggle_tile_overlay, "swap_pairs"):
            swaps_to_do = toggle_tile_overlay.swap_pairs[:num_revealed]
            for a, b in swaps_to_do:
                # Actually swap the tiles at positions a and b
                swap_order[a], swap_order[b] = swap_order[b], swap_order[a]
        grid_cols = tile_overlay_grid_size
        for i, idx in enumerate(swap_order):
            part, box, (row, col) = tile_overlay_parts[idx]
            grid_row = i // grid_cols
            grid_col = i % grid_cols
            left = grid_col * (w // grid_cols)
            top = grid_row * (h // grid_cols)
            right = left + (w // grid_cols) if grid_col < grid_cols - 1 else w
            bottom = top + (h // grid_cols) if grid_row < grid_cols - 1 else h
            new_box = (left, top, right, bottom)
            part_resized = part.resize((right - left, bottom - top), Image.LANCZOS)
            # Dim if not in correct position
            if idx != i:
                overlay = Image.new("RGBA", part_resized.size, (0, 0, 0, 100))
                part_resized = Image.alpha_composite(part_resized, overlay)
            if (right - left) > 0 and (bottom - top) > 0:
                composite.paste(part_resized, new_box)
    else:
        # Reveal tiles in the same shuffled order each time
        for i in range(num_revealed):
            idx = tile_overlay_order[i]
            part, box, _ = tile_overlay_parts[idx]
            composite.paste(part, box)

    # Resize for display
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    target_h = int(screen_h * 0.7)
    scale = target_h / h
    img_w = int(w * scale)
    img_h = target_h
    composite = composite.resize((img_w, img_h), Image.LANCZOS)
    tk_composite = ImageTk.PhotoImage(composite)

    x = (screen_w - img_w) // 2
    y = (screen_h - img_h) // 2

    if not tile_overlay_window or not tile_overlay_window.winfo_exists():
        tile_overlay_window = tk.Toplevel(root)
        tile_overlay_window.overrideredirect(True)
        tile_overlay_window.attributes("-topmost", True)
        tile_overlay_window.attributes("-alpha", 0.98)
        tile_overlay_window.configure(bg="white", highlightbackground="black", highlightthickness=2)
        tile_overlay_window.geometry(f"{img_w}x{img_h}+{x}+{y}")

        tile_overlay_label = tk.Label(tile_overlay_window, image=tk_composite, bg="gray")
        tile_overlay_label.image = tk_composite
        tile_overlay_label.pack()
    else:
        tile_overlay_label.configure(image=tk_composite)
        tile_overlay_label.image = tk_composite
        tile_overlay_window.geometry(f"{img_w}x{img_h}+{x}+{y}")

# =========================================
#        *PROFILE LIGHTNING ROUND
# =========================================

profile_overlay_window = None
profile_text_label = None
profile_image_label = None
profile_words_shown = 0

def toggle_character_profile_overlay(word_count=0, image_countdown=15, destroy=False):
    """Displays a character profile with gender, a word-by-word BIO, and delayed image reveal."""
    global profile_overlay_window, profile_text_label, profile_image_label, profile_words_shown

    if destroy:
        if profile_overlay_window and profile_overlay_window.winfo_exists():
            animate_window(profile_overlay_window, root.winfo_screenwidth(), profile_overlay_window.winfo_y(), destroy=True)
        profile_overlay_window = None
        return

    if not character_round_answer:
        return

    name, img, gender, desc = character_round_answer
    word_count
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    target_width = int(screen_width * 0.7)
    target_height = int(screen_height * 0.7)

    back_color = INVERSE_OVERLAY_BACKGROUND_COLOR
    front_color = INVERSE_OVERLAY_TEXT_COLOR

    # Scale image to fit vertically
    pil_img = ImageTk.getimage(img).copy()
    scale = target_height / pil_img.height
    scaled_width = int(pil_img.width * scale)
    scaled_img = pil_img.resize((scaled_width, target_height), Image.LANCZOS)
    tk_scaled_img = ImageTk.PhotoImage(scaled_img)# Create a very blurry version of the image
    blurred_img = scaled_img.filter(ImageFilter.GaussianBlur(radius=100))
    tk_blurred_img = ImageTk.PhotoImage(blurred_img)

    # Let's say text area should match image width roughly or be slightly narrower
    desc_width =  (target_width // 3)*2 # max(int(target_width - tk_scaled_img.width()), int(target_width // 3))
    image_width = target_width - desc_width
    wraplength = desc_width - scl(20)

    font_title = ("Arial", scl(60), "bold", "underline")
    font_body = ("Arial", scl(50))

    if not profile_overlay_window or not profile_overlay_window.winfo_exists():
        # Create the main window
        profile_overlay_window = tk.Toplevel(root)
        profile_overlay_window.overrideredirect(True)
        profile_overlay_window.attributes("-topmost", True)
        profile_overlay_window.attributes("-alpha", 0.95)
        profile_overlay_window.configure(bg=back_color, highlightbackground=front_color, highlightthickness=4)

        x = (screen_width - target_width) // 2
        y = (screen_height - target_height) // 2
        profile_overlay_window.geometry(f"{target_width}x{target_height}+{x}+{y}")

        # Main layout container
        container = tk.Frame(profile_overlay_window, bg=back_color)
        container.pack(fill="both", expand=True)

        # Split left/right
        left_frame = tk.Frame(container, bg=back_color)
        left_frame.pack(side="left", fill="both", expand=False, ipadx=5, ipady=10, padx=5, pady=10)
        left_frame.config(width=desc_width, height=target_height)

        right_frame = tk.Frame(container, bg=back_color)
        right_frame.pack(side="right", fill="both", expand=False, ipadx=5, ipady=5, padx=5, pady=10)
        right_frame.config(width=image_width, height=target_height)

        bio_label = tk.Label(left_frame, text="CHARACTER DESCRIPTION:", font=font_title, bg=back_color, fg=front_color,
                             wraplength=wraplength, justify="left", anchor="nw")
        bio_label.pack(side="top", anchor="w", fill="x", padx=scl(10), pady=(scl(10), 0))

        profile_text_label = tk.Label(left_frame, text="", font=font_body, bg=back_color, fg=front_color,
                             wraplength=wraplength, justify="left", anchor="nw")
        profile_text_label.pack(side="top", anchor="w", fill="x", padx=scl(10), pady=(scl(10), 0))

        # Right: Image or countdown
        profile_image_label = tk.Label(right_frame, bg=back_color)
        profile_image_label.pack(expand=True)

        # Store resized image
        profile_image_label.scaled_img = tk_scaled_img

    # Show the countdown or image
    if image_countdown > 0:
        profile_image_label.config(
            image=tk_blurred_img,
            text="",
            bg=back_color
        )
        profile_image_label.image = tk_blurred_img
    else:
        profile_image_label.config(
            image=profile_image_label.scaled_img,
            text="",
            bg=back_color
        )
        profile_image_label.image = profile_image_label.scaled_img

    def update_profile_bio_text(description, word_limit, wraplength, label_font, max_lines=11):
        global profile_overlay_window

        if isinstance(label_font, tuple):
            label_font = font.Font(font=label_font)

        # Lazy init dummy label
        if not hasattr(update_profile_bio_text, "_dummy_label"):
            update_profile_bio_text._dummy_label = tk.Label(
                profile_overlay_window, font=label_font, wraplength=wraplength,
                justify="left", bg=back_color, fg=front_color
            )
            update_profile_bio_text._dummy_label.place(x=-5000, y=-5000)

        dummy = update_profile_bio_text._dummy_label
        words = description.split()
        trimmed_words = words[:word_limit]

        current_text = ""
        visible_text = ""
        dummy.config(text="")  # reset
        dummy.update_idletasks()

        line_height = label_font.metrics("linespace")
        current_lines = 0

        for i, word in enumerate(trimmed_words):
            test_text = current_text + (" " if current_text else "") + word
            dummy.config(text=test_text)
            dummy.update_idletasks()

            height = dummy.winfo_height()
            new_lines = max(1, height // line_height)

            if new_lines > max_lines:
                break

            current_text = test_text
            visible_text = current_text
            current_lines = new_lines

        # Try to add ellipsis without exceeding max lines
        if visible_text != " ".join(trimmed_words):
            ellipsed_text = visible_text.rstrip() + "..."
            dummy.config(text=ellipsed_text)
            dummy.update_idletasks()
            height = dummy.winfo_height()
            if height // line_height <= max_lines:
                visible_text = ellipsed_text
            else:
                # Try trimming back a bit to fit the ellipsis
                for j in range(len(visible_text.split()) - 1, 0, -1):
                    short_text = " ".join(visible_text.split()[:j]) + "..."
                    dummy.config(text=short_text)
                    dummy.update_idletasks()
                    height = dummy.winfo_height()
                    if height // line_height <= max_lines:
                        visible_text = short_text
                        break

        profile_text_label.config(text=visible_text)

    update_profile_bio_text(f"Gender: {gender.capitalize()}. {desc}", word_count+2, wraplength, font_body)

# =========================================
#          *TAGS LIGHTNING ROUND
# =========================================

tag_cloud_tags = []

def set_cloud_tags():
    global tag_cloud_tags
    data = currently_playing.get("data")
    if data:
        tags = []
        if data.get("tags"):
            for tag in data.get("tags"):
                tags.append({"name": tag[0].replace(" - to be split and deleted", "").replace(" -- to be split and deleted", ""), "weight": tag[1]})
        else:
            for tag in get_tags(data):
                tags.append({"name": tag, "weight": 600})
            tags.append({"name": "only MAL tags", "weight": 600})
    else:
        tags = [
            {"name": "no tags found", "weight": 600}
        ]
    tag_cloud_tags = sorted(tags, key=lambda t: t["weight"], reverse=True)
    weights = [t["weight"] for t in tag_cloud_tags]
    min_w, max_w = min(weights), max(weights)

    # Adjust font size range based on number of tags
    min_font_size = scl(max(22, 60 - len(tag_cloud_tags)))
    max_font_size = scl(max(min_font_size+6, 60 - len(tag_cloud_tags) // 4))  # Smaller range for many tags

    font_range = max_font_size - min_font_size

    def font_size(w):
        # Normalize weight and apply squash (square root) to reduce disparity
        normalized = (w - min_w) / (max_w - min_w + 1e-5)
        squashed = normalized ** 0.5  # reduces the extreme difference
        return int(min_font_size + font_range * squashed)

    random.shuffle(tag_cloud_tags)
    if currently_playing.get("data", {}).get("season"):
        tag_cloud_tags.insert(0, {"name": currently_playing.get("data", {}).get("season")[-4:], "weight": 600})
    for t in tag_cloud_tags:
        t["font_size"] = font_size(t["weight"])

# Globals
tag_overlay_boxes = {}
tag_cloud_positions = []

def toggle_tag_cloud_overlay(num_tags=1, destroy=False):
    global tag_overlay_boxes, tag_cloud_tags, tag_cloud_positions

    if destroy:
        for box in tag_overlay_boxes.values():
            if box and box.winfo_exists():
                box.destroy()
        tag_overlay_boxes.clear()
        tag_cloud_positions.clear()
        return

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    cx, cy = screen_w // 2, screen_h // 2
    margin = scl(50)

    def boxes_overlap(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return not (ax + aw < bx or ax > bx + bw or ay + ah < by or ay > by + bh)

    def find_non_overlapping_position(w, h):
        top_margin = int(screen_h * 0.12)
        bottom_margin = int(screen_h * 0.12)

        angle = 0
        radius = 0
        max_radius = screen_w  # or a large enough value to expand fully

        while radius < max_radius:
            x = int(cx + radius * math.cos(angle)) - w // 2
            y = int(cy + radius * math.sin(angle)) - h // 2

            # Clamp y to margins
            clamped_y = max(top_margin, min(y, screen_h - bottom_margin - h))

            # If clamping adjusted y, it means hit vertical boundary
            if clamped_y != y:
                y = clamped_y
                # Push x outward to avoid collapsing horizontally
                # Increase radius horizontally only, keep y fixed within margin
                # Calculate direction: +1 if cosine positive, -1 if negative
                horizontal_direction = 1 if math.cos(angle) >= 0 else -1
                # Push x farther out beyond current radius:
                x = int(cx + (radius + 20) * horizontal_direction) - w // 2

            pos = (x, y, w, h)

            if all(not boxes_overlap(pos, p) for p in tag_cloud_positions):
                tag_cloud_positions.append(pos)
                return x, y

            angle += 0.5
            radius += 4

        # fallback to center but respect margins vertically
        x = cx - w // 2
        y = max(top_margin, min(cy - h // 2, screen_h - bottom_margin - h))
        return x, y

    
    num_tags = min(num_tags, len(tag_cloud_tags))
    for i in range(num_tags):
        key = f"tag_{i}"
        if key in tag_overlay_boxes and tag_overlay_boxes[key].winfo_exists():
            continue

        tag = tag_cloud_tags[i]
        font_size = tag["font_size"]

        # Temporary window to get size
        temp = tk.Toplevel()
        temp.overrideredirect(True)
        temp.attributes("-alpha", 0.0)
        label = tk.Label(temp, text=tag["name"], font=("Arial", font_size, "bold"))
        label.pack()
        temp.update_idletasks()
        w, h = temp.winfo_width(), temp.winfo_height()
        temp.destroy()

        x, y = find_non_overlapping_position(w, h)

        box = tk.Toplevel()
        box.overrideredirect(True)
        box.attributes("-topmost", True)
        box.attributes("-alpha", 0.9)
        box.configure(bg=OVERLAY_BACKGROUND_COLOR)

        label = tk.Label(
            box, text=tag["name"],
            font=("Arial", font_size, "bold"),
            fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR
        )
        label.pack()
        box.geometry(f"+{x}+{y}")
        tag_overlay_boxes[key] = box

# =========================================
#          *EPISODE LIGHTNING ROUND
# =========================================

episode_overlay_boxes = {}  # Global storage for the overlay windows
light_episode_names = []  # Make sure to populate this elsewhere

def set_light_episodes():
    global light_episode_names
    data = currently_playing.get("data")
    episodes = data.get("episode_info", [])
    base_title = get_base_title().lower()
    title_words = set(re.findall(r'\w+', base_title))  # Break base title into words

    if not data or not episodes:
        light_episode_names = ["No Episodes Found"]
        return

    # Score how many title words appear in each episode name
    def score_overlap(ep_name):
        words = set(re.findall(r'\w+', ep_name.lower()))
        return len(title_words & words)

    # Replace title words in the episode name with underscores
    def mask_title_words(text):
        def replace_word(match):
            word = match.group()
            return "_" * len(word) if word.lower() in title_words else word
        return re.sub(r'\w+', replace_word, text)

    # Shuffle and prioritize episodes with lower overlap first
    scored_episodes = sorted(episodes, key=lambda ep: score_overlap(ep[1]))
    episode_names = [mask_title_words(ep[1]) for ep in scored_episodes]

    light_episode_names = episode_names

def toggle_episode_overlay(num_episodes=6, destroy=False):
    global episode_overlay_boxes, light_episode_names

    max_boxes = 6
    columns = 2
    rows = 3

    if destroy:
        for i in range(max_boxes):
            key = f"ep_{i}"
            box = episode_overlay_boxes.get(key)
            if box and box.winfo_exists():
                box.destroy()
        episode_overlay_boxes.clear()
        return

    # Get episode names to display
    num_episodes = min(num_episodes, len(light_episode_names))
    selected_episodes = light_episode_names[:num_episodes]

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    # Use 70% of screen area for the grid
    grid_w = round(screen_w * 0.7)
    grid_h = round(screen_h * 0.7)

    box_width = grid_w // columns
    box_height = grid_h // rows

    # Calculate top-left corner to center the whole grid
    grid_start_x = (screen_w - box_width * columns) // 2
    grid_start_y = (screen_h - box_height * rows) // 2

    for i in range(num_episodes):
        if f"ep_{i}" in episode_overlay_boxes and episode_overlay_boxes[f"ep_{i}"].winfo_exists():
            continue  # Don't re-create if already exists
        
        title = selected_episodes[i]
        row = i // columns
        col = i % columns

        x = grid_start_x + col * box_width
        y = grid_start_y + row * box_height

        box = tk.Toplevel()
        box.overrideredirect(True)
        box.attributes("-topmost", True)
        box.attributes("-alpha", 0.9)
        box.configure(bg=OVERLAY_BACKGROUND_COLOR, highlightbackground=OVERLAY_TEXT_COLOR, highlightthickness=4)
        font_size = scl(55)
        wrap = box_width - scl(40)
        # Try to find the largest font size that fits within 3 lines
        background = OVERLAY_BACKGROUND_COLOR
        if light_name_overlay:
            background = {"a":'#374151',"s":'#065F46',"m":'#1E3A8A'}.get(title[0], '#374151')
            title = title[1]
        while font_size >= scl(10):
            test_font = font.Font(family="Arial", size=font_size, weight="bold")
            line_count = get_wrapped_line_count(title, test_font, wrap-scl(10))
            if line_count <= 3:
                break
            font_size -= 1
        label = tk.Label(
            box,
            text=title,
            font=("Arial", font_size, "bold"),
            fg=OVERLAY_TEXT_COLOR,
            bg=background,
            wraplength=wrap,
            justify="center"
        )
        label.pack(expand=True, fill="both", padx=scl(10), pady=scl(10))

        box.geometry(f"{box_width - scl(20)}x{box_height - scl(20)}+{x}+{y}")
        episode_overlay_boxes[f"ep_{i}"] = box

def get_wrapped_line_count(text, font, wraplength):
    words = text.split()
    line = ''
    lines = []
    for word in words:
        test_line = f"{line} {word}".strip()
        if font.measure(test_line) <= wraplength:
            line = test_line
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return len(lines)

# =========================================
#          *NAMES LIGHTNING ROUND
# =========================================

light_name_overlay = False

def set_light_names():
    global light_episode_names
    data = currently_playing.get("data")

    if data and data.get("characters"):
        main = []
        secondary = []
        appear = []
        for character in data["characters"]:
            name = character[1]
            if character[0] == "m":
                main.append([character[0], name])
            elif character[0] == "s":
                secondary.append([character[0], name])
            elif character[0] == "a":
                appear.append([character[0], name])

        # Shuffle all groups
        random.shuffle(main)
        random.shuffle(secondary)
        random.shuffle(appear)

        used_names = set()
        result = []

        # Helper to add up to n characters from a group without duplicates
        def add_unique(group, n):
            added = 0
            for char in group:
                if char[1] not in used_names:
                    result.append(char)
                    used_names.add(char[1])
                    added += 1
                if added == n:
                    break
            return added

        # Attempt to add 3 appear, 2 secondary, 1 main
        needed = 6
        needed -= add_unique(appear, 3)
        needed -= add_unique(secondary, 2)
        needed -= add_unique(main, 1)

        # Fill any leftovers from all characters
        remaining = appear + secondary + main
        for char in remaining:
            if needed == 0:
                break
            if char[1] not in used_names:
                result.append(char)
                used_names.add(char[1])
                needed -= 1

        light_episode_names = result[:6]  # Ensure only 6 are kept

# =========================================
#          *CLIP/*TRAILER LIGHTNING ROUND
# =========================================
stream_instance = vlc.Instance(
    "--aout=directsound",
    "--video-on-top",
    "--no-xlib", 
    "-q", 
    "--fullscreen",
    "--vout=opengl"
)
ost_stream_instance = vlc.Instance(
    "--aout=directsound",
    "--no-xlib", 
    "-q",
    "--vout=opengl"
)
stream_player = stream_instance.media_player_new()
currently_streaming = None
last_streamed = ["","","",""]
_cached_streams = {}

def get_youtube_stream_url(youtube_url):
    try:
        if youtube_url in _cached_streams:
            return _cached_streams[youtube_url]

        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=False)
            stream_url = info_dict["url"]
            duration = info_dict.get("duration", 0)  # Duration in seconds

            _cached_streams[youtube_url] = (stream_url, duration)
            return stream_url, duration
    except:
        _cached_streams[youtube_url] = (None, 0)
        return None, 0

def stream_url(url, name, channel, new_player=True):
    global currently_streaming, last_streamed, preset_media, video_stopped, stream_player
    direct_stream, length = get_youtube_stream_url(url)
    if direct_stream:
        currently_streaming = [name, url, channel]
        last_streamed = [currently_playing.get("filename"), name, url, channel]
        media = stream_instance.media_new(direct_stream)
        media.parse_with_options(vlc.MediaParseFlag.local, timeout=5)
        if new_player:
            if light_mode == 'ost':
                stream_player = ost_stream_instance.media_player_new()
            else:
                stream_player = stream_instance.media_player_new()
            stream_player.set_media(media)
            stream_player.play()
            stream_player.set_fullscreen(False)
            stream_player.set_fullscreen(True)
        else:
            video_stopped = True
            if current_vout != "opengl":
                set_vout("opengl")
            time.sleep(2)
            player.set_media(media)
            player.play()
            player.set_fullscreen(False)
            player.set_fullscreen(True)
    else:
        currently_streaming = None
    return length

def stop_stream():
    global currently_streaming
    currently_streaming = None
    stream_player.stop()
    stream_player.set_media(None)  # Reset the media

def play_trailer(url=None):
    url = url or currently_playing.get("data", {}).get("trailer")
    if url:
        url = f"https://www.youtube.com/watch?v={url}"
        return stream_url(url, "Trailer", None, light_mode == 'clip')
    return 0

def get_stream_start_time(length):
    if last_streamed and last_streamed[3] and "Crunchyroll" in last_streamed[3]:
        start_buffer = 0
        end_buffer = 10
    elif last_streamed and last_streamed[3] and "Netflix" in last_streamed[3]:
        start_buffer = 0
        end_buffer = 25
    else:
        start_buffer = 5
        end_buffer = 5
    if length <= light_round_length + start_buffer + end_buffer:
        return 0  # Start early if the trailer is short
    max_start = int(length - light_round_length - end_buffer)
    return random.randint(start_buffer, max_start)

def play_random_clip(data=None, queue=False, ost=False):
    if currently_streaming and not data:
        stop_stream()
        return
    if not data:
        data = currently_playing.get("data")
    url, name, channel = load_random_clips(data, ost=ost)
    if url:
        if not queue:
            return stream_url(url, name, channel)
        return url, name, channel
    else:
        if not queue:
            return 0
        return None, None, None

def load_random_clips(data=None, limit_channels=False, ost=False):
    if not data:
        data = currently_playing.get("data")
    title = get_display_title(data)
    year = int(data.get("season", "9999")[-4:])
    if ost:
        url, name, channel = get_random_anime_clip_stream_url(title, year, data, limit_channels=False, ost=True)
    else:
        url, name, channel = get_random_anime_clip_stream_url(title, year, data, limit_channels=True)
        if not url and title != get_base_title(title=title):
            url, name, channel = get_random_anime_clip_stream_url(get_base_title(title=title), year, data, limit_channels=True)
        if not url and not limit_channels:
            url, name, channel = get_random_anime_clip_stream_url(title, year, data, limit_channels=False)
    if selected_extra_metadata == "links":
        update_extra_metadata(data)
    return url, name, channel

def stream_clip(video_id, name, channel):
    url = f"https://www.youtube.com/watch?v={video_id}"
    if currently_streaming and currently_streaming[1] == url:
        stop_stream()
    else:
        stream_url(url, name, channel, False)

YOUTUBE_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
YOUTUBE_VIDEO_DETAILS_URL = 'https://www.googleapis.com/youtube/v3/videos'
youtube_api_limited = False
youtube_api_limited_count = 0
_cached_clips = {}
_cached_ost_clips = {}
def get_random_anime_clip_stream_url(anime_title, year, data, limit_channels=True, ost=False):
    global youtube_api_limited, youtube_api_limited_count
    _cached_id = f"{anime_title}-{year}"
    if not ost and _cached_id in _cached_clips and (_cached_clips[_cached_id] or limit_channels):
        valid_video_ids = _cached_clips[_cached_id]
    elif ost and _cached_id in _cached_ost_clips:
        valid_video_ids = _cached_ost_clips[_cached_id]
    else:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        video_ids = None
        if limit_channels:
            query_extra = "crunchyroll"
        elif ost:
            query_extra = "anime ost"
        else:
            query_extra = "anime clip"
        if len(anime_title.split(" ")) == 1:
            query = f"{query_extra} {anime_title} {year}"
        else:
            query = f"{query_extra} {anime_title}"
        test_print(f"SEARCHING: '{query}'")
        try:
            search_response = youtube.search().list(
                q=query,
                part="id,snippet",
                type="video",
                order="relevance",
                relevanceLanguage="en",
                regionCode="US",
                maxResults=50
            ).execute()

            video_ids = [item["id"]["videoId"] for item in search_response["items"]]
            youtube_api_limited_count = 0
            test_print(len(video_ids))
        except:
            youtube_api_limited_count += 1
            if youtube_api_limited_count >= 3:
                youtube_api_limited = True
        if not video_ids:
            return None, None, None

        # Get details like duration
        details_response = youtube.videos().list(
            part="contentDetails,snippet,statistics",
            id=",".join(video_ids)
        ).execute()

        priority_video_ids = []
        valid_video_ids = []
        back_up_valid_videos = []
        for item in details_response["items"]:
            video_id = item["id"]
            duration = item["contentDetails"].get("duration", "0")
            title = item["snippet"]["title"]
            description = item["snippet"].get("description", "")
            channel_title = item["snippet"]["channelTitle"]
            
            try:
                # check aspect ratio
                thumb = (
                    item["snippet"]["thumbnails"].get("standard")
                    or item["snippet"]["thumbnails"].get("high")
                    or item["snippet"]["thumbnails"].get("medium")
                    or item["snippet"]["thumbnails"]["default"]
                )
                width = thumb.get("width")
                height = thumb.get("height")
                if width and height and width / height < 1:
                    test_print(f"[{video_id}]{title}: is short")
                    continue  # Likely a vertical video (Short)
                
                # check bad keywords
                bad_keywords = [
                    "summary", "explained", "opening", "ending", "shorts", "amv",
                    "[amv]", "trailer", "comparison", "musicvideo", "music video", 
                    "animate-it", "references", "extended", "review",
                    "meet the english voice of", "theme song", "cd single", "[sub indo]",
                    "you should be reading", "& update", "getting a season", "in-depth",
                    "full album", "full length", "explain in", "masterpiece", "unboxing",
                    "how to watch", "op1", "op2", "op3", "op4", "op5", "op6", "op7", "op8",
                    "op9", "ed1", "ed2", "ed3", "ed4", "ed5", "ed6", "ed7", "ed8", "ed9",
                    "ranting about", "1. ", "horrible season of", "was almost perfect",
                    "anime vs manga", "10 shocking ", "everyone skipped this anime",
                    " is wicked…", "unanswered questions", "needs to address", "tráiler",
                    "release date update", "is finally here", "fun facts", "badly explaining",
                    "this manga is", "trash taste", "gigguk", "mmv", "manga release", "lyrics", "lyric",
                    "reactions", "reaction", "underrated anime is back", "is finally returning",
                    "10 differences between", "overrated!?!", "manga and anime", "film theory:",
                    "the manga that", "the anime that", "anime similar to", "should you watch",
                    "best anime of", "best watch order", "manga is so much better than the anime",
                    "everything you need to know about", "seasons ranked", "#animeedit", "they need to remake",
                    "? watch these!", "must watch", "anime you should", "anime you must", "anime you need",
                    "anime you have to", "anime you gotta", "veggietales", "reacting to", "the anime effect #",
                    "#animeexplain", "top 10", "why you should watch ", "simulcast sampler", "anime haul", "anime unboxing",
                    "anime mix", "english dub greeting video", "best of 20"
                ]
                ost_bad_keywords = [
                    "insert song"
                ]
                game_bad_keywords = [
                    "gameplay", "let's play", "walkthrough", "opening cinematic", "game trailer"
                ]
                if not is_game(data):
                    bad_keywords += game_bad_keywords
                if not ost:
                    bad_keywords += ost_bad_keywords
                else:
                    bad_keywords += ["#"]

                # Filter out any bad keywords that appear in the anime title
                filtered_keywords = [kw for kw in bad_keywords if kw not in f"{anime_title.lower()} {data.get("title").lower()}"]
                # Now check if any of the remaining bad keywords are in the video title
                if any(kw in title.lower() for kw in filtered_keywords):
                    test_print(f"[{video_id}]{title}:  bad keyword")
                    continue

                # Whole words to filter (like "op" or "ed")
                whole_word_keywords = {"op", "ed", "recap", "amv"}
                ost_whole_word_keywords = {"ost"}
                if not ost:
                    whole_word_keywords |= ost_whole_word_keywords
                def contains_whole_word(title, keywords):
                    pattern = r'\b(?:' + '|'.join(re.escape(word) for word in keywords) + r')\b'
                    return re.search(pattern, title.lower()) is not None
                if not (contains_whole_word(anime_title.lower(), whole_word_keywords) or contains_whole_word(data.get("title").lower(), whole_word_keywords)) and contains_whole_word(title, whole_word_keywords):
                    test_print(f"[{video_id}]{title}:  has a whole-word keyword")
                    continue
                
                # check if movie
                if "movie" not in anime_title.lower() and "movie" in title.lower() and not data.get("type") == "Movie":
                    test_print(f"[{video_id}]{title}:  movie in title when not movie")
                    continue
                
                #check description
                bad_description_phrases = [" amv ", " amv."]
                if any(phrase in description.lower() for phrase in bad_description_phrases):
                    test_print(f"[{video_id}]{title}:  bad phrase in description")
                    continue

                # check title match
                title_okay = False
                check_description = True
                different_title_phrases = [
                    "from the creators of", "from the makers of", "by the creators of", "all it took was", "from the studio that brought you"
                ]
                
                title_to_check = title
                if channel_title in ["Crunchyroll"]:
                    if "|" in title:
                        title_to_check = title.split("|")[1].strip()
                    check_description = False
                elif any(phrase in description.lower() for phrase in different_title_phrases):
                    check_description = False
                for t in [anime_title, data.get("title"), get_base_title(title=anime_title), get_base_title(title=data.get("title"))]:
                    t_edits = [t]
                    # Only use the split-at-colon result if it's not too short or trivial
                    colon_split = t.split(": ")[0]
                    if colon_split != t and len(colon_split.strip()) >= 3:
                        t_edits.append(colon_split)
                    t_edits.extend([t.replace(" ", ""), t.replace(".", ""), t.replace("-", " ")])
                    for t_edit in t_edits:
                        if title_match_score(t_edit, title_to_check) or (check_description and title_match_score(t_edit, description)):
                            title_okay = True
                            break
                    if title_okay:
                        break
                if not title_okay:
                    test_print(f"[{video_id}]{title}: title doesn't match enough")
                    continue  # skip this result
                
                if ost:
                    # check if ost match
                    is_ost = False
                    for t in ["OST", "Soundtrack", "Insert Song"]:
                        if title_match_score(t, title) or title_match_score(t, description):
                            is_ost = True
                            break
                    if not is_ost:
                        test_print(f"[{video_id}]{title}: is not ost")
                        continue  # skip this result

                # check channel
                blacklisted_channels = [
                    "Reacts", "AniRecaps", "Anime Recap", "Anime Summary", "Plot Recap", "Explains", "Crunchyroll Brasil", 
                    "Explained", "Mother's Basement", "Crunchyroll: Inside Anime", "Crunchyroll TV", "It's Certified Otaku Vibes",
                    "Crunchyroll en Español", "Crunchyroll FR", "Crunchyroll India", "Crunchyroll DE", "WatchMojo", "Watch Mojo",
                    "AnimeVersa", "Crunchyroll en Español", "Netflix Jr.", "MWAMVEVO", "Tarkeus", "Gigguk", "ryuuarm", "Jent Watches"
                    "IGN Anime Club", "Albert Senpai", "AnimeSekaiStore", "ForgottenRelics", "Anuj Lama"
                ]
                ost_blacklisted_channels = [
                    " - Topic"
                ]
                if not ost:
                    blacklisted_channels += ost_blacklisted_channels
                if any(blacklist in channel_title for blacklist in blacklisted_channels):
                    test_print(f"[{video_id}]{title}: bad channel")
                    continue

                # check views
                views = int(item["statistics"].get("viewCount", 0))
                if views < 500:
                    test_print(f"[{video_id}]{title}: too few views")
                    continue  # Too obscure or low-quality
                seconds = parse_iso8601_duration(duration)
                priority_channels = ["Crunchyroll", "Crunchyroll Dubs", "Netflix Anime"]
                video_data = [title, video_id, channel_title]
                if seconds >= 60 and any(priority == channel_title for priority in priority_channels):
                    less_priority_words = ["Teaser PV", "Now Available"]
                    if any(word in title for word in less_priority_words):
                        valid_video_ids.append(video_data)
                    else:
                        priority_video_ids.append(video_data)
                    continue
                elif limit_channels:
                    continue
                elif seconds > 60:
                    valid_video_ids.append(video_data)
                elif seconds >= 20:
                    back_up_valid_videos.append(video_data)
                else:
                    test_print(f"[{video_id}]{title}: too short")
            except Exception as e:
                test_print(f"error{e}")
                continue
        if not ost:
            valid_video_ids = priority_video_ids or valid_video_ids or back_up_valid_videos
        test_print(valid_video_ids)
        if not valid_video_ids:
            if ost:
                _cached_ost_clips[_cached_id] = None
            else:
                _cached_clips[_cached_id] = None
            return None, None, None
        else:
            if ost:
                _cached_ost_clips[_cached_id] = valid_video_ids
            else:
                _cached_clips[_cached_id] = valid_video_ids
    if valid_video_ids:
        if limit_channels:
            selected_title, selected_video_id, selected_channel = random.choice(valid_video_ids)
        else:
            selected_title, selected_video_id, selected_channel = random.choice(valid_video_ids[:5])
        video_url = f"https://www.youtube.com/watch?v={selected_video_id}"
        return video_url, selected_title, selected_channel
    else:
        return None, None, None
    
def title_match_score(anime_title, video_title):
    GENERIC_WORDS = {
        "the", "a", "an", "of", "and", "in", "to", "for", "with", "on",
        "season", "part", "new", "as"
    }
    def clean_words(text, exclude_generic=True):
        words = [
            word.strip("|『[]×.,!?:;\"'").lower()
            for word in text.lower().split()
        ]
        if exclude_generic:
            words = [w for w in words if w not in GENERIC_WORDS]
        return words

    anime_words = clean_words(anime_title, True)
    anime_words_count = clean_words(anime_title)
    video_words = clean_words(video_title, True)

    # Filter case: Video title contains "from the director of <Anime Title>" which refers to a DIFFERENT work.
    # We should not treat that as a match if the ONLY occurrence of the anime title is inside that phrase.
    # Strategy: detect the phrase, then check if anime title tokens appear elsewhere outside the phrase.
    lowered_full = video_title.lower()
    phrase_key = "from the director of"
    if phrase_key in lowered_full:
        # Build regex to capture the portion after the phrase up to common separators
        # (dash, pipe, colon, parentheses start, end of string)
        # Example: "From the director of Attack on Titan | New Sci-Fi Original" -> captures "Attack on Titan"
        # Escape anime title for presence test, but we'll instead tokenize to be robust.
        # Identify spans of the phrase + following chunk (max 8 words) for scanning tokens.
        pattern = re.compile(r"from the director of\s+([^-|:()]+)", re.IGNORECASE)
        spans = []
        for m in pattern.finditer(video_title):
            span_words = clean_words(m.group(1), False)
            spans.append((m.span(1), span_words))
        if spans:
            # Count total appearances of anime words in entire title
            video_all_tokens_no_generic = clean_words(video_title, True)
            anime_set = set(anime_words)
            # Check if every anime word occurrence lies wholly within one of the captured spans
            # Build a map of indices of tokens in spans
            # Simpler: reconstruct tokens sequence with indices to see if anime words appear outside any span.
            tokens_full = [w.strip("|『[]×.,!?:;\"'").lower() for w in video_title.lower().split()]
            # Build char index for each token to test if within a span; approximate via running position.
            # For simplicity: check raw substring presence outside phrase first.
            outside_text = lowered_full
            for sspan, _w in spans:
                start, end = sspan
                outside_text = outside_text[:start].replace(anime_title.lower(), "") + outside_text[end:].replace(anime_title.lower(), "")
            # If after removing span regions the anime title (as a contiguous substring ignoring case) no longer appears,
            # and all anime words appear inside one span, treat as non-match.
            anime_inline = anime_title.lower()
            appears_outside = anime_inline in outside_text
            # Also ensure the span actually contains all required anime words (order-insensitive) to avoid false negatives.
            span_contains_all = any(anime_set.issubset(set(words)) for _, words in spans)
            if span_contains_all and not appears_outside:
                return False

    # Try to match all anime title words in order in the video title
    i = 0
    if len(anime_words_count) < 3:
        min_match = len(anime_words_count)
    else:
        min_match = min(5, max(1, len(anime_words_count) // 2 + len(anime_words_count) % 2))
    for word in video_words:
        if word == anime_words[i]:
            i += 1
            if i == min_match:
                return True
        else:
            i = 0
    return False

def parse_iso8601_duration(duration):
    match = re.match(r'PT(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return 0
    minutes = int(match.group(1)) if match.group(1) else 0
    seconds = int(match.group(2)) if match.group(2) else 0
    return minutes * 60 + seconds

test_printing = False
def test_print(text):
    if test_printing:
        print(text)

edge_overlay = None
def toggle_outer_edge_overlay(destroy=False, pixels=65, color="black"):
    global edge_overlay

    if destroy:
        if edge_overlay:
            edge_overlay.destroy()
            edge_overlay = None
        return

    if edge_overlay:
        edge_overlay.lift()
        edge_overlay.attributes("-topmost", True)
        return

    # Create the overlay window
    edge_overlay = tk.Toplevel()
    edge_overlay.overrideredirect(True)
    edge_overlay.attributes("-topmost", True)

    screen_width = edge_overlay.winfo_screenwidth()
    screen_height = edge_overlay.winfo_screenheight()
    edge_overlay.geometry(f"{screen_width}x{pixels}+0+{screen_height - pixels}")

    # Background frame (bottom only)
    frame = tk.Frame(edge_overlay, bg=color)
    frame.pack(fill="both", expand=True)

# =========================================
#          *OST LIGHTNING ROUND
# =========================================

def extract_track_name_from_youtube_title(youtube_title, data):
    """
    Extracts the likely track name from a YouTube title by removing all words from the anime's Japanese and English titles and common separators.
    """
    if not youtube_title:
        return ""
    # Get possible anime titles
    titles = [data.get("title", ""), data.get("eng_title", "")]
    # Remove each word from both titles (case-insensitive)
    for anime_title in titles:
        if anime_title:
            for word in anime_title.split():
                # Remove word surrounded by word boundaries (case-insensitive)
                youtube_title = re.sub(rf"\b{re.escape(word)}\b", "", youtube_title, flags=re.IGNORECASE)
    # Remove common separators
    for sep in ["OST", "-", "—", "|", "(", ")", "[", "]", "Official", "Theme", "Soundtrack"]:
        youtube_title = youtube_title.replace(sep, "")
    # Remove extra spaces
    track_name = youtube_title.strip()
    # Remove multiple spaces
    track_name = re.sub(r"\s+", " ", track_name)
    # Try to filter out generic words if multiple parts
    parts = [p.strip() for p in track_name.split() if p.strip()]
    GENERIC_WORDS = {"ost", "official", "theme", "soundtrack"}
    filtered = [p for p in parts if p.lower() not in GENERIC_WORDS]
    if filtered:
        track_name = " ".join(filtered)
    return track_name

# =========================================
#          *LIGHTNING ROUND OVERLAYS
# =========================================

def set_countdown(value=None, position="top right", inverse=False):
    """Creates, updates, or removes the countdown overlay in a separate always-on-top window with a semi-transparent background."""
    if inverted_positions:
        position = "top left"
    set_floating_text("Countdown", value, position=position, inverse=inverse)

def set_light_round_number(value=None, inverse=False):
    size = 80
    if value:
        if len(value) >= 5:
            size = 48
        elif len(value) >= 4:
            size = 62
    set_floating_text("Lightning Round Number", value, position="bottom right", size=size, inverse=inverse)

def set_frame_number(value=None, inverse=False):
    set_floating_text("Frame Number", value, position="bottom center", inverse=inverse)

def top_info(value=None, size=80, width_max=0.7, inverse=False):
    set_floating_text("Top Info", value, position="top center", size=size, width_max=width_max, inverse=inverse)

floating_windows = {}  # Dictionary to store windows and labels

def set_floating_text(name, value, position="top right", size=80, width_max=0.7, inverse=False):
    """
    Creates, updates, or removes a floating overlay window with text.

    Args:
        name (str): A unique identifier for the floating window (e.g., "countdown", "light_round").
        value (str or int): The text to display. If None or '0', the window is removed.
        position (str): Where to place the window (e.g., "top left", "bottom center", "middle right").
    """
    global floating_windows
    size = scl(size)
    # Remove window if value is '0' or negative
    if value is None or isinstance(value, str) and value == '0' or isinstance(value, int) and value < 0:
        if name in floating_windows:
            floating_windows[name]["window"].destroy()
            del floating_windows[name]
        return

    if inverse:
        back_color = INVERSE_OVERLAY_BACKGROUND_COLOR
        front_color = INVERSE_OVERLAY_TEXT_COLOR
    else:
        back_color = OVERLAY_BACKGROUND_COLOR
        front_color = OVERLAY_TEXT_COLOR

    # Create the window if it doesn't exist
    if name not in floating_windows:
        window = tk.Toplevel()
        window.title(name)
        window.overrideredirect(True)  # Remove window borders
        window.attributes("-topmost", True)  # Keep it on top
        window.wm_attributes("-alpha", 0.7)  # Semi-transparent background
        window.configure(bg=back_color)

        label = tk.Label(window, font=("Arial", size, "bold"), fg=front_color, bg=back_color)
        label.pack(padx=20, pady=10)

        floating_windows[name] = {"window": window, "label": label}

        # Temporarily place at (0,0) before positioning update
        window.geometry("+0+0")
    
    else:
        window = floating_windows[name]["window"]
        label = floating_windows[name]["label"]

    # Resize font if it's too wide for the screen
    screen_width = window.winfo_screenwidth()
    max_width = int(screen_width * width_max)

    current_size = size
    test_font = font.Font(family="Arial", size=current_size, weight="bold")
    while test_font.measure(str(value)) + 40 > max_width and current_size > 10:
        current_size -= 1
        test_font.configure(size=current_size)

    # Update the label text
    window.config(bg=back_color)
    label.config(text=str(value), font=test_font, fg=front_color, bg=back_color)

    # Function to set position after Tkinter updates
    def update_position():
        window.update_idletasks()  # Ensure correct window size
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        window_width = window.winfo_reqwidth()
        window_height = window.winfo_reqheight()

        positions = {
            "top left": (20, 20),
            "top center": ((screen_width - window_width) // 2, 20),
            "top right": (screen_width - window_width - 20, 20),
            "middle left": (20, (screen_height - window_height) // 2),
            "center": ((screen_width - window_width) // 2, (screen_height - window_height) // 2),
            "middle right": (screen_width - window_width - 20, (screen_height - window_height) // 2),
            "bottom left": (20, screen_height - window_height - 20),
            "bottom center": ((screen_width - window_width) // 2, screen_height - window_height - 20),
            "bottom right": (screen_width - window_width - 20, screen_height - window_height - 20),
        }

        x, y = positions.get(position, positions["top right"])
        window.update_idletasks()
        window.geometry(f"+{x}+{y}")
        window.update_idletasks()
        window.geometry(f"+{x}+{y}")
        window.lift()  # Bring to front

    # Ensure window is correctly positioned **after** all updates
    update_position()

progress_overlay = None
light_progress_bar = None
music_icon_label = None
pulse_step = 0
progress_bar_ready = False  # Tracks when progress bar is fully initialized

def set_progress_overlay(current_time=None, total_length=None, destroy=False):
    global progress_overlay, light_progress_bar, music_icon_label, progress_bar_ready

    if destroy:
        if progress_overlay is not None:
            screen_width = progress_overlay.winfo_screenwidth()
            screen_height = progress_overlay.winfo_screenheight()
            window_height = round((screen_height / 15) * 6)
            animate_window(progress_overlay, screen_width, (screen_height - window_height) // 2,
                           steps=20, delay=5, bounce=False, fade=None, destroy=True)
        progress_overlay = None
        light_progress_bar = None
        music_icon_label = None
        progress_bar_ready = False
        return

    if progress_overlay is None:
        progress_overlay = tk.Toplevel(root)
        progress_overlay.title("Blind Progress Bar")
        progress_overlay.overrideredirect(True)
        progress_overlay.attributes("-topmost", True)
        progress_overlay.attributes("-alpha", 0.8)
        progress_overlay.configure(bg=OVERLAY_BACKGROUND_COLOR)

        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        width, height = round(screen_width * 0.7), round(screen_height * 0.5)
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2

        # Initially place off-screen
        progress_overlay.geometry(f"{width}x{height}+{-screen_width}+{y}")
        progress_overlay.update_idletasks()

        # Style configuration
        style = ttk.Style(root)
        style.theme_use('default')
        style.configure("Horizontal.TProgressbar",
                        thickness=round(screen_height / 15),
                        background=generate_random_color(0, 200),
                        bordercolor='black',
                        borderwidth=10,
                        relief="solid")

        light_progress_bar = ttk.Progressbar(progress_overlay, orient="horizontal", mode="determinate",
                                             length=round(screen_width * 0.6))
        light_progress_bar.place(relx=0.5, rely=0.7, anchor="center")

        # Music icon
        if light_mode == 'ost':
            music_icon = "🎼"
        else:
            music_icon = "🎵"
        music_icon_label = tk.Label(progress_overlay, text=music_icon, font=("Segoe UI Emoji", scl(100)),
                                    bg=OVERLAY_BACKGROUND_COLOR, fg=generate_random_color(100, 255))

        music_icon_label.place(x=0, rely=0.35, anchor="center")  # Temporarily place far left

        def pulsate_music_icon_worker():
            pulsate_music_icon(music_icon_label)
        threading.Thread(target=pulsate_music_icon_worker, daemon=True).start()
        # pulsate_music_icon(music_icon_label)

        # Animate to center, then mark ready and move icon
        def finish_animation():
            nonlocal current_time, total_length
            progress_overlay.update_idletasks()
            move_music_icon(current_time, total_length)
            global progress_bar_ready
            progress_bar_ready = True

        animate_window(progress_overlay, x, y, steps=20, delay=5, bounce=False, fade=None,
                       callback=finish_animation)

    elif current_time is not None and total_length is not None:
        # Wait until layout is complete
        if progress_bar_ready:
            move_music_icon(current_time, total_length)
        light_progress_bar["maximum"] = total_length
        light_progress_bar["value"] = current_time
        progress_overlay.wm_attributes("-topmost", True)

def pulsate_music_icon(label):
    global pulse_step

    # Retry until the label exists
    if not label.winfo_exists():
        return  # Stop if truly gone

    if not label.winfo_ismapped():
        root.after(100, pulsate_music_icon, label)  # Wait and retry
        return

    if not player.is_playing():
        root.after(500, pulsate_music_icon, label)  # Check again later if paused
        return

    base_size = scl(160)
    max_size = scl(200)
    speed = 0.5

    pulse_step += speed
    new_size = int(base_size + (math.sin(pulse_step) * (max_size - base_size) / 2))
    label.config(font=("Arial", new_size))

    root.after(50, pulsate_music_icon, label)

def move_music_icon(current_time, total_length):
    if music_icon_label is None or light_progress_bar is None:
        return

    progress_overlay.update_idletasks()

    progress_bar_x = light_progress_bar.winfo_x()
    progress_bar_width = light_progress_bar.winfo_width()
    if progress_bar_width <= 1:
        return  # Avoid division by zero or incomplete layout

    icon_width = scl(40)  # Estimated width

    if total_length > 0:
        progress_ratio = min(max(current_time / total_length, 0), 1)
        new_x = progress_bar_x + (progress_ratio * (progress_bar_width - icon_width))
        music_icon_label.place(x=new_x, rely=0.35, anchor="center")

def generate_random_color(min = 0, max = 255):
    # Generate random values for red, green, and blue
    red = random.randint(min, max)
    green = random.randint(min, max)
    blue = random.randint(min, max)

    # Format the color as a hexadecimal string
    color = f"#{red:02x}{green:02x}{blue:02x}"
    return color

# =========================================
#            *MUSIC
# =========================================

pygame.mixer.init()
music_files = []  # List to store music files
current_music_index = 0
music_loaded = False
music_changed = False
valid_music_ext = (".mp3", ".wav", ".ogg")

def load_music_files():
    """Load all music files from the "music" folder"""
    global music_files, current_music_index
    music_folder = "music"
    if os.path.exists(music_folder):
        music_files = [os.path.join(music_folder, f) for f in os.listdir(music_folder) if f.endswith(valid_music_ext)]
        random.shuffle(music_files)  # Randomize playlist
        current_music_index = 0  # Start at the first track

def next_background_track():
    global current_music_index, music_changed
    if music_files:
        # Get background track history for current playlist
        track_history = playlist.get("background_track_history", [])
        total_tracks = len(music_files)
        
        # Calculate how many tracks to avoid (half of total tracks)
        avoid_count = total_tracks // 2
        
        # Get list of recently used tracks to avoid
        recent_tracks = track_history[-avoid_count:] if avoid_count > 0 else []
        
        # Find next available track that hasn't been used recently
        attempts = 0
        original_index = current_music_index
        
        while attempts < total_tracks:
            current_music_index = (current_music_index + 1) % total_tracks
            current_track_path = music_files[current_music_index]
            current_track_basename = os.path.basename(current_track_path)
            
            # If this track is not in recent history, use it
            if current_track_basename not in recent_tracks:
                break
            
            attempts += 1
        
        # If all tracks are in recent history, just use the next one
        if attempts >= total_tracks:
            current_music_index = (original_index + 1) % total_tracks
        
        music_changed = True

checked_music_folder = False
def play_background_music(toggle):
    """Function to play or pause background music"""
    global music_loaded, current_music_index, music_changed, checked_music_folder

    if not music_files:  # Ensure music is loaded
        load_music_files()
    
    if not music_files:  # If still empty, return
        if not checked_music_folder:
            print("No music files found in 'music' folder.")
            checked_music_folder = True
        return

    if music_loaded and not music_changed:
        if toggle and not disable_video_audio:
            pygame.mixer.music.unpause()
            now_playing_background_music(music_files[current_music_index])
        else:
            pygame.mixer.music.pause()
            now_playing_background_music()
    else:
        if toggle:
            music_loaded = True
            pygame.mixer.music.load(music_files[current_music_index])
            pygame.mixer.music.play(-1)  # -1 loops indefinitely
            if disable_video_audio:
                pygame.mixer.music.set_volume(0)
            else:
                pygame.mixer.music.set_volume(0.15*(volume_level/100))  # Adjust volume
            music_changed = False
            # Record track usage only when actually played
            record_background_track_usage(music_files[current_music_index])
            now_playing_background_music(music_files[current_music_index])

def record_background_track_usage(track_path):
    """Record the usage of a background track in the current playlist's history"""
    if not track_path:
        return
    
    # Ensure background_track_history exists in playlist
    if "background_track_history" not in playlist:
        playlist["background_track_history"] = []
    
    # Add track to history (avoid duplicates) - store only basename
    track_basename = os.path.basename(track_path)
    if not playlist["background_track_history"] or playlist["background_track_history"][-1] != track_basename:
        playlist["background_track_history"].append(track_basename)
    
    # Keep history manageable - limit to total number of tracks available
    # This ensures we can always find non-recent tracks when we have enough variety
    max_history = len(music_files) if music_files else 50
    if len(playlist["background_track_history"]) > max_history:
        playlist["background_track_history"] = playlist["background_track_history"][-max_history:]

def now_playing_background_music(track = None):
    if not frame_light_round_started and (light_mode == 'peek' or not light_muted or peek_overlay1 or edge_overlay_box or grow_overlay_boxes):
        track = None
    if track:
        basename = os.path.basename(track)
        for ext in valid_music_ext:
            basename = basename.replace(ext, "")
        track = "BGM: " + basename
    set_floating_text("Now Playing Background Music", track, position="bottom left", size=14, inverse=character_round_answer)

# =========================================
#            *INFORMATION POPUP
# =========================================

def toggle_info_popup():
    toggle_title_popup(not is_title_window_up() or title_info_only)

def toggle_title_info_popup():
    toggle_title_popup(not is_title_window_up(), title_only=True)

def animate_window(window, target_x, target_y, steps=20, delay=5, bounce=True, fade="in", destroy=False, callback=None):
    """Smoothly moves a Tkinter window to a new position with optional bounce, fade effects, and a completion callback."""
    if not window:
        return

    start_x = window.winfo_x()
    start_y = window.winfo_y()

    delta_x = (target_x - start_x) / steps
    delta_y = (target_y - start_y) / steps

    original_alpha = 0.8  # Default transparency
    if fade == "in":
        window.attributes("-alpha", 0)  # Start fully transparent

    def step(i=0):
        if i <= steps and window:
            bounce_strength = math.sin((i / steps) * math.pi) * 5 if bounce and i > steps * 0.7 else 0

            new_x = int(start_x + delta_x * i + bounce_strength)
            new_y = int(start_y + delta_y * i + bounce_strength)
            window.geometry(f"+{new_x}+{new_y}")

            if fade == "in":
                alpha = min(original_alpha, (i / steps) * original_alpha)
                window.attributes("-alpha", alpha)
            elif fade == "out":
                alpha = max(0, ((steps - i) / steps) * original_alpha)
                window.attributes("-alpha", alpha)

            if i < steps:
                window.after(delay, lambda: step(i + 1))
            elif destroy and window:
                window.destroy()
                if callback:
                    callback()
            else:
                # Final geometry and callback after a short delay
                window.after(delay * 2, lambda: (
                    window.geometry(f"+{new_x}+{new_y}"),
                    callback() if callback else None
                ))
    step()

title_window = None  # Store the title popup window
title_row_label = None
top_row_label = None
bottom_row_label = None

def adjust_font_size(label, max_width, base_size=scl(50), min_size=scl(20)):
    """Adjusts the font size dynamically to fit within max_width."""
    font_size = base_size
    label.config(font=("Arial", font_size, "bold"))
    
    label.update_idletasks()  # Ensure geometry updates
    while label.winfo_reqwidth() > max_width and font_size > min_size:
        font_size -= 2
        label.config(font=("Arial", font_size, "bold"))
    return font_size

def is_title_window_up():
    return not (title_window is None or title_window.attributes("-alpha") == 0)

title_info_only = False
def toggle_title_popup(show, title_only=False):
    """Creates or destroys the title popup at the bottom middle of the screen."""
    global title_window, title_row_label, top_row_label, bottom_row_label, info_button, light_mode, title_info_only, pre_censor
    title_info_only = title_only
    if not is_title_window_up() and not show:
        title_info_only = False
        return
    if title_window:
        screen_width = title_window.winfo_screenwidth()
        screen_height = title_window.winfo_screenheight()
        window_width = title_window.winfo_reqwidth()
        window_height = title_window.winfo_reqheight()
        if not show:
            title_info_only = False
            animate_window(title_window, (screen_width - window_width) // 2, screen_height, fade="out")
    if title_only:
        button_seleted(info_button, False)
        button_seleted(title_info_button, show)
    else: 
        button_seleted(info_button, show and not light_mode)
        button_seleted(title_info_button, False)

    if not show:
        return

    if guessing_extra:
        guess_extra(guessing_extra)

    if black_overlay:
        blind()
    pre_censor = False
    if (peek_overlay1 or edge_overlay_box or grow_overlay_boxes):
        toggle_peek()

    if not title_window:
        title_window = tk.Toplevel()
        title_window.title("Anime Info")
        title_window.overrideredirect(True)  
        title_window.attributes("-topmost", True)  
        title_window.wm_attributes("-alpha", 0.8)  
        title_window.configure(bg="black")

    top_row = ""
    title_row = ""
    bottom_row = ""
    bg_color = OVERLAY_BACKGROUND_COLOR
    fg_color = OVERLAY_TEXT_COLOR
    top_font = ("Arial", scl(20), "bold")
    title_font = ("Arial", scl(50), "bold")
    bottom_font = ("Arial", scl(15), "bold")
    data = currently_playing.get("data")
    if data:
        if currently_playing.get("type") == "youtube":
            title = get_youtube_display_title(data)
            full_title = data.get("title")
            if full_title == title:
                full_title = ""
            else:
                full_title = full_title + "\n"
            uploaded = f"{datetime.strptime(data.get("upload_date"), "%Y%m%d").strftime("%Y-%m-%d")}"
            views = f"{data.get("view_count"):,}"
            likes = f"{data.get("like_count"):,}"
            channel = data.get("name")
            subscribers = f"{data.get("subscriber_count"):,}"
            duration = str(format_seconds(get_youtube_duration(data))) + " mins"
            fg_color = INVERSE_OVERLAY_TEXT_COLOR
            bg_color = INVERSE_OVERLAY_BACKGROUND_COLOR

            top_row = f"Uploaded by {channel} ({subscribers} subscribers)"
            title_row = title
            bottom_row = f"{full_title}Views: {views} | Likes: {likes} | {uploaded} | {duration}"
        else:
            japanese_title = data.get("title")
            title = data.get("eng_title") or japanese_title or (data.get("synonyms", [None]) or [None])[0]
            theme = format_slug(data.get("slug"))
            version_num = data.get("version")
            if version_num and version_num != 1:
                version_num = f"v{version_num}"
            else:
                version_num = ""
            if check_favorited(currently_playing.get("filename", "")):
                marks = "❤"
            else:
                marks = ""
            song = get_song_string(data)
            if is_game(data):
                aired = data.get("release")
                bg_color = "Dark Red"
                fg_color = "white"
            else:
                aired = data.get("season")
            studio = ", ".join(data.get("studios"))
            tags = get_tags_string(data)
            type = data.get("type")
            source = data.get("source")
            if data.get("platforms"):
                episodes = ", ".join(data.get("platforms"))
                if data.get("reviews"):
                    members = f"Reviews: {(data.get("reviews", 0) or 0):,}"
                else:
                    members = ""
                if data.get("score"):
                    score = f"Score: {data.get("score")}"
                else:
                    score = ""
            else:
                episodes =  data.get("episodes")
                if not episodes:
                    episodes = "Airing"
                else:
                    episodes = str(episodes) + " Episodes"
                members = f"Members: {data.get("members") or 0:,} (#{data.get("popularity") or "N/A"})"
                score = f"Score: {data.get("score")} (#{data.get("rank")})"
            if not title_only:
                title_row = title
                top_row = f"{marks}{theme}{version_num}{overall_theme_num_display(currently_playing.get("filename"))} | {song} | {aired}"
                middle_row_string = f"{score} | {japanese_title} | {members}\n"
                if not score and not members:
                    if japanese_title != title:
                        middle_row_string = f"{japanese_title}\n"
                    else:
                        middle_row_string = ""
                bottom_row = f"{middle_row_string}{studio} | {tags} | {episodes} | {type} | {source}"
            else:
                title_row = get_base_title()
                japanese_title = get_base_title(title=japanese_title)
                if title_top_info_txt:
                    top_row = title_top_info_txt
                else:
                    top_font = ("Arial", 1)
                if japanese_title != title:
                    bottom_row = f"{japanese_title}"
                else:
                    bottom_font = ("Arial", 1)
    else:
        top_font = ("Arial", 1)
        bottom_font = ("Arial", 1)
        title_row = currently_playing.get("filename", "No Media Playing").split(".")[0]

    title_window.configure(bg=bg_color)
    if title_row_label:
        title_row_label.config(text=title_row, font=title_font, fg=fg_color, bg=bg_color)
        top_row_label.config(text=top_row, font=top_font, fg=fg_color, bg=bg_color)
        bottom_row_label.config(text=bottom_row, font = bottom_font, fg=fg_color, bg=bg_color)
    else:
        top_row_label = tk.Label(title_window, text=top_row,
                                font=top_font, fg=fg_color, bg=bg_color)
        top_row_label.pack(pady=(scl(10), 0), padx = scl(10))

        # Title Label (Large Text)
        title_row_label = tk.Label(title_window, text=title_row, font=title_font, fg=fg_color, bg=bg_color)
        title_row_label.pack(pady=(0, 0), padx = scl(10))

        bottom_row_label = tk.Label(title_window, text=bottom_row,
                                font=bottom_font, fg=fg_color, bg=bg_color)
        bottom_row_label.pack(pady=(0, scl(10)), padx = scl(10))

    # Dynamically adjust font size to fit window width
    title_window.update_idletasks()
    max_width = title_window.winfo_screenwidth() - scl(550)  # Leave padding
    adjust_font_size(title_row_label, max_width)
    
    # Position at the bottom center of the screen
    title_window.update_idletasks()  # Ensure correct size update
    screen_width = title_window.winfo_screenwidth()
    screen_height = title_window.winfo_screenheight()
    window_width = title_window.winfo_reqwidth()
    window_height = title_window.winfo_reqheight()
    title_window.geometry(f"+{(screen_width - window_width) // 2}+{screen_height}")  # Adjust for bottom spacing
    root.after(1, lambda: animate_window(title_window, (screen_width - window_width) // 2, screen_height - window_height - scl(20)))

def get_tags_string(data):
    return ", ".join(get_tags(data))

def get_tags(data):
    tags = []
    for c in ['genres', 'themes','demographics']:
        if data.get(c):
            tags = tags + data.get(c)
    return tags

def get_song_string(data, type=None, totals=False, artist_limit=3):
    for theme in data.get("songs", []):
        if theme.get("slug") == data.get("slug"):
            if type:
                if type == "artist":
                    return get_artists_string(theme.get("artist"), total=totals, limit=artist_limit)
                else:
                    return theme.get(type)
            else:
                return (theme.get("title", "N/A") or "N/A") + " by " + get_artists_string(theme.get("artist"), total=totals, limit=artist_limit)
    return ""

def prompt_title_top_info_text(event=None):
    global title_top_info_txt
    result = simpledialog.askstring("Title Top Info Text", "Enter text that will appear above the title only info popup:", initialvalue=title_top_info_txt)
    if result is not None:
        title_top_info_txt = result
        save_config()    

# =========================================
#         *BONUS QUESTIONS
# =========================================

guessing_extra = None
showing_bonus_answer = False
bonus_points = ['1 PT', '2 PTs', '2 PTs']
def guess_extra(extra = None):
    global guessing_extra, showing_bonus_answer, bonus_chars, bonus_correct_indices
    buttons = [guess_year_button, guess_members_button, guess_score_button, guess_tags_button, 
               guess_multiple_button, guess_characters_button, guess_popularity_button,
               guess_studio_button, guess_artist_button, guess_song_button]
    for b in buttons:
        button_seleted(b, False)
    ROUND_PREFIX = "BONUS?: "
    def reset_bonus():
        global guessing_extra, showing_bonus_answer
        guessing_extra = None
        showing_bonus_answer = False
        destroy_bonus_characters()
        toggle_coming_up_popup(False, ROUND_PREFIX)

    if extra:
        if extra == guessing_extra:
            if extra == "characters" and bonus_overlay_window and not showing_bonus_answer:
                showing_bonus_answer = True
                toggle_coming_up_popup(False, ROUND_PREFIX)
                show_bonus_characters(bonus_chars, reveal_correct=True)
                return
            reset_bonus()
        else:
            guessing_extra = extra
        if guessing_extra == "year":
            button_seleted(guess_year_button, True)
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The Year This Anime Aired", 
                                ("Only 1 guess per person, no repeats.\n"
                                f"+{bonus_points[0]} for closest guess. "
                                f"+{bonus_points[1]} if exact year."),
                                up_next=False)
        elif guessing_extra == "members":
            button_seleted(guess_members_button, True)
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The # Of Members This Anime Has", 
                                ("Members are users who added the anime to their list on MyAnimeList.\n"
                                 "EG: Death Note has over 4 million. Only 1 guess per person, no repeats.\n"
                                f"+{bonus_points[0]} for closest guess. "
                                f"+{bonus_points[1]} PTs if first 2 digits are correct."),
                                up_next=False)
        elif guessing_extra == "popularity":
            button_seleted(guess_popularity_button, True)
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The Popularity Rank This Anime Has", 
                                ("The rank is based on users who added the anime to their list on MyAnimeList.\n"
                                 f"Ranks range from {get_lowest_parameter("popularity")} to {get_highest_parameter("popularity")}.\n"
                                f"+{bonus_points[0]} for closest guess. "
                                f"+{bonus_points[1]} PTs if exact rank."),
                                up_next=False)
        elif guessing_extra == "score":
            button_seleted(guess_score_button, True)
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The Score This Anime Has", 
                                ("Scores takem MyAnimeList and range from 0.0 to 10.0.\n"
                                 "Only 1 guess per person, no repeats.\n"
                                f"+{bonus_points[0]} for closest guess. "
                                f"+{bonus_points[1]} if exact score."),
                                up_next=False)
        elif guessing_extra == "tags":
            button_seleted(guess_tags_button, True)
            data = currently_playing.get("data")
            if data:
                tags = len(data.get('genres', []) + data.get('themes', []) + data.get('demographics', []))
                if tags > 1:
                    tags = str(tags) + " Tags"
                else:
                    tags = str(tags) + " Tag"
            else:
                tags = "Tag(s)"
            tags_array = split_array(get_random_tags())
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The " + tags + " This Anime Has", 
                                (f"Guess until you get a tag wrong. +{bonus_points[0]} for each correct tag.\n\n"
                                "[" + "] [".join(tags_array[0]) + "]\n[" + "] [".join(tags_array[1])) + "]",
                                up_next=False)
        elif guessing_extra == "multiple":
            button_seleted(guess_multiple_button, True)
            data = currently_playing.get("data")
            titles = get_random_titles()
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The Anime", 
                                (f"Only one guess. +{bonus_points[1]} if correct.\n\n"
                                f"[A] {titles[0]}\n[B] {titles[1]}\n"
                                f"[C] {titles[2]}\n[D] {titles[3]}"),
                                up_next=False)
        elif guessing_extra == "characters":
            button_seleted(guess_characters_button, True)
            
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The 2 Characters From This Anime", 
                                ("2 out of 6 characters are from this anime.\n"
                                f"+{bonus_points[0]} PT per correct guess."),
                                up_next=False)
            bonus_chars, bonus_correct_indices = pick_bonus_characters()
            
            def worker():
                show_bonus_characters(bonus_chars)
            threading.Thread(target=worker, daemon=True).start()
        elif guessing_extra == "studio":
            button_seleted(guess_studio_button, True)
            data = currently_playing.get("data")
            studios = data.get("studios", [])
            correct_studio = studios[0] if studios else "Unknown"

            # Weighted list: studios can repeat, so big studios are more likely
            weighted_studios = [s for s in get_all_studios(directory_files, False, True) if s != correct_studio]
            
            # Build unique distractors, weighted by frequency
            distractors = []
            used = set([correct_studio])
            attempts = 0
            while len(distractors) < 3 and attempts < 100:
                pick = random.choice(weighted_studios or ["Unknown"])
                if pick == "Unknown":
                    distractors = ["Unknown"] * 3
                    break
                if pick not in used:
                    distractors.append(pick)
                    used.add(pick)
                attempts += 1

            choices = [correct_studio] + distractors
            random.shuffle(choices)

            toggle_coming_up_popup(True,
                ROUND_PREFIX + "Guess The Studio That Made This Anime",
                (f"Which studio made this anime?\n"
                f"Only one guess. +{bonus_points[0]} if correct.\n\n"
                f"[A] {choices[0]}\n[B] {choices[1]}\n[C] {choices[2]}\n[D] {choices[3]}"),
                up_next=False)
        elif guessing_extra == "artist":
            button_seleted(guess_artist_button, True)
            data = currently_playing.get("data")
            # Get the correct song entry (by type and slug)
            slug = data.get("slug")
            theme = None
            for song in data.get("songs", []):
                if song.get("slug") == slug:
                    theme = song
                    break
            correct_artist = theme.get("artist", ["Unknown"])[0] if theme else "Unknown"

            # Build weighted list of distractor artists from other anime
            weighted_artists = []
            data_tags = set(data.get("genres", []) + data.get("themes", []) + data.get("demographics", []))
            for anime in anime_metadata.values():
                if anime.get("title") == data.get("title"):
                    continue
                anime_tags = set(anime.get("genres", []) + anime.get("themes", []) + anime.get("demographics", []))
                tag_overlap = len(data_tags & anime_tags)
                for song in anime.get("songs", []):
                    for artist in song.get("artist", []):
                        if artist and artist != correct_artist:
                            # Weight by tag overlap + 1 (always at least 1)
                            weighted_artists.extend([artist] * (1 + tag_overlap))

            # Pick 3 unique distractors, weighted by tag similarity
            distractors = []
            used = set([correct_artist])
            attempts = 0
            while len(distractors) < 3 and attempts < 100:
                if not weighted_artists:
                    break
                pick = random.choice(weighted_artists)
                if pick not in used:
                    distractors.append(pick)
                    used.add(pick)
                attempts += 1

            # Fallback if not enough distractors
            while len(distractors) < 3:
                distractors.append("Unknown")

            choices = [correct_artist] + distractors
            random.shuffle(choices)

            toggle_coming_up_popup(True,
                ROUND_PREFIX + "Guess The Artist Who Performed This Song",
                (f"Which artist performed the song for this anime?\n"
                f"Only one guess. +{bonus_points[0]} if correct.\n\n"
                f"[A] {choices[0]}\n[B] {choices[1]}\n[C] {choices[2]}\n[D] {choices[3]}"),
                up_next=False)
        elif guessing_extra == "song":
            button_seleted(guess_song_button, True)
            data = currently_playing.get("data")
            slug = data.get("slug")
            theme = None
            for song in data.get("songs", []):
                if song.get("slug") == slug:
                    theme = song
                    break
            correct_title = theme.get("title", "Unknown") if theme else "Unknown"
            correct_artist = theme.get("artist", ["Unknown"])[0] if theme and theme.get("artist") else "Unknown"

            # 1. Gather all songs by the same artist (excluding the correct song)
            same_artist_titles = []
            for anime in anime_metadata.values():
                if anime.get("title") == data.get("title"):
                    continue
                for song in anime.get("songs", []):
                    if song.get("artist") and correct_artist in song.get("artist") and song.get("title") and song.get("title") != correct_title:
                        same_artist_titles.append(song.get("title"))

            # 2. Gather weighted titles by tag overlap (excluding correct title and same artist titles)
            weighted_titles = []
            data_tags = set(data.get("genres", []) + data.get("themes", []) + data.get("demographics", []))
            for anime in anime_metadata.values():
                if anime.get("title") == data.get("title"):
                    continue
                anime_tags = set(anime.get("genres", []) + anime.get("themes", []) + anime.get("demographics", []))
                tag_overlap = len(data_tags & anime_tags)
                for song in anime.get("songs", []):
                    title = song.get("title")
                    if title and title != correct_title and title not in same_artist_titles:
                        weighted_titles.extend([title] * (1 + tag_overlap))

            # 3. Pick distractors: at least one from same artist (if available), rest from weighted
            distractors = []
            used = set([correct_title])
            # Pick one from same artist if possible
            if same_artist_titles:
                pick = random.choice(same_artist_titles)
                distractors.append(pick)
                used.add(pick)
            # Fill remaining slots from weighted titles
            attempts = 0
            while len(distractors) < 3 and attempts < 100:
                if not weighted_titles:
                    break
                pick = random.choice(weighted_titles)
                if pick not in used and pick:
                    distractors.append(pick)
                    used.add(pick)
                attempts += 1
            # Fallback if not enough distractors
            while len(distractors) < 3:
                distractors.append("Unknown")

            choices = [correct_title] + distractors
            random.shuffle(choices)

            toggle_coming_up_popup(True,
                ROUND_PREFIX + "Guess The Song Title",
                (f"Which song is played for this anime?\n"
                    f"Only one guess. +{bonus_points[0]} if correct.\n\n"
                f"[A] {choices[0]}\n[B] {choices[1]}\n[C] {choices[2]}\n[D] {choices[3]}"),
                up_next=False)
    else:
        reset_bonus()

def get_random_tags():
    data = currently_playing.get("data")
    if data:
        tags = get_tags(data)
        tags_len = len(tags)
        all_tags = get_all_tags(game=False, double=True)
        all_tags_len = len(get_all_tags(game=False))
        while len(tags) < 20 and len(tags) < tags_len*4 and len(tags) != all_tags_len:
            random_tag = random.choice(all_tags)
            if random_tag not in tags:
                tags.append(random_tag)
        return sorted(tags)
    return ["",""]

def get_random_titles(amount=4):
    data = currently_playing.get("data")
    if not data:
        return ["", "", "", ""]


    correct_title = get_display_title(data)
    correct_base_title = get_base_title(data)
    correct_series = (data.get("series") or [data.get("title")])
    titles = [correct_title]
    used_series = set(correct_series)

    GENERIC_WORDS = {"the", "a", "an", "of", "and", "in", "to", "for", "with", "on", "season", "part", "new", "as", "is", "at", "by", "from", 
                        "it", "this", "that", "these", "those", "animation", "movie", "ova", "special", "tv", "series", "episode", "episodes",
                        "no"}

    def get_words(title):
        return set(w.lower() for w in re.findall(r'\w+', title) if w.lower() not in GENERIC_WORDS)

    correct_words = get_words(correct_base_title)

    def get_similarity_score(anime):
        score = 0
        score += len(set(anime.get("genres", [])) & set(data.get("genres", [])))
        score += len(set(anime.get("themes", [])) & set(data.get("genres", [])))
        score += len(set(anime.get("studios", [])) & set(data.get("studios", [])))
        score += len(set(get_tags(anime)) & set(get_tags(data)))
        score -= max(0, (get_series_total(anime) - 2))
        # Add bonus for non-generic word overlap
        anime_words = get_words(get_base_title(anime))
        overlap = len(correct_words & anime_words)
        score += overlap * 2
        return score

    # Step 1: Filter and score
    similar_anime = [
        a for a in anime_metadata.values()
        if get_display_title(a) != correct_title
    ]

    # Step 2: Sort by similarity (descending)
    similar_anime = sorted(similar_anime, key=get_similarity_score, reverse=True)

    # Step 3: Filter for unique series
    unique_series_anime = []
    seen_series = set(used_series)
    for anime in similar_anime:
        series = anime.get("series") or [anime.get("title")]
        if isinstance(series, str):
            series = [series]
        if not seen_series.intersection(series):
            unique_series_anime.append(anime)
            seen_series.update(series)
        if len(unique_series_anime) >= 30:
            break

    # # Step 4: Try to include at least one with non-generic word overlap
    # overlap_candidates = [a for a in unique_series_anime if get_words(get_base_title(a)) & correct_words]
    distractors = []
    # if overlap_candidates:
    #     pick = random.choice(overlap_candidates)
    #     distractors.append(get_display_title(pick))
    #     unique_series_anime = [a for a in unique_series_anime if a != pick]

    # Step 5: Fill remaining with less popular ones
    needed = amount - 1 - len(distractors)
    top_similar_sorted_by_members = sorted(unique_series_anime, key=lambda a: int(a.get("members") or 0))
    for group in split_array(top_similar_sorted_by_members, needed):
        if group:
            pick = random.choice(group)
            distractors.append(get_display_title(pick))

    titles.extend(distractors)
    random.shuffle(titles)
    return titles

def get_series_total(data):
    get_series_totals(refetch=False)
    series = data.get("series")
    if series:
        series = series[0]
    else:
        series = data.get("title")
    return series_totals[series]

def split_array(arr, parts=2):
    if parts <= 0:
        raise ValueError("Number of parts must be positive")
    
    avg_len = len(arr) / float(parts)
    output = []
    last = 0.0

    while last < len(arr):
        output.append(arr[int(last):int(last + avg_len)])
        last += avg_len

    return output

bonus_overlay_window = None
bonus_character_labels = []
bonus_correct_indices = []

def pick_bonus_characters():
    """
    Picks 2 'appears' characters from the current show and 2 distractors from different series.
    Prioritizes distractors from shows with shared studios or tags.
    Returns: list of 4 character tuples, and indices of the correct ones.
    """
    data = currently_playing.get("data", {})
    if not data or not data.get("characters"):
        return [], []

    # Get correct characters
    characters = data["characters"]
    selected = []

    def get_chars_by_role(role_code):
        return [c for c in characters if c[0] == role_code and c[2] and c[3] != "unknown"]

    # Try getting characters in order: appears -> secondary -> main
    for role in ["a", "s", "m"]:
        role_chars = get_chars_by_role(role)
        needed = 2 - len(selected)
        if role_chars:
            selected.extend(random.sample(role_chars, min(needed, len(role_chars))))
        if len(selected) == 2:
            break

    # Fallback if somehow still not 2
    if len(selected) < 2:
        backup = [c for c in characters if c[2]]
        selected.extend(random.sample(backup, min(2 - len(selected), len(backup))))

    # Metadata for comparison
    correct_series = data.get("series") or [data.get("title")]
    correct_year = int(data.get("season", "9999")[-4:])
    used_series = set(correct_series)
    correct_studios = set(data.get("studios") or [])
    correct_tags = set(get_tags(data))
    correct_has_anthro = "Anthropomorphic" in correct_tags

    distractors = []

    for mal_id, anime in anime_metadata.items():
        if not mal_id.isdigit() or (anime.get("series") or [anime.get("title")]) == correct_series:
            continue

        # Series exclusion
        series = anime.get("series") or [anime.get("title")]
        if set(series).intersection(used_series):
            continue

        # Anthropomorphic tag pairing rule
        anime_tags = set(get_tags(anime))
        if ("Anthropomorphic" in anime_tags) != correct_has_anthro:
            continue

        # Get characters via mapping
        anidb_data = get_anidb_metadata_from_anime(mal_id)
        if not anidb_data:
            continue

        valid_chars = [c for c in anidb_data.get("characters", []) if c[0] == "a" and c[2] and c[3] != "unknown"]
        if not valid_chars:
            continue

        # Score based on studio and tag overlap
        score = 0
        score += len(set(anime.get("studios", [])) & correct_studios) * 3
        score += len(anime_tags & correct_tags)
        distractor_year = int(anime.get("season", "9999")[-4:])
        if correct_year and distractor_year:
            year_diff = abs(correct_year - distractor_year)
            if year_diff <= 2:
                score += 3
            elif year_diff <= 5:
                score += 2
            elif year_diff <= 10:
                score += 1

        distractors.append((score, random.choice(valid_chars), set(series)))

    # Sort by score descending and uniqueness of series
    distractors.sort(key=lambda x: -x[0])

    final_distractors = []
    for _, char, series_set in distractors:
        if not used_series.intersection(series_set):
            final_distractors.append(char)
            used_series.update(series_set)
        if len(final_distractors) == 4:
            break

    # Fallback if we couldn’t get 2 unique
    while len(final_distractors) < 4:
        random_char = random.choice([c for c in characters if c not in selected and c[2]])
        final_distractors.append(random_char)

    all_chars = selected + final_distractors
    random.shuffle(all_chars)
    correct_indices = [i for i, c in enumerate(all_chars) if c in selected]
    return all_chars, correct_indices

def get_anidb_metadata_from_anime(mal):
    # Find file metadata entries that link MAL or AniDB to AniDB ID
    for file_entry in file_metadata.values():
        anidb_id = file_entry.get("anidb")
        mal_id = file_entry.get("mal")

        # Match either by direct MAL ID
        if mal_id == mal:
            return anidb_metadata.get(anidb_id)

    return {}  # No match found

def show_bonus_characters(characters, reveal_correct=False):
    global bonus_overlay_window, bonus_character_labels

    # Destroy existing window if needed
    if bonus_overlay_window and bonus_overlay_window.winfo_exists():
        bonus_overlay_window.destroy()

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    height = int(screen_height * 0.3)
    if reveal_correct:
        width = int(screen_width * 0.585)
        y = scl(10)
    else:
        width = coming_up_window.winfo_reqwidth()
        y = coming_up_window.winfo_reqheight() + scl(20)
    
    x = (screen_width - width) // 2

    bonus_overlay_window = tk.Toplevel(root)
    bonus_overlay_window.geometry(f"{width}x{height}+{x}+{y}")
    bonus_overlay_window.overrideredirect(True)
    bonus_overlay_window.lift()
    bonus_overlay_window.attributes("-topmost", True)
    bonus_overlay_window.attributes("-alpha", 0.9)
    bonus_overlay_window.config(bg=OVERLAY_BACKGROUND_COLOR)

    container = tk.Frame(bonus_overlay_window, bg="pink")
    container.pack(expand=True)

    label_font = ("Arial", scl(24), "bold")
    bonus_character_labels = []

    # Use a nested frame to help center the character row
    center_frame = tk.Frame(container, bg=OVERLAY_BACKGROUND_COLOR)
    center_frame.pack(expand=True)

    for i, char in enumerate(characters):
        img_url = "https://cdn-eu.anidb.net/images/main/" + char[2]
        img = load_image_from_url(img_url, size=(scl(210), scl(315)))
        # Frame for each character (black background, white border)
        frame = tk.Frame(center_frame,
                         bg="black",
                         highlightbackground=OVERLAY_TEXT_COLOR,
                         highlightthickness=scl(2),
                         padx=scl(6),
                         pady=scl(6))
        frame.grid(row=0, column=i, padx=scl(5), pady=scl(5))

        inner_frame = tk.Frame(frame, bg=OVERLAY_BACKGROUND_COLOR)
        inner_frame.pack()


        back_color = "gray" if reveal_correct and i in bonus_correct_indices else "black"
        label = tk.Label(inner_frame,
                         image=img,
                         text=f"[{chr(65+i)}]",
                         font=label_font,
                         compound="top",
                         fg="white",
                         bg=back_color)
        label.image = img
        label.pack()
        bonus_character_labels.append(label)

def destroy_bonus_characters():
    global bonus_overlay_window
    if bonus_overlay_window and bonus_overlay_window.winfo_exists():
        bonus_overlay_window.destroy()
        bonus_overlay_window = None

# =========================================
#         *RULES
# =========================================

def load_rules(filename="rules.json", folder="files"):
    """
    Loads the rules JSON file from the specified folder.

    Args:
        filename (str): The name of the JSON file.
        folder (str): The folder where the file is located.

    Returns:
        dict: Parsed JSON data as a Python dictionary.
    """
    file_path = os.path.join(folder, filename)
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON in '{file_path}': {e}")
        return {}

scoreboard_rules = load_rules()
def set_rules(type=None):
    if not scoreboard_rules:
        return
    
    rules_txt = f"[RULES]{"\n".join(scoreboard_rules.get("global_title", []))}\n"
    if type == "anime":
        rules_txt += "\n".join(scoreboard_rules.get("lightning_anime", []))
    elif type == "character":
        rules_txt += "\n".join(scoreboard_rules.get("lightning_character", []))
    elif type == "trivia":
        rules_txt += "\n".join(scoreboard_rules.get("lightning_trivia", []))
    else:
        rules_txt += "\n".join(scoreboard_rules.get("standard", []))
    rules_txt += "\n" + "\n".join(scoreboard_rules.get("global_end", [])) 

    send_scoreboard_command(rules_txt)

# =========================================
#         *VIDEO PLAYBACK/CONTROLS
# =========================================

currently_playing = {}
def play_video(index=playlist["current_index"]):
    """Function to play a specific video by index"""
    global video_stopped, currently_playing, search_queue, censors_enabled, frame_light_round_started, light_round_start_time, synopsis_start_index, title_light_letters, playlist_loaded, playing_next_error, light_round_started
    playlist_loaded = False
    light_round_start_time = None
    synopsis_start_index = None
    title_light_letters = None
    clean_up_light_round()
    light_round_started = False
    video_stopped = True
    playing_next_error = False
    guess_extra()
    toggle_title_popup(False)
    set_countdown()
    toggle_coming_up_popup(False)

    if playlist["current_index"] < len(playlist["playlist"]) and index + 1 >= len(playlist["playlist"]):
        if len(playlist["playlist"]) >= INFINITE_PLAYLIST_LIMIT:
            index -= len(playlist["playlist"]) - INFINITE_PLAYLIST_LIMIT + 1
        get_next_infinite_track()
        
    if youtube_queue is not None:
        currently_playing = {
            "type":"youtube",
            "filename": youtube_queue.get("filename"),
            "data":youtube_queue
        }
        set_black_screen(False)
        reset_metadata()
        update_youtube_metadata()
        if "guess the character" in (get_youtube_display_title(youtube_queue)).lower():
            set_rules("character")
        else:
            set_rules("anime")
        stream_youtube(os.path.join("youtube", youtube_queue.get("filename")))
        unload_youtube_video()
    elif search_queue:
        # Check if search_queue is a YouTube file
        if is_youtube_file(search_queue):
            youtube_data = get_youtube_metadata_by_filename(search_queue)
            if youtube_data:
                currently_playing = {
                    "type":"youtube",
                    "filename": search_queue,
                    "data":youtube_data
                }
                set_black_screen(False)
                reset_metadata()
                update_youtube_metadata(youtube_data)
                if "guess the character" in (get_youtube_display_title(youtube_data)).lower():
                    set_rules("character")
                else:
                    set_rules("anime")
                # Get file path for external YouTube files
                youtube_file_path = get_file_path(search_queue)
                if youtube_file_path:
                    stream_youtube(youtube_file_path)
                else:
                    stream_youtube(os.path.join("youtube", search_queue))
            else:
                play_filename(search_queue)
        else:
            play_filename(search_queue)
        search_queue = None
        if "SEARCH QUEUE" in popout_buttons_by_name:
            button_seleted(popout_buttons_by_name["SEARCH QUEUE"], False)
    elif 0 <= index < len(playlist["playlist"]):
        same_index = index == playlist["current_index"]
        update_current_index(index)
        up_next_text()
        
        playlist_entry = playlist["playlist"][playlist["current_index"]]
        filename = get_clean_filename(playlist_entry)
        
        # Check if this is a YouTube file
        if is_youtube_file(filename):
            youtube_data = get_youtube_metadata_by_filename(filename)
            if youtube_data:
                currently_playing = {
                    "type":"youtube",
                    "filename": filename,
                    "data":youtube_data
                }
                set_black_screen(False)
                reset_metadata()
                update_youtube_metadata(youtube_data)
                if "guess the character" in (get_youtube_display_title(youtube_data)).lower():
                    set_rules("character")
                else:
                    set_rules("anime")
                # Get file path for external YouTube files
                youtube_file_path = get_file_path(playlist_entry)
                if youtube_file_path:
                    stream_youtube(youtube_file_path)
                else:
                    stream_youtube(os.path.join("youtube", filename))
            else:
                if play_filename(playlist_entry, fullscreen=not same_index or autoplay_toggle != 1):
                    root.after(3000, thread_prefetch_metadata)
                    root.after(1000, queue_next_lightning_mode)
        else:
            if play_filename(playlist_entry, fullscreen=not same_index or autoplay_toggle != 1):
                root.after(3000, thread_prefetch_metadata)
                root.after(1000, queue_next_lightning_mode)
    else:
        if index < 0:
            play_next()
        else:
            messagebox.showinfo("Playlist Error", "Invalid playlist index.")
        return
    
    if playlist["current_index"]+1 < len(playlist["playlist"]):
        next_filename = get_clean_filename(playlist["playlist"][playlist["current_index"]+1])
        root.after(1000, check_next_queue_round, next_filename)
    add_session_history()

def check_next_queue_round(next_filename_set):
    if playlist["current_index"]+1 < len(playlist["playlist"]):
        next_filename = get_clean_filename(playlist["playlist"][playlist["current_index"]+1])
        if next_filename_set == next_filename:
            if check_blind_mark(next_filename):
                toggle_blind_round()
            elif check_peek_mark(next_filename):
                toggle_peek_round()
            elif check_mute_peek_mark(next_filename):
                toggle_mute_peek_round()

skip_limit = 0
def skip_filename():
    global blind_round_toggle, peek_round_toggle, mute_peek_round_toggle, skip_limit
    blind_round_toggle = False
    peek_round_toggle = False
    mute_peek_round_toggle = False
    skip_limit += 1
    play_video(playlist["current_index"] + skip_direction)  # Try playing the next video

def play_filename(playlist_entry, fullscreen=True):
    global blind_round_toggle, peek_round_toggle, mute_peek_round_toggle, currently_playing
    global video_stopped, previous_media, skip_limit
    filepath = get_file_path(playlist_entry)  # Get file path from playlist
    # Extract clean filename for metadata lookup (removes [L] prefix)
    filename = get_clean_filename(playlist_entry)
    data = get_metadata(filename, fetch=auto_fetch_missing)
    if skip_limit <= 10:
        if not filepath or not os.path.exists(filepath):  # Check if file exists
            print(f"File not found: {filepath}. Skipping...")
            skip_filename()
            return False
        elif not variety_light_mode_enabled and light_mode and not has_lightning_mode_info(data, light_mode):
            print(f"Not enough info for {filename}. Skipping...")
            skip_filename()
            return False
    currently_playing = {
        "type":"theme",
        "filename":filename,
        "playlist_entry":playlist_entry,
        "data":data
    }
    update_censor_button_count()
    if censor_editor:
        open_censor_editor(True)
    if variety_light_mode_enabled:
        set_variety_light_mode()
    if auto_info_start:
        toggle_title_popup(True)
    # Update metadata display asynchronously
    update_metadata_queue(playlist["current_index"])
    is_mp4 = filepath.lower().endswith(".mp4") or filepath.lower().endswith(".m4v")
    is_webm = filepath.lower().endswith(".webm")
    if not is_webm:
        if current_vout != 'opengl':
            set_vout(vout_module='opengl')
    elif current_vout:
        set_vout()
    if hw_acc_enabled or is_mp4:
        media = instance.media_new(filepath)
    else:
        media = instance.media_new(filepath, ":avcodec-hw=none")
    previous_media = media
    player.set_media(media)
    global light_round_number, light_round_length
    if light_mode:
        if "c." in light_mode:
            set_rules("character")
        elif light_mode == "trivia":
            set_rules("trivia")
        else:
            set_rules("anime")
        if light_round_number%10 == 0:
            next_background_track()
        light_round_number = light_round_number + 1
        if light_mode != 'peek':
            set_light_round_number("#" + str(light_round_number))
        light_round_length = lightning_mode_settings.get(light_mode, {}).get("length", light_round_length_default)
        if not black_overlay:
            set_black_screen(True)
            root.after(500, lambda: player.play())
        else:
            player.play()
    else:
        set_rules()
        light_round_number = 0
        set_countdown()
        set_light_round_number()
        global manual_blind
        toggle_coming_up_popup(False, "Lightning Round")
        if blind_round_toggle:
            button_seleted(blind_round_button, blind_round_toggle)
            manual_blind = True
            set_black_screen(True)
            root.after(500, lambda: player.play())
        elif peek_round_toggle or mute_peek_round_toggle:
            manual_blind = False
            set_black_screen(False)
            toggle_peek()
            if peek_round_toggle:
                button_seleted(peek_round_button, peek_round_toggle)
            else:
                next_background_track()
                toggle_mute(True)
                button_seleted(mute_peek_round_button, mute_peek_round_toggle)
            root.after(500, lambda: player.play())
        else:
            manual_blind = False
            set_black_screen(False)
            player.play()
    blind_round_toggle = False
    button_seleted(blind_round_button, False)
    peek_round_toggle = False
    button_seleted(peek_round_button, False)
    mute_peek_round_toggle = False
    button_seleted(mute_peek_round_button, False)
    if light_mode not in ['frame', 'clip', 'ost', 'blind']:
        root.after(500, play_video_retry, 5, fullscreen)  # Retry playback
    
    # Mark lightning status for infinite playlists only
    if playlist.get("infinite", False):
        current_entry = playlist["playlist"][playlist["current_index"]]
        lightning_changed = False
        if light_mode:  # Lightning round
            # Add [L] if not already there
            if not current_entry.startswith("[L]"):
                playlist["playlist"][playlist["current_index"]] = "[L]" + current_entry
                lightning_changed = True
        else:  # Normal round
            # Remove [L] if it's there
            if current_entry.startswith("[L]"):
                playlist["playlist"][playlist["current_index"]] = current_entry[3:]
                lightning_changed = True
        
        # Refresh playlist display if lightning status changed
        if lightning_changed:
            root.after(10, refresh_current_list)
    
    # Update playlist name to reflect new count (will be updated when session log is added)
    root.after(100, update_playlist_name)
    skip_limit = 0
    save_config()
    return True

# =========================================
#         *SESSION LOGS
# =========================================

def parse_timestamp_flexible(timestamp_str):
    """Parse timestamp that can be either 'HH:MM:SS' or 'YYYY-MM-DD HH:MM:SS' format"""
    try:
        # Try full datetime format first
        if len(timestamp_str) > 8:  # Full datetime format
            return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        else:  # Time-only format - use today's date
            time_part = datetime.strptime(timestamp_str, '%H:%M:%S').time()
            return datetime.combine(datetime.now().date(), time_part)
    except ValueError:
        # If both fail, return current time as fallback
        return datetime.now()

session_data = []  # JSON session data
session_start_time = None

def generate_session_stats():
    """Generate session statistics header for text file"""
    if not session_data:
        return []
    
    stats_lines = []
    
    # Basic session info
    first_entry = session_data[0]
    last_entry = session_data[-1]
    start_time = parse_timestamp_flexible(first_entry.get("timestamp", ""))
    end_time = parse_timestamp_flexible(last_entry.get("timestamp", ""))
    duration = end_time - start_time
    
    # Format duration in hours with 1 decimal place
    duration_hours = duration.total_seconds() / 3600
    
    # Get timezone info
    local_timezone = time.tzname[time.daylight] if time.daylight else time.tzname[0]
    
    stats_lines.append("="*60)
    stats_lines.append("GUESS THE ANIME! SESSION LOG")
    stats_lines.append(start_time.strftime('%B %d, %Y').upper())
    stats_lines.append(f"{start_time.strftime('%I:%M%p').lower()} - {end_time.strftime('%I:%M%p').lower()} ({duration_hours:.1f} HOURS) {local_timezone}")
    stats_lines.append("="*60)
    
    # Get unique themes for counting
    unique_themes = get_unique_themes_played()
    
    # Count OP/ED from unique themes only
    op_count, ed_count = get_op_ed_counts(unique_themes)
    
    stats_lines.append(f"Themes Played: {len(unique_themes)}")
    
    # Only show OP/ED if there are any
    if op_count + ed_count > 0:
        op_percent = (op_count / (op_count + ed_count)) * 100
        ed_percent = (ed_count / (op_count + ed_count)) * 100
        stats_lines.append(f"Openings: {op_count} ({op_percent:.1f}%)")
        stats_lines.append(f"Endings: {ed_count} ({ed_percent:.1f}%)")

    # Only show lightning rounds if there were any
    lightning_tracks = sum(1 for entry in session_data if entry.get("lightning_mode"))
    if lightning_tracks > 0:
        stats_lines.append(f"Lightning Rounds: {lightning_tracks}")
    
    # Only show YouTube videos if there were any
    youtube_count = sum(1 for entry in session_data if entry.get("type") == "youtube")
    if youtube_count > 0:
        stats_lines.append(f"YouTube Videos: {youtube_count}")
    
    # Add scoreboard section if there are any score changes
    scoreboard_entries = [entry for entry in session_data if entry.get("type") == "scoreboard_score"]
    if scoreboard_entries:
        # Collect final scores for each player
        player_scores = {}
        for entry in scoreboard_entries:
            player = entry.get("player", "")
            new_score = entry.get("new_score", 0)
            player_scores[player] = new_score
        
        # Sort players by score (highest to lowest)
        sorted_players = sorted(player_scores.items(), key=lambda x: x[1], reverse=True)
        
        stats_lines.append("="*60)
        stats_lines.append("-SCOREBOARD-")
        stats_lines.append("PTs   PLAYER")
        stats_lines.append("‾‾‾‾‾‾‾‾‾‾‾‾")
        for i, (player, score) in enumerate(sorted_players, 1):
            # Format score to remove .0 if it's a whole number
            score_str = f"{score:g}"
            score_str += " " * (4 - len(score_str))  # Padding for alignment
            stats_lines.append(f"{score_str}  {player}")
    
    stats_lines.append("="*60)
    stats_lines.append("")  # Empty line before session data
    
    return stats_lines

def generate_text_from_session_data():
    """Generate text format from session_data for text file output"""
    # Start with statistics header
    text_lines = generate_session_stats()
    
    lightning_round_num = 0
    for i, entry in enumerate(session_data):
        timestamp = entry.get("timestamp", "")
        entry_type = entry.get("type", "theme")
        filename = entry.get("filename", "")
        lightning_mode = entry.get("lightning_mode")
        
        # Calculate lightning round number if this is a lightning entry
        
        session_string = f"{timestamp}:"
        
        if entry_type == "youtube":
            url = entry.get("url", "")
            title = entry.get("title", "")
            name = entry.get("name", "")
            session_string = f"{session_string} [YOUTUBE VIDEO({url})] - {title} by {name}"
        elif entry_type == "scoreboard_score":
            player = entry.get("player", "")
            delta = entry.get("delta", 0)
            old_score = entry.get("old_score", 0)
            new_score = entry.get("new_score", 0)
            if delta == 1:
                delta_str = "PT"
            else:
                delta_str = "PTs"
            session_string = f"{session_string} [SCOREBOARD] {player} {delta:+g} {delta_str} ({old_score} → {new_score})"
        else:
            if lightning_mode:
                lightning_round_num += 1
                session_string = f"{session_string} [LIGHTNING ROUND #{lightning_round_num}({lightning_mode.upper()})] -"
            else:
                lightning_round_num = 0  # Not a lightning round
            title = entry.get("title", "")
            slug = entry.get("slug", "")
            
            # Look up metadata to get song and artist details
            theme_data = get_metadata(filename)
            song_and_artist = ""
            
            if theme_data and slug:
                # Set the slug in the data so get_song_string can match properly
                theme_data["slug"] = slug
                song_and_artist = get_song_string(theme_data)
            
            # Build the session string
            session_string = f"{session_string} {title} - {format_slug(slug)}"
            if song_and_artist:
                session_string = f"{session_string} ({song_and_artist})"
        
        if not title and filename:
            session_string = f"{session_string} {filename}"
            
        text_lines.append(session_string)
    
    return text_lines

def get_unique_themes_played():
    """Get list of unique filenames played this session from session data"""
    unique_themes = []
    seen = set()
    for entry in session_data:
        if entry.get("lightning_mode"):
            continue  # Skip lightning rounds
        filename = entry.get("filename")
        if filename and filename not in seen:
            unique_themes.append(filename)
            seen.add(filename)
    return unique_themes

def get_themes_played_count():
    """Get count of unique themes played this session"""
    return len(get_unique_themes_played())

def get_current_session_lightning_tracks():
    """Get set of filenames that were played in lightning mode during the current session"""
    lightning_tracks = set()
    for entry in session_data:
        if entry.get("lightning_mode") and entry.get("filename"):
            lightning_tracks.add(entry.get("filename"))
    return lightning_tracks

def create_new_session():
    """Initialize a new session log"""
    global session_start_time
    # First try to load a recent session  
    if not load_recent_session():
        # No recent session found, start a new one
        session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')
        # Clear any existing score changes from previous sessions
        try:
            open("score_changes.json", "w").close()
        except Exception:
            pass  # File might not exist yet

def load_recent_session():
    """Check for existing current_session.json file and load it to continue the session"""
    global session_data, session_start_time
    
    sessions_folder = "sessions"
    if not os.path.exists(sessions_folder):
        return False
    
    json_path = os.path.join(sessions_folder, "current_session.json")
    if not os.path.exists(json_path):
        return False
    
    try:
        # Get file modification time
        file_mod_time = datetime.fromtimestamp(os.path.getmtime(json_path))
        current_time = datetime.now()
        time_diff = (current_time - file_mod_time).total_seconds() / 60  # minutes
        
        if time_diff <= 120:  # Within # minutes
            if time_diff > 15:
                confirm = messagebox.askyesno("Continue Session", "A recent session was found. Do you want to continue it?")
                if not confirm:
                    # delete the existing session file
                    os.remove(json_path)
                    return False
            # Load the existing session
            with open(json_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            # Set session start time based on first entry or current time
            if session_data:
                first_timestamp = session_data[0].get("timestamp", "")
                if first_timestamp:
                    session_start_time = parse_timestamp_flexible(first_timestamp).strftime('%Y-%m-%d_%H-%M')
                else:
                    session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')
            else:
                session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')
            update_playlist_name()
            return True
                    
    except (ValueError, json.JSONDecodeError, KeyError):
        return False  # Invalid file format, skip
    
    return False

def add_session_history():
    global session_data, session_start_time
    
    data = currently_playing.get("data")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if len(session_data) == 0:
        session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')
    
    # Create JSON session entry
    session_entry = {
        "timestamp": timestamp,
        "type": currently_playing.get("type", "theme"),
        "filename": currently_playing.get("filename", ""),
        "lightning_mode": light_mode if light_mode else None
    }
    
    # Add data fields if available
    if data:
        session_entry.update({
            "id": data.get("mal"),
            "title": get_display_title(data),
            "name": data.get("name"),
            "slug": data.get("slug")
        })
        
        if currently_playing.get("type") == "youtube":
            session_entry["url"] = data.get("url")
            session_entry["title"] = get_youtube_display_title(data)
    
    session_data.append(session_entry)
    
    # Always save JSON immediately, save text file every 100 entries
    if len(session_data) % 100 == 0 and playlist.get("name") not in SYSTEM_PLAYLISTS:
        save_session_history(create_text_file=True)  # Create text file
    else:
        save_session_history(create_text_file=False)   # Only JSON file

def save_session_history(create_text_file=True, silent=True):
    global session_data
    if not session_data or not session_start_time:
        return  # Nothing to save

    # Add any new score changes from scoreboard before saving
    add_score_changes_to_session()
    
    # Sort session_data by timestamp to maintain chronological order
    def get_sort_key(entry):
        timestamp_val = entry.get("timestamp", "00:00:00")
        
        # Handle different timestamp types
        try:
            # If it's already a number (Unix timestamp), return it directly
            if isinstance(timestamp_val, (int, float)):
                return float(timestamp_val)
            
            # If it's a string, parse it
            if isinstance(timestamp_val, str):
                if len(timestamp_val) > 8:  # Full datetime format
                    dt = datetime.strptime(timestamp_val, "%Y-%m-%d %H:%M:%S")
                    return dt.timestamp()
                else:  # Time only format - use today's date
                    time_part = datetime.strptime(timestamp_val, "%H:%M:%S").time()
                    dt = datetime.combine(datetime.now().date(), time_part)
                    return dt.timestamp()
            
            # If it's neither string nor number, return 0
            return 0
            
        except (ValueError, OverflowError, TypeError):
            return 0  # Fallback for invalid timestamps
    
    session_data.sort(key=get_sort_key)

    # Ensure the folder exists
    os.makedirs("sessions", exist_ok=True)

    # Always save JSON file (overwrites existing current_session.json)
    json_filename = "sessions/current_session.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)
    
    # Save text file if requested
    if create_text_file:
        txt_filename = f"sessions/guess_the_anime_{session_start_time}.txt"
        text_lines = generate_text_from_session_data()
        
        with open(txt_filename, "w", encoding="utf-8") as f:
            for line in text_lines:
                f.write(line + "\n")
        if not silent:
            print(f"Session log saved to: {txt_filename}")

def thread_prefetch_metadata():
    if auto_fetch_missing:
        threading.Thread(target=pre_fetch_metadata, daemon=True).start()

def play_video_retry(retries, fullscreen=True):
    global video_stopped
    # Check if the video is playing
    if (not player.is_playing() or player.get_length() == 0):
        if retries > 0:
            if retries < 5:
                print(f"Retrying playback for: {currently_playing.get('filename')}")
                player.play()
            root.after(2000, play_video_retry, retries - 1)  # Retry playback
            return
        else:
            play_video(playlist["current_index"] + skip_direction)
    if fullscreen:
        player.set_fullscreen(False)
        player.set_fullscreen(True)
        set_skip_direction(1)
    video_stopped = False

previous_media = None
def check_video_end():
    """Function to check if the current video has ended"""
    global video_stopped
    if player.is_playing() or video_stopped or autoplay_toggle == 2 or last_seek_time:
        # If the video is still playing, check again in 1/2 second
        root.after(500, check_video_end)
    else:
        # If the video has ended, play the next video
        if autoplay_toggle == 0:
            play_next()
            video_stopped = True
        else:
            player.pause()
            player.set_media(previous_media)
            player.play()
        root.after(10000, check_video_end)

def update_current_index(value = None, save = True):
    """Function to update the current entry text box"""
    global current_entry
    try:
        if value != None:
            playlist["current_index"] = value
        if globals().get("current_entry"):
            current_entry.delete(0, tk.END)
            if playlist.get("infinite", False):
                current_entry.insert(0, "∞")
                out_of = total_infinite_files - len(cached_skipped_themes)
            else:
                current_entry.insert(0, str(playlist["current_index"]+1))
                out_of = len(playlist["playlist"])
            playlist_size_label.configure(text = "/" + str(out_of))
        
        # Update playlist view to show current item if playlist is loaded
        if list_loaded == "playlist" and value is not None:
            global current_list_offset, current_list_selected
            # Update the selected index to match the current playing item
            current_list_selected = value
            # Auto-scroll if current item or next 3 items are not visible
            entries_count = get_list_entries_count()
            current_start = current_list_offset
            current_end = current_list_offset + entries_count
            
            # Check if current track or next 3 tracks ahead are not visible
            look_ahead = min(3, len(playlist["playlist"]) - value - 1)  # Don't look beyond playlist end
            needs_scroll = (value < current_start or value >= current_end or 
                          (value + look_ahead) >= current_end)
            
            if needs_scroll:
                # Position so current item is visible with room for next 3 tracks
                ideal_offset = max(0, value - 1)  # Show current with 1 item before if possible
                max_offset = max(0, len(playlist["playlist"]) - entries_count)
                current_list_offset = min(ideal_offset, max_offset)
            refresh_current_list()
            
        if save:
            save_config()
    except NameError:
        pass  # root isn't defined yet — possibly too early in startup

_cached_images = {}
def load_image_from_url(url, size=(400, 400)):
    """Loads an image from a URL, resizes it to fit one side of the box fully (maximizing size while preserving aspect ratio), centers it in a transparent box, and returns a Tkinter-compatible PhotoImage."""
    if _cached_images.get(url):
        image = _cached_images[url]
    else:
        response = requests.get(url)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        _cached_images[url] = image
    if not size:
        return ImageTk.PhotoImage(image)

    # Target box size
    box_width, box_height = size
    img_width, img_height = image.size

    # Calculate scale factors
    scale_w = box_width / img_width
    scale_h = box_height / img_height

    # Use the smaller scale so the image fits completely inside the box
    scale = min(scale_w, scale_h)

    # Compute new size
    new_size = (int(img_width * scale), int(img_height * scale))
    image = image.resize(new_size, Image.LANCZOS)

    # Create a transparent box and paste the resized image centered
    background = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    offset_x = (box_width - new_size[0]) // 2
    offset_y = (box_height - new_size[1]) // 2
    background.paste(image, (offset_x, offset_y), image)

    return ImageTk.PhotoImage(background)

def go_to_index():
    """Function to jump to a specific index"""
    try:
        index = int(current_entry.get())-1
        if 0 <= index < len(playlist["playlist"]):
            play_video(index)
        else:
            messagebox.showwarning("Invalid Index", "Index is out of range.")
    except ValueError:
        messagebox.showwarning("Invalid Input", "Please enter a valid number.")

def play_pause():
    """Function to play/pause the video"""
    global video_stopped, frame_light_round_pause
    video_stopped = True
    if frame_light_round_started:
        frame_light_round_pause = not frame_light_round_pause
        return
    elif light_mode and lightning_mode_settings.get(light_mode, {}).get("muted"):
        if player.is_playing():
            pygame.mixer.music.pause()
        elif light_round_start_time and ((player.get_time()/1000) < (light_round_start_time+light_round_length)):
            pygame.mixer.music.unpause()
    if player.is_playing():
        video_stopped = True
        player.pause()
    elif player.get_media():
        player.play()
        video_stopped = False
    else:
        play_video(playlist["current_index"])
    
    for plyr in [mismatched_player, stream_player]:
        if plyr.is_playing():
            plyr.pause()
        elif plyr.get_media():
            plyr.play()

# Function to play next video
skip_direction = 1
def set_skip_direction(dir):
    global skip_direction
    skip_direction = dir

def play_next():
    set_skip_direction(1)
    if playlist_loaded:
        play_video(playlist["current_index"])
    else:
        if playlist["current_index"] + 1 >= len(playlist["playlist"]):
            get_next_infinite_track()
        if playlist["current_index"] + 1 < len(playlist["playlist"]):
            play_video(playlist["current_index"] + 1)

def play_previous():
    """Function to play previous video"""
    if playlist["current_index"] - 1 >= 0:
        set_skip_direction(-1)
        play_video(playlist["current_index"] - 1)

def stop():
    """Function to stop the video"""
    global video_stopped, currently_playing
    video_stopped = True
    toggle_light_mode()
    clean_up_light_round()
    set_countdown()
    set_light_round_number()
    set_black_screen(False)
    toggle_title_popup(False)
    guess_extra()
    player.stop()
    player.set_media(None)  # Reset the media
    update_progress_bar(0,1)
    remove_all_censor_boxes()
    seek_bar.set(0)

last_seek_time = None
def seek(value):
    """Function to seek the video"""
    global can_seek
    if can_seek:
        global last_seek_time
        last_seek_time = value
    else:
        can_seek = True

last_vlc_time = 0
projected_vlc_time = 0
SEEK_POLLING = 50
last_error = None
last_error_count = 0
playing_next_error = False
def update_seek_bar():
    """Function to update the seek bar"""
    global last_vlc_time, projected_vlc_time, last_error, last_error_count, coming_up_queue, playing_next_error, can_seek
    try:
        if not player.is_playing():
            vlc_time = player.get_time()
            if vlc_time != last_vlc_time or last_vlc_time != projected_vlc_time:
                last_vlc_time = vlc_time
                projected_vlc_time = vlc_time
                if not last_seek_time:
                    can_seek = False
                    seek_bar.set(vlc_time/1000)
        else:
            vlc_time = player.get_time()
            if vlc_time != last_vlc_time:
                last_vlc_time = vlc_time
                projected_vlc_time = vlc_time
            else:
                projected_vlc_time = projected_vlc_time + SEEK_POLLING * light_speed_modifier
            length = player.get_length()/1000
            time = projected_vlc_time/1000
            if manual_blind and not light_round_started:
                set_progress_overlay(time, length)
            if peek_overlay1 and not light_round_started:
                gap = get_peek_gap(currently_playing.get("data"))
                progress = ((time+peek_modifier)%24/12)*100
                if progress >= 100:
                    direction = "right"
                    progress -= 100
                else:
                    direction = "down"
                toggle_peek_overlay(direction=direction, progress=progress, gap=gap)
            if length > 0:
                if not last_seek_time:
                    can_seek = False
                    seek_bar.config(to=length)
                    seek_bar.set(time)
                if currently_playing.get("type") == "youtube":
                    start = currently_playing.get("data").get("start")
                    end = currently_playing.get("data").get("end")
                    if time < start:
                        player.set_time(int(start*1000)+100)
                    elif end != 0 and time >= end:
                        player.pause()
                        play_next()
                    else:
                        set_light_round_number(str(format_seconds(round(get_youtube_duration(currently_playing.get("data")) - (time-start)))))
                else:
                    if not light_mode and (length - time) <= 8:
                        if (not is_title_window_up() or title_info_only) and auto_info_end:
                            toggle_title_popup(True)
                        if coming_up_queue:
                            toggle_coming_up_popup(True, title=coming_up_queue["title"], details=coming_up_queue["details"], image=coming_up_queue["image"], up_next=coming_up_queue["up_next"])
                            coming_up_queue = None
                    update_light_round(time)
                    apply_censors(time, length)
            update_progress_bar(projected_vlc_time, player.get_length(), currently_playing.get("filename"))
    except Exception as e:
        error_str = str(e)
        if not playing_next_error:
            if error_str == last_error:
                last_error_count += 1
                print(f"\rError: {error_str} x {last_error_count}", end='', flush=True)
            else:
                last_error = error_str
                last_error_count = 1
                if last_error_count > 20:
                    playing_next_error = True
                    play_next()
                print(f"\nError: {error_str} x 1", flush=True)
    root.after(SEEK_POLLING, update_seek_bar)

def format_seconds(seconds):
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f"{minutes:02}:{remaining_seconds:02}"

# =========================================
#            *COMING UP UI
# =========================================

coming_up_window = None  # Store the lightning round window
coming_up_title_label = None  # Store the label for the lightning round message
coming_up_rules_label = None
coming_up_queue = None

def toggle_coming_up_popup(show, title="", details="", image=None, up_next=True, queue=False):
    """Creates or destroys the lightning round announcement popup with an optional image."""
    global coming_up_window, coming_up_title_label, coming_up_rules_label, light_round_length, coming_up_queue

    if coming_up_window:
        screen_width = coming_up_window.winfo_screenwidth()
        window_width = coming_up_window.winfo_reqwidth()
        window_height = coming_up_window.winfo_reqheight()
        if not show and (title == "" or (coming_up_title_label and title != "" and title.lower() in coming_up_title_label.cget("text").lower())):
            coming_up_title_label.configure(text="")
            animate_window(coming_up_window, (screen_width - window_width) // 2, -window_height)

    if not show:
        if coming_up_queue:
            if title in coming_up_queue["title"]:
                coming_up_queue = None
        return
    if queue and player.is_playing():
        coming_up_queue = {
            "title": title,
            "details": details,
            "image": image,
            "up_next": up_next
        }
        return
    if not coming_up_window:
        coming_up_window = tk.Toplevel()
        coming_up_window.title("UP NEXT!")
        coming_up_window.overrideredirect(True)  # Remove window borders
        coming_up_window.attributes("-topmost", True)  # Keep it on top
        coming_up_window.wm_attributes("-alpha", 0.8)  # Semi-transparent background
    coming_up_window.configure(bg=OVERLAY_BACKGROUND_COLOR)

    # Title
    if not coming_up_title_label:
        coming_up_title_label = tk.Label(coming_up_window, font=("Arial", scl(40), "bold", "underline"))
        coming_up_title_label.pack(pady=(scl(10), 0), padx=scl(10))
    if up_next:
        title = "UP NEXT: " + title.upper() + "!"
    if title == coming_up_title_label.cget("text"):
        return
    coming_up_title_label.configure(text=title.upper(), fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR)

    # Details
    if not coming_up_rules_label:
        coming_up_rules_label = tk.Label(coming_up_window, font=("Arial", scl(20), "bold"), justify="center", wraplength=scl(1700))
        coming_up_rules_label.pack(pady=(scl(5), scl(10)))
    if image:
        coming_up_rules_label.configure(image=image, compound="top")
        coming_up_rules_label.image = image
    else:
        coming_up_rules_label.configure(image="")
        coming_up_rules_label.image = None
    coming_up_rules_label.configure(text=details, fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR)

    # Position at the top center of the screen
    coming_up_window.update_idletasks()
    screen_width = coming_up_window.winfo_screenwidth()
    window_width = coming_up_window.winfo_reqwidth()
    coming_up_window.geometry(f"+{(screen_width - window_width) // 2}+{-coming_up_window.winfo_reqheight()}")
    root.after(10, lambda: animate_window(coming_up_window, (screen_width - window_width) // 2, 20))

def format_slug(slug):
    """Converts OP/ED notation to full text format."""
    if slug.startswith("OP"):
        return f"Opening {slug[2:]}"
    elif slug.startswith("ED"):
        return f"Ending {slug[2:]}"
    return slug  # Return unchanged if it doesn't match

# =========================================
#            *PROGRESS BAR
# =========================================

# Global variable for the progress bar
progress_bar = None
progress_bar_enabled = True
def create_progress_bar(color="grey"):
    """Creates a thin progress bar at the bottom of the screen."""
    global progress_bar

    height = 10
    progress_bar = tk.Toplevel()
    progress_bar.title = "Progress Bar"
    progress_bar.overrideredirect(True)  
    progress_bar.attributes("-topmost", True)  
    progress_bar.wm_attributes("-alpha", 0.3)  
    progress_bar.configure(bg=color, width=0, height=height, highlightthickness=0)
    progress_bar.geometry(f"+{0}+{root.winfo_screenheight() - height}")  # Adjust for bottom spacing

def update_progress_bar(current_time, total_time, filename=None):
    global progress_bar

    if not progress_bar_enabled:
        if progress_bar:
            progress_bar.destroy()
            progress_bar = None
        return

    if not progress_bar:
        create_progress_bar()
        progress_bar.update_idletasks()
    
    """Updates the progress bar based on video time, accounting for skip censors."""
    if progress_bar and total_time > 0:
        # Calculate effective time excluding skip censors
        effective_current_time = current_time
        effective_total_time = total_time
        
        # Only adjust for skip censors if filename is provided
        if filename:
            try:
                if os.path.exists(CENSOR_JSON_FILE):
                    with open(CENSOR_JSON_FILE, "r") as f:
                        censor_data = json.load(f)
                    
                    file_censors = censor_data.get(filename, [])
                    
                    # Convert VLC times (milliseconds) to seconds for comparison with censor times
                    current_time_seconds = current_time / 1000.0
                    total_time_seconds = total_time / 1000.0
                    
                    # Calculate total skip duration and skip time before current position
                    total_skip_duration_seconds = 0
                    skip_duration_before_current_seconds = 0
                    
                    skip_censors = [c for c in file_censors if c.get("skip")]
                    
                    for censor in skip_censors:
                        skip_start = censor['start']
                        skip_end = censor['end']
                        skip_duration = skip_end - skip_start
                        
                        if skip_duration > 0:
                            total_skip_duration_seconds += skip_duration
                            
                            # If this skip segment is entirely before current time, subtract it
                            if skip_end <= current_time_seconds:
                                skip_duration_before_current_seconds += skip_duration
                            # If current time is within this skip segment, adjust partially
                            elif skip_start < current_time_seconds < skip_end:
                                skip_duration_before_current_seconds += (current_time_seconds - skip_start)
                    
                    # Calculate effective times in seconds, then convert back to milliseconds
                    effective_current_time_seconds = current_time_seconds - skip_duration_before_current_seconds
                    effective_total_time_seconds = total_time_seconds - total_skip_duration_seconds
                    
                    # Convert back to milliseconds for progress bar calculation
                    effective_current_time = effective_current_time_seconds * 1000
                    effective_total_time = effective_total_time_seconds * 1000
                    
            except Exception as e:
                # If there's any error loading censors, fall back to normal progress
                pass
        
        # Ensure we don't have negative or zero effective times
        if effective_total_time <= 0:
            effective_total_time = total_time
        if effective_current_time < 0:
            effective_current_time = 0
            
        screen_width = progress_bar.winfo_screenwidth()
        progress_width = int((effective_current_time / effective_total_time) * screen_width)
        height = progress_bar.winfo_height()
        progress_bar.configure(width=progress_width)
        progress_bar.geometry(f"+{0}+{root.winfo_screenheight() - height}")  # Adjust for bottom spacing

# =========================================
#            *BLIND SCREEN
# =========================================

black_overlay = None
blind_enabled = False
manual_blind = False
def blind(manual = False):
    """Toggle black screen"""
    global black_overlay, manual_blind
    if black_overlay is None:  # Create black overlay if it doesn't exist
        manual_blind = manual
        set_black_screen(True)
    else:  # Destroy the black overlay to reveal VLC
        manual_blind = False
        toggle_mute(False, True)
        set_black_screen(False)
        set_progress_overlay(destroy=True)

def set_black_screen(toggle, smooth=True):
    global black_overlay
    button_seleted(blind_button, toggle)
    if toggle:
        if black_overlay is None:  # Create black overlay if it doesn't exist
            black_overlay = tk.Toplevel()
            # black_overlay.attributes("-fullscreen", True)
            black_overlay.overrideredirect(True)  # Remove window borders
            black_overlay.configure(bg=get_image_color())
            black_overlay.attributes("-topmost", True)
            black_overlay.bind("<Escape>", lambda e: blind())  # Escape to close
            
            # Get screen dimensions
            screen_width = black_overlay.winfo_screenwidth()
            screen_height = black_overlay.winfo_screenheight()

            if smooth:
                # Start offscreen on the left
                black_overlay.update_idletasks()  
                black_overlay.geometry(f"{screen_width}x{screen_height}+{-screen_width}+0")
                black_overlay.update_idletasks()  
                animate_window(black_overlay, 0, 0, steps=20, delay=5, bounce=False, fade=None)  # Animate to center
                root.after(600, set_blind_enabled, toggle)
            else:
                black_overlay.geometry(f"{screen_width}x{screen_height}+0+0")
                set_blind_enabled(True)
    else:
        if black_overlay:  # Destroy the black overlay smoothly
            if smooth:
                screen_width = black_overlay.winfo_screenwidth()
                screen_height = black_overlay.winfo_screenheight()
                animate_window(black_overlay, screen_width, 0, steps=20, delay=5, bounce=False, fade=None, destroy=True)
            else:
                black_overlay.destroy()
            black_overlay = None
        set_blind_enabled(False)
    root.after(100, configure_style)

def set_blind_enabled(toggle):
    global blind_enabled, manual_blind
    if toggle and not black_overlay:
        toggle = False
    blind_enabled = toggle
    if not toggle:
        manual_blind = False

def black_while_loading(toggle):
    if toggle:
        global black_overlay
        set_black_screen(True)
        black_overlay.attributes("-topmost", False)
    else:
        set_black_screen(False)

blind_round_toggle = False
def toggle_blind_round():
    global blind_round_toggle
    blind_round_toggle = not blind_round_toggle
    button_seleted(blind_round_button, blind_round_toggle)
    if blind_round_toggle:
        if peek_round_toggle:
            toggle_peek_round()
        if mute_peek_round_toggle:
            toggle_mute_peek_round()
            
        if special_round_warning:
            toggle_coming_up_popup(True, "Blind Round", "Guess the anime from just the music.\nNormal rules apply.", queue=True)
    else:
        toggle_coming_up_popup(False, "Blind Round")

# =========================================
#              *BLACK DESKTOP
# =========================================

desktop_black_overlay = None

def toggle_desktop_black_overlay(toggle=None):
    global desktop_black_overlay
    if toggle is None:
        toggle = desktop_black_overlay is None
    if toggle:
        if desktop_black_overlay and desktop_black_overlay.winfo_exists():
            desktop_black_overlay.destroy()
        desktop_black_overlay = tk.Toplevel()
        desktop_black_overlay.overrideredirect(True)
        desktop_black_overlay.configure(bg="black")
        desktop_black_overlay.attributes("-topmost", False)  # Push to back
        desktop_black_overlay.lower()  # Lower below other windows

        # Set geometry to cover the entire screen
        screen_w = desktop_black_overlay.winfo_screenwidth()
        screen_h = desktop_black_overlay.winfo_screenheight()
        desktop_black_overlay.geometry(f"{screen_w}x{screen_h}+0+0")
    else:
        if desktop_black_overlay and desktop_black_overlay.winfo_exists():
            desktop_black_overlay.destroy()
            desktop_black_overlay = None
    button_seleted(desktop_black_button, desktop_black_overlay)

# =========================================
#              *CENSOR BOXES
# =========================================

censor_list = {}
other_censor_lists = []
censors_enabled = True

censor_boxes = {}
def toggle_censor_box(filename, censor, enabled):
    censor_id = f"{filename}:{censor['pos_x']}x{censor['pos_y']}--{censor['size_w']}x{censor['size_h']}-{censor['start']}-{censor['end']}"
    if censor_id in censor_boxes and censor_boxes[censor_id] and censor_boxes[censor_id].get("box") and censor_boxes[censor_id].get("box").winfo_exists():
        if not enabled:
            censor_boxes[censor_id]["box"].destroy()
            del censor_boxes[censor_id]
    elif enabled:
        censor_box = tk.Toplevel()
        censor_box.configure(bg="black")
        censor_box.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}")
        censor_box.overrideredirect(True)
        censor_box.attributes("-topmost", True)
        censor_boxes[censor_id] = {
            "box": censor_box,
            "used": True
        }
        root.after(100, lift_peek)
        root.after(100, lift_windows)
        if censor_editor:
            censor_editor.attributes("-topmost", True)
    return censor_boxes.get(censor_id)

def lift_peek():
    for p in [peek_overlay1, peek_overlay2]:
        if p:
            p.lift()

def remove_all_censor_boxes(filename=None):
    censors_to_delete = []
    for censor_id, box_data in censor_boxes.items():
        if not filename or filename not in censor_id:
            box = box_data.get("box")
            if box and box.winfo_exists():
                box.destroy()
            censors_to_delete.append(censor_id)
    for censor_id in censors_to_delete:
        del censor_boxes[censor_id]

def load_censors():
    global censor_list, other_censor_lists

    # Load main censor file
    if os.path.exists(CENSOR_JSON_FILE):
        with open(CENSOR_JSON_FILE, "r") as a:
            censor_list = json.load(a)
            print(f"Loaded censors for {len(censor_list)} files...")

    # Load other censor-related files in the same directory
    folder = os.path.dirname(CENSOR_JSON_FILE)
    basename = os.path.basename(CENSOR_JSON_FILE)
    if os.path.exists(folder):
        for fname in os.listdir(folder):
            if (
                "censor" in fname.lower()
                and fname.endswith(".json")
                and fname != basename
            ):
                try:
                    with open(os.path.join(folder, fname), "r") as f:
                        data = json.load(f)
                        other_censor_lists.append(data)
                        print(f"Loaded {len(data)} entries from {fname}")
                except Exception as e:
                    print(f"Failed to load {fname}: {e}")

load_censors()

censor_used = False
mute_censor_used = False
pre_censor = False
def apply_censors(time, length):
    """"Apply Censors"""
    global censor_used, mute_censor_used, pre_censor
    global censor_list
    global censors_enabled
    if censors_enabled and not mismatch_visuals and not currently_streaming:
        check_file_censors(currently_playing.get('filename'), time, False, not pre_censor)
        if not video_stopped and length - time <= 0.3 and playlist["current_index"]+1 < len(playlist["playlist"]) and check_file_censors(get_clean_filename(playlist["playlist"][playlist["current_index"]+1]), time, True, auto_info_start):
            pre_censor = True
        else:
            remove_all_censor_boxes(filename=currently_playing.get('filename'))
    else:
        remove_all_censor_boxes()
        if mute_censor_used:
            player.audio_set_mute(disable_video_audio)
            mute_censor_used = False

def get_file_censors(filename):
    filenames = [filename, filename.replace(".mp4", ".webm")]
    for f in filenames:
        file_censors = censor_list.get(f)
        if not file_censors:
            for c_list in other_censor_lists:
                other_file_censors = c_list.get(f)
                if other_file_censors:
                    return other_file_censors
        else:
            return file_censors
    return []

def check_file_censors(filename, time, video_end, check_title=True):
    global censor_used, mute_censor_used
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    file_censors = get_file_censors(filename)
    censor_found = False
    mute_found = False
    if file_censors:
        for censor in file_censors:
            if (not blind_enabled or censor.get("mute")) and (not check_title or not is_title_window_up() or censor.get("nsfw") or censor.get("skip")) and ((video_end and censor['start'] == 0) or (time >= censor['start'] and time <= censor['end'])):
                if censor.get("skip"):
                    skip_length = censor['end'] - censor['start']
                    if not light_round_started and time < censor['start']+(skip_length / 4):
                        if censor['end'] < player.get_length()/1000:
                            player.set_time(int(censor['end'] * 1000))
                        else:
                            play_next()
                    censor_found = True
                elif not censor.get("mute"):
                    censor_box = toggle_censor_box(filename, censor, True)["box"]
                    censor_box.geometry(str(int(screen_width*(censor['size_w']/100))) + "x" + str(int(screen_height*(censor['size_h']/100))))
                    censor_box.configure(bg=(censor.get("color") or get_image_color()))
                    set_window_position(censor_box, censor['pos_x'], censor['pos_y'])
                else:
                    player.audio_set_mute(True)
                    mute_censor_used = True
                    mute_found = True
                censor_found = True
            elif not (censor.get("mute") or censor.get("skip")):
                toggle_censor_box(filename, censor, False)

    if not censor_found and censor_editor:
        censor_editor.attributes("-topmost", False)

    if not mute_found and not light_round_started and mute_censor_used:
        player.audio_set_mute(disable_video_audio)
        mute_censor_used = False

    return censor_found

def lift_windows():
    if root.attributes("-topmost"):
        root.lift()
    for window in [title_window, progress_bar, coming_up_window, character_image_overlay, censor_editor]:
        if window:
            window.lift()

def set_window_position(window, pos_x, pos_y):
    """Moves the Tkinter root window to the bottom-left corner with accurate positioning."""
    root.update_idletasks()  # Ensure correct window size calculations

    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    window_width = window.winfo_width()
    window_height = window.winfo_height()

    y_position = (screen_height - window_height)*(pos_y/100)
    x_position = (screen_width - window_width)*(pos_x/100)

    y_position = int(max(0, y_position))
    x_position = int(max(0, x_position))

    # Set exact position (left edge at x=0)
    window.geometry(f"+{x_position}+{y_position}")

camera = None
camera_init_attempts = 0
camera_disabled = False  # Flag to disable camera permanently if too many errors
camera_error_count = 0  # Count COM/access errors
MAX_CAMERA_INIT_ATTEMPTS = 3
CAMERA_DISABLE_THRESHOLD = 5  # Disable camera after this many errors

def initialize_camera():
    global camera, camera_init_attempts
    
    try:
        if camera is not None:
            try:
                camera.stop()
                time.sleep(0.05)  # Brief pause for cleanup
            except:
                pass
            camera = None
        
        # Create new camera with fallback options
        try:
            # Try with explicit device parameters first
            camera = dxcam.create(device_idx=0, output_idx=0)
        except:
            try:
                # Fallback to default parameters
                camera = dxcam.create()
            except Exception as create_err:
                raise Exception(f"Failed to create DXCam object: {create_err}")
        
        if camera is None:
            raise Exception("DXCam create() returned None")
            
        camera.start(target_fps=30)
        camera_init_attempts = 0
        return True
        
    except Exception as e:
        print(f"DXCam initialization failed (attempt {camera_init_attempts + 1}): {e}")
        camera_init_attempts += 1
        camera = None
        return False

# Initialize camera with retry logic
for _ in range(MAX_CAMERA_INIT_ATTEMPTS):
    if initialize_camera():
        break
    time.sleep(1)

def get_image_color():
    global camera, camera_init_attempts, camera_disabled, camera_error_count
    
    # Fallback color if camera fails
    fallback_color = "#000000"
    
    # Don't try to use camera if permanently disabled
    if camera_disabled:
        return fallback_color
    
    try:
        if camera is None:
            if camera_init_attempts < MAX_CAMERA_INIT_ATTEMPTS:
                if not initialize_camera():
                    return fallback_color
            else:
                return fallback_color
        
        img = camera.get_latest_frame()
        if img is None:
            raise Exception("Failed to capture frame")
            
        im_arr = np.array(img)
        l = im_arr.shape[0] * im_arr.shape[1]
        if l == 0:
            return fallback_color
            
        r, g, b = im_arr[:,:,0].sum()/l, im_arr[:,:,1].sum()/l, im_arr[:,:,2].sum()/l
        average_color = rgbtohex(int(r), int(g), int(b))
        return average_color
        
    except (OSError, Exception) as e:
        # Handle COM errors and other DXCam errors
        error_msg = str(e).lower()
        
        if any(keyword in error_msg for keyword in ["keyed mutex", "com error", "access violation", "comtypes"]):
            camera_error_count += 1
            
            # Disable camera permanently if too many COM errors
            if camera_error_count >= CAMERA_DISABLE_THRESHOLD:
                camera_disabled = True
                print(f"DXCam disabled after {camera_error_count} COM errors. Background color will use fallback.")
                return fallback_color
            
            print(f"DXCam COM/mutex error detected ({camera_error_count}/{CAMERA_DISABLE_THRESHOLD}), reinitializing camera...")
            camera_init_attempts = 0  # Reset attempt counter for COM errors
            
            if initialize_camera():
                try:
                    img = camera.get_latest_frame()
                    if img is not None:
                        im_arr = np.array(img)
                        l = im_arr.shape[0] * im_arr.shape[1]
                        if l > 0:
                            r, g, b = im_arr[:,:,0].sum()/l, im_arr[:,:,1].sum()/l, im_arr[:,:,2].sum()/l
                            return rgbtohex(int(r), int(g), int(b))
                except:
                    pass
        else:
            print(f"DXCam capture error: {e}")
        
        return fallback_color

def rgbtohex(r,g,b):
    return f'#{r:02x}{g:02x}{b:02x}'

def update_censor_button_count():
    censors_num = len(get_file_censors(currently_playing.get("filename","")))
    toggle_censor_bar_button.configure(text=f"[C]ENSOR({censors_num})")
    if popout_buttons_by_name.get(toggle_censor_bar_button):
        popout_buttons_by_name.get(toggle_censor_bar_button).configure(text=f"CENSORS({censors_num})")

class RectangleDrawerOverlay:
    def __init__(self, on_rectangle_picked):
        self.on_rectangle_picked = on_rectangle_picked
        self.root = tk.Toplevel()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(cursor="cross")

        self.canvas = tk.Canvas(self.root, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<ButtonRelease-2>", lambda e: self.root.destroy())

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="red", width=2)

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        end_x, end_y = event.x, event.y
        width = abs(end_x - self.start_x)
        height = abs(end_y - self.start_y)

        left_edge = min(self.start_x, end_x)
        top_edge = min(self.start_y, end_y)

        x_percent = (left_edge / (self.screen_width - width)) * 100
        y_percent = (top_edge / (self.screen_height - height)) * 100
        width_percent = width / self.screen_width * 100
        height_percent = height / self.screen_height * 100

        x_percent = self.edge_round(x_percent)
        y_percent = self.edge_round(y_percent)
        width_percent = self.edge_round(width_percent)
        height_percent = self.edge_round(height_percent)

        result = f"{width_percent:.2f}x{height_percent:.2f},{x_percent:.2f}x{y_percent:.2f}"
        pyperclip.copy(result)

        self.on_rectangle_picked(result)
        self.root.destroy()

    def edge_round(self, position):
        if position < 1:
            return 0
        elif position > 99:
            return 100
        return position

class ColorPickerOverlay:
    def __init__(self, on_color_picked):
        self.on_color_picked = on_color_picked
        self.root = tk.Toplevel()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(cursor="cross", bg="black")

        self.root.bind("<Button-1>", self.on_click)
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<ButtonRelease-2>", lambda e: self.root.destroy())

    def on_click(self, event):
        self.root.attributes("-alpha", 0.0)
        self.root.update()

        color = pyautogui.screenshot().getpixel((event.x_root, event.y_root))
        hex_color = '#{:02X}{:02X}{:02X}'.format(*color)
        pyperclip.copy(hex_color)

        self.on_color_picked(hex_color)
        self.root.after(100, self.root.destroy)

def extract_title_and_slug_from_filename(filename):
    """Extracts the title part, slug, and version from an anime filename."""
    try:
        parts = filename.split("-")
        if len(parts) >= 2:
            title_part = parts[0]  # First part is the title
            
            # Try to get slug and version from metadata first, fallback to filename parsing
            file_data = get_file_metadata_by_name(filename)
            if file_data and file_data.get('slug'):
                slug = file_data['slug']
                version = file_data.get('version')
            else:
                slug = parts[1].split(".")[0].split("v")[0]  # Fallback to filename parsing
                # Try to extract version from filename if available
                version_part = parts[1].split(".")[0]
                if "v" in version_part:
                    version = version_part.split("v")[1] if len(version_part.split("v")) > 1 else None
                else:
                    version = None
            
            return title_part, slug, version
    except:
        pass
    return None, None, None

def find_similar_theme_censors(current_filename):
    """Finds censors from files with the same title and slug but different versions/quality."""
    current_title, current_slug, current_version = extract_title_and_slug_from_filename(current_filename)
    
    if not current_title or not current_slug:
        return {}
    
    similar_censors = {}
    
    # Check main censor list
    for filename, censors in censor_list.items():
        if filename == current_filename:
            continue  # Skip current file
            
        title, slug, version = extract_title_and_slug_from_filename(filename)
        if title == current_title and slug == current_slug:
            similar_censors[filename] = censors
    
    # Check other censor lists
    for c_list in other_censor_lists:
        for filename, censors in c_list.items():
            if filename == current_filename:
                continue
                
            title, slug, version = extract_title_and_slug_from_filename(filename)
            if title == current_title and slug == current_slug:
                similar_censors[filename] = censors
    
    return similar_censors

current_censors = {}
censor_editor = None
censor_entry_widgets = []
def open_censor_editor(refresh=False):
    global current_censors, censor_editor, censor_entry_widgets
    
    # Pagination variables
    global censor_page_offset
    if 'censor_page_offset' not in globals():
        censor_page_offset = 0
    
    CENSORS_PER_PAGE = 15
    
    def censor_editor_close():
        global censor_editor, censor_entry_widgets, censor_page_offset
        button_seleted(edit_censors_button, False)
        edit_censors_button.configure(text="➕")
        censor_entry_widgets = []
        censor_page_offset = 0
        censor_editor.destroy()
        censor_editor = None

    filename = currently_playing.get("filename")
    if filename:
        current_censors = copy.deepcopy(get_file_censors(filename))
    button_seleted(edit_censors_button, True)
    edit_censors_button.configure(text="❌")

    font_big = ("Arial", 14)
    fg_color = "white"
    bg_color = "black"

    if censor_editor:
        if not refresh:
            censor_editor_close()
            return
    else:
        censor_editor = tk.Toplevel()
        censor_editor.configure(bg=BACKGROUND_COLOR)
        censor_editor.protocol("WM_DELETE_WINDOW", censor_editor_close)
        x = root.winfo_x()
        y = root.winfo_y()
        censor_editor.update_idletasks()
        censor_editor.geometry(f"+{x}+{y}")
        
    # Create header and pagination controls
    def create_header_with_pagination():
        # Clear existing header and pagination widgets
        for widget in censor_editor.winfo_children():
            row = int(widget.grid_info().get("row", -1))
            if row in [0, 1]:  # Pagination and header rows
                widget.destroy()
        
        # Add pagination controls at top (only if more than one page)
        total_censors = len(current_censors) if current_censors else 0
        total_pages = (total_censors + CENSORS_PER_PAGE - 1) // CENSORS_PER_PAGE if total_censors > 0 else 1
        
        header_row = 0
        if total_pages > 1:
            current_page = (censor_page_offset // CENSORS_PER_PAGE) + 1
            
            # Previous button
            prev_btn = tk.Button(censor_editor, text="◀ PREV", font=font_big, bg=bg_color, fg=fg_color, 
                                command=lambda: page_prev(), state="normal" if current_page > 1 else "disabled")
            prev_btn.grid(row=0, column=0, padx=4, pady=6)
            
            # Page info
            page_label = tk.Label(censor_editor, text=f"Page {current_page}/{total_pages} ({total_censors} total)", 
                                font=font_big, bg=BACKGROUND_COLOR, fg=fg_color)
            page_label.grid(row=0, column=1, columnspan=5, padx=8, pady=6)
            
            # Next button
            next_btn = tk.Button(censor_editor, text="NEXT ▶", font=font_big, bg=bg_color, fg=fg_color,
                                command=lambda: page_next(), state="normal" if current_page < total_pages else "disabled")
            next_btn.grid(row=0, column=6, columnspan=2, padx=4, pady=6)
            
            header_row = 1
        
        # Column headers
        headers = ["SIZE", "POSITION", "START", "END", "COLOR", "NSFW", "ACTIONS"]
        for col, header in enumerate(headers):
            tk.Label(censor_editor, text=header, font=font_big, bg=BACKGROUND_COLOR, fg=fg_color).grid(row=header_row, column=col, padx=8, pady=6)
    
    def page_prev():
        global censor_page_offset
        if censor_page_offset >= CENSORS_PER_PAGE:
            censor_page_offset -= CENSORS_PER_PAGE
            refresh_ui()
    
    def page_next():
        global censor_page_offset
        total_censors = len(current_censors)
        if censor_page_offset + CENSORS_PER_PAGE < total_censors:
            censor_page_offset += CENSORS_PER_PAGE
            refresh_ui()
    
    create_header_with_pagination()
        
    censor_editor.title(f"Censor Editor for {filename}")

    def current_time_func():
        return projected_vlc_time / 1000

    def pick_color_func(label):
        def set_color(hex_color):
            label.config(bg=hex_color, text="")
        ColorPickerOverlay(set_color)
        save_to_current()

    def pick_target_func(size_var, pos_var):
        def set_target(rect_text):
            try:
                size_part, pos_part = rect_text.split(",")
                size_var.set(size_part)
                pos_var.set(pos_part)
            except Exception as e:
                print("Failed to parse rectangle:", e)
        RectangleDrawerOverlay(set_target)

    def save_censor_func():
        global censor_list
        censor_list[filename] = current_censors
        with open(CENSOR_JSON_FILE, "w") as f:
            json.dump(censor_list, f, indent=4)
        update_censor_button_count()

    def refresh_ui():
        global current_censors, censor_page_offset
        for widgets in censor_entry_widgets:
            for widget in widgets:
                widget.destroy()
        censor_entry_widgets.clear()

        current_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))
        
        # Calculate pagination
        total_censors = len(current_censors)
        total_pages = (total_censors + CENSORS_PER_PAGE - 1) // CENSORS_PER_PAGE if total_censors > 0 else 1
        current_page = (censor_page_offset // CENSORS_PER_PAGE) + 1
        
        # Ensure page offset is within bounds
        if censor_page_offset >= total_censors and total_censors > 0:
            censor_page_offset = max(0, total_censors - CENSORS_PER_PAGE)
        
        # Get censors for current page
        start_idx = censor_page_offset
        end_idx = min(start_idx + CENSORS_PER_PAGE, total_censors)
        page_censors = current_censors[start_idx:end_idx]

        # Calculate starting row for censors (depends on whether pagination is shown)
        total_censors = len(current_censors)
        total_pages = (total_censors + CENSORS_PER_PAGE - 1) // CENSORS_PER_PAGE if total_censors > 0 else 1
        censor_start_row = 2 if total_pages > 1 else 1

        for display_idx, censor in enumerate(page_censors):
            actual_idx = start_idx + display_idx
            
            row_widgets = []

            # Frame for Size
            size_frame = tk.Frame(censor_editor, bg=BACKGROUND_COLOR)
            if not censor.get("mute") and not censor.get("skip"):
                size_var = tk.StringVar(value=f"{censor['size_w']}x{censor['size_h']}")
                pos_var = tk.StringVar(value=f"{censor['pos_x']}x{censor['pos_y']}")
                size_entry = tk.Entry(size_frame, textvariable=size_var, width=12, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color)
                size_entry.pack(side="left")
                tk.Button(size_frame, text="🎯", width=3, font=font_big, bg=bg_color, fg=fg_color, command=lambda sv=size_var, pv=pos_var: pick_target_func(sv, pv)).pack(side="left")
            size_frame.grid(row=display_idx+censor_start_row, column=0, padx=(6, 0), pady=4)

            # Frame for Position
            pos_frame = tk.Frame(censor_editor, bg=BACKGROUND_COLOR)
            if not censor.get("mute") and not censor.get("skip"):
                pos_entry = tk.Entry(pos_frame, textvariable=pos_var, width=12, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color)
                pos_entry.pack(side="left")
            pos_frame.grid(row=display_idx+censor_start_row, column=1, padx=(0, 6), pady=4)

            # Frame for Start and End Times
            def build_time_frame(var, row, col, back_color):
                frame = tk.Frame(censor_editor, bg=back_color)
                tk.Button(frame, text="-", width=3, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(v.get() - 0.1, 1))).pack(side="left")
                tk.Entry(frame, textvariable=var, width=6, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color).pack(side="left")
                tk.Button(frame, text="+", width=3, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(v.get() + 0.1, 1))).pack(side="left")
                tk.Button(frame, text="NOW", width=5, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(current_time_func(), 1))).pack(side="left")
                frame.grid(row=row, column=col, padx=6, pady=4)
                return frame

            start_var = tk.DoubleVar(value=censor['start'])
            end_var = tk.DoubleVar(value=censor['end'])
            start_frame = build_time_frame(start_var, display_idx+censor_start_row, 2, BACKGROUND_COLOR)
            if censor['end']:
                row_color = BACKGROUND_COLOR
            else:
                row_color = "white"
            end_frame = build_time_frame(end_var, display_idx+censor_start_row, 3, row_color)

            # Frame for Color and Buttons
            def remove_color(label):
                label.config(bg="#333", text="AUTO")
                save_to_current()

            color_frame = tk.Frame(censor_editor, bg=BACKGROUND_COLOR)
            if censor.get("mute"):
                mute_label = tk.Label(color_frame, text="MUTE CENSOR", width=16, font=font_big, justify="center", bg=bg_color, fg=fg_color, highlightbackground="white", highlightthickness=2)
                mute_label.pack(side="left")
            elif censor.get("skip"):
                skip_label = tk.Label(color_frame, text="SKIP CENSOR", width=16, font=font_big, justify="center", bg=bg_color, fg=fg_color, highlightbackground="white", highlightthickness=2)
                skip_label.pack(side="left")
            else:
                color = censor.get("color")
                color_box = tk.Label(color_frame, text="AUTO" if not color else "", width=8, font=font_big, bg=color if color else "#333", fg=fg_color, relief="groove")
                color_box.pack(side="left")
                tk.Button(color_frame, text="PICK", width=5, font=font_big, bg=bg_color, fg=fg_color, command=lambda b=color_box: pick_color_func(b)).pack(side="left", padx=2)
                tk.Button(color_frame, text="X", width=2, font=font_big, bg=bg_color, fg=fg_color, command=lambda c=color_box: remove_color(c)).pack(side="left")
            color_frame.grid(row=display_idx+censor_start_row, column=4, padx=6, pady=4)

            # NSFW Toggle Button
            def add_nsfw_toggle_button(censor, parent, row, column=5):
                nsfw_var = censor.get("nsfw")

                def toggle_nsfw():
                    nsfw_button.var = not nsfw_button.var
                    update_nsfw_button()

                def update_nsfw_button():
                    if nsfw_button.var:
                        nsfw_button.config(text="✗ NSFW", bg="#880000")
                    else:
                        nsfw_button.config(text="✓ SFW", bg="#444444")

                nsfw_button = tk.Button(parent, text="", command=toggle_nsfw, font=font_big, width=8, height=1, fg="white", activeforeground="white", activebackground="#333", bd=0, relief="flat", bg="#444444")
                nsfw_button.grid(row=row, column=column, padx=6, pady=4)
                nsfw_button.var = nsfw_var  # Optional, to match original 

                update_nsfw_button()
                return nsfw_button
            
            nsfw_button = add_nsfw_toggle_button(censor, censor_editor, row=display_idx+censor_start_row)

            # Test Button with left/right click functionality
            test_button = tk.Button(censor_editor, text="▶TEST", command=lambda c=actual_idx: test_censor_playback(c), font=font_big, bg="#226622", fg="white", activebackground="#2a8a2a", bd=0, relief="raised", width=6)
            test_button.grid(row=display_idx+censor_start_row, column=6, padx=6, pady=4)
            # Bind right-click to test from end time
            test_button.bind("<Button-3>", lambda event, c=actual_idx: test_censor_playback_from_end(c))
            delete_button = tk.Button(censor_editor, text="DELETE", bg=bg_color, fg="red", width=8, font=font_big, command=lambda i=actual_idx: delete_censor(i))
            delete_button.grid(row=display_idx+censor_start_row, column=7, padx=6, pady=4)
            row_widgets.extend([size_frame, pos_frame, start_frame, end_frame, color_frame, nsfw_button, delete_button, test_button])
            censor_entry_widgets.append(row_widgets)
        
        # Update header with current pagination info
        if len(current_censors) > CENSORS_PER_PAGE:
            create_header_with_pagination()
        
        # Refresh the bottom buttons (especially import button state)
        create_bottom_buttons()

    def test_censor_playback(censor, from_end=False):
        save_to_current()
        try:
            if from_end:
                end = float(current_censors[censor].get("end", 0))
                if end > 0:
                    # Go back 1 second from end time, minimum 0
                    test_time = max(0, (end - 1) * 1000)
                else:
                    # If no end time, use start time
                    test_time = max(0, (float(current_censors[censor].get("start", 0)) - 1) * 1000)
            else:
                start = float(current_censors[censor].get("start", 0))
                test_time = max(0, (start - 1) * 1000)  # Go back 1 second, minimum 0
            
            player.set_time(int(test_time))
            player.play()
        except Exception as e:
            print(f"Error playing censor preview: {e}")

    def test_censor_playback_from_end(censor):
        test_censor_playback(censor, from_end=True)

    def delete_censor(index):
        if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this censor?"):
            global censor_page_offset
            save_to_current()
            del current_censors[index]
            
            # Adjust page offset if necessary after deletion
            total_censors = len(current_censors)
            if total_censors > 0:
                max_offset = ((total_censors - 1) // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
                if censor_page_offset > max_offset:
                    censor_page_offset = max_offset
            else:
                censor_page_offset = 0
            
            refresh_ui()

    def add_new_censor():
        global censor_page_offset
        save_to_current()
        new_censor = {
            "size_w": 100.00, "size_h": 100.00,
            "pos_x": 0.0, "pos_y": 0.0,
            "start": round(current_time_func(), 1), "end": 0.0,
            "color": None, "nsfw": False
        }
        current_censors.append(new_censor)
        
        # Sort censors to find where the new one will be positioned
        sorted_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))
        
        # Find the index of the new censor in the sorted list
        new_censor_index = None
        for i, censor in enumerate(sorted_censors):
            if (censor["start"] == new_censor["start"] and 
                censor["end"] == new_censor["end"] and 
                censor.get("size_w") == new_censor.get("size_w") and
                censor.get("pos_x") == new_censor.get("pos_x")):
                new_censor_index = i
                break
        
        # Navigate to the page containing the new censor
        if new_censor_index is not None:
            target_page_offset = (new_censor_index // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
            censor_page_offset = target_page_offset
        
        refresh_ui()

    def add_new_mute():
        global censor_page_offset
        save_to_current()
        new_censor = {
            "mute":True,
            "start": round(current_time_func(), 1), "end": 0.0,
            "nsfw": False
        }
        current_censors.append(new_censor)
        
        # Sort censors to find where the new one will be positioned
        sorted_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))
        
        # Find the index of the new censor in the sorted list
        new_censor_index = None
        for i, censor in enumerate(sorted_censors):
            if (censor["start"] == new_censor["start"] and 
                censor["end"] == new_censor["end"] and 
                censor.get("mute") == True):
                new_censor_index = i
                break
        
        # Navigate to the page containing the new censor
        if new_censor_index is not None:
            target_page_offset = (new_censor_index // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
            censor_page_offset = target_page_offset
        
        refresh_ui()

    def add_new_skip():
        global censor_page_offset
        save_to_current()
        new_censor = {
            "skip": True,
            "start": round(current_time_func(), 1), "end": 0.0,
            "nsfw": False
        }
        current_censors.append(new_censor)
        
        # Sort censors to find where the new one will be positioned
        sorted_censors = sorted(current_censors, key=lambda c: (c["start"], c["end"]))
        
        # Find the index of the new censor in the sorted list
        new_censor_index = None
        for i, censor in enumerate(sorted_censors):
            if (censor["start"] == new_censor["start"] and 
                censor["end"] == new_censor["end"] and 
                censor.get("skip") == True):
                new_censor_index = i
                break
        
        # Navigate to the page containing the new censor
        if new_censor_index is not None:
            target_page_offset = (new_censor_index // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
            censor_page_offset = target_page_offset
        
        refresh_ui()

    def save_to_current():
        for display_i, widgets in enumerate(censor_entry_widgets):
            try:
                # Map display index to actual index in current_censors
                actual_i = censor_page_offset + display_i
                if actual_i >= len(current_censors):
                    continue
                    
                if current_censors[actual_i].get("mute", False):
                    current_censors[actual_i] = {
                        "mute": True,
                        "start": float(widgets[2].winfo_children()[1].get()),
                        "end": float(widgets[3].winfo_children()[1].get()),
                        "nsfw": widgets[5].var
                    }
                elif current_censors[actual_i].get("skip", False):
                    current_censors[actual_i] = {
                        "skip": True,
                        "start": float(widgets[2].winfo_children()[1].get()),
                        "end": float(widgets[3].winfo_children()[1].get()),
                        "nsfw": widgets[5].var
                    }
                else:
                    size_parts = widgets[0].winfo_children()[0].get().split("x")
                    pos_parts = widgets[1].winfo_children()[0].get().split("x")
                    current_censors[actual_i] = {
                        "size_w": float(size_parts[0]),
                        "size_h": float(size_parts[1]),
                        "pos_x": float(pos_parts[0]),
                        "pos_y": float(pos_parts[1]),
                        "start": float(widgets[2].winfo_children()[1].get()),
                        "end": float(widgets[3].winfo_children()[1].get()),
                        "color": widgets[4].winfo_children()[0].cget("bg") if widgets[4].winfo_children()[0].cget("text") != "AUTO" else None,
                        "nsfw": widgets[5].var
                    }
            except Exception as e:
                messagebox.showerror("Save Error", f"Error saving row {display_i+1}: {e}")
                return

    def save_all():
        save_to_current()
        save_censor_func()
        save_censors_button.configure(text="SAVED!")
        root.after(300, lambda: save_censors_button.configure(text="SAVE CENSOR(S)"))
        remove_all_censor_boxes()
        apply_censors(player.get_time()/1000, player.get_length()/1000)

    def import_previous_censors():
        """Import censors from previous versions of the same theme."""
        similar_censors = find_similar_theme_censors(filename)
        if not similar_censors:
            messagebox.showinfo("No Similar Censors", "No censors found from previous versions of this theme.")
            return
        
        # If multiple similar files exist, let user choose
        if len(similar_censors) > 1:
            options = list(similar_censors.keys())
            choice = simpledialog.askstring(
                "Choose Source", 
                f"Multiple versions found. Enter the number of the file to import from:\n" + 
                "\n".join([f"{i+1}. {fname}" for i, fname in enumerate(options)]) + 
                f"\n\nEnter 1-{len(options)}:"
            )
            try:
                choice_index = int(choice) - 1
                if 0 <= choice_index < len(options):
                    source_filename = options[choice_index]
                else:
                    return
            except (ValueError, TypeError):
                return
        else:
            source_filename = list(similar_censors.keys())[0]
        
        # Import the censors
        imported_censors = copy.deepcopy(similar_censors[source_filename])
        current_censors.extend(imported_censors)
        
        # Go to last page to show imported censors
        global censor_page_offset
        total_censors = len(current_censors)
        last_page_offset = ((total_censors - 1) // CENSORS_PER_PAGE) * CENSORS_PER_PAGE
        censor_page_offset = last_page_offset
        
        # Refresh the UI to show imported censors
        refresh_ui()

    # Keep track of bottom buttons so we can clear them
    bottom_button_widgets = []
    
    def create_bottom_buttons():
        nonlocal bottom_button_widgets
        
        # Clear existing bottom buttons
        for widget in bottom_button_widgets:
            widget.destroy()
        bottom_button_widgets.clear()
        
        # Create standard buttons
        add_censor_btn = tk.Button(censor_editor, text="ADD NEW CENSOR", width=26, font=font_big, bg=bg_color, fg=fg_color, command=add_new_censor)
        add_censor_btn.grid(row=999, column=0, columnspan=2, pady=12)
        bottom_button_widgets.append(add_censor_btn)
        
        add_mute_btn = tk.Button(censor_editor, text="ADD NEW MUTE", width=18, font=font_big, bg=bg_color, fg=fg_color, command=add_new_mute)
        add_mute_btn.grid(row=999, column=2, columnspan=1, pady=12)
        bottom_button_widgets.append(add_mute_btn)
        
        add_skip_btn = tk.Button(censor_editor, text="ADD NEW SKIP", width=18, font=font_big, bg=bg_color, fg=fg_color, command=add_new_skip)
        add_skip_btn.grid(row=999, column=3, columnspan=1, pady=12)
        bottom_button_widgets.append(add_skip_btn)
        
        global save_censors_button
        save_censors_button = tk.Button(censor_editor, text="SAVE CENSOR(S)", width=19, font=font_big, bg=bg_color, fg=fg_color, command=save_all)
        save_censors_button.grid(row=999, column=4, columnspan=4, pady=12)
        bottom_button_widgets.append(save_censors_button)
        
        # Check if import button should be shown
        current_has_censors = len(current_censors) > 0
        similar_censors = find_similar_theme_censors(filename) if filename else {}
        show_import_button = not current_has_censors and len(similar_censors) > 0
        
        # Add import button if conditions are met
        if show_import_button:
            import_button = tk.Button(censor_editor, text="IMPORT PREVIOUS CENSORS", width=30, font=font_big, bg="dark green", fg=fg_color, command=import_previous_censors)
            import_button.grid(row=1000, column=0, columnspan=6, pady=12)
            bottom_button_widgets.append(import_button)
    
    create_bottom_buttons()

    refresh_ui()

# =========================================
#            *TAG/*FAVORITE FILES
# =========================================
SYSTEM_PLAYLISTS = ['Tagged Themes', 'Favorite Themes', 'New Themes', 'Missing Artists', 'Blind Themes', 'Peek Themes', 'Mute Peek Themes']

def get_playlist(playlist_name):
    playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")
    if os.path.exists(playlist_path):
        with open(playlist_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        new_playlist = copy.deepcopy(BLANK_PLAYLIST)
        new_playlist["name"] = playlist_name
        return new_playlist

def toggle_theme(playlist_name, button=None, filename=None, quiet=False, add=False):
    """Toggles a theme in a specified playlist (e.g., Tagged Themes, Favorite Themes)."""
    if not filename:
        if currently_playing.get("filename"):
            filename = currently_playing.get("filename")
        else:
            return
        
    playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")
    # Load or initialize the playlist
    data = get_playlist(playlist_name)
    theme_list = data["playlist"]

    type_string = "saved to"
    if filename in theme_list:
        if not add:
            # Remove theme
            theme_list.remove(filename)
            if button:
                button_seleted(button, False)
            type_string = "removed from"
        else:
            return
    else:
        # Add theme
        if not theme_list:
            theme_list = [filename]
        else:
            theme_list.append(filename)
        if button:
            button_seleted(button, True)

    # Save the updated playlist
    data["playlist"] = theme_list

    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)

    with open(playlist_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        if not quiet:
            print(f"{filename} {type_string} playlist '{playlist_name}'.")

    # Add/Remove from current playlist if it's loaded
    if playlist.get("name") == playlist_name:
        if filename in theme_list:
            if filename not in playlist["playlist"]:
                playlist["playlist"].append(filename)
            # Update current index to end of playlist
            if currently_playing.get("filename") == filename:
                playlist["current_index"] = len(playlist["playlist"]) - 1
            update_current_index()
        else:
            if filename in playlist["playlist"]:
                playlist["playlist"].remove(filename)
                # Update current index and adjust current index if currently playing item was removed
                if currently_playing.get("filename") == filename:
                    playlist["current_index"] -= 1
                    update_current_index()

    check_theme(playlist_name=playlist_name, recache=True)

    if currently_playing.get("data") and currently_playing.get('filename') == filename:
        update_series_song_information(currently_playing.get("data"), currently_playing.get("data").get("mal"))

check_theme_cache = {}
def check_theme(filename=None, playlist_name=None, recache=False):
    """Checks if a theme exists in a specified playlist (e.g., Tagged Themes, Favorite Themes)."""
    global check_theme_cache
    if playlist_name and (recache or not check_theme_cache.get(playlist_name)):
        playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")
        if os.path.exists(playlist_path):
            with open(playlist_path, "r", encoding="utf-8") as f:
                check_theme_cache[playlist_name] = json.load(f).get("playlist", [])
    return filename in check_theme_cache.get(playlist_name, [])

def tag():
    """Toggles the current theme in the 'Tagged Themes' playlist."""
    toggle_theme("Tagged Themes", tag_button)

def check_tagged(filename):
    """Checks if a filename is in the 'Tagged Themes' playlist."""
    return check_theme(filename, "Tagged Themes")

def favorite():
    """Toggles the current theme in the 'Favorite Themes' playlist."""
    toggle_theme("Favorite Themes", favorite_button)

def check_favorited(filename):
    """Checks if a filename is in the 'Favorite Themes' playlist."""
    return check_theme(filename, "Favorite Themes")

def check_new(filename):
    """Checks if a filename is in the 'New Themes' playlist."""
    return check_theme(filename, "New Themes")

def blind_mark(remove=False):
    """Toggles the current theme in the 'Blind Themes' playlist."""
    if not remove:
        filename = currently_playing.get("filename")
        if check_peek_mark(filename):
            peek_mark(True)
        if check_mute_peek_mark(filename):
            mute_peek_mark(True)
    toggle_theme("Blind Themes", blind_mark_button)

def check_blind_mark(filename):
    """Checks if a filename is in the 'Blind Themes' playlist."""
    return check_theme(filename, "Blind Themes")

def peek_mark(remove=False):
    """Toggles the current theme in the 'Peek Themes' playlist."""
    if not remove:
        filename = currently_playing.get("filename")
        if check_blind_mark(filename):
            blind_mark(True)
        if check_mute_peek_mark(filename):
            mute_peek_mark(True)
    toggle_theme("Peek Themes", peek_mark_button)

def check_peek_mark(filename):
    """Checks if a filename is in the 'Peek Themes' playlist."""
    return check_theme(filename, "Peek Themes")

def mute_peek_mark(remove=False):
    """Toggles the current theme in the 'Mute Peek Themes' playlist."""
    if not remove:
        filename = currently_playing.get("filename")
        if check_blind_mark(filename):
            blind_mark(True)
        if check_peek_mark(filename):
            peek_mark(True)
    toggle_theme("Mute Peek Themes", mute_peek_mark_button)

def check_mute_peek_mark(filename):
    """Checks if a filename is in the 'Mute Peek Themes' playlist."""
    return check_theme(filename, "Mute Peek Themes")

def handle_bulk_marking(playlist_name, check_func, mutually_exclusive_playlists=None):
    """Handle bulk marking/unmarking of entire playlist based on current item's state."""
    if not playlist.get("playlist") or not currently_playing.get("filename"):
        return
    
    current_filename = currently_playing.get("filename")
    
    # Check if current item is marked
    current_is_marked = check_func(current_filename)
    action = "unmark" if current_is_marked else "mark"
    
    # Show confirmation dialog
    playlist_count = len(playlist["playlist"])
    confirm = messagebox.askyesno(
        f"Bulk {action.title()} Confirmation", 
        f"Are you sure you want to {action} all {playlist_count} items in the playlist for '{playlist_name}'?"
    )
    
    if not confirm:
        return
    
    # Apply opposite operation to all items in playlist
    for filename in playlist["playlist"]:
        if current_is_marked:
            # Current item is marked, so unmark all entries
            if check_func(filename):
                toggle_theme(playlist_name, filename=filename, quiet=True)
        else:
            # Current item is not marked, so mark all entries
            if not check_func(filename):
                # Remove from mutually exclusive playlists first
                if mutually_exclusive_playlists:
                    for exclusive_playlist, exclusive_check_func in mutually_exclusive_playlists:
                        if exclusive_check_func(filename):
                            toggle_theme(exclusive_playlist, filename=filename, quiet=True)
                
                toggle_theme(playlist_name, filename=filename, quiet=True, add=True)
    
    # Print summary
    action_past = "unmarked" if current_is_marked else "marked"
    print(f"Bulk {action_past} entire playlist for '{playlist_name}'")

def bulk_tag_playlist(event=None):
    """Middle click handler for tag button - bulk mark/unmark entire playlist."""
    handle_bulk_marking("Tagged Themes", check_tagged)

def bulk_favorite_playlist(event=None):
    """Middle click handler for favorite button - bulk mark/unmark entire playlist."""
    handle_bulk_marking("Favorite Themes", check_favorited)

def bulk_blind_mark_playlist(event=None):
    """Middle click handler for blind mark button - bulk mark/unmark entire playlist."""
    # Blind marks are mutually exclusive with peek and mute peek marks
    mutually_exclusive = [
        ("Peek Themes", check_peek_mark),
        ("Mute Peek Themes", check_mute_peek_mark)
    ]
    handle_bulk_marking("Blind Themes", check_blind_mark, mutually_exclusive)

def bulk_peek_mark_playlist(event=None):
    """Middle click handler for peek mark button - bulk mark/unmark entire playlist."""
    # Peek marks are mutually exclusive with blind and mute peek marks
    mutually_exclusive = [
        ("Blind Themes", check_blind_mark),
        ("Mute Peek Themes", check_mute_peek_mark)
    ]
    handle_bulk_marking("Peek Themes", check_peek_mark, mutually_exclusive)

def bulk_mute_peek_mark_playlist(event=None):
    """Middle click handler for mute peek mark button - bulk mark/unmark entire playlist."""
    # Mute peek marks are mutually exclusive with blind and peek marks
    mutually_exclusive = [
        ("Blind Themes", check_blind_mark),
        ("Peek Themes", check_peek_mark)
    ]
    handle_bulk_marking("Mute Peek Themes", check_mute_peek_mark, mutually_exclusive)

def check_missing_artists():
    playlist["name"] = "Missing Artists"
    def remove_previous_playlist():
        try:
            os.remove(os.path.join(PLAYLISTS_FOLDER, f"{playlist["name"]}.json"))
        except Exception as e:
            print(e)
            pass
    missing_artists = []
    previous_removed = False
    for filename in directory_files:
        data = get_metadata(filename)
        for theme in data.get("songs",[]):
            if theme.get("slug") == data.get("slug") and theme.get("artist") == []:
                if not previous_removed:
                    remove_previous_playlist()
                    previous_removed = True
                toggle_theme(playlist["name"], favorite_button, filename)
                missing_artists.append(filename)
    playlist["playlist"] = missing_artists
    update_current_index(0)

# =========================================
#               *DOCK PLAYER
# =========================================

undock_position = []
def dock_player():
    """Toggles the Tkinter window between front and back, moves it to bottom left,
    adjusts transparency, and removes the title bar when brought forward."""
    global undock_position
    button_seleted(dock_button, not is_docked())
    if is_docked():
        # Send to back, restore transparency, and re-enable title bar
        root.attributes("-topmost", False)
        # root.overrideredirect(False)  # Restore title bar
        root.attributes("-alpha", 1.0)  # Make fully visible
        if not disable_shortcuts:
            move_root_to_bottom(False)
        elif undock_position[1] < root.winfo_y():
            root.after(10, lambda: root.geometry(f"+{undock_position[0]}+{undock_position[1]}"))
    else:
        # Bring to front, move to bottom-left, set full transparency, and remove title bar
        right_top.delete(1.0, tk.END)
        undock_position = (root.winfo_x(), root.winfo_y())
        # root.overrideredirect(True)  # Remove title bar
        root.attributes("-alpha", 0.8)  # Set transparency to 80%
        root.attributes("-topmost", True)
        move_root_to_bottom()
        root.lift()
    up_next_text()
    # Refresh list display to adjust button count based on right_top content changes
    if list_loaded:
        refresh_current_list()

def move_root_to_bottom(toggle=True):
    """Moves the Tkinter root window to the bottom-left corner with accurate positioning."""
    root.update_idletasks()  # Ensure correct window size calculations

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    window_width = root.winfo_width()
    window_height = root.winfo_height()

    # Adjust for possible taskbar height (defaulting to 40px)
    taskbar_height = 0  
    y_position = screen_height - window_height - taskbar_height
    x_position = screen_width/2 - window_width/2 - taskbar_height

    # Ensure y is never negative
    y_position = max(0, y_position)
    x_position = int(max(0, x_position))
    # Set exact position (left edge at x=0)
    if not toggle:
        root.after(1, lambda: animate_window(root, x_position, screen_height))
    else:
        root.geometry(f"+{x_position}+{screen_height}")  # Adjust for bottom spacing
        root.after(10, lambda: animate_window(root, x_position, y_position-30))

def is_docked():
    return root.attributes("-topmost")

# =========================================
#                  *LISTS
# =========================================

last_themes_listed = {}
def show_field_themes(update = False, group=[]):
    global last_themes_listed
    if group == []:
        field_list = last_themes_listed
    else:
        field_list = group
    if last_themes_listed != group:
        update = True
    field_list.sort(key=lambda file: get_title(file, file).lower())
    last_themes_listed = field_list
    selected = -1
    for index, filename in enumerate(field_list):
        if filename == currently_playing.get('filename'):
            selected = index
            break

    show_list("field_list", right_column, convert_playlist_to_dict(field_list), get_title, play_video_from_last, selected, update)

def get_title(key, value):
    try:
        # Check if this entry has lightning round marking
        is_lightning = value.startswith("[L]")
        lightning_icon = "⚡" if is_lightning else ""
        
        # Extract filename for metadata lookup
        filename = get_clean_filename(value)
        
        # Check if this is a YouTube file first
        if is_youtube_file(filename):
            youtube_data = get_youtube_metadata_by_filename(filename)
            if youtube_data:
                title = get_youtube_display_title(youtube_data)
                display_name = f"{lightning_icon}[YT] {title}"
            else:
                display_name = lightning_icon + filename
        else:
            # Regular theme file handling
            data = get_metadata(filename)
            if data:
                title = get_display_title(data)
                display_name = title + " " + data.get("slug")
                version_num = data.get("version")
                if version_num and version_num != 1:
                    display_name += f"v{version_num}"
                # Add indicators for lightning, external files
                if os.path.isabs(value):
                    display_name = "📁 " + display_name
                display_name = lightning_icon + display_name
            else:
                # Show filename with external indicator if applicable
                display_name = filename
                if os.path.isabs(value):
                    display_name = "📁 " + display_name
                display_name = lightning_icon + display_name
        
        # Truncate if too long (will be limited after index is added in update_persistent_button)
        return display_name
        
    except:
        filename = get_clean_filename(value)
        is_lightning = value.startswith("[L]")
        lightning_icon = "⚡" if is_lightning else ""
        return lightning_icon + (("📁 " + filename) if os.path.isabs(value) else filename)

def play_video_from_last(index):
    if last_themes_listed:
        play_video_from_filename(last_themes_listed[index])

def show_playlist(update = False):
    show_list("playlist", right_column, convert_playlist_to_dict(playlist["playlist"]), get_title, play_video, playlist["current_index"], update, right_click_func=remove_theme)

def remove(update = False):
    show_list("remove", right_column, convert_playlist_to_dict(playlist["playlist"]), get_title, remove_theme, playlist["current_index"], update)

def convert_playlist_to_dict(playlis):
    return {f"{video}_{i}": video for i, video in enumerate(playlis)}

def update_playlist_display():
    """Helper function to update the playlist display when the playlist changes"""
    if list_loaded == "playlist":
        global current_list_content, current_list_selected
        current_list_content = convert_playlist_to_dict(playlist["playlist"])
        current_list_selected = playlist["current_index"]
        refresh_current_list()

def remove_theme(index):
    global playlist, current_list_content, current_list_selected
    playlist_entry = playlist["playlist"][index]
    display_name = os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry
    confirm = messagebox.askyesno("Remove Theme", f"Are you sure you want to remove '{display_name}' from '{playlist["name"]}'?")
    if not confirm:
        return  # User canceled
    del playlist["playlist"][index]
    
    # Update current_list_content to reflect the removal
    if list_loaded == "playlist":
        current_list_content = convert_playlist_to_dict(playlist["playlist"])
        # Adjust current_list_selected if needed
        if current_list_selected > index:
            current_list_selected -= 1
        elif current_list_selected == index and current_list_selected >= len(playlist["playlist"]):
            current_list_selected = len(playlist["playlist"]) - 1 if playlist["playlist"] else -1
        refresh_current_list()
    elif list_loaded == "remove":
        current_list_content = convert_playlist_to_dict(playlist["playlist"])
        # If we're in the remove view, we need to refresh that too
        reload_playlist(True)

def reload_playlist(update = False):
    if list_loaded:
        for button in list_buttons:
            if list_loaded == button.get('label'):
                button.get('func')(update)
                return

def get_filename(key, value):
    return value

def button_seleted(button, selected):
    if hasattr(button, 'configure') and button.winfo_exists():
        if selected:
            button.configure(bg=HIGHLIGHT_COLOR, fg="white")
        else:
            button.configure(bg="black", fg="white")
        if popout_buttons_by_name.get(button):
            button_seleted(popout_buttons_by_name[button], selected)

list_loaded = None
list_index = 0
list_func = None
playlist_page_offset = 0
def get_list_entries_count():
    """Get the number of entries to show in lists based on available height."""
    try:
        # Get the actual height of the right_column widget
        right_column.update_idletasks()  # Ensure geometry is updated
        available_height = right_column.winfo_height()
        
        # If height is not yet available (window not fully initialized), use default logic
        if available_height <= 1:
            content = right_top.get(1.0, tk.END)
            content_stripped = content.strip()
            # Check if content is empty or just whitespace/newlines
            if not content_stripped or content_stripped == "" or len(content_stripped) == 0:
                return 13
            else:
                return 12
        
        # Estimate button height including padding/spacing
        # Each button is roughly 25-30 pixels with spacing, using 28 as safe estimate
        button_height_estimate = scl(26, "UI")  # Adjusted for UI scaling
        
        # Calculate how many buttons can fit, with minimum of 8 and maximum of 20
        calculated_count = available_height // button_height_estimate
        
        return calculated_count
        
    except Exception as e:
        return 12  # Default fallback

persistent_buttons = []  # Store the reusable buttons for any list type
button_to_index_map = {}  # Map button widgets to their current indices
current_list_offset = 0  # Offset for any list type
current_list_content = {}  # Store current list content
current_list_name_func = None  # Store current name function
current_list_selected = -1  # Store the currently selected/playing item index
def create_persistent_list_buttons(column, target_count=None):
    """Create persistent buttons that will be reused for any list display."""
    global persistent_buttons, button_to_index_map
    
    if target_count is None:
        target_count = get_list_entries_count()
    
    # Clear any existing buttons
    for btn in persistent_buttons:
        try:
            btn.destroy()
        except:
            pass
    
    persistent_buttons = []
    button_to_index_map = {}
    
    # Create buttons based on target count
    entries_count = target_count
    for i in range(entries_count):
        btn = tk.Button(column, text="", borderwidth=0, pady=0,
                       bg="black", fg="white", font=("Consolas", scl(11, "UI")),
                       command=lambda idx=i: handle_persistent_button_click(idx))
        
        # Add all the event bindings
        btn.bind("<Button-3>", lambda e, idx=i: handle_persistent_right_click(e, idx))
        btn.bind("<MouseWheel>", lambda e: handle_list_scroll(e))
        btn.bind("<Button-4>", lambda e: handle_btn_scroll_up(e))
        btn.bind("<Button-5>", lambda e: handle_btn_scroll_down(e))
        btn.bind("<Enter>", lambda e, idx=i: handle_persistent_button_enter(e, idx))
        btn.bind("<Leave>", lambda e, idx=i: handle_persistent_button_leave(e, idx))
        
        # Add drag bindings only for playlist
        if list_loaded == "playlist":
            btn.bind("<Button-1>", lambda e, idx=i: handle_persistent_drag_start(e, idx))
            btn.bind("<B1-Motion>", lambda e: handle_drag_motion(e))
            btn.bind("<ButtonRelease-1>", lambda e: end_playlist_drag(e))
        
        persistent_buttons.append(btn)
    
    return persistent_buttons

def list_scroll_up():
    global current_list_offset
    if list_loaded:
        current_list_offset = max(0, current_list_offset - 1)
        refresh_current_list()

def list_scroll_down():
    global current_list_offset, current_list_content
    if list_loaded:
        list_size = len(current_list_content)
        entries_count = get_list_entries_count()
        max_offset = max(0, list_size - entries_count)
        current_list_offset = min(max_offset, current_list_offset + 1)
        refresh_current_list()

def refresh_current_list():
    """Refresh the current list display without changing the list type."""
    if list_loaded == "playlist":
        # Update the current list content from the actual playlist data
        global current_list_content
        current_list_content = convert_playlist_to_dict(playlist["playlist"])
        
        # Check if button count needs to change first
        entries_count = get_list_entries_count()
        current_count = len(persistent_buttons) if persistent_buttons else 0
        
        if current_count != entries_count:
            # Directly recreate buttons and layout
            if persistent_buttons:
                try:
                    column = persistent_buttons[0].master
                    create_persistent_list_buttons(column, entries_count)
                    
                    # Recreate layout
                    column.config(state=tk.NORMAL, wrap="none")
                    column.delete(1.0, tk.END)
                    for button_index in range(entries_count):
                        try:
                            column.window_create(tk.END, window=persistent_buttons[button_index])
                            column.insert(tk.END, "\n")
                        except tk.TclError:
                            pass
                    column.config(state=tk.DISABLED)
                except (IndexError, AttributeError, tk.TclError) as e:
                    return
        
        # For playlist, just update the persistent buttons directly instead of calling show_playlist
        if persistent_buttons and current_list_content:
            start_index = current_list_offset
            end_index = min(len(current_list_content), start_index + entries_count)
            
            for button_index in range(entries_count):
                item_index = start_index + button_index
                if item_index < end_index:
                    update_persistent_button(button_index, item_index, current_list_name_func, current_list_content, current_list_selected)
                else:
                    update_persistent_button(button_index, -1, current_list_name_func, current_list_content, current_list_selected)
        else:
            # Fallback to full refresh if persistent buttons aren't ready
            show_playlist(update=True)
    elif list_loaded and current_list_content:
        # For other lists, update the display directly
        update_persistent_list_display()

def update_persistent_list_display():
    """Update the persistent buttons with current list content."""
    global current_list_content, current_list_name_func
    
    if not current_list_content or not current_list_name_func:
        return
    
    list_size = len(current_list_content)
    start_index = current_list_offset
    entries_count = get_list_entries_count()
    end_index = min(list_size, start_index + entries_count)
    
    # Update each persistent button
    for button_index in range(entries_count):
        list_index = start_index + button_index
        if list_index < end_index:
            update_persistent_button(button_index, list_index, current_list_name_func, current_list_content, current_list_selected)
        else:
            # Clear button content for unused positions
            try:
                persistent_buttons[button_index].config(text="", state="disabled")
            except (tk.TclError, IndexError):
                pass

def get_display_width(text):
    """Calculate display width treating Unicode icons as 2 characters each."""
    width = 0
    for char in text:
        # Count Unicode icons as 2 characters for alignment in monospace fonts
        if char in ['⚡', '📁']:
            width += 2
        else:
            width += 1
    return width

def truncate_by_display_width(text, max_width):
    """Truncate text based on display width, treating Unicode icons as 2 characters."""
    if get_display_width(text) <= max_width:
        return text
    
    # Find the truncation point
    current_width = 0
    for i, char in enumerate(text):
        char_width = 2 if char in ['⚡', '📁'] else 1
        if current_width + char_width > max_width:
            return text[:i]
        current_width += char_width
    
    return text

def update_persistent_button(button_index, item_index, name_func, content_dict, selected):
    """Update a single persistent button with new content."""
    global button_to_index_map
    
    if button_index >= len(persistent_buttons):
        return
    
    btn = persistent_buttons[button_index]
    
    # Check if button still exists
    try:
        if not btn.winfo_exists():
            return
    except tk.TclError:
        return
    
    button_to_index_map[btn] = item_index
    
    # Get the content for this item index
    items_list = list(content_dict.items())
    if item_index < len(items_list) and item_index >= 0:
        key, value = items_list[item_index]
        index_prefix = str(item_index + 1) + ": "
        title_part = name_func(key, value)

        # Calculate available space for title (47 total - index prefix display width)
        max_total_width = 47
        available_width = max_total_width - get_display_width(index_prefix)
        
        # Truncate title if needed based on display width
        if get_display_width(title_part) > available_width:
            keep_width = available_width - 1  # Account for "…" (1 character width)
            if keep_width > 0:
                half_width = keep_width // 2
                # Find truncation points that respect character boundaries
                left_part = truncate_by_display_width(title_part, half_width)
                
                # For right part, work backwards from the end
                right_width = keep_width - get_display_width(left_part)
                right_part = ""
                if right_width > 0:
                    temp_width = 0
                    for i in range(len(title_part) - 1, -1, -1):
                        char = title_part[i]
                        char_width = 2 if char in ['⚡', '📁'] else 1
                        if temp_width + char_width > right_width:
                            break
                        temp_width += char_width
                        right_part = char + right_part
                
                title_part = left_part + "…" + right_part
            else:
                title_part = truncate_by_display_width(title_part, available_width)
        
        name = index_prefix + title_part
        
        # Update button appearance
        if item_index == selected:
            font = ("Consolas", scl(11, "UI"), "bold")
            bg = HIGHLIGHT_COLOR
        elif not disable_shortcuts and item_index == list_index:
            font = ("Consolas", scl(11, "UI"))
            bg = HIGHLIGHT_COLOR
        else:
            font = ("Consolas", scl(11, "UI"))
            bg = "black"
        
        try:
            btn.config(text=name, font=font, bg=bg, fg="white", state="normal")
        except tk.TclError:
            return
    else:
        # Hide button if no content
        try:
            btn.config(text="", state="disabled")
        except tk.TclError:
            return

def handle_persistent_button_click(button_index):
    """Handle click on a persistent button."""
    try:
        if button_index < len(persistent_buttons):
            btn = persistent_buttons[button_index]
            if btn in button_to_index_map and btn.winfo_exists():
                actual_index = button_to_index_map[btn]
                if list_func:
                    list_func(actual_index)
    except (tk.TclError, IndexError):
        pass

def handle_persistent_right_click(event, button_index):
    """Handle right click on a persistent button."""
    try:
        if button_index < len(persistent_buttons):
            btn = persistent_buttons[button_index]
            if btn in button_to_index_map and btn.winfo_exists():
                actual_index = button_to_index_map[btn]
                # Call the right-click function if it exists
                if hasattr(handle_persistent_right_click, 'right_click_func') and handle_persistent_right_click.right_click_func:
                    handle_persistent_right_click.right_click_func(actual_index)
    except (tk.TclError, IndexError):
        pass

def handle_persistent_button_enter(event, button_index):
    """Handle mouse enter on persistent button."""
    if button_index < len(persistent_buttons):
        btn = persistent_buttons[button_index]
        if btn in button_to_index_map:
            actual_index = button_to_index_map[btn]
            on_button_enter(event, actual_index)

def handle_persistent_button_leave(event, button_index):
    """Handle mouse leave on persistent button."""
    if button_index < len(persistent_buttons):
        btn = persistent_buttons[button_index]
        if btn in button_to_index_map:
            actual_index = button_to_index_map[btn]
            on_button_leave(event, actual_index)

def handle_persistent_drag_start(event, button_index):
    """Handle drag start on persistent button."""
    if button_index < len(persistent_buttons):
        btn = persistent_buttons[button_index]
        if btn in button_to_index_map:
            actual_index = button_to_index_map[btn]
            start_playlist_drag(event, actual_index)

def list_set_loaded(type):
    global list_loaded
    list_loaded = type
    for button in list_buttons:
        if button.get('button') and globals().get(button.get('button')):
            button_seleted(globals().get(button.get('button')), list_loaded == button.get('label'))

def list_unload(column):
    global persistent_buttons
    # Clean up persistent buttons when switching away from playlist
    if list_loaded == "playlist" and persistent_buttons:
        for btn in persistent_buttons:
            try:
                btn.destroy()
            except:
                pass
        persistent_buttons = []
    
    list_set_loaded(None)
    update_extra_metadata(currently_playing.get("data"))

def list_move(amount):
    global list_index, current_list_offset
    if list_loaded and current_list_content:
        # Move selection with wrapping
        old_index = list_index
        list_size = len(current_list_content)
        
        if amount > 0:  # Moving down
            list_index = (list_index + 1) % list_size
        else:  # Moving up
            list_index = (list_index - 1) % list_size
        
        # Auto-scroll if selection moves out of visible area
        entries_count = get_list_entries_count()
        if list_index < current_list_offset:
            current_list_offset = list_index
            refresh_current_list()
        elif list_index >= current_list_offset + entries_count:
            current_list_offset = list_index - entries_count + 1
            refresh_current_list()
        elif old_index != list_index:
            # Just update highlighting if no scrolling needed
            refresh_current_list()
    else:
        left_column.yview_scroll(amount, "units")
        middle_column.yview_scroll(amount, "units")
        right_column.yview_scroll(amount, "units")

def list_select():
    if list_loaded:
        list_func(list_index)

def playlist_page_up():
    if list_loaded == "playlist":
        list_scroll_up()

def playlist_page_down():
    if list_loaded == "playlist":
        list_scroll_down()

def show_list(type, column, content, name_func, btn_func, selected, update = True, right_click_func=None, items_per_page=None):
    global list_loaded, list_index, list_func, current_list_offset, current_list_content, current_list_name_func, persistent_buttons
    
    list_size = len(content)
    buttons_need_recreation = False
    
    if list_loaded == type and not update:
        list_unload(column)
        return
    elif list_loaded != type:
        list_set_loaded(type)
        if selected < 0:
            list_index = 0
        else:
            list_index = selected
        list_func = btn_func
        current_list_offset = 0
        buttons_need_recreation = True
        
        # For playlist, center on current playing item
        if type == "playlist":
            entries_count = get_list_entries_count()
            current_playing = playlist.get("current_index", -1)
            if current_playing >= 0:
                current_list_offset = max(0, current_playing - entries_count // 2)
                max_offset = max(0, list_size - entries_count)
                current_list_offset = min(current_list_offset, max_offset)
    elif list_index >= list_size:
        list_index = 0
    elif list_index < 0:
        list_index = list_size - 1
    
    # Store current list data
    current_list_content = content
    current_list_name_func = name_func
    
    # Store the selected index for highlighting
    global current_list_selected
    current_list_selected = selected
    
    # Update playlist offset for playlist type
    if type == "playlist":
        global playlist_page_offset
        playlist_page_offset = current_list_offset
    
    # Store right_click_func for persistent button handlers
    handle_persistent_right_click.right_click_func = right_click_func
    
    # Only clear and recreate layout when switching list types
    if buttons_need_recreation:
        column.config(state=tk.NORMAL, wrap="none", spacing1=0, spacing3=0)
        column.delete(1.0, tk.END)
        
        # Create or recreate persistent buttons if count changed
        entries_count = get_list_entries_count()
        current_count = len(persistent_buttons) if persistent_buttons else 0
        if not persistent_buttons or len(persistent_buttons) != entries_count:
            create_persistent_list_buttons(column, entries_count)
        else:
            pass  # Button count matches, no recreation needed
        
        # Add buttons to layout
        for button_index in range(entries_count):
            try:
                column.window_create(tk.END, window=persistent_buttons[button_index])
                column.insert(tk.END, "\n")
            except tk.TclError:
                # Button was destroyed, recreate persistent buttons
                create_persistent_list_buttons(column, entries_count)
                column.window_create(tk.END, window=persistent_buttons[button_index])
                column.insert(tk.END, "\n")
        
        column.config(state=tk.DISABLED, spacing1=0, spacing3=0)
    
    # Calculate display boundaries
    entries_count = get_list_entries_count()
    start_index = current_list_offset
    end_index = min(list_size, start_index + entries_count)
    
    # Adjust offset if we're beyond the valid range
    if start_index >= list_size:
        current_list_offset = max(0, list_size - entries_count)
        start_index = current_list_offset
        end_index = min(list_size, start_index + entries_count)
    
    # Update each persistent button with current content (no layout changes needed)
    for button_index in range(entries_count):
        item_index = start_index + button_index
        if item_index < end_index:
            update_persistent_button(button_index, item_index, name_func, content, selected)
        else:
            # Hide button if no content
            update_persistent_button(button_index, -1, name_func, content, selected)
    
    # Ensure keyboard focus for navigation
    if buttons_need_recreation:
        column.focus_set()

# Drag and drop variables
drag_start_index = None
drag_current_y = None
drag_indicator_line = None

# Hover tracking for drag-and-drop insertion
hovered_button_index = None
external_drag_active = False

def start_playlist_drag(event, index):
    """Start dragging a playlist item."""
    global drag_start_index, drag_current_y
    # Clear any existing highlighting
    clear_drop_highlight()
    
    drag_start_index = index
    drag_current_y = event.y_root
    
    # Highlight the source item being dragged
    highlight_drag_source(index)

def handle_drag_motion(event):
    """Handle dragging motion - can be called from any button."""
    global drag_current_y, drag_indicator_line
    if drag_start_index is None:
        return
    
    drag_current_y = event.y_root
    
    # Update cursor to show dragging is active
    try:
        event.widget.configure(cursor="hand2")
    except (tk.TclError, AttributeError):
        pass
    
    # Calculate and highlight drop target position
    try:
        # Get the widget under the mouse cursor
        widget_under_mouse = root.winfo_containing(event.x_root, event.y_root)
        
        # Clear only target highlights (preserve source highlight)
        clear_target_highlights()
        
        # If we're over a button, highlight it
        if widget_under_mouse and hasattr(widget_under_mouse, 'cget'):
            try:
                button_text = widget_under_mouse.cget('text')
                # Extract index from button text (format: "1: Title Name")
                if ':' in button_text:
                    index_str = button_text.split(':')[0].strip()
                    if index_str.isdigit():
                        target_index = int(index_str) - 1  # Convert to 0-based
                        
                        # Only highlight if it's different from the source
                        if target_index != drag_start_index and 0 <= target_index < len(playlist["playlist"]):
                            # Store original colors and highlight
                            highlighted_buttons[target_index] = {
                                'widget': widget_under_mouse,
                                'original_bg': widget_under_mouse.cget('bg'),
                                'original_fg': widget_under_mouse.cget('fg'),
                                'is_target': True
                            }
                            widget_under_mouse.configure(bg=HIGHLIGHT_COLOR, fg="white")
            except (tk.TclError, AttributeError, ValueError):
                pass
            
    except (ValueError, tk.TclError, AttributeError):
        pass

# Global variables to track highlight tags
current_highlight_tag = None
current_source_tag = None
highlighted_buttons = {}  # Track highlighted button widgets

def highlight_drag_source(source_index):
    """Highlight the source item being dragged to look like it's pressed."""
    global current_source_tag
    
    if list_loaded != "playlist":
        return
        
    try:
        # Highlight the button widget for the source index to look pressed (white bg, black text)
        highlight_button_at_index(source_index, "white", "black", is_source=True)
        
    except (tk.TclError, AttributeError, ValueError):
        pass

def highlight_drop_target(target_index):
    """Highlight the target drop position in the playlist."""
    global current_highlight_tag
    
    if list_loaded != "playlist":
        return
    
    # Don't highlight if dropping on the same item
    if target_index == drag_start_index:
        clear_button_highlights()
        return
        
    try:
        # Clear previous button highlights
        clear_button_highlights()
        
        # Find and highlight the button widget for the target index
        highlight_button_at_index(target_index, "lime", "black")
        
    except (tk.TclError, AttributeError, ValueError):
        pass

def highlight_button_at_index(target_index, bg_color, fg_color, is_source=False):
    """Highlight the button widget at the specified playlist index."""
    global highlighted_buttons
    
    try:
        # Find all button widgets in the right_column
        for widget_name in right_column.children:
            widget = right_column.nametowidget(widget_name)
            if hasattr(widget, 'configure') and hasattr(widget, 'cget'):
                try:
                    button_text = widget.cget('text')
                    # Check if this button corresponds to our target index
                    if button_text.startswith(f"{target_index + 1}:"):
                        # Store original colors
                        if target_index not in highlighted_buttons:
                            highlighted_buttons[target_index] = {
                                'widget': widget,
                                'original_bg': widget.cget('bg'),
                                'original_fg': widget.cget('fg'),
                                'is_source': is_source,
                                'is_target': not is_source
                            }
                        # Apply highlight
                        widget.configure(bg=bg_color, fg=fg_color)
                        break
                except (tk.TclError, AttributeError):
                    continue
    except (tk.TclError, AttributeError):
        pass

def clear_button_highlights():
    """Clear all button highlighting and restore original colors."""
    global highlighted_buttons
    
    try:
        for index, button_data in highlighted_buttons.items():
            widget = button_data['widget']
            if widget and hasattr(widget, 'configure'):
                try:
                    # Restore original colors
                    widget.configure(
                        bg=button_data['original_bg'],
                        fg=button_data['original_fg']
                    )
                except (tk.TclError, AttributeError):
                    pass
        highlighted_buttons.clear()
    except (tk.TclError, AttributeError):
        pass

def clear_target_highlights():
    """Clear only target button highlights, preserve source highlight."""
    global highlighted_buttons
    
    try:
        # Find and clear only target highlights
        targets_to_remove = []
        for index, button_data in highlighted_buttons.items():
            if button_data.get('is_target', False):
                widget = button_data['widget']
                if widget and hasattr(widget, 'configure'):
                    try:
                        # Restore original colors
                        widget.configure(
                            bg=button_data['original_bg'],
                            fg=button_data['original_fg']
                        )
                        targets_to_remove.append(index)
                    except (tk.TclError, AttributeError):
                        pass
        
        # Remove cleared targets from the dictionary
        for index in targets_to_remove:
            del highlighted_buttons[index]
            
    except (tk.TclError, AttributeError):
        pass

def clear_drop_highlight():
    """Clear any drop target and source highlighting."""
    global current_highlight_tag, current_source_tag
    try:
        # Clear button highlights
        clear_button_highlights()
        
        # Clear any remaining text highlights
        if current_highlight_tag:
            right_column.tag_delete(current_highlight_tag)
            current_highlight_tag = None
        if current_source_tag:
            right_column.tag_delete(current_source_tag)
            current_source_tag = None
    except (tk.TclError, AttributeError):
        pass

def on_button_enter(event, index):
    """Handle mouse entering a button during drag operation."""
    global hovered_button_index
    
    # Always track which button we're hovering over (for file drops)
    hovered_button_index = index
    
    # Always highlight on hover, unless it's a special button we shouldn't change
    try:
        current_bg = event.widget.cget('bg')
        current_fg = event.widget.cget('fg')
        
        # Don't change highlighting if it's the current playing song or drag source
        is_current_index = (index == playlist.get("current_index", -1))
        is_drag_source = (drag_start_index is not None and index == drag_start_index)
        
        if not (is_current_index or is_drag_source):
            # Store original colors if not already stored
            if index not in highlighted_buttons:
                highlighted_buttons[index] = {
                    'widget': event.widget,
                    'original_bg': current_bg,
                    'original_fg': current_fg
                }
            
            # Apply hover highlight
            event.widget.configure(bg="gray26", fg="white")
        
    except (tk.TclError, AttributeError):
        pass

def on_button_leave(event, index):
    """Handle mouse leaving a button during drag operation."""
    global hovered_button_index
    
    # Clear hover tracking when leaving button
    if hovered_button_index == index:
        hovered_button_index = None
    
    # Restore original colors when leaving (unless it's current index or drag source)
    is_current_index = (index == playlist.get("current_index", -1))
    is_drag_source = (drag_start_index is not None and index == drag_start_index)
    
    if not (is_current_index or is_drag_source) and index in highlighted_buttons:
        try:
            button_data = highlighted_buttons[index]
            event.widget.configure(
                bg=button_data['original_bg'],
                fg=button_data['original_fg']
            )
            del highlighted_buttons[index]
        except (tk.TclError, AttributeError, KeyError):
            pass

def drag_playlist_item(event, index):
    """Handle dragging motion (legacy function)."""
    handle_drag_motion(event)

def end_playlist_drag(event):
    """End dragging and reorder playlist if needed."""
    global drag_start_index, drag_current_y, playlist
    
    if drag_start_index is None:
        return
    
    # Calculate drop position based on mouse position - use same method as visual highlighting
    try:
        # Get the widget under the mouse cursor (same as visual highlighting)
        widget_under_mouse = root.winfo_containing(event.x_root, event.y_root)
        drop_index = None
        
        # If we're over a button, get its index
        if widget_under_mouse and hasattr(widget_under_mouse, 'cget'):
            try:
                button_text = widget_under_mouse.cget('text')
                # Extract index from button text (format: "1: Title Name")
                if ':' in button_text:
                    index_str = button_text.split(':')[0].strip()
                    if index_str.isdigit():
                        display_index = int(index_str) - 1  # Convert to 0-based
                        # Account for pagination offset
                        if list_loaded == "playlist":
                            drop_index = display_index  # display_index already includes pagination offset
                        else:
                            drop_index = display_index
            except (tk.TclError, AttributeError, ValueError):
                pass
        
        # If no button found, try fallback text position method
        if drop_index is None:
            try:
                text_widget = right_column
                x_rel = event.x_root - text_widget.winfo_rootx()
                y_rel = event.y_root - text_widget.winfo_rooty()
                
                if (0 <= x_rel <= text_widget.winfo_width() and 
                    0 <= y_rel <= text_widget.winfo_height()):
                    
                    text_index = text_widget.index(f"@{x_rel},{y_rel}")
                    drop_line = int(text_index.split('.')[0]) - 1  # Convert to 0-based line index
                    
                    # Account for pagination in playlist view
                    if list_loaded == "playlist":
                        # Each line corresponds to a playlist item, add the pagination offset
                        drop_index = max(0, min(drop_line + playlist_page_offset, len(playlist["playlist"]) - 1))
                    else:
                        # Original logic for non-playlist lists
                        # Account for the "items above" indicator if present
                        if "items above" in text_widget.get("1.0", "2.0"):
                            drop_line = max(0, drop_line - 1)
                        
                        drop_index = max(0, min(drop_line, len(playlist["playlist"]) - 1))
            except (ValueError, tk.TclError):
                pass
        
        # Perform the reorder if we have a valid drop position
        if (drop_index is not None and 
            drop_index != drag_start_index and 
            0 <= drop_index < len(playlist["playlist"])):
            
            # Reorder the playlist
            item = playlist["playlist"].pop(drag_start_index)
            playlist["playlist"].insert(drop_index, item)
            
            # Adjust current_index if needed
            if playlist["current_index"] == drag_start_index:
                playlist["current_index"] = drop_index
            elif drag_start_index < playlist["current_index"] <= drop_index:
                playlist["current_index"] -= 1
            elif drop_index <= playlist["current_index"] < drag_start_index:
                playlist["current_index"] += 1
            
            # Refresh the playlist display
            show_playlist(True)
    
    except Exception as e:
        print(f"Drag and drop error: {e}")
    
    # Clear drop target highlighting
    clear_drop_highlight()
    
    # Reset drag state
    drag_start_index = None
    drag_current_y = None
    
    # Reset cursor
    try:
        event.widget.configure(cursor="")
        right_column.configure(cursor="")
    except (tk.TclError, AttributeError):
        pass

def list_keyboard_shortcuts():
    right_column.config(state=tk.NORMAL, wrap="none")
    right_column.delete(1.0, tk.END)
    add_single_line(right_column, "SHOW KEYBOARD SHORTCUTS", "[K]")
    add_single_line(right_column, "ENABLE SHORTCUTS", "[']", False)
    add_single_line(right_column, "INFO", "[I]", False)
    add_single_line(right_column, "TITLE", "[O]")
    add_single_line(right_column, "PLAY/PAUSE", "[SPACE BAR]", False)
    add_single_line(right_column, "STOP", "[ESC]")
    add_single_line(right_column, "PREVIOUS/NEXT", "[⬅]/[➡]", False)
    add_single_line(right_column, "FULLSCREEN", "[TAB]")
    add_single_line(right_column, "SEEK TO PART", "[0]-[9]", False)
    add_single_line(right_column, "DOCK PLAYER", "[D]")
    add_single_line(right_column, "MUTE VIDEO", "[M]", False)
    add_single_line(right_column, "SCROLL UP/DOWN", "[⬆]/[⬇]")
    add_single_line(right_column, "TAG", "[T]", False)
    add_single_line(right_column, "FAVORITE", "[*]", False)
    add_single_line(right_column, "MODE DOWN/UP", "[<]/[>]")
    add_single_line(right_column, "REFETCH METADATA", "[F]", False)
    add_single_line(right_column, "REROLL NEXT", "[R]")
    add_single_line(right_column, "SHOW PLAYLIST", "[P]", False)
    add_single_line(right_column, "SHOW YOUTUBE VIDEOS", "[Y]")
    add_single_line(right_column, "LIST UP/DOWN", "[⬆]/[⬇]", False)
    add_single_line(right_column, "LIST SELECT", "[ENTER]")
    add_single_line(right_column, "SEARCH/QUEUE", "[S]", False)
    add_single_line(right_column, "CANCEL SEARCH", "[ESC]")
    add_single_line(right_column, "", "BONUS?", False)
    add_single_line(right_column, "YEAR, SCORE, RANK, MEMBERS", "[G]")
    add_single_line(right_column, "CHARACTERS", "      [J]", False)
    add_single_line(right_column, "TAGS", "[N]", False)
    add_single_line(right_column, "MULTIPLE", "[U]")
    add_single_line(right_column, "STUDIO, SONG, ARTIST", "      [H]")
    add_single_line(right_column, "TOGGLE BLIND", "[BKSP]", False)
    add_single_line(right_column, "TOGGLE PEEK", "[=]")
    add_single_line(right_column, "BLIND/PEEK/MUTE ROUND", "[B]", False)
    add_single_line(right_column, "PEEK SIZE", "[ [ ]/[ ] ]")
    add_single_line(right_column, "LIGHTNING ROUND CYCLE", "[L]", False)
    add_single_line(right_column, "VARIETY", "[V]")
    add_single_line(right_column, "TOGGLE CENSOR BAR", "[C]", False)
    add_single_line(right_column, "END SESSION", "[E]")
    add_single_line(right_column, "[W]IDEN [Z]IP [A]NCHOR E[X]TEND [Q]UIT", "SCORE", False)
    right_column.config(state=tk.DISABLED)

def add_single_line(column, line, title, newline=True):
    column.insert(tk.END, title + ": ", "bold")
    column.insert(tk.END, line, "white")
    if newline:
        column.insert(tk.END, "\n", "white")
    else:
        column.insert(tk.END, "   ", "white")

# =========================================
#                 *TOGGLES
# =========================================

def toggle_disable_shortcuts():
    global disable_shortcuts
    disable_shortcuts = not disable_shortcuts
    print("Keyboard Shortcuts Disabled: " + str(disable_shortcuts))
    button_seleted(toggle_disable_shortcuts_button, not disable_shortcuts)

auto_info_start = False
def toggle_auto_info_start():
    global auto_info_start
    auto_info_start = not auto_info_start
    print("Auto Info Popup at start: " + str(auto_info_start))
    button_seleted(start_info_button, auto_info_start)

auto_info_end = False
def toggle_auto_info_end():
    global auto_info_end
    auto_info_end = not auto_info_end
    print("Auto Info Popup at end: " + str(auto_info_end))
    button_seleted(end_info_button, auto_info_end)

auto_refresh_toggle = False
def toggle_auto_auto_refresh():
    global auto_refresh_toggle
    auto_refresh_toggle = not auto_refresh_toggle
    print("Auto refresh metadata: " + str(auto_refresh_toggle))
    button_seleted(toggle_refresh_metadata_button, auto_refresh_toggle)

def toggle_censor_bar():
    global censors_enabled
    censors_enabled = not censors_enabled
    print("Censor Bar Enabled: " + str(censors_enabled))
    apply_censors(player.get_time()/1000, player.get_length()/1000)
    button_seleted(toggle_censor_bar_button, censors_enabled)
    if not censors_enabled:
        remove_all_censor_boxes()
        
def toggle_progress_bar():
    global progress_bar_enabled
    progress_bar_enabled = not progress_bar_enabled
    print("Progress Bar Enabled: " + str(progress_bar_enabled))
    apply_censors(player.get_time()/1000, player.get_length()/1000)
    button_seleted(toggle_progress_bar_button, progress_bar_enabled)
    update_progress_bar(player.get_time(), player.get_length())

disable_video_audio = False
light_muted = False
def toggle_mute(muted=None, lightning=False):
    global disable_video_audio, light_muted
    if light_mode or light_round_started or lightning:
        if muted == None:
            muted = not light_muted
        light_muted = muted
        if not disable_video_audio:
            player.audio_set_mute(muted)
        play_background_music(muted and not currently_streaming and light_mode not in ['clip', 'ost'])
        button_seleted(mute_button, muted or disable_video_audio)
    else:
        if muted == None:
            muted = not disable_video_audio
        disable_video_audio = muted
        player.audio_set_mute(disable_video_audio)
        if music_loaded:
            if disable_video_audio:
                pygame.mixer.music.set_volume(0)
            else:
                pygame.mixer.music.set_volume(0.2*(volume_level/100))
        button_seleted(mute_button, disable_video_audio)

# =========================================
#              *END SESSION
# =========================================

def end_session():
    global video_stopped
    if not end_message_window:
        video_stopped = True
    else:
        video_stopped = False
    toggle_end_message()
    send_scoreboard_command("end")

end_message_window = None

def get_op_ed_counts(themes):
    opening_count = 0
    ending_count = 0

    for filename in themes:
        # Try to get slug and version from metadata first, fallback to filename parsing
        file_data = get_file_metadata_by_name(filename)
        if file_data and file_data.get('slug'):
            slug = file_data['slug']
            version = file_data.get('version')
        else:
            slug = filename.split("-")[1].split(".")[0].split("v")[0]  # Fallback to filename parsing
            # Try to extract version from filename if available
            version_part = filename.split("-")[1].split(".")[0]
            if "v" in version_part:
                version = version_part.split("v")[1] if len(version_part.split("v")) > 1 else None
            else:
                version = None
        
        if is_slug_op(slug):
            opening_count += 1
        else:
            ending_count += 1
    return opening_count, ending_count

DEFAULT_END_SESSION_MESSAGE = "THANKS FOR\nPLAYING!🤍"
def toggle_end_message(speed=500):
    """Toggles the 'Thanks for playing!' message with detailed stats."""
    global end_message_window
    try:
        button_seleted(end_button, not end_message_window)
        if end_message_window:
            end_message_window.destroy()
            end_message_window = None
            return

        end_message_window = tk.Toplevel()
        end_message_window.title("End Message")
        end_message_window.overrideredirect(True)
        end_message_window.attributes("-topmost", True)
        end_message_window.wm_attributes("-alpha", 0.8)
        end_message_window.configure(bg=OVERLAY_BACKGROUND_COLOR)

        # Create main container frame
        main_frame = tk.Frame(end_message_window, bg=OVERLAY_BACKGROUND_COLOR)
        main_frame.pack(padx=scl(25), pady=scl(25))

        total_played = get_themes_played_count()
        opening_count, ending_count = get_op_ed_counts(get_unique_themes_played())
        
        # Count lightning rounds and YouTube videos from session data
        lightning_count = sum(1 for entry in session_data if entry.get("lightning_mode"))
        youtube_count = sum(1 for entry in session_data if entry.get("type") == "youtube")
        
        end_message_text = end_session_txt.replace("\\n", "\n") or DEFAULT_END_SESSION_MESSAGE

        # Main end message - largest font (90pt)
        end_msg_label = tk.Label(main_frame, text=end_message_text, 
                                 font=("Arial", scl(90), "bold"),
                                 fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR, 
                                 justify="center")
        end_msg_label.pack(pady=(0, scl(20)))

        # Separator line 1
        separator1 = tk.Frame(main_frame, height=2, bg=OVERLAY_TEXT_COLOR)
        separator1.pack(fill="x", padx=scl(0), pady=(0, scl(10)))

        # Date and time section - right after thank you message
        datetime_str = datetime.now().strftime("%b %d, %Y")
        date_label = tk.Label(main_frame, text=f"GUESS THE ANIME! {datetime_str.upper()}", 
                              font=("Arial", scl(35), "bold"),
                              fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                              justify="center")
        date_label.pack(pady=(0, scl(10)))

        # Session time range
        try:
            # session_start_time is stored as a string, need to convert back to datetime
            start_datetime = datetime.strptime(session_start_time, '%Y-%m-%d_%H-%M')
            start_time = start_datetime.strftime("%#I:%M %p")
            duration = datetime.now() - start_datetime
        except (ValueError, TypeError):
            start_time = "N/A"
            duration = None
        
        # Get timezone abbreviation
        # Check if we're in daylight saving time
        is_dst = time.daylight and time.localtime().tm_isdst
        timezone_name = time.tzname[1 if is_dst else 0]
        
        # Create abbreviation by taking first letter of each word
        timezone_abbr = ''.join(word[0].upper() for word in timezone_name.split())
        
        end_time = datetime.now().strftime("%#I:%M %p")
        time_text = f"{start_time} - {end_time} {timezone_abbr}"
        if duration:
            time_text += f" [{duration.seconds//3600}h {(duration.seconds//60)%60}m]"
        
        time_range_label = tk.Label(main_frame, text=time_text, 
                                    font=("Arial", scl(30), "normal"),
                                    fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                                    justify="center")
        time_range_label.pack(pady=(0, scl(5)))

        separator2 = tk.Frame(main_frame, height=2, bg=OVERLAY_TEXT_COLOR)
        separator2.pack(fill="x", padx=scl(0), pady=(0, scl(10)))

        # Session Stats Header
        stats_header = tk.Label(main_frame, text="SESSION BREAKDOWN:", 
                               font=("Arial", scl(40), "bold underline"),
                               fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR, 
                               justify="center")
        stats_header.pack(pady=(0, scl(15)))

        # Themes played section - large font
        themes_label = tk.Label(main_frame, text=f"{total_played} THEMES PLAYED", 
                                font=("Arial", scl(55), "bold"),
                                fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                                justify="center")
        themes_label.pack(pady=(0, 0))

        # Lightning rounds and YouTube videos - additional stats
        additional_stats_parts = []
        if lightning_count > 0:
            if lightning_count == 1:
                additional_stats_parts.append("1 LIGHTNING ROUND")
            else:
                additional_stats_parts.append(f"{lightning_count} LIGHTNING ROUNDS")
        if youtube_count > 0:
            if youtube_count == 1:
                additional_stats_parts.append("1 YOUTUBE VIDEO")
            else:
                additional_stats_parts.append(f"{youtube_count} YOUTUBE VIDEOS")
        if additional_stats_parts:
            additional_stats_text = "\n".join(additional_stats_parts)
        else:
            additional_stats_text = ""

        # OP/ED breakdown - medium font
        breakdown_label = tk.Label(main_frame, text=f"{opening_count} OPENINGS  •  {ending_count} ENDINGS", 
                                   font=("Arial", scl(35), "normal"),
                                   fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                                   justify="center")
        breakdown_label.pack(pady=(0, scl(10)))

        additional_stats_label = tk.Label(main_frame, text=f"{additional_stats_text}", 
                                   font=("Arial", scl(35), "normal"),
                                   fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                                   justify="center")
        additional_stats_label.pack(pady=(scl(10), scl(10)))

        # Top Series section
        series_counts = {}
        unique_themes_per_series = {}  # Track unique themes per series to avoid double counting same theme
        
        for entry in session_data:
            if entry.get("type") == "theme" and entry.get("id") and entry.get("slug"):
                # Create unique identifier for this theme
                theme_id = f"{entry.get('id')}_{entry.get('slug')}"
                
                # Get theme data from metadata using ID and slug to find series info
                theme_data = get_metadata(entry.get("filename", ""))
                series_name = None
                
                if theme_data:
                    # Use series parameter from top level metadata, fallback to title
                    series_raw = theme_data.get("series") or theme_data.get("title")
                    
                    # Handle case where series might be a list
                    if isinstance(series_raw, list):
                        series_name = series_raw[0] if series_raw else None
                    else:
                        series_name = series_raw
                
                # Further fallback to entry title if still nothing found
                if not series_name:
                    series_name = entry.get("title")
                
                if series_name:
                    # Initialize series tracking if not exists
                    if series_name not in unique_themes_per_series:
                        unique_themes_per_series[series_name] = set()
                        series_counts[series_name] = 0
                    
                    # Only count if we haven't seen this specific theme for this series
                    if theme_id not in unique_themes_per_series[series_name]:
                        unique_themes_per_series[series_name].add(theme_id)
                        series_counts[series_name] += 1
        # Filter series with more than one theme and sort by count
        top_series = [(series, count) for series, count in series_counts.items() if count > 1]
        top_series.sort(key=lambda x: x[1], reverse=True)
        # Only show if there's exactly one clear winner (no ties for first place)
        if top_series and len(top_series) >= 1:
            top_count = top_series[0][1]
            # Check if there's a tie for first place
            tied_series = [series for series, count in top_series if count == top_count]
            
            if len(tied_series) == 1:  # No ties, show the single top series
                top_series_name, count = top_series[0]
                
                # Add separator line
                separator4 = tk.Frame(main_frame, height=2, bg=OVERLAY_TEXT_COLOR)
                separator4.pack(fill="x", padx=scl(0), pady=(scl(10), scl(10)))
                
                # Top Series Header (singular)
                series_header = tk.Label(main_frame, text="MOST PLAYED SERIES:", 
                                        font=("Arial", scl(35), "bold underline"),
                                        fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR, 
                                        justify="center")
                series_header.pack(pady=(0, scl(10)))
                
                # Display the single top series
                series_label = tk.Label(main_frame, text=f"{top_series_name} ({count})", 
                                       font=("Arial", scl(28), "normal"),
                                       fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                                       justify="center")
                series_label.pack(pady=(0, scl(10)))

        # Top Artists section
        artist_counts = {}
        unique_themes = set()  # Track unique themes to avoid double counting
        
        for entry in session_data:
            if entry.get("type") == "theme" and entry.get("id") and entry.get("slug"):
                # Create unique identifier for this theme
                theme_id = f"{entry.get('id')}_{entry.get('slug')}"
                
                # Only process if we haven't seen this theme before
                if theme_id not in unique_themes:
                    unique_themes.add(theme_id)
                    
                    # Get theme data from metadata using ID and slug
                    theme_data = get_metadata(entry.get("filename", ""))
                    if theme_data:
                        for theme in theme_data.get("songs", []):
                            if theme.get("slug") == entry.get("slug"):
                                for artist in theme.get("artist", []):
                                    if artist:  # Skip empty artist names
                                        artist_counts[artist] = artist_counts.get(artist, 0) + 1
        
        # Filter artists played more than once and sort by count
        top_artists = [(artist, count) for artist, count in artist_counts.items() if count > 1]
        top_artists.sort(key=lambda x: x[1], reverse=True)
        
        # Only show if there's exactly one clear winner (no ties for first place)
        if top_artists and len(top_artists) >= 1:
            top_count = top_artists[0][1]
            # Check if there's a tie for first place
            tied_artists = [artist for artist, count in top_artists if count == top_count]
            
            if len(tied_artists) == 1:  # No ties, show the single top artist
                top_artist, count = top_artists[0]
                
                # Add separator line
                separator3 = tk.Frame(main_frame, height=2, bg=OVERLAY_TEXT_COLOR)
                separator3.pack(fill="x", padx=scl(0), pady=(scl(10), scl(10)))
                
                # Top Artist Header (singular)
                artists_header = tk.Label(main_frame, text="MOST PLAYED ARTIST:", 
                                         font=("Arial", scl(35), "bold underline"),
                                         fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR, 
                                         justify="center")
                artists_header.pack(pady=(0, scl(10)))
                
                # Display the single top artist
                artists_label = tk.Label(main_frame, text=f"{top_artist} ({count})", 
                                        font=("Arial", scl(28), "normal"),
                                        fg=OVERLAY_TEXT_COLOR, bg=OVERLAY_BACKGROUND_COLOR,
                                        justify="center")
                artists_label.pack(pady=(0, scl(10)))

        # Update window positioning to use the main frame
        end_message_window.update_idletasks()
        screen_width = end_message_window.winfo_screenwidth()
        screen_height = end_message_window.winfo_screenheight()
        window_width = main_frame.winfo_reqwidth()
        window_height = main_frame.winfo_reqheight()
        start_x = screen_width - window_width - scl(60)
        start_y = screen_height
        end_x = screen_width - window_width - scl(60)
        end_y = scl(10)

        root.update_idletasks()
        end_message_window.geometry(f"+{start_x}+{start_y}")
        root.update_idletasks()
        root.after(1, lambda: animate_window(end_message_window, end_x, end_y, delay=5, steps=2000, fade=None))
        save_session_history(create_text_file=True, silent=False)
    except AttributeError as e:
        print("Error displaying end session message:", e)
        pass

def on_closing():
    pass

def prompt_end_session_text(event=None):
    global end_session_txt
    result = simpledialog.askstring("End Session", "Enter end session message text(use '\\n' for new lines):", initialvalue=end_session_txt)
    if result is not None:
        end_session_txt = result
        save_config()

# =========================================
#            *POPOUT CONTROLS
# =========================================

popout_controls = None
popout_buttons_by_name = {}
popout_up_next = None
popout_up_next_font = None
popout_currently_playing = None
popout_currently_playing_extra = None
popout_button_font = None
resize_after_id = None
popout_show_metadata = True
popout_show_up_next = False
popout_show_currently_playing = False

def toggle_show_popout_currently_playing():
    global popout_show_currently_playing
    popout_show_currently_playing = not popout_show_currently_playing
    if popout_show_currently_playing:
        if currently_playing.get("data"):
            update_popout_currently_playling(currently_playing.get("data"))
        popout_currently_playing.configure(pady=0, fg="white")
    else:
        # Show placeholder when hidden with gray text
        popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
        popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
        popout_currently_playing_extra.delete(1.0, tk.END)
        popout_currently_playing_extra.config(state=tk.DISABLED)
    popout_controls.event_generate("<Configure>")

def toggle_show_popout_up_next():
    global popout_show_up_next
    popout_show_up_next = not popout_show_up_next
    if popout_show_up_next:
        update_up_next_display(popout_up_next)
    else:
        update_up_next_display(popout_up_next, clear=True)
    popout_controls.event_generate("<Configure>")

def toggle_show_popout_metadata():
    global popout_show_metadata
    popout_show_metadata = not popout_show_metadata
    button_seleted(popout_buttons_by_name["toggle_metadata"], popout_show_metadata)
    if popout_show_metadata:
        if popout_show_currently_playing and currently_playing.get("data"):
            update_popout_currently_playling(currently_playing.get("data"))
            popout_currently_playing.configure(pady=0, fg="white")
        elif not popout_show_currently_playing:
            # Show placeholder with gray text
            popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
            popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
            popout_currently_playing_extra.delete(1.0, tk.END)
            popout_currently_playing_extra.config(state=tk.DISABLED)
    else:
        # Clear currently playing completely
        popout_currently_playing.configure(text="", fg="white")
        popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
        popout_currently_playing_extra.delete(1.0, tk.END)
        popout_currently_playing_extra.config(state=tk.DISABLED)
    # Always update up-next display
    if popout_show_up_next:
        update_up_next_display(popout_up_next)
    else:
        update_up_next_display(popout_up_next, clear=False)
    popout_controls.event_generate("<Configure>")

popout_searching = False
POPOUT_SEARCH_DEFAULT = "SEARCH THEMES"
def create_popout_controls(columns=5, title="Popout Controls"):
    # --- SEARCH GROUP STATE ---
    global search_term, search_results
    search_var = tk.StringVar(value=search_term if ('search_term' in globals() and search_term) else POPOUT_SEARCH_DEFAULT)
    search_results_var = tk.StringVar(value="")
    search_results_map = {}

    global popout_controls, popout_up_next, popout_up_next_font, popout_button_font, popout_currently_playing, popout_currently_playing_extra

    def on_popout_close():
        global popout_controls, popout_up_next, popout_currently_playing, popout_currently_playing_extra
        button_seleted(popout_controls_button, False)
        popout_buttons_by_name.clear()
        popout_controls.destroy()
        popout_controls = None
        popout_up_next = None
        popout_currently_playing = None
        popout_currently_playing_extra = None

    def on_popout_resize(event):
        global resize_after_id

        def do_resize():
            if not popout_controls:
                return

            width = popout_controls.winfo_width()
            height = popout_controls.winfo_height()
            min_dim = min(width*.5, height)

            # Use combined or minimum dimension for scaling
            new_upnext_size = max(10, int(min_dim / 30))
            new_button_size = max(10, int(min_dim / 25))
            new_current_size = max(10, int(min_dim / 25))
            new_current_extra_size = max(10, int(min_dim / 50))

            popout_button_font.configure(size=new_button_size)

            if popout_show_metadata:
                popout_up_next_font.configure(size=new_upnext_size)
                popout_current_font.configure(size=new_current_size)
                popout_current_extra_font.configure(size=new_current_extra_size)

                # Adjust text wrap to match new width
                popout_currently_playing.configure(wraplength=int(width * 0.95))
            else:
                # Collapse metadata if disabled
                popout_up_next_font.configure(size=1)
                popout_current_font.configure(size=1)
                popout_current_extra_font.configure(size=1)
                popout_currently_playing.configure(wraplength=0)

            # Reapply button fonts to all cloned buttons
            for widget in popout_buttons_by_name.values():
                if isinstance(widget, tk.Button):
                    widget.configure(font=popout_button_font)

        # Cancel any pending resize jobs
        if resize_after_id is not None:
            popout_controls.after_cancel(resize_after_id)

        # Schedule a new resize job 150ms from now
        resize_after_id = popout_controls.after(150, do_resize)

    if popout_controls:
        on_popout_close()
        return

    popout_controls = tk.Toplevel()
    popout_controls.title(title)
    popout_controls.configure(bg=BACKGROUND_COLOR)
    popout_controls.geometry("1440x810")
    popout_controls.protocol("WM_DELETE_WINDOW", on_popout_close)
    popout_controls.bind("<Configure>", on_popout_resize)

    # Shared fonts
    popout_up_next_font = font.Font(family="Helvetica", size=20, weight="bold")
    popout_current_font = font.Font(family="Helvetica", size=25, weight="bold")
    popout_current_extra_font = font.Font(family="Helvetica", size=10, weight="bold")
    popout_button_font = font.Font(family="Helvetica", size=20, weight="bold")

    # Button group structure
    button_groups = {
        "POPOUT CONTROLS": [
            (mute_peek_mark_button, "MARK", True),
            (tag_button, "TAG", True),
            (favorite_button, "FAV", True),
            (info_button, "INFO", False),
            (title_info_button, "TITLE ONLY", False)
        ],
        "BLIND CONTROLS": [
            (blind_mark_button, "MARK", True),
            (blind_button, "BLIND", False, 1),
            (blind_round_button, "BLIND NEXT", True, 1),
            (mute_button, "MUTE", False),
            (mute_peek_round_button, "MUTE PEEK NEXT", True, 1),
        ],
        "PEEK CONTROLS": [
            (peek_mark_button, "MARK", True),
            (peek_button, "PEEK", False, 1),
            (peek_round_button, "PEEK NEXT", True, 1),
            (widen_peek_button, "WIDEN PK", True, 1),
            (narrow_peek_button, "NARROW PK", True, 1),
        ],
        "BONUS QUESTIONS": [
            (guess_year_button, "YEAR", True),
            (guess_members_button, "MEMBERS", True),
            (guess_score_button, "SCORE", True),
            (guess_tags_button, "TAGS", True),
            (guess_multiple_button, "MULTIPLE", True)
        ],
        "BONUS QUESTIONS2": [
            (guess_popularity_button, "RANK", True),
            (guess_studio_button, "STUDIO", True),
            (guess_artist_button, "ARTIST", True),
            (guess_song_button, "SONG", True),
            (guess_characters_button, "CHARACTERS", True)
        ],
        "LIGHTNING ROUNDS": [
            ("LIGHTNING DROPDOWN", "MODE SELECT", 2),
            (start_light_mode_button, "START", True),
            (variety_light_mode_button, "VARIETY", True),
            ("DIFFICULTY DROPDOWN", "DIFFICULTY SELECT", 1)
        ],
        "YOUTUBE QUEUE": [
            ("YOUTUBE DROPDOWN", "YOUTUBE VIDEOS", 4),
            ("YOUTUBE QUEUE", "QUEUE NEXT", 1)
        ],
        "SEARCH": [
            ("SEARCH ENTRY", "SEARCH", 2),
            ("SEARCH DROPDOWN", "RESULTS", 2),
            ("SEARCH QUEUE", "QUEUE NEXT", 1)
        ],
        "MISC TOGGLES": [
            (dock_button, "DOCK", False),
            (toggle_censor_bar_button, f"CENSORS({len(get_file_censors(currently_playing.get("filename","")))})", False),
            ("toggle_metadata", "METADATA", False),
            (filter_button, "FILTERS", False),
            (end_button, "END SESSION", False)
        ],
        "PLAYER CONTROLS": [
            ("reroll", "", False),
            (play_pause_button, "PLAY/PAUSE", True),
            (stop_button, "STOP", True),
            (previous_button, "PREVIOUS", True),
            (next_button, "NEXT", True)
        ]
    }

    row = 0

    popout_currently_playing = tk.Label(
        popout_controls,
        font=popout_current_font,
        bg=BACKGROUND_COLOR,
        fg="white",
        text="",
        anchor="center",     # Center vertically
        justify="center",    # Center multiline text
        padx=5,
        pady=5               # Adjust as needed for vertical spacing inside label
    )
    popout_currently_playing.grid(
        row=row,
        column=0,
        columnspan=columns,
        sticky="nsew",
        padx=5,
        pady=(10, 10)         # Padding below the label
    )
    popout_controls.grid_rowconfigure(row, weight=0)
    
    # Add click binding to toggle currently playing display (on mouse up)
    popout_currently_playing.bind("<ButtonRelease-1>", lambda e: toggle_show_popout_currently_playing())

    row += 1

    popout_currently_playing_extra = tk.Text(
        popout_controls,
        font=popout_current_extra_font,
        bg=BACKGROUND_COLOR,
        fg="white",
        bd=0,
        height=4
    )
    popout_currently_playing_extra.grid(row=row, column=0, columnspan=columns, sticky="nsew", padx=5, pady=(0, 0))
    popout_controls.grid_rowconfigure(row, weight=0)
    popout_currently_playing_extra.tag_configure("white", foreground="white", justify="center")
    
    # Add click binding to toggle currently playing display (on mouse up)
    popout_currently_playing_extra.bind("<ButtonRelease-1>", lambda e: toggle_show_popout_currently_playing())

    row += 1

    for group_name, button_entries in button_groups.items():
        if row > 0:
            row += 1
        col = 0

        for entry in button_entries:
            # --- SEARCH GROUP ---
            if group_name == "SEARCH":
                if entry[0] == "SEARCH ENTRY":
                    # Search entry
                    search_entry = tk.Entry(
                        popout_controls,
                        textvariable=search_var,
                        font=popout_button_font,
                        bg="black",
                        fg="white",
                        insertbackground="white"
                    )
                    search_entry.grid(row=row, column=col, columnspan=entry[2], sticky="nsew", padx=2, pady=1)
                    def on_search_entry_key(event=None):
                        global search_term, search_results
                        query = search_var.get().strip()
                        if not query:
                            query = ""
                        elif query == POPOUT_SEARCH_DEFAULT:
                            search_term = ""
                            search_results = []
                            search_results_dropdown["values"] = []
                            search_results_var.set("")
                            search_results_map.clear()
                            return
                        else:
                            search_term = query
                        # Use the standard search logic
                        if query and query != POPOUT_SEARCH_DEFAULT:
                            search_results = search_playlist(query)
                        else:
                            search_results = []
                        search_results.sort(key=lambda file: get_title(file, file).lower())
                        # Update dropdown
                        titles = [get_title(f, f) for f in search_results]
                        search_results_dropdown["values"] = titles
                        if titles:
                            search_results_var.set(titles[0])
                        else:
                            search_results_var.set("")
                        # Map titles to filenames
                        search_results_map.clear()
                        for i, f in enumerate(search_results):
                            search_results_map[titles[i]] = f
                    def on_focus_in(e):
                        global popout_searching
                        popout_searching = True
                        if search_var.get() == POPOUT_SEARCH_DEFAULT:
                            search_var.set("")
                    def on_focus_out(e):
                        global popout_searching
                        popout_searching = False
                        if not search_var.get().strip():
                            search_var.set(POPOUT_SEARCH_DEFAULT)
                    search_entry.bind("<FocusIn>", on_focus_in)
                    search_entry.bind("<FocusOut>", on_focus_out)
                    search_entry.bind("<KeyRelease>", on_search_entry_key)
                    popout_buttons_by_name[entry[0]] = search_entry
                    col += entry[2]
                    continue
                elif entry[0] == "SEARCH DROPDOWN":
                    # Results dropdown
                    titles = [get_title(f, f) for f in search_results]
                    for i, f in enumerate(search_results):
                        search_results_map[titles[i]] = f
                    search_results_dropdown = ttk.Combobox(
                        popout_controls,
                        values=titles,
                        textvariable=search_results_var,
                        font=popout_button_font,
                        height=10,
                        style="Black.TCombobox",
                        state='readonly'
                    )
                    search_results_dropdown.grid(row=row, column=col, columnspan=entry[2], sticky="nsew", padx=2, pady=1)
                    def on_search_dropdown_change(event):
                        search_results_dropdown.selection_clear()
                        search_results_dropdown.icursor(tk.END)
                    search_results_dropdown.bind("<<ComboboxSelected>>", on_search_dropdown_change)
                    popout_buttons_by_name[entry[0]] = search_results_dropdown
                    col += entry[2]
                    continue
                elif entry[0] == "SEARCH QUEUE":
                    # Queue/Add Next button
                    def queue_selected_search():
                        global search_queue, search_results, playlist
                        selected = search_results_var.get()
                        if selected and selected in search_results_map:
                            filename = search_results_map[selected]
                            if playlist.get("infinite"):
                                # Use add_search_playlist (index is 1-based)
                                if filename in search_results:
                                    idx = search_results.index(filename) + 1
                                    add_search_playlist(idx)
                                # Reset search box and dropdown
                                search_var.set(POPOUT_SEARCH_DEFAULT)
                                search_results_var.set("")
                                search_results_map.clear()
                                search_results_dropdown["values"] = []
                            else:
                                # Use the same function as regular search queue
                                if filename in search_results:
                                    idx = search_results.index(filename) + 1
                                    set_search_queue(idx)
                        if search_queue: 
                            search_queue_button.configure(bg=HIGHLIGHT_COLOR)
                        else:
                            search_queue_button.configure(bg="black")
                    button_text = "ADD NEXT" if playlist.get("infinite") else "QUEUE NEXT"
                    search_queue_button = tk.Button(
                        popout_controls,
                        text=button_text,
                        font=popout_button_font,
                        command=queue_selected_search,
                        bg="black",
                        fg="white"
                    )
                    search_queue_button.grid(row=row, column=col, columnspan=entry[2], sticky="nsew", padx=2, pady=1)
                    popout_buttons_by_name[entry[0]] = search_queue_button
                    col += entry[2]
                    continue
                elif entry[0] is None:
                    tk.Label(popout_controls, text="", bg=BACKGROUND_COLOR).grid(row=row, column=col, columnspan=entry[2], sticky="nsew")
                    col += entry[2]
                    continue
            # --- END SEARCH GROUP ---
            # --- YOUTUBE QUEUE GROUP ---
            if group_name == "YOUTUBE QUEUE":
                if entry[0] == "YOUTUBE DROPDOWN":
                    # Build YouTube dropdown with only downloaded videos
                    youtube_video_var = tk.StringVar(value="")
                    youtube_video_list = []
                    youtube_video_map = {}
                    for key, value in youtube_metadata.get("videos", {}).items():
                        if os.path.exists(os.path.join("youtube", value["filename"])):
                            title = value.get('custom_title') or value.get('title')
                            youtube_video_list.append(title)
                            youtube_video_map[title] = key
                    youtube_dropdown = ttk.Combobox(
                        popout_controls,
                        values=youtube_video_list,
                        textvariable=youtube_video_var,
                        font=popout_button_font,
                        height=10,
                        style="Black.TCombobox",
                        state='readonly'
                    )
                    youtube_dropdown.grid(row=row, column=col, columnspan=entry[2], sticky="nsew", padx=2, pady=1)
                    def set_dropdown_default():
                        youtube_dropdown.set("YOUTUBE VIDEOS")
                    youtube_dropdown.after(100, set_dropdown_default)
                    def on_youtube_dropdown_change(event):
                        youtube_dropdown.selection_clear()
                        youtube_dropdown.icursor(tk.END)
                    youtube_dropdown.bind("<<ComboboxSelected>>", on_youtube_dropdown_change)
                    popout_buttons_by_name[entry[0]] = youtube_dropdown
                    col += entry[2]
                    continue
                elif entry[0] == "YOUTUBE QUEUE":
                    def queue_selected_youtube():
                        selected = popout_buttons_by_name["YOUTUBE DROPDOWN"].get()
                        if selected and selected in youtube_video_map:
                            video_id = youtube_video_map[selected]
                            # Find the index of the video_id in the current _youtube_playlist
                            show_youtube_playlist()
                            video_keys = list(_youtube_playlist.keys())
                            try:
                                index = video_keys.index(video_id)
                            except ValueError:
                                index = None
                            if index is not None:
                                load_youtube_video(index)
                        if youtube_queue:
                            queue_button.configure(bg=HIGHLIGHT_COLOR)
                        else:
                            queue_button.configure(bg="black")
                    queue_button = tk.Button(
                        popout_controls,
                        text=entry[1],
                        font=popout_button_font,
                        command=queue_selected_youtube,
                        bg="black",
                        fg="white"
                    )
                    queue_button.grid(row=row, column=col, columnspan=entry[2], sticky="nsew", padx=2, pady=1)
                    popout_buttons_by_name[entry[0]] = queue_button
                    col += entry[2]
                    continue
                elif entry[0] is None:
                    # Blank columns
                    tk.Label(popout_controls, text="", bg=BACKGROUND_COLOR).grid(row=row, column=col, columnspan=entry[2], sticky="nsew")
                    col += entry[2]
                    continue

            # --- END YOUTUBE QUEUE GROUP ---
            if isinstance(entry[0], str) and "DROPDOWN" in entry[0]:
                _, label_text, colspan = entry
                if col + colspan > columns:
                    row += 1
                    col = 0
                if entry[0] == "LIGHTNING DROPDOWN":
                    dropdown = ttk.Combobox(
                        popout_controls,
                        values=[display for _, display in light_mode_options],
                        font=popout_button_font,
                        height=len(light_mode_options),
                        style="Black.TCombobox",
                        state='readonly'
                    )

                    def on_popout_dropdown_change(event):
                        dropdown = popout_buttons_by_name[light_dropdown]
                        value = dropdown.get()
                        light_dropdown.set(value)
                        if light_mode:
                            select_lightning_mode()
                        dropdown.selection_clear()
                        dropdown.icursor(tk.END)

                    dropdown.set(light_dropdown.get())
                    dropdown.bind("<<ComboboxSelected>>", on_popout_dropdown_change)
                    popout_buttons_by_name[light_dropdown] = dropdown
                    dropdown.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=2, pady=1)
                elif entry[0] == "DIFFICULTY DROPDOWN":
                    dropdown = ttk.Combobox(
                        popout_controls,
                        values=difficulty_options,
                        font=popout_button_font,
                        height=len(difficulty_options),
                        style="Black.TCombobox",
                        state='readonly'
                    )

                    def on_popout_dropdown_change(event):
                        dropdown = popout_buttons_by_name["DIFFICULTY DROPDOWN"]
                        value = dropdown.get()
                        difficulty_dropdown.set(value)
                        select_difficulty()
                        dropdown.selection_clear()
                        dropdown.icursor(tk.END)

                    dropdown.set(difficulty_options[playlist.get("difficulty", 2)])
                    dropdown.bind("<<ComboboxSelected>>", on_popout_dropdown_change)
                    popout_buttons_by_name[entry[0]] = dropdown
                    dropdown.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=2, pady=1)
                    if not playlist.get("infinite"):
                        dropdown.grid_remove()
                col += colspan
                continue

            if len(entry) == 4:
                original_button, label_text, show_original, colspan = entry
            else:
                original_button, label_text, show_original = entry
                colspan = 1

            if col + colspan > columns:
                row += 1
                col = 0
            if original_button and not isinstance(original_button, str):
                btn_fg = original_button.cget("fg")
                btn_bg = original_button.cget("bg")
                btn_cmd = original_button.cget("command")
                original_text = original_button.cget("text")
            else:
                btn_fg = "white"
                btn_bg = "black"
                btn_cmd = None
                original_text = ""
                if original_button == "toggle_metadata":
                    if popout_show_metadata:
                        btn_bg = HIGHLIGHT_COLOR
                    btn_cmd = toggle_show_popout_metadata

            full_label = ""
            if show_original:
                full_label += original_text
                # if label_text:
                #     full_label += "\n"
            full_label += label_text

            clone = tk.Button(
                popout_controls,
                text=full_label,
                fg=btn_fg,
                bg=btn_bg,
                command=btn_cmd,
                font=popout_button_font,
                justify="center"
            )
            clone.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=2, pady=1)
            popout_buttons_by_name[original_button] = clone

            col += colspan

        row += 1

    # "Up Next" info area
    popout_up_next = tk.Text(
        popout_controls,
        font=popout_up_next_font,
        bg=BACKGROUND_COLOR,
        fg="white",
        wrap="word",
        bd=0,
        height=1
    )
    popout_up_next.grid(row=row, column=0, columnspan=columns, sticky="nsew", padx=5, pady=(10, 5))
    popout_controls.grid_rowconfigure(row, weight=0)
    popout_up_next.tag_configure("bold", font=popout_up_next_font.copy())
    popout_up_next.tag_configure("white", foreground="white", justify="center")
    popout_up_next.tag_configure("center", foreground="gray", justify="center")
    
    # Add click binding to toggle up next display (on mouse up)
    popout_up_next.bind("<ButtonRelease-1>", lambda e: toggle_show_popout_up_next())

    # Enable expansion
    for i in range(columns):
        popout_controls.grid_columnconfigure(i, weight=1)
    for i in range(row):
        popout_controls.grid_rowconfigure(i, weight=1)

    button_seleted(popout_controls_button, True)
    if currently_playing.get("data"):
        update_popout_currently_playling(currently_playing.get("data"))
        popout_controls.after(500, up_next_text)

# =========================================
#                 *GUI SETUP
# =========================================

# Load saved configuration on startup
load_config()

BACKGROUND_COLOR = "gray12"
WINDOW_TITLE = f"Guess the Anime! Playlist Tool v{APP_VERSION}"

# Try to use tkinterdnd2 for better drag-and-drop support
try:
    root = tkdnd.Tk()
except ImportError:
    root = tk.Tk()
except Exception as e:
    root = tk.Tk()

root.title(WINDOW_TITLE)
root.geometry(f"{scl(1200, "UI")}x{scl(580, "UI")}")
root.minsize(scl(900, "UI"), scl(580, "UI"))  # Set minimum window size to prevent controls squishing
root.configure(bg=BACKGROUND_COLOR)  # Set background color to black
ROOT_FONT = ("Segoe UI", scl(9, "UI"))
# root.resizable(False, False)

# Enable drag-and-drop on main window
def setup_main_window_drag_drop():
    try:
        # Enable drag-and-drop on main window
        enable_drag_and_drop(root, handle_dropped_files)
    except Exception as e:
        print(f"Could not enable drag-and-drop on main window: {e}")

# Setup drag-and-drop after window is fully initialized
root.after(500, setup_main_window_drag_drop)

def blank_space(row, size=2):
    space_label = tk.Label(row, text="", bg=BACKGROUND_COLOR, fg="white")
    space_label.pack(side="left", padx=size)

def create_button(frame, label, func, add_space=False, enabled=False, help_title="", help_text=""):
    """Creates a button with optional spacing and right-click help functionality."""
    bg = HIGHLIGHT_COLOR if enabled else "black"
    
    # Create the button
    # button = tk.Button(frame, text=label, command=func, bg=bg, fg="white")
    button = tk.Button(frame, text=label, command=func, bg=bg, fg="white", font=ROOT_FONT)
    button.pack(side="left", padx=(0,0))

    # Bind right-click to show help
    button.bind("<Button-3>", lambda event, title=help_title, text=help_text: show_button_help(title, text))

    if add_space:
        blank_space(frame)
    
    return button

def show_button_help(help_title, help_text):
    """Displays the help title (bold + underline) and description in the help column."""
    right_column.config(state=tk.NORMAL, wrap="word")
    right_column.delete(1.0, tk.END)  # Clear previous help text
    # Add title in bold + underline
    right_column.insert(tk.END, f"{help_title}\n\n", ("bold", "underline"))
    right_column.insert(tk.END, f"{help_text}\n", "white")
    
    right_column.tag_configure("underline", underline=True)
    
    right_column.config(state=tk.DISABLED)

# First row
first_row_frame = tk.Frame(root, bg=BACKGROUND_COLOR)
first_row_frame.pack(pady=(5,5))

def select_directory():
    global directory
    directory_path = filedialog.askdirectory()
    if directory_path:
        directory = directory_path
        scan_directory()

def scan_directory(queue=False):
    def worker():
        global directory_entry, directory_files, directory
        if not directory:
            return
        print(f"Scanning Directory...", end="", flush=True)
        directory_files = {}
        if globals().get("directory_entry"):
            directory_entry.delete(0, tk.END)
            directory_entry.insert(0, directory)
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith((".mp4", ".webm", ".mkv")):
                    directory_files[file] = os.path.join(root, file)
        save_config()
        get_cached_sfw_themes()
        if playlist.get("infinite", False):
            get_pop_time_groups(refetch=True)
            update_current_index()
        print(f"\rScanning Directory....COMPLETE ({len(directory_files)} files)")
    if queue:
        threading.Thread(target=worker, daemon=True).start()
    else:
        worker()

def create_first_row_buttons():
    for widget in first_row_frame.winfo_children():
        widget.destroy()
    global dock_button
    dock_button = create_button(first_row_frame, "[D]OCK", dock_player, True, 
                                help_title="[D]OCK PLAYER (Shortcut Key = 'd')",
                                help_text="Docks the player on the bottom of the screen and makes it semitransparent. " +
                                "Click again to undock.\n\nWhen shortcuts are enabled it will" + 
                                " hide it at the bottom of the screen. Otherwise it will return to its " + 
                                "previous position.\n\nIt can be useful if you need to share any "+
                                "information on the player, or use any buttons that don't have "+
                                "shortcuts. Also if you are just browsing.")

    global popout_controls_button
    popout_controls_button = create_button(first_row_frame, "🗖POPOUT", create_popout_controls, True, 
                                help_title="CONTROLS POPOUT",
                                help_text="Opens a popout window with bigger buttons for common controls used " +
                                "in a session. Useful if running without keyboard shortcuts, and want bigger buttons.")
    
    global select_button
    select_button = create_button(first_row_frame, "FOLDER:", select_directory,
                                help_title="CHOOSE VIDEO DIRECTORY FOLDER",
                                help_text="Choose the folder you have all your themes stored "+
                                "in. This application expects files from the AnimeThemes " +
                                "website, either grabbed from the torrent or downloaded from the site. " +
                                "\n\nIt searches subfolders, so just pick the highest folder.\n\n" +
                                "You can add themes not from AnimeThemes, but they must be labeled " +
                                "properly to be able to fetch the metadata from MAL. Label them as follows:\n\n" +
                                "AnimeName-OP1-[MAL]49618[ART]Minami[SNG]Rude Lose Dance.webm\n\n" + 
                                "It does expect .webm files. You should be able to just change " + 
                                "the extension if it's .mp4.\n\nYou'll want to hit the CREATE " + 
                                "button after to create the playlist.")

    global directory_entry
    directory_entry = tk.Entry(first_row_frame, width=scl(29, "UI"), bg="black", fg="white", insertbackground="white", textvariable=directory)
    directory_entry.pack(side="left")
    directory_entry.delete(0, tk.END)
    directory_entry.insert(0, directory)

    global generate_button
    generate_button = create_button(first_row_frame, "➕", generate_playlist_button,
                                help_title="CREATE PLAYLIST",
                                help_text=("This creates a playlist using all videos "
                                "found in the directory.\n\nIf this is your first time "
                                "creating a playlist with these files, and you want "
                                "to be able to use all the other playlist functions, "
                                "you'll need to fetch the metadata for all the files. "
                                "You can do this by hitting the '?' button next to the "
                                "RE[F]ETCH METADATA button. It may take a while "
                                "depending on how many themes you have.\n\n"
                                "You will be asked to confirm when creating."))
    
    global create_infinite_button
    create_infinite_button = create_button(first_row_frame, "∞", create_infinite_playlist, 
                                help_title="CREATE INFINITE PLAYLIST",
                                help_text="Creates a new infinite playlist. These playlists pull files from the directory, and go on infinitely "
                                "based on popularity and season groups. Favorited tracks get a boost, and tagged tracks will not be picked. "
                                "Tracks from the last 3 seasons also get a boost.\n\n"
                                "Filters can be applied and removed freely. Sorting/shuffling is disabled.\n\n"
                                "Difficulty can be chosen, limiting the groups to certain popularity levels. The groups are as follows:\n\n"
                                "Easy: 1-250\n"
                                "Medium: 250-1000\n"
                                "Hard: >1001\n\n"
                                "By selecting a difficulty, it doesn't change the ranges, just limit which groups are being used as follows:\n\n"
                                "VERY EASY: [Easy]\n"
                                "EASY: [Easy, Medium]\n"
                                "NORMAL: [Easy, Medium, Hard]\n"
                                "HARD: [Medium, Hard]\n"
                                "VERY HARD: [Hard]\n\n"
                                "So Normal will include everything, while other difficulties exclude certain groups.")
    create_infinite_button.bind("<Button-2>", test_infinite_playlist)

    global generate_from_anilist_button
    generate_from_anilist_button = create_button(first_row_frame, "AL", generate_anilist_playlist,
                                help_title="CREATE PLAYLIST FROM ANILIST ID",
                                help_text=("This creates a playlist using an AniList ID as a reference and "
                                           "selecting all themes in the directory that match the user's list."))
    global empty_button
    empty_button = create_button(first_row_frame, "❌", empty_playlist, True,
                                help_title="EMPTY PLAYLIST",
                                help_text=("This resets you to a blank playlist. "
                                "This is only if you want to manually add themes to the "
                                "playlist using the SEARCH+ button. That's not really what "
                                "this application was made for, so it may be a hassle "
                                "depending on how many themes you want to add to the list."))

    global show_playlist_button
    show_playlist_button = create_button(first_row_frame, "[P]LAYLIST", show_playlist, False,
                                help_title="VIEW [P]LAYLIST/[P]LAY HISTORY (Shortcut Key = 'p')",
                                help_text=("List all themes in the playlist. It will scroll to whichever "
                                "theme the current index is at. Select a theme to play it immediately "
                                "and set the current index to it.\n\nAs with all lists, it loads buttons "
                                "to select the entry, but for the playlist it may be quite a few buttons. "
                                "It usually loads quickly, but may take a second to clear."))
    
    # Enable drag-and-drop on playlist button
    def setup_playlist_drag_drop():
        try:
            enable_drag_and_drop(show_playlist_button, handle_dropped_files)
        except Exception as e:
            print(f"Could not enable drag-and-drop on playlist button: {e}")
    
    # Setup drag-and-drop after widget is fully created
    root.after(100, setup_playlist_drag_drop)
    # if not playlist.get("infinite", False):
    global remove_button
    remove_button = create_button(first_row_frame, "❌", remove, True,
                                help_title="REMOVE THEME",
                                help_text=("Remove a theme from the playlist. There is a confirmation "
                                "dialogue after selecting.\n\nIt may be a bit slow depending on how many "
                                "themes you have added or want to delete."))

    global go_button
    go_button = create_button(first_row_frame, "GO TO:", go_to_index,
                                help_title="GO TO INDEX",
                                help_text=("Go to the index in the text box of the playlist. "
                                "It will play it immediately and set the current index."))
    global current_entry
    current_entry = tk.Entry(first_row_frame, width=5, bg="black", fg="white", insertbackground="white", justify='center', font=ROOT_FONT)
    if playlist.get("infinite", False):
        current_entry.insert(0, "∞")
        out_of = "?"
    else:
        current_entry.insert(0, str(playlist["current_index"]+1))
        out_of = len(playlist["playlist"])
    current_entry.pack(side="left")

    global playlist_size_label
    playlist_size_label = tk.Label(first_row_frame, text=f"/{out_of}", bg=BACKGROUND_COLOR, fg="white", font=ROOT_FONT)
    playlist_size_label.pack(side="left")

    blank_space(first_row_frame)

    global save_button
    save_button = create_button(first_row_frame, "SAVE", save, True,
                                help_title="SAVE PLAYLIST",
                                help_text=("Use this to save your current playlist. Playlists are stored as JSON files in the "
                                "playlists/ folder.\n\nCurrently loaded playlists are automatically saved in the config file, "
                                "but if you want to be able to create a new playlist and load this one back later you'll need to "
                                "save it.\n\nYou will be prompted to enter a name. If you enter the name of any existing playlist, "
                                "it will overwrite it without warning. If this playlist was already saved/loaded, the title will be prefilled."
                                "\n\nThe current index is also stored in the playlist, so you can load where you left off."))
    global load_button
    load_button = create_button(first_row_frame, "LOAD", load,
                                help_title="LOAD PLAYLIST",
                                help_text=("Load a playlist from your list of saved playlists.\n\n"
                                "This will not interrupt the currently playing theme, but will load the playlist "
                                "and set the current index.\n\nPlaylists are stored in the playlists/ folder.\n\n"
                                "When shortcuts are enabled, the currently loaded playlist will auto save. This is "
                                "so I can load up another playlist, then go back while keeping the position. I don't "
                                "have a shortcut for saving, but if you were not using shortcuts you could just save manually "
                                "before loading a playlist if you want to."))
    global load_system_button
    load_system_button = create_button(first_row_frame, "📋", load_system_playlist,
                                help_title="LOAD SYSTEM PLAYLIST",
                                help_text=("Load a system playlist (Tagged, Favorite, Blind, Peek, Mute Peek, New, or Missing Artists themes).\n\n"
                                "These are special playlists managed by the application for marking and organizing themes."))
    global delete_button
    delete_button = create_button(first_row_frame, "❌", delete, True,
                                help_title="DELETE PLAYLIST",
                                help_text=("Delete a playlist from your list of saved playlists.\n\n"
                                "You will be asked to confirm when deleting."))
    
    global filter_button
    filter_button = create_button(first_row_frame, "FILTER", filters,
                                help_title="FILTER PLAYLIST",
                                help_text=("Open a window where you can create, apply, and save playlist filters.\n\n"
                                "The filter will apply to the currently selected playlist.\n\n"
                                "Saved filters are stored in the filters/ folder.\n\n" 
                                "The values are taken from the metadata files, so this will take a while to grab all "
                                "the metadata if you haven't already.\n\nThe Artists, Studios, and Tags filter all "
                                "will grab any themes that match just one of the selected items if you select multiple. "
                                "If you only want themes that match multiple items, you can run the filter another time "
                                "after filtering to one."))
    global load_filters_button
    load_filters_button = create_button(first_row_frame, "💾", load_filters,
                                help_title="APPLY SAVED FILTER",
                                help_text=("Apply a filter from your list of saved filters. You can save filters in the FILTER "
                                "button. The filter will apply to the currently selected playlist."))
    global delete_filters_button
    delete_filters_button = create_button(first_row_frame, "❌", delete_filters, True,
                                help_title="DELETE SAVED FILTER",
                                help_text=("Delete a filter from your list of saved filters.\n\n"
                                "You will be asked to confirm when deleting."))

    if playlist.get("infinite", False):
        global selected_difficulty

        selected_difficulty = tk.StringVar()
        selected_difficulty.set(difficulty_options[playlist["difficulty"]])
        global difficulty_dropdown
        difficulty_dropdown = ttk.Combobox(first_row_frame,
                                values=difficulty_options,
                                textvariable=selected_difficulty,
                                width=17,
                                height=len(difficulty_options),
                                state="readonly",
                                style="Black.TCombobox",
                                font=ROOT_FONT)
        difficulty_dropdown.pack(side="left")
        difficulty_dropdown.bind("<<ComboboxSelected>>", select_difficulty)
        blank_space(first_row_frame)
        if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
            popout_buttons_by_name.get("DIFFICULTY DROPDOWN").grid()
        if popout_buttons_by_name.get("SEARCH QUEUE"):
            popout_buttons_by_name.get("SEARCH QUEUE").config(text="ADD NEXT")
    else:
        if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
            popout_buttons_by_name.get("DIFFICULTY DROPDOWN").grid_remove()
        if popout_buttons_by_name.get("SEARCH QUEUE"):
            popout_buttons_by_name.get("SEARCH QUEUE").config(text="QUEUE NEXT")
        global sort_button
        sort_button = create_button(first_row_frame, "SORT", sort, True,
                                    help_title="SORT PLAYLIST",
                                    help_text=("Sorts the current playlist using one of the premade sorts.\n\n"
                                    "I think I covered every type of sort someone would want, " + 
                                    "but I could add more later if needed."))

        global randomize_playlist_button
        randomize_playlist_button = create_button(first_row_frame, "SHUFFLE", randomize_playlist,
                                    help_title="SHUFFLE PLAYLIST",
                                    help_text=("Randomizes the current playlist.\n\n" +
                                    "This is a completely random shuffle. For a weighted shuffle, hit the ⚖️ button "
                                    "next to this one.\n\n" +
                                    "You will be asked to confirm when shuffling"))
        global weighted_randomize_playlist_button
        weighted_randomize_playlist_button = create_button(first_row_frame, "⚖️", weighted_randomize, True,
                                    help_title="WEIGHTED SHUFFLE PLAYLIST",
                                    help_text=("Apply a weighted shuffle to the current playlist.\n\n"
                                                "This will try to balance popular/niche and old/new anime "
                                                "while still randomizing to some extent. It also tries to "
                                                "avoid the same series appearing too close to itself.\n\n"
                                                "This is meant to give more variety during trivia sessions.\n\n"
                                                "The exact logic involves sorting the list by popularity, "
                                                "then splitting by 3. After that each third is sorted by "
                                                "year and split into 3. Each of the 9 parts are then shuffled. "
                                                "They are then staggered into a new list, but in a random order every "
                                                "9 to try and create a balanced, but not too formulaic order. Lastly "
                                                "titles from the same series are moved around if they are too close. "
                                                "How close they can be is determined by playlist size."))
    
    global settings_button
    settings_button = create_button(first_row_frame, "⚙️", show_settings_popup, True,
                                      help_title="CONFIGURATION SETTINGS",
                                      help_text=("Open settings menu to edit configuration values.\n"
                                                 "\nVolume Level: Sets the default volume for the player."
                                                 "\n\nStream Volume Boost: Additional volume boost for streaming audio output."
                                                 "\n\nBackground and Text Colors: Edit the background and highlight colors used in the application. Can add/delete custom colors."
                                                 "\n\nInverted Positions: Makes lighting round timer be on left instead of right. Good if you keep the scoreboard on the right."
                                                 "\n\nHalf Points: Enable half points for bonus question pop-ups."
                                                 "\n\nNon WebM OpenGL: Enable/disable non-WebM OpenGL acceleration for video playback."
                                                 "\n\nScale Main UI: Scaling factor for the main user interface elements. Requires restart to take effect."
                                                 "\n\nYouTube API Key: Required to be able to play clips from YouTube. for Clip and OST Lightning rounds."
                                                 "\n\nOpenAI API Key: Required for Trivia and Emoji Lightning rounds."
                                                 "\n\nTitle Only Info Text: Text that appears above the title only information popup."
                                                 "\n\nEnd Session Text: Text that can replace 'THANKS FOR PLAYING!' message on the end session screen."
                                                 ""))
    
    global help_button
    help_button = create_button(first_row_frame, "HELP", lambda:show_button_help("HELP", 
                                                                                ("Right click any button for an "
                                                                                "explanation of it's purpose and use.\n\n"
                                                                                "This application was created by Ramun Flame")),
                                    help_title="HELP",
                                    help_text=("It's just here to let people know you can right click things for explanations.\n\n"
                                    "If you are unsure where to start, go to the FOLDER: button, and right click it to "
                                    "see an explanation."))

# Second row
second_row_frame = tk.Frame(root, bg=BACKGROUND_COLOR)
second_row_frame.pack(pady=(0,5))

blind_button = create_button(second_row_frame, "BLIND[BKSP]", lambda: blind(True),
                                help_title="BLIND (Shortcut Key = 'backspace')",
                                help_text=("Covers the screen. Will be a color matching the average color of the screen. "
                                            "If a video is playing, it will display a progress bar."))
blind_round_button = create_button(second_row_frame, "👁", toggle_blind_round, True,
                                help_title="[B]LIND ROUND (Shortcut Key = 'b')",
                                help_text=("Enables the next video to play as a 'Blind Round'. A blind round plays normally, "
                                            "but will cover the screen at the start to make it audio only. This is only lasts "
                                            "for one video, and the blind can be removed with the normal BLIND toggle."))

peek_button = create_button(second_row_frame, "PEEK[=]", toggle_peek, False,
                                help_title="PEEK OVERLAY (Shortcut Key = '=')",
                                help_text=("Covers the screen except for a small peek window. Picks one of three variants at random."))
narrow_peek_button = create_button(second_row_frame, "◀", narrow_peek, False,
                                help_title="NARROW PEEK OVERLAY (Shortcut Key = '[')",
                                help_text=("Narrows the gap of the peek window."))
widen_peek_button = create_button(second_row_frame, "▶", widen_peek, False,
                                help_title="WIDEN PEEK OVERLAY (Shortcut Key = ']')",
                                help_text=("Widens the gap of the peek window."))
peek_round_button = create_button(second_row_frame, "👀", toggle_peek_round, True,
                                help_title="PEEK ROUND (Shortcut Key = 'b','b')",
                                help_text=("Enables the next video to play as a 'Peek Round'. A peek round plays normally, "
                                            "but will cover most of the screen at the start, only showing a small moving window. "
                                            "The peek can be removed with the normal PEEK toggle."))

mute_button = create_button(second_row_frame, "[M]UTE", toggle_mute, False,
                                help_title="[M]UTE THEME AUDIO (Shortcut Key = 'm')",
                                help_text=("Toggles muting the video audio."))
mute_peek_round_button = create_button(second_row_frame, "🔇", toggle_mute_peek_round, True,
                                help_title="MUTE PEEK ROUND (Shortcut Key = 'b','b','b')",
                                help_text=("Enables the next video to play as a 'Mute Peek Round'."
                                            "It is the same as the Peek Round, but will also mute the audio."))

guess_year_button = create_button(second_row_frame, "📅", lambda: guess_extra("year"), False,
                                help_title="[G]UESS YEAR (Shortcut Key = 'g')",
                                help_text=("Displays a pop-up at the top informing players to guess the year. "
                                            "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_score_button = create_button(second_row_frame, "🏆", lambda: guess_extra("score"), False,
                                help_title="GUESS SCORE (Shortcut Key = 'g','g')",
                                help_text=("Displays a pop-up at the top informing players to guess the score. "
                                            "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_popularity_button = create_button(second_row_frame, "🥇", lambda: guess_extra("popularity"), False,
                                help_title="GUESS POPULARITY (Shortcut Key = 'g','g','g')",
                                help_text=("Displays a pop-up at the top informing players to guess the popularity. "
                                            "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_members_button = create_button(second_row_frame, "👥", lambda: guess_extra("members"), False,
                                help_title="GUESS MEMBERS (Shortcut Key = 'g','g','g','g')",
                                help_text=("Displays a pop-up at the top informing players to guess the members. "
                                            "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_tags_button = create_button(second_row_frame, "🔖", lambda: guess_extra("tags"), False,
                                help_title="[G]UESS TAGS (Shortcut Key = 'n')",
                                help_text=("Displays a pop-up at the top informing a player to guess the tags. "
                                            "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_studio_button = create_button(second_row_frame, "🏢", lambda: guess_extra("studio"), False,
                                help_title="GUESS STUDIO (Shortcut Key = 'h')",
                                help_text=("Displays a pop-up for guessing the studio that produced the anime. "
                                        "Multiple choice: 1 correct, 3 distractors."))
guess_song_button = create_button(second_row_frame, "🎵", lambda: guess_extra("song"), False,
                                help_title="GUESS SONG (Shortcut Key = 'h','h')",
                                help_text=("Displays a pop-up for guessing the song title for this anime. Multiple choice: 1 correct, 3 distractors."))
guess_artist_button = create_button(second_row_frame, "🎤", lambda: guess_extra("artist"), False,
                                help_title="GUESS ARTIST (Shortcut Key = 'h','h','h')",
                                help_text=("Displays a pop-up for guessing the artist who performed the song for this anime. "
                                        "Multiple choice: 1 correct, 3 distractors."))
guess_multiple_button = create_button(second_row_frame, "４", lambda: guess_extra("multiple"),
                                help_title="GUESS MULTIPLE (Shortcut Key = 'u')",
                                help_text=("Displays a pop-up at the top informing a player to guess the anime from a multiple choice. "
                                            "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_characters_button = create_button(second_row_frame, "👤", lambda: guess_extra("characters"), True,
                                help_title="GUESS CHARACTERS (Shortcut Key = 'j')",
                                help_text=("Displays a pop-up at the top informing a player to guess 2 characters from the anime from a multiple choice. "
                                            "It also lists the rules. Opening the Info Popup or toggling again will reveal the answer, then remove it if pressed again."))

# Define the Lightning Round modes and their metadata
light_mode_options = [
    (key, f"{mode['icon']} {key.upper()}")
    for key, mode in light_modes.items()
    if key != "variety"
]

# Mapping from display string ("ICON NAME") back to the key
title_to_key = {display: key for key, display in light_mode_options}

# Tkinter StringVar for the current selection
selected_mode = StringVar(value=light_mode_options[0][1])  # default to first display string

style = ttk.Style()
style.theme_use('clam')
def configure_style():
    global style
    style.configure("Black.TCombobox",
                    fieldbackground="black",   # background of selected value
                    background="black",        # dropdown arrow area
                    foreground="white",        # text color
                    arrowcolor="white",        # arrow color
                    justify='center')        

    # Also style the readonly state explicitly
    style.map("Black.TCombobox",
        fieldbackground=[('readonly', 'black')],
        foreground=[('readonly', 'white')]
    )
configure_style()
# Create the combobox
light_dropdown = ttk.Combobox(second_row_frame,
                        values=[display for _, display in light_mode_options],
                        textvariable=selected_mode,
                        width=15,
                        height=len(light_mode_options),
                        state="readonly",
                        style="Black.TCombobox",
                        font=ROOT_FONT)
light_dropdown.current(0)
light_dropdown.pack(side="left")

def unhighlight_selection(event, setting=False):
    if popout_buttons_by_name.get(light_dropdown):
        value = light_dropdown.get()
        popout_buttons_by_name[light_dropdown].set(value)
    if not setting and light_mode:
        select_lightning_mode()
    light_dropdown.selection_clear()
    light_dropdown.icursor(tk.END)

light_dropdown.bind("<<ComboboxSelected>>", unhighlight_selection)

# Start button using selected mode
def select_lightning_mode():
    selected_display = selected_mode.get()
    mode_key = title_to_key[selected_display]
    toggle_light_mode(mode_key)

start_light_mode_button = create_button(second_row_frame, "▶", select_lightning_mode, False,
                              help_title="START LIGHTNING ROUND",
                              help_text=("Start the selected lighting round type. Instructions will appear in the pop-up at the end of the theme."
                                         "\nDuring many rounds, music will play in the background. This is loaded from the music/ folder. "
                                         "I recommend something low energy, since if you use something too intense "
                                         "it's kinda grating with the constant music switching. "
                                         "I recommend the following tracks:\n\n"
                                         "Fullmetal Alchemist Brotherhood [OST] - Interlude\n"
                                         "Land of the Lustrous [OST] - Early Afternoon\n"
                                         "Katanagatari [OST] - DUB TRIP"))
variety_light_mode_button = create_button(second_row_frame, "🎲", lambda: toggle_light_mode("variety"), False,
                              help_title="[V]ARIETY LIGHTNING ROUND (Shortcut Key = 'v')",
                              help_text=("Lightning Round variant using the following rules:\n\n" + light_modes["variety"]["desc"] +
                                         "\n\nThis mode ensures no round is repeated consecutively, and picks rounds "
                                         "taking the show's popularity into account. So you aren't likely to get a Clues round "
                                         "unless a quite popular show appears."))
variety_light_mode_button.bind("<Button-2>", test_variety_distrbution)
light_mode_settings_button = create_button(second_row_frame, "🛠", open_settings_editor, True,
                              help_title="LIGHTNING ROUND SETTINGS",
                              help_text=("Edit settings for lightning rounds and manage variety round settings.\n\n"
                                         "LENGTH: Duration of round.\n\n"
                                         "MUTED: If round has theme sound or not. Will play background tracks if true\\nn"
                                         "VARIANTS(on some): Enable and disable variants for round.\n\n"
                                         "CHARACTER_TYPES(on c. rounds): Enable/diable different character types form appearing. popularity_limit wil use popularity to decide if secondary or appears characters should appear.\n\n"
                                         "VARIETY: Different settings for controlling what appears in variety rounds.\n\n"
                                         "VARIETY/ENABLED: Allowed or not allowed to appear in variety rounds.\n\n"
                                         "VARIETY/POPULARITY: Settings to limit popularity allowed and frequency of round.\n\n"
                                         "VARIETY/POPULARITY/RANGE: Popularity range of shows allowed to use this round.\n\n"
                                         "VARIETY/POPULARITY/WEIGHT: How likely it should appear. Sometimes split by OP/ED.\n\n"
                                         "VARIETY/COOLDOWN: Settings for how often a round can/is forced to appear.\n\n"
                                         "VARIETY/COOLDOWN/MIN_GAP: How long a round must wait to appear again.\n\n"
                                         "VARIETY/COOLDOWN/MAX_GAP: How long before a round is forced to appear.\n\n"
                                         "VARIETY/COOLDOWN/POPULARITY_FORCE_THRESHOLD: Minimum popularity a theme must be to be forced. Sometimes split by OP/ED.\n\n"
                                         "VARIETY/COOLDOWN/NO_REPEAT_LIMIT: How long until this round can use the same content. This also controls how much history of this lightning round is stored in the playlist.\n\n"
                                         "Changes will only stay between launches if saved."))


show_youtube_playlist_button = create_button(second_row_frame, "[Y]OUTUBE VIDEOS", show_youtube_playlist,
                              help_title="[Y]OUTUBE VIDEOS (Shortcut Key = 'y')",
                              help_text=("Lists downloaded YouTube videos to queue up.\n\nVideos are added using the '➕' button. "
                                         "The downloads are stored in the youtube/ folder.\n\n"
                                         "Videos are queued with a UP NEXT popup when selected, and will play after the current theme. "
                                         "Only one video may be queued at a time, and selecting the same video will unqueue it."))
manage_youtube_button = create_button(second_row_frame, "➕", open_youtube_editor, True,
                              help_title="MANAGE YOUTUBE VIDEOS",
                              help_text=("Opens an interface for managing YouTube videos. Press [ADD VIDEO FROM URL] to add one. It takes a few seconds to retrieve the video information, so please wait after clicking. Here's an explanation of each field:"
                                         "\n\nVIDEO ID: ID of YouTube video from URL. "
                                         "\n\nTITLE: Title that will show in the interface. Can be changed freely. Use [⟳] to reset it back to default."
                                         "\n\nSTART/END: Start/end time of video. Use the [NOW] button to set it to the player's current time. "
                                         "Useful if you want to cut out intros/outros. Use [⟳] to reset each back to default."
                                         "\n\n[▶]: Play the video. Good for testing the video, and setting start/end times."
                                         "\n\n[ARCHIVE]: Archives the video. Useful if you don't want it to show up in the interface, but don't want to delete it."
                                         "\n\n[❌] Delete the video. Also deletes file if downloaded."
                                         "\n\n[SAVE ALL] Save any changes. Many functions auto-save, but any title, start, or end changes need to be saved manually."
                                         "\n\n[SHOW ARCHIVED] Show archived videos. From here, videos can be restored or deleted."))

search_button = create_button(second_row_frame, "[S]EARCH DIRECTORY", search,
                            help_title="[S]EARCH (Shortcut Key = 's')",
                            help_text=("Search the filenames, titles, and english titles for the entered keyword. "
                                        "The selected theme will queue up to play next, or play if nothing "
                                        "is currently playing.\n\nOnly one theme can be queued up at a time. "
                                        "Selecting the same theme again will clear the queue. This does not add the "
                                        "theme to the playlist. For that function, use the adjacent + button. This "
                                        "function was created so a theme could be pulled up on the fly, but not "
                                        "interrupt the current playlist.\n\n"
                                        "The search behaves differently when hotkeys are enabled. Instead of a dialogue, "
                                        "the search takes all keypresses and refreshes the search with each keypress. "
                                        "You must hit ESC to exit this mode. Lists also function different with shortcuts " 
                                        "enabled. You can read about the controls by hitting the SHORTCUT [K]EYS button."))
add_search_button = create_button(second_row_frame, "➕ADD TO PLAYLIST", search_add, True,
                            help_title="SEARCH ADD",
                            help_text=("The same as the SEARCH, but will add the theme to the playlist "
                                        "instead of just queueing it.\n\nThis was more of an after thought feature "
                                        "just in case you want to add some themes that were maybe removed, or added "
                                        "later. It would be kinda slow with the dialogue popping up each time, but it "
                                        "may be fast with shortcuts enabled, as described on the SEARCH button. You could "
                                        "also use this to add tracks to an empty playlist to create your own from scratch."))

global stats_button
stats_button = create_button(second_row_frame, "📊", display_theme_stats_in_columns,
                                help_title="THEME DIRECTORY/STATS",
                                help_text=("Shows detailed stats of themes in directory."))

third_row_frame = tk.Frame(root, bg=BACKGROUND_COLOR)
third_row_frame.pack(pady=(0,0))

info_button = create_button(third_row_frame, "[I]NFORMATION POP-UP", toggle_info_popup,
                              help_title="SHOW/HIDE [I]NFO POPUP (Shortcut Key = 'i')",
                              help_text=("Show or hide the information popup at the bottom of the screen.\n\n"
                                         "This shows most of the information from the main player in a nicer format. "
                                         "During trivia, if someone gets the answer correct or people give up, "
                                         "this can be toggled to let them know the answer/more information.\n\n"
                                         "The popup will automatically close when the theme ends."))
title_info_button = create_button(third_row_frame, "𝕋", toggle_title_info_popup,
                              help_title="SHOW/HIDE TITLE POPUP (Shortcut Key = 'o')",
                              help_text=("Show or hide the title popup at the bottom of the screen.\n\n"
                                         "Additional text can be set/added to the top by middle clicking this button."))
title_info_button.bind("<Button-2>", prompt_title_top_info_text)

start_info_button = create_button(third_row_frame, "⏪", toggle_auto_info_start,
                              help_title="TOGGLE AUTO INFO POPUP AT START",
                              help_text=("When enabled, will show the theme's info popup at the start.\n\n"
                                         "Useful if you aren't doing trivia, and just want th info displayed as you watch."))
end_info_button = create_button(third_row_frame, "⏩", toggle_auto_info_end, True,
                              help_title="TOGGLE AUTO INFO POPUP AT END",
                              help_text=("When enabled, will show the theme's info popup during the last 8 seconds.\n\n"
                                         "Useful if you want to go more hands off with the trivia, and just show the answer at the end."))

tag_button = create_button(third_row_frame, "❌", tag, False,
                              help_title="[T]AG THEME (Shortcut Key = 't')",
                              help_text=("Adds the currently playing theme to a 'Tagged Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nThe purpose is to tag "
                                         "themes you may need to check out later for various reasons. "
                                         "Like adding censors, updating the theme, or even deleting it. "
                                         "Just a reminder.\n\nMiddle click to bulk mark/unmark entire playlist: "
                                         "If current item is marked, all items will be unmarked. If current item is not marked, all items will be marked. "
                                         "Requires confirmation before proceeding."))
tag_button.bind("<Button-2>", bulk_tag_playlist)
favorite_button = create_button(third_row_frame, "❤", favorite, False,
                              help_title="FAVORITE THEME (Shortcut Key='*')",
                              help_text=("Adds the currently playing theme to a 'Favorite Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nJust a way to keep track of your favorite themes."
                                         "\n\nMiddle click to bulk mark/unmark entire playlist: "
                                         "If current item is marked, all items will be unmarked. If current item is not marked, all items will be marked. "
                                         "Requires confirmation before proceeding."))
favorite_button.bind("<Button-2>", bulk_favorite_playlist)
blind_mark_button = create_button(third_row_frame, "👁", blind_mark, False,
                              help_title="BLIND MARK THEME",
                              help_text=("Adds the currently playing theme to a 'Blind Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nThemes in this list will auto queue those types of rounds."
                                         "\n\nMiddle click to bulk mark/unmark entire playlist: "
                                         "If current item is marked, all items will be unmarked. If current item is not marked, all items will be marked. "
                                         "Blind marks are mutually exclusive with Peek and Mute Peek marks - existing conflicting marks will be removed first. "
                                         "Requires confirmation before proceeding."))
blind_mark_button.bind("<Button-2>", bulk_blind_mark_playlist)
peek_mark_button = create_button(third_row_frame, "👀", peek_mark, False,
                              help_title="PEEK MARK THEME",
                              help_text=("Adds the currently playing theme to a 'Peek Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nThemes in this list will auto queue those types of rounds."
                                         "\n\nMiddle click to bulk mark/unmark entire playlist: "
                                         "If current item is marked, all items will be unmarked. If current item is not marked, all items will be marked. "
                                         "Peek marks are mutually exclusive with Blind and Mute Peek marks - existing conflicting marks will be removed first. "
                                         "Requires confirmation before proceeding."))
peek_mark_button.bind("<Button-2>", bulk_peek_mark_playlist)
mute_peek_mark_button = create_button(third_row_frame, "🔇", mute_peek_mark, True,
                              help_title="MUTE PEEK MARK THEME",
                              help_text=("Adds the currently playing theme to a 'Mute Peek Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nThemes in this list will auto queue those types of rounds."
                                         "\n\nMiddle click to bulk mark/unmark entire playlist: "
                                         "If current item is marked, all items will be unmarked. If current item is not marked, all items will be marked. "
                                         "Mute Peek marks are mutually exclusive with Blind and Peek marks - existing conflicting marks will be removed first. "
                                         "Requires confirmation before proceeding."))
mute_peek_mark_button.bind("<Button-2>", bulk_mute_peek_mark_playlist)


refetch_metadata_button = create_button(third_row_frame, "RE[F]ETCH METADATA", refetch_metadata,
                              help_title="RE[F]ETCH THEME METADATA (Shortcut Key = 'f')",
                              help_text=("Refetch the metadata for the currently playing theme.\n\n"
                                         "You may want to do this if there's mising information that "
                                         "may have been filled by now, or you want to update the score/ "
                                         "members stats. For that purpose though, you can enable auto refresh "
                                         "of jikan metadata by hitting the ♻ button."))
fetch_missing_metadata_button = create_button(third_row_frame, "❓", fetch_all_metadata,
                              help_title="FETCH ALL MISSING METADATA",
                              help_text=("Use this to check if metadata exists for all files in the chosen "
                                         "directory, and fetch metadata for any that are missing. You should do "
                                         "this whenever you have new videos in the directory.\n\n"
                                         "It can take quite a while depending on how many themes you have. "
                                         "It may need to be left overnight if you have thousands."))
refresh_all_metadata_button = create_button(third_row_frame, "⭮", refresh_all_metadata, False,
                              help_title="REFRESH ALL JIKAN METADATA",
                              help_text=("Refreshes the jikan metadata for files in your directory. "
                                         "You can specify how many years back to refresh (e.g., '3' for last 3 years) "
                                         "or leave empty to refresh all years. Only refreshes data for anime you actually have files for, "
                                         "not everything in the metadata database.\n\n"
                                         "You may want to do this if you feel the score and members data are outdated, "
                                         "although you could also use the ♻ button to toggle auto refreshing the data "
                                         "as files are playing if you don't want to have it call for all the files at once."))
toggle_refresh_metadata_button = create_button(third_row_frame, "♻", toggle_auto_auto_refresh, True,
                              help_title="TOGGLE AUTO REFRESH JIKAN METADATA",
                              help_text=("Toggle auto refreshing jikan metadata. This will refresh the "
                                         "jikan metadata for the currently playing theme, and the next "
                                         "theme as you play them. It will never refresh the same anime in the same session."
                                         "\n\nThis is for the score and members data, which changes "
                                         "over time. It's not too necessary if you don't care about it being up "
                                         "to date, or if you've already grabbed the metadata recently.\n\n"
                                         "It doesn't refetch everything, or call the AnimeThemes API like "
                                         "the regular [R]EFETCH does for the current theme. If you "
                                         "want to to do that for all files, you would need to delete the "
                                         "anime_metadata.json file in the metadata/ folder, and fetch "
                                         "all missing metadata again, but I wouldn't recommend that."))

toggle_censor_bar_button = create_button(third_row_frame, "[C]ENSOR(0)", toggle_censor_bar, False, enabled=censors_enabled,
                              help_title="TOGGLE [C]ENSOR BARS (Shortcut Key = 'c')",
                              help_text=("Toggle censor bars. These are pulled from the censors.json file in the files/ "
                                         "folder. Additonal censors are also loaded from any json files with 'censor' in the title. "
                                         "You can add these using the [➕] button next to this one.\n\n"
                                         "The point of this feature is to mainly block out titles that show up too early, "
                                         "since this is a trivia program. They always assume the video is fullscreen, on "
                                         "the main monitor, so it will be weird if you try playing in a window. I would have disabled them "
                                         "when vlc isn't fulscreen, but checking that isn't reliable."))
edit_censors_button = create_button(third_row_frame, "➕", open_censor_editor, True,
                              help_title="CENSORS EDITOR",
                              help_text=("Opens an interface for editing censors. Press [ADD NEW CENSOR] to add one. Here's an explanation of each field."
                                         "\n\nSIZE/POSITION: The size/position of the censor box, in percent of screen. "
                                         "Use the [🎯] button to draw a censor box, and the SIZE/POSITION will be filled. Middle-click the overlay to cancel."
                                         "\n\nSTART/END: Start/end time censor box will appear. Use the [NOW] button to set it to the player's current time. "
                                         "Use the [-]/[+] to adjust by 0.1 sec. The end time can usually be exact, but the start needs to be a bit before to account for the time to pop up."
                                         "\n\nCOLOR: Color of censor box. Will automatically pick the average color of the screen. Use [PICK] to select a specific color from the screen. Middle-click the overlay to cancel."
                                         " Use [X] to reset back to AUTO."
                                         "\n\nNSFW: Used to mark a censor as NSFW. These censors will appear even when the Information Pop-up is up."
                                         "\n\nUse [TEST] to play the video from a second before the censor start time to test it. Right-clicking will play from the end time. Censors will not appear until the [SAVE CENSOR(S)] button "
                                         "is pressed. This must be pressed again after every change for it to take effect. To delete censors, use the [DELETE] button. This will also only save if the "
                                         "[SAVE CENSOR(S)] button is pressed. Lastly, censors are all linked to the filename."))

toggle_progress_bar_button = create_button(third_row_frame, "PROGRESS BAR", toggle_progress_bar, True, enabled=progress_bar_enabled,
                              help_title="TOGGLE PROGRESS BAR OVERLAY",
                              help_text=("This toggles a progress bar overlay for the current time for the theme.\n\n"
                                         "It's pretty thin, and meant to be subtle as to not obstruct the theme."))

desktop_black_button = create_button(
    third_row_frame,
    "DESKTOP BLACK",
    toggle_desktop_black_overlay,
    True,
    help_title="DESKTOP BLACK SCREEN",
    help_text="Covers the desktop with a black screen behind all windows. Useful for hiding the desktop during a session."
)

toggle_disable_shortcuts_button = create_button(third_row_frame, "ENABLE SHORTCUTS[`]", toggle_disable_shortcuts,
                              help_title="ENABLE SHORTCUTS (Shortcut Key = '`')",
                              help_text=("Used to toggle shortcut keys.\n\nIn my current setup, I am streaming my desktop to "
                                         "one screen, and do not have access to a second monitor to manage the "
                                         "application. I stream the applicaiton window to another display, but I can't interact with it. "
                                         "So I've mapped all the functions I may want to use during a session to shortcut keys. "
                                         "It may be hard to track them all, but most buttons have the shortcut key on them.\n\n"
                                         "For a full reference, use the SHORTCUT [K]EYS button.\n\nAlso when this is enabled, "
                                         "lists greater than 50 items no longer have buttons. The buttons slow down things a bit, and since they "
                                         "aren't needed if I'm using shortcuts, I disabled them."))

list_keyboard_shortcuts_button = create_button(third_row_frame, "[K]EYS", list_keyboard_shortcuts, True,
                              help_title="LIST SHORTCUT [K]EYS (Shortcut Key = 'k')",
                              help_text=("Lists all shortcut keys on the application.\n\nAlthough all are listed in uppercase for clarity "
                                         "it only accepts inputs in lowercase.\n\nThe scoreboard stuff at the "
                                         "bottom is actually a separate application that pulls scores from a google "
                                         "sheet I update during the session, and can be ignored. The scoreboard is pretty specific to "
                                         "the format of my google sheet. I could probably share it though if anyone asked.\n\n"
                                         "The up/down arrows have two functions. When a list is up, they control which you are "
                                         "highlighting to select. Otherwise, they scroll all the columns up/down."))

end_button = create_button(third_row_frame, "[E]ND SCREEN", end_session,
                              help_title="[E]ND SESSION MESSAGE (Shortcut Key = 'e')",
                              help_text="Displays an end message 'THANKS FOR PLAYING!' slowly scrolling "
                              "up the right side of the screen. Just a nice way for me to end my trivia sessions.\n\n"
                              "It also lists the 'TOTAL THEMES PLAYED:', which are tracked while the application is running.\n\n" \
                              "The end message can be set by middle clicking this button.")
end_button.bind("<Button-2>", prompt_end_session_text)

info_panel = tk.Frame(root, bg="black")
info_panel.pack(fill="both", expand=True, padx=scl(10, "UI"), pady=scl(5, "UI"))

# Left Column
left_column = tk.Text(info_panel, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                      insertbackground="white", state=tk.DISABLED,
                      selectbackground=HIGHLIGHT_COLOR, wrap="word")
left_column.pack(side="left", fill="both", expand=True)

# Middle Column
middle_column = tk.Text(info_panel, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                        insertbackground="white", state=tk.DISABLED,
                        selectbackground=HIGHLIGHT_COLOR, wrap="word")
middle_column.pack(side="left", fill="both", expand=True)

# === RIGHT COLUMN CONTAINER ===
right_column_container = tk.Frame(info_panel, bg="black")
right_column_container.pack(side="left", fill="both", expand=True)

# Top Shorter Column (e.g., header, stats, etc.)
right_top = tk.Text(right_column_container, height=0, width=scl(40, "UI"), bg="black", fg="white",
                    insertbackground="white", state=tk.DISABLED,
                    selectbackground=HIGHLIGHT_COLOR, wrap="word")
right_top.pack(fill="x")

# Main Right Column
right_column = tk.Text(right_column_container, height=scl(20, "UI"), width=scl(40, "UI"), bg="black", fg="white",
                       insertbackground="white", state=tk.DISABLED,
                       selectbackground=HIGHLIGHT_COLOR, wrap="word",
                       spacing1=0, spacing2=0, spacing3=0)
right_column.pack(fill="both", expand=True)

# Add drag-and-drop bindings to the text widget for better drop detection
right_column.bind("<B1-Motion>", lambda e: handle_drag_motion(e) if drag_start_index is not None else None)
right_column.bind("<ButtonRelease-1>", lambda e: end_playlist_drag(e) if drag_start_index is not None else None)

# Add mouse wheel bindings for any list pagination
def handle_list_scroll(event):
    if list_loaded:
        if hasattr(event, 'delta') and event.delta > 0:  # Scroll up
            list_scroll_up()
        elif hasattr(event, 'delta') and event.delta < 0:  # Scroll down
            list_scroll_down()
        return "break"  # Prevent default scrolling behavior
    return None

def handle_btn_scroll_up(e):
    if list_loaded:
        list_scroll_up()
        return "break"
    return None

def handle_btn_scroll_down(e):
    if list_loaded:
        list_scroll_down()
        return "break"
    return None

right_column.bind("<MouseWheel>", handle_list_scroll)
right_column.bind("<Button-4>", lambda e: handle_btn_scroll_up(e))  # Linux scroll up
right_column.bind("<Button-5>", lambda e: handle_btn_scroll_down(e))  # Linux scroll down

# Video controls
controls_frame = tk.Frame(root, bg="black")
controls_frame.pack(pady=0, fill="x", expand=False)
controls_frame.pack_propagate(False)  # Prevent children from controlling frame size
controls_frame.configure(height=scl(80, "UI"))  # Set fixed height for controls

# Volume Control
def set_volume(value):
    """Sets the volume based on value input (0 to 100)."""
    global volume_level
    volume_level = int(value)
    player.audio_set_volume(volume_level)  # Adjust VLC volume
    if music_loaded:
        pygame.mixer.music.set_volume(0.2*(volume_level/100))  # Adjust volume
    update_volume_display()

def update_volume_display():
    """Update the volume label display."""
    volume_label.config(text=str(volume_level))

def increase_volume():
    """Increase volume by 5."""
    global volume_level
    volume_level = min(200, volume_level + 5)
    set_volume(volume_level)

def decrease_volume():
    """Decrease volume by 5."""
    global volume_level
    volume_level = max(0, volume_level - 5)
    set_volume(volume_level)

# Volume control container
volume_container = tk.Frame(controls_frame, bg="black", highlightbackground="white", highlightthickness=2, padx=2, pady=2)
volume_container.pack(side="left", padx=(scl(10, "UI"), scl(5, "UI")))

# Left side: icon and number
volume_left_frame = tk.Frame(volume_container, bg="black")
volume_left_frame.pack(side="left", padx=(2, 0))

# Volume icon
volume_icon = tk.Label(volume_left_frame, text="🔊", bg="black", fg="white", 
                        font=("Arial", scl(12, "UI"), "bold"), pady=0)
volume_icon.pack(pady=0)

# Volume label (displays current volume)
volume_label = tk.Label(volume_left_frame, text=str(volume_level), bg="black", fg="white", 
                         font=("Arial", scl(14, "UI"), "bold"), width=3, pady=0)
volume_label.pack(pady=0)

# Right side: buttons
volume_buttons_frame = tk.Frame(volume_container, bg="black")
volume_buttons_frame.pack(side="left", padx=(0, 2))

# Volume up button
volume_up_button = tk.Button(volume_buttons_frame, text="➕", command=increase_volume, bg="black", fg="white", 
                              font=("Arial", scl(12, "UI"), "bold"), border=0, width=2, height=1, pady=0)
volume_up_button.pack(pady=0)

# Volume down button
volume_down_button = tk.Button(volume_buttons_frame, text="➖", command=decrease_volume, bg="black", fg="white", 
                                font=("Arial", scl(12, "UI"), "bold"), border=0, width=2, height=1, pady=0)
volume_down_button.pack(pady=0)

play_pause_button = tk.Button(controls_frame, text="⏯", command=play_pause, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
play_pause_button.pack(side="left", padx=0)

stop_button = tk.Button(controls_frame, text="⏹", command=stop, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
stop_button.pack(side="left", padx=0)

previous_button = tk.Button(controls_frame, text="⏮", command=play_previous, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
previous_button.pack(side="left", padx=0)

next_button = tk.Button(controls_frame, text="⏭", command=play_next, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2)
next_button.pack(side="left", padx=0)

autoplay_toggle = 0
def toggle_autoplay():
    global autoplay_toggle
    autoplay_toggle += 1
    if autoplay_toggle == 3:
        autoplay_toggle = 0
    if autoplay_toggle == 0:
        autoplay_button.configure(text="🔁", fg="white")
    elif autoplay_toggle == 1:
        autoplay_button.configure(text="🔂", fg="white")
    elif autoplay_toggle == 2:
        autoplay_button.configure(text="🔁", fg=HIGHLIGHT_COLOR)

autoplay_button = tk.Button(controls_frame, text="🔁", command=toggle_autoplay, bg="black", fg="white", font=("Arial", scl(30, "UI"), "bold"), border=0, width=2, anchor="center", justify="center")
autoplay_button.pack(side="left", padx=0, pady=(0,scl(15, "UI")))

# Seek bar
seek_bar = tk.Scale(controls_frame, from_=0, to=1000, orient=tk.HORIZONTAL, command=seek, length=2000, resolution=0.1, bg="black", fg="white")
seek_bar.pack(side="left", fill="x", padx=(scl(5, "UI"),scl(10, "UI")))

left_font_name = "Arial"
middle_font_name = "Arial"
right_font_name = "Arial"

# Text formatting tags
left_column.tag_configure("bold", font=(left_font_name, scl(12, "UI"), "bold"), foreground="white")
left_column.tag_configure("underline", underline=True)
middle_column.tag_configure("bold", font=(middle_font_name, scl(12, "UI"), "bold"), foreground="white")
middle_column.tag_configure("highlight", background="#333333", foreground="white", font=(middle_font_name, scl(12, "UI"), "bold"))  # Dark gray highlight
middle_column.tag_configure("underline", underline=True)
right_column.tag_configure("bold", font=(right_font_name, scl(12, "UI"), "bold"), foreground="white")
right_column.tag_configure("highlight", background=HIGHLIGHT_COLOR, foreground="white", font=(right_font_name, scl(12, "UI"), "bold"))  # Dark gray highlight
right_column.tag_configure("highlightreg", background=HIGHLIGHT_COLOR, foreground="white", font=(right_font_name, scl(12, "UI")))  # Dark gray highlight
right_column.tag_configure("underline", underline=True)
left_column.tag_configure("white", foreground="white", font=(left_font_name, scl(12, "UI")))
left_column.tag_configure("blank", foreground="white", font=(left_font_name, scl(6, "UI")))
middle_column.tag_configure("white", foreground="white", font=(middle_font_name, scl(12, "UI")))
middle_column.tag_configure("blank", foreground="white", font=(middle_font_name, scl(6, "UI")))
right_column.tag_configure("white", foreground="white", font=(right_font_name, scl(12, "UI")))
right_column.tag_configure("blank", foreground="white", font=(right_font_name, scl(6, "UI")))
right_top.tag_configure("bold", font=(right_font_name, scl(12, "UI"), "bold"), foreground="white")
right_top.tag_configure("white", foreground="white", font=(right_font_name, scl(12, "UI")))

list_buttons = [
    {"button":"show_playlist_button", "label":"playlist", "func":show_playlist},
    {"button":None, "label":"field_list", "func":show_field_themes},
    {"button":"remove_button", "label":"remove", "func":remove_theme},
    {"button":"load_button", "label":"load_playlist", "func":load},
    {"button":"load_system_button", "label":"load_system_playlist", "func":load_system_playlist},
    {"button":"delete_button", "label":"delete_playlist", "func":delete},
    {"button":"load_filters_button", "label":"load_filters", "func":load_filter},
    {"button":"delete_filters_button", "label":"delete_filters", "func":delete_filter},
    {"button":"sort_button", "label":"sort", "func":sort},
    {"button":"search_button", "label":"search", "func":search},
    {"button":"add_search_button", "label":"search_add", "func":search_add},
    {"button":"show_youtube_playlist_button", "label":"youtube", "func":show_youtube_playlist}
]

# =========================================
#            *KEYBOARD SHORTCUTS
# =========================================

disable_shortcuts = True
def on_press(key):
    global disable_shortcuts
    try:
        if disable_shortcuts:
            pass
        # Arrow key movement for grow peek overlay (position only)
        elif grow_overlay_boxes and any(box.winfo_exists() for box in grow_overlay_boxes.values()):
            move_amount = 10  # pixels per key press
            if key == key.up:
                move_grow_position(0, -move_amount)
            elif key == key.down:
                move_grow_position(0, move_amount)
            elif key == key.left:
                move_grow_position(-move_amount, 0)
            elif key == key.right:
                move_grow_position(move_amount, 0)
        elif key == key.up:
            list_move(-1)
        elif key == key.down:
            list_move(1)
    except AttributeError:
        try:
            if list_loaded == "search":
                pass
            elif not playlist.get("infinite", False) and (key.char == '-'):
                player.set_time(player.get_time()-1000)
            elif not playlist.get("infinite", False) and (key.char == '+'):
                player.set_time(player.get_time()+1000)
        except AttributeError as e:
            print(f"Error: {e}")

def on_release(key):
    global disable_shortcuts
    try:
        if popout_searching:
            pass
        elif disable_shortcuts:
            try:
                if key.char == '`':
                    toggle_disable_shortcuts()
            except:
                pass
        elif list_loaded in ["search", "search_add"]:
            global search_term
            try:
                if key == key.esc:
                    search(add = playlist.get("infinite", False))
                elif key == key.backspace:
                    if search_term != "":
                        search_term = search_term[:-1]
                    search(True, add=playlist.get("infinite", False))
                elif key == key.space:
                    search_term = search_term + " "
                    search(True, add=playlist.get("infinite", False))
                elif key == key.enter:
                    list_select()
                    search_term = ""
                    list_unload(right_column)
            except AttributeError:
                search_term = search_term + key.char
                search(True, add=playlist.get("infinite", False))
        else:
            try:
                # Only handle left/right arrows for next/previous if grow_overlay_boxes is not active/visible
                if not (grow_overlay_boxes and any(box.winfo_exists() for box in grow_overlay_boxes.values())):
                    if key == key.right:
                        play_next()
                    elif key == key.left:
                        play_previous()
                if key == key.space:
                    play_pause()
                elif key == key.esc:
                    stop()
                elif key == key.tab:
                    player.toggle_fullscreen()
                elif key == key.backspace:
                    if (peek_overlay1 or edge_overlay_box or grow_overlay_boxes):
                        toggle_peek()
                    else:
                        blind(True)
                elif key == key.enter:
                    list_select()
            except AttributeError:
                if key.char == '`':
                    toggle_disable_shortcuts()
                elif key.char == 'm':
                    toggle_mute()
                elif key.char == 't':
                    tag()
                elif key.char == '*':
                    favorite()
                elif key.char == 'd':
                    dock_player()
                elif key.char == 'p':
                    show_playlist()
                elif key.char == 'y':
                    show_youtube_playlist()
                elif key.char.isdigit():
                    if list_loaded and list_loaded != "playlist":
                        global list_index
                        list_index = int(key.char)-1
                        list_select()
                    else:
                        seek_value = player.get_length()-((player.get_length()/10)*(10-int(key.char)))
                        player.set_time(int(seek_value))
                elif key.char == 'r':
                    if playlist.get("infinite", False) and playlist["current_index"] == len(playlist["playlist"])-2:
                        refetch_next_track()
                elif key.char == 'c':
                    toggle_censor_bar()
                elif key.char == 'k':
                    list_keyboard_shortcuts()
                elif key.char == 'l':
                    light_mode_keys = list(light_modes.keys())
                    try:
                        light_cycle_index = light_mode_keys.index(light_mode)
                        next_index = (light_cycle_index + 1) % len(light_mode_keys)
                    except ValueError:
                        next_index = 0  # fallback if current mode isn't found
                    mode = light_mode_keys[next_index]
                    if mode == 'variety':
                        toggle_light_mode()
                    else:
                        toggle_light_mode(mode)
                elif key.char == 'f':
                    refetch_metadata()
                elif key.char == 'n':
                    guess_extra("tags")
                elif key.char == 'u':
                    guess_extra("multiple")
                elif key.char == 'b':
                    if not (mute_peek_round_toggle or peek_round_toggle or blind_round_toggle):
                        toggle_blind_round()
                    elif not (peek_round_toggle or mute_peek_round_toggle):
                        toggle_peek_round()
                    else:
                        toggle_mute_peek_round()
                elif key.char in ['=', '+']:
                    toggle_peek()
                elif key.char == '[':
                    narrow_peek()
                elif key.char == ']':
                    widen_peek()
                elif key.char == 'v':
                    toggle_light_mode("variety")
                elif key.char == 'i':
                    toggle_info_popup()
                elif key.char == 'o':
                    toggle_title_info_popup()
                elif key.char == 'e':
                    end_session()
                elif key.char == 's':
                    search()
                elif key.char == 'g':
                    if guessing_extra not in ["year", "score", "popularity", "members"]:
                        guess_extra("year")
                    elif guessing_extra not in ["score", "popularity", "members"]:
                        guess_extra("score")
                    elif guessing_extra not in ["popularity", "members"]:
                        guess_extra("popularity")
                    else:
                        guess_extra("members")
                elif key.char == 'h':
                    if guessing_extra not in ["studio", "song", "artist"]:
                        guess_extra("studio")
                    elif guessing_extra not in ["song", "artist"]:
                        guess_extra("song")
                    else:
                        guess_extra("artist")
                elif key.char == 'j':
                    guess_extra("characters")
                elif playlist.get("infinite") and (key.char in ['<',',']):
                    if playlist["difficulty"] > 0:
                        playlist["difficulty"] -= 1
                        difficulty_dropdown.current(playlist["difficulty"])
                        select_difficulty()
                elif playlist.get("infinite") and (key.char in ['>','.']):
                    if playlist["difficulty"] < len(difficulty_options)-1:
                        playlist["difficulty"] += 1
                        difficulty_dropdown.current(playlist["difficulty"])
                        select_difficulty()
                elif key.char == 'a':
                    send_scoreboard_command("align")
                elif key.char == 'x':
                    send_scoreboard_command("extend")
                elif key.char == 'w':
                    send_scoreboard_command("shrink")
                elif key.char == 'z':
                    send_scoreboard_command("grow")
                elif key.char == 'q':
                    send_scoreboard_command("toggle")
    except AttributeError as e:
        print(f"Error: {e}")

# Mouse state tracking
mouse_left_pressed = False
mouse_dragging_grow_overlay = False
target_mouse_position = None
animation_after_id = None

def smooth_move_grow_overlay():
    """Smoothly animate the grow overlay toward the target mouse position."""
    global grow_position, target_mouse_position, animation_after_id
    
    if not mouse_dragging_grow_overlay or not target_mouse_position:
        animation_after_id = None
        return
    
    current_x, current_y = grow_position if grow_position else (0, 0)
    raw_target_x, raw_target_y = target_mouse_position
    
    # Apply offset so grow window appears at bottom-left of cursor (cursor won't block the window)
    # Incorporate gap_modifier to adjust offset based on grow overlay size
    base_offset_x = -50  # Base offset: 50 pixels to the left of cursor
    base_offset_y = -50  # Base offset: 50 pixels above cursor  
    
    # Scale offset by gap_modifier (starts at 0, increases by 1 each time grow is widened)
    offset_multiplier = (gap_modifier * 6)  # Increase offset by 50% per gap level
    offset_x = base_offset_x - offset_multiplier
    offset_y = base_offset_y - offset_multiplier
    
    target_x = raw_target_x + offset_x
    target_y = raw_target_y + offset_y
    
    # Calculate smooth movement (lerp with factor for smoothness)
    lerp_factor = 0.15  # Adjust this value: lower = smoother/slower, higher = faster
    new_x = current_x + (target_x - current_x) * lerp_factor
    new_y = current_y + (target_y - current_y) * lerp_factor
    
    # Update position
    grow_position = (int(new_x), int(new_y))
    toggle_grow_overlay(block_percent=last_grow_block_percent, position=grow_position)
    
    # Continue animation if we're still dragging and not close enough to target
    distance = ((target_x - new_x) ** 2 + (target_y - new_y) ** 2) ** 0.5
    if mouse_dragging_grow_overlay and distance > 2:  # Stop when very close
        animation_after_id = root.after(16, smooth_move_grow_overlay)  # ~60 FPS
    else:
        animation_after_id = None

# Mouse event handlers
def on_mouse_click(x, y, button, pressed):
    """Handle mouse click events."""
    global mouse_left_pressed, mouse_dragging_grow_overlay, target_mouse_position, animation_after_id, last_seek_time, can_seek
    
    if pressed:
        if button == mouse.Button.left:
            mouse_left_pressed = True
            # Check if grow overlay is active and start dragging
            if (grow_overlay_boxes and 
                any(box.winfo_exists() for box in grow_overlay_boxes.values())):
                mouse_dragging_grow_overlay = True
                target_mouse_position = (x, y)
                # Start smooth animation if not already running
                if animation_after_id is None:
                    smooth_move_grow_overlay()
        
        elif button == mouse.Button.right:
            widen_peek()
    else:
        if button == mouse.Button.left:
            mouse_left_pressed = False
            mouse_dragging_grow_overlay = False
            target_mouse_position = None
            # Cancel animation
            if animation_after_id:
                root.after_cancel(animation_after_id)
                animation_after_id = None
            if last_seek_time:
                player.set_time(int(float(last_seek_time)) * 1000)
                last_seek_time = None
                def clear_last_seek_time():
                    global last_seek_time
                    last_seek_time = None
                root.after(100, clear_last_seek_time)
        # Add your mouse release handling logic here

def on_mouse_move(x, y):
    """Handle mouse move events - set target position for smooth animation."""
    global target_mouse_position
    
    # If left mouse is pressed and we're dragging the grow overlay
    if mouse_dragging_grow_overlay and mouse_left_pressed:
        target_mouse_position = (x, y)
        # Start animation if not already running
        if animation_after_id is None:
            smooth_move_grow_overlay()

def on_mouse_scroll(x, y, dx, dy):
    """Handle mouse scroll events."""
    # Add your scroll handling logic here

# =========================================
#                *STARTUP
# =========================================

# Start keyboard listener
keyboard_listener = keyboard.Listener(
    on_press=on_press,
    on_release=on_release)
keyboard_listener.start()

# Start mouse listener
mouse_listener = mouse.Listener(
    on_click=on_mouse_click,
    on_move=on_mouse_move,
    on_scroll=on_mouse_scroll)
mouse_listener.start()

update_playlist_name()
update_current_index()
load_youtube_metadata()
load_metadata()
scan_directory(True)
create_first_row_buttons()
threading.Thread(target=load_default_char_images, daemon=True).start()

# Clean up any leftover updater files from previous updates
def cleanup_updater_files():
    """Remove updater.exe and updater.log files if they exist."""
    files_to_clean = ["updater.exe", "updater.log"]
    for filename in files_to_clean:
        if os.path.exists(filename):
            try:
                os.remove(filename)
                print(f"Cleaned up: {filename}")
            except Exception as e:
                print(f"Could not clean up {filename}: {e}")

# Clean up updater files on startup
cleanup_updater_files()

# Add debounced resize handler to refresh list display when window resize is complete
resize_timer_id = None

def on_window_resize(event):
    """Handle window resize events with debouncing - only update after resize is complete."""
    global resize_timer_id
    
    # Only handle resize events from the root window
    if event.widget != root or not list_loaded:
        return
    
    # Cancel any pending resize update
    if resize_timer_id is not None:
        root.after_cancel(resize_timer_id)
    
    # Schedule a new update after 500ms of no resize events (resize finished)
    resize_timer_id = root.after(500, refresh_list_on_resize)

def refresh_list_on_resize():
    """Refresh the current list display with updated button count."""
    global list_loaded, current_list_content, current_list_name_func, current_list_selected, resize_timer_id
    
    # Clear the timer ID since we're executing now
    resize_timer_id = None
    
    if list_loaded and current_list_content is not None:
        # Check if the number of entries would actually change
        current_button_count = len(persistent_buttons) if persistent_buttons else 0
        new_entries_count = get_list_entries_count()
        
        # Only refresh if the row count would change
        if current_button_count != new_entries_count:
            # Get current list type and refresh it
            current_type = list_loaded
            # Force recreation of buttons by temporarily clearing list_loaded
            temp_loaded = list_loaded
            list_set_loaded("")
            show_list(temp_loaded, right_column, current_list_content, current_list_name_func, 
                      list_func, current_list_selected, update=True)

# Bind resize event to root window
root.bind("<Configure>", on_window_resize)

root.after(1000, create_new_session)

# Start updating the seek bar
root.after(1000, update_seek_bar)
# Schedule a check for when the video ends
root.after(1000, check_video_end)
# Check for updates on startup (after 3 seconds to let UI load)
root.after(3000, check_for_updates_on_startup)

root.mainloop()