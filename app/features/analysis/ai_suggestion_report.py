from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.features.analysis.vertex_ai_service import VertexAIError, build_prompt, suggest_versions
from app.features.setup.vertex_config_store import get_vertex_config


_MAX_DEPENDENCIES = 140
_MAX_VULNERABILITIES = 80

_KNOWN_SAFE_VERSIONS: dict[str, tuple[str, str, str]] = {
    "org.apache.logging.log4j:log4j-core": (
        "2.17.2",
        ">=2.17.2,<3.0.0",
        "Mitigates known Log4Shell family issues on Java 8 line.",
    ),
    "org.apache.struts:struts2-core": (
        "2.5.33",
        ">=2.5.33,<3.0.0",
        "Upgrade to latest maintained 2.5.x with multiple Struts CVE fixes.",
    ),
    "com.google.guava:guava": (
        "32.1.3-jre",
        ">=32.1.3-jre,<33.0.0",
        "Includes fixes for multiple historical Guava advisories.",
    ),
    "junit:junit": (
        "4.13.2",
        ">=4.13.2,<5.0.0",
        "Latest JUnit4 patch release; prefer maintained test dependency.",
    ),
}


def _extract_name_version_from_id(value: str) -> tuple[str, str] | None:
    """Parse ORT package IDs like 'Maven:group:artifact:1.2.3'."""
    raw = value.strip()
    if not raw or ":" not in raw:
        return None

    prefix, sep, version = raw.rpartition(":")
    if not sep or not prefix or not version:
        return None

    _, sep2, name = prefix.partition(":")
    if not sep2 or not name:
        return None

    package_name = name.lstrip(":").strip()
    # NPM scoped packages: @scope:name → @scope/name (e.g. NPM:@babel:core → @babel/core)
    if package_name.startswith("@") and ":" in package_name:
        package_name = package_name.replace(":", "/", 1)
    package_version = version.strip()
    if not package_name or not package_version:
        return None

    return package_name, package_version


def _collect_dependency_entries(node: Any, result: list[dict[str, str]]) -> None:
    if isinstance(node, dict):
        name = node.get("name")
        version = node.get("version")
        if isinstance(name, str) and isinstance(version, str):
            result.append({"name": name, "version": version})
        else:
            ort_id = node.get("id")
            if isinstance(ort_id, str):
                parsed = _extract_name_version_from_id(ort_id)
                if parsed:
                    package_name, package_version = parsed
                    result.append({"name": package_name, "version": package_version})

        for value in node.values():
            _collect_dependency_entries(value, result)
    elif isinstance(node, list):
        for item in node:
            _collect_dependency_entries(item, result)


def _collect_vulnerability_entries(node: Any, result: list[dict[str, str]]) -> None:
    if isinstance(node, dict):
        vuln_id = node.get("id") or node.get("cve") or node.get("reference")
        severity = node.get("severity") or node.get("score")
        package = node.get("package") or node.get("packageName")

        if isinstance(vuln_id, str):
            result.append(
                {
                    "id": vuln_id,
                    "severity": str(severity or "unknown"),
                    "package": str(package or "unknown"),
                }
            )

        for value in node.values():
            _collect_vulnerability_entries(value, result)
    elif isinstance(node, list):
        for item in node:
            _collect_vulnerability_entries(item, result)


def _severity_rank(value: str) -> int:
    order = {
        "CRITICAL": 4,
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
        "UNKNOWN": 0,
    }
    return order.get(value.upper(), 0)


