"""Router for the environment setup / ort.properties configuration page."""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from app.config import settings
from app.features.jobs.event_contract import connected_payload, heartbeat_payload, to_sse_payload
from app.features.jobs.log_stream import log_stream_hub
from app.features.setup.vertex_config_store import get_vertex_config, mask_secret, save_vertex_config
from app.i18n import translate
from app.shared_templates import templates

router = APIRouter(prefix="/setup", tags=["setup"])


def _lang(request: Request) -> str:
    lang = (
        request.query_params.get("lang")
        or request.cookies.get("lang")
        or settings.default_language
    )
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


# ── Vertex AI config ───────────────────────────────────────────────────────────

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


# ── Environment status ─────────────────────────────────────────────────────────

def _check_java_ok() -> tuple[bool, str | None, int]:
    from app.features.ort.installer import (
        _find_installed_ort_launcher,
        _find_java_21_home,
    )
    from app.features.ort.java_runtime import ort_required_java

    launcher = _find_installed_ort_launcher()
    required_java = ort_required_java(launcher)
    home = _find_java_21_home(required_java)
    if home:
        return True, str(home), required_java
    return False, None, required_java


def _check_ort_ok() -> tuple[bool, str | None]:
    launcher = settings.ort_install_dir / ("ort.bat" if os.name == "nt" else "ort")
    if launcher.exists():
        return True, str(launcher)
    found = shutil.which("ort")
    if found:
        return True, found
    return False, None


def _check_trivy_ok() -> tuple[bool, str | None]:
    from app.features.trivy.installer import _which_trivy
    found = _which_trivy()
    return (True, found) if found else (False, None)


def _check_trivy_db_ok() -> bool:
    db_dir = settings.trivy_cache_dir / "db"
    return (db_dir / "trivy.db").exists() or (db_dir / "metadata.json").exists()


@router.get("/api/env-status")
async def api_env_status() -> JSONResponse:
    java_ok, java_path, java_required = await asyncio.to_thread(_check_java_ok)
    ort_ok, ort_path = await asyncio.to_thread(_check_ort_ok)
    trivy_ok, trivy_path = await asyncio.to_thread(_check_trivy_ok)
    trivy_db_ok = await asyncio.to_thread(_check_trivy_db_ok)
    return JSONResponse({
        "java_ok": java_ok,
        "java_path": java_path,
        "java_required": java_required,
        "ort_ok": ort_ok,
        "ort_path": ort_path,
        "trivy_ok": trivy_ok,
        "trivy_path": trivy_path,
        "trivy_db_ok": trivy_db_ok,
    })


# ── Install tasks ──────────────────────────────────────────────────────────────

async def _download_trivy_db(log) -> None:
    from app.features.trivy.installer import _which_trivy
    trivy_path = _which_trivy()
    if not trivy_path:
        await log("[trivy-db] Trivy binary not found — install Trivy first.\n")
        return

    cache_dir = settings.trivy_cache_dir
    await log(f"[trivy-db] Downloading Trivy DB to {cache_dir} …\n")

    env = os.environ.copy()
    env["TRIVY_CACHE_DIR"] = str(cache_dir)

    cmd = [
        trivy_path, "image", "--download-db-only",
        "--cache-dir", str(cache_dir), "--no-progress",
    ]
    await log(f"[trivy-db] $ {' '.join(str(c) for c in cmd)}\n")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        await log(raw.decode("utf-8", errors="replace"))
    rc = await proc.wait()
    if rc == 0:
        await log("[trivy-db] Database downloaded successfully.\n")
    else:
        await log(f"[trivy-db] Download failed (exit code {rc}).\n")


async def _run_install(session_id: str, tool: str) -> None:
    # Give the client ~300 ms to open the EventSource before we emit the first log.
    await asyncio.sleep(0.3)

    async def log(line: str) -> None:
        msg = line if line.endswith("\n") else line + "\n"
        await log_stream_hub.publish(session_id, {"type": "log", "line": msg})

    try:
        if tool == "java":
            from app.features.ort.installer import (
                _ensure_java_version,
                _find_installed_ort_launcher,
            )
            from app.features.ort.java_runtime import ort_required_java

            required_java = ort_required_java(_find_installed_ort_launcher())
            java_home = await _ensure_java_version(
                required_java,
                log,
            )
            if not java_home:
                await log_stream_hub.publish(
                    session_id,
                    {
                        "type": "error",
                        "message": (
                            f"Java {required_java}+ installation failed or the "
                            "installed JDK could not be detected."
                        ),
                    },
                )
                return

            # Make the newly selected JDK available to jobs immediately,
            # without requiring another web-server restart.
            os.environ["ORT_WEB_JAVA_HOME"] = str(java_home)
            await log(f"Java {required_java}+ is ready at {java_home}.\n")

        elif tool == "ort":
            # install_ort_local publishes to log_stream_hub(session_id) internally
            from app.features.ort.installer import install_ort_local
            with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
                tmp_log = Path(f.name)
            exit_code, _ = await install_ort_local(session_id, tmp_log)
            try:
                tmp_log.unlink(missing_ok=True)
            except Exception:
                pass
            if exit_code != 0:
                await log_stream_hub.publish(
                    session_id,
                    {"type": "error", "message": "ORT install failed — see log above."},
                )
                return

        elif tool == "trivy":
            from app.features.trivy.installer import ensure_trivy
            result = await ensure_trivy(log)
            if not result:
                await log_stream_hub.publish(
                    session_id,
                    {"type": "error", "message": "Trivy install failed — see log above."},
                )
                return

        elif tool == "trivy_db":
            await _download_trivy_db(log)

        await log_stream_hub.publish(session_id, {"type": "done"})

    except Exception as exc:
        await log_stream_hub.publish(
            session_id,
            {"type": "error", "message": str(exc)},
        )


@router.post("/api/install/{tool}")
async def api_install_tool(tool: str, background_tasks: BackgroundTasks) -> JSONResponse:
    if tool not in ("java", "ort", "trivy", "trivy_db"):
        return JSONResponse({"error": f"Unknown tool: {tool}"}, status_code=400)
    session_id = str(uuid4())
    background_tasks.add_task(_run_install, session_id, tool)
    return JSONResponse({"session_id": session_id})


@router.get("/api/install/{session_id}/events")
async def api_install_events(session_id: str) -> StreamingResponse:
    queue = log_stream_hub.subscribe(session_id)

    async def stream():
        try:
            yield connected_payload()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield to_sse_payload(event)
                    if event.get("type") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    yield heartbeat_payload()
        finally:
            log_stream_hub.unsubscribe(session_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
