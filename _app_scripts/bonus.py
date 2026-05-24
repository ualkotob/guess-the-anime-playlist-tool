"""Bonus questions module for Guess the Anime!

Owns:
  BONUS_SETTINGS_DEFAULT   — default point/config values for every bonus type
  guessing_extra           — None | str (active bonus question type)
  showing_bonus_answer     — bool (character bonus is in reveal state)
  bonus_chars              — list of character tuples for the active char round
  bonus_correct_indices    — list of int indices of correct characters
  bonus_overlay_window     — None | True (sentinel for character OSD visibility)
  _pending_bonus_answers   — list of {name, answer} dicts from web server
  _bonus_correct_answer    — the correct answer for the active bonus question
  _yt_bonus_*              — YouTube-bonus-template state
  used_multiple_titles     — dict tracking how many times each series appeared
"""

import random
import re
import threading
from datetime import datetime

from . import web_server
from . import utils
from core.game_state import state

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

# ---------------------------------------------------------------------------
# Module-owned state
# ---------------------------------------------------------------------------

BONUS_SETTINGS_DEFAULT = {
    "year":       {"points_close": 1.0, "points_exact": 2.0, "lightning_points_close": 1.0, "lightning_points_exact": 2.0, "included_in_random": True, "show_in_menu": True},
    "members":    {"points_close": 1.0, "points_exact": 2.0, "lightning_points_close": 1.0, "lightning_points_exact": 2.0, "exact_pct": 0.10, "included_in_random": True, "show_in_menu": True},
    "popularity": {"points_close": 1.0, "points_exact": 2.0, "lightning_points_close": 1.0, "lightning_points_exact": 2.0, "exact_pct": 0.05, "included_in_random": True, "show_in_menu": True},
    "score":      {"points_close": 1.0, "points_exact": 2.0, "lightning_points_close": 1.0, "lightning_points_exact": 2.0, "included_in_random": True, "show_in_menu": True},
    "multiple":   {"points": 2.0, "lightning_points": 1.0, "included_in_random": True, "show_in_menu": True},
    "studio":     {"points": 1.0, "lightning_points": 1.0, "included_in_random": True, "show_in_menu": True},
    "artist":     {"points": 1.0, "lightning_points": 1.0, "included_in_random": True, "show_in_menu": True},
    "song":       {"points": 1.0, "lightning_points": 1.0, "included_in_random": True, "show_in_menu": True},
    "tags":       {"points_per_tag": 1.0, "lightning_points_per_tag": 1.0, "included_in_random": True, "show_in_menu": True},
    "characters": {"num_correct": 1, "points_per_correct": 1.0, "lightning_points_per_correct": 1.0, "scale": 1.0, "included_in_random": False, "show_in_menu": True},
    "freeform":   {"points": 1.0, "lightning_points": 1.0, "included_in_random": False, "show_in_menu": True},
    "buzzer":     {"popup": False, "player_buzz_popup": True, "sound": True, "sound_volume": 1.0, "included_in_random": False, "show_in_menu": True,
                   "player_buzz_popup_properties": {
                       "max_alpha": 0.9,
                       "fade_in_ms": 220,
                       "hold_ms": 2400,
                       "fade_out_ms": 350,
                       "steps": 18,
                       "rise_px": 50,
                       "push_ms": 220,
                       "push_steps": 18,
                       "margin": 40,
                       "gap": 10,
                   }},
    "random":     {"no_repeat": True, "cycle_all": True},
}

guessing_extra = None
showing_bonus_answer = False

_yt_bonus_template_questions = []
_yt_bonus_template_triggered = set()
_yt_bonus_template_scored = set()
_yt_bonus_current_question = None
_yt_bonus_pts = 1.0

used_multiple_titles = {}

bonus_overlay_window = None
bonus_chars = []
bonus_correct_indices = []
_bonus_chars_img_overlay = None
_bonus_chars_current = []
_bonus_chars_reveal = False

_pending_bonus_answers = []
_bonus_correct_answer = None

# ---------------------------------------------------------------------------
# Context (injected at startup)
# ---------------------------------------------------------------------------

_root = None
_player = None
_get_light_mode = None
_get_light_round_started = None
_get_fixed_current_round = None
_get_coming_up_osd_box_h = None
_get_overlay_background_color = None
# cached_images is read directly from state.playback.cached_images

_toggle_coming_up_popup = None
_toggle_mc_choices_overlay = None
_send_scoreboard_command = None
_evaluate_and_submit_fn = None
_push_web_toggles_fn = None
_refresh_popout_toggles_fn = None
_register_mpv_tracked_window = None
_unregister_mpv_tracked_window = None

_get_display_title = None
_get_base_title = None
_get_tags = None
_get_all_tags = None
_get_all_studios = None
_series_list = None
_series_set = None
_series_overlap = None
_series_primary = None
_get_series_popularity = None
_is_game = None
_aired_to_season_year = None
_get_lowest_parameter = None
_get_highest_parameter = None
_load_pil_image_from_url = None
_get_ass_font = None

# Metadata-cluster dicts (anime_metadata, file_metadata, anilist_metadata,
# anidb_metadata, directory_files) are read directly from `state.metadata.*`.


