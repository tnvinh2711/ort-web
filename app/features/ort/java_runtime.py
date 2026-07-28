"""Resolve one Java runtime for ORT precheck and execution."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Mapping


def _java_name() -> str:
    return "java.exe" if os.name == "nt" else "java"


def _valid_java_home(value: str | os.PathLike[str] | None) -> Path | None:
    if not value:
        return None
    home = Path(value).expanduser().resolve()
    return home if (home / "bin" / _java_name()).is_file() else None


def resolve_java_home(environment: Mapping[str, str] | None = None) -> Path | None:
    """Return the Java home shared by precheck and ORT.

    ``ORT_WEB_JAVA_HOME`` is the application-specific override. A valid
    ``JAVA_HOME`` is next, followed by the Java executable found on ``PATH``.
    """
    env = environment or os.environ
    for key in ("ORT_WEB_JAVA_HOME", "JAVA_HOME"):
        home = _valid_java_home(env.get(key))
        if home:
            return home

    java = shutil.which(_java_name(), path=env.get("PATH"))
    if not java:
        return None
    resolved = Path(java).resolve()
    inferred = resolved.parent.parent

    # /usr/bin/java on macOS is a system launcher, not a JDK's real binary.
    # Resolve it through java_home instead of incorrectly returning /usr.
    if platform.system() == "Darwin" and inferred == Path("/usr"):
        try:
            result = subprocess.run(
                ["/usr/libexec/java_home"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                return _valid_java_home(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return None

    return _valid_java_home(inferred)


def apply_java_runtime(environment: dict[str, str]) -> Path | None:
    """Normalize JAVA_HOME and PATH in-place and return the selected home."""
    home = resolve_java_home(environment)
    if not home:
        return None

    environment["JAVA_HOME"] = str(home)
    java_bin = str(home / "bin")
    path_parts = [
        part
        for part in environment.get("PATH", "").split(os.pathsep)
        if part and Path(part).expanduser().resolve() != Path(java_bin).resolve()
    ]
    environment["PATH"] = os.pathsep.join([java_bin, *path_parts])
    return home
