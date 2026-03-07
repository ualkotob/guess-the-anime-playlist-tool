# Guess The Anime - Playlist Tool

## Description

Guess The Anime - Playlist Tool is a comprehensive Python-based application designed for hosting anime trivia sessions. It features deep integration with AnimeThemes and Jikan APIs, VLC-powered video playback, and an extensive suite of lightning round modes. Perfect for anime clubs, stream entertainment, or personal anime knowledge testing.

## Core Features

### Video Playback & Sources
- **Local Files**: Play anime openings, endings, and video files from your computer
- **AnimeThemes Integration**: Stream directly from AnimeThemes.moe or download themes on-demand
- **YouTube Integration**: Add YouTube videos via a manager

### Lightning Round Modes

**20+ Unique Lightning Round Types:**

- **🗲 Regular**: Random 12-second clip from opening/ending
- **👁 Blind**: Audio-only mode (screen hidden)
- **👀 Peek**: Small viewport that grows or moves across the screen
- **📷 Frame**: Show 4 still frames from the video, revealed one at a time
- **📚 Cover**: Anime cover art revealed gradually
- **🌐 Image**: Random Google image search result revealed over time
- **👤 Character**: 4 character images revealed gradually
- **🔍 Clues**: Display anime statistics (year, score, rank, members)
- **𝕋 Title**: Letters randomly fill in to spell the anime title
- **📰 Synopsis**: Synopsis revealed word-by-word
- **❓ Trivia**: AI-generated trivia question about the anime (requires OpenAI API)
- **😄 Emoji**: 6 emojis representing the anime (requires OpenAI API)
- **🎵 Song**: Show song metadata with audio in final seconds
- **💿 OST**: Play a clip from the anime's soundtrack (requires YouTube API)
- **🔖 Tags**: Detailed genre tags revealed over time
- **📺 Episodes**: Display 6 episode titles revealed gradually
- **🎭 Names**: Show 6 character names revealed over time
- **🎬 Clip**: Play a random YouTube clip or trailer (requires YouTube API)
- **✨ Character Reveal**: Single character image revealed gradually
- **📝 Character Profile**: Character description and gender, image in final seconds
- **🔤 Character Name**: Letters fill in to spell character name
- **🎲 Variety**: Dynamic mix of all modes based on popularity

Each lightning round is fully customizable with adjustable timing, reveal patterns, and round length.

## Installation

### Windows Executable (Recommended)

Download the latest `.exe` from the [Releases](https://github.com/ualkotob/guess-the-anime-playlist-tool/releases) page. The executable is standalone and doesn't require Python installation.

**Requirements:**
- Windows 10 or later
- [VLC Media Player](https://www.videolan.org/vlc/) (required for video playback)
- (OPTIONAL) [FFmpeg](https://www.ffmpeg.org/) installed in system path for downloading YouTube videos and editing video files 

## Folder Edxplanation
- **files**: Configuration and data files
  - `config.txt` - Current playlist, index, and directory settings
  - `censors.json` - Censors for titles, and NSFW things
  - `settings.json` - Application settings and API keys
  
- **playlists**: Saved playlist files (`.json` format)
  - Includes system playlists: Tagged Themes, Favorite Themes, etc.
  
- **filters**: Saved filter configurations (`.json` format)

- **metadata**: Cached API responses for faster loading
  - Separate caches for AnimeThemes, Jikan, and YouTube data

- **banners**: Lightning round banner images (grab from repository or use custom)
  
- **music**: Background music for lightning rounds
  - Place any audio files here for background music to play during lightning rounds
  
- **youtube**: Auto-downloaded YouTube videos
  - Downloaded YouTube videos are stored here
