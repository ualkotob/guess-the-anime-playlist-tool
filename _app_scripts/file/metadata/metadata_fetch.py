"""
metadata_fetch.py
-----------------
Pure API-fetch functions and stateless computation helpers extracted from
guess_the_anime.py.  Nothing here reads or writes the main `metadata` /
`file_metadata` dicts – those stay in the host module.

State owned by this module
--------------------------
animethemes_cache   – in-process cache keyed by filename slug
last_jikan_error    – last error string from fetch_jikan_metadata (or None)
_igdb_token_cache   – dict holding the cached Twitch/IGDB OAuth token
_igdb_client_id     – IGDB credentials, injected via set_credentials()
_igdb_client_secret

Call set_credentials(igdb_client_id, igdb_client_secret) from load_config()
each time the config is loaded so this module always has fresh credentials.
"""

import json
import os
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from tkinter import messagebox, simpledialog

import requests

from core.game_state import state
import _app_scripts.utils as utils
import _app_scripts.data.metadata_io as metadata_io
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.theme.marks as playlist_marks
import _app_scripts.playback.ffmpeg_check as ffmpeg_check
import _app_scripts.directory.scan as directory_scan
import _app_scripts.queue_round.youtube.youtube_control as youtube_control
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.file.metadata.metadata_panel as metadata_panel
import _app_scripts.queue_round.lightning_rounds.lightning_manager as lightning_manager

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

animethemes_cache: dict = {}

last_jikan_error = None

_igdb_token_cache: dict = {"token": None, "expires_at": 0}

_igdb_client_id: str = ""
_igdb_client_secret: str = ""


def set_credentials(igdb_client_id: str, igdb_client_secret: str) -> None:
    """Inject IGDB (Twitch) credentials.  Called from load_config() in main."""
    global _igdb_client_id, _igdb_client_secret
    _igdb_client_id = igdb_client_id or ""
    _igdb_client_secret = igdb_client_secret or ""


# ---------------------------------------------------------------------------
# ARM cross-reference
# ---------------------------------------------------------------------------

def fetch_arm_ids(mal_id):
    """Looks up AniList, aniDB, and Kitsu IDs for a given MAL ID via arm-server.
    Returns a dict with keys: 'anilist', 'anidb', 'kitsu' (all strings), or empty dict on failure."""
    try:
        response = requests.get(
            "https://arm.haglund.dev/api/v2/ids",
            params={"source": "myanimelist", "id": str(mal_id)},
            timeout=5
        )
        if response.status_code != 200:
            return {}
        data = response.json()
        result = {}
        if data.get("anilist"):
            result["anilist"] = str(data["anilist"])
        if data.get("anidb"):
            result["anidb"] = str(data["anidb"])
        if data.get("kitsu"):
            result["kitsu"] = str(data["kitsu"])
        return result
    except Exception as e:
        print(f" [ARM lookup ✗: {e}]", end="")
        return {}


# ---------------------------------------------------------------------------
# AnimThemes
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Jikan (MyAnimeList)
# ---------------------------------------------------------------------------

def fetch_jikan_metadata(mal_id):
    global last_jikan_error
    last_jikan_error = None
    url = f"https://api.jikan.moe/v4/anime/{mal_id}/full"
    try:
        response = requests.get(url, timeout=12)
        if response.status_code == 200:
            data = response.json()
            if data.get("data"):
                return data["data"]
            last_jikan_error = f"Jikan returned 200 but no data payload for MAL {mal_id}"
            return None

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            last_jikan_error = f"Jikan rate-limited (429) for MAL {mal_id}" + (f", Retry-After={retry_after}s" if retry_after else "")
        elif 500 <= response.status_code <= 599:
            last_jikan_error = f"Jikan server error ({response.status_code}) for MAL {mal_id}"
        else:
            last_jikan_error = f"Jikan request failed ({response.status_code}) for MAL {mal_id}"
    except requests.exceptions.Timeout:
        last_jikan_error = f"Jikan timeout for MAL {mal_id}"
    except requests.exceptions.RequestException as e:
        last_jikan_error = f"Jikan network error for MAL {mal_id}: {e}"
    except Exception as e:
        last_jikan_error = f"Unexpected Jikan error for MAL {mal_id}: {e}"

    return None


# ---------------------------------------------------------------------------
# IGDB (Twitch)
# ---------------------------------------------------------------------------

