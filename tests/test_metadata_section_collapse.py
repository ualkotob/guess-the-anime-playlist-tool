from _app_scripts.file.metadata import metadata_panel


def _themes(kind, count):
    return [
        {"type": kind, "slug": f"{kind}{number}"}
        for number in range(1, count + 1)
    ]


def test_auto_collapse_uses_inserts_first_and_stops_under_threshold(monkeypatch):
    monkeypatch.setattr(metadata_panel, "_collapsed_sections", set())
    themes = _themes("OP", 4) + _themes("ED", 3) + _themes("IN", 4)

    metadata_panel._auto_init_section_collapse("1", themes, "OP1")

    assert metadata_panel._collapsed_sections == {("1", "IN")}


def test_auto_collapse_uses_op_or_ed_only_when_inserts_are_not_enough(monkeypatch):
    monkeypatch.setattr(metadata_panel, "_collapsed_sections", set())
    themes = _themes("OP", 5) + _themes("ED", 5) + _themes("IN", 1)

    metadata_panel._auto_init_section_collapse("1", themes, "OP1")

    assert metadata_panel._collapsed_sections == {("1", "IN"), ("1", "ED")}


def test_auto_collapse_keeps_the_playing_insert_section_open(monkeypatch):
    monkeypatch.setattr(metadata_panel, "_collapsed_sections", set())
    themes = _themes("OP", 5) + _themes("ED", 2) + _themes("IN", 4)

    metadata_panel._auto_init_section_collapse("1", themes, "IN1")

    assert metadata_panel._collapsed_sections == {("1", "OP")}


def test_auto_collapse_leaves_all_sections_open_at_threshold(monkeypatch):
    monkeypatch.setattr(metadata_panel, "_collapsed_sections", {("1", "IN"), ("2", "ED")})
    themes = _themes("OP", 3) + _themes("ED", 3) + _themes("IN", 2)

    metadata_panel._auto_init_section_collapse("1", themes, "OP1")

    assert metadata_panel._collapsed_sections == {("2", "ED")}
