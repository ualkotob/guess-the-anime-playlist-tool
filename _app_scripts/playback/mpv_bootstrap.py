"""mpv DLL discovery/download and python-mpv import bootstrap."""

import io
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

import requests
import tkinter as tk
from tkinter import messagebox, ttk


MPV_DLL_NAME = "libmpv-2.dll"
_MPV_RELEASE_API = "https://api.github.com/repos/zhongfly/mpv-winbuild/releases/latest"


def get_app_dir():
    """Return the directory containing the running exe (frozen) or script (dev)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.getcwd()


def mpv_dll_path():
    return os.path.join(get_app_dir(), MPV_DLL_NAME)


def ensure_mpv_dll():
    """Return path to mpv-2.dll, downloading it automatically if missing."""
    dll = mpv_dll_path()
    if os.path.exists(dll):
        return dll

    _temp_root = None
    try:
        if tk._default_root is None:
            _temp_root = tk.Tk()
            _temp_root.withdraw()
    except Exception:
        pass

    try:
        if not messagebox.askyesno(
            "mpv not found",
            f"{MPV_DLL_NAME} was not found in the application folder.\n\n"
            "Download it automatically from GitHub? (~30 MB)\n\n"
            "This is required to play media.",
            icon="warning"
        ):
            messagebox.showerror(
                "Cannot continue",
                f"{MPV_DLL_NAME} is required. Exiting."
            )
            sys.exit(1)

        dlg = tk.Toplevel()
        dlg.title("Downloading mpv...")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)
        tk.Label(dlg, text=f"Downloading {MPV_DLL_NAME}, please wait...",
                 font=("Arial", 11)).pack(padx=24, pady=(16, 4))
        status_var = tk.StringVar(value="Connecting...")
        tk.Label(dlg, textvariable=status_var, font=("Arial", 9), fg="#aaa").pack(padx=24)
        pb = ttk.Progressbar(dlg, length=360, mode="determinate")
        pb.pack(padx=24, pady=(6, 18))
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"410x115+{(sw-410)//2}+{(sh-115)//2}")
        dlg.update()

        q = queue.Queue()
        err_ref = [None]
        ok_ref = [None]

        def _worker():
            try:
                q.put(("status", "Fetching release info..."))
                resp = requests.get(
                    _MPV_RELEASE_API, timeout=15,
                    headers={"User-Agent": "GuessTheAnime/auto-mpv-dl"}
                )
                resp.raise_for_status()
                assets = resp.json().get("assets", [])

                asset_url = None
                for a in assets:
                    n = a["name"]
                    if (n.startswith("mpv-dev-x86_64-") and n.endswith(".7z")
                            and "lgpl" not in n and "v3" not in n):
                        asset_url = a["browser_download_url"]
                        break
                if not asset_url:
                    names = [a['name'] for a in assets]
                    raise RuntimeError(
                        "No mpv-dev-x86_64 .7z found in the latest GitHub release.\n"
                        f"Available assets: {names}\n"
                        "https://github.com/zhongfly/mpv-winbuild/releases"
                    )

                q.put(("status", f"Downloading {os.path.basename(asset_url)}..."))
                resp = requests.get(
                    asset_url, stream=True, timeout=180,
                    headers={"User-Agent": "GuessTheAnime/auto-mpv-dl"}
                )
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                buf = io.BytesIO()
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=131072):
                    if chunk:
                        buf.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            q.put(("progress", downloaded, total))

                q.put(("status", "Extracting libmpv-2.dll..."))
                buf.seek(0)
                tmp_dir = tempfile.mkdtemp(prefix="gta_mpv_")
                try:
                    tmp_7z_path = os.path.join(tmp_dir, "mpv-dev.7z")
                    with open(tmp_7z_path, "wb") as _f:
                        _f.write(buf.read())

                    exe_7z = (shutil.which("7z") or shutil.which("7za") or
                              next((p for p in [
                                  r"C:\Program Files\7-Zip\7z.exe",
                                  r"C:\Program Files (x86)\7-Zip\7z.exe",
                              ] if os.path.exists(p)), None))
                    if not exe_7z:
                        q.put(("status", "Downloading 7zr.exe (one-time, ~400 KB)..."))
                        exe_7z = os.path.join(tmp_dir, "7zr.exe")
                        r7z = requests.get(
                            "https://www.7-zip.org/a/7zr.exe",
                            timeout=30,
                            headers={"User-Agent": "GuessTheAnime/auto-mpv-dl"}
                        )
                        r7z.raise_for_status()
                        with open(exe_7z, "wb") as _f:
                            _f.write(r7z.content)

                    q.put(("status", "Extracting libmpv-2.dll..."))
                    out_dir = os.path.dirname(dll)
                    result = subprocess.run(
                        [exe_7z, "e", tmp_7z_path, MPV_DLL_NAME,
                         f"-o{out_dir}", "-y"],
                        capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        raise RuntimeError(
                            f"7-Zip extraction failed (code {result.returncode}):\n"
                            f"{result.stderr or result.stdout}"
                        )
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                if os.path.exists(dll):
                    ok_ref[0] = dll
                if not ok_ref[0]:
                    raise RuntimeError(
                        f"{MPV_DLL_NAME} was not found inside the downloaded archive."
                    )
                q.put(("done", dll))
            except Exception as exc:
                err_ref[0] = str(exc)
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    msg = q.get_nowait()
                    kind = msg[0]
                    if kind == "progress":
                        _, dl, tot = msg
                        pb["value"] = dl / tot * 100
                        status_var.set(f"{dl/1048576:.1f} / {tot/1048576:.1f} MB")
                    elif kind == "status":
                        status_var.set(msg[1])
                    elif kind in ("done", "error"):
                        dlg.destroy()
                        return
            except Exception:
                pass
            dlg.after(80, _poll)

        threading.Thread(target=_worker, daemon=True).start()
        dlg.after(80, _poll)
        dlg.wait_window()

        if err_ref[0]:
            messagebox.showerror(
                "Download failed",
                f"Could not download {MPV_DLL_NAME}:\n\n{err_ref[0]}\n\n"
                "Please download it manually and place it next to the exe:\n"
                "https://github.com/zhongfly/mpv-winbuild/releases\n"
                "(get mpv-dev-x86_64-*.7z, extract mpv-2.dll)"
            )
            sys.exit(1)

        return dll

    finally:
        if _temp_root:
            try:
                _temp_root.destroy()
            except Exception:
                pass


def load_mpv_module():
    """Ensure libmpv is present, update PATH, and import python-mpv."""
    ensure_mpv_dll()
    app_dir = get_app_dir()
    if app_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = app_dir + os.pathsep + os.environ.get("PATH", "")
    try:
        import mpv as mpv_module
        return mpv_module
    except Exception as mpv_err:
        try:
            messagebox.showerror(
                "mpv load error",
                f"Failed to load mpv:\n\n{mpv_err}\n\n"
                "Please ensure libmpv-2.dll is in the application folder."
            )
        except Exception:
            print(f"FATAL: Failed to load mpv: {mpv_err}")
        sys.exit(1)
