"""Regression tests for metadata records without exact air dates."""

from _app_scripts.file.metadata import metadata_fetch


def test_missing_aired_values_are_quiet_fallbacks(capsys):
    assert metadata_fetch.aired_to_season_year(None) == "N/A"
    assert metadata_fetch.aired_to_season_year("N/A") == "N/A"
    assert metadata_fetch.aired_to_season_year("N/A to N/A", start=False) == "N/A"
    assert metadata_fetch.aired_to_season_year("unknown") == "N/A"
    assert metadata_fetch.aired_to_season_year("Not available") == "N/A"
    assert capsys.readouterr().out == ""
