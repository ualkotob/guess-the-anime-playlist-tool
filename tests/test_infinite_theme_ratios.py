"""Insert limits share the ending limit's history, availability and fallback rules."""

import copy

import pytest

from _app_scripts.playlists import infinite

session_stats = infinite.session_stats


@pytest.fixture
def theme_picker(monkeypatch):
    metadata = {
        "insert-IN1.webm": {"mal": "insert", "slug": "IN1"},
        "opening-OP1.webm": {"mal": "opening", "slug": "OP1"},
        "ending-ED1.webm": {"mal": "ending", "slug": "ED1"},
        "other-SP1.webm": {"mal": "other", "slug": "SP1"},
    }
    monkeypatch.setattr(infinite.metadata_fetch, "get_file_metadata_by_name",
                        lambda file: metadata.get(file.removeprefix("[L]")))
    monkeypatch.setattr(infinite.metadata_fetch, "get_metadata",
                        lambda file: metadata.get(file.removeprefix("[L]")))
    monkeypatch.setattr(infinite, "get_cooldown_for_popularity", lambda *args: (0, 0))
    monkeypatch.setattr(infinite.variety_round, "get_series_popularity", lambda data: 1)
    monkeypatch.setattr(infinite.session_stats, "get_current_session_lightning_tracks", lambda: set())
    monkeypatch.setattr(infinite.random, "shuffle", lambda files: None)

    def make_snapshot(history, candidates, *, insert_ratio=0.1, ending_ratio=0.5, tail=()):
        settings = copy.deepcopy(infinite.INFINITE_SETTINGS_DEFAULT)
        settings.update(insert_limit_ratio=insert_ratio, ending_limit_ratio=ending_ratio, tag_cooldown=0)
        return {
            "groups": [[list(candidates), [], []], [[], [], []], [[], [], []]],
            "shows_files_map": {metadata[file]["mal"]: [file] for file in candidates},
            "pop_time_order": [(0, 0)], "next_pop_time_order": [],
            "playlist_history": list(history) + list(tail),
            "last50": list(history)[-50:] + list(tail), "spec_tail": list(tail),
            "initial_spec_order": -1, "difficulty": 5, "light_mode": None,
            "inf_settings": settings, "minimum_cooldowns": (0, 0),
        }

    return make_snapshot


INSERT = "insert-IN1.webm"
OPENING = "opening-OP1.webm"
ENDING = "ending-ED1.webm"
OTHER = "other-SP1.webm"


def test_counter_separates_inserts_and_preserves_legacy_session_counts(theme_picker):
    themes = [OPENING, ENDING, INSERT, OTHER, None]
    assert session_stats.get_theme_type_counts(themes) == (1, 1, 1, 1)
    assert session_stats.get_op_ed_counts(themes) == (1, 3)


def test_counter_uses_metadata_for_shared_filenames(theme_picker, monkeypatch):
    monkeypatch.setattr(infinite.metadata_fetch, "get_file_metadata_by_name",
                        lambda file: {"slug": "IN2"})
    assert session_stats.get_theme_type_counts(["shared-video.webm"]) == (0, 0, 1, 0)


def test_counter_can_fall_back_to_filename_slugs(theme_picker, monkeypatch):
    monkeypatch.setattr(infinite.metadata_fetch, "get_file_metadata_by_name", lambda file: None)
    assert session_stats.get_theme_type_counts([
        "Show-OP1.webm", "Show-ED2v2.webm", "[L]Show-IN3.webm", "Show-SP1.webm",
        "unrecognized.webm", None,
    ]) == (1, 1, 1, 1)


@pytest.mark.parametrize("difficulty", [0, 1, 2, 3, 4, 5])
def test_default_insert_limit_selects_non_insert_when_over_ten_percent(theme_picker, difficulty):
    snap = theme_picker([INSERT] * 3 + [OPENING] * 17, [INSERT, OPENING])
    snap["difficulty"] = difficulty
    assert infinite._select_speculative_track(snap)[0] == OPENING


def test_insert_ratio_allows_inserts_below_limit(theme_picker):
    snap = theme_picker([INSERT] + [OPENING] * 19, [INSERT, OPENING])
    assert infinite._select_speculative_track(snap)[0] == INSERT


