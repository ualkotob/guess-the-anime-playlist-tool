"""Shared character-roster cleanup for character-based lightning rounds."""
from __future__ import annotations

import re
import unicodedata


_ROLE_PRIORITY = {"m": 0, "s": 1, "a": 2}


def normalize_character_name(name):
    """Return a conservative key for exact-name duplicate detection."""
    normalized = unicodedata.normalize("NFKC", str(name or ""))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def dedupe_characters_by_name(characters):
    """Keep one entry per name, preferring main, secondary, then appears."""
    selected = {}
    order = []
    for character in characters or []:
        if len(character) < 2:
            continue
        name_key = normalize_character_name(character[1])
        if not name_key:
            continue
        if name_key not in selected:
            selected[name_key] = character
            order.append(name_key)
            continue

        current = selected[name_key]
        current_role = current[0] if current else ""
        candidate_role = character[0] if character else ""
        if _ROLE_PRIORITY.get(candidate_role, 99) < _ROLE_PRIORITY.get(
            current_role, 99
        ):
            selected[name_key] = character

    return [selected[name_key] for name_key in order]
