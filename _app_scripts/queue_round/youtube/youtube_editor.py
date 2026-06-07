# YouTube Video Manager window.
import os
import re
import shutil
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, simpledialog

from yt_dlp import YoutubeDL

from core.game_state import state
import _app_scripts.queue_round.youtube.youtube_control as youtube_control
import _app_scripts.toggles.censors as censors
import _app_scripts.bonus.bonus_template_editor as bonus_template_editor
import _app_scripts.playback.ffmpeg_check as ffmpeg_check
import _app_scripts.playback.transport as transport
import _app_scripts.ui.windowing as windowing

BACKGROUND_COLOR = state.colors.BACKGROUND_COLOR

# Module-private window state (was a main-file global)
youtube_editor_window = None


def open_youtube_editor():
    global youtube_editor_window, youtube_page_offset
    
    # Pagination variables
    if 'youtube_page_offset' not in globals():
        youtube_page_offset = 0
    
    VIDEOS_PER_PAGE = 10

    youtube_metadata = state.metadata.youtube_metadata
    
    def youtube_editor_close():
        global youtube_editor_window, youtube_page_offset
        youtube_page_offset = 0
        youtube_editor_window.destroy()
        youtube_editor_window = None

    if youtube_editor_window:
        youtube_editor_close()
        return
    else:
        youtube_editor_window = tk.Toplevel()
        youtube_editor_window.title("YouTube Video Manager")
        youtube_editor_window.configure(bg=BACKGROUND_COLOR)
        windowing.get_window_position_and_setup(youtube_editor_window)
        youtube_editor_window.protocol("WM_DELETE_WINDOW", youtube_editor_close)
    
    font_big = ("Arial", 14)
    fg_color = "white"

    entry_widgets = []

    def refresh_ui():
        global youtube_page_offset
        for widget in youtube_editor_window.winfo_children():
            widget.destroy()
        entry_widgets.clear()
        
        active_videos = {k: v for k, v in youtube_metadata.get("videos", {}).items() if not v.get("archived")}

        # Sort by date_added (newest first), then by upload_date as fallback
        def get_sort_key_manager(item):
            video_id, video = item
            # Try to get date_added first, fallback to upload_date
            date_added = video.get("date_added")
            if date_added:
                try:
                    return datetime.fromisoformat(date_added)
                except (ValueError, TypeError):
                    pass
            
            # Fallback to upload_date
            upload_date = video.get("upload_date", "")
            if upload_date:
                try:
                    return datetime.strptime(upload_date, "%Y%m%d")
                except (ValueError, TypeError):
                    pass
            
            # If no valid dates, use a very old date so it appears last
            return datetime(1900, 1, 1)

        sorted_videos = sorted(active_videos.items(), key=get_sort_key_manager, reverse=True)
        
        # Calculate pagination
        total_videos = len(sorted_videos)
        total_pages = (total_videos + VIDEOS_PER_PAGE - 1) // VIDEOS_PER_PAGE if total_videos > 0 else 1
        current_page = (youtube_page_offset // VIDEOS_PER_PAGE) + 1
        
        # Ensure page offset is within bounds
        if youtube_page_offset >= total_videos and total_videos > 0:
            youtube_page_offset = max(0, total_videos - VIDEOS_PER_PAGE)
        
        start_idx = youtube_page_offset
        end_idx = min(start_idx + VIDEOS_PER_PAGE, total_videos)
        page_videos = sorted_videos[start_idx:end_idx]
        
        header_row = 0
        if total_pages > 1:
            def page_prev():
                global youtube_page_offset
                if youtube_page_offset >= VIDEOS_PER_PAGE:
                    youtube_page_offset -= VIDEOS_PER_PAGE
                    refresh_ui()
            
            def page_next():
                global youtube_page_offset
                if youtube_page_offset + VIDEOS_PER_PAGE < total_videos:
                    youtube_page_offset += VIDEOS_PER_PAGE
                    refresh_ui()
            
            # Previous button
            prev_btn = tk.Button(youtube_editor_window, text="◀ PREV", font=font_big, bg="black", fg=fg_color, 
                                command=page_prev, state="normal" if current_page > 1 else "disabled")
            prev_btn.grid(row=0, column=0, padx=4, pady=6)
            
            # Page info
            page_label = tk.Label(youtube_editor_window, text=f"Page {current_page}/{total_pages} ({total_videos} total)", 
                                font=font_big, bg=BACKGROUND_COLOR, fg=fg_color)
            page_label.grid(row=0, column=1, columnspan=4, padx=8, pady=6)
            
            # Next button
            next_btn = tk.Button(youtube_editor_window, text="NEXT ▶", font=font_big, bg="black", fg=fg_color,
                                command=page_next, state="normal" if current_page < total_pages else "disabled")
            next_btn.grid(row=0, column=5, padx=4, pady=6)
            
            header_row = 1
        
        # Column headers
        headers = ["Video ID", "Channel", "Title", "Start", "End", "Actions"]
        for col, header in enumerate(headers):
            tk.Label(youtube_editor_window, text=header.upper(), font=font_big, bg=BACKGROUND_COLOR, fg=fg_color).grid(row=header_row, column=col, padx=8, pady=6)

        for display_idx, (video_id, video) in enumerate(page_videos):
            video_row = display_idx + header_row + 1
            row_widgets = []

            tk.Label(youtube_editor_window, text=video_id, font=font_big, fg=fg_color, bg=BACKGROUND_COLOR).grid(row=video_row, column=0, padx=4, pady=4)

            # Channel name
            channel_id = video.get("channel_id")
            channel_name = youtube_metadata.get("channels", {}).get(channel_id, {}).get("name", "Unknown")
            tk.Label(youtube_editor_window, text=channel_name, font=font_big, fg=fg_color, bg=BACKGROUND_COLOR, width=15, anchor="w").grid(row=video_row, column=1, padx=4, pady=4)

            # Title (Entry)
            title_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)

            title_var = tk.StringVar(value=youtube_control.get_youtube_display_title(video))
            title_entry = tk.Entry(title_frame, textvariable=title_var, font=font_big, width=40, bg="#222", fg=fg_color, insertbackground=fg_color)
            title_entry.pack(side="left")

            title_frame.grid(row=video_row, column=2, padx=4, pady=4)

            start_var = tk.StringVar(value=str(video.get("start", 0)))
            end_var = tk.StringVar(value=str(video.get("end", 0) or video.get("duration")))

            def set_now(var):
                var.set(int(state.seek.projected_player_time / 1000))

            # Start time (Entry + NOW + REFRESH)
            start_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)
            start_entry = tk.Entry(start_frame, textvariable=start_var, font=font_big, width=4, justify="center", bg="#222", fg=fg_color, insertbackground=fg_color)
            start_entry.pack(side="left")

            tk.Button(
                start_frame,
                text="NOW",
                font=font_big,
                command=lambda v=start_var: set_now(v),
                bg="black",
                fg="white"
            ).pack(side="left", padx=2)

            start_frame.grid(row=video_row, column=3, padx=4)

            # End time (Entry + NOW + REFRESH)
            end_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)
            end_entry = tk.Entry(end_frame, textvariable=end_var, font=font_big, width=4, justify="center", bg="#222", fg=fg_color, insertbackground=fg_color)
            end_entry.pack(side="left")

            tk.Button(
                end_frame,
                text="NOW",
                font=font_big,
                command=lambda v=end_var: set_now(v),
                bg="black",
                fg="white"
            ).pack(side="left")

            end_frame.grid(row=video_row, column=4, padx=4)

            filepath = os.path.join("youtube", video["filename"])
            is_downloaded = os.path.exists(filepath)

            action_frame = tk.Frame(youtube_editor_window, bg=BACKGROUND_COLOR)

            # Define play/stream function
            def play_youtube_video(vid):
                save_all()
                state.playback.youtube_queue = youtube_control.get_youtube_metadata_from_index(key_id=vid)
                transport.play_video()

            def archive_this(vid=video_id):
                video = youtube_metadata["videos"][vid]
                video["archived"] = True
                video["archived_date"] = datetime.now().strftime("%Y-%m-%d")
                archive_folder = os.path.join("youtube", "archive")
                os.makedirs(archive_folder, exist_ok=True)
                old_path = os.path.join("youtube", video.get("filename", ""))
                new_path = os.path.join(archive_folder, video.get("filename", ""))
                if os.path.exists(old_path):
                    try:
                        shutil.move(old_path, new_path)
                    except Exception as e:
                        print(f"Error archiving file: {e}")
                youtube_control.save_youtube_metadata()
                youtube_editor_window.after(0, refresh_ui)

            def delete_this(vid=video_id):
                video = youtube_metadata["videos"].get(vid)
                if not video:
                    messagebox.showerror("Error", f"Video {vid} not found in metadata.")
                    return
                filename = video.get("filename", "")
                fpath = os.path.join("youtube", filename)
                filesize = os.path.getsize(fpath) / (1024 * 1024) if os.path.exists(fpath) else 0
                filesize_str = f"{filesize:.2f} MB"
                confirm_message = f"Delete video {vid}?\n\nFile: {filename}\nSize: {filesize_str}"
                if messagebox.askyesno("Confirm Delete (CANNOT BE UNDONE)", confirm_message, parent=youtube_editor_window):
                    youtube_metadata["videos"].pop(vid, None)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except Exception as e:
                            print(f"Failed to delete file {fpath}: {e}")
                    youtube_control.save_youtube_metadata()
                    youtube_editor_window.after(0, refresh_ui)

            btn_ref = [None]

            def open_actions_menu(event, vid=video_id, vid_data=video, dl=is_downloaded, sv=start_var, ev=end_var, tv=title_var, bref=btn_ref):
                url = f"https://www.youtube.com/watch?v={vid}"
                menu = tk.Menu(youtube_editor_window, tearoff=0, bg="#222", fg="white",
                               activebackground="#444", activeforeground="white", bd=0,
                               font=font_big)
                if dl:
                    menu.add_command(label="▶  Play Now", command=lambda: play_youtube_video(vid))
                else:
                    menu.add_command(label="▶  Stream Now", command=lambda: play_youtube_video(vid))
                    def _do_download(v=vid):
                        youtube_control.download_youtube_video(v, bref[0], refresh_ui)
                    menu.add_command(label="⬇  Download", command=_do_download)
                menu.add_separator()
                menu.add_command(label="🔗  Open in Browser", command=lambda: webbrowser.open(url))
                menu.add_separator()
                menu.add_command(label="⟳  Reset Title", command=lambda: tv.set(vid_data.get("title", "")))
                menu.add_command(label="⟳  Reset Start", command=lambda: sv.set(0))
                menu.add_command(label="⟳  Reset End",   command=lambda: ev.set(int(vid_data.get("duration", 0))))
                menu.add_separator()
                menu.add_command(label="📝  Edit Bonus Template", command=lambda v=vid: bonus_template_editor.open_youtube_bonus_template_editor(v))
                def _open_yt_censor_editor(v=vid, vd=vid_data):
                    _yt_fn = vd.get("filename", "")
                    censors.set_youtube_censors_for_file(_yt_fn, youtube_control.load_youtube_censors(v))
                    censors.open_censor_editor(filename=_yt_fn)
                menu.add_command(label="🚫  Edit Censors", command=_open_yt_censor_editor)
                menu.add_separator()
                if dl:
                    menu.add_command(label="📦  Archive", command=lambda: archive_this(vid))
                menu.add_command(label="❌  Delete", foreground="#f77", command=lambda: delete_this(vid))
                menu.post(event.x_root, event.y_root)

            btn_color = "#1a5c1a" if is_downloaded else "#1a3a5c"
            actions_btn = tk.Button(action_frame, text="ACTIONS ▾", font=font_big,
                                    bg=btn_color, fg="white",
                                    activebackground=btn_color, activeforeground="white",
                                    relief="flat", bd=0)
            actions_btn.bind("<Button-1>", open_actions_menu)
            actions_btn.pack(side="left", padx=2)
            btn_ref[0] = actions_btn

            action_frame.grid(row=video_row, column=5, padx=4)
            row_widgets.append(action_frame)
            # Store the widget row
            entry_widgets.append((video_id, [title_entry, start_frame, end_frame]))

        def save_all():
            for video_id, widgets in entry_widgets:
                title_entry = widgets[0]
                start_frame = widgets[1]
                end_frame = widgets[2]

                # Get values from within the nested frames
                start_entry = start_frame.winfo_children()[0]  # Entry is the first child
                end_entry = end_frame.winfo_children()[0]      # Entry is the first child

                title = title_entry.get().strip()
                start = start_entry.get().strip()
                end = end_entry.get().strip()

                video = youtube_metadata["videos"][video_id]
                video["custom_title"] = title if title != video["title"] else ""
                video["start"] = int(start)
                video["end"] = int(end)

            youtube_control.save_youtube_metadata()
            save_youtube_button.configure(text="SAVED!")
            state.widgets.root.after(300, lambda: save_youtube_button.configure(text="SAVE ALL"))

        def add_video_by_url():
            if not ffmpeg_check.ffmpeg_available:
                messagebox.showerror("FFmpeg Not Found", "FFmpeg is required to add YouTube videos. Please ensure FFmpeg is installed and accessible in your system PATH.")
                return
            add_video_button.configure(text="ADDING...(PLEASE WAIT)")
            url = simpledialog.askstring("Add YouTube Video", "Enter YouTube video URL:", parent=youtube_editor_window)
            if not url:
                add_video_button.configure(text="ADD VIDEO FROM URL")
                return
        
            video_id = youtube_control.extract_youtube_id_from_url(url)
            if not video_id:
                messagebox.showerror("Invalid URL", "Could not extract video ID from the URL.")
                add_video_button.configure(text="ADD VIDEO FROM URL")
                return
            url = f"https://www.youtube.com/watch?v={video_id}"

            if video_id in youtube_metadata.get("videos", {}):
                messagebox.showinfo("Duplicate", "This video already exists in the list.")
                add_video_button.configure(text="ADD VIDEO FROM URL")
                return
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'format': 'best',
            }

            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                # Ensure data structure is ready
                if "videos" not in youtube_metadata:
                    youtube_metadata["videos"] = {}
                if "channels" not in youtube_metadata:
                    youtube_metadata["channels"] = {}

                # Add channel info
                channel_id = info.get("channel_id")
                if channel_id:
                    youtube_metadata["channels"][channel_id] = {
                        "name": info.get("channel"),
                        "subscriber_count": info.get("channel_follower_count", 0)
                    }

                # Build filename and store video data
                sanitized_title = re.sub(r'[^A-Za-z0-9]', '', info["title"])
                filename = f"{video_id}-{sanitized_title}.mp4"

                youtube_metadata["videos"][video_id] = {
                    "title": info["title"],
                    "custom_title": "",  # editable title, empty means use default
                    "start": 0,
                    "end": 0,
                    "channel_id": channel_id,
                    "duration": info.get("duration", 0),
                    "view_count": info.get("view_count", 0),
                    "like_count": info.get("like_count", 0),
                    "upload_date": info.get("upload_date", ""),
                    "description": info.get("description", ""),
                    "thumbnail": info.get("thumbnail", ""),
                    "filename": filename,
                    "archived": False,
                    "archived_date": None,
                    "date_added": datetime.now().isoformat()
                }

                youtube_control.save_youtube_metadata()
                refresh_ui()

            except Exception as e:
                add_video_button.configure(text="ADD VIDEO FROM URL")
                messagebox.showerror("Error", f"Failed to add video: {e}")

        def open_archived_youtube_view():
            archive_window = tk.Toplevel()
            archive_window.title("Archived YouTube Videos")
            archive_window.configure(bg=BACKGROUND_COLOR)
            archive_window.geometry("950x600")
            windowing.get_window_position_and_setup(archive_window)

            # Scrollable frame setup
            canvas = tk.Canvas(archive_window, bg=BACKGROUND_COLOR, highlightthickness=0)
            scrollbar = tk.Scrollbar(archive_window, orient="vertical", command=canvas.yview)
            scroll_frame = tk.Frame(canvas, bg=BACKGROUND_COLOR)

            scroll_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Sort and filter archived videos
            archived_videos = {
                vid: v for vid, v in youtube_metadata.get("videos", {}).items()
                if v.get("archived")
            }
            sorted_videos = sorted(archived_videos.items(), key=lambda x: x[1].get("archived_date", ""))

            for idx, (video_id, video) in enumerate(sorted_videos):
                title = youtube_control.get_youtube_display_title(video)
                archive_date = video.get("archived_date", "Unknown")
                filename = video.get("filename", "")
                filepath = os.path.join("youtube", "archive", filename)
                size_label = ""

                if os.path.exists(filepath):
                    try:
                        size_mb = os.path.getsize(filepath) / 1024 / 1024
                        size_label = f" ({size_mb:.1f} MB)"
                    except:
                        pass

                row_frame = tk.Frame(scroll_frame, bg=BACKGROUND_COLOR)
                row_frame.grid(row=idx, column=0, sticky="w", padx=8, pady=6)

                # Video ID
                tk.Label(row_frame, text=video_id, width=12, font=font_big, bg=BACKGROUND_COLOR, fg="gray").pack(side="left", padx=6)

                # Title + Size
                tk.Label(row_frame, text=title + size_label, font=font_big, bg=BACKGROUND_COLOR, fg=fg_color, width=40, anchor="w").pack(side="left", padx=6)

                # Archive date
                tk.Label(row_frame, text=archive_date, font=font_big, bg=BACKGROUND_COLOR, fg="#aaa", width=12).pack(side="left", padx=6)

                # Restore Button
                def restore_this(vid=video_id):
                    video = youtube_metadata["videos"][vid]
                    video["archived"] = False
                    video.pop("archived_date", None)

                    old_path = os.path.join("youtube", "archive", video["filename"])
                    new_path = os.path.join("youtube", video["filename"])
                    if os.path.exists(old_path):
                        try:
                            shutil.move(old_path, new_path)
                            print(f"Restored file: {video['filename']}")
                        except Exception as e:
                            print(f"Failed to restore file: {e}")

                    archive_window.destroy()
                    youtube_control.save_youtube_metadata()
                    refresh_ui()

                tk.Button(row_frame, text="RESTORE", font=font_big, bg="green", fg="white", command=restore_this).pack(side="left", padx=4)

                # Delete Button
                def delete_this(vid=video_id):
                    if messagebox.askyesno("Confirm Delete", f"Delete video {vid}?", parent=archive_window):
                        video = youtube_metadata["videos"].pop(vid, None)
                        archive_path = os.path.join("youtube", "archive", video["filename"])
                        if os.path.exists(archive_path):
                            try:
                                os.remove(archive_path)
                                print(f"Deleted file: {archive_path}")
                            except Exception as e:
                                print(f"Failed to delete file: {e}")
                        archive_window.destroy()
                        youtube_control.save_youtube_metadata()
                        refresh_ui()

                tk.Button(row_frame, text="❌", font=font_big, fg="red", bg="black", command=delete_this).pack(side="left", padx=4)

        add_video_button = tk.Button(
            youtube_editor_window,
            text="ADD VIDEO FROM URL",
            font=font_big,
            bg="black",
            fg="white",
            command=add_video_by_url
        )
        add_video_button.grid(row=999, column=0, columnspan=2, pady=10)
        save_youtube_button = tk.Button(youtube_editor_window, text="SAVE ALL", font=font_big, command=save_all, bg="black", fg="white")
        save_youtube_button.grid(row=999, column=2, columnspan=2, pady=12)
        archived_count = sum(1 for v in youtube_metadata.get("videos", {}).values() if v.get("archived"))
        tk.Button(youtube_editor_window, text=f"SHOW ARCHIVED({archived_count})", font=font_big, command=open_archived_youtube_view, bg="black", fg="white").grid(row=999, column=3, columnspan=3, pady=12)

    refresh_ui()
