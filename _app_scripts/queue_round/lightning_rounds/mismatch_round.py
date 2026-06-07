"""Mismatch lightning round — plays one theme's audio with another's video.

Picks a tag/year-similar but different-series theme as the visual decoy,
adds it as an external mpv video track on top of the real theme's audio.
The actual mpv video-add and seek dance lives in
``lightning_manager.update_light_round`` (it needs to coordinate with the
broader round timing); this module owns the picker, the NSFW filter, and
the live mismatch-state flags.
"""
from __future__ import annotations
from core.game_state import state

import random

from _app_scripts import utils
from _app_scripts.file.metadata import metadata_fetch, metadata_display
from _app_scripts.information import information_popup
from _app_scripts.toggles import censors


is_slug_op = utils.is_slug_op


# ---------------------------------------------------------------------------
# Mismatch state — owned here, written by lightning_manager.update_light_round
# during the round start, read back during clean_up_light_round.
# ---------------------------------------------------------------------------
cached_sfw_themes = {}
mismatch_visuals = None

_mismatch_active = False
_mismatch_vid_track_id = None   # track ID of the external video added via video-add
_mismatch_orig_vid = None        # original video track ID before mismatch was applied
_mismatch_hwnd = 0   # unused (kept so references elsewhere don't error)
_main_hwnd = 0
_note_hwnd = 0


def _uninstall_mismatch_hook():
    pass  # removed — no longer needed


def get_cached_sfw_themes():
    global cached_sfw_themes
    cached_sfw_themes = {
        "ops":[],
        "eds":[]
    }
    for filename in state.metadata.directory_files:
        if not check_nsfw(filename):
            data = metadata_fetch.get_metadata(filename)
            if data:
                if is_slug_op(data.get("slug")):
                    cached_sfw_themes["ops"].append(filename)
                else:
                    cached_sfw_themes["eds"].append(filename)


def get_mismatched_theme():
    global mismatch_visuals
    match_data = state.playback.currently_playing.get("data")
    if not match_data:
        return None

    is_op = is_slug_op(match_data.get("slug"))
    match_series = metadata_display.series_primary(match_data)
    match_season = match_data.get("season")  # e.g., "Fall 2020"

    # Convert season to year
    def extract_year(season_str):
        if season_str and isinstance(season_str, str) and season_str[-4:].isdigit():
            return int(season_str[-4:])
        return None

    match_year = extract_year(match_season)

    # Return {tag_name: rank} from anilist_metadata for a given anime data dict.
    # Uses file_metadata to resolve MAL → AniList ID, then looks up tags.
    def get_anilist_tags(data):
        mal_id = data.get("mal")
        if not mal_id:
            return {}
        fm = state.metadata.file_metadata.get(str(mal_id)) or state.metadata.file_metadata.get(mal_id)
        if not fm:
            return {}
        al_id = fm.get("anilist")
        if not al_id:
            return {}
        al = state.metadata.anilist_metadata.get(str(al_id))
        if not al:
            return {}
        return {t["name"]: t.get("rank", 0) for t in al.get("tags", []) if t.get("name")}

    match_anilist_tags = get_anilist_tags(match_data)
    match_basic_tags   = set(information_popup.get_tags(match_data))  # fallback when no AniList data

    theme_pool = cached_sfw_themes["ops"] if is_op else cached_sfw_themes["eds"]
    if len(theme_pool) <= 1:
        theme_pool = cached_sfw_themes["ops"] + cached_sfw_themes["eds"]

    candidates = []

    for filename in theme_pool:
        file_data = metadata_fetch.get_metadata(filename)
        if not file_data:
            continue

        file_series = metadata_display.series_primary(file_data)
        if file_series == match_series:
            continue  # skip same series

        file_year = extract_year(file_data.get("season"))

        # Tag similarity: prefer AniList weighted overlap (min(rank1,rank2)/100 per shared tag),
        # same formula as bonus get_random_titles. Fall back to basic set-overlap count.
        file_anilist_tags = get_anilist_tags(file_data)
        if match_anilist_tags and file_anilist_tags:
            tag_score = sum(
                min(match_anilist_tags[name], file_anilist_tags[name]) / 100
                for name in match_anilist_tags if name in file_anilist_tags
            )
        else:
            tag_score = len(match_basic_tags & set(information_popup.get_tags(file_data)))

        year_score = 0
        if match_year and file_year:
            year_diff = abs(match_year - file_year)
            year_score = max(0, 5 - year_diff)  # Closer years get more points

        # Add a little randomness
        random_bonus = random.uniform(0, 1.5)

        total_score = tag_score * 1.5 + year_score + random_bonus

        candidates.append((total_score, filename, file_data))

    if not candidates:
        tries = 0
        while tries <= 10:
            filename = random.choice(theme_pool)
            file_data = metadata_fetch.get_metadata(filename)
            file_series = metadata_display.series_primary(file_data)
            if file_series != match_series:
                mismatch_visuals = metadata_display.get_display_title(file_data) + " " + utils.format_slug(file_data.get("slug"))
                return filename
            tries += 1
        return None

    # Sort by score and randomly choose from top 5
    candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = candidates[:5]
    score, chosen_filename, chosen_data = random.choice(top_candidates)

    mismatch_visuals = metadata_display.get_display_title(chosen_data) + " " + utils.format_slug(chosen_data.get("slug"))
    return chosen_filename


def check_nsfw(filename):
    for censor in censors.get_file_censors(filename):
        if censor.get("nsfw"):
            return True
    data = metadata_fetch.get_metadata(filename)
    if data:
        theme = utils.get_song_by_slug(data, data.get("slug", ""))
        if theme.get("nsfw"):
            return True
    return False
