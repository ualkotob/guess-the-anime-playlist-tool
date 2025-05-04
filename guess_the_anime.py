# =========================================
#      GUESS THE ANIME - PLAYLIST TOOL
#             by Ramun Flame
# =========================================

import os
import ctypes
import random
import math
import json
import requests
import re
import dxcam
import time
from collections import Counter
import numpy as np
from io import BytesIO
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageTk
import threading  # For asynchronous metadata loading
import vlc
import yt_dlp
from pynput import keyboard
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame
import pyperclip

# Explicitly load libvlc.dll and its dependencies
vlc_path = r'C:\Program Files\VideoLAN\VLC'  # Replace with your VLC installation path
os.add_dll_directory(vlc_path)  # Add VLC directory to DLL search path

# Load libvlc.dll
try:
    ctypes.CDLL(os.path.join(vlc_path, 'libvlc.dll'))
except OSError as e:
    print(f"Error loading libvlc.dll: {e}")
    exit(1)

# Initialize VLC instance with hardware acceleration disabled
instance = vlc.Instance("--no-xlib -q") #instance = vlc.Instance("--no-xlib --no-video-deco")  # Disable hardware acceleration
player = instance.media_player_new()

# =========================================
#       *GLOBAL VARIABLES/CONSTANTS
# =========================================

playlist = []
playlist_name = ""
current_index = 0
video_stopped = True
can_seek = True
file_metadata = {}
file_metadata_file = "metadata/file_metadata.json"
anime_metadata = {}
anime_metadata_file = "metadata/anime_metadata.json"
manual_metadata_file = "metadata/manual_metadata.json"
youtube_metadata = {}
youtube_metadata_file = "metadata/youtube_metadata.json"
directory_files = {}
CONFIG_FILE = "files/config.json"
YOUTUBE_FOLDER = "youtube"
ARCHIVE_FILE = "files/youtube_archive.txt"
PLAYLISTS_FOLDER = "playlists/"
FILTERS_FOLDER = "filters"
YOUTUBE_LINKS_FILE = "files/youtube_links.txt"
CENSOR_FILE = "files/censors.csv"
TAGGED_FILE = "files/tagged.txt"
HIGHLIGHT_COLOR = "gray26"

# =========================================
#         *FETCHING ANIME METADATA
# =========================================

# Function to fetch anime metadata using AnimeThemes.moe API
def fetch_animethemes_metadata(filename):
    url = "https://api.animethemes.moe/anime"
    params = {
        "filter[has]": "animethemes.animethemeentries.videos",
        "filter[video][basename-like]": filename.split("-")[0] + "-%",
        "include": "series,resources,images,animethemes.animethemeentries.videos,animethemes.song.artists"
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data.get("anime"):
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

fetched_metadata = []
def pre_fetch_metadata():
    for i in range(current_index-1, current_index+3):
        if i >= 0 and i < len(playlist) and i != current_index and (fetching_metadata.get(playlist[i]) is None):
            get_metadata(playlist[i], True, fetch=True)

def get_metadata(filename, refresh = False, refresh_all = False, fetch = False):
    global fetched_metadata
    file_data = file_metadata.get(filename)
    if file_data:
        mal_id = file_data.get('mal')
        anime_data = anime_metadata.get(mal_id)
        if anime_data:
            if "-[ID]" not in filename and mal_id and mal_id not in fetched_metadata and refresh and (refresh_all or (auto_refresh_toggle and fetch)):
                fetched_metadata.append(mal_id)
                refresh_jikan_data(mal_id, anime_data)
            return file_data | anime_data
    if fetch:
        return fetch_metadata(filename)
    else:
        return {}

def refetch_metadata():
    if currently_playing and currently_playing.get('type') == 'theme':
        filename = currently_playing.get('filename')
    else:
        filename = playlist[current_index]
    fetch_metadata(filename, True)

fetching_metadata = {}
def fetch_metadata(filename = None, refetch = False):
    global currently_playing
    if filename is None:
        filename = playlist[current_index]
        refetch = True

    print(f"Fetching metadata for {filename}...", end="", flush=True)

    fetching_metadata[filename] = True
    slug = filename.split("-")[1].split(".")[0].split("v")[0]
    mal_id = None
    if (not "[MAL]" in filename) and (not "[ID]" in filename):
        if len(filename.split("-")) >= 3:
            slug_ext = filename.split("-")[2]
            if "NCBD" not in slug_ext and "NCDVD" not in slug_ext and "BD1080" not in slug_ext and "Lyrics" not in slug_ext:
                slug = slug + "-" + slug_ext.split(".")[0]
                slug = slug + "-" + slug_ext.split("-Lyrics")[0]
        anime_themes = fetch_animethemes_metadata(filename)
        if anime_themes:
            for resource in anime_themes.get("resources", []):
                if resource["site"] == "MyAnimeList":
                    mal_id = str(resource["external_id"])
                    break
    elif ("[MAL]" in filename):
        filename_metadata = get_filename_metadata(filename)
        mal_id = filename_metadata.get('mal_id')
        anime_themes = {
            "animethemes":[{
                "type":slug[:2],
                "slug":slug,
                "song":{
                    "title":filename_metadata.get("song", "N/A"),
                    "artists":[{
                        "name":filename_metadata.get("artist", "N/A")
                    }]
                }
            }]
        }
        season_year = get_last_two_folders(directory_files.get(filename))
        season = season_year[1]
        year = season_year[0]
        if season in ['Winter','Spring','Summer','Fall']:
            anime_themes["season"] = season
            anime_themes["year"] = year
    else:
        mal_id = re.search(r"\[ID](.*?)(?=\[|$|\.)", filename).group(1)
        anime_themes = {}
    if mal_id:
        file_data = {
            "mal":mal_id,
            "slug":slug
        }
        anime_data = anime_metadata.get(mal_id)
        old_songs = []
        if anime_data:
            old_songs = anime_data.get("songs", [])
        file_metadata[filename] = file_data
        if refetch or not anime_data:
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
                    "synopsis":jikan_data.get('synopsis', "N/A")
                }
                if "N/A" in anime_data.get("season"):
                    if anime_themes.get("season"):
                        anime_data["season"] = str(anime_themes.get("season", "N/A")) + " " + str(anime_themes.get("year", "N/A"))
                    else:
                        aired_to_season_year(anime_data.get("aired"))
                else:
                    anime_data["season"] = anime_data["season"].capitalize()
                anime_metadata[mal_id] = anime_data
        if anime_data:
            # Get new songs from the current fetch
            new_songs = get_theme_list(anime_themes)
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
            anime_data["songs"] = list(openings+endings+other)
            save_metadata()
            data = file_data | anime_data
            if currently_playing.get('filename') == filename:
                currently_playing["data"] = data
                update_metadata()
            print(f"\rFetching metadata for {filename}...COMPLETE")
        else:
            data = {}
            print(f"\rFetching metadata for {filename}...FAILED")
    else:
        data = {}
        print(f"\rFetching metadata for {filename}...FAILED")
    return data

def get_theme_list(data):
    openings = []
    endings = []
    other = []
    for theme in data.get("animethemes", {}):
        artists = []
        for artist in theme["song"]["artists"]:
            artists.append(artist["name"])
        theme_data = {
            "type":theme["type"],
            "slug":theme["slug"],
            "title":theme["song"]["title"],
            "artist": artists,
            "episodes": theme["animethemeentries"][0]["episodes"] if theme.get("animethemeentries") else "N/A"
        }
        if theme.get("animethemeentries"):
            if theme["animethemeentries"][0]["spoiler"]:
                theme_data["spoiler"] = theme["animethemeentries"][0]["spoiler"]
            if theme["animethemeentries"][0]["videos"] and theme["animethemeentries"][0]["videos"][0]["overlap"] and theme["animethemeentries"][0]["videos"][0]["overlap"] != "None":
                theme_data["overlap"] = theme["animethemeentries"][0]["videos"][0]["overlap"]
        if "OP" in theme["slug"]:
            openings.append(theme_data)
        elif "ED" in theme["slug"]:
            endings.append(theme_data)
        else:
            other.append(theme_data)
    return openings + endings + other

def get_filename_metadata(filename):
    """Extracts MAL ID, artist, and song name from a filename with optional bracketed tags."""
    metadata = {"mal_id": None, "artist": None, "song": None}
    
    # Define patterns for each tag
    mal_match = re.search(r"\[MAL](\d+)", filename)
    artist_match = re.search(r"\[ART](.*?)(?=\[|$|\.)", filename)
    song_match = re.search(r"\[SNG](.*?)(?=\[|$|\.)", filename)
    
    # Extract values if found
    if mal_match:
        metadata["mal_id"] = mal_match.group(1)
    
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

def refresh_jikan_data(mal_id, data):
    print(f"Refreshing Jikan data for {data['title']}...", end="", flush=True)
    
    jikan_data = fetch_jikan_metadata(mal_id)
    if jikan_data:
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
        
        save_metadata()
        print(f"\rRefreshing Jikan data for {data['title']}...COMPLETE")
    else:
        print(f"\rRefreshing Jikan data for {data['title']}...FAILED")

def aired_to_season_year(aired_str):
    """Converts an aired string to 'Season Year' format based on the first date."""
    try:
        # Extract the first part before "to"
        first_date_str = aired_str.split("to")[0].strip()
        # Parse it into a datetime object
        try:
            aired_date = datetime.strptime(first_date_str, "%b %d, %Y")
        except:
            aired_date = datetime.strptime(first_date_str, "%B %d, %Y")
        month = aired_date.month
        year = aired_date.year

        # Determine season
        if month in [1, 2, 3]:
            season = "Winter"
        elif month in [4, 5, 6]:
            season = "Spring"
        elif month in [7, 8, 9]:
            season = "Summer"
        else:
            season = "Fall"

        return f"{season} {year}"
    except Exception as e:
        print(f"Error parsing aired string: {aired_str} -> {e}")
        return "N/A"

def get_last_two_folders(filepath):
    print(filepath)
    path_parts = filepath.split(os.sep)
    # Filter out empty strings that might occur due to leading/trailing separators or double separators
    path_parts = list(filter(None, path_parts))
    print(path_parts)
    if len(path_parts) >= 3:
        return [path_parts[-3], path_parts[-2]]
    else:
        return ["",""]
    
def get_name_list(data, get):
    name_list = []
    for item in data.get(get, []):
        name_list.append(item.get("name"))
    return name_list

def get_artists_string(artists):
    return ", ".join(artists) if artists else "N/A"

def fetch_all_metadata(delay=1):
    """Fetches missing metadata for the entire directory, spacing out API calls."""
    confirm = messagebox.askyesno("Fetch All Missing Metadata", f"Are you sure you want to fetch all missing metadata?")
    if not confirm:
        return  # User canceled
    scan_directory()
    def worker():
        total_checked = 0
        total_fetched = 0
        for filename in directory_files:
            total_checked = total_checked + 1
            # Skip if metadata already exists
            if filename in file_metadata:
                file_data = file_metadata.get(filename)
                mal_id = file_data.get('mal')
                if mal_id in anime_metadata:
                    continue  
            fetch_metadata(filename)  # Call your existing metadata function
            total_fetched = total_fetched + 1
            time.sleep(delay)  # Delay to avoid API rate limits

        print("Metadata fetching complete! - Checked:" + str(total_checked) + " Missing:" + str(total_fetched))

    # Run in a separate thread so it doesn’t freeze the UI
    threading.Thread(target=worker, daemon=True).start()

def refresh_all_metadata(delay=1):
    """Refreshes all jikan metadata for the entire directory, spacing out API calls."""
    confirm = messagebox.askyesno("Refresh All Jikan Metadata", f"Are you sure you want to refresh all jikan metadata?")
    if not confirm:
        return  # User canceled
    def worker():
        total_checked = 0
        for filename in directory_files:
            get_metadata(filename, refresh = True, refresh_all = True)
            total_checked = total_checked + 1
            # time.sleep(delay)  # Delay to avoid API rate limits

        print("Metadata refeshing complete! - Refreshed:" + str(total_checked))

    # Run in a separate thread so it doesn’t freeze the UI
    threading.Thread(target=worker, daemon=True).start()


# =========================================
#        *METADATA DISPLAY
# =========================================

def clear_metadata():
    """Function to clear metadata fields"""
    global list_loaded
    list_set_loaded(None)
    left_column.delete(1.0, tk.END)
    middle_column.delete(1.0, tk.END)
    right_column.delete(1.0, tk.END)

def reset_metadata(filename = None):
    """Function to reset metadata and add filename"""
    toggleColumnEdit(True)
    clear_metadata()
    if filename is None:
        filename = currently_playing.get('filename')
    left_column.insert(tk.END, "FILENAME: ", "bold")
    left_column.insert(tk.END, f"{filename}", "white")
    left_column.window_create(tk.END, window=tk.Button(left_column, text="⎘", borderwidth=0, pady=0, command=lambda: pyperclip.copy(filename), bg="black", fg="white"))
    if playlist_name == "Tagged Themes":
        left_column.window_create(tk.END, window=tk.Button(left_column, text="❌", borderwidth=0, pady=0, command=lambda: delete_file_by_filename(filename), bg="black", fg="white"))
    left_column.insert(tk.END, "\n\n", "blank")
 
def update_metadata_queue(index):
    """Function to update metadata display asynchronously"""
    global updating_metadata
    if updating_metadata:
        root.after(100, update_metadata_queue, index)
    elif index == current_index:
        updating_metadata = True
        threading.Thread(target=update_metadata, daemon=True).start()

updating_metadata = False
def update_metadata():
    global updating_metadata
    filename = currently_playing.get("filename")
    if filename:
        button_seleted(tag_button, check_tagged(filename))
        button_seleted(favorite_button, check_favorited(filename))
        data = currently_playing.get('data')
        # Clear previous metadata
        reset_metadata()
        if data:
            # Left Column: Filename, Title, English Title, and Large Image
            add_single_data_line(left_column, data, "TITLE: ", 'title', False)
            add_field_total_button(left_column, get_all_matching_field("mal", data.get("mal")))
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
                left_column.insert(tk.END, f"{f"{(data.get("reviews", 0) or 0):,}"}", "white")
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
            for index, studio in enumerate(data.get("studios")):
                left_column.insert(tk.END, f"{studio}", "white")
                add_field_total_button(left_column, get_filenames_from_studio(studio), blank = False)
                if index < len(data.get("studios"))-1:
                    left_column.insert(tk.END, f", ", "white")
            if data.get("series"):
                left_column.insert(tk.END, "\n\n", "blank")
                add_multiple_data_line(left_column, data, "SERIES: ", "series", False)
                add_field_total_button(left_column, get_all_matching_field("series", data.get("series")))
            up_next_text()
            add_single_data_line(right_column, data, "SYNOPSIS:\n", 'synopsis')

            # Right Column: List of OP/EDs
            openingAdded = False
            endingAdded = False
            for theme in data.get("songs", []):
                if not openingAdded and theme["type"] == "OP":
                    openingAdded = True
                    middle_column.insert(tk.END, "OPENINGS:\n", "bold")
                elif not endingAdded and theme["type"] == "ED":
                    endingAdded = True
                    middle_column.insert(tk.END, "ENDINGS:\n", "bold")
                add_op_ed(theme, middle_column, data.get("slug"), data.get("title"))
            toggleColumnEdit(False)
        else:
            up_next_text()
    else:
        up_next_text()
    updating_metadata = False

def up_next_text():
    right_column.insert(tk.END, "NEXT UP: \n", "bold")
    next_up_text = "End of playlist"
    if current_index+1 < len(playlist):
        try:
            next_up_data = get_metadata(playlist[current_index+1])
            next_up_text = f"{next_up_data.get("eng_title") or next_up_data.get("title")} - {format_slug(next_up_data.get("slug"))} ({next_up_data.get("members") or 0:,})"
        except Exception:
            next_up_text = playlist[current_index+1]
    right_column.insert(tk.END, f"{next_up_text}", "white")
    right_column.insert(tk.END, "\n\n", "blank")

def is_game(data):
    return data.get("type") == "Game" or data.get("type") == "Visual Novel" or data.get("platforms")

def add_field_total_button(column, group, blank = True, show_count=True):
    count = len(group)
    if count > 0:
        if show_count:
            column.insert(tk.END, f" [{count}", "white")
        btn = tk.Button(column, text="▶", borderwidth=0, pady=0, command=lambda: show_field_themes(group=group), bg="black", fg="white")
        column.window_create(tk.END, window=btn)
        if show_count:
            column.insert(tk.END, f"]", "white")
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

def get_overall_theme_number(filename):
    """Returns the overall opening/ending number across the series based on the filename."""
    data = get_metadata(filename)
    if not data or is_game(data):
        return None

    target_series = data.get("series")
    target_slug = data.get("slug")
    mal_id = file_metadata.get(filename, {}).get("mal")

    if not mal_id or not target_series or not target_slug:
        return None

    if isinstance(target_series, str):
        target_series = [target_series]

    theme_type = target_slug[:2]  # "OP" or "ED"
    if theme_type not in ["OP", "ED"]:
        return None

    is_parody = "Parody" in data.get("themes")
    slug_extra = get_slug_extra(target_slug)
    # Step 1: Find all anime from same series
    related_anime = []
    for anime_id, anime in anime_metadata.items():
        if anime.get("series") == target_series and has_same_start(data.get("title"), anime.get("title"), length=1) and not is_game(anime) and (is_parody == ("Parody" in anime.get("themes"))):
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

    # Step 3: Count themes of the same type, stopping at the target
    overall_index = 0
    base_title = None
    data_title = data.get("title")
    for anime_id, anime in related_anime:
        anime_title = anime.get("title")
        if not base_title:
            for end in [" (TV)", " 1st", ":", " no Kajitsu"]:
                anime_title = anime_title.split(end)[0]
            if anime_title in data_title:
                base_title = anime_title
            else:
                continue
        if base_title and base_title in anime_title:
            for song in anime.get("songs", []):
                if song["type"] == theme_type:
                    if song.get("spoiler") or song.get("overlap") or not (slug_extra == get_slug_extra(song.get("slug"))):
                        continue
                    overall_index += 1
                    if anime_id == mal_id and song["slug"] == target_slug:
                        return overall_index

    return None

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

