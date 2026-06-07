"""Session history: tracking, persistence, stats generation, and text export."""

import json
import os
import time
from datetime import datetime
from tkinter import messagebox

from _app_scripts.file import scoreboard_control
from _app_scripts import utils
from _app_scripts.file.web_server import web_server
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.information.information_popup as information_popup
import _app_scripts.queue_round.youtube.youtube_ui as youtube_ui
import _app_scripts.playback.transport as transport

# ---------------------------------------------------------------------------
# Module-owned state
# ---------------------------------------------------------------------------
session_data = []
session_start_time = None


# ---------------------------------------------------------------------------
# Public API for external code to manipulate session_data
# ---------------------------------------------------------------------------
def add_entry(entry):
    """Append a single entry to session_data."""
    session_data.append(entry)


# ---------------------------------------------------------------------------
# OP / ED counting helper
# ---------------------------------------------------------------------------
def get_op_ed_counts(themes):
    opening_count = 0
    ending_count = 0

    for filename in themes:
        if filename is None:
            continue

        file_data = metadata_fetch.get_file_metadata_by_name(filename)
        if file_data and file_data.get('slug'):
            slug = file_data['slug']
        else:
            parts = filename.split("-")
            if len(parts) < 2:
                continue
            slug = parts[1].split(".")[0].split("v")[0]

        if utils.is_slug_op(slug):
            opening_count += 1
        else:
            ending_count += 1

    return opening_count, ending_count


# ---------------------------------------------------------------------------
# Top-series / top-artist helpers
# ---------------------------------------------------------------------------
def get_top_series_from_session(session_entries):
    series_counts = {}
    unique_themes_per_series = {}

    for entry in session_entries:
        if entry.get("type") == "theme" and entry.get("id") and entry.get("slug"):
            theme_id = f"{entry.get('id')}_{entry.get('slug')}"

            theme_data = metadata_fetch.get_metadata(entry.get("filename", ""))
            series_name = None

            if theme_data:
                series_raw = theme_data.get("series") or theme_data.get("title")
                if isinstance(series_raw, list):
                    series_name = series_raw[0] if series_raw else None
                else:
                    series_name = series_raw

            if not series_name:
                series_name = entry.get("title")

            if series_name:
                if series_name not in unique_themes_per_series:
                    unique_themes_per_series[series_name] = set()
                    series_counts[series_name] = 0

                if theme_id not in unique_themes_per_series[series_name]:
                    unique_themes_per_series[series_name].add(theme_id)
                    series_counts[series_name] += 1

    top_series = [(series, count) for series, count in series_counts.items() if count > 1]
    top_series.sort(key=lambda x: x[1], reverse=True)
    if not top_series:
        return None, 0

    top_count = top_series[0][1]
    tied_series = [series for series, count in top_series if count == top_count]
    if len(tied_series) != 1:
        return None, 0

    top_series_name, count = top_series[0]
    return top_series_name, count


def get_top_artist_from_session(session_entries):
    artist_counts = {}
    unique_themes = set()

    for entry in session_entries:
        if entry.get("type") == "theme" and entry.get("id") and entry.get("slug"):
            theme_id = f"{entry.get('id')}_{entry.get('slug')}"

            if theme_id not in unique_themes:
                unique_themes.add(theme_id)

                theme_data = metadata_fetch.get_metadata(entry.get("filename", ""))
                if theme_data:
                    for theme in theme_data.get("songs", []):
                        if theme.get("slug") == entry.get("slug"):
                            for artist in theme.get("artist", []):
                                if artist:
                                    artist_counts[artist] = artist_counts.get(artist, 0) + 1

    top_artists = [(artist, count) for artist, count in artist_counts.items() if count > 1]
    top_artists.sort(key=lambda x: x[1], reverse=True)
    if not top_artists:
        return None, 0

    top_count = top_artists[0][1]
    tied_artists = [artist for artist, count in top_artists if count == top_count]
    if len(tied_artists) != 1:
        return None, 0

    top_artist, count = top_artists[0]
    return top_artist, count


# ---------------------------------------------------------------------------
# Stats generation
# ---------------------------------------------------------------------------
def get_unique_themes_from_entries(data=None):
    """Get unique non-lightning filenames from the supplied session entries."""
    if data is None:
        data = session_data

    unique_themes = []
    seen = set()
    for entry in data:
        if entry.get("lightning_mode"):
            continue
        filename = entry.get("filename")
        if filename and filename not in seen:
            unique_themes.append(filename)
            seen.add(filename)
    return unique_themes


