"""Router for the environment setup / ort.properties configuration page."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.i18n import translate
from app.services.language_detector import get_language_options
from app.services.ort_config import generate_config_yml, get_config_yml_path, read_config_yml
from app.services.ort_properties import (
    detect_all_tools,
    get_managers_for_language,
    get_ort_properties_path,
    read_ort_properties,
    write_ort_properties,
)
from app.services.vertex_config_store import get_vertex_config, mask_secret, save_vertex_config

router = APIRouter(prefix="/setup", tags=["setup"])
templates = Jinja2Templates(directory="app/templates")


def _lang(request: Request) -> str:
    from app.config import settings

    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return lang if lang in {"vi", "en"} else settings.default_language


@router.get("/", response_class=HTMLResponse)
def setup_page(request: Request) -> HTMLResponse:
    lang = _lang(request)
    tools = detect_all_tools()
    props_content = read_ort_properties()
    props_path = get_ort_properties_path()
    vertex = get_vertex_config()

    response = templates.TemplateResponse(
        request,
        "setup/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "tools": tools,
            "props_content": props_content,
            "props_path": str(props_path),
            "language_options": get_language_options(),
            "config_yml_content": read_config_yml(),
            "config_yml_path": str(get_config_yml_path()),
            "vertex_configured": vertex.enabled,
            "vertex_model": vertex.model,
            "vertex_api_key_masked": mask_secret(vertex.api_key),
        },
    )
    response.set_cookie("lang", lang)
    return response


@router.post("/api/detect-tools")
async def api_detect_tools(request: Request) -> JSONResponse:
    """Detect all supported package manager tools on PATH."""
    try:
        tools = detect_all_tools()
        return JSONResponse({"tools": tools})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/apply-ort-properties")
async def api_apply_ort_properties(request: Request) -> JSONResponse:
    """Write ort.properties with the selected enabled package managers."""
    try:
        body = await request.json()
        enabled: list[str] = body.get("enabled_managers", [])
        custom_paths: dict[str, str] = body.get("custom_paths", {})

        if not isinstance(enabled, list):
            return JSONResponse({"error": "enabled_managers must be a list"}, status_code=400)

        # Sanitise: only accept known ORT package manager names
        from app.services.ort_properties import PACKAGE_MANAGERS

        known_names = {pm["ort_name"] for pm in PACKAGE_MANAGERS}
        safe_enabled = [m for m in enabled if m in known_names]
        safe_paths = {k: v for k, v in custom_paths.items() if k in known_names and isinstance(v, str)}

        props_path = write_ort_properties(safe_enabled, safe_paths)
        content = props_path.read_text(encoding="utf-8")
        return JSONResponse(
            {
                "success": True,
                "props_path": str(props_path),
                "content": content,
                "enabled_count": len(safe_enabled),
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/auto-select")
async def api_auto_select(request: Request) -> JSONResponse:
    """Return recommended package managers for a given language."""
    try:
        body = await request.json()
        language: str = body.get("language", "")
        if not language:
            return JSONResponse({"error": "language is required"}, status_code=400)

        recommended = get_managers_for_language(language)
        return JSONResponse({"recommended": recommended})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/generate-config")
async def api_generate_config(request: Request) -> JSONResponse:
    """Generate config.yml for a given language."""
    try:
        body = await request.json()
        language: str = body.get("language", "")
        if not language:
            return JSONResponse({"error": "language is required"}, status_code=400)

        config_path = generate_config_yml(language)
        content = config_path.read_text(encoding="utf-8")
        return JSONResponse(
            {
                "success": True,
                "config_path": str(config_path),
                "content": content,
                "language": language,
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


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
