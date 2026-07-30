"""Service for generating ORT config.yml and repository .ort.yml configuration."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

from app.features.shared.language_detector import get_package_manager_categories
from app.features.ort.properties import get_managers_for_language

# Default path excludes per language category.
# These go into .ort.yml (repository config), NOT config.yml (global config).
LANGUAGE_EXCLUDES: dict[str, list[dict[str, str]]] = {
    "python": [
        {
            "pattern": "**/venv/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Python virtual environment",
        },
        {
            "pattern": "**/.venv/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Python virtual environment",
        },
        {
            "pattern": "**/__pycache__/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Python bytecode cache",
        },
        {
            "pattern": "**/.tox/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Tox test runner environments",
        },
    ],
    "jvm": [
        {
            "pattern": "**/build/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Gradle/Maven build output",
        },
        {
            "pattern": "**/target/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Maven target directory",
        },
        {
            "pattern": "**/.gradle/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Gradle cache",
        },
    ],
    "nodejs": [
        {
            "pattern": "**/node_modules/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Node.js dependencies (managed by package manager)",
        },
        {
            "pattern": "**/.next/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Next.js generated build and development output",
        },
        {
            "pattern": "**/.turbo/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Turborepo generated cache",
        },
        {
            "pattern": "**/dist/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Build output",
        },
        {
            "pattern": "**/out/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Generated static build output",
        },
        {
            "pattern": "**/.claude/worktrees/**",
            "reason": "OTHER",
            "comment": "Nested Claude agent Git worktrees duplicate the source project",
        },
        {
            "pattern": "**/.codex/worktrees/**",
            "reason": "OTHER",
            "comment": "Nested Codex agent Git worktrees duplicate the source project",
        },
    ],
    "go": [
        {
            "pattern": "**/vendor/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Go vendored dependencies",
        },
    ],
    "rust": [
        {
            "pattern": "**/target/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Cargo build output",
        },
    ],
    "cpp": [
        {
            "pattern": "**/build/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "CMake/build output",
        },
        {
            "pattern": "**/cmake-build-*/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "CLion CMake build directories",
        },
    ],
    "ruby": [
        {
            "pattern": "**/vendor/bundle/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Bundler installed gems",
        },
    ],
    "php": [
        {
            "pattern": "**/vendor/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Composer dependencies",
        },
    ],
    "swift": [
        {
            "pattern": "**/.build/**",
            "reason": "BUILD_TOOL_OF",
            "comment": "Swift Package Manager build output",
        },
    ],
    "dotnet": [
        {
            "pattern": "**/bin/**",
            "reason": "BUILD_TOOL_OF",
            "comment": ".NET build output",
        },
        {
            "pattern": "**/obj/**",
            "reason": "BUILD_TOOL_OF",
            "comment": ".NET intermediate build files",
        },
    ],
}


def get_config_yml_path() -> Path:
    """Return the standard ORT config.yml path (~/.ort/config/config.yml)."""
    return Path.home() / ".ort" / "config" / "config.yml"


# Module-level cache for read_config_yml: avoid re-reading on every dashboard load.
# Invalidated by mtime, so external edits are picked up automatically.
_config_yml_cache: tuple[float, str] | None = None  # (mtime, content)


def read_config_yml() -> str:
    """Read the current config.yml content, or return empty string. mtime-cached."""
    global _config_yml_cache
    config_path = get_config_yml_path()
    try:
        st = config_path.stat()
    except OSError:
        return ""
    mtime = st.st_mtime
    if _config_yml_cache is not None and _config_yml_cache[0] == mtime:
        return _config_yml_cache[1]
    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    _config_yml_cache = (mtime, content)
    return content


def _get_excludes_for_language(language: str) -> list[dict[str, str]]:
    """Build a list of path exclude entries appropriate for *language*."""
    categories = get_package_manager_categories(language)
    excludes: list[dict[str, str]] = []
    seen_patterns: set[str] = set()
    for cat in categories:
        for entry in LANGUAGE_EXCLUDES.get(cat, []):
            if entry["pattern"] not in seen_patterns:
                excludes.append(entry)
                seen_patterns.add(entry["pattern"])
    return excludes


def _is_in_git_work_tree(project_path: Optional[str]) -> bool:
    """Return whether *project_path* is inside a Git work tree.

    A worktree marker can be either a directory (normal clone) or a file
    (linked worktree / submodule), so ``exists()`` is intentional here.
    """
    if not project_path:
        return False

    current = Path(project_path).resolve()
    if current.is_file():
        current = current.parent

    return any((candidate / ".git").exists() for candidate in (current, *current.parents))


def _get_swift_unresolvable_definition_file_excludes(
    project_path: Optional[str],
) -> list[dict[str, str]]:
    """Return SwiftPM / CocoaPods definition files ORT cannot resolve safely.

    SwiftPM returns absolute filesystem URLs for ``.package(path: ...)``.
    Current ORT releases cannot convert these to a valid PackageURL. CocoaPods
    explicitly does not support a Podfile without its lockfile. Skipping only
    those definition files avoids analyzer errors while the first-party source
    remains covered by repository-level ScanCode and by Trivy.
    """
    if not project_path:
        return []

    root = Path(project_path).resolve()
    if not root.is_dir():
        return []

    local_path_pattern = re.compile(
        r"\.package\s*\(\s*(?:name\s*:\s*[^,]+,\s*)?path\s*:",
        re.DOTALL,
    )
    prune_dirs = {
        ".build", ".git", ".gradle", ".idea", ".venv", ".vscode",
        "DerivedData", "build", "dist", "node_modules", "target", "venv",
    }
    excludes: list[dict[str, str]] = []

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [directory for directory in dirs if directory not in prune_dirs]
        current = Path(current_root)

        if "Package.swift" in files:
            manifest = current / "Package.swift"
            try:
                content = manifest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            if local_path_pattern.search(content):
                excludes.append(
                    {
                        "pattern": manifest.relative_to(root).as_posix(),
                        "reason": "OTHER",
                        "comment": (
                            "SwiftPM local path dependency: ORT cannot map its "
                            "filesystem URL to a PackageURL"
                        ),
                    }
                )

        if "Podfile" in files and not (current / "Podfile.lock").is_file():
            podfile = current / "Podfile"
            excludes.append(
                {
                    "pattern": podfile.relative_to(root).as_posix(),
                    "reason": "OTHER",
                    "comment": "CocoaPods analysis requires a sibling Podfile.lock",
                }
            )

    return excludes


def _refine_managers_for_project(managers: list[str], project_path: Optional[str]) -> list[str]:
    """Narrow down package managers based on actual definition files in the project."""
    if not project_path:
        return managers

    root = Path(project_path)
    if not root.is_dir():
        return managers

    # For Python: choose between PIP and Poetry based on what files exist
    if "PIP" in managers and "Poetry" in managers:
        has_poetry_lock = (root / "poetry.lock").exists()
        has_pyproject = (root / "pyproject.toml").exists()
        has_requirements = any(root.glob("requirements*.txt"))

        if has_poetry_lock:
            # Clearly a Poetry project
            managers = [m for m in managers if m != "PIP"]
        elif has_pyproject and not has_requirements:
            # pyproject.toml without requirements.txt — prefer Poetry
            managers = [m for m in managers if m != "PIP"]
        elif has_requirements and not has_poetry_lock:
            # requirements.txt without poetry.lock — prefer PIP
            managers = [m for m in managers if m != "Poetry"]

    # For JVM: choose between Gradle and Maven
    if "Gradle" in managers and "Maven" in managers:
        has_gradle = (root / "build.gradle").exists() or (root / "build.gradle.kts").exists()
        has_maven = (root / "pom.xml").exists()
        if has_gradle and not has_maven:
            managers = [m for m in managers if m != "Maven"]
        elif has_maven and not has_gradle:
            managers = [m for m in managers if m != "Gradle"]

    # For Node.js: choose between NPM, PNPM, Yarn
    npm_managers = {"NPM", "PNPM", "Yarn"}
    active_npm = [m for m in managers if m in npm_managers]
    if len(active_npm) > 1:
        has_pnpm_lock = (root / "pnpm-lock.yaml").exists()
        has_yarn_lock = (root / "yarn.lock").exists()
        has_npm_lock = (root / "package-lock.json").exists()
        if has_pnpm_lock:
            managers = [m for m in managers if m not in npm_managers or m == "PNPM"]
        elif has_yarn_lock:
            managers = [m for m in managers if m not in npm_managers or m == "Yarn"]
        elif has_npm_lock:
            managers = [m for m in managers if m not in npm_managers or m == "NPM"]

    return managers


def generate_config_yml(
    language: str,
    project_path: Optional[str] = None,
) -> Path:
    """Generate ``~/.ort/config/config.yml`` tailored to *language*.

    This file only contains global ORT settings (analyzer, scanner, etc.).
    Path excludes belong in the repository config (.ort.yml), not here.

    Returns the path where the file was written.
    """
    config_path = get_config_yml_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    enabled_managers = get_managers_for_language(language)
    enabled_managers = _refine_managers_for_project(enabled_managers, project_path)

    config: dict = {
        "ort": {
            "analyzer": {
                "allowDynamicVersions": True,
            },
            # Restrict curation providers to local-only sources. The Spring
            # provider makes outbound HTTP requests to repo.spring.io which
            # can stall analysis indefinitely on restricted networks.
            "packageCurationProviders": [
                {"type": "DefaultDir"},
                {"type": "DefaultFile"},
            ],
        },
    }

    if enabled_managers:
        config["ort"]["analyzer"]["enabledPackageManagers"] = enabled_managers

    header = (
        "# ORT config.yml — global configuration\n"
        f"# Auto-generated by ORT Web for language: {language}\n"
        "# See https://github.com/oss-review-toolkit/ort for documentation.\n"
        "\n"
    )

    yaml_body = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
    config_path.write_text(header + yaml_body, encoding="utf-8")
    return config_path


def generate_repo_config(
    language: str,
    output_path: Path,
    project_path: Optional[str] = None,
) -> Path:
    """Generate a repository configuration file (.ort.yml format).

    Build/cache paths are skipped completely when the project belongs to a Git
    work tree. This is required for Swift because ``.build/checkouts`` contains
    dependency manifests and nested Git metadata that ORT must not treat as
    first-party projects.

    ORT 85+ can crash when path excludes are applied to an analyzed directory
    without repository VCS information (for example, an extracted archive), so
    non-Git inputs intentionally retain an empty repository configuration.

    Returns the path where the file was written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "# ORT repository configuration\n"
        f"# Auto-generated by ORT Web for language: {language}\n"
        "\n"
    )

    config: dict = {}
    excludes = _get_excludes_for_language(language)
    if language == "swift":
        excludes.extend(_get_swift_unresolvable_definition_file_excludes(project_path))
    if excludes and _is_in_git_work_tree(project_path):
        config = {
            "analyzer": {
                "skip_excluded": True,
            },
            "excludes": {
                "paths": excludes,
            },
        }

    yaml_body = yaml.dump(
        config,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    output_path.write_text(header + yaml_body, encoding="utf-8")
    return output_path
