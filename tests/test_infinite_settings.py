"""Tests for the pure/settings logic in _app_scripts/playlists/infinite.py.

Importing `infinite` pulls in a large module cluster, but none of it runs UI
or playback at import time; these tests only exercise pure functions and the
settings-resolution logic against `core.game_state`.
"""

from datetime import datetime

import pytest

import _app_scripts.playlists.infinite as infinite
from core.game_state import state


@pytest.fixture
def clean_playlist():
    """Mutate state.metadata.playlist freely; restore it after the test."""
    saved = dict(state.metadata.playlist)
    yield state.metadata.playlist
    state.metadata.playlist.clear()
    state.metadata.playlist.update(saved)


# ---------------------------------------------------------------------------
# Settings resolution
# ---------------------------------------------------------------------------

class TestInfiniteSettings:
    def test_template_does_not_alias_defaults(self):
        # Regression: the template was a shallow .copy(), so editing nested
        # dicts in place corrupted INFINITE_SETTINGS_DEFAULT.
        assert infinite.infinite_settings is not infinite.INFINITE_SETTINGS_DEFAULT
        for key, value in infinite.INFINITE_SETTINGS_DEFAULT.items():
            if isinstance(value, (dict, list)):
                assert infinite.infinite_settings[key] is not value, key

    def test_template_matches_defaults_initially(self):
        assert infinite.infinite_settings == infinite.INFINITE_SETTINGS_DEFAULT

    def test_no_stored_settings_returns_template(self, clean_playlist):
        clean_playlist.pop("infinite_settings", None)
        assert infinite.get_infinite_settings() is infinite.infinite_settings

    def test_stored_settings_win_over_defaults(self, clean_playlist):
        clean_playlist["infinite_settings"] = {"tag_cooldown": 99}
        settings = infinite.get_infinite_settings()
        assert settings["tag_cooldown"] == 99
        # Missing keys come from the defaults
        assert settings["group_series"] == infinite.INFINITE_SETTINGS_DEFAULT["group_series"]

    def test_merged_settings_are_not_the_stored_dict(self, clean_playlist):
        stored = {"tag_cooldown": 99}
        clean_playlist["infinite_settings"] = stored
        assert infinite.get_infinite_settings() is not stored


# ---------------------------------------------------------------------------
# Season helpers
# ---------------------------------------------------------------------------

class TestSeasons:
    def test_last_three_seasons_shape(self):
        seasons = infinite.get_last_three_seasons()
        assert len(seasons) == 3
        assert len(set(seasons)) == 3
        for s in seasons:
            name, year = s.split()
            assert name in infinite.SEASON_ORDER
            assert year.isdigit()

    def test_first_entry_is_current_season(self):
        now = datetime.now()
        expected = f"{infinite.SEASON_ORDER[(now.month - 1) // 3]} {now.year}"
        assert infinite.get_last_three_seasons()[0] == expected

    def test_seasons_descend_consecutively(self):
        seasons = infinite.get_last_three_seasons()
        for newer, older in zip(seasons, seasons[1:]):
            n_name, n_year = newer.split()
            o_name, o_year = older.split()
            n_idx = infinite.SEASON_ORDER.index(n_name)
            o_idx = infinite.SEASON_ORDER.index(o_name)
            # The older season is exactly one step back in the cycle.
            assert (o_idx + 1) % 4 == n_idx
            if n_idx == 0:  # Winter rolls back to previous year's Fall
                assert int(o_year) == int(n_year) - 1
            else:
                assert o_year == n_year

    def test_boost_multiplier_by_recency(self, monkeypatch, clean_playlist):
        clean_playlist.pop("infinite_settings", None)
        monkeypatch.setattr(
            infinite, "get_last_three_seasons",
            lambda: ["Spring 2026", "Winter 2026", "Fall 2025"],
        )
        expected = infinite.INFINITE_SETTINGS_DEFAULT["recent_boost_multiplier"]
        assert infinite.get_boost_multiplier("Spring 2026") == expected[0]
        assert infinite.get_boost_multiplier("Winter 2026") == expected[1]
        assert infinite.get_boost_multiplier("Fall 2025") == expected[2]
        assert infinite.get_boost_multiplier("Summer 2010") == 1


# ---------------------------------------------------------------------------
# Cooldown interpolation
# ---------------------------------------------------------------------------

class TestCooldownForPopularity:
    @pytest.fixture
    def cooldown_caches(self, monkeypatch):
        """Install known 3-group cooldown caches: easy/medium/hard."""
        monkeypatch.setattr(infinite, "series_cooldowns_cache", [100, 200, 400])
        monkeypatch.setattr(infinite, "file_cooldowns_cache", [1000, 2000, 4000])

    def test_empty_caches_fall_back(self, monkeypatch):
        monkeypatch.setattr(infinite, "series_cooldowns_cache", None)
        monkeypatch.setattr(infinite, "file_cooldowns_cache", None)
        assert infinite.get_cooldown_for_popularity(1, ["easy"], None) == (84, 385)

    def test_top_ranks_use_easy_cooldowns(self, cooldown_caches):
        assert infinite.get_cooldown_for_popularity(1, None, None) == (100, 1000)
        assert infinite.get_cooldown_for_popularity(50, None, None) == (100, 1000)

    def test_easy_to_medium_interpolation(self, cooldown_caches):
        # Midpoint of the 50..250 band: halfway easy -> medium.
        series, file = infinite.get_cooldown_for_popularity(150, None, None)
        assert series == 150
        assert file == 1500

    def test_band_boundaries_are_continuous(self, cooldown_caches):
        assert infinite.get_cooldown_for_popularity(250, None, None) == (200, 2000)
        assert infinite.get_cooldown_for_popularity(1000, None, None) == (400, 4000)

    def test_medium_to_hard_interpolation(self, cooldown_caches):
        series, file = infinite.get_cooldown_for_popularity(625, None, None)
        assert series == 300
        assert file == 3000

    def test_single_group_cache(self, monkeypatch):
        monkeypatch.setattr(infinite, "series_cooldowns_cache", [123])
        monkeypatch.setattr(infinite, "file_cooldowns_cache", [456])
        assert infinite.get_cooldown_for_popularity(5000, None, None) == (123, 456)

    def test_beyond_hard_scales_toward_max_history(self, cooldown_caches, clean_playlist):
        clean_playlist.pop("infinite_settings", None)
        max_check = infinite.get_infinite_settings()["max_history_check"]
        series, file = infinite.get_cooldown_for_popularity(max_check, None, None)
        # At the cap the file cooldown reaches max_history_check itself,
        # and series keeps the hard-band series:file ratio (400:4000 = 0.1).
        assert file == max_check
        assert series == int(max_check * 0.1)
