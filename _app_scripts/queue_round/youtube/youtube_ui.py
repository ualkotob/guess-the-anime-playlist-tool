"""YouTube queue/list UI helpers for the main player."""

import os
from datetime import datetime

import _app_scripts.queue_round.youtube.youtube_control as youtube_control


_ctx = {}
_youtube_playlist = {}
_archived_youtube_playlist = {}


def set_context(
    *,
    get_youtube_queue,
    set_youtube_queue,
    youtube_metadata,
    get_playlist,
    show_list,
    get_right_column,
    stream_icon,
    load_pil_image_from_url,
    format_seconds,
    player,
    player_play,
    root,
    set_video_stopped,
    toggle_coming_up_popup,
    play_video,
    up_next_text,
    get_popout_buttons_by_name,
    button_selected,
    bonus,
    get_currently_playing,
    censors,
    get_left_column,
    get_middle_column,
    get_popout_currently_playing,
    update_popout_currently_playing,
    web_server,
):
    _ctx.clear()
    _ctx.update(locals())


def unload_youtube_video():
    youtube_queue = _ctx["get_youtube_queue"]()
    if youtube_queue:
        _ctx["toggle_coming_up_popup"](False, get_youtube_display_title(youtube_queue))
    try:
        popout_buttons = _ctx["get_popout_buttons_by_name"]()
        if "YOUTUBE QUEUE" in popout_buttons:
            _ctx["button_selected"](popout_buttons["YOUTUBE QUEUE"], False)
        if "YOUTUBE DROPDOWN" in popout_buttons:
            popout_buttons["YOUTUBE DROPDOWN"].set("YOUTUBE VIDEOS")
    except Exception:
        pass
    _ctx["set_youtube_queue"](None)


def stream_youtube(youtube_url):
    """Stream a YouTube video using mpv."""
    player = _ctx["player"]
    player.set_media(youtube_url)
    _ctx["player_play"]()
    check_youtube_video_playing()


def check_youtube_video_playing():
    player = _ctx["player"]
    if player.is_playing():
        _ctx["set_video_stopped"](False)
    else:
        _ctx["root"].after(1000, check_youtube_video_playing)


def _is_downloaded_youtube_file(filename):
    if os.path.exists(os.path.join("youtube", filename)):
        return True
    for playlist_entry in _ctx["get_playlist"]().get("playlist", []):
        if (
            os.path.isabs(playlist_entry)
            and os.path.basename(playlist_entry) == filename
            and os.path.exists(playlist_entry)
        ):
            return True
    return False


def _sort_active_video_key(item):
    _, video = item
    date_added = video.get("date_added")
    if date_added:
        try:
            return datetime.fromisoformat(date_added)
        except (ValueError, TypeError):
            pass

    upload_date = video.get("upload_date", "")
    if upload_date:
        try:
            return datetime.strptime(upload_date, "%Y%m%d")
        except (ValueError, TypeError):
            pass
    return datetime(1900, 1, 1)


def show_youtube_playlist(update=False):
    global _youtube_playlist
    all_videos = {}

    for video_id, video in _ctx["youtube_metadata"].get("videos", {}).items():
        if video.get("archived", False):
            continue

        filename = video["filename"]
        video_copy = video.copy()
        video_copy["video_id"] = video_id
        video_copy["downloaded"] = _is_downloaded_youtube_file(filename)
        all_videos[video_id] = video_copy

    all_videos = dict(sorted(all_videos.items(), key=_sort_active_video_key, reverse=True))

    selected = -1
    youtube_queue = _ctx["get_youtube_queue"]()
    if youtube_queue:
        queue_video_id = youtube_queue.get("url")
        for index, (key, value) in enumerate(all_videos.items()):
            if key == queue_video_id:
                selected = index
                youtube_queue["index"] = selected
                break

    _youtube_playlist.clear()
    _youtube_playlist.update(all_videos)
    _ctx["show_list"](
        "youtube",
        _ctx["get_right_column"](),
        all_videos,
        get_youtube_title,
        load_youtube_video,
        selected,
        update,
        title="YOUTUBE VIDEOS",
    )


