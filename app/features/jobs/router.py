from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse

from app.config import settings
from app.i18n import translate
from app.models import Job
from app.features.jobs.queue import job_queue
from app.features.jobs.event_contract import connected_payload, heartbeat_payload, to_sse_payload
from app.features.jobs.store import job_store
from app.features.jobs.log_stream import log_stream_hub
from app.features.analysis.vuln_summary import get_vuln_summary
from app.features.analysis.markdown_report import generate_markdown_report
from app.features.results.router import _collect_artifact_files
from app.features.setup.vertex_config_store import get_vertex_config
from app.shared_templates import templates

router = APIRouter(prefix="/jobs", tags=["jobs"])

def _lang(request: Request) -> str:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return lang if lang in {"vi", "en"} else settings.default_language


_LOG_TAIL_BYTES = 256 * 1024  # 256 KB tail for inline display


def _read_log_tail(log_path: Path) -> str:
    """Read the tail of a log file. Returns full content if smaller than threshold."""
    if not log_path.exists():
        return ""
    try:
        size = log_path.stat().st_size
        if size <= _LOG_TAIL_BYTES:
            return log_path.read_text(encoding="utf-8", errors="replace")
        with log_path.open("rb") as f:
            f.seek(-_LOG_TAIL_BYTES, 2)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        # Drop partial first line (likely cut mid-utf8 or mid-line)
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
        return f"[log truncated — showing last {_LOG_TAIL_BYTES // 1024} KB of {size // 1024} KB]\n" + text
    except Exception:
        return ""


