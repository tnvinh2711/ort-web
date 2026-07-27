from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.config import settings
from app.i18n import translate
from app.models import Job
from app.features.jobs.queue import job_queue
from app.features.jobs.store import job_store
from app.features.shared.language_detector import detect_language, get_language_options
from app.features.ort.config import generate_config_yml, generate_repo_config, get_config_yml_path, read_config_yml
from app.features.ort.properties import auto_generate_ort_properties, get_managers_for_language
from app.features.ort.env_installer import detect_install_tasks
from app.features.analysis.vuln_summary import get_vuln_summary
from app.shared_templates import templates

router = APIRouter()

# ---------------------------------------------------------------------------
# In-process caches
# ---------------------------------------------------------------------------

# ORT binary detection (expensive disk probe → cache 10 min)
_ort_cache: dict = {"path": None, "at": 0.0, "valid": False}
_ORT_CACHE_TTL = 600.0

# Dashboard data cache — skip expensive DB + FS queries for repeat loads.
# Invalidated on any job mutation so counts stay accurate.
_dashboard_cache: dict = {"data": None, "at": 0.0}
_DASHBOARD_CACHE_TTL = 2.0


def _invalidate_dashboard_cache() -> None:
    _dashboard_cache["data"] = None


# Patch job_store write methods to invalidate the dashboard cache so the
# next page load always reflects the latest job state.
_original_create = None
_original_update = None
_original_delete = None


def _setup_store_hooks() -> None:
    global _original_create, _original_update, _original_delete
    from app.features.jobs.store import job_store as _store

    if _original_create is not None:
        return  # already patched

    _original_create = _store.create_job
    _original_update = _store.update_job
    _original_delete = _store.delete_job

    def _create(job):
        _invalidate_dashboard_cache()
        return _original_create(job)

    def _update(job):
        _invalidate_dashboard_cache()
        return _original_update(job)

    def _delete(job_id):
        _invalidate_dashboard_cache()
        return _original_delete(job_id)

    _store.create_job = _create
    _store.update_job = _update
    _store.delete_job = _delete


def _invalidate_ort_cache() -> None:
    _ort_cache["valid"] = False


def _is_ort_install_healthy(binary_path: Path) -> bool:
    """Treat the binary's existence as proof of installation.

    We previously ran ``ort --version`` to verify the install, but on slow
    Windows devices the JVM cold start regularly exceeded the 20s subprocess
    timeout, causing the dashboard to falsely report "not installed". A
    truly broken install will surface its error when an actual job runs.
    """
    return binary_path.exists()


def _detect_ort_on_disk() -> str | None:
    """Check known locations for the ORT binary."""
    now = time.monotonic()
    if _ort_cache["valid"] and (now - _ort_cache["at"]) < _ORT_CACHE_TTL:
        return _ort_cache["path"]

    import shutil as _shutil

    # Candidate paths: default install dir, runtime bin dir, PATH.
    # On Windows, ORT launcher is usually ort.bat.
    candidates: list[Path] = [
        settings.ort_install_dir / "ort",
        settings.bin_dir / "ort",
    ]
    if os.name == "nt":
        candidates.extend(
            [
                settings.ort_install_dir / "ort.bat",
                settings.bin_dir / "ort.bat",
            ]
        )

    # Also check the .ort-dist deployment under both dirs
    for parent in (settings.ort_install_dir, settings.bin_dir):
        dist_bin = parent / ".ort-dist" / "current" / "bin" / "ort"
        if dist_bin not in candidates:
            candidates.append(dist_bin)
        if os.name == "nt":
            dist_bat = parent / ".ort-dist" / "current" / "bin" / "ort.bat"
            if dist_bat not in candidates:
                candidates.append(dist_bat)

    # shutil.which checks PATH
    which_ort = _shutil.which("ort")
    if which_ort:
        candidates.append(Path(which_ort))
    if os.name == "nt":
        which_ort_bat = _shutil.which("ort.bat")
        if which_ort_bat:
            candidates.append(Path(which_ort_bat))

    found: str | None = None
    for path in candidates:
        if _is_ort_install_healthy(path):
            found = str(path)
            break

    # Only cache positive detections. Caching None as valid would stick the
    # "not installed" state for 10 minutes if the very first probe happened
    # to lose a race (e.g., file system was momentarily unreadable).
    if found is not None:
        _ort_cache.update({"path": found, "at": now, "valid": True})
    else:
        _ort_cache.update({"path": None, "at": now, "valid": False})
    return found


@router.get("/api/ort-status")
def api_ort_status() -> JSONResponse:
    """Lightweight endpoint to poll ORT install state."""
    path = _detect_ort_on_disk()
    return JSONResponse({"installed": path is not None, "path": path})


