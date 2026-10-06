"""Regression tests for authoritative metadata package imports."""

import copy

# Import metadata_io first to follow the application's cycle-safe import order.
import _app_scripts.data.metadata_io  # noqa: F401
from _app_scripts import utils
from _app_scripts.file.metadata import metadata_import
from core.game_state import state


def test_package_entries_replace_matching_data_and_add_missing_entries():
    local = {
        "existing": {"artist": ["Old Artist"]},
        "local-only": {"artist": ["Local Artist"]},
    }
    package = {
        "existing": {"artist": ["Updated Artist"]},
        "missing": {"artist": ["New Artist"]},
    }

    new_count = metadata_import._merge_package_entries(local, package)

    assert new_count == 1
    assert local == {
        "existing": {"artist": ["Updated Artist"]},
        "local-only": {"artist": ["Local Artist"]},
        "missing": {"artist": ["New Artist"]},
    }


def test_package_overrides_are_folded_into_release_data_not_user_overrides():
    saved_anime = copy.deepcopy(state.metadata.anime_metadata)
    saved_overrides = copy.deepcopy(state.metadata.anime_metadata_overrides)
    try:
        state.metadata.anime_metadata.clear()
        state.metadata.anime_metadata.update({
            "1": {"songs": [{"slug": "OP1", "artist": ["Old Artist"]}]},
        })
        state.metadata.anime_metadata_overrides.clear()
        state.metadata.anime_metadata_overrides.update({
            "1": {"songs": [{"slug": "OP1", "artist": ["User Artist"]}]},
        })

        metadata_import._merge_package_store(
            "anime_metadata_overrides",
            {"1": {"songs": [{"slug": "OP1", "artist": ["Package Artist"]}]}},
        )

        package_song = state.metadata.anime_metadata["1"]["songs"][0]
        assert package_song["artist"] == ["Package Artist"]
        assert state.metadata.anime_metadata_overrides["1"]["songs"][0]["artist"] == ["User Artist"]

        # load_metadata applies the user's overrides after package data.
        utils.deep_merge(
            state.metadata.anime_metadata,
            state.metadata.anime_metadata_overrides,
        )
        assert state.metadata.anime_metadata["1"]["songs"][0]["artist"] == ["User Artist"]
    finally:
        state.metadata.anime_metadata.clear()
        state.metadata.anime_metadata.update(saved_anime)
        state.metadata.anime_metadata_overrides.clear()
        state.metadata.anime_metadata_overrides.update(saved_overrides)


def test_release_artist_correction_wins_over_bundled_catalog_projection(monkeypatch):
    saved_anime = copy.deepcopy(state.metadata.anime_metadata)
    saved_animethemes = copy.deepcopy(state.metadata.animethemes_metadata)
    saved_overrides = copy.deepcopy(state.metadata.anime_metadata_overrides)
    try:
        state.metadata.anime_metadata.clear()
        state.metadata.anime_metadata.update({
            "1": {"songs": [{"slug": "OP1", "artist": []}]},
        })
        state.metadata.animethemes_metadata.clear()
        state.metadata.anime_metadata_overrides.clear()
        state.metadata.anime_metadata_overrides.update({
            "1": {"songs": [{"slug": "OP1", "artist": ["User Artist"]}]},
        })

        from _app_scripts.theme import animethemes

        monkeypatch.setattr(animethemes, "build_indexes", lambda *, force=False: None)

        def project_stale_catalog():
            state.metadata.anime_metadata["1"] = {
                "songs": [{"slug": "OP1", "artist": []}],
            }

        monkeypatch.setattr(
            animethemes,
            "sync_catalog_to_metadata",
            project_stale_catalog,
        )

        metadata_import._apply_package_stores({
            "anime_metadata": {
                "1": {"songs": [{"slug": "OP1", "artist": ["Package Artist"]}]},
            },
            "anime_metadata_overrides": {
                "1": {"songs": [{"slug": "OP1", "artist": ["Corrected Artist"]}]},
            },
            "animethemes_metadata": {"anime": [{"id": 1}]},
        })

        assert state.metadata.anime_metadata["1"]["songs"][0]["artist"] == [
            "Corrected Artist"
        ]
        assert state.metadata.anime_metadata_overrides["1"]["songs"][0]["artist"] == [
            "User Artist"
        ]

        # The recipient's personal correction remains the final display value.
        utils.deep_merge(
            state.metadata.anime_metadata,
            state.metadata.anime_metadata_overrides,
        )
        assert state.metadata.anime_metadata["1"]["songs"][0]["artist"] == [
            "User Artist"
        ]
    finally:
        state.metadata.anime_metadata.clear()
        state.metadata.anime_metadata.update(saved_anime)
        state.metadata.animethemes_metadata.clear()
        state.metadata.animethemes_metadata.update(saved_animethemes)
        state.metadata.anime_metadata_overrides.clear()
        state.metadata.anime_metadata_overrides.update(saved_overrides)


def test_import_is_saved_synchronously_before_reload(monkeypatch):
    calls = []

    monkeypatch.setattr(
        metadata_import.metadata_io,
        "save_animethemes_metadata",
        lambda: calls.append(("save_animethemes", None)),
    )
    monkeypatch.setattr(
        metadata_import.metadata_io,
        "save_anisongdb_metadata",
        lambda: calls.append(("save_anisongdb", None)),
    )
    monkeypatch.setattr(
        metadata_import.metadata_io,
        "save_metadata",
        lambda *, immediate=False: calls.append(("save", immediate)),
    )
    monkeypatch.setattr(
        metadata_import.metadata_io,
        "load_metadata",
        lambda: calls.append(("load", None)),
    )

    metadata_import._persist_imported_metadata()

    assert calls == [
        ("save_animethemes", None),
        ("save_anisongdb", None),
        ("save", True),
        ("load", None),
    ]


def test_anime_overrides_file_is_part_of_import_format():
    assert (
        "metadata/anime_metadata_overrides.json",
        "anime_metadata_overrides",
    ) in metadata_import.METADATA_PACKAGE_FILES


def test_anisongdb_catalog_is_part_of_import_format():
    assert (
        "metadata/anisongdb_metadata.json",
        "anisongdb_metadata",
    ) in metadata_import.METADATA_PACKAGE_FILES


def test_animethemes_catalog_is_part_of_import_format():
    assert (
        "metadata/animethemes_metadata.json",
        "animethemes_metadata",
    ) in metadata_import.METADATA_PACKAGE_FILES
