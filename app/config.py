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

    # Scanners that Trivy runs in `trivy fs`. Override with ORT_WEB_TRIVY_SCANNERS
    # (comma-separated, e.g. "vuln" or "vuln,secret,misconfig").
    trivy_scanners: str = os.environ.get("ORT_WEB_TRIVY_SCANNERS", "vuln,secret,misconfig")
    # Severity filter passed to Trivy. Empty string = report all severities.
    trivy_severity: str = os.environ.get("ORT_WEB_TRIVY_SEVERITY", "HIGH,CRITICAL")
    # Offline mode (default ON): add --offline-scan --skip-db-update
    # --skip-check-update so Trivy never touches the network and relies entirely
    # on the cache dir's pre-populated DB. Disable with ORT_WEB_TRIVY_OFFLINE=0
    # to let Trivy download/refresh its DB online.
    trivy_offline: bool = os.environ.get("ORT_WEB_TRIVY_OFFLINE", "1").strip() == "1"

    @property
    def trivy_cache_dir(self) -> Path:
        """Trivy cache dir holding the vulnerability DB (db/trivy.db + metadata).

        Defaults to ``~/Trivy`` (the pre-populated offline DB location). Override
        with ORT_WEB_TRIVY_CACHE_DIR. Absolute so it resolves regardless of the
        directory Trivy is invoked from.
        """
        override = os.environ.get("ORT_WEB_TRIVY_CACHE_DIR")
        if override:
            return Path(override).resolve()
        return (Path.home() / "Trivy").resolve()

    @property
    def npm_cache_dir(self) -> Path:
        """Shared npm cache used by both env_installer and ORT executor.

        Returns an *absolute* path so NPM_CONFIG_CACHE is resolved correctly
        regardless of the working directory npm/ORT is invoked from.
        """
        return (self.runtime_dir / ".npm-cache").resolve()

    @property
    def gradle_user_home_dir(self) -> Path:
        """Persistent Gradle wrapper, dependency, and Tooling API cache."""
        override = os.environ.get("ORT_WEB_GRADLE_USER_HOME")
        if override:
            return Path(override).expanduser().resolve()
        return (self.runtime_dir / ".gradle").resolve()

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
    settings.gradle_user_home_dir.mkdir(parents=True, exist_ok=True)
    settings.trivy_cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
