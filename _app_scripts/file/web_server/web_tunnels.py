"""web_tunnels.py — ngrok / cloudflared tunnel discovery and launch helpers.

Split out of web_server.py: this module owns the public-URL exposure layer
(finding the tunnel binaries at import time and launching them as subprocesses).
The launch helpers are pure with respect to web_server's state — they return
``(process, public_url)`` and let web_server own the process refs / public_url,
rather than reaching back into that module's globals.
"""

import os
import shutil
import subprocess
import sys


# ---------------------------------------------------------------------------
# Tunnel availability (checked once at import time)
# ---------------------------------------------------------------------------
def find_ngrok_cmd():
    """Return the ngrok command string if found, else None."""
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    for candidate in [
        os.path.join(script_dir, 'ngrok.exe'),
        os.path.join(os.path.dirname(sys.executable), 'ngrok.exe'),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which('ngrok')


def find_cloudflared_cmd():
    """Return the cloudflared command string if found, else None."""
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    for candidate in [
        os.path.join(script_dir, 'cloudflared.exe'),
        os.path.join(os.path.dirname(sys.executable), 'cloudflared.exe'),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which('cloudflared')


NGROK_CMD = find_ngrok_cmd()   # None if not found
NGROK_AVAILABLE = NGROK_CMD is not None
CLOUDFLARED_CMD = find_cloudflared_cmd()   # None if not found
CLOUDFLARED_AVAILABLE = CLOUDFLARED_CMD is not None


# ---------------------------------------------------------------------------
# Tunnel launch
# ---------------------------------------------------------------------------
def start_ngrok(domain, port):
    """Launch an ngrok tunnel for ``domain`` → ``port``.

    Returns ``(process, public_url)`` on success, or ``(None, None)`` if the
    ngrok binary could not be found (server stays local-only).
    """
    # Strip any protocol prefix the user may have pasted into config
    domain = domain.removeprefix('https://').removeprefix('http://').rstrip('/')
    # Resolve ngrok: prefer the exe dir (works inside a frozen .exe) then fall back to PATH
    try:
        process = subprocess.Popen(
            [NGROK_CMD, 'http', '--domain', domain, str(port)],  # NGROK_CMD resolved at import
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        public_url = f'https://{domain}'
        print(f'[Web Server] Live at: {public_url}')
        return process, public_url
    except FileNotFoundError:
        print('[Web Server] ngrok.exe not found in PATH or exe directory. Server is local-only.')
        return None, None


def start_cloudflared(token, public_url_str):
    """Launch a named Cloudflare tunnel using ``token``.

    Returns ``(process, public_url)`` on success, or ``(None, None)`` if the
    cloudflared binary could not be found (server stays local-only).
    """
    url = public_url_str.strip().rstrip('/')
    if url and not url.startswith('http'):
        url = 'https://' + url
    try:
        process = subprocess.Popen(
            [CLOUDFLARED_CMD, 'tunnel', 'run', '--token', token],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f'[Web Server] Live at: {url}')
        return process, url
    except FileNotFoundError:
        print('[Web Server] cloudflared not found in PATH or exe directory. Server is local-only.')
        return None, None
