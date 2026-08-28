"""Tests for the pure helpers in _app_scripts/utils.py."""

import copy
import gzip
import json
import os

import pytest

from _app_scripts import utils


# ---------------------------------------------------------------------------
# JSON infinity serialization
# ---------------------------------------------------------------------------

class TestInfinityMarkers:
    def test_roundtrip_nested(self):
        original = {
            "a": float("inf"),
            "b": float("-inf"),
            "c": [1, float("inf"), {"d": float("-inf")}],
            "e": 1.5,
            "f": "plain",
        }
        markers = utils.convert_infinities_to_markers(original)
        # Result must be JSON-serializable without infinities
        json.dumps(markers)
        assert markers["a"] == "__INFINITY__"
        assert markers["b"] == "__NEG_INFINITY__"
        restored = utils.convert_infinity_markers(markers)
        assert restored == original

    def test_legacy_inf_strings(self):
        assert utils.convert_infinity_markers("inf") == float("inf")
        assert utils.convert_infinity_markers("-inf") == float("-inf")

    def test_ordinary_values_untouched(self):
        assert utils.convert_infinities_to_markers(42) == 42
        assert utils.convert_infinities_to_markers("inf") == "inf"  # only floats convert
        assert utils.convert_infinity_markers({"x": "information"}) == {"x": "information"}

    def test_does_not_mutate_input(self):
        original = {"range": [1, float("inf")]}
        snapshot = copy.deepcopy(original)
        utils.convert_infinities_to_markers(original)
        assert original == snapshot


# ---------------------------------------------------------------------------
# deep_merge / merge_songs_by_slug
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_nested_dict_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        utils.deep_merge(base, {"a": {"y": 20, "z": 30}, "c": 4})
        assert base == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3, "c": 4}

    def test_override_replaces_non_dict(self):
        base = {"a": {"x": 1}}
        utils.deep_merge(base, {"a": 5})
        assert base == {"a": 5}

    def test_songs_lists_merge_by_slug(self):
        base = {"songs": [{"slug": "OP1", "title": "old", "artist": "A"}]}
        override = {"songs": [{"slug": "OP1", "title": "new"}, {"slug": "ED1", "title": "ed"}]}
        utils.deep_merge(base, override)
        assert base["songs"][0] == {"slug": "OP1", "title": "new", "artist": "A"}
        assert base["songs"][1] == {"slug": "ED1", "title": "ed"}

    def test_non_songs_lists_replaced(self):
        base = {"tags": [1, 2]}
        utils.deep_merge(base, {"tags": [3]})
        assert base["tags"] == [3]

    def test_songs_without_slug_skipped(self):
        base = [{"slug": "OP1", "v": 1}]
        utils.merge_songs_by_slug(base, [{"v": 2}])
        assert base == [{"slug": "OP1", "v": 1}]


# ---------------------------------------------------------------------------
# sync_with_default / fill_missing_defaults
# ---------------------------------------------------------------------------

DEFAULTS = {
    "scalar": 1,
    "nested": {"a": 1.0, "b": {"deep": True}},
    "listy": [1, 2],
}


class TestSyncWithDefault:
    def test_removes_unknown_keys(self):
        saved = {"scalar": 5, "stale": 9}
        utils.sync_with_default(saved, DEFAULTS)
        assert "stale" not in saved
        assert saved["scalar"] == 5

    def test_adds_missing_keys(self):
        saved = {}
        utils.sync_with_default(saved, DEFAULTS)
        assert saved == DEFAULTS

    def test_added_keys_do_not_alias_default(self):
        # Regression: missing keys must be deep-copied, otherwise editing the
        # synced dict in place would corrupt the shared defaults.
        saved = {}
        utils.sync_with_default(saved, DEFAULTS)
        assert saved["nested"] is not DEFAULTS["nested"]
        assert saved["nested"]["b"] is not DEFAULTS["nested"]["b"]
        assert saved["listy"] is not DEFAULTS["listy"]
        saved["nested"]["b"]["deep"] = False
        assert DEFAULTS["nested"]["b"]["deep"] is True

    def test_type_mismatch_replaced(self):
        saved = {"scalar": "not an int"}
        utils.sync_with_default(saved, DEFAULTS)
        assert saved["scalar"] == 1

    def test_recurses_into_nested(self):
        saved = {"nested": {"a": 2.5}}
        utils.sync_with_default(saved, DEFAULTS)
        assert saved["nested"]["a"] == 2.5
        assert saved["nested"]["b"] == {"deep": True}