def set_context(
    root,
    player,
    get_light_mode,
    get_light_round_started,
    get_fixed_current_round,
    get_coming_up_osd_box_h,
    get_overlay_background_color,
    toggle_coming_up_popup,
    toggle_mc_choices_overlay,
    send_scoreboard_command,
    evaluate_and_submit_fn,
    push_web_toggles_fn,
    refresh_popout_toggles_fn,
    register_mpv_tracked_window,
    unregister_mpv_tracked_window,
    get_display_title,
    get_base_title,
    get_tags,
    get_all_tags,
    get_all_studios,
    series_list,
    series_set,
    series_overlap,
    series_primary,
    get_series_popularity,
    is_game,
    aired_to_season_year,
    get_lowest_parameter,
    get_highest_parameter,
    load_pil_image_from_url,
    get_ass_font,
):
    global _root, _player
    global _get_light_mode, _get_light_round_started
    global _get_fixed_current_round
    global _get_coming_up_osd_box_h, _get_overlay_background_color
    global _toggle_coming_up_popup, _toggle_mc_choices_overlay, _send_scoreboard_command
    global _evaluate_and_submit_fn, _push_web_toggles_fn, _refresh_popout_toggles_fn
    global _register_mpv_tracked_window, _unregister_mpv_tracked_window
    global _get_display_title, _get_base_title, _get_tags, _get_all_tags, _get_all_studios
    global _series_list, _series_set, _series_overlap, _series_primary, _get_series_popularity
    global _is_game, _aired_to_season_year, _get_lowest_parameter, _get_highest_parameter
    global _load_pil_image_from_url, _get_ass_font

    _root = root
    _player = player
    _get_light_mode = get_light_mode
    _get_light_round_started = get_light_round_started
    _get_fixed_current_round = get_fixed_current_round
    _get_coming_up_osd_box_h = get_coming_up_osd_box_h
    _get_overlay_background_color = get_overlay_background_color
    _toggle_coming_up_popup = toggle_coming_up_popup
    _toggle_mc_choices_overlay = toggle_mc_choices_overlay
    _send_scoreboard_command = send_scoreboard_command
    _evaluate_and_submit_fn = evaluate_and_submit_fn
    _push_web_toggles_fn = push_web_toggles_fn
    _refresh_popout_toggles_fn = refresh_popout_toggles_fn
    _register_mpv_tracked_window = register_mpv_tracked_window
    _unregister_mpv_tracked_window = unregister_mpv_tracked_window
    _get_display_title = get_display_title
    _get_base_title = get_base_title
    _get_tags = get_tags
    _get_all_tags = get_all_tags
    _get_all_studios = get_all_studios
    _series_list = series_list
    _series_set = series_set
    _series_overlap = series_overlap
    _series_primary = series_primary
    _get_series_popularity = get_series_popularity
    _is_game = is_game
    _aired_to_season_year = aired_to_season_year
    _get_lowest_parameter = get_lowest_parameter
    _get_highest_parameter = get_highest_parameter
    _load_pil_image_from_url = load_pil_image_from_url
    _get_ass_font = get_ass_font


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_pt(v):
    """Format a point value as a display string, e.g. 1.0 → '1 PT', 2.0 → '2 PTs'."""
    n = int(v) if v == int(v) else v
    return f"{n} PT" if v <= 1 else f"{n} PTs"


def setup_for_youtube(questions):
    """Reset YouTube bonus template state for a new video or after saving.

    *questions* is the resolved list from youtube_control.load_bonus_template().
    Call before playback starts so time-triggered questions fire from a clean slate.
    """
    global _yt_bonus_template_questions, _yt_bonus_template_triggered
    global _yt_bonus_template_scored, _yt_bonus_current_question
    _yt_bonus_template_questions = questions
    _yt_bonus_template_triggered = set()
    _yt_bonus_template_scored = set()
    _yt_bonus_current_question = None


# ---------------------------------------------------------------------------
# Core bonus question dispatcher
# ---------------------------------------------------------------------------

