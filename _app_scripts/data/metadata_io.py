"""Metadata file I/O — save/load the metadata dicts (file/anime/anidb/ai/anilist)
plus the manual-rank estimators used by load_metadata.

The metadata dicts (file_metadata, anime_metadata, …) live in main and are
mutated in place (clear + update) so module-level aliases and state.metadata.*
keep the same identity — see the note in load_metadata.

Sibling metadata helpers (metadata_fetch, metadata_display) are imported
directly.
"""
import atexit
import os
import threading
from core.game_state import state
import json

from _app_scripts import utils
from _app_scripts.file.metadata import metadata_fetch, metadata_display
from core.app_logging import log_exception
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


# Local aliases for utils helpers used here.
save_metadata_atomic     = utils.save_metadata_atomic
save_metadata_compressed = utils.save_metadata_compressed
load_metadata_compressed = utils.load_metadata_compressed
deep_merge               = utils.deep_merge


# --- Debounced save machinery -------------------------------------------------
# A full save serializes + gzips every metadata store (~140MB of JSON) and takes
# multiple seconds; the json.dumps portion holds the GIL, which starves the Tk
# main loop even when the save runs on a worker thread. Fetch paths call
# save_metadata() after every successful fetch, so mid-session bursts used to
# stall the UI repeatedly. Debouncing coalesces those bursts into one save.
_SAVE_DEBOUNCE_SECONDS = 45.0
_save_state_lock = threading.Lock()   # guards _save_timer/_save_pending
_save_io_lock    = threading.Lock()   # serializes actual disk writes
_save_timer      = None
_save_pending    = False


def save_metadata(immediate=False):
    """Persist all metadata stores.

    By default the save is debounced: the write happens on a background timer
    thread up to _SAVE_DEBOUNCE_SECONDS later, and calls arriving in between are
    coalesced into that one write. In-memory state is always current — only the
    disk flush is deferred. Pass immediate=True to write synchronously (app
    close / explicit flush).
    """
    global _save_timer, _save_pending
    if immediate:
        with _save_state_lock:
            if _save_timer is not None:
                _save_timer.cancel()
                _save_timer = None
            _save_pending = False
        _do_save_metadata()
        return
    with _save_state_lock:
        _save_pending = True
        if _save_timer is None:
            _save_timer = threading.Timer(_SAVE_DEBOUNCE_SECONDS, _run_pending_save)
            _save_timer.daemon = True
            _save_timer.start()


def _run_pending_save():
    global _save_timer, _save_pending
    with _save_state_lock:
        _save_timer = None
        if not _save_pending:
            return
        _save_pending = False
    try:
        _do_save_metadata()
    except Exception:
        log_exception("debounced metadata save failed")


def flush_pending_metadata_save():
    """Write now if a debounced save is pending (called at app exit)."""
    with _save_state_lock:
        pending = _save_pending
    if pending:
        save_metadata(immediate=True)


atexit.register(flush_pending_metadata_save)


def _do_save_metadata():
    """Ensures the metadata folder exists before saving metadata files with atomic writes and compression."""
    with _save_io_lock:
        metadata_folder = os.path.dirname(FILE_METADATA_FILE)
        if not os.path.exists(metadata_folder):
            os.makedirs(metadata_folder)

        save_metadata_compressed(FILE_METADATA_FILE, state.metadata.file_metadata)

        deep_merge(state.metadata.anime_metadata, state.metadata.anime_metadata_overrides)
        save_metadata_compressed(ANIME_METADATA_FILE, state.metadata.anime_metadata)
        save_metadata_compressed(ANIDB_METADATA_FILE, state.metadata.anidb_metadata)
        save_metadata_compressed(AI_METADATA_FILE, state.metadata.ai_metadata, encoding="utf-8", ensure_ascii=False)
        save_metadata_compressed(ANILIST_METADATA_FILE, state.metadata.anilist_metadata, encoding="utf-8", ensure_ascii=False)


def save_metadata_overrides():
    save_metadata_atomic(FILE_METADATA_OVERRIDES_FILE, state.metadata.file_metadata_overrides)
    save_metadata_atomic(ANIME_METADATA_OVERRIDES_FILE, state.metadata.anime_metadata_overrides)


