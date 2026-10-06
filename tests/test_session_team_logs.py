"""Regression tests for team grouping in saved session logs."""

import json

from _app_scripts.file import scoreboard_control, session_end


session_stats = session_end.session_stats


def _score(timestamp, player, score, team=""):
    entry = {
        "timestamp": timestamp,
        "type": "scoreboard_score",
        "player": player,
        "old_score": 0,
        "new_score": score,
        "delta": score,
    }
    if team:
        entry["team"] = team
    return entry


def test_scoreboard_summary_groups_players_by_team():
    data = [
        _score("2026-08-28 12:00:00", "Alice", 7, "Team Rocket"),
        _score("2026-08-28 12:00:01", "Bob", 3, "Team Rocket"),
        _score("2026-08-28 12:00:02", "Carol", 8, "Team Aqua"),
        _score("2026-08-28 12:00:03", "Dave", 2),
    ]

    lines = session_stats.generate_session_stats(data)

    rocket = lines.index("Team Rocket [10 PTs]")
    aqua = lines.index("Team Aqua [8 PTs]")
    no_team = lines.index("NO TEAM [2 PTs]")
    assert rocket < aqua < no_team
    assert lines[rocket + 1:rocket + 3] == ["7     Alice", "3     Bob"]
    assert lines[aqua + 1] == "8     Carol"
    assert lines[no_team + 1] == "2     Dave"


def test_scoreboard_summary_stays_flat_without_teams():
    data = [
        _score("2026-08-28 12:00:00", "Alice", 3),
        _score("2026-08-28 12:00:01", "Bob", 7),
    ]

    lines = session_stats.generate_session_stats(data)

    header = lines.index("PTs   PLAYER")
    assert lines[header + 2:header + 4] == ["7     Bob", "3     Alice"]
    assert not any("NO TEAM" in line for line in lines)


def test_score_changes_snapshot_current_team_assignments(tmp_path, monkeypatch):
    monkeypatch.setattr(scoreboard_control, "_DATA_FOLDER", str(tmp_path))
    (tmp_path / "scoreboard_scores.json").write_text(
        json.dumps({"players": [{"name": "Alice", "score": 5, "team": "Team Rocket"}]}),
        encoding="utf-8",
    )
    (tmp_path / "score_changes.json").write_text(
        json.dumps({
            "timestamp": "2026-08-28 12:00:00",
            "player": "Alice",
            "old_score": 0,
            "new_score": 5,
            "delta": 5,
        }) + "\n",
        encoding="utf-8",
    )
    session_data = []

    scoreboard_control.add_score_changes_to_session(session_data)

    assert session_data[0]["team"] == "Team Rocket"


def test_score_changes_remove_old_team_when_player_is_now_unassigned(tmp_path, monkeypatch):
    monkeypatch.setattr(scoreboard_control, "_DATA_FOLDER", str(tmp_path))
    (tmp_path / "scoreboard_scores.json").write_text(
        json.dumps({"players": [{"name": "Alice", "score": 5, "team": ""}]}),
        encoding="utf-8",
    )
    session_data = [_score("2026-08-28 12:00:00", "Alice", 5, "Old Team")]

    scoreboard_control.add_score_changes_to_session(session_data)

    assert "team" not in session_data[0]


def test_score_change_detail_line_includes_team_name():
    data = [_score("2026-08-28 12:00:00", "Alice", 5, "Team Rocket")]

    lines = session_stats.generate_text_from_session_data(data)

    assert any("[SCOREBOARD] [Team Rocket] Alice +5 PTs" in line for line in lines)


def test_quick_reload_of_same_fixed_playlist_counts_once():
    data = [
        {
            "timestamp": "2026-08-28 12:00:00",
            "type": "fixed_rounds_start",
            "playlist_name": "Opening Night",
            "creator": "Host",
        },
        {
            "timestamp": "2026-08-28 12:02:00",
            "type": "fixed_rounds_start",
            "playlist_name": "Opening Night",
            "creator": "Host",
        },
    ]

    assert session_stats.get_session_summary_counts(data)["fixed_playlist_count"] == 1


def test_later_replay_of_same_fixed_playlist_counts_again():
    data = [
        {
            "timestamp": "2026-08-28 12:00:00",
            "type": "fixed_rounds_start",
            "playlist_name": "Opening Night",
            "creator": "Host",
        },
        {
            "timestamp": "2026-08-28 12:06:00",
            "type": "fixed_rounds_start",
            "playlist_name": "Opening Night",
            "creator": "Host",
        },
    ]

    assert session_stats.get_session_summary_counts(data)["fixed_playlist_count"] == 2
