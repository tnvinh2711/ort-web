"""Install missing tools and project-local dependencies before ORT runs.

Flow per detected package manager:
  1. Check if the tool binary exists.
  2. If missing → auto-install the tool (platform-aware).
  3. Run the project-level install command (npm install, mvn dependency:resolve, …).
"""
from __future__ import annotations

import asyncio
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
from app.features.jobs.event_contract import EVENT_LOG, make_event
from app.features.jobs.log_stream import log_stream_hub

_LogFn = Callable[[str], Awaitable[None]]

_MAVEN_VERSION = "3.9.9"
_MAVEN_URL = (
    f"https://dlcdn.apache.org/maven/maven-3/{_MAVEN_VERSION}/binaries/"
    f"apache-maven-{_MAVEN_VERSION}-bin.tar.gz"
)
_GRADLE_VERSION = "8.14"
_GRADLE_URL = (
    f"https://services.gradle.org/distributions/"
    f"gradle-{_GRADLE_VERSION}-bin.zip"
)


# ---------------------------------------------------------------------------
# Logging / streaming helpers
# ---------------------------------------------------------------------------

async def _log(job_id: str, log_file: Path, line: str) -> None:
    with log_file.open("a", encoding="utf-8") as out:
        out.write(line)
    await log_stream_hub.publish(job_id, make_event(EVENT_LOG, line=line))


def _make_log_fn(job_id: str, log_file: Path) -> _LogFn:
    async def _fn(line: str) -> None:
        await _log(job_id, log_file, line if line.endswith("\n") else line + "\n")
    return _fn


async def _stream(log_fn: _LogFn, *args: str, cwd: str, env: Optional[dict] = None) -> int:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip()
        if line:
            await log_fn(line + "\n")
    return await proc.wait()


def _which(*cmds: str) -> Optional[str]:
    for c in cmds:
        p = shutil.which(c)
        if p:
            return p
    return None


def _local_bin() -> Path:
    return settings.bin_dir


