import os

import pytest

from _app_scripts.playback import cache_download


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    folder = tmp_path / "themes_cache"
    folder.mkdir()
    metadata_file = folder / "cache_metadata.json"
    monkeypatch.setattr(cache_download, "THEMES_CACHE_FOLDER", str(folder))
    monkeypatch.setattr(cache_download, "CACHE_METADATA_FILE", str(metadata_file))
    monkeypatch.setattr(cache_download, "cache_metadata", {})
    monkeypatch.setattr(cache_download, "active_downloads", {})
    return folder


def _cached_file(cache_dir, name, size):
    path = cache_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_finalize_uses_real_file_sizes_and_evicts_lru(cache_dir, monkeypatch):
    monkeypatch.setattr(cache_download, "_cache_limit_bytes", lambda: 10)
    old_path = _cached_file(cache_dir, "old.webm", 6)
    new_path = _cached_file(cache_dir, "new.webm", 6)
    cache_download.cache_metadata["old.webm"] = {
        "path": "old.webm",
        "size": 1,
        "last_played": "2026-01-01T00:00:00",
    }

    assert cache_download._finalize_cached_file("new.webm", "new.webm", str(new_path)) is True

    assert not old_path.exists()
    assert new_path.exists()
    assert set(cache_download.cache_metadata) == {"new.webm"}
    assert cache_download.cache_metadata["new.webm"]["size"] == 6


def test_failed_eviction_keeps_new_file_for_the_active_session(cache_dir, monkeypatch):
    monkeypatch.setattr(cache_download, "_cache_limit_bytes", lambda: 10)
    old_path = _cached_file(cache_dir, "locked.webm", 8)
    new_path = _cached_file(cache_dir, "new.webm", 5)
    cache_download.cache_metadata["locked.webm"] = {
        "path": "locked.webm",
        "size": 8,
        "last_played": "2026-01-01T00:00:00",
    }
    real_remove = os.remove

    def remove_unless_locked(path):
        if os.path.normcase(path) == os.path.normcase(str(old_path)):
            raise PermissionError("file is in use")
        real_remove(path)

    monkeypatch.setattr(cache_download.os, "remove", remove_unless_locked)

    assert cache_download._finalize_cached_file("new.webm", "new.webm", str(new_path)) is False

    assert old_path.exists()
    assert new_path.exists()
    assert set(cache_download.cache_metadata) == {"locked.webm", "new.webm"}


def test_oversized_file_is_kept_as_the_only_cache_entry(cache_dir, monkeypatch):
    monkeypatch.setattr(cache_download, "_cache_limit_bytes", lambda: 10)
    old_path = _cached_file(cache_dir, "old.webm", 6)
    new_path = _cached_file(cache_dir, "oversized.webm", 11)
    cache_download.cache_metadata["old.webm"] = {
        "path": "old.webm",
        "size": 6,
        "last_played": "2026-01-01T00:00:00",
    }

    assert cache_download._finalize_cached_file("oversized.webm", "oversized.webm", str(new_path)) is True

    assert not old_path.exists()
    assert new_path.exists()
    assert set(cache_download.cache_metadata) == {"oversized.webm"}


def test_later_download_recovers_from_a_temporary_locked_file_overage(cache_dir, monkeypatch):
    monkeypatch.setattr(cache_download, "_cache_limit_bytes", lambda: 10)
    locked_path = _cached_file(cache_dir, "locked.webm", 8)
    middle_path = _cached_file(cache_dir, "middle.webm", 5)
    cache_download.cache_metadata["locked.webm"] = {
        "path": "locked.webm",
        "size": 8,
        "last_played": "2026-01-01T00:00:00",
    }
    real_remove = os.remove

    def remove_unless_locked(path):
        if os.path.normcase(path) == os.path.normcase(str(locked_path)):
            raise PermissionError("file is in use")
        real_remove(path)

    monkeypatch.setattr(cache_download.os, "remove", remove_unless_locked)
    assert cache_download._finalize_cached_file("middle.webm", "middle.webm", str(middle_path)) is False

    monkeypatch.setattr(cache_download.os, "remove", real_remove)
    latest_path = _cached_file(cache_dir, "latest.webm", 2)
    assert cache_download._finalize_cached_file("latest.webm", "latest.webm", str(latest_path)) is True

    assert not locked_path.exists()
    assert middle_path.exists()
    assert latest_path.exists()
    assert sum(path.stat().st_size for path in cache_dir.glob("*.webm")) <= 10


def test_load_registers_untracked_files_and_trims_to_limit(cache_dir, monkeypatch):
    monkeypatch.setattr(cache_download, "_cache_limit_bytes", lambda: 10)
    first = _cached_file(cache_dir, "first.webm", 6)
    second = _cached_file(cache_dir, "second.webm", 6)
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))

    cache_download.load_cache_metadata()

    remaining = [path for path in cache_dir.rglob("*.webm") if path.is_file()]
    assert remaining == [second]
    assert sum(path.stat().st_size for path in remaining) <= 10
    assert set(cache_download.cache_metadata) == {"second.webm"}
