"""Run a Trivy filesystem scan and render standalone Markdown/HTML reports.

Trivy runs independently of ORT. Results are written to the job's artifact
directory as ``trivy-result.json`` (security), ``trivy-license-result.json``
(source licenses), plus Markdown and self-contained HTML reports, all of which
the results page lists/renders automatically. Nothing here touches ORT's ``vuln_summary``
or advisor data — the two engines are separate.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.config import settings
from app.features.jobs.event_contract import EVENT_LOG, make_event
from app.features.jobs.log_stream import log_stream_hub
from app.features.trivy.installer import ensure_trivy

JSON_FILENAME = "trivy-result.json"
LICENSE_JSON_FILENAME = "trivy-license-result.json"
REPORT_FILENAME = "trivy-report.md"
HTML_REPORT_FILENAME = "trivy-report.html"

_HEARTBEAT_INTERVAL = 60
_READLINE_TIMEOUT = 60

_SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]


def _make_log_fn(job_id: str, log_file: Path):
    async def _fn(line: str) -> None:
        text = line if line.endswith("\n") else line + "\n"
        with log_file.open("a", encoding="utf-8") as out:
            out.write(text)
        await log_stream_hub.publish(job_id, make_event(EVENT_LOG, line=text))

    return _fn


def _is_swift_target(target: str) -> bool:
    path = Path(target)
    if path.is_file():
        return path.name in {"Package.swift", "Package.resolved"}
    if not path.is_dir():
        return False
    for _root, dirs, files in os.walk(path):
        dirs[:] = [
            d for d in dirs
            if d not in {".git", ".build", "node_modules", "DerivedData"}
        ]
        if "Package.swift" in files or "Package.resolved" in files:
            return True
    return False


async def _run_trivy_process(
    tokens: list[str],
    target: str,
    env: dict[str, str],
    log_fn,
    on_process_start: Optional[Callable[[asyncio.subprocess.Process], None]],
) -> int:
    await log_fn(f"[trivy] $ {' '.join(tokens)}\n")
    process = await asyncio.create_subprocess_exec(
        *tokens,
        cwd=str(target) if Path(target).is_dir() else os.getcwd(),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    if on_process_start is not None:
        try:
            on_process_start(process)
        except Exception:
            pass

    start_time = time.monotonic()
    timeout_secs = settings.ort_job_timeout_seconds
    last_heartbeat = start_time
    assert process.stdout is not None

    while True:
        if time.monotonic() - start_time >= timeout_secs:
            await log_fn(f"[trivy] Exceeded timeout of {timeout_secs}s — killing process.\n")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return -1
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=_READLINE_TIMEOUT)
        except asyncio.TimeoutError:
            now = time.monotonic()
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                elapsed = int(now - start_time)
                await log_fn(f"[trivy] still running... ({elapsed // 60}m {elapsed % 60}s elapsed)\n")
                last_heartbeat = now
            continue
        if not line:
            break
        await log_fn(line.decode("utf-8", errors="replace"))
        last_heartbeat = time.monotonic()

    return await process.wait()


async def run_trivy_scan(
    job_id: str,
    target: str,
    output_dir: Path,
    log_file: Path,
    *,
    on_process_start: Optional[Callable[[asyncio.subprocess.Process], None]] = None,
) -> int:
    """Scan ``target`` with Trivy. Returns the trivy exit code (0 = success)."""
    log_fn = _make_log_fn(job_id, log_file)
    target = str(Path(target).resolve())

    await log_fn("[trivy] --- Trivy filesystem scan ---\n")
    await log_fn(f"[trivy] Target: {target}\n")

    trivy_path = await ensure_trivy(log_fn)
    if not trivy_path:
        await log_fn("[trivy] Trivy unavailable — scan skipped.\n")
        return 1
    # ensure_trivy() may return a path relative to the app's cwd (e.g.
    # "runtime/bin/trivy"). The subprocess below runs with cwd=target, and a
    # relative path containing a slash is resolved against *that* cwd by
    # exec(), not searched via PATH — so it must be made absolute first.
    trivy_path = str(Path(trivy_path).resolve())

    output_dir.mkdir(parents=True, exist_ok=True)
    json_out = output_dir / JSON_FILENAME

    cache_dir = settings.trivy_cache_dir
    env = os.environ.copy()
    env["TRIVY_CACHE_DIR"] = str(cache_dir)
    # Ensure the freshly installed binary (in runtime/bin) is resolvable.
    env["PATH"] = str(settings.bin_dir) + os.pathsep + env.get("PATH", "")

    # Always emit JSON to a file (the manual `trivy fs ...` dumps a table to
    # stdout instead) so the results page has an artifact + a rendered report.
    tokens = [
        trivy_path,
        "fs",
        "--cache-dir", str(cache_dir),
        "--scanners", settings.trivy_scanners,
        "--no-progress",
        "--format", "json",
        "--output", str(json_out),
    ]
    if settings.trivy_severity.strip():
        tokens += ["--severity", settings.trivy_severity]
    if settings.trivy_offline:
        tokens += ["--offline-scan"]
        # Trivy fatals with "--skip-db-update cannot be specified on the first
        # run" when no DB is cached yet. Only skip the DB/checks update when a
        # local DB actually exists; otherwise let Trivy download it once.
        db_dir = cache_dir / "db"
        db_present = (db_dir / "trivy.db").exists() or (db_dir / "metadata.json").exists()
        if db_present:
            # --skip-check-update also stops the misconfig "checks bundle" fetch
            # so a warm cache never touches the network.
            tokens += ["--skip-db-update", "--skip-check-update"]
        else:
            await log_fn(
                f"[trivy] No local DB at {cache_dir / 'db' / 'trivy.db'} — "
                "downloading it once (requires network on first run).\n"
            )
    tokens += [str(target)]

    await log_fn(
        f"[trivy] Cache dir: {cache_dir} "
        f"(offline={'on' if settings.trivy_offline else 'off'}, "
        f"severity={settings.trivy_severity or 'all'})\n"
    )
    exit_code = await _run_trivy_process(tokens, target, env, log_fn, on_process_start)

    license_out: Path | None = None
    if _is_swift_target(target):
        license_out = output_dir / LICENSE_JSON_FILENAME
        license_tokens = [
            trivy_path,
            "fs",
            "--cache-dir", str(cache_dir),
            "--scanners", "license",
            "--license-full",
            "--no-progress",
            "--format", "json",
            "--output", str(license_out),
        ]
        # License scanning is source-only; vulnerability DB/offline flags do not apply.
        license_tokens += [str(target)]
        await log_fn("[trivy] --- Swift full license scan (source already present only) ---\n")
        license_exit = await _run_trivy_process(
            license_tokens, target, env, log_fn, on_process_start
        )
        if license_exit == 0 and license_out.exists():
            try:
                license_data = json.loads(
                    license_out.read_text(encoding="utf-8", errors="replace")
                )
                licenses = (
                    _parse_trivy_licenses(license_data)
                    if isinstance(license_data, dict)
                    else []
                )
            except (OSError, json.JSONDecodeError) as exc:
                await log_fn(f"[trivy] License result unreadable: {exc} (non-fatal).\n")
                license_out = None
            else:
                await log_fn(f"[trivy] License findings: {len(licenses)}\n")
                if not licenses:
                    await log_fn(
                        "[trivy] No source licenses found. Package.resolved alone has no license "
                        "text; resolve local Package.swift manifests to create .build/checkouts.\n"
                    )
        else:
            await log_fn(f"[trivy] License scan failed with exit code {license_exit} (non-fatal).\n")
            license_out = None

    if exit_code == 0 and json_out.exists():
        try:
            report_path = build_trivy_markdown(
                json_out, output_dir / REPORT_FILENAME, license_out
            )
            await log_fn(f"[trivy] Report generated: {report_path.name}\n")
        except Exception as exc:
            await log_fn(f"[trivy] Markdown report generation failed: {exc}\n")
        try:
            html_report_path = build_trivy_html(
                json_out, output_dir / HTML_REPORT_FILENAME, license_out
            )
            await log_fn(f"[trivy] HTML report generated: {html_report_path.name}\n")
        except Exception as exc:
            await log_fn(f"[trivy] HTML report generation failed: {exc}\n")
    elif exit_code != 0:
        await log_fn(f"[trivy] Scan failed with exit code {exit_code}.\n")

    await log_fn("[trivy] --------------------------------\n")
    return exit_code


# ---------------------------------------------------------------------------
# JSON -> Markdown / HTML
# ---------------------------------------------------------------------------

def _md(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = " ".join(str(value).split())
    return (text or default).replace("|", "\\|")


def _severity_summary(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        sev = (row.get("severity") or "UNKNOWN").upper()
        counts[sev] = counts.get(sev, 0) + 1
    ordered = [(s, counts[s]) for s in _SEVERITY_ORDER if s in counts]
    ordered += [(s, c) for s, c in counts.items() if s not in _SEVERITY_ORDER]
    return ", ".join(f"{s}: {c}" for s, c in ordered) if ordered else "0"


def _parse_trivy_results(
    data: dict, fallback_artifact: str
) -> tuple[str, list[dict], list[dict], list[dict]]:
    """Extract (artifact, vulns, secrets, misconfigs) rows from a Trivy JSON result."""
    vulns: list[dict] = []
    secrets: list[dict] = []
    misconfigs: list[dict] = []

    for result in data.get("Results") or []:
        target = result.get("Target", "")
        for v in result.get("Vulnerabilities") or []:
            vulns.append({
                "target": target,
                "package": v.get("PkgName", ""),
                "installed": v.get("InstalledVersion", ""),
                "fixed": v.get("FixedVersion", ""),
                "id": v.get("VulnerabilityID", ""),
                "severity": v.get("Severity", ""),
                "title": v.get("Title") or v.get("Description", ""),
            })
        for s in result.get("Secrets") or []:
            secrets.append({
                "target": target,
                "rule": s.get("RuleID", ""),
                "severity": s.get("Severity", ""),
                "title": s.get("Title", ""),
                "line": s.get("StartLine", ""),
            })
        for m in result.get("Misconfigurations") or []:
            misconfigs.append({
                "target": target,
                "id": m.get("ID", ""),
                "severity": m.get("Severity", ""),
                "title": m.get("Title", ""),
                "message": m.get("Message", ""),
            })

    artifact = data.get("ArtifactName", fallback_artifact)
    return artifact, vulns, secrets, misconfigs


def _parse_trivy_licenses(data: dict) -> list[dict]:
    licenses: list[dict] = []
    for result in data.get("Results") or []:
        if not isinstance(result, dict):
            continue
        target = result.get("Target", "")
        for item in result.get("Licenses") or []:
            if not isinstance(item, dict):
                continue
            confidence = item.get("Confidence")
            licenses.append({
                "target": target,
                "license": item.get("Name") or item.get("License") or "",
                "category": item.get("Category") or item.get("Severity") or "",
                "package": item.get("PkgName") or item.get("FilePath") or "",
                "confidence": "" if confidence is None else confidence,
            })
    return licenses


def _load_trivy_licenses(license_json_path: Path | None) -> list[dict]:
    if not license_json_path or not license_json_path.exists():
        return []
    try:
        data = json.loads(license_json_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    return _parse_trivy_licenses(data) if isinstance(data, dict) else []


def build_trivy_markdown(
    json_path: Path, report_path: Path, license_json_path: Path | None = None
) -> Path:
    """Parse Trivy JSON results and write a standalone Markdown report."""
    data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    artifact, vulns, secrets, misconfigs = _parse_trivy_results(data, json_path.parent.name)
    licenses = _load_trivy_licenses(license_json_path)

    lines = [
        f"# Trivy Report — {_md(artifact)}",
        "",
        "## Summary",
        "",
        f"- Vulnerabilities: {len(vulns)} ({_severity_summary(vulns)})",
        f"- Secrets: {len(secrets)} ({_severity_summary(secrets)})",
        f"- Misconfigurations: {len(misconfigs)} ({_severity_summary(misconfigs)})",
        f"- Licenses: {len(licenses)}",
        "",
    ]

    if vulns:
        lines += [
            "## Vulnerabilities",
            "",
            "| Target | Package | Installed | Fixed | ID | Severity | Title |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in vulns[:300]:
            lines.append(
                f"| {_md(r['target'])} | {_md(r['package'])} | {_md(r['installed'])} | "
                f"{_md(r['fixed'])} | {_md(r['id'])} | {_md(r['severity'])} | {_md(r['title'])} |"
            )
        if len(vulns) > 300:
            lines += ["", f"_Showing 300 of {len(vulns)} vulnerabilities._"]
        lines.append("")

    if secrets:
        lines += [
            "## Secrets",
            "",
            "| Target | Rule | Severity | Line | Title |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in secrets[:300]:
            lines.append(
                f"| {_md(r['target'])} | {_md(r['rule'])} | {_md(r['severity'])} | "
                f"{_md(r['line'])} | {_md(r['title'])} |"
            )
        lines.append("")

    if misconfigs:
        lines += [
            "## Misconfigurations",
            "",
            "| Target | ID | Severity | Title | Message |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in misconfigs[:300]:
            lines.append(
                f"| {_md(r['target'])} | {_md(r['id'])} | {_md(r['severity'])} | "
                f"{_md(r['title'])} | {_md(r['message'])} |"
            )
        lines.append("")

    if licenses:
        lines += [
            "## Licenses",
            "",
            "| Target | License | Category | Package / File | Confidence |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in licenses[:300]:
            lines.append(
                f"| {_md(row['target'])} | {_md(row['license'])} | {_md(row['category'])} | "
                f"{_md(row['package'])} | {_md(row['confidence'])} |"
            )
        if len(licenses) > 300:
            lines += ["", f"_Showing 300 of {len(licenses)} licenses._"]
        lines.append("")

    if not (vulns or secrets or misconfigs or licenses):
        lines += ["No vulnerabilities, secrets, misconfigurations, or licenses were found.", ""]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _html_escape(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = " ".join(str(value).split())
    if not text:
        return default
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _sev_class(severity: str) -> str:
    sev = (severity or "UNKNOWN").strip().upper()
    return sev if sev in _SEVERITY_ORDER else "UNKNOWN"


def _severity_badges_html(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        sev = _sev_class(row.get("severity", ""))
        counts[sev] = counts.get(sev, 0) + 1
    ordered = [(s, counts[s]) for s in _SEVERITY_ORDER if s in counts]
    if not ordered:
        return '<span class="badge UNKNOWN">0</span>'
    return " ".join(f'<span class="badge {s}">{s}: {c}</span>' for s, c in ordered)


def _rows_table_html(
    headers: list[str], rows: list[dict], fields: list[str], *, limit: int = 300
) -> str:
    thead = "".join(f"<th>{h}</th>" for h in headers)
    body_rows = []
    for r in rows[:limit]:
        cells = "".join(
            f'<td class="sev-{_sev_class(r["severity"])}">{_html_escape(r.get("severity"))}</td>'
            if f == "severity" else f"<td>{_html_escape(r.get(f))}</td>"
            for f in fields
        )
        body_rows.append(f"<tr>{cells}</tr>")
    note = f'<p class="note">Showing {limit} of {len(rows)} rows.</p>' if len(rows) > limit else ""
    return (
        f'<table><thead><tr>{thead}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>{note}'
    )


def build_trivy_html(
    json_path: Path, report_path: Path, license_json_path: Path | None = None
) -> Path:
    """Parse Trivy JSON results and write a self-contained HTML report."""
    data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    artifact, vulns, secrets, misconfigs = _parse_trivy_results(data, json_path.parent.name)
    licenses = _load_trivy_licenses(license_json_path)

    sections = []
    if vulns:
        sections.append(
            "<h2>Vulnerabilities</h2>"
            + _rows_table_html(
                ["Target", "Package", "Installed", "Fixed", "ID", "Severity", "Title"],
                vulns,
                ["target", "package", "installed", "fixed", "id", "severity", "title"],
            )
        )
    if secrets:
        sections.append(
            "<h2>Secrets</h2>"
            + _rows_table_html(
                ["Target", "Rule", "Severity", "Line", "Title"],
                secrets,
                ["target", "rule", "severity", "line", "title"],
            )
        )
    if misconfigs:
        sections.append(
            "<h2>Misconfigurations</h2>"
            + _rows_table_html(
                ["Target", "ID", "Severity", "Title", "Message"],
                misconfigs,
                ["target", "id", "severity", "title", "message"],
            )
        )
    if licenses:
        sections.append(
            "<h2>Licenses</h2>"
            + _rows_table_html(
                ["Target", "License", "Category", "Package / File", "Confidence"],
                licenses,
                ["target", "license", "category", "package", "confidence"],
            )
        )
    if not sections:
        sections.append(
            "<p>No vulnerabilities, secrets, misconfigurations, or licenses were found.</p>"
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Trivy Report — {_html_escape(artifact)}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px 32px 48px;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; word-break: break-all; }}
  h2 {{ font-size: 1.1rem; margin-top: 32px; color: #f8fafc; border-bottom: 1px solid #334155; padding-bottom: 6px; }}
  .subtitle {{ color: #94a3b8; margin-top: 0; font-size: 0.85rem; }}
  .summary {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0 8px; }}
  .summary .group {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; }}
  .summary .group .label {{ display: block; font-size: 0.75rem; color: #94a3b8; margin-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #1e293b; vertical-align: top; }}
  th {{ background: #1e293b; color: #f8fafc; position: sticky; top: 0; }}
  tr:hover td {{ background: #16213a; }}
  .note {{ color: #94a3b8; font-size: 0.8rem; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }}
  .badge.CRITICAL, .sev-CRITICAL {{ background: #7f1d1d; color: #fecaca; }}
  .badge.HIGH, .sev-HIGH {{ background: #7c2d12; color: #fed7aa; }}
  .badge.MEDIUM, .sev-MEDIUM {{ background: #78350f; color: #fde68a; }}
  .badge.LOW, .sev-LOW {{ background: #14532d; color: #bbf7d0; }}
  .badge.UNKNOWN, .sev-UNKNOWN {{ background: #334155; color: #cbd5e1; }}
  td.sev-CRITICAL, td.sev-HIGH, td.sev-MEDIUM, td.sev-LOW, td.sev-UNKNOWN {{ font-weight: 600; }}
  a.back {{ color: #93c5fd; text-decoration: none; font-size: 0.85rem; }}
</style>
</head>
<body>
  <a class="back" href="/results/">&larr; Back to Results</a>
  <h1>Trivy Report</h1>
  <p class="subtitle">{_html_escape(artifact)}</p>
  <div class="summary">
    <div class="group"><span class="label">Vulnerabilities ({len(vulns)})</span>{_severity_badges_html(vulns)}</div>
    <div class="group"><span class="label">Secrets ({len(secrets)})</span>{_severity_badges_html(secrets)}</div>
    <div class="group"><span class="label">Misconfigurations ({len(misconfigs)})</span>{_severity_badges_html(misconfigs)}</div>
    <div class="group"><span class="label">Licenses</span><span class="badge UNKNOWN">{len(licenses)}</span></div>
  </div>
  {"".join(sections)}
</body>
</html>
"""
    report_path.write_text(html, encoding="utf-8")
    return report_path
