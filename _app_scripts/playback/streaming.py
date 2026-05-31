"""Streaming / clip / trailer playback module.

Owns:
  currently_streaming  — None | [name, url, channel]
  last_streamed        — [filename, name, url, channel]
  _stream_theme_path   — path to restore after stream ends
  _stream_wall_start   — None | True (sentinel: seek-to-start done)
  youtube_api_limited  — bool
  _cached_clips        — {id: [[title, video_id, channel], ...]}
  _cached_ost_clips    — same for OST clips
"""

import random
import re

from _app_scripts.queue_round.youtube import youtube_control
from core.game_state import state

try:
    from googleapiclient.discovery import build as _yt_build
except ImportError:
    _yt_build = None

# ---------------------------------------------------------------------------
# Module-owned state
# ---------------------------------------------------------------------------
currently_streaming = None          # None | [name, url, channel]
last_streamed = ["", "", "", ""]    # [filename, name, url, channel]
_stream_theme_path = None           # full path to restore into player after stream ends
_stream_wall_start = None           # True once seek-to-start_time has been performed
youtube_api_limited = False
youtube_api_limited_count = 0
_cached_clips = {}
_cached_ost_clips = {}
_cached_clips_links = []      # resolved for currently-displayed data; set by resolve_clips_for_data()
_cached_ost_clips_links = []  # same for OST clips
test_printing = False

# ---------------------------------------------------------------------------
# Context (injected at startup)
# ---------------------------------------------------------------------------
_root = None
_player = None
_get_previous_media = None
_get_projected_player_time = None
_get_light_round_start_time = None
_get_light_round_length = None
_get_fixed_current_round = None
_set_video_stopped = None
_get_light_mode = None
_get_display_title = None
_is_game = None
_get_base_title = None
_get_format = None
_get_selected_extra_metadata = None
_hide_ost_cover_fn = None
_update_extra_metadata_fn = None
_youtube_api_key = ""


def set_context(
    root,
    player,
    get_previous_media,
    get_projected_player_time,
    get_light_round_start_time,
    get_light_round_length,
    get_fixed_current_round,
    set_video_stopped,
    get_light_mode,
    get_display_title,
    is_game,
    get_base_title,
    get_format,
    get_selected_extra_metadata,
    hide_ost_cover_fn,
    update_extra_metadata_fn,
):
    global _root, _player
    global _get_previous_media, _get_projected_player_time
    global _get_light_round_start_time, _get_light_round_length, _get_fixed_current_round
    global _set_video_stopped, _get_light_mode
    global _get_display_title, _is_game, _get_base_title, _get_format
    global _get_selected_extra_metadata, _hide_ost_cover_fn, _update_extra_metadata_fn

    _root = root
    _player = player
    _get_previous_media = get_previous_media
    _get_projected_player_time = get_projected_player_time
    _get_light_round_start_time = get_light_round_start_time
    _get_light_round_length = get_light_round_length
    _get_fixed_current_round = get_fixed_current_round
    _set_video_stopped = set_video_stopped
    _get_light_mode = get_light_mode
    _get_display_title = get_display_title
    _is_game = is_game
    _get_base_title = get_base_title
    _get_format = get_format
    _get_selected_extra_metadata = get_selected_extra_metadata
    _hide_ost_cover_fn = hide_ost_cover_fn
    _update_extra_metadata_fn = update_extra_metadata_fn


def update_settings(youtube_api_key=""):
    global _youtube_api_key
    _youtube_api_key = youtube_api_key


# ---------------------------------------------------------------------------
# _stream_wall_start accessor (for external mutation from lightning round code)
# ---------------------------------------------------------------------------
def get_stream_wall_start():
    return _stream_wall_start


def set_stream_wall_start(value):
    global _stream_wall_start
    _stream_wall_start = value


