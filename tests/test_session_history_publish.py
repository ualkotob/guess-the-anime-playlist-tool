from _app_scripts.file import session_end


session_stats = session_end.session_stats


def _theme(timestamp, filename):
    return {
        "timestamp": timestamp,
        "type": "theme",
        "filename": filename,
        "title": filename,
        "slug": "OP1",
    }


def _prepare(monkeypatch, entries):
    pushes = []
    monkeypatch.setattr(session_stats, "session_data", entries)
    monkeypatch.setattr(session_stats, "session_start_time", "2026-08-09_12-00")
    monkeypatch.setattr(session_stats, "_last_web_revealed_theme_entry", None)
    monkeypatch.setattr(session_stats, "_last_web_session_lines", None)
    monkeypatch.setattr(
        session_stats,
        "generate_text_from_session_data",
        lambda data=None: [
            entry["filename"]
            for entry in (session_stats.session_data if data is None else data)
        ],
    )
    monkeypatch.setattr(
        session_stats.web_server,
        "push_session_history",
        lambda lines, filename=None: pushes.append((list(lines), filename)),
    )
    return pushes


def test_reveal_publishes_once_per_theme(monkeypatch):
    first = _theme("2026-08-09 12:00:00", "first.webm")
    entries = [first]
    pushes = _prepare(monkeypatch, entries)

    assert session_stats.publish_revealed_session_history("theme", "first.webm")
    assert not session_stats.publish_revealed_session_history("theme", "first.webm")

    second = _theme("2026-08-09 12:01:00", "second.webm")
    entries.append(second)
    assert session_stats.publish_revealed_session_history("theme", "second.webm")

    assert [lines for lines, _filename in pushes] == [
        ["first.webm"],
        ["first.webm", "second.webm"],
    ]


def test_reveal_does_not_publish_a_previous_theme(monkeypatch):
    pushes = _prepare(
        monkeypatch,
        [_theme("2026-08-09 12:00:00", "previous.webm")],
    )

    assert not session_stats.publish_revealed_session_history("theme", "current.webm")
    assert pushes == []


def test_end_only_republishes_when_session_changed_after_reveal(monkeypatch):
    entries = [_theme("2026-08-09 12:00:00", "theme.webm")]
    pushes = _prepare(monkeypatch, entries)

    assert session_stats.publish_revealed_session_history("theme", "theme.webm")
    assert not session_stats.publish_final_session_history()

    entries.append({"timestamp": "2026-08-09 12:01:00", "type": "bonus", "filename": "bonus"})
    assert session_stats.publish_final_session_history()
    assert len(pushes) == 2


def test_info_display_defers_publish_until_theme_is_logged(monkeypatch):
    callbacks = []
    published = []
    information_popup = session_stats.information_popup

    class _Root:
        def after_idle(self, callback):
            callbacks.append(callback)

    monkeypatch.setattr(information_popup.state.widgets, "root", _Root())
    monkeypatch.setattr(
        information_popup.state.playback,
        "currently_playing",
        {"type": "theme", "filename": "current.webm"},
    )
    monkeypatch.setattr(
        session_stats,
        "publish_revealed_session_history",
        lambda entry_type, filename: published.append((entry_type, filename)),
    )

    information_popup._schedule_revealed_session_history_publish()

    assert published == []
    callbacks[0]()
    assert published == [("theme", "current.webm")]
