"""Global repeat minimums must survive weighting, boosts and subgroup exhaustion."""

import copy

import pytest

from core.game_state import state
from _app_scripts.playlists import infinite


def _pool(series_count, themes_per_series=1):
    return {
        f"show-{i}-OP{j}.webm": {
            "mal": str(i), "title": f"Show {i}", "series": [f"Series {i}"],
            "slug": f"OP{j}", "popularity": 10, "season": "Fall 2000",
        }
        for i in range(series_count) for j in range(1, themes_per_series + 1)
    }


@pytest.fixture
def selection_state(monkeypatch):
    metadata = {}
    monkeypatch.setattr(state.metadata, "playlist", {
        "playlist": [], "difficulty": 2, "filter": {}, "order": 0,
        "pop_time_order": [(p, t) for p in range(3) for t in range(3)],
    })
    monkeypatch.setattr(state.playback, "check_theme_cache", {})
    monkeypatch.setattr(infinite, "cached_pop_time_group", None)
    monkeypatch.setattr(infinite, "cached_boosted_show_files_map", None)
    monkeypatch.setattr(infinite, "cached_show_files_map", None)
    monkeypatch.setattr(infinite, "series_cooldowns_cache", None)
    monkeypatch.setattr(infinite, "file_cooldowns_cache", None)
    monkeypatch.setattr(infinite, "minimum_cooldowns_cache", (0, 0))
    monkeypatch.setattr(infinite, "cached_skipped_themes", [])
    monkeypatch.setattr(infinite, "total_infinite_files", 0)
    monkeypatch.setattr(infinite.metadata_fetch, "get_metadata",
                        lambda file: metadata.get(file.removeprefix("[L]")))
    monkeypatch.setattr(infinite.metadata_display, "_play_name_key", lambda file: file)
    monkeypatch.setattr(infinite.variety_round, "get_series_popularity",
                        lambda data: data["popularity"])
    monkeypatch.setattr(infinite.playlist_marks, "check_theme", lambda *args: None)
    monkeypatch.setattr(infinite.session_stats, "get_theme_type_counts", lambda files: (len(files), 0, 0, 0))
    monkeypatch.setattr(infinite.session_stats, "get_current_session_lightning_tracks", lambda: set())
    monkeypatch.setattr(infinite, "get_series_boost_multiplier", lambda *args, **kwargs: 1)
    monkeypatch.setattr(infinite, "get_boost_multiplier", lambda season: 1)
    monkeypatch.setattr(infinite.random, "shuffle", lambda values: None)
    return metadata


def _snapshot(metadata, cells, history=(), minimum=(10, 30), difficulty=2):
    groups = [[[], [], []] for _ in range(3)]
    for (p, t), files in cells.items():
        groups[p][t] = list(files)
    candidates = {file for files in cells.values() for file in files}
    shows = {}
    for file, data in metadata.items():
        if file in candidates:
            shows.setdefault(data["mal"], []).append(file)
    settings = copy.deepcopy(infinite.INFINITE_SETTINGS_DEFAULT)
    settings["tag_cooldown"] = 0
    return {
        "groups": groups, "shows_files_map": shows,
        "pop_time_order": [(p, t) for p in range(3) for t in range(3)],
        "next_pop_time_order": [], "playlist_history": list(history),
        "spec_tail": [], "last50": list(history)[-50:],
        "initial_spec_order": -1, "difficulty": difficulty,
        "inf_settings": settings, "light_mode": None, "minimum_cooldowns": minimum,
    }


@pytest.mark.parametrize("series,themes,expected", [
    (1, 1, (0, 0)), (4, 3, (1, 3)), (40, 3, (10, 30)), (400, 5, (20, 50)),
])
def test_minimum_scales_with_pool_and_stops_at_caps(series, themes, expected):
    assert infinite._compute_minimum_cooldowns(
        _pool(series, themes), infinite.INFINITE_SETTINGS_DEFAULT,
    ) == expected


