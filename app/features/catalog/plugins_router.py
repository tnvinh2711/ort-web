from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.features.catalog.registry import PLUGIN_CATEGORIES
from app.i18n import translate

router = APIRouter(prefix="/plugins", tags=["plugins"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def plugins_page(request: Request) -> HTMLResponse:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return templates.TemplateResponse(
        request,
        "plugins/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "categories": PLUGIN_CATEGORIES,
        },
    )
