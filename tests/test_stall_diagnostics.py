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
