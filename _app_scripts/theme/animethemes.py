"""AnimeThemes full-catalog provider and metadata projection.

AnimeThemes does not publish a public one-request catalog dump.  Its anime
index can, however, return the complete playable catalog in pages with all of
the relationships needed by the app.  This module downloads those pages,
retains the raw records, and projects them into the same ``file_metadata`` and
``anime_metadata`` stores used by local files.

The projection is deliberately self-contained: it must work when the user has
no downloaded metadata package and no local theme directory.
"""

from __future__ import annotations

import time
from typing import Callable

import requests

from core.app_meta import APP_VERSION
from core.game_state import state


CATALOG_URL = "https://api.animethemes.moe/anime"
PAGE_SIZE = 100
PROJECTION_VERSION = 2
CATALOG_MARKER = "animethemes_catalog"
CATALOG_OWNED_MARKER = "animethemes_catalog_owned"

INCLUDE_PATHS = (
    "series,resources,images,studios,"
    "animethemes.animethemeentries.videos,animethemes.song.artists"
)

_indexes: dict[str, dict] = {}
_index_signature = None


def _catalog() -> dict:
    return state.metadata.animethemes_metadata


def has_catalog() -> bool:
    return isinstance(_catalog().get("anime"), list) and bool(_catalog()["anime"])


def _raise_for_status(response) -> None:
    response.raise_for_status()


def _retry_after_seconds(response) -> float:
    try:
        return max(0.0, float(response.headers.get("Retry-After", 1)))
    except (AttributeError, TypeError, ValueError):
        return 1.0


def fetch_catalog(
    *,
    timeout=90,
    request_session=requests,
    progress_callback: Callable[[int, int], None] | None = None,
    sleep_func=time.sleep,
) -> dict:
    """Download and validate every playable AnimeThemes anime page.

    The public API permits 100 results per page and returns a ``links.next``
    URL rather than a reliable total.  Pages are sorted by stable primary key,
    fetched sequentially, and accumulated entirely before the caller replaces
    the active catalog.
    """
    anime_rows = []
    page = 1
    while True:
        params = {
            "filter[has]": "animethemes.animethemeentries.videos",
            "include": INCLUDE_PATHS,
            "sort": "id",
            "page[number]": page,
            "page[size]": PAGE_SIZE,
        }
        response = None
        for attempt in range(4):
            response = request_session.get(
                CATALOG_URL,
                params=params,
                headers={
                    "User-Agent": (
                        f"GuessTheAnime/{APP_VERSION} "
                        "(https://github.com/ualkotob/guess-the-anime-playlist-tool)"
                    )
                },
                timeout=timeout,
            )
            if getattr(response, "status_code", None) != 429:
                break
            if attempt == 3:
                _raise_for_status(response)
            sleep_func(_retry_after_seconds(response))

        _raise_for_status(response)
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("anime"), list):
            raise ValueError("AnimeThemes returned an unexpected catalog response.")
        page_rows = payload["anime"]
        if any(not isinstance(anime, dict) for anime in page_rows):
            raise ValueError("AnimeThemes returned a malformed anime catalog page.")
        anime_rows.extend(page_rows)
        if progress_callback:
            progress_callback(page, len(anime_rows))

        links = payload.get("links")
        next_url = links.get("next") if isinstance(links, dict) else None
        if not next_url or not page_rows:
            break
        page += 1

    if not anime_rows:
        raise ValueError("AnimeThemes returned an empty playable catalog.")
    return {
        "anime": anime_rows,
        "fetched_at": int(time.time()),
        "projection_version": 0,
    }


def replace_catalog(catalog: dict) -> None:
    """Replace the raw in-memory catalog while preserving dict identity."""
    global _index_signature
    if not isinstance(catalog, dict) or not isinstance(catalog.get("anime"), list):
        raise ValueError("AnimeThemes catalog is missing its anime list.")
    target = _catalog()
    target.clear()
    target.update(catalog)
    _index_signature = None
    build_indexes(force=True)


def _resource_id(anime: dict, site: str) -> str | None:
    for resource in anime.get("resources") or []:
        if not isinstance(resource, dict) or resource.get("site") != site:
            continue
        external_id = resource.get("external_id")
        if external_id not in (None, ""):
            return str(external_id)
    return None