@router.get("/api/debug-info")
def api_debug_info() -> JSONResponse:
    """Server-side diagnostic info for debugging blank dashboard issues."""
    import platform
    import sys
    errors: list[str] = []

    db_ok = False
    job_count = 0
    try:
        jobs = job_store.list_jobs(limit=1)
        job_count = len(jobs)
        db_ok = True
    except Exception as exc:
        errors.append(f"DB error: {exc}")

    template_ok = False
    try:
        from app.shared_templates import templates as _t
        _t.get_template("dashboard/index.html")
        template_ok = True
    except Exception as exc:
        errors.append(f"Template error: {exc}")

    config_ok = False
    try:
        from app.features.ort.config import get_config_yml_path, read_config_yml
        get_config_yml_path()
        read_config_yml()
        config_ok = True
    except Exception as exc:
        errors.append(f"Config error: {exc}")

    return JSONResponse({
        "platform": platform.system(),
        "python": sys.version,
        "db_ok": db_ok,
        "job_count": job_count,
        "template_ok": template_ok,
        "config_ok": config_ok,
        "ort_path": _detect_ort_on_disk(),
        "errors": errors,
    })


def _lang(request: Request) -> str:
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
    return lang if lang in {"vi", "en"} else settings.default_language


def _format_datetime(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return value


def render_jobs_list_html(lang: str, page: int = 1, per_page: int = 10) -> str:
    """Render the first page of jobs as an HTML string for SSR embedding."""
    jobs, total = job_store.list_jobs_paged(page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    vuln_summaries = {
        job.job_id: get_vuln_summary(job.vuln_summary_json)
        for job in jobs
        if job.status.value == "success"
    }
    trivy_vuln_summaries = {
        job.job_id: get_vuln_summary(job.trivy_vuln_summary_json)
        for job in jobs
        if job.status.value == "success"
    }
    tpl = templates.env.get_template("dashboard/jobs_list.html")
    return tpl.render(
        lang=lang,
        t=lambda key: translate(lang, key),
        fmt_dt=_format_datetime,
        jobs=jobs,
        page=page,
        total_pages=total_pages,
        total=total,
        vuln_summaries=vuln_summaries,
        trivy_vuln_summaries=trivy_vuln_summaries,
        status_map={
            "pending": translate(lang, "status.pending"),
            "running": translate(lang, "status.running"),
            "success": translate(lang, "status.success"),
            "failed": translate(lang, "status.failed"),
            "cancelled": translate(lang, "status.cancelled"),
        },
    )


_PICK_RESULT_NAMES = {
    "evaluation-result.yml",
    "scan-result.yml",
    "advisor-result.yml",
    "analyzer-result.yml",
    "evaluation-result.json",
    "scan-result.json",
    "advisor-result.json",
    "analyzer-result.json",
}

_PICK_PRUNE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

import re as _re
_RUN_DIR_RE_DASHBOARD = _re.compile(r"^[0-9a-f]{32}$")


def _find_latest_run_dir_local(base: Path) -> str | None:
    """Same logic as results._find_latest_run_dir, kept local to avoid circular import."""
    if not base.exists():
        return None
    latest_name: str | None = None
    latest_mtime: float = -1.0
    try:
        with os.scandir(base) as it:
            for entry in it:
                if not _RUN_DIR_RE_DASHBOARD.match(entry.name):
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


def _scan_for_result_files(root: Path) -> tuple[str | None, float]:
    """Walk ``root`` once with os.walk + DirEntry stat. Returns (latest_path, mtime)."""
    best_path: str | None = None
    best_mtime: float = -1.0
    if not root.exists():
        return None, best_mtime
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PICK_PRUNE_DIRS]
        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    if entry.name not in _PICK_RESULT_NAMES:
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        mtime = entry.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_path = entry.path
        except OSError:
            continue
    return best_path, best_mtime


def _pick_existing_result_input() -> str:
    base = settings.artifacts_dir
    # Short-circuit: scan most recent run dir first (covers ~all real cases).
    latest_run = _find_latest_run_dir_local(base)
    if latest_run is not None:
        path, _mtime = _scan_for_result_files(base / latest_run)
        if path is not None:
            return path

    # Fallback: scan the whole artifacts tree (rare path).
    path, _mtime = _scan_for_result_files(base)
    if path is not None:
        return path

    # Final fallback: keeps command valid syntax even if no prior results yet.
    return str(base / "analyzer-result.yml")


def _shell(value: str | Path) -> str:
    return shlex.quote(str(value))


def _base_tpl(request: Request) -> str:
    return "base_partial.html" if request.headers.get("HX-Request") else "base.html"


def _scan_mode_flags(
    scan_mode: str | None,
    run_analyze: str | None,
    run_scancode: str | None,
) -> tuple[bool, bool]:
    """Return (vulnerability_enabled, license_enabled) for a submitted job."""
    if scan_mode in {"vulnerability", "license", "full"}:
        return (
            scan_mode in {"vulnerability", "full"},
            scan_mode in {"license", "full"},
        )
    return run_analyze == "on", run_scancode == "on"


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    _setup_store_hooks()
    lang = _lang(request)
    notice_key = request.query_params.get("notice", "")

    now = time.monotonic()
    cached = _dashboard_cache["data"]
    if cached is not None and (now - _dashboard_cache["at"]) < _DASHBOARD_CACHE_TTL:
        jobs, ort_path, config_yml_content = cached
    else:
        jobs, ort_path, config_yml_content = await asyncio.gather(
            asyncio.to_thread(job_store.list_jobs, 20),
            asyncio.to_thread(_detect_ort_on_disk),
            asyncio.to_thread(read_config_yml),
        )
        _dashboard_cache["data"] = (jobs, ort_path, config_yml_content)
        _dashboard_cache["at"]   = now

    total_jobs   = len(jobs)
    success_jobs = sum(1 for j in jobs if j.status.value == "success")
    failed_jobs  = sum(1 for j in jobs if j.status.value == "failed")

    # Analyze runs ORT + Trivy together. ORT needs a one-time install (the gate
    # below); Trivy auto-installs at scan time, so readiness tracks ORT only.
    scanner_label = "ORT + Trivy"
    scanner_ready = bool(ort_path)

    def _t(key: str) -> str:
        return translate(lang, key)

    response = templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "request": request,
            "lang": lang,
            "t": _t,
            "jobs": jobs,
            "ort_path": ort_path,
            "notice_key": notice_key,
            "language_options": get_language_options(),
            "config_yml_path": str(get_config_yml_path()),
            "config_yml_content": config_yml_content,
            "total_jobs": total_jobs,
            "success_jobs": success_jobs,
            "failed_jobs": failed_jobs,
            "scanner_label": scanner_label,
            "scanner_ready": scanner_ready,
            "base_template": _base_tpl(request),
        },
    )
    response.set_cookie("lang", lang)
    return response


