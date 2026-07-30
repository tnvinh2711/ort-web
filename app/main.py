from __future__ import annotations

import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Scope

from app.config import ensure_runtime_dirs, settings
from app.features.jobs.queue import job_queue
from app.features.jobs.store import job_store
from app.features.ort.installer import maintain_ort_runtime_on_startup
from app.features.routes import include_feature_routes


class CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that sets long-lived cache headers.

    Cache-busting is done via ?v={app_version} query param in templates.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_dirs(settings)
    job_store.initialize()
    maintenance_log = settings.runtime_dir / "startup-runtime-maintenance.log"
    try:
        await maintain_ort_runtime_on_startup(maintenance_log)
    except Exception:
        # Runtime maintenance must never make the Setup UI unreachable. The
        # normal job precheck will still block ORT when Java is incompatible.
        with maintenance_log.open("a", encoding="utf-8") as output:
            output.write(
                "[startup] Runtime maintenance failed unexpectedly; "
                "continuing so the issue can be repaired from Setup.\n"
            )
            output.write(traceback.format_exc())
    await job_queue.start()
    try:
        yield
    finally:
        await job_queue.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", CachedStaticFiles(directory="app/static"), name="static")

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
