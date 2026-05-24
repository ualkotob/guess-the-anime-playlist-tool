# _app_scripts/stats_ops.py
# Stats display operations extracted from playlist_ops.py
import threading

# ---------------------------------------------------------------------------
# Injected context (populated by set_context())
# ---------------------------------------------------------------------------
_root = None
_right_column = None
_get_metadata = None
_get_file_metadata_by_name = None
_get_tags = None
_get_format = None
_show_field_themes = None
_show_list = None
_push_list_nav = None
_clear_list_nav = None

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_stat_token = 0
_current_stat_groups = {}
_current_stat_title = ""

# ---------------------------------------------------------------------------
# set_context()
# ---------------------------------------------------------------------------
def set_context(
    root, right_column,
    get_metadata, get_file_metadata_by_name,
    get_tags, get_format,
    show_field_themes, show_list,
    push_list_nav=None, clear_list_nav=None,
):
    global _root, _right_column
    global _get_metadata, _get_file_metadata_by_name
    global _get_tags, _get_format
    global _show_field_themes, _show_list
    global _push_list_nav, _clear_list_nav

    _root = root
    _right_column = right_column
    _get_metadata = get_metadata
    _get_file_metadata_by_name = get_file_metadata_by_name
    _get_tags = get_tags
    _get_format = get_format
    _show_field_themes = show_field_themes
    _show_list = show_list
    _push_list_nav = push_list_nav
    _clear_list_nav = clear_list_nav


# ===========================================================================
#  STATS DISPLAY
# ===========================================================================

def _run_stat_in_background(title, compute_fn):
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
            show_directory_stat_groups(title, groups)

        _root.after(0, _apply)

    threading.Thread(target=_worker, daemon=True).start()


def year_stats(files):
    def compute():
        year_to_filenames = {}
        for filename in files:
            data = _get_metadata(filename)
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
            data = _get_metadata(filename)
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
            file_data = _get_file_metadata_by_name(filename)
            if not file_data:
                continue
            slug = file_data.get("slug")
            data = _get_metadata(filename)
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
            data = _get_metadata(filename)
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
                ranks = [_get_metadata(fn).get("popularity") for fn in files]
                ranks = [r for r in ranks if r is not None]
                return min(ranks) if ranks else float('inf')
            return sorted(series_to_filenames.items(), key=_series_pop)
        return sorted(series_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY SERIES", compute)


def studio_stats(files, sort='count'):
    def compute():
        studio_to_filenames = {}
        for filename in files:
            data = _get_metadata(filename)
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
            data = _get_metadata(filename)
            for tag in _get_tags(data):
                tag_to_filenames.setdefault(tag, []).append(filename)
        if sort == 'alpha':
            return sorted(tag_to_filenames.items(), key=lambda x: x[0].lower())
        return sorted(tag_to_filenames.items(), key=lambda x: (-len(x[1]), x[0].lower()))

    _run_stat_in_background("THEMES BY TAG (MAL)", compute)


def anilist_tag_stats(files, anilist_metadata, sort='count'):
    def compute():
        tag_to_filenames = {}
        for filename in files:
            data = _get_metadata(filename)
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
            data = _get_metadata(filename)
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
            data = _get_metadata(filename)
            t = _get_format(data) or "Unknown"
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
        if _push_list_nav:
            saved_title = _current_stat_title
            saved_groups = [(lbl, list(fls)) for _, (lbl, fls, _t) in sorted(_current_stat_groups.items())]
            _push_list_nav(lambda: show_directory_stat_groups(saved_title, saved_groups))
        _show_field_themes(group=list(files), title=label)


def show_directory_stat_groups(title, groups):
    global _current_stat_groups, _current_stat_title
    if _clear_list_nav:
        _clear_list_nav()
    _current_stat_title = title
    total = sum(len(files) for _, files in groups)
    _current_stat_groups = {i: (label, list(files), total) for i, (label, files) in enumerate(groups)}
    _show_list(
        "directory_stat", _right_column, _current_stat_groups,
        _get_stat_group_name, _select_stat_group, -1, True, title=title,
    )
