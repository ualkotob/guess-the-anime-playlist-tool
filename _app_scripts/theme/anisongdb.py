"""AniSongDB full-catalog provider.

The catalog is retained verbatim in ``state.metadata.anisongdb_metadata``.  The
normal app metadata stores receive only the fields needed for lookup, display,
and playback; callers can still retrieve the complete AniSongDB record through
``get_metadata`` without duplicating the catalog for every media variant.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache

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
PROJECTION_VERSION = 21

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
_artist_id_index = None
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
    _invalidate_artist_display_aliases()

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
    # Several provider rows can share one established song. Its anime row
    # retains only one provider identity, while each selectable file retains
    # its own. Restore those mappings too so a restart preserves every slot.
    for entry in state.metadata.file_metadata.values():
        if not isinstance(entry, dict):
            continue
        for slug, versions in entry.get("themes", {}).items():
            for files in versions.values():
                for properties in files.values():
                    if not isinstance(properties, dict) or properties.get("source") != "ANISONGDB" or not properties.get("anisongdb_source_slug"):
                        continue
                    key = (
                        str(properties.get("anisongdb_ann_id")),
                        str(properties.get("anisongdb_ann_song_id")),
                        str(properties.get("anisongdb_amq_song_id")),
                        properties["anisongdb_source_slug"],
                    )
                    _mapped_slugs.setdefault(key, slug)
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
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", value)


@lru_cache(maxsize=32768)
def _song_title_spelling_key(title: str | None) -> str:
    """Keep exact spellings comparable across punctuation and word boundaries."""
    title = unicodedata.normalize("NFKC", str(title or "")).casefold()
    title = title.replace("×", "x")
    title = re.sub(r"(?<![a-z])ver(?:\.|(?=\W|$))", "version", title)
    if len(re.findall(r"[^\W_]+", title)) > 1:
        title = re.sub(r"\bwo\b", "o", title)
    return _match_key(title)


@lru_cache(maxsize=32768)
def _song_title_key(title: str | None) -> str:
    """Compare spelling and long-vowel variants, retaining recording labels."""
    title = unicodedata.normalize("NFKC", str(title or "")).casefold().replace("×", "x")
    title = re.sub(r"(?<![a-z])ver(?:\.|(?=\W|$))", "version", title)
    if len(re.findall(r"[^\W_]+", title)) > 1:
        title = re.sub(r"\bwo\b", "o", title)
    if len(_match_key(title)) <= 3:
        return _match_key(title)
    # Keep English titles such as Shine and Sine distinct. Title comparisons
    # fold vowels and accents, but do not replace Hepburn/Kunrei syllables.
    return _romanization_key(title, fold_syllables=False)


def _song_titles_match(left, right) -> bool:
    # Joining words before vowel folding can change morpheme boundaries:
    # "Niji-iro" and "Nijiiro" must still agree by their exact spelling.
    return bool(_song_title_spelling_key(left)) and (
        _song_title_spelling_key(left) == _song_title_spelling_key(right)
        or _song_title_key(left) == _song_title_key(right)
    )


@lru_cache(maxsize=32768)
def _romanization_key(name: str, *, fold_syllables=True) -> str:
    """Compare common Japanese romanizations without fuzzy edit distance.

    Fold Latin macrons, Hepburn/Kunrei syllables and long vowels in words that
    can be read as romaji. Keep other words and Japanese characters intact.
    This is only an alias lookup key; ambiguous matches are not accepted.
    """
    name = unicodedata.normalize("NFKC", name).casefold()

    def normalize_word(match):
        word = match.group()
        latin = "".join(char for char in unicodedata.normalize("NFKD", word)
                        if not unicodedata.combining(char))
        if not latin.isascii() or not latin.isalpha():
            return word
        accentless = latin
        syllables = (
            ("sha", "sya"), ("shu", "syu"), ("sho", "syo"), ("shi", "si"),
            ("cha", "tya"), ("chu", "tyu"), ("cho", "tyo"), ("chi", "ti"),
            ("tsu", "tu"), ("ja", "zya"), ("ju", "zyu"), ("jo", "zyo"),
            ("ji", "zi"), ("fu", "hu"),
        )
        if fold_syllables:
            for source, target in syllables:
                latin = latin.replace(source, target)
        latin = re.sub(r"oh(?=[bcdfghjkmnprstwyz]|$)", "o", latin)
        latin = re.sub(r"m(?=[bp])", "n", latin)
        if not re.fullmatch(r"(?:[bcdfghjkmnprstwyz]{0,2}[aeiou]|n)+", latin):
            # Latin accents are spelling variants even in non-romaji words.
            return accentless
        return re.sub(r"ou|oo|uu|aa|ee|ii", lambda vowel: vowel.group()[0], latin)

    return _match_key(re.sub(r"[^\W_]+", normalize_word, name))


def _invalidate_artist_display_aliases() -> None:
    global _artist_display_aliases, _artist_id_index
    _artist_display_aliases = None
    _artist_id_index = None
    _reviewed_artist_data.cache_clear()
    _reviewed_artist_alias_keys.cache_clear()
    _reviewed_romanized_artist_keys.cache_clear()
    _source_artist_aliases_by_id.cache_clear()


@lru_cache(maxsize=1)
def _reviewed_artist_data() -> dict[str, tuple]:
    """Index shared artist identities declared in anime metadata overrides.

    Each relevant anime carries these declarations in its exported metadata.
    Read them once per metadata refresh, rather than scanning the stores while
    searching or comparing every pair of performers. Personal overrides have
    priority over publisher declarations for the same artist identity.
    """
    result = {kind: {} for kind in ("artist_aliases", "source_artist_aliases", "group_member_additions")}
    selected = state.metadata.anime_metadata.keys() | state.metadata.anime_metadata_overrides.keys()
    for mal in sorted(selected, key=lambda value: (value in state.metadata.anime_metadata_overrides, str(value))):
        matching = _theme_matching_overrides(str(mal))
        if not isinstance(matching, dict):
            continue
        for kind, rows in result.items():
            records = matching.get(kind)
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                if kind in ("artist_aliases", "source_artist_aliases"):
                    names = record.get("names")
                    if not isinstance(names, list) or not names or not all(isinstance(name, str) and name.strip() for name in names):
                        continue
                    if kind == "artist_aliases":
                        if len(names) < 2:
                            continue
                        key = _match_key(names[0])
                        row = tuple(names)
                    else:
                        identity, observed = record.get("artist_id"), record.get("source_name")
                        if not isinstance(identity, (str, int)) or not isinstance(observed, str) or not observed.strip():
                            continue
                        key = (str(identity), _match_key(observed))
                        row = (str(identity), observed, tuple(names), record.get("reference"))
                else:
                    identity, observed = record.get("artist_id"), record.get("source_name")
                    selected, expected, additions = (record.get(field) for field in ("line_up_id", "expected_members", "additional_members"))
                    if (not isinstance(identity, (str, int)) or not isinstance(observed, str) or not observed.strip()
                            or not isinstance(selected, int) or selected < 0
                            or not isinstance(expected, list) or not expected
                            or not isinstance(additions, list) or not additions
                            or not all(isinstance(value, (str, int)) for value in [*expected, *additions])):
                        continue
                    key = (str(identity), _match_key(observed), selected)
                    row = (str(identity), observed, selected, tuple(expected), tuple(additions), record.get("reference"))
                rows[key] = row
    return {kind: tuple(rows.values()) for kind, rows in result.items()}


def _artist_ids_by_name() -> dict[str, set]:
    global _artist_id_index
    if _artist_id_index is None:
        _artist_id_index = defaultdict(set)
        for artist_id, record in _catalog().get("artists", {}).items():
            if isinstance(record, dict):
                for name in record.get("names") or []:
                    if isinstance(name, str):
                        _artist_id_index[_match_key(name)].add(artist_id)
    return _artist_id_index


def _artist_names_match(left: str, right: str) -> bool:
    """Compare a credit in context even when both spellings are established."""
    left_key, right_key = _match_key(left), _match_key(right)
    if left_key == right_key:
        return True
    ids = _artist_ids_by_name()
    left_ids, right_ids = ids.get(left_key, set()), ids.get(right_key, set())
    if left_ids and right_ids and left_ids.isdisjoint(right_ids):
        return False
    if _artist_credit_key(left) == _artist_credit_key(right):
        return True
    # Person records supply stage-name identities (e.g. senya/Mayumi
    # Morinaga). Group aliases may instead describe contextual casts.
    for artist_id in left_ids & right_ids:
        record_type = str(_catalog().get("artists", {}).get(artist_id, {}).get("type", "")).casefold()
        if record_type == "person" or (
            record_type == "group" and not any(re.search(r"\b(?:feat\.?|featuring|with)\b", name, re.IGNORECASE)
                                               for name in (left, right))
        ):
            return True
    if _reviewed_artist_key(left) == _reviewed_artist_key(right):
        return True
    left_romanized = _romanization_key(left.replace("×", "x"))
    right_romanized = _romanization_key(right.replace("×", "x"))
    return bool(left_romanized) and (
        left_romanized == right_romanized
        or _reversed_person_name_key(left, normalize=_romanization_key) == right_romanized
    )


@lru_cache(maxsize=1)
def _reviewed_artist_alias_keys() -> dict[str, str]:
    result = {}
    for names in _reviewed_artist_data()["artist_aliases"]:
        key = _match_key(names[0])
        for name in names:
            result[_match_key(name)] = key
    return result


def _reviewed_artist_key(name: str) -> str:
    aliases = _reviewed_artist_alias_keys()
    key = _match_key(name)
    exact = aliases.get(key) or aliases.get(_reversed_person_name_key(name))
    if exact:
        return exact
    return _reviewed_romanized_artist_keys().get(_romanization_key(name), key)


@lru_cache(maxsize=1)
def _reviewed_romanized_artist_keys() -> dict[str, str]:
    candidates = defaultdict(set)
    for names in _reviewed_artist_data()["artist_aliases"]:
        for name in names:
            candidates[_romanization_key(name)].add(_match_key(names[0]))
    return {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}


@lru_cache(maxsize=32768)
def _artist_credit_key(name: str) -> str:
    """Normalize complete collaboration spellings without dropping guests."""
    value = unicodedata.normalize("NFKC", str(name or "")).casefold()
    value = re.sub(r"\b(?:featuring\s+|feat(?:\.\s*|\s+))", "feat ", value)
    value = re.sub(r"\band\b", "&", value)
    return _match_key(value)


@lru_cache(maxsize=1)
def _source_artist_aliases_by_id() -> dict[str, list[tuple]]:
    result = defaultdict(list)
    for artist_id, observed, names, _reference in _reviewed_artist_data()["source_artist_aliases"]:
        result[artist_id].append((_match_key(observed), names))
    return result


def _source_artist_aliases(record: dict) -> list[str]:
    observed = {_match_key(name) for name in record.get("names") or []}
    return [name for key, names in _source_artist_aliases_by_id().get(str(record.get("id")), ())
            if key in observed for name in names]


def _reviewed_title_match(song: dict, title) -> bool:
    matching = _theme_matching_overrides(_mal_id(song))
    source_title = _song_title_spelling_key(song.get("songName"))
    target_title = _song_title_spelling_key(title)
    return any(isinstance(alias, dict)
               and str(alias.get("ann_song_id")) == str(song.get("annSongId"))
               and _song_title_spelling_key(alias.get("source_title")) == source_title
               and _song_title_spelling_key(alias.get("title")) == target_title
               for alias in matching.get("title_aliases") or [])


def _performer_rosters_match(song: dict, artists) -> bool:
    """Require the full credited roster when choosing between cast versions."""
    target = [artists] if isinstance(artists, str) else list(artists or [])
    for source in _performer_rosters(song):
        if source and target and len(source) == len(target) and (
            all(any(_artist_names_match(a, b) for b in target) for a in source)
            and all(any(_artist_names_match(a, b) for a in source) for b in target)
        ):
            return True
    records = _matching_credits(song.get("artists"))
    expanded = []
    for record in records:
        members = _selected_vocalist_members(record)
        if members is None:
            expanded = []
            break
        expanded.extend(members)
    for roster in (records, expanded):
        if roster and len(roster) == len(target) and _credit_records_match(roster, target, song.get("songArtist")):
            return True
    return False


def _literal_performer_rosters_match(song: dict, artists) -> bool:
    """Keep all written performers when a table omits a producer or splits a unit.

    Every literal name and every linked source credit must be represented.
    A complete unit can be written as several names in the established table;
    its full credit must match, never just one of its members.
    """
    credit = str(song.get("songArtist") or "")
    target = [artists] if isinstance(artists, str) else list(artists or [])
    records = _matching_credits(song.get("artists"))
    if len(target) > 1 and all(isinstance(name, str) and name.strip() for name in target):
        joined = [separator.join(target) for separator in (" & ", " with ", " to ", " feat. ", " adding ")]
        matching = [name for name in joined if _artist_names_match(credit, name)]
        if matching and all(
            any(_credit_record_matches(record, name, credit) for name in [*target, *matching])
            and (str(record.get("type", "")).casefold() != "group"
                 or _group_credit_members(record, target) is not None)
            for record in records
        ):
            return True
    parts = re.split(r"\s+(?:featuring\s+|(?:feat|ft)(?:\.\s*|\s+)|with\s+|adding\s+)", credit, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return _performer_rosters_match(song, artists)
    names = [parts[0].strip(), *(part.strip() for part in re.split(r"\s*[&\u00d7,]\s*", parts[1]))]
    if not all(names) or len(names) != len(target):
        return False
    if not all(any(_credit_record_matches(record, name, credit) for name in names) for record in records):
        return False
    # Linked records can establish an affiliation spelling or stage name for
    # a literal singer, but cannot add a performer absent from the credit.
    literal_records = [{"type": "person", "names": [name, *[
        alias for record in records if str(record.get("type", "")).casefold() == "person" and _credit_record_matches(record, name, credit)
        for alias in (record.get("names") or [])
    ]]} for name in names]
    return _credit_records_match(literal_records, target)


def _credit_record_matches(record: dict, name: str, fallback=None, *, reviewed=False) -> bool:
    names = (record.get("names") or []) if str(record.get("type", "")).casefold() == "person" else _primary_names([record], fallback)
    if reviewed:
        names = [*names, *_source_artist_aliases(record)]
    return any(_artist_names_match(candidate, name) for candidate in names)


def _credit_records_match(records: list[dict], target: list[str], fallback=None, *, reviewed=False) -> bool:
    """Match every source record to a different credited target performer."""
    edges = [[i for i, name in enumerate(target) if _credit_record_matches(record, name, fallback, reviewed=reviewed)] for record in records]
    owners = {}

    def assign(source, visited):
        for index in edges[source]:
            if index in visited:
                continue
            visited.add(index)
            if index not in owners or assign(owners[index], visited):
                owners[index] = source
                return True
        return False

    return len(records) == len(target) and all(assign(i, set()) for i in range(len(records)))


def _selected_vocalist_members(record: dict, trail=(), *, include_groups=False) -> list[dict] | None:
    """Expand explicit nested group casts, rejecting unknown casts and cycles."""
    if str(record.get("type", "")).casefold() != "group":
        return [record] if record.get("names") else None
    identity = str(record.get("id"))
    if identity in trail:
        return None
    lineups = record.get("line_ups") or []
    selected = record.get("line_up_id", -1)
    if not isinstance(selected, int) or not 0 <= selected < len(lineups):
        vocalists = [i for i, lineup in enumerate(lineups) if lineup.get("line_up_type") == "vocalists"]
        if len(vocalists) != 1:
            return None
        selected = vocalists[0]
    lineup = lineups[selected]
    if lineup.get("line_up_type") != "vocalists" or not lineup.get("members"):
        return None
    result = []
    values = lineup["members"]
    for artist_id, observed, selected_id, expected, additions, _reference in _reviewed_artist_data()["group_member_additions"]:
        if identity != artist_id or selected != selected_id or _match_key(observed) not in {_match_key(name) for name in record.get("names") or []}:
            continue
        actual = {str(value[0]) for value in values if isinstance(value, (list, tuple)) and value}
        known = {str(value) for value in expected}
        allowed = known | {str(value) for value in additions}
        if known <= actual <= allowed:
            values = [*values, *[[value, -1] for value in additions if str(value) not in actual]]
    for member in _matching_credits(values):
        expanded = _selected_vocalist_members(member, (*trail, identity), include_groups=include_groups)
        if expanded is None:
            return None
        if include_groups and str(member.get("type", "")).casefold() == "group":
            result.append(member)
        result.extend(expanded)
    return result or None


def _group_credit_members(record: dict, target: list[str], trail=()) -> list[dict] | None:
    """Read the selected cast without accepting a competing known recording."""
    # Established credits can name nested subgroups rather than their singers.
    members = _selected_vocalist_members(record, include_groups=True)
    if not members:
        return None
    identity = str(record.get("id"))
    if identity in trail:
        return None
    lineups = record.get("line_ups") or []
    selected = record.get("line_up_id", -1)
    vocalists = [(i, lineup) for i, lineup in enumerate(lineups) if lineup.get("line_up_type") == "vocalists"]
    if not isinstance(selected, int) or not 0 <= selected < len(lineups):
        selected = vocalists[0][0]  # Expansion succeeded only for one known cast.
    if any(i != selected and _performer_rosters_match({"artists": other.get("members")}, target)
           for i, other in vocalists):
        return None
    for child in _matching_credits(lineups[selected].get("members")):
        if str(child.get("type", "")).casefold() != "group":
            continue
        child_members = _selected_vocalist_members(child, include_groups=True) or []
        child_target = [name for name in target if _credit_record_matches(child, name, reviewed=True)
                        or any(_credit_record_matches(member, name, reviewed=True) for member in child_members)]
        if child_target:
            if _group_credit_members(child, child_target, (*trail, identity)) is None:
                return None
    return members


def _theme_credit_roles(song: dict, artists) -> tuple[str, ...]:
    """Find composer/arranger credits agreeing with the full established credit.

    This detects a possible difference in credited roles; a cover can share
    these authors, so this evidence alone must never merge recordings.
    """
    return tuple(
        role for role in ("composer", "arranger")
        if _performer_rosters_match(
            {"artists": song.get(role + "s"), "songArtist": song.get("song" + role.title())},
            artists,
        )
    )


def _unaccounted_credit_evidence(song: dict, artists) -> tuple[str, ...]:
    """Explain a unique remaining title using explicit source relationships.

    This relaxed credit check is never a global artist alias. A different
    known cast, an unknown cast, or an uncredited guest remains unresolved.
    """
    roles = _theme_credit_roles(song, artists)
    if roles:
        return roles
    target = [artists] if isinstance(artists, str) else list(artists or [])
    records = _matching_credits(song.get("artists"))
    if not target or not records:
        return ()
    if any(_source_artist_aliases(record) for record in records) and _credit_records_match(records, target, song.get("songArtist"), reviewed=True):
        return ("reviewed_source_artist",)
    if any(str(record.get("type", "")).casefold() == "group" for record in records):
        accounted = set()
        for record in records:
            is_group = str(record.get("type", "")).casefold() == "group"
            members = _group_credit_members(record, target) if is_group else [record]
            if not members:
                return ()
            matches = {i for i, name in enumerate(target)
                       if any(_credit_record_matches(member, name, reviewed=True) for member in members)}
            # Every top-level credited group/person must be represented. This
            # permits incomplete member lists without dropping a guest singer.
            if not matches:
                return ()
            accounted.update(matches)
        if len(accounted) == len(target):
            return ("selected_group_members",)
    if all(str(record.get("type", "")).casefold() == "person" for record in records) and len(target) == 1:
        prefix, separator, _member = str(song.get("songArtist") or "").partition(":")
        if not separator:
            return ()
        represented = 0
        for record in records:
            for group in _matching_credits(record.get("groups")):
                if str(group.get("type", "")).casefold() != "group":
                    continue
                names = group.get("names") or []
                if not any(_artist_names_match(prefix, name) and _artist_names_match(name, target[0]) for name in names):
                    continue
                members = _selected_vocalist_members(group) or []
                if any(str(member.get("id")) == str(record.get("id")) for member in members):
                    represented += 1
                    break
        if represented == len(records):
            return ("credited_group_member",)
    return ()


def _matching_credits(values) -> list[dict]:
    """Read credit names/lineups without copying the complete provider record."""
    result = []
    for value in values or []:
        if isinstance(value, (list, tuple)) and value:
            record = _catalog().get("artists", {}).get(str(value[0]), {})
            if isinstance(record, dict):
                result.append({**record, "id": value[0], "line_up_id": value[1] if len(value) > 1 else -1})
        elif isinstance(value, dict):
            result.append(value)
    return result


def _performer_rosters(song: dict) -> list[list[str]]:
    records = _matching_credits(song.get("artists"))
    primary = _primary_names(records, song.get("songArtist"))
    rosters = [primary]
    expanded = []
    contextual = []
    for record in records:
        selected_names = _primary_names([record], song.get("songArtist"))
        for name in selected_names:
            credit = re.split(r"\s+(?:featuring\s+|feat(?:\.\s*|\s+)|with\s+)", name, maxsplit=1, flags=re.IGNORECASE)
            if len(credit) == 2:
                parts = re.split(r"\s*[&×,]\s*", credit[1])
                known_prefix = _match_key(credit[0]) in {_match_key(alias) for alias in record.get("names") or []}
                literal_names = [credit[0], *(part.strip() for part in parts)]
                known_collaboration = all(_artist_ids_by_name().get(_match_key(part)) for part in literal_names)
                known_cast = (str(record.get("type", "")).casefold() != "group"
                              or not record.get("line_ups")
                              or _group_credit_members(record, literal_names) is not None)
                if parts and all(part.strip() for part in parts) and (known_prefix or known_collaboration) and known_cast:
                    contextual.extend([credit[0], *(part.strip() for part in parts)])
                    continue
            contextual.append(name)
        lineups = record.get("line_ups") or []
        selected = record.get("line_up_id", -1)
        if isinstance(selected, int) and 0 <= selected < len(lineups):
            lineups = [lineups[selected]]
        vocalists = [lineup for lineup in lineups if lineup.get("line_up_type") == "vocalists"]
        # Unknown lineups with multiple casts cannot identify a recording.
        if str(record.get("type", "")).casefold() == "group" and len(vocalists) == 1:
            members = _matching_credits(vocalists[0].get("members"))
            member_names = _primary_names(members, None)
            if members and len(member_names) == len(members):
                expanded.extend(member_names)
                continue
        expanded.extend(_primary_names([record], song.get("songArtist")))
    if expanded and expanded != primary:
        rosters.append(expanded)
    if contextual and contextual != primary:
        rosters.append(contextual)
    if not records and song.get("songArtist"):
        split = re.split(r",\s*|\s+[&×]\s+|\s+(?:feat\.?|featuring|with|and)\s+", song["songArtist"], flags=re.IGNORECASE)
        if len(split) > 1 and all(name.strip() for name in split):
            rosters.append([name.strip() for name in split])
    return rosters


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


def _reversed_person_name_key(name: str, normalize=_match_key) -> str | None:
    """Return a two-part name in reverse order, or None for complex credits."""
    match = re.fullmatch(r"([^\W_]{2,})[ ,]+([^\W_]{2,})\.?", str(name or "").strip())
    if not match:
        return None
    return normalize(f"{match.group(2)} {match.group(1)}")


def _build_artist_display_aliases() -> dict[str, str]:
    """Map AniSongDB aliases to the spelling already used by AnimeThemes.

    Prefer exact aliases, then unambiguous romanizations and two-part name
    reversals. Plain-text song credits need this too: many catalog songs have
    no artist-table links. The retained catalog remains raw.
    """
    preferred = _preferred_artist_spellings()
    romanized = defaultdict(set)
    reviewed = defaultdict(set)
    artist_ids = defaultdict(set)
    names = set()
    for key, spellings in preferred.items():
        for name in spellings:
            romanized[_romanization_key(name)].add(key)
            reviewed[_reviewed_artist_key(name)].add(key)
            names.add(name)
    for artist_id, record in _catalog().get("artists", {}).items():
        if not isinstance(record, dict):
            continue
        for alias in record.get("names") or []:
            if isinstance(alias, str) and alias.strip():
                names.add(alias)
                artist_ids[_match_key(alias)].add(artist_id)
    names.update(song["songArtist"] for song in _catalog().get("songs", [])
                 if isinstance(song, dict) and isinstance(song.get("songArtist"), str)
                 and song["songArtist"].strip())
    # Reviewed spellings also apply to saved credits absent from this catalog.
    names.update(name for group in _reviewed_artist_data()["artist_aliases"] for name in group)
    aliases = {}

    def conflicts_with_artist_id(source_key, target_key):
        # Similar stage names can belong to different performers (e.g. YUUKA
        # and YUKA). Known, disjoint identities outweigh a spelling heuristic.
        source_ids, target_ids = artist_ids[source_key], artist_ids[target_key]
        return source_ids and target_ids and source_ids.isdisjoint(target_ids)

    for alias in sorted(names):
        alias_key = _match_key(alias)
        if not alias_key:
            continue
        display = _preferred_spelling(preferred.get(alias_key))
        if display is None:
            candidates = reviewed.get(_reviewed_artist_key(alias), set())
            if len(candidates) == 1:
                candidate = next(iter(candidates))
                if not conflicts_with_artist_id(alias_key, candidate):
                    display = _preferred_spelling(preferred[candidate])
        if display is None:
            reverse_key = _reversed_person_name_key(alias)
            if not conflicts_with_artist_id(alias_key, reverse_key):
                display = _preferred_spelling(preferred.get(reverse_key))
        if display is None:
            candidates = romanized.get(_romanization_key(alias), set())
            reverse_key = _reversed_person_name_key(alias, normalize=_romanization_key)
            if reverse_key:
                candidates = candidates | romanized.get(reverse_key, set())
            if len(candidates) == 1:
                candidate = next(iter(candidates))
                if not conflicts_with_artist_id(alias_key, candidate):
                    display = _preferred_spelling(preferred[candidate])
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
    for artist in _matching_credits(song.get("artists")):
        if str(artist.get("type", "")).casefold() == "group":
            selected = _primary_names([artist], song.get("songArtist"))
            values.extend(name for name in artist.get("names") or []
                          if name in selected or not re.search(r"\b(?:feat\.?|featuring|with)\b", name, re.IGNORECASE))
        else:
            values.extend(artist.get("names") or [])
    return {
        key for value in values
        for key in (_match_key(value), _match_key(canonical_artist_name(str(value or ""))))
        if key
    }


def _matches_theme(song: dict, title=None, artists=None) -> bool:
    """Known titles and performers must agree; recording qualifiers matter."""
    if _song_title_spelling_key(title) and not _song_titles_match(title, song.get("songName")):
        return _reviewed_title_match(song, title) and (
            _performer_rosters_match(song, artists) or _literal_performer_rosters_match(song, artists)
        )
    values = [artists] if isinstance(artists, str) else (artists or [])
    artist_keys = {
        key for value in values
        for key in (_match_key(value), _match_key(canonical_artist_name(str(value))))
        if key
    }
    source_keys = _song_artist_keys(song) if artist_keys else set()
    if not artist_keys or not source_keys or artist_keys & source_keys:
        return True
    names = [song.get("songArtist"), *_primary_names(_matching_credits(song.get("artists")), song.get("songArtist"))]
    return (any(_artist_names_match(source, target) for source in names for target in values)
            or _performer_rosters_match(song, values) or _literal_performer_rosters_match(song, values))


_REVIEWED_MATCH_FIELDS = (
    "ann_song_id", "amq_song_id", "source_title", "source_artist", "category",
    "source_slug", "source_video", "slug", "title", "artist", "native_file",
)


def _theme_matching_overrides(mal_id: str) -> dict:
    """Combine imported publisher decisions with this user's override priority."""
    published = state.metadata.anime_metadata.get(mal_id)
    personal = state.metadata.anime_metadata_overrides.get(mal_id)
    published = published.get("anisongdb_matching") if isinstance(published, dict) else None
    personal = personal.get("anisongdb_matching") if isinstance(personal, dict) else None
    return {**(published if isinstance(published, dict) else {}), **(personal if isinstance(personal, dict) else {})}


