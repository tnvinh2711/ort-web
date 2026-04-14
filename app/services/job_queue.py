from __future__ import annotations

import asyncio
import re
import shlex
import shutil
from pathlib import Path

from app.config import settings
from app.models import Job, JobStatus
from app.services.ort_installer import install_ort_local
from app.services.job_store import job_store
from app.services.log_stream import log_stream_hub
from app.services.ort_executor import OrtExecutionError, run_ort_command


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


def _build_followup_report_command(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except Exception:
        return None

    if not tokens or tokens[0] != "ort":
        return None

    # The "analyze" subcommand can appear after global flags like "-P key=val".
    if "analyze" not in tokens:
        return None

    output_dir: str | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"-o", "--output-dir"} and i + 1 < len(tokens):
            output_dir = tokens[i + 1]
            i += 1
        elif token.startswith("--output-dir="):
            output_dir = token.split("=", 1)[1]
        i += 1

    if not output_dir:
        return None

    analyzer_result = Path(output_dir) / "analyzer-result.yml"
    return (
        f"ort -P ort.forceOverwrite=true report -i {shlex.quote(str(analyzer_result))} "
        f"-o {shlex.quote(output_dir)} --report-formats StaticHtml,WebApp"
    )


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
        await log_stream_hub.publish(job_id, {"type": "status", "status": job.status.value})

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
                if exit_code == 0:
                    followup_report_command = _build_followup_report_command(job.command)
                    if followup_report_command:
                        with log_file.open("a", encoding="utf-8") as out:
                            out.write("\n[info] Analyze completed. Running follow-up report to generate HTML outputs...\n")
                        await log_stream_hub.publish(
                            job.job_id,
                            {
                                "type": "log",
                                "line": "[info] Analyze completed. Running follow-up report to generate HTML outputs...\n",
                            },
                        )
                        exit_code = await run_ort_command(job.job_id, followup_report_command, job.work_dir, log_file)
                        if exit_code == 0:
                            output_dir: Path | None = None
                            tokens = shlex.split(job.command)
                            for i, token in enumerate(tokens):
                                if token in {"-o", "--output-dir"} and i + 1 < len(tokens):
                                    output_dir = Path(tokens[i + 1])
                                elif token.startswith("--output-dir="):
                                    output_dir = Path(token.split("=", 1)[1])

                            if output_dir:
                                created_aliases = _create_analyzer_html_aliases(output_dir)
                                if created_aliases:
                                    with log_file.open("a", encoding="utf-8") as out:
                                        for alias in created_aliases:
                                            out.write(f"[info] Created analyzer HTML alias: {alias}\n")
                                    for alias in created_aliases:
                                        await log_stream_hub.publish(
                                            job.job_id,
                                            {
                                                "type": "log",
                                                "line": f"[info] Created analyzer HTML alias: {alias}\n",
                                            },
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
        except Exception as exc:  # pragma: no cover
            job.status = JobStatus.FAILED
            job.error_message = f"Unexpected error: {exc}"
            with log_file.open("a", encoding="utf-8") as out:
                out.write(f"[error] Unexpected error: {exc}\n")
        finally:
            job.finished_at = Job.now_iso()
            if not ephemeral:
                job_store.update_job(job)
            await log_stream_hub.publish(job_id, {"type": "status", "status": job.status.value})


job_queue = JobQueue()
