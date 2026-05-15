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

import os
import re
import sys
import xml.etree.ElementTree as ET

import requests

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


def extract_video_properties(anime_themes, filename):
    """Extract video properties (lyrics, nc, resolution, source) from AnimThemes API response."""
    properties = {}
    
    if not anime_themes or not anime_themes.get("animethemes"):
        return properties
    
    for theme in anime_themes.get("animethemes", []):
        for entry in theme.get("animethemeentries", []):
            for video in entry.get("videos", []):
                if video.get("basename") and filename.split(".")[0] == video.get("basename", "").split(".")[0]:
                    properties["lyrics"] = video.get("lyrics", False)
                    properties["nc"] = video.get("nc", False)
                    properties["resolution"] = video.get("resolution")
                    properties["source"] = video.get("source")
                    return properties
    
    return properties


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
