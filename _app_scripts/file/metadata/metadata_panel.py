# Metadata panel rendering (right-column renderer).
import re
import webbrowser
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog

import pyperclip

from core.game_state import state
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.streaming as streaming
import _app_scripts.file.web_server.web_server as web_server
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.utils as utils
import _app_scripts.queue_round.youtube.youtube_control as youtube_control
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.playlists.entry_paths as entry_paths
import _app_scripts.file.metadata.metadata_display as metadata_display
import _app_scripts.queue_round.youtube.youtube_ui as youtube_ui
import _app_scripts.playback.image_loader as image_loader
import _app_scripts.ui.lists as lists
import _app_scripts.data.metadata_io as metadata_io
import _app_scripts.information.information_popup as information_popup
import _app_scripts.theme.marks as playlist_marks

from _app_scripts.ui.scaling import scl

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------
stream_icon = '📶'


def _has_anilist_fallback(data, selected_extra_metadata):
    """Returns True if AniList data can fill in for a missing anidb field."""
    if selected_extra_metadata not in ("characters", "tags"):
        return False
    anilist_id = data.get("anilist")
    if not anilist_id or str(anilist_id) not in state.metadata.anilist_metadata:
        return False
    al = state.metadata.anilist_metadata[str(anilist_id)]
    if selected_extra_metadata == "characters":
        return bool(al.get("characters"))
    if selected_extra_metadata == "tags":
        return bool(al.get("tags"))
    return False