def guess_extra(extra=None):
    global guessing_extra, showing_bonus_answer, bonus_chars, bonus_correct_indices, _bonus_correct_answer
    ROUND_PREFIX = "BONUS?: "

    def reset_bonus(destory_characters=True):
        global guessing_extra, showing_bonus_answer
        # Flush any silent (not formally submitted) selections into the answer queue
        # and _pending_bonus_answers BEFORE scoring, so they count.
        web_server.flush_pending_selections()
        for _entry in web_server.get_answers():
            print(f"[WEB ANSWER] {_entry['name']}: {_entry['answer']}")
            _already = {e['name'] for e in _pending_bonus_answers}
            if guessing_extra and _entry['name'] not in _already:
                _pending_bonus_answers.append(_entry)
                _send_scoreboard_command(f"[SUBMITTED]{_entry['name']}")
        _evaluate_and_submit_fn()
        if destory_characters:
            guessing_extra = None
            destroy_bonus_characters()
            showing_bonus_answer = False
        _toggle_coming_up_popup(False, ROUND_PREFIX)
        web_server.clear_question()
        # Hide the web timer when the bonus closes
        if web_server.is_running():
            web_server.clear_timer()
        _send_scoreboard_command("[CLEAR_SUBMITTED]")

    if extra:
        if extra == guessing_extra:
            if extra == "characters" and bonus_overlay_window and not showing_bonus_answer:
                showing_bonus_answer = True
                _toggle_coming_up_popup(False, ROUND_PREFIX)
                show_bonus_characters(bonus_chars, reveal_correct=True)
                reset_bonus(destory_characters=False)
                return
            else:
                reset_bonus()
        else:
            if guessing_extra == "buzzer":
                _send_scoreboard_command("[CLEAR_BUZZ_ORDER]")
            guessing_extra = extra
            _pending_bonus_answers.clear()
        _is_light_mode = _get_light_mode() or _get_light_round_started()
        bonus_settings = state.playback.bonus_settings
        currently_playing = state.playback.currently_playing
        if guessing_extra == "year":
            _bs_year = bonus_settings.get("year", BONUS_SETTINGS_DEFAULT["year"])
            _bs_pt_close = _bs_year["lightning_points_close" if _is_light_mode else "points_close"]
            _bs_pt_exact = _bs_year["lightning_points_exact" if _is_light_mode else "points_exact"]
            _toggle_coming_up_popup(True,
                                ROUND_PREFIX + "Guess The Year",
                                ("Only 1 guess per person, no repeats.\n"
                                f"+{_fmt_pt(_bs_pt_close)} for closest guess. "
                                f"+{_fmt_pt(_bs_pt_exact)} if exact year."),
                                up_next=False)
            web_server.push_question("Guess The Year This Anime Aired",
                                     "Only 1 guess per person, no repeats.",
                                     year={"min": 1900, "max": datetime.now().year, "initial": 2000})
            _data = currently_playing.get("data") or {}
            _year = None
            _season = _data.get("season", "")
            _tail = _season[-4:] if len(_season) >= 4 else ""
            if _tail.isdigit():
                _year = int(_tail)
            if not _year:
                _aired = _data.get("aired")
                if _aired:
                    _sy = _aired_to_season_year(_aired)
                    _tail = _sy[-4:]
                    if _tail.isdigit():
                        _year = int(_tail)
            _bonus_correct_answer = _year
        elif guessing_extra == "members":
            _bs_members = bonus_settings.get("members", BONUS_SETTINGS_DEFAULT["members"])
            _bs_pt_close = _bs_members["lightning_points_close" if _is_light_mode else "points_close"]
            _bs_pt_exact = _bs_members["lightning_points_exact" if _is_light_mode else "points_exact"]
            _exact_pct = int(_bs_members.get("exact_pct", 0.10) * 100)
            _toggle_coming_up_popup(True,
                                ROUND_PREFIX + "Guess The Members",
                                ("Members are users who added the anime to their list on MyAnimeList.\n"
                                 "EG: Death Note has over 4 million. Only 1 guess per person, no repeats.\n"
                                f"+{_fmt_pt(_bs_pt_close)} for closest guess. "
                                f"+{_fmt_pt(_bs_pt_exact)} if your guess is within ±{_exact_pct}% of correct."),
                                up_next=False)
            web_server.push_question("Guess The # Of Members",
                                     "How many users added this anime to their list on MyAnimeList?",
                                     stepper={"initial": 0, "min": 0, "max": 10000000,
                                              "steps": [
                                                  {"label": "-5 000", "delta": -5000},
                                                  {"label": "-10 000",   "delta": -10000},
                                                  {"label": "-50 000",    "delta": -50000},
                                                  {"label": "+5 000",   "delta": 5000},
                                                  {"label": "+10 000",    "delta": +10000},
                                                  {"label": "+50 000",    "delta": 50000},
                                                  {"label": "CLEAR", "delta": -100000000},
                                                  {"label": "+100 000",   "delta": 100000},
                                                  {"label": "+500 000", "delta": 500000},
                                              ]})
            _bonus_correct_answer = (currently_playing.get("data") or {}).get("members")
        elif guessing_extra == "popularity":
            _bs_pop = bonus_settings.get("popularity", BONUS_SETTINGS_DEFAULT["popularity"])
            _bs_pt_close = _bs_pop["lightning_points_close" if _is_light_mode else "points_close"]
            _bs_pt_exact = _bs_pop["lightning_points_exact" if _is_light_mode else "points_exact"]
            _exact_pct = int(_bs_pop.get("exact_pct", 0.10) * 100)
            _toggle_coming_up_popup(True,
                                ROUND_PREFIX + "Guess The Popularity Rank",
                                ("The rank is based on users who added the anime to their list on MyAnimeList.\n"
                                 f"Ranks range from {_get_lowest_parameter('popularity')} to {_get_highest_parameter('popularity')}. "
                                 "Only 1 guess per person, no repeats.\n"
                                f"+{_fmt_pt(_bs_pt_close)} for closest guess. "
                                f"+{_fmt_pt(_bs_pt_exact)} if your guess is within ±{_exact_pct}% of correct."),
                                up_next=False)
            web_server.push_question("Guess The Popularity Rank",
                                     "Only 1 guess per person, no repeats.",
                                     rank_slider={"initial": 1000,
                                              "min": 1, "max": _get_highest_parameter('popularity') or 9999})
            _bonus_correct_answer = (currently_playing.get("data") or {}).get("popularity")
        elif guessing_extra == "score":
            _bs_score = bonus_settings.get("score", BONUS_SETTINGS_DEFAULT["score"])
            _bs_pt_close = _bs_score["lightning_points_close" if _is_light_mode else "points_close"]
            _bs_pt_exact = _bs_score["lightning_points_exact" if _is_light_mode else "points_exact"]
            _toggle_coming_up_popup(True,
                                ROUND_PREFIX + "Guess The Score",
                                ("Scores taken from MyAnimeList and range from 0.0 to 10.0.\n"
                                 "Only 1 guess per person, no repeats.\n"
                                f"+{_fmt_pt(_bs_pt_close)} for closest guess. "
                                f"+{_fmt_pt(_bs_pt_exact)} if exact score(rounded to nearest 0.1)."),
                                up_next=False)
            web_server.push_question("Guess The MyAnimeList Score",
                                     "Only 1 guess per person, no repeats.",
                                     drum={"min": 0.0, "max": 10.0, "step": 0.1, "decimals": 1, "initial": 7.0, "reverse": True})
            _bonus_correct_answer = (currently_playing.get("data") or {}).get("score")
        elif guessing_extra == "tags":
            data = currently_playing.get("data")
            correct_tags = _get_tags(data) if data else []
            num_correct = len(correct_tags)
            if num_correct > 1:
                tags_label = str(num_correct) + " Tags"
            else:
                tags_label = str(num_correct) + " Tag"
            random_tags = get_random_tags()
            tags_array = utils.split_array(random_tags)
            _bs_tags = bonus_settings.get("tags", BONUS_SETTINGS_DEFAULT["tags"])
            _bs_pt_tag = _bs_tags["lightning_points_per_tag" if _is_light_mode else "points_per_tag"]
            _toggle_coming_up_popup(True,
                                ROUND_PREFIX + "Guess The " + tags_label,
                                (f"Pick up to {num_correct} tags. +{_fmt_pt(_bs_pt_tag)} per correct, -{_fmt_pt(_bs_pt_tag)} per wrong.\n\n"
                                "[" + "] [".join(tags_array[0]) + "]\n[" + "] [".join(tags_array[1])) + "]",
                                up_next=False)
            web_server.push_question(
                f"Guess The {tags_label}",
                f"Pick up to {num_correct} tags. +{_fmt_pt(_bs_pt_tag)} per correct, -{_fmt_pt(_bs_pt_tag)} per wrong.",
                tags=random_tags,
                tags_max=num_correct)
            _bonus_correct_answer = correct_tags
        elif guessing_extra == "multiple":
            data = currently_playing.get("data")
            titles = get_random_titles()
            _bs_multiple = bonus_settings.get("multiple", BONUS_SETTINGS_DEFAULT["multiple"])
            _multiple_pt = _bs_multiple["lightning_points" if _is_light_mode else "points"]
            _toggle_coming_up_popup(True,
                                ROUND_PREFIX + "Guess The Anime",
                                (f"Only one guess. +{_fmt_pt(_multiple_pt)} if correct.\n\n"
                                f"[A] {titles[0]}\n[B] {titles[1]}\n"
                                f"[C] {titles[2]}\n[D] {titles[3]}"),
                                up_next=False)
            web_server.push_question("Guess The Anime", "Which anime is this?",
                                     choices=titles)
            _bonus_correct_answer = _get_display_title(currently_playing.get("data") or {})
        elif guessing_extra == "characters":
            _bs_chars = bonus_settings.get("characters", BONUS_SETTINGS_DEFAULT["characters"])
            _bs_num_correct = int(_bs_chars.get("num_correct", BONUS_SETTINGS_DEFAULT["characters"]["num_correct"]))
            _bs_pt_char = float(_bs_chars.get("lightning_points_per_correct" if _is_light_mode else "points_per_correct",
                                              BONUS_SETTINGS_DEFAULT["characters"]["lightning_points_per_correct" if _is_light_mode else "points_per_correct"]))
            _char_word = "character" if _bs_num_correct == 1 else "characters"
            _char_verb = "is" if _bs_num_correct == 1 else "are"
            _toggle_coming_up_popup(True,
                                ROUND_PREFIX + f"Guess The {_char_word.title()}",
                                f"{_bs_num_correct} out of 6 characters {_char_verb} from this anime.\n" +
                                (f"+{_fmt_pt(_bs_pt_char)} if correct." if _bs_num_correct == 1 else f"+{_fmt_pt(_bs_pt_char)} per correct character."),
                                up_next=False)
            bonus_chars, bonus_correct_indices = pick_bonus_characters()
            # Build web payload: {label, image_url} for each card
            _char_choices = [
                {
                    "label": chr(65 + i),
                    "image_url": ("https://cdn-eu.anidb.net/images/main/" + c[2]) if len(c) > 2 and c[2] else "",
                }
                for i, c in enumerate(bonus_chars)
            ]
            _correct_labels = [chr(65 + i) for i in bonus_correct_indices]
            _bonus_correct_answer = _correct_labels  # list of correct letter(s)
            web_server.push_question(
                f"Guess The {_char_word.title()}",
                f"Pick {_bs_num_correct} out of {len(bonus_chars)}. " +
                (f"+{_fmt_pt(_bs_pt_char)} if correct." if _bs_num_correct == 1 else f"+{_fmt_pt(_bs_pt_char)} per correct."),
                character_choices=_char_choices,
                character_picks=_bs_num_correct,
            )

            def worker():
                show_bonus_characters(bonus_chars)
            threading.Thread(target=worker, daemon=True).start()
        elif guessing_extra == "studio":
            data = currently_playing.get("data") or {}
            studios = data.get("studios", [])
            correct_studio = studios[0] if studios else "Unknown"

            # Weighted list: studios can repeat, so big studios are more likely
            weighted_studios = [s for s in _get_all_studios(state.metadata.directory_files, False, True) if s != correct_studio]

            # Build unique distractors, weighted by frequency
            distractors = []
            used = set([correct_studio])
            attempts = 0
            while len(distractors) < 3 and attempts < 100:
                pick = random.choice(weighted_studios or ["Unknown"])
                if pick == "Unknown":
                    distractors = ["Unknown"] * 3
                    break
                if pick not in used:
                    distractors.append(pick)
                    used.add(pick)
                attempts += 1

            choices = [correct_studio] + distractors
            random.shuffle(choices)

            _bs_studio = bonus_settings.get("studio", BONUS_SETTINGS_DEFAULT["studio"])
            _bs_pt_studio = _bs_studio["lightning_points" if _is_light_mode else "points"]
            _toggle_coming_up_popup(True,
                ROUND_PREFIX + "Guess The Studio",
                (f"Which studio made this anime?\n"
                f"Only one guess. +{_fmt_pt(_bs_pt_studio)} if correct.\n\n"
                f"[A] {choices[0]}\n[B] {choices[1]}\n[C] {choices[2]}\n[D] {choices[3]}"),
                up_next=False)
            web_server.push_question("Guess The Studio", "Which studio made this anime?",
                                     choices=choices)
            _bonus_correct_answer = correct_studio
        elif guessing_extra == "artist":
            data = currently_playing.get("data") or {}
            slug = data.get("slug")
            theme = None
            for song in data.get("songs", []):
                if song.get("slug") == slug:
                    theme = song
                    break
            correct_artist = theme.get("artist", ["Unknown"])[0] if theme else "Unknown"

            # Build weighted list of distractor artists from other anime
            weighted_artists = []
            data_tags = set(_get_tags(data))
            for anime in state.metadata.anime_metadata.values():
                if anime.get("title") == data.get("title"):
                    continue
                anime_tags = set(_get_tags(anime))
                tag_overlap = len(data_tags & anime_tags)
                for song in anime.get("songs", []):
                    for artist in song.get("artist", []):
                        if artist and artist != correct_artist:
                            weighted_artists.extend([artist] * (1 + tag_overlap))

            # Pick 3 unique distractors, weighted by tag similarity
            distractors = []
            used = set([correct_artist])
            attempts = 0
            while len(distractors) < 3 and attempts < 100:
                if not weighted_artists:
                    break
                pick = random.choice(weighted_artists)
                if pick not in used:
                    distractors.append(pick)
                    used.add(pick)
                attempts += 1

            while len(distractors) < 3:
                distractors.append("Unknown")

            choices = [correct_artist] + distractors
            random.shuffle(choices)

            _bs_artist = bonus_settings.get("artist", BONUS_SETTINGS_DEFAULT["artist"])
            _bs_pt_artist = _bs_artist["lightning_points" if _is_light_mode else "points"]
            _toggle_coming_up_popup(True,
                ROUND_PREFIX + "Guess The Artist/Band",
                (f"Which artist/band performed this song in this anime?\n"
                f"Only one guess. +{_fmt_pt(_bs_pt_artist)} if correct.\n\n"
                f"[A] {choices[0]}\n[B] {choices[1]}\n[C] {choices[2]}\n[D] {choices[3]}"),
                up_next=False)
            web_server.push_question("Guess The Artist/Band", "Which artist/band performed this song in this anime?",
                                     choices=choices)
            _bonus_correct_answer = correct_artist
        elif guessing_extra == "song":
            data = currently_playing.get("data") or {}
            slug = data.get("slug")
            theme = None
            for song in data.get("songs", []):
                if song.get("slug") == slug:
                    theme = song
                    break
            correct_title = theme.get("title", "Unknown") if theme else "Unknown"
            correct_artist = theme.get("artist", ["Unknown"])[0] if theme and theme.get("artist") else "Unknown"

            # 1. Gather all songs by the same artist (excluding the correct song)
            same_artist_titles = []
            for anime in state.metadata.anime_metadata.values():
                if anime.get("title") == data.get("title"):
                    continue
                for song in anime.get("songs", []):
                    if song.get("artist") and correct_artist in song.get("artist") and song.get("title") and song.get("title") != correct_title:
                        same_artist_titles.append(song.get("title"))

            # 2. Gather weighted titles by tag overlap (excluding correct title and same artist titles)
            weighted_titles = []
            data_tags = set(_get_tags(data))
            for anime in state.metadata.anime_metadata.values():
                if anime.get("title") == data.get("title"):
                    continue
                anime_tags = set(_get_tags(anime))
                tag_overlap = len(data_tags & anime_tags)
                for song in anime.get("songs", []):
                    title = song.get("title")
                    if title and title != correct_title and title not in same_artist_titles:
                        weighted_titles.extend([title] * (1 + tag_overlap))

            distractors = []
            used = set([correct_title])
            if same_artist_titles:
                pick = random.choice(same_artist_titles)
                distractors.append(pick)
                used.add(pick)
            # Fill remaining slots from weighted titles
            attempts = 0
            while len(distractors) < 3 and attempts < 100:
                if not weighted_titles:
                    break
                pick = random.choice(weighted_titles)
                if pick not in used and pick:
                    distractors.append(pick)
                    used.add(pick)
                attempts += 1
            while len(distractors) < 3:
                distractors.append("Unknown")

            choices = [correct_title] + distractors
            random.shuffle(choices)

            _bs_song = bonus_settings.get("song", BONUS_SETTINGS_DEFAULT["song"])
            _bs_pt_song = _bs_song["lightning_points" if _is_light_mode else "points"]
            _toggle_coming_up_popup(True,
                ROUND_PREFIX + "Guess The Song Title",
                (f"Which song is played in this anime?\n"
                f"Only one guess. +{_fmt_pt(_bs_pt_song)} if correct.\n\n"
                f"[A] {choices[0]}\n[B] {choices[1]}\n[C] {choices[2]}\n[D] {choices[3]}"),
                up_next=False)
            web_server.push_question("Guess The Song Title", "Which song is played in this anime?",
                                     choices=choices)
            _bonus_correct_answer = correct_title
        elif guessing_extra == "fixed_mc":
            _fr = _get_fixed_current_round() or {}
            correct_answer = _fr.get("trivia_answer", "")
            _other = [_fr.get("mc_choice_2", ""), _fr.get("mc_choice_3", ""), _fr.get("mc_choice_4", "")]
            _other = [c for c in _other if c.strip()]
            choices = [correct_answer] + _other
            random.shuffle(choices)
            _toggle_mc_choices_overlay(choices=choices, correct=correct_answer)
            web_server.push_question(
                _fr.get("trivia_header", "Trivia") or "Trivia",
                _fr.get("trivia_question", "") or "",
                choices=choices)
            _bonus_correct_answer = correct_answer
        elif guessing_extra == "yt_bonus":
            _q = _yt_bonus_current_question or {}
            _q_answer = _q.get("answer", "")
            _q_choices = _q.get("choices", [])
            if not _q_choices:
                _q_choices = [_q_answer]
            _q_text = _q.get("question", "")
            _q_header = _q.get("header", "") or "Bonus Question"
            web_server.push_question(_q_header, _q_text, choices=_q_choices)
            _bonus_correct_answer = _q_answer
        elif guessing_extra == "freeform":
            _toggle_coming_up_popup(True,
                ROUND_PREFIX + "Free Form",
                "Answer according to the prompt.",
                up_next=False)
            web_server.push_question("Free Form", "Answer according to the prompt.", autocomplete="anime")
        elif guessing_extra == "buzzer":
            if state.playback.bonus_settings.get("buzzer", BONUS_SETTINGS_DEFAULT["buzzer"]).get("popup", False):
                _toggle_coming_up_popup(True,
                    ROUND_PREFIX + "Buzzer Enabled", "Buzz in to answer.",
                    up_next=False)
            else:
                _toggle_coming_up_popup(False)
            web_server.push_question(
                "Buzzer Enabled",
                "Press BUZZ to answer.",
                buzzer_only=True,
            )
    else:
        reset_bonus()
    _refresh_popout_toggles_fn()
    if web_server.is_running():
        _push_web_toggles_fn()


