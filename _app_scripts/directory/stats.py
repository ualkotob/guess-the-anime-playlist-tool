# Stats display operations.
import re
import threading

from core.game_state import state
import _app_scripts.playlists.playlist as playlist_ops
import _app_scripts.theme.marks as playlist_marks
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.information.information_popup as information_popup
import _app_scripts.ui.lists as lists

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_stat_token = 0
_current_stat_groups = {}
_current_stat_title = ""


def _current_files():
    return playlist_ops.get_cached_deduplicated_files()


def show_year_stats():
    year_stats(_current_files())


def show_season_stats():
    season_stats(_current_files())


def show_artist_stats(sort='count'):
    artist_stats(_current_files(), sort)


def show_series_stats(sort='count'):
    series_stats(_current_files(), sort)


def show_title_stats(sort='alpha'):
    title_stats(_current_files(), sort)


def show_studio_stats(sort='count'):
    studio_stats(_current_files(), sort)


def show_tag_stats(sort='count'):
    tag_stats(_current_files(), sort)


def show_anilist_tag_stats(sort='count'):
    anilist_tag_stats(
        _current_files(),
        state.metadata.anilist_metadata,
        sort,
    )


def show_slug_stats(sort='count'):
    slug_stats(_current_files(), sort)


def show_type_stats():
    type_stats(_current_files())


# ===========================================================================
#  STATS DISPLAY
# ===========================================================================

def _run_stat_in_background(title, compute_fn, select_fn=None):
    global _stat_token
    _stat_token += 1
    token = _stat_token

    def _worker():
        try:
            groups = compute_fn()
        except Exception as e:
            print(f"[stat error] {e}")
            groups = []

        def _apply():
            if token != _stat_token:
                return
            show_directory_stat_groups(title, groups, select_fn=select_fn)

        state.widgets.root.after(0, _apply)

    threading.Thread(target=_worker, daemon=True).start()


def year_stats(files):
    def compute():
        year_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            season = data.get("season", "")
            year_str = season[-4:] if season and season[-4:].isdigit() else "Unknown"
            if year_str.isdigit():
                year = int(year_str)
                if year >= 2000:   group = str(year)
                elif year >= 1990: group = "1990s"
                elif year >= 1980: group = "1980s"
                elif year >= 1970: group = "1970s"
                elif year >= 1960: group = "1960s"
                else:              group = "Pre-60s"
            else:
                group = "Unknown"
            year_to_filenames.setdefault(group, []).append(filename)

        def sort_key(g):
            if g.isdigit(): return -int(g)
            elif g.endswith("s"): return -int(g[:4])
            elif g == "Pre-60s": return -1950
            else: return 9999

        return [(g, year_to_filenames[g]) for g in sorted(year_to_filenames, key=sort_key)]

    _run_stat_in_background("THEMES BY YEAR", compute)


def season_stats(files):
    def compute():
        season_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            s = data.get("season") or "Unknown"
            if s == "N/A":
                s = "Unknown"
            season_to_filenames.setdefault(s, []).append(filename)

        def season_sort_key(s):
            if s == "Unknown":
                return (9999, 4)
            try:
                season, year = s.split()
                return (int(year), {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}.get(season, 4))
            except Exception:
                return (9999, 4)

        return [(s, season_to_filenames[s]) for s in sorted(season_to_filenames, key=season_sort_key, reverse=True)]

    _run_stat_in_background("THEMES BY SEASON", compute)