class TestFillMissingDefaults:
    def test_fills_missing_only(self):
        target = {"scalar": 99}
        utils.fill_missing_defaults(target, DEFAULTS)
        assert target["scalar"] == 99
        assert target["nested"] == DEFAULTS["nested"]

    def test_keeps_extra_keys(self):
        target = {"extra": "kept"}
        utils.fill_missing_defaults(target, DEFAULTS)
        assert target["extra"] == "kept"

    def test_keeps_type_mismatches(self):
        # Unlike sync_with_default: a float where the default has an int
        # is a legitimate user value, not corruption.
        target = {"scalar": 0.5}
        utils.fill_missing_defaults(target, DEFAULTS)
        assert target["scalar"] == 0.5

    def test_no_aliasing_of_default(self):
        target = {}
        utils.fill_missing_defaults(target, DEFAULTS)
        assert target["nested"] is not DEFAULTS["nested"]
        target["nested"]["b"]["deep"] = False
        assert DEFAULTS["nested"]["b"]["deep"] is True

    def test_recurses_into_partial_nested(self):
        target = {"nested": {"a": 7.0}}
        utils.fill_missing_defaults(target, DEFAULTS)
        assert target["nested"] == {"a": 7.0, "b": {"deep": True}}

    def test_returns_target(self):
        target = {}
        assert utils.fill_missing_defaults(target, DEFAULTS) is target


# ---------------------------------------------------------------------------
# compute_settings_diff
# ---------------------------------------------------------------------------

class TestComputeSettingsDiff:
    def test_identical_returns_none(self):
        assert utils.compute_settings_diff(DEFAULTS, copy.deepcopy(DEFAULTS)) is None

    def test_scalar_diff(self):
        saved = copy.deepcopy(DEFAULTS)
        saved["scalar"] = 5
        assert utils.compute_settings_diff(DEFAULTS, saved) == {"scalar": 5}

    def test_nested_diff_only_contains_changes(self):
        saved = copy.deepcopy(DEFAULTS)
        saved["nested"]["a"] = 9.0
        assert utils.compute_settings_diff(DEFAULTS, saved) == {"nested": {"a": 9.0}}

    def test_unknown_keys_kept(self):
        saved = {"brand_new": 1}
        assert utils.compute_settings_diff(DEFAULTS, saved) == {"brand_new": 1}

    def test_diff_then_merge_roundtrip(self):
        # The persistence contract: defaults + saved diff == original settings.
        saved = copy.deepcopy(DEFAULTS)
        saved["scalar"] = 7
        saved["nested"]["b"]["deep"] = False
        diff = utils.compute_settings_diff(DEFAULTS, saved)
        rebuilt = copy.deepcopy(DEFAULTS)
        utils.deep_merge(rebuilt, diff)
        assert rebuilt == saved


# ---------------------------------------------------------------------------
# Theme flag migration
# ---------------------------------------------------------------------------

class TestMigrateThemeFlags:
    def test_renames_legacy_flags(self):
        f = {"themes_exclude": ["OVERLAP", "other"], "themes_include": ["SPOILER"]}
        utils._migrate_theme_flags(f)
        assert f["themes_exclude"] == ["OVERLAP (Without Censors)", "other"]
        assert f["themes_include"] == ["SPOILER (Without Censors)"]

    def test_ignores_non_dict(self):
        utils._migrate_theme_flags(None)  # must not raise

    def test_ignores_missing_keys(self):
        f = {}
        utils._migrate_theme_flags(f)
        assert f == {}


# ---------------------------------------------------------------------------
# Atomic / compressed file I/O
# ---------------------------------------------------------------------------

class TestAtomicJsonWrite:
    def test_writes_json(self, tmp_path):
        path = str(tmp_path / "out.json")
        utils._atomic_json_write(path, {"a": 1})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"a": 1}
        assert not os.path.exists(path + ".tmp")

    def test_failure_preserves_original_and_cleans_tmp(self, tmp_path):
        path = str(tmp_path / "out.json")
        utils._atomic_json_write(path, {"a": 1})
        with pytest.raises(TypeError):
            utils._atomic_json_write(path, {"bad": object()})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"a": 1}
        assert not os.path.exists(path + ".tmp")


