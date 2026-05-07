from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings
from app.models import Job, JobStatus


class JobStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("pragma journal_mode=wal")
        return con

    def initialize(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                create table if not exists jobs (
                    job_id text primary key,
                    name text not null,
                    command text not null,
                    work_dir text not null,
                    language text not null,
                    status text not null,
                    created_at text not null,
                    started_at text,
                    finished_at text,
                    exit_code integer,
                    error_message text,
                    log_file text not null,
                    ort_install_path text,
                    project_path text,
                    detected_language text,
                    ai_report_status text,
                    ai_report_path text,
                    ai_report_summary text
                )
                """
            )

            con.execute(
                """
                create table if not exists settings (
                    key text primary key,
                    value text not null,
                    updated_at text not null
                )
                """
            )
            
            # Migrate existing tables to add new columns
            try:
                con.execute("pragma table_info(jobs)")
                columns = con.execute("pragma table_info(jobs)").fetchall()
                column_names = {col[1] for col in columns}
                
                if "ort_install_path" not in column_names:
                    con.execute("alter table jobs add column ort_install_path text")
                if "project_path" not in column_names:
                    con.execute("alter table jobs add column project_path text")
                if "detected_language" not in column_names:
                    con.execute("alter table jobs add column detected_language text")
                if "ai_report_status" not in column_names:
                    con.execute("alter table jobs add column ai_report_status text")
                if "ai_report_path" not in column_names:
                    con.execute("alter table jobs add column ai_report_path text")
                if "ai_report_summary" not in column_names:
                    con.execute("alter table jobs add column ai_report_summary text")
            except Exception:
                pass
            
            con.commit()

    def create_job(self, job: Job) -> None:
        with self._connect() as con:
            con.execute(
                """
                insert into jobs (
                    job_id, name, command, work_dir, language, status,
                    created_at, started_at, finished_at, exit_code,
                    error_message, log_file, ort_install_path, project_path,
                    detected_language, ai_report_status, ai_report_path,
                    ai_report_summary
                ) values (
                    :job_id, :name, :command, :work_dir, :language, :status,
                    :created_at, :started_at, :finished_at, :exit_code,
                    :error_message, :log_file, :ort_install_path, :project_path,
                    :detected_language, :ai_report_status, :ai_report_path,
                    :ai_report_summary
                )
                """,
                job.to_row(),
            )
            con.commit()

    def update_job(self, job: Job) -> None:
        with self._connect() as con:
            con.execute(
                """
                update jobs
                set
                    name = :name,
                    command = :command,
                    work_dir = :work_dir,
                    language = :language,
                    status = :status,
                    created_at = :created_at,
                    started_at = :started_at,
                    finished_at = :finished_at,
                    exit_code = :exit_code,
                    error_message = :error_message,
                    log_file = :log_file,
                    ort_install_path = :ort_install_path,
                    project_path = :project_path,
                    detected_language = :detected_language,
                    ai_report_status = :ai_report_status,
                    ai_report_path = :ai_report_path,
                    ai_report_summary = :ai_report_summary
                where job_id = :job_id
                """,
                job.to_row(),
            )
            con.commit()

    def get_setting(self, key: str) -> str | None:
        with self._connect() as con:
            row = con.execute("select value from settings where key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as con:
            con.execute(
                """
                insert into settings (key, value, updated_at)
                values (?, ?, ?)
                on conflict(key) do update set
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, Job.now_iso()),
            )
            con.commit()

    def get_job(self, job_id: str) -> Job | None:
        with self._connect() as con:
            row = con.execute("select * from jobs where job_id = ?", (job_id,)).fetchone()
        return Job.from_row(dict(row)) if row else None

    def list_jobs(self, limit: int = 50) -> list[Job]:
        with self._connect() as con:
            rows = con.execute(
                "select * from jobs order by created_at desc limit ?",
                (limit,),
            ).fetchall()
        return [Job.from_row(dict(row)) for row in rows]

    def list_jobs_paged(
        self,
        *,
        page: int = 1,
        per_page: int = 10,
        status: str = "",
        query: str = "",
        date_from: str = "",
        date_to: str = "",
        detected_language: str = "",
    ) -> tuple[list[Job], int]:
        """Return (jobs, total_count) with filtering and pagination."""
        clauses: list[str] = []
        params: list[str | int] = []

        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if detected_language:
            clauses.append("lower(coalesce(detected_language,'')) = ?")
            params.append(detected_language.lower())
        if query:
            clauses.append(
                "(lower(job_id || name || command || coalesce(project_path,'') || coalesce(detected_language,'')) like ?)"
            )
            params.append(f"%{query.lower()}%")
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at < ?")
            params.append(date_to + "T23:59:59Z" if "T" not in date_to else date_to)

        where = (" where " + " and ".join(clauses)) if clauses else ""

        with self._connect() as con:
            total = con.execute(f"select count(*) from jobs{where}", params).fetchone()[0]
            offset = (page - 1) * per_page
            rows = con.execute(
                f"select * from jobs{where} order by created_at desc limit ? offset ?",
                [*params, per_page, offset],
            ).fetchall()

        return [Job.from_row(dict(r)) for r in rows], total

    def mark_running_jobs_as_failed(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                update jobs
                set status = ?,
                    finished_at = ?,
                    error_message = ?
                where status = ?
                """,
                (
                    JobStatus.FAILED.value,
                    Job.now_iso(),
                    "Service restarted while job was running.",
                    JobStatus.RUNNING.value,
                ),
            )
            con.commit()


job_store = JobStore(settings.jobs_db_path)
