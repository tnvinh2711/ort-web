"""Router for the environment setup / ort.properties configuration page."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.i18n import translate
from app.features.setup.vertex_config_store import get_vertex_config, mask_secret, save_vertex_config

router = APIRouter(prefix="/setup", tags=["setup"])
templates = Jinja2Templates(directory="app/templates")


def _lang(request: Request) -> str:
    from app.config import settings

    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return lang if lang in {"vi", "en"} else settings.default_language


@router.get("/", response_class=HTMLResponse)
def setup_page(request: Request) -> HTMLResponse:
    lang = _lang(request)
    vertex = get_vertex_config()

    response = templates.TemplateResponse(
        request,
        "setup/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "vertex_configured": vertex.enabled,
            "vertex_model": vertex.model,
            "vertex_api_key_masked": mask_secret(vertex.api_key),
        },
    )
    response.set_cookie("lang", lang)
    return response


@router.get("/api/vertex-config")
async def api_get_vertex_config() -> JSONResponse:
    try:
        cfg = get_vertex_config()
        return JSONResponse(
            {
                "configured": cfg.enabled,
                "model": cfg.model,
                "api_key_masked": mask_secret(cfg.api_key),
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/vertex-config")
async def api_save_vertex_config(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        api_key = str(body.get("api_key", "")).strip()
        model = str(body.get("model", "grok-4.20-reasoning")).strip() or "grok-4.20-reasoning"

        if not api_key:
            return JSONResponse({"error": "api_key is required"}, status_code=400)

        save_vertex_config(api_key=api_key, model=model)
        return JSONResponse(
            {
                "success": True,
                "configured": True,
                "model": model,
                "api_key_masked": mask_secret(api_key),
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
