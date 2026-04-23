from __future__ import annotations

from dataclasses import dataclass

from app.features.jobs.store import job_store

_AI_API_KEY = "ai.api_key"
_AI_MODEL = "ai.model"


@dataclass
class VertexConfig:
    api_key: str
    model: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model)


def get_vertex_config() -> VertexConfig:
    return VertexConfig(
        api_key=job_store.get_setting(_AI_API_KEY) or "",
        model=job_store.get_setting(_AI_MODEL) or "grok-4.20-reasoning",
    )


def save_vertex_config(*, api_key: str, model: str) -> None:
    job_store.set_setting(_AI_API_KEY, api_key.strip())
    job_store.set_setting(_AI_MODEL, model.strip() or "grok-4.20-reasoning")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
