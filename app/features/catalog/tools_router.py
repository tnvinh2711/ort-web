from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.features.catalog.registry import CORE_TOOLS
from app.i18n import translate
from app.shared_templates import templates

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/", response_class=HTMLResponse)
def tools_page(request: Request) -> HTMLResponse:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return templates.TemplateResponse(
        request,
        "tools/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "tools": CORE_TOOLS,
        },
    )
