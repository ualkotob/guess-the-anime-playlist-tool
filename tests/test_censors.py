from PIL import Image

from _app_scripts.toggles import censors


def test_rectangle_result_keeps_target_after_editor_rows_are_rebuilt():
    target = {
        "size_w": 100.0, "size_h": 100.0,
        "pos_x": 0.0, "pos_y": 0.0,
        "start": 5.0, "end": 10.0,
        "color": None, "nsfw": False,
    }
    original_target = target

    # Saving before an editor refresh must preserve the record identity held by
    # an already-open RectangleDrawerOverlay callback.
    censors._replace_censor_in_place(target, dict(target))
    editor_censors = [
        {"size_w": 100.0, "size_h": 100.0, "pos_x": 0.0, "pos_y": 0.0,
         "start": 1.0, "end": 2.0, "color": None, "nsfw": False},
        target,
    ]
    editor_censors.sort(key=lambda censor: (censor["start"], censor["end"]))

    censors._apply_rectangle_result(target, "25.00x30.00,40.00x50.00,15.00,ellipse")

    assert target is original_target
    assert any(censor is target for censor in editor_censors)
    assert target == {
        "size_w": 25.0, "size_h": 30.0,
        "pos_x": 40.0, "pos_y": 50.0,
        "rotation": 15.0, "shape": "ellipse",
        "start": 5.0, "end": 10.0,
        "color": None, "nsfw": False,
    }


def test_prime_start_censors_uses_end_of_initial_skip(monkeypatch):
    skip = {"skip": True, "start": 0, "end": 5}
    ended_during_skip = {"start": 0, "end": 4, "color": "red"}
    active_before_skip_end = {"start": 3, "end": 7, "color": "green"}
    active_at_skip_end = {"start": 5, "end": 8, "color": "blue"}
    starts_after_skip = {"start": 6, "end": 9, "color": "yellow"}
    file_censors = [
        skip,
        ended_during_skip,
        active_before_skip_end,
        active_at_skip_end,
        starts_after_skip,
    ]
    primed = []

    monkeypatch.setattr(censors, "censors_enabled", True)
    monkeypatch.setattr(censors, "censors_nsfw_enabled", True)
    monkeypatch.setattr(censors.mismatch_round, "mismatch_visuals", False)
    monkeypatch.setattr(censors.streaming, "currently_streaming", False)
    monkeypatch.setattr(censors, "get_file_censors", lambda filename: file_censors)
    monkeypatch.setattr(censors, "_is_filter_suppressing_censors", lambda: False)
    monkeypatch.setattr(censors, "_commit_censor_osd", lambda: None)

    def record_censor(filename, censor, enabled):
        primed.append(censor)
        return {"color": "black", "destroying": False}

    monkeypatch.setattr(censors, "toggle_censor_box", record_censor)

    censors._prime_start_censors("theme.mp4")

    assert primed == [active_before_skip_end, active_at_skip_end]


def test_commit_keeps_censors_behind_active_blind(monkeypatch):
    commands = []
    player = type("Player", (), {})()
    player._p = type("Mpv", (), {"osd_width": 1280, "osd_height": 720})()
    player.video_get_size = lambda _track: (1280, 720)

    monkeypatch.setattr(censors.state.widgets, "player", player)
    monkeypatch.setattr(censors, "_osd_command", lambda *args: commands.append(args))
    monkeypatch.setattr(censors, "_is_filter_suppressing_censors", lambda: False)
    monkeypatch.setattr(censors.filter_overlay, "get_zoom_state", lambda: None)
    monkeypatch.setattr(censors, "censor_boxes", {
        "theme:censor": {
            "censor": {"pos_x": 10, "pos_y": 10, "size_w": 20, "size_h": 20},
            "color": "black",
            "destroying": False,
        }
    })

    import _app_scripts.playback.blind_screen as blind_screen
    monkeypatch.setattr(blind_screen, "black_overlay", True)

    censors._commit_censor_osd()

    drawn = [cmd for cmd in commands if cmd[0] == "osd-overlay" and cmd[2] == "ass-events"]
    assert drawn
    assert drawn[0][-2] == -1


