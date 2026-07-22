"""Variety lightning round — picks a random lightning mode each round.

Owns variety-mode selection state (cooldown counters, popularity cache,
recent-history tracking) and the per-mode info-availability checks used to
filter what modes are viable for a given theme. ``queue_next_lightning_mode``
in :mod:`lightning_manager` calls into this module when variety mode is on.
"""
from __future__ import annotations
from core.game_state import state

import random

from _app_scripts import utils
from _app_scripts.playback import streaming
from _app_scripts.file.metadata import metadata_fetch, metadata_display
from _app_scripts.information import information_popup
from _app_scripts.queue_round.lightning_rounds import (
    character_parts_overlay,
    cover_image_overlay,
    episode_overlay,
    lightning_settings,
    title_overlay,
)


# ---------------------------------------------------------------------------
# Variety state
# ---------------------------------------------------------------------------
last_round = None
last_variety_forced = False
variety_light_mode_enabled = False
testing_variety = False

# Seed each mode's cooldown counter at a random value within its allowed gap so
# the first variety round doesn't always force the same modes.
variety_mode_cooldown_counts = {}
for rnd_name, rnd_data in lightning_settings.lightning_mode_settings_default.items():
    vr = rnd_data.get("variety", {})
    if vr:
        cd = vr.get("cooldown", {})
        variety_mode_cooldown_counts[rnd_name] = random.randint(0, cd.get("max_gap", 0))
    else:
        variety_mode_cooldown_counts[rnd_name] = 0

is_slug_op = utils.is_slug_op


# ---------------------------------------------------------------------------
# Recent-history tracking — used by variety's no_repeat_limit cooldown.
# ---------------------------------------------------------------------------
def append_lightning_history():
    data = state.playback.currently_playing.get("data", {})
    mode_limits = state.playback.lightning_mode_settings.get(state.lightning.light_mode, {}).get("variety", {}).get("cooldown")
    if mode_limits and mode_limits.get("no_repeat_limit", 0) > 0:
        if "c." in state.lightning.light_mode:
            append = state.lightning.character_round_answer[0]
        elif state.lightning.light_mode == "title":
            append = title_overlay.get_base_title()
        else:
            append = data.get("mal")
        if append:
            history_by_mode = state.metadata.playlist.get("lightning_history")
            if not isinstance(history_by_mode, dict):
                history_by_mode = {}
                state.metadata.playlist["lightning_history"] = history_by_mode
            history_by_mode.setdefault(state.lightning.light_mode, []).append(append)
            while len(history_by_mode[state.lightning.light_mode]) > mode_limits.get("no_repeat_limit"):
                history_by_mode[state.lightning.light_mode].pop(0)


def check_recent_history(mode, data=None):
    from _app_scripts.queue_round.lightning_rounds import lightning_manager
    if not data:
        data = state.playback.currently_playing.get("data", {})
    mode_limits = state.playback.lightning_mode_settings.get(mode, {}).get("variety", {}).get("cooldown")
    if mode_limits and mode_limits.get("no_repeat_limit"):
        if "c." in mode:
            data = state.playback.currently_playing.get("data", {})
            history = state.metadata.playlist.get("lightning_history", {}).get(mode, [])
            valid_types = lightning_manager.get_char_types_by_popularity(data, mode)
            for char in data.get("characters", []):
                role = char[0]
                name = char[1]
                if role in valid_types and name not in history:
                    return False  # Found a character not in history
            return True  # All valid characters are in history
        elif mode == "title":
            append_check = title_overlay.get_base_title(data)
        else:
            append_check = data.get("mal")

        if append_check:
            return append_check in state.metadata.playlist.get("lightning_history", {}).get(mode, [])
    return False


_series_popularity_cache = None
def get_series_popularity(data):
    global _series_popularity_cache

    if _series_popularity_cache is None:
        _series_popularity_cache = {}
        for anime in state.metadata.anime_metadata.values():
            pop = anime.get("popularity") or 10000
            if not isinstance(pop, (int, float)):
                pop = 10000  # placeholder values like "N/A"
            for s in metadata_display.series_list(anime, fallback_title=False):
                if s not in _series_popularity_cache or pop < _series_popularity_cache[s]:
                    _series_popularity_cache[s] = pop

    pops = [_series_popularity_cache[s] for s in metadata_display.series_list(data, fallback_title=False) if s in _series_popularity_cache]
    fallback = data.get("popularity") or 10000
    if not isinstance(fallback, (int, float)):
        fallback = 10000
    return min(pops) if pops else fallback