def _write_launcher(path: Path, body: str, *, executable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    if executable and os.name != "nt":
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download_blocking(
    url: str, dest: Path, log_fn: _LogFn, loop: asyncio.AbstractEventLoop
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ort-web-env-installer"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        last_pct = -1
        with dest.open("wb") as f:
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
                        msg = f"  {pct}% ({mb}/{total // (1024*1024)} MB)\n"
                        asyncio.run_coroutine_threadsafe(log_fn(msg), loop)


# ---------------------------------------------------------------------------
# Tool auto-installers  (return True = tool now available)
# ---------------------------------------------------------------------------

async def _install_node(log_fn: _LogFn) -> bool:
    system = platform.system()
    await log_fn(f"  Installing Node.js ({system})...\n")
    if system == "Darwin":
        brew = _which("brew")
        if brew:
            return await _stream(log_fn, brew, "install", "node", cwd="/tmp") == 0
    elif system == "Linux":
        for mgr, args in [
            (_which("apt-get"), ["sudo", "apt-get", "install", "-y", "nodejs", "npm"]),
            (_which("dnf"),     ["sudo", "dnf",     "install", "-y", "nodejs", "npm"]),
            (_which("yum"),     ["sudo", "yum",     "install", "-y", "nodejs", "npm"]),
        ]:
            if mgr and await _stream(log_fn, *args, cwd="/tmp") == 0:
                return True
    elif system == "Windows":
        winget = _which("winget")
        if winget:
            rc = await _stream(
                log_fn, winget, "install", "--id", "OpenJS.NodeJS.LTS",
                "--exact", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity",
                cwd=os.environ.get("TEMP", "C:\\Temp"),
            )
            if rc == 0:
                return True
        choco = _which("choco")
        if choco:
            return await _stream(log_fn, choco, "install", "nodejs-lts", "-y", "--no-progress",
                                 cwd=os.environ.get("TEMP", "C:\\Temp")) == 0
    await log_fn("  Cannot auto-install Node.js. Visit https://nodejs.org\n")
    return False


async def _install_pnpm(log_fn: _LogFn) -> bool:
    npm = _which("npm")
    if npm:
        await log_fn("  Installing pnpm via npm...\n")
        return await _stream(log_fn, npm, "install", "-g", "pnpm", cwd=tempfile.gettempdir()) == 0
    return False


async def _install_yarn(log_fn: _LogFn) -> bool:
    corepack = _which("corepack")
    if corepack:
        await log_fn("  Enabling Yarn via corepack...\n")
        return await _stream(log_fn, corepack, "enable", "yarn", cwd=tempfile.gettempdir()) == 0
    npm = _which("npm")
    if npm:
        await log_fn("  Installing Yarn via npm...\n")
        return await _stream(log_fn, npm, "install", "-g", "yarn", cwd=tempfile.gettempdir()) == 0
    return False


async def _install_maven(log_fn: _LogFn) -> bool:
    await log_fn(f"  Downloading Apache Maven {_MAVEN_VERSION}...\n")
    loop = asyncio.get_running_loop()
    local_bin = _local_bin()

    with tempfile.TemporaryDirectory(prefix="maven-") as tmp:
        tmp_dir = Path(tmp)
        archive = tmp_dir / f"apache-maven-{_MAVEN_VERSION}-bin.tar.gz"
        try:
            await asyncio.to_thread(_download_blocking, _MAVEN_URL, archive, log_fn, loop)
        except Exception as exc:
            await log_fn(f"  Download failed: {exc}\n")
            return False

        extract_dir = tmp_dir / "x"
        extract_dir.mkdir()
        try:
            await asyncio.to_thread(lambda: tarfile.open(archive, "r:gz").extractall(extract_dir))
        except Exception as exc:
            await log_fn(f"  Extraction failed: {exc}\n")
            return False

        subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        if not subdirs:
            return False

        maven_home = local_bin / ".maven-dist"
        if maven_home.exists():
            shutil.rmtree(maven_home)
        shutil.copytree(subdirs[0], maven_home)

    if os.name == "nt":
        launcher = local_bin / "mvn.bat"
        _write_launcher(launcher, f'@call "{maven_home / "bin" / "mvn.bat"}" %*\r\n', executable=False)
    else:
        launcher = local_bin / "mvn"
        _write_launcher(launcher, f'#!/usr/bin/env sh\nexec "{maven_home / "bin" / "mvn"}" "$@"\n')

    await log_fn(f"  Maven installed: {launcher}\n")
    return True


async def _install_gradle(log_fn: _LogFn, work_dir: str = "") -> bool:
    # Gradle wrapper takes priority — no network download needed.
    if work_dir:
        w = "gradlew.bat" if os.name == "nt" else "gradlew"
        wrapper = Path(work_dir) / w
        if wrapper.exists():
            if os.name != "nt":
                mode = wrapper.stat().st_mode
                wrapper.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            await log_fn(f"  Using Gradle wrapper: {wrapper}\n")
            return True

    await log_fn(f"  Downloading Gradle {_GRADLE_VERSION}...\n")
    loop = asyncio.get_running_loop()
    local_bin = _local_bin()

    with tempfile.TemporaryDirectory(prefix="gradle-") as tmp:
        tmp_dir = Path(tmp)
        archive = tmp_dir / f"gradle-{_GRADLE_VERSION}-bin.zip"
        try:
            await asyncio.to_thread(_download_blocking, _GRADLE_URL, archive, log_fn, loop)
        except Exception as exc:
            await log_fn(f"  Download failed: {exc}\n")
            return False

        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp_dir / "x")
        except Exception as exc:
            await log_fn(f"  Extraction failed: {exc}\n")
            return False

        subdirs = [d for d in (tmp_dir / "x").iterdir() if d.is_dir()]
        if not subdirs:
            return False
        gradle_home = local_bin / ".gradle-dist"
        if gradle_home.exists():
            shutil.rmtree(gradle_home)
        shutil.copytree(subdirs[0], gradle_home)

    if os.name == "nt":
        launcher = local_bin / "gradle.bat"
        _write_launcher(launcher, f'@call "{gradle_home / "bin" / "gradle.bat"}" %*\r\n', executable=False)
    else:
        launcher = local_bin / "gradle"
        _write_launcher(launcher, f'#!/usr/bin/env sh\nexec "{gradle_home / "bin" / "gradle"}" "$@"\n')

    await log_fn(f"  Gradle installed: {launcher}\n")
    return True


async def _install_poetry(log_fn: _LogFn) -> bool:
    pip = _which("pip3", "pip")
    if pip:
        await log_fn("  Installing Poetry via pip...\n")
        # No --user: install into the active venv so the binary lands in
        # venv/Scripts, which executor.py adds to PATH for ORT subprocesses.
        return await _stream(log_fn, pip, "install", "poetry",
                             cwd=tempfile.gettempdir()) == 0
    return False


async def _install_bundler(log_fn: _LogFn) -> bool:
    gem = _which("gem")
    if gem:
        await log_fn("  Installing Bundler via gem...\n")
        return await _stream(log_fn, gem, "install", "bundler",
                             cwd=tempfile.gettempdir()) == 0
    return False


async def _install_composer(log_fn: _LogFn) -> bool:
    php = _which("php")
    if not php:
        await log_fn("  PHP not found; cannot install Composer.\n")
        return False
    await log_fn("  Downloading Composer PHAR...\n")
    loop = asyncio.get_running_loop()
    local_bin = _local_bin()
    phar = local_bin / "composer.phar"
    try:
        await asyncio.to_thread(
            _download_blocking, "https://getcomposer.org/composer-stable.phar", phar, log_fn, loop
        )
    except Exception as exc:
        await log_fn(f"  Download failed: {exc}\n")
        return False

    if os.name == "nt":
        launcher = local_bin / "composer.bat"
        _write_launcher(launcher, f'@php "{phar}" %*\r\n', executable=False)
    else:
        launcher = local_bin / "composer"
        _write_launcher(launcher, f'#!/usr/bin/env sh\nexec php "{phar}" "$@"\n')
    await log_fn(f"  Composer installed: {launcher}\n")
    return True


async def _install_conan(log_fn: _LogFn) -> bool:
    pip = _which("pip3", "pip")
    if pip:
        await log_fn("  Installing Conan via pip...\n")
        # No --user: install into the active venv so the binary lands in
        # venv/Scripts, which executor.py adds to PATH for ORT subprocesses.
        return await _stream(log_fn, pip, "install", "conan",
                             cwd=tempfile.gettempdir()) == 0
    return False


async def _install_go(log_fn: _LogFn) -> bool:
    system = platform.system()
    await log_fn(f"  Installing Go ({system})...\n")
    if system == "Darwin":
        brew = _which("brew")
        if brew:
            return await _stream(log_fn, brew, "install", "go", cwd="/tmp") == 0
    elif system == "Linux":
        for mgr, args in [
            (_which("apt-get"), ["sudo", "apt-get", "install", "-y", "golang-go"]),
            (_which("dnf"),     ["sudo", "dnf",     "install", "-y", "golang"]),
        ]:
            if mgr and await _stream(log_fn, *args, cwd="/tmp") == 0:
                return True
    elif system == "Windows":
        winget = _which("winget")
        if winget:
            return await _stream(
                log_fn, winget, "install", "--id", "GoLang.Go",
                "--exact", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
                cwd=os.environ.get("TEMP", "C:\\Temp"),
            ) == 0
    await log_fn("  Cannot auto-install Go. Visit https://go.dev/dl\n")
    return False


async def _install_cargo(log_fn: _LogFn) -> bool:
    if platform.system() == "Windows":
        await log_fn("  Install Rust via https://rustup.rs (rustup-init.exe)\n")
        return False
    rustup = _which("rustup")
    if rustup:
        return await _stream(log_fn, rustup, "update", "stable", cwd="/tmp") == 0
    await log_fn("  Downloading rustup...\n")
    loop = asyncio.get_running_loop()
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "rustup-init.sh"
        try:
            await asyncio.to_thread(_download_blocking, "https://sh.rustup.rs", script, log_fn, loop)
        except Exception as exc:
            await log_fn(f"  Download failed: {exc}\n")
            return False
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        env = os.environ.copy()
        env["RUSTUP_INIT_SKIP_PATH_CHECK"] = "yes"
        return await _stream(log_fn, str(script), "-y", "--no-modify-path",
                             cwd=tmp, env=env) == 0


async def _install_dotnet(log_fn: _LogFn) -> bool:
    system = platform.system()
    await log_fn(f"  Installing .NET SDK ({system})...\n")
    if system == "Darwin":
        brew = _which("brew")
        if brew:
            return await _stream(log_fn, brew, "install", "--cask", "dotnet-sdk", cwd="/tmp") == 0
    elif system == "Linux":
        for mgr, args in [
            (_which("apt-get"), ["sudo", "apt-get", "install", "-y", "dotnet-sdk-8.0"]),
            (_which("dnf"),     ["sudo", "dnf",     "install", "-y", "dotnet-sdk-8.0"]),
        ]:
            if mgr and await _stream(log_fn, *args, cwd="/tmp") == 0:
                return True
    elif system == "Windows":
        winget = _which("winget")
        if winget:
            return await _stream(
                log_fn, winget, "install", "--id", "Microsoft.DotNet.SDK.8",
                "--exact", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
                cwd=os.environ.get("TEMP", "C:\\Temp"),
            ) == 0
    await log_fn("  Cannot auto-install .NET. Visit https://dot.net\n")
    return False


# ---------------------------------------------------------------------------
# Detect what the project needs (always, regardless of tool availability)
# ---------------------------------------------------------------------------

def detect_install_tasks(work_dir: str) -> list[dict]:
    """
    Inspect manifest/lock files and return one install task per detected
    package manager.  Each task includes which tool to check/install and
    the command to run for the project-level install.

    Tasks are returned even when the tool is not currently installed — the
    runner will attempt to install it first.
    """
    wd = Path(work_dir)
    tasks: list[dict] = []

    def task(
        label: str,
        tool_cmds: list[str],
        install_tool,           # async (log_fn) -> bool, or None
        project_cmd: list[str], # command tokens; first token = tool binary
        *,
        cwd: str = work_dir,
        optional: bool = False,
    ) -> dict:
        return {
            "label": label,
            "tool_cmds": tool_cmds,
            "install_tool": install_tool,
            "project_cmd": project_cmd,
            "cwd": cwd,
            "optional": optional,
        }

    # ── Node.js ─────────────────────────────────────────────────────────
    # Goal is cache warm-up, not a strict reproducible install, so we use
    # permissive flags: --legacy-peer-deps handles mismatched peer versions,
    # --ignore-scripts skips lifecycle hooks that may fail in CI-like envs.
    # All Node.js tasks are optional — a failed npm install should not block
    # ORT from running (ORT will attempt its own npm install anyway).
    for root, dirs, files in os.walk(wd):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        rp = Path(root)
        if "package.json" not in files:
            continue
        pkg_root = str(rp)
        if "pnpm-lock.yaml" in files:
            tasks.append(task(
                "pnpm install", ["pnpm"],
                _install_pnpm,
                ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"],
                cwd=pkg_root,
                optional=True,
            ))
        elif "yarn.lock" in files:
            tasks.append(task(
                "yarn install", ["yarn"],
                _install_yarn,
                ["yarn", "install", "--frozen-lockfile", "--ignore-scripts"],
                cwd=pkg_root,
                optional=True,
            ))
        else:
            # Always use "install" (not "ci") — more permissive, tolerates
            # missing/invalid versions that would fail npm ci.
            tasks.append(task(
                "npm install", ["npm"],
                _install_node,
                ["npm", "install", "--prefer-offline", "--legacy-peer-deps",
                 "--ignore-scripts", "--no-audit", "--no-fund"],
                cwd=pkg_root,
                optional=True,
            ))
        break  # top-level only

    # ── Maven ───────────────────────────────────────────────────────────
    if (wd / "pom.xml").exists():
        tasks.append(task(
            "mvn dependency:resolve", ["mvn"],
            _install_maven,
            ["mvn", "dependency:resolve", "-q", "--no-transfer-progress", "-DskipTests"],
        ))

    # ── Gradle ──────────────────────────────────────────────────────────
    if (wd / "build.gradle").exists() or (wd / "build.gradle.kts").exists():
        if os.name == "nt":
            wrapper = wd / "gradlew.bat"
            tool_cmd = str(wrapper) if wrapper.exists() else "gradle"
        else:
            wrapper = wd / "gradlew"
            if wrapper.exists():
                mode = wrapper.stat().st_mode
                wrapper.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                tool_cmd = str(wrapper)
            else:
                tool_cmd = "gradle"
        tasks.append(task(
            "gradle dependencies",
            [tool_cmd, "gradle"],
            lambda log_fn: _install_gradle(log_fn, work_dir),
            [tool_cmd, "dependencies", "--configuration", "runtimeClasspath", "-q"],
            optional=True,
        ))

    # ── Python ──────────────────────────────────────────────────────────
    if (wd / "poetry.lock").exists() and (wd / "pyproject.toml").exists():
        tasks.append(task(
            "poetry install", ["poetry"],
            _install_poetry,
            ["poetry", "install", "--no-interaction", "--no-root"],
        ))
    elif (wd / "requirements.txt").exists():
        pip = _which("pip3", "pip") or "pip3"
        tasks.append(task(
            "pip install -r requirements.txt", ["pip3", "pip"],
            None,  # pip ships with Python; if missing, nothing we can do easily
            [pip, "install", "-r", "requirements.txt", "-q", "--user"],
        ))
    elif (wd / "setup.py").exists() or (wd / "pyproject.toml").exists():
        pip = _which("pip3", "pip") or "pip3"
        tasks.append(task(
            "pip install -e .", ["pip3", "pip"], None,
            [pip, "install", "-e", ".", "-q", "--user"],
            optional=True,
        ))

    # ── Go ──────────────────────────────────────────────────────────────
    if (wd / "go.mod").exists():
        tasks.append(task(
            "go mod download", ["go"],
            _install_go,
            ["go", "mod", "download"],
        ))

    # ── Rust ────────────────────────────────────────────────────────────
    if (wd / "Cargo.toml").exists():
        tasks.append(task(
            "cargo fetch", ["cargo"],
            _install_cargo,
            ["cargo", "fetch"],
        ))

    # ── Ruby ────────────────────────────────────────────────────────────
    if (wd / "Gemfile").exists():
        tasks.append(task(
            "bundle install", ["bundle", "bundler"],
            _install_bundler,
            ["bundle", "install"],
        ))

    # ── PHP ─────────────────────────────────────────────────────────────
    if (wd / "composer.json").exists():
        tasks.append(task(
            "composer install", ["composer"],
            _install_composer,
            ["composer", "install", "--no-interaction", "--no-progress", "--prefer-dist"],
        ))

    # ── .NET ────────────────────────────────────────────────────────────
    if list(wd.glob("*.sln")) or list(wd.glob("**/*.csproj")):
        tasks.append(task(
            "dotnet restore", ["dotnet"],
            _install_dotnet,
            ["dotnet", "restore", "--verbosity", "minimal"],
        ))

    # ── Swift ───────────────────────────────────────────────────────────
    if (wd / "Package.swift").exists():
        tasks.append(task(
            "swift package resolve", ["swift"],
            None,
            ["swift", "package", "resolve"],
        ))

    # ── Conan (C++) ─────────────────────────────────────────────────────
    if (wd / "conanfile.txt").exists() or (wd / "conanfile.py").exists():
        tasks.append(task(
            "conan install", ["conan"],
            _install_conan,
            ["conan", "install", ".", "--build=missing"],
            optional=True,
        ))

    return tasks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def install_environment(
    job_id: str,
    work_dir: str,
    log_file: Path,
) -> int:
    """
    For each package manager detected in *work_dir*:
      1. If the tool is missing, auto-install it.
      2. Run the project-level install command.

    Returns 0 if all non-optional steps succeed, 1 otherwise.
    """
    log_fn = _make_log_fn(job_id, log_file)

    await log_fn("[env-install] --- Project environment setup ---\n")
    await log_fn(f"[env-install] Project: {work_dir}\n")

    tasks = detect_install_tasks(work_dir)
    if not tasks:
        await log_fn("[env-install] No package managers detected — nothing to install.\n")
        await log_fn("[env-install] ----------------------------------------\n")
        return 0

    await log_fn(f"[env-install] Detected {len(tasks)} task(s): "
                 + ", ".join(t["label"] for t in tasks) + "\n")

    all_ok = True

    for t in tasks:
        label     = t["label"]
        tool_cmds = t["tool_cmds"]
        installer = t["install_tool"]
        proj_cmd  = t["project_cmd"]
        cwd       = t["cwd"]
        optional  = t["optional"]

        await log_fn(f"\n[env-install] === {label} ===\n")

        # 1. Ensure tool is present
        tool_path = _which(*tool_cmds)
        if not tool_path:
            if installer:
                await log_fn(f"[env-install] '{tool_cmds[0]}' not found — installing...\n")
                try:
                    ok = await installer(log_fn)
                except Exception as exc:
                    await log_fn(f"[env-install] Install error: {exc}\n")
                    ok = False

                if ok:
                    tool_path = _which(*tool_cmds)
                    # Also check local bin dir (freshly installed tools)
                    if not tool_path:
                        local = _local_bin() / (tool_cmds[0] + (".bat" if os.name == "nt" else ""))
                        if local.exists():
                            tool_path = str(local)

                if not tool_path:
                    msg = f"[env-install] '{tool_cmds[0]}' still not available after install attempt.\n"
                    await log_fn(msg)
                    if not optional:
                        all_ok = False
                    continue
            else:
                await log_fn(
                    f"[env-install] '{tool_cmds[0]}' not found and no auto-installer available. "
                    "Install it manually.\n"
                )
                if not optional:
                    all_ok = False
                continue

        # Replace placeholder binary in project_cmd with resolved path
        cmd = [tool_path if i == 0 else arg for i, arg in enumerate(proj_cmd)]

        # 2. Run project-level install
        # For Node.js package managers, pin NPM_CONFIG_CACHE to the shared
        # runtime cache dir so downloaded packages are reused by ORT later.
        run_env: Optional[dict] = None
        if tool_cmds[0] in ("npm", "pnpm", "yarn", "corepack"):
            from app.config import settings as _settings
            run_env = os.environ.copy()
            run_env.setdefault("NPM_CONFIG_CACHE", str(_settings.npm_cache_dir))
            run_env.setdefault("NPM_CONFIG_PREFER_OFFLINE", "false")  # allow download on first run
            run_env.setdefault("NPM_CONFIG_AUDIT", "false")
            run_env.setdefault("NPM_CONFIG_FUND", "false")
            run_env.setdefault("NPM_CONFIG_PROGRESS", "false")

        await log_fn(f"[env-install] $ {' '.join(cmd)}\n")
        try:
            rc = await _stream(log_fn, *cmd, cwd=cwd, env=run_env)
        except Exception as exc:
            await log_fn(f"[env-install] Error: {exc}\n")
            rc = 1

        if rc == 0:
            await log_fn(f"[env-install] OK\n")
        else:
            await log_fn(f"[env-install] {'WARN (optional)' if optional else 'FAIL'} exit={rc}\n")
            if not optional:
                all_ok = False

    await log_fn("\n[env-install] " + ("All done." if all_ok else "Finished with errors.") + "\n")
    await log_fn("[env-install] ----------------------------------------\n")
    return 0 if all_ok else 1
