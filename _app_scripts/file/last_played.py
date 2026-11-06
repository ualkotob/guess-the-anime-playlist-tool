"""Read-only dates for playlist positions, inferred from existing session logs.

Only unique ordered runs are accepted. All parsing/matching happens on one
background worker; Info rendering reads an immutable in-memory result. No play
records, playlist fields, or persistent timestamp indexes are written.
"""

from __future__ import annotations

from collections import defaultdict
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import threading
import time
import unicodedata

from core.app_logging import log_exception
from core.game_state import state
from core.paths import PLAYLISTS_FOLDER


_EVENT = re.compile(r"^(?:(\d{4}-\d{2}-\d{2}) )?(\d{2}:\d{2}:\d{2}):\s*(.*)$")
_LOG_DATE = re.compile(r"guess_the_anime_(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}")
_THEME = re.compile(r"^(.+) - ((?:Opening|Ending)\s+\S+|[A-Z]+\d[\w.-]*)(?=\s*(?:\(|$))")
_LIGHTNING = re.compile(r"^\[?LIGHTNING ROUND #\d+\([^)]+\)\]?\s*-\s*", re.I)
_FIXED = re.compile(r"^\[?FIXED LIGHTNING ROUNDS", re.I)
_MEDIA = re.compile(r"(?:^|\s)([^\s]+\.(?:webm|mp4|mkv|avi|mov))$", re.I)
_NON_PLAY = ("[SCOREBOARD]", "[BONUS?")
_SESSION_FIELDS = ("type", "filename", "id", "slug", "timestamp", "lightning_mode", "fixed_playlist")
_MIN_RUN = 6
_RESCAN_SECONDS = 10


def _yield(index):
    if index % 256 == 0:
        # A zero-length sleep can immediately reacquire the GIL on Windows.
        # Give Tk a real scheduling opportunity during archive construction.
        time.sleep(0.001)