def fetch_igdb_token():
    """Obtain or return a cached Twitch OAuth bearer token for IGDB."""
    import time as _time
    if _igdb_token_cache["token"] and _time.time() < _igdb_token_cache["expires_at"] - 60:
        return _igdb_token_cache["token"]
    if not _igdb_client_id or not _igdb_client_secret:
        return None
    try:
        resp = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": _igdb_client_id,
                "client_secret": _igdb_client_secret,
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            d = resp.json()
            _igdb_token_cache["token"] = d["access_token"]
            import time as _time2
            _igdb_token_cache["expires_at"] = _time2.time() + d.get("expires_in", 3600)
            return _igdb_token_cache["token"]
        else:
            print(f" [IGDB token] FAILED: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f" [IGDB token error: {e}]")
    return None


def fetch_igdb_metadata(igdb_id):
    """Fetch game metadata from IGDB and map it to the internal schema."""
    token = fetch_igdb_token()
    if not token:
        return None
    try:
        headers = {
            "Client-ID": _igdb_client_id,
            "Authorization": f"Bearer {token}",
        }
        # Support both numeric IDs and URL slugs
        if str(igdb_id).lstrip("-").isdigit():
            where_clause = f"where id = {igdb_id};"
        else:
            where_clause = f'where slug = "{igdb_id}";'
        body = (
            f"fields name,alternative_names.name,summary,first_release_date,"
            f"cover.url,rating,rating_count,genres.name,themes.name,"
            f"platforms.name,involved_companies.company.name,involved_companies.developer,"
            f"involved_companies.publisher,game_type.type,videos.video_id,videos.name,"
            f"collection.name,collections.name,franchise.name,franchises.name,slug;"
            f" {where_clause}"
        )
        resp = requests.post(
            "https://api.igdb.com/v4/games",
            headers=headers,
            data=body,
            timeout=12,
        )
        if resp.status_code != 200:
            print(f" [IGDB {resp.status_code} for id {igdb_id}]")
            return None
        results = resp.json()
        if not results:
            print(f" [IGDB] No results for id={igdb_id}")
            return None
        g = results[0]

        # Title
        title = g.get("name", "N/A")
        alt_names = [a["name"] for a in g.get("alternative_names", []) if a.get("name")]

        # Release date
        release = None
        if g.get("first_release_date"):
            import datetime as _dt
            release = _dt.datetime.fromtimestamp(g["first_release_date"], _dt.timezone.utc).strftime("%B %d, %Y")

        # Cover  (IGDB URLs start with //images.igdb.com — add https: and upgrade to 720p)
        cover_url = None
        if g.get("cover") and g["cover"].get("url"):
            raw = g["cover"]["url"]
            if raw.startswith("//"):
                raw = "https:" + raw
            cover_url = raw.replace("/t_thumb/", "/t_720p/")

        # Rating  (IGDB uses 0-100)
        score = round(g["rating"] / 10, 1) if g.get("rating") else None
        reviews = g.get("rating_count")

        # Genres / themes
        genres = [x["name"] for x in g.get("genres", []) if x.get("name")]
        # Deduplicate themes against genres to avoid showing the same tag twice
        _raw_themes = [x["name"] for x in g.get("themes", []) if x.get("name")]
        themes = [t for t in _raw_themes if t not in genres]

        # Platforms
        platforms = [x["name"] for x in g.get("platforms", []) if x.get("name")]

        # Studios = developers first, then publishers
        studios = []
        for ic in g.get("involved_companies", []):
            name = (ic.get("company") or {}).get("name")
            if name and ic.get("developer") and name not in studios:
                studios.append(name)
        for ic in g.get("involved_companies", []):
            name = (ic.get("company") or {}).get("name")
            if name and ic.get("publisher") and name not in studios:
                studios.append(name)

        # Determine type: Visual Novel check via IGDB game_type
        game_type_str = ((g.get("game_type") or {}).get("type") or "").lower()
        entry_type = "Visual Novel" if "visual novel" in game_type_str else "Game"

        # Trailer — prefer a video named "Trailer", fall back to first video
        trailer_yt_id = None
        videos = g.get("videos", [])
        for v in videos:
            if "trailer" in (v.get("name") or "").lower() and v.get("video_id"):
                trailer_yt_id = v["video_id"]
                break
        if not trailer_yt_id and videos:
            trailer_yt_id = videos[0].get("video_id")

        # Series — from collection/collections (primary) then franchise/franchises (broader)
        series_names = []
        if g.get("collection") and g["collection"].get("name"):
            series_names.append(g["collection"]["name"])
        for col in g.get("collections", []):
            name = col.get("name")
            if name and name not in series_names:
                series_names.append(name)
        if g.get("franchise") and g["franchise"].get("name"):
            name = g["franchise"]["name"]
            if name not in series_names:
                series_names.append(name)
        for fr in g.get("franchises", []):
            name = fr.get("name")
            if name and name not in series_names:
                series_names.append(name)

        mapped = {
            "title": title,
            "eng_title": title,
            "synonyms": alt_names,
            "igdb": str(igdb_id),
            "igdb_slug": g.get("slug"),
            "series": series_names,
            "release": release,
            "score": score,
            "reviews": reviews,
            "type": entry_type,
            "source": "Original",
            "studios": studios,
            "genres": genres,
            "themes": themes,
            "demographics": [],
            "platforms": platforms,
            "synopsis": g.get("summary", "N/A"),
            "cover": cover_url,
            "trailer": trailer_yt_id,
        }
        return mapped
    except Exception as e:
        print(f" [IGDB fetch error for id {igdb_id}: {e}]")
        return None


# ---------------------------------------------------------------------------
# AniDB
# ---------------------------------------------------------------------------

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

        if not title:
            title = f"Episode {number}"

        episodes.append([number, title])

    result["episodes"] = episodes

    return result


# ---------------------------------------------------------------------------
# AniList
# ---------------------------------------------------------------------------

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


def fetch_anilist_metadata(anilist_id=None, mal_id=None):
    """Fetches detailed metadata for a specific AniList anime ID, or by MAL ID.
    When mal_id is given the AniList ID is discovered from the response.
    Returns (resolved_anilist_id_str, metadata_dict), or (None, None) on failure."""
    if anilist_id is not None:
        lookup_field = "id: $id"
        variables = {"id": int(anilist_id)}
    elif mal_id is not None:
        lookup_field = "idMal: $id"
        variables = {"id": int(mal_id)}
    else:
        return None, None

    query = f'''
    query ($id: Int) {{
      Media({lookup_field}, type: ANIME) {{
        id
        idMal
        title {{
          romaji
          english
        }}
        format
        meanScore
        popularity
        rankings {{
          rank
          type
          format
          year
          season
          allTime
          context
        }}
        tags {{
          name
          category
          rank
          isMediaSpoiler
        }}
        externalLinks {{
          site
          url
        }}
        characters(sort: ROLE, perPage: 25) {{
          edges {{
            role
            node {{
              name {{
                full
              }}
              gender
              age
              description
              image {{
                large
                medium
              }}
            }}
            voiceActors(language: JAPANESE) {{
              name {{
                full
              }}
            }}
          }}
        }}
      }}
    }}
    '''

    try:
        response = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": variables}
        )

        if response.status_code != 200:
            print(f"AniList API error: {response.text}")
            return None, None

        data = response.json()
        media = data.get("data", {}).get("Media")
        
        if not media:
            return None, None

        # Resolve the AniList ID from the response (works for both lookup modes)
        resolved_anilist_id = str(media.get("id")) if media.get("id") else str(anilist_id or "")

        # Extract and format the metadata in desired order
        metadata = {
            "mal_id": media.get("idMal"),
            "title": media.get("title", {}).get("romaji"),
            "title_english": media.get("title", {}).get("english"),
            "format": media.get("format"),
            "score": media.get("meanScore"),
            "popularity": media.get("popularity")
        }

        # Extract rankings - store all-time, yearly, and seasonal rankings
        if media.get("rankings"):
            for ranking in media["rankings"]:
                rank_type = ranking.get("type")
                is_all_time = ranking.get("allTime", False)
                year = ranking.get("year")
                season = ranking.get("season")
                rank_value = ranking.get("rank")
                
                if rank_type == "RATED":
                    if is_all_time:
                        metadata["score_rank_all"] = rank_value
                    elif season:
                        metadata["score_rank_season"] = rank_value
                    elif year:
                        metadata["score_rank_year"] = rank_value
                        
                elif rank_type == "POPULAR":
                    if is_all_time:
                        metadata["popularity_rank_all"] = rank_value
                    elif season:
                        metadata["popularity_rank_season"] = rank_value
                    elif year:
                        metadata["popularity_rank_year"] = rank_value

        # Now add tags after rankings
        metadata["tags"] = []
        
        if media.get("tags"):
            sorted_tags = sorted(media["tags"], key=lambda x: x.get("rank", 0), reverse=True)
            metadata["tags"] = [
                {
                    "name": tag.get("name"),
                    "category": tag.get("category"),
                    "rank": tag.get("rank"),
                    "spoiler": tag.get("isMediaSpoiler", False)
                }
                for tag in sorted_tags
            ]

        # Extract aniDB ID from externalLinks
        anidb_id_from_anilist = None
        external_links = media.get("externalLinks") or []
        for link in external_links:
            if link.get("site") == "AniDB" and link.get("url"):
                m = re.search(r'anidb\.net/anime/(\d+)', link["url"])
                if m:
                    anidb_id_from_anilist = m.group(1)
                    break
        if anidb_id_from_anilist:
            metadata["anidb_id"] = anidb_id_from_anilist

        # Finally add characters
        metadata["characters"] = []
        
        if media.get("characters", {}).get("edges"):
            for edge in media["characters"]["edges"]:
                char_node = edge.get("node", {})
                character_data = {
                    "name": char_node.get("name", {}).get("full"),
                    "role": edge.get("role"),
                    "gender": char_node.get("gender"),
                    "age": char_node.get("age"),
                    "description": char_node.get("description"),
                    "image": char_node.get("image", {}).get("large")
                }
                
                voice_actors = edge.get("voiceActors", [])
                if voice_actors:
                    character_data["voice_actors"] = [
                        va.get("name", {}).get("full") for va in voice_actors
                    ]
                
                metadata["characters"].append(character_data)

        return resolved_anilist_id, metadata

    except Exception as e:
        print(f"Failed to fetch AniList metadata: {e}")
        return None, None


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def aired_to_season_year(aired_str, start=True):
    """Converts an aired string to 'Season Year' format based on the start or end date."""
    
    _MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    def parse_date(date_str):
        date_str = date_str.strip()
        m = re.match(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', date_str)
        if m:
            mon_key = m.group(1)[:3].lower()
            mon_num = _MONTHS.get(mon_key)
            if mon_num:
                from datetime import datetime as _dt
                return _dt(int(m.group(3)), mon_num, int(m.group(2)))
        m = re.match(r'([A-Za-z]+)\s+(\d{4})', date_str)
        if m:
            mon_key = m.group(1)[:3].lower()
            mon_num = _MONTHS.get(mon_key)
            if mon_num:
                from datetime import datetime as _dt
                return _dt(int(m.group(2)), mon_num, 1)
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', date_str)
        if m:
            from datetime import datetime as _dt
            return _dt(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r'^(\d{4})$', date_str.strip())
        if m:
            from datetime import datetime as _dt
            return _dt(int(m.group(1)), 1, 1)
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(date_str, fmt)
            except ValueError:
                pass
        raise ValueError(f"Unrecognised date format: {date_str!r}")

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
        if re.search(r'\bto\b', aired_str):
            parts = re.split(r'\bto\b', aired_str, maxsplit=1)
            chosen_part = parts[0].strip() if start else (parts[1].strip() if len(parts) > 1 else "?")
        else:
            chosen_part = aired_str.strip()
        if chosen_part == "?":
            from datetime import datetime
            aired_date = datetime.now()
        else:
            aired_date = parse_date(chosen_part)

        season = get_season_from_date(aired_date)
        return f"{season} {aired_date.year}"

    except Exception as e:
        print(f"Error parsing aired string: {aired_str} -> {e}")
        return "N/A"


def get_last_two_folders(filepath):
    if not filepath:
        return ["", ""]
    path_parts = filepath.split(os.sep)
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


def _song_slug_sort_key(song):
    """Sort key for theme songs: OPs before EDs before others, numerically within each group."""
    slug = song.get("slug") or "" if isinstance(song, dict) else (song or "")
    m = re.match(r"([A-Z]+)(\d+)(.*)", slug)
    if m:
        prefix, num, variant = m.groups()
        return (prefix, bool(variant), int(num))
    return ("ZZZ", True, 999999)


def sort_songs(songs):
    """Return a new sorted list: openings, then endings, then others; numerically within each group."""
    openings = [s for s in songs if "OP" in (s.get("slug") or "")]
    endings  = [s for s in songs if "ED" in (s.get("slug") or "")]
    others   = [s for s in songs if "OP" not in (s.get("slug") or "") and "ED" not in (s.get("slug") or "")]
    return sorted(openings, key=_song_slug_sort_key) + sorted(endings, key=_song_slug_sort_key) + sorted(others, key=_song_slug_sort_key)




def get_external_site_id(anime_themes, site):
    if anime_themes:
        for resource in anime_themes.get("resources", []):
            if resource.get("site") == site:
                ext_id = resource.get("external_id")
                if ext_id is not None:
                    site_id = str(ext_id)
                    if site_id != "None":
                        return site_id

                # Fallback: some resources may omit external_id but still include it in the link.
                link = str(resource.get("link") or "")
                if "/episode/" in link:
                    return None
                if site == "MyAnimeList":
                    m = re.search(r"/anime/(\d+)", link)
                    if m:
                        return m.group(1)
                elif site == "AniList":
                    m = re.search(r"/anime/(\d+)", link)
                    if m:
                        return m.group(1)
                elif site == "aniDB":
                    m = re.search(r"/anime/(\d+)", link)
                    if m:
                        return m.group(1)
    return None


# NOTE: sibling helpers (deep_merge, save_metadata, update_metadata, …) are called
# directly via their owning modules (utils/metadata_io/metadata_panel/…), imported
# at module top. metadata-cluster dicts (file_metadata, anilist_metadata,
# anime_metadata, anidb_metadata, ai_metadata, anime_metadata_overrides,
# directory_files, playlist) and playback dicts (currently_playing) are read
# directly from `state.metadata.*` and `state.playback.*` — no getters needed.


def toggle_auto_auto_refresh():
    state.controls.auto_refresh_toggle = not state.controls.auto_refresh_toggle
    print("Auto refresh metadata: " + str(state.controls.auto_refresh_toggle))


# ── State ───────────────────────────────────────────────────────────────────


# ── Orchestration functions ─────────────────────────────────────────────────



def pre_fetch_metadata():
    for i in range(state.metadata.playlist["current_index"]-1, state.metadata.playlist["current_index"]+3):
        playlist_entry = state.metadata.playlist["playlist"][i] if i >= 0 and i < len(state.metadata.playlist["playlist"]) else None
        if playlist_entry and i != state.metadata.playlist["current_index"]:
            filename = entry_paths.get_clean_filename(playlist_entry)
            filepath = entry_paths.get_file_path(playlist_entry)
            if fetching_metadata.get(filename) is None and filepath and os.path.exists(filepath):
                get_metadata(filename, refresh=True, fetch=True)

_metadata_cache = {}
# Make sure this is initialized as a set!
fetched_metadata = set()

_file_metadata_base_cache = {}
_file_metadata_cache_valid = False
filename_to_mal = {}


def invalidate_file_metadata_cache():
    """Call this when state.metadata.file_metadata changes"""
    global _file_metadata_cache_valid
    _file_metadata_cache_valid = False




def build_filename_to_mal_map():
    """Build lookup map from filename to MAL ID/slug/version for fast access.
    Returns the count of actual files (not including base name lookups)."""
    global filename_to_mal
    filename_to_mal = {}
    actual_file_count = 0
    
    for mal_id, mal_data in state.metadata.file_metadata.items():
        themes = mal_data.get("themes", {})
        for slug, slug_data in themes.items():
            for version, version_data in slug_data.items():
                for filename in version_data.keys():
                    filename_to_mal[filename] = {
                        "mal_id": mal_id,
                        "slug": slug,
                        "version": version
                    }
                    actual_file_count += 1
                    # Also store base name without extension for lookup
                    base_name = os.path.splitext(filename)[0]
                    if base_name not in filename_to_mal:
                        filename_to_mal[base_name] = {
                            "mal_id": mal_id,
                            "slug": slug,
                            "version": version
                        }
    
    return actual_file_count


def get_metadata(filename, refresh=False, refresh_all=False, fetch=False):
    global fetched_metadata
    # Lazy import: variety_round imports metadata_fetch, so a module-level import would cycle.
    import _app_scripts.queue_round.lightning_rounds.variety_round as variety_round

    if not filename:
        return {}

    if not (refresh or fetch) and filename in _metadata_cache:
        return _metadata_cache[filename]

    if not ("-OP" in filename or "-ED" in filename):
        return {}

    file_data = get_file_metadata_by_name(filename)
    if not file_data:
        return fetch_metadata(filename, refetch=refresh) if fetch else {}

    mal_id = file_data.get('mal')
    anidb_id = file_data.get('anidb')
    anilist_id = file_data.get('anilist')
    anime_data = state.metadata.anime_metadata.get(mal_id) or {}
    anidb_data = state.metadata.anidb_metadata.get(anidb_id, {}) if anidb_id else {}
    ai_data = state.metadata.ai_metadata.get(mal_id, {}) if mal_id else {}
    re_queue_lightning_mode = False
    if anime_data and "-[ID]" not in filename and mal_id:
        if refresh and mal_id not in fetched_metadata and (refresh_all or (state.controls.auto_refresh_toggle and fetch)):
            fetched_metadata.add(mal_id)
            refresh_jikan_data(mal_id, anime_data)
            if state.lightning.light_mode:
                re_queue_lightning_mode = True
        if refresh and fetch and anidb_id and (anidb_id not in state.metadata.anidb_metadata or state.controls.auto_refresh_toggle) and not anidb_cooldown and (variety_round.variety_light_mode_enabled or state.lightning.light_mode in ['characters', 'tags', 'episodes', 'names'] or (state.lightning.light_mode and "c." in state.lightning.light_mode)):
            refresh_anidb_data(anidb_id, anime_data)
            re_queue_lightning_mode = True
        if refresh and fetch and anilist_id and state.controls.auto_refresh_toggle and str(anilist_id) in state.metadata.anilist_metadata:
            # Refresh AniList metadata when auto refresh is enabled
            try:
                _, anilist_data = fetch_anilist_metadata(anilist_id=anilist_id)
                if anilist_data:
                    state.metadata.anilist_metadata[str(anilist_id)] = anilist_data
                    metadata_io.save_metadata()
            except Exception as e:
                print(f" [AniList auto-refresh ✗: {e}]", end="")

    result = file_data | anime_data | anidb_data | ai_data
    # Ensure igdb from state.metadata.file_metadata is never lost to a null in state.metadata.anime_metadata
    if not result.get("igdb") and file_data.get("igdb"):
        result["igdb"] = file_data["igdb"]
    _metadata_cache[filename] = result
    if re_queue_lightning_mode:
        lightning_manager.queue_next_lightning_mode()
    return result


def get_file_metadata_by_name(filename):
    """
    Get file metadata for a filename using the filename_to_mal lookup map.
    Returns the full MAL entry with all themes, plus file-specific properties.
    """
    if not filename:
        return None
    
    if not filename_to_mal:
        build_filename_to_mal_map()
    
    # Try exact match first
    lookup_data = filename_to_mal.get(filename)
    
    # Try base name without extension
    if not lookup_data:
        base_name = os.path.splitext(filename)[0]
        lookup_data = filename_to_mal.get(base_name)
    
    if not lookup_data:
        return None
    
    mal_id = lookup_data["mal_id"]
    slug = lookup_data["slug"]
    version = lookup_data["version"]
    # Get the full MAL entry
    mal_entry = state.metadata.file_metadata.get(mal_id)
    if not mal_entry:
        return None
    
    # Return MAL entry with current file info added
    result = dict(mal_entry)  # Copy the entry
    result["mal"] = mal_id
    result["slug"] = slug
    result["version"] = version
    result["anidb"] = mal_entry.get("anidb")
    result["anilist"] = mal_entry.get("anilist")
    
    # Add file-specific properties (lyrics, nc, resolution, source)
    themes = mal_entry.get("themes", {})
    if slug in themes:
        versions = themes[slug]
        version_str = str(version) if version else "1"
        if version_str in versions:
            files = versions[version_str]
            file_props = files.get(filename, {})
            result["file_properties"] = file_props
    
    return result


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
    except Exception:
        pass
    
    return None


def extract_video_file_properties(filename):
    """Extract actual video properties from the file using ffmpeg/ffprobe."""
    
    # Get the file path
    filepath = state.metadata.directory_files.get(filename)
    if not filepath or not os.path.exists(filepath):
        return {}
    
    if not ffmpeg_check.is_ffmpeg_available():
        return {}
    
    try:
        # Use ffprobe to get video stream information
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 'v:0',  # First video stream
            filepath
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            return {}
        
        data = json.loads(result.stdout)
        
        if not data.get('streams') or len(data['streams']) == 0:
            return {}
        
        stream = data['streams'][0]
        
        # Extract properties
        properties = {}
        
        # Resolution (height in pixels, e.g., "720", "1080")
        if stream.get('height'):
            properties['resolution'] = str(stream['height'])
        
        if stream.get('bit_rate'):
            bit_rate_mbps = int(stream['bit_rate']) / 1_000_000
            properties['bitrate'] = f"{bit_rate_mbps:.1f}"
        
        return properties
        
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError, Exception) as e:
        print(f"Failed to extract video properties for {filename}: {e}")
        return {}


