"""Language detection for source code projects."""

from pathlib import Path
from typing import Optional


# Common file extensions by programming language
LANGUAGE_PATTERNS = {
    "python": {".py", ".pyx", ".pyi"},
    "java": {".java", ".gradle", ".gradle.kts"},
    "kotlin": {".kt", ".kts"},
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
    "kotlin": {".kt", "build.gradle.kts"},
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
    
    # Count language matches
    language_scores = {}
    
    # Recursively search for files
    for file_path in project.rglob("*"):
        if not file_path.is_file():
            continue
        
        # Skip hidden and common ignored files
        name = file_path.name
        if name.startswith(".") or name in {"node_modules", ".git", ".venv", "venv", "env"}:
            continue
        
        suffix = file_path.suffix
        
        for lang, patterns in LANGUAGE_PATTERNS.items():
            if suffix in patterns or name in patterns:
                language_scores[lang] = language_scores.get(lang, 0) + 1
    
    if not language_scores:
        return None
    
    # Return language with highest score
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
