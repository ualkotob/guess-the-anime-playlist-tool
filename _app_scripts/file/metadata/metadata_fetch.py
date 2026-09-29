"""
metadata_fetch.py
-----------------
Pure API-fetch functions and stateless computation helpers extracted from
guess_the_anime.py.  Nothing here reads or writes the main `metadata` /
`file_metadata` dicts – those stay in the host module.

State owned by this module
--------------------------
animethemes_cache   – in-process cache keyed by filename slug
last_tenrai_error    – last error string from fetch_tenrai_metadata (or None)
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
import _app_scripts.theme.anisongdb as anisongdb
import _app_scripts.theme.animethemes as animethemes_catalog
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

last_arm_lookup_succeeded = False
last_anilist_status = None
last_tenrai_error = None
last_tenrai_status = None
_tenrai_request_lock = threading.Lock()
_last_tenrai_request = 0.0
_TENRAI_MIN_REQUEST_INTERVAL = 0.5  # Leave headroom below the public rate limit.

_MISSING_METADATA_RETRY_DAYS = 30
_MISSING_METADATA_RETRY_SECONDS = _MISSING_METADATA_RETRY_DAYS * 24 * 60 * 60
_FETCH_FAILURES_KEY = "metadata_fetch_failures"

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
    global last_arm_lookup_succeeded
    last_arm_lookup_succeeded = False
    try:
        response = requests.get(
            "https://arm.haglund.dev/api/v2/ids",
            params={"source": "myanimelist", "id": str(mal_id)},
            timeout=5
        )
        if response.status_code != 200:
            return {}
        data = response.json()
        last_arm_lookup_succeeded = isinstance(data, dict)
        if not last_arm_lookup_succeeded:
            return {}
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
    catalog_match = animethemes_catalog.find_anime(
        filename=filename,
        mal_id=mal_id,
        split=split,
    )
    if catalog_match:
        if filename:
            animethemes_cache[filename] = catalog_match
        return catalog_match

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
# Tenrai (MyAnimeList)
# ---------------------------------------------------------------------------

def fetch_tenrai_metadata(mal_id):
    global last_tenrai_error, last_tenrai_status, _last_tenrai_request
    last_tenrai_error = None
    last_tenrai_status = None
    url = f"https://api.tenrai.org/v1/anime/{mal_id}/full"
    try:
        with _tenrai_request_lock:
            wait_seconds = _TENRAI_MIN_REQUEST_INTERVAL - (time.monotonic() - _last_tenrai_request)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            _last_tenrai_request = time.monotonic()
        response = requests.get(url, timeout=12)
        if response.status_code == 200:
            data = response.json()
            if data.get("data"):
                last_tenrai_status = "success"
                return data["data"]
            last_tenrai_error = f"Tenrai returned 200 but no data payload for MAL {mal_id}"
            last_tenrai_status = "transient"
            return None

        if response.status_code == 404:
            last_tenrai_status = "not_found"
            last_tenrai_error = f"Tenrai request failed (404) for MAL {mal_id}"
        elif response.status_code == 429:
            last_tenrai_status = "transient"
            retry_after = response.headers.get("Retry-After")
            last_tenrai_error = f"Tenrai rate-limited (429) for MAL {mal_id}" + (f", Retry-After={retry_after}s" if retry_after else "")
        elif 500 <= response.status_code <= 599:
            last_tenrai_status = "transient"
            last_tenrai_error = f"Tenrai server error ({response.status_code}) for MAL {mal_id}"
        else:
            last_tenrai_status = "transient"
            last_tenrai_error = f"Tenrai request failed ({response.status_code}) for MAL {mal_id}"
    except requests.exceptions.Timeout:
        last_tenrai_status = "transient"
        last_tenrai_error = f"Tenrai timeout for MAL {mal_id}"
    except requests.exceptions.RequestException as e:
        last_tenrai_status = "transient"
        last_tenrai_error = f"Tenrai network error for MAL {mal_id}: {e}"
    except Exception as e:
        last_tenrai_status = "transient"
        last_tenrai_error = f"Unexpected Tenrai error for MAL {mal_id}: {e}"

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


class AniDBResponseError(RuntimeError):
    """AniDB returned a valid HTTP response containing an API error."""


class AniDBCooldownError(AniDBResponseError):
    """AniDB explicitly reported that this client/IP is temporarily banned."""


def _valid_provider_id(value):
    """Return whether a linked AniList/AniDB ID is a positive integer."""
    text = str(value or "").strip()
    return text.isdigit() and int(text) > 0


def fetch_anidb_metadata(aid):
    if not _valid_provider_id(aid):
        raise AniDBResponseError(f"Invalid AniDB ID: {aid}")

    url = "http://api.anidb.net:9001/httpapi"
    params = {
        "request": "anime",
        "client": "guesstheanime",
        "clientver": "1",
        "protover": "1",
        "aid": str(aid)
    }

    response = requests.get(url, params=params, timeout=30)
    if not response.ok:
        if response.status_code in (403, 429):
            raise AniDBCooldownError(
                f"AniDB access blocked ({response.status_code})"
            )
        raise Exception(f"AniDB request failed: {response.status_code}")

    root = ET.fromstring(response.text)
    if root.tag.casefold() == "error":
        error_code = str(root.get("code") or "").strip()
        error_message = " ".join("".join(root.itertext()).split()) or "Unknown error"
        if error_code == "500" or "banned" in error_message.casefold():
            raise AniDBCooldownError(
                f"AniDB temporarily banned this client ({error_message})"
            )
        code_suffix = f" [{error_code}]" if error_code else ""
        raise AniDBResponseError(f"AniDB API error{code_suffix}: {error_message}")
    if root.tag.casefold() != "anime":
        raise AniDBResponseError(f"Unexpected AniDB response: <{root.tag}>")

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
    global last_anilist_status
    last_anilist_status = None
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
            lookup_label = (
                f"MAL {mal_id}" if mal_id is not None else f"AniList {anilist_id}"
            )
            if response.status_code == 404:
                last_anilist_status = "not_found"
                print(f"AniList has no anime entry for {lookup_label}.", end=" ")
            else:
                last_anilist_status = "transient"
                print(f"AniList API error for {lookup_label}: {response.text}")
            return None, None

        data = response.json()
        media = data.get("data", {}).get("Media")
        
        if not media:
            last_anilist_status = "not_found"
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

        last_anilist_status = "success"
        return resolved_anilist_id, metadata

    except Exception as e:
        last_anilist_status = "transient"
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


def invalidate_metadata_cache(filenames=None):
    """Clear merged metadata results for all files or selected filenames."""
    if filenames is None:
        _metadata_cache.clear()
        return
    for filename in filenames:
        _metadata_cache.pop(filename, None)


def _filename_theme_slug(filename):
    """Return the OP/ED slug encoded in a conventional theme filename."""
    basename = os.path.splitext(os.path.basename(filename))[0]
    match = re.search(r"(?:^|-)(OP|ED)(\d+)(?=(?:v\d+)?(?:[-_.]|$))", basename, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1).upper()}{match.group(2)}"


def _store_filename_lookup(key, candidate, *, overwrite_ties):
    """Store a lookup candidate, preferring metadata that agrees with the filename."""
    existing = filename_to_mal.get(key)
    if existing is None:
        filename_to_mal[key] = candidate
        return

    filename_slug = _filename_theme_slug(key)
    existing_matches = existing.get("slug", "").upper() == filename_slug
    candidate_matches = candidate.get("slug", "").upper() == filename_slug
    if candidate_matches != existing_matches:
        if candidate_matches:
            filename_to_mal[key] = candidate
    elif bool(existing.get("anisongdb_alternate")) != bool(
        candidate.get("anisongdb_alternate")
    ):
        # One AniSongDB media file can occasionally be linked to multiple
        # anime/slugs. A gap/source-pool registration must win over a covered
        # theme's alternate-only registration for global filename lookup.
        if not candidate.get("anisongdb_alternate"):
            filename_to_mal[key] = candidate
    elif overwrite_ties:
        filename_to_mal[key] = candidate




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
                for filename, properties in version_data.items():
                    lookup_data = {
                        "mal_id": mal_id,
                        "slug": slug,
                        "version": version,
                        "anisongdb_alternate": bool(
                            isinstance(properties, dict)
                            and properties.get("anisongdb_alternate")
                        ),
                    }
                    # A file can occasionally be listed under multiple metadata
                    # slugs.  In that case, prefer the slug encoded in its name
                    # (for example, Foo-OP1.webm should resolve as OP1 even if it
                    # is also present under ED1).
                    _store_filename_lookup(filename, lookup_data, overwrite_ties=True)
                    actual_file_count += 1
                    # Also store base name without extension for lookup
                    base_name = os.path.splitext(filename)[0]
                    _store_filename_lookup(base_name, lookup_data, overwrite_ties=False)
    
    return actual_file_count


def get_metadata(filename, refresh=False, refresh_all=False, fetch=False):
    global fetched_metadata
    # Lazy import: variety_round imports metadata_fetch, so a module-level import would cycle.
    import _app_scripts.queue_round.lightning_rounds.variety_round as variety_round

    if not filename:
        return {}

    if not (refresh or fetch) and filename in _metadata_cache:
        return _metadata_cache[filename]

    file_data = get_file_metadata_by_name(filename)
    if not file_data and not ("-OP" in filename or "-ED" in filename):
        return fetch_metadata(filename, refetch=refresh) if fetch else {}
    if not file_data:
        return fetch_metadata(filename, refetch=refresh) if fetch else {}
    properties = file_data.get("file_properties") or {}
    if properties.get("source") == "ANISONGDB" and not anisongdb.has_catalog():
        try:
            anisongdb.ensure_catalog(download=fetch or refresh)
        except Exception as exc:
            print(f"AniSongDB catalog lookup failed: {exc}")

    mal_id = file_data.get('mal')
    anidb_id = file_data.get('anidb')
    anilist_id = file_data.get('anilist')
    anime_data = state.metadata.anime_metadata.get(mal_id) or {}
    anidb_data = (
        state.metadata.anidb_metadata.get(str(anidb_id), {})
        if _valid_provider_id(anidb_id)
        else {}
    )
    ai_data = state.metadata.ai_metadata.get(mal_id, {}) if mal_id else {}
    re_queue_lightning_mode = False
    if anime_data and "-[ID]" not in filename and mal_id:
        if refresh and mal_id not in fetched_metadata and (refresh_all or (state.controls.auto_refresh_toggle and fetch)):
            fetched_metadata.add(mal_id)
            refresh_tenrai_data(mal_id, anime_data)
            if state.lightning.light_mode:
                re_queue_lightning_mode = True
        if refresh and fetch and _valid_provider_id(anidb_id) and (str(anidb_id) not in state.metadata.anidb_metadata or state.controls.auto_refresh_toggle) and not anidb_cooldown and (variety_round.variety_light_mode_enabled or state.lightning.light_mode in ['characters', 'tags', 'episodes', 'names'] or (state.lightning.light_mode and "c." in state.lightning.light_mode)):
            refresh_anidb_data(str(anidb_id), anime_data)
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
    # Normal list/playlist lookups stay lightweight. The raw catalog retains
    # the complete record, which explicit fetch/detail paths expand on demand.
    anisongdb.apply_full_metadata(filename, result, include_full=False)
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
        version_str = str(version) if version is not None else "null"
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
    for key in ["mal", "anidb", "anilist", "kitsu", "anisongdb_ann_id"]:
        if key in entry:
            ordered_entry[key] = entry[key]
    
    # 3. Provider retry state (optional)
    if _FETCH_FAILURES_KEY in entry:
        ordered_entry[_FETCH_FAILURES_KEY] = entry[_FETCH_FAILURES_KEY]

    # 4. AnimThemes IDs (optional)
    for key in ["animethemes_id", "animethemes_slug"]:
        if key in entry:
            ordered_entry[key] = entry[key]

    # 5. Themes last
    if "themes" in entry:
        ordered_entry["themes"] = entry["themes"]
    
    # Replace the entry with ordered version
    state.metadata.file_metadata[mal_id] = ordered_entry

anidb_cooldown = False
fetching_metadata = {}


def _theme_song_hints(data, slug):
    """Return an existing song title and artist list for one theme slug."""
    for theme in (data or {}).get("animethemes", []):
        if theme.get("slug") != slug:
            continue
        song = theme.get("song") or {}
        artists = [
            artist.get("name")
            for artist in song.get("artists") or []
            if isinstance(artist, dict) and artist.get("name")
        ]
        return song.get("title"), artists
    return None, []


def _append_manual_song_theme(data, slug, title, artists):
    """Append the file-specific answer row after provider-wide theme rows."""
    if not slug or (not title and not artists):
        return
    data.setdefault("animethemes", []).append({
        "type": slug[:2],
        "slug": slug,
        "song": {
            "title": title,
            "artists": [{"name": artist} for artist in artists],
        },
        "animethemeentries": [],
    })


def _metadata_failure_deferred(file_data, source, identity, *, now=None):
    """Return whether a confirmed absence is still inside its retry window."""
    if not isinstance(file_data, dict):
        return False
    record = (file_data.get(_FETCH_FAILURES_KEY) or {}).get(source)
    if not isinstance(record, dict) or record.get("status") != "not_found":
        return False
    if str(record.get("identity")) != str(identity):
        return False
    try:
        retry_after = float(record.get("retry_after"))
    except (TypeError, ValueError):
        return False
    return retry_after > (time.time() if now is None else now)


def _record_metadata_absence(file_data, source, identity, *, now=None):
    """Persist a confirmed provider absence and return whether data changed."""
    if not isinstance(file_data, dict):
        return False
    checked_at = int(time.time() if now is None else now)
    record = {
        "status": "not_found",
        "identity": str(identity),
        "checked_at": checked_at,
        "retry_after": checked_at + _MISSING_METADATA_RETRY_SECONDS,
    }
    failures = file_data.setdefault(_FETCH_FAILURES_KEY, {})
    changed = failures.get(source) != record
    failures[source] = record
    return changed


def _clear_metadata_absence(file_data, source):
    """Remove stale negative state after a provider becomes available."""
    if not isinstance(file_data, dict):
        return False
    failures = file_data.get(_FETCH_FAILURES_KEY)
    if not isinstance(failures, dict) or source not in failures:
        return False
    failures.pop(source, None)
    if not failures:
        file_data.pop(_FETCH_FAILURES_KEY, None)
    return True


def _file_entries_for_provider_id(provider, identity):
    """Yield every file-metadata row referring to one provider identity."""
    identity = str(identity)
    for entry_key, file_data in state.metadata.file_metadata.items():
        if not isinstance(file_data, dict):
            continue
        value = file_data.get(provider)
        if provider == "mal":
            value = value or entry_key
        if str(value) == identity:
            yield file_data


def _record_absence_for_provider_id(provider, identity, source):
    return sum(
        _record_metadata_absence(file_data, source, identity)
        for file_data in _file_entries_for_provider_id(provider, identity)
    )


def _clear_absence_for_provider_id(provider, identity, source):
    return sum(
        _clear_metadata_absence(file_data, source)
        for file_data in _file_entries_for_provider_id(provider, identity)
    )


def _mal_metadata_missing(data):
    """Return whether an anime row is only a stub rather than fetched MAL data."""
    if not isinstance(data, dict) or not data.get("title"):
        return True
    # AniSongDB projections intentionally provide a useful title/season, but
    # not these MAL fields. Checking key presence (rather than truthiness)
    # avoids repeatedly fetching legitimate null values from the API.
    return any(
        key not in data
        for key in ("aired", "members", "studios", "synopsis")
    )


def _anilist_metadata_missing(anilist_id):
    if not _valid_provider_id(anilist_id):
        return True
    data = state.metadata.anilist_metadata.get(str(anilist_id))
    return not isinstance(data, dict) or any(
        key not in data for key in ("title", "tags", "characters")
    )


def _anidb_metadata_missing(anidb_id):
    if not _valid_provider_id(anidb_id):
        return True
    data = state.metadata.anidb_metadata.get(str(anidb_id))
    return not isinstance(data, dict) or any(
        key not in data for key in ("tags", "characters", "episode_info")
    )


def _linked_metadata_complete(file_data, anime_data):
    """Return whether a known theme has all three linked metadata sources."""
    if _mal_metadata_missing(anime_data):
        return False
    anilist_id = file_data.get("anilist")
    anidb_id = file_data.get("anidb")
    if not _valid_provider_id(anilist_id) or not _valid_provider_id(anidb_id):
        return False
    return not _anilist_metadata_missing(anilist_id) and not _anidb_metadata_missing(anidb_id)


def _linked_id_resolution_status(missing_before, file_data):
    """Describe which absent provider IDs were resolved by a lookup attempt."""
    labels = {"anilist": "AniList", "anidb": "AniDB"}
    resolved = [
        labels[key] for key in missing_before if _valid_provider_id(file_data.get(key))
    ]
    unavailable = [
        labels[key]
        for key in missing_before
        if not _valid_provider_id(file_data.get(key))
    ]

    if unavailable:
        parts = []
        if resolved:
            parts.append(f"Resolved {', '.join(resolved)}")
        parts.append(f"{', '.join(unavailable)} unavailable")
        marker = "⚠" if resolved else "✗"
        return f"{marker} {'; '.join(parts)}", False

    return f"✓ Resolved {', '.join(resolved)}", True


def _collect_missing_metadata_targets():
    """Collect missing linked metadata once per known anime.

    The source set is file_metadata rather than directory_files so a
    metadata-only/streaming library receives the same enrichment as local
    downloads. Physical files with no registration are handled separately by
    ``fetch_all_metadata``.
    """
    mal_targets = []
    anilist_targets = []
    anidb_targets = []
    resolve_id_targets = []
    seen_mal = set()
    seen_anilist = set()
    seen_anidb = set()
    deferred = 0

    for entry_key, file_data in state.metadata.file_metadata.items():
        if not isinstance(file_data, dict):
            continue
        mal_id = file_data.get("mal") or entry_key
        mal_id = str(mal_id)
        if not mal_id.isdigit() or mal_id in seen_mal:
            continue
        seen_mal.add(mal_id)

        anime_data = state.metadata.anime_metadata.get(mal_id)
        if _mal_metadata_missing(anime_data):
            if _metadata_failure_deferred(file_data, "tenrai", mal_id):
                deferred += 1
            else:
                mal_targets.append((mal_id, anime_data))

        raw_anilist_id = file_data.get("anilist")
        raw_anidb_id = file_data.get("anidb")
        anilist_id = str(raw_anilist_id) if _valid_provider_id(raw_anilist_id) else None
        anidb_id = str(raw_anidb_id) if _valid_provider_id(raw_anidb_id) else None
        if anilist_id is not None:
            anilist_id = str(anilist_id)
            if _anilist_metadata_missing(anilist_id) and anilist_id not in seen_anilist:
                seen_anilist.add(anilist_id)
                if _metadata_failure_deferred(
                    file_data, "anilist_metadata", anilist_id
                ):
                    deferred += 1
                else:
                    anilist_targets.append(anilist_id)
        if anidb_id is not None:
            anidb_id = str(anidb_id)
            if _anidb_metadata_missing(anidb_id) and anidb_id not in seen_anidb:
                seen_anidb.add(anidb_id)
                anidb_targets.append((anidb_id, mal_id))
        missing_link_sources = []
        if not anilist_id:
            if _metadata_failure_deferred(file_data, "linked_anilist", mal_id):
                deferred += 1
            else:
                missing_link_sources.append("anilist")
        if not anidb_id:
            if _metadata_failure_deferred(file_data, "linked_anidb", mal_id):
                deferred += 1
            else:
                missing_link_sources.append("anidb")
        if missing_link_sources:
            resolve_id_targets.append((mal_id, file_data))

    return {
        "mal": mal_targets,
        "anilist": anilist_targets,
        "anidb": anidb_targets,
        "resolve_ids": resolve_id_targets,
        "known_anime": len(seen_mal),
        "deferred": deferred,
    }


def fetch_metadata(filename=None, refetch=False, label="", batch_mode=False):
    """Fetch one file's metadata and always release its in-flight marker."""
    if filename is None:
        playlist_entry = entry_paths.get_clean_filename(state.metadata.playlist["playlist"][state.metadata.playlist["current_index"]])
        filename = os.path.basename(playlist_entry) if os.path.isabs(playlist_entry) else playlist_entry
        refetch = True

    try:
        return _fetch_metadata_impl(filename, refetch, label, batch_mode)
    finally:
        fetching_metadata.pop(filename, None)


