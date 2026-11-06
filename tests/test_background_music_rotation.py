"""Assigned fixed-round music must start its own rotation period."""

import pytest

from _app_scripts.playback import transport


@pytest.fixture
def rotation(monkeypatch):
    changes = []
    monkeypatch.setattr(transport, "background_music_rounds", 0)
    monkeypatch.setattr(transport.state.lightning, "fixed_current_round", None)
    monkeypatch.setattr(
        transport.state.playback,
        "lightning_mode_settings",
        {"_misc_settings": {"background_music": {"rounds_per_track": 3}}},
    )
    monkeypatch.setattr(transport.music, "next_background_track", lambda: changes.append(True))
    return changes


def test_unassigned_rounds_keep_the_existing_rotation_limit(rotation):
    for _ in range(3):
        transport._advance_background_music_round()
    assert rotation == []
    transport._advance_background_music_round()
    assert rotation == [True]


@pytest.mark.parametrize("previous_rounds", [0, 1, 2, 3, 17])
def test_assigned_track_starts_a_fresh_period(monkeypatch, rotation, previous_rounds):
    monkeypatch.setattr(transport, "background_music_rounds", previous_rounds)
    monkeypatch.setattr(
        transport.state.lightning, "fixed_current_round", {"background_track": "horror.mp3"}
    )
    transport._advance_background_music_round()
    assert transport.background_music_rounds == 1
    assert rotation == []

    monkeypatch.setattr(transport.state.lightning, "fixed_current_round", {})
    transport._advance_background_music_round()
    transport._advance_background_music_round()
    assert rotation == []
    transport._advance_background_music_round()
    assert rotation == [True]


@pytest.mark.parametrize("rounds_per_track", [3, 4])
@pytest.mark.parametrize("previous_rounds", [0, 2, 3, 17])
def test_spaced_fixed_parts_never_rotate_randomly(
    monkeypatch, rotation, rounds_per_track, previous_rounds
):
    settings = transport.state.playback.lightning_mode_settings
    settings["_misc_settings"]["background_music"]["rounds_per_track"] = rounds_per_track
    for part in range(4):
        # Each part can start at any phase after other session rounds.
        transport.background_music_rounds = previous_rounds + part
        for question in range(10):
            fixed_round = {"background_track": f"part-{part}-{question}.mp3"} if question % 2 == 0 else {}
            monkeypatch.setattr(transport.state.lightning, "fixed_current_round", fixed_round)
            transport._advance_background_music_round()
    assert rotation == []


@pytest.mark.parametrize("track", [None, "", "   "])
def test_empty_assignment_does_not_reset_rotation(monkeypatch, rotation, track):
    monkeypatch.setattr(transport, "background_music_rounds", 3)
    monkeypatch.setattr(
        transport.state.lightning, "fixed_current_round", {"background_track": track}
    )
    transport._advance_background_music_round()
    assert rotation == [True]
    assert transport.background_music_rounds == 4
