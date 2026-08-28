"""Regression coverage for the web filter editor's shared controls."""

from _app_scripts.file.web_server import web_client_html


def test_filter_picker_suggestions_are_scoped_to_the_focused_picker():
    html = web_client_html.HTML

    assert (
        ".ctrl-filter-picker:focus-within .ctrl-filter-suggestions.active"
        " { display: block; }"
    ) in html
    assert "input.onfocus = () => { _ctrlFilterCloseSuggestions(suggestions); show(); };" in html
    assert "document.addEventListener('pointerdown', ev => {" in html
    assert "_ctrlFilterCloseSuggestions(active);" in html


def test_filter_range_tracks_snap_the_nearest_thumb_to_clicks():
    html = web_client_html.HTML

    assert "track.onpointerdown = ev => _ctrlFilterSliderTrackPointerDown(name, ev);" in html
    assert "const ratio = Math.max(0, Math.min(1, (ev.clientX - bounds.left) / bounds.width));" in html
    assert (
        "const target = Math.abs(value - Number(low.value)) <= "
        "Math.abs(value - Number(high.value)) ? low : high;"
    ) in html
    assert "_ctrlFilterRangeChanged(target);" in html