# ---------------------------------------------------------------------------
# Tag / title helpers
# ---------------------------------------------------------------------------

def get_random_tags():
    currently_playing = state.playback.currently_playing
    data = currently_playing.get("data")
    if data:
        tags = _get_tags(data)
        tags_len = len(tags)
        all_tags = _get_all_tags(game=False, double=True)
        all_tags_len = len(_get_all_tags(game=False))
        while len(tags) < 20 and len(tags) < tags_len * 4 and len(tags) != all_tags_len:
            random_tag = random.choice(all_tags)
            if random_tag not in tags:
                tags.append(random_tag)
        return sorted(tags)
    return ["", ""]


def get_random_titles(amount=4):
    currently_playing = state.playback.currently_playing
    data = currently_playing.get("data")
    if not data:
        return ["", "", "", ""]

    correct_title = _get_display_title(data)
    correct_series = _series_list(data)
    titles = [correct_title]
    used_series = set(correct_series)

    GENERIC_WORDS = {"the", "a", "an", "of", "and", "in", "to", "for", "with", "on", "season", "part", "new", "as", "is", "at", "by", "from",
                        "it", "this", "that", "these", "those", "animation", "movie", "ova", "special", "tv", "series", "episode", "episodes",
                        "no"}

    def get_words(title):
        return set(w.lower() for w in re.findall(r'\w+', title) if w.lower() not in GENERIC_WORDS)

    def get_series_key(anime):
        return _series_primary(anime) or ""

    # Build series title-count lookup once (O(n)) to avoid O(n²) in scoring
    series_title_count = {}
    for a in state.metadata.anime_metadata.values():
        key = get_series_key(a)
        series_title_count[key] = series_title_count.get(key, 0) + 1

    # Build MAL ID -> AniList tag {name: rank} dict from file_metadata
    mal_to_anilist_tags = {}
    for mal_id, fm_entry in state.metadata.file_metadata.items():
        anilist_id = fm_entry.get("anilist")
        if anilist_id:
            al = state.metadata.anilist_metadata.get(str(anilist_id))
            if al:
                mal_to_anilist_tags[mal_id] = {t["name"]: t.get("rank", 0) for t in al.get("tags", []) if t.get("name")}

    correct_mal_id = data.get("mal")
    correct_studios = set(data.get("studios", []))
    correct_tags = set(_get_tags(data))
    correct_anilist_tags = mal_to_anilist_tags.get(correct_mal_id, {})

    def get_similarity_score(entry):
        mal_id, anime = entry
        score = 0
        score += len(set(anime.get("studios", [])) & correct_studios)
        candidate_tags = mal_to_anilist_tags.get(mal_id, {})
        if correct_anilist_tags and candidate_tags:
            score += sum(min(correct_anilist_tags[name], candidate_tags[name]) / 100
                         for name in correct_anilist_tags if name in candidate_tags)
        else:
            score += len(set(_get_tags(anime)) & correct_tags) * 2
        score -= max(0, (series_title_count.get(get_series_key(anime), 1) - 2))
        score -= used_multiple_titles.get(get_series_key(anime), 0) * 2
        return score

    # Filter and score
    similar_anime = [
        (mal_id, a) for mal_id, a in state.metadata.anime_metadata.items()
        if _get_display_title(a) != correct_title
    ]

    # Sort by similarity (descending)
    similar_anime = sorted(similar_anime, key=get_similarity_score, reverse=True)

    unique_series_anime = []
    seen_series = set(used_series)
    for mal_id, anime in similar_anime:
        series = _series_list(anime)
        if not seen_series.intersection(series) and not _is_game(anime):
            unique_series_anime.append(anime)
            seen_series.update(series)
        if len(unique_series_anime) >= 30:
            break

    distractors = []

    needed = amount - 1 - len(distractors)
    top_similar_sorted_by_members = sorted(unique_series_anime, key=lambda a: _get_series_popularity(a))
    all_groups = utils.split_array(top_similar_sorted_by_members, needed + 1)
    for group in all_groups[1:]:  # Skip first (most popular) group
        if group:
            pick = random.choice(group)
            distractors.append(_get_display_title(pick))
            key = get_series_key(pick)
            used_multiple_titles[key] = used_multiple_titles.get(key, 0) + 1

    correct_key = correct_series[0] if correct_series else correct_title
    used_multiple_titles[correct_key] = used_multiple_titles.get(correct_key, 0) + 1

    titles.extend(distractors)

    # Fallback: fill remaining slots from similar_anime (relaxing uniqueness) if not enough distractors
    if len(titles) < amount:
        used_titles = set(titles)
        for mal_id, anime in similar_anime:
            if len(titles) >= amount:
                break
            t = _get_display_title(anime)
            if t not in used_titles:
                titles.append(t)
                used_titles.add(t)

    # Last resort: pad with empty strings
    while len(titles) < amount:
        titles.append("")

    random.shuffle(titles)
    return titles[:amount]