# ---------------------------------------------------------------------------
# Core streaming functions
# ---------------------------------------------------------------------------
def stream_url(url, name=None, channel=None, new_player=True):
    global currently_streaming, last_streamed, _stream_theme_path

    currently_playing = state.playback.currently_playing

    # Check for a locally cached file first (avoids live yt-dlp URL resolution)
    cache_path = youtube_control._get_yt_cache_path(url)
    if cache_path and __import__('os').path.exists(cache_path) and not __import__('os').path.exists(cache_path + '.part'):
        direct_stream = cache_path
        cached = youtube_control._cached_streams.get(url)
        if cached and len(cached) >= 4:
            length = cached[1]
            if not name:
                name = cached[2]
            if not channel:
                channel = cached[3]
        else:
            meta = youtube_control._load_yt_meta(url)
            if meta:
                length = meta.get('duration', 0) or 0
                if not name:
                    name = meta.get('title') or __import__('os').path.splitext(__import__('os').path.basename(cache_path))[0]
                if not channel:
                    channel = meta.get('channel', '')
                youtube_control._cached_streams[url] = (cache_path, length, name, channel)
            else:
                _, fetched_length, fetched_name, fetched_channel = youtube_control.get_youtube_stream_url(url, include_other_info=True)
                length = fetched_length or 0
                if not name:
                    name = fetched_name or __import__('os').path.splitext(__import__('os').path.basename(cache_path))[0]
                if not channel:
                    channel = fetched_channel or ""
                youtube_control._save_yt_meta(url, title=name, channel=channel, duration=length)
    elif not name or not channel:
        direct_stream, length, name, channel = youtube_control.get_youtube_stream_url(url, include_other_info=True)
    else:
        direct_stream, length = youtube_control.get_youtube_stream_url(url)

    if direct_stream:
        currently_streaming = [name, url, channel]
        last_streamed = [currently_playing.get("filename"), name, url, channel]
        _stream_theme_path = _get_previous_media()
        _player.set_media(direct_stream)
    else:
        currently_streaming = None
    return length


def stop_stream(restore=True):
    global currently_streaming, _stream_theme_path, _stream_wall_start

    if not currently_streaming:
        return  # no-op when no stream is active

    currently_streaming = None
    _stream_wall_start = None

    if _stream_theme_path and restore:
        _set_video_stopped(True)
        restore_path = _stream_theme_path
        _stream_theme_path = None
        _player.set_media(restore_path)

        _expected_start = _get_light_round_start_time()
        _seek_types = ["regular", "reveal", "blind", "song"]
        fixed_current_round = _get_fixed_current_round()
        _fixed_answer_start = (
            fixed_current_round.get("start_time")
            if (fixed_current_round
                and fixed_current_round.get("start_time") is not None
                and fixed_current_round.get("type") not in _seek_types
                and not fixed_current_round.get("clip_for_answer"))
            else None
        )
        light_round_start_time = _get_light_round_start_time()
        light_round_length = _get_light_round_length()
        if _fixed_answer_start is not None:
            _target_ms = int(_fixed_answer_start * 1000)
        elif light_round_start_time is not None:
            _target_ms = int((light_round_start_time + light_round_length) * 1000)
        else:
            _target_ms = None

        def _seek_to_answer(attempt=0):
            if (_get_light_round_start_time() != _expected_start
                    or currently_streaming
                    or _target_ms is None):
                _hide_ost_cover_fn()
                return
            current_ms = _player.get_time()
            if abs(current_ms - _target_ms) <= 1000:
                _hide_ost_cover_fn()
                return
            if _player.is_playing():
                if _get_projected_player_time() < _target_ms - 500 or _get_projected_player_time() > _target_ms + 500:
                    _player.set_time(_target_ms)
                _hide_ost_cover_fn()
            elif attempt < 12:
                try:
                    _root.after(50, _seek_to_answer, attempt + 1)
                except Exception:
                    _hide_ost_cover_fn()
        try:
            _root.after(50, _seek_to_answer)
        except Exception:
            _hide_ost_cover_fn()
    else:
        if not restore:
            _stream_theme_path = None
        else:
            _player.stop()


def play_trailer(url=None):
    currently_playing = state.playback.currently_playing
    url = url or currently_playing.get("data", {}).get("trailer")
    if url:
        url = f"https://www.youtube.com/watch?v={url}"
        return stream_url(url, "Trailer", "Trailer", _get_light_mode() == 'clip')
    return 0