def iter_reviewed_matches(kind: str, mal_id: str | None = None):
    """Read guarded case data from the exported metadata overrides."""
    selected = [mal_id] if mal_id is not None else (
        state.metadata.anime_metadata.keys() | state.metadata.anime_metadata_overrides.keys()
    )
    for mal in selected:
        matching = _theme_matching_overrides(str(mal))
        for record in matching.get(kind) or []:
            if not isinstance(record, dict) or not all(field in record for field in _REVIEWED_MATCH_FIELDS):
                continue
            if not isinstance(record["artist"], list):
                continue
            values = tuple(record[field] for field in _REVIEWED_MATCH_FIELDS)
            yield (str(mal), *values[:9], tuple(values[9]), values[10])


def _reviewed_link_keys(records) -> dict:
    keys = defaultdict(list)
    for mal, ann, amq, title, credit, category, source_slug, media, slug, target_title, artists, filename in records:
        keys[(str(mal), str(ann), str(amq))].append((
            _song_title_spelling_key(title), _artist_credit_key(credit),
            str(category or "").casefold(), str(source_slug).upper(), str(media).casefold(),
            str(slug).upper(), _song_title_spelling_key(target_title),
            tuple(sorted(_match_key(name) for name in artists)), str(filename).casefold(),
        ))
    return dict(keys)