# ---------------------------------------------------------------------------
# Variety mode picker — chooses the next lightning mode based on popularity
# bands, per-mode cooldowns, weighting, and no-repeat history.
# ---------------------------------------------------------------------------
def set_variety_light_mode(queue=None, excluded_modes=[]):
    from _app_scripts.queue_round.lightning_rounds import lightning_manager
    global last_round, variety_light_mode_enabled, last_variety_forced

    forced = False
    if not queue and lightning_manager.lightning_queue and lightning_manager.lightning_queue[0] == state.playback.currently_playing.get("filename"):
        next_round = lightning_manager.lightning_queue[1]
    else:
        if queue:
            data = metadata_fetch.get_metadata(queue)
        else:
            data = state.playback.currently_playing.get('data', {})
        popularity = ((data.get('popularity') or 3000) + get_series_popularity(data)) / 2

        is_op = is_slug_op(data.get('slug', ""))

        variety_settings = state.playback.lightning_mode_settings.get("variety", {})
        popularity_limit = variety_settings.get("popularity_limit", True)
        series_mode_limit = variety_settings.get("series_mode_limit", True)
        mode_weight = variety_settings.get("mode_weight", True)
        mode_cooldowns = variety_settings.get("mode_cooldowns", True)

        round_options = []
        for rnd_name, rnd_data in state.playback.lightning_mode_settings.items():
            v_data = rnd_data.get("variety", {})
            if v_data and v_data["enabled"] and rnd_name not in excluded_modes:
                pop_limit = v_data.get("popularity", {})
                range = pop_limit.get("range", (0,0))
                if not popularity_limit:
                    range = (0,0)
                weight = pop_limit.get("weight", 10)
                if not mode_weight:
                    weight = 1
                elif isinstance(weight, dict):
                    if is_op:
                        weight = weight.get("op")
                    else:
                        weight = weight.get("ed")
                if has_lightning_mode_info(data, rnd_name) and popularity > range[0] and (not range[1] or popularity <= range[1]):
                    round_options += [rnd_name]*weight

        # Remove last round from options to avoid repeats
        round_options = [r for r in round_options if r != last_round]

        # Apply cooldown filtering
        forced_options = []
        forced_max_pop_limit = 3000
        for rnd_name, rnd_data in state.playback.lightning_mode_settings.items():
            v_data = rnd_data.get("variety", {})
            cd = v_data.get("cooldown", {})
            min_cooldown = cd.get("min_gap", 0)
            max_cooldown = cd.get("max_gap", 10000)
            if not mode_cooldowns:
                min_cooldown = 0
                max_cooldown = 10000
            max_popularity_limit = cd.get("popularity_force_threshold") or float('inf')
            if isinstance(max_popularity_limit, dict):
                if is_op:
                    max_popularity_limit = max_popularity_limit.get("op") or float('inf')
                else:
                    max_popularity_limit = max_popularity_limit.get("ed") or float('inf')
            if rnd_name in round_options:
                count = variety_mode_cooldown_counts.get(rnd_name, 0)
                if (series_mode_limit and check_recent_history(rnd_name, data)) or count < min_cooldown:
                    round_options = [r for r in round_options if r != rnd_name]
                elif (max_cooldown and count >= max_cooldown) and popularity <= max_popularity_limit:
                    if forced_options:
                        if forced_max_pop_limit == max_popularity_limit:
                            forced_options.append(rnd_name)
                        elif forced_max_pop_limit < max_popularity_limit:
                            continue
                    forced_options = [rnd_name]
                    forced_max_pop_limit = max_popularity_limit

        if forced_options:
            next_round = random.choice(forced_options)
            last_variety_forced = True
            forced = True
        elif not round_options:
            next_round = "regular"
        else:
            random.shuffle(round_options)
            next_round = round_options[0]

        if queue:
            lightning_manager.lightning_queue = [queue, next_round]
            return next_round

    # Update cooldown counters
    for rnd_name in state.playback.lightning_mode_settings:
        if rnd_name == next_round:
            variety_mode_cooldown_counts[rnd_name] = 0
        else:
            variety_mode_cooldown_counts[rnd_name] += 1

    last_round = next_round

    if not testing_variety:
        lightning_manager.unselect_light_modes()
        lightning_manager.toggle_light_mode(next_round, False, False)
        variety_light_mode_enabled = True
    return next_round, forced


# ---------------------------------------------------------------------------
# Per-mode info viability — checks whether a theme has enough metadata for
# a given round type. Used by the variety picker to filter options.
# ---------------------------------------------------------------------------
def has_lightning_mode_info(data, round_type):
    """Returns True if the given round_type has enough info for the file's data."""
    from _app_scripts.queue_round.lightning_rounds import lightning_manager, trivia_round
    if round_type == "clues":
        return len(information_popup.get_tags(data)) >= 3
    elif round_type == "song":
        return information_popup.get_song_string(data, "artist_string") != "N/A"
    elif round_type == "synopsis":
        return len((data.get("synopsis") or "").split()) > 40
    elif round_type == "title":
        return len(title_overlay.get_base_title(data).replace(" ", "")) >= 7
    elif round_type == "characters":
        return len(data.get("characters", [])) >= 4
    elif round_type == "cover":
        return bool(data.get("cover"))
    elif round_type == "image":
        return state.lightning.fixed_lightning_queue or state.lightning.fixed_lightning_round_playlist_data or (state.config.SERPAPI_KEY and not cover_image_overlay.serpapi_limited)
    elif round_type == "tags":
        return len(data.get("tags", [])) >= 10
    elif round_type == "episodes":
        return len(data.get("episode_info", [])) >= 6 and episode_overlay.check_valid_episodes(data)
    elif round_type == "clip":
        return not metadata_display.is_game(data) and not ((streaming.youtube_api_limited or not state.config.YOUTUBE_API_KEY) and not data.get("trailer"))
    elif round_type == "ost":
        return not (streaming.youtube_api_limited or not state.config.YOUTUBE_API_KEY)
    elif round_type == "trivia":
        return data.get("trivia") or (state.config.OPENAI_API_KEY and (int(data.get("season", "9999")[-4:]) <= trivia_round.gpt_cutoff_year or len((data.get("synopsis") or "").split()) > 40))
    elif round_type == "emoji":
        return bool(data.get("emojis")) or state.config.OPENAI_API_KEY
    elif round_type == "names":
        return len(data.get("characters", [])) >= 6
    elif round_type in ["c. reveal", "c. profile", "c. name"]:
        if not data.get("characters"):
            return False
        if round_type == "c. profile":
            return character_parts_overlay.has_char_descriptions(
                data.get("characters"),
                120,
                types=lightning_manager.get_char_types_by_popularity(data, mode="c. profile"),
                anilist_id=data.get("anilist")
            )
        return True
    else:
        return True