def get_youtube_title(key, value):
    icon = _ctx["stream_icon"] if not value.get("downloaded", False) else ""
    display_title = shorten_youtube_title(get_youtube_display_title(value))
    return f"{icon}[{str(_ctx['format_seconds'](get_youtube_duration(value)))}]{display_title}"


def _set_youtube_queue(video):
    """Activate or clear a YouTube queue item from any context."""
    youtube_queue = _ctx["get_youtube_queue"]()
    if video and youtube_queue != video:
        unload_youtube_video()
        _ctx["set_youtube_queue"](video)
        youtube_queue = video
        title = get_youtube_display_title(youtube_queue)
        try:
            image = _ctx["load_pil_image_from_url"](youtube_queue.get("thumbnail"), size=(400, 225))
        except Exception:
            image = None
        try:
            upload_str = datetime.strptime(youtube_queue.get("upload_date", ""), "%Y%m%d").strftime("%Y-%m-%d")
            upload_line = f"Uploaded: {upload_str} | "
        except Exception:
            upload_line = ""
        details = (
            f"Created by: {youtube_queue.get('name')} ({youtube_queue.get('subscriber_count', 0):,} subscribers)\n"
            f"{upload_line}Duration: {_ctx['format_seconds'](get_youtube_duration(youtube_queue))} mins\n\n"
            "1 PT for the first correct answer."
        )
        if _ctx["player"].is_playing():
            _ctx["toggle_coming_up_popup"](True, title, details, image, queue=True)
        else:
            _ctx["play_video"]()
    else:
        unload_youtube_video()


def load_youtube_video(index):
    video = get_youtube_metadata_from_index(key_id=list(_youtube_playlist.keys())[index])
    _set_youtube_queue(video)
    show_youtube_playlist(True)
    _ctx["up_next_text"]()


def _sort_archived_video_key(item):
    _, video = item
    archived_date = video.get("archived_date")
    if archived_date:
        try:
            return datetime.fromisoformat(archived_date)
        except (ValueError, TypeError):
            pass
    return datetime(1900, 1, 1)


def show_archived_youtube_playlist(update=False):
    global _archived_youtube_playlist
    all_videos = {}

    for video_id, video in _ctx["youtube_metadata"].get("videos", {}).items():
        if not video.get("archived", False):
            continue
        filename = video["filename"]
        video_copy = video.copy()
        video_copy["video_id"] = video_id
        video_copy["downloaded"] = os.path.exists(os.path.join("youtube", "archive", filename))
        all_videos[video_id] = video_copy

    all_videos = dict(sorted(all_videos.items(), key=_sort_archived_video_key, reverse=True))

    selected = -1
    youtube_queue = _ctx["get_youtube_queue"]()
    if youtube_queue:
        queue_video_id = youtube_queue.get("url")
        for index, (key, value) in enumerate(all_videos.items()):
            if key == queue_video_id:
                selected = index
                youtube_queue["index"] = selected
                break

    _archived_youtube_playlist.clear()
    _archived_youtube_playlist.update(all_videos)
    _ctx["show_list"](
        "youtube",
        _ctx["get_right_column"](),
        all_videos,
        get_youtube_title,
        load_archived_youtube_video,
        selected,
        update,
        title="ARCHIVED YOUTUBE VIDEOS",
    )


def load_archived_youtube_video(index):
    video = get_youtube_metadata_from_index(key_id=list(_archived_youtube_playlist.keys())[index])
    _set_youtube_queue(video)
    show_archived_youtube_playlist(True)
    _ctx["up_next_text"]()


