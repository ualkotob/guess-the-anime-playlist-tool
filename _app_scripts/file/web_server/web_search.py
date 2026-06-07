"""Web answer-server search/result helpers.

Pure data-shaping logic that backs the web server's theme search and host
panels: building play-count/series maps, formatting a single theme result dict,
the autocomplete title list, duration formatting, the menu-registry invoker, and
the standard theme-queue toggle.

Sibling helpers are imported directly, including the playback hub
``transport.play_video``. Callers reach this module's helpers as
``web_search.X`` (no main aliases).
"""

from core.game_state import state

from _app_scripts.search import search as search_ops
from _app_scripts.file.metadata import metadata_fetch, metadata_display
from _app_scripts.information import information_popup
from _app_scripts.playback import cache_download, transport
from _app_scripts.ui import menu_registry


def get_all_anime_titles():
    """Return sorted unique anime display titles from the metadata cache for autocomplete."""
    seen = set()
    titles = []
    for data in metadata_fetch._metadata_cache.values():
        if not isinstance(data, dict):
            continue
        t = metadata_display.get_display_title(data)
        if t and t != "No Title Found" and t not in seen:
            seen.add(t)
            titles.append(t)
    return sorted(titles)


def _invoke_registry_by_id(item_id: str):
    """Look up a menu registry item by id and call its command (searches submenus recursively)."""
    def _search(items):
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("id") == item_id:
                cmd = item.get("command")
                if callable(cmd):
                    cmd()
                return True
            if _search(item.get("submenu") or []):
                return True
        return False
    registry = menu_registry.get_menu_registry()
    for section in registry.values():
        if isinstance(section, list):
            if _search(section):
                return True
    return False


def _fmt_seconds(seconds) -> str:
    """Format a duration in seconds as M:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02}"


def _build_play_maps():
    """Build play-count and series-play maps from the current playlist history."""
    playlist = state.metadata.playlist
    _pl = playlist.get('playlist', [])
    _cur_idx = playlist.get('current_index', 0)
    _played = _pl[:_cur_idx + 1]
    _play_count_map = {}
    _play_last_map = {}
    for _i, _item in enumerate(_played):
        _f = _item[3:] if _item.startswith('[L]') else _item
        _k = metadata_display._play_name_key(_f)
        _play_count_map[_k] = _play_count_map.get(_k, 0) + 1
        _play_last_map[_k] = _i
    _series_play_map = metadata_display._build_played_series_map(_played, _cur_idx)
    return _play_count_map, _play_last_map, _series_play_map, _cur_idx


def _build_theme_web_result(fn, _play_count_map, _play_last_map, _series_play_map, _cur_idx, query_lower=''):
    """Build a single theme result dict for web push_theme_search_results / push_directory_themes."""
    meta = metadata_fetch.get_metadata(fn)
    title_en = str(meta.get('eng_title') or '').strip()
    title_jp = str(meta.get('title') or '').strip()
    title = title_en or title_jp or fn
    slug = meta.get('slug') or ''
    song_title = ''
    artist_name = ''
    for s in (meta.get('songs') or []):
        if s.get('slug') == slug:
            song_title = s.get('title') or ''
            artist_name = metadata_fetch.get_artists_string(s.get('artist') or [], total=False)
            break
    _fn_series = metadata_display.series_set(meta)
    _sp_count = sum(_series_play_map[_s]['count'] for _s in _fn_series if _s in _series_play_map)
    _sp_last = min((_series_play_map[_s]['last_idx'] for _s in _fn_series if _s in _series_play_map), default=None)
    _pk = metadata_display._play_name_key(fn)
    return {
        'filename': fn,
        'title': title,
        'title_en': title_en,
        'title_jp': title_jp,
        'slug': slug,
        'song': song_title,
        'artist': artist_name,
        'season': str(meta.get('season') or '').strip(),
        'format': str(information_popup.get_format(meta) or '').strip(),
        'studio': ', '.join([str(x).strip() for x in (meta.get('studios') or []) if str(x).strip()]),
        'song_match': bool(query_lower and song_title and query_lower in song_title.lower()),
        'artist_match': bool(query_lower and artist_name and query_lower in artist_name.lower()),
        'plays': _play_count_map.get(_pk, 0),
        'plays_ago': (_cur_idx - _play_last_map[_pk]) if _pk in _play_last_map and _play_last_map[_pk] < _cur_idx else None,
        'series_plays': _sp_count,
        'series_plays_ago': (_cur_idx - _sp_last) if _sp_last is not None and _sp_last < _cur_idx else None,
    }


def _queue_theme_standard(fn: str):
    """Queue a specific theme file as search_queue, or dequeue it if already queued."""
    if not fn:
        return
    if search_ops.search_queue == fn:
        search_ops.search_queue = None
        metadata_display.up_next_text()
    else:
        search_ops.search_queue = fn
        if not state.widgets.player.is_playing():
            transport.play_video()
            return
        metadata_display.up_next_text()
    cache_download.prefetch_next_themes()
