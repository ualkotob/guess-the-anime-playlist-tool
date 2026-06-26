"""Infinite-playlist engine: pop-time grouping, cooldown computation, the
speculative-tail pre-pick machinery, difficulty selection, re-roll/refetch, and
the per-track selection used to grow an infinite playlist.

Extracted from playlist.py. This owns the infinite caches and settings. It calls
back into playlist.py (aliased playlist_ops) for the directory/dedup utilities
and shuffle helpers that stay there (get_directory_files,
deduplicate_theme_versions, split_into_three, get_pop_time_order,
_notify_playlist_list_updated), and into filters for filter_playlist; playlist,
filters and several playback modules import this module in turn. All cross-module
references are runtime-only, so the cycles resolve cleanly.
"""
import copy
import random
import threading
import time
from datetime import datetime

import tkinter as tk

from core.game_state import state
from _app_scripts import utils
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.information.information_popup as information_popup
import _app_scripts.file.session_stats as session_stats
import _app_scripts.queue_round.lightning_rounds.variety_round as variety_round
import _app_scripts.queue_round.lightning_rounds.lightning_manager as lightning_manager
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.transport as transport
import _app_scripts.data.config_io as config_io
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.theme.marks as playlist_marks
import _app_scripts.playlists.filters as filters
import _app_scripts.playlists.playlist as playlist_ops

INFINITE_SETTINGS_DEFAULT = {
    "max_history_check": 10000,
    "difficulty_groups": {
        "easy": {"range": [1, 250], "cooldown": [0.5, 0.6], "file_boost_limit": 20},
        "medium": {"range": [251, 1000], "cooldown": [0.75, 0.9], "file_boost_limit": 5},
        "hard": {"range": [1001, float('inf')], "cooldown": [1.0, 1.0], "file_boost_limit": 1},
        "all": {"range": [1, float('inf')], "cooldown": [1.0, 1.5], "file_boost_limit": 1},
    },
    "ending_limit_ratio": 0.5,
    "recent_boost_multiplier": [20, 10, 5],
    "favorites_boost_multiplier": 2,
    "score_boost": {"min_score": 7.5, "multiplier": 1.0},
    "group_series": True,
    "tag_cooldown": 1,
    "include_non_local_files": False,
    "deduplicate_files": True,
    "deduplicate_versions": False,
    "preload_track_count": 5,
}

# Global template settings: used for playlists without stored settings of
# their own, snapshotted into new infinite playlists, and edited in place by
# the infinite settings editor / named-preset load. Deep copy so nested dicts
# (difficulty_groups, score_boost) never alias the immutable defaults.
infinite_settings = copy.deepcopy(INFINITE_SETTINGS_DEFAULT)

difficulty_ranges = [
    ["easy"],
    ["easy", "medium"],
    ["easy", "medium", "hard"],
    ["medium", "hard"],
    ["hard"],
    ["easy", "medium", "hard"],
]

INT_INF = float('inf')
SEASON_ORDER = ["Winter", "Spring", "Summer", "Fall"]

cached_pop_time_group = None
cached_show_files_map = None
cached_boosted_show_files_map = None
cached_pop_time_cooldown = 0
cached_skipped_themes = []
total_infinite_files = 0
series_cooldowns_cache = None
file_cooldowns_cache = None
_refetch_debounce_id = None
_reroll_debounce_id = None


def get_infinite_settings():
    """Get infinite settings from current playlist or fall back to global settings."""
    playlist = state.metadata.playlist
    stored = playlist.get("infinite_settings")
    if stored is None:
        return infinite_settings
    return {**INFINITE_SETTINGS_DEFAULT, **stored}






def get_last_three_seasons():
    now = datetime.now()
    current_season_string = f"{['Winter', 'Spring', 'Summer', 'Fall'][(now.month - 1) // 3]} {now.year}"
    season, year = current_season_string.split()
    year = int(year)
    index = SEASON_ORDER.index(season)

    last_three = []
    for i in range(3):
        cur_index = (index - i) % 4
        year_offset = (index - i) < 0
        cur_year = year - 1 if year_offset else year
        last_three.append(f"{SEASON_ORDER[cur_index]} {cur_year}")

    return last_three


def get_boost_multiplier(season_string):
    for i, s in enumerate(get_last_three_seasons()):
        if s == season_string:
            return get_infinite_settings()["recent_boost_multiplier"][i]
    return 1


