from _app_scripts.playback.media_player import MediaPlayer
from _app_scripts.playback import streaming
from _app_scripts.queue_round.youtube import youtube_control


class _FakeMpv:
    def __init__(self):
        self.commands = []

    def command(self, *args):
        self.commands.append(args)

    def observe_property(self, *_args):
        pass


def test_ydl_options_detect_node_on_path(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube_control, "_ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(
        youtube_control.shutil,
        "which",
        lambda name: "C:/runtime/node.exe" if name in {"node", "node.exe"} else None,
    )

    options = youtube_control.get_youtube_ydl_options(quiet=True)

    assert options["js_runtimes"] == {"node": {"path": "C:/runtime/node.exe"}}
    assert options["no_cache_dir"] is True
    assert options["quiet"] is True


def test_ydl_options_detect_portable_deno(monkeypatch, tmp_path):
    deno_path = tmp_path / "deno.exe"
    deno_path.touch()
    monkeypatch.setattr(youtube_control, "_ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(youtube_control.shutil, "which", lambda _name: None)

    options = youtube_control.get_youtube_ydl_options()

    assert options["js_runtimes"] == {"deno": {"path": str(deno_path)}}


def test_stream_resolver_returns_separate_video_and_audio_urls(monkeypatch):
    class _FakeYoutubeDL:
        def __init__(self, options):
            assert options["format"].startswith("bestvideo")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def extract_info(self, _url, download):
            assert download is False
            return {
                "requested_formats": [
                    {
                        "url": "https://video.example/track",
                        "vcodec": "avc1",
                        "acodec": "none",
                    },
                    {
                        "url": "https://audio.example/track",
                        "vcodec": "none",
                        "acodec": "mp4a",
                    },
                ],
                "duration": 123,
                "title": "Example",
                "channel": "Channel",
            }

    monkeypatch.setattr(youtube_control, "YoutubeDL", _FakeYoutubeDL)
    youtube_control._cached_streams.clear()

    result = youtube_control.get_youtube_stream_url(
        "https://www.youtube.com/watch?v=abcdefghijk",
        include_other_info=True,
    )

    assert result == (
        ("https://video.example/track", "https://audio.example/track"),
        123,
        "Example",
        "Channel",
    )


def test_media_player_loads_separate_youtube_video_and_audio_tracks():
    mpv = _FakeMpv()
    player = MediaPlayer(mpv)
    mpv.commands.clear()

    player.set_media(("https://video.example/track", "https://audio.example/track"))

    assert mpv.commands == [
        (
            "loadfile",
            "https://video.example/track",
            "replace",
            "-1",
            "audio-file=https://audio.example/track",
        )
    ]


def test_failed_stream_fallback_restores_theme_and_evicts_direct_url(monkeypatch):
    class _Player:
        def __init__(self):
            self.media_calls = []

        def set_media(self, path, start_seconds=None):
            self.media_calls.append((path, start_seconds))

    player = _Player()
    source_url = "https://www.youtube.com/watch?v=abcdefghijk"
    monkeypatch.setattr(streaming.state.widgets, "player", player)
    monkeypatch.setattr(streaming.state.playback, "previous_media", "theme.webm")
    monkeypatch.setattr(
        streaming.state.playback, "currently_playing", {"filename": "round.webm"}
    )
    monkeypatch.setattr(streaming.state.controls, "video_stopped", True)
    monkeypatch.setattr(streaming, "currently_streaming", ["Clip", source_url, "Channel"])
    monkeypatch.setattr(
        streaming, "last_streamed", ["round.webm", "Clip", source_url, "Channel"]
    )
    monkeypatch.setattr(streaming, "_stream_theme_path", "theme.webm")
    monkeypatch.setattr(streaming, "_stream_wall_start", True)
    youtube_control._cached_streams[source_url] = (
        "https://expired.example/video",
        120,
        "Clip",
        "Channel",
    )

    assert streaming.fallback_to_theme(12.5) is True

    assert player.media_calls == [("theme.webm", 12.5)]
    assert streaming.currently_streaming is None
    assert streaming.last_streamed == ["", "", "", ""]
    assert streaming.get_stream_wall_start() is None
    assert streaming.state.controls.video_stopped is False
    assert source_url not in youtube_control._cached_streams
