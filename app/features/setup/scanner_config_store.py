"""Persisted choice of vulnerability scanner engine (Trivy vs ORT).

Stored in the shared key-value settings table. The two engines are mutually
exclusive at analyze time — selecting one skips the other entirely.
"""
from __future__ import annotations

from app.features.jobs.store import job_store

_SCANNER_ENGINE = "scanner.engine"

VALID_ENGINES = ("trivy", "ort")
DEFAULT_ENGINE = "trivy"


def get_scanner_engine() -> str:
    """Return the configured engine, defaulting to Trivy."""
    value = (job_store.get_setting(_SCANNER_ENGINE) or "").strip().lower()
    return value if value in VALID_ENGINES else DEFAULT_ENGINE


def set_scanner_engine(engine: str) -> str:
    """Persist and return the normalized engine choice."""
    normalized = (engine or "").strip().lower()
    if normalized not in VALID_ENGINES:
        normalized = DEFAULT_ENGINE
    job_store.set_setting(_SCANNER_ENGINE, normalized)
    return normalized
