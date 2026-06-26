"""Application identity constants.

Lowest-layer module (no imports) holding the app version and GitHub repo slug
so any module can read them directly. Bump APP_VERSION when cutting a release.
"""

APP_VERSION = "19.8"  # Update this when making releases
GITHUB_REPO = "ualkotob/guess-the-anime-playlist-tool"
WINDOW_TITLE = f"Guess the Anime! Playlist Tool v{APP_VERSION}"
