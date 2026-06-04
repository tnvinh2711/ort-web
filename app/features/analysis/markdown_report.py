from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.config import settings


REPORT_FILENAME = "ort-report.md"


def _safe_load(path: Path) -> Any:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        return yaml.safe_load(text)
    if suffix == ".json":
        import json

        return json.loads(text)
    return None


def _plain(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        text = " ".join(value.split())
        return text or default
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value if item)
        return text or default
    return str(value)


def _md(value: Any, default: str = "-") -> str:
    text = _plain(value, default)
    return text.replace("|", "\\|")


def _without_git_value(value: Any) -> str:
    text = _plain(value, "")
    return "" if "git" in text.lower() else text


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _parse_package_id(package_id: str) -> tuple[str, str, str]:
    parts = str(package_id or "").split(":")
    if len(parts) >= 4:
        pkg_type = parts[0]
        namespace = parts[1]
        name = parts[2]
        version = parts[3]
        if namespace:
            # NPM scoped packages use @scope/name format (e.g. NPM:@babel:core → @babel/core)
            sep = "/" if (pkg_type == "NPM" and namespace.startswith("@")) else ":"
            package_name = f"{namespace}{sep}{name}"
        else:
            package_name = name
        return package_name, version, pkg_type
    return str(package_id or ""), "", ""


def _license_text(pkg: dict[str, Any]) -> str:
    processed = pkg.get("declared_licenses_processed")
    if isinstance(processed, dict) and processed.get("spdx_expression"):
        return str(processed["spdx_expression"])
    declared = pkg.get("declared_licenses")
    if isinstance(declared, list):
        return ", ".join(str(item) for item in declared if item)
    return ""


def _project_metadata(data: Any, output_dir: Path) -> dict[str, str]:
    analyzer = data.get("analyzer") if isinstance(data, dict) else {}
    result = analyzer.get("result") if isinstance(analyzer, dict) else {}
    projects = result.get("projects") if isinstance(result, dict) else []
    project = projects[0] if projects and isinstance(projects[0], dict) else {}
    title, version, package_type = _parse_package_id(str(project.get("id") or output_dir.name))

    created = analyzer.get("start_time") if isinstance(analyzer, dict) else ""
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = _without_git_value(project.get("homepage_url"))
    description = project.get("description") or project.get("definition_file_path") or "ORT generated Markdown report."
    authors = project.get("authors") or project.get("author") or []

    tags = ["ort", "markdown-report"]
    if package_type:
        tags.append(package_type.lower())

    return {
        "title": title or output_dir.name,
        "source": _plain(source),
        "author": _plain(authors),
        "published": _plain(source),
        "created": _plain(created or generated),
        "description": _plain(description),
        "tags": ", ".join(tags),
        "generated": generated,
        "version": version,
    }


def _extract_components(data: Any) -> list[dict[str, str]]:
    analyzer = data.get("analyzer") if isinstance(data, dict) else {}
    result = analyzer.get("result") if isinstance(analyzer, dict) else {}
    packages = result.get("packages") if isinstance(result, dict) else []
    rows: list[dict[str, str]] = []

    for pkg in packages if isinstance(packages, list) else []:
        if not isinstance(pkg, dict):
            continue
        name, version, package_type = _parse_package_id(str(pkg.get("id") or ""))
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "version": version,
                "type": package_type,
                "license": _license_text(pkg),
                "homepage": _without_git_value(pkg.get("homepage_url")),
                "description": _plain(pkg.get("description"), ""),
            }
        )

    return sorted(rows, key=lambda item: (item["name"].lower(), item["version"]))


