from __future__ import annotations

CORE_TOOLS = [
    {
        "id": "analyze",
        "title": "Analyzer",
        "purpose": "Determine dependencies and metadata from source projects.",
        "sample": "ort analyze -i <project-dir> -o <output-dir>",
        "output": ["analyzer-result.yml", "analyzer-result.json"],
    },
    {
        "id": "download",
        "title": "Downloader",
        "purpose": "Fetch dependency source code from VCS and artifacts.",
        "sample": "ort download -i <analyzer-result> -o <output-dir>",
        "output": ["downloaded source trees", "archives"],
    },
    {
        "id": "scan",
        "title": "Scanner",
        "purpose": "Run license and copyright scanners on source code.",
        "sample": "ort scan -i <analyzer-result> -o <output-dir> --scanners ScanCode",
        "output": ["scan-result.yml", "scan-result.json"],
    },
    {
        "id": "advise",
        "title": "Advisor",
        "purpose": "Collect vulnerability advisories from providers.",
        "sample": "ort advise -i <analyzer-result> -o <output-dir> --advisors OSV",
        "output": ["advisor-result.yml", "advisor-result.json"],
    },
    {
        "id": "evaluate",
        "title": "Evaluator",
        "purpose": "Evaluate policy rules against ORT results.",
        "sample": "ort evaluate -i <scan-result> -o <output-dir>",
        "output": ["evaluation-result.yml", "evaluation-result.json"],
    },
    {
        "id": "report",
        "title": "Reporter",
        "purpose": "Generate SBOM and human-readable reports.",
        "sample": "ort report -i <evaluation-result> -o <output-dir> -f WebApp,StaticHtml",
        "output": ["scan-report.html", "scan-report-web-app.html", "sbom files"],
    },
    {
        "id": "notify",
        "title": "Notifier",
        "purpose": "Send notifications based on ORT result scripts.",
        "sample": "ort notify -i <evaluation-result> -n notifications.kts",
        "output": ["notification side effects", "notifier run data"],
    },
]

SUPPORTING_COMMANDS = [
    {
        "id": "requirements",
        "purpose": "Check tool prerequisites required by ORT.",
        "sample": "ort requirements",
    },
    {"id": "compare", "purpose": "Compare two ORT result files.", "sample": "ort compare <a> <b>"},
    {"id": "config", "purpose": "Inspect active ORT config.", "sample": "ort config --show-active"},
    {"id": "plugins", "purpose": "List installed ORT plugins.", "sample": "ort plugins"},
    {"id": "migrate", "purpose": "Migrate old ORT config formats.", "sample": "ort migrate --hocon-to-yaml old.conf"},
    {
        "id": "upload-curations",
        "purpose": "Upload curations to configured servers.",
        "sample": "ort upload-curations -i curations.yml",
    },
    {
        "id": "upload-result-to-postgres",
        "purpose": "Upload ORT result to PostgreSQL storage.",
        "sample": "ort upload-result-to-postgres -i scan-result.yml",
    },
]

PLUGIN_CATEGORIES = {
    "advisors": ["OSV", "VulnerableCode", "OssIndex", "BlackDuck"],
    "scanners": ["ScanCode", "FossID", "Askalono", "Licensee", "ScanOss", "Dos"],
    "reporters": [
        "WebApp",
        "StaticHtml",
        "CycloneDx",
        "SpdxDocument",
        "PlainTextTemplate",
        "EvaluatedModel",
    ],
    "package_managers": [
        "NPM",
        "PNPM",
        "Yarn",
        "Maven",
        "Gradle",
        "Poetry",
        "PIP",
        "GoMod",
        "Cargo",
        "Conan",
    ],
    "vcs": ["Git", "GitRepo", "Mercurial", "Subversion"],
}

CONFIG_ARTIFACTS = [
    {"name": ".ort.yml", "scope": "repository", "used_by": ["analyze", "scan", "evaluate", "report"]},
    {"name": "curations.yml", "scope": "global", "used_by": ["analyze", "evaluate"]},
    {
        "name": "license-classifications.yml",
        "scope": "global",
        "used_by": ["evaluate", "report"],
    },
    {"name": "resolutions.yml", "scope": "global", "used_by": ["evaluate", "report", "notify"]},
    {
        "name": "package-configurations/",
        "scope": "global",
        "used_by": ["scan", "evaluate", "report"],
    },
    {"name": "evaluator.rules.kts", "scope": "global", "used_by": ["evaluate"]},
    {"name": "notifications.kts", "scope": "global", "used_by": ["notify"]},
]

RELATED_TOOLS = [
    {"name": "ORT Server", "role": "Centralized orchestration service for ORT runs."},
    {"name": "ORT GitHub Action", "role": "Run ORT in GitHub CI pipelines."},
    {"name": "ORT Workbench", "role": "Human workflow UI around ORT results."},
]
