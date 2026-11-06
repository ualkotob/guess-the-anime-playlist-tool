from core import app_logging


def test_stall_watch_records_thread_stacks_and_completion_time(monkeypatch):
    timers, messages = [], []
    class Timer:
        def __init__(self, delay, callback):
            self.callback = callback
            self.cancelled = False
            timers.append(self)
        def start(self):
            pass
        def cancel(self):
            self.cancelled = True
    times = iter([0, 6])
    monkeypatch.setattr(app_logging.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(app_logging.threading, "Timer", Timer)
    monkeypatch.setattr(app_logging.threading, "current_thread", lambda: object())
    monkeypatch.setattr(app_logging, "log_warning", lambda message, *args:
                        messages.append(message % args))
    with app_logging.watch_for_stall("Playback"):
        timers[0].callback()
    assert any("Still waiting" in message for message in messages)
    assert any("thread MainThread" in message for message in messages)
    assert any("Slow operation (6.000s): Playback" == message for message in messages)
    assert timers[0].cancelled
    count = len(messages)
    timers[0].callback()
    assert len(messages) == count


def test_ui_stall_logs_every_thread_once_while_the_loop_is_blocked(monkeypatch):
    import threading
    from types import SimpleNamespace
    from core import ui_watchdog
    messages = []
    monkeypatch.setattr(ui_watchdog, "get_logger", lambda: SimpleNamespace(
        warning=lambda message, *args: messages.append(message % args)))
    monkeypatch.setattr(ui_watchdog, "_last_tick", 100.0)
    monkeypatch.setattr(ui_watchdog, "_stack_logged_for", None)
    monkeypatch.setattr(ui_watchdog, "_last_stack_time", 0.0)
    ready, release = threading.Event(), threading.Event()
    def build_index():
        ready.set()
        release.wait(2)
    worker = threading.Thread(target=build_index, name="index-builder")
    worker.start()
    try:
        assert ready.wait(2)
        ui_watchdog._check_for_stall(100.3)  # Late, but too short for a stack.
        assert messages == []
        ui_watchdog._check_for_stall(100.7)
        ui_watchdog._check_for_stall(105.0)  # The same stall is logged once.
    finally:
        release.set()
        worker.join(2)
    assert len(messages) == 1
    assert "UI stall in progress (~0.60s)" in messages[0]
    assert "test_ui_stall_logs_every_thread_once_while_the_loop_is_blocked" in messages[0]
    assert "index-builder: " in messages[0] and "build_index" in messages[0]
    ui_watchdog._last_tick = 110.0  # The loop recovered, then blocked again.
    ui_watchdog._check_for_stall(111.0)
    assert len(messages) == 2


def test_ui_watchdog_sampler_stops_when_the_app_closes(monkeypatch):
    import threading
    from core import ui_watchdog
    checked = threading.Event()
    monkeypatch.setattr(ui_watchdog, "_stopped", threading.Event())
    monkeypatch.setattr(ui_watchdog, "_SAMPLE_EVERY_S", 0.01)
    monkeypatch.setattr(ui_watchdog, "_check_for_stall", lambda now: checked.set())
    sampler = threading.Thread(target=ui_watchdog._sample)
    sampler.start()
    assert checked.wait(2)
    ui_watchdog.stop()
    sampler.join(2)
    assert not sampler.is_alive()
