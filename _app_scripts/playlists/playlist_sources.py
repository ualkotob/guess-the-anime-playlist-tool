"""External-source playlist generators: build playlists from AniList users,
AnimeThemes playlists, and saved session logs, plus the startup auto-update
("living playlist") pass that refreshes saved source-backed playlists.

Extracted from playlist.py. These resolve external data to local files and
hand off to playlist.new_playlist(); the playlist-structure functions they
rely on (new_playlist, get_directory_files) stay in playlist.py.
"""
import copy
import json
import os
import re
import threading

import requests
from tkinter import filedialog, messagebox, simpledialog

from core.game_state import state
from core.app_meta import APP_VERSION
from core.paths import PLAYLISTS_FOLDER
from _app_scripts import utils
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.playlists.playlist as playlist
import _app_scripts.playback.cache_download as cache_download


def get_anilist_matching_files(user_id, only_watched, include_non_local):
    """Fetch and return matching files for an AniList user."""
    user_anime_ids = metadata_fetch.fetch_anilist_user_ids(user_id, only_watched)
    if not user_anime_ids:
        return None

    matching_files = []
    for file in playlist.get_directory_files(include_non_local=include_non_local):
        data = metadata_fetch.get_metadata(file)
        if data and str(data.get("anilist")) in user_anime_ids:
            matching_files.append(file)

    return matching_files


def get_animethemes_matching_files(hashid, include_non_local):
    """Fetch and return matching files, playlist name, and total count for an AnimeThemes playlist."""
    headers = {
        'User-Agent': f'GuessTheAnime/{APP_VERSION} '
                      f'(https://github.com/ualkotob/guess-the-anime-playlist-tool)'
    }
    response = requests.get(
        f'https://api.animethemes.moe/playlist/{hashid}'
        f'?include=tracks.video&fields[playlist]=name&fields[video]=path',
        headers=headers,
    )
    if response.status_code != 200:
        return None, None, None

    data = response.json()
    playlist_name = data.get('playlist', {}).get('name', hashid)
    tracks = data.get('playlist', {}).get('tracks', [])

    if not tracks:
        return [], playlist_name, 0

    available_files = set(playlist.get_directory_files(include_non_local=include_non_local)) if not include_non_local else set()

    matching_files = []
    total_count = 0
    for track in tracks:
        video = track.get('video', {})
        if video and video.get('path'):
            total_count += 1
            filename = os.path.basename(video['path'])
            if include_non_local or filename in available_files:
                matching_files.append(filename)

    if total_count == 0:
        return [], playlist_name, 0

    return matching_files, playlist_name, total_count


def create_living_playlist_with_confirmation(matching_files, playlist_name, source_data, total_available=None):
    """Create a playlist with confirmation dialog and store source metadata."""
    if not matching_files:
        return False

    if total_available is not None:
        message = f"{len(matching_files)} of {total_available} themes found. Create playlist?"
    else:
        message = f"{len(matching_files)} matches found. Create playlist?"

    confirm = messagebox.askyesno("Create Playlist", message)
    if not confirm:
        return False

    auto_update = messagebox.askyesno(
        "Auto-Update Playlist",
        "Should this playlist automatically update with new matching themes on startup?",
    )

    playlist.new_playlist(matching_files, playlist_name)
    source_data["auto_update"] = auto_update
    state.metadata.playlist["source"] = source_data
    return True


def generate_anilist_playlist(include_non_local=None):
    user_id = simpledialog.askstring("AniList User ID", "Enter the AniList user ID:")
    if not user_id:
        return

    only_watched = messagebox.askyesno("AniList Only Watched",
                                       "Do you want to limit results to only watched entries?")
    if include_non_local is None:
        include_non_local = messagebox.askyesno(
            "Create Playlist: Include non-local files",
            "Would you like to include non-local files from metadata(they will stream)?",
        )

    matching_files = get_anilist_matching_files(user_id, only_watched, include_non_local)

    if matching_files is None:
        messagebox.showerror("Error", "Could not fetch AniList data or no entries found.")
        return

    if not matching_files:
        messagebox.showwarning("Playlist Error",
                               "No matching video files found for this AniList user.")
        return

    source_data = {
        "type": "anilist",
        "user_id": user_id,
        "only_watched": only_watched,
        "include_non_local": include_non_local,
    }
    create_living_playlist_with_confirmation(matching_files, f"{user_id}'s AniList", source_data)