def test_dynamic_color_is_prewarmed_before_censor_starts(monkeypatch):
    dynamic = {"start": 10, "end": 12, "color": None}
    samples = []

    monkeypatch.setattr(censors, "censors_enabled", True)
    monkeypatch.setattr(censors, "censors_nsfw_enabled", True)
    monkeypatch.setattr(censors.mismatch_round, "mismatch_visuals", False)
    monkeypatch.setattr(censors.streaming, "currently_streaming", False)
    monkeypatch.setattr(censors, "_is_filter_suppressing_censors", lambda: False)
    monkeypatch.setattr(censors, "show_censor", lambda censor, check_title=True: True)
    monkeypatch.setattr(censors, "_get_dynamic_censor_color",
                        lambda: samples.append(True) or "#123456")
    monkeypatch.setattr(censors, "toggle_censor_box", lambda *args, **kwargs: None)
    monkeypatch.setattr(censors, "get_file_censors", lambda filename: [dynamic])

    censors.check_file_censors("theme.mp4", 9.6, check_title=True)

    assert samples == [True]


def test_fixed_color_does_not_start_prewarm(monkeypatch):
    fixed = {"start": 10, "end": 12, "color": "#abcdef"}
    samples = []

    monkeypatch.setattr(censors, "censors_enabled", True)
    monkeypatch.setattr(censors, "censors_nsfw_enabled", True)
    monkeypatch.setattr(censors.mismatch_round, "mismatch_visuals", False)
    monkeypatch.setattr(censors.streaming, "currently_streaming", False)
    monkeypatch.setattr(censors, "_is_filter_suppressing_censors", lambda: False)
    monkeypatch.setattr(censors, "show_censor", lambda censor, check_title=True: True)
    monkeypatch.setattr(censors, "_get_dynamic_censor_color",
                        lambda: samples.append(True) or "#123456")

    result = censors.prewarm_dynamic_censor_color(
        "theme.mp4", 9.6, file_censors=[fixed]
    )

    assert result == censors._dyn_color_latest
    assert samples == []


def test_retiring_color_worker_cannot_publish_into_new_file(monkeypatch):
    monkeypatch.setattr(censors, "_dyn_color_generation", 8)
    monkeypatch.setattr(censors, "_dyn_color_latest", "#newfile")
    monkeypatch.setattr(censors, "_dyn_color_worker_running", True)
    monkeypatch.setattr(censors, "_compute_frame_color", lambda: "#oldfile")

    censors._dyn_color_worker(7)

    assert censors._dyn_color_latest == "#newfile"
    assert censors._dyn_color_worker_running is True


def test_warmed_color_replaces_primed_fallback_before_rebuild(monkeypatch):
    dynamic = {"start": 0, "end": 5, "color": None}
    fixed = {"start": 0, "end": 5, "color": "#fixed"}
    monkeypatch.setattr(censors, "_dyn_color_latest", "#123456")
    monkeypatch.setattr(censors, "censor_boxes", {
        "dynamic": {"censor": dynamic, "color": "black", "destroying": False},
        "fixed": {"censor": fixed, "color": "#fixed", "destroying": False},
    })

    changed = censors.refresh_active_dynamic_censor_colors()

    assert changed is True
    assert censors.censor_boxes["dynamic"]["color"] == "#123456"
    assert censors.censor_boxes["fixed"]["color"] == "#fixed"


def test_frame_color_inherits_active_fullscreen_fixed_censor(monkeypatch):
    calls = []

    class FakeMpv:
        def screenshot_raw(self, *, includes):
            calls.append(includes)
            return Image.new("RGB", (16, 16), (10, 20, 30))

    player = type("Player", (), {"_p": FakeMpv()})()
    monkeypatch.setattr(censors.state.widgets, "player", player)
    monkeypatch.setattr(censors, "censor_boxes", {
        "fixed": {
            "censor": {"size_w": 100, "size_h": 100, "color": "#eeeeee"},
            "color": "#eeeeee",
            "destroying": False,
        }
    })

    assert censors._compute_frame_color() == "#eeeeee"
    assert calls == []


def test_frame_color_excludes_partial_censor_from_raw_video(monkeypatch):
    calls = []
    image = Image.new("RGB", (16, 16), (200, 0, 0))
    for x in range(8, 16):
        for y in range(16):
            image.putpixel((x, y), (0, 20, 40))

    class FakeMpv:
        def screenshot_raw(self, *, includes):
            calls.append(includes)
            return image

    player = type("Player", (), {"_p": FakeMpv()})()
    monkeypatch.setattr(censors.state.widgets, "player", player)
    monkeypatch.setattr(censors, "censor_boxes", {
        "fixed": {
            "censor": {
                "size_w": 50, "size_h": 100,
                "pos_x": 0, "pos_y": 0,
                "color": "#cc0000",
            },
            "color": "#cc0000",
            "destroying": False,
        }
    })

    assert censors._compute_frame_color() == "#001428"
    assert calls == ["video"]
