from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Awaitable

from app.config import settings
from app.features.jobs.log_stream import log_stream_hub

GITHUB_LATEST_RELEASE = "https://api.github.com/repos/oss-review-toolkit/ort/releases/latest"


class OrtInstallerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Java detection & installation
# ---------------------------------------------------------------------------

def _java_major_version(java_bin: str | Path) -> int | None:
    """Return Java major version number, or None if undetectable."""
    try:
        result = subprocess.run(
            [str(java_bin), "-version"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        output = result.stderr + result.stdout
        m = re.search(r'version "(\d+)', output)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _find_java_21_home() -> Path | None:
    """Search common locations for a Java 21+ home directory."""
    system = platform.system()

    def _check(home: Path) -> Path | None:
        java_bin = home / "bin" / ("java.exe" if system == "Windows" else "java")
        if java_bin.exists() and (_java_major_version(java_bin) or 0) >= 21:
            return home
        return None

    # 1. JAVA_HOME env
    java_home_env = os.environ.get("JAVA_HOME")
    if java_home_env:
        result = _check(Path(java_home_env))
        if result:
            return result

    if system == "Darwin":
        # /usr/libexec/java_home -v 21+
        try:
            r = subprocess.run(
                ["/usr/libexec/java_home", "-v", "21+"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if r.returncode == 0 and r.stdout.strip():
                result = _check(Path(r.stdout.strip()))
                if result:
                    return result
        except Exception:
            pass

        # Homebrew openjdk@21
        for prefix in ("/opt/homebrew", "/usr/local"):
            home = Path(prefix) / "opt" / "openjdk@21" / "libexec" / "openjdk.jdk" / "Contents" / "Home"
            result = _check(home)
            if result:
                return result

    elif system == "Linux":
        for pattern in [
            "/usr/lib/jvm/java-21-openjdk-amd64",
            "/usr/lib/jvm/java-21-openjdk-arm64",
            "/usr/lib/jvm/java-21-openjdk",
            "/usr/lib/jvm/temurin-21",
            "/usr/lib/jvm/java-21",
        ]:
            result = _check(Path(pattern))
            if result:
                return result

    elif system == "Windows":
        for base_env in ("LOCALAPPDATA", "ProgramFiles", "ProgramW6432"):
            base = os.environ.get(base_env, "")
            if not base:
                continue
            for subdir in [
                "Eclipse Adoptium\\jdk-21",
                "Microsoft\\jdk-21",
                "Java\\jdk-21",
                "Java\\jdk-21.0",
            ]:
                result = _check(Path(base) / subdir)
                if result:
                    return result

    # Last resort: java in PATH
    java_in_path = shutil.which("java")
    if java_in_path and (_java_major_version(java_in_path) or 0) >= 21:
        return Path(java_in_path).resolve().parent.parent

    return None


async def _ensure_java_21(
    log: Callable[[str], Awaitable[None]],
) -> Path | None:
    """
    Ensure Java 21+ is available. Auto-installs if missing.
    Returns JAVA_HOME path or None if unavailable after install attempt.
    """
    java_home = await asyncio.to_thread(_find_java_21_home)
    if java_home:
        version = await asyncio.to_thread(_java_major_version, java_home / "bin" / "java")
        await log(f"Java {version} found at {java_home}")
        return java_home

    # Check what Java is currently available
    java_cmd = shutil.which("java")
    if java_cmd:
        version = await asyncio.to_thread(_java_major_version, java_cmd)
        await log(f"Java {version or '?'} found but need 21+. Installing Java 21...")
    else:
        await log("Java not found. Installing Java 21...")

    system = platform.system()

    async def _stream_proc(*args: str) -> int:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                await log(line)
        await proc.wait()
        return proc.returncode

    if system == "Darwin":
        brew = shutil.which("brew")
        if not brew:
            await log("Homebrew not found. Install Java 21 manually from: https://adoptium.net/temurin/releases/?version=21")
            return None
        await log("Installing Java 21 via Homebrew (this may take a few minutes)...")
        rc = await _stream_proc(brew, "install", "openjdk@21")
        if rc != 0:
            await log("Homebrew Java install failed. Install manually from: https://adoptium.net")
            return None

    elif system == "Linux":
        installed = False
        for pkg_mgr, pkg in [
            (shutil.which("apt-get"), ["sudo", "apt-get", "install", "-y", "openjdk-21-jdk"]),
            (shutil.which("dnf"),     ["sudo", "dnf",     "install", "-y", "java-21-openjdk-devel"]),
            (shutil.which("yum"),     ["sudo", "yum",     "install", "-y", "java-21-openjdk-devel"]),
            (shutil.which("zypper"),  ["sudo", "zypper",  "install", "-y", "java-21-openjdk"]),
        ]:
            if not pkg_mgr:
                continue
            await log(f"Installing Java 21 via {pkg[1]}...")
            rc = await _stream_proc(*pkg)
            if rc == 0:
                installed = True
                break
        if not installed:
            await log("Could not auto-install Java. Install manually:")
            await log("  Ubuntu/Debian: sudo apt-get install openjdk-21-jdk")
            await log("  Fedora/RHEL:   sudo dnf install java-21-openjdk-devel")
            return None

    elif system == "Windows":
        winget = shutil.which("winget")
        if winget:
            await log("Installing Java 21 via winget...")
            rc = await _stream_proc(
                winget, "install", "Microsoft.OpenJDK.21",
                "--silent", "--accept-package-agreements", "--accept-source-agreements",
            )
            if rc != 0:
                await log("winget install failed. Install manually from: https://adoptium.net")
                return None
        else:
            await log("winget not found. Install Java 21 manually from: https://adoptium.net")
            return None
    else:
        await log(f"Auto-install not supported on {system}. Install Java 21 manually.")
        return None

    # Re-detect after install
    java_home = await asyncio.to_thread(_find_java_21_home)
    if java_home:
        await log(f"Java 21 installed successfully at {java_home}")
    else:
        await log("Java installed but could not locate JAVA_HOME — will try without explicit JAVA_HOME.")
    return java_home


# ---------------------------------------------------------------------------
# ORT archive helpers
# ---------------------------------------------------------------------------

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


def _deploy_distribution(
    source_root: Path,
    target_bin_dir: Path,
    java_home: Path | None = None,
) -> tuple[Path, Path]:
    """
    Deploy ORT distribution and create a launcher that embeds JAVA_HOME if provided.
    Returns (launcher_path, install_home).
    """
    install_home = target_bin_dir / ".ort-dist" / "current"
    if install_home.exists():
        shutil.rmtree(install_home)

    install_home.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, install_home)

    if os.name == "nt":
        launcher = target_bin_dir / "ort.bat"
        java_lines = (
            f'set "JAVA_HOME={java_home}"\r\n'
            f'set "PATH=%JAVA_HOME%\\bin;%PATH%"\r\n'
            if java_home else ""
        )
        launcher.write_text(
            "@echo off\r\n"
            + java_lines
            + f'"{install_home / "bin" / "ort.bat"}" %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = target_bin_dir / "ort"
        java_lines = (
            f'export JAVA_HOME="{java_home}"\n'
            f'export PATH="$JAVA_HOME/bin:$PATH"\n'
            if java_home else ""
        )
        launcher.write_text(
            "#!/usr/bin/env sh\n"
            "set -e\n"
            + java_lines
            + f'ORT_HOME="{install_home}"\n'
            'exec "$ORT_HOME/bin/ort" "$@"\n',
            encoding="utf-8",
        )
        mode = launcher.stat().st_mode
        launcher.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return launcher, install_home


def _verify_ort_runtime(launcher: Path, java_home: Path | None = None) -> None:
    env = os.environ.copy()
    if java_home:
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = str(java_home / "bin") + os.pathsep + env.get("PATH", "")

    cmd = [str(launcher), "--version"]
    if os.name == "nt" and str(launcher).lower().endswith(".bat"):
        cmd = ["cmd", "/c", *cmd]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    if result.returncode == 0:
        return

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if "UnsupportedClassVersionError" in output:
        raise OrtInstallerError(
            "ORT requires Java 21+. Java auto-install may have failed — "
            "please install JDK 21+ manually and set JAVA_HOME."
        )

    raise OrtInstallerError(f"ORT launcher verification failed: {output.strip()[:600]}")


# ---------------------------------------------------------------------------
# Main installer entry point
# ---------------------------------------------------------------------------

async def install_ort_local(
    job_id: str,
    log_file: Path,
    target_dir_override: Path | None = None,
) -> tuple[int, str | None]:
    """
    Install full ORT distribution (auto-installs Java 21 if needed).
    Returns (exit_code, ort_install_path).
    """

    async def log(line: str) -> None:
        message = f"{line.rstrip()}\n"
        with log_file.open("a", encoding="utf-8") as out:
            out.write(message)
            out.flush()
        await log_stream_hub.publish(job_id, {"type": "log", "line": message})

    loop = asyncio.get_running_loop()
    ort_path: str | None = None

    try:
        await log("Starting ORT local install...")
        await log(f"Detected platform: {platform.system()}")

        # --- Step 1: Ensure Java 21+ ---
        await log("--- Step 1: Checking Java ---")
        java_home = await _ensure_java_21(log)

        # --- Step 2: Choose install directory ---
        await log("--- Step 2: Preparing install directory ---")
        target_dir = target_dir_override or settings.ort_install_dir
        await log(f"Install dir: {target_dir}")

        try:
            await asyncio.to_thread(_ensure_writable_dir, target_dir)
        except Exception:
            fallback = Path.home() / ".local" / "bin"
            await log(f"Install dir not writable: {target_dir}")
            await log(f"Fallback: {fallback}")
            target_dir = fallback
            await asyncio.to_thread(_ensure_writable_dir, target_dir)

        # --- Step 3: Fetch latest ORT release ---
        await log("--- Step 3: Fetching ORT release info ---")

        def _fetch_release() -> dict:
            with urllib.request.urlopen(GITHUB_LATEST_RELEASE, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        release = await asyncio.to_thread(_fetch_release)
        assets = release.get("assets", [])
        asset = _select_asset(assets)
        download_url = asset["browser_download_url"]
        asset_name = asset["name"]
        await log(f"Selected release: {asset_name}")

        # --- Step 4: Download + extract + deploy ---
        await log("--- Step 4: Downloading ORT ---")
        with tempfile.TemporaryDirectory(prefix="ort-installer-") as tmp:
            tmp_dir = Path(tmp)
            archive_path = tmp_dir / asset_name
            extract_dir = tmp_dir / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)

            def _download_with_progress() -> None:
                req = urllib.request.Request(download_url, headers={"User-Agent": "ort-web-installer"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    total = int(resp.headers.get("Content-Length") or 0)
                    downloaded = 0
                    last_pct = -1
                    with archive_path.open("wb") as f:
                        while True:
                            chunk = resp.read(512 * 1024)
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

            await log("--- Step 5: Extracting archive ---")
            await asyncio.to_thread(_extract_archive, archive_path, extract_dir)

            await log("--- Step 6: Deploying ORT ---")
            source_bin = await asyncio.to_thread(_find_bin_dir, extract_dir)
            source_root = source_bin.parent
            await log(f"Deploying to: {target_dir / '.ort-dist' / 'current'}")
            launcher, install_home = await asyncio.to_thread(
                _deploy_distribution, source_root, target_dir, java_home
            )

        if not launcher.exists():
            raise OrtInstallerError(f"Launcher not found after deploy: {launcher}")

        await log("--- Step 7: Verifying ORT ---")
        await asyncio.to_thread(_verify_ort_runtime, launcher, java_home)

        ort_path = str(launcher)
        await log("ORT installed successfully.")
        await log(f"Launcher: {launcher}")
        await log(f"Install home: {install_home}")
        if java_home:
            await log(f"JAVA_HOME embedded in launcher: {java_home}")
        return 0, ort_path

    except Exception as exc:
        await log(f"[error] ORT install failed: {exc}")
        return 1, ort_path