def _collect_vulnerability_entries_from_advisor(advisor_data: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    results = (((advisor_data or {}).get("advisor") or {}).get("results") or {})
    if not isinstance(results, dict):
        return entries

    for package_id, findings in results.items():
        if not isinstance(package_id, str):
            continue

        parsed = _extract_name_version_from_id(package_id)
        package_name, package_version = parsed if parsed else (package_id, "")

        if not isinstance(findings, list):
            continue

        for item in findings:
            if not isinstance(item, dict):
                continue

            vulnerabilities = item.get("vulnerabilities")
            if not isinstance(vulnerabilities, list):
                continue

            for vuln in vulnerabilities:
                if not isinstance(vuln, dict):
                    continue

                vuln_id = str(vuln.get("id") or "").strip()
                if not vuln_id:
                    continue

                highest = "UNKNOWN"
                refs = vuln.get("references")
                if isinstance(refs, list):
                    for ref in refs:
                        if not isinstance(ref, dict):
                            continue
                        sev = str(ref.get("severity") or "UNKNOWN").upper()
                        if _severity_rank(sev) > _severity_rank(highest):
                            highest = sev

                entries.append(
                    {
                        "id": vuln_id,
                        "severity": highest,
                        "package": package_name,
                        "current_version": package_version,
                    }
                )

    return entries


def _infer_package_manager(command: str, analyzer_data: Any) -> str:
    lower = command.lower()
    if "gradle" in lower:
        return "gradle"
    if "npm" in lower or "yarn" in lower or "pnpm" in lower:
        return "npm"
    if "pip" in lower or "poetry" in lower:
        return "pip"

    projects = (((analyzer_data or {}).get("analyzer") or {}).get("result") or {}).get("projects") or []
    if isinstance(projects, list):
        for project in projects:
            if not isinstance(project, dict):
                continue
            project_id = str(project.get("id") or "")
            if project_id.startswith("Maven:"):
                return "maven"
            if project_id.startswith("Gradle:"):
                return "gradle"
            if project_id.startswith("NPM:"):
                return "npm"
            if project_id.startswith("PIP:"):
                return "pip"
            if project_id.startswith("Poetry:"):
                return "pip"

    return "unknown"


def _fallback_known_suggestions(vulnerabilities: list[dict[str, str]]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for vuln in vulnerabilities:
        package = str(vuln.get("package") or "").strip()
        if not package or package in seen:
            continue
        safe = _KNOWN_SAFE_VERSIONS.get(package)
        if not safe:
            continue
        exact, safe_range, rationale = safe
        suggestions.append(
            {
                "package": package,
                "current_version": str(vuln.get("current_version") or "").strip(),
                "suggested_exact_version": exact,
                "suggested_safe_range": safe_range,
                "rationale_short": rationale,
                "confidence": 0.74,
            }
        )
        seen.add(package)

    return suggestions


def _read_yaml_file(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {}


def _normalize_output(parsed: dict[str, Any]) -> dict[str, Any]:
    suggestions = parsed.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = []

    normalized: list[dict[str, Any]] = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "package": str(item.get("package", "")).strip(),
                "current_version": str(item.get("current_version", "")).strip(),
                "suggested_exact_version": str(item.get("suggested_exact_version", "")).strip(),
                "suggested_safe_range": str(item.get("suggested_safe_range", "")).strip(),
                "rationale_short": str(item.get("rationale_short", "")).strip(),
                "confidence": float(item.get("confidence", 0.0) or 0.0),
            }
        )

    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "needs_manual_review": bool(parsed.get("needs_manual_review", False)),
        "suggestions": normalized,
    }