def _anime_key(anime: dict) -> str | None:
    mal_id = _resource_id(anime, "MyAnimeList")
    if mal_id:
        return mal_id
    anime_id = anime.get("id")
    return f"ANIMETHEMES:{anime_id}" if anime_id not in (None, "") else None


def _catalog_signature():
    rows = _catalog().get("anime")
    return id(rows), len(rows) if isinstance(rows, list) else 0


def build_indexes(*, force=False) -> None:
    """Build raw-catalog lookups by video basename, prefix, and linked IDs."""
    global _indexes, _index_signature
    signature = _catalog_signature()
    if not force and _index_signature == signature:
        return
    by_basename = {}
    by_prefix = {}
    by_mal = {}
    for anime in _catalog().get("anime", []):
        if not isinstance(anime, dict):
            continue
        mal_id = _resource_id(anime, "MyAnimeList")
        if mal_id:
            by_mal.setdefault(mal_id, anime)
        for theme in anime.get("animethemes") or []:
            if not isinstance(theme, dict):
                continue
            for entry in theme.get("animethemeentries") or []:
                if not isinstance(entry, dict):
                    continue
                for video in entry.get("videos") or []:
                    if not isinstance(video, dict):
                        continue
                    basename = str(video.get("basename") or "")
                    if not basename:
                        continue
                    lowered = basename.casefold()
                    by_basename.setdefault(lowered, anime)
                    by_prefix.setdefault(lowered.split("-", 1)[0], anime)
    _indexes = {
        "basename": by_basename,
        "prefix": by_prefix,
        "mal": by_mal,
    }
    _index_signature = signature


def find_anime(*, filename=None, mal_id=None, split=True) -> dict | None:
    """Resolve an AnimeThemes anime from the retained raw catalog."""
    if not has_catalog():
        return None
    build_indexes()
    if mal_id not in (None, ""):
        return _indexes["mal"].get(str(mal_id))
    if not filename:
        return None
    lowered = str(filename).casefold()
    exact = _indexes["basename"].get(lowered)
    if exact:
        return exact
    if split:
        return _indexes["prefix"].get(lowered.split("-", 1)[0])
    return None


def _names(anime: dict, relation: str) -> list[str]:
    return [
        str(item["name"])
        for item in anime.get(relation) or []
        if isinstance(item, dict) and item.get("name")
    ]


def _cover(anime: dict) -> str | None:
    images = [item for item in anime.get("images") or [] if isinstance(item, dict)]
    for preferred_facet in ("Large Cover", "Small Cover"):
        for image in images:
            if image.get("facet") == preferred_facet and image.get("link"):
                return image["link"]
    return next((image.get("link") for image in images if image.get("link")), None)


def _entry_overlap(entry: dict):
    overlaps = [
        video.get("overlap")
        for video in entry.get("videos") or []
        if isinstance(video, dict)
    ]
    if "None" in overlaps:
        return "None"
    return next((value for value in overlaps if value not in (None, "")), None)


def _theme_song(theme: dict) -> dict | None:
    slug = theme.get("slug")
    if not slug:
        return None
    song = theme.get("song") if isinstance(theme.get("song"), dict) else {}
    entries = [
        entry
        for entry in theme.get("animethemeentries") or []
        if isinstance(entry, dict)
    ]
    versions = []
    for entry in entries:
        version_data = {
            "version": entry.get("version"),
            "episodes": entry.get("episodes", "N/A"),
            "spoiler": bool(entry.get("spoiler")),
            "nsfw": bool(entry.get("nsfw")),
        }
        overlap = _entry_overlap(entry)
        if overlap is not None:
            version_data["overlap"] = overlap
        versions.append(version_data)

    result = {
        "type": theme.get("type") or str(slug)[:2],
        "slug": slug,
        "title": song.get("title"),
        "artist": [
            artist["name"]
            for artist in song.get("artists") or []
            if isinstance(artist, dict) and artist.get("name")
        ],
        "episodes": entries[0].get("episodes") if entries else None,
        "nsfw": any(bool(entry.get("nsfw")) for entry in entries),
        "versions": versions,
        CATALOG_MARKER: True,
    }
    if entries and all(bool(entry.get("spoiler")) for entry in entries):
        result["spoiler"] = True
    overlaps = [version.get("overlap") for version in versions]
    meaningful_overlaps = [value for value in overlaps if value not in (None, "None")]
    if versions and meaningful_overlaps and "None" not in overlaps:
        result["overlap"] = meaningful_overlaps[0]
    return result


