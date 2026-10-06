"""Desktop and browser UI exposure for AniSongDB metadata."""

from _app_scripts.file.metadata import metadata_display
from _app_scripts.file.web_server import web_client_html
from _app_scripts.ui import menu_registry


def test_desktop_external_sites_menu_contains_anisongdb():
    external_sites = next(
        item
        for item in menu_registry.get_menu_registry()["theme"]
        if isinstance(item, dict) and item.get("label") == "External Sites"
    )
    anisongdb_item = next(
        item for item in external_sites["submenu"] if item.get("id") == "open_anisongdb"
    )

    assert anisongdb_item["label"] == "AniSongDB"
    assert metadata_display.has_anisongdb_identity({"anisongdb_ann_id": 13}) is True
    assert metadata_display.has_anisongdb_identity({}) is False


def test_web_ui_renders_anisongdb_links_and_multiple_theme_files():
    html = web_client_html.HTML

    assert "label: 'AniSongDB'" in html
    assert "https://anisongdb.com/" in html
    assert "(v.files && v.files.length) ? v.files : [v]" in html
    assert "(theme.files && theme.files.length) ? theme.files : [theme]" in html
