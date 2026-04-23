from __future__ import annotations

import json
from typing import Any

EVENT_LOG = "log"
EVENT_STATUS = "status"
EVENT_AI_REPORT = "ai-report"
EVENT_PING = "ping"

TERMINAL_JOB_STATUSES = frozenset({"success", "failed", "cancelled"})


def make_event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, **payload}


def to_sse_payload(event: dict[str, Any]) -> str:
    event_type = str(event.get("type", "message"))
    payload = json.dumps(event, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def connected_payload() -> str:
    return "event: ping\ndata: connected\n\n"


def heartbeat_payload() -> str:
    return "event: ping\ndata: heartbeat\n\n"
