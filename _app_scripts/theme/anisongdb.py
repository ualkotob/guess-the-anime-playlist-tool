"""AniSongDB full-catalog provider.

The catalog is retained verbatim in ``state.metadata.anisongdb_metadata``.  The
normal app metadata stores receive only the fields needed for lookup, display,
and playback; callers can still retrieve the complete AniSongDB record through
``get_metadata`` without duplicating the catalog for every media variant.
"""

from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal

import requests

from core.app_meta import APP_VERSION
from core.game_state import state


CATALOG_URL = "https://anisongdb.com/api/catalog_dump"
DIST_BASE_URLS = {
    "na-east": "https://naedist.animemusicquiz.com/",
    "na-west": "https://nawdist.animemusicquiz.com/",
    "europe": "https://eudist.animemusicquiz.com/",
}
DEFAULT_DIST_REGION = "na-east"
PROJECTION_VERSION = 5

_TAGGED_AMQ_RE = re.compile(r"\[(?:ASDB|AMQ)\](\d+)", re.IGNORECASE)
_TAGGED_ANN_RE = re.compile(r"\[ANNSONG\](\d+)", re.IGNORECASE)
_LEGACY_RE = re.compile(r"^ASDB-\d+-(?:OP|ED)\d+-(\d+)", re.IGNORECASE)
_NATIVE_MEDIA_RE = re.compile(r"^(?:[a-z0-9]{6}|[a-z0-9]{16})\.webm$", re.IGNORECASE)
_MANUAL_FILE_RE = re.compile(r"\[(?:MAL|ID|IGDB)\]", re.IGNORECASE)
_ANIMETHEMES_FILE_RE = re.compile(r"-(?:OP|ED)\d+(?:\.\d+)?(?:v\d+)?(?:[-.\[]|$)", re.IGNORECASE)
_VIDEO_EXTENSIONS = (".webm", ".mp4", ".mkv")

SOURCE_ANISONGDB = "anisongdb"
SOURCE_ANIMETHEMES = "animethemes"
SOURCE_MANUAL = "manual"
SOURCE_UNKNOWN = "unknown"

_indexes = {}
_index_signature = None
_catalog_attempted = False
_artist_display_aliases = None
_mapped_slugs = {}


def _catalog() -> dict:
    return state.metadata.anisongdb_metadata


def has_catalog() -> bool:
    catalog = _catalog()
    return (
        isinstance(catalog.get("anime"), dict)
        and isinstance(catalog.get("artists"), dict)
        and isinstance(catalog.get("songs"), list)
    )