def update_extra_metadata(column=None):
    currently_playing = state.playback.currently_playing
    anilist_metadata = state.metadata.anilist_metadata
    right_column = state.widgets.right_column
    list_loaded = state.lists.list_loaded
    selected_extra_metadata = state.metadata_panel.selected_extra_metadata
    show_spoiler_tags = state.metadata_panel.show_spoiler_tags
    YOUTUBE_API_KEY = state.config.YOUTUBE_API_KEY
    if currently_playing.get("type") == "youtube":
        youtube_ui.show_youtube_playlist()
        return
    
    data = currently_playing.get("data")
    if column is None:
        column = right_column
    # Don't overwrite a loaded list — it will show metadata when the list is closed
    if column is right_column and not (not list_loaded or list_loaded in metadata_display.LISTS_TO_CLOSE):
        return
    if column is right_column and state.lists.current_list_title:
        state.lists.current_list_title = ""
        lists._insert_list_title_row(column)
    column.config(state=tk.NORMAL, wrap="word")
    column.delete(1.0, tk.END)
    extra_data = [
        "synopsis", "characters", "episode_info", "tags", "clips"
    ]
    column.insert(tk.END, "   ", "blank")
    if data:
        for e in extra_data:
            if selected_extra_metadata == e:
                bg=state.colors.HIGHLIGHT_COLOR
            else:
                bg="black"
            column.window_create(tk.END, window=tk.Button(column, text=(f"{e.upper().replace("EPISODE_INFO", "EPS").replace("CsHARACTERS", "")}"), font=("Arial", scl(11, "UI"), "bold", "underline"), command=lambda x=e: metadata_display.select_extra_metadata(x), padx=scl(2), bg=bg, fg="white"))
        column.insert(tk.END, "\n\n", "blank")
    if not data or selected_extra_metadata == "clips":
        filename = currently_playing.get("filename")
        if not filename:
            column.config(state=tk.DISABLED, wrap="word")
            return
        playlist_entry = currently_playing.get("playlist_entry", filename)
        filepath = entry_paths.get_file_path(playlist_entry) if playlist_entry else None
        
        status = cache_download.get_file_status(filename)
        is_cached = status["is_cached"]
        
        streaming.resolve_clips_for_data(data)
        links = [
            ["YOUTUBE CLIPS", "header", data and YOUTUBE_API_KEY],
            ["LOAD YOUTUBE CLIPS", streaming.load_random_clips, data and YOUTUBE_API_KEY and not streaming._cached_clips_links],
            ["YOUTUBE CLIP LIST", streaming.stream_clip, streaming._cached_clips_links],
            ["YOUTUBE OSTS", "header", data and YOUTUBE_API_KEY],
            ["LOAD YOUTUBE OSTS", lambda: streaming.load_random_clips(ost=True), data and YOUTUBE_API_KEY and not streaming._cached_ost_clips_links],
            ["YOUTUBE OST LIST", streaming.stream_clip, streaming._cached_ost_clips_links]
        ]
        def create_link_button(name, func, new_line=False, blank=True):
            b = tk.Button(
                column,
                text=name,
                command=func,
                padx=scl(2, "UI"), pady=scl(1, "UI"),
                bg="black", fg="white",
                font=("Arial", scl(12, "UI"))
            )
            column.window_create(tk.END, window=b)
            if new_line:
                column.insert(tk.END, "\n", "blank")
            elif blank:
                column.insert(tk.END, " ")
        
        first_line = True
        for name, command, show in links:
            if show:
                if command == "header":
                    if first_line:
                        first_line = False
                    else:
                        column.insert(tk.END, "\n\n", "blank")
                    column.insert(tk.END, name + ":", "bold")
                    column.insert(tk.END, "\n", "blank")
                else:
                    if name == "YOUTUBE CLIP LIST" or name == "YOUTUBE OST LIST":
                        if name == "YOUTUBE CLIP LIST":
                            clips_to_load = streaming._cached_clips_links
                        else:
                            clips_to_load = streaming._cached_ost_clips_links
                        for clip in clips_to_load:
                            title, video_id, channel_title = clip
                            url = f"https://www.youtube.com/watch?v={video_id}"
                            create_link_button(
                                "▶",
                                lambda v=video_id, t=title, c=channel_title: command(v, t, c),
                                blank=False
                            )
                            create_link_button(
                                "🔗",
                                lambda u=url: webbrowser.open(u),
                                blank=False
                            )
                            create_link_button(
                                "⎘",
                                lambda u=url: pyperclip.copy(u),
                                blank=False
                            )
                            column.insert(tk.END, f"{title} by {channel_title}\n", "white")
                    elif name == "⬇️DOWNLOAD":
                        dl_btn = tk.Button(
                            column,
                            text=name,
                            command=lambda: None,  # Set below
                            padx=scl(2, "UI"), pady=scl(1, "UI"),
                            bg="black", fg="white",
                            font=("Arial", scl(12, "UI"))
                        )
                        # If cached, move to directory; otherwise download
                        if is_cached:
                            dl_btn.config(command=lambda b=dl_btn, f=filename: cache_download.move_cached_file_to_directory(f, b))
                        else:
                            dl_btn.config(command=lambda b=dl_btn, f=filename: cache_download.download_animethemes_file(f, b))
                        column.window_create(tk.END, window=dl_btn)
                        column.insert(tk.END, " ")
                    else:
                        create_link_button(name, command)
    elif not data.get(selected_extra_metadata) and not _has_anilist_fallback(data, selected_extra_metadata):
        column.insert(tk.END, f"No {selected_extra_metadata.capitalize().replace('_info', 's')} data found.", "white")
    elif selected_extra_metadata == "synopsis":
        metadata_display.add_single_data_line(column, data, "", 'synopsis')
    elif selected_extra_metadata == "characters":
        # AniDB Characters
        anidb_groups = {
            "main": [],
            "secondary": [],
            "appears": []
        }

        for char in data.get("characters", []):
            role = char[0]
            name = char[1]
            image = char[2]
            gender = char[3] if len(char) > 3 else "Unknown"
            desc = char[4] if len(char) > 4 else ""

            # Store full character info
            entry = (name, image, gender, desc)

            if role == "m":
                anidb_groups["main"].append(entry)
            elif role == "s":
                anidb_groups["secondary"].append(entry)
            else:
                anidb_groups["appears"].append(entry)

        def create_anidb_image_popup(name, image_filename, gender, desc):
            def _popup():
                popup = tk.Toplevel()
                popup.title(name)
                popup.configure(bg="black")
                
                # Name
                tk.Label(popup, text=name, font=("Arial", scl(20), "bold", "underline"), bg="black", fg="white", anchor="center").pack(anchor="center", pady=(scl(10), 0))

                # Load image with error handling
                try:
                    tk_img = image_loader.load_image_from_url("https://cdn-eu.anidb.net/images/main/" + image_filename, size=(scl(700), scl(700)))
                    if tk_img:
                        label = tk.Label(popup, image=tk_img, bg="black")
                        label.image = tk_img  # Keep reference
                        label.pack(pady=scl(10))
                except Exception:
                    tk.Label(popup, text=f"[Image failed to load: {image_filename}]", 
                            font=("Arial", scl(12)), bg="black", fg="gray").pack(pady=scl(10))

                # Info section
                info_frame = tk.Frame(popup, bg="black")
                info_frame.pack(padx=scl(20), pady=(0, scl(20)), fill="both", expand=True)

                new_desc = f"Gender: {gender.capitalize()}. {desc.strip()}"
                if new_desc.strip():
                    tk.Label(info_frame, text="DESCRIPTION:", font=("Arial", scl(15), "bold", "underline"), bg="black", fg="white", anchor="w").pack(anchor="w", pady=(scl(10), 0))
                    
                    desc_frame = tk.Frame(info_frame, bg="black")
                    desc_frame.pack(fill="both", expand=True, pady=(scl(5), 0))
                    
                    scrollbar = tk.Scrollbar(desc_frame)
                    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                    
                    desc_text = tk.Text(desc_frame, wrap=tk.WORD, font=("Arial", scl(15)), 
                                       bg="black", fg="white", height=10, width=60,
                                       yscrollcommand=scrollbar.set)
                    desc_text.pack(side=tk.LEFT, fill="both", expand=True)
                    desc_text.insert("1.0", new_desc.strip())
                    desc_text.config(state=tk.DISABLED)
                    scrollbar.config(command=desc_text.yview)

            return _popup

        # Display AniDB Characters
        has_anidb_chars = any(anidb_groups.values())
        if has_anidb_chars:
            column.insert(tk.END, "ANIDB CHARACTERS:\n", "bold underline")
            
            anidb_headers = [
                ("Main Characters", anidb_groups["main"]),
                ("Supporting Characters", anidb_groups["secondary"]),
                ("Also Appears", anidb_groups["appears"]),
            ]

            for header, char_list in anidb_headers:
                if not char_list:
                    continue
                column.insert(tk.END, header.upper() + ":\n", "bold")
                for name, image, gender, desc in sorted(char_list, key=lambda x: x[0].lower()):
                    b = tk.Button(
                        column,
                        text=name,
                        command=create_anidb_image_popup(name, image, gender, desc),
                        padx=2, pady=1,
                        bg="black", fg="white",
                        font=("Arial", scl(12))
                    )
                    column.window_create(tk.END, window=b)
                    column.insert(tk.END, " ")
                column.insert(tk.END, "\n", "blank")
            column.insert(tk.END, "\n", "blank")
        
        # AniList Characters
        anilist_id = data.get("anilist")
        if anilist_id and str(anilist_id) in anilist_metadata:
            anilist_data = anilist_metadata[str(anilist_id)]
            anilist_chars = anilist_data.get("characters", [])
            
            if anilist_chars:
                column.insert(tk.END, "ANILIST CHARACTERS:\n", "bold underline")
                
                # Group by role
                anilist_groups = {
                    "MAIN": [],
                    "SUPPORTING": [],
                    "BACKGROUND": []
                }
                
                for char in anilist_chars:
                    role = char.get("role", "BACKGROUND")
                    if role in anilist_groups:
                        anilist_groups[role].append(char)
                
                def create_anilist_popup(char_data):
                    def _popup():
                        popup = tk.Toplevel()
                        popup.title(char_data.get("name", "Character"))
                        popup.configure(bg="black")
                        
                        # Character name
                        tk.Label(popup, text=char_data.get("name", "Unknown"), 
                                font=("Arial", scl(20), "bold", "underline"), 
                                bg="black", fg="white", anchor="center").pack(anchor="center", pady=(scl(10), 0))
                        
                        # Load character image with error handling
                        image_url = char_data.get("image")
                        if image_url:
                            try:
                                tk_img = image_loader.load_image_from_url(image_url, size=(scl(700), scl(700)))
                                if tk_img:
                                    label = tk.Label(popup, image=tk_img, bg="black")
                                    label.image = tk_img  # Keep reference
                                    label.pack(pady=scl(10))
                            except Exception:
                                tk.Label(popup, text="[Image failed to load]", 
                                        font=("Arial", scl(12)), bg="black", fg="gray").pack(pady=scl(10))
                        
                        # Info section
                        info_frame = tk.Frame(popup, bg="black")
                        info_frame.pack(padx=scl(20), pady=(scl(20), scl(20)), fill="both", expand=True)
                        
                        # Basic info
                        info_parts = []
                        if char_data.get("gender"):
                            info_parts.append(f"Gender: {char_data['gender']}")
                        if char_data.get("age"):
                            info_parts.append(f"Age: {char_data['age']}")
                        
                        if info_parts:
                            tk.Label(info_frame, text=" | ".join(info_parts), 
                                    font=("Arial", scl(13)), bg="black", fg="gray", 
                                    anchor="w").pack(anchor="w", pady=(0, scl(10)))
                        
                        # Voice Actors
                        voice_actors = char_data.get("voice_actors", [])
                        if voice_actors:
                            tk.Label(info_frame, text="VOICE ACTORS (JP):", 
                                    font=("Arial", scl(15), "bold", "underline"), 
                                    bg="black", fg="white", anchor="w").pack(anchor="w", pady=(0, scl(5)))
                            tk.Label(info_frame, text=", ".join(voice_actors), 
                                    font=("Arial", scl(13)), bg="black", fg="white", 
                                    anchor="w").pack(anchor="w", pady=(0, scl(10)))
                        
                        # Description
                        desc = char_data.get("description", "")
                        if desc:
                            # Remove HTML tags from description
                            desc_clean = re.sub(r'<[^>]+>', '', desc)
                            desc_clean = desc_clean.replace('&quot;', '"').replace('&amp;', '&')
                            
                            tk.Label(info_frame, text="DESCRIPTION:", 
                                    font=("Arial", scl(15), "bold", "underline"), 
                                    bg="black", fg="white", anchor="w").pack(anchor="w", pady=(0, scl(5)))
                            
                            desc_frame = tk.Frame(info_frame, bg="black")
                            desc_frame.pack(fill="both", expand=True, pady=(scl(5), 0))
                            
                            scrollbar = tk.Scrollbar(desc_frame)
                            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                            
                            desc_text = tk.Text(desc_frame, wrap=tk.WORD, font=("Arial", scl(13)), 
                                               bg="black", fg="white", height=10, width=60,
                                               yscrollcommand=scrollbar.set)
                            desc_text.pack(side=tk.LEFT, fill="both", expand=True)
                            desc_text.insert("1.0", desc_clean.strip())
                            desc_text.config(state=tk.DISABLED)
                            scrollbar.config(command=desc_text.yview)
                    
                    return _popup
                
                for role_name, char_list in [("Main Characters", anilist_groups["MAIN"]), 
                                             ("Supporting Characters", anilist_groups["SUPPORTING"]), 
                                             ("Background Characters", anilist_groups["BACKGROUND"])]:
                    if not char_list:
                        continue
                    
                    column.insert(tk.END, role_name.upper() + ":\n", "bold")
                    for char in char_list:
                        name = char.get("name", "Unknown")
                        b = tk.Button(
                            column,
                            text=name,
                            command=create_anilist_popup(char),
                            padx=2, pady=1,
                            bg="black", fg="white",
                            font=("Arial", scl(12))
                        )
                        column.window_create(tk.END, window=b)
                        column.insert(tk.END, " ")
                    column.insert(tk.END, "\n", "blank")
        
        # If no characters from either source
        if not has_anidb_chars and not (anilist_id and str(anilist_id) in anilist_metadata and anilist_metadata[str(anilist_id)].get("characters")):
            column.insert(tk.END, "No character data available.", "white")
    elif selected_extra_metadata == "episode_info":
        episodes = sorted(data.get("episode_info", []), key=lambda x: x[0])  # Sort by episode number
        for num, title in episodes:
            column.insert(tk.END, f"EPISODE {num}: ", "bold")
            column.insert(tk.END, f"{title}\n", "white")
    elif selected_extra_metadata == "tags":
        # AniDB Tags
        anidb_tags = sorted(data.get("tags", []), key=lambda x: (-x[1], x[0].lower()))  # Sort by score descending, then name
        if anidb_tags:
            column.insert(tk.END, "ANIDB TAGS:\n", "bold")
            display_tags = []
            for tag, score in anidb_tags:
                if score > 0:
                    display = f"{tag} ({score})"
                else:
                    display = tag
                display_tags.append(display.capitalize())
            column.insert(tk.END, f"{", ".join(display_tags)}.", "white")
            column.insert(tk.END, "\n\n", "blank")
        
        # AniList Tags
        anilist_id = data.get("anilist")
        if anilist_id and str(anilist_id) in anilist_metadata:
            anilist_data = anilist_metadata[str(anilist_id)]
            anilist_tags = anilist_data.get("tags", [])
            if anilist_tags:
                column.insert(tk.END, "ANILIST TAGS:", "bold")
                
                spoiler_count = sum(1 for tag in anilist_tags if tag.get("spoiler", False))
                
                if spoiler_count > 0:
                    button_text = f"Hide {spoiler_count} spoiler tag{'s' if spoiler_count != 1 else ''}" if show_spoiler_tags else f"Show {spoiler_count} spoiler tag{'s' if spoiler_count != 1 else ''}"
                    column.insert(tk.END, " ")
                    column.window_create(tk.END, window=tk.Button(
                        column, 
                        text=button_text, 
                        command=metadata_display.toggle_spoiler_tags, 
                        padx=scl(2), 
                        bg="black", 
                        fg="white"
                    ))
                
                column.insert(tk.END, "\n", "white")
                
                # Display tags in rank order (already sorted from AniList)
                display_tags = []
                for tag in anilist_tags:
                    is_spoiler = tag.get("spoiler", False)
                    
                    if is_spoiler and not show_spoiler_tags:
                        continue
                    
                    tag_name = tag.get("name", "")
                    rank = tag.get("rank", 0)
                    category = tag.get("category", "")
                    
                    # Format: TagName (Rank%) [Category]
                    display = f"{tag_name} ({rank}%)"
                    if category:
                        display += f" [{category}]"
                    if is_spoiler:
                        display += " *SPOILER"
                    
                    display_tags.append(display)
                
                if display_tags:
                    column.insert(tk.END, f"{'\n'.join(display_tags)}", "white")
                
                column.insert(tk.END, ".", "white")
        
        # If no tags from either source
        if not anidb_tags and not (anilist_id and str(anilist_id) in anilist_metadata and anilist_metadata[str(anilist_id)].get("tags")):
            column.insert(tk.END, "No tags available.", "white")
    column.config(state=tk.DISABLED, wrap="word")