# ---------------------------------------------------------------------------
# Character bonus
# ---------------------------------------------------------------------------

def _bonus_chars_on_mpv_rect(mx, my, mw, mh):
    """Redraw bonus character overlay when mpv window is moved/resized."""
    if bonus_overlay_window and _bonus_chars_current:
        _draw_bonus_characters_osd(_bonus_chars_current, _bonus_chars_reveal)


def pick_bonus_characters():
    """
    Picks num_correct characters from the current show and (6 - num_correct) distractors.
    Prioritizes distractors from shows with shared studios or tags.
    Returns: list of 6 character tuples, and indices of the correct ones.
    """
    currently_playing = state.playback.currently_playing
    bonus_settings = state.playback.bonus_settings
    data = currently_playing.get("data", {})
    if not data or not data.get("characters"):
        return [], []

    _bs_chars = bonus_settings.get("characters", BONUS_SETTINGS_DEFAULT["characters"])
    num_correct = max(1, min(5, int(_bs_chars.get("num_correct", BONUS_SETTINGS_DEFAULT["characters"]["num_correct"]))))
    num_distractors = 6 - num_correct

    # Get correct characters
    characters = data["characters"]
    selected = []

    def get_chars_by_role(role_code):
        return [c for c in characters if c[0] == role_code and c[2] and c[3] != "unknown"]

    # Try getting characters in order: appears -> secondary -> main
    for role in ["a", "s", "m"]:
        role_chars = get_chars_by_role(role)
        needed = num_correct - len(selected)
        if role_chars:
            selected.extend(random.sample(role_chars, min(needed, len(role_chars))))
        if len(selected) == num_correct:
            break

    if len(selected) < num_correct:
        backup = [c for c in characters if c[2]]
        selected.extend(random.sample(backup, min(num_correct - len(selected), len(backup))))

    correct_series = _series_list(data)
    correct_year = int(data.get("season", "9999")[-4:])
    used_series = set(correct_series)
    correct_studios = set(data.get("studios") or [])
    correct_tags = set(_get_tags(data))

    # Build mal_id -> {tag_name: rank} from anilist_metadata
    mal_to_anilist_tags = {}
    for _mid, fm_entry in state.metadata.file_metadata.items():
        _al_id = fm_entry.get("anilist")
        if _al_id:
            _al = state.metadata.anilist_metadata.get(str(_al_id))
            if _al:
                mal_to_anilist_tags[_mid] = {t["name"]: t.get("rank", 0) for t in _al.get("tags", []) if t.get("name")}

    correct_mal_id = data.get("mal")
    correct_anilist_tags = mal_to_anilist_tags.get(correct_mal_id, {})
    correct_has_anthro = (correct_anilist_tags.get("Anthropomorphic", 0) > 0) if correct_anilist_tags else ("Anthropomorphic" in correct_tags)

    distractors = []

    for mal_id, anime in state.metadata.anime_metadata.items():
        if not mal_id.isdigit() or _series_overlap(anime, data):
            continue

        if _series_set(anime).intersection(used_series):
            continue

        anime_anilist_tags = mal_to_anilist_tags.get(mal_id, {})
        if anime_anilist_tags:
            anime_has_anthro = anime_anilist_tags.get("Anthropomorphic", 0) > 0
        else:
            anime_has_anthro = "Anthropomorphic" in set(_get_tags(anime))
        if anime_has_anthro != correct_has_anthro:
            continue

        anidb_data = get_anidb_metadata_from_anime(mal_id)
        if not anidb_data:
            continue

        valid_chars = [c for c in anidb_data.get("characters", []) if c[0] == "a" and c[2] and c[3] != "unknown"]
        if not valid_chars:
            continue

        score = 0
        score += len(set(anime.get("studios", [])) & correct_studios) * 3
        if correct_anilist_tags and anime_anilist_tags:
            score += sum(min(correct_anilist_tags[name], anime_anilist_tags[name]) / 100
                         for name in correct_anilist_tags if name in anime_anilist_tags)
        else:
            score += len(set(_get_tags(anime)) & correct_tags)
        distractor_year = int(anime.get("season", "9999")[-4:])
        if correct_year and distractor_year:
            year_diff = abs(correct_year - distractor_year)
            if year_diff <= 2:
                score += 3
            elif year_diff <= 5:
                score += 2
            elif year_diff <= 10:
                score += 1

        distractors.append((score, random.choice(valid_chars), _series_set(anime)))

    distractors.sort(key=lambda x: -x[0])

    final_distractors = []
    for _, char, distractor_series_set in distractors:
        if not used_series.intersection(distractor_series_set):
            final_distractors.append(char)
            used_series.update(distractor_series_set)
        if len(final_distractors) == num_distractors:
            break

    while len(final_distractors) < num_distractors:
        random_char = random.choice([c for c in characters if c not in selected and c[2]])
        final_distractors.append(random_char)

    all_chars = selected + final_distractors
    random.shuffle(all_chars)
    correct_indices = [i for i, c in enumerate(all_chars) if c in selected]
    return all_chars, correct_indices


