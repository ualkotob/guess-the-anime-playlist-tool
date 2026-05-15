import tkinter as tk

# ── Module-level window reference ─────────────────────────────────────────────
_tutorial_window = None

# ── Tutorial content ──────────────────────────────────────────────────────────
# Structure: list of section dicts, each with:
#   "title"   – display name
#   "icon"    – emoji shown left of title (optional)
#   "content" – list of (tag, value) tuples rendered in the content pane
#   "subs"    – list of child section dicts (same structure, recursive)
#
# Content tags:
#   ("h1",  "Title text")          – large bold underlined heading
#   ("h2",  "Subtitle text")       – medium bold underlined subheading
#   ("p",   "Body text")           – normal paragraph
#   ("b",   "Bold text")           – bold inline line
#   ("ul",  ["item", ...])         – bulleted list
#   ("tip", "Tip text")            – highlighted callout box
#   ("sep",)                       – vertical whitespace separator

TUTORIAL_CONTENT = [
    {
        "title": "Welcome & Start", "icon": "👋",
            "content": [
                ("h1",  "Welcome to the Guess The Anime Playlist Tool!"),
                ("p",   "This tool lets you run and create anime opening/ending theme guessing games/quizzes. "
                        "It has lots of functionality, and is honestly quite bloated with features. "
                        "I'll try my best to explain them all in this tutorial."),
                ("tip", "All menu options have tooltips explaining their function."),
                ("tip", "This tutorial is a work in progress(10% I'd say so far), and will be expanded over time to cover all features."
                        "If you stumble across this program and have questions, you can reach out on GitHub or Discord (Ramun_Flame)."),
            ],
        "subs": [
            {
                "title": "About This Tutorial",
                "content": [
                    ("h1",  "About This Tutorial"),
                    ("p",   "I went back and forth about how to best structure this tutorial. "
                            "I felt the best course of action was to just have it follow the same strucuture as the menus. "
                            "So if you want to learn about a specific feature, you can just find the relevant section in the tutorial that matches the menu structure. "
                            "It's not meant for you to read every page before starting. Go to the First Steps section to get up and running, "
                            "and then refer back to other sections as you explore the features of the program.")
                ],
            },
            {
                "title": "Requirements",
                "content": [
                    ("h1",  "Requirements"),
                    ("p",   "This tool is designed to run on Windows 10 or later. "
                            "It may work on other platforms but I haven't tested it."),
                    ("ul",  [
                        "(Optional) FFMPEG installed and added to PATH for youtube video downloading and file editing.",
                        "(Optional) Cloudflare or ngrok for using the Web Server (Players join online)."
                    ]),
                ],
            },
            {
                "title": "First Steps",
                "content": [
                    ("h1",  "First Steps"),
                    ("p",   "This program supports playing local downloaded themes, and streaming/downloading themes from animethemes.moe. "
                            "If you do not have local files, you can ignore the steps for local files and metadata fetching. Skip directly to playlist creation."),
                    ("h2",  "Overview to get started quick"),
                    ("ul",  [
                        "(If Local Files)Select the folder you keep your themes in from FILE → Choose Theme Directory. Subfolders are searched as well.",
                        "If you didn't import metadata on start up, go to FILE → Import → Import Data (from GitHub) to get the latest metadata.",
                        "Create an Infinite playlist using PLAYLIST → Create Playlist → Infinite. Include streaming themes if you do not have local files.",
                        "You can now play themes freely. Use INFORMATION → Info Popup to show the detail for the current theme.",
                        "If you want to trigger special rounds, you can use the QUEUE ROUND menu.",
                        "If you have two screens, and want bigger, more customizable controls, use the POPOUT menu to open/configure the Popout controls.",
                        "If you prefer keyboard shortcuts, use the TOGGLES → Enable Shortcuts / Edit/View Shortcuts to enable and configure/view them.",
                        "Feel free to explore menu options, and discover functionality."
                    ]),
                    ("tip", "The above steps are just a quick way to get started. The rest of the tutorial will go in depth on all features, and how to use them effectively.")
                ],
            },
        ],
    },
    {
        "title": "Metadata & Import",
        "content": [
            ("h1",  "Metadata & Import"),
            ("p",   "Metadata provides full informaiton for each theme, like full titles, song names, etc. "
                    "Without metadata, the app can only show file names, and some features are unavailable."),
            ("h2",  "Importing Metadata"),
            ("ul",  [
                "Upon first launch and when it's updated, you should be prompted to import metadata from GitHub on startup.",
                "If you want to trigger this manually you can use FILE → Import → Import Data (from GitHub).",
                "This data provides animethemes files with their data, and is also required to be able to stream/download themes."
            ]),
            ("h2",  "Metadata Sources"),
            ("ul",  [
                "Metadata is from animethemes, myanimelist, anilist, and anidb.",
                "animethemes: Song Name and Artist information.",
                "myanimelist: Basic anime information, cover, trailer, members, and score.",
                "anilist: Members, score, ranks, character, and tag information.",
                "anidb: Episodes, characters, and tags."
            ]),
        ],
        "subs": [
            {
                "title": "Fetching Metadata",
                "content": [
                    ("h1",  "Fetching Metadata"),
                    ("p",   "If you do not import metadata from GitHub, or have files not included in the imported "
                            "data you can fetch it in the program as long as the file is named properly. When playing a file, "
                            "you can use THEME → Fetch Theme Data to grab metadata for that theme. It must follow the rules below to succeed."),
                    ("h2",  "Files from animethemes.moe"),
                    ("ul",  [
                        "These files are compatible without any further changes, as long as you do not change the filename from how it was when downloaded."
                    ]),
                    ("h2",  "Files not from animethemes.moe, but have entries on myanimelist",),
                    ("ul",  [
                        "Name these following the following format:",
                        "AnimeTitle-OP1-[MAL]123[ART]Artist Name[SNG]Song Name.webm",
                        "The AnimeTitle can be anything, and doesn't matter.",
                        "The slug after bust be OP or ED, and a number.",
                        "If it's a special theme, you can use an udnerscore after the number(OP1_EN).",
                        "You can also add version numbers, like OP1v2.",
                        "The [MAL] tag is required, and is the ID from the url on the anime's myanimelist page.",
                        "For example, for https://myanimelist.net/anime/12345/Example_Anime, the MAL ID is 12345.",
                        "The [ART] and [SNG] tags are for the theme's artist and song name. These are optional, but recommended to add."
                        "Anidb and Anilist data is fetched based on the MAL ID, but [ADB] and [ALT] tags can be added if it's not fetching the correct data.",
                    ]),
                    ("h2",  "Game Themes"),
                    ("ul",  [
                        "Game themes that are on igdb.com can be added using the same format above.",
                        "Just replace the [MAL] tag with [IGDB], and put the game's IGDB ID there instead.",
                        "GameTitle-OP1-[IGDB]123[ART]Artist Name[SNG]Song Name.webm",
                        "This Id is not in the url of the igdb page, but on the right side of the page."
                    ]),
                    ("h2",  "Other Themes"),
                    ("ul",  [
                        "Anything that doesn't meet the above requirements can only get metadata if manually provided.",
                        "You need to create a manual_metadata.json file in the metadata folder, and add entries for each file there.",
                        "This would follow the same format as the anime_metadata file, so you can just copy paste an entry from there and fill it out.",
                        "The entry's ID(top level label, uaually the MAL id, with a unique ID of your choosing, that should use letters to avoid duplicating MAL ids.)",
                        "The name the file with the ID tagged, like the following.",
                        "ThemeTitle-OP1-[ID]UniqueID.webm",
                        "This Id is not in the url of the source page, but on the right side of the page."
                    ]),
                    ("sep",),
                    ("tip", "Although all the examples use .webm, that is not required and other formats can be used."),
                ],
            },
        ]
    },
    {
        "title": "FILE [🛠]", "icon": "📁",
        "content": [
            ("h1", "FILE [🛠]"),
            ("p", "[WORK IN PROGRESS] File management, metadata import/export, web server, scoreboard, and app settings."),
        ],
        "subs": [
            {
                "title": "Choose Theme Directory [🛠]",
                "content": [
                    ("h1", "Choose Theme Directory [🛠]"),
                    ("p", "[WORK IN PROGRESS] Choose the folder where your anime themes are stored.\n\n"
                          "The app expects files from AnimeThemes (torrent or downloaded). "
                          "It searches subfolders, so pick the top-level folder.\n\n"
                          "Custom files must be labeled as:\n"
                          "AnimeName-OP1-[MAL]49618[ART]Minami[SNG]Rude Lose Dance.webm"),
                ],
            },
            {
                "title": "Import [🛠]",
                "content": [
                    ("h1", "Import [🛠]"),
                    ("p", "[WORK IN PROGRESS] Import metadata or censors from GitHub."),
                ],
                "subs": [
                    {
                        "title": "Import Data (from GitHub) [🛠]",
                        "content": [
                            ("h1", "Import Data (from GitHub) [🛠]"),
                            ("p", "[WORK IN PROGRESS] Imports metadata from a remote GitHub. "
                                 "Downloads a zip package and merges all metadata with your existing data."),
                        ],
                    },
                    {
                        "title": "Import Censors (Ramun's) [🛠]",
                        "content": [
                            ("h1", "Import Censors (Ramun's) [🛠]"),
                            ("p", "[WORK IN PROGRESS] Downloads and imports Ramun's censors from GitHub. "
                                 "Saved as 'ramuns_censors.json' in your files folder."),
                        ],
                    },
                ],
            },
            {
                "title": "Export Data [🛠]",
                "content": [
                    ("h1", "Export Data [🛠]"),
                    ("p", "[WORK IN PROGRESS] Exports all metadata files into a zip package for backup or sharing."),
                ],
            },
            {
                "title": "Fetch All Missing Metadata [🛠]",
                "content": [
                    ("h1", "Fetch All Missing Metadata [🛠]"),
                    ("p", "[WORK IN PROGRESS] Check all files in the directory for missing metadata and fetch any that are absent."),
                ],
            },
            {
                "title": "Refresh Metadata [🛠]",
                "content": [
                    ("h1", "Refresh Metadata [🛠]"),
                    ("p", "[WORK IN PROGRESS] Refresh metadata from external sources."),
                ],
                "subs": [
                    {
                        "title": "Refresh Jikan (MAL) [🛠]",
                        "content": [
                            ("h1", "Refresh Jikan (MAL) [🛠]"),
                            ("p", "[WORK IN PROGRESS] Refresh Jikan (MAL) metadata — score and members — for files in your directory."),
                        ],
                    },
                    {
                        "title": "Refresh AniList [🛠]",
                        "content": [
                            ("h1", "Refresh AniList [🛠]"),
                            ("p", "[WORK IN PROGRESS] Refresh AniList metadata — scores, rankings, tags, characters — for files in your directory."),
                        ],
                    },
                    {
                        "title": "Refresh IGDB [🛠]",
                        "content": [
                            ("h1", "Refresh IGDB [🛠]"),
                            ("p", "[WORK IN PROGRESS] Refresh IGDB metadata for game files in your directory."),
                        ],
                    },
                ],
            },
            {
                "title": "Web Server [🛠]",
                "content": [
                    ("h1", "Web Server [🛠]"),
                    ("p", "[WORK IN PROGRESS] Start or stop the web answer server that lets players submit bonus answers from their browser."),
                ],
            },
            {
                "title": "Scoreboard [🛠]",
                "content": [
                    ("h1", "Scoreboard [🛠]"),
                    ("p", "[WORK IN PROGRESS] Launch, close, update, or control the Universal Scoreboard — a companion overlay for tracking scores during sessions."),
                ],
            },
            {
                "title": "Reset Session History [🛠]",
                "content": [
                    ("h1", "Reset Session History [🛠]"),
                    ("p", "[WORK IN PROGRESS] Clear the current session history. Starts a fresh session from this point."),
                ],
            },
            {
                "title": "Configuration Settings [🛠]",
                "content": [
                    ("h1", "Configuration Settings [🛠]"),
                    ("p", "[WORK IN PROGRESS] Open settings to configure volume, colors, API keys, scaling, and more."),
                ],
            },
        ],
    },
    {
        "title": "PLAYLIST", "icon": "🎵",
        "content": [
            ("h1",  "Playlists"),
            ("p",   "Playlists hold themes, and are required to use the functions of this program. "
                "When you create a playlist it is stored in the config file. The currently loaded playlist is always "
                "saved in the config file until another playlist is loaded. When you save a playlist, it creates a "
                "playlist file in the playlists folder. This will only contain the playlist in the state it was saved in, "
                "and will not be updated as you make changes to the currently loaded playlist. It must be saved to reflect "
                "those changes. There are a few playlist types, but the metadata, and file distribution is designed to be used "
                "in an Infinite Playlist so I recommend to start there."),
        ],
        "subs": [
            {
                "title": "Create Playlist",
                "content": [
                    ("h1",  "Create Playlist"),
                    ("p",   "Use this to create a new playlist. Each playlist type is explained in the sections below."),
                ],
                "subs": [
                    {
                        "title": "Infinite",
                        "content": [
                            ("h1",  "Infinite Playlist"),
                            ("p",   "The Infinite playlist starts with one theme, and as you play it, it adds themes to the end infinitely. "
                                    "While it does this, it takes into account popularity and release dates of anime to make sure the playlist has an "
                                    "even balance."),
                            ("ul",  [
                                "Click PLAYLIST → Create Playlist → Infinite",
                                "Choose Local Files Only or Include Streaming Themes",
                                "Set the Difficulty Mode in the PLAYLIST menu.",
                                "By default, new infinite playlists have recommended filters enabled. See the Filters section for more info."
                            ]),
                            ("h2",  "Difficulty Modes"),
                            ("p",   "Difficulty modes are an easy way to switch between showing popular or more obscure themes. "
                                    "Different modes toggle which popularity groups are included. The default for each group is as follows:\n"
                                    "Easy: Popularity 1-250\n"
                                    "Medium: Popularity 251-1000\n"
                                    "Hard: Popularity 1001 and above\n"
                                    "These can be customized in the configuration settings. These are the mode options."),
                            ("ul",  [
                                "Mode: Very Easy — Includes only Easy themes.",
                                "Mode: Easy — Includes Easy and Medium themes.",
                                "Mode: Normal — Includes Easy, Medium, and Hard themes.",
                                "Mode: Hard — Includes Medium and Hard themes.",
                                "Mode: Very Hard — Includes only Hard themes.",
                                "Mode: Random — Includes themes from all difficulty levels, and disables release and popularity balancing for a more chaotic order..",
                            ]),
                            ("h2",  "Infinite Playlist Settings"),
                            ("p",   "Under PLAYLIST → Infinite Settings you can edit specific infinite settings, and save and load templates. Here are the options:"),
                            ("ul",  [
                                "max_history_check: This is how far back in the playlist it will check to boost less played themes. Setting this higher can cause it to run slower.",
                                "difficulty_groups: You can edit the parameters of each difficulty group.",
                                "difficulty_groups > range: Set the minimum and max popularity of the group. Use 'inf' for the max value.",
                                "difficulty_groups > cooldown: Set modifiers for how often themes from this group can show up. It's basedon number of themes in the group, additionally multiplied by this modifier. The first value is how often a series can appear, and the second is how often an individual theme can appear.",
                                "difficulty_groups > file_boost_limit: How much a file can be boosted by being unplayed for awhile.",
                                "ending_limit_ratio: Limits the ratio of ending themes to opening themes. 0.5 will not let it exceed 50 percent ending themes. Set to 1 to disable.",
                                "recent_boost_multiplier: This boosts themes from the last 3 seasons, making them more likely to appear and reducing cooldowns. [0] is the most recent season, [1] is the second most recent, and so on.",
                                "favorites_boost_multiplier: This boosts themes from anime marked as favorites more likely to appear and reducing cooldowns. Set to 1 to disable.",
                                "score_boost: This boosts themes based on their score, making higher scored themes more likely to appear. The boost is based on how much higher the score is from the min_score. Set multiplier to 0 to disable.",
                                "group_series: This causes themes from the same series(Like Dr. Stone Season 4, and Season 1), to appear in the same difficulty groups. This causes themes from lower popularities to appear in easier difficulties if they are from the same series as a popular theme. When disabled, themes from later seasons play less if not the same popularity.",
                                "tag_cooldown: This adds a cooldown to themes with the same tag. For example, if you set it to 3, after playing a theme with the 'mecha' tag, it won't play another theme with the 'mecha' tag for at least 3 more themes. Set to 0 to disable.",
                                "include_non_local_files: This setting allows you to include themes that are not downloaded on your computer, but are available to stream from AnimeThemes.moe. These themes will be marked with a streaming tag in the playlist.",
                                "deduplicate_files: This setting deduplicates files with multiple formats, so you don't play the 480p version of a theme if a 720p version exists.",
                                "deduplicate_versions: This will deduplicate different versions for themes, picking the one with the best format, or just the first one if they are the same. Versions are on the same cooldown as each other, so even when it's disabled a different version of a theme won't appear until its file cooldown is up.",
                                "preload_track_count: This controls how many tracks are preloaded ahead. This is mostly useful if you are streaming themes, and should probably not be edited. The preloaded themes don't appear in the playlist, and are fetched in the background."
                            ]),
                            ("sep",),
                            ("h2",  "Detailed Explanation of Infinite Logic"),
                            ("p",   "If you're curious, here's a detailed explanation of the balance/logic of infinite playlists. Basically, it first splits the themes into "
                                    "different difficulty groups as listed above. then each group is split into 3 even groups by release date. On Normal mode, this results in "
                                    "9 groups of themes(Easy Old, Easy Mid, Easy New, Medium Old, Medium Mid, Medium New, Hard Old, Hard Mid, Hard New). A pattern is randomly created "
                                    "that ensures every three themes in a pattern will include an Easy, Medium, and Hard theme, as well as an Old, Mid, and New theme. An example would be "
                                    "(Hard New, Medium Mid, Easy Old, Easy Mid, Medium New, Hard Old, Medium Old, Easy New, Hard Mid)"
                                    "This ensures a balance of themes so you don't have to wait too long to get a theme from every category. The in the above section details other boosts/filter that affect the themes played."),
                        ],
                    },
                    {
                        "title": "Standard (all files)",
                        "content": [
                            ("h1",  "Standard Playlist"),
                            ("p",   "Creates a flat playlist from all files in your directory/metadata. "
                                    "This is just a standard playlistas you'd expect, and doesn't need extra explanations "
                                    "like the infinite playlist. Themes are in the order they are found in the directory/metadata."),
                            ("ul",  [
                                "Click PLAYLIST → Create Playlist → Standard",
                                "Choose Local Files Only or Include Streaming Themes",
                                "Supports shuffle, filtering, and manual reordering",
                            ]),
                            ("h2",  "Sort"),
                            ("p",   "You can sort the playlist by various criteria such as title, season, etc."),
                            ("ul",  [
                                "Click PLAYLIST → Sort → Criteria → Ascending or Descending",
                            ]),
                            ("h2",  "Shuffle"),
                            ("p",   "Shuffling randomizes the order of themes in the playlist. The two types are Random and Weighted."),
                            ("ul",  [
                                "Click PLAYLIST → Shuffle → Type",
                                "Random Shuffle — Completely random order.",
                                "Weighted Shuffle — Balances popularity, season, and series to create a balanced playlist."
                                "Similar to the logic of Infinite playlist,but is limited based on the distribution of the files.",
                            ]),
                            ("sep",),
                            ("tip", "Even a streamable theme is added to a playlist, it will stream regardless of the option picked at playlist creation. "
                                    "The option only determines if streamable themes are included initially on creation."),
                        ],
                    },
                    {
                        "title": "From AniList",
                        "content": [
                            ("h1",  "AniList & AnimeThemes Playlists"),
                            ("p",   "Generate a playlist directly from an AniList user's anime list. "
                                    "Has the same options as a Standard playlist."),
                            ("ul",  [
                                "PLAYLIST → Create Playlist → From AniList ID",
                                "Choose Local Files Only or Include Streaming Themes",
                                "You will need to provide the AniList username.",
                                "You can choose to include only complete anime, or all in their list.",
                                "You also can decide if you want this playlist to auto update on startup. "
                                "If enabled, it will fetch their list on startup and update the playlist with any new anime or changes to their list. "
                                "This will overwrite any changes you've made to the playlist, including shuffling or reordering.",
                            ]),
                        ],
                    },
                    {
                        "title": "From AnimeThemes Playlists",
                        "content": [
                            ("h1",  "AnimeThemes Playlists"),
                            ("p",   "Generate a playlist directly from an AnimeThemes playlist. "
                                    "Has the same options as a Standard playlist."),
                            ("ul",  [
                                "PLAYLIST → Create Playlist → From AnimeThemes Playlist",
                                "Choose Local Files Only or Include Streaming Themes",
                                "You will need to provide the AnimeThemes playlist ID.",
                                "You also can decide if you want this playlist to auto update on startup. "
                                "If enabled, it will fetch their list on startup and update the playlist with any new anime or changes to their list. "
                                "This will overwrite any changes you've made to the playlist, including shuffling or reordering.",
                            ]),
                        ],
                    },
                    {
                        "title": "From Session Log",
                        "content": [
                            ("h1",  "From Session Log"),
                            ("p",   "Generate a playlist directly from a session log. Will match the themes played in the log, if possible, and mark "
                                    "themes played in lightning rounds accordningly. It cannot replay the lightning rounds the same as the log specifies, "
                                    "it's just to make clear which themes were played as lightning rounds. If played normally, the mark will be removed."
                                    "Has the same options as a Standard playlist."),
                            ("ul",  [
                                "PLAYLIST → Create Playlist → From Session Log",
                                "You will need to provide the session log file."
                            ]),
                        ],
                    },
                    {
                        "title": "Empty Playlist",
                        "content": [
                            ("h1",  "Empty Playlist"),
                            ("p",   "Creates an empty playlist that you can add themes to manually. "
                                    "This is useful if you want to create a custom playlist with specific themes."),
                            ("ul",  [
                                "Click PLAYLIST → Create Playlist → Empty",
                            ]),
                        ],
                    },
                ],
            },
            {
                "title": "View Playlist [🛠]",
                "content": [
                    ("h1", "View Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes in the playlist. Scrolls to the current index. Select a theme to jump to it immediately."),
                ],
            },
            {
                "title": "Go to Index [🛠]",
                "content": [
                    ("h1", "Go to Index [🛠]"),
                    ("p", "[WORK IN PROGRESS] Jump to a specific track number in the playlist. Only available for non-infinite playlists."),
                ],
            },
            {
                "title": "Remove Theme [🛠]",
                "content": [
                    ("h1", "Remove Theme [🛠]"),
                    ("p", "[WORK IN PROGRESS] Remove a theme from the playlist. There is a confirmation dialogue after selecting."),
                ],
            },
            {
                "title": "Save Playlist [🛠]",
                "content": [
                    ("h1", "Save Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Save the current playlist to its existing file in the playlists/ folder. "
                         "The current index is also saved so you can resume where you left off."),
                ],
            },
            {
                "title": "Save Playlist As [🛠]",
                "content": [
                    ("h1", "Save Playlist As [🛠]"),
                    ("p", "[WORK IN PROGRESS] Save the current playlist under a new name. "
                         "You will be prompted for a name. Entering an existing name will overwrite it. "
                         "The current index is also saved so you can resume where you left off."),
                ],
            },
            {
                "title": "Load Playlist [🛠]",
                "content": [
                    ("h1", "Load Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Load a saved playlist. Won't interrupt the currently playing theme."),
                ],
            },
            {
                "title": "Load System Playlist [🛠]",
                "content": [
                    ("h1", "Load System Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Load a system playlist: Tagged, Favorite, Blind, Reveal, Mute Reveal, New, or Missing Artists."),
                ],
            },
            {
                "title": "Merge Playlist [🛠]",
                "content": [
                    ("h1", "Merge Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Merge another playlist into the current one. "
                         "Only non-infinite playlists are listed. Duplicates are skipped."),
                ],
            },
            {
                "title": "Delete a Playlist [🛠]",
                "content": [
                    ("h1", "Delete a Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Select a playlist from the list to delete. You will be asked to confirm."),
                ],
            },
            {
                "title": "Filter Playlist [🛠]",
                "content": [
                    ("h1", "Filter Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Create, apply, save, and delete playlist filters."),
                ],
                "subs": [
                    {
                        "title": "Open Filter Editor [🛠]",
                        "content": [
                            ("h1", "Open Filter Editor [🛠]"),
                            ("p", "[WORK IN PROGRESS] Open a window to create, apply, and save playlist filters."),
                        ],
                    },
                    {
                        "title": "Load Saved Filter [🛠]",
                        "content": [
                            ("h1", "Load Saved Filter [🛠]"),
                            ("p", "[WORK IN PROGRESS] Apply a previously saved filter to the current playlist."),
                        ],
                    },
                    {
                        "title": "Delete Saved Filter [🛠]",
                        "content": [
                            ("h1", "Delete Saved Filter [🛠]"),
                            ("p", "[WORK IN PROGRESS] Delete a saved filter. You will be asked to confirm."),
                        ],
                    },
                ],
            },
            {
                "title": "Sort Playlist [🛠]",
                "content": [
                    ("h1", "Sort Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Sort the playlist by various criteria. Only available for non-infinite playlists."),
                ],
                "subs": [
                    {
                        "title": "Filename [🛠]",
                        "content": [
                            ("h1", "Sort by Filename [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sort filenames A → Z (Ascending) or Z → A (Descending)."),
                        ],
                    },
                    {
                        "title": "Title [🛠]",
                        "content": [
                            ("h1", "Sort by Title [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sort by the anime's Japanese title, ascending or descending."),
                        ],
                    },
                    {
                        "title": "English Title [🛠]",
                        "content": [
                            ("h1", "Sort by English Title [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sort by the anime's English title, ascending or descending."),
                        ],
                    },
                    {
                        "title": "Score [🛠]",
                        "content": [
                            ("h1", "Sort by Score [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sort by MAL score, lowest first or highest first."),
                        ],
                    },
                    {
                        "title": "Members [🛠]",
                        "content": [
                            ("h1", "Sort by Members [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sort by MAL member count (popularity), least or most popular first."),
                        ],
                    },
                    {
                        "title": "Season [🛠]",
                        "content": [
                            ("h1", "Sort by Season [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sort by the anime's airing season and year, oldest or newest first."),
                        ],
                    },
                ],
            },
            {
                "title": "Shuffle Playlist [🛠]",
                "content": [
                    ("h1", "Shuffle Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Randomize the order of themes in the playlist. Only available for non-infinite playlists."),
                ],
                "subs": [
                    {
                        "title": "Random [🛠]",
                        "content": [
                            ("h1", "Random Shuffle [🛠]"),
                            ("p", "[WORK IN PROGRESS] Completely random shuffle of the current playlist."),
                        ],
                    },
                    {
                        "title": "Weighted [🛠]",
                        "content": [
                            ("h1", "Weighted Shuffle [🛠]"),
                            ("p", "[WORK IN PROGRESS] Weighted shuffle balancing popular/niche and old/new anime, "
                                 "while avoiding the same series appearing too close together. Ideal for trivia sessions."),
                        ],
                    },
                ],
            },
            {
                "title": "Difficulty Mode [🛠]",
                "content": [
                    ("h1", "Difficulty Mode [🛠]"),
                    ("p", "[WORK IN PROGRESS] Sets the difficulty for infinite playlists by controlling which popularity groups are included. "
                         "Only visible when an infinite playlist is loaded."),
                ],
            },
            {
                "title": "Infinite Settings [🛠]",
                "content": [
                    ("h1", "Infinite Settings [🛠]"),
                    ("p", "[WORK IN PROGRESS] Open the Infinite Settings editor to configure infinite playlist behavior. "
                         "Only visible when an infinite playlist is loaded."),
                ],
            },
            {
                "title": "Bulk Mark Playlist [🛠]",
                "content": [
                    ("h1", "Bulk Mark Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Apply or remove a mark for every theme in the current playlist."),
                ],
                "subs": [
                    {
                        "title": "Bulk Tag Playlist [🛠]",
                        "content": [
                            ("h1", "Bulk Tag Playlist [🛠]"),
                            ("p", "[WORK IN PROGRESS] Bulk tag or untag every theme in the current playlist. Requires confirmation."),
                        ],
                    },
                    {
                        "title": "Bulk Favorite Playlist [🛠]",
                        "content": [
                            ("h1", "Bulk Favorite Playlist [🛠]"),
                            ("p", "[WORK IN PROGRESS] Bulk favorite or unfavorite every theme in the current playlist. Requires confirmation."),
                        ],
                    },
                    {
                        "title": "Bulk Blind Mark Playlist [🛠]",
                        "content": [
                            ("h1", "Bulk Blind Mark Playlist [🛠]"),
                            ("p", "[WORK IN PROGRESS] Bulk blind-mark or unmark every theme. Mutually exclusive with Reveal/Mute Reveal. Requires confirmation."),
                        ],
                    },
                    {
                        "title": "Bulk Reveal Mark Playlist [🛠]",
                        "content": [
                            ("h1", "Bulk Reveal Mark Playlist [🛠]"),
                            ("p", "[WORK IN PROGRESS] Bulk reveal-mark or unmark every theme. Mutually exclusive with Blind/Mute Reveal. Requires confirmation."),
                        ],
                    },
                    {
                        "title": "Bulk Mute Reveal Mark Playlist [🛠]",
                        "content": [
                            ("h1", "Bulk Mute Reveal Mark Playlist [🛠]"),
                            ("p", "[WORK IN PROGRESS] Bulk mute-reveal-mark or unmark every theme. Mutually exclusive with Blind/Reveal. Requires confirmation."),
                        ],
                    },
                ],
            },
        ],
    },
    {
        "title": "QUEUE [🛠]", "icon": "⚡",
        "content": [
            ("h1", "QUEUE [🛠]"),
            ("p", "[WORK IN PROGRESS] Queue special round types, lightning rounds, and YouTube videos."),
        ],
        "subs": [
            {
                "title": "Blind Round [🛠]",
                "content": [
                    ("h1", "Blind Round [🛠]"),
                    ("p", "[WORK IN PROGRESS] Queue the next theme as a Blind Round — audio only, screen covered."),
                ],
            },
            {
                "title": "Reveal Round [🛠]",
                "content": [
                    ("h1", "Reveal Round [🛠]"),
                    ("p", "[WORK IN PROGRESS] Queue the next theme as a Reveal Round — visuals are partially obscured (blur, zoom, slice, etc.)."),
                ],
                "subs": [
                    {
                        "title": "Blur [🛠]",
                        "content": [
                            ("h1", "Blur [🛠]"),
                            ("p", "[WORK IN PROGRESS] Gaussian blur — strong at the start, fades as the round progresses."),
                        ],
                    },
                    {
                        "title": "Edge [🛠]",
                        "content": [
                            ("h1", "Edge [🛠]"),
                            ("p", "[WORK IN PROGRESS] Blocks the middle of the screen, showing only the edges. Shrinks the blocked area over time."),
                        ],
                    },
                    {
                        "title": "Grow [🛠]",
                        "content": [
                            ("h1", "Grow [🛠]"),
                            ("p", "[WORK IN PROGRESS] Small window that slowly expands to reveal more of the video."),
                        ],
                    },
                    {
                        "title": "Outline [🛠]",
                        "content": [
                            ("h1", "Outline [🛠]"),
                            ("p", "[WORK IN PROGRESS] Only shows black outlines on white background. Line density increases over time."),
                        ],
                    },
                    {
                        "title": "Pixelize [🛠]",
                        "content": [
                            ("h1", "Pixelize [🛠]"),
                            ("p", "[WORK IN PROGRESS] Heavy pixelation — block size shrinks as the round progresses."),
                        ],
                    },
                    {
                        "title": "Slice [🛠]",
                        "content": [
                            ("h1", "Slice [🛠]"),
                            ("p", "[WORK IN PROGRESS] Two black panels slide apart to reveal a growing strip of video."),
                        ],
                    },
                    {
                        "title": "Wave [🛠]",
                        "content": [
                            ("h1", "Wave [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sine-wave spatial warp — distortion amplitude decreases over time."),
                        ],
                    },
                    {
                        "title": "Zoom [🛠]",
                        "content": [
                            ("h1", "Zoom [🛠]"),
                            ("p", "[WORK IN PROGRESS] Extreme zoom-in on a random region, gradually pulls back to full frame."),
                        ],
                    },
                ],
            },
            {
                "title": "Mute Reveal Round [🛠]",
                "content": [
                    ("h1", "Mute Reveal Round [🛠]"),
                    ("p", "[WORK IN PROGRESS] Queue the next theme as a Mute Reveal Round — visuals partially obscured, audio muted."),
                ],
            },
            {
                "title": "Lightning Rounds [🛠]",
                "content": [
                    ("h1", "Lightning Rounds [🛠]"),
                    ("p", "[WORK IN PROGRESS] Start a lightning round of a chosen type."),
                ],
            },
            {
                "title": "Variety Lightning Round [🛠]",
                "content": [
                    ("h1", "Variety Lightning Round [🛠]"),
                    ("p", "[WORK IN PROGRESS] Start a Variety Lightning Round — randomly picks round types weighted by popularity."),
                ],
            },
            {
                "title": "Lightning Settings [🛠]",
                "content": [
                    ("h1", "Lightning Settings [🛠]"),
                    ("p", "[WORK IN PROGRESS] Edit length, variants, and variety settings for each lightning round type."),
                ],
            },
            {
                "title": "YouTube Videos [🛠]",
                "content": [
                    ("h1", "YouTube Videos [🛠]"),
                    ("p", "[WORK IN PROGRESS] Browse and queue a YouTube video to play after the current theme."),
                ],
            },
            {
                "title": "Archived YouTube Videos [🛠]",
                "content": [
                    ("h1", "Archived YouTube Videos [🛠]"),
                    ("p", "[WORK IN PROGRESS] Browse and queue an archived YouTube video."),
                ],
            },
            {
                "title": "Manage YouTube Videos [🛠]",
                "content": [
                    ("h1", "Manage YouTube Videos [🛠]"),
                    ("p", "[WORK IN PROGRESS] Add, edit, and archive YouTube videos for queuing."),
                ],
            },
            {
                "title": "Fixed Lightning Rounds [🛠]",
                "content": [
                    ("h1", "Fixed Lightning Rounds [🛠]"),
                    ("p", "[WORK IN PROGRESS] Queue up a curated fixed lightning round playlist."),
                ],
            },
            {
                "title": "Manage Fixed Lightning Rounds [🛠]",
                "content": [
                    ("h1", "Manage Fixed Lightning Rounds [🛠]"),
                    ("p", "[WORK IN PROGRESS] Create and manage curated fixed lightning round playlists."),
                ],
            },
        ],
    },
    {
        "title": "BONUS [🛠]", "icon": "🎲",
        "content": [
            ("h1", "BONUS [🛠]"),
            ("p", "[WORK IN PROGRESS] Bonus question types for players to answer while a theme plays."),
        ],
        "subs": [
            {
                "title": "Auto Bonus at Start [🛠]",
                "content": [
                    ("h1", "Auto Bonus at Start [🛠]"),
                    ("p", "[WORK IN PROGRESS] Automatically start a bonus question at the beginning of each theme."),
                ],
            },
            {
                "title": "Free Form [🛠]",
                "content": [
                    ("h1", "Free Form [🛠]"),
                    ("p", "[WORK IN PROGRESS] Open a free-answer prompt."),
                ],
            },
            {
                "title": "Buzzer [🛠]",
                "content": [
                    ("h1", "Buzzer [🛠]"),
                    ("p", "[WORK IN PROGRESS] Open a buzzer-only web bonus round."),
                ],
            },
            {
                "title": "Multiple Choice [🛠]",
                "content": [
                    ("h1", "Multiple Choice [🛠]"),
                    ("p", "[WORK IN PROGRESS] Multiple-choice: guess the anime from 4 options."),
                ],
            },
            {
                "title": "Year [🛠]",
                "content": [
                    ("h1", "Year [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the year this anime first aired."),
                ],
            },
            {
                "title": "Score [🛠]",
                "content": [
                    ("h1", "Score [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the MyAnimeList score (0.0–10.0)."),
                ],
            },
            {
                "title": "Members [🛠]",
                "content": [
                    ("h1", "Members [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the number of MyAnimeList members."),
                ],
            },
            {
                "title": "Popularity Rank [🛠]",
                "content": [
                    ("h1", "Popularity Rank [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the popularity rank on MyAnimeList."),
                ],
            },
            {
                "title": "Tags [🛠]",
                "content": [
                    ("h1", "Tags [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the genres/themes/demographics tags."),
                ],
            },
            {
                "title": "Studio [🛠]",
                "content": [
                    ("h1", "Studio [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the studio that made this anime."),
                ],
            },
            {
                "title": "Artist [🛠]",
                "content": [
                    ("h1", "Artist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the artist who performed the theme."),
                ],
            },
            {
                "title": "Song Title [🛠]",
                "content": [
                    ("h1", "Song Title [🛠]"),
                    ("p", "[WORK IN PROGRESS] Guess the name of the song."),
                ],
            },
            {
                "title": "Characters [🛠]",
                "content": [
                    ("h1", "Characters [🛠]"),
                    ("p", "[WORK IN PROGRESS] Identify 2 characters from this anime out of 6 shown."),
                ],
            },
            {
                "title": "Bonus Settings [🛠]",
                "content": [
                    ("h1", "Bonus Settings [🛠]"),
                    ("p", "[WORK IN PROGRESS] Configure points, lightning points, and random eligibility for each bonus type."),
                ],
            },
        ],
    },
    {
        "title": "INFORMATION [🛠]", "icon": "ℹ️",
        "content": [
            ("h1", "INFORMATION [🛠]"),
            ("p", "[WORK IN PROGRESS] Popups showing information about the currently playing theme and anime."),
        ],
        "subs": [
            {
                "title": "Info Popup [🛠]",
                "content": [
                    ("h1", "Info Popup [🛠]"),
                    ("p", "[WORK IN PROGRESS] Show or hide the information popup at the bottom of the screen."),
                ],
            },
            {
                "title": "Title Popup [🛠]",
                "content": [
                    ("h1", "Title Popup [🛠]"),
                    ("p", "[WORK IN PROGRESS] Show or hide the title popup at the bottom of the screen."),
                ],
            },
            {
                "title": "Artist Info [🛠]",
                "content": [
                    ("h1", "Artist Info [🛠]"),
                    ("p", "[WORK IN PROGRESS] Show or hide the info popup listing themes by this artist."),
                ],
            },
            {
                "title": "Studio Info [🛠]",
                "content": [
                    ("h1", "Studio Info [🛠]"),
                    ("p", "[WORK IN PROGRESS] Show or hide the info popup listing anime by this studio."),
                ],
            },
            {
                "title": "Season Rankings [🛠]",
                "content": [
                    ("h1", "Season Rankings [🛠]"),
                    ("p", "[WORK IN PROGRESS] Show or hide the info popup with season popularity rankings."),
                ],
            },
            {
                "title": "Year Rankings [🛠]",
                "content": [
                    ("h1", "Year Rankings [🛠]"),
                    ("p", "[WORK IN PROGRESS] Show or hide the info popup with year popularity rankings."),
                ],
            },
            {
                "title": "Auto-show at Start [🛠]",
                "content": [
                    ("h1", "Auto-show at Start [🛠]"),
                    ("p", "[WORK IN PROGRESS] When enabled, automatically shows the info popup at the start of each theme."),
                ],
            },
            {
                "title": "Auto-show at End [🛠]",
                "content": [
                    ("h1", "Auto-show at End [🛠]"),
                    ("p", "[WORK IN PROGRESS] When enabled, automatically shows the info popup during the last 8 seconds."),
                ],
            },
            {
                "title": "End Screen [🛠]",
                "content": [
                    ("h1", "End Screen [🛠]"),
                    ("p", "[WORK IN PROGRESS] Display the end session screen with a scrolling message and themes played count."),
                ],
            },
        ],
    },
    {
        "title": "THEME [🛠]", "icon": "🎬",
        "content": [
            ("h1", "THEME [🛠]"),
            ("p", "[WORK IN PROGRESS] Actions and marks for the currently playing theme."),
        ],
        "subs": [
            {
                "title": "Tag [🛠]",
                "content": [
                    ("h1", "Tag [🛠]"),
                    ("p", "[WORK IN PROGRESS] Add or remove the current theme from the 'Tagged Themes' playlist."),
                ],
            },
            {
                "title": "Favorite [🛠]",
                "content": [
                    ("h1", "Favorite [🛠]"),
                    ("p", "[WORK IN PROGRESS] Add or remove the current theme from the 'Favorite Themes' playlist."),
                ],
            },
            {
                "title": "Blind Mark [🛠]",
                "content": [
                    ("h1", "Blind Mark [🛠]"),
                    ("p", "[WORK IN PROGRESS] Add or remove the current theme from the 'Blind Themes' auto-round playlist."),
                ],
            },
            {
                "title": "Reveal Mark [🛠]",
                "content": [
                    ("h1", "Reveal Mark [🛠]"),
                    ("p", "[WORK IN PROGRESS] Add or remove the current theme from the Reveal playlist (plays as a Reveal Round)."),
                ],
            },
            {
                "title": "Mute Reveal Mark [🛠]",
                "content": [
                    ("h1", "Mute Reveal Mark [🛠]"),
                    ("p", "[WORK IN PROGRESS] Add or remove the current theme from the Mute Reveal playlist (plays as a Mute Reveal Round)."),
                ],
            },
            {
                "title": "Add to Playlist [🛠]",
                "content": [
                    ("h1", "Add to Playlist [🛠]"),
                    ("p", "[WORK IN PROGRESS] Add the current theme to one of your saved (non-system) playlists."),
                ],
            },
            {
                "title": "Fetch Theme Data [🛠]",
                "content": [
                    ("h1", "Fetch Theme Data [🛠]"),
                    ("p", "[WORK IN PROGRESS] Fetch metadata for the currently playing theme from AnimeThemes, Jikan, AniList, and AniDB."),
                ],
            },
            {
                "title": "Copy Filename [🛠]",
                "content": [
                    ("h1", "Copy Filename [🛠]"),
                    ("p", "[WORK IN PROGRESS] Copy the filename to the clipboard."),
                ],
            },
            {
                "title": "Download [🛠]",
                "content": [
                    ("h1", "Download [🛠]"),
                    ("p", "[WORK IN PROGRESS] Download or move this file to the local directory."),
                ],
            },
            {
                "title": "File Actions [🛠]",
                "content": [
                    ("h1", "File Actions [🛠]"),
                    ("p", "[WORK IN PROGRESS] File operations for the currently playing theme."),
                ],
                "subs": [
                    {
                        "title": "Open Folder [🛠]",
                        "content": [
                            ("h1", "Open Folder [🛠]"),
                            ("p", "[WORK IN PROGRESS] Open the folder containing this file."),
                        ],
                    },
                    {
                        "title": "Cut Before [🛠]",
                        "content": [
                            ("h1", "Cut Before [🛠]"),
                            ("p", "[WORK IN PROGRESS] Cut the file before the current playback position."),
                        ],
                    },
                    {
                        "title": "Cut After [🛠]",
                        "content": [
                            ("h1", "Cut After [🛠]"),
                            ("p", "[WORK IN PROGRESS] Cut the file after the current playback position."),
                        ],
                    },
                    {
                        "title": "Rename [🛠]",
                        "content": [
                            ("h1", "Rename [🛠]"),
                            ("p", "[WORK IN PROGRESS] Rename the currently playing file."),
                        ],
                    },
                    {
                        "title": "Convert [🛠]",
                        "content": [
                            ("h1", "Convert [🛠]"),
                            ("p", "[WORK IN PROGRESS] Convert the file to a different format."),
                        ],
                    },
                    {
                        "title": "Edit Volume [🛠]",
                        "content": [
                            ("h1", "Edit Volume [🛠]"),
                            ("p", "[WORK IN PROGRESS] Adjust the audio volume of this file."),
                        ],
                    },
                    {
                        "title": "Delete File [🛠]",
                        "content": [
                            ("h1", "Delete File [🛠]"),
                            ("p", "[WORK IN PROGRESS] Permanently delete this file."),
                        ],
                    },
                ],
            },
            {
                "title": "External Sites [🛠]",
                "content": [
                    ("h1", "External Sites [🛠]"),
                    ("p", "[WORK IN PROGRESS] Open external database pages for this anime."),
                ],
                "subs": [
                    {
                        "title": "MyAnimeList [🛠]",
                        "content": [
                            ("h1", "MyAnimeList [🛠]"),
                            ("p", "[WORK IN PROGRESS] Open the MyAnimeList page for this anime."),
                        ],
                    },
                    {
                        "title": "AniDB [🛠]",
                        "content": [
                            ("h1", "AniDB [🛠]"),
                            ("p", "[WORK IN PROGRESS] Open the AniDB page for this anime."),
                        ],
                    },
                    {
                        "title": "AniList [🛠]",
                        "content": [
                            ("h1", "AniList [🛠]"),
                            ("p", "[WORK IN PROGRESS] Open the AniList page for this anime."),
                        ],
                    },
                    {
                        "title": "AnimeThemes [🛠]",
                        "content": [
                            ("h1", "AnimeThemes [🛠]"),
                            ("p", "[WORK IN PROGRESS] Open the AnimeThemes page for this anime."),
                        ],
                    },
                    {
                        "title": "IGDB [🛠]",
                        "content": [
                            ("h1", "IGDB [🛠]"),
                            ("p", "[WORK IN PROGRESS] Open the IGDB page for this game."),
                        ],
                    },
                ],
            },
            {
                "title": "Media [🛠]",
                "content": [
                    ("h1", "Media [🛠]"),
                    ("p", "[WORK IN PROGRESS] Cover art, trailer, and AI trivia for this anime."),
                ],
                "subs": [
                    {
                        "title": "Show Cover [🛠]",
                        "content": [
                            ("h1", "Show Cover [🛠]"),
                            ("p", "[WORK IN PROGRESS] Show the cover art for this anime."),
                        ],
                    },
                    {
                        "title": "Copy Cover URL [🛠]",
                        "content": [
                            ("h1", "Copy Cover URL [🛠]"),
                            ("p", "[WORK IN PROGRESS] Copy the cover art URL to the clipboard."),
                        ],
                    },
                    {
                        "title": "Play Trailer [🛠]",
                        "content": [
                            ("h1", "Play Trailer [🛠]"),
                            ("p", "[WORK IN PROGRESS] Play the trailer for this anime."),
                        ],
                    },
                    {
                        "title": "Copy Trailer URL [🛠]",
                        "content": [
                            ("h1", "Copy Trailer URL [🛠]"),
                            ("p", "[WORK IN PROGRESS] Copy the trailer URL to the clipboard."),
                        ],
                    },
                    {
                        "title": "Trivia [🛠]",
                        "content": [
                            ("h1", "Trivia [🛠]"),
                            ("p", "[WORK IN PROGRESS] Generate AI trivia about this anime. Prints in console."),
                        ],
                    },
                ],
            },
        ],
    },
    {
        "title": "TOGGLES [🛠]", "icon": "⚙️",
        "content": [
            ("h1", "TOGGLES [🛠]"),
            ("p", "[WORK IN PROGRESS] Toggle visual effects, audio effects, censors, and other app settings."),
        ],
        "subs": [
            {
                "title": "Blind [🛠]",
                "content": [
                    ("h1", "Blind [🛠]"),
                    ("p", "[WORK IN PROGRESS] Covers the screen with a color matching the average screen color. Shows a progress bar if a video is playing."),
                ],
            },
            {
                "title": "Reveal [🛠]",
                "content": [
                    ("h1", "Reveal [🛠]"),
                    ("p", "[WORK IN PROGRESS] When off: opens a submenu to pick a variant (or random). When on: turns off."),
                ],
                "subs": [
                    {
                        "title": "Blur [🛠]",
                        "content": [
                            ("h1", "Blur [🛠]"),
                            ("p", "[WORK IN PROGRESS] Gaussian blur — strong at the start, fades as the round progresses."),
                        ],
                    },
                    {
                        "title": "Edge [🛠]",
                        "content": [
                            ("h1", "Edge [🛠]"),
                            ("p", "[WORK IN PROGRESS] Blocks the middle of the screen, showing only the edges. Shrinks the blocked area over time."),
                        ],
                    },
                    {
                        "title": "Grow [🛠]",
                        "content": [
                            ("h1", "Grow [🛠]"),
                            ("p", "[WORK IN PROGRESS] Small window that slowly expands to reveal more of the video."),
                        ],
                    },
                    {
                        "title": "Outline [🛠]",
                        "content": [
                            ("h1", "Outline [🛠]"),
                            ("p", "[WORK IN PROGRESS] Only shows black outlines on white background. Line density increases over time."),
                        ],
                    },
                    {
                        "title": "Pixelize [🛠]",
                        "content": [
                            ("h1", "Pixelize [🛠]"),
                            ("p", "[WORK IN PROGRESS] Heavy pixelation — block size shrinks as the round progresses."),
                        ],
                    },
                    {
                        "title": "Slice [🛠]",
                        "content": [
                            ("h1", "Slice [🛠]"),
                            ("p", "[WORK IN PROGRESS] Two black panels slide apart to reveal a growing strip of video."),
                        ],
                    },
                    {
                        "title": "Wave [🛠]",
                        "content": [
                            ("h1", "Wave [🛠]"),
                            ("p", "[WORK IN PROGRESS] Sine-wave spatial warp — distortion amplitude decreases over time."),
                        ],
                    },
                    {
                        "title": "Zoom [🛠]",
                        "content": [
                            ("h1", "Zoom [🛠]"),
                            ("p", "[WORK IN PROGRESS] Extreme zoom-in on a random region, gradually pulls back to full frame."),
                        ],
                    },
                ],
            },
            {
                "title": "Reveal Less [🛠]",
                "content": [
                    ("h1", "Reveal Less [🛠]"),
                    ("p", "[WORK IN PROGRESS] Reveals less — increases the obscuring effect."),
                ],
            },
            {
                "title": "Reveal More [🛠]",
                "content": [
                    ("h1", "Reveal More [🛠]"),
                    ("p", "[WORK IN PROGRESS] Reveals more — decreases the obscuring effect."),
                ],
            },
            {
                "title": "Mute [🛠]",
                "content": [
                    ("h1", "Mute [🛠]"),
                    ("p", "[WORK IN PROGRESS] Toggles muting the video/theme audio."),
                ],
            },
            {
                "title": "Distort Audio [🛠]",
                "content": [
                    ("h1", "Distort Audio [🛠]"),
                    ("p", "[WORK IN PROGRESS] Apply audio distortion filters to make themes harder to recognise."),
                ],
                "subs": [
                    {
                        "title": "Echo [🛠]",
                        "content": [
                            ("h1", "Echo [🛠]"),
                            ("p", "[WORK IN PROGRESS] Echo / reverb effect."),
                        ],
                    },
                    {
                        "title": "Flanger [🛠]",
                        "content": [
                            ("h1", "Flanger [🛠]"),
                            ("p", "[WORK IN PROGRESS] Swirling / wobbly flanger effect."),
                        ],
                    },
                    {
                        "title": "Vibrato [🛠]",
                        "content": [
                            ("h1", "Vibrato [🛠]"),
                            ("p", "[WORK IN PROGRESS] Pitch oscillation at 7 Hz."),
                        ],
                    },
                    {
                        "title": "Telephone [🛠]",
                        "content": [
                            ("h1", "Telephone [🛠]"),
                            ("p", "[WORK IN PROGRESS] Narrow phone-band filter (300–3400 Hz only)."),
                        ],
                    },
                    {
                        "title": "Underwater [🛠]",
                        "content": [
                            ("h1", "Underwater [🛠]"),
                            ("p", "[WORK IN PROGRESS] Heavy lowpass + reverb — muffled underwater effect."),
                        ],
                    },
                    {
                        "title": "Chipmunk [🛠]",
                        "content": [
                            ("h1", "Chipmunk [🛠]"),
                            ("p", "[WORK IN PROGRESS] 2× pitch up — chipmunk voice."),
                        ],
                    },
                    {
                        "title": "Demon [🛠]",
                        "content": [
                            ("h1", "Demon [🛠]"),
                            ("p", "[WORK IN PROGRESS] 0.5× pitch down — deep demon voice."),
                        ],
                    },
                    {
                        "title": "Vaporwave [🛠]",
                        "content": [
                            ("h1", "Vaporwave [🛠]"),
                            ("p", "[WORK IN PROGRESS] 0.8× pitch — slowed + slightly lower."),
                        ],
                    },
                    {
                        "title": "8-bit Game [🛠]",
                        "content": [
                            ("h1", "8-bit Game [🛠]"),
                            ("p", "[WORK IN PROGRESS] 2-bit depth @ 8 kHz — retro video game bleeps."),
                        ],
                    },
                    {
                        "title": "Robot [🛠]",
                        "content": [
                            ("h1", "Robot [🛠]"),
                            ("p", "[WORK IN PROGRESS] Rapid micro-echoes + 30 Hz vibrato — robotic stutter."),
                        ],
                    },
                ],
            },
            {
                "title": "Censors Toggle [🛠]",
                "content": [
                    ("h1", "Censors Toggle [🛠]"),
                    ("p", "[WORK IN PROGRESS] Toggle regular censor bars on or off. NSFW censors have a separate toggle."),
                ],
            },
            {
                "title": "NSFW Censors Toggle [🛠]",
                "content": [
                    ("h1", "NSFW Censors Toggle [🛠]"),
                    ("p", "[WORK IN PROGRESS] Toggle NSFW censor bars on or off. Regular censors have a separate toggle."),
                ],
            },
            {
                "title": "Censor Editor [🛠]",
                "content": [
                    ("h1", "Censor Editor [🛠]"),
                    ("p", "[WORK IN PROGRESS] Opens the censor editor to add, edit, or delete censor boxes for the current theme."),
                ],
            },
            {
                "title": "Always On Top [🛠]",
                "content": [
                    ("h1", "Always On Top [🛠]"),
                    ("p", "[WORK IN PROGRESS] Keep the mpv player window on top of all other windows."),
                ],
            },
            {
                "title": "Auto Refresh Metadata [🛠]",
                "content": [
                    ("h1", "Auto Refresh Metadata [🛠]"),
                    ("p", "[WORK IN PROGRESS] Toggle auto refreshing jikan metadata (score, members) as themes play — never refreshes the same anime twice per session."),
                ],
            },
            {
                "title": "Fullscreen [🛠]",
                "content": [
                    ("h1", "Fullscreen [🛠]"),
                    ("p", "[WORK IN PROGRESS] Toggle whether the player starts in fullscreen when a track plays."),
                ],
            },
            {
                "title": "Progress Bar [🛠]",
                "content": [
                    ("h1", "Progress Bar [🛠]"),
                    ("p", "[WORK IN PROGRESS] Toggle a subtle progress bar overlay showing the current playback position."),
                ],
            },
            {
                "title": "Enable Shortcuts [🛠]",
                "content": [
                    ("h1", "Enable Shortcuts [🛠]"),
                    ("p", "[WORK IN PROGRESS] Toggle shortcut keys on or off."),
                ],
            },
            {
                "title": "Edit/View Shortcuts [🛠]",
                "content": [
                    ("h1", "Edit/View Shortcuts [🛠]"),
                    ("p", "[WORK IN PROGRESS] View and edit keyboard shortcuts."),
                ],
            },
        ],
    },
    {
        "title": "DIRECTORY [🛠]", "icon": "🗂",
        "content": [
            ("h1", "DIRECTORY [🛠]"),
            ("p", "[WORK IN PROGRESS] Browse and list all themes grouped by various criteria."),
        ],
        "subs": [
            {
                "title": "Themes by Artist [🛠]",
                "content": [
                    ("h1", "Themes by Artist [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by artist."),
                ],
            },
            {
                "title": "Themes by Season [🛠]",
                "content": [
                    ("h1", "Themes by Season [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by season."),
                ],
            },
            {
                "title": "Themes by Series [🛠]",
                "content": [
                    ("h1", "Themes by Series [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by series."),
                ],
            },
            {
                "title": "Themes by Slug [🛠]",
                "content": [
                    ("h1", "Themes by Slug [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by slug (OP1, ED2, etc.)."),
                ],
            },
            {
                "title": "Themes by Studio [🛠]",
                "content": [
                    ("h1", "Themes by Studio [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by studio."),
                ],
            },
            {
                "title": "Themes by Tag [🛠]",
                "content": [
                    ("h1", "Themes by Tag [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by tag."),
                ],
            },
            {
                "title": "Themes by Type [🛠]",
                "content": [
                    ("h1", "Themes by Type [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by format/type."),
                ],
            },
            {
                "title": "Themes by Year [🛠]",
                "content": [
                    ("h1", "Themes by Year [🛠]"),
                    ("p", "[WORK IN PROGRESS] List all themes grouped by year."),
                ],
            },
        ],
    }
]


