from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class LogStreamHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._subscribers[job_id].append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._subscribers.get(job_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues and job_id in self._subscribers:
            del self._subscribers[job_id]

    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        for queue in self._subscribers.get(job_id, []):
            if queue.full():
                continue
            queue.put_nowait(event)


log_stream_hub = LogStreamHub()