def update_youtube_metadata(data=None):
    youtube_data = data or _ctx["get_youtube_queue"]()
    if not youtube_data:
        return
    video_id = youtube_data.get("url")
    _ctx["bonus"].setup_for_youtube(load_bonus_template(video_id) if video_id else [])
    currently_playing = _ctx["get_currently_playing"]()
    yt_filename = currently_playing.get("filename")
    if video_id and yt_filename:
        _ctx["censors"].set_youtube_censors_for_file(yt_filename, youtube_control.load_youtube_censors(video_id))
    _ctx["censors"].reset_for_new_file(yt_filename)

    left_column = _ctx["get_left_column"]()
    middle_column = _ctx["get_middle_column"]()
    insert_column_line(left_column, "TITLE: ", get_youtube_display_title(youtube_data))
    insert_column_line(left_column, "FULL TITLE: ", youtube_data.get("title"))
    insert_column_line(left_column, "UPLOAD DATE: ", f"{datetime.strptime(youtube_data.get('upload_date'), '%Y%m%d').strftime('%Y-%m-%d')}")
    insert_column_line(left_column, "VIEWS: ", f"{youtube_data.get('view_count') or 0:,}")
    insert_column_line(left_column, "LIKES: ", f"{youtube_data.get('like_count') or 0:,}")
    insert_column_line(left_column, "CHANNEL: ", youtube_data.get("name"))
    insert_column_line(left_column, "SUBSCRIBERS: ", f"{youtube_data.get('subscriber_count') or 0:,}")
    insert_column_line(left_column, "DURATION: ", str(_ctx["format_seconds"](get_youtube_duration(youtube_data))) + " mins")
    insert_column_line(middle_column, "DESCRIPTION: ", youtube_data.get("description"))
    show_youtube_playlist()
    if _ctx["get_popout_currently_playing"]():
        _ctx["update_popout_currently_playing"](_ctx["get_youtube_queue"]())

    web_server = _ctx["web_server"]
    if web_server.is_running():
        try:
            yt_upload = youtube_data.get("upload_date")
            yt_upload_fmt = datetime.strptime(yt_upload, "%Y%m%d").strftime("%Y-%m-%d") if yt_upload else None
            yt_duration = get_youtube_duration(youtube_data)
            web_server.push_metadata({
                "type": "youtube",
                "filename": currently_playing.get("filename", ""),
                "title": get_youtube_display_title(youtube_data),
                "full_title": youtube_data.get("title"),
                "custom_title": youtube_data.get("custom_title"),
                "upload_date": yt_upload_fmt,
                "view_count": youtube_data.get("view_count"),
                "like_count": youtube_data.get("like_count"),
                "channel": youtube_data.get("name"),
                "channel_id": youtube_data.get("channel_id"),
                "subscriber_count": youtube_data.get("subscriber_count"),
                "duration": str(_ctx["format_seconds"](yt_duration)) + " mins" if yt_duration else None,
                "duration_seconds": yt_duration,
                "full_duration_seconds": youtube_data.get("duration"),
                "start": youtube_data.get("start"),
                "end": youtube_data.get("end"),
                "synopsis": youtube_data.get("description"),
                "url": youtube_data.get("url"),
                "thumbnail": youtube_data.get("thumbnail"),
                "tags": youtube_data.get("tags") or [],
                "category": youtube_data.get("category"),
                "language": youtube_data.get("language"),
            })
        except Exception:
            pass


def insert_column_line(column, title, data):
    column.insert("end", title, "bold")
    column.insert("end", f"{data}", "white")
    column.insert("end", "\n\n", "blank")


get_youtube_duration = youtube_control.get_youtube_duration
get_youtube_metadata_from_index = youtube_control.get_youtube_metadata_from_index
get_youtube_display_title = youtube_control.get_youtube_display_title
shorten_youtube_title = youtube_control.shorten_youtube_title
load_bonus_template = youtube_control.load_bonus_template
load_youtube_censors = youtube_control.load_youtube_censors
save_youtube_censors = youtube_control.save_youtube_censors
