from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class VertexAIError(RuntimeError):
    pass


@dataclass
class VertexResponse:
    raw_text: str
    parsed: dict[str, Any]


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise VertexAIError("Model output is not valid JSON.")

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VertexAIError(f"Cannot parse model JSON output: {exc}") from exc


def build_prompt(
    *,
    error_message: str,
    package_manager: str,
    dependencies: list[dict[str, str]],
    vulnerabilities: list[dict[str, str]],
) -> str:
    payload = {
        "error_message": error_message,
        "package_manager": package_manager,
        "dependencies": dependencies,
        "vulnerabilities": vulnerabilities,
    }

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "needs_manual_review": {"type": "boolean"},
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "package": {"type": "string"},
                        "current_version": {"type": "string"},
                        "suggested_exact_version": {"type": "string"},
                        "suggested_safe_range": {"type": "string"},
                        "rationale_short": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "package",
                        "current_version",
                        "suggested_exact_version",
                        "suggested_safe_range",
                        "rationale_short",
                        "confidence",
                    ],
                },
            },
        },
        "required": ["summary", "needs_manual_review", "suggestions"],
    }

    return (
        "You are a dependency remediation assistant. "
        "Given ORT vulnerability context, suggest safer dependency versions that reduce breakage risk. "
        "Rules: return JSON only, do not include markdown, do not hallucinate package names, "
        "prioritize packages that appear in vulnerability entries, and always try to provide exact version + safe range. "
        "Only set needs_manual_review=true with empty suggestions if there is truly no actionable vulnerable package in input.\n\n"
        f"Input context:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"Output JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
    )


def suggest_versions(
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout: int = 60,
) -> VertexResponse:
    endpoint = "https://api.x.ai/v1/responses"

    body = {
        "model": model,
        "input": prompt,
        "max_output_tokens": 2048,
        "temperature": 0.2,
    }

    req = request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    raw: str | None = None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except (TimeoutError, socket.timeout) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.8)
                continue
            raise VertexAIError(f"xAI request timed out after {timeout}s") from exc
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise VertexAIError(f"xAI HTTP {exc.code}: {details[:400]}") from exc
        except error.URLError as exc:
            raise VertexAIError(f"xAI request failed: {exc.reason}") from exc

    if raw is None:
        raise VertexAIError(f"xAI request failed unexpectedly: {last_error}")

    try:
        data = json.loads(raw)

        text = str(data.get("output_text") or "").strip()
        if not text:
            output_items = data.get("output") if isinstance(data.get("output"), list) else []
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                content_items = item.get("content") if isinstance(item.get("content"), list) else []
                for content in content_items:
                    if not isinstance(content, dict):
                        continue
                    if content.get("type") in {"output_text", "text"}:
                        text_value = content.get("text")
                        if isinstance(text_value, str) and text_value.strip():
                            text = text_value.strip()
                            break
                if text:
                    break

        if not text:
            raise VertexAIError("xAI response has no text content.")

        parsed = _extract_json_object(text)
        return VertexResponse(raw_text=text, parsed=parsed)
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
        raise VertexAIError(f"Cannot decode xAI response: {exc}") from exc