def _extract_vulnerabilities(data: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    advisor = data.get("advisor") if isinstance(data, dict) else {}
    advisor_results = advisor.get("results") if isinstance(advisor, dict) else {}
    if isinstance(advisor_results, dict):
        for package_id, results in advisor_results.items():
            package_name, package_version, _ = _parse_package_id(str(package_id))
            for result in results if isinstance(results, list) else []:
                if not isinstance(result, dict):
                    continue
                for vuln in result.get("vulnerabilities") or []:
                    if not isinstance(vuln, dict):
                        continue
                    references = vuln.get("references")
                    severities = [
                        str(ref.get("severity"))
                        for ref in references
                        if isinstance(ref, dict) and ref.get("severity")
                    ] if isinstance(references, list) else []
                    rows.append(
                        {
                            "package": package_name,
                            "version": package_version,
                            "id": _plain(vuln.get("id") or vuln.get("external_id")),
                            "severity": severities[0] if severities else "",
                            "summary": _plain(vuln.get("summary") or vuln.get("description")),
                        }
                    )
        return rows

    for node in _walk(data):
        vulnerabilities = node.get("vulnerabilities")
        if not isinstance(vulnerabilities, list):
            continue
        package_name, package_version, _ = _parse_package_id(str(node.get("id") or ""))
        for vuln in vulnerabilities:
            if not isinstance(vuln, dict):
                continue
            references = vuln.get("references")
            severities = [
                str(ref.get("severity"))
                for ref in references
                if isinstance(ref, dict) and ref.get("severity")
            ] if isinstance(references, list) else []
            severity = severities[0] if severities else ""
            rows.append(
                {
                    "package": package_name,
                    "version": package_version,
                    "id": _plain(vuln.get("id") or vuln.get("external_id")),
                    "severity": severity,
                    "summary": _plain(vuln.get("summary") or vuln.get("description")),
                }
            )
    return rows


def _report_output_dir(ort_output_dir: Path, markdown_reports_dir: Path | None = None) -> Path:
    base = markdown_reports_dir or settings.markdown_reports_dir
    try:
        if base.resolve() == settings.artifacts_dir.resolve():
            return ort_output_dir
    except FileNotFoundError:
        pass
    return base / ort_output_dir.name


def generate_markdown_report(output_dir: Path, markdown_reports_dir: Path | None = None) -> Path | None:
    """Generate a Markdown report from ORT artifacts in output_dir."""
    source_path = output_dir / "advisor-result.yml"
    if not source_path.exists():
        source_path = output_dir / "scan-result.yml"
    if not source_path.exists():
        source_path = output_dir / "analyzer-result.yml"
    data = _safe_load(source_path)
    if not isinstance(data, dict):
        return None

    metadata = _project_metadata(data, output_dir)
    components = _extract_components(data)
    vulnerabilities = _extract_vulnerabilities(data)
    severity_counts = Counter(row["severity"] or "UNKNOWN" for row in vulnerabilities)

    lines = [
        f"# {metadata['title']}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Title | {_md(metadata['title'])} |",
        f"| Source | {_md(metadata['source'])} |",
        f"| Author | {_md(metadata['author'])} |",
        f"| Published | {_md(metadata['published'])} |",
        f"| Created | {_md(metadata['created'])} |",
        f"| Description | {_md(metadata['description'])} |",
        f"| Tags | {_md(metadata['tags'])} |",
        "",
        "## Summary",
        "",
        f"- Generated: {metadata['generated']}",
        f"- Input file: {source_path.name}",
        f"- Components: {len(components)}",
        f"- Vulnerabilities: {len(vulnerabilities)}",
    ]
    if severity_counts:
        counts = ", ".join(f"{key}: {value}" for key, value in sorted(severity_counts.items()))
        lines.append(f"- Severity counts: {counts}")

    lines.extend(["", "## Tags", "", metadata["tags"], ""])

    if vulnerabilities:
        lines.extend(["## Vulnerabilities", "", "| Package | Version | ID | Severity | Summary |", "| --- | --- | --- | --- | --- |"])
        for row in vulnerabilities[:100]:
            lines.append(
                f"| {_md(row['package'])} | {_md(row['version'])} | {_md(row['id'])} | "
                f"{_md(row['severity'])} | {_md(row['summary'])} |"
            )
        if len(vulnerabilities) > 100:
            lines.extend(["", f"_Showing 100 of {len(vulnerabilities)} vulnerabilities._"])
        lines.append("")

    lines.extend(["## Components", "", "| Component | Version | Type | License | Home Page | Description |", "| --- | --- | --- | --- | --- | --- |"])
    for row in components[:200]:
        lines.append(
            f"| {_md(row['name'])} | {_md(row['version'])} | {_md(row['type'])} | "
            f"{_md(row['license'])} | {_md(row['homepage'])} | {_md(row['description'])} |"
        )
    if len(components) > 200:
        lines.extend(["", f"_Showing 200 of {len(components)} components._"])
    lines.append("")

    report_dir = _report_output_dir(output_dir, markdown_reports_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / REPORT_FILENAME
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
