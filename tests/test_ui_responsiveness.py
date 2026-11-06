"""Background work must leave the Tk thread able to run."""

import threading
from types import SimpleNamespace

from _app_scripts import utils
from _app_scripts.data import metadata_io


def test_worker_loops_let_the_tk_thread_run_between_items(monkeypatch):
    sleeps = []
    monkeypatch.setattr(utils, "time", SimpleNamespace(sleep=sleeps.append))
    source = {"a": 1, "b": 2}
    seen = []

    def worker():
        for key in utils.yield_to_ui(source):
            source["c"] = 3  # Another thread changes the dict mid-loop.
            seen.append(key)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(2)
    assert seen == ["a", "b"]
    assert sleeps == [0, 0]
    # The Tk thread never gives the GIL away.
    assert list(utils.yield_to_ui(source)) == ["a", "b", "c"]
    assert sleeps == [0, 0]


def test_loaded_metadata_is_excluded_from_full_garbage_collections(monkeypatch, tmp_path):
    frozen = []
    monkeypatch.setattr(metadata_io, "gc", SimpleNamespace(freeze=lambda: frozen.append(True)))
    monkeypatch.setattr(metadata_io, "load_metadata_compressed", lambda path, **kwargs: (None, False))
    for name in ("MANUAL_METADATA_FILE", "ANIME_METADATA_OVERRIDES_FILE", "THEME_ARTIST_RESOLUTIONS_FILE"):
        monkeypatch.setattr(metadata_io, name, str(tmp_path / name))
    monkeypatch.setattr(metadata_io, "save_metadata", lambda: None)
    metadata_io.load_metadata()
    assert frozen == [True]
