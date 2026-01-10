from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import DefaultDict

from .models import RunEvent


class EventBus:
    """
    Minimal in-memory pubsub per run_id.
    We also persist events to disk elsewhere for replay, but this is enough for MVP.
    """

    def __init__(self) -> None:
        self._queues: DefaultDict[str, set[asyncio.Queue[RunEvent]]] = defaultdict(set)

    def subscribe(self, run_id: str) -> asyncio.Queue[RunEvent]:
        q: asyncio.Queue[RunEvent] = asyncio.Queue()
        self._queues[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[RunEvent]) -> None:
        self._queues[run_id].discard(q)
        if not self._queues[run_id]:
            self._queues.pop(run_id, None)

    async def publish(self, event: RunEvent) -> None:
        for q in list(self._queues.get(event.run_id, set())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # For MVP, drop if a client can't keep up.
                pass


EVENT_BUS = EventBus()

