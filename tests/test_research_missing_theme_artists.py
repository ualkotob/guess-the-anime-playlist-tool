from tools.research_missing_theme_artists import (
    missing_artist_inventory,
    parse_theme_section,
)
from _app_scripts.utils import theme_artist_needs_resolution


def test_parse_ending_section_before_reviews_without_episode_videos():
    page = """
    <h2>Opening Theme</h2>
    <div class="theme-songs opening">No opening themes have been added.</div>
    <h2>Ending Theme</h2>
    <div class="theme-songs js-theme-songs ending">
      <table><tr>
        <td width="84%">"Kalinka"<span class="theme-song-artist">
          by Ivan Petrovich Larionov
        </span><input type="hidden" value="" /></td>
      </tr></table>
    </div>
    <br><br><br><br>
    <h2>Reviews</h2>
    """

    assert parse_theme_section(page, "ED") == [
        {
            "index": 1,
            "title": "Kalinka",
            "artist": "Ivan Petrovich Larionov",
            "episodes": "",
            "text": '"Kalinka" by Ivan Petrovich Larionov',
        }
    ]


def test_missing_artist_inventory_includes_reviewed_resolution():
    anime = {
        "1": {
            "title": "Example",
            "songs": [{"slug": "ED1", "type": "ED", "artist": []}],
        }
    }
    file_metadata = {
        "1": {
            "mal": 10,
            "themes": {"ED1": {"v1": {"Example-ED1.webm": {}}}},
        }
    }
    resolutions = {
        "10:ED1": {
            "status": "instrumental_or_score",
            "detail": "Reviewed instrumental cue.",
        }
    }

    rows = missing_artist_inventory(anime, file_metadata, resolutions)

    assert rows[0]["resolution_status"] == "instrumental_or_score"
    assert rows[0]["resolution_detail"] == "Reviewed instrumental cue."


def test_missing_artist_inventory_defaults_new_blank_to_unresolved():
    anime = {"1": {"songs": [{"slug": "OP1", "artist": []}]}}
    file_metadata = {"1": {"themes": {"OP1": {}}}}

    rows = missing_artist_inventory(anime, file_metadata, {})

    assert rows[0]["resolution_status"] == "unresolved"


def test_missing_artist_playlist_ignores_reviewed_intentional_blanks():
    assert not theme_artist_needs_resolution(
        {"artist": []}, "instrumental_or_score"
    )
    assert not theme_artist_needs_resolution(
        {"artist": []}, "no_credited_performer"
    )
    assert theme_artist_needs_resolution({"artist": []}, "unresolved")
    assert theme_artist_needs_resolution({"artist": []})
    assert not theme_artist_needs_resolution({"artist": ["Singer"]})
