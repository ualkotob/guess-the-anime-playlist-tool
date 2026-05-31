"""Lightning round static configuration.

Pure data + one helper:
  * ``LIGHT_ROUND_LENGTH_DEFAULT`` / ``LIGHT_ROUND_ANSWER_LENGTH_DEFAULT``
    — fallback durations used when a per-mode ``length`` isn't set or when
    a mode hasn't been configured yet.
  * ``light_modes`` — display metadata (icon + description) keyed by mode
    name. Read by the lightning round popup, the settings editor, and the
    web UI to render mode chooser tooltips.
  * ``lightning_mode_settings_default`` — the master settings tree mirrored
    by every saved lightning-mode profile. Each mode entry has ``length``,
    ``muted``, optional ``variants`` / ``character_types``, and a
    ``variety`` sub-tree controlling popularity / cooldown weighting.
  * ``update_lightning_mode_settings`` — migration + sync helper run when
    a saved profile is loaded from config.

This module imports nothing from the runtime (no mpv, no state, no PIL),
so it can be imported cheaply by tooling and fixed-round loaders.
"""
from __future__ import annotations

import _app_scripts.utils as utils


# ---------------------------------------------------------------------------
# Default durations (fallback when a mode's per-profile ``length`` is unset)
# ---------------------------------------------------------------------------
LIGHT_ROUND_LENGTH_DEFAULT        = 12
LIGHT_ROUND_ANSWER_LENGTH_DEFAULT = 8


# ---------------------------------------------------------------------------
# Per-mode display metadata (icon + description)
# ---------------------------------------------------------------------------
light_modes = {
    "blind":{
        "icon":"👁",
        "desc":(
            "Opening/Ending starts at a random point.\n"
            "You will only be able to hear the music."
        )
    },
    "c. name":{
        "icon":"🔤",
        "desc":(
            "You will need to guess the character name as letters are randomly placed in position."
        )
    },
    "c. profile":{
        "icon":"📝",
        "desc":(
            "You will be shown the gender and description of a character over time.\n"
            "Image will be revealed in last few seconds."
        )
    },
    "c. reveal":{
        "icon":"✨",
        "desc":(
            "You will be shown a character, revealed over time."
        )
    },
    "characters":{
        "icon":"👤",
        "desc":(
            "You will be shown 4 characters revealed over time."
        )
    },
    "clip":{
        "icon":"🎬",
        "desc":(
            "You will be shown a random clip or trailer."
        )
    },
    "clues":{
        "icon":"🔍",
        "desc":(
            "You will be shown various stats."
        )
    },
    "cover":{
        "icon":"📚",
        "desc":(
            "You will be shown the cover of the anime, revealed over time."
        )
    },
    "emoji":{
        "icon":"😄",
        "desc":(
            "You are shown 6 emojis over time."
        )
    },
    "episodes":{
        "icon":"📺",
        "desc":(
            "You will be shown 6 episode titles.\n"
            "They will be revealed over time."
        )
    },
    "frame":{
        "icon":"📷",
        "desc":(
            "You will be shown 4 different frames from the Opening/Ending.\n"
            "Each frame will be shown one at a time."
        )
    },
    "image":{
        "icon":"🌐",
        "desc":(
            "You will be shown a random image, revealed over time."
        )
    },
    "names":{
        "icon":"🎭",
        "desc":(
            "You will be shown 6 character names.\n"
            "They will be revealed over time."
        )
    },
    "ost":{
        "icon":"💿",
        "desc":(
            "You hear part of the anime's OST."
        )
    },
    "reveal":{
        "icon":"👀",
        "desc":(
            "Opening/Ending starts at a random point muted.\n"
            "Only a small part of the screen is shown, and grows or moves over time."
        )
    },
    "regular":{
        "icon":"🗲",
        "desc":(
            "Opening/Ending starts at a random point."
        )
    },
    "song":{
        "icon":"🎵",
        "desc":(
            "You will be shown song information for the Opening/Ending.\n"
            "It will be revealed over time, and the song plays the last few seconds."
        )
    },
    "synopsis":{
        "icon":"📰",
        "desc":(
            "You will be shown a part of the synopsis.\n"
            "It will be revealed word by word over time."
        )
    },
    "tags":{
        "icon":"🔖",
        "desc":(
            "You will be show detailed tags revealed over time."
        )
    },
    "title":{
        "icon":"𝕋",
        "desc":(
            "You will need to guess the title as letters are randomly placed in position."
        )
    },
    "trivia":{
        "icon":"❓",
        "desc":(
            "You will be asked a trivia question about an anime.\n"
            "It will be revealed word by word over time."
        )
    },
    "variety":{
        "icon":"🎲",
        "desc":(
            "Plays a dynamic mix of lightning rounds based on popularity."
        )
    }
}


