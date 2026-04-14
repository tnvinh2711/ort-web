from __future__ import annotations

import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.i18n import translate
from app.models import Job
from app.services.job_queue import job_queue
from app.services.job_store import job_store
from app.services.language_detector import detect_language, get_language_options
from app.services.ort_config import generate_config_yml, generate_repo_config, get_config_yml_path, read_config_yml
from app.services.ort_properties import auto_generate_ort_properties, get_managers_for_language

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _is_install_command(command: str) -> bool:
    return command == "__install_ort__" or command.startswith("__install_ort__::")


def _latest_successful_install() -> Job | None:
    jobs = job_store.list_jobs(limit=100)
    for job in jobs:
        if _is_install_command(job.command) and job.status.value == "success" and job.ort_install_path:
            return job
    return None


def _is_ort_install_healthy(binary_path: Path) -> bool:
    if not binary_path.exists():
        return False
    try:
        result = subprocess.run(
            [str(binary_path), "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _detect_ort_on_disk() -> str | None:
    """Check known locations for a working ORT binary, independent of job history."""
    import shutil as _shutil

    # Candidate paths: default install dir, runtime bin dir, PATH
    candidates: list[Path] = [
        settings.ort_install_dir / "ort",
        settings.bin_dir / "ort",
    ]
    # Also check the .ort-dist deployment under both dirs
    for parent in (settings.ort_install_dir, settings.bin_dir):
        dist_bin = parent / ".ort-dist" / "current" / "bin" / "ort"
        if dist_bin not in candidates:
            candidates.append(dist_bin)

    # shutil.which checks PATH
    which_ort = _shutil.which("ort")
    if which_ort:
        candidates.append(Path(which_ort))

    for path in candidates:
        if _is_ort_install_healthy(path):
            return str(path)
    return None


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


def _pick_existing_result_input() -> str:
    names = {
        "evaluation-result.yml",
        "scan-result.yml",
        "advisor-result.yml",
        "analyzer-result.yml",
        "evaluation-result.json",
        "scan-result.json",
        "advisor-result.json",
        "analyzer-result.json",
    }

    matches = [
        path for path in settings.artifacts_dir.rglob("*")
        if path.is_file() and path.name in names
    ]
    if matches:
        latest = max(matches, key=lambda path: path.stat().st_mtime)
        return str(latest)

    # Fallback keeps command valid syntax even if user has not generated prior results yet.
    return str(settings.artifacts_dir / "analyzer-result.yml")


def _shell(value: str | Path) -> str:
    return shlex.quote(str(value))


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    lang = _lang(request)
    jobs = job_store.list_jobs(limit=20)

    install_job = _latest_successful_install()
    ort_path = install_job.ort_install_path if install_job else None

    if not ort_path:
        ort_path = _detect_ort_on_disk()

    notice_key = request.query_params.get("notice", "")

    # KPI stats
    total_jobs = len(jobs)
    success_jobs = sum(1 for j in jobs if j.status.value == "success")
    failed_jobs = sum(1 for j in jobs if j.status.value == "failed")

    response = templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key: translate(lang, key),
            "jobs": jobs,
            "ort_path": ort_path,
            "notice_key": notice_key,
            "language_options": get_language_options(),
            "config_yml_path": str(get_config_yml_path()),
            "config_yml_content": read_config_yml(),
            "total_jobs": total_jobs,
            "success_jobs": success_jobs,
            "failed_jobs": failed_jobs,
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
    # Check job history first, then fall back to disk detection
    existing_path: str | None = None
    successful_install = _latest_successful_install()
    if successful_install and successful_install.ort_install_path:
        binary_path = Path(successful_install.ort_install_path)
        if _is_ort_install_healthy(binary_path):
            existing_path = successful_install.ort_install_path
    if not existing_path:
        existing_path = _detect_ort_on_disk()

    if existing_path:
        return JSONResponse({"already_installed": True, "path": existing_path})

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
        if os.name == "posix":
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


@router.post("/jobs/analyze-project", response_class=RedirectResponse)
async def analyze_project(
    request: Request,
    project_path: str = Form(...),
    language: str = Form("python"),
    command: str = Form("analyze"),
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

    # Auto-generate config.yml and ort.properties for the detected language
    if language:
        generate_config_yml(language, project_path)
        auto_generate_ort_properties(language)

    # ORT auto-reads ~/.ort/config/config.yml by default, no need for --config flag.
    job_output_dir = (settings.artifacts_dir / job_id).resolve()

    # Generate per-job repository config (.ort.yml) with language-specific excludes.
    # Passed via --repository-configuration-file so we don't modify the user's project.
    repo_config_flag = ""
    if language:
        repo_config_path = job_output_dir / "repo-config.ort.yml"
        generate_repo_config(language, repo_config_path)
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
        name=f"ORT {command.title()} {Path(project_path).name}",
        command=ort_command,
        work_dir=str(work_dir),
        language=ui_language,
        project_path=project_path,
        detected_language=language,
        created_at=Job.now_iso(),
        log_file=str(log_file),
    )
    await job_queue.enqueue(job)

    return JSONResponse({"job_id": job_id})

