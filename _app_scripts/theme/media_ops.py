"""Per-file media operations: delete, open-folder, rename, volume edit,
format conversion, and time-based cutting of individual video files.

Extracted from playlist.py. These act on single files in the directory
(via the OS / ffmpeg) rather than on playlist structure; the only shared
playlist state they touch is the deduplicated-files cache, invalidated
through playlist.invalidate_deduplicated_cache().
"""
import os
import platform
import subprocess

from tkinter import messagebox, simpledialog

from core.game_state import state
import _app_scripts.file.metadata.metadata_fetch as metadata_fetch
import _app_scripts.playback.cache_download as cache_download
import _app_scripts.playback.transport as transport
import _app_scripts.file.metadata.metadata_panel as metadata_panel
import _app_scripts.data.config_io as config_io
import _app_scripts.data.metadata_io as metadata_io
import _app_scripts.playlists.playlist as playlist


def delete_file_by_filename(filename):
    """Find the full path from directory_files and delete the file after confirmation."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Delete File",
                             f"The file does not exist or is not found:\n{filename}")
        return

    confirm = messagebox.askyesno("Delete File",
                                   f"Are you sure you want to delete this file?\n\n{filename}")
    if confirm:
        try:
            transport.stop()

            file_data = metadata_fetch.get_file_metadata_by_name(filename)

            os.remove(filepath)
            print(f"Deleted file: {filename}")
            del directory_files[filename]
            playlist.invalidate_deduplicated_cache()

            file_metadata = state.metadata.file_metadata
            metadata_updated = False
            if file_data and not cache_download.is_animethemes_stream_file(filename):
                mal_id = file_data.get("mal")
                slug = file_data.get("slug")
                version = str(file_data.get("version")) if file_data.get("version") is not None else "null"

                if mal_id and slug and mal_id in file_metadata:
                    themes = file_metadata[mal_id].get("themes", {})
                    if slug in themes and version in themes[slug] and filename in themes[slug][version]:
                        del themes[slug][version][filename]
                        metadata_updated = True

                        if not themes[slug][version]:
                            del themes[slug][version]
                        if not themes[slug]:
                            del themes[slug]

            if metadata_updated:
                metadata_fetch.build_filename_to_mal_map()
                metadata_io.save_metadata()

            currently_playing = state.playback.currently_playing
            if currently_playing and currently_playing.get("filename") == filename:
                state.widgets.root.after(100, lambda: metadata_panel.update_extra_metadata())

        except Exception as e:
            messagebox.showerror("Error", f"Could not delete file:\n{e}")
    else:
        print(f"Deletion canceled for file: {filename}")


def open_file_folder_by_filename(filename):
    """Find the full path from directory_files and open its containing folder."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Open Folder",
                             f"The file does not exist or is not found:\n{filename}")
        return

    try:
        if platform.system() == "Windows":
            subprocess.run(["explorer", "/select,", os.path.normpath(filepath)])
        elif platform.system() == "Darwin":
            subprocess.run(["open", "-R", filepath])
        else:
            subprocess.run(["xdg-open", os.path.dirname(filepath)])
        print(f"Opened folder for: {filename}")
    except Exception as e:
        messagebox.showerror("Error", f"Could not open folder:\n{e}")