def get_session_summary_counts(data=None):
    """Return shared session summary counts for text export and end-session OSD."""
    if data is None:
        data = session_data

    unique_themes = get_unique_themes_from_entries(data)
    opening_count, ending_count = get_op_ed_counts(unique_themes)

    return {
        "themes_played": len(unique_themes),
        "opening_count": opening_count,
        "ending_count": ending_count,
        "lightning_count": sum(
            1 for entry in data
            if entry.get("lightning_mode") and not entry.get("fixed_playlist")
        ),
        "fixed_playlist_count": sum(
            1 for entry in data
            if entry.get("type") == "fixed_rounds_start"
        ),
        "youtube_count": sum(
            1 for entry in data
            if entry.get("type") == "youtube"
        ),
    }


def generate_session_stats(data=None):
    """Generate session statistics header lines for text file output."""
    if data is None:
        data = session_data
    if not data:
        return []

    stats_lines = []

    first_entry = data[0]
    last_entry = data[-1]
    start_time = utils.parse_timestamp_flexible(first_entry.get("timestamp", ""))
    end_time = utils.parse_timestamp_flexible(last_entry.get("timestamp", ""))
    duration = end_time - start_time
    duration_hours = duration.total_seconds() / 3600
    local_timezone = time.tzname[time.daylight] if time.daylight else time.tzname[0]

    stats_lines.append("=" * 60)
    stats_lines.append("GUESS THE ANIME! SESSION LOG")
    stats_lines.append(start_time.strftime('%B %d, %Y').upper())
    stats_lines.append(
        f"{start_time.strftime('%I:%M%p').lower()} - {end_time.strftime('%I:%M%p').lower()} "
        f"({duration_hours:.1f} HOURS) {local_timezone}"
    )
    stats_lines.append("=" * 60)

    summary = get_session_summary_counts(data)
    op_count = summary["opening_count"]
    ed_count = summary["ending_count"]
    stats_lines.append(f"Themes Played: {summary['themes_played']}")

    if op_count + ed_count > 0:
        op_percent = (op_count / (op_count + ed_count)) * 100
        ed_percent = (ed_count / (op_count + ed_count)) * 100
        stats_lines.append(f"Openings: {op_count} ({op_percent:.1f}%)")
        stats_lines.append(f"Endings: {ed_count} ({ed_percent:.1f}%)")

    lightning_tracks = summary["lightning_count"]
    if lightning_tracks > 0:
        stats_lines.append(f"Lightning Rounds: {lightning_tracks}")

    fixed_playlist_count = summary["fixed_playlist_count"]
    if fixed_playlist_count > 0:
        stats_lines.append(f"Fixed Playlists: {fixed_playlist_count}")

    youtube_count = summary["youtube_count"]
    if youtube_count > 0:
        stats_lines.append(f"YouTube Videos: {youtube_count}")

    top_series_name, top_series_count = get_top_series_from_session(data)
    if top_series_name:
        stats_lines.append(f"Most Played Series: {top_series_name} ({top_series_count})")

    top_artist, top_artist_count = get_top_artist_from_session(data)
    if top_artist:
        stats_lines.append(f"Most Played Artist: {top_artist} ({top_artist_count})")

    scoreboard_entries = [entry for entry in data if entry.get("type") == "scoreboard_score"]
    if scoreboard_entries:
        player_scores = {}
        for entry in scoreboard_entries:
            player = entry.get("player", "")
            new_score = entry.get("new_score", 0)
            player_scores[player] = new_score

        sorted_players = sorted(player_scores.items(), key=lambda x: x[1], reverse=True)

        stats_lines.append("=" * 60)
        stats_lines.append("-SCOREBOARD-")
        stats_lines.append("PTs   PLAYER")
        stats_lines.append("\u203e" * 12)
        for i, (player, score) in enumerate(sorted_players, 1):
            score_str = f"{score:g}"
            score_str += " " * (4 - len(score_str))
            stats_lines.append(f"{score_str}  {player}")

    stats_lines.append("=" * 60)
    stats_lines.append("")
    return stats_lines


