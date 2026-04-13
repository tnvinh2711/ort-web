from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.services.job_store import job_store
from app.services.log_stream import log_stream_hub

router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory="app/templates")


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
def job_panel(request: Request, job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    log_text = ""
    log_path = Path(job.log_file)
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")

    return templates.TemplateResponse(
        request,
        "partials/job_panel.html",
        {"request": request, "job": job, "log_text": log_text},
    )


@router.get("/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    if not job_store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

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
                    # Keep stream open during quiet periods.
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