def _minimal_anime_metadata(anime: dict) -> dict:
    season = anime.get("season") or "N/A"
    year = anime.get("year") or "N/A"
    return {
        "title": anime.get("name") or "N/A",
        "eng_title": None,
        "synonyms": [],
        "series": _names(anime, "series"),
        # AnimeThemes provides a season and year, not an exact air-date range.
        # Keep this absent so consumers correctly fall back to ``season``.
        "aired": None,
        "season": f"{season} {year}".strip().capitalize(),
        "score": None,
        "rank": None,
        "members": None,
        "popularity": None,
        "type": anime.get("media_format") or "N/A",
        "source": "N/A",
        "episodes": "N/A",
        "studios": _names(anime, "studios"),
        "genres": [],
        "themes": [],
        "demographics": [],
        "synopsis": anime.get("synopsis") or "N/A",
        "cover": _cover(anime),
        "trailer": None,
        "songs": [
            song
            for song in (_theme_song(theme) for theme in anime.get("animethemes") or [])
            if song
        ],
        CATALOG_MARKER: True,
    }


def _merge_anime_metadata(key: str, anime: dict) -> None:
    incoming = _minimal_anime_metadata(anime)
    existing = state.metadata.anime_metadata.get(key)
    if not isinstance(existing, dict):
        incoming[CATALOG_OWNED_MARKER] = True
        state.metadata.anime_metadata[key] = incoming
        return

    # AnimeThemes owns its theme-song records.  Existing rich anime metadata
    # remains authoritative for fields such as ratings, genres and characters.
    old_songs = {
        str(song.get("slug")): song
        for song in existing.get("songs") or []
        if isinstance(song, dict) and song.get("slug")
    }
    merged_songs = []
    incoming_slugs = set()
    for song in incoming["songs"]:
        slug = str(song.get("slug"))
        incoming_slugs.add(slug)
        previous = old_songs.get(slug) or {}
        merged = dict(previous)
        merged.update(song)
        # A provider refresh must not erase a curated value merely because
        # the upstream relationship is blank. Metadata packages commonly use
        # this path to supply artists that AnimeThemes does not yet credit.
        for field in ("title", "artist"):
            if song.get(field) in (None, "", []) and previous.get(field) not in (
                None,
                "",
                [],
            ):
                merged[field] = previous[field]
        if slug not in old_songs:
            merged[CATALOG_OWNED_MARKER] = True
        merged_songs.append(merged)
    merged_songs.extend(
        song for slug, song in old_songs.items() if slug not in incoming_slugs
    )

    for field in (
        "title",
        "series",
        "aired",
        "season",
        "type",
        "studios",
        "synopsis",
        "cover",
    ):
        if existing.get(field) in (None, "", "N/A", [], {}):
            existing[field] = incoming[field]
    existing["songs"] = merged_songs
    existing[CATALOG_MARKER] = True


def _video_properties(video: dict) -> dict:
    return {
        "lyrics": bool(video.get("lyrics")),
        "nc": bool(video.get("nc")),
        "resolution": video.get("resolution"),
        "source": video.get("source"),
        "subbed": bool(video.get("subbed")),
        "uncen": bool(video.get("uncen")),
        "tags": video.get("tags"),
        "overlap": video.get("overlap"),
        "animethemes_video_id": video.get("id"),
        "animethemes_path": video.get("path"),
        "size": video.get("size"),
        CATALOG_MARKER: True,
    }