def generate_animethemes_playlist(include_non_local=None):
    hashid = simpledialog.askstring("AnimeThemes Playlist",
                                    "Enter the AnimeThemes playlist hashid:")
    if not hashid:
        return

    if include_non_local is None:
        include_non_local = messagebox.askyesno(
            "Create Playlist: Include non-local files",
            "Would you like to include non-local files from metadata(they will stream)?",
        )

    try:
        matching_files, playlist_name, total_count = get_animethemes_matching_files(hashid, include_non_local)

        if matching_files is None:
            messagebox.showerror("Error", "Could not fetch playlist.")
            return

        if not matching_files:
            messagebox.showwarning("Playlist Error",
                                   "No matching video files found for this AnimeThemes playlist.")
            return

        source_data = {
            "type": "animethemes",
            "hashid": hashid,
            "include_non_local": include_non_local,
        }
        create_living_playlist_with_confirmation(matching_files, playlist_name, source_data, total_count)

    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch AnimeThemes playlist: {str(e)}")


def generate_session_log_playlist(include_non_local=None):
    """Create a playlist by matching themes from a saved session log (.txt) file."""
    filepath = filedialog.askopenfilename(
        title="Open Session Log",
        initialdir="sessions" if os.path.isdir("sessions") else ".",
        filetypes=[("Session log files", "*.txt"), ("All files", "*.*")],
    )
    if not filepath:
        return

    if include_non_local is None:
        include_non_local = messagebox.askyesno(
            "Create Playlist: Include non-local files",
            "Would you like to include non-local files from metadata(they will stream)?",
        )

    anime_metadata = state.metadata.anime_metadata
    file_metadata = state.metadata.file_metadata
    directory_files = state.metadata.directory_files

    title_to_mals = {}
    for mal_id, data in anime_metadata.items():
        for t in filter(None, [data.get("eng_title"), data.get("title"),
                                *(data.get("synonyms") or [])]):
            ts = str(t).strip()
            if ts:
                title_to_mals.setdefault(ts.lower(), []).append(mal_id)

    mal_slug_to_files = {}
    for mal_id, mal_data in file_metadata.items():
        for slug, slug_data in mal_data.get("themes", {}).items():
            for version_data in slug_data.values():
                for fname in version_data.keys():
                    is_local = fname in directory_files
                    if is_local:
                        # Local files take priority: keep them at the front so
                        # candidates[0] resolves to a local file when one exists.
                        mal_slug_to_files.setdefault((mal_id, slug), []).insert(0, fname)
                    elif include_non_local and cache_download.is_animethemes_stream_file(fname):
                        mal_slug_to_files.setdefault((mal_id, slug), []).append(fname)

    def _unformat_slug(fmt):
        if fmt.startswith("Opening "):
            return "OP" + fmt[8:]
        if fmt.startswith("Ending "):
            return "ED" + fmt[7:]
        return fmt

    timestamp_re = re.compile(r'^\d{2}:\d{2}:\d{2}: ?')
    skip_markers = ('[YOUTUBE VIDEO', '[FIXED LIGHTNING ROUNDS', '[SCOREBOARD]', '[BONUS?')
    lightning_re = re.compile(r'^\[LIGHTNING ROUND #\d+\([^)]+\)\] - ')
    slug_op_ed_re = re.compile(r'^(.*) - ((?:Opening|Ending)\s*\d+)(?=\s*(?:\(|$))')
    ext_re = re.compile(r'\s(\S+\.(?:webm|mkv|mp4|avi|mov))\s*$', re.IGNORECASE)

    matched = []
    unmatched_lines = []
    total_lines = 0
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.rstrip('\n\r')
                if not timestamp_re.match(line):
                    continue
                original_body = timestamp_re.sub('', line)
                body = original_body
                if any(body.startswith(m) for m in skip_markers):
                    continue
                is_lightning = bool(lightning_re.match(body))
                body = lightning_re.sub('', body)
                total_lines += 1

                filename_hint = None
                fn_m = ext_re.search(body)
                if fn_m:
                    filename_hint = fn_m.group(1)
                    body = body[:fn_m.start()]

                title = None
                slug = None
                op_ed_m = slug_op_ed_re.match(body.strip())
                if op_ed_m:
                    title = op_ed_m.group(1).strip()
                    slug = _unformat_slug(op_ed_m.group(2).strip())
                else:
                    body_stripped = re.sub(r'\s*\([^(]*\)\s*$', '', body).strip()
                    sep = body_stripped.rfind(' - ')
                    if sep != -1:
                        title = body_stripped[:sep].strip()
                        slug = body_stripped[sep + 3:].strip()

                found = None
                if filename_hint and (
                    filename_hint in directory_files
                    or (include_non_local
                        and cache_download.is_animethemes_stream_file(filename_hint))
                ):
                    found = filename_hint
                elif title is not None and slug:
                    for mal_id in title_to_mals.get(title.lower(), []):
                        candidates = mal_slug_to_files.get((mal_id, slug), [])
                        if candidates:
                            found = candidates[0]
                            break

                if found:
                    matched.append(f"[L]{found}" if is_lightning else found)
                else:
                    unmatched_lines.append(original_body.rstrip())

    except Exception as e:
        messagebox.showerror("Error", f"Failed to read session log:\n{e}")
        return

    unmatched = len(unmatched_lines)
    if unmatched_lines:
        print(f"[Session Log Playlist] {unmatched} unmatched lines:")
        for ul in unmatched_lines:
            print(f"  UNMATCHED: {ul}")

    match_target = "files" if include_non_local else "local files"
    if not matched:
        messagebox.showwarning(
            "No Matches",
            f"No matching {match_target} found.\n"
            f"({total_lines} theme lines parsed, {unmatched} unmatched)",
        )
        return

    msg = f"{len(matched)} of {total_lines} theme lines matched to {match_target}."
    if unmatched:
        msg += f"\n{unmatched} could not be matched."
    msg += "\n\nCreate playlist?"
    if not messagebox.askyesno("Create Playlist from Session Log", msg):
        return

    basename = os.path.splitext(os.path.basename(filepath))[0]
    if basename.startswith("guess_the_anime_"):
        playlist_name = basename[len("guess_the_anime_"):]
    else:
        playlist_name = basename

    playlist.new_playlist(matched, playlist_name)


