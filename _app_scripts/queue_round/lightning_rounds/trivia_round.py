"""Trivia lightning round — OpenAI-backed question/answer generator.

The trivia round asks a GPT-generated question about the anime; answers are
cached per MAL ID under ``ai_metadata`` so repeat plays reuse stored Q&A
without hitting the API. Cached trivia is also used as a fallback when no
API key is configured.
"""
from __future__ import annotations
from core.game_state import state
from core.app_logging import log_warning

import random
import re
import threading
import time

import openai

from _app_scripts.queue_round.lightning_rounds import synopsis_overlay
from _app_scripts.file.metadata import metadata_display
from _app_scripts.data import metadata_io


client = None
gpt_cutoff_year = 2025
light_trivia_answer = None
OPENAI_MODEL = "gpt-5.6-terra"
OPENAI_TIMEOUT_SECONDS = 8.0
OPENAI_FAILURE_COOLDOWN_SECONDS = 300
TRIVIA_REASONING_EFFORT = "low"
TRIVIA_MAX_OUTPUT_TOKENS = 300
MIN_REVEAL_WORDS_PER_SECOND = 5.0
_api_retry_after = 0.0
_api_failure_reason = None

_TITLE_GENERIC_WORDS = synopsis_overlay.TITLE_GENERIC_WORDS | {
    "anime", "episode", "film", "movie", "ona", "ova", "part", "season",
    "series", "special",
}


def _meaningful_words(text):
    return {
        match.group(0)
        for match in re.finditer(r"[^\W_]+", str(text or "").casefold())
        if len(match.group(0)) >= 4 and match.group(0) not in _TITLE_GENERIC_WORDS
    }


def answer_uses_title_clue(title, answer):
    """Return True when an answer repeats or expands a meaningful title word."""
    title_words = _meaningful_words(title)
    answer_words = _meaningful_words(answer)
    return any(
        title_word in answer_word or answer_word in title_word
        for title_word in title_words
        for answer_word in answer_words
    )


def is_acceptable_trivia(title, question, answer):
    if not question or not answer or str(answer).strip().casefold() == "none":
        return False
    if len(str(question).split()) > 40:
        return False
    return not answer_uses_title_clue(title, answer)


def get_reveal_duration(word_count, round_length, answer_time):
    """Return a trivia reveal duration that never drops below the minimum pace."""
    available_reveal_time = max(0.0, float(round_length) - float(answer_time))
    if word_count <= 0 or available_reveal_time <= 0:
        return 0.0
    minimum_pace_duration = word_count / MIN_REVEAL_WORDS_PER_SECOND
    return min(available_reveal_time, minimum_pace_duration)


def set_openai_client_key(api_key=None):
    global client, _api_retry_after, _api_failure_reason
    if api_key is None:
        api_key = state.config.OPENAI_API_KEY
    client = openai.OpenAI(
        api_key=api_key,
        timeout=OPENAI_TIMEOUT_SECONDS,
        max_retries=0,
    )
    _api_retry_after = 0.0
    _api_failure_reason = None


def is_openai_available():
    return bool(
        client
        and state.config.OPENAI_API_KEY
        and time.monotonic() >= _api_retry_after
    )


def _record_api_failure(error):
    global _api_retry_after, _api_failure_reason
    code = getattr(error, "code", None)
    if not code and isinstance(getattr(error, "body", None), dict):
        code = error.body.get("code")
    _api_failure_reason = code or type(error).__name__
    _api_retry_after = time.monotonic() + OPENAI_FAILURE_COOLDOWN_SECONDS
    log_warning(
        "OpenAI request failed (%s, retry suppressed for %ss): %s",
        _api_failure_reason,
        OPENAI_FAILURE_COOLDOWN_SECONDS,
        error,
    )


def get_ai_metadata_entry(mal_id, create=False):
    """Return an AI metadata entry across JSON string/int MAL key formats."""
    if not mal_id:
        return None
    for key in (str(mal_id), mal_id):
        entry = state.metadata.ai_metadata.get(key)
        if isinstance(entry, dict):
            return entry
    if create:
        return state.metadata.ai_metadata.setdefault(str(mal_id), {})
    return None


def get_cached_trivia(data):
    entry = get_ai_metadata_entry(data.get("mal")) or {}
    title = metadata_display.get_display_title(data)
    stored_trivia = entry.get("trivia") or []
    if not isinstance(stored_trivia, list):
        stored_trivia = [stored_trivia]
    elif len(stored_trivia) >= 2 and all(
        isinstance(value, str) for value in stored_trivia[:2]
    ):
        stored_trivia = [stored_trivia]
    valid = [
        item
        for item in stored_trivia
        if isinstance(item, (list, tuple))
        and len(item) >= 2
        and is_acceptable_trivia(title, item[0], item[1])
    ]
    return list(random.choice(valid)[:2]) if valid else None


