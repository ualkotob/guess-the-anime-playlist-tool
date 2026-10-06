import pytest

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch


class _ImmediateThread:
    def __init__(self, target, args=(), kwargs=None, **_options):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def _complete_anime():
    return {
        "title": "Known Anime",
        "aired": None,
        "members": None,
        "studios": [],
        "synopsis": None,
    }


def test_confirmed_missing_linked_ids_are_deferred_and_eventually_retried(
    monkeypatch,
):
    file_entry = {"name": "Known Anime", "mal": "1", "themes": {}}
    monkeypatch.setattr(state.metadata, "file_metadata", {"1": file_entry})
    monkeypatch.setattr(state.metadata, "anime_metadata", {"1": _complete_anime()})
    monkeypatch.setattr(state.metadata, "anilist_metadata", {})
    monkeypatch.setattr(state.metadata, "anidb_metadata", {})
    monkeypatch.setattr(state.metadata, "directory_files", {})
    monkeypatch.setattr(metadata_fetch.directory_scan, "scan_directory", lambda: None)
    monkeypatch.setattr(metadata_fetch.messagebox, "askyesno", lambda *_a, **_k: True)
    monkeypatch.setattr(metadata_fetch.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(metadata_fetch.time, "sleep", lambda _seconds: None)
    clock = [1_000]
    monkeypatch.setattr(metadata_fetch.time, "time", lambda: clock[0])
    saves = []
    monkeypatch.setattr(
        metadata_fetch.metadata_io,
        "save_metadata",
        lambda *args, **kwargs: saves.append((args, kwargs)),
    )
    monkeypatch.setattr(metadata_fetch, "build_filename_to_mal_map", lambda: None)

    def unavailable_arm(_mal_id):
        metadata_fetch.last_arm_lookup_succeeded = True
        return {}

    def unavailable_anilist(*_args, **_kwargs):
        metadata_fetch.last_anilist_status = "not_found"
        return None, None

    monkeypatch.setattr(metadata_fetch, "fetch_arm_ids", unavailable_arm)
    monkeypatch.setattr(metadata_fetch, "fetch_anilist_metadata", unavailable_anilist)

    metadata_fetch.fetch_all_metadata()

    failures = file_entry[metadata_fetch._FETCH_FAILURES_KEY]
    assert failures["linked_anilist"]["identity"] == "1"
    assert failures["linked_anidb"]["identity"] == "1"
    assert failures["linked_anidb"]["retry_after"] == (
        1_000 + metadata_fetch._MISSING_METADATA_RETRY_SECONDS
    )
    assert saves

    targets = metadata_fetch._collect_missing_metadata_targets()
    assert targets["resolve_ids"] == []
    assert targets["deferred"] == 2

    clock[0] += metadata_fetch._MISSING_METADATA_RETRY_SECONDS + 1
    targets = metadata_fetch._collect_missing_metadata_targets()
    assert [item[0] for item in targets["resolve_ids"]] == ["1"]


def test_transient_arm_failure_is_not_a_confirmed_missing_mapping(monkeypatch):
    class Response:
        status_code = 503

    monkeypatch.setattr(
        metadata_fetch.requests,
        "get",
        lambda *_args, **_kwargs: Response(),
    )

    assert metadata_fetch.fetch_arm_ids("1") == {}
    assert metadata_fetch.last_arm_lookup_succeeded is False


def test_reordering_file_metadata_preserves_retry_state(monkeypatch):
    failures = {
        "linked_anidb": {
            "status": "not_found",
            "identity": "1",
            "checked_at": 1_000,
            "retry_after": 2_000,
        }
    }
    monkeypatch.setattr(
        state.metadata,
        "file_metadata",
        {
            "1": {
                "themes": {},
                metadata_fetch._FETCH_FAILURES_KEY: failures,
                "mal": "1",
                "name": "Known Anime",
            }
        },
    )

    metadata_fetch.reorder_file_metadata_entry("1")

    assert (
        state.metadata.file_metadata["1"][metadata_fetch._FETCH_FAILURES_KEY]
        == failures
    )


def test_invalid_anidb_sentinel_is_resolved_instead_of_fetched(monkeypatch):
    file_entry = {
        "name": "Sparse AniDB Mapping",
        "mal": "1",
        "anilist": "1",
        "anidb": "-1",
        "themes": {},
    }
    monkeypatch.setattr(state.metadata, "file_metadata", {"1": file_entry})
    monkeypatch.setattr(state.metadata, "anime_metadata", {"1": _complete_anime()})
    monkeypatch.setattr(
        state.metadata,
        "anilist_metadata",
        {"1": {"title": "Known", "tags": [], "characters": []}},
    )
    monkeypatch.setattr(state.metadata, "anidb_metadata", {})

    targets = metadata_fetch._collect_missing_metadata_targets()

    assert targets["anidb"] == []
    assert [item[0] for item in targets["resolve_ids"]] == ["1"]


@pytest.mark.parametrize(
    ("xml", "exception_type"),
    [
        (
            "<error>aid Missing or Invalid</error>",
            metadata_fetch.AniDBResponseError,
        ),
        (
            '<error code="500">banned</error>',
            metadata_fetch.AniDBCooldownError,
        ),
    ],
)
def test_anidb_xml_errors_are_not_inferred_from_empty_metadata(
    monkeypatch, xml, exception_type
):
    class Response:
        ok = True
        status_code = 200
        text = xml

    monkeypatch.setattr(
        metadata_fetch.requests,
        "get",
        lambda *_args, **_kwargs: Response(),
    )

    with pytest.raises(exception_type) as exc_info:
        metadata_fetch.fetch_anidb_metadata("1")
    assert type(exc_info.value) is exception_type


def test_valid_sparse_anidb_anime_is_not_a_cooldown(monkeypatch):
    class Response:
        ok = True
        status_code = 200
        text = '<anime id="1"><titles /></anime>'

    monkeypatch.setattr(
        metadata_fetch.requests,
        "get",
        lambda *_args, **_kwargs: Response(),
    )

    assert metadata_fetch.fetch_anidb_metadata("1") == {
        "tags": [],
        "characters": [],
        "episodes": [],
    }