def update_metadata():
    currently_playing = state.playback.currently_playing
    playlist = state.metadata.playlist
    anilist_metadata = state.metadata.anilist_metadata
    left_column = state.widgets.left_column
    popout_currently_playing = popout_window.popout_currently_playing
    try:
        filename = currently_playing.get("filename")
        if filename:
            data = currently_playing.get('data')
            metadata_display.reset_metadata()
            # count number of times file / series appears in playlist
            if playlist.get("infinite"):
                _pl      = playlist.get("playlist", [])
                _cur_idx = playlist.get("current_index", 0)
                _fp, _sp = metadata_display._calc_plays_info(filename, data, _pl, _cur_idx)

                left_column.insert(tk.END, "PLAYS: ", "bold")
                left_column.insert(tk.END, metadata_display._fmt_plays(_fp), "white")
                if _sp:
                    left_column.insert(tk.END, "  SERIES: ", "bold")
                    left_column.insert(tk.END, metadata_display._fmt_plays(_sp), "white")
                left_column.insert(tk.END, "\n\n", "blank")

            if data:
                metadata_display.add_single_data_line(left_column, data, "TITLE: ", 'title', True)
                metadata_display.add_single_data_line(left_column, data, "ENGLISH: ", 'eng_title', True)
                if data.get("synonyms"):
                    metadata_display.add_multiple_data_line(left_column, data, "SYNONYMS: ", "synonyms", True)
                if metadata_display.is_game(data):
                    metadata_display.add_single_data_line(left_column, data, "RELEASE DATE: ", "release", True)
                else:
                    metadata_display.add_single_data_line(left_column, data, "AIR: ", "aired", False)
                    metadata_display.add_single_data_line(left_column, data, ", ", "season", False, title_font="white")
                    metadata_display.add_field_total_button(left_column, metadata_display.get_all_matching_field("season", data.get("season")), blank=True, title=(data.get("season") or "").upper())
                metadata_display.add_single_data_line(left_column, data, "SCORE: ", 'score', False)
                if not metadata_display.is_game(data):
                    metadata_display.add_single_data_line(left_column, data, " (#", 'rank', False, title_font="white")
                if data.get("platforms"):
                    _reviews_num = metadata_display._safe_int(data.get("reviews", 0), 0)
                    _pop_display = data.get("popularity") or "N/A"
                    left_column.insert(tk.END, " REVIEWS: ", "bold")
                    left_column.insert(tk.END, f"{_reviews_num:,} (#{_pop_display})", "white")
                else:
                    _members_num = metadata_display._safe_int(data.get("members", 0), 0)
                    _pop_display = data.get("popularity") or "N/A"
                    left_column.insert(tk.END, ") ", "white")
                    left_column.insert(tk.END, "MEMBERS: ", "bold")
                    left_column.insert(tk.END, f"{_members_num:,} (#{_pop_display})", "white")
                
                anilist_id = data.get("anilist")
                if anilist_id and str(anilist_id) in anilist_metadata:
                    anilist_data = anilist_metadata[str(anilist_id)]
                    anilist_score = anilist_data.get("score")
                    anilist_popularity = anilist_data.get("popularity")
                    
                    if anilist_score or anilist_popularity:
                        left_column.insert(tk.END, "\n\n", "blank")
                        
                        # AniList Score with all rankings
                        if anilist_score:
                            left_column.insert(tk.END, "ANILIST SCORE: ", "bold")
                            score_str = f"{anilist_score}%"
                            rank_parts = []
                            if anilist_data.get("score_rank_season"):
                                rank_parts.append(f"#{anilist_data['score_rank_season']} Season")
                            if anilist_data.get("score_rank_year"):
                                rank_parts.append(f"#{anilist_data['score_rank_year']} Year")
                            if anilist_data.get("score_rank_all"):
                                rank_parts.append(f"#{anilist_data['score_rank_all']} All-Time")
                            if rank_parts:
                                score_str += f" ({' / '.join(rank_parts)})"
                            left_column.insert(tk.END, f"{score_str} ", "white")
                        
                        # AniList Popularity with all rankings
                        if anilist_popularity:
                            left_column.insert(tk.END, "MEMBERS: ", "bold")
                            pop_str = f"{anilist_popularity:,}"
                            rank_parts = []
                            if anilist_data.get("popularity_rank_season"):
                                rank_parts.append(f"#{anilist_data['popularity_rank_season']} Season")
                            if anilist_data.get("popularity_rank_year"):
                                rank_parts.append(f"#{anilist_data['popularity_rank_year']} Year")
                            if anilist_data.get("popularity_rank_all"):
                                rank_parts.append(f"#{anilist_data['popularity_rank_all']} All-Time")
                            if rank_parts:
                                pop_str += f" ({' / '.join(rank_parts)})"
                            left_column.insert(tk.END, f"{pop_str}", "white")
                        
                        left_column.insert(tk.END, "\n", "blank")
                
                left_column.insert(tk.END, "\n\n", "blank")
                if data.get("platforms"):
                    metadata_display.add_multiple_data_line(left_column, data, "PLATFORMS: ", 'platforms', True)
                    left_column.insert(tk.END, "TYPE: ", "bold")
                    left_column.insert(tk.END, f"{information_popup.get_format(data) or 'N/A'}", "white") 
                else:
                    left_column.insert(tk.END, "EPISODES: ", "bold")
                    left_column.insert(tk.END, f"{information_popup.get_episode_display(data, suffix='')}", "white")
                    left_column.insert(tk.END, " TYPE: ", "bold")
                    left_column.insert(tk.END, f"{information_popup.get_format(data) or 'N/A'}", "white") 
                metadata_display.add_single_data_line(left_column, data, " SOURCE: ", 'source', True)
                left_column.insert(tk.END, "TAGS: ", "bold")
                tags = information_popup.get_tags(data)
                for index, tag in enumerate(tags):
                    left_column.insert(tk.END, f"{tag}", "white")
                    if index < len(tags)-1:
                        left_column.insert(tk.END, ", ", "white")
                left_column.insert(tk.END, "\n\n", "blank")
                left_column.insert(tk.END, "STUDIOS: ", "bold")
                for index, studio in enumerate(data.get("studios", [])):
                    left_column.insert(tk.END, f"{studio}", "white")
                    metadata_display.add_field_total_button(left_column, metadata_display.get_filenames_from_studio(studio), blank = False, title=studio)
                    if index < len(data.get("studios"))-1:
                        left_column.insert(tk.END, ", ", "white")
                if data.get("series"):
                    left_column.insert(tk.END, "\n\n", "blank")
                    metadata_display.add_multiple_data_line(left_column, data, "SERIES: ", "series", False)
                    _series_val = data.get("series", "")
                    metadata_display.add_field_total_button(left_column, metadata_display.get_all_matching_field("series", _series_val), title=(", ".join(_series_val) if isinstance(_series_val, list) else str(_series_val or "")))

                update_series_song_information(data, data.get("mal"))

            update_extra_metadata()
                
            metadata_display.toggleColumnEdit(False)

            if popout_currently_playing:
                update_popout_currently_playling(data)
            if web_server.is_running():
                _is_game = metadata_display.is_game(data) if data else False
                _tags = information_popup.get_tags(data) if data else []
                _anilist_score_str = None
                _anilist_popularity_val = None
                _anilist_popularity_ranks = []
                _anilist_tags = []
                _anilist_characters = []
                if data:
                    _anilist_id = data.get("anilist")
                    if _anilist_id and str(_anilist_id) in anilist_metadata:
                        _al = anilist_metadata[str(_anilist_id)]
                        _al_score = _al.get("score")
                        if _al_score:
                            _rank_parts = []
                            if _al.get("score_rank_season"): _rank_parts.append(f"#{_al['score_rank_season']} Season")
                            if _al.get("score_rank_year"): _rank_parts.append(f"#{_al['score_rank_year']} Year")
                            if _al.get("score_rank_all"): _rank_parts.append(f"#{_al['score_rank_all']} All-Time")
                            _anilist_score_str = f"{_al_score}%" + (f" ({' / '.join(_rank_parts)})" if _rank_parts else "")
                        _al_pop = _al.get("popularity")
                        if _al_pop:
                            _anilist_popularity_val = _al_pop
                            if _al.get("popularity_rank_season"): _anilist_popularity_ranks.append(f"#{_al['popularity_rank_season']} Season")
                            if _al.get("popularity_rank_year"): _anilist_popularity_ranks.append(f"#{_al['popularity_rank_year']} Year")
                            if _al.get("popularity_rank_all"): _anilist_popularity_ranks.append(f"#{_al['popularity_rank_all']} All-Time")
                        _anilist_tags = _al.get("tags") or []
                        _anilist_characters = [
                            {
                                "name": c.get("name", ""),
                                "role": c.get("role", ""),
                                "gender": c.get("gender", "") or "",
                                "age": c.get("age", "") or "",
                                "vas": c.get("voice_actors", []),
                                "url": c.get("image", "") or "",
                                "desc": re.sub(r'<[^>]+>', '', c.get("description", "") or "").replace('&quot;', '"').replace('&amp;', '&').strip(),
                            }
                            for c in (_al.get("characters") or [])
                        ]
                _web_meta = {"filename": filename}
                if data:
                    _web_meta = {
                        "filename": filename,
                        "title": data.get("title"),
                        "eng_title": data.get("eng_title"),
                        "synonyms": data.get("synonyms") or [],
                        "is_game": bool(_is_game),
                        "aired": data.get("aired"),
                        "season": data.get("season"),
                        "release": data.get("release"),
                        "score": data.get("score"),
                        "rank": data.get("rank"),
                        "members": data.get("members"),
                        "popularity": data.get("popularity"),
                        "reviews": data.get("reviews"),
                        "platforms": data.get("platforms") or [],
                        "episodes": data.get("episodes"),
                        "format": information_popup.get_format(data),
                        "source": data.get("source"),
                        "tags": _tags,
                        "studios": data.get("studios") or [],
                        "series": data.get("series"),
                        "anilist_score": _anilist_score_str,
                        "anilist_popularity": _anilist_popularity_val,
                        "anilist_popularity_ranks": _anilist_popularity_ranks,
                        "synopsis": data.get("synopsis"),
                        "episode_info": [[e[0], e[1]] for e in (data.get("episode_info") or [])],
                        "anidb_tags": [[t[0], t[1]] for t in sorted((data.get("tags") or []), key=lambda x: (-x[1], x[0].lower()))],
                        "anidb_characters": [{"role": c[0], "name": c[1], "url": ("https://cdn-eu.anidb.net/images/main/" + c[2]) if len(c) > 2 and c[2] else "", "gender": c[3] if len(c) > 3 else "", "desc": c[4] if len(c) > 4 else ""} for c in (data.get("characters") or [])],
                        "anilist_tags": _anilist_tags,
                        "anilist_characters": _anilist_characters,
                        "mal_id": data.get("mal"),
                        "anidb_id": data.get("anidb"),
                        "anilist_id": data.get("anilist"),
                        "igdb_id": data.get("igdb"),
                        "igdb_slug": data.get("igdb_slug"),
                        "animethemes_slug": data.get("animethemes_slug"),
                        "cover": data.get("cover"),
                    }
                if playlist.get("infinite"):
                    _pl      = playlist.get("playlist", [])
                    _cur_idx = playlist.get("current_index", 0)
                    _fp, _sp = metadata_display._calc_plays_info(filename, data, _pl, _cur_idx)
                    _web_meta["file_plays"]   = _fp
                    _web_meta["series_plays"] = _sp  # None if no series matches
                if data:
                    _slug = data.get("slug")
                    _songs = data.get("songs") or []
                    _song = next((s for s in _songs if s.get("slug") == _slug), None)
                    _overall_suffix = metadata_display.overall_theme_num_display(filename) if filename else ""
                    _v_num_str = metadata_fetch.get_version_from_filename(filename) if filename else None
                    _v_num = int(_v_num_str) if _v_num_str and str(_v_num_str).isdigit() else None
                    _v_episodes = None
                    _v_flags = []
                    if _song:
                        _versions = _song.get("versions") or []
                        if _versions:
                            _ver = next((v for v in _versions if v.get("version") == _v_num), None)
                            if _ver is None and _v_num in (None, 1) and len(_versions) == 1:
                                _ver = _versions[0]
                            if _ver:
                                _v_episodes = _ver.get("episodes")
                                _v_flags = metadata_display._get_version_flags(_ver)
                        if not _v_episodes:
                            _v_episodes = _song.get("episodes")
                        if not _v_flags:
                            _v_flags = metadata_display._get_version_flags(_song)
                    _ct_artists = (_song.get("artist") or []) if _song else []
                    _web_meta["current_theme"] = {
                        "slug": _slug,
                        "overall_suffix": _overall_suffix,
                        "title": _song.get("title") if _song else None,
                        "favorited": bool(playlist_marks.check_favorited(filename)) if filename else False,
                        "artists": _ct_artists,
                        "artists_str": metadata_fetch.get_artists_string(_ct_artists, total=True),
                        "version": _v_num,
                        "episodes": _v_episodes,
                        "flags": _v_flags,
                        "file_props": metadata_display.get_file_props_label(filename) if filename else "",
                    }
                    # Add artist themes data for each artist in current theme
                    if _ct_artists:
                        _artist_themes_map = {}
                        for _artist in _ct_artists:
                            _artist_themes_map[_artist] = information_popup.get_artist_themes_data(_artist, filename, include_current=True)
                        _web_meta["current_theme"]["artist_themes"] = _artist_themes_map
                    _ct_studios = data.get("studios", []) or []
                    if _ct_studios:
                        _studio_entries_map = {}
                        _studio_total = 0
                        for _studio in _ct_studios:
                            _s_data = information_popup.get_studio_entries_data(_studio, filename, include_current=True)
                            _studio_entries_map[_studio] = _s_data
                            _studio_total += int(_s_data.get("entry_count", 0) or 0)
                        _web_meta["current_theme"]["studio_entries"] = _studio_entries_map
                        _web_meta["current_theme"]["studio_entry_total"] = _studio_total
                _web_meta["series_themes"] = metadata_display._build_web_series_themes(data, filename)
                web_server.push_metadata(_web_meta)
                playlist_marks._push_web_marks(filename)
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        state.controls.updating_metadata = False

