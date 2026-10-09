"""Small file logger for recoverable app errors.

This intentionally avoids application state, Tk, and mpv so any extracted
module can use it without creating new dependency loops.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler


LOG_FOLDER = "logs"
LOG_FILE = os.path.join(LOG_FOLDER, "guess_the_anime.log")

_logger = None


def get_logger() -> logging.Logger:
    """Return the shared app logger, initializing it on first use."""
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(LOG_FOLDER, exist_ok=True)

    logger = logging.getLogger("guess_the_anime")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(getattr(h, "_gta_file_handler", False) for h in logger.handlers):
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler._gta_file_handler = True
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        ))
        logger.addHandler(handler)

    _logger = logger
    return logger


def log_exception(message: str, *args, **kwargs) -> None:
    """Log the active exception without raising logging errors to callers."""
    try:
        get_logger().exception(message, *args, **kwargs)
    except Exception:
        pass


def log_warning(message: str, *args, **kwargs) -> None:
    """Log a recoverable warning without raising logging errors to callers."""
    try:
        get_logger().warning(message, *args, **kwargs)
    except Exception:
        pass


@contextmanager
def watch_for_stall(operation: str, *, warn_after=1.0, dump_after=5.0):
    """Log slow work and thread stacks during a stall without blocking Tk."""
    started = time.monotonic()
    finished = threading.Event()

    def dump_threads():
        if finished.is_set():
            return
        log_warning("Still waiting after %.1fs: %s", dump_after, operation)
        frames = sys._current_frames()
        for thread in threading.enumerate():
            frame = frames.get(thread.ident)
            if frame is not None and thread is not threading.current_thread():
                log_warning("%s — thread %s:\n%s", operation, thread.name,
                            "".join(traceback.format_stack(frame, limit=20)))

    timer = None
    try:
        timer = threading.Timer(dump_after, dump_threads)
        timer.daemon = True
        timer.start()
    except Exception:
        timer = None  # Diagnostics must never prevent playback or rendering.
    try:
        yield
    finally:
        finished.set()
        if timer is not None:
            timer.cancel()
        elapsed = time.monotonic() - started
        if elapsed >= warn_after:
            log_warning("Slow operation (%.3fs): %s", elapsed, operation)