def refetch_metadata():
    if state.playback.currently_playing and state.playback.currently_playing.get('type') == 'theme':
        filename = state.playback.currently_playing.get('filename')
    else:
        playlist_entry = entry_paths.get_clean_filename(state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]])
        filename = os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry
    fetch_metadata(filename, True)


def reorder_file_metadata_entry(mal_id):
    """Reorder state.metadata.file_metadata entry to have name first, then IDs, then themes last."""
    if mal_id not in state.metadata.file_metadata:
        return
    
    entry = state.metadata.file_metadata[mal_id]
    ordered_entry = {}
    
    if "name" in entry and entry["name"] is not None:
        ordered_entry["name"] = entry["name"]
    
    # 2. IDs
    for key in ["mal", "anidb", "anilist"]:
        if key in entry:
            ordered_entry[key] = entry[key]
    
    # 3. AnimThemes IDs (optional)
    for key in ["animethemes_id", "animethemes_slug"]:
        if key in entry:
            ordered_entry[key] = entry[key]
    
    # 4. Themes last
    if "themes" in entry:
        ordered_entry["themes"] = entry["themes"]
    
    # Replace the entry with ordered version
    state.metadata.file_metadata[mal_id] = ordered_entry

anidb_cooldown = False
fetching_metadata = {}


