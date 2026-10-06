"""Regression tests for metadata package export freshness."""

from _app_scripts.data import metadata_io, updates_io


def test_export_flushes_current_metadata_synchronously(monkeypatch):
    calls = []

    monkeypatch.setattr(
        metadata_io,
        "save_metadata_overrides",
        lambda: calls.append(("overrides", None)),
    )
    monkeypatch.setattr(
        metadata_io,
        "save_animethemes_metadata",
        lambda: calls.append(("animethemes", None)),
    )
    monkeypatch.setattr(
        metadata_io,
        "save_anisongdb_metadata",
        lambda: calls.append(("anisongdb", None)),
    )
    monkeypatch.setattr(
        metadata_io,
        "save_metadata",
        lambda *, immediate=False: calls.append(("metadata", immediate)),
    )

    updates_io._persist_metadata_for_export()

    assert calls == [
        ("overrides", None),
        ("animethemes", None),
        ("anisongdb", None),
        ("metadata", True),
    ]