def fetch_catalog(*, timeout=90, request_session=requests) -> dict:
    """Download and validate AniSongDB's complete catalog dump."""
    response = request_session.get(
        CATALOG_URL,
        headers={
            "User-Agent": (
                f"GuessTheAnime/{APP_VERSION} "
                "(https://github.com/ualkotob/guess-the-anime-playlist-tool)"
            )
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("AniSongDB returned an unexpected catalog response.")
    if not isinstance(payload.get("anime"), dict):
        raise ValueError("AniSongDB's catalog is missing the anime table.")
    if not isinstance(payload.get("artists"), dict):
        raise ValueError("AniSongDB's catalog is missing the artist table.")
    if not isinstance(payload.get("songs"), list):
        raise ValueError("AniSongDB's catalog is missing the song table.")
    return payload


def replace_catalog(catalog: dict) -> None:
    """Replace the in-memory catalog while preserving its dict identity."""
    global _index_signature, _catalog_attempted
    target = _catalog()
    target.clear()
    target.update(catalog)
    _index_signature = None
    _catalog_attempted = True
    _invalidate_artist_display_aliases()
    build_indexes(force=True)


def ensure_catalog(*, download=False) -> bool:
    """Ensure catalog indexes exist, optionally downloading once per run."""
    global _catalog_attempted
    if has_catalog():
        build_indexes()
        return True
    if not download or _catalog_attempted:
        return False
    _catalog_attempted = True
    replace_catalog(fetch_catalog())
    # Native media names cannot be resolved without the raw catalog, so keep
    # an automatically fetched copy across restarts as well as manual refreshes.
    from _app_scripts.data import metadata_io

    sync_catalog_to_metadata()
    metadata_io.save_anisongdb_metadata()
    metadata_io.save_metadata()
    return True


def _valid_media_basename(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (
        not value
        or os.path.basename(value) != value
        or not value.lower().endswith(_VIDEO_EXTENSIONS)
    ):
        return None
    return value


def iter_videos(song: dict):
    """Yield each distinct playable video as (basename, resolution, field)."""
    seen = set()
    for field, resolution in (("HQ", 720), ("MQ", 480)):
        basename = _valid_media_basename(song.get(field))
        if basename and basename.lower() not in seen:
            seen.add(basename.lower())
            yield basename, resolution, field


def video_sources(song: dict, region: str = DEFAULT_DIST_REGION) -> list[dict]:
    """Return AniSongDB video variants with stable media IDs and derived URLs."""
    return [
        {
            "quality": quality,
            "resolution": resolution,
            "media": basename,
            "url": media_url(basename, region),
        }
        for basename, resolution, quality in iter_videos(song)
    ]


def media_url(basename: str, region: str = DEFAULT_DIST_REGION) -> str:
    basename = _valid_media_basename(basename)
    if not basename:
        raise ValueError("AniSongDB media must be a supported video basename.")
    try:
        return DIST_BASE_URLS[region] + basename
    except KeyError as exc:
        raise ValueError(f"Unknown AniSongDB distribution region: {region}") from exc


def build_indexes(*, force=False) -> dict:
    """Build native-media and ID indexes over the retained catalog."""
    global _indexes, _index_signature, _mapped_slugs
    catalog = _catalog()
    songs = catalog.get("songs") if isinstance(catalog, dict) else None
    signature = (id(catalog), id(songs), len(songs) if isinstance(songs, list) else -1)
    if not force and signature == _index_signature:
        return _indexes

    indexes = {"media": {}, "amq": {}, "ann_song": {}, "mal": {}}
    if isinstance(songs, list):
        for song in songs:
            if not isinstance(song, dict):
                continue
            for basename, _resolution, _field in iter_videos(song):
                indexes["media"][basename.lower()] = song
            for field, index_name in (
                ("amqSongId", "amq"),
                ("annSongId", "ann_song"),
            ):
                value = song.get(field)
                if value is not None:
                    indexes[index_name][str(value)] = song
            anime = catalog.get("anime", {}).get(str(song.get("annId")), {})
            linked = anime.get("linked_ids") if isinstance(anime, dict) else {}
            mal_id = linked.get("myanimelist") if isinstance(linked, dict) else None
            if mal_id is not None:
                indexes["mal"].setdefault(str(mal_id), []).append(song)

    _indexes = indexes
    _index_signature = signature
    # Restore the saved cross-provider numbering once when loading a catalog.
    # The original source slug distinguishes repeated uses of a shared song ID.
    _mapped_slugs = {}
    for anime in state.metadata.anime_metadata.values():
        if not isinstance(anime, dict):
            continue
        for song in anime.get("songs") or []:
            if not isinstance(song, dict) or not song.get("anisongdb_source_slug"):
                continue
            key = (
                str(song.get("anisongdb_ann_id")),
                str(song.get("anisongdb_ann_song_id")),
                str(song.get("anisongdb_amq_song_id")),
                song["anisongdb_source_slug"],
            )
            _mapped_slugs[key] = song.get("slug")
    return indexes


def looks_like_tagged_filename(filename: str) -> bool:
    name = os.path.basename(filename or "")
    return bool(_TAGGED_AMQ_RE.search(name) or _TAGGED_ANN_RE.search(name) or _LEGACY_RE.search(name))


def classify_filename(filename: str) -> str:
    """Classify a filename by structure without making a network request."""
    name = os.path.basename(filename or "")
    if _MANUAL_FILE_RE.search(name):
        return SOURCE_MANUAL
    if (
        looks_like_tagged_filename(name)
        or _NATIVE_MEDIA_RE.fullmatch(name)
    ):
        return SOURCE_ANISONGDB
    if _ANIMETHEMES_FILE_RE.search(name):
        return SOURCE_ANIMETHEMES
    return SOURCE_UNKNOWN


def looks_like_native_filename(filename: str) -> bool:
    """Return whether a name follows a recognized AniSongDB file format."""
    return classify_filename(filename) == SOURCE_ANISONGDB


def find_song(filename: str, *, download_catalog=False) -> dict | None:
    """Find a song by its native media basename or an embedded ID."""
    if not ensure_catalog(download=download_catalog):
        return None
    indexes = build_indexes()
    name = os.path.basename(filename or "")
    native = indexes["media"].get(name.lower())
    if native:
        return native
    match = _TAGGED_AMQ_RE.search(name) or _LEGACY_RE.search(name)
    if match:
        return indexes["amq"].get(match.group(1))
    match = _TAGGED_ANN_RE.search(name)
    if match:
        return indexes["ann_song"].get(match.group(1))
    return None


def _song_type(song: dict) -> tuple[str | None, int]:
    value = song.get("songType")
    number = song.get("songNumber") or 1
    if value in (1, "1"):
        return "OP", int(number)
    if value in (2, "2"):
        return "ED", int(number)
    if value in (3, "3"):
        return "IN", int(number)
    text = str(value or "")
    match = re.match(r"^(Opening|Ending|Insert)(?:\s+(\d+))?", text, re.IGNORECASE)
    if not match:
        return None, int(number)
    kind = {"opening": "OP", "ending": "ED", "insert": "IN"}[match.group(1).lower()]
    return kind, int(match.group(2) or number)


def _source_theme_slug(song: dict) -> str | None:
    kind, number = _song_type(song)
    if kind in ("OP", "ED"):
        return f"{kind}{number}"
    if kind == "IN":
        unique_id = song.get("annSongId") or song.get("amqSongId")
        return f"IN{unique_id}" if unique_id is not None else None
    return None


def _song_key(song: dict) -> tuple:
    return (
        str(song.get("annId")),
        str(song.get("annSongId")),
        str(song.get("amqSongId")),
        _source_theme_slug(song),
    )


def theme_slug(song: dict) -> str | None:
    """Return the saved app slot, retaining the upstream slot independently."""
    return _mapped_slugs.get(_song_key(song)) or _source_theme_slug(song)


def _artist_record(artist_id, line_up_id=-1) -> dict:
    raw = _catalog().get("artists", {}).get(str(artist_id), {})
    if not isinstance(raw, dict):
        raw = {}
    result = deepcopy(raw)
    result["id"] = artist_id
    result["line_up_id"] = line_up_id
    return result


def _expand_credits(values) -> list[dict]:
    result = []
    for value in values or []:
        if isinstance(value, (list, tuple)) and value:
            result.append(_artist_record(value[0], value[1] if len(value) > 1 else -1))
        elif isinstance(value, dict):
            result.append(deepcopy(value))
    return result


def normalize_song(song: dict) -> dict:
    """Return the complete song enriched with its anime and artist rows."""
    result = deepcopy(song)
    anime = _catalog().get("anime", {}).get(str(song.get("annId")), {})
    result["anime"] = deepcopy(anime) if isinstance(anime, dict) else {}
    result["artists"] = _expand_credits(song.get("artists"))
    result["composers"] = _expand_credits(song.get("composers"))
    result["arrangers"] = _expand_credits(song.get("arrangers"))
    result["video_sources"] = video_sources(song)
    return result


def _linked_ids(song: dict) -> dict:
    anime = _catalog().get("anime", {}).get(str(song.get("annId")), {})
    linked = anime.get("linked_ids") if isinstance(anime, dict) else {}
    return linked if isinstance(linked, dict) else {}


def _mal_id(song: dict) -> str | None:
    value = _linked_ids(song).get("myanimelist")
    return str(value) if value not in (None, "") else None


def linked_ids(song: dict) -> dict:
    """Return a copy of the anime-site IDs linked to a catalog song."""
    return deepcopy(_linked_ids(song))


def file_identity(song: dict) -> dict:
    """Return AniSongDB identity fields safe to attach to any local file."""
    return {
        "anisongdb_ann_id": song.get("annId"),
        "anisongdb_ann_song_id": song.get("annSongId"),
        "anisongdb_amq_song_id": song.get("amqSongId"),
        "anisongdb_source_slug": _source_theme_slug(song),
    }


def _match_key(value) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def _invalidate_artist_display_aliases() -> None:
    global _artist_display_aliases
    _artist_display_aliases = None


def _preferred_artist_spellings() -> dict[str, Counter]:
    """Index established non-AniSongDB artist spellings by normalized name."""
    preferred = defaultdict(Counter)
    for anime in state.metadata.anime_metadata.values():
        if not isinstance(anime, dict):
            continue
        for song in anime.get("songs") or []:
            if not isinstance(song, dict) or song.get("anisongdb_only"):
                continue
            artist_values = song.get("artist") or []
            if isinstance(artist_values, str):
                artist_values = [artist_values]
            for artist in artist_values:
                if not isinstance(artist, str) or not artist.strip():
                    continue
                name = artist.strip()
                key = _match_key(name)
                if key:
                    preferred[key][name] += 1
    return preferred


def _preferred_spelling(candidates: Counter) -> str | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda name: (-candidates[name], name.casefold(), name),
    )


def _reversed_person_name_key(name: str) -> str | None:
    """Return a two-part name in reverse order, or None for complex credits."""
    words = re.findall(r"[^\W_]+", str(name or ""), flags=re.UNICODE)
    if len(words) != 2:
        return None
    return _match_key(" ".join(reversed(words)))


def _build_artist_display_aliases() -> dict[str, str]:
    """Map AniSongDB aliases to the spelling already used by AnimeThemes.

    AniSongDB commonly stores Japanese personal names family-name first while
    AnimeThemes stores the same artist given-name first. Exact normalized
    aliases are preferred; a two-part reversal is accepted only when it points
    to one established normalized name. The retained catalog remains raw.
    """
    preferred = _preferred_artist_spellings()
    aliases = {}
    for record in _catalog().get("artists", {}).values():
        if not isinstance(record, dict):
            continue
        for alias in record.get("names") or []:
            if not isinstance(alias, str) or not alias.strip():
                continue
            alias_key = _match_key(alias)
            if not alias_key:
                continue
            display = _preferred_spelling(preferred.get(alias_key))
            if display is None:
                reverse_key = _reversed_person_name_key(alias)
                if reverse_key:
                    display = _preferred_spelling(preferred.get(reverse_key))
            if display is not None:
                aliases[alias_key] = display
    return aliases


def canonical_artist_name(name: str) -> str:
    """Return the established display spelling for an AniSongDB artist name."""
    global _artist_display_aliases
    if _artist_display_aliases is None:
        _artist_display_aliases = _build_artist_display_aliases()
    return _artist_display_aliases.get(_match_key(name), name)


def songs_for_mal_slug(mal_id, slug: str) -> list[dict]:
    """Return catalog candidates for a MAL anime and saved app slot."""
    if not ensure_catalog():
        return []
    return [
        song for song in build_indexes()["mal"].get(str(mal_id), [])
        if str(theme_slug(song) or "").upper() == str(slug or "").upper()
    ]


def _song_artist_keys(song: dict) -> set[str]:
    values = [song.get("songArtist")]
    for artist in _expand_credits(song.get("artists")):
        values.extend(artist.get("names") or [])
    return {
        key for value in values
        for key in (_match_key(value), _match_key(canonical_artist_name(str(value or ""))))
        if key
    }


def _matches_theme(song: dict, title=None, artists=None) -> bool:
    """Known titles and performers must agree; recording qualifiers matter."""
    if _match_key(title) and _match_key(song.get("songName")) != _match_key(title):
        return False
    values = [artists] if isinstance(artists, str) else (artists or [])
    artist_keys = {
        key for value in values
        for key in (_match_key(value), _match_key(canonical_artist_name(str(value))))
        if key
    }
    source_keys = _song_artist_keys(song) if artist_keys else set()
    return not artist_keys or not source_keys or bool(artist_keys & source_keys)


def resolve_song_for_mal_slug(
    mal_id,
    slug: str,
    *,
    title=None,
    artists=None,
    download_catalog=False,
) -> dict | None:
    """Resolve song identity across source numbering without accepting conflicts."""
    if not ensure_catalog(download=download_catalog):
        return None
    match = re.fullmatch(r"(OP|ED|IN)(\d+(?:\.\d+)?)", str(slug or ""), re.IGNORECASE)
    if not match:
        return None
    kind = match.group(1).upper()
    slot_candidates = songs_for_mal_slug(mal_id, slug)
    # With a known title, the number cannot restrict the search. Without one,
    # the saved slot remains the only evidence for a manually named file.
    pool = build_indexes()["mal"].get(str(mal_id), []) if title and kind != "IN" else slot_candidates
    candidates = [
        song for song in pool
        if _song_type(song)[0] == kind
        and not song.get("isDub") and not song.get("isRebroadcast")
        and _matches_theme(song, title, artists)
    ]
    if not candidates:
        return None
    in_slot = [song for song in candidates if song in slot_candidates]
    if in_slot:
        candidates = in_slot
    if len(candidates) == 1:
        return candidates[0]

    # Duplicate ANN rows sometimes describe the same actual song. Choosing one
    # is safe when the answer-facing title and artist are identical.
    answers = {
        (_match_key(song.get("songName")), _match_key(song.get("songArtist")))
        for song in candidates
    }
    return candidates[0] if len(answers) == 1 else None


def _primary_names(
    records: list[dict],
    fallback: str | None,
    *,
    canonicalize=False,
) -> list[str]:
    names = []
    for record in records:
        aliases = record.get("names")
        if not isinstance(aliases, list) or not aliases:
            continue
        usable_aliases = [
            alias for alias in aliases if isinstance(alias, str) and alias.strip()
        ]
        if not usable_aliases:
            continue

        # Some catalog records represent more than one contextual credit. Use
        # songArtist/songComposer/songArranger to choose the applicable alias
        # instead of always projecting the record's first name.
        selected = usable_aliases[0]
        fallback_key = _match_key(fallback)
        contextual = [
            alias
            for alias in usable_aliases
            if _match_key(alias) and _match_key(alias) in fallback_key
        ]
        if contextual:
            selected = max(contextual, key=lambda alias: len(_match_key(alias)))
        if canonicalize:
            selected = canonical_artist_name(selected)
        if selected not in names:
            names.append(selected)
    if not names and fallback:
        name = str(fallback)
        names.append(canonical_artist_name(name) if canonicalize else name)
    return names


def song_metadata(song: dict) -> dict:
    full = normalize_song(song)
    kind, _number = _song_type(song)
    return {
        "type": kind,
        "slug": theme_slug(song),
        "title": song.get("songName") or "",
        "artist": _primary_names(
            full["artists"], song.get("songArtist"), canonicalize=True
        ),
        "composer": _primary_names(full["composers"], song.get("songComposer")),
        "arranger": _primary_names(full["arrangers"], song.get("songArranger")),
        "anisongdb_ann_id": song.get("annId"),
        "anisongdb_ann_song_id": song.get("annSongId"),
        "anisongdb_amq_song_id": song.get("amqSongId"),
        "anisongdb_category": song.get("songCategory"),
        "anisongdb_source_slug": _source_theme_slug(song),
        "anisongdb_difficulty": song.get("songDifficulty"),
        "anisongdb_length": song.get("songLength"),
        "anisongdb_is_dub": song.get("isDub"),
        "anisongdb_is_rebroadcast": song.get("isRebroadcast"),
    }


def _merge_anime_metadata(mal_id: str, song: dict) -> None:
    anime_raw = _catalog().get("anime", {}).get(str(song.get("annId")), {})
    if not isinstance(anime_raw, dict):
        anime_raw = {}
    anime = state.metadata.anime_metadata.setdefault(mal_id, {})
    defaults = {
        "title": anime_raw.get("animeJPName") or anime_raw.get("animeENName") or f"MAL {mal_id}",
        "eng_title": anime_raw.get("animeENName") or anime_raw.get("animeJPName") or f"MAL {mal_id}",
        "season": anime_raw.get("animeVintage"),
        "type": anime_raw.get("animeType"),
        "anisongdb_ann_id": song.get("annId"),
        "anisongdb_category": anime_raw.get("animeCategory"),
        "anisongdb_genres": deepcopy(anime_raw.get("genres") or []),
        "anisongdb_tags": deepcopy(anime_raw.get("tags") or []),
    }
    for key, value in defaults.items():
        if value not in (None, "", []):
            anime.setdefault(key, value)

    # AnimeThemes/MAL-backed rows normally provide this list. Provider-only
    # rows do not, but several established UI paths treat it as iterable.
    if anime.get("themes") is None:
        anime["themes"] = []

    incoming = song_metadata(song)
    if not isinstance(anime.get("songs"), list):
        anime["songs"] = []
    songs = anime["songs"]
    existing = next(
        (item for item in songs if item.get("slug") == incoming.get("slug")),
        None,
    )
    if existing is None:
        incoming["anisongdb_only"] = True
        songs.append(incoming)
    else:
        credits = existing.setdefault("anisongdb_credits", {})
        for key, value in incoming.items():
            if value not in (None, "", []) and (
                key.startswith("anisongdb_") or not existing.get(key)
            ):
                existing[key] = value
                if key in ("composer", "arranger"):
                    credits[key] = deepcopy(value)


def merge_song_metadata(mal_id, song: dict) -> None:
    """Enrich an existing anime/song row without registering remote media."""
    if song:
        _merge_anime_metadata(str(mal_id), song)


def _register_file(
    mal_id: str,
    song: dict,
    filename: str,
    video: tuple[str, int, str],
    *,
    is_gap=False,
    is_preferred=False,
    is_alternate=False,
) -> None:
    linked = _linked_ids(song)
    anime_raw = _catalog().get("anime", {}).get(str(song.get("annId")), {})
    entry = state.metadata.file_metadata.setdefault(mal_id, {})
    entry.setdefault("name", anime_raw.get("animeJPName") or anime_raw.get("animeENName") or f"MAL {mal_id}")
    entry.setdefault("mal", mal_id)
    for key, linked_key in (("anidb", "anidb"), ("anilist", "anilist"), ("kitsu", "kitsu")):
        value = linked.get(linked_key)
        if value not in (None, "") and not entry.get(key):
            entry[key] = str(value)
    entry.setdefault("anisongdb_ann_id", song.get("annId"))
    entry["anisongdb_projection_version"] = PROJECTION_VERSION

    basename, resolution, quality = video
    slug = theme_slug(song)
    properties = {
        "lyrics": False,
        "nc": False,
        "resolution": resolution,
        "source": "ANISONGDB",
        "stream_url": media_url(basename),
        "anisongdb_media": basename,
        "anisongdb_quality": quality,
        "anisongdb_ann_id": song.get("annId"),
        "anisongdb_ann_song_id": song.get("annSongId"),
        "anisongdb_amq_song_id": song.get("amqSongId"),
        "anisongdb_source_slug": _source_theme_slug(song),
    }
    fallback_urls = [
        media_url(other_basename)
        for other_basename, _other_resolution, _other_quality in iter_videos(song)
        if other_basename.lower() != basename.lower()
    ]
    if fallback_urls:
        properties["anisongdb_fallback_stream_urls"] = fallback_urls
    if is_gap:
        properties["anisongdb_gap"] = True
        properties["anisongdb_preferred"] = bool(is_preferred)
    if is_alternate:
        properties["anisongdb_alternate"] = True
    entry.setdefault("themes", {}).setdefault(slug, {}).setdefault("1", {})[filename] = properties


def register_song(
    song: dict,
    *,
    filename: str | None = None,
    is_gap=False,
    merge_metadata=True,
    preferred_only=False,
    is_alternate=False,
) -> list[str]:
    """Register one catalog song, using a local filename when supplied."""
    mal_id = _mal_id(song)
    slug = theme_slug(song)
    videos = list(iter_videos(song))
    if not mal_id or not slug or not videos:
        return []

    if filename:
        local_basename = os.path.basename(filename).lower()
        video = next((item for item in videos if item[0].lower() == local_basename), videos[0])
        registrations = [(os.path.basename(filename), video)]
    else:
        selected_videos = videos[:1] if preferred_only else videos
        registrations = [(video[0], video) for video in selected_videos]
    preferred_basename = videos[0][0].lower()
    for registered_filename, video in registrations:
        _register_file(
            mal_id,
            song,
            registered_filename,
            video,
            is_gap=is_gap,
            is_preferred=video[0].lower() == preferred_basename,
            is_alternate=is_alternate,
        )
    if merge_metadata:
        _merge_anime_metadata(mal_id, song)
    return [item[0] for item in registrations]


def _existing_non_anisongdb_coverage() -> set[tuple[str, str]]:
    """Return MAL/slug pairs already backed by AnimeThemes or a local file."""
    coverage = set()
    for mal_id, entry in state.metadata.file_metadata.items():
        if not isinstance(entry, dict):
            continue
        themes = entry.get("themes")
        if not isinstance(themes, dict):
            continue
        for slug, versions in themes.items():
            if not isinstance(versions, dict):
                continue
            covered = False
            for files in versions.values():
                if not isinstance(files, dict):
                    continue
                for properties in files.values():
                    # Conservatively retain old entries without a property
                    # dict. They still represent an existing theme source.
                    if not isinstance(properties, dict) or str(
                        properties.get("source", "")
                    ).upper() != "ANISONGDB":
                        covered = True
                        break
                if covered:
                    break
            if covered:
                coverage.add((str(mal_id), str(slug).upper()))
    return coverage


def gap_filenames(*, preferred_only=True, theme_types=None) -> list[str]:
    """Return registered AniSongDB-only media, optionally filtered by OP/ED/IN."""
    accepted_types = None
    if theme_types is not None:
        accepted_types = {str(value).upper() for value in theme_types}
    filenames = []
    for entry in state.metadata.file_metadata.values():
        if not isinstance(entry, dict):
            continue
        for slug, versions in entry.get("themes", {}).items():
            if not isinstance(versions, dict):
                continue
            slug_upper = str(slug).upper()
            theme_type = next(
                (prefix for prefix in ("OP", "ED", "IN") if slug_upper.startswith(prefix)),
                "OTHER",
            )
            if accepted_types is not None and theme_type not in accepted_types:
                continue
            for files in versions.values():
                if not isinstance(files, dict):
                    continue
                for filename, properties in files.items():
                    if not isinstance(properties, dict) or not properties.get("anisongdb_gap"):
                        continue
                    if preferred_only and not properties.get("anisongdb_preferred"):
                        continue
                    filenames.append(filename)
    return sorted(set(filenames), key=str.casefold)


def registered_gap_count() -> int:
    """Return the number of persisted AniSongDB gap projections."""
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
                    if isinstance(properties, dict)
                    and properties.get("anisongdb_gap")
                )
    return count


def registered_alternate_count() -> int:
    """Return the number of selectable AniSongDB alternatives for covered themes."""
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
                    if isinstance(properties, dict)
                    and properties.get("anisongdb_alternate")
                )
    return count


