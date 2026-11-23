from pathlib import Path

import pytest

from _app_scripts.file.web_server import web_video_queue
from _app_scripts.playback import anisongdb, cache_download
from _app_scripts.playlists import entry_paths
from _app_scripts.theme import source_preferences


VIDEO = b'\x1aE\xdf\xa3' + b'video-test-data'


class _MediaResponse:
    is_redirect = False

    def __init__(self, body, size=None):
        self.body = body
        self.headers = {'content-length': str(size if size is not None else len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body


@pytest.fixture
def queue_state(tmp_path, monkeypatch):
    state = web_video_queue.state
    monkeypatch.setattr(state.playback, 'youtube_queue', None)
    monkeypatch.setattr(state.lightning, 'fixed_lightning_queue', None)
    monkeypatch.setattr(state.lightning, 'fixed_lightning_round_playlist_data', None)
    monkeypatch.setattr(web_video_queue.search, 'search_queue', None)
    monkeypatch.setattr(state.metadata, 'playlist', {'playlist': ['[L]Show-OP1.webm'], 'current_index': -1})
    monkeypatch.setattr(state.metadata, 'directory_files', {})
    monkeypatch.setattr(cache_download, 'THEMES_CACHE_FOLDER', str(tmp_path / 'cache'))
    monkeypatch.setattr(cache_download, 'CACHE_METADATA_FILE', str(tmp_path / 'cache' / 'cache_metadata.json'))
    monkeypatch.setattr(cache_download, '_cache_limit_bytes', lambda: 1024)
    for name in ('active_downloads', 'cache_metadata', '_download_sources', '_download_errors',
                 'download_progress', 'download_cancel_flags'):
        monkeypatch.setattr(cache_download, name, {})
    monkeypatch.setattr(cache_download, '_manual_downloads', set())
    monkeypatch.setattr(cache_download, 'downloads_completed', 0)
    monkeypatch.setattr(cache_download, 'download_ui_update_pending', False)
    monkeypatch.setattr(source_preferences, 'DOWNLOAD_SOURCES_FILE', str(tmp_path / 'config' / 'sources.json'))
    monkeypatch.setattr(source_preferences, '_download_sources', {})
    monkeypatch.setattr(source_preferences, '_sources_loaded', False)
    return state


def test_anisongdb_matches_number_and_expands_catbox_filename(monkeypatch):
    monkeypatch.setattr(anisongdb.metadata_fetch, 'get_file_metadata_by_name',
                        lambda filename: {'mal': '1', 'slug': 'OP1'})

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {'songType': 'Opening 2', 'HQ': 'wrong.webm'},
                {'songType': 'Opening 1', 'HQ': 'correct.webm', 'MQ': 'https://files.catbox.moe/correct-mq.webm'},
            ]

    def post(url, *, json, timeout):
        assert url == 'https://anisongdb.com/api/mal_ids_request'
        assert json == {'mal_ids': [1]}
        return Response()

    monkeypatch.setattr(anisongdb.requests, 'post', post)
    assert anisongdb.get_video_urls('Show-OP1.webm') == [
        'https://files.catbox.moe/correct.webm', 'https://files.catbox.moe/correct-mq.webm',
    ]


def test_host_download_selects_playback_copy_and_survives_failed_replacement(queue_state, tmp_path, monkeypatch):
    local_file = tmp_path / 'Show-OP1.webm'
    local_file.write_bytes(VIDEO + b'library')
    queue_state.metadata.directory_files['Show-OP1.webm'] = str(local_file)
    monkeypatch.setattr(anisongdb, 'get_video_urls', lambda filename: ['https://files.catbox.moe/test.webm'])
    monkeypatch.setattr(cache_download, '_validate_downloaded_video', lambda path: True)
    monkeypatch.setattr(cache_download.requests, 'get', lambda *args, **kwargs: _MediaResponse(VIDEO))

    row = web_video_queue.queue_page(0)['rows'][0]
    assert (row['state'], row['source']) == ('ready', 'Local library')

    def download(source):
        assert web_video_queue.request_download(0, row['key'], source) == ''
        thread = cache_download.active_downloads.get('Show-OP1.webm')
        if thread:
            thread.join(timeout=2)
            assert not thread.is_alive()

    download('anisongdb')
    cache_download.load_cache_metadata()
    preferred = Path(entry_paths.get_file_path('[L]Show-OP1.webm'))
    assert preferred != local_file and preferred.read_bytes() == VIDEO
    selected = web_video_queue.queue_page(0)['rows'][0]
    assert (selected['state'], selected['source']) == ('ready', 'AniSongDB')
    monkeypatch.setattr(queue_state.config, 'theme_online_source', 'animethemes_only')
    monkeypatch.setattr(queue_state.config, 'theme_allow_excluded_downloads', False)
    entry = '[L]Show-OP1.webm'
    assert cache_download.select_theme_entry(entry) == entry
    assert cache_download.resolve_playable_path('Show-OP1.webm', entry, str(local_file), False) == (str(preferred), False)

    monkeypatch.setattr(cache_download.requests, 'get',
                        lambda *args, **kwargs: _MediaResponse(VIDEO, size=len(VIDEO) + 10))
    download('animethemes')
    selected = web_video_queue.queue_page(0)['rows'][0]
    assert selected['source'] == 'AniSongDB'
    assert 'AnimeThemes download failed' in selected['error']
    assert preferred.read_bytes() == VIDEO
    assert not list(preferred.parent.glob('*.part'))


def test_host_download_rejects_a_stale_queue_row(queue_state, monkeypatch):
    stale = web_video_queue.queue_page(0)['rows'][0]
    queue_state.metadata.playlist['playlist'][0] = 'Other-ED1.webm'
    monkeypatch.setattr(cache_download, 'download_to_cache',
                        lambda *args, **kwargs: pytest.fail('A stale row started a download.'))
    assert 'queue changed' in web_video_queue.request_download(0, stale['key'], 'animethemes')


def test_infinite_playlist_candidates_appear_only_when_queued(queue_state):
    playlist = queue_state.metadata.playlist
    playlist.update(infinite=True, speculative_tail=['Candidate-OP2.webm'])

    page = web_video_queue.queue_page(0)
    assert page['total'] == 1
    assert [row['title'] for row in page['rows']] == ['Show-OP1.webm']

    playlist['playlist'].append(playlist['speculative_tail'].pop(0))
    page = web_video_queue.queue_page(0)
    assert page['total'] == 2
    assert [row['title'] for row in page['rows']] == ['Show-OP1.webm', 'Candidate-OP2.webm']


def test_inline_status_and_downloads_follow_the_displayed_entries(queue_state, monkeypatch):
    items = queue_state.metadata.playlist['playlist']
    items.append('Next-ED1.webm')
    queue_state.metadata.playlist['current_index'] = 0
    monkeypatch.setattr(web_video_queue.search, 'search_queue', 'Search-OP2.webm')
    cache_download._download_errors['Show-OP1.webm'] = 'AnimeThemes download failed.'
    cache_download.active_downloads['Search-OP2.webm'] = object()
    cache_download._download_sources['Search-OP2.webm'] = 'anisongdb'
    playlist_source = {'items': items, 'is_fixed': False}
    status = web_video_queue.inline_status(playlist_source, [0, 1, -1], include_next=True)

    assert status['next']['title'] == 'Search-OP2.webm'
    assert status['next']['downloading'] == 'AniSongDB'
    shown, upcoming = status['playlist']
    assert shown['key'] == web_video_queue.playlist_video_key(playlist_source, 0)
    assert shown['error'] == 'AnimeThemes download failed.'
    assert upcoming['title'] == 'Next-ED1.webm'

    target = {'scope': 'playlist', 'position': 0, 'key': shown['key']}
    assert web_video_queue.selected_page(target, playlist_source)['rows'] == [shown]
    calls = []
    monkeypatch.setattr(cache_download, 'download_to_cache', lambda *args, **kwargs: calls.append((args, kwargs)) or True)
    assert web_video_queue.request_download(0, shown['key'], 'anisongdb', scope='playlist',
                                            playlist_source=playlist_source) == ''
    assert calls == [(('Show-OP1.webm',), {'silent': True, 'source': 'anisongdb', 'manual': True})]

    items.reverse()
    assert web_video_queue.selected_page(target, playlist_source)['rows'] == []
