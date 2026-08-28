import pytest

from _app_scripts.queue_round.lightning_rounds import (
    lightning_manager,
    lightning_settings,
    trivia_round,
)


def test_trivia_question_stays_during_answer_by_default():
    assert (
        lightning_settings.lightning_mode_settings_default["trivia"]
        ["show_question_during_answer"]
        is True
    )


def test_enabled_setting_keeps_active_trivia_question(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "trivia"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"trivia": {"show_question_during_answer": True}},
    )
    monkeypatch.setattr(trivia_round, "light_trivia_answer", "An answer")

    assert lightning_manager._should_keep_trivia_question() is True


def test_trivia_fallback_does_not_keep_synopsis_as_a_trivia_question(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "synopsis"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"trivia": {"show_question_during_answer": True}},
    )
    monkeypatch.setattr(trivia_round, "light_trivia_answer", "An answer")

    assert lightning_manager._should_keep_trivia_question() is False


def test_synopsis_stays_during_answer_by_default(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "synopsis"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"synopsis": {}},
    )

    assert (
        lightning_settings.lightning_mode_settings_default["synopsis"]
        ["show_synopsis_during_answer"]
        is True
    )
    assert lightning_manager._should_keep_synopsis() is True


def test_synopsis_setting_can_hide_it_during_answer(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "synopsis"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"synopsis": {"show_synopsis_during_answer": False}},
    )

    assert lightning_manager._should_keep_synopsis() is False


def test_short_trivia_reveals_at_minimum_pace():
    duration = trivia_round.get_reveal_duration(
        word_count=6,
        round_length=12,
        answer_time=6,
    )

    assert duration == pytest.approx(1.2)


def test_long_trivia_still_preserves_answer_window():
    duration = trivia_round.get_reveal_duration(
        word_count=24,
        round_length=12,
        answer_time=6,
    )

    assert duration == pytest.approx(4.8)


def test_trivia_reveals_immediately_when_no_reveal_time_is_available():
    duration = trivia_round.get_reveal_duration(
        word_count=10,
        round_length=5,
        answer_time=6,
    )

    assert duration == 0.0
