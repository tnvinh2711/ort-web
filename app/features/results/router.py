from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.i18n import translate
from app.features.shared.language_detector import get_language_options

# Files to hide from the results listing.
_HIDDEN_FILENAMES = {"analyzer-report.html", "analyzer-report-web-app.html"}
_HIDDEN_SUFFIXES = {".xml", ".yml", ".yaml"}

router = APIRouter(prefix="/results", tags=["results"])
templates = Jinja2Templates(directory="app/templates")


def _artifact_base_dir() -> Path:
    return settings.artifacts_dir.resolve()


def _find_latest_run_dir(base: Path) -> str | None:
    # Run folders are created as job_id (32 hex chars).
    run_pattern = re.compile(r"^[0-9a-f]{32}$")
    candidates: list[Path] = []
    for child in base.iterdir():
        if child.is_dir() and run_pattern.match(child.name):
            candidates.append(child)

    if not candidates:
        return None

    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return latest.name


def _collect_artifact_files(limit: int = 120, run_dir: str | None = None) -> list[dict[str, str | int | bool]]:
    base = _artifact_base_dir()
    if not base.exists():
        return []

    search_root = base / run_dir if run_dir else base
    if not search_root.exists() or not search_root.is_dir():
        return []

    files: list[Path] = [
        p
        for p in search_root.rglob("*")
        if p.is_file()
        and p.name not in _HIDDEN_FILENAMES
        and p.suffix.lower() not in _HIDDEN_SUFFIXES
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    result: list[dict[str, str | int | bool]] = []

    for item in files[:limit]:
        rel_path = item.relative_to(base).as_posix()
        suffix = item.suffix.lower()
        result.append(
            {
                "path": rel_path,
                "filename": item.name,
                "size": item.stat().st_size,
                "is_html": suffix in {".html", ".htm"},
                "is_text": suffix in {".json", ".yml", ".yaml", ".txt", ".log", ".xml", ".csv", ".md"},
            }
        )
    return result


def _resolve_artifact_path(path_value: str) -> Path:
    base = _artifact_base_dir()
    normalized = path_value.strip().replace('\\', '/')
    if normalized.startswith("runtime/artifacts/"):
        normalized = normalized[len("runtime/artifacts/"):]
    elif normalized == "runtime/artifacts":
        normalized = ""

    candidate = (base / normalized).resolve()
    if base != candidate and base not in candidate.parents:
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return candidate


@router.get("/", response_class=HTMLResponse)
def results_page(request: Request) -> HTMLResponse:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    show_all = request.query_params.get("scope") == "all"
    base = _artifact_base_dir()
    latest_run_dir = _find_latest_run_dir(base) if base.exists() else None
    selected_run = None if show_all else latest_run_dir
    artifact_files = _collect_artifact_files(run_dir=selected_run)

    # Fallback: if there are no run folders yet, still show base artifacts.
    if not artifact_files and not show_all:
        artifact_files = _collect_artifact_files(run_dir=None)

    is_htmx = request.headers.get("HX-Request")
    return templates.TemplateResponse(
        request,
        "results/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "language_options": get_language_options(),
            "artifact_files": artifact_files,
            "latest_run_dir": latest_run_dir,
            "show_all": show_all,
            "base_template": "base_partial.html" if is_htmx else "base.html",
        },
    )


@router.get("/render", response_class=HTMLResponse)
def render_artifact(request: Request, path: str) -> HTMLResponse:
    file_path = _resolve_artifact_path(path)
    suffix = file_path.suffix.lower()
    if suffix not in {".html", ".htm", ".json", ".yml", ".yaml", ".txt", ".xml", ".csv", ".md", ".log"}:
        raise HTTPException(status_code=400, detail="This file type cannot be rendered directly")

    if suffix in {".html", ".htm"}:
        rel_path = file_path.relative_to(_artifact_base_dir()).as_posix()
        redirect_path = quote(rel_path, safe="/")
        return RedirectResponse(url=f"/results/artifacts/{redirect_path}", status_code=307)

    text = file_path.read_text(encoding="utf-8", errors="replace")
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    title = file_path.name
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>"
        + title
        + "</title><style>"
        + "body{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,'Liberation Mono',monospace;"
        + "margin:16px;background:#0f172a;color:#e2e8f0;}"
        + "a{display:inline-block;margin-bottom:12px;color:#93c5fd;}"
        + "h2{color:#f8fafc;margin-top:0;}"
        + "pre{white-space:pre-wrap;word-break:break-word;background:#111827;color:#e5e7eb;"
        + "padding:12px;border-radius:8px;border:1px solid #374151;}"
        + "a{display:inline-block;margin-bottom:12px;}</style></head><body>"
        + "<a href='/results/'>Back to Results</a>"
        + f"<h2>{title}</h2><pre>{escaped}</pre></body></html>"
    )
    return HTMLResponse(content=html)


@router.get("/artifacts/{artifact_path:path}")
def serve_artifact_file(artifact_path: str) -> FileResponse:
    file_path = _resolve_artifact_path(artifact_path)
    return FileResponse(path=file_path)


@router.get("/download")
def download_artifact(path: str) -> FileResponse:
    file_path = _resolve_artifact_path(path)
    return FileResponse(path=file_path, filename=file_path.name)
