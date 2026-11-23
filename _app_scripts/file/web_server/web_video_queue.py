"""Host-only download controls for the upcoming playback queue."""

import hashlib
from itertools import chain, islice
import os

from core.game_state import state
from _app_scripts.file.metadata import metadata_fetch
from _app_scripts.playback import cache_download
from _app_scripts.playlists import entry_paths
from _app_scripts.queue_round.youtube import youtube_control, youtube_ui
from _app_scripts.search import search
from _app_scripts.theme import source_preferences


PAGE_SIZE = 15


def _queue_entries():
    active = state.lightning.fixed_lightning_round_playlist_data or {}
    queued = state.lightning.fixed_lightning_queue or {}
    if queued and (not active or queued.get('name') != active.get('name')):
        fixed, fixed_start = queued, 0
    else:
        fixed, fixed_start = active, max(0, active.get('current_index', -1) + 1)
    rounds = fixed.get('rounds', [])
    youtube = state.playback.youtube_queue or {}
    playlist = state.metadata.playlist
    items = playlist.get('playlist', [])
    start = max(0, playlist.get('current_index', -1) + 1)

    entries = chain(
        ((round_data.get('theme'), 'Fixed lightning', None) for round_data in islice(rounds, fixed_start, None)),
        [(youtube.get('filename'), 'YouTube queue', youtube)] if youtube else (),
        [(search.search_queue, 'Search queue', None)] if search.search_queue else (),
        ((item, 'Playlist', None) for item in islice(items, start, None)),
    )
    total = max(0, len(rounds) - fixed_start) + bool(youtube) + bool(search.search_queue)
    total += max(0, len(items) - start)
    return entries, total


def _entry_key(entry):
    filename, group, youtube = entry
    video_id = (youtube or {}).get('video_id') or (youtube or {}).get('url')
    return hashlib.sha256(repr((filename, group, video_id)).encode()).hexdigest()[:24]


def up_next_entry():
    """Resolve the entry shown in the host's Up Next panel and its round label."""
    youtube = state.playback.youtube_queue
    if youtube:
        return (youtube.get('filename'), 'YouTube queue', youtube), ''
    if search.search_queue:
        return (search.search_queue, 'Search queue', None), ''
    fixed = state.lightning.fixed_lightning_round_playlist_data or state.lightning.fixed_lightning_queue or {}
    rounds = fixed.get('rounds', [])
    next_round = fixed.get('current_index', -1) + 1
    if 0 <= next_round < len(rounds):
        round_data = rounds[next_round]
        return (round_data.get('theme'), 'Fixed lightning', None), f"[{round_data.get('type', '').upper()}]"
    playlist = state.metadata.playlist
    items = playlist.get('playlist', [])
    position = playlist.get('current_index', -1) + 1
    if 0 <= position < len(items):
        return (items[position], 'Playlist', None), ''
    return None, ''


def playlist_entry(source, position):
    if not isinstance(position, int) or not 0 <= position < len(source['items']):
        return None
    item = source['items'][position]
    if source['is_fixed']:
        return item.get('theme'), 'Fixed lightning', None
    return item, 'Playlist', None


def playlist_video_key(source, position):
    entry = playlist_entry(source, position)
    return _entry_key(entry) if entry else ''


def _downloadable(filename):
    if not filename or any(char in filename for char in '/\\:<>"|?*\0'):
        return False
    stem, extension = os.path.splitext(filename)
    return bool(stem and (cache_download.is_anisongdb_stream_file(filename)
                         or (cache_download.is_animethemes_stream_file(stem + '.webm')
                             and (extension.lower() == '.webm' or (
                                 extension.lower() == '.mp4' and metadata_fetch._filename_theme_slug(filename))))))


def _describe_entry(position, entry):
    item, group, youtube = entry
    filename = entry_paths.get_clean_filename(item) if isinstance(item, str) else ''
    path = entry_paths.get_file_path(item, require_on_disk=True) if filename else None
    youtube = youtube or (youtube_control.get_youtube_metadata_by_filename(filename) if filename else None)
    downloadable = not youtube and _downloadable(filename)
    if youtube:
        paths = (path, os.path.join('youtube', filename), os.path.join('youtube', 'archive', filename))
        ready = any(cache_download.is_nonempty_file(candidate) for candidate in paths)
        title = youtube_ui.get_youtube_display_title(youtube) or filename or 'YouTube video'
        status = {'source': 'YouTube', 'state': 'ready' if ready else 'online'}
    elif filename:
        title = filename
        status = cache_download.describe_download(filename, path)
        online_url = cache_download.get_theme_stream_url(item) if downloadable and not path else None
        online = bool(online_url)
        status['state'] = 'ready' if path else 'online' if online else 'missing'
        if not status['source'] and online:
            status['source'] = cache_download.DOWNLOAD_SOURCES.get(source_preferences.source_for_url(online_url), '')
    else:
        title = 'No theme video'
        status = {'source': '', 'state': 'missing'}
    return {'position': position, 'key': _entry_key(entry), 'title': title,
            'group': group, 'downloadable': downloadable, **status}


def queue_page(offset):
    entries, total = _queue_entries()
    offset = max(0, min(offset, (max(0, total - 1) // PAGE_SIZE) * PAGE_SIZE))
    page = islice(entries, offset, offset + PAGE_SIZE)
    return {'offset': offset, 'total': total, 'page_size': PAGE_SIZE,
            'rows': [_describe_entry(position, entry) for position, entry in enumerate(page, offset)]}


def up_next_status(entry):
    return _describe_entry(0, entry) if entry else None


def inline_status(playlist_source, indexes, include_next):
    return {
        'next': up_next_status(up_next_entry()[0]) if include_next else None,
        'playlist': [_describe_entry(position, entry) for position in indexes
                     if (entry := playlist_entry(playlist_source, position)) is not None],
    }


def _target_entry(scope, position, playlist_source):
    if scope == 'next':
        return up_next_entry()[0]
    if scope == 'playlist':
        return playlist_entry(playlist_source, position)
    entries, total = _queue_entries()
    return next(islice(entries, position, None), None) if 0 <= position < total else None


def selected_page(target, playlist_source):
    position = target.get('position')
    entry = _target_entry(target['scope'], position, playlist_source) if isinstance(position, int) else None
    row = _describe_entry(position, entry) if entry and _entry_key(entry) == target.get('key') else None
    return {'target': target, 'rows': [row] if row else []}


def request_download(position, key, source, *, scope='queue', playlist_source=None):
    if (not isinstance(position, int) or position < 0 or not isinstance(source, str)
            or source not in cache_download.DOWNLOAD_SOURCES):
        return 'Choose a queued theme and a download source.'
    entry = _target_entry(scope, position, playlist_source)
    if entry is None or _entry_key(entry) != key:
        return 'The queue changed. Select the video again.'
    row = _describe_entry(position, entry)
    if not row['downloadable']:
        return 'This video has no anime theme download option.'
    filename = entry_paths.get_clean_filename(entry[0])
    context = {'theme_entry': entry[0]} if entry_paths.parse_theme_reference(entry[0]) else {}
    if not cache_download.download_to_cache(filename, silent=True, source=source, manual=True, **context):
        return 'This video is already downloading.' if cache_download.is_downloading(filename) else 'Could not start the download.'
    return ''
