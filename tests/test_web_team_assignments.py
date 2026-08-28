"""Regression tests for team headers in the web scoreboard."""

import copy

import _app_scripts.bonus.answers as answers


def test_persisted_web_team_replaces_numeric_scoreboard_team_id(monkeypatch):
    monkeypatch.setattr(
        answers,
        "_load_web_team_assignments",
        lambda: {"Alice": "Team Rocket"},
    )
    scores = {"players": [{"name": "Alice", "score": 4, "team": "2"}]}

    result = answers._apply_web_team_assignments(scores)

    assert result["players"][0]["team"] == "Team Rocket"


def test_persisted_web_team_survives_scores_file_refresh_race(monkeypatch):
    monkeypatch.setattr(
        answers,
        "_load_web_team_assignments",
        lambda: {"Alice": "Team Rocket"},
    )
    scores = {"players": [{"name": "Alice", "score": 4, "team": ""}]}

    result = answers._apply_web_team_assignments(scores)

    assert result["players"][0]["team"] == "Team Rocket"


def test_displayable_scoreboard_team_wins_over_stale_web_assignment(monkeypatch):
    monkeypatch.setattr(
        answers,
        "_load_web_team_assignments",
        lambda: {"Alice": "Old Team"},
    )
    scores = {"players": [{"name": "Alice", "score": 4, "team": "New Team"}]}

    result = answers._apply_web_team_assignments(scores)

    assert result["players"][0]["team"] == "New Team"


def test_team_resolution_does_not_mutate_scores_payload(monkeypatch):
    monkeypatch.setattr(
        answers,
        "_load_web_team_assignments",
        lambda: {"Alice": "Team Rocket"},
    )
    scores = {"players": [{"name": "Alice", "score": 4, "team": "1"}]}
    original = copy.deepcopy(scores)

    answers._apply_web_team_assignments(scores)

    assert scores == original
