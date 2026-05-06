from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.features.catalog.registry import SUPPORTING_COMMANDS
from app.i18n import translate
from app.shared_templates import templates

router = APIRouter(prefix="/commands", tags=["commands"])


@router.get("/", response_class=HTMLResponse)
def commands_page(request: Request) -> HTMLResponse:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return templates.TemplateResponse(
        request,
        "commands/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "commands": SUPPORTING_COMMANDS,
        },
    )