def registered_projection_version() -> int:
    """Return the oldest projection version, including mixed package imports."""
    versions = (
        entry.get("anisongdb_projection_version", 0)
        for entry in state.metadata.file_metadata.values()
        if isinstance(entry, dict)
        and ("anisongdb_projection_version" in entry or "anisongdb_ann_id" in entry)
    )
    return min(versions, default=0)


def _enrich_covered_files(coverage: set[tuple[str, str]]) -> list[str]:
    """Attach IDs/backups and register a selectable AniSongDB alternative."""
    registered = []
    for mal_id, slug in coverage:
        anime = state.metadata.anime_metadata.get(mal_id, {})
        theme = next(
            (
                item
                for item in anime.get("songs", [])
                if isinstance(item, dict) and str(item.get("slug", "")).upper() == slug
            ),
            {},
        )
        song = resolve_song_for_mal_slug(
            mal_id,
            slug,
            title=theme.get("title"),
            artists=theme.get("artist"),
        )
        if not song:
            continue
        entry = state.metadata.file_metadata.get(mal_id)
        if not isinstance(entry, dict):
            continue
        entry["anisongdb_ann_id"] = song.get("annId")
        entry["anisongdb_projection_version"] = PROJECTION_VERSION
        videos = list(iter_videos(song))
        alternate = videos[0] if videos else None
        versions = next(
            (
                value
                for key, value in entry.get("themes", {}).items()
                if str(key).upper() == slug
            ),
            {},
        )
        for files in versions.values():
            if not isinstance(files, dict):
                continue
            for properties in files.values():
                if not isinstance(properties, dict):
                    continue
                if str(properties.get("source", "")).upper() == "ANISONGDB":
                    continue
                properties.update(
                    {
                        key: value
                        for key, value in file_identity(song).items()
                        if value is not None
                    }
                )
                if alternate:
                    basename, resolution, quality = alternate
                    properties.update(
                        {
                            "anisongdb_stream_url": media_url(basename),
                            "anisongdb_media": basename,
                            "anisongdb_quality": quality,
                            "anisongdb_resolution": resolution,
                        }
                    )
                    fallback_urls = [
                        media_url(other_basename)
                        for other_basename, _other_resolution, _other_quality in videos[1:]
                    ]
                    if fallback_urls:
                        properties["anisongdb_fallback_stream_urls"] = fallback_urls
        registered.extend(
            register_song(
                song,
                merge_metadata=False,
                preferred_only=True,
                is_alternate=True,
            )
        )
    return registered