def get_stream_start_time(length):
    fixed_current_round = _get_fixed_current_round()
    light_round_length = _get_light_round_length()

    _cst = fixed_current_round.get("clip_start_time") if fixed_current_round else None
    if _cst is not None:
        return max(0, _cst)
    if last_streamed and last_streamed[3] and "Crunchyroll" in last_streamed[3]:
        start_buffer = 0
        end_buffer = 10
    elif last_streamed and last_streamed[3] and "Netflix" in last_streamed[3]:
        start_buffer = 0
        end_buffer = 25
    else:
        start_buffer = 5
        end_buffer = 5
    if length <= light_round_length + start_buffer + end_buffer:
        return 0
    max_start = int(length - light_round_length - end_buffer)
    return random.randint(start_buffer, max_start)


def play_random_clip(data=None, queue=False, ost=False):
    currently_playing = state.playback.currently_playing
    if currently_streaming and not data:
        stop_stream()
        return
    if not data:
        data = currently_playing.get("data")
    url, name, channel = load_random_clips(data, ost=ost)
    if url:
        if not queue:
            return stream_url(url, name, channel)
        return url, name, channel
    else:
        if not queue:
            return 0
        return None, None, None


def load_random_clips(data=None, limit_channels=False, ost=False):
    currently_playing = state.playback.currently_playing
    if not data:
        data = currently_playing.get("data")
    title = _get_display_title(data)
    year = int(data.get("season", "9999")[-4:])
    if ost:
        url, name, channel = get_random_anime_clip_stream_url(title, year, data, limit_channels=False, ost=True)
    else:
        url = name = channel = None
        if not _is_game(data) and len(data.get("title", "")) > 1:
            url, name, channel = get_random_anime_clip_stream_url(title, year, data, limit_channels=True)
        if not url and title != _get_base_title(title=title):
            url, name, channel = get_random_anime_clip_stream_url(_get_base_title(title=title), year, data, limit_channels=True)
        if not url and not limit_channels:
            url, name, channel = get_random_anime_clip_stream_url(title, year, data, limit_channels=False)
    if _get_selected_extra_metadata() == "clips":
        _update_extra_metadata_fn()
    return url, name, channel


def stream_clip(video_id, name, channel):
    url = f"https://www.youtube.com/watch?v={video_id}"
    if currently_streaming and currently_streaming[1] == url:
        stop_stream()
    else:
        stream_url(url, name, channel, False)


def resolve_clips_for_data(data):
    """Populate _cached_clips_links and _cached_ost_clips_links for *data*.

    Call this before building the clips link list so the lists reflect the
    current track. Encapsulates the cache-key computation that previously
    lived in the main module.
    """
    global _cached_clips_links, _cached_ost_clips_links
    cached_id = f"{_get_display_title(data)}-{data.get('season', '9999')[-4:]}"
    cached_id_base = f"{_get_base_title(title=_get_display_title(data))}-{data.get('season', '9999')[-4:]}"
    _cached_clips_links = _cached_clips.get(cached_id) or _cached_clips.get(cached_id_base) or []
    _cached_ost_clips_links = _cached_ost_clips.get(cached_id) or _cached_ost_clips.get(cached_id_base) or []


