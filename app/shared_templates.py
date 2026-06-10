from __future__ import annotations

import os
import platform
import shlex

from fastapi.templating import Jinja2Templates

from app._version import __version__


def _quote_if_spaced(token: str) -> str:
    return f'"{token}"' if " " in token else token


def _display_trivy_command(target: str) -> str:
    """Render the Trivy sentinel as the readable `trivy fs ...` it runs."""
    from app.config import settings

    parts = [
        "trivy", "fs",
        "--cache-dir", str(settings.trivy_cache_dir),
        "--scanners", settings.trivy_scanners,
        "--format", "json", "--output", "trivy-result.json",
    ]
    if settings.trivy_severity.strip():
        parts += ["--severity", settings.trivy_severity]
    if settings.trivy_offline:
        parts += ["--offline-scan", "--skip-db-update", "--skip-check-update"]
    parts.append(target)
    return " ".join(_quote_if_spaced(p) for p in parts)


def display_ort_command(command: str) -> str:
    """Format an ORT command string for display on the current platform."""
    if not command:
        return command

    if command == "__trivy_scan__" or command.startswith("__trivy_scan__::"):
        target = command.split("::", 1)[1] if "::" in command else ""
        return _display_trivy_command(target)

    if command.startswith("__"):
        return command

    if os.name == "nt":
        try:
            tokens = shlex.split(command)
        except ValueError:
            return command
        if tokens and tokens[0] == "ort":
            tokens[0] = "ort.bat"
        parts = []
        for token in tokens:
            if " " in token:
                parts.append(f'"{token}"')
            else:
                parts.append(token)
        return " ".join(parts)

    return command


def platform_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Windows":
        return "Windows"
    return "Linux"


templates = Jinja2Templates(directory="app/templates")
templates.env.globals["display_ort_command"] = display_ort_command
templates.env.globals["platform_name"] = platform_name()
templates.env.globals["app_version"] = __version__
