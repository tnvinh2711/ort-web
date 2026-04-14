"""ORT Web CLI — open, update, version."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

from app._version import __version__

REPO_URL = "https://github.com/tnvinh2711/ort-web"
API_TAGS_URL = "https://api.github.com/repos/tnvinh2711/ort-web/tags"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _find_free_port(default: int = 8000) -> int:
    """Return default port if available, otherwise find a free one."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", default))
            return default
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def cmd_open(args: argparse.Namespace) -> None:
    """Start the server and open browser."""
    port = args.port or _find_free_port()
    host = "127.0.0.1"
    url = f"http://{host}:{port}"

    print(f"ORT Web v{__version__}")
    print(f"Starting server at {url}")

    # Open browser after a short delay
    def _open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    # Start uvicorn
    os.chdir(str(PROJECT_ROOT))
    try:
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=args.reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\nServer stopped.")


def _fetch_latest_tag() -> str | None:
    """Fetch latest tag from GitHub API."""
    import ssl
    try:
        ctx = ssl.create_default_context()
        req = Request(API_TAGS_URL, headers={"User-Agent": "ort-web-cli"})
        with urlopen(req, timeout=10, context=ctx) as resp:
            tags = json.loads(resp.read().decode())
        if tags:
            return tags[0]["name"]
    except (URLError, json.JSONDecodeError, KeyError, IndexError, ssl.SSLError):
        pass
    return None


def _current_git_tag() -> str | None:
    """Get the tag pointing to current HEAD, if any."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True, text=True, check=False,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def cmd_update(args: argparse.Namespace) -> None:
    """Check for updates and pull latest."""
    print(f"Current version: v{__version__}")

    latest_tag = _fetch_latest_tag()
    if not latest_tag:
        print("Could not check for updates. Check your internet connection.")
        return

    current_tag = f"v{__version__}"
    if latest_tag == current_tag:
        print(f"Already up to date ({current_tag}).")
        return

    print(f"New version available: {latest_tag} (current: {current_tag})")

    if not args.yes:
        answer = input("Update now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Update cancelled.")
            return

    print(f"Fetching {latest_tag}...")
    try:
        subprocess.run(
            ["git", "fetch", "--tags", "origin"],
            check=True, cwd=str(PROJECT_ROOT),
        )
        subprocess.run(
            ["git", "checkout", latest_tag],
            check=True, cwd=str(PROJECT_ROOT),
        )
        print(f"Updated to {latest_tag}.")

        # Reinstall dependencies
        print("Installing dependencies...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            check=True, cwd=str(PROJECT_ROOT),
        )
        print("Done! Run `ort-web open` to start.")
    except subprocess.CalledProcessError as exc:
        print(f"Update failed: {exc}")
        sys.exit(1)


def cmd_version(args: argparse.Namespace) -> None:
    """Print version info."""
    print(f"ort-web v{__version__}")
    git_tag = _current_git_tag()
    if git_tag:
        print(f"git tag: {git_tag}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ort-web",
        description="ORT Web — Local GUI for OSS Review Toolkit",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"ort-web v{__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    # open
    p_open = sub.add_parser("open", help="Start server and open browser")
    p_open.add_argument("-p", "--port", type=int, default=None, help="Port (default: 8000)")
    p_open.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    p_open.set_defaults(func=cmd_open)

    # update
    p_update = sub.add_parser("update", help="Check for updates and pull latest")
    p_update.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_update.set_defaults(func=cmd_update)

    # version
    p_ver = sub.add_parser("version", help="Show version info")
    p_ver.set_defaults(func=cmd_version)

    args = parser.parse_args()
    if not args.command:
        # Default to open
        args.port = None
        args.reload = False
        cmd_open(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