def rename_file_by_filename(filename):
    """Rename a file and update all relevant metadata and directory references."""
    directory_files = state.metadata.directory_files
    file_metadata = state.metadata.file_metadata
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Rename File",
                             f"The file does not exist or is not found:\n{filename}")
        return

    current_base, extension = os.path.splitext(filename)
    new_base = simpledialog.askstring("Rename File",
                                      "Enter new filename (without extension):",
                                      initialvalue=current_base)

    if not new_base:
        return

    new_base = new_base.strip()
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    if any(char in new_base for char in invalid_chars):
        messagebox.showerror("Invalid Name",
                             f"Filename cannot contain: {' '.join(invalid_chars)}")
        return

    new_filename = new_base + extension
    directory = os.path.dirname(filepath)
    new_filepath = os.path.join(directory, new_filename)

    if new_filename in directory_files and new_filename != filename:
        messagebox.showerror("Rename Error",
                             f"A file with the name '{new_filename}' already exists in the directory list.")
        return

    if os.path.exists(new_filepath) and new_filepath != filepath:
        messagebox.showerror("Rename Error", f"A file already exists at:\n{new_filepath}")
        return

    currently_playing = state.playback.currently_playing
    if currently_playing.get("filename") == filename:
        transport.stop()

    try:
        os.rename(filepath, new_filepath)

        if filename in directory_files:
            del directory_files[filename]
        directory_files[new_filename] = new_filepath
        playlist.invalidate_deduplicated_cache()

        file_data = metadata_fetch.get_file_metadata_by_name(filename)
        if file_data:
            mal_id = file_data.get("mal")
            slug = file_data.get("slug")
            version = str(file_data.get("version")) if file_data.get("version") is not None else "null"

            if mal_id and slug and mal_id in file_metadata:
                themes = file_metadata[mal_id].get("themes", {})
                if slug in themes and version in themes[slug]:
                    if filename in themes[slug][version]:
                        themes[slug][version][new_filename] = themes[slug][version][filename]
                        del themes[slug][version][filename]
                        metadata_fetch.build_filename_to_mal_map()

        playlist_data = state.metadata.playlist
        if playlist_data and playlist_data.get("playlist"):
            for i, playlist_file in enumerate(playlist_data["playlist"]):
                clean_playlist_file = playlist_file[3:] if playlist_file.startswith("[L]") else playlist_file
                if clean_playlist_file == filename:
                    prefix = "[L]" if playlist_file.startswith("[L]") else ""
                    playlist_data["playlist"][i] = prefix + new_filename

        if currently_playing.get("filename") == filename:
            currently_playing["filename"] = new_filename
            if "playlist_entry" in currently_playing:
                old_entry = currently_playing["playlist_entry"]
                prefix = "[L]" if old_entry.startswith("[L]") else ""
                currently_playing["playlist_entry"] = prefix + new_filename

        metadata_io.save_metadata()
        config_io.save_config()

        if currently_playing.get("filename") == new_filename:
            metadata_panel.update_metadata()
        print(f"Renamed '{filename}' to '{new_filename}'")

    except Exception as e:
        messagebox.showerror("Rename Error", f"Failed to rename file:\n{e}")
        print(f"Error renaming file: {e}")


