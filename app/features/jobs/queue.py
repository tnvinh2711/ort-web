from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from app.config import settings
from app.models import Job, JobStatus
from app.features.ort.installer import install_ort_local
from app.features.ort.env_installer import install_environment
from app.features.jobs.event_contract import EVENT_AI_REPORT, EVENT_LOG, EVENT_STATUS, make_event
from app.features.jobs.store import job_store
from app.features.jobs.log_stream import log_stream_hub
from app.features.ort.executor import OrtExecutionError, run_ort_command
from app.features.ort.precheck import run_environment_precheck
from app.features.trivy.scanner import run_trivy_scan
from app.features.analysis.ai_suggestion_report import generate_ai_suggestion_report
from app.features.analysis.component_inventory_csv import generate_component_inventory_csv
from app.features.analysis.markdown_report import generate_markdown_report
from app.features.analysis.vuln_summary import parse_trivy_vuln_summary, parse_vuln_summary
from app.features.setup.vertex_config_store import get_vertex_config


def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    """Best-effort kill of an ORT subprocess and any children it spawned.

    On Windows, ``taskkill /F /T`` walks the win32 job tree (cmd.exe -> ort.bat -> java).
    On POSIX, the process is its own session leader (see executor.py), so we
    signal the whole process group.
    """
    if process.returncode is not None:
        return
    pid = process.pid
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
    except Exception:
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _purge_job_data(job_id: str) -> None:
    """Delete DB row, log file, and artifact dir for a job. Best-effort."""
    try:
        job_store.delete_job(job_id)
    except Exception:
        pass
    try:
        (settings.logs_dir / f"{job_id}.log").unlink(missing_ok=True)
    except Exception:
        pass
    artifact_dir = settings.artifacts_dir / job_id
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir, ignore_errors=True)


def _extract_failure_reason(log_file: Path) -> str | None:
    if not log_file.exists():
        return None

    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    if not lines:
        return None

    pattern = re.compile(r"(error|exception|failed|not found|denied|invalid)", re.IGNORECASE)
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        if pattern.search(text):
            return text[:300]

    for line in reversed(lines):
        text = line.strip()
        if text:
            return text[:300]

    return None


def _extract_output_dir(command: str) -> Path | None:
    """Extract the -o / --output-dir value from an ORT command string."""
    try:
        tokens = shlex.split(command)
    except Exception:
        return None
    i = 0
    while i < len(tokens):
        if tokens[i] in {"-o", "--output-dir"} and i + 1 < len(tokens):
            return Path(tokens[i + 1])
        if tokens[i].startswith("--output-dir="):
            return Path(tokens[i].split("=", 1)[1])
        i += 1
    return None




async def _log_info(job_id: str, log_file: Path, message: str) -> None:
    line = f"[info] {message}\n"
    with log_file.open("a", encoding="utf-8") as out:
        out.write(line)
    await log_stream_hub.publish(job_id, make_event(EVENT_LOG, line=line))


async def _generate_markdown_report_for_job(
    job_id: str, output_dir: Path, log_file: Path, *, reason: str = ""
) -> None:
    try:
        md_path = generate_markdown_report(output_dir)
        if md_path:
            suffix = f" ({reason})" if reason else ""
            await _log_info(job_id, log_file, f"Generated Markdown report{suffix}: {md_path}")
        else:
            await _log_info(job_id, log_file, "Skipped Markdown report: no ORT result data.")
    except Exception as exc:
        await _log_info(job_id, log_file, f"Markdown report generation failed: {exc}")


