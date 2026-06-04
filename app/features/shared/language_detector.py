"""Language detection for source code projects."""

import os
from pathlib import Path
from typing import Optional


# Directories never useful for language detection — pruned in-place during walk
# so we don't descend into them at all (was a real bug previously: only filename
# was checked, so node_modules contents WERE scanned).
_DETECT_PRUNE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "env",
    "__pycache__", ".gradle", ".idea", ".vscode",
    "build", "dist", "target", "out", "obj",
}

_DETECT_FILE_HARD_CAP = 20000  # never scan more than this many files
_DETECT_EARLY_FILES = 5000     # consider early termination after this many
_DETECT_EARLY_LEAD = 10        # leader must have >= this multiple of #2 to stop early


# Common file extensions by programming language
LANGUAGE_PATTERNS = {
    "python": {".py", ".pyx", ".pyi"},
    "java": {".java", ".gradle", ".gradle.kts"},
    "kotlin": {".kt", ".kts", "build.gradle.kts"},
    "go": {".go", "go.mod", "go.sum"},
    "rust": {".rs", "Cargo.toml", "Cargo.lock"},
    "csharp": {".cs", ".csproj", ".sln"},
    "cpp": {".cpp", ".cc", ".cxx", ".h", ".hpp", ".hpp.in"},
    "c": {".c", ".h"},
    "javascript": {".js", ".jsx", ".mjs", "package.json"},
    "typescript": {".ts", ".tsx"},
    "nodejs": {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"},
    "ruby": {".rb", "Gemfile", "Rakefile"},
    "php": {".php", "composer.json"},
    "swift": {".swift", "Package.swift"},
    "gradle": {"build.gradle", "build.gradle.kts", "gradle.properties"},
    "maven": {"pom.xml"},
    "npm": {"package.json"},
    "dotnet": {".csproj", ".sln", "global.json"},
}


# Map detected language names to ORT package-manager category strings.
# Used to bridge language detection with ort_properties auto-selection.
LANGUAGE_TO_CATEGORIES: dict[str, list[str]] = {
    "python": ["python"],
    "java": ["jvm"],
    "kotlin": ["jvm"],
    "go": ["go"],
    "rust": ["rust"],
    "csharp": ["dotnet"],
    "cpp": ["cpp"],
    "c": ["cpp"],
    "javascript": ["nodejs"],
    "typescript": ["nodejs"],
    "nodejs": ["nodejs"],
    "ruby": ["ruby"],
    "php": ["php"],
    "swift": ["swift"],
    "gradle": ["jvm"],
    "maven": ["jvm"],
    "npm": ["nodejs"],
    "dotnet": ["dotnet"],
}


def get_package_manager_categories(language: str) -> list[str]:
    """Return ORT package-manager categories for a detected language."""
    return LANGUAGE_TO_CATEGORIES.get(language, [])


def detect_language(project_path: str) -> Optional[str]:
    """
    Auto-detect the primary programming language of a project.

    Args:
        project_path: Path to the project directory

    Returns:
        Detected language name or None if not detected
    """
    project = Path(project_path)
    if not project.exists() or not project.is_dir():
        return None

    language_scores: dict[str, int] = {}
    files_scanned = 0

    # os.walk + in-place dir prune so we never descend into node_modules/.git/etc.
    # (Path.rglob can't prune; previous code only filtered by FILENAME so
    # node_modules/foo.js was still walked — major perf bug on JS projects.)
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in _DETECT_PRUNE_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            files_scanned += 1
            dot = name.rfind(".")
            suffix = name[dot:] if dot >= 0 else ""

            for lang, patterns in LANGUAGE_PATTERNS.items():
                if suffix in patterns or name in patterns:
                    language_scores[lang] = language_scores.get(lang, 0) + 1

            # Early termination — leader is overwhelmingly dominant.
            if files_scanned == _DETECT_EARLY_FILES and len(language_scores) >= 2:
                ranked = sorted(language_scores.values(), reverse=True)
                if ranked[0] >= ranked[1] * _DETECT_EARLY_LEAD:
                    return max(language_scores.items(), key=lambda x: x[1])[0]

            if files_scanned >= _DETECT_FILE_HARD_CAP:
                if language_scores:
                    return max(language_scores.items(), key=lambda x: x[1])[0]
                return None

    if not language_scores:
        return None

    return max(language_scores.items(), key=lambda x: x[1])[0]


def get_language_options() -> list[dict[str, str]]:
    """Get list of supported languages for project analysis."""
    return [
        {"value": "python", "label": "Python"},
        {"value": "java", "label": "Java"},
        {"value": "kotlin", "label": "Kotlin"},
        {"value": "go", "label": "Go"},
        {"value": "rust", "label": "Rust"},
        {"value": "csharp", "label": "C# (.NET)"},
        {"value": "cpp", "label": "C++"},
        {"value": "c", "label": "C"},
        {"value": "javascript", "label": "JavaScript"},
        {"value": "typescript", "label": "TypeScript"},
        {"value": "nodejs", "label": "Node.js"},
        {"value": "ruby", "label": "Ruby"},
        {"value": "php", "label": "PHP"},
        {"value": "swift", "label": "Swift"},
        {"value": "gradle", "label": "Gradle"},
        {"value": "maven", "label": "Maven"},
        {"value": "npm", "label": "NPM"},
        {"value": "dotnet", "label": ".NET"},
    ]