def get_series_boost_multiplier(series, cache=None):
    """Return the lowest seasonal boost across a series."""
    if not series:
        return 1
    if isinstance(series, str):
        series = [series]
    series_key = tuple(sorted(series))
    if cache is not None and series_key in cache:
        return cache[series_key]
    series_target = set(series)
    series_boost = 1
    directory_files = state.metadata.directory_files
    for _filename in directory_files:
        _data = metadata_fetch.get_metadata(_filename)
        if not _data:
            continue
        if metadata_display.series_set(_data) & series_target:
            series_boost = min(series_boost, get_boost_multiplier(_data.get("season", "Fall 2000")))
            if series_boost <= 1:
                break
    if cache is not None:
        cache[series_key] = series_boost
    return series_boost


def select_difficulty(event=None):
    playlist = state.metadata.playlist
    difficulty_dropdown = state.playlist_ui.difficulty_dropdown
    value = difficulty_dropdown.get()
    for i, d in enumerate(state.playlist_ui.difficulty_options):
        if d == value:
            playlist["difficulty"] = i
            refresh_pop_time_groups()
    difficulty_dropdown.selection_clear()
    difficulty_dropdown.icursor(tk.END)
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
        value = difficulty_dropdown.get()
        popout_buttons_by_name["DIFFICULTY DROPDOWN"].set(value)
    popout_window._refresh_popout_toggles()
    config_io.save_config()


def _set_difficulty_from_menu(idx):
    """Set infinite playlist difficulty from a menu radiobutton selection."""
    playlist = state.metadata.playlist
    playlist["difficulty"] = idx
    refresh_pop_time_groups()
    try:
        state.playlist_ui.selected_difficulty.set(state.playlist_ui.difficulty_options[idx])
        state.playlist_ui.difficulty_dropdown.selection_clear()
    except Exception:
        pass
    popout_buttons_by_name = state.playback.popout_buttons_by_name
    if popout_buttons_by_name.get("DIFFICULTY DROPDOWN"):
        popout_buttons_by_name["DIFFICULTY DROPDOWN"].set(state.playlist_ui.difficulty_options[idx])
    popout_window._refresh_popout_toggles()
    config_io.save_config()


def _clear_speculative_tail():
    """Cancel downloads for and discard all speculative tail entries."""
    playlist = state.metadata.playlist
    for f in playlist.get("speculative_tail", []):
        clean = entry_paths.get_clean_filename(f)
        if cache_download.is_downloading(clean):
            cache_download.cancel_download(clean)
    playlist["speculative_tail"] = []
    playlist.pop("spec_order", None)


def refresh_pop_time_groups(refetch_next=True):
    playlist = state.metadata.playlist
    get_pop_time_groups(refetch=True)
    transport.update_current_index(save=False)
    if refetch_next and playlist["current_index"] == len(playlist["playlist"]) - 2:
        refetch_next_track()
    elif refetch_next:
        _clear_speculative_tail()
        global _refetch_debounce_id
        if _refetch_debounce_id is not None:
            state.widgets.root.after_cancel(_refetch_debounce_id)
        _refetch_debounce_id = state.widgets.root.after(5000, _start_refetch_prefetch)


def _start_refetch_prefetch():
    global _refetch_debounce_id
    _refetch_debounce_id = None
    playlist = state.metadata.playlist
    if playlist.get("playlist"):
        cn = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(cn):
            cache_download.cancel_download(cn)
    cache_download.prefetch_next_themes()


def refetch_next_track():
    global _refetch_debounce_id
    playlist = state.metadata.playlist

    if playlist.get("playlist"):
        old_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(old_next):
            cache_download.cancel_download(old_next)

    _clear_speculative_tail()

    if _refetch_debounce_id is not None:
        state.widgets.root.after_cancel(_refetch_debounce_id)
        _refetch_debounce_id = None

    playlist["playlist"].pop(len(playlist["playlist"]) - 1)
    get_next_infinite_track(increment=False)

    if playlist.get("playlist"):
        new_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(new_next):
            cache_download.cancel_download(new_next)

    metadata_display.up_next_text()
    state.widgets.root.after(1000, lightning_manager.queue_next_lightning_mode)

    state.widgets.root.after(100, lambda: fill_speculative_tail())

    _refetch_debounce_id = state.widgets.root.after(5000, _start_refetch_prefetch)


def reset_infinite_caches():
    """Clear cached infinite-playlist grouping/cooldown data."""
    global cached_pop_time_group, series_cooldowns_cache, file_cooldowns_cache
    cached_pop_time_group = None
    series_cooldowns_cache = None
    file_cooldowns_cache = None


