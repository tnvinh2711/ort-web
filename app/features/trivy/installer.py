"""Ensure the Trivy binary is available, auto-installing it if missing.

Primary strategy mirrors ``app/features/ort/installer.py``: download the
platform-appropriate release archive from GitHub, extract the ``trivy`` binary,
and drop it into ``settings.bin_dir`` (which ``executor.py`` already adds to
PATH for subprocesses). No admin rights required.

On Windows we additionally try winget/choco/scoop as a best-effort fallback.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.config import settings

_LogFn = Callable[[str], Awaitable[None]]

GITHUB_LATEST_RELEASE = "https://api.github.com/repos/aquasecurity/trivy/releases/latest"


def _trivy_binary_name() -> str:
    return "trivy.exe" if os.name == "nt" else "trivy"


def _which_trivy() -> Optional[str]:
    """Return an existing Trivy path: PATH first, then the local bin dir."""
    found = shutil.which("trivy")
    if found:
        return found
    local = settings.bin_dir / _trivy_binary_name()
    if local.exists():
        return str(local)
    return None


def _select_asset(assets: list[dict]) -> Optional[dict]:
    system = platform.system()
    machine = platform.machine().lower()
    arch = "ARM64" if machine in ("arm64", "aarch64") else "64bit"

    if system == "Windows":
        os_token, ext = "windows", ".zip"
    elif system == "Darwin":
        os_token, ext = "macOS", ".tar.gz"
    elif system == "Linux":
        os_token, ext = "Linux", ".tar.gz"
    else:
        return None

    wanted = f"{os_token}-{arch}".lower()
    fallback = f"{os_token}-64bit".lower()

    def _match(token: str) -> Optional[dict]:
        for a in assets:
            name = str(a.get("name", "")).lower()
            if name.startswith("trivy_") and token in name and name.endswith(ext):
                return a
        return None

    return _match(wanted) or _match(fallback)


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ort-web-trivy-installer"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)


def _extract(archive: Path, extract_dir: Path) -> None:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(extract_dir)


def _find_binary(extract_dir: Path) -> Optional[Path]:
    name = _trivy_binary_name()
    for candidate in extract_dir.rglob(name):
        if candidate.is_file():
            return candidate
    return None


async def _stream(log_fn: _LogFn, *args: str) -> int:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=tempfile.gettempdir(),
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip()
        if line:
            await log_fn(line + "\n")
    return await proc.wait()


async def _install_from_github(log_fn: _LogFn) -> Optional[str]:
    await log_fn("  Fetching latest Trivy release info...\n")

    def _fetch() -> dict:
        req = urllib.request.Request(
            GITHUB_LATEST_RELEASE, headers={"User-Agent": "ort-web-trivy-installer"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        release = await asyncio.to_thread(_fetch)
    except Exception as exc:
        await log_fn(f"  Could not fetch release info: {exc}\n")
        return None

    asset = _select_asset(release.get("assets", []))
    if not asset:
        await log_fn("  No compatible Trivy release asset found for this platform.\n")
        return None

    url = asset["browser_download_url"]
    name = asset["name"]
    await log_fn(f"  Selected: {name}\n")

    bin_dir = settings.bin_dir
    bin_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="trivy-installer-") as tmp:
        tmp_dir = Path(tmp)
        archive = tmp_dir / name
        extract_dir = tmp_dir / "x"
        extract_dir.mkdir()
        try:
            await asyncio.to_thread(_download, url, archive)
            await asyncio.to_thread(_extract, archive, extract_dir)
        except Exception as exc:
            await log_fn(f"  Download/extract failed: {exc}\n")
            return None

        binary = await asyncio.to_thread(_find_binary, extract_dir)
        if not binary:
            await log_fn("  Could not locate the trivy binary in the archive.\n")
            return None

        target = bin_dir / _trivy_binary_name()
        try:
            await asyncio.to_thread(shutil.copy2, binary, target)
        except Exception as exc:
            await log_fn(f"  Could not place trivy in {bin_dir}: {exc}\n")
            return None

    if os.name != "nt":
        mode = target.stat().st_mode
        target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    await log_fn(f"  Trivy installed: {target}\n")
    return str(target)


async def _install_via_package_manager(log_fn: _LogFn) -> Optional[str]:
    """Best-effort Windows package-manager fallback."""
    if platform.system() != "Windows":
        return None

    winget = shutil.which("winget")
    if winget:
        await log_fn("  Trying winget install AquaSecurity.Trivy...\n")
        rc = await _stream(
            log_fn, winget, "install", "--id", "AquaSecurity.Trivy",
            "--exact", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity",
        )
        if rc == 0 and _which_trivy():
            return _which_trivy()

    choco = shutil.which("choco")
    if choco:
        await log_fn("  Trying choco install trivy...\n")
        rc = await _stream(log_fn, choco, "install", "trivy", "-y", "--no-progress")
        if rc == 0 and _which_trivy():
            return _which_trivy()

    scoop = shutil.which("scoop")
    if scoop:
        await log_fn("  Trying scoop install trivy...\n")
        rc = await _stream(log_fn, scoop, "install", "trivy")
        if rc == 0 and _which_trivy():
            return _which_trivy()

    return None


async def ensure_trivy(log_fn: _LogFn) -> Optional[str]:
    """Return a path to the Trivy binary, installing it if necessary.

    Returns ``None`` if Trivy is unavailable after the install attempt.
    """
    existing = _which_trivy()
    if existing:
        await log_fn(f"  Trivy found: {existing}\n")
        return existing

    await log_fn("  Trivy not found — installing...\n")
    path = await _install_from_github(log_fn)
    if path:
        return path

    path = await _install_via_package_manager(log_fn)
    if path:
        return path

    await log_fn(
        "  Could not auto-install Trivy. Install manually: "
        "https://trivy.dev/latest/getting-started/installation/\n"
    )
    return None