async def _heal_scancode_cache(job_id: str, log_file: Path) -> None:
    """Detect and clear a corrupt or locked ScanCode license cache.

    Two failure modes that cause 20+ minute hangs:
    1. Corrupt cache (MemoryError on pickle.load) — ScanCode rebuilds the full
       38k-license index on every file instead of loading once from disk.
    2. Stale lock file — a previous run killed mid-build leaves a FileLock that
       blocks any new run for up to 360 seconds per file, then raises LockTimeout.

    Both are fixed by deleting the offending files before ORT invokes ScanCode.
    ScanCode will rebuild the cache cleanly on the next run (~2 min, one-time).
    """
    import pickle as _pickle
    import time as _time

    if not shutil.which("scancode"):
        return

    try:
        import importlib.util as _ilu
        spec = _ilu.find_spec("licensedcode")
        if not spec or not spec.origin:
            return
        cache_dir = Path(spec.origin).parent / "data" / "cache" / "license_index"
    except Exception:
        return

    cache_file = cache_dir / "index_cache"
    lock_file  = cache_dir / "index_cache.lock"

    # 1. Remove stale lock (mtime > 10 min → almost certainly orphaned)
    if lock_file.exists():
        try:
            age = _time.time() - lock_file.stat().st_mtime
            if age > 600:
                lock_file.unlink(missing_ok=True)
                await _log_info(
                    job_id, log_file,
                    f"Removed stale ScanCode lock file (age {int(age)}s): {lock_file}"
                )
        except Exception:
            pass

    # 2. Validate cache integrity; delete if corrupt
    if not cache_file.exists():
        return

    try:
        with cache_file.open("rb") as f:
            _pickle.load(f)
    except Exception as exc:
        await _log_info(
            job_id, log_file,
            f"ScanCode license cache corrupt ({type(exc).__name__}) — "
            f"deleting to force rebuild (one-time ~2 min): {cache_file}"
        )
        try:
            cache_file.unlink(missing_ok=True)
            lock_file.unlink(missing_ok=True)
        except Exception:
            pass


def _advise_input(
    analyzer_result: Path, scan_result: Path, scan_exit: int
) -> Path:
    return scan_result if scan_exit == 0 and scan_result.exists() else analyzer_result


