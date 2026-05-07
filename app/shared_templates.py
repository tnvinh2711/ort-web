from __future__ import annotations

import os
import platform
import shlex

from fastapi.templating import Jinja2Templates

from app._version import __version__


def display_ort_command(command: str) -> str:
    """Format an ORT command string for display on the current platform."""
    if not command or command.startswith("__"):
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
