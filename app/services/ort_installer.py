from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from app.config import settings
from app.services.log_stream import log_stream_hub

GITHUB_LATEST_RELEASE = "https://api.github.com/repos/oss-review-toolkit/ort/releases/latest"


class OrtInstallerError(RuntimeError):
    pass


def _select_asset(assets: list[dict[str, str]]) -> dict[str, str]:
    system = platform.system()

    def is_main_ort(name: str) -> bool:
        return name.startswith("ort-") and not name.startswith("orth-")

    if system == "Windows":
        candidates = [a for a in assets if is_main_ort(a.get("name", "")) and a.get("name", "").endswith(".zip")]
    elif system in ("Darwin", "Linux"):
        candidates = [a for a in assets if is_main_ort(a.get("name", "")) and a.get("name", "").endswith(".tgz")]
    else:
        raise OrtInstallerError(f"Unsupported platform for this installer flow: {system}")

    if not candidates:
        raise OrtInstallerError(f"Could not find a compatible ORT release asset for {system}.")

    return candidates[0]


def _extract_archive(archive_path: Path, extract_dir: Path) -> None:
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_dir)
        return

    if archive_path.suffix == ".tgz" or archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(extract_dir)
        return

    raise OrtInstallerError(f"Unsupported archive format: {archive_path.name}")


def _find_bin_dir(extract_dir: Path) -> Path:
    for candidate in extract_dir.rglob("bin"):
        if candidate.is_dir() and ((candidate / "ort").exists() or (candidate / "ort.bat").exists()):
            return candidate
    raise OrtInstallerError("Could not locate ORT 'bin' directory in extracted archive.")


def _ensure_writable_dir(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    probe = target_dir / ".write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _deploy_distribution(source_root: Path, target_bin_dir: Path) -> tuple[Path, Path]:
    """
    Deploy ORT distribution under target_bin_dir/.ort-dist/current and create launcher in target_bin_dir.

    Returns:
        (launcher_path, install_home)
    """
    install_home = target_bin_dir / ".ort-dist" / "current"
    if install_home.exists():
        shutil.rmtree(install_home)

    install_home.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, install_home)

    if os.name == "nt":
        launcher = target_bin_dir / "ort.bat"
        launcher.write_text(
            "@echo off\r\n"
            f'"{install_home / "bin" / "ort.bat"}" %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = target_bin_dir / "ort"
        launcher.write_text(
            "#!/usr/bin/env sh\n"
            "set -e\n"
            f'ORT_HOME="{install_home}"\n'
            'exec "$ORT_HOME/bin/ort" "$@"\n',
            encoding="utf-8",
        )
        mode = launcher.stat().st_mode
        launcher.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return launcher, install_home


def _verify_ort_runtime(launcher: Path) -> None:
    result = subprocess.run(
        [str(launcher), "--version"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode == 0:
        return

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if "UnsupportedClassVersionError" in output:
        raise OrtInstallerError(
            "ORT requires newer Java runtime. Detected class version mismatch. "
            "Please install JDK 21+ and set JAVA_HOME/PATH to that JDK."
        )

    raise OrtInstallerError(f"ORT launcher verification failed: {output.strip()[:600]}")


async def install_ort_local(
    job_id: str,
    log_file: Path,
    target_dir_override: Path | None = None,
) -> tuple[int, str | None]:
    """
    Install full ORT distribution and create launcher binary in target directory.

    Returns:
        Tuple of (exit_code, ort_install_path)
    """

    async def log(line: str) -> None:
        message = f"{line.rstrip()}\n"
        with log_file.open("a", encoding="utf-8") as out:
            out.write(message)
            out.flush()
        await log_stream_hub.publish(job_id, {"type": "log", "line": message})

    ort_path: str | None = None
    try:
        await log("Starting ORT local install...")
        await log(f"Detected platform: {platform.system()}")

        target_dir = target_dir_override or settings.ort_install_dir

        if target_dir_override is not None:
            await log(f"Using custom install dir: {target_dir}")
        else:
            await log(f"Using default install dir: {target_dir}")

        try:
            await asyncio.to_thread(_ensure_writable_dir, target_dir)
        except Exception:
            fallback = Path.home() / ".local" / "bin"
            await log(f"Install dir not writable: {target_dir}")
            await log(f"Fallback to writable user dir: {fallback}")
            target_dir = fallback
            await asyncio.to_thread(_ensure_writable_dir, target_dir)

        def _fetch_release() -> dict:
            with urllib.request.urlopen(GITHUB_LATEST_RELEASE, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        release = await asyncio.to_thread(_fetch_release)

        assets = release.get("assets", [])
        asset = _select_asset(assets)
        download_url = asset["browser_download_url"]
        asset_name = asset["name"]

        await log(f"Selected release asset: {asset_name}")

        with tempfile.TemporaryDirectory(prefix="ort-installer-") as tmp:
            tmp_dir = Path(tmp)
            archive_path = tmp_dir / asset_name
            extract_dir = tmp_dir / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)

            await log("Downloading ORT release archive...")
            loop = asyncio.get_running_loop()

            def _download_with_progress() -> None:
                req = urllib.request.Request(
                    download_url, headers={"User-Agent": "ort-web-installer"}
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    total = int(resp.headers.get("Content-Length") or 0)
                    downloaded = 0
                    last_pct = -1
                    with archive_path.open("wb") as f:
                        while True:
                            chunk = resp.read(512 * 1024)  # 512KB chunks, each has 60s timeout
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = int(downloaded * 100 / total)
                                if pct // 10 != last_pct // 10:
                                    last_pct = pct
                                    mb = downloaded // (1024 * 1024)
                                    total_mb = total // (1024 * 1024)
                                    msg = f"Downloading... {pct}% ({mb}/{total_mb} MB)\n"
                                    with log_file.open("a", encoding="utf-8") as out:
                                        out.write(msg)
                                    asyncio.run_coroutine_threadsafe(
                                        log_stream_hub.publish(job_id, {"type": "log", "line": msg}),
                                        loop,
                                    )

            await asyncio.to_thread(_download_with_progress)

            await log("Extracting archive...")
            await asyncio.to_thread(_extract_archive, archive_path, extract_dir)

            source_bin = await asyncio.to_thread(_find_bin_dir, extract_dir)
            source_root = source_bin.parent
            await log(f"Installing full distribution to: {target_dir / '.ort-dist' / 'current'}")
            launcher, install_home = await asyncio.to_thread(_deploy_distribution, source_root, target_dir)

        if not launcher.exists():
            raise OrtInstallerError(f"Install finished but launcher not found at: {launcher}")

        await asyncio.to_thread(_verify_ort_runtime, launcher)

        ort_path = str(launcher)
        await log("ORT installed successfully.")
        await log(f"Launcher: {launcher}")
        await log(f"Install home: {install_home}")
        return 0, ort_path
    except Exception as exc:
        await log(f"[error] ORT install failed: {exc}")
        return 1, ort_path
