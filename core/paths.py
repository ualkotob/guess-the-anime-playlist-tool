"""Centralized file and folder path constants for the Guess the Anime app.

All paths are relative to the application root directory. The main entry point
(`guess_the_anime.py`) performs `os.chdir(...)` to that directory at startup,
so relative paths resolve correctly throughout the running process.

`_app_scripts/*` modules that need to work independently of cwd build their
own absolute paths via `_ROOT_DIR` and receive paths from the main file via
their `set_context()` / `update_settings()` calls — they intentionally do not
import from this module to keep them loosely coupled.
"""

# --- Metadata files ---------------------------------------------------------
FILE_METADATA_FILE            = "metadata/file_metadata.json"
FILE_METADATA_OVERRIDES_FILE  = "metadata/file_metadata_overrides.json"
ANIME_METADATA_FILE           = "metadata/anime_metadata.json"
ANIDB_METADATA_FILE           = "metadata/anidb_metadata.json"
AI_METADATA_FILE              = "metadata/ai_metadata.json"
ANIME_METADATA_OVERRIDES_FILE = "metadata/anime_metadata_overrides.json"
MANUAL_METADATA_FILE          = "metadata/manual_metadata.json"
YOUTUBE_METADATA_FILE         = "metadata/youtube_metadata.json"
ANILIST_METADATA_FILE         = "metadata/anilist_metadata.json"

# --- Config -----------------------------------------------------------------
CONFIG_FOLDER = "config"
CONFIG_FILE   = "config/config.json"

# --- Content folders --------------------------------------------------------
CENSORS_FOLDER             = "censors"
CENSOR_JSON_FILE           = "censors/censors.json"
RULES_FOLDER               = "rules"
LIGHTNING_SETTINGS_FOLDER  = "lightning_settings"
INFINITE_SETTINGS_FOLDER   = "infinite_settings"
BONUS_SETTINGS_FOLDER      = "bonus_settings"
POPOUT_LAYOUTS_FOLDER      = "popout_layouts"
YOUTUBE_FOLDER             = "youtube"
YOUTUBE_CACHE_FOLDER       = "youtube/cache"
PLAYLISTS_FOLDER           = "playlists/"  # trailing slash preserved for back-compat
FILTERS_FOLDER             = "filters"
THEMES_CACHE_FOLDER        = "themes_cache"
CACHE_METADATA_FILE        = "themes_cache/cache_metadata.json"
