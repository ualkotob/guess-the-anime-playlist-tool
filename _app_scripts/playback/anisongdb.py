"""Find the AniSongDB video links for a queued anime theme."""

import re
import unicodedata
from urllib.parse import urlsplit

import requests

from _app_scripts.file.metadata import metadata_fetch


MEDIA_HOSTS = frozenset({
    'files.catbox.moe', 'litter.catbox.moe', 'v.animethemes.moe',
    'openings.moe', 'ladist1.catbox.video', 'ladist2.catbox.video',
    'naedist.animemusicquiz.com', 'eudist.animemusicquiz.com',
})


def is_media_url(url):
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname in MEDIA_HOSTS
                and parts.netloc.lower() == parts.hostname
                and parts.path.lower().endswith(('.webm', '.mp4')))
    except ValueError:
        return False


def _song_key(value):
    normalized = unicodedata.normalize('NFKC', value or '').casefold()
    return ''.join(char for char in normalized if char.isalnum())


def _theme_identity(filename):
    data = metadata_fetch.get_file_metadata_by_name(filename) or {}
    slug = data.get('slug') or metadata_fetch._filename_theme_slug(filename)
    mal_id = data.get('mal')
    if str(mal_id).isdecimal() and slug:
        song = next((song for song in data.get('songs', []) if song.get('slug') == slug), {})
        return int(mal_id), slug, song.get('title')

    anime = metadata_fetch.fetch_animethemes_metadata(filename, split=False, timeout=15) or {}
    mal_id = metadata_fetch.get_external_site_id(anime, 'MyAnimeList')
    if str(mal_id).isdecimal():
        for theme in anime.get('animethemes', []):
            for entry in theme.get('animethemeentries', []):
                if any(video.get('basename') == filename for video in entry.get('videos', [])):
                    return int(mal_id), theme.get('slug'), (theme.get('song') or {}).get('title')
    raise ValueError('Could not identify this theme for AniSongDB.')


def get_video_urls(filename):
    mal_id, slug, title = _theme_identity(filename)
    response = requests.post('https://anisongdb.com/api/mal_ids_request',
                             json={'mal_ids': [mal_id]}, timeout=15)
    response.raise_for_status()
    songs = response.json()

    numbered = re.fullmatch(r'(OP|ED)(\d+)', slug or '', re.IGNORECASE)
    if numbered:
        kind = 'Opening' if numbered[1].upper() == 'OP' else 'Ending'
        song_type = f'{kind} {int(numbered[2])}'
        matches = [song for song in songs if song.get('songType') == song_type]
        if len(matches) > 1:
            matches = [song for song in matches if title and _song_key(song.get('songName')) == _song_key(title)]
    elif re.fullmatch(r'IN\d*', slug or '', re.IGNORECASE) and title:
        matches = [song for song in songs if song.get('songType') == 'Insert Song'
                   and _song_key(song.get('songName')) == _song_key(title)]
    else:
        matches = []

    if len(matches) != 1:
        raise ValueError('AniSongDB has no unambiguous match for this theme.')
    urls = []
    for quality in ('HQ', 'MQ'):
        link = matches[0].get(quality) or ''
        # The API commonly returns only a Catbox filename.
        if re.fullmatch(r'[a-zA-Z0-9_-]+\.(?:webm|mp4)', link, re.IGNORECASE):
            link = f'https://files.catbox.moe/{link}'
        urls.append(link)
    urls = list(dict.fromkeys(url for url in urls if is_media_url(url)))
    if not urls:
        raise ValueError('AniSongDB has no supported video link for this theme.')
    return urls
