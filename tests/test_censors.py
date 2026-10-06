import re

from PIL import Image

from _app_scripts.playback.media_player import MediaPlayer
from _app_scripts.toggles import censors
from _app_scripts import utils


def test_anisongdb_file_finds_local_censors_by_shared_song_id(monkeypatch):
    local_filename = (
        "DragonRajaS2-OP1-[MAL]59662[ADB]19480"
        "[ART]Hazel Fernandes[SNG]We Are Made.webm"
    )
    anisongdb_filename = "dq6458pmeqtp15rm.webm"
    local_censors = [{"start": 4.0, "end": 7.0}]
    metadata = {
        local_filename: {
            "mal": "59662",
            "slug": "OP1",
            "version": None,
            "file_properties": {
                "resolution": "1080",
                "anisongdb_amq_song_id": 81131,
            },
        },
        anisongdb_filename: {
            "mal": "59662",
            "slug": "OP1",
            "version": "1",
            "file_properties": {
                "resolution": 720,
                "anisongdb_amq_song_id": 81131,
            },
        },
    }

    monkeypatch.setattr(censors, "censor_list", {local_filename: local_censors})
    monkeypatch.setattr(censors, "other_censor_lists", [])
    monkeypatch.setattr(
        censors.metadata_fetch,
        "get_file_metadata_by_name",
        lambda filename: metadata.get(filename),
    )

    assert censors.find_similar_theme_censors(anisongdb_filename) == {
        local_filename: local_censors
    }


def test_censor_matching_uses_mal_and_slug_without_provider_song_ids(monkeypatch):
    metadata = {
        "local-file.webm": {"mal": "123", "slug": "ED2", "version": None},
        "remote-file.webm": {"mal": 123, "slug": "ed2", "version": "1"},
        "other-anime.webm": {"mal": "456", "slug": "ED2", "version": "1"},
    }
    monkeypatch.setattr(censors, "censor_list", {
        "local-file.webm": [{"start": 1, "end": 2}],
        "other-anime.webm": [{"start": 3, "end": 4}],
    })
    monkeypatch.setattr(censors, "other_censor_lists", [])
    monkeypatch.setattr(
        censors.metadata_fetch,
        "get_file_metadata_by_name",
        lambda filename: metadata.get(filename),
    )

    assert list(censors.find_similar_theme_censors("remote-file.webm")) == [
        "local-file.webm"
    ]


def test_censor_sources_exclude_current_and_keep_main_file_precedence(monkeypatch):
    main_censors = [{"start": 1, "end": 2}]
    imported_duplicate = [{"start": 3, "end": 4}]
    imported_unique = [{"start": 5, "end": 6}]
    monkeypatch.setattr(censors, "censor_list", {
        "current.webm": [{"start": 0, "end": 1}],
        "duplicate.webm": main_censors,
        "empty.webm": [],
    })
    monkeypatch.setattr(censors, "other_censor_lists", [{
        "duplicate.webm": imported_duplicate,
        "unique.webm": imported_unique,
    }])

    assert censors.get_censor_sources("current.webm") == {
        "duplicate.webm": main_censors,
        "unique.webm": imported_unique,
    }


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


def test_color_result_survives_a_destroyed_editor_row():
    target = {"color": None}

    class DestroyedLabel:
        def winfo_exists(self):
            return False

        def config(self, **_kwargs):
            raise AssertionError("a destroyed swatch must not be configured")

    censors._apply_color_result(target, "#12AB34", DestroyedLabel())

    assert target["color"] == "#12AB34"


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


def test_letterbox_rect_uses_display_aspect_not_stored_pixels():
    # 4:3 video on a 16:9 canvas is pillarboxed; 16:9 fills it edge to edge.
    assert utils.letterbox_rect(1920, 1080, 4 / 3) == (240, 0, 1440, 1080)
    assert utils.letterbox_rect(1920, 1080, 16 / 9) == (0, 0, 1920, 1080)
    # 16:9 video in a 4:3 window is letterboxed.
    assert utils.letterbox_rect(1440, 1080, 16 / 9) == (0, 135, 1440, 810)
    # Unknown aspect (mpv has not reported video-params yet) falls back to the
    # full container rather than guessing a shape.
    assert utils.letterbox_rect(1280, 720, 0.0) == (0, 0, 1280, 720)
    assert utils.letterbox_rect(0, 0, 16 / 9) == (0, 0, 0, 0)


