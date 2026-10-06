from _app_scripts.playlists import playlist


def test_theme_deduplication_preserves_selected_file_order(monkeypatch):
    metadata = {
        "op-low.webm": {"mal": "1", "slug": "OP1", "version": "1"},
        "op-best.webm": {"mal": "1", "slug": "OP1", "version": "1"},
        "ed.webm": {"mal": "1", "slug": "ED1", "version": "1"},
    }
    monkeypatch.setattr(
        playlist.metadata_fetch,
        "get_file_metadata_by_name",
        metadata.get,
    )
    monkeypatch.setattr(
        playlist.metadata_display,
        "prioritize_theme_files",
        lambda files: "op-best.webm" if "op-best.webm" in files else files[0],
    )

    result = playlist.deduplicate_theme_versions(
        ["op-low.webm", "op-best.webm", "op-low.webm", "ed.webm"]
    )

    assert result == ["op-best.webm", "ed.webm"]