def add_op_ed(theme, column, slug, title):
    theme_slug = theme.get("slug")
    song_title = theme.get("title")
    artist = get_artists_string(theme.get("artist"))
    episodes = theme.get("episodes")
    format = "white"
    filename = get_theme_filename(title, theme_slug)
    if theme_slug == slug:
        format = "highlight"
    if filename:
        column.window_create(tk.END, window=tk.Button(column, text="▶", borderwidth=0, pady=0, command=lambda: play_video_from_filename(filename), bg="black", fg="white"))
    else:
        column.insert(tk.END, ">", format)
    column.insert(tk.END, f"{theme_slug}{overall_theme_num_display(filename)}: {song_title}\n", format)
    column.insert(tk.END, f"Artist(s): ", format)
    if theme.get("artist") == []:
        column.insert(tk.END, f"N/A", format)
    else:
        for index, artist in enumerate(theme.get("artist")):
            column.insert(tk.END, f"{artist}", format)
            add_field_total_button(column, get_filenames_from_artist(artist), blank = False)
            if index < len(theme.get("artist"))-1:
                column.insert(tk.END, f", ", format)
    column.insert(tk.END, f"\n", format)        

    column.insert(tk.END, f"(Episodes: {episodes})", format)   
    if theme.get("overlap", None) == "Over":
        column.insert(tk.END, f" (OVERLAP)", format)    
    if theme.get("spoiler", False):
        column.insert(tk.END, f" (SPOILER)", format)    
    column.insert(tk.END, f"\n", format)       
    if theme_slug == slug:
        column.see("end-1c")
    column.insert(tk.END, "\n", "blank")

def get_theme_filename(title, slug):
    for filename in directory_files:
        data = get_metadata(filename)
        if data.get("title") == title and data.get("slug") == slug:
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

def update_youtube_metadata():
    global youtube_queue
    insert_column_line(left_column, "TITLE: ", youtube_queue.get('title'))
    insert_column_line(left_column, "FULL TITLE: ", youtube_queue.get('full_title'))
    insert_column_line(left_column, "UPLOAD DATE: ", f"{datetime.strptime(youtube_queue.get('upload_date'), "%Y%m%d").strftime("%Y-%m-%d")}")
    insert_column_line(left_column, "VIEWS: ", f"{youtube_queue.get('view_count'):,}")
    insert_column_line(left_column, "LIKES: ", f"{youtube_queue.get('like_count'):,}")
    insert_column_line(left_column, "CHANNEL: ", youtube_queue.get('channel'))
    insert_column_line(left_column, "SUBSCRIBERS: ", f"{youtube_queue.get('channel_follower_count'):,}")
    insert_column_line(left_column, "DURATION: ", str(format_seconds(get_youtube_duration(youtube_queue))) + " mins")
    insert_column_line(middle_column, "DESCRIPTION: ", youtube_queue.get('description'))
    show_youtube_playlist()
    # 'thumbnail':info.get('thumbnail'),

def insert_column_line(column, title, data):
    column.insert(tk.END, title, "bold")
    column.insert(tk.END, f"{data}", "white")
    column.insert(tk.END, "\n\n", "blank")

# =========================================
#        *FETCHING YOTUBE METADATA
# =========================================

def load_video_links():
    """Load video links from a text file"""
    video_map = {}
    ARCHIVE_FILE = "files/youtube_archive.txt"

    # Load existing archive entries (full lines)
    archived_lines = set()
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r") as archive:
            archived_lines = {line.strip() for line in archive}

    if os.path.exists(YOUTUBE_LINKS_FILE):
        try:
            # Load existing archive entries but store only URLs for comparison
            archived_urls = set()
            if os.path.exists(ARCHIVE_FILE):
                with open(ARCHIVE_FILE, "r") as archive_file:
                    for line in archive_file:
                        parts = line.strip().split(",")
                        if len(parts) > 1:  # Ensure valid format
                            archived_urls.add(parts[1])  # Store only the URL for checking

            with open(YOUTUBE_LINKS_FILE, "r") as file, open(ARCHIVE_FILE, "a") as archive:
                for index, line in enumerate(file):
                    url, start, end, title = line.strip().split(",")
                    if url and url != 'url':  # Ensure URL is valid and not a header
                        video_map[url] = {
                            'index': index,
                            'url': url,
                            'start': start,
                            'end': end,
                            'title': title
                        }

                        # Check if the URL is already archived (ignoring date)
                        if url not in archived_urls:
                            archive_entry = f"{datetime.now().strftime('%Y-%m-%d')},{line.strip()}"
                            archive.write(archive_entry + "\n")
                            archived_urls.add(url)  # Add the URL to prevent future duplicates

            # remove old metadata
            to_delete = []
            for key, value in youtube_metadata.items():
                match = False
                for k, v in video_map.items():
                    if key == v.get('url'):
                        match = True
                        break
                if not match:
                    to_delete.append(key)
            for d in to_delete:
                del youtube_metadata[d]
            save_youtube_metadata()
            # Delete outdated videos
            if os.path.exists(YOUTUBE_FOLDER):
                for filename in os.listdir(YOUTUBE_FOLDER):
                    match = False
                    for url, value in youtube_metadata.items():
                        if value.get('title') + '.webm' == filename:
                            match = True
                            break
                    if not match:
                        os.remove(os.path.join(YOUTUBE_FOLDER, filename))
                        print(f"Deleted outdated video: {filename}")
        except Exception as e:
            print("Error: " + str(e))

    return video_map

youtube_queue = None

def download_videos():
    """Downloads all YouTube videos if not already downloaded, without freezing the UI."""
    global youtube_metadata
    ydl_opts = {
        'quiet': True,
        'format': 'bestvideo[height<=1080]+bestaudio/best',
        'merge_output_format': 'webm',
        'outtmpl': os.path.join("youtube", '%(id)s.%(ext)s'),  # Save as YouTube ID
    }
    def download_single_video(key, data):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                url = key
                info = ydl.extract_info(url, download=False)
                filename = os.path.join("youtube", data.get('title') + ".webm")
                youtube_metadata[key] = {
                    "index":data.get('index'),
                    "title":data.get('title'),
                    "start":int(data.get('start')),
                    "end":int(data.get('end')),
                    "full_title":info.get('title'),
                    "filename":filename,
                    'upload_date':info.get('upload_date'),
                    'channel':info.get('channel'),
                    'channel_follower_count':info.get('channel_follower_count'),
                    'like_count':info.get('like_count'),
                    'view_count':info.get('view_count'),
                    'duration':info.get('duration'),
                    'description':info.get('description'),
                    'thumbnail':info.get('thumbnail'),
                }
                save_youtube_metadata()
                """Downloads a single video if not already downloaded."""
                if not os.path.exists(filename):  # Skip if file exists
                    print(f"Downloading {url} as {filename}...")
                    info_dict = ydl.extract_info(url, download=True)
                    downloaded_filename = ydl.prepare_filename(info_dict)  # Get actual filename
                    os.rename(downloaded_filename, filename)  # Rename to number-based format
                    print(f"Download complete: {filename}")
                else:
                    print(f"Skipping {url}, already downloaded.")# Create a thread for each video download
        except Exception as e:
            print(f"Error downloading {url}: {e}")
    
    threads = []
    for key, data in load_video_links().items():
        if youtube_metadata.get(key) is None or not os.path.exists(youtube_metadata.get(key).get("filename")):
            thread = threading.Thread(target=download_single_video, args=(key, data))
            thread.start()
            threads.append(thread)

    # Optionally, wait for all downloads to complete
    for thread in threads:
        thread.join()

def get_youtube_duration(data):
    start = data.get("start")
    end = data.get("end")
    length = data.get('duration')
    if end == 0:
        end = length
    duration = round(end-start)
    return duration

def get_youtube_metadata_from_index(index):
    for idx, (key, value) in enumerate(youtube_metadata.items()):
        if idx == index:
            return value

# =========================================
#           *CREATE PLAYLIST
# =========================================

playlist_changed = False
def generate_playlist():
    """Function to generate a shuffled playlist"""
    global playlist_changed
    playlist_changed = True
    playlist = []
    for file in directory_files:
        playlist.append(file)
    return playlist

# =========================================
#            *SHUFFLE PLAYLIST
# =========================================

def randomize_playlist():
    global playlist
    confirm = messagebox.askyesno("Shuffle Playlist", f"Are you sure you want to shuffle '{playlist_name}'?")
    if not confirm:
        return  # User canceled
    random.shuffle(playlist)
    update_current_index()
    show_playlist(True)

def weighted_randomize():
    global playlist
    confirm = messagebox.askyesno("Weighted Shuffle Playlist", f"Are you sure you want to weighted shuffle '{playlist_name}'?")
    if not confirm:
        return  # User canceled
    playlist = weighted_shuffle(playlist)
    update_current_index()
    show_playlist(True)