def update_living_playlists():
    """Update all saved playlists with source metadata (living playlists) in background."""
    def update_in_background():
        try:
            if not os.path.exists(PLAYLISTS_FOLDER):
                return

            updated_playlists = []

            for filename in os.listdir(PLAYLISTS_FOLDER):
                if not filename.endswith('.json'):
                    continue

                filepath = os.path.join(PLAYLISTS_FOLDER, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        saved_playlist = json.load(f)

                    saved_playlist = utils.convert_infinity_markers(saved_playlist)

                    source = saved_playlist.get('source')
                    if not source:
                        continue

                    if not source.get('auto_update', True):
                        continue

                    source_type = source.get('type')
                    existing_files = set(saved_playlist.get('playlist', []))
                    all_matching = None

                    if source_type == 'anilist':
                        user_id = source.get('user_id')
                        only_watched = source.get('only_watched', False)
                        include_non_local = source.get('include_non_local', False)
                        all_matching = get_anilist_matching_files(user_id, only_watched, include_non_local)

                    elif source_type == 'animethemes':
                        hashid = source.get('hashid')
                        include_non_local = source.get('include_non_local', False)
                        result = get_animethemes_matching_files(hashid, include_non_local)
                        if result:
                            all_matching, _, _ = result

                    if all_matching is not None:
                        all_matching_set = set(all_matching)
                        new_files = [f for f in all_matching if f not in existing_files]
                        removed_files = [f for f in existing_files if f not in all_matching_set]

                        if new_files or removed_files:
                            saved_playlist['playlist'] = all_matching
                            playlist_to_save = copy.deepcopy(saved_playlist)
                            if playlist_to_save.get("infinite_settings"):
                                playlist_to_save["infinite_settings"] = utils.convert_infinities_to_markers(
                                    playlist_to_save["infinite_settings"]
                                )
                            with open(filepath, 'w', encoding='utf-8') as f:
                                json.dump(playlist_to_save, f, indent=4)

                            playlist_name = saved_playlist.get('name', filename[:-5])
                            change_summary = []
                            if new_files:
                                change_summary.append(f"+{len(new_files)}")
                            if removed_files:
                                change_summary.append(f"-{len(removed_files)}")
                            updated_playlists.append((playlist_name, len(new_files), len(removed_files)))
                            print(f"Updated playlist '{playlist_name}': {' '.join(change_summary)} themes")
                            for theme in removed_files:
                                print(f"  - {theme}")
                            for theme in new_files:
                                print(f"  + {theme}")

                except Exception as e:
                    print(f"Error updating playlist {filename}: {e}")
        except Exception as e:
            print(f"Error in update_living_playlists: {e}")

    thread = threading.Thread(target=update_in_background, daemon=True)
    thread.start()
