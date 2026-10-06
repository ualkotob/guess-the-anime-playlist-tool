"""Tests for playlist entry path/filename resolution (entry_paths.py)."""

import pytest

import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.playback.cache_download as cache_download
from core.game_state import state


@pytest.fixture
def directory_files():
    """Mutate state.metadata.directory_files freely; restore after."""
    saved = dict(state.metadata.directory_files)
    state.metadata.directory_files.clear()
    yield state.metadata.directory_files
    state.metadata.directory_files.clear()
    state.metadata.directory_files.update(saved)


class TestGetCleanFilename:
    def test_plain_entry_passes_through(self):
        assert entry_paths.get_clean_filename("Show-OP1.webm") == "Show-OP1.webm"

    def test_lightning_prefix_stripped(self):
        assert entry_paths.get_clean_filename("[L]Show-OP1.webm") == "Show-OP1.webm"

    def test_absolute_path_reduced_to_basename(self):
        assert entry_paths.get_clean_filename(r"C:\themes\Show-OP1.webm") == "Show-OP1.webm"

    def test_base_only_strips_id_tags_and_extension(self):
        assert entry_paths.get_clean_filename("Show-OP1[MAL]123.webm", base_only=True) == "Show-OP1"

    def test_base_only_plain_filename(self):
        assert entry_paths.get_clean_filename("Show-OP1.webm", base_only=True) == "Show-OP1"

    def test_shared_theme_reference_keeps_identity_and_physical_filename(self):
        reference = entry_paths.make_theme_reference(
            "Show-OP1.webm", "123", "OP1", "1"
        )

        assert entry_paths.parse_theme_reference(reference) == {
            "mal_id": "123",
            "slug": "OP1",
            "version": "1",
            "filename": "Show-OP1.webm",
        }
        assert entry_paths.get_clean_filename(reference) == "Show-OP1.webm"


class TestGetFilePath:
    def test_directory_files_lookup(self, directory_files, monkeypatch):
        directory_files["Show-OP1.webm"] = r"themes\Show-OP1.webm"
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda f: None)
        assert entry_paths.get_file_path("Show-OP1.webm") == r"themes\Show-OP1.webm"

    def test_lightning_prefix_resolves_same_file(self, directory_files, monkeypatch):
        directory_files["Show-OP1.webm"] = r"themes\Show-OP1.webm"
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda f: None)
        assert entry_paths.get_file_path("[L]Show-OP1.webm") == r"themes\Show-OP1.webm"

    def test_shared_theme_reference_resolves_same_file(self, directory_files, monkeypatch):
        directory_files["Show-OP1.webm"] = r"themes\Show-OP1.webm"
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda f: None)
        reference = entry_paths.make_theme_reference(
            "Show-OP1.webm", "123", "OP1", "1"
        )

        assert entry_paths.get_file_path(reference) == r"themes\Show-OP1.webm"

    def test_webm_entry_resolves_converted_mp4(self, directory_files, monkeypatch):
        directory_files["Show-OP1.mp4"] = r"themes\Show-OP1.mp4"
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda f: None)
        assert entry_paths.get_file_path("Show-OP1.webm") == r"themes\Show-OP1.mp4"

    def test_mp4_entry_resolves_webm(self, directory_files, monkeypatch):
        directory_files["Show-OP1.webm"] = r"themes\Show-OP1.webm"
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda f: None)
        assert entry_paths.get_file_path("Show-OP1.mp4") == r"themes\Show-OP1.webm"

    def test_exact_extension_is_preferred(self, directory_files, monkeypatch):
        directory_files["Show-OP1.webm"] = r"themes\Show-OP1.webm"
        directory_files["Show-OP1.mp4"] = r"themes\Show-OP1.mp4"
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda f: None)
        assert entry_paths.get_file_path("Show-OP1.webm") == r"themes\Show-OP1.webm"

    def test_cache_fallback(self, directory_files, monkeypatch):
        monkeypatch.setattr(
            cache_download, "get_cached_file_path",
            lambda f: r"themes_cache\Show-OP1.webm" if f == "Show-OP1.webm" else None,
        )
        assert entry_paths.get_file_path("Show-OP1.webm") == r"themes_cache\Show-OP1.webm"

    def test_missing_everywhere_returns_none(self, directory_files, monkeypatch):
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda f: None)
        assert entry_paths.get_file_path("Nope-OP1.webm") is None

    def test_existing_absolute_path_returned_as_is(self, tmp_path):
        p = tmp_path / "Show-OP1.webm"
        p.write_bytes(b"")
        assert entry_paths.get_file_path(str(p)) == str(p)

    def test_missing_absolute_path_returns_none(self, tmp_path):
        assert entry_paths.get_file_path(str(tmp_path / "gone.webm")) is None

    def test_absolute_webm_path_resolves_converted_mp4(self, tmp_path):
        mp4_path = tmp_path / "Show-OP1.mp4"
        mp4_path.write_bytes(b"")
        assert entry_paths.get_file_path(str(tmp_path / "Show-OP1.webm")) == str(mp4_path)


class TestExtensionEquivalentAvailability:
    def test_converted_mp4_prevents_download(self, directory_files, monkeypatch):
        directory_files["Show-OP1.mp4"] = r"themes\Show-OP1.mp4"
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda _f: None)

        assert cache_download.check_file_availability("Show-OP1.webm") is True
        assert cache_download.download_to_cache("Show-OP1.webm", silent=True) is False

    def test_playable_resolution_uses_converted_mp4(self, directory_files, monkeypatch):
        mp4_path = r"themes\Show-OP1.mp4"
        directory_files["Show-OP1.mp4"] = mp4_path
        monkeypatch.setattr(cache_download, "get_cached_file_path", lambda _f: None)
        local_path = entry_paths.get_file_path("Show-OP1.webm")

        assert cache_download.resolve_playable_path(
            "Show-OP1.webm", "Show-OP1.webm", local_path, fullscreen=False
        ) == (mp4_path, False)