class TestCompressedMetadata:
    def test_save_and_load_compressed(self, tmp_path):
        path = str(tmp_path / "meta" / "data.json")
        utils.save_metadata_compressed(path, {"k": "v"})
        # Only the .gz is written when no readable file pre-exists
        assert os.path.exists(path + ".gz")
        assert not os.path.exists(path)
        data, was_compressed = utils.load_metadata_compressed(path)
        assert data == {"k": "v"}
        assert was_compressed is True

    def test_readable_file_kept_in_sync_when_present(self, tmp_path):
        path = str(tmp_path / "data.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"old": True}, f)
        utils.save_metadata_compressed(path, {"new": True})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"new": True}

    def test_load_falls_back_to_plain_json(self, tmp_path):
        path = str(tmp_path / "data.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"plain": 1}, f)
        data, was_compressed = utils.load_metadata_compressed(path)
        assert data == {"plain": 1}
        assert was_compressed is False

    def test_corrupt_gz_falls_back_to_plain(self, tmp_path):
        path = str(tmp_path / "data.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"plain": 1}, f)
        with open(path + ".gz", "wb") as f:
            f.write(b"not gzip data")
        data, was_compressed = utils.load_metadata_compressed(path)
        assert data == {"plain": 1}
        assert was_compressed is False

    def test_missing_returns_none(self, tmp_path):
        data, was_compressed = utils.load_metadata_compressed(str(tmp_path / "nope.json"))
        assert data is None
        assert was_compressed is False


# ---------------------------------------------------------------------------
# Misc pure helpers
# ---------------------------------------------------------------------------

class TestMiscHelpers:
    def test_format_seconds(self):
        assert utils.format_seconds(0) == "00:00"
        assert utils.format_seconds(61) == "01:01"
        assert utils.format_seconds(3599) == "59:59"

    def test_split_array_even(self):
        assert utils.split_array([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_split_array_uneven_preserves_all_elements(self):
        arr = list(range(10))
        parts = utils.split_array(arr, 3)
        assert len(parts) == 3
        assert [x for part in parts for x in part] == arr

    def test_split_array_invalid_parts(self):
        with pytest.raises(ValueError):
            utils.split_array([1], 0)

    def test_format_slug(self):
        assert utils.format_slug("OP1") == "Opening 1"
        assert utils.format_slug("ED2") == "Ending 2"
        assert utils.format_slug("Special") == "Special"

    def test_is_slug_op(self):
        assert utils.is_slug_op("OP1") is True
        assert utils.is_slug_op("ED1") is False

    def test_season_to_tuple(self):
        assert utils._season_to_tuple("Fall 2020") == (2020, 3)
        assert utils._season_to_tuple("Winter 1999") == (1999, 0)
        # Sortable: Winter 2021 comes after Fall 2020
        assert utils._season_to_tuple("Winter 2021") > utils._season_to_tuple("Fall 2020")

    def test_season_to_tuple_invalid(self):
        assert utils._season_to_tuple("garbage") == (0, -1)
        assert utils._season_to_tuple(None) == (0, -1)

    def test_get_song_by_slug(self):
        data = {"songs": [{"slug": "OP1", "title": "t"}]}
        assert utils.get_song_by_slug(data, "OP1") == {"slug": "OP1", "title": "t"}
        assert utils.get_song_by_slug(data, "ED1") == {}
        assert utils.get_song_by_slug({}, "OP1") == {}

    def test_rgb_to_hex(self):
        assert utils.rgb_to_hex((255, 0, 128)) == "#ff0080"
        assert utils.rgb_to_hex((0, 0, 0)) == "#000000"

    def test_parse_timestamp_full_format(self):
        dt = utils.parse_timestamp_flexible("2026-06-11 12:30:00")
        assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 6, 11, 12, 30)

    def test_parse_timestamp_time_only_uses_today(self):
        from datetime import datetime
        dt = utils.parse_timestamp_flexible("01:02:03")
        assert dt.date() == datetime.now().date()
        assert (dt.hour, dt.minute, dt.second) == (1, 2, 3)


# ---------------------------------------------------------------------------
# Preset folder round-trip
# ---------------------------------------------------------------------------

class TestSettingsPresets:
    def test_save_load_roundtrip_with_infinities(self, tmp_path):
        folder = str(tmp_path / "presets")
        default = {"limit": 5, "groups": {"hard": {"range": [1, float("inf")]}}}
        saved = {
            "mine": {"limit": 10, "groups": {"hard": {"range": [1, float("inf")]}}},
        }
        utils._save_settings_presets(folder, saved, default, convert_inf=True)
        loaded = utils.convert_infinity_markers(utils._load_settings_presets(folder))
        # Stored as diff against defaults: only "limit" differs.
        assert loaded == {"mine": {"limit": 10}}

    def test_orphan_files_removed(self, tmp_path):
        folder = str(tmp_path / "presets")
        utils._save_settings_presets(folder, {"keep": {"a": 1}}, {"a": 0})
        utils._save_settings_presets(folder, {}, {"a": 0})
        assert os.listdir(folder) == []
