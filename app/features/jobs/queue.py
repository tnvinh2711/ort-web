from __future__ import annotations

import asyncio
import re
import shlex
import shutil
from pathlib import Path

from app.config import settings
from app.models import Job, JobStatus
from app.features.ort.installer import install_ort_local
from app.features.jobs.event_contract import EVENT_AI_REPORT, EVENT_LOG, EVENT_STATUS, make_event
from app.features.jobs.store import job_store
from app.features.jobs.log_stream import log_stream_hub
from app.features.ort.executor import OrtExecutionError, run_ort_command
from app.features.analysis.ai_suggestion_report import generate_ai_suggestion_report
from app.features.analysis.vuln_summary import parse_vuln_summary


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


async def _run_post_analyze_pipeline(
    job_id: str, analyze_command: str, work_dir: str, log_file: Path
) -> int:
    """Chain after analyze: advise (OSV) → report. Returns the final exit code."""
    output_dir = _extract_output_dir(analyze_command)
    if not output_dir:
        return 0

    analyzer_result = output_dir / "analyzer-result.yml"
    advisor_result = output_dir / "advisor-result.yml"

    # Step 1: Advise
    advise_cmd = (
        f"ort -P ort.forceOverwrite=true advise "
        f"-i {shlex.quote(str(analyzer_result))} "
        f"-o {shlex.quote(str(output_dir))} "
        f"--advisors OSV"
    )
    await _log_info(job_id, log_file, "Analyze completed. Running Advisor (OSV)...")
    advise_exit = await run_ort_command(job_id, advise_cmd, work_dir, log_file)

    # Step 2: Report — use advisor-result when advise succeeded, else fall back to analyzer-result
    input_result = advisor_result if (advise_exit == 0 and advisor_result.exists()) else analyzer_result
    report_cmd = (
        f"ort -P ort.forceOverwrite=true report "
        f"-i {shlex.quote(str(input_result))} "
        f"-o {shlex.quote(str(output_dir))} "
        f"--report-formats StaticHtml,WebApp"
    )
    await _log_info(job_id, log_file, f"Generating report from {input_result.name}...")
    report_exit = await run_ort_command(job_id, report_cmd, work_dir, log_file)

    if report_exit == 0:
        created = _create_analyzer_html_aliases(output_dir)
        for alias in created:
            await _log_info(job_id, log_file, f"Created report alias: {alias.name}")

    return report_exit


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
        should_run = (
            job.status == JobStatus.SUCCESS
            and "analyze" in shlex.split(job.command)
            and has_vulnerabilities
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
            else:
                exit_code = await run_ort_command(job.job_id, job.command, job.work_dir, log_file)
                if exit_code == 0 and "analyze" in shlex.split(job.command):
                    exit_code = await _run_post_analyze_pipeline(
                        job.job_id, job.command, job.work_dir, log_file
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
            job.finished_at = Job.now_iso()
            if not ephemeral:
                job_store.update_job(job)
                self._launch_ai_suggestion_task(job, ephemeral=ephemeral)
            await log_stream_hub.publish(job_id, make_event(EVENT_STATUS, status=job.status.value))


job_queue = JobQueue()
