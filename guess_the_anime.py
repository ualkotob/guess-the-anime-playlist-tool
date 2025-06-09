# =========================================
#      GUESS THE ANIME - PLAYLIST TOOL
#             by Ramun Flame
# =========================================

import os
import sys
import shutil
import ctypes
import random
import math
import json
import requests
import xml.etree.ElementTree as ET
import re
import dxcam
import time
import copy
from collections import Counter
import numpy as np
from io import BytesIO
from datetime import datetime
import tkinter as tk
import tkinter.font as tkFont
from tkinter import filedialog, messagebox, simpledialog, ttk, StringVar
import webbrowser
from PIL import Image, ImageTk
import threading  # For asynchronous metadata loading
import vlc
import yt_dlp
from pynput import keyboard
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame
import pyperclip
import pyautogui

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

BLANK_PLAYLIST = {
    "name":"",
    "current_index":-1,
    "lightning_history": {},
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
anime_metadata_overrides = {}
ANIME_METADATA_OVERRIDES_FILE = "metadata/anime_metadata_overrides.json"
manual_metadata_file = "metadata/manual_metadata.json"
youtube_metadata = {}
YOUTUBE_METADATA_FILE = "metadata/youtube_metadata.json"
directory = ""
directory_files = {}
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

# =========================================
#         *FETCHING ANIME METADATA
# =========================================

# Function to fetch anime metadata using AnimeThemes.moe API
def fetch_animethemes_metadata(filename=None, mal_id=None):
    url = "https://api.animethemes.moe/anime"
    if filename:
        params = {
            "filter[has]": "animethemes.animethemeentries.videos",
            "filter[video][basename-like]": filename.split("-")[0] + "-%",
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
        if pic and char_type in ['a','s','m']:
            character = [char_type, name, os.path.basename(pic)]
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
        if not epno or not epno.isdigit() or (epno.isdigit() and int(epno) > 25):
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

fetched_metadata = []
def pre_fetch_metadata():
    for i in range(playlist["current_index"]-1, playlist["current_index"]+3):
        if i >= 0 and i < len(playlist["playlist"]) and i != playlist["current_index"] and (fetching_metadata.get(playlist["playlist"][i]) is None):
            get_metadata(playlist["playlist"][i], True, fetch=True)

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
                if not anidb_cooldown and file_data.get('anidb') and (variety_light_mode_enabled or light_mode in ['character', 'tags', 'episodes', 'names']):
                    refresh_anidb_data(file_data.get('anidb'), anime_data)
            return file_data | anime_data
    if fetch:
        return fetch_metadata(filename)
    else:
        return {}

def refetch_metadata():
    if currently_playing and currently_playing.get('type') == 'theme':
        filename = currently_playing.get('filename')
    else:
        filename = playlist["playlist"][playlist["current_index"]]
    fetch_metadata(filename, True)

def get_external_site_id(anime_themes, site):
    if anime_themes:
        for resource in anime_themes.get("resources", []):
            if resource["site"] == site:
                return str(resource["external_id"])
    return None

anidb_cooldown = False
fetching_metadata = {}
def fetch_metadata(filename = None, refetch = False):
    global currently_playing, anidb_cooldown, anidb_delay
    if filename is None:
        filename = playlist["playlist"][playlist["current_index"]]
        refetch = True

    print(f"Fetching metadata for {filename}...", end="", flush=True)

    fetching_metadata[filename] = True
    slug = filename.split("-")[1].split(".")[0].split("v")[0]
    mal_id = None
    anidb_id = None
    if (not "[MAL]" in filename) and (not "[ID]" in filename):
        if len(filename.split("-")) >= 3:
            slug_ext = filename.split("-")[2]
            if "NCBD" not in slug_ext and "NCDVD" not in slug_ext and "BD1080" not in slug_ext and "Lyrics" not in slug_ext:
                slug = slug + "-" + slug_ext.split(".")[0]
        anime_themes = fetch_animethemes_metadata(filename)
        mal_id = get_external_site_id(anime_themes, "MyAnimeList")
        anidb_id = get_external_site_id(anime_themes, "aniDB")
    elif ("[MAL]" in filename):
        filename_metadata = get_filename_metadata(filename)
        mal_id = filename_metadata.get('mal_id')
        anidb_id = filename_metadata.get('anidb_id')
        anime_themes = fetch_animethemes_metadata(mal_id=mal_id)
        if not anime_themes:
            anime_themes = {
                 "animethemes":[]
            }
        else:
            file = anime_themes.get("animethemes",[{}])[0].get("animethemeentries",[{}])[0].get("videos",[{}])[0].get("basename")
            if file:
                anime_themes = fetch_animethemes_metadata(file) or anime_themes
                anidb_id = anidb_id or get_external_site_id(anime_themes, "aniDB")
        if filename_metadata.get("song"):
            anime_themes["animethemes"].append({
                "type": slug[:2],
                "slug": slug,
                "song": {
                    "title": filename_metadata.get("song", "N/A"),
                    "artists": [{
                        "name": filename_metadata.get("artist", "N/A")
                    }]
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
            "slug":slug
        }
        anime_data = anime_metadata.get(mal_id)
        old_songs = []
        if anime_data:
            old_episode_info = anime_data.get("episode_info", [])
            old_characters = anime_data.get("characters", [])
            old_tags = anime_data.get("tags", [])
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
                        anime_data["season"] = aired_to_season_year(anime_data.get("aired"))
                else:
                    anime_data["season"] = anime_data["season"].capitalize()
                anime_metadata[mal_id] = anime_data
        if refetch or not anime_data or not anime_data.get("characters") or not anime_data.get("tags") or not anime_data.get("episode_info"):
            if not anidb_cooldown and anidb_id:
                anidb = fetch_anidb_metadata(anidb_id)
                if anidb["tags"] == [] and anidb["characters"] == [] and anidb["episodes"] == []:
                    anidb_cooldown = True
                    print("[aniDB cooldown reached!]")
                else:
                    anidb_delay = 5
                    anime_data["tags"] = anidb["tags"]
                    anime_data["characters"] = anidb["characters"]
                    anime_data["episode_info"] = anidb["episodes"]
                    anime_metadata[mal_id] = anime_data
            if anidb_cooldown:
                anime_data["tags"] = old_tags
                anime_data["characters"] = old_characters
                anime_data["episode_info"] = old_episode_info
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
                    
            def slug_sort_key(song):
                slug = song["slug"]
                match = re.match(r"([A-Z]+)(\d+)(.*)", slug)
                if match:
                    prefix, num, variant = match.groups()
                    is_variant = bool(variant)  # True if there's a suffix like _EN
                    return (prefix, is_variant, int(num))
                else:
                    # Push unrecognized formats to the end
                    return ("ZZZ", True, float('inf'))

            # Sort and combine
            anime_data["songs"] = (
                sorted(openings, key=slug_sort_key) +
                sorted(endings, key=slug_sort_key) +
                sorted(other, key=slug_sort_key)
            )
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
    metadata = {"mal_id": None, "anidb_id": None, "artist": None, "song": None}
    
    # Define patterns for each tag
    mal_match = re.search(r"\[MAL](\d+)", filename)
    anidb_match = re.search(r"\[ADB](\d+)", filename)
    artist_match = re.search(r"\[ART](.*?)(?=\[|$|\.)", filename)
    song_match = re.search(r"\[SNG](.*?)(?=\[|$|\.)", filename)
    
    # Extract values if found
    if mal_match:
        metadata["mal_id"] = mal_match.group(1)

    if anidb_match:
        metadata["anidb_id"] = anidb_match.group(1)
    
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
    title = data.get('title', f"MAL ID: {mal_id}")
    print(f"Refreshing Jikan data for {title}...", end="", flush=True)
    
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
        
        save_metadata()
        print(f"\rRefreshing Jikan data for {data['title']}...COMPLETE")
    else:
        print(f"\rRefreshing Jikan data for {title}...FAILED")

def refresh_anidb_data(anidb_id, data):
    global anidb_cooldown
    print(f"Refreshing aniDB data for {data['title']}...", end="", flush=True)
    
    anidb = fetch_anidb_metadata(anidb_id)
    if anidb:
        if anidb["tags"] == [] and anidb["characters"] == []:
            anidb_cooldown = True
            print(f"\rRefreshing aniDB data for {data['title']}...FAILED[aniDB cooldown reached!]")
        else:
            data["tags"] = anidb["tags"]
            data["characters"] = anidb["characters"]
            data["episode_info"] = anidb["episodes"]
            save_metadata()
            print(f"\rRefreshing aniDB data for {data['title']}...COMPLETE")
    else:
        print(f"\rRefreshing aniDB data for {data['title']}...FAILED")

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

def get_artists_string(artists, total = False):
    artists_string = "N/A"
    if artists:
        for artist in artists:
            if artists_string == "N/A":
                artists_string = artist
            else:
                artists_string = artists_string + ", " + artist
            if total:
                artist_count = len(get_filenames_from_artist(artist))
                if artist_count > 1:
                    artists_string = f"{artists_string} [{artist_count}]"
    return artists_string

anidb_delay = 0
def fetch_all_metadata(delay=1):
    global cached_pop_time_group, series_cooldowns_cache
    """Fetches missing metadata for the entire directory, spacing out API calls."""
    confirm = messagebox.askyesno("Fetch All Missing Metadata", f"Are you sure you want to fetch all missing metadata?")
    if not confirm:
        return  # User canceled
    scan_directory()
    cached_pop_time_group = None
    series_cooldowns_cache = None
    def worker():
        global anidb_delay
        total_checked = 0
        total_fetched = 0
        total_skipped = 0
        for filename in directory_files:
            total_checked += 1
            # Skip if metadata already exists
            if filename in file_metadata:
                file_data = file_metadata.get(filename)
                mal_id = file_data.get('mal')
                anidb_id = file_data.get('anidb')
                if mal_id in anime_metadata and (not anidb_id or anime_metadata.get(mal_id, {}).get("tags")):
                    if not anime_metadata.get(mal_id, {}).get("title"):
                        refresh_jikan_data(mal_id, anime_metadata.get(mal_id))
                        total_fetched += 1
                    continue  
                if anidb_id and not anime_metadata.get(mal_id, {}).get("tags") and anidb_cooldown:
                    total_skipped += 1
                    continue
            if total_fetched > 0: 
                time.sleep(delay+anidb_delay)  # Delay to avoid API rate limits
                anidb_delay = 0
            fetch_metadata(filename)  # Call your existing metadata function
            total_fetched += 1
            toggle_theme("New Themes", filename=filename, quite=True)

        print("Metadata fetching complete! - Checked:" + str(total_checked) + " Missing:" + str(total_fetched+total_skipped) + " Skipped:" + str(total_skipped))
        if total_fetched > 0:
            print(f"{total_fetched} files saved to playlist '{"New Themes"}'.")

    # Run in a separate thread so it doesn’t freeze the UI
    threading.Thread(target=worker, daemon=True).start()

def refresh_all_metadata(delay=1):
    """Refreshes all jikan metadata for the entire directory, spacing out API calls."""
    confirm = messagebox.askyesno("Refresh All Jikan Metadata", f"Are you sure you want to refresh all jikan metadata?")
    if not confirm:
        return  # User canceled
    def worker():
        current_year = datetime.now().year
        year_limit = messagebox.askyesno("Year Limit", f"Do you want to limit to the last 5 years({current_year-5}-{current_year})?")
        total_checked = 0
        for key, data in anime_metadata.items():
            if key.isdigit():
                season = data.get("season")
                if not year_limit or int(season[-4:] if season and season[-4:].isdigit() else 0) >= (current_year-5):
                    refresh_jikan_data(key, data)
                    total_checked = total_checked + 1
            # time.sleep(delay)  # Delay to avoid API rate limits

        print("Metadata refeshing complete! - Refreshed:" + str(total_checked))

    # Run in a separate thread so it doesn’t freeze the UI
    threading.Thread(target=worker, daemon=True).start()


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
    list_set_loaded(None)
    left_column.delete(1.0, tk.END)
    middle_column.delete(1.0, tk.END)
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
        left_column.window_create(tk.END, window=tk.Button(left_column, text="[AT]", borderwidth=0, pady=0, command=lambda: anime_themes_video(filename), bg="black", fg="white"))
    left_column.window_create(tk.END, window=tk.Button(left_column, text="⎘", borderwidth=0, pady=0, command=lambda: pyperclip.copy(filename), bg="black", fg="white"))
    if playlist["name"] == "Tagged Themes":
        left_column.window_create(tk.END, window=tk.Button(left_column, text="❌", borderwidth=0, pady=0, command=lambda: delete_file_by_filename(filename), bg="black", fg="white"))
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
    filename = currently_playing.get("filename")
    if filename:
        button_seleted(tag_button, check_tagged(filename))
        button_seleted(favorite_button, check_favorited(filename))
        data = currently_playing.get('data')
        reset_metadata()
        if data:
            add_single_data_line(left_column, data, "TITLE: ", 'title', False)
            add_field_total_button(left_column, get_all_matching_field("mal", data.get("mal")), is_game(data))
            if not is_game(data):
                left_column.window_create(tk.END, window=tk.Button(left_column, text="[MAL]", borderwidth=0, pady=0, command=lambda: open_mal_page(data.get("mal")), bg="black", fg="white"))
                left_column.window_create(tk.END, window=tk.Button(left_column, text="[ADB]", borderwidth=0, pady=0, command=lambda: open_anidb_page(data.get("anidb")), bg="black", fg="white"))
                left_column.insert(tk.END, "\n\n", "blank")
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

            update_extra_metadata(data)
            
            toggleColumnEdit(False)
    updating_metadata = False

def update_extra_metadata(data):
    right_column.config(state=tk.NORMAL, wrap="word")
    right_column.delete(1.0, tk.END)
    extra_data = [
        "synopsis", "characters", "episode_info", "tags"
    ]
    right_column.insert(tk.END, "   ", "blank")
    for e in extra_data:
        if selected_extra_metadata == e:
            bg=HIGHLIGHT_COLOR
        else:
            bg="black"
        right_column.window_create(tk.END, window=tk.Button(right_column, text=(f"{e.upper().replace("_INFO", "S")}"), font=("Arial", 11, "bold", "underline"), command=lambda x=e: select_extra_metadata(x), padx=2, bg=bg, fg="white"))
        right_column.insert(tk.END, "   ", "blank")
    right_column.insert(tk.END, "\n\n", "blank")
    if not data.get(selected_extra_metadata):
        right_column.insert(tk.END, f"No {selected_extra_metadata.capitalize().replace("_info", "s")} data found.", "white")
    elif selected_extra_metadata == "synopsis":
        add_single_data_line(right_column, data, "", 'synopsis')
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

            if role == "m":
                groups["main"].append((name, image))
            elif role == "s":
                groups["secondary"].append((name, image))
            else:
                groups["appears"].append((name, image))

        def create_image_popup(name, image_filename):
            def _popup():
                # TODO: Replace this with your actual image retrieval logic
                popup = tk.Toplevel()
                popup.title(name)        
                tk_img = load_image_from_url("https://cdn-eu.anidb.net/images/main/" + image_filename, size=(1000, 1000))
                # Set image and label
                label = tk.Label(popup, image=tk_img, bg="black")
                label.image = tk_img
                label.pack()
            return _popup

        headers = [
            ("Main Characters", groups["main"]),
            ("Supporting Characters", groups["secondary"]),
            ("Also Appears", groups["appears"]),
        ]

        for header, char_list in headers:
            if not char_list:
                continue
            right_column.insert(tk.END, header.upper() + ":\n", "bold")
            for name, image in sorted(char_list, key=lambda x: x[0].lower()):
                b = tk.Button(right_column, text=name, command=create_image_popup(name, image), padx=2, pady=1, bg="black", fg="white", font=("Arial", 12))
                right_column.window_create(tk.END, window=b)
                right_column.insert(tk.END, "\n", "blank")
            right_column.insert(tk.END, "\n", "blank")
    elif selected_extra_metadata == "episode_info":
        episodes = sorted(data.get("episode_info", []), key=lambda x: x[0])  # Sort by episode number
        for num, title in episodes:
            right_column.insert(tk.END, f"EPISODE {num}: ", "bold")
            right_column.insert(tk.END, f"{title}\n", "white")
    elif selected_extra_metadata == "tags":
        tags = sorted(data.get("tags", []), key=lambda x: (-x[1], x[0].lower()))  # Sort by score descending, then name
        display_tags = []
        for tag, score in tags:
            if score > 0:
                display = f"{tag} ({score})"
            else:
                display = tag
            display_tags.append(display.capitalize())
        right_column.insert(tk.END, f"{", ".join(display_tags)}", "white")
        right_column.insert(tk.END, ".", "white")
    right_column.config(state=tk.DISABLED, wrap="word")

selected_extra_metadata = "synopsis"
def select_extra_metadata(extra_metadata):
    global selected_extra_metadata
    selected_extra_metadata = extra_metadata
    update_extra_metadata(currently_playing.get("data"))

def update_series_song_information(data, mal):
    middle_column.config(state=tk.NORMAL)
    middle_column.delete("1.0", tk.END)
    if not data.get("series"):
        update_song_information(data, mal)
    else:
        all_series_themes = get_all_theme_from_series(data)
        index = 0
        for anime_id, anime in all_series_themes:
            index += 1
            middle_column.insert(tk.END, f"{get_display_title(anime)} [{anime.get("season")}]:\n", "bold underline")
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
        add_op_ed(theme, middle_column, slug, data.get("title"), mal)
        if (extra_scroll and extra_scroll < 3) or theme.get("slug") == slug:
            extra_scroll += 1
            middle_column.see("end-1c")
        if index < len(theme_list) - 1:
            middle_column.insert(tk.END, "\n", "blank")

def up_next_text():
    right_top.config(state=tk.NORMAL, height=0, wrap="word")
    right_top.delete(1.0, tk.END)
    if not is_docked():
        if playlist.get("infinite", False) and playlist["current_index"] == len(playlist["playlist"])-2:
            right_top.window_create(tk.END, window=tk.Button(right_top, text="🔄", font=("Arial", 11, "bold"), borderwidth=0, pady=0, command=refetch_next_track, bg="black", fg="white"))
        right_top.insert(tk.END, "NEXT: ", "bold")
        next_up_text = "End of playlist"
        if playlist["current_index"]+1 < len(playlist["playlist"]):
            try:
                next_filename = playlist["playlist"][playlist["current_index"]+1]
                next_up_data = get_metadata(next_filename)
                next_up_text = f"{get_file_marks(next_filename)}{get_display_title(next_up_data)}\n{format_slug(next_up_data.get("slug"))} | {next_up_data.get("members") or 0:,} (#{next_up_data.get("popularity")}) | {next_up_data.get("season")}"
            except Exception:
                next_up_text = playlist["playlist"][playlist["current_index"]+1]
        right_top.insert(tk.END, f"{next_up_text}", "white")
        # Measure line count
        total_lines = right_top.count("1.0", "end", "displaylines")[0]
        right_top.config(state=tk.NORMAL, height=total_lines+1, wrap="word")
    right_top.config(state=tk.DISABLED, wrap="word")

def get_display_title(data):
    return data.get("eng_title") or data.get("title")

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
        if (has_same_start(data.get("title"), anime.get("title"), length=1) or has_same_start(get_display_title(data), get_display_title(anime), length=1)) and not is_game(anime) and (is_parody == ("Parody" in anime.get("themes"))):
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
    filename = get_theme_filename(title, theme_slug)

    if theme_slug == slug:
        format = "highlight"

    # ▶ button or fallback
    if filename:
        column.window_create(tk.END, window=tk.Button(column, text="▶", borderwidth=0, pady=0, command=lambda: play_video_from_filename(filename), bg="black", fg="white"))
        column.insert(tk.END, get_file_marks(filename), format)
    else:
        column.insert(tk.END, ">", format)

    # Song label
    column.insert(tk.END, f"{theme_slug}{overall_theme_num_display(filename)}: {song_title}\n", format)

    # Artist section
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

    column.insert(tk.END, f"\n", format)

    # Episodes + Flags
    column.insert(tk.END, f"(Episodes: {episodes})", format)
    if theme.get("overlap") == "Over":
        column.insert(tk.END, f" (OVERLAP)", format)
    if theme.get("spoiler"):
        column.insert(tk.END, f" (SPOILER)", format)
    if theme.get("special"):
        column.insert(tk.END, f" (SPECIAL)", format)

    column.insert(tk.END, f"\n", format)

def get_file_marks(filename):
    marks = ""
    if check_favorited(filename):
        marks = marks + "❤"
    if check_tagged(filename):
        marks = marks + "❌"
    return marks

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
                    if filename != "archive":
                        match = False
                        for url, value in youtube_metadata.items():
                            if value.get('title') + '.webm' == filename:
                                match = True
                                break
                        if not match:
                            archive_folder = os.path.join(YOUTUBE_FOLDER, "archive")
                            if not os.path.exists(archive_folder):
                                os.makedirs(archive_folder)
                            
                            # Move the outdated video to the archive folder
                            shutil.move(os.path.join(YOUTUBE_FOLDER, filename), os.path.join(archive_folder, filename))
                            print(f"Moved outdated video: {filename} to archive.")
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
    playlis = []
    for file in directory_files:
        playlis.append(file)
    return playlis

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
            series = get_metadata(final_playlist[i]).get("series") or [get_metadata(final_playlist[i]).get("title")]
            total_series = series_totals.get(series[0], 0)
            if total_series > 1:
                if series in exausted_series:
                    skipped_entries += 1
                else:
                    min_spacing = int(min(350, max(3, (len(final_playlist) // total_series)) * (0.9**swap_pass)))
                    for j in range(1, min_spacing + 1):
                        if i + j < len(final_playlist):
                            next_series = get_metadata(final_playlist[i + j]).get("series") or [get_metadata(final_playlist[i + j]).get("title")]
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
    test_size = 5000
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
            return [3,2,1.5][i]
    return 1

difficulty_options = ["MODE: VERY EASY","MODE: EASY","MODE: NORMAL","MODE: HARD","MODE: VERY HARD"]
def select_difficulty(event=None):
    value = difficulty_dropdown.get()
    for i, d in enumerate(difficulty_options):
        if d == value:
            playlist["difficulty"] = i
            get_pop_time_groups(refetch=True)
            update_current_index(save=False)
            if playlist["current_index"] == len(playlist["playlist"])-2:
                refetch_next_track()
    difficulty_dropdown.selection_clear()
    difficulty_dropdown.icursor(tk.END)
    save_config()

def refetch_next_track():
    playlist["playlist"].pop(len(playlist["playlist"])-1)
    get_next_infinite_track(increment=False)
    up_next_text()

INT_INF = 10**18
cached_pop_time_group = None
cached_show_files_map = None
cached_boosted_show_files_map = None
cached_pop_time_cooldown = 0
cached_skipped_themes = []
def get_pop_time_groups(refetch=False):
    global cached_pop_time_group, cached_show_files_map, cached_boosted_show_files_map, cached_pop_time_cooldown, cached_skipped_themes
    if refetch or not cached_pop_time_group:
        # Step 1: Sort by popularity and split into 3 groups
        difficulty_ranges = [
            [100, 250, 500],
            [150, 500, 1000],
            [250, 1000, 0],
            [500, 1500, 0],
            [750, 2000, 0]
        ]
        group_limits = difficulty_ranges[playlist["difficulty"]]
        shows_files_map = {}
        sorted_groups = [[] for _ in range(3)]
        playlist_mal_history = []
        cached_skipped_themes = []
        for f in playlist.get("playlist"):
            d = get_metadata(f)
            if d:
                playlist_mal_history.append(d.get("mal"))

        for f in directory_files:
            d = get_metadata(f)
            if not d or check_tagged(f) or check_theme(f, "New Themes"):
                cached_skipped_themes.append(f)
                continue
            p = get_series_popularity(d)
            mal = d.get("mal")
            for k, l in enumerate(group_limits):
                if (l == 0 or p <= l):
                    boost = 0
                    if not shows_files_map.get(mal):
                        boost += max(0, (d.get("score", 0) or 0) - 7)
                        boost += get_boost_multiplier(d.get("season", "Fall 2000"))
                        check_range = len(playlist["playlist"])
                        while check_range >= 1000:
                            if mal not in playlist_mal_history[-check_range:]:
                                boost += 1
                            check_range -= 1000
                    elif len(shows_files_map[mal]) < [20,5,1][k]:
                        boost += 1
                    for _ in range(int(boost)):
                        sorted_groups[k].append(f)
                    shows_files_map.setdefault(mal, []).append(f)
                    extra_boost = 0
                    if check_favorited(f):
                        extra_boost += 1
                    for _ in range(int(extra_boost)):
                        sorted_groups[k].append(f"{f}[EXTRA]")
                    break
                
        # Step 2: Within each popularity group, sort by year (oldest to newest)
        def sort_by_year(entries):
            return sorted(entries, key=lambda x: int(get_metadata(x.replace("[EXTRA]", "")).get("season", "9999")[-4:]), reverse=True)

        for i, g in enumerate(sorted_groups):
            sorted_subgroups = split_into_three(sort_by_year(g))
            for sublist in sorted_subgroups:
                random.shuffle(sublist)
            sorted_groups[i] = sorted_subgroups
        cached_pop_time_group, cached_show_files_map = sorted_groups, shows_files_map
    if refetch or not cached_boosted_show_files_map:
        # Boost files in each group based on how long unplayed
        boosted_show_files_map = {}
        for key, files in cached_show_files_map.items():
            for file in files:
                file_boost = 1
                check_range = len(playlist["playlist"])
                boost_multiplier = 0
                while check_range >= 1000:
                    boost_multiplier += 1
                    if file not in playlist["playlist"][-check_range:]:
                        file_boost += boost_multiplier
                    check_range -= 1000
                for _ in range(int(file_boost)):
                    boosted_show_files_map.setdefault(key, []).append(file)
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

def get_next_infinite_track(increment=True):
    if not playlist.get("infinite", False):
        return
    
    next_playlist_order(increment)
    groups, shows_files_map = get_pop_time_groups()
    SERIES_LIMIT, FILE_LIMIT = compute_cooldowns(groups)

    p, t = playlist["pop_time_order"][playlist["order"]][0], playlist["pop_time_order"][playlist["order"]][1]
    random.shuffle(groups[p][t])
    selected_file = None
    s_limit = SERIES_LIMIT[p]
    f_limit = FILE_LIMIT[p]
    checked_mal_ids = []
    while not selected_file:
        if not groups[p][t]:
            next_playlist_order()
            p, t = playlist["pop_time_order"][playlist["order"]][0], playlist["pop_time_order"][playlist["order"]][1]
            s_limit = SERIES_LIMIT[p]
            f_limit = FILE_LIMIT[p]
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
                series = d.get("series") or [d.get("title")]
                boost = get_boost_multiplier(d.get("season", "Fall 2000"))
                if s_limit > 1 and f_limit > 1:
                    for h, f in enumerate(reversed(playlist["playlist"])):
                        if f == selected_file or (h < max(SERIES_LIMIT[0], (s_limit/boost)) and series == (get_metadata(f).get("series") or [get_metadata(f).get("title")])):
                            selected_file = None
                            break
                        elif h >= max(FILE_LIMIT[0], ((f_limit)/boost)):
                            break
                if selected_file:
                    playlist["playlist"].append(selected_file)
                    if playlist["current_index"] == -1:
                        update_current_index(0)
                    if len(playlist["playlist"]) > 5000:
                        playlist["playlist"].pop(0)
                        update_current_index(playlist["current_index"]-1)
                    else:
                        update_current_index()
                    return selected_file
        if not groups[p][t]:
            groups = get_pop_time_groups()
            random.shuffle(groups[p][t])
            checked_mal_ids = []
            s_limit = s_limit * 0.9
            f_limit = f_limit * 0.9

series_cooldowns_cache = None
file_cooldowns_cache  = None
def compute_cooldowns(groups):
    global series_cooldowns_cache, file_cooldowns_cache
    if not series_cooldowns_cache:
        POPULARITY_WEIGHTS = [0.5, 0.75, 1.0]  # Lower = more frequent repeats allowed
        FILE_POPULARITY_WEIGHTS = [0.5, 0.75, 1.0]  # Lower = more frequent repeats allowed
        series_cooldowns = []
        file_cooldowns = []

        for i, group in enumerate(groups):
            all_files = [f for subgroup in group for f in subgroup]
            file_count = len(set(all_files))

            unique_series = set(tuple(get_metadata(f).get("series") or [get_metadata(f).get("title")]) for f in all_files)
            series_count = len(unique_series)

            # Base cooldowns
            base_s_cd = series_count
            base_f_cd = file_count

            # Apply weights
            s_cd = max(30, int(base_s_cd * POPULARITY_WEIGHTS[i]))
            f_cd = max(300, int(base_f_cd * FILE_POPULARITY_WEIGHTS[i]))

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
        "playlist": playlist,
        "directory": directory,
        "directory_files": directory_files
    }
    update_current_index(save = False)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_config():
    """Function to load configuration"""
    global directory_files, directory, playlist
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            playlist = config.get("playlist", copy.deepcopy(BLANK_PLAYLIST))
            directory_files = config.get("directory_files", {})
            directory = config.get("directory", "")
            update_playlist_name()
            update_current_index()
    except Exception as e:
        os.remove(CONFIG_FILE)
        print(f"Error loading config: {e}")
        return False
    return False

def update_playlist_name(name=None):
    if name:
        playlist["name"] = name
    root.title(f"[{len(all_themes_played)}] {WINDOW_TITLE} - {playlist["name"]}")

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

def save_metadata_overrides():
    with open(ANIME_METADATA_OVERRIDES_FILE, "w") as f:
        json.dump(anime_metadata_overrides, f, indent=4)

def load_metadata():
    global file_metadata, anime_metadata, anime_metadata_overrides
    if os.path.exists(FILE_METADATA_FILE):
        with open(FILE_METADATA_FILE, "r") as f:
            file_metadata = json.load(f)
            print("Loaded metadata for " + str(len(file_metadata)) + " files...")
    if os.path.exists(ANIME_METADATA_FILE):
        with open(ANIME_METADATA_FILE, "r") as a:
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
    if os.path.exists(ANIME_METADATA_OVERRIDES_FILE):
        with open(ANIME_METADATA_OVERRIDES_FILE, "r") as a:
            anime_metadata_overrides = json.load(a)
            print("Loaded metadata overrides for " + str(len(anime_metadata_overrides)) + " entries...")
            deep_merge(anime_metadata, anime_metadata_overrides)

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

def save_youtube_metadata():
    """Ensures the metadata folder exists before saving metadata file."""
    metadata_folder = os.path.dirname(YOUTUBE_METADATA_FILE)  # Get the folder path

    # Create the folder if it does not exist
    if not os.path.exists(metadata_folder):
        os.makedirs(metadata_folder)

    with open(YOUTUBE_METADATA_FILE, "w") as f:
        json.dump(youtube_metadata, f)

def load_youtube_metadata():
    global youtube_metadata
    if os.path.exists(YOUTUBE_METADATA_FILE):
        with open(YOUTUBE_METADATA_FILE, "r") as f:
            youtube_metadata = json.load(f)
            print("Loaded metadata for " + str(len(youtube_metadata)) + " youtube videos...")
        return True
    return False

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
            return
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
    playlist_data = get_playlists_dict()[index]
    name = playlist_data
    filename = os.path.join(PLAYLISTS_FOLDER, f"{name}.json")

    if not os.path.exists(filename):
        print(f"Playlist {name} not found.")
        return None

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    global playlist, playlist_changed
    if playlist["name"] != "" and not disable_shortcuts:
        save(True)
    playlist_changed = False
    playlist = data
    update_playlist_name()
    update_current_index()
    root.title(WINDOW_TITLE + " - " + playlist["name"])
    print(f"Loaded playlist: {name}")
    playlist_loaded = True
    save_config()
    create_first_row_buttons()
    load(True)

def load(update = False):
    selected = -1
    playlists = get_playlists_dict()
    for key, value in playlists.items():
        if playlist["name"] == value:
            selected = key
            break
        
    show_list("load_playlist", right_column, playlists, get_playlist_name, load_playlist, selected, update)

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
        column.insert(tk.END, f"{count} ({percent}%)", "white")
        add_field_total_button(column, year_to_filenames[group], False, False)
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
    for series, count in sorted(series_counter.items(), key=lambda x: (-x[1], x[0].lower())):
        column.insert(tk.END, f"{series}: ", "bold")
        column.insert(tk.END, f"{count} ({(round(count/len(directory_files)*100, ndigits=2))}%)", "white")
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
        slug = file_metadata.get(filename, {}).get("slug")
        # Artists (only if the slug matches)
        for song in data.get("songs", []):
            if song.get("slug") == slug:
                for artist in song.get("artist", []):
                    artist_counter[artist] += 1
    column.config(state=tk.NORMAL)
    column.delete("1.0", tk.END)
    column.insert(tk.END, "THEMES BY ARTIST\n", ("bold", "underline"))
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
    if playlist.get("infinite", False):
        return

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
    return {i: os.path.splitext(playlis)[0] for i, playlis in enumerate(playlists)}

def get_lowest_parameter(parameter):
    lowest = 10000000
    for filename in playlist["playlist"]:
        data = get_metadata(filename)
        if data:
            item = data.get(parameter, lowest)
            if item and item < lowest:
                lowest = item
    return lowest

def get_highest_parameter(parameter):
    highest = 0
    for filename in playlist["playlist"]:
        data = get_metadata(filename)
        if data:
            item = data.get(parameter, highest)
            if item and item > highest:
                highest = item
    return highest

def get_all_artists():
    artists = []
    for filename in playlist["playlist"]:
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
    for filename in playlist["playlist"]:
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

    for filename in playlist["playlist"]:
        data = get_metadata(filename)
        # Extract metadata
        
        title = data.get("title", "").lower()
        eng_title = (data.get("eng_title", "") or "").lower()
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
    playlist["playlist"] = filtered
    print("Applied Filters:", filters)  # Debugging
    show_playlist(True)
    update_current_index(0)
    messagebox.showinfo("Playlist Filtered", f"Playlist filtered to {len(playlist["playlist"])} videos.")

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
        extract_season_data(filename) if key == "season" else
        float(get_metadata(filename).get(key, 0) or 0) if key in {"members", "score"} else
        get_metadata(filename).get(key, "").lower() if isinstance(get_metadata(filename).get(key), str) else "",
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
        scan_directory()
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
    return {i: os.path.splitext(playlis)[0] for i, playlis in enumerate(playlists)}

# =========================================
#            *LIGHTNING ROUNDS
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
        "title":"Lightning Round",
        "icon":"🗲",
        "desc":(
            "Opening/Ending starts at a random point.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "title":{
        "title":"Title Lightning Round",
        "icon":"𝕋",
        "length":20,
        "desc":(
            "You will be shown the title with most letters blanked.\n"
            "Letters will be revealed over time.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "frame":{
        "title":"Frame Lightning Round",
        "icon":"📷",
        "desc":(
            "You will be shown 4 different frames from the Opening/Ending.\n"
            "Each frame will be visible for " + str(light_round_length // 4) + " seconds.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "character":{
        "title":"Character Lightning Round",
        "icon":"👤",
        "desc":(
            "You will be shown 4 characters one by one every " + str(light_round_length // 4) + " seconds.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "peek":{
        "title":"Peek Lightning Round",
        "icon":"👀",
        "desc":(
            "Opening/Ending starts at a random point muted.\n"
            "Only a small part of the screen is shown, and moves over time.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "blind":{
        "title":"Blind Lightning Round",
        "icon":"👁",
        "desc":(
            "Opening/Ending starts at a random point.\n"
            "You will only be able to hear the music.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "mismatch":{
        "title":"Mismatch Lightning Round",
        "icon":"🔄",
        "desc":(
            "Opening/Ending starts at a random point.\n"
            "You will only be able to hear the music. Visuals from a different theme will play to distract.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "song":{
        "title":"Song Lightning Round",
        "icon":"🎵",
        "desc":(
            "You will be shown song information for the Opening/Ending.\n"
            "It will be revealed over time, and the song plays the last few seconds.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "clues":{
        "length":20,
        "title":"Clues Lightning Round",
        "icon":"🔍",
        "desc":(
            "You will be shown various stats.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "synopsis":{
        "title":"Synopsis Lightning Round",
        "icon":"📰",
        "length":20,
        "desc":(
            "You will be shown a part of the synopsis.\n"
            "It will be revealed word by word over time.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "tags":{
        "length":20,
        "title":"Tags Lightning Round",
        "icon":"🔖",
        "desc":(
            "You will be show detailed tags revealed over time.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "episodes":{
        "length":20,
        "title":"Episodes Lightning Round",
        "icon":"📺",
        "desc":(
            "You will be shown 6 episode titles.\n"
            "They will be revealed over time.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "names":{
        "length":20,
        "title":"Names Lightning Round",
        "icon":"🎭",
        "desc":(
            "You will be shown 6 character names.\n"
            "They will be revealed over time.\n"
            "You have 20 seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    },
    "variety":{
        "title":"Variety Lightning Round",
        "icon":"🎲",
        "desc":(
            "Plays a dynamic mix of lightning rounds based on popularity.\n"
            "You have " + str(light_round_length) + " seconds to guess.\n\n"
            "1 PT for the first to guess the anime!"
        )
    }
}

def toggle_light_mode(type=None):
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
            # light_dropdown.current(list(light_modes.keys()).index(type))
            configure_style()
            light_dropdown.update_idletasks()
            light_dropdown.configure(state="readonly", style='Black.TCombobox')
            unhighlight_selection(None, setting=True)
            light_dropdown.update_idletasks()
        button_seleted(globals()['start_light_mode_button'], True)
        start_light_mode_button.configure(text="⏹️")
        if popout_buttons_by_name.get(start_light_mode_button):
            popout_buttons_by_name[start_light_mode_button].configure(text="⏹️\nSTOP")
        if light_round_number == 0:
            image_path = "banners/" + type + "_lightning_round.webp"
            image_tk = None
            if os.path.exists(image_path):
                image = Image.open(image_path)
                image = image.resize((400, 225), Image.LANCZOS)  # Resize if needed
                image_tk = ImageTk.PhotoImage(image)  # Convert to Tkinter format
            toggle_coming_up_popup(True, mode.get("title"), mode.get("desc"), image_tk, queue=True)

def unselect_light_modes():
    global light_mode, variety_light_mode_enabled, start_light_mode_button
    light_mode = None
    variety_light_mode_enabled = False
    button_seleted(globals()['variety_light_mode_button'], False)
    button_seleted(globals()['start_light_mode_button'], False)
    start_light_mode_button.configure(text="▶")
    if popout_buttons_by_name.get(start_light_mode_button):
        popout_buttons_by_name[start_light_mode_button].configure(text="▶\nSTART")

def get_light_round_time():
    length = player.get_length()/1000
    buffer = 10
    need_censors = light_mode in ['regular', 'peek']
    need_mute_censors = light_mode in ['regular', 'blind', 'mismatch', 'song']
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
                    if ((censor.get("mute") and need_mute_censors) or (not censor.get("mute") and need_censors)) and (not (censor['end'] < start_time or censor['start'] > end_time)):
                        start_time = None
                        break
    return start_time

light_speed_modifier = 1
light_fullscreen_try = False
def update_light_round(time):
    global light_round_started, light_round_start_time, censors_enabled, light_round_length, light_speed_modifier, light_name_overlay, light_fullscreen_try
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
                player.set_fullscreen(True)
                if mismatch_visuals:
                    top_info_data = "MISMATCHED VISUALS:\n" + mismatch_visuals
                else:
                    top_info_data = None
                toggle_title_popup(True)
                set_black_screen(False)
                clean_up_light_round()
                if top_info_data:
                    top_info(top_info_data, 20)
            if not light_mode:
                start_str = "end"
            set_countdown(start_str + " in..." + str(round(light_round_answer_length-(time - (light_round_start_time+light_round_length)))))
        else:
            if not light_fullscreen_try:
                light_fullscreen_try = True
                player.set_fullscreen(False)
                player.set_fullscreen(True)
            time_left = (light_round_length-(time - light_round_start_time))
            if time_left < 1 and light_speed_modifier != 1:
                light_speed_modifier = 1
                player.set_rate(light_speed_modifier)
            if light_mode == 'mismatch' and time_left > 11:
                mismatched_player.set_fullscreen(False)
                mismatched_player.set_fullscreen(True)
            if song_overlay_boxes:
                toggle_song_overlay(show_title=True, show_artist=time_left<=9, show_theme=time_left<=6, show_music=time_left<=4)
                player.audio_set_mute(time_left > 4)
                play_background_music(time_left > 4)
            elif clues_overlay:
                data = currently_playing.get("data")
                if time_left <= 15:
                    tags = "\n".join(get_tags(data))
                    val_size = 60 - max(0, (tags.count('\n') - 5) * 5)
                    clues_overlay_labels["Tags"].config(text=tags, font=("Arial", val_size))
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
                toggle_synopsis_overlay(text=get_light_synopsis_string(min(41, (light_round_length*3)-round(time_left*3)+1)))
            elif light_progress_bar:
                set_progress_overlay(round((time - light_round_start_time)*100), light_round_length*100)
            elif title_overlay:
                starting_letters = min(5, max(1, len(title_light_letters) // 5))
                interval = len(title_light_letters) * 0.09
                final_count = round((5*interval)+starting_letters)
                word_num = min(final_count, int(((light_round_length-time_left)/3)*interval)+starting_letters)
                set_frame_number(f"{word_num}/{final_count} REVEALS")
                toggle_title_overlay(get_title_light_string(word_num))
            elif peek_overlay:
                gap = get_peek_gap(currently_playing.get("data"))
                toggle_peek_overlay(direction=peek_light_direction, progress=((light_round_length-time_left)/light_round_length)*100, gap=gap)
                now_playing_background_music(music_files[current_music_index])
            elif character_overlay_boxes:
                reveal_num = min(4, (int(light_round_length - (time_left)) // (light_round_length // 4)) + 1)
                toggle_character_overlay(num_characters=reveal_num)
                set_frame_number(f"{reveal_num}/{4}")
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
            set_countdown(round(time_left/light_speed_modifier))
    if light_mode and time < 1:
        toggle_coming_up_popup(False, "Lightning Round")
        if not light_round_started:
            light_round_started = True
            if light_mode == 'regular' or light_mode == 'peek':
                root.after(500, set_black_screen, False)
            if light_mode in ['regular', 'blind'] and light_speed_modifier == 1:
                popularity = currently_playing.get("data", {}).get("popularity", 1000) or 3000
                if (popularity <= 100 and random.randint(1, 5) == 1) or (popularity <= 250 and random.randint(1, 10) == 1):
                    light_speed_modifier = 2
                    player.set_rate(light_speed_modifier)
                    light_round_length = light_round_length*light_speed_modifier
                    set_frame_number(f"x{light_speed_modifier} SPEED")
            if light_round_start_time is None:
                light_round_start_time = get_light_round_time()
            if light_mode == 'blind':
                set_progress_overlay(light_round_start_time*100, light_round_length*100)
            elif light_mode in ['clues', 'song', 'synopsis', 'title', 'peek', 'character', 'tags', 'episodes', 'names']:
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
                    toggle_title_overlay(get_title_light_string(min(5, max(1, len(title_light_letters) // 5))))
                    set_frame_number(f"2/{min(7, len(title_light_string))}")
                    top_info("MUST SAY FULL TITLE")
                elif light_mode == 'peek':
                    choose_peek_direction()
                    toggle_peek_overlay()
                elif light_mode == 'character':
                    get_character_round_characters()
                    toggle_character_overlay(num_characters=1)
                    top_info("CHARACTERS")
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
                pass
        player.set_time(int(float(light_round_start_time))*1000)
        if light_mode == 'mismatch':
            media = instance.media_new(directory_files.get(get_mismatched_theme()))
            mismatched_player.set_media(media)
            mismatched_player.play()
            mismatched_player.set_time(int(float(light_round_start_time))*1000)
            mismatched_player.set_fullscreen(False)
            mismatched_player.set_fullscreen(True)
            top_info("MISMATCHED VISUALS")
            set_frame_number("GUESS BY MUSIC ONLY")
            root.after(700, set_black_screen, False)
        else:
            player.set_fullscreen(False)
            player.set_fullscreen(True)
        set_countdown(light_round_length)
        set_light_round_number("#" + str(light_round_number))

def clean_up_light_round():
    global mismatch_visuals, character_round_characters, tag_cloud_tags, light_speed_modifier, light_episode_names, light_name_overlay, light_fullscreen_try
    light_fullscreen_try = False
    mismatched_player.stop()
    mismatched_player.set_media(None)  # Reset the media
    mismatch_visuals = None
    light_name_overlay = False
    character_round_characters = []
    tag_cloud_tags = []
    light_episode_names = []
    light_speed_modifier = 1
    player.set_rate(light_speed_modifier)
    for overlay in [set_progress_overlay, toggle_clues_overlay, toggle_song_overlay, toggle_synopsis_overlay, toggle_title_overlay, 
                    toggle_peek_overlay, toggle_character_overlay, toggle_tag_cloud_overlay, toggle_episode_overlay]:
        overlay(destroy=True)
    for info in [set_frame_number, top_info]:
        info()
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

def get_light_bg_color():
    if is_game(currently_playing.get("data")):
        return "Dark Red"
    else:
        return "Black"

# =========================================
#          *VARIETY LIGHTNING ROUND
# =========================================

last_round = None
variety_light_mode_enabled = False
variety_mode_cooldowns = {
    "song":     {"min": 10, "max": 20, "max_limit": 100},
    "clues":    {"min": 10, "max": 20, "max_limit": 250, "repeat":40},
    "tags":     {"min": 15, "max": 20, "max_limit": 500, "repeat":40},
    "episodes": {"min": 10, "max": 20, "max_limit": 500, "repeat":40},
    "names":    {"min": 10, "max": 20, "max_limit": 500, "repeat":40},
    "blind":    {"min": 3, "max": 8, "max_limit": 750},
    "mismatch": {"min": 3, "max": 8, "max_limit": 750},
    "title":    {"min": 4, "max": 7, "max_limit": 1000, "repeat":80},
    "synopsis": {"min": 4, "max": 7, "max_limit": 1000, "repeat":80},
    "character":{"min": 2, "max": 7, "repeat":80},
    "peek":     {"min": 3, "max": 10},
    "frame":    {"min": 4, "max": 20},
}

def append_lightning_history():
    data = currently_playing.get("data", {})
    mode_limits = variety_mode_cooldowns.get(light_mode)
    if mode_limits and mode_limits.get("repeat"):
        if light_mode == "title":
            append = get_base_title()
        else:
            append = data.get("mal")
        if append:
            playlist["lightning_history"].setdefault(light_mode, []).append(append)
            while len(playlist["lightning_history"][light_mode]) > mode_limits.get("repeat"):
                playlist["lightning_history"][light_mode].pop(0)

def check_recent_history(mode):
    mode_limits = variety_mode_cooldowns.get(mode)
    if mode_limits.get("repeat"):
        if light_mode == "title":
            append_check = get_base_title()
        else:
            append_check = currently_playing.get("data", {}).get("mal")
        if append_check:
            return append_check in playlist.get("lightning_history", {}).get(mode, [])
    return False


def get_series_popularity(data):
    max_popularity = data.get('popularity') or 3000
    series = data.get("series")
    if series:
        for key, anime in anime_metadata.items():
            if anime.get("series") == series:
                popularity = anime.get('popularity') or 3000
                if popularity < max_popularity:
                    max_popularity = popularity
    return max_popularity

def set_variety_light_mode():
    global last_round, variety_light_mode_enabled, variety_mode_cooldowns
    data = currently_playing.get('data', {})
    popularity = ((data.get('popularity') or 3000) + get_series_popularity(data)) / 2
    
    is_op = data.get('slug').startswith("OP")

    # Round options by popularity and OP status, now strings instead of numbers
    if popularity <= 100:
        if is_op:
            round_options = (
                ["frame"] +
                ["blind"] * 2 +
                ["mismatch"] * 2 +
                ["clues", "song", "character", "synopsis", "title", "tags", "episodes", "names"] +
                ["peek"] * 2
            )
        else:
            round_options = (
                ["frame"] +
                ["blind"] * 2 +
                ["mismatch"] * 2 +
                ["clues"] * 2 +
                ["song", "synopsis", "title", "character", "peek", "tags", "episodes", "names"]
            )
    elif popularity <= 250:
        if is_op:
            round_options = (
                ["regular", "frame"] +
                ["blind"] * 2 +
                ["mismatch"] * 2 +
                ["clues", "song", "character", "synopsis", "title", "tags", "episodes", "names"] +
                ["peek"] * 2
            )
        else:
            round_options = (
                ["regular", "frame"] +
                ["frame"] +
                ["blind", "mismatch"] +
                ["clues", "synopsis", "character", "tags", "episodes", "names"] +
                ["title"] * 2 +
                ["peek"] * 2
            )
    elif popularity <= 500:
        round_options = (
            ["regular"] +
            ["frame"] * 2 +
            ["blind"] * 2 +
            ["mismatch"] * 2 +
            ["character"] * 2 +
            ["clues", "synopsis", "title", "peek", "tags", "episodes", "names"]
        )
    elif popularity <= 750:
        round_options = (
            ["regular"] * 2 +
            ["frame"] * 2 +
            ["blind"] * 3 +
            ["character"] * 2 +
            ["mismatch", "synopsis", "title", "peek", "tags", "episodes", "names"]
        )
    elif popularity <= 1000:
        if is_op:
            round_options = (
                ["regular"] * 2 +
                ["frame"] * 2 +
                ["character"] * 2 +
                ["blind", "mismatch", "synopsis", "title", "peek", "tags", "episodes", "names"]
            )
        else:
            round_options = (
                ["regular"] * 4 +
                ["frame"] * 4 +
                ["character"] * 2 +
                ["blind", "synopsis", "title", "tags", "episodes", "names"]
            )
    elif popularity <= 1500:
        round_options = (
            ["regular"] * 5 +
            ["frame"] * 3 +
            ["blind", "title", "peek"] + 
            ["character"] * 2
        )
    else:
        round_options = (
            ["regular"] * 4 +
            ["frame"] * 3 +
            ["peek"] * 2 +
            ["character"] * 2
        )

    # Filtering based on conditions
    if len(get_tags(data)) < 3:
        round_options = [r for r in round_options if r != "clues"]
    if get_song_string(data, "artist") == "N/A":
        round_options = [r for r in round_options if r != "song"]
    if len((data.get("synopsis") or "").split()) <= 40:
        round_options = [r for r in round_options if r != "synopsis"]
    if len(get_unique_letters(get_base_title())) < 7:
        round_options = [r for r in round_options if r != "title"]
    if len(data.get("characters", [])) < 4:
        round_options = [r for r in round_options if r != "character"]
    if len(data.get("tags", [])) < 10:
        round_options = [r for r in round_options if r != "tags"]
    if len(data.get("episode_info", [])) < 6:
        round_options = [r for r in round_options if r != "episodes"]
    if len(data.get("characters", [])) < 6:
        round_options = [r for r in round_options if r != "names"]

    # Remove last round from options to avoid repeats
    round_options = [r for r in round_options if r != last_round]

    # Apply cooldown filtering
    forced = False
    for rnd_name, cooldown in variety_mode_cooldowns.items():
        if rnd_name in round_options:
            count = cooldown.get("rnd", 0)
            if check_recent_history(rnd_name) or (cooldown.get("played") and count < cooldown.get("min", 0)):
                round_options = [r for r in round_options if r != rnd_name]
            elif count >= cooldown.get("max", 100) and popularity <= cooldown.get("max_limit", 10000):
                round_options = [rnd_name]
                forced = True
                break

    if not round_options:
        next_round = "regular"
    else:
        random.shuffle(round_options)
        next_round = round_options[0]

    # Update cooldown counters
    for rnd_name in variety_mode_cooldowns:
        if rnd_name == next_round:
            variety_mode_cooldowns[rnd_name]["rnd"] = 0
            variety_mode_cooldowns[rnd_name]["played"] = True
        else:
            variety_mode_cooldowns[rnd_name]["rnd"] = variety_mode_cooldowns[rnd_name].get("rnd", 0) + 1

    last_round = next_round

    if not testing_variety:
        unselect_light_modes()
        toggle_light_mode(next_round)
        variety_light_mode_enabled = True
        button_seleted(variety_light_mode_button, True)
    return next_round, forced

testing_variety = False
def test_variety_distrbution(event=None):
    global currently_playing, testing_variety
    print("TESTING VARIETY LIGHTNING ROUND DISTRIBUTION:")
    i = 0
    mode_counts = {}
    testing_variety = True
    while i < 1000 and playlist["current_index"]+i < len(playlist["playlist"]):
        filename = playlist[playlist["current_index"]+i]
        data = get_metadata(filename, fetch=True)
        currently_playing = {
            "type":"theme",
            "filename":filename,
            "data":data
        }
        mode, forced = set_variety_light_mode()
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        i += 1
        if forced:
            mode = f"{mode}[FORCED]"
        print(f"{i}. {get_display_title(data)} {format_slug(data.get("slug"))}[{data.get("popularity")}]: {mode}")
    testing_variety = False
    for m in light_modes:
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
    clues_overlay.configure(bg="black")

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
        frame = tk.Frame(clues_overlay, bg="black", padx=20, pady=20, highlightbackground="white", highlightthickness=4)
        frame.grid(row=row, column=column, columnspan=columnspan, rowspan=rowspan, sticky="nsew", padx=10, pady=10)

        if title:
            tk.Label(frame, text=title.upper(), font=("Arial", 50, "bold", "underline"), fg="white", bg="black").pack(anchor="center")

        val_size = 70 - max(0, (value.count('\n') - 5) * 5)
        label = tk.Label(frame, text=value, font=("Arial", val_size), fg="white", bg="black",
                         wraplength=((overlay_width // 3) * columnspan - 10), justify="center")
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
                box.configure(bg="black", padx=20, pady=20, highlightbackground="white", highlightthickness=4)

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

# =========================================
#          *SYNOPSIS LIGHTNING ROUND
# =========================================

synopsis_start_index = None
synopsis_split = None
def pick_synopsis():
    global synopsis_start_index, synopsis_split
    if not synopsis_start_index:
        synopsis = (currently_playing.get("data", {}).get("synopsis") or "No synopsis found.")
        for extra_characters in ["\n\n[Written by MAL Rewrite]", "\n\n(Source: adapted from ANN)", " \n\n", "\n \n", "\n\n", "\n"]:
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
        content_height = measure_text_height(get_light_synopsis_string(), wraplength-5, font=("Arial", 60))+30
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

# =========================================
#          *TITLE LIGHTNING ROUND
# =========================================

title_light_letters = None
title_light_string = None
def set_title_light_text():
    global title_light_letters, title_light_string
    if not title_light_letters:
        title_light_letters = get_unique_letters(get_base_title())
        title_light_string = get_base_title()
        random.shuffle(title_light_letters)

def get_base_title():
    data = currently_playing.get("data", {})
    title = data.get('eng_title') or data.get("title")
    for p in [': ',' ']:
        for s in ['Season', 'Series', 'Part']:
            for n in ['0','1','2','3','4','5','6','7','8','9','I','II','III','IV','V','VI','VII','VIII','VIIII','X']:
                title = title.replace(f"{p}{s} {n}", "")
    for p in [': ',' ']:
        for n in ['First','Second','Third','Fourth','Fifth','1st','2nd','3rd','4th','5th','6th','Final']:
            for s in ['Season', 'Series', 'Part']:
                title = title.replace(f"{p}{n} {s}", "")
    return title

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

# =========================================
#          *PEEK LIGHTNING ROUND
# =========================================

peek_modifier = 0
gap_modifier = 0
def toggle_peek():
    global peek_modifier, gap_modifier
    if not peek_overlay:
        gap_modifier = 0
        peek_modifier = random.randint(0,24)
        toggle_peek_overlay()
        if black_overlay:
            blind()
        button_seleted(peek_button, True)
    else:
        toggle_peek_overlay(destroy=True)

peek_round_toggle = False
def toggle_peek_round():
    global peek_round_toggle
    peek_round_toggle = not peek_round_toggle
    button_seleted(peek_round_button, peek_round_toggle)
    if peek_round_toggle:
        if blind_round_toggle:
            toggle_blind_round()
        toggle_coming_up_popup(True, "Peek Round", "Guess the anime from a small moving window revealing the visuals. \nNormal rules apply.", queue=True)
    else:
        toggle_coming_up_popup(False, "Peek Round")

def widen_peek():
    global gap_modifier
    gap_modifier += 1

def get_peek_gap(data):
    gap = (0 + min(9, (data.get('popularity') or 3000)/100))
    return gap

peek_light_direction = None
def choose_peek_direction():
    global peek_light_direction
    new_dir = peek_light_direction
    while new_dir == peek_light_direction:
        new_dir = random.choice(["right","down"])
    peek_light_direction = new_dir

peek_overlay = None
def toggle_peek_overlay(destroy=False, direction="right", progress=0, gap=1):
    """Toggles two fullscreen overlays that reveal the screen in a chosen direction by percentage.

    Args:
        destroy (bool): Whether to remove the overlays.
        direction (str): 'left', 'right', 'up', or 'down'.
        progress (int): How much to reveal, from 0 (fully covered) to 100 (fully uncovered).
        gap (int): The gap between the two overlays, as a percentage of the screen width/height.
    """
    global peek_overlay

    if destroy:
        if peek_overlay:
            if peek_overlay[0]:
                peek_overlay[0].destroy()
            if peek_overlay[1]:
                peek_overlay[1].destroy()
            peek_overlay = None
            button_seleted(peek_button, False)
        return

    if not 0 <= progress <= 100:
        return

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()

    # Calculate the gap in pixels as a percentage of the screen size
    gap_pixels = ((gap / 100) * screen_width) + (gap_modifier*(screen_width/100)) # Use screen width for gap calculation
    # Initialize overlay dimensions and positions
    first_width, first_height, first_x, first_y = 0, 0, 0, 0
    second_width, second_height, second_x, second_y = 0, 0, 0, 0

    cover_margin = 20  # pixels to ensure full screen edge coverage

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

    # Create the peek_overlay list if it hasn't been created yet
    if peek_overlay is None:
        peek_overlay = [None, None]

    # image_color = get_image_color()
    image_color = "Black"
    # First overlay
    if peek_overlay[0] is None:
        peek_overlay[0] = tk.Toplevel(root)
        peek_overlay[0].overrideredirect(True)
        peek_overlay[0].attributes("-topmost", True)
        peek_overlay[0].configure(bg=image_color)

    # Second overlay
    if peek_overlay[1] is None:
        peek_overlay[1] = tk.Toplevel(root)
        peek_overlay[1].overrideredirect(True)
        peek_overlay[1].attributes("-topmost", True)
        peek_overlay[1].configure(bg=image_color)

    # Update both overlays
    def update_overlays():
        for i in range(2):
            if peek_overlay and peek_overlay[i]:
                peek_overlay[i].update()
            else:
                return False
        return True

    if update_overlays():
        if direction == "right":
            peek_overlay[1].geometry(f"{first_width}x{first_height}+{first_x}+{first_y}")
            peek_overlay[0].geometry(f"{second_width}x{second_height}+{second_x}+{second_y}")
        else:
            peek_overlay[0].geometry(f"{first_width}x{first_height}+{first_x}+{first_y}")
            peek_overlay[1].geometry(f"{second_width}x{second_height}+{second_x}+{second_y}")
    
    update_overlays()
    button_seleted(peek_button, True)
    lift_windows()

# =========================================
#          *MISMATCH LIGHTNING ROUND
# =========================================

instance2 = vlc.Instance("--no-audio", "--fullscreen", "--no-xlib", "-q")
mismatched_player = instance2.media_player_new()
mismatch_visuals = None
def get_mismatched_theme():
    global mismatch_visuals
    options = []
    match_data = currently_playing.get("data")
    if match_data:
        is_op = "OP" in match_data.get("slug")
        match_series = (match_data.get("series") or [match_data.get("title")])[0]
        for filename in directory_files:
            if not check_nsfw(filename):
                data = get_metadata(filename)
                if data:
                    filename_series = (data.get("series") or [data.get("title")])[0]
                    if match_series != filename_series and (is_op == ("OP" in data.get("slug"))):
                        options.append(filename)
    random.shuffle(options)
    mismatch_data = get_metadata(options[0])
    mismatch_visuals = get_display_title(mismatch_data) + " " + format_slug(mismatch_data.get("slug"))
    return options[0]

def check_nsfw(filename):
    for censor in censor_list.get(filename, {}):
        if censor.get("nsfw"):
            return True
    return False

# =========================================
#          *CHARACTER LIGHTNING ROUND
# =========================================

character_overlay_boxes = {}
character_round_characters = []
character_round_image_cache_default = []
character_round_image_cache_default_urls =[
    "https://w0.peakpx.com/wallpaper/104/618/HD-wallpaper-anime-error-female-dress-black-cute-hair-windows-girl-anime-page.jpg",
    "https://i.imgflip.com/1xuu83.jpg",
    "https://platform.polygon.com/wp-content/uploads/sites/2/chorus/uploads/chorus_asset/file/23653986/20073937.jpeg",
    "https://cdn.anidb.net/misc/confused.png",
]

def get_cached_character_round_images(urls, default=False):
    global character_round_image_cache_default, character_round_characters
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    img_size = int(min(screen_width, screen_height) * 0.35)
    for index, url in enumerate(urls):
        tk_img = load_image_from_url(url, size=(img_size, img_size))
        if tk_img:
            if default:
                character_round_image_cache_default.append(tk_img)
            else:
                character_round_characters.append(tk_img)
        else:
            if not default and index < len(character_round_image_cache_default):
                character_round_characters.append(character_round_image_cache_default[index])

def load_default_char_images():
    get_cached_character_round_images(character_round_image_cache_default_urls, default=True)

def get_character_round_characters():
    global character_round_characters
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
        character_round_characters = []
        get_cached_character_round_images([urls[0]])
        def worker():
            get_cached_character_round_images(urls[1:4])
        threading.Thread(target=worker, daemon=True).start()
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
                tags.append({"name": tag[0], "weight": tag[1]})
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
    min_font_size = max(22, 60 - len(tag_cloud_tags))
    max_font_size = max(min_font_size+6, 60 - len(tag_cloud_tags) // 4)  # Smaller range for many tags

    font_range = max_font_size - min_font_size

    def font_size(w):
        # Normalize weight and apply squash (square root) to reduce disparity
        normalized = (w - min_w) / (max_w - min_w + 1e-5)
        squashed = normalized ** 0.5  # reduces the extreme difference
        return int(min_font_size + font_range * squashed)

    random.shuffle(tag_cloud_tags)
    if currently_playing.get("data", {}).get("season"):
        tag_cloud_tags.append({"name": currently_playing.get("data", {}).get("season")[-4:], "weight": 600})
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
    margin = 50

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
        box.configure(bg="black")

        label = tk.Label(
            box, text=tag["name"],
            font=("Arial", font_size, "bold"),
            fg="white", bg="black"
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
    episode_names = []
    episodes = data.get("episode_info")
    if data and episodes:
        random.shuffle(episodes)
        for ep in episodes:
            episode_names.append(f"{ep[1]}")
    else:
        episode_names.append(f"No Episodes Found")
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
        box.configure(bg="black", highlightbackground="white", highlightthickness=4)
        font_size = 55
        wrap = box_width - 40
        # Try to find the largest font size that fits within 3 lines
        background = "black"
        if light_name_overlay:
            background = {"a":'#374151',"s":'#065F46',"m":'#1E3A8A'}.get(title[0], '#374151')
            title = title[1]
        while font_size >= 10:
            test_font = tkFont.Font(family="Arial", size=font_size, weight="bold")
            line_count = get_wrapped_line_count(title, test_font, wrap-10)
            if line_count <= 3:
                break
            font_size -= 1
        label = tk.Label(
            box,
            text=title,
            font=("Arial", font_size, "bold"),
            fg="white",
            bg=background,
            wraplength=wrap,
            justify="center"
        )
        label.pack(expand=True, fill="both", padx=10, pady=10)

        box.geometry(f"{box_width - 20}x{box_height - 20}+{x}+{y}")
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
#          *LIGHTNING ROUND OVERLAYS
# =========================================

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

def top_info(value=None, size=80):
    set_floating_text("Top Info", value, position="top center", size=size)

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

progress_overlay = None
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
    global progress_overlay, light_progress_bar, music_icon_label
    # If asked to destroy, close the progress_overlay and clear globals
    if destroy:
        if progress_overlay is not None:
            screen_width = progress_overlay.winfo_screenwidth()
            screen_height = progress_overlay.winfo_screenheight()
            window_height = round((screen_height/15)*6)
            animate_window(progress_overlay, screen_width, (screen_height - window_height) // 2, steps=20, delay=5, bounce=False, fade=None, destroy=True)
        progress_overlay = None
        light_progress_bar = None
        return

    # Create progress_overlay if it doesn't exist
    if progress_overlay is None:
        progress_overlay = tk.Toplevel(root)
        progress_overlay.title("Blind Progress Bar")
        progress_overlay.overrideredirect(True)  # Remove window decorations
        progress_overlay.attributes("-topmost", True)  # Ensure it stays on top
        progress_overlay.attributes("-alpha", 0.8)  # Semi-transparent
        progress_overlay.configure(bg="black")
        
        # Set a larger size for the progress_overlay (e.g., 800x200) and center it
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        width, height = round(screen_width*.7), round((screen_height*.5))

        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        progress_overlay.update_idletasks()
        progress_overlay.geometry(f"{width}x{height}+{-screen_width}+{y}")
        # progress_overlay.geometry(f"{width}x{height}+{x}+{y}")
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
        
        # Create a larger progress bar inside the progress_overlay (length 700 pixels)
        light_progress_bar = ttk.Progressbar(progress_overlay, orient="horizontal", mode="determinate", length=round(screen_width*.6))
        light_progress_bar.place(relx=0.5, rely=0.7, anchor="center")
        
        # Add a music icon (using a label with text or an image)
        music_icon_label = tk.Label(progress_overlay, text="🎵", font=("Arial", 100), bg="black", fg=generate_random_color(100,255)) #  🎶 🎵  🎶
        music_icon_label.place(relx=0, rely=0.35, anchor="center")

        # Start pulsating the music icon
        pulsate_music_icon(music_icon_label)
        progress_overlay.update_idletasks()
        animate_window(progress_overlay, x, y, steps=20, delay=5, bounce=False, fade=None)  # Animate to center

    # If current_time and total_length are provided, update the progress bar
    if current_time is not None and total_length is not None:
        move_music_icon(current_time, total_length)
        light_progress_bar["maximum"] = total_length
        light_progress_bar["value"] = current_time
        progress_overlay.wm_attributes("-topmost", True)

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
            if disable_video_audio:
                pygame.mixer.music.set_volume(0)
            else:
                pygame.mixer.music.set_volume(0.15*(volume_level/100))  # Adjust volume
            music_changed = False
            now_playing_background_music(music_files[current_music_index])

def now_playing_background_music(track = None):
    if track:
        basename = os.path.basename(track)
        for ext in valid_music_ext:
            basename = basename.replace(ext, "")
        track = "BGM: " + basename
    set_floating_text("Now Playing Background Music", track, position="bottom left", size=14)

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
    bg_color = "Black"
    fg_color = "White"
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
            fg_color = "Black"
            bg_color = "White"

            top_row = f"Uploaded by {channel} ({subscribers} subscribers)"
            title_row = title
            bottom_row = f"{full_title}\nViews: {views} | Likes: {likes} | {uploaded} | {duration}"
        else:
            japanese_title = data.get("title")
            title = data.get("eng_title") or japanese_title or (data.get("synonyms", [None]) or [None])[0]
            get_series_totals(refetch=False)
            series_total = series_totals.get((data.get("series") or [data.get("title")])[0], 0)
            if series_total > 1:
                japanese_title = f"{japanese_title} [{series_total}]"
            theme = format_slug(data.get("slug"))
            marks = get_file_marks(currently_playing.get("filename", ""))
            song = get_song_string(data, totals=True)
            if is_game(data):
                aired = data.get("release")
                bg_color = "Dark Red"
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
            top_row = f"{marks}{theme}{overall_theme_num_display(currently_playing.get("filename"))} | {song} | {aired}"
            title_row = title
            bottom_row = f"{score} | {japanese_title} | {members}\n{studio} | {tags} | {episodes} | {type} | {source}"
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
        top_row_label.pack(pady=(10, 0), padx = 10)

        # Title Label (Large Text)
        title_row_label = tk.Label(title_window, text=title_row, font=title_font, fg=fg_color, bg=bg_color)
        title_row_label.pack(pady=(0, 0), padx = 10)

        bottom_row_label = tk.Label(title_window, text=bottom_row,
                                font=bottom_font, fg=fg_color, bg=bg_color)
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
    return ", ".join(get_tags(data))

def get_tags(data):
    tags = []
    for c in ['genres', 'themes','demographics']:
        if data.get(c):
            tags = tags + data.get(c)
    return tags

def get_song_string(data, type=None, totals=False):
    for theme in data.get("songs", []):
        if theme.get("slug") == data.get("slug"):
            if type:
                if type == "artist":
                    return get_artists_string(theme.get("artist"), total=totals)
                else:
                    return theme.get(type)
            else:
                return theme.get("title") + " by " + get_artists_string(theme.get("artist"), total=totals)
    return ""
    
# =========================================
#         *GUESS YEAR/MEMBERS/SCORE
# =========================================

guessing_extra = None
def guess_extra(extra = None):
    global guessing_extra
    buttons = [guess_year_button, guess_members_button, guess_score_button, guess_tags_button, guess_multiple_button]
    for b in buttons:
        button_seleted(b, False)
    ROUND_PREFIX = "BONUS?: "
    if extra:
        if extra == guessing_extra:
            guessing_extra = None
            toggle_coming_up_popup(False, ROUND_PREFIX)
        else:
            guessing_extra = extra
        if guessing_extra == "year":
            button_seleted(guess_year_button, True)
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The Year This Anime Aired", 
                                ("Only 1 guess per person, no repeats.\n"
                                "+1 PT for closest guess. "
                                "+2 PTs if exact year."),
                                up_next=False)
        elif guessing_extra == "members":
            button_seleted(guess_members_button, True)
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The # Of Members This Anime Has On MyAnimeList", 
                                ("Members are users who added the anime to their list.\n"
                                 "EG: Death Note has over 4 million. Only 1 guess per person, no repeats.\n"
                                "+1 PT for closest guess. "
                                "+2 PTs if first 2 digits are correct."),
                                up_next=False)
        elif guessing_extra == "score":
            button_seleted(guess_score_button, True)
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The Score This Anime Has On MyAnimeList", 
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
            tags_array = split_array(get_random_tags())
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The " + tags + " This Anime Has", 
                                ("Guess until you get a tag wrong. +1 PT for each correct tag.\n\n"
                                "[" + "] [".join(tags_array[0]) + "]\n[" + "] [".join(tags_array[1])) + "]",
                                up_next=False)
        elif guessing_extra == "multiple":
            button_seleted(guess_multiple_button, True)
            data = currently_playing.get("data")
            titles = get_random_titles()
            toggle_coming_up_popup(True, 
                                ROUND_PREFIX + "Guess The Anime", 
                                ("Only one guess. +2 PTs if correct.\n\n"
                                f"[A] {titles[0]}\n[B] {titles[1]}\n"
                                f"[C] {titles[2]}\n[D] {titles[3]}"),
                                up_next=False)
    else:
        guessing_extra = None
        toggle_coming_up_popup(False, ROUND_PREFIX)

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
    if data:
        correct_title = get_display_title(data)
        titles = [correct_title]

        def get_similarity_score(anime):
            score = 0
            score += len(set(anime.get("genres", [])) & set(data.get("genres", [])))
            score += len(set(anime.get("themes", [])) & set(data.get("genres", [])))
            score += len(set(anime.get("studios", [])) & set(data.get("studios", [])))
            score += len(set(get_tags(anime)) & set(get_tags(data)))
            score -= max(0, (get_series_total(anime)-2))
            return score

        # Step 1: Filter and score
        similar_anime = [
            a for a in anime_metadata.values()
            if get_display_title(a) != correct_title
        ]

        # Step 2: Sort by similarity (descending)
        similar_anime = sorted(similar_anime, key=get_similarity_score, reverse=True)

        # Step 3: Take top 30 most similar
        top_similar = similar_anime[:30]

        # Step 4: Sort those by members (ascending)
        top_similar_sorted_by_members = sorted(top_similar, key=lambda a: int(a.get("members") or 0))

        # Step 5: Choose titles from the less popular ones
        for group in split_array(top_similar_sorted_by_members, amount - 1):
            titles.append(get_display_title(random.choice(group)))

        random.shuffle(titles)
        return titles
    else:
        return ["", "", "", ""]

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
    elif 0 <= index < len(playlist["playlist"]):
        same_index = index == playlist["current_index"]
        update_current_index(index)
        play_filename(playlist["playlist"][playlist["current_index"]], fullscreen=not same_index)
    else:
        messagebox.showinfo("Playlist Error", "Invalid playlist index.")
        return
    if playlist["current_index"]+1 >= len(playlist["playlist"]):
        get_next_infinite_track()
    up_next_text()
    root.after(3000, thread_prefetch_metadata)

all_themes_played = []
def play_filename(filename, fullscreen=True):
    global blind_round_toggle, peek_round_toggle, currently_playing, video_stopped, all_themes_played, previous_media
    filepath = directory_files.get(filename)  # Get file path from playlist
    if not filepath or not os.path.exists(filepath):  # Check if file exists
        print(f"File not found: {filepath}. Skipping...")
        blind_round_toggle = False
        peek_round_toggle = False
        play_video(playlist["current_index"] + skip_direction)  # Try playing the next video
        return
    currently_playing = {
        "type":"theme",
        "filename":filename,
        "data":get_metadata(filename, fetch=True)
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
    media = instance.media_new(filepath)
    previous_media = media
    player.set_media(media)
    global light_round_number, light_round_length
    if light_mode:
        append_lightning_history()
        if light_round_number%10 == 0:
            next_background_track()
        light_round_number = light_round_number + 1
        set_light_round_number("#" + str(light_round_number))
        light_round_length = light_modes[light_mode].get("length", light_round_length_default)
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
        toggle_coming_up_popup(False, "Lightning Round")
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
        if peek_round_toggle:
            peek_round_toggle = False
            button_seleted(peek_round_button, peek_round_toggle)
            toggle_peek_overlay()
        root.after(500, play_video_retry, 5, fullscreen)  # Retry playback
    if filename not in all_themes_played:
        all_themes_played.append(filename)
        update_playlist_name()
    save_config()

def thread_prefetch_metadata():
    threading.Thread(target=pre_fetch_metadata, daemon=True).start()

def play_video_retry(retries, fullscreen=True):
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
            play_video(playlist["current_index"] + skip_direction)
    if fullscreen and light_mode != 'mismatch':
        player.set_fullscreen(False)
        player.set_fullscreen(True)
        set_skip_direction(1)
    video_stopped = False

previous_media = None
def check_video_end():
    """Function to check if the current video has ended"""
    global video_stopped
    if player.is_playing() or video_stopped or autoplay_toggle == 2:
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
    if value != None:
        playlist["current_index"] = value
    if globals().get("current_entry"):
        current_entry.delete(0, tk.END)
        if playlist.get("infinite", False):
            current_entry.insert(0, "∞")
            out_of = len(directory_files) - len(cached_skipped_themes)
        else:
            current_entry.insert(0, str(playlist["current_index"]+1))
            out_of = len(playlist["playlist"])
        playlist_size_label.configure(text = "/" + str(out_of))
    if save:
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
            toggle_coming_up_popup(True, title, details, image, queue=True)
        else:
            play_video()
    else:
        unload_youtube_video()
    show_youtube_playlist(True)

def load_image_from_url(url, size=(400, 400)):
    """Loads an image from a URL, resizes it to fit one side of the box fully (maximizing size while preserving aspect ratio), centers it in a transparent box, and returns a Tkinter-compatible PhotoImage."""
    response = requests.get(url)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content)).convert("RGBA")

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

def unload_youtube_video():
    global youtube_queue
    if youtube_queue:
        toggle_coming_up_popup(False, youtube_queue.get('title'))
    youtube_queue = None

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
        player.set_fullscreen(True)
    else:
        root.after(1000, check_youtube_video_playing)

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
    elif light_mode in ['clues', 'song', 'synopsis', 'title', 'character', 'tags', 'episodes', 'names']:
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

# Function to play next video
skip_direction = 1
def set_skip_direction(dir):
    global skip_direction
    skip_direction = dir

def play_next():
    if playlist_loaded:
        play_video(playlist["current_index"])
    else:
        if playlist["current_index"] + 1 >= len(playlist["playlist"]):
            get_next_infinite_track()
        if playlist["current_index"] + 1 < len(playlist["playlist"]):
            play_video(playlist["current_index"] + 1)
    set_skip_direction(1)

def play_previous():
    """Function to play previous video"""
    if playlist["current_index"] - 1 >= 0:
        play_video(playlist["current_index"] - 1)
        set_skip_direction(-1)

def stop():
    """Function to stop the video"""
    global video_stopped, currently_playing, censor_bar
    video_stopped = True
    toggle_light_mode()
    clean_up_light_round()
    set_countdown()
    set_light_round_number()
    set_black_screen(False)
    toggle_title_popup(False)
    player.stop()
    player.set_media(None)  # Reset the media
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
last_error = None
last_error_count = 0
playing_next_error = False
def update_seek_bar():
    """Function to update the seek bar"""
    global last_vlc_time, projected_vlc_time, last_error, last_error_count, coming_up_queue, playing_next_error
    try:
        if player.is_playing():
            vlc_time = player.get_time()
            if vlc_time != last_vlc_time:
                last_vlc_time = vlc_time
                projected_vlc_time = vlc_time
            else:
                projected_vlc_time = projected_vlc_time + SEEK_POLLING * light_speed_modifier
            length = player.get_length()/1000
            time = projected_vlc_time/1000
            if manual_blind:
                set_progress_overlay(time, length)
            if peek_overlay and not light_round_started:
                gap = get_peek_gap(currently_playing.get("data"))
                progress = ((time+peek_modifier)%24/12)*100
                if progress >= 100:
                    direction = "right"
                    progress -= 100
                else:
                    direction = "down"
                toggle_peek_overlay(direction=direction, progress=progress, gap=gap)
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
                        if coming_up_queue:
                            toggle_coming_up_popup(True, title=coming_up_queue["title"], details=coming_up_queue["details"], image=coming_up_queue["image"], up_next=coming_up_queue["up_next"])
                            coming_up_queue = None
                    update_light_round(time)
                    apply_censors(time, length)
            update_progress_bar(projected_vlc_time, player.get_length())
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
        coming_up_window.configure(bg="black")

    # Title
    if not coming_up_title_label:
        coming_up_title_label = tk.Label(coming_up_window, font=("Arial", 40, "bold", "underline"), fg="white", bg="black")
        coming_up_title_label.pack(pady=(10, 0), padx=10)
    if up_next:
        title = "UP NEXT: " + title.upper() + "!"
    if title == coming_up_title_label.cget("text"):
        return
    coming_up_title_label.configure(text=title.upper())

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
    if blind_round_toggle:
        if peek_round_toggle:
            toggle_peek_round()
        toggle_coming_up_popup(True, "Blind Round", "Guess the anime from just the music.\nNormal rules apply.", queue=True)
    else:
        toggle_coming_up_popup(False, "Blind Round")

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

    if os.path.exists(CENSOR_JSON_FILE):
        with open(CENSOR_JSON_FILE, "r") as a:
            censor_list = json.load(a)
            print(f"Loaded censors for {len(censor_list)} files...")

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
    if censors_enabled and not mismatch_visuals:
        if check_file_censors(currently_playing.get('filename'), time, False):
            return
        elif length - time <= 1.2 and playlist["current_index"]+1 < len(playlist["playlist"]) and check_file_censors(os.path.basename(playlist["playlist"][playlist["current_index"]+1]), time, True):
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
    censor_found = False
    mute_found = False
    if file_censors != None:
        for censor in file_censors:
            if (not blind_enabled or censor.get("mute")) and (not is_title_window_up() or censor.get("nsfw")) and ((video_end and censor['start'] == 0) or (time >= censor['start'] and time <= censor['end'])):
                if not censor_used and not censor.get("mute"):
                    censor_used = True
                    censor_bar.attributes("-topmost", True)
                    if peek_overlay:
                        for i in range(2):
                            if peek_overlay[i]:
                                peek_overlay[i].lift()
                    lift_windows()
                    if censor_editor:
                        censor_editor.attributes("-topmost", True)
                if censor.get("mute"):
                    player.audio_set_mute(True)
                    mute_found = True
                else:
                    censor_bar.geometry(str(int(screen_width*(censor['size_w']/100))) + "x" + str(int(screen_height*(censor['size_h']/100))))
                    censor_bar.configure(bg=(censor.get("color") or get_image_color()))
                    set_window_position(censor_bar, censor['pos_x'], censor['pos_y'])
                censor_found = True

    if not censor_found and censor_editor:
        censor_editor.attributes("-topmost", False)

    if not mute_found and not light_round_started:
        player.audio_set_mute(disable_video_audio)

    return censor_found

def lift_windows():
    if root.attributes("-topmost"):
        root.lift()
    for window in [title_window, progress_bar, coming_up_window, censor_editor]:
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
    for button in [toggle_censor_bar_button, popout_buttons_by_name.get(toggle_censor_bar_button, toggle_censor_bar_button)]:
        button.configure(text="[C]ENSOR(" + str(len(censor_list.get(currently_playing.get("filename",""), {}))) +")")

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

current_censors = {}
censor_editor = None
censor_entry_widgets = []
def open_censor_editor(refresh=False):
    global current_censors, censor_editor, censor_entry_widgets
    
    def censor_editor_close():
        global censor_editor, censor_entry_widgets
        button_seleted(edit_censors_button, False)
        edit_censors_button.configure(text="➕")
        censor_entry_widgets = []
        censor_editor.destroy()
        censor_editor = None

    filename = currently_playing.get("filename")
    if filename:
        current_censors = copy.deepcopy(censor_list.get(filename, []))
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
        headers = ["SIZE", "POSITION", "START", "END", "COLOR", "NSFW", "ACTIONS"]
        for col, header in enumerate(headers):
            tk.Label(censor_editor, text=header, font=font_big, bg=BACKGROUND_COLOR, fg=fg_color).grid(row=0, column=col, padx=8, pady=6)
        
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
        for widgets in censor_entry_widgets:
            for widget in widgets:
                widget.destroy()
        censor_entry_widgets.clear()

        for idx, censor in enumerate(current_censors):
            row_widgets = []

            # Frame for Size
            size_frame = tk.Frame(censor_editor, bg=BACKGROUND_COLOR)
            if not censor.get("mute"):
                size_var = tk.StringVar(value=f"{censor['size_w']}x{censor['size_h']}")
                pos_var = tk.StringVar(value=f"{censor['pos_x']}x{censor['pos_y']}")
                size_entry = tk.Entry(size_frame, textvariable=size_var, width=12, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color)
                size_entry.pack(side="left")
                tk.Button(size_frame, text="🎯", width=3, font=font_big, bg=bg_color, fg=fg_color, command=lambda sv=size_var, pv=pos_var: pick_target_func(sv, pv)).pack(side="left")
            size_frame.grid(row=idx+1, column=0, padx=(6, 0), pady=4)

            # Frame for Position
            pos_frame = tk.Frame(censor_editor, bg=BACKGROUND_COLOR)
            if not censor.get("mute"):
                pos_entry = tk.Entry(pos_frame, textvariable=pos_var, width=12, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color)
                pos_entry.pack(side="left")
            pos_frame.grid(row=idx+1, column=1, padx=(0, 6), pady=4)

            # Frame for Start and End Times
            def build_time_frame(var, row, col):
                frame = tk.Frame(censor_editor, bg=BACKGROUND_COLOR)
                tk.Button(frame, text="-", width=3, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(v.get() - 0.1, 1))).pack(side="left")
                tk.Entry(frame, textvariable=var, width=6, font=font_big, justify="center", bg=bg_color, fg=fg_color, insertbackground=fg_color).pack(side="left")
                tk.Button(frame, text="+", width=3, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(v.get() + 0.1, 1))).pack(side="left")
                tk.Button(frame, text="NOW", width=5, font=font_big, bg=bg_color, fg=fg_color, command=lambda v=var: v.set(round(current_time_func(), 1))).pack(side="left")
                frame.grid(row=row, column=col, padx=6, pady=4)
                return frame

            start_var = tk.DoubleVar(value=censor['start'])
            end_var = tk.DoubleVar(value=censor['end'])
            start_frame = build_time_frame(start_var, idx+1, 2)
            end_frame = build_time_frame(end_var, idx+1, 3)

            # Frame for Color and Buttons
            def remove_color(label):
                label.config(bg="#333", text="AUTO")
                save_to_current()

            color_frame = tk.Frame(censor_editor, bg=BACKGROUND_COLOR)
            if not censor.get("mute"):
                color = censor.get("color")
                color_box = tk.Label(color_frame, text="AUTO" if not color else "", width=8, font=font_big, bg=color if color else "#333", fg=fg_color, relief="groove")
                color_box.pack(side="left")
                tk.Button(color_frame, text="PICK", width=5, font=font_big, bg=bg_color, fg=fg_color, command=lambda b=color_box: pick_color_func(b)).pack(side="left", padx=2)
                tk.Button(color_frame, text="X", width=2, font=font_big, bg=bg_color, fg=fg_color, command=lambda c=color_box: remove_color(c)).pack(side="left")
            else:
                mute_label = tk.Label(color_frame, text="MUTE CENSOR", width=16, font=font_big, justify="center", bg=bg_color, fg=fg_color, highlightbackground="white", highlightthickness=2)
                mute_label.pack(side="left")
            color_frame.grid(row=idx+1, column=4, padx=6, pady=4)

            # NSFW Toggle Button
            def add_nsfw_toggle_button(censor, parent, row, column=5):
                nsfw_var = censor.get("nsfw")

                def toggle_nsfw():
                    nsfw_button.var = not nsfw_button.var
                    update_nsfw_button()

                def update_nsfw_button():
                    if nsfw_button.var:
                        nsfw_button.config(text="✓ NSFW", bg="#880000")
                    else:
                        nsfw_button.config(text="✗ SFW", bg="#444444")

                nsfw_button = tk.Button(parent, text="", command=toggle_nsfw, font=font_big, width=8, height=1, fg="white", activeforeground="white", activebackground="#333", bd=0, relief="flat", bg="#444444")
                nsfw_button.grid(row=row, column=column, padx=6, pady=4)
                nsfw_button.var = nsfw_var  # Optional, to match original 

                update_nsfw_button()
                return nsfw_button
            
            nsfw_button = add_nsfw_toggle_button(censor, censor_editor, row=idx+1)

            # Delete Button
            test_button = tk.Button(censor_editor, text="▶TEST", command=lambda c=idx: test_censor_playback(c), font=font_big, bg="#226622", fg="white", activebackground="#2a8a2a", bd=0, relief="raised", width=6)
            test_button.grid(row=idx+1, column=6, padx=6, pady=4)
            delete_button = tk.Button(censor_editor, text="DELETE", bg=bg_color, fg="red", width=8, font=font_big, command=lambda i=idx: delete_censor(i))
            delete_button.grid(row=idx+1, column=7, padx=6, pady=4)
            row_widgets.extend([size_frame, pos_frame, start_frame, end_frame, color_frame, nsfw_button, delete_button, test_button])
            censor_entry_widgets.append(row_widgets)

    def test_censor_playback(censor):
        save_to_current()
        try:
            start = float(current_censors[censor].get("start", 0))
            start = max(0, (start - 1)*1000)  # Go back 1 second, minimum 0
            player.set_time(int(start))
            player.play()
        except Exception as e:
            print(f"Error playing censor preview: {e}")

    def delete_censor(index):
        if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this censor?"):
            save_to_current()
            del current_censors[index]
            refresh_ui()

    def add_new_censor():
        save_to_current()
        current_censors.append({
            "size_w": 100.00, "size_h": 100.00,
            "pos_x": 0.0, "pos_y": 0.0,
            "start": round(current_time_func(), 1), "end": 0.0,
            "color": None, "nsfw": False
        })
        refresh_ui()

    def add_new_mute():
        save_to_current()
        current_censors.append({
            "mute":True,
            "start": round(current_time_func(), 1), "end": 0.0,
            "nsfw": False
        })
        refresh_ui()
    def save_to_current():
        for i, widgets in enumerate(censor_entry_widgets):
            try:
                if current_censors[i].get("mute", False):
                    current_censors[i] = {
                        "mute": True,
                        "start": float(widgets[2].winfo_children()[1].get()),
                        "end": float(widgets[3].winfo_children()[1].get()),
                        "nsfw": widgets[5].var
                    }
                else:
                    size_parts = widgets[0].winfo_children()[0].get().split("x")
                    pos_parts = widgets[1].winfo_children()[0].get().split("x")
                    current_censors[i] = {
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
                messagebox.showerror("Save Error", f"Error saving row {i+1}: {e}")
                return

    def save_all():
        save_to_current()
        save_censor_func()
        save_censors_button.configure(text="SAVED!")
        root.after(300, lambda: save_censors_button.configure(text="SAVE CENSOR(S)"))

    tk.Button(censor_editor, text="ADD NEW CENSOR", width=20, font=font_big, bg=bg_color, fg=fg_color, command=add_new_censor).grid(row=999, column=0, columnspan=2, pady=12)
    tk.Button(censor_editor, text="ADD NEW MUTE", width=20, font=font_big, bg=bg_color, fg=fg_color, command=add_new_mute).grid(row=999, column=2, columnspan=2, pady=12)
    save_censors_button = tk.Button(censor_editor, text="SAVE CENSOR(S)", width=19, font=font_big, bg=bg_color, fg=fg_color, command=save_all)
    save_censors_button.grid(row=999, column=4, columnspan=2, pady=12)

    refresh_ui()

# =========================================
#            *TAG/FAVORITE FILES
# =========================================

def toggle_theme(playlist_name, button=None, filename=None, quite=False):
    """Toggles a theme in a specified playlist (e.g., Tagged Themes, Favorite Themes)."""
    if not filename:
        if currently_playing.get("filename"):
            filename = currently_playing.get("filename")
        else:
            return
        
    playlist_path = os.path.join(PLAYLISTS_FOLDER, f"{playlist_name}.json")
    # Load or initialize the playlist
    if os.path.exists(playlist_path):
        with open(playlist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            theme_list = data.get("playlist", [])
    else:
        data = copy.deepcopy(BLANK_PLAYLIST)
        data["name"] = playlist_name
        theme_list = data["playlist"]

    type_string = "saved to"
    if filename in theme_list:
        # Remove theme
        theme_list.remove(filename)
        if button:
            button_seleted(button, False)
        type_string = "removed from"
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
        if not quite:
            print(f"{filename} {type_string} playlist '{playlist_name}'.")

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

def check_missing_artists():
    playlist["name"] = "Missing Artists"
    try:
        os.remove(os.path.join(PLAYLISTS_FOLDER, f"{playlist["name"]}.json"))
    except Exception as e:
        print(e)
        pass
    for filename in directory_files:
        data = get_metadata(filename)
        for theme in data.get("songs",[]):
            if theme.get("slug") == data.get("slug") and theme.get("artist") == []:
                toggle_theme(playlist["name"], favorite_button, filename)

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
        title = get_display_title(data)
        max_length = 38  # includes space before slug
        if len(title) > 37:
            keep = 34  # number of characters excluding "..."
            half = keep // 2
            title = title[:half] + "..." + title[-(keep - half):]
        return title + " " + data.get("slug")
    else:
        return value

def play_video_from_last(index):
    if last_themes_listed:
        play_video_from_filename(last_themes_listed[index])

def show_playlist(update = False):
    show_list("playlist", right_column, convert_playlist_to_dict(playlist["playlist"]), get_title, play_video, playlist["current_index"], update)

def remove(update = False):
    show_list("remove", right_column, convert_playlist_to_dict(playlist["playlist"]), get_title, remove_theme, playlist["current_index"], update)

def convert_playlist_to_dict(playlis):
    return {f"{video}_{i}": video for i, video in enumerate(playlis)}

def remove_theme(index):
    global playlist
    confirm = messagebox.askyesno("Remove Theme", f"Are you sure you want to remove '{playlist["playlist"][index]}' from '{playlist["name"]}'?")
    if not confirm:
        return  # User canceled
    del playlist["playlist"][index]
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
def list_set_loaded(type):
    global list_loaded
    list_loaded = type
    for button in list_buttons:
        if button.get('button') and globals().get(button.get('button')):
            button_seleted(globals().get(button.get('button')), list_loaded == button.get('label'))

def list_unload(column):
    list_set_loaded(None)
    if currently_playing.get("data"):
        update_extra_metadata(currently_playing.get("data"))
    else:
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
        if (list_index-100 <= index <= list_index+100):
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
    add_single_line(right_column, "ENABLE SHORTCUTS", "[']", False)
    add_single_line(right_column, "INFO", "[I]", False)
    add_single_line(right_column, "DOCK", "[D]")
    add_single_line(right_column, "PLAY/PAUSE", "[SPACE BAR]", False)
    add_single_line(right_column, "STOP", "[ESC]")
    add_single_line(right_column, "PREVIOUS/NEXT", "[⬅]/[➡]", False)
    add_single_line(right_column, "FULLSCREEN", "[TAB]")
    add_single_line(right_column, "SEEK TO PART", "[0]-[9]", False)
    add_single_line(right_column, "SEEK or MODE", "[-]/[+]")
    add_single_line(right_column, "MUTE VIDEO", "[M]", False)
    add_single_line(right_column, "SCROLL UP/DOWN", "[⬆]/[⬇]")
    add_single_line(right_column, "TAG THEME", "[T]", False)
    add_single_line(right_column, "FAVORITE THEME", "[*]")
    add_single_line(right_column, "REFETCH METADATA", "[F]", False)
    add_single_line(right_column, "REROLL NEXT", "[R]")
    add_single_line(right_column, "SHOW PLAYLIST", "[P]", False)
    add_single_line(right_column, "LOAD PLAYLIST", "[O]")
    add_single_line(right_column, "LIST UP/DOWN", "[⬆]/[⬇]", False)
    add_single_line(right_column, "LIST SELECT", "[ENTER]")
    add_single_line(right_column, "SEARCH/QUEUE", "[S]", False)
    add_single_line(right_column, "CANCEL SEARCH", "[ESC]")
    add_single_line(right_column, "", "BONUS?", False)
    add_single_line(right_column, "YEAR", "[G]", False)
    add_single_line(right_column, "MEMBERS", "[H]", False)
    add_single_line(right_column, "SCORE", "[J]")
    add_single_line(right_column, "TAGS", "                       [N]", False)
    add_single_line(right_column, "MULTIPLE", "[U]")
    add_single_line(right_column, "TOGGLE BLIND", "[BKSP]", False)
    add_single_line(right_column, "TOGGLE PEEK", "[=]")
    add_single_line(right_column, "BLIND/PEEK ROUND", "[B]", False)
    add_single_line(right_column, "WIDEN PEEK", "[ _ ]")
    add_single_line(right_column, "SHOW YOUTUBE PLAYLIST", "[Y]")
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

def on_closing():
    pass

# =========================================
#            *POPOUT CONTROLS
# =========================================

popout_buttons_by_name = {}  # Global mapping
popout_controls = None
def create_popout_controls(columns=5, title="Popout Controls"):
    global popout_controls
    def on_popout_close():
        global popout_controls
        button_seleted(popout_controls_button, False)
        popout_buttons_by_name.clear()
        popout_controls.destroy()
        popout_controls = None
        
    if popout_controls:
        on_popout_close()
        return
    
    popout_controls = tk.Toplevel()
    popout_controls.title(title)
    popout_controls.configure(bg=BACKGROUND_COLOR)
    popout_controls.geometry("850x515")
    popout_controls.protocol("WM_DELETE_WINDOW", on_popout_close)

    # Group them by category
    button_groups = {
        "POPOUT CONTROLS": [
            (dock_button, "DOCK\nPLAYER", False), 
            (tag_button, "TAG", True),
            (favorite_button, "FAVORITE", True),
            (info_button, "INFORMATION\nPOP-UP", False, 2)
        ],
        "BLIND/PEEK CONTROLS": [
            (blind_button, "BLIND\nSCREEN", False, 1), 
            (blind_round_button, "BLIND NEXT", True, 1),
            (peek_button, "PEEK\nSCREEN", False, 1), 
            (widen_peek_button, "WIDEN PEEK", True, 1), 
            (peek_round_button, "PEEK NEXT", True, 1)
        ],
        "BONUS QUESTIONS": [
            (guess_year_button, "YEAR", True), 
            (guess_members_button, "MEMBERS", True),
            (guess_score_button, "SCORE", True),
            (guess_tags_button, "TAGS", True), 
            (guess_multiple_button, "MULTIPLE", True)
        ],
        "LIGHTNING ROUNDS": [
            ("DROPDOWN", "MODE SELECT", 2),  # ("marker", label, colspan)
            (start_light_mode_button, "START", True),
            (variety_light_mode_button, "VARIETY", True, 2)],
        "MISC TOGGLES": [
            (toggle_censor_bar_button, "", True, 2), 
            (mute_button, "MUTE", False),
            (end_button, "END SESSION STATS", False, 2)]
    }
    button_font = ("Helvetica", 20, "bold")  # Double-size font

    row = 0
    for group_name, button_entries in button_groups.items():
        if row > 0:
            # Group label
            group_label = tk.Label(popout_controls, text=group_name, font=("Helvetica", 10, "bold"))
            group_label.grid(row=row, column=0, columnspan=columns, sticky="w", padx=10, pady=(0, 2))
            row += 1
        col = 0  # Start at column 0

        for entry in button_entries:
            if isinstance(entry[0], str) and entry[0] == "DROPDOWN":
                _, label_text, colspan = entry

                if col + colspan > columns:
                    row += 1
                    col = 0

                # Create the dropdown here
                dropdown = ttk.Combobox(
                    popout_controls,
                    values=[display for _, display in light_mode_options],
                    font=button_font,
                    height=len(light_mode_options),
                    style="Black.TCombobox",
                    state='readonly'  # This ensures full-box click behavior
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
                dropdown.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=2, pady=1)
                dropdown.bind("<<ComboboxSelected>>", on_popout_dropdown_change)
                col += colspan
                popout_buttons_by_name[light_dropdown] = dropdown
                continue

            # Unpack entry with default colspan = 1
            if len(entry) == 4:
                original_button, label_text, show_original, colspan = entry
            else:
                original_button, label_text, show_original = entry
                colspan = 1

            # Move to next row if not enough space left in this row
            if col + colspan > columns:
                row += 1
                col = 0

            # Pull original attributes
            btn_fg = original_button.cget("fg")
            btn_bg = original_button.cget("bg")
            btn_cmd = original_button.cget("command")
            original_text = original_button.cget("text")

            # Compose label
            full_label = ""
            if show_original:
                full_label += original_text
                if label_text:
                    full_label += "\n"
            full_label += label_text

            # Create and place the button
            clone = tk.Button(
                popout_controls,
                text=full_label,
                fg=btn_fg,
                bg=btn_bg,
                command=btn_cmd,
                font=button_font,
                wraplength=180 * colspan,
                justify="center"
            )
            clone.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=2, pady=1)

            popout_buttons_by_name[original_button] = clone

            col += colspan  # Now move the column index after placing

        row += 1  # Add space between groups
    button_seleted(popout_controls_button, True)
    # Allow columns to resize
    for i in range(columns):
        popout_controls.grid_columnconfigure(i, weight=1)


# =========================================
#                 *GUI SETUP
# =========================================

BACKGROUND_COLOR = "gray12"
WINDOW_TITLE = "Guess the Anime! Playlist Tool"
root = tk.Tk()
root.title(WINDOW_TITLE)
root.geometry("1200x550")
root.configure(bg=BACKGROUND_COLOR)  # Set background color to black

def blank_space(row, size=0):
    space_label = tk.Label(row, text="", bg=BACKGROUND_COLOR, fg="white")
    space_label.pack(side="left", padx=size)

def create_button(frame, label, func, add_space=False, enabled=False, help_title="", help_text=""):
    """Creates a button with optional spacing and right-click help functionality."""
    bg = HIGHLIGHT_COLOR if enabled else "black"
    
    # Create the button
    button = tk.Button(frame, text=label, command=func, bg=bg, fg="white")
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

def scan_directory():
    global directory_entry, directory_files, directory
    if not directory:
        return
    directory_files = {}
    if globals().get("directory_entry"):
        directory_entry.delete(0, tk.END)
        directory_entry.insert(0, directory)
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith((".mp4", ".webm", ".mkv")):
                directory_files[file] = os.path.join(root, file)
    save_config()


def empty_playlist():
    global playlist
    confirm = messagebox.askyesno("Clear Playlist", f"Are you sure you want to create an empty playlist?")
    if not confirm:
        return  # User canceled
    playlist = copy.deepcopy(BLANK_PLAYLIST)
    update_playlist_name()
    create_first_row_buttons()
    show_playlist(True)

# Generate playlist button
def generate_playlist_button():
    global playlist
    scan_directory()
    confirm = messagebox.askyesno("Create Playlist", f"Are you sure you want to create a new playlist with all {len(directory_files)} files in the directory?")
    if not confirm:
        return  # User canceled
    playlist = copy.deepcopy(BLANK_PLAYLIST)
    playlist["playlist"] = generate_playlist()
    create_first_row_buttons()
    update_current_index(0)
    update_playlist_name()
    save_config()
    show_playlist(True)
    if not playlist["playlist"]:
        messagebox.showwarning("Playlist Error", "No video files found in the directory.")

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
    popout_controls_button = create_button(first_row_frame, "🗖", create_popout_controls, True, 
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
    directory_entry = tk.Entry(first_row_frame, width=33, bg="black", fg="white", insertbackground="white", textvariable=directory)
    directory_entry.pack(side="left")
    directory_entry.insert(0, directory)

    global generate_button
    generate_button = create_button(first_row_frame, "CREATE", generate_playlist_button,
                                help_title="CREATE PLAYLIST",
                                help_text=("This creates a playlist using all videos "
                                "found in the directory.\n\nIf this is your first time "
                                "creating a playlist with these files, and you want "
                                "to be able to use all the other playlist functions, "
                                "you'll need to fetch the metadata for all the files. "
                                "You can do this by hitting the '?' button next to the "
                                "RE[F]ETCH button. It may take awhile "
                                "depending on how many themes you have.\n\n"
                                "You will be asked to confirm when creating."))
    global empty_button
    empty_button = create_button(first_row_frame, "❌", empty_playlist, True,
                                help_title="EMPTY PLAYLIST",
                                help_text=("This resets you to a blank playlist. "
                                "This is only if you want to manually add themes to the "
                                "playlist using the SEARCH+ button. That's not really what "
                                "this application was made for, so it may be a hassle "
                                "depending on how many themes you want to add to the list."))
    global toggle_infinite_button
    toggle_infinite_button = create_button(first_row_frame, "∞", toggle_infinite_playlist, False, playlist.get("infinite", False), 
                                help_title="INFINITE PLAYLIST TOGGLE",
                                help_text="When enabled, will allow the playlist to play infinitely. Tracks are chosen from all tracks in directory "
                                "based on popularity and season groups. Favorited tracks get a boost, and tagged tracks will not be picked. "
                                "Tracks from the last 3 seasons also get a boost.\n\n"
                                "Filters cannot be used(yet) and sorting/shuffling is disabled.\n\n"
                                "Difficulty can be chosen, limiting the groups to certain popularity levels. For example, 'VERY EASY' will only "
                                "pick tracks from MALs top 500 anime, rotating from the top 100, 100-250, and 250-500 every 3 entries. "
                                "'NORMAL' will pick from the top 250, 250-750, then 1000+ every 3 entries.")
    toggle_infinite_button.bind("<Button-2>", test_infinite_playlist)

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
                                style="Black.TCombobox")
        difficulty_dropdown.pack(side="left")
        difficulty_dropdown.bind("<<ComboboxSelected>>", select_difficulty)

    global show_playlist_button
    show_playlist_button = create_button(first_row_frame, "[P]LAYLIST", show_playlist, False,
                                help_title="VIEW [P]LAYLIST/[P]LAY HISTORY (Shortcut Key = 'p')",
                                help_text=("List all themes in the playlist. It will scroll to whichever "
                                "theme the current index is at. Select a theme to play it immediately "
                                "and set the current index to it.\n\nAs with all lists, it loads buttons "
                                "to select the entry, but for the playlist it may be quite a few buttons. "
                                "It usually loads quickly, but may take a second to clear."))
    # if not playlist.get("infinite", False):
    global remove_button
    remove_button = create_button(first_row_frame, "❌", remove, True,
                                help_title="REMOVE THEME",
                                help_text=("Remove a theme from the playlist. There is a confirmation "
                                "dialogue after selecting.\n\nIt may be a bit slow dpending on how many "
                                "themes you have added or want to delete."))

    global go_button
    go_button = create_button(first_row_frame, "GO TO:", go_to_index,
                                help_title="GO TO INDEX",
                                help_text=("Go to the index in the text box of the playlist. "
                                "It will play it immediately and set the current index."))
    global current_entry
    current_entry = tk.Entry(first_row_frame, width=5, bg="black", fg="white", insertbackground="white", justify='center')
    if playlist.get("infinite", False):
        current_entry.insert(0, "∞")
    else:
        current_entry.insert(0, str(playlist["current_index"]+1))
    current_entry.pack(side="left")

    global playlist_size_label
    if playlist.get("infinite", False):
        out_of = len(directory_files)
    else:
        out_of = len(playlist["playlist"])
    playlist_size_label = tk.Label(first_row_frame, text="/" + str(out_of), bg=BACKGROUND_COLOR, fg="white")
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
    load_button = create_button(first_row_frame, "L[O]AD", load,
                                help_title="L[O]AD PLAYLIST (Shortcut Key = 'o')",
                                help_text=("Load a playlist from your list of saved playlists.\n\n"
                                "This will not interrupt the currently playing theme, but will load the playlist "
                                "and set the current index.\n\nPlaylists are stored in the playlists/ folder.\n\n"
                                "When shortcuts are enabled, the currently loaded playlist will auto save. This is "
                                "so I can load up another playlist, then go back while keeping the position. I don't "
                                "have a shortcut for saving, but if you were not using shortcuts you could just save manually "
                                "before loading a playlist if you want to."))
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
                                "The values are taken from the metadata files, so this will take awhile to grab all "
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

    if not playlist.get("infinite", False):
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
                                    "This is a completly random shuffle. For a weighted shuffle, hit the ⚖️ button "
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

    global search_button
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
    global add_search_button
    add_search_button = create_button(first_row_frame, "➕", search_add, True,
                                help_title="SEARCH ADD",
                                help_text=("The same as the SEARCH, but will add the theme to the playlist "
                                            "instead of just queueing it.\n\nThis was more of an after thought feature "
                                            "just in case you want to add some themes that were maybe removed, or added "
                                            "later. It would be kinda slow with the dialogue popping up each time, but it "
                                            "may be fast with shortcuts enabled, as described on the SEARCH button. You could "
                                            "also use this to add tracks to an empty playlist to create your own from scratch."))
    
    global stats_button
    stats_button = create_button(first_row_frame, "📊", display_theme_stats_in_columns, True,
                                help_title="THEME DIRECTORY/STATS",
                                help_text=("Shows detailed stats of themes in directory."))

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
second_row_frame.pack(pady=(0,0))

info_button = create_button(second_row_frame, "[I]NFO", toggle_info_popup,
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

tag_button = create_button(second_row_frame, "❌", tag, False,
                              help_title="[T]AG THEME (Shortcut Key = 't')",
                              help_text=("Adds the current;y playing theme to a 'Tagged Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nThe purpose is to tag "
                                         "themes you may need to check out later for various reasons. "
                                         "Like adding censors, updating the theme, or even deleting it. "
                                         "Just a reminder."))
favorite_button = create_button(second_row_frame, "❤", favorite, True,
                              help_title="FAVORITE THEME (Shortcut Key='*')",
                              help_text=("Adds the current;y playing theme to a 'Favorite Themes' playlist. Clicking again "
                                         "will remove it from the playlist.\n\nJust a way to keep track of your favorite themes."))

refetch_metadata_button = create_button(second_row_frame, "RE[F]ETCH", refetch_metadata,
                              help_title="RE[F]ETCH THEME METADATA (Shortcut Key = 'f')",
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

peek_button = create_button(second_row_frame, "PEEK", toggle_peek, False,
                              help_title="PEEK OVERLAY (Shortcut Key = '=')",
                              help_text=("Covers the screen except for a small peek window that moves across the screen."))
widen_peek_button = create_button(second_row_frame, "⇔", widen_peek, False,
                              help_title="WIDEN PEEK OVERLAY (Shortcut Key = '_')",
                              help_text=("Widens the gap of the peek window."))
peek_round_button = create_button(second_row_frame, "👀", toggle_peek_round, True,
                              help_title="PEEK ROUND (Shortcut Key = 'b','b')",
                              help_text=("Enables the next video to play as a 'Peek Round'. A peek round plays normally, "
                                         "but will cover most of the screen at the start, only showing a small moving window. "
                                         "The peek can be removed with the normal PEEK toggle."))

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
guess_tags_button = create_button(second_row_frame, "🔖", lambda: guess_extra("tags"), False,
                              help_title="[G]UESS TAGS (Shortcut Key = 'g','g')",
                              help_text=("Displays a pop-up at the top informing a player to guess the tags. "
                                         "It also lists the rules. Opening the Info Popup or toggling again will remove it."))
guess_multiple_button = create_button(second_row_frame, "４", lambda: guess_extra("multiple"), True,
                              help_title="GUESS MUTIPLE (Shortcut Key = 'h','h')",
                              help_text=("Displays a pop-up at the top informing a player to guess the anime from a multiple choice. "
                                         "It also lists the rules. Opening the Info Popup or toggling again will remove it."))

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
                        width=14,
                        height=len(light_mode_options),
                        state="readonly",
                        style="Black.TCombobox")
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
variety_light_mode_button = create_button(second_row_frame, "🎲", lambda: toggle_light_mode("variety"), True,
                              help_title="[V]ARIETY LIGHTNING ROUND (Shortcut Key = 'v')",
                              help_text=("Lightning Round varient using the following rules:\n\n" + light_modes["variety"]["desc"] +
                                         "\n\nThis mode ensures no round is repeated consecutively, and picks rounds "
                                         "taking the show's popularity into account. So you aren't likely to get a Clues round "
                                         "unless a quite popular show appears."))

variety_light_mode_button.bind("<Button-2>", test_variety_distrbution)

show_youtube_playlist_button = create_button(second_row_frame, "[Y]OUTUBE", show_youtube_playlist, True,
                              help_title="[Y]OUTUBE VIDEOS (Shortcut Key = 'y')",
                              help_text=("Lists downloaded youtube videos to queue up.\n\nVideos are downloaded on startup "
                                         "based on the youtube_links.txt file in the files/ folder. The downloads are stored in the "
                                         "youtube/ folder and deleted when removed from the youtube_links.txt file. All videos are "
                                         "also listed in the youtube_archive.txt file just to keep track of videos downloaded.\n\n"
                                         "Videos are queued with a UP NEXT popup when selected, and will play after the current theme. "
                                         "Only one video may be queued at a time, and selecting the same video will unqueue it."))

toggle_censor_bar_button = create_button(second_row_frame, "[C]ENSOR(0)", toggle_censor_bar, False, enabled=censors_enabled,
                              help_title="TOGGLE [C]ENSOR BARS (Shortcut Key = 'c')",
                              help_text=("Toggle censor bars. These are pulled from the censors.json file in the files/ "
                                         "folder. You can add these using the [➕] button next to this one.\n\n"
                                         "The point of this feature is to mainly block out titles that show up too early, "
                                         "since this is a trivia program. They always assume the video is fullscreen, on "
                                         "the main monitor, so it will be weird if you try playing in a window. I would have disabled them "
                                         "when vlc isn't fulscreen, but checking that isn't reliable."))
edit_censors_button = create_button(second_row_frame, "➕", open_censor_editor, True,
                              help_title="CENSORS EDITOR",
                              help_text=("Opens an interface for editing censors. Press [ADD NEW CENSOR] to add one. Heres's an explanation of each field."
                                         "\n\nSIZE/POSITION: The size/position of the censor box, in percent of screen. "
                                         "Use the [🎯] button to draw a censor box, and the SIZE/POSITION will be filled."
                                         "\n\nSTART/END: Start/end time censor bos will appear. Use the [NOW] button to set it to the player's current time. "
                                         "Use the [-]/[+] to adjust by 0.1 sec. The end time can usually be exact, but the start need to be a bit before to account for the time to pop up."
                                         "\n\nCOLOR: Color of censor box. Will automatically pick the average color fo the screen. Use [PICK] to select a specific color from the screen. "
                                         " Use [X] to rset back to AUTO."
                                         "\n\nNSFW: Used to mark a censor as NSFW. These censors will appear even when the Information Pop-up is up."
                                         "\n\nUse [TEST] to play the video from a second before the censor start time to test it. Censors will not appear until the [SAVE CENSOR(S)] button "
                                         "is pressed. This must be pressed againa fter every change to have it reflect. To delete censors, use the [DELETE] button. this will also only save if the "
                                         "[SAVE CENSOR(S)] button is pressed. Lastly, censors are all linked to the filename."))

toggle_progress_bar_button = create_button(second_row_frame, "BAR", toggle_progress_bar, True, enabled=progress_bar_enabled,
                              help_title="TOGGLE PROGRESS BAR OVERLAY",
                              help_text=("This toggles a progress bar overlay for the current time for the theme.\n\n"
                                         "It's pretty thin, and meant to be subtle as to not obstruct the theme."))

mute_button = create_button(second_row_frame, "[M]UTE", toggle_mute, True,
                              help_title="[M]UTE THEME AUDIO (Shortcut Key = 'm')",
                              help_text=("Toggles muting the video audio."))

toggle_disable_shortcuts_button = create_button(second_row_frame, "ENABLE", toggle_disable_shortcuts,
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

info_panel = tk.Frame(root, bg="black")
info_panel.pack(fill="both", expand=True, padx=10, pady=5)

# Left Column
left_column = tk.Text(info_panel, height=20, width=40, bg="black", fg="white",
                      insertbackground="white", state=tk.DISABLED,
                      selectbackground=HIGHLIGHT_COLOR, wrap="word")
left_column.pack(side="left", fill="both", expand=True)

# Middle Column
middle_column = tk.Text(info_panel, height=20, width=40, bg="black", fg="white",
                        insertbackground="white", state=tk.DISABLED,
                        selectbackground=HIGHLIGHT_COLOR, wrap="word")
middle_column.pack(side="left", fill="both", expand=True)

# === RIGHT COLUMN CONTAINER ===
right_column_container = tk.Frame(info_panel, bg="black")
right_column_container.pack(side="left", fill="both", expand=True)

# Top Shorter Column (e.g., header, stats, etc.)
right_top = tk.Text(right_column_container, height=0, width=40, bg="black", fg="white",
                    insertbackground="white", state=tk.DISABLED,
                    selectbackground=HIGHLIGHT_COLOR, wrap="word")
right_top.pack(fill="x")

# Main Right Column
right_column = tk.Text(right_column_container, height=20, width=40, bg="black", fg="white",
                       insertbackground="white", state=tk.DISABLED,
                       selectbackground=HIGHLIGHT_COLOR, wrap="word")
right_column.pack(fill="both", expand=True)


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
volume_slider.pack(side="left", padx=(10, 5))

play_pause_button = tk.Button(controls_frame, text="⏯", command=play_pause, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
play_pause_button.pack(side="left", padx=0)

stop_button = tk.Button(controls_frame, text="⏹", command=stop, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
stop_button.pack(side="left", padx=0)

previous_button = tk.Button(controls_frame, text="⏮", command=play_previous, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
previous_button.pack(side="left", padx=0)

next_button = tk.Button(controls_frame, text="⏭", command=play_next, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2)
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

autoplay_button = tk.Button(controls_frame, text="🔁", command=toggle_autoplay, bg="black", fg="white", font=("Arial", 30, "bold"), border=0, width=2, anchor="center", justify="center")
autoplay_button.pack(side="left", padx=0, pady=(0,15))

# Seek bar
seek_bar = tk.Scale(controls_frame, from_=0, to=1000, orient=tk.HORIZONTAL, command=seek, length=2000, resolution=0.1, bg="black", fg="white")
seek_bar.pack(side="left", fill="x", padx=(5,10))

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
right_top.tag_configure("bold", font=("Arial", 12, "bold"), foreground="white")
right_top.tag_configure("white", foreground="white", font=("Arial", 12))

list_buttons = [
    {"button":"show_playlist_button", "label":"playlist", "func":show_playlist},
    {"button":None, "label":"field_list", "func":show_field_themes},
    {"button":"remove_button", "label":"remove", "func":remove_theme},
    {"button":"load_button", "label":"load_playlist", "func":load},
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
        if disable_shortcuts:
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
                    if peek_overlay:
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
                    if list_loaded:
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
                    if not peek_round_toggle and not blind_round_toggle:
                        toggle_blind_round()
                    else:
                        toggle_peek_round()
                elif key.char == '=':
                    toggle_peek()
                elif key.char == '_':
                    widen_peek()
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
                    guess_extra("year")
                elif key.char == 'h':
                    guess_extra("members")
                elif key.char == 'j':
                    guess_extra("score")
                elif playlist.get("infinite", False) and (key.char == '-'):
                    if playlist["difficulty"] > 0:
                        playlist["difficulty"] -= 1
                        difficulty_dropdown.current(playlist["difficulty"])
                        select_difficulty()
                elif playlist.get("infinite", False) and (key.char == '+'):
                    if playlist["difficulty"] < len(difficulty_options)-1:
                        playlist["difficulty"] += 1
                        difficulty_dropdown.current(playlist["difficulty"])
                        select_difficulty()
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
create_first_row_buttons()
threading.Thread(target=load_default_char_images, daemon=True).start()

# Start downloading videos in the background
download_thread = threading.Thread(target=download_videos, daemon=True)
download_thread.start()

# Start updating the seek bar
root.after(1000, update_seek_bar)
# Schedule a check for when the video ends
root.after(1000, check_video_end)

root.mainloop()