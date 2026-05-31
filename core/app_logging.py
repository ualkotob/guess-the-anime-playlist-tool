"""Small file logger for recoverable app errors.

This intentionally avoids application state, Tk, and mpv so any extracted
module can use it without creating new dependency loops.
"""

from __future__ import annotations

import logging
import os
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