async def _run_post_analyze_pipeline(
    job: Job, log_file: Path
) -> int:
    """Chain after analyze: scan -> advise (OSV) -> report -> inventory CSV.

    Mutates ``job.vuln_summary_json`` in place so the caller's final
    ``job_store.update_job(job)`` persists it. Writing through a fresh fetch
    here would be silently overwritten by that final update.
    """
    job_id = job.job_id
    output_dir = _extract_output_dir(job.command)
    if not output_dir:
        return 0

    analyzer_result = output_dir / "analyzer-result.yml"
    scan_result = output_dir / "scan-result.yml"
    advisor_result = output_dir / "advisor-result.yml"

    # Step 1: Scan licenses with ScanCode. Existing jobs retain the Swift
    # default; new dashboard jobs use their explicit toggle setting.
    scan_exit = 1
    swift_license_scan = job.detected_language == "swift"
    scan_enabled = (
        getattr(job, "scancode_enabled", None)
        if getattr(job, "scancode_enabled", None) is not None
        else swift_license_scan or os.environ.get("ORT_WEB_ENABLE_SCAN", "0").strip() == "1"
    )
    scancode_available = (
        shutil.which("scancode")
        or shutil.which("scancode.exe")
        or shutil.which("scancode", path=str(Path(sys.executable).parent))
        or shutil.which("scancode.exe", path=str(Path(sys.executable).parent))
    )

    if not scan_enabled:
        await _log_info(
            job_id, log_file,
            "Scanner step skipped by the ScanCode job option."
        )
    elif not scancode_available:
        reason = "Swift license detection skipped" if swift_license_scan else "Scanner skipped"
        await _log_info(
            job_id, log_file,
            f"{reason}: ScanCode not found in PATH. Install with: pip install scancode-toolkit"
        )
    else:
        # Guard against corrupt cache before invoking ORT.
        await _heal_scancode_cache(job_id, log_file)
        # Scanning every dependency provenance is prohibitively expensive for
        # large Node.js graphs (often 1,000+ separate downloads and ScanCode
        # invocations). Their declared licenses are already available from the
        # analyzer and Trivy performs a full license pass over installed source.
        # Keep package scanning for Swift, where dependency source scanning is
        # required to recover license data that Swift manifests do not declare.
        package_types = "" if swift_license_scan else " --package-types PROJECT"
        scan_cmd = (
            f"ort -P ort.forceOverwrite=true scan "
            f"-i {shlex.quote(str(analyzer_result))} "
            f"-o {shlex.quote(str(output_dir))} "
            f"--scanners ScanCode"
            f"{package_types}"
        )
        scan_scope = "projects and packages" if swift_license_scan else "project source only"
        await _log_info(
            job_id,
            log_file,
            f"Running Scanner (ScanCode, {scan_scope})...",
        )
        scan_exit = await run_ort_command(job_id, scan_cmd, job.work_dir, log_file)
        if scan_exit != 0:
            await _log_info(job_id, log_file, "Scanner step failed — continuing without scan results.")

    # ScanCode-only is a license job. It still needs analyzer-result.yml as
    # input, but must never call OSV or Trivy's vulnerability pass.
    if getattr(job, "analysis_enabled", None) is False:
        input_result = scan_result if scan_exit == 0 and scan_result.exists() else analyzer_result
        report_cmd = (
            f"ort -P ort.forceOverwrite=true report "
            f"-i {shlex.quote(str(input_result))} "
            f"-o {shlex.quote(str(output_dir))} "
            f"--report-formats StaticHtml,WebApp"
        )
        await _log_info(
            job_id, log_file,
            "ORT ScanCode step completed. Generating license report..."
        )
        report_exit = await run_ort_command(job_id, report_cmd, job.work_dir, log_file)
        if report_exit == 0:
            for alias in _create_analyzer_html_aliases(output_dir):
                await _log_info(job_id, log_file, f"Created report alias: {alias.name}")
        try:
            csv_path = generate_component_inventory_csv(output_dir)
            if csv_path:
                await _log_info(job_id, log_file, f"Generated component inventory CSV: {csv_path.name}")
        except Exception as exc:
            await _log_info(job_id, log_file, f"Component inventory CSV generation failed: {exc}")
        await _generate_markdown_report_for_job(job_id, output_dir, log_file, reason="ScanCode-only")
        return report_exit

    # Step 2: Advise. Feed the scan result forward when available so its
    # detected licenses survive alongside OSV vulnerabilities.
    advise_input = _advise_input(analyzer_result, scan_result, scan_exit)
    advise_cmd = (
        f"ort -P ort.forceOverwrite=true advise "
        f"-i {shlex.quote(str(advise_input))} "
        f"-o {shlex.quote(str(output_dir))} "
        f"--advisors OSV"
    )
    await _log_info(job_id, log_file, "Analyze completed. Running Advisor (OSV)...")
    advise_exit = await run_ort_command(job_id, advise_cmd, job.work_dir, log_file)

    # Step 3: Report — prefer advisor, then scan (if available), then analyzer.
    if advise_exit == 0 and advisor_result.exists():
        input_result = advisor_result
    elif scan_exit == 0 and scan_result.exists():
        input_result = scan_result
    else:
        input_result = analyzer_result

    report_cmd = (
        f"ort -P ort.forceOverwrite=true report "
        f"-i {shlex.quote(str(input_result))} "
        f"-o {shlex.quote(str(output_dir))} "
        f"--report-formats StaticHtml,WebApp"
    )
    await _log_info(job_id, log_file, f"Generating report from {input_result.name}...")
    report_exit = await run_ort_command(job_id, report_cmd, job.work_dir, log_file)

    if report_exit == 0:
        created = _create_analyzer_html_aliases(output_dir)
        for alias in created:
            await _log_info(job_id, log_file, f"Created report alias: {alias.name}")

    # Step 4: CSV inventory (best effort, should not fail pipeline).
    try:
        csv_path = generate_component_inventory_csv(output_dir)
        if csv_path:
            await _log_info(job_id, log_file, f"Generated component inventory CSV: {csv_path.name}")
        else:
            await _log_info(job_id, log_file, "Skipped component inventory CSV: no analyzer/scan package data.")
    except Exception as exc:
        await _log_info(job_id, log_file, f"Component inventory CSV generation failed: {exc}")

    # Step 5: Markdown report (automatic, best effort).
    await _generate_markdown_report_for_job(job_id, output_dir, log_file, reason="ORT pipeline")

    # Step 6: Cache vuln summary on the job. Store "null" (not Python None) so
    # DB-cached=True even when no vulns found — None means "never computed" and
    # would force YAML re-parse on every list load. The caller persists this
    # via its final job_store.update_job(job).
    try:
        import json as _json
        summary = parse_vuln_summary(job_id)
        job.vuln_summary_json = _json.dumps(summary)
    except Exception:
        pass

    return report_exit


def _cache_trivy_vuln_summary(job: Job) -> None:
    """Persist the Trivy counts after its JSON artifact has been written."""
    try:
        import json as _json
        parse_trivy_vuln_summary.cache_clear()
        job.trivy_vuln_summary_json = _json.dumps(parse_trivy_vuln_summary(job.job_id))
    except Exception:
        pass


