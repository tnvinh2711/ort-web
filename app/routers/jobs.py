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
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.i18n import translate
from app.models import Job
from app.services.job_queue import job_queue
from app.services.job_store import job_store
from app.services.log_stream import log_stream_hub
from app.services.vuln_summary import parse_vuln_summary
from app.routers.results import _collect_artifact_files

router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory="app/templates")

def _lang(request: Request) -> str:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return lang if lang in {"vi", "en"} else settings.default_language


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


@router.get("/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang = _lang(request)

    log_text = ""
    log_path = Path(job.log_file)
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")

    artifact_files = _collect_artifact_files(run_dir=job_id)
    ai_report = _load_ai_report(job)

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
            "artifact_files": artifact_files,
            "vuln_summary": parse_vuln_summary(job_id),
            "ai_report": ai_report,
            "base_template": "base_partial.html" if is_htmx else "base.html",
            "status_map": {
                "pending": translate(lang, "status.pending"),
                "running": translate(lang, "status.running"),
                "success": translate(lang, "status.success"),
                "failed": translate(lang, "status.failed"),
                "cancelled": translate(lang, "status.cancelled"),
            },
        },
    )


@router.get("/{job_id}/panel", response_class=HTMLResponse)
def job_inline_panel(request: Request, job_id: str):
    """HTMX partial: inline job panel for dashboard."""
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang = _lang(request)

    log_text = ""
    log_path = Path(job.log_file)
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")

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
            "vuln_summary": parse_vuln_summary(job_id),
            "ai_report": _load_ai_report(job),
            "status_map": {
                "pending": translate(lang, "status.pending"),
                "running": translate(lang, "status.running"),
                "success": translate(lang, "status.success"),
                "failed": translate(lang, "status.failed"),
                "cancelled": translate(lang, "status.cancelled"),
            },
        },
    )


@router.get("/{job_id}/log-text")
def job_log_text(job_id: str):
    """Return raw log text for a job (works for ephemeral jobs too)."""
    from app.config import settings as _settings
    # Try DB first, fall back to log file path derived from job_id
    job = job_store.get_job(job_id)
    log_path = Path(job.log_file) if job else _settings.logs_dir / f"{job_id}.log"
    if log_path.exists():
        return PlainTextResponse(log_path.read_text(encoding="utf-8", errors="replace"))
    return PlainTextResponse("")


@router.get("/{job_id}/files", response_class=HTMLResponse)
def job_files_partial(request: Request, job_id: str):
    """HTMX partial: generated files for a specific job."""
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang = _lang(request)
    artifact_files = _collect_artifact_files(run_dir=job_id)

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
            yield "event: ping\ndata: connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    event_type = str(event.get("type", "message"))
                    payload = json.dumps(event, ensure_ascii=False)
                    yield f"event: {event_type}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: heartbeat\n\n"
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


@router.post("/{job_id}/open-log", response_class=RedirectResponse)
def open_job_log(request: Request, job_id: str) -> RedirectResponse:
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    log_path = Path(job.log_file)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    _open_path(log_path.resolve())

    referer = request.headers.get("referer") or f"/jobs/{job_id}"
    return RedirectResponse(url=referer, status_code=303)