def weighted_shuffle(playlist):
    """Performs a weighted shuffle of the playlist, balancing popularity and season while preventing repeats."""
    
    if not playlist:
        return playlist  # Return as is if empty

    # Step 1: Sort by popularity and split into 3 groups
    sorted_playlist = sorted(playlist, key=lambda x: get_metadata(x).get("members", 0) or 0, reverse=True)
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
    def split_into_three(entries):
        size = len(entries) // 3 or 1  # Ensure at least 1 per split
        return [entries[:size], entries[size:size*2], entries[size*2:]]

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
    
    while any(any(group) for group in groups):  # Continue while any group has entries
        time_order = [0, 1, 2]  # Old, Mid, Recent
        pop_order = [0, 1, 2]  # Niche, Mid, Popular

        random.shuffle(time_order)  # Shuffle time groups
        for t in time_order:  # Go through randomized time order
            random.shuffle(pop_order)  # Shuffle popularity groups
            for p in pop_order:  # Go through randomized popularity order
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
            if filename_group[final_playlist[index]] == filename_group[final_playlist[swap_index]]:
                if is_safe_swap(index, swap_index):
                    return swap_index
        
        # If no forward swap found, check backward
        for swap_index in range(index - spacing, -1, -1):
            if filename_group[final_playlist[index]] == filename_group[final_playlist[swap_index]]:
                if is_safe_swap(index, swap_index):
                    return swap_index

        return None  # No good swap found

    def is_safe_swap(i1, i2):
        """Checks if swapping entries i1 and i2 resolves spacing issues for both."""
        def is_valid_placement(index, entry_title, entry_series):
            for offset in range(1, min_spacing + 1):
                # Check before
                if index - offset >= 0:
                    prev = final_playlist[index - offset]
                    prev_title = get_metadata(prev).get("title", "")
                    prev_series = get_metadata(prev).get("series", "")
                    if entry_title == prev_title or (entry_series and entry_series == prev_series):
                        return False
                # Check after
                if index + offset < len(final_playlist):
                    next_ = final_playlist[index + offset]
                    next_title = get_metadata(next_).get("title", "")
                    next_series = get_metadata(next_).get("series", "")
                    if entry_title == next_title or (entry_series and entry_series == next_series):
                        return False
            return True

        # Get entries and their metadata
        entry1 = final_playlist[i1]
        entry2 = final_playlist[i2]
        title1 = get_metadata(entry1).get("title", "")
        series1 = get_metadata(entry1).get("series", "")
        title2 = get_metadata(entry2).get("title", "")
        series2 = get_metadata(entry2).get("series", "")

        # Check if both would be safely placed after swap
        return (
            is_valid_placement(i2, title1, series1) and
            is_valid_placement(i1, title2, series2)
    )

    swapped_entrys = 1
    skipped_entries = 0
    swap_pass = 0

    print("Weighted Shuffle - STARTING... (may take some time, 10 pass max)")
    while (swapped_entrys > 0 or skipped_entries > 0) and swap_pass < 10:
        swapped_entrys = 0
        skipped_entries = 0
        swap_pass += 1

        for i in range(len(final_playlist)):
            print(f"Spacing Same Series Pass {swap_pass} - Checking entry {i + 1} / {len(final_playlist)} ({swapped_entrys} swapped / {skipped_entries} skipped)", end="\r")  # 🔄 Overwrites same line
            title, series = get_metadata(final_playlist[i]).get("title", ""), get_metadata(final_playlist[i]).get("series", "")
            total_series = len(get_all_matching_field("series", series))
            if total_series == 0:
                total_series = len(get_all_matching_field("title", title))
            min_spacing = int(min(350, max(3, (len(final_playlist) // total_series)) * (0.9**swap_pass)))

            for j in range(1, min_spacing + 1):
                if i + j < len(final_playlist):
                    next_title, next_series = get_metadata(final_playlist[i + j]).get("title", ""), get_metadata(final_playlist[i + j]).get("series", "")
                    if title == next_title or (series and series == next_series):
                        swap_index = find_suitable_swap(i + j)
                        if swap_index:
                            swapped_entrys += 1
                            final_playlist[i + j], final_playlist[swap_index] = final_playlist[swap_index], final_playlist[i + j]
                        else:
                            skipped_entries += 1
        print(f"")
        
    print("Weighted Shuffle - COMPLETE!")

    return final_playlist

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
        "current_index": current_index,
        "playlist_name": playlist_name,
        "playlist": playlist,
        "directory": directory_entry.get(),
        "directory_files": directory_files
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def load_config():
    """Function to load configuration"""
    global playlist, playlist_name, directory_files
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            directory_files = config.get("directory_files", {})
            update_playlist_name(config.get("playlist_name", ""))
            playlist = config.get("playlist", [])
            directory_entry.insert(0, config.get("directory", ""))
            update_current_index(config.get("current_index", 0))
    except Exception as e:
        os.remove(CONFIG_FILE)
        print(f"Error loading config: {e}")
        return False
    return False

def update_playlist_name(name):
    global playlist_name
    playlist_name = name
    root.title(WINDOW_TITLE + " - " + playlist_name)

def save_metadata():
    """Ensures the metadata folder exists before saving metadata files."""
    metadata_folder = os.path.dirname(file_metadata_file)  # Get the folder path

    # Create the folder if it does not exist
    if not os.path.exists(metadata_folder):
        os.makedirs(metadata_folder)

    # Save metadata files
    with open(file_metadata_file, "w") as f:
        json.dump(file_metadata, f, indent=4)  # Pretty-print for readability

    with open(anime_metadata_file, "w") as f:
        json.dump(anime_metadata, f, indent=4)

def load_metadata():
    global file_metadata, anime_metadata
    if os.path.exists(file_metadata_file):
        with open(file_metadata_file, "r") as f:
            file_metadata = json.load(f)
            print("Loaded metadata for " + str(len(file_metadata)) + " files...")
    if os.path.exists(anime_metadata_file):
        with open(anime_metadata_file, "r") as a:
            anime_metadata = json.load(a)
            print("Loaded metadata for " + str(len(anime_metadata)) + " entries...")
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

REVIEW_MODIFIER = 1000
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

def save_youtube_metadata():
    """Ensures the metadata folder exists before saving metadata file."""
    metadata_folder = os.path.dirname(youtube_metadata_file)  # Get the folder path

    # Create the folder if it does not exist
    if not os.path.exists(metadata_folder):
        os.makedirs(metadata_folder)

    with open(youtube_metadata_file, "w") as f:
        json.dump(youtube_metadata, f)

def load_youtube_metadata():
    global youtube_metadata
    if os.path.exists(youtube_metadata_file):
        with open(youtube_metadata_file, "r") as f:
            youtube_metadata = json.load(f)
            print("Loaded metadata for " + str(len(youtube_metadata)) + " youtube videos...")
        return True
    return False

# =========================================
#           *MANAGE PLAYLISTS
# =========================================

def save(autosave = False):
    save_playlist(playlist, current_index, root, autosave)

def save_playlist(playlist, index, parent, autosave):
    """Opens a popup to enter a name, then saves the playlist, and index as JSON."""
    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)

    if autosave:
        name = playlist_name
    else:
        # Ask for a playlist name
        name = simpledialog.askstring("Save Playlist", "Enter playlist name:", initialvalue=playlist_name, parent=parent)
        if not name:
            return  # User canceled
        elif name.lower() == "missing artists":
            check_missing_artists()
            return

    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")

    # Save playlist data
    data = {
        "name": name,
        "current_index": index,
        "playlist": playlist
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    
    update_playlist_name(name)
    save_config()
    print(f"Playlist saved as {filename}")

playlist_loaded = False
def load_playlist(index):
    """Loads a saved playlist from JSON."""
    global playlist_loaded
    playlist_data = get_playlists_dict()[index]
    name = playlist_data
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")

    if not os.path.exists(filename):
        print(f"Playlist {name} not found.")
        return None

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    global playlist, playlist_changed
    if playlist_name != "" and not disable_shortcuts:
        save(True)
    playlist_changed = False
    playlist = data.get('playlist')
    update_playlist_name(data.get('name'))
    update_current_index(data.get('current_index'))
    root.title(WINDOW_TITLE + " - " + playlist_name)
    print(f"Loaded playlist: {name}")
    playlist_loaded = True
    save_config()
    load(True)

def load(update = False):
    selected = -1
    playlists = get_playlists_dict()
    for key, value in playlists.items():
        if playlist_name == value:
            selected = key
            break
        
    show_list("load_playlist", right_column, playlists, get_playlist_name, load_playlist, selected, update)

def delete(update = False):
    selected = -1
    playlists = get_playlists_dict()
    for key, value in playlists.items(): 
        if playlist_name == value:
            selected = key
            break
        
    show_list("delete_playlist", right_column, playlists, get_playlist_name, delete_playlist, selected, update)

def delete_playlist(index):
    """Deletes a playlist by index after confirmation."""
    playlists = get_playlists_dict()  # Get dictionary of playlists

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
        print(f"Deleted playlist: {name}")
    except Exception as e:
        print(f"Error deleting playlist: {e}")
        return

    # Refresh the list display
    delete(True)

def delete_file_by_filename(filename):
    """Find the full path from directory_files and delete the file after confirmation."""
    filepath = directory_files.get(filename)
    
    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Delete File", f"The file does not exist or is not found:\n{filename}")
        return

    confirm = messagebox.askyesno("Delete File", f"Are you sure you want to delete this file?\n\n{filename}")
    if confirm:
        try:
            os.remove(filepath)
            messagebox.showinfo("File Deleted", f"Successfully deleted:\n{filename}")
            print(f"Deleted file: {filename}")
            # Optionally, remove from your directory_files dict too:
            del directory_files[filename]
        except Exception as e:
            messagebox.showerror("Error", f"Could not delete file:\n{e}")
    else:
        print(f"Deletion canceled for file: {filename}")

# =========================================
#           *STATS DISPLAY
# =========================================

def year_stats(column):
    year_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        # Year stats
        season = data.get("season", "")
        year = season[-4:] if season and season[-4:].isdigit() else "Unknown"
        year_counter[year] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY YEAR\n", ("bold", "underline"))
    for year in sorted(year_counter, reverse=True, key=lambda y: int(y) if y.isdigit() else 9999):
        column.insert(tk.END, f"{year}: ", "bold")
        column.insert(tk.END, f"{year_counter[year]} ({(round(year_counter[year]/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_filenames_from_year(year), False, False)
        column.insert(tk.END, f"\n")
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
    column.insert(tk.END, "TAG FREQUENCY\n", ("bold", "underline"))
    for tag, count in sorted(tag_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{tag}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_filenames_from_tag(tag), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

def series_stats(column):
    series_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        # Series
        series = data.get("series") or data.get("title", "Unknown")
        if isinstance(series, list):
            for s in series:
                series_counter[s] += 1
        else:
            series_counter[series] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY SERIES\n", ("bold", "underline"))
    for series, count in sorted(series_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{series}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_all_matching_field("series", [series]), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

def artist_stats(column):
    artist_counter = Counter()
    for filename in directory_files:
        data = get_metadata(filename)
        slug = file_metadata.get(filename, {}).get("slug")
        # Artists (only if the slug matches)
        for song in data.get("songs", []):
            if song.get("slug") == slug:
                for artist in song.get("artist", []):
                    artist_counter[artist] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "TOP ARTISTS\n", ("bold", "underline"))
    for artist, count in sorted(artist_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{artist}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
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
    column.insert(tk.END, "TOP STUDIOS\n", ("bold", "underline"))
    for studio, count in sorted(studio_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{studio}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
        add_field_total_button(column, get_filenames_from_studio(studio), False, False)
        column.insert(tk.END, f"\n")
    column.config(state=tk.DISABLED)

STAT_TYPES = [
    {"name":"THEMES PER YEAR", "func":year_stats},
    {"name":"THEMES PER SEASON", "func":season_stats},
    {"name":"TOP ARTISTS", "func":artist_stats},
    {"name":"TOP SERIES", "func":series_stats},
    {"name":"TOP STUDIOS", "func":studio_stats},
    {"name":"TOP TAGS", "func":tag_stats}
]

def display_theme_stats_in_columns():
    """Displays year stats, artist stats, series stats, and studio stats in the respective UI columns."""
    left_column.config(state=tk.NORMAL)
    left_column.delete("1.0", tk.END)
    left_column.insert(tk.END, "STATISTICS\n", ("bold", "underline"))
    for s in STAT_TYPES:
        left_column.insert(tk.END, f"{s.get("name")}", "bold")
        btn = tk.Button(left_column, text="▶", borderwidth=0, pady=0, command=lambda func=s.get("func"): func(middle_column), bg="black", fg="white")
        left_column.window_create(tk.END, window=btn)
        left_column.insert(tk.END, f"\n")
    left_column.config(state=tk.DISABLED)

# =========================================
#           *FILTERING PLAYLISTS
# =========================================

def load_filters(update = False):
    filters = get_all_filters()
    show_list("load_filters", right_column, filters, get_filter_name, load_filter, -1, update)

def get_filter_name(key, value):
    return value.get("name")

def load_filter(index):
    """Applys a saved filter from JSON."""
    filter_data = get_all_filters()[index]
    name = filter_data.get('name')
    confirm = messagebox.askyesno("Filter Playlist", f"Are you sure you want to apply the filter '{name}'?")
    if not confirm:
        return  # User canceled
    filter_playlist(filter_data.get("filter"))

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
    delete_filters(True)

def filters():
    show_filter_popup()

def show_filter_popup():
    """Opens a properly formatted, scrollable popup for filtering the playlist."""
    def update_score_range(event=None):
        """Ensures min_score does not exceed max_score."""
        min_score = min_score_slider.get()
        max_score = max_score_slider.get()
        
        if min_score > max_score:
            if event == min_score:
                max_score_slider.set(min_score)  # Adjust max if min is moved beyond it
            else:
                min_score_slider.set(max_score)  # Adjust min if max is moved below it
    
    def filter_entry_range(title, root_frame, start, end):
        frame = tk.Frame(root_frame, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)

        tk.Label(frame, text=title + " RANGE", bg=BACKGROUND_COLOR, fg="white").pack(side="left", pady=(0, 0))

        min_entry = tk.Entry(frame, bg="black", fg="white", justify="center", width=8)
        min_entry.pack(side="left", pady=0)
        min_entry.delete(0, tk.END)
        min_entry.insert(0, start)

        tk.Label(frame, text=" TO ", bg=BACKGROUND_COLOR, fg="white").pack(side="left", pady=(0, 0))

        max_entry = tk.Entry(frame, bg="black", fg="white", justify="center", width=8)
        max_entry.pack(side="left", pady=0)
        max_entry.delete(0, tk.END)
        max_entry.insert(0, end)

        return {
            "min":min_entry,
            "max":max_entry
        }
    
    def filter_entry_listbox(title, root_frame, data):
        frame = tk.Frame(root_frame, bg=BACKGROUND_COLOR)
        frame.pack(fill="x", pady=5)

        tk.Label(frame, text=title, bg=BACKGROUND_COLOR, fg="white").pack(side="left", pady=(0, 0))

        listbox = tk.Listbox(frame, selectmode=tk.MULTIPLE, height=6, width=20, exportselection=False, bg="black", fg="white")
        listbox.pack(side="left", fill="x", expand=True)
        
        scrollbar = tk.Scrollbar(frame, command=listbox.yview, bg="black")
        scrollbar.pack(side="right", fill="y")
        
        listbox.config(yscrollcommand=scrollbar.set)

        for item in data:
            listbox.insert(tk.END, item)

        return listbox
    popup = tk.Toplevel(bg="black")
    popup.title("Filter Playlist")
    popup.geometry("250x750")  # Ensures a good starting size

    # Create a frame inside the popup to hold everything
    main_frame = tk.Frame(popup, bg=BACKGROUND_COLOR)
    main_frame.pack(fill="both", expand=True)

    # Create a canvas with scrollbar
    canvas = tk.Canvas(main_frame, bg=BACKGROUND_COLOR)
    scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=BACKGROUND_COLOR)

    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    tk.Label(scrollable_frame, text="KEYWORDS (separated by commas):", bg=BACKGROUND_COLOR, fg="white").pack(anchor="w", pady=(5, 0))
    keywords_entry = tk.Entry(scrollable_frame, width=40, bg="black", fg="white")
    keywords_entry.pack(pady=2)

    # Label for Theme Type

    # Dropdown (Combobox) for Theme Type Selection

    theme_type_frame = tk.Frame(scrollable_frame, bg=BACKGROUND_COLOR)
    theme_type_frame.pack(fill="x", pady=5)

    tk.Label(theme_type_frame, text="THEME TYPE:", bg=BACKGROUND_COLOR, fg="white").pack(side="left", pady=(0, 0))

    theme_var = tk.StringVar(value="Both")  # Default value
    theme_type_dropdown = tk.OptionMenu(theme_type_frame, theme_var, "Both", "Opening", "Ending")
    theme_type_dropdown.config(bg="black", fg="white", width=20)  # Match style
    theme_type_dropdown.pack(side="left", pady=0)

    score_frame = tk.Frame(scrollable_frame, bg=BACKGROUND_COLOR)
    score_frame.pack(fill="x")# Score Range Slider

    tk.Label(score_frame, text="SCORE\nRANGE", bg=BACKGROUND_COLOR, fg="white").pack(side="left", pady=(0, 0))

    lowest_score = get_lowest_parameter("score")
    highest_score = get_highest_parameter("score")

    min_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, borderwidth=0, orient="horizontal", bg="black", fg="white", command=update_score_range)
    min_score_slider.pack(fill="x")
    min_score_slider.set(lowest_score)

    max_score_slider = tk.Scale(score_frame, from_=0, to=10, resolution=0.1, orient="horizontal", bg="black", fg="white", command=update_score_range)
    max_score_slider.pack(fill="x")
    max_score_slider.set(highest_score)

    rank_entry = filter_entry_range("RANK", scrollable_frame, get_highest_parameter("rank"), get_lowest_parameter("rank"))

    members_entry = filter_entry_range("MEMBERS", scrollable_frame, get_lowest_parameter("members"), get_highest_parameter("members"))

    popularity_entry = filter_entry_range("POPULARITY", scrollable_frame, get_highest_parameter("popularity"), get_lowest_parameter("popularity"))

    artists_listbox = filter_entry_listbox("ARTISTS\nINCLUDE", scrollable_frame, get_all_artists())

    studio_listbox = filter_entry_listbox("STUDIOS\nINCLUDE", scrollable_frame, get_all_studios())

    all_tags = get_all_tags()

    tags_listbox = filter_entry_listbox("TAGS\nINCLUDE", scrollable_frame, all_tags)
    
    excluded_tags_listbox = filter_entry_listbox("TAGS\nEXCLUDE", scrollable_frame, all_tags)

    def extract_filter():
        def assign_filter_range_value(filter, type, entry, start, end):
            if start > end:
                if int(entry.get('min').get()) < start : filter[type + '_min'] = int(entry.get('min').get())
                if int(entry.get('max').get()) > end : filter[type + '_max'] = int(entry.get('max').get())
            else:
                if int(entry.get('min').get()) > start : filter[type + '_min'] = int(entry.get('min').get())
                if int(entry.get('max').get()) < end : filter[type + '_max'] = int(entry.get('max').get())
            return filter
        
        filters = {}
        if keywords_entry.get() != "" : filters['keywords'] = str(keywords_entry.get())
        if theme_var.get() != "Both" : filters['theme_type'] = str(theme_var.get())
        if float(min_score_slider.get()) != round(lowest_score, 1) : filters['score_min'] = float(min_score_slider.get()) 
        if float(max_score_slider.get()) != round(highest_score, 1) : filters['score_max'] = float(max_score_slider.get()) 
        filters = assign_filter_range_value(filters, 'rank', rank_entry, get_highest_parameter("rank"), get_lowest_parameter("rank"))
        filters = assign_filter_range_value(filters, 'members', members_entry, get_lowest_parameter("members"), get_highest_parameter("members"))
        filters = assign_filter_range_value(filters, 'popularity', popularity_entry, get_highest_parameter("popularity"), get_lowest_parameter("popularity"))
        if len([artists_listbox.get(i) for i in artists_listbox.curselection()]) > 0: filters["artists"] = [str(artists_listbox.get(i)) for i in artists_listbox.curselection()]
        if len([studio_listbox.get(i) for i in studio_listbox.curselection()]) > 0: filters["studios"] = [str(studio_listbox.get(i)) for i in studio_listbox.curselection()]
        if len([tags_listbox.get(i) for i in tags_listbox.curselection()]) > 0: filters["tags_include"] = [str(tags_listbox.get(i)) for i in tags_listbox.curselection()]
        if len([excluded_tags_listbox.get(i) for i in excluded_tags_listbox.curselection()]) > 0: filters["tags_exclude"] = [excluded_tags_listbox.get(i) for i in excluded_tags_listbox.curselection()]
        return filters

    def apply_filter():
        """Applies filters and closes the popup."""
        filters = extract_filter()
        filter_playlist(filters)
        popup.destroy()  # Close the filter popup

    def save_filter():
        filters = extract_filter()
        """Prompts for a filter name and saves the current filter to a JSON file."""
        if not os.path.exists(FILTERS_FOLDER):
            os.makedirs(FILTERS_FOLDER)  # Ensure the filters folder exists

        filter_name = simpledialog.askstring("Save Filter", "Enter a name for this filter:")
        if not filter_name:
            return  # User canceled or left it empty

        filter_path = os.path.join(FILTERS_FOLDER, f"{filter_name}.json")

        try:
            with open(filter_path, "w") as file:
                filter_json = {
                    "name":filter_name,
                    "filter":filters
                }
                json.dump(filter_json, file, indent=4)  # Save the filter as JSON
            messagebox.showinfo("Success", f"Filter '{filter_name}' saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save filter: {e}")

    # Buttons Frame (Always Visible)
    button_frame = tk.Frame(popup, bg="black")
    button_frame.pack(fill="x", pady=10)

    apply_button = tk.Button(button_frame, text="APPLY FILTER", bg="black", fg="white", command=apply_filter)
    apply_button.pack(side="left", padx=10)

    save_button = tk.Button(button_frame, text="SAVE FILTER", bg="black", fg="white", command=save_filter)
    save_button.pack(side="right", padx=10)

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

def get_playlists_dict():
    """Returns a dictionary of available playlists indexed numerically."""
    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)

    playlists = sorted(f for f in os.listdir(PLAYLISTS_FOLDER) if f.endswith(".json"))
    return {i: os.path.splitext(playlist)[0] for i, playlist in enumerate(playlists)}

def get_lowest_parameter(parameter):
    lowest = 10000000
    for filename in playlist:
        data = get_metadata(filename)
        if data:
            item = data.get(parameter, lowest)
            if item and item < lowest:
                lowest = item
    return lowest

def get_highest_parameter(parameter):
    highest = 0
    for filename in playlist:
        data = get_metadata(filename)
        if data:
            item = data.get(parameter, highest)
            if item and item > highest:
                highest = item
    return highest

def get_all_artists():
    artists = []
    for filename in playlist:
        data = get_metadata(filename)
        if data:
            for song in data.get('songs', []):
                for artist in song.get("artist", []):
                    if artist not in artists:
                        artists.append(artist)
    return sorted(artists, key=str.lower)

def get_all_tags(game=True, double=False):
    tags = []
    for anime in anime_metadata.values():
        if game or not is_game(anime):
            for tag in anime.get('genres', []) + anime.get('themes', []) + anime.get('demographics', []):
                if double or tag not in tags:
                    tags.append(tag)
    return sorted(tags)

def get_all_studios():
    studios = []
    for filename in playlist:
        data = get_metadata(filename)
        if data:
            for studio in data.get('studios', []):
                if studio not in studios:
                    studios.append(studio)
    return sorted(studios)

def filter_playlist(filters):
    """Filters the playlist based on given criteria."""
    global playlist
    filtered = []

    for filename in playlist:
        data = get_metadata(filename)
        # Extract metadata
        
        title = data.get("title", "").lower()
        eng_title = data.get("eng_title", "")
        if not eng_title:
            eng_title = ""
        theme_type = format_slug(data.get("slug"))
        score = float(data.get("score") or 0)
        rank = data.get("rank") or 100000
        members = int(data.get("members") or 0)
        popularity = data.get("popularity") or float('inf')
        artists = get_song_by_slug(data, data.get("slug", "")).get("artist", [])
        studios = data.get("studios", [])
        tags = set(data.get("genres", []) + data.get("themes", []) + data.get("demographics", []))  # Ensure tags are a set for fast lookup

        # Apply filters
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
        if "artists" in filters and not any(artist in artists for artist in filters["artists"]):
            continue
        if "studios" in filters and not any(studio in studios for studio in filters["studios"]):
            continue
        if "tags_include" in filters and not any(tag in tags for tag in filters["tags_include"]):
            continue
        if "tags_exclude" in filters and any(tag in tags for tag in filters["tags_exclude"]):
            continue

        # If all checks pass, add to filtered list
        filtered.append(filename)
    playlist = filtered
    print("Applied Filters:", filters)  # Debugging
    show_playlist(True)
    update_current_index()
    messagebox.showinfo("Playlist Filtered", f"Playlist filtered to {len(playlist)} videos.")

def get_song_by_slug(data, slug):
    """Returns the list of artists for the song matching the given slug."""
    for theme in data.get("songs", []):  # Iterate through themes
        if theme["slug"] == slug:  # Find the matching slug
            return theme
    return {}  # Return empty list if no match

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
    global playlist, list_index
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
    playlist.sort(key=lambda filename: (
        extract_season_data(filename) if key == "season" else
        float(get_metadata(filename).get(key, 0) or 0) if key in {"members", "score"} else
        get_metadata(filename).get(key, "").lower() if isinstance(get_metadata(filename).get(key), str) else "",
        filename.lower()  # Secondary sort by filename for consistency
    ), reverse=reverse)
    update_current_index()
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
        playlist.insert(current_index+1, filename)
        search_add(True, False)
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
    for filename in directory_files:
        metadata = get_metadata(filename)
        filename_trim = filename.replace(".webm", "").lower()
        title = metadata.get("title", "").lower()
        english_title = metadata.get("eng_title")
        if english_title:
            english_title = english_title.lower()
        if (search_term in filename_trim) or (title and search_term in title) or (english_title and search_term in english_title):
            results.append(filename)

    return results

def get_playlist_name(key, value):
    return value

def get_playlists_dict():
    """Returns a dictionary of available playlists indexed numerically."""
    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)

    playlists = sorted(f for f in os.listdir(PLAYLISTS_FOLDER) if f.endswith(".json"))
    return {i: os.path.splitext(playlist)[0] for i, playlist in enumerate(playlists)}

# =========================================
#            *LIGHTNING ROUNDS
# =========================================

light_round_started = False
light_round_start_time = None
light_round_number = 0
light_round_length = 12
light_round_answer_length = 8
light_mode = None
light_modes = {
    "regular":{
        "title":"Lightning Round",
        "img":"banners/lightning_round.webp",
        "desc":(
            "Opening/Ending starts at a random point.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "frame":{
        "title":"Frame Lightning Round",
        "img":"banners/frame_lightning_round.webp",
        "desc":(
            "You will be shown 4 different frames from the Opening/Ending.\n"
            "Each frame will be visible for " + str(light_round_length // 4) + " seconds.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "blind":{
        "title":"Blind Lightning Round",
        "img":"banners/blind_lightning_round.webp",
        "desc":(
            "Opening/Ending starts at a random point.\n"
            "You will only be able to hear the music.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "clues":{
        "length":20,
        "title":"Clues Lightning Round",
        "img":"banners/clues_lightning_round.webp",
        "desc":(
            "You will be shown various stats for the Anime.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "song":{
        "title":"Song Lightning Round",
        "img":"banners/song_lightning_round.webp",
        "desc":(
            "You will be shown song information for the Opening/Ending.\n"
            "It will be revealed over time, and the song plays the last few seconds.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "synopsis":{
        "title":"Synopsis Lightning Round",
        "length":20,
        "img":"banners/synopsis_lightning_round.webp",
        "desc":(
            "You will be shown a part of the synopsis for the Anime.\n"
            "It will be revealed word by word over time.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "title":{
        "title":"Title Lightning Round",
        "length":20,
        "img":"banners/title_lightning_round.webp",
        "desc":(
            "You will be shown the title with most letters blanked.\n"
            "Letters will be revealed over time.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "variety":{
        "title":"Variety Lightning Round",
        "img":"banners/variety_lightning_round.webp",
        "desc":(
            "Plays a different lightning round each anime.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    }
}

def toggle_light_mode(type=None):
    global light_mode, variety_light_mode_enabled
    if type == None or light_mode == type or (variety_light_mode_enabled and type == 'variety'):
        unselect_light_modes()
        toggle_coming_up_popup(False)
    else:
        unselect_light_modes()
        mode = light_modes[type]
        light_mode = type
        button_seleted(globals()[type + '_light_mode_button'], True)
        if type == 'variety':
            variety_light_mode_enabled = True
        if light_round_number == 0:
            image_path = mode.get("img")
            image_tk = None
            if os.path.exists(image_path):
                image = Image.open(image_path)
                image = image.resize((400, 225), Image.LANCZOS)  # Resize if needed
                image_tk = ImageTk.PhotoImage(image)  # Convert to Tkinter format
            toggle_coming_up_popup(True, mode.get("title"), mode.get("desc"), image_tk)

def unselect_light_modes():
    global light_mode, variety_light_mode_enabled
    light_mode = None
    variety_light_mode_enabled = False
    for key, value in light_modes.items():
        button_seleted(globals()[key + '_light_mode_button'], False)

last_round = -1
variety_light_mode_enabled = False
def set_variety_light_mode():
    global light_mode, last_round, variety_light_mode_enabled
    data = currently_playing.get('data')
    popularity = data.get('popularity') or 3000
    if popularity <= 100:
        round_options = [1,2,2,2,2,2,3,4,4,5,6,6]
    elif popularity <= 250:
        round_options = [0,1,2,2,2,2,3,4,5,5,6,6]
    elif popularity <= 500:
        round_options = [0,1,1,1,2,2,2,2,3,5,5,6]
    elif popularity <= 750:
        round_options = [0,0,0,1,1,1,1,2,2,2,5,6]
    elif popularity <= 1000:
        round_options = [0,0,0,0,1,1,1,1,2,2,5,6]
    elif popularity <= 1500:
        round_options = [0,0,0,0,0,1,1,1,1,1,2,6]
    else:
        round_options = [0,0,0,0,0,0,0,1,1,1,1,1]

    # Filter list
    if data.get("mal") in clues_anime_ids:
        round_options = [x for x in round_options if x != 3]
    if get_song_string(data, "artist") == "N/A":
        round_options = [x for x in round_options if x != 4]
    if len((data.get("synopsis") or "").split()) <= 40:
        round_options = [x for x in round_options if x != 5]
    if len(get_unique_letters(data.get('eng_title') or data.get('title'))) < 9:
        round_options = [x for x in round_options if x != 6]
    round_options = [x for x in round_options if x != last_round]

    random.shuffle(round_options)  # Shuffle in place

    next_round = round_options[0] if round_options else 0
    last_round = next_round
    unselect_light_modes()
    toggle_light_mode(get_light_round_by_index(next_round))
    variety_light_mode_enabled = True
    button_seleted(variety_light_mode_button, True)

def get_light_round_by_index(index):
    if index == 1:
        return "frame"
    elif index == 2:
        return "blind"
    elif index == 3:
        return "clues"
    elif index == 4:
        return "song"
    elif index == 5:
        return "synopsis"
    elif index == 6:
        return "title"
    else:
        return "regular"

def get_light_round_time():
    length = player.get_length()/1000
    buffer = 10
    if light_mode == 'blind':
        buffer = 1
    if length < (light_round_length+light_round_answer_length+(buffer*2)+1):
        return 1  # If the video is too short, start from 1
    start_time = None
    try_count = 0
    while start_time is None:
        start_time = random.randrange(buffer, int(length - (light_round_length+light_round_answer_length+buffer)))
        try_count = try_count + 1
        if try_count < 20 and not light_mode == 'blind':
            file_censors = censor_list.get(currently_playing.get('filename'))
            if file_censors != None:
                end_time = start_time+light_round_length
                for censor in file_censors:
                    if not (censor['end'] < start_time or censor['start'] > end_time):
                        start_time = None
                        break
    return start_time

clues_anime_ids = []
def update_light_round(time):
    global light_round_started, light_round_start_time, censors_enabled
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
            if not is_title_window_up():
                toggle_title_popup(True)
                set_black_screen(False)
                clean_up_light_round()
            if not light_mode:
                start_str = "end"
            set_countdown(start_str + " in..." + str(round(light_round_answer_length-(time - (light_round_start_time+light_round_length)))))
        else:
            time_left = (light_round_length-(time - light_round_start_time))
            if song_overlay_boxes:
                toggle_song_overlay(show_title=True, show_artist=time_left<=9, show_theme=time_left<=6, show_music=time_left<=4)
                player.audio_set_mute(time_left > 4)
                play_background_music(time_left > 4)
            elif synopsis_start_index is not None:
                toggle_synopsis_overlay(text=get_light_synopsis_string(min(41, (light_round_length*3)-round(time_left*3)+1)))
            elif light_progress_bar:
                set_progress_overlay(round((time - light_round_start_time)*100), light_round_length*100)
            elif title_overlay:
                word_num = min(7, (int(light_round_length-time_left) // 3)+2)
                set_frame_number(f"{word_num}/{min(7, len(title_light_letters))}")
                toggle_title_overlay(get_title_light_string(word_num))
            set_countdown(round(time_left))
    if light_mode and time < 1:
        toggle_coming_up_popup(False)
        light_round_started = True
        if light_mode == 'regular':
            root.after(500, set_black_screen, False)
        if light_round_start_time is None:
            light_round_start_time = get_light_round_time()
        if light_mode == 'blind':
            set_progress_overlay(light_round_start_time*100, light_round_length*100)
        elif light_mode == 'clues' or light_mode == 'song' or light_mode == 'synopsis' or light_mode == 'title':
            player.audio_set_mute(True)
            play_background_music(True)
            if light_mode == 'clues':
                toggle_clues_overlay()
            elif light_mode == 'song':
                toggle_song_overlay(show_title=True, show_artist=False, show_theme=False, show_music=False)
            elif light_mode == 'synopsis':
                pick_synopsis()
                toggle_synopsis_overlay(text=get_light_synopsis_string(words = 1))
            elif light_mode == 'title':
                set_title_light_text()
                toggle_title_overlay(get_title_light_string(2))
                set_frame_number(f"2/{min(7, len(title_light_string))}")
            pass
        player.set_time(int(float(light_round_start_time))*1000)
        player.set_fullscreen(True)
        set_countdown(light_round_length)
        set_light_round_number("#" + str(light_round_number))

def clean_up_light_round():
    set_progress_overlay(destroy=True)
    toggle_clues_overlay(destroy=True)
    toggle_song_overlay(destroy=True)
    toggle_synopsis_overlay(destroy=True)
    toggle_title_overlay(destroy=True)
    set_frame_number()
    if not disable_video_audio:
        player.audio_set_mute(False)
    play_background_music(False)

def light_round_transition():
    global video_stopped
    video_stopped = True
    player.pause()
    set_countdown()
    toggle_title_popup(False)
    set_black_screen(True)
    root.after(500, play_next)

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
    toggle_coming_up_popup(False)
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
    
    if currently_playing.get('filename') != currently_playing_filename:
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
                apply_censors(time/1000,length/1000)
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

clues_overlay = None  # Store the overlay window
def toggle_clues_overlay(destroy=False):
    """
    Toggles a Clues Lightning Round overlay displaying anime metadata.

    Args:
        destroy (bool): If True, removes the overlay.
    """
    global clues_overlay

    # If destroy is True, close the overlay and clear reference
    if destroy:
        if clues_overlay:
            screen_width = root.winfo_screenwidth()
            animate_window(clues_overlay, screen_width, 0, steps=20, delay=5, bounce=False, fade=None, destroy=True)
            # clues_overlay.destroy()
        clues_overlay = None
        return

    # Create overlay if it doesn’t exist
    if clues_overlay is None:
        clues_overlay = tk.Toplevel(root)
        clues_overlay.overrideredirect(True)  # Remove window borders
        clues_overlay.attributes("-topmost", True)  # Keep on top
        clues_overlay.attributes("-alpha", 0.8)  # Set transparency to 80%
        clues_overlay.configure(bg="black")

        # Set position in the middle of the screen
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        overlay_width = round(screen_width*.75)  # Doubled width
        overlay_height = round(screen_height*.80)   # Doubled height
        x = (screen_width - overlay_width) // 2
        y = (screen_height - overlay_height) // 2
        clues_overlay.update_idletasks()
        clues_overlay.geometry(f"{overlay_width}x{overlay_height}+{-screen_width}+{y}")
        # clues_overlay.geometry(f"{overlay_width}x{overlay_height}+{x}+{y}")
        clues_overlay.update_idletasks()

        # Create a grid layout
        clues_overlay.grid_columnconfigure(0, weight=1)
        clues_overlay.grid_columnconfigure(1, weight=1)
        clues_overlay.grid_columnconfigure(2, weight=2)  # Tags column wider
        clues_overlay.grid_rowconfigure(0, weight=1)
        clues_overlay.grid_rowconfigure(1, weight=1)
        clues_overlay.grid_rowconfigure(2, weight=1)
        # clues_overlay.grid_rowconfigure(3, weight=3)

        # Helper function to create a label box
        def create_box(row, column, title, value, columnspan=1, rowspan=1):
            frame = tk.Frame(clues_overlay, bg="black", padx=20, pady=20, highlightbackground="white", highlightthickness=4)  # Thick borders
            frame.grid(row=row, column=column, columnspan=columnspan, rowspan=rowspan, sticky="nsew", padx=10, pady=10)
            
            if title:
                # Title Label (ALL CAPS, Underlined, Bigger)
                title_label = tk.Label(frame, text=title.upper(), font=("Arial", 70, "bold", "underline"), fg="white", bg="black")
                title_label.pack(anchor="center")

            val_size = 60
            lines = value.count('\n')
            if lines > 5:
                val_size = val_size - 5*(lines - 5)
            # Value Label
            value_label = tk.Label(frame, text=value, font=("Arial", val_size), fg="white", bg="black", wraplength=650*columnspan, justify="center")
            value_label.pack(fill="both", expand=True)
            # adjust_font_size(value_label, frame, 650*columnspan)

        data = currently_playing.get("data")
        season=data.get('season').replace(" ", "\n")
        studio="\n".join(data.get("studios"))
        tags=get_tags_string(data).replace(", ", "\n")
        score=f"{data.get("score")}\n#{data.get('rank')}"
        popularity=f"{data.get("members") or 0:,}\n#{data.get("popularity") or "N/A"}"
        episodes = str(data.get("episodes") or "Airing")
        type = data.get("type")
        source = data.get("source")
        # theme = format_slug(data.get("slug"))
        # song = get_song_string(data)

        # Add metadata boxes
        create_box(0, 0, "Type", type)
        create_box(0, 1, "Source", source)
        create_box(0, 2, "Episodes", episodes)
        create_box(1, 0, "Season", season)
        create_box(1, 1, "Studio", studio)
        create_box(1, 2, "Tags", tags, rowspan=2)  # Tags box spans both rows
        create_box(2, 0, "Score", score)
        create_box(2, 1, "Members", popularity)
        # create_box(3, 0, None, theme + ": " + song, columnspan=3)
        animate_window(clues_overlay, x, y, steps=20, delay=5, bounce=False, fade=None)  # Animate to center

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
        "theme":   (theme_label, None, 0, int(screen_height * 0.28), 60, show_theme),
        "title":   ("SONG TITLE", song, 0, int(screen_height * 0.4), 120, show_title),
        "artist":  ("SONG ARTIST", artist, 0, int(screen_height * 0.65), 80, show_artist),
        "music":  ("             \n\n", None, 2, int(screen_height * 0.12), 70, show_music)
    }

    for key, (title, text, x_offset, y, font_size, show) in boxes.items():
        if show:
            if key not in song_overlay_boxes or (key != "music" and not song_overlay_boxes[key].winfo_exists()):
                box = tk.Toplevel(root)
                box.overrideredirect(True)
                box.attributes("-topmost", True)
                box.attributes("-alpha", 0.85)
                box.configure(bg="black", padx=20, pady=20)

                song_overlay_boxes[key] = box

                # Title label
                if key == "music":
                    title_lbl = tk.Label(box, text=title, font=("Arial", font_size, "bold"), fg="white", bg="black")
                else:
                    title_lbl = tk.Label(box, text=title, font=("Arial", 60, "bold", "underline"), fg="white", bg="black")
                if text:
                    title_lbl.pack(anchor="center")
                else:
                    title_lbl.pack(anchor="center", fill="both", expand=True)

                if key == "music":
                    text_lbl = tk.Label(box, text="🎵", font=("Arial", 1000), bg="black", fg=generate_random_color(100,255))
                    text_lbl.place(relx=0.5, rely=0.5, anchor="center")
                    # Start pulsating the music icon
                    pulsate_music_icon(text_lbl)
                elif text:
                    # Text label (optional)
                    text_lbl = tk.Label(box, text=text, font=("Arial", font_size), fg="white", bg="black", justify="center")
                    text_lbl.pack(fill="both", expand=True)
                    adjust_font_size(text_lbl, text, box_width, base_size=font_size, min_size=20)

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

synopsis_start_index = None
synopsis_split = None
def pick_synopsis():
    global synopsis_start_index, synopsis_split
    if not synopsis_start_index:
        synopsis = (currently_playing.get("data", {}).get("synopsis") or "No synopsis found.").split("[Written by MAL Rewrite]")[0]
        synopsis_split = synopsis.split(" ")
        length = len(synopsis_split)
        if length <= light_round_length*2:
            synopsis_start_index = 0
        else:
            synopsis_start_index = random.randint(0, length-(light_round_length*2))

TITLE_GENERIC_WORDS = {"the", "a", "an", "and", "of", "in", "on", "to", "with", "for", "by", "at", "from", "no"}
def get_light_synopsis_string(words = 41):
    for w in range(0, words):
        if len(synopsis_split) > (w+synopsis_start_index):
            word = synopsis_split[synopsis_start_index+w]
            data = currently_playing.get("data", {})
            word_check = word.lower().strip(",!." + '"')
            if word_check not in TITLE_GENERIC_WORDS and word_check in ((data.get("eng_title") or "") + " " + data.get("title", "")).lower().split():
                word = '_' * len(word)
            if w > 0:
                text = text + " " + word
            else:
                text = word
        if w == 40:
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

    if synopsis_start_index > 0:
        text = "..." + text

    if synopsis_overlay is None and text:
        synopsis_overlay = tk.Toplevel(root)
        synopsis_overlay.overrideredirect(True)
        synopsis_overlay.attributes("-topmost", True)
        synopsis_overlay.attributes("-alpha", 0.9)
        synopsis_overlay.configure(bg="black")

        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        overlay_width = round(screen_width * 0.7)
        wraplength = overlay_width - 60

        # 📏 Measure how tall the label will need to be
        content_height = measure_text_height(get_light_synopsis_string(), wraplength-20, font=("Arial", 60))+30
        overlay_height = content_height + 160  # Add space for padding/title

        x = (screen_width - overlay_width) // 2
        y = (screen_height - overlay_height) // 2

        synopsis_overlay.geometry(f"{overlay_width}x{overlay_height}+{-screen_width}+{y}")
        synopsis_overlay.update_idletasks()

        frame = tk.Frame(synopsis_overlay, bg="black", padx=20, pady=20, highlightbackground="white", highlightthickness=4)
        frame.pack(fill="both", expand=True)

        title_label = tk.Label(frame, text="SYNOPSIS:", font=("Arial", 70, "bold", "underline"),
                               fg="white", bg="black", anchor="w", justify="left")
        title_label.pack(anchor="w")

        synopsis_label = tk.Label(frame, text=text, font=("Arial", 60),
                                  fg="white", bg="black", wraplength=wraplength,
                                  justify="left", anchor="nw")
        synopsis_label.pack(side="top", anchor="w", fill="x", padx=10, pady=(10, 0))

        animate_window(synopsis_overlay, x, y, steps=20, delay=5, bounce=False, fade=None)

    elif text is not None and synopsis_label:
        synopsis_label.config(text=text)

def measure_text_height(text, wraplength, font=("Arial", 60), justify="left"):
    temp_root = tk.Tk()
    temp_root.withdraw()
    label = tk.Label(temp_root, text=text, font=font, wraplength=wraplength, justify=justify)
    label.update_idletasks()
    height = label.winfo_reqheight()
    temp_root.destroy()
    return height

title_light_letters = None
title_light_string = None
def set_title_light_text():
    global title_light_letters, title_light_string
    if not title_light_letters:
        data = currently_playing.get("data", {})
        title = data.get('eng_title') or data.get("title")
        title_light_letters = get_unique_letters(title)
        title_light_string = title
        random.shuffle(title_light_letters)

def get_unique_letters(title):
    letters = []
    for letter in title:
        if letter.isalnum() and letter.lower() not in letters:
            letters.append(letter.lower())
    return letters

def get_title_light_string(letters=0):
    revealed_title = ""
    for letter in title_light_string:
        if letter.isalnum():
            new_letter = "ˍ"
            for l in range(0, min(len(title_light_letters), letters)):
                if title_light_letters[l] == letter.lower():
                    new_letter = letter
                    continue
            revealed_title = revealed_title + new_letter
        else:
            revealed_title = revealed_title + letter
    return revealed_title

title_overlay = None
title_label_text = None
def toggle_title_overlay(title_text=None, destroy=False):
    """Displays an overlay with the blanked or masked anime title."""
    global title_overlay, title_label_text

    if destroy:
        if title_overlay:
            screen_width = root.winfo_screenwidth()
            animate_window(title_overlay, screen_width, 0, steps=20, delay=5, bounce=False, fade=None, destroy=True)
        title_overlay = None
        return

    if title_overlay is None:
        title_overlay = tk.Toplevel(root)
        title_overlay.overrideredirect(True)
        title_overlay.attributes("-topmost", True)
        title_overlay.attributes("-alpha", 0.9)
        title_overlay.configure(bg="black")

        title_font = ("Courier New", 80, "bold")

        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        overlay_width = round(screen_width * 0.7)
        overlay_height = measure_text_height(title_text, overlay_width - 40, font=title_font, justify="center")+300

        x = (screen_width - overlay_width) // 2
        y = (screen_height - overlay_height) // 2

        title_overlay.geometry(f"{overlay_width}x{overlay_height}+{-screen_width}+{y}")
        title_overlay.update_idletasks()

        # Frame with border
        frame = tk.Frame(title_overlay, bg="black", padx=20, pady=20, highlightbackground="white", highlightthickness=4)
        frame.pack(fill="both", expand=True)

        # Title
        title_label = tk.Label(frame, text="TITLE:", font=("Arial", 70, "bold", "underline"),
                               fg="white", bg="black", anchor="w", justify="left")
        title_label.pack(anchor="w", pady=(0, 10))

        # Text display
        title_label_text = tk.Label(frame, text=title_text or "", font=title_font,
                                    fg="white", bg="black", wraplength=overlay_width - 40,
                                    justify="center", anchor="center")
        title_label_text.pack(fill="both", expand=True)

        animate_window(title_overlay, x, y, steps=20, delay=5, bounce=False, fade=None)

    elif title_text is not None and title_label_text:
        title_label_text.config(text=title_text)

def set_countdown(value=None):
    """Creates, updates, or removes the countdown overlay in a separate always-on-top window with a semi-transparent background."""
    set_floating_text("Countdown", value, position="top right")

def set_light_round_number(value=None):
    size = 80
    if value:
        if len(value) >= 5:
            size = 48
        elif len(value) >= 4:
            size = 62
    set_floating_text("Lightning Round Number", value, position="bottom right", size=size)

def set_frame_number(value=None):
    set_floating_text("Frame Number", value, position="bottom center")

floating_windows = {}  # Dictionary to store windows and labels

def set_floating_text(name, value, position="top right", size=80):
    """
    Creates, updates, or removes a floating overlay window with text.

    Args:
        name (str): A unique identifier for the floating window (e.g., "countdown", "light_round").
        value (str or int): The text to display. If None or '0', the window is removed.
        position (str): Where to place the window (e.g., "top left", "bottom center", "middle right").
    """
    global floating_windows

    # Remove window if value is '0' or negative
    if value is None or isinstance(value, str) and value == '0' or isinstance(value, int) and value < 0:
        if name in floating_windows:
            floating_windows[name]["window"].destroy()
            del floating_windows[name]
        return

    # Create the window if it doesn't exist
    if name not in floating_windows:
        window = tk.Toplevel()
        window.title(name)
        window.overrideredirect(True)  # Remove window borders
        window.attributes("-topmost", True)  # Keep it on top
        window.wm_attributes("-alpha", 0.7)  # Semi-transparent background
        window.configure(bg="black")

        label = tk.Label(window, font=("Arial", size, "bold"), fg="white", bg="black")
        label.pack(padx=20, pady=10)

        floating_windows[name] = {"window": window, "label": label}

        # Temporarily place at (0,0) before positioning update
        window.geometry("+0+0")
    
    else:
        window = floating_windows[name]["window"]
        label = floating_windows[name]["label"]

    # Update the label text
    label.config(text=str(value), font=("Arial", size, "bold"))

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
    # update_position()

overlay = None
light_progress_bar = None
music_icon_label = None

def set_progress_overlay(current_time=None, total_length=None, destroy=False):
    """
    Creates/updates or destroys an overlay with a large progress bar.
    
    The overlay is a frameless, semi-transparent window centered on the screen.
    It displays only a progress bar that you update manually.
    
    Args:
        current_time: Current progress (e.g., seconds elapsed) to set the progress bar value.
        total_length: Total length (e.g., total seconds) to set as the maximum of the progress bar.
        destroy (bool): If True, the overlay (if present) is destroyed.
    """
    global overlay, light_progress_bar, music_icon_label
    # If asked to destroy, close the overlay and clear globals
    if destroy:
        if overlay is not None:
            screen_width = overlay.winfo_screenwidth()
            screen_height = overlay.winfo_screenheight()
            window_height = round((screen_height/15)*6)
            animate_window(overlay, screen_width, (screen_height - window_height) // 2, steps=20, delay=5, bounce=False, fade=None, destroy=True)
        overlay = None
        light_progress_bar = None
        return

    # Create overlay if it doesn't exist
    if overlay is None:
        overlay = tk.Toplevel(root)
        overlay.title("Blind Progress Bar")
        overlay.overrideredirect(True)  # Remove window decorations
        overlay.attributes("-topmost", True)  # Ensure it stays on top
        overlay.attributes("-alpha", 0.8)  # Semi-transparent
        overlay.configure(bg="black")
        
        # Set a larger size for the overlay (e.g., 800x200) and center it
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        width, height = round(screen_width*.7), round((screen_height*.5))

        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        overlay.update_idletasks()
        overlay.geometry(f"{width}x{height}+{-screen_width}+{y}")
        # overlay.geometry(f"{width}x{height}+{x}+{y}")
        style = ttk.Style(root)
        style.theme_use('default')

        # To change the background color (trough color):
        # style.configure("Horizontal.TProgressbar", troughcolor=generate_random_color(), thickness=50)
        style.configure("Horizontal.TProgressbar", thickness=round(screen_height/15))

        # # To change the foreground color (bar color):
        style.configure("Horizontal.TProgressbar", background=generate_random_color(0,200))

        # # To change the border color:
        style.configure("Horizontal.TProgressbar", bordercolor='black', borderwidth=10, relief="solid")

        # To change light and dark color of the bar:
        # style.configure("Horizontal.TProgressbar", lightcolor='white', darkcolor='black')
        
        # Create a larger progress bar inside the overlay (length 700 pixels)
        light_progress_bar = ttk.Progressbar(overlay, orient="horizontal", mode="determinate", length=round(screen_width*.6))
        light_progress_bar.place(relx=0.5, rely=0.7, anchor="center")
        
        # Add a music icon (using a label with text or an image)
        music_icon_label = tk.Label(overlay, text="🎵", font=("Arial", 100), bg="black", fg=generate_random_color(100,255)) #  🎶 🎵  🎶
        music_icon_label.place(relx=0, rely=0.35, anchor="center")

        # Start pulsating the music icon
        pulsate_music_icon(music_icon_label)
        overlay.update_idletasks()
        animate_window(overlay, x, y, steps=20, delay=5, bounce=False, fade=None)  # Animate to center

    # If current_time and total_length are provided, update the progress bar
    if current_time is not None and total_length is not None:
        move_music_icon(current_time, total_length)
        light_progress_bar["maximum"] = total_length
        light_progress_bar["value"] = current_time
        overlay.wm_attributes("-topmost", True)

pulse_step = 0  # Track animation progress
move_active = False  # Control movement loop

def pulsate_music_icon(label):
    """Creates a smooth pulsating effect for the music icon using sinusoidal scaling."""
    global music_icon_label, pulse_step

    if label.winfo_exists():
        if player.is_playing():
            base_size = 160  # Minimum size
            max_size = 200  # Maximum size
            speed = 0.1  # Speed of pulsation (lower is slower, higher is faster)

            # Use sine wave for smooth size transition
            pulse_step += speed
            new_size = int(base_size + (math.sin(pulse_step) * (max_size - base_size) / 2))

            # Apply new font size
            label.config(font=("Arial", new_size))

        # Loop animation
        if label.winfo_exists():
            root.after(5, pulsate_music_icon, label)  # Smooth update interval (50ms)

def move_music_icon(current_time, total_length):
    """Moves the music icon left to right along the progress bar."""
    global music_icon_label, light_progress_bar, move_active

    if music_icon_label is None or light_progress_bar is None:
        move_active = False  # Stop if elements are missing
        return

    if not move_active:
        move_active = True  # Mark the movement loop as active

    # Calculate horizontal position based on progress
    progress_bar_x = light_progress_bar.winfo_x()  # X position of progress bar
    progress_bar_width = light_progress_bar.winfo_width()  # Width of progress bar
    icon_width = 40  # Approximate width of the music icon

    if total_length > 0:  # Avoid division by zero
        progress_ratio = min(max(current_time / total_length, 0), 1)  # Clamp between 0-1
        new_x = progress_bar_x + (progress_ratio * (progress_bar_width - icon_width))  # Move across bar

        # Move the music icon
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

def load_music_files():
    """Load all music files from the "music" folder"""
    global music_files, current_music_index
    music_folder = "music"
    if os.path.exists(music_folder):
        music_files = [os.path.join(music_folder, f) for f in os.listdir(music_folder) if f.endswith((".mp3", ".wav", ".ogg"))]
        random.shuffle(music_files)  # Randomize playlist
        current_music_index = 0  # Start at the first track

def next_background_track():
    global current_music_index, music_changed
    if music_files:
        current_music_index = current_music_index + 1
        if current_music_index >= len(music_files):
            current_music_index = 0
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
            pygame.mixer.music.set_volume(0.15*(volume_level/100))  # Adjust volume
            music_changed = False
            now_playing_background_music(music_files[current_music_index])

def now_playing_background_music(track = None):
    if track:
        track = "NOW PLAYING: " + os.path.basename(track).split(".")[0]
    set_floating_text("Now Playing Background Music", track, position="bottom left", size=10)

# =========================================
#            *INFORMATION POPUP
# =========================================

def toggle_info_popup():
    toggle_title_popup(not is_title_window_up())

def animate_window(window, target_x, target_y, steps=20, delay=5, bounce=True, fade="in", destroy=False):
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
            # Bounce effect (stronger overshoot near the end of movement)
            bounce_strength = math.sin((i / steps) * math.pi) * 5 if bounce and i > steps * 0.7 else 0

            new_x = int(start_x + delta_x * i + bounce_strength)
            new_y = int(start_y + delta_y * i + bounce_strength)
            window.geometry(f"+{new_x}+{new_y}")

            # Fade-in effect from 0 to original_alpha
            if fade == "in":
                alpha = min(original_alpha, (i / steps) * original_alpha)
                window.attributes("-alpha", alpha)
            elif fade == "out":
                alpha = max(0, ((steps - i) / steps) * original_alpha)
                window.attributes("-alpha", alpha)

            if i < steps:
                window.after(delay, lambda: step(i + 1))
            elif destroy and window:
                window.destroy()  # Call the completion function after animation ends
            else:
                window.after(delay*20, lambda: window.geometry(f"+{new_x}+{new_y}"))

    step()  # Start animation

title_window = None  # Store the title popup window
title_row_label = None
top_row_label = None
bottom_row_label = None

def adjust_font_size(label, text, max_width, base_size=50, min_size=20):
    """Adjusts the font size dynamically to fit within max_width."""
    font_size = base_size
    label.config(font=("Arial", font_size, "bold"))
    
    label.update_idletasks()  # Ensure geometry updates
    while label.winfo_reqwidth() > max_width and font_size > min_size:
        font_size -= 2
        label.config(font=("Arial", font_size, "bold"))

def is_title_window_up():
    return not (title_window is None or title_window.attributes("-alpha") == 0)

def toggle_title_popup(show):
    """Creates or destroys the title popup at the bottom middle of the screen."""
    global title_window, title_row_label, top_row_label, bottom_row_label, info_button, light_mode
    if not is_title_window_up() and not show:
        return
    if title_window:
        screen_width = title_window.winfo_screenwidth()
        screen_height = title_window.winfo_screenheight()
        window_width = title_window.winfo_reqwidth()
        window_height = title_window.winfo_reqheight()
        if not show:
            animate_window(title_window, (screen_width - window_width) // 2, screen_height, fade="out")
    button_seleted(info_button, show and not light_mode)
    if not show:
        return

    if guessing_extra:
        guess_extra()

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
    top_font = ("Arial", 20, "bold")
    title_font = ("Arial", 50, "bold")
    bottom_font = ("Arial", 15, "bold")
    data = currently_playing.get("data")
    if data:
        if currently_playing.get("type") == "youtube":
            title = data.get("title")
            full_title = data.get("full_title")
            uploaded = f"{datetime.strptime(data.get("upload_date"), "%Y%m%d").strftime("%Y-%m-%d")}"
            views = f"{data.get("view_count"):,}"
            likes = f"{data.get("like_count"):,}"
            channel = data.get("channel")
            subscribers = f"{data.get("channel_follower_count"):,}"
            duration = str(format_seconds(get_youtube_duration(data))) + " mins"

            top_row = f"Uploaded by {channel} ({subscribers} subscribers)"
            title_row = title
            bottom_row = f"{full_title}\nViews: {views} | Likes: {likes} | {uploaded} | {duration}"
        else:
            japanese_title = data.get("title")
            title = data.get("eng_title") or japanese_title or (data.get("synonyms", [None]) or [None])[0]
            theme = format_slug(data.get("slug"))
            song = get_song_string(data)
            if is_game(data):
                aired = data.get("release")
            else:
                aired = data.get("season")
            studio = ", ".join(data.get("studios"))
            tags = get_tags_string(data)
            type = data.get("type")
            source = data.get("source")
            if data.get("platforms"):
                episodes = ", ".join(data.get("platforms"))
                members = f"Reviews: {(data.get("reviews", 0) or 0):,}"
                score = f"Score: {data.get("score")}"
            else:
                episodes =  data.get("episodes")
                if not episodes:
                    episodes = "Airing"
                else:
                    episodes = str(episodes) + " Episodes"
                members = f"Members: {data.get("members") or 0:,} (#{data.get("popularity") or "N/A"})"
                score = f"Score: {data.get("score")} (#{data.get("rank")})"
            top_row = f"{theme}{overall_theme_num_display(currently_playing.get("filename"))} | {song} | {aired}"
            title_row = title
            bottom_row = f"{score} | {japanese_title} | {members}\n{studio} | {tags} | {episodes} | {type} | {source}"
    else:
        top_font = ("Arial", 1)
        bottom_font = ("Arial", 1)
        title_row = currently_playing.get("filename").split(".")[0]

    if title_row_label:
        title_row_label.config(text=title_row, font=title_font)
        top_row_label.config(text=top_row, font=top_font)
        bottom_row_label.config(text=bottom_row, font = bottom_font)
    else:
        top_row_label = tk.Label(title_window, text=top_row,
                                font=top_font, fg="white", bg="black")
        top_row_label.pack(pady=(10, 0), padx = 10)

        # Title Label (Large Text)
        title_row_label = tk.Label(title_window, text=title_row, font=title_font, fg="white", bg="black")
        title_row_label.pack(pady=(0, 0), padx = 10)

        bottom_row_label = tk.Label(title_window, text=bottom_row,
                                font=bottom_font, fg="white", bg="black")
        bottom_row_label.pack(pady=(0, 10), padx = 10)

    # Dynamically adjust font size to fit window width
    title_window.update_idletasks()
    max_width = title_window.winfo_screenwidth() - 550  # Leave padding
    adjust_font_size(title_row_label, title_row, max_width)
    
    # Position at the bottom center of the screen
    title_window.update_idletasks()  # Ensure correct size update
    screen_width = title_window.winfo_screenwidth()
    screen_height = title_window.winfo_screenheight()
    window_width = title_window.winfo_reqwidth()
    window_height = title_window.winfo_reqheight()
    title_window.geometry(f"+{(screen_width - window_width) // 2}+{screen_height}")  # Adjust for bottom spacing
    root.after(1, lambda: animate_window(title_window, (screen_width - window_width) // 2, screen_height - window_height - 20))

def get_tags_string(data):
    tags_string = ", ".join(data.get('genres'))
    for c in ['themes','demographics']:
        if data.get(c):
            tags_string = tags_string + ", " + ", ".join(data.get(c))

    return tags_string

def get_song_string(data, type=None):
    for theme in data.get("songs", []):
        if theme.get("slug") == data.get("slug"):
            if type:
                if type == "artist":
                    return get_artists_string(theme.get("artist"))
                else:
                    return theme.get(type)
            else:
                return theme.get("title") + " by " + get_artists_string(theme.get("artist"))
    return ""
    
# =========================================
#         *GUESS YEAR/MEMBERS/SCORE
# =========================================

guessing_extra = None
def guess_extra(extra = None):
    global guessing_extra
    buttons = [guess_year_button, guess_members_button, guess_score_button, guess_tags_button]
    for b in buttons:
        button_seleted(b, False)
    if extra:
        if extra == guessing_extra:
            guessing_extra = None
            toggle_coming_up_popup(False)
        else:
            guessing_extra = extra
        if guessing_extra == "year":
            button_seleted(guess_year_button, True)
            toggle_coming_up_popup(True, 
                                "Guess The Year This Anime Aired", 
                                ("Only 1 guess per person, no repeats.\n"
                                "+1 PT for closest guess. "
                                "+2 PTs if exact year."),
                                up_next=False)
        elif guessing_extra == "members":
            button_seleted(guess_members_button, True)
            toggle_coming_up_popup(True, 
                                "Guess The Number Of Members This Anime Has On MyAnimeList", 
                                ("Members are users who added the anime to their list.\n"
                                 "EG: Death Note has over 4 million. Only 1 guess per person, no repeats.\n"
                                "+1 PT for closest guess. "
                                "+2 PTs if within 10,000 of member count."),
                                up_next=False)
        elif guessing_extra == "score":
            button_seleted(guess_score_button, True)
            toggle_coming_up_popup(True, 
                                "Guess The Score This Anime Has On MyAnimeList", 
                                ("Scores range from 0.0 to 10.0. Only 1 guess per person, no repeats.\n"
                                "+1 PT for closest guess. "
                                "+2 PTs if exact score."),
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
            tags_1, tags_2 = split_array_half(get_random_tags())
            toggle_coming_up_popup(True, 
                                "Guess The " + tags + " This Anime Has", 
                                (""
                                "Guess until you get a tag wrong. +1 PT for each correct tag.\n\n"
                                "[" + "] [".join(tags_1) + "]\n[" + "] [".join(tags_2)) + "]",
                                up_next=False)
            
    else:
        guessing_extra = None
        toggle_coming_up_popup(False)

def get_random_tags():
    data = currently_playing.get("data")
    if data:
        tags = data.get('genres', []) + data.get('themes', []) + data.get('demographics', [])
        tags_len = len(tags)
        all_tags = get_all_tags(game=False, double=True)
        all_tags_len = len(get_all_tags(game=False))
        while len(tags) < 20 and len(tags) < tags_len*4 and len(tags) != all_tags_len:
            random_tag = random.choice(all_tags)
            if random_tag not in tags:
                tags.append(random_tag)
        return sorted(tags)
    return []

def split_array_half(arr):
    mid = len(arr) // 2
    return arr[:mid], arr[mid:]

# =========================================
#         *VIDEO PLAYBACK/CONTROLS
# =========================================

currently_playing = {}
def play_video(index = current_index):
    """Function to play a specific video by index"""
    global video_stopped, currently_playing, search_queue, censors_enabled, frame_light_round_started, light_round_start_time, synopsis_start_index, title_light_letters, playlist_loaded, guessing_year
    playlist_loaded = False
    light_round_start_time = None
    synopsis_start_index = None
    title_light_letters = None
    clean_up_light_round()
    video_stopped = True
    guess_extra()
    toggle_title_popup(False)
    set_countdown()
    frame_light_round_started = False
    if youtube_queue is not None:
        currently_playing = {
            "type":"youtube",
            "filename":youtube_queue.get("filename"),
            "data":youtube_queue
        }
        set_black_screen(False)
        reset_metadata()
        update_youtube_metadata()
        stream_youtube(youtube_queue.get("filename"))
        unload_youtube_video()
    elif search_queue:
        play_filename(search_queue)
        search_queue = None
    elif 0 <= index < len(playlist):
        update_current_index(index)
        play_filename(playlist[current_index])
    else:
        messagebox.showinfo("Playlist Error", "Invalid playlist index.")
    root.after(3000, thread_prefetch_metadata)

all_themes_played = []
def play_filename(filename):
    global blind_round_toggle, currently_playing, video_stopped, clues_anime_ids, all_themes_played
    filepath = directory_files.get(filename)  # Get file path from playlist
    if not filepath or not os.path.exists(filepath):  # Check if file exists
        print(f"File not found: {filepath}. Skipping...")
        blind_round_toggle = False
        play_video(current_index + 1)  # Try playing the next video
        return
    currently_playing = {
        "type":"theme",
        "filename":filename,
        "data":get_metadata(filename, fetch=True)
    }
    update_censor_button_count()
    if variety_light_mode_enabled:
        set_variety_light_mode()
    if light_mode == 'clues':
        mal_id = currently_playing.get("data").get("mal")
        if mal_id in clues_anime_ids and filename not in all_themes_played:
            play_next()
            return
        else:
            clues_anime_ids.append(mal_id)
    if auto_info_start:
        toggle_title_popup(True)
    # Update metadata display asynchronously
    update_metadata_queue(current_index)
    media = instance.media_new(filepath)
    player.set_media(media)
    global light_round_number, light_round_length
    if light_mode:
        if light_round_number%10 == 0:
            next_background_track()
        light_round_number = light_round_number + 1
        set_light_round_number("#" + str(light_round_number))
        light_round_length = light_modes[light_mode].get("length", 12)
        if not black_overlay:
            set_black_screen(True)
            root.after(500, lambda: player.play())
        else:
            player.play()
    else:
        light_round_number = 0
        set_countdown()
        set_light_round_number(str(light_round_number))
        global manual_blind
        toggle_coming_up_popup(False)
        if blind_round_toggle:
            blind_round_toggle = False
            button_seleted(blind_round_button, blind_round_toggle)
            manual_blind = True
            set_black_screen(True)
            root.after(500, lambda: player.play())
        else:
            manual_blind = False
            set_black_screen(False)
            player.play()
        root.after(500, play_video_retry, 5)  # Retry playback
    if filename not in all_themes_played:
        all_themes_played.append(filename)
    save_config()

def thread_prefetch_metadata():
    threading.Thread(target=pre_fetch_metadata, daemon=True).start()

def play_video_retry(retries):
    global video_stopped
    # Check if the video is playing
    if not player.is_playing():
        if retries > 0:
            if retries < 5:
                print(f"Retrying playback for: {currently_playing.get('filename')}")
                player.play()
            root.after(2000, play_video_retry, retries - 1)  # Retry playback
            return
        else:
            play_next()
    player.set_fullscreen(True)
    video_stopped = False

# Function to play next video
def play_next():
    if playlist_loaded:
        play_video(current_index)
    elif current_index + 1 < len(playlist):
        play_video(current_index + 1)

def play_previous():
    """Function to play previous video"""
    if current_index - 1 >= 0:
        play_video(current_index - 1)

def check_video_end():
    """Function to check if the current video has ended"""
    global video_stopped
    if player.is_playing() or video_stopped:
        # If the video is still playing, check again in 1/2 second
        root.after(500, check_video_end)
    else:
        # If the video has ended, play the next video
        play_next()
        video_stopped = True
        root.after(10000, check_video_end)

def update_current_index(value = 0):
    """Function to update the current entry text box"""
    global current_index
    current_index = value
    current_entry.delete(0, tk.END)
    current_entry.insert(0, str(current_index+1))
    playlist_size_label.configure(text = "/" + str(len(playlist)))
    save_config()

def load_youtube_video(index):
    global youtube_queue
    video = get_youtube_metadata_from_index(int(index))
    if video and youtube_queue != video:
        unload_youtube_video()
        youtube_queue = video
        title = youtube_queue.get('title')
        try:
            image = load_image_from_url(youtube_queue.get('thumbnail'))
        except:
            image = None
        details = (
            "Created by: " + youtube_queue.get("channel") + " (" + str(f"{youtube_queue.get("channel_follower_count"):,}") + " subscribers)" + "\n"
            "Uploaded: " + str(f"{datetime.strptime(youtube_queue.get("upload_date"), "%Y%m%d").strftime("%Y-%m-%d")}") + " | Duration: " + str(format_seconds(get_youtube_duration(youtube_queue))) + " mins\n\n"
            "1 PT for the first correct answer."
        )
        if player.is_playing():
            toggle_coming_up_popup(True, title, details, image)
        else:
            play_video()
    else:
        unload_youtube_video()
    show_youtube_playlist(True)

def load_image_from_url(url, size=(400, 225)):
    """Loads an image from a URL and returns a Tkinter-compatible ImageTk.PhotoImage."""
    response = requests.get(url)
    response.raise_for_status()  # Ensure the request was successful
    image = Image.open(BytesIO(response.content))
    image = image.resize(size, Image.LANCZOS)  # Resize the image if needed
    return ImageTk.PhotoImage(image)

def unload_youtube_video():
    global youtube_queue
    youtube_queue = None
    toggle_coming_up_popup(False)

def stream_youtube(youtube_url):
    """Streams a YouTube video in VLC using yt-dlp to get a direct URL."""
    media = instance.media_new(youtube_url)
    player.set_media(media)
    player.play()
    check_youtube_video_playing()

def check_youtube_video_playing():
    if player.is_playing():
        global video_stopped
        video_stopped = False
        player.set_fullscreen(True)
    else:
        root.after(1000, check_youtube_video_playing)

def go_to_index():
    """Function to jump to a specific index"""
    try:
        index = int(current_entry.get())-1
        if 0 <= index < len(playlist):
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
    elif light_mode == 'clues' or light_mode == 'song' or light_mode == 'synopsis' or light_mode == 'title':
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
        play_video(current_index)

def stop():
    """Function to stop the video"""
    global video_stopped, currently_playing, censor_bar, light_mode
    video_stopped = True
    toggle_light_mode()
    clean_up_light_round()
    set_countdown()
    set_light_round_number()
    set_black_screen(False)
    player.stop()
    player.set_media(None)  # Reset the media
    currently_playing = {}
    update_progress_bar(0,1)
    if censor_bar:
        censor_bar.destroy()
        censor_bar = None

def seek(value):
    """Function to seek the video"""
    global can_seek
    if can_seek:
        player.set_time(int(float(value))*1000)
    else:
        can_seek = True

last_vlc_time = 0
projected_vlc_time = 0
SEEK_POLLING = 50
def update_seek_bar():
    """Function to update the seek bar"""
    global last_vlc_time, projected_vlc_time
    try:
        if player.is_playing():
            vlc_time = player.get_time()
            if vlc_time != last_vlc_time:
                last_vlc_time = vlc_time
                projected_vlc_time = vlc_time
            else:
                projected_vlc_time = projected_vlc_time + SEEK_POLLING
            length = player.get_length()/1000
            time = projected_vlc_time/1000
            if manual_blind:
                set_progress_overlay(time, length)
            if length > 0:
                global can_seek
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
                    if (length - time) <= 8:
                        if not light_mode and not is_title_window_up() and auto_info_end:
                            toggle_title_popup(True)
                        blind_round_coming_up()
                    update_light_round(time)
                    apply_censors(time, length)
            update_progress_bar(projected_vlc_time, player.get_length())
    except Exception as e:
        print("Error: " + str(e))
    root.after(SEEK_POLLING, update_seek_bar)

def format_seconds(seconds):
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f"{minutes:02}:{remaining_seconds:02}"

# =========================================
#            *OTHER UI OVERLAYS
# =========================================

coming_up_window = None  # Store the lightning round window
coming_up_title_label = None  # Store the label for the lightning round message
coming_up_rules_label = None

def toggle_coming_up_popup(show, title="", details="", image=None, up_next=True):
    """Creates or destroys the lightning round announcement popup with an optional image."""
    global coming_up_window, coming_up_title_label, coming_up_rules_label, light_round_length, image_label

    if coming_up_window:
        screen_width = coming_up_window.winfo_screenwidth()
        window_width = coming_up_window.winfo_reqwidth()
        window_height = coming_up_window.winfo_reqheight()
        if not show:
            root.after(10, lambda: coming_up_title_label.configure(text=""))
            animate_window(coming_up_window, (screen_width - window_width) // 2, -window_height)

    if not show:
        return

    if not coming_up_window:
        coming_up_window = tk.Toplevel()
        coming_up_window.title("UP NEXT!")
        coming_up_window.overrideredirect(True)  # Remove window borders
        coming_up_window.attributes("-topmost", True)  # Keep it on top
        coming_up_window.wm_attributes("-alpha", 0.8)  # Semi-transparent background
        coming_up_window.configure(bg="black")

    # Title
    if not coming_up_title_label:
        coming_up_title_label = tk.Label(coming_up_window, font=("Arial", 40, "bold", "underline"), fg="white", bg="black")
        coming_up_title_label.pack(pady=(10, 0), padx=10)
    if up_next:
        title = "UP NEXT: " + title + "!"
    if title == coming_up_title_label.cget("text"):
        return
    coming_up_title_label.configure(text=title)

    # Details
    if not coming_up_rules_label:
        coming_up_rules_label = tk.Label(coming_up_window, font=("Arial", 20, "bold"), fg="white", bg="black", justify="center", wraplength=1700)
        coming_up_rules_label.pack(pady=(5, 10))
    if image:
        coming_up_rules_label.configure(image=image, compound="top")
        coming_up_rules_label.image = image
    else:
        coming_up_rules_label.configure(image="")
        coming_up_rules_label.image = None
    coming_up_rules_label.configure(text=details)

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

# Global variable for the progress bar
progress_bar = None
progress_bar_enabled = True
def create_progress_bar(color="grey"):
    """Creates a thin progress bar at the bottom of the screen."""
    global progress_bar

    height = 5
    progress_bar = tk.Toplevel()
    progress_bar.title = "Progress Bar"
    progress_bar.overrideredirect(True)  
    progress_bar.attributes("-topmost", True)  
    progress_bar.wm_attributes("-alpha", 0.3)  
    progress_bar.configure(bg=color, width=0, height=height, highlightthickness=0)
    progress_bar.geometry(f"+{0}+{root.winfo_screenheight() - height}")  # Adjust for bottom spacing

def update_progress_bar(current_time, total_time):
    global progress_bar

    if not progress_bar_enabled:
        if progress_bar:
            progress_bar.destroy()
            progress_bar = None
        return

    if not progress_bar:
        create_progress_bar()
        progress_bar.update_idletasks()
    
    """Updates the progress bar based on video time."""
    if progress_bar and total_time > 0:
        screen_width = progress_bar.winfo_screenwidth()
        progress_width = int((current_time / total_time) * screen_width)
        height = progress_bar.winfo_height()
        progress_bar.configure(width=progress_width)
        progress_bar.geometry(f"+{0}+{root.winfo_screenheight() - height}")  # Adjust for bottom spacing

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

def blind_round_coming_up():
    if blind_round_toggle:
        toggle_coming_up_popup(True, "Blind Round", "Guess the anime from just the music.\nNormal rules apply.")
    else:
        toggle_coming_up_popup(False)

# =========================================
#              *CENSOR BOXES
# =========================================

censor_list = {}
censors_enabled = True
censor_bar = None
def create_censor_bar():
    global censor_bar
    censor_bar = tk.Toplevel()
    censor_bar.configure(bg="black")
    censor_bar.geometry("5000x2500")
    censor_bar.overrideredirect(True)
    censor_bar.lower()

def load_censors():
    global censor_list
    censor_map = {}
    lines = -1

    if os.path.exists(CENSOR_FILE):
        try:
            with open(CENSOR_FILE, "r") as file:
                for line in file:
                    lines += 1
                    parts = [p.strip() for p in line.strip().split(",")]

                    if parts[0] != "filename":  # Skip header
                        filename = parts[0]
                        size = parts[1] if len(parts) > 1 else "0x0"
                        pos = parts[2] if len(parts) > 2 else "0x0"
                        start = float(parts[3]) if len(parts) > 3 else 0.0
                        end = float(parts[4]) if len(parts) > 4 else 0.0
                        color = parts[5] if len(parts) > 5 and parts[5] != "" else None
                        nsfw = parts[6] if len(parts) > 6 and parts[6] != "" else False

                        if censor_map.get(filename) is None:
                            censor_map[filename] = []
                        
                        censor_map[filename].append({
                            "size_w": float(size.split("x")[0]),
                            "size_h": float(size.split("x")[1]),
                            "pos_x": float(pos.split("x")[0]),
                            "pos_y": float(pos.split("x")[1]),
                            "start": start,
                            "end": end,
                            "color": color,  # Optional field stored if needed
                            "nsfw": nsfw  # Optional field stored if needed
                        })
        except FileNotFoundError:
            print("Error: " + filename + " not found.")
        
        print(f"Loaded {lines} censors for {len(censor_map)} files...")
        censor_list = censor_map

        if currently_playing and currently_playing.get("filename"):
            update_censor_button_count()
load_censors()

censor_used = False
def apply_censors(time, length):
    """"Apply Censors"""
    global censor_used
    global censor_list
    global censors_enabled
    if censor_bar is None:
        create_censor_bar()
    screen_width = censor_bar.winfo_screenwidth()
    screen_height = censor_bar.winfo_screenheight()
    if censors_enabled and not blind_enabled:
        if check_file_censors(currently_playing.get('filename'), time, False):
            return
        elif length - time <= 1 and current_index+1 < len(playlist) and check_file_censors(os.path.basename(playlist[current_index+1]), time, True):
            return
    if censor_used:
        censor_bar.attributes("-topmost", False)
        censor_bar.lower()
        censor_bar.geometry(str(screen_width) + "x" + str(screen_height))
        censor_bar.configure(bg="Black")
        censor_bar.geometry(f"+0+0")
        if not disable_shortcuts and not root.attributes("-topmost"):
            root.lower()
        censor_used = False

def check_file_censors(filename, time, video_end):
    global censor_used
    screen_width = censor_bar.winfo_screenwidth()
    screen_height = censor_bar.winfo_screenheight()
    file_censors = censor_list.get(filename)
    if file_censors != None:
        for censor in file_censors:
            if (not is_title_window_up() or censor.get("nsfw")) and ((video_end and censor['start'] == 0) or (time >= censor['start'] and time <= censor['end'])):
                if not censor_used:
                    censor_used = True
                    censor_bar.attributes("-topmost", True)
                    if root.attributes("-topmost"):
                        root.lift()
                    if title_window:
                        title_window.lift()
                    if progress_bar:
                        progress_bar.lift()
                    if coming_up_window:
                        coming_up_window.lift()
                censor_bar.geometry(str(int(screen_width*(censor['size_w']/100))) + "x" + str(int(screen_height*(censor['size_h']/100))))
                censor_bar.configure(bg=(censor.get("color") or get_image_color()))
                set_window_position(censor_bar, censor['pos_x'], censor['pos_y'])
                return True
    return False

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

camera = dxcam.create() 
camera.start(target_fps=30) # threaded

def get_image_color():
    img = camera.get_latest_frame() # Will block until new frame available
    im_arr = np.array(img)
    l = im_arr.shape[0]*im_arr.shape[1]
    r,g,b = im_arr[:,:,0].sum()/l , im_arr[:,:,1].sum()/l , im_arr[:,:,2].sum()/l
    average_color = rgbtohex(int(r), int(g), int(b))
    return average_color

def rgbtohex(r,g,b):
    return f'#{r:02x}{g:02x}{b:02x}'

def update_censor_button_count():
    toggle_censor_bar_button.configure(text="[C]ENSOR(" + str(len(censor_list.get(currently_playing.get("filename",""), {}))) +")")
    
# =========================================
#            *TAG/FAVORITE FILES
# =========================================

def toggle_theme(playlist_name, button, filename=None):
    if not filename:
        filename = currently_playing.get("filename")
    """Toggles a theme in a specified playlist (e.g., Tagged Themes, Favorite Themes)."""
    playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")

    # Load or initialize the playlist
    if os.path.exists(playlist_path):
        with open(playlist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            theme_list = data.get("playlist", [])
    else:
        data = {"name": playlist_name, "current_index": 0, "playlist": []}
        theme_list = data["playlist"]

    if filename in theme_list:
        # Remove theme
        theme_list.remove(filename)
        button_seleted(button, False)
    else:
        # Add theme
        theme_list.append(filename)
        button_seleted(button, True)

    # Save the updated playlist
    data["playlist"] = theme_list

    if not os.path.exists(PLAYLISTS_FOLDER):
        os.makedirs(PLAYLISTS_FOLDER)

    with open(playlist_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        print(f"{filename} saved to playlist '{playlist_name}'.")

def check_theme(filename, playlist_name):
    """Checks if a theme exists in a specified playlist (e.g., Tagged Themes, Favorite Themes)."""
    playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")
    if os.path.exists(playlist_path):
        with open(playlist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return filename in data.get("playlist", [])
    return False

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

def check_missing_artists():
    playlist_name = "Missing Artists"
    try:
        os.remove(os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json"))
    except Exception as e:
        print(e)
        pass
    for filename in directory_files:
        data = get_metadata(filename)
        for theme in data.get("songs",[]):
            if theme.get("slug") == data.get("slug") and theme.get("artist") == []:
                toggle_theme(playlist_name, favorite_button, filename)

# =========================================
#               *DOCK PLAYER
# =========================================

undock_position = []
def dock_player():
    """Toggles the Tkinter window between front and back, moves it to bottom left,
    adjusts transparency, and removes the title bar when brought forward."""
    global undock_position
    current_state = root.attributes("-topmost")
    button_seleted(dock_button, not current_state)
    if current_state:
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
        undock_position = (root.winfo_x(), root.winfo_y())
        # root.overrideredirect(True)  # Remove title bar
        root.attributes("-alpha", 0.8)  # Set transparency to 80%
        root.attributes("-topmost", True)
        move_root_to_bottom()
        root.lift()

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
    last_themes_listed = field_list
    selected = -1
    for index, filename in enumerate(field_list):
        if filename == currently_playing.get('filename'):
            selected = index
            break
    show_list("field_list", right_column, convert_playlist_to_dict(field_list), get_title, play_video_from_last, selected, update)

def get_title(key, value):
    data = get_metadata(value)
    if data:
        title = (data.get("eng_title") or data.get("title"))
        if len(title) > 37:
            title = title[:35] + "..."
        return title + " " + data.get("slug")
    else:
        return value

def play_video_from_last(index):
    if last_themes_listed:
        play_video_from_filename(last_themes_listed[index])

def show_playlist(update = False):
    show_list("playlist", right_column, convert_playlist_to_dict(playlist), get_title, play_video, current_index, update)

def remove(update = False):
    show_list("remove", right_column, convert_playlist_to_dict(playlist), get_title, remove_theme, current_index, update)

def convert_playlist_to_dict(playlist):
    return {f"{video}_{i}": video for i, video in enumerate(playlist)}

def remove_theme(index):
    global playlist
    confirm = messagebox.askyesno("Remove Theme", f"Are you sure you want to remove '{playlist[index]}' from '{playlist_name}'?")
    if not confirm:
        return  # User canceled
    del playlist[index]
    remove(True)

def get_filename(key, value):
    return value

def show_youtube_playlist(update = False):
    for index, (key, value) in enumerate(youtube_metadata.items()):
        value['index'] = index
    if youtube_queue:
        selected = youtube_queue.get('index')
    else:
        selected = -1
    show_list("youtube", right_column, youtube_metadata, get_youtube_title, load_youtube_video, selected, update)

def get_youtube_title(key, value):
    return value.get('title')

def button_seleted(button, selected):
    if selected:
        button.configure(bg=HIGHLIGHT_COLOR, fg="white")
    else:
        button.configure(bg="black", fg="white")

list_loaded = None
list_index = 0
list_func = None
def list_set_loaded(type):
    global list_loaded
    list_loaded = type
    for button in list_buttons:
        button_seleted(button.get('button'), list_loaded == button.get('label'))

def list_unload(column):
    list_set_loaded(None)
    column.config(state=tk.NORMAL, wrap="word")
    column.delete(1.0, tk.END)
    column.config(state=tk.DISABLED, wrap="word")


def list_move(amount):
    global list_index
    if list_loaded != None:
        list_index = list_index + amount
        for button in list_buttons:
            if list_loaded == button.get('label'):
                button.get('func')(True)
    else:
        left_column.yview_scroll(amount, "units")
        middle_column.yview_scroll(amount, "units")
        right_column.yview_scroll(amount, "units")

def list_select():
    if list_loaded:
        list_func(list_index)

def show_list(type, column, content, name_func, btn_func, selected, update = True):
    global list_loaded, list_index, list_func
    list_size = len(content)
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
    elif list_index >= list_size:
        list_index = 0
    elif list_index < 0:
        list_index = list_size - 1
    column.config(state=tk.NORMAL, wrap="none")
    column.delete(1.0, tk.END)  # Clear existing content
    
    scrolled = False
    for index, (key, value) in enumerate(content.items()):
        name = str(index+1) + ": " + name_func(key, value)
        if list_size < 50 or disable_shortcuts:
            # Create button for the video
            btn = tk.Button(column, text="▶", borderwidth=0, pady=0, command=lambda idx=index: btn_func(idx), bg="black", fg="white")
            column.window_create(tk.END, window=btn)
        if index == selected:
            if index == list_index:
                column.insert(tk.END, name, "highlight")
            else:
                column.insert(tk.END, name, "bold")
        else:
            if index == list_index:
                column.insert(tk.END, name, "highlightreg")
            else:
                column.insert(tk.END, name, "white")
        if list_size > 19 and not scrolled and (index == list_index+15 or index == (list_size-1)):
            scrolled = True
            column.see("end-1c")
        column.insert(tk.END, "\n")  # Ensure next item appears on a new line

    column.config(state=tk.DISABLED)

def list_keyboard_shortcuts():
    right_column.config(state=tk.NORMAL, wrap="none")
    right_column.delete(1.0, tk.END)
    add_single_line(right_column, "SHOW KEYBOARD SHORTCUTS", "[K]")
    add_single_line(right_column, "TOGGLE KEYBOARD SHORTCUTS", "[']")
    add_single_line(right_column, "TOGGLE INFORMATION POP-UP", "[I]")
    add_single_line(right_column, "DOCK/UNDOCK PLAYER", "[D]")
    add_single_line(right_column, "PLAY/PAUSE", "[SPACE BAR]", False)
    add_single_line(right_column, "STOP", "[ESC]")
    add_single_line(right_column, "PREVIOUS/NEXT", "[⬅]/[➡]", False)
    add_single_line(right_column, "FULLSCREEN", "[TAB]")
    add_single_line(right_column, "SEEK TO PART", "[0]-[9]", False)
    add_single_line(right_column, "REWIND/FORWARD", "[-]/[+]")
    add_single_line(right_column, "MUTE VIDEO", "[M]", False)
    add_single_line(right_column, "SCROLL UP/DOWN", "[⬆]/[⬇]")
    add_single_line(right_column, "TAG THEME", "[T]", False)
    add_single_line(right_column, "FAVORITE THEME", "[*]")
    add_single_line(right_column, "REFETCH METADATA", "[R]")
    add_single_line(right_column, "SHOW PLAYLIST", "[P]", False)
    add_single_line(right_column, "LOAD PLAYLIST", "[O]")
    add_single_line(right_column, "LIST UP/DOWN", "[⬆]/[⬇]", False)
    add_single_line(right_column, "LIST SELECT", "[ENTER]")
    add_single_line(right_column, "SEARCH/QUEUE", "[S]", False)
    add_single_line(right_column, "CANCEL SEARCH", "[ESC]")
    add_single_line(right_column, "GUESS YEAR", "[G]", False)
    add_single_line(right_column, "MEMBERS", "[H]", False)
    add_single_line(right_column, "SCORE", "[J]")
    add_single_line(right_column, "BLIND ROUND", "[B]", False)
    add_single_line(right_column, "TOGGLE BLIND", "[BACKSPACE]")
    add_single_line(right_column, "SHOW YOUTUBE PLAYLIST", "[Y]")
    add_single_line(right_column, "START/END LIGHTNING ROUND", "[L]")
    add_single_line(right_column, "FRAME", "[F]", False)
    add_single_line(right_column, "BLIND", "[N]", False)
    add_single_line(right_column, "CLUES", "[U]", False)
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
        load_censors()
        
def toggle_progress_bar():
    global progress_bar_enabled
    progress_bar_enabled = not progress_bar_enabled
    print("Progress Bar Enabled: " + str(progress_bar_enabled))
    apply_censors(player.get_time()/1000, player.get_length()/1000)
    button_seleted(toggle_progress_bar_button, progress_bar_enabled)
    update_progress_bar(player.get_time(), player.get_length())

disable_video_audio = False
def toggle_mute():
    global disable_video_audio
    disable_video_audio = not disable_video_audio
    player.audio_set_mute(disable_video_audio)
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

end_message_window = None

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
        end_message_window.configure(bg="black")

        total_played = len(all_themes_played)
        opening_count = 0
        ending_count = 0
        artist_counter = Counter()

        for filename in all_themes_played:
            data = get_metadata(filename)
            slug = filename.split("-")[1].split(".")[0].split("v")[0]
            matching_song = next((song for song in data.get("songs", []) if song.get("slug") == slug), None)

            if matching_song:
                theme_type = matching_song.get("type", "")
                if "OP" in theme_type:
                    opening_count += 1
                elif "ED" in theme_type:
                    ending_count += 1

        stats_text = (
            "THANKS FOR\nPLAYING!🤍\n\n"
            f"{total_played} THEMES\nPLAYED\n"
            f"{opening_count} OPENINGS\n{ending_count} ENDINGS"
        )

        label = tk.Label(end_message_window, text=stats_text, font=("Arial", 90, "bold"),
                         fg="white", bg="black", justify="right", anchor="e")
        label.pack(padx=20, pady=20)

        screen_width = end_message_window.winfo_screenwidth()
        screen_height = end_message_window.winfo_screenheight()
        window_width = label.winfo_reqwidth()
        start_x = screen_width - window_width - 50
        start_y = screen_height
        end_x = screen_width - window_width - 50
        end_y = 10

        root.update_idletasks()
        end_message_window.geometry(f"+{start_x}+{start_y}")
        root.update_idletasks()
        root.after(1, lambda: animate_window(end_message_window, end_x, end_y, delay=5, steps=2000, fade=None))
    except AttributeError:
        pass


    except AttributeError:
        pass

def on_closing():
    pass

# =========================================
#                 *GUI SETUP
# =========================================

BACKGROUND_COLOR = "gray12"
WINDOW_TITLE = "Guess the Anime! Playlist Tool"
root = tk.Tk()
root.title(WINDOW_TITLE)
root.geometry("1200x550")
root.configure(bg=BACKGROUND_COLOR)  # Set background color to black

def blank_space(row, size=1):
    space_label = tk.Label(row, text="", bg=BACKGROUND_COLOR, fg="white")
    space_label.pack(side="left", padx=size)

def create_button(frame, label, func, add_space=False, enabled=False, help_title="", help_text=""):
    """Creates a button with optional spacing and right-click help functionality."""
    bg = HIGHLIGHT_COLOR if enabled else "black"
    
    # Create the button
    button = tk.Button(frame, text=label, command=func, bg=bg, fg="white")
    button.pack(side="left")

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
first_row_frame.pack(pady=5)

dock_button = create_button(first_row_frame, "[D]OCK PLAYER", dock_player, True, 
                            help_title="[D]OCK PLAYER (Shortcut Key = 'd')",
                            help_text="Docks the player on the bottom of the screen and makes it semitransparent. " +
                            "Click again to undock.\n\nWhen shortcuts are enabled it will" + 
                            " hide it at the bottom of the screen. Otherwise it will return to its " + 
                            "previous position.\n\nIt can be useful if you need to share any "+
                            "information on the player, or use any buttons that don't have "+
                            "shortcuts. Also if you are just browsing.")

def select_directory():
    directory = filedialog.askdirectory()
    if directory:
        scan_directory(directory)

def scan_directory(directory = None):
    global directory_entry, directory_files
    if not directory:
        directory = directory_entry.get()
    directory_files = {}
    directory_entry.delete(0, tk.END)
    directory_entry.insert(0, directory)
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith((".mp4", ".webm", ".mkv")):
                directory_files[file] = os.path.join(root, file)
    save_config()

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

directory_entry = tk.Entry(first_row_frame, width=33, bg="black", fg="white", insertbackground="white")
directory_entry.pack(side="left")

# Generate playlist button
def generate_playlist_button():
    global playlist
    scan_directory()
    confirm = messagebox.askyesno("Create Playlist", f"Are you sure you want to create a new playlist with all {len(directory_files)} files in the directory?")
    if not confirm:
        return  # User canceled
    playlist = generate_playlist()
    update_current_index()
    update_playlist_name("")
    if playlist:
        save_config()
        show_playlist(True)
    else:
        messagebox.showwarning("Playlist Error", "No video files found in the directory.")

def empty_playlist():
    global playlist
    confirm = messagebox.askyesno("Clear Playlist", f"Are you sure you want to clear '{playlist_name}'?")
    if not confirm:
        return  # User canceled
    playlist = []
    show_playlist(True)

generate_button = create_button(first_row_frame, "CREATE", generate_playlist_button,
                              help_title="CREATE PLAYLIST",
                              help_text=("This created a playlist using all videos "
                              "found in the directory.\n\nIf this is your first time "
                              "creating a playlist with these files, and you want "
                              "to be able to use all the other playlist functions, "
                              "you'll need to fetch the metadata for all the files. "
                              "You can do this by hitting the '?' button next to the "
                              "[R]EFETCH button. It may take awhile "
                              "depending on how many themes you have.\n\n"
                              "You will be asked to confirm when creating."))

empty_button = create_button(first_row_frame, "❌", empty_playlist, True,
                              help_title="EMPTY PLAYLIST",
                              help_text=("This resets you to a blank playlist. "
                              "This is only if you want to manually add themes to the "
                              "playlist using the SEARCH+ button. That's not really what "
                              "this application was made for, so it may be a hassle "
                              "depending on how many themes you want to add to the list."))

show_playlist_button = create_button(first_row_frame, "[P]LAYLIST", show_playlist,
                              help_title="VIEW [P]LAYLIST (Shortcut Key = 'p')",
                              help_text=("List all themes in the playlist. It will scroll to whichever "
                              "theme the current index is at. Select a theme to play it immediately "
                              "and set the current index to it.\n\nAs with all lists, it loads buttons "
                              "to select the entry, but for the playlist it may be quite a few buttons. "
                              "It usually loads quickly, but may take a second to clear."))
remove_button = create_button(first_row_frame, "❌", remove, True,
                              help_title="REMOVE THEME",
                              help_text=("Remove a theme from the playlist. There is a confirmation "
                              "dialogue after selecting.\n\nIt may be a bit slow dpending on how many "
                              "themes you have added or want to delete."))

go_button = create_button(first_row_frame, "GO TO:", go_to_index,
                              help_title="GO TO INDEX",
                              help_text=("Go to the index in the text box of the playlist. "
                              "It will play it immediately and set the current index."))
current_entry = tk.Entry(first_row_frame, width=5, bg="black", fg="white", insertbackground="white", justify='center')
current_entry.pack(side="left")

playlist_size_label = tk.Label(first_row_frame, text="/" + str(len(playlist)), bg=BACKGROUND_COLOR, fg="white")
playlist_size_label.pack(side="left")

blank_space(first_row_frame)

save_button = create_button(first_row_frame, "SAVE", save, True,
                              help_title="SAVE PLAYLIST",
                              help_text=("Use this to save your current playlist. Playlists are stored as JSON files in the "
                              "playlists/ folder.\n\nCurrently loaded playlists are automatically saved in the config file, "
                              "but if you want to be able to create a new playlist and load this one back later you'll need to "
                              "save it.\n\nYou will be prompted to enter a name. If you enter the name of any existing playlist, "
                              "it will overwrite it without warning. If this playlist was already saved/loaded, the title will be prefilled."
                              "\n\nThe current index is also stored in the playlist, so you can load where you left off."))

load_button = create_button(first_row_frame, "L[O]AD", load,
                              help_title="L[O]AD PLAYLIST (Shortcut Key = 'o')",
                              help_text=("Load a playlist from your list of saved playlists.\n\n"
                              "This will not interrupt the currently playing theme, but will load the playlist "
                              "and set the current index.\n\nPlaylists are stored in the playlists/ folder.\n\n"
                              "When shortcuts are enabled, the currently loaded playlist will auto save. This is "
                              "so I can load up another playlist, then go back while keeping the position. I don't "
                              "have a shortcut for saving, but if you were not using shortcuts you could just save manually "
                              "before loading a playlist if you want to."))
delete_button = create_button(first_row_frame, "❌", delete, True,
                              help_title="DELETE PLAYLIST",
                              help_text=("Delete a playlist from your list of saved playlists.\n\n"
                              "You will be asked to confirm when deleting."))

filter_button = create_button(first_row_frame, "FILTER", filters,
                              help_title="FILTER PLAYLIST",
                              help_text=("Open a window where you can create, apply, and save playlist filters.\n\n"
                              "The filter will apply to the currently selected playlist.\n\n"
                              "Saved filters are stored in the filters/ folder.\n\n" 
                              "The values are taken from the metadata files, so this will take awhile to grab all "
                              "the metadata if you haven't already.\n\nThe Artists, Studios, and Tags filter all "
                              "will grab any themes that match just one of the selected items if you select multiple. "
                              "If you only want themes that match multiple items, you can run the filter another time "
                              "after filtering to one."))
load_filters_button = create_button(first_row_frame, "💾", load_filters,
                              help_title="APPLY SAVED FILTER",
                              help_text=("Apply a filter from your list of saved filters. You can save filters in the FILTER "
                              "button. The filter will apply to the currently selected playlist."))
delete_filters_button = create_button(first_row_frame, "❌", delete_filters, True,
                              help_title="DELETE SAVED FILTER",
                              help_text=("Delete a filter from your list of saved filters.\n\n"
                              "You will be asked to confirm when deleting."))

sort_button = create_button(first_row_frame, "SORT", sort, True,
                              help_title="SORT PLAYLIST",
                              help_text=("Sorts the current playlist using one of the premade sorts.\n\n"
                              "I think I covered every type of sort someone would want, " + 
                              "but I could add more later if needed."))

randomize_playlist_button = create_button(first_row_frame, "SHUFFLE", randomize_playlist,
                              help_title="SHUFFLE PLAYLIST",
                              help_text=("Randomizes the current playlist.\n\n" +
                              "This is a completly random shuffle. For a weighted shuffle, hit the ⚖️ button "
                              "next to this one.\n\n" +
                              "You will be asked to confirm when shuffling"))
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

search_button = create_button(first_row_frame, "[S]EARCH", search,
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
add_search_button = create_button(first_row_frame, "➕", search_add, True,
                              help_title="SEARCH ADD",
                              help_text=("The same as the SEARCH, but will add the theme to the playlist "
                                         "instead of just queueing it.\n\nThis was more of an after thought feature "
                                         "just in case you want to add some themes that were maybe removed, or added "
                                         "later. It would be kinda slow with the dialogue popping up each time, but it "
                                         "may be fast with shortcuts enabled, as described on the SEARCH button. You could "
                                         "also use this to add tracks to an empty playlist to create your own from scratch."))

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
second_row_frame.pack(pady=5)

info_button = create_button(second_row_frame, "[I]NFO POPUP", toggle_info_popup,
                              help_title="SHOW/HIDE [I]NFO POPUP (Shortcut Key = 'i')",
                              help_text=("Show or hide the information popup at the bottom of the screen.\n\n"
                                         "This shows most of the information from the main player in a nicer format. "
                                         "During trivia, if someone gets the answer correct or people give up, "
                                         "this can be toggled to let them know the answer/more information.\n\n"
                                         "The popup will automatically close when the theme ends."))
start_info_button = create_button(second_row_frame, "⏪", toggle_auto_info_start,
                              help_title="TOGGLE AUTO INFO POPUP AT START",
                              help_text=("When enabled, will show the theme's info popup at the start.\n\n"
                                         "Useful if you aren't doing trivia, and just want th info displayed as you watch."))
end_info_button = create_button(second_row_frame, "⏩", toggle_auto_info_end, True,
                              help_title="TOGGLE AUTO INFO POPUP AT END",
                              help_text=("When enabled, will show the theme's info popup during the last 8 seconds.\n\n"
                                         "Useful if you want to go more hands off with the trivia, and just show the answer at the end."))

tag_button = create_button(second_row_frame, "[T]AG", tag, False,
                              help_title="[T]AG THEME (Shortcut Key = 't')",
                              help_text=("Adds the current;y playing theme to a 'Tagged Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nThe purpose is to tag "
                                         "themes you may need to check out later for various reasons. "
                                         "Like adding censors, updating the theme, or even deleting it. "
                                         "Just a reminder."))
favorite_button = create_button(second_row_frame, "❤️", favorite, True,
                              help_title="FAVORITE THEME (Shortcut Key='*')",
                              help_text=("Adds the current;y playing theme to a 'Favorite Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nJust a way to keep track of your favorite themes."))

refetch_metadata_button = create_button(second_row_frame, "[R]EFETCH", refetch_metadata,
                              help_title="[R]EFETCH THEME METADATA (Shortcut Key = 'r')",
                              help_text=("Refetch the metadata for the currently playing theme.\n\n"
                                         "You may want to do this if there's mising information that "
                                         "may have been filled by now, or you want to update the score/ "
                                         "members stats. For that purpose though, you can enable auto refresh "
                                         "of jikan metadata by hitting the ♻ button."))
fetch_missing_metadata_button = create_button(second_row_frame, "❓", fetch_all_metadata,
                              help_title="FETCH ALL MISSING METADATA",
                              help_text=("Use this to check if metadata exists for all files in the chosen "
                                         "directory, and fetch metadata for any that are missing. You should do "
                                         "this whenever you have new videos in the directory.\n\n"
                                         "It can take quite awhile depending on how many themes you have. "
                                         "It may need to be left overnight if you have thousands."))
refresh_all_metadata_button = create_button(second_row_frame, "⭮", refresh_all_metadata, False,
                              help_title="REFRESH ALL JIKAN METADATA",
                              help_text=("Refreshes the jikan metadata for all files in the directory. "
                                         "You may want to do this if you feel the score and members data are outdated, "
                                         "although you could also use the ♻ button to toggle auto refreshing the data "
                                         "as files are playing if you don't want to have it call for all the files at once."))
toggle_refresh_metadata_button = create_button(second_row_frame, "♻", toggle_auto_auto_refresh, True,
                              help_title="TOGGLE AUTO REFRESH JIKAN METADATA",
                              help_text=("Toggle auto refreshing jikan metadata. This will refresh the "
                                         "jikan metadata for the currently playing theme, and the next "
                                         "theme as you play them, It will never refresh the same anime in the same session."
                                         "\n\nThis if for the score and members data, which changes "
                                         "over time. It's not too nessessary if you don't care about it being up "
                                         "to date, or if you've already grabbed the metadata recently.\n\n"
                                         "It doesn't refetch everything, or call the AnimeThemes API like "
                                         "the regular [R]EFETCH does for the current theme. If you "
                                         "want to to do that for all files, you would need to delete the "
                                         "anime_metadata.json file in the metadata/ folder, and fetch "
                                         "all missing metadata again, but I wouldn't recommend that."))

blind_button = create_button(second_row_frame, "BLIND", lambda: blind(True),
                              help_title="BLIND (Shortcut Key = 'backspace')",
                              help_text=("Covers the screen. Will be a color matching the average color of the screen. "
                                         "If a video is playing, it will display a progress bar."))
blind_round_button = create_button(second_row_frame, "👁", toggle_blind_round, True,
                              help_title="[B]LIND ROUND (Shortcut Key = 'b')",
                              help_text=("Enables the next video to play as a 'Blind Round'. A blind round plays normally, "
                                         "but will cover the screen at the start to make it audio only. This is only lasts "
                                         "for one video, and the blind can be removed with the normal BLIND toggle."))

guess_year_button = create_button(second_row_frame, "📅", lambda: guess_extra("year"), False,
                              help_title="[G]UESS YEAR (Shortcut Key = 'g')",
                              help_text=("Displays a pop-up at the top informing players to guess the year. "
                                         "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_members_button = create_button(second_row_frame, "👥", lambda: guess_extra("members"), False,
                              help_title="GUESS MEMBERS([H]EADCOUNT) (Shortcut Key = 'h')",
                              help_text=("Displays a pop-up at the top informing players to guess the members. "
                                         "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_score_button = create_button(second_row_frame, "🏆", lambda: guess_extra("score"), False,
                              help_title="GUESS SCORE([J]UDGE) (Shortcut Key = 'j')",
                              help_text=("Displays a pop-up at the top informing players to guess the score. "
                                         "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_tags_button = create_button(second_row_frame, "🔖", lambda: guess_extra("tags"), True,
                              help_title="[G]UESS TAGS (Shortcut Key = 'g','g')",
                              help_text=("Displays a pop-up at the top informing players to guess the tags. "
                                         "It also lists the rules. Opening the Info Popup or toggling again will remove it."))

regular_light_mode_button = create_button(second_row_frame, "🗲", lambda: toggle_light_mode("regular"),
                              help_title="[L]IGHTNING ROUND (Shortcut Key = 'l')",
                              help_text=("Start/End the Lightning Round mode. This mode uses the same playlist as "
                                         "normal, but uses the following rules:\n\n" + light_modes["regular"]["desc"] +
                                         "\n\nThe round will queue up with a UP NEXT popup and start after the current theme "
                                         "finishes.\n\nNumber of rounds are tracked and you can go on as long as you like "
                                         "until ended.\n\nLightning Rounds also avoid any censors you may have added."))
title_light_mode_button = create_button(second_row_frame, "🧩", lambda: toggle_light_mode("title"),
                              help_title="TIT[L]E [L]IGHTNING ROUND (Shortcut Key = 'l', 'l')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["title"]["desc"] +
                                         "\n\nOnly alphanumeric characters are hidden, and case doesn't matter."
                                         "\n\nThe music is the same from the Frame Lightning Round. "
                                         "You can check that help section for more details."))
frame_light_mode_button = create_button(second_row_frame, "📷", lambda: toggle_light_mode("frame"),
                              help_title="[F]RAME LIGHTNING ROUND (Shortcut Key = 'f')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["frame"]["desc"] +
                                         "\n\nFrames are picked randomly from each quarter of the theme. Results can vary "
                                         "in difficulty because of that, but it can still be an entertaining mode. "
                                         "Music will play while the frames are displaying if you put it in the music/ folder. "
                                         "I recommend something low energy, since if you use something too intense "
                                         "it's kinda grating with the constant music switching. "
                                         "I recommend the following tracks:\n\n"
                                         "Fullmetal Alchemist Brotherhood OST - Interlude\n"
                                         "Houseki no Kuni OST - Early Afternoon\n"
                                         "Katanagatari OST - 12 DUB TRIP"))
blind_light_mode_button = create_button(second_row_frame, "👁", lambda: toggle_light_mode("blind"),
                              help_title="BLI[N]D LIGHTNING ROUND (Shortcut Key = 'n')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["blind"]["desc"] +
                                         "\n\nThis mode doesn't avoid censors, since nothing is shown. Identifying from music "
                                         "only may be hard if you're not an expert or using popular shows. It may be recommended to "
                                         "use a filtered playlist based on popularity depending on the crowd."))
song_light_mode_button = create_button(second_row_frame, "🎵", lambda: toggle_light_mode("song"),
                              help_title="SONG LIGHTNING ROUND (Shortcut Key = 'b', 'b')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["song"]["desc"] +
                                         "\n\nThis mode is pretty difficult unless you are quite knowledgable. Probably not recommended "
                                         "on its own unless using a pretty curated playlist.\n\nThe music is the same from the Frame Lightning Round. "
                                         "You can check that help section for more details."))
clues_light_mode_button = create_button(second_row_frame, "🔍", lambda: toggle_light_mode("clues"),
                              help_title="CL[U]ES LIGHTNING ROUND (Shortcut Key = 'u')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["clues"]["desc"] +
                                         "\n\nThis mode is pretty difficult unless you are quite knowledgable. Probably not recommended "
                                         "on its own unless using a pretty curated playlist.\n\nThe music is the same from the Frame Lightning Round. "
                                         "You can check that help section for more details."))
synopsis_light_mode_button = create_button(second_row_frame, "📰", lambda: toggle_light_mode("synopsis"),
                              help_title="SYNOPSIS LIGHTNING ROUND (Shortcut Key = 'u', 'u')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["synopsis"]["desc"] +
                                         "\n\nWords from the title of the show are blanked out in the synopsis."
                                         "\n\nThe music is the same from the Frame Lightning Round. "
                                         "You can check that help section for more details."))
variety_light_mode_button = create_button(second_row_frame, "🎲", lambda: toggle_light_mode("variety"), True,
                              help_title="[V]ARIETY LIGHTNING ROUND (Shortcut Key = 'v')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["variety"]["desc"] +
                                         "\n\nThis mode ensures no round is repeated consecutively, and picks rounds "
                                         "taking the shows popularity into account. So you aren't likely to get a Clues round "
                                         "unless a quite popular show appears."))

show_youtube_playlist_button = create_button(second_row_frame, "[Y]OUTUBE", show_youtube_playlist, True,
                              help_title="[Y]OUTUBE VIDEOS (Shortcut Key = 'y')",
                              help_text=("Lists downloaded youtube videos to queue up.\n\nVideos are downloaded on startup "
                                         "based on the youtube_links.txt file in the files/ folder. The downloads are stored in the "
                                         "youtube/ folder and deleted when removed from the youtube_links.txt file. All videos are "
                                         "also listed in the youtube_archive.txt file just to keep track of videos downloaded.\n\n"
                                         "Videos are queued with a UP NEXT popup when selected, and will play after the current theme. "
                                         "Only one video may be queued at a time, and selecting the same video will unqueue it."))

toggle_censor_bar_button = create_button(second_row_frame, "[C]ENSOR(0)", toggle_censor_bar, True, enabled=censors_enabled,
                              help_title="TOGGLE [C]ENSOR BARS (Shortcut Key = 'c')",
                              help_text=("Toggle censor bars. These are pulled from the censors.txt file in the files/ "
                                         "folder. These have to be manually added by adding lines to the censors.txt file.\n\n"
                                         "The format is shown in the file, and the censor_bar_tool.py in the same folder "
                                         "can be used to quickly create boxes of different sizes and positions. It copies the "
                                         "value to the clipboard so you can just paste it into the censors.txt file.\n\n"
                                         "The point of this feature is to mainly block out titles that show up too early, "
                                         "since this is a trivia program. They always assume the video is fullscreen, on "
                                         "the main monitor, so it will be weird if you try playing in a window. I would have disabled them "
                                         "when vlc isn't fulscreen, but checking that isn't reliable."))

toggle_progress_bar_button = create_button(second_row_frame, "BAR", toggle_progress_bar, True, enabled=progress_bar_enabled,
                              help_title="TOGGLE PROGRESS BAR OVERLAY",
                              help_text=("This toggles a progress bar overlay for the current time for the theme.\n\n"
                                         "It's pretty thin, and meant to be subtle as to not obstruct the theme."))

mute_button = create_button(second_row_frame, "[M]UTE", toggle_mute, True,
                              help_title="[M]UTE THEME AUDIO (Shortcut Key = 'm')",
                              help_text=("Toggles muting the video audio."))

stats_button = create_button(second_row_frame, "📊", display_theme_stats_in_columns, True,
                              help_title="THEME STATS",
                              help_text=("Shows detailed stats of themes in directory."))

toggle_disable_shortcuts_button = create_button(second_row_frame, "[`]ENABLE", toggle_disable_shortcuts,
                              help_title="ENABLE SHORTCUTS (Shortcut Key = '`')",
                              help_text=("Used to toggle shortcut keys.\n\nIn my current setup, I am streaming my desktop to "
                                         "one screen, and do not have access to a second monitor to manage the "
                                         "application. I stream the applicaiton window to another display, but I can't interact with it. "
                                         "So I've mapped all the functions I may want to use during a session to shortcut keys. "
                                         "It may be hard to track them all, but most buttons have the shortcut key on them.\n\n"
                                         "For a full reference, use the SHORTCUT [K]EYS button.\n\nAlso when this is enabled, "
                                         "lists greater than 50 items no longer have buttons. The buttons slow down things a bit, and since they "
                                         "aren't needed if I'm using shortcuts, I disabled them."))

list_keyboard_shortcuts_button = create_button(second_row_frame, "[K]EYS", list_keyboard_shortcuts, True,
                              help_title="LIST SHORTCUT [K]EYS (Shortcut Key = 'k')",
                              help_text=("Lists all shortcut keys on the application.\n\nAlthough all are listed in uppercase for clarity "
                                         "it only accepts inputs in lowercase.\n\nThe scoreboard stuff at the "
                                         "bottom is actually a separate application that pulls scores from a google "
                                         "sheet I update during the session, and can be ignored. The scoreboard is pretty specific to "
                                         "the format of my google sheet. I could probably share it though if anyone asked.\n\n"
                                         "The up/down arrows have two functions. When a list is up, they control which you are "
                                         "highlighting to select. Otherwise, they scroll all the columns up/down."))

end_button = create_button(second_row_frame, "[E]ND", end_session,
                              help_title="[E]ND SESSION MESSAGE (Shortcut Key = 'e')",
                              help_text="Diplays an end message 'THANKS FOR PLAYING!' slowly scrolling "
                              "up the right side of the screen. Just a nice way for me to end my trivia sessions.\n\n"
                              "It also lists the 'TOTAL THEMED PLAYED:', which are tracked while the application is running.")

# Info Panel (Three Columns)
info_panel = tk.Frame(root, bg="black")
info_panel.pack(fill="both", expand=True, padx=10, pady=5)

# Left Column: Filename, Title, English Title, and Large Image
left_column = tk.Text(info_panel, height=20, width=40, bg="black", fg="white", insertbackground="white", state=tk.DISABLED, selectbackground=HIGHLIGHT_COLOR, wrap="word")
left_column.pack(side="left", fill="both", expand=True)

# Middle Column: Synopsis, Season Aired, Members, and Score
middle_column = tk.Text(info_panel, height=20, width=40, bg="black", fg="white", insertbackground="white", state=tk.DISABLED, selectbackground=HIGHLIGHT_COLOR, wrap="word")
middle_column.pack(side="left", fill="both", expand=True)

# Right Column: List of OP/EDs
right_column = tk.Text(info_panel, height=20, width=40, bg="black", fg="white", insertbackground="white", state=tk.DISABLED, selectbackground=HIGHLIGHT_COLOR, wrap="word")
right_column.pack(side="left", fill="both", expand=True)

# Video controls
controls_frame = tk.Frame(root, bg="black")
controls_frame.pack(pady=0)

# Volume Control
volume_level = 100
def set_volume(value):
    """Sets the volume based on slider input (0 to 100)."""
    global volume_level
    volume_level = int(value)
    player.audio_set_volume(volume_level)  # Adjust VLC volume
    if music_loaded:
        pygame.mixer.music.set_volume(0.2*(volume_level/100))  # Adjust volume

volume_slider = tk.Scale(controls_frame, from_=200, to=0, orient=tk.VERTICAL, command=set_volume, label="🔊", length=50, bg="black", fg="white", border=0, font=("Arial", 12, "bold"))
volume_slider.set(100)  # Default volume at 50%
volume_slider.pack(side="left", padx=(10))

play_pause_button = tk.Button(controls_frame, text="⏯", command=play_pause, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
play_pause_button.pack(side="left", padx=5)

stop_button = tk.Button(controls_frame, text="⏹", command=stop, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
stop_button.pack(side="left", padx=5)

previous_button = tk.Button(controls_frame, text="⏮", command=play_previous, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
previous_button.pack(side="left", padx=5)

next_button = tk.Button(controls_frame, text="⏭", command=play_next, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
next_button.pack(side="left", padx=5)

# Seek bar
seek_bar = tk.Scale(controls_frame, from_=0, to=1000, orient=tk.HORIZONTAL, command=seek, length=2000, resolution=0.1, bg="black", fg="white")
seek_bar.pack(side="left", fill="x", padx=10)


# Text formatting tags
left_column.tag_configure("bold", font=("Arial", 12, "bold"), foreground="white")
left_column.tag_configure("underline", underline=True)
middle_column.tag_configure("bold", font=("Arial", 12, "bold"), foreground="white")
middle_column.tag_configure("highlight", background="#333333", foreground="white", font=("Arial", 12, "bold"))  # Dark gray highlight
middle_column.tag_configure("underline", underline=True)
right_column.tag_configure("bold", font=("Arial", 12, "bold"), foreground="white")
right_column.tag_configure("highlight", background=HIGHLIGHT_COLOR, foreground="white", font=("Arial", 12, "bold"))  # Dark gray highlight
right_column.tag_configure("highlightreg", background=HIGHLIGHT_COLOR, foreground="white", font=("Arial", 12))  # Dark gray highlight
right_column.tag_configure("underline", underline=True)
left_column.tag_configure("white", foreground="white", font=("Arial", 12))
left_column.tag_configure("blank", foreground="white", font=("Arial", 6))
middle_column.tag_configure("white", foreground="white", font=("Arial", 12))
middle_column.tag_configure("blank", foreground="white", font=("Arial", 6))
right_column.tag_configure("white", foreground="white", font=("Arial", 12))
right_column.tag_configure("blank", foreground="white", font=("Arial", 6))

list_buttons = [
    {"button":show_playlist_button, "label":"playlist", "func":show_playlist},
    {"button":show_playlist_button, "label":"field_list", "func":show_field_themes},
    {"button":remove_button, "label":"remove", "func":remove_theme},
    {"button":load_button, "label":"load_playlist", "func":load},
    {"button":delete_button, "label":"delete_playlist", "func":delete},
    {"button":load_filters_button, "label":"load_filters", "func":load_filter},
    {"button":delete_filters_button, "label":"delete_filters", "func":delete_filter},
    {"button":sort_button, "label":"sort", "func":sort},
    {"button":search_button, "label":"search", "func":search},
    {"button":add_search_button, "label":"search_add", "func":search_add},
    {"button":show_youtube_playlist_button, "label":"youtube", "func":show_youtube_playlist}
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
        elif key == key.up:
            list_move(-1)
        elif key == key.down:
            list_move(1)
    except AttributeError:
        try:
            if list_loaded == "search":
                pass
            elif key.char == '-' or key.char == '_':
                player.set_time(player.get_time()-1000)
            elif key.char == '=' or key.char == '+':
                player.set_time(player.get_time()+1000)
        except AttributeError as e:
            print(f"Error: {e}")

def on_release(key):
    global disable_shortcuts
    if disable_shortcuts:
        try:
            if key.char == '`':
                toggle_disable_shortcuts()
        except:
            pass
    elif list_loaded == "search":
        global search_term
        try:
            if key == key.esc:
                search()
            elif key == key.backspace:
                if search_term != "":
                    search_term = search_term[:-1]
                search(True)
            elif key == key.space:
                search_term = search_term + " "
                search(True)
            elif key == key.enter:
                list_select()
        except AttributeError:
            search_term = search_term + key.char
            search(True)
    else:    
        try:
            if key == key.right:
                play_next()
            elif key == key.space:
                play_pause()
            elif key == key.left:
                play_previous()
            elif key == key.esc:
                stop()
            elif key == key.tab:
                player.toggle_fullscreen()
            elif key == key.backspace:
                blind(True)
            elif key == key.enter:
                list_select()
        except AttributeError:
            try:
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
                    if list_loaded:
                        global list_index
                        list_index = int(key.char)-1
                        list_select()
                    else:
                        seek_value = player.get_length()-((player.get_length()/10)*(10-int(key.char)))
                        player.set_time(int(seek_value))
                elif key.char == 'r':
                    refetch_metadata()
                elif key.char == 'c':
                    toggle_censor_bar()
                elif key.char == 'k':
                    list_keyboard_shortcuts()
                elif key.char == 'l':
                    if not (light_mode == 'regular' or light_mode == 'title'):
                        toggle_light_mode("regular")
                    else:
                        toggle_light_mode("title")
                elif key.char == 'f':
                    toggle_light_mode("frame")
                elif key.char == 'n':
                    if not (light_mode == 'blind' or light_mode == 'song'):
                        toggle_light_mode("blind")
                    else:
                        toggle_light_mode("song")
                elif key.char == 'u':
                    if not (light_mode == 'clues' or light_mode == 'synopsis'):
                        toggle_light_mode("clues")
                    else:
                        toggle_light_mode("synopsis")
                elif key.char == 'b':
                    toggle_blind_round()
                elif key.char == 'v':
                    toggle_light_mode("variety")
                elif key.char == 'i':
                    toggle_info_popup()
                elif key.char == 'o':
                    load()
                elif key.char == 'e':
                    end_session()
                elif key.char == 's':
                    search()
                elif key.char == 'g':
                    if guessing_extra != "year" and guessing_extra != "tags":
                        guess_extra("year")
                    else:
                        guess_extra("tags")
                elif key.char == 'h':
                    guess_extra("members")
                elif key.char == 'j':
                    guess_extra("score")
            except AttributeError as e:
                print(f"Error: {e}")

# =========================================
#                *STARTUP
# =========================================

listener = keyboard.Listener(
    on_press=on_press,
    on_release=on_release)
listener.start()

# Load saved configuration on startup
load_config()
load_youtube_metadata()
load_metadata()
scan_directory()

# Start downloading videos in the background
download_thread = threading.Thread(target=download_videos, daemon=True)
download_thread.start()

# Start updating the seek bar
root.after(1000, update_seek_bar)
# Schedule a check for when the video ends
root.after(1000, check_video_end)

root.mainloop()