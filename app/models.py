"""Domain models for ORT job tracking."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    job_id: str
    name: str
    command: str
    work_dir: str
    language: str
    log_file: str
    created_at: str
    status: JobStatus = field(default=JobStatus.PENDING)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    ort_install_path: str | None = None
    project_path: str | None = None
    detected_language: str | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_row(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "command": self.command,
            "work_dir": self.work_dir,
            "language": self.language,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "log_file": self.log_file,
            "ort_install_path": self.ort_install_path,
            "project_path": self.project_path,
            "detected_language": self.detected_language,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Job":
        return cls(
            job_id=row["job_id"],
            name=row["name"],
            command=row["command"],
            work_dir=row["work_dir"],
            language=row["language"],
            status=JobStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
            exit_code=row.get("exit_code"),
            error_message=row.get("error_message"),
            log_file=row["log_file"],
            ort_install_path=row.get("ort_install_path"),
            project_path=row.get("project_path"),
            detected_language=row.get("detected_language"),
        )