def _refresh_runtime_lookup(filenames: list[str], *, clear_all=False) -> None:
    if not filenames and not clear_all:
        return
    from _app_scripts.file.metadata import metadata_fetch
    from _app_scripts.playlists import playlist

    metadata_fetch.build_filename_to_mal_map()
    metadata_fetch.invalidate_file_metadata_cache()
    metadata_fetch.invalidate_metadata_cache(None if clear_all else filenames)
    playlist.invalidate_deduplicated_cache()


def _assign_theme_slugs(coverage: set[tuple[str, str]]) -> None:
    """Align songs to established slots and number additional songs in order."""
    global _mapped_slugs
    indexes = build_indexes()
    _mapped_slugs = {}
    covered_slots = defaultdict(set)
    for mal_id, slug in coverage:
        covered_slots[mal_id].add(slug)
    for mal_id, source_songs in indexes["mal"].items():
        anime = state.metadata.anime_metadata.get(mal_id, {})
        songs = {
            str(song.get("slug", "")).upper(): song
            for song in anime.get("songs") or [] if isinstance(song, dict)
        }
        slots = set(songs) | covered_slots[mal_id]
        for kind in ("OP", "ED"):
            anchors = {
                slug: songs.get(slug, {}) for slug in slots
                if re.fullmatch(rf"{kind}\d+(?:\.\d+)?", slug)
            }
            rows = sorted(
                (song for song in source_songs if _song_type(song)[0] == kind
                 and not song.get("isDub") and not song.get("isRebroadcast")),
                key=lambda song: (_song_type(song)[1], str(song.get("annSongId")), str(song.get("amqSongId"))),
            )
            for song in rows:
                matches = []
                for slug, theme in anchors.items():
                    if not theme.get("title") and slug != _source_theme_slug(song):
                        continue
                    if _matches_theme(song, theme.get("title"), theme.get("artist")):
                        matches.append(slug)
                if _source_theme_slug(song) in matches:
                    matches = [_source_theme_slug(song)]
                if len(matches) == 1:
                    _mapped_slugs[_song_key(song)] = matches[0]

            occupied = {Decimal(slug[2:]) for slug in anchors}
            previous = None
            index = 0
            while index < len(rows):
                song = rows[index]
                mapped = _mapped_slugs.get(_song_key(song))
                if mapped:
                    previous = Decimal(mapped[2:])
                    index += 1
                    continue
                end = index
                while end < len(rows) and _song_key(rows[end]) not in _mapped_slugs:
                    end += 1
                next_slot = (
                    Decimal(_mapped_slugs[_song_key(rows[end])][2:])
                    if end < len(rows) else None
                )
                lower = previous if previous is not None else (
                    max(Decimal(0), next_slot - 1) if next_slot is not None else Decimal(0)
                )
                between = next_slot is not None and next_slot > lower
                step = Decimal("0.1")
                if between:
                    while True:
                        available = 0
                        candidate = lower + step
                        while candidate < next_slot and available < end - index:
                            available += candidate not in occupied
                            candidate += step
                        if available >= end - index:
                            break
                        step /= 10
                duplicate_slots = {}
                for extra in rows[index:end]:
                    duplicate_key = (
                        _source_theme_slug(extra), _match_key(extra.get("songName")),
                        _match_key(extra.get("songArtist")),
                    )
                    if duplicate_key in duplicate_slots:
                        number = duplicate_slots[duplicate_key]
                    else:
                        number = lower + step if between else Decimal(int(lower) + 1)
                        # With no anchors, retain an upstream gap in numbering.
                        if not anchors:
                            number = max(number, Decimal(_song_type(extra)[1]))
                        while number in occupied:
                            number += step if between else 1
                        occupied.add(number)
                        duplicate_slots[duplicate_key] = number
                        lower = number
                    _mapped_slugs[_song_key(extra)] = kind + format(number.normalize(), "f")
                previous = lower
                index = end


