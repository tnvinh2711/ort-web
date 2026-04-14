from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.i18n import translate
from app.services.job_store import job_store
from app.services.log_stream import log_stream_hub
from app.routers.results import _collect_artifact_files

router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory="app/templates")


def _lang(request: Request) -> str:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or "vi"
    return lang if lang in {"vi", "en"} else "vi"


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
