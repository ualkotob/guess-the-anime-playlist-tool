import tools.apply_missing_series_overrides as series_audit


build_audit = series_audit.build_audit


def _anime(title, *, series=None, anisongdb_only=False):
    return {
        "title": title,
        "series": series,
        "songs": [{"slug": "OP1", "anisongdb_only": anisongdb_only}],
    }


def _edge(relation_type, mal_id, title):
    return {
        "relationType": relation_type,
        "node": {
            "idMal": mal_id,
            "type": "ANIME",
            "title": {"romaji": title, "english": None, "native": None},
            "synonyms": [],
        },
    }


def _relations(title, *edges):
    return {
        "title": {"romaji": title, "english": None, "native": None},
        "synonyms": [],
        "relations": {"edges": list(edges)},
    }


def test_related_titles_are_assigned_but_standalone_with_many_songs_is_not():
    anime = {
        70001: _anime("Example Show"),
        70002: _anime("Example Show 2", anisongdb_only=True),
        70003: {
            "title": "Standalone",
            "series": None,
            "songs": [{"slug": "OP1"}, {"slug": "ED1"}],
        },
    }
    relations = {
        "70001": _relations("Example Show", _edge("SEQUEL", 70002, "Example Show 2")),
        "70002": _relations("Example Show 2", _edge("PREQUEL", 70001, "Example Show")),
        "70003": _relations("Standalone"),
    }

    audit = build_audit(anime, relations)

    assert audit["assignments"][70001] == ["Example Show"]
    assert audit["assignments"][70002] == ["Example Show"]
    assert 70003 not in audit["assignments"]


def test_crossover_child_receives_both_series_without_flattening_parents():
    anime = {
        70101: _anime("Alpha Rangers"),
        70102: _anime("Beta Detectives"),
        70103: _anime("Alpha Rangers x Beta Detectives"),
    }
    relations = {
        "70101": _relations(
            "Alpha Rangers",
            _edge("SIDE_STORY", 70103, "Alpha Rangers x Beta Detectives"),
        ),
        "70102": _relations(
            "Beta Detectives",
            _edge("SIDE_STORY", 70103, "Alpha Rangers x Beta Detectives"),
        ),
        "70103": _relations(
            "Alpha Rangers x Beta Detectives",
            _edge("PARENT", 70101, "Alpha Rangers"),
            _edge("PARENT", 70102, "Beta Detectives"),
        ),
    }

    audit = build_audit(anime, relations)

    assert audit["assignments"][70101] == ["Alpha Rangers"]
    assert audit["assignments"][70102] == ["Beta Detectives"]
    assert audit["assignments"][70103] == ["Alpha Rangers", "Beta Detectives"]


def test_missing_relative_inherits_an_existing_multi_series_membership():
    anime = {
        70201: _anime("Shared Universe", series=["Alpha", "Beta"]),
        70202: _anime("Shared Universe Special", anisongdb_only=True),
    }
    relations = {
        "70202": _relations(
            "Shared Universe Special",
            _edge("PARENT", 70201, "Shared Universe"),
        ),
    }

    audit = build_audit(anime, relations)

    assert audit["assignments"][70202] == ["Alpha", "Beta"]


def test_verified_title_family_covers_entries_absent_from_anilist(monkeypatch):
    anime = {
        70301: _anime("Known Franchise", series=["Existing Universe"]),
        70302: _anime("Known Franchise Special Edition", anisongdb_only=True),
    }
    monkeypatch.setattr(
        series_audit,
        "VERIFIED_SERIES_GROUPS",
        {"Known Franchise": (70301, 70302)},
    )

    audit = build_audit(anime, relations={})

    assert audit["assignments"][70301] == ["Existing Universe", "Known Franchise"]
    assert audit["assignments"][70302] == ["Known Franchise"]
    assert audit["unresolved_without_relations"] == []


def test_missing_local_parent_can_bridge_to_an_existing_series(monkeypatch):
    anime = {
        70401: _anime("Known Franchise Season 3", series=["Known Franchise"]),
        70402: _anime("Known Franchise Holiday Special", anisongdb_only=True),
    }
    relations = {
        "70402": _relations(
            "Known Franchise Holiday Special",
            _edge("PARENT", 79999, "Known Franchise"),
        )
    }
    monkeypatch.setattr(series_audit, "VERIFIED_SERIES_GROUPS", {})

    audit = build_audit(anime, relations)

    assert audit["assignments"][70402] == ["Known Franchise"]


def test_unrelated_external_alternative_does_not_bridge_series(monkeypatch):
    anime = {
        70501: _anime("Known Franchise Season 3", series=["Known Franchise"]),
        70502: _anime("Unrelated Anthology Segment", anisongdb_only=True),
    }
    relations = {
        "70502": _relations(
            "Unrelated Anthology Segment",
            _edge("ALTERNATIVE", 79999, "Known Franchise"),
        )
    }
    monkeypatch.setattr(series_audit, "VERIFIED_SERIES_GROUPS", {})

    audit = build_audit(anime, relations)

    assert 70502 not in audit["assignments"]


def test_canonical_series_correction_replaces_an_incorrect_split(monkeypatch):
    anime = {
        70601: _anime("Original", series=["Shared Series"]),
        70602: _anime("Original Next", series=["Original Next"]),
    }
    monkeypatch.setattr(series_audit, "VERIFIED_SERIES_GROUPS", {})
    monkeypatch.setattr(
        series_audit,
        "CANONICAL_SERIES_GROUPS",
        {"Shared Series": (70601, 70602)},
    )

    audit = build_audit(anime, relations={})

    assert 70601 not in audit["assignments"]
    assert audit["assignments"][70602] == ["Shared Series"]


def test_known_series_cleanup_is_preserved_by_future_backfills():
    anime = {
        1854: _anime("Rockman Hoshi ni Negai wo", series=["Ryuusei no Rockman"]),
        6900: _anime("Tamagotchi!", series=["Tamagotchi!"]),
        28401: _anime(
            "Q Transformers: Kaette Kita Convoy no Nazo",
            series=["Q Transformers"],
        ),
        38431: _anime(
            "Persona 5 the Animation TV Specials",
            series=["Persona 5"],
        ),
        51682: _anime(
            "Tomica Heroes Jobraver: Tokusou Gattai Robo",
            series=["Tomica Heroes Jobraver: Tokusou Gattai Robo"],
        ),
        1548: _anime("Shin Taketori Monogatari: 1000-nen Joou", series=[]),
        1549: _anime("1000-nen Joou: Queen Millennia"),
    }

    audit = build_audit(anime, relations={})

    assert audit["assignments"][1854] == ["Rockman"]
    assert audit["assignments"][6900] == ["Tamagotchi"]
    assert audit["assignments"][28401] == ["Q Transformers", "Transformers"]
    assert audit["assignments"][38431] == ["Persona 5", "Persona"]
    assert audit["assignments"][51682] == [
        "Tomica Heroes Jobraver: Tokusou Gattai Robo",
        "Tomica",
    ]
    assert audit["assignments"][1548] == ["Queen Millennia"]
    assert audit["assignments"][1549] == ["Queen Millennia"]
