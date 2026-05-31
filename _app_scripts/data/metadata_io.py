"""Metadata file I/O — save/load the metadata dicts (file/anime/anidb/ai/anilist)
plus the manual-rank estimators used by load_metadata.

The metadata dicts (file_metadata, anime_metadata, …) live in main and are
mutated in place (clear + update) so module-level aliases and state.metadata.*
keep the same identity — see the note in load_metadata.

Cross-module references go through `_main.X`; set_context binds it.
"""
import os
import json

from _app_scripts import utils
from core.paths import (
    FILE_METADATA_FILE,
    FILE_METADATA_OVERRIDES_FILE,
    ANIME_METADATA_FILE,
    ANIME_METADATA_OVERRIDES_FILE,
    ANIDB_METADATA_FILE,
    AI_METADATA_FILE,
    ANILIST_METADATA_FILE,
    MANUAL_METADATA_FILE,
)

_main = None  # populated by set_context()


def set_context(*, main_module):
    global _main
    _main = main_module


# Local aliases for utils helpers used here.
save_metadata_atomic     = utils.save_metadata_atomic
save_metadata_compressed = utils.save_metadata_compressed
load_metadata_compressed = utils.load_metadata_compressed
deep_merge               = utils.deep_merge


def save_metadata():
    """Ensures the metadata folder exists before saving metadata files with atomic writes and compression."""
    metadata_folder = os.path.dirname(FILE_METADATA_FILE)
    if not os.path.exists(metadata_folder):
        os.makedirs(metadata_folder)

    save_metadata_compressed(FILE_METADATA_FILE, _main.file_metadata)

    deep_merge(_main.anime_metadata, _main.anime_metadata_overrides)
    save_metadata_compressed(ANIME_METADATA_FILE, _main.anime_metadata)
    save_metadata_compressed(ANIDB_METADATA_FILE, _main.anidb_metadata)
    save_metadata_compressed(AI_METADATA_FILE, _main.ai_metadata, encoding="utf-8", ensure_ascii=False)
    save_metadata_compressed(ANILIST_METADATA_FILE, _main.anilist_metadata, encoding="utf-8", ensure_ascii=False)


def save_metadata_overrides():
    save_metadata_atomic(FILE_METADATA_OVERRIDES_FILE, _main.file_metadata_overrides)
    save_metadata_atomic(ANIME_METADATA_OVERRIDES_FILE, _main.anime_metadata_overrides)


def load_metadata():
    # All metadata dicts are mutated in place (clear + update) so the
    # module-level aliases and `state.metadata.*` keep the same identity.
    # For file_metadata specifically, FileMetadataDict.update() also
    # invalidates the cache, so we don't need to call invalidate manually.

    # Load file_metadata (with custom dict class)
    data, is_compressed = load_metadata_compressed(FILE_METADATA_FILE, name="file metadata")
    if data is not None:
        _main.file_metadata.clear()
        _main.file_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        file_count = _main.build_filename_to_mal_map()
        print("Loaded file metadata for " + str(len(_main.file_metadata)) + " entries and " + str(file_count) + " files..." + suffix)

    # Load file_metadata_overrides
    data, is_compressed = load_metadata_compressed(FILE_METADATA_OVERRIDES_FILE, name="file metadata overrides")
    if data is not None:
        _main.file_metadata_overrides.clear()
        _main.file_metadata_overrides.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print("Loaded file metadata overrides for " + str(len(_main.file_metadata_overrides)) + " entries..." + suffix)
        deep_merge(_main.file_metadata, _main.file_metadata_overrides)
        # Rebuild the lookup map after applying overrides
        file_count = _main.build_filename_to_mal_map()

    # Load anime_metadata
    data, is_compressed = load_metadata_compressed(ANIME_METADATA_FILE, name="anime metadata")
    if data is not None:
        _main.anime_metadata.clear()
        _main.anime_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print("Loaded anime metadata for " + str(len(_main.anime_metadata)) + " entries..." + suffix)

    if os.path.exists(MANUAL_METADATA_FILE):
        with open(MANUAL_METADATA_FILE, "r", encoding="utf-8") as m:
            manual_metadata = json.load(m)
            for entry in manual_metadata:
                _main.anime_metadata[entry] = manual_metadata[entry]
                if _main.anime_metadata[entry].get("reviews") and (_main.is_game(_main.anime_metadata[entry])):
                    _main.anime_metadata[entry]["members"] = _main.anime_metadata[entry].get("reviews") * REVIEW_MODIFIER
                if _main.anime_metadata[entry].get("release"):
                    _main.anime_metadata[entry]["aired"] = _main.anime_metadata[entry].get("release")
                    _main.anime_metadata[entry]["season"] = _main.aired_to_season_year(_main.anime_metadata[entry].get("release"))
                _main.anime_metadata[entry]["popularity"] = estimate_manual_popularity(_main.anime_metadata[entry].get("members"))
                _main.anime_metadata[entry]["rank"] = estimate_manual_rank(_main.anime_metadata[entry].get("score"))
    # Load anime_metadata_overrides (plain JSON only — never stored as .gz)
    if os.path.exists(ANIME_METADATA_OVERRIDES_FILE):
        with open(ANIME_METADATA_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            loaded_overrides = json.load(f)
        _main.anime_metadata_overrides.clear()
        _main.anime_metadata_overrides.update(loaded_overrides)
        print("Loaded anime metadata overrides for " + str(len(_main.anime_metadata_overrides)) + " entries...")
        deep_merge(_main.anime_metadata, _main.anime_metadata_overrides)

    # Load anilist_metadata
    data, is_compressed = load_metadata_compressed(ANILIST_METADATA_FILE, encoding="utf-8", name="anilist metadata")
    if data is not None:
        _main.anilist_metadata.clear()
        _main.anilist_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print(f"Loaded anilist metadata for {len(_main.anilist_metadata)} entries...{suffix}")

    # Load anidb_metadata
    data, is_compressed = load_metadata_compressed(ANIDB_METADATA_FILE, name="anidb metadata")
    if data is not None:
        _main.anidb_metadata.clear()
        _main.anidb_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print("Loaded anidb metadata for " + str(len(_main.anidb_metadata)) + " entries..." + suffix)

    # Load ai_metadata
    data, is_compressed = load_metadata_compressed(AI_METADATA_FILE, encoding="utf-8", name="ai metadata")
    if data is not None:
        _main.ai_metadata.clear()
        _main.ai_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print(f"Loaded ai metadata for {len(_main.ai_metadata)} entries...{suffix}")


REVIEW_MODIFIER = 500


def estimate_manual_popularity(members):
    """Estimate popularity rank based on member count."""
    if not members:
        return None  # Return N/A if no data is available

    # Load all known anime popularity & members counts
    known_popularities = []
    for anime in _main.anime_metadata.values():
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
        return None  # Return N/A if no data is available

    # Load all known anime rank & score
    known_ranks = []
    for anime in _main.anime_metadata.values():
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