def update_popout_currently_playling(data, clear=False):
    currently_playing = state.playback.currently_playing
    popout_currently_playing = popout_window.popout_currently_playing
    popout_currently_playing_extra = popout_window.popout_currently_playing_extra
    popout_show_metadata = state.popout.show_metadata
    popout_show_currently_playing = state.popout.show_currently_playing
    youtube_queue = state.playback.youtube_queue
    is_youtube = currently_playing.get("type") == "youtube"
    popout_currently_playing_extra.config(state=tk.NORMAL, wrap="word")
    popout_currently_playing_extra.delete(1.0, tk.END)
    if not clear and popout_show_metadata and popout_show_currently_playing:
        if is_youtube:
            title = youtube_control.get_youtube_display_title(data)
        else:
            title = metadata_display.get_display_title(data)
        japanese_title = data.get("title")
        slug = data.get("slug")
        # Handle YouTube videos or missing slug gracefully
        if slug:
            theme = utils.format_slug(slug)
        elif is_youtube:
            theme = "[YouTube]"
        else:
            theme = ""
        song = information_popup.get_song_string(data)
        tags = information_popup.get_tags_string(data)
        if is_youtube:
            studio = youtube_queue.get('name')
        else:
            studio = ", ".join(data.get("studios", []))
        type = information_popup.get_format(data)
        source = data.get("source")
        marks = metadata_display.get_file_marks(currently_playing.get("filename", ""))
        if data.get("platforms"):
            episodes = ", ".join(information_popup._shorten_platform(p) for p in data.get("platforms"))
            _reviews_num = metadata_display._safe_int(data.get("reviews", 0), 0)
            members = f"Reviews: {_reviews_num:,}"
            score = f"Score: {data.get("score")}" if data.get("score") else ""
        elif is_youtube:
            duration = data.get("duration")
            if duration:
                episodes = f"{utils.format_seconds(duration)}"
            else:
                episodes = "YouTube Video"
            members = f"Views: {data.get('view_count'):,}" if data.get('view_count') else ""
            score = f"Likes: {data.get('like_count'):,}" if data.get('like_count') else ""
        else:
            episodes = information_popup.get_episode_display(data)
            _members_num = metadata_display._safe_int(data.get("members", 0), 0)
            _pop_display = data.get("popularity") or "N/A"
            members = f"Members: {_members_num:,} (#{_pop_display})"
            score = f"Score: {data.get("score") or "N/A"} (#{data.get("rank") or "N/A"})"
        if metadata_display.is_game(data):
            aired = data.get("release")
        elif is_youtube:
            aired = f"{datetime.strptime(data.get("upload_date"), "%Y%m%d").strftime("%Y-%m-%d")}"
        else:
            aired = data.get("season")
        popout_currently_playing.configure(text=title)
        if is_youtube:
            popout_currently_playing_extra.insert(tk.END, f"Uploaded by {studio} ({data.get('subscriber_count', 0):,} subscribers)\n{japanese_title}\n{members} | {score} | {aired} | {episodes}", "white")
        else:
            popout_currently_playing_extra.insert(tk.END, f"{marks}{theme}{metadata_display.overall_theme_num_display(currently_playing.get('filename'))} | {song} | {aired}\n{score} | {japanese_title} | {members}\n{studio} | {tags} | {episodes} | {type} | {source}", "white")
        popout_currently_playing.configure(fg="white")
    elif popout_show_metadata and not popout_show_currently_playing:
        # Show placeholder when metadata is on but currently playing is hidden
        popout_currently_playing.configure(text="CLICK TO SHOW/HIDE INFO", fg="gray")
    else:
        popout_currently_playing.configure(text="", fg="white")
    popout_currently_playing_extra.config(state=tk.DISABLED)


