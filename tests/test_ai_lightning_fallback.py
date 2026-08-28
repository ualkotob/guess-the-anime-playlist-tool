from types import SimpleNamespace

import pytest

from _app_scripts.queue_round.lightning_rounds import (
    emoji_overlay,
    lightning_manager,
    lightning_settings,
    trivia_round,
)


def test_openai_client_has_bounded_timeout_and_no_retries(monkeypatch):
    options = {}

    def fake_openai(**kwargs):
        options.update(kwargs)
        return object()

    monkeypatch.setattr(trivia_round.openai, "OpenAI", fake_openai)

    trivia_round.set_openai_client_key("test-key")

    assert options["timeout"] == trivia_round.OPENAI_TIMEOUT_SECONDS
    assert options["max_retries"] == 0


def test_trivia_uses_current_low_latency_model(monkeypatch):
    request = {}
    text = SimpleNamespace(
        text="Question: In Test (2020), what hidden symbol appears?\nAnswer: A crescent"
    )
    response = SimpleNamespace(output=[SimpleNamespace(content=[text])])

    class _Responses:
        def create(self, **kwargs):
            request.update(kwargs)
            return response

    monkeypatch.setattr(
        trivia_round,
        "client",
        SimpleNamespace(responses=_Responses()),
    )
    monkeypatch.setattr(trivia_round.state.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(trivia_round, "_api_retry_after", 0)
    monkeypatch.setattr(trivia_round.state.lightning, "fixed_current_round", None)
    monkeypatch.setattr(trivia_round.metadata_display, "get_display_title", lambda _data: "Test")
    monkeypatch.setattr(trivia_round.metadata_display, "is_game", lambda _data: False)

    result = trivia_round.generate_anime_trivia(
        {"season": "Winter 2020", "synopsis": ""}
    )

    assert result == (
        "In Test (2020), what hidden symbol appears?",
        "A crescent",
    )
    assert trivia_round.OPENAI_MODEL == "gpt-5.6-terra"
    assert trivia_round.gpt_cutoff_year == 2025
    assert request["model"] == trivia_round.OPENAI_MODEL
    assert request["reasoning"] == {
        "effort": trivia_round.TRIVIA_REASONING_EFFORT
    }
    assert trivia_round.TRIVIA_REASONING_EFFORT == "low"
    assert request["max_output_tokens"] == trivia_round.TRIVIA_MAX_OUTPUT_TOKENS
    assert "Silently consider three candidates" in request["input"]
    assert 'Bad example for "Death Note"' in request["input"]


def test_title_derived_answer_is_rejected():
    assert trivia_round.answer_uses_title_clue("Death Note", "the notebook")
    assert not trivia_round.is_acceptable_trivia(
        "Death Note",
        "In Death Note (2006), what item must be touched?",
        "the notebook",
    )


def test_specific_title_independent_answer_is_accepted():
    assert trivia_round.is_acceptable_trivia(
        "Death Note",
        "In Death Note (2006), what alias does the investigation assign its suspect?",
        "Kira",
    )


def test_generated_title_derived_answer_is_not_cached(monkeypatch):
    text = SimpleNamespace(
        text=(
            "Question: In Death Note (2006), what object must be touched?\n"
            "Answer: A notebook"
        )
    )
    response = SimpleNamespace(output=[SimpleNamespace(content=[text])])

    class _Responses:
        def create(self, **_kwargs):
            return response

    monkeypatch.setattr(
        trivia_round,
        "client",
        SimpleNamespace(responses=_Responses()),
    )
    monkeypatch.setattr(trivia_round.state.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(trivia_round, "_api_retry_after", 0)
    monkeypatch.setattr(trivia_round.state.lightning, "fixed_current_round", None)
    monkeypatch.setattr(trivia_round.state.metadata, "ai_metadata", {})
    monkeypatch.setattr(
        trivia_round.metadata_display,
        "get_display_title",
        lambda _data: "Death Note",
    )
    monkeypatch.setattr(trivia_round.metadata_display, "is_game", lambda _data: False)
    monkeypatch.setattr(
        trivia_round.metadata_io,
        "save_metadata",
        lambda: pytest.fail("rejected trivia was cached"),
    )

    result = trivia_round.generate_anime_trivia(
        {"mal": 1535, "season": "Fall 2006", "synopsis": ""}
    )

    assert result == ("No trivia available.", "None")
    assert trivia_round.state.metadata.ai_metadata == {}


def test_cached_trivia_filters_title_derived_answers(monkeypatch):
    monkeypatch.setattr(
        trivia_round.state.metadata,
        "ai_metadata",
        {
            "1535": {
                "trivia": [
                    ["In Death Note (2006), what object is touched?", "notebook"],
                    ["In Death Note (2006), what alias is assigned?", "Kira"],
                ]
            }
        },
    )

    assert trivia_round.get_cached_trivia(
        {"mal": 1535, "title": "Death Note"}
    ) == ["In Death Note (2006), what alias is assigned?", "Kira"]


def test_cached_ai_metadata_survives_json_string_keys(monkeypatch):
    monkeypatch.setattr(
        trivia_round.state.metadata,
        "ai_metadata",
        {
                "123": {
                    "trivia": [["Cached question?", "Cached answer"]],
                    "emojis": ["🧪", "🧑‍🔬", "❤️", "🇯🇵", "👁️‍🗨️", "🛡️"],
                }
            },
    )

    data = {"mal": 123}

    assert trivia_round.get_cached_trivia(data) == [
        "Cached question?",
        "Cached answer",
    ]
    assert emoji_overlay.get_cached_emoji_clues(data) == [
        "🧪", "🧑‍🔬", "❤️", "🇯🇵", "👁️‍🗨️", "🛡️",
    ]


def test_no_emoji_api_call_when_playback_needs_clue(monkeypatch):
    class _Responses:
        def create(self, **_kwargs):
            raise AssertionError("playback attempted a synchronous API call")

    monkeypatch.setattr(trivia_round, "client", SimpleNamespace(responses=_Responses()))
    monkeypatch.setattr(emoji_overlay.state.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(emoji_overlay.state.metadata, "ai_metadata", {})

    assert emoji_overlay.get_emoji_clues_for_title(
        {"mal": 456}, allow_api=False
    ) is None


def test_emoji_generation_uses_progressive_prompt_and_validation(monkeypatch):
    request = {}
    text = SimpleNamespace(
        text=(
            '{"emojis":["🧪","🧑‍🔬","❤️","🇯🇵","👁️‍🗨️","🛡️"]}'
        )
    )
    response = SimpleNamespace(output=[SimpleNamespace(content=[text])])

    class _Responses:
        def create(self, **kwargs):
            request.update(kwargs)
            return response

    monkeypatch.setattr(
        trivia_round,
        "client",
        SimpleNamespace(responses=_Responses()),
    )
    monkeypatch.setattr(trivia_round.state.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(trivia_round, "_api_retry_after", 0)
    monkeypatch.setattr(trivia_round.state.metadata, "ai_metadata", {})
    monkeypatch.setattr(
        emoji_overlay.metadata_display,
        "get_display_title",
        lambda _data: "Recent Test",
    )

    result = emoji_overlay.get_emoji_clues_for_title(
        {
            "season": "Spring 2026",
            "synopsis": "A scientist discovers a hidden shield in modern Japan.",
        }
    )

    assert result == ["🧪", "🧑‍🔬", "❤️", "🇯🇵", "👁️‍🗨️", "🛡️"]
    assert request["reasoning"] == {
        "effort": emoji_overlay.EMOJI_REASONING_EFFORT
    }
    assert emoji_overlay.EMOJI_REASONING_EFFORT == "low"
    assert request["max_output_tokens"] == emoji_overlay.EMOJI_MAX_OUTPUT_TOKENS
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert "Positions 1-2: subtle but fair clues" in request["input"]
    assert "Recent-title context" in request["input"]
    assert "hidden shield" in request["input"]


def test_emoji_validation_requires_six_distinct_single_emojis():
    valid = ["🧪", "🧑‍🔬", "❤️", "🇯🇵", "👁️‍🗨️", "🛡️"]

    assert emoji_overlay.validate_emoji_clues(valid) == valid
    assert emoji_overlay.validate_emoji_clues(valid[:5]) is None
    assert emoji_overlay.validate_emoji_clues(valid[:5] + ["🧪"]) is None
    assert emoji_overlay.validate_emoji_clues(valid[:5] + ["clue"]) is None
    assert emoji_overlay.validate_emoji_clues(valid[:5] + ["🦸‍♂️😈"]) is None
    assert emoji_overlay.validate_emoji_clues(valid[:5] + [["🛡️"]]) is None


def test_invalid_cached_emoji_clues_are_ignored(monkeypatch):
    monkeypatch.setattr(
        trivia_round.state.metadata,
        "ai_metadata",
        {"123": {"emojis": ["🧪", "🧑‍🔬", "❤️", "🇯🇵", "👁️‍🗨️"]}},
    )

    assert emoji_overlay.get_cached_emoji_clues({"mal": 123}) is None


def test_emoji_clues_stay_during_answer_by_default(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "emoji"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"emoji": {}},
    )

    assert (
        lightning_settings.lightning_mode_settings_default["emoji"]
        ["show_emojis_during_answer"]
        is True
    )
    assert lightning_manager._should_keep_emoji_clues() is True


def test_emoji_fallback_does_not_keep_emoji_overlay(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "regular"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"emoji": {"show_emojis_during_answer": True}},
    )

    assert lightning_manager._should_keep_emoji_clues() is False


def test_api_failure_suppresses_repeated_requests(monkeypatch):
    monkeypatch.setattr(trivia_round, "client", object())
    monkeypatch.setattr(trivia_round.state.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(trivia_round, "_api_retry_after", 0)
    monkeypatch.setattr(trivia_round, "_api_failure_reason", None)
    monkeypatch.setattr(trivia_round.time, "monotonic", lambda: 100)
    monkeypatch.setattr(trivia_round, "log_warning", lambda *_args: None)
    error = SimpleNamespace(code="insufficient_quota", body={})

    trivia_round._record_api_failure(error)

    assert trivia_round.is_openai_available() is False
    assert trivia_round._api_failure_reason == "insufficient_quota"
    assert trivia_round._api_retry_after == 400


def test_ai_fallback_uses_local_synopsis(monkeypatch):
    calls = []
    data = {"synopsis": " ".join(f"word{i}" for i in range(25))}
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "currently_playing",
        {"data": data},
    )
    monkeypatch.setattr(lightning_manager.state.lightning, "current_light_mode", "trivia")
    monkeypatch.setattr(lightning_manager.title_overlay, "get_base_title", lambda _data: "Title")
    monkeypatch.setattr(lightning_manager.synopsis_overlay, "pick_synopsis", lambda: calls.append("pick"))
    monkeypatch.setattr(
        lightning_manager.synopsis_overlay,
        "get_light_synopsis_string",
        lambda words=1: "word0",
    )
    monkeypatch.setattr(
        lightning_manager.synopsis_overlay,
        "toggle_synopsis_overlay",
        lambda **kwargs: calls.append(kwargs["text"]),
    )

    assert lightning_manager._start_ai_round_fallback("trivia") == "synopsis"
    assert lightning_manager.state.lightning.current_light_mode == "synopsis"
    assert calls == ["pick", "word0"]


def test_fixed_trivia_starts_from_embedded_question(monkeypatch):
    question = "Which of these is a real anime title?"
    answer = "Goldfish Warning!"
    shown = []
    monkeypatch.setattr(
        lightning_manager.state.lightning,
        "fixed_current_round",
        {"trivia_question": question, "trivia_answer": answer},
    )
    monkeypatch.setattr(
        trivia_round,
        "get_cached_trivia",
        lambda _data: pytest.fail("fixed trivia consulted the AI cache"),
    )
    monkeypatch.setattr(trivia_round, "light_trivia_answer", None)
    monkeypatch.setattr(
        lightning_manager.synopsis_overlay, "synopsis_start_index", None
    )
    monkeypatch.setattr(
        lightning_manager.synopsis_overlay, "synopsis_split", None
    )
    monkeypatch.setattr(
        lightning_manager.synopsis_overlay,
        "toggle_synopsis_overlay",
        lambda **kwargs: shown.append(kwargs["text"]),
    )

    assert lightning_manager._start_trivia_overlay({}) is True
    assert trivia_round.light_trivia_answer == answer
    assert lightning_manager.synopsis_overlay.synopsis_split == question.split(" ")
    assert shown == ["Which"]


def test_ai_fallback_regular_round_is_skippable_and_audible(monkeypatch):
    calls = []
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "currently_playing",
        {"data": {"synopsis": ""}},
    )
    monkeypatch.setattr(lightning_manager.state.lightning, "current_light_mode", "emoji")
    monkeypatch.setattr(lightning_manager.title_overlay, "get_base_title", lambda _data: "A")
    monkeypatch.setattr(
        lightning_manager.audio_toggles,
        "toggle_mute",
        lambda *args: calls.append(("mute", args)),
    )
    monkeypatch.setattr(
        lightning_manager.blind_screen,
        "set_black_screen",
        lambda value: calls.append(("blind", value)),
    )
    monkeypatch.setattr(
        lightning_manager.osd_text,
        "top_info",
        lambda text: calls.append(("top", text)),
    )
    monkeypatch.setattr(
        lightning_manager.osd_text,
        "bottom_info",
        lambda text: calls.append(("bottom", text)),
    )

    assert lightning_manager._start_ai_round_fallback("emoji") == "regular"
    assert lightning_manager.state.lightning.current_light_mode == "regular"
    assert ("mute", (False, True)) in calls
    assert ("blind", False) in calls