def generate_text_from_session_data(data=None):
    """Generate text format from session_data for text file output."""
    if data is None:
        data = session_data
    text_lines = generate_session_stats(data)

    lightning_round_num = 0
    for i, entry in enumerate(data):
        timestamp = entry.get("timestamp", "")
        entry_type = entry.get("type", "theme")
        filename = entry.get("filename", "")
        lightning_mode = entry.get("lightning_mode")

        title = ""
        time_str = timestamp.split(" ")[-1] if " " in timestamp else timestamp
        session_string = f"{time_str}:"

        if entry_type == "youtube":
            url = entry.get("url", "")
            youtube_title = entry.get("title", "")
            name = entry.get("name", "")
            session_string = f"{session_string} [YOUTUBE VIDEO({url})] - {youtube_title} by {name}"
        elif entry_type == "fixed_rounds_start":
            playlist_name = entry.get("playlist_name", "Unknown")
            creator = entry.get("creator", "N/A")
            round_count = entry.get("round_count", 0)
            session_string = (
                f"{session_string} [FIXED LIGHTNING ROUNDS START] "
                f"{playlist_name} by {creator} ({round_count} rounds)"
            )
        elif entry_type == "scoreboard_score":
            player = entry.get("player", "")
            delta = entry.get("delta", 0)
            old_score = entry.get("old_score", 0)
            new_score = entry.get("new_score", 0)
            delta_str = "PT" if delta == 1 else "PTs"
            session_string = (
                f"{session_string} [SCOREBOARD] {player} {delta:+g} "
                f"{delta_str} ({old_score} \u2192 {new_score})"
            )
        elif entry_type == "bonus_question":
            q_type = entry.get("q_type", "").upper().replace("_", " ")
            correct = entry.get("correct")
            bonus_answers = entry.get("answers", [])
            if correct is not None:
                if isinstance(correct, list):
                    correct_str = f" | Correct: {', '.join(str(c) for c in correct)}"
                else:
                    correct_str = f" | Correct: {correct}"
            else:
                correct_str = ""
            parts = []
            for a in bonus_answers:
                a_name = a.get("name", "?")
                a_ans = a.get("answer", "?")
                a_pts = a.get("pts", 0)
                if a_pts:
                    n = int(a_pts) if a_pts == int(a_pts) else a_pts
                    parts.append(f"{a_name}: {a_ans!r} (+{n})")
                else:
                    parts.append(f"{a_name}: {a_ans!r}")
            answers_str = ", ".join(parts) if parts else "(no answers)"
            session_string = f"{session_string} [BONUS? {q_type}]{correct_str} | {answers_str}"
        else:
            if lightning_mode:
                lightning_round_num += 1
                session_string = (
                    f"{session_string} [LIGHTNING ROUND #{lightning_round_num}"
                    f"({lightning_mode.upper()})] -"
                )
            else:
                lightning_round_num = 0

            title = entry.get("title", "")
            slug = entry.get("slug", "")

            theme_data = metadata_fetch.get_metadata(filename)
            song_and_artist = ""

            if theme_data and slug:
                theme_data["slug"] = slug
                song_and_artist = information_popup.get_song_string(theme_data)

            session_string = f"{session_string} {title} - {utils.format_slug(slug)}"
            if song_and_artist:
                session_string = f"{session_string} ({song_and_artist})"

        if not title and filename:
            session_string = f"{session_string} {filename}"

        text_lines.append(session_string)

    return text_lines


# ---------------------------------------------------------------------------
# Unique themes / counts
# ---------------------------------------------------------------------------
def get_unique_themes_played():
    """Get list of unique filenames played this session (non-lightning)."""
    return get_unique_themes_from_entries(session_data)


def get_themes_played_count():
    """Get count of unique themes played this session."""
    return len(get_unique_themes_played())


def get_current_session_lightning_tracks():
    """Get set of filenames played in lightning mode during the current session."""
    lightning_tracks = set()
    for entry in session_data:
        if entry.get("lightning_mode") and entry.get("filename"):
            lightning_tracks.add(entry.get("filename"))
    return lightning_tracks


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
def create_new_session():
    """Initialize a new session log (called once at startup)."""
    global session_start_time
    if not load_recent_session():
        session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')
        try:
            _sc_path = os.path.join('scoreboard_data', 'score_changes.json')
            if os.path.exists(_sc_path):
                open(_sc_path, "w").close()
        except Exception:
            pass


