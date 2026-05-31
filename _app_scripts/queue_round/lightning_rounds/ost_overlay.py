"""OST lightning-round helper — extracts the likely track name from a
YouTube video title by aggressively stripping every word and fragment
that matches the anime's titles/synonyms/series.

Extracted from `guess_the_anime.py`. The OST round itself is driven by
the streaming module (`stream_clip` / `play_random_clip`); this helper
is only used at answer time to surface "what the song was actually
called" when the YouTube source title still contains the track name
after the anime metadata is scrubbed out.

Stateless — no module state, no `set_context` needed.
"""
from __future__ import annotations

import re


def extract_track_name_from_youtube_title(youtube_title, data):
    """
    Extracts the likely track name from a YouTube title by aggressively removing all words from the anime's titles.
    Very stringent to ensure anime title doesn't remain.
    """
    if not youtube_title:
        return ""

    # Collect all possible title variations
    titles_to_remove = []

    # Add main titles
    if data.get("title"):
        titles_to_remove.append(data.get("title"))
    if data.get("eng_title") and data.get("eng_title") != "N/A":
        titles_to_remove.append(data.get("eng_title"))

    # Add synonyms
    if data.get("synonyms"):
        titles_to_remove.extend(data.get("synonyms", []))

    if data.get("series"):
        series = data.get("series")
        if isinstance(series, list):
            titles_to_remove.extend(series)
        else:
            titles_to_remove.append(series)

    # Collect all individual words AND fragments (including punctuation) from all titles
    all_title_words = set()
    all_title_fragments = set()

    for title in titles_to_remove:
        if title and title != "N/A":
            # Split on spaces to get word+punctuation fragments
            fragments = title.lower().split()
            all_title_fragments.update(fragments)

            # Also split on spaces and punctuation to get pure words
            words = re.findall(r'\w+', title.lower())
            all_title_words.update(words)

    result = youtube_title.lower()

    # First pass: Remove exact title matches (case-insensitive)
    for title in titles_to_remove:
        if title and title != "N/A":
            result = re.sub(re.escape(title.lower()), "", result, flags=re.IGNORECASE)

    # Second pass: Remove fragments with punctuation (like "re:", "no.", etc.)
    for fragment in all_title_fragments:
        if fragment:
            # Remove as exact match with word boundaries
            result = re.sub(rf"\b{re.escape(fragment)}\b", "", result, flags=re.IGNORECASE)
            # Also try removing from start/end of string
            if result.startswith(fragment):
                result = result[len(fragment):].lstrip()
            if result.endswith(fragment):
                result = result[:-len(fragment)].rstrip()

    # Third pass: Remove individual words with word boundaries
    for word in all_title_words:
        if len(word) > 2:  # Only remove words longer than 2 characters
            result = re.sub(rf"\b{re.escape(word)}\b", "", result, flags=re.IGNORECASE)

    # Fourth pass: Remove words as substrings (more aggressive)
    for word in all_title_words:
        if len(word) > 3:  # Only do substring removal for words longer than 3 chars
            result = result.replace(word.lower(), "")

    # Remove any remaining title fragments or single characters at the start
    while True:
        old_result = result
        result = result.lstrip(":/-–—|~ ")
        # Remove single letters or short fragments at the start
        result = re.sub(r'^[a-z]{1,2}[\s:]+', '', result, flags=re.IGNORECASE)
        if result == old_result:
            break

    # Remove common OST-related words and separators
    remove_patterns = [
        r'\bost\b', r'\bofficial\b', r'\btheme\b', r'\bsoundtrack\b',
        r'\bopening\b', r'\bending\b', r'\bop\b', r'\bed\b',
        r'\bfull\b', r'\bversion\b', r'\baudio\b', r'\bmusic\b',
        r'\banime\b', r'\bmanga\b', r'\bseries\b', r'\bseason\b',
        r'\bepisode\b', r'\bep\b', r'\bvol\b', r'\bvolume\b',
        r'\boriginal\b', r'\binsert\b', r'\bsong\b', r'\btrack\b',
        r'\bii\b', r'\biii\b', r'\biv\b'  # Roman numerals often from season numbers
    ]

    for pattern in remove_patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    # Remove separators and special characters but keep essential punctuation
    for sep in ["-", "—", "–", "|", "~", "×", "✕", "･", "・"]:
        result = result.replace(sep, " ")

    result = re.sub(r'\([^)]*\)', '', result)
    result = re.sub(r'\[[^\]]*\]', '', result)
    result = re.sub(r'\{[^}]*\}', '', result)

    # Clean up extra spaces
    result = re.sub(r'\s+', ' ', result).strip()

    # Final cleanup: Remove any remaining title fragments from start/end
    for fragment in all_title_fragments:
        if fragment and len(fragment) > 1:
            if result.lower().startswith(fragment):
                result = result[len(fragment):].lstrip(":/-–—|~ ")
            if result.lower().endswith(fragment):
                result = result[:-len(fragment)].rstrip(":/-–—|~ ")

    remaining_words = set(re.findall(r'\w+', result.lower()))
    overlap = remaining_words & all_title_words

    # If more than 30% of remaining words are title words, it's not clean enough
    if remaining_words and len(overlap) / len(remaining_words) > 0.3:
        return ""

    if len(result) < 2:
        return ""

    return result.strip()