async def generate_ai_suggestion_report(job_id: str, error_message: str, command: str) -> dict[str, Any]:
    config = get_vertex_config()
    if not config.enabled:
        return {"status": "skipped", "summary": "Grok API key/model is not configured."}

    output_dir = settings.artifacts_dir / job_id
    analyzer_path = output_dir / "analyzer-result.yml"
    advisor_path = output_dir / "advisor-result.yml"

    analyzer_data = _read_yaml_file(analyzer_path)
    advisor_data = _read_yaml_file(advisor_path)

    dependencies: list[dict[str, str]] = []
    vulnerabilities: list[dict[str, str]] = []
    _collect_dependency_entries(analyzer_data, dependencies)
    vulnerabilities.extend(_collect_vulnerability_entries_from_advisor(advisor_data))
    if not vulnerabilities:
        _collect_vulnerability_entries(advisor_data, vulnerabilities)

    if not dependencies:
        return {
            "status": "skipped",
            "summary": "No dependency context found in artifacts.",
        }

    seen_dep: set[tuple[str, str]] = set()
    trimmed_deps: list[dict[str, str]] = []
    for dep in dependencies:
        key = (dep["name"], dep["version"])
        if key in seen_dep:
            continue
        seen_dep.add(key)
        trimmed_deps.append(dep)
        if len(trimmed_deps) >= _MAX_DEPENDENCIES:
            break

    seen_vuln: set[tuple[str, str, str]] = set()
    trimmed_vulns: list[dict[str, str]] = []
    for vuln in vulnerabilities:
        key = (vuln["id"], vuln["severity"], vuln["package"])
        if key in seen_vuln:
            continue
        seen_vuln.add(key)
        trimmed_vulns.append(vuln)
        if len(trimmed_vulns) >= _MAX_VULNERABILITIES:
            break

    package_manager = _infer_package_manager(command, analyzer_data)

    prompt = build_prompt(
        error_message=error_message,
        package_manager=package_manager,
        dependencies=trimmed_deps,
        vulnerabilities=trimmed_vulns,
    )

    try:
        result = await asyncio.to_thread(
            suggest_versions,
            api_key=config.api_key,
            model=config.model,
            prompt=prompt,
        )
    except VertexAIError as exc:
        fallback_suggestions = _fallback_known_suggestions(trimmed_vulns)
        if fallback_suggestions:
            report = {
                "prompt_version": "v1",
                "model": config.model,
                "job_id": job_id,
                "status": "success",
                "error_message": error_message,
                "input": {
                    "dependency_count": len(trimmed_deps),
                    "vulnerability_count": len(trimmed_vulns),
                },
                "output": {
                    "summary": f"AI request failed ({exc}); returned fallback safe versions for known vulnerable packages.",
                    "needs_manual_review": True,
                    "suggestions": fallback_suggestions,
                },
            }
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path = output_dir / "ai-suggestions.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "status": "success",
                "path": str(report_path),
                "summary": report["output"]["summary"],
                "suggestions": fallback_suggestions,
            }
        return {"status": "failed", "summary": str(exc)}
    except Exception as exc:  # pragma: no cover
        fallback_suggestions = _fallback_known_suggestions(trimmed_vulns)
        if fallback_suggestions:
            report = {
                "prompt_version": "v1",
                "model": config.model,
                "job_id": job_id,
                "status": "success",
                "error_message": error_message,
                "input": {
                    "dependency_count": len(trimmed_deps),
                    "vulnerability_count": len(trimmed_vulns),
                },
                "output": {
                    "summary": f"AI request raised unexpected error ({exc}); returned fallback safe versions for known vulnerable packages.",
                    "needs_manual_review": True,
                    "suggestions": fallback_suggestions,
                },
            }
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path = output_dir / "ai-suggestions.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "status": "success",
                "path": str(report_path),
                "summary": report["output"]["summary"],
                "suggestions": fallback_suggestions,
            }
        return {"status": "failed", "summary": f"Unexpected error: {exc}"}

    normalized = _normalize_output(result.parsed)
    if not normalized.get("suggestions"):
        fallback_suggestions = _fallback_known_suggestions(trimmed_vulns)
        if fallback_suggestions:
            normalized["suggestions"] = fallback_suggestions
            normalized["needs_manual_review"] = False
            if not normalized.get("summary"):
                normalized["summary"] = "Generated baseline safe-version suggestions from known vulnerability mappings."
    report = {
        "prompt_version": "v1",
        "model": config.model,
        "job_id": job_id,
        "status": "success",
        "error_message": error_message,
        "input": {
            "dependency_count": len(trimmed_deps),
            "vulnerability_count": len(trimmed_vulns),
        },
        "output": normalized,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "ai-suggestions.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "success",
        "path": str(report_path),
        "summary": normalized.get("summary") or f"Generated {len(normalized['suggestions'])} suggestion(s).",
        "suggestions": normalized.get("suggestions", []),
    }
