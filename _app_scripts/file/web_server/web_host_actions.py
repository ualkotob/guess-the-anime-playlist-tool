"""Web host action dispatcher — extracted from guess_the_anime.py.

Handles remote control commands sent by the web host controller (web_server callback).
Uses the _main module-reference pattern: main injects itself via set_context(main_module=...)
and the dispatcher reaches main-resident state and helpers via _main.X.
"""
import copy
import os
import json
import threading
from datetime import datetime

from core.game_state import state
import _app_scripts.file.web_server.web_server as web_server
import _app_scripts.queue_round.lightning_rounds.peek_dispatch as peek_dispatch
import _app_scripts.playback.music as music
import _app_scripts.bonus.bonus as bonus
import _app_scripts.bonus.buzz as buzz
import _app_scripts.bonus.answers as bonus_answers
import _app_scripts.playlists.playlist as playlist_ops

_main = None


def set_context(*, main_module):
    global _main
    _main = main_module


def _handle_host_action(action: str, data: dict):
    """Dispatch remote control commands from the web host controller."""
    def _dispatch():

        def _get_web_playlist_source():
            if _main.fixed_lightning_round_playlist_data and _main.fixed_lightning_round_playlist_data.get("rounds"):
                rounds = _main.fixed_lightning_round_playlist_data.get("rounds", [])
                current_index = _main.fixed_lightning_round_playlist_data.get("current_index", 0)
                return {
                    "is_fixed": True,
                    "items": rounds,
                    "current_index": current_index,
                    "counter": f'{current_index + 1}/{len(rounds)}' if rounds else '0/0',
                    "label": _main.fixed_lightning_round_playlist_data.get('name') or 'Fixed Playlist',
                }
            items = _main.playlist.get("playlist", [])
            current_index = _main.playlist.get("current_index", -1)
            if _main.playlist.get("infinite", False):
                out_of = playlist_ops.total_infinite_files - len(playlist_ops.cached_skipped_themes)
                counter = f'∞/{out_of}'
            else:
                out_of = len(items)
                counter = f'{current_index+1}/{out_of}'
            return {
                "is_fixed": False,
                "items": items,
                "current_index": current_index,
                "counter": counter,
                "label": _main.playlist.get('name') or 'Playlist',
            }

        if action == 'invoke':
            item_id = str(data.get('id', '')).strip()
            if item_id:
                _main._invoke_registry_by_id(item_id)
                _main._push_web_toggles()
                _main._push_web_marks()
        elif action == 'queue_peek_variant':
            variant = str(data.get('variant', '')).strip()
            mute = bool(data.get('mute', False))
            if variant and variant in peek_dispatch._PEEK_VARIANT_LABELS:
                _main._queue_peek_variant(variant, mute=mute)
            else:
                _main._queue_peek_random(mute=mute)
            _main._push_web_toggles()
        elif action == 'set_peek_variant':
            # Set queued variant without touching the round toggle (used by live tgl_peek dropdown)
            variant = str(data.get('variant', '')).strip()
            if variant and variant in peek_dispatch._PEEK_VARIANT_LABELS:
                peek_dispatch._queued_peek_variant[0] = variant
            else:
                peek_dispatch._queued_peek_variant[0] = None
            _main._push_web_toggles()
        elif action in ('stop_queues', 'stop_lightning'):
            _main.stop_all_queues()
            _main._push_web_toggles()
        elif action == 'seek':
            ms = int(data.get('position_ms', 0))
            _main.seek_to(ms)
        elif action == 'seek_near_end':
            state.widgets.root.after(0, lambda: _main._invoke_registry_by_id("skip_to_end_ff"))
        elif action == 'set_volume':
            vol = max(0, min(100, int(data.get('volume', 100))))
            _main.set_volume(vol)
        elif action == 'set_bgm_modifier':
            state.controls.bgm_volume = max(0.0, min(1.5, float(data.get('modifier', 1.0))))
            _main._sync_control_globals()
            if music.music_loaded:
                _main.set_volume(state.controls.volume_level)
            _main.save_config()
        elif action == 'set_bzz_modifier':
            _main.bonus_settings.setdefault('buzzer', dict(_main.BONUS_SETTINGS_DEFAULT['buzzer']))['sound_volume'] = max(0.0, min(1.5, float(data.get('modifier', 1.0))))
            _main.save_config()
        elif action == 'set_strm_boost':
            state.controls.stream_volume_boost = max(-100, min(100, int(data.get('boost', 0))))
            _main._sync_control_globals()
            _main.set_volume(state.controls.volume_level)
            _main.save_config()
        elif action == 'set_autoplay':
            _main.set_autoplay_mode(max(0, min(3, int(data.get('mode', 0)))))
        elif action == 'request_state':
            web_server.push_playback_state(
                _main.projected_player_time, state.widgets.player.get_length(), state.widgets.player.is_playing(), state.controls.volume_level, state.controls.autoplay_toggle, state.controls.bgm_volume,
                bzz_modifier=_main.bonus_settings.get('buzzer', _main.BONUS_SETTINGS_DEFAULT['buzzer']).get('sound_volume', 1.0),
                strm_boost=state.controls.stream_volume_boost
            )
        elif action == 'toggle_scoreboard':
            # Follow the menu registry's open/close items so behavior matches UI menu
            try:
                if _main.is_scoreboard_running():
                    _main._invoke_registry_by_id('close_scoreboard')
                else:
                    _main._invoke_registry_by_id('open_scoreboard')
            except Exception:
                # Fall back to visibility toggle if registry items unavailable
                _main._invoke_registry_by_id('scoreboard_toggle')
            _main._push_web_toggles()
            _main._push_web_marks()
        elif action == 'reset_session_history':
            _main.reset_session_history(confirm=False)
            _main._push_web_toggles()
        elif action == 'get_youtube_list':
            def _vid_date(vid):
                da = vid.get("date_added")
                if da:
                    try: return datetime.fromisoformat(da)
                    except (ValueError, TypeError): pass
                ud = vid.get("upload_date", "")
                if ud:
                    try: return datetime.strptime(ud, "%Y%m%d")
                    except (ValueError, TypeError): pass
                return datetime(1900, 1, 1)
            videos = []
            for vid_id, vid in _main.youtube_metadata.get("videos", {}).items():
                if vid.get("archived", False):
                    continue
                full_title = (vid.get("custom_title") or vid.get("title") or "")
                start = vid.get("start") or 0
                end = vid.get("end") or vid.get("duration") or 0
                dur = _main._fmt_seconds(round(end - start)) if end else _main._fmt_seconds(vid.get("duration") or 0)
                short_title = _main.shorten_youtube_title(full_title).strip()
                videos.append({"id": vid_id, "title": short_title or full_title, "full_title": full_title, "duration": dur, "_date": _vid_date(vid)})
            videos.sort(key=lambda v: v.pop("_date"), reverse=True)
            queued_id = (_main.youtube_queue or {}).get("url")
            web_server.push_youtube_list(videos, queued_id)
        elif action == 'get_archived_youtube_list':
            def _arc_date(vid):
                ad = vid.get("archived_date")
                if ad:
                    try: return datetime.fromisoformat(ad)
                    except (ValueError, TypeError): pass
                return datetime(1900, 1, 1)
            videos = []
            for vid_id, vid in _main.youtube_metadata.get("videos", {}).items():
                if not vid.get("archived", False):
                    continue
                full_title = (vid.get("custom_title") or vid.get("title") or "")
                start = vid.get("start") or 0
                end = vid.get("end") or vid.get("duration") or 0
                dur = _main._fmt_seconds(round(end - start)) if end else _main._fmt_seconds(vid.get("duration") or 0)
                short_title = _main.shorten_youtube_title(full_title).strip()
                videos.append({"id": vid_id, "title": short_title or full_title, "full_title": full_title, "duration": dur, "_date": _arc_date(vid)})
            videos.sort(key=lambda v: v.pop("_date"), reverse=True)
            queued_id = (_main.youtube_queue or {}).get("url")
            web_server.push_archived_youtube_list(videos, queued_id)
        elif action in ('queue_youtube', 'queue_archived_youtube'):
            video_id = str(data.get('video_id', '')).strip()
            if video_id:
                video = _main.get_youtube_metadata_from_index(key_id=video_id)
                _main._set_youtube_queue(video)
                _main.up_next_text()
        elif action == 'get_fixed_lightning_list':
            _main.load_fixed_lightning_rounds(filter_missing_themes=True)
            rounds = []
            for i, r in enumerate(_main.fixed_lightning_rounds_list):
                rounds.append({
                    "index": i,
                    "name": r.get("name", ""),
                    "duration": _main._fmt_seconds(r.get("total_duration", 0)),
                    "description": r.get("description", ""),
                })
            queued_name = (_main.fixed_lightning_queue or {}).get("name")
            web_server.push_fixed_lightning_list(rounds, queued_name)
        elif action == 'queue_fixed_lightning':
            idx = data.get('index')
            if idx is not None:
                _main.queue_fixed_lightning_round(int(idx))
                _main.up_next_text()
        elif action == 'queue_fixed_lightning_randomized':
            idx = data.get('index')
            if idx is not None:
                _main._queue_fixed_lightning_round_by_index(int(idx), randomize=True)
        elif action in ('play_fixed_lightning_now', 'play_fixed_lightning_now_randomized'):
            idx = data.get('index')
            if idx is not None:
                _main._play_fixed_lightning_round_now(int(idx), randomize=(action == 'play_fixed_lightning_now_randomized'))
        elif action == 'get_rules_list':
            files = _main.get_available_rules_files()
            web_server.push_rules_list(files, _main.selected_rules_file)
        elif action == 'select_rules_file':
            new_file = str(data.get('file', '')).strip()
            if new_file in _main.get_available_rules_files():
                _main.selected_rules_file = new_file
                _main.scoreboard_rules = _main.load_rules(_main.selected_rules_file)
                _main.save_config()
                _main.set_rules()
                _main._push_web_toggles()
        elif action == 'get_playlist_list':
            names = list(_main.get_playlists_dict(exclude_system=True).values())
            system_names = list(_main.get_playlists_dict(system_only=True).values())
            web_server.push_playlist_list(names, system_names, _main.playlist.get('name'), changed=_main._playlist_has_unsaved_changes())
        elif action == 'select_playlist':
            target = str(data.get('name', '')).strip()
            all_pl = _main.get_playlists_dict()
            if target and target in all_pl.values():
                _main._load_playlist_by_name(target, save_first=bool(data.get('save_first')))
        elif action == 'get_lightning_presets_list':
            presets = sorted(_main.saved_lightning_mode_settings.keys())
            web_server.push_lightning_presets_list(presets, _main.selected_light_mode_settings)
        elif action == 'select_lightning_preset':
            preset_name = str(data.get('name', '')).strip()
            if preset_name == '' or preset_name in _main.saved_lightning_mode_settings:
                _main.selected_light_mode_settings = preset_name
                if preset_name and preset_name in _main.saved_lightning_mode_settings:
                    _main.lightning_mode_settings.clear()
                    _main.lightning_mode_settings.update(_main.update_lightning_mode_settings(
                        copy.deepcopy(_main.saved_lightning_mode_settings[preset_name])
                    ))
                else:
                    _main.lightning_mode_settings.clear()
                    _main.lightning_mode_settings.update(_main.update_lightning_mode_settings(
                        copy.deepcopy(_main.lightning_mode_settings_default)
                    ))
                _main.save_config()
                _main._push_web_toggles()
        elif action == 'search_themes':
            query = str(data.get('query', '')).strip()
            if query:
                def _run_search(q=query):
                    _play_count_map, _play_last_map, _series_play_map, _cur_idx = _main._build_play_maps()
                    raw = _main.search_playlist(q)
                    results = [_main._build_theme_web_result(fn, _play_count_map, _play_last_map, _series_play_map, _cur_idx, query_lower=q.lower()) for fn in raw]
                    web_server.push_theme_search_results(results, _main.playlist.get('infinite', False), q)
                threading.Thread(target=_run_search, daemon=True).start()

        elif action == 'get_directory_groups':
            stat_type = str(data.get('stat_type', '')).strip()
            sid = data.get('_sid')
            def _run_dir_groups(st=stat_type, _sid=sid):
                # Parse base type and optional sort suffix
                _sort = 'count'
                _base = st
                for _suffix in ('_alpha', '_popularity'):
                    if st.endswith(_suffix):
                        _sort = _suffix[1:]  # strip leading '_'
                        _base = st[:-len(_suffix)]
                        break

                groups_raw = []
                try:
                    if _base == 'artist':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            fd = _main.get_file_metadata_by_name(fn)
                            if not fd: continue
                            slug = fd.get('slug')
                            meta = _main.get_metadata(fn)
                            for song in meta.get('songs', []):
                                if song.get('slug') == slug:
                                    for artist in song.get('artist', []):
                                        d.setdefault(artist, []).append(fn)
                                    break
                        if _sort == 'alpha':
                            groups_raw = sorted(d.items(), key=lambda x: x[0].lower())
                        else:
                            groups_raw = sorted(d.items(), key=lambda x: (-len(x[1]), x[0].lower()))
                    elif _base == 'series':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            series = meta.get('series') or meta.get('title', 'Unknown')
                            if isinstance(series, list):
                                for s in series: d.setdefault(s, []).append(fn)
                            else:
                                d.setdefault(series, []).append(fn)
                        if _sort == 'alpha':
                            groups_raw = sorted(d.items(), key=lambda x: x[0].lower())
                        elif _sort == 'popularity':
                            def _spop(item):
                                ranks = [_main.get_metadata(fn).get('popularity') for fn in item[1]]
                                ranks = [r for r in ranks if r is not None]
                                return min(ranks) if ranks else float('inf')
                            groups_raw = sorted(d.items(), key=_spop)
                        else:
                            groups_raw = sorted(d.items(), key=lambda x: (-len(x[1]), x[0].lower()))
                    elif _base == 'season':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            s = meta.get('season') or 'Unknown'
                            if s == 'N/A': s = 'Unknown'
                            d.setdefault(s, []).append(fn)
                        def _sk(s):
                            if s == 'Unknown': return (9999, 4)
                            try:
                                sn, yr = s.split()
                                return (int(yr), {'Winter':0,'Spring':1,'Summer':2,'Fall':3}.get(sn, 4))
                            except: return (9999, 4)
                        groups_raw = [(s, d[s]) for s in sorted(d, key=_sk, reverse=True)]
                    elif _base == 'year':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            season = meta.get('season', '')
                            yr = season[-4:] if season and season[-4:].isdigit() else 'Unknown'
                            if yr.isdigit():
                                y = int(yr)
                                if y >= 2000: g = str(y)
                                elif y >= 1990: g = '1990s'
                                elif y >= 1980: g = '1980s'
                                elif y >= 1970: g = '1970s'
                                elif y >= 1960: g = '1960s'
                                else: g = 'Pre-60s'
                            else:
                                g = 'Unknown'
                            d.setdefault(g, []).append(fn)
                        def _yk(g):
                            if g.isdigit(): return -int(g)
                            elif g.endswith('s'): return -int(g[:4])
                            elif g == 'Pre-60s': return -1950
                            else: return 9999
                        groups_raw = [(g, d[g]) for g in sorted(d, key=_yk)]
                    elif _base == 'studio':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            for studio in meta.get('studios', []):
                                d.setdefault(studio, []).append(fn)
                        if _sort == 'alpha':
                            groups_raw = sorted(d.items(), key=lambda x: x[0].lower())
                        else:
                            groups_raw = sorted(d.items(), key=lambda x: (-len(x[1]), x[0].lower()))
                    elif _base == 'tag':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            for tag in _main.get_tags(meta):
                                d.setdefault(tag, []).append(fn)
                        if _sort == 'alpha':
                            groups_raw = sorted(d.items(), key=lambda x: x[0].lower())
                        else:
                            groups_raw = sorted(d.items(), key=lambda x: (-len(x[1]), x[0].lower()))
                    elif _base == 'anilist_tag':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            al_id = meta.get('anilist')
                            if not al_id:
                                continue
                            al_data = _main.anilist_metadata.get(str(al_id), {})
                            for tag in al_data.get('tags', []):
                                name = tag.get('name')
                                if name:
                                    d.setdefault(name, []).append(fn)
                        if _sort == 'alpha':
                            groups_raw = sorted(d.items(), key=lambda x: x[0].lower())
                        else:
                            groups_raw = sorted(d.items(), key=lambda x: (-len(x[1]), x[0].lower()))
                    elif _base == 'type':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            t = _main.get_format(meta) or 'Unknown'
                            d.setdefault(t, []).append(fn)
                        groups_raw = sorted(d.items(), key=lambda x: (-len(x[1]), x[0].lower()))
                    elif _base == 'slug':
                        d = {}
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            slug = meta.get('slug', 'Unknown')
                            d.setdefault(slug, []).append(fn)
                        if _sort == 'alpha':
                            groups_raw = sorted(d.items(), key=lambda x: x[0].lower())
                        else:
                            groups_raw = sorted(d.items(), key=lambda x: (-len(x[1]), x[0].lower()))
                except Exception as e:
                    print(f"[directory_groups error] {e}")
                total = sum(len(files) for _, files in groups_raw)
                groups_out = [{'label': label, 'count': len(files)} for label, files in groups_raw]
                web_server.push_directory_groups(groups_out, st, total, to_sid=_sid)
            threading.Thread(target=_run_dir_groups, daemon=True).start()

        elif action == 'get_directory_themes':
            stat_type = str(data.get('stat_type', '')).strip()
            group_label = str(data.get('group_label', '')).strip()
            sid = data.get('_sid')
            def _run_dir_themes(st=stat_type, gl=group_label, _sid=sid):
                # Rebuild the group's file list (same logic as above but for one group)
                try:
                    files = []
                    # Strip sort suffix — 'series_alpha' → 'series', 'artist_alpha' → 'artist', etc.
                    _base = st.removesuffix('_alpha').removesuffix('_popularity')
                    if _base == 'artist':
                        for fn in _main.get_cached_deduplicated_files():
                            fd = _main.get_file_metadata_by_name(fn)
                            if not fd: continue
                            slug = fd.get('slug')
                            meta = _main.get_metadata(fn)
                            for song in meta.get('songs', []):
                                if song.get('slug') == slug:
                                    if gl in song.get('artist', []):
                                        files.append(fn)
                                    break
                    elif _base == 'series':
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            series = meta.get('series') or meta.get('title', 'Unknown')
                            if isinstance(series, list):
                                if gl in series: files.append(fn)
                            else:
                                if series == gl: files.append(fn)
                    elif _base == 'season':
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            s = meta.get('season') or 'Unknown'
                            if s == 'N/A': s = 'Unknown'
                            if s == gl: files.append(fn)
                    elif _base == 'year':
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            season = meta.get('season', '')
                            yr = season[-4:] if season and season[-4:].isdigit() else 'Unknown'
                            if yr.isdigit():
                                y = int(yr)
                                if y >= 2000: g = str(y)
                                elif y >= 1990: g = '1990s'
                                elif y >= 1980: g = '1980s'
                                elif y >= 1970: g = '1970s'
                                elif y >= 1960: g = '1960s'
                                else: g = 'Pre-60s'
                            else:
                                g = 'Unknown'
                            if g == gl: files.append(fn)
                    elif _base == 'studio':
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            if gl in meta.get('studios', []): files.append(fn)
                    elif _base == 'tag':
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            if gl in _main.get_tags(meta): files.append(fn)
                    elif _base == 'type':
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            if (_main.get_format(meta) or 'Unknown') == gl: files.append(fn)
                    elif _base == 'slug':
                        for fn in _main.get_cached_deduplicated_files():
                            meta = _main.get_metadata(fn)
                            if meta.get('slug', 'Unknown') == gl: files.append(fn)
                    files.sort(key=lambda f: _main.get_title(f, f).lower())
                    _play_count_map, _play_last_map, _series_play_map, _cur_idx = _main._build_play_maps()
                    results = [_main._build_theme_web_result(fn, _play_count_map, _play_last_map, _series_play_map, _cur_idx) for fn in files]
                except Exception as e:
                    print(f"[directory_themes error] {e}")
                    results = []
                web_server.push_directory_themes(results, st, gl, to_sid=_sid)
            threading.Thread(target=_run_dir_themes, daemon=True).start()

        elif action == 'get_buzz_presets':
            presets_list = [{'index': i, 'name': p[0]} for i, p in enumerate(buzz.BUZZ_PRESETS)]
            web_server.push_buzz_presets(presets_list, buzz._buzz_preset_index, to_sid=data.get('_sid'))

        elif action == 'set_buzz_preset':
            idx = int(data.get('index', 0))
            if 0 <= idx < len(buzz.BUZZ_PRESETS):
                buzz._buzz_preset_index = idx
            presets_list = [{'index': i, 'name': p[0]} for i, p in enumerate(buzz.BUZZ_PRESETS)]
            web_server.push_buzz_presets(presets_list, buzz._buzz_preset_index)
            if not data.get('silent'):
                buzz._play_buzz_sound(1, 'Test')

        elif action == 'queue_theme':
            fn = str(data.get('filename', '')).strip()
            if fn:
                if _main.playlist.get('infinite', False):
                    _main.add_theme_next(fn, prevent_duplicates=True)
                    _main.save_config()
                    _main.up_next_text()
                else:
                    _main._queue_theme_standard(fn)
                _main._push_web_toggles()

        elif action == 'queue_theme_only':
            fn = str(data.get('filename', '')).strip()
            if fn:
                _main._queue_theme_standard(fn)
                _main._push_web_toggles()

        elif action == 'play_theme_now':
            fn = str(data.get('filename', '')).strip()
            if fn:
                _main.play_video_from_filename(fn)
                _main.up_next_text()
                _main._push_web_toggles()

        elif action == 'add_theme':
            fn = str(data.get('filename', '')).strip()
            if fn:
                _main.add_theme_next(fn, prevent_duplicates=True)
                _main.save_config()
                _main.up_next_text()
                _main.prefetch_next_themes()
        elif action == 'get_playlist_info':
            source = _get_web_playlist_source()
            web_server.push_playlist_info(len(source['items']), source['current_index'], to_sid=data.get('_sid'), counter=source['counter'], label=source['label'])
        elif action == 'playlist_goto':
            idx = int(data.get('index', -1))
            source = _get_web_playlist_source()
            if 0 <= idx < len(source['items']):
                if source['is_fixed']:
                    state.widgets.root.after(0, _main.play_fixed_round_by_index, idx)
                else:
                    state.widgets.root.after(0, _main.play_video, idx)
        elif action == 'playlist_delete':
            idx = int(data.get('index', -1))
            source = _get_web_playlist_source()
            if not source['is_fixed'] and 0 <= idx < len(source['items']):
                def _do_delete(i=idx):
                    pl = _main.playlist.get("playlist", [])
                    if not (0 <= i < len(pl)):
                        return
                    del pl[i]
                    # Adjust current_index pointer so current track doesn't shift
                    cur = _main.playlist.get("current_index", 0)
                    if i < cur:
                        _main.playlist["current_index"] = max(0, cur - 1)
                    # Clamp scroll offset so it can't be past the end (causes black screen)
                    entries_count = _main.get_list_entries_count()
                    max_offset = max(0, len(pl) - entries_count)
                    _main.current_list_offset = min(_main.current_list_offset, max_offset)
                    _main.update_playlist_name()
                    _main.update_current_index()
                    # update_playlist_display rebuilds current_list_content and current_list_selected
                    # correctly, then calls refresh_current_list()
                    if _main.list_loaded == "playlist":
                        _main.update_playlist_display()
                    # Build correct args for push_playlist_info(total, current_index, counter, label)
                    new_source = _get_web_playlist_source()
                    web_server.push_playlist_info(len(new_source['items']), new_source['current_index'], counter=new_source['counter'], label=new_source['label'])
                state.widgets.root.after(0, _do_delete)
        elif action == 'get_playlist_chunk':
            offset = int(data.get('offset', 0))
            count  = min(int(data.get('count', 100)), 200)
            source = _get_web_playlist_source()
            items  = source['items']
            cur    = source['current_index']
            chunk  = items[offset: offset + count]
            results = []
            for rel_i, item in enumerate(chunk):
                abs_i = offset + rel_i
                if source['is_fixed']:
                    title = _main.get_fixed_round_title(f'round_{abs_i}', item)
                    slug = ''
                    song_title = ''
                    song_artist = ''
                else:
                    fn = item
                    is_lightning = fn.startswith('[L]')
                    clean_fn = fn[3:] if is_lightning else fn
                    file_data = _main.get_file_metadata_by_name(clean_fn)
                    if file_data:
                        mal_key = file_data.get('mal')
                        anime_d = _main.anime_metadata.get(mal_key, {}) if mal_key else {}
                        title = _main.get_display_title({**file_data, **anime_d}) if anime_d else (file_data.get('name') or clean_fn)
                        slug  = ('[L] ' if is_lightning else '') + file_data.get('slug', '')
                        song_title  = ''
                        song_artist = ''
                        for s in (file_data.get('songs') or []):
                            if s.get('slug') == file_data.get('slug', ''):
                                song_title = s.get('title') or ''
                                if abs_i == cur:
                                    song_artist = _main.get_artists_string(s.get('artist') or [], total=True)
                                break
                    else:
                        title       = clean_fn
                        slug        = '[L]' if is_lightning else ''
                        song_title  = ''
                        song_artist = ''
                results.append({
                    'i':       abs_i,
                    'title':   title,
                    'slug':    slug,
                    'song':    song_title,
                    'artist':  song_artist,
                    'current': abs_i == cur,
                })
            web_server.push_playlist_chunk(offset, results, to_sid=data.get('_sid'))
        elif action == 'set_difficulty':
            val = data.get('value')
            if val is not None:
                _main._set_difficulty_from_menu(max(0, min(5, int(val))))
                _main._push_web_toggles()
        elif action == 'set_auto_bonus':
            val = str(data.get('value', '')).strip() or None
            _main.set_auto_bonus_start(val)
            _main._push_web_toggles()
        elif action == 'buzzer_control':
            cmd = str(data.get('cmd', '')).strip().lower()
            print(f"[BUZZER][HOST_ACTION] cmd='{cmd}' running={web_server.is_running()} guessing_extra='{bonus.guessing_extra}'")
            web_server.control_buzzer(cmd)
        elif action == 'score_adjust':
            name = str(data.get('name', '')).strip()
            try:
                delta = float(data.get('delta', 0))
            except (ValueError, TypeError):
                delta = 0.0
            if name and delta != 0:
                _main.send_scoreboard_score(name, delta)
        elif action == 'score_set':
            name = str(data.get('name', '')).strip()
            try:
                score = float(data.get('score', 0))
            except (ValueError, TypeError):
                score = 0.0
            if name:
                _main.send_scoreboard_command(f"[SCORE_SET][PLAYER]{name}[SCORE]{score}")
        elif action == 'player_add':
            name = str(data.get('name', '')).strip()
            if name:
                _main.send_scoreboard_command(f"[PLAYER_ADD][NAME]{name}")
        elif action == 'player_remove':
            name = str(data.get('name', '')).strip()
            if name:
                _main.send_scoreboard_command(f"[PLAYER_REMOVE][NAME]{name}")
        elif action == 'player_rename':
            old_name = str(data.get('old_name', '')).strip()
            new_name = str(data.get('new_name', '')).strip()
            if old_name and new_name:
                _main.send_scoreboard_command(f"[PLAYER_RENAME][OLD]{old_name}[NEW]{new_name}")
        elif action == 'sc_set_prefs':
            cfg_path = os.path.join('scoreboard_data', 'scoreboard_config.json')
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, 'r', encoding='utf-8') as cf:
                        sb_cfg = json.load(cf)
                    sb_cfg.setdefault('style', {})
                    sb_cfg['style'].setdefault('delta_auto_send',     {'selected': True})
                    sb_cfg['style'].setdefault('delta_delay_together', {'selected': False})
                    sb_cfg['style']['delta_auto_send']['selected']     = bool(data.get('auto_send', True))
                    sb_cfg['style']['delta_delay_together']['selected'] = bool(data.get('delay_together', False))
                    with open(cfg_path, 'w', encoding='utf-8') as cf:
                        json.dump(sb_cfg, cf, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"Error saving sc_set_prefs: {e}")
        elif action == 'scores_clear_all':
            _main.send_scoreboard_command("[CLEAR_ALL]")
            try:
                _sc_path = os.path.join('scoreboard_data', 'score_changes.json')
                open(_sc_path, 'w', encoding='utf-8').close()
            except Exception as e:
                print(f"Error clearing score history on clear_all: {e}")
            web_server.push_score_history([], to_sid=data.get('_sid'))
        elif action == 'scores_archive':
            _main.send_scoreboard_command("[ARCHIVE]")
        elif action == 'get_scores':
            bonus_answers._push_web_scores()
        elif action == 'get_score_history':
            entries = _main.read_all_score_changes()
            web_server.push_score_history(entries, to_sid=data.get('_sid'))
        elif action == 'clear_score_history':
            try:
                _sc_path = os.path.join('scoreboard_data', 'score_changes.json')
                open(_sc_path, 'w', encoding='utf-8').close()
            except Exception as e:
                print(f"Error clearing score history: {e}")
            web_server.push_score_history([], to_sid=data.get('_sid'))
        elif action == 'player_set_team':
            name      = str(data.get('name', '')).strip()
            team_name = str(data.get('team', '')).strip()
            if name:
                _main.send_scoreboard_command(f"[PLAYER_SET_TEAM][NAME]{name}[TEAM]{team_name}")
        elif action == 'get_teams':
            _main.send_scoreboard_command("[GET_TEAM_NAMES]")
    state.widgets.root.after(0, _dispatch)
