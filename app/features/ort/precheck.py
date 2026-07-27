"""Pre-flight environment checks before running ORT commands."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.config import settings
from app.features.jobs.event_contract import EVENT_LOG, make_event
from app.features.jobs.log_stream import log_stream_hub


async def _log(job_id: str, log_file: Path, line: str) -> None:
    with log_file.open("a", encoding="utf-8") as out:
        out.write(line)
    await log_stream_hub.publish(job_id, make_event(EVENT_LOG, line=line))


def _find_ort_binary() -> Optional[str]:
    """Return path to the ORT binary/script, or None if not found."""
    if os.name == "nt":
        for candidate in (
            settings.ort_install_dir / "ort.bat",
            settings.bin_dir / "ort.bat",
        ):
            if candidate.exists():
                return str(candidate)

    # Expand PATH with the dirs executor.py uses so the check matches runtime.
    extra = [str(settings.ort_install_dir), str(settings.bin_dir)]
    env_path = os.pathsep.join(extra) + os.pathsep + os.environ.get("PATH", "")
    found = shutil.which("ort", path=env_path)
    return found


def _check_java() -> tuple[bool, Optional[str]]:
    """Return (available, version_line).  version_line may be None on error."""
    java = shutil.which("java")
    if not java:
        return False, None
    try:
        result = subprocess.run(
            [java, "-version"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        # `java -version` writes to stderr on most JDKs
        out = (result.stderr or result.stdout or "").strip().splitlines()
        return True, out[0] if out else "version unknown"
    except Exception:
        return True, None


def _find_tool(detect_commands: list[str]) -> Optional[str]:
    for cmd in detect_commands:
        path = shutil.which(cmd)
        if path:
            return path
    return None


def _check_npm_version() -> tuple[Optional[str], bool]:
    """Return (version_string, is_modern).  is_modern = major >= 9."""
    npm = shutil.which("npm")
    if not npm:
        return None, True  # npm not installed — handled elsewhere
    try:
        result = subprocess.run(
            [npm, "--version"], capture_output=True, text=True, timeout=10, check=False,
        )
        ver = (result.stdout or "").strip()
        major = int(ver.split(".")[0]) if ver else 0
        return ver, major >= 9
    except Exception:
        return None, True


def _find_swift_local_path_manifests(work_dir: str) -> list[Path]:
    """Find first-party manifests that declare ``.package(path: ...)``."""
    root = Path(work_dir)
    if not root.is_dir():
        return []

    local_path_pattern = re.compile(
        r"\.package\s*\(\s*(?:name\s*:\s*[^,]+,\s*)?path\s*:",
        re.DOTALL,
    )
    prune_dirs = {
        ".build",
        ".git",
        ".gradle",
        ".idea",
        ".venv",
        ".vscode",
        "DerivedData",
        "build",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
    manifests: list[Path] = []

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [directory for directory in dirs if directory not in prune_dirs]
        if "Package.swift" not in files:
            continue

        manifest = Path(current_root) / "Package.swift"
        try:
            content = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if local_path_pattern.search(content):
            manifests.append(manifest)

    return manifests


async def _check_package_managers_for_workdir(
    job_id: str,
    work_dir: str,
    log_file: Path,
) -> None:
    """Detect project language and warn about missing package manager tools."""
    from app.features.shared.language_detector import detect_language
    from app.features.ort.properties import PACKAGE_MANAGERS, get_managers_for_language

    language: Optional[str] = await asyncio.to_thread(detect_language, work_dir)
    if not language:
        await _log(
            job_id, log_file,
            "[precheck] Language detection: no dominant language found — "
            "skipping package manager check\n",
        )
        return

    await _log(job_id, log_file, f"[precheck] Detected language: {language}\n")

    needed = set(get_managers_for_language(language))
    if not needed:
        await _log(
            job_id, log_file,
            f"[precheck] No package managers mapped for language '{language}'\n",
        )
        return

    pm_by_name = {pm["ort_name"]: pm for pm in PACKAGE_MANAGERS}
    missing_labels: list[str] = []

    for ort_name in sorted(needed):
        pm = pm_by_name.get(ort_name)
        if not pm:
            continue
        path = _find_tool(pm["detect_commands"])
        if ort_name == "Gradle" and not path:
            project = Path(work_dir)
            wrappers = (
                project / "gradlew",
                project / "gradlew.bat",
            )
            wrapper = next((candidate for candidate in wrappers if candidate.is_file()), None)
            if wrapper:
                path = str(wrapper)
        if path:
            await _log(job_id, log_file, f"[precheck] OK   {pm['label']}: {path}\n")
        else:
            tried = ", ".join(pm["detect_commands"])
            await _log(
                job_id, log_file,
                f"[precheck] WARN {pm['label']} not found (tried: {tried}) — "
                f"ORT may fail to resolve {language} dependencies\n",
            )
            missing_labels.append(pm["label"])

    if missing_labels:
        await _log(
            job_id, log_file,
            f"[precheck] WARN Missing: {', '.join(missing_labels)}. "
            "Install them before running analysis.\n",
        )

    if language == "swift":
        local_manifests = await asyncio.to_thread(
            _find_swift_local_path_manifests,
            work_dir,
        )
        if local_manifests:
            project_root = Path(work_dir).resolve()
            paths = ", ".join(
                str(path.resolve().relative_to(project_root))
                for path in local_manifests[:5]
            )
            more = (
                f" (+{len(local_manifests) - 5} more)"
                if len(local_manifests) > 5
                else ""
            )
            await _log(
                job_id,
                log_file,
                "[precheck] WARN Swift local path dependencies found in "
                f"{paths}{more}. ORT SwiftPM may report "
                "MalformedPackageURLException for .package(path: ...); "
                "the local source remains covered by ScanCode and Trivy.\n",
            )


async def run_environment_precheck(
    job_id: str,
    work_dir: str,
    log_file: Path,
    command_tokens: list[str],
) -> bool:
    """Run pre-flight checks and log results to the job log.

    Checks ORT binary and Java (critical — returns False if either is absent).
    For *analyze* commands also detects the project language and warns about
    missing package manager tools (non-blocking).

    Returns True when all critical checks pass, False otherwise.
    """
    subcommand = next(
        (t for t in command_tokens if t in {"analyze", "scan", "advise", "report"}),
        None,
    )

    await _log(job_id, log_file, "[precheck] --- Environment pre-flight check ---\n")

    critical_ok = True

    # 1. ORT binary
    ort_path = _find_ort_binary()
    if ort_path:
        await _log(job_id, log_file, f"[precheck] OK   ORT binary: {ort_path}\n")
    else:
        await _log(
            job_id, log_file,
            "[precheck] FAIL ORT binary not found. "
            "Run the ORT installer from the Setup page.\n",
        )
        critical_ok = False

    # 2. Java
    java_found, java_version = _check_java()
    if java_found:
        await _log(job_id, log_file, f"[precheck] OK   Java: {java_version or 'version unknown'}\n")
    else:
        await _log(
            job_id, log_file,
            "[precheck] FAIL Java not found in PATH. "
            "ORT requires Java 21+. Install a JDK and ensure it is in PATH.\n",
        )
        critical_ok = False

    # 3. npm version (warn if < 9 — old npm has bugs with packages published by npm 10+)
    npm_ver, npm_modern = _check_npm_version()
    if npm_ver and not npm_modern:
        await _log(
            job_id, log_file,
            f"[precheck] WARN npm {npm_ver} is outdated (need 9+). "
            "Old npm may fail with 'Invalid Version' on packages published by newer npm. "
            "Upgrade: npm install -g npm@latest\n",
        )
    elif npm_ver:
        await _log(job_id, log_file, f"[precheck] OK   npm: {npm_ver}\n")

    # 4. Trivy (analyze runs it alongside ORT). Non-blocking: it auto-installs
    # at scan time, so a miss here is informational only.
    if subcommand == "analyze":
        trivy_path = shutil.which("trivy") or (
            str(settings.bin_dir / ("trivy.exe" if os.name == "nt" else "trivy"))
            if (settings.bin_dir / ("trivy.exe" if os.name == "nt" else "trivy")).exists()
            else None
        )
        if trivy_path:
            await _log(job_id, log_file, f"[precheck] OK   Trivy: {trivy_path}\n")
        else:
            await _log(
                job_id, log_file,
                "[precheck] INFO Trivy not found — it will auto-install on first scan.\n",
            )

    # 5. Package managers (only for analyze — other subcommands work on existing result files)
    if subcommand == "analyze":
        await _check_package_managers_for_workdir(job_id, work_dir, log_file)

    if critical_ok:
        await _log(job_id, log_file, "[precheck] Environment looks ready.\n")
    else:
        await _log(job_id, log_file, "[precheck] Critical dependencies missing — job will not start.\n")

    await _log(job_id, log_file, "[precheck] --------------------------------------------\n")
    return critical_ok