@router.get("/partials/jobs", response_class=HTMLResponse)
def jobs_partial(request: Request) -> HTMLResponse:
    lang = _lang(request)
    status_filter = request.query_params.get("status", "all").strip().lower()
    query = request.query_params.get("q", "").strip().lower()
    date_from = request.query_params.get("date_from", "").strip()
    date_to = request.query_params.get("date_to", "").strip()
    language_filter = request.query_params.get("detected_language", "").strip().lower()
    page = max(1, int(request.query_params.get("page", "1")))
    per_page = 10

    jobs, total = job_store.list_jobs_paged(
        page=page,
        per_page=per_page,
        status=status_filter,
        query=query,
        date_from=date_from,
        date_to=date_to,
        detected_language=language_filter,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    vuln_summaries = {
        job.job_id: get_vuln_summary(job.vuln_summary_json)
        for job in jobs
        if job.status.value == "success"
    }
    trivy_vuln_summaries = {
        job.job_id: get_vuln_summary(job.trivy_vuln_summary_json)
        for job in jobs
        if job.status.value == "success"
    }

    return templates.TemplateResponse(
        request,
        "dashboard/jobs_list.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "fmt_dt": _format_datetime,
            "jobs": jobs,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "vuln_summaries": vuln_summaries,
            "trivy_vuln_summaries": trivy_vuln_summaries,
            "status_map": {
                "pending": translate(lang, "status.pending"),
                "running": translate(lang, "status.running"),
                "success": translate(lang, "status.success"),
                "failed": translate(lang, "status.failed"),
                "cancelled": translate(lang, "status.cancelled"),
            },
        },
    )


@router.post("/jobs", response_class=RedirectResponse)
async def create_job(
    request: Request,
    command: str = Form(...),
    work_dir: str = Form(""),
    language: str = Form("vi"),
) -> RedirectResponse:
    lang = _lang(request)
    job_id = uuid4().hex
    log_file = settings.logs_dir / f"{job_id}.log"

    job = Job(
        job_id=job_id,
        name=f"ORT Run {job_id[:8]}",
        command=command,
        work_dir=work_dir or str(Path.cwd()),
        language=language,
        created_at=Job.now_iso(),
        log_file=str(log_file),
    )
    await job_queue.enqueue(job)

    response = RedirectResponse(url=f"/?lang={lang}", status_code=303)
    response.set_cookie("lang", lang)
    return response