def test_display_size_prefers_aspect_corrected_video_params():
    player = MediaPlayer.__new__(MediaPlayer)
    player._c_width, player._c_height = 720, 480
    player._c_disp_width = player._c_disp_height = None

    # Before mpv reports video-params the stored size is all there is.
    assert player.get_display_size() == (720, 480)

    # An anamorphic 4:3 DVD rip stores 720x480 but displays 4:3 — the censor
    # geometry must follow video-params, not the stored pixels.
    player._on_video_params("video-params", {"w": 720, "h": 480, "dw": 720, "dh": 540})
    assert player.get_display_size() == (720, 540)
    assert player.get_display_aspect() == 4 / 3

    # The 16:9 anamorphic rip of the same stored size resolves the other way.
    player._on_video_params("video-params", {"w": 720, "h": 480, "dw": 853, "dh": 480})
    assert round(player.get_display_aspect(), 3) == 1.777

    # Unloading clears the cache instead of stranding the last file's shape.
    player._on_video_params("video-params", None)
    assert player.get_display_size() == (720, 480)


def _draw_single_censor(monkeypatch, osd_w, osd_h, display_size):
    """Commit one full-frame censor and return its (x, y, w, h) in OSD pixels."""
    commands = []
    player = type("Player", (), {})()
    player._p = type("Mpv", (), {"osd_width": osd_w, "osd_height": osd_h})()
    player.get_display_aspect = lambda: display_size[0] / display_size[1]

    monkeypatch.setattr(censors.state.widgets, "player", player)
    monkeypatch.setattr(censors, "_osd_command", lambda *args: commands.append(args))
    monkeypatch.setattr(censors, "_is_filter_suppressing_censors", lambda: False)
    monkeypatch.setattr(censors.filter_overlay, "get_zoom_state", lambda: None)
    monkeypatch.setattr(censors, "censor_boxes", {
        "theme:censor": {
            "censor": {"pos_x": 0, "pos_y": 0, "size_w": 100, "size_h": 100},
            "color": "black",
            "destroying": False,
        }
    })

    censors._commit_censor_osd()

    payload = next(cmd[3] for cmd in commands if cmd[2] == "ass-events")
    drawing = payload.split(r"\p1}")[1].split("{")[0]        # just the "m x y l ..." path
    coords = [int(n) for n in re.findall(r"-?\d+", drawing)]
    xs, ys = coords[0::2], coords[1::2]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def test_censors_follow_the_pillarboxed_rect_of_an_anamorphic_4_3_file(monkeypatch):
    # UltraManiac-OP1.webm: stored 720x480, SAR 8:9, so mpv displays it 4:3.
    # A full-frame censor must cover only the 4:3 video, not the black pillars.
    assert _draw_single_censor(monkeypatch, 1920, 1080, (720, 540)) == (240, 0, 1440, 1080)
    # The 16:9 rip of the same stored size still fills the screen (853x480 is a
    # hair under 16:9, so it is inset by a pixel rather than exactly flush).
    x, y, w, h = _draw_single_censor(monkeypatch, 1920, 1080, (853, 480))
    assert (x, y, h) == (0, 0, 1080) and w >= 1919


def test_censor_rect_is_window_shape_independent_for_anamorphic_files(monkeypatch):
    # Same censor, two window shapes: the box must keep the same fraction of the
    # video (the whole of it here) instead of shifting between windowed and
    # fullscreen, which is what the old 720x480 -> 16:9 assumption caused.
    wide_x, _, wide_w, wide_h = _draw_single_censor(monkeypatch, 1920, 1080, (720, 540))
    tall_x, _, tall_w, tall_h = _draw_single_censor(monkeypatch, 1200, 900, (720, 540))
    assert round(wide_w / wide_h, 3) == round(tall_w / tall_h, 3) == round(4 / 3, 3)
    assert (wide_x, tall_x) == (240, 0)
