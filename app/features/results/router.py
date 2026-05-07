from __future__ import annotations

import asyncio
import heapq
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.config import settings
from app.i18n import translate
from app.features.shared.language_detector import get_language_options
from app.features.dashboard.router import render_jobs_list_html
from app.shared_templates import templates

# Files to hide from the results listing.
_HIDDEN_FILENAMES = {"analyzer-report.html", "analyzer-report-web-app.html"}
_HIDDEN_SUFFIXES = {".xml", ".yml", ".yaml"}
_MARKDOWN_REPORTS_PREFIX = "__markdown_reports__"

# Directories to skip when walking artifact trees (Phase 3).
# Conservative list — only common build/cache dirs that never contain ORT outputs.
_PRUNE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".gradle", ".idea", ".vscode",
}

router = APIRouter(prefix="/results", tags=["results"])


def _artifact_base_dir() -> Path:
    return settings.artifacts_dir.resolve()


def _markdown_reports_base_dir() -> Path:
    return settings.markdown_reports_dir.resolve()


_RUN_DIR_RE = re.compile(r"^[0-9a-f]{32}$")


def _find_latest_run_dir(base: Path) -> str | None:
    # Single os.scandir pass — DirEntry caches stat (1 syscall vs 2 with iterdir+stat).
    if not base.exists():
        return None
    latest_name: str | None = None
    latest_mtime: float = -1.0
    try:
        with os.scandir(base) as it:
            for entry in it:
                if not _RUN_DIR_RE.match(entry.name):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_name = entry.name
    except OSError:
        return None
    return latest_name


def _walk_files(root: Path, *, suffix_filter: set[str] | None = None):
    """Yield (Path, st_mtime, st_size) for files under root, pruning known build dirs.

    Uses os.walk with in-place dir pruning + DirEntry-cached stat to avoid the
    per-entry stat() syscalls that Path.rglob makes (3-10x slower on Windows NTFS).
    """
    for dirpath, dirnames, _filenames in os.walk(root):
        # Prune unwanted dirs in-place so os.walk doesn't descend into them.
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if entry.name in _HIDDEN_FILENAMES:
                        continue
                    name = entry.name
                    suf = ""
                    dot = name.rfind(".")
                    if dot >= 0:
                        suf = name[dot:].lower()
                    if suffix_filter is not None and suf not in suffix_filter:
                        continue
                    if suf in _HIDDEN_SUFFIXES:
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    yield Path(entry.path), st.st_mtime, st.st_size, suf
        except OSError:
            continue


# Phase 4c: cache artifact scans by (search_root, parent_mtime) with short TTL.
# Invalidates automatically when the run directory's mtime changes (new file written).
_artifact_cache: dict[tuple[str, str | None, int], tuple[float, float, list]] = {}
_ARTIFACT_CACHE_TTL = 30.0  # seconds


def _collect_artifact_files(limit: int = 120, run_dir: str | None = None) -> list[dict[str, str | int | bool]]:
    base = _artifact_base_dir()
    if not base.exists():
        return []

    search_root = base / run_dir if run_dir else base
    if not search_root.exists() or not search_root.is_dir():
        return []

    # Cache lookup: keyed by (root, run_dir, limit) + validated against parent mtime + TTL.
    try:
        parent_mtime = search_root.stat().st_mtime
    except OSError:
        parent_mtime = 0.0
    cache_key = (str(base), run_dir, limit)
    now = time.monotonic()
    cached = _artifact_cache.get(cache_key)
    if cached is not None:
        cached_mtime, cached_at, cached_result = cached
        if cached_mtime == parent_mtime and (now - cached_at) < _ARTIFACT_CACHE_TTL:
            return cached_result

    # heap of (mtime, sequence, Path, size, suffix) — keep top-`limit` by mtime desc.
    # Use heapq.nsmallest on negative mtime so the smallest-negative wins (i.e. largest mtime).
    seq = 0
    candidates: list[tuple[float, int, Path, int, str]] = []
    for path, mtime, size, suf in _walk_files(search_root):
        candidates.append((-mtime, seq, path, size, suf))
        seq += 1

    top = heapq.nsmallest(limit, candidates)

    result: list[dict[str, str | int | bool]] = []
    for _neg_mtime, _idx, path, size, suf in top:
        try:
            rel_path = path.relative_to(base).as_posix()
        except ValueError:
            continue
        result.append(
            {
                "path": rel_path,
                "filename": path.name,
                "size": size,
                "is_html": suf in {".html", ".htm"},
                "is_text": suf in {".json", ".yml", ".yaml", ".txt", ".log", ".xml", ".csv", ".md"},
            }
        )

    markdown_base = _markdown_reports_base_dir()
    if markdown_base != base:
        markdown_root = markdown_base / run_dir if run_dir else markdown_base
        if markdown_root.exists() and markdown_root.is_dir():
            md_seq = 0
            md_candidates: list[tuple[float, int, Path, int]] = []
            for path, mtime, size, _suf in _walk_files(markdown_root, suffix_filter={".md"}):
                md_candidates.append((-mtime, md_seq, path, size))
                md_seq += 1
            md_top = heapq.nsmallest(max(0, limit - len(result)), md_candidates)
            for _neg, _idx, path, size in md_top:
                try:
                    rel_path = path.relative_to(markdown_base).as_posix()
                except ValueError:
                    continue
                result.append(
                    {
                        "path": f"{_MARKDOWN_REPORTS_PREFIX}/{rel_path}",
                        "filename": path.name,
                        "size": size,
                        "is_html": False,
                        "is_text": True,
                    }
                )

    _artifact_cache[cache_key] = (parent_mtime, now, result)
    return result


def _resolve_artifact_path(path_value: str) -> Path:
    base = _artifact_base_dir()
    normalized = path_value.strip().replace('\\', '/')
    if normalized.startswith(f"{_MARKDOWN_REPORTS_PREFIX}/"):
        markdown_base = _markdown_reports_base_dir()
        markdown_rel = normalized[len(_MARKDOWN_REPORTS_PREFIX) + 1:]
        candidate = (markdown_base / markdown_rel).resolve()
        if markdown_base != candidate and markdown_base not in candidate.parents:
            raise HTTPException(status_code=400, detail="Invalid Markdown report path")
        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(status_code=404, detail="Markdown report file not found")
        return candidate

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


def _safe_render_jobs_list(lang: str) -> str:
    try:
        return render_jobs_list_html(lang)
    except Exception:
        return ""


@router.get("/", response_class=HTMLResponse)
async def results_page(request: Request) -> HTMLResponse:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    is_htmx = request.headers.get("HX-Request")
    initial_jobs_html = await asyncio.to_thread(_safe_render_jobs_list, lang)
    return templates.TemplateResponse(
        request,
        "results/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "language_options": get_language_options(),
            "initial_jobs_html": initial_jobs_html,
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