def load_metadata():
    # All metadata dicts are mutated in place (clear + update) so the
    # module-level aliases and `state.metadata.*` keep the same identity.
    # For file_metadata specifically, FileMetadataDict.update() also
    # invalidates the cache, so we don't need to call invalidate manually.

    # Load file_metadata (with custom dict class)
    data, is_compressed = load_metadata_compressed(FILE_METADATA_FILE, name="file metadata")
    if data is not None:
        state.metadata.file_metadata.clear()
        state.metadata.file_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        file_count = metadata_fetch.build_filename_to_mal_map()
        print("Loaded file metadata for " + str(len(state.metadata.file_metadata)) + " entries and " + str(file_count) + " files..." + suffix)

    # Load file_metadata_overrides
    data, is_compressed = load_metadata_compressed(FILE_METADATA_OVERRIDES_FILE, name="file metadata overrides")
    if data is not None:
        state.metadata.file_metadata_overrides.clear()
        state.metadata.file_metadata_overrides.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print("Loaded file metadata overrides for " + str(len(state.metadata.file_metadata_overrides)) + " entries..." + suffix)
        deep_merge(state.metadata.file_metadata, state.metadata.file_metadata_overrides)
        # Rebuild the lookup map after applying overrides
        file_count = metadata_fetch.build_filename_to_mal_map()

    # Load anime_metadata
    data, is_compressed = load_metadata_compressed(ANIME_METADATA_FILE, name="anime metadata")
    if data is not None:
        state.metadata.anime_metadata.clear()
        state.metadata.anime_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print("Loaded anime metadata for " + str(len(state.metadata.anime_metadata)) + " entries..." + suffix)

    if os.path.exists(MANUAL_METADATA_FILE):
        with open(MANUAL_METADATA_FILE, "r", encoding="utf-8") as m:
            manual_metadata = json.load(m)
            for entry in manual_metadata:
                state.metadata.anime_metadata[entry] = manual_metadata[entry]
                if state.metadata.anime_metadata[entry].get("reviews") and (metadata_display.is_game(state.metadata.anime_metadata[entry])):
                    state.metadata.anime_metadata[entry]["members"] = state.metadata.anime_metadata[entry].get("reviews") * REVIEW_MODIFIER
                if state.metadata.anime_metadata[entry].get("release"):
                    state.metadata.anime_metadata[entry]["aired"] = state.metadata.anime_metadata[entry].get("release")
                    state.metadata.anime_metadata[entry]["season"] = metadata_fetch.aired_to_season_year(state.metadata.anime_metadata[entry].get("release"))
                state.metadata.anime_metadata[entry]["popularity"] = estimate_manual_popularity(state.metadata.anime_metadata[entry].get("members"))
                state.metadata.anime_metadata[entry]["rank"] = estimate_manual_rank(state.metadata.anime_metadata[entry].get("score"))
    # Load anime_metadata_overrides (plain JSON only — never stored as .gz)
    if os.path.exists(ANIME_METADATA_OVERRIDES_FILE):
        with open(ANIME_METADATA_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            loaded_overrides = json.load(f)
        state.metadata.anime_metadata_overrides.clear()
        state.metadata.anime_metadata_overrides.update(loaded_overrides)
        print("Loaded anime metadata overrides for " + str(len(state.metadata.anime_metadata_overrides)) + " entries...")
        deep_merge(state.metadata.anime_metadata, state.metadata.anime_metadata_overrides)

    # Load anilist_metadata
    data, is_compressed = load_metadata_compressed(ANILIST_METADATA_FILE, encoding="utf-8", name="anilist metadata")
    if data is not None:
        state.metadata.anilist_metadata.clear()
        state.metadata.anilist_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print(f"Loaded anilist metadata for {len(state.metadata.anilist_metadata)} entries...{suffix}")

    # Load anidb_metadata
    data, is_compressed = load_metadata_compressed(ANIDB_METADATA_FILE, name="anidb metadata")
    if data is not None:
        state.metadata.anidb_metadata.clear()
        state.metadata.anidb_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print("Loaded anidb metadata for " + str(len(state.metadata.anidb_metadata)) + " entries..." + suffix)

    # Load ai_metadata
    data, is_compressed = load_metadata_compressed(AI_METADATA_FILE, encoding="utf-8", name="ai metadata")
    if data is not None:
        state.metadata.ai_metadata.clear()
        state.metadata.ai_metadata.update(data)
        suffix = " (compressed)" if is_compressed else ""
        print(f"Loaded ai metadata for {len(state.metadata.ai_metadata)} entries...{suffix}")


REVIEW_MODIFIER = 500


def estimate_manual_popularity(members):
    """Estimate popularity rank based on member count."""
    if not members:
        return None  # Return N/A if no data is available

    # Load all known anime popularity & members counts
    known_popularities = []
    for anime in state.metadata.anime_metadata.values():
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
    for anime in state.metadata.anime_metadata.values():
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
