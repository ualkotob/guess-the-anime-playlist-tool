from PIL import Image

from _app_scripts.queue_round.lightning_rounds import (
    characters_overlay,
    lightning_manager,
    lightning_settings,
)


def test_characters_stay_during_answer_by_default(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "characters"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"characters": {}},
    )

    assert (
        lightning_settings.lightning_mode_settings_default["characters"]
        ["show_characters_during_answer"]
        is True
    )
    assert lightning_manager._should_keep_characters() is True


def test_character_answer_overlay_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        lightning_manager.state.lightning, "current_light_mode", "characters"
    )
    monkeypatch.setattr(
        lightning_manager.state.playback,
        "lightning_mode_settings",
        {"characters": {"show_characters_during_answer": False}},
    )

    assert lightning_manager._should_keep_characters() is False


def test_prefetched_character_names_stay_aligned_with_images(monkeypatch):
    class Root:
        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

    monkeypatch.setattr(characters_overlay.state.widgets, "root", Root())
    monkeypatch.setattr(characters_overlay.random, "shuffle", lambda _items: None)
    monkeypatch.setattr(
        characters_overlay.image_loader,
        "load_image_from_url",
        lambda url, size=None: url,
    )
    data = {
        "characters": [
            ["a", "Appear One", "appear-1.jpg"],
            ["a", "Appear Two", "appear-2.jpg"],
            ["s", "Supporting", "support.jpg"],
            ["m", "Main", "main.jpg"],
        ]
    }

    result = characters_overlay.get_characters_round_characters(
        data=data, queue=True, include_names=True
    )

    assert result["names"] == [
        "Appear One",
        "Appear Two",
        "Supporting",
        "Main",
    ]
    assert [image.rsplit("/", 1)[-1] for image in result["images"]] == [
        "appear-1.jpg",
        "appear-2.jpg",
        "support.jpg",
        "main.jpg",
    ]


def test_character_names_are_drawn_only_for_answer_view(monkeypatch):
    captions = []

    class ImageOverlay:
        def update(self, _canvas):
            pass

    class Backend:
        osd_width = 400
        osd_height = 300

        def create_image_overlay(self):
            return ImageOverlay()

    class Player:
        _p = Backend()

    images = [Image.new("RGBA", (100, 100), "red") for _ in range(2)]
    monkeypatch.setattr(characters_overlay.state.widgets, "player", Player())
    monkeypatch.setattr(characters_overlay, "characters_round_characters", images)
    monkeypatch.setattr(
        characters_overlay, "characters_round_names", ["Alpha", "Beta"]
    )
    monkeypatch.setattr(characters_overlay, "_characters_img_overlay", None)
    monkeypatch.setattr(characters_overlay.ImageTk, "getimage", lambda image: image)
    monkeypatch.setattr(
        characters_overlay,
        "_draw_character_caption",
        lambda _draw, name, *_args: captions.append(name),
    )

    characters_overlay.toggle_characters_overlay(
        num_characters=2, show_names=False
    )
    assert captions == []

    characters_overlay.toggle_characters_overlay(
        num_characters=2, show_names=True
    )
    assert captions == ["Alpha", "Beta"]


def test_named_answer_grid_moves_up_to_clear_info_popup():
    centered = characters_overlay._get_grid_margin_y(
        osd_h=1152,
        img_size=403,
        in_between=25,
        answer_view=False,
    )
    answer = characters_overlay._get_grid_margin_y(
        osd_h=1152,
        img_size=403,
        in_between=25,
        answer_view=True,
    )

    assert centered - answer == 32
