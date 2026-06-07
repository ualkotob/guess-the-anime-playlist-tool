"""Trivia lightning round — OpenAI-backed question/answer generator.

The trivia round asks a GPT-generated question about the anime; answers are
cached per MAL ID under ``ai_metadata`` so repeat plays reuse stored Q&A
without hitting the API. Cached trivia is also used as a fallback when no
API key is configured.
"""
from __future__ import annotations
from core.game_state import state

import random

import openai

from _app_scripts.queue_round.lightning_rounds import synopsis_overlay
from _app_scripts.file.metadata import metadata_display
from _app_scripts.data import metadata_io


client = None
gpt_cutoff_year = 2023
light_trivia_answer = None


def set_openai_client_key(api_key=None):
    global client
    if api_key is None:
        api_key = state.config.OPENAI_API_KEY
    client = openai.OpenAI(api_key=api_key)


def extract_response_text(response):
    texts = []
    for item in response.output:
        if hasattr(item, "content") and item.content:
            for c in item.content:
                if hasattr(c, "text") and c.text:
                    texts.append(c.text)
    return "\n".join(texts) if texts else None


def generate_anime_trivia(data, display=False):
    if state.lightning.fixed_current_round:
        trivia = state.lightning.fixed_current_round.get("trivia_question", "No trivia found.")
        trivia_answer = state.lightning.fixed_current_round.get("trivia_answer", "None")
        return trivia, trivia_answer

    def no_trivia_available():
        return "No trivia available.", "None"

    mal_id = data.get("mal")
    stored_trivia = state.metadata.ai_metadata.get(mal_id, {}).get("trivia") if mal_id else []
    if not isinstance(stored_trivia, list):
        stored_trivia = [stored_trivia] if stored_trivia else []

    if not client:
        if stored_trivia:
            question, answer = random.choice(stored_trivia)
            return question, answer
        return "No 'openai_api_key' set in config file.", "None"

    title = metadata_display.get_display_title(data)
    year = int(data.get("season", "9999")[-4:])

    media_type = "anime"
    if metadata_display.is_game(data):
        media_type = "game"

    prompt = f"""
        Generate a trivia question and answer about the {media_type} "{title}" ({year}).
        - The question must be under 40 words.
        - Start the question with: "In {title} ({year}),"
        - Avoid questions with ambiguous answers.
        - Avoid spoilers and generic questions like "Who is the main character?"
        - Do NOT make the answer a character name.
        - Do NOT use character names or any words from the anime's title in the answer.
        - Avoid questions where the answer is "Who is ___" or "What is the name of ___".
        - Do NOT make the answer a person's name.
        - Do NOT make the answer a song name or artist.
        - Do NOT ask about the number of episodes.
        - The answer should be concise and direct (not a full sentence).

        Format:
        Question: <your question>
        Answer: <your answer>
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
            model="gpt-4-turbo",
            input=prompt
        )

        content = extract_response_text(response)
        if display:
            print(content)
        if content and "Question:" in content and "Answer:" in content:
            question, answer = parse_trivia_response(content)
            if mal_id and answer and all(answer != a for _, a in stored_trivia):
                state.metadata.ai_metadata.setdefault(mal_id, {}).setdefault("trivia", []).append([question, answer])
                metadata_io.save_metadata()
            return question, answer
        else:
            return no_trivia_available()
    except Exception as e:
        if display:
            print(e)
        return no_trivia_available()


def parse_trivia_response(response_text):
    lines = response_text.split("\n")
    q = next((line[9:] for line in lines if line.startswith("Question:")), None).strip()
    a = next((line[7:] for line in lines if line.startswith("Answer:")), None).strip()
    return q, a


def set_light_trivia(data=None, queue=False, trivia_data=None):
    global light_trivia_answer
    if trivia_data:
        question, answer = trivia_data[0], trivia_data[1]
    else:
        if not data:
            data = state.playback.currently_playing.get("data")
        question, answer = generate_anime_trivia(data)
    if queue:
        return [question, answer]
    else:
        synopsis_overlay.synopsis_start_index = 0
        synopsis_overlay.synopsis_split = question.split(" ")
        light_trivia_answer = answer