def test_insert_ratio_uses_same_threshold_boundary_as_ending_ratio(theme_picker):
    # Both existing ratio rules act when the current share is above the limit.
    snap = theme_picker([INSERT] + [OPENING] * 9, [INSERT, OPENING])
    assert infinite._select_speculative_track(snap)[0] == INSERT
    snap = theme_picker([ENDING] + [OPENING] * 9, [ENDING, OPENING], ending_ratio=0.1)
    assert infinite._select_speculative_track(snap)[0] == ENDING


@pytest.mark.parametrize("ratio", [0.25, 1.0])
def test_custom_ratio_and_disable_value_are_respected(theme_picker, ratio):
    snap = theme_picker([INSERT] * 4 + [OPENING] * 16, [INSERT, OPENING], insert_ratio=ratio)
    assert infinite._select_speculative_track(snap)[0] == INSERT


def test_old_playlist_settings_receive_ten_percent_default(theme_picker):
    snap = theme_picker([INSERT] * 3 + [OPENING] * 17, [INSERT, OPENING])
    snap["inf_settings"].pop("insert_limit_ratio")
    assert infinite._select_speculative_track(snap)[0] == OPENING


def test_an_ending_can_satisfy_the_non_insert_requirement(theme_picker):
    snap = theme_picker([INSERT] * 3 + [OPENING] * 17, [INSERT, ENDING])
    assert infinite._select_speculative_track(snap)[0] == ENDING


def test_other_themes_are_included_in_the_insert_denominator(theme_picker):
    snap = theme_picker([INSERT] + [OTHER] * 19, [INSERT, OTHER])
    assert infinite._select_speculative_track(snap)[0] == INSERT


def test_inserts_do_not_count_as_endings(theme_picker):
    snap = theme_picker([INSERT] * 10 + [OPENING] * 10, [INSERT, ENDING, OPENING], ending_ratio=0.1)
    assert infinite._select_speculative_track(snap)[0] == ENDING


def test_both_ratio_limits_can_apply_together(theme_picker):
    snap = theme_picker([INSERT] * 10 + [ENDING] * 30 + [OPENING] * 10,
                       [INSERT, ENDING, OPENING])
    assert infinite._select_speculative_track(snap)[0] == OPENING


def test_recent_history_window_and_queued_tracks_match_ending_ratio(theme_picker):
    # Old inserts outside the last 50 do not contribute.
    snap = theme_picker([INSERT] * 50 + [OPENING] * 50, [INSERT, OPENING])
    assert infinite._select_speculative_track(snap)[0] == INSERT
    # Already queued inserts contribute exactly once, like queued endings.
    snap = theme_picker([OPENING] * 50, [INSERT, OPENING], tail=[INSERT] * 6)
    assert infinite._select_speculative_track(snap)[0] == OPENING


def test_empty_history_allows_an_initial_insert(theme_picker):
    snap = theme_picker([], [INSERT, OPENING])
    assert infinite._select_speculative_track(snap)[0] == INSERT


@pytest.mark.parametrize("candidates", [[INSERT], [INSERT] * 20 + [OPENING]])
def test_insert_only_or_overwhelmingly_insert_groups_stay_playable(theme_picker, candidates):
    snap = theme_picker([INSERT] * 20, candidates)
    assert infinite._select_speculative_track(snap)[0] == INSERT


def test_candidate_group_is_counted_once_despite_multiple_rejections(theme_picker, monkeypatch):
    # Distinct anime are needed because selection checks each anime only once.
    metadata = {f"show{i}-IN1.webm": {"mal": str(i), "slug": "IN1"} for i in range(5)}
    metadata[OPENING] = {"mal": "op", "slug": "OP1"}
    metadata[INSERT] = {"mal": "history", "slug": "IN1"}
    monkeypatch.setattr(infinite.metadata_fetch, "get_metadata", metadata.get)
    monkeypatch.setattr(infinite.metadata_fetch, "get_file_metadata_by_name", metadata.get)
    candidates = list(metadata)[:6]
    snap = theme_picker([INSERT] * 10, [INSERT, OPENING])
    snap["groups"][0][0] = candidates
    snap["shows_files_map"] = {metadata[file]["mal"]: [file] for file in candidates}
    real_counter = session_stats.get_theme_type_counts
    calls = []

    def count(files):
        calls.append(tuple(files))
        return real_counter(files)

    monkeypatch.setattr(infinite.session_stats, "get_theme_type_counts", count)
    assert infinite._select_speculative_track(snap)[0] == OPENING
    assert len(calls) == 2  # One history scan and one candidate-cell scan.