@router.post("/jobs/install-ort")
async def install_ort(
    request: Request,
    language: str = Form("vi"),
    install_dir: str = Form(""),
) -> JSONResponse:
    existing_path = _detect_ort_on_disk()

    if existing_path:
        return JSONResponse({"already_installed": True, "path": existing_path})

    # Invalidate cache so the post-install status check re-probes disk.
    _invalidate_ort_cache()

    job_id = uuid4().hex
    log_file = settings.logs_dir / f"{job_id}.log"

    custom_install_dir = install_dir.strip()
    command = "__install_ort__"
    if custom_install_dir:
        command = f"__install_ort__::{custom_install_dir}"

    job = Job(
        job_id=job_id,
        name=f"Install ORT {job_id[:8]}",
        command=command,
        work_dir=str(Path.cwd()),
        language=language,
        created_at=Job.now_iso(),
        log_file=str(log_file),
    )
    await job_queue.enqueue(job, ephemeral=True)

    return JSONResponse({"job_id": job_id})


@router.get("/api/pick-directory")
def api_pick_directory() -> JSONResponse:
    try:
        import platform
        system = platform.system()

        if system == "Darwin":
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'POSIX path of (choose folder with prompt "Select folder")',
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return JSONResponse({"selected": None})
            selected = result.stdout.strip()
            return JSONResponse({"selected": selected or None})

        if system == "Windows":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$selected = ''; "
                "try { "
                "  $f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "  $f.Description = 'Select project folder'; "
                "  $f.UseDescriptionForTitle = $true; "
                "  if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
                "    $selected = $f.SelectedPath; "
                "  } "
                "} catch { } "
                "if (-not $selected) { "
                "  try { "
                "    $shell = New-Object -ComObject Shell.Application; "
                "    $folder = $shell.BrowseForFolder(0, 'Select project folder', 0, 0); "
                "    if ($folder) { $selected = $folder.Self.Path } "
                "  } catch { } "
                "} "
                "$selected"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_script],
                capture_output=True,
                text=True,
                check=False,
            )
            selected = result.stdout.strip()
            return JSONResponse({"selected": selected or None})

        if system == "Linux":
            # Try zenity (GNOME) then kdialog (KDE)
            for cmd in [
                ["zenity", "--file-selection", "--directory", "--title=Select project folder"],
                ["kdialog", "--getexistingdirectory", "/"],
            ]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if result.returncode == 0:
                        selected = result.stdout.strip()
                        return JSONResponse({"selected": selected or None})
                except FileNotFoundError:
                    continue

        return JSONResponse(
            {"selected": None, "error": "Folder picker is not supported on this platform yet."},
            status_code=501,
        )
    except Exception as exc:
        return JSONResponse(
            {"selected": None, "error": str(exc)},
            status_code=500,
        )


@router.post("/api/detect-language")
async def api_detect_language(request: Request) -> JSONResponse:
    """Detect programming language of a project folder."""
    try:
        body = await request.json()
        project_path = body.get("project_path", "")
        
        if not project_path:
            return JSONResponse({"detected": None, "error": "No project path provided"}, status_code=400)
        
        detected = detect_language(project_path)
        managers = get_managers_for_language(detected) if detected else []
        return JSONResponse({"detected": detected, "recommended_managers": managers})
    except Exception as exc:
        return JSONResponse({"detected": None, "error": str(exc)}, status_code=400)


@router.get("/debug/env-install", response_class=HTMLResponse)
async def debug_env_install(request: Request) -> HTMLResponse:
    lang = _lang(request)
    return templates.TemplateResponse(
        request,
        "debug/env_install.html",
        {"request": request, "lang": lang, "t": lambda key: translate(lang, key)},
    )


@router.post("/api/env-install/tasks")
async def api_env_install_tasks(request: Request) -> JSONResponse:
    """Detect install tasks for a project path (preview, no execution)."""
    try:
        body = await request.json()
        project_path = body.get("project_path", "").strip()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not project_path:
        return JSONResponse({"error": "project_path required"}, status_code=400)

    from pathlib import Path as _Path
    import shutil as _shutil

    if not _Path(project_path).is_dir():
        return JSONResponse({"error": f"Directory not found: {project_path}"}, status_code=400)

    tasks = await asyncio.to_thread(detect_install_tasks, project_path)

    result = []
    for t in tasks:
        tool_path = next((_shutil.which(c) for c in t["tool_cmds"] if _shutil.which(c)), None)
        result.append({
            "label": t["label"],
            "tool_cmds": t["tool_cmds"],
            "tool_found": tool_path,
            "has_installer": t["install_tool"] is not None,
            "optional": t["optional"],
            "project_cmd": t["project_cmd"],
        })

    return JSONResponse({"tasks": result})


