from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ensure_runtime_dirs, settings
from app.routers import commands, dashboard, jobs, plugins, results, setup, tools
from app.services.job_queue import job_queue
from app.services.job_store import job_store


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

app.include_router(dashboard.router)
app.include_router(jobs.router)
app.include_router(tools.router)
app.include_router(commands.router)
app.include_router(plugins.router)
app.include_router(results.router)
app.include_router(setup.router)