# ---------------------------------------------------------------------------
# YouTube clip search
# ---------------------------------------------------------------------------
def get_random_anime_clip_stream_url(anime_title, year, data, limit_channels=True, ost=False):
    global youtube_api_limited, youtube_api_limited_count

    _cached_id = f"{anime_title}-{year}"
    if not ost and _cached_id in _cached_clips and (_cached_clips[_cached_id] or limit_channels):
        valid_video_ids = _cached_clips[_cached_id]
    elif ost and _cached_id in _cached_ost_clips:
        valid_video_ids = _cached_ost_clips[_cached_id]
    else:
        if _yt_build is None:
            return None, None, None
        youtube = _yt_build("youtube", "v3", developerKey=_youtube_api_key)
        video_ids = None
        if limit_channels:
            query_extra = "crunchyroll"
        elif ost:
            query_extra = "anime ost"
        else:
            query_extra = "anime clip"
        if len(anime_title.split(" ")) == 1:
            query = f"{query_extra} {anime_title} {year}"
        else:
            query = f"{query_extra} {anime_title}"
        test_print(f"SEARCHING: '{query}'")
        try:
            search_response = youtube.search().list(
                q=query,
                part="id,snippet",
                type="video",
                order="relevance",
                relevanceLanguage="en",
                regionCode="US",
                maxResults=50
            ).execute()

            video_ids = [item["id"]["videoId"] for item in search_response["items"]]
            youtube_api_limited_count = 0
            test_print(len(video_ids))
        except Exception:
            youtube_api_limited_count += 1
            if youtube_api_limited_count >= 3:
                youtube_api_limited = True
        if not video_ids:
            return None, None, None

        details_response = youtube.videos().list(
            part="contentDetails,snippet,statistics",
            id=",".join(video_ids)
        ).execute()

        priority_video_ids = []
        valid_video_ids = []
        back_up_valid_videos = []
        for item in details_response["items"]:
            video_id = item["id"]
            duration = item["contentDetails"].get("duration", "0")
            title = item["snippet"]["title"]
            description = item["snippet"].get("description", "")
            channel_title = item["snippet"]["channelTitle"]

            try:
                thumb = (
                    item["snippet"]["thumbnails"].get("standard")
                    or item["snippet"]["thumbnails"].get("high")
                    or item["snippet"]["thumbnails"].get("medium")
                    or item["snippet"]["thumbnails"]["default"]
                )
                width = thumb.get("width")
                height = thumb.get("height")
                if width and height and width / height < 1:
                    test_print(f"[{video_id}]{title}: is short")
                    continue

                bad_keywords = [
                    "summary", "explained", "opening", "ending", "shorts", "amv",
                    "[amv]", "trailer", "comparison", "musicvideo", "music video",
                    "animate-it", "references", "review", "anime haul", "anime unboxing",
                    "meet the english voice of", "[sub indo]", "why you should watch ", "simulcast sampler",
                    "you should be reading", "& update", "getting a season", "in-depth",
                    "full length", "explain in", "masterpiece", "unboxing",
                    "how to watch", "op1", "op2", "op3", "op4", "op5", "op6", "op7", "op8",
                    "op9", "ed1", "ed2", "ed3", "ed4", "ed5", "ed6", "ed7", "ed8", "ed9",
                    "ranting about", "1. ", "horrible season of", "was almost perfect",
                    "anime vs manga", "10 shocking ", "everyone skipped this anime",
                    " is wicked\u2026", "unanswered questions", "needs to address", "tr\u00e1iler",
                    "release date update", "is finally here", "fun facts", "badly explaining",
                    "this manga is", "trash taste", "gigguk", "mmv", "manga release", "lyrics", "lyric",
                    "reactions", "reaction", "underrated anime is back", "is finally returning",
                    "10 differences between", "overrated!?!", "manga and anime", "film theory:",
                    "the manga that", "the anime that", "anime similar to", "should you watch",
                    "best anime of", "best watch order", "manga is so much better than the anime",
                    "everything you need to know about", "seasons ranked", "#animeedit", "they need to remake",
                    "? watch these!", "must watch", "anime you should", "anime you must", "anime you need",
                    "anime you have to", "anime you gotta", "veggietales", "reacting to", "the anime effect #",
                    "#animeexplain", "top 3", "top 5", "top 10", "top 11", "top 12", "top 13",
                    "anime mix", "english dub greeting video", "best of 20", "reacts to", "anime boston",
                    "best anime fights compilation", "best anime fight compilation", "best anime battles compilation",
                    "best anime battle compilation", "#animeindo", "first impressions", ") hype reel", "my recommended "
                ]
                ost_bad_keywords = [
                    "insert song", "anime songs", "cd single", "theme song", "full album", "extended", "toda la música"
                ]
                game_bad_keywords = [
                    "gameplay", "let's play", "walkthrough", "opening cinematic", "game trailer", "action rpg",
                ]
                if not _is_game(data):
                    bad_keywords += game_bad_keywords
                if not ost:
                    bad_keywords += ost_bad_keywords
                else:
                    bad_keywords += ["#"]

                filtered_keywords = [kw for kw in bad_keywords if kw not in f"{anime_title.lower()} {data.get('title').lower()}"]
                if any(kw in title.lower() for kw in filtered_keywords):
                    test_print(f"[{video_id}]{title}:  bad keyword")
                    continue

                whole_word_keywords = {"op", "ed", "recap", "amv"}
                ost_whole_word_keywords = {"ost"}
                if not ost:
                    whole_word_keywords |= ost_whole_word_keywords

                def contains_whole_word(t, keywords):
                    pattern = r'\b(?:' + '|'.join(re.escape(word) for word in keywords) + r')\b'
                    return re.search(pattern, t.lower()) is not None

                if (not (contains_whole_word(anime_title.lower(), whole_word_keywords)
                         or contains_whole_word(data.get("title").lower(), whole_word_keywords))
                        and contains_whole_word(title, whole_word_keywords)):
                    test_print(f"[{video_id}]{title}:  has a whole-word keyword")
                    continue

                if "movie" not in anime_title.lower() and "movie" in title.lower() and not _get_format(data) == "Movie":
                    test_print(f"[{video_id}]{title}:  movie in title when not movie")
                    continue

                bad_description_phrases = [" amv ", " amv.", "artista: "]
                if any(phrase in description.lower() for phrase in bad_description_phrases):
                    test_print(f"[{video_id}]{title}:  bad phrase in description")
                    continue

                title_okay = False
                check_description = True
                different_title_phrases = [
                    "from the creators of", "from the makers of", "by the creators of",
                    "all it took was", "from the studio that brought you",
                ]

                title_to_check = title
                if channel_title in ["Crunchyroll"]:
                    if "|" in title:
                        title_to_check = title.split("|")[1].strip()
                    check_description = False
                elif any(phrase in description.lower() for phrase in different_title_phrases):
                    check_description = False

                for t in [anime_title, data.get("title"), _get_base_title(title=anime_title), _get_base_title(title=data.get("title"))]:
                    t_edits = [t]
                    colon_split = t.split(": ")[0]
                    if colon_split != t and len(colon_split.strip()) >= 3:
                        t_edits.append(colon_split)
                    t_edits.extend([t.replace(" ", ""), t.replace(".", ""), t.replace("-", " ")])
                    for t_edit in t_edits:
                        if title_match_score(t_edit, title_to_check) or (check_description and title_match_score(t_edit, description)):
                            title_okay = True
                            break
                    if title_okay:
                        break
                if not title_okay:
                    test_print(f"[{video_id}]{title}: title doesn't match enough")
                    continue

                if ost:
                    is_ost = False
                    for t in ["OST", "Soundtrack", "Insert Song"]:
                        if title_match_score(t, title) or title_match_score(t, description):
                            is_ost = True
                            break
                    if not is_ost:
                        test_print(f"[{video_id}]{title}: is not ost")
                        continue

                blacklisted_channels = [
                    "Reacts", "AniRecaps", "Anime Recap", "Anime Summary", "Plot Recap", "Explains", "Crunchyroll Brasil",
                    "Explained", "Mother's Basement", "Crunchyroll: Inside Anime", "Crunchyroll TV", "It's Certified Otaku Vibes",
                    "Crunchyroll en Espa\u00f1ol", "Crunchyroll FR", "Crunchyroll India", "Crunchyroll DE", "WatchMojo", "Watch Mojo",
                    "AnimeVersa", "Crunchyroll en Espa\u00f1ol", "Netflix Jr.", "MWAMVEVO", "Tarkeus", "Gigguk", "ryuuarm", "Jent Watches",
                    "IGN Anime Club", "Albert Senpai", "AnimeSekaiStore", "ForgottenRelics", "Anuj Lama", "Garnt", " Watches",
                    "ProfessorOtakuD2", "The Best Anime Here", "SuperGainsBros", "BennettTheSage",
                ]
                ost_blacklisted_channels = [" - Topic"]
                if not ost:
                    blacklisted_channels += ost_blacklisted_channels
                if any(blacklist in channel_title for blacklist in blacklisted_channels):
                    test_print(f"[{video_id}]{title}: bad channel")
                    continue

                views = int(item["statistics"].get("viewCount", 0))
                if views < 500:
                    test_print(f"[{video_id}]{title}: too few views")
                    continue
                seconds = parse_iso8601_duration(duration)
                priority_channels = ["Crunchyroll", "Crunchyroll Dubs", "Netflix Anime"]
                video_data = [title, video_id, channel_title]
                if seconds >= 60 and any(priority == channel_title for priority in priority_channels):
                    less_priority_words = ["Teaser PV", "Now Available"]
                    if any(word in title for word in less_priority_words):
                        valid_video_ids.append(video_data)
                    else:
                        priority_video_ids.append(video_data)
                    continue
                elif limit_channels:
                    continue
                elif seconds > 60:
                    valid_video_ids.append(video_data)
                elif seconds >= 20:
                    back_up_valid_videos.append(video_data)
                else:
                    test_print(f"[{video_id}]{title}: too short")
            except Exception as e:
                test_print(f"error{e}")
                continue

        if not ost:
            valid_video_ids = priority_video_ids or valid_video_ids or back_up_valid_videos
        test_print(valid_video_ids)
        if not valid_video_ids:
            if ost:
                _cached_ost_clips[_cached_id] = None
            else:
                _cached_clips[_cached_id] = None
            return None, None, None
        else:
            if ost:
                _cached_ost_clips[_cached_id] = valid_video_ids
            else:
                _cached_clips[_cached_id] = valid_video_ids

    if valid_video_ids:
        if limit_channels:
            selected_title, selected_video_id, selected_channel = random.choice(valid_video_ids)
        else:
            selected_title, selected_video_id, selected_channel = random.choice(valid_video_ids[:5])
        video_url = f"https://www.youtube.com/watch?v={selected_video_id}"
        return video_url, selected_title, selected_channel
    else:
        return None, None, None


