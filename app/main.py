from __future__ import annotations

import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import ensure_runtime_dirs, settings
from app.features.jobs.queue import job_queue
from app.features.jobs.store import job_store
from app.features.routes import include_feature_routes


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_dirs(settings)
    job_store.initialize()
    await job_queue.start()
    try:
        yield
    finally:
        await job_queue.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

include_feature_routes(app)


@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception) -> HTMLResponse:
    tb = traceback.format_exc()
    html = (
        "<html><body style='font-family:monospace;padding:24px'>"
        f"<h2 style='color:red'>Server Error: {type(exc).__name__}</h2>"
        f"<pre style='background:#f5f5f5;padding:16px;border-radius:6px;overflow:auto'>{tb}</pre>"
        f"<p style='color:#666'>Path: {request.url}</p>"
        "</body></html>"
    )
    return HTMLResponse(content=html, status_code=500)