SERIES_COLLAPSE_THRESHOLD = 20   # total themes across all anime in series before collapsing non-playing
SECTION_COLLAPSE_THRESHOLD = 8   # themes in one anime before collapsing non-playing section type

_collapsed_anime = set()     # str(anime_id) — collapsed series entries
_collapsed_sections = set()  # (str(mal_id), type_str) — collapsed OP/ED section headers

def _rerender_songs(scroll_to=None):
    currently_playing = state.playback.currently_playing
    d = currently_playing.get('data')
    if d:
        update_series_song_information(d, d.get('mal'), rerender=True, scroll_to=scroll_to)

def _auto_init_series_collapse(all_series_themes, playing_mal):
    """Auto-collapse non-playing anime entries if the series is large."""
    _collapsed_anime.clear()
    total_themes = sum(len(anime.get("songs", [])) for _, anime in all_series_themes)
    if total_themes > SERIES_COLLAPSE_THRESHOLD:
        for anime_id, _ in all_series_themes:
            if str(anime_id) != str(playing_mal):
                _collapsed_anime.add(str(anime_id))

def _auto_init_section_collapse(mal_key, theme_list, playing_slug):
    """Auto-collapse non-playing section type if the anime has many themes."""
    _collapsed_sections.discard  # don't clear all; only touch this anime's keys
    types_present = set(t.get("type") for t in theme_list)
    # Remove any old keys for this anime first
    for t in list(_collapsed_sections):
        if isinstance(t, tuple) and t[0] == mal_key:
            _collapsed_sections.discard(t)
    if len(theme_list) <= SECTION_COLLAPSE_THRESHOLD:
        return
    playing_type = None
    for theme in theme_list:
        if theme.get("slug") == playing_slug:
            playing_type = theme.get("type")
            break
    for t in types_present:
        if t != playing_type:
            _collapsed_sections.add((mal_key, t))