# ---------------------------------------------------------------------------
# Pure helpers (also used in main for general title matching)
# ---------------------------------------------------------------------------
def title_match_score(anime_title, video_title):
    GENERIC_WORDS = {
        "the", "a", "an", "of", "and", "in", "to", "for", "with", "on",
        "season", "part", "new", "as",
    }
    COMMON_PHRASES = {
        "daily life", "life of", "story of", "tale of", "adventures of",
        "chronicles of", "saga of", "legend of", "world of",
    }

    anime_stripped = anime_title.strip()
    if len(anime_stripped) <= 2:
        pattern = r'\b' + re.escape(anime_stripped) + r'\b'
        if re.search(pattern, video_title, re.IGNORECASE):
            return True
        return False

    def clean_words(text, exclude_generic=True):
        words = [word.strip("|'\u300e[]x.,!?:;\"'").lower() for word in text.lower().split()]
        if exclude_generic:
            words = [w for w in words if w not in GENERIC_WORDS]
        return words

    anime_words = clean_words(anime_title, True)
    anime_words_count = clean_words(anime_title)
    video_words = clean_words(video_title, True)

    lowered_full = video_title.lower()
    phrase_key = "from the director of"
    if phrase_key in lowered_full:
        pattern = re.compile(r"from the director of\s+([^-|:()]+)", re.IGNORECASE)
        spans = []
        for m in pattern.finditer(video_title):
            span_words = clean_words(m.group(1), False)
            spans.append((m.span(1), span_words))
        if spans:
            outside_text = lowered_full
            for sspan, _w in spans:
                start, end = sspan
                outside_text = (outside_text[:start].replace(anime_title.lower(), "")
                                + outside_text[end:].replace(anime_title.lower(), ""))
            anime_inline = anime_title.lower()
            appears_outside = anime_inline in outside_text
            anime_set = set(anime_words)
            span_contains_all = any(anime_set.issubset(set(words)) for _, words in spans)
            if span_contains_all and not appears_outside:
                return False

    i = 0
    matched_words = []
    if len(anime_words_count) < 3:
        min_match = len(anime_words_count)
    else:
        min_match = min(5, max(1, len(anime_words_count) // 2 + len(anime_words_count) % 2))

    for word in video_words:
        if i < len(anime_words) and word == anime_words[i]:
            matched_words.append(word)
            i += 1
            if i >= min_match:
                matched_text = " ".join(matched_words)
                is_only_common_phrase = any(phrase in matched_text for phrase in COMMON_PHRASES)
                if is_only_common_phrase and i < len(anime_words):
                    continue
                return True
        else:
            i = 0
            matched_words = []
    return False


def parse_iso8601_duration(duration):
    match = re.match(r'PT(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return 0
    minutes = int(match.group(1)) if match.group(1) else 0
    seconds = int(match.group(2)) if match.group(2) else 0
    return minutes * 60 + seconds


def test_print(text):
    if test_printing:
        print(text)