def test_versions_sources_and_sequels_do_not_inflate_counts():
    metadata = _pool(40, 3)
    for filename, data in list(metadata.items()):
        metadata["alternate-" + filename] = dict(data)
    # Extra anime seasons share the existing franchise keys.
    for i in range(40):
        data = dict(metadata[f"show-{i}-OP1.webm"], mal=f"sequel-{i}")
        metadata[f"sequel-{i}.webm"] = data
    assert infinite._compute_minimum_cooldowns(
        metadata, infinite.INFINITE_SETTINGS_DEFAULT,
    ) == (10, 40)


def test_ratios_can_be_disabled_and_partial_settings_use_defaults():
    metadata = _pool(40, 3)
    assert infinite._compute_minimum_cooldowns(metadata, {
        "minimum_cooldown": {"series_ratio": 0},
    }) == (0, 30)
    assert infinite._compute_minimum_cooldowns(metadata, {
        "minimum_cooldown": {"series_ratio": 0, "theme_ratio": 0},
    }) == (0, 0)


@pytest.mark.parametrize("difficulty,count", [(0, 4), (1, 8), (2, 12), (3, 8), (4, 4), (5, 12)])
def test_cached_counts_include_unweighted_themes_and_only_allowed_difficulty(
    selection_state, monkeypatch, difficulty, count,
):
    metadata = selection_state
    metadata.update(_pool(12, 4))
    for data in metadata.values():
        data["popularity"] = (10, 500, 2000)[int(data["mal"]) // 4]
    settings = copy.deepcopy(infinite.INFINITE_SETTINGS_DEFAULT)
    settings["deduplicate_files"] = False
    for group in settings["difficulty_groups"].values():
        group["file_boost_limit"] = 0  # Only one weighted entry, but four playable themes per show.
    state.metadata.playlist.update(difficulty=difficulty, infinite_settings=settings)
    monkeypatch.setattr(infinite, "get_infinite_directory_files", lambda: list(metadata))

    infinite.get_pop_time_groups(refetch=True)

    assert infinite.minimum_cooldowns_cache == (count // 4, count)
    assert infinite._build_spec_snapshot()["minimum_cooldowns"] == (count // 4, count)
    infinite.reset_infinite_caches()
    assert infinite.minimum_cooldowns_cache == (0, 0)


def test_warm_snapshots_do_not_recount_pool_or_fetch_metadata(selection_state, monkeypatch):
    selection_state.update(_pool(100, 3))
    monkeypatch.setattr(infinite, "get_infinite_directory_files", lambda: list(selection_state))
    monkeypatch.setattr(infinite.playlist_ops, "deduplicate_theme_versions",
                        lambda files, **kwargs: files)
    infinite.get_pop_time_groups(refetch=True)

    def unexpected_work(*args, **kwargs):
        pytest.fail("Warm snapshots must reuse cached pool counts and metadata")

    monkeypatch.setattr(infinite, "_compute_minimum_cooldowns", unexpected_work)
    monkeypatch.setattr(infinite.metadata_fetch, "get_metadata", unexpected_work)
    for _ in range(3):
        assert infinite._build_spec_snapshot()["minimum_cooldowns"] == (20, 50)


@pytest.mark.parametrize("difficulty", [2, 5])
def test_recent_popular_show_loses_to_unplayed_candidate(selection_state, monkeypatch, difficulty):
    metadata = selection_state
    metadata.update(_pool(40))
    files = list(metadata)
    cells = {(0, 0): [files[0]] * 20, (1, 0): files[1:]}
    if difficulty == 5:
        cells = {(0, 0): [files[0]] * 20 + files[1:]}
    snap = _snapshot(metadata, cells, [files[0]], difficulty=difficulty)
    original_shows = copy.deepcopy(snap["shows_files_map"])
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (1, 1))

    selected, order = infinite._select_speculative_track(snap)

    assert selected == files[1]
    assert order == 0
    assert snap["shows_files_map"] == original_shows


def test_popular_show_is_allowed_after_minimum_and_keeps_priority(selection_state, monkeypatch):
    metadata = selection_state
    metadata.update(_pool(20))
    files = list(metadata)
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[1]]},
                     [files[0]] + files[2:12], minimum=(10, 10))
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (1, 1))
    assert infinite._select_speculative_track(snap)[0] == files[0]