def _fetch_metadata_impl(filename, refetch=False, label="", batch_mode=False):
    global anidb_cooldown, anidb_delay

    print(f"{label}Fetching metadata for {filename}...", end="", flush=True)

    fetching_metadata[filename] = True
    
    if not refetch and filename in filename_to_mal:
        lookup_data = filename_to_mal[filename]
        mal_id = lookup_data["mal_id"]
        slug = lookup_data["slug"]
        version = lookup_data["version"]
        
        anime_data = state.metadata.anime_metadata.get(mal_id)
        file_data = get_file_metadata_by_name(filename) or {}
        if (
            anime_data
            and anime_data.get("title")
            and _linked_metadata_complete(file_data, anime_data)
        ):
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
            anisongdb.apply_full_metadata(filename, data)
            
            if state.playback.currently_playing.get('filename') == filename:
                state.playback.currently_playing["data"] = data
                metadata_panel.update_metadata()
            
            print(f"\r{label}Fetching metadata for {filename}...COMPLETE")
            return data
    
    slug = _filename_theme_slug(filename)
    version = None
    mal_id = None
    anidb_id = None
    anilist_id = None
    anime_themes = None
    is_animethemes_file = False
    anisong_song = None
    anisong_fallback_song = None
    filename_source = anisongdb.classify_filename(filename)

    # Classify from the filename first. AniSongDB candidates are then confirmed
    # against the catalog; obvious manual files never enter either provider.
    try:
        if filename_source == anisongdb.SOURCE_ANISONGDB:
            anisong_song = anisongdb.find_song(filename, download_catalog=True)
        elif filename_source != anisongdb.SOURCE_MANUAL and anisongdb.has_catalog():
            anisong_song = anisongdb.find_song(filename)
    except Exception as exc:
        print(f" [AniSongDB lookup failed: {exc}]", end="")

    if anisong_song:
        anisongdb.register_detected_file(filename, anisong_song)
        anime_row = anisongdb.normalize_song(anisong_song).get("anime", {})
        linked_ids = anime_row.get("linked_ids", {})
        mal_id = str(linked_ids.get("myanimelist")) if linked_ids.get("myanimelist") is not None else None
        anidb_id = str(linked_ids.get("anidb")) if linked_ids.get("anidb") is not None else None
        anilist_id = str(linked_ids.get("anilist")) if linked_ids.get("anilist") is not None else None
        slug = anisongdb.theme_slug(anisong_song)
        version = 1
        anime_themes = {
            "name": anime_row.get("animeJPName") or anime_row.get("animeENName"),
            "season": anime_row.get("animeVintage"),
            "media_format": anime_row.get("animeType"),
            "animethemes": [],
        }
    
    elif filename_source == anisongdb.SOURCE_ANISONGDB:
        # It had AniSongDB's structure but could not be confirmed. Do not send
        # it to AnimeThemes under a misleading basename.
        anime_themes = {}

    elif re.search(r"\[IGDB\]", filename, re.IGNORECASE):
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
                        "aired": "N/A", "season": "N/A", "score": None,
                        "rank": None, "members": None, "popularity": None,
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

    elif filename_source != anisongdb.SOURCE_MANUAL:
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
    elif re.search(r"\[MAL\]", filename, re.IGNORECASE):
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
        existing_title, existing_artists = _theme_song_hints(anime_themes, slug)
        explicit_title = filename_metadata.get("song")
        explicit_artists = [
            artist.strip()
            for artist in (filename_metadata.get("artist") or "").split("+")
            if artist.strip()
        ]
        title_hint = explicit_title or existing_title
        artist_hints = explicit_artists or existing_artists
        missing_answer_data = not title_hint or not artist_hints
        if mal_id and slug and (anisongdb.has_catalog() or missing_answer_data):
            try:
                anisong_fallback_song = anisongdb.resolve_song_for_mal_slug(
                    mal_id,
                    slug,
                    title=title_hint,
                    artists=artist_hints,
                    download_catalog=missing_answer_data,
                )
            except Exception as exc:
                print(f" [AniSongDB MAL/slug lookup failed: {exc}]", end="")

        fallback_data = (
            anisongdb.song_metadata(anisong_fallback_song)
            if anisong_fallback_song
            else {}
        )
        final_title = explicit_title or existing_title or fallback_data.get("title")
        final_artists = explicit_artists or existing_artists or fallback_data.get("artist") or []
        if anisong_fallback_song or explicit_title or explicit_artists:
            _append_manual_song_theme(
                anime_themes,
                slug,
                final_title,
                final_artists,
            )
        if filename_metadata.get("season"):
            anime_themes["season"] = filename_metadata["season"]
            anime_themes["year"] = filename_metadata["year"]
    else:
        # [ID] file
        mal_id = re.search(r"\[ID](.*?)(?=\[|$|\.)", filename, re.IGNORECASE).group(1)
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
        if re.search(r"\[(?:ID|MAL)\]", filename, re.IGNORECASE) and slug:
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
            if anisong_fallback_song:
                file_properties = mal_entry["themes"][slug][version_key][filename]
                file_properties.update(anisongdb.file_identity(anisong_fallback_song))
                mal_entry["anisongdb_ann_id"] = anisong_fallback_song.get("annId")
                fallback_ids = anisongdb.linked_ids(anisong_fallback_song)
                for key in ("anidb", "anilist", "kitsu"):
                    if fallback_ids.get(key) is not None and not mal_entry.get(key):
                        mal_entry[key] = str(fallback_ids[key])
        
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
        if refetch or _mal_metadata_missing(anime_data):
            tenrai_data = fetch_tenrai_metadata(mal_id)
            if tenrai_data:
                anime_data = {
                    "title":tenrai_data.get("title"),
                    "eng_title":tenrai_data.get("title_english", "N/A"),
                    "synonyms":tenrai_data.get("title_synonyms", []),
                    "series":get_name_list(anime_themes, "series"),
                    "aired": tenrai_data.get("aired", []).get("string"),
                    "season":str(tenrai_data.get("season") or "N/A") + " " + str(tenrai_data.get("year") or "N/A"),
                    "score":tenrai_data.get("score"),
                    "rank":tenrai_data.get("rank"),
                    "members":tenrai_data.get("members"),
                    "popularity":tenrai_data.get("popularity"),
                    "type":tenrai_data.get("type", "N/A"),
                    "source":tenrai_data.get("source", "N/A"),
                    "episodes":tenrai_data.get("episodes", "N/A"),
                    "studios":get_name_list(tenrai_data, "studios"),
                    "genres":get_name_list(tenrai_data, "genres"),
                    "themes":get_name_list(tenrai_data, "themes"),
                    "demographics":get_name_list(tenrai_data, "demographics"),
                    "synopsis":tenrai_data.get('synopsis', "N/A"),
                    "cover":tenrai_data.get("images", {}).get("jpg", {}).get("large_image_url"),
                    "trailer":youtube_control.extract_youtube_id_from_trailer(tenrai_data.get("trailer", {}))
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
                        "score": None,
                        "rank": None,
                        "members": None,
                        "popularity": None,
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
                _tenrai_reason = f" ({last_tenrai_error})" if last_tenrai_error else ""
                print(f" [META DBG] Tenrai missing/unavailable for MAL {mal_id}{_tenrai_reason}; using minimal AniThemes-derived metadata", end="")
        anilist_fetched = False
        if not _valid_provider_id(anilist_id) and mal_id and (refetch or mal_id not in state.metadata.file_metadata or not _valid_provider_id(state.metadata.file_metadata[mal_id].get("anilist"))):
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
                    if not _valid_provider_id(anidb_id) and anilist_data.get("anidb_id"):
                        anidb_id = anilist_data["anidb_id"]
                        if mal_id in state.metadata.file_metadata:
                            state.metadata.file_metadata[mal_id]["anidb"] = anidb_id
                    # Clear any cached metadata for files under this mal_id so new IDs are picked up
                    for cached_fn, cached_ref in list(filename_to_mal.items()):
                        if cached_ref.get("mal_id") == mal_id:
                            _metadata_cache.pop(cached_fn, None)
            except Exception as e:
                print(f" [AniList MAL-lookup ✗: {e}]", end="")

        if _valid_provider_id(anidb_id):
            anidb_id = str(anidb_id)
            anidb_data = state.metadata.anidb_metadata.get(anidb_id, {})
            if refetch or not anidb_data.get("characters") or not anidb_data.get("tags") or not anidb_data.get("episode_info"):
                if not anidb_cooldown:
                    try:
                        anidb = fetch_anidb_metadata(anidb_id)
                    except AniDBCooldownError as exc:
                        anidb_cooldown = True
                        print(f"[AniDB cooldown: {exc}]")
                    except AniDBResponseError as exc:
                        print(f"[AniDB unavailable: {exc}]")
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
            if anisong_song:
                # A Tenrai refresh may replace the dict. Restore AniSongDB's
                # source-specific anime fields and exact song identity.
                anisongdb.register_detected_file(filename, anisong_song)
                anime_data = state.metadata.anime_metadata.get(mal_id, anime_data)
            # Get new songs from the current fetch
            new_songs = get_theme_list(anime_themes, slug, version)
            # Avoid duplicates by slug (new wins), then sort
            all_songs = list({song["slug"]: song for song in old_songs + new_songs}.values())
            anime_data["songs"] = sort_songs(all_songs)
            anime_data["series"] = get_name_list(anime_themes, "series") or state.metadata.anime_metadata_overrides.get(mal_id, {}).get("series") or anime_data.get("series")
            # Store updated anime_data back into state.metadata.anime_metadata before saving
            # This ensures overrides can be applied to the updated data
            state.metadata.anime_metadata[mal_id] = anime_data
            if anisong_fallback_song:
                anisongdb.merge_song_metadata(mal_id, anisong_fallback_song)
                anime_data = state.metadata.anime_metadata[mal_id]
        
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
        anisongdb.apply_full_metadata(filename, data)
        
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
    """Extract IDs, artist, and song name from optional bracketed tags."""
    metadata = {
        "mal_id": None,
        "anidb_id": None,
        "igdb_id": None,
        "anisongdb_amq_song_id": None,
        "anisongdb_ann_song_id": None,
        "artist": None,
        "song": None,
    }
    
    mal_match = re.search(r"\[MAL](\d+)", filename, re.IGNORECASE)
    anidb_match = re.search(r"\[ADB](\d+)", filename, re.IGNORECASE)
    anilist_match = re.search(r"\[ALT](\d+)", filename, re.IGNORECASE)
    igdb_match = re.search(r"\[IGDB]([A-Za-z0-9][A-Za-z0-9-]*)", filename, re.IGNORECASE)
    artist_match = re.search(r"\[ART](.*?)(?=\[|$|\.)", filename, re.IGNORECASE)
    song_match = re.search(r"\[SNG](.*?)(?=\[|$|\.)", filename, re.IGNORECASE)
    amq_match = re.search(r"\[(?:ASDB|AMQ)](\d+)", filename, re.IGNORECASE)
    ann_song_match = re.search(r"\[ANNSONG](\d+)", filename, re.IGNORECASE)
    
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

    if amq_match:
        metadata["anisongdb_amq_song_id"] = amq_match.group(1)

    if ann_song_match:
        metadata["anisongdb_ann_song_id"] = ann_song_match.group(1)

    season_year = get_last_two_folders(state.metadata.directory_files.get(filename))
    season = season_year[1]
    year = season_year[0]
    if season in ['Winter','Spring','Summer','Fall']:
        metadata["season"] = season
        metadata["year"] = year
    return metadata


def refresh_tenrai_data(mal_id, data, label=""):
    title = data.get('title', f"MAL ID: {mal_id}")
    print(f"{label}Refreshing Tenrai data for {title}...", end="", flush=True)
    
    tenrai_data = fetch_tenrai_metadata(mal_id)
    if tenrai_data:
        data["title"] = tenrai_data.get("title", "N/A")
        data["eng_title"] = tenrai_data.get("title_english", "N/A")
        data["synonyms"] = tenrai_data.get("title_synonyms", [])
        data["aired"] = tenrai_data.get("aired", []).get("string")
        data["score"] = tenrai_data.get("score")
        data["rank"] = tenrai_data.get("rank")
        data["members"] = tenrai_data.get("members")
        data["popularity"] = tenrai_data.get("popularity")
        data["type"] = tenrai_data.get("type", "N/A")
        data["source"] = tenrai_data.get("source", "N/A")
        data["episodes"] = tenrai_data.get("episodes", "N/A")
        data["studios"] = get_name_list(tenrai_data, "studios")
        data["genres"] = get_name_list(tenrai_data, "genres")
        data["themes"] = get_name_list(tenrai_data, "themes")
        data["demographics"] = get_name_list(tenrai_data, "demographics")
        data["synopsis"] = tenrai_data.get("synopsis", "N/A")
        data["cover"] = tenrai_data.get("images", {}).get("jpg", {}).get("large_image_url")
        data["trailer"] = youtube_control.extract_youtube_id_from_trailer(tenrai_data.get("trailer", {}))
        
        metadata_io.save_metadata()
        print(f"\r{label}Refreshing Tenrai data for {data['title']}...COMPLETE")
    else:
        _reason = f" ({last_tenrai_error})" if last_tenrai_error else ""
        print(f"\r{label}Refreshing Tenrai data for {title}...FAILED{_reason}")


def refresh_anidb_data(anidb_id, data, label=""):
    global anidb_cooldown, anidb_delay

    fetch_string = "Refreshing"
    if anidb_id not in state.metadata.anidb_metadata:
        fetch_string = "Fetching"
    print(f"{label}{fetch_string} aniDB data for {data['title']}...", end="", flush=True)
    
    try:
        anidb = fetch_anidb_metadata(anidb_id)
    except AniDBCooldownError as exc:
        anidb_cooldown = True
        print(
            f"\r{label}{fetch_string} aniDB data for {data['title']}..."
            f"FAILED [{exc}]"
        )
        return False
    except AniDBResponseError as exc:
        print(
            f"\r{label}{fetch_string} aniDB data for {data['title']}..."
            f"FAILED [{exc}]"
        )
        return False

    mal_id = data.get("mal")
    anidb_entry = {
        "tags": anidb["tags"],
        "characters": anidb["characters"],
        "episode_info": anidb["episodes"],
    }

    if mal_id:
        state.metadata.anidb_metadata[anidb_id] = {"mal_id": mal_id}
        state.metadata.anidb_metadata[anidb_id].update(anidb_entry)
    else:
        state.metadata.anidb_metadata[anidb_id] = anidb_entry

    metadata_io.save_metadata()
    anidb_delay = 5
    print(f"\r{label}{fetch_string} aniDB data for {data['title']}...COMPLETE")
    return True


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
    """Fetch missing MAL, AniList, and AniDB data for every known anime."""
    directory_scan.scan_directory()
    preview = _collect_missing_metadata_targets()
    unregistered_files = sum(
        1
        for filename in state.metadata.directory_files
        if not get_file_metadata_by_name(filename)
    )
    known_missing = sum(
        len(preview[key])
        for key in ("mal", "anilist", "anidb", "resolve_ids")
    )
    if not known_missing and not unregistered_files:
        deferred_note = (
            f"\n\n{preview['deferred']:,} confirmed unavailable checks are "
            f"deferred for up to {_MISSING_METADATA_RETRY_DAYS} days."
            if preview["deferred"]
            else ""
        )
        messagebox.showinfo(
            "Fetch All Missing Metadata",
            "No currently retryable MAL, AniList, AniDB, or file metadata "
            f"was found.{deferred_note}",
        )
        return

    anidb_hours = len(preview["anidb"]) * 5 / 3600
    confirm = messagebox.askyesno(
        "Fetch All Missing Metadata",
        "Fetch missing MAL, AniList, and AniDB metadata for every known "
        "theme?\n\n"
        f"MAL entries: {len(preview['mal']):,}\n"
        f"AniList entries: {len(preview['anilist']):,}\n"
        f"AniDB entries: {len(preview['anidb']):,}\n"
        f"Missing ID mappings: {len(preview['resolve_ids']):,}\n"
        f"Deferred unavailable checks: {preview['deferred']:,}\n"
        f"Unregistered local files: {unregistered_files:,}\n\n"
        "This includes local files and metadata-only streaming themes. "
        "The work is saved as it progresses and can be resumed by running "
        "this again. Confirmed unavailable records are retried automatically "
        f"after {_MISSING_METADATA_RETRY_DAYS} days. Large AniSongDB collections "
        "can take a long time. "
        f"The currently missing AniDB entries alone require at least about "
        f"{anidb_hours:.1f} hours because its API must be queried slowly.",
    )
    if not confirm:
        return  # User canceled
    # Lazy import: infinite imports metadata_fetch, so a module-level import
    # here would create a cycle.
    import _app_scripts.playlists.infinite as infinite
    infinite.reset_infinite_caches()
    def fetch_all_metadata_worker():
        global anidb_cooldown, anidb_delay
        # A cooldown belongs to the previous run, not the lifetime of the app.
        # Retrying the command later should not require restarting the process.
        anidb_cooldown = False
        total_checked = 0
        total_fetched = 0
        total_skipped = 0
        total_missing = 0
        save_new_theme = False

        def progress_label():
            processed = total_fetched + total_skipped
            return f"[{processed + 1}/{total_missing}]"

        targets = _collect_missing_metadata_targets()
        refresh_tenrai = list(targets["mal"])
        refresh_anidb = list(targets["anidb"])
        refresh_anilist = list(targets["anilist"])
        resolve_ids = list(targets["resolve_ids"])
        fetch_data = []
        files_since_last_save = 0
        print(
            f"{targets['known_anime']} known anime and "
            f"{len(state.metadata.directory_files)} local files found; "
            "checking for missing linked metadata..."
        )
        for filename in state.metadata.directory_files:
            total_checked += 1
            file_data = get_file_metadata_by_name(filename)
            if not file_data:
                fetch_data.append(filename)
        total_checked += targets["known_anime"]
        total_missing = (
            len(fetch_data)
            + len(refresh_tenrai)
            + len(refresh_anidb)
            + len(refresh_anilist)
            + len(resolve_ids)
        )
        
        if total_missing > 0:
            if fetch_data:
                save_new_theme = messagebox.askyesno("Save Missing Entries To New Themes", "Would you like to save all missing entries to the 'New Themes' state.metadata.playlist? Entries in the 'New Themes' will not appear in infinite playlists until removed from the 'New Themes' state.metadata.playlist. (Select 'NO' if unsure)")
            
            BATCH_SAVE_INTERVAL = 100

            def note_metadata_changes(change_count=1):
                nonlocal files_since_last_save
                if not change_count:
                    return
                files_since_last_save += change_count
                if files_since_last_save >= BATCH_SAVE_INTERVAL:
                    metadata_io.save_metadata()
                    build_filename_to_mal_map()
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
                    result = fetch_metadata(
                        filename,
                        label=progress_label(),
                        batch_mode=True,
                    )
                    if result and save_new_theme:
                        playlist_marks.toggle_theme("New Themes", filename=filename, quiet=True)
                    if result:
                        total_fetched += 1
                        note_metadata_changes()
                    else:
                        total_skipped += 1
                except Exception as e:
                    print(e)
                    time.sleep(3)  # Delay to avoid API rate limits
                    total_skipped += 1

            # Resolve absent AniList/AniDB IDs before fetching those stores.
            # AniSongDB entries normally already have both IDs; this also
            # repairs older/manual registrations that only have a MAL ID.
            queued_anilist = set(refresh_anilist)
            queued_anidb = {str(item[0]) for item in refresh_anidb}
            for mal_id, file_entry in resolve_ids:
                try:
                    invalid_id_changes = 0
                    for key in ("anilist", "anidb"):
                        value = file_entry.get(key)
                        if value not in (None, "") and not _valid_provider_id(value):
                            file_entry.pop(key, None)
                            invalid_id_changes += 1
                    missing_before = tuple(
                        key
                        for key in ("anilist", "anidb")
                        if not _valid_provider_id(file_entry.get(key))
                    )
                    deferred_before = {
                        key: _metadata_failure_deferred(
                            file_entry, f"linked_{key}", mal_id
                        )
                        for key in missing_before
                    }
                    print(
                        f"{progress_label()} Resolving linked IDs "
                        f"for MAL {mal_id}...",
                        end=" ",
                        flush=True,
                    )
                    linked_ids = fetch_arm_ids(mal_id)
                    resolved_id_changes = 0
                    for key in ("anilist", "anidb", "kitsu"):
                        value = linked_ids.get(key)
                        if value and (
                            (key == "kitsu" and not file_entry.get(key))
                            or (
                                key in ("anilist", "anidb")
                                and not _valid_provider_id(file_entry.get(key))
                            )
                        ):
                            file_entry[key] = str(value)
                            resolved_id_changes += 1
                    attempted_anilist_fallback = False
                    if (
                        not _valid_provider_id(file_entry.get("anilist"))
                        and not deferred_before.get("anilist", False)
                    ):
                        attempted_anilist_fallback = True
                        resolved_anilist_id, anilist_data = fetch_anilist_metadata(
                            mal_id=mal_id
                        )
                        if resolved_anilist_id and anilist_data:
                            file_entry["anilist"] = str(resolved_anilist_id)
                            resolved_id_changes += 1
                            state.metadata.anilist_metadata[
                                str(resolved_anilist_id)
                            ] = anilist_data
                            if (
                                anilist_data.get("anidb_id")
                                and not _valid_provider_id(file_entry.get("anidb"))
                            ):
                                file_entry["anidb"] = str(anilist_data["anidb_id"])
                                resolved_id_changes += 1

                    status_changes = 0
                    for key in missing_before:
                        if _valid_provider_id(file_entry.get(key)):
                            status_changes += _clear_metadata_absence(
                                file_entry, f"linked_{key}"
                            )
                        elif deferred_before.get(key, False):
                            continue
                        elif key == "anidb" and last_arm_lookup_succeeded:
                            status_changes += _record_metadata_absence(
                                file_entry, "linked_anidb", mal_id
                            )
                        elif (
                            key == "anilist"
                            and attempted_anilist_fallback
                            and last_anilist_status == "not_found"
                        ):
                            status_changes += _record_metadata_absence(
                                file_entry, "linked_anilist", mal_id
                            )
                    note_metadata_changes(
                        status_changes + resolved_id_changes + invalid_id_changes
                    )
                    anilist_id = (
                        str(file_entry.get("anilist"))
                        if _valid_provider_id(file_entry.get("anilist"))
                        else None
                    )
                    anidb_id = (
                        str(file_entry.get("anidb"))
                        if _valid_provider_id(file_entry.get("anidb"))
                        else None
                    )
                    if (
                        anilist_id
                        and _anilist_metadata_missing(anilist_id)
                        and str(anilist_id) not in queued_anilist
                    ):
                        queued_anilist.add(str(anilist_id))
                        refresh_anilist.append(str(anilist_id))
                        total_missing += 1
                    if (
                        anidb_id
                        and _anidb_metadata_missing(anidb_id)
                        and str(anidb_id) not in queued_anidb
                    ):
                        queued_anidb.add(str(anidb_id))
                        refresh_anidb.append((str(anidb_id), mal_id))
                        total_missing += 1
                    status, fully_resolved = _linked_id_resolution_status(
                        missing_before, file_entry
                    )
                    print(status)
                    if fully_resolved:
                        total_fetched += 1
                    else:
                        total_skipped += 1
                    time.sleep(0.25)
                except Exception as e:
                    print(f"✗ Error: {e}")
                    total_skipped += 1

            for file_refresh in refresh_tenrai:
                try:
                    mal_id, anime_data = file_refresh
                    if not isinstance(anime_data, dict):
                        anime_data = {
                            "mal": mal_id,
                            "title": (
                                state.metadata.file_metadata.get(mal_id, {}).get("name")
                                or f"MAL ID: {mal_id}"
                            ),
                            "songs": [],
                        }
                        state.metadata.anime_metadata[mal_id] = anime_data
                    refresh_tenrai_data(
                        mal_id,
                        anime_data,
                        label=progress_label(),
                    )
                    if _mal_metadata_missing(anime_data):
                        if last_tenrai_status == "not_found":
                            note_metadata_changes(
                                _record_absence_for_provider_id(
                                    "mal", mal_id, "tenrai"
                                )
                            )
                        total_skipped += 1
                    else:
                        note_metadata_changes(
                            _clear_absence_for_provider_id(
                                "mal", mal_id, "tenrai"
                            )
                        )
                        total_fetched += 1
                except Exception as e:
                    print(e)
                    time.sleep(3)  # Delay to avoid API rate limits
                    total_skipped += 1
            for anilist_id in refresh_anilist:
                try:
                    if _anilist_metadata_missing(anilist_id):
                        print(f"{progress_label()} Fetching AniList metadata for ID {anilist_id}...", end=" ", flush=True)
                        _, anilist_data = fetch_anilist_metadata(anilist_id=anilist_id)
                        if anilist_data:
                            state.metadata.anilist_metadata[anilist_id] = anilist_data
                            note_metadata_changes(
                                _clear_absence_for_provider_id(
                                    "anilist", anilist_id, "anilist_metadata"
                                )
                            )
                            mal_id = str(anilist_data.get("mal_id") or "")
                            file_entry = state.metadata.file_metadata.get(mal_id)
                            linked_anidb_id = anilist_data.get("anidb_id")
                            if (
                                isinstance(file_entry, dict)
                                and linked_anidb_id
                                and not file_entry.get("anidb")
                            ):
                                linked_anidb_id = str(linked_anidb_id)
                                file_entry["anidb"] = linked_anidb_id
                                if (
                                    _anidb_metadata_missing(linked_anidb_id)
                                    and linked_anidb_id not in queued_anidb
                                ):
                                    queued_anidb.add(linked_anidb_id)
                                    refresh_anidb.append((linked_anidb_id, mal_id))
                                    total_missing += 1
                            print(f"✓ ({anilist_data.get('title', 'Unknown')})")
            
                            # Save all metadata after fetching
                            metadata_io.save_metadata()
                            total_fetched += 1
                        else:
                            if last_anilist_status == "not_found":
                                note_metadata_changes(
                                    _record_absence_for_provider_id(
                                        "anilist",
                                        anilist_id,
                                        "anilist_metadata",
                                    )
                                )
                            print("✗ Failed")
                            total_skipped += 1
                        time.sleep(1.0)
                    else:
                        # A preceding ID-resolution lookup may have populated
                        # this store after the initial work list was built.
                        note_metadata_changes(
                            _clear_absence_for_provider_id(
                                "anilist", anilist_id, "anilist_metadata"
                            )
                        )
                        total_fetched += 1
                except Exception as e:
                    print(f"✗ Error: {e}")
                    time.sleep(1.0)
                    total_skipped += 1

            # AniDB is deliberately last: its mandatory pacing makes it much
            # slower than MAL/AniList, so the faster stores finish even if the
            # user stops and resumes the job before AniDB completes.
            for anidb_index, file_anidb_refresh in enumerate(refresh_anidb):
                try:
                    if anidb_cooldown:
                        remaining = len(refresh_anidb) - anidb_index
                        print(
                            f"AniDB cooldown reached; leaving {remaining:,} "
                            "AniDB metadata requests queued for the next run."
                        )
                        break
                    if total_fetched > 0 and delay+anidb_delay > 0:
                        time.sleep(delay+anidb_delay)  # Delay to avoid API rate limits
                        anidb_delay = 0
                    anidb_id, mal_id = file_anidb_refresh
                    if _anidb_metadata_missing(anidb_id):
                        anime_data = state.metadata.anime_metadata.get(mal_id) or {
                            "mal": mal_id,
                            "title": f"MAL ID: {mal_id}",
                        }
                        refresh_anidb_data(
                            anidb_id,
                            anime_data,
                            label=progress_label(),
                        )
                    if _anidb_metadata_missing(anidb_id):
                        total_skipped += 1
                    else:
                        total_fetched += 1
                except Exception as e:
                    print(e)
                    time.sleep(3)  # Delay to avoid API rate limits
                    total_skipped += 1

        # After all fetching is done, save any remaining unsaved changes
        if files_since_last_save > 0:
            metadata_io.save_metadata(immediate=True)
            build_filename_to_mal_map()
        elif total_fetched > 0:
            metadata_io.save_metadata(immediate=True)
            if not filename_to_mal:
                build_filename_to_mal_map()

        print(
            "Metadata fetching complete! - Checked:"
            + str(total_checked)
            + " Processed:"
            + str(total_fetched + total_skipped)
            + " Completed:"
            + str(total_fetched)
            + " Skipped/Unavailable:"
            + str(total_skipped)
        )
        if save_new_theme and total_fetched > 0:
            print(f"{total_fetched} files saved to state.metadata.playlist '{"New Themes"}'.")

    # Run in a separate thread so it doesn’t freeze the UI
    threading.Thread(target=fetch_all_metadata_worker, daemon=True).start()


def refresh_anisongdb_catalog():
    """Download AniSongDB's catalog and refresh gap/alternative videos."""
    confirm = messagebox.askyesno(
        "Refresh AniSongDB Catalog",
        "Download AniSongDB's complete catalog for file detection and full "
        "song metadata?\n\n"
        "Uncovered themes will be registered for playlists and streaming. For "
        "themes already covered by AnimeThemes or a local file, the AniSongDB "
        "video will be available as an alternate in the theme/version list. "
        "The full source catalog will be retained locally in its own compressed "
        "metadata file.",
    )
    if not confirm:
        return

    def worker():
        try:
            print("Refreshing AniSongDB catalog...", flush=True)
            catalog = anisongdb.fetch_catalog()
            anisongdb.replace_catalog(catalog)
            registered = anisongdb.sync_catalog_to_metadata()
            preferred_gaps = len(anisongdb.gap_filenames())
            alternates = anisongdb.registered_alternate_count()
            metadata_io.save_anisongdb_metadata()
            metadata_io.save_metadata(immediate=True)
            directory_scan.scan_directory()
            print(
                "AniSongDB catalog refresh complete! - "
                f"Songs: {len(catalog.get('songs', []))} "
                f"Gap themes: {preferred_gaps} Video sources: {registered} "
                f"Covered alternatives: {alternates}"
            )
            messagebox.showinfo(
                "AniSongDB Refresh Complete",
                f"Loaded {len(catalog.get('songs', [])):,} songs. Registered "
                f"{preferred_gaps:,} uncovered themes with {registered:,} "
                f"playable video sources and {alternates:,} selectable "
                "alternatives for covered themes.",
            )
        except Exception as exc:
            print(f"AniSongDB catalog refresh failed: {exc}")
            messagebox.showerror("AniSongDB Refresh Failed", str(exc))

    threading.Thread(target=worker, daemon=True).start()


def refresh_animethemes_catalog():
    """Download AnimeThemes' paginated catalog and register every video."""
    confirm = messagebox.askyesno(
        "Refresh AnimeThemes Catalog",
        "Download the complete playable AnimeThemes catalog?\n\n"
        "This works without an imported metadata package or local theme files. "
        "Anime titles, songs, artists, theme versions, and remote videos will "
        "be registered for searching, streaming, and downloading.\n\n"
        "The catalog currently requires about 50 API requests. Existing local, "
        "manual, enriched, and AniSongDB metadata will be preserved.",
    )
    if not confirm:
        return

    def worker():
        try:
            print("Refreshing AnimeThemes catalog...", flush=True)

            def report_progress(page, anime_count):
                print(
                    f"AnimeThemes catalog page {page}: "
                    f"{anime_count:,} anime received...",
                    flush=True,
                )

            catalog = animethemes_catalog.fetch_catalog(
                progress_callback=report_progress,
            )
            # Do not replace usable local state until every page has arrived
            # and passed validation.
            animethemes_catalog.replace_catalog(catalog)
            registered = animethemes_catalog.sync_catalog_to_metadata()

            gap_count = 0
            alternate_count = 0
            if anisongdb.has_catalog():
                # AnimeThemes is the primary source. Recompute AniSongDB gaps
                # and alternatives against the newly refreshed coverage.
                anisongdb.sync_catalog_to_metadata()
                gap_count = len(anisongdb.gap_filenames())
                alternate_count = anisongdb.registered_alternate_count()

            metadata_io.save_animethemes_metadata()
            metadata_io.save_metadata(immediate=True)
            directory_scan.scan_directory()
            anime_count = len(catalog.get("anime", []))
            print(
                "AnimeThemes catalog refresh complete! - "
                f"Anime: {anime_count} Video registrations: {registered} "
                f"AniSongDB gaps: {gap_count} "
                f"AniSongDB alternatives: {alternate_count}"
            )
            messagebox.showinfo(
                "AnimeThemes Refresh Complete",
                f"Loaded {anime_count:,} anime and registered {registered:,} "
                "playable video sources.\n\n"
                "The catalog is now available to search and to playlists that "
                "include streaming themes.",
            )
        except Exception as exc:
            print(f"AnimeThemes catalog refresh failed: {exc}")
            messagebox.showerror("AnimeThemes Refresh Failed", str(exc))

    threading.Thread(target=worker, daemon=True).start()


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
    """Refreshes all tenrai metadata for files in the directory, spacing out API calls."""
    confirm = messagebox.askyesno("Refresh All Tenrai Metadata", "Are you sure you want to refresh all tenrai metadata for files in your directory?")
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
                refresh_tenrai_data(mal_id, data, label=f"[{total_refreshed + 1}/{total_to_refresh}]")
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