def get_anidb_metadata_from_anime(mal):
    for anidb_id, anidb_data in state.metadata.anidb_metadata.items():
        mal_id = anidb_data.get("mal_id")
        if mal_id and str(mal_id) == str(mal):
            return anidb_data
    return {}


def _draw_bonus_characters_osd(characters, reveal_correct=False):
    """Render bonus character portraits as an mpv image overlay (pure PIL, no ASS)."""
    global _bonus_chars_img_overlay, _bonus_chars_reveal
    _bonus_chars_reveal = reveal_correct
    if Image is None:
        return
    try:
        osd_w = int(_player._p.osd_width or 0)
        osd_h = int(_player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h or not characters:
        return

    modifier = min(osd_w / 2560, osd_h / 1440)

    bonus_settings = state.playback.bonus_settings
    _bs_chars = bonus_settings.get("characters", BONUS_SETTINGS_DEFAULT["characters"])
    modifier *= float(_bs_chars.get("scale", BONUS_SETTINGS_DEFAULT["characters"]["scale"]))
    img_w    = max(80,  round(210 * modifier))
    img_h    = max(120, round(315 * modifier))
    label_fs = max(10,  round(24  * modifier * 1.6))
    pad      = max(4,   round(6   * modifier))
    border   = max(1,   round(2   * modifier))
    gap      = max(4,   round(8   * modifier))

    n      = len(characters)
    cell_w = img_w + 2 * (pad + border)
    cell_h = img_h + label_fs + 3 * pad + 2 * border
    total_w = n * cell_w + (n - 1) * gap

    _coming_up_osd_box_h = _get_coming_up_osd_box_h()
    if reveal_correct:
        pos_x = (osd_w - total_w) // 2
        pos_y = max(4, round(10 * modifier))
    else:
        pos_x = (osd_w - total_w) // 2
        pos_y = (_coming_up_osd_box_h + max(10, round(20 * modifier))
                 if _coming_up_osd_box_h > 0 else round(osd_h * 0.15))

    try:
        r16, g16, b16 = _root.winfo_rgb(_get_overlay_background_color())
        bg_r, bg_g, bg_b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        bg_r, bg_g, bg_b = 0, 0, 0

    canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    fnt    = _get_ass_font(label_fs)

    cached_images = state.playback.cached_images
    for i, char in enumerate(characters):
        cx = pos_x + i * (cell_w + gap)
        cy = pos_y

        is_correct   = reveal_correct and i in bonus_correct_indices
        cell_fill    = (100, 100, 100, 220) if is_correct else (bg_r, bg_g, bg_b, 210)
        border_color = (220, 220, 220, 255)

        draw.rectangle([cx, cy, cx + cell_w - 1, cy + cell_h - 1],
                       fill=cell_fill, outline=border_color, width=border)

        ix = cx + pad + border
        iy = cy + pad + border
        if len(char) > 2 and char[2]:
            img_url = "https://cdn-eu.anidb.net/images/main/" + char[2]
            raw = cached_images.get(img_url)
            if raw is not None:
                pil_img = _load_pil_image_from_url(img_url, size=(img_w, img_h))
                if pil_img:
                    canvas.paste(pil_img, (ix, iy), pil_img)
                else:
                    draw.rectangle([ix, iy, ix + img_w - 1, iy + img_h - 1],
                                   fill=(50, 50, 50, 200))
            else:
                draw.rectangle([ix, iy, ix + img_w - 1, iy + img_h - 1],
                               fill=(40, 40, 40, 200))
                if fnt:
                    ph = "..."
                    try:
                        ph_w = round(fnt.getlength(ph))
                    except AttributeError:
                        ph_w = len(ph) * label_fs // 2
                    draw.text((ix + (img_w - ph_w) // 2, iy + img_h // 2 - label_fs // 2),
                              ph, font=fnt, fill=(150, 150, 150, 200))

        label = f"[{chr(65 + i)}]"
        ly = iy + img_h + pad
        if fnt:
            try:
                tw = round(fnt.getlength(label))
            except AttributeError:
                tw = len(label) * label_fs // 2
            lx = cx + (cell_w - tw) // 2
            draw.text((lx, ly), label, font=fnt, fill=(255, 255, 255, 255))

    if _bonus_chars_img_overlay is None:
        _bonus_chars_img_overlay = _player._p.create_image_overlay()
    _bonus_chars_img_overlay.update(canvas)


def show_bonus_characters(characters, reveal_correct=False):
    """Display bonus character portraits as an mpv OSD image overlay.

    Safe to call from a background thread — image loading may be slow on first
    call but is cached afterwards; the OSD update is dispatched via root.after.
    """
    global bonus_overlay_window, _bonus_chars_current, _bonus_chars_reveal

    destroy_bonus_characters()

    if not characters:
        return

    _bonus_chars_current = characters
    _bonus_chars_reveal = reveal_correct
    bonus_overlay_window = True

    _register_mpv_tracked_window("bonus_chars", None, _bonus_chars_on_mpv_rect)

    try:
        _root.after(0, lambda: _draw_bonus_characters_osd(characters, reveal_correct))
    except Exception:
        pass

    def _load_and_redraw(char, _chars=characters, _rev=reveal_correct):
        if len(char) > 2 and char[2]:
            _load_pil_image_from_url("https://cdn-eu.anidb.net/images/main/" + char[2], size=None)
        if bonus_overlay_window:
            try:
                _root.after(0, lambda: _draw_bonus_characters_osd(_chars, _rev))
            except Exception:
                pass

    for char in characters:
        threading.Thread(target=_load_and_redraw, args=(char,), daemon=True).start()


def destroy_bonus_characters():
    global bonus_overlay_window, _bonus_chars_img_overlay, _bonus_chars_current, _bonus_chars_reveal
    bonus_overlay_window = None
    _bonus_chars_current = []
    _bonus_chars_reveal = False
    _unregister_mpv_tracked_window("bonus_chars")
    if _bonus_chars_img_overlay is not None:
        try:
            _bonus_chars_img_overlay.remove()
        except Exception:
            pass
        _bonus_chars_img_overlay = None
