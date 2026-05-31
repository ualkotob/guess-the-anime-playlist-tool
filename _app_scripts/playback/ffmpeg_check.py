"""FFmpeg availability detection."""

import subprocess


ffmpeg_available = False


def check_ffmpeg_availability():
    """Check if ffmpeg is available in system PATH."""
    global ffmpeg_available
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ffmpeg_available = result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        ffmpeg_available = False
        print("FFmpeg not found in PATH")
    return ffmpeg_available


def is_ffmpeg_available():
    """Return whether ffmpeg is available."""
    return ffmpeg_available