def load_recent_session():
    """Load current_session.json if it was modified within the last 3 hours."""
    global session_data, session_start_time

    sessions_folder = "sessions"
    if not os.path.exists(sessions_folder):
        return False

    json_path = os.path.join(sessions_folder, "current_session.json")
    if not os.path.exists(json_path):
        return False

    try:
        file_mod_time = datetime.fromtimestamp(os.path.getmtime(json_path))
        time_diff = (datetime.now() - file_mod_time).total_seconds() / 60  # minutes

        if time_diff <= 180:
            with open(json_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)

            if session_data:
                first_timestamp = session_data[0].get("timestamp", "")
                if first_timestamp:
                    session_start_time = utils.parse_timestamp_flexible(first_timestamp).strftime('%Y-%m-%d_%H-%M')
                else:
                    session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')
            else:
                session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')

            transport.update_playlist_name()
            return True

    except (ValueError, json.JSONDecodeError, KeyError):
        return False

    return False


def add_session_history(currently_playing, light_mode, playlist, system_playlists, is_fixed_lightning=False):
    """Add currently-playing entry to session log and auto-save."""
    global session_start_time

    data = currently_playing.get("data")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if len(session_data) == 0:
        session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')

    session_entry = {
        "timestamp": timestamp,
        "type": currently_playing.get("type", "theme"),
        "filename": currently_playing.get("filename", ""),
        "lightning_mode": light_mode if light_mode else None,
    }
    if is_fixed_lightning:
        session_entry["fixed_playlist"] = True

    if data:
        session_entry.update({
            "id": data.get("mal"),
            "title": metadata_display.get_display_title(data),
            "slug": data.get("slug"),
        })

        if currently_playing.get("type") == "youtube":
            session_entry["url"] = data.get("url")
            session_entry["title"] = youtube_ui.get_youtube_display_title(data)
            session_entry["name"] = data.get("name")

    session_data.append(session_entry)

    if len(session_data) % 100 == 0 and playlist.get("name") not in system_playlists:
        save_session_history(create_text_file=True)
    else:
        save_session_history(create_text_file=False)


def save_session_history(create_text_file=True, silent=True):
    """Persist session_data to JSON (always) and optionally to .txt."""
    if not session_data or not session_start_time:
        return

    scoreboard_control.add_score_changes_to_session(session_data)

    def get_sort_key(entry):
        timestamp_val = entry.get("timestamp", "00:00:00")
        try:
            if isinstance(timestamp_val, (int, float)):
                return float(timestamp_val)
            if isinstance(timestamp_val, str):
                if len(timestamp_val) > 8:
                    dt = datetime.strptime(timestamp_val, "%Y-%m-%d %H:%M:%S")
                    return dt.timestamp()
                else:
                    time_part = datetime.strptime(timestamp_val, "%H:%M:%S").time()
                    dt = datetime.combine(datetime.now().date(), time_part)
                    return dt.timestamp()
            return 0
        except (ValueError, OverflowError, TypeError):
            return 0

    session_data.sort(key=get_sort_key)

    os.makedirs("sessions", exist_ok=True)

    json_filename = "sessions/current_session.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)

    last_theme_idx = next(
        (i for i in range(len(session_data) - 1, -1, -1)
         if session_data[i].get("type") in ("theme", "youtube")),
        None,
    )
    if last_theme_idx is not None:
        web_data = session_data[:last_theme_idx] + session_data[last_theme_idx + 1:]
    else:
        web_data = session_data
    web_server.push_session_history(
        generate_text_from_session_data(web_data),
        filename=f"guess_the_anime_{session_start_time}.txt",
    )

    if create_text_file:
        txt_filename = f"sessions/guess_the_anime_{session_start_time}.txt"
        text_lines = generate_text_from_session_data()
        with open(txt_filename, "w", encoding="utf-8") as f:
            for line in text_lines:
                f.write(line + "\n")
        if not silent:
            print(f"Session log saved to: {txt_filename}")


def reset_session_history(confirm=True):
    """Clear the current session, optionally asking for confirmation."""
    global session_data, session_start_time

    if confirm and session_data:
        count = get_themes_played_count()
        confirmed = messagebox.askyesno(
            "Reset Session History",
            f"Reset the session history for {count} theme{'s' if count != 1 else ''}?\n\nThis cannot be undone.",
        )
        if not confirmed:
            return

    session_data = []
    session_start_time = datetime.now().strftime('%Y-%m-%d_%H-%M')

    _sc_path = os.path.join('scoreboard_data', 'score_changes.json')
    if os.path.exists(_sc_path):
        open(_sc_path, "w").close()

    transport.update_playlist_name()
