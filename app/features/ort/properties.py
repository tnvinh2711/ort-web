"""Service for managing ORT ort.properties configuration."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

# ORT package manager name → detection info
PACKAGE_MANAGERS: list[dict] = [
    {
        "ort_name": "Gradle",
        "label": "Gradle",
        "detect_commands": ["gradle", "gradlew"],
        "also_needs": ["java"],
        "description": "Android / Java Gradle builds",
        "category": "jvm",
    },
    {
        "ort_name": "Maven",
        "label": "Maven",
        "detect_commands": ["mvn"],
        "also_needs": ["java"],
        "description": "Java Maven builds (pom.xml)",
        "category": "jvm",
    },
    {
        "ort_name": "NPM",
        "label": "npm",
        "detect_commands": ["npm"],
        "also_needs": [],
        "description": "Node.js / npm (package.json)",
        "category": "nodejs",
    },
    {
        "ort_name": "PNPM",
        "label": "pnpm",
        "detect_commands": ["pnpm"],
        "also_needs": [],
        "description": "Node.js / pnpm (pnpm-lock.yaml)",
        "category": "nodejs",
    },
    {
        "ort_name": "Yarn",
        "label": "Yarn",
        "detect_commands": ["yarn"],
        "also_needs": [],
        "description": "Node.js / Yarn (yarn.lock)",
        "category": "nodejs",
    },
    {
        "ort_name": "PIP",
        "label": "pip / Python",
        "detect_commands": ["pip3", "pip", "python3", "python"],
        "also_needs": [],
        "description": "Python pip packages (requirements.txt)",
        "category": "python",
    },
    {
        "ort_name": "Poetry",
        "label": "Poetry",
        "detect_commands": ["poetry"],
        "also_needs": [],
        "description": "Python Poetry (pyproject.toml)",
        "category": "python",
    },
    {
        "ort_name": "GoMod",
        "label": "Go Modules",
        "detect_commands": ["go"],
        "also_needs": [],
        "description": "Go modules (go.mod)",
        "category": "go",
    },
    {
        "ort_name": "Cargo",
        "label": "Cargo",
        "detect_commands": ["cargo"],
        "also_needs": [],
        "description": "Rust Cargo (Cargo.toml)",
        "category": "rust",
    },
    {
        "ort_name": "Conan",
        "label": "Conan",
        "detect_commands": ["conan"],
        "also_needs": [],
        "description": "C/C++ Conan (conanfile.txt)",
        "category": "cpp",
    },
    {
        "ort_name": "Bundler",
        "label": "Bundler",
        "detect_commands": ["bundle", "bundler"],
        "also_needs": [],
        "description": "Ruby Bundler (Gemfile)",
        "category": "ruby",
    },
    {
        "ort_name": "Composer",
        "label": "Composer",
        "detect_commands": ["composer"],
        "also_needs": [],
        "description": "PHP Composer (composer.json)",
        "category": "php",
    },
    {
        "ort_name": "SwiftPM",
        "label": "Swift PM",
        "detect_commands": ["swift"],
        "also_needs": [],
        "description": "Swift Package Manager (Package.swift)",
        "category": "swift",
    },
    {
        "ort_name": "CocoaPods",
        "label": "CocoaPods",
        "detect_commands": ["pod"],
        "also_needs": [],
        "description": "iOS/macOS CocoaPods (Podfile)",
        "category": "swift",
    },
    {
        "ort_name": "Carthage",
        "label": "Carthage",
        "detect_commands": ["carthage"],
        "also_needs": [],
        "description": "iOS/macOS Carthage (Cartfile)",
        "category": "swift",
    },
    {
        "ort_name": "NuGet",
        "label": ".NET / NuGet",
        "detect_commands": ["dotnet"],
        "also_needs": [],
        "description": "C# .NET / NuGet (.csproj, .sln)",
        "category": "dotnet",
    },
]


def get_managers_for_language(language: str) -> list[str]:
    """Return ORT package manager names relevant to a detected language.

    Uses the category field on each PACKAGE_MANAGERS entry and maps
    through ``LANGUAGE_TO_CATEGORIES`` from the language detector.
    """
    from app.features.shared.language_detector import get_package_manager_categories

    categories = set(get_package_manager_categories(language))
    if not categories:
        return []
    return [pm["ort_name"] for pm in PACKAGE_MANAGERS if pm["category"] in categories]


def get_available_managers_for_language(language: str) -> list[str]:
    """Return only the ORT package manager names for *language* whose CLI tools
    are actually present in PATH.

    ORT throws an unhandled exception (and kills the job) when it tries to
    invoke a package manager binary that does not exist.  Filtering here ensures
    ort.properties only lists tools ORT can actually call.
    """
    all_managers = get_managers_for_language(language)
    pm_by_name = {pm["ort_name"]: pm for pm in PACKAGE_MANAGERS}
    available = []
    for ort_name in all_managers:
        pm = pm_by_name.get(ort_name)
        if pm and any(shutil.which(cmd) for cmd in pm["detect_commands"]):
            available.append(ort_name)
    return available


def auto_generate_ort_properties(
    language: str, custom_paths: Optional[dict[str, str]] = None
) -> Path:
    """Auto-generate ``ort.properties`` with package managers for *language*.

    Only managers whose CLI tools are present in PATH are enabled — ORT crashes
    with an unhandled exception if it encounters a missing tool.
    """
    managers = get_available_managers_for_language(language)
    return write_ort_properties(managers, custom_paths)


def _detect_command_path(commands: list[str]) -> Optional[str]:
    """Return the path of the first command found on PATH, or None."""
    for cmd in commands:
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _get_version(cmd_path: str) -> Optional[str]:
    """Try to get version string from a tool binary."""
    try:
        result = subprocess.run(
            [cmd_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        out = (result.stdout or result.stderr or "").strip()
        # Return first non-empty line, capped at 80 chars
        for line in out.splitlines():
            line = line.strip()
            if line:
                return line[:80]
    except Exception:
        pass
    return None


def detect_all_tools() -> list[dict]:
    """
    Detect all supported package manager tools on PATH.

    Returns list of dicts with keys:
        ort_name, label, description, category,
        detected, path, version
    """
    results = []
    for pm in PACKAGE_MANAGERS:
        path = _detect_command_path(pm["detect_commands"])
        version = _get_version(path) if path else None
        results.append(
            {
                "ort_name": pm["ort_name"],
                "label": pm["label"],
                "description": pm["description"],
                "category": pm["category"],
                "detect_commands": pm["detect_commands"],
                "detected": path is not None,
                "path": path,
                "version": version,
            }
        )
    return results


def get_ort_properties_path() -> Path:
    """Return the standard ORT properties file path (~/.ort/ort.properties)."""
    return Path.home() / ".ort" / "ort.properties"


def read_ort_properties() -> str:
    """Read the current ort.properties content, or return empty string."""
    props_path = get_ort_properties_path()
    if props_path.exists():
        return props_path.read_text(encoding="utf-8")
    return ""


def write_ort_properties(enabled_managers: list[str], custom_paths: Optional[dict[str, str]] = None) -> Path:
    """
    Write ort.properties with the selected package managers.

    Args:
        enabled_managers: List of ORT package manager names to enable.
        custom_paths: Optional dict of {ort_name: binary_path} for manual overrides.

    Returns:
        Path where the file was written.
    """
    props_path = get_ort_properties_path()
    props_path.parent.mkdir(parents=True, exist_ok=True)

    managers_str = ",".join(enabled_managers) if enabled_managers else ""

    lines = [
        "# File: ort.properties",
        "# Auto-generated by ORT Web — do not edit manually.",
        "",
        "# Enabled package managers",
        f"ort.analyzer.enabledPackageManagers={managers_str}",
        "",
        "# Uncomment to enable scanner",
        "#ort.scanner.enabled=true",
        "",
        "# Uncomment to cache analyzer results",
        "#ort.analyzer.cache.enabled=true",
        "",
        "# Uncomment to set default output directory",
        "#ort.output.directory=reports",
        "",
        "# Log level: INFO, WARN, DEBUG",
        "#log.level=INFO",
    ]

    if custom_paths:
        lines.append("")
        lines.append("# Custom tool paths")
        for ort_name, bin_path in custom_paths.items():
            clean_path = bin_path.replace("\\", "/")
            lines.append(f"# {ort_name} binary: {clean_path}")

    props_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return props_path
