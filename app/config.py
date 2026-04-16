from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import platform


@dataclass(frozen=True)
class Settings:
    app_name: str = "ORT Local Visualizer"
    default_language: str = "en"
    runtime_dir: Path = Path("runtime")
    jobs_db_file: str = "jobs.sqlite3"
    max_parallel_jobs: int = 2

    @property
    def jobs_db_path(self) -> Path:
        return self.runtime_dir / self.jobs_db_file

    @property
    def logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def artifacts_dir(self) -> Path:
        return self.runtime_dir / "artifacts"

    @property
    def uploads_dir(self) -> Path:
        return self.runtime_dir / "uploads"

    @property
    def bin_dir(self) -> Path:
        return self.runtime_dir / "bin"

    @property
    def ort_config_dir(self) -> Path:
        return Path.home() / ".ort" / "config"

    @property
    def ort_install_dir(self) -> Path:
        system = platform.system()

        if system == "Windows":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                return Path(local_app_data) / "Programs" / "ORT" / "bin"
            return Path.home() / "AppData" / "Local" / "Programs" / "ORT" / "bin"

        if system == "Darwin":
            if Path("/opt/homebrew/bin").exists():
                return Path("/opt/homebrew/bin")
            return Path("/usr/local/bin")

        return Path.home() / ".local" / "bin"


def ensure_runtime_dirs(settings: Settings) -> None:
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.bin_dir.mkdir(parents=True, exist_ok=True)
    settings.ort_config_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