def fetch_metadata(filename = None, refetch = False, label="", batch_mode=False):
    global anidb_cooldown, anidb_delay
    if filename is None:
        playlist_entry = entry_paths.get_clean_filename(state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]])
        filename = os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry
        refetch = True

    print(f"{label}Fetching metadata for {filename}...", end="", flush=True)

    fetching_metadata[filename] = True
    
    if not refetch and filename in filename_to_mal:
        lookup_data = filename_to_mal[filename]
        mal_id = lookup_data["mal_id"]
        slug = lookup_data["slug"]
        version = lookup_data["version"]
        
        anime_data = state.metadata.anime_metadata.get(mal_id)
        if anime_data and anime_data.get("title"):
            file_data = get_file_metadata_by_name(filename)
            anidb_id = file_data.get('anidb')
            anilist_id = file_data.get('anilist')
            
            # Get override-applied anime_data
            anime_data = dict(anime_data)
            if mal_id in state.metadata.anime_metadata_overrides:
                utils.deep_merge(anime_data, state.metadata.anime_metadata_overrides[mal_id])
            
            data = {
                "mal": mal_id,
                "anidb": anidb_id,
                "anilist": anilist_id,
                "slug": slug,
                "version": version
            }
            data.update(anime_data)
            
            if state.playback.currently_playing.get('filename') == filename:
                state.playback.currently_playing["data"] = data
                metadata_panel.update_metadata()
            
            print(f"\r{label}Fetching metadata for {filename}...COMPLETE")
            return data
    
    slug = filename.split("-")[1].split(".")[0].split("v")[0] if "-" in filename else None
    version = None
    mal_id = None
    anidb_id = None
    anilist_id = None
    anime_themes = None
    is_animethemes_file = False
    
    if "[IGDB]" in filename:
        # --- IGDB game/VN file ---
        filename_metadata = get_filename_metadata(filename)
        igdb_id = filename_metadata.get("igdb_id")
        igdb_key = f"IGDB:{igdb_id}" if igdb_id else None
        version = get_version_from_filename(filename)

        if igdb_key not in state.metadata.file_metadata:
            state.metadata.file_metadata[igdb_key] = {
                "name": None,
                "igdb": igdb_id,
                "themes": {}
            }
        igdb_entry = state.metadata.file_metadata[igdb_key]

        # Register this file in the themes structure
        if slug:
            if slug not in igdb_entry["themes"]:
                igdb_entry["themes"][slug] = {}
            version_key = str(version) if version is not None else "null"
            if version_key not in igdb_entry["themes"][slug]:
                igdb_entry["themes"][slug][version_key] = {}
            if filename not in igdb_entry["themes"][slug][version_key]:
                video_properties = extract_video_file_properties(filename)
                video_properties["source"] = "LOCAL"
                igdb_entry["themes"][slug][version_key][filename] = video_properties

        # Build/refresh metadata
        anime_data = state.metadata.anime_metadata.get(igdb_key)
        if refetch or not anime_data or not anime_data.get("title") or not anime_data.get("igdb_slug"):
            igdb_data = fetch_igdb_metadata(igdb_id) if igdb_id else None
            if igdb_data:
                # Preserve songs already accumulated before replacing with fresh API data
                _preserved_songs = (state.metadata.anime_metadata.get(igdb_key) or {}).get("songs", [])
                anime_data = igdb_data
                if _preserved_songs:
                    anime_data["songs"] = _preserved_songs
                # Fold in series from overrides if present (merge with API-fetched series)
                _override_series = (state.metadata.anime_metadata_overrides.get(igdb_key) or {}).get("series")
                if _override_series:
                    merged = list(anime_data.get("series") or [])
                    for _s in _override_series:
                        if _s not in merged:
                            merged.append(_s)
                    anime_data["series"] = merged
                else:
                    anime_data.setdefault("series", [])
                # Compute derived fields
                if anime_data.get("reviews"):
                    anime_data["members"] = anime_data["reviews"] * metadata_io.REVIEW_MODIFIER
                anime_data["popularity"] = metadata_io.estimate_manual_popularity(anime_data.get("members"))
                anime_data["rank"] = metadata_io.estimate_manual_rank(anime_data.get("score"))
                if anime_data.get("release"):
                    anime_data["aired"] = anime_data["release"]
                    anime_data["season"] = aired_to_season_year(anime_data["release"])
                state.metadata.anime_metadata[igdb_key] = anime_data
                igdb_entry["name"] = anime_data.get("title")
                if not batch_mode:
                    metadata_io.save_metadata()
            else:
                if not anime_data:
                    anime_data = {
                        "title": "N/A", "synonyms": [], "series": [],
                        "aired": "N/A", "season": "N/A", "score": "N/A",
                        "rank": "N/A", "members": "N/A", "popularity": "N/A",
                        "type": "Game", "source": "N/A", "episodes": 1,
                        "studios": [], "genres": [], "themes": [], "demographics": [],
                        "platforms": [], "synopsis": "N/A", "cover": None, "trailer": None,
                        "igdb": str(igdb_id) if igdb_id else None,
                    }
                    state.metadata.anime_metadata[igdb_key] = anime_data
                print(f" [IGDB meta missing for id {igdb_id}]", end="")

        # Build song from [ART]/[SNG] tags and merge/sort like the MAL branch
        old_songs = anime_data.get("songs", [])
        new_songs = []
        if filename_metadata.get("song"):
            artists_group = [
                {"name": a} for a in (filename_metadata.get("artist") or "N/A").split("+")
            ]
            new_songs = [{
                "type": slug[:2].upper() if slug else "OP",
                "slug": slug,
                "title": filename_metadata["song"],
                "artist": [a["name"] for a in artists_group],
                "episodes": None,
            }]
        # Merge old + new, dedup by slug (new wins), then sort
        all_songs = list({s["slug"]: s for s in old_songs + new_songs if s.get("slug")}.values())
        anime_data["songs"] = sort_songs(all_songs)
        state.metadata.anime_metadata[igdb_key] = anime_data
        _metadata_cache.pop(filename, None)  # invalidate stale cache entry

        reorder_file_metadata_entry(igdb_key)
        if not batch_mode:
            metadata_io.save_metadata()
            build_filename_to_mal_map()
        else:
            if igdb_key in state.metadata.file_metadata:
                for _ts, _vs in state.metadata.file_metadata[igdb_key].get("themes", {}).items():
                    for _vk, _fs in _vs.items():
                        for _fn in _fs.keys():
                            filename_to_mal[_fn] = {
                                "mal_id": igdb_key,
                                "slug": _ts,
                                "version": None if _vk == "null" else (int(_vk) if _vk.isdigit() else _vk)
                            }

        data = {"mal": igdb_key, "igdb": igdb_id, "slug": slug, "version": version}
        data.update(anime_data)
        if state.playback.currently_playing.get("filename") == filename:
            state.playback.currently_playing["data"] = data
            # Do NOT call metadata_panel.update_metadata() directly — let the already-queued thread pick up
            # the newly-set data. A direct call here races with the queued thread and causes
            # Tkinter deadlocks when the two threads manipulate widgets concurrently.
            if not state.controls.updating_metadata:
                metadata_display.update_metadata_queue(state.metadata.playlist["current_index"])
        print(f"\r{label}Fetching metadata for {filename}...COMPLETE")
        fetching_metadata.pop(filename, None)
        return data

    elif (not "[MAL]" in filename) and (not "[ID]" in filename):
        # AnimThemes file
        is_animethemes_file = True
        anime_themes = fetch_animethemes_metadata(filename)
        # Extract slug and version from animethemes data instead of filename
        slug_found = False
        filename_base = os.path.splitext(str(filename or ""))[0].lower()

        def _extract_slug_version(src):
            nonlocal slug, version, slug_found
            if not src or not src.get("animethemes"):
                return
            for theme in src.get("animethemes", []):
                for entry in theme.get("animethemeentries", []):
                    for video in entry.get("videos", []):
                        video_base = os.path.splitext(str(video.get("basename") or ""))[0].lower()
                        if video_base and video_base == filename_base:
                            slug = theme.get("slug", slug)
                            version = entry.get("version")
                            slug_found = True
                            return

        # Pass 1: prefix match lookup (fast/common)
        _extract_slug_version(anime_themes)

        # Pass 2: exact basename fallback (important when prefix returns a different anime)
        if not slug_found:
            anime_themes_exact = fetch_animethemes_metadata(filename, split=False)
            if anime_themes_exact:
                anime_themes = anime_themes_exact
                _extract_slug_version(anime_themes)

        mal_id = get_external_site_id(anime_themes, "MyAnimeList")
        anidb_id = get_external_site_id(anime_themes, "aniDB")
        anilist_id = get_external_site_id(anime_themes, "AniList")
    elif ("[MAL]" in filename):
        # Manual [MAL] file
        filename_metadata = get_filename_metadata(filename)
        mal_id = filename_metadata.get('mal_id')
        anidb_id = filename_metadata.get('anidb_id')
        anilist_id = filename_metadata.get('anilist_id')
        version = get_version_from_filename(filename)
        # Use ARM cross-reference service to resolve missing IDs from MAL ID
        if mal_id and (not anidb_id or not anilist_id):
            _arm = fetch_arm_ids(mal_id)
            anidb_id = anidb_id or _arm.get("anidb")
            anilist_id = anilist_id or _arm.get("anilist")
        anime_themes = fetch_animethemes_metadata(mal_id=mal_id)
        if not anime_themes:
            anime_themes = {
                 "animethemes":[]
            }
        else:
            # Always try to resolve IDs from the MAL-based response first
            anidb_id = anidb_id or get_external_site_id(anime_themes, "aniDB")
            anilist_id = anilist_id or get_external_site_id(anime_themes, "AniList")
            try:
                file = anime_themes.get("animethemes",[{}])[0].get("animethemeentries",[{}])[0].get("videos",[{}])[0].get("basename")
            except Exception:
                file = None
            if file:
                anime_themes = fetch_animethemes_metadata(file) or anime_themes
                anidb_id = anidb_id or get_external_site_id(anime_themes, "aniDB")
                anilist_id = anilist_id or get_external_site_id(anime_themes, "AniList")
        if filename_metadata.get("song"):
            artists_group = []
            for art in (filename_metadata.get("artist") or "N/A").split('+'):
                artists_group.append(
                    {"name":art}
                )
            anime_themes["animethemes"].append({
                "type": slug[:2] if slug else None,
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
        # [ID] file
        mal_id = re.search(r"\[ID](.*?)(?=\[|$|\.)", filename).group(1)
        version = get_version_from_filename(filename)
        # Try to fetch AnimThemes metadata by MAL ID
        anime_themes = fetch_animethemes_metadata(mal_id=mal_id)
        if not anime_themes:
            anime_themes = {}
        
    if mal_id:
        # Create or get MAL entry
        if mal_id not in state.metadata.file_metadata:
            state.metadata.file_metadata[mal_id] = {
                "name": None,  # Will be populated later
                "mal": mal_id,
                "anidb": anidb_id,
                "anilist": anilist_id,
                "themes": {}
            }
        
        mal_entry = state.metadata.file_metadata[mal_id]
        
        if anidb_id:
            mal_entry["anidb"] = anidb_id
        if anilist_id:
            mal_entry["anilist"] = anilist_id
        
        if is_animethemes_file:
            if anime_themes and anime_themes.get("id"):
                mal_entry["animethemes_id"] = anime_themes.get("id")
            if anime_themes and anime_themes.get("slug"):
                mal_entry["animethemes_slug"] = anime_themes.get("slug")
        
        # Store all themes from AnimThemes API
        if anime_themes and anime_themes.get("animethemes"):
            for theme in anime_themes.get("animethemes", []):
                theme_slug = theme.get("slug")
                if not theme_slug:
                    continue
                    
                if theme_slug not in mal_entry["themes"]:
                    mal_entry["themes"][theme_slug] = {}
                
                for entry in theme.get("animethemeentries", []):
                    entry_version = entry.get("version")
                    version_key = str(entry_version) if entry_version is not None else "null"
                    
                    if version_key not in mal_entry["themes"][theme_slug]:
                        mal_entry["themes"][theme_slug][version_key] = {}
                    
                    for video in entry.get("videos", []):
                        video_basename = video.get("basename")
                        if not video_basename:
                            continue
                        
                        # Store video properties
                        video_props = {
                            "lyrics": video.get("lyrics", False),
                            "nc": video.get("nc", False),
                            "resolution": video.get("resolution"),
                            "source": video.get("source")
                        }
                        
                        mal_entry["themes"][theme_slug][version_key][video_basename] = video_props
        
        # For [ID] and [MAL] files, add this file to the themes structure
        if ("[ID]" in filename or "[MAL]" in filename) and slug:
            if slug not in mal_entry["themes"]:
                mal_entry["themes"][slug] = {}
            
            version_key = str(version) if version is not None else "null"
            if version_key not in mal_entry["themes"][slug]:
                mal_entry["themes"][slug][version_key] = {}
            
            # Add ID file with video properties
            if filename not in mal_entry["themes"][slug][version_key]:
                video_properties = extract_video_file_properties(filename)
                video_properties["source"] = "LOCAL"
                mal_entry["themes"][slug][version_key][filename] = video_properties
        
        # Fetch and store anime metadata
        anime_data = state.metadata.anime_metadata.get(mal_id)
        old_songs = []
        if anime_data:
            old_songs = anime_data.get("songs", [])
            
        # Store anime name in state.metadata.file_metadata
        if anime_themes and anime_themes.get("name"):
            mal_entry["name"] = anime_themes.get("name")
        elif anime_data and anime_data.get("title"):
            mal_entry["name"] = anime_data.get("title")
        
        # Cache invalidation now automatic via FileMetadataDict
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
                    "trailer":youtube_control.extract_youtube_id_from_trailer(jikan_data.get("trailer", {}))
                }
                if "N/A" in anime_data.get("season"):
                    if anime_themes.get("season"):
                        anime_data["season"] = str(anime_themes.get("season", "N/A")) + " " + str(anime_themes.get("year", "N/A"))
                    else:
                        anime_data["season"] = aired_to_season_year(anime_data.get("aired"))
                else:
                    anime_data["season"] = anime_data["season"].capitalize()
                state.metadata.anime_metadata[mal_id] = anime_data
                # Update name in state.metadata.file_metadata
                if anime_data.get("title"):
                    mal_entry["name"] = anime_data.get("title")
            else:
                # Keep a minimal entry so AnimThemes songs/artists can still be stored and shown.
                if not anime_data:
                    anime_data = {
                        "title": (anime_themes or {}).get("name") or mal_entry.get("name") or "N/A",
                        "synonyms": [],
                        "series": get_name_list(anime_themes or {}, "series"),
                        "aired": "N/A",
                        "season": ((str((anime_themes or {}).get("season") or "N/A") + " " + str((anime_themes or {}).get("year") or "N/A")).strip()),
                        "score": "N/A",
                        "rank": "N/A",
                        "members": "N/A",
                        "popularity": "N/A",
                        "type": (anime_themes or {}).get("media_format") or "N/A",
                        "source": "N/A",
                        "episodes": "N/A",
                        "studios": [],
                        "genres": [],
                        "themes": [],
                        "demographics": [],
                        "synopsis": (anime_themes or {}).get("synopsis") or "N/A",
                        "cover": ((anime_themes or {}).get("images", [{}])[0] or {}).get("link"),
                        "trailer": None,
                    }
                    state.metadata.anime_metadata[mal_id] = anime_data
                    if anime_data.get("title") and mal_entry.get("name") in [None, "N/A", ""]:
                        mal_entry["name"] = anime_data.get("title")
                _jikan_reason = f" ({last_jikan_error})" if last_jikan_error else ""
                print(f" [META DBG] Jikan missing/unavailable for MAL {mal_id}{_jikan_reason}; using minimal AniThemes-derived metadata", end="")
        anilist_fetched = False
        if not anilist_id and mal_id and (refetch or mal_id not in state.metadata.file_metadata or not state.metadata.file_metadata[mal_id].get("anilist")):
            # No AniList ID known yet — try to resolve it from the MAL ID
            try:
                resolved_id, anilist_data = fetch_anilist_metadata(mal_id=mal_id)
                if resolved_id and anilist_data:
                    anilist_id = resolved_id
                    state.metadata.anilist_metadata[resolved_id] = anilist_data
                    anilist_fetched = True
                    # Back-populate anilist and anidb IDs into state.metadata.file_metadata
                    if mal_id in state.metadata.file_metadata:
                        state.metadata.file_metadata[mal_id]["anilist"] = resolved_id
                    if not anidb_id and anilist_data.get("anidb_id"):
                        anidb_id = anilist_data["anidb_id"]
                        if mal_id in state.metadata.file_metadata:
                            state.metadata.file_metadata[mal_id]["anidb"] = anidb_id
                    # Clear any cached metadata for files under this mal_id so new IDs are picked up
                    for cached_fn, cached_ref in list(filename_to_mal.items()):
                        if cached_ref.get("mal_id") == mal_id:
                            _metadata_cache.pop(cached_fn, None)
            except Exception as e:
                print(f" [AniList MAL-lookup ✗: {e}]", end="")

        if anidb_id:
            anidb_data = state.metadata.anidb_metadata.get(anidb_id, {})
            if refetch or not anidb_data.get("characters") or not anidb_data.get("tags") or not anidb_data.get("episode_info"):
                if not anidb_cooldown:
                    anidb = fetch_anidb_metadata(anidb_id)
                    if anidb["tags"] == [] and anidb["characters"] == [] and anidb["episodes"] == []:
                        anidb_cooldown = True
                        print("[aniDB cooldown reached!]")
                    else:
                        anidb_delay = 5
                        anidb_entry = {
                            "tags": anidb["tags"],
                            "characters": anidb["characters"],
                            "episode_info": anidb["episodes"]
                        }
                        
                        if mal_id:
                            state.metadata.anidb_metadata[anidb_id] = {"mal_id": mal_id}
                            state.metadata.anidb_metadata[anidb_id].update(anidb_entry)
                        else:
                            state.metadata.anidb_metadata[anidb_id] = anidb_entry

        if anilist_id and not anilist_fetched and (refetch or str(anilist_id) not in state.metadata.anilist_metadata):
            try:
                _, anilist_data = fetch_anilist_metadata(anilist_id=anilist_id)
                if anilist_data:
                    state.metadata.anilist_metadata[str(anilist_id)] = anilist_data
                    anilist_fetched = True
            except Exception as e:
                print(f" [AniList ✗: {e}]", end="")
        
        if anime_data:
            # Get new songs from the current fetch
            new_songs = get_theme_list(anime_themes, slug, version)
            # Avoid duplicates by slug (new wins), then sort
            all_songs = list({song["slug"]: song for song in old_songs + new_songs}.values())
            anime_data["songs"] = sort_songs(all_songs)
            anime_data["series"] = get_name_list(anime_themes, "series") or state.metadata.anime_metadata_overrides.get(mal_id, {}).get("series") or anime_data.get("series")
            # Store updated anime_data back into state.metadata.anime_metadata before saving
            # This ensures overrides can be applied to the updated data
            state.metadata.anime_metadata[mal_id] = anime_data
        
        if not batch_mode:
            metadata_io.save_metadata()
        
        reorder_file_metadata_entry(mal_id)
        
        if not batch_mode:
            # Rebuild filename_to_mal map to reflect the reordered entry
            build_filename_to_mal_map()
        else:
            # In batch mode, incrementally update the map instead of full rebuild
            # This allows subsequent files to benefit from early return
            if mal_id in state.metadata.file_metadata:
                themes = state.metadata.file_metadata[mal_id].get("themes", {})
                for theme_slug, versions in themes.items():
                    for version_key, files in versions.items():
                        for file_name in files.keys():
                            # Add this file to the lookup map
                            filename_to_mal[file_name] = {
                                "mal_id": mal_id,
                                "slug": theme_slug,
                                "version": None if version_key == "null" else int(version_key) if version_key.isdigit() else version_key
                            }
        
        if mal_id in state.metadata.file_metadata:
            themes = state.metadata.file_metadata[mal_id].get("themes", {})
            for slug_data in themes.values():
                for version_data in slug_data.values():
                    for cache_filename in list(version_data.keys()):
                        _metadata_cache.pop(cache_filename, None)
        
        if not batch_mode:
            # Save all metadata is persisted
            metadata_io.save_metadata()
        
        # Now get the anime_data with overrides applied
        anime_data = state.metadata.anime_metadata.get(mal_id, {})
        
        if mal_id in state.metadata.anime_metadata_overrides:
            # Create a fresh copy of anime_data to avoid reference issues
            anime_data = dict(anime_data)
            # Apply overrides directly using utils.deep_merge on our local copy  
            utils.deep_merge(anime_data, state.metadata.anime_metadata_overrides[mal_id])
        
        # This needs to use the override-applied anime_data
        data = {
            "mal": mal_id,
            "anidb": anidb_id,
            "anilist": anilist_id,
            "slug": slug,
            "version": version
        }
        if anime_data:
            data.update(anime_data)
        # Merge aniDB data so characters/tags are immediately available
        anidb_data = state.metadata.anidb_metadata.get(anidb_id, {}) if anidb_id else {}
        if anidb_data:
            data = {**anidb_data, **data}  # data keys win over anidb_data
        
        if state.playback.currently_playing.get('filename') == filename:
            state.playback.currently_playing["data"] = data
            if not state.controls.updating_metadata:
                metadata_display.update_metadata_queue(state.metadata.playlist["current_index"])
        
        print(f"\r{label}Fetching metadata for {filename}...COMPLETE")
        return data
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
                    
                    overlap = None
                    if entry.get("videos") and entry["videos"]:
                        for video in entry["videos"]:
                            overlap = video.get("overlap", "None")
                            version_data["overlap"] = overlap
                            if not overlap or overlap == "None":
                                break
                    
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
    """Extracts MAL ID, IGDB ID, artist, and song name from a filename with optional bracketed tags."""
    metadata = {"mal_id": None, "anidb_id": None, "igdb_id": None, "artist": None, "song": None}
    
    mal_match = re.search(r"\[MAL](\d+)", filename)
    anidb_match = re.search(r"\[ADB](\d+)", filename)
    anilist_match = re.search(r"\[ALT](\d+)", filename)
    igdb_match = re.search(r"\[IGDB]([A-Za-z0-9][A-Za-z0-9-]*)", filename)
    artist_match = re.search(r"\[ART](.*?)(?=\[|$|\.)", filename)
    song_match = re.search(r"\[SNG](.*?)(?=\[|$|\.)", filename)
    
    if mal_match:
        metadata["mal_id"] = mal_match.group(1)

    if igdb_match:
        metadata["igdb_id"] = igdb_match.group(1)

    if anidb_match:
        metadata["anidb_id"] = anidb_match.group(1)

    if anilist_match:
        metadata["anilist_id"] = anilist_match.group(1)
    
    if artist_match:
        metadata["artist"] = artist_match.group(1).strip()
    
    if song_match:
        metadata["song"] = song_match.group(1).strip()

    season_year = get_last_two_folders(state.metadata.directory_files.get(filename))
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
        data["trailer"] = youtube_control.extract_youtube_id_from_trailer(jikan_data.get("trailer", {}))
        
        metadata_io.save_metadata()
        print(f"\r{label}Refreshing Jikan data for {data['title']}...COMPLETE")
    else:
        _reason = f" ({last_jikan_error})" if last_jikan_error else ""
        print(f"\r{label}Refreshing Jikan data for {title}...FAILED{_reason}")


def refresh_anidb_data(anidb_id, data, label=""):
    global anidb_cooldown, anidb_delay

    fetch_string = "Refreshing"
    if anidb_id not in state.metadata.anidb_metadata:
        fetch_string = "Fetching"
    print(f"{label}{fetch_string} aniDB data for {data['title']}...", end="", flush=True)
    
    anidb = fetch_anidb_metadata(anidb_id)
    if anidb:
        if anidb["tags"] == [] and anidb["characters"] == []:
            anidb_cooldown = True
            print(f"\rRefreshing aniDB data for {data['title']}...FAILED[aniDB cooldown reached!]")
        else:
            mal_id = data.get("mal")
            
            anidb_entry = {
                "tags": anidb["tags"],
                "characters": anidb["characters"],
                "episode_info": anidb["episodes"]
            }
            
            if mal_id:
                state.metadata.anidb_metadata[anidb_id] = {"mal_id": mal_id}
                state.metadata.anidb_metadata[anidb_id].update(anidb_entry)
            else:
                state.metadata.anidb_metadata[anidb_id] = anidb_entry
                
            metadata_io.save_metadata()
            anidb_delay = 5
            print(f"\r{label}{fetch_string} aniDB data for {data['title']}...COMPLETE")
    else:
        print(f"\r{label}{fetch_string} aniDB data for {data['title']}...FAILED")


def get_artists_string(artists, total = False, limit=None):
    artists_string = "N/A"
    if artists:
        displayed_count = 0
        for artist in artists:
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
                artist_count = len(metadata_display.get_filenames_from_artist(artist))
                if artist_count > 1:
                    artists_string = f"{artists_string} [{artist_count}]"
            
            displayed_count += 1
    return artists_string

anidb_delay = 0

def fetch_all_metadata(delay=0):
    """Fetches missing metadata for the entire directory, spacing out API calls."""
    confirm = messagebox.askyesno("Fetch All Missing Metadata", "Are you sure you want to fetch all missing metadata?")
    if not confirm:
        return  # User canceled
    directory_scan.scan_directory()
    # Lazy import: infinite imports metadata_fetch, so a module-level import
    # here would create a cycle.
    import _app_scripts.playlists.infinite as infinite
    infinite.reset_infinite_caches()
    def fetch_all_metadata_worker():
        global anidb_delay
        total_checked = 0
        total_fetched = 0
        total_skipped = 0
        total_missing = 0
        save_new_theme = False

        refresh_jikan = []
        refresh_anidb = []
        refresh_anilist = []
        fetch_data = []
        print(f"{len(state.metadata.directory_files)} files found in directory, checking for missing metadata...")
        for filename in state.metadata.directory_files:
            total_checked += 1
            file_data = get_file_metadata_by_name(filename)
            if file_data:
                mal_id = file_data.get('mal')
                anidb_id = file_data.get('anidb')
                anilist_id = file_data.get('anilist')
                
                if mal_id in state.metadata.anime_metadata:
                    if not state.metadata.anime_metadata.get(mal_id, {}).get("title"):
                        jikan_append = [mal_id, state.metadata.anime_metadata.get(mal_id)]
                        if jikan_append not in refresh_jikan:
                            refresh_jikan.append(jikan_append)
                            total_missing += 1
                
                if anilist_id and str(anilist_id) not in state.metadata.anilist_metadata:
                    if anilist_id not in refresh_anilist:
                        refresh_anilist.append(str(anilist_id))
                        total_missing += 1

                if anidb_id and (not anidb_id in state.metadata.anidb_metadata):
                    if anidb_cooldown:
                        total_skipped += 1
                    else:
                        anidb_append = [anidb_id, state.metadata.anime_metadata.get(mal_id)]
                        if anidb_append not in refresh_anidb:
                            refresh_anidb.append(anidb_append)
                            total_missing += 1
            else:
                fetch_data.append(filename)
                total_missing += 1
        
        if total_missing > 0:
            if fetch_data:
                save_new_theme = messagebox.askyesno("Save Missing Entries To New Themes", "Would you like to save all missing entries to the 'New Themes' state.metadata.playlist? Entries in the 'New Themes' will not appear in infinite playlists until removed from the 'New Themes' state.metadata.playlist. (Select 'NO' if unsure)")
            
            BATCH_SAVE_INTERVAL = 100
            files_since_last_save = 0
            
            for filename in fetch_data:
                needs_api_call = True
                temp_slug = filename.split("-")[1].split(".")[0].split("v")[0] if "-" in filename else None
                if temp_slug and not ("[MAL]" in filename or "[ID]" in filename):
                    # For AnimThemes files, check cache
                    temp_filename = filename.split("-")[0]
                    if temp_filename in animethemes_cache:
                        temp_anime = animethemes_cache.get(temp_filename)
                        if temp_anime:
                            temp_mal_id = get_external_site_id(temp_anime, "MyAnimeList")
                            if temp_mal_id and temp_mal_id in state.metadata.anime_metadata and state.metadata.anime_metadata[temp_mal_id].get("title"):
                                needs_api_call = False
                elif "[IGDB]" in filename:
                    temp_match = re.search(r"\[IGDB]([A-Za-z0-9][A-Za-z0-9-]*)", filename)
                    if temp_match:
                        temp_igdb_key = f"IGDB:{temp_match.group(1)}"
                        if temp_igdb_key in state.metadata.anime_metadata and state.metadata.anime_metadata[temp_igdb_key].get("title"):
                            needs_api_call = False
                elif "[MAL]" in filename or "[ID]" in filename:
                    if "[MAL]" in filename:
                        temp_match = re.search(r"\[MAL](\d+)", filename)
                    else:
                        temp_match = re.search(r"\[ID](.*?)(?=\[|$|\.)", filename)
                    if temp_match:
                        temp_mal_id = temp_match.group(1)
                        if temp_mal_id in state.metadata.anime_metadata and state.metadata.anime_metadata[temp_mal_id].get("title"):
                            needs_api_call = False
                
                if total_fetched > 0 and needs_api_call and delay+anidb_delay > 0: 
                    time.sleep(delay+anidb_delay)  # Delay to avoid API rate limits
                    anidb_delay = 0
                try:
                    fetch_metadata(filename, label=f"[{total_fetched+1}/{total_missing}]", batch_mode=True)  # Call your existing metadata function
                    if save_new_theme:
                        playlist_marks.toggle_theme("New Themes", filename=filename, quiet=True)
                    total_fetched += 1
                    files_since_last_save += 1
                    
                    # Periodic save every BATCH_SAVE_INTERVAL files
                    if files_since_last_save >= BATCH_SAVE_INTERVAL:
                        metadata_io.save_metadata()
                        build_filename_to_mal_map()
                        files_since_last_save = 0
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
                        if file_anidb_refresh[0] not in state.metadata.anidb_metadata:
                            refresh_anidb_data(file_anidb_refresh[0], file_anidb_refresh[1], label=f"[{total_fetched+1}/{total_missing}]")
                        total_fetched += 1
                    else:
                        total_skipped += 1
                except Exception as e:
                    print(e)
                    time.sleep(3)  # Delay to avoid API rate limits
                    total_skipped += 1
            
            for anilist_id in refresh_anilist:
                try:
                    if anilist_id not in state.metadata.anilist_metadata:
                        print(f"[{total_fetched+1}/{total_missing}] Fetching AniList metadata for ID {anilist_id}...", end=" ", flush=True)
                        _, anilist_data = fetch_anilist_metadata(anilist_id=anilist_id)
                        if anilist_data:
                            state.metadata.anilist_metadata[anilist_id] = anilist_data
                            print(f"✓ ({anilist_data.get('title', 'Unknown')})")
            
                            # Save all metadata after fetching
                            metadata_io.save_metadata()
                        else:
                            print("✗ Failed")
                        total_fetched += 1
                        time.sleep(1.0)
                except Exception as e:
                    print(f"✗ Error: {e}")
                    time.sleep(1.0)
                    total_skipped += 1

        # After all fetching is done, save any remaining unsaved changes
        if total_fetched > 0 and files_since_last_save > 0:
            metadata_io.save_metadata()
            build_filename_to_mal_map()
        elif total_fetched > 0:
            if not filename_to_mal:
                build_filename_to_mal_map()

        print("Metadata fetching complete! - Checked:" + str(total_checked) + " Missing:" + str(total_fetched+total_skipped) + " Skipped:" + str(total_skipped))
        if save_new_theme and total_fetched > 0:
            print(f"{total_fetched} files saved to state.metadata.playlist '{"New Themes"}'.")

    # Run in a separate thread so it doesn’t freeze the UI
    threading.Thread(target=fetch_all_metadata_worker, daemon=True).start()


def refresh_all_anilist_metadata(delay=2):
    """Refreshes all AniList metadata for files in the directory, spacing out API calls."""
    confirm = messagebox.askyesno("Refresh All AniList Metadata", "Are you sure you want to refresh all AniList metadata for files in your directory?")
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
                    print(f"Refreshing AniList metadata for files from {year_limit} onwards...")
                else:
                    print("Invalid input. Refreshing all AniList metadata...")
            except ValueError:
                print("Invalid input. Refreshing all AniList metadata...")
        else:
            print("Refreshing all AniList metadata...")
        
        # Get list of AniList IDs that we actually have files for
        anilist_ids_in_directory = set()
        for filename in state.metadata.directory_files:
            file_data = get_file_metadata_by_name(filename) or {}
            anilist_id = file_data.get('anilist')
            mal_id = file_data.get('mal')
            
            if year_limit is not None and mal_id and mal_id in state.metadata.anime_metadata:
                data = state.metadata.anime_metadata[mal_id]
                season = data.get("season", "")
                try:
                    season_year = int(season[-4:] if season and season[-4:].isdigit() else 0)
                    if season_year < year_limit:
                        continue
                except (ValueError, IndexError):
                    pass
            
            if anilist_id:
                anilist_ids_in_directory.add(str(anilist_id))
        
        total_to_refresh = len(anilist_ids_in_directory)
        total_refreshed = 0
        total_failed = 0
        
        print(f"Found {total_to_refresh} AniList entries to refresh from your directory files...")
        
        for anilist_id in sorted(anilist_ids_in_directory):
            try:
                print(f"[{total_refreshed + 1}/{total_to_refresh}] Refreshing AniList ID {anilist_id}...", end=" ", flush=True)
                _, anilist_data = fetch_anilist_metadata(anilist_id=anilist_id)
                if anilist_data:
                    state.metadata.anilist_metadata[anilist_id] = anilist_data
                    print(f"✓ ({anilist_data.get('title', 'Unknown')})")
                    total_refreshed += 1
                else:
                    print("✗ Failed")
                    total_failed += 1
                time.sleep(delay)
            except Exception as e:
                print(f"✗ Error: {e}")
                total_failed += 1
                time.sleep(delay)
        
        # Save metadata
        metadata_io.save_metadata()
        
        print(f"\nAniList metadata refresh complete! - Refreshed: {total_refreshed}/{total_to_refresh} - Failed: {total_failed}")

    # Run in a separate thread so it doesn't freeze the UI
    threading.Thread(target=worker, args=(year_input,), daemon=True).start()


def refresh_all_metadata(delay=1):
    """Refreshes all jikan metadata for files in the directory, spacing out API calls."""
    confirm = messagebox.askyesno("Refresh All Jikan Metadata", "Are you sure you want to refresh all jikan metadata for files in your directory?")
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
        for filename in state.metadata.directory_files:
            file_data = get_file_metadata_by_name(filename) or {}
            mal_id = file_data.get('mal')
            if mal_id and mal_id.isdigit():
                mal_ids_in_directory.add(mal_id)
        
        # Filter state.metadata.anime_metadata to only include entries we have files for
        entries_to_refresh = []
        for mal_id in mal_ids_in_directory:
            if mal_id in state.metadata.anime_metadata:
                data = state.metadata.anime_metadata[mal_id]
                season = data.get("season", "")
                
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


def refresh_all_igdb_metadata():
    """Refreshes all IGDB metadata for game files in the directory."""
    confirm = messagebox.askyesno("Refresh All IGDB Metadata", "Are you sure you want to refresh all IGDB metadata for game files in your directory?")
    if not confirm:
        return

    def worker():
        igdb_files = [fn for fn in state.metadata.directory_files if "[IGDB]" in fn]

        # Deduplicate by igdb_key so we report per-game, but process every file
        # so slugs, versions, and song tags are all registered correctly.
        seen_keys = {}
        for filename in igdb_files:
            fm = get_filename_metadata(filename)
            igdb_id = fm.get("igdb_id")
            if igdb_id:
                seen_keys.setdefault(f"IGDB:{igdb_id}", []).append(filename)

        total = len(seen_keys)
        if not total:
            print("No IGDB game files found in directory.")
            messagebox.showinfo("IGDB Refresh", "No IGDB game files found in directory.")
            return

        print(f"Refreshing IGDB metadata for {total} game(s) ({len(igdb_files)} file(s))...")
        refreshed = 0
        failed = 0
        for i, (igdb_key, filenames) in enumerate(seen_keys.items(), 1):
            try:
                title = (state.metadata.anime_metadata.get(igdb_key) or {}).get("title") or igdb_key
                print(f"[{i}/{total}] Refreshing {title} ({len(filenames)} file(s))...", flush=True)
                for filename in filenames:
                    fetch_metadata(filename, refetch=True)
                result_title = (state.metadata.anime_metadata.get(igdb_key) or {}).get("title", "Unknown")
                print(f"  ✓ {result_title}")
                refreshed += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  ✗ Error: {e}")
                failed += 1
                time.sleep(0.5)

        metadata_io.save_metadata()
        build_filename_to_mal_map()
        print(f"\nIGDB refresh complete! Refreshed: {refreshed}/{total}, Failed: {failed}")
        messagebox.showinfo("IGDB Refresh Complete", f"Refreshed {refreshed}/{total} IGDB entries.\nFailed: {failed}")

    threading.Thread(target=worker, daemon=True).start()



