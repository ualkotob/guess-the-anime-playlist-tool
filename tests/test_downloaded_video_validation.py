"""Corrupt downloads are rejected before they replace a playable file."""

from types import SimpleNamespace

from _app_scripts.playback import cache_download


def test_ffprobe_rejects_media_without_audio_or_video(monkeypatch):
    monkeypatch.setattr(cache_download.shutil, "which", lambda _name: "ffprobe")
    monkeypatch.setattr(cache_download.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout='{"streams": []}'))
    assert not cache_download._validate_downloaded_video("bad.webm.part")


def test_ffprobe_accepts_video_stream(monkeypatch):
    monkeypatch.setattr(cache_download.shutil, "which", lambda _name: "ffprobe")
    monkeypatch.setattr(cache_download.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout='{"streams": [{"codec_type": "video"}]}'))
    assert cache_download._validate_downloaded_video("good.webm.part")