def sync_catalog_to_metadata() -> int:
    """Project gaps plus selectable alternatives for covered themes."""
    if not has_catalog():
        return 0
    # Retain detected MQ and renamed files as logical entries after rebuilding
    # the preferred catalog videos. No physical file is moved or renamed.
    detected_files = []
    for entry in state.metadata.file_metadata.values():
        for versions in entry.get("themes", {}).values():
            for files in versions.values():
                for filename, properties in files.items():
                    if not isinstance(properties, dict) or properties.get("source") != "ANISONGDB":
                        continue
                    song = find_song(filename)
                    if not song:
                        song = build_indexes()["ann_song"].get(str(properties.get("anisongdb_ann_song_id")))
                    videos = list(iter_videos(song)) if song else []
                    if videos and filename.casefold() != videos[0][0].casefold():
                        detected_files.append((filename, song))
    existing_coverage = _existing_non_anisongdb_coverage()
    clear_registered_metadata()
    _assign_theme_slugs(existing_coverage)
    filenames = []
    for song in _catalog().get("songs", []):
        if not isinstance(song, dict) or song.get("isDub") or song.get("isRebroadcast"):
            continue
        mal_id = _mal_id(song)
        slug = theme_slug(song)
        if not mal_id or not slug:
            continue
        _merge_anime_metadata(mal_id, song)
        if (mal_id, slug.upper()) in existing_coverage:
            continue
        filenames.extend(
            register_song(
                song,
                is_gap=True,
                merge_metadata=False,
                preferred_only=True,
            )
        )
    alternate_filenames = _enrich_covered_files(existing_coverage)
    for filename, song in detected_files:
        covered = (_mal_id(song), theme_slug(song).upper()) in existing_coverage
        register_song(song, filename=filename, is_gap=not covered, is_alternate=covered)
    from _app_scripts.file.metadata.metadata_fetch import sort_songs

    for anime in state.metadata.anime_metadata.values():
        if isinstance(anime, dict) and isinstance(anime.get("songs"), list):
            anime["songs"] = sort_songs(anime["songs"])
    _refresh_runtime_lookup(filenames + alternate_filenames, clear_all=True)
    return len(filenames)