def clear_registered_metadata() -> None:
    """Remove the previous catalog projection without touching other sources."""
    for key, file_entry in list(state.metadata.file_metadata.items()):
        if not isinstance(file_entry, dict):
            continue
        themes = file_entry.get("themes")
        if not isinstance(themes, dict):
            continue
        for slug, versions in list(themes.items()):
            if not isinstance(versions, dict):
                continue
            for version, files in list(versions.items()):
                if not isinstance(files, dict):
                    continue
                for filename, properties in list(files.items()):
                    if not isinstance(properties, dict) or not properties.get(CATALOG_MARKER):
                        continue
                    if filename in state.metadata.directory_files:
                        properties.pop(CATALOG_MARKER, None)
                        continue
                    del files[filename]
                if not files:
                    del versions[version]
            if not versions:
                del themes[slug]
        file_entry.pop("animethemes_projection_version", None)
        if not themes and file_entry.get(CATALOG_OWNED_MARKER):
            state.metadata.file_metadata.pop(key, None)

    for key, anime in list(state.metadata.anime_metadata.items()):
        if not isinstance(anime, dict):
            continue
        songs = anime.get("songs")
        if isinstance(songs, list):
            anime["songs"] = [
                song
                for song in songs
                if not (
                    isinstance(song, dict)
                    and song.get(CATALOG_MARKER)
                    and song.get(CATALOG_OWNED_MARKER)
                )
            ]
        if anime.get(CATALOG_OWNED_MARKER) and key not in state.metadata.file_metadata:
            state.metadata.anime_metadata.pop(key, None)


def _register_anime(anime: dict) -> int:
    key = _anime_key(anime)
    if not key:
        return 0
    existing = state.metadata.file_metadata.get(key)
    if not isinstance(existing, dict):
        existing = {
            "name": anime.get("name") or "N/A",
            "themes": {},
            CATALOG_OWNED_MARKER: True,
        }
        state.metadata.file_metadata[key] = existing
    existing.setdefault("themes", {})
    if anime.get("name"):
        existing["name"] = anime["name"]
    mal_id = _resource_id(anime, "MyAnimeList")
    if mal_id:
        existing["mal"] = mal_id
    for field, site in (("anidb", "aniDB"), ("anilist", "AniList"), ("kitsu", "Kitsu")):
        external_id = _resource_id(anime, site)
        if external_id:
            existing[field] = external_id
    if anime.get("id") is not None:
        existing["animethemes_id"] = anime["id"]
    if anime.get("slug"):
        existing["animethemes_slug"] = anime["slug"]
    existing["animethemes_projection_version"] = PROJECTION_VERSION

    registered = 0
    for theme in anime.get("animethemes") or []:
        if not isinstance(theme, dict) or not theme.get("slug"):
            continue
        slug = str(theme["slug"])
        slug_entry = existing["themes"].setdefault(slug, {})
        for entry in theme.get("animethemeentries") or []:
            if not isinstance(entry, dict):
                continue
            version = entry.get("version")
            version_key = str(version) if version is not None else "null"
            files = slug_entry.setdefault(version_key, {})
            for video in entry.get("videos") or []:
                if not isinstance(video, dict) or not video.get("basename"):
                    continue
                basename = str(video["basename"])
                properties = files.setdefault(basename, {})
                if not isinstance(properties, dict):
                    properties = {}
                    files[basename] = properties
                properties.update(_video_properties(video))
                registered += 1
    _merge_anime_metadata(key, anime)
    return registered


def _refresh_runtime_lookup() -> None:
    from _app_scripts.file.metadata import metadata_fetch
    from _app_scripts.playlists import playlist

    metadata_fetch.build_filename_to_mal_map()
    metadata_fetch.animethemes_cache.clear()
    metadata_fetch.invalidate_file_metadata_cache()
    metadata_fetch.invalidate_metadata_cache()
    playlist.invalidate_deduplicated_cache()


def sync_catalog_to_metadata() -> int:
    """Project the complete catalog into browsable, streamable app metadata."""
    if not has_catalog():
        return 0
    clear_registered_metadata()
    registered = 0
    for anime in _catalog().get("anime", []):
        if isinstance(anime, dict):
            registered += _register_anime(anime)
    _catalog()["projection_version"] = PROJECTION_VERSION
    build_indexes(force=True)
    _refresh_runtime_lookup()
    return registered


def registered_video_count() -> int:
    count = 0
    for entry in state.metadata.file_metadata.values():
        if not isinstance(entry, dict):
            continue
        for versions in entry.get("themes", {}).values():
            if not isinstance(versions, dict):
                continue
            for files in versions.values():
                if not isinstance(files, dict):
                    continue
                count += sum(
                    1
                    for properties in files.values()
                    if isinstance(properties, dict) and properties.get(CATALOG_MARKER)
                )
    return count


def registered_projection_version() -> int:
    versions = (
        entry.get("animethemes_projection_version", 0)
        for entry in state.metadata.file_metadata.values()
        if isinstance(entry, dict)
    )
    return max(versions, default=0)
