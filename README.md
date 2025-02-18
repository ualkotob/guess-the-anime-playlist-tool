# Guess The Anime - Playlist Tool

## Description

Guess The Anime - Playlist Tool is a Python-based program I created to help me run trivia sessions with anime openings from the AnimeThemes website. It supports playlist management, metadata fetching from AnimeThemes and Jikan API, and multiple lightning rounds.

## Features

- Play local anime openings & endings.
- Pull and display information using API.
- Multiple Lightning Round modes:
  - **Regular** (Random 12 seconds)
  - **Frame** (Still images only)
  - **Blind** (Audio-only)
  - **Clues** (Metadata hints only)
  - **Variety** (Random mix of modes)
- Save & load custom playlists and filters.
- Search, filter, and sort playlists.
- Keyboard shortcuts for running everything with just the keyboard.
- Documentation in-application by right clicking buttons.

## Installation

### Windows EXE

You should be able to just download the windows exe in releases and run the application without python. See below for running in Python.

## Folders

In whichever place you keep the exe, it will create/check folders for files. Here's an explanation of each.

- **banners**: This folder is checked for the banners for ligning rounds. You can grab them from this repository, or just use your own as long as they have the same names.
- **files**: The following files are stored here.
  - **config.txt** Stores currently loaded playlist, index, and directory information.
  - **censors.txt** Stores all censors created for files. These are created outside of the application. My file is in the repository, and also the censor_bar_tool.py for help in creating them.
  - **youtube_links.txt** This is where youtbe links are read, then downloaded. I have an example file in the repository.
  - **youtube_archive.txt** Just a copy of any link read in the youtube_links.txt to keep a history.
- **filters**: Filters will be stored here.
- **metadata**: Metadata for files, anime, and youtube videos are stored here.
- **music**: Create this folder and place music files in it to have them play in the background of Frame and Clues lightning rounds.
- **playlists**: Saved playlists are stored here, including Tagged Themes, and Favorite Themes.
- **youtube**: This is where downloaded youtube videos will be stored. They are automatically deleted if remoed from the youtube_links.txt file.

### Python Requirements

Ensure you have the following installed:

- Python **3.10+**
- VLC Media Player (for video playback)
- Required dependencies from below.

## Dependencies

The project has a lot of features, including video playback, music playback, and even a function for getting the average color of the screen. Therefore there are quite a few dependencies that must be installed first:

```plaintext
os, ctypes, random, math, json, requests, re, dxcam, time, numpy, BytesIO, datetime,
tkinter, PIL (Pillow), threading, vlc, yt_dlp, pynput, pygame
```

