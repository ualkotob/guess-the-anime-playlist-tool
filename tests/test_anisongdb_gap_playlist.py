"""Tests for creating an editable AniSongDB gap-review playlist."""

import json

from _app_scripts.playlists import playlist_io
from _app_scripts.theme import anisongdb


def test_create_anisongdb_gap_playlist_writes_op_ed_snapshot(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(playlist_io, "PLAYLISTS_FOLDER", str(tmp_path))
    monkeypatch.setattr(
        anisongdb,
        "gap_filenames",
        lambda **kwargs: calls.append(kwargs) or ["opening.webm", "ending.webm"],
    )

    result = playlist_io.create_anisongdb_gap_playlist(
        confirm_overwrite=False,
        notify=False,
    )

    playlist_path = tmp_path / f"{playlist_io.ANISONGDB_GAP_PLAYLIST_NAME}.json"
    assert result == (str(playlist_path), 2)
    assert calls == [{"preferred_only": True, "theme_types": {"OP", "ED"}}]
    data = json.loads(playlist_path.read_text(encoding="utf-8"))
    assert data["name"] == playlist_io.ANISONGDB_GAP_PLAYLIST_NAME
    assert data["infinite"] is False
    assert data["current_index"] == -1
    assert data["playlist"] == ["opening.webm", "ending.webm"]