def artist_stats(files, sort='count'):
    def compute():
        artist_to_filenames = {}
        for filename in files:
            file_data = metadata_fetch.get_file_metadata_by_name(filename)
            if not file_data:
                continue
            slug = file_data.get("slug")
            data = metadata_fetch.get_metadata(filename)
            for song in data.get("songs", []):
                if song.get("slug") == slug:
                    for artist in song.get("artist", []):
                        artist_to_filenames.setdefault(artist, []).append(filename)
                    break
        if sort == 'alpha':
            return sorted(artist_to_filenames.items(), key=lambda x: x[0].lower())
        return sorted(artist_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY ARTIST", compute)


def series_stats(files, sort='count'):
    def compute():
        series_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            series = data.get("series") or data.get("title", "Unknown")
            if isinstance(series, list):
                for s in series:
                    series_to_filenames.setdefault(s, []).append(filename)
            else:
                series_to_filenames.setdefault(series, []).append(filename)
        if sort == 'alpha':
            return sorted(series_to_filenames.items(), key=lambda x: x[0].lower())
        if sort == 'popularity':
            def _series_pop(item):
                _, files = item
                ranks = [metadata_fetch.get_metadata(fn).get("popularity") for fn in files]
                ranks = [r for r in ranks if r is not None]
                return min(ranks) if ranks else float('inf')
            return sorted(series_to_filenames.items(), key=_series_pop)
        return sorted(series_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY SERIES", compute)


def title_stats(files, sort='alpha'):
    def compute():
        title_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            title = data.get("title") or "Unknown"
            title_to_filenames.setdefault(title, []).append(filename)
        if sort == 'popularity':
            def _title_pop(item):
                _, files = item
                ranks = [metadata_fetch.get_metadata(fn).get("popularity") for fn in files]
                ranks = [r for r in ranks if r is not None]
                return min(ranks) if ranks else float('inf')
            return sorted(title_to_filenames.items(), key=_title_pop)
        return sorted(title_to_filenames.items(), key=lambda x: x[0].lower())

    _run_stat_in_background("THEMES BY TITLE", compute)


def studio_stats(files, sort='count'):
    def compute():
        studio_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            for studio in data.get("studios", []):
                studio_to_filenames.setdefault(studio, []).append(filename)
        if sort == 'alpha':
            return sorted(studio_to_filenames.items(), key=lambda x: x[0].lower())
        return sorted(studio_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY STUDIO", compute)


def tag_stats(files, sort='count'):
    def compute():
        tag_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            for tag in information_popup.get_tags(data):
                tag_to_filenames.setdefault(tag, []).append(filename)
        if sort == 'alpha':
            return sorted(tag_to_filenames.items(), key=lambda x: x[0].lower())
        return sorted(tag_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY TAG (MAL)", compute)


def anilist_tag_stats(files, anilist_metadata, sort='count'):
    def compute():
        tag_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            anilist_id = data.get("anilist")
            if not anilist_id:
                continue
            al_data = anilist_metadata.get(str(anilist_id), {})
            for tag in al_data.get("tags", []):
                name = tag.get("name")
                if name:
                    tag_to_filenames.setdefault(name, []).append(filename)
        if sort == 'alpha':
            return sorted(tag_to_filenames.items(), key=lambda x: x[0].lower())
        return sorted(tag_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY TAG (ANILIST)", compute)


def slug_stats(files, sort='count'):
    def compute():
        slug_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            slug = data.get("slug", "Unknown")
            slug_to_filenames.setdefault(slug, []).append(filename)
        if sort == 'alpha':
            return sorted(slug_to_filenames.items(), key=lambda x: x[0].lower())
        return sorted(slug_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY SLUG", compute)


def type_stats(files):
    def compute():
        type_to_filenames = {}
        for filename in files:
            data = metadata_fetch.get_metadata(filename)
            t = information_popup.get_format(data) or "Unknown"
            type_to_filenames.setdefault(t, []).append(filename)
        return sorted(type_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY TYPE", compute)


def _get_stat_group_name(key, value):
    label, files, total = value
    count = len(files)
    pct = round(count / total * 100, 1) if total else 0
    return f"{label} ({count}, {pct}%)"


def _select_stat_group(index):
    if index in _current_stat_groups:
        label, files, _ = _current_stat_groups[index]
        saved_title = _current_stat_title
        saved_groups = [(lbl, list(fls)) for _, (lbl, fls, _t) in sorted(_current_stat_groups.items())]
        lists.push_list_nav(lambda: show_directory_stat_groups(saved_title, saved_groups))
        lists.show_field_themes(group=list(files), title=label)


def show_directory_stat_groups(title, groups, select_fn=None):
    global _current_stat_groups, _current_stat_title
    lists.clear_list_nav()
    _current_stat_title = title
    total = sum(len(files) for _, files in groups)
    _current_stat_groups = {i: (label, list(files), total) for i, (label, files) in enumerate(groups)}
    lists.show_list(
        "directory_stat", state.widgets.right_column, _current_stat_groups,
        _get_stat_group_name, select_fn or _select_stat_group, -1, True, title=title,
    )


# ===========================================================================
#  THEMES BY PLAYLIST
# ===========================================================================

# (mode, menu label) — order shown in the per-playlist sort sub-menu.
# Every mode except the two "Playlist Order" entries deduplicates themes so a
# theme appears only once regardless of how many copies the playlist holds.
PLAYLIST_SORT_OPTIONS = [
    ('alpha_asc',  'Alphabetical (Ascending)'),
    ('alpha_desc', 'Alphabetical (Descending)'),
    ('pop_most',   'Most Popular'),
    ('pop_least',  'Least Popular'),
    ('newest',     'Newest'),
    ('oldest',     'Oldest'),
    ('order_asc',  'Playlist Order (Ascending)'),
    ('order_desc', 'Playlist Order (Descending)'),
    ('played',     'Most Played'),
]

# Holds (playlist_name, files) while its sort sub-menu is showing.
_current_playlist_sort = None


def show_user_playlists():
    _show_playlist_directory('user')


def show_system_playlists():
    _show_playlist_directory('system')


def _show_playlist_directory(scope):
    def compute():
        if scope == 'system':
            names = playlist_ops.get_playlists_dict(system_only=True).values()
        else:
            names = playlist_ops.get_playlists_dict(exclude_system=True).values()
        groups = []
        for name in names:
            data = playlist_marks.get_playlist(name) or {}
            groups.append((name, list(data.get('playlist', []))))
        return groups

    title = "PLAYLISTS (SYSTEM)" if scope == 'system' else "PLAYLISTS (USER)"
    _run_stat_in_background(title, compute, select_fn=_select_playlist_group)


def _select_playlist_group(index):
    """Clicking a playlist drills into its sort-options sub-menu."""
    if index in _current_stat_groups:
        label, files, _ = _current_stat_groups[index]
        saved_title = _current_stat_title
        saved_groups = [(lbl, list(fls)) for _, (lbl, fls, _t) in sorted(_current_stat_groups.items())]
        lists.push_list_nav(
            lambda: show_directory_stat_groups(saved_title, saved_groups, select_fn=_select_playlist_group))
        _show_playlist_sort_menu(label, list(files))


def _show_playlist_sort_menu(name, files):
    """List the sort options for a playlist; picking one lists its themes."""
    global _current_playlist_sort
    _current_playlist_sort = (name, list(files))
    content = {i: opt for i, opt in enumerate(PLAYLIST_SORT_OPTIONS)}
    lists.show_list(
        "playlist_sort", state.widgets.right_column, content,
        _get_playlist_sort_name, _select_playlist_sort, -1, True, title=name,
    )


def _get_playlist_sort_name(key, value):
    _mode, label = value
    return label


def _select_playlist_sort(index):
    if _current_playlist_sort is None or not (0 <= index < len(PLAYLIST_SORT_OPTIONS)):
        return
    name, files = _current_playlist_sort
    mode, _label = PLAYLIST_SORT_OPTIONS[index]
    saved = (name, list(files))
    lists.push_list_nav(lambda: _show_playlist_sort_menu(saved[0], saved[1]))
    show_playlist_themes(saved[0], list(saved[1]), mode)


# --- per-entry metadata keys --------------------------------------------------

def _alpha_key(entry):
    data = metadata_fetch.get_metadata(entry_paths.get_clean_filename(entry)) or {}
    return (data.get('eng_title') or data.get('title') or entry).lower()


def _pop_rank(entry):
    """Popularity rank (lower = more popular) or None when unknown."""
    rank = (metadata_fetch.get_metadata(entry_paths.get_clean_filename(entry)) or {}).get('popularity')
    return rank if isinstance(rank, (int, float)) else None


_SEASON_QUARTER = {'winter': 1, 'spring': 2, 'summer': 3, 'fall': 4}


def _season_year(entry):
    """Sortable season value, or None when unknown.

    Prefers the ``season`` field and folds the season quarter into the value
    (``year + quarter/10``) so anime from the same year still order
    Winter → Spring → Summer → Fall. Falls back to the bare year parsed from
    ``aired``/``release`` when no season is recorded."""
    data = metadata_fetch.get_metadata(entry_paths.get_clean_filename(entry)) or {}
    season_str = str(data.get('season') or '')
    m = re.search(r'\b(19|20)\d{2}\b', season_str)
    if m:
        quarter = next((q for name, q in _SEASON_QUARTER.items() if name in season_str.lower()), 0)
        return int(m.group(0)) + quarter / 10.0
    for val in (data.get('aired'), data.get('release')):
        if not val:
            continue
        m = re.search(r'\b(19|20)\d{2}\b', str(val))
        if m:
            return int(m.group(0))
    return None


# --- dedup + play counts ------------------------------------------------------

def _play_counts(files):
    """Map clean filename -> {'regular': n, 'lightning': n} over raw entries.

    Lightning copies are the playlist entries prefixed with ``[L]``.
    """
    counts = {}
    for entry in files:
        clean = entry_paths.get_clean_filename(entry)
        c = counts.setdefault(clean, {'regular': 0, 'lightning': 0})
        if str(entry).startswith('[L]'):
            c['lightning'] += 1
        else:
            c['regular'] += 1
    return counts


def _dedupe_entries(files):
    """One clean filename per theme, first-seen order. The ``[L]`` lightning
    prefix is stripped so deduped lists show plain filenames."""
    seen = set()
    order = []
    for entry in files:
        clean = entry_paths.get_clean_filename(entry)
        if clean not in seen:
            seen.add(clean)
            order.append(clean)
    return order


def _make_played_name_func(counts):
    """Label renderer that appends '(regular ▶ / lightning ⚡)' play counts."""
    def _name(key, value):
        base = lists.get_title(key, value)
        c = counts.get(entry_paths.get_clean_filename(value), {'regular': 0, 'lightning': 0})
        return f"{base}  ({c['regular']}▶ {c['lightning']}⚡)"
    return _name


def _build_playlist_theme_list(files, mode):
    """Return (ordered_entries, name_func) for the chosen sort mode.

    Playlist-order modes keep duplicate copies; everything else deduplicates.
    name_func is None unless a mode needs custom labels (Most Played).
    """
    if mode == 'order_asc':
        return list(files), None
    if mode == 'order_desc':
        return list(files)[::-1], None

    entries = _dedupe_entries(files)

    if mode == 'alpha_asc':
        entries.sort(key=_alpha_key)
    elif mode == 'alpha_desc':
        entries.sort(key=_alpha_key, reverse=True)
    elif mode == 'pop_most':
        # Most popular first (lowest rank), unknowns last.
        entries.sort(key=lambda e: (0, _pop_rank(e)) if _pop_rank(e) is not None else (1, 0))
    elif mode == 'pop_least':
        # Least popular first (highest rank), unknowns last.
        entries.sort(key=lambda e: (0, -_pop_rank(e)) if _pop_rank(e) is not None else (1, 0))
    elif mode == 'newest':
        entries.sort(key=lambda e: (0, -_season_year(e)) if _season_year(e) is not None else (1, 0))
    elif mode == 'oldest':
        entries.sort(key=lambda e: (0, _season_year(e)) if _season_year(e) is not None else (1, 0))
    elif mode == 'played':
        counts = _play_counts(files)
        # Sort by regular plays only; lightning copies are shown but don't rank.
        entries.sort(key=lambda e: -counts.get(entry_paths.get_clean_filename(e), {}).get('regular', 0))
        return entries, _make_played_name_func(counts)

    return entries, None


def show_playlist_themes(name, files, mode='order_asc'):
    """List a single playlist's themes ordered/deduplicated per the chosen mode."""
    ordered, name_func = _build_playlist_theme_list(files, mode)
    lists.show_field_themes(
        group=ordered, title=name,
        sort_key=lambda f: 0,   # preserve the ordering we just computed
        name_func=name_func,
    )