def edit_file_volume_by_filename(filename):
    """Find the full path from directory_files and edit the volume using ffmpeg."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("Edit Volume",
                             f"The file does not exist or is not found:\n{filename}")
        return

    volume_str = simpledialog.askstring(
        "Edit Volume",
        "Enter volume multiplier (e.g., 0.5 for half volume, 2.0 for double volume):\n\n"
        "Examples:\n• 0.5 = 50% volume\n• 1.0 = original volume\n• 2.0 = 200% volume",
        initialvalue="1.0",
    )

    if not volume_str:
        return

    try:
        volume_level_set = float(volume_str)
        if volume_level_set <= 0:
            messagebox.showerror("Invalid Volume", "Volume level must be greater than 0")
            return
    except ValueError:
        messagebox.showerror("Invalid Volume",
                             "Please enter a valid number (e.g., 0.5, 1.0, 2.0)")
        return

    confirm = messagebox.askyesno(
        "Edit Volume",
        f"This will modify the volume of:\n{filename}\n\n"
        f"Volume multiplier: {volume_level_set}\n\n"
        "The video will be stopped and the original file will be replaced.\nContinue?",
    )
    if not confirm:
        return

    transport.stop()
    base, ext = os.path.splitext(filepath)
    temp_filepath = f"{base}_temp_volume{ext}"

    try:
        ffmpeg_cmd = [
            "ffmpeg", "-i", filepath,
            "-af", f"volume={volume_level_set}",
            "-c:v", "copy", "-y", temp_filepath,
        ]

        result = subprocess.run(
            ffmpeg_cmd, capture_output=True, text=True,
            encoding='utf-8', errors='ignore', timeout=300,
        )

        if result.returncode == 0:
            if os.path.exists(temp_filepath):
                os.remove(filepath)
                os.rename(temp_filepath, filepath)
                messagebox.showinfo(
                    "Volume Edited",
                    f"Successfully edited volume:\n{filename}\n\nVolume multiplier: {volume_level_set}x",
                )
                print(f"Successfully edited volume for: {filename} (volume: {volume_level_set}x)")
            else:
                messagebox.showerror("Error", "Temporary file was not created successfully")
        else:
            try:
                error_msg = result.stderr if result.stderr else "Unknown ffmpeg error"
            except UnicodeDecodeError:
                error_msg = "FFmpeg error (unable to decode error message)"
            messagebox.showerror("FFmpeg Error", f"Failed to edit volume:\n\n{error_msg}")
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)

    except subprocess.TimeoutExpired:
        messagebox.showerror("Timeout",
                             "Operation timed out. The file may be too large or ffmpeg is not responding.")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
    except FileNotFoundError:
        messagebox.showerror(
            "FFmpeg Not Found",
            "FFmpeg is not installed or not found in PATH.\n\n"
            "Please install FFmpeg and ensure it's available in your system PATH.",
        )
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while editing volume:\n{e}")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)


def convert_file_format_by_filename(filename):
    """Convert a file to a different format using ffmpeg."""
    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)

    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("File Not Found",
                             f"The file does not exist or is not found:\n{filename}")
        return

    format_str = simpledialog.askstring(
        "Convert Format",
        "Enter output format (file extension):\n\n"
        "Examples:\n• mp4\n• webm\n• mkv\n• avi\n• mov\n• mp3\n• wav\n\n"
        "Enter format without the dot:",
        initialvalue="webm",
    )

    if not format_str:
        return

    output_format = format_str.strip().lower()
    if output_format.startswith('.'):
        output_format = output_format[1:]

    base, _ = os.path.splitext(filepath)
    output_filepath = f"{base}.{output_format}"

    confirm = messagebox.askyesno(
        "Convert Format",
        f"This will convert:\n{filename}\n\nTo format: {output_format.upper()}\n"
        f"Output file: {os.path.basename(output_filepath)}\n\nContinue?",
    )
    if not confirm:
        return

    transport.stop()

    try:
        if output_format in ['mp4', 'mov']:
            video_codec = "libx264"
            audio_codec = "aac"
            audio_settings = ["-b:a", "256k"]
            video_settings = ["-crf", "18"]
        elif output_format == 'webm':
            video_codec = "libvpx-vp9"
            audio_codec = "libopus"
            audio_settings = ["-b:a", "128k"]
            video_settings = ["-crf", "25", "-b:v", "0"]
        elif output_format in ['mkv', 'avi']:
            video_codec = "libx264"
            audio_codec = "aac"
            audio_settings = ["-b:a", "256k"]
            video_settings = ["-crf", "18"]
        elif output_format == 'mp3':
            video_codec = None
            audio_codec = "libmp3lame"
            audio_settings = ["-b:a", "320k"]
            video_settings = []
        elif output_format == 'wav':
            video_codec = None
            audio_codec = "pcm_s16le"
            audio_settings = []
            video_settings = []
        elif output_format in ['ogg', 'oga']:
            video_codec = None
            audio_codec = "libvorbis"
            audio_settings = ["-q:a", "8"]
            video_settings = []
        else:
            video_codec = None
            audio_codec = None
            audio_settings = ["-b:a", "256k"]
            video_settings = []

        ffmpeg_cmd = ["ffmpeg", "-i", filepath]

        if video_codec:
            ffmpeg_cmd.extend(["-c:v", video_codec])
            if output_format == 'webm':
                ffmpeg_cmd.extend(["-deadline", "best", "-cpu-used", "0"])
            else:
                ffmpeg_cmd.extend(["-preset", "slow"])
            ffmpeg_cmd.extend(video_settings)
        elif video_codec is None and output_format not in ['mp3', 'wav', 'ogg', 'oga']:
            ffmpeg_cmd.extend(["-c:v", "copy"])

        if audio_codec:
            ffmpeg_cmd.extend(["-c:a", audio_codec])
            ffmpeg_cmd.extend(audio_settings)
        elif audio_codec is None:
            ffmpeg_cmd.extend(["-c:a", "copy"])

        if output_format in ['mp3', 'wav', 'ogg', 'oga']:
            ffmpeg_cmd.extend(["-vn"])

        ffmpeg_cmd.extend(["-y", output_filepath])

        print(f"Converting {filename} to {output_format.upper()} format...")
        result = subprocess.run(ffmpeg_cmd, text=True, encoding='utf-8', errors='ignore')

        if result.returncode == 0 and os.path.exists(output_filepath):
            messagebox.showinfo("Conversion Complete",
                                f"File converted successfully!\nSaved as: {os.path.basename(output_filepath)}")
            print(f"Conversion completed successfully: {os.path.basename(output_filepath)}")

            try:
                if platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", os.path.normpath(output_filepath)])
                elif platform.system() == "Darwin":
                    subprocess.run(["open", "-R", output_filepath])
                else:
                    subprocess.run(["xdg-open", os.path.dirname(output_filepath)])
            except Exception as e:
                print(f"Could not open folder: {e}")

            replace = messagebox.askyesno(
                "Replace Original",
                f"Do you want to replace the original file with the converted version?\n\n"
                f"Original: {filename}\nConverted: {os.path.basename(output_filepath)}\n\n"
                "This cannot be undone!",
            )

            if replace:
                try:
                    os.remove(filepath)
                    original_base, _ = os.path.splitext(filepath)
                    new_original_path = f"{original_base}.{output_format}"
                    os.rename(output_filepath, new_original_path)

                    original_base_name, old_ext = os.path.splitext(filename)
                    new_filename = f"{original_base_name}.{output_format}"

                    if filename in directory_files:
                        del directory_files[filename]
                        directory_files[new_filename] = new_original_path
                    playlist.invalidate_deduplicated_cache()

                    file_metadata = state.metadata.file_metadata
                    file_data = metadata_fetch.get_file_metadata_by_name(filename)
                    if file_data:
                        mal_id = file_data.get("mal")
                        slug = file_data.get("slug")
                        version = str(file_data.get("version")) if file_data.get("version") is not None else "null"

                        if mal_id and slug and mal_id in file_metadata:
                            themes = file_metadata[mal_id].get("themes", {})
                            if slug in themes and version in themes[slug]:
                                if filename in themes[slug][version]:
                                    themes[slug][version][new_filename] = themes[slug][version][filename]
                                    del themes[slug][version][filename]
                                    metadata_fetch.build_filename_to_mal_map()

                    playlist_data = state.metadata.playlist
                    if playlist_data and playlist_data.get("playlist"):
                        for i, playlist_file in enumerate(playlist_data["playlist"]):
                            if playlist_file == filename:
                                playlist_data["playlist"][i] = new_filename

                    metadata_io.save_metadata()
                    config_io.save_config()

                    messagebox.showinfo("File Replaced",
                                       f"Original file has been replaced with the converted version.\n"
                                       f"Metadata updated for: {new_filename}")
                    print(f"Replaced {filename} with converted {output_format.upper()} version")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to replace original file:\n{e}")
        else:
            print(f"FFmpeg conversion failed with return code {result.returncode}")
            messagebox.showerror("Conversion Error",
                                 f"Failed to convert file to {output_format.upper()} format.\n\n"
                                 "Check the console for detailed error information.")
            if os.path.exists(output_filepath):
                os.remove(output_filepath)

    except subprocess.TimeoutExpired:
        messagebox.showerror("Timeout",
                             "Conversion timed out after 15 minutes.")
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
    except FileNotFoundError:
        messagebox.showerror("FFmpeg Not Found",
                             "FFmpeg is not installed or not found in PATH.\n\n"
                             "Please install FFmpeg and ensure it's available in your system PATH.")
    except Exception as e:
        messagebox.showerror("Error",
                             f"An unexpected error occurred during conversion:\n\n{str(e)}")
        if os.path.exists(output_filepath):
            os.remove(output_filepath)


def _cut_video_at_time(filename, cut_mode):
    """Shared helper to cut video before or after current time using FFmpeg."""
    if not state.widgets.player.get_media():
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title,
                             "No video is currently loaded. Please load a video first.")
        return

    current_time_ms = state.widgets.player.get_time()
    if current_time_ms <= 0:
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title, "Cannot determine current playback time.")
        return

    current_time_sec = current_time_ms / 1000.0

    directory_files = state.metadata.directory_files
    filepath = directory_files.get(filename)
    if not filepath or not os.path.exists(filepath):
        error_title = "Cut Before" if cut_mode == "before" else "Cut After"
        messagebox.showerror(error_title,
                             f"The file does not exist or is not found:\n{filename}")
        return

    minutes = int(current_time_sec // 60)
    seconds = int(current_time_sec % 60)
    milliseconds = int((current_time_sec % 1) * 1000)
    time_display = f"{minutes}:{seconds:02d}.{milliseconds:03d}"

    if cut_mode == "before":
        confirm_title = "Cut Before Current Time"
        confirm_msg = (
            f"This will cut the video BEFORE the current time:\n{filename}\n\n"
            f"Current time: {time_display}\n"
            f"Result: Keep everything AFTER {time_display}\n\nContinue?"
        )
        suffix = "_cut_before"
        log_msg = f"before {time_display}"
    else:
        confirm_title = "Cut After Current Time"
        confirm_msg = (
            f"This will cut the video AFTER the current time:\n{filename}\n\n"
            f"Current time: {time_display}\n"
            f"Result: Keep everything BEFORE {time_display}\n\nContinue?"
        )
        suffix = "_cut_after"
        log_msg = f"after {time_display}"

    confirm = messagebox.askyesno(confirm_title, confirm_msg)
    if not confirm:
        return

    cutting_method = messagebox.askyesnocancel(
        "Choose Cutting Method",
        "Choose cutting precision:\n\n"
        "YES = FAST CUT (stream copy)\n"
        "  • Very fast, no quality loss\n"
        "  • May cut a few seconds off due to keyframes\n\n"
        "NO = PRECISE CUT (re-encode)\n"
        "  • Frame-accurate cutting\n"
        "  • Slower, slight quality loss\n\n"
        "CANCEL = Abort operation",
    )

    if cutting_method is None:
        return

    use_stream_copy = cutting_method

    base, ext = os.path.splitext(filepath)
    precision_suffix = "_fast" if use_stream_copy else "_precise"
    cut_filepath = f"{base}{suffix}{precision_suffix}{ext}"

    try:
        _, output_ext = os.path.splitext(cut_filepath)
        output_ext = output_ext.lower()

        if output_ext == '.webm':
            video_codec_options = ["libvpx-vp9", "libvpx", "libx264"]
            audio_codec_options = ["libvorbis", "libopus", "aac"]
        elif output_ext == '.mp4':
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]
        elif output_ext == '.mkv':
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]
        else:
            video_codec_options = ["libx264", "h264"]
            audio_codec_options = ["aac", "mp3"]

        def check_codec_available(codec_name, codec_type="encoder"):
            try:
                result = subprocess.run(
                    ["ffmpeg", "-hide_banner", f"-{codec_type}s"],
                    capture_output=True, text=True, timeout=10,
                )
                return codec_name in result.stdout
            except Exception:
                return False

        video_codec = next((c for c in video_codec_options if check_codec_available(c)), None)
        audio_codec = next((c for c in audio_codec_options if check_codec_available(c)), None)

        if output_ext == '.webm' and (video_codec in ["libx264", "h264"] or audio_codec == "aac"):
            print("Warning: WebM codecs not available, switching to MP4 format")
            cut_filepath = os.path.splitext(cut_filepath)[0] + ".mp4"
            output_ext = '.mp4'
            if not video_codec:
                video_codec = "libx264"
            if not audio_codec:
                audio_codec = "aac"

        if not use_stream_copy:
            if not video_codec:
                messagebox.showerror("Codec Error",
                                     f"No suitable video encoder found for {output_ext} format.\n"
                                     "Try using fast cut (stream copy) instead.")
                return
            if not audio_codec:
                messagebox.showerror("Codec Error",
                                     f"No suitable audio encoder found for {output_ext} format.\n"
                                     "Try using fast cut (stream copy) instead.")
                return

        def _audio_quality_args(codec):
            if codec == "libvorbis":
                return ["-q:a", "6"]
            elif codec in ("libopus", "aac", "mp3"):
                return ["-b:a", "192k"]
            return []

        if cut_mode == "before":
            if use_stream_copy:
                ffmpeg_cmd = [
                    "ffmpeg", "-ss", str(current_time_sec), "-i", filepath,
                    "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", cut_filepath,
                ]
            else:
                ffmpeg_cmd = (
                    ["ffmpeg", "-i", filepath, "-ss", str(current_time_sec),
                     "-c:v", video_codec, "-c:a", audio_codec, "-preset", "fast",
                     "-avoid_negative_ts", "make_zero", "-y"]
                    + _audio_quality_args(audio_codec)
                    + [cut_filepath]
                )
        else:
            if use_stream_copy:
                ffmpeg_cmd = [
                    "ffmpeg", "-i", filepath, "-t", str(current_time_sec),
                    "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", cut_filepath,
                ]
            else:
                ffmpeg_cmd = (
                    ["ffmpeg", "-i", filepath, "-t", str(current_time_sec),
                     "-c:v", video_codec, "-c:a", audio_codec, "-preset", "fast",
                     "-avoid_negative_ts", "make_zero", "-y"]
                    + _audio_quality_args(audio_codec)
                    + [cut_filepath]
                )

        if use_stream_copy:
            result = subprocess.run(
                ffmpeg_cmd, capture_output=True, text=True,
                encoding='utf-8', errors='ignore', timeout=300,
            )
        else:
            result = subprocess.run(ffmpeg_cmd, text=True, encoding='utf-8', errors='ignore', timeout=600)

        if result.returncode == 0 and os.path.exists(cut_filepath):
            success_msg = f"Video cut successfully!\nSaved as: {os.path.basename(cut_filepath)}"
            if not use_stream_copy:
                success_msg += "\n\n(Re-encoded for frame precision)"
            messagebox.showinfo("Cut Complete", success_msg)

            try:
                if platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", os.path.normpath(cut_filepath)])
                elif platform.system() == "Darwin":
                    subprocess.run(["open", "-R", cut_filepath])
                else:
                    subprocess.run(["xdg-open", os.path.dirname(cut_filepath)])
            except Exception as e:
                print(f"Could not open folder: {e}")

            replace = messagebox.askyesno(
                "Replace Original",
                f"Do you want to replace the original file with the cut version?\n\n"
                f"Original: {filename}\nCut file: {os.path.basename(cut_filepath)}\n\n"
                "This cannot be undone!",
            )

            if replace:
                try:
                    transport.stop()
                    os.remove(filepath)
                    os.rename(cut_filepath, filepath)
                    messagebox.showinfo("File Replaced",
                                       "Original file has been replaced with the cut version.")
                    print(f"Replaced {filename} with cut version ({log_msg})")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to replace original file:\n{e}")
        else:
            if hasattr(result, 'stderr') and result.stderr:
                error_details = result.stderr.strip()
                error_summary = error_details.split('\n')[-1] if error_details else "Unknown FFmpeg error"
            else:
                error_summary = f"FFmpeg exited with code {result.returncode}"
            messagebox.showerror("FFmpeg Error", f"Failed to cut video:\n\n{error_summary}")
            if os.path.exists(cut_filepath):
                os.remove(cut_filepath)

    except subprocess.TimeoutExpired as e:
        messagebox.showerror("Timeout", f"Operation timed out after {e.timeout} seconds.")
        if os.path.exists(cut_filepath):
            os.remove(cut_filepath)
    except FileNotFoundError:
        messagebox.showerror("FFmpeg Not Found",
                             "FFmpeg is not installed or not found in PATH.\n\n"
                             "Please install FFmpeg and ensure it's available in your system PATH.")
    except Exception as e:
        messagebox.showerror("Error", f"An unexpected error occurred:\n\n{str(e)}")
        if os.path.exists(cut_filepath):
            os.remove(cut_filepath)


def cut_before_current_time(filename):
    """Cut the video before the current playback time using FFmpeg."""
    _cut_video_at_time(filename, "before")


def cut_after_current_time(filename):
    """Cut the video after the current playback time using FFmpeg."""
    _cut_video_at_time(filename, "after")