def get_pop_time_groups(refetch=False):
    global cached_pop_time_group, cached_show_files_map, cached_boosted_show_files_map
    global cached_pop_time_cooldown, cached_skipped_themes, total_infinite_files

    playlist = state.metadata.playlist
    inf_settings = get_infinite_settings()
    playlist_history = playlist["playlist"][-inf_settings.get("max_history_check", 5000):]
    _cold_build = refetch or not cached_pop_time_group
    _t0 = time.monotonic() if _cold_build else None
    if refetch or not cached_pop_time_group:
        group_limits = difficulty_ranges[playlist["difficulty"]]
        sorted_groups = [[] for _ in range(3)]
        cached_skipped_themes = []

        directory_options = (
            filters.filter_playlist(playlist["filter"])
            if playlist.get("filter")
            else playlist_ops.get_directory_files(
                include_non_local=inf_settings.get("include_non_local_files", False),
                deduplicate_files=False, deduplicate_versions=False,
            )
        )

        if inf_settings.get("deduplicate_files", False):
            directory_options = playlist_ops.deduplicate_theme_versions(
                directory_options,
                keep_versions=not inf_settings.get("deduplicate_versions", False),
            )

        total_infinite_files = len(directory_options)
        all_metadata = {f: metadata_fetch.get_metadata(f) for f in directory_options}
        current_session_lightning = session_stats.get_current_session_lightning_tracks()

        playlist_mal_history = []
        for f in playlist_history:
            clean_f = entry_paths.get_clean_filename(f)
            metadata = metadata_fetch.get_metadata(clean_f)
            if metadata and metadata.get("mal"):
                if not f.startswith("[L]") or clean_f in current_session_lightning:
                    playlist_mal_history.append(metadata.get("mal"))

        mal_last_index = {}
        for idx, mal_id in enumerate(playlist_mal_history):
            mal_last_index[mal_id] = idx
        history_len = len(playlist_mal_history)

        playlist_marks.check_theme("", "Favorite Themes")
        check_theme_cache = state.playback.check_theme_cache
        favorited_set = check_theme_cache.get("Favorite Themes", set())

        last_three = get_last_three_seasons()
        recent_boost = inf_settings["recent_boost_multiplier"]
        season_boost_map = {s: recent_boost[i] for i, s in enumerate(last_three)}

        difficulty_groups_list = [
            (k, inf_settings["difficulty_groups"].get(l))
            for k, l in enumerate(group_limits)
        ]
        score_boost_min = inf_settings["score_boost"]["min_score"]
        score_boost_mult = inf_settings["score_boost"]["multiplier"]
        fav_boost = inf_settings["favorites_boost_multiplier"]
        group_series = inf_settings["group_series"]

        shows_files_map = {}
        for f, d in all_metadata.items():
            if not d:
                cached_skipped_themes.append(f)
                continue

            if group_series:
                p = variety_round.get_series_popularity(d)
            else:
                p = d.get("popularity") or INT_INF
            mal = d.get("mal")
            placed = False

            for k, difficulty_group in difficulty_groups_list:
                dg_range = difficulty_group["range"]
                if dg_range[0] <= p <= dg_range[1]:
                    boost = 0
                    if mal not in shows_files_map:
                        boost += (max(0, (d.get("score", 0) or 0) - score_boost_min) % 0.5) * score_boost_mult
                        boost += season_boost_map.get(d.get("season", "Fall 2000"), 1)
                        if mal in mal_last_index:
                            distance_from_end = history_len - 1 - mal_last_index[mal]
                        else:
                            distance_from_end = history_len
                        distance_boost = (distance_from_end // 2000) * (distance_from_end // 2000)
                        boost += distance_boost
                    elif len(shows_files_map[mal]) <= difficulty_group["file_boost_limit"]:
                        boost += 1

                    if fav_boost and f in favorited_set:
                        boost += fav_boost

                    sorted_groups[k].extend([f] * int(boost))
                    shows_files_map.setdefault(mal, []).append(f)
                    placed = True
                    break

            if not placed:
                cached_skipped_themes.append(f)

        if playlist["difficulty"] == 5:
            sorted_groups = [[sorted_groups[0] + sorted_groups[1] + sorted_groups[2], [], []], [[], [], []], [[], [], []]]
        else:
            year_cache = {}
            for entry, meta in all_metadata.items():
                if meta:
                    if meta.get("aired"):
                        season = metadata_fetch.aired_to_season_year(meta.get("aired"), False)
                    else:
                        season = meta.get("season", "9999")[-4:]
                    year_cache[entry] = int(season[-4:])

            def sort_by_year(entries):
                return sorted(entries, key=lambda e: year_cache.get(e.replace("[EXTRA]", ""), 9999), reverse=True)

            for i, g in enumerate(sorted_groups):
                sorted_subgroups = playlist_ops.split_into_three(sort_by_year(g))
                for sublist in sorted_subgroups:
                    random.shuffle(sublist)
                sorted_groups[i] = sorted_subgroups

        cached_pop_time_group = sorted_groups
        cached_show_files_map = shows_files_map

        if playlist["difficulty"] == 5:
            sorted_groups = create_virtual_groups_for_random(sorted_groups)

        compute_cooldowns(sorted_groups, True)

    if refetch or not cached_boosted_show_files_map:
        file_last_index = {}
        for idx, f in enumerate(playlist_history):
            file_last_index[f] = idx
        ph_len = len(playlist_history)
        fav_boost = get_infinite_settings()["favorites_boost_multiplier"]
        playlist_marks.check_theme("", "Favorite Themes")
        check_theme_cache = state.playback.check_theme_cache
        favorited_set = check_theme_cache.get("Favorite Themes", set())

        boosted_show_files_map = {}
        for mal_id, files in cached_show_files_map.items():
            for file in files:
                file_boost = 1
                if file in file_last_index:
                    distance_from_end = ph_len - 1 - file_last_index[file]
                else:
                    distance_from_end = ph_len
                file_boost += (distance_from_end // 2000) * (distance_from_end // 2000)
                if fav_boost and file in favorited_set:
                    file_boost = file_boost * fav_boost
                boosted_show_files_map.setdefault(mal_id, []).extend([file] * int(file_boost))
        cached_pop_time_cooldown = 0
        cached_boosted_show_files_map = boosted_show_files_map

    if _cold_build:
        _dt = time.monotonic() - _t0
        if _dt > 0.5:
            print(f"[get_pop_time_groups] cold build took {_dt:.2f}s "
                  f"(files={total_infinite_files}, refetch={refetch})", flush=True)
    return copy.deepcopy(cached_pop_time_group), copy.deepcopy(cached_boosted_show_files_map)


def next_playlist_order():
    global cached_pop_time_cooldown
    playlist = state.metadata.playlist
    playlist["order"] += 1
    if playlist["order"] >= len(playlist["pop_time_order"]):
        old_len = len(playlist["pop_time_order"])
        playlist["order"] = 0
        playlist["pop_time_order"] = playlist.pop("next_pop_time_order", None) or playlist_ops.get_pop_time_order()
        playlist["next_pop_time_order"] = playlist_ops.get_pop_time_order()
        if "spec_order" in playlist:
            playlist["spec_order"] = max(0, playlist["spec_order"] - old_len)
    cached_pop_time_cooldown += 1
    if cached_pop_time_cooldown > 50:
        def worker():
            get_pop_time_groups(True)
        threading.Thread(target=worker, daemon=True).start()
        cached_pop_time_cooldown = 0


def next_spec_order():
    playlist = state.metadata.playlist
    playlist["spec_order"] = playlist.get("spec_order", playlist["order"]) + 1


def _get_pop_time_entry(order_val):
    playlist = state.metadata.playlist
    pop = playlist["pop_time_order"]
    if order_val < len(pop):
        return pop[order_val]
    nxt = playlist.get("next_pop_time_order", [])
    idx = order_val - len(pop)
    if idx < len(nxt):
        return nxt[idx]
    return pop[order_val % len(pop)]


def get_next_infinite_track(increment=True, speculative=False):
    playlist = state.metadata.playlist
    if not playlist.get("infinite", False):
        return

    if speculative:
        snap = _build_spec_snapshot()
        next_spec_order()
        result, final_spec_order = _select_speculative_track(snap)
        if result and final_spec_order > playlist.get("spec_order", 0):
            playlist["spec_order"] = final_spec_order
        return result

    if increment:
        next_playlist_order()
    inf_settings = get_infinite_settings()
    snap = _build_spec_snapshot()
    snap["initial_spec_order"] = playlist["order"] - 1
    snap["spec_tail"] = []
    hist_limit = inf_settings.get("max_history_check", 5000)
    snap["playlist_history"] = list(playlist["playlist"][-hist_limit:])
    snap["last50"] = list(playlist["playlist"][-50:])

    result, _ = _select_speculative_track(snap)
    if result:
        playlist["playlist"].append(result)
        if playlist["current_index"] == -1:
            transport.update_current_index(0)
        else:
            transport.update_current_index()
        playlist_ops._notify_playlist_list_updated()
        cache_download.prefetch_next_themes()
    return result


def _start_reroll_prefetch():
    """Called 5 s after the last re-roll to download the chosen next track."""
    global _reroll_debounce_id
    _reroll_debounce_id = None
    cache_download.prefetch_next_themes()


def is_reroll_valid():
    """Check if re-roll is currently valid."""
    playlist = state.metadata.playlist
    return (
        playlist.get("infinite", False)
        and playlist["current_index"] == len(playlist["playlist"]) - 2
    )


def reroll_next():
    """Re-roll the next track in infinite mode immediately."""
    global _reroll_debounce_id
    if not is_reroll_valid():
        return

    playlist = state.metadata.playlist

    if playlist["playlist"]:
        old_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(old_next):
            cache_download.cancel_download(old_next)

    if _reroll_debounce_id is not None:
        state.widgets.root.after_cancel(_reroll_debounce_id)
        _reroll_debounce_id = None

    playlist["playlist"].pop()
    get_next_infinite_track(increment=False)
    metadata_display.up_next_text()
    state.widgets.root.after(1000, lightning_manager.queue_next_lightning_mode)

    if playlist["playlist"]:
        new_next = entry_paths.get_clean_filename(playlist["playlist"][-1])
        if cache_download.is_downloading(new_next):
            cache_download.cancel_download(new_next)

    _reroll_debounce_id = state.widgets.root.after(5000, _start_reroll_prefetch)


_spec_pick_running = False


def _build_spec_snapshot():
    """Snapshot all data needed by _select_speculative_track. MUST be called on the main thread."""
    playlist = state.metadata.playlist
    inf_settings = get_infinite_settings()
    groups, shows_files_map = get_pop_time_groups()
    spec_tail = list(playlist.get("speculative_tail", []))
    full_hist = playlist["playlist"] + spec_tail
    hist_limit = inf_settings.get("max_history_check", 5000)
    return {
        "groups": groups,
        "shows_files_map": shows_files_map,
        "spec_tail": spec_tail,
        "playlist_history": list(full_hist[-hist_limit:]),
        "last50": list(playlist["playlist"][-50:]) + spec_tail,
        "initial_spec_order": playlist.get("spec_order", playlist["order"]),
        "pop_time_order": list(playlist["pop_time_order"]),
        "next_pop_time_order": list(playlist.get("next_pop_time_order", [])),
        "difficulty": playlist["difficulty"],
        "inf_settings": inf_settings,
        "light_mode": state.lightning.light_mode,
    }


def _select_speculative_track(snap):
    """Pure selection function — reads only from *snap*, writes nothing global.
    Safe to run in a background thread. Returns (selected_file, final_spec_order).
    """
    inf_settings = snap["inf_settings"]
    groups = snap["groups"]
    shows_files_map = snap["shows_files_map"]
    pop_time_order = snap["pop_time_order"]
    nxt_pop_order = snap["next_pop_time_order"]
    playlist_history = snap["playlist_history"]
    spec_tail = snap["spec_tail"]
    snap_light_mode = snap["light_mode"]
    spec_order = snap["initial_spec_order"] + 1

    def _local_pop_entry(order_val):
        if order_val < len(pop_time_order):
            return pop_time_order[order_val]
        idx = order_val - len(pop_time_order)
        if idx < len(nxt_pop_order):
            return nxt_pop_order[idx]
        return pop_time_order[order_val % max(len(pop_time_order), 1)]

    effective_difficulty_range = difficulty_ranges[snap["difficulty"]]
    _min_s_limit, _min_f_limit = get_cooldown_for_popularity(1, effective_difficulty_range, groups)
    s_limit_mod, f_limit_mod = 1, 1

    p, t = _local_pop_entry(spec_order)
    if p < len(groups) and t < len(groups[p]) and groups[p][t]:
        random.shuffle(groups[p][t])

    selected_file = None
    checked_mal_ids = set()
    try_count = 0
    tag_cooldown_failures = 0
    tag_failed_files = []
    max_tag_tries = min(len(groups[p][t]) // 3, 5) if (p < len(groups) and t < len(groups[p])) else 0
    _hist_entry_cache = {}

    op_count, ed_count = session_stats.get_op_ed_counts(snap["last50"])
    series_boost_cache = {}
    current_session_lightning = session_stats.get_current_session_lightning_tracks()

    recent_tags_union = set()
    if inf_settings.get("tag_cooldown"):
        tag_cooldown_limit = inf_settings["tag_cooldown"]
        for recent_file in (playlist_history + spec_tail)[-tag_cooldown_limit:]:
            recent_tags_union.update(information_popup.get_tags(metadata_fetch.get_metadata(entry_paths.get_clean_filename(recent_file))))

    # --- spec-pick watchdog / hard-stop guard (diagnose + never hang the app) ---
    _iter_count = 0
    _refill_count = 0
    _t_start = time.monotonic()
    _watchdog_next = 5000
    _RELAX_AFTER = 50000     # force-relax all soft constraints to guarantee a pick
    _HARD_CAP = 200000       # absolute bail-out — return None rather than hang
    _force_accept = False

    while not selected_file:
        if p < len(groups) and t < len(groups[p]):
            group_op_count, group_ed_count = session_stats.get_op_ed_counts(groups[p][t])
        else:
            group_op_count, group_ed_count = 0, 0
        if group_ed_count == 0 or (ed_count + op_count) == 0:
            need_op = False
        else:
            need_op = (
                (ed_count / (ed_count + op_count)) > inf_settings["ending_limit_ratio"]
                and (group_op_count / (2 * group_ed_count)) > 0.05
            )

        _iter_count += 1
        if _iter_count >= _watchdog_next:
            _watchdog_next += 5000
            _cell = len(groups[p][t]) if (p < len(groups) and t < len(groups[p])) else -1
            print(f"[spec-pick watchdog] iters={_iter_count} refills={_refill_count} "
                  f"p={p} t={t} cell={_cell} need_op={need_op} "
                  f"s_mod={s_limit_mod:.3f} f_mod={f_limit_mod:.3f} try={try_count} "
                  f"tags={'on' if recent_tags_union else 'off'} "
                  f"elapsed={time.monotonic() - _t_start:.1f}s", flush=True)
        if _iter_count >= _HARD_CAP:
            print(f"[spec-pick] HARD CAP ({_HARD_CAP}) hit after "
                  f"{time.monotonic() - _t_start:.1f}s — returning None to avoid hang", flush=True)
            return None, spec_order
        if _iter_count >= _RELAX_AFTER:
            if not _force_accept:
                _force_accept = True
                print(f"[spec-pick] relaxing all soft constraints after {_iter_count} iters", flush=True)
            need_op = False
            recent_tags_union = set()
            s_limit_mod = 0.0
            f_limit_mod = 0.0

        if p >= len(groups) or t >= len(groups[p]) or not groups[p][t]:
            if try_count > 18:
                return None, spec_order
            spec_order += 1
            p, t = _local_pop_entry(spec_order)
            if p < len(groups) and t < len(groups[p]) and groups[p][t]:
                random.shuffle(groups[p][t])
            max_tag_tries = min(len(groups[p][t]) // 4, 5) if (p < len(groups) and t < len(groups[p])) else 0
            tag_cooldown_failures = 0
            try_count += 1
            continue

        file = groups[p][t].pop(0)
        if file is None:
            try_count += 1
            continue

        extra_file = False
        if "[EXTRA]" in file:
            file = file.replace("[EXTRA]", "")
            extra_file = True
        else:
            selected_mal = metadata_fetch.get_metadata(file).get("mal")

        if extra_file or selected_mal not in checked_mal_ids:
            if extra_file:
                show_files = [file]
            else:
                checked_mal_ids.add(selected_mal)
                show_files = shows_files_map.get(selected_mal, [])
                random.shuffle(show_files)
            checked_files = set()
            while show_files and not selected_file:
                selected_file = show_files.pop(0)
                if selected_file in checked_files:
                    selected_file = None
                    continue
                checked_files.add(selected_file)
                d = metadata_fetch.get_metadata(selected_file)

                if need_op and not utils.is_slug_op(d.get("slug")):
                    selected_file = None
                    continue

                s_pop = variety_round.get_series_popularity(d)
                f_pop = d.get("popularity") or INT_INF
                _base_s_cd, _ = get_cooldown_for_popularity(s_pop, effective_difficulty_range, groups)
                _, _base_f_cd = get_cooldown_for_popularity(f_pop, effective_difficulty_range, groups)
                s_limit = int(_base_s_cd * s_limit_mod)
                f_limit = int(_base_f_cd * f_limit_mod)

                if inf_settings.get("tag_cooldown") and recent_tags_union and tag_cooldown_failures < max_tag_tries:
                    selected_tags = set(information_popup.get_tags(d))
                    if selected_tags & recent_tags_union:
                        tag_failed_files.append(selected_file)
                        selected_file = None
                        tag_cooldown_failures += 1
                        if tag_cooldown_failures >= max_tag_tries:
                            groups[p][t].extend(tag_failed_files)
                            tag_failed_files = []
                    if not selected_file:
                        continue

                if s_limit > 1 or f_limit > 1:
                    series = metadata_display.series_list(d)
                    file_boost = get_boost_multiplier(d.get("season", "Fall 2000"))
                    series_boost = get_series_boost_multiplier(series, cache=series_boost_cache)
                    d_mal = d.get("mal")
                    d_slug = d.get("slug")
                    d_series = set(series)
                    f_break = max(_min_f_limit * f_limit_mod, f_limit / file_boost)
                    s_thresh = max(_min_s_limit * s_limit_mod, s_limit / series_boost)
                    cooldown_count = 0
                    selected_base_f = metadata_display._play_name_key(selected_file)

                    for f in reversed(playlist_history):
                        is_l = f.startswith("[L]")
                        cooldown_count += 0.25 if is_l else 1
                        clean_f = entry_paths.get_clean_filename(f)
                        if not snap_light_mode and is_l and clean_f not in current_session_lightning:
                            continue
                        if cooldown_count >= f_break:
                            break
                        if clean_f not in _hist_entry_cache:
                            f_d = metadata_fetch.get_metadata(clean_f)
                            _hist_entry_cache[clean_f] = (
                                metadata_display._play_name_key(clean_f),
                                f_d.get("mal"),
                                f_d.get("slug"),
                                metadata_display.series_set(f_d),
                            )
                        _base_f, _f_mal, _f_slug, _f_series = _hist_entry_cache[clean_f]
                        if (clean_f == selected_file or _base_f == selected_base_f
                                or (_f_mal == d_mal and _f_slug == d_slug)
                                or (cooldown_count <= s_thresh and bool(d_series & _f_series))):
                            selected_file = None
                            break

        if not groups[p][t]:
            _refill_count += 1
            groups, shows_files_map = get_pop_time_groups()
            if p < len(groups) and t < len(groups[p]) and groups[p][t]:
                random.shuffle(groups[p][t])
                tag_cooldown_failures = 0
            checked_mal_ids = set()
            if recent_tags_union:
                recent_tags_union = set()
            else:
                s_limit_mod = s_limit_mod * 0.9
                f_limit_mod = f_limit_mod * 0.9

    return selected_file, spec_order


def fill_speculative_tail(n=None):
    """Pre-pick up to n speculative tracks beyond the committed next."""
    global _spec_pick_running
    playlist = state.metadata.playlist
    if not playlist.get("infinite", False):
        return
    if n is None:
        n = get_infinite_settings().get("preload_track_count", 3)
    if "speculative_tail" not in playlist:
        playlist["speculative_tail"] = []
    if "next_pop_time_order" not in playlist:
        playlist["next_pop_time_order"] = playlist_ops.get_pop_time_order()
    if "spec_order" not in playlist:
        playlist["spec_order"] = playlist["order"]
    if len(playlist["speculative_tail"]) >= n:
        return
    if _spec_pick_running:
        state.widgets.root.after(30, lambda: fill_speculative_tail(n))
        return

    snap = _build_spec_snapshot()
    next_spec_order()
    _spec_pick_running = True

    def _worker():
        global _spec_pick_running
        try:
            result, final_spec_order = _select_speculative_track(snap)
        except Exception as e:
            print(f"[spec pick thread error] {e}")
            result, final_spec_order = None, snap["initial_spec_order"]

        def _on_main():
            global _spec_pick_running
            _spec_pick_running = False
            if result:
                playlist["speculative_tail"].append(result)
                if final_spec_order > playlist.get("spec_order", 0):
                    playlist["spec_order"] = final_spec_order
            if len(playlist.get("speculative_tail", [])) < n:
                state.widgets.root.after(5, lambda: fill_speculative_tail(n))

        state.widgets.root.after(0, _on_main)

    threading.Thread(target=_worker, daemon=True).start()


def _promote_or_generate_next():
    """Advance infinite playlist by one track."""
    playlist = state.metadata.playlist
    if not playlist.get("infinite", False):
        return
    tail = playlist.get("speculative_tail", [])
    if tail:
        promoted = tail.pop(0)
        next_playlist_order()
        playlist["playlist"].append(promoted)
        if playlist["current_index"] == -1:
            transport.update_current_index(0)
        else:
            transport.update_current_index()
        playlist_ops._notify_playlist_list_updated()
        cache_download.prefetch_next_themes()
        state.widgets.root.after(50, lambda: fill_speculative_tail())
    else:
        _threaded_generate_next()
        playlist.pop("spec_order", None)
        state.widgets.root.after(50, lambda: fill_speculative_tail())


def _threaded_generate_next():
    """Run a non-speculative infinite pick in a background thread."""
    playlist = state.metadata.playlist
    next_playlist_order()
    snap = _build_spec_snapshot()
    snap["initial_spec_order"] = playlist["order"] - 1

    def _worker():
        try:
            result, _ = _select_speculative_track(snap)
        except Exception as e:
            print(f"[threaded generate next error] {e}")
            result = None

        def _apply():
            if result:
                playlist["playlist"].append(result)
                if playlist["current_index"] == -1:
                    transport.update_current_index(0)
                else:
                    transport.update_current_index()
                playlist_ops._notify_playlist_list_updated()
                cache_download.prefetch_next_themes()
            else:
                get_next_infinite_track()

        state.widgets.root.after(0, _apply)

    threading.Thread(target=_worker, daemon=True).start()


def get_cooldown_for_popularity(popularity_rank, difficulty_range, groups):
    """Calculate cooldowns using computed values with smooth interpolation."""
    if not series_cooldowns_cache or not file_cooldowns_cache:
        return 84, 385

    if len(series_cooldowns_cache) == 1:
        return int(series_cooldowns_cache[0]), int(file_cooldowns_cache[0])
    elif len(series_cooldowns_cache) == 2:
        group1_series, group2_series = series_cooldowns_cache
        group1_file, group2_file = file_cooldowns_cache

        if difficulty_range == ["easy", "medium"]:
            easy_series, medium_series, hard_series = group1_series, group2_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group2_file, group2_file
        elif difficulty_range == ["medium", "hard"]:
            easy_series, medium_series, hard_series = group1_series, group1_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group1_file, group2_file
        else:
            easy_series, medium_series, hard_series = group1_series, group1_series, group2_series
            easy_file, medium_file, hard_file = group1_file, group1_file, group2_file
    else:
        easy_series, medium_series, hard_series = series_cooldowns_cache
        easy_file, medium_file, hard_file = file_cooldowns_cache

    if popularity_rank <= 50:
        series_cooldown = easy_series
        file_cooldown = easy_file
    elif popularity_rank <= 250:
        progress = (popularity_rank - 50) / 200
        series_cooldown = easy_series + (progress * (medium_series - easy_series))
        file_cooldown = easy_file + (progress * (medium_file - easy_file))
    elif popularity_rank <= 1000:
        progress = (popularity_rank - 250) / 750
        series_cooldown = medium_series + (progress * (hard_series - medium_series))
        file_cooldown = medium_file + (progress * (hard_file - medium_file))
    else:
        inf_settings = get_infinite_settings()
        max_rank_for_scaling = inf_settings.get("max_history_check", 10000)
        capped_rank = min(popularity_rank, max_rank_for_scaling)
        progress = (capped_rank - 1000) / max(max_rank_for_scaling - 1000, 1)
        file_cooldown = hard_file + (progress * (inf_settings.get("max_history_check", 10000) - hard_file))
        if hard_file > 0:
            series_to_file_ratio = hard_series / hard_file
        else:
            series_to_file_ratio = 1
        series_cooldown = file_cooldown * series_to_file_ratio

    return int(series_cooldown), int(file_cooldown)


def create_virtual_groups_for_random(sorted_groups):
    """Create virtual groups for random mode by redistributing files by popularity ranges."""
    all_files_flat = []
    for group in sorted_groups:
        for subgroup in group:
            all_files_flat.extend(subgroup)

    virtual_groups = [[], [], []]
    for file in all_files_flat:
        clean_file = file.replace("[EXTRA]", "")
        metadata = metadata_fetch.get_metadata(clean_file)
        popularity = metadata.get("popularity") or float('inf')

        if popularity <= 250:
            virtual_groups[0].append(file)
        elif popularity <= 1000:
            virtual_groups[1].append(file)
        else:
            virtual_groups[2].append(file)

    structured_virtual_groups = []
    for i, virtual_group in enumerate(virtual_groups):
        def get_year(entry):
            meta = metadata_fetch.get_metadata(entry.replace("[EXTRA]", ""))
            if meta and meta.get("aired"):
                season = metadata_fetch.aired_to_season_year(meta.get("aired"), False)
            else:
                season = meta.get("season", "9999")[-4:] if meta else "9999"
            return int(season[-4:])

        sorted_virtual_group = sorted(virtual_group, key=get_year, reverse=True)
        virtual_subgroups = playlist_ops.split_into_three(sorted_virtual_group)

        for sublist in virtual_subgroups:
            random.shuffle(sublist)

        structured_virtual_groups.append(virtual_subgroups)

    return structured_virtual_groups


def compute_cooldowns(groups, refetch=False):
    global series_cooldowns_cache, file_cooldowns_cache
    playlist = state.metadata.playlist
    if not series_cooldowns_cache or refetch:
        series_cooldowns = []
        file_cooldowns = []

        inf_settings = get_infinite_settings()
        difficulty_range = difficulty_ranges[playlist["difficulty"]]

        for i, group in enumerate(groups):
            if i >= len(difficulty_range):
                continue
            difficulty_group = inf_settings["difficulty_groups"][difficulty_range[i]]
            all_files = [f for subgroup in group for f in subgroup]
            unique_files = set(f.replace("[EXTRA]", "") for f in all_files)
            file_count = len(unique_files)
            unique_series = set(metadata_display.series_cache_key(metadata_fetch.get_metadata(f.replace("[EXTRA]", ""))) for f in all_files)
            series_count = len(unique_series)

            base_s_cd = series_count
            base_f_cd = file_count

            s_cd = int(base_s_cd * difficulty_group["cooldown"][0])
            f_cd = int(base_f_cd * difficulty_group["cooldown"][1])

            series_cooldowns.append(s_cd)
            file_cooldowns.append(f_cd)

        series_cooldowns_cache, file_cooldowns_cache = series_cooldowns, file_cooldowns
    return series_cooldowns_cache, file_cooldowns_cache