def _reviewed_recording_match(song: dict, theme: dict, slug: str) -> bool:
    """Accept only the currently observed records and verified native clips."""
    keys = _reviewed_link_keys(iter_reviewed_matches("recordings", _mal_id(song)))
    return _reviewed_link_match(song, theme, slug, keys)


def _reviewed_official_credit_match(song: dict, theme: dict, slug: str) -> bool:
    """Apply a primary theme-credit review only to its observed media/credits."""
    keys = _reviewed_link_keys(iter_reviewed_matches("official_credits", _mal_id(song)))
    return _reviewed_link_match(song, theme, slug, keys)


def _reviewed_theme_match(song: dict, theme: dict, slug: str) -> bool:
    return (_reviewed_recording_match(song, theme, slug)
            or _reviewed_official_credit_match(song, theme, slug))


def _reviewed_link_match(song: dict, theme: dict, slug: str, keys: dict) -> bool:
    mal_id = _mal_id(song)
    candidates = keys.get((mal_id, str(song.get("annSongId")), str(song.get("amqSongId"))), ())
    if not candidates:
        return False
    videos = list(iter_videos(song))
    if not videos:
        return False
    artists = theme.get("artist") or []
    if isinstance(artists, str):
        artists = [artists]
    identity = (
        _song_title_spelling_key(song.get("songName")), _artist_credit_key(song.get("songArtist") or ""),
        str(song.get("songCategory") or "").casefold(), str(_source_theme_slug(song)).upper(), videos[0][0].casefold(),
        str(slug).upper(), _song_title_spelling_key(theme.get("title")),
        tuple(sorted(_match_key(name) for name in artists)),
    )
    established_files = {
        str(filename).casefold()
        for files in state.metadata.file_metadata.get(mal_id, {}).get("themes", {}).get(slug, {}).values()
        for filename, properties in files.items()
        if isinstance(properties, dict) and str(properties.get("source", "")).upper() != "ANISONGDB"
    }
    return any(identity == candidate[:-1] and candidate[-1] in established_files for candidate in candidates)