def update_series_song_information(data, mal, rerender=False, scroll_to=None):
    middle_column = state.widgets.middle_column
    middle_column.config(state=tk.NORMAL)
    middle_column.delete("1.0", tk.END)
    playing_mal = str(data.get("mal"))
    playing_slug = data.get("slug")
    scroll_anchor = None  # widget whose position we'll scroll to after render

    if not data.get("series"):
        if not rerender:
            _collapsed_anime.clear()
            _collapsed_sections.clear()
            _auto_init_section_collapse(str(mal), data.get("songs", []), playing_slug)
        update_song_information(data, mal, scroll_to=scroll_to, scroll_anchor_out=[])
    else:
        all_series_themes = metadata_display.get_all_theme_from_series(data)
        if len(all_series_themes) == 1:
            if not rerender:
                _collapsed_anime.clear()
                _collapsed_sections.clear()
                _auto_init_section_collapse(str(mal), data.get("songs", []), playing_slug)
            update_song_information(data, mal, scroll_to=scroll_to, scroll_anchor_out=[])
        else:
            if not rerender:
                _collapsed_sections.clear()
                _auto_init_series_collapse(all_series_themes, playing_mal)
                for anime_id, anime in all_series_themes:
                    if str(anime_id) == playing_mal:
                        _auto_init_section_collapse(str(anime_id), anime.get("songs", []), playing_slug)
                        break

            for i, (anime_id, anime) in enumerate(all_series_themes):
                aid_key = str(anime_id)
                is_collapsed = aid_key in _collapsed_anime

                def toggle_anime(key=aid_key):
                    _collapsed_anime.discard(key) if key in _collapsed_anime else _collapsed_anime.add(key)
                    _rerender_songs(scroll_to=key)

                btn = tk.Button(middle_column, text="▶" if is_collapsed else "▼",
                    borderwidth=0, pady=0, command=toggle_anime, bg="black", fg="white")
                middle_column.window_create(tk.END, window=btn)
                if scroll_to == aid_key:
                    scroll_anchor = btn
                header = f" {metadata_display.get_display_title(anime)} [{information_popup.get_format(anime)} / {anime.get('season')}]:\n"
                middle_column.insert(tk.END, header, "bold underline")

                if not is_collapsed:
                    slug = playing_slug if str(anime_id) == playing_mal else "SKIP"
                    anchor_out = []
                    update_song_information(anime, anime_id, slug, scroll_to=scroll_to, scroll_anchor_out=anchor_out)
                    if anchor_out and scroll_anchor is None:
                        scroll_anchor = anchor_out[0]

                if i < len(all_series_themes) - 1:
                    middle_column.insert(tk.END, "\n", "blank")
    middle_column.config(state=tk.DISABLED)
    if scroll_anchor is not None:
        middle_column.after_idle(lambda w=scroll_anchor: middle_column.see(middle_column.index(w)))