def clear_registered_metadata() -> None:
    """Remove stale provider projections without touching other source data."""
    indexes = build_indexes()
    for mal_id, entry in list(state.metadata.file_metadata.items()):
        had_provider = entry.pop("anisongdb_ann_id", None) is not None
        entry.pop("anisongdb_projection_version", None)
        themes = entry.get("themes", {})
        for slug, versions in list(themes.items()):
            for version, files in list(versions.items()):
                for filename, properties in list(files.items()):
                    if isinstance(properties, dict) and properties.get("source") == "ANISONGDB":
                        del files[filename]
                    elif isinstance(properties, dict):
                        for key in list(properties):
                            if key.startswith("anisongdb_"):
                                properties.pop(key, None)
                if not files:
                    del versions[version]
            if not versions:
                del themes[slug]
        if not themes and had_provider:
            state.metadata.file_metadata.pop(mal_id, None)

    provider_keys = {
        "anisongdb_ann_id",
        "anisongdb_category",
        "anisongdb_genres",
        "anisongdb_tags",
    }
    for anime in state.metadata.anime_metadata.values():
        songs = anime.get("songs")
        if isinstance(songs, list):
            retained = []
            for song in songs:
                if song.get("anisongdb_only"):
                    continue
                credits = song.get("anisongdb_credits")
                if not isinstance(credits, dict):
                    # Version 4 did not track ownership. Remove only credits
                    # that still exactly equal the previously attached source.
                    old_source = indexes["ann_song"].get(str(song.get("anisongdb_ann_song_id")))
                    if old_source and str(old_source.get("annId")) == str(song.get("anisongdb_ann_id")):
                        old_metadata = song_metadata(old_source)
                        credits = {key: old_metadata[key] for key in ("composer", "arranger")}
                    else:
                        credits = {}
                for key, value in credits.items():
                    if song.get(key) == value:
                        song.pop(key, None)
                for key in list(song):
                    if key.startswith("anisongdb_"):
                        song.pop(key, None)
                retained.append(song)
            anime["songs"] = retained
        for key in provider_keys:
            anime.pop(key, None)
    _invalidate_artist_display_aliases()