def _create_analyzer_html_aliases(output_dir: Path) -> list[Path]:
    created: list[Path] = []
    mapping = {
        output_dir / "scan-report.html": output_dir / "analyzer-report.html",
        output_dir / "scan-report-web-app.html": output_dir / "analyzer-report-web-app.html",
    }

    for source, target in mapping.items():
        if source.exists():
            shutil.copy2(source, target)
            created.append(target)

    return created


class JobQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._started = False
        self._ephemeral_jobs: dict[str, Job | None] = {}
        # Live subprocess handles, keyed by job_id, so we can kill on cancel.
        self._running_processes: dict[str, asyncio.subprocess.Process] = {}
        # Job IDs the user has cancelled — suppresses post-run DB writes and
        # post-analyze pipeline steps in the worker.
        self._cancelled: set[str] = set()

    async def start(self) -> None:
        if self._started:
            return

        job_store.mark_running_jobs_as_failed()

        for _ in range(settings.max_parallel_jobs):
            self._workers.append(asyncio.create_task(self._worker_loop()))
        self._started = True

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    async def enqueue(self, job: Job, *, ephemeral: bool = False) -> None:
        if not ephemeral:
            job_store.create_job(job)
        self._ephemeral_jobs[job.job_id] = job if ephemeral else None
        await self._queue.put(job.job_id)

    async def cancel_job(self, job_id: str) -> dict:
        """Cancel a pending or running job and erase all of its data.

        Kills the live subprocess tree (if any), marks the job as cancelled so
        the worker skips post-run bookkeeping, then deletes the DB row, log,
        and artifact directory. Returns ``{"cancelled": bool, "reason": str}``.
        """
        # Mark as cancelled BEFORE killing — the worker checks this set in its
        # finally block and skips DB writes / AI report scheduling accordingly.
        self._cancelled.add(job_id)

        process = self._running_processes.get(job_id)
        was_running = process is not None and process.returncode is None
        if was_running:
            _kill_process_tree(process)  # type: ignore[arg-type]

        await log_stream_hub.publish(
            job_id, make_event(EVENT_STATUS, status=JobStatus.CANCELLED.value)
        )

        await asyncio.to_thread(_purge_job_data, job_id)
        self._ephemeral_jobs.pop(job_id, None)

        return {"cancelled": True, "was_running": was_running}

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run(job_id)
            finally:
                self._queue.task_done()

    def retry_ai_report(self, job_id: str) -> bool:
        """Trigger AI report regeneration for an existing job without rerunning ORT."""
        job = job_store.get_job(job_id)
        if not job:
            return False
        if not get_vertex_config().api_key.strip():
            return False
        if job.ai_report_status == "pending":
            return False

        job.ai_report_status = "pending"
        job.ai_report_path = None
        job.ai_report_summary = "Retry requested. Generating AI report in background..."
        job_store.update_job(job)
        asyncio.create_task(
            log_stream_hub.publish(
                job.job_id,
                make_event(
                    EVENT_AI_REPORT,
                    status="pending",
                    summary=job.ai_report_summary,
                ),
            )
        )
        asyncio.create_task(self._run_ai_suggestion_report(job_id))
        return True

    def _launch_ai_suggestion_task(self, job: Job, *, ephemeral: bool) -> None:
        vuln = parse_vuln_summary(job.job_id)
        has_vulnerabilities = bool(vuln and vuln.get("total", 0) > 0)
        ai_key_configured = bool(get_vertex_config().api_key.strip())
        should_run = (
            job.status == JobStatus.SUCCESS
            and "analyze" in shlex.split(job.command)
            and has_vulnerabilities
            and ai_key_configured
        )
        if ephemeral or not should_run:
            return

        job.ai_report_status = "pending"
        job.ai_report_path = None
        job.ai_report_summary = None
        job_store.update_job(job)
        asyncio.create_task(
            log_stream_hub.publish(
                job.job_id,
                make_event(EVENT_AI_REPORT, status="pending", summary=""),
            )
        )

        asyncio.create_task(self._run_ai_suggestion_report(job.job_id))

    async def _run_ai_suggestion_report(self, job_id: str) -> None:
        job = job_store.get_job(job_id)
        if not job:
            return

        result = await generate_ai_suggestion_report(
            job_id=job.job_id,
            error_message="Vulnerabilities detected by ORT advisor results.",
            command=job.command,
        )

        latest = job_store.get_job(job_id)
        if not latest:
            return

        latest.ai_report_status = str(result.get("status", "failed"))
        latest.ai_report_path = str(result.get("path", "")) or None
        latest.ai_report_summary = str(result.get("summary", "")) or None
        job_store.update_job(latest)
        await log_stream_hub.publish(
            latest.job_id,
            make_event(
                EVENT_AI_REPORT,
                status=latest.ai_report_status,
                summary=latest.ai_report_summary or "",
            ),
        )

    async def _run(self, job_id: str) -> None:
        # Job was cancelled while still pending in the queue — skip entirely.
        if job_id in self._cancelled:
            self._cancelled.discard(job_id)
            self._ephemeral_jobs.pop(job_id, None)
            return

        ephemeral = job_id in self._ephemeral_jobs and self._ephemeral_jobs[job_id] is not None
        if ephemeral:
            job = self._ephemeral_jobs.pop(job_id)
        else:
            self._ephemeral_jobs.pop(job_id, None)
            job = job_store.get_job(job_id)
        if not job:
            return

        job.status = JobStatus.RUNNING
        job.started_at = Job.now_iso()
        if not ephemeral:
            job_store.update_job(job)
        await log_stream_hub.publish(job_id, make_event(EVENT_STATUS, status=job.status.value))

        log_file = Path(job.log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        register = lambda p: self._running_processes.__setitem__(job_id, p)  # noqa: E731

        try:
            if job.command == "__install_ort__" or job.command.startswith("__install_ort__::"):
                target_dir: Path | None = None
                if job.command.startswith("__install_ort__::"):
                    raw_dir = job.command.split("::", 1)[1].strip()
                    if raw_dir:
                        target_dir = Path(raw_dir)
                exit_code, ort_path = await install_ort_local(job.job_id, log_file, target_dir)
                if ort_path:
                    job.ort_install_path = ort_path
            elif job.command == "__install_env__" or job.command.startswith("__install_env__::"):
                env_work_dir = job.work_dir
                if job.command.startswith("__install_env__::"):
                    raw_dir = job.command.split("::", 1)[1].strip()
                    if raw_dir:
                        env_work_dir = raw_dir
                exit_code = await install_environment(job.job_id, env_work_dir, log_file)
            elif job.command == "__trivy_scan__" or job.command.startswith("__trivy_scan__::"):
                target = job.work_dir
                if job.command.startswith("__trivy_scan__::"):
                    raw_target = job.command.split("::", 1)[1].strip()
                    if raw_target:
                        target = raw_target
                trivy_out_dir = (settings.artifacts_dir / job.job_id).resolve()
                exit_code = await run_trivy_scan(
                    job.job_id, target, trivy_out_dir, log_file,
                    on_process_start=register,
                )
                _cache_trivy_vuln_summary(job)
            else:
                try:
                    _pre_tokens = shlex.split(job.command)
                except Exception:
                    _pre_tokens = []

                # Pre-flight: verify ORT, Java, and relevant package managers are
                # present before spending time in the queue only to fail immediately.
                precheck_ok = await run_environment_precheck(
                    job.job_id, job.work_dir, log_file, _pre_tokens
                )
                if not precheck_ok:
                    raise OrtExecutionError(
                        "Environment precheck failed: ORT or Java not found in PATH."
                    )

                # For analyze jobs, prepare dependencies where a separate
                # package-manager invocation is useful. Gradle is deliberately
                # excluded; ORT uses its Tooling API directly with shared cache.
                if "analyze" in _pre_tokens:
                    await _log_info(
                        job.job_id, log_file,
                        "Preparing project dependencies..."
                    )
                    await install_environment(
                        job.job_id,
                        job.work_dir,
                        log_file,
                        node_tool_only=True,
                    )

                    # Re-generate ort.properties now that env_installer may have
                    # installed new tools (e.g. conan, maven, poetry).  ORT throws
                    # an unhandled exception — crashing the whole job — when it
                    # tries to invoke a package manager binary that does not exist,
                    # so we must only enable tools actually present in PATH.
                    if job.detected_language:
                        from app.features.ort.properties import auto_generate_ort_properties
                        updated = auto_generate_ort_properties(
                            job.detected_language, project_path=job.work_dir
                        )
                        await _log_info(
                            job.job_id, log_file,
                            f"ort.properties updated with available tools: {updated}"
                        )

                # ORT's DirectoryStash can hit AccessDeniedException for
                # large/deep node_modules trees on Windows. Keep the workaround
                # Windows-only; deleting dependencies on macOS/Linux needlessly
                # forces a fresh install on every analysis.
                if "analyze" in _pre_tokens and os.name == "nt":
                    _wd = Path(job.work_dir)
                    for _nm in _wd.rglob("node_modules"):
                        if _nm.is_dir() and "node_modules" not in _nm.relative_to(_wd).parent.parts:
                            shutil.rmtree(_nm, ignore_errors=True)

                exit_code = await run_ort_command(
                    job.job_id, job.command, job.work_dir, log_file,
                    on_process_start=register,
                )
                command_tokens = shlex.split(job.command)
                # Skip post-run pipeline if the user cancelled mid-run — the
                # subprocess was killed and the job's data is being purged.
                if job_id in self._cancelled:
                    return
                if exit_code == 0 and "analyze" in command_tokens:
                    exit_code = await _run_post_analyze_pipeline(job, log_file)
                # Trivy runs alongside ORT on every analyze job, into the same
                # artifact dir, so both result sets surface together. It is
                # independent: runs even if the ORT pipeline above failed, and a
                # Trivy failure is logged but never fails the job (ORT is primary).
                analysis_enabled = getattr(job, "analysis_enabled", None)
                scancode_enabled = getattr(job, "scancode_enabled", None)
                if (
                    "analyze" in command_tokens
                    and (analysis_enabled is not False or scancode_enabled is True)
                    and job_id not in self._cancelled
                ):
                    trivy_dir = (settings.artifacts_dir / job_id).resolve()
                    trivy_target = job.project_path or job.work_dir
                    try:
                        await run_trivy_scan(
                            job.job_id, trivy_target, trivy_dir, log_file,
                            on_process_start=register,
                            include_vulnerabilities=analysis_enabled is not False,
                            include_licenses=scancode_enabled,
                        )
                        _cache_trivy_vuln_summary(job)
                    except Exception as exc:
                        await _log_info(
                            job_id, log_file, f"Trivy scan failed (non-fatal): {exc}"
                        )
                elif exit_code == 0 and "report" in command_tokens:
                    output_dir = _extract_output_dir(job.command)
                    if output_dir:
                        await _generate_markdown_report_for_job(
                            job.job_id, output_dir, log_file, reason="ORT report"
                        )
            job.exit_code = exit_code
            job.status = JobStatus.SUCCESS if exit_code == 0 else JobStatus.FAILED
            if job.status == JobStatus.FAILED and not job.error_message:
                job.error_message = _extract_failure_reason(log_file) or "Command failed with non-zero exit code."
        except OrtExecutionError as exc:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            with log_file.open("a", encoding="utf-8") as out:
                out.write(f"[error] {exc}\n")
            await log_stream_hub.publish(job.job_id, make_event(EVENT_LOG, line=f"[error] {exc}\n"))
        except Exception as exc:  # pragma: no cover
            job.status = JobStatus.FAILED
            job.error_message = f"Unexpected error: {exc}"
            with log_file.open("a", encoding="utf-8") as out:
                out.write(f"[error] Unexpected error: {exc}\n")
            await log_stream_hub.publish(
                job.job_id,
                make_event(EVENT_LOG, line=f"[error] Unexpected error: {exc}\n"),
            )
        finally:
            self._running_processes.pop(job_id, None)
            cancelled = job_id in self._cancelled
            self._cancelled.discard(job_id)
            if cancelled:
                # cancel_job() has already wiped DB row, log file, and artifacts;
                # don't re-create the row by writing back through job_store.
                return
            job.finished_at = Job.now_iso()
            if not ephemeral:
                job_store.update_job(job)
                self._launch_ai_suggestion_task(job, ephemeral=ephemeral)
            await log_stream_hub.publish(job_id, make_event(EVENT_STATUS, status=job.status.value))


job_queue = JobQueue()