def update_song_information(data, mal, slug=None, scroll_to=None, scroll_anchor_out=None):
    middle_column = state.widgets.middle_column
    file_metadata = state.metadata.file_metadata
    extra_scroll = 0
    max_scroll = 3
    if not slug:
        slug = data.get("slug")
    theme_list = list(data.get("songs", []))
    mal_key = str(mal)

    # Also show any slugs that exist only as local files but aren't in the fetched songs list
    known_slugs = {t.get("slug") for t in theme_list}
    fm_entry = file_metadata.get(mal_key, {})
    local_only = []
    for slug_key in fm_entry.get("themes", {}):
        if slug_key not in known_slugs:
            s = slug_key[:2].upper()
            t_type = "OP" if s == "OP" else ("ED" if s == "ED" else "OTHER")
            local_only.append({
                "type": t_type,
                "slug": slug_key,
                "title": None,
                "artist": [],
                "episodes": None,
                "versions": [],
            })
    if local_only:
        def _slug_sort(s):
            import re as _re
            m = _re.match(r"([A-Z]+)(\d+)(.*)", s["slug"])
            if m:
                pre, num, var = m.groups()
                return (pre, bool(var), int(num))
            return ("ZZZ", True, 999999)
        local_only.sort(key=_slug_sort)
        theme_list = theme_list + local_only

    # Group themes by type while preserving order of first appearance
    sections = {}
    for theme in theme_list:
        t = theme.get("type", "OTHER")
        sections.setdefault(t, []).append(theme)

    first_section = True
    for type_str, type_themes in sections.items():
        sec_key = (mal_key, type_str)
        is_sec_collapsed = sec_key in _collapsed_sections

        if type_str == "OP":
            header_text = "OPENINGS"
        elif type_str == "ED":
            header_text = "ENDINGS"
        else:
            header_text = f"{type_str}S"

        if not first_section:
            middle_column.insert(tk.END, "\n", "blank")
        first_section = False

        def toggle_section(key=sec_key):
            _collapsed_sections.discard(key) if key in _collapsed_sections else _collapsed_sections.add(key)
            _rerender_songs(scroll_to=key)

        btn = tk.Button(middle_column, text="▶" if is_sec_collapsed else "▼",
            borderwidth=0, pady=0, command=toggle_section, bg="black", fg="white")
        middle_column.window_create(tk.END, window=btn)
        if scroll_to == sec_key and scroll_anchor_out is not None and not scroll_anchor_out:
            scroll_anchor_out.append(btn)
        middle_column.insert(tk.END, f"{header_text}:\n", "bold")

        if not is_sec_collapsed:
            for i, theme in enumerate(type_themes):
                version_count = add_op_ed(theme, middle_column, slug, data.get("title"), mal)
                if scroll_to is None:
                    if (extra_scroll and extra_scroll < max_scroll) or theme.get("slug") == slug:
                        extra_scroll += 1 + (version_count // 4)
                        if extra_scroll <= max_scroll:
                            middle_column.see("end-1c")
                if i < len(type_themes) - 1:
                    middle_column.insert(tk.END, "\n", "blank")


def _render_file_props(column, files, playing_f):
    """Render file property label (single file) or clickable buttons (multiple files)."""
    for f in files:
        props_label = metadata_display.get_file_props_label(f) or "[ALT]"
        if len(files) == 1:
            column.tag_configure("file_props_small", font=(None, scl(9, "UI")), foreground="white")
            column.insert(tk.END, " " + props_label, "file_props_small")
        else:
            is_playing = f == playing_f
            display_label = (props_label[0] + ">" + props_label[1:]) if is_playing else props_label
            column.window_create(tk.END, window=_create_theme_play_button(
                column,
                f,
                display_label,
                relief="flat",
                font=(None, scl(9, "UI"), "bold") if is_playing else (None, scl(9, "UI")),
            ))

def _refresh_current_theme_list():
    data = state.playback.currently_playing.get("data")
    if data:
        update_series_song_information(data, data.get("mal"), rerender=True)

def _create_theme_play_button(column, filename, text, **kwargs):
    btn = tk.Button(
        column,
        text=text,
        borderwidth=0,
        pady=0,
        command=lambda f=filename: metadata_display.play_video_from_filename(f),
        bg="black",
        fg="white",
        **kwargs,
    )
    btn.bind(
        "<Button-3>",
        lambda event, f=filename: lists._theme_context_menu(f, _refresh_current_theme_list),
    )
    return btn

def add_op_ed(theme, column, slug, title, mal_id):
    currently_playing = state.playback.currently_playing
    anime_metadata_overrides = state.metadata.anime_metadata_overrides
    anime_metadata = state.metadata.anime_metadata
    playlist = state.metadata.playlist
    theme_slug = theme.get("slug")
    song_title = theme.get("title")
    artist_list = theme.get("artist", [])
    episodes = theme.get("episodes")
    format = "white"
    versions = theme.get("versions", [])
    no_file_icon = "⁃"
    no_versions_icon = "    "

    if theme_slug == slug:
        format = "highlight"

    if not versions or len(versions) == 1:
        # For single version, use the version-specific filename, otherwise use theme filename
        if len(versions) == 1:
            filename = metadata_display.get_theme_filename(mal_id, theme_slug, versions[0].get('version'))
        else:
            filename = metadata_display.get_theme_filename(mal_id, theme_slug)
        # ▶ button or fallback
        if filename:
            column.window_create(tk.END, window=_create_theme_play_button(column, filename, get_filename_icon(filename)))
            column.insert(tk.END, metadata_display.get_file_marks(filename), format)
        else:
            column.insert(tk.END, no_file_icon, format)
    else:
        # Multiple versions - no play button at top
        column.insert(tk.END, no_file_icon, format)

    overall_display = ""
    filename = metadata_display.get_theme_filename(mal_id, theme_slug)
    if filename:
        overall_display = metadata_display.overall_theme_num_display(filename)
    if theme_slug == slug:
        format = "highlight"
    column.insert(tk.END, f"{theme_slug}{overall_display}: {song_title if song_title else '????'}\n", format)

    # Artist section
    column.insert(tk.END, "by: ", format)
    if not artist_list:
        column.insert(tk.END, "N/A ", format)

        # Add [+] button to insert missing artist
        def prompt_and_add_artist():
            artist_input = simpledialog.askstring("Add Artist", "Enter artist name(s)(Use '[AND]' to separate multiple artists.):")
            if not artist_input:
                return
            
            artist_input = artist_input.split("[AND]")

            theme["artist"] = artist_input

            # Update override metadata
            anime_entry_override = anime_metadata_overrides.setdefault(mal_id, {})
            for entry in anime_metadata[mal_id]["songs"]:
                if entry.get("slug") == theme_slug:
                    break
            else:
                messagebox.showerror("Error", "Could not find original theme entry.")
                return

            # Copy the original song and override the artist
            new_song = {"slug": theme_slug}
            new_song["artist"] = artist_input

            # Replace or insert the song into the override
            override_songs = anime_entry_override.setdefault("songs", [])
            for i, s in enumerate(override_songs):
                if s.get("slug") == theme_slug:
                    override_songs[i] = new_song
                    break
            else:
                override_songs.append(new_song)

            # Also update main metadata live
            for s in anime_metadata[mal_id]["songs"]:
                if s.get("slug") == theme_slug:
                    s["artist"] = [artist_input]
            metadata_io.save_metadata_overrides()
            metadata_io.save_metadata()
            filename = currently_playing.get("filename")
            if filename:
                update_series_song_information(metadata_fetch.get_metadata(filename), mal_id)
        if playlist.get("name") in ["Tagged Themes", "New Themes"]:
            column.window_create(tk.END, window=tk.Button(column, text="[ADD ARTIST]", command=prompt_and_add_artist, padx=2, bg="black", fg="white"))
    else:
        for index, artist in enumerate(artist_list):
            column.insert(tk.END, f"{artist}", format)
            if theme_slug == slug:
                metadata_display.add_field_total_button(column, metadata_display.get_filenames_from_artist(artist), blank=False, title=artist)
            if index < len(artist_list) - 1:
                column.insert(tk.END, ", ", format)

    # Versions or Episodes + Flags
    version_format = "white"
    if versions:
        if len(versions) == 1:
            version_format = format
            version = versions[0]
            version_num = version.get('version')
            version_text = ""
            if version_num and version_num != 1:
                version_text += f"v{version_num}: "
            if version.get('episodes'):
                version_text += f"(Eps: {version.get('episodes')})"
            flags = metadata_display._get_version_flags(version)
            if flags:
                version_text += f" {' '.join(flags)}"
            if version_text:
                column.insert(tk.END, f"\n{version_text}", format)
            all_ver_files = metadata_display.get_theme_filenames(mal_id, theme_slug, version_num)
            if all_ver_files:
                if not version_text:
                    column.insert(tk.END, "\n", format)
                _render_file_props(column, all_ver_files, currently_playing.get('filename'))
        else:
            # Multiple versions - display with individual play buttons
            for i, version in enumerate(versions):
                column.insert(tk.END, "\n", version_format if i > 0 else format)
                version_num = version.get('version')
                version_filename = metadata_display.get_theme_filename(mal_id, theme_slug, version_num, need_version=True)
                if version_num == 1 and not version_filename:
                    version_filename = metadata_display.get_theme_filename(mal_id, theme_slug, None, need_version=True)
                if version_num is None:
                    version_num = 1

                version_format = "white"
                if theme_slug == slug and version_filename and int(metadata_fetch.get_version_from_filename(currently_playing.get('filename'))) == version_num:
                    version_format = "highlight"

                if version_filename:
                    column.window_create(tk.END, window=_create_theme_play_button(column, version_filename, get_filename_icon(version_filename)))
                    column.insert(tk.END, metadata_display.get_file_marks(version_filename), version_format)
                else:
                    column.insert(tk.END, no_versions_icon, version_format)

                version_text = f"v{version_num}" if version_num else ""
                flags = metadata_display._get_version_flags(version)
                if version.get("episodes") or flags:
                    version_text += ":"
                    if version.get('episodes'):
                        version_text += f" (Eps: {version.get('episodes')})"
                    if flags:
                        version_text += f" {' '.join(flags)}"
                column.insert(tk.END, version_text, version_format)
                all_ver_files = metadata_display.get_theme_filenames(mal_id, theme_slug, version_num, need_version=True)
                _render_file_props(column, all_ver_files, currently_playing.get('filename'))
        column.insert(tk.END, "", "white")
    else:
        version_text = ""
        if episodes:
            version_text += f"(Eps: {episodes})"
        flags = metadata_display._get_version_flags(theme)
        if flags:
            version_text += f" {' '.join(flags)}"
        if version_text:
            column.insert(tk.END, f"\n{version_text}", format)
        all_theme_files = metadata_display.get_theme_filenames(mal_id, theme_slug)
        if all_theme_files:
            if not version_text:
                column.insert(tk.END, "\n", format)
            _render_file_props(column, all_theme_files, currently_playing.get('filename'))

    if theme.get("special"):
        column.insert(tk.END, " (SPECIAL)", format)

    column.insert(tk.END, "\n", version_format)
    return len(versions)

def get_filename_icon(filename):
    directory_files = state.metadata.directory_files
    if filename in directory_files:
        return "▶"
    elif cache_download.is_animethemes_stream_file(filename):
        return stream_icon
    else:
        return "❌"
