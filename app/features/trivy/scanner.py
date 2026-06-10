"""Run a Trivy filesystem scan and render a standalone Markdown report.

Trivy runs independently of ORT. Results are written to the job's artifact
directory as ``trivy-result.json`` (raw) and ``trivy-report.md`` (rendered),
both of which the results page lists/renders automatically. Nothing here
touches ORT's ``vuln_summary`` or advisor data — the two engines are separate.
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
REPORT_FILENAME = "trivy-report.md"

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

    await log_fn("[trivy] --- Trivy filesystem scan ---\n")
    await log_fn(f"[trivy] Target: {target}\n")

    trivy_path = await ensure_trivy(log_fn)
    if not trivy_path:
        await log_fn("[trivy] Trivy unavailable — scan skipped.\n")
        return 1

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
        # --skip-check-update stops the misconfig "checks bundle" network fetch
        # so offline mode never touches the network.
        tokens += ["--offline-scan", "--skip-db-update", "--skip-check-update"]
    tokens += [str(target)]

    await log_fn(f"[trivy] $ {' '.join(tokens)}\n")
    await log_fn(
        f"[trivy] Cache dir: {cache_dir} "
        f"(offline={'on' if settings.trivy_offline else 'off'}, "
        f"severity={settings.trivy_severity or 'all'})\n"
    )

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

    exit_code = await process.wait()

    if exit_code == 0 and json_out.exists():
        try:
            report_path = build_trivy_markdown(json_out, output_dir / REPORT_FILENAME)
            await log_fn(f"[trivy] Report generated: {report_path.name}\n")
        except Exception as exc:
            await log_fn(f"[trivy] Markdown report generation failed: {exc}\n")
    elif exit_code != 0:
        await log_fn(f"[trivy] Scan failed with exit code {exit_code}.\n")

    await log_fn("[trivy] --------------------------------\n")
    return exit_code


# ---------------------------------------------------------------------------
# JSON -> Markdown
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


def build_trivy_markdown(json_path: Path, report_path: Path) -> Path:
    """Parse a Trivy JSON result and write a standalone Markdown report."""
    data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))

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

    artifact = data.get("ArtifactName", json_path.parent.name)
    lines = [
        f"# Trivy Report — {_md(artifact)}",
        "",
        "## Summary",
        "",
        f"- Vulnerabilities: {len(vulns)} ({_severity_summary(vulns)})",
        f"- Secrets: {len(secrets)} ({_severity_summary(secrets)})",
        f"- Misconfigurations: {len(misconfigs)} ({_severity_summary(misconfigs)})",
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

    if not (vulns or secrets or misconfigs):
        lines += ["No vulnerabilities, secrets, or misconfigurations were found.", ""]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