def extract_response_text(response):
    texts = []
    for item in response.output:
        if hasattr(item, "content") and item.content:
            for c in item.content:
                if hasattr(c, "text") and c.text:
                    texts.append(c.text)
    return "\n".join(texts) if texts else None


def generate_anime_trivia(data, display=False, allow_api=True):
    if state.lightning.fixed_current_round:
        trivia = state.lightning.fixed_current_round.get("trivia_question", "No trivia found.")
        trivia_answer = state.lightning.fixed_current_round.get("trivia_answer", "None")
        return trivia, trivia_answer

    def no_trivia_available():
        return "No trivia available.", "None"

    mal_id = data.get("mal")
    cached_trivia = get_cached_trivia(data)
    entry = get_ai_metadata_entry(mal_id) or {}
    stored_trivia = entry.get("trivia") or []
    if not isinstance(stored_trivia, list):
        stored_trivia = [stored_trivia] if stored_trivia else []
    elif len(stored_trivia) >= 2 and all(
        isinstance(value, str) for value in stored_trivia[:2]
    ):
        stored_trivia = [stored_trivia]
    stored_trivia = [
        item
        for item in stored_trivia
        if isinstance(item, (list, tuple)) and len(item) >= 2
    ]

    if not allow_api or not is_openai_available():
        if cached_trivia:
            return cached_trivia
        return "No 'openai_api_key' set in config file.", "None"

    title = metadata_display.get_display_title(data)
    year = int(data.get("season", "9999")[-4:])

    media_type = "anime"
    if metadata_display.is_game(data):
        media_type = "game"

    prompt = f"""
        Write one fair, medium-difficulty, spoiler-light trivia question about
        the {media_type} "{title}" ({year}). Players already see its title and
        year, so the answer must require specific knowledge of the work.

        Reject a candidate if:
        - Its answer can be guessed from the title, subtitle, genre, central
          premise, or a common title association.
        - Its answer repeats, contains, expands, translates, paraphrases, or is
          a close synonym of a meaningful word or concept in the title.
        - Its answer is a character or person's name, song, artist, title, or
          episode count.
        - The question is ambiguous, subjective, generic, trivial, or reveals a
          major spoiler.

        Bad example for "Death Note": asking what object must be touched and
        answering "a notebook." "Notebook" is effectively revealed by "Note."

        Silently consider three candidates and return only the strongest one
        that passes every rule. The question must be under 40 words, and the
        answer must be concise rather than a full sentence.

        Start the question exactly with: "In {title} ({year}),"
        Return exactly:
        Question: <question>
        Answer: <answer>
        """

    if year > gpt_cutoff_year:
        if len((data.get("synopsis") or "").split()) <= 40:
            return no_trivia_available()
        short_synopsis = data["synopsis"][:300].rsplit('.', 1)[0] + '.'
        prompt += f"""
        The anime may be too recent, so here's a synopsis you can use for context:
        [{short_synopsis}]
        """
    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=prompt,
            reasoning={"effort": TRIVIA_REASONING_EFFORT},
            max_output_tokens=TRIVIA_MAX_OUTPUT_TOKENS,
        )

        content = extract_response_text(response)
        if display:
            print(content)
        if content and "Question:" in content and "Answer:" in content:
            question, answer = parse_trivia_response(content)
            if not is_acceptable_trivia(title, question, answer):
                return no_trivia_available()
            if mal_id and answer and all(answer != a for _, a in stored_trivia):
                get_ai_metadata_entry(mal_id, create=True).setdefault("trivia", []).append([question, answer])
                metadata_io.save_metadata()
            return question, answer
        else:
            return no_trivia_available()
    except Exception as e:
        _record_api_failure(e)
        if display:
            print(e)
        return no_trivia_available()


def parse_trivia_response(response_text):
    lines = response_text.split("\n")
    q = next((line[9:] for line in lines if line.startswith("Question:")), None).strip()
    a = next((line[7:] for line in lines if line.startswith("Answer:")), None).strip()
    return q, a


def set_light_trivia(data=None, queue=False, trivia_data=None, allow_api=True):
    global light_trivia_answer
    if trivia_data:
        question, answer = trivia_data[0], trivia_data[1]
    else:
        if not data:
            data = state.playback.currently_playing.get("data")
        question, answer = generate_anime_trivia(data, allow_api=allow_api)
    if queue:
        return [question, answer]
    else:
        synopsis_overlay.synopsis_start_index = 0
        synopsis_overlay.synopsis_split = question.split(" ")
        light_trivia_answer = answer


def generate_anime_trivia_async(data):
    """Run the manual trivia action without blocking Tk's main loop."""
    thread = threading.Thread(
        target=generate_anime_trivia,
        args=(data, True),
        daemon=True,
        name="openai-trivia",
    )
    thread.start()
    return thread
