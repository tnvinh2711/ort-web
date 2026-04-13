from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import settings


@lru_cache(maxsize=2)
def _load_messages(lang: str) -> dict[str, str]:
    base = Path("app") / "i18n"
    file_path = base / f"messages.{lang}.json"
    if not file_path.exists():
        file_path = base / f"messages.{settings.default_language}.json"
    return json.loads(file_path.read_text(encoding="utf-8"))


def translate(lang: str, key: str) -> str:
    messages = _load_messages(lang)
    if key in messages:
        return messages[key]

    fallback = _load_messages(settings.default_language)
    if key in fallback:
        return fallback[key]

    # Handle stale in-memory cache when translation JSON changed but process was not reloaded.
    _load_messages.cache_clear()
    messages = _load_messages(lang)
    if key in messages:
        return messages[key]

    fallback = _load_messages(settings.default_language)
    return fallback.get(key, key)