def show_tutorial_popup(root, *, bg_color, hl_color, root_font, scl,
                        get_window_pos, is_shown, on_close):
    """Opens the Help & Tutorial window with a sidebar-driven layout.

    Args:
        root:           tk root window (for transient/positioning).
        bg_color:       BACKGROUND_COLOR string.
        hl_color:       HIGHLIGHT_COLOR string.
        root_font:      ROOT_FONT tuple.
        scl:            Scale function scl(value, mode).
        get_window_pos: get_window_position_and_setup function.
        is_shown:       Current value of tutorial_shown (bool).
        on_close:       Callback(show_on_startup: bool) invoked when the
                        window closes — use it to persist tutorial_shown and
                        call save_config().
    """
    global _tutorial_window

    if _tutorial_window and _tutorial_window.winfo_exists():
        try:
            _tutorial_window.lift()
            _tutorial_window.focus_force()
        except Exception:
            pass
        return

    # ── Style constants ───────────────────────────────────────────────────────
    _SIDEBAR_BG = "gray18"
    _SEL_BG     = hl_color
    _HOVER_BG   = "gray30"
    _TIP_BG     = "gray22"
    _TIP_FG     = "#d0eaff"
    _H1_FONT    = (root_font[0], root_font[1] + 7, "bold")
    _H2_FONT    = (root_font[0], root_font[1] + 3, "bold")
    _SUB_FONT   = (root_font[0], root_font[1] + 1)

    # ── Window setup ──────────────────────────────────────────────────────────
    _tutorial_window = tk.Toplevel(bg=bg_color)
    _tutorial_window.title("Help & Tutorial")
    _tutorial_window.resizable(True, True)
    _tutorial_window.geometry(f"{scl(950, 'UI')}x{scl(600, 'UI')}")
    _tutorial_window.minsize(scl(680, 'UI'), scl(420, 'UI'))

    try:
        _tutorial_window.transient(root)
        get_window_pos(_tutorial_window, offset_x=40, offset_y=40)
    except Exception:
        pass

    # ── State: "show on startup" checkbox ────────────────────────────────────
    _show_on_startup = tk.BooleanVar(value=not is_shown)

    def _on_close():
        global _tutorial_window
        on_close(_show_on_startup.get())
        try:
            _tutorial_window.destroy()
        except Exception:
            pass
        _tutorial_window = None

    _tutorial_window.protocol("WM_DELETE_WINDOW", _on_close)

    # ── Layout ────────────────────────────────────────────────────────────────
    outer = tk.Frame(_tutorial_window, bg=bg_color)
    outer.pack(fill="both", expand=True)

    sidebar_frame = tk.Frame(outer, bg=_SIDEBAR_BG, width=scl(230, 'UI'))
    sidebar_frame.pack(side="left", fill="y")
    sidebar_frame.pack_propagate(False)

    sidebar_canvas = tk.Canvas(sidebar_frame, bg=_SIDEBAR_BG, highlightthickness=0)
    sidebar_scroll = tk.Scrollbar(sidebar_frame, orient="vertical", command=sidebar_canvas.yview)
    sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
    sidebar_inner = tk.Frame(sidebar_canvas, bg=_SIDEBAR_BG)
    _sid_win = sidebar_canvas.create_window((0, 0), window=sidebar_inner, anchor="nw")
    sidebar_scroll.pack(side="right", fill="y")
    sidebar_canvas.pack(side="left", fill="both", expand=True)

    def _on_sidebar_resize(e):
        sidebar_canvas.after(0, lambda: sidebar_canvas.configure(
            scrollregion=sidebar_canvas.bbox("all")))

    def _on_canvas_configure(e):
        sidebar_canvas.itemconfig(_sid_win, width=e.width)

    sidebar_inner.bind("<Configure>", _on_sidebar_resize)
    sidebar_canvas.bind("<Configure>", _on_canvas_configure)

    def _sidebar_mousewheel(e):
        sidebar_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
    sidebar_canvas.bind("<MouseWheel>", _sidebar_mousewheel)
    sidebar_inner.bind("<MouseWheel>", _sidebar_mousewheel)

    # Content area
    content_frame = tk.Frame(outer, bg=bg_color)
    content_frame.pack(side="left", fill="both", expand=True)

    content_text = tk.Text(
        content_frame, bg=bg_color, fg="white",
        font=(root_font[0], root_font[1] + 2), wrap="word", relief="flat",
        padx=scl(20, 'UI'), pady=scl(14, 'UI'),
        cursor="arrow", state=tk.DISABLED,
    )
    content_scroll = tk.Scrollbar(content_frame, orient="vertical", command=content_text.yview)
    content_text.configure(yscrollcommand=content_scroll.set)
    content_scroll.pack(side="right", fill="y")
    content_text.pack(fill="both", expand=True)

    # ── Text tags ─────────────────────────────────────────────────────────────
    content_text.tag_configure("h1",
        font=_H1_FONT, foreground="white", spacing1=4, spacing3=8)
    content_text.tag_configure("h1_ul", underline=True)
    content_text.tag_configure("h2",
        font=_H2_FONT, foreground="#cccccc", spacing1=12, spacing3=4)
    content_text.tag_configure("h2_ul", underline=True)
    content_text.tag_configure("p",
        font=(root_font[0], root_font[1] + 2), foreground="#dddddd",
        spacing1=2, spacing3=6, lmargin1=4, lmargin2=4)
    content_text.tag_configure("b",
        font=(root_font[0], root_font[1] + 2, "bold"), foreground="white")
    content_text.tag_configure("bullet",
        font=(root_font[0], root_font[1] + 2), foreground="#dddddd",
        spacing1=1, spacing3=1,
        lmargin1=scl(14, 'UI'), lmargin2=scl(28, 'UI'))
    content_text.tag_configure("tip_label",
        background=_TIP_BG, foreground="#7bc4f0",
        font=(root_font[0], root_font[1] + 2, "bold"),
        spacing1=8, spacing3=0, lmargin1=scl(10, 'UI'))
    content_text.tag_configure("tip_body",
        background=_TIP_BG, foreground=_TIP_FG,
        font=(root_font[0], root_font[1] + 2),
        spacing1=2, spacing3=8,
        lmargin1=scl(10, 'UI'), lmargin2=scl(10, 'UI'), rmargin=scl(10, 'UI'))
    content_text.tag_configure("sep_space",
        font=(root_font[0], 5), spacing1=2, spacing3=2)

    # ── Content renderer ──────────────────────────────────────────────────────
    def _render_content(content_list):
        content_text.config(state=tk.NORMAL)
        content_text.delete("1.0", tk.END)
        for item in content_list:
            tag = item[0]
            if tag == "h1":
                content_text.insert(tk.END, item[1] + "\n", ("h1", "h1_ul"))
            elif tag == "h2":
                content_text.insert(tk.END, item[1] + "\n", ("h2", "h2_ul"))
            elif tag == "p":
                content_text.insert(tk.END, item[1] + "\n", "p")
            elif tag == "b":
                content_text.insert(tk.END, item[1] + "\n", "b")
            elif tag == "ul":
                for bullet in item[1]:
                    content_text.insert(tk.END, f"\u2022  {bullet}\n", "bullet")
            elif tag == "tip":
                content_text.insert(tk.END, "  \U0001f4a1 Note\n", "tip_label")
                content_text.insert(tk.END, f"  {item[1]}\n", "tip_body")
            elif tag == "sep":
                content_text.insert(tk.END, "\n", "sep_space")
        content_text.config(state=tk.DISABLED)
        content_text.yview_moveto(0)

    # ── Sidebar state ─────────────────────────────────────────────────────────
    _all_btns   = []        # list of (button, is_top_level)
    _nav_pages  = []        # ordered list of (btn, content) for content nodes
    _nav_index  = [0]
    _first_node = [None, None]  # [btn, content] of first content node

    def _deselect_all():
        for btn, is_top in _all_btns:
            btn.config(
                bg=_SIDEBAR_BG,
                fg="white" if is_top else "#cccccc",
                relief="flat",
            )

    # ── Recursive tree builder ─────────────────────────────────────────────────
    def _build_tree(parent, nodes, level=0):
        indent = "  " * (level + 1)
        for node in nodes:
            title   = node.get("title", "")
            icon    = node.get("icon", "")
            content = node.get("content", [])
            subs    = node.get("subs", [])
            is_top  = (level == 0)

            has_subs = bool(subs)
            arrow    = "▶ " if has_subs else "  "
            if icon:
                label = f"{indent}{arrow}{icon}  {title}"
            else:
                label = f"{indent}{arrow}{title}"

            wrapper = tk.Frame(parent, bg=_SIDEBAR_BG)
            wrapper.pack(fill="x")

            btn = tk.Button(
                wrapper, text=label, anchor="w",
                bg=_SIDEBAR_BG,
                fg="white" if is_top else "#cccccc",
                font=(root_font[0], root_font[1] + (2 if is_top else 1),
                      "bold" if is_top else "normal"),
                relief="flat", bd=0,
                padx=scl(6, 'UI'),
                pady=scl(6 if is_top else 5, 'UI'),
                activebackground=_HOVER_BG, activeforeground="white",
                cursor="hand2",
            )
            btn.pack(fill="x")
            _all_btns.append((btn, is_top))

            if content:
                _nav_pages.append((btn, content))
                if _first_node[0] is None:
                    _first_node[0] = btn
                    _first_node[1] = content

            if subs:
                children_frame = tk.Frame(wrapper, bg=_SIDEBAR_BG)
                _col = [True]  # True = collapsed

                _build_tree(children_frame, subs, level + 1)

                def _make_label(ic, t, ind, collapsed):
                    arr = "▶ " if collapsed else "▼ "
                    return (f"{ind}{arr}{ic}  {t}") if ic else (f"{ind}{arr}{t}")

                def _click(b=btn, c=content, cf=children_frame, col=_col,
                           ic=icon, t=title, ind=indent):
                    if c:
                        _deselect_all()
                        b.config(bg=_SEL_BG, fg="white")
                        _render_content(c)
                    col[0] = not col[0]
                    b.config(text=_make_label(ic, t, ind, col[0]))
                    if col[0]:
                        cf.pack_forget()
                    else:
                        cf.pack(fill="x")
                    b.after(0, lambda: sidebar_canvas.configure(
                        scrollregion=sidebar_canvas.bbox("all")))

                btn.config(command=_click)
            elif content:
                def _click(b=btn, c=content):
                    _deselect_all()
                    b.config(bg=_SEL_BG, fg="white")
                    _render_content(c)
                btn.config(command=_click)

            btn.bind("<Enter>",
                lambda e, b=btn: b.config(bg=_HOVER_BG) if b.cget("bg") != _SEL_BG else None)
            btn.bind("<Leave>",
                lambda e, b=btn: b.config(bg=_SIDEBAR_BG) if b.cget("bg") == _HOVER_BG else None)
            btn.bind("<MouseWheel>", _sidebar_mousewheel)

    _build_tree(sidebar_inner, TUTORIAL_CONTENT)
    sidebar_inner.update_idletasks()
    sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))

    # Select first content node
    if _first_node[0] is not None:
        _first_node[0].config(bg=_SEL_BG, fg="white")
        _render_content(_first_node[1])
        _nav_index[0] = 0

    # ── Bottom bar ────────────────────────────────────────────────────────────
    bottom_bar = tk.Frame(_tutorial_window, bg="gray18", pady=scl(7, 'UI'))
    bottom_bar.pack(side="bottom", fill="x")

    tk.Checkbutton(
        bottom_bar, text="Show this on startup",
        variable=_show_on_startup,
        bg="gray18", fg="#dfdfdf",
        selectcolor="gray18",
        activebackground="gray18", activeforeground="white",
        font=_SUB_FONT,
    ).pack(side="left", padx=scl(16, 'UI'))

    tk.Button(
        bottom_bar, text="Close", command=_on_close,
        bg="black", fg="white", font=root_font,
        relief="flat", padx=scl(12, 'UI'), pady=scl(4, 'UI'),
        activebackground=hl_color, activeforeground="white",
    ).pack(side="right", padx=scl(16, 'UI'))

    _nav_center = tk.Frame(bottom_bar, bg="gray18")
    _nav_center.pack(side="left", fill="x", expand=True)

    def _go_to_page(idx):
        idx = max(0, min(idx, len(_nav_pages) - 1))
        _nav_index[0] = idx
        btn, content = _nav_pages[idx]
        _deselect_all()
        btn.config(bg=_SEL_BG, fg="white")
        _render_content(content)
        prev_btn.config(state=tk.NORMAL if idx > 0 else tk.DISABLED)
        next_btn.config(state=tk.NORMAL if idx < len(_nav_pages) - 1 else tk.DISABLED)

    prev_btn = tk.Button(
        _nav_center, text="◀  Previous Page", command=lambda: _go_to_page(_nav_index[0] - 1),
        bg="black", fg="white", font=root_font,
        relief="flat", padx=scl(12, 'UI'), pady=scl(4, 'UI'),
        activebackground=hl_color, activeforeground="white",
        state=tk.DISABLED,
    )
    prev_btn.pack(side="left", expand=True)

    next_btn = tk.Button(
        _nav_center, text="Next Page  ▶", command=lambda: _go_to_page(_nav_index[0] + 1),
        bg="black", fg="white", font=root_font,
        relief="flat", padx=scl(12, 'UI'), pady=scl(4, 'UI'),
        activebackground=hl_color, activeforeground="white",
    )
    next_btn.pack(side="left", expand=True)

    next_btn.config(state=tk.NORMAL if len(_nav_pages) > 1 else tk.DISABLED)