def test_longer_normal_cooldown_is_preserved(selection_state, monkeypatch):
    metadata = selection_state
    metadata.update(_pool(100))
    files = list(metadata)
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[1]]},
                     [files[0]] + files[2:62], minimum=(20, 50))
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (100, 100))
    assert infinite._select_speculative_track(snap)[0] == files[1]


def test_floor_survives_boosts_and_normal_cooldown_relaxation(selection_state, monkeypatch):
    metadata = selection_state
    metadata.update(_pool(4))
    files = list(metadata)
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[1]]},
                     [files[1], files[2], files[3], files[0]], minimum=(2, 2))
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (100, 100))
    monkeypatch.setattr(infinite, "get_boost_multiplier", lambda season: 20)
    monkeypatch.setattr(infinite, "get_series_boost_multiplier", lambda *args, **kwargs: 20)
    # The older show becomes available as normal cooldowns relax. The more recent
    # show must not bypass the floor during any of those passes.
    assert infinite._select_speculative_track(snap)[0] == files[1]


def test_series_floor_applies_across_sequels_with_theme_floor_disabled(selection_state, monkeypatch):
    metadata = selection_state
    metadata.update(_pool(3))
    files = list(metadata)
    metadata[files[1]]["series"] = metadata[files[0]]["series"]
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[2]]},
                     [files[1]], minimum=(5, 0))
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (0, 0))
    assert infinite._select_speculative_track(snap)[0] == files[2]


def test_theme_floor_applies_across_versions_with_series_floor_disabled(selection_state, monkeypatch):
    metadata = selection_state
    metadata.update(_pool(2))
    files = list(metadata)
    metadata["version2.webm"] = dict(metadata[files[0]])
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[1]]},
                     ["version2.webm"], minimum=(0, 5))
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (0, 0))
    assert infinite._select_speculative_track(snap)[0] == files[1]


def test_wholly_blocked_pool_relaxes_minimum_and_returns_a_track(selection_state, monkeypatch):
    metadata = selection_state
    metadata.update(_pool(2))
    files = list(metadata)
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[1]]},
                     files, minimum=(10, 10))
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (100, 100))
    assert infinite._select_speculative_track(snap)[0] == files[0]


def test_queued_speculative_track_counts_toward_minimum(selection_state, monkeypatch):
    metadata = selection_state
    metadata.update(_pool(3))
    files = list(metadata)
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[1]]}, minimum=(5, 5))
    snap["spec_tail"] = [files[0]]
    snap["playlist_history"] = [files[2], files[0]]  # Snapshot includes queued entries once.
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (1, 1))
    assert infinite._select_speculative_track(snap)[0] == files[1]


@pytest.mark.parametrize("current_session,expected_index", [(False, 0), (True, 1)])
def test_lightning_history_keeps_existing_session_rules(
    selection_state, monkeypatch, current_session, expected_index,
):
    metadata = selection_state
    metadata.update(_pool(2))
    files = list(metadata)
    snap = _snapshot(metadata, {(0, 0): [files[0]], (1, 0): [files[1]]},
                     ["[L]" + files[0]], minimum=(1, 1))
    monkeypatch.setattr(infinite.session_stats, "get_current_session_lightning_tracks",
                        lambda: {files[0]} if current_session else set())
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (0, 0))
    assert infinite._select_speculative_track(snap)[0] == files[expected_index]


def test_applying_settings_invalidates_caches_and_refreshes_queue(monkeypatch):
    from _app_scripts.file import settings_actions

    settings = copy.deepcopy(infinite.INFINITE_SETTINGS_DEFAULT)
    monkeypatch.setattr(state.metadata, "playlist", {"infinite": True, "infinite_settings": settings})
    monkeypatch.setattr(state.settings_presets, "selected_infinite_settings", "")
    calls = []
    monkeypatch.setattr(infinite, "reset_infinite_caches", lambda: calls.append("reset"))
    monkeypatch.setattr(infinite, "refresh_pop_time_groups", lambda: calls.append("refresh"))

    def open_editor(**kwargs):
        kwargs["on_apply_callback"](settings, "Test")

    monkeypatch.setattr(settings_actions.generic_settings_editor, "open_generic_settings_editor", open_editor)
    settings_actions.open_infinite_settings_editor()
    assert calls == ["reset", "refresh"]
    assert state.settings_presets.selected_infinite_settings == "Test"
