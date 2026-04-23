from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
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