# ---------------------------------------------------------------------------
# Master settings tree mirrored by every saved lightning-mode profile.
# ---------------------------------------------------------------------------
lightning_mode_settings_default = {
    "variety": {
        "popularity_limit": True,
        "series_mode_limit": True,
        "mode_weight": True,
        "mode_cooldowns": True
    },
    "_misc_settings": {
        "answer_length": 8,
        "image_width_percent": 70,
        "download_cache_mb": 100,
        "always_download_clip": True,
        "framed_video": False,
        "framed_video_clip": True,
        "background_music": {
            "rounds_per_track": 3,
            "random_start": False,
            "hide_display_during_reveal": False
        }
    },
    "blind": {
        "length": 12,
        "muted": False,
        "variants": {
            "standard": True,
            "double_speed": True,
            "mismatch": True,
            "one_second": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1500],
                "weight":  {
                    "op":10,
                    "ed":3
                }
            },
            "cooldown": {
                "min_gap": 2,
                "max_gap": 7,
                "popularity_force_threshold": {
                    "op":750,
                    "ed":500
                },
                "no_repeat_limit": 0
            }
        }
    },
    "c. name": {
        "length": 20,
        "muted": True,
        "character_types": {
            "main": True,
            "secondary": False,
            "appears": False,
            "popularity_limit": True
        },
        "variety": {
            "enabled": False,
            "popularity": {
                "range": [0, 750],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 250,
                "no_repeat_limit": 40
            }
        }
    },
    "c. profile": {
        "length": 20,
        "muted": True,
        "character_types": {
            "main": True,
            "secondary": True,
            "appears": False,
            "popularity_limit": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 250],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 30,
                "popularity_force_threshold": 750,
                "no_repeat_limit": 40
            }
        }
    },
    "c. reveal": {
        "length": 20,
        "muted": True,
        "variants": {
            "standard": False,
            "blur": True,
            "parts": True,
            "pixel": True,
            "slice": True,
            "slide": True,
            "swap": True,
            "tile": True,
            "zoom": True
        },
        "character_types": {
            "main": True,
            "secondary": True,
            "appears": False,
            "popularity_limit": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 750],
                "weight": 30
            },
            "cooldown": {
                "min_gap": 5,
                "max_gap": 10,
                "popularity_force_threshold": 750,
                "no_repeat_limit": 40
            }
        }
    },
    "characters": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 2,
                "max_gap": 7,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 80
            }
        }
    },
    "clues": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 20,
                "popularity_force_threshold": 250,
                "no_repeat_limit": 40
            }
        }
    },
    "clip": {
        "length": 12,
        "muted": True,
        "variants": {
            "random_clip": True,
            "trailer": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 3,
                "max_gap": 8,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 80
            }
        }
    },
    "cover": {
        "length": 20,
        "muted": True,
        "variants": {
            "standard": False,
            "blur": True,
            "pixel": True,
            "slice": True,
            "slide": True,
            "swap": True,
            "tile": True,
            "zoom": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 5,
                "max_gap": 15,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 80
            }
        }
    },
    "image": {
        "length": 20,
        "muted": True,
        "variants": {
            "standard": False,
            "blur": True,
            "pixel": True,
            "slice": True,
            "slide": True,
            "swap": True,
            "tile": True,
            "zoom": True
        },
        "variety": {
            "enabled": False,
            "popularity": {
                "range": [0, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 5,
                "max_gap": 25,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 80
            }
        }
    },
    "emoji": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 30,
                "popularity_force_threshold": 100,
                "no_repeat_limit": 40
            }
        }
    },
    "episodes": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1000],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 500,
                "no_repeat_limit": 40
            }
        }
    },
    "frame": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 3000],
                "weight": {
                    "op":10,
                    "ed":5
                }
            },
            "cooldown": {
                "min_gap": 4,
                "max_gap": 20,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 0
            }
        }
    },
    "names": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1000],
                "weight": 5
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 500,
                "no_repeat_limit": 40
            }
        }
    },
    "ost": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 250],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 25,
                "popularity_force_threshold": 100,
                "no_repeat_limit": 40
            }
        }
    },
    "reveal": {
        "length": 20,
        "muted": True,
        "variants": {
            "blur": True,
            "edge": True,
            "grow": True,
            "outline": False,
            "pixelize": True,
            "slice": True,
            "wave": False,
            "zoom": True
        },
        "show_in_menu": {
            "blur": True,
            "edge": True,
            "grow": True,
            "outline": False,
            "pixelize": True,
            "slice": True,
            "wave": False,
            "zoom": True
        },
        "blur_censor_percent": 40,
        "pixelize_censor_percent": 40,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 3000],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 3,
                "max_gap": 10,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 0
            }
        }
    },
    "regular": {
        "length": 12,
        "muted": False,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [250, 0],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 0,
                "max_gap": 0,
                "popularity_force_threshold": 0,
                "no_repeat_limit": 0
            }
        }
    },
    "song": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 250],
                "weight": {
                    "op":10,
                    "ed":3
                }
            },
            "cooldown": {
                "min_gap": 10,
                "max_gap": 25,
                "popularity_force_threshold": {
                    "op":100,
                    "ed":50
                },
                "no_repeat_limit": 40
            }
        }
    },
    "synopsis": {
        "length": 20,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [50, 1500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 4,
                "max_gap": 10,
                "popularity_force_threshold": 1000,
                "no_repeat_limit": 80
            }
        }
    },
    "tags": {
        "length": 20,
        "muted": True,
        "use_anilist_tags": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 750],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 25,
                "max_gap": 50,
                "popularity_force_threshold": 500,
                "no_repeat_limit": 40
            }
        }
    },
    "title": {
        "length": 20,
        "muted": True,
        "variants": {
            "reveal": True,
            "scramble": True,
            "swap": True
        },
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1500],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 4,
                "max_gap": 6,
                "popularity_force_threshold": 1000,
                "no_repeat_limit": 80
            }
        }
    },
    "trivia": {
        "length": 12,
        "muted": True,
        "variety": {
            "enabled": True,
            "popularity": {
                "range": [0, 1000],
                "weight": 10
            },
            "cooldown": {
                "min_gap": 7,
                "max_gap": 15,
                "popularity_force_threshold": 1000,
                "no_repeat_limit": 40
            }
        }
    }
}


# ---------------------------------------------------------------------------
# Profile migration / sync helper
# ---------------------------------------------------------------------------
def update_lightning_mode_settings(settings):
    # Migrate old 'peek' key to 'reveal' for backward compatibility
    if "peek" in settings and "reveal" not in settings:
        settings["reveal"] = settings.pop("peek")
    settings = utils.sync_with_default(settings, lightning_mode_settings_default)
    return dict(sorted(settings.items()))
