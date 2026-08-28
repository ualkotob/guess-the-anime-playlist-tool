from _app_scripts.queue_round.lightning_rounds import (
    character_roster,
    characters_overlay,
    episode_overlay,
)


CHARACTERS_WITH_ALTERNATE = [
    ["a", "Hero Name", "hero-minor.jpg"],
    ["m", "  HERO   NAME  ", "hero-main.jpg"],
    ["a", "Minor One", "minor-1.jpg"],
    ["a", "Minor Two", "minor-2.jpg"],
    ["a", "Minor Three", "minor-3.jpg"],
    ["s", "Supporting", "support.jpg"],
    ["m", "Other Lead", "other-main.jpg"],
]


def test_character_dedupe_prefers_highest_role_and_normalizes_name():
    result = character_roster.dedupe_characters_by_name(
        CHARACTERS_WITH_ALTERNATE
    )

    hero_entries = [
        character
        for character in result
        if character_roster.normalize_character_name(character[1]) == "hero name"
    ]
    assert hero_entries == [["m", "  HERO   NAME  ", "hero-main.jpg"]]


def test_characters_round_uses_main_portrait_not_minor_alternate(monkeypatch):
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

    result = characters_overlay.get_characters_round_characters(
        data={"characters": CHARACTERS_WITH_ALTERNATE},
        queue=True,
        include_names=True,
    )

    normalized_names = [
        character_roster.normalize_character_name(name)
        for name in result["names"]
    ]
    assert normalized_names.count("hero name") == 1
    hero_index = normalized_names.index("hero name")
    assert result["images"][hero_index].endswith("hero-main.jpg")


def test_names_round_does_not_select_minor_alternate_of_main(monkeypatch):
    monkeypatch.setattr(
        episode_overlay.state.playback,
        "currently_playing",
        {"data": {"characters": CHARACTERS_WITH_ALTERNATE}},
    )
    monkeypatch.setattr(episode_overlay.random, "shuffle", lambda _items: None)

    episode_overlay.set_light_names()

    hero_entries = [
        character
        for character in episode_overlay.light_episode_names
        if character_roster.normalize_character_name(character[1]) == "hero name"
    ]
    assert hero_entries == [["m", "  HERO   NAME  "]]