def register_detected_file(filename: str, song: dict | None = None) -> bool:
    """Map a recognized local AniSongDB filename to its catalog song."""
    song = song or find_song(filename)
    filenames = register_song(song, filename=filename) if song else []
    _refresh_runtime_lookup(filenames)
    return bool(filenames)


def song_for_registered_file(filename: str) -> dict | None:
    song = find_song(filename)
    if song:
        return song
    from _app_scripts.file.metadata import metadata_fetch

    file_data = metadata_fetch.get_file_metadata_by_name(filename) or {}
    properties = file_data.get("file_properties") or {}
    song_id = properties.get("anisongdb_amq_song_id")
    if song_id is not None and ensure_catalog():
        return build_indexes()["amq"].get(str(song_id))
    return None


def apply_full_metadata(filename: str, result: dict, *, include_full=True) -> dict:
    """Attach AniSongDB identity and optionally its complete catalog record."""
    properties = result.get("file_properties") or {}
    if isinstance(properties, dict):
        for key in (
            "anisongdb_ann_id",
            "anisongdb_ann_song_id",
            "anisongdb_amq_song_id",
        ):
            value = properties.get(key)
            if value is not None:
                result[key] = value
    if not include_full:
        return result

    song = song_for_registered_file(filename)
    if not song:
        return result
    full = normalize_song(song)
    result["anisongdb"] = full
    result["anisongdb_ann_id"] = song.get("annId")
    result["anisongdb_ann_song_id"] = song.get("annSongId")
    result["anisongdb_amq_song_id"] = song.get("amqSongId")
    # Keep the exact theme row namespaced: top-level ``title`` is the anime
    # title throughout the app, whereas this row's ``title`` is the song.
    result["anisongdb_song"] = song_metadata(song)
    return result
