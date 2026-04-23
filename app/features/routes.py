from __future__ import annotations

from fastapi import FastAPI

from app.features.catalog import commands_router, plugins_router, tools_router
from app.features.dashboard import router as dashboard_router
from app.features.jobs import router as jobs_router
from app.features.results import router as results_router
from app.features.setup import router as setup_router

FEATURE_ROUTERS = (
    dashboard_router.router,
    jobs_router.router,
    tools_router.router,
    commands_router.router,
    plugins_router.router,
    results_router.router,
    setup_router.router,
)


def include_feature_routes(app: FastAPI) -> None:
    for router in FEATURE_ROUTERS:
        app.include_router(router)