def _normal_text(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


@dataclass(frozen=True)
class Event:
    key: tuple | None
    when: datetime | None


_BOUNDARY = Event(None, None)


class Resolver:
    """Resolve exact recorded names/slugs; retain ambiguity instead of guessing."""

    def __init__(self, anime, files, key_for_entry):
        self.key_for_entry = key_for_entry
        self.aliases = defaultdict(set)
        self.songs = defaultdict(set)
        self.keys = defaultdict(set)
        for index, (anime_id, record) in enumerate(anime):
            _yield(index)
            if not isinstance(record, dict):
                continue
            anime_id = str(anime_id)
            for title in (record.get("title"), record.get("eng_title"), *(record.get("synonyms") or [])):
                if title:
                    self.aliases[_normal_text(title)].add(anime_id)
            for song in record.get("songs") or []:
                slug = str(song.get("slug") or "").upper()
                if slug and song.get("title"):
                    self.songs[anime_id, slug].add(_normal_text(song["title"]))
        for index, (anime_id, record) in enumerate(files):
            _yield(index)
            if not isinstance(record, dict):
                continue
            anime_id = str(anime_id)
            for slug, versions in record.get("themes", {}).items():
                identity = (anime_id, str(slug).upper())
                if anime_id.isdigit() and int(anime_id) > 0:
                    self.keys[identity].add(("theme", str(int(anime_id)), identity[1]))
                else:
                    for media in versions.values():
                        for filename in media:
                            self.keys[identity].add(key_for_entry(filename))

    def resolve(self, body):
        match = _THEME.match(body)
        if match:
            title, slug = match.groups()
            slug = slug.replace("Opening ", "OP").replace("Ending ", "ED").upper()
            candidates = {(anime_id, slug) for anime_id in self.aliases.get(_normal_text(title), ())}
            song = body[match.end():].strip()
            if song.startswith("(") and song.endswith(")"):
                song = song[1:-1]
            song = _normal_text(song.rsplit(" by ", 1)[0])
            if len(candidates) > 1 and song:
                candidates = {candidate for candidate in candidates if song in self.songs.get(candidate, ())}
            if len(candidates) == 1:
                identity = next(iter(candidates))
                known_songs = self.songs.get(identity)
                if song and known_songs and song not in known_songs:
                    return None
                keys = self.keys.get(identity, set())
                if len(keys) == 1:
                    return next(iter(keys))
                # Deleted manual files can still be identified by their MAL tag.
                if not keys and identity[0].isdigit() and int(identity[0]) > 0:
                    return ("theme", str(int(identity[0])), identity[1])
        hint = _MEDIA.search(body)
        return self.key_for_entry(hint.group(1)) if hint else None


def _session_date(text, filename):
    match = _LOG_DATE.search(filename)
    try:
        from_name = date.fromisoformat(match.group(1)) if match else None
    except ValueError:
        from_name = None
    from_header = None
    for line in text.splitlines()[:8]:
        try:
            from_header = datetime.strptime(line, "%B %d, %Y").date()
            break
        except ValueError:
            pass
    if from_name and from_header and from_name != from_header:
        return None
    return from_header or from_name


def parse_text(text, filename, resolver):
    """Parse old/new text formats, preserving unknown plays as run boundaries."""
    day = _session_date(text, filename)
    previous = None
    fixed_remaining = 0
    events = []
    for index, line in enumerate(text.splitlines()):
        _yield(index)
        match = _EVENT.match(line)
        if not match:
            continue
        explicit_date, clock, body = match.groups()
        when = None
        try:
            clock = datetime.strptime(clock, "%H:%M:%S").time()
            if explicit_date:
                day = date.fromisoformat(explicit_date)
                when = datetime.combine(day, clock)
            elif day:
                if previous and previous.hour >= 18 and clock.hour <= 6:
                    day += timedelta(days=1)
                when = datetime.combine(day, clock)
            if when and previous and when < previous:
                events.append(_BOUNDARY)
            if when:
                previous = when
        except ValueError:
            events.append(_BOUNDARY)
        if body.startswith(_NON_PLAY):
            continue
        if _FIXED.match(body):
            rounds = re.search(r"\((\d+) rounds?\)", body)
            fixed_remaining = int(rounds.group(1)) if rounds else 0
            events.append(_BOUNDARY)
            continue
        if body.startswith("[YOUTUBE VIDEO") or re.search(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)", body):
            events.append(_BOUNDARY)
            continue
        if fixed_remaining:
            fixed_remaining -= 1
            continue
        if _LIGHTNING.match(body):
            continue
        events.append(Event(resolver.resolve(body), when))
    return tuple(events)


def parse_session(entries, resolver):
    """Read the existing live-session fields; do not add provenance fields."""
    events = []
    previous = None
    for index, values in enumerate(entries):
        _yield(index)
        entry = dict(zip(_SESSION_FIELDS, values))
        kind = entry["type"] or "theme"
        if kind in ("youtube", "fixed_rounds_start"):
            events.append(_BOUNDARY)
            continue
        if kind != "theme" or entry["lightning_mode"] or entry["fixed_playlist"]:
            continue
        filename = entry["filename"]
        if not filename:
            events.append(_BOUNDARY)
            continue
        try:
            when = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            when = None
        if previous and when and when < previous:
            events.append(_BOUNDARY)
        if when:
            previous = when
        identity = {"mal": entry["id"], "slug": entry["slug"]}
        key = resolver.key_for_entry(filename, identity if identity["mal"] and identity["slug"] else None)
        events.append(Event(key, when))
    return tuple(events)


def align_dates(histories, sources, min_run=_MIN_RUN):
    """Return dates at actual history indices, anchored by unique theme runs.

    histories maps playlist names to (canonical key, original index) pairs.
    Conflicting dates and windows shared with copies or repeated within one
    history are left undated. Unknown events never bridge two matching runs.
    """
    keys = {name: tuple(key for key, _ in history) for name, history in histories.items()}
    anchors = {}
    for name, sequence in keys.items():
        for index in range(len(sequence) - min_run + 1):
            _yield(index)
            window = sequence[index:index + min_run]
            if None in window or len(set(window)) < 3:
                continue
            anchors[window] = (name, index) if window not in anchors else None
    evidence = defaultdict(set)
    for source_index, events in enumerate(sources):
        _yield(source_index)
        sequence = tuple(event.key for event in events)
        assignments = defaultdict(set)
        for index in range(len(sequence) - min_run + 1):
            _yield(index)
            anchor = anchors.get(sequence[index:index + min_run])
            if anchor is None:
                continue
            name, position = anchor
            if assignments[index] == {anchor}:
                continue
            history = keys[name]
            left, start = index, position
            while left and start and sequence[left - 1] is not None and sequence[left - 1] == history[start - 1]:
                left -= 1
                start -= 1
            right, end = index + min_run, position + min_run
            while right < len(sequence) and end < len(history) and sequence[right] is not None and sequence[right] == history[end]:
                right += 1
                end += 1
            times = [event.when for event in events[left:right] if event.when]
            if any(a > b for a, b in zip(times, times[1:])):
                continue
            for offset, event_index in enumerate(range(left, right)):
                assignments[event_index].add((name, start + offset))
        for event_index, positions in assignments.items():
            if len(positions) != 1 or events[event_index].when is None:
                continue
            name, position = next(iter(positions))
            evidence[name, histories[name][position][1]].add(events[event_index].when)
    result = defaultdict(dict)
    for (name, index), times in evidence.items():
        if len(times) == 1:
            result[name][index] = next(iter(times))
    for dates in result.values():
        ordered = sorted(dates.items())
        conflicts = {index for (a, t1), (b, t2) in zip(ordered, ordered[1:]) if t1 > t2 for index in (a, b)}
        for index in conflicts:
            dates.pop(index, None)
    return dict(result)


@dataclass(frozen=True)
class Request:
    name: str
    entries: tuple
    session: tuple
    generation: int


class DateCache:
    """One coalescing worker, with parsed-file and metadata caches."""

    def __init__(self, resolver_factory, sessions="sessions", playlists=PLAYLISTS_FOLDER):
        self.resolver_factory = resolver_factory
        self.sessions = Path(sessions)
        self.playlists = Path(playlists)
        self._lock = threading.Lock()
        self._pending = None
        self._requested = None
        self._working = False
        self._next_check = 0
        self._result = None
        self._generation = None
        self._resolver = None
        self._text_cache = {}
        self._playlist_cache = {}
        self._key_cache = {}
        self._built_signature = None
        self._built_dates = {}
        self.changed = threading.Event()
        self.idle = threading.Event()
        self.idle.set()

    def request(self, request):
        with self._lock:
            if request == self._requested and time.monotonic() < self._next_check:
                return
            self._requested = self._pending = request
            self._next_check = time.monotonic() + _RESCAN_SECONDS
            if self._working:
                return
            self._working = True
            self.idle.clear()
        threading.Thread(target=self._work, daemon=True, name="last-played-dates").start()

    def _work(self):
        while True:
            with self._lock:
                request, self._pending = self._pending, None
            try:
                dates = self.build(request)
                with self._lock:
                    if request == self._requested:
                        previous = self._result
                        self._result = (request, dates)
                        if previous is None or previous[0].name != request.name or previous[1] != dates or previous[0].generation != request.generation:
                            self.changed.set()
            except Exception:
                log_exception("Failed to build last-played dates")
            with self._lock:
                if self._pending is None:
                    self._working = False
                    self.idle.set()
                    return

    def lookup(self, name, entries, generation, indices):
        with self._lock:
            result = self._result
        if result is None:
            return {}
        request, dates = result
        if request.name != name or request.generation != generation:
            return {}
        common = min(len(request.entries), len(entries))
        if request.entries[:common] != entries[:common]:
            return {}
        return {index: dates[index] for index in indices if index in dates and index < common}

    def _history(self, entries):
        result = []
        for index, entry in enumerate(entries):
            _yield(index)
            if not isinstance(entry, str) or entry.startswith("[L]"):
                continue
            if entry not in self._key_cache:
                self._key_cache[entry] = self._resolver.key_for_entry(entry)
            result.append((self._key_cache[entry], index))
        return tuple(result)

    @staticmethod
    def _signature(path):
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    def build(self, request):
        """Synchronous worker body, also usable for deterministic verification."""
        import json

        def scan_sources(folder, pattern):
            result = []
            for index, path in enumerate(sorted(folder.glob(pattern))):
                _yield(index)
                try:
                    result.append((path, self._signature(path)))
                except OSError:
                    pass
            return tuple(result)

        playlist_sources = scan_sources(self.playlists, "*.json")
        text_sources = scan_sources(self.sessions, "*.txt")
        signature = (request, playlist_sources, text_sources)
        if signature == self._built_signature:
            return self._built_dates

        if self._generation != request.generation:
            self._resolver = self.resolver_factory()
            self._generation = request.generation
            self._text_cache.clear()
            self._playlist_cache.clear()
            self._key_cache.clear()
        histories = {}
        for index, (path, source_signature) in enumerate(playlist_sources):
            _yield(index)
            try:
                cached = self._playlist_cache.get(path)
                if cached is None or cached[0] != source_signature:
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                    name = path.stem.casefold()
                    history = self._history(data.get("playlist", [])[:data.get("current_index", -1) + 1]) if data.get("infinite") else None
                    cached = (source_signature, name, history)
                    self._playlist_cache[path] = cached
                if cached[2] is not None:
                    histories[cached[1]] = cached[2]
            except (OSError, ValueError, TypeError):
                self._playlist_cache.pop(path, None)
        histories[request.name] = self._history(request.entries)
        sources = []
        for index, (path, source_signature) in enumerate(text_sources):
            _yield(index)
            try:
                cached = self._text_cache.get(path)
                if cached is None or cached[0] != source_signature:
                    events = parse_text(path.read_text(encoding="utf-8-sig", errors="replace"), path.name, self._resolver)
                    cached = (source_signature, events)
                    self._text_cache[path] = cached
                sources.append(cached[1])
            except (OSError, ValueError):
                self._text_cache.pop(path, None)
        sources.append(parse_session(request.session, self._resolver))
        dates = align_dates(histories, sources).get(request.name, {})
        self._built_signature = (request, playlist_sources, text_sources)
        self._built_dates = dates
        return dates


def _runtime_resolver():
    from _app_scripts.file.metadata import metadata_display

    return Resolver(tuple(state.metadata.anime_metadata.items()), tuple(state.metadata.file_metadata.items()),
                    metadata_display._file_play_key)


_cache = DateCache(_runtime_resolver)
_started = False


def _snapshot():
    from _app_scripts.file import session_stats
    from _app_scripts.file.metadata import metadata_fetch

    playlist = state.metadata.playlist
    if not playlist.get("infinite"):
        return None
    entries = tuple(playlist.get("playlist", [])[:playlist.get("current_index", -1) + 1])
    session = tuple(tuple(entry.get(field) for field in _SESSION_FIELDS)
                    for entry in tuple(session_stats.session_data)
                    if entry.get("type", "theme") not in ("scoreboard_score", "bonus_question"))
    return Request(str(playlist.get("name") or "<active>").casefold(), entries, session,
                   metadata_fetch.metadata_cache_generation)


def get_dates(indices, entries=None, current_index=None):
    """Rendering fast path: no disk reads, matching, or waiting for the worker."""
    from _app_scripts.file.metadata import metadata_fetch

    playlist = state.metadata.playlist
    if not playlist.get("infinite"):
        return {}
    active_entries = tuple(playlist.get("playlist", [])[:playlist.get("current_index", -1) + 1])
    if entries is not None and (
        current_index != playlist.get("current_index", -1)
        or tuple(entries[:current_index + 1]) != active_entries
    ):
        return {}
    return _cache.lookup(str(playlist.get("name") or "<active>").casefold(), active_entries,
                         metadata_fetch.metadata_cache_generation, indices)


def format_timestamp(when):
    hour = when.hour % 12 or 12
    return f"{when:%b} {when.day}, {when.year} at {hour}:{when.minute:02}:{when.second:02} {'PM' if when.hour >= 12 else 'AM'}"


def _completed_months(earlier, later):
    months = (later.year - earlier.year) * 12 + later.month - earlier.month
    anniversary = earlier.replace(year=later.year, month=later.month,
                                  day=min(earlier.day, monthrange(later.year, later.month)[1]))
    return months - (anniversary > later)


def short_date(when, now=None):
    now = now if now is not None else datetime.now()
    month = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")[when.month - 1]
    value = f"{month}-{when.day}"
    if when > now or _completed_months(when, now) >= 12:
        value += f"-{when.year % 100:02}"
    return value


def relative_age(when, now=None):
    """Keep nonzero calendar years/months/days, or hours/minutes for short gaps."""
    now = now if now is not None else datetime.now()
    future = when > now
    earlier, later = (now, when) if future else (when, now)
    seconds = int((later - earlier).total_seconds())
    if seconds < 60:
        return "in a moment" if future else "just now"
    months = _completed_months(earlier, later)
    years, months_part = divmod(months, 12)
    year, month = divmod(earlier.year * 12 + earlier.month - 1 + months, 12)
    anniversary = earlier.replace(year=year, month=month + 1,
                                  day=min(earlier.day, monthrange(year, month + 1)[1]))
    days = (later - anniversary).days
    if years or months_part or days:
        parts = [(years, "y"), (months_part, "m"), (days, "d")]
    else:
        hours, minutes = divmod(seconds // 60, 60)
        parts = [(hours, "h"), (minutes, "min")]
    value = " ".join(f"{count}{unit}" for count, unit in parts if count)
    return f"in {value}" if future else f"{value} ago"


def start():
    """Start lightweight polling on Tk; archive work never runs on this thread."""
    global _started
    if _started:
        return
    root = state.widgets.root
    if root is None:
        return
    _started = True

    def poll():
        try:
            if not root.winfo_exists():
                return
        except Exception:
            return
        try:
            request = _snapshot()
            if request is not None:
                _cache.request(request)
            if _cache.changed.is_set():
                _cache.changed.clear()
                playing = state.playback.currently_playing
                if request is not None and playing.get("filename") and playing.get("type") == "theme":
                    from _app_scripts.file.metadata import metadata_display

                    metadata_display.update_metadata_queue(state.metadata.playlist.get("current_index", -1))
        except Exception:
            log_exception("Failed to refresh last-played dates")
        root.after(1000, poll)

    poll()
