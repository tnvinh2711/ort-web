from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import platform


# Default folder for automatically generated Markdown report files.
# Change this value if you want .md reports to be stored in another source-configured folder.
# Example absolute path: DEFAULT_MARKDOWN_REPORTS_DIR = Path("/Users/your-user/ort-markdown-reports")
DEFAULT_MARKDOWN_REPORTS_DIR = Path("runtime") / "markdown-reports"


@dataclass(frozen=True)
class Settings:
    app_name: str = "OSS Guard Local Visualizer"
    default_language: str = "en"
    runtime_dir: Path = Path("runtime")
    # Markdown reports are generated automatically. Change this source value or
    # set ORT_WEB_MARKDOWN_REPORTS_DIR to store them outside the default folder.
    markdown_reports_dir: Path = Path(
        os.environ.get("ORT_WEB_MARKDOWN_REPORTS_DIR", str(DEFAULT_MARKDOWN_REPORTS_DIR))
    )
    jobs_db_file: str = "jobs.sqlite3"
    max_parallel_jobs: int = 2
    # Maximum seconds a single ORT subprocess may run before it is killed.
    # npm install for large projects can run 10-20 min; default gives headroom.
    # Override with ORT_WEB_JOB_TIMEOUT env var.
    ort_job_timeout_seconds: int = int(os.environ.get("ORT_WEB_JOB_TIMEOUT", "1800"))

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
    def npm_cache_dir(self) -> Path:
        """Shared npm cache used by both env_installer and ORT executor.

        Returns an *absolute* path so NPM_CONFIG_CACHE is resolved correctly
        regardless of the working directory npm/ORT is invoked from.
        """
        return (self.runtime_dir / ".npm-cache").resolve()

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
    settings.markdown_reports_dir.mkdir(parents=True, exist_ok=True)
    settings.ort_config_dir.mkdir(parents=True, exist_ok=True)
    settings.npm_cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