@router.post("/jobs/install-env")
async def install_env(request: Request) -> JSONResponse:
    """Create an __install_env__ job for a project directory."""
    try:
        body = await request.json()
        project_path = body.get("project_path", "").strip()
        lang = body.get("lang", "vi")
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not project_path:
        return JSONResponse({"error": "project_path required"}, status_code=400)

    job_id = uuid4().hex
    log_file = settings.logs_dir / f"{job_id}.log"

    from pathlib import Path as _Path
    job = Job(
        job_id=job_id,
        name=f"Env Install {_Path(project_path).name}",
        command=f"__install_env__::{project_path}",
        work_dir=project_path,
        language=lang,
        project_path=project_path,
        created_at=Job.now_iso(),
        log_file=str(log_file),
    )
    await job_queue.enqueue(job)
    return JSONResponse({"job_id": job_id})


@router.post("/jobs/analyze-project", response_class=RedirectResponse)
async def analyze_project(
    request: Request,
    project_path: str = Form(...),
    language: str = Form("python"),
    command: str = Form("analyze"),
    run_analyze: str | None = Form(None),
    run_scancode: str | None = Form(None),
    scan_mode: str | None = Form(None),
    ui_language: str = Form("vi"),
) -> RedirectResponse:
    """Run ORT command on a project."""
    lang = ui_language
    job_id = uuid4().hex
    log_file = settings.logs_dir / f"{job_id}.log"

    # Build the ORT command
    work_dir = Path(project_path)
    if not work_dir.exists():
        work_dir = Path.cwd()

    # Older clients can still post the two checkbox fields.
    analyze_enabled, scancode_enabled = _scan_mode_flags(
        scan_mode, run_analyze, run_scancode
    )
    if not analyze_enabled and not scancode_enabled:
        return JSONResponse({"error": "Select Analyze or ScanCode before starting."}, status_code=400)

    # Auto-generate config.yml and ort.properties for the detected language
    # Both modes need ORT Analyzer data. ScanCode-only skips only the advisor
    # and Trivy vulnerability stages later in the job queue.
    if language:
        generate_config_yml(language, project_path)
        auto_generate_ort_properties(language, project_path=str(work_dir))

    # ORT auto-reads ~/.ort/config/config.yml by default, no need for --config flag.
    job_output_dir = (settings.artifacts_dir / job_id).resolve()

    # Generate per-job repository config (.ort.yml) with language-specific excludes.
    # Passed via --repository-configuration-file so we don't modify the user's project.
    repo_config_flag = ""
    if language:
        repo_config_path = job_output_dir / "repo-config.ort.yml"
        generate_repo_config(language, repo_config_path, project_path=str(work_dir))
        repo_config_flag = f" --repository-configuration-file {_shell(repo_config_path)}"

    input_result = _pick_existing_result_input()

    # Map command names to ORT commands with common parameters
    ort_commands = {
        "analyze": f"ort -P ort.forceOverwrite=true analyze -i {_shell(project_path)} -o {_shell(job_output_dir)}{repo_config_flag}",
        "scan": f"ort -P ort.forceOverwrite=true scan -i {_shell(input_result)} -o {_shell(job_output_dir)}",
        "evaluate": f"ort -P ort.forceOverwrite=true evaluate -i {_shell(input_result)} -o {_shell(job_output_dir)}",
        "advise": f"ort -P ort.forceOverwrite=true advise -i {_shell(input_result)} -o {_shell(job_output_dir)}",
        "report": f"ort -P ort.forceOverwrite=true report -i {_shell(input_result)} -o {_shell(job_output_dir)} --report-formats StaticHtml,WebApp",
    }
    
    ort_command = ort_commands.get(command, f"ort analyze -i {project_path}")

    job = Job(
        job_id=job_id,
        name=(
            f"ORT {command.title()} {Path(project_path).name}"
            if analyze_enabled
            else f"ScanCode License Scan {Path(project_path).name}"
        ),
        command=ort_command,
        work_dir=str(work_dir),
        language=ui_language,
        project_path=project_path,
        detected_language=language,
        scancode_enabled=scancode_enabled,
        analysis_enabled=analyze_enabled,
        created_at=Job.now_iso(),
        log_file=str(log_file),
    )
    await job_queue.enqueue(job)

    return JSONResponse({"job_id": job_id})
