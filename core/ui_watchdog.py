"""Tk main-loop stall watchdog.

Schedules a lightweight 100ms tick on the Tk event loop and measures how late
each tick arrives. When the loop is blocked (synchronous I/O, GIL starvation,
long callbacks), ticks arrive late and the drift is logged to the app log with
a timestamp — turning "the overlay froze for a second" into a datable,
sizable record that can be correlated with what the session was doing.

Kept free of application state, Tk widget refs, and mpv (like app_logging) so
it can never participate in a dependency cycle. Start it once with
start(root) after the root window exists.
"""

import time

from core.app_logging import get_logger

_INTERVAL_MS = 100          # watchdog tick period
_LOG_THRESHOLD_S = 0.25     # log individual stalls at least this long
_LOG_RATE_LIMIT_S = 2.0     # min seconds between individual stall log lines
_SUMMARY_EVERY_S = 600.0    # periodic summary window (10 min)

_last_tick = None
_last_log_time = 0.0
_summary_start = None
_stall_count = 0
_stall_total = 0.0
_stall_max = 0.0


def _tick(root):
    global _last_tick, _last_log_time, _summary_start
    global _stall_count, _stall_total, _stall_max

    now = time.monotonic()
    if _last_tick is not None:
        late = now - _last_tick - (_INTERVAL_MS / 1000.0)
        if late >= _LOG_THRESHOLD_S:
            _stall_count += 1
            _stall_total += late
            _stall_max = max(_stall_max, late)
            if now - _last_log_time >= _LOG_RATE_LIMIT_S:
                _last_log_time = now
                get_logger().warning("UI stall: main loop blocked ~%.2fs", late)

    if _summary_start is None:
        _summary_start = now
    elif now - _summary_start >= _SUMMARY_EVERY_S:
        if _stall_count:
            get_logger().info(
                "UI stall summary: %d stalls >=%.0fms in last %.0fmin (max %.2fs, total %.1fs)",
                _stall_count, _LOG_THRESHOLD_S * 1000,
                (now - _summary_start) / 60.0, _stall_max, _stall_total,
            )
        _stall_count = 0
        _stall_total = 0.0
        _stall_max = 0.0
        _summary_start = now

    _last_tick = now
    try:
        root.after(_INTERVAL_MS, _tick, root)
    except Exception:
        pass  # root destroyed — watchdog ends with the app


def start(root):
    """Begin watching the given Tk root's event loop."""
    root.after(_INTERVAL_MS, _tick, root)