def _format_datetime(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return value


def _open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if os.name == "posix":
        opener = "open"
        subprocess.run([opener, str(path)], check=False)
        return
    raise RuntimeError("Unsupported platform for open file action")


def _load_ai_report(job: Job) -> dict | None:
    report_path = Path(job.ai_report_path) if job.ai_report_path else settings.artifacts_dir / job.job_id / "ai-suggestions.json"
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


@router.get("/{job_id}/panel", response_class=HTMLResponse)
async def job_inline_panel(request: Request, job_id: str):
    """HTMX partial: inline job panel for dashboard."""
    job = await asyncio.to_thread(job_store.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang = _lang(request)
    ai_key_configured = bool(get_vertex_config().api_key.strip())

    log_path = Path(job.log_file)
    log_text, vuln_summary, ai_report = await asyncio.gather(
        asyncio.to_thread(_read_log_tail, log_path),
        asyncio.to_thread(get_vuln_summary, job.vuln_summary_json),
        asyncio.to_thread(_load_ai_report, job),
    )

    return templates.TemplateResponse(
        request,
        "jobs/inline_panel.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "fmt_dt": _format_datetime,
            "job": job,
            "log_text": log_text,
            "vuln_summary": vuln_summary,
            "ai_report": ai_report,
            "ai_key_configured": ai_key_configured,
            "status_map": {
                "pending": translate(lang, "status.pending"),
                "running": translate(lang, "status.running"),
                "success": translate(lang, "status.success"),
                "failed": translate(lang, "status.failed"),
                "cancelled": translate(lang, "status.cancelled"),
            },
        },
    )


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_detail_page(request: Request, job_id: str) -> HTMLResponse:
    """Standalone job detail page (no inline expand)."""
    job = await asyncio.to_thread(job_store.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang = _lang(request)
    ai_key_configured = bool(get_vertex_config().api_key.strip())
    log_path = Path(job.log_file)
    log_text, vuln_summary, ai_report = await asyncio.gather(
        asyncio.to_thread(_read_log_tail, log_path),
        asyncio.to_thread(get_vuln_summary, job.vuln_summary_json),
        asyncio.to_thread(_load_ai_report, job),
    )

    is_htmx = request.headers.get("HX-Request")
    return templates.TemplateResponse(
        request,
        "jobs/detail.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "fmt_dt": _format_datetime,
            "job": job,
            "log_text": log_text,
            "vuln_summary": vuln_summary,
            "ai_report": ai_report,
            "ai_key_configured": ai_key_configured,
            "status_map": {
                "pending": translate(lang, "status.pending"),
                "running": translate(lang, "status.running"),
                "success": translate(lang, "status.success"),
                "failed": translate(lang, "status.failed"),
                "cancelled": translate(lang, "status.cancelled"),
            },
            "base_template": "base_partial.html" if is_htmx else "base.html",
        },
    )


@router.get("/{job_id}/log-text")
async def job_log_text(job_id: str):
    """Return raw log text for a job (works for ephemeral jobs too)."""
    from app.config import settings as _settings
    job = await asyncio.to_thread(job_store.get_job, job_id)
    log_path = Path(job.log_file) if job else _settings.logs_dir / f"{job_id}.log"
    if log_path.exists():
        text = await asyncio.to_thread(log_path.read_text, encoding="utf-8", errors="replace")
        return PlainTextResponse(text)
    return PlainTextResponse("")


@router.get("/{job_id}/files", response_class=HTMLResponse)
async def job_files_partial(request: Request, job_id: str):
    """HTMX partial: generated files for a specific job."""
    job = await asyncio.to_thread(job_store.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang = _lang(request)
    artifact_files = await asyncio.to_thread(_collect_artifact_files, run_dir=job_id)

    return templates.TemplateResponse(
        request,
        "jobs/files_partial.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "artifact_files": artifact_files,
        },
    )


@router.post("/{job_id}/generate-markdown-report", response_class=HTMLResponse)
async def generate_job_markdown_report(request: Request, job_id: str):
    """Refresh the generated Markdown report for a completed job."""
    job = await asyncio.to_thread(job_store.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    output_dir = (settings.artifacts_dir / job_id).resolve()
    report_path = await asyncio.to_thread(generate_markdown_report, output_dir)
    if not report_path:
        raise HTTPException(status_code=404, detail="No ORT result data found for this job.")

    lang = _lang(request)
    artifact_files = await asyncio.to_thread(_collect_artifact_files, run_dir=job_id)
    return templates.TemplateResponse(
        request,
        "jobs/files_partial.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "artifact_files": artifact_files,
        },
    )


@router.get("/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    # Allow ephemeral jobs (not in DB) — just subscribe to the stream
    queue = log_stream_hub.subscribe(job_id)

    async def stream():
        try:
            yield connected_payload()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield to_sse_payload(event)
                except asyncio.TimeoutError:
                    yield heartbeat_payload()
        finally:
            log_stream_hub.unsubscribe(job_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{job_id}/run-advise")
async def run_advise(job_id: str) -> JSONResponse:
    """Create and enqueue an advise job from a completed analyze job."""
    parent = job_store.get_job(job_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Job not found")

    if parent.status.value != "success":
        raise HTTPException(status_code=400, detail="Analyze job has not completed successfully.")

    if "analyze" not in parent.command:
        raise HTTPException(status_code=400, detail="Job is not an analyze job.")

    # Resolve analyzer-result.yml from the parent job's output dir
    parent_output_dir = (settings.artifacts_dir / job_id).resolve()
    analyzer_result = parent_output_dir / "analyzer-result.yml"
    if not analyzer_result.exists():
        raise HTTPException(status_code=404, detail="analyzer-result.yml not found for this job.")

    new_job_id = uuid4().hex
    new_output_dir = (settings.artifacts_dir / new_job_id).resolve()
    log_file = settings.logs_dir / f"{new_job_id}.log"

    advise_command = (
        f"ort -P ort.forceOverwrite=true advise "
        f"-i {shlex.quote(str(analyzer_result))} "
        f"-o {shlex.quote(str(new_output_dir))} "
        f"--advisors OSV"
    )

    project_name = Path(parent.project_path or parent.work_dir).name
    new_job = Job(
        job_id=new_job_id,
        name=f"ORT Advise {project_name}",
        command=advise_command,
        work_dir=parent.work_dir,
        language=parent.language,
        project_path=parent.project_path,
        detected_language=parent.detected_language,
        created_at=Job.now_iso(),
        log_file=str(log_file),
    )
    await job_queue.enqueue(new_job)

    return JSONResponse({"job_id": new_job_id})


@router.get("/{job_id}/api/status")
async def get_job_status(job_id: str) -> JSONResponse:
    """Get current job and AI report status for polling."""
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JSONResponse({
        "status": job.status.value,
        "ai_report_status": job.ai_report_status or "not-started",
        "ai_report_summary": job.ai_report_summary or ""
    })


@router.post("/{job_id}/retry-ai-report")
async def retry_ai_report(job_id: str) -> JSONResponse:
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.ai_report_status == "pending":
        return JSONResponse({"success": False, "error": "AI report is already generating."}, status_code=409)

    accepted = job_queue.retry_ai_report(job_id)
    if not accepted:
        return JSONResponse({"success": False, "error": "Cannot start AI report retry."}, status_code=400)

    return JSONResponse({"success": True, "status": "pending"})


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str) -> JSONResponse:
    """Cancel a running or pending job and erase all of its data.

    Kills the live ORT subprocess tree (if any), then deletes the DB row,
    log file, and artifact directory. Cancelling a finished job is a no-op
    against the queue but still removes any leftover data on disk.
    """
    job = await asyncio.to_thread(job_store.get_job, job_id)
    if not job and job_id not in job_queue._running_processes and job_id not in job_queue._ephemeral_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    if job and job.status.value in {"success", "failed", "cancelled"}:
        return JSONResponse(
            {"cancelled": False, "reason": "Job already finished."},
            status_code=409,
        )

    result = await job_queue.cancel_job(job_id)
    return JSONResponse(result)


@router.post("/{job_id}/open-log", response_class=RedirectResponse)
def open_job_log(request: Request, job_id: str) -> RedirectResponse:
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    log_path = Path(job.log_file)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    _open_path(log_path.resolve())

    lang = _lang(request)
    referer = request.headers.get("referer") or f"/results?lang={lang}"
    return RedirectResponse(url=referer, status_code=303)
