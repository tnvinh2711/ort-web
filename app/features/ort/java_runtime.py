"""Resolve one Java runtime for ORT precheck and execution."""
from __future__ import annotations

import os
import platform
import re
import shutil
import struct
import subprocess
import zipfile
from glob import glob
from pathlib import Path
from typing import Mapping


def _java_name() -> str:
    return "java.exe" if os.name == "nt" else "java"


def _valid_java_home(value: str | os.PathLike[str] | None) -> Path | None:
    if not value:
        return None
    home = Path(value).expanduser().resolve()
    return home if (home / "bin" / _java_name()).is_file() else None


def java_major_version(java_bin: str | Path) -> int | None:
    try:
        result = subprocess.run(
            [str(java_bin), "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (getattr(result, "stderr", "") or "") + (
        getattr(result, "stdout", "") or ""
    )
    match = re.search(r'version "(\d+)', output)
    return int(match.group(1)) if match else None


def _compatible_java_home(
    value: str | os.PathLike[str] | None,
    minimum_major: int,
) -> Path | None:
    home = _valid_java_home(value)
    if not home:
        return None
    java = home / "bin" / _java_name()
    return home if (java_major_version(java) or 0) >= minimum_major else None


def ort_required_java(launcher: str | Path | None) -> int:
    """Infer ORT's minimum Java from OrtMainKt.class; default to Java 21."""
    if not launcher:
        return 21

    path = Path(launcher).expanduser()
    candidates: list[Path] = []
    resolved = path.resolve()
    for item in (path, resolved):
        if item.is_dir():
            candidates.append(item)
        else:
            candidates.extend([item.parent.parent, item.parent / ".ort-dist" / "current"])

    # Wrapper launchers live next to .ort-dist/current.
    candidates.extend(
        [
            path.parent / ".ort-dist" / "current",
            resolved.parent / ".ort-dist" / "current",
        ]
    )

    seen: set[Path] = set()
    for home in candidates:
        home = home.resolve()
        if home in seen:
            continue
        seen.add(home)
        for jar in sorted((home / "lib").glob("cli-*.jar")):
            if jar.name.endswith("-pathing.jar"):
                continue
            try:
                with zipfile.ZipFile(jar) as archive:
                    header = archive.read("org/ossreviewtoolkit/cli/OrtMainKt.class")[:8]
                if len(header) == 8 and header[:4] == b"\xca\xfe\xba\xbe":
                    class_major = struct.unpack(">H", header[6:8])[0]
                    return max(21, class_major - 44)
            except (OSError, KeyError, zipfile.BadZipFile):
                continue
    return 21


def resolve_java_home(
    environment: Mapping[str, str] | None = None,
    minimum_major: int = 21,
) -> Path | None:
    """Return the Java home shared by precheck and ORT.

    ``ORT_WEB_JAVA_HOME`` is the application-specific override. A valid
    ``JAVA_HOME`` is next, followed by the Java executable found on ``PATH``.
    """
    env = environment or os.environ
    for key in ("ORT_WEB_JAVA_HOME", "JAVA_HOME"):
        home = _compatible_java_home(env.get(key), minimum_major)
        if home:
            return home

    java = shutil.which(_java_name(), path=env.get("PATH"))
    if java:
        resolved = Path(java).resolve()
        inferred = resolved.parent.parent

        if inferred != Path("/usr"):
            home = _compatible_java_home(inferred, minimum_major)
            if home:
                return home

    system = platform.system()
    if system == "Darwin":
        # Ask macOS for a compatible JDK even when JAVA_HOME points to an older
        # runtime. This is the key path for ORT releases compiled with a newer JDK.
        try:
            result = subprocess.run(
                ["/usr/libexec/java_home", "-v", f"{minimum_major}+"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                home = _compatible_java_home(result.stdout.strip(), minimum_major)
                if home:
                    return home
        except (OSError, subprocess.SubprocessError):
            pass

        for prefix in ("/opt/homebrew", "/usr/local"):
            for formula in ("openjdk", f"openjdk@{minimum_major}"):
                home = (
                    Path(prefix)
                    / "opt"
                    / formula
                    / "libexec"
                    / "openjdk.jdk"
                    / "Contents"
                    / "Home"
                )
                compatible = _compatible_java_home(home, minimum_major)
                if compatible:
                    return compatible
    elif system == "Linux":
        for candidate in glob("/usr/lib/jvm/*"):
            compatible = _compatible_java_home(candidate, minimum_major)
            if compatible:
                return compatible
    elif system == "Windows":
        candidates: list[str] = []
        for base_key in ("LOCALAPPDATA", "ProgramFiles", "ProgramW6432"):
            base = env.get(base_key)
            if base:
                candidates.extend(glob(str(Path(base) / "*" / "jdk-*")))
                candidates.extend(glob(str(Path(base) / "Java" / "jdk-*")))
        for candidate in candidates:
            compatible = _compatible_java_home(candidate, minimum_major)
            if compatible:
                return compatible

    return None


def apply_java_runtime(
    environment: dict[str, str],
    minimum_major: int = 21,
) -> Path | None:
    """Normalize JAVA_HOME and PATH in-place and return the selected home."""
    home = resolve_java_home(environment, minimum_major)
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
