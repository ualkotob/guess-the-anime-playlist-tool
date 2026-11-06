from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.game_state import GameState
from _app_scripts.playback import transport
from _app_scripts.queue_round.lightning_rounds import lightning_manager as lm


@pytest.fixture
def clue_answer(monkeypatch):
    state = GameState()
    player = Mock()
    player._p = SimpleNamespace(osd_width=1280, osd_height=720)
    player.get_time.return_value = 11_000
    player.is_playing.return_value = True
    player.set_time.side_effect = lambda value: setattr(
        player.get_time, "return_value", value
    )
    state.widgets.player = player
    state.lightning.light_round_started = True
    state.lightning.light_round_start_time = 10
    state.lightning.light_round_length = 20
    state.lightning.light_round_answer_length = 8
    state.playback.currently_playing.update(filename="theme.webm")
    for module in (lm, transport, lm.tag_cloud_overlay, lm.episode_overlay):
        monkeypatch.setattr(module, "state", state)

    monkeypatch.setattr(transport, "seek_to", player.set_time)
    monkeypatch.setattr(lm, "_wall_time", lambda: 100)
    monkeypatch.setattr(lm.streaming, "currently_streaming", None)
    monkeypatch.setattr(lm.streaming, "last_streamed", [None] * 4)
    monkeypatch.setattr(lm.cover_image_overlay, "light_cover_image", None)
    monkeypatch.setattr(lm.cover_image_overlay, "last_image_source", [None, None])
    monkeypatch.setattr(lm.trivia_round, "light_trivia_answer", None)
    monkeypatch.setattr(lm.frame_round, "frame_light_round_started", False)
    monkeypatch.setattr(lm.blind_screen, "_video_frame_active", False)
    monkeypatch.setattr(lm.blind_screen, "black_overlay", False)
    monkeypatch.setattr(lm.synopsis_overlay, "_mc_last_choices", None)
    monkeypatch.setattr(lm.synopsis_overlay, "synopsis_start_index", None)
    for name, value in (
        ("_mismatch_active", False), ("_mismatch_hwnd", 0),
        ("_main_hwnd", 0), ("_note_hwnd", 0),
        ("_mismatch_reveal_pending", False), ("mismatch_visuals", None),
    ):
        monkeypatch.setattr(lm.mismatch_round, name, value)
    monkeypatch.setattr(lm.characters_overlay, "characters_round_characters", [])
    monkeypatch.setattr(lm.characters_overlay, "characters_round_names", [])
    for name, value in (
        ("tag_cloud_tags", []), ("tag_cloud_positions", []),
        ("_tag_cloud_font_sizes", []), ("_tag_cloud_last_osd_h", 0),
    ):
        monkeypatch.setattr(lm.tag_cloud_overlay, name, value)
    monkeypatch.setattr(lm.episode_overlay, "light_episode_names", [])
    monkeypatch.setattr(lm.episode_overlay, "light_name_overlay", False)
    monkeypatch.setattr(lm.episode_overlay, "episode_overlay_boxes", {})

    for module, names in (
        (lm, ("_restore_lightning_answer_audio", "update_light_round_number")),
        (lm.mismatch_round, ("_uninstall_mismatch_hook",)),
        (lm.progress_overlay_ops, ("set_progress_overlay",)),
        (lm.title_overlay, ("toggle_title_overlay",)),
        (lm.scramble_overlay, ("toggle_scramble_overlay",)),
        (lm.swap_overlay, ("toggle_swap_overlay",)),
        (lm.peek_overlay, ("toggle_peek_overlay",)),
        (lm.edge_overlay, ("toggle_edge_overlay",)),
        (lm.grow_overlay, ("toggle_grow_overlay",)),
        (lm.image_reveal_overlays, (
            "toggle_tile_overlay", "toggle_character_pixel_overlay",
            "toggle_character_reveal_overlay", "toggle_character_blur_reveal_overlay",
            "toggle_character_zoom_reveal_overlay", "toggle_slice_overlay",
        )),
        (lm.overlay_primitives, (
            "spawn_pulsating_music_note", "toggle_outer_edge_overlay",
        )),
        (lm.character_parts_overlay, ("toggle_character_image_overlay",)),
        (lm.clues_overlay, ("toggle_clues_overlay",)),
        (lm.song_overlay, ("toggle_song_overlay",)),
        (lm.profile_overlay, ("toggle_character_profile_overlay",)),
        (lm.characters_overlay, ("toggle_characters_overlay",)),
        (lm.emoji_overlay, ("toggle_emoji_overlay",)),
        (lm.filter_overlay, ("toggle_filter_vf",)),
        (lm.blind_screen, ("set_video_frame", "set_black_screen")),
        (lm.synopsis_overlay, ("toggle_mc_choices_overlay", "toggle_synopsis_overlay")),
        (lm.osd_text, ("bottom_info", "top_info", "set_countdown")),
        (lm.scoreboard_control, ("send_command",)),
        (lm.information_popup, ("toggle_title_popup",)),
        (lm.round_start_guard, ("after",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, Mock())
    monkeypatch.setattr(lm.web_server, "is_running", lambda: False)
    monkeypatch.setattr(lm.osd_text, "_color_str_to_ass_bgr", lambda color: color)
    monkeypatch.setattr(lm.osd_text, "_ass_wrap_text", lambda text, *_args: [text])
    commands = []
    monkeypatch.setattr(lm.osd_text, "osd_command", lambda *args: commands.append(args))
    return state, commands


def _start_clues(state, mode):
    # Variety selects a concrete current_light_mode; retention must use that mode.
    state.lightning.light_mode = "variety"
    state.lightning.current_light_mode = mode
    if mode == "tags":
        clues = [f"Tag {index}" for index in range(8)]
        lm.tag_cloud_overlay.tag_cloud_tags = [
            {"name": clue, "weight": 600} for clue in clues
        ]
        lm.tag_cloud_overlay.toggle_tag_cloud_overlay(num_tags=1)
        return lm.tag_cloud_overlay._TAG_CLOUD_ASS_OSD_ID, clues

    clues = [f"Clue {index}" for index in range(8 if mode == "episodes" else 6)]
    lm.episode_overlay.light_name_overlay = mode == "names"
    lm.episode_overlay.light_episode_names = (
        [["m", clue] for clue in clues] if mode == "names" else clues
    )
    lm.episode_overlay.toggle_episode_overlay(num_episodes=1)
    return lm.episode_overlay._EPISODE_ASS_OSD_ID, clues[:6]


@pytest.mark.parametrize("mode", ["tags", "episodes", "names"])
@pytest.mark.parametrize("skip", [False, True], ids=["timer", "skip"])
def test_answer_reveals_remaining_clues_and_next_skip_clears_them(
    clue_answer, mode, skip
):
    state, commands = clue_answer
    osd_id, clues = _start_clues(state, mode)
    partial_payload = commands[-1][3]
    assert clues[0] in partial_payload
    assert clues[-1] not in partial_payload
    commands.clear()

    if skip:
        transport.play_next()
        assert state.widgets.player.get_time() == 30_050
        answer_time = state.widgets.player.get_time() / 1000
    else:
        answer_time = 30.1
    lm.update_light_round(answer_time)

    payloads = [cmd[3] for cmd in commands if cmd[1:3] == (osd_id, "ass-events")]
    assert len(payloads) == 1
    assert all(clue in payloads[0] for clue in clues)
    assert state.lightning._showed_lightning_answer is True
    if mode == "episodes":
        assert "Clue 6" not in payloads[0]
        assert "Clue 7" not in payloads[0]
    if mode == "names":
        assert lm.episode_overlay.light_name_overlay is True
        assert "#1E3A8A" in payloads[0]
        assert "['m'," not in payloads[0]

    transport.play_next()

    assert any(cmd[1:3] == (osd_id, "none") for cmd in commands)
    assert lm.tag_cloud_overlay.tag_cloud_tags == []
    assert lm.tag_cloud_overlay.tag_cloud_positions == []
    assert lm.episode_overlay.light_episode_names == []
    assert lm.episode_overlay.episode_overlay_boxes == {}
    assert lm.episode_overlay.light_name_overlay is False


@pytest.mark.parametrize("mode", ["tags", "episodes", "names"])
def test_answer_clue_retention_can_be_disabled(clue_answer, mode):
    state, commands = clue_answer
    osd_id, _clues = _start_clues(state, mode)
    setting = f"show_{mode}_during_answer"
    assert lm.lightning_settings.update_lightning_mode_settings({})[mode][setting] is True
    state.playback.lightning_mode_settings = {mode: {setting: False}}
    commands.clear()

    lm.update_light_round(30.1)

    assert any(cmd[1:3] == (osd_id, "none") for cmd in commands)
    assert not any(cmd[1:3] == (osd_id, "ass-events") for cmd in commands)
