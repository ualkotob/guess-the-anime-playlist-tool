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

### Requirements

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