def _matches_projected_credit_role(song: dict, title, artists) -> bool:
    """Resolve a credit discrepancy only through a current established mapping."""
    mal_id = _mal_id(song)
    anime = state.metadata.anime_metadata.get(mal_id, {})
    if anime.get("anisongdb_projection_version") != PROJECTION_VERSION:
        return False
    files = state.metadata.file_metadata.get(mal_id, {})
    if ("anisongdb_projection_version" in files or "anisongdb_ann_id" in files) and files.get("anisongdb_projection_version") != PROJECTION_VERSION:
        return False
    mapped = _mapped_slugs.get(_song_key(song))
    anchor = next((theme for theme in anime.get("songs") or []
                   if theme.get("slug") == mapped and not theme.get("anisongdb_only")), None)
    if not anchor or not _song_titles_match(title, anchor.get("title")):
        return False
    recording_match = _reviewed_theme_match(song, anchor, mapped)
    if not recording_match and not (_song_titles_match(title, song.get("songName")) or _reviewed_title_match(song, title)):
        return False
    anchor_artists = anchor.get("artist") or []
    if isinstance(anchor_artists, str):
        anchor_artists = [anchor_artists]
    return (recording_match or bool(_unaccounted_credit_evidence(song, anchor_artists))) and _performer_rosters_match(
        {"artists": [{"names": [name]} for name in anchor_artists]}, artists,
    )


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
    match = re.fullmatch(r"(OP|ED|IN)(\d+(?:\.\d+)?)(?:-(?:BD|HD|TV|SOUND))?", str(slug or ""), re.IGNORECASE)
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
        and (_matches_theme(song, title, artists) or _matches_projected_credit_role(song, title, artists))
    ]
    if not candidates:
        return None

    # A verified clip in this slot has stronger evidence than another cast's
    # matching answer credits. Check it before the roster filter can discard it.
    anchor = next((theme for theme in state.metadata.anime_metadata.get(str(mal_id), {}).get("songs") or []
                   if str(theme.get("slug", "")).upper() == str(slug).upper() and not theme.get("anisongdb_only")), None)
    if anchor:
        reviewed = [song for song in candidates if song in slot_candidates
                    and _reviewed_theme_match(song, anchor, anchor["slug"])
                    and _matches_projected_credit_role(song, title, artists)]
        if reviewed:
            return reviewed[0]

    exact_rosters = [song for song in candidates if _performer_rosters_match(song, artists)]
    if exact_rosters:
        candidates = exact_rosters
    in_slot = [song for song in candidates if song in slot_candidates]
    if in_slot:
        candidates = in_slot
    if len(candidates) == 1:
        return candidates[0]

    # Duplicate ANN rows sometimes describe the same actual song. Choosing one
    # is safe when the answer-facing title and artist are identical.
    answers = {
        (_song_title_key(song.get("songName")),
         _match_key(canonical_artist_name(str(song.get("songArtist") or ""))))
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
            # A character credit must not replace the actor's own name in
            # another song just because both aliases share a provider row.
            reviewed = _source_artist_aliases({**record, "names": [selected]})
            selected = canonical_artist_name(reviewed[0] if reviewed else selected)
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
    anime["anisongdb_projection_version"] = PROJECTION_VERSION

    # AnimeThemes/MAL-backed rows normally provide this list. Provider-only
    # rows do not, but several established UI paths treat it as iterable.
    if anime.get("themes") is None:
        anime["themes"] = []

    incoming = song_metadata(song)
    if not isinstance(anime.get("songs"), list):
        anime["songs"] = []
    songs = anime["songs"]
    existing = next(
        (item for item in songs if str(item.get("slug", "")).upper() == str(incoming.get("slug", "")).upper()),
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
    """Return the oldest projection version across both saved stores."""
    versions = []
    for mal_id, entry in state.metadata.file_metadata.items():
        if not isinstance(entry, dict) or not (
            "anisongdb_projection_version" in entry or "anisongdb_ann_id" in entry
        ):
            continue
        version = entry.get("anisongdb_projection_version", 0)
        if version >= 6:
            # From v6 onward, both stores must agree. A newer file index paired
            # with old song rows can otherwise retain false OP/ED duplicates.
            anime = state.metadata.anime_metadata.get(mal_id, {})
            song_version = anime.get("anisongdb_projection_version", 0) if isinstance(anime, dict) else 0
            version = min(version, song_version)
        versions.append(version)
    return min(versions, default=0)


def _enrich_covered_files(coverage: set[tuple[str, str]]) -> list[str]:
    """Attach backups and retain every mapped AniSongDB video alternative."""
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
        alternatives = [
            candidate for candidate in songs_for_mal_slug(mal_id, slug)
            if not candidate.get("isDub") and not candidate.get("isRebroadcast")
            and (_matches_theme(candidate, theme.get("title"), theme.get("artist"))
                 or _matches_projected_credit_role(candidate, theme.get("title"), theme.get("artist")))
        ]
        if not song and alternatives:
            song = alternatives[0]
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
        # Several provider rows can describe one established recording while
        # supplying different clips. Each clip must remain directly selectable.
        for candidate in [song, *(item for item in alternatives if _song_key(item) != _song_key(song))]:
            registered.extend(
                register_song(
                    candidate,
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


def _unaccounted_title_pairs(rows: list[dict], anchors: dict, mappings: dict) -> list[tuple[dict, str]]:
    """Find unique same-title pairs remaining after the performer matching pass.

    A matched base slot also accounts for its HD/TV/Sound clips. Every remaining
    source row participates in ambiguity checks, including rows with different
    composers, so the order of the catalog cannot choose a cover accidentally.
    """
    accounted = {str(mappings[_song_key(song)]).upper().split("-", 1)[0]
                 for song in rows if _song_key(song) in mappings}
    remaining = {slug: theme for slug, theme in anchors.items()
                 if slug.split("-", 1)[0] not in accounted and theme.get("title")}
    sources = {_song_key(song): song for song in rows if _song_key(song) not in mappings}
    matches = {key: [slug for slug, theme in remaining.items()
                     if (_song_titles_match(song.get("songName"), theme.get("title"))
                         or _reviewed_title_match(song, theme.get("title")))]
               for key, song in sources.items()}
    frequency = Counter(slug for candidates in matches.values() for slug in candidates)
    return [(sources[key], candidates[0]) for key, candidates in matches.items()
            if len(candidates) == 1 and frequency[candidates[0]] == 1]


def _apply_native_theme_overrides(coverage: set[tuple[str, str]]) -> None:
    """Apply native theme edits before matching provider rows to their slots."""
    from _app_scripts import utils

    for mal, overrides in state.metadata.anime_metadata_overrides.items():
        themes = {str(song.get("slug", "")).upper(): song
                  for song in state.metadata.anime_metadata.get(str(mal), {}).get("songs") or []
                  if isinstance(song, dict)}
        for override in overrides.get("songs") or []:
            if not isinstance(override, dict):
                continue
            slug = str(override.get("slug", "")).upper()
            if (str(mal), slug) in coverage and slug in themes:
                utils.deep_merge(themes[slug], deepcopy(override))


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
                if re.fullmatch(rf"{kind}\d+(?:\.\d+)?(?:-(?:BD|HD|TV|SOUND))?", slug)
            }
            rows = sorted(
                (song for song in source_songs if _song_type(song)[0] == kind
                 and not song.get("isDub") and not song.get("isRebroadcast")),
                key=lambda song: (_song_type(song)[1], str(song.get("annSongId")), str(song.get("amqSongId"))),
            )
            def cast_matches(song, slug, theme):
                return (not theme.get("artist_complete_roster")
                        or _literal_performer_rosters_match(song, theme.get("artist")))

            for song in rows:
                reviewed = [slug for slug, theme in anchors.items()
                            if _reviewed_theme_match(song, theme, slug)]
                if len(reviewed) == 1:
                    _mapped_slugs[_song_key(song)] = anchors[reviewed[0]].get("slug") or reviewed[0]
            for song in rows:
                if _song_key(song) in _mapped_slugs:
                    continue
                matches = []
                for slug, theme in anchors.items():
                    if not cast_matches(song, slug, theme):
                        continue
                    if not theme.get("title") and slug != _source_theme_slug(song):
                        continue
                    if _matches_theme(song, theme.get("title"), theme.get("artist")):
                        matches.append(slug)
                identified = [slug for slug in matches if anchors[slug].get("title")]
                if identified:
                    matches = identified
                exact_rosters = [slug for slug in matches if _performer_rosters_match(song, anchors[slug].get("artist"))]
                if exact_rosters:
                    matches = exact_rosters
                if _source_theme_slug(song) in matches:
                    matches = [_source_theme_slug(song)]
                elif len(matches) > 1:
                    # Prefer a unique standard slot when the qualified clips
                    # share its number or all reference the same native video.
                    plain = [slug for slug in matches if "-" not in slug]
                    if len(plain) == 1:
                        same_number = all(slug.split("-", 1)[0] == plain[0] for slug in matches)
                        # TV and BD theme numbering can diverge while both
                        # slots reference the exact same native video. That
                        # shared source also identifies the standard slot.
                        native_files = [
                            {str(filename).casefold()
                             for files in state.metadata.file_metadata.get(mal_id, {}).get("themes", {}).get(slug, {}).values()
                             for filename, properties in files.items()
                             if isinstance(properties, dict) and str(properties.get("source", "")).upper() != "ANISONGDB"}
                            for slug in matches
                        ]
                        if same_number or set.intersection(*native_files):
                            matches = plain
                if len(matches) == 1:
                    _mapped_slugs[_song_key(song)] = anchors[matches[0]].get("slug") or matches[0]

            # Reconcile unaccounted themes before numbering additional entries.
            # A unique title and explicit author/member/identity evidence can
            # explain differing credits. A cover of an already accounted-for
            # song remains an extra, without relaxing artist matching globally.
            for song, slug in _unaccounted_title_pairs(rows, anchors, _mapped_slugs):
                if (cast_matches(song, slug, anchors[slug])
                        and _unaccounted_credit_evidence(song, anchors[slug].get("artist"))):
                    _mapped_slugs[_song_key(song)] = anchors[slug].get("slug") or slug

            occupied = {Decimal(slug[2:].split("-", 1)[0]) for slug in anchors}
            previous = None
            index = 0
            while index < len(rows):
                song = rows[index]
                mapped = _mapped_slugs.get(_song_key(song))
                if mapped:
                    previous = Decimal(mapped[2:].split("-", 1)[0])
                    index += 1
                    continue
                end = index
                while end < len(rows) and _song_key(rows[end]) not in _mapped_slugs:
                    end += 1
                next_slot = (
                    Decimal(_mapped_slugs[_song_key(rows[end])][2:].split("-", 1)[0])
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
                        _source_theme_slug(extra), _song_title_key(extra.get("songName")),
                        _match_key(canonical_artist_name(str(extra.get("songArtist") or ""))),
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
    _apply_native_theme_overrides(existing_coverage)
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
        "anisongdb_projection_version",
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
